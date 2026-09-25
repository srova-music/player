"""Dormant runtime composition and immutable Spotify output binding."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from services.spotify_endpoint_lifecycle import SpotifyEndpointLifecycle
from services.spotify_endpoint_network_access import SpotifyEndpointNetworkAccess
from services.spotify_firewall_manager import SpotifyFirewallManager
from services.spotify_alsa_pcm_verifier import SpotifyAlsaPcmVerifier
from services.spotify_lan_network_resolver import SpotifyLanNetworkResolver
from services.spotify_orchestrator import SpotifyOrchestrator
from services.spotify_paths import SpotifyPaths
from services.spotify_pipewire_dac_resolver import SpotifyPipeWireDacResolver
from services.spotify_pipewire_prearm import SpotifyPipeWirePrearm
from services.spotify_runtime_supervisor import SpotifyRuntimeSupervisor
from services.spotify_soloist_event_observer import SpotifySoloistEventObserver
from services.spotify_soloist_listener_resolver import (
    SpotifySoloistLanListenerResolver,
)


class SpotifyRuntimeCompositionError(RuntimeError):
    """Dormant Spotify dependencies could not be composed safely."""


@dataclass(frozen=True)
class SpotifyRuntimeComponents:
    """Stable dormant dependencies shared by a future orchestrator."""

    runtime_supervisor: SpotifyRuntimeSupervisor
    dac_resolver: SpotifyPipeWireDacResolver
    pipewire_prearm: SpotifyPipeWirePrearm
    observer: SpotifySoloistEventObserver
    pcm_verifier: SpotifyAlsaPcmVerifier
    firewall_manager: SpotifyFirewallManager
    lan_network_resolver: SpotifyLanNetworkResolver
    listener_resolver: SpotifySoloistLanListenerResolver
    endpoint_network_access: SpotifyEndpointNetworkAccess


@dataclass(frozen=True)
class SpotifyOutputBinding:
    """Immutable physical ALSA identity for one orchestrator lifetime."""

    card_number: int
    device_number: int

    def __post_init__(self) -> None:
        for value in (self.card_number, self.device_number):
            if type(value) is not int or value < 0:
                raise SpotifyRuntimeCompositionError(
                    "Spotify output binding is invalid"
                )


def build_spotify_runtime_components(
    *,
    paths: SpotifyPaths,
    managed,
    runtime_supervisor_factory: Callable = SpotifyRuntimeSupervisor,
    dac_resolver_factory: Callable = SpotifyPipeWireDacResolver,
    pipewire_prearm_factory: Callable = SpotifyPipeWirePrearm,
    observer_factory: Callable = SpotifySoloistEventObserver,
    pcm_verifier_factory: Callable = SpotifyAlsaPcmVerifier,
    firewall_manager_factory: Callable = SpotifyFirewallManager,
    lan_network_resolver_factory: Callable = SpotifyLanNetworkResolver,
    listener_resolver_factory: Callable = SpotifySoloistLanListenerResolver,
    endpoint_network_access_factory: Callable = SpotifyEndpointNetworkAccess,
) -> SpotifyRuntimeComponents:
    """Construct stable runtime dependencies without activating any of them."""

    if not isinstance(paths, SpotifyPaths):
        raise SpotifyRuntimeCompositionError("Spotify paths are unavailable")
    if (
        getattr(managed, "paths", None) is not paths
        or getattr(managed, "soloist_supervisor", None) is None
    ):
        raise SpotifyRuntimeCompositionError(
            "Managed Spotify components are unavailable"
        )

    runtime_supervisor = runtime_supervisor_factory(
        runtime_dir=paths.spotify_runtime_dir,
    )
    dac_resolver = dac_resolver_factory()
    pipewire_prearm = pipewire_prearm_factory()
    observer = observer_factory(
        binary_path=os.path.join(
            paths.soloist_install_dir,
            "soloist",
        ),
    )
    pcm_verifier = pcm_verifier_factory()
    firewall_manager = firewall_manager_factory()
    lan_network_resolver = lan_network_resolver_factory()
    listener_resolver = listener_resolver_factory()
    endpoint_network_access = endpoint_network_access_factory(
        firewall_manager=firewall_manager,
        lan_network_resolver=lan_network_resolver,
        listener_resolver=listener_resolver,
        soloist_supervisor=managed.soloist_supervisor,
    )

    return SpotifyRuntimeComponents(
        runtime_supervisor=runtime_supervisor,
        dac_resolver=dac_resolver,
        pipewire_prearm=pipewire_prearm,
        observer=observer,
        pcm_verifier=pcm_verifier,
        firewall_manager=firewall_manager,
        lan_network_resolver=lan_network_resolver,
        listener_resolver=listener_resolver,
        endpoint_network_access=endpoint_network_access,
    )


def build_spotify_orchestrator(
    *,
    binding: SpotifyOutputBinding,
    device_name: str,
    coordinator,
    secret_store,
    managed,
    runtime: SpotifyRuntimeComponents,
    orchestrator_factory: Callable = SpotifyOrchestrator,
):
    """Compose physical output identity with its independent presentation name."""

    if not isinstance(binding, SpotifyOutputBinding):
        raise SpotifyRuntimeCompositionError("Spotify output binding is unavailable")
    if (
        not isinstance(device_name, str)
        or not device_name
        or device_name != device_name.strip()
        or len(device_name) > 256
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in device_name
        )
    ):
        raise SpotifyRuntimeCompositionError(
            "Spotify presentation name is unavailable"
        )
    if not isinstance(runtime, SpotifyRuntimeComponents):
        raise SpotifyRuntimeCompositionError("Spotify runtime is unavailable")
    if coordinator is None or secret_store is None:
        raise SpotifyRuntimeCompositionError(
            "Spotify application authorities are unavailable"
        )
    soloist_supervisor = getattr(managed, "soloist_supervisor", None)
    if soloist_supervisor is None:
        raise SpotifyRuntimeCompositionError(
            "Managed Spotify components are unavailable"
        )

    return orchestrator_factory(
        coordinator=coordinator,
        secret_store=secret_store,
        runtime_supervisor=runtime.runtime_supervisor,
        dac_resolver=runtime.dac_resolver,
        pipewire_prearm=runtime.pipewire_prearm,
        soloist_supervisor=soloist_supervisor,
        observer=runtime.observer,
        pcm_verifier=runtime.pcm_verifier,
        card_number=binding.card_number,
        device_number=binding.device_number,
        device_name=device_name,
    )


def build_spotify_endpoint_lifecycle(
    *,
    binding: SpotifyOutputBinding,
    device_name: str,
    coordinator,
    secret_store,
    managed,
    runtime: SpotifyRuntimeComponents,
    orchestrator_factory: Callable = SpotifyOrchestrator,
    lifecycle_factory: Callable = SpotifyEndpointLifecycle,
):
    """Construct one dormant outer lifecycle around one inner orchestrator."""

    orchestrator = build_spotify_orchestrator(
        binding=binding,
        device_name=device_name,
        coordinator=coordinator,
        secret_store=secret_store,
        managed=managed,
        runtime=runtime,
        orchestrator_factory=orchestrator_factory,
    )
    return lifecycle_factory(
        orchestrator=orchestrator,
        network_access=runtime.endpoint_network_access,
    )


__all__ = [
    "SpotifyOutputBinding",
    "SpotifyRuntimeComponents",
    "SpotifyRuntimeCompositionError",
    "build_spotify_endpoint_lifecycle",
    "build_spotify_orchestrator",
    "build_spotify_runtime_components",
]
