"""Read-only authority for official Spotify Soloist artifacts."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Optional

from services.spotify_paths import SpotifyPaths


class SpotifySoloistArtifactError(RuntimeError):
    """A Soloist artifact failed a controlled validation boundary."""

    def __init__(self, message: str, *, code: str = "artifact_invalid") -> None:
        super().__init__(message)
        self.code = code


class SpotifySoloistArtifactStatusCode(str, Enum):
    NOT_INSTALLED = "not_installed"
    VALID = "valid"
    EXPIRED = "expired"
    INVALID_FILE = "invalid_file"
    INVALID_ELF = "invalid_elf"
    VERSION_FAILED = "version_failed"
    INVALID_VERSION = "invalid_version"
    ARCHITECTURE_MISMATCH = "architecture_mismatch"


@dataclass(frozen=True)
class SpotifySoloistBuildInfo:
    version: str
    build_timestamp: int
    build_date_token: str
    build_identifier: str
    platform: str
    architecture: str
    build_datetime_utc: datetime
    expires_at_utc: datetime


@dataclass(frozen=True)
class SpotifySoloistArtifactStatus:
    installed: bool
    valid: bool
    version: Optional[str]
    build_timestamp: Optional[int]
    build_date: Optional[str]
    build_identifier: Optional[str]
    platform: Optional[str]
    architecture: Optional[str]
    sha256: Optional[str]
    expires_at: Optional[str]
    expired: Optional[bool]
    seconds_remaining: Optional[int]
    error_code: str

    def as_dict(self) -> dict:
        return asdict(self)


_ARCHITECTURE_ALIASES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "armv7l": "armv7l",
}

_ARCHIVE_URLS = {
    "x86_64": (
        "https://soloist-builds.spotifycdn.com/"
        "soloist_release_x86_64.tar.gz"
    ),
    "aarch64": (
        "https://soloist-builds.spotifycdn.com/"
        "soloist_release_arm64.tar.gz"
    ),
    "armv7l": (
        "https://soloist-builds.spotifycdn.com/"
        "soloist_release_arm32.tar.gz"
    ),
}

_ELF_CONTRACTS = {
    "x86_64": (2, 62, 64),
    "aarch64": (2, 183, 64),
    "armv7l": (1, 40, 52),
}

_VERSION_RE = re.compile(
    r"soloist "
    r"(?P<version>[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}) "
    r"build (?P<timestamp>[0-9]{1,12}) "
    r"\((?P<date>[0-9]{8})\) "
    r"\((?P<identifier>[A-Za-z0-9][A-Za-z0-9._+\-]{0,63})\) "
    r"\(linux/(?P<architecture>x86_64|aarch64|armv7l)\)"
)

_MIN_BUILD_TIMESTAMP = 946684800  # 2000-01-01T00:00:00Z
_MAX_BUILD_TIMESTAMP = 4102444800  # 2100-01-01T00:00:00Z
_EXPIRY_DAYS = 90
_MAX_VERSION_STREAM_BYTES = 4096
_DEFAULT_VERSION_TIMEOUT_SECONDS = 3.0


def normalize_spotify_architecture(architecture: str) -> str:
    if not isinstance(architecture, str):
        raise SpotifySoloistArtifactError("Unsupported Soloist architecture")
    canonical = _ARCHITECTURE_ALIASES.get(architecture.strip().lower())
    if canonical is None:
        raise SpotifySoloistArtifactError("Unsupported Soloist architecture")
    return canonical


def official_soloist_archive_url(architecture: str) -> str:
    return _ARCHIVE_URLS[normalize_spotify_architecture(architecture)]


def parse_soloist_version(output: str) -> SpotifySoloistBuildInfo:
    if not isinstance(output, str):
        raise SpotifySoloistArtifactError(
            "Soloist version output is invalid",
            code=SpotifySoloistArtifactStatusCode.INVALID_VERSION.value,
        )
    text = output.strip()
    if not text or "\n" in text or "\r" in text:
        raise SpotifySoloistArtifactError(
            "Soloist version output is invalid",
            code=SpotifySoloistArtifactStatusCode.INVALID_VERSION.value,
        )
    match = _VERSION_RE.fullmatch(text)
    if match is None:
        raise SpotifySoloistArtifactError(
            "Soloist version output is invalid",
            code=SpotifySoloistArtifactStatusCode.INVALID_VERSION.value,
        )

    build_timestamp = int(match.group("timestamp"))
    if not _MIN_BUILD_TIMESTAMP <= build_timestamp < _MAX_BUILD_TIMESTAMP:
        raise SpotifySoloistArtifactError(
            "Soloist build timestamp is invalid",
            code=SpotifySoloistArtifactStatusCode.INVALID_VERSION.value,
        )
    build_datetime = datetime.fromtimestamp(build_timestamp, timezone.utc)
    date_token = match.group("date")
    try:
        parsed_date = datetime.strptime(date_token, "%Y%m%d").date()
    except ValueError:
        raise SpotifySoloistArtifactError(
            "Soloist build date is invalid",
            code=SpotifySoloistArtifactStatusCode.INVALID_VERSION.value,
        ) from None
    if parsed_date != build_datetime.date():
        raise SpotifySoloistArtifactError(
            "Soloist build date does not match its timestamp",
            code=SpotifySoloistArtifactStatusCode.INVALID_VERSION.value,
        )

    architecture = match.group("architecture")
    if architecture not in _ELF_CONTRACTS:
        raise SpotifySoloistArtifactError(
            "Soloist reported architecture is invalid",
            code=SpotifySoloistArtifactStatusCode.INVALID_VERSION.value,
        )

    return SpotifySoloistBuildInfo(
        version=match.group("version"),
        build_timestamp=build_timestamp,
        build_date_token=date_token,
        build_identifier=match.group("identifier"),
        platform="linux",
        architecture=architecture,
        build_datetime_utc=build_datetime,
        expires_at_utc=build_datetime + timedelta(days=_EXPIRY_DAYS),
    )


def evaluate_soloist_expiry(
    build: SpotifySoloistBuildInfo,
    *,
    now: datetime,
) -> tuple[datetime, bool, int]:
    if not isinstance(build, SpotifySoloistBuildInfo):
        raise SpotifySoloistArtifactError("Soloist build information is invalid")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise SpotifySoloistArtifactError("Expiry reference time must include UTC")
    reference = now.astimezone(timezone.utc)
    expires_at = build.expires_at_utc
    expired = reference >= expires_at
    seconds_remaining = max(0, int((expires_at - reference).total_seconds()))
    return expires_at, expired, seconds_remaining


def inspect_soloist_elf(path: os.PathLike | str, architecture: str) -> str:
    canonical = normalize_spotify_architecture(architecture)
    try:
        path_text = os.fspath(path)
    except TypeError:
        raise SpotifySoloistArtifactError(
            "Soloist executable is invalid",
            code=SpotifySoloistArtifactStatusCode.INVALID_FILE.value,
        ) from None
    if not isinstance(path_text, str) or not path_text:
        raise SpotifySoloistArtifactError(
            "Soloist executable is invalid",
            code=SpotifySoloistArtifactStatusCode.INVALID_FILE.value,
        )
    try:
        before = os.lstat(path_text)
    except OSError:
        raise SpotifySoloistArtifactError(
            "Soloist executable is unavailable",
            code=SpotifySoloistArtifactStatusCode.INVALID_FILE.value,
        ) from None
    if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
        raise SpotifySoloistArtifactError(
            "Soloist executable is not a regular file",
            code=SpotifySoloistArtifactStatusCode.INVALID_FILE.value,
        )

    elf_class, machine, header_size = _ELF_CONTRACTS[canonical]
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(path_text, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
            or opened.st_size < header_size
        ):
            raise SpotifySoloistArtifactError(
                "Soloist ELF file is invalid",
                code=SpotifySoloistArtifactStatusCode.INVALID_ELF.value,
            )
        header = os.read(descriptor, header_size)
    except SpotifySoloistArtifactError:
        raise
    except OSError:
        raise SpotifySoloistArtifactError(
            "Soloist ELF file could not be read",
            code=SpotifySoloistArtifactStatusCode.INVALID_ELF.value,
        ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if (
        len(header) != header_size
        or header[:4] != b"\x7fELF"
        or header[4] != elf_class
        or header[5] != 1
        or header[6] != 1
        or int.from_bytes(header[18:20], "little") != machine
    ):
        raise SpotifySoloistArtifactError(
            "Soloist ELF architecture is invalid",
            code=SpotifySoloistArtifactStatusCode.INVALID_ELF.value,
        )
    return canonical


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_status(
    *,
    installed: bool,
    code: SpotifySoloistArtifactStatusCode,
) -> SpotifySoloistArtifactStatus:
    return SpotifySoloistArtifactStatus(
        installed=installed,
        valid=False,
        version=None,
        build_timestamp=None,
        build_date=None,
        build_identifier=None,
        platform=None,
        architecture=None,
        sha256=None,
        expires_at=None,
        expired=None,
        seconds_remaining=None,
        error_code=code.value,
    )


class SpotifySoloistArtifactAuthority:
    """Inspect only the manager-owned Soloist executable from SpotifyPaths."""

    def __init__(
        self,
        *,
        paths: SpotifyPaths,
        host_architecture: Optional[str] = None,
        command_runner: Callable = subprocess.run,
        version_timeout_seconds: float = _DEFAULT_VERSION_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(paths, SpotifyPaths):
            raise SpotifySoloistArtifactError("Spotify path authority is invalid")
        architecture = host_architecture
        if architecture is None:
            architecture = os.uname().machine
        self._architecture = normalize_spotify_architecture(architecture)
        self._binary_path = os.path.normpath(
            os.path.join(paths.soloist_install_dir, "soloist")
        )
        if not os.path.isabs(self._binary_path):
            raise SpotifySoloistArtifactError("Soloist executable path is invalid")
        try:
            timeout = float(version_timeout_seconds)
        except (TypeError, ValueError):
            raise SpotifySoloistArtifactError(
                "Soloist version timeout is invalid"
            ) from None
        if timeout <= 0:
            raise SpotifySoloistArtifactError("Soloist version timeout is invalid")
        self._runner = command_runner
        self._version_timeout = timeout

    @property
    def canonical_architecture(self) -> str:
        return self._architecture

    def official_archive_url(self) -> str:
        return official_soloist_archive_url(self._architecture)

    def inspect_installed(
        self,
        *,
        now: Optional[datetime] = None,
    ) -> SpotifySoloistArtifactStatus:
        try:
            info = os.lstat(self._binary_path)
        except FileNotFoundError:
            return _empty_status(
                installed=False,
                code=SpotifySoloistArtifactStatusCode.NOT_INSTALLED,
            )
        except OSError:
            return _empty_status(
                installed=False,
                code=SpotifySoloistArtifactStatusCode.INVALID_FILE,
            )
        if not stat.S_ISREG(info.st_mode) or not os.access(
            self._binary_path, os.X_OK
        ):
            return _empty_status(
                installed=True,
                code=SpotifySoloistArtifactStatusCode.INVALID_FILE,
            )

        try:
            inspect_soloist_elf(self._binary_path, self._architecture)
            build = self._inspect_version()
            if build.architecture != self._architecture:
                raise SpotifySoloistArtifactError(
                    "Soloist architecture does not match this host",
                    code=(
                        SpotifySoloistArtifactStatusCode.ARCHITECTURE_MISMATCH.value
                    ),
                )
            digest = self._sha256()
            reference = datetime.now(timezone.utc) if now is None else now
            expires_at, expired, seconds_remaining = evaluate_soloist_expiry(
                build,
                now=reference,
            )
        except SpotifySoloistArtifactError as error:
            try:
                code = SpotifySoloistArtifactStatusCode(error.code)
            except ValueError:
                code = SpotifySoloistArtifactStatusCode.INVALID_FILE
            return _empty_status(installed=True, code=code)

        code = (
            SpotifySoloistArtifactStatusCode.EXPIRED
            if expired
            else SpotifySoloistArtifactStatusCode.VALID
        )
        return SpotifySoloistArtifactStatus(
            installed=True,
            valid=not expired,
            version=build.version,
            build_timestamp=build.build_timestamp,
            build_date=build.build_date_token,
            build_identifier=build.build_identifier,
            platform=build.platform,
            architecture=build.architecture,
            sha256=digest,
            expires_at=_utc_text(expires_at),
            expired=expired,
            seconds_remaining=seconds_remaining,
            error_code=code.value,
        )

    def status_snapshot(
        self,
        *,
        now: Optional[datetime] = None,
    ) -> dict:
        return self.inspect_installed(now=now).as_dict()

    def _inspect_version(self) -> SpotifySoloistBuildInfo:
        try:
            completed = self._runner(
                [self._binary_path, "--version"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self._version_timeout,
                check=False,
                shell=False,
            )
        except Exception:
            raise SpotifySoloistArtifactError(
                "Soloist version inspection failed",
                code=SpotifySoloistArtifactStatusCode.VERSION_FAILED.value,
            ) from None
        if getattr(completed, "returncode", None) != 0:
            raise SpotifySoloistArtifactError(
                "Soloist version inspection failed",
                code=SpotifySoloistArtifactStatusCode.VERSION_FAILED.value,
            )
        stdout = self._bounded_stream(getattr(completed, "stdout", None))
        self._bounded_stream(getattr(completed, "stderr", None))
        try:
            version_text = stdout.decode("ascii")
        except UnicodeDecodeError:
            raise SpotifySoloistArtifactError(
                "Soloist version output is invalid",
                code=SpotifySoloistArtifactStatusCode.INVALID_VERSION.value,
            ) from None
        return parse_soloist_version(version_text)

    @staticmethod
    def _bounded_stream(value) -> bytes:
        if isinstance(value, str):
            try:
                data = value.encode("utf-8")
            except UnicodeError:
                data = b""
        elif isinstance(value, bytes):
            data = value
        else:
            raise SpotifySoloistArtifactError(
                "Soloist version output is invalid",
                code=SpotifySoloistArtifactStatusCode.VERSION_FAILED.value,
            )
        if len(data) > _MAX_VERSION_STREAM_BYTES:
            raise SpotifySoloistArtifactError(
                "Soloist version output is too large",
                code=SpotifySoloistArtifactStatusCode.VERSION_FAILED.value,
            )
        return data

    def _sha256(self) -> str:
        digest = hashlib.sha256()
        descriptor = None
        try:
            before = os.lstat(self._binary_path)
            flags = os.O_RDONLY
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self._binary_path, flags)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != before.st_dev
                or opened.st_ino != before.st_ino
            ):
                raise OSError("changed artifact")
            while True:
                block = os.read(descriptor, 1024 * 1024)
                if not block:
                    break
                digest.update(block)
        except OSError:
            raise SpotifySoloistArtifactError(
                "Soloist executable could not be hashed",
                code=SpotifySoloistArtifactStatusCode.INVALID_FILE.value,
            ) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return digest.hexdigest()


__all__ = [
    "SpotifySoloistArtifactAuthority",
    "SpotifySoloistArtifactError",
    "SpotifySoloistArtifactStatus",
    "SpotifySoloistArtifactStatusCode",
    "SpotifySoloistBuildInfo",
    "evaluate_soloist_expiry",
    "inspect_soloist_elf",
    "normalize_spotify_architecture",
    "official_soloist_archive_url",
    "parse_soloist_version",
]
