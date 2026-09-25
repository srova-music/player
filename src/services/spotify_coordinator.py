"""Inert ownership-state foundation for the optional Spotify add-on."""

from enum import Enum
import threading
from typing import Dict, Iterable


class SpotifyLifecycle(str, Enum):
    """Lifecycle states with explicit native-audio safety semantics."""

    DISABLED = "disabled"
    STANDBY = "standby"
    ACQUIRING = "acquiring"
    OWNED = "owned"
    RELEASING = "releasing"
    RECOVERING = "recovering"
    SAFE_ERROR = "safe_error"
    UNSAFE_ERROR = "unsafe_error"


class InvalidSpotifyTransition(RuntimeError):
    """Raised when a lifecycle action is not legal from the current state."""


class SpotifySafetyVerificationRequired(RuntimeError):
    """Raised when a native-safe state is requested without verification."""


_NATIVE_BLOCKED = {
    SpotifyLifecycle.DISABLED: False,
    SpotifyLifecycle.STANDBY: False,
    SpotifyLifecycle.ACQUIRING: True,
    SpotifyLifecycle.OWNED: True,
    SpotifyLifecycle.RELEASING: True,
    SpotifyLifecycle.RECOVERING: True,
    SpotifyLifecycle.SAFE_ERROR: False,
    SpotifyLifecycle.UNSAFE_ERROR: True,
}

_SPOTIFY_OWNER = {
    SpotifyLifecycle.DISABLED: False,
    SpotifyLifecycle.STANDBY: False,
    SpotifyLifecycle.ACQUIRING: False,
    SpotifyLifecycle.OWNED: True,
    # A release request does not prove that Spotify has relinquished the PCM.
    SpotifyLifecycle.RELEASING: True,
    SpotifyLifecycle.RECOVERING: False,
    SpotifyLifecycle.SAFE_ERROR: False,
    SpotifyLifecycle.UNSAFE_ERROR: False,
}


class SpotifyCoordinator:
    """Thread-safe, side-effect-free Spotify/native ownership authority.

    Native playback fails closed during every ownership transition or uncertain
    recovery. Only an explicit positively verified completion can return a
    releasing or recovering coordinator to native-safe standby.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = SpotifyLifecycle.DISABLED

    @property
    def state(self) -> SpotifyLifecycle:
        with self._lock:
            return self._state

    @property
    def spotify_owner(self) -> bool:
        with self._lock:
            return _SPOTIFY_OWNER[self._state]

    @property
    def native_blocked(self) -> bool:
        with self._lock:
            return _NATIVE_BLOCKED[self._state]

    def can_native_play(self) -> bool:
        with self._lock:
            return not _NATIVE_BLOCKED[self._state]

    def status_snapshot(self) -> Dict[str, object]:
        """Return one atomic, deliberately allowlisted non-secret snapshot."""
        with self._lock:
            state = self._state
            return {
                "state": state.value,
                "spotify_owner": _SPOTIFY_OWNER[state],
                "native_blocked": _NATIVE_BLOCKED[state],
            }

    def enter_standby(self) -> SpotifyLifecycle:
        return self._transition(
            "enter_standby",
            (SpotifyLifecycle.DISABLED,),
            SpotifyLifecycle.STANDBY,
        )

    def begin_acquisition(self) -> SpotifyLifecycle:
        return self._transition(
            "begin_acquisition",
            (SpotifyLifecycle.STANDBY,),
            SpotifyLifecycle.ACQUIRING,
        )

    def confirm_owned(self) -> SpotifyLifecycle:
        return self._transition(
            "confirm_owned",
            (
                SpotifyLifecycle.ACQUIRING,
                SpotifyLifecycle.RECOVERING,
            ),
            SpotifyLifecycle.OWNED,
        )

    def cancel_recovery_without_spotify_claim(
        self,
        *,
        verified_no_spotify_claim: bool,
    ) -> SpotifyLifecycle:
        """Return to disabled only when Spotify never had a claim opportunity."""
        if verified_no_spotify_claim is not True:
            raise SpotifySafetyVerificationRequired(
                "cancel_recovery_without_spotify_claim requires "
                "verified_no_spotify_claim=True"
            )
        return self._transition(
            "cancel_recovery_without_spotify_claim",
            (SpotifyLifecycle.RECOVERING,),
            SpotifyLifecycle.DISABLED,
        )

    def begin_release(self) -> SpotifyLifecycle:
        return self._transition(
            "begin_release",
            (SpotifyLifecycle.OWNED,),
            SpotifyLifecycle.RELEASING,
        )

    def begin_recovery(self) -> SpotifyLifecycle:
        return self._transition(
            "begin_recovery",
            (
                SpotifyLifecycle.ACQUIRING,
                SpotifyLifecycle.OWNED,
                SpotifyLifecycle.RELEASING,
                SpotifyLifecycle.UNSAFE_ERROR,
            ),
            SpotifyLifecycle.RECOVERING,
        )

    def complete_release(self, *, verified_safe: bool) -> SpotifyLifecycle:
        return self._complete_safety_transition(
            "complete_release",
            SpotifyLifecycle.RELEASING,
            verified_safe,
        )

    def complete_recovery(self, *, verified_safe: bool) -> SpotifyLifecycle:
        return self._complete_safety_transition(
            "complete_recovery",
            SpotifyLifecycle.RECOVERING,
            verified_safe,
        )

    def mark_safe_error(self, *, verified_safe: bool) -> SpotifyLifecycle:
        """Record an error as native-safe only with positive PCM verification."""
        if not verified_safe:
            raise SpotifySafetyVerificationRequired(
                "mark_safe_error requires verified_safe=True"
            )
        return self._transition(
            "mark_safe_error",
            (
                state
                for state in SpotifyLifecycle
                if state is not SpotifyLifecycle.SAFE_ERROR
            ),
            SpotifyLifecycle.SAFE_ERROR,
        )

    def mark_unsafe_error(self) -> SpotifyLifecycle:
        """Record uncertainty and keep native playback blocked."""
        return self._transition(
            "mark_unsafe_error",
            (
                state
                for state in SpotifyLifecycle
                if state is not SpotifyLifecycle.UNSAFE_ERROR
            ),
            SpotifyLifecycle.UNSAFE_ERROR,
        )

    def disable(self) -> SpotifyLifecycle:
        """Disable only from a state where native PCM safety is established."""
        return self._transition(
            "disable",
            (SpotifyLifecycle.STANDBY, SpotifyLifecycle.SAFE_ERROR),
            SpotifyLifecycle.DISABLED,
        )

    def _complete_safety_transition(
        self,
        action: str,
        expected: SpotifyLifecycle,
        verified_safe: bool,
    ) -> SpotifyLifecycle:
        with self._lock:
            if self._state is not expected:
                self._raise_invalid(action, (expected,))
            self._state = (
                SpotifyLifecycle.STANDBY
                if verified_safe
                else SpotifyLifecycle.UNSAFE_ERROR
            )
            return self._state

    def _transition(
        self,
        action: str,
        allowed: Iterable[SpotifyLifecycle],
        target: SpotifyLifecycle,
    ) -> SpotifyLifecycle:
        allowed_states = tuple(allowed)
        with self._lock:
            if self._state not in allowed_states:
                self._raise_invalid(action, allowed_states)
            self._state = target
            return self._state

    def _raise_invalid(
        self,
        action: str,
        allowed: Iterable[SpotifyLifecycle],
    ) -> None:
        allowed_text = ", ".join(state.value for state in allowed)
        raise InvalidSpotifyTransition(
            f"{action} is invalid from {self._state.value}; expected: {allowed_text}"
        )


__all__ = [
    "InvalidSpotifyTransition",
    "SpotifyCoordinator",
    "SpotifyLifecycle",
    "SpotifySafetyVerificationRequired",
]
