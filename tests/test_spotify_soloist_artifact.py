import dataclasses
import hashlib
import importlib.util
import inspect
import os
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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
    SpotifySoloistArtifactError,
    SpotifySoloistArtifactStatusCode,
    evaluate_soloist_expiry,
    inspect_soloist_elf,
    normalize_spotify_architecture,
    official_soloist_archive_url,
    parse_soloist_version,
)


SAMPLE = (
    "soloist 1.3.8.43 build 1789538504 (20260916) "
    "(g5c3a2053ac) (linux/x86_64)"
)
BUILD_NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


def _paths(tmp_path):
    return SpotifyPaths(
        spotify_state_dir=str(tmp_path / "state"),
        spotify_cache_dir=str(tmp_path / "cache"),
        spotify_runtime_dir=str(tmp_path / "run"),
        soloist_install_dir=str(tmp_path / "state/soloist/install"),
        soloist_data_dir=str(tmp_path / "state/soloist/data"),
        soloist_cache_dir=str(tmp_path / "cache/soloist"),
    )


def _elf_bytes(architecture, *, machine=None, elf_class=None, endian=1):
    contracts = {
        "x86_64": (2, 62, 64),
        "aarch64": (2, 183, 64),
        "armv7l": (1, 40, 52),
    }
    expected_class, expected_machine, size = contracts[architecture]
    header = bytearray(size)
    header[:4] = b"\x7fELF"
    header[4] = expected_class if elf_class is None else elf_class
    header[5] = endian
    header[6] = 1
    selected_machine = expected_machine if machine is None else machine
    header[18:20] = selected_machine.to_bytes(2, "little")
    return bytes(header) + b"synthetic-elf-payload"


def _write_elf(path, architecture="x86_64", **kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_elf_bytes(architecture, **kwargs))
    path.chmod(0o700)
    return path


class RecordingRunner:
    def __init__(self, *, stdout=SAMPLE.encode("ascii"), stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(
            argv,
            self.returncode,
            self.stdout,
            self.stderr,
        )


def _installed_authority(tmp_path, *, runner=None, architecture="x86_64"):
    paths = _paths(tmp_path)
    binary = _write_elf(Path(paths.soloist_install_dir) / "soloist", architecture)
    authority = SpotifySoloistArtifactAuthority(
        paths=paths,
        host_architecture=architecture,
        command_runner=runner or RecordingRunner(),
    )
    return authority, binary


def test_import_is_side_effect_free(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("side effect during module import")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "makedirs", forbidden)
    monkeypatch.setattr(os, "mkdir", forbidden)
    monkeypatch.setattr(os, "chmod", forbidden)
    module_name = "services.spotify_soloist_artifact_import_probe"
    spec = importlib.util.spec_from_file_location(
        module_name,
        SRC / "services/spotify_soloist_artifact.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)


def test_construction_is_side_effect_free(tmp_path):
    paths = _paths(tmp_path)
    runner = mock.Mock(side_effect=AssertionError("runner invoked"))
    authority = SpotifySoloistArtifactAuthority(
        paths=paths,
        host_architecture="x86_64",
        command_runner=runner,
    )
    assert authority.canonical_architecture == "x86_64"
    assert not Path(paths.soloist_install_dir).exists()
    runner.assert_not_called()


@pytest.mark.parametrize(
    ("supplied", "canonical"),
    [
        ("x86_64", "x86_64"),
        ("amd64", "x86_64"),
        ("aarch64", "aarch64"),
        ("arm64", "aarch64"),
        ("armv7l", "armv7l"),
    ],
)
def test_architecture_normalization(supplied, canonical):
    assert normalize_spotify_architecture(supplied) == canonical


@pytest.mark.parametrize("architecture", ["i686", "armv8", "armhf", "", None])
def test_unknown_architecture_is_rejected(architecture):
    with pytest.raises(SpotifySoloistArtifactError):
        normalize_spotify_architecture(architecture)


@pytest.mark.parametrize(
    ("architecture", "expected"),
    [
        (
            "x86_64",
            "https://soloist-builds.spotifycdn.com/soloist_release_x86_64.tar.gz",
        ),
        (
            "aarch64",
            "https://soloist-builds.spotifycdn.com/soloist_release_arm64.tar.gz",
        ),
        (
            "armv7l",
            "https://soloist-builds.spotifycdn.com/soloist_release_arm32.tar.gz",
        ),
    ],
)
def test_official_url_is_constant_controlled(architecture, expected):
    assert official_soloist_archive_url(architecture) == expected


def test_arbitrary_url_cannot_be_supplied():
    assert tuple(inspect.signature(official_soloist_archive_url).parameters) == (
        "architecture",
    )
    with pytest.raises(TypeError):
        official_soloist_archive_url("x86_64", "https://example.invalid")


def test_current_observed_version_form_parses():
    build = parse_soloist_version(SAMPLE + "\n")
    assert build.version == "1.3.8.43"
    assert build.build_timestamp == 1789538504
    assert build.build_date_token == "20260916"
    assert build.build_identifier == "g5c3a2053ac"
    assert build.platform == "linux"
    assert build.architecture == "x86_64"
    assert build.build_datetime_utc == datetime(
        2026, 9, 16, 6, 1, 44, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    "output",
    [
        "garbage",
        "soloist 1.2 build",
        SAMPLE.replace("soloist", "other", 1),
        SAMPLE + " unexpected",
        SAMPLE.replace("g5c3a2053ac", "bad identifier"),
    ],
)
def test_malformed_version_fails_closed(output):
    with pytest.raises(SpotifySoloistArtifactError):
        parse_soloist_version(output)


def test_unexpected_non_whitespace_second_line_fails():
    with pytest.raises(SpotifySoloistArtifactError):
        parse_soloist_version(SAMPLE + "\nsecond line")


@pytest.mark.parametrize("timestamp", ["0", "-1"])
def test_zero_or_negative_build_timestamp_fails(timestamp):
    output = SAMPLE.replace("1789538504", timestamp)
    with pytest.raises(SpotifySoloistArtifactError):
        parse_soloist_version(output)


@pytest.mark.parametrize("date_token", ["20261301", "20260230", "2026916"])
def test_invalid_date_token_fails(date_token):
    with pytest.raises(SpotifySoloistArtifactError):
        parse_soloist_version(SAMPLE.replace("20260916", date_token))


def test_timestamp_and_date_mismatch_fails():
    with pytest.raises(SpotifySoloistArtifactError, match="does not match"):
        parse_soloist_version(SAMPLE.replace("20260916", "20260917"))


def test_non_linux_platform_fails():
    with pytest.raises(SpotifySoloistArtifactError):
        parse_soloist_version(SAMPLE.replace("linux/", "darwin/"))


def test_unknown_reported_architecture_fails():
    with pytest.raises(SpotifySoloistArtifactError):
        parse_soloist_version(SAMPLE.replace("x86_64", "riscv64"))


def test_expiry_is_exactly_90_days():
    build = parse_soloist_version(SAMPLE)
    assert build.expires_at_utc - build.build_datetime_utc == timedelta(days=90)


def test_not_expired_calculation_is_deterministic():
    build = parse_soloist_version(SAMPLE)
    expires, expired, remaining = evaluate_soloist_expiry(build, now=BUILD_NOW)
    assert expired is False
    assert remaining == int((expires - BUILD_NOW).total_seconds())


def test_expired_calculation_is_deterministic():
    build = parse_soloist_version(SAMPLE)
    expires, expired, remaining = evaluate_soloist_expiry(
        build,
        now=build.expires_at_utc + timedelta(seconds=1),
    )
    assert expires == build.expires_at_utc
    assert expired is True
    assert remaining == 0


@pytest.mark.parametrize("architecture", ["x86_64", "aarch64", "armv7l"])
def test_valid_synthetic_elf_is_accepted(tmp_path, architecture):
    binary = _write_elf(tmp_path / architecture, architecture)
    assert inspect_soloist_elf(binary, architecture) == architecture


@pytest.mark.parametrize(
    ("architecture", "wrong_machine"),
    [("x86_64", 183), ("aarch64", 62)],
)
def test_wrong_elf_machine_is_rejected(tmp_path, architecture, wrong_machine):
    binary = _write_elf(
        tmp_path / architecture,
        architecture,
        machine=wrong_machine,
    )
    with pytest.raises(SpotifySoloistArtifactError):
        inspect_soloist_elf(binary, architecture)


def test_wrong_armv7_elf_class_is_rejected(tmp_path):
    binary = _write_elf(tmp_path / "armv7", "armv7l", elf_class=2)
    with pytest.raises(SpotifySoloistArtifactError):
        inspect_soloist_elf(binary, "armv7l")


def test_big_endian_elf_is_rejected(tmp_path):
    binary = _write_elf(tmp_path / "big-endian", "x86_64", endian=2)
    with pytest.raises(SpotifySoloistArtifactError):
        inspect_soloist_elf(binary, "x86_64")


def test_symlink_elf_is_rejected(tmp_path):
    target = _write_elf(tmp_path / "target", "x86_64")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(SpotifySoloistArtifactError):
        inspect_soloist_elf(link, "x86_64")


def test_non_regular_elf_is_rejected(tmp_path):
    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(SpotifySoloistArtifactError):
        inspect_soloist_elf(directory, "x86_64")


@pytest.mark.parametrize("payload", [b"", b"\x7fELF\x02\x01"])
def test_empty_or_truncated_elf_is_rejected(tmp_path, payload):
    binary = tmp_path / "soloist"
    binary.write_bytes(payload)
    with pytest.raises(SpotifySoloistArtifactError):
        inspect_soloist_elf(binary, "x86_64")


def test_absent_installed_binary_returns_not_installed(tmp_path):
    runner = mock.Mock(side_effect=AssertionError("runner invoked"))
    authority = SpotifySoloistArtifactAuthority(
        paths=_paths(tmp_path),
        host_architecture="x86_64",
        command_runner=runner,
    )
    status = authority.inspect_installed(now=BUILD_NOW)
    assert status.installed is False
    assert status.valid is False
    assert status.error_code == "not_installed"
    runner.assert_not_called()


def test_valid_inspection_invokes_only_expected_binary_version(tmp_path):
    runner = RecordingRunner()
    authority, binary = _installed_authority(tmp_path, runner=runner)
    status = authority.inspect_installed(now=BUILD_NOW)
    assert status.valid is True
    assert len(runner.calls) == 1
    argv, kwargs = runner.calls[0]
    assert argv == [str(binary), "--version"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] > 0
    assert kwargs["check"] is False


def test_nonzero_version_exit_is_rejected(tmp_path):
    authority, _binary = _installed_authority(
        tmp_path,
        runner=RecordingRunner(returncode=10),
    )
    status = authority.inspect_installed(now=BUILD_NOW)
    assert status.valid is False
    assert status.error_code == "version_failed"


def test_version_timeout_is_rejected(tmp_path):
    def timeout(_argv, **kwargs):
        raise subprocess.TimeoutExpired("soloist", kwargs["timeout"])

    authority, _binary = _installed_authority(tmp_path, runner=timeout)
    status = authority.inspect_installed(now=BUILD_NOW)
    assert status.valid is False
    assert status.error_code == "version_failed"


def test_unexpected_runner_error_is_sanitized(tmp_path):
    private_detail = "private-subprocess-detail-never-exposed"

    def fail(_argv, **_kwargs):
        raise RuntimeError(private_detail)

    authority, _binary = _installed_authority(tmp_path, runner=fail)
    status = authority.inspect_installed(now=BUILD_NOW)
    assert status.error_code == "version_failed"
    assert private_detail not in repr(status)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_oversized_version_stream_is_rejected(tmp_path, stream):
    kwargs = {stream: b"x" * 4097}
    authority, _binary = _installed_authority(
        tmp_path,
        runner=RecordingRunner(**kwargs),
    )
    status = authority.inspect_installed(now=BUILD_NOW)
    assert status.valid is False
    assert status.error_code == "version_failed"


def test_reported_architecture_mismatch_is_rejected(tmp_path):
    output = SAMPLE.replace("x86_64", "aarch64").encode("ascii")
    authority, _binary = _installed_authority(
        tmp_path,
        runner=RecordingRunner(stdout=output),
    )
    status = authority.inspect_installed(now=BUILD_NOW)
    assert status.valid is False
    assert status.error_code == "architecture_mismatch"


def test_sha256_is_calculated_from_local_binary(tmp_path):
    authority, binary = _installed_authority(tmp_path)
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    status = authority.inspect_installed(now=BUILD_NOW)
    assert status.sha256 == expected
    assert len(status.sha256) == 64


def test_expired_installed_binary_is_invalid_with_fixed_status(tmp_path):
    authority, _binary = _installed_authority(tmp_path)
    build = parse_soloist_version(SAMPLE)
    status = authority.inspect_installed(
        now=build.expires_at_utc + timedelta(seconds=1)
    )
    assert status.installed is True
    assert status.valid is False
    assert status.expired is True
    assert status.seconds_remaining == 0
    assert status.error_code == "expired"


def test_sanitized_status_has_exact_secret_free_fields(tmp_path):
    authority, _binary = _installed_authority(tmp_path)
    snapshot = authority.status_snapshot(now=BUILD_NOW)
    assert set(snapshot) == {
        "installed",
        "valid",
        "version",
        "build_timestamp",
        "build_date",
        "build_identifier",
        "platform",
        "architecture",
        "sha256",
        "expires_at",
        "expired",
        "seconds_remaining",
        "error_code",
    }
    lowered = repr(snapshot).lower()
    assert "api_key" not in lowered
    assert "secret" not in lowered
    assert str(tmp_path) not in lowered


def test_status_contract_is_immutable(tmp_path):
    authority, _binary = _installed_authority(tmp_path)
    status = authority.inspect_installed(now=BUILD_NOW)
    with pytest.raises(dataclasses.FrozenInstanceError):
        status.valid = False


def test_source_has_no_network_install_or_secret_access_code():
    source = (SRC / "services/spotify_soloist_artifact.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "import requests",
        "import httpx",
        "import socket",
        "urllib.request",
        "import tarfile",
        "unpack_archive",
        "extractall",
        "api_key",
        "spotifysecretstore",
        "os.makedirs",
        "os.mkdir",
        "os.chmod",
        "os.chown",
        "os.rename",
        "os.replace",
    )
    assert not any(item in lowered for item in forbidden)


def test_authority_uses_locked_paths_binary_location_only():
    parameters = inspect.signature(SpotifySoloistArtifactAuthority).parameters
    assert "binary_path" not in parameters
    assert "url" not in parameters
    source = inspect.getsource(SpotifySoloistArtifactAuthority.__init__)
    assert 'os.path.join(paths.soloist_install_dir, "soloist")' in source


def test_status_code_values_are_fixed_and_nonsecret():
    assert {code.value for code in SpotifySoloistArtifactStatusCode} == {
        "not_installed",
        "valid",
        "expired",
        "invalid_file",
        "invalid_elf",
        "version_failed",
        "invalid_version",
        "architecture_mismatch",
    }
