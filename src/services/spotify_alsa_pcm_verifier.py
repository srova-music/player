"""Fail-closed kernel authority for selected ALSA playback PCM release."""

from __future__ import annotations

import math
import os
import re
import stat
import time
from pathlib import Path


class SpotifyAlsaPcmVerificationError(RuntimeError):
    """Raised when PCM safety cannot be positively established."""


class SpotifyAlsaPcmVerifier:
    """Verify selected ALSA playback PCM ownership via /proc/asound.

    A PCM is considered free only when every enumerated playback substream
    status is readable and exactly ``closed`` after surrounding whitespace is
    stripped.

    Any valid ALSA state record such as ``state: RUNNING`` is busy.

    Missing, unreadable, malformed or structurally unsafe proc entries are
    verification errors and therefore can never authorize native playback.
    """

    _BUSY_STATE_RE = re.compile(
        r"^state:\s+[A-Z][A-Z0-9_-]*$"
    )

    def __init__(
        self,
        *,
        proc_root: str = "/proc/asound",
        wait_timeout_seconds: float = 10.0,
        poll_seconds: float = 0.05,
        max_status_chars: int = 4096,
    ) -> None:
        self._proc_root = self._absolute_path(proc_root)
        self._wait_timeout_seconds = self._positive_seconds(
            wait_timeout_seconds
        )
        self._poll_seconds = self._positive_seconds(
            poll_seconds
        )
        self._max_status_chars = self._positive_int(
            max_status_chars
        )

    @property
    def proc_root(self) -> str:
        return self._proc_root

    def is_free(
        self,
        *,
        card_number: int,
        device_number: int,
    ) -> bool:
        """Return True only after a positive all-substreams-closed scan."""

        card = self._device_number(card_number)
        device = self._device_number(device_number)

        status_paths = self._status_paths(
            card,
            device,
        )

        busy = False

        for status_path in status_paths:
            value = self._read_status(status_path)

            if value == "closed":
                continue

            first_line = value.splitlines()[0].strip()

            if self._BUSY_STATE_RE.fullmatch(first_line) is None:
                raise SpotifyAlsaPcmVerificationError(
                    "Selected ALSA PCM status is invalid"
                )

            busy = True

        return not busy

    def is_absent(
        self,
        *,
        card_number: int,
        device_number: int,
    ) -> bool:
        """Return True only when the selected PCM path physically does not exist.

        This is deliberately separate from is_free(): an absent PCM is never
        treated as positive "closed" evidence.
        """

        card = self._device_number(card_number)
        device = self._device_number(device_number)

        proc_root = self._proc_root
        card_root = os.path.join(
            proc_root,
            f"card{card}",
        )
        pcm_root = os.path.join(
            card_root,
            f"pcm{device}p",
        )

        try:
            root_stat = os.lstat(proc_root)
        except OSError:
            return False

        if (
            stat.S_ISLNK(root_stat.st_mode)
            or not stat.S_ISDIR(root_stat.st_mode)
        ):
            return False

        try:
            card_stat = os.lstat(card_root)
        except FileNotFoundError:
            return True
        except OSError:
            return False

        if (
            stat.S_ISLNK(card_stat.st_mode)
            or not stat.S_ISDIR(card_stat.st_mode)
        ):
            return False

        try:
            pcm_stat = os.lstat(pcm_root)
        except FileNotFoundError:
            return True
        except OSError:
            return False

        if (
            stat.S_ISLNK(pcm_stat.st_mode)
            or not stat.S_ISDIR(pcm_stat.st_mode)
        ):
            return False

        return False

    def wait_until_free(
        self,
        *,
        card_number: int,
        device_number: int,
    ) -> bool:
        """Poll until positive kernel evidence proves the PCM is free.

        Returns True only on verified release. Timeout and inspection
        uncertainty raise SpotifyAlsaPcmVerificationError.
        """

        card = self._device_number(card_number)
        device = self._device_number(device_number)

        deadline = time.monotonic() + self._wait_timeout_seconds

        while True:
            if self.is_free(
                card_number=card,
                device_number=device,
            ):
                return True

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                raise SpotifyAlsaPcmVerificationError(
                    "Selected ALSA PCM did not become free"
                )

            time.sleep(
                min(
                    self._poll_seconds,
                    remaining,
                )
            )

    @staticmethod
    def _absolute_path(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(
                "proc_root must be an absolute path"
            )

        path = Path(value)

        if not path.is_absolute():
            raise ValueError(
                "proc_root must be an absolute path"
            )

        return str(path)

    @staticmethod
    def _positive_seconds(value: object) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            raise ValueError(
                "timeout values must be positive finite numbers"
            )

        result = float(value)

        if not math.isfinite(result) or result <= 0:
            raise ValueError(
                "timeout values must be positive finite numbers"
            )

        return result

    @staticmethod
    def _positive_int(value: object) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
        ):
            raise ValueError(
                "max_status_chars must be a positive integer"
            )

        return value

    @staticmethod
    def _device_number(value: object) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise SpotifyAlsaPcmVerificationError(
                "ALSA PCM identity is invalid"
            )

        return value

    def _status_paths(
        self,
        card_number: int,
        device_number: int,
    ) -> tuple[str, ...]:
        pcm_root = os.path.join(
            self._proc_root,
            f"card{card_number}",
            f"pcm{device_number}p",
        )

        try:
            root_stat = os.lstat(pcm_root)

            if (
                stat.S_ISLNK(root_stat.st_mode)
                or not stat.S_ISDIR(root_stat.st_mode)
            ):
                raise SpotifyAlsaPcmVerificationError(
                    "Selected ALSA PCM status is unavailable"
                )

            status_paths: list[tuple[int, str]] = []

            with os.scandir(pcm_root) as entries:
                for entry in entries:
                    match = re.fullmatch(
                        r"sub(\d+)",
                        entry.name,
                    )

                    if match is None:
                        continue

                    if not entry.is_dir(
                        follow_symlinks=False
                    ):
                        raise SpotifyAlsaPcmVerificationError(
                            "Selected ALSA PCM status is unavailable"
                        )

                    status_path = os.path.join(
                        pcm_root,
                        entry.name,
                        "status",
                    )

                    status_stat = os.lstat(
                        status_path
                    )

                    if (
                        stat.S_ISLNK(status_stat.st_mode)
                        or not stat.S_ISREG(
                            status_stat.st_mode
                        )
                    ):
                        raise SpotifyAlsaPcmVerificationError(
                            "Selected ALSA PCM status is unavailable"
                        )

                    status_paths.append(
                        (
                            int(match.group(1)),
                            status_path,
                        )
                    )

        except SpotifyAlsaPcmVerificationError:
            raise

        except (OSError, ValueError):
            raise SpotifyAlsaPcmVerificationError(
                "Selected ALSA PCM status is unavailable"
            ) from None

        if not status_paths:
            raise SpotifyAlsaPcmVerificationError(
                "Selected ALSA PCM status is unavailable"
            )

        status_paths.sort(
            key=lambda item: item[0]
        )

        return tuple(
            path
            for _index, path in status_paths
        )

    def _read_status(self, path: str) -> str:
        try:
            with open(
                path,
                "r",
                encoding="utf-8",
                errors="strict",
            ) as handle:
                content = handle.read(
                    self._max_status_chars + 1
                )

        except (OSError, UnicodeError):
            raise SpotifyAlsaPcmVerificationError(
                "Selected ALSA PCM status is unavailable"
            ) from None

        if len(content) > self._max_status_chars:
            raise SpotifyAlsaPcmVerificationError(
                "Selected ALSA PCM status is invalid"
            )

        value = content.strip()

        if not value:
            raise SpotifyAlsaPcmVerificationError(
                "Selected ALSA PCM status is invalid"
            )

        return value


__all__ = [
    "SpotifyAlsaPcmVerificationError",
    "SpotifyAlsaPcmVerifier",
]
