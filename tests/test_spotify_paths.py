import dataclasses
import importlib.util
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services import spotify_paths as paths_module  # noqa: E402
from services.spotify_paths import (  # noqa: E402
    SpotifyPathError,
    resolve_spotify_paths,
)


EMPTY_ENV = {}


def _resolve(environment=None):
    return resolve_spotify_paths(
        environ=EMPTY_ENV if environment is None else environment,
        data_dir="/dev/data/hiresti",
        cache_dir="/dev/cache/hiresti",
    )


def test_import_is_side_effect_free(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("filesystem mutation attempted during import")

    monkeypatch.setattr(os, "makedirs", forbidden)
    monkeypatch.setattr(os, "mkdir", forbidden)
    monkeypatch.setattr(os, "chmod", forbidden)
    monkeypatch.setattr(os, "remove", forbidden)
    monkeypatch.setattr(os, "unlink", forbidden)
    module_name = "services.spotify_paths_side_effect_probe"
    spec = importlib.util.spec_from_file_location(
        module_name,
        SRC / "services/spotify_paths.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)


def test_resolution_is_side_effect_free(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("filesystem mutation attempted during resolution")

    monkeypatch.setattr(os, "makedirs", forbidden)
    monkeypatch.setattr(os, "mkdir", forbidden)
    monkeypatch.setattr(os, "chmod", forbidden)
    monkeypatch.setattr(os, "remove", forbidden)
    monkeypatch.setattr(os, "unlink", forbidden)
    resolved = _resolve()
    assert resolved.spotify_state_dir == "/dev/data/hiresti/spotify"


def test_explicit_spotify_state_override_wins():
    resolved = _resolve(
        {
            "SROVA_SPOTIFY_STATE_DIR": "/srv/custom/state/../state",
            "STATE_DIRECTORY": "/ignored/state",
        }
    )
    assert resolved.spotify_state_dir == "/srv/custom/state"


def test_explicit_spotify_cache_override_wins():
    resolved = _resolve(
        {
            "SROVA_SPOTIFY_CACHE_DIR": "/srv/custom/cache/./spotify",
            "CACHE_DIRECTORY": "/ignored/cache",
        }
    )
    assert resolved.spotify_cache_dir == "/srv/custom/cache/spotify"


def test_explicit_spotify_runtime_override_wins():
    resolved = _resolve(
        {
            "SROVA_SPOTIFY_RUNTIME_DIR": "/srv/custom/run/../run/spotify",
            "RUNTIME_DIRECTORY": "/ignored/run",
        }
    )
    assert resolved.spotify_runtime_dir == "/srv/custom/run/spotify"


@pytest.mark.parametrize(
    ("variable", "value", "attribute", "expected"),
    [
        (
            "STATE_DIRECTORY",
            "/var/lib/srova",
            "spotify_state_dir",
            "/var/lib/srova/spotify",
        ),
        (
            "CACHE_DIRECTORY",
            "/var/cache/srova",
            "spotify_cache_dir",
            "/var/cache/srova/spotify",
        ),
        (
            "RUNTIME_DIRECTORY",
            "/run/srova",
            "spotify_runtime_dir",
            "/run/srova/spotify",
        ),
    ],
)
def test_systemd_directory_produces_spotify_child(
    variable, value, attribute, expected
):
    assert getattr(_resolve({variable: value}), attribute) == expected


def test_systemd_directory_list_uses_first_absolute_parent():
    resolved = _resolve({"RUNTIME_DIRECTORY": "/run/srova:/run/other"})
    assert resolved.spotify_runtime_dir == "/run/srova/spotify"


def test_source_state_fallback_uses_get_data_dir(monkeypatch):
    monkeypatch.setattr(paths_module, "get_data_dir", lambda: "/source/data/hiresti")
    resolved = paths_module.resolve_spotify_paths(
        environ=EMPTY_ENV,
        cache_dir="/source/cache/hiresti",
    )
    assert resolved.spotify_state_dir == "/source/data/hiresti/spotify"


def test_source_cache_fallback_uses_get_cache_dir(monkeypatch):
    monkeypatch.setattr(paths_module, "get_cache_dir", lambda: "/source/cache/hiresti")
    resolved = paths_module.resolve_spotify_paths(
        environ=EMPTY_ENV,
        data_dir="/source/data/hiresti",
    )
    assert resolved.spotify_cache_dir == "/source/cache/hiresti/spotify"


def test_runtime_fallback_preserves_locked_supervisor_contract():
    assert _resolve().spotify_runtime_dir == "/run/srova/spotify"


@pytest.mark.parametrize(
    "variable",
    [
        "SROVA_SPOTIFY_STATE_DIR",
        "SROVA_SPOTIFY_CACHE_DIR",
        "SROVA_SPOTIFY_RUNTIME_DIR",
        "STATE_DIRECTORY",
        "CACHE_DIRECTORY",
        "RUNTIME_DIRECTORY",
    ],
)
def test_relative_environment_paths_fail(variable):
    with pytest.raises(SpotifyPathError, match="absolute"):
        _resolve({variable: "relative/path"})


@pytest.mark.parametrize(
    "variable",
    [
        "SROVA_SPOTIFY_STATE_DIR",
        "SROVA_SPOTIFY_CACHE_DIR",
        "SROVA_SPOTIFY_RUNTIME_DIR",
    ],
)
def test_explicit_spotify_root_override_fails(variable):
    with pytest.raises(SpotifyPathError, match="filesystem root"):
        _resolve({variable: "/"})


@pytest.mark.parametrize(
    "variable",
    [
        "SROVA_SPOTIFY_STATE_DIR",
        "SROVA_SPOTIFY_CACHE_DIR",
        "SROVA_SPOTIFY_RUNTIME_DIR",
        "STATE_DIRECTORY",
        "CACHE_DIRECTORY",
        "RUNTIME_DIRECTORY",
    ],
)
@pytest.mark.parametrize("value", ["", "   "])
def test_empty_explicit_environment_values_fail_deterministically(variable, value):
    with pytest.raises(SpotifyPathError, match="cannot be empty"):
        _resolve({variable: value})


def test_soloist_layout_is_deterministic_and_separates_data_classes():
    resolved = _resolve()
    assert (
        resolved.soloist_install_dir
        == "/dev/data/hiresti/spotify/soloist/install"
    )
    assert resolved.soloist_data_dir == "/dev/data/hiresti/spotify/soloist/data"
    assert resolved.soloist_cache_dir == "/dev/cache/hiresti/spotify/soloist"
    assert len(
        {
            resolved.soloist_install_dir,
            resolved.soloist_data_dir,
            resolved.soloist_cache_dir,
        }
    ) == 3


def test_resolved_contract_is_immutable():
    resolved = _resolve()
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolved.spotify_state_dir = "/replacement"


@pytest.mark.parametrize(
    "environment",
    [
        {
            "SROVA_SPOTIFY_STATE_DIR": "/same/spotify",
            "SROVA_SPOTIFY_CACHE_DIR": "/same/spotify",
        },
        {
            "SROVA_SPOTIFY_STATE_DIR": "/same/spotify",
            "SROVA_SPOTIFY_RUNTIME_DIR": "/same/spotify",
        },
        {
            "SROVA_SPOTIFY_CACHE_DIR": "/same/spotify",
            "SROVA_SPOTIFY_RUNTIME_DIR": "/same/spotify",
        },
    ],
)
def test_owned_roots_cannot_alias_exactly(environment):
    with pytest.raises(SpotifyPathError, match="must be distinct"):
        _resolve(environment)


def test_sp1_disposable_path_is_never_produced():
    resolved = _resolve()
    assert all(
        "/tmp/srova-sp1" not in value
        for value in dataclasses.astuple(resolved)
    )


def test_source_has_no_machine_path_secret_or_side_effect_dependencies():
    source = (SRC / "services/spotify_paths.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "/home/casaos" not in source
    assert "/tmp/srova-sp1" not in source
    assert "spotifysecretstore" not in lowered
    assert "api_key" not in lowered
    assert "subprocess" not in lowered
    assert "requests" not in lowered
    assert "urllib" not in lowered
    assert "download" not in lowered
    assert "makedirs" not in lowered
    assert "mkdir(" not in lowered
    assert "chmod" not in lowered


def test_fallback_parent_must_also_be_safe_and_absolute():
    with pytest.raises(SpotifyPathError):
        resolve_spotify_paths(
            environ=EMPTY_ENV,
            data_dir="relative/data",
            cache_dir="/safe/cache",
        )
