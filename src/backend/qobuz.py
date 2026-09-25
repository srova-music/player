"""Isolated Qobuz browser-authentication and session support.

The Qobuz service mechanics are independently adapted from the MIT-licensed
``vicrodh/qbz`` project at commit
``aa5690e4491507976b56a982025eb4b38ec8e064``.  Relevant references are
``crates/qbz/src/auth.rs``, ``crates/qbzd/src/login.rs``,
``crates/qbz-qobuz/src/{bundle,client,auth}.rs``, and
``crates/qbz-models/src/types.rs``.

Authentication, catalog requests, normalized catalog/library/search lookups,
and the isolated CMAF delivery/decryption proof live here. Catalog routes, UI,
and player capabilities remain absent.
"""

import base64
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import stat
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit

import requests

from backend.qobuz_catalog import (
    QobuzCatalogClient,
    QobuzCatalogError,
)
from backend.qobuz_cmaf import (
    QobuzCmafDelivery,
    QobuzCmafError,
    compute_request_signature,
    decrypt_segment,
    derive_session_key,
    flac_format_id,
    parse_init_segment,
    unwrap_content_key,
    validate_flac_structure,
)
from utils.paths import get_cache_dir, get_config_dir


logger = logging.getLogger(__name__)


class QobuzAuthError(RuntimeError):
    """A safe, user-presentable Qobuz authentication failure."""


class QobuzAuthRejected(QobuzAuthError):
    """Qobuz explicitly rejected a user authorization or saved token."""


class QobuzDeliveryError(RuntimeError):
    """A safe Qobuz delivery-layer failure isolated from other providers."""


class QobuzDeliveryRejected(QobuzDeliveryError):
    """Qobuz rejected an authenticated playback-delivery request."""


class QobuzTrackUnavailable(QobuzDeliveryError):
    """The requested Qobuz track or format is unavailable."""


class QobuzBackend:
    """Provide isolated Qobuz authentication and delivery proof support."""

    PROVIDER_ID = "qobuz"
    DISPLAY_NAME = "Qobuz"
    CAPABILITIES = frozenset()

    AUTH_SIGNED_OUT = "signed_out"
    AUTH_LOGIN_PENDING = "login_pending"
    AUTH_AUTHENTICATED = "authenticated"
    AUTH_ERROR = "error"
    AUTH_UNAVAILABLE = "unavailable"

    LOGIN_PAGE_URL = "https://play.qobuz.com/login"
    BUNDLE_BASE_URL = "https://play.qobuz.com"
    OAUTH_SIGNIN_URL = "https://www.qobuz.com/signin/oauth"
    API_BASE_URL = "https://www.qobuz.com/api.json/0.2"
    OAUTH_CALLBACK_PATH = "/oauth/callback"
    USER_LOGIN_PATH = "/user/login"
    CMAF_SESSION_PATH = "/session/start"
    CMAF_FILE_URL_PATH = "/file/url"
    CMAF_PROFILE = "qbz-1"
    CMAF_SEED = "abb21364945c0583309667d13ca3d93a"
    CMAF_FORMAT_IDS = frozenset((6, 7, 27))

    SEARCH_QUERY_MAX_CHARS = 4096
    SEARCH_TYPES = frozenset(
        (
            "MainArtist",
            "Performer",
            "Composer",
            "Label",
            "ReleaseName",
        )
    )

    DISCOVER_ALBUM_ENDPOINT_METHODS = {
        "/discover/newReleases": "discovernewReleases",
        "/discover/idealDiscography": "discoveridealDiscography",
        "/discover/mostStreamed": "discovermostStreamed",
        "/discover/qobuzissims": "discoverqobuzissims",
        "/discover/albumOfTheWeek": "discoveralbumOfTheWeek",
        "/discover/pressAward": "discoverpressAward",
    }

    SERVICE_CACHE_MAX_AGE = 24 * 60 * 60
    SERVICE_RESPONSE_MAX_BYTES = 16 * 1024 * 1024
    CALLBACK_REQUEST_MAX_BYTES = 8192
    MANUAL_CALLBACK_PREFIX = "/qobuz/login/callback/"
    CMAF_INIT_MAX_BYTES = 8 * 1024 * 1024
    CMAF_SEGMENT_MAX_BYTES = 64 * 1024 * 1024
    CMAF_PROOF_MAX_FLAC_BYTES = 512 * 1024 * 1024
    CMAF_SESSION_RENEWAL_SKEW = 60

    _BUNDLE_URL_RE = re.compile(
        r'<script[^>]+src=["\'](?P<url>/resources/'
        r'\d+\.\d+\.\d+-[a-z]\d{3}/bundle\.js)["\']',
        re.IGNORECASE,
    )
    _APP_ID_RE = re.compile(r'production:\{api:\{appId:"(?P<app_id>\d{9})"')
    _PRIVATE_KEY_RE = re.compile(
        r'privateKey:\s*"(?P<private_key>[A-Za-z0-9]{6,30})"'
    )
    _APP_SECRET_SEED_RE = re.compile(
        r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",'
        r'window\.utimezone\.(?P<timezone>[a-z]+)\)'
    )
    _APP_SECRET_SIMPLE_RE = re.compile(
        r'appSecret:"(?P<secret>[a-f0-9]{32})"',
        re.IGNORECASE,
    )

    def __init__(
        self,
        config_dir=None,
        cache_dir=None,
        http_session=None,
        auth_timeout=180.0,
        now=None,
    ):
        self.available = False
        self.authenticated = False
        self.initialization_error = ""
        self.capabilities = self.CAPABILITIES

        self._auth_state = self.AUTH_SIGNED_OUT
        self._last_error = ""
        self._session = None
        self._auth_timeout = max(1.0, float(auth_timeout))
        self._now = now or time.time
        self._http = http_session or self._build_http_session()

        config_root = config_dir or get_config_dir()
        cache_root = cache_dir or get_cache_dir()
        self._session_file = os.path.join(config_root, "qobuz_session.json")
        self._service_cache_file = os.path.join(cache_root, "qobuz_service.json")

        self._auth_lock = threading.RLock()
        self._login_start_lock = threading.Lock()
        self._service_lock = threading.Lock()
        self._cmaf_lock = threading.Lock()
        self._cmaf_session = None

        # Q10E native lyrics cache.  Provider-local by construction so a
        # numeric Qobuz track ID can never collide with another provider cache.
        # Keep the established lyrics cache bound of 300 entries.
        self._lyrics_lock = threading.RLock()
        self._lyrics_cache = {}
        self._lyrics_cache_max_entries = 300
        self._login_thread = None
        self._login_listener = None
        self._cancel_event = None
        self._attempt_id = ""
        self._login_nonce = ""
        self._login_context = None
        self._configured_manual_callback_origin = ""
        self._login_manual_callback_origin = ""
        self._service_metadata = self._load_service_cache()
        self.available = self._service_metadata is not None

        self._catalog = QobuzCatalogClient(
            http_session=self._http,
            api_base_url=self.API_BASE_URL,
            metadata_loader=lambda: self._get_service_metadata(
                require_app_secrets=True
            ),
            token_loader=self._catalog_auth_token,
            now=self._now,
        )

    @staticmethod
    def _build_http_session():
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=4)
        session.mount("https://", adapter)
        return session

    def status(self):
        """Return serializable provider/authentication state without secrets."""
        with self._auth_lock:
            user = self._public_user(self._session)
            return {
                "provider_id": self.PROVIDER_ID,
                "display_name": self.DISPLAY_NAME,
                "available": bool(self.available),
                "authenticated": bool(self.authenticated),
                "usable": bool(self.available and self.authenticated),
                "auth_state": self._auth_state,
                "login_pending": self._auth_state == self.AUTH_LOGIN_PENDING,
                "error": self._last_error,
                "initialization_error": self.initialization_error,
                "user": user,
                "capabilities": sorted(self.capabilities),
            }

    def _catalog_auth_token(self):
        """Return the active Qobuz token internally, never via status()."""
        with self._auth_lock:
            session = self._session

            if (
                not self.authenticated
                or not isinstance(session, dict)
            ):
                return None

            token = session.get("user_auth_token")

            if not self._valid_token(token):
                return None

            return token

    def _catalog_request(
        self,
        path,
        *,
        method_name,
        params=None,
        signature_params=None,
        require_auth=False,
        signed=True,
    ):
        """Issue one bounded provider request."""
        return self._catalog.request_json(
            path,
            method_name=method_name,
            params=params,
            signature_params=signature_params,
            require_auth=require_auth,
            signed=signed,
        )

    def _catalog_post_request(
        self,
        path,
        *,
        method_name,
        json_body,
        signature_params=None,
        require_auth=False,
    ):
        """Issue one bounded read-only provider JSON POST."""
        return self._catalog.request_json_post(
            path,
            method_name=method_name,
            json_body=json_body,
            signature_params=signature_params,
            require_auth=require_auth,
        )

    @staticmethod
    def _catalog_page_bounds(
        limit=None,
        offset=None,
        *,
        default_limit=None,
        maximum_limit=None,
    ):
        return QobuzCatalogClient.page_bounds(
            limit,
            offset,
            default_limit=default_limit,
            maximum_limit=maximum_limit,
        )

    @staticmethod
    def _catalog_numeric_request_id(value, label):
        """Validate one positive numeric provider ID for an outbound request."""
        text = str(
            value
            if value is not None
            else ""
        ).strip()

        if (
            not text
            or not text.isascii()
            or not text.isdigit()
            or int(text) <= 0
        ):
            raise QobuzCatalogError(
                "invalid_request",
                f"Qobuz {label} is invalid.",
            )

        return text

    @staticmethod
    def _catalog_album_request_id(value):
        """Validate one opaque Qobuz album ID without inventing its format."""
        text = str(
            value
            if value is not None
            else ""
        ).strip()

        if (
            not text
            or len(text) > 512
            or not text.isascii()
            or any(
                ord(char) <= 32 or ord(char) == 127
                for char in text
            )
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz album ID is invalid.",
            )

        return text

    @staticmethod
    def _catalog_clean_text(value, *, maximum=16384):
        """Return bounded provider text without stringifying raw objects."""
        if not isinstance(value, str):
            return ""

        text = value.strip()

        if (
            not text
            or len(text) > int(maximum)
            or any(
                ord(char) == 0
                for char in text
            )
        ):
            return ""

        return text

    @classmethod
    def _catalog_optional_text(
        cls,
        value,
        *,
        maximum=16384,
    ):
        text = cls._catalog_clean_text(
            value,
            maximum=maximum,
        )
        return text or None

    @staticmethod
    def _catalog_optional_int(value, *, minimum=0):
        if value is None or isinstance(value, bool):
            return None

        try:
            number = int(value)
        except (TypeError, ValueError):
            return None

        if number < int(minimum):
            return None

        return number

    @staticmethod
    def _catalog_optional_float(value, *, minimum=0.0):
        if value is None or isinstance(value, bool):
            return None

        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        if (
            number != number
            or number in (float("inf"), float("-inf"))
            or number < float(minimum)
        ):
            return None

        return number

    @staticmethod
    def _catalog_response_numeric_id_text(value):
        """Normalize only integer/string numeric provider IDs."""
        if isinstance(value, bool):
            return ""

        if isinstance(value, int):
            return str(value)

        if isinstance(value, str):
            return value.strip()

        return ""

    @staticmethod
    def _catalog_response_bool(value):
        """Accept provider booleans only; never rely on Python truthiness."""
        return value if isinstance(value, bool) else False

    @classmethod
    def _catalog_required_response_numeric_id(
        cls,
        value,
        label,
    ):
        text = cls._catalog_response_numeric_id_text(
            value
        )

        if (
            not text
            or len(text) > 64
            or not text.isascii()
            or not text.isdigit()
            or int(text) <= 0
        ):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response has an invalid ID.",
            )

        return text

    @classmethod
    def _catalog_required_response_album_id(
        cls,
        value,
    ):
        text = cls._catalog_clean_text(
            value,
            maximum=512,
        )

        if (
            not text
            or not text.isascii()
            or any(
                ord(char) <= 32 or ord(char) == 127
                for char in text
            )
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz album response has an invalid ID.",
            )

        return text

    @classmethod
    def _catalog_optional_numeric_id(cls, value):
        text = cls._catalog_response_numeric_id_text(
            value
        )

        if (
            not text
            or len(text) > 64
            or not text.isascii()
            or not text.isdigit()
            or int(text) <= 0
        ):
            return None

        return text

    @classmethod
    def _catalog_optional_identifier(cls, value):
        text = cls._catalog_clean_text(
            value,
            maximum=512,
        )

        if (
            not text
            or not text.isascii()
            or any(
                ord(char) <= 32 or ord(char) == 127
                for char in text
            )
        ):
            return None

        return text

    @classmethod
    def _normalize_qobuz_artwork(cls, image):
        """Normalize Qobuz ImageSet using pinned QBZ best-image precedence."""
        if not isinstance(image, dict):
            return None

        variants = {}

        for key in (
            "small",
            "thumbnail",
            "large",
            "extralarge",
            "mega",
            "back",
        ):
            value = cls._catalog_optional_text(
                image.get(key),
                maximum=16384,
            )

            if value:
                variants[key] = value

        best = None

        for key in (
            "mega",
            "extralarge",
            "large",
            "thumbnail",
            "small",
        ):
            if key in variants:
                best = variants[key]
                break

        if not variants:
            return None

        result = {"url": best}
        result.update(variants)
        return result

    @classmethod
    def _normalize_qobuz_named_ref(
        cls,
        value,
        *,
        numeric_id=True,
    ):
        if not isinstance(value, dict):
            return None

        if numeric_id:
            provider_id = cls._catalog_optional_numeric_id(
                value.get("id")
            )
        else:
            provider_id = cls._catalog_optional_identifier(
                value.get("id")
            )

        name = cls._catalog_optional_text(
            value.get("name"),
            maximum=2048,
        )

        if provider_id is None and name is None:
            return None

        return {
            "id": provider_id,
            "name": name or "",
        }

    @classmethod
    def _normalize_qobuz_track(
        cls,
        payload,
        *,
        album_context=None,
    ):
        """Normalize one provider-native Qobuz Track into SROVA form."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz track response is invalid.",
            )

        native_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "track",
        )

        parent_album = (
            album_context
            if isinstance(album_context, dict)
            else {}
        )

        performer = (
            payload.get("performer")
            if isinstance(payload.get("performer"), dict)
            else {}
        )

        parent_artist = (
            parent_album.get("artist")
            if isinstance(parent_album.get("artist"), dict)
            else {}
        )

        artist_name = (
            cls._catalog_optional_text(
                performer.get("name"),
                maximum=2048,
            )
            or cls._catalog_optional_text(
                parent_artist.get("name"),
                maximum=2048,
            )
            or ""
        )

        artist_id = (
            cls._catalog_optional_numeric_id(
                performer.get("id")
            )
            or cls._catalog_optional_numeric_id(
                parent_artist.get("id")
            )
        )

        embedded_album = (
            payload.get("album")
            if isinstance(payload.get("album"), dict)
            else {}
        )

        album_id = (
            cls._catalog_optional_identifier(
                embedded_album.get("id")
            )
            or cls._catalog_optional_identifier(
                parent_album.get("id")
            )
        )

        album_title = (
            cls._catalog_optional_text(
                embedded_album.get("title"),
                maximum=4096,
            )
            or cls._catalog_optional_text(
                parent_album.get("title"),
                maximum=4096,
            )
            or ""
        )

        artwork = cls._normalize_qobuz_artwork(
            embedded_album.get("image")
        )

        if artwork is None:
            artwork = cls._normalize_qobuz_artwork(
                parent_album.get("image")
            )

        maximum_sampling_rate = cls._catalog_optional_float(
            payload.get("maximum_sampling_rate"),
            minimum=0.0,
        )

        maximum_bit_depth = cls._catalog_optional_int(
            payload.get("maximum_bit_depth"),
            minimum=0,
        )

        hires = cls._catalog_response_bool(
            payload.get("hires")
        )
        hires_streamable = cls._catalog_response_bool(
            payload.get("hires_streamable")
        )
        streamable = cls._catalog_response_bool(
            payload.get("streamable")
        )

        return {
            "source": "qobuz",
            "provider_track_id": native_id,
            "id": f"qobuz:{native_id}",
            "title": cls._catalog_clean_text(
                payload.get("title"),
                maximum=4096,
            ),
            "version": cls._catalog_optional_text(
                payload.get("version"),
                maximum=4096,
            ),
            "work": cls._catalog_optional_text(
                payload.get("work"),
                maximum=8192,
            ),
            "artist": artist_name,
            "artist_id": artist_id,
            "album": album_title,
            "album_id": album_id,
            "duration": (
                cls._catalog_optional_int(
                    payload.get("duration"),
                    minimum=0,
                )
                or 0
            ),
            "isrc": cls._catalog_optional_text(
                payload.get("isrc"),
                maximum=64,
            ),
            "disc_number": cls._catalog_optional_int(
                payload.get("media_number"),
                minimum=1,
            ),
            "track_number": cls._catalog_optional_int(
                payload.get("track_number"),
                minimum=1,
            ),
            "explicit": cls._catalog_response_bool(
                payload.get("parental_warning")
            ),
            "streamable": streamable,
            "artwork": artwork,
            "artwork_url": (
                artwork.get("url")
                if isinstance(artwork, dict)
                else None
            ),
            "quality": {
                "hires": hires,
                "hires_streamable": hires_streamable,
                "maximum_sampling_rate_khz": (
                    maximum_sampling_rate
                ),
                "maximum_bit_depth": maximum_bit_depth,
            },
            "format_availability": {
                "streamable": streamable,
                "hires_streamable": hires_streamable,
            },
            "performers": cls._catalog_optional_text(
                payload.get("performers"),
                maximum=8192,
            ),
            "composer": cls._normalize_qobuz_named_ref(
                payload.get("composer"),
                numeric_id=True,
            ),
            "copyright": cls._catalog_optional_text(
                payload.get("copyright"),
                maximum=8192,
            ),
        }

    @classmethod
    def _normalize_qobuz_album(cls, payload):
        """Normalize one Qobuz Album and its ordered embedded tracks."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz album response is invalid.",
            )

        album_id = cls._catalog_required_response_album_id(
            payload.get("id")
        )

        artist_ref = cls._normalize_qobuz_named_ref(
            payload.get("artist"),
            numeric_id=True,
        )

        artwork = cls._normalize_qobuz_artwork(
            payload.get("image")
        )

        dates = (
            payload.get("dates")
            if isinstance(payload.get("dates"), dict)
            else {}
        )

        release_date_original = (
            cls._catalog_optional_text(
                dates.get("original"),
                maximum=64,
            )
            or cls._catalog_optional_text(
                payload.get("release_date_original"),
                maximum=64,
            )
        )

        release_date_stream = (
            cls._catalog_optional_text(
                dates.get("stream"),
                maximum=64,
            )
            or cls._catalog_optional_text(
                payload.get("release_date_stream"),
                maximum=64,
            )
        )

        audio_info = (
            payload.get("audio_info")
            if isinstance(payload.get("audio_info"), dict)
            else {}
        )

        maximum_sampling_rate = (
            cls._catalog_optional_float(
                audio_info.get(
                    "maximum_sampling_rate"
                ),
                minimum=0.0,
            )
        )

        if maximum_sampling_rate is None:
            maximum_sampling_rate = (
                cls._catalog_optional_float(
                    payload.get(
                        "maximum_sampling_rate"
                    ),
                    minimum=0.0,
                )
            )

        maximum_bit_depth = cls._catalog_optional_int(
            audio_info.get("maximum_bit_depth"),
            minimum=0,
        )

        if maximum_bit_depth is None:
            maximum_bit_depth = (
                cls._catalog_optional_int(
                    payload.get(
                        "maximum_bit_depth"
                    ),
                    minimum=0,
                )
            )

        maximum_channel_count = (
            cls._catalog_optional_int(
                audio_info.get(
                    "maximum_channel_count"
                ),
                minimum=1,
            )
        )

        track_count = cls._catalog_optional_int(
            payload.get("track_count"),
            minimum=0,
        )

        if track_count is None:
            track_count = cls._catalog_optional_int(
                payload.get("tracks_count"),
                minimum=0,
            )

        raw_tracks = payload.get("tracks")
        normalized_tracks = []

        if raw_tracks is not None:
            if not isinstance(raw_tracks, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz album tracks response is invalid.",
                )

            items = raw_tracks.get("items")

            if items is not None:
                if not isinstance(items, list):
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz album track list is invalid.",
                    )

                normalized_tracks = [
                    cls._normalize_qobuz_track(
                        item,
                        album_context=payload,
                    )
                    for item in items
                ]

        streamable_value = payload.get("streamable")
        streamable = (
            streamable_value
            if isinstance(streamable_value, bool)
            else None
        )

        explicit_value = payload.get(
            "parental_warning"
        )
        explicit = (
            explicit_value
            if isinstance(explicit_value, bool)
            else None
        )

        hires = cls._catalog_response_bool(
            payload.get("hires")
        )
        hires_streamable = cls._catalog_response_bool(
            payload.get("hires_streamable")
        )

        return {
            "source": "qobuz",
            "album_id": album_id,
            "title": cls._catalog_clean_text(
                payload.get("title"),
                maximum=4096,
            ),
            "version": cls._catalog_optional_text(
                payload.get("version"),
                maximum=4096,
            ),
            "artist": (
                artist_ref.get("name", "")
                if artist_ref
                else ""
            ),
            "artist_id": (
                artist_ref.get("id")
                if artist_ref
                else None
            ),
            "artwork": artwork,
            "artwork_url": (
                artwork.get("url")
                if isinstance(artwork, dict)
                else None
            ),
            "release_date": release_date_original,
            "release_date_original": (
                release_date_original
            ),
            "release_date_stream": (
                release_date_stream
            ),
            "track_count": track_count,
            "duration": cls._catalog_optional_int(
                payload.get("duration"),
                minimum=0,
            ),
            "streamable": streamable,
            "explicit": explicit,
            "hires": hires,
            "hires_streamable": hires_streamable,
            "quality": {
                "hires": hires,
                "hires_streamable": hires_streamable,
                "maximum_sampling_rate_khz": (
                    maximum_sampling_rate
                ),
                "maximum_bit_depth": (
                    maximum_bit_depth
                ),
                "maximum_channel_count": (
                    maximum_channel_count
                ),
            },
            "label": cls._normalize_qobuz_named_ref(
                payload.get("label"),
                numeric_id=True,
            ),
            "genre": cls._normalize_qobuz_named_ref(
                payload.get("genre"),
                numeric_id=True,
            ),
            "upc": cls._catalog_optional_text(
                payload.get("upc"),
                maximum=128,
            ),
            "description": (
                cls._catalog_optional_text(
                    payload.get("description"),
                    maximum=65536,
                )
            ),
            "tracks": normalized_tracks,
        }

    @classmethod
    def _normalize_qobuz_artist(cls, payload):
        """Normalize the stable identity fields from one Qobuz Artist."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist response is invalid.",
            )

        artist_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "artist",
        )

        artwork = cls._normalize_qobuz_artwork(
            payload.get("image")
        )

        return {
            "source": "qobuz",
            "artist_id": artist_id,
            "name": cls._catalog_clean_text(
                payload.get("name"),
                maximum=4096,
            ),
            "artwork": artwork,
            "artwork_url": (
                artwork.get("url")
                if isinstance(artwork, dict)
                else None
            ),
            "albums_count": (
                cls._catalog_optional_int(
                    payload.get("albums_count"),
                    minimum=0,
                )
            ),
        }

    def _lyrics_cache_lookup(self, native_id):
        key = str(native_id)

        with self._lyrics_lock:
            if key not in self._lyrics_cache:
                return False, None

            value = self._lyrics_cache.pop(key)
            self._lyrics_cache[key] = value
            return True, value

    def _lyrics_cache_store(self, native_id, value):
        key = str(native_id)

        with self._lyrics_lock:
            self._lyrics_cache.pop(key, None)
            self._lyrics_cache[key] = value

            while (
                len(self._lyrics_cache)
                > self._lyrics_cache_max_entries
            ):
                oldest = next(iter(self._lyrics_cache))
                self._lyrics_cache.pop(oldest, None)

        return value

    def get_lyrics(self, track_id):
        """Fetch native Qobuz lyrics and normalize them for SROVA."""
        native_id = self._catalog_numeric_request_id(
            track_id,
            "track ID",
        )

        cache_hit, cached = self._lyrics_cache_lookup(
            native_id
        )

        if cache_hit:
            return cached

        try:
            envelope = self._catalog_request(
                "/track/lyricsUrl",
                method_name="tracklyricsUrl",
                params={"track_id": native_id},
                require_auth=True,
            )
        except QobuzCatalogError as exc:
            if exc.code == "not_found":
                return self._lyrics_cache_store(
                    native_id,
                    None,
                )
            raise

        if not isinstance(envelope, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz returned an invalid lyrics response.",
            )

        envelope_track_id = (
            self._catalog_response_numeric_id_text(
                envelope.get("track_id")
            )
        )

        if (
            envelope_track_id
            and envelope_track_id != native_id
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz returned lyrics for a different track.",
            )

        lyrics_url = self._catalog_clean_text(
            envelope.get("lyrics_url"),
            maximum=32768,
        )

        if not lyrics_url:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz returned no lyrics document URL.",
            )

        parsed_url = urlsplit(lyrics_url)
        hostname = str(
            parsed_url.hostname or ""
        ).strip().lower()

        if (
            parsed_url.scheme.lower() != "https"
            or not hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or hostname == "localhost"
            or hostname.endswith(".localhost")
            or hostname.endswith(".local")
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz returned an invalid lyrics document URL.",
            )

        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None

        if (
            address is not None
            and (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_unspecified
            )
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz returned an invalid lyrics document URL.",
            )

        maximum_bytes = 2 * 1024 * 1024

        try:
            with self._http.get(
                lyrics_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=(10, 30),
                stream=True,
                allow_redirects=False,
            ) as response:
                status = int(response.status_code)

                if status == 404:
                    return self._lyrics_cache_store(
                        native_id,
                        None,
                    )

                if status == 429:
                    raise QobuzCatalogError(
                        "rate_limited",
                        "Qobuz temporarily rate limited lyrics.",
                        http_status=status,
                        transient=True,
                    )

                if status >= 500:
                    raise QobuzCatalogError(
                        "provider_unavailable",
                        "Qobuz lyrics are temporarily unavailable.",
                        http_status=status,
                        transient=True,
                    )

                if not 200 <= status < 300:
                    raise QobuzCatalogError(
                        "provider_error",
                        "Qobuz rejected the lyrics request.",
                        http_status=status,
                    )

                body = bytearray()

                for chunk in response.iter_content(
                    chunk_size=65536
                ):
                    if not chunk:
                        continue

                    body.extend(chunk)

                    if len(body) > maximum_bytes:
                        raise QobuzCatalogError(
                            "malformed_response",
                            "Qobuz lyrics document is too large.",
                        )

        except requests.exceptions.Timeout as exc:
            raise QobuzCatalogError(
                "timeout",
                "Qobuz lyrics request timed out.",
                transient=True,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise QobuzCatalogError(
                "provider_unavailable",
                "Qobuz lyrics service could not be reached.",
                transient=True,
            ) from exc

        try:
            document = json.loads(
                bytes(body).decode("utf-8")
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz returned an invalid lyrics document.",
            ) from exc

        if not isinstance(document, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz returned an unexpected lyrics document.",
            )

        document_track_id = (
            self._catalog_response_numeric_id_text(
                document.get("track_id")
            )
        )

        if (
            document_track_id
            and document_track_id != native_id
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz returned lyrics for a different track.",
            )

        original = document.get("original")

        if not isinstance(original, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz lyrics content is unavailable.",
            )

        content_type = self._catalog_clean_text(
            original.get("type"),
            maximum=32,
        ).lower()

        raw_lines = original.get("lines")

        if not isinstance(raw_lines, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz lyrics lines are invalid.",
            )

        def clean_line(value):
            if isinstance(value, dict):
                value = value.get("line")
            return self._catalog_clean_text(
                value,
                maximum=16384,
            )

        if content_type in ("wsync", "lsync"):
            synced_lines = []
            fallback_lines = []

            for item in raw_lines:
                if not isinstance(item, dict):
                    continue

                line_text = clean_line(item)

                if line_text:
                    fallback_lines.append(line_text)

                start = item.get("start")

                if isinstance(start, bool):
                    continue

                try:
                    start_ms = int(start)
                except (TypeError, ValueError):
                    continue

                if (
                    not line_text
                    or start_ms < 0
                    or start_ms > 24 * 60 * 60 * 1000
                ):
                    continue

                synced_lines.append(
                    {
                        "ms": start_ms,
                        "text": line_text,
                    }
                )

            if synced_lines:
                return self._lyrics_cache_store(
                    native_id,
                    {
                        "synced": True,
                        "lines": synced_lines,
                    },
                )

            fallback_text = "\n".join(
                fallback_lines
            ).strip()

            if fallback_text:
                return self._lyrics_cache_store(
                    native_id,
                    {
                        "synced": False,
                        "text": fallback_text,
                    },
                )

            return self._lyrics_cache_store(
                native_id,
                None,
            )

        if content_type == "plain":
            plain_lines = []

            for item in raw_lines:
                line_text = clean_line(item)

                if line_text:
                    plain_lines.append(line_text)

            plain_text = "\n".join(
                plain_lines
            ).strip()

            if plain_text:
                return self._lyrics_cache_store(
                    native_id,
                    {
                        "synced": False,
                        "text": plain_text,
                    },
                )

            return self._lyrics_cache_store(
                native_id,
                None,
            )

        raise QobuzCatalogError(
            "malformed_response",
            "Qobuz returned an unsupported lyrics format.",
        )

    def get_track(self, track_id):
        """Fetch and normalize one authenticated Qobuz track."""
        native_id = self._catalog_numeric_request_id(
            track_id,
            "track ID",
        )

        payload = self._catalog_request(
            "/track/get",
            method_name="trackget",
            params={"track_id": native_id},
            require_auth=True,
        )

        return self._normalize_qobuz_track(
            payload
        )

    def get_tracks_batch(
        self,
        track_ids,
    ):
        """
        Resolve authenticated Qobuz track metadata through track/getList.

        Qobuz caps this endpoint at 50 IDs per POST. Larger caller inputs
        are split into bounded serial chunks. Returned tracks are mapped
        back to requested native-ID order rather than trusting provider
        response order.
        """
        if not isinstance(
            track_ids,
            (list, tuple),
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz track ID batch must be a list.",
            )

        native_ids = [
            self._catalog_numeric_request_id(
                value,
                "track ID",
            )
            for value in track_ids
        ]

        if not native_ids:
            return []

        resolved = []

        for start in range(
            0,
            len(native_ids),
            50,
        ):
            chunk = native_ids[
                start:start + 50
            ]

            ids_string = ",".join(chunk)

            payload = self._catalog_post_request(
                "/track/getList",
                method_name="trackgetList",
                json_body={
                    "tracks_id": [
                        int(value)
                        for value in chunk
                    ],
                },
                signature_params={
                    "tracks_id": ids_string,
                },
                require_auth=True,
            )

            if not isinstance(payload, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz track batch response is invalid.",
                )

            tracks_page = payload.get(
                "tracks"
            )

            if not isinstance(
                tracks_page,
                dict,
            ):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz track batch is missing tracks.",
                )

            raw_items = tracks_page.get(
                "items"
            )

            if not isinstance(
                raw_items,
                list,
            ):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz track batch item list is invalid.",
                )

            by_id = {}

            for raw_item in raw_items:
                detail = (
                    self._normalize_qobuz_track(
                        raw_item
                    )
                )

                detail_id = str(
                    detail.get(
                        "provider_track_id"
                    )
                    or ""
                ).strip()

                if (
                    detail_id
                    and detail_id not in by_id
                ):
                    by_id[detail_id] = detail

            for native_id in chunk:
                detail = by_id.get(
                    native_id
                )

                if detail is not None:
                    resolved.append(
                        detail
                    )

        return resolved

    def get_album(self, album_id):
        """Fetch and normalize one authenticated Qobuz album."""
        native_id = self._catalog_album_request_id(
            album_id
        )

        payload = self._catalog_request(
            "/album/get",
            method_name="albumget",
            params={"album_id": native_id},
            require_auth=True,
        )

        return self._normalize_qobuz_album(
            payload
        )

    def get_artist(
        self,
        artist_id,
        *,
        lang="en",
    ):
        """Fetch and normalize one authenticated Qobuz artist."""
        native_id = self._catalog_numeric_request_id(
            artist_id,
            "artist ID",
        )

        language = str(lang or "").strip().lower()

        if re.fullmatch(r"[a-z]{2}", language) is None:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz artist language is invalid.",
            )

        payload = self._catalog_request(
            "/artist/get",
            method_name="artistget",
            params={
                "artist_id": native_id,
                "lang": language,
            },
            require_auth=True,
        )

        return self._normalize_qobuz_artist(
            payload
        )

    @staticmethod
    def _catalog_library_total(value):
        """Validate the numeric total from a Qobuz list envelope."""
        if isinstance(value, bool) or not isinstance(value, int):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz library response has an invalid total.",
            )

        if value < 0:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz library response has an invalid total.",
            )

        return value

    def _get_library_page(
        self,
        favorite_type,
        normalizer,
        *,
        limit=None,
        offset=None,
    ):
        """Fetch exactly one bounded Qobuz favorites/library page."""
        if favorite_type not in {
            "albums",
            "tracks",
            "artists",
        }:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz library type is invalid.",
            )

        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        payload = self._catalog_request(
            "/favorite/getUserFavorites",
            method_name="favoritegetUserFavorites",
            params={
                "type": favorite_type,
                "limit": str(page_limit),
                "offset": str(page_offset),
            },
            # Pinned QBZ signs this endpoint with no request
            # parameters even though type/limit/offset are sent.
            signature_params={},
            require_auth=True,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz library response is invalid.",
            )

        branch = payload.get(favorite_type)

        if not isinstance(branch, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz library response is missing its requested section.",
            )

        items = branch.get("items")

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz library item list is invalid.",
            )

        if len(items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz library response exceeded the requested page limit.",
            )

        total = self._catalog_library_total(
            branch.get("total")
        )

        normalized = [
            normalizer(item)
            for item in items
        ]

        return {
            "ok": True,
            "items": normalized,
            "offset": page_offset,
            "limit": page_limit,
            "total": total,
        }

    def get_library_albums(
        self,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded page of the user's Qobuz albums."""
        return self._get_library_page(
            "albums",
            self._normalize_qobuz_album,
            limit=limit,
            offset=offset,
        )

    def get_library_tracks(
        self,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded page of the user's Qobuz tracks."""
        return self._get_library_page(
            "tracks",
            self._normalize_qobuz_track,
            limit=limit,
            offset=offset,
        )

    def get_library_artists(
        self,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded page of the user's Qobuz artists."""
        return self._get_library_page(
            "artists",
            self._normalize_qobuz_artist,
            limit=limit,
            offset=offset,
        )

    # Q10I native Qobuz Favorites ---------------------------------------
    #
    # Keep provider identity explicit:
    #   track  -> positive numeric native Qobuz ID
    #   artist -> positive numeric native Qobuz ID
    #   album  -> opaque native Qobuz album ID
    #
    # Canonical SROVA qobuz:<track-id> IDs must never be sent to these
    # provider endpoints.

    @staticmethod
    def _favorite_kind(value):
        kind = str(
            value
            if value is not None
            else ""
        ).strip().lower()

        if kind not in {
            "track",
            "album",
            "artist",
        }:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz favorite type is invalid.",
            )

        return kind

    def _favorite_native_id(
        self,
        favorite_type,
        item_id,
    ):
        kind = self._favorite_kind(
            favorite_type
        )

        if kind == "album":
            native_id = (
                self._catalog_album_request_id(
                    item_id
                )
            )
        else:
            native_id = (
                self._catalog_numeric_request_id(
                    item_id,
                    f"{kind} ID",
                )
            )

        return kind, native_id

    def get_favorite_ids(self):
        """Return native Qobuz favorite IDs for tracks, albums and artists."""
        payload = self._catalog_request(
            "/favorite/getUserFavoriteIds",
            method_name=(
                "favoritegetUserFavoriteIds"
            ),
            require_auth=True,
            signed=False,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz favorite ID response is invalid.",
            )

        result = {
            "ok": True,
            "track_ids": [],
            "album_ids": [],
            "artist_ids": [],
        }

        specs = (
            (
                "tracks",
                "track_ids",
                "track",
            ),
            (
                "albums",
                "album_ids",
                "album",
            ),
            (
                "artists",
                "artist_ids",
                "artist",
            ),
        )

        for (
            provider_key,
            result_key,
            favorite_type,
        ) in specs:
            values = payload.get(
                provider_key
            )

            if not isinstance(
                values,
                list,
            ):
                raise QobuzCatalogError(
                    "malformed_response",
                    (
                        "Qobuz favorite ID response "
                        f"is missing {provider_key}."
                    ),
                )

            # Bounded defensive validation. This limit is intentionally
            # far above a practical personal library while preventing an
            # unexpectedly huge provider payload from entering UI state.
            if len(values) > 100000:
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz favorite ID response is too large.",
                )

            normalized = []
            seen = set()

            for value in values:
                (
                    _kind,
                    native_id,
                ) = self._favorite_native_id(
                    favorite_type,
                    value,
                )

                if native_id in seen:
                    continue

                seen.add(native_id)
                normalized.append(
                    native_id
                )

            result[result_key] = (
                normalized
            )

        return result

    def get_favorite_status(
        self,
        favorite_type,
        item_id,
    ):
        """Return confirmed native provider favorite state for one item."""
        (
            kind,
            native_id,
        ) = self._favorite_native_id(
            favorite_type,
            item_id,
        )

        payload = self._catalog_request(
            "/favorite/status",
            method_name="favoritestatus",
            params={
                "type": kind,
                "item_id": native_id,
            },
            require_auth=True,
            signed=False,
        )

        if (
            not isinstance(payload, dict)
            or not isinstance(
                payload.get("status"),
                bool,
            )
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz favorite status response is invalid.",
            )

        return {
            "ok": True,
            "type": kind,
            "id": native_id,
            "is_favorite": payload[
                "status"
            ],
        }

    def set_favorite(
        self,
        favorite_type,
        item_id,
        is_favorite,
    ):
        """Set and immediately confirm one native Qobuz favorite state."""
        if not isinstance(
            is_favorite,
            bool,
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz favorite state must be boolean.",
            )

        (
            kind,
            native_id,
        ) = self._favorite_native_id(
            favorite_type,
            item_id,
        )

        current = self.get_favorite_status(
            kind,
            native_id,
        )

        if (
            current["is_favorite"]
            is is_favorite
        ):
            return {
                "ok": True,
                "type": kind,
                "id": native_id,
                "is_favorite": is_favorite,
                "changed": False,
                "confirmed": True,
                "provider_request_sent": False,
            }

        endpoint = (
            "/favorite/create"
            if is_favorite
            else "/favorite/delete"
        )

        method_name = (
            "favoritecreate"
            if is_favorite
            else "favoritedelete"
        )

        id_key = (
            f"{kind}_ids"
        )

        params = {
            id_key: native_id,
        }

        mutation_response_unreadable = (
            False
        )

        try:
            self._catalog_request(
                endpoint,
                method_name=method_name,
                params=params,
                signature_params=dict(
                    params
                ),
                require_auth=True,
            )
        except QobuzCatalogError as exc:
            # Some provider mutation endpoints have historically returned
            # a successful HTTP status with little/no useful JSON. If that
            # occurs, provider read-back remains the authority rather than
            # treating an unreadable success body as proof of failure.
            if (
                exc.code
                == "malformed_response"
                and exc.http_status
                is not None
                and 200
                <= exc.http_status
                < 300
            ):
                mutation_response_unreadable = (
                    True
                )
            else:
                raise

        confirmed = (
            self.get_favorite_status(
                kind,
                native_id,
            )
        )

        if (
            confirmed[
                "is_favorite"
            ]
            is not is_favorite
        ):
            raise QobuzCatalogError(
                "reconcile_timeout",
                (
                    "Qobuz accepted the favorite update, "
                    "but SROVA could not confirm it yet."
                ),
                transient=True,
            )

        return {
            "ok": True,
            "type": kind,
            "id": native_id,
            "is_favorite": is_favorite,
            "changed": True,
            "confirmed": True,
            "provider_request_sent": True,
            "mutation_response_unreadable": (
                mutation_response_unreadable
            ),
        }

    @classmethod
    def _catalog_search_query(cls, query):
        """Validate and normalize one provider-native search query."""
        if not isinstance(query, str):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz search query must be text.",
            )

        normalized = query.strip()

        if (
            not normalized
            or len(normalized) > cls.SEARCH_QUERY_MAX_CHARS
            or any(ord(char) == 0 for char in normalized)
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz search query is invalid.",
            )

        return normalized

    @classmethod
    def _catalog_search_type(cls, search_type):
        """Validate Qobuz's provider-native optional search type."""
        if search_type is None:
            return None

        if (
            not isinstance(search_type, str)
            or search_type not in cls.SEARCH_TYPES
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz search type is invalid.",
            )

        return search_type

    @classmethod
    def _normalize_qobuz_playlist(cls, payload):
        """Normalize one Qobuz playlist search result."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist response is invalid.",
            )

        playlist_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "playlist",
        )

        title = cls._catalog_clean_text(
            payload.get("name"),
            maximum=4096,
        )

        owner = cls._normalize_qobuz_named_ref(
            payload.get("owner"),
            numeric_id=True,
        )

        cover_urls = []

        for key in (
            "images300",
            "images150",
            "images",
        ):
            candidate = payload.get(key)

            if (
                not isinstance(candidate, list)
                or not candidate
            ):
                continue

            for value in candidate:
                url = cls._catalog_optional_text(
                    value,
                    maximum=16384,
                )

                if (
                    url
                    and url not in cover_urls
                ):
                    cover_urls.append(url)

                if len(cover_urls) == 4:
                    break

            # Pinned QBZ selects the first non-empty source list.
            break

        artwork_url = (
            cover_urls[0]
            if cover_urls
            else None
        )

        artwork = (
            {
                "url": artwork_url,
                "urls": list(cover_urls),
            }
            if cover_urls
            else None
        )

        return {
            "source": "qobuz",
            "playlist_id": playlist_id,
            "name": title,
            "title": title,
            "description": cls._catalog_optional_text(
                payload.get("description"),
                maximum=65536,
            ),
            "owner": owner,
            "owner_id": (
                owner.get("id")
                if owner
                else None
            ),
            "owner_name": (
                owner.get("name", "")
                if owner
                else ""
            ),
            "artwork": artwork,
            "artwork_url": artwork_url,
            "cover_urls": cover_urls,
            "track_count": (
                cls._catalog_optional_int(
                    payload.get("tracks_count"),
                    minimum=0,
                )
                or 0
            ),
            "duration": (
                cls._catalog_optional_int(
                    payload.get("duration"),
                    minimum=0,
                )
                or 0
            ),
            "is_public": cls._catalog_response_bool(
                payload.get("is_public")
            ),
            "slug": cls._catalog_optional_text(
                payload.get("slug"),
                maximum=4096,
            ),
            "users_count": cls._catalog_optional_int(
                payload.get("users_count"),
                minimum=0,
            ),
        }

    @classmethod
    def _normalize_qobuz_search_items(
        cls,
        items,
        normalizer,
    ):
        """Normalize search rows leniently, preserving valid provider order."""
        normalized = []

        for item in items:
            try:
                normalized.append(
                    normalizer(item)
                )
            except QobuzCatalogError as exc:
                if exc.code != "malformed_response":
                    raise

        return normalized

    @classmethod
    def _normalize_qobuz_search_page(
        cls,
        payload,
        key,
        normalizer,
        *,
        page_limit,
        page_offset,
        branch_required,
    ):
        """Normalize one Qobuz search page into SROVA's stable page form."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz search response is invalid.",
            )

        branch = payload.get(key)

        if branch is None:
            if branch_required:
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz search response is missing its requested section.",
                )

            return {
                "items": [],
                "offset": page_offset,
                "limit": page_limit,
                "total": 0,
            }

        if not isinstance(branch, dict):
            if branch_required:
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz search result section is invalid.",
                )

            return {
                "items": [],
                "offset": page_offset,
                "limit": page_limit,
                "total": 0,
            }

        raw_items = branch.get("items")

        if raw_items is None:
            raw_items = []

        if not isinstance(raw_items, list):
            if branch_required:
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz search item list is invalid.",
                )

            raw_items = []

        if len(raw_items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz search response exceeded the requested page limit.",
            )

        raw_total = branch.get("total")

        if raw_total is None:
            total = 0
        elif (
            isinstance(raw_total, bool)
            or not isinstance(raw_total, int)
            or raw_total < 0
        ):
            if branch_required:
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz search response has an invalid total.",
                )

            total = 0
        else:
            total = raw_total

        return {
            "items": cls._normalize_qobuz_search_items(
                raw_items,
                normalizer,
            ),
            "offset": page_offset,
            "limit": page_limit,
            "total": total,
        }

    def _search_qobuz_page(
        self,
        *,
        query,
        path,
        method_name,
        key,
        normalizer,
        limit=None,
        offset=None,
        search_type=None,
        allow_search_type=False,
    ):
        """Issue one bounded provider-native typed search page."""
        normalized_query = self._catalog_search_query(
            query
        )

        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        normalized_type = None

        if allow_search_type:
            normalized_type = self._catalog_search_type(
                search_type
            )
        elif search_type is not None:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz search type is not supported for this category.",
            )

        params = {
            "query": normalized_query,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        signature_params = {
            "limit": str(page_limit),
            "offset": str(page_offset),
            "query": normalized_query,
        }

        if normalized_type is not None:
            params["type"] = normalized_type
            signature_params["type"] = normalized_type

        payload = self._catalog_request(
            path,
            method_name=method_name,
            params=params,
            signature_params=signature_params,
            require_auth=True,
        )

        page = self._normalize_qobuz_search_page(
            payload,
            key,
            normalizer,
            page_limit=page_limit,
            page_offset=page_offset,
            branch_required=True,
        )

        return {
            "ok": True,
            "query": normalized_query,
            "search_type": normalized_type,
            **page,
        }

    def search_albums(
        self,
        query,
        *,
        limit=None,
        offset=None,
        search_type=None,
    ):
        """Return one Qobuz album-search page."""
        return self._search_qobuz_page(
            query=query,
            path="/album/search",
            method_name="albumsearch",
            key="albums",
            normalizer=self._normalize_qobuz_album,
            limit=limit,
            offset=offset,
            search_type=search_type,
            allow_search_type=True,
        )

    def search_tracks(
        self,
        query,
        *,
        limit=None,
        offset=None,
        search_type=None,
    ):
        """Return one Qobuz track-search page."""
        return self._search_qobuz_page(
            query=query,
            path="/track/search",
            method_name="tracksearch",
            key="tracks",
            normalizer=self._normalize_qobuz_track,
            limit=limit,
            offset=offset,
            search_type=search_type,
            allow_search_type=True,
        )

    def search_artists(
        self,
        query,
        *,
        limit=None,
        offset=None,
        search_type=None,
    ):
        """Return one Qobuz artist-search page."""
        return self._search_qobuz_page(
            query=query,
            path="/artist/search",
            method_name="artistsearch",
            key="artists",
            normalizer=self._normalize_qobuz_artist,
            limit=limit,
            offset=offset,
            search_type=search_type,
            allow_search_type=True,
        )

    def search_playlists(
        self,
        query,
        *,
        limit=None,
        offset=None,
    ):
        """Return one Qobuz playlist-search page."""
        return self._search_qobuz_page(
            query=query,
            path="/playlist/search",
            method_name="playlistsearch",
            key="playlists",
            normalizer=self._normalize_qobuz_playlist,
            limit=limit,
            offset=offset,
        )

    @classmethod
    def _normalize_qobuz_most_popular(
        cls,
        value,
    ):
        """Pick the first valid Qobuz most-popular entry in provider order."""
        if not isinstance(value, dict):
            return None

        items = value.get("items")

        if not isinstance(items, list):
            return None

        normalizers = {
            "albums": cls._normalize_qobuz_album,
            "tracks": cls._normalize_qobuz_track,
            "artists": cls._normalize_qobuz_artist,
        }

        for entry in items:
            if not isinstance(entry, dict):
                continue

            kind = entry.get("type")
            normalizer = normalizers.get(kind)

            if normalizer is None:
                continue

            try:
                content = normalizer(
                    entry.get("content")
                )
            except QobuzCatalogError as exc:
                if exc.code != "malformed_response":
                    raise
                continue

            return {
                "type": kind,
                "content": content,
            }

        return None

    def search_catalog(
        self,
        query,
        *,
        limit=None,
        offset=None,
    ):
        """Return one combined provider-native Qobuz catalog-search page."""
        normalized_query = self._catalog_search_query(
            query
        )

        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "query": normalized_query,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        signature_params = {
            "limit": str(page_limit),
            "offset": str(page_offset),
            "query": normalized_query,
        }

        payload = self._catalog_request(
            "/catalog/search",
            method_name="catalogsearch",
            params=params,
            signature_params=signature_params,
            require_auth=True,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz combined search response is invalid.",
            )

        return {
            "ok": True,
            "query": normalized_query,
            "offset": page_offset,
            "limit": page_limit,
            "albums": self._normalize_qobuz_search_page(
                payload,
                "albums",
                self._normalize_qobuz_album,
                page_limit=page_limit,
                page_offset=page_offset,
                branch_required=False,
            ),
            "tracks": self._normalize_qobuz_search_page(
                payload,
                "tracks",
                self._normalize_qobuz_track,
                page_limit=page_limit,
                page_offset=page_offset,
                branch_required=False,
            ),
            "artists": self._normalize_qobuz_search_page(
                payload,
                "artists",
                self._normalize_qobuz_artist,
                page_limit=page_limit,
                page_offset=page_offset,
                branch_required=False,
            ),
            "playlists": self._normalize_qobuz_search_page(
                payload,
                "playlists",
                self._normalize_qobuz_playlist,
                page_limit=page_limit,
                page_offset=page_offset,
                branch_required=False,
            ),
            "most_popular": self._normalize_qobuz_most_popular(
                payload.get("most_popular")
            ),
        }


    @classmethod
    def _catalog_discovery_request_id(
        cls,
        value,
        label,
    ):
        """Validate one positive numeric discovery request identifier."""
        text = cls._catalog_response_numeric_id_text(
            value
        )

        if (
            not text
            or len(text) > 64
            or not text.isascii()
            or not text.isdigit()
            or int(text) <= 0
        ):
            raise QobuzCatalogError(
                "invalid_request",
                f"Qobuz {label} is invalid.",
            )

        return text

    @classmethod
    def _catalog_discovery_genre_ids(
        cls,
        genre_ids,
    ):
        """Normalize the optional Qobuz discover genre-id list."""
        if genre_ids is None:
            return []

        if not isinstance(
            genre_ids,
            (list, tuple),
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz genre IDs must be a list.",
            )

        return [
            cls._catalog_discovery_request_id(
                value,
                "genre ID",
            )
            for value in genre_ids
        ]

    @classmethod
    def _normalize_qobuz_genre_path(
        cls,
        value,
    ):
        """Normalize Qobuz's optional top-level-to-self genre path."""
        if value is None:
            return None

        if not isinstance(value, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz genre path is invalid.",
            )

        return [
            cls._catalog_required_response_numeric_id(
                item,
                "genre path",
            )
            for item in value
        ]

    @classmethod
    def _normalize_qobuz_genre(
        cls,
        payload,
    ):
        """Normalize one provider-native Qobuz GenreInfo row."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz genre response is invalid.",
            )

        genre_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "genre",
        )

        return {
            "source": "qobuz",
            "genre_id": genre_id,
            "name": cls._catalog_clean_text(
                payload.get("name"),
                maximum=4096,
            ),
            "color": cls._catalog_optional_text(
                payload.get("color"),
                maximum=128,
            ),
            "slug": cls._catalog_optional_text(
                payload.get("slug"),
                maximum=4096,
            ),
            "path": cls._normalize_qobuz_genre_path(
                payload.get("path")
            ),
        }

    def get_genres(
        self,
        parent_id=None,
    ):
        """Return one Qobuz genre level using the pinned English contract."""
        normalized_parent = None

        if parent_id is not None:
            normalized_parent = (
                self._catalog_discovery_request_id(
                    parent_id,
                    "genre parent ID",
                )
            )

        params = {
            "lang": "en",
        }

        if normalized_parent is not None:
            params["parent_id"] = normalized_parent

        payload = self._catalog_request(
            "/genre/list",
            method_name="genrelist",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz genre response is invalid.",
            )

        genres = payload.get("genres")

        if not isinstance(genres, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz genre response is missing its genre section.",
            )

        items = genres.get("items")

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz genre item list is invalid.",
            )

        return {
            "ok": True,
            "parent_id": normalized_parent,
            "items": [
                self._normalize_qobuz_genre(item)
                for item in items
            ],
        }

    @classmethod
    def _normalize_qobuz_discover_artist(
        cls,
        payload,
    ):
        """Normalize one artist embedded in a Qobuz Discover album."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Discover artist response is invalid.",
            )

        artist_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "Discover artist",
        )

        roles_value = payload.get("roles")
        roles = None

        if roles_value is not None:
            if not isinstance(roles_value, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz Discover artist roles are invalid.",
                )

            roles = []

            for value in roles_value:
                if not isinstance(value, str):
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz Discover artist role is invalid.",
                    )

                role = cls._catalog_clean_text(
                    value,
                    maximum=2048,
                )

                if role:
                    roles.append(role)

        return {
            "id": artist_id,
            "name": cls._catalog_clean_text(
                payload.get("name"),
                maximum=4096,
            ),
            "roles": roles,
        }

    @classmethod
    def _normalize_qobuz_discover_award(
        cls,
        payload,
    ):
        """Normalize the pinned /discover/index album-award shape."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Discover album award is invalid.",
            )

        raw_id = payload.get("id")
        award_id = None

        if raw_id is not None:
            award_id = cls._catalog_optional_numeric_id(
                raw_id
            )

            if award_id is None:
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz Discover album award ID is invalid.",
                )

        return {
            "id": award_id,
            "name": cls._catalog_clean_text(
                payload.get("name"),
                maximum=4096,
            ),
            "awarded_at": cls._catalog_optional_text(
                payload.get("awarded_at"),
                maximum=64,
            ),
        }

    @classmethod
    def _normalize_qobuz_discover_album(
        cls,
        payload,
    ):
        """Normalize one Qobuz DiscoverAlbum into the common album model."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Discover album response is invalid.",
            )

        raw_artists = payload.get("artists")

        if not isinstance(raw_artists, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Discover album artist list is invalid.",
            )

        artists = [
            cls._normalize_qobuz_discover_artist(
                artist
            )
            for artist in raw_artists
        ]

        adapted = dict(payload)

        if raw_artists:
            adapted["artist"] = raw_artists[0]

        normalized = cls._normalize_qobuz_album(
            adapted
        )

        dates = (
            payload.get("dates")
            if isinstance(payload.get("dates"), dict)
            else {}
        )

        release_date_download = (
            cls._catalog_optional_text(
                dates.get("download"),
                maximum=64,
            )
        )

        normalized["release_date_download"] = (
            release_date_download
        )

        normalized["release_date"] = (
            normalized.get("release_date_original")
            or release_date_download
            or normalized.get("release_date_stream")
        )

        normalized["artists"] = artists

        raw_awards = payload.get("awards")
        awards = []

        if raw_awards is not None:
            if not isinstance(raw_awards, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz Discover album awards are invalid.",
                )

            awards = [
                cls._normalize_qobuz_discover_award(
                    award
                )
                for award in raw_awards
            ]

        normalized["awards"] = awards

        return normalized

    @classmethod
    def _normalize_qobuz_playlist_tag(
        cls,
        payload,
    ):
        """Normalize one Qobuz Discover playlist tag."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist tag response is invalid.",
            )

        return {
            "id": cls._catalog_required_response_numeric_id(
                payload.get("id"),
                "playlist tag",
            ),
            "slug": cls._catalog_clean_text(
                payload.get("slug"),
                maximum=4096,
            ),
            "name": cls._catalog_clean_text(
                payload.get("name"),
                maximum=4096,
            ),
        }

    @classmethod
    def _normalize_qobuz_playlist_genre(
        cls,
        payload,
    ):
        """Normalize one genre embedded in a Discover playlist."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist genre response is invalid.",
            )

        return {
            "id": cls._catalog_required_response_numeric_id(
                payload.get("id"),
                "playlist genre",
            ),
            "name": cls._catalog_clean_text(
                payload.get("name"),
                maximum=4096,
            ),
            "slug": cls._catalog_optional_text(
                payload.get("slug"),
                maximum=4096,
            ),
        }

    @classmethod
    def _normalize_qobuz_discover_playlist(
        cls,
        payload,
    ):
        """Normalize the dedicated Qobuz DiscoverPlaylist wire shape."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Discover playlist response is invalid.",
            )

        playlist_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "Discover playlist",
        )

        owner_value = payload.get("owner")

        if not isinstance(owner_value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Discover playlist owner is invalid.",
            )

        owner = cls._normalize_qobuz_named_ref(
            owner_value,
            numeric_id=True,
        )

        image = payload.get("image")

        if not isinstance(image, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Discover playlist image is invalid.",
            )

        rectangle = cls._catalog_optional_text(
            image.get("rectangle"),
            maximum=16384,
        )

        raw_covers = image.get("covers")
        covers = []

        if raw_covers is not None:
            if not isinstance(raw_covers, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz Discover playlist covers are invalid.",
                )

            for value in raw_covers:
                if not isinstance(value, str):
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz Discover playlist cover is invalid.",
                    )

                cover = cls._catalog_optional_text(
                    value,
                    maximum=16384,
                )

                if cover:
                    covers.append(cover)

        artwork_url = (
            rectangle
            or (
                covers[0]
                if covers
                else None
            )
        )

        artwork = None

        if rectangle or covers:
            artwork = {
                "url": artwork_url,
                "rectangle": rectangle,
                "covers": covers,
            }

        raw_tags = payload.get("tags")
        tags = []

        if raw_tags is not None:
            if not isinstance(raw_tags, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz Discover playlist tags are invalid.",
                )

            tags = [
                cls._normalize_qobuz_playlist_tag(
                    tag
                )
                for tag in raw_tags
            ]

        raw_genres = payload.get("genres")
        genres = []

        if raw_genres is not None:
            if not isinstance(raw_genres, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz Discover playlist genres are invalid.",
                )

            genres = [
                cls._normalize_qobuz_playlist_genre(
                    genre
                )
                for genre in raw_genres
            ]

        return {
            "source": "qobuz",
            "playlist_id": playlist_id,
            "name": cls._catalog_clean_text(
                payload.get("name"),
                maximum=4096,
            ),
            "title": cls._catalog_clean_text(
                payload.get("name"),
                maximum=4096,
            ),
            "description": cls._catalog_optional_text(
                payload.get("description"),
                maximum=65536,
            ),
            "owner": owner,
            "owner_id": (
                owner.get("id")
                if owner
                else None
            ),
            "owner_name": (
                owner.get("name", "")
                if owner
                else ""
            ),
            "artwork": artwork,
            "artwork_url": artwork_url,
            "rectangle_artwork_url": rectangle,
            "cover_urls": covers,
            "track_count": (
                cls._catalog_optional_int(
                    payload.get("tracks_count"),
                    minimum=0,
                )
                or 0
            ),
            "duration": (
                cls._catalog_optional_int(
                    payload.get("duration"),
                    minimum=0,
                )
                or 0
            ),
            "tags": tags,
            "tag_slugs": [
                tag["slug"]
                for tag in tags
                if tag["slug"]
            ],
            "category": (
                tags[0]["name"]
                if tags
                else None
            ),
            "genres": genres,
        }

    @classmethod
    def _normalize_qobuz_discover_container(
        cls,
        value,
        normalizer,
        label,
    ):
        """Normalize one optional /discover/index container."""
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz Discover {label} container is invalid.",
            )

        raw_id = value.get("id")

        if not isinstance(raw_id, str):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz Discover {label} container ID is invalid.",
            )

        container_id = cls._catalog_clean_text(
            raw_id,
            maximum=4096,
        )

        data = value.get("data")

        if not isinstance(data, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz Discover {label} data is invalid.",
            )

        has_more = data.get("has_more")

        if not isinstance(has_more, bool):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz Discover {label} pagination is invalid.",
            )

        items = data.get("items")

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz Discover {label} item list is invalid.",
            )

        return {
            "id": container_id,
            "has_more": has_more,
            "items": [
                normalizer(item)
                for item in items
            ],
        }

    def get_discover_index(
        self,
        *,
        genre_ids=None,
    ):
        """Return the authenticated provider-native Qobuz Discover index."""
        normalized_genres = (
            self._catalog_discovery_genre_ids(
                genre_ids
            )
        )

        params = {}

        if normalized_genres:
            params["genre_ids"] = ",".join(
                normalized_genres
            )

        payload = self._catalog_request(
            "/discover/index",
            method_name="discoverindex",
            params=params,
            signature_params=dict(params),
            require_auth=True,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Discover index response is invalid.",
            )

        containers = payload.get("containers")

        if not isinstance(containers, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Discover index is missing its containers.",
            )

        specs = (
            (
                "playlists",
                self._normalize_qobuz_discover_playlist,
                "playlists",
            ),
            (
                "ideal_discography",
                self._normalize_qobuz_discover_album,
                "ideal discography",
            ),
            (
                "playlists_tags",
                self._normalize_qobuz_playlist_tag,
                "playlist tags",
            ),
            (
                "new_releases",
                self._normalize_qobuz_discover_album,
                "new releases",
            ),
            (
                "qobuzissims",
                self._normalize_qobuz_discover_album,
                "Qobuzissimes",
            ),
            (
                "most_streamed",
                self._normalize_qobuz_discover_album,
                "most streamed",
            ),
            (
                "press_awards",
                self._normalize_qobuz_discover_album,
                "press awards",
            ),
            (
                "album_of_the_week",
                self._normalize_qobuz_discover_album,
                "album of the week",
            ),
        )

        normalized = {}

        for key, normalizer, label in specs:
            normalized[key] = (
                self._normalize_qobuz_discover_container(
                    containers.get(key),
                    normalizer,
                    label,
                )
            )

        return {
            "ok": True,
            "genre_ids": normalized_genres,
            "containers": normalized,
        }

    @classmethod
    def _catalog_discovery_tag(
        cls,
        value,
    ):
        """Validate one optional provider-native Discover playlist tag."""
        if value is None:
            return None

        if not isinstance(value, str):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz Discover playlist tag must be text.",
            )

        tag = cls._catalog_clean_text(
            value,
            maximum=4096,
        )

        if not tag:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz Discover playlist tag is invalid.",
            )

        return tag

    @classmethod
    def _normalize_qobuz_discover_page(
        cls,
        payload,
        normalizer,
        *,
        page_limit,
        page_offset,
        label,
    ):
        """Normalize one strict has-more-driven Qobuz Discover page."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz Discover {label} response is invalid.",
            )

        has_more = payload.get("has_more")

        if not isinstance(has_more, bool):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz Discover {label} pagination is invalid.",
            )

        items = payload.get("items")

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz Discover {label} item list is invalid.",
            )

        if len(items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz Discover {label} response exceeded the requested page limit.",
            )

        return {
            "items": [
                normalizer(item)
                for item in items
            ],
            "offset": page_offset,
            "limit": page_limit,
            "has_more": has_more,
        }

    def get_discover_albums(
        self,
        endpoint,
        *,
        genre_ids=None,
        limit=None,
        offset=None,
    ):
        """Return one bounded page from an allowlisted Qobuz Discover album feed."""
        if (
            not isinstance(endpoint, str)
            or endpoint not in self.DISCOVER_ALBUM_ENDPOINT_METHODS
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz Discover album endpoint is invalid.",
            )

        normalized_genres = (
            self._catalog_discovery_genre_ids(
                genre_ids
            )
        )

        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {}

        if normalized_genres:
            params["genre_ids"] = ",".join(
                normalized_genres
            )

        params["offset"] = str(page_offset)
        params["limit"] = str(page_limit)

        payload = self._catalog_request(
            endpoint,
            method_name=(
                self.DISCOVER_ALBUM_ENDPOINT_METHODS[
                    endpoint
                ]
            ),
            params=params,
            signature_params=dict(params),
            require_auth=True,
        )

        page = self._normalize_qobuz_discover_page(
            payload,
            self._normalize_qobuz_discover_album,
            page_limit=page_limit,
            page_offset=page_offset,
            label="album browse",
        )

        return {
            "ok": True,
            "endpoint": endpoint,
            "genre_ids": normalized_genres,
            **page,
        }

    def get_discover_playlists(
        self,
        *,
        tag=None,
        genre_ids=None,
        limit=None,
        offset=None,
    ):
        """Return one bounded provider-native Qobuz Discover playlist page."""
        normalized_tag = self._catalog_discovery_tag(
            tag
        )

        normalized_genres = (
            self._catalog_discovery_genre_ids(
                genre_ids
            )
        )

        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {}

        if normalized_tag is not None:
            params["tags"] = normalized_tag

        if normalized_genres:
            params["genre_ids"] = ",".join(
                normalized_genres
            )

        params["limit"] = str(page_limit)
        params["offset"] = str(page_offset)

        payload = self._catalog_request(
            "/discover/playlists",
            method_name="discoverplaylists",
            params=params,
            signature_params=dict(params),
            require_auth=True,
        )

        page = self._normalize_qobuz_discover_page(
            payload,
            self._normalize_qobuz_discover_playlist,
            page_limit=page_limit,
            page_offset=page_offset,
            label="playlist browse",
        )

        return {
            "ok": True,
            "tag": normalized_tag,
            "genre_ids": normalized_genres,
            **page,
        }

    @staticmethod
    def _catalog_release_watch_type(value):
        """Normalize the provider-native Release Watch tab."""
        if not isinstance(value, str):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz Release Watch type is invalid.",
            )

        normalized = value.strip().lower()

        if normalized not in {
            "artists",
            "labels",
            "awards",
        }:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz Release Watch type is invalid.",
            )

        return normalized

    @classmethod
    def _normalize_qobuz_release_watch_album(
        cls,
        payload,
    ):
        """Normalize one Release Watch album with QBZ's artists[0] backfill."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Release Watch album response is invalid.",
            )

        adapted = dict(payload)

        if adapted.get("artist") is None:
            raw_artists = adapted.get("artists")

            if (
                isinstance(raw_artists, list)
                and raw_artists
            ):
                adapted["artist"] = raw_artists[0]

        return cls._normalize_qobuz_album(
            adapted
        )

    @classmethod
    def _normalize_qobuz_release_watch_page(
        cls,
        payload,
        *,
        page_limit,
        page_offset,
    ):
        """Normalize one strict has-more-driven Release Watch page."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Release Watch response is invalid.",
            )

        has_more = payload.get("has_more")

        if not isinstance(has_more, bool):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Release Watch pagination is invalid.",
            )

        items = payload.get("items")

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Release Watch item list is invalid.",
            )

        if len(items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz Release Watch response exceeded the requested page limit.",
            )

        return {
            "items": [
                cls._normalize_qobuz_release_watch_album(
                    item
                )
                for item in items
            ],
            "offset": page_offset,
            "limit": page_limit,
            "has_more": has_more,
        }

    def get_release_watch(
        self,
        release_type="artists",
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded Qobuz Release Watch page."""
        normalized_type = (
            self._catalog_release_watch_type(
                release_type
            )
        )

        page_limit, page_offset = (
            self._catalog_page_bounds(
                limit,
                offset,
            )
        )

        params = {
            "type": normalized_type,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        payload = self._catalog_request(
            "/favorite/getNewReleases",
            method_name="favoritegetNewReleases",
            params=params,
            require_auth=True,
            signed=False,
        )

        page = (
            self._normalize_qobuz_release_watch_page(
                payload,
                page_limit=page_limit,
                page_offset=page_offset,
            )
        )

        return {
            "ok": True,
            "release_type": normalized_type,
            **page,
        }


    @staticmethod
    def _catalog_featured_type(value):
        """Normalize the provider-supported /album/getFeatured type."""
        if not isinstance(value, str):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz featured album type is invalid.",
            )

        normalized = value.strip().lower()

        if normalized not in {
            "new-releases",
            "press-awards",
            "most-streamed",
        }:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz featured album type is invalid.",
            )

        return normalized

    def _catalog_playlist_tag_language(self):
        """Resolve QBZ-compatible playlist-tag localization language."""
        with self._auth_lock:
            session = self._session
            language_code = (
                session.get("language_code")
                if isinstance(session, dict)
                else None
            )

        text = str(language_code or "").strip().lower()
        language = text.split("-", 1)[0]

        if re.fullmatch(r"[a-z]{2}", language) is None:
            return "en"

        return language

    @classmethod
    def _normalize_qobuz_raw_playlist_tag(
        cls,
        payload,
        *,
        language,
    ):
        """Adapt one raw /playlist/getTags row using QBZ semantics."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz raw playlist tag response is invalid.",
            )

        slug = payload.get("slug")
        name_json = payload.get("name_json")

        if not isinstance(slug, str):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz raw playlist tag slug is invalid.",
            )

        if not isinstance(name_json, str):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz raw playlist tag name data is invalid.",
            )

        for key in (
            "position",
            "is_discover",
            "featured_tag_id",
        ):
            value = payload.get(key)

            if value is not None and not isinstance(value, str):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz raw playlist tag metadata is invalid.",
                )

        if payload.get("is_discover") != "true":
            return None

        try:
            names = json.loads(name_json)
        except (TypeError, ValueError):
            return None

        if not isinstance(names, dict):
            return None

        name = names.get(language)

        if not isinstance(name, str):
            name = names.get("en")

        if not isinstance(name, str):
            return None

        normalized_name = cls._catalog_clean_text(
            name,
            maximum=4096,
        )

        if not normalized_name:
            return None

        raw_featured_id = payload.get("featured_tag_id")
        tag_id = 0

        if (
            isinstance(raw_featured_id, str)
            and raw_featured_id
            and raw_featured_id.isascii()
            and raw_featured_id.isdigit()
        ):
            parsed_id = int(raw_featured_id)

            if 0 <= parsed_id <= 18446744073709551615:
                tag_id = parsed_id

        return {
            "id": str(tag_id),
            "slug": cls._catalog_clean_text(
                slug,
                maximum=4096,
            ),
            "name": normalized_name,
        }

    @classmethod
    def _normalize_qobuz_featured_page(
        cls,
        payload,
        *,
        page_limit,
        page_offset,
    ):
        """Normalize one strict provider-native featured album page."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz featured album response is invalid.",
            )

        albums = payload.get("albums")

        if not isinstance(albums, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz featured album response is missing its albums section.",
            )

        items = albums.get("items")

        if items is None:
            items = []

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz featured album item list is invalid.",
            )

        if len(items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz featured album response exceeded the requested page limit.",
            )

        raw_total = albums.get("total")

        if raw_total is None:
            total = 0
        elif (
            isinstance(raw_total, bool)
            or not isinstance(raw_total, int)
            or raw_total < 0
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz featured album total is invalid.",
            )
        else:
            total = raw_total

        return {
            "items": [
                cls._normalize_qobuz_album(item)
                for item in items
            ],
            "offset": page_offset,
            "limit": page_limit,
            "total": total,
        }

    def get_featured_albums(
        self,
        featured_type,
        *,
        limit=None,
        offset=None,
        genre_id=None,
    ):
        """Return one bounded provider-native Qobuz featured album page."""
        normalized_type = self._catalog_featured_type(
            featured_type
        )

        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        normalized_genre = None

        if genre_id is not None:
            normalized_genre = self._catalog_numeric_request_id(
                genre_id,
                "genre ID",
            )

        params = {
            "type": normalized_type,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        if normalized_genre is not None:
            params["genre_id"] = normalized_genre

        payload = self._catalog_request(
            "/album/getFeatured",
            method_name="albumgetFeatured",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        page = self._normalize_qobuz_featured_page(
            payload,
            page_limit=page_limit,
            page_offset=page_offset,
        )

        return {
            "ok": True,
            "featured_type": normalized_type,
            "genre_id": normalized_genre,
            **page,
        }

    def get_playlist_tags(self):
        """Return the authenticated provider-native Discover playlist tags."""
        language = self._catalog_playlist_tag_language()

        payload = self._catalog_request(
            "/playlist/getTags",
            method_name="playlistgetTags",
            params={},
            signature_params={},
            require_auth=True,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist tag list response is invalid.",
            )

        raw_tags = payload.get("tags")

        if not isinstance(raw_tags, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist tag list is invalid.",
            )

        normalized = []

        for raw_tag in raw_tags:
            item = self._normalize_qobuz_raw_playlist_tag(
                raw_tag,
                language=language,
            )

            if item is not None:
                normalized.append(item)

        return {
            "ok": True,
            "items": normalized,
        }

    # Q6H1_ARTIST_DETAIL_CANDIDATE

    @classmethod
    def _catalog_artist_page_required_text(
        cls,
        value,
        label,
        *,
        maximum=16384,
    ):
        """Validate one required typed provider string in artist-detail data."""
        if not isinstance(value, str):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        text = cls._catalog_clean_text(
            value,
            maximum=maximum,
        )

        if not text:
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return text

    @classmethod
    def _catalog_artist_page_optional_text(
        cls,
        value,
        label,
        *,
        maximum=16384,
    ):
        """Validate one optional typed provider string."""
        if value is None:
            return None

        if not isinstance(value, str):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        stripped = value.strip()

        if (
            len(stripped) > int(maximum)
            or any(ord(char) == 0 for char in stripped)
        ):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return stripped or None

    @staticmethod
    def _catalog_artist_page_optional_int(
        value,
        label,
        *,
        minimum=None,
    ):
        """Validate one optional integer from a typed artist-detail model."""
        if value is None:
            return None

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or (
                minimum is not None
                and value < int(minimum)
            )
        ):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return value

    @staticmethod
    def _catalog_artist_page_optional_float(
        value,
        label,
        *,
        minimum=None,
    ):
        """Validate one optional finite numeric provider value."""
        if value is None:
            return None

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        number = float(value)

        if (
            number != number
            or number in (
                float("inf"),
                float("-inf"),
            )
            or (
                minimum is not None
                and number < float(minimum)
            )
        ):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return number

    @staticmethod
    def _catalog_artist_page_optional_bool(
        value,
        label,
    ):
        """Validate one optional provider boolean."""
        if value is None:
            return None

        if not isinstance(value, bool):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return value

    @classmethod
    def _catalog_artist_page_name_display(
        cls,
        value,
        label,
    ):
        """Extract required PageArtistName.display."""
        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return cls._catalog_artist_page_required_text(
            value.get("display"),
            label,
            maximum=4096,
        )

    @classmethod
    def _catalog_artist_page_named_ref(
        cls,
        value,
        label,
    ):
        """Validate a strict provider {id,name} reference."""
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return {
            "id": cls._catalog_required_response_numeric_id(
                value.get("id"),
                label,
            ),
            "name": cls._catalog_artist_page_required_text(
                value.get("name"),
                label,
                maximum=4096,
            ),
        }

    @classmethod
    def _catalog_artist_page_image_set(
        cls,
        value,
        label,
    ):
        """Validate and copy only the known Qobuz ImageSet URL fields."""
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        result = {}

        for key in (
            "small",
            "thumbnail",
            "large",
            "extralarge",
            "mega",
            "back",
        ):
            if key not in value or value.get(key) is None:
                continue

            text = cls._catalog_artist_page_optional_text(
                value.get(key),
                f"{label} {key}",
                maximum=16384,
            )

            if text:
                result[key] = text

        return result

    @classmethod
    def _normalize_qobuz_artist_page_portrait(
        cls,
        value,
        *,
        label="artist portrait",
    ):
        """Normalize PageArtistPortrait hash/format to one stable artwork URL."""
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        image_hash = cls._catalog_artist_page_required_text(
            value.get("hash"),
            f"{label} hash",
            maximum=2048,
        )
        image_format = cls._catalog_artist_page_required_text(
            value.get("format"),
            f"{label} format",
            maximum=128,
        )

        return {
            "hash": image_hash,
            "format": image_format,
            "url": (
                "https://static.qobuz.com/images/artists/"
                f"covers/large/{image_hash}.{image_format}"
            ),
        }

    @classmethod
    def _normalize_qobuz_artist_page_images(
        cls,
        value,
        *,
        label="artist images",
    ):
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return cls._normalize_qobuz_artist_page_portrait(
            value.get("portrait"),
            label=f"{label} portrait",
        )

    @classmethod
    def _normalize_qobuz_artist_page_similar_artist(
        cls,
        payload,
    ):
        """Normalize one embedded /artist/page similar-artist row."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page similar artist response is invalid.",
            )

        artist_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "artist-page similar artist",
        )
        name = cls._catalog_artist_page_name_display(
            payload.get("name"),
            "artist-page similar artist name",
        )
        artwork = cls._normalize_qobuz_artist_page_images(
            payload.get("images"),
            label="artist-page similar artist images",
        )

        return {
            "source": "qobuz",
            "artist_id": artist_id,
            "name": name,
            "artwork": artwork,
            "artwork_url": (
                artwork.get("url")
                if isinstance(artwork, dict)
                else None
            ),
        }

    @classmethod
    def _normalize_qobuz_artist_page_similar(
        cls,
        value,
    ):
        """Normalize the embedded similar-artists snapshot."""
        if value is None:
            return {
                "has_more": False,
                "items": [],
            }

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page similar-artists response is invalid.",
            )

        has_more = value.get("has_more")
        items = value.get("items")

        if not isinstance(has_more, bool):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page similar-artists pagination is invalid.",
            )

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page similar-artists list is invalid.",
            )

        return {
            "has_more": has_more,
            "items": [
                cls._normalize_qobuz_artist_page_similar_artist(
                    item
                )
                for item in items
            ],
        }

    @classmethod
    def _normalize_qobuz_artist_page_audio_info(
        cls,
        value,
        label,
    ):
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return {
            "maximum_sampling_rate": (
                cls._catalog_artist_page_optional_float(
                    value.get("maximum_sampling_rate"),
                    f"{label} sampling rate",
                    minimum=0.0,
                )
            ),
            "maximum_bit_depth": (
                cls._catalog_artist_page_optional_int(
                    value.get("maximum_bit_depth"),
                    f"{label} bit depth",
                    minimum=0,
                )
            ),
            "maximum_channel_count": (
                cls._catalog_artist_page_optional_int(
                    value.get("maximum_channel_count"),
                    f"{label} channel count",
                    minimum=1,
                )
            ),
        }

    @classmethod
    def _normalize_qobuz_artist_page_rights(
        cls,
        value,
        label,
    ):
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return {
            key: cls._catalog_artist_page_optional_bool(
                value.get(key),
                f"{label} {key}",
            )
            for key in (
                "streamable",
                "hires_streamable",
                "hires_purchasable",
                "purchasable",
                "downloadable",
                "previewable",
                "sampleable",
            )
        }

    @classmethod
    def _normalize_qobuz_artist_page_physical_support(
        cls,
        value,
        label,
    ):
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        return {
            "media_number": (
                cls._catalog_artist_page_optional_int(
                    value.get("media_number"),
                    f"{label} media number",
                    minimum=0,
                )
            ),
            "track_number": (
                cls._catalog_artist_page_optional_int(
                    value.get("track_number"),
                    f"{label} track number",
                    minimum=0,
                )
            ),
        }

    @classmethod
    def _normalize_qobuz_artist_page_dates(
        cls,
        value,
        label,
    ):
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        result = {}

        for key in (
            "original",
            "download",
            "stream",
        ):
            if key not in value or value.get(key) is None:
                continue

            result[key] = cls._catalog_artist_page_optional_text(
                value.get(key),
                f"{label} {key}",
                maximum=64,
            )

        return result

    @classmethod
    def _normalize_qobuz_artist_page_track_album(
        cls,
        value,
    ):
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page track album response is invalid.",
            )

        album = {
            "id": cls._catalog_required_response_album_id(
                value.get("id")
            ),
            "title": cls._catalog_artist_page_required_text(
                value.get("title"),
                "artist-page track album title",
                maximum=4096,
            ),
        }

        version = cls._catalog_artist_page_optional_text(
            value.get("version"),
            "artist-page track album version",
            maximum=4096,
        )
        image = cls._catalog_artist_page_image_set(
            value.get("image"),
            "artist-page track album image",
        )
        label = cls._catalog_artist_page_named_ref(
            value.get("label"),
            "artist-page track album label",
        )
        genre = cls._catalog_artist_page_named_ref(
            value.get("genre"),
            "artist-page track album genre",
        )

        if version is not None:
            album["version"] = version
        if image is not None:
            album["image"] = image
        if label is not None:
            album["label"] = label
        if genre is not None:
            album["genre"] = genre

        return album

    @classmethod
    def _normalize_qobuz_artist_page_track(
        cls,
        payload,
    ):
        """Adapt one strict PageArtistTrack to the locked common track model."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page track response is invalid.",
            )

        cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "artist-page track",
        )
        title = cls._catalog_artist_page_required_text(
            payload.get("title"),
            "artist-page track title",
            maximum=4096,
        )

        adapted = {
            "id": payload.get("id"),
            "title": title,
        }

        for key, maximum in (
            ("version", 4096),
            ("isrc", 64),
        ):
            value = cls._catalog_artist_page_optional_text(
                payload.get(key),
                f"artist-page track {key}",
                maximum=maximum,
            )
            if value is not None:
                adapted[key] = value

        duration = cls._catalog_artist_page_optional_int(
            payload.get("duration"),
            "artist-page track duration",
            minimum=0,
        )
        explicit = cls._catalog_artist_page_optional_bool(
            payload.get("parental_warning"),
            "artist-page track parental warning",
        )

        if duration is not None:
            adapted["duration"] = duration
        if explicit is not None:
            adapted["parental_warning"] = explicit

        artist = payload.get("artist")

        if artist is not None:
            if not isinstance(artist, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz artist-page track artist response is invalid.",
                )

            performer_id = cls._catalog_required_response_numeric_id(
                artist.get("id"),
                "artist-page track artist",
            )
            performer_name = cls._catalog_artist_page_name_display(
                artist.get("name"),
                "artist-page track artist name",
            )

            adapted["performer"] = {
                "id": performer_id,
                "name": performer_name,
            }

        audio_info = cls._normalize_qobuz_artist_page_audio_info(
            payload.get("audio_info"),
            "artist-page track audio info",
        )

        if audio_info is not None:
            if audio_info["maximum_sampling_rate"] is not None:
                adapted["maximum_sampling_rate"] = (
                    audio_info["maximum_sampling_rate"]
                )
            if audio_info["maximum_bit_depth"] is not None:
                adapted["maximum_bit_depth"] = (
                    audio_info["maximum_bit_depth"]
                )

        rights = cls._normalize_qobuz_artist_page_rights(
            payload.get("rights"),
            "artist-page track rights",
        )

        if rights is not None:
            if rights["streamable"] is not None:
                adapted["streamable"] = rights["streamable"]
            if rights["hires_streamable"] is not None:
                adapted["hires_streamable"] = (
                    rights["hires_streamable"]
                )

        physical = cls._normalize_qobuz_artist_page_physical_support(
            payload.get("physical_support"),
            "artist-page track physical support",
        )

        if physical is not None:
            if physical["media_number"] is not None:
                adapted["media_number"] = physical["media_number"]
            if physical["track_number"] is not None:
                adapted["track_number"] = physical["track_number"]

        album = cls._normalize_qobuz_artist_page_track_album(
            payload.get("album")
        )

        if album is not None:
            adapted["album"] = album

        return cls._normalize_qobuz_track(
            adapted
        )

    @classmethod
    def _normalize_qobuz_artist_page_contributor(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page release contributor response is invalid.",
            )

        roles_value = payload.get("roles")
        roles = None

        if roles_value is not None:
            if not isinstance(roles_value, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz artist-page release contributor roles are invalid.",
                )

            roles = []

            for value in roles_value:
                role = cls._catalog_artist_page_required_text(
                    value,
                    "artist-page release contributor role",
                    maximum=2048,
                )
                roles.append(role)

        result = {
            "id": cls._catalog_required_response_numeric_id(
                payload.get("id"),
                "artist-page release contributor",
            ),
            "name": cls._catalog_artist_page_required_text(
                payload.get("name"),
                "artist-page release contributor name",
                maximum=4096,
            ),
        }

        if roles is not None:
            result["roles"] = roles

        return result

    @classmethod
    def _normalize_qobuz_artist_page_release_artist(
        cls,
        payload,
    ):
        if payload is None:
            return None

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page release artist response is invalid.",
            )

        return {
            "id": cls._catalog_required_response_numeric_id(
                payload.get("id"),
                "artist-page release artist",
            ),
            "name": cls._catalog_artist_page_name_display(
                payload.get("name"),
                "artist-page release artist name",
            ),
        }

    @classmethod
    def _normalize_qobuz_artist_page_release(
        cls,
        payload,
    ):
        """Adapt one strict PageArtistRelease to the common Discover album model."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page release response is invalid.",
            )

        album_id = cls._catalog_required_response_album_id(
            payload.get("id")
        )
        title = cls._catalog_artist_page_required_text(
            payload.get("title"),
            "artist-page release title",
            maximum=4096,
        )

        singular_artist = (
            cls._normalize_qobuz_artist_page_release_artist(
                payload.get("artist")
            )
        )

        raw_artists = payload.get("artists")

        if raw_artists is None:
            raw_artists = []

        if not isinstance(raw_artists, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page release artist list is invalid.",
            )

        contributors = [
            cls._normalize_qobuz_artist_page_contributor(
                item
            )
            for item in raw_artists
        ]

        if not contributors and singular_artist is not None:
            contributors = [
                {
                    "id": singular_artist["id"],
                    "name": singular_artist["name"],
                }
            ]

        adapted = {
            "id": album_id,
            "title": title,
            "artists": contributors,
        }

        version = cls._catalog_artist_page_optional_text(
            payload.get("version"),
            "artist-page release version",
            maximum=4096,
        )
        release_type = cls._catalog_artist_page_optional_text(
            payload.get("release_type"),
            "artist-page release type",
            maximum=128,
        )

        if version is not None:
            adapted["version"] = version

        tracks_count = cls._catalog_artist_page_optional_int(
            payload.get("tracks_count"),
            "artist-page release track count",
            minimum=0,
        )
        duration = cls._catalog_artist_page_optional_int(
            payload.get("duration"),
            "artist-page release duration",
            minimum=0,
        )
        explicit = cls._catalog_artist_page_optional_bool(
            payload.get("parental_warning"),
            "artist-page release parental warning",
        )

        if tracks_count is not None:
            adapted["tracks_count"] = tracks_count
        if duration is not None:
            adapted["duration"] = duration
        if explicit is not None:
            adapted["parental_warning"] = explicit

        image = cls._catalog_artist_page_image_set(
            payload.get("image"),
            "artist-page release image",
        )
        label = cls._catalog_artist_page_named_ref(
            payload.get("label"),
            "artist-page release label",
        )
        genre = cls._catalog_artist_page_named_ref(
            payload.get("genre"),
            "artist-page release genre",
        )
        dates = cls._normalize_qobuz_artist_page_dates(
            payload.get("dates"),
            "artist-page release dates",
        )
        audio_info = cls._normalize_qobuz_artist_page_audio_info(
            payload.get("audio_info"),
            "artist-page release audio info",
        )
        rights = cls._normalize_qobuz_artist_page_rights(
            payload.get("rights"),
            "artist-page release rights",
        )

        if image is not None:
            adapted["image"] = image
        if label is not None:
            adapted["label"] = label
        if genre is not None:
            adapted["genre"] = genre
        if dates is not None:
            adapted["dates"] = dates
        if audio_info is not None:
            adapted["audio_info"] = audio_info

        if rights is not None:
            if rights["streamable"] is not None:
                adapted["streamable"] = rights["streamable"]
            if rights["hires_streamable"] is not None:
                adapted["hires_streamable"] = (
                    rights["hires_streamable"]
                )

        release_tags_value = payload.get("release_tags")
        release_tags = None

        if release_tags_value is not None:
            if not isinstance(release_tags_value, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz artist-page release tags are invalid.",
                )

            release_tags = [
                cls._catalog_artist_page_required_text(
                    value,
                    "artist-page release tag",
                    maximum=2048,
                )
                for value in release_tags_value
            ]

        awards_value = payload.get("awards")

        if awards_value is not None:
            if not isinstance(awards_value, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz artist-page release awards are invalid.",
                )

            adapted["awards"] = [
                cls._normalize_qobuz_discover_award(
                    award
                )
                for award in awards_value
            ]

        normalized = cls._normalize_qobuz_discover_album(
            adapted
        )

        normalized["release_type"] = release_type
        normalized["release_tags"] = release_tags
        normalized["rights"] = rights

        return normalized

    @classmethod
    def _normalize_qobuz_artist_release_group(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist release group response is invalid.",
            )

        release_type = cls._catalog_artist_page_required_text(
            payload.get("type"),
            "artist release group type",
            maximum=128,
        )
        has_more = payload.get("has_more")
        items = payload.get("items")

        if not isinstance(has_more, bool):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist release group pagination is invalid.",
            )

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist release group item list is invalid.",
            )

        return {
            "release_type": release_type,
            "has_more": has_more,
            "items": [
                cls._normalize_qobuz_artist_page_release(
                    item
                )
                for item in items
            ],
        }

    @classmethod
    def _normalize_qobuz_artist_page_playlist(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page playlist response is invalid.",
            )

        playlist_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "artist-page playlist",
        )
        title = cls._catalog_artist_page_optional_text(
            payload.get("title"),
            "artist-page playlist title",
            maximum=4096,
        )
        description = cls._catalog_artist_page_optional_text(
            payload.get("description"),
            "artist-page playlist description",
            maximum=65536,
        )

        owner_value = payload.get("owner")
        owner = None

        if owner_value is not None:
            if not isinstance(owner_value, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz artist-page playlist owner response is invalid.",
                )

            owner = {
                "id": cls._catalog_required_response_numeric_id(
                    owner_value.get("id"),
                    "artist-page playlist owner",
                ),
                "name": cls._catalog_artist_page_optional_text(
                    owner_value.get("name"),
                    "artist-page playlist owner name",
                    maximum=4096,
                ),
            }

        track_count = cls._catalog_artist_page_optional_int(
            payload.get("tracks_count"),
            "artist-page playlist track count",
            minimum=0,
        )
        duration = cls._catalog_artist_page_optional_int(
            payload.get("duration"),
            "artist-page playlist duration",
            minimum=0,
        )

        images_value = payload.get("images")
        rectangle_urls = []

        if images_value is not None:
            if not isinstance(images_value, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz artist-page playlist images response is invalid.",
                )

            rectangles = images_value.get("rectangle")

            if rectangles is not None:
                if not isinstance(rectangles, list):
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz artist-page playlist rectangle images are invalid.",
                    )

                for value in rectangles:
                    if not isinstance(value, str):
                        raise QobuzCatalogError(
                            "malformed_response",
                            "Qobuz artist-page playlist rectangle image is invalid.",
                        )

                    url = cls._catalog_artist_page_optional_text(
                        value,
                        "artist-page playlist rectangle image",
                        maximum=16384,
                    )

                    if url:
                        rectangle_urls.append(url)

        artwork_url = (
            rectangle_urls[0]
            if rectangle_urls
            else None
        )
        artwork = (
            {
                "url": artwork_url,
                "rectangle": rectangle_urls,
            }
            if rectangle_urls
            else None
        )

        return {
            "source": "qobuz",
            "playlist_id": playlist_id,
            "name": title or "",
            "title": title or "",
            "description": description,
            "owner": owner,
            "owner_id": (
                owner["id"]
                if owner
                else None
            ),
            "owner_name": (
                owner["name"]
                if owner
                else None
            ),
            "track_count": track_count,
            "duration": duration,
            "artwork": artwork,
            "artwork_url": artwork_url,
            "rectangle_artwork_urls": rectangle_urls,
        }

    @classmethod
    def _normalize_qobuz_artist_page_playlists(
        cls,
        value,
    ):
        if value is None:
            return {
                "has_more": False,
                "items": [],
            }

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page playlists response is invalid.",
            )

        has_more = value.get("has_more")
        items = value.get("items")

        if not isinstance(has_more, bool):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page playlists pagination is invalid.",
            )

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page playlist list is invalid.",
            )

        return {
            "has_more": has_more,
            "items": [
                cls._normalize_qobuz_artist_page_playlist(
                    item
                )
                for item in items
            ],
        }

    @classmethod
    def _normalize_qobuz_artist_page_biography(
        cls,
        value,
    ):
        if value is None:
            return None

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page biography response is invalid.",
            )

        raw_source = value.get("source")
        source = None

        if isinstance(raw_source, str):
            source = cls._catalog_artist_page_optional_text(
                raw_source,
                "artist-page biography source",
                maximum=4096,
            )

        return {
            "content": cls._catalog_artist_page_optional_text(
                value.get("content"),
                "artist-page biography content",
                maximum=262144,
            ),
            "source": source,
            "language": cls._catalog_artist_page_optional_text(
                value.get("language"),
                "artist-page biography language",
                maximum=128,
            ),
        }

    @classmethod
    def _normalize_qobuz_artist_page(
        cls,
        payload,
    ):
        """Normalize one complete provider-native /artist/page response."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page response is invalid.",
            )

        artist_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "artist-page artist",
        )
        name = cls._catalog_artist_page_name_display(
            payload.get("name"),
            "artist-page artist name",
        )

        artwork = cls._normalize_qobuz_artist_page_images(
            payload.get("images"),
            label="artist-page artist images",
        )

        top_tracks_value = payload.get("top_tracks")

        if top_tracks_value is None:
            top_tracks_value = []

        if not isinstance(top_tracks_value, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page top-track list is invalid.",
            )

        releases_value = payload.get("releases")

        if releases_value is None:
            releases_value = []

        if not isinstance(releases_value, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page release list is invalid.",
            )

        appears_value = payload.get("tracks_appears_on")

        if appears_value is None:
            appears_value = []

        if not isinstance(appears_value, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-page appears-on track list is invalid.",
            )

        last_release = payload.get("last_release")

        return {
            "ok": True,
            "artist_id": artist_id,
            "name": name,
            "artist_category": (
                cls._catalog_artist_page_optional_text(
                    payload.get("artist_category"),
                    "artist-page artist category",
                    maximum=4096,
                )
            ),
            "biography": (
                cls._normalize_qobuz_artist_page_biography(
                    payload.get("biography")
                )
            ),
            "artwork": artwork,
            "artwork_url": (
                artwork.get("url")
                if isinstance(artwork, dict)
                else None
            ),
            "similar_artists": (
                cls._normalize_qobuz_artist_page_similar(
                    payload.get("similar_artists")
                )
            ),
            "top_tracks": [
                cls._normalize_qobuz_artist_page_track(
                    item
                )
                for item in top_tracks_value
            ],
            "last_release": (
                cls._normalize_qobuz_artist_page_release(
                    last_release
                )
                if last_release is not None
                else None
            ),
            "release_groups": [
                cls._normalize_qobuz_artist_release_group(
                    group
                )
                for group in releases_value
            ],
            "tracks_appears_on": [
                cls._normalize_qobuz_artist_page_track(
                    item
                )
                for item in appears_value
            ],
            "playlists": (
                cls._normalize_qobuz_artist_page_playlists(
                    payload.get("playlists")
                )
            ),
        }

    @staticmethod
    def _catalog_artist_release_type(value):
        """Validate one open provider-native artist release bucket token."""
        if not isinstance(value, str):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz artist release type is invalid.",
            )

        token = value.strip()

        if (
            not token
            or len(token) > 128
            or not token.isascii()
            or any(
                ord(char) <= 32 or ord(char) == 127
                for char in token
            )
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz artist release type is invalid.",
            )

        return token

    @staticmethod
    def _catalog_artist_release_sort(value):
        """Allow only provider sort semantics proven by pinned QBZ."""
        if value is None:
            return None

        if not isinstance(value, str):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz artist release sort is invalid.",
            )

        normalized = value.strip()

        if normalized != "release_date":
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz artist release sort is invalid.",
            )

        return normalized

    def get_artist_page(
        self,
        artist_id,
    ):
        """Return the single-request provider-native Qobuz artist page."""
        native_id = self._catalog_numeric_request_id(
            artist_id,
            "artist ID",
        )

        params = {
            "artist_id": native_id,
        }

        payload = self._catalog_request(
            "/artist/page",
            method_name="artistpage",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        return self._normalize_qobuz_artist_page(
            payload
        )

    def get_artist_releases_grid(
        self,
        artist_id,
        release_type,
        *,
        limit=None,
        offset=None,
        sort=None,
    ):
        """Return one bounded provider-native artist release bucket page."""
        native_id = self._catalog_numeric_request_id(
            artist_id,
            "artist ID",
        )
        normalized_type = self._catalog_artist_release_type(
            release_type
        )
        normalized_sort = self._catalog_artist_release_sort(
            sort
        )
        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "artist_id": native_id,
            "release_type": normalized_type,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        if normalized_sort is not None:
            params["sort"] = normalized_sort

        payload = self._catalog_request(
            "/artist/getReleasesGrid",
            method_name="artistgetReleasesGrid",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist release-grid response is invalid.",
            )

        has_more = payload.get("has_more")
        items = payload.get("items")

        if not isinstance(has_more, bool):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist release-grid pagination is invalid.",
            )

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist release-grid item list is invalid.",
            )

        if len(items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist release-grid response exceeded the requested page limit.",
            )

        return {
            "ok": True,
            "artist_id": native_id,
            "release_type": normalized_type,
            "sort": normalized_sort,
            "items": [
                self._normalize_qobuz_artist_page_release(
                    item
                )
                for item in items
            ],
            "offset": page_offset,
            "limit": page_limit,
            "has_more": has_more,
        }

    @classmethod
    def _normalize_qobuz_artist_story_item(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist story response is invalid.",
            )

        story_id = cls._catalog_artist_page_required_text(
            payload.get("id"),
            "artist story ID",
            maximum=512,
        )
        title = cls._catalog_artist_page_required_text(
            payload.get("title"),
            "artist story title",
            maximum=16384,
        )
        display_date = cls._catalog_artist_page_optional_int(
            payload.get("display_date"),
            "artist story display date",
        )
        image = cls._catalog_artist_page_optional_text(
            payload.get("image"),
            "artist story image",
            maximum=16384,
        )
        description_short = (
            cls._catalog_artist_page_optional_text(
                payload.get("description_short"),
                "artist story description",
                maximum=65536,
            )
        )

        images_value = payload.get("images")
        images = []

        if images_value is not None:
            if not isinstance(images_value, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz artist story image list is invalid.",
                )

            for item in images_value:
                if not isinstance(item, dict):
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz artist story image response is invalid.",
                    )

                images.append(
                    {
                        "format": (
                            cls._catalog_artist_page_optional_text(
                                item.get("format"),
                                "artist story image format",
                                maximum=128,
                            )
                        ),
                        "url": (
                            cls._catalog_artist_page_required_text(
                                item.get("url"),
                                "artist story image URL",
                                maximum=16384,
                            )
                        ),
                    }
                )

        authors_value = payload.get("authors")
        authors = []

        if authors_value is not None:
            if not isinstance(authors_value, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz artist story author list is invalid.",
                )

            for item in authors_value:
                if not isinstance(item, dict):
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz artist story author response is invalid.",
                    )

                authors.append(
                    {
                        "name": (
                            cls._catalog_artist_page_required_text(
                                item.get("name"),
                                "artist story author name",
                                maximum=4096,
                            )
                        ),
                        "id": (
                            cls._catalog_artist_page_optional_text(
                                item.get("id"),
                                "artist story author ID",
                                maximum=512,
                            )
                        ),
                        "slug": (
                            cls._catalog_artist_page_optional_text(
                                item.get("slug"),
                                "artist story author slug",
                                maximum=2048,
                            )
                        ),
                    }
                )

        slugs_value = payload.get("section_slugs")
        section_slugs = []

        if slugs_value is not None:
            if not isinstance(slugs_value, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz artist story section-slug list is invalid.",
                )

            section_slugs = [
                cls._catalog_artist_page_required_text(
                    value,
                    "artist story section slug",
                    maximum=2048,
                )
                for value in slugs_value
            ]

        image_url = (
            image
            or (
                images[0]["url"]
                if images
                else None
            )
        )

        return {
            "id": story_id,
            "title": title,
            "display_date": display_date,
            "image": image,
            "images": images,
            "image_url": image_url,
            "description_short": description_short,
            "authors": authors,
            "section_slugs": section_slugs,
        }

    def get_artist_story(
        self,
        artist_id,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded provider-native Qobuz artist Magazine page."""
        native_id = self._catalog_numeric_request_id(
            artist_id,
            "artist ID",
        )
        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "artist_id": native_id,
            "offset": str(page_offset),
            "limit": str(page_limit),
        }

        payload = self._catalog_request(
            "/artist/story",
            method_name="artiststory",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-story response is invalid.",
            )

        has_more = payload.get("has_more")
        items = payload.get("items")

        if not isinstance(has_more, bool):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-story pagination is invalid.",
            )

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-story item list is invalid.",
            )

        if len(items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz artist-story response exceeded the requested page limit.",
            )

        return {
            "ok": True,
            "artist_id": native_id,
            "items": [
                self._normalize_qobuz_artist_story_item(
                    item
                )
                for item in items
            ],
            "offset": page_offset,
            "limit": page_limit,
            "has_more": has_more,
        }

    @classmethod
    def _normalize_qobuz_album_suggest(
        cls,
        payload,
    ):
        """Normalize the provider-native /album/suggest response."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz album suggestion response is invalid.",
            )

        algorithm = cls._catalog_optional_text(
            payload.get("algorithm"),
            maximum=4096,
        )

        albums = payload.get("albums")

        if albums is None:
            return {
                "algorithm": algorithm,
                "items": [],
            }

        if not isinstance(albums, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz album suggestion album section is invalid.",
            )

        raw_items = albums.get("items")

        if raw_items is None:
            raw_items = []

        if not isinstance(raw_items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz album suggestion item list is invalid.",
            )

        normalized = {
            "algorithm": algorithm,
            "items": [
                cls._normalize_qobuz_album(
                    item
                )
                for item in raw_items
            ],
        }

        provider_limit = albums.get("limit")

        if provider_limit is not None:
            if (
                isinstance(provider_limit, bool)
                or not isinstance(provider_limit, int)
                or provider_limit < 0
            ):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz album suggestion limit is invalid.",
                )

            normalized["limit"] = provider_limit

        return normalized

    def get_similar_artists(
        self,
        artist_id,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded provider-native Qobuz similar-artists page."""
        native_id = self._catalog_numeric_request_id(
            artist_id,
            "artist ID",
        )

        page_limit, page_offset = (
            self._catalog_page_bounds(
                limit,
                offset,
            )
        )

        params = {
            "artist_id": native_id,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        payload = self._catalog_request(
            "/artist/getSimilarArtists",
            method_name="artistgetSimilarArtists",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        page = self._normalize_qobuz_search_page(
            payload,
            "artists",
            self._normalize_qobuz_artist,
            page_limit=page_limit,
            page_offset=page_offset,
            branch_required=True,
        )

        return {
            "ok": True,
            "artist_id": native_id,
            **page,
        }

    def get_album_suggest(
        self,
        album_id,
    ):
        """Return provider-native Qobuz album suggestions for one album."""
        native_id = self._catalog_album_request_id(
            album_id
        )

        payload = self._catalog_request(
            "/album/suggest",
            method_name="albumsuggest",
            params={
                "album_id": native_id,
            },
            require_auth=False,
            signed=False,
        )

        normalized = (
            self._normalize_qobuz_album_suggest(
                payload
            )
        )

        return {
            "ok": True,
            "album_id": native_id,
            **normalized,
        }

    @staticmethod
    def _public_user(session):
        if not isinstance(session, dict):
            return None
        return {
            "display_name": str(session.get("display_name") or ""),
            "subscription": str(session.get("subscription") or ""),
            "subscription_valid_until": session.get("subscription_valid_until"),
            "country_code": session.get("country_code"),
            "language_code": session.get("language_code"),
        }

    @staticmethod
    def _normalise_manual_callback_origin(origin):
        """Return one exact private-LAN HTTP origin or fail closed."""
        text = str(origin or "").strip()

        if (
            not text
            or len(text) > 512
            or not text.isascii()
            or any(
                ord(char) <= 32
                or ord(char) == 127
                for char in text
            )
        ):
            return ""

        try:
            parsed = urlsplit(text)
            port = parsed.port
        except (TypeError, ValueError):
            return ""

        if (
            parsed.scheme.lower() != "http"
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.query)
            or bool(parsed.fragment)
            or parsed.path not in ("", "/")
            or port is None
        ):
            return ""

        host = str(
            parsed.hostname or ""
        ).strip().lower()

        if not host:
            return ""

        try:
            address = ipaddress.ip_address(
                host
            )
        except ValueError:
            return ""

        if address.version != 4:
            return ""

        allowed_networks = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("169.254.0.0/16"),
        )

        if not any(
            address in network
            for network in allowed_networks
        ):
            return ""

        if not (
            1 <= int(port) <= 65535
        ):
            return ""

        return (
            "http://"
            + address.compressed
            + ":"
            + str(int(port))
        )

    def set_manual_callback_origin(self, origin):
        """Configure trusted LAN origin for the next login attempt."""
        normalised = (
            self._normalise_manual_callback_origin(
                origin
            )
        )

        with self._auth_lock:
            self._configured_manual_callback_origin = (
                normalised
            )

        return bool(normalised)

    def manual_callback_request_valid(
        self,
        request_target,
    ):
        """Validate one browser callback for presentation only."""
        request_target = str(
            request_target or ""
        ).strip()

        with self._auth_lock:
            auth_state = self._auth_state
            nonce = str(
                self._login_nonce or ""
            )
            manual_origin = str(
                self._login_manual_callback_origin
                or ""
            )
            listener = self._login_listener
            cancel_event = self._cancel_event
            thread = self._login_thread

        active = (
            auth_state == self.AUTH_LOGIN_PENDING
            and bool(nonce)
            and bool(manual_origin)
            and listener is not None
            and cancel_event is not None
            and not cancel_event.is_set()
            and thread is not None
            and thread.is_alive()
        )

        if not active:
            return False

        if (
            not request_target
            or len(request_target)
            > self.CALLBACK_REQUEST_MAX_BYTES
            or not request_target.isascii()
            or any(
                ord(char) <= 32
                or ord(char) == 127
                for char in request_target
            )
        ):
            return False

        try:
            parsed = urlsplit(
                request_target
            )
        except (
            TypeError,
            ValueError,
        ):
            return False

        expected_path = (
            self.MANUAL_CALLBACK_PREFIX
            + nonce
        )

        if (
            bool(parsed.scheme)
            or bool(parsed.netloc)
            or bool(parsed.fragment)
            or not secrets.compare_digest(
                parsed.path,
                expected_path,
            )
        ):
            return False

        worker_target = f"/{nonce}"

        if parsed.query:
            worker_target += (
                "?"
                + parsed.query
            )

        code = (
            self._parse_callback_request_line(
                f"GET {worker_target} HTTP/1.1",
                nonce,
            )
        )

        return code is not None

    def start_login(self):
        """Start or deterministically reuse one browser authentication attempt."""
        with self._login_start_lock:
            listener = None
            with self._auth_lock:
                if self.authenticated:
                    return {
                        "logged_in": True,
                        "pending": False,
                        "auth_state": self._auth_state,
                    }
                if (
                    self._auth_state == self.AUTH_LOGIN_PENDING
                    and self._login_thread is not None
                    and self._login_thread.is_alive()
                    and self._login_context is not None
                ):
                    return dict(self._login_context)

                configured_manual_origin = str(
                    self._configured_manual_callback_origin
                    or ""
                )

            try:
                metadata = self._get_service_metadata()
                listener = self._bind_login_listener()
                port = int(listener.getsockname()[1])
                nonce = secrets.token_hex(24)
                attempt_id = secrets.token_hex(16)
                redirect = f"http://localhost:{port}/{nonce}"

                login_url = (
                    f"{self.OAUTH_SIGNIN_URL}?ext_app_id="
                    f"{quote(metadata['app_id'], safe='')}&redirect_url="
                    f"{quote(redirect, safe='')}"
                )

                manual_origin = (
                    self._normalise_manual_callback_origin(
                        configured_manual_origin
                    )
                )

                manual_login_url = ""

                if manual_origin:
                    manual_redirect = (
                        manual_origin
                        + self.MANUAL_CALLBACK_PREFIX
                        + nonce
                    )

                    manual_login_url = (
                        f"{self.OAUTH_SIGNIN_URL}?ext_app_id="
                        f"{quote(metadata['app_id'], safe='')}&redirect_url="
                        f"{quote(manual_redirect, safe='')}"
                    )

                cancel_event = threading.Event()

                context = {
                    "url": login_url,
                    "manual_url": manual_login_url,
                    "attempt_id": attempt_id,
                    "callback_port": port,
                    "logged_in": False,
                    "pending": True,
                    "auth_state": self.AUTH_LOGIN_PENDING,
                }
                thread = threading.Thread(
                    target=self._login_worker,
                    args=(attempt_id, listener, nonce, cancel_event),
                    name="qobuz-browser-auth",
                    daemon=True,
                )
                with self._auth_lock:
                    self.available = True
                    self.authenticated = False
                    self._auth_state = self.AUTH_LOGIN_PENDING
                    self._last_error = ""
                    self.initialization_error = ""
                    self._attempt_id = attempt_id
                    self._login_nonce = nonce
                    self._login_manual_callback_origin = (
                        manual_origin
                    )
                    self._login_listener = listener
                    self._cancel_event = cancel_event
                    self._login_context = context
                    self._login_thread = thread
                thread.start()
                logger.info("Qobuz browser authentication attempt started")
                return dict(context)
            except Exception as exc:
                self._close_listener(listener)
                with self._auth_lock:
                    self._login_listener = None
                    self._login_nonce = ""
                    self._login_manual_callback_origin = ""
                    self._cancel_event = None
                    self._login_context = None
                    self._login_thread = None
                self._record_failure(
                    "Qobuz sign-in could not be started.",
                    exc,
                    unavailable=True,
                )
                return {
                    "logged_in": False,
                    "pending": False,
                    "auth_state": self.AUTH_UNAVAILABLE,
                    "error": "Qobuz sign-in could not be started.",
                }

    def poll_login(self, attempt_id=None):
        """Report an attempt's state without exposing its URL or nonce."""
        with self._auth_lock:
            if attempt_id and self._attempt_id and attempt_id != self._attempt_id:
                return {
                    "logged_in": False,
                    "pending": False,
                    "auth_state": self._auth_state,
                    "error": "Qobuz sign-in attempt is no longer active.",
                }
            payload = self.status()
        return {
            "logged_in": payload["authenticated"],
            "pending": payload["login_pending"],
            "auth_state": payload["auth_state"],
            "error": payload["error"],
            "user": payload["user"],
        }

    def restore_session(self):
        """Validate and restore a persisted Qobuz user token."""
        with self._login_start_lock:
            return self._restore_session_locked()

    def _restore_session_locked(self):
        try:
            saved = self._load_json_file(self._session_file)
        except Exception as exc:
            self._record_failure("Saved Qobuz session is invalid.", exc)
            return False
        if saved is None:
            with self._auth_lock:
                self.authenticated = False
                if self._auth_state != self.AUTH_LOGIN_PENDING:
                    self._auth_state = self.AUTH_SIGNED_OUT
                    self._last_error = ""
            return False
        token = saved.get("user_auth_token") if isinstance(saved, dict) else None
        if not self._valid_token(token):
            self._record_failure("Saved Qobuz session is invalid.", ValueError("token"))
            return False

        try:
            metadata = self._get_service_metadata()
            session = self._login_with_token(metadata["app_id"], token)
        except QobuzAuthRejected as exc:
            self._clear_session_file()
            self._record_failure("Saved Qobuz session was rejected.", exc)
            return False
        except Exception as exc:
            # Keep the token on network/service errors so a later restart or
            # explicit retry can restore it.
            self._record_failure(
                "Saved Qobuz session could not be restored.",
                exc,
                unavailable=not self.available,
            )
            return False

        with self._auth_lock:
            self.available = True
            self.authenticated = True
            self._auth_state = self.AUTH_AUTHENTICATED
            self._last_error = ""
            self.initialization_error = ""
            self._session = session
        logger.info("Qobuz session restored")
        return True


    def complete_login(self, attempt_id, callback_url):
        """Relay one validated headless callback to the active Q2 worker."""
        attempt_id = str(attempt_id or "").strip()
        callback_url = str(callback_url or "").strip()

        with self._auth_lock:
            if self.authenticated:
                return {
                    "accepted": True,
                    "logged_in": True,
                    "pending": False,
                    "auth_state": self._auth_state,
                }

            auth_state = self._auth_state
            current_attempt = str(self._attempt_id or "")
            context = dict(self._login_context or {})
            nonce = str(self._login_nonce or "")

            manual_origin = str(
                self._login_manual_callback_origin
                or ""
            )

            listener = self._login_listener
            cancel_event = self._cancel_event
            thread = self._login_thread

        active = (
            auth_state == self.AUTH_LOGIN_PENDING
            and bool(attempt_id)
            and bool(current_attempt)
            and secrets.compare_digest(
                attempt_id,
                current_attempt,
            )
            and bool(context)
            and bool(nonce)
            and listener is not None
            and cancel_event is not None
            and not cancel_event.is_set()
            and thread is not None
            and thread.is_alive()
        )

        if not active:
            return {
                "accepted": False,
                "logged_in": False,
                "pending": (
                    auth_state
                    == self.AUTH_LOGIN_PENDING
                ),
                "auth_state": auth_state,
                "error": (
                    "Qobuz sign-in attempt is no longer active."
                ),
            }

        def invalid_completion():
            return {
                "accepted": False,
                "logged_in": False,
                "pending": True,
                "auth_state": self.AUTH_LOGIN_PENDING,
                "error": (
                    "Qobuz sign-in completion address is invalid. "
                    "Copy the full callback address from the browser."
                ),
            }

        if (
            not callback_url
            or len(callback_url)
            > self.CALLBACK_REQUEST_MAX_BYTES
            or not callback_url.isascii()
            or any(
                ord(char) <= 32
                or ord(char) == 127
                for char in callback_url
            )
        ):
            return invalid_completion()

        try:
            parsed = urlsplit(callback_url)
            callback_port = parsed.port
        except (TypeError, ValueError):
            return invalid_completion()

        host = str(parsed.hostname or "").lower()

        try:
            expected_port = int(
                context.get("callback_port") or 0
            )
        except (TypeError, ValueError):
            return invalid_completion()

        expected_path = f"/{nonce}"

        remote_valid = (
            parsed.scheme.lower()
            == "http"
            and host in (
                "localhost",
                "127.0.0.1",
            )
            and parsed.username is None
            and parsed.password is None
            and callback_port
            == expected_port
            and secrets.compare_digest(
                parsed.path,
                expected_path,
            )
            and not bool(
                parsed.fragment
            )
        )

        manual_valid = False

        if manual_origin:
            try:
                expected_manual = urlsplit(
                    manual_origin
                )
                expected_manual_port = (
                    expected_manual.port
                )
            except (
                TypeError,
                ValueError,
            ):
                expected_manual = None
                expected_manual_port = None

            expected_manual_host = (
                str(
                    expected_manual.hostname
                    if expected_manual
                    else ""
                )
                .strip()
                .lower()
            )

            expected_manual_path = (
                self.MANUAL_CALLBACK_PREFIX
                + nonce
            )

            manual_valid = bool(
                expected_manual
                and parsed.scheme.lower()
                == "http"
                and host
                == expected_manual_host
                and parsed.username is None
                and parsed.password is None
                and callback_port
                == expected_manual_port
                and secrets.compare_digest(
                    parsed.path,
                    expected_manual_path,
                )
                and not bool(
                    parsed.fragment
                )
            )

        if not (
            remote_valid
            or manual_valid
        ):
            return invalid_completion()

        # The existing Q2 loopback worker remains authoritative.
        target = f"/{nonce}"

        if parsed.query:
            target += (
                "?"
                + parsed.query
            )

        code = (
            self._parse_callback_request_line(
                f"GET {target} HTTP/1.1",
                nonce,
            )
        )

        if code is None:
            return invalid_completion()

        request = (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: localhost:{expected_port}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")

        try:
            with socket.create_connection(
                ("127.0.0.1", expected_port),
                timeout=2.0,
            ) as relay:
                relay.sendall(request)
        except OSError:
            with self._auth_lock:
                state = self._auth_state

            return {
                "accepted": False,
                "logged_in": False,
                "pending": (
                    state == self.AUTH_LOGIN_PENDING
                ),
                "auth_state": state,
                "error": (
                    "Qobuz sign-in attempt is no longer active."
                ),
            }

        logger.info(
            "Qobuz headless authentication callback accepted for relay"
        )

        return {
            "accepted": True,
            "logged_in": False,
            "pending": True,
            "auth_state": self.AUTH_LOGIN_PENDING,
        }

    def logout(self):
        """Cancel pending auth and clear only Qobuz user-session state."""
        with self._login_start_lock:
            return self._logout_locked()

    def _logout_locked(self):
        with self._auth_lock:
            self._attempt_id = secrets.token_hex(16)
            self._login_nonce = ""
            self._login_manual_callback_origin = ""
            cancel_event = self._cancel_event
            listener = self._login_listener
            self._cancel_event = None
            self._login_listener = None
            self._login_context = None
            self._login_thread = None
            self._session = None
            self.authenticated = False
            self._auth_state = self.AUTH_SIGNED_OUT
            self._last_error = ""
            self.initialization_error = ""
        with self._cmaf_lock:
            self._cmaf_session = None
        if cancel_event is not None:
            cancel_event.set()
        self._close_listener(listener)
        self._clear_session_file()
        logger.info("Qobuz session cleared")
        return True

    @staticmethod
    def _bind_login_listener():
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(4)
            listener.settimeout(0.2)
            if listener.getsockname()[0] != "127.0.0.1":
                raise OSError("unexpected callback bind")
            return listener
        except Exception:
            listener.close()
            raise

    def _login_worker(self, attempt_id, listener, nonce, cancel_event):
        try:
            deadline = time.monotonic() + self._auth_timeout
            code = self._capture_callback(listener, nonce, cancel_event, deadline)
            if cancel_event.is_set():
                return
            if not code:
                self._finish_attempt_error(attempt_id, "Qobuz sign-in timed out.")
                return
            # The callback is one-shot.  Release the port before performing
            # either of the Qobuz network exchanges.
            self._close_listener(listener)
            with self._auth_lock:
                if attempt_id == self._attempt_id:
                    self._login_listener = None
            logger.info("Qobuz callback received and state validated")
            session = self._exchange_code(code)
            with self._auth_lock:
                if attempt_id != self._attempt_id or cancel_event.is_set():
                    return
                self._persist_session(session["user_auth_token"])
                self._session = session
                self.available = True
                self.authenticated = True
                self._auth_state = self.AUTH_AUTHENTICATED
                self._last_error = ""
                self.initialization_error = ""
                self._login_nonce = ""
                self._login_context = None
            logger.info("Qobuz session established and persisted")
        except QobuzAuthRejected as exc:
            self._finish_attempt_error(attempt_id, "Qobuz rejected the sign-in.", exc)
        except Exception as exc:
            self._finish_attempt_error(attempt_id, "Qobuz sign-in failed.", exc)
        finally:
            self._close_listener(listener)
            with self._auth_lock:
                if attempt_id == self._attempt_id:
                    self._login_listener = None
                    self._login_nonce = ""
                    self._login_manual_callback_origin = ""
                    self._cancel_event = None
                    self._login_thread = None

    def _capture_callback(self, listener, nonce, cancel_event, deadline):
        while not cancel_event.is_set() and time.monotonic() < deadline:
            try:
                connection, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if cancel_event.is_set():
                    return None
                raise
            with connection:
                connection.settimeout(2.0)
                request = self._read_callback_request(connection)
                request_line = request.splitlines()[0] if request else ""
                code = self._parse_callback_request_line(request_line, nonce)
                self._send_callback_response(connection, success=code is not None)
                if code is not None:
                    return code
        return None

    def _read_callback_request(self, connection):
        chunks = bytearray()
        while len(chunks) < self.CALLBACK_REQUEST_MAX_BYTES:
            try:
                part = connection.recv(
                    min(2048, self.CALLBACK_REQUEST_MAX_BYTES - len(chunks))
                )
            except socket.timeout:
                break
            if not part:
                break
            chunks.extend(part)
            if b"\r\n\r\n" in chunks:
                break
        return bytes(chunks).decode("iso-8859-1", errors="replace")

    @staticmethod
    def _parse_callback_request_line(request_line, expected_nonce):
        parts = str(request_line or "").split()
        if len(parts) < 2 or parts[0].upper() != "GET":
            return None
        parsed = urlsplit(parts[1])
        if parsed.path != f"/{expected_nonce}":
            return None
        query = parse_qs(parsed.query, keep_blank_values=True)
        values = query.get("code_autorisation") or query.get("code") or []
        code = str(values[0] if values else "").strip()
        if (
            not code
            or len(code) > 4096
            or not code.isascii()
            or any(ord(char) <= 32 or ord(char) == 127 for char in code)
        ):
            return None
        return code

    @staticmethod
    def _send_callback_response(connection, success):
        if success:
            body = (
                "<html><body><h2>Qobuz sign-in complete</h2>"
                "<p>You can close this tab and return to SROVA.</p></body></html>"
            )
        else:
            body = "<html><body><h2>Waiting for Qobuz sign-in</h2></body></html>"
        encoded = body.encode("utf-8")
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Cache-Control: no-store\r\n"
            + f"Content-Length: {len(encoded)}\r\n".encode("ascii")
            + b"Connection: close\r\n\r\n"
            + encoded
        )
        try:
            connection.sendall(response)
        except OSError:
            pass

    def _exchange_code(self, code):
        metadata = self._get_service_metadata()
        try:
            response = self._http.get(
                self.API_BASE_URL + self.OAUTH_CALLBACK_PATH,
                headers={"X-App-Id": metadata["app_id"]},
                params={
                    "code": code,
                    "private_key": metadata["private_key"],
                    "app_id": metadata["app_id"],
                },
                timeout=(10, 30),
            )
        except requests.exceptions.RequestException as exc:
            raise QobuzAuthError("OAuth exchange request failed") from exc
        if response.status_code in (401, 403):
            raise QobuzAuthRejected("OAuth authorization rejected")
        if not 200 <= response.status_code < 300:
            if response.status_code == 400:
                self._expire_service_cache()
            raise QobuzAuthError("OAuth exchange service unavailable")
        payload = self._response_json(response)
        token = payload.get("token") if isinstance(payload, dict) else None
        if not self._valid_token(token):
            raise QobuzAuthError("OAuth exchange response invalid")
        return self._login_with_token(metadata["app_id"], token)

    def _login_with_token(self, app_id, token):
        try:
            response = self._http.post(
                self.API_BASE_URL + self.USER_LOGIN_PATH,
                headers={
                    "X-App-Id": app_id,
                    "X-User-Auth-Token": token,
                    "Content-Type": "text/plain;charset=UTF-8",
                },
                data="extra=partner",
                timeout=(10, 30),
            )
        except requests.exceptions.RequestException as exc:
            raise QobuzAuthError("User session request failed") from exc
        if response.status_code in (401, 403):
            raise QobuzAuthRejected("User token rejected")
        if not 200 <= response.status_code < 300:
            raise QobuzAuthError("User session service unavailable")
        return self._parse_user_session(self._response_json(response), token)

    @staticmethod
    def _response_json(response):
        try:
            value = response.json()
        except (TypeError, ValueError) as exc:
            raise QobuzAuthError("Qobuz returned an invalid response") from exc
        if not isinstance(value, dict):
            raise QobuzAuthError("Qobuz returned an invalid response")
        return value

    @classmethod
    def _parse_user_session(cls, payload, fallback_token):
        user = payload.get("user") if isinstance(payload, dict) else None
        if not isinstance(user, dict):
            raise QobuzAuthError("Qobuz user session is incomplete")
        credential = user.get("credential")
        parameters = credential.get("parameters") if isinstance(credential, dict) else None
        if not isinstance(parameters, dict) or not parameters:
            raise QobuzAuthRejected("Qobuz subscription is not eligible")
        token = payload.get("user_auth_token") or fallback_token
        if not cls._valid_token(token):
            raise QobuzAuthError("Qobuz user session has no token")
        valid_until = None
        for key in (
            "end_date",
            "expiration_date",
            "valid_until",
            "expires_at",
            "expiry_date",
        ):
            value = parameters.get(key)
            if isinstance(value, str) and value.strip():
                valid_until = value.strip()
                break
        return {
            "user_auth_token": token,
            "user_id": user.get("id"),
            "display_name": str(user.get("display_name") or user.get("login") or ""),
            "subscription": str(parameters.get("short_label") or "Unknown"),
            "subscription_valid_until": valid_until,
            "country_code": user.get("country_code"),
            "language_code": user.get("language_code"),
        }

    def resolve_track_delivery(self, track_id, format_id):
        """Resolve one authenticated Qobuz track to verified CMAF metadata.

        The returned object contains ephemeral signed-delivery and key material
        in memory. Its representation and ``safe_summary`` deliberately omit
        those fields. This method performs no playback or persistence work.
        """
        track_id = self._positive_int(track_id, "track ID")
        format_id = self._positive_int(format_id, "format ID")
        if format_id not in self.CMAF_FORMAT_IDS:
            raise QobuzDeliveryError("Unsupported Qobuz format ID")

        app_id, token = self._delivery_auth_context()
        cmaf_session = self._ensure_cmaf_session(app_id, token)
        timestamp = int(self._now())
        arguments = {
            "track_id": track_id,
            "format_id": format_id,
            "intent": "stream",
        }
        signature = compute_request_signature(
            "fileurl",
            arguments,
            timestamp,
            self.CMAF_SEED,
        )
        headers = self._delivery_headers(app_id, token)
        headers["X-Session-Id"] = cmaf_session["session_id"]
        params = {
            "track_id": str(track_id),
            "format_id": str(format_id),
            "intent": "stream",
            "request_ts": str(timestamp),
            "request_sig": signature,
        }
        try:
            response = self._http.get(
                self.API_BASE_URL + self.CMAF_FILE_URL_PATH,
                headers=headers,
                params=params,
                timeout=(10, 30),
            )
        except requests.exceptions.RequestException as exc:
            raise QobuzDeliveryError("Qobuz delivery request failed") from exc
        try:
            self._raise_delivery_status(response, "file URL", track_id=track_id)
        except QobuzDeliveryRejected:
            self._discard_cmaf_session(cmaf_session["session_id"])
            raise
        payload = self._delivery_json(response, "file URL")

        url_template = payload.get("url_template")
        if not isinstance(url_template, str) or len(url_template) > 16384:
            raise QobuzDeliveryError("Qobuz delivery URL template is missing")
        parsed_url = urlsplit(url_template)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.netloc
            or "$SEGMENT$" not in url_template
        ):
            raise QobuzDeliveryError("Qobuz delivery URL template is invalid")

        n_segments = self._positive_int(
            payload.get("n_segments"),
            "segment count",
            maximum=255,
        )
        key_string = payload.get("key")
        if (
            not isinstance(key_string, str)
            or not 1 <= len(key_string) <= 8192
            or not key_string.isascii()
        ):
            raise QobuzDeliveryError("Qobuz wrapped content key is missing")
        returned_format_id = payload.get("format_id")
        if returned_format_id is not None:
            returned_format_id = self._positive_int(
                returned_format_id,
                "returned format ID",
            )
        if (
            returned_format_id is not None
            and returned_format_id not in self.CMAF_FORMAT_IDS
        ):
            raise QobuzDeliveryError("Qobuz returned an unsupported format ID")
        mime_type = str(payload.get("mime_type") or "").strip()
        if len(mime_type) > 128:
            raise QobuzDeliveryError("Qobuz delivery MIME type is invalid")

        try:
            session_key = derive_session_key(
                self.CMAF_SEED,
                cmaf_session["infos"],
            )
            content_key = unwrap_content_key(session_key, key_string)
        except QobuzCmafError as exc:
            raise QobuzDeliveryError("Qobuz content key could not be derived") from exc

        init_bytes = self._download_cmaf_bytes(
            url_template.replace("$SEGMENT$", "0"),
            self.CMAF_INIT_MAX_BYTES,
            "initialization segment",
        )
        try:
            init_info = parse_init_segment(init_bytes)
        except QobuzCmafError as exc:
            raise QobuzDeliveryError(
                "Qobuz initialization segment is invalid"
            ) from exc
        if init_info.track_id not in (0, track_id):
            raise QobuzDeliveryError("Qobuz initialization track ID does not match")
        if len(init_info.segment_table) != n_segments:
            raise QobuzDeliveryError(
                "Qobuz segment table does not match the delivery response"
            )
        actual_format_id = flac_format_id(
            init_info.sample_rate,
            init_info.bit_depth,
        )

        return QobuzCmafDelivery(
            track_id=track_id,
            requested_format_id=format_id,
            returned_format_id=returned_format_id,
            actual_format_id=actual_format_id,
            mime_type=mime_type,
            sample_rate=init_info.sample_rate,
            bit_depth=init_info.bit_depth,
            channels=init_info.channels,
            total_samples=init_info.total_samples,
            n_segments=n_segments,
            flac_header=init_info.flac_header,
            segment_table=init_info.segment_table,
            url_template=url_template,
            content_key=content_key,
        )

    def fetch_decrypt_cmaf_segment(self, delivery, segment_index):
        """Fetch and decrypt one audio segment without caching or playback."""
        if not isinstance(delivery, QobuzCmafDelivery):
            raise QobuzDeliveryError("Invalid Qobuz delivery object")
        segment_index = self._positive_int(segment_index, "segment index")
        if segment_index > delivery.n_segments:
            raise QobuzDeliveryError("Qobuz segment index is out of range")
        encrypted = self._download_cmaf_bytes(
            delivery.url_template.replace("$SEGMENT$", str(segment_index)),
            self.CMAF_SEGMENT_MAX_BYTES,
            "audio segment",
        )
        try:
            return decrypt_segment(
                delivery.content_key,
                encrypted,
                expected_length=delivery.segment_table[segment_index - 1].byte_len,
            )
        except QobuzCmafError as exc:
            raise QobuzDeliveryError("Qobuz audio segment is invalid") from exc

    def reconstruct_flac_for_validation(self, delivery):
        """Sequentially reconstruct one bounded FLAC proof entirely in memory."""
        if not isinstance(delivery, QobuzCmafDelivery):
            raise QobuzDeliveryError("Invalid Qobuz delivery object")
        if delivery.virtual_flac_length > self.CMAF_PROOF_MAX_FLAC_BYTES:
            raise QobuzDeliveryError("Qobuz FLAC proof exceeds its memory bound")
        output = bytearray(delivery.flac_header)
        for segment_index in range(1, delivery.n_segments + 1):
            output.extend(
                self.fetch_decrypt_cmaf_segment(delivery, segment_index)
            )
        if len(output) != delivery.virtual_flac_length:
            raise QobuzDeliveryError("Reconstructed Qobuz FLAC length is invalid")
        try:
            validate_flac_structure(output)
        except QobuzCmafError as exc:
            raise QobuzDeliveryError("Reconstructed Qobuz FLAC is invalid") from exc
        return bytes(output)

    def _delivery_auth_context(self):
        with self._auth_lock:
            session = self._session
            if not self.authenticated or not isinstance(session, dict):
                raise QobuzDeliveryRejected("Qobuz authentication is required")
            token = session.get("user_auth_token")
            if not self._valid_token(token):
                raise QobuzDeliveryRejected("Qobuz authentication is invalid")
        metadata = self._get_service_metadata()
        app_id = str(metadata.get("app_id") or "")
        if re.fullmatch(r"\d{9}", app_id) is None:
            raise QobuzDeliveryError("Qobuz application metadata is invalid")
        return app_id, token

    @staticmethod
    def _delivery_headers(app_id, token):
        return {
            "X-App-Id": app_id,
            "X-User-Auth-Token": token,
            "User-Agent": "Mozilla/5.0",
        }

    def _ensure_cmaf_session(self, app_id, token):
        with self._cmaf_lock:
            now = int(self._now())
            cached = self._cmaf_session
            if (
                isinstance(cached, dict)
                and cached.get("expires_at", 0)
                > now + self.CMAF_SESSION_RENEWAL_SKEW
            ):
                return dict(cached)

            timestamp = int(self._now())
            arguments = {"profile": self.CMAF_PROFILE}
            signature = compute_request_signature(
                "sessionstart",
                arguments,
                timestamp,
                self.CMAF_SEED,
            )
            try:
                response = self._http.post(
                    self.API_BASE_URL + self.CMAF_SESSION_PATH,
                    headers=self._delivery_headers(app_id, token),
                    data={
                        "profile": self.CMAF_PROFILE,
                        "request_ts": str(timestamp),
                        "request_sig": signature,
                    },
                    timeout=(10, 30),
                )
            except requests.exceptions.RequestException as exc:
                raise QobuzDeliveryError(
                    "Qobuz playback session request failed"
                ) from exc
            self._raise_delivery_status(response, "playback session")
            payload = self._delivery_json(response, "playback session")
            session_id = payload.get("session_id")
            infos = payload.get("infos")
            expires_at = self._positive_int(
                payload.get("expires_at"),
                "playback-session expiry",
            )
            if (
                not isinstance(session_id, str)
                or not 1 <= len(session_id) <= 8192
                or not session_id.isascii()
                or any(ord(char) <= 32 or ord(char) == 127 for char in session_id)
            ):
                raise QobuzDeliveryError("Qobuz playback session ID is invalid")
            if (
                not isinstance(infos, str)
                or not 1 <= len(infos) <= 8192
                or not infos.isascii()
            ):
                raise QobuzDeliveryError("Qobuz playback-session infos are invalid")
            if expires_at <= now + self.CMAF_SESSION_RENEWAL_SKEW:
                raise QobuzDeliveryError("Qobuz playback session is already expired")
            try:
                derive_session_key(self.CMAF_SEED, infos)
            except QobuzCmafError as exc:
                raise QobuzDeliveryError(
                    "Qobuz playback-session infos are invalid"
                ) from exc
            cached = {
                "session_id": session_id,
                "infos": infos,
                "expires_at": expires_at,
            }
            self._cmaf_session = cached
            return dict(cached)

    def _discard_cmaf_session(self, session_id):
        with self._cmaf_lock:
            cached = self._cmaf_session
            if isinstance(cached, dict) and cached.get("session_id") == session_id:
                self._cmaf_session = None

    @staticmethod
    def _raise_delivery_status(response, context, track_id=None):
        status = int(getattr(response, "status_code", 0) or 0)
        if 200 <= status < 300:
            return
        if status in (401, 403):
            raise QobuzDeliveryRejected(f"Qobuz rejected the {context} request")
        if status == 404 and track_id is not None:
            raise QobuzTrackUnavailable(f"Qobuz track {track_id} is unavailable")
        raise QobuzDeliveryError(f"Qobuz {context} request failed")

    @staticmethod
    def _delivery_json(response, context):
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise QobuzDeliveryError(
                f"Qobuz {context} response is invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise QobuzDeliveryError(f"Qobuz {context} response is invalid")
        return payload

    def _download_cmaf_bytes(self, url, maximum_bytes, context):
        try:
            with self._http.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=(10, 45),
                stream=True,
            ) as response:
                self._raise_delivery_status(response, context)
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except (TypeError, ValueError) as exc:
                        raise QobuzDeliveryError(
                            f"Qobuz {context} length is invalid"
                        ) from exc
                    if declared_length < 0 or declared_length > maximum_bytes:
                        raise QobuzDeliveryError(
                            f"Qobuz {context} exceeds its size limit"
                        )
                chunks = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    chunks.extend(chunk)
                    if len(chunks) > maximum_bytes:
                        raise QobuzDeliveryError(
                            f"Qobuz {context} exceeds its size limit"
                        )
        except requests.exceptions.RequestException as exc:
            raise QobuzDeliveryError(f"Qobuz {context} request failed") from exc
        if not chunks:
            raise QobuzDeliveryError(f"Qobuz {context} response is empty")
        return bytes(chunks)

    @staticmethod
    def _positive_int(value, label, maximum=None):
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise QobuzDeliveryError(f"Qobuz {label} is invalid")
        if isinstance(value, str) and (
            not value.isascii() or not value.isdigit()
        ):
            raise QobuzDeliveryError(f"Qobuz {label} is invalid")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise QobuzDeliveryError(f"Qobuz {label} is invalid") from exc
        if parsed <= 0 or (maximum is not None and parsed > maximum):
            raise QobuzDeliveryError(f"Qobuz {label} is invalid")
        return parsed

    @staticmethod
    def _valid_token(token):
        return (
            isinstance(token, str)
            and token == token.strip()
            and 1 <= len(token) <= 8192
            and token.isascii()
            and not any(ord(char) <= 32 or ord(char) == 127 for char in token)
        )

    def _get_service_metadata(self, require_app_secrets=False):
        with self._service_lock:
            cached = self._service_metadata or self._load_service_cache()
            if (
                cached
                and self._service_cache_fresh(cached)
                and (
                    not require_app_secrets
                    or self._valid_app_secrets(
                        cached.get("app_secrets")
                    )
                )
            ):
                self._service_metadata = cached
                self.available = True
                return cached
            try:
                login_page = self._download_text(self.LOGIN_PAGE_URL, max_bytes=1024 * 1024)
                match = self._BUNDLE_URL_RE.search(login_page)
                if not match:
                    raise QobuzAuthError("Qobuz web-player bundle was not found")
                bundle_url = match.group("url")
                if (
                    cached
                    and cached.get("bundle_url") == bundle_url
                    and (
                        not require_app_secrets
                        or self._valid_app_secrets(
                            cached.get("app_secrets")
                        )
                    )
                ):
                    cached["fetched_at"] = int(self._now())
                    self._save_service_cache(cached)
                    self._service_metadata = cached
                    self.available = True
                    return cached
                bundle = self._download_text(self.BUNDLE_BASE_URL + bundle_url)
                app_match = self._APP_ID_RE.search(bundle)
                key_match = self._PRIVATE_KEY_RE.search(bundle)

                if not app_match or not key_match:
                    raise QobuzAuthError(
                        "Required Qobuz authentication "
                        "metadata was not found"
                    )

                app_secrets = self._extract_app_secrets(
                    bundle
                )

                if (
                    require_app_secrets
                    and not app_secrets
                ):
                    raise QobuzAuthError(
                        "Required Qobuz catalog signing "
                        "metadata was not found"
                    )

                metadata = {
                    "version": 2,
                    "bundle_url": bundle_url,
                    "bundle_version": (
                        bundle_url.split("/")[2]
                    ),
                    "app_id": app_match.group("app_id"),
                    "private_key": (
                        key_match.group("private_key")
                    ),
                    "app_secrets": app_secrets,
                    "fetched_at": int(self._now()),
                }
                self._save_service_cache(metadata)
                self._service_metadata = metadata
                self.available = True
                logger.info("Qobuz authentication service metadata refreshed")
                return metadata
            except Exception:
                if (
                    cached
                    and (
                        not require_app_secrets
                        or self._valid_app_secrets(
                            cached.get("app_secrets")
                        )
                    )
                ):
                    self._service_metadata = cached
                    self.available = True
                    logger.warning(
                        "Qobuz metadata refresh failed; "
                        "using cached metadata"
                    )
                    return cached
                raise


    # Q6H2A_LABEL_CORE_CANDIDATE

    @staticmethod
    def _catalog_label_required_text(
        value,
        label,
        *,
        maximum=16384,
    ):
        if not isinstance(value, str):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} is invalid.",
            )

        text = value.strip()

        if (
            not text
            or len(text) > maximum
            or "\x00" in text
        ):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} is invalid.",
            )

        return text

    @classmethod
    def _catalog_label_optional_text(
        cls,
        value,
        label,
        *,
        maximum=16384,
    ):
        if value is None:
            return None

        if not isinstance(value, str):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} is invalid.",
            )

        text = value.strip()

        if not text:
            return None

        if (
            len(text) > maximum
            or "\x00" in text
        ):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} is invalid.",
            )

        return text

    @staticmethod
    def _catalog_label_optional_nonnegative_int(
        value,
        label,
    ):
        if value is None:
            return None

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} is invalid.",
            )

        return value

    @staticmethod
    def _catalog_label_optional_bool(
        value,
        label,
    ):
        if value is None:
            return None

        if not isinstance(value, bool):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} is invalid.",
            )

        return value

    @classmethod
    def _catalog_label_name_display(
        cls,
        value,
        label,
    ):
        if isinstance(value, str):
            return cls._catalog_label_required_text(
                value,
                label,
                maximum=4096,
            )

        if isinstance(value, dict):
            return cls._catalog_label_required_text(
                value.get("display"),
                label,
                maximum=4096,
            )

        raise QobuzCatalogError(
            "malformed_response",
            f"Qobuz {label} is invalid.",
        )

    @classmethod
    def _normalize_qobuz_label_image_value(
        cls,
        value,
        *,
        keys=(
            "mega",
            "extralarge",
            "large",
            "medium",
            "thumbnail",
            "small",
        ),
        label="label image",
    ):
        if value is None:
            return None

        if isinstance(value, str):
            return cls._catalog_label_optional_text(
                value,
                label,
                maximum=16384,
            )

        if not isinstance(value, dict):
            return None

        for key in keys:
            candidate = value.get(key)

            if candidate is None:
                continue

            if not isinstance(candidate, str):
                continue

            text = cls._catalog_label_optional_text(
                candidate,
                f"{label} {key}",
                maximum=16384,
            )

            if text is not None:
                return text

        return None

    @classmethod
    def _catalog_label_roles(
        cls,
        value,
    ):
        if value is None:
            return None

        if not isinstance(value, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label artist roles are invalid.",
            )

        roles = []

        for role in value:
            roles.append(
                cls._catalog_label_required_text(
                    role,
                    "label artist role",
                    maximum=256,
                )
            )

        return roles

    @classmethod
    def _catalog_label_artist_identity(
        cls,
        value,
        *,
        label,
        require_id=True,
    ):
        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} is invalid.",
            )

        name = cls._catalog_label_name_display(
            value.get("name"),
            f"{label} name",
        )

        artist_id = None

        if value.get("id") is not None:
            artist_id = cls._catalog_required_response_numeric_id(
                value.get("id"),
                label,
            )
        elif require_id:
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} ID is invalid.",
            )

        return {
            "id": artist_id,
            "name": name,
            "roles": cls._catalog_label_roles(
                value.get("roles")
            ),
        }

    @classmethod
    def _normalize_qobuz_label_album(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label album response is invalid.",
            )

        adapted = dict(payload)

        contributors = []
        artists_value = payload.get("artists")

        if artists_value is not None:
            if not isinstance(artists_value, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz label album artist list is invalid.",
                )

            for artist in artists_value:
                contributors.append(
                    cls._catalog_label_artist_identity(
                        artist,
                        label="label album artist",
                        require_id=True,
                    )
                )

        primary = None

        if contributors:
            primary = next(
                (
                    artist
                    for artist in contributors
                    if (
                        isinstance(artist.get("roles"), list)
                        and "main-artist" in artist["roles"]
                    )
                ),
                contributors[0],
            )

        if primary is None:
            singular = payload.get("artist")

            if isinstance(singular, dict):
                try:
                    primary = cls._catalog_label_artist_identity(
                        singular,
                        label="label album primary artist",
                        require_id=False,
                    )
                except QobuzCatalogError:
                    primary = None

        if primary is not None:
            adapted["artist"] = {
                "id": (
                    int(primary["id"])
                    if primary.get("id") is not None
                    else 0
                ),
                "name": primary["name"],
            }

        normalized = cls._normalize_qobuz_album(
            adapted
        )

        if contributors:
            normalized["artists"] = [
                {
                    "id": artist["id"],
                    "name": artist["name"],
                    "roles": artist["roles"],
                }
                for artist in contributors
            ]

        return normalized

    @classmethod
    def _catalog_label_pick_track_artist(
        cls,
        payload,
    ):
        artists = payload.get("artists")

        if artists is not None:
            if not isinstance(artists, list):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz label track artist list is invalid.",
                )

            parsed = []

            for raw in artists:
                parsed.append(
                    cls._catalog_label_artist_identity(
                        raw,
                        label="label track artist",
                        require_id=False,
                    )
                )

            if parsed:
                return next(
                    (
                        artist
                        for artist in parsed
                        if (
                            isinstance(
                                artist.get("roles"),
                                list,
                            )
                            and "main-artist" in artist["roles"]
                        )
                    ),
                    parsed[0],
                )

        candidates = [
            payload.get("performer"),
            payload.get("artist"),
        ]

        album = payload.get("album")

        if isinstance(album, dict):
            candidates.append(
                album.get("artist")
            )

        for raw in candidates:
            if not isinstance(raw, dict):
                continue

            try:
                return cls._catalog_label_artist_identity(
                    raw,
                    label="label track artist",
                    require_id=False,
                )
            except QobuzCatalogError:
                continue

        return None

    @classmethod
    def _normalize_qobuz_label_top_track(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label track response is invalid.",
            )

        adapted = dict(payload)
        primary = cls._catalog_label_pick_track_artist(
            payload
        )

        if primary is not None:
            adapted["performer"] = {
                "id": (
                    int(primary["id"])
                    if primary.get("id") is not None
                    else 0
                ),
                "name": primary["name"],
            }

        audio_info = payload.get("audio_info")

        if audio_info is not None:
            if not isinstance(audio_info, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz label track audio information is invalid.",
                )

            for key in (
                "maximum_sampling_rate",
                "maximum_bit_depth",
            ):
                if (
                    adapted.get(key) is None
                    and audio_info.get(key) is not None
                ):
                    adapted[key] = audio_info.get(key)

        rights = payload.get("rights")

        if rights is not None:
            if not isinstance(rights, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz label track rights are invalid.",
                )

            for key in (
                "streamable",
                "hires_streamable",
            ):
                if rights.get(key) is not None:
                    if not isinstance(
                        rights.get(key),
                        bool,
                    ):
                        raise QobuzCatalogError(
                            "malformed_response",
                            "Qobuz label track rights are invalid.",
                        )

                    adapted[key] = rights.get(key)

        return cls._normalize_qobuz_track(
            adapted
        )

    @classmethod
    def _normalize_qobuz_label_playlist_image(
        cls,
        payload,
    ):
        image = payload.get("image")

        if isinstance(image, dict):
            rectangle = image.get("rectangle")

            if isinstance(rectangle, str):
                value = cls._catalog_label_optional_text(
                    rectangle,
                    "label playlist rectangle image",
                    maximum=16384,
                )

                if value is not None:
                    return value

            covers = image.get("covers")

            if isinstance(covers, list):
                for raw in covers:
                    if not isinstance(raw, str):
                        continue

                    value = cls._catalog_label_optional_text(
                        raw,
                        "label playlist cover image",
                        maximum=16384,
                    )

                    if value is not None:
                        return value

            image_url = cls._normalize_qobuz_label_image_value(
                image,
                keys=(
                    "large",
                    "thumbnail",
                    "small",
                ),
                label="label playlist image",
            )

            if image_url is not None:
                return image_url

        for key in (
            "images300",
            "images150",
            "images",
        ):
            values = payload.get(key)

            if not isinstance(values, list):
                continue

            for raw in values:
                if not isinstance(raw, str):
                    continue

                value = cls._catalog_label_optional_text(
                    raw,
                    f"label playlist {key} image",
                    maximum=16384,
                )

                if value is not None:
                    return value

        return None

    @classmethod
    def _normalize_qobuz_label_playlist(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label playlist response is invalid.",
            )

        playlist_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "label playlist",
        )
        title = cls._catalog_label_required_text(
            payload.get("name"),
            "label playlist name",
            maximum=16384,
        )

        owner_id = None
        owner_name = None
        owner = payload.get("owner")

        if owner is not None:
            if not isinstance(owner, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz label playlist owner is invalid.",
                )

            if owner.get("id") is not None:
                owner_id = cls._catalog_required_response_numeric_id(
                    owner.get("id"),
                    "label playlist owner",
                )

            owner_name = cls._catalog_label_optional_text(
                owner.get("name"),
                "label playlist owner name",
                maximum=4096,
            )

        track_count = cls._catalog_label_optional_nonnegative_int(
            payload.get("tracks_count"),
            "label playlist track count",
        )
        duration = cls._catalog_label_optional_nonnegative_int(
            payload.get("duration"),
            "label playlist duration",
        )

        return {
            "playlist_id": playlist_id,
            "title": title,
            "description": cls._catalog_label_optional_text(
                payload.get("description"),
                "label playlist description",
                maximum=65536,
            ),
            "owner_id": owner_id,
            "owner_name": owner_name,
            "track_count": (
                0
                if track_count is None
                else track_count
            ),
            "duration": (
                0
                if duration is None
                else duration
            ),
            "artwork_url": (
                cls._normalize_qobuz_label_playlist_image(
                    payload
                )
            ),
        }

    @classmethod
    def _normalize_qobuz_label_artist(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label artist response is invalid.",
            )

        artist_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "label artist",
        )
        name = cls._catalog_label_name_display(
            payload.get("name"),
            "label artist name",
        )

        artwork_url = cls._normalize_qobuz_label_image_value(
            payload.get("image"),
            keys=(
                "large",
                "extralarge",
                "medium",
                "thumbnail",
                "small",
            ),
            label="label artist image",
        )

        if artwork_url is None:
            picture = payload.get("picture")

            if isinstance(picture, str):
                artwork_url = cls._catalog_label_optional_text(
                    picture,
                    "label artist picture",
                    maximum=16384,
                )

        if artwork_url is None:
            images = payload.get("images")

            if isinstance(images, dict):
                portrait = images.get("portrait")

                if isinstance(portrait, dict):
                    try:
                        image_hash = cls._catalog_label_required_text(
                            portrait.get("hash"),
                            "label artist portrait hash",
                            maximum=4096,
                        )
                        image_format = cls._catalog_label_required_text(
                            portrait.get("format"),
                            "label artist portrait format",
                            maximum=128,
                        )

                        artwork_url = (
                            "https://static.qobuz.com/images/"
                            "artists/covers/medium/"
                            f"{image_hash}.{image_format}"
                        )
                    except QobuzCatalogError:
                        artwork_url = None

        return {
            "artist_id": artist_id,
            "name": name,
            "artwork_url": artwork_url,
        }

    @classmethod
    def _normalize_qobuz_label_explore_row(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label explore row is invalid.",
            )

        return {
            "label_id": (
                cls._catalog_required_response_numeric_id(
                    payload.get("id"),
                    "label explore label",
                )
            ),
            "name": (
                cls._catalog_label_required_text(
                    payload.get("name"),
                    "label explore name",
                    maximum=4096,
                )
            ),
            "artwork_url": (
                cls._normalize_qobuz_label_image_value(
                    payload.get("image"),
                    keys=(
                        "large",
                        "thumbnail",
                        "small",
                    ),
                    label="label explore image",
                )
            ),
        }

    @classmethod
    def _normalize_qobuz_label_generic_list(
        cls,
        value,
        *,
        row_normalizer,
        label,
    ):
        if value is None:
            return {
                "has_more": None,
                "items": [],
            }

        if not isinstance(value, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} section is invalid.",
            )

        has_more = cls._catalog_label_optional_bool(
            value.get("has_more"),
            f"{label} pagination",
        )
        items = value.get("items")

        if items is None:
            items = []

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} item list is invalid.",
            )

        normalized = []

        for raw in items:
            try:
                item = row_normalizer(raw)
            except QobuzCatalogError:
                continue

            normalized.append(item)

        return {
            "has_more": has_more,
            "items": normalized,
        }

    @classmethod
    def _normalize_qobuz_label_release_container(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label release container is invalid.",
            )

        container_id = cls._catalog_label_optional_text(
            payload.get("id"),
            "label release container ID",
            maximum=512,
        )
        data = payload.get("data")

        page = cls._normalize_qobuz_label_generic_list(
            data,
            row_normalizer=cls._normalize_qobuz_label_album,
            label="label release",
        )

        return {
            "id": container_id,
            **page,
        }

    @classmethod
    def _normalize_qobuz_label_page(
        cls,
        payload,
    ):
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label-page response is invalid.",
            )

        label_id = cls._catalog_required_response_numeric_id(
            payload.get("id"),
            "label-page label",
        )
        name = cls._catalog_label_required_text(
            payload.get("name"),
            "label-page name",
            maximum=4096,
        )

        releases_value = payload.get("releases")

        if releases_value is None:
            releases_value = []

        if not isinstance(releases_value, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label-page release list is invalid.",
            )

        release_groups = []

        for raw in releases_value:
            try:
                group = cls._normalize_qobuz_label_release_container(
                    raw
                )
            except QobuzCatalogError:
                continue

            release_groups.append(group)

        top_tracks_value = payload.get("top_tracks")

        if top_tracks_value is None:
            top_tracks_value = []

        if not isinstance(top_tracks_value, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label-page top-track list is invalid.",
            )

        top_tracks = []

        for raw in top_tracks_value:
            try:
                item = cls._normalize_qobuz_label_top_track(
                    raw
                )
            except QobuzCatalogError:
                continue

            top_tracks.append(item)

        return {
            "ok": True,
            "label_id": label_id,
            "name": name,
            "description": (
                cls._catalog_label_optional_text(
                    payload.get("description"),
                    "label-page description",
                    maximum=65536,
                )
            ),
            "artwork_url": (
                cls._normalize_qobuz_label_image_value(
                    payload.get("image"),
                    keys=(
                        "mega",
                        "extralarge",
                        "large",
                        "thumbnail",
                        "small",
                    ),
                    label="label-page image",
                )
            ),
            "release_groups": release_groups,
            "playlists": (
                cls._normalize_qobuz_label_generic_list(
                    payload.get("playlists"),
                    row_normalizer=cls._normalize_qobuz_label_playlist,
                    label="label playlist",
                )
            ),
            "top_tracks": top_tracks,
            "top_artists": (
                cls._normalize_qobuz_label_generic_list(
                    payload.get("top_artists"),
                    row_normalizer=cls._normalize_qobuz_label_artist,
                    label="label top-artist",
                )
            ),
        }

    def get_label_page(
        self,
        label_id,
    ):
        """Return one provider-native Qobuz label landing-page snapshot."""
        native_id = self._catalog_numeric_request_id(
            label_id,
            "label ID",
        )

        params = {
            "label_id": native_id,
        }

        payload = self._catalog_request(
            "/label/page",
            method_name="labelpage",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        return self._normalize_qobuz_label_page(
            payload
        )

    def get_label_explore(
        self,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded provider-native Qobuz label-explore page."""
        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        payload = self._catalog_request(
            "/label/explore",
            method_name="labelexplore",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label-explore response is invalid.",
            )

        has_more = self._catalog_label_optional_bool(
            payload.get("has_more"),
            "label-explore pagination",
        )
        items = payload.get("items")

        if items is None:
            items = []

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label-explore item list is invalid.",
            )

        if len(items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label-explore response exceeded the requested page limit.",
            )

        normalized = []

        for raw in items:
            try:
                item = self._normalize_qobuz_label_explore_row(
                    raw
                )
            except QobuzCatalogError:
                continue

            normalized.append(item)

        return {
            "ok": True,
            "items": normalized,
            "offset": page_offset,
            "limit": page_limit,
            "has_more": has_more,
        }

    def get_label_albums(
        self,
        label_id,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded provider-native Qobuz label album page."""
        native_id = self._catalog_numeric_request_id(
            label_id,
            "label ID",
        )
        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "label_id": native_id,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        payload = self._catalog_request(
            "/label/getAlbums",
            method_name="labelgetalbums",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label album-page response is invalid.",
            )

        has_more = self._catalog_label_optional_bool(
            payload.get("has_more"),
            "label album-page pagination",
        )
        total = self._catalog_label_optional_nonnegative_int(
            payload.get("total"),
            "label album-page total",
        )

        self._catalog_label_optional_nonnegative_int(
            payload.get("offset"),
            "label album-page provider offset",
        )
        self._catalog_label_optional_nonnegative_int(
            payload.get("limit"),
            "label album-page provider limit",
        )

        items = payload.get("items")

        if items is None:
            items = []

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label album-page item list is invalid.",
            )

        if len(items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz label album-page response exceeded the requested page limit.",
            )

        return {
            "ok": True,
            "label_id": native_id,
            "items": [
                self._normalize_qobuz_label_album(
                    item
                )
                for item in items
            ],
            "offset": page_offset,
            "limit": page_limit,
            "total": total,
            "has_more": has_more,
        }


    # Q6H2B_LABEL_SUBRESOURCES_CANDIDATE

    @classmethod
    def _normalize_qobuz_label_typed_page(
        cls,
        payload,
        *,
        row_normalizer,
        page_limit,
        page_offset,
        label,
    ):
        """Normalize one strict typed LabelListPage provider response."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response is invalid.",
            )

        has_more = cls._catalog_label_optional_bool(
            payload.get("has_more"),
            f"{label} pagination",
        )
        total = cls._catalog_label_optional_nonnegative_int(
            payload.get("total"),
            f"{label} total",
        )

        cls._catalog_label_optional_nonnegative_int(
            payload.get("offset"),
            f"{label} provider offset",
        )
        cls._catalog_label_optional_nonnegative_int(
            payload.get("limit"),
            f"{label} provider limit",
        )

        items = payload.get("items")

        if items is None:
            items = []

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} item list is invalid.",
            )

        if len(items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} response exceeded the requested page limit.",
            )

        return {
            "items": [
                row_normalizer(item)
                for item in items
            ],
            "offset": page_offset,
            "limit": page_limit,
            "total": total,
            "has_more": has_more,
        }

    def get_label_next_releases(
        self,
        label_id,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded Qobuz label upcoming-release page."""
        native_id = self._catalog_numeric_request_id(
            label_id,
            "label ID",
        )
        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "label_id": native_id,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        payload = self._catalog_request(
            "/label/getNextReleases",
            method_name="labelgetnextreleases",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        page = self._normalize_qobuz_label_typed_page(
            payload,
            row_normalizer=self._normalize_qobuz_label_album,
            page_limit=page_limit,
            page_offset=page_offset,
            label="label next-release page",
        )

        return {
            "ok": True,
            "label_id": native_id,
            **page,
        }

    def get_label_awarded_releases(
        self,
        label_id,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded Qobuz label awarded-release page."""
        native_id = self._catalog_numeric_request_id(
            label_id,
            "label ID",
        )
        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "label_id": native_id,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        payload = self._catalog_request(
            "/label/getAwardedReleases",
            method_name="labelgetawardedreleases",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        page = self._normalize_qobuz_label_typed_page(
            payload,
            row_normalizer=self._normalize_qobuz_label_album,
            page_limit=page_limit,
            page_offset=page_offset,
            label="label awarded-release page",
        )

        return {
            "ok": True,
            "label_id": native_id,
            **page,
        }

    def get_label_playlists(
        self,
        label_id,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded Qobuz label curated-playlist page."""
        native_id = self._catalog_numeric_request_id(
            label_id,
            "label ID",
        )
        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "label_id": native_id,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        payload = self._catalog_request(
            "/label/getPlaylists",
            method_name="labelgetplaylists",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        page = self._normalize_qobuz_label_typed_page(
            payload,
            row_normalizer=self._normalize_qobuz_label_playlist,
            page_limit=page_limit,
            page_offset=page_offset,
            label="label playlist page",
        )

        return {
            "ok": True,
            "label_id": native_id,
            **page,
        }

    def get_label_top_artists(
        self,
        label_id,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded Qobuz label top-artist page."""
        native_id = self._catalog_numeric_request_id(
            label_id,
            "label ID",
        )
        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "label_id": native_id,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        payload = self._catalog_request(
            "/label/getTopArtists",
            method_name="labelgettopartists",
            params=params,
            signature_params=dict(params),
            require_auth=False,
        )

        page = self._normalize_qobuz_label_typed_page(
            payload,
            row_normalizer=self._normalize_qobuz_label_artist,
            page_limit=page_limit,
            page_offset=page_offset,
            label="label top-artist page",
        )

        return {
            "ok": True,
            "label_id": native_id,
            **page,
        }



    @staticmethod
    def _catalog_purchase_type(value):
        """Validate the optional provider purchase type without coercion."""
        if value is None:
            return None

        if (
            not isinstance(value, str)
            or value not in ("albums", "tracks")
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz purchase type is invalid.",
            )

        return value

    @classmethod
    def _normalize_qobuz_purchase_album(
        cls,
        payload,
    ):
        """Normalize one provider PurchaseAlbum without local download state."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase album response is invalid.",
            )

        adapted = dict(payload)

        raw_id = payload.get("id")

        if isinstance(raw_id, bool):
            adapted["id"] = ""
        elif isinstance(raw_id, str):
            adapted["id"] = raw_id
        elif isinstance(raw_id, (int, float)):
            adapted["id"] = str(raw_id)
        else:
            adapted["id"] = ""

        if (
            "title" in payload
            and not isinstance(payload.get("title"), str)
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase album title is invalid.",
            )

        for field in ("artist", "image"):
            if (
                field in payload
                and not isinstance(payload.get(field), dict)
            ):
                raise QobuzCatalogError(
                    "malformed_response",
                    f"Qobuz purchase album {field} is invalid.",
                )

        if (
            "hires" in payload
            and not isinstance(payload.get("hires"), bool)
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase album hires flag is invalid.",
            )

        if (
            "downloadable" in payload
            and not isinstance(
                payload.get("downloadable"),
                bool,
            )
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase album downloadable flag is invalid.",
            )

        adapted.setdefault("hires", False)

        # PurchaseAlbum.tracks is lenient Option<Page<PurchaseTrack>>;
        # do not let the stricter common album normalizer interpret it.
        adapted.pop("tracks", None)

        # Local QBZ registry state is not provider purchase metadata.
        adapted.pop("downloaded", None)

        normalized = cls._normalize_qobuz_album(
            adapted
        )

        normalized["downloadable"] = (
            payload.get("downloadable")
            if "downloadable" in payload
            else True
        )

        purchased_at = payload.get("purchased_at")
        if (
            isinstance(purchased_at, bool)
            or not isinstance(purchased_at, int)
        ):
            purchased_at = None

        normalized["purchased_at"] = purchased_at

        raw_tracks = payload.get("tracks")

        if raw_tracks is None:
            normalized["tracks"] = None
        elif not isinstance(raw_tracks, dict):
            normalized["tracks"] = None
        else:
            normalized["tracks"] = (
                cls._normalize_qobuz_purchase_page(
                    raw_tracks,
                    "tracks",
                )
            )

        normalized.pop("downloaded", None)
        normalized.pop("downloaded_format_ids", None)

        return normalized

    @classmethod
    def _normalize_qobuz_purchase_track(
        cls,
        payload,
    ):
        """Normalize one provider PurchaseTrack with Q5 canonical identity."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase track response is invalid.",
            )

        if (
            "title" in payload
            and not isinstance(payload.get("title"), str)
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase track title is invalid.",
            )

        for field in ("track_number", "duration"):
            if field not in payload:
                continue

            value = payload.get(field)

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise QobuzCatalogError(
                    "malformed_response",
                    f"Qobuz purchase track {field} is invalid.",
                )

        if (
            "performer" in payload
            and not isinstance(payload.get("performer"), dict)
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase track performer is invalid.",
            )

        if (
            "hires" in payload
            and not isinstance(payload.get("hires"), bool)
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase track hires flag is invalid.",
            )

        if (
            "streamable" in payload
            and not isinstance(payload.get("streamable"), bool)
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase track streamable flag is invalid.",
            )

        adapted = dict(payload)

        # PurchaseTrack intentionally has no version semantics.
        adapted.pop("version", None)

        adapted.setdefault("hires", False)
        adapted.setdefault("streamable", True)

        # Local QBZ registry state must not enter provider-native Q6 data.
        adapted.pop("downloaded", None)
        adapted.pop("downloaded_format_ids", None)

        normalized = cls._normalize_qobuz_track(
            adapted
        )

        normalized.pop("version", None)
        normalized.pop("downloaded", None)
        normalized.pop("downloaded_format_ids", None)

        normalized["streamable"] = adapted["streamable"]

        availability = normalized.get(
            "format_availability"
        )
        if isinstance(availability, dict):
            availability["streamable"] = (
                adapted["streamable"]
            )

        quality = normalized.get("quality")
        if isinstance(quality, dict):
            quality["hires"] = adapted["hires"]

        purchased_at = payload.get("purchased_at")
        if (
            isinstance(purchased_at, bool)
            or not isinstance(purchased_at, int)
        ):
            purchased_at = None

        normalized["purchased_at"] = purchased_at

        return normalized

    @classmethod
    def _normalize_qobuz_purchase_page(
        cls,
        payload,
        purchase_type,
    ):
        """Mirror QBZ lenient_page while emitting normalized SROVA items."""
        empty = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 0,
        }

        if payload is None:
            return dict(empty)

        if not isinstance(payload, dict):
            return dict(empty)

        items = payload.get("items", [])

        if not isinstance(items, list):
            return dict(empty)

        metadata = {}

        for field in ("total", "offset", "limit"):
            value = payload.get(field, 0)

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                return dict(empty)

            metadata[field] = value

        if purchase_type == "albums":
            normalizer = cls._normalize_qobuz_purchase_album
        elif purchase_type == "tracks":
            normalizer = cls._normalize_qobuz_purchase_track
        else:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase page type is invalid.",
            )

        try:
            normalized_items = [
                normalizer(item)
                for item in items
            ]
        except QobuzCatalogError:
            return dict(empty)

        return {
            "items": normalized_items,
            "total": metadata["total"],
            "offset": metadata["offset"],
            "limit": metadata["limit"],
        }

    @classmethod
    def _normalize_qobuz_purchase_response(
        cls,
        payload,
    ):
        """Normalize /purchase/getUserPurchases response."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchases response is invalid.",
            )

        return {
            "source": "qobuz",
            "albums": cls._normalize_qobuz_purchase_page(
                payload.get("albums"),
                "albums",
            ),
            "tracks": cls._normalize_qobuz_purchase_page(
                payload.get("tracks"),
                "tracks",
            ),
        }

    @staticmethod
    def _normalize_qobuz_purchase_ids_page(
        payload,
    ):
        """Expose only provider page totals/metadata; opaque ids stay private."""
        empty = {
            "total": 0,
            "offset": 0,
            "limit": 0,
        }

        if payload is None:
            return dict(empty)

        if not isinstance(payload, dict):
            return dict(empty)

        if (
            "items" in payload
            and not isinstance(payload.get("items"), list)
        ):
            return dict(empty)

        result = {}

        for field in ("total", "offset", "limit"):
            value = payload.get(field, 0)

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                return dict(empty)

            result[field] = value

        return result

    @classmethod
    def _normalize_qobuz_purchase_ids_response(
        cls,
        payload,
    ):
        """Normalize /purchase/getUserPurchasesIds metadata-only response."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz purchase ids response is invalid.",
            )

        return {
            "source": "qobuz",
            "albums": cls._normalize_qobuz_purchase_ids_page(
                payload.get("albums")
            ),
            "tracks": cls._normalize_qobuz_purchase_ids_page(
                payload.get("tracks")
            ),
        }

    def get_user_purchases(
        self,
        purchase_type=None,
        limit=None,
        offset=None,
    ):
        """Read one bounded provider-native page of Qobuz purchases."""
        purchase_type = self._catalog_purchase_type(
            purchase_type
        )

        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "limit": page_limit,
            "offset": page_offset,
        }

        if purchase_type is not None:
            params["type"] = purchase_type

        payload = self._catalog_request(
            "/purchase/getUserPurchases",
            method_name="purchasegetUserPurchases",
            params=params,
            require_auth=True,
            signed=False,
        )

        return self._normalize_qobuz_purchase_response(
            payload
        )

    def get_user_purchases_ids(
        self,
        purchase_type=None,
        limit=None,
        offset=None,
    ):
        """Read one bounded provider-native purchase-id metadata page."""
        purchase_type = self._catalog_purchase_type(
            purchase_type
        )

        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "limit": page_limit,
            "offset": page_offset,
        }

        if purchase_type is not None:
            params["type"] = purchase_type

        payload = self._catalog_request(
            "/purchase/getUserPurchasesIds",
            method_name="purchasegetUserPurchasesIds",
            params=params,
            require_auth=True,
            signed=False,
        )

        return self._normalize_qobuz_purchase_ids_response(
            payload
        )


    @classmethod
    def _normalize_qobuz_radio_page(
        cls,
        payload,
    ):
        """Mirror QBZ lenient_page_flexible for one radio track page."""
        page = payload if isinstance(payload, dict) else {}

        raw_items = page.get("items")
        if not isinstance(raw_items, list):
            raw_items = []

        items = []

        for raw_item in raw_items:
            try:
                item = cls._normalize_qobuz_track(
                    raw_item
                )
            except QobuzCatalogError:
                continue

            items.append(item)

        def provider_u32(field, fallback):
            value = page.get(field)

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > 18446744073709551615
            ):
                return fallback

            # QBZ converts serde_json u64 to Rust u32 with `as`.
            return value & 0xFFFFFFFF

        item_count = len(items)

        return {
            "items": items,
            "total": provider_u32(
                "total",
                item_count,
            ),
            "offset": provider_u32(
                "offset",
                0,
            ),
            "limit": provider_u32(
                "limit",
                item_count,
            ),
        }

    @classmethod
    def _normalize_qobuz_radio_response(
        cls,
        payload,
    ):
        """Normalize one provider-native Qobuz RadioResponse."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz radio response is invalid.",
            )

        radio_type = payload.get("type")
        title = payload.get("title")

        if (
            radio_type is not None
            and not isinstance(radio_type, str)
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz radio type is invalid.",
            )

        if (
            title is not None
            and not isinstance(title, str)
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz radio title is invalid.",
            )

        return {
            "source": "qobuz",
            "type": radio_type,
            "title": title,
            "tracks": cls._normalize_qobuz_radio_page(
                payload.get("tracks")
            ),
        }

    def _enrich_qobuz_radio_response_artists(
        self,
        response,
    ):
        """
        Fill only missing Qobuz Radio artist metadata from authoritative
        provider track detail.

        Normal cold path uses Qobuz track/getList in bounded 50-ID
        batches. The original individual track/get path remains a
        salvage fallback only for batch failure or unresolved IDs.

        Preserve Radio track identity, order, album, artwork, duration
        and provider context; mutate only artist and artist_id.
        """
        if not isinstance(response, dict):
            return response

        page = response.get("tracks")

        if not isinstance(page, dict):
            return response

        items = page.get("items")

        if not isinstance(items, list):
            return response

        cache = getattr(
            self,
            "_qobuz_radio_track_artist_cache",
            None,
        )

        if not isinstance(cache, dict):
            cache = {}
            self._qobuz_radio_track_artist_cache = (
                cache
            )

        candidates = []
        pending_ids = []
        pending_seen = set()

        for item in items:
            if not isinstance(item, dict):
                continue

            existing_artist = str(
                item.get("artist")
                or ""
            ).strip()

            if existing_artist:
                continue

            native_id = str(
                item.get("provider_track_id")
                or ""
            ).strip()

            if not native_id:
                canonical_id = str(
                    item.get("id")
                    or ""
                ).strip()

                if canonical_id.startswith(
                    "qobuz:"
                ):
                    native_id = (
                        canonical_id[6:].strip()
                    )

            if not native_id:
                continue

            candidates.append(
                (item, native_id)
            )

            if (
                native_id not in cache
                and native_id not in pending_seen
            ):
                pending_seen.add(
                    native_id
                )
                pending_ids.append(
                    native_id
                )

        def store_artist(
            native_id,
            detail,
        ):
            if not isinstance(detail, dict):
                return False

            artist = str(
                detail.get("artist")
                or ""
            ).strip()

            if not artist:
                return False

            cached = {
                "artist": artist,
                "artist_id": detail.get(
                    "artist_id"
                ),
            }

            if (
                native_id not in cache
                and len(cache) >= 512
            ):
                try:
                    cache.pop(
                        next(iter(cache))
                    )
                except (
                    StopIteration,
                    KeyError,
                ):
                    pass

            cache[native_id] = cached
            return True

        if pending_ids:
            batch_details = []

            try:
                batch_details = (
                    self.get_tracks_batch(
                        pending_ids
                    )
                )
            except Exception as exc:
                logger.debug(
                    "Qobuz Radio batch artist enrichment "
                    "failed; falling back to track detail: %s",
                    exc,
                )

            pending_set = set(
                pending_ids
            )

            for detail in batch_details:
                if not isinstance(detail, dict):
                    continue

                detail_id = str(
                    detail.get(
                        "provider_track_id"
                    )
                    or ""
                ).strip()

                if detail_id not in pending_set:
                    continue

                store_artist(
                    detail_id,
                    detail,
                )

            for native_id in pending_ids:
                if native_id in cache:
                    continue

                try:
                    detail = self.get_track(
                        native_id
                    )
                except Exception as exc:
                    logger.debug(
                        "Qobuz Radio artist enrichment "
                        "failed track_id=%s: %s",
                        native_id,
                        exc,
                    )
                    continue

                store_artist(
                    native_id,
                    detail,
                )

        for item, native_id in candidates:
            cached = cache.get(
                native_id
            )

            if not isinstance(cached, dict):
                continue

            artist = str(
                cached.get("artist")
                or ""
            ).strip()

            if not artist:
                continue

            item["artist"] = artist

            artist_id = cached.get(
                "artist_id"
            )

            if artist_id is not None:
                item["artist_id"] = (
                    artist_id
                )

        return response


    def get_radio_artist(
        self,
        artist_id,
    ):
        """Return one provider-native Qobuz artist-radio response."""
        native_id = self._catalog_numeric_request_id(
            artist_id,
            "artist ID",
        )

        payload = self._catalog_request(
            "/radio/artist",
            method_name="radioartist",
            params={
                "artist_id": native_id,
            },
            require_auth=True,
            signed=False,
        )

        return self._enrich_qobuz_radio_response_artists(
            self._normalize_qobuz_radio_response(
                payload
            )
        )

    def get_radio_track(
        self,
        track_id,
    ):
        """Return one provider-native Qobuz track-radio response."""
        native_id = self._catalog_numeric_request_id(
            track_id,
            "track ID",
        )

        payload = self._catalog_request(
            "/radio/track",
            method_name="radiotrack",
            params={
                "track_id": native_id,
            },
            require_auth=True,
            signed=False,
        )

        return self._enrich_qobuz_radio_response_artists(
            self._normalize_qobuz_radio_response(
                payload
            )
        )

    def get_radio_album(
        self,
        album_id,
    ):
        """Return one provider-native Qobuz album-radio response."""
        native_id = self._catalog_album_request_id(
            album_id
        )

        payload = self._catalog_request(
            "/radio/album",
            method_name="radioalbum",
            params={
                "album_id": native_id,
            },
            require_auth=True,
            signed=False,
        )

        return self._enrich_qobuz_radio_response_artists(
            self._normalize_qobuz_radio_response(
                payload
            )
        )

    @classmethod
    def _normalize_qobuz_playlist_tracks_page(
        cls,
        payload,
        *,
        limit,
        offset,
    ):
        """Normalize one bounded provider playlist track page."""
        if payload is None:
            return {
                "items": [],
                "total": 0,
                "offset": offset,
                "limit": limit,
            }

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist tracks response is invalid.",
            )

        raw_items = payload.get("items")

        if not isinstance(raw_items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist track items are invalid.",
            )

        total = payload.get("total")

        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
            or total > 0xFFFFFFFF
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist track total is invalid.",
            )

        if len(raw_items) > limit:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist track page exceeds the requested limit.",
            )

        items = []

        for raw_item in raw_items:
            normalized_item = (
                cls._normalize_qobuz_track(
                    raw_item
                )
            )

            # playlist_track_id is Qobuz playlist-occurrence identity.
            # Preserve it only on playlist-detail rows; it must never
            # replace catalog/provider_track_id playback identity.
            if isinstance(raw_item, dict):
                raw_occurrence_id = (
                    raw_item.get(
                        "playlist_track_id"
                    )
                )

                if raw_occurrence_id is not None:
                    occurrence_id = str(
                        raw_occurrence_id
                    ).strip()

                    if occurrence_id:
                        normalized_item[
                            "playlist_track_id"
                        ] = occurrence_id

            items.append(
                normalized_item
            )

        return {
            "items": items,
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @classmethod
    def _normalize_qobuz_playlist_detail(
        cls,
        payload,
        *,
        limit,
        offset,
    ):
        """Normalize one provider playlist plus one bounded track page."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist detail response is invalid.",
            )

        playlist = cls._normalize_qobuz_playlist(
            payload
        )

        tracks = cls._normalize_qobuz_playlist_tracks_page(
            payload.get("tracks"),
            limit=limit,
            offset=offset,
        )

        playlist["tracks"] = tracks
        return playlist


    def _current_session_user_id(self):
        """Return the authenticated Qobuz user ID internally, never via status."""
        lock = getattr(
            self,
            "_auth_lock",
            None,
        )

        if lock is None:
            session = getattr(
                self,
                "_session",
                None,
            )
            authenticated = bool(
                getattr(
                    self,
                    "authenticated",
                    False,
                )
            )
        else:
            with lock:
                session = self._session
                authenticated = bool(
                    self.authenticated
                )

        if (
            not authenticated
            or not isinstance(
                session,
                dict,
            )
        ):
            return ""

        user_id = str(
            session.get("user_id")
            or ""
        ).strip()

        if (
            not user_id
            or not user_id.isascii()
            or not user_id.isdigit()
            or int(user_id) <= 0
        ):
            return ""

        return user_id

    def _playlist_owned_by_current_user(
        self,
        playlist,
    ):
        """Return True only for a playlist positively owned by this session."""
        if not isinstance(
            playlist,
            dict,
        ):
            return False

        current_user_id = (
            self._current_session_user_id()
        )

        owner_id = str(
            playlist.get("owner_id")
            or ""
        ).strip()

        return bool(
            current_user_id
            and owner_id
            and current_user_id
            == owner_id
        )

    def get_user_playlists(self):
        """Return the signed-in user's provider-native Qobuz playlists."""
        payload = self._catalog_request(
            "/playlist/getUserPlaylists",
            method_name="playlistgetUserPlaylists",
            params={},
            signature_params={},
            require_auth=True,
            signed=True,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz user playlist response is invalid.",
            )

        playlists = payload.get("playlists")

        if not isinstance(playlists, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz user playlist container is invalid.",
            )

        raw_items = playlists.get("items")

        if not isinstance(raw_items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz user playlist items are invalid.",
            )

        normalized = [
            self._normalize_qobuz_playlist(item)
            for item in raw_items
        ]

        current_user_id = (
            self._current_session_user_id()
        )

        for playlist in normalized:
            owner_id = str(
                playlist.get("owner_id")
                or ""
            ).strip()

            playlist[
                "playlist_editable"
            ] = bool(
                current_user_id
                and owner_id
                and current_user_id
                == owner_id
            )

        return normalized

    def create_playlist(
        self,
        name,
        description=None,
        *,
        is_public=False,
    ):
        """Create one authenticated provider-native Qobuz playlist."""
        normalized_name = self._catalog_clean_text(
            name,
            maximum=4096,
        )

        if not normalized_name:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz playlist name is invalid.",
            )

        if description is None:
            normalized_description = None
        elif not isinstance(description, str):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz playlist description is invalid.",
            )
        else:
            normalized_description = description.strip()

            if (
                len(normalized_description) > 65536
                or "\x00" in normalized_description
            ):
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz playlist description is invalid.",
                )

            if not normalized_description:
                normalized_description = None

        if not isinstance(is_public, bool):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz playlist privacy is invalid.",
            )

        params = {
            "name": normalized_name,
            "is_public": (
                "true"
                if is_public
                else "false"
            ),
        }

        if normalized_description is not None:
            params["description"] = normalized_description

        payload = self._catalog_request(
            "/playlist/create",
            method_name="playlistcreate",
            params=params,
            signature_params=dict(params),
            require_auth=True,
            signed=True,
        )

        playlist = self._normalize_qobuz_playlist(
            payload
        )

        # A successfully created provider playlist is necessarily owned by
        # the authenticated account which created it. Preserve that fact in
        # the immediate F3A local-upsert result instead of waiting for the
        # eventually-consistent provider list to confirm it.
        playlist["playlist_editable"] = True

        return {
            "ok": True,
            "playlist": playlist,
            "id": playlist["playlist_id"],
            "name": playlist["name"],
            "is_public": playlist["is_public"],
        }



    @classmethod
    def _q8d_normalize_playlist_add_tracks(
        cls,
        tracks,
    ):
        """Validate Q8D Qobuz identities and preserve first-seen input order."""
        if (
            not isinstance(tracks, list)
            or not tracks
            or len(tracks) > 10000
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz playlist tracks are invalid.",
            )

        normalized = []
        seen = set()
        input_duplicates = 0

        for track in tracks:
            if not isinstance(track, dict):
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz playlist track identity is invalid.",
                )

            source = str(
                track.get("source")
                or ""
            ).strip().lower()

            canonical_id = str(
                track.get("id")
                or ""
            ).strip()

            raw_provider_id = track.get(
                "provider_track_id"
            )

            if (
                source != "qobuz"
                or raw_provider_id is None
            ):
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz playlist track identity is invalid.",
                )

            provider_id = (
                cls._catalog_numeric_request_id(
                    raw_provider_id,
                    "track ID",
                )
            )

            if canonical_id != (
                "qobuz:" + provider_id
            ):
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz playlist track identity is invalid.",
                )

            if provider_id in seen:
                input_duplicates += 1
                continue

            seen.add(provider_id)
            normalized.append(provider_id)

        if not normalized:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz playlist tracks are invalid.",
            )

        return (
            normalized,
            input_duplicates,
            len(tracks),
        )

    @staticmethod
    def _q8d_validate_playlist_mutation_response(
        payload,
    ):
        """Reject explicit provider failure envelopes before reconciliation."""
        if not isinstance(
            payload,
            (dict, list),
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist mutation response is invalid.",
            )

        if isinstance(payload, dict):
            status = str(
                payload.get("status")
                or ""
            ).strip().lower()

            if (
                payload.get("ok") is False
                or payload.get("success") is False
                or payload.get("error")
                not in (None, "", False)
                or status in (
                    "error",
                    "failed",
                    "failure",
                )
            ):
                raise QobuzCatalogError(
                    "provider_error",
                    "Qobuz rejected the playlist update.",
                )

        return True

    def _complete_owned_playlist_tracks(
        self,
        playlist_id,
    ):
        """Resolve one complete Qobuz playlist positively owned by this session."""
        native_id = (
            self._catalog_numeric_request_id(
                playlist_id,
                "playlist ID",
            )
        )

        current_user_id = (
            self._current_session_user_id()
        )

        if not current_user_id:
            raise QobuzCatalogError(
                "not_authenticated",
                "Qobuz authentication is required.",
                http_status=401,
            )

        page_size = 100
        maximum_tracks = 10000
        resolved_tracks = []
        provider_total = None
        offset = 0
        owner_checked = False

        while True:
            detail = self.get_playlist(
                native_id,
                limit=page_size,
                offset=offset,
            )

            if not isinstance(detail, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz playlist detail response is invalid.",
                )

            if not owner_checked:
                if not self._playlist_owned_by_current_user(
                    detail
                ):
                    raise QobuzCatalogError(
                        "not_editable",
                        "This Qobuz playlist is not editable by the current user.",
                        http_status=403,
                    )

                owner_checked = True

            track_page = detail.get(
                "tracks"
            )

            if not isinstance(
                track_page,
                dict,
            ):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz playlist track page is invalid.",
                )

            items = track_page.get(
                "items"
            )

            total = track_page.get(
                "total"
            )

            if (
                not isinstance(items, list)
                or isinstance(total, bool)
                or not isinstance(total, int)
                or total < 0
            ):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz playlist track page is invalid.",
                )

            if len(items) > page_size:
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz playlist page exceeded its requested limit.",
                )

            if provider_total is None:
                provider_total = total

                if (
                    provider_total
                    > maximum_tracks
                ):
                    raise QobuzCatalogError(
                        "playlist_too_large",
                        "Qobuz playlist exceeds the supported track limit.",
                    )

            elif total != provider_total:
                raise QobuzCatalogError(
                    "playlist_changed",
                    "Qobuz playlist changed while SROVA was reading it.",
                    transient=True,
                )

            if not items:
                if (
                    len(resolved_tracks)
                    < provider_total
                ):
                    raise QobuzCatalogError(
                        "playlist_changed",
                        "Qobuz playlist pagination ended before the provider total.",
                        transient=True,
                    )

                break

            for track in items:
                if not isinstance(
                    track,
                    dict,
                ):
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz playlist track identity is invalid.",
                    )

                source = str(
                    track.get("source")
                    or ""
                ).strip().lower()

                provider_track_id = str(
                    track.get(
                        "provider_track_id"
                    )
                    or ""
                ).strip()

                canonical_id = str(
                    track.get("id")
                    or ""
                ).strip()

                if (
                    source != "qobuz"
                    or not provider_track_id
                    or canonical_id
                    != "qobuz:"
                    + provider_track_id
                ):
                    raise QobuzCatalogError(
                        "malformed_response",
                        "Qobuz playlist track identity is invalid.",
                    )

                provider_track_id = (
                    self._catalog_numeric_request_id(
                        provider_track_id,
                        "track ID",
                    )
                )

                normalized_track = dict(
                    track
                )

                normalized_track[
                    "source"
                ] = "qobuz"

                normalized_track[
                    "provider_track_id"
                ] = provider_track_id

                normalized_track[
                    "id"
                ] = (
                    "qobuz:"
                    + provider_track_id
                )

                resolved_tracks.append(
                    normalized_track
                )

            offset += len(items)

            if (
                len(resolved_tracks)
                > provider_total
            ):
                raise QobuzCatalogError(
                    "playlist_changed",
                    "Qobuz playlist returned more tracks than its provider total.",
                    transient=True,
                )

            if (
                len(resolved_tracks)
                == provider_total
            ):
                break

        if provider_total is None:
            provider_total = 0

        if (
            len(resolved_tracks)
            != provider_total
        ):
            raise QobuzCatalogError(
                "playlist_changed",
                "Qobuz playlist did not resolve completely.",
                transient=True,
            )

        return (
            native_id,
            resolved_tracks,
        )

    def _q8d_complete_owned_playlist_track_ids(
        self,
        playlist_id,
    ):
        """Resolve complete owned Qobuz catalog IDs for Q8D duplicate truth."""
        (
            native_id,
            tracks,
        ) = self._complete_owned_playlist_tracks(
            playlist_id
        )

        return (
            native_id,
            [
                track[
                    "provider_track_id"
                ]
                for track in tracks
            ],
        )

    def add_tracks_to_playlist(
        self,
        playlist_id,
        tracks,
    ):
        """Add validated native Qobuz tracks to one owned provider playlist."""
        (
            requested_ids,
            input_duplicates,
            requested_count,
        ) = self._q8d_normalize_playlist_add_tracks(
            tracks
        )

        (
            native_playlist_id,
            existing_ids,
        ) = self._q8d_complete_owned_playlist_track_ids(
            playlist_id
        )

        existing_set = set(existing_ids)
        to_add = []
        existing_duplicates = 0

        for provider_track_id in requested_ids:
            if provider_track_id in existing_set:
                existing_duplicates += 1
                continue

            to_add.append(provider_track_id)

        duplicates_skipped = (
            input_duplicates
            + existing_duplicates
        )

        if not to_add:
            return {
                "ok": True,
                "playlist_id": native_playlist_id,
                "requested": requested_count,
                "items_added": 0,
                "duplicates_skipped": duplicates_skipped,
                "total_before": len(existing_ids),
                "total_after": len(existing_ids),
                "confirmed": True,
                "provider_request_sent": False,
            }

        batch_size = 100

        for start in range(
            0,
            len(to_add),
            batch_size,
        ):
            chunk = to_add[
                start:
                start + batch_size
            ]

            params = {
                "playlist_id":
                    native_playlist_id,
                "track_ids":
                    ",".join(chunk),
            }

            response = self._catalog_request(
                "/playlist/addTracks",
                method_name="playlistaddTracks",
                params=params,
                signature_params=dict(params),
                require_auth=True,
                signed=True,
            )

            self._q8d_validate_playlist_mutation_response(
                response
            )

        last_error = None

        for delay in (
            0.0,
            1.0,
            3.0,
        ):
            if delay:
                time.sleep(delay)

            try:
                (
                    _confirmed_playlist_id,
                    confirmed_ids,
                ) = self._q8d_complete_owned_playlist_track_ids(
                    native_playlist_id
                )
            except QobuzCatalogError as exc:
                last_error = exc
                continue

            confirmed_set = set(
                confirmed_ids
            )

            if all(
                provider_track_id
                in confirmed_set
                for provider_track_id
                in to_add
            ):
                return {
                    "ok": True,
                    "playlist_id":
                        native_playlist_id,
                    "requested":
                        requested_count,
                    "items_added":
                        len(to_add),
                    "duplicates_skipped":
                        duplicates_skipped,
                    "total_before":
                        len(existing_ids),
                    "total_after":
                        len(confirmed_ids),
                    "confirmed": True,
                    "provider_request_sent": True,
                }

        raise QobuzCatalogError(
            "reconcile_timeout",
            "Qobuz accepted the playlist update, but SROVA could not confirm it yet.",
            transient=True,
        ) from last_error


    @classmethod
    def _q8e_normalize_playlist_remove_tracks(
        cls,
        tracks,
    ):
        """Validate selected Qobuz playlist occurrences without trusting browser identity."""
        if (
            not isinstance(tracks, list)
            or not tracks
            or len(tracks) > 10000
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz playlist tracks are invalid.",
            )

        normalized = []
        occurrence_owner = {}

        for track in tracks:
            if not isinstance(
                track,
                dict,
            ):
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz playlist track identity is invalid.",
                )

            source = str(
                track.get("source")
                or ""
            ).strip().lower()

            canonical_id = str(
                track.get("id")
                or ""
            ).strip()

            raw_provider_id = track.get(
                "provider_track_id"
            )

            raw_occurrence_id = (
                track.get(
                    "playlist_track_id"
                )
            )

            if (
                source != "qobuz"
                or raw_provider_id is None
                or raw_occurrence_id is None
            ):
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz playlist track identity is invalid.",
                )

            provider_id = (
                cls._catalog_numeric_request_id(
                    raw_provider_id,
                    "track ID",
                )
            )

            occurrence_id = (
                cls._catalog_numeric_request_id(
                    raw_occurrence_id,
                    "playlist track ID",
                )
            )

            if (
                canonical_id
                != "qobuz:"
                + provider_id
            ):
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz playlist track identity is invalid.",
                )

            previous_provider = (
                occurrence_owner.get(
                    occurrence_id
                )
            )

            if (
                previous_provider is not None
                and previous_provider
                != provider_id
            ):
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz playlist occurrence identity is inconsistent.",
                )

            if previous_provider is not None:
                continue

            occurrence_owner[
                occurrence_id
            ] = provider_id

            normalized.append({
                "source": "qobuz",
                "id":
                    "qobuz:"
                    + provider_id,
                "provider_track_id":
                    provider_id,
                "playlist_track_id":
                    occurrence_id,
            })

        if not normalized:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz playlist tracks are invalid.",
            )

        return (
            normalized,
            len(tracks),
        )

    def _q8e_provider_occurrence_id(
        self,
        track,
    ):
        """Return one provider occurrence ID or fail on malformed provider identity."""
        if not isinstance(
            track,
            dict,
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist track identity is invalid.",
            )

        raw_occurrence_id = (
            track.get(
                "playlist_track_id"
            )
        )

        if (
            raw_occurrence_id is None
            or not str(
                raw_occurrence_id
            ).strip()
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist occurrence identity is missing.",
            )

        try:
            return (
                self._catalog_numeric_request_id(
                    raw_occurrence_id,
                    "playlist track ID",
                )
            )
        except QobuzCatalogError as exc:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist occurrence identity is invalid.",
            ) from exc

    def remove_tracks_from_playlist(
        self,
        playlist_id,
        tracks,
    ):
        """Remove selected Qobuz catalog tracks from one owned playlist."""
        (
            selected,
            requested_count,
        ) = self._q8e_normalize_playlist_remove_tracks(
            tracks
        )

        (
            native_playlist_id,
            existing_tracks,
        ) = self._complete_owned_playlist_tracks(
            playlist_id
        )

        occurrence_map = {}

        for existing_track in existing_tracks:
            raw_occurrence_id = (
                existing_track.get(
                    "playlist_track_id"
                )
            )

            if (
                raw_occurrence_id is None
                or not str(
                    raw_occurrence_id
                ).strip()
            ):
                continue

            occurrence_id = (
                self._q8e_provider_occurrence_id(
                    existing_track
                )
            )

            if occurrence_id in occurrence_map:
                raise QobuzCatalogError(
                    "playlist_changed",
                    "Qobuz playlist occurrence identity is duplicated.",
                    transient=True,
                )

            occurrence_map[
                occurrence_id
            ] = existing_track

        # The browser occurrence is only a claim. Re-resolve it against the
        # complete owned provider playlist before any mutation.
        for selected_track in selected:
            occurrence_id = (
                selected_track[
                    "playlist_track_id"
                ]
            )

            provider_track_id = (
                selected_track[
                    "provider_track_id"
                ]
            )

            resolved_track = (
                occurrence_map.get(
                    occurrence_id
                )
            )

            if resolved_track is None:
                raise QobuzCatalogError(
                    "playlist_changed",
                    "The selected Qobuz playlist track is no longer present.",
                    transient=True,
                )

            if (
                resolved_track[
                    "provider_track_id"
                ]
                != provider_track_id
            ):
                raise QobuzCatalogError(
                    "invalid_request",
                    "Qobuz playlist occurrence does not match the selected track.",
                )

        target_provider_ids = []
        target_provider_set = set()

        for selected_track in selected:
            provider_track_id = (
                selected_track[
                    "provider_track_id"
                ]
            )

            if (
                provider_track_id
                in target_provider_set
            ):
                continue

            target_provider_set.add(
                provider_track_id
            )

            target_provider_ids.append(
                provider_track_id
            )

        # Removing a selected catalog track removes every occurrence of
        # that track in the playlist.
        delete_occurrence_ids = []
        seen_occurrence_ids = set()

        for existing_track in existing_tracks:
            provider_track_id = (
                existing_track[
                    "provider_track_id"
                ]
            )

            if (
                provider_track_id
                not in target_provider_set
            ):
                continue

            occurrence_id = (
                self._q8e_provider_occurrence_id(
                    existing_track
                )
            )

            if (
                occurrence_id
                in seen_occurrence_ids
            ):
                continue

            seen_occurrence_ids.add(
                occurrence_id
            )

            delete_occurrence_ids.append(
                occurrence_id
            )

        if not delete_occurrence_ids:
            raise QobuzCatalogError(
                "playlist_changed",
                "The selected Qobuz playlist track is no longer present.",
                transient=True,
            )

        batch_size = 100

        for start in range(
            0,
            len(delete_occurrence_ids),
            batch_size,
        ):
            chunk = (
                delete_occurrence_ids[
                    start:
                    start + batch_size
                ]
            )

            params = {
                "playlist_id":
                    native_playlist_id,
                "playlist_track_ids":
                    ",".join(chunk),
            }

            response = self._catalog_request(
                "/playlist/deleteTracks",
                method_name=
                    "playlistdeleteTracks",
                params=params,
                signature_params=
                    dict(params),
                require_auth=True,
                signed=True,
            )

            self._q8d_validate_playlist_mutation_response(
                response
            )

        last_error = None
        deleted_occurrence_set = set(
            delete_occurrence_ids
        )

        for delay in (
            0.0,
            1.0,
            3.0,
        ):
            if delay:
                time.sleep(delay)

            try:
                (
                    _confirmed_playlist_id,
                    confirmed_tracks,
                ) = self._complete_owned_playlist_tracks(
                    native_playlist_id
                )
            except QobuzCatalogError as exc:
                last_error = exc
                continue

            target_track_still_present = any(
                track[
                    "provider_track_id"
                ]
                in target_provider_set
                for track in confirmed_tracks
            )

            confirmed_occurrence_ids = set()

            for confirmed_track in confirmed_tracks:
                raw_occurrence_id = (
                    confirmed_track.get(
                        "playlist_track_id"
                    )
                )

                if (
                    raw_occurrence_id is None
                    or not str(
                        raw_occurrence_id
                    ).strip()
                ):
                    continue

                try:
                    confirmed_occurrence_ids.add(
                        self._catalog_numeric_request_id(
                            raw_occurrence_id,
                            "playlist track ID",
                        )
                    )
                except QobuzCatalogError:
                    continue

            deleted_occurrence_still_present = bool(
                deleted_occurrence_set
                & confirmed_occurrence_ids
            )

            if (
                not target_track_still_present
                and not deleted_occurrence_still_present
            ):
                return {
                    "ok": True,
                    "playlist_id":
                        native_playlist_id,
                    "requested":
                        requested_count,
                    "items_removed":
                        len(
                            target_provider_ids
                        ),
                    "occurrences_removed":
                        len(
                            delete_occurrence_ids
                        ),
                    "total_before":
                        len(existing_tracks),
                    "total_after":
                        len(confirmed_tracks),
                    "confirmed":
                        True,
                    "provider_request_sent":
                        True,
                }

        raise QobuzCatalogError(
            "reconcile_timeout",
            "Qobuz accepted the playlist update, but SROVA could not confirm it yet.",
            transient=True,
        ) from last_error

    def rename_playlist(
        self,
        playlist_id,
        name,
    ):
        """Rename one authenticated provider playlist owned by this user."""
        native_id = (
            self._catalog_numeric_request_id(
                playlist_id,
                "playlist ID",
            )
        )

        normalized_name = (
            self._catalog_clean_text(
                name,
                maximum=4096,
            )
        )

        if not normalized_name:
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz playlist name is invalid.",
            )

        current_user_id = (
            self._current_session_user_id()
        )

        if not current_user_id:
            raise QobuzCatalogError(
                "not_authenticated",
                "Qobuz authentication is required.",
                http_status=401,
            )

        # Re-resolve immediately before mutation. Browser/list state is not
        # accepted as ownership authority.
        playlist = self.get_playlist(
            native_id,
            limit=1,
            offset=0,
        )

        if not isinstance(
            playlist,
            dict,
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist detail response is invalid.",
            )

        owner_id = str(
            playlist.get("owner_id")
            or ""
        ).strip()

        if (
            not owner_id
            or owner_id
            != current_user_id
        ):
            raise QobuzCatalogError(
                "not_editable",
                "This Qobuz playlist is not editable by the current user.",
                http_status=403,
            )

        # /playlist/update changes only fields which are supplied.
        # Rename deliberately leaves description and visibility untouched.
        params = {
            "playlist_id":
                native_id,
            "name":
                normalized_name,
        }

        payload = self._catalog_request(
            "/playlist/update",
            method_name="playlistupdate",
            params=params,
            signature_params=dict(params),
            require_auth=True,
            signed=True,
        )

        self._q8d_validate_playlist_mutation_response(
            payload
        )

        # Native /playlist/update returns a Playlist object. Validate that the
        # response itself is structurally usable and refers to this playlist,
        # but do not turn the write response alone into final success.
        updated_playlist = (
            self._normalize_qobuz_playlist(
                payload
            )
        )

        updated_id = str(
            updated_playlist.get(
                "playlist_id"
            )
            or ""
        ).strip()

        if (
            not updated_id
            or updated_id
            != native_id
        ):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz playlist update response identity is invalid.",
            )

        # Qobuz reads may lag a successful metadata update. Confirm the new
        # name using the same bounded reconciliation cadence as Q8D/Q8E.
        last_error = None

        for delay_seconds in (
            0.0,
            1.0,
            3.0,
        ):
            if delay_seconds:
                time.sleep(
                    delay_seconds
                )

            try:
                confirmed = self.get_playlist(
                    native_id,
                    limit=1,
                    offset=0,
                )
            except Exception as exc:
                last_error = exc
                continue

            if not isinstance(
                confirmed,
                dict,
            ):
                last_error = QobuzCatalogError(
                    "malformed_response",
                    "Qobuz playlist detail response is invalid.",
                )
                continue

            confirmed_id = str(
                confirmed.get(
                    "playlist_id"
                )
                or ""
            ).strip()

            if (
                not confirmed_id
                or confirmed_id
                != native_id
            ):
                last_error = QobuzCatalogError(
                    "malformed_response",
                    "Qobuz playlist readback identity is invalid.",
                )
                continue

            confirmed_name = str(
                confirmed.get(
                    "name"
                )
                or ""
            ).strip()

            if (
                confirmed_name
                == normalized_name
            ):
                confirmed_playlist = dict(
                    confirmed
                )
                confirmed_playlist[
                    "playlist_editable"
                ] = True

                return {
                    "ok": True,
                    "playlist_id":
                        native_id,
                    "name":
                        normalized_name,
                    "playlist":
                        confirmed_playlist,
                    "confirmed":
                        True,
                    "provider_request_sent":
                        True,
                }

        raise QobuzCatalogError(
            "reconcile_timeout",
            "Qobuz accepted the playlist update, but SROVA could not confirm it yet.",
            transient=True,
        ) from last_error

    def delete_playlist(
        self,
        playlist_id,
    ):
        """Delete one authenticated provider playlist owned by this user."""
        native_id = (
            self._catalog_numeric_request_id(
                playlist_id,
                "playlist ID",
            )
        )

        current_user_id = (
            self._current_session_user_id()
        )

        if not current_user_id:
            raise QobuzCatalogError(
                "not_authenticated",
                "Qobuz authentication is required.",
                http_status=401,
            )

        # Re-resolve immediately before mutation. Browser/list state is not
        # accepted as ownership authority.
        playlist = self.get_playlist(
            native_id,
            limit=1,
            offset=0,
        )

        owner_id = str(
            playlist.get("owner_id")
            or ""
        ).strip()

        if (
            not owner_id
            or owner_id
            != current_user_id
        ):
            raise QobuzCatalogError(
                "not_editable",
                "This Qobuz playlist is not editable by the current user.",
                http_status=403,
            )

        params = {
            "playlist_id":
                native_id,
        }

        self._catalog_request(
            "/playlist/delete",
            method_name="playlistdelete",
            params=params,
            signature_params=dict(params),
            require_auth=True,
            signed=True,
        )

        return {
            "ok": True,
            "playlist_id": native_id,
        }

    def get_playlist(
        self,
        playlist_id,
        *,
        limit=None,
        offset=None,
    ):
        """Return exactly one bounded provider-native playlist track page."""
        native_id = self._catalog_numeric_request_id(
            playlist_id,
            "playlist ID",
        )

        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "playlist_id": native_id,
            "limit": str(page_limit),
            "offset": str(page_offset),
            "extra": "tracks",
        }

        payload = self._catalog_request(
            "/playlist/get",
            method_name="playlistget",
            params=params,
            signature_params=dict(params),
            require_auth=False,
            signed=True,
        )

        return self._normalize_qobuz_playlist_detail(
            payload,
            limit=page_limit,
            offset=page_offset,
        )

    @staticmethod
    def _catalog_award_request_id(value):
        """Validate one opaque Qobuz award ID for an outbound request."""
        if isinstance(value, bool):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz award ID is invalid.",
            )

        if isinstance(value, int):
            text = str(value)
        elif isinstance(value, str):
            text = value.strip()
        else:
            text = ""

        if (
            not text
            or len(text) > 512
            or not text.isascii()
            or any(
                ord(char) <= 32 or ord(char) == 127
                for char in text
            )
        ):
            raise QobuzCatalogError(
                "invalid_request",
                "Qobuz award ID is invalid.",
            )

        return text

    @classmethod
    def _normalize_qobuz_award_image(
        cls,
        value,
        *,
        strict=False,
        label="award image",
    ):
        """Normalize one provider Award image without inventing URL forms."""
        if value is None:
            return None

        if isinstance(value, str):
            try:
                return cls._catalog_label_optional_text(
                    value,
                    label,
                    maximum=16384,
                )
            except QobuzCatalogError:
                if strict:
                    raise
                return None

        if strict:
            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} is invalid.",
            )

        if not isinstance(value, dict):
            return None

        for key in (
            "large",
            "extralarge",
            "mega",
            "medium",
            "thumbnail",
            "small",
        ):
            candidate = value.get(key)

            if not isinstance(candidate, str):
                continue

            try:
                text = cls._catalog_label_optional_text(
                    candidate,
                    f"{label} {key}",
                    maximum=16384,
                )
            except QobuzCatalogError:
                continue

            if text is not None:
                return text

        return None

    @classmethod
    def _normalize_qobuz_award_explore_row(
        cls,
        payload,
    ):
        """Normalize one usable /award/explore catalog row."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz award explore row is invalid.",
            )

        try:
            award_id = cls._catalog_award_request_id(
                payload.get("id")
            )
        except QobuzCatalogError as exc:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz award explore ID is invalid.",
            ) from exc

        name = cls._catalog_label_required_text(
            payload.get("name"),
            "award explore name",
            maximum=16384,
        )

        magazine = None
        raw_magazine = payload.get("magazine")

        if isinstance(raw_magazine, dict):
            try:
                magazine_name = cls._catalog_label_optional_text(
                    raw_magazine.get("name"),
                    "award explore magazine name",
                    maximum=16384,
                )
            except QobuzCatalogError:
                magazine_name = None

            if magazine_name is not None:
                magazine = {
                    "name": magazine_name,
                }

        return {
            "id": award_id,
            "name": name,
            "magazine": magazine,
            "image": cls._normalize_qobuz_award_image(
                payload.get("image"),
                label="award explore image",
            ),
        }

    @classmethod
    def _normalize_qobuz_award_page(
        cls,
        payload,
    ):
        """Normalize the evidence-backed fields from /award/page."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz award page response is invalid.",
            )

        def optional_award_identity(value, label):
            if value is None:
                return None

            if isinstance(value, bool) or not isinstance(
                value,
                (str, int),
            ):
                raise QobuzCatalogError(
                    "malformed_response",
                    f"Qobuz {label} is invalid.",
                )

            try:
                return cls._catalog_award_request_id(
                    value
                )
            except QobuzCatalogError as exc:
                raise QobuzCatalogError(
                    "malformed_response",
                    f"Qobuz {label} is invalid.",
                ) from exc

        def optional_string_or_int(value, label):
            if value is None:
                return None

            if isinstance(value, bool):
                raise QobuzCatalogError(
                    "malformed_response",
                    f"Qobuz {label} is invalid.",
                )

            if isinstance(value, int):
                return str(value)

            if isinstance(value, str):
                return cls._catalog_label_optional_text(
                    value,
                    label,
                    maximum=16384,
                )

            raise QobuzCatalogError(
                "malformed_response",
                f"Qobuz {label} is invalid.",
            )

        magazine = None
        raw_magazine = payload.get("magazine")

        if raw_magazine is not None:
            if not isinstance(raw_magazine, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz award magazine is invalid.",
                )

            magazine = {
                "id": optional_award_identity(
                    raw_magazine.get("id"),
                    "award magazine ID",
                ),
                "name": cls._catalog_label_optional_text(
                    raw_magazine.get("name"),
                    "award magazine name",
                    maximum=16384,
                ),
                "image": cls._normalize_qobuz_award_image(
                    raw_magazine.get("image"),
                    strict=True,
                    label="award magazine image",
                ),
            }

        return {
            "id": optional_award_identity(
                payload.get("id"),
                "award page ID",
            ),
            "name": cls._catalog_label_optional_text(
                payload.get("name"),
                "award page name",
                maximum=16384,
            ),
            "image": cls._normalize_qobuz_award_image(
                payload.get("image"),
                strict=True,
                label="award page image",
            ),
            "awarded_at": optional_string_or_int(
                payload.get("awarded_at"),
                "award date",
            ),
            "magazine": magazine,
        }

    @classmethod
    def _normalize_qobuz_award_album_page(
        cls,
        payload,
        *,
        page_limit,
        page_offset,
    ):
        """Normalize current or evidenced legacy /award/getAlbums envelope."""
        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz award album response is invalid.",
            )

        if "albums" in payload:
            page_payload = payload.get("albums")

            if not isinstance(page_payload, dict):
                raise QobuzCatalogError(
                    "malformed_response",
                    "Qobuz legacy award album page is invalid.",
                )
        else:
            page_payload = payload

        return cls._normalize_qobuz_label_typed_page(
            page_payload,
            row_normalizer=cls._normalize_qobuz_label_album,
            page_limit=page_limit,
            page_offset=page_offset,
            label="award album page",
        )

    def get_award_explore(
        self,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded provider-native Qobuz Award catalog page."""
        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        payload = self._catalog_request(
            "/award/explore",
            method_name="awardexplore",
            params=params,
            signature_params=dict(params),
            require_auth=True,
        )

        if not isinstance(payload, dict):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz award explore response is invalid.",
            )

        has_more = self._catalog_label_optional_bool(
            payload.get("has_more"),
            "award explore pagination",
        )

        items = payload.get("items")

        if items is None:
            items = []

        if not isinstance(items, list):
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz award explore item list is invalid.",
            )

        if len(items) > page_limit:
            raise QobuzCatalogError(
                "malformed_response",
                "Qobuz award explore response exceeded the requested page limit.",
            )

        normalized = []

        for item in items:
            try:
                normalized.append(
                    self._normalize_qobuz_award_explore_row(
                        item
                    )
                )
            except QobuzCatalogError:
                continue

        return {
            "ok": True,
            "items": normalized,
            "offset": page_offset,
            "limit": page_limit,
            "has_more": has_more,
        }

    def get_award_page(
        self,
        award_id,
    ):
        """Return the evidence-backed provider-native Qobuz Award detail."""
        native_id = self._catalog_award_request_id(
            award_id
        )

        params = {
            "award_id": native_id,
        }

        payload = self._catalog_request(
            "/award/page",
            method_name="awardpage",
            params=params,
            signature_params=dict(params),
            require_auth=True,
        )

        page = self._normalize_qobuz_award_page(
            payload
        )

        return {
            "ok": True,
            "award_id": native_id,
            **page,
        }

    def get_award_albums(
        self,
        award_id,
        *,
        limit=None,
        offset=None,
    ):
        """Return one bounded provider-native Award album page."""
        native_id = self._catalog_award_request_id(
            award_id
        )
        page_limit, page_offset = self._catalog_page_bounds(
            limit,
            offset,
        )

        params = {
            "award_id": native_id,
            "limit": str(page_limit),
            "offset": str(page_offset),
        }

        payload = self._catalog_request(
            "/award/getAlbums",
            method_name="awardgetAlbums",
            params=params,
            signature_params=dict(params),
            require_auth=True,
        )

        page = self._normalize_qobuz_award_album_page(
            payload,
            page_limit=page_limit,
            page_offset=page_offset,
        )

        return {
            "ok": True,
            "award_id": native_id,
            **page,
        }

    @staticmethod
    def _valid_catalog_secret(secret):
        return (
            isinstance(secret, str)
            and secret == secret.strip()
            and 1 <= len(secret) <= 512
            and secret.isascii()
            and not any(
                ord(char) <= 32 or ord(char) == 127
                for char in secret
            )
        )

    @classmethod
    def _valid_app_secrets(cls, secrets_list):
        return (
            isinstance(secrets_list, (list, tuple))
            and bool(secrets_list)
            and all(
                cls._valid_catalog_secret(value)
                for value in secrets_list
            )
        )

    @classmethod
    def _extract_app_secrets(cls, bundle):
        """Extract Qobuz API signing secrets safely.

        This follows the pinned MIT-licensed QBZ bundle
        extraction contract. OAuth ``private_key`` and
        catalog signing secrets are intentionally separate.
        """
        if not isinstance(bundle, str) or not bundle:
            return []

        seeds = {}
        timezones = []

        for match in cls._APP_SECRET_SEED_RE.finditer(
            bundle
        ):
            seed = match.group("seed")
            timezone = match.group("timezone")

            if seed and timezone:
                seeds[timezone] = seed

                if timezone not in timezones:
                    timezones.append(timezone)

        secrets_list = []

        if seeds:
            timezone_names = []

            for timezone in timezones:
                if not timezone:
                    continue

                timezone_names.append(
                    re.escape(
                        timezone[0].upper()
                        + timezone[1:]
                    )
                )

            if timezone_names:
                info_re = re.compile(
                    r'name:"\w+/(?P<timezone>'
                    + "|".join(timezone_names)
                    + r')",info:"(?P<info>[\w=]+)",'
                    r'extras:"(?P<extras>[\w=]+)"'
                )

                for match in info_re.finditer(bundle):
                    timezone = (
                        match.group("timezone").lower()
                    )

                    seed = seeds.get(timezone)

                    if not seed:
                        continue

                    combined = (
                        seed
                        + match.group("info")
                        + match.group("extras")
                    )

                    if len(combined) <= 44:
                        continue

                    encoded = combined[:-44]

                    try:
                        decoded = base64.b64decode(
                            encoded,
                            validate=True,
                        ).decode("utf-8")
                    except (
                        ValueError,
                        UnicodeDecodeError,
                    ):
                        continue

                    if cls._valid_catalog_secret(
                        decoded
                    ):
                        secrets_list.append(decoded)

        # QBZ retains a simple appSecret fallback for
        # bundle layouts that directly expose a hex secret.
        if not secrets_list:
            for match in (
                cls._APP_SECRET_SIMPLE_RE.finditer(bundle)
            ):
                secret = match.group("secret")

                if cls._valid_catalog_secret(secret):
                    secrets_list.append(secret)

        # Preserve bundle order and eliminate only exact
        # duplicate secret values.
        return list(dict.fromkeys(secrets_list))

    def _download_text(self, url, max_bytes=None):
        limit = int(max_bytes or self.SERVICE_RESPONSE_MAX_BYTES)
        try:
            with self._http.get(url, timeout=(10, 45), stream=True) as response:
                if not 200 <= response.status_code < 300:
                    raise QobuzAuthError("Qobuz service metadata is unavailable")
                chunks = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    chunks.extend(chunk)
                    if len(chunks) > limit:
                        raise QobuzAuthError("Qobuz service response exceeded its limit")
        except requests.exceptions.RequestException as exc:
            raise QobuzAuthError("Qobuz service metadata request failed") from exc
        return bytes(chunks).decode("utf-8", errors="replace")

    def _service_cache_fresh(self, cached):
        fetched_at = cached.get("fetched_at") if isinstance(cached, dict) else None
        try:
            return 0 <= self._now() - float(fetched_at) < self.SERVICE_CACHE_MAX_AGE
        except (TypeError, ValueError):
            return False

    def _load_service_cache(self):
        try:
            cached = self._load_json_file(self._service_cache_file)
        except Exception:
            return None
        if not isinstance(cached, dict):
            return None
        if not re.fullmatch(r"\d{9}", str(cached.get("app_id") or "")):
            return None
        if not re.fullmatch(r"[A-Za-z0-9]{6,30}", str(cached.get("private_key") or "")):
            return None
        bundle_url = str(cached.get("bundle_url") or "")
        if not bundle_url.startswith("/resources/") or not bundle_url.endswith("/bundle.js"):
            return None
        return cached

    def _save_service_cache(self, metadata):
        self._atomic_json_write(self._service_cache_file, metadata)

    def _expire_service_cache(self):
        catalog = getattr(self, "_catalog", None)
        if catalog is not None:
            catalog.clear_validated_secret()

        with self._service_lock:
            self._service_metadata = None
            try:
                os.remove(self._service_cache_file)
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning("Qobuz service metadata cache could not be cleared")

    def _persist_session(self, token):
        self._atomic_json_write(
            self._session_file,
            {"version": 1, "user_auth_token": token},
        )

    def _clear_session_file(self):
        try:
            os.remove(self._session_file)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise QobuzAuthError("Qobuz session file could not be cleared") from exc

    @staticmethod
    def _load_json_file(path):
        try:
            file_stat = os.lstat(path)
        except FileNotFoundError:
            return None
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_size <= 0
            or file_stat.st_size > 65536
        ):
            raise ValueError("invalid private state file size")
        os.chmod(path, 0o600)
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _atomic_json_write(path, payload):
        parent = os.path.dirname(path)
        os.makedirs(parent, mode=0o700, exist_ok=True)
        temp_path = f"{path}.tmp-{secrets.token_hex(8)}"
        descriptor = None
        try:
            descriptor = os.open(
                temp_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = None
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            os.chmod(path, 0o600)
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
            raise

    def _finish_attempt_error(self, attempt_id, message, exc=None):
        with self._auth_lock:
            if attempt_id != self._attempt_id:
                return
            self.authenticated = False
            self._session = None
            self._auth_state = self.AUTH_ERROR
            self._last_error = message
            self._login_nonce = ""
            self._login_context = None
        if exc is None:
            logger.warning("Qobuz authentication attempt ended without a callback")
        else:
            logger.warning(
                "Qobuz authentication attempt failed safely (%s)",
                type(exc).__name__,
            )

    def _record_failure(self, message, exc, unavailable=False):
        with self._auth_lock:
            self.authenticated = False
            self._session = None
            self._auth_state = self.AUTH_UNAVAILABLE if unavailable else self.AUTH_ERROR
            self._last_error = message
            if unavailable:
                self.available = False
                self.initialization_error = message
        logger.warning("Qobuz authentication failure isolated (%s)", type(exc).__name__)

    @staticmethod
    def _close_listener(listener):
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
