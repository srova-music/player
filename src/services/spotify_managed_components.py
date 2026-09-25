"""Side-effect-free composition for managed Spotify artifact components."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

from services.spotify_paths import SpotifyPaths, resolve_spotify_paths
from services.spotify_soloist_artifact import SpotifySoloistArtifactAuthority
from services.spotify_soloist_installer import SpotifySoloistInstaller
from services.spotify_soloist_supervisor import SpotifySoloistSupervisor


@dataclass(frozen=True)
class SpotifyManagedComponents:
    """Production objects sharing one immutable Spotify path authority."""

    paths: SpotifyPaths
    artifact_authority: SpotifySoloistArtifactAuthority
    installer: SpotifySoloistInstaller
    soloist_supervisor: SpotifySoloistSupervisor


def build_spotify_managed_components(
    *,
    paths: Optional[SpotifyPaths] = None,
    path_resolver: Callable[[], SpotifyPaths] = resolve_spotify_paths,
    artifact_authority_factory: Callable = SpotifySoloistArtifactAuthority,
    installer_factory: Callable = SpotifySoloistInstaller,
    soloist_supervisor_factory: Callable = SpotifySoloistSupervisor,
) -> SpotifyManagedComponents:
    """Construct dormant managed components from one resolved path object."""

    shared_paths = path_resolver() if paths is None else paths
    canonical_binary = os.path.join(
        shared_paths.soloist_install_dir,
        "soloist",
    )

    return SpotifyManagedComponents(
        paths=shared_paths,
        artifact_authority=artifact_authority_factory(paths=shared_paths),
        installer=installer_factory(paths=shared_paths),
        soloist_supervisor=soloist_supervisor_factory(
            binary_path=canonical_binary,
            data_dir=shared_paths.soloist_data_dir,
            cache_dir=shared_paths.soloist_cache_dir,
        ),
    )


__all__ = [
    "SpotifyManagedComponents",
    "build_spotify_managed_components",
]
