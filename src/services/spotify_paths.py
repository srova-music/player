"""Side-effect-free path authority for managed Spotify runtime components."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from utils.paths import get_cache_dir, get_data_dir


class SpotifyPathError(ValueError):
    """A Spotify-owned path could not be resolved safely."""


@dataclass(frozen=True)
class SpotifyPaths:
    """Immutable resolved locations for later Spotify managers."""

    spotify_state_dir: str
    spotify_cache_dir: str
    spotify_runtime_dir: str
    soloist_install_dir: str
    soloist_data_dir: str
    soloist_cache_dir: str


_SPOTIFY_DIRECTORY_NAME = "spotify"
_SOLOIST_DIRECTORY_NAME = "soloist"
_DEFAULT_RUNTIME_PARENT = "/run/srova"


def _absolute_directory(value: object, *, label: str) -> str:
    if not isinstance(value, (str, os.PathLike)):
        raise SpotifyPathError(f"{label} must be an absolute path")
    text = os.fspath(value)
    if not isinstance(text, str):
        raise SpotifyPathError(f"{label} must be an absolute path")
    text = text.strip()
    if not text or not os.path.isabs(text):
        raise SpotifyPathError(f"{label} must be an absolute path")
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise SpotifyPathError(f"{label} contains unsafe characters")
    normalized = os.path.normpath(text)
    if normalized == os.path.sep:
        raise SpotifyPathError(f"{label} cannot be the filesystem root")
    return normalized


def _environment_value(environment: Mapping[str, str], name: str) -> Optional[str]:
    if name not in environment:
        return None
    value = environment[name]
    if not isinstance(value, str) or not value.strip():
        raise SpotifyPathError(f"{name} cannot be empty")
    return value.strip()


def _systemd_parent(environment: Mapping[str, str], name: str) -> Optional[str]:
    value = _environment_value(environment, name)
    if value is None:
        return None
    # systemd may expose multiple *Directory entries as a colon-separated
    # absolute path list. The first entry is the authority for this slice.
    parent = value.split(":", 1)[0]
    return _absolute_directory(parent, label=name)


def _resolve_root(
    environment: Mapping[str, str],
    *,
    override_name: str,
    systemd_name: str,
    fallback_parent: object,
    label: str,
) -> str:
    override = _environment_value(environment, override_name)
    if override is not None:
        return _absolute_directory(override, label=override_name)

    systemd_parent = _systemd_parent(environment, systemd_name)
    if systemd_parent is not None:
        return _absolute_directory(
            os.path.join(systemd_parent, _SPOTIFY_DIRECTORY_NAME),
            label=label,
        )

    parent = _absolute_directory(fallback_parent, label=f"{label} parent")
    return _absolute_directory(
        os.path.join(parent, _SPOTIFY_DIRECTORY_NAME),
        label=label,
    )


def resolve_spotify_paths(
    *,
    environ: Optional[Mapping[str, str]] = None,
    data_dir: Optional[os.PathLike | str] = None,
    cache_dir: Optional[os.PathLike | str] = None,
) -> SpotifyPaths:
    """Resolve Spotify-owned paths without touching the filesystem."""

    environment = os.environ if environ is None else environ
    if not isinstance(environment, Mapping):
        raise SpotifyPathError("environment must be a mapping")

    data_parent = get_data_dir() if data_dir is None else data_dir
    cache_parent = get_cache_dir() if cache_dir is None else cache_dir

    state = _resolve_root(
        environment,
        override_name="SROVA_SPOTIFY_STATE_DIR",
        systemd_name="STATE_DIRECTORY",
        fallback_parent=data_parent,
        label="Spotify state directory",
    )
    cache = _resolve_root(
        environment,
        override_name="SROVA_SPOTIFY_CACHE_DIR",
        systemd_name="CACHE_DIRECTORY",
        fallback_parent=cache_parent,
        label="Spotify cache directory",
    )

    runtime_override = _environment_value(
        environment, "SROVA_SPOTIFY_RUNTIME_DIR"
    )
    if runtime_override is not None:
        runtime = _absolute_directory(
            runtime_override,
            label="SROVA_SPOTIFY_RUNTIME_DIR",
        )
    else:
        runtime_parent = _systemd_parent(environment, "RUNTIME_DIRECTORY")
        if runtime_parent is None:
            runtime_parent = _DEFAULT_RUNTIME_PARENT
        runtime = _absolute_directory(
            os.path.join(runtime_parent, _SPOTIFY_DIRECTORY_NAME),
            label="Spotify runtime directory",
        )

    roots = (state, cache, runtime)
    if len(set(roots)) != len(roots):
        raise SpotifyPathError(
            "Spotify state, cache, and runtime directories must be distinct"
        )

    soloist_state = os.path.join(state, _SOLOIST_DIRECTORY_NAME)
    return SpotifyPaths(
        spotify_state_dir=state,
        spotify_cache_dir=cache,
        spotify_runtime_dir=runtime,
        soloist_install_dir=os.path.join(soloist_state, "install"),
        soloist_data_dir=os.path.join(soloist_state, "data"),
        soloist_cache_dir=os.path.join(cache, _SOLOIST_DIRECTORY_NAME),
    )


__all__ = [
    "SpotifyPathError",
    "SpotifyPaths",
    "resolve_spotify_paths",
]
