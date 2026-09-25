"""Transactional installer for the official Spotify Soloist artifact."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Optional

from services.spotify_paths import SpotifyPaths
from services.spotify_soloist_artifact import (
    SpotifySoloistArtifactAuthority,
    SpotifySoloistArtifactError,
)


MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 128 * 1024 * 1024
MAX_DECLARED_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 128
DOWNLOAD_CHUNK_BYTES = 128 * 1024
EXTRACT_CHUNK_BYTES = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30.0
INSTALL_DIRECTORY_MODE = 0o700
BINARY_MODE = 0o500
OFFICIAL_DOWNLOAD_HOST = "soloist-builds.spotifycdn.com"


class SpotifySoloistInstallerError(RuntimeError):
    """A controlled installer operation failed."""

    def __init__(self, code: str) -> None:
        super().__init__("Soloist installation failed")
        self.code = code


@dataclass(frozen=True)
class SpotifySoloistInstallResult:
    success: bool
    changed: bool
    action: str
    version: Optional[str]
    build_timestamp: Optional[int]
    architecture: Optional[str]
    binary_sha256: Optional[str]
    archive_sha256: Optional[str]
    error_code: Optional[str]


@dataclass(frozen=True)
class SpotifySoloistUpdateCheckResult:
    ok: bool
    installed: bool
    update_available: bool
    error_code: str


@dataclass(frozen=True)
class _DownloadedArchive:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class _ExistingFile:
    exists: bool
    device: Optional[int]
    inode: Optional[int]


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, url):
        return None


class SpotifySoloistInstaller:
    """Download, validate, and atomically replace one managed executable."""

    def __init__(
        self,
        *,
        paths: SpotifyPaths,
        host_architecture: Optional[str] = None,
        command_runner: Callable = subprocess.run,
        url_opener: Optional[Callable] = None,
        download_timeout_seconds: float = DOWNLOAD_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(paths, SpotifyPaths):
            raise SpotifySoloistInstallerError("unsafe_install_directory")
        try:
            timeout = float(download_timeout_seconds)
        except (TypeError, ValueError):
            raise SpotifySoloistInstallerError("download_failed") from None
        if timeout <= 0:
            raise SpotifySoloistInstallerError("download_failed")

        self._paths = paths
        self._host_architecture = host_architecture
        self._command_runner = command_runner
        self._url_opener = url_opener
        self._download_timeout = timeout
        self._install_dir = os.path.normpath(paths.soloist_install_dir)
        self._final_binary = os.path.join(self._install_dir, "soloist")
        if not os.path.isabs(self._install_dir):
            raise SpotifySoloistInstallerError("unsafe_install_directory")
        self._lock = threading.RLock()

    def install_or_update(
        self,
        *,
        now: Optional[datetime] = None,
    ) -> SpotifySoloistInstallResult:
        """Run one bounded transaction; never raise untrusted details."""
        with self._lock:
            return self._install_locked(now=now)

    def check_for_update(
        self,
        *,
        now: Optional[datetime] = None,
    ) -> SpotifySoloistUpdateCheckResult:
        """Compare the installed artifact with the official candidate."""
        with self._lock:
            return self._check_for_update_locked(now=now)

    def _check_for_update_locked(
        self,
        *,
        now: Optional[datetime],
    ) -> SpotifySoloistUpdateCheckResult:
        staging_dir = None
        try:
            authority = self._authority(self._paths)
            existing = authority.inspect_installed(now=now)
            if existing.installed is not True:
                return SpotifySoloistUpdateCheckResult(
                    ok=True,
                    installed=False,
                    update_available=False,
                    error_code="not_installed",
                )
            if (
                existing.valid is not True
                or existing.expired is not False
                or existing.build_timestamp is None
                or existing.sha256 is None
                or existing.architecture is None
            ):
                return self._update_check_failure(installed=True)

            url = authority.official_archive_url()
            self._validate_official_url(url)
            staging_dir = tempfile.mkdtemp(prefix=".srova-soloist-check-")
            os.chmod(staging_dir, INSTALL_DIRECTORY_MODE)

            archive_path = os.path.join(staging_dir, "archive.tar.gz")
            downloaded = self._download(url, archive_path)
            member_size = self._scan_archive(downloaded.path)
            staged_binary = os.path.join(staging_dir, "soloist")
            self._extract_candidate(
                downloaded.path,
                staged_binary,
                declared_size=member_size,
            )

            candidate_paths = replace(
                self._paths,
                soloist_install_dir=staging_dir,
            )
            candidate = self._authority(candidate_paths).inspect_installed(
                now=now
            )
            if (
                candidate.installed is not True
                or candidate.valid is not True
                or candidate.expired is not False
                or candidate.build_timestamp is None
                or candidate.sha256 is None
                or candidate.architecture is None
            ):
                return self._update_check_failure(installed=True)

            if candidate.build_timestamp > existing.build_timestamp:
                return SpotifySoloistUpdateCheckResult(
                    ok=True,
                    installed=True,
                    update_available=True,
                    error_code="update_available",
                )
            if candidate.build_timestamp < existing.build_timestamp:
                return SpotifySoloistUpdateCheckResult(
                    ok=True,
                    installed=True,
                    update_available=False,
                    error_code="current",
                )
            if candidate.sha256 != existing.sha256:
                return self._update_check_failure(installed=True)
            return SpotifySoloistUpdateCheckResult(
                ok=True,
                installed=True,
                update_available=False,
                error_code="current",
            )
        except Exception:
            return self._update_check_failure(installed=True)
        finally:
            if staging_dir is not None:
                self._remove_check_staging(staging_dir)

    def _install_locked(
        self,
        *,
        now: Optional[datetime],
    ) -> SpotifySoloistInstallResult:
        staging_dir = None
        archive_sha256 = None
        committed = False
        committed_result = None
        try:
            authority = self._authority(self._paths)
            url = authority.official_archive_url()
            self._validate_official_url(url)
            existing_file = self._inspect_final_object()
            existing = authority.inspect_installed(now=now)

            self._prepare_install_directory()
            staging_dir = tempfile.mkdtemp(
                prefix=".srova-soloist-install-",
                dir=self._install_dir,
            )
            os.chmod(staging_dir, INSTALL_DIRECTORY_MODE)

            archive_path = os.path.join(staging_dir, "archive.tar.gz")
            downloaded = self._download(url, archive_path)
            archive_sha256 = downloaded.sha256

            member_size = self._scan_archive(downloaded.path)
            staged_binary = os.path.join(staging_dir, "soloist")
            self._extract_candidate(
                downloaded.path,
                staged_binary,
                declared_size=member_size,
            )

            candidate_paths = replace(
                self._paths,
                soloist_install_dir=staging_dir,
            )
            candidate_authority = self._authority(candidate_paths)
            candidate = candidate_authority.inspect_installed(now=now)
            if candidate.error_code == "expired" or candidate.expired is True:
                raise SpotifySoloistInstallerError("candidate_expired")
            if (
                candidate.installed is not True
                or candidate.valid is not True
                or candidate.expired is not False
                or candidate.build_timestamp is None
                or candidate.sha256 is None
                or candidate.architecture is None
            ):
                raise SpotifySoloistInstallerError("invalid_candidate")

            action = "updated" if existing_file.exists else "installed"
            if (
                existing.build_timestamp is not None
                and existing.sha256 is not None
            ):
                if candidate.build_timestamp < existing.build_timestamp:
                    raise SpotifySoloistInstallerError("downgrade_rejected")
                if candidate.build_timestamp == existing.build_timestamp:
                    if candidate.sha256 == existing.sha256:
                        return SpotifySoloistInstallResult(
                            success=True,
                            changed=False,
                            action="unchanged",
                            version=candidate.version,
                            build_timestamp=candidate.build_timestamp,
                            architecture=candidate.architecture,
                            binary_sha256=candidate.sha256,
                            archive_sha256=archive_sha256,
                            error_code=None,
                        )
                    raise SpotifySoloistInstallerError("same_build_conflict")

            self._verify_final_unchanged(existing_file)
            try:
                os.replace(staged_binary, self._final_binary)
            except OSError:
                raise SpotifySoloistInstallerError("commit_failed") from None
            committed = True
            committed_result = SpotifySoloistInstallResult(
                success=True,
                changed=True,
                action=action,
                version=candidate.version,
                build_timestamp=candidate.build_timestamp,
                architecture=candidate.architecture,
                binary_sha256=candidate.sha256,
                archive_sha256=archive_sha256,
                error_code=None,
            )

            self._verify_committed_file()
            self._fsync_install_directory()
            return committed_result
        except SpotifySoloistInstallerError as error:
            if committed and committed_result is not None:
                return committed_result
            return self._failure(error.code, archive_sha256=archive_sha256)
        except Exception:
            if committed and committed_result is not None:
                return committed_result
            return self._failure(
                "download_failed",
                archive_sha256=archive_sha256,
            )
        finally:
            if staging_dir is not None:
                try:
                    self._remove_staging(staging_dir)
                except Exception:
                    pass

    def _authority(self, paths: SpotifyPaths) -> SpotifySoloistArtifactAuthority:
        try:
            return SpotifySoloistArtifactAuthority(
                paths=paths,
                host_architecture=self._host_architecture,
                command_runner=self._command_runner,
            )
        except SpotifySoloistArtifactError:
            raise SpotifySoloistInstallerError(
                "unsupported_architecture"
            ) from None

    @staticmethod
    def _validate_official_url(url: str) -> None:
        try:
            parsed = urllib.parse.urlsplit(url)
        except (TypeError, ValueError):
            raise SpotifySoloistInstallerError("unexpected_response") from None
        if (
            parsed.scheme != "https"
            or parsed.hostname != OFFICIAL_DOWNLOAD_HOST
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise SpotifySoloistInstallerError("unexpected_response")

    def _inspect_final_object(self) -> _ExistingFile:
        try:
            info = os.lstat(self._install_dir)
        except FileNotFoundError:
            return _ExistingFile(False, None, None)
        except OSError:
            raise SpotifySoloistInstallerError("unsafe_install_directory") from None
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise SpotifySoloistInstallerError("unsafe_install_directory")

        try:
            final_info = os.lstat(self._final_binary)
        except FileNotFoundError:
            return _ExistingFile(False, None, None)
        except OSError:
            raise SpotifySoloistInstallerError("unsafe_install_directory") from None
        if (
            not stat.S_ISREG(final_info.st_mode)
            or final_info.st_uid != os.geteuid()
        ):
            raise SpotifySoloistInstallerError("unsafe_install_directory")
        return _ExistingFile(True, final_info.st_dev, final_info.st_ino)

    def _prepare_install_directory(self) -> None:
        try:
            os.makedirs(
                self._install_dir,
                mode=INSTALL_DIRECTORY_MODE,
                exist_ok=True,
            )
            info = os.lstat(self._install_dir)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
                raise SpotifySoloistInstallerError("unsafe_install_directory")
            os.chmod(self._install_dir, INSTALL_DIRECTORY_MODE)
            secured = os.lstat(self._install_dir)
            if (
                not stat.S_ISDIR(secured.st_mode)
                or secured.st_uid != os.geteuid()
                or stat.S_IMODE(secured.st_mode) != INSTALL_DIRECTORY_MODE
            ):
                raise SpotifySoloistInstallerError("unsafe_install_directory")
        except SpotifySoloistInstallerError:
            raise
        except OSError:
            raise SpotifySoloistInstallerError("unsafe_install_directory") from None

    def _download(self, url: str, destination: str) -> _DownloadedArchive:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": "SROVA-Soloist-Installer/1"},
        )
        response = None
        descriptor = None
        try:
            opener = self._url_opener
            if opener is None:
                opener = urllib.request.build_opener(_RejectRedirects()).open
            response = opener(request, timeout=self._download_timeout)
        except Exception:
            raise SpotifySoloistInstallerError("download_failed") from None

        try:
            final_url = response.geturl()
            status_code = getattr(response, "status", None)
            if status_code is None and hasattr(response, "getcode"):
                status_code = response.getcode()
            if final_url != url or status_code != 200:
                raise SpotifySoloistInstallerError("unexpected_response")

            declared_length = None
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except (TypeError, ValueError):
                    raise SpotifySoloistInstallerError(
                        "unexpected_response"
                    ) from None
                if declared_length < 0:
                    raise SpotifySoloistInstallerError("unexpected_response")
                if declared_length > MAX_ARCHIVE_BYTES:
                    raise SpotifySoloistInstallerError("download_too_large")

            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(destination, flags, 0o600)
            digest = hashlib.sha256()
            total = 0
            while True:
                block = response.read(DOWNLOAD_CHUNK_BYTES)
                if not isinstance(block, bytes):
                    raise SpotifySoloistInstallerError("download_failed")
                if not block:
                    break
                total += len(block)
                if total > MAX_ARCHIVE_BYTES:
                    raise SpotifySoloistInstallerError("download_too_large")
                self._write_all(descriptor, block)
                digest.update(block)
            if declared_length is not None and total != declared_length:
                raise SpotifySoloistInstallerError("download_failed")
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            return _DownloadedArchive(destination, digest.hexdigest(), total)
        except SpotifySoloistInstallerError:
            raise
        except Exception:
            raise SpotifySoloistInstallerError("download_failed") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    @staticmethod
    def _write_all(descriptor: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written

    def _scan_archive(self, archive_path: str) -> int:
        names = set()
        member_count = 0
        declared_total = 0
        soloist_size = None
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                for member in archive:
                    member_count += 1
                    if member_count > MAX_ARCHIVE_MEMBERS:
                        raise SpotifySoloistInstallerError("invalid_archive")
                    self._validate_member(member, names)
                    declared_total += member.size
                    if declared_total > MAX_DECLARED_UNCOMPRESSED_BYTES:
                        raise SpotifySoloistInstallerError("invalid_archive")
                    if member.name == "soloist":
                        if soloist_size is not None:
                            raise SpotifySoloistInstallerError("invalid_archive")
                        if member.size <= 0 or member.size > MAX_EXECUTABLE_BYTES:
                            raise SpotifySoloistInstallerError("invalid_archive")
                        soloist_size = member.size
        except SpotifySoloistInstallerError:
            raise
        except (OSError, tarfile.TarError, EOFError):
            raise SpotifySoloistInstallerError("invalid_archive") from None
        if soloist_size is None:
            raise SpotifySoloistInstallerError("invalid_archive")
        return soloist_size

    @staticmethod
    def _validate_member(member: tarfile.TarInfo, names: set[str]) -> None:
        name = member.name
        if (
            not isinstance(name, str)
            or not name
            or name.startswith("/")
            or "\\" in name
            or "/" in name
            or name in (".", "..")
            or name in names
            or not member.isfile()
            or member.size < 0
        ):
            raise SpotifySoloistInstallerError("invalid_archive")
        names.add(name)

    def _extract_candidate(
        self,
        archive_path: str,
        destination: str,
        *,
        declared_size: int,
    ) -> None:
        descriptor = None
        source = None
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                member = archive.getmember("soloist")
                source = archive.extractfile(member)
                if source is None:
                    raise SpotifySoloistInstallerError("invalid_archive")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_CLOEXEC"):
                    flags |= os.O_CLOEXEC
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(destination, flags, BINARY_MODE)
                copied = 0
                while True:
                    block = source.read(EXTRACT_CHUNK_BYTES)
                    if not isinstance(block, bytes):
                        raise SpotifySoloistInstallerError("invalid_archive")
                    if not block:
                        break
                    copied += len(block)
                    if copied > declared_size or copied > MAX_EXECUTABLE_BYTES:
                        raise SpotifySoloistInstallerError("invalid_archive")
                    self._write_all(descriptor, block)
                if copied != declared_size:
                    raise SpotifySoloistInstallerError("invalid_archive")
                os.fchmod(descriptor, BINARY_MODE)
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
        except SpotifySoloistInstallerError:
            raise
        except (OSError, KeyError, tarfile.TarError, EOFError):
            raise SpotifySoloistInstallerError("invalid_archive") from None
        finally:
            if source is not None:
                source.close()
            if descriptor is not None:
                os.close(descriptor)

    def _verify_final_unchanged(self, expected: _ExistingFile) -> None:
        try:
            current = os.lstat(self._final_binary)
        except FileNotFoundError:
            if expected.exists:
                raise SpotifySoloistInstallerError("commit_failed") from None
            return
        except OSError:
            raise SpotifySoloistInstallerError("commit_failed") from None
        if (
            not expected.exists
            or not stat.S_ISREG(current.st_mode)
            or current.st_dev != expected.device
            or current.st_ino != expected.inode
        ):
            raise SpotifySoloistInstallerError("commit_failed")

    def _verify_committed_file(self) -> None:
        try:
            info = os.lstat(self._final_binary)
        except OSError:
            raise SpotifySoloistInstallerError("commit_failed") from None
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != BINARY_MODE
        ):
            raise SpotifySoloistInstallerError("commit_failed")

    def _fsync_install_directory(self) -> None:
        descriptor = None
        try:
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            descriptor = os.open(self._install_dir, flags)
            os.fsync(descriptor)
        except OSError:
            if descriptor is not None:
                os.close(descriptor)
            raise SpotifySoloistInstallerError("commit_failed") from None
        os.close(descriptor)

    def _remove_staging(self, staging_dir: str) -> None:
        expected_parent = os.path.realpath(self._install_dir)
        if os.path.dirname(os.path.realpath(staging_dir)) != expected_parent:
            return
        try:
            shutil.rmtree(staging_dir)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    @staticmethod
    def _remove_check_staging(staging_dir: str) -> None:
        if not os.path.basename(staging_dir).startswith(
            ".srova-soloist-check-"
        ):
            return
        try:
            shutil.rmtree(staging_dir)
        except (FileNotFoundError, OSError):
            pass

    @staticmethod
    def _update_check_failure(
        *,
        installed: bool,
    ) -> SpotifySoloistUpdateCheckResult:
        return SpotifySoloistUpdateCheckResult(
            ok=False,
            installed=installed,
            update_available=False,
            error_code="check_failed",
        )

    @staticmethod
    def _failure(
        code: str,
        *,
        archive_sha256: Optional[str],
    ) -> SpotifySoloistInstallResult:
        allowed = {
            "unsupported_architecture",
            "unsafe_install_directory",
            "download_failed",
            "unexpected_response",
            "download_too_large",
            "invalid_archive",
            "invalid_candidate",
            "candidate_expired",
            "downgrade_rejected",
            "same_build_conflict",
            "commit_failed",
        }
        safe_code = code if code in allowed else "invalid_candidate"
        return SpotifySoloistInstallResult(
            success=False,
            changed=False,
            action="unchanged",
            version=None,
            build_timestamp=None,
            architecture=None,
            binary_sha256=None,
            archive_sha256=archive_sha256,
            error_code=safe_code,
        )


__all__ = [
    "BINARY_MODE",
    "DOWNLOAD_CHUNK_BYTES",
    "INSTALL_DIRECTORY_MODE",
    "MAX_ARCHIVE_BYTES",
    "MAX_ARCHIVE_MEMBERS",
    "MAX_DECLARED_UNCOMPRESSED_BYTES",
    "MAX_EXECUTABLE_BYTES",
    "OFFICIAL_DOWNLOAD_HOST",
    "SpotifySoloistInstallResult",
    "SpotifySoloistInstaller",
    "SpotifySoloistInstallerError",
    "SpotifySoloistUpdateCheckResult",
]
