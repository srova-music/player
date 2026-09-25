import dataclasses
import hashlib
import importlib.util
import inspect
import io
import os
import stat
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.spotify_paths import SpotifyPaths  # noqa: E402
from services.spotify_soloist_artifact import (  # noqa: E402
    SpotifySoloistArtifactAuthority,
)
from services import spotify_soloist_installer as installer_module  # noqa: E402
from services.spotify_soloist_installer import (  # noqa: E402
    BINARY_MODE,
    DOWNLOAD_CHUNK_BYTES,
    INSTALL_DIRECTORY_MODE,
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_MEMBERS,
    MAX_DECLARED_UNCOMPRESSED_BYTES,
    MAX_EXECUTABLE_BYTES,
    SpotifySoloistInstaller,
    SpotifySoloistInstallerError,
)


CURRENT_OUTPUT = (
    "soloist 1.3.8.43 build 1789538504 (20260916) "
    "(g5c3a2053ac) (linux/x86_64)"
)
OLDER_OUTPUT = (
    "soloist 1.3.8.42 build 1789452104 (20260915) "
    "(goldbuild0001) (linux/x86_64)"
)
NEWER_OUTPUT = (
    "soloist 1.3.8.44 build 1789624904 (20260917) "
    "(gnewbuild0001) (linux/x86_64)"
)
EXPIRED_OUTPUT = (
    "soloist 1.3.7.1 build 1777593600 (20260501) "
    "(gexpired0001) (linux/x86_64)"
)
VALID_NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


def _paths(tmp_path):
    return SpotifyPaths(
        spotify_state_dir=str(tmp_path / "state"),
        spotify_cache_dir=str(tmp_path / "cache"),
        spotify_runtime_dir=str(tmp_path / "run"),
        soloist_install_dir=str(tmp_path / "state/soloist/install"),
        soloist_data_dir=str(tmp_path / "state/soloist/data"),
        soloist_cache_dir=str(tmp_path / "cache/soloist"),
    )


def _elf_bytes(architecture="x86_64", *, suffix=b"candidate"):
    contracts = {
        "x86_64": (2, 62, 64),
        "aarch64": (2, 183, 64),
        "armv7l": (1, 40, 52),
    }
    elf_class, machine, size = contracts[architecture]
    header = bytearray(size)
    header[:4] = b"\x7fELF"
    header[4] = elf_class
    header[5] = 1
    header[6] = 1
    header[18:20] = machine.to_bytes(2, "little")
    return bytes(header) + suffix


def _tar_bytes(members=None, *, soloist_bytes=None):
    if members is None:
        members = [
            ("CHANGELOG.md", b"synthetic changelog", tarfile.REGTYPE, None),
            ("THIRD_PARTY_LICENSES.txt", b"synthetic licenses", tarfile.REGTYPE, None),
            (
                "soloist",
                _elf_bytes() if soloist_bytes is None else soloist_bytes,
                tarfile.REGTYPE,
                None,
            ),
        ]
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, payload, member_type, linkname in members:
            info = tarfile.TarInfo(name)
            info.type = member_type
            info.linkname = linkname or ""
            info.mode = 0o777
            info.size = len(payload) if member_type == tarfile.REGTYPE else 0
            archive.addfile(info, io.BytesIO(payload) if info.size else None)
    return output.getvalue()


class FakeResponse:
    def __init__(
        self,
        body,
        *,
        url=None,
        status=200,
        content_length=True,
    ):
        self._body = io.BytesIO(body)
        self._url = url
        self.status = status
        self.headers = {}
        if content_length is True:
            self.headers["Content-Length"] = str(len(body))
        elif content_length not in (False, None):
            self.headers["Content-Length"] = str(content_length)
        self.read_sizes = []
        self.closed = False

    def geturl(self):
        return self._url

    def read(self, size):
        self.read_sizes.append(size)
        return self._body.read(size)

    def close(self):
        self.closed = True


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, request, **kwargs):
        self.calls.append((request, kwargs))
        if self.error is not None:
            raise self.error
        if self.response._url is None:
            self.response._url = request.full_url
        return self.response


class VersionRunner:
    def __init__(self, *, existing=CURRENT_OUTPUT, candidate=CURRENT_OUTPUT):
        self.existing = existing
        self.candidate = candidate
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        selected = (
            self.candidate
            if ".srova-soloist-" in argv[0]
            else self.existing
        )
        return subprocess.CompletedProcess(
            argv,
            0,
            selected.encode("ascii"),
            b"",
        )


def _installer(tmp_path, archive=None, *, runner=None, response=None):
    paths = _paths(tmp_path)
    url = SpotifySoloistArtifactAuthority(
        paths=paths,
        host_architecture="x86_64",
        command_runner=runner or VersionRunner(),
    ).official_archive_url()
    archive = _tar_bytes() if archive is None else archive
    response = response or FakeResponse(archive, url=url)
    opener = FakeOpener(response=response)
    installer = SpotifySoloistInstaller(
        paths=paths,
        host_architecture="x86_64",
        command_runner=runner or VersionRunner(),
        url_opener=opener,
    )
    return installer, paths, opener, archive


def _write_existing(paths, payload=None):
    path = Path(paths.soloist_install_dir) / "soloist"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_elf_bytes(suffix=b"existing") if payload is None else payload)
    path.chmod(BINARY_MODE)
    return path


def _staging_entries(paths):
    install = Path(paths.soloist_install_dir)
    if not install.exists():
        return []
    return [path for path in install.iterdir() if path.name.startswith(".srova-")]


def test_import_is_side_effect_free(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("side effect during import")

    monkeypatch.setattr(installer_module.urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(installer_module.os, "makedirs", forbidden)
    monkeypatch.setattr(installer_module.os, "replace", forbidden)
    module_name = "services.spotify_soloist_installer_import_probe"
    spec = importlib.util.spec_from_file_location(
        module_name,
        SRC / "services/spotify_soloist_installer.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)


def test_constructor_is_side_effect_free(tmp_path):
    paths = _paths(tmp_path)
    opener = mock.Mock(side_effect=AssertionError("network used"))
    runner = mock.Mock(side_effect=AssertionError("binary executed"))
    SpotifySoloistInstaller(
        paths=paths,
        host_architecture="x86_64",
        command_runner=runner,
        url_opener=opener,
    )
    assert not Path(paths.soloist_install_dir).exists()
    opener.assert_not_called()
    runner.assert_not_called()


def test_official_url_comes_from_locked_artifact_authority(tmp_path, monkeypatch):
    expected = "https://soloist-builds.spotifycdn.com/soloist_release_x86_64.tar.gz"
    called = []
    original = SpotifySoloistArtifactAuthority.official_archive_url

    def record(authority):
        called.append(True)
        return original(authority)

    monkeypatch.setattr(
        SpotifySoloistArtifactAuthority,
        "official_archive_url",
        record,
    )
    installer, _paths_value, opener, _archive = _installer(tmp_path)
    result = installer.install_or_update(now=VALID_NOW)
    assert result.success is True
    assert called
    assert opener.calls[0][0].full_url == expected


def test_arbitrary_url_is_not_a_constructor_or_operation_parameter():
    constructor = inspect.signature(SpotifySoloistInstaller).parameters
    operation = inspect.signature(
        SpotifySoloistInstaller.install_or_update
    ).parameters
    assert "url" not in constructor
    assert "url" not in operation


@pytest.mark.parametrize(
    "url",
    [
        "http://soloist-builds.spotifycdn.com/archive.tar.gz",
        "https://example.com/archive.tar.gz",
        "https://user@soloist-builds.spotifycdn.com/archive.tar.gz",
        "https://soloist-builds.spotifycdn.com/archive.tar.gz?token=secret",
        "https://soloist-builds.spotifycdn.com/archive.tar.gz#fragment",
    ],
)
def test_https_and_official_host_authority(url):
    with pytest.raises(SpotifySoloistInstallerError) as error:
        SpotifySoloistInstaller._validate_official_url(url)
    assert error.value.code == "unexpected_response"


def test_redirect_or_final_url_mismatch_is_rejected_before_body(tmp_path):
    archive = _tar_bytes()
    response = FakeResponse(archive, url="https://example.com/redirected.tar.gz")
    installer, _paths_value, _opener, _archive = _installer(
        tmp_path,
        archive,
        response=response,
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "unexpected_response"
    assert response.read_sizes == []


def test_non_200_response_is_rejected_before_body(tmp_path):
    response = FakeResponse(_tar_bytes(), status=206)
    installer, _paths_value, _opener, _archive = _installer(
        tmp_path,
        response=response,
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "unexpected_response"
    assert response.read_sizes == []


def test_content_length_over_limit_rejected_before_body(tmp_path):
    response = FakeResponse(b"small", content_length=MAX_ARCHIVE_BYTES + 1)
    installer, _paths_value, _opener, _archive = _installer(
        tmp_path,
        response=response,
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "download_too_large"
    assert response.read_sizes == []


def test_streamed_body_over_limit_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(installer_module, "MAX_ARCHIVE_BYTES", 64)
    response = FakeResponse(b"x" * 65, content_length=False)
    installer, _paths_value, _opener, _archive = _installer(
        tmp_path,
        response=response,
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "download_too_large"
    assert response.read_sizes


def test_archive_sha_is_calculated_while_streaming(tmp_path):
    installer, _paths_value, _opener, archive = _installer(tmp_path)
    result = installer.install_or_update(now=VALID_NOW)
    assert result.archive_sha256 == hashlib.sha256(archive).hexdigest()


def test_download_api_uses_bounded_stream_reads(tmp_path):
    installer, _paths_value, opener, _archive = _installer(tmp_path)
    result = installer.install_or_update(now=VALID_NOW)
    assert result.success is True
    sizes = opener.response.read_sizes
    assert len(sizes) >= 2
    assert set(sizes) == {DOWNLOAD_CHUNK_BYTES}


def test_valid_minimal_archive_is_accepted(tmp_path):
    archive = _tar_bytes(
        [("soloist", _elf_bytes(), tarfile.REGTYPE, None)]
    )
    installer, paths, _opener, _archive = _installer(tmp_path, archive)
    result = installer.install_or_update(now=VALID_NOW)
    assert result.success is True
    assert result.action == "installed"
    assert Path(paths.soloist_install_dir, "soloist").is_file()


def test_missing_soloist_member_is_rejected(tmp_path):
    archive = _tar_bytes(
        [("README", b"documentation", tarfile.REGTYPE, None)]
    )
    installer, _paths_value, _opener, _archive = _installer(tmp_path, archive)
    assert installer.install_or_update(now=VALID_NOW).error_code == "invalid_archive"


def test_duplicate_soloist_member_is_rejected(tmp_path):
    archive = _tar_bytes(
        [
            ("soloist", _elf_bytes(), tarfile.REGTYPE, None),
            ("soloist", _elf_bytes(), tarfile.REGTYPE, None),
        ]
    )
    installer, _paths_value, _opener, _archive = _installer(tmp_path, archive)
    assert installer.install_or_update(now=VALID_NOW).error_code == "invalid_archive"


@pytest.mark.parametrize(
    "name",
    ["/soloist", "../soloist", "nested/../../soloist", "nested/soloist", "..\\soloist"],
)
def test_unsafe_or_non_top_level_member_path_is_rejected(tmp_path, name):
    archive = _tar_bytes(
        [(name, _elf_bytes(), tarfile.REGTYPE, None)]
    )
    installer, _paths_value, _opener, _archive = _installer(tmp_path, archive)
    assert installer.install_or_update(now=VALID_NOW).error_code == "invalid_archive"


@pytest.mark.parametrize(
    "member_type",
    [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE],
)
def test_link_device_and_fifo_members_are_rejected(tmp_path, member_type):
    members = [
        ("unsafe", b"", member_type, "soloist"),
        ("soloist", _elf_bytes(), tarfile.REGTYPE, None),
    ]
    installer, _paths_value, _opener, _archive = _installer(
        tmp_path,
        _tar_bytes(members),
    )
    assert installer.install_or_update(now=VALID_NOW).error_code == "invalid_archive"


def test_excessive_member_count_is_rejected(tmp_path):
    members = [
        (f"doc-{index}", b"", tarfile.REGTYPE, None)
        for index in range(MAX_ARCHIVE_MEMBERS)
    ]
    members.append(("soloist", _elf_bytes(), tarfile.REGTYPE, None))
    installer, _paths_value, _opener, _archive = _installer(
        tmp_path,
        _tar_bytes(members),
    )
    assert installer.install_or_update(now=VALID_NOW).error_code == "invalid_archive"


class _FakeTar:
    def __init__(self, members, source=None):
        self.members = members
        self.source = source

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self.members)

    def getmember(self, name):
        return next(member for member in self.members if member.name == name)

    def extractfile(self, _member):
        return self.source


def _regular_member(name, size):
    member = tarfile.TarInfo(name)
    member.size = size
    member.type = tarfile.REGTYPE
    return member


def test_total_declared_uncompressed_size_cap(tmp_path, monkeypatch):
    members = [
        _regular_member("doc", MAX_DECLARED_UNCOMPRESSED_BYTES),
        _regular_member("soloist", 1),
    ]
    installer, _paths_value, _opener, _archive = _installer(tmp_path)
    monkeypatch.setattr(
        installer_module.tarfile,
        "open",
        lambda *_args, **_kwargs: _FakeTar(members),
    )
    with pytest.raises(SpotifySoloistInstallerError, match="failed") as error:
        installer._scan_archive("synthetic")
    assert error.value.code == "invalid_archive"


def test_soloist_member_size_cap(tmp_path, monkeypatch):
    members = [_regular_member("soloist", MAX_EXECUTABLE_BYTES + 1)]
    installer, _paths_value, _opener, _archive = _installer(tmp_path)
    monkeypatch.setattr(
        installer_module.tarfile,
        "open",
        lambda *_args, **_kwargs: _FakeTar(members),
    )
    with pytest.raises(SpotifySoloistInstallerError) as error:
        installer._scan_archive("synthetic")
    assert error.value.code == "invalid_archive"


def test_only_soloist_is_extracted_and_docs_are_ignored(tmp_path):
    installer, paths, _opener, archive = _installer(tmp_path)
    install = Path(paths.soloist_install_dir)
    install.mkdir(parents=True)
    archive_path = install / "archive.tar.gz"
    archive_path.write_bytes(archive)
    size = installer._scan_archive(str(archive_path))
    destination = install / "soloist"
    installer._extract_candidate(
        str(archive_path),
        str(destination),
        declared_size=size,
    )
    assert destination.is_file()
    assert not (install / "CHANGELOG.md").exists()
    assert not (install / "THIRD_PARTY_LICENSES.txt").exists()


def test_candidate_has_controlled_mode_and_exact_size(tmp_path):
    installer, paths, _opener, archive = _installer(tmp_path)
    result = installer.install_or_update(now=VALID_NOW)
    binary = Path(paths.soloist_install_dir) / "soloist"
    assert result.success is True
    assert stat.S_IMODE(binary.stat().st_mode) == BINARY_MODE
    assert binary.read_bytes() == _elf_bytes()


def test_candidate_short_copy_is_rejected(tmp_path, monkeypatch):
    member = _regular_member("soloist", 10)
    fake = _FakeTar([member], source=io.BytesIO(b"short"))
    installer, paths, _opener, _archive = _installer(tmp_path)
    monkeypatch.setattr(
        installer_module.tarfile,
        "open",
        lambda *_args, **_kwargs: fake,
    )
    Path(paths.soloist_install_dir).mkdir(parents=True)
    with pytest.raises(SpotifySoloistInstallerError) as error:
        installer._extract_candidate(
            "synthetic",
            str(Path(paths.soloist_install_dir) / "candidate"),
            declared_size=10,
        )
    assert error.value.code == "invalid_archive"


def test_staged_candidate_is_validated_through_locked_authority(tmp_path):
    runner = VersionRunner()
    installer, _paths_value, _opener, _archive = _installer(
        tmp_path,
        runner=runner,
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.success is True
    candidate_calls = [
        argv for argv, _kwargs in runner.calls
        if ".srova-soloist-install-" in argv[0]
    ]
    assert len(candidate_calls) == 1
    assert candidate_calls[0][1:] == ["--version"]


def test_update_check_not_installed_is_network_free(tmp_path):
    paths = _paths(tmp_path)
    opener = mock.Mock(side_effect=AssertionError("network used"))
    installer = SpotifySoloistInstaller(
        paths=paths,
        host_architecture="x86_64",
        command_runner=VersionRunner(),
        url_opener=opener,
    )

    result = installer.check_for_update(now=VALID_NOW)

    assert result.ok is True
    assert result.installed is False
    assert result.update_available is False
    assert result.error_code == "not_installed"
    opener.assert_not_called()


def test_update_check_damaged_installed_artifact_fails_closed_without_network(
    tmp_path,
):
    paths = _paths(tmp_path)
    _write_existing(paths, b"not-an-elf")
    opener = mock.Mock(side_effect=AssertionError("network used"))
    installer = SpotifySoloistInstaller(
        paths=paths,
        host_architecture="x86_64",
        command_runner=VersionRunner(),
        url_opener=opener,
    )

    result = installer.check_for_update(now=VALID_NOW)

    assert result.ok is False
    assert result.installed is True
    assert result.update_available is False
    assert result.error_code == "check_failed"
    opener.assert_not_called()


@pytest.mark.parametrize(
    ("candidate_output", "candidate_bytes", "available", "ok"),
    [
        (CURRENT_OUTPUT, _elf_bytes(), False, True),
        (NEWER_OUTPUT, _elf_bytes(suffix=b"newer"), True, True),
        (OLDER_OUTPUT, _elf_bytes(suffix=b"older"), False, True),
        (CURRENT_OUTPUT, _elf_bytes(suffix=b"conflict"), False, False),
        ("malformed version", _elf_bytes(), False, False),
        (EXPIRED_OUTPUT, _elf_bytes(suffix=b"expired"), False, False),
    ],
    ids=[
        "same-build-same-hash",
        "newer",
        "older",
        "same-build-conflict",
        "invalid-candidate",
        "expired-candidate",
    ],
)
def test_update_check_comparison_is_fail_closed(
    tmp_path,
    candidate_output,
    candidate_bytes,
    available,
    ok,
):
    runner = VersionRunner(candidate=candidate_output)
    installer, paths, _opener, _archive = _installer(
        tmp_path,
        _tar_bytes(soloist_bytes=candidate_bytes),
        runner=runner,
    )
    _write_existing(paths, _elf_bytes())

    result = installer.check_for_update(now=VALID_NOW)

    assert result.ok is ok
    assert result.installed is True
    assert result.update_available is available
    assert result.error_code == (
        "update_available" if available else ("current" if ok else "check_failed")
    )


def test_update_check_is_non_mutating_and_cleans_temporary_staging(
    tmp_path,
    monkeypatch,
):
    runner = VersionRunner(candidate=NEWER_OUTPUT)
    installer, paths, _opener, _archive = _installer(
        tmp_path,
        _tar_bytes(soloist_bytes=_elf_bytes(suffix=b"newer")),
        runner=runner,
    )
    final = _write_existing(paths, _elf_bytes())
    original = final.read_bytes()
    original_mode = stat.S_IMODE(final.stat().st_mode)
    staged = tmp_path / ".srova-soloist-check-synthetic"

    def make_staging(*, prefix):
        assert prefix == ".srova-soloist-check-"
        staged.mkdir()
        return str(staged)

    monkeypatch.setattr(installer_module.tempfile, "mkdtemp", make_staging)
    replace_spy = mock.Mock(side_effect=AssertionError("managed binary replaced"))
    monkeypatch.setattr(installer_module.os, "replace", replace_spy)

    result = installer.check_for_update(now=VALID_NOW)

    assert result.update_available is True
    assert final.read_bytes() == original
    assert stat.S_IMODE(final.stat().st_mode) == original_mode
    assert not staged.exists()
    replace_spy.assert_not_called()


def test_expired_candidate_is_rejected(tmp_path):
    installer, _paths_value, _opener, _archive = _installer(tmp_path)
    result = installer.install_or_update(
        now=datetime(2027, 1, 1, tzinfo=timezone.utc)
    )
    assert result.error_code == "candidate_expired"


@pytest.mark.parametrize(
    "candidate",
    [_elf_bytes("aarch64"), b"not-an-elf"],
)
def test_wrong_architecture_or_malformed_elf_is_rejected(tmp_path, candidate):
    installer, _paths_value, _opener, _archive = _installer(
        tmp_path,
        _tar_bytes(soloist_bytes=candidate),
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "invalid_candidate"


def test_malformed_version_is_rejected(tmp_path):
    runner = VersionRunner(candidate="malformed version")
    installer, _paths_value, _opener, _archive = _installer(
        tmp_path,
        runner=runner,
    )
    assert installer.install_or_update(now=VALID_NOW).error_code == "invalid_candidate"


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_unsafe_final_object_is_rejected_without_network(tmp_path, kind):
    paths = _paths(tmp_path)
    final = Path(paths.soloist_install_dir) / "soloist"
    final.parent.mkdir(parents=True)
    if kind == "symlink":
        target = tmp_path / "outside"
        target.write_bytes(b"outside")
        final.symlink_to(target)
    else:
        final.mkdir()
    opener = mock.Mock(side_effect=AssertionError("network used"))
    installer = SpotifySoloistInstaller(
        paths=paths,
        host_architecture="x86_64",
        command_runner=VersionRunner(),
        url_opener=opener,
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "unsafe_install_directory"
    opener.assert_not_called()


def test_install_directory_symlink_is_rejected(tmp_path):
    paths = _paths(tmp_path)
    target = tmp_path / "outside-install"
    target.mkdir()
    install = Path(paths.soloist_install_dir)
    install.parent.mkdir(parents=True)
    install.symlink_to(target, target_is_directory=True)
    opener = mock.Mock(side_effect=AssertionError("network used"))
    installer = SpotifySoloistInstaller(
        paths=paths,
        host_architecture="x86_64",
        command_runner=VersionRunner(),
        url_opener=opener,
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "unsafe_install_directory"
    opener.assert_not_called()


def test_absent_install_succeeds_with_private_install_directory(tmp_path):
    installer, paths, _opener, _archive = _installer(tmp_path)
    result = installer.install_or_update(now=VALID_NOW)
    assert result.success is True
    assert result.changed is True
    assert result.action == "installed"
    assert stat.S_IMODE(Path(paths.soloist_install_dir).stat().st_mode) == (
        INSTALL_DIRECTORY_MODE
    )


def test_unsupported_architecture_returns_controlled_result(tmp_path):
    paths = _paths(tmp_path)
    opener = mock.Mock(side_effect=AssertionError("network used"))
    installer = SpotifySoloistInstaller(
        paths=paths,
        host_architecture="riscv64",
        command_runner=VersionRunner(),
        url_opener=opener,
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "unsupported_architecture"
    opener.assert_not_called()


def test_invalid_regular_existing_binary_is_repaired(tmp_path):
    installer, paths, _opener, _archive = _installer(tmp_path)
    existing = _write_existing(paths, b"invalid existing binary")
    result = installer.install_or_update(now=VALID_NOW)
    assert result.success is True
    assert result.action == "updated"
    assert existing.read_bytes() == _elf_bytes()


def test_expired_regular_existing_binary_is_repaired_by_newer_build(tmp_path):
    runner = VersionRunner(existing=OLDER_OUTPUT, candidate=CURRENT_OUTPUT)
    installer, paths, _opener, _archive = _installer(tmp_path, runner=runner)
    existing = _write_existing(paths)
    result = installer.install_or_update(
        now=datetime(2026, 12, 14, 7, tzinfo=timezone.utc)
    )
    assert result.success is True
    assert result.action == "updated"
    assert existing.read_bytes() == _elf_bytes()


def test_valid_older_existing_is_updated_by_newer_candidate(tmp_path):
    runner = VersionRunner(existing=OLDER_OUTPUT, candidate=NEWER_OUTPUT)
    installer, paths, _opener, archive = _installer(tmp_path, runner=runner)
    existing = _write_existing(paths)
    old_hash = hashlib.sha256(existing.read_bytes()).hexdigest()
    result = installer.install_or_update(now=VALID_NOW)
    assert result.success is True
    assert result.action == "updated"
    assert result.binary_sha256 != old_hash
    assert existing.read_bytes() == _elf_bytes()


def test_older_candidate_is_rejected_as_downgrade(tmp_path):
    runner = VersionRunner(existing=CURRENT_OUTPUT, candidate=OLDER_OUTPUT)
    installer, paths, _opener, _archive = _installer(tmp_path, runner=runner)
    existing = _write_existing(paths)
    before = existing.read_bytes()
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "downgrade_rejected"
    assert existing.read_bytes() == before


def test_same_build_and_same_hash_is_successful_noop(tmp_path):
    candidate = _elf_bytes()
    installer, paths, _opener, _archive = _installer(
        tmp_path,
        _tar_bytes(soloist_bytes=candidate),
    )
    existing = _write_existing(paths, candidate)
    before_inode = existing.stat().st_ino
    result = installer.install_or_update(now=VALID_NOW)
    assert result.success is True
    assert result.changed is False
    assert result.action == "unchanged"
    assert existing.stat().st_ino == before_inode


def test_same_build_with_different_hash_fails_closed(tmp_path):
    installer, paths, _opener, _archive = _installer(tmp_path)
    existing = _write_existing(paths, _elf_bytes(suffix=b"different"))
    before = existing.read_bytes()
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "same_build_conflict"
    assert existing.read_bytes() == before


def test_failed_download_preserves_existing_hash(tmp_path):
    paths = _paths(tmp_path)
    existing = _write_existing(paths)
    before = hashlib.sha256(existing.read_bytes()).hexdigest()
    opener = FakeOpener(error=OSError("synthetic network failure"))
    installer = SpotifySoloistInstaller(
        paths=paths,
        host_architecture="x86_64",
        command_runner=VersionRunner(),
        url_opener=opener,
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "download_failed"
    assert hashlib.sha256(existing.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "archive",
    [b"not a tar", _tar_bytes(soloist_bytes=b"invalid candidate")],
)
def test_archive_or_candidate_failure_preserves_existing(tmp_path, archive):
    installer, paths, _opener, _archive = _installer(tmp_path, archive)
    existing = _write_existing(paths)
    before = existing.read_bytes()
    result = installer.install_or_update(now=VALID_NOW)
    assert result.success is False
    assert existing.read_bytes() == before


def test_replace_failure_preserves_existing_binary(tmp_path, monkeypatch):
    runner = VersionRunner(existing=OLDER_OUTPUT, candidate=NEWER_OUTPUT)
    installer, paths, _opener, _archive = _installer(tmp_path, runner=runner)
    existing = _write_existing(paths)
    before = existing.read_bytes()
    monkeypatch.setattr(
        installer_module.os,
        "replace",
        mock.Mock(side_effect=OSError("synthetic replace failure")),
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.error_code == "commit_failed"
    assert existing.read_bytes() == before


def test_replacement_source_is_staged_on_install_filesystem(tmp_path, monkeypatch):
    installer, paths, _opener, _archive = _installer(tmp_path)
    real_replace = os.replace
    calls = []

    def record(source, destination):
        calls.append((source, destination))
        return real_replace(source, destination)

    monkeypatch.setattr(installer_module.os, "replace", record)
    assert installer.install_or_update(now=VALID_NOW).success is True
    source, destination = calls[0]
    assert os.path.commonpath([source, paths.soloist_install_dir]) == (
        paths.soloist_install_dir
    )
    assert destination == str(Path(paths.soloist_install_dir) / "soloist")


def test_successful_commit_has_expected_binary_hash(tmp_path):
    candidate = _elf_bytes(suffix=b"expected")
    installer, paths, _opener, _archive = _installer(
        tmp_path,
        _tar_bytes(soloist_bytes=candidate),
    )
    result = installer.install_or_update(now=VALID_NOW)
    final = Path(paths.soloist_install_dir) / "soloist"
    assert result.success is True
    assert hashlib.sha256(final.read_bytes()).hexdigest() == result.binary_sha256


def test_staging_residue_removed_on_success(tmp_path):
    installer, paths, _opener, _archive = _installer(tmp_path)
    assert installer.install_or_update(now=VALID_NOW).success is True
    assert _staging_entries(paths) == []


def test_staging_residue_removed_on_precommit_failure(tmp_path):
    installer, paths, _opener, _archive = _installer(tmp_path, b"invalid tar")
    assert installer.install_or_update(now=VALID_NOW).success is False
    assert _staging_entries(paths) == []


def test_cleanup_failure_after_commit_does_not_reverse_success(
    tmp_path,
    monkeypatch,
):
    installer, paths, _opener, _archive = _installer(tmp_path)
    monkeypatch.setattr(
        installer,
        "_remove_staging",
        mock.Mock(side_effect=OSError("synthetic cleanup failure")),
    )
    result = installer.install_or_update(now=VALID_NOW)
    assert result.success is True
    assert result.changed is True
    assert Path(paths.soloist_install_dir, "soloist").is_file()


def test_data_cache_and_runtime_directories_are_not_mutated(tmp_path):
    installer, paths, _opener, _archive = _installer(tmp_path)
    protected = [
        Path(paths.soloist_data_dir),
        Path(paths.soloist_cache_dir),
        Path(paths.spotify_runtime_dir),
    ]
    for directory in protected:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "marker").write_text("unchanged", encoding="utf-8")
    assert installer.install_or_update(now=VALID_NOW).success is True
    for directory in protected:
        assert (directory / "marker").read_text(encoding="utf-8") == "unchanged"


def test_request_has_no_credentials_authorization_cookies_or_query(tmp_path):
    installer, _paths_value, opener, _archive = _installer(tmp_path)
    assert installer.install_or_update(now=VALID_NOW).success is True
    request = opener.calls[0][0]
    headers = {name.lower(): value for name, value in request.header_items()}
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert request.full_url.startswith("https://soloist-builds.spotifycdn.com/")
    assert "?" not in request.full_url


def test_no_real_network_when_transport_is_injected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        installer_module.urllib.request,
        "build_opener",
        mock.Mock(side_effect=AssertionError("real transport constructed")),
    )
    installer, _paths_value, _opener, _archive = _installer(tmp_path)
    assert installer.install_or_update(now=VALID_NOW).success is True


def test_source_has_no_secret_root_shell_or_unsafe_extraction_code():
    source = (SRC / "services/spotify_soloist_installer.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "spotifysecretstore",
        "api_key",
        "authorization",
        "sudo",
        "shell=true",
        "subprocess.popen",
        "curl",
        "wget",
        "extractall",
        "/tmp",
        "/opt",
        "/usr/local/bin",
        "srova-sp1",
    )
    assert not any(item in lowered for item in forbidden)


def test_result_contract_is_frozen_and_sanitized(tmp_path):
    response = FakeResponse(b"failure", status=500)
    installer, _paths_value, _opener, _archive = _installer(
        tmp_path,
        response=response,
    )
    result = installer.install_or_update(now=VALID_NOW)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.success = True
    rendered = repr(result).lower()
    assert str(tmp_path) not in rendered
    assert "secret" not in rendered
