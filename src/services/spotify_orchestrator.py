"""Serialized policy orchestration for the optional Spotify endpoint."""

from __future__ import annotations

import threading

from services.spotify_alsa_pcm_verifier import (
    SpotifyAlsaPcmVerificationError,
)
from services.spotify_coordinator import (
    InvalidSpotifyTransition,
    SpotifyLifecycle,
    SpotifySafetyVerificationRequired,
)
from services.spotify_pipewire_dac_resolver import (
    SpotifyPipeWireDacResolutionError,
)
from services.spotify_pipewire_prearm import SpotifyPipeWirePrearmError
from services.spotify_runtime_supervisor import SpotifyRuntimeError
from services.spotify_secret_store import SpotifySecretStoreError
from services.spotify_soloist_event_observer import (
    SpotifySoloistEventObserverError,
)
from services.spotify_soloist_supervisor import SpotifySoloistError


_LOCKED_COMPONENT_ERRORS = (
    InvalidSpotifyTransition,
    SpotifyAlsaPcmVerificationError,
    SpotifyPipeWireDacResolutionError,
    SpotifyPipeWirePrearmError,
    SpotifyRuntimeError,
    SpotifySafetyVerificationRequired,
    SpotifySecretStoreError,
    SpotifySoloistError,
    SpotifySoloistEventObserverError,
)

_STATE_SAFETY = {
    SpotifyLifecycle.DISABLED.value: (False, False),
    SpotifyLifecycle.STANDBY.value: (False, False),
    SpotifyLifecycle.ACQUIRING.value: (False, True),
    SpotifyLifecycle.OWNED.value: (True, True),
    SpotifyLifecycle.RELEASING.value: (True, True),
    SpotifyLifecycle.RECOVERING.value: (False, True),
    SpotifyLifecycle.SAFE_ERROR.value: (False, False),
    SpotifyLifecycle.UNSAFE_ERROR.value: (False, True),
}


class SpotifyOrchestratorError(RuntimeError):
    """A Spotify endpoint policy operation could not complete safely."""


class SpotifyOrchestrator:
    """Join locked Spotify primitives without implementing their mechanisms."""

    def __init__(
        self,
        *,
        coordinator,
        secret_store,
        runtime_supervisor,
        dac_resolver,
        pipewire_prearm,
        soloist_supervisor,
        observer,
        pcm_verifier,
        card_number: int,
        device_number: int,
        device_name: str,
    ) -> None:
        self._card_number = self._device_number(card_number)
        self._device_number_value = self._device_number(device_number)
        self._device_name = self._nonempty_text(device_name)
        self._coordinator = coordinator
        self._secret_store = secret_store
        self._runtime_supervisor = runtime_supervisor
        self._dac_resolver = dac_resolver
        self._pipewire_prearm = pipewire_prearm
        self._soloist_supervisor = soloist_supervisor
        self._observer = observer
        self._pcm_verifier = pcm_verifier
        self._lock = threading.RLock()
        self._phase = "disabled"

    def enable(self) -> bool:
        with self._lock:
            try:
                state = self._state_locked()
                if state in (
                    SpotifyLifecycle.STANDBY,
                    SpotifyLifecycle.OWNED,
                ):
                    health = self._endpoint_health_locked()
                else:
                    health = None
                if state is SpotifyLifecycle.STANDBY and health["healthy"]:
                    if health["is_active"]:
                        self._coordinator.begin_acquisition()
                        self._coordinator.confirm_owned()
                        self._phase = "owned"
                        return True
                    self._phase = "standby"
                    return False
                if state is SpotifyLifecycle.OWNED and health["healthy"]:
                    self._phase = "owned"
                    return False
                if state is not SpotifyLifecycle.DISABLED:
                    self._recover_endpoint_locked()
                    if self._state_locked() is SpotifyLifecycle.UNSAFE_ERROR:
                        raise SpotifyOrchestratorError(
                            "Spotify endpoint cannot be recovered safely"
                        )

                configured = self._secret_store.key_configured()
                if configured is not True:
                    raise SpotifyOrchestratorError(
                        "Spotify endpoint credentials are unavailable"
                    )
                api_key = self._secret_store.get_api_key()
                if not isinstance(api_key, str) or not api_key:
                    raise SpotifyOrchestratorError(
                        "Spotify endpoint credentials are unavailable"
                    )

                try:
                    # Block native claims before the first PCM observation.
                    # Otherwise native could begin between a free-state probe
                    # and endpoint construction.
                    self._block_for_recovery_locked()
                    self._phase = "starting"
                    endpoint_start_attempted = False

                    try:
                        if self._pcm_verifier.is_free(
                            card_number=self._card_number,
                            device_number=self._device_number_value,
                        ) is not True:
                            raise SpotifyOrchestratorError(
                                "Spotify endpoint cannot be started safely"
                            )

                        # Set this before the call: start_private_graph() may
                        # partially create runtime state and then raise.
                        endpoint_start_attempted = True
                        self._runtime_supervisor.start_private_graph()
                        environment = (
                            self._runtime_supervisor.private_environment()
                        )
                        node_name = self._dac_resolver.resolve(
                            card_number=self._card_number,
                            device_number=self._device_number_value,
                            environment=environment,
                        )
                        self._pipewire_prearm.prearm(
                            card_number=self._card_number,
                            device_number=self._device_number_value,
                            pipewire_node_name=node_name,
                            environment=environment,
                        )
                        try:
                            self._soloist_supervisor.start(
                                api_key=api_key,
                                device_name=self._device_name,
                                pipewire_node_name=node_name,
                                environment=environment,
                            )
                        finally:
                            api_key = None

                        soloist_status = (
                            self._soloist_supervisor.status_snapshot()
                        )
                        ws_port = self._ready_ws_port(soloist_status)
                        self._observer.start(ws_port=ws_port)
                        observer_status = self._observer.status_snapshot()
                        is_active = self._ready_observer_state(
                            observer_status
                        )

                        if is_active:
                            # Remain native-blocked continuously. Confirming
                            # active Spotify ownership directly from recovery
                            # avoids a transient native-safe STANDBY state.
                            self._coordinator.confirm_owned()
                            self._phase = "owned"
                        else:
                            # Endpoint construction must not inherit the
                            # pre-start PCM result. Positively re-verify that
                            # the selected PCM is still free before returning
                            # native playback to a safe STANDBY state.
                            if self._pcm_verifier.is_free(
                                card_number=self._card_number,
                                device_number=self._device_number_value,
                            ) is not True:
                                raise SpotifyOrchestratorError(
                                    "Spotify endpoint cannot be started safely"
                                )
                            self._coordinator.complete_recovery(
                                verified_safe=True
                            )
                            self._phase = "standby"
                    except Exception:
                        if not endpoint_start_attempted:
                            # Native was blocked before the PCM probe, but no
                            # Spotify runtime start was attempted. Spotify
                            # therefore had no opportunity to claim the PCM.
                            self._coordinator.cancel_recovery_without_spotify_claim(
                                verified_no_spotify_claim=True
                            )
                            self._phase = "disabled"
                            raise SpotifyOrchestratorError(
                                "Spotify endpoint could not be started"
                            ) from None

                        verified = self._cleanup_endpoint_locked(
                            wait_for_free=True
                        )
                        self._finish_error_locked(verified)
                        raise SpotifyOrchestratorError(
                            "Spotify endpoint could not be started"
                        ) from None
                    finally:
                        environment = None
                        node_name = None
                    return True
                finally:
                    api_key = None
            except SpotifyOrchestratorError:
                raise
            except _LOCKED_COMPONENT_ERRORS:
                raise SpotifyOrchestratorError(
                    "Spotify endpoint operation failed"
                ) from None
            except Exception:
                raise SpotifyOrchestratorError(
                    "Spotify endpoint operation failed"
                ) from None

    def disable(self) -> bool:
        with self._lock:
            try:
                state = self._state_locked()
                if (
                    state is SpotifyLifecycle.DISABLED
                    and not self._endpoint_present_or_uncertain_locked()
                ):
                    self._phase = "disabled"
                    return False

                self._block_for_recovery_locked()
                self._phase = "withdrawing"
                verified = self._cleanup_endpoint_locked(
                    wait_for_free=True
                )
                if not verified:
                    self._finish_error_locked(False)
                    raise SpotifyOrchestratorError(
                        "Spotify endpoint could not be disabled safely"
                    )

                self._complete_recovery_to_disabled_locked()
                self._phase = "disabled"
                return True
            except SpotifyOrchestratorError:
                raise
            except Exception:
                self._mark_unsafe_best_effort_locked()
                raise SpotifyOrchestratorError(
                    "Spotify endpoint could not be disabled safely"
                ) from None

    def deactivate(self) -> bool:
        with self._lock:
            try:
                state = self._state_locked()

                if state is SpotifyLifecycle.STANDBY:
                    self._phase = "standby"
                    return False

                if state is not SpotifyLifecycle.OWNED:
                    raise SpotifyOrchestratorError(
                        "Spotify active device cannot be released safely"
                    )

                if self._soloist_supervisor.deactivate() is not True:
                    raise SpotifyOrchestratorError(
                        "Spotify active device could not be released"
                    )

                # Do not clear ownership here. The passive Soloist observer
                # must first report is_active=False and normal reconciliation
                # must positively verify the PCM before STANDBY is restored.
                self._phase = "owned"
                return True
            except SpotifyOrchestratorError:
                raise
            except _LOCKED_COMPONENT_ERRORS:
                raise SpotifyOrchestratorError(
                    "Spotify active device could not be released"
                ) from None
            except Exception:
                raise SpotifyOrchestratorError(
                    "Spotify active device could not be released"
                ) from None

    def reconcile(self) -> bool:
        with self._lock:
            try:
                return self._reconcile_locked()
            except SpotifyOrchestratorError:
                raise
            except Exception:
                self._mark_unsafe_best_effort_locked()
                raise SpotifyOrchestratorError(
                    "Spotify endpoint reconciliation failed"
                ) from None

    def prepare_native_claim(self) -> bool:
        with self._lock:
            try:
                state = self._state_locked()

                if state is SpotifyLifecycle.STANDBY:
                    health = self._endpoint_health_locked()
                    if not health["healthy"]:
                        self._recover_endpoint_locked()
                        return False
                    if health["is_active"]:
                        self._coordinator.begin_acquisition()
                        self._coordinator.confirm_owned()
                        self._phase = "owned"
                        return False
                    return self._withdraw_for_native_locked()

                if state is SpotifyLifecycle.SAFE_ERROR:
                    return self._withdraw_for_native_locked()

                if state is SpotifyLifecycle.DISABLED:
                    if self._endpoint_present_or_uncertain_locked():
                        return self._withdraw_for_native_locked()
                    try:
                        verified = self._pcm_verifier.is_free(
                            card_number=self._card_number,
                            device_number=self._device_number_value,
                        ) is True
                    except Exception:
                        verified = False
                    if verified:
                        return True
                    self._coordinator.mark_unsafe_error()
                    self._phase = "unsafe_error"
                    return False

                self._set_phase_for_state_locked(state)
                return False
            except Exception:
                self._mark_unsafe_best_effort_locked()
                return False

    def status_snapshot(self) -> dict[str, object]:
        with self._lock:
            coordinator_status = self._safe_coordinator_status_locked()
            health = self._endpoint_health_locked()
            coordinator_valid = coordinator_status["valid"]
            return {
                "phase": (
                    self._phase if coordinator_valid else "unsafe_error"
                ),
                "endpoint_available": bool(
                    coordinator_valid and health["healthy"]
                ),
                "coordinator_state": coordinator_status["state"],
                "spotify_owner": coordinator_status["spotify_owner"],
                "native_blocked": coordinator_status["native_blocked"],
                "observer_ready": health["observer_ready"],
                "is_active": health["is_active"],
                "playback_status": health["playback_status"],
            }

    def _reconcile_locked(self) -> bool:
        state = self._state_locked()

        if state is SpotifyLifecycle.STANDBY:
            health = self._endpoint_health_locked()
            if not health["healthy"]:
                return self._recover_endpoint_locked()
            if health["is_active"]:
                self._coordinator.begin_acquisition()
                self._coordinator.confirm_owned()
                self._phase = "owned"
                return True
            self._phase = "standby"
            return False

        if state is SpotifyLifecycle.OWNED:
            health = self._endpoint_health_locked()
            if not health["healthy"]:
                return self._recover_endpoint_locked()
            if health["is_active"]:
                self._phase = "owned"
                return False

            self._coordinator.begin_release()
            self._phase = "releasing"
            try:
                released = self._pcm_verifier.wait_until_free(
                    card_number=self._card_number,
                    device_number=self._device_number_value,
                )
            except Exception:
                released = False
            if released is True:
                self._coordinator.complete_release(verified_safe=True)
                self._phase = "standby"
                return True

            self._coordinator.begin_recovery()
            self._phase = "recovering"
            verified = self._cleanup_endpoint_locked(wait_for_free=True)
            self._finish_error_locked(verified)
            return True

        if state is SpotifyLifecycle.DISABLED:
            if not self._endpoint_present_or_uncertain_locked():
                self._phase = "disabled"
                return False
            return self._recover_endpoint_locked()

        if state is SpotifyLifecycle.SAFE_ERROR:
            self._phase = "safe_error"
            return False

        if state is SpotifyLifecycle.UNSAFE_ERROR:
            return self._recover_endpoint_locked()

        return self._recover_endpoint_locked()

    def _recover_endpoint_locked(self) -> bool:
        self._block_for_recovery_locked()
        self._phase = "recovering"
        verified = self._cleanup_endpoint_locked(wait_for_free=True)
        self._finish_error_locked(verified)
        return True

    def _withdraw_for_native_locked(self) -> bool:
        self._block_for_recovery_locked()
        self._phase = "withdrawing"
        verified = self._cleanup_endpoint_locked(wait_for_free=True)
        if not verified:
            self._finish_error_locked(False)
            return False
        self._complete_recovery_to_disabled_locked()
        self._phase = "disabled"
        return True

    def _cleanup_endpoint_locked(self, *, wait_for_free: bool) -> bool:
        cleanup_ok = True
        for action in (
            self._observer.stop,
            self._soloist_supervisor.stop,
            self._runtime_supervisor.stop_private_graph,
        ):
            try:
                action()
            except _LOCKED_COMPONENT_ERRORS:
                cleanup_ok = False
            except Exception:
                cleanup_ok = False

        try:
            if wait_for_free:
                pcm_free = self._pcm_verifier.wait_until_free(
                    card_number=self._card_number,
                    device_number=self._device_number_value,
                )
            else:
                pcm_free = self._pcm_verifier.is_free(
                    card_number=self._card_number,
                    device_number=self._device_number_value,
                )
        except Exception:
            pcm_free = False

        # A physically missing PCM remains different from a verified closed
        # PCM. It may authorize teardown completion only after every managed
        # Spotify component is positively confirmed absent.
        if cleanup_ok and pcm_free is not True:
            try:
                pcm_absent = self._pcm_verifier.is_absent(
                    card_number=self._card_number,
                    device_number=self._device_number_value,
                ) is True
            except Exception:
                pcm_absent = False

            if pcm_absent and self._managed_endpoint_absent_locked():
                pcm_free = True

        return bool(cleanup_ok and pcm_free is True)

    def _managed_endpoint_absent_locked(self) -> bool:
        """Positively verify that no managed Spotify runtime remains."""

        try:
            runtime = self._runtime_supervisor.status_snapshot()
            soloist = self._soloist_supervisor.status_snapshot()
            observer = self._observer.status_snapshot()
        except Exception:
            return False

        return bool(
            isinstance(runtime, dict)
            and isinstance(soloist, dict)
            and isinstance(observer, dict)
            and runtime.get("pipewire_running") is False
            and runtime.get("wireplumber_running") is False
            and soloist.get("soloist_running") is False
            and observer.get("observer_running") is False
        )

    def _block_for_recovery_locked(self) -> None:
        state = self._state_locked()
        if state is SpotifyLifecycle.RECOVERING:
            return
        if state in (
            SpotifyLifecycle.ACQUIRING,
            SpotifyLifecycle.OWNED,
            SpotifyLifecycle.RELEASING,
            SpotifyLifecycle.UNSAFE_ERROR,
        ):
            self._coordinator.begin_recovery()
            return
        self._coordinator.mark_unsafe_error()
        self._coordinator.begin_recovery()

    def _finish_error_locked(self, verified_safe: bool) -> None:
        state = self._state_locked()
        if verified_safe:
            if state is SpotifyLifecycle.RECOVERING:
                self._coordinator.complete_recovery(verified_safe=True)
            elif state is SpotifyLifecycle.RELEASING:
                self._coordinator.complete_release(verified_safe=True)
            self._coordinator.mark_safe_error(verified_safe=True)
            self._phase = "safe_error"
            return

        if state is SpotifyLifecycle.RECOVERING:
            self._coordinator.complete_recovery(verified_safe=False)
        elif state is SpotifyLifecycle.RELEASING:
            self._coordinator.complete_release(verified_safe=False)
        elif state is not SpotifyLifecycle.UNSAFE_ERROR:
            self._coordinator.mark_unsafe_error()
        self._phase = "unsafe_error"

    def _complete_recovery_to_disabled_locked(self) -> None:
        state = self._state_locked()
        if state is SpotifyLifecycle.RECOVERING:
            self._coordinator.complete_recovery(verified_safe=True)
        elif state is SpotifyLifecycle.RELEASING:
            self._coordinator.complete_release(verified_safe=True)
        state = self._state_locked()
        if state is SpotifyLifecycle.SAFE_ERROR:
            self._coordinator.disable()
        elif state is SpotifyLifecycle.STANDBY:
            self._coordinator.disable()
        elif state is not SpotifyLifecycle.DISABLED:
            self._coordinator.mark_safe_error(verified_safe=True)
            self._coordinator.disable()

    def _endpoint_health_locked(self) -> dict[str, object]:
        result = {
            "healthy": False,
            "observer_ready": False,
            "is_active": None,
            "playback_status": None,
        }
        try:
            runtime = self._runtime_supervisor.status_snapshot()
            soloist = self._soloist_supervisor.status_snapshot()
            observer = self._observer.status_snapshot()
            ws_port = soloist.get("ws_port")
            observer_ready = bool(
                observer.get("observer_running") is True
                and observer.get("ready") is True
                and observer.get("faulted") is False
            )
            is_active = observer.get("is_active")
            healthy = bool(
                runtime.get("pipewire_running") is True
                and runtime.get("wireplumber_running") is True
                and soloist.get("soloist_running") is True
                and soloist.get("ready") is True
                and isinstance(ws_port, int)
                and not isinstance(ws_port, bool)
                and 1 <= ws_port <= 65535
                and observer_ready
                and isinstance(is_active, bool)
            )
            result["healthy"] = healthy
            result["observer_ready"] = observer_ready
            if healthy:
                result["is_active"] = is_active
                playback_status = observer.get("playback_status")
                if playback_status is None or isinstance(
                    playback_status, str
                ):
                    result["playback_status"] = playback_status
        except Exception:
            pass
        return result

    def _endpoint_present_or_uncertain_locked(self) -> bool:
        try:
            runtime = self._runtime_supervisor.status_snapshot()
            soloist = self._soloist_supervisor.status_snapshot()
            observer = self._observer.status_snapshot()
            return bool(
                runtime.get("pipewire_running") is True
                or runtime.get("wireplumber_running") is True
                or soloist.get("soloist_running") is True
                or observer.get("observer_running") is True
            )
        except Exception:
            return True

    def _safe_coordinator_status_locked(self) -> dict[str, object]:
        try:
            snapshot = self._coordinator.status_snapshot()
            state = snapshot.get("state")
            expected = _STATE_SAFETY.get(state)
            owner = snapshot.get("spotify_owner")
            blocked = snapshot.get("native_blocked")
            if (
                expected is None
                or not isinstance(owner, bool)
                or not isinstance(blocked, bool)
                or (owner, blocked) != expected
            ):
                raise ValueError
            return {
                "valid": True,
                "state": state,
                "spotify_owner": owner,
                "native_blocked": blocked,
            }
        except Exception:
            return {
                "valid": False,
                "state": SpotifyLifecycle.UNSAFE_ERROR.value,
                "spotify_owner": False,
                "native_blocked": True,
            }

    def _state_locked(self) -> SpotifyLifecycle:
        state = self._coordinator.state
        if not isinstance(state, SpotifyLifecycle):
            raise SpotifyOrchestratorError(
                "Spotify coordinator state is invalid"
            )
        return state

    @staticmethod
    def _ready_ws_port(snapshot: object) -> int:
        if not isinstance(snapshot, dict):
            raise SpotifyOrchestratorError(
                "Soloist readiness is invalid"
            )
        port = snapshot.get("ws_port")
        if (
            snapshot.get("soloist_running") is not True
            or snapshot.get("ready") is not True
            or isinstance(port, bool)
            or not isinstance(port, int)
            or port < 1
            or port > 65535
        ):
            raise SpotifyOrchestratorError(
                "Soloist readiness is invalid"
            )
        return port

    @staticmethod
    def _ready_observer_state(snapshot: object) -> bool:
        if not isinstance(snapshot, dict):
            raise SpotifyOrchestratorError(
                "Observer readiness is invalid"
            )
        active = snapshot.get("is_active")
        if (
            snapshot.get("observer_running") is not True
            or snapshot.get("ready") is not True
            or snapshot.get("faulted") is not False
            or not isinstance(active, bool)
        ):
            raise SpotifyOrchestratorError(
                "Observer readiness is invalid"
            )
        return active

    def _mark_unsafe_best_effort_locked(self) -> None:
        try:
            if self._state_locked() is not SpotifyLifecycle.UNSAFE_ERROR:
                self._coordinator.mark_unsafe_error()
        except Exception:
            pass
        self._phase = "unsafe_error"

    def _set_phase_for_state_locked(self, state: SpotifyLifecycle) -> None:
        self._phase = state.value

    @staticmethod
    def _device_number(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SpotifyOrchestratorError(
                "Spotify audio identity is invalid"
            )
        return value

    @staticmethod
    def _nonempty_text(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SpotifyOrchestratorError(
                "Spotify device name is invalid"
            )
        return value


__all__ = [
    "SpotifyOrchestrator",
    "SpotifyOrchestratorError",
]
