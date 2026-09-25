"""Private persistence for the optional Spotify Soloist API key."""

from __future__ import annotations

import json
import os
import secrets
import stat
import threading

from utils.paths import get_config_dir


class SpotifySecretStoreError(RuntimeError):
    """Spotify private state could not be read or written safely."""


class SpotifySecretStore:
    """Persist the user-supplied Spotify API key outside general settings."""

    PRIVATE_DIRNAME = "spotify"
    STATE_FILENAME = "private_state.json"

    MAX_API_KEY_BYTES = 8192
    MAX_STATE_BYTES = 16384

    def __init__(self, config_dir: str | None = None):
        root = str(config_dir or get_config_dir() or "").strip()
        if not root:
            raise SpotifySecretStoreError("Spotify config root is unavailable")

        self._private_dir = os.path.join(root, self.PRIVATE_DIRNAME)
        self._state_file = os.path.join(
            self._private_dir,
            self.STATE_FILENAME,
        )
        self._lock = threading.RLock()

    @property
    def private_dir(self) -> str:
        return self._private_dir

    @property
    def state_file(self) -> str:
        return self._state_file

    @classmethod
    def _validate_api_key(cls, value) -> str:
        if not isinstance(value, str):
            raise ValueError("invalid Spotify API key")

        if (
            value != value.strip()
            or not value
            or not value.isascii()
            or len(value.encode("ascii")) > cls.MAX_API_KEY_BYTES
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("invalid Spotify API key")

        return value

    def _secure_existing_private_dir(self) -> bool:
        try:
            info = os.lstat(self._private_dir)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise SpotifySecretStoreError(
                "Spotify private state directory is unavailable"
            ) from exc

        if not stat.S_ISDIR(info.st_mode):
            raise SpotifySecretStoreError(
                "Spotify private state directory is invalid"
            )

        try:
            os.chmod(self._private_dir, 0o700)
        except OSError as exc:
            raise SpotifySecretStoreError(
                "Spotify private state directory permissions could not be secured"
            ) from exc

        return True

    def _ensure_private_dir(self) -> None:
        os.makedirs(
            self._private_dir,
            mode=0o700,
            exist_ok=True,
        )

        if not self._secure_existing_private_dir():
            raise SpotifySecretStoreError(
                "Spotify private state directory is unavailable"
            )

    def _load_payload(self) -> dict:
        if not self._secure_existing_private_dir():
            return {}

        try:
            info = os.lstat(self._state_file)
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise SpotifySecretStoreError(
                "Spotify private state could not be inspected"
            ) from exc

        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > self.MAX_STATE_BYTES
        ):
            raise SpotifySecretStoreError(
                "Spotify private state file is invalid"
            )

        try:
            os.chmod(self._state_file, 0o600)
            with open(self._state_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            raise SpotifySecretStoreError(
                "Spotify private state could not be read"
            ) from exc

        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or set(payload) != {"version", "api_key"}
        ):
            raise SpotifySecretStoreError(
                "Spotify private state payload is invalid"
            )

        try:
            self._validate_api_key(payload.get("api_key"))
        except ValueError as exc:
            raise SpotifySecretStoreError(
                "Spotify private state contains an invalid API key"
            ) from exc

        return payload

    def get_api_key(self) -> str | None:
        with self._lock:
            payload = self._load_payload()
            value = payload.get("api_key")
            if value is None:
                return None
            return self._validate_api_key(value)

    def key_configured(self) -> bool:
        return self.get_api_key() is not None

    def set_api_key(self, value: str) -> None:
        api_key = self._validate_api_key(value)

        with self._lock:
            self._ensure_private_dir()

            temp_path = os.path.join(
                self._private_dir,
                ".private-state.tmp-" + secrets.token_hex(8),
            )
            descriptor = None

            try:
                descriptor = os.open(
                    temp_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )

                with os.fdopen(
                    descriptor,
                    "w",
                    encoding="utf-8",
                ) as handle:
                    descriptor = None

                    json.dump(
                        {
                            "version": 1,
                            "api_key": api_key,
                        },
                        handle,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    handle.flush()
                    os.fsync(handle.fileno())

                os.replace(
                    temp_path,
                    self._state_file,
                )
                os.chmod(
                    self._state_file,
                    0o600,
                )

            except Exception as exc:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass

                try:
                    os.remove(temp_path)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

                if isinstance(exc, SpotifySecretStoreError):
                    raise

                raise SpotifySecretStoreError(
                    "Spotify private state could not be written"
                ) from exc


__all__ = [
    "SpotifySecretStore",
    "SpotifySecretStoreError",
]
