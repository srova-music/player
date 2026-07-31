import logging
import sys
import os
import json
import socket
import threading
import time
import re
import random
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from gi.repository import GLib

from core.logging import setup_logging
from core.constants import PlayMode, AudioLatency, AlsaMmapRealtimePriority
from app import app_init_runtime
from local_library import LocalLibraryBusyError, LocalLibraryIndex, local_library_rebuild_running
import network_music
from network_root_state import add_exact_managed_root, remove_exact_managed_root

logger = logging.getLogger(__name__)

APP_INSTANCE = None
HTTP_PORT    = 8081
HTTP_HOST    = "0.0.0.0"

_APP_ROOT = os.path.abspath(os.path.join(_src_dir, os.pardir))
_SROVA_STATE_DIR = os.environ.get("SROVA_STATE_DIR", "/var/lib/srova")
_SROVA_ENV_FILE = os.environ.get("SROVA_ENV_FILE", os.path.join(_SROVA_STATE_DIR, "srova.env"))
_SROVA_LEGACY_ENV_FILE = os.path.join(_APP_ROOT, "srova.env")
_SROVA_SERVICE_NAME = os.environ.get("SROVA_SERVICE_NAME", "srova.service")
_SROVA_LAN_ADDRESS_ENV = "SROVA_LAN_ADDRESS"
_SROVA_RESTART_REQUIRED = False
_SROVA_PENDING_PORT = None
_SROVA_PROCESS_STARTED_AT = time.time()
_SROVA_RESTART_EXIT_CODE = 75
_SROVA_RESTART_LOCK = threading.Lock()
_SROVA_RESTART_SCHEDULED = False
_NETWORK_DISCOVERY_CACHE = {"at": 0.0, "payload": None}
_NETWORK_DISCOVERY_CACHE_SECONDS = 20.0
_NETWORK_ROOT_STATE_LOCK = threading.RLock()
_NETWORK_MANAGED_ID_RE = re.compile(r"^(?:nfs|smb)-[0-9a-f]{12}$")

# ALSA output configuration -- overridden by --alsa-driver / --alsa-device CLI args.
# Pi 4 (Fosi ZD3):  ALSA     / hw:0,0
# Pi 5 (FiiO QX13): alsa_mmap / hw:0,0
ALSA_DRIVER = "ALSA"
ALSA_DEVICE = "hw:0,0"
ALSA_DAC_NAME = ""

_AUDIO_OUTPUT_FILE = os.path.join(
    os.path.expanduser("~"), ".config", "hiresti", "audio_output.json"
)
_AUDIO_OUTPUT_LOCK = threading.Lock()
_VALID_ALSA_DRIVERS = ("ALSA", "alsa_mmap")
_DAC_NOT_DETECTED_ERROR = "dac_not_detected"
_DAC_NOT_DETECTED_MESSAGE = "DAC not detected. Please connect or switch on your DAC before playback."

PLAY_QUEUE = []
QUEUE_INDEX = 0
PLAY_QUEUE_PENDING_AFTER_CONTEXT = False

LAST_STATE = None
LAST_STATE_TIME = 0

CURRENT_STREAM_INFO = {
    "sample_rate": None,
    "bit_depth":   None,
    "codec":       None
}

# Stores enough context for other devices to restore the player bar on load
PLAYBACK_START_TIME = None   # wall-clock time when current track started
IDLE_RELEASE_TIMER  = None   # timer thread to release DAC after pause inactivity
PAUSED_PLAYBACK_POSITION = 0.0
PAUSED_PLAYBACK_TRACK_ID = None
PAUSED_PIPELINE_RELEASED = False
QUEUE_OVERRUN_ADVANCE_GUARD = ""
QUEUE_AUTO_ADVANCE_ARMED_KEY = ""
QUEUE_AUTO_ADVANCE_DISARMED_BY_USER = False
QUEUE_OVERRUN_DIAGNOSTIC_GUARD = ""

CURRENT_CONTEXT = {
    "track_id":    None,
    "title":       None,
    "artist":      None,
    "artist_id":   None,
    "cover":       None,
    "duration":    0,
    "album":       None,
    "album_id":    None,
    "context_title": None,
    "context_type":  None,
    "context_id":    None
}
LOCAL_PLAYBACK_ACTIVE = False
LOCAL_PLAYBACK_CONTEXT = {}
LOCAL_CUE_BOUNDARY_TOKEN = 0

REPEAT_MODE = "off"
SHUFFLE_ON  = False
ORIGINAL_QUEUE = []

RADIO_MODE    = False
CURRENT_RADIO = None  # dict mirror of the station currently playing, or None

CURRENT_RADIO_METADATA = {}  # populated by the active metadata resolver
CURRENT_RADIO_ARTWORK = {}   # dynamic now-playing cover art resolved from radio metadata
_RADIO_SCROBBLE_CURRENT_KEY = None
_RADIO_START_LOCK = threading.RLock()
_RADIO_STARTING = False
_RADIO_START_TOKEN = 0
_RADIO_LAST_START_AT = 0.0
_RADIO_MIN_RESTART_INTERVAL = 3.0
_RADIO_SWITCHING_UNTIL = 0.0
_ONLINE_STATE_LOCK = threading.Lock()
_ONLINE_STATE = {
    "online": True,
    "checked_at": 0.0,
    "method": "tcp_connect",
    "target": "",
    "confidence": "unknown",
    "error": "",
}
_ONLINE_STATE_TTL = 10.0
_ONLINE_STATE_TCP_TARGETS = (("1.1.1.1", 53), ("8.8.8.8", 53), ("9.9.9.9", 53))
_ONLINE_STATE_TCP_TIMEOUT = 0.75

_RADIO_ART_LOCK = threading.RLock()
_RADIO_ART_CACHE = {}        # "artist\0title" -> {"data": dict, "ts": float}
_RADIO_ART_IN_FLIGHT = set()
TTL_RADIO_ART = 7 * 86400
TTL_RADIO_ART_MISS = 1800


from radio_metadata import EasyRadioWebsiteResolver, IcecastJsonResolver, RadioParadiseIcyMetadataResolver, OggVorbisResolver, ResolverRegistry, probe_flac_technical_info
# EasyRadio stays first.  Radio Paradise FLAC "m" streams need ICY metadata
# blocks requested on a side-channel connection, before the generic Ogg reader.
_METADATA_REGISTRY = ResolverRegistry([EasyRadioWebsiteResolver, IcecastJsonResolver, RadioParadiseIcyMetadataResolver, OggVorbisResolver])


def _is_radio_paradise_metadata_stream(stream_url):
    text = str(stream_url or "").lower()
    return (
        "radioparadise.com" in text
        and (
            "flacm" in text
            or "mellow-flacm" in text
            or "rock-flacm" in text
            or "global-flacm" in text
        )
    )

# Track metadata cache: str(track_id) -> {id,title,artist,cover,duration,quality}
# Populated by POST queue endpoints; used by GET /tidal/queue and persisted to disk.
PLAY_QUEUE_META_CACHE = {}

# Protects queue globals from concurrent mutation by HTTP handler threads.
_QUEUE_LOCK = threading.Lock()

# TIDAL track and stream URL resolution performs network I/O. Keep that work
# away from the GLib main loop and use a generation token so a late result
# cannot override a newer playback, pause, stop, or source-selection request.
_TIDAL_STREAM_RESOLUTION_LOCK = threading.Lock()
_TIDAL_STREAM_RESOLUTION_GENERATION = 0
_TIDAL_STREAM_RESOLUTION_PENDING = None


def _begin_tidal_stream_resolution(index, track_id):
    global _TIDAL_STREAM_RESOLUTION_GENERATION
    global _TIDAL_STREAM_RESOLUTION_PENDING

    expected_index = int(index)
    expected_track_id = str(track_id)
    with _TIDAL_STREAM_RESOLUTION_LOCK:
        _TIDAL_STREAM_RESOLUTION_GENERATION += 1
        token = _TIDAL_STREAM_RESOLUTION_GENERATION
        _TIDAL_STREAM_RESOLUTION_PENDING = (
            token,
            expected_index,
            expected_track_id,
        )
    return token


def _invalidate_tidal_stream_resolution(reason):
    global _TIDAL_STREAM_RESOLUTION_GENERATION
    global _TIDAL_STREAM_RESOLUTION_PENDING

    with _TIDAL_STREAM_RESOLUTION_LOCK:
        had_pending = _TIDAL_STREAM_RESOLUTION_PENDING is not None
        _TIDAL_STREAM_RESOLUTION_GENERATION += 1
        _TIDAL_STREAM_RESOLUTION_PENDING = None

    if had_pending:
        logger.info(
            "Pending TIDAL stream resolution invalidated: %s",
            reason,
        )


def _tidal_stream_resolution_matches(
    token,
    expected_index,
    expected_track_id,
    consume=False,
):
    global _TIDAL_STREAM_RESOLUTION_PENDING

    expected = (
        int(token),
        int(expected_index),
        str(expected_track_id),
    )

    with _TIDAL_STREAM_RESOLUTION_LOCK:
        if _TIDAL_STREAM_RESOLUTION_PENDING != expected:
            return False

        with _QUEUE_LOCK:
            queue_matches = (
                0 <= expected[1] < len(PLAY_QUEUE)
                and QUEUE_INDEX == expected[1]
                and str(PLAY_QUEUE[expected[1]]) == expected[2]
            )

        if not queue_matches or consume:
            _TIDAL_STREAM_RESOLUTION_PENDING = None

        return queue_matches

# Temporary/test-only local playback allowlist. This is intentionally separate
# from TIDAL queue state and does not implement a local library scanner.
_LOCAL_TEST_ROOTS_ENV = "SROVA_LOCAL_TEST_ROOTS"
_NETWORK_MUSIC_ROOTS_ENV = "SROVA_NETWORK_MUSIC_ROOTS"
_NETWORK_ROOT_MIGRATION_ENV = "SROVA_NETWORK_ROOT_MIGRATION"
_NETWORK_ROOT_MIGRATION_COMPLETE = "rc3-v1-complete"
_NETWORK_ROOT_MIGRATION_PENDING = "rc3-v1-pending"
_NETWORK_FILESYSTEM_TYPES = frozenset(("nfs", "nfs4", "cifs", "smb3"))
_NETWORK_AUTOFS_WAKE_TIMEOUT_SECONDS = 1.5
_NETWORK_AUTOMOUNT_SCAN_ERROR = "network_music_autofs_scan_blocked"
_NETWORK_AUTOMOUNT_SCAN_MESSAGE = (
    "This Network Music folder uses systemd automount/autofs. "
    "Scanning this type of mount is blocked because it can "
    "hang the scanner. Please mount the share as a normal NFS/SMB path, then scan again."
)
_LOCAL_ARTWORK_LOOKUP_DISABLED_ENV = "SROVA_LOCAL_LIBRARY_DISABLE_ARTWORK_LOOKUP"
_LOCAL_TEST_AUDIO_EXTENSIONS = {
    ".aac", ".aif", ".aiff", ".alac", ".ape", ".flac", ".m4a",
    ".mp3", ".ogg", ".opus", ".wav", ".wave",
}
_LOCAL_TEST_CODEC_BY_EXT = {
    ".aac": "AAC",
    ".aif": "AIFF",
    ".aiff": "AIFF",
    ".alac": "ALAC",
    ".ape": "APE",
    ".flac": "FLAC",
    ".m4a": "ALAC/AAC",
    ".mp3": "MP3",
    ".ogg": "OGG",
    ".opus": "Opus",
    ".wav": "WAV",
    ".wave": "WAV",
}

# Persistence file in XDG data home.
_QUEUE_FILE = os.path.join(
    os.path.expanduser("~"), ".local", "share", "hiresti", "hiresti_queue.json"
)

_APP_SETTINGS_FILE = os.path.join(
    os.path.expanduser("~"), ".config", "hiresti", "srova_settings.json"
)
_APP_SETTINGS_LOCK = threading.Lock()
_APP_SETTINGS = {
    "tidal_infinite_play": False,
    "tidal_infinite_play_mode": "similar_artist",
}

# Scrobble credentials file
_SCROBBLE_FILE = os.path.join(
    os.path.expanduser("~"), ".local", "share", "hiresti", "hiresti_scrobble.json"
)

# Stores the OAuth future between /login/start and /login/poll
_OAUTH_FUTURE = None
_OAUTH_LOCK   = threading.Lock()


# =========================================================================
# In-memory TTL cache
# =========================================================================

_CACHE      = {}
_CACHE_LOCK = threading.Lock()

TTL_HOME      = 120
TTL_TRACKS    = 300
TTL_SEARCH    = 60
TTL_PLAYLISTS = 120
TTL_FEATURED  = 600   # chart / new-releases data changes slowly

# Home-page sections the user has opted to hide (case-insensitive substring match).
_HOME_EXCLUDED_TITLES = (
    "spotlighted uploads",
    "albums you'll enjoy",
    "uploads for you",
    "because you listened to",
    "because you liked",
)

def _home_section_excluded(title):
    tl = str(title or "").strip().lower()
    for ex in _HOME_EXCLUDED_TITLES:
        if ex in tl:
            return True
    return False


def cache_get(key):
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        if time.time() - entry["ts"] > entry["ttl"]:
            del _CACHE[key]
            return None
        return entry["data"]


def cache_set(key, data, ttl):
    with _CACHE_LOCK:
        _CACHE[key] = {"data": data, "ts": time.time(), "ttl": ttl}


def cache_invalidate(prefix=None):
    with _CACHE_LOCK:
        if prefix is None:
            _CACHE.clear()
        else:
            keys = [k for k in _CACHE if k.startswith(prefix)]
            for k in keys:
                del _CACHE[k]


def cache_stats():
    with _CACHE_LOCK:
        now  = time.time()
        live = {k: round(v["ttl"] - (now - v["ts"]), 1)
                for k, v in _CACHE.items()
                if now - v["ts"] <= v["ttl"]}
        return {"entries": len(live), "keys": live}



# =========================================================================
# Network / remote access helpers
# =========================================================================

def _parse_env_file(path):
    data = {}
    try:
        if not os.path.exists(path):
            return data
        with open(path, "r") as f:
            for line in f:
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    data[key] = value
    except Exception as e:
        logger.warning("Could not read SROVA env file %s: %s", path, e)
    return data


def _srova_env_candidates():
    candidates = [_SROVA_ENV_FILE, _SROVA_LEGACY_ENV_FILE]
    seen = set()
    result = []
    for path in candidates:
        text = str(path or "").strip()
        if not text:
            continue
        real = os.path.abspath(text)
        if real in seen:
            continue
        seen.add(real)
        result.append(text)
    return result


def _load_srova_env_values():
    merged = {}
    for path in reversed(_srova_env_candidates()):
        if os.path.exists(path):
            merged.update(_parse_env_file(path))
    return merged


def _saved_env_or_process_value(key):
    """Return saved configuration even when its explicit value is empty."""
    saved_env = _load_srova_env_values()
    if key in saved_env:
        return str(saved_env.get(key, "") or "")
    return str(os.environ.get(key, "") or "")


def _load_srova_env_port():
    env_port = str(os.environ.get("SROVA_PORT", "") or "").strip()
    file_port = str(_load_srova_env_values().get("SROVA_PORT", "") or "").strip()
    port_text = env_port or file_port
    if not port_text:
        return None
    try:
        port = int(port_text)
        return _validate_web_port(port)
    except Exception as e:
        logger.warning("Ignoring invalid SROVA_PORT value %r: %s", port_text, e)
        return None


def _load_srova_env_lan_address():
    env_lan = str(os.environ.get(_SROVA_LAN_ADDRESS_ENV, "") or "").strip()
    file_lan = str(_load_srova_env_values().get(_SROVA_LAN_ADDRESS_ENV, "") or "").strip()
    lan_address = env_lan or file_lan
    if not lan_address:
        return None
    try:
        return _validate_lan_address(lan_address)
    except Exception as e:
        logger.warning("Ignoring invalid %s value %r: %s", _SROVA_LAN_ADDRESS_ENV, lan_address, e)
        return None


def _validate_lan_address(address):
    value = str(address or "").strip()
    if not value:
        raise ValueError("LAN address is required.")
    if len(value) > 255:
        raise ValueError("LAN address is too long.")
    if re.search(r"\s", value):
        raise ValueError("LAN address cannot contain spaces.")
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or "/" in value or "?" in value or "#" in value:
        raise ValueError("Enter only the LAN address, without http://, port, or path.")
    return value


def _validate_web_port(port):
    try:
        value = int(port)
    except Exception:
        raise ValueError("Port must be a number.")
    if value < 1024 or value > 65535:
        raise ValueError("Port must be between 1024 and 65535.")
    return value


def _write_srova_env_port(port):
    port = _validate_web_port(port)
    env = _load_srova_env_values()
    env["SROVA_PORT"] = str(port)
    tmp = _SROVA_ENV_FILE + ".tmp"
    os.makedirs(os.path.dirname(_SROVA_ENV_FILE), exist_ok=True)
    ordered_keys = ["SROVA_PORT"] + sorted(k for k in env if k != "SROVA_PORT")
    with open(tmp, "w") as f:
        f.write("# SROVA runtime environment\n")
        f.write("# Edited by the SROVA Settings Remote Access section.\n")
        for key in ordered_keys:
            value = str(env.get(key, ""))
            f.write(f"{key}={value}\n")
    os.replace(tmp, _SROVA_ENV_FILE)
    return port


def _write_srova_remote_target(lan_address, port):
    lan_address = _validate_lan_address(lan_address)
    port = _validate_web_port(port)
    _write_srova_env_values({
        _SROVA_LAN_ADDRESS_ENV: lan_address,
        "SROVA_PORT": str(port),
    }, "Remote Access")
    return lan_address, port


_LOCAL_LIBRARY_BLOCKED_ROOTS = (
    "/", "/etc", "/proc", "/sys", "/dev", "/usr", "/bin", "/sbin", "/var", "/home"
)
_LOCAL_BROWSE_ROOTS_ENV = "SROVA_LOCAL_BROWSE_ROOTS"
_LOCAL_BROWSE_DEFAULT_ROOTS = ("/DATA", "/mnt", "/media", "/srv")
_LOCAL_BROWSE_MAX_DIRS = 500
_LOCAL_LIBRARY_MOUNT_HINT_ROOTS = ("/DATA", "/mnt", "/media", "/srv")


def _local_library_mount_expected(path):
    root = os.path.realpath(os.path.expanduser(str(path or "").strip()))
    if not root or root == "/":
        return False
    for hint in _LOCAL_LIBRARY_MOUNT_HINT_ROOTS:
        hint_real = os.path.realpath(hint)
        if root == hint_real or _path_inside_root(root, hint_real):
            return True
    return False


def _local_library_mount_point(path):
    root = os.path.realpath(os.path.expanduser(str(path or "").strip()))
    if not root:
        return None
    probe = root
    if not os.path.exists(probe):
        probe = os.path.dirname(probe)
    if os.path.isfile(probe):
        probe = os.path.dirname(probe)
    while probe and probe != "/":
        try:
            if os.path.ismount(probe):
                return probe
        except Exception:
            pass
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return "/" if os.path.ismount("/") else None


def _local_library_path_diagnostics(path):
    root = os.path.realpath(os.path.expanduser(str(path or "").strip()))
    exists = bool(root and os.path.exists(root))
    is_directory = bool(exists and os.path.isdir(root))
    readable = bool(is_directory and os.access(root, os.R_OK | os.X_OK))
    mount_point = _local_library_mount_point(root) if root else None
    mounted = bool(mount_point and mount_point != "/")
    mount_expected = _local_library_mount_expected(root)
    mount_warning = ""
    if mount_expected and not mounted:
        mount_warning = (
            "This looks like a USB/SMB/NFS-style library path, but SROVA could not "
            "detect a mounted parent below /DATA, /mnt, /media, or /srv. If the drive "
            "or share is not mounted, the scan may see an empty folder."
        )
    return {
        "path": root,
        "exists": exists,
        "directory": is_directory,
        "readable": readable,
        "mounted": mounted,
        "mount_point": mount_point,
        "mount_expected": mount_expected,
        "mount_warning": mount_warning,
    }


def _write_srova_env_values(values, edited_by):
    env = _load_srova_env_values()
    for key, value in values.items():
        env[str(key)] = str(value)
    tmp = _SROVA_ENV_FILE + ".tmp"
    os.makedirs(os.path.dirname(_SROVA_ENV_FILE), exist_ok=True)
    preferred = [
        _SROVA_LAN_ADDRESS_ENV,
        "SROVA_PORT",
        _LOCAL_TEST_ROOTS_ENV,
        _NETWORK_MUSIC_ROOTS_ENV,
        _NETWORK_ROOT_MIGRATION_ENV,
    ]
    ordered_keys = [k for k in preferred if k in env]
    ordered_keys.extend(sorted(k for k in env if k not in ordered_keys))
    with open(tmp, "w") as f:
        f.write("# SROVA runtime environment\n")
        f.write("# Edited by the SROVA Settings %s section.\n" % edited_by)
        for key in ordered_keys:
            value = str(env.get(key, ""))
            f.write(f"{key}={value}\n")
    os.replace(tmp, _SROVA_ENV_FILE)


def _validate_local_library_root(raw_path):
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("Music folder path is required.")
    if not os.path.isabs(os.path.expanduser(text)):
        raise ValueError("Music folder path must be absolute.")
    root = os.path.realpath(os.path.expanduser(text))
    if root == "/":
        raise ValueError("Music folder path cannot be the filesystem root.")

    diag = _local_library_path_diagnostics(root)
    if not diag.get("exists"):
        raise ValueError(
            "Music folder path does not exist. If this is a USB, SMB, or NFS library, "
            "mount it first and then try again."
        )
    if not diag.get("directory"):
        raise ValueError("Music folder path must be a directory.")
    if not diag.get("readable"):
        raise ValueError(
            "Music folder path exists but is not readable/searchable by the SROVA service user."
        )

    for blocked in _LOCAL_LIBRARY_BLOCKED_ROOTS:
        blocked_real = os.path.realpath(blocked)
        if blocked_real == "/":
            if root == blocked_real:
                raise ValueError("Music folder path is inside a protected system folder.")
            continue
        if root == blocked_real or _path_inside_root(root, blocked_real):
            raise ValueError("Music folder path is inside a protected system folder.")
    return root


def _local_library_browse_roots():
    raw = os.environ.get(_LOCAL_BROWSE_ROOTS_ENV, "")
    candidates = raw.split(os.pathsep) if raw.strip() else list(_LOCAL_BROWSE_DEFAULT_ROOTS)
    roots = []
    for item in candidates:
        text = str(item or "").strip()
        if not text or not os.path.isabs(os.path.expanduser(text)):
            continue
        root = os.path.realpath(os.path.expanduser(text))
        if root == "/" or root in roots:
            continue
        if not os.path.exists(root) or not os.path.isdir(root):
            continue
        diag = _local_library_path_diagnostics(root)
        # Top-level browse roots like /DATA, /mnt, /media and /srv are just
        # entry points. They do not need warning copy unless the user selects
        # a real library folder under them.
        roots.append({
            "name": root,
            "path": root,
            "exists": bool(diag.get("exists")),
            "readable": bool(diag.get("readable")),
            "mounted": bool(diag.get("mounted")),
            "mount_point": diag.get("mount_point"),
            "mount_expected": bool(diag.get("mount_expected")),
            "mount_warning": "",
        })
    return roots


def _local_library_allowed_browse_roots():
    return [
        item["path"] for item in _local_library_browse_roots()
        if item.get("exists") and item.get("readable")
    ]


def _validate_local_library_browse_path(raw_path):
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("Folder path is required.")
    if not os.path.isabs(os.path.expanduser(text)):
        raise ValueError("Folder path must be absolute.")
    path = os.path.realpath(os.path.expanduser(text))
    if path == "/":
        raise ValueError("Browsing filesystem root is not allowed.")
    roots = _local_library_allowed_browse_roots()
    if not any(_path_inside_root(path, root) for root in roots):
        raise PermissionError("Folder is outside allowed browse roots.")
    if not os.path.exists(path):
        raise ValueError("Folder does not exist.")
    if not os.path.isdir(path):
        raise ValueError("Path is not a directory.")
    if not os.access(path, os.R_OK | os.X_OK):
        raise PermissionError("Folder is not readable by SROVA.")
    return path, roots


def _local_library_browse_payload(raw_path=""):
    text = str(raw_path or "").strip()
    if not text:
        return {
            "ok": True,
            "path": None,
            "roots": _local_library_browse_roots(),
        }

    path, roots = _validate_local_library_browse_path(text)
    parent = None
    parent_path = os.path.realpath(os.path.dirname(path))
    if parent_path and parent_path != path:
        if any(path != root and _path_inside_root(parent_path, root) for root in roots):
            parent = parent_path

    directories = []
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    except PermissionError:
        raise PermissionError("Folder is not readable by SROVA.")
    for entry in entries:
        if len(directories) >= _LOCAL_BROWSE_MAX_DIRS:
            break
        try:
            if entry.name.startswith("."):
                continue
            if not entry.is_dir(follow_symlinks=True):
                continue
            child_path = os.path.realpath(entry.path)
            if not any(_path_inside_root(child_path, root) for root in roots):
                continue
            if not os.access(child_path, os.R_OK | os.X_OK):
                continue
            directories.append({
                "name": entry.name,
                "path": child_path,
                "readable": True,
            })
        except Exception:
            continue
    return {
        "ok": True,
        "path": path,
        "parent": parent,
        "directories": directories,
        "limit": _LOCAL_BROWSE_MAX_DIRS,
        "diagnostics": _local_library_path_diagnostics(path),
    }


def _local_library_roots_payload(payload):
    raw_roots = []
    raw_network_roots = []
    if isinstance(payload, dict):
        if isinstance(payload.get("roots"), list):
            raw_roots = payload.get("roots")
        elif payload.get("root") is not None:
            raw_roots = [payload.get("root")]
        if isinstance(payload.get("network_roots"), list):
            raw_network_roots = payload.get("network_roots")

    roots = []
    diagnostics = []
    warnings = []
    for raw in raw_roots:
        root = _validate_local_library_root(raw)
        if root not in roots:
            roots.append(root)
            diag = _local_library_path_diagnostics(root)
            diagnostics.append(diag)
            warning = diag.get("mount_warning") or ""
            if warning and warning not in warnings:
                warnings.append(warning)

    network_roots = []
    for raw in raw_network_roots:
        root = _validate_local_library_root(raw)
        if root not in roots:
            raise ValueError("Network music folder must also be in the saved music folders list.")
        if root not in network_roots:
            network_roots.append(root)

    if not roots:
        raise ValueError("At least one music folder path is required.")

    roots_value = os.pathsep.join(roots)
    network_roots_value = os.pathsep.join(network_roots)
    _write_srova_env_values({
        _LOCAL_TEST_ROOTS_ENV: roots_value,
        _NETWORK_MUSIC_ROOTS_ENV: network_roots_value,
        _NETWORK_ROOT_MIGRATION_ENV: _NETWORK_ROOT_MIGRATION_COMPLETE,
    }, "Local Music Library")
    os.environ[_LOCAL_TEST_ROOTS_ENV] = roots_value
    os.environ[_NETWORK_MUSIC_ROOTS_ENV] = network_roots_value
    os.environ[_NETWORK_ROOT_MIGRATION_ENV] = _NETWORK_ROOT_MIGRATION_COMPLETE

    message = "Music folders saved. Press Scan Now to update the SROVA index."
    if warnings:
        message += " Mount check: " + " ".join(warnings)
    return {
        "ok": True,
        "roots": roots,
        "network_roots": network_roots,
        "local_roots": [root for root in roots if root not in network_roots],
        "diagnostics": diagnostics,
        "warnings": warnings,
        "message": message,
        "persistent": True,
        "runtime": True,
    }


def _network_music_error(message):
    return {"ok": False, "error": str(message or "Network Music request failed.")[:500]}


def _network_music_text(value, field, required=True, max_len=255):
    text = str(value or "")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError(f"{field} contains unsupported characters.")
    text = text.strip()
    if required and not text:
        raise ValueError(f"{field} is required.")
    if len(text) > max_len:
        raise ValueError(f"{field} is too long.")
    return text


def _network_music_discover_payload(refresh=False):
    now = time.time()
    if not refresh:
        cached_at = float(_NETWORK_DISCOVERY_CACHE.get("at") or 0)
        cached = _NETWORK_DISCOVERY_CACHE.get("payload")
        if cached and now - cached_at < _NETWORK_DISCOVERY_CACHE_SECONDS:
            data = dict(cached)
            data["cached"] = True
            return data
    try:
        data = network_music.discover_servers()
        data["cached"] = False
        _NETWORK_DISCOVERY_CACHE["at"] = now
        _NETWORK_DISCOVERY_CACHE["payload"] = data
        return data
    except Exception as e:
        logger.warning("network music discovery failed: %s", e)
        return _network_music_error("Network share discovery failed.")


def _network_music_shares_payload(payload):
    try:
        host = network_music.validate_host(payload.get("host"))
        protocol = _network_music_text(payload.get("protocol"), "protocol").lower()
        credentials = payload.get("credentials") if isinstance(payload.get("credentials"), dict) else {}
        creds = {
            "username": _network_music_text(credentials.get("username"), "username", required=False),
            "password": network_music.validate_password(credentials.get("password")),
            "domain": _network_music_text(credentials.get("domain"), "domain", required=False),
        }
        data = network_music.list_shares(host, protocol, credentials=creds)
        if isinstance(data, dict):
            data.pop("password", None)
        return data
    except Exception as e:
        logger.warning("network music share listing failed: %s", e)
        return _network_music_error(e)


def _network_music_mounts_payload():
    return network_music.call_mount_helper("list", {}, timeout=8.0)


def _network_music_connect_payload(payload):
    try:
        protocol = _network_music_text(payload.get("protocol"), "protocol").lower()
        helper_payload = {
            "protocol": protocol,
            "host": network_music.validate_host(payload.get("host")),
        }
        if protocol == "nfs":
            helper_payload["export"] = _network_music_text(payload.get("export"), "export", max_len=1024)
        elif protocol == "smb":
            helper_payload["share"] = _network_music_text(payload.get("share"), "share")
            helper_payload["username"] = _network_music_text(payload.get("username"), "username", required=False)
            helper_payload["password"] = network_music.validate_password(payload.get("password"))
            helper_payload["domain"] = _network_music_text(payload.get("domain"), "domain", required=False)
        else:
            raise ValueError("Unsupported network share protocol.")
        with _NETWORK_ROOT_STATE_LOCK:
            data = network_music.call_mount_helper("connect", helper_payload, timeout=20.0)
            if not isinstance(data, dict) or not data.get("ok"):
                return data
            data.pop("password", None)
            mount_id, mount_path = _managed_mount_identity(data.get("id"), data.get("mount_path"))
            original_local, original_network = _snapshot_music_root_values()
            state = add_exact_managed_root(original_local, original_network, mount_path)
            try:
                _persist_music_root_values(state["local_value"], state["network_value"],
                                           "Managed Network Music Connect")
            except Exception:
                if data.get("created_mount") is True:
                    rollback = network_music.call_mount_helper("disconnect", {"id": mount_id}, timeout=15.0)
                    if not isinstance(rollback, dict) or not rollback.get("ok"):
                        return {
                            "ok": False,
                            "partial_failure": True,
                            "id": mount_id,
                            "mount_path": mount_path,
                            "error": "The share is mounted, but SROVA could not save it or roll the mount back. Disconnect it before retrying.",
                        }
                    return _network_music_error(
                        "The share connection was rolled back because SROVA could not save the music folders."
                    )
                return {
                    "ok": False,
                    "partial_failure": True,
                    "id": mount_id,
                    "mount_path": mount_path,
                    "mounted": True,
                    "error": "The existing mount was left connected, but SROVA could not save it as a music folder.",
                }
            data.update({key: state[key] for key in ("roots", "network_roots", "local_roots")})
            return data
    except Exception as e:
        logger.warning("network music connect failed (%s)", type(e).__name__)
        return _network_music_error("Network Music connect failed.")


def _network_music_disconnect_payload(payload):
    try:
        mount_id, mount_path = _managed_mount_identity(payload.get("id"))
        with _NETWORK_ROOT_STATE_LOCK:
            original_local, original_network = _snapshot_music_root_values()
            state = remove_exact_managed_root(original_local, original_network, mount_path)
            _persist_music_root_values(state["local_value"], state["network_value"],
                                       "Managed Network Music Disconnect")
            data = network_music.call_mount_helper("disconnect", {"id": mount_id}, timeout=15.0)
            if not isinstance(data, dict) or not data.get("ok"):
                try:
                    _persist_music_root_values(original_local, original_network,
                                               "Managed Network Music Disconnect Rollback")
                except Exception:
                    logger.error("network music disconnect root rollback failed")
                    return {
                        "ok": False,
                        "partial_failure": True,
                        "id": mount_id,
                        "mount_path": mount_path,
                        "error": "The mount was not disconnected and SROVA could not restore its saved folder state.",
                    }
                return data
            returned_id, returned_path = _managed_mount_identity(data.get("id"), data.get("mount_path"))
            if returned_id != mount_id or returned_path != mount_path:
                raise ValueError("Mount helper returned an unexpected managed mount.")
            data.update({key: state[key] for key in ("roots", "network_roots", "local_roots")})
            return data
    except Exception as e:
        logger.warning("network music disconnect failed (%s)", type(e).__name__)
        return _network_music_error("Network Music disconnect failed.")


def _managed_mount_identity(mount_id, mount_path=None):
    mid = str(mount_id or "").strip()
    if not _NETWORK_MANAGED_ID_RE.fullmatch(mid):
        raise ValueError("Managed mount id is invalid.")
    expected = f"/mnt/srova-network/{mid}"
    if mount_path is not None and str(mount_path) != expected:
        raise ValueError("Managed mount path is invalid.")
    return mid, expected


def _snapshot_music_root_values():
    saved_env = _load_srova_env_values()

    def current(key):
        if key in saved_env:
            return str(saved_env.get(key, "") or "")
        return str(os.environ.get(key, "") or "")

    return current(_LOCAL_TEST_ROOTS_ENV), current(_NETWORK_MUSIC_ROOTS_ENV)


def _persist_music_root_values(local_value, network_value, edited_by):
    values = {
        _LOCAL_TEST_ROOTS_ENV: str(local_value),
        _NETWORK_MUSIC_ROOTS_ENV: str(network_value),
        _NETWORK_ROOT_MIGRATION_ENV: _NETWORK_ROOT_MIGRATION_COMPLETE,
    }
    _write_srova_env_values(values, edited_by)
    os.environ.update(values)


def _saved_music_root_values(key):
    """Parse configured roots without statting or resolving the filesystem."""
    raw = _saved_env_or_process_value(key)
    roots = []
    for item in raw.split(os.pathsep):
        item = str(item or "").strip()
        if not item:
            continue
        root = os.path.normpath(
            os.path.abspath(os.path.expanduser(item))
        )
        if root and root not in roots:
            roots.append(root)
    return roots


def _configured_music_root_state():
    roots = _saved_music_root_values(_LOCAL_TEST_ROOTS_ENV)
    network_roots = [
        root for root in _saved_music_root_values(_NETWORK_MUSIC_ROOTS_ENV)
        if root in roots
    ]
    return {
        "roots": roots,
        "network_roots": network_roots,
        "local_roots": [root for root in roots if root not in network_roots],
    }


def _legacy_music_root_kind(root):
    """Classify only roots that are provably managed, network, or local."""
    text = os.path.normpath(os.path.abspath(os.path.expanduser(str(root or "").strip())))
    if not text or text == os.sep:
        return "pending"

    managed_parent = os.path.normpath("/mnt/srova-network")
    if os.path.dirname(text) == managed_parent:
        managed_id = os.path.basename(text)
        if _NETWORK_MANAGED_ID_RE.fullmatch(managed_id):
            return "network"

    autofs_mount = _autofs_mount_for_path(text)
    if autofs_mount:
        if _network_mount_entry_for_path(text):
            return "network"
        _wake_exact_autofs_path(text)
        if _network_mount_entry_for_path(text):
            return "network"
        return "pending"

    backing = _active_non_autofs_mount_for_path(text)
    if backing:
        fstype = str(backing.get("fstype") or "").lower()
        if fstype in _NETWORK_FILESYSTEM_TYPES:
            return "network"

        mount_point = os.path.normpath(
            str(backing.get("mount_point") or "")
        )
        if mount_point and mount_point != os.sep:
            return "local"

    try:
        exists = os.path.isdir(text)
    except Exception:
        exists = False

    # A plain directory such as /mnt/music on the root filesystem is not
    # enough evidence to call the root local. It may be an unavailable
    # legacy USB/NFS/SMB mountpoint, so retain it as pending.
    if exists and not _local_library_mount_expected(text):
        return "local"
    return "pending"


def _migrate_legacy_network_root_state():
    """Classify RC1 combined roots without remounting, deleting, or rescanning."""
    with _NETWORK_ROOT_STATE_LOCK:
        saved = _load_srova_env_values()
        marker = str(saved.get(_NETWORK_ROOT_MIGRATION_ENV, "") or "").strip()

        if marker == _NETWORK_ROOT_MIGRATION_COMPLETE:
            return {
                "changed": False,
                "status": marker,
                "network_roots": _saved_music_root_values(_NETWORK_MUSIC_ROOTS_ENV),
                "pending_roots": [],
            }

        # RC2 already wrote this key explicitly. Preserve that classification
        # and merely mark the migration schema complete.
        if (
            marker != _NETWORK_ROOT_MIGRATION_PENDING
            and _NETWORK_MUSIC_ROOTS_ENV in saved
        ):
            _write_srova_env_values(
                {_NETWORK_ROOT_MIGRATION_ENV: _NETWORK_ROOT_MIGRATION_COMPLETE},
                "Network Music Root Migration",
            )
            os.environ[_NETWORK_ROOT_MIGRATION_ENV] = _NETWORK_ROOT_MIGRATION_COMPLETE
            logger.info("Preserved existing explicit Network Music root classification")
            return {
                "changed": True,
                "status": _NETWORK_ROOT_MIGRATION_COMPLETE,
                "network_roots": _saved_music_root_values(_NETWORK_MUSIC_ROOTS_ENV),
                "pending_roots": [],
            }

        roots = _saved_music_root_values(_LOCAL_TEST_ROOTS_ENV)
        network_roots = [
            root for root in _saved_music_root_values(_NETWORK_MUSIC_ROOTS_ENV)
            if root in roots
        ]
        pending = []
        classified = []

        for root in roots:
            if root in network_roots:
                continue
            kind = _legacy_music_root_kind(root)
            if kind == "network":
                network_roots.append(root)
                classified.append(root)
            elif kind == "pending":
                pending.append(root)

        status = (
            _NETWORK_ROOT_MIGRATION_PENDING
            if pending
            else _NETWORK_ROOT_MIGRATION_COMPLETE
        )
        network_value = os.pathsep.join(network_roots)
        old_network_value = str(saved.get(_NETWORK_MUSIC_ROOTS_ENV, "") or "")
        changed = (
            old_network_value != network_value
            or marker != status
        )

        if changed:
            updates = {
                _NETWORK_MUSIC_ROOTS_ENV: network_value,
                _NETWORK_ROOT_MIGRATION_ENV: status,
            }
            _write_srova_env_values(updates, "Network Music Root Migration")
            os.environ.update(updates)

        if classified:
            logger.info("Classified legacy Network Music root(s): %s", classified)
        if pending:
            logger.warning(
                "Legacy music root classification remains pending; no root was removed: %s",
                pending,
            )

        return {
            "changed": changed,
            "status": status,
            "network_roots": network_roots,
            "classified_roots": classified,
            "pending_roots": pending,
        }


def _remove_disconnected_managed_root(mount_path):
    """Remove one exact helper-returned path while allowing empty root values."""
    text = str(mount_path or "").strip()
    if not text or not os.path.isabs(text):
        raise ValueError("Disconnected managed mount path is invalid.")
    state = remove_exact_managed_root(
        os.pathsep.join(_saved_music_root_values(_LOCAL_TEST_ROOTS_ENV)),
        os.pathsep.join(_saved_music_root_values(_NETWORK_MUSIC_ROOTS_ENV)),
        text,
    )
    local_value = state["local_value"]
    network_value = state["network_value"]
    _persist_music_root_values(local_value, network_value, "Managed Network Music Disconnect")
    return {key: state[key] for key in ("roots", "network_roots", "local_roots")}


def _get_lan_ip():
    candidates = []
    try:
        host_ip = socket.gethostbyname(socket.gethostname())
        candidates.append(host_ip)
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # Documentation TEST-NET-2 address; no packet has to be sent.
            sock.connect(("198.51.100.1", 1))
            candidates.append(sock.getsockname()[0])
    except Exception:
        pass
    for ip in candidates:
        token = str(ip or "").strip()
        if not token or token.startswith("127."):
            continue
        return token
    return None


def _get_hostname_short():
    try:
        hostname = socket.gethostname()
    except Exception:
        return None
    token = str(hostname or "").strip().split(".", 1)[0].strip()
    return token or None


def _network_payload(port=None, restart_required=None):
    detected_lan_ip = _get_lan_ip()
    hostname_short = _get_hostname_short()
    saved_lan_address = _load_srova_env_lan_address()
    lan_address = saved_lan_address or detected_lan_ip or "127.0.0.1"
    active_port = int(port or HTTP_PORT)
    url = f"http://{lan_address}:{active_port}"
    return {
        "lan_ip": lan_address,
        "lan_address": lan_address,
        "lan_address_persisted": bool(saved_lan_address),
        "detected_lan_ip": detected_lan_ip or "Not detected",
        "lan_ip_detected": bool(saved_lan_address or detected_lan_ip),
        "hostname_short": hostname_short or "",
        "port": active_port,
        "url": url,
        "restart_supported": True,
        "restart_required": bool(_SROVA_RESTART_REQUIRED if restart_required is None else restart_required),
        "restart_method": "systemd",
        "service_name": _SROVA_SERVICE_NAME,
        "process_started_at": _SROVA_PROCESS_STARTED_AT,
        "env_file": _SROVA_ENV_FILE,
        "pending_port": _SROVA_PENDING_PORT,
    }


def _restart_srova_service_later(delay=0.35):
    """Exit deliberately so systemd Restart=on-failure starts a new process."""
    global _SROVA_RESTART_SCHEDULED

    with _SROVA_RESTART_LOCK:
        if _SROVA_RESTART_SCHEDULED:
            logger.info("SROVA restart is already scheduled")
            return False
        _SROVA_RESTART_SCHEDULED = True

    def _restart():
        try:
            logger.info(
                "Preparing controlled SROVA self-restart with exit code %d",
                _SROVA_RESTART_EXIT_CODE,
            )

            try:
                _invalidate_tidal_stream_resolution("service-restart")
            except Exception as exc:
                logger.debug(
                    "Restart TIDAL resolution cancellation failed: %s",
                    exc,
                )

            try:
                _cancel_pending_radio_start()
            except Exception as exc:
                logger.debug(
                    "Restart Radio cancellation failed: %s",
                    exc,
                )

            try:
                _METADATA_REGISTRY.detach()
            except Exception as exc:
                logger.debug(
                    "Restart metadata detach failed: %s",
                    exc,
                )

            try:
                _cancel_idle_release()
            except Exception as exc:
                logger.debug(
                    "Restart idle-release cancellation failed: %s",
                    exc,
                )

            try:
                cancel_scrobble()
            except Exception as exc:
                logger.debug(
                    "Restart scrobble cancellation failed: %s",
                    exc,
                )

            try:
                player = (
                    APP_INSTANCE.player
                    if APP_INSTANCE is not None
                    else None
                )
                if player is not None and hasattr(player, "stop"):
                    player.stop()
            except Exception as exc:
                logger.warning(
                    "Restart player stop failed safely: %s",
                    exc,
                )

            try:
                save_thread = save_queue()
                if save_thread is not None:
                    save_thread.join(timeout=2.0)
                    if save_thread.is_alive():
                        logger.warning(
                            "Queue persistence was still running at restart exit"
                        )
            except Exception as exc:
                logger.warning(
                    "Restart queue persistence failed safely: %s",
                    exc,
                )
        except Exception as exc:
            logger.warning(
                "Controlled restart cleanup failed safely: %s",
                exc,
            )
        finally:
            logger.warning(
                "Exiting SROVA with code %d for systemd-managed restart",
                _SROVA_RESTART_EXIT_CODE,
            )
            try:
                logging.shutdown()
            finally:
                os._exit(_SROVA_RESTART_EXIT_CODE)

    try:
        timer = threading.Timer(float(delay), _restart)
        timer.daemon = True
        timer.start()
    except Exception:
        with _SROVA_RESTART_LOCK:
            _SROVA_RESTART_SCHEDULED = False
        raise

    return True

# =========================================================================
# Audio output preference / DAC discovery
# =========================================================================

def _audio_output_path():
    os.makedirs(os.path.dirname(_AUDIO_OUTPUT_FILE), exist_ok=True)
    return _AUDIO_OUTPUT_FILE


def _validate_audio_driver(driver):
    driver = str(driver or "").strip()
    if driver not in _VALID_ALSA_DRIVERS:
        raise ValueError("Unsupported ALSA driver")
    return driver


def _validate_audio_device(device):
    device = str(device or "").strip()
    if not re.match(r"^(hw|plughw):\d+,\d+$", device):
        raise ValueError("Unsupported ALSA device. Use hw:X,Y or plughw:X,Y.")
    return device


def _normalise_dac_name(name):
    return re.sub(r"\s+", " ", str(name or "").strip())[:120]


class AudioOutputUnavailable(Exception):
    def __init__(self, detail=""):
        super().__init__(detail or _DAC_NOT_DETECTED_MESSAGE)
        self.detail = detail or ""

    def to_payload(self):
        return {
            "ok": False,
            "error": _DAC_NOT_DETECTED_ERROR,
            "message": _DAC_NOT_DETECTED_MESSAGE,
        }


def _load_audio_output_config():
    """Load saved audio output preference without touching the active player.

    Returns True when a saved preference was successfully loaded. The return
    value is used during startup so Settings-saved DAC choices survive systemd
    restarts even when older service files still pass --alsa-driver/--alsa-device.
    """
    global ALSA_DRIVER, ALSA_DEVICE, ALSA_DAC_NAME
    try:
        path = _audio_output_path()
        if not os.path.exists(path):
            return False
        with open(path, "r") as f:
            data = json.load(f)
        driver = _validate_audio_driver(data.get("alsa_driver", ALSA_DRIVER))
        device = _validate_audio_device(data.get("alsa_device", ALSA_DEVICE))
        name   = _normalise_dac_name(data.get("dac_name", ""))
        with _AUDIO_OUTPUT_LOCK:
            ALSA_DRIVER   = driver
            ALSA_DEVICE   = device
            ALSA_DAC_NAME = name
        logger.info("Audio output preference loaded: %s / %s (%s)", driver, device, name or "unnamed")
        return True
    except Exception as e:
        logger.warning("load audio output preference failed: %s", e)
        return False


def _save_audio_output_config(driver, device, dac_name=""):
    path = _audio_output_path()
    data = {
        "alsa_driver": driver,
        "alsa_device": device,
        "dac_name": _normalise_dac_name(dac_name),
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _parse_aplay_devices(output):
    devices = []
    seen = set()
    pattern = re.compile(
        r"card\s+(\d+):\s*([^\[]*)\[([^\]]+)\],\s*device\s+(\d+):\s*([^\[]*)\[([^\]]+)\]",
        re.IGNORECASE,
    )
    for line in str(output or "").splitlines():
        m = pattern.search(line)
        if not m:
            continue
        card_num = m.group(1)
        card_short = _normalise_dac_name(m.group(2))
        card_name = _normalise_dac_name(m.group(3))
        dev_num = m.group(4)
        dev_short = _normalise_dac_name(m.group(5))
        dev_name = _normalise_dac_name(m.group(6))
        device = f"hw:{card_num},{dev_num}"
        if device in seen:
            continue
        seen.add(device)
        name = card_name or dev_name or card_short or dev_short or f"ALSA device {device}"
        devices.append({
            "label": f"{name} — {device}",
            "name": name,
            "driver": "ALSA",
            "device": device,
        })
    return devices


def _alsa_device_numbers(device):
    m = re.match(r"^(?:hw|plughw):(\d+),(\d+)$", str(device or "").strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _dac_identity_token_text(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _dac_identity_matches(saved_name, *parts):
    saved = _normalise_dac_name(saved_name)
    if not saved:
        return True
    haystack = " ".join(_normalise_dac_name(p) for p in parts if p)
    saved_compact = _dac_identity_token_text(saved)
    haystack_compact = _dac_identity_token_text(haystack)
    if saved_compact and saved_compact in haystack_compact:
        return True
    tokens = [t for t in re.split(r"[^a-z0-9]+", saved.lower()) if len(t) >= 2]
    return bool(tokens) and all(t in haystack.lower() for t in tokens)


def _selected_audio_output_available_for_playback():
    """Strict playback-only DAC presence check.

    Unlike _discover_audio_devices(), this never re-inserts the saved output.
    It matches the selected hw/plughw card and device against raw aplay -l
    output and, when saved, requires the DAC identity to still match.
    """
    with _AUDIO_OUTPUT_LOCK:
        driver = ALSA_DRIVER
        device = ALSA_DEVICE
        dac_name = ALSA_DAC_NAME

    if driver not in _VALID_ALSA_DRIVERS:
        return False, f"unsupported ALSA driver: {driver}"
    card_num, dev_num = _alsa_device_numbers(device)
    if card_num is None or dev_num is None:
        return False, f"unsupported ALSA device: {device}"

    try:
        res = subprocess.run(
            ["aplay", "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        output = (res.stdout or "") + "\n" + (res.stderr or "")
    except Exception as e:
        return False, f"aplay failed: {e}"

    pattern = re.compile(
        r"card\s+(\d+):\s*([^\[]*)\[([^\]]+)\],\s*device\s+(\d+):\s*([^\[]*)\[([^\]]+)\]",
        re.IGNORECASE,
    )
    exact_line = ""
    for line in str(output or "").splitlines():
        m = pattern.search(line)
        if not m:
            continue
        if m.group(1) != card_num or m.group(4) != dev_num:
            continue
        exact_line = line.strip()
        if _dac_identity_matches(dac_name, line, m.group(2), m.group(3), m.group(5), m.group(6)):
            return True, ""
        return False, f"selected ALSA device {device} is now {exact_line}"

    return False, f"selected ALSA device {device} not found"


def _require_audio_output_for_playback(reason="playback"):
    ok, detail = _selected_audio_output_available_for_playback()
    if ok:
        return True
    logger.warning("DAC unavailable before %s: %s", reason, detail)
    raise AudioOutputUnavailable(detail)


def _discover_audio_devices():
    try:
        res = subprocess.run(
            ["aplay", "-l"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        devices = _parse_aplay_devices((res.stdout or "") + "\n" + (res.stderr or ""))
    except Exception as e:
        logger.debug("aplay device discovery failed: %s", e)
        devices = []

    with _AUDIO_OUTPUT_LOCK:
        current_driver = ALSA_DRIVER
        current_device = ALSA_DEVICE
        current_name = ALSA_DAC_NAME

    if current_device and not any(d.get("device") == current_device for d in devices):
        devices.insert(0, {
            "label": f"{current_name or 'Current output'} — {current_device}",
            "name": current_name or "Current output",
            "driver": current_driver,
            "device": current_device,
        })
    return devices


def _resolve_dac_name(device=None):
    target = str(device or ALSA_DEVICE or "").strip()
    with _AUDIO_OUTPUT_LOCK:
        saved_name = ALSA_DAC_NAME
    for d in _discover_audio_devices():
        if d.get("device") == target:
            return _normalise_dac_name(d.get("name"))
    return saved_name or target


def _audio_output_locked_state():
    player = APP_INSTANCE.player if APP_INSTANCE is not None else None
    playing = False
    exclusive = False
    if player is not None:
        try:
            playing = bool(player.is_playing())
        except Exception:
            playing = False
        try:
            exclusive = bool(getattr(player, "exclusive_lock_mode", False))
        except Exception:
            exclusive = False
    return {
        "playing": playing,
        "exclusive": exclusive,
        "dac_locked": bool(playing or exclusive),
    }


def _audio_output_state():
    with _AUDIO_OUTPUT_LOCK:
        driver = ALSA_DRIVER
        device = ALSA_DEVICE
        # Keep /status lightweight: do not run aplay during polling.
        # The Settings devices endpoint resolves friendly names on demand.
        name = ALSA_DAC_NAME or ALSA_DEVICE
    out = {
        "alsa_driver": driver,
        "alsa_device": device,
        "dac_name": name,
    }
    out.update(_audio_output_locked_state())
    return out


def _quality_tier_from_stream(sample_rate=None, bit_depth=None):
    """Return the same quality tier used by the UI colour logic.

    This helper is intentionally read-only. It does not touch the player,
    DAC lock/release flow, or ALSA configuration.
    """
    try:
        sr = int(sample_rate or 0)
    except Exception:
        sr = 0
    try:
        bd = int(bit_depth or 0)
    except Exception:
        bd = 0
    if bd >= 24 or sr > 48000:
        return "hires"
    if sr or bd:
        return "cd"
    return "unknown"


def _quality_label_from_stream(codec=None, sample_rate=None, bit_depth=None):
    parts = []
    if codec:
        parts.append(str(codec).upper())
    try:
        bd = int(bit_depth or 0)
    except Exception:
        bd = 0
    try:
        sr = int(sample_rate or 0)
    except Exception:
        sr = 0
    if bd:
        parts.append(f"{bd}BIT")
    if sr:
        khz = (sr / 1000.0)
        label = (f"{khz:.1f}" if khz % 1 else f"{int(khz)}")
        parts.append(f"{label}KHZ")
    return " / ".join(parts)


def _positive_int(value):
    try:
        out = int(float(value or 0))
    except Exception:
        return None
    return out if out > 0 else None


def _bounded_int(value, default, minimum=1, maximum=300):
    try:
        out = int(float(value or default))
    except Exception:
        out = int(default)
    return max(int(minimum), min(int(out), int(maximum)))


def _local_test_output_format_from_player(player):
    """Return local-test output format only when Rust has reported it.

    These values come from the existing Rust/GStreamer output caps plumbing via
    player.stream_info. They are intentionally not inferred from source metadata.
    """
    if player is None:
        return None, None, "unknown"
    try:
        info = dict(getattr(player, "stream_info", {}) or {})
    except Exception:
        info = {}
    output_rate = _positive_int(info.get("output_rate"))
    output_depth = _positive_int(info.get("output_depth"))
    if output_rate or output_depth:
        return output_rate, output_depth, "rust_gstreamer_output_caps"
    return None, None, "unknown"


def _is_local_playback_context():
    if LOCAL_PLAYBACK_ACTIVE:
        return True
    track_id = str(CURRENT_CONTEXT.get("track_id") or "")
    return (
        str(CURRENT_CONTEXT.get("context_type") or "") == "local"
        and (track_id.startswith("local-test:") or track_id.startswith("local:"))
    )


def _is_local_album_playback_context():
    return (
        _is_local_playback_context()
        and str(LOCAL_PLAYBACK_CONTEXT.get("context_type") or "") == "local_album"
        and isinstance(LOCAL_PLAYBACK_CONTEXT.get("track_ids"), list)
        and bool(LOCAL_PLAYBACK_CONTEXT.get("track_ids"))
    )


def _queue_current_snapshot():
    with _QUEUE_LOCK:
        if PLAY_QUEUE and 0 <= QUEUE_INDEX < len(PLAY_QUEUE):
            track_id = str(PLAY_QUEUE[QUEUE_INDEX])
            return track_id, dict(PLAY_QUEUE_META_CACHE.get(track_id, {}) or {})
    return None, {}


def _status_playback_context(player):
    """Return a source-aware status context for /status and /session.

    A persisted queue can survive after the player pipeline is idle.  In that
    case CURRENT_CONTEXT may still contain an older Tidal item while the queue
    points at a Local item.  Treat that mismatch as idle unless an active local,
    radio, or matching Tidal context proves the current item is resumable.
    """
    try:
        is_playing = bool(player.is_playing()) if player is not None else False
    except Exception:
        is_playing = False

    queue_track_id, queue_meta = _queue_current_snapshot()

    if RADIO_MODE and CURRENT_RADIO:
        return {
            "playback_state": "playing" if is_playing else "paused",
            "current_track_valid": True,
            "source": "radio",
            "current_track_id": None,
            "context": CURRENT_CONTEXT,
        }

    context = LOCAL_PLAYBACK_CONTEXT if _is_local_playback_context() else CURRENT_CONTEXT
    context_track_id = str(context.get("track_id") or "")
    queue_source = str((queue_meta or {}).get("source") or "").lower()
    queue_is_local = bool(queue_track_id) and (queue_source == "local" or str(queue_track_id).startswith("local:"))

    if queue_is_local:
        if _is_local_playback_context() and context_track_id == str(queue_track_id):
            return {
                "playback_state": "playing" if is_playing else "paused",
                "current_track_valid": True,
                "source": "local",
                "current_track_id": context_track_id,
                "context": context,
            }
        local_start_age = time.time() - float(PLAYBACK_START_TIME) if PLAYBACK_START_TIME else 999.0
        if is_playing:
            derived = {
                "track_id": queue_track_id,
                "title": queue_meta.get("title") or "",
                "artist": queue_meta.get("artist") or "",
                "artist_id": "",
                "cover": queue_meta.get("cover") or queue_meta.get("artwork_url") or "",
                "duration": queue_meta.get("duration") or 0,
                "album": queue_meta.get("album") or "",
                "album_id": "",
                "context_title": queue_meta.get("album") or "Play Queue",
                "context_type": "local_queue",
                "context_id": "queue",
            }
            return {
                "playback_state": "playing",
                "current_track_valid": True,
                "source": "local",
                "current_track_id": queue_track_id,
                "context": derived,
            }
        if queue_meta and local_start_age < 5.0:
            derived = {
                "track_id": queue_track_id,
                "title": queue_meta.get("title") or "",
                "artist": queue_meta.get("artist") or "",
                "artist_id": "",
                "cover": queue_meta.get("cover") or queue_meta.get("artwork_url") or "",
                "duration": queue_meta.get("duration") or 0,
                "album": queue_meta.get("album") or "",
                "album_id": "",
                "context_title": queue_meta.get("album") or "Play Queue",
                "context_type": "local_queue",
                "context_id": "queue",
            }
            return {
                "playback_state": "playing" if is_playing else "paused",
                "current_track_valid": True,
                "source": "local",
                "current_track_id": queue_track_id,
                "context": derived,
            }
        return {
            "playback_state": "idle",
            "current_track_valid": False,
            "source": None,
            "current_track_id": None,
            "context": {},
        }

    if queue_track_id and context_track_id and context_track_id != str(queue_track_id):
        if is_playing and queue_meta:
            derived = {
                "track_id": queue_track_id,
                "title": queue_meta.get("title") or "",
                "artist": queue_meta.get("artist") or "",
                "artist_id": queue_meta.get("artist_id") or "",
                "cover": queue_meta.get("cover") or "",
                "duration": queue_meta.get("duration") or 0,
                "album": queue_meta.get("album") or "",
                "album_id": queue_meta.get("album_id") or "",
                "context_title": queue_meta.get("context_title") or "",
                "context_type": queue_meta.get("context_type") or "",
                "context_id": queue_meta.get("context_id") or "",
            }
            return {
                "playback_state": "playing",
                "current_track_valid": True,
                "source": "tidal",
                "current_track_id": queue_track_id,
                "context": derived,
            }
        return {
            "playback_state": "idle",
            "current_track_valid": False,
            "source": None,
            "current_track_id": None,
            "context": {},
        }

    if context_track_id:
        if not queue_track_id and not is_playing and not _is_local_playback_context():
            return {
                "playback_state": "idle",
                "current_track_valid": False,
                "source": None,
                "current_track_id": None,
                "context": {},
            }
        return {
            "playback_state": "playing" if is_playing else "paused",
            "current_track_valid": True,
            "source": "local" if _is_local_playback_context() else "tidal",
            "current_track_id": context_track_id,
            "context": context,
        }

    return {
        "playback_state": "idle",
        "current_track_valid": False,
        "source": None,
        "current_track_id": None,
        "context": {},
    }


def _tidal_account_display_name():
    """Return a safe logged-in Tidal account label, without exposing secrets."""
    try:
        backend = APP_INSTANCE.backend if APP_INSTANCE else None
        if not backend or not backend.check_login():
            return ""
        user = getattr(getattr(backend, "session", None), "user", None)
        if not user:
            return ""
        for attr in ("username", "email"):
            value = getattr(user, attr, "")
            if callable(value):
                value = value()
            value = str(value or "").strip()
            if value:
                return value
        first = str(getattr(user, "first_name", "") or "").strip()
        last = str(getattr(user, "last_name", "") or "").strip()
        full_name = " ".join([part for part in (first, last) if part]).strip()
        if full_name:
            return full_name
        profile = getattr(user, "profile_metadata", None)
        if isinstance(profile, dict):
            for key in ("username", "email", "name"):
                value = str(profile.get(key) or "").strip()
                if value:
                    return value
    except Exception as e:
        logger.debug("Could not read Tidal account display name: %s", e)
    return ""


def _set_local_playback_context(meta):
    global LOCAL_PLAYBACK_ACTIVE, LOCAL_PLAYBACK_CONTEXT
    LOCAL_PLAYBACK_ACTIVE = True
    context_type = meta.get("context_type") or "local"
    LOCAL_PLAYBACK_CONTEXT = {
        "track_id": meta.get("track_id"),
        "title": meta.get("title"),
        "artist": meta.get("artist"),
        "artist_id": "",
        "cover": meta.get("cover") or "",
        "duration": meta.get("duration"),
        "album": meta.get("album"),
        "album_id": meta.get("album_id") or "",
        "context_title": meta.get("context_title") or "Local Test",
        "context_type": context_type,
        "context_id": meta.get("context_id") or meta.get("track_id"),
    }
    for key in (
        "track_ids",
        "current_index",
        "is_cue_track",
        "cue_path",
        "cue_audio_path",
        "cue_track_number",
        "cue_start_seconds",
        "cue_end_seconds",
    ):
        if key in meta:
            LOCAL_PLAYBACK_CONTEXT[key] = meta.get(key)
    CURRENT_CONTEXT.update(LOCAL_PLAYBACK_CONTEXT)


def _clear_local_playback_context():
    global LOCAL_PLAYBACK_ACTIVE, LOCAL_PLAYBACK_CONTEXT
    LOCAL_PLAYBACK_ACTIVE = False
    LOCAL_PLAYBACK_CONTEXT = {}


def _reset_idle_playback_context():
    """Clear now-playing/session metadata after an intentional full stop."""
    global PLAYBACK_START_TIME, RADIO_MODE, CURRENT_RADIO, CURRENT_RADIO_METADATA
    global _RADIO_SCROBBLE_CURRENT_KEY
    _clear_local_playback_context()
    if RADIO_MODE:
        _set_radio_switching_guard()
        _cancel_pending_radio_start()
        try:
            _METADATA_REGISTRY.detach()
        except Exception:
            pass
    CURRENT_RADIO = None
    CURRENT_RADIO_METADATA = {}
    _RADIO_SCROBBLE_CURRENT_KEY = None
    RADIO_MODE = False
    _set_player_live_radio_mode(enabled=False)
    _set_current_radio_artwork({})
    for key in list(CURRENT_STREAM_INFO.keys()):
        CURRENT_STREAM_INFO[key] = None
    for key in (
        "channels",
        "observed_sample_rate",
        "observed_bit_depth",
        "output_sample_rate",
        "output_bit_depth",
        "output_channels",
        "radio_observed_sample_rate",
        "radio_observed_bit_depth",
        "radio_observed_output_sample_rate",
        "radio_observed_output_bit_depth",
        "radio_observed_rate_confidence",
    ):
        CURRENT_STREAM_INFO.pop(key, None)
    CURRENT_CONTEXT.update({
        "track_id": None,
        "title": None,
        "artist": None,
        "artist_id": None,
        "cover": None,
        "duration": 0,
        "album": None,
        "album_id": None,
        "context_title": None,
        "context_type": None,
        "context_id": None,
    })
    PLAYBACK_START_TIME = None


def _finalize_end_of_queue_playback(reason):
    """Stop final queue playback while preserving queue/repeat/shuffle state."""
    _invalidate_tidal_stream_resolution(reason)
    global PAUSED_PLAYBACK_POSITION, PAUSED_PLAYBACK_TRACK_ID
    logger.info("%s", reason)
    try:
        player = APP_INSTANCE.player if APP_INSTANCE is not None else None
        if player is not None and hasattr(player, "stop"):
            player.stop()
    except Exception as e:
        logger.debug("End-of-queue player.stop() failed: %s", e)
    PAUSED_PLAYBACK_POSITION = 0.0
    PAUSED_PLAYBACK_TRACK_ID = None
    _disarm_queue_auto_advance(reason)
    _reset_idle_playback_context()
    _schedule_idle_release(5)
    return False


def _local_playback_has_queue_position():
    global QUEUE_INDEX
    if not _is_local_playback_context() or not PLAY_QUEUE:
        return False
    if _active_local_cue_album_context() and not PLAY_QUEUE_PENDING_AFTER_CONTEXT:
        return False
    current_id = str(LOCAL_PLAYBACK_CONTEXT.get("track_id") or CURRENT_CONTEXT.get("track_id") or "")
    if not current_id:
        return False
    if 0 <= QUEUE_INDEX < len(PLAY_QUEUE) and str(PLAY_QUEUE[QUEUE_INDEX]) == current_id:
        return True
    try:
        QUEUE_INDEX = PLAY_QUEUE.index(current_id)
        return True
    except ValueError:
        return False



def _active_local_cue_album_context():
    """True only while a Local CUE virtual track is playing from album context."""
    if not _is_local_album_playback_context():
        return False
    try:
        if int(LOCAL_PLAYBACK_CONTEXT.get("is_cue_track") or 0):
            return True
    except Exception:
        pass
    try:
        current_id = str(LOCAL_PLAYBACK_CONTEXT.get("track_id") or "")
        meta = PLAY_QUEUE_META_CACHE.get(current_id, {}) or {}
        return int(meta.get("is_cue_track") or 0) == 1
    except Exception:
        return False


def _trim_future_local_cue_album_queue_locked(reason="queue-action"):
    """When a CUE album context is only there for navigation, do not let its
    future virtual tracks look like user-added queue items after Add to Queue
    or Play Next. Keep previous/current items for navigation/history and remove
    only future context items before inserting explicit user queue items.
    Caller must hold _QUEUE_LOCK.
    """
    global PLAY_QUEUE_PENDING_AFTER_CONTEXT
    if PLAY_QUEUE_PENDING_AFTER_CONTEXT:
        logger.info(
            "Local CUE album future queue trim skipped before %s: explicit user queue already active",
            reason,
        )
        return False
    if not _active_local_cue_album_context():
        return False
    if not PLAY_QUEUE or not (0 <= QUEUE_INDEX < len(PLAY_QUEUE)):
        return False
    if QUEUE_INDEX >= len(PLAY_QUEUE) - 1:
        return False

    removed = list(PLAY_QUEUE[QUEUE_INDEX + 1:])
    del PLAY_QUEUE[QUEUE_INDEX + 1:]

    identity = _queue_current_identity_locked()
    if ORIGINAL_QUEUE and identity:
        orig_idx = _queue_find_identity_index_locked(ORIGINAL_QUEUE, identity)
        if 0 <= orig_idx < len(ORIGINAL_QUEUE) - 1:
            del ORIGINAL_QUEUE[orig_idx + 1:]
    else:
        ORIGINAL_QUEUE[:] = list(PLAY_QUEUE)

    PLAY_QUEUE_PENDING_AFTER_CONTEXT = True
    logger.info(
        "Local CUE album future queue trimmed before %s: removed=%d queue_index=%s queue_length=%s",
        reason,
        len(removed),
        QUEUE_INDEX,
        len(PLAY_QUEUE),
    )
    return True

def _bit_perfect_state(audio_state=None):
    """Build a pragmatic, backend-confirmed Bit Perfect readout.

    Important: this function is observational only. It must never configure,
    claim, release, pause, resume, or otherwise affect the active pipeline.
    """
    audio_state = dict(audio_state or _audio_output_state())
    driver = str(audio_state.get("alsa_driver") or "").strip()
    device = str(audio_state.get("alsa_device") or "").strip()
    codec = CURRENT_STREAM_INFO.get("codec")
    sample_rate = CURRENT_STREAM_INFO.get("sample_rate")
    bit_depth = CURRENT_STREAM_INFO.get("bit_depth")
    is_local_context = _is_local_playback_context()
    tier = _quality_tier_from_stream(sample_rate, bit_depth)
    label = _quality_label_from_stream(codec, sample_rate, bit_depth)

    player = APP_INSTANCE.player if APP_INSTANCE is not None else None
    try:
        playing = bool(player.is_playing()) if player is not None else False
    except Exception:
        playing = False
    try:
        exclusive = bool(getattr(player, "exclusive_lock_mode", False)) if player is not None else False
    except Exception:
        exclusive = False

    local_output_sample_rate = None
    local_output_bit_depth = None
    local_output_confidence = "unknown"
    if is_local_context:
        local_output_sample_rate, local_output_bit_depth, local_output_confidence = (
            _local_test_output_format_from_player(player)
        )

    payload = {
        "quality_tier": tier,
        "quality_label": label,
        "source_format": codec,
        "source_sample_rate": sample_rate,
        "source_bit_depth": bit_depth,
        "source_channels": CURRENT_STREAM_INFO.get("channels") if is_local_context else None,
        "output_sample_rate": local_output_sample_rate,
        "output_bit_depth": local_output_bit_depth,
        "output_rate_confidence": local_output_confidence,
        "software_volume": 1.0,
        "dsp_active": False,
        "resampling_active": False,
        "bit_perfect_path_confirmed": False,
        "bit_perfect_confidence": "unconfirmed",
        "bit_perfect_reason": "Bit Perfect Unconfirmed",
    }

    if not audio_state.get("dac_locked"):
        payload["bit_perfect_reason"] = "DAC not locked"
        return payload
    if not exclusive:
        payload["bit_perfect_reason"] = "Exclusive output not active"
        return payload
    if not playing:
        payload["bit_perfect_reason"] = "Nothing playing"
        return payload
    if driver not in _VALID_ALSA_DRIVERS:
        payload["bit_perfect_reason"] = "Output driver is not direct ALSA"
        return payload
    if not re.match(r"^hw:\d+,\d+$", device):
        payload["bit_perfect_reason"] = "Output device is not a direct hw ALSA path"
        return payload
    if not sample_rate:
        payload["bit_perfect_reason"] = "Source sample rate unknown"
        return payload
    if not bit_depth:
        payload["bit_perfect_reason"] = "Source bit depth unknown"
        return payload
    if is_local_context:
        codec_l = str(codec or "").strip().lower()
        if codec_l not in ("flac", "ape", "wav", "wave", "aiff", "aif", "alac"):
            payload["bit_perfect_reason"] = "Local source format is not verified lossless"
            return payload
        if not local_output_sample_rate:
            payload["bit_perfect_reason"] = "Local output sample rate unknown"
            return payload
        if not local_output_bit_depth:
            payload["bit_perfect_reason"] = "Local output bit depth unknown"
            return payload
        if local_output_confidence != "rust_gstreamer_output_caps":
            payload["bit_perfect_reason"] = "Local output format confidence is insufficient"
            return payload
        if int(local_output_sample_rate) != int(sample_rate):
            payload["bit_perfect_reason"] = "Local output sample rate does not match source"
            return payload
        if payload.get("software_volume") != 1.0:
            payload["bit_perfect_reason"] = "Software volume is not unity"
            return payload
        if payload.get("dsp_active"):
            payload["bit_perfect_reason"] = "SROVA DSP active"
            return payload
        if payload.get("resampling_active"):
            payload["bit_perfect_reason"] = "SROVA resampling active"
            return payload
        khz = (int(sample_rate) / 1000.0)
        rate_label = (f"{khz:.1f}" if khz % 1 else f"{int(khz)}") + " kHz"
        if int(local_output_bit_depth) != int(bit_depth):
            if int(local_output_bit_depth) == 32 and int(bit_depth) in (16, 24):
                payload.update({
                    "bit_perfect_path_confirmed": True,
                    "bit_perfect_confidence": "confirmed_by_srova",
                    "bit_perfect_reason": (
                        f"Local {str(codec or 'lossless').upper()} confirmed at native sample rate "
                        f"{rate_label}; Rust/GStreamer reports S32_LE output container "
                        f"for {int(bit_depth)}-bit source audio, with direct locked "
                        f"{'ALSA mmap' if driver == 'alsa_mmap' else 'ALSA'} output and no SROVA DSP/resampling"
                    ),
                })
                return payload
            payload["bit_perfect_reason"] = "Local output bit depth does not match source"
            return payload
        payload.update({
            "bit_perfect_path_confirmed": True,
            "bit_perfect_confidence": "confirmed_by_srova",
            "bit_perfect_reason": (
                f"Local {str(codec or 'lossless').upper()} confirmed from indexed source metadata at native "
                f"{rate_label} / {int(bit_depth)}-bit, Rust/GStreamer output caps match, "
                f"direct locked {'ALSA mmap' if driver == 'alsa_mmap' else 'ALSA'} output, no SROVA DSP/resampling"
            ),
        })
        return payload
    if RADIO_MODE:
        codec_l = str(codec or "").strip().lower()
        if codec_l not in ("flac",):
            payload["bit_perfect_reason"] = "Radio source format not lossless"
            return payload
        if CURRENT_STREAM_INFO.get("radio_observed_rate_confidence") != "flac_streaminfo":
            payload["bit_perfect_reason"] = "Radio source technical info not verified"
            return payload
        if payload.get("software_volume") != 1.0:
            payload["bit_perfect_reason"] = "Software volume is not unity"
            return payload
        if payload.get("dsp_active"):
            payload["bit_perfect_reason"] = "SROVA DSP active"
            return payload
        if payload.get("resampling_active"):
            payload["bit_perfect_reason"] = "SROVA resampling active"
            return payload
        khz = (int(sample_rate) / 1000.0)
        rate_label = (f"{khz:.1f}" if khz % 1 else f"{int(khz)}") + " kHz"
        payload.update({
            "output_sample_rate": sample_rate,
            "output_bit_depth": bit_depth,
            "output_rate_confidence": "srova_native_direct_alsa",
            "bit_perfect_path_confirmed": True,
            "bit_perfect_confidence": "confirmed_by_srova",
            "bit_perfect_reason": (
                "Lossless radio stream confirmed from FLAC STREAMINFO at native "
                f"{rate_label} / {int(bit_depth)}-bit, direct locked "
                f"{'ALSA mmap' if driver == 'alsa_mmap' else 'ALSA'} output, no SROVA DSP"
            ),
        })
        return payload

    payload.update({
        "output_sample_rate": sample_rate,
        "output_bit_depth": bit_depth,
        "output_rate_confidence": "srova_native_direct_alsa",
        "bit_perfect_path_confirmed": True,
        "bit_perfect_confidence": "srova_confirmed_pragmatic",
        "bit_perfect_reason": (
            "SROVA-confirmed direct %s output, direct hw device, native stream rate, "
            "no SROVA DSP/resampling, unity software volume"
            % ("ALSA mmap" if driver == "alsa_mmap" else "ALSA")
        ),
    })
    return payload


def _set_audio_output_preference(driver, device, dac_name=""):
    global ALSA_DRIVER, ALSA_DEVICE, ALSA_DAC_NAME
    driver = _validate_audio_driver(driver)
    device = _validate_audio_device(device)
    name = _normalise_dac_name(dac_name) or _resolve_dac_name(device)
    _save_audio_output_config(driver, device, name)
    with _AUDIO_OUTPUT_LOCK:
        ALSA_DRIVER = driver
        ALSA_DEVICE = device
        ALSA_DAC_NAME = name
    logger.info("Audio output preference saved: %s / %s (%s)", driver, device, name or "unnamed")
    return _audio_output_state()


# =========================================================================
# App settings persistence
# =========================================================================

def _load_app_settings():
    with _APP_SETTINGS_LOCK:
        try:
            if os.path.exists(_APP_SETTINGS_FILE):
                with open(_APP_SETTINGS_FILE, "r") as f:
                    data = json.load(f) or {}
                if isinstance(data, dict):
                    _APP_SETTINGS.update(data)
        except Exception as e:
            logger.warning("load_app_settings failed: %s", e)


def _save_app_settings():
    with _APP_SETTINGS_LOCK:
        data = dict(_APP_SETTINGS)
    try:
        os.makedirs(os.path.dirname(_APP_SETTINGS_FILE), exist_ok=True)
        tmp = _APP_SETTINGS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, _APP_SETTINGS_FILE)
    except Exception as e:
        logger.warning("save_app_settings failed: %s", e)


def _tidal_infinite_play_enabled():
    with _APP_SETTINGS_LOCK:
        return bool(_APP_SETTINGS.get("tidal_infinite_play"))


def _normalise_tidal_infinite_play_mode(mode):
    mode = str(mode or "").strip().lower()
    if mode in ("same_artist", "similar_artist", "surprise_me"):
        return mode
    return "similar_artist"


def _tidal_infinite_play_mode():
    with _APP_SETTINGS_LOCK:
        return _normalise_tidal_infinite_play_mode(_APP_SETTINGS.get("tidal_infinite_play_mode"))


def _set_tidal_infinite_play_settings(enabled=None, mode=None):
    with _APP_SETTINGS_LOCK:
        if enabled is not None:
            _APP_SETTINGS["tidal_infinite_play"] = bool(enabled)
        if mode is not None:
            _APP_SETTINGS["tidal_infinite_play_mode"] = _normalise_tidal_infinite_play_mode(mode)
    _save_app_settings()
    return {
        "enabled": _tidal_infinite_play_enabled(),
        "mode": _tidal_infinite_play_mode(),
    }


# =========================================================================
# Queue persistence
# =========================================================================

def save_queue():
    """Persist queue state to disk asynchronously (daemon thread)."""
    def _save():
        try:
            os.makedirs(os.path.dirname(_QUEUE_FILE), exist_ok=True)
            data = {
                "queue":          list(PLAY_QUEUE),
                "queue_index":    QUEUE_INDEX,
                "repeat_mode":    REPEAT_MODE,
                "shuffle_on":     SHUFFLE_ON,
                "original_queue": list(ORIGINAL_QUEUE),
                "meta_cache":     dict(PLAY_QUEUE_META_CACHE)
            }
            tmp = _QUEUE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, _QUEUE_FILE)
        except Exception as e:
            logger.warning("save_queue failed: %s", e)
    t = threading.Thread(target=_save, daemon=True)
    t.start()
    return t


def load_queue():
    """Restore queue state from disk on startup.
    Playback does NOT auto-resume (Option A). The user navigates to the
    queue view and taps a track to resume."""
    global PLAY_QUEUE, QUEUE_INDEX, REPEAT_MODE, SHUFFLE_ON, ORIGINAL_QUEUE
    global PLAY_QUEUE_META_CACHE
    try:
        if not os.path.exists(_QUEUE_FILE):
            return
        with open(_QUEUE_FILE, "r") as f:
            data = json.load(f)
        PLAY_QUEUE.clear()
        PLAY_QUEUE.extend([str(x) for x in data.get("queue", [])])
        QUEUE_INDEX = int(data.get("queue_index", 0))
        if QUEUE_INDEX >= len(PLAY_QUEUE):
            QUEUE_INDEX = max(0, len(PLAY_QUEUE) - 1)
        REPEAT_MODE = data.get("repeat_mode", "off")
        SHUFFLE_ON  = bool(data.get("shuffle_on", False))
        ORIGINAL_QUEUE.clear()
        ORIGINAL_QUEUE.extend([str(x) for x in data.get("original_queue", [])])
        PLAY_QUEUE_META_CACHE.clear()
        PLAY_QUEUE_META_CACHE.update(data.get("meta_cache", {}))
        logger.info("Queue restored: %d tracks, index %d", len(PLAY_QUEUE), QUEUE_INDEX)
    except Exception as e:
        logger.warning("load_queue failed: %s", e)


def _reset_startup_playback_state():
    """Clear transient playback state after restoring persistent queue/settings."""
    global PLAYBACK_START_TIME, LOCAL_PLAYBACK_ACTIVE, LOCAL_PLAYBACK_CONTEXT
    global RADIO_MODE, CURRENT_RADIO, CURRENT_RADIO_METADATA, _RADIO_SCROBBLE_CURRENT_KEY
    global PAUSED_PLAYBACK_POSITION, PAUSED_PLAYBACK_TRACK_ID, PAUSED_PIPELINE_RELEASED
    global LAST_STATE, LAST_STATE_TIME

    try:
        _cancel_pending_radio_start()
        _METADATA_REGISTRY.detach()
    except Exception:
        pass
    try:
        player = APP_INSTANCE.player if APP_INSTANCE is not None else None
        if player is not None and hasattr(player, "stop"):
            player.stop()
    except Exception as e:
        logger.debug("startup player.stop() failed: %s", e)

    CURRENT_CONTEXT.update({
        "track_id": None,
        "title": "",
        "artist": "",
        "artist_id": None,
        "cover": None,
        "duration": 0,
        "album": None,
        "album_id": None,
        "context_title": None,
        "context_type": None,
        "context_id": None,
    })
    LOCAL_PLAYBACK_ACTIVE = False
    LOCAL_PLAYBACK_CONTEXT = {}
    RADIO_MODE = False
    CURRENT_RADIO = None
    CURRENT_RADIO_METADATA = {}
    _RADIO_SCROBBLE_CURRENT_KEY = None
    _set_player_live_radio_mode(enabled=False)
    _set_current_radio_artwork({})
    PLAYBACK_START_TIME = None
    PAUSED_PLAYBACK_POSITION = 0.0
    PAUSED_PLAYBACK_TRACK_ID = None
    PAUSED_PIPELINE_RELEASED = False
    LAST_STATE = None
    LAST_STATE_TIME = 0
    CURRENT_STREAM_INFO.clear()
    CURRENT_STREAM_INFO.update({
        "sample_rate": None,
        "bit_depth": None,
        "codec": None,
    })
    logger.info("Startup playback state reset: queue preserved, playback idle")


def _queue_current_identity_locked():
    """Return the active queue item identity and duplicate occurrence rank."""
    if not PLAY_QUEUE or not (0 <= QUEUE_INDEX < len(PLAY_QUEUE)):
        return None
    current_id = str(PLAY_QUEUE[QUEUE_INDEX])
    occurrence = 0
    for idx in range(0, QUEUE_INDEX + 1):
        if str(PLAY_QUEUE[idx]) == current_id:
            occurrence += 1
    return current_id, occurrence


def _queue_find_identity_index_locked(queue, identity):
    if not identity:
        return 0
    current_id, occurrence = identity
    seen = 0
    fallback = None
    for idx, tid in enumerate(queue):
        if str(tid) != str(current_id):
            continue
        if fallback is None:
            fallback = idx
        seen += 1
        if seen == occurrence:
            return idx
    return fallback if fallback is not None else min(QUEUE_INDEX, max(0, len(queue) - 1))


def _queue_remap_index_locked(identity):
    global QUEUE_INDEX
    if not PLAY_QUEUE:
        QUEUE_INDEX = 0
        return
    QUEUE_INDEX = _queue_find_identity_index_locked(PLAY_QUEUE, identity)


def _queue_ensure_canonical_locked():
    if not ORIGINAL_QUEUE or not PLAY_QUEUE:
        ORIGINAL_QUEUE.clear()
        ORIGINAL_QUEUE.extend(PLAY_QUEUE)


def _queue_group_key_locked(track_id):
    meta = PLAY_QUEUE_META_CACHE.get(str(track_id), {}) or {}
    context_id = str(meta.get("context_id") or "").strip().lower()
    album_id = str(meta.get("album_id") or "").strip().lower()
    album = str(meta.get("album") or "").strip().lower()
    artist = str(meta.get("album_artist") or meta.get("artist") or "").strip().lower()
    source = str(meta.get("source") or ("local" if str(track_id).startswith("local:") else "tidal")).lower()
    return album_id or context_id or (artist + "\0" + album if album else "") or source


def _queue_shuffle_score_locked(candidate):
    """Score only severe album/context clumps; lower is better."""
    if len(candidate) < 6:
        return 0
    group_keys = [_queue_group_key_locked(tid) for tid in candidate]
    group_count = len(set(group_keys))
    if group_count <= 1:
        return 0

    hard_run_limit = 5 if len(candidate) >= 18 else 4
    score = 0

    run_len = 1
    for idx in range(1, len(group_keys)):
        if group_keys[idx] == group_keys[idx - 1]:
            run_len += 1
            if run_len >= hard_run_limit:
                score += (run_len - hard_run_limit + 1) ** 2
        else:
            run_len = 1

    block_window = min(10, max(6, len(candidate) // 2))
    if len(group_keys) >= block_window:
        block_limit = block_window - 1
        for start in range(0, len(group_keys) - block_window + 1):
            counts = {}
            for key in group_keys[start:start + block_window]:
                counts[key] = counts.get(key, 0) + 1
            max_count = max(counts.values())
            if max_count >= block_limit:
                score += (max_count - block_limit + 1) * 2

    return score


def _queue_smart_shuffle_locked(track_ids):
    """Use true random order unless it has extreme album/context clumps."""
    base = list(track_ids)
    count = len(base)
    if count < 6:
        random.shuffle(base)
        return base

    attempts = max(10, min(30, count))
    best = None
    for attempt in range(attempts):
        candidate = list(base)
        random.shuffle(candidate)
        score = _queue_shuffle_score_locked(candidate)
        if score == 0:
            return candidate
        if best is None or score < best[0] or (score == best[0] and random.random() < 0.35):
            best = (score, candidate)
        # Keep the first few attempts especially random; only fall back to the
        # least-severe clump if every candidate violates the loose guardrails.
        if attempt >= 4 and best and best[0] <= 1 and random.random() < 0.35:
            return best[1]
    return best[1] if best else base


def _queue_without_identity_locked(queue, identity):
    items = list(queue)
    if not identity:
        return items
    idx = _queue_find_identity_index_locked(items, identity)
    if 0 <= idx < len(items):
        items.pop(idx)
    return items


def _queue_current_id_from_identity(identity):
    if not identity:
        return None
    return str(identity[0])


def _queue_shuffle_from_canonical_locked(identity=None):
    """Build the active visible/playback queue from canonical order."""
    global QUEUE_INDEX
    _queue_ensure_canonical_locked()
    PLAY_QUEUE[:] = _queue_smart_shuffle_locked(ORIGINAL_QUEUE)
    QUEUE_INDEX = 0


def _queue_shuffle_future_after_current_locked(identity):
    global QUEUE_INDEX
    _queue_ensure_canonical_locked()
    current_id = _queue_current_id_from_identity(identity)
    if not current_id:
        _queue_shuffle_from_canonical_locked(identity)
        return
    future = PLAY_QUEUE[QUEUE_INDEX + 1:] if 0 <= QUEUE_INDEX < len(PLAY_QUEUE) else []
    PLAY_QUEUE[:] = [current_id] + _queue_smart_shuffle_locked(future)
    QUEUE_INDEX = 0


def _queue_restore_canonical_locked(identity=None, keep_current_boundary=False):
    global QUEUE_INDEX
    _queue_ensure_canonical_locked()
    if keep_current_boundary and identity:
        current_id = _queue_current_id_from_identity(identity)
        orig_idx = _queue_find_identity_index_locked(ORIGINAL_QUEUE, identity)
        future = list(ORIGINAL_QUEUE[orig_idx + 1:]) if 0 <= orig_idx < len(ORIGINAL_QUEUE) else []
        PLAY_QUEUE[:] = [current_id] + future
        QUEUE_INDEX = 0
        return
    PLAY_QUEUE[:] = list(ORIGINAL_QUEUE)
    QUEUE_INDEX = 0


def _queue_remove_value_once_locked(queue, value):
    value = str(value)
    for idx, tid in enumerate(queue):
        if str(tid) == value:
            queue.pop(idx)
            return True
    return False


def _queue_remove_active_index_locked(index):
    """Remove one queue item and report whether it was the current item.

    Caller must hold _QUEUE_LOCK.
    """
    global QUEUE_INDEX
    if not (0 <= index < len(PLAY_QUEUE)):
        return False
    removed_current = index == QUEUE_INDEX
    removed_id = PLAY_QUEUE.pop(index)
    _queue_remove_value_once_locked(ORIGINAL_QUEUE, removed_id)
    if not PLAY_QUEUE:
        QUEUE_INDEX = 0
    elif index < QUEUE_INDEX:
        QUEUE_INDEX -= 1
    elif removed_current:
        QUEUE_INDEX = max(0, min(index, len(PLAY_QUEUE) - 1))
    return removed_current


def _queue_remove_active_indices_locked(indices):
    for idx in sorted(set(indices), reverse=True):
        _queue_remove_active_index_locked(idx)


# =========================================================================
# Radio station persistence
# =========================================================================

_RADIO_LOCK = threading.Lock()
_RADIO_FILE = os.path.join(
    os.path.expanduser("~"), ".config", "hiresti", "radio_stations.json"
)
_RADIO_PRESET_CATALOG_VERSION = 1
_RADIO_PRESET_STATIONS = (
    {
        "id": "preset-60-north-radio",
        "name": "60 North Radio",
        "url": "https://cdn1.zetcast.net/flac",
        "icon": "https://60north.radio/wp-content/uploads/2025/06/60n-radio-app-icon-600x600-1-1.png",
    },
    {
        "id": "preset-easy-radio",
        "name": "Easy Radio",
        "url": "https://live.easyradio.bg/flac",
        "icon": "https://easyradio.bg/static/radio-l.png",
    },
    {
        "id": "preset-pure-lounge-radio",
        "name": "Pure Lounge Radio",
        "url": "https://mscp4.live-streams.nl:8142/lounge.ogg",
        "icon": "https://static.mytuner.mobi/media/tvos_radios/bXV2ZQAg8q.png",
    },
    {
        "id": "preset-radio-paradise-mellow",
        "name": "Radio Paradise - Mellow Mix",
        "url": "http://stream.radioparadise.com/mellow-flacm",
        "icon": "https://radioparadise.com/rpassets/images/logo/logo_2022_nav_244x64.svg",
    },
    {
        "id": "preset-naim-jazz",
        "name": "Naim Jazz",
        "url": "http://mscp3.live-streams.nl:8340/jazz-flac.flac",
        "icon": "https://www.hiresaudio.online/wp-content/uploads/2020/12/Naim-Jazz-678x381.jpg",
    },
    {
        "id": "preset-radio-paradise-main",
        "name": "Radio Paradise - Main Mix",
        "url": "http://stream.radioparadise.com/flacm",
        "icon": "https://radioparadise.com/rpassets/images/logo/logo_2022_nav_244x64.svg",
    },
)


def _radio_stations_path():
    os.makedirs(os.path.dirname(_RADIO_FILE), exist_ok=True)
    return _RADIO_FILE


def _radio_station_name_key(station):
    return str((station or {}).get("name", "") or "").strip().casefold()


def _radio_station_url_key(station):
    return str((station or {}).get("url", "") or "").strip().rstrip("/").casefold()


def _radio_merge_preset_catalog(stations):
    merged = [dict(station) for station in stations if isinstance(station, dict)]
    existing_names = {_radio_station_name_key(station) for station in merged}
    existing_urls = {_radio_station_url_key(station) for station in merged}

    for preset in _RADIO_PRESET_STATIONS:
        name_key = _radio_station_name_key(preset)
        url_key = _radio_station_url_key(preset)
        if (name_key and name_key in existing_names) or (url_key and url_key in existing_urls):
            continue
        merged.append(dict(preset))
        existing_names.add(name_key)
        existing_urls.add(url_key)
    return merged


def _write_radio_station_data(stations):
    path = _radio_stations_path()
    tmp = path + ".tmp"
    data = {
        "preset_catalog_version": _RADIO_PRESET_CATALOG_VERSION,
        "stations": stations,
    }
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_radio_stations():
    try:
        path = _radio_stations_path()
        if not os.path.exists(path):
            stations = [dict(preset) for preset in _RADIO_PRESET_STATIONS]
            _write_radio_station_data(stations)
            return stations
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        stations = data.get("stations", [])
        if not isinstance(stations, list):
            raise ValueError("stations is not a list")
        try:
            catalog_version = int(data.get("preset_catalog_version", 0) or 0)
        except (TypeError, ValueError):
            catalog_version = 0
        if catalog_version < _RADIO_PRESET_CATALOG_VERSION:
            stations = _radio_merge_preset_catalog(stations)
            _write_radio_station_data(stations)
        return stations
    except Exception as e:
        logger.warning("_load_radio_stations failed: %s", e)
        return []


def _save_radio_stations(stations):
    _write_radio_station_data(stations)


def _reorder_radio_stations(stations, station_ids):
    if not isinstance(station_ids, list):
        raise ValueError("station_ids must be a list")

    current = [dict(station) for station in stations if isinstance(station, dict)]
    current_ids = [str(station.get("id", "") or "").strip() for station in current]
    requested_ids = [str(station_id or "").strip() for station_id in station_ids]

    if any(not station_id for station_id in current_ids):
        raise ValueError("all saved stations must have an id")
    if any(not station_id for station_id in requested_ids):
        raise ValueError("station_ids cannot contain empty values")
    if len(current_ids) != len(set(current_ids)):
        raise ValueError("saved station ids are not unique")
    if len(requested_ids) != len(set(requested_ids)):
        raise ValueError("station_ids cannot contain duplicates")
    if len(requested_ids) != len(current_ids) or set(requested_ids) != set(current_ids):
        raise ValueError("station_ids must contain every station exactly once")

    by_id = {str(station["id"]): station for station in current}
    return [by_id[station_id] for station_id in requested_ids]


# Latest spectrum frame for the VU meter -- updated by on_spectrum_data callback.
# Stores smoothed RMS and peak dB for L and R channels.
_SPECTRUM_LOCK = threading.Lock()
_SPECTRUM_STATE = {
    "left_rms":   -70.0,
    "right_rms":  -70.0,
    "left_peak":  -70.0,
    "right_peak": -70.0,
    "ts":          0.0
}
_SP_ALPHA_RMS  = 0.18   # RMS smoothing (slow, VU ballistics)
_SP_ALPHA_PEAK_ATK = 0.90   # peak attack (fast)
_SP_ALPHA_PEAK_REL = 0.06   # peak release (slow)


def _spectrum_mean_db(mags):
    """Convert FFT magnitude list (dB) to mean power dB."""
    if not mags:
        return -70.0
    lin = sum(10.0 ** (max(-70.0, float(m)) / 10.0) for m in mags)
    mean = lin / len(mags)
    import math
    return 10.0 * math.log10(mean) if mean > 0.0 else -70.0


def _spectrum_max_db(mags):
    """Peak bin from FFT magnitude list (dB)."""
    if not mags:
        return -70.0
    return max(-70.0, max(float(m) for m in mags))


def _on_spectrum_data_headless(self, magnitudes, position_s=None):
    """Headless on_spectrum_data -- computes L/R RMS+peak, stores in global."""
    if not magnitudes:
        return
    global _SPECTRUM_STATE
    try:
        if isinstance(magnitudes, dict):
            left_mags  = list(magnitudes.get("left")  or magnitudes.get("mono") or [])
            right_mags = list(magnitudes.get("right") or magnitudes.get("mono") or [])
        else:
            left_mags  = list(magnitudes)
            right_mags = list(magnitudes)

        raw_rms_l  = _spectrum_mean_db(left_mags)
        raw_rms_r  = _spectrum_mean_db(right_mags)
        raw_peak_l = _spectrum_max_db(left_mags)
        raw_peak_r = _spectrum_max_db(right_mags)

        with _SPECTRUM_LOCK:
            s = _SPECTRUM_STATE
            # Smooth RMS
            s["left_rms"]  = _SP_ALPHA_RMS * raw_rms_l  + (1 - _SP_ALPHA_RMS) * s["left_rms"]
            s["right_rms"] = _SP_ALPHA_RMS * raw_rms_r  + (1 - _SP_ALPHA_RMS) * s["right_rms"]
            # Peak with fast attack / slow release
            al = _SP_ALPHA_PEAK_ATK if raw_peak_l > s["left_peak"]  else _SP_ALPHA_PEAK_REL
            ar = _SP_ALPHA_PEAK_ATK if raw_peak_r > s["right_peak"] else _SP_ALPHA_PEAK_REL
            s["left_peak"]  = al * raw_peak_l + (1 - al) * s["left_peak"]
            s["right_peak"] = ar * raw_peak_r + (1 - ar) * s["right_peak"]
            s["ts"] = time.time()
    except Exception as e:
        logger.debug("spectrum data error: %s", e)

TADB_API_KEY  = "123"
TADB_BASE_URL = "https://www.theaudiodb.com/api/v1/json/" + TADB_API_KEY + "/"

_META_CACHE      = {}   # cache_key -> {"data": dict, "ts": float}
_META_CACHE_LOCK = threading.Lock()
TTL_META         = 3600   # 1 hour in-memory

_META_CACHE_FILE = os.path.join(
    os.path.expanduser("~"), ".local", "share", "hiresti", "hiresti_meta_cache.json"
)


def _strip_html(text):
    """Strip HTML tags from Last.fm bio text and clean whitespace."""
    if not text:
        return ""
    # Remove <a ...>...</a> links (Last.fm appends "Read more on Last.fm")
    text = re.sub(r'<a\s[^>]*>.*?</a>', '', text, flags=re.IGNORECASE | re.DOTALL)
    # Remove remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _meta_http_get(url, timeout=9):
    """Simple GET returning parsed JSON, raises on error."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "SROVA/0.1 (https://srova.music)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_lastfm_artist_meta(artist_name, api_key):
    """Fetch artist info from Last.fm: bio, tags, similar, stats."""
    url = (LASTFM_API_URL +
           "?method=artist.getInfo"
           "&artist="   + urllib.parse.quote(artist_name) +
           "&api_key="  + urllib.parse.quote(api_key) +
           "&autocorrect=1"
           "&format=json")
    data = _meta_http_get(url)
    a    = data.get("artist", {})
    bio_raw = (a.get("bio") or {}).get("summary", "")
    bio     = _strip_html(bio_raw)
    tags = [t["name"] for t in
            ((a.get("tags") or {}).get("tag") or [])
            if t.get("name")][:6]
    similar = [s["name"] for s in
               ((a.get("similar") or {}).get("artist") or [])
               if s.get("name")][:8]
    stats     = a.get("stats") or {}
    listeners = stats.get("listeners", "")
    playcount = stats.get("playcount", "")
    return {
        "artist_bio":      bio,
        "tags":            tags,
        "similar_artists": similar,
        "listeners":       listeners,
        "playcount":       playcount,
    }


def _fetch_lastfm_track_meta(artist_name, track_title, api_key):
    """Fetch track wiki from Last.fm."""
    url = (LASTFM_API_URL +
           "?method=track.getInfo"
           "&artist=" + urllib.parse.quote(artist_name) +
           "&track="  + urllib.parse.quote(track_title) +
           "&api_key=" + urllib.parse.quote(api_key) +
           "&autocorrect=1"
           "&format=json")
    data = _meta_http_get(url)
    t    = data.get("track", {})
    wiki_raw = (t.get("wiki") or {}).get("summary", "")
    wiki     = _strip_html(wiki_raw)
    # Extra track tags (merge with artist tags later)
    track_tags = [tg["name"] for tg in
                  ((t.get("toptags") or {}).get("tag") or [])
                  if tg.get("name")][:4]
    return {
        "track_summary": wiki,
        "track_tags":    track_tags,
    }



def _lastfm_best_image(images):
    """Return the largest useful Last.fm image URL from an image list."""
    if not isinstance(images, list):
        return ""
    priority = {"mega": 5, "extralarge": 4, "large": 3, "medium": 2, "small": 1}
    candidates = []
    for img in images:
        if not isinstance(img, dict):
            continue
        url = str(img.get("#text", "") or "").strip()
        if not url:
            continue
        # Last.fm's historical placeholder image should not replace station art.
        if "2a96cbd8b46e442fc41c2b86b821562f" in url:
            continue
        size = str(img.get("size", "") or "").strip().lower()
        candidates.append((priority.get(size, 0), url))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _radio_art_cache_key(artist_name, track_title):
    artist = re.sub(r"\s+", " ", str(artist_name or "").strip()).lower()
    title = re.sub(r"\s+", " ", str(track_title or "").strip()).lower()
    return artist + "\0" + title if artist and title else ""


def _clean_radio_art_lookup_text(value):
    """Lightly clean radio metadata for lookup without changing UI display text."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = text.replace("’", "'").replace("`", "'").replace("…", "...")
    # Remove common broadcaster/version clutter that often hurts Last.fm matching.
    text = re.sub(r"\s+\|\s+.*$", "", text)
    text = re.sub(r"\s+[•·]\s+.*$", "", text)
    text = re.sub(r"\s+-\s+(official|lyrics?|video|radio edit).*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\[(official|lyrics?|video|radio edit)[^\]]*\]\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _radio_art_text_variants(value, is_title=False):
    """Return safe Last.fm lookup variants, most-specific first.

    Radio metadata often includes remix/version tags. The UI still shows the
    original metadata; these variants are lookup-only.
    """
    base = _clean_radio_art_lookup_text(value)
    if not base:
        return []
    variants = []
    seen = set()

    def _normalise_variant(v):
        v = str(v or "").strip(" -–—\t\r\n")
        v = v.replace("’", "'").replace("`", "'").replace("…", "...")
        v = re.sub(r"\s+", " ", v)
        # Last.fm often has spacing around ellipses even when radio metadata does not.
        v = re.sub(r"\.{3}\s*", "... ", v)
        v = re.sub(r"\s+", " ", v).strip(" -–—\t\r\n")
        return v

    def _add(v):
        v = _normalise_variant(v)
        k = re.sub(r"[^a-z0-9]+", "", v.lower())
        if v and k and k not in seen:
            seen.add(k)
            variants.append(v)

    _add(base)

    if is_title:
        # Some stations append release years to the displayed title. Keep the
        # original metadata intact, but try the base title for Last.fm lookup.
        without_year_suffix = re.sub(
            r"\s*(?:[\[(](?:19|20)\d{2}[\])]|\s+[-–—]\s+(?:19|20)\d{2})\s*$",
            "",
            base,
        )
        _add(without_year_suffix)

        # Remove bracketed/parenthetical version text. This helps cases like
        # "Title (Original Mix)" or "Title [Radio Edit]" without changing display.
        without_brackets = re.sub(
            r"\s*[\[(][^\])]*(mix|edit|remaster|remastered|version|mono|stereo|live|explicit|clean|radio|club|extended|original|dub|instrumental)[^\])]*[\])]\s*",
            " ", base, flags=re.IGNORECASE
        )
        _add(without_brackets)

        # Remove trailing remix/version suffixes after a dash. Pure Lounge often
        # sends titles like "Straight To...Number One - Dreamcatcher's Mix";
        # Last.fm commonly indexes the base title more reliably.
        dash_version = re.split(
            r"\s+[-–—]\s+.*\b(mix|edit|remaster|remastered|version|radio|club|extended|original|dub|instrumental)\b.*$",
            base, maxsplit=1, flags=re.IGNORECASE
        )[0]
        _add(dash_version)

        # Try the conservative first segment for appended station/edition tags.
        for sep in (" / ", " | ", " — ", " – ", " - "):
            if sep in base:
                _add(base.split(sep, 1)[0])

        # Punctuation-tolerant variants. These help odd stream spellings such as
        # "To...Number" vs "To... Number" vs "To Number".
        _add(re.sub(r"\.\.\.", " ", base))
        _add(re.sub(r"[^\w\s']+", " ", base))
        if dash_version and dash_version != base:
            _add(re.sub(r"\.\.\.", " ", dash_version))
            _add(re.sub(r"[^\w\s']+", " ", dash_version))

        # Some streams put "Title - Remix" where Last.fm stores "Title (Remix)".
        m = re.match(r"^(.*?)\s+[-–—]\s+(.*\b(?:mix|edit|version|remaster|dub|instrumental)\b.*)$", base, flags=re.IGNORECASE)
        if m:
            _add(m.group(1) + " (" + m.group(2) + ")")
    else:
        # Handle common featuring syntax. Last.fm often prefers the primary artist.
        primary_artist = re.split(r"\s+(?:feat\.?|ft\.?|featuring|with|x|&|,|/)\s+", base, maxsplit=1, flags=re.IGNORECASE)[0]
        _add(primary_artist)
        _add(re.sub(r"[^\w\s']+", " ", primary_artist))

    return variants[:10]


def _lastfm_track_image_from_payload(track, fallback_artist, fallback_title, source_suffix=""):
    if not isinstance(track, dict):
        return {}
    album = track.get("album") or {}
    image_url = _lastfm_best_image(album.get("image") or [])
    if not image_url:
        image_url = _lastfm_best_image(track.get("image") or [])
    if not image_url:
        return {}
    artist_obj = track.get("artist") or {}
    if isinstance(artist_obj, dict):
        resolved_artist = str(artist_obj.get("name") or fallback_artist).strip()
    else:
        resolved_artist = str(artist_obj or fallback_artist).strip()
    return {
        "url": image_url,
        "source": "lastfm" + (":" + source_suffix if source_suffix else ""),
        "artist": resolved_artist,
        "title": str(track.get("name") or fallback_title).strip(),
        "album": str(album.get("title") or "").strip(),
        "updated_at": time.time(),
    }


def _lastfm_artist_image_fallback(artist_name, api_key):
    """Return a Last.fm artist image as a last visual fallback only."""
    artist_variants = _radio_art_text_variants(artist_name, is_title=False)
    for artist in artist_variants[:4]:
        try:
            url = (LASTFM_API_URL +
                   "?method=artist.getInfo"
                   "&artist=" + urllib.parse.quote(artist) +
                   "&api_key=" + urllib.parse.quote(api_key) +
                   "&autocorrect=1"
                   "&format=json")
            data = _meta_http_get(url, timeout=7)
            artist_obj = data.get("artist") or {}
            image_url = _lastfm_best_image(artist_obj.get("image") or [])
            if image_url:
                resolved_artist = str(artist_obj.get("name") or artist).strip()
                logger.info("Radio artwork Last.fm artist fallback match: %s -> %s", artist_name, resolved_artist)
                return {
                    "url": image_url,
                    "source": "lastfm:artist.getInfo",
                    "artist": resolved_artist,
                    "title": "",
                    "album": "",
                    "updated_at": time.time(),
                }
        except Exception as e:
            logger.debug("Radio artwork artist.getInfo miss for %s: %s", artist, e)
    return {}


def _fetch_lastfm_radio_cover_art(artist_name, track_title, api_key):
    """Fetch artwork for a radio now-playing item from Last.fm.

    This is metadata-only. It never touches playback, the queue, DAC lock,
    bit-perfect state, stream probing, or radio transport.
    """
    artist_variants = _radio_art_text_variants(artist_name, is_title=False)
    title_variants = _radio_art_text_variants(track_title, is_title=True)
    if not artist_variants or not title_variants:
        return {}

    attempts = []
    seen_attempts = set()
    for artist in artist_variants:
        for title in title_variants:
            k = (artist.lower(), title.lower())
            if k not in seen_attempts:
                seen_attempts.add(k)
                attempts.append((artist, title))
    attempts = attempts[:24]

    last_error = None
    logger.info("Radio artwork lookup variants: artist=%r title=%r attempts=%s",
                artist_name, track_title, attempts[:8])

    # Pass 1: exact/autocorrected track.getInfo over cleaned variants.
    for artist, title in attempts:
        try:
            url = (LASTFM_API_URL +
                   "?method=track.getInfo"
                   "&artist=" + urllib.parse.quote(artist) +
                   "&track=" + urllib.parse.quote(title) +
                   "&api_key=" + urllib.parse.quote(api_key) +
                   "&autocorrect=1"
                   "&format=json")
            data = _meta_http_get(url, timeout=7)
            track = data.get("track") or {}
            result = _lastfm_track_image_from_payload(track, artist, title, "track.getInfo")
            if result:
                logger.info("Radio artwork Last.fm track.getInfo match: %s - %s -> %s - %s",
                            artist_name, track_title, result.get("artist"), result.get("title"))
                return result
        except Exception as e:
            last_error = e
            logger.debug("Radio artwork track.getInfo miss for %s - %s: %s", artist, title, e)

    # Pass 2: Last.fm track.search with both specific and stripped titles.
    for artist, title in attempts[:12]:
        for query in ((artist + " " + title).strip(), title):
            try:
                url = (LASTFM_API_URL +
                       "?method=track.search"
                       "&track=" + urllib.parse.quote(query) +
                       "&artist=" + urllib.parse.quote(artist) +
                       "&api_key=" + urllib.parse.quote(api_key) +
                       "&format=json"
                       "&limit=12")
                data = _meta_http_get(url, timeout=7)
                matches = (((data.get("results") or {}).get("trackmatches") or {}).get("track") or [])
                if isinstance(matches, dict):
                    matches = [matches]
                for match in matches:
                    result = _lastfm_track_image_from_payload(match, artist, title, "track.search")
                    if result:
                        logger.info("Radio artwork Last.fm track.search match: %s - %s -> %s - %s",
                                    artist_name, track_title, result.get("artist"), result.get("title"))
                        return result
            except Exception as e:
                last_error = e
                logger.debug("Radio artwork track.search miss for %s - %s: %s", artist, title, e)

    # Pass 3: artist image fallback. This is not album cover art, so the source
    # label is explicit. It is only used when Last.fm cannot provide a track image.
    artist_fallback = _lastfm_artist_image_fallback(artist_name, api_key)
    if artist_fallback:
        artist_fallback["title"] = track_title
        return artist_fallback

    logger.info("Radio artwork Last.fm no image: artist=%r title=%r attempts=%d last_error=%s",
                artist_name, track_title, len(attempts), last_error or "none")
    return {}

def _set_current_radio_artwork(data):
    global CURRENT_RADIO_ARTWORK
    with _RADIO_ART_LOCK:
        CURRENT_RADIO_ARTWORK = dict(data or {})


def _get_current_radio_artwork():
    with _RADIO_ART_LOCK:
        return dict(CURRENT_RADIO_ARTWORK or {})


def _schedule_radio_artwork_lookup(meta):
    """Resolve radio track artwork asynchronously and cache by artist/title."""
    artist = str((meta or {}).get("artist", "") or "").strip()
    title = str((meta or {}).get("title", "") or "").strip()
    raw = str((meta or {}).get("raw", "") or "").strip()

    if not artist or not title:
        if raw:
            logger.info("Radio artwork skipped: incomplete metadata artist=%r title=%r raw=%r", artist, title, raw)
        _set_current_radio_artwork({})
        return

    key = _radio_art_cache_key(artist, title)
    if not key:
        _set_current_radio_artwork({})
        return

    now = time.time()
    cached_data = None
    already_running = False

    with _RADIO_ART_LOCK:
        entry = _RADIO_ART_CACHE.get(key)
        if entry:
            ttl = TTL_RADIO_ART if (entry.get("data") or {}).get("url") else TTL_RADIO_ART_MISS
            if now - entry.get("ts", 0) < ttl:
                cached_data = entry.get("data") or {}
        if cached_data is None:
            if key in _RADIO_ART_IN_FLIGHT:
                already_running = True
            else:
                _RADIO_ART_IN_FLIGHT.add(key)

    if cached_data is not None:
        _set_current_radio_artwork(cached_data)
        return
    if already_running:
        return

    # Keep the existing station logo visible while Last.fm resolves.
    _set_current_radio_artwork({
        "url": "",
        "source": "pending",
        "artist": artist,
        "title": title,
        "raw": raw,
        "updated_at": now,
    })

    current_station_url = str((CURRENT_RADIO or {}).get("url", "") or "")

    def _worker():
        data = {}
        try:
            api_key = (_SCROBBLE_CREDS.get("lastfm_api_key") or LASTFM_API_KEY or "").strip()
            if api_key and api_key != "YOUR_LASTFM_API_KEY":
                data = _fetch_lastfm_radio_cover_art(artist, title, api_key)
        except Exception as e:
            logger.debug("Radio Last.fm artwork lookup failed for %s - %s: %s", artist, title, e)

        if not data:
            data = {
                "url": "",
                "source": "none",
                "artist": artist,
                "title": title,
                "raw": raw,
                "updated_at": time.time(),
            }

        with _RADIO_ART_LOCK:
            _RADIO_ART_CACHE[key] = {"data": data, "ts": time.time()}
            _RADIO_ART_IN_FLIGHT.discard(key)

        try:
            still_same_station = RADIO_MODE and str((CURRENT_RADIO or {}).get("url", "") or "") == current_station_url
            still_same_track = str((CURRENT_RADIO_METADATA or {}).get("raw", "") or "").strip() == raw
            if still_same_station and still_same_track:
                _set_current_radio_artwork(data)
                if data.get("url"):
                    logger.info("Radio artwork resolved via Last.fm: %s - %s", artist, title)
        except Exception as e:
            logger.debug("Radio artwork stale-check failed: %s", e)

    threading.Thread(
        target=_worker,
        daemon=True,
        name="radio-lastfm-artwork",
    ).start()


def _fetch_tadb_artist_meta(artist_name):
    """Fetch artist artwork and metadata from TheAudioDB."""
    url  = TADB_BASE_URL + "searchartists.php?s=" + urllib.parse.quote(artist_name)
    data = _meta_http_get(url)
    artists = data.get("artists")
    if not artists:
        return {}
    a = artists[0]
    # Pick best available fanart (prefer wide banner)
    fanart = (a.get("strArtistFanart")  or
              a.get("strArtistFanart2") or
              a.get("strArtistFanart3") or "")
    thumb  = a.get("strArtistThumb") or ""
    # Biography -- prefer English
    bio_tadb = _strip_html(a.get("strBiographyEN") or "")
    return {
        "fanart":       fanart,
        "artist_thumb": thumb,
        "formed_year":  str(a.get("intFormedYear") or ""),
        "country":      a.get("strCountry")         or "",
        "genre":        a.get("strGenre")            or "",
        "style":        a.get("strStyle")            or "",
        "bio_tadb":     bio_tadb,
    }


def _fetch_all_meta(track_id, artist, title, api_key):
    """Fetch Last.fm + TADB in parallel, merge, and return a single dict."""
    results = {}

    def _do_lfm_artist():
        try:
            results["lfm_artist"] = _fetch_lastfm_artist_meta(artist, api_key)
        except Exception as e:
            logger.debug("meta lfm_artist failed: %s", e)

    def _do_lfm_track():
        try:
            results["lfm_track"] = _fetch_lastfm_track_meta(artist, title, api_key)
        except Exception as e:
            logger.debug("meta lfm_track failed: %s", e)

    def _do_tadb():
        try:
            results["tadb"] = _fetch_tadb_artist_meta(artist)
        except Exception as e:
            logger.debug("meta tadb failed: %s", e)

    threads = [
        threading.Thread(target=_do_lfm_artist, daemon=True),
        threading.Thread(target=_do_lfm_track,  daemon=True),
        threading.Thread(target=_do_tadb,        daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    la = results.get("lfm_artist", {})
    lt = results.get("lfm_track",  {})
    td = results.get("tadb",       {})

    # Merge tags: artist tags + track tags, deduplicated, max 8
    all_tags = []
    seen_tags = set()
    for tag in (la.get("tags") or []) + (lt.get("track_tags") or []):
        tl = tag.lower()
        if tl not in seen_tags:
            seen_tags.add(tl)
            all_tags.append(tag)
        if len(all_tags) >= 8:
            break

    # Pick best bio: prefer Last.fm (usually richer), fall back to TADB
    artist_bio = la.get("artist_bio") or td.get("bio_tadb") or ""

    return {
        "artist":          artist,
        "title":           title,
        "fanart":          td.get("fanart",       ""),
        "artist_thumb":    td.get("artist_thumb", ""),
        "formed_year":     td.get("formed_year",  ""),
        "country":         td.get("country",      ""),
        "genre":           td.get("genre",        ""),
        "style":           td.get("style",        ""),
        "tags":            all_tags,
        "listeners":       la.get("listeners",       ""),
        "playcount":       la.get("playcount",       ""),
        "artist_bio":      artist_bio,
        "track_summary":   lt.get("track_summary", ""),
        "similar_artists": la.get("similar_artists", []),
    }


def _load_meta_cache():
    """Load persisted meta cache, flushing entries older than 7 days."""
    global _META_CACHE
    try:
        if not os.path.exists(_META_CACHE_FILE):
            return
        with open(_META_CACHE_FILE, "r") as f:
            raw = json.load(f)
        cutoff = time.time() - (7 * 86400)
        kept   = {k: v for k, v in raw.items()
                  if isinstance(v, dict) and v.get("ts", 0) > cutoff}
        with _META_CACHE_LOCK:
            _META_CACHE.update(kept)
        logger.info("Meta cache loaded: %d entries (%d flushed)",
                    len(kept), len(raw) - len(kept))
    except Exception as e:
        logger.warning("load_meta_cache failed: %s", e)


def _save_meta_cache():
    """Persist meta cache to disk (daemon thread, max 500 entries)."""
    def _write():
        try:
            with _META_CACHE_LOCK:
                snapshot = dict(_META_CACHE)
            # Keep only the 500 most recently accessed entries
            if len(snapshot) > 500:
                sorted_keys = sorted(snapshot, key=lambda k: snapshot[k].get("ts", 0))
                for k in sorted_keys[:len(snapshot) - 500]:
                    del snapshot[k]
            os.makedirs(os.path.dirname(_META_CACHE_FILE), exist_ok=True)
            tmp = _META_CACHE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(snapshot, f)
            os.replace(tmp, _META_CACHE_FILE)
        except Exception as e:
            logger.warning("save_meta_cache failed: %s", e)
    threading.Thread(target=_write, daemon=True).start()


# =========================================================================
# Scrobbler -- Last.fm and ListenBrainz, fully non-blocking
# =========================================================================

import hashlib
import urllib.parse
import urllib.request

LASTFM_API_URL    = "https://ws.audioscrobbler.com/2.0/"
LASTFM_API_KEY    = "YOUR_LASTFM_API_KEY"     # set via /scrobble/lastfm/setup
LASTFM_API_SECRET = "YOUR_LASTFM_API_SECRET"  # set via /scrobble/lastfm/setup
LBZ_API_URL       = "https://api.listenbrainz.org/1/submit-listens"

_SCROBBLE_CREDS = {
    "lastfm_session_key": "",
    "lastfm_username":    "",
    "lastfm_api_key":     "",
    "lastfm_api_secret":  "",
    "lastfm_connected":   False,
    "lbz_token":          "",
    "lbz_connected":      False
}

_SCROBBLE_TIMER   = None
_SCROBBLE_LOCK    = threading.Lock()
_SCROBBLE_PENDING = None   # track_id currently being timed


def _save_scrobble_creds():
    try:
        os.makedirs(os.path.dirname(_SCROBBLE_FILE), exist_ok=True)
        tmp = _SCROBBLE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_SCROBBLE_CREDS, f)
        os.replace(tmp, _SCROBBLE_FILE)
    except Exception as e:
        logger.warning("save_scrobble_creds failed: %s", e)


def _load_scrobble_creds():
    global _SCROBBLE_CREDS
    try:
        if not os.path.exists(_SCROBBLE_FILE):
            return
        with open(_SCROBBLE_FILE, "r") as f:
            data = json.load(f)
        _SCROBBLE_CREDS.update(data)
        # Restore API key/secret into module-level vars so signing works
        global LASTFM_API_KEY, LASTFM_API_SECRET
        if _SCROBBLE_CREDS.get("lastfm_api_key"):
            LASTFM_API_KEY    = _SCROBBLE_CREDS["lastfm_api_key"]
        if _SCROBBLE_CREDS.get("lastfm_api_secret"):
            LASTFM_API_SECRET = _SCROBBLE_CREDS["lastfm_api_secret"]
        logger.info(
            "Scrobble creds loaded -- Last.fm: %s  ListenBrainz: %s",
            "connected" if _SCROBBLE_CREDS.get("lastfm_connected") else "not configured",
            "connected" if _SCROBBLE_CREDS.get("lbz_connected")   else "not configured"
        )
    except Exception as e:
        logger.warning("load_scrobble_creds failed: %s", e)


def _lastfm_sign(params):
    """Build Last.fm API method signature (md5 of sorted key+val pairs + secret)."""
    sig_str = "".join(k + params[k] for k in sorted(params))
    sig_str += LASTFM_API_SECRET
    return hashlib.md5(sig_str.encode("utf-8")).hexdigest()


def _lastfm_post(params):
    """POST to Last.fm API, return parsed JSON. Raises on API error."""
    params["api_key"] = LASTFM_API_KEY
    params["format"]  = "json"
    # Sign everything except 'format'
    params["api_sig"] = _lastfm_sign({k: v for k, v in params.items()
                                      if k != "format"})
    data = urllib.parse.urlencode(params).encode("utf-8")
    req  = urllib.request.Request(LASTFM_API_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lastfm_get_session(username, password, api_key, api_secret):
    """One-time auth: returns session key or raises."""
    global LASTFM_API_KEY, LASTFM_API_SECRET
    LASTFM_API_KEY    = api_key
    LASTFM_API_SECRET = api_secret
    params = {
        "method":   "auth.getMobileSession",
        "username": username,
        "password": password,
    }
    result = _lastfm_post(params)
    if "error" in result:
        raise Exception(result.get("message", "Last.fm auth failed"))
    return result["session"]["key"]


def _lastfm_now_playing(title, artist, album, duration, session_key):
    try:
        params = {
            "method":   "track.updateNowPlaying",
            "track":    title,
            "artist":   artist,
            "album":    album,
            "duration": str(int(duration)),
            "sk":       session_key,
        }
        _lastfm_post(params)
        logger.info("Last.fm now playing: %s - %s", artist, title)
    except Exception as e:
        logger.debug("Last.fm now playing failed: %s", e)


def _lastfm_scrobble(title, artist, album, duration, timestamp, session_key, chosen_by_user=None):
    params = {
        "method":    "track.scrobble",
        "track":     title,
        "artist":    artist,
        "album":     album,
        "duration":  str(int(duration)),
        "timestamp": str(int(timestamp)),
        "sk":        session_key,
    }
    if chosen_by_user is not None:
        params["chosenByUser"] = "1" if chosen_by_user else "0"
    result = _lastfm_post(params)
    if "error" in result:
        raise Exception(result.get("message", "Last.fm scrobble failed"))
    logger.info("Last.fm scrobbled: %s - %s", artist, title)


def _lbz_submit(title, artist, album, duration, timestamp, token, listen_type="single"):
    payload = {
        "listen_type": listen_type,
        "payload": [{
            "listened_at": int(timestamp),
            "track_metadata": {
                "track_name":   title,
                "artist_name":  artist,
                "release_name": album,
                "additional_info": {
                    "listening_from": "SROVA",
                    "duration_ms":    int(duration * 1000)
                }
            }
        }]
    }
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        LBZ_API_URL,
        data=data,
        headers={
            "Authorization": "Token " + token,
            "Content-Type":  "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("status") != "ok":
        raise Exception("ListenBrainz submit failed: " + str(result))
    logger.info("ListenBrainz scrobbled: %s - %s", artist, title)


def _lbz_validate_token(token):
    """Returns username string if token is valid, raises otherwise."""
    req = urllib.request.Request(
        "https://api.listenbrainz.org/1/validate-token",
        headers={"Authorization": "Token " + token},
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not result.get("valid"):
        raise Exception("Invalid ListenBrainz token")
    return result.get("user_name", "")


def _do_scrobble(track_id, title, artist, album, duration, timestamp, chosen_by_user=None):
    """Daemon thread: submit to both services if still on the same track."""
    with _SCROBBLE_LOCK:
        if _SCROBBLE_PENDING != track_id:
            return   # track changed before timer fired
    sk    = _SCROBBLE_CREDS.get("lastfm_session_key", "")
    token = _SCROBBLE_CREDS.get("lbz_token", "")
    if _SCROBBLE_CREDS.get("lastfm_connected") and sk:
        try:
            _lastfm_scrobble(title, artist, album, duration, timestamp, sk, chosen_by_user)
        except Exception as e:
            logger.warning("Last.fm scrobble error: %s", e)
    if _SCROBBLE_CREDS.get("lbz_connected") and token:
        try:
            _lbz_submit(title, artist, album, duration, timestamp, token)
        except Exception as e:
            logger.warning("ListenBrainz scrobble error: %s", e)


def schedule_scrobble(track_id, title, artist, album, duration, timestamp, chosen_by_user=None):
    """Cancel any pending scrobble and schedule a new one.
    Fires after max(30s, half duration) up to 4 minutes -- standard Last.fm rule."""
    global _SCROBBLE_TIMER, _SCROBBLE_PENDING
    with _SCROBBLE_LOCK:
        if _SCROBBLE_TIMER is not None:
            _SCROBBLE_TIMER.cancel()
            _SCROBBLE_TIMER = None
        if not (_SCROBBLE_CREDS.get("lastfm_connected") or
                _SCROBBLE_CREDS.get("lbz_connected")):
            return
        _SCROBBLE_PENDING = track_id
        delay = max(30, min(int(duration / 2), 240)) if duration > 0 else 30
        t = threading.Timer(
            delay, _do_scrobble,
            args=(track_id, title, artist, album, duration, timestamp, chosen_by_user)
        )
        t.daemon = True
        t.start()
        _SCROBBLE_TIMER = t


def cancel_scrobble():
    """Cancel pending scrobble timer (track skip or pause)."""
    global _SCROBBLE_TIMER, _SCROBBLE_PENDING
    with _SCROBBLE_LOCK:
        if _SCROBBLE_TIMER is not None:
            _SCROBBLE_TIMER.cancel()
            _SCROBBLE_TIMER = None
        _SCROBBLE_PENDING = None


def _scrobble_clean_text(value):
    text = str(value or "").strip()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _scrobble_norm_key(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _radio_metadata_reject_reason(artist, title, meta=None):
    artist = _scrobble_clean_text(artist)
    title = _scrobble_clean_text(title)
    raw = _scrobble_clean_text((meta or {}).get("raw", ""))
    if not artist or not title:
        return "missing_artist_or_title"

    bad_exact = {
        "unknown", "unknown artist", "unknown title", "untitled",
        "advert", "adverts", "advertisement", "commercial",
        "commercial break", "promo", "promotion", "jingle",
        "station id", "on air", "live", "music", "playlist",
    }
    for value in (artist, title, raw):
        if value and value.lower() in bad_exact:
            return "generic_metadata"

    combined = " ".join([artist, title, raw]).lower()
    if re.search(r"\b(advertisement|commercial break|sponsored|promo|station id)\b", combined):
        return "non_music_metadata"
    if re.search(r"https?://|www\.|\.com\b|\.net\b|\.org\b|\.bg\b", combined):
        return "url_like_metadata"

    station = CURRENT_RADIO or {}
    station_values = [
        station.get("name", ""),
        station.get("title", ""),
        station.get("display_name", ""),
    ]
    try:
        host = urlparse(str(station.get("url", "") or "")).hostname or ""
        if host:
            station_values.append(host)
    except Exception:
        pass
    artist_key = _scrobble_norm_key(artist)
    title_key = _scrobble_norm_key(title)
    raw_key = _scrobble_norm_key(raw)
    for station_value in station_values:
        station_key = _scrobble_norm_key(station_value)
        if not station_key:
            continue
        if station_key in {artist_key, title_key, raw_key}:
            return "station_metadata"
        if len(station_key) >= 6 and (station_key in artist_key or station_key in title_key):
            return "station_metadata"

    return ""


def _radio_scrobble_key(artist, title):
    return _scrobble_norm_key(artist) + "\0" + _scrobble_norm_key(title)


def build_current_scrobble_track(source=None):
    """Return source-neutral metadata for external scrobblers.

    Local tracks must never expose filesystem paths; use only the normalized
    library/player metadata already shown by status/session.
    """
    context_source = str(source or "").lower().strip()
    if context_source == "local" or (not context_source and _is_local_playback_context()):
        context_source = "local"
        context = LOCAL_PLAYBACK_CONTEXT if LOCAL_PLAYBACK_CONTEXT else CURRENT_CONTEXT
    elif context_source == "radio" or (not context_source and RADIO_MODE):
        context_source = "radio"
        meta = CURRENT_RADIO_METADATA or {}
        artist = _scrobble_clean_text(meta.get("artist", ""))
        title = _scrobble_clean_text(meta.get("title", ""))
        reject_reason = _radio_metadata_reject_reason(artist, title, meta)
        if reject_reason:
            return None
        artwork = _get_current_radio_artwork()
        album = _scrobble_clean_text(meta.get("album") or meta.get("release") or "")
        if not album and str(artwork.get("source", "")).startswith("lastfm:track"):
            album = _scrobble_clean_text(artwork.get("album", ""))
        track_id = "radio:" + _radio_scrobble_key(artist, title)
        return {
            "source": context_source,
            "id": track_id,
            "artist": artist,
            "title": title,
            "album": album,
            "duration": 0,
        }
    else:
        context_source = "tidal"
        context = CURRENT_CONTEXT

    track_id = str(context.get("track_id") or "").strip()
    title = str(context.get("title") or "").strip()
    artist = str(context.get("artist") or "").strip()
    album = str(context.get("album") or "").strip()
    try:
        duration = int(float(context.get("duration") or 0))
    except Exception:
        duration = 0

    if not track_id or not title or not artist:
        return None
    return {
        "source": context_source,
        "id": track_id,
        "artist": artist,
        "title": title,
        "album": album,
        "duration": duration,
    }


def start_current_scrobble(track=None, timestamp=None):
    """Send now-playing and schedule final scrobble for the current track."""
    track = track or build_current_scrobble_track()
    if not track:
        return False
    timestamp = timestamp or time.time()
    title = track.get("title") or ""
    artist = track.get("artist") or ""
    album = track.get("album") or ""
    duration = track.get("duration") or 0

    def _np():
        sk = _SCROBBLE_CREDS.get("lastfm_session_key", "")
        token = _SCROBBLE_CREDS.get("lbz_token", "")
        if _SCROBBLE_CREDS.get("lastfm_connected") and sk:
            _lastfm_now_playing(title, artist, album, duration, sk)
        if _SCROBBLE_CREDS.get("lbz_connected") and token:
            try:
                _lbz_submit(title, artist, album, duration,
                            timestamp, token,
                            listen_type="playing_now")
            except Exception as e:
                logger.debug("LBZ now playing failed: %s", e)

    threading.Thread(target=_np, daemon=True).start()
    chosen_by_user = False if track.get("source") == "radio" else None
    schedule_scrobble(str(track.get("id") or ""), title, artist, album,
                      duration, timestamp, chosen_by_user=chosen_by_user)
    return True


def handle_radio_scrobble_metadata(meta):
    global _RADIO_SCROBBLE_CURRENT_KEY
    artist = _scrobble_clean_text((meta or {}).get("artist", ""))
    title = _scrobble_clean_text((meta or {}).get("title", ""))
    key = _radio_scrobble_key(artist, title) if artist and title else ""
    reject_reason = _radio_metadata_reject_reason(artist, title, meta)

    if reject_reason:
        if _RADIO_SCROBBLE_CURRENT_KEY:
            cancel_scrobble()
        _RADIO_SCROBBLE_CURRENT_KEY = None
        logger.info("Radio scrobble skipped: %s artist=%r title=%r raw=%r",
                    reject_reason, artist, title, (meta or {}).get("raw", ""))
        return False

    if key and key == _RADIO_SCROBBLE_CURRENT_KEY:
        return False

    cancel_scrobble()
    _RADIO_SCROBBLE_CURRENT_KEY = key
    started = start_current_scrobble(build_current_scrobble_track("radio"), time.time())
    if started:
        logger.info("Radio scrobble scheduled: %s - %s", artist, title)
    return started


class HeadlessApp:

    MODE_LOOP    = PlayMode.LOOP
    MODE_ONE     = PlayMode.ONE
    MODE_SHUFFLE = PlayMode.SHUFFLE
    MODE_SMART   = PlayMode.SMART

    MODE_ICONS    = PlayMode.ICONS
    MODE_TOOLTIPS = PlayMode.TOOLTIPS

    # AlsaMmapRealtimePriority -- string label default + map (matches 1.8.0)
    ALSA_MMAP_REALTIME_PRIORITY_DEFAULT = AlsaMmapRealtimePriority.DEFAULT_LABEL
    ALSA_MMAP_REALTIME_PRIORITY_MAP     = AlsaMmapRealtimePriority.MAP

    ALSA_LATENCY_BUFFER_MS_DEFAULT  = 100
    ALSA_LATENCY_TARGET_MS_DEFAULT  = 10

    # AudioLatency map (matches 1.8.0)
    LATENCY_MAP = AudioLatency.MAP

    def on_next_track(self):              logger.info("Track ended")
    def update_tech_label(self, *a):
        global CURRENT_STREAM_INFO
        if not RADIO_MODE:
            return
        try:
            info = a[0] if a and isinstance(a[0], dict) else None
            if info is None:
                player = getattr(self, "player", None)
                info = dict(getattr(player, "stream_info", {}) or {}) if player is not None else {}
            else:
                info = dict(info)
            if info:
                logger.debug("Radio raw stream_info observed: %s", info)

            allowed_bit_depths = {8, 16, 20, 24, 32, 64}

            def _pick_source_bit_depth():
                if "source_depth" not in info:
                    return None
                raw = info.get("source_depth", 0)
                try:
                    value = int(float(raw or 0))
                except Exception:
                    value = 0
                if value <= 0:
                    return None
                if value in allowed_bit_depths:
                    return value
                logger.debug("Ignoring implausible radio source bit depth: %r", raw)
                return None

            codec = str(info.get("codec", "") or "").strip()
            if codec in ("-", "Loading..."):
                codec = ""

            try:
                sample_rate = int(float(info.get("source_rate", 0) or 0))
            except Exception:
                sample_rate = 0
            if sample_rate <= 0:
                sample_rate = None
                if info.get("rate") or info.get("output_rate"):
                    logger.debug(
                        "Radio stream_info has no source_rate; ignoring rate=%r output_rate=%r for visible quality",
                        info.get("rate"),
                        info.get("output_rate"),
                    )
            bit_depth = _pick_source_bit_depth()

            changed = {}
            if sample_rate and CURRENT_STREAM_INFO.get("sample_rate") != sample_rate:
                CURRENT_STREAM_INFO["sample_rate"] = sample_rate
                changed["sample_rate"] = sample_rate
                logger.info("Radio source sample rate observed: %s", sample_rate)
            if bit_depth and CURRENT_STREAM_INFO.get("bit_depth") != bit_depth:
                CURRENT_STREAM_INFO["bit_depth"] = bit_depth
                changed["bit_depth"] = bit_depth
            if codec and CURRENT_STREAM_INFO.get("codec") != codec:
                CURRENT_STREAM_INFO["codec"] = codec
                changed["codec"] = codec

        except Exception as e:
            logger.debug("Radio stream info observer failed: %s", e)
    def on_spectrum_data(self, *a, **kw): _on_spectrum_data_headless(self, *a, **kw)
    def on_viz_sync_offset_update(self,*a):pass
    def _schedule_cache_maintenance(self):pass
    def _account_scope_from_backend_user(self): return "guest"
    def _apply_account_scope(self, force=False): pass
    def _init_ui_refs(self):              pass
    def _detect_app_version(self):        return "headless-dev"
    def on_output_state_transition(self, *a): pass
    def record_diag_event(self, *a):      pass
    def set_diag_health(self, *a):        pass
    def show_output_notice(self, *a):     pass


def filtered_rust_event(event):
    global LAST_STATE, LAST_STATE_TIME
    if not isinstance(event, dict):
        return
    state = event.get("state")
    if not state:
        return
    now = time.time()
    if LAST_STATE == "Paused" and state == "Playing":
        if now - LAST_STATE_TIME < 1:
            return
    LAST_STATE      = state
    LAST_STATE_TIME = now
    logger.info("Rust audio event state: %s", state)


def parse_quality_from_log(q):
    try:
        m = re.search(r"(\d+)bit/(\d+)Hz", q)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None, None


def _playback_audio_output_ready():
    """Return True when the selected DAC/output is already held for playback."""
    player = APP_INSTANCE.player if APP_INSTANCE is not None else None
    if player is None:
        return False
    try:
        return bool(getattr(player, "exclusive_lock_mode", False))
    except Exception:
        return False


def _ensure_audio_output_for_playback(reason="playback"):
    """Auto-lock the currently selected DAC before user-initiated playback.

    This keeps Release DAC as an explicit handoff action, but removes the
    need to manually press Exclusive Mode before starting SROVA playback.
    The actual output application still goes through configure_audio().
    """
    _require_audio_output_for_playback(reason)
    if _playback_audio_output_ready():
        return False
    logger.info("Auto-locking DAC before %s: driver=%s device=%s",
                reason, ALSA_DRIVER, ALSA_DEVICE)
    configure_audio()
    return True


def _network_music_roots():
    """Return configured Network Music roots without requiring them to be online.

    Network folder rows are saved configuration, not a live mount inventory.
    Offline or idle shares therefore remain visible in Settings. Scanner and
    playback availability continue to be controlled by _local_test_roots().
    """
    return _saved_music_root_values(_NETWORK_MUSIC_ROOTS_ENV)



def _local_test_roots():
    """Return configured roots without touching their filesystems."""
    return _saved_music_root_values(_LOCAL_TEST_ROOTS_ENV)


def _active_local_test_roots(roots=None):
    """Return roots currently safe to index or use for local playback."""
    configured = list(
        _local_test_roots() if roots is None else roots
    )
    try:
        network_roots = set(_network_music_roots())
    except Exception:
        network_roots = set()

    active = []
    for root in configured:
        text = os.path.normpath(
            os.path.abspath(os.path.expanduser(str(root or "").strip()))
        )
        if not text or text in active:
            continue

        # Mountinfo is checked before any filesystem access. This safely
        # recognises active NFS/CIFS mounts and avoids touching idle autofs.
        if _network_mount_entry_for_path(text):
            active.append(text)
            continue

        if _autofs_mount_for_path(text):
            continue

        # A configured Network Music root without an active backing network
        # mount remains visible in Settings but is excluded from indexing.
        if text in network_roots:
            continue

        try:
            diagnostics = _local_library_path_diagnostics(text)
        except Exception:
            continue

        if not diagnostics.get("directory"):
            continue
        if not diagnostics.get("readable"):
            continue

        # Paths below /DATA, /mnt, /media and /srv are mount-style roots.
        # Do not scan an empty fallback directory when its mount is absent.
        if (
            diagnostics.get("mount_expected")
            and not diagnostics.get("mounted")
        ):
            continue

        active.append(text)

    return active


def _music_root_availability():
    configured = _local_test_roots()
    active = _active_local_test_roots(configured)
    return {
        "configured_roots": configured,
        "active_roots": active,
        "unavailable_roots": [
            root for root in configured if root not in active
        ],
    }


def _path_inside_root(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except Exception:
        return False


def _validate_local_test_file(raw_path):
    requested = str(raw_path or "").strip()
    if not requested:
        raise ValueError("path is required")

    roots = _active_local_test_roots()
    if not roots:
        raise ValueError("No active local music roots are available.")

    real_path = os.path.realpath(os.path.expanduser(requested))
    if not any(_path_inside_root(real_path, root) for root in roots):
        raise PermissionError("path is outside allowlisted local test roots")
    if not os.path.isfile(real_path):
        raise ValueError("path is not a regular file")

    ext = os.path.splitext(real_path)[1].lower()
    if ext not in _LOCAL_TEST_AUDIO_EXTENSIONS:
        raise ValueError("unsupported local test audio extension")
    return real_path


def _local_library_index():
    return LocalLibraryIndex(roots=_active_local_test_roots())


_LOCAL_LYRICS_FLAC_MAX_BLOCK = 16 * 1024 * 1024
_LOCAL_LYRICS_TAGS = ("lyrics", "unsyncedlyrics", "unsynced lyrics")


def _lyrics_payload_from_text(raw):
    text_value = str(raw or "").strip()
    if not text_value:
        return {"error": "no_lyrics"}
    if text_value.startswith("[") and "]" in text_value:
        lines = []
        for line in text_value.splitlines():
            line = line.strip()
            if not line:
                continue
            tags = re.findall(r'\[(\d+):(\d+(?:\.\d+)?)\]', line)
            text = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', line).strip()
            for m, s in tags:
                ms = int(m) * 60000 + int(float(s) * 1000)
                lines.append({"ms": ms, "text": text})
        lines.sort(key=lambda x: x["ms"])
        lines = [line for line in lines if line["text"]]
        if lines:
            return {"synced": True, "lines": lines}
    return {"synced": False, "text": text_value}


def _local_flac_embedded_lyrics(real_path):
    try:
        with open(real_path, "rb") as f:
            if f.read(4) != b"fLaC":
                return None
            for _ in range(64):
                header = f.read(4)
                if len(header) != 4:
                    break
                is_last = bool(header[0] & 0x80)
                block_type = header[0] & 0x7f
                length = int.from_bytes(header[1:4], "big")
                if length > _LOCAL_LYRICS_FLAC_MAX_BLOCK:
                    f.seek(length, os.SEEK_CUR)
                    if is_last:
                        break
                    continue
                data = f.read(length)
                if len(data) != length:
                    break
                if block_type == 4:
                    if len(data) < 8:
                        return None
                    vendor_len = int.from_bytes(data[0:4], "little")
                    pos = 4 + vendor_len
                    if pos + 4 > len(data):
                        return None
                    count = int.from_bytes(data[pos:pos + 4], "little")
                    pos += 4
                    found = {}
                    for _ in range(min(count, 512)):
                        if pos + 4 > len(data):
                            break
                        item_len = int.from_bytes(data[pos:pos + 4], "little")
                        pos += 4
                        if pos + item_len > len(data):
                            break
                        item = data[pos:pos + item_len].decode("utf-8", "replace")
                        pos += item_len
                        if "=" not in item:
                            continue
                        key, value = item.split("=", 1)
                        key = key.strip().lower()
                        value = value.strip()
                        if key in _LOCAL_LYRICS_TAGS and value and key not in found:
                            found[key] = value
                    for key in _LOCAL_LYRICS_TAGS:
                        if found.get(key):
                            return found[key]
                    return None
                if is_last:
                    break
    except Exception:
        return None
    return None


def _local_library_lyrics_payload(track_id):
    roots = _local_test_roots()
    if not roots:
        return {"error": "no_lyrics"}
    track_id = str(track_id or "").strip()
    if not track_id:
        return {"error": "no_lyrics"}
    try:
        track = _local_library_index().track_by_id(track_id)
    except LocalLibraryBusyError:
        return {"error": "local_library_busy", "busy": True}
    except Exception:
        return {"error": "no_lyrics"}
    if not track:
        return {"error": "no_lyrics"}

    real_path = os.path.realpath(str(track.get("cue_audio_path") or track.get("path") or ""))
    if not any(_path_inside_root(real_path, root) for root in roots):
        return {"error": "no_lyrics"}
    if not os.path.isfile(real_path):
        return {"error": "no_lyrics"}
    if os.path.splitext(real_path)[1].lower() != ".flac":
        return {"error": "no_lyrics"}

    return _lyrics_payload_from_text(_local_flac_embedded_lyrics(real_path))


def _local_library_maintenance_busy_payload(extra=None):
    state = _local_library_status_payload()
    payload = {
        "ok": False,
        "busy": True,
        "error": "local_library_rebuild_running",
        "message": "Local Music is rebuilding. Please wait until the scan finishes.",
        "scan_running": bool(state.get("scan_running")),
        "rebuild_running": bool(state.get("rebuild_running")),
        "maintenance_mode": state.get("maintenance_mode") or "local_library_rebuild",
    }
    payload.update(extra or {})
    return payload


def _local_library_status_payload():
    _sync_local_library_artwork_policy()
    availability = _music_root_availability()
    try:
        # Status only reads database metadata. Passing no roots avoids any
        # additional normalization or filesystem access.
        data = LocalLibraryIndex(roots=[]).status()
        data["roots"] = availability["active_roots"]
        data["configured_roots"] = availability["configured_roots"]
        data["unavailable_roots"] = availability["unavailable_roots"]
        return data
    except LocalLibraryBusyError:
        return {
            "ok": True,
            "busy": True,
            "error": "local_library_busy",
            "roots": availability["active_roots"],
            "configured_roots": availability["configured_roots"],
            "unavailable_roots": availability["unavailable_roots"],
            "scan_running": True,
            "rebuild_running": local_library_rebuild_running(),
            "maintenance_mode": (
                "local_library_rebuild"
                if local_library_rebuild_running()
                else None
            ),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "roots": availability["active_roots"],
            "configured_roots": availability["configured_roots"],
            "unavailable_roots": availability["unavailable_roots"],
        }


def _mountinfo_unescape(value):
    return (
        str(value or "")
        .replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _same_or_child_path(path, root):
    try:
        path = os.path.abspath(str(path or ""))
        root = os.path.abspath(str(root or ""))
    except Exception:
        return False
    root = root.rstrip(os.sep) or os.sep
    return path == root or path.startswith(root + os.sep)


def _autofs_mount_for_path(path):
    """Return the autofs mountpoint containing path, without stat()ing the path."""
    try:
        target = os.path.abspath(os.path.expanduser(str(path or "")))
    except Exception:
        return ""
    if not target:
        return ""
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if " - " not in line:
                    continue
                pre, post = line.rstrip("\n").split(" - ", 1)
                fields = pre.split()
                post_fields = post.split()
                if len(fields) < 5 or not post_fields:
                    continue
                mountpoint = _mountinfo_unescape(fields[4])
                fstype = post_fields[0]
                if fstype == "autofs" and _same_or_child_path(target, mountpoint):
                    return mountpoint
    except Exception:
        return ""
    return ""


def _local_library_network_scan_preflight(roots, action="scan"):
    """Wake each exact idle autofs root once, then perform one recheck."""
    try:
        network_roots = set(_network_music_roots())
    except Exception:
        network_roots = set()

    blocked = _local_library_autofs_blocked_network_roots(roots)
    wake_attempted = []

    if blocked:
        for item in blocked:
            root = str((item or {}).get("root") or "").strip()
            if not root:
                continue
            wake_attempted.append(root)
            _wake_exact_autofs_path(root)

        # Exactly one bounded post-wake mountinfo recheck.
        blocked = _local_library_autofs_blocked_network_roots(roots)

    if not blocked:
        _sync_local_library_artwork_policy(roots)
        return None

    logger.warning(
        "Blocked Local Music %s after bounded autofs wake/recheck "
        "on root(s): %s",
        action,
        blocked,
    )
    return {
        "ok": False,
        "error": _NETWORK_AUTOMOUNT_SCAN_ERROR,
        "message": _NETWORK_AUTOMOUNT_SCAN_MESSAGE,
        "roots": list(roots or []),
        "blocked_roots": blocked,
        "wake_attempted_roots": wake_attempted,
        "network_roots": list(network_roots),
        "local_roots": [
            root for root in (roots or [])
            if root not in network_roots
        ],
        "scan_running": False,
        "rebuild_running": False,
        "maintenance_mode": None,
    }


def _local_library_mountinfo_entries():
    entries = []
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if " - " not in line:
                    continue
                left, right = line.split(" - ", 1)
                left_parts = left.split()
                right_parts = right.split()
                if len(left_parts) < 5 or len(right_parts) < 3:
                    continue
                mount_point = _mountinfo_unescape(left_parts[4])
                fstype = right_parts[0]
                source = right_parts[1]
                entries.append({
                    "mount_point": mount_point,
                    "fstype": fstype,
                    "source": source,
                    "line": line,
                })
    except Exception:
        return []
    return entries


def _active_non_autofs_mount_for_path(path):
    try:
        target = os.path.normpath(os.path.abspath(os.path.expanduser(str(path or ""))))
    except Exception:
        target = str(path or "").strip()
    if not target:
        return None

    best = None
    for entry in _local_library_mountinfo_entries():
        mount_point = entry.get("mount_point") or ""
        fstype = entry.get("fstype") or ""
        if not mount_point or fstype == "autofs":
            continue
        if _same_or_child_path(target, mount_point):
            if best is None or len(mount_point) > len(best.get("mount_point") or ""):
                best = entry
    return best


def _network_mount_entry_for_path(path):
    entry = _active_non_autofs_mount_for_path(path)
    fstype = str((entry or {}).get("fstype") or "").lower()
    if fstype in _NETWORK_FILESYSTEM_TYPES:
        return entry
    return None


def _wake_exact_autofs_path(path, timeout=_NETWORK_AUTOFS_WAKE_TIMEOUT_SECONDS):
    """Trigger only the configured path in a bounded child process."""
    root = str(path or "").strip()
    if not root or not os.path.isabs(root):
        return False

    argv = [
        sys.executable,
        "-c",
        "import os,sys; it=os.scandir(sys.argv[1]); next(it,None); it.close()",
        root,
    ]
    process = None
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return process.wait(timeout=max(0.1, float(timeout))) == 0
    except subprocess.TimeoutExpired:
        logger.warning("Timed out waking idle Network Music automount: %s", root)
        try:
            process.kill()
        except Exception:
            pass
        try:
            process.wait(timeout=0.2)
        except Exception:
            pass
        return False
    except Exception as exc:
        logger.info("Could not wake Network Music automount %s: %s", root, exc)
        return False


def _local_library_env_value_from_files(key):
    for env_path in ("/var/lib/srova/srova.env", "/etc/srova/srova.env"):
        try:
            with open(env_path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    name, value = line.split("=", 1)
                    if name.strip() == key:
                        return value.strip().strip('"').strip("'")
        except Exception:
            continue
    return ""


def _local_library_split_root_value(raw):
    text = str(raw or "").strip()
    if not text:
        return []
    # Existing SROVA root values are simple Linux paths. Accept common separators
    # for future multi-root values without statting/touching the filesystem.
    for sep in ("\n", ";", ","):
        text = text.replace(sep, ":")
    out = []
    for item in text.split(":"):
        item = item.strip()
        if not item:
            continue
        try:
            item = os.path.normpath(os.path.abspath(os.path.expanduser(item)))
        except Exception:
            pass
        if item and item not in out:
            out.append(item)
    return out


def _local_library_network_roots():
    key = globals().get("_NETWORK_MUSIC_ROOTS_ENV", "SROVA_NETWORK_MUSIC_ROOTS")
    return _saved_music_root_values(key)


def _local_library_autofs_blocked_network_roots(roots=None):
    roots_to_check = list(roots or _local_library_network_roots())
    blocked = []
    for root in roots_to_check:
        try:
            root_text = os.path.normpath(os.path.abspath(os.path.expanduser(str(root or "").strip())))
        except Exception:
            root_text = str(root or "").strip()
        if not root_text:
            continue

        autofs_mount = _autofs_mount_for_path(root_text)
        if not autofs_mount:
            continue

        # Option B:
        # systemd autofs is allowed when a real backing mount is already active
        # for the same path, e.g. /mnt/music autofs + active nfs4 mount.
        backing = _active_non_autofs_mount_for_path(root_text)
        if backing:
            continue

        blocked.append({
            "root": root_text,
            "autofs_mount": autofs_mount,
        })
    return blocked


def _sync_local_library_artwork_policy(roots=None):
    blocked = _local_library_autofs_blocked_network_roots(roots)
    if blocked:
        os.environ[_LOCAL_ARTWORK_LOOKUP_DISABLED_ENV] = "1"
    else:
        os.environ.pop(_LOCAL_ARTWORK_LOOKUP_DISABLED_ENV, None)
    return blocked

def _local_library_scan_payload():
    configured = _local_test_roots()
    if not configured:
        return {
            "ok": False,
            "error": "No local library roots configured. "
                     "Set SROVA_LOCAL_TEST_ROOTS.",
            "roots": [],
            "configured_roots": [],
            "unavailable_roots": [],
        }

    blocked = _local_library_network_scan_preflight(
        configured,
        action="scan",
    )
    if blocked:
        return blocked

    active = _active_local_test_roots(configured)
    unavailable = [
        root for root in configured if root not in active
    ]
    if not active:
        return {
            "ok": False,
            "error": "local_library_roots_unavailable",
            "message": "None of the saved music folders are currently available.",
            "roots": [],
            "configured_roots": configured,
            "unavailable_roots": unavailable,
            "scan_running": False,
        }

    try:
        result = LocalLibraryIndex(roots=active).scan()
        if isinstance(result, dict):
            result["configured_roots"] = configured
            result["unavailable_roots"] = unavailable
        return result
    except LocalLibraryBusyError:
        return {
            "ok": False,
            "error": "local_library_busy",
            "busy": True,
            "scan_running": False,
            "roots": active,
            "configured_roots": configured,
            "unavailable_roots": unavailable,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "roots": active,
            "configured_roots": configured,
            "unavailable_roots": unavailable,
        }


def _local_library_rebuild_payload():
    configured = _local_test_roots()
    if not configured:
        return {
            "ok": False,
            "error": "No local library roots configured. "
                     "Set SROVA_LOCAL_TEST_ROOTS.",
            "roots": [],
            "configured_roots": [],
            "unavailable_roots": [],
            "scan_running": False,
            "rebuild_running": False,
        }

    blocked = _local_library_network_scan_preflight(
        configured,
        action="rebuild",
    )
    if blocked:
        return blocked

    active = _active_local_test_roots(configured)
    unavailable = [
        root for root in configured if root not in active
    ]

    # Rebuild deletes and recreates the database. It is never safe to rebuild
    # only the currently available subset because rows belonging to an offline
    # configured root would be lost.
    if unavailable:
        return {
            "ok": False,
            "error": "local_library_rebuild_roots_unavailable",
            "message": (
                "Rebuild was not started because one or more saved music "
                "folders are unavailable."
            ),
            "roots": active,
            "configured_roots": configured,
            "unavailable_roots": unavailable,
            "scan_running": False,
            "rebuild_running": False,
        }

    status = _local_library_status_payload()
    if status.get("scan_running") or status.get("rebuild_running"):
        return {
            "ok": False,
            "error": "local_library_scan_running",
            "busy": True,
            "roots": active,
            "configured_roots": configured,
            "unavailable_roots": [],
            "scan_running": bool(status.get("scan_running")),
            "rebuild_running": bool(status.get("rebuild_running")),
            "maintenance_mode": status.get("maintenance_mode"),
        }

    def _run_rebuild():
        try:
            LocalLibraryIndex(roots=active).rebuild_and_scan()
        except Exception as exc:
            logger.warning("Local library rebuild failed: %s", exc)

    threading.Thread(target=_run_rebuild, daemon=True).start()
    deadline = time.time() + 0.5
    while time.time() < deadline and not local_library_rebuild_running():
        time.sleep(0.01)

    return {
        "ok": True,
        "rebuild_started": True,
        "scan_running": True,
        "rebuild_running": True,
        "maintenance_mode": "local_library_rebuild",
        "roots": active,
        "configured_roots": configured,
        "unavailable_roots": [],
    }


def _local_library_cleanup_stale_payload():
    configured = _local_test_roots()
    if not configured:
        return {
            "ok": False,
            "error": "No local library roots configured. "
                     "Set SROVA_LOCAL_TEST_ROOTS.",
            "roots": [],
            "configured_roots": [],
            "unavailable_roots": [],
            "stale_before": 0,
            "deleted": 0,
            "scan_running": False,
        }

    blocked = _local_library_network_scan_preflight(
        configured,
        action="cleanup",
    )
    if blocked:
        return blocked

    active = _active_local_test_roots(configured)
    unavailable = [
        root for root in configured if root not in active
    ]
    if not active:
        return {
            "ok": False,
            "error": "local_library_roots_unavailable",
            "message": "None of the saved music folders are currently available.",
            "roots": [],
            "configured_roots": configured,
            "unavailable_roots": unavailable,
            "stale_before": 0,
            "deleted": 0,
            "scan_running": False,
        }

    try:
        result = LocalLibraryIndex(roots=active).cleanup_stale()
        if isinstance(result, dict):
            result["configured_roots"] = configured
            result["unavailable_roots"] = unavailable
        return result
    except LocalLibraryBusyError:
        return {
            "ok": False,
            "error": "local_library_busy",
            "busy": True,
            "roots": active,
            "configured_roots": configured,
            "unavailable_roots": unavailable,
            "stale_before": 0,
            "deleted": 0,
            "scan_running": False,
        }
    except Exception:
        return {
            "ok": False,
            "error": "local_library_cleanup_failed",
            "roots": active,
            "configured_roots": configured,
            "unavailable_roots": unavailable,
            "stale_before": 0,
            "deleted": 0,
            "scan_running": False,
        }


def _local_library_tracks_payload(limit=1000):
    _sync_local_library_artwork_policy()
    if local_library_rebuild_running():
        return _local_library_maintenance_busy_payload({"count": 0, "tracks": []})
    try:
        return _local_library_index().tracks(limit=limit)
    except LocalLibraryBusyError:
        return {
            "ok": False,
            "error": "local_library_busy",
            "busy": True,
            "scan_running": True,
            "count": 0,
            "tracks": [],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _local_library_artists_payload(limit=500):
    _sync_local_library_artwork_policy()
    if local_library_rebuild_running():
        return _local_library_maintenance_busy_payload({"count": 0, "artists": []})
    try:
        return _local_library_index().artists(limit=limit)
    except LocalLibraryBusyError:
        return {
            "ok": False,
            "error": "local_library_busy",
            "busy": True,
            "scan_running": True,
            "count": 0,
            "artists": [],
        }
    except Exception:
        return {"ok": False, "error": "local_library_artists_failed"}


def _local_library_albums_payload(limit=500, artist=None, sort="latest"):
    _sync_local_library_artwork_policy()
    if local_library_rebuild_running():
        return _local_library_maintenance_busy_payload({"count": 0, "albums": []})
    try:
        return _local_library_index().albums(limit=limit, artist=artist, sort=sort)
    except LocalLibraryBusyError:
        return {
            "ok": False,
            "error": "local_library_busy",
            "busy": True,
            "scan_running": True,
            "count": 0,
            "albums": [],
        }
    except Exception:
        return {"ok": False, "error": "local_library_albums_failed"}


def _local_library_search_payload(query="", limit=100):
    _sync_local_library_artwork_policy()
    if local_library_rebuild_running():
        return _local_library_maintenance_busy_payload({
            "query": str(query or "").strip(),
            "count": 0,
            "songs": [],
            "tracks": [],
            "albums": [],
            "artists": [],
        })
    try:
        return _local_library_index().search(query=query, limit=limit)
    except LocalLibraryBusyError:
        return {
            "ok": False,
            "error": "local_library_busy",
            "busy": True,
            "scan_running": True,
            "query": str(query or "").strip(),
            "count": 0,
            "tracks": [],
        }
    except Exception:
        return {"ok": False, "error": "local_library_search_failed"}


def _local_library_album_payload(artist="", album="", album_id=""):
    _sync_local_library_artwork_policy()
    if local_library_rebuild_running():
        return _local_library_maintenance_busy_payload({
            "artist": str(artist or "").strip(),
            "album": str(album or "").strip(),
            "album_id": str(album_id or "").strip(),
            "track_count": 0,
            "tracks": [],
        })
    try:
        return _local_library_index().album_detail(artist=artist, album=album, album_id=album_id)
    except LocalLibraryBusyError:
        return {
            "ok": False,
            "error": "local_library_busy",
            "busy": True,
            "scan_running": True,
            "artist": str(artist or "").strip(),
            "album": str(album or "").strip(),
            "album_id": str(album_id or "").strip(),
            "track_count": 0,
            "tracks": [],
        }
    except Exception:
        return {"ok": False, "error": "local_library_album_failed"}


def _local_library_artwork_file(path="", embedded_path=""):
    _sync_local_library_artwork_policy()
    roots = _local_test_roots()
    if not roots:
        raise ValueError("No local library roots configured. Set SROVA_LOCAL_TEST_ROOTS.")
    index = LocalLibraryIndex(roots=roots)
    if embedded_path:
        return index.embedded_artwork_file(embedded_path)
    return index.artwork_file(path)


def _local_library_artist_payload(artist="", limit=1000):
    _sync_local_library_artwork_policy()
    if local_library_rebuild_running():
        return _local_library_maintenance_busy_payload({
            "artist": str(artist or "").strip(),
            "album_count": 0,
            "track_count": 0,
            "albums": [],
            "tracks": [],
        })
    try:
        return _local_library_index().artist_detail(artist=artist, limit=limit)
    except LocalLibraryBusyError:
        return {
            "ok": False,
            "error": "local_library_busy",
            "busy": True,
            "scan_running": True,
            "artist": str(artist or "").strip(),
            "album_count": 0,
            "track_count": 0,
            "albums": [],
            "tracks": [],
        }
    except Exception:
        return {"ok": False, "error": "local_library_artist_failed"}


def _local_library_play_payload(payload):
    global PLAY_QUEUE, QUEUE_INDEX, ORIGINAL_QUEUE, PLAY_QUEUE_META_CACHE, PLAY_QUEUE_PENDING_AFTER_CONTEXT
    if local_library_rebuild_running():
        return _local_library_maintenance_busy_payload({
            "source": "local",
            "id": str((payload or {}).get("id") or "").strip(),
        })
    roots = _local_test_roots()
    if not roots:
        return {
            "ok": False,
            "error": "No local library roots configured. Set SROVA_LOCAL_TEST_ROOTS.",
            "source": "local",
        }
    track_id = str((payload or {}).get("id") or "").strip()
    if not track_id:
        return {"ok": False, "error": "id_required", "source": "local"}
    raw_track_ids = (payload or {}).get("track_ids", [])
    if not isinstance(raw_track_ids, list):
        raw_track_ids = []
    track_ids = []
    seen_track_ids = set()
    for raw_id in raw_track_ids:
        tid = str(raw_id or "").strip()
        if tid and tid.startswith("local:") and tid not in seen_track_ids:
            track_ids.append(tid)
            seen_track_ids.add(tid)
    if track_id not in seen_track_ids:
        track_ids.insert(0, track_id)
    try:
        start_index = int((payload or {}).get("start_index", track_ids.index(track_id)))
    except Exception:
        start_index = track_ids.index(track_id) if track_id in track_ids else 0
    if not (0 <= start_index < len(track_ids)) or track_ids[start_index] != track_id:
        start_index = track_ids.index(track_id) if track_id in track_ids else 0
    context_type = str((payload or {}).get("context_type") or "").strip()
    context_id = str((payload or {}).get("context_id") or "").strip()
    context_title = str((payload or {}).get("context_title") or "").strip()
    try:
        index = LocalLibraryIndex(roots=roots)
        track = index.track_by_id(track_id)
    except LocalLibraryBusyError:
        return {
            "ok": False,
            "error": "local_library_busy",
            "busy": True,
            "source": "local",
            "id": track_id,
        }
    except Exception:
        return {"ok": False, "error": "local_library_lookup_failed", "source": "local", "id": track_id}
    if not track:
        return {"ok": False, "error": "track_not_found", "source": "local", "id": track_id}

    context_tracks = {}
    if context_type == "local_album" and track_ids:
        try:
            found_ids = set()
            for tid in track_ids:
                ctx_track = index.track_by_id(tid)
                if not ctx_track:
                    continue
                ctx_real_path = os.path.realpath(str(ctx_track.get("cue_audio_path") or ctx_track.get("path") or ""))
                if any(_path_inside_root(ctx_real_path, root) for root in roots):
                    found_ids.add(tid)
                    context_tracks[tid] = ctx_track
            track_ids = [tid for tid in track_ids if tid in found_ids]
            if track_id not in track_ids:
                return {"ok": False, "error": "track_not_found_in_context", "source": "local", "id": track_id}
            start_index = track_ids.index(track_id)
        except LocalLibraryBusyError:
            return {
                "ok": False,
                "error": "local_library_busy",
                "busy": True,
                "source": "local",
                "id": track_id,
            }
        except Exception:
            return {"ok": False, "error": "local_library_context_failed", "source": "local", "id": track_id}

    real_path = os.path.realpath(str(track.get("cue_audio_path") or track.get("path") or ""))
    if not any(_path_inside_root(real_path, root) for root in roots):
        return {"ok": False, "error": "path_outside_local_roots", "source": "local", "id": track_id}
    if not os.path.isfile(real_path):
        return {"ok": False, "error": "file_not_found", "source": "local", "id": track_id, "path": real_path}
    try:
        _require_audio_output_for_playback("local playback")
    except AudioOutputUnavailable as e:
        payload = e.to_payload()
        payload.update({"source": "local", "id": track_id})
        return payload

    _invalidate_tidal_stream_resolution("local-playback")
    queue_meta = PLAY_QUEUE_META_CACHE.get(track_id, {}) or {}
    artwork_url = (
        (payload or {}).get("artwork_url")
        or (payload or {}).get("cover")
        or queue_meta.get("artwork_url")
        or queue_meta.get("cover")
        or None
    )
    if not artwork_url:
        try:
            album_lookup_id = context_id if context_id.startswith("local-album:") else ""
            if album_lookup_id:
                album_payload = index.album_detail(album_id=album_lookup_id)
            else:
                album_payload = index.album_detail(
                    artist=track.get("artist") or "",
                    album=track.get("album") or "",
                )
            artwork_url = album_payload.get("artwork_url") or None
        except Exception:
            artwork_url = None
    file_uri = _local_test_file_uri(real_path)
    playback_meta = {
        "track_id": track.get("id"),
        "title": track.get("title"),
        "artist": track.get("artist"),
        "album": track.get("album"),
        "duration": int(track.get("duration") or 0),
        "codec": track.get("codec") or _local_test_codec(real_path),
        "sample_rate": track.get("sample_rate"),
        "bit_depth": track.get("bit_depth"),
        "channels": track.get("channels"),
        "cover": artwork_url,
        "context_title": context_title or "Local Library",
        "context_type": context_type or "local",
        "context_id": context_id or track.get("id"),
        "is_cue_track": int(track.get("is_cue_track") or 0),
        "cue_path": track.get("cue_path") or "",
        "cue_audio_path": track.get("cue_audio_path") or "",
        "cue_track_number": track.get("cue_track_number"),
        "cue_start_seconds": track.get("cue_start_seconds"),
        "cue_end_seconds": track.get("cue_end_seconds"),
    }
    if context_type == "local_album" and track_ids:
        playback_meta["track_ids"] = track_ids
        playback_meta["current_index"] = start_index
        playback_meta["album_id"] = context_id if context_id.startswith("local-album:") else ""
        with _QUEUE_LOCK:
            PLAY_QUEUE.clear()
            ORIGINAL_QUEUE.clear()
            PLAY_QUEUE_META_CACHE.clear()
            cue_album_visible_from_current = False
            try:
                cue_album_visible_from_current = int(track.get("is_cue_track") or 0) == 1
            except Exception:
                cue_album_visible_from_current = False
            visible_track_ids = track_ids
            visible_start_index = start_index
            for tid in visible_track_ids:
                ctx_track = context_tracks.get(tid)
                if not ctx_track:
                    continue
                PLAY_QUEUE.append(tid)
                PLAY_QUEUE_META_CACHE[tid] = {
                    "source": "local",
                    "id": tid,
                    "title": ctx_track.get("title") or "",
                    "artist": ctx_track.get("artist") or "",
                    "album": ctx_track.get("album") or "",
                    "cover": artwork_url or "",
                    "artwork_url": artwork_url or "",
                    "duration": int(ctx_track.get("duration") or 0),
                    "quality": "LOCAL",
                    "is_cue_track": int(ctx_track.get("is_cue_track") or 0),
                    "cue_start_seconds": ctx_track.get("cue_start_seconds"),
                    "cue_end_seconds": ctx_track.get("cue_end_seconds"),
                    "_srova_context_direct_start": True,
                    "_srova_display_start_index": int(visible_start_index),
                }
            ORIGINAL_QUEUE.extend(PLAY_QUEUE)
            QUEUE_INDEX = max(0, min(visible_start_index, len(PLAY_QUEUE) - 1)) if PLAY_QUEUE else 0
            if cue_album_visible_from_current:
                logger.info(
                    "Local CUE album visible queue uses full album context: selected_index=%s visible_length=%s full_context_length=%s",
                    start_index,
                    len(PLAY_QUEUE),
                    len(track_ids),
                )
            if SHUFFLE_ON and PLAY_QUEUE:
                _queue_shuffle_future_after_current_locked(_queue_current_identity_locked())
            PLAY_QUEUE_PENDING_AFTER_CONTEXT = False
        save_queue()
    try:
        _local_resume_position = max(0.0, float((payload or {}).get("_resume_position") or 0))
    except Exception:
        _local_resume_position = 0.0
    if _local_resume_position > 0:
        playback_meta["_resume_position"] = _local_resume_position
        logger.info(
            "Local clean reload resume requested: %.3fs title=%s",
            _local_resume_position,
            playback_meta.get("title") or track.get("title") or "",
        )

    GLib.idle_add(lambda: play_local_test_file(real_path, file_uri, playback_meta=playback_meta))
    return {
        "ok": True,
        "source": "local",
        "id": track.get("id"),
        "path": real_path,
        "uri": file_uri,
        "title": track.get("title"),
        "artist": track.get("artist"),
        "album": track.get("album"),
        "artwork_url": artwork_url,
        "context_type": playback_meta.get("context_type"),
        "context_id": playback_meta.get("context_id"),
        "context_title": playback_meta.get("context_title"),
        "context_index": start_index,
        "context_length": len(track_ids),
        "message": "local library playback scheduled",
    }


def _play_local_context_index(index):
    track_ids = LOCAL_PLAYBACK_CONTEXT.get("track_ids")
    if not isinstance(track_ids, list) or not track_ids:
        logger.info("Local playback context has no upcoming tracks")
        return False
    try:
        idx = int(index)
    except Exception:
        idx = 0
    if not (0 <= idx < len(track_ids)):
        logger.info("Local playback context finished")
        return False
    track_id = str(track_ids[idx] or "").strip()
    if not track_id:
        logger.info("Local playback context has empty track id at index %s", idx)
        return False
    payload = {
        "id": track_id,
        "track_ids": track_ids,
        "start_index": idx,
        "context_type": LOCAL_PLAYBACK_CONTEXT.get("context_type") or "local_album",
        "context_id": LOCAL_PLAYBACK_CONTEXT.get("context_id") or "",
        "context_title": LOCAL_PLAYBACK_CONTEXT.get("context_title") or "Local Library",
    }
    result = _local_library_play_payload(payload)
    if not result.get("ok"):
        logger.warning("Local context playback failed: %s", result.get("error"))
    return False


def play_next_local_track():
    track_ids = LOCAL_PLAYBACK_CONTEXT.get("track_ids")
    if not isinstance(track_ids, list) or not track_ids:
        logger.info("Local playback has no continuation context")
        return
    try:
        current_index = int(LOCAL_PLAYBACK_CONTEXT.get("current_index", 0) or 0)
    except Exception:
        current_index = 0
    next_index = current_index + 1
    if REPEAT_MODE == "all" and next_index >= len(track_ids):
        next_index = 0
    if next_index < len(track_ids):
        GLib.idle_add(lambda: _play_local_context_index(next_index))
    else:
        logger.info("End of local playback context")


def play_previous_local_track():
    track_ids = LOCAL_PLAYBACK_CONTEXT.get("track_ids")
    if not isinstance(track_ids, list) or not track_ids:
        return False
    try:
        current_index = int(LOCAL_PLAYBACK_CONTEXT.get("current_index", 0) or 0)
    except Exception:
        current_index = 0
    prev_index = max(0, current_index - 1)
    GLib.idle_add(lambda: _play_local_context_index(prev_index))
    return True


def _local_test_file_uri(real_path):
    return Path(real_path).as_uri()


def _local_test_codec(real_path):
    ext = os.path.splitext(real_path)[1].lower()
    return _LOCAL_TEST_CODEC_BY_EXT.get(ext, ext.lstrip(".").upper() or "Local")


def _local_test_first_tag(tags, *names):
    if not isinstance(tags, dict):
        return None
    for name in names:
        value = tags.get(name)
        if value is None:
            value = tags.get(str(name).upper())
        if value is None:
            value = tags.get(str(name).lower())
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def _probe_local_test_metadata_mutagen(real_path):
    try:
        from mutagen import File as MutagenFile
    except Exception:
        return None

    try:
        audio = MutagenFile(real_path)
    except Exception as e:
        logger.debug("Local test mutagen probe failed for %s: %s", real_path, e)
        return None
    if audio is None:
        return None

    info = getattr(audio, "info", None)
    tags = getattr(audio, "tags", None) or {}
    metadata = {}
    codec = _local_test_codec(real_path)
    ext = os.path.splitext(real_path)[1].lower()
    if ext == ".flac":
        codec = "FLAC"
    metadata["codec"] = codec

    for out_key, attr in (
        ("sample_rate", "sample_rate"),
        ("bit_depth", "bits_per_sample"),
        ("channels", "channels"),
    ):
        value = getattr(info, attr, None)
        if value:
            try:
                metadata[out_key] = int(value)
            except Exception:
                pass
    length = getattr(info, "length", None)
    if length:
        try:
            metadata["duration"] = int(round(float(length)))
        except Exception:
            pass
    for out_key, names in (
        ("title", ("title",)),
        ("artist", ("artist", "albumartist")),
        ("album", ("album",)),
    ):
        value = _local_test_first_tag(tags, *names)
        if value:
            metadata[out_key] = value
    return metadata


def _parse_local_test_flac_comments(data):
    tags = {}
    if len(data) < 8:
        return tags
    try:
        vendor_len = int.from_bytes(data[0:4], "little")
        pos = 4 + vendor_len
        if pos + 4 > len(data):
            return tags
        count = int.from_bytes(data[pos:pos + 4], "little")
        pos += 4
        for _ in range(min(count, 128)):
            if pos + 4 > len(data):
                break
            item_len = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
            if item_len < 0 or pos + item_len > len(data):
                break
            item = data[pos:pos + item_len].decode("utf-8", "replace")
            pos += item_len
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key and value and key not in tags:
                tags[key] = value
    except Exception:
        return {}
    return tags


def _probe_local_test_flac_metadata(real_path):
    metadata = {"codec": "FLAC"}
    try:
        with open(real_path, "rb") as f:
            if f.read(4) != b"fLaC":
                return metadata
            for _ in range(32):
                header = f.read(4)
                if len(header) != 4:
                    break
                is_last = bool(header[0] & 0x80)
                block_type = header[0] & 0x7f
                length = int.from_bytes(header[1:4], "big")
                if length > 1024 * 1024:
                    f.seek(length, os.SEEK_CUR)
                    if is_last:
                        break
                    continue
                data = f.read(length)
                if len(data) != length:
                    break
                if block_type == 0 and length >= 34:
                    packed = int.from_bytes(data[10:18], "big")
                    sample_rate = (packed >> 44) & 0xfffff
                    channels = ((packed >> 41) & 0x7) + 1
                    bit_depth = ((packed >> 36) & 0x1f) + 1
                    total_samples = packed & ((1 << 36) - 1)
                    if sample_rate:
                        metadata["sample_rate"] = int(sample_rate)
                    if bit_depth:
                        metadata["bit_depth"] = int(bit_depth)
                    if channels:
                        metadata["channels"] = int(channels)
                    if sample_rate and total_samples:
                        metadata["duration"] = int(round(total_samples / float(sample_rate)))
                elif block_type == 4:
                    tags = _parse_local_test_flac_comments(data)
                    for out_key, names in (
                        ("title", ("title",)),
                        ("artist", ("artist", "albumartist")),
                        ("album", ("album",)),
                    ):
                        value = _local_test_first_tag(tags, *names)
                        if value:
                            metadata[out_key] = value
                if is_last:
                    break
    except Exception as e:
        logger.debug("Local test FLAC probe failed for %s: %s", real_path, e)
    return metadata


def _probe_local_test_metadata(real_path):
    metadata = _probe_local_test_metadata_mutagen(real_path) or {}
    ext = os.path.splitext(real_path)[1].lower()
    if ext == ".flac":
        flac_metadata = _probe_local_test_flac_metadata(real_path)
        flac_metadata.update({k: v for k, v in metadata.items() if v not in (None, "")})
        metadata = flac_metadata
    return metadata


def _local_test_metadata(real_path):
    title = os.path.splitext(os.path.basename(real_path))[0].replace("_", " ").strip()
    album_dir = os.path.basename(os.path.dirname(real_path)).strip()
    artist_dir = os.path.basename(os.path.dirname(os.path.dirname(real_path))).strip()
    track_uuid = uuid.uuid5(uuid.NAMESPACE_URL, real_path).hex
    probed = _probe_local_test_metadata(real_path)
    return {
        "track_id": "local-test:" + track_uuid,
        "title": probed.get("title") or title or os.path.basename(real_path),
        "artist": probed.get("artist") or artist_dir or "Local",
        "album": probed.get("album") or album_dir or "Local File",
        "duration": int(probed.get("duration") or 0),
        "codec": probed.get("codec") or _local_test_codec(real_path),
        "sample_rate": probed.get("sample_rate"),
        "bit_depth": probed.get("bit_depth"),
        "channels": probed.get("channels"),
    }


def play_local_test_file(real_path, file_uri, _audio_ready=False, playback_meta=None):
    global PLAYBACK_START_TIME, CURRENT_STREAM_INFO, LOCAL_CUE_BOUNDARY_TOKEN
    global RADIO_MODE, CURRENT_RADIO, CURRENT_RADIO_METADATA, _RADIO_SCROBBLE_CURRENT_KEY
    global PAUSED_PLAYBACK_POSITION, PAUSED_PLAYBACK_TRACK_ID

    if not _audio_ready:
        try:
            audio_configured = _ensure_audio_output_for_playback("local test playback")
        except AudioOutputUnavailable:
            return False
        if audio_configured:
            GLib.timeout_add(
                1500,
                lambda: play_local_test_file(
                    real_path, file_uri, _audio_ready=True, playback_meta=playback_meta
                )
            )
            return False

    if _audio_ready:
        try:
            _require_audio_output_for_playback("local test playback")
        except AudioOutputUnavailable:
            return False

    player = APP_INSTANCE.player
    _set_player_live_radio_mode(player, False)

    try:
        cancel_scrobble()
    except Exception:
        pass

    if RADIO_MODE:
        _cancel_pending_radio_start()
        _METADATA_REGISTRY.detach()
        _set_radio_switching_guard()
        CURRENT_RADIO_METADATA = {}
        _RADIO_SCROBBLE_CURRENT_KEY = None
        _set_current_radio_artwork({})
        RADIO_MODE = False
        CURRENT_RADIO = None
        _set_player_live_radio_mode(player, False)

    try:
        player.stop()
    except Exception as e:
        logger.debug("Local test stop before load failed: %s", e)

    meta = dict(_local_test_metadata(real_path))
    if playback_meta:
        meta.update({k: v for k, v in playback_meta.items() if v is not None})
    CURRENT_STREAM_INFO["sample_rate"] = meta.get("sample_rate")
    CURRENT_STREAM_INFO["bit_depth"] = meta.get("bit_depth")
    CURRENT_STREAM_INFO["codec"] = meta.get("codec") or _local_test_codec(real_path)
    CURRENT_STREAM_INFO["channels"] = meta.get("channels")
    for key in ("observed_sample_rate", "observed_bit_depth",
                "output_sample_rate", "output_bit_depth", "output_channels"):
        CURRENT_STREAM_INFO.pop(key, None)

    _set_local_playback_context(meta)
    PAUSED_PLAYBACK_POSITION = 0.0
    PAUSED_PLAYBACK_TRACK_ID = None

    PLAYBACK_START_TIME = time.time()
    _cancel_idle_release()
    logger.info("Local test playback: %s", real_path)
    try:
        # Rust/native transport needs a file:// locator, but it currently opens
        # percent-encoded Path.as_uri() paths literally. Use an unescaped local
        # file URI for native playback while keeping file_uri for API/UI payloads.
        player.load("file://" + real_path)
        player.play()
        _arm_active_queue_auto_advance()
        try:
            cue_start = float(meta.get("cue_start_seconds") or 0)
        except Exception:
            cue_start = 0.0
        try:
            cue_end = float(meta.get("cue_end_seconds") or 0)
        except Exception:
            cue_end = 0.0
        LOCAL_CUE_BOUNDARY_TOKEN += 1
        cue_token = LOCAL_CUE_BOUNDARY_TOKEN
        if cue_start > 0 and hasattr(player, "seek"):
            GLib.timeout_add(80, lambda: _seek_local_cue_start(cue_token, cue_start))
        if cue_end > cue_start:
            GLib.timeout_add(500, lambda: _monitor_local_cue_boundary(cue_token, cue_end))

        try:
            _local_resume_position = max(0.0, float(meta.get("_resume_position") or 0))
        except Exception:
            _local_resume_position = 0.0
        if _local_resume_position > 0 and hasattr(player, "seek"):
            _set_playback_clock_position(_local_resume_position)
            _resume_delay_ms = 950 if cue_start > 0 else 700
            GLib.timeout_add(_resume_delay_ms, lambda pos=_local_resume_position: _seek_resume_position(pos))
            logger.info(
                "Local clean reload resume seek scheduled: %.3fs cue_start=%.3fs title=%s",
                _local_resume_position,
                cue_start,
                meta.get("title") or "",
            )
        try:
            start_current_scrobble(
                build_current_scrobble_track("local"),
                PLAYBACK_START_TIME
            )
        except Exception as se:
            logger.debug("schedule local scrobble failed: %s", se)
    except Exception as e:
        logger.warning("Local test playback failed: %s", e)
    return False


def _seek_local_cue_start(token, start_seconds):
    if _radio_context_active():
        logger.info("SEEK SKIPPED for radio live stream")
        return False
    if int(token) != int(LOCAL_CUE_BOUNDARY_TOKEN):
        return False
    try:
        player = APP_INSTANCE.player
        if not hasattr(player, "seek"):
            return False

        try:
            before = _player_position_seconds(player)
        except Exception:
            before = 0.0

        try:
            if hasattr(player, "pause"):
                player.pause()
        except Exception as pe:
            logger.debug("Local CUE pre-seek pause failed: %s", pe)

        def _do_cue_seek():
            if int(token) != int(LOCAL_CUE_BOUNDARY_TOKEN):
                return False
            try:
                try:
                    player.seek(float(start_seconds))
                except Exception:
                    player.seek(int(float(start_seconds)))
                try:
                    mid = _player_position_seconds(player)
                except Exception:
                    mid = 0.0
                logger.info(
                    "Local CUE seek issued: %.3fs before=%.3f mid=%.3f",
                    float(start_seconds),
                    before,
                    mid,
                )
            except Exception as se:
                logger.debug("Local CUE seek failed: %s", se)
                return False

            def _resume_after_cue_seek():
                if int(token) != int(LOCAL_CUE_BOUNDARY_TOKEN):
                    return False
                try:
                    if hasattr(player, "play"):
                        player.play()
                    try:
                        after = _player_position_seconds(player)
                    except Exception:
                        after = 0.0
                    logger.info(
                        "Local CUE post-seek resume: %.3fs after=%.3f playing=%s",
                        float(start_seconds),
                        after,
                        bool(player.is_playing()) if hasattr(player, "is_playing") else None,
                    )
                except Exception as re:
                    logger.debug("Local CUE post-seek resume failed: %s", re)
                return False

            GLib.timeout_add(700, _resume_after_cue_seek)
            return False

        GLib.timeout_add(150, _do_cue_seek)
    except Exception as e:
        logger.debug("Local CUE seek scheduling failed: %s", e)
    return False


def _monitor_local_cue_boundary(token, end_seconds):
    if int(token) != int(LOCAL_CUE_BOUNDARY_TOKEN):
        return False
    if not _is_local_playback_context():
        return False
    try:
        current_end = float(LOCAL_PLAYBACK_CONTEXT.get("cue_end_seconds") or 0)
    except Exception:
        current_end = 0.0
    if not current_end or abs(current_end - float(end_seconds)) > 0.5:
        return False
    try:
        player = APP_INSTANCE.player
        is_playing = bool(player.is_playing()) if hasattr(player, "is_playing") else False
        if not is_playing:
            return True
        position = float(player.get_position()) if hasattr(player, "get_position") else 0.0
    except Exception:
        return True
    if position >= float(end_seconds) - 0.25:
        logger.info("Local CUE boundary reached: %.3fs", float(end_seconds))
        if _local_cue_has_continuation():
            play_next_track()
        else:
            try:
                player.stop()
            except Exception:
                pass
            _reset_idle_playback_context()
        return False
    return True


def _local_cue_has_continuation():
    if REPEAT_MODE in ("one", "all"):
        return True
    if _is_local_album_playback_context() and not _local_playback_has_queue_position():
        track_ids = LOCAL_PLAYBACK_CONTEXT.get("track_ids")
        try:
            current_index = int(LOCAL_PLAYBACK_CONTEXT.get("current_index", 0) or 0)
        except Exception:
            current_index = 0
        return isinstance(track_ids, list) and current_index + 1 < len(track_ids)
    with _QUEUE_LOCK:
        return bool(PLAY_QUEUE and QUEUE_INDEX + 1 < len(PLAY_QUEUE))


def play_queue_index(
    index,
    _audio_ready=False,
    _resume_position=0.0,
    _tidal_resolution=None,
):
    # A worker completion re-enters on the GLib main loop. Reject it before
    # touching playback state when a newer user action has superseded it.
    if _tidal_resolution is not None:
        token, expected_index, expected_track_id = _tidal_resolution[:3]
        if not _tidal_stream_resolution_matches(
            token,
            expected_index,
            expected_track_id,
        ):
            logger.info(
                "Discarding superseded TIDAL resolution before playback: "
                "token=%s index=%s track_id=%s",
                token,
                expected_index,
                expected_track_id,
            )
            return False
    global PLAY_QUEUE, QUEUE_INDEX, CURRENT_STREAM_INFO, PLAY_QUEUE_PENDING_AFTER_CONTEXT
    global PLAYBACK_START_TIME
    global _RADIO_SCROBBLE_CURRENT_KEY
    global PAUSED_PLAYBACK_POSITION, PAUSED_PLAYBACK_TRACK_ID
    if index >= len(PLAY_QUEUE):
        logger.info("Queue finished")
        return False

    # If the user previously released the DAC, automatically reclaim the
    # selected output on the next intentional playback action. Give the Rust
    # audio engine a brief moment to open the device before loading audio.
    if not _audio_ready:
        try:
            audio_configured = _ensure_audio_output_for_playback("Tidal playback")
        except AudioOutputUnavailable:
            return False
        if audio_configured:
            GLib.timeout_add(1500, lambda: play_queue_index(index, _audio_ready=True, _resume_position=_resume_position))
            return False
    else:
        try:
            _require_audio_output_for_playback("Tidal playback")
        except AudioOutputUnavailable:
            return False

    _clear_local_playback_context()
    _RADIO_SCROBBLE_CURRENT_KEY = None
    cancel_scrobble()
    PLAY_QUEUE_PENDING_AFTER_CONTEXT = False

    _set_player_live_radio_mode(APP_INSTANCE.player, False)
    QUEUE_INDEX = index
    PLAYBACK_START_TIME = time.time()
    track_id    = PLAY_QUEUE[index]
    queue_meta  = PLAY_QUEUE_META_CACHE.get(str(track_id), {}) or {}
    if str(queue_meta.get("source") or "").lower() == "radio" or str(track_id).startswith("radio:station:"):
        station = _radio_queue_station_from_meta(track_id, queue_meta)
        if not station.get("url"):
            logger.warning("Radio queue playback failed: missing station URL for %s", track_id)
            return False
        with _QUEUE_LOCK:
            _queue_prune_after_first_radio_locked("radio-playback")
        save_queue()
        _request_radio_station_start(station, reason="radio queue playback")
        return False
    if str(queue_meta.get("source") or "").lower() == "local" or str(track_id).startswith("local:"):
        payload = {
            "id": str(track_id),
            "context_type": "local_queue",
            "context_id": "queue",
            "context_title": "Play Queue",
        }
        try:
            _local_resume_position = float(_resume_position or 0)
        except Exception:
            _local_resume_position = 0.0
        if _local_resume_position > 0:
            payload["_resume_position"] = _local_resume_position
        result = _local_library_play_payload(payload)
        if not result.get("ok"):
            logger.warning("Local queue playback failed: %s", result.get("error"))
        return False

    backend     = APP_INSTANCE.backend
    player      = APP_INSTANCE.player
    try:
        if _tidal_resolution is None:
            expected_index = int(index)
            expected_track_id = str(track_id)
            token = _begin_tidal_stream_resolution(
                expected_index,
                expected_track_id,
            )

            def _resolve_tidal_stream():
                resolved_track = None
                resolved_uri = None
                resolution_error = None

                try:
                    resolved_track = backend.session.track(track_id)
                    resolved_uri = backend.get_stream_url(resolved_track)
                except Exception as exc:
                    resolution_error = exc

                GLib.idle_add(
                    lambda: play_queue_index(
                        expected_index,
                        _audio_ready=True,
                        _resume_position=_resume_position,
                        _tidal_resolution=(
                            token,
                            expected_index,
                            expected_track_id,
                            resolved_track,
                            resolved_uri,
                            resolution_error,
                        ),
                    )
                )

            threading.Thread(
                target=_resolve_tidal_stream,
                name=f"srova-tidal-resolve-{token}",
                daemon=True,
            ).start()
            return False

        (
            token,
            expected_index,
            expected_track_id,
            track,
            uri,
            resolution_error,
        ) = _tidal_resolution

        # Recheck immediately before applying the resolved stream. Consuming
        # the token also prevents an accidental duplicate completion.
        if not _tidal_stream_resolution_matches(
            token,
            expected_index,
            expected_track_id,
            consume=True,
        ):
            logger.info(
                "Discarding superseded TIDAL resolution at playback handoff: "
                "token=%s index=%s track_id=%s",
                token,
                expected_index,
                expected_track_id,
            )
            return False

        if resolution_error is not None:
            raise resolution_error
        CURRENT_STREAM_INFO["sample_rate"] = None
        CURRENT_STREAM_INFO["bit_depth"]   = None
        CURRENT_STREAM_INFO["codec"]       = "FLAC"
        try:
            # Prefer the actual stream metadata set by get_stream_url()
            bd = int(getattr(backend, "_last_stream_bit_depth",  0) or 0) or None
            sr = int(getattr(backend, "_last_stream_sample_rate", 0) or 0) or None
            if bd or sr:
                CURRENT_STREAM_INFO["bit_depth"]   = bd
                CURRENT_STREAM_INFO["sample_rate"] = sr
            else:
                # Fallback: parse from audio_quality enum string
                quality = getattr(track, "audio_quality", None)
                if quality:
                    bd, sr = parse_quality_from_log(str(quality))
                    CURRENT_STREAM_INFO["bit_depth"]   = bd
                    CURRENT_STREAM_INFO["sample_rate"] = sr
        except Exception:
            pass
        # Update CURRENT_CONTEXT for multi-device session sync
        # NOTE: No network calls here -- only use data already on the track object
        # to avoid blocking the GLib main loop and breaking auto-advance.
        try:
            CURRENT_CONTEXT["track_id"] = str(track_id)
            CURRENT_CONTEXT["title"]    = str(getattr(track, "name", "") or "")
            CURRENT_CONTEXT["duration"] = int(getattr(track, "duration", 0) or 0)
            artist_obj = getattr(track, "artist", None)
            CURRENT_CONTEXT["artist"]   = str(getattr(artist_obj, "name", "") or "") if artist_obj else ""
            CURRENT_CONTEXT["artist_id"] = str(getattr(artist_obj, "id", "") or "") if artist_obj else ""
            # Cover and album info from album object -- no network call
            cover_url = ""
            album_obj = getattr(track, "album", None)
            CURRENT_CONTEXT["album"]    = str(getattr(album_obj, "name", "") or "") if album_obj else ""
            CURRENT_CONTEXT["album_id"] = str(getattr(album_obj, "id",   "") or "") if album_obj else ""
            for attr in ("cover", "image", "squareImage", "imageId"):
                cid = getattr(album_obj, attr, None) if album_obj else None
                if cid and str(cid).strip():
                    token     = str(cid).replace("-", "/")
                    cover_url = ("https://resources.tidal.com/images/"
                                 + token + "/320x320.jpg")
                    break
            if cover_url:
                CURRENT_CONTEXT["cover"] = cover_url
        except Exception as ce:
            logger.debug("CURRENT_CONTEXT update failed: %s", ce)

        PAUSED_PLAYBACK_POSITION = 0.0
        PAUSED_PLAYBACK_TRACK_ID = None
        PLAYBACK_START_TIME = time.time()
        _cancel_idle_release()   # cancel any pending DAC release
        logger.info("Queue playback: %s", uri)
        player.load(uri)
        player.play()
        try:
            _queue_resume_position = max(0.0, float(_resume_position or 0))
        except Exception:
            _queue_resume_position = 0.0
        if _queue_resume_position > 0:
            _set_playback_clock_position(_queue_resume_position)
            GLib.timeout_add(120, lambda pos=_queue_resume_position: _seek_resume_position(pos))
            logger.info(
                "Tidal clean reload resume seek scheduled: %.3fs track_id=%s",
                _queue_resume_position,
                track_id,
            )
        _arm_active_queue_auto_advance()
        # Schedule scrobble -- non-blocking, daemon thread, safe to call here
        try:
            start_current_scrobble(
                build_current_scrobble_track("tidal"),
                PLAYBACK_START_TIME
            )
        except Exception as se:
            logger.debug("schedule_scrobble failed: %s", se)
    except Exception as e:
        logger.warning("Queue playback failed: %s", e)


def play_next_track():
    global QUEUE_INDEX, REPEAT_MODE, PLAY_QUEUE_PENDING_AFTER_CONTEXT
    if RADIO_MODE:
        logger.info("Radio mode active, not advancing Tidal queue")
        return
    if _is_local_album_playback_context():
        if not _local_playback_has_queue_position():
            if REPEAT_MODE == "one":
                try:
                    current_index = int(LOCAL_PLAYBACK_CONTEXT.get("current_index", 0) or 0)
                except Exception:
                    current_index = 0
                GLib.idle_add(lambda: _play_local_context_index(current_index))
                return
            play_next_local_track()
            return
        if REPEAT_MODE == "one":
            try:
                current_index = int(QUEUE_INDEX)
            except Exception:
                current_index = 0
            GLib.idle_add(lambda: play_queue_index(current_index))
            return
    if REPEAT_MODE == "one":
        logger.info("Repeat one: replaying track %s", QUEUE_INDEX)
        GLib.idle_add(lambda: play_queue_index(QUEUE_INDEX))
        return
    next_index = QUEUE_INDEX + 1
    current_id = str(PLAY_QUEUE[QUEUE_INDEX]) if PLAY_QUEUE and 0 <= QUEUE_INDEX < len(PLAY_QUEUE) else ""
    logger.info(
        "play_next_track: current_index=%s queue_length=%s repeat=%s current_id=%s next_index=%s",
        QUEUE_INDEX,
        len(PLAY_QUEUE),
        REPEAT_MODE,
        current_id,
        next_index,
    )
    if REPEAT_MODE == "all" and next_index >= len(PLAY_QUEUE):
        logger.info("Repeat all: wrapping queue to start")
        next_index = 0
    if next_index < len(PLAY_QUEUE):
        logger.info("Playing next track")
        GLib.idle_add(lambda: play_queue_index(next_index))
    else:
        current_meta = PLAY_QUEUE_META_CACHE.get(current_id, {}) or {}
        if current_id.startswith("local:") or str(current_meta.get("source") or "").lower() == "local":
            GLib.idle_add(_finalize_end_of_queue_playback, "End of local queue")
            return
        if not _tidal_infinite_play_enabled():
            GLib.idle_add(_finalize_end_of_queue_playback, "End of queue -- Infinite Play disabled")
            return
        logger.info("End of queue -- triggering autofill")
        threading.Thread(target=_autofill_queue, daemon=True).start()


def _radio_station_key(station):
    if not station:
        return ""
    sid = str((station or {}).get("id", "") or "").strip()
    if sid:
        return "id:" + sid
    url = str((station or {}).get("url", "") or "").strip()
    return "url:" + url if url else ""


def _current_radio_key():
    return _radio_station_key(CURRENT_RADIO)


def _radio_context_active(playback_context=None):
    if RADIO_MODE or CURRENT_RADIO:
        return True
    context_type = str(CURRENT_CONTEXT.get("context_type") or "").lower()
    if context_type == "radio":
        return True
    playback_context = playback_context or {}
    source = str(playback_context.get("source") or "").lower()
    if source == "radio" or bool(playback_context.get("radio_mode")):
        return True
    context = playback_context.get("context") or {}
    return str(context.get("context_type") or "").lower() == "radio"


def _radio_eos_should_ignore(playback_context=None):
    if time.monotonic() < float(_RADIO_SWITCHING_UNTIL or 0.0):
        return True
    return _radio_context_active(playback_context)


def _set_radio_switching_guard(seconds=2.0):
    global _RADIO_SWITCHING_UNTIL
    _RADIO_SWITCHING_UNTIL = max(
        float(_RADIO_SWITCHING_UNTIL or 0.0),
        time.monotonic() + float(seconds or 0.0),
    )


def _radio_player_is_playing(player=None):
    try:
        player = player or (APP_INSTANCE.player if APP_INSTANCE is not None else None)
        return bool(player is not None and player.is_playing())
    except Exception:
        return False


def _set_player_live_radio_mode(player=None, enabled=False):
    try:
        player = player or (APP_INSTANCE.player if APP_INSTANCE is not None else None)
        if player is not None and hasattr(player, "set_live_radio_mode"):
            player.set_live_radio_mode(bool(enabled))
    except Exception as e:
        logger.debug("set_live_radio_mode(%s) failed: %s", bool(enabled), e)


def _request_radio_station_start(station, reason="radio playback"):
    global RADIO_MODE, CURRENT_RADIO, _RADIO_STARTING, _RADIO_START_TOKEN, _RADIO_LAST_START_AT

    try:
        _require_audio_output_for_playback(reason)
    except AudioOutputUnavailable as e:
        payload = e.to_payload()
        payload["station"] = station or {}
        return payload

    _invalidate_tidal_stream_resolution("radio-start")
    _disarm_queue_auto_advance("radio-start")
    station = dict(station or {})
    station_key = _radio_station_key(station)
    now = time.monotonic()
    with _RADIO_START_LOCK:
        same_station = bool(station_key and RADIO_MODE and station_key == _current_radio_key())
        if same_station and (_RADIO_STARTING or _radio_player_is_playing()):
            logger.info("Radio start ignored: station already %s (%s)",
                        "starting" if _RADIO_STARTING else "playing",
                        station.get("name") or station_key)
            return {"ok": True, "station": CURRENT_RADIO or station, "state": "starting" if _RADIO_STARTING else "playing", "duplicate": True}
        if same_station and now - float(_RADIO_LAST_START_AT or 0.0) < _RADIO_MIN_RESTART_INTERVAL:
            logger.info("Radio start throttled: station=%s age=%.2fs",
                        station.get("name") or station_key, now - float(_RADIO_LAST_START_AT or 0.0))
            return {"ok": True, "station": CURRENT_RADIO or station, "state": "throttled", "duplicate": True}

        radio_to_radio_switch = bool(RADIO_MODE and not same_station)
        start_station = dict(station)
        start_station["_radio_to_radio_switch"] = radio_to_radio_switch
        _RADIO_START_TOKEN += 1
        token = _RADIO_START_TOKEN
        _RADIO_STARTING = True
        _RADIO_LAST_START_AT = now
        RADIO_MODE = True
        CURRENT_RADIO = station

    GLib.idle_add(lambda: (play_radio_station(start_station, token=token, reason=reason), False)[1])
    return {"ok": True, "station": station, "state": "starting", "duplicate": False}


def _finish_radio_start(token):
    global _RADIO_STARTING
    with _RADIO_START_LOCK:
        if token == _RADIO_START_TOKEN:
            _RADIO_STARTING = False


def _cancel_pending_radio_start():
    global _RADIO_STARTING, _RADIO_START_TOKEN
    with _RADIO_START_LOCK:
        _RADIO_START_TOKEN += 1
        _RADIO_STARTING = False


def play_radio_station(station, token=None, reason="radio playback"):
    global RADIO_MODE, CURRENT_RADIO, PLAYBACK_START_TIME, CURRENT_RADIO_METADATA
    global _RADIO_SCROBBLE_CURRENT_KEY, _RADIO_STARTING, _RADIO_START_TOKEN
    global PAUSED_PLAYBACK_POSITION, PAUSED_PLAYBACK_TRACK_ID, PAUSED_PIPELINE_RELEASED

    player = APP_INSTANCE.player
    station = dict(station or {})
    radio_to_radio_switch = bool(station.pop("_radio_to_radio_switch", False))
    station_key = _radio_station_key(station)
    with _RADIO_START_LOCK:
        if token is None:
            _RADIO_START_TOKEN += 1
            token = _RADIO_START_TOKEN
            _RADIO_STARTING = True
        elif token != _RADIO_START_TOKEN:
            logger.info("Radio start discarded: stale token for %s", station.get("name") or station_key)
            return False
    try:
        _require_audio_output_for_playback(reason)
    except AudioOutputUnavailable:
        _finish_radio_start(token)
        return False

    _clear_local_playback_context()
    cancel_scrobble()
    _RADIO_SCROBBLE_CURRENT_KEY = None
    switching_radio = bool(radio_to_radio_switch or _radio_player_is_playing(player))
    _set_player_live_radio_mode(player, True)
    if switching_radio:
        logger.info("Radio switch stop/load begin: %s", station.get("name") or station_key)
        _set_radio_switching_guard()
        _METADATA_REGISTRY.detach()
        try:
            player.stop()
        except Exception as e:
            logger.debug("Radio switch stop before load failed: %s", e)
        CURRENT_RADIO_METADATA = {}
        _set_current_radio_artwork({})
        PAUSED_PLAYBACK_POSITION = 0.0
        PAUSED_PLAYBACK_TRACK_ID = None
        PAUSED_PIPELINE_RELEASED = False
        PLAYBACK_START_TIME = None

    RADIO_MODE    = True
    CURRENT_RADIO = dict(station)

    CURRENT_STREAM_INFO["sample_rate"] = None
    CURRENT_STREAM_INFO["bit_depth"]   = None
    CURRENT_STREAM_INFO["codec"]       = None
    for _key in (
        "output_sample_rate",
        "output_bit_depth",
        "radio_observed_sample_rate",
        "radio_observed_bit_depth",
        "radio_observed_output_sample_rate",
        "radio_observed_output_bit_depth",
        "radio_observed_rate_confidence",
    ):
        CURRENT_STREAM_INFO.pop(_key, None)

    CURRENT_CONTEXT["track_id"]      = None
    CURRENT_CONTEXT["title"]         = str(station.get("name", "") or "")
    CURRENT_CONTEXT["artist"]        = "Radio"
    CURRENT_CONTEXT["artist_id"]     = ""
    CURRENT_CONTEXT["cover"]         = str(station.get("icon", "") or "")
    CURRENT_CONTEXT["duration"]      = 0
    CURRENT_CONTEXT["album"]         = ""
    CURRENT_CONTEXT["album_id"]      = ""
    CURRENT_CONTEXT["context_title"] = str(station.get("name", "") or "")
    CURRENT_CONTEXT["context_type"]  = "radio"
    CURRENT_CONTEXT["context_id"]    = str(station.get("id", "") or "")

    PLAYBACK_START_TIME = time.time()
    _cancel_idle_release()

    logger.info("Radio playback start: %s -> %s reason=%s",
                station.get("name", "?"), station.get("url", "?"), reason)

    stream_url = str(station.get("url", "") or "")
    is_radio_paradise_metadata_stream = _is_radio_paradise_metadata_stream(stream_url)
    if is_radio_paradise_metadata_stream:
        logger.info(
            "Radio Paradise metadata diagnostic: station_played url=%s metadata_registry=%s",
            stream_url,
            "EasyRadioWebsiteResolver,IcecastJsonResolver,RadioParadiseIcyMetadataResolver,OggVorbisResolver",
        )

    _METADATA_REGISTRY.detach()
    CURRENT_RADIO_METADATA = {}
    _set_current_radio_artwork({})

    def _probe_radio_technical_info(_url):
        try:
            observed = probe_flac_technical_info(_url)
            if not observed:
                logger.debug("Radio technical probe found no FLAC STREAMINFO for %s", _url)
                return
            current = CURRENT_RADIO if RADIO_MODE else None
            current_url = str((current or {}).get("url", "") or "")
            if current_url != _url:
                logger.debug("Discarding stale radio technical probe result for %s", _url)
                return
            codec = str(observed.get("codec", "") or "").strip()
            sample_rate = int(observed.get("sample_rate", 0) or 0)
            bit_depth = int(observed.get("bit_depth", 0) or 0)
            if codec:
                CURRENT_STREAM_INFO["codec"] = codec
            if sample_rate:
                CURRENT_STREAM_INFO["sample_rate"] = sample_rate
            if bit_depth:
                CURRENT_STREAM_INFO["bit_depth"] = bit_depth
            for _key in ("radio_observed_rate_confidence",):
                if observed.get(_key):
                    CURRENT_STREAM_INFO[_key] = observed[_key]
            logger.info("Radio technical probe observed: %s", observed)
        except Exception as e:
            logger.debug("Radio technical probe failed for %s: %s", _url, e)

    threading.Thread(
        target=_probe_radio_technical_info,
        args=(stream_url,),
        daemon=True,
        name="radio-technical-probe",
    ).start()

    def _on_metadata_update(meta):
        global CURRENT_RADIO_METADATA
        CURRENT_RADIO_METADATA = meta
        logger.info("Radio metadata observed: station=%s raw=%r artist=%r title=%r",
                    station.get("name", ""), meta.get("raw", ""), meta.get("artist", ""), meta.get("title", ""))
        if is_radio_paradise_metadata_stream:
            logger.info(
                "Radio Paradise metadata diagnostic: final metadata state written artist=%r title=%r raw=%r",
                meta.get("artist", ""),
                meta.get("title", ""),
                meta.get("raw", ""),
            )
        _schedule_radio_artwork_lookup(meta)
        handle_radio_scrobble_metadata(meta)

    def _log_if_no_radio_metadata():
        try:
            same_station = RADIO_MODE and str((CURRENT_RADIO or {}).get("url", "") or "") == stream_url
            if same_station and not (CURRENT_RADIO_METADATA or {}).get("raw"):
                logger.info(
                    "Radio metadata not observed yet for station=%s. Station logo fallback is expected; this stream may need an ICY/Shoutcast metadata resolver or may not expose now-playing text on this URL.",
                    station.get("name", ""),
                )
        except Exception as e:
            logger.debug("Radio no-metadata diagnostic failed: %s", e)
        return False

    GLib.timeout_add(12000, _log_if_no_radio_metadata)

    if getattr(player, "exclusive_lock_mode", False):
        with _RADIO_START_LOCK:
            if token != _RADIO_START_TOKEN:
                logger.info("Radio immediate start skipped: stale token for %s", station.get("name") or station_key)
                return False
        try:
            _set_player_live_radio_mode(player, True)
            logger.info("Radio load live=True uri=%s", stream_url)
            player.load(stream_url)
            player.play()
            _METADATA_REGISTRY.attach(stream_url, _on_metadata_update, station)
            if switching_radio:
                logger.info("Radio switch stop/load done: %s", station.get("name") or station_key)
        finally:
            _finish_radio_start(token)
    else:
        def _radio_start_step1():
            with _RADIO_START_LOCK:
                if token != _RADIO_START_TOKEN:
                    logger.info("Radio output prep skipped: stale token for %s", station.get("name") or station_key)
                    return False
            try:
                _ensure_audio_output_for_playback(reason)
            except AudioOutputUnavailable:
                _finish_radio_start(token)
            return False
        def _radio_start_step2():
            with _RADIO_START_LOCK:
                if token != _RADIO_START_TOKEN:
                    logger.info("Radio stream load skipped: stale token for %s", station.get("name") or station_key)
                    return False
            try:
                _require_audio_output_for_playback(reason)
            except AudioOutputUnavailable:
                _finish_radio_start(token)
                return False
            try:
                _set_player_live_radio_mode(player, True)
                logger.info("Radio load live=True uri=%s", stream_url)
                player.load(stream_url)
                player.play()
                _METADATA_REGISTRY.attach(stream_url, _on_metadata_update, station)
                if switching_radio:
                    logger.info("Radio switch stop/load done: %s", station.get("name") or station_key)
            finally:
                _finish_radio_start(token)
            return False
        GLib.idle_add(_radio_start_step1)
        GLib.timeout_add(1500, _radio_start_step2)
    return False


def stop_radio():
    global RADIO_MODE, CURRENT_RADIO, CURRENT_RADIO_METADATA, _RADIO_SCROBBLE_CURRENT_KEY
    player = APP_INSTANCE.player
    _cancel_pending_radio_start()
    _set_radio_switching_guard()
    try:
        player.stop()
    except Exception as e:
        logger.debug("player.stop() during stop_radio failed: %s", e)
    _METADATA_REGISTRY.detach()
    CURRENT_RADIO_METADATA = {}
    _RADIO_SCROBBLE_CURRENT_KEY = None
    cancel_scrobble()
    _set_current_radio_artwork({})
    RADIO_MODE    = False
    CURRENT_RADIO = None
    _set_player_live_radio_mode(player, False)
    # Radio stop is an intentional playback stop, so let the existing idle
    # release path park the DAC/output shortly after the stream has stopped.
    _schedule_idle_release(5)


def _radio_standby_payload():
    global PAUSED_PLAYBACK_POSITION, PAUSED_PLAYBACK_TRACK_ID, PAUSED_PIPELINE_RELEASED

    player = APP_INSTANCE.player
    playback_context = _status_playback_context(player)
    if (
        not RADIO_MODE
        or not CURRENT_RADIO
        or playback_context.get("source") != "radio"
        or playback_context.get("playback_state") == "playing"
    ):
        return {"ok": True, "cleared": False, "reason": "not_paused_radio"}

    try:
        if player.is_playing():
            return {"ok": True, "cleared": False, "reason": "radio_playing"}
    except Exception:
        pass

    # Standby has now confirmed that Radio is not actively playing. Invalidate
    # any queued GLib start step before stopping and clearing the Radio context.
    _cancel_pending_radio_start()

    try:
        player.stop()
    except Exception as e:
        logger.debug("player.stop() during radio standby failed: %s", e)

    PAUSED_PLAYBACK_POSITION = 0.0
    PAUSED_PLAYBACK_TRACK_ID = None
    PAUSED_PIPELINE_RELEASED = False
    cancel_scrobble()
    _reset_idle_playback_context()
    _schedule_idle_release(5)
    return {"ok": True, "cleared": True, "result": "idle"}


def _tidal_track_cover_url(track):
    try:
        alb = getattr(track, "album", None)
        for attr in ("cover", "image", "squareImage", "imageId"):
            cid = getattr(alb, attr, None) if alb else None
            if cid and str(cid).strip():
                return ("https://resources.tidal.com/images/"
                        + str(cid).replace("-", "/") + "/320x320.jpg")
    except Exception:
        pass
    return ""


def _tidal_track_artist_name(track):
    try:
        artist = getattr(track, "artist", None)
        return _safe_str(artist.name) if artist else ""
    except Exception:
        return ""


def _lastfm_api_key_for_recommendations():
    if not _SCROBBLE_CREDS.get("lastfm_connected"):
        return ""
    api_key = (_SCROBBLE_CREDS.get("lastfm_api_key") or LASTFM_API_KEY or "").strip()
    if not api_key or api_key == "YOUR_LASTFM_API_KEY":
        return ""
    return api_key


def _lastfm_similar_artist_names(artist_name, limit=20):
    artist_name = str(artist_name or "").strip()
    api_key = _lastfm_api_key_for_recommendations()
    if not artist_name or not api_key:
        return []
    try:
        url = (LASTFM_API_URL +
               "?method=artist.getSimilar"
               "&artist=" + urllib.parse.quote(artist_name) +
               "&api_key=" + urllib.parse.quote(api_key) +
               "&autocorrect=1"
               "&format=json"
               "&limit=" + str(int(limit or 20)))
        data = _meta_http_get(url)
        similar = (data.get("similarartists", {}).get("artist") or [])
        return [a["name"] for a in similar if a.get("name")][:limit]
    except Exception as e:
        logger.warning("Infinite Play Last.fm getSimilar failed for %s: %s", artist_name, e)
        return []


def _seed_artist_name_for_track(seed_id):
    seed_id = str(seed_id or "").strip()
    if not seed_id:
        return ""
    try:
        meta = PLAY_QUEUE_META_CACHE.get(seed_id, {}) or {}
        if meta.get("artist"):
            return _safe_str(meta.get("artist"))
    except Exception:
        pass
    try:
        seed_track = APP_INSTANCE.backend.session.track(seed_id)
        return _tidal_track_artist_name(seed_track)
    except Exception as e:
        logger.info("Infinite Play: could not resolve seed track artist for %s: %s", seed_id, e)
        return ""


def _normalise_infinite_play_title(title):
    return " ".join(str(title or "").strip().lower().split())


def _infinite_play_artist_pool(seed_artist, mode):
    seed_artist = str(seed_artist or "").strip()
    mode = _normalise_tidal_infinite_play_mode(mode)
    if not seed_artist:
        return []
    if mode == "same_artist":
        return [seed_artist]

    first_degree = _lastfm_similar_artist_names(seed_artist, limit=20)
    if mode == "similar_artist":
        return first_degree or [seed_artist]

    all_names = [seed_artist] + first_degree
    seen = set(n.lower() for n in all_names if n)
    for artist_name in first_degree[:6]:
        for related in _lastfm_similar_artist_names(artist_name, limit=8):
            key = related.lower()
            if key and key not in seen:
                all_names.append(related)
                seen.add(key)
    tail = all_names[1:]
    random.shuffle(tail)
    return [seed_artist] + tail


def _best_tidal_artist_for_name(backend, artist_name):
    matches = backend.search_artist(artist_name)
    if not matches:
        return None
    wanted = str(artist_name or "").strip().lower()
    for match in matches:
        if _safe_str(getattr(match, "name", "")).strip().lower() == wanted:
            return match
    return matches[0]


def _recommended_tracks_for_seed(seed_id, limit=12, mode=None):
    try:
        backend = APP_INSTANCE.backend
        if not seed_id:
            logger.warning("Infinite Play: no seed track available")
            return []
        if not backend or not getattr(backend, "session", None):
            logger.info("Infinite Play: TIDAL is not logged in or session is unavailable")
            return []

        mode = _normalise_tidal_infinite_play_mode(mode or _tidal_infinite_play_mode())
        seed_artist = _seed_artist_name_for_track(seed_id)
        if not seed_artist:
            logger.warning("Infinite Play: no seed artist for track %s", seed_id)
            return []

        def _track_id(track):
            return str(getattr(track, "id", "") or "").strip()

        def _fetch_artist_tracks(artist_names, fetch_mode, target_limit):
            tracks = []
            seen_track_ids = set()
            per_artist = target_limit if fetch_mode == "same_artist" else 3
            if fetch_mode == "surprise_me":
                per_artist = 2

            fetch_cap = max(target_limit * 2, target_limit)
            if fetch_mode == "same_artist":
                # Same Artist is the safety net. Fetch deeper so obscure/new artists
                # can still keep Infinite Play alive without Last.fm depth.
                fetch_cap = max(target_limit * 2, 25)

            for artist_name in artist_names:
                if len(tracks) >= fetch_cap:
                    break
                try:
                    tidal_artist = _best_tidal_artist_for_name(backend, artist_name)
                    if not tidal_artist:
                        continue

                    artist_fetch_limit = max(
                        per_artist,
                        target_limit if fetch_mode == "same_artist" else per_artist
                    )
                    if fetch_mode == "same_artist":
                        artist_fetch_limit = fetch_cap

                    top_tracks = backend.get_artist_top_tracks(tidal_artist, limit=artist_fetch_limit)
                    artist_added = 0
                    for track in top_tracks:
                        tid = _track_id(track)
                        if not tid or tid in seen_track_ids:
                            continue
                        seen_track_ids.add(tid)
                        tracks.append(track)
                        artist_added += 1

                        if fetch_mode != "same_artist" and artist_added >= per_artist:
                            break
                        if len(tracks) >= fetch_cap:
                            break
                except Exception as e:
                    logger.warning("Infinite Play TIDAL track fetch failed for %s: %s", artist_name, e)

            return tracks

        artist_names = []
        fallback_added = 0
        minimum_needed = min(10, max(1, int(limit or 10)))

        if mode == "same_artist":
            artist_names = [seed_artist]
        else:
            if _lastfm_api_key_for_recommendations():
                artist_names = _infinite_play_artist_pool(seed_artist, mode)
            else:
                logger.info("Infinite Play: Last.fm is not configured; using same-artist fallback")

        if not artist_names:
            logger.info(
                "Infinite Play: no Last.fm artist pool for %s in mode=%s; using same-artist fallback",
                seed_artist,
                mode,
            )

        tracks = _fetch_artist_tracks(artist_names, mode, limit) if artist_names else []

        # Safety net: Similar Artists and Surprise Me must not stall when Last.fm
        # has too little data. Fall back to Same Artist and let append logic fill
        # with shuffled/recycled same-artist tracks if the catalogue is tiny.
        if mode != "same_artist" and len(tracks) < minimum_needed:
            before = len(tracks)
            fallback_tracks = _fetch_artist_tracks([seed_artist], "same_artist", max(limit, 25))
            seen = set(_track_id(t) for t in tracks if _track_id(t))
            for track in fallback_tracks:
                tid = _track_id(track)
                if not tid or tid in seen:
                    continue
                seen.add(tid)
                tracks.append(track)

            fallback_added = len(tracks) - before
            logger.info(
                "Infinite Play: fallback same_artist mode=%s seed_artist=%s primary_candidates=%d fallback_added=%d",
                mode,
                seed_artist,
                before,
                fallback_added,
            )

        if mode == "surprise_me":
            random.shuffle(tracks)

        logger.info(
            "Infinite Play: mode=%s seed_artist=%s candidates=%d fallback_same_artist=%d",
            mode,
            seed_artist,
            len(tracks),
            fallback_added,
        )
        return tracks
    except Exception as e:
        logger.warning("Infinite Play recommendation lookup failed: %s", e)
        return []


def _append_infinite_play_recommendations(seed_id=None, limit=10, autoplay=False, mode=None):
    global PLAY_QUEUE, ORIGINAL_QUEUE, PLAY_QUEUE_META_CACHE
    try:
        if not seed_id:
            with _QUEUE_LOCK:
                seed_id = PLAY_QUEUE[-1] if PLAY_QUEUE else None
        if not seed_id:
            logger.warning("Infinite Play: no recommendation seed available")
            return {"ok": False, "error": "no seed track available", "added": 0}
        seed_id = str(seed_id)
        if seed_id.startswith("local:"):
            logger.info("Infinite Play: local seed ignored")
            return {"ok": False, "error": "seed is not a TIDAL track", "added": 0}

        mode = _normalise_tidal_infinite_play_mode(mode or _tidal_infinite_play_mode())
        new_tracks = _recommended_tracks_for_seed(seed_id, limit=max(limit * 2, 12), mode=mode)
        if not new_tracks:
            return {"ok": False, "error": "no recommended tracks found", "added": 0}

        with _QUEUE_LOCK:
            existing = set(str(tid) for tid in PLAY_QUEUE)
            denied_titles = set()
            try:
                if 0 <= QUEUE_INDEX < len(PLAY_QUEUE):
                    recent_start = max(0, QUEUE_INDEX - 9)
                    recent_ids = PLAY_QUEUE[recent_start:QUEUE_INDEX + 1]
                else:
                    recent_ids = PLAY_QUEUE[-10:]
                for recent_id in recent_ids:
                    recent_meta = PLAY_QUEUE_META_CACHE.get(str(recent_id), {}) or {}
                    title_key = _normalise_infinite_play_title(
                        recent_meta.get("title") or recent_meta.get("name")
                    )
                    if title_key:
                        denied_titles.add(title_key)
                seed_meta = PLAY_QUEUE_META_CACHE.get(seed_id, {}) or {}
                seed_title_key = _normalise_infinite_play_title(
                    seed_meta.get("title") or seed_meta.get("name")
                )
                if seed_title_key:
                    denied_titles.add(seed_title_key)
            except Exception as e:
                logger.debug("Infinite Play title deny set build failed: %s", e)

            id_filtered = [t for t in new_tracks if str(getattr(t, "id", "") or "") not in existing]
            if not id_filtered:
                # If the artist catalogue is tiny and everything is already in
                # the queue, allow repeats rather than allowing Infinite Play to stop.
                id_filtered = list(new_tracks)

            filtered = []
            filtered_ids = set()
            skipped_titles = 0
            for t in id_filtered:
                tid_key = str(getattr(t, "id", "") or "").strip()
                title_key = _normalise_infinite_play_title(getattr(t, "name", ""))
                if title_key and title_key in denied_titles:
                    skipped_titles += 1
                    continue
                filtered.append(t)
                if tid_key:
                    filtered_ids.add(tid_key)
                if title_key:
                    denied_titles.add(title_key)
                if len(filtered) >= limit:
                    break

            if skipped_titles:
                logger.info("Infinite Play: skipped %d repeated-title recommendations", skipped_titles)

            if len(filtered) < limit:
                relaxed_added = 0
                for t in id_filtered:
                    tid_key = str(getattr(t, "id", "") or "").strip()
                    if tid_key and tid_key in filtered_ids:
                        continue
                    filtered.append(t)
                    if tid_key:
                        filtered_ids.add(tid_key)
                    relaxed_added += 1
                    if len(filtered) >= limit:
                        break
                if relaxed_added:
                    logger.info(
                        "Infinite Play: relaxed duplicate/title guard added %d tracks to keep queue alive",
                        relaxed_added,
                    )

            if filtered and len(filtered) < limit:
                # Final safety net for very small same-artist catalogues: recycle
                # shuffled candidates so Infinite Play always appends the requested
                # count instead of stopping at queue end.
                recycle_source = list(filtered)
                recycled = 0
                while recycle_source and len(filtered) < limit:
                    filtered.append(random.choice(recycle_source))
                    recycled += 1
                if recycled:
                    logger.info(
                        "Infinite Play: recycled %d same-artist candidates to keep queue alive",
                        recycled,
                    )

            insert_start = len(PLAY_QUEUE)
            added = 0
            for t in filtered[:limit]:
                tid = str(getattr(t, "id", "") or "").strip()
                if not tid:
                    continue
                meta = {
                    "id":       tid,
                    "title":    _safe_str(getattr(t, "name", "")),
                    "artist":   _tidal_track_artist_name(t),
                    "cover":    _tidal_track_cover_url(t),
                    "duration": int(getattr(t, "duration", 0) or 0),
                    "quality":  _quality_badge(t)
                }
                PLAY_QUEUE.append(tid)
                ORIGINAL_QUEUE.append(tid)
                PLAY_QUEUE_META_CACHE[tid] = meta
                added += 1
            next_idx = insert_start

        if added <= 0:
            logger.warning("Infinite Play: recommendations had no usable track ids")
            return {"ok": False, "error": "no usable recommended tracks", "added": 0}

        save_queue()
        logger.info("Infinite Play: appended %d recommended tracks with mode=%s", added, mode)
        if autoplay:
            GLib.idle_add(lambda: play_queue_index(next_idx))
        return {"ok": True, "added": added, "mode": mode, "queue_length": len(PLAY_QUEUE)}
    except Exception as e:
        logger.warning("Infinite Play append failed: %s", e)
        return {"ok": False, "error": str(e), "added": 0}


def _autofill_queue():
    """Fetch similar tracks and append them when Infinite Play reaches queue end."""
    try:
        if not _tidal_infinite_play_enabled():
            logger.info("Autofill skipped: Infinite Play disabled")
            return
        _append_infinite_play_recommendations(limit=10, autoplay=True, mode=_tidal_infinite_play_mode())
    except Exception as e:
        logger.warning("Autofill failed: %s", e)


def install_eos_hook():
    player   = APP_INSTANCE.player
    original = player._on_eos_callback
    def eos_callback(*args, **kwargs):
        if _radio_eos_should_ignore():
            logger.info("Radio EOS ignored: live stream")
            return
        if original:
            original(*args, **kwargs)
        logger.info("SROVA EOS callback advancing queue")
        play_next_track()
    player._on_eos_callback = eos_callback


def _cancel_idle_release():
    """Cancel any pending DAC idle-release timer."""
    global IDLE_RELEASE_TIMER
    if IDLE_RELEASE_TIMER is not None:
        IDLE_RELEASE_TIMER.cancel()
        IDLE_RELEASE_TIMER = None


def _schedule_idle_release(delay_s=5):
    """Release the DAC after delay_s seconds of inactivity (like squeezelite -C 5)."""
    global IDLE_RELEASE_TIMER, PAUSED_PIPELINE_RELEASED
    PAUSED_PIPELINE_RELEASED = False
    _cancel_idle_release()
    def _do_release():
        global IDLE_RELEASE_TIMER, PAUSED_PIPELINE_RELEASED
        IDLE_RELEASE_TIMER = None
        try:
            if not APP_INSTANCE.player.is_playing():
                player = APP_INSTANCE.player
                # Step 1: stop the pipeline
                player.stop()
                # Step 2: clear exclusive mode flags so the Rust engine
                #         releases the hw:0,0 handle on next set_output call
                player.exclusive_lock_mode = False
                player.bit_perfect_mode    = False
                player.active_rate_switch  = False
                # Step 3: switch to ALSA auto (not exclusive) -- this releases hw:0,0
                #         and parks on a non-exclusive handle the OS can share
                def _release_output():
                    global PAUSED_PIPELINE_RELEASED
                    release_driver = "ALSA" if ALSA_DRIVER == "alsa_mmap" else ALSA_DRIVER
                    player.set_output(release_driver, "default")
                    PAUSED_PIPELINE_RELEASED = True
                    logger.info("DAC released after idle timeout")
                    return False
                GLib.idle_add(_release_output)
        except Exception as e:
            logger.debug("DAC idle release failed: %s", e)
    IDLE_RELEASE_TIMER = threading.Timer(delay_s, _do_release)
    IDLE_RELEASE_TIMER.daemon = True
    IDLE_RELEASE_TIMER.start()


def _player_position_seconds(player=None):
    """Return the current player position as seconds.

    The Rust adapter may expose either a scalar position or a ``(position,
    duration)`` tuple. Normalising here keeps /status, pause capture, and
    resume recovery aligned.
    """
    player = player or (APP_INSTANCE.player if APP_INSTANCE is not None else None)
    if player is None or not hasattr(player, "get_position"):
        return 0.0
    try:
        raw = player.get_position()
        if isinstance(raw, (tuple, list)):
            raw = raw[0] if raw else 0
        return max(0.0, float(raw or 0))
    except Exception:
        return 0.0


def _playback_context_cue_details(playback_context=None):
    """Return Local-CUE details from a status/session playback context.

    Positions coming from the player/Rust are absolute positions in the backing
    album-length audio file. UI/session positions for CUE virtual tracks must be
    relative to the current virtual track.
    """
    playback_context = playback_context or {}
    context = playback_context.get("context") if isinstance(playback_context, dict) else {}
    context = context if isinstance(context, dict) else {}
    source = str((playback_context.get("source") if isinstance(playback_context, dict) else "") or context.get("source") or "").lower()
    try:
        is_cue_track = int(context.get("is_cue_track") or 0) == 1
    except Exception:
        is_cue_track = False
    try:
        cue_start_seconds = float(context.get("cue_start_seconds") or 0.0)
    except Exception:
        cue_start_seconds = 0.0
    try:
        duration = float(context.get("duration") or 0.0)
    except Exception:
        duration = 0.0
    cue_track_index = context.get("cue_track_number")
    if cue_track_index is None:
        cue_track_index = context.get("current_index")
    track_id = str((playback_context.get("current_track_id") if isinstance(playback_context, dict) else "") or context.get("track_id") or "")
    return bool(source == "local" and is_cue_track), cue_start_seconds, duration, cue_track_index, track_id


def _playback_display_position(position, playback_context=None, position_is_raw=True):
    """Normalize a player/clock position for UI and /session display.

    For Local CUE virtual tracks:
      * raw player/clock positions are album-image absolute and must subtract
        cue_start_seconds;
      * saved pause positions are stored as virtual-track-relative and must not
        subtract cue_start_seconds again.
    """
    try:
        pos = max(0.0, float(position or 0.0))
    except Exception:
        pos = 0.0
    is_cue_track, cue_start_seconds, duration, _cue_track_index, _track_id = _playback_context_cue_details(playback_context)
    if is_cue_track and position_is_raw and cue_start_seconds > 0:
        pos = max(0.0, pos - cue_start_seconds)
    if duration > 0:
        pos = min(pos, duration)
    return pos


def _playback_clock_position_for_display(display_position, playback_context=None):
    """Return the wall-clock baseline position expected by PLAYBACK_START_TIME."""
    try:
        pos = max(0.0, float(display_position or 0.0))
    except Exception:
        pos = 0.0
    is_cue_track, cue_start_seconds, _duration, _cue_track_index, _track_id = _playback_context_cue_details(playback_context)
    if is_cue_track and cue_start_seconds > 0:
        return cue_start_seconds + pos
    return pos


def _queue_auto_advance_key(source, current_id, queue_index, title):
    return "|".join([
        str(source or "").lower(),
        str(current_id or ""),
        str(queue_index),
        str(title or ""),
    ])


def _queue_item_source(current_id, meta):
    meta_source = str((meta or {}).get("source") or "").lower()
    if str(current_id or "").startswith(("local:", "local-test:")) or meta_source == "local":
        return "local"
    return "tidal"


def _active_queue_auto_advance_snapshot():
    with _QUEUE_LOCK:
        if not PLAY_QUEUE or not (0 <= QUEUE_INDEX < len(PLAY_QUEUE)):
            return None
        queue_index = QUEUE_INDEX
        current_id = str(PLAY_QUEUE[QUEUE_INDEX])
        current_meta = PLAY_QUEUE_META_CACHE.get(current_id, {}) or {}
        source = _queue_item_source(current_id, current_meta)
        title = str(current_meta.get("title") or "")
        if not title:
            context = LOCAL_PLAYBACK_CONTEXT if source == "local" else CURRENT_CONTEXT
            if str((context or {}).get("track_id") or "") == current_id:
                title = str((context or {}).get("title") or "")
        return {
            "source": source,
            "current_id": current_id,
            "queue_index": queue_index,
            "title": title,
            "key": _queue_auto_advance_key(source, current_id, queue_index, title),
            "has_next": queue_index < len(PLAY_QUEUE) - 1,
            "meta": current_meta,
        }


def _arm_queue_auto_advance(source, current_id, queue_index, title):
    global QUEUE_AUTO_ADVANCE_ARMED_KEY, QUEUE_AUTO_ADVANCE_DISARMED_BY_USER
    if str(source or "").lower() not in ("local", "tidal"):
        return
    QUEUE_AUTO_ADVANCE_ARMED_KEY = _queue_auto_advance_key(source, current_id, queue_index, title)
    QUEUE_AUTO_ADVANCE_DISARMED_BY_USER = False
    logger.debug("Queue auto-advance armed: %s", QUEUE_AUTO_ADVANCE_ARMED_KEY)


def _arm_active_queue_auto_advance():
    snap = _active_queue_auto_advance_snapshot()
    if not snap:
        return
    _arm_queue_auto_advance(snap["source"], snap["current_id"], snap["queue_index"], snap["title"])


def _disarm_queue_auto_advance(reason):
    global QUEUE_AUTO_ADVANCE_ARMED_KEY, QUEUE_AUTO_ADVANCE_DISARMED_BY_USER
    if QUEUE_AUTO_ADVANCE_ARMED_KEY:
        logger.debug("Queue auto-advance disarmed: reason=%s key=%s", reason, QUEUE_AUTO_ADVANCE_ARMED_KEY)
    QUEUE_AUTO_ADVANCE_ARMED_KEY = ""
    QUEUE_AUTO_ADVANCE_DISARMED_BY_USER = True


def _maybe_schedule_queue_overrun_advance(playback_context, position, duration):
    global QUEUE_OVERRUN_ADVANCE_GUARD, QUEUE_OVERRUN_DIAGNOSTIC_GUARD
    try:
        playback_context = playback_context or {}
        if _radio_eos_should_ignore(playback_context):
            return
        source = str(playback_context.get("source") or "").lower()
        if source not in ("local", "tidal"):
            return
        player = APP_INSTANCE.player if APP_INSTANCE is not None else None
        if player is None:
            return
        is_playing = bool(player.is_playing())
        if REPEAT_MODE == "one":
            return
        start_age = None
        if PLAYBACK_START_TIME:
            start_age = time.time() - float(PLAYBACK_START_TIME)
        duration = int(duration or 0)
        position = float(position or 0)
        raw_position = position
        if duration <= 0:
            return
        snap = _active_queue_auto_advance_snapshot()
        if not snap or not snap.get("has_next"):
            return
        queue_source = snap["source"]
        queue_index = snap["queue_index"]
        current_id = snap["current_id"]
        current_meta = snap["meta"]
        if source == "local":
            cue_start = 0.0
            cue_track = False
            context_for_cue = playback_context.get("context") or {}
            for cue_meta in (playback_context, context_for_cue, current_meta, LOCAL_PLAYBACK_CONTEXT, CURRENT_CONTEXT):
                if not cue_meta:
                    continue
                try:
                    is_cue = int(cue_meta.get("is_cue_track") or 0)
                except Exception:
                    is_cue = 0
                if not is_cue:
                    continue
                cue_track = True
                try:
                    cue_start = float(cue_meta.get("cue_start_seconds") or 0)
                except Exception:
                    cue_start = 0.0
                break
            if cue_track and cue_start > 0:
                position = max(0.0, raw_position - cue_start)
        title = str(
            snap.get("title") or
            (playback_context.get("context") or {}).get("title") or
            ""
        )
        guard_key = _queue_auto_advance_key(queue_source, current_id, queue_index, title)
        active_id = str(playback_context.get("current_track_id") or "")
        queue_status_matched = bool(active_id and active_id == current_id)
        if queue_source != source:
            return
        near_end = position >= max(0.0, float(duration) - 0.5)
        overrun = position > float(duration) + 2.0
        age_ready = start_age is not None and start_age >= max(8.0, float(duration) - 2.0)
        playing_overrun = is_playing and overrun
        armed = bool(QUEUE_AUTO_ADVANCE_ARMED_KEY and QUEUE_AUTO_ADVANCE_ARMED_KEY == guard_key)
        ended_stalled_near_duration = (
            not is_playing and
            armed and
            not QUEUE_AUTO_ADVANCE_DISARMED_BY_USER and
            queue_status_matched and
            age_ready and
            (near_end or position > float(duration) or age_ready)
        )

        trigger_reason = ""
        skip_reason = ""
        if not queue_status_matched:
            skip_reason = "queue_status_mismatch"
        elif start_age is not None and start_age < 8:
            skip_reason = "transition_suppression"
        elif playing_overrun:
            trigger_reason = "playing-overrun"
        elif ended_stalled_near_duration:
            trigger_reason = "ended-stalled-near-duration"
        elif is_playing:
            skip_reason = "playing_not_overrun"
        elif not armed:
            skip_reason = "not_armed"
        elif QUEUE_AUTO_ADVANCE_DISARMED_BY_USER:
            skip_reason = "disarmed_by_user"
        elif not age_ready:
            skip_reason = "age_not_ready"
        else:
            skip_reason = "not_near_end"

        if not trigger_reason:
            if near_end or overrun or age_ready:
                diag_key = "|".join([
                    guard_key,
                    skip_reason,
                    str(int(position)),
                    str(int(duration)),
                    str(bool(is_playing)),
                ])
                if QUEUE_OVERRUN_DIAGNOSTIC_GUARD != diag_key:
                    QUEUE_OVERRUN_DIAGNOSTIC_GUARD = diag_key
                    logger.info(
                        "SROVA queue overrun fallback not scheduled reason=%s source=%s index=%s title=%s current_id=%s queue_id=%s queue_title=%s position=%.1f duration=%.1f is_playing=%s repeat=%s start_age=%.1f queue_status_matched=%s armed=%s disarmed_by_user=%s",
                        skip_reason,
                        source,
                        queue_index,
                        title or (playback_context.get("context") or {}).get("title") or "",
                        active_id,
                        current_id,
                        str(current_meta.get("title") or ""),
                        position,
                        float(duration),
                        is_playing,
                        REPEAT_MODE,
                        float(start_age or 0),
                        queue_status_matched,
                        armed,
                        QUEUE_AUTO_ADVANCE_DISARMED_BY_USER,
                    )
            return
        if QUEUE_OVERRUN_ADVANCE_GUARD == guard_key:
            return
        QUEUE_OVERRUN_ADVANCE_GUARD = guard_key
        logger.info(
            "SROVA queue overrun fallback advancing reason=%s source=%s index=%s position=%.1f duration=%.1f title=%s",
            trigger_reason,
            source,
            queue_index,
            position,
            float(duration or 0),
            title or current_id,
        )
        GLib.idle_add(play_next_track)
    except Exception as e:
        logger.debug("Queue overrun fallback check failed: %s", e)


def _set_playback_clock_position(position):
    global PLAYBACK_START_TIME
    pos = max(0.0, float(position or 0))
    PLAYBACK_START_TIME = time.time() - pos


def _resume_position_for_track(track_id):
    if not track_id:
        return 0.0
    if PAUSED_PLAYBACK_TRACK_ID and str(PAUSED_PLAYBACK_TRACK_ID) == str(track_id):
        return max(0.0, float(PAUSED_PLAYBACK_POSITION or 0))
    return 0.0


def _current_context_track_id():
    context = LOCAL_PLAYBACK_CONTEXT if _is_local_playback_context() else CURRENT_CONTEXT
    return str((context or {}).get("track_id") or "")


def _resume_loaded_pipeline(player, resume_position, reason):
    """Resume the currently loaded pipeline and repair its cursor if needed."""
    global PAUSED_PIPELINE_RELEASED
    if _radio_context_active():
        logger.info("Radio loaded-pipeline resume skipped: live stream")
        return False
    try:
        player.play()
        PAUSED_PIPELINE_RELEASED = False
        if float(resume_position or 0) > 0:
            GLib.timeout_add(150, lambda: _seek_resume_position(resume_position))
        else:
            _set_playback_clock_position(0)
        logger.info("%s resumed loaded pipeline at %.3fs", reason, float(resume_position or 0))
        return True
    except Exception as e:
        logger.warning("%s loaded-pipeline resume failed: %s", reason, e)
        return False



def _resume_seek_reassert_play(position):
    """After a resume seek, reassert play once.

    Some ALSA mmap/Rust resume paths restore the cursor correctly but remain
    silent until play() is pressed again. This mirrors that second Play press
    without changing DAC release timing or Rust/audio internals.
    """
    if _radio_context_active():
        return False
    try:
        player = APP_INSTANCE.player if APP_INSTANCE is not None else None
        if player is None or not hasattr(player, "play"):
            return False
        # If the user has paused again, do not restart playback behind them.
        try:
            if hasattr(player, "is_playing") and not player.is_playing():
                return False
        except Exception:
            pass
        player.play()
        logger.info("Resume seek reasserted playback at %.3fs", float(position or 0))
    except Exception as e:
        logger.debug("Resume seek playback reassert failed: %s", e)
    return False

def _seek_resume_position(position, attempts=8):
    if _radio_context_active():
        logger.info("SEEK SKIPPED for radio live stream")
        return False
    pos = max(0.0, float(position or 0))
    if pos <= 0:
        _set_playback_clock_position(0)
        return False
    try:
        player = APP_INSTANCE.player
        if player is not None and hasattr(player, "seek"):
            try:
                if hasattr(player, "pause"):
                    player.pause()
                    logger.info("Resume seek pre-pause before restore %.3fs", pos)
            except Exception as pe:
                logger.debug("Resume seek pre-pause failed: %s", pe)

            def _do_resume_seek():
                try:
                    player.seek(pos)
                    _set_playback_clock_position(pos)
                    logger.info("Resume seek restored paused position %.3fs", pos)
                except Exception as se:
                    logger.debug("Resume seek attempt failed: %s", se)
                    if attempts > 0:
                        GLib.timeout_add(350, lambda: _seek_resume_position(pos, attempts - 1))
                    return False

                def _resume_after_seek():
                    try:
                        if hasattr(player, "play"):
                            player.play()
                        try:
                            playing = bool(player.is_playing()) if hasattr(player, "is_playing") else None
                        except Exception:
                            playing = None
                        logger.info(
                            "Resume seek delayed playback start at %.3fs playing=%s",
                            pos,
                            playing,
                        )
                    except Exception as re:
                        logger.debug("Resume seek delayed playback start failed: %s", re)
                    return False

                GLib.timeout_add(650, _resume_after_seek)
                GLib.timeout_add(1250, lambda p=pos: _resume_seek_reassert_play(p))
                return False

            GLib.timeout_add(150, _do_resume_seek)
            return False
    except Exception as e:
        logger.debug("Resume seek scheduling failed: %s", e)
    if attempts > 0:
        GLib.timeout_add(350, lambda: _seek_resume_position(pos, attempts - 1))
    return False


def _quality_badge(track):
    """Return a short display string for the track quality.

    Priority order:
    1. Explicit bit_depth / sample_rate attributes on the track object
       (set by tidalapi from the stream manifest -- most accurate)
    2. audio_quality enum string (fast but sometimes under-reports hi-res)
    """
    # 1. Check numeric stream metadata if available on the object
    try:
        bd = int(getattr(track, "bit_depth",   0) or 0)
        sr = int(getattr(track, "sample_rate", 0) or 0)
        if bd >= 24 or sr > 48000:
            return "HI-RES"
        if bd > 0 or sr > 0:
            return "CD"
    except Exception:
        pass

    # 2. Fall back to audio_quality enum string
    qs = str(getattr(track, "audio_quality", "") or "").strip().upper()
    if not qs:
        return None
    if "HI_RES_LOSSLESS" in qs or "HI_RES" in qs or "MASTER" in qs:
        return "HI-RES"
    if "LOSSLESS" in qs or "HIGH_LOSSLESS" in qs or "HIGH" in qs:
        return "CD"
    return None


def _build_track_list(tracks, show_artist=False):
    """Build and return track list data for the browser.
    Does NOT touch PLAY_QUEUE -- queue is populated exclusively via
    POST /tidal/queue/replace so browsing never disrupts playback."""
    data = []
    for position, t in enumerate(tracks, start=1):
        artist_name = ""
        if show_artist:
            try:
                artist_name = _safe_str(t.artist.name) if getattr(t, "artist", None) else ""
            except Exception:
                artist_name = ""
        cover_url = ""
        try:
            album_obj = getattr(t, "album", None)
            for attr in ("cover", "image", "squareImage", "imageId"):
                cid = getattr(album_obj, attr, None) if album_obj else None
                if cid and str(cid).strip():
                    cover_url = ("https://resources.tidal.com/images/"
                                 + str(cid).replace("-", "/") + "/320x320.jpg")
                    break
        except Exception:
            pass
        data.append({
            "id":           t.id,
            "title":        _safe_str(t.name),
            "artist":       artist_name,
            "duration":     t.duration,
            "track_number": position,
            "cover":        cover_url,
            "quality":      _quality_badge(t)
        })
    return data


def _rebuild_queue_from_cache(cached_data):
    """No-op kept for call-site compatibility. Queue is populated via POST only.
    Browsing a cached album/playlist no longer disrupts playback."""
    pass


def _tidal_pause_payload():
    global _RADIO_SCROBBLE_CURRENT_KEY, PAUSED_PLAYBACK_POSITION, PAUSED_PLAYBACK_TRACK_ID
    _invalidate_tidal_stream_resolution("user-pause")
    _disarm_queue_auto_advance("user-pause")
    player = APP_INSTANCE.player
    playback_context = _status_playback_context(player)
    current_track_id = playback_context.get("current_track_id")
    raw_paused_position = _player_position_seconds(player)
    paused_position = _playback_display_position(raw_paused_position, playback_context, position_is_raw=True)
    is_local_cue, cue_start_seconds, _cue_duration, cue_track_index, cue_track_id = _playback_context_cue_details(playback_context)
    if str(playback_context.get("source") or "").lower() == "local":
        if is_local_cue:
            logger.info(
                "Local CUE pause captured relative position: position=%.3fs raw_position=%.3fs cue_start_seconds=%.3f cue_track_index=%s track_id=%s",
                float(paused_position or 0),
                float(raw_paused_position or 0),
                cue_start_seconds,
                cue_track_index,
                cue_track_id or current_track_id,
            )
        else:
            logger.info(
                "Local pause captured position: position=%.3fs track_id=%s",
                float(paused_position or 0),
                current_track_id,
            )
    try:
        APP_INSTANCE.player.pause()
    except Exception as e:
        logger.warning("Pause failed: %s", e)
    PAUSED_PLAYBACK_POSITION = paused_position
    PAUSED_PLAYBACK_TRACK_ID = str(current_track_id or "")
    # Schedule DAC release for Tidal, Radio, and local playback. Radio keeps
    # RADIO_MODE active for resume; local keeps CURRENT_CONTEXT for status.
    _schedule_idle_release(5)
    cancel_scrobble()
    if RADIO_MODE:
        _RADIO_SCROBBLE_CURRENT_KEY = None
    payload = {"result": "paused"}
    if _is_local_playback_context():
        payload["source"] = "local"
    payload["position"] = PAUSED_PLAYBACK_POSITION
    return payload


def _tidal_resume_payload():
    global PAUSED_PIPELINE_RELEASED
    was_released = bool(PAUSED_PIPELINE_RELEASED)
    player = APP_INSTANCE.player
    playback_context = _status_playback_context(player)
    current_track_id = playback_context.get("current_track_id")
    resume_position = _resume_position_for_track(current_track_id)
    if not playback_context.get("current_track_valid"):
        with _QUEUE_LOCK:
            queue_index = QUEUE_INDEX if PLAY_QUEUE and 0 <= QUEUE_INDEX < len(PLAY_QUEUE) else None
        if queue_index is not None:
            try:
                _require_audio_output_for_playback("resume")
            except AudioOutputUnavailable as e:
                payload = e.to_payload()
                payload["result"] = "idle"
                return payload
            _cancel_idle_release()
            GLib.idle_add(lambda idx=queue_index: play_queue_index(idx))
            return {"result": "playing", "source": "queue", "index": queue_index, "position": 0}
        return {"result": "idle", "position": 0}
    try:
        _require_audio_output_for_playback("resume")
    except AudioOutputUnavailable as e:
        payload = e.to_payload()
        payload["result"] = "idle"
        return payload
    _cancel_idle_release()
    if _is_local_playback_context():
        try:
            context = playback_context.get("context") or {}
            is_local_cue, cue_start_seconds, _cue_duration, cue_track_index, cue_track_id = _playback_context_cue_details(playback_context)
            with _QUEUE_LOCK:
                _local_reload_index = (
                    QUEUE_INDEX
                    if PLAY_QUEUE and 0 <= QUEUE_INDEX < len(PLAY_QUEUE)
                    and str(PLAY_QUEUE[QUEUE_INDEX]) == str(current_track_id or "")
                    else None
                )
            if _local_reload_index is not None:
                if not was_released:
                    try:
                        _local_player = APP_INSTANCE.player if APP_INSTANCE is not None else player
                        if _local_player is not None and hasattr(_local_player, "play"):
                            _local_player.play()
                            PAUSED_PIPELINE_RELEASED = False
                            _set_playback_clock_position(
                                _playback_clock_position_for_display(resume_position, playback_context)
                            )
                            if is_local_cue:
                                logger.info(
                                    "Local CUE short resume uses loaded pipeline: index=%s position=%.3fs cue_start_seconds=%.3f cue_track_index=%s track_id=%s was_released=%s",
                                    _local_reload_index,
                                    float(resume_position or 0),
                                    cue_start_seconds,
                                    cue_track_index,
                                    cue_track_id or current_track_id,
                                    was_released,
                                )
                                logger.info(
                                    "Local CUE resume target: cue_start_seconds=%.3f cue_track_index=%s track_id=%s",
                                    cue_start_seconds,
                                    cue_track_index,
                                    cue_track_id or current_track_id,
                                )
                            else:
                                logger.info(
                                    "Local short resume uses loaded pipeline: index=%s position=%.3fs track_id=%s was_released=%s",
                                    _local_reload_index,
                                    float(resume_position or 0),
                                    current_track_id,
                                    was_released,
                                )
                            try:
                                start_current_scrobble(build_current_scrobble_track("local"))
                            except Exception as se:
                                logger.debug("schedule local short resume scrobble failed: %s", se)
                            _arm_active_queue_auto_advance()
                            return {"result": "playing", "source": "local", "position": resume_position}
                    except Exception as e:
                        logger.warning("Local short loaded-pipeline resume failed; falling back to restart: %s", e)

                PAUSED_PIPELINE_RELEASED = False
                if is_local_cue:
                    logger.info(
                        "Local CUE released-DAC resume restarts current CUE track from cue_start_seconds=%.3f: index=%s cue_track_index=%s track_id=%s saved_position=%.3fs",
                        cue_start_seconds,
                        _local_reload_index,
                        cue_track_index,
                        cue_track_id or current_track_id,
                        float(resume_position or 0),
                    )
                    logger.info(
                        "Local CUE resume target: cue_start_seconds=%.3f cue_track_index=%s track_id=%s",
                        cue_start_seconds,
                        cue_track_index,
                        cue_track_id or current_track_id,
                    )
                    reason = "local_cue_released_resume_restart_from_cue_start"
                else:
                    logger.info(
                        "Local released-DAC resume restarts current track from beginning: index=%s track_id=%s saved_position=%.3fs",
                        _local_reload_index,
                        current_track_id,
                        float(resume_position or 0),
                    )
                    reason = "local_released_resume_restart_from_zero"
                GLib.idle_add(
                    lambda idx=_local_reload_index:
                        play_queue_index(idx, _resume_position=0.0)
                )
                _arm_active_queue_auto_advance()
                return {
                    "result": "playing",
                    "source": "local",
                    "position": 0,
                    "restarted": True,
                    "reason": reason,
                }

            if not was_released:
                _resume_loaded_pipeline(player, resume_position, "Local")
            else:
                def _local_resume_step1():
                    try:
                        _ensure_audio_output_for_playback("local resume")
                    except AudioOutputUnavailable:
                        return False
                    return False
                def _local_resume_step2():
                    try:
                        _require_audio_output_for_playback("local resume")
                    except AudioOutputUnavailable:
                        return False
                    _resume_loaded_pipeline(player, 0.0 if is_local_cue else 0.0, "Local released fallback")
                    try:
                        start_current_scrobble(build_current_scrobble_track("local"))
                    except Exception as se:
                        logger.debug("schedule local resume scrobble failed: %s", se)
                    return False
                GLib.idle_add(_local_resume_step1)
                GLib.timeout_add(1500, _local_resume_step2)
            if not was_released:
                try:
                    start_current_scrobble(build_current_scrobble_track("local"))
                except Exception as se:
                    logger.debug("schedule local resume scrobble failed: %s", se)
            _arm_active_queue_auto_advance()
        except Exception as e:
            logger.warning("Local resume failed: %s", e)
        return {"result": "playing", "source": "local", "position": resume_position}
    if RADIO_MODE:
        try:
            player = APP_INSTANCE.player
            if not player.is_playing():
                _station = dict(CURRENT_RADIO) if CURRENT_RADIO else None
                if _station:
                    _set_player_live_radio_mode(player, True)
                    if not was_released:
                        logger.info("Radio loaded-pipeline resume skipped: live stream")
                        player.play()
                        return {"result": "playing", "source": "radio", "position": 0}
                    _request_radio_station_start(_station, reason="radio reconnect")
                else:
                    _set_player_live_radio_mode(player, True)
                    player.play()
            else:
                _set_player_live_radio_mode(player, True)
                player.play()
        except Exception as e:
            logger.warning("Radio resume failed: %s", e)
        return {"result": "playing"}
    try:
        with _QUEUE_LOCK:
            _tidal_reload_index = (
                QUEUE_INDEX
                if PLAY_QUEUE and 0 <= QUEUE_INDEX < len(PLAY_QUEUE)
                and str(PLAY_QUEUE[QUEUE_INDEX]) == str(current_track_id or "")
                else None
            )
        if _tidal_reload_index is not None:
            if not was_released:
                try:
                    _tidal_player = APP_INSTANCE.player if APP_INSTANCE is not None else player
                    if _tidal_player is not None and hasattr(_tidal_player, "play"):
                        _tidal_player.play()
                        PAUSED_PIPELINE_RELEASED = False
                        _set_playback_clock_position(resume_position)
                        logger.info(
                            "Tidal short resume uses loaded pipeline: index=%s position=%.3fs was_released=%s",
                            _tidal_reload_index,
                            float(resume_position or 0),
                            was_released,
                        )
                        try:
                            start_current_scrobble(build_current_scrobble_track("tidal"))
                        except Exception as se:
                            logger.debug("schedule TIDAL short resume scrobble failed: %s", se)
                        _arm_active_queue_auto_advance()
                        return {"result": "playing", "source": "tidal", "position": resume_position}
                except Exception as e:
                    logger.warning("Tidal short loaded-pipeline resume failed; falling back to clean reload: %s", e)
            if was_released:
                PAUSED_PIPELINE_RELEASED = False
                logger.info(
                    "Tidal released-DAC resume restarts from beginning: index=%s saved_position=%.3fs",
                    _tidal_reload_index,
                    float(resume_position or 0),
                )
                GLib.idle_add(
                    lambda idx=_tidal_reload_index:
                        play_queue_index(idx, _resume_position=0.0)
                )
                _arm_active_queue_auto_advance()
                return {
                    "result": "playing",
                    "source": "tidal",
                    "position": 0,
                    "restarted": True,
                    "reason": "tidal_released_resume_restart_from_zero",
                }
            logger.info(
                "Tidal resume uses clean queue reload: index=%s position=%.3fs was_released=%s",
                _tidal_reload_index,
                float(resume_position or 0),
                was_released,
            )
            GLib.idle_add(
                lambda idx=_tidal_reload_index, pos=resume_position:
                    play_queue_index(idx, _resume_position=pos)
            )
        else:
            logger.info(
                "Tidal resume clean reload unavailable; falling back to loaded pipeline position=%.3fs was_released=%s",
                float(resume_position or 0),
                was_released,
            )
            _resume_loaded_pipeline(player, resume_position, "Tidal")
        _arm_active_queue_auto_advance()
    except Exception as e:
        logger.warning("Resume failed: %s", e)
    return {"result": "playing", "position": resume_position}


def _tidal_next_payload():
    _invalidate_tidal_stream_resolution("user-next")
    try:
        _require_audio_output_for_playback("next track")
    except AudioOutputUnavailable as e:
        return e.to_payload()
    if _is_local_album_playback_context() and not _local_playback_has_queue_position():
        GLib.idle_add(play_next_local_track)
        return {"result": "next", "source": "local"}
    GLib.idle_add(play_next_track)
    return {"result": "next"}


def _tidal_prev_payload():
    global RADIO_MODE, CURRENT_RADIO, CURRENT_RADIO_METADATA
    _invalidate_tidal_stream_resolution("user-previous")
    try:
        _require_audio_output_for_playback("previous track")
    except AudioOutputUnavailable as e:
        return e.to_payload()
    if _is_local_album_playback_context() and not _local_playback_has_queue_position():
        if play_previous_local_track():
            return {"result": "prev", "source": "local"}
        return {"result": "unsupported", "source": "local"}
    if RADIO_MODE:
        _cancel_pending_radio_start()
        _METADATA_REGISTRY.detach()
        _set_radio_switching_guard()
        CURRENT_RADIO_METADATA = {}
        _set_current_radio_artwork({})
        RADIO_MODE = False
        CURRENT_RADIO = None
        _set_player_live_radio_mode(player, False)
    prev_index = max(0, QUEUE_INDEX - 1)
    GLib.idle_add(lambda: play_queue_index(prev_index))
    return {"result": "prev", "index": prev_index}


def _tidal_seek_payload(position):
    global PAUSED_PLAYBACK_POSITION, PAUSED_PLAYBACK_TRACK_ID
    try:
        target = float(position or 0)
    except Exception:
        target = 0.0
    target = max(0.0, target)
    player = APP_INSTANCE.player
    playback_context = _status_playback_context(player)
    source = str(playback_context.get("source") or "").lower()
    context = playback_context.get("context") or {}
    current_track_id = playback_context.get("current_track_id")
    title = str(context.get("title") or "")
    duration = float(context.get("duration") or 0)
    context_type = str(context.get("context_type") or CURRENT_CONTEXT.get("context_type") or "")
    logger.info(
        "SEEK REQUEST received: source=%s, radio_mode=%s, context_type=%s, duration=%.1f, pos=%.1f",
        source,
        bool(RADIO_MODE or playback_context.get("radio_mode")),
        context_type,
        duration,
        target,
    )
    if _radio_context_active(playback_context):
        logger.info("SEEK SKIPPED for radio live stream")
        return {
            "ok": False,
            "error": "seek_unsupported_for_radio",
            "position": 0,
            "duration": duration,
            "playing": bool(player.is_playing()),
            "source": source or "radio",
            "current_track_id": current_track_id,
            "queue_index": QUEUE_INDEX,
        }
    if duration <= 0:
        logger.info("Seek ignored: non-seekable stream duration=%.1f source=%s", duration, source)
        return {
            "ok": False,
            "error": "no_seekable_duration",
            "position": 0,
            "duration": duration,
            "playing": bool(player.is_playing()),
            "source": source,
            "current_track_id": current_track_id,
            "queue_index": QUEUE_INDEX,
        }
    if source not in ("local", "tidal") or not playback_context.get("current_track_valid"):
        return {
            "ok": False,
            "error": "no_seekable_track",
            "position": 0,
            "duration": duration,
            "playing": bool(player.is_playing()),
            "source": source,
            "current_track_id": current_track_id,
            "queue_index": QUEUE_INDEX,
        }
    if source == "local" and int(context.get("is_cue_track") or 0):
        try:
            cue_start_for_seek_block = float(context.get("cue_start_seconds") or 0)
        except Exception:
            cue_start_for_seek_block = 0.0
        try:
            raw_now = _player_position_seconds(player)
        except Exception:
            raw_now = 0.0
        rel_now = raw_now - cue_start_for_seek_block if cue_start_for_seek_block > 0 else raw_now
        if duration > 0:
            rel_now = max(0.0, min(float(rel_now or 0), duration))
        else:
            rel_now = max(0.0, float(rel_now or 0))
        logger.info(
            "Seek skipped: Local CUE virtual track manual seek disabled target=%.1f rel_now=%.1f raw_now=%.1f cue_start=%.3f title=%s current_id=%s",
            target,
            rel_now,
            raw_now,
            cue_start_for_seek_block,
            title,
            current_track_id,
        )
        return {
            "ok": False,
            "error": "seek_unsupported_for_local_cue",
            "position": rel_now,
            "duration": duration,
            "playing": bool(player.is_playing()),
            "source": source,
            "current_track_id": current_track_id,
            "queue_index": QUEUE_INDEX,
        }
    if duration > 0:
        target = max(0.0, min(target, duration))
    was_playing = bool(player.is_playing())
    raw_before = _player_position_seconds(player)
    start_age = time.time() - float(PLAYBACK_START_TIME) if PLAYBACK_START_TIME else 0.0
    logger.info(
        "SROVA seek request source=%s index=%s title=%s current_id=%s target=%.1f duration=%.1f was_playing=%s raw_before=%.1f start_age=%.1f armed_key=%s",
        source,
        QUEUE_INDEX,
        title,
        current_track_id,
        target,
        duration,
        was_playing,
        raw_before,
        start_age,
        QUEUE_AUTO_ADVANCE_ARMED_KEY,
    )
    if not hasattr(player, "seek"):
        return {
            "ok": False,
            "error": "seek_unsupported",
            "position": raw_before,
            "duration": duration,
            "playing": was_playing,
            "source": source,
            "current_track_id": current_track_id,
            "queue_index": QUEUE_INDEX,
        }
    resumed = False
    try:
        result = player.seek(target)
        if was_playing:
            try:
                player.play()
                resumed = True
            except Exception as pe:
                logger.warning("Seek resume play failed: %s", pe)
        raw_after = _player_position_seconds(player)
        playing_after = bool(player.is_playing())
        if playing_after:
            _set_playback_clock_position(target)
        else:
            PAUSED_PLAYBACK_POSITION = target
            PAUSED_PLAYBACK_TRACK_ID = str(current_track_id or "")
        if was_playing and playing_after and source in ("local", "tidal"):
            _arm_active_queue_auto_advance()
        elif not playing_after:
            _disarm_queue_auto_advance("seek-while-paused")
        logger.info(
            "SROVA seek complete source=%s index=%s title=%s target=%.1f duration=%.1f raw_after=%.1f playing_after=%s resumed=%s result=%s start_time=%.3f armed_key=%s",
            source,
            QUEUE_INDEX,
            title,
            target,
            duration,
            raw_after,
            playing_after,
            resumed,
            str(result),
            float(PLAYBACK_START_TIME or 0),
            QUEUE_AUTO_ADVANCE_ARMED_KEY,
        )
        return {
            "ok": True,
            "result": "ok",
            "position": target,
            "duration": duration,
            "playing": playing_after,
            "source": source,
            "current_track_id": current_track_id,
            "queue_index": QUEUE_INDEX,
            "resumed": resumed,
        }
    except Exception as e:
        logger.warning("Seek failed: %s", e)
        return {
            "ok": False,
            "error": str(e),
            "position": raw_before,
            "duration": duration,
            "playing": bool(player.is_playing()),
            "source": source,
            "current_track_id": current_track_id,
            "queue_index": QUEUE_INDEX,
        }


def _safe_artwork(backend, obj, size=320):
    try:
        return backend.get_artwork_url(obj, size) or ""
    except Exception:
        return ""


def _safe_str(value, fallback=""):
    """Safely convert a tidalapi attribute to a string.
    Guards against callable values (e.g. bound methods returned instead of
    plain strings by some tidalapi object types).
    """
    if value is None:
        return fallback
    if callable(value):
        try:
            value = value()
        except Exception:
            return fallback
    return str(value or fallback)


def _call_with_timeout(fn, timeout_seconds, fallback=None):
    box = {"done": False, "value": fallback, "error": None}

    def _runner():
        try:
            box["value"] = fn()
        except Exception as e:
            box["error"] = e
        finally:
            box["done"] = True

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join(timeout=max(0.1, float(timeout_seconds or 0)))
    if not box["done"]:
        return False, fallback, TimeoutError("operation timed out")
    if box["error"] is not None:
        return False, fallback, box["error"]
    return True, box["value"], None


def _tidal_login_snapshot():
    try:
        backend = APP_INSTANCE.backend if APP_INSTANCE else None
        session = getattr(backend, "session", None)
        return bool(getattr(session, "access_token", None) or getattr(backend, "user", None))
    except Exception:
        return False


def _tidal_status_payload():
    ok, logged_in, error = _call_with_timeout(
        lambda: bool(APP_INSTANCE.backend.check_login()),
        2.0,
        fallback=_tidal_login_snapshot(),
    )
    if not ok:
        logger.warning("TIDAL status unavailable: %s", error)
        return {
            "logged_in": bool(logged_in),
            "tidal_username": "",
            "tidal_online": False,
            "offline": True,
            "error": "TIDAL is unavailable. Local Music remains available.",
        }
    return {
        "logged_in": bool(logged_in),
        "tidal_username": _tidal_account_display_name() if logged_in else "",
        "tidal_online": True,
        "offline": False,
    }


def _radio_stream_available(station, timeout=4.0):
    stream_url = str((station or {}).get("url", "") or "").strip()
    parsed = urlparse(stream_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False, "Radio stream URL is invalid."
    return True, ""


def _probe_external_online(timeout=_ONLINE_STATE_TCP_TIMEOUT):
    last_error = ""
    for host, port in _ONLINE_STATE_TCP_TARGETS:
        target = f"{host}:{port}"
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return {
                    "online": True,
                    "target": target,
                    "confidence": "confirmed",
                    "error": "",
                }
        except Exception as e:
            last_error = str(e or "").strip()
            continue
    return {
        "online": False,
        "target": ",".join(f"{host}:{port}" for host, port in _ONLINE_STATE_TCP_TARGETS),
        "confidence": "all_failed",
        "error": last_error or "all internet checks failed",
    }


def _schedule_active_tidal_offline_stop():
    """Clear a stalled active TIDAL stream after confirmed network loss."""
    try:
        player = APP_INSTANCE.player if APP_INSTANCE is not None else None
        playback_context = _status_playback_context(player)
        if (
            str(playback_context.get("source") or "").lower() != "tidal"
            or playback_context.get("playback_state") != "playing"
            or not playback_context.get("current_track_valid")
        ):
            return False
        logger.info(
            "Confirmed network loss while TIDAL is playing; "
            "scheduling stopped playback state"
        )
        GLib.idle_add(
            _finalize_end_of_queue_playback,
            "TIDAL playback stopped: network unavailable",
        )
        return True
    except Exception as e:
        logger.debug(
            "TIDAL offline playback-state cleanup skipped: %s",
            e,
        )
        return False


def _online_state_payload(force=False):
    now = time.time()
    with _ONLINE_STATE_LOCK:
        cached = dict(_ONLINE_STATE)
    if not force and now - float(cached.get("checked_at", 0) or 0) < _ONLINE_STATE_TTL:
        return {
            "online": bool(cached.get("online")),
            "checked_at": cached.get("checked_at", 0),
            "method": cached.get("method", "tcp_connect"),
            "target": cached.get("target", ""),
            "confidence": cached.get("confidence", "unknown"),
            "error": cached.get("error", ""),
        }
    try:
        result = _probe_external_online()
        payload = {
            "online": bool(result.get("online")),
            "checked_at": time.time(),
            "method": "tcp_connect",
            "target": result.get("target", ""),
            "confidence": result.get("confidence", "unknown"),
            "error": result.get("error", ""),
        }
    except Exception as e:
        payload = {
            "online": True,
            "checked_at": time.time(),
            "method": "tcp_connect",
            "target": "",
            "confidence": "unknown",
            "error": str(e or "").strip(),
        }
    with _ONLINE_STATE_LOCK:
        transitioned_offline = (
            bool(_ONLINE_STATE.get("online"))
            and not bool(payload.get("online"))
        )
        _ONLINE_STATE.update(payload)
    if transitioned_offline:
        _schedule_active_tidal_offline_stop()
    return payload


def _mark_online_unavailable(error=""):
    logger.debug("online source unavailable without changing generic online state: %s", error)


def _offline_online_source_payload():
    return {
        "ok": False,
        "offline": True,
        "error": "You are offline. Local Music remains available.",
    }


def _is_local_track_payload(track):
    if not isinstance(track, dict):
        return False
    return (
        str(track.get("source") or "").lower() == "local" or
        str(track.get("id") or "").startswith("local:")
    )


def _all_tracks_are_local(tracks):
    tracks = tracks if isinstance(tracks, list) else []
    return bool(tracks) and all(_is_local_track_payload(t) for t in tracks)


def _is_radio_track_payload(track):
    if not isinstance(track, dict):
        return False
    source = str(track.get("source") or "").lower()
    track_id = str(track.get("id") or "").strip()
    return source == "radio" or track_id.startswith("radio:station:")


def _radio_queue_block_payload():
    return {
        "ok": False,
        "error": "Clear the Radio station from the Play Queue before adding to it.",
        "source": "radio",
        "radio_mode": True,
    }


def _radio_queue_payload_from_station(station):
    station = dict(station or {})
    station_id = str(station.get("id") or "").strip()
    return {
        "id": "radio:station:" + station_id if station_id else "radio:station",
        "source": "radio",
        "station_id": station_id,
        "title": str(station.get("name") or "Radio").strip(),
        "artist": "Radio",
        "album": "Radio",
        "cover": str(station.get("icon") or "").strip(),
        "duration": 0,
        "quality": "RADIO",
        "url": str(station.get("url") or "").strip(),
        "icon": str(station.get("icon") or "").strip(),
        "context_type": "radio",
        "context_id": station_id,
        "context_title": str(station.get("name") or "Radio").strip(),
    }


def _radio_queue_station_from_meta(track_id, meta):
    meta = dict(meta or {})
    station_id = str(
        meta.get("station_id")
        or meta.get("radio_station_id")
        or meta.get("context_id")
        or ""
    ).strip()
    tid = str(track_id or "").strip()
    prefix = "radio:station:"
    if not station_id and tid.startswith(prefix):
        station_id = tid[len(prefix):].strip()

    station = {
        "id": station_id,
        "name": str(meta.get("title") or meta.get("name") or "Radio").strip(),
        "url": str(meta.get("url") or meta.get("station_url") or "").strip(),
        "icon": str(meta.get("cover") or meta.get("image_url") or meta.get("icon") or "").strip(),
    }

    if (not station.get("url")) and station_id:
        try:
            with _RADIO_LOCK:
                stations = _load_radio_stations()
            for s in stations:
                if str((s or {}).get("id") or "") == station_id:
                    found = dict(s or {})
                    if not station.get("name") or station.get("name") == "Radio":
                        station["name"] = str(found.get("name") or station["name"] or "Radio")
                    station["url"] = str(found.get("url") or station.get("url") or "")
                    station["icon"] = str(found.get("icon") or station.get("icon") or "")
                    break
        except Exception as e:
            logger.debug("Radio queue station lookup failed: %s", e)

    return station


def _queue_prune_after_first_radio_locked(reason="radio-terminal"):
    """Radio stations are endless live streams, so no queue items may follow them."""
    first_radio_idx = None
    for idx, tid in enumerate(PLAY_QUEUE):
        meta = PLAY_QUEUE_META_CACHE.get(str(tid), {}) or {}
        if str(tid).startswith("radio:station:") or str(meta.get("source") or "").lower() == "radio":
            first_radio_idx = idx
            break
    if first_radio_idx is None:
        return 0

    removed = list(PLAY_QUEUE[first_radio_idx + 1:])
    if removed:
        del PLAY_QUEUE[first_radio_idx + 1:]

    ORIGINAL_QUEUE[:] = list(PLAY_QUEUE)

    for tid in removed:
        try:
            if str(tid) not in PLAY_QUEUE:
                PLAY_QUEUE_META_CACHE.pop(str(tid), None)
        except Exception:
            pass

    if removed:
        logger.info(
            "Radio terminal queue prune after %s: removed=%d radio_index=%d queue_length=%d",
            reason,
            len(removed),
            first_radio_idx,
            len(PLAY_QUEUE),
        )
    return len(removed)


def _queue_current_item_is_radio():
    try:
        with _QUEUE_LOCK:
            if not PLAY_QUEUE or not (0 <= QUEUE_INDEX < len(PLAY_QUEUE)):
                return False
            tid = str(PLAY_QUEUE[QUEUE_INDEX])
            meta = PLAY_QUEUE_META_CACHE.get(tid, {}) or {}
            return tid.startswith("radio:station:") or str(meta.get("source") or "").lower() == "radio"
    except Exception as e:
        logger.debug("Radio current-queue check failed: %s", e)
        return False


class ControlHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        msg = format % args
        if ('"/status '     in msg) or ('"/tidal/play/' in msg) or \
           ('"/tidal/login/poll' in msg):
            return
        logger.info("HTTP %s - %s", self.address_string(), msg)

    def _send_json(self, data, no_store=False):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        if no_store:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):

        global APP_INSTANCE, PLAY_QUEUE, QUEUE_INDEX, CURRENT_STREAM_INFO
        global REPEAT_MODE, SHUFFLE_ON, ORIGINAL_QUEUE, PLAY_QUEUE_META_CACHE
        global _OAUTH_FUTURE, RADIO_MODE, CURRENT_RADIO, CURRENT_RADIO_METADATA

        static_path = urlparse(self.path).path
        if static_path == "/":
            static_path = "/ui_web/index.html"

        # -- Static files --------------------------------------------------
        if static_path.startswith("/ui_web"):
            file_path = os.path.join(_src_dir, static_path.lstrip("/"))
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                if   file_path.endswith(".html"):        mime = "text/html"
                elif file_path.endswith(".css"):         mime = "text/css"
                elif file_path.endswith(".js"):          mime = "application/javascript"
                elif file_path.endswith(".webmanifest"): mime = "application/manifest+json"
                elif file_path.endswith(".png"):         mime = "image/png"
                elif file_path.endswith(".svg"):         mime = "image/svg+xml"
                elif file_path.endswith(".ico"):         mime = "image/x-icon"
                else:                                    mime = "application/octet-stream"
                self.send_header("Content-Type", mime)
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404)
            return



        # -- Audio output / DAC preference -------------------------------
        if self.path == "/api/audio/output":
            self._send_json(_audio_output_state())
            return

        if self.path == "/api/audio/devices":
            self._send_json({
                "devices": _discover_audio_devices(),
                "current": {
                    "driver": ALSA_DRIVER,
                    "device": ALSA_DEVICE,
                    "dac_name": _resolve_dac_name(ALSA_DEVICE),
                }
            })
            return

        # -- Network / Remote Access ---------------------------------------
        if static_path == "/api/network":
            self._send_json(_network_payload(), no_store=True)
            return

        if static_path == "/api/online-state":
            query = parse_qs(urlparse(self.path).query)
            fresh = str((query.get("fresh") or [""])[0]).lower() in ("1", "true", "yes")
            self._send_json(_online_state_payload(force=fresh), no_store=True)
            return

        # -- Local library scanner/index ------------------------------------
        if static_path == "/api/local/library/browse":
            query = parse_qs(urlparse(self.path).query)
            requested = (query.get("path") or [""])[0]
            try:
                self._send_json(_local_library_browse_payload(requested))
            except PermissionError as e:
                self._send_json({"ok": False, "error": str(e), "path": requested})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e), "path": requested})
            return

        if static_path == "/api/local/library/status":
            data = _local_library_status_payload()
            try:
                configured = _configured_music_root_state()
                active_roots = data.get("roots") if isinstance(data.get("roots"), list) else []
                data["active_roots"] = active_roots
                data["configured_roots"] = configured["roots"]
                data["network_roots"] = configured["network_roots"]
                data["local_roots"] = configured["local_roots"]
            except Exception:
                data["active_roots"] = data.get("roots") if isinstance(data.get("roots"), list) else []
                data["configured_roots"] = data["active_roots"]
                data["network_roots"] = []
                data["local_roots"] = data["configured_roots"]
            self._send_json(data, no_store=True)
            return

        if static_path == "/api/local/library/network/discover":
            query = parse_qs(urlparse(self.path).query)
            fresh = str((query.get("refresh") or [""])[0]).lower() in ("1", "true", "yes")
            self._send_json(_network_music_discover_payload(refresh=fresh), no_store=True)
            return

        if static_path == "/api/local/library/network/mounts":
            self._send_json(_network_music_mounts_payload(), no_store=True)
            return

        if static_path == "/api/local/library/artwork":
            query = parse_qs(urlparse(self.path).query)
            requested = (query.get("p") or [""])[0]
            embedded = (query.get("e") or [""])[0]
            try:
                art = _local_library_artwork_file(requested, embedded_path=embedded)
                with open(art["path"], "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", art["mime"])
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "private, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            except PermissionError:
                self.send_error(403)
            except Exception:
                self.send_error(404)
            return

        if static_path == "/api/local/library/tracks":
            query = parse_qs(urlparse(self.path).query)
            limit = (query.get("limit") or [1000])[0]
            self._send_json(_local_library_tracks_payload(limit=limit))
            return

        if static_path == "/api/local/library/artists":
            query = parse_qs(urlparse(self.path).query)
            limit = (query.get("limit") or [500])[0]
            self._send_json(_local_library_artists_payload(limit=limit))
            return

        if static_path == "/api/local/library/albums":
            query = parse_qs(urlparse(self.path).query)
            limit = (query.get("limit") or [500])[0]
            artist = (query.get("artist") or [""])[0]
            sort = (query.get("sort") or ["latest"])[0]
            self._send_json(_local_library_albums_payload(limit=limit, artist=artist, sort=sort))
            return

        if static_path == "/api/local/library/search":
            query = parse_qs(urlparse(self.path).query)
            text = (query.get("q") or query.get("query") or [""])[0]
            limit = (query.get("limit") or [100])[0]
            self._send_json(_local_library_search_payload(query=text, limit=limit))
            return

        if static_path == "/api/local/library/album":
            query = parse_qs(urlparse(self.path).query)
            album_id = (query.get("id") or query.get("album_id") or query.get("group_id") or [""])[0]
            artist = (query.get("artist") or [""])[0]
            album = (query.get("album") or [""])[0]
            self._send_json(_local_library_album_payload(artist=artist, album=album, album_id=album_id))
            return

        if static_path == "/api/local/library/artist":
            query = parse_qs(urlparse(self.path).query)
            artist = (query.get("artist") or [""])[0]
            limit = (query.get("limit") or [1000])[0]
            self._send_json(_local_library_artist_payload(artist=artist, limit=limit))
            return

        # -- Status --------------------------------------------------------
        if static_path == "/status":
            player   = APP_INSTANCE.player
            raw_position = int(_player_position_seconds(player))
            position = raw_position
            audio_state = _audio_output_state()
            bit_perfect_state = _bit_perfect_state(audio_state)
            playback_context = _status_playback_context(player)
            playback_source = playback_context.get("source")
            current_track_id = playback_context.get("current_track_id")
            context_for_status = playback_context.get("context") or {}
            duration_for_status = int(context_for_status.get("duration") or 0)
            _maybe_schedule_queue_overrun_advance(playback_context, raw_position, duration_for_status)
            if playback_context.get("current_track_valid") and not player.is_playing():
                position = int(_playback_display_position(
                    _resume_position_for_track(current_track_id),
                    playback_context,
                    position_is_raw=False,
                ))
            else:
                position = int(_playback_display_position(raw_position, playback_context, position_is_raw=True))
            status_context_type = context_for_status.get("context_type")
            status_context_id = context_for_status.get("context_id")
            status_context_title = context_for_status.get("context_title")
            if playback_source != "local" and status_context_type == "local":
                status_context_type = None
                status_context_id = None
                status_context_title = None
            status_payload = {
                "running":          True,
                "logged_in":        _tidal_login_snapshot(),
                "sample_rate":      CURRENT_STREAM_INFO["sample_rate"],
                "bit_depth":        CURRENT_STREAM_INFO["bit_depth"],
                "codec":            CURRENT_STREAM_INFO["codec"],
                "playing":          player.is_playing(),
                "playback_state":   playback_context.get("playback_state"),
                "current_track_valid": bool(playback_context.get("current_track_valid")),
                "position":         position,
                "queue_index":      QUEUE_INDEX,
                "queue_length":     len(PLAY_QUEUE),
                "current_track_id": current_track_id,
                "source":           playback_source,
                "title":            context_for_status.get("title"),
                "artist":           context_for_status.get("artist"),
                "album":            context_for_status.get("album"),
                "cover":            context_for_status.get("cover"),
                "duration":         context_for_status.get("duration"),
                "context_type":     status_context_type,
                "context_id":       status_context_id,
                "context_title":    status_context_title,
                "repeat":           REPEAT_MODE,
                "shuffle":          SHUFFLE_ON,
                "exclusive":        bool(getattr(player, "exclusive_lock_mode", False)),
                "alsa_driver":      audio_state.get("alsa_driver"),
                "alsa_device":      audio_state.get("alsa_device"),
                "dac_name":         audio_state.get("dac_name"),
                "dac_locked":       audio_state.get("dac_locked"),
                "radio_mode":       RADIO_MODE,
                "radio_station":    CURRENT_RADIO,
                "radio_metadata":   CURRENT_RADIO_METADATA,
                "tidal_infinite_play_enabled": _tidal_infinite_play_enabled(),
                "tidal_infinite_play_mode": _tidal_infinite_play_mode()
            }
            radio_artwork = _get_current_radio_artwork()
            status_payload.update({
                "radio_cover_art_url": radio_artwork.get("url", ""),
                "radio_cover_art_source": radio_artwork.get("source", ""),
                "radio_cover_art_artist": radio_artwork.get("artist", ""),
                "radio_cover_art_title": radio_artwork.get("title", ""),
                "radio_cover_art_album": radio_artwork.get("album", ""),
                "radio_cover_art_updated_at": radio_artwork.get("updated_at", 0),
            })
            status_payload.update(bit_perfect_state)
            self._send_json(status_payload)
            return

        # -- Cache utils ---------------------------------------------------
        if self.path == "/cache/stats":
            self._send_json(cache_stats())
            return

        if self.path == "/cache/clear":
            cache_invalidate()
            logger.info("Cache cleared (all)")
            self._send_json({"cleared": "all"})
            return

        if self.path == "/cache/clear/home":
            cache_invalidate("home")
            cache_invalidate("hires")
            cache_invalidate("featured")
            logger.info("Cache cleared (home)")
            self._send_json({"cleared": "home"})
            return

        if static_path == "/tidal/status":
            self._send_json(_tidal_status_payload(), no_store=True)
            return

        # -- Login: start OAuth flow ---------------------------------------
        # Returns { "url": "...", "user_code": "..." }
        if self.path == "/tidal/login/start":
            with _OAUTH_LOCK:
                try:
                    result       = APP_INSTANCE.backend.start_oauth()
                    _OAUTH_FUTURE = result["future"]
                    logger.info("OAuth started: %s", result["url"])
                    self._send_json({
                        "url":       result["url"],
                        "user_code": result.get("user_code", "")
                    })
                except Exception as e:
                    logger.error("OAuth start failed: %s", e)
                    self._send_json({"error": str(e)})
            return

        # -- Login: poll for completion ------------------------------------
        # Returns { "logged_in": true } or { "logged_in": false, "pending": true }
        if self.path == "/tidal/login/poll":
            with _OAUTH_LOCK:
                future = _OAUTH_FUTURE
            if future is None:
                self._send_json({"logged_in": False, "error": "No login in progress"})
                return
            try:
                if not future.done():
                    self._send_json({"logged_in": False, "pending": True})
                    return
                ok = APP_INSTANCE.backend.finish_login(future)
                if ok:
                    logger.info("OAuth login completed successfully")
                    # Clear all caches so home/playlists reload fresh
                    cache_invalidate()
                    with _OAUTH_LOCK:
                        _OAUTH_FUTURE = None
                    self._send_json({"logged_in": True})
                else:
                    err = APP_INSTANCE.backend.get_last_login_error()
                    self._send_json({"logged_in": False, "error": err})
            except Exception as e:
                logger.error("OAuth poll failed: %s", e)
                self._send_json({"logged_in": False, "error": str(e)})
            return

        # -- Logout --------------------------------------------------------
        if self.path == "/tidal/logout":
            try:
                APP_INSTANCE.backend.logout()
                cache_invalidate()
                logger.info("Logged out and cache cleared")
                self._send_json({"logged_out": True})
            except Exception as e:
                logger.error("Logout failed: %s", e)
                self._send_json({"error": str(e)})
            return

        # -- My Playlists --------------------------------------------------
        if self.path == "/tidal/myplaylists":
            cached = cache_get("myplaylists")
            if cached is not None:
                logger.info("Cache HIT: myplaylists")
                self._send_json(cached)
                return

            # Return empty immediately so the UI does not block, then fetch
            # in a background daemon thread.  The UI will retry after a delay
            # and pick up the cache once the slow Tidal API call completes.
            self._send_json([])

            backend = APP_INSTANCE.backend

            def _bg_fetch():
                result = []
                try:
                    import requests as _req

                    # Bypass tidalapi's blocking user.favorites.playlists() call.
                    # Call the Tidal v2 REST API directly with a hard timeout so
                    # this thread can never hang indefinitely.

                    access_token = getattr(backend.session, "access_token", None)
                    if not access_token:
                        logger.warning("bg playlists: no access token available")
                        return

                    base = "https://api.tidal.com/v2/"
                    try:
                        cfg_base = getattr(
                            getattr(backend.session, "config", None),
                            "api_v2_location", None
                        )
                        if cfg_base:
                            base = cfg_base.rstrip("/") + "/"
                    except Exception:
                        pass

                    headers  = {"Authorization": "Bearer " + access_token}
                    limit    = 50
                    seen_ids = set()
                    cursor   = None   # Tidal v2 uses cursor-based pagination

                    while True:
                        params = {
                            "folderId":       "root",
                            "includeOnly":    "PLAYLIST",
                            "limit":          limit,
                            "order":          "NAME",
                            "orderDirection": "ASC",
                        }
                        # Use cursor if we have one, otherwise start from offset 0
                        if cursor:
                            params["cursor"] = cursor
                        else:
                            params["offset"] = 0

                        try:
                            resp = _req.get(
                                base + "my-collection/playlists/folders",
                                headers=headers,
                                params=params,
                                timeout=10
                            )
                            resp.raise_for_status()
                            data = resp.json()
                        except Exception as re:
                            logger.warning("bg playlists: API request failed: %s", re)
                            break

                        items = data.get("items") or []
                        if not items:
                            break

                        new_this_page = 0
                        for item in items:
                            pl  = item.get("data") or item
                            pid = str(pl.get("uuid") or pl.get("id") or "").strip()
                            if not pid or pid in seen_ids:
                                continue
                            seen_ids.add(pid)
                            new_this_page += 1
                            name       = str(pl.get("title") or pl.get("name") or "").strip()
                            num_tracks = pl.get("numberOfTracks") or pl.get("num_tracks") or 0
                            sub        = str(num_tracks) + " tracks" if num_tracks else ""
                            img_url    = ""
                            img_uuid   = (pl.get("squareImage") or
                                          pl.get("image") or
                                          pl.get("imageId") or "")
                            if img_uuid:
                                token   = str(img_uuid).replace("-", "/")
                                img_url = ("https://resources.tidal.com/images/"
                                           + token + "/320x320.jpg")
                            last_updated = str(pl.get("lastUpdated") or
                                               pl.get("lastModifiedAt") or "")
                            created_at   = str(pl.get("createdAt") or
                                               pl.get("created") or "")
                            result.append({
                                "id":           pid,
                                "name":         name,
                                "num_tracks":   num_tracks,
                                "sub_title":    sub,
                                "image_url":    img_url,
                                "last_updated": last_updated,
                                "created_at":   created_at
                            })

                        total = (data.get("totalNumberOfItems") or
                                 data.get("total") or
                                 data.get("totalCount") or 0)

                        # Try to get next cursor from response
                        next_cursor = (data.get("cursor") or
                                       data.get("nextCursor") or
                                       data.get("next_cursor") or
                                       (data.get("metadata") or {}).get("cursor") or
                                       None)

                        logger.info("bg playlists: got=%d new=%d total=%d accumulated=%d cursor=%s",
                                    len(items), new_this_page, total, len(result),
                                    bool(next_cursor))

                        # If all items this page were duplicates, pagination isn't advancing
                        if new_this_page == 0:
                            logger.warning("bg playlists: all items on this page were duplicates -- stopping")
                            break

                        cursor = next_cursor if next_cursor else None

                        # Stop conditions
                        if len(items) < limit:
                            break
                        if total > 0 and len(result) >= total:
                            break

                    logger.info("bg playlists: fetched %d playlists", len(result))
                    if result:
                        cache_set("myplaylists", result, TTL_PLAYLISTS)
                    else:
                        logger.warning("bg playlists: API returned 0 playlists")
                except Exception as e:
                    logger.warning("bg playlists fetch failed: %s", e)

            t = threading.Thread(target=_bg_fetch, daemon=True)
            t.start()
            return

        # -- Playlists: find duplicates ------------------------------------
        # Returns groups of playlists that share name + track count and have
        # total duration within 30s of each other.
        # Only fetches full track lists for the candidate groups (strategy B).
        if self.path == "/tidal/playlists/find_duplicates":
            playlists = cache_get("myplaylists")
            if not playlists:
                self._send_json({"error": "playlists_not_loaded",
                                 "message": "Open My Playlists first so the list loads, then retry."})
                return

            # Group by name, then by track count
            from collections import defaultdict
            by_name = defaultdict(list)
            for pl in playlists:
                by_name[pl["name"].strip()].append(pl)

            # Collect candidate groups: same name, same num_tracks, 2+ playlists
            candidates = []
            for name, group in by_name.items():
                by_count = defaultdict(list)
                for pl in group:
                    by_count[int(pl.get("num_tracks", 0))].append(pl)
                for count, pls in by_count.items():
                    if len(pls) >= 2:
                        candidates.append(pls)

            if not candidates:
                self._send_json({"groups": [], "total_to_delete": 0})
                return

            # Fetch durations for all candidates in parallel
            backend = APP_INSTANCE.backend
            duration_results = {}
            dur_lock = threading.Lock()

            def _fetch_duration(pl_id):
                try:
                    pl_obj = backend.session.playlist(pl_id)
                    tracks = pl_obj.items()
                    total  = sum(int(getattr(t, "duration", 0) or 0) for t in tracks)
                    with dur_lock:
                        duration_results[pl_id] = total
                except Exception as e:
                    logger.warning("duration fetch failed for %s: %s", pl_id, e)
                    with dur_lock:
                        duration_results[pl_id] = None

            threads = []
            for group in candidates:
                for pl in group:
                    t = threading.Thread(
                        target=_fetch_duration, args=(pl["id"],), daemon=True
                    )
                    threads.append(t)
            # Stagger starts to avoid overwhelming DNS with parallel requests
            for i, t in enumerate(threads):
                t.start()
                if i % 4 == 3:
                    time.sleep(0.1)
            for t in threads:
                t.join(timeout=30)

            # Resolve each candidate group: find duplicates within +/-30s
            result_groups = []
            for group in candidates:
                # Attach durations
                for pl in group:
                    pl["duration"] = duration_results.get(pl["id"])

                # Remove playlists where duration fetch failed
                valid = [pl for pl in group if pl["duration"] is not None]
                if len(valid) < 2:
                    continue

                # Sort by duration descending (keep longest)
                valid.sort(key=lambda p: p["duration"], reverse=True)

                # Find pairs within 30s of each other
                to_keep   = []
                to_delete = []
                used = set()
                for i in range(len(valid)):
                    if i in used:
                        continue
                    keep = valid[i]
                    dupes = []
                    for j in range(i + 1, len(valid)):
                        if j in used:
                            continue
                        if abs(valid[j]["duration"] - keep["duration"]) <= 30:
                            dupes.append(valid[j])
                            used.add(j)
                    if dupes:
                        used.add(i)
                        to_keep.append(keep)
                        to_delete.extend(dupes)

                if to_delete:
                    result_groups.append({
                        "name":      valid[0]["name"],
                        "keep":      to_keep,
                        "delete":    to_delete
                    })

            total_to_delete = sum(len(g["delete"]) for g in result_groups)
            logger.info("find_duplicates: %d groups, %d to delete",
                        len(result_groups), total_to_delete)
            self._send_json({
                "groups":          result_groups,
                "total_to_delete": total_to_delete
            })
            return

        # -- My Albums (liked albums, most recent first) -------------------
        if self.path == "/tidal/myalbums":
            cached = cache_get("myalbums")
            if cached is not None:
                self._send_json(cached)
                return
            self._send_json([])
            backend = APP_INSTANCE.backend
            def _bg_albums():
                try:
                    albums = backend.get_recent_albums(limit=2000)
                    # Sort by add-date descending (most recently liked first).
                    # user_date_added is a datetime on tidalapi objects; fall back
                    # to reversed() order if the attribute is not present.
                    try:
                        albums = sorted(
                            albums,
                            key=lambda a: getattr(a, "user_date_added", None) or 0,
                            reverse=True
                        )
                    except Exception:
                        albums = list(reversed(albums))
                    result = []
                    for a in albums:
                        image_url = _safe_artwork(backend, a, 320)
                        artist_name = ""
                        try:
                            artist_name = _safe_str(a.artist.name if a.artist else "")
                        except Exception:
                            pass
                        result.append({
                            "id":        getattr(a, "id", None),
                            "name":      _safe_str(getattr(a, "name", "")),
                            "sub_title": artist_name,
                            "image_url": image_url,
                            "quality":   _quality_badge(a),
                            "type":      "Album"
                        })
                    if result:
                        cache_set("myalbums", result, TTL_PLAYLISTS)
                    logger.info("myalbums: fetched %d albums", len(result))
                except Exception as e:
                    logger.warning("myalbums fetch failed: %s", e)
            threading.Thread(target=_bg_albums, daemon=True).start()
            return

        # -- My Songs (liked tracks, most recent first) --------------------
        if self.path == "/tidal/mysongs":
            cached = cache_get("mysongs")
            if cached is not None:
                self._send_json(cached)
                return
            self._send_json([])
            backend = APP_INSTANCE.backend
            def _bg_songs():
                try:
                    tracks = backend.get_favorite_tracks(limit=500)
                    # Sort by add-date descending (most recently liked first).
                    try:
                        tracks = sorted(
                            tracks,
                            key=lambda t: getattr(t, "user_date_added", None) or 0,
                            reverse=True
                        )
                    except Exception:
                        tracks = list(reversed(tracks))
                    result = []
                    for t in tracks:
                        cover_url = ""
                        try:
                            album_obj = getattr(t, "album", None)
                            for attr in ("cover", "image", "squareImage", "imageId"):
                                cid = getattr(album_obj, attr, None) if album_obj else None
                                if cid and str(cid).strip():
                                    cover_url = ("https://resources.tidal.com/images/"
                                                 + str(cid).replace("-", "/") + "/320x320.jpg")
                                    break
                        except Exception:
                            pass
                        artist_name = ""
                        try:
                            artist_obj  = getattr(t, "artist", None)
                            artist_name = _safe_str(artist_obj.name) if artist_obj else ""
                        except Exception:
                            pass
                        result.append({
                            "id":        getattr(t, "id", None),
                            "name":      _safe_str(getattr(t, "name", "")),
                            "sub_title": artist_name,
                            "image_url": cover_url,
                            "duration":  int(getattr(t, "duration", 0) or 0),
                            "quality":   _quality_badge(t),
                            "type":      "Track"
                        })
                    if result:
                        cache_set("mysongs", result, TTL_PLAYLISTS)
                    logger.info("mysongs: fetched %d tracks", len(result))
                except Exception as e:
                    logger.warning("mysongs fetch failed: %s", e)
            threading.Thread(target=_bg_songs, daemon=True).start()
            return

        # -- Home page -----------------------------------------------------
        if self.path == "/tidal/home":
            cached = cache_get("home")
            if cached is not None:
                logger.info("Cache HIT: home")
                self._send_json(cached)
                return

            logger.info("Cache MISS: home -- fetching from Tidal")
            backend      = APP_INSTANCE.backend
            sections_out = []
            try:
                sections = backend.get_home_page()
                for sec in sections:
                    sec_title = _safe_str(sec.get("title"))
                    if _home_section_excluded(sec_title):
                        logger.debug("Home: skipping excluded section %r", sec_title)
                        continue
                    items = []
                    for it in sec.get("items", []):
                        obj      = it.get("obj")
                        raw_type = it.get("type") or (type(obj).__name__ if obj else "Album")
                        rl       = str(raw_type).lower()
                        if   "playlist" in rl: type_str = "Playlist"
                        elif "mix"      in rl: type_str = "Mix"
                        elif "track"    in rl: type_str = "Track"
                        elif "album"    in rl: type_str = "Album"
                        else:                  type_str = "Album"
                        duration = None
                        if type_str == "Track" and obj is not None:
                            try:
                                duration = int(getattr(obj, "duration", 0) or 0) or None
                            except Exception:
                                duration = None
                        image_url = it.get("image_url")
                        if not image_url and obj is not None:
                            try:
                                image_url = _safe_artwork(backend, obj, 320) or None
                            except Exception:
                                pass
                        items.append({
                            "name":      _safe_str(it.get("name")),
                            "sub_title": _safe_str(it.get("sub_title")),
                            "image_url": image_url,
                            "id":        getattr(obj, "id", None) if obj else None,
                            "type":      type_str,
                            "quality":   _quality_badge(obj) if obj is not None else None,
                            "duration":  duration
                        })
                    if items:
                        sections_out.append({"title": sec_title, "items": items})
            except Exception as e:
                logger.warning("Home fetch failed: %s", e)

            cache_set("home", sections_out, TTL_HOME)
            self._send_json(sections_out)
            return

        # -- Hi-Res page ---------------------------------------------------
        if self.path == "/tidal/hires":
            cached = cache_get("hires")
            if cached is not None:
                logger.info("Cache HIT: hires")
                self._send_json(cached)
                return

            logger.info("Cache MISS: hires -- fetching from Tidal")
            backend      = APP_INSTANCE.backend
            sections_out = []
            try:
                sections = backend.get_hires_page()
                for sec in sections:
                    items = []
                    for it in sec.get("items", []):
                        obj      = it.get("obj")
                        raw_type = it.get("type") or (type(obj).__name__ if obj else "Album")
                        rl       = str(raw_type).lower()
                        if   "playlist" in rl: type_str = "Playlist"
                        elif "mix"      in rl: type_str = "Mix"
                        elif "track"    in rl: type_str = "Track"
                        elif "album"    in rl: type_str = "Album"
                        else:                  type_str = "Album"
                        duration = None
                        if type_str == "Track" and obj is not None:
                            try:
                                duration = int(getattr(obj, "duration", 0) or 0) or None
                            except Exception:
                                duration = None
                        items.append({
                            "name":      _safe_str(it.get("name")),
                            "sub_title": _safe_str(it.get("sub_title")),
                            "image_url": it.get("image_url"),
                            "id":        getattr(obj, "id", None) if obj else None,
                            "type":      type_str,
                            "quality":   _quality_badge(obj) if obj is not None else "HI-RES",
                            "duration":  duration
                        })
                    sections_out.append({
                        "title": _safe_str(sec.get("title")),
                        "items": items
                    })
            except Exception as e:
                logger.warning("Hi-Res page fetch failed: %s", e)

            cache_set("hires", sections_out, TTL_HOME)
            self._send_json(sections_out)
            return

        # -- Featured: Top Tracks/Albums/Hits + New Tracks/Albums -----------
        # Fetched from Tidal's explore_top_music and explore_new_music pages.
        # Returns empty array immediately and fills cache in a background thread.
        if self.path == "/tidal/featured":
            cached = cache_get("featured")
            if cached is not None:
                logger.info("Cache HIT: featured")
                self._send_json(cached)
                return
            # Return empty so the frontend slot-poll pattern kicks in
            self._send_json([])
            backend = APP_INSTANCE.backend

            def _bg_featured():
                top_raw = []
                new_raw = []

                def _fetch_top():
                    try:
                        top_raw.extend(backend.get_top_page() or [])
                    except Exception as e:
                        logger.warning("Featured top page failed: %s", e)

                def _fetch_new():
                    try:
                        new_raw.extend(backend.get_new_page() or [])
                    except Exception as e:
                        logger.warning("Featured new page failed: %s", e)

                t1 = threading.Thread(target=_fetch_top, daemon=True)
                t2 = threading.Thread(target=_fetch_new, daemon=True)
                t1.start(); t2.start()
                t1.join(timeout=30); t2.join(timeout=30)

                def _cover_from_track_obj(track_obj):
                    """Extract album cover URL from a real tidalapi Track object."""
                    try:
                        album_obj = getattr(track_obj, "album", None)
                        for attr in ("cover", "image", "squareImage", "imageId"):
                            cid = getattr(album_obj, attr, None) if album_obj else None
                            if cid and str(cid).strip():
                                return ("https://resources.tidal.com/images/"
                                        + str(cid).replace("-", "/") + "/320x320.jpg")
                    except Exception:
                        pass
                    return None

                def _resolve_track_covers(items):
                    """Parallel-fetch real Track objects for items with no cover."""
                    to_resolve = [
                        (i, it) for i, it in enumerate(items)
                        if it["type"] == "Track"
                        and not it.get("image_url")
                        and it.get("id")
                    ]
                    if not to_resolve:
                        return
                    cover_lock    = threading.Lock()
                    cover_results = {}

                    def _fetch(idx, item_id):
                        try:
                            track_obj = backend.session.track(item_id)
                            url = _cover_from_track_obj(track_obj)
                            if url:
                                with cover_lock:
                                    cover_results[idx] = url
                        except Exception:
                            pass

                    threads = [
                        threading.Thread(target=_fetch, args=(i, it["id"]), daemon=True)
                        for i, it in to_resolve
                    ]
                    for th in threads: th.start()
                    for th in threads: th.join(timeout=8)
                    for idx, url in cover_results.items():
                        items[idx]["image_url"] = url

                def _process_page(raw_sections):
                    """Convert page sections to our standard item format."""
                    skip_titles = (
                        "albums you'll enjoy",
                    )
                    out = []
                    for sec in raw_sections:
                        sec_title_lc = str(sec.get("title", "")).strip().lower()
                        if any(ex in sec_title_lc for ex in skip_titles):
                            logger.debug("Featured: skipping excluded section %r", sec.get("title"))
                            continue
                        items = []
                        for it in sec.get("items", []):
                            obj      = it.get("obj")
                            raw_type = it.get("type") or (type(obj).__name__ if obj else "")
                            rl       = str(raw_type).lower()
                            if   "track"    in rl: type_str = "Track"
                            elif "album"    in rl: type_str = "Album"
                            elif "playlist" in rl: type_str = "Playlist"
                            elif "mix"      in rl: type_str = "Mix"
                            else:                  continue
                            duration = None
                            if type_str == "Track" and obj is not None:
                                try:
                                    duration = int(getattr(obj, "duration", 0) or 0) or None
                                except Exception:
                                    pass
                            # image_url: use what the page gave us, or try
                            # _safe_artwork on the obj as a quick attempt.
                            # Missing Track covers are resolved below via
                            # _resolve_track_covers() which fetches real Track objects.
                            image_url = it.get("image_url")
                            if not image_url and obj is not None:
                                try:
                                    image_url = _safe_artwork(backend, obj, 320) or None
                                except Exception:
                                    pass
                            items.append({
                                "name":      _safe_str(it.get("name")),
                                "sub_title": _safe_str(it.get("sub_title")),
                                "image_url": image_url,
                                "id":        getattr(obj, "id", None) if obj else None,
                                "type":      type_str,
                                "quality":   _quality_badge(obj) if obj is not None else None,
                                "duration":  duration
                            })
                        # Resolve any Track items that still have no cover
                        _resolve_track_covers(items)
                        if items:
                            out.append({
                                "title": sec.get("title", ""),
                                "items": items,
                                "_dominant": max(
                                    set(x["type"] for x in items),
                                    key=lambda t: sum(1 for x in items if x["type"] == t)
                                )
                            })
                    return out

                def _pick(processed, dominant, exclude=None):
                    """Pick first section whose dominant item type matches."""
                    exclude = exclude or []
                    for sec in processed:
                        if sec in exclude:
                            continue
                        if sec.get("_dominant") == dominant:
                            return sec
                    return None

                top = _process_page(top_raw)
                new = _process_page(new_raw)

                top_tracks = _pick(top, "Track")
                top_albums = _pick(top, "Album")
                # Top Hits: second track section, else first mix/playlist from top
                top_hits = _pick(top, "Track", exclude=[top_tracks] if top_tracks else [])
                if not top_hits:
                    top_hits = _pick(top, "Mix") or _pick(top, "Playlist")
                new_tracks = _pick(new, "Track")
                new_albums = _pick(new, "Album")

                wanted = [
                    ("Top Tracks", top_tracks),
                    ("Top Albums", top_albums),
                    ("Top Hits",   top_hits),
                    ("New Tracks", new_tracks),
                    ("New Albums", new_albums),
                ]
                result = []
                for title, sec in wanted:
                    if sec:
                        result.append({
                            "title": title,
                            "items": [{k: v for k, v in it.items() if k != "_dominant"}
                                      for it in sec["items"]]
                        })

                if result:
                    cache_set("featured", result, TTL_FEATURED)
                    logger.info("Featured: cached %d sections", len(result))
                else:
                    logger.warning("Featured: no sections found")

            threading.Thread(target=_bg_featured, daemon=True).start()
            return
        if self.path.startswith("/tidal/search"):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            query  = params.get("q", [""])[0].strip()
            limit_per_type = _bounded_int((params.get("limit") or [6])[0], default=6, minimum=1, maximum=100)
            if not query:
                self._send_json({"artists": [], "albums": [], "tracks": []})
                return

            cache_key = "search:" + query.lower() + ":" + str(limit_per_type)
            cached    = cache_get(cache_key)
            if cached is not None:
                logger.info("Cache HIT: search '%s'", query)
                self._send_json(cached)
                return

            logger.info("Cache MISS: search '%s' limit=%s", query, limit_per_type)
            backend = APP_INSTANCE.backend
            out     = {"artists": [], "albums": [], "tracks": []}
            try:
                if hasattr(backend, "session"):
                    if hasattr(backend.session, "check_login") and not backend.session.check_login():
                        raise RuntimeError("Tidal session expired or not logged in during search.")
                    api_limit = max(limit_per_type, min(limit_per_type * 3, 300))
                    raw = backend.session.search(query, limit=api_limit)
                    results = {"artists": [], "albums": [], "tracks": []}
                    for key in results:
                        items = getattr(raw, key, None)
                        if items is None and isinstance(raw, dict):
                            items = raw.get(key)
                        if items:
                            items = items() if callable(items) else items
                            results[key] = list(items)[:limit_per_type]
                else:
                    results = backend.search_items(query)
                for a in results.get("artists", []):
                    out["artists"].append({
                        "id":        getattr(a, "id", None),
                        "name":      _safe_str(getattr(a, "name", "")),
                        "image_url": _safe_artwork(backend, a, 320)
                    })
                for a in results.get("albums", []):
                    artist_name = ""
                    try:
                        artist_name = _safe_str(a.artist.name if a.artist else "")
                    except Exception:
                        pass
                    out["albums"].append({
                        "id":        getattr(a, "id", None),
                        "name":      _safe_str(getattr(a, "name", "")),
                        "artist":    artist_name,
                        "image_url": _safe_artwork(backend, a, 320)
                    })
                for t in results.get("tracks", []):
                    artist_name = ""
                    try:
                        artist_name = _safe_str(t.artist.name if t.artist else "")
                    except Exception:
                        pass
                    out["tracks"].append({
                        "id":        getattr(t, "id",       None),
                        "name":      _safe_str(getattr(t, "name", "")),
                        "duration":  getattr(t, "duration", 0),
                        "artist":    artist_name,
                        "image_url": _safe_artwork(backend, t, 320)
                    })
            except Exception as e:
                logger.warning("Search failed: %s", e)

            cache_set(cache_key, out, TTL_SEARCH)
            self._send_json(out)
            return

        # -- Artist discography (albums + EPs/singles) ---------------------
        # Must sit before the /tidal/artist/ top-tracks handler.
        if self.path.startswith("/tidal/artist/") and self.path.endswith("/albums"):
            parts     = self.path.rstrip("/").split("/")
            artist_id = parts[-2]
            cache_key = "artist_discog:" + artist_id
            cached    = cache_get(cache_key)
            if cached is not None:
                logger.info("Cache HIT: artist discog %s", artist_id)
                self._send_json(cached)
                return
            logger.info("Cache MISS: artist discog %s", artist_id)
            backend = APP_INSTANCE.backend
            try:
                artist = backend.session.artist(artist_id)
                albums = []
                # Try various tidalapi versions
                for _attempt in (
                    lambda: list(artist.get_albums()            or []),
                    lambda: list(artist.albums()                or []),
                ):
                    try:
                        _r = _attempt()
                        if _r:
                            albums = _r
                            break
                    except Exception:
                        pass
                eps = []
                for _attempt in (
                    lambda: list(artist.get_albums_ep_singles() or []),
                    lambda: list(artist.get_eps_and_singles()   or []),
                ):
                    try:
                        _r = _attempt()
                        if _r:
                            eps = _r
                            break
                    except Exception:
                        pass
                seen_ids = set()
                data = []
                for a in (albums + eps):
                    aid = getattr(a, "id", None)
                    if not aid or str(aid) in seen_ids:
                        continue
                    seen_ids.add(str(aid))
                    release_date = ""
                    try:
                        rd = getattr(a, "release_date", None)
                        if rd:
                            release_date = str(rd)[:10]
                    except Exception:
                        pass
                    album_type = "ALBUM"
                    try:
                        at = (getattr(a, "type", None) or
                              getattr(a, "album_type", None))
                        if at:
                            album_type = str(at).upper().split(".")[-1]
                    except Exception:
                        pass
                    data.append({
                        "id":           aid,
                        "name":         _safe_str(getattr(a, "name", "")),
                        "image_url":    _safe_artwork(backend, a, 320),
                        "release_date": release_date,
                        "num_tracks":   int(getattr(a, "num_tracks", 0) or 0),
                        "type":         album_type,
                    })

                # Second-pass dedup: among editions with the same normalised title
                # keep the highest-quality version (HI-RES > LOSSLESS > HIGH > unknown).
                import re as _re
                def _norm_title(t):
                    return _re.sub(r"[^a-z0-9]", "", str(t or "").lower())

                def _quality_rank(a):
                    aq = str(getattr(a, "audio_quality", "") or "").upper()
                    if any(x in aq for x in ("HI_RES_LOSSLESS", "HI_RES", "MASTER")): return 3
                    if any(x in aq for x in ("HIGH_LOSSLESS", "LOSSLESS")):            return 2
                    if "HIGH" in aq:                                                    return 1
                    return 0

                # Build a quality-ranked map: norm_title -> (rank, album_obj, data_dict)
                title_map = {}   # norm_title -> (rank, album_obj, data_dict)
                album_obj_map = {}  # aid -> tidalapi album object (for quality lookup)
                for a in (albums + eps):
                    aid = str(getattr(a, "id", "") or "")
                    if aid:
                        album_obj_map[aid] = a

                for item in data:
                    key  = _norm_title(item["name"])
                    if not key:
                        continue
                    aid  = str(item.get("id") or "")
                    rank = _quality_rank(album_obj_map.get(aid))
                    if key not in title_map or rank > title_map[key][0]:
                        title_map[key] = (rank, item)

                # Reconstruct in original order, one entry per title
                seen_titles = set()
                deduped = []
                for item in data:
                    key = _norm_title(item["name"])
                    if not key or key in seen_titles:
                        continue
                    seen_titles.add(key)
                    deduped.append(title_map[key][1])
                data = deduped
                cache_set(cache_key, data, TTL_TRACKS)
                self._send_json(data)
            except Exception as e:
                logger.warning("Artist discography fetch failed: %s", e)
                self._send_json({"error": str(e)})
            return

        # -- Artist top tracks ---------------------------------------------
        if self.path.startswith("/tidal/artist/"):
            artist_id = self.path.split("/")[-1]
            cache_key = "artist:" + artist_id
            cached    = cache_get(cache_key)
            if cached is not None:
                logger.info("Cache HIT: artist %s", artist_id)
                _rebuild_queue_from_cache(cached)
                self._send_json(cached)
                return
            logger.info("Cache MISS: artist %s", artist_id)
            backend = APP_INSTANCE.backend
            try:
                tracks = backend.get_artist_top_tracks(artist_id, limit=10)
                data   = _build_track_list(tracks, show_artist=True)
                cache_set(cache_key, data, TTL_TRACKS)
                self._send_json(data)
            except Exception as e:
                logger.warning("Artist top tracks fetch failed: %s", e)
                self._send_json({"error": str(e)})
            return

        # -- Album tracks --------------------------------------------------
        if self.path.startswith("/tidal/album/"):
            album_id  = self.path.split("/")[-1]
            cache_key = "album:" + album_id
            cached    = cache_get(cache_key)
            if cached is not None:
                logger.info("Cache HIT: album %s", album_id)
                _rebuild_queue_from_cache(cached)
                self._send_json(cached)
                return
            logger.info("Cache MISS: album %s", album_id)
            backend = APP_INSTANCE.backend
            try:
                album  = backend.session.album(album_id)
                tracks = album.tracks()
                CURRENT_CONTEXT["context_title"] = str(getattr(album, "name", "") or "")
                CURRENT_CONTEXT["context_type"]  = "album"
                CURRENT_CONTEXT["context_id"]    = str(album_id)
                data = _build_track_list(tracks, show_artist=False)
                # Wrap with album artist info so the UI can make the artist name clickable
                album_artist_id   = ""
                album_artist_name = ""
                try:
                    artist_obj = getattr(album, "artist", None)
                    if artist_obj:
                        album_artist_id   = str(getattr(artist_obj, "id",   "") or "")
                        album_artist_name = str(getattr(artist_obj, "name", "") or "")
                except Exception:
                    pass
                result = {
                    "tracks":      data,
                    "artist_id":   album_artist_id,
                    "artist_name": album_artist_name
                }
                cache_set(cache_key, result, TTL_TRACKS)
                self._send_json(result)
            except Exception as e:
                logger.warning("Album track fetch failed: %s", e)
                self._send_json({"error": str(e)})
            return

        # -- Playlist tracks -----------------------------------------------
        if self.path.startswith("/tidal/playlist/"):
            playlist_id = self.path.split("/")[-1]
            cache_key   = "playlist:" + playlist_id
            cached      = cache_get(cache_key)
            if cached is not None:
                logger.info("Cache HIT: playlist %s", playlist_id)
                _rebuild_queue_from_cache(cached)
                self._send_json(cached)
                return
            logger.info("Cache MISS: playlist %s", playlist_id)
            backend = APP_INSTANCE.backend
            try:
                pl = backend.session.playlist(playlist_id)
                tracks = pl.items()
                playlist_name = str(getattr(pl, "name", "") or "")
                playlist_editable = bool(
                    backend._is_owned_user_playlist(pl)
                )
                CURRENT_CONTEXT["context_title"] = playlist_name
                CURRENT_CONTEXT["context_type"] = "playlist"
                CURRENT_CONTEXT["context_id"] = str(playlist_id)
                data = _build_track_list(tracks, show_artist=True)
                result = {
                    "tracks": data,
                    "playlist_id": str(playlist_id),
                    "playlist_name": playlist_name,
                    "playlist_editable": playlist_editable,
                }
                cache_set(cache_key, result, TTL_TRACKS)
                self._send_json(result)
            except Exception as e:
                logger.warning("Playlist track fetch failed: %s", e)
                self._send_json({"error": str(e)})
            return

        # -- Mix tracks ----------------------------------------------------
        if self.path.startswith("/tidal/mix/"):
            mix_id    = self.path.split("/")[-1]
            cache_key = "mix:" + mix_id
            cached    = cache_get(cache_key)
            if cached is not None:
                logger.info("Cache HIT: mix %s", mix_id)
                _rebuild_queue_from_cache(cached)
                self._send_json(cached)
                return
            logger.info("Cache MISS: mix %s", mix_id)
            backend = APP_INSTANCE.backend
            try:
                mix    = backend.session.mix(mix_id)
                tracks = mix.items()
                CURRENT_CONTEXT["context_title"] = str(getattr(mix, "title", "") or "")
                CURRENT_CONTEXT["context_type"]  = "mix"
                CURRENT_CONTEXT["context_id"]    = str(mix_id)
                data   = _build_track_list(tracks, show_artist=True)
                cache_set(cache_key, data, TTL_TRACKS)
                self._send_json(data)
            except Exception as e:
                logger.warning("Mix track fetch failed: %s", e)
                self._send_json({"error": str(e)})
            return

        # -- Queue: read state ---------------------------------------------
        if self.path == "/tidal/queue":
            with _QUEUE_LOCK:
                tracks = []
                for tid in PLAY_QUEUE:
                    meta = PLAY_QUEUE_META_CACHE.get(str(tid))
                    if not meta:
                        meta = {"id": tid, "title": "", "artist": "",
                                "cover": "", "duration": 0, "quality": ""}
                    tracks.append(meta)
                self._send_json({
                    "queue_index":  QUEUE_INDEX,
                    "queue_length": len(PLAY_QUEUE),
                    "tracks":       tracks
                })
            return

        # -- Queue: jump to index ------------------------------------------
        if self.path.startswith("/tidal/queue/jump/"):
            try:
                idx = int(self.path.split("/")[-1])
            except ValueError:
                self.send_error(400)
                return
            try:
                _require_audio_output_for_playback("queue jump")
            except AudioOutputUnavailable as e:
                self._send_json(e.to_payload())
                return
            if RADIO_MODE:
                _cancel_pending_radio_start()
                _METADATA_REGISTRY.detach()
                _set_radio_switching_guard()
                CURRENT_RADIO_METADATA = {}
                _set_current_radio_artwork({})
                RADIO_MODE    = False
                CURRENT_RADIO = None
                _set_player_live_radio_mode(enabled=False)
            with _QUEUE_LOCK:
                if not (0 <= idx < len(PLAY_QUEUE)):
                    self._send_json({"error": "index out of range"})
                    return
                QUEUE_INDEX = idx
            save_queue()
            _invalidate_tidal_stream_resolution("queue-jump")
            GLib.idle_add(lambda: play_queue_index(idx))
            self._send_json({"result": "ok"})
            return

        # -- Queue: remove track at index ----------------------------------
        if self.path.startswith("/tidal/queue/remove/"):
            try:
                idx = int(self.path.split("/")[-1])
            except ValueError:
                self.send_error(400)
                return
            removed_current = False
            with _QUEUE_LOCK:
                _queue_ensure_canonical_locked()
                if 0 <= idx < len(PLAY_QUEUE):
                    removed_current = _queue_remove_active_index_locked(idx)
            if removed_current:
                _finalize_end_of_queue_playback("Current queue item removed")
            save_queue()
            self._send_json({
                "result": "ok",
                "queue_length": len(PLAY_QUEUE),
                "stopped": removed_current,
            })
            return

        # -- Queue: clear upcoming -----------------------------------------
        if self.path == "/tidal/queue/clear/upcoming":
            with _QUEUE_LOCK:
                _queue_ensure_canonical_locked()
                if QUEUE_INDEX < len(PLAY_QUEUE):
                    _queue_remove_active_indices_locked(range(QUEUE_INDEX + 1, len(PLAY_QUEUE)))
            save_queue()
            self._send_json({"result": "ok", "queue_length": len(PLAY_QUEUE)})
            return

        # -- Queue: clear all and stop -------------------------------------
        if self.path == "/tidal/queue/clear":
            _invalidate_tidal_stream_resolution("queue-clear")
            _disarm_queue_auto_advance("queue-clear")
            try:
                APP_INSTANCE.player.stop()
                _schedule_idle_release(1)
            except Exception:
                pass
            _reset_idle_playback_context()
            with _QUEUE_LOCK:
                PLAY_QUEUE.clear()
                ORIGINAL_QUEUE.clear()
                PLAY_QUEUE_META_CACHE.clear()
                QUEUE_INDEX = 0
            save_queue()
            self._send_json({"result": "ok"})
            return

        # -- DAC: manual force-release -----------------------------------------
        # Stops playback immediately and releases the hw:0,0 exclusive handle
        # so Audirvana / Squeezelite can take over. Use as a failsafe when the
        # automatic idle-release does not fire (especially on Pi 5 with alsa_mmap).
        if self.path == "/tidal/dac/release":
            _invalidate_tidal_stream_resolution("dac-release")
            _disarm_queue_auto_advance("dac-release")
            try:
                APP_INSTANCE.player.stop()
            except Exception as e:
                logger.debug("DAC release: player.stop() error: %s", e)
            # Immediately clear exclusive-mode flags then park on ALSA default.
            # Mirrors _schedule_idle_release() but fires right now with no delay.
            try:
                player = APP_INSTANCE.player
                player.exclusive_lock_mode = False
                player.bit_perfect_mode    = False
                player.active_rate_switch  = False
                def _do_release_now():
                    try:
                        release_driver = "ALSA" if ALSA_DRIVER == "alsa_mmap" else ALSA_DRIVER
                        player.set_output(release_driver, "default")
                        logger.info("DAC force-released by user")
                    except Exception as e:
                        logger.warning("DAC force-release set_output failed: %s", e)
                    return False
                GLib.idle_add(_do_release_now)
            except Exception as e:
                logger.warning("DAC force-release failed: %s", e)
                self._send_json({"error": str(e)})
                return
            _cancel_idle_release()
            cancel_scrobble()
            self._send_json({"result": "released"})
            return

        # -- DAC: manual exclusive-mode grab -----------------------------------
        # Re-runs configure_audio() to claim hw:0,0 in bit-perfect exclusive mode.
        # Use on Pi 5 cold boot when the automatic ALSA probe did not result in a
        # working bit-perfect output. Does NOT start playback -- press Play after.
        if self.path == "/tidal/dac/exclusive":
            _cancel_idle_release()
            def _grab():
                configure_audio()
                return False
            GLib.idle_add(_grab)
            logger.info("DAC exclusive mode requested by user")
            self._send_json({"result": "ok"})
            return

        if self.path.startswith("/tidal/play/"):
            track_id = str(self.path.split("/")[-1])
            _invalidate_tidal_stream_resolution("direct-tidal-selection")
            if not _online_state_payload(force=True).get("online"):
                self._send_json(_offline_online_source_payload(), no_store=True)
                return
            try:
                _require_audio_output_for_playback("Tidal playback")
            except AudioOutputUnavailable as e:
                self._send_json(e.to_payload())
                return
            if RADIO_MODE:
                _cancel_pending_radio_start()
                _METADATA_REGISTRY.detach()
                _set_radio_switching_guard()
                CURRENT_RADIO_METADATA = {}
                _set_current_radio_artwork({})
                RADIO_MODE    = False
                CURRENT_RADIO = None
                _set_player_live_radio_mode(enabled=False)
            with _QUEUE_LOCK:
                _queue_ensure_canonical_locked()
                if track_id in PLAY_QUEUE:
                    index = PLAY_QUEUE.index(track_id)
                else:
                    PLAY_QUEUE.clear()
                    ORIGINAL_QUEUE.clear()
                    PLAY_QUEUE.append(track_id)
                    ORIGINAL_QUEUE.append(track_id)
                    index = 0
            GLib.idle_add(lambda: play_queue_index(index))
            self._send_json({"result": "playing", "track": track_id})
            return

        # -- Session state (for multi-device sync) ------------------------
        if static_path == "/session":
            player   = APP_INSTANCE.player
            playback_context = _status_playback_context(player)
            context_for_session = playback_context.get("context") or {}
            # Calculate position from wall-clock time -- reliable across sleep/wake
            position = 0
            try:
                is_session_cue, cue_start_for_session, _cue_duration, cue_track_index_for_session, cue_track_id_for_session = _playback_context_cue_details(playback_context)
                if player.is_playing() and playback_context.get("current_track_valid"):
                    if is_session_cue:
                        raw_session_position = int(_player_position_seconds(player))
                        position = int(_playback_display_position(raw_session_position, playback_context, position_is_raw=True))
                    elif PLAYBACK_START_TIME:
                        raw_session_position = int(time.time() - PLAYBACK_START_TIME)
                        position = int(_playback_display_position(raw_session_position, playback_context, position_is_raw=True))
                    else:
                        raw_session_position = int(_player_position_seconds(player))
                        position = int(_playback_display_position(raw_session_position, playback_context, position_is_raw=True))
                elif playback_context.get("current_track_valid"):
                    position = int(_playback_display_position(
                        _resume_position_for_track(playback_context.get("current_track_id")),
                        playback_context,
                        position_is_raw=False,
                    ))
            except Exception:
                position = 0
            radio_artwork = _get_current_radio_artwork()
            self._send_json({
                "playing":       player.is_playing(),
                "playback_state": playback_context.get("playback_state"),
                "current_track_valid": bool(playback_context.get("current_track_valid")),
                "position":      position,
                "track_id":      playback_context.get("current_track_id"),
                "source":        playback_context.get("source"),
                "title":         context_for_session.get("title"),
                "artist":        context_for_session.get("artist"),
                "artist_id":     context_for_session.get("artist_id"),
                "album":         context_for_session.get("album"),
                "album_id":      context_for_session.get("album_id"),
                "cover":         context_for_session.get("cover"),
                "duration":      context_for_session.get("duration", 0),
                "context_title": context_for_session.get("context_title"),
                "context_type":  context_for_session.get("context_type"),
                "context_id":    context_for_session.get("context_id"),
                "queue_length":  len(PLAY_QUEUE),
                "queue_index":   QUEUE_INDEX,
                "repeat":        REPEAT_MODE,
                "shuffle":       SHUFFLE_ON,
                "sample_rate":   CURRENT_STREAM_INFO["sample_rate"],
                "bit_depth":     CURRENT_STREAM_INFO["bit_depth"],
                "codec":         CURRENT_STREAM_INFO["codec"],
                "radio_mode":    RADIO_MODE,
                "radio_station": CURRENT_RADIO,
                "radio_metadata": CURRENT_RADIO_METADATA,
                "radio_cover_art_url": radio_artwork.get("url", ""),
                "radio_cover_art_source": radio_artwork.get("source", "")
            })
            return

        # -- Playback controls ---------------------------------------------
        if self.path == "/tidal/pause":
            self._send_json(_tidal_pause_payload())
            return

        if self.path == "/tidal/resume":
            self._send_json(_tidal_resume_payload())
            return

        if self.path == "/tidal/next":
            self._send_json(_tidal_next_payload())
            return

        if self.path == "/tidal/prev":
            self._send_json(_tidal_prev_payload())
            return

        if self.path == "/tidal/repeat":
            if   REPEAT_MODE == "off": REPEAT_MODE = "all"
            elif REPEAT_MODE == "all": REPEAT_MODE = "one"
            else:                      REPEAT_MODE = "off"
            logger.info("Repeat mode: %s", REPEAT_MODE)
            save_queue()
            self._send_json({"repeat": REPEAT_MODE})
            return

        if self.path == "/tidal/shuffle":
            try:
                shuffle_active_playback = bool(APP_INSTANCE.player.is_playing())
            except Exception:
                shuffle_active_playback = False
            with _QUEUE_LOCK:
                identity = _queue_current_identity_locked()
                SHUFFLE_ON = not SHUFFLE_ON
                logger.info("Shuffle: %s", SHUFFLE_ON)
                if SHUFFLE_ON:
                    if shuffle_active_playback:
                        _queue_shuffle_future_after_current_locked(identity)
                    else:
                        _queue_shuffle_from_canonical_locked(identity)
                else:
                    _queue_restore_canonical_locked(
                        identity,
                        keep_current_boundary=shuffle_active_playback,
                    )
            save_queue()
            self._send_json({
                "shuffle": SHUFFLE_ON,
                "queue_index": QUEUE_INDEX,
                "queue_length": len(PLAY_QUEUE),
                "active_playback": shuffle_active_playback,
            })
            return

        if self.path.startswith("/tidal/seek/"):
            pos_str = self.path.split("/")[-1]
            try:
                position = float(pos_str)
                self._send_json(_tidal_seek_payload(position))
            except Exception as e:
                logger.warning("Seek failed: %s", e)
                self._send_json({"ok": False, "error": str(e)})
            return

        # -- Favorites: current in-memory ID sets ----------------------------
        # Returns all favorited IDs instantly from memory (no Tidal API call).
        if self.path == "/tidal/favorites/ids":
            backend = APP_INSTANCE.backend
            self._send_json({
                "track_ids":  list(backend.fav_track_ids),
                "album_ids":  list(backend.fav_album_ids),
                "artist_ids": list(backend.fav_artist_ids)
            })
            return

        # -- Favorites: toggle track ----------------------------------------
        if self.path.startswith("/tidal/favorite/track/"):
            item_id = self.path.split("/")[-1]
            backend  = APP_INSTANCE.backend
            new_state = not backend.is_track_favorite(item_id)
            # Optimistic: update in-memory set immediately
            if new_state:
                backend.fav_track_ids.add(str(item_id))
            else:
                backend.fav_track_ids.discard(str(item_id))
            def _bg_track():
                ok = backend.toggle_track_favorite(item_id, add=new_state)
                if not ok:
                    if new_state: backend.fav_track_ids.discard(str(item_id))
                    else:         backend.fav_track_ids.add(str(item_id))
                else:
                    cache_invalidate("mysongs")
            threading.Thread(target=_bg_track, daemon=True).start()
            self._send_json({"is_favorite": new_state, "id": item_id})
            return

        # -- Favorites: toggle album ----------------------------------------
        if self.path.startswith("/tidal/favorite/album/"):
            item_id   = self.path.split("/")[-1]
            backend   = APP_INSTANCE.backend
            new_state = not backend.is_favorite(item_id)
            if new_state:
                backend.fav_album_ids.add(str(item_id))
            else:
                backend.fav_album_ids.discard(str(item_id))
            def _bg_album():
                ok = backend.toggle_album_favorite(item_id, add=new_state)
                if not ok:
                    if new_state: backend.fav_album_ids.discard(str(item_id))
                    else:         backend.fav_album_ids.add(str(item_id))
                else:
                    cache_invalidate("myalbums")
            threading.Thread(target=_bg_album, daemon=True).start()
            self._send_json({"is_favorite": new_state, "id": item_id})
            return

        # -- Favorites: toggle artist ---------------------------------------
        if self.path.startswith("/tidal/favorite/artist/"):
            item_id   = self.path.split("/")[-1]
            backend   = APP_INSTANCE.backend
            new_state = not backend.is_artist_favorite(item_id)
            if new_state:
                backend.fav_artist_ids.add(str(item_id))
            else:
                backend.fav_artist_ids.discard(str(item_id))
            def _bg_artist():
                ok = backend.toggle_artist_favorite(item_id, add=new_state)
                if not ok:
                    if new_state: backend.fav_artist_ids.discard(str(item_id))
                    else:         backend.fav_artist_ids.add(str(item_id))
            threading.Thread(target=_bg_artist, daemon=True).start()
            self._send_json({"is_favorite": new_state, "id": item_id})
            return

        # -- Rich metadata for currently playing track ----------------------
        # Returns merged Last.fm + TheAudioDB data.
        # Served from in-memory cache if fresh; fetches in background otherwise.
        if self.path == "/meta/now":
            if RADIO_MODE or str(CURRENT_CONTEXT.get("context_type") or "").lower() == "radio":
                radio_track = build_current_scrobble_track("radio")
                if not radio_track:
                    self._send_json({"error": "radio_metadata_unavailable"})
                    return
                track_id = radio_track.get("id")
                artist   = (radio_track.get("artist") or "").strip()
                title    = (radio_track.get("title")  or "").strip()
            else:
                track_id = CURRENT_CONTEXT.get("track_id")
                artist   = (CURRENT_CONTEXT.get("artist") or "").strip()
                title    = (CURRENT_CONTEXT.get("title")  or "").strip()

            if not track_id or not artist:
                self._send_json({"error": "nothing playing"})
                return
            cache_key = str(track_id)
            with _META_CACHE_LOCK:
                entry = _META_CACHE.get(cache_key)
            if entry and (time.time() - entry.get("ts", 0)) < TTL_META:
                logger.debug("Meta cache HIT: %s", cache_key)
                self._send_json(entry["data"])
                return
            logger.info("Meta cache MISS: fetching for %s - %s", artist, title)
            api_key = _SCROBBLE_CREDS.get("lastfm_api_key") or LASTFM_API_KEY
            try:
                data = _fetch_all_meta(track_id, artist, title, api_key)
                with _META_CACHE_LOCK:
                    _META_CACHE[cache_key] = {"data": data, "ts": time.time()}
                _save_meta_cache()
                self._send_json(data)
            except Exception as e:
                logger.warning("meta fetch failed: %s", e)
                self._send_json({"error": str(e)})
            return

        # -- Lyrics -------------------------------------------------------
        if static_path.startswith("/api/local/library/lyrics/"):
            prefix = "/api/local/library/lyrics/"
            track_id = unquote(static_path[len(prefix):])
            self._send_json(_local_library_lyrics_payload(track_id))
            return

        if self.path.startswith("/tidal/lyrics/"):
            track_id = self.path.split("/")[-1]
            backend  = APP_INSTANCE.backend
            try:
                raw = backend.get_lyrics(track_id)
                if not raw:
                    self._send_json({"error": "no_lyrics"})
                    return
                # Detect synced (LRC) vs unsynced by presence of timestamp tags
                if raw.strip().startswith("[") and "]" in raw:
                    lines = []
                    for line in raw.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        # Parse all [mm:ss.xx] timestamps on this line
                        import re as _re
                        tags = _re.findall(r'\[(\d+):(\d+(?:\.\d+)?)\]', line)
                        text = _re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', line).strip()
                        for m, s in tags:
                            ms = int(m) * 60000 + int(float(s) * 1000)
                            lines.append({"ms": ms, "text": text})
                    # Sort by timestamp (some LRC files are out of order)
                    lines.sort(key=lambda x: x["ms"])
                    # Filter out metadata lines (empty text or [xx:xx] only)
                    lines = [l for l in lines if l["text"]]
                    if lines:
                        self._send_json({"synced": True, "lines": lines})
                        return
                # Fall through to unsynced if parsing yielded nothing
                self._send_json({"synced": False, "text": raw.strip()})
            except Exception as e:
                logger.warning("lyrics fetch failed: %s", e)
                self._send_json({"error": str(e)})
            return

        # -- Spectrum / VU meter data -------------------------------------
        if self.path == "/spectrum":
            with _SPECTRUM_LOCK:
                data = dict(_SPECTRUM_STATE)
            # Decay to silence if no frame received in last 2s (paused/stopped)
            age = time.time() - data["ts"]
            if age > 2.0:
                decay = max(0.0, 1.0 - (age - 2.0) / 3.0)
                for k in ("left_rms", "right_rms", "left_peak", "right_peak"):
                    data[k] = -70.0 + (data[k] + 70.0) * decay
            self._send_json(data)
            return

        # -- Scrobble: status ------------------------------------------------
        if static_path == "/scrobble/status":
            self._send_json({
                "lastfm_connected": _SCROBBLE_CREDS.get("lastfm_connected", False),
                "lastfm_username":  _SCROBBLE_CREDS.get("lastfm_username",  ""),
                "lbz_connected":    _SCROBBLE_CREDS.get("lbz_connected",    False),
                "lbz_username":     _SCROBBLE_CREDS.get("lbz_username",     ""),
                "tidal_username":   _tidal_account_display_name(),
                "tidal_infinite_play_enabled": _tidal_infinite_play_enabled(),
                "tidal_infinite_play_mode": _tidal_infinite_play_mode()
            }, no_store=True)
            return

        # -- Scrobble: disconnect Last.fm ------------------------------------
        if self.path == "/scrobble/lastfm/disconnect":
            _SCROBBLE_CREDS["lastfm_session_key"] = ""
            _SCROBBLE_CREDS["lastfm_username"]    = ""
            _SCROBBLE_CREDS["lastfm_connected"]   = False
            _save_scrobble_creds()
            self._send_json({"result": "ok"})
            return

        # -- Scrobble: disconnect ListenBrainz ------------------------------
        if self.path == "/scrobble/lbz/disconnect":
            _SCROBBLE_CREDS["lbz_token"]     = ""
            _SCROBBLE_CREDS["lbz_username"]  = ""
            _SCROBBLE_CREDS["lbz_connected"] = False
            _save_scrobble_creds()
            self._send_json({"result": "ok"})
            return

        # -- Auto-Mix: artist search (Last.fm autocomplete) ------------------
        if self.path.startswith("/api/automix/search"):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            query  = params.get("q", [""])[0].strip()
            if not query:
                self._send_json([])
                return
            api_key = _SCROBBLE_CREDS.get("lastfm_api_key") or LASTFM_API_KEY
            try:
                url = (LASTFM_API_URL +
                       "?method=artist.search"
                       "&artist=" + urllib.parse.quote(query) +
                       "&api_key=" + urllib.parse.quote(api_key) +
                       "&format=json"
                       "&limit=10")
                data    = _meta_http_get(url)
                matches = ((data.get("results", {})
                               .get("artistmatches", {})
                               .get("artist")) or [])
                names   = [a["name"] for a in matches if a.get("name")]
                self._send_json(names)
            except Exception as e:
                logger.warning("automix search failed: %s", e)
                self._send_json([])
            return

        if self.path == "/api/radio/stations":
            with _RADIO_LOCK:
                stations = _load_radio_stations()
            self._send_json({"stations": stations})
            return

        self.send_error(404)


    def do_POST(self):

        global APP_INSTANCE, PLAY_QUEUE, QUEUE_INDEX, ORIGINAL_QUEUE, PLAY_QUEUE_PENDING_AFTER_CONTEXT
        global SHUFFLE_ON, PLAY_QUEUE_META_CACHE, RADIO_MODE, CURRENT_RADIO, CURRENT_RADIO_METADATA

        # -- Radio routes (no request body) ----------------------------------
        if self.path.startswith("/api/radio/play/"):
            station_id = self.path.split("/")[-1]
            logger.debug("radio/play handler: path=%s id=%s", self.path, station_id)
            with _RADIO_LOCK:
                stations = _load_radio_stations()
            match = None
            for _s in stations:
                if _s.get("id") == station_id:
                    match = _s
                    break
            if match is None:
                logger.warning("radio/play: station id not found: %s", station_id)
                self._send_json({"error": "station not found", "id": station_id})
                return
            _st = dict(match)
            available, reason = _radio_stream_available(_st)
            if not available:
                logger.warning("radio/play: invalid stream URL for %s: %s", station_id, reason)
                self._send_json({
                    "ok": False,
                    "offline": False,
                    "error": reason or "Radio stream URL is invalid.",
                    "detail": reason,
                })
                return
            online_state = _online_state_payload(force=True)
            if online_state.get("online") is False and str(online_state.get("confidence") or "") == "all_failed":
                self._send_json(_offline_online_source_payload(), no_store=True)
                return
            logger.info(
                "Radio play: skipping Range preflight for live stream station=%s url=%s",
                _st.get("name", ""),
                _st.get("url", ""),
            )
            with _QUEUE_LOCK:
                PLAY_QUEUE.clear()
                ORIGINAL_QUEUE.clear()
                PLAY_QUEUE_META_CACHE.clear()
                QUEUE_INDEX = 0
                radio_payload = _radio_queue_payload_from_station(_st)
                radio_tid = str(radio_payload.get("id") or "").strip()
                if radio_tid:
                    PLAY_QUEUE.append(radio_tid)
                    ORIGINAL_QUEUE.append(radio_tid)
                    PLAY_QUEUE_META_CACHE[radio_tid] = radio_payload
            save_queue()
            self._send_json(_request_radio_station_start(_st, reason="radio playback"))
            return

        if self.path == "/api/radio/stop":
            _invalidate_tidal_stream_resolution("radio-stop")
            GLib.idle_add(lambda: (stop_radio(), False)[1])
            self._send_json({"ok": True})
            return

        if self.path == "/api/radio/standby":
            _invalidate_tidal_stream_resolution("radio-standby")
            self._send_json(_radio_standby_payload())
            return

        # -- Playback controls, POST-compatible for clients using commands ---
        if self.path == "/tidal/pause":
            self._send_json(_tidal_pause_payload())
            return

        if self.path == "/tidal/resume":
            self._send_json(_tidal_resume_payload())
            return

        if self.path == "/tidal/next":
            self._send_json(_tidal_next_payload())
            return

        if self.path == "/tidal/prev":
            self._send_json(_tidal_prev_payload())
            return

        # -- Local library scanner/index ------------------------------------
        if self.path == "/api/local/library/scan":
            self._send_json(_local_library_scan_payload())
            return

        if self.path == "/api/local/library/rebuild":
            self._send_json(_local_library_rebuild_payload())
            return

        if self.path == "/api/local/library/cleanup-stale":
            self._send_json(_local_library_cleanup_stale_payload())
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body    = self.rfile.read(length)
            payload = json.loads(body)
        except Exception:
            self.send_error(400)
            return


        # -- Network / Remote Access ---------------------------------------
        if self.path == "/api/settings/web-port":
            global _SROVA_RESTART_REQUIRED, _SROVA_PENDING_PORT
            try:
                new_lan_address, new_port = _write_srova_remote_target(payload.get("lan_address"), payload.get("port"))
                _SROVA_RESTART_REQUIRED = (new_port != int(HTTP_PORT))
                _SROVA_PENDING_PORT = new_port
                data = _network_payload(port=new_port, restart_required=_SROVA_RESTART_REQUIRED)
                data.update({
                    "ok": True,
                    "lan_address": new_lan_address,
                    "message": "Target saved. Restart SROVA for the new port to take effect."
                               if _SROVA_RESTART_REQUIRED else
                               "Target saved. SROVA is already using this port."
                })
                self._send_json(data)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)})
            return

        if self.path == "/api/local/library/roots":
            try:
                self._send_json(_local_library_roots_payload(payload))
            except Exception as e:
                self._send_json({"ok": False, "error": str(e), "roots": _local_test_roots()})
            return

        if self.path == "/api/local/library/network/shares":
            self._send_json(_network_music_shares_payload(payload), no_store=True)
            return

        if self.path == "/api/local/library/network/connect":
            self._send_json(_network_music_connect_payload(payload), no_store=True)
            return

        if self.path == "/api/local/library/network/disconnect":
            self._send_json(_network_music_disconnect_payload(payload), no_store=True)
            return

        if self.path == "/api/system/restart":
            target_port = _SROVA_PENDING_PORT or _load_srova_env_port() or HTTP_PORT
            data = _network_payload(port=target_port, restart_required=True)
            data.update({"ok": True, "message": "Restarting SROVA."})
            self._send_json(data)
            _restart_srova_service_later()
            return

        # -- Audio output / DAC preference -------------------------------
        if self.path == "/api/audio/output":
            try:
                locked = _audio_output_locked_state()
                if locked.get("dac_locked"):
                    self._send_json({"error": "DAC is locked. Release DAC before changing output."})
                    return
                driver = payload.get("alsa_driver", payload.get("driver", ALSA_DRIVER))
                device = payload.get("alsa_device", payload.get("device", ALSA_DEVICE))
                name = payload.get("dac_name", payload.get("name", ""))
                self._send_json(_set_audio_output_preference(driver, device, name))
            except Exception as e:
                self._send_json({"error": str(e)})
            return

        if self.path == "/api/settings/tidal-infinite-play":
            enabled = bool(payload.get("enabled")) if "enabled" in payload else None
            mode = payload.get("mode") if "mode" in payload else None
            state = _set_tidal_infinite_play_settings(enabled=enabled, mode=mode)
            logger.info(
                "TIDAL Infinite Play setting: %s mode=%s",
                "enabled" if state["enabled"] else "disabled",
                state["mode"],
            )
            self._send_json({"ok": True, "enabled": state["enabled"], "mode": state["mode"]}, no_store=True)
            return

        # -- Local library indexed playback ---------------------------------
        if self.path == "/api/local/library/play":
            self._send_json(_local_library_play_payload(payload))
            return

        # -- Temporary local playback proof ---------------------------------
        # Test-only endpoint: allowlisted single-file playback through the
        # existing Rust/GStreamer/ALSA player. Does not touch TIDAL queue state.
        if self.path == "/api/local/test-play":
            try:
                real_path = _validate_local_test_file(payload.get("path"))
                file_uri = _local_test_file_uri(real_path)
                _require_audio_output_for_playback("local test playback")
                _invalidate_tidal_stream_resolution("local-test-playback")
                GLib.idle_add(lambda: play_local_test_file(real_path, file_uri))
                self._send_json({
                    "ok": True,
                    "source": "local",
                    "path": real_path,
                    "uri": file_uri,
                    "message": "local test playback scheduled"
                })
            except PermissionError as e:
                self._send_json({"ok": False, "error": str(e)})
            except AudioOutputUnavailable as e:
                payload = e.to_payload()
                payload["source"] = "local"
                self._send_json(payload)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)})
            return

        # -- Queue: replace entirely and start playback --------------------
        # Body: {tracks: [{id,title,artist,cover,duration,quality},...], start_index: N}
        if self.path == "/tidal/queue/replace":
            tracks    = payload.get("tracks", [])
            if not _all_tracks_are_local(tracks) and not _online_state_payload(force=True).get("online"):
                self._send_json(_offline_online_source_payload(), no_store=True)
                return
            if tracks:
                try:
                    _require_audio_output_for_playback("queue replace playback")
                except AudioOutputUnavailable as e:
                    self._send_json(e.to_payload())
                    return
            if RADIO_MODE:
                _cancel_pending_radio_start()
                _METADATA_REGISTRY.detach()
                _set_radio_switching_guard()
                CURRENT_RADIO_METADATA = {}
                _set_current_radio_artwork({})
                RADIO_MODE    = False
                CURRENT_RADIO = None
                _set_player_live_radio_mode(enabled=False)
            if local_library_rebuild_running() and any(
                str((t or {}).get("source") or "").lower() == "local" or str((t or {}).get("id") or "").startswith("local:")
                for t in tracks if isinstance(t, dict)
            ):
                self._send_json(_local_library_maintenance_busy_payload({"source": "local"}))
                return
            start_idx = int(payload.get("start_index", 0))
            ctx_type  = str(payload.get("context_type",  "") or "").strip()
            ctx_id    = str(payload.get("context_id",    "") or "").strip()
            ctx_title = str(payload.get("context_title", "") or "").strip()
            _invalidate_tidal_stream_resolution("queue-replace")
            with _QUEUE_LOCK:
                PLAY_QUEUE.clear()
                ORIGINAL_QUEUE.clear()
                PLAY_QUEUE_META_CACHE.clear()
                for t in tracks:
                    tid = str(t.get("id", "")).strip()
                    if tid:
                        PLAY_QUEUE.append(tid)
                        PLAY_QUEUE_META_CACHE[tid] = t
                ORIGINAL_QUEUE.extend(PLAY_QUEUE)
                if PLAY_QUEUE:
                    _queue_prune_after_first_radio_locked("replace")
                    QUEUE_INDEX = max(0, min(start_idx, len(PLAY_QUEUE) - 1))
                    if SHUFFLE_ON:
                        _queue_shuffle_future_after_current_locked(_queue_current_identity_locked())
                        _queue_prune_after_first_radio_locked("replace-shuffle")
                else:
                    QUEUE_INDEX = 0
            if ctx_type:
                CURRENT_CONTEXT["context_type"]  = ctx_type
                CURRENT_CONTEXT["context_id"]    = ctx_id or None
                CURRENT_CONTEXT["context_title"] = ctx_title or None
            save_queue()
            idx = QUEUE_INDEX
            GLib.idle_add(lambda: play_queue_index(idx))
            self._send_json({"result": "ok", "queue_length": len(PLAY_QUEUE)})
            return

        # -- Queue: append tracks to end -----------------------------------
        # Body: {tracks: [{id,title,artist,cover,duration,quality},...]}
        if self.path == "/tidal/queue/append":
            tracks = payload.get("tracks", [])
            if RADIO_MODE or _queue_current_item_is_radio():
                self._send_json(_radio_queue_block_payload(), no_store=True)
                return
            if not _all_tracks_are_local(tracks) and not _online_state_payload(force=True).get("online"):
                self._send_json(_offline_online_source_payload(), no_store=True)
                return
            if local_library_rebuild_running() and any(
                str((t or {}).get("source") or "").lower() == "local" or str((t or {}).get("id") or "").startswith("local:")
                for t in tracks if isinstance(t, dict)
            ):
                self._send_json(_local_library_maintenance_busy_payload({"source": "local"}))
                return
            with _QUEUE_LOCK:
                _queue_ensure_canonical_locked()
                _trim_future_local_cue_album_queue_locked("append")
                for t in tracks:
                    tid = str(t.get("id", "")).strip()
                    if tid:
                        PLAY_QUEUE.append(tid)
                        ORIGINAL_QUEUE.append(tid)
                        PLAY_QUEUE_META_CACHE[tid] = t
                _queue_prune_after_first_radio_locked("append")
            save_queue()
            self._send_json({"result": "ok", "queue_length": len(PLAY_QUEUE)})
            return

        # -- Queue: insert tracks immediately after current track -----------
        # Body: {tracks: [{id,title,artist,cover,duration,quality},...]}
        if self.path == "/tidal/queue/insert_next":
            tracks = payload.get("tracks", [])
            if RADIO_MODE or _queue_current_item_is_radio():
                self._send_json(_radio_queue_block_payload(), no_store=True)
                return
            if not _all_tracks_are_local(tracks) and not _online_state_payload(force=True).get("online"):
                self._send_json(_offline_online_source_payload(), no_store=True)
                return
            if local_library_rebuild_running() and any(
                str((t or {}).get("source") or "").lower() == "local" or str((t or {}).get("id") or "").startswith("local:")
                for t in tracks if isinstance(t, dict)
            ):
                self._send_json(_local_library_maintenance_busy_payload({"source": "local"}))
                return
            with _QUEUE_LOCK:
                _queue_ensure_canonical_locked()
                identity = _queue_current_identity_locked()
                if _active_local_cue_album_context():
                    _trim_future_local_cue_album_queue_locked("insert_next")
                    insert_at = max(0, min(QUEUE_INDEX + 1, len(PLAY_QUEUE)))
                    PLAY_QUEUE_PENDING_AFTER_CONTEXT = True
                elif _is_local_album_playback_context():
                    insert_at = max(0, min(QUEUE_INDEX + 1, len(PLAY_QUEUE)))
                    PLAY_QUEUE_PENDING_AFTER_CONTEXT = True
                else:
                    insert_at = QUEUE_INDEX + 1
                original_insert_at = len(ORIGINAL_QUEUE)
                if ORIGINAL_QUEUE and identity:
                    original_insert_at = _queue_find_identity_index_locked(ORIGINAL_QUEUE, identity) + 1
                for i, t in enumerate(tracks):
                    tid = str(t.get("id", "")).strip()
                    if tid:
                        PLAY_QUEUE.insert(insert_at + i, tid)
                        ORIGINAL_QUEUE.insert(original_insert_at + i, tid)
                        PLAY_QUEUE_META_CACHE[tid] = t
                _queue_prune_after_first_radio_locked("insert_next")
            save_queue()
            self._send_json({"result": "ok", "queue_length": len(PLAY_QUEUE)})
            return

        if self.path == "/api/tidal/infinite-play/refill":
            if not _tidal_infinite_play_enabled():
                self._send_json({"ok": False, "error": "Infinite Play is disabled"}, no_store=True)
                return
            if RADIO_MODE:
                logger.info("Infinite Play refill skipped: radio mode active")
                self._send_json({"ok": False, "error": "radio mode active"}, no_store=True)
                return
            try:
                limit = int(payload.get("limit", 10) or 10)
            except Exception:
                limit = 10
            limit = max(1, min(limit, 25))
            mode = _normalise_tidal_infinite_play_mode(payload.get("mode") or _tidal_infinite_play_mode())
            seed_id = str(payload.get("seed_id", payload.get("seed_track_id", "")) or "").strip()
            with _QUEUE_LOCK:
                if not PLAY_QUEUE or not (0 <= QUEUE_INDEX < len(PLAY_QUEUE)):
                    self._send_json({"ok": False, "error": "no active queue"}, no_store=True)
                    return
                active_id = str(PLAY_QUEUE[QUEUE_INDEX])
                active_meta = PLAY_QUEUE_META_CACHE.get(active_id, {}) or {}
                active_source = str(active_meta.get("source") or "").lower()
                if active_id.startswith("local:") or active_source == "local":
                    logger.info("Infinite Play refill skipped: active queue item is local")
                    self._send_json({"ok": False, "error": "active track is not TIDAL"}, no_store=True)
                    return
                if QUEUE_INDEX < len(PLAY_QUEUE) - 1:
                    self._send_json({"ok": False, "error": "queue is not at tail"}, no_store=True)
                    return
                if seed_id and seed_id != active_id:
                    logger.info("Infinite Play refill seed mismatch: requested=%s active=%s", seed_id, active_id)
                seed_id = active_id
            result = _append_infinite_play_recommendations(seed_id=seed_id, limit=limit, autoplay=False, mode=mode)
            self._send_json(result, no_store=True)
            return

        # -- Queue: save current queue as a new Tidal playlist ---------------
        # Body: {name: "My Playlist"}
        if self.path == "/tidal/playlist/create_from_queue":
            name = payload.get("name", "").strip()
            if not name:
                self._send_json({"error": "name required"})
                return
            try:
                user = APP_INSTANCE.backend.session.user
                pl   = user.create_playlist(name, "Created by SROVA")
                ids  = [int(tid) for tid in PLAY_QUEUE if tid]
                if ids:
                    pl.add(ids)
                logger.info("Playlist created: %s (%d tracks)", name, len(ids))
                self._send_json({"result": "ok", "name": name, "id": str(pl.id)})
            except Exception as e:
                logger.warning("create_playlist failed: %s", e)
                self._send_json({"error": str(e)})
            return

        # -- Playlist: create empty TIDAL playlist ---------------------------
        # Body: {name: "My Playlist", description: "..."}
        if self.path == "/tidal/playlist/create":
            name = str(payload.get("name", "") or "").strip()
            description = str(payload.get("description", "") or "")
            if not name:
                self._send_json({"ok": False, "error": "playlist name required"}, no_store=True)
                return
            try:
                backend = APP_INSTANCE.backend
                if not backend or not getattr(backend, "session", None) or not getattr(backend.session, "user", None):
                    self._send_json({"ok": False, "error": "TIDAL is not logged in"}, no_store=True)
                    return
                pl = backend.create_cloud_playlist(name, description)
                if not pl:
                    self._send_json({"ok": False, "error": "TIDAL playlist creation failed"}, no_store=True)
                    return
                pid = str(getattr(pl, "id", "") or "")
                pname = str(getattr(pl, "name", "") or name)
                cache_invalidate("myplaylists")
                self._send_json({
                    "ok": True,
                    "playlist": {"id": pid, "name": pname},
                    "id": pid,
                    "name": pname
                }, no_store=True)
            except Exception as e:
                logger.warning("playlist/create failed: %s", e)
                self._send_json({"ok": False, "error": str(e)}, no_store=True)
            return

        # -- Playlist: add explicit tracks to existing TIDAL playlist --------
        # Body: {playlist_id: "...", track_ids: ["123", "456", ...]}
        if self.path == "/tidal/playlist/add_tracks":
            playlist_id = str(payload.get("playlist_id", "") or "").strip()
            raw_track_ids = payload.get("track_ids", [])
            if not playlist_id:
                self._send_json({"ok": False, "error": "playlist id required"}, no_store=True)
                return
            if not isinstance(raw_track_ids, list):
                raw_track_ids = [raw_track_ids]
            track_ids = [str(tid).strip() for tid in raw_track_ids if str(tid or "").strip()]
            if not track_ids:
                self._send_json({"ok": False, "error": "no valid TIDAL track ids"}, no_store=True)
                return
            try:
                backend = APP_INSTANCE.backend
                if not backend or not getattr(backend, "session", None) or not getattr(backend.session, "user", None):
                    self._send_json({"ok": False, "error": "TIDAL is not logged in"}, no_store=True)
                    return
                result = backend.add_tracks_to_cloud_playlist(playlist_id, track_ids, dedupe=True, batch_size=100)
                if not result or not result.get("ok"):
                    error = (result or {}).get("error") or "TIDAL add to playlist failed"
                    logger.warning(
                        "playlist/add_tracks helper failed: playlist_id=%s requested=%d error=%s",
                        playlist_id,
                        len(track_ids),
                        error
                    )
                    self._send_json({"ok": False, "error": error}, no_store=True)
                    return
                cache_invalidate("myplaylists")
                cache_invalidate("playlist:" + playlist_id)
                added = int(result.get("added") or 0)
                self._send_json({
                    "ok": True,
                    "playlist_id": str(result.get("playlist_id") or playlist_id),
                    "requested": int(result.get("requested") or len(track_ids)),
                    "items_added": added,
                    "added": added,
                    "skipped_invalid": int(result.get("skipped_invalid") or 0)
                }, no_store=True)
            except Exception as e:
                logger.warning("playlist/add_tracks failed: %s", e)
                self._send_json({"ok": False, "error": str(e)}, no_store=True)
            return

        # -- Playlist: remove explicit tracks from existing TIDAL playlist ---
        # Body: {playlist_id: "...", track_ids: ["123", "456", ...]}
        if self.path == "/tidal/playlist/remove_tracks":
            playlist_id = str(payload.get("playlist_id", "") or "").strip()
            raw_track_ids = payload.get("track_ids", [])
            if not playlist_id:
                self._send_json({"ok": False, "error": "playlist id required"}, no_store=True)
                return
            if not isinstance(raw_track_ids, list):
                raw_track_ids = [raw_track_ids]
            track_ids = [str(tid).strip() for tid in raw_track_ids if str(tid or "").strip()]
            if not track_ids:
                self._send_json({"ok": False, "error": "no valid TIDAL track ids"}, no_store=True)
                return
            try:
                backend = APP_INSTANCE.backend
                if not backend or not getattr(backend, "session", None) or not getattr(backend.session, "user", None):
                    self._send_json({"ok": False, "error": "TIDAL is not logged in"}, no_store=True)
                    return
                result = backend.remove_tracks_from_cloud_playlist(playlist_id, track_ids)
                if not result or not result.get("ok"):
                    error = (result or {}).get("error") or "TIDAL remove from playlist failed"
                    logger.warning(
                        "playlist/remove_tracks helper failed: playlist_id=%s requested=%d error=%s",
                        playlist_id,
                        len(track_ids),
                        error
                    )
                    self._send_json({"ok": False, "error": error}, no_store=True)
                    return
                cache_invalidate("myplaylists")
                cache_invalidate("playlist:" + playlist_id)
                removed = int(result.get("removed") or 0)
                self._send_json({
                    "ok": True,
                    "playlist_id": str(result.get("playlist_id") or playlist_id),
                    "requested": int(result.get("requested") or len(track_ids)),
                    "items_removed": removed,
                    "removed": removed,
                    "skipped_invalid": int(result.get("skipped_invalid") or 0)
                }, no_store=True)
            except Exception as e:
                logger.warning("playlist/remove_tracks failed: %s", e)
                self._send_json({"ok": False, "error": str(e)}, no_store=True)
            return

        # -- Playlist: rename one user-owned TIDAL playlist -----------------
        # Body: {playlist_id: "...", name: "..."}
        if self.path == "/tidal/playlist/rename":
            playlist_id = str(payload.get("playlist_id", "") or "").strip()
            name = str(payload.get("name", "") or "").strip()
            if not playlist_id:
                self._send_json(
                    {"ok": False, "error": "playlist id required"},
                    no_store=True,
                )
                return
            if not name:
                self._send_json(
                    {"ok": False, "error": "playlist name required"},
                    no_store=True,
                )
                return
            try:
                backend = APP_INSTANCE.backend
                if (
                    not backend
                    or not getattr(backend, "session", None)
                    or not getattr(backend.session, "user", None)
                ):
                    self._send_json(
                        {"ok": False, "error": "TIDAL is not logged in"},
                        no_store=True,
                    )
                    return
                result = backend.rename_cloud_playlist(playlist_id, name)
                if not result or not result.get("ok"):
                    error = (
                        (result or {}).get("error")
                        or "TIDAL playlist rename failed"
                    )
                    self._send_json(
                        {"ok": False, "error": error},
                        no_store=True,
                    )
                    return
                renamed_name = str(result.get("name") or name)
                cache_invalidate("myplaylists")
                cache_invalidate("playlist:" + playlist_id)
                self._send_json(
                    {
                        "ok": True,
                        "playlist_id": playlist_id,
                        "name": renamed_name,
                    },
                    no_store=True,
                )
            except Exception as e:
                logger.warning("playlist/rename failed: %s", e)
                self._send_json(
                    {"ok": False, "error": str(e)},
                    no_store=True,
                )
            return

        # -- Playlist: delete one TIDAL playlist ----------------------------
        # Body: {playlist_id: "..."}
        if self.path == "/tidal/playlist/delete":
            playlist_id = str(payload.get("playlist_id", "") or "").strip()
            if not playlist_id:
                self._send_json({"ok": False, "error": "playlist id required"}, no_store=True)
                return
            try:
                backend = APP_INSTANCE.backend
                if not backend or not getattr(backend, "session", None) or not getattr(backend.session, "user", None):
                    self._send_json({"ok": False, "error": "TIDAL is not logged in"}, no_store=True)
                    return
                result = backend.delete_cloud_playlist(playlist_id)
                # tidalapi may return None from delete() on success. The helper
                # includes playlist_id when resolution reached a playlist.
                if not result or (not result.get("ok") and result.get("playlist_id") is None):
                    self._send_json({"ok": False, "error": "TIDAL playlist delete failed"}, no_store=True)
                    return
                cache_invalidate("myplaylists")
                cache_invalidate("playlist:" + playlist_id)
                self._send_json({"ok": True, "playlist_id": playlist_id}, no_store=True)
            except Exception as e:
                logger.warning("playlist/delete failed: %s", e)
                self._send_json({"ok": False, "error": str(e)}, no_store=True)
            return

        # -- Playlist: create from explicit track list -----------------------
        # Body: {name: "My Playlist", track_ids: ["123", "456", ...]}
        if self.path == "/tidal/playlist/create_from_tracks":
            name      = payload.get("name", "").strip()
            track_ids = payload.get("track_ids", [])
            if not name:
                self._send_json({"error": "name required"})
                return
            try:
                user = APP_INSTANCE.backend.session.user
                pl   = user.create_playlist(name, "Created by SROVA")
                ids  = [int(tid) for tid in track_ids if tid]
                if ids:
                    pl.add(ids)
                logger.info("Playlist created from tracks: %s (%d tracks)", name, len(ids))
                self._send_json({"result": "ok", "name": name, "id": str(pl.id)})
            except Exception as e:
                logger.warning("create_playlist_from_tracks failed: %s", e)
                self._send_json({"error": str(e)})
            return

        # -- Scrobble: connect Last.fm ---------------------------------------
        # Body: {username, password, api_key, api_secret}
        if self.path == "/scrobble/lastfm/connect":
            username   = payload.get("username",   "").strip()
            password   = payload.get("password",   "").strip()
            api_key    = payload.get("api_key",    "").strip()
            api_secret = payload.get("api_secret", "").strip()
            if not all([username, password, api_key, api_secret]):
                self._send_json({"error": "All fields required"})
                return
            def _connect():
                try:
                    sk = lastfm_get_session(username, password, api_key, api_secret)
                    _SCROBBLE_CREDS["lastfm_session_key"] = sk
                    _SCROBBLE_CREDS["lastfm_username"]    = username
                    _SCROBBLE_CREDS["lastfm_api_key"]     = api_key
                    _SCROBBLE_CREDS["lastfm_api_secret"]  = api_secret
                    _SCROBBLE_CREDS["lastfm_connected"]   = True
                    _save_scrobble_creds()
                    logger.info("Last.fm connected: %s", username)
                except Exception as e:
                    logger.warning("Last.fm connect failed: %s", e)
            threading.Thread(target=_connect, daemon=True).start()
            # Respond immediately; UI polls /scrobble/status to confirm
            self._send_json({"result": "connecting"})
            return

        # -- Scrobble: connect ListenBrainz ----------------------------------
        # Body: {token}
        if self.path == "/scrobble/lbz/connect":
            token = payload.get("token", "").strip()
            if not token:
                self._send_json({"error": "Token required"})
                return
            def _connect_lbz():
                try:
                    username = _lbz_validate_token(token)
                    _SCROBBLE_CREDS["lbz_token"]     = token
                    _SCROBBLE_CREDS["lbz_username"]  = username
                    _SCROBBLE_CREDS["lbz_connected"] = True
                    _save_scrobble_creds()
                    logger.info("ListenBrainz connected: %s", username)
                except Exception as e:
                    logger.warning("ListenBrainz connect failed: %s", e)
                    _SCROBBLE_CREDS["lbz_connected"] = False
                    _save_scrobble_creds()
            threading.Thread(target=_connect_lbz, daemon=True).start()
            self._send_json({"result": "connecting"})
            return

        # -- Playlists: delete duplicates ----------------------------------
        # Body: {ids: ["uuid1", "uuid2", ...]}
        if self.path == "/tidal/playlists/delete_duplicates":
            ids     = payload.get("ids", [])
            backend = APP_INSTANCE.backend
            deleted = []
            failed  = []
            for pid in ids:
                try:
                    result = backend.delete_cloud_playlist(pid)
                    # pl.delete() returns None on some tidalapi versions even on success.
                    # Treat None return as success -- no exception means the delete worked.
                    if result.get("ok") or result.get("playlist_id") is not None:
                        deleted.append(pid)
                        logger.info("Deleted duplicate playlist: %s", pid)
                    else:
                        # Retry once directly via session if resolve failed
                        try:
                            pl = backend.session.playlist(pid)
                            if pl and hasattr(pl, "delete"):
                                pl.delete()
                                deleted.append(pid)
                                logger.info("Deleted duplicate playlist (retry): %s", pid)
                            else:
                                failed.append(pid)
                                logger.warning("Failed to delete playlist %s", pid)
                        except Exception as re:
                            failed.append(pid)
                            logger.warning("delete retry failed %s: %s", pid, re)
                    # Small delay to avoid Tidal API rate limiting
                    time.sleep(0.3)
                except Exception as e:
                    failed.append(pid)
                    logger.warning("delete_cloud_playlist error %s: %s", pid, e)
            if deleted:
                cache_invalidate("myplaylists")
            self._send_json({"deleted": deleted, "failed": failed})
            return

        # -- Auto-Mix: create playlist from artist affinity ------------------
        # Body: {artist: "...", depth: "essential"|"balanced"|"deep"}
        if self.path == "/api/automix/create":
            artist = payload.get("artist", "").strip()
            depth  = payload.get("depth", "balanced").lower()
            if not artist:
                self._send_json({"error": "artist required"})
                return
            api_key = _SCROBBLE_CREDS.get("lastfm_api_key") or LASTFM_API_KEY
            backend = APP_INSTANCE.backend

            def _get_similar(artist_name, limit=20):
                try:
                    url = (LASTFM_API_URL +
                           "?method=artist.getSimilar"
                           "&artist=" + urllib.parse.quote(artist_name) +
                           "&api_key=" + urllib.parse.quote(api_key) +
                           "&autocorrect=1"
                           "&format=json"
                           "&limit=" + str(limit))
                    data    = _meta_http_get(url)
                    similar = (data.get("similarartists", {}).get("artist") or [])
                    return [a["name"] for a in similar if a.get("name")][:limit]
                except Exception as e:
                    logger.warning("getSimilar failed for %s: %s", artist_name, e)
                    return []

            if depth == "essential":
                n_tracks     = 2
                artist_names = [artist] + _get_similar(artist, limit=10)
            elif depth == "deep":
                n_tracks     = 3
                first_degree = _get_similar(artist, limit=20)
                all_names    = [artist] + first_degree
                seen         = set(n.lower() for n in all_names)
                for a in first_degree[:5]:
                    for s in _get_similar(a, limit=5):
                        if s.lower() not in seen:
                            all_names.append(s)
                            seen.add(s.lower())
                artist_names = all_names
            else:
                n_tracks     = 3
                artist_names = [artist] + _get_similar(artist, limit=20)

            track_ids = []
            for a_name in artist_names:
                try:
                    matches = backend.search_artist(a_name)
                    if not matches:
                        continue
                    best = None
                    for m in matches:
                        if _safe_str(getattr(m, "name", "")).lower() == a_name.lower():
                            best = m
                            break
                    if best is None:
                        best = matches[0]
                    top = backend.get_artist_top_tracks(best, limit=n_tracks)
                    for t in top[:n_tracks]:
                        tid = str(getattr(t, "id", "")).strip()
                        if tid and tid not in track_ids:
                            track_ids.append(tid)
                except Exception as e:
                    logger.warning("automix track fetch failed for %s: %s", a_name, e)

            if not track_ids:
                self._send_json({"error": "no tracks found"})
                return
            try:
                pl_name = payload.get("playlist_name", "").strip() or ("Auto-Mix: " + artist)
                user    = backend.session.user
                pl      = user.create_playlist(pl_name, "Created by SROVA Auto-Mix")
                ids     = [int(tid) for tid in track_ids if tid]
                if ids:
                    pl.add(ids)
                logger.info("Auto-Mix created: %s (%d tracks)", pl_name, len(ids))
                self._send_json({"playlist_name": pl_name, "track_count": len(ids)})
            except Exception as e:
                logger.warning("automix create_playlist failed: %s", e)
                self._send_json({"error": str(e)})
            return

        if self.path == "/api/radio/stations":
            name = str(payload.get("name", "") or "").strip()
            url  = str(payload.get("url",  "") or "").strip()
            icon = str(payload.get("icon", "") or "").strip()
            if not name or not url:
                self._send_json({"error": "name and url are required"})
                return
            station = {"id": uuid.uuid4().hex, "name": name, "url": url, "icon": icon}
            with _RADIO_LOCK:
                stations = _load_radio_stations()
                stations.append(station)
                _save_radio_stations(stations)
            self._send_json({"station": station})
            return

        self.send_error(404)

    def do_PUT(self):

        global RADIO_MODE, CURRENT_RADIO

        length = int(self.headers.get("Content-Length", 0))
        try:
            body    = self.rfile.read(length)
            payload = json.loads(body)
        except Exception:
            self.send_error(400)
            return

        if self.path == "/api/radio/stations/order":
            try:
                with _RADIO_LOCK:
                    stations = _load_radio_stations()
                    reordered = _reorder_radio_stations(
                        stations, payload.get("station_ids")
                    )
                    _save_radio_stations(reordered)
                self._send_json({"ok": True, "stations": reordered})
            except ValueError as e:
                self._send_json({"ok": False, "error": str(e)})
            except Exception as e:
                logger.warning("radio station reorder failed: %s", e)
                self._send_json({
                    "ok": False,
                    "error": "Could not save Radio station order.",
                })
            return

        if self.path.startswith("/api/radio/stations/"):
            station_id = self.path.split("/")[-1]
            name = str(payload.get("name", "") or "").strip()
            url  = str(payload.get("url",  "") or "").strip()
            icon = str(payload.get("icon", "") or "").strip()
            if not name or not url:
                self._send_json({"error": "name and url are required"})
                return

            updated = None
            with _RADIO_LOCK:
                stations = _load_radio_stations()
                for idx, station in enumerate(stations):
                    if station.get("id") != station_id:
                        continue
                    merged = dict(station)
                    merged.update({"id": station_id, "name": name, "url": url, "icon": icon})
                    stations[idx] = merged
                    updated = merged
                    break
                if updated is None:
                    self.send_error(404)
                    return
                _save_radio_stations(stations)

            if RADIO_MODE and str((CURRENT_RADIO or {}).get("id", "") or "") == station_id:
                current_url = str((CURRENT_RADIO or {}).get("url", "") or "")
                CURRENT_RADIO["name"] = name
                CURRENT_RADIO["icon"] = icon
                if current_url == url:
                    CURRENT_RADIO["url"] = url
                CURRENT_CONTEXT["title"] = name
                CURRENT_CONTEXT["cover"] = icon
                CURRENT_CONTEXT["context_title"] = name

            self._send_json({"station": updated})
            return

        self.send_error(404)


    def do_DELETE(self):

        if self.path.startswith("/api/radio/stations/"):
            station_id = self.path.split("/")[-1]
            with _RADIO_LOCK:
                stations = _load_radio_stations()
                new_stations = [s for s in stations if s.get("id") != station_id]
                if len(new_stations) == len(stations):
                    self.send_error(404)
                    return
                _save_radio_stations(new_stations)
            self._send_json({"ok": True})
            return

        self.send_error(404)


def _probe_alsa_device():
    """Return True if the ALSA device is fully enumerated and ready to open.

    Strategy 1: aplay -l -- lists all ALSA devices. If the target card/device
    appears in the output the kernel driver has attached and the device is usable.
    This works reliably on all platforms including x86/Debian where
    --dump-hw-params against /dev/null returns a read error.

    Strategy 2: aplay --dump-hw-params /dev/null -- attempts to open the device
    directly. Works on Pi/Raspbian but not on all Debian x86 systems.
    """
    # Strategy 1: check aplay -l output for our device
    try:
        result = subprocess.run(
            ["aplay", "-l"],
            capture_output=True,
            timeout=3
        )
        output = (result.stdout + result.stderr).decode("utf-8", errors="ignore")
        # ALSA_DEVICE is e.g. "hw:0,0" or "hw:CARD=ZD3,DEV=0"
        # Check both card number and card name forms
        dev = ALSA_DEVICE.lower()
        card_num = None
        card_name = None
        try:
            # hw:0,0 -> card 0
            parts = dev.replace("hw:", "").split(",")
            if parts[0].isdigit():
                card_num = parts[0]
            # hw:CARD=ZD3,DEV=0 -> ZD3
            for part in parts:
                if part.startswith("card="):
                    card_name = part.split("=", 1)[1]
        except Exception:
            pass
        for line in output.splitlines():
            ll = line.lower()
            if card_num and ("card " + card_num) in ll:
                return True
            if card_name and card_name.lower() in ll:
                return True
    except Exception as e:
        logger.debug("ALSA probe (aplay -l) failed: %s", e)

    # Strategy 2: dump-hw-params (works on Pi, may fail on x86 Debian)
    try:
        result = subprocess.run(
            ["aplay",
             "--device=" + ALSA_DEVICE,
             "--dump-hw-params",
             "/dev/null"],
            capture_output=True,
            timeout=3
        )
        output = (result.stdout + result.stderr).decode("utf-8", errors="ignore")
        if result.returncode == 0:
            return True
        if "HW Params" in output or "ACCESS" in output or "FORMAT" in output:
            return True
    except Exception as e:
        logger.debug("ALSA probe (dump-hw-params) failed: %s", e)

    return False


def _configure_audio_when_ready(attempt=0):
    """Probe the ALSA device and call configure_audio() once it is ready.

    Retries every 3 seconds up to 10 times (~30 seconds total).
    This mirrors Squeezelite's strategy of attempting to open the device
    before committing to exclusive mode, rather than relying on a fixed
    startup delay. Works for both Pi 4 (fast) and Pi 5 (slower cold boot).
    """
    MAX_ATTEMPTS  = 10
    RETRY_MS      = 3000

    if _probe_alsa_device():
        logger.info("ALSA device ready after %d probe attempt(s) -- configuring audio",
                    attempt + 1)
        configure_audio()
        return False   # stop GLib timer

    if attempt >= MAX_ATTEMPTS - 1:
        logger.error(
            "ALSA device not ready after %d attempts -- "
            "falling back to configure_audio() anyway", MAX_ATTEMPTS
        )
        configure_audio()
        return False

    logger.info(
        "ALSA device not ready (attempt %d/%d) -- retrying in %dms",
        attempt + 1, MAX_ATTEMPTS, RETRY_MS
    )
    GLib.timeout_add(RETRY_MS,
                     lambda: _configure_audio_when_ready(attempt + 1))
    return False


def configure_audio():
    player = APP_INSTANCE.player
    logger.info("Configuring audio output: driver=%s device=%s", ALSA_DRIVER, ALSA_DEVICE)
    player.requested_driver    = ALSA_DRIVER
    player.requested_device_id = ALSA_DEVICE
    player.bit_perfect_mode    = True
    player.exclusive_lock_mode = True
    player.active_rate_switch  = True
    player.set_output(ALSA_DRIVER, ALSA_DEVICE)
    return False


def start_http():
    server = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), ControlHandler)
    logger.info("HTTP control server started on %s:%d", HTTP_HOST, HTTP_PORT)
    server.serve_forever()


def main():
    global APP_INSTANCE, HTTP_PORT, HTTP_HOST, ALSA_DRIVER, ALSA_DEVICE, ALSA_DAC_NAME
    parser = argparse.ArgumentParser(description="SROVA headless")
    parser.add_argument("--port",        type=int, default=None,    help="HTTP port")
    parser.add_argument("--host",        type=str, default="0.0.0.0", help="Bind host")
    parser.add_argument("--log-level",   type=str, default="INFO",  help="Log level")
    parser.add_argument("--alsa-driver", type=str, default=None,    help="ALSA driver override (ALSA or alsa_mmap)")
    parser.add_argument("--alsa-device", type=str, default=None,    help="ALSA device override, e.g. hw:0,0")
    args = parser.parse_args()
    setup_logging()
    try:
        migration = _migrate_legacy_network_root_state()
        logger.info(
            "Network Music root migration status=%s changed=%s pending=%s",
            migration.get("status"),
            bool(migration.get("changed")),
            migration.get("pending_roots") or [],
        )
    except Exception as exc:
        logger.warning("Network Music root migration failed safely: %s", exc)
    env_port = _load_srova_env_port()
    HTTP_PORT = env_port or args.port or 8081
    HTTP_HOST = str(args.host or "0.0.0.0").strip() or "0.0.0.0"
    if env_port and args.port and int(args.port) != int(env_port):
        logger.info("Using SROVA_PORT=%d from %s instead of CLI --port %d", env_port, _SROVA_ENV_FILE, args.port)
    saved_audio_output_loaded = _load_audio_output_config()
    force_cli_audio = str(os.environ.get("SROVA_FORCE_CLI_AUDIO", "") or "").strip().lower() in ("1", "true", "yes", "on")
    if saved_audio_output_loaded and (args.alsa_driver is not None or args.alsa_device is not None) and not force_cli_audio:
        logger.info(
            "Using Settings-saved audio output preference; ignoring CLI audio override. "
            "Set SROVA_FORCE_CLI_AUDIO=1 to force --alsa-driver/--alsa-device."
        )
    else:
        if args.alsa_driver is not None:
            ALSA_DRIVER = _validate_audio_driver(args.alsa_driver)
        if args.alsa_device is not None:
            ALSA_DEVICE = _validate_audio_device(args.alsa_device)
            ALSA_DAC_NAME = _resolve_dac_name(ALSA_DEVICE)
    logger.info("Starting SROVA headless runtime")

    # Silence routine Rust audio state chatter
    logging.getLogger("_rust.audio").setLevel(logging.WARNING)

    APP_INSTANCE = HeadlessApp()

    # 1.8.0 app_init_runtime._init_runtime_state references ui_config.WINDOW_WIDTH/HEIGHT.
    # Patch the ui.config module with safe defaults if it hasn't been imported yet,
    # so headless startup never fails on a missing GTK window size constant.
    try:
        from ui import config as _ui_cfg
        if not hasattr(_ui_cfg, "WINDOW_WIDTH"):
            _ui_cfg.WINDOW_WIDTH  = 1024
        if not hasattr(_ui_cfg, "WINDOW_HEIGHT"):
            _ui_cfg.WINDOW_HEIGHT = 768
    except Exception:
        import types as _types
        import sys as _sys
        _fake = _types.ModuleType("ui.config")
        _fake.WINDOW_WIDTH  = 1024
        _fake.WINDOW_HEIGHT = 768
        _sys.modules.setdefault("ui.config", _fake)
        _sys.modules.setdefault("ui",        _types.ModuleType("ui"))

    app_init_runtime.init_runtime(APP_INSTANCE)
    APP_INSTANCE.player._on_rust_event = filtered_rust_event

    try:
        APP_INSTANCE.backend.try_load_session()
        logger.info("Tidal session restore attempted")
    except Exception as e:
        logger.warning("Session restore failed: %s", e)

    # Restore queue from disk (silent -- no auto-resume, Option A)
    load_queue()
    _reset_startup_playback_state()

    # Restore persisted SROVA app settings
    _load_app_settings()

    # Restore scrobble credentials
    _load_scrobble_creds()

    # Load rich metadata cache from disk
    _load_meta_cache()

    install_eos_hook()

    http_thread = threading.Thread(target=start_http, daemon=True)
    http_thread.start()

    # Restore audio output preference for status/UI only. The selected DAC is
    # opened lazily by _ensure_audio_output_for_playback() on intentional play.

    # Enable spectrum data stream for VU meter (read-only tap, no audio path impact)
    def _enable_spectrum():
        try:
            if hasattr(APP_INSTANCE.player, "set_spectrum_enabled"):
                APP_INSTANCE.player.set_spectrum_enabled(True)
                logger.info("Spectrum stream enabled for VU meter")
        except Exception as e:
            logger.debug("set_spectrum_enabled failed: %s", e)
        return False
    GLib.timeout_add(2000, _enable_spectrum)

    loop = GLib.MainLoop()
    logger.info("Entering GLib main loop")
    try:
        loop.run()
    except KeyboardInterrupt:
        logger.info("Shutting down runtime")


if __name__ == "__main__":
    main()
