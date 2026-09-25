"""Serialized production lifecycle for Spotify audio and network access."""

from __future__ import annotations

import threading


class SpotifyEndpointLifecycleError(RuntimeError):
    """The Spotify endpoint lifecycle could not complete safely."""


class SpotifyEndpointLifecycle:
    """Wrap the audio authority with bounded dynamic network access."""

    def __init__(self, *, orchestrator, network_access) -> None:
        self._orchestrator = orchestrator
        self._network_access = network_access
        self._lock = threading.RLock()
        self._network_activation_failed = False
        self._retired = False

    def enable(self) -> bool:
        with self._lock:
            if self._retired:
                raise SpotifyEndpointLifecycleError(
                    "Spotify endpoint lifecycle is retired"
                )
            try:
                preflight_changed = bool(self._network_access.preflight())
                inner_changed = bool(self._orchestrator.enable())
                network_changed = bool(self._network_access.activate())
                reconciled = bool(self._orchestrator.reconcile())
                snapshot = self._inner_status()
                if snapshot.get("endpoint_available") is not True:
                    raise ValueError("endpoint unavailable after reconciliation")
            except Exception:
                self._network_activation_failed = True
                self._withdraw_after_failed_enable()
                raise SpotifyEndpointLifecycleError(
                    "Spotify endpoint could not be enabled"
                ) from None
            self._network_activation_failed = False
            return bool(
                preflight_changed
                or inner_changed
                or network_changed
                or reconciled
            )

    def disable(self) -> bool:
        with self._lock:
            if self._retired:
                return False
            release_failed = False
            release_changed = False
            try:
                release_changed = bool(self._network_access.release())
            except Exception:
                release_failed = True

            inner_changed = False
            inner_failed = False
            try:
                inner_changed = bool(self._orchestrator.disable())
            except Exception:
                inner_failed = True

            cleanup_failed = False
            cleanup_changed = False
            if release_failed:
                try:
                    cleanup_changed = bool(self._network_access.cleanup_stale())
                except Exception:
                    cleanup_failed = True

            self._network_activation_failed = False
            if inner_failed or cleanup_failed:
                raise SpotifyEndpointLifecycleError(
                    "Spotify endpoint could not be disabled cleanly"
                )
            return bool(release_changed or inner_changed or cleanup_changed)

    def deactivate(self) -> bool:
        with self._lock:
            if self._retired:
                return False
            try:
                return bool(self._orchestrator.deactivate())
            except Exception:
                raise SpotifyEndpointLifecycleError(
                    "Spotify active device could not be released"
                ) from None

    def prepare_native_claim(self) -> bool:
        with self._lock:
            if self._retired:
                return True
            try:
                allowed = bool(self._orchestrator.prepare_native_claim())
            except Exception:
                raise SpotifyEndpointLifecycleError(
                    "Spotify native claim preparation failed"
                ) from None

            if not allowed:
                return False

            release_failed = False
            try:
                self._network_access.release()
            except Exception:
                release_failed = True

            if release_failed:
                try:
                    self._network_access.cleanup_stale()
                except Exception:
                    pass
            self._network_activation_failed = False
            return True

    def reconcile(self) -> bool:
        with self._lock:
            if self._retired:
                return False
            try:
                changed = bool(self._orchestrator.reconcile())
                snapshot = self._inner_status()
                if snapshot.get("endpoint_available") is not True:
                    release_failed = False
                    try:
                        network_changed = bool(self._network_access.release())
                    except Exception:
                        release_failed = True
                        network_changed = False
                    if release_failed:
                        self._network_access.cleanup_stale()
                    changed = changed or network_changed
                return changed
            except Exception:
                raise SpotifyEndpointLifecycleError(
                    "Spotify endpoint reconciliation failed"
                ) from None

    def status_snapshot(self) -> dict:
        with self._lock:
            try:
                snapshot = self._inner_status()
            except Exception:
                raise SpotifyEndpointLifecycleError(
                    "Spotify endpoint status is unavailable"
                ) from None
            if self._network_activation_failed or self._retired:
                snapshot["endpoint_available"] = False
            return snapshot

    def retire(self) -> bool:
        with self._lock:
            if self._retired:
                return False
            try:
                self.disable()
            except Exception:
                raise SpotifyEndpointLifecycleError(
                    "Spotify endpoint could not be retired safely"
                ) from None
            self._retired = True
            self._network_activation_failed = False
            return True

    def _inner_status(self) -> dict:
        snapshot = self._orchestrator.status_snapshot()
        if not isinstance(snapshot, dict):
            raise ValueError("invalid inner status")
        return dict(snapshot)

    def _withdraw_after_failed_enable(self) -> None:
        try:
            self._network_access.release()
        except Exception:
            pass
        try:
            self._network_access.cleanup_stale()
        except Exception:
            pass
        try:
            self._orchestrator.disable()
        except Exception:
            pass


__all__ = ["SpotifyEndpointLifecycle", "SpotifyEndpointLifecycleError"]
