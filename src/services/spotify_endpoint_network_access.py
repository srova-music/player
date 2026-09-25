"""Firewall and LAN mechanisms for the optional Spotify endpoint."""

from __future__ import annotations

import threading

from services.spotify_firewall_manager import FirewallClassification


class SpotifyEndpointNetworkAccessError(RuntimeError):
    """Spotify endpoint network access could not be managed safely."""


class SpotifyEndpointNetworkAccess:
    """Own one exact dynamic firewall lease for one Soloist supervisor."""

    def __init__(
        self,
        *,
        firewall_manager,
        lan_network_resolver,
        listener_resolver,
        soloist_supervisor,
    ) -> None:
        self._firewall_manager = firewall_manager
        self._lan_network_resolver = lan_network_resolver
        self._listener_resolver = listener_resolver
        self._soloist_supervisor = soloist_supervisor
        self._lease_active = False
        self._lock = threading.RLock()

    def preflight(self) -> bool:
        with self._lock:
            classification = self._classification()
            if classification in (
                FirewallClassification.NO_FIREWALL,
                FirewallClassification.UFW_INACTIVE,
            ):
                return False
            if classification is not FirewallClassification.UFW_ACTIVE:
                raise SpotifyEndpointNetworkAccessError(
                    "Spotify endpoint firewall is incompatible"
                )
            if self._lease_active:
                return False
            try:
                return bool(self._firewall_manager.cleanup_stale())
            except Exception:
                raise SpotifyEndpointNetworkAccessError(
                    "Spotify endpoint firewall preflight failed"
                ) from None

    def activate(self) -> bool:
        with self._lock:
            classification = self._classification()
            if classification in (
                FirewallClassification.NO_FIREWALL,
                FirewallClassification.UFW_INACTIVE,
            ):
                return False
            if classification is not FirewallClassification.UFW_ACTIVE:
                raise SpotifyEndpointNetworkAccessError(
                    "Spotify endpoint firewall is incompatible"
                )

            try:
                process_id = self._soloist_supervisor.process_id
                if type(process_id) is not int or process_id <= 0:
                    raise ValueError("invalid process")
                network = self._lan_network_resolver.resolve()
                port = self._listener_resolver.resolve(process_id=process_id)
                verified_process_id = self._soloist_supervisor.process_id
                if (
                    type(verified_process_id) is not int
                    or verified_process_id <= 0
                    or verified_process_id != process_id
                ):
                    raise ValueError("invalid process")
                changed = self._firewall_manager.prepare(
                    interface=network.interface,
                    source_cidr=network.source_cidr,
                    destination_ipv4=network.destination_ipv4,
                    port=port,
                )
                snapshot = self._firewall_manager.status_snapshot()
                if (
                    not isinstance(snapshot, dict)
                    or snapshot.get("lease_active") is not True
                    or snapshot.get("classification")
                    != FirewallClassification.UFW_ACTIVE.value
                    or snapshot.get("compatible") is not True
                    or snapshot.get("error") is not False
                ):
                    raise ValueError("lease verification failed")
            except Exception:
                self._lease_active = False
                raise SpotifyEndpointNetworkAccessError(
                    "Spotify endpoint network activation failed"
                ) from None

            self._lease_active = True
            return bool(changed)

    def release(self) -> bool:
        with self._lock:
            try:
                changed = bool(self._firewall_manager.release())
            except Exception:
                raise SpotifyEndpointNetworkAccessError(
                    "Spotify endpoint network release failed"
                ) from None
            self._lease_active = False
            return changed

    def cleanup_stale(self) -> bool:
        with self._lock:
            try:
                changed = bool(self._firewall_manager.cleanup_stale())
            except Exception:
                raise SpotifyEndpointNetworkAccessError(
                    "Spotify endpoint stale network cleanup failed"
                ) from None
            self._lease_active = False
            return changed

    def status_snapshot(self) -> dict[str, bool]:
        with self._lock:
            return {"lease_active": self._lease_active}

    def _classification(self) -> FirewallClassification:
        try:
            classification = self._firewall_manager.inspect()
        except Exception:
            raise SpotifyEndpointNetworkAccessError(
                "Spotify endpoint firewall inspection failed"
            ) from None
        if not isinstance(classification, FirewallClassification):
            raise SpotifyEndpointNetworkAccessError(
                "Spotify endpoint firewall inspection failed"
            )
        return classification


__all__ = [
    "SpotifyEndpointNetworkAccess",
    "SpotifyEndpointNetworkAccessError",
]
