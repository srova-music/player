import base64
import json
import hashlib
import logging
import os
import re
import shlex
import sqlite3
import threading
import time
import uuid
import wave
from pathlib import Path
from urllib.parse import quote

from utils.paths import get_cache_dir, get_data_dir


logger = logging.getLogger(__name__)

DB_FILENAME = "local_music.sqlite3"
FLAC_EXTENSION = ".flac"
CUE_EXTENSION = ".cue"
ALAC_EXTENSIONS = {".alac", ".m4a"}
WAV_EXTENSIONS = {".wav", ".wave"}
SUPPORTED_AUDIO_EXTENSIONS = {
    FLAC_EXTENSION,
    ".ape",
    ".wav",
    ".wave",
    ".aiff",
    ".aif",
    ".alac",
    ".m4a",
}
LOSSY_AUDIO_EXTENSIONS = {
    ".mp3",
    ".aac",
    ".ogg",
    ".oga",
    ".opus",
    ".wma",
    ".m4p",
    ".mp2",
}
LOSSY_AUDIO_SAMPLE_LIMIT = 12
LOSSLESS_SCAN_NOTICE = (
    "SROVA is designed as a lossless player. Lossy audio formats are "
    "intentionally ignored during Local Music scans."
)

CUE_FALLBACK_REFERENCE_EXTENSIONS = set(SUPPORTED_AUDIO_EXTENSIONS)
ARTWORK_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ARTWORK_MIN_BYTES = 2048
ARTWORK_PREFERRED_NAMES = ("cover", "folder", "front", "album", "artwork", "albumart", "art", "scan")
EMBEDDED_ARTWORK_EXTENSIONS = {".flac", ".ape", ".m4a", ".mp4", ".alac"}
COLLECTION_MIN_TRACKS = 8
COLLECTION_MIN_ONE_TRACK_GROUPS = 5
COLLECTION_MIN_DISTINCT_ARTISTS = 5
SQLITE_TIMEOUT_SECONDS = 2.0
SQLITE_BUSY_TIMEOUT_MS = 2000
SCAN_COMMIT_BATCH_SIZE = 100
LOCAL_METADATA_VERSION = 4
LOCAL_ARTWORK_LOOKUP_DISABLED_ENV = "SROVA_LOCAL_LIBRARY_DISABLE_ARTWORK_LOOKUP"
IGNORED_SYSTEM_DIR_NAMES = {
    "$recycle.bin",
    ".trash",
    ".trashes",
    "system volume information",
    "lost+found",
    ".fseventsd",
    ".spotlight-v100",
    "@eadir",
    "__macosx",
}

_SCAN_LOCK = threading.Lock()
_SCAN_STATE_LOCK = threading.Lock()
_SCAN_STATE = {
    "scan_running": False,
    "rebuild_running": False,
    "maintenance_mode": None,
    "scan_started_at": None,
    "scan_finished_at": None,
    "last_scan_at": None,
    "last_scan_stats": None,
    "last_scan_error": None,
}
_INIT_LOCK = threading.Lock()
_INITIALIZED_DBS = set()


class LocalLibraryBusyError(RuntimeError):
    pass


def _is_sqlite_busy(exc):
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    text = str(exc).lower()
    return "database is locked" in text or "database is busy" in text


def _scan_state_snapshot():
    with _SCAN_STATE_LOCK:
        return dict(_SCAN_STATE)


def _update_scan_state(**kwargs):
    with _SCAN_STATE_LOCK:
        _SCAN_STATE.update(kwargs)
        return dict(_SCAN_STATE)


def local_library_rebuild_running():
    state = _scan_state_snapshot()
    return bool(state.get("rebuild_running")) or state.get("maintenance_mode") == "local_library_rebuild"


def _coerce_limit(limit, default=100, maximum=1000):
    try:
        return max(1, min(int(limit), int(maximum)))
    except Exception:
        return int(default)


def _coerce_album_sort(sort):
    value = str(sort or "latest").strip().lower()
    if value in ("latest", "oldest", "alpha_asc", "alpha_desc"):
        return value
    return "latest"


def _album_wall_quality_from_tracks(tracks):
    known = []
    missing = False
    for track in tracks or []:
        codec = str(track.get("codec") or "").strip().upper()
        try:
            bit_depth = int(track.get("bit_depth") or 0)
        except Exception:
            bit_depth = 0
        try:
            sample_rate = int(track.get("sample_rate") or 0)
        except Exception:
            sample_rate = 0
        if not codec or not bit_depth or not sample_rate:
            missing = True
            continue
        known.append({
            "codec": codec,
            "bit_depth": bit_depth,
            "sample_rate": sample_rate,
        })

    if not known:
        return None

    first = known[0]
    codec_mixed = any(track["codec"] != first["codec"] for track in known)
    resolution_mixed = any(
        track["bit_depth"] != first["bit_depth"] or track["sample_rate"] != first["sample_rate"]
        for track in known
    )
    if codec_mixed or resolution_mixed:
        return "mixed"
    if missing:
        return None
    if first["bit_depth"] > 16 or first["sample_rate"] > 48000:
        return "hires"
    return "cd"


def _like_pattern(value):
    text = str(value or "").strip()
    text = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + text + "%"


def _path_inside_root(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except Exception:
        return False


def _normalise_roots(roots):
    out = []
    for item in roots or []:
        text = str(item or "").strip()
        if not text:
            continue
        if _local_artwork_lookup_disabled():
            try:
                root = os.path.normpath(os.path.abspath(os.path.expanduser(text)))
            except Exception:
                root = text
            if root and root not in out:
                out.append(root)
            continue
        root = os.path.realpath(os.path.expanduser(text))
        if root and os.path.isdir(root) and root not in out:
            out.append(root)
    return out


def _is_ignored_system_dir_name(name):
    text = str(name or "").strip().casefold()
    if not text:
        return False
    if text.startswith(".trash-"):
        return True
    return text in IGNORED_SYSTEM_DIR_NAMES


def _path_has_ignored_system_dir(path):
    text = str(path or "")
    if not text:
        return False
    for part in text.split("::cue:"):
        for name in re.split(r"[\\/]+", part):
            if _is_ignored_system_dir_name(name):
                return True
    return False


def _artwork_url_for_path(path):
    return "/api/local/library/artwork?p=" + quote(str(path or ""), safe="")


def _embedded_artwork_url_for_path(path):
    return "/api/local/library/artwork?e=" + quote(str(path or ""), safe="")


def _artwork_mime_for_path(path):
    ext = os.path.splitext(str(path or ""))[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return None


def _extension_for_mime(mime):
    if mime == "image/jpeg":
        return ".jpg"
    if mime == "image/png":
        return ".png"
    if mime == "image/webp":
        return ".webp"
    return ""


def _validate_artwork_path(path, roots):
    requested = str(path or "").strip()
    if not requested:
        raise ValueError("artwork path required")
    real_path = os.path.realpath(os.path.expanduser(requested))
    if not any(_path_inside_root(real_path, root) for root in roots):
        raise PermissionError("artwork path outside local roots")
    if not os.path.isfile(real_path):
        raise ValueError("artwork path is not a file")
    if os.path.basename(real_path).startswith("."):
        raise ValueError("hidden artwork files are not supported")
    mime = _artwork_mime_for_path(real_path)
    if not mime:
        raise ValueError("unsupported artwork extension")
    if os.path.getsize(real_path) < ARTWORK_MIN_BYTES:
        raise ValueError("artwork file is too small")
    return real_path, mime


def _validate_embedded_artwork_track_path(path, roots):
    requested = str(path or "").strip()
    if not requested:
        raise ValueError("track path required")
    real_path = os.path.realpath(os.path.expanduser(requested))
    if not any(_path_inside_root(real_path, root) for root in roots):
        raise PermissionError("track path outside local roots")
    if not os.path.isfile(real_path):
        raise ValueError("track path is not a file")
    if os.path.basename(real_path).startswith("."):
        raise ValueError("hidden track files are not supported")
    if os.path.splitext(real_path)[1].lower() not in EMBEDDED_ARTWORK_EXTENSIONS:
        raise ValueError("unsupported embedded artwork track extension")
    return real_path


def _embedded_artwork_cache_dir():
    path = os.path.join(get_cache_dir(), "local_artwork")
    os.makedirs(path, exist_ok=True)
    return path


def _embedded_artwork_cache_base(track_path):
    stat = os.stat(track_path)
    basis = "%s:%s:%s" % (track_path, stat.st_mtime_ns, stat.st_size)
    return hashlib.sha256(basis.encode("utf-8", "surrogatepass")).hexdigest()


def _mime_from_image_bytes(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _parse_flac_picture_block(data):
    try:
        pos = 0
        if len(data) < 32:
            return None
        pic_type = int.from_bytes(data[pos:pos + 4], "big")
        pos += 4
        mime_len = int.from_bytes(data[pos:pos + 4], "big")
        pos += 4
        mime = data[pos:pos + mime_len].decode("ascii", "ignore").lower()
        pos += mime_len
        desc_len = int.from_bytes(data[pos:pos + 4], "big")
        pos += 4 + desc_len
        pos += 16
        data_len = int.from_bytes(data[pos:pos + 4], "big")
        pos += 4
        image_data = data[pos:pos + data_len]
        if len(image_data) != data_len or len(image_data) < ARTWORK_MIN_BYTES:
            return None
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            mime = _mime_from_image_bytes(image_data)
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            return None
        return image_data, mime, pic_type
    except Exception:
        return None


def _extract_flac_embedded_artwork(track_path):
    try:
        with open(track_path, "rb") as f:
            if f.read(4) != b"fLaC":
                return None
            fallback = None
            while True:
                header = f.read(4)
                if len(header) != 4:
                    break
                is_last = bool(header[0] & 0x80)
                block_type = header[0] & 0x7f
                length = int.from_bytes(header[1:4], "big")
                block = f.read(length)
                if len(block) != length:
                    break
                if block_type == 6:
                    parsed = _parse_flac_picture_block(block)
                    if parsed:
                        image_data, mime, pic_type = parsed
                        if int(pic_type or 0) == 3:
                            return image_data, mime
                        if fallback is None:
                            fallback = (image_data, mime)
                elif block_type == 4:
                    parsed = _extract_flac_vorbis_picture(block)
                    if parsed:
                        return parsed
                if is_last:
                    break
            return fallback
    except Exception:
        return None


def _extract_flac_vorbis_picture(block):
    try:
        pos = 0
        vendor_len = int.from_bytes(block[pos:pos + 4], "little")
        pos += 4 + vendor_len
        comment_count = int.from_bytes(block[pos:pos + 4], "little")
        pos += 4
        for _idx in range(comment_count):
            if pos + 4 > len(block):
                return None
            comment_len = int.from_bytes(block[pos:pos + 4], "little")
            pos += 4
            raw = block[pos:pos + comment_len]
            pos += comment_len
            text = raw.decode("utf-8", "ignore")
            if "=" not in text:
                continue
            key, value = text.split("=", 1)
            if key.strip().upper() != "METADATA_BLOCK_PICTURE":
                continue
            parsed = _parse_flac_picture_block(base64.b64decode(value.strip()))
            if parsed:
                image_data, mime, _pic_type = parsed
                return image_data, mime
    except Exception:
        return None
    return None


def _extract_embedded_artwork_bytes(track_path):
    if os.path.splitext(track_path)[1].lower() == ".flac":
        extracted = _extract_flac_embedded_artwork(track_path)
        if extracted:
            return extracted

    try:
        from mutagen import File as MutagenFile
        from mutagen.flac import FLAC
        from mutagen.id3 import APIC
        from mutagen.mp4 import MP4Cover
    except Exception:
        return None

    try:
        audio = MutagenFile(track_path)
    except Exception:
        return None
    if audio is None:
        return None

    pictures = []
    try:
        if isinstance(audio, FLAC):
            pictures = list(getattr(audio, "pictures", []) or [])
    except Exception:
        pictures = []
    if pictures:
        pictures.sort(key=lambda pic: 0 if int(getattr(pic, "type", 0) or 0) == 3 else 1)
        for pic in pictures:
            mime = str(getattr(pic, "mime", "") or "").lower()
            data = getattr(pic, "data", None)
            if mime in ("image/jpeg", "image/png", "image/webp") and data and len(data) >= ARTWORK_MIN_BYTES:
                return data, mime

    try:
        tags = getattr(audio, "tags", None)
        if tags:
            for value in tags.values():
                values = value if isinstance(value, list) else [value]
                for item in values:
                    if isinstance(item, APIC):
                        mime = str(getattr(item, "mime", "") or "").lower()
                        data = getattr(item, "data", None)
                        if mime in ("image/jpeg", "image/png", "image/webp") and data and len(data) >= ARTWORK_MIN_BYTES:
                            return data, mime
                    if isinstance(item, MP4Cover):
                        data = bytes(item)
                        fmt = getattr(item, "imageformat", None)
                        mime = "image/png" if fmt == MP4Cover.FORMAT_PNG else "image/jpeg"
                        if data and len(data) >= ARTWORK_MIN_BYTES:
                            return data, mime
    except Exception:
        return None
    return None


def _embedded_artwork_file_for_track_path(path, roots):
    track_path = _validate_embedded_artwork_track_path(path, roots)
    base = _embedded_artwork_cache_base(track_path)
    cache_dir = _embedded_artwork_cache_dir()
    for ext in (".jpg", ".png", ".webp"):
        cached = os.path.join(cache_dir, base + ext)
        if os.path.isfile(cached) and os.path.getsize(cached) >= ARTWORK_MIN_BYTES:
            mime = _artwork_mime_for_path(cached)
            if mime:
                return cached, mime

    extracted = _extract_embedded_artwork_bytes(track_path)
    if not extracted:
        raise ValueError("embedded artwork not found")
    data, mime = extracted
    ext = _extension_for_mime(mime)
    if not ext:
        raise ValueError("unsupported embedded artwork mime")
    cached = os.path.join(cache_dir, base + ext)
    with open(cached, "wb") as f:
        f.write(data)
    return cached, mime


def _is_disc_folder_name(name):
    text = str(name or "").strip().casefold().replace("_", " ").replace("-", " ")
    parts = [p for p in text.split() if p]
    if not parts:
        return False
    if parts[0] in ("cd", "disc", "disk") and (len(parts) == 1 or any(p.isdigit() for p in parts[1:])):
        return True
    compact = "".join(parts)
    if compact.startswith(("cd", "disc", "disk")):
        suffix = compact[2:] if compact.startswith("cd") else compact[4:]
        return bool(suffix) and suffix.isdigit()
    return False



def _local_artwork_lookup_disabled():
    return str(os.environ.get(LOCAL_ARTWORK_LOOKUP_DISABLED_ENV, "")).strip().lower() in {
        "1", "true", "yes", "on"
    }


def _local_db_path_for_grouping(path):
    """Normalize DB-stored paths without triggering autofs/stat when protection is active."""
    text = str(path or "")
    if not text:
        return ""
    if _local_artwork_lookup_disabled():
        try:
            return os.path.normpath(os.path.abspath(text))
        except Exception:
            return text
    return os.path.realpath(text)



def _local_path_inside_configured_root(path, roots):
    text = str(path or "")
    if not text:
        return False
    try:
        target = os.path.normpath(os.path.abspath(text))
    except Exception:
        target = text
    for root in roots or []:
        root_text = str(root or "")
        if not root_text:
            continue
        try:
            root_norm = os.path.normpath(os.path.abspath(root_text))
        except Exception:
            root_norm = root_text
        try:
            if os.path.commonpath([target, root_norm]) == root_norm:
                return True
        except Exception:
            if target == root_norm or target.startswith(root_norm.rstrip("/") + "/"):
                return True
    return False


def _filter_rows_to_configured_roots(rows, roots):
    roots = [str(r or "").strip() for r in (roots or []) if str(r or "").strip()]
    if not roots:
        return list(rows or [])
    out = []
    for row in rows or []:
        try:
            root = str(row.get("root") or "")
            path = _track_storage_path(row)
            if (root and _local_path_inside_configured_root(root, roots)) or (
                path and _local_path_inside_configured_root(path, roots)
            ):
                out.append(row)
        except Exception:
            continue
    return out



def _album_artwork_search_folders(track_folder, roots=None):
    if _local_artwork_lookup_disabled():
        return []
    roots = roots or []
    try:
        folder = os.path.realpath(track_folder)
    except Exception:
        return []
    out = []
    if folder and os.path.isdir(folder):
        out.append(folder)
    parent = _local_db_path_for_grouping(os.path.dirname(folder)) if folder else ""
    if parent and parent != folder and _is_disc_folder_name(os.path.basename(folder)):
        out.append(parent)
    if roots:
        out = [p for p in out if any(_path_inside_root(p, root) for root in roots)]
    deduped = []
    for p in out:
        if p not in deduped:
            deduped.append(p)
    return deduped


def _select_album_artwork_from_folder(folder, roots):
    if _local_artwork_lookup_disabled():
        return None
    try:
        folder_real = os.path.realpath(folder)
    except Exception:
        return None
    if not os.path.isdir(folder_real):
        return None
    if not any(_path_inside_root(folder_real, root) for root in roots):
        return None

    candidates = []
    try:
        entries = sorted(os.scandir(folder_real), key=lambda e: e.name.lower())
    except Exception:
        return None
    for entry in entries:
        name = entry.name
        if not name or name.startswith("."):
            continue
        try:
            if not entry.is_file(follow_symlinks=True):
                continue
        except Exception:
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in ARTWORK_EXTENSIONS:
            continue
        try:
            real_path = os.path.realpath(entry.path)
            if not any(_path_inside_root(real_path, root) for root in roots):
                continue
            if os.path.getsize(real_path) < ARTWORK_MIN_BYTES:
                continue
        except Exception:
            continue

        stem = os.path.splitext(name)[0].lower()
        if stem in ARTWORK_PREFERRED_NAMES:
            rank = (0, ARTWORK_PREFERRED_NAMES.index(stem), stem, name.lower())
        else:
            contained = [idx for idx, word in enumerate(ARTWORK_PREFERRED_NAMES) if word in stem]
            if contained:
                rank = (1, min(contained), stem, name.lower())
            else:
                rank = (2, 999, stem, name.lower())
        candidates.append((rank, real_path))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _select_album_artwork_for_track_path(track_path, roots):
    if not track_path:
        return None
    for folder in _album_artwork_search_folders(os.path.dirname(str(track_path)), roots):
        artwork = _select_album_artwork_from_folder(folder, roots)
        if artwork:
            return artwork
    return None


def _select_album_artwork_for_paths(paths, roots):
    seen = set()
    for path in sorted([str(p or "") for p in paths or []], key=lambda p: p.lower()):
        if not path or path in seen:
            continue
        seen.add(path)
        artwork = _select_album_artwork_for_track_path(path, roots)
        if artwork:
            return artwork
    return None


def _select_embedded_artwork_track_for_paths(paths, roots):
    seen = set()
    for path in sorted([str(p or "") for p in paths or []], key=lambda p: p.lower()):
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            _embedded_artwork_file_for_track_path(path, roots)
            return path
        except Exception:
            continue
    return None


def _album_artwork_url_for_paths(paths, roots):
    if _local_artwork_lookup_disabled():
        return None
    artwork_path = _select_album_artwork_for_paths(paths, roots)
    if artwork_path:
        return _artwork_url_for_path(artwork_path)
    embedded_path = _select_embedded_artwork_track_for_paths(paths, roots)
    if embedded_path:
        return _embedded_artwork_url_for_path(embedded_path)
    return None


def _add_artwork_to_album_rows(rows, roots):
    albums = []
    for row in rows:
        item = dict(row)
        folder = os.path.dirname(item.pop("_album_folder", "") or "")
        artwork_path = _select_album_artwork_from_folder(folder, roots)
        item["artwork_url"] = _artwork_url_for_path(artwork_path) if artwork_path else None
        albums.append(item)
    return albums


def _album_folder_for_path(path):
    return _local_db_path_for_grouping(os.path.dirname(str(path or "")))


def _album_root_folder_for_path(path):
    if "::cue:" in str(path or ""):
        path = str(path).split("::cue:", 1)[0]
    folder = _album_folder_for_path(path)
    parent = _local_db_path_for_grouping(os.path.dirname(folder)) if folder else ""
    if parent and parent != folder and _is_disc_folder_name(os.path.basename(folder)):
        return parent
    return folder


def _album_id_for_group_key(key):
    basis = json.dumps(key, sort_keys=True, ensure_ascii=False)
    return "local-album:" + uuid.uuid5(uuid.NAMESPACE_URL, basis).hex


def _album_display_artist(artists, album_artist=None):
    album_artist = str(album_artist or "").strip()
    if album_artist:
        aa_key = album_artist.casefold()
        if aa_key in ("v.a.", "va", "v/a", "various", "various artist", "various artists") or aa_key.startswith("various"):
            return "Various Artists"
        return album_artist
    clean = []
    seen = set()
    for artist in artists or []:
        text = str(artist or "").strip()
        key = text.casefold()
        if text and key not in seen:
            clean.append(text)
            seen.add(key)
    if len(clean) > 1:
        return "Various Artists"
    if clean:
        return clean[0]
    return "Local Library"


def _clean_collection_title(folder):
    title = os.path.basename(_local_db_path_for_grouping(str(folder or ""))).strip()
    lowered = title.casefold()
    for prefix in ("various artists - ", "v.a. - ", "va - "):
        if lowered.startswith(prefix):
            return title[len(prefix):].strip() or title
    return title or "Local Collection"


def _base_album_group_key(row):
    album = str(row.get("album") or "Local File").strip() or "Local File"
    album_artist = str(row.get("album_artist") or "").strip()
    folder = _album_root_folder_for_path(_track_storage_path(row))
    if album_artist:
        return ("album_artist", album_artist.casefold(), album.casefold(), folder), album
    if int(row.get("compilation") or 0):
        return ("compilation", album.casefold(), folder), album
    return ("folder", album.casefold(), folder), album


def _track_storage_path(row):
    if isinstance(row, dict):
        return row.get("cue_audio_path") or row.get("path") or ""
    try:
        return row["cue_audio_path"] or row["path"] or ""
    except Exception:
        try:
            return row["path"] or ""
        except Exception:
            return ""


def _build_collection_folder_info(rows):
    folders = {}
    for row in rows or []:
        folder = _album_root_folder_for_path(_track_storage_path(row))
        if not folder:
            continue
        base_key, _album = _base_album_group_key(row)
        info = folders.setdefault(folder, {
            "tracks": 0,
            "albums": set(),
            "album_artists": set(),
            "artists": set(),
            "base_groups": {},
        })
        info["tracks"] += 1
        album = str(row.get("album") or "").strip()
        album_artist = str(row.get("album_artist") or "").strip()
        artist = str(row.get("artist") or "").strip()
        if album:
            info["albums"].add(album.casefold())
        if album_artist:
            info["album_artists"].add(album_artist.casefold())
        if artist:
            info["artists"].add(artist.casefold())
        info["base_groups"][base_key] = info["base_groups"].get(base_key, 0) + 1

    out = {}
    for folder, info in folders.items():
        one_track_groups = sum(1 for count in info["base_groups"].values() if count == 1)
        distinct_albums = len(info["albums"])
        distinct_album_artists = len(info["album_artists"])
        distinct_artists = len(info["artists"])
        is_collection = (
            info["tracks"] >= COLLECTION_MIN_TRACKS
            and (
                one_track_groups >= COLLECTION_MIN_ONE_TRACK_GROUPS
                or (
                    distinct_artists >= COLLECTION_MIN_DISTINCT_ARTISTS
                    and distinct_albums >= COLLECTION_MIN_DISTINCT_ARTISTS
                )
                or (
                    distinct_albums == 1
                    and distinct_album_artists >= COLLECTION_MIN_DISTINCT_ARTISTS
                )
            )
        )
        out[folder] = {
            "is_collection": is_collection,
            "title": _clean_collection_title(folder),
            "one_track_groups": one_track_groups,
            "track_count": info["tracks"],
            "distinct_albums": distinct_albums,
            "distinct_album_artists": distinct_album_artists,
            "distinct_artists": distinct_artists,
        }
    return out


def _album_group_key(row, collection_info=None):
    folder = _album_root_folder_for_path(_track_storage_path(row))
    info = (collection_info or {}).get(folder)
    if info and info.get("is_collection"):
        return ("collection_folder", folder), info.get("title") or _clean_collection_title(folder)
    return _base_album_group_key(row)


def _parse_leading_number(value):
    text = os.path.splitext(os.path.basename(str(value or "")))[0]
    digits = ""
    for ch in text:
        if ch.isdigit():
            digits += ch
            continue
        break
    if digits:
        try:
            return int(digits)
        except Exception:
            return None
    return None


def _track_sort_key(track):
    path = _track_storage_path(track)
    folder = os.path.basename(os.path.dirname(path)).lower()
    disc = track.get("disc_number")
    number = track.get("track_number")
    if disc is None:
        disc = _parse_leading_number(folder)
    if number is None:
        number = _parse_leading_number(path)
    return (
        disc if disc is not None else 999,
        number if number is not None else 9999,
        str(path or "").lower(),
    )


def _decorate_track_order(track):
    item = dict(track)
    path = _track_storage_path(item)
    folder = os.path.basename(os.path.dirname(path))
    if item.get("disc_number") is None:
        item["disc_number"] = _parse_leading_number(folder)
    if item.get("track_number") is None:
        item["track_number"] = _parse_leading_number(path)
    return item


def local_library_db_path():
    return os.path.realpath(os.path.join(get_data_dir(), DB_FILENAME))


def _assert_db_outside_roots(db_path, roots):
    db_real = os.path.realpath(db_path)
    for root in _normalise_roots(roots):
        if _path_inside_root(db_real, root):
            raise RuntimeError(
                "Local library database path is inside an allowlisted music root; "
                "refusing to initialize scanner index"
            )



def _lossy_audio_label_for_path(path):
    ext = os.path.splitext(str(path or ""))[1].lower()
    if ext in LOSSY_AUDIO_EXTENSIONS:
        return ext.lstrip(".").upper() or "LOSSY"
    if ext == ".m4a":
        try:
            if probe_lossless_file(os.path.realpath(path)) is None:
                return "M4A/AAC"
        except Exception:
            return "M4A/AAC"
    return None


def _record_lossy_audio_ignored(stats, path):
    label = _lossy_audio_label_for_path(path)
    if not label:
        return False
    stats["lossy_audio_ignored"] = int(stats.get("lossy_audio_ignored") or 0) + 1
    by_format = stats.setdefault("lossy_audio_by_format", {})
    by_format[label] = int(by_format.get(label) or 0) + 1
    sample = stats.setdefault("lossy_audio_sample", [])
    if len(sample) < LOSSY_AUDIO_SAMPLE_LIMIT:
        sample.append(os.path.basename(str(path or "")) or str(path or ""))
    return True



def _first_tag(tags, *names):
    if not isinstance(tags, dict):
        return None
    for name in names:
        value = tags.get(str(name).lower())
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def _parse_tag_int(value):
    text = str(value or "").strip()
    if not text:
        return None
    text = text.split("/", 1)[0].strip()
    digits = ""
    for ch in text:
        if ch.isdigit():
            digits += ch
            continue
        if digits:
            break
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _compilation_value(value):
    text = str(value or "").strip().casefold()
    if text in ("1", "true", "yes", "y"):
        return 1
    if text in ("0", "false", "no", "n", ""):
        return 0
    return 0


def _parse_flac_comments(data):
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
            if pos + item_len > len(data):
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


def probe_flac_file(real_path):
    metadata = {"codec": "FLAC"}
    with open(real_path, "rb") as f:
        if f.read(4) != b"fLaC":
            return metadata
        for _ in range(64):
            header = f.read(4)
            if len(header) != 4:
                break
            is_last = bool(header[0] & 0x80)
            block_type = header[0] & 0x7f
            length = int.from_bytes(header[1:4], "big")
            if length > 16 * 1024 * 1024:
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
                tags = _parse_flac_comments(data)
                for out_key, names in (
                    ("title", ("title",)),
                    ("artist", ("artist",)),
                    ("album_artist", ("albumartist", "album_artist", "album artist", "albumartistsort")),
                    ("album", ("album",)),
                ):
                    value = _first_tag(tags, *names)
                    if value:
                        metadata[out_key] = value
                compilation = _first_tag(tags, "compilation", "itunescompilation")
                if compilation is not None:
                    metadata["compilation"] = _compilation_value(compilation)
                track_number = _first_tag(tags, "tracknumber", "track")
                if track_number is not None:
                    metadata["track_number"] = _parse_tag_int(track_number)
                disc_number = _first_tag(tags, "discnumber", "disc")
                if disc_number is not None:
                    metadata["disc_number"] = _parse_tag_int(disc_number)
            if is_last:
                break
    return metadata


def _codec_for_extension(real_path):
    ext = os.path.splitext(str(real_path or ""))[1].lower()
    return {
        ".ape": "APE",
        ".wav": "WAV",
        ".wave": "WAV",
        ".aiff": "AIFF",
        ".aif": "AIFF",
        ".alac": "ALAC",
        ".m4a": "ALAC",
    }.get(ext, ext.lstrip(".").upper() or "Local")


def _first_mutagen_tag(tags, *names):
    if not tags:
        return None
    lowered = {str(key).lower(): value for key, value in getattr(tags, "items", lambda: [])()}
    for name in names:
        value = lowered.get(str(name).lower())
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = str(item).strip()
            if text:
                return text
    return None


def _first_info_int(info, *names):
    for name in names:
        try:
            value = getattr(info, name, None)
        except Exception:
            continue
        if value in (None, ""):
            continue
        try:
            out = int(value)
        except Exception:
            continue
        if out > 0:
            return out
    return None


def _first_info_duration(info):
    try:
        value = getattr(info, "length", None)
    except Exception:
        return None
    if value in (None, ""):
        return None
    try:
        out = int(round(float(value)))
    except Exception:
        return None
    return out if out > 0 else None


def _probe_info_technical_metadata(info, codec):
    metadata = {"codec": codec}
    duration = _first_info_duration(info)
    sample_rate = _first_info_int(info, "sample_rate", "samplerate")
    bit_depth = _first_info_int(info, "bits_per_sample", "bit_depth", "sample_bits", "bits")
    channels = _first_info_int(info, "channels")
    if duration:
        metadata["duration"] = duration
    if sample_rate:
        metadata["sample_rate"] = sample_rate
    if bit_depth:
        metadata["bit_depth"] = bit_depth
    if channels:
        metadata["channels"] = channels
    return metadata


def _probe_mutagen_audio_file(real_path):
    try:
        from mutagen import File as MutagenFile
    except Exception:
        return None
    try:
        audio = MutagenFile(real_path)
    except Exception:
        return None
    if audio is None:
        return None

    ext = os.path.splitext(real_path)[1].lower()
    info = getattr(audio, "info", None)
    tags = getattr(audio, "tags", None) or {}
    codec = _codec_for_extension(real_path)
    raw_codec = str(getattr(info, "codec", "") or getattr(info, "codec_description", "") or "")
    if ext in ALAC_EXTENSIONS:
        if "alac" not in raw_codec.lower() and "apple lossless" not in raw_codec.lower():
            return None
        codec = "ALAC"

    metadata = {"codec": codec}
    metadata.update(_probe_info_technical_metadata(info, codec))

    for out_key, names in (
        ("title", ("title", "\xa9nam")),
        ("artist", ("artist", "\xa9ART", "albumartist", "album artist")),
        ("album_artist", ("albumartist", "album_artist", "album artist", "aART")),
        ("album", ("album", "\xa9alb")),
    ):
        value = _first_mutagen_tag(tags, *names)
        if value:
            metadata[out_key] = value
    compilation = _first_mutagen_tag(tags, "compilation", "cpil")
    if compilation is not None:
        metadata["compilation"] = _compilation_value(compilation)
    track_number = _first_mutagen_tag(tags, "tracknumber", "track", "trkn")
    if track_number is not None:
        metadata["track_number"] = _parse_tag_int(track_number)
    disc_number = _first_mutagen_tag(tags, "discnumber", "disc", "disk")
    if disc_number is not None:
        metadata["disc_number"] = _parse_tag_int(disc_number)
    return metadata


def _probe_wav_technical_metadata(real_path):
    metadata = {"codec": "WAV"}
    try:
        with wave.open(real_path, "rb") as audio:
            sample_rate = int(audio.getframerate() or 0)
            channels = int(audio.getnchannels() or 0)
            sample_width = int(audio.getsampwidth() or 0)
            frames = int(audio.getnframes() or 0)
            if sample_rate:
                metadata["sample_rate"] = sample_rate
            if channels:
                metadata["channels"] = channels
            if sample_width:
                metadata["bit_depth"] = sample_width * 8
            if sample_rate and frames:
                metadata["duration"] = int(round(frames / float(sample_rate)))
    except Exception:
        return None
    return metadata


def _probe_ape_technical_metadata(real_path):
    metadata = {"codec": "APE"}
    try:
        with open(real_path, "rb") as f:
            header = f.read(64)
    except Exception:
        return None
    if len(header) < 32 or header[0:4] != b"MAC ":
        return None
    try:
        version = int.from_bytes(header[4:6], "little")
        if version >= 3980 and len(header) >= 52:
            descriptor_bytes = int.from_bytes(header[8:12], "little")
            header_bytes = int.from_bytes(header[12:16], "little")
            if descriptor_bytes < 52 or header_bytes < 24:
                return metadata
            with open(real_path, "rb") as f:
                f.seek(descriptor_bytes)
                ape_header = f.read(header_bytes)
            if len(ape_header) < 24:
                return metadata
            blocks_per_frame = int.from_bytes(ape_header[4:8], "little")
            final_frame_blocks = int.from_bytes(ape_header[8:12], "little")
            total_frames = int.from_bytes(ape_header[12:16], "little")
            bit_depth = int.from_bytes(ape_header[16:18], "little")
            channels = int.from_bytes(ape_header[18:20], "little")
            sample_rate = int.from_bytes(ape_header[20:24], "little")
        else:
            if len(header) < 32:
                return metadata
            format_flags = int.from_bytes(header[8:10], "little")
            channels = int.from_bytes(header[10:12], "little")
            sample_rate = int.from_bytes(header[12:16], "little")
            total_frames = int.from_bytes(header[24:28], "little")
            final_frame_blocks = int.from_bytes(header[28:32], "little")
            blocks_per_frame = 73728 * 4 if version >= 3950 else 9216
            if format_flags & 0x08:
                bit_depth = 8
            elif format_flags & 0x01:
                bit_depth = 24
            else:
                bit_depth = 16

        if sample_rate:
            metadata["sample_rate"] = int(sample_rate)
        if bit_depth:
            metadata["bit_depth"] = int(bit_depth)
        if channels:
            metadata["channels"] = int(channels)
        if sample_rate and total_frames:
            total_blocks = max(0, int(total_frames) - 1) * int(blocks_per_frame)
            total_blocks += int(final_frame_blocks or blocks_per_frame)
            if total_blocks > 0:
                metadata["duration"] = int(round(total_blocks / float(sample_rate)))
    except Exception:
        return None
    return metadata


def _merge_missing_metadata(base, fallback):
    out = dict(base or {})
    for key, value in (fallback or {}).items():
        if value not in (None, "") and out.get(key) in (None, ""):
            out[key] = value
    return out


def probe_lossless_file(real_path):
    ext = os.path.splitext(real_path)[1].lower()
    if ext == FLAC_EXTENSION:
        metadata = probe_flac_file(real_path)
        mutagen_metadata = _probe_mutagen_audio_file(real_path) or {}
        metadata.update({k: v for k, v in mutagen_metadata.items() if v not in (None, "")})
        metadata["codec"] = "FLAC"
        return metadata
    if ext not in SUPPORTED_AUDIO_EXTENSIONS:
        return None
    metadata = _probe_mutagen_audio_file(real_path)
    if ext == ".ape":
        metadata = _merge_missing_metadata(metadata, _probe_ape_technical_metadata(real_path))
    if ext in WAV_EXTENSIONS:
        metadata = _merge_missing_metadata(metadata, _probe_wav_technical_metadata(real_path))
    if metadata is None and ext not in ALAC_EXTENSIONS:
        metadata = {"codec": _codec_for_extension(real_path)}
    return metadata


def _track_id_for_path(real_path):
    return "local:" + uuid.uuid5(uuid.NAMESPACE_URL, real_path).hex


def _cue_track_id(cue_path, audio_path, track_number):
    basis = "%s|%s|%s" % (
        os.path.realpath(str(cue_path or "")),
        os.path.realpath(str(audio_path or "")),
        int(track_number or 0),
    )
    return "local:" + uuid.uuid5(uuid.NAMESPACE_URL, "cue:" + basis).hex


def _cue_virtual_path(cue_path, audio_path, track_number):
    return "%s::cue:%s:%02d" % (
        os.path.realpath(str(audio_path or "")),
        os.path.realpath(str(cue_path or "")),
        int(track_number or 0),
    )


def _read_cue_text(cue_path):
    last_error = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(cue_path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    with open(cue_path, "r", encoding="latin-1", errors="replace") as f:
        return f.read()


def _cue_time_to_seconds(value):
    m = re.match(r"^\s*(\d+):(\d{1,2}):(\d{1,2})\s*$", str(value or ""))
    if not m:
        return None
    minutes = int(m.group(1))
    seconds = int(m.group(2))
    frames = int(m.group(3))
    return minutes * 60.0 + seconds + (frames / 75.0)


def _cue_tokens(line):
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _resolve_cue_audio_file(cue_dir, file_ref):
    candidate = os.path.realpath(os.path.join(cue_dir, file_ref))
    if os.path.isfile(candidate):
        return candidate

    expanded = os.path.realpath(os.path.expanduser(file_ref))
    if os.path.isfile(expanded):
        return expanded

    ref_name = os.path.basename(str(file_ref or ""))
    ref_stem, ref_ext = os.path.splitext(ref_name)
    if not ref_stem or ref_ext.lower() not in CUE_FALLBACK_REFERENCE_EXTENSIONS:
        return candidate

    matches = []
    try:
        for sibling in os.listdir(cue_dir):
            sibling_stem, sibling_ext = os.path.splitext(sibling)
            if sibling_stem.casefold() != ref_stem.casefold():
                continue
            if sibling_ext.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                continue
            sibling_path = os.path.realpath(os.path.join(cue_dir, sibling))
            if os.path.isfile(sibling_path):
                matches.append(sibling_path)
    except Exception as exc:
        logger.debug("CUE backing-file fallback scan failed for %s: %s", file_ref, exc)
        return candidate

    unique_matches = sorted(set(matches))
    if len(unique_matches) == 1:
        logger.debug("CUE backing-file fallback resolved %s -> %s", file_ref, unique_matches[0])
        return unique_matches[0]
    if len(unique_matches) > 1:
        logger.debug(
            "CUE backing-file fallback ambiguous for %s: %s",
            file_ref,
            ", ".join(unique_matches),
        )
    return candidate


def _parse_cue_file(cue_path, roots):
    text = _read_cue_text(cue_path)
    cue_dir = os.path.dirname(os.path.realpath(cue_path))
    global_performer = ""
    global_title = ""
    current_file = None
    current_track = None
    tracks = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        try:
            if upper.startswith("PERFORMER "):
                value = line.split(None, 1)[1].strip().strip('"')
                if current_track is not None:
                    current_track["performer"] = value
                else:
                    global_performer = value
            elif upper.startswith("TITLE "):
                value = line.split(None, 1)[1].strip().strip('"')
                if current_track is not None:
                    current_track["title"] = value
                else:
                    global_title = value
            elif upper.startswith("FILE "):
                tokens = _cue_tokens(line)
                if len(tokens) >= 2:
                    file_ref = tokens[1]
                    current_file = _resolve_cue_audio_file(cue_dir, file_ref)
            elif upper.startswith("TRACK "):
                tokens = _cue_tokens(line)
                if len(tokens) >= 2:
                    try:
                        number = int(tokens[1])
                    except Exception:
                        number = len(tracks) + 1
                    current_track = {
                        "number": number,
                        "title": "",
                        "performer": "",
                        "audio_path": current_file,
                        "start": None,
                    }
                    tracks.append(current_track)
            elif upper.startswith("INDEX 01 ") and current_track is not None:
                tokens = _cue_tokens(line)
                if len(tokens) >= 3:
                    current_track["start"] = _cue_time_to_seconds(tokens[2])
        except Exception:
            continue

    valid = []
    for track in tracks:
        audio_path = os.path.realpath(str(track.get("audio_path") or ""))
        if not audio_path or not os.path.isfile(audio_path):
            continue
        if os.path.splitext(audio_path)[1].lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            continue
        if not any(_path_inside_root(audio_path, root) for root in roots):
            continue
        if track.get("start") is None:
            continue
        valid.append(track)

    if not valid:
        return []

    by_audio = {}
    for track in valid:
        by_audio.setdefault(os.path.realpath(track["audio_path"]), []).append(track)

    out = []
    for audio_path, audio_tracks in by_audio.items():
        audio_tracks.sort(key=lambda item: (float(item.get("start") or 0), int(item.get("number") or 0)))
        parent = probe_lossless_file(audio_path)
        if parent is None:
            continue
        parent_duration = float(parent.get("duration") or 0)
        stat = os.stat(audio_path)
        cue_stat = os.stat(cue_path)
        album_title = global_title or parent.get("album") or os.path.basename(os.path.dirname(audio_path)) or "Local File"
        album_artist = global_performer or parent.get("album_artist") or parent.get("artist") or ""
        for idx, track in enumerate(audio_tracks):
            start = float(track.get("start") or 0)
            if idx + 1 < len(audio_tracks):
                end = float(audio_tracks[idx + 1].get("start") or 0)
            else:
                end = parent_duration if parent_duration > start else 0
            duration = int(round(max(0, end - start))) if end else 0
            title = track.get("title") or "Track %02d" % int(track.get("number") or idx + 1)
            artist = track.get("performer") or global_performer or parent.get("artist") or album_artist
            row = {
                "id": _cue_track_id(cue_path, audio_path, track.get("number")),
                "root": next((root for root in roots if _path_inside_root(audio_path, root)), ""),
                "path": _cue_virtual_path(cue_path, audio_path, track.get("number")),
                "uri": Path(audio_path).as_uri(),
                "title": title,
                "artist": artist or "",
                "album_artist": album_artist or "",
                "album": album_title,
                "compilation": 0,
                "track_number": int(track.get("number") or idx + 1),
                "disc_number": None,
                "duration": duration,
                "sample_rate": parent.get("sample_rate"),
                "bit_depth": parent.get("bit_depth"),
                "channels": parent.get("channels"),
                "codec": parent.get("codec") or _codec_for_extension(audio_path),
                "file_size": int(stat.st_size),
                "mtime": max(float(stat.st_mtime), float(cue_stat.st_mtime)),
                "metadata_version": LOCAL_METADATA_VERSION,
                "scanned_at": time.time(),
                "is_cue_track": 1,
                "cue_path": os.path.realpath(cue_path),
                "cue_audio_path": audio_path,
                "cue_track_number": int(track.get("number") or idx + 1),
                "cue_start_seconds": start,
                "cue_end_seconds": end or None,
            }
            out.append(row)
    return out


def _row_from_file(real_path, root, stat_result=None):
    stat = stat_result or os.stat(real_path)
    probed = probe_lossless_file(real_path)
    if probed is None:
        return None
    title = os.path.splitext(os.path.basename(real_path))[0].replace("_", " ").strip()
    album_dir = os.path.basename(os.path.dirname(real_path)).strip()
    artist_dir = os.path.basename(os.path.dirname(os.path.dirname(real_path))).strip()
    return {
        "id": _track_id_for_path(real_path),
        "root": root,
        "path": real_path,
        "uri": Path(real_path).as_uri(),
        "title": probed.get("title") or title or os.path.basename(real_path),
        "artist": probed.get("artist") or artist_dir or "Local",
        "album_artist": probed.get("album_artist") or "",
        "album": probed.get("album") or album_dir or "Local File",
        "compilation": int(probed.get("compilation") or 0),
        "track_number": probed.get("track_number"),
        "disc_number": probed.get("disc_number"),
        "duration": int(probed.get("duration") or 0),
        "sample_rate": probed.get("sample_rate"),
        "bit_depth": probed.get("bit_depth"),
        "channels": probed.get("channels"),
        "codec": probed.get("codec") or _codec_for_extension(real_path),
        "file_size": int(stat.st_size),
        "mtime": float(stat.st_mtime),
        "metadata_version": LOCAL_METADATA_VERSION,
        "scanned_at": time.time(),
    }


class LocalLibraryIndex:
    def __init__(self, roots=None, db_path=None):
        self.roots = _normalise_roots(roots)
        self.db_path = os.path.realpath(db_path or local_library_db_path())
        _assert_db_outside_roots(self.db_path, self.roots)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with _INIT_LOCK:
            if self.db_path not in _INITIALIZED_DBS:
                self._init_db()
                _INITIALIZED_DBS.add(self.db_path)

    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=SQLITE_TIMEOUT_SECONDS)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = %d" % SQLITE_BUSY_TIMEOUT_MS)
        return con

    def _raise_if_rebuild_running(self):
        if local_library_rebuild_running():
            raise LocalLibraryBusyError("local_library_rebuild_running")

    def _init_db(self):
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS local_tracks (
                  id TEXT PRIMARY KEY,
                  root TEXT NOT NULL,
                  path TEXT NOT NULL UNIQUE,
                  uri TEXT NOT NULL,
                  title TEXT NOT NULL,
                  artist TEXT NOT NULL,
                  album TEXT NOT NULL,
                  duration INTEGER NOT NULL DEFAULT 0,
                  sample_rate INTEGER,
                  bit_depth INTEGER,
                  channels INTEGER,
                  codec TEXT NOT NULL,
                  file_size INTEGER NOT NULL,
                  mtime REAL NOT NULL,
                  scanned_at REAL NOT NULL
                )
                """
            )
            existing_cols = {
                row["name"] for row in con.execute("PRAGMA table_info(local_tracks)")
            }
            migrations = (
                ("album_artist", "TEXT"),
                ("compilation", "INTEGER NOT NULL DEFAULT 0"),
                ("track_number", "INTEGER"),
                ("disc_number", "INTEGER"),
                ("metadata_version", "INTEGER NOT NULL DEFAULT 0"),
                ("is_cue_track", "INTEGER NOT NULL DEFAULT 0"),
                ("cue_path", "TEXT"),
                ("cue_audio_path", "TEXT"),
                ("cue_track_number", "INTEGER"),
                ("cue_start_seconds", "REAL"),
                ("cue_end_seconds", "REAL"),
            )
            for col_name, col_type in migrations:
                if col_name not in existing_cols:
                    con.execute("ALTER TABLE local_tracks ADD COLUMN %s %s" % (col_name, col_type))
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_local_tracks_artist_album "
                "ON local_tracks(artist, album)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_local_tracks_album_artist_album "
                "ON local_tracks(album_artist, album)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_local_tracks_title ON local_tracks(title)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_local_tracks_mtime ON local_tracks(mtime)"
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS local_scan_meta (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                )
                """
            )

    def _recreate_index_files(self):
        data_dir = os.path.realpath(get_data_dir())
        db_path = os.path.realpath(self.db_path)
        if db_path != os.path.join(data_dir, DB_FILENAME):
            raise RuntimeError("refusing to rebuild unexpected local library database path")
        _assert_db_outside_roots(db_path, self.roots)
        for path in (db_path, db_path + "-wal", db_path + "-shm", db_path + "-journal"):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except FileNotFoundError:
                pass
        with _INIT_LOCK:
            _INITIALIZED_DBS.discard(db_path)
            self._init_db()
            _INITIALIZED_DBS.add(db_path)

    def _set_meta(self, con, key, value):
        if not isinstance(value, str):
            value = json.dumps(value, sort_keys=True)
        con.execute(
            """
            INSERT INTO local_scan_meta(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(key), str(value)),
        )

    def _upsert_track(self, con, row):
        row = dict(row)
        row.setdefault("is_cue_track", 0)
        row.setdefault("cue_path", None)
        row.setdefault("cue_audio_path", None)
        row.setdefault("cue_track_number", None)
        row.setdefault("cue_start_seconds", None)
        row.setdefault("cue_end_seconds", None)
        con.execute(
            """
            INSERT INTO local_tracks (
              id, root, path, uri, title, artist, album_artist, album,
              compilation, track_number, disc_number, duration,
              sample_rate, bit_depth, channels, codec, file_size, mtime,
              metadata_version, scanned_at
              , is_cue_track, cue_path, cue_audio_path, cue_track_number,
              cue_start_seconds, cue_end_seconds
            ) VALUES (
              :id, :root, :path, :uri, :title, :artist, :album_artist, :album,
              :compilation, :track_number, :disc_number, :duration,
              :sample_rate, :bit_depth, :channels, :codec, :file_size, :mtime,
              :metadata_version, :scanned_at,
              COALESCE(:is_cue_track, 0), :cue_path, :cue_audio_path, :cue_track_number,
              :cue_start_seconds, :cue_end_seconds
            )
            ON CONFLICT(path) DO UPDATE SET
              id=excluded.id,
              root=excluded.root,
              uri=excluded.uri,
              title=excluded.title,
              artist=excluded.artist,
              album_artist=excluded.album_artist,
              album=excluded.album,
              compilation=excluded.compilation,
              track_number=excluded.track_number,
              disc_number=excluded.disc_number,
              duration=excluded.duration,
              sample_rate=excluded.sample_rate,
              bit_depth=excluded.bit_depth,
              channels=excluded.channels,
              codec=excluded.codec,
              file_size=excluded.file_size,
              mtime=excluded.mtime,
              metadata_version=excluded.metadata_version,
              scanned_at=excluded.scanned_at,
              is_cue_track=excluded.is_cue_track,
              cue_path=excluded.cue_path,
              cue_audio_path=excluded.cue_audio_path,
              cue_track_number=excluded.cue_track_number,
              cue_start_seconds=excluded.cue_start_seconds,
              cue_end_seconds=excluded.cue_end_seconds
            """,
            row,
        )

    def _folder_audio_and_cue_paths(self, dirpath, filenames, root):
        audio_paths = []
        cue_paths = []
        for filename in sorted(filenames, key=lambda item: item.casefold()):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED_AUDIO_EXTENSIONS and ext != CUE_EXTENSION:
                continue
            real_path = os.path.realpath(os.path.join(dirpath, filename))
            if not _path_inside_root(real_path, root):
                continue
            if ext == CUE_EXTENSION:
                cue_paths.append(real_path)
            else:
                if ext in ALAC_EXTENSIONS and probe_lossless_file(real_path) is None:
                    continue
                audio_paths.append(real_path)
        return audio_paths, cue_paths

    def _filter_walk_dirnames(self, dirpath, dirnames, root):
        kept = []
        skipped = 0
        for dirname in dirnames:
            real_path = os.path.realpath(os.path.join(dirpath, dirname))
            if not _path_inside_root(real_path, root):
                continue
            if _is_ignored_system_dir_name(dirname) or _path_has_ignored_system_dir(real_path):
                skipped += 1
                continue
            kept.append(dirname)
        dirnames[:] = kept
        return skipped

    def _delete_ignored_system_rows(self, con):
        deleted = 0
        rows = con.execute(
            """
            SELECT path, cue_path, cue_audio_path
            FROM local_tracks
            """
        ).fetchall()
        for row in rows:
            candidates = [
                row["path"] or "",
                row["cue_path"] if "cue_path" in row.keys() else "",
                row["cue_audio_path"] if "cue_audio_path" in row.keys() else "",
            ]
            storage_path = os.path.realpath(candidates[2] or str(candidates[0]).split("::cue:", 1)[0])
            if not any(_path_inside_root(storage_path, root) for root in self.roots):
                continue
            if not any(_path_has_ignored_system_dir(path) for path in candidates):
                continue
            con.execute("DELETE FROM local_tracks WHERE path = ?", (row["path"],))
            deleted += 1
        return deleted

    def _delete_ignored_cue_rows(self, con, cue_path):
        cue_path = os.path.realpath(str(cue_path or ""))
        cur = con.execute(
            """
            DELETE FROM local_tracks
            WHERE cue_path = ?
               OR instr(path, '::cue:' || ? || ':') > 0
            """,
            (cue_path, cue_path),
        )
        return int(cur.rowcount or 0)

    def _delete_stale_cue_virtual_rows(self, con, seen_paths):
        deleted = 0
        rows = con.execute(
            """
            SELECT path, cue_audio_path
            FROM local_tracks
            WHERE COALESCE(is_cue_track, 0) = 1
               OR path LIKE '%::cue:%'
            """
        ).fetchall()
        for row in rows:
            db_path = os.path.realpath(row["path"])
            cue_audio = row["cue_audio_path"] if "cue_audio_path" in row.keys() else None
            storage_path = os.path.realpath(cue_audio or db_path)
            if not any(_path_inside_root(storage_path, root) for root in self.roots):
                continue
            if db_path in seen_paths:
                continue
            con.execute("DELETE FROM local_tracks WHERE path = ?", (row["path"],))
            deleted += 1
        return deleted

    def _collect_seen_paths(self):
        seen_paths = set()
        for root in self.roots:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                if _path_has_ignored_system_dir(dirpath):
                    dirnames[:] = []
                    continue
                self._filter_walk_dirnames(dirpath, dirnames, root)
                folder_audio_paths, folder_cue_paths = self._folder_audio_and_cue_paths(dirpath, filenames, root)
                cue_paths_to_parse = folder_cue_paths if len(folder_audio_paths) <= 1 else []
                for filename in filenames:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext not in SUPPORTED_AUDIO_EXTENSIONS and ext != CUE_EXTENSION:
                        continue
                    real_path = os.path.realpath(os.path.join(dirpath, filename))
                    if _path_inside_root(real_path, root):
                        if ext in ALAC_EXTENSIONS and probe_lossless_file(real_path) is None:
                            continue
                        seen_paths.add(real_path)
                        if ext == CUE_EXTENSION and real_path in cue_paths_to_parse:
                            try:
                                for row in _parse_cue_file(real_path, self.roots):
                                    if row.get("path"):
                                        seen_paths.add(os.path.realpath(row.get("path")))
                                    if row.get("cue_audio_path"):
                                        seen_paths.add(os.path.realpath(row.get("cue_audio_path")))
                            except Exception:
                                pass
        return seen_paths

    def _stale_paths(self, con, seen_paths):
        stale_paths = []
        for row in con.execute("SELECT path, cue_path, cue_audio_path FROM local_tracks"):
            db_path = os.path.realpath(row["path"])
            cue_audio = row["cue_audio_path"] if "cue_audio_path" in row.keys() else None
            storage_path = os.path.realpath(cue_audio or db_path)
            if not any(_path_inside_root(storage_path, root) for root in self.roots):
                continue
            if db_path in seen_paths:
                continue
            stale_paths.append(db_path)
        return stale_paths

    def scan(self, rebuild=False, lock_acquired=False):
        if not lock_acquired and not _SCAN_LOCK.acquire(blocking=False):
            state = _scan_state_snapshot()
            return {
                "ok": False,
                "error": "local_library_scan_running",
                "scan_running": True,
                "rebuild_running": bool(state.get("rebuild_running")),
                "maintenance_mode": state.get("maintenance_mode"),
                "scan_started_at": state.get("scan_started_at"),
                "scan_finished_at": state.get("scan_finished_at"),
                "last_scan_at": state.get("last_scan_at"),
                "last_scan_stats": state.get("last_scan_stats"),
                "last_scan_error": state.get("last_scan_error"),
                "db_path": self.db_path,
                "roots": list(self.roots),
            }
        stats = {
            "ok": True,
            "db_path": self.db_path,
            "roots": list(self.roots),
            "scanned": 0,
            "added": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped": 0,
            "lossy_audio_ignored": 0,
            "lossy_audio_by_format": {},
            "lossy_audio_sample": [],
            "lossless_scan_notice": LOSSLESS_SCAN_NOTICE,
            "unsupported_files_ignored": 0,
            "stale": 0,
            "cue_files_seen": 0,
            "cue_files_parsed": 0,
            "cue_tracks_added": 0,
            "cue_tracks_updated": 0,
            "cue_errors": 0,
            "ignored_system_dirs": 0,
            "ignored_system_rows_deleted": 0,
            "errors": [],
        }
        started_at = time.time()
        _update_scan_state(
            scan_running=True,
            rebuild_running=bool(rebuild),
            maintenance_mode="local_library_rebuild" if rebuild else None,
            scan_started_at=started_at,
            scan_finished_at=None,
            last_scan_error=None,
        )
        con = None
        pending_writes = 0
        seen_paths = set()
        try:
            con = self._connect()
            self._set_meta(con, "scan_started_at", started_at)
            self._set_meta(con, "last_scan_error", "")
            ignored_rows_deleted = self._delete_ignored_system_rows(con)
            if ignored_rows_deleted:
                stats["ignored_system_rows_deleted"] = ignored_rows_deleted
            con.commit()
            for root in self.roots:
                for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                    if _path_has_ignored_system_dir(dirpath):
                        dirnames[:] = []
                        continue
                    stats["ignored_system_dirs"] += self._filter_walk_dirnames(dirpath, dirnames, root)
                    cue_audio_paths = set()
                    folder_audio_paths, folder_cue_paths = self._folder_audio_and_cue_paths(dirpath, filenames, root)
                    parse_cue_paths = folder_cue_paths if len(folder_audio_paths) <= 1 else []
                    ignored_cue_paths = set(folder_cue_paths) - set(parse_cue_paths)
                    for cue_path in sorted(ignored_cue_paths):
                        seen_paths.add(cue_path)
                        stats["cue_files_seen"] += 1
                        deleted = self._delete_ignored_cue_rows(con, cue_path)
                        if deleted:
                            pending_writes += deleted
                    for cue_path in parse_cue_paths:
                        if not _path_inside_root(cue_path, root):
                            stats["skipped"] += 1
                            continue
                        seen_paths.add(cue_path)
                        stats["cue_files_seen"] += 1
                        try:
                            cue_rows = _parse_cue_file(cue_path, self.roots)
                            if not cue_rows:
                                stats["cue_errors"] += 1
                                stats["errors"].append({"path": cue_path, "error": "cue_no_valid_tracks"})
                                continue
                            stats["cue_files_parsed"] += 1
                            audio_paths = {
                                os.path.realpath(row.get("cue_audio_path") or "")
                                for row in cue_rows if row.get("cue_audio_path")
                            }
                            for audio_path in audio_paths:
                                cue_audio_paths.add(audio_path)
                                seen_paths.add(audio_path)
                                con.execute(
                                    "DELETE FROM local_tracks WHERE path = ? AND COALESCE(is_cue_track, 0) = 0",
                                    (audio_path,),
                                )
                                pending_writes += 1
                            for row in cue_rows:
                                seen_paths.add(os.path.realpath(row.get("path") or ""))
                                previous = con.execute(
                                    """
                                    SELECT file_size, mtime, metadata_version
                                    FROM local_tracks
                                    WHERE path = ?
                                    """,
                                    (row.get("path"),),
                                ).fetchone()
                                self._upsert_track(con, row)
                                pending_writes += 1
                                stats["scanned"] += 1
                                if previous is None:
                                    stats["added"] += 1
                                    stats["cue_tracks_added"] += 1
                                elif (
                                    int(previous["file_size"]) == int(row.get("file_size") or 0)
                                    and float(previous["mtime"]) == float(row.get("mtime") or 0)
                                    and int(previous["metadata_version"] or 0) >= LOCAL_METADATA_VERSION
                                ):
                                    stats["unchanged"] += 1
                                else:
                                    stats["updated"] += 1
                                    stats["cue_tracks_updated"] += 1
                                if pending_writes >= SCAN_COMMIT_BATCH_SIZE:
                                    con.commit()
                                    pending_writes = 0
                        except Exception as exc:
                            if _is_sqlite_busy(exc):
                                raise
                            stats["cue_errors"] += 1
                            stats["errors"].append({"path": cue_path, "error": str(exc)})
                    for filename in filenames:
                        ext = os.path.splitext(filename)[1].lower()
                        real_path = os.path.realpath(os.path.join(dirpath, filename))
                        if ext not in SUPPORTED_AUDIO_EXTENSIONS:
                            if ext != CUE_EXTENSION:
                                if not _record_lossy_audio_ignored(stats, real_path):
                                    stats["unsupported_files_ignored"] += 1
                                    stats["skipped"] += 1
                            continue
                        if not _path_inside_root(real_path, root):
                            stats["skipped"] += 1
                            continue
                        if real_path in cue_audio_paths:
                            continue
                        if ext in ALAC_EXTENSIONS and probe_lossless_file(real_path) is None:
                            if ext == ".m4a":
                                _record_lossy_audio_ignored(stats, real_path)
                            else:
                                stats["skipped"] += 1
                            continue
                        seen_paths.add(real_path)
                        try:
                            stat = os.stat(real_path)
                            previous = con.execute(
                                """
                                SELECT file_size, mtime, metadata_version, album_artist,
                                       compilation, track_number, disc_number
                                FROM local_tracks
                                WHERE path = ?
                                """,
                                (real_path,),
                            ).fetchone()
                            stats["scanned"] += 1
                            if previous is None:
                                row = _row_from_file(real_path, root, stat)
                                if row is None:
                                    stats["skipped"] += 1
                                    continue
                                self._upsert_track(con, row)
                                pending_writes += 1
                                stats["added"] += 1
                            elif (
                                int(previous["file_size"]) == int(stat.st_size)
                                and float(previous["mtime"]) == float(stat.st_mtime)
                                and int(previous["metadata_version"] or 0) >= LOCAL_METADATA_VERSION
                                and previous["album_artist"] is not None
                                and previous["compilation"] is not None
                            ):
                                stats["unchanged"] += 1
                            else:
                                row = _row_from_file(real_path, root, stat)
                                if row is None:
                                    stats["skipped"] += 1
                                    continue
                                self._upsert_track(con, row)
                                pending_writes += 1
                                stats["updated"] += 1
                            if pending_writes >= SCAN_COMMIT_BATCH_SIZE:
                                con.commit()
                                pending_writes = 0
                        except Exception as exc:
                            if _is_sqlite_busy(exc):
                                raise
                            stats["errors"].append({"path": real_path, "error": str(exc)})
            if pending_writes:
                con.commit()
                pending_writes = 0
            deleted_stale_cue_rows = self._delete_stale_cue_virtual_rows(con, seen_paths)
            if deleted_stale_cue_rows:
                con.commit()
            stale_paths = self._stale_paths(con, seen_paths)
            stats["stale"] = len(stale_paths)
            if deleted_stale_cue_rows:
                stats["stale_cue_virtual_deleted"] = deleted_stale_cue_rows
            stale_sample = stale_paths[:10]
            if stale_sample:
                stats["stale_sample"] = stale_sample
            finished_at = time.time()
            self._set_meta(con, "last_scan_at", started_at)
            self._set_meta(con, "scan_finished_at", finished_at)
            self._set_meta(con, "last_scan_stats", stats)
            self._set_meta(con, "last_scan_error", "")
            con.commit()
            _update_scan_state(
                scan_running=False,
                rebuild_running=False,
                maintenance_mode=None,
                scan_finished_at=finished_at,
                last_scan_at=started_at,
                last_scan_stats=stats,
                last_scan_error=None,
            )
            stats["scan_running"] = False
            stats["rebuild_running"] = False
            stats["maintenance_mode"] = None
            stats["scan_started_at"] = started_at
            stats["scan_finished_at"] = finished_at
            stats["last_scan_at"] = started_at
            stats["last_scan_error"] = None
            return stats
        except Exception as exc:
            if con is not None:
                try:
                    con.rollback()
                except Exception:
                    pass
            finished_at = time.time()
            error = "local_library_busy" if _is_sqlite_busy(exc) else str(exc)
            if con is not None:
                try:
                    self._set_meta(con, "scan_finished_at", finished_at)
                    self._set_meta(con, "last_scan_error", error)
                    con.commit()
                except Exception:
                    pass
            _update_scan_state(
                scan_running=False,
                rebuild_running=False,
                maintenance_mode=None,
                scan_finished_at=finished_at,
                last_scan_error=error,
            )
            if _is_sqlite_busy(exc):
                raise LocalLibraryBusyError(error)
            raise
        finally:
            if con is not None:
                con.close()
            _SCAN_LOCK.release()

    def rebuild_and_scan(self):
        if not _SCAN_LOCK.acquire(blocking=False):
            state = _scan_state_snapshot()
            return {
                "ok": False,
                "error": "local_library_scan_running" if state.get("scan_running") else "local_library_busy",
                "scan_running": bool(state.get("scan_running")),
                "rebuild_running": bool(state.get("rebuild_running")),
                "maintenance_mode": state.get("maintenance_mode"),
                "scan_started_at": state.get("scan_started_at"),
                "scan_finished_at": state.get("scan_finished_at"),
                "last_scan_stats": state.get("last_scan_stats"),
                "last_scan_error": state.get("last_scan_error"),
                "db_path": self.db_path,
                "roots": list(self.roots),
            }
        started_at = time.time()
        _update_scan_state(
            scan_running=True,
            rebuild_running=True,
            maintenance_mode="local_library_rebuild",
            scan_started_at=started_at,
            scan_finished_at=None,
            last_scan_error=None,
        )
        try:
            self._recreate_index_files()
        except Exception as exc:
            finished_at = time.time()
            error = "local_library_busy" if _is_sqlite_busy(exc) else str(exc)
            _update_scan_state(
                scan_running=False,
                rebuild_running=False,
                maintenance_mode=None,
                scan_finished_at=finished_at,
                last_scan_error=error,
            )
            _SCAN_LOCK.release()
            if _is_sqlite_busy(exc):
                raise LocalLibraryBusyError(error)
            raise
        return self.scan(rebuild=True, lock_acquired=True)

    def cleanup_stale(self):
        if not _SCAN_LOCK.acquire(blocking=False):
            state = _scan_state_snapshot()
            scan_running = bool(state.get("scan_running"))
            return {
                "ok": False,
                "error": "local_library_scan_running" if scan_running else "local_library_busy",
                "db_path": self.db_path,
                "roots": list(self.roots),
                "stale_before": 0,
                "deleted": 0,
                "scan_running": scan_running,
            }
        con = None
        try:
            seen_paths = self._collect_seen_paths()
            con = self._connect()
            ignored_deleted = self._delete_ignored_system_rows(con)
            stale_paths = self._stale_paths(con, seen_paths)
            for path in stale_paths:
                con.execute("DELETE FROM local_tracks WHERE path = ?", (path,))
            con.commit()
            out = {
                "ok": True,
                "db_path": self.db_path,
                "roots": list(self.roots),
                "stale_before": len(stale_paths),
                "deleted": len(stale_paths) + ignored_deleted,
                "ignored_system_rows_deleted": ignored_deleted,
                "scan_running": False,
            }
            if stale_paths:
                out["deleted_sample"] = stale_paths[:10]
            return out
        except Exception as exc:
            if con is not None:
                try:
                    con.rollback()
                except Exception:
                    pass
            if _is_sqlite_busy(exc):
                raise LocalLibraryBusyError("local_library_busy")
            raise
        finally:
            if con is not None:
                con.close()
            _SCAN_LOCK.release()

    def status(self):
        state = _scan_state_snapshot()
        try:
            with self._connect() as con:
                count = con.execute("SELECT COUNT(*) AS c FROM local_tracks").fetchone()["c"]
                meta = {
                    row["key"]: row["value"]
                    for row in con.execute("SELECT key, value FROM local_scan_meta")
                }
        except Exception as exc:
            if not _is_sqlite_busy(exc) and not local_library_rebuild_running():
                raise
            return {
                "ok": True,
                "busy": True,
                "error": "local_library_rebuild_running" if local_library_rebuild_running() else "local_library_busy",
                "db_path": self.db_path,
                "roots": list(self.roots),
                "track_count": None,
                "scan_running": bool(state.get("scan_running")),
                "rebuild_running": bool(state.get("rebuild_running")),
                "maintenance_mode": state.get("maintenance_mode"),
                "scan_started_at": state.get("scan_started_at"),
                "scan_finished_at": state.get("scan_finished_at"),
                "last_scan_at": state.get("last_scan_at"),
                "last_scan_stats": state.get("last_scan_stats"),
                "last_scan_error": state.get("last_scan_error"),
            }
        last_scan_stats = None
        if meta.get("last_scan_stats"):
            try:
                last_scan_stats = json.loads(meta["last_scan_stats"])
            except Exception:
                last_scan_stats = None
        last_scan_error = meta.get("last_scan_error") or state.get("last_scan_error")
        scan_started_at = (
            state.get("scan_started_at")
            if state.get("scan_running")
            else float(meta["scan_started_at"]) if meta.get("scan_started_at") else state.get("scan_started_at")
        )
        scan_finished_at = (
            float(meta["scan_finished_at"]) if meta.get("scan_finished_at") else state.get("scan_finished_at")
        )
        last_scan_at = (
            float(meta["last_scan_at"]) if meta.get("last_scan_at") else state.get("last_scan_at")
        )
        return {
            "ok": True,
            "db_path": self.db_path,
            "roots": list(self.roots),
            "track_count": int(count),
            "scan_running": bool(state.get("scan_running")),
            "rebuild_running": bool(state.get("rebuild_running")),
            "maintenance_mode": state.get("maintenance_mode"),
            "scan_started_at": scan_started_at,
            "scan_finished_at": scan_finished_at,
            "last_scan_at": last_scan_at,
            "last_scan_stats": last_scan_stats,
            "last_scan_error": last_scan_error or None,
        }

    def tracks(self, limit=1000):
        self._raise_if_rebuild_running()
        limit = _coerce_limit(limit, default=1000, maximum=5000)
        try:
            with self._connect() as con:
                rows = con.execute(
                    """
                    SELECT id, root, path, uri, title, artist, album_artist, album,
                           compilation, track_number, disc_number, duration,
                           sample_rate, bit_depth, channels, codec, file_size, mtime,
                           metadata_version, scanned_at,
                           is_cue_track, cue_path, cue_audio_path, cue_track_number,
                           cue_start_seconds, cue_end_seconds
                    FROM local_tracks
                    ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, title COLLATE NOCASE, path
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except Exception as exc:
            if not _is_sqlite_busy(exc):
                raise
            state = _scan_state_snapshot()
            return {
                "ok": False,
                "error": "local_library_busy",
                "busy": True,
                "scan_running": bool(state.get("scan_running")),
                "db_path": self.db_path,
                "count": 0,
                "tracks": [],
            }
        return {
            "ok": True,
            "db_path": self.db_path,
            "scan_running": bool(_scan_state_snapshot().get("scan_running")),
            "count": len(rows),
            "tracks": [dict(row) for row in rows],
        }

    def track_by_id(self, track_id):
        self._raise_if_rebuild_running()
        track_id = str(track_id or "").strip()
        if not track_id:
            return None
        try:
            with self._connect() as con:
                row = con.execute(
                    """
                    SELECT id, root, path, uri, title, artist, album_artist, album,
                           compilation, track_number, disc_number, duration,
                           sample_rate, bit_depth, channels, codec, file_size, mtime,
                           metadata_version, scanned_at,
                           is_cue_track, cue_path, cue_audio_path, cue_track_number,
                           cue_start_seconds, cue_end_seconds
                    FROM local_tracks
                    WHERE id = ?
                    """,
                    (track_id,),
                ).fetchone()
        except Exception as exc:
            if not _is_sqlite_busy(exc):
                raise
            raise LocalLibraryBusyError("local_library_busy")
        return dict(row) if row else None

    def artwork_file(self, path):
        if _local_artwork_lookup_disabled():
            raise FileNotFoundError("local artwork lookup disabled for autofs-backed network roots")
        real_path, mime = _validate_artwork_path(path, self.roots)
        return {
            "path": real_path,
            "mime": mime,
            "size": os.path.getsize(real_path),
        }

    def embedded_artwork_file(self, path):
        if _local_artwork_lookup_disabled():
            raise FileNotFoundError("local embedded artwork lookup disabled for autofs-backed network roots")
        real_path, mime = _embedded_artwork_file_for_track_path(path, self.roots)
        return {
            "path": real_path,
            "mime": mime,
            "size": os.path.getsize(real_path),
        }

    def artists(self, limit=500):
        self._raise_if_rebuild_running()
        limit = _coerce_limit(limit, default=500, maximum=2000)
        try:
            with self._connect() as con:
                rows = con.execute(
                    """
                    SELECT artist,
                           COUNT(*) AS track_count,
                           COUNT(DISTINCT album) AS album_count,
                           COALESCE(SUM(duration), 0) AS duration
                    FROM local_tracks
                    GROUP BY artist
                    ORDER BY artist COLLATE NOCASE
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except Exception as exc:
            if not _is_sqlite_busy(exc):
                raise
            raise LocalLibraryBusyError("local_library_busy")
        return {
            "ok": True,
            "db_path": self.db_path,
            "scan_running": bool(_scan_state_snapshot().get("scan_running")),
            "count": len(rows),
            "artists": [dict(row) for row in rows],
        }

    def albums(self, limit=500, artist=None, sort="latest"):
        self._raise_if_rebuild_running()
        limit = _coerce_limit(limit, default=500, maximum=2000)
        sort = _coerce_album_sort(sort)
        artist = str(artist or "").strip()
        where = ""
        params = []
        if artist:
            where = "WHERE artist = ?"
            params.append(artist)
        try:
            with self._connect() as con:
	                rows = con.execute(
	                    """
	                    SELECT id, artist, album_artist, album, compilation, path, cue_audio_path,
	                           duration, sample_rate, bit_depth, codec, mtime, scanned_at
                    FROM local_tracks
                    {where}
                    ORDER BY album COLLATE NOCASE, path COLLATE NOCASE
                    """.format(where=where),
                    params,
                ).fetchall()
        except Exception as exc:
            if not _is_sqlite_busy(exc):
                raise
            raise LocalLibraryBusyError("local_library_busy")
        rows = _filter_rows_to_configured_roots([dict(row) for row in rows], self.roots)
        albums = self._album_groups_from_rows(
            rows,
            limit=limit,
            hide_single_track_groups=True,
            sort=sort,
        )
        return {
            "ok": True,
            "db_path": self.db_path,
            "scan_running": bool(_scan_state_snapshot().get("scan_running")),
            "count": len(albums),
            "sort": sort,
            "albums": albums,
        }

    def _album_groups_from_rows(self, rows, limit=None, hide_single_track_groups=False, sort="artist_album"):
        collection_info = _build_collection_folder_info(rows)
        groups = {}
        for row in rows or []:
            key, album = _album_group_key(row, collection_info)
            storage_path = _track_storage_path(row)
            folder = _album_root_folder_for_path(storage_path)
            group = groups.setdefault(key, {
                "album": album,
                "folder": folder,
                "paths": [],
                "album_artist": "" if key[0] == "collection_folder" else str(row.get("album_artist") or "").strip(),
                "compilation": int(row.get("compilation") or 0),
                "artists": [],
                "quality_tracks": [],
                "track_count": 0,
                "duration": 0,
                "first_track_id": row.get("id") or "",
                "latest_mtime": 0.0,
                "latest_scanned_at": 0.0,
            })
            artist = str(row.get("artist") or "").strip()
            if artist:
                group["artists"].append(artist)
            if storage_path:
                group["paths"].append(storage_path)
            group["quality_tracks"].append({
                "codec": row.get("codec"),
                "bit_depth": row.get("bit_depth"),
                "sample_rate": row.get("sample_rate"),
            })
            group["track_count"] += 1
            group["duration"] += int(row.get("duration") or 0)
            try:
                group["latest_mtime"] = max(float(group.get("latest_mtime") or 0), float(row.get("mtime") or 0))
            except Exception:
                pass
            try:
                group["latest_scanned_at"] = max(float(group.get("latest_scanned_at") or 0), float(row.get("scanned_at") or 0))
            except Exception:
                pass
            if not group.get("first_track_id"):
                group["first_track_id"] = row.get("id") or ""

        albums = []
        for key, group in groups.items():
            if hide_single_track_groups and group["track_count"] <= 1:
                continue
            display_artist = _album_display_artist(group.get("artists"), group.get("album_artist"))
            artwork_url = _album_artwork_url_for_paths(group.get("paths"), self.roots)
            album_id = _album_id_for_group_key(key)
            albums.append({
                "album_id": album_id,
                "group_id": album_id,
                "artist": display_artist,
                "album_artist": display_artist,
                "album": group["album"],
                "track_count": group["track_count"],
                "duration": group["duration"],
                "first_track_id": group.get("first_track_id") or "",
                "artwork_url": artwork_url,
                "album_quality": _album_wall_quality_from_tracks(group.get("quality_tracks")),
                "latest_mtime": group.get("latest_mtime") or 0,
                "latest_scanned_at": group.get("latest_scanned_at") or 0,
            })
        if sort == "latest":
            albums.sort(key=lambda item: (
                -(float(item.get("latest_mtime") or item.get("latest_scanned_at") or 0)),
                str(item.get("album") or "").casefold(),
                str(item.get("artist") or "").casefold(),
                str(item.get("album_id") or ""),
            ))
        elif sort == "oldest":
            albums.sort(key=lambda item: (
                float(item.get("latest_mtime") or item.get("latest_scanned_at") or 0),
                str(item.get("album") or "").casefold(),
                str(item.get("artist") or "").casefold(),
                str(item.get("album_id") or ""),
            ))
        elif sort == "alpha_asc":
            albums.sort(key=lambda item: (
                str(item.get("album") or "").casefold(),
                str(item.get("artist") or "").casefold(),
                str(item.get("album_id") or ""),
            ))
        elif sort == "alpha_desc":
            albums.sort(key=lambda item: (
                str(item.get("album") or "").casefold(),
                str(item.get("artist") or "").casefold(),
                str(item.get("album_id") or ""),
            ), reverse=True)
        else:
            albums.sort(key=lambda item: (
                str(item.get("artist") or "").casefold(),
                str(item.get("album") or "").casefold(),
                str(item.get("album_id") or ""),
            ))
        if limit:
            albums = albums[:int(limit)]
        return albums

    def search(self, query="", limit=100):
        self._raise_if_rebuild_running()
        limit = _coerce_limit(limit, default=100, maximum=500)
        query = str(query or "").strip()
        if not query:
            return {
                "ok": True,
                "db_path": self.db_path,
                "scan_running": bool(_scan_state_snapshot().get("scan_running")),
                "query": query,
                "count": 0,
                "song_count": 0,
                "album_count": 0,
                "artist_count": 0,
                "songs": [],
                "tracks": [],
                "albums": [],
                "artists": [],
            }
        pattern = _like_pattern(query)
        try:
            with self._connect() as con:
                song_rows = con.execute(
                    """
                    SELECT id, root, path, uri, title, artist, album_artist, album,
                           compilation, track_number, disc_number, duration,
                           sample_rate, bit_depth, channels, codec, file_size, mtime,
                           metadata_version, scanned_at,
                           is_cue_track, cue_path, cue_audio_path, cue_track_number,
                           cue_start_seconds, cue_end_seconds
                    FROM local_tracks
                    WHERE title LIKE ? ESCAPE '\\'
                       OR artist LIKE ? ESCAPE '\\'
                       OR album LIKE ? ESCAPE '\\'
                       OR path LIKE ? ESCAPE '\\'
                    ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, title COLLATE NOCASE, path
                    LIMIT ?
                    """,
                    (pattern, pattern, pattern, pattern, limit),
                ).fetchall()
                album_rows = con.execute(
                    """
                    SELECT id, artist, album_artist, album, compilation, path, cue_audio_path, duration
                    FROM local_tracks
                    WHERE album LIKE ? ESCAPE '\\'
                       OR artist LIKE ? ESCAPE '\\'
                       OR path LIKE ? ESCAPE '\\'
                    ORDER BY album COLLATE NOCASE, path COLLATE NOCASE
                    """,
                    (pattern, pattern, pattern),
                ).fetchall()
                artist_rows = con.execute(
                    """
                    SELECT artist,
                           COUNT(*) AS track_count,
                           COUNT(DISTINCT album) AS album_count,
                           COALESCE(SUM(duration), 0) AS duration
                    FROM local_tracks
                    WHERE artist LIKE ? ESCAPE '\\'
                       OR path LIKE ? ESCAPE '\\'
                    GROUP BY artist
                    ORDER BY artist COLLATE NOCASE
                    LIMIT ?
                    """,
                    (pattern, pattern, limit),
                ).fetchall()
        except Exception as exc:
            if not _is_sqlite_busy(exc):
                raise
            raise LocalLibraryBusyError("local_library_busy")
        songs = _filter_rows_to_configured_roots([dict(row) for row in song_rows], self.roots)
        artwork_cache = {}
        for song in songs:
            try:
                storage_path = _track_storage_path(song)
                if not storage_path:
                    continue
                cache_key = os.path.dirname(str(storage_path)) or str(storage_path)
                if cache_key not in artwork_cache:
                    artwork_cache[cache_key] = _album_artwork_url_for_paths([storage_path], self.roots) or ""
                artwork_url = artwork_cache.get(cache_key) or ""
                if artwork_url:
                    song["artwork_url"] = artwork_url
                    song["cover"] = artwork_url
            except Exception:
                continue
        album_rows_filtered = _filter_rows_to_configured_roots([dict(row) for row in album_rows], self.roots)
        albums = self._album_groups_from_rows(album_rows_filtered, limit=limit)
        artists = [dict(row) for row in artist_rows]
        return {
            "ok": True,
            "db_path": self.db_path,
            "scan_running": bool(_scan_state_snapshot().get("scan_running")),
            "query": query,
            "count": len(songs),
            "song_count": len(songs),
            "album_count": len(albums),
            "artist_count": len(artists),
            "songs": songs,
            "tracks": songs,
            "albums": albums,
            "artists": artists,
        }

    def album_detail(self, artist=None, album=None, album_id=None):
        self._raise_if_rebuild_running()
        album_id = str(album_id or "").strip()
        artist = str(artist or "").strip()
        album = str(album or "").strip()
        try:
            with self._connect() as con:
                if album_id:
                    seed_rows = con.execute(
                        """
                        SELECT id, artist, album_artist, album, compilation, path, cue_audio_path, duration
                        FROM local_tracks
                        ORDER BY album COLLATE NOCASE, path COLLATE NOCASE
                        """
                    ).fetchall()
                    seed_dicts = [dict(row) for row in seed_rows]
                    collection_info = _build_collection_folder_info(seed_dicts)
                    match_key = None
                    seen = set()
                    for seed in seed_dicts:
                        key, _seed_album = _album_group_key(seed, collection_info)
                        if key in seen:
                            continue
                        seen.add(key)
                        if _album_id_for_group_key(key) == album_id:
                            match_key = key
                            break
                    if not match_key:
                        rows = []
                    else:
                        rows = con.execute(
                            """
                            SELECT id, root, path, uri, title, artist, album_artist, album,
                                   compilation, track_number, disc_number, duration,
                                   sample_rate, bit_depth, channels, codec, file_size, mtime,
                                   metadata_version, scanned_at,
                                   is_cue_track, cue_path, cue_audio_path, cue_track_number,
                                   cue_start_seconds, cue_end_seconds
                            FROM local_tracks
                            ORDER BY path COLLATE NOCASE
                            """
                        ).fetchall()
                        rows = [
                            row for row in rows
                            if _album_group_key(dict(row), collection_info)[0] == match_key
                        ]
                else:
                    seed_rows = con.execute(
                        """
                        SELECT id, artist, album_artist, album, compilation, path, cue_audio_path, duration
                        FROM local_tracks
                        WHERE album = ?
                          AND (? = '' OR artist = ?)
                        ORDER BY path COLLATE NOCASE
                        LIMIT 1
                        """,
                        (album, artist, artist),
                    ).fetchall()
                    all_seed_rows = con.execute(
                        """
                        SELECT id, artist, album_artist, album, compilation, path, cue_audio_path, duration
                        FROM local_tracks
                        ORDER BY album COLLATE NOCASE, path COLLATE NOCASE
                        """
                    ).fetchall()
                    collection_info = _build_collection_folder_info([dict(row) for row in all_seed_rows])
                    match_key = None
                    if seed_rows:
                        match_key = _album_group_key(dict(seed_rows[0]), collection_info)[0]
                    else:
                        seen = set()
                        for seed in [dict(row) for row in all_seed_rows]:
                            key, display_album = _album_group_key(seed, collection_info)
                            if key in seen:
                                continue
                            seen.add(key)
                            if display_album != album:
                                continue
                            group_rows = [
                                dict(row) for row in all_seed_rows
                                if _album_group_key(dict(row), collection_info)[0] == key
                            ]
                            display_artist = _album_display_artist(
                                [row.get("artist") for row in group_rows],
                                "" if key[0] == "collection_folder" else group_rows[0].get("album_artist") if group_rows else "",
                            )
                            if not artist or display_artist == artist:
                                match_key = key
                                break
                    if not match_key:
                        rows = []
                    else:
                        rows = con.execute(
                            """
                            SELECT id, root, path, uri, title, artist, album_artist, album,
                                   compilation, track_number, disc_number, duration,
                                   sample_rate, bit_depth, channels, codec, file_size, mtime,
                                   metadata_version, scanned_at,
                                   is_cue_track, cue_path, cue_audio_path, cue_track_number,
                                   cue_start_seconds, cue_end_seconds
                            FROM local_tracks
                            WHERE album = ?
                            ORDER BY path COLLATE NOCASE
                            """,
                            (album,),
                        ).fetchall()
                        if match_key and match_key[0] == "collection_folder":
                            rows = con.execute(
                                """
                                SELECT id, root, path, uri, title, artist, album_artist, album,
                                       compilation, track_number, disc_number, duration,
                                       sample_rate, bit_depth, channels, codec, file_size, mtime,
                                       metadata_version, scanned_at,
                                       is_cue_track, cue_path, cue_audio_path, cue_track_number,
                                       cue_start_seconds, cue_end_seconds
                                FROM local_tracks
                                ORDER BY path COLLATE NOCASE
                                """
                            ).fetchall()
                        rows = [
                            row for row in rows
                            if _album_group_key(dict(row), collection_info)[0] == match_key
                        ]
        except Exception as exc:
            if not _is_sqlite_busy(exc):
                raise
            raise LocalLibraryBusyError("local_library_busy")
        tracks = [_decorate_track_order(dict(row)) for row in rows]
        tracks.sort(key=_track_sort_key)
        artwork_url = None
        if tracks:
            artwork_url = _album_artwork_url_for_paths([_track_storage_path(track) for track in tracks], self.roots)
        detail_collection_info = _build_collection_folder_info(tracks)
        detail_key = _album_group_key(tracks[0], detail_collection_info)[0] if tracks else None
        detail_album = _album_group_key(tracks[0], detail_collection_info)[1] if tracks else album
        display_album = detail_album if tracks else album
        display_artist = _album_display_artist(
            [track.get("artist") for track in tracks],
            "" if detail_key and detail_key[0] == "collection_folder" else tracks[0].get("album_artist") if tracks else "",
        )
        resolved_album_id = _album_id_for_group_key(detail_key) if tracks and detail_key else album_id
        return {
            "ok": True,
            "db_path": self.db_path,
            "scan_running": bool(_scan_state_snapshot().get("scan_running")),
            "album_id": resolved_album_id,
            "group_id": resolved_album_id,
            "artist": display_artist,
            "album_artist": display_artist,
            "album": display_album,
            "artwork_url": artwork_url,
            "track_count": len(tracks),
            "duration": sum(int(track.get("duration") or 0) for track in tracks),
            "tracks": tracks,
        }

    def artist_detail(self, artist, limit=1000):
        self._raise_if_rebuild_running()
        artist = str(artist or "").strip()
        limit = _coerce_limit(limit, default=1000, maximum=5000)
        try:
            with self._connect() as con:
                album_rows = con.execute(
                    """
                    SELECT album,
                           COUNT(*) AS track_count,
                           COALESCE(SUM(duration), 0) AS duration,
                           MIN(id) AS first_track_id
                    FROM local_tracks
                    WHERE artist = ?
                    GROUP BY album
                    ORDER BY album COLLATE NOCASE
                    """,
                    (artist,),
                ).fetchall()
                track_rows = con.execute(
                    """
                    SELECT id, root, path, uri, title, artist, album_artist, album,
                           compilation, track_number, disc_number, duration,
                           sample_rate, bit_depth, channels, codec, file_size, mtime,
                           metadata_version, scanned_at,
                           is_cue_track, cue_path, cue_audio_path, cue_track_number,
                           cue_start_seconds, cue_end_seconds
                    FROM local_tracks
                    WHERE artist = ?
                    ORDER BY album COLLATE NOCASE, title COLLATE NOCASE, path
                    LIMIT ?
                    """,
                    (artist, limit),
                ).fetchall()
        except Exception as exc:
            if not _is_sqlite_busy(exc):
                raise
            raise LocalLibraryBusyError("local_library_busy")
        albums = [dict(row) for row in album_rows]
        tracks = [dict(row) for row in track_rows]
        return {
            "ok": True,
            "db_path": self.db_path,
            "scan_running": bool(_scan_state_snapshot().get("scan_running")),
            "artist": artist,
            "album_count": len(albums),
            "track_count": sum(int(album.get("track_count") or 0) for album in albums),
            "albums": albums,
            "tracks_count": len(tracks),
            "tracks": tracks,
        }
