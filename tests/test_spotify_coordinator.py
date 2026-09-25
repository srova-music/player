import importlib
import os
import socket
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services import spotify_coordinator
from services.spotify_coordinator import (
    InvalidSpotifyTransition,
    SpotifyCoordinator,
    SpotifyLifecycle,
    SpotifySafetyVerificationRequired,
)


EXPECTED_STATUS_KEYS = {"state", "spotify_owner", "native_blocked"}
STATE_SEMANTICS = {
    "disabled": (False, False),
    "standby": (False, False),
    "acquiring": (False, True),
    "owned": (True, True),
    "releasing": (True, True),
    "recovering": (False, True),
    "safe_error": (False, False),
    "unsafe_error": (False, True),
}


def _owned_coordinator():
    coordinator = SpotifyCoordinator()
    coordinator.enter_standby()
    coordinator.begin_acquisition()
    coordinator.confirm_owned()
    return coordinator


def _coordinator_in_state(state):
    coordinator = SpotifyCoordinator()
    if state is SpotifyLifecycle.DISABLED:
        return coordinator
    if state is SpotifyLifecycle.SAFE_ERROR:
        coordinator.mark_safe_error(verified_safe=True)
        return coordinator
    if state is SpotifyLifecycle.UNSAFE_ERROR:
        coordinator.mark_unsafe_error()
        return coordinator

    coordinator.enter_standby()
    if state is SpotifyLifecycle.STANDBY:
        return coordinator

    coordinator.begin_acquisition()
    if state is SpotifyLifecycle.ACQUIRING:
        return coordinator
    if state is SpotifyLifecycle.RECOVERING:
        coordinator.begin_recovery()
        return coordinator

    coordinator.confirm_owned()
    if state is SpotifyLifecycle.OWNED:
        return coordinator

    coordinator.begin_release()
    assert state is SpotifyLifecycle.RELEASING
    return coordinator


def test_initial_state_is_deterministic_and_native_safe():
    coordinator = SpotifyCoordinator()

    assert coordinator.state is SpotifyLifecycle.DISABLED
    assert coordinator.spotify_owner is False
    assert coordinator.native_blocked is False
    assert coordinator.can_native_play() is True
    assert coordinator.status_snapshot() == {
        "state": "disabled",
        "spotify_owner": False,
        "native_blocked": False,
    }


@pytest.mark.parametrize(
    ("state", "owner", "blocked"),
    [
        (SpotifyLifecycle.DISABLED, False, False),
        (SpotifyLifecycle.STANDBY, False, False),
        (SpotifyLifecycle.ACQUIRING, False, True),
        (SpotifyLifecycle.OWNED, True, True),
        (SpotifyLifecycle.RELEASING, True, True),
        (SpotifyLifecycle.RECOVERING, False, True),
        (SpotifyLifecycle.SAFE_ERROR, False, False),
        (SpotifyLifecycle.UNSAFE_ERROR, False, True),
    ],
)
def test_each_lifecycle_state_has_locked_ownership_semantics(state, owner, blocked):
    coordinator = _coordinator_in_state(state)

    assert coordinator.spotify_owner is owner
    assert coordinator.native_blocked is blocked
    assert coordinator.can_native_play() is (not blocked)
    assert coordinator.status_snapshot() == {
        "state": state.value,
        "spotify_owner": owner,
        "native_blocked": blocked,
    }


def test_happy_path_requires_verified_release_before_native_unlocks():
    coordinator = _owned_coordinator()

    coordinator.begin_release()

    assert coordinator.state is SpotifyLifecycle.RELEASING
    assert coordinator.spotify_owner is True
    assert coordinator.native_blocked is True

    coordinator.complete_release(verified_safe=True)

    assert coordinator.state is SpotifyLifecycle.STANDBY
    assert coordinator.spotify_owner is False
    assert coordinator.can_native_play() is True


def test_unverified_release_fails_closed_until_verified_recovery():
    coordinator = _owned_coordinator()
    coordinator.begin_release()

    coordinator.complete_release(verified_safe=False)

    assert coordinator.state is SpotifyLifecycle.UNSAFE_ERROR
    assert coordinator.native_blocked is True
    coordinator.begin_recovery()
    assert coordinator.native_blocked is True
    coordinator.complete_recovery(verified_safe=True)
    assert coordinator.state is SpotifyLifecycle.STANDBY
    assert coordinator.can_native_play() is True


@pytest.mark.parametrize(
    "recovery_origin",
    [
        SpotifyLifecycle.ACQUIRING,
        SpotifyLifecycle.OWNED,
        SpotifyLifecycle.RELEASING,
    ],
)
def test_uncertain_runtime_loss_enters_blocked_recovery(recovery_origin):
    coordinator = _coordinator_in_state(recovery_origin)

    coordinator.begin_recovery()

    assert coordinator.state is SpotifyLifecycle.RECOVERING
    assert coordinator.native_blocked is True
    coordinator.complete_recovery(verified_safe=False)
    assert coordinator.state is SpotifyLifecycle.UNSAFE_ERROR
    assert coordinator.native_blocked is True


def test_safe_error_requires_positive_verification():
    coordinator = _owned_coordinator()

    with pytest.raises(SpotifySafetyVerificationRequired):
        coordinator.mark_safe_error(verified_safe=False)

    assert coordinator.state is SpotifyLifecycle.OWNED
    assert coordinator.native_blocked is True

    coordinator.mark_safe_error(verified_safe=True)
    assert coordinator.state is SpotifyLifecycle.SAFE_ERROR
    assert coordinator.can_native_play() is True


def test_disable_is_rejected_while_ownership_is_not_verified_safe():
    coordinator = _owned_coordinator()

    with pytest.raises(InvalidSpotifyTransition):
        coordinator.disable()

    assert coordinator.state is SpotifyLifecycle.OWNED
    assert coordinator.native_blocked is True

    coordinator.begin_release()
    coordinator.complete_release(verified_safe=True)
    coordinator.disable()
    assert coordinator.state is SpotifyLifecycle.DISABLED


def test_illegal_transition_leaves_state_unchanged():
    coordinator = SpotifyCoordinator()
    before = coordinator.status_snapshot()

    with pytest.raises(InvalidSpotifyTransition):
        coordinator.begin_acquisition()

    assert coordinator.status_snapshot() == before


def test_completion_from_wrong_state_is_rejected_without_mutation():
    coordinator = SpotifyCoordinator()
    coordinator.enter_standby()
    before = coordinator.status_snapshot()

    with pytest.raises(InvalidSpotifyTransition):
        coordinator.complete_release(verified_safe=True)

    assert coordinator.status_snapshot() == before


def test_status_snapshot_is_exactly_allowlisted_and_secret_free():
    coordinator = _owned_coordinator()
    snapshot = coordinator.status_snapshot()

    assert set(snapshot) == EXPECTED_STATUS_KEYS
    forbidden = (
        "api_key",
        "token",
        "password",
        "secret",
        "argv",
        "command",
        "environment",
    )
    assert not any(token in key.lower() for key in snapshot for token in forbidden)


def test_concurrent_snapshots_never_expose_impossible_combinations():
    coordinator = SpotifyCoordinator()
    coordinator.enter_standby()
    stop = threading.Event()
    errors = []
    errors_lock = threading.Lock()

    def reader():
        while not stop.is_set():
            snapshot = coordinator.status_snapshot()
            expected_owner, expected_blocked = STATE_SEMANTICS[snapshot["state"]]
            if snapshot["spotify_owner"] is not expected_owner:
                with errors_lock:
                    errors.append(snapshot)
                stop.set()
            if snapshot["native_blocked"] is not expected_blocked:
                with errors_lock:
                    errors.append(snapshot)
                stop.set()

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for thread in readers:
        thread.start()

    try:
        for _ in range(500):
            coordinator.begin_acquisition()
            coordinator.confirm_owned()
            coordinator.begin_release()
            coordinator.complete_release(verified_safe=True)
    finally:
        stop.set()
        for thread in readers:
            thread.join(timeout=2.0)

    assert errors == []
    assert all(not thread.is_alive() for thread in readers)


def test_import_and_construction_have_no_runtime_side_effects():
    source_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "src")
    )
    code = r"""
import importlib
import os
import socket
import subprocess
import threading

from services import spotify_coordinator

def forbidden_call(*_args, **_kwargs):
    raise AssertionError("runtime side effect attempted")

threading.Thread.start = forbidden_call
subprocess.Popen = forbidden_call
subprocess.run = forbidden_call
os.system = forbidden_call
socket.socket = forbidden_call

reloaded = importlib.reload(spotify_coordinator)
coordinator = reloaded.SpotifyCoordinator()

assert coordinator.status_snapshot() == {
    "state": "disabled",
    "spotify_owner": False,
    "native_blocked": False,
}
"""

    env = dict(os.environ)
    env["PYTHONPATH"] = source_root + os.pathsep + env.get(
        "PYTHONPATH",
        "",
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, (
        completed.stdout + completed.stderr
    )


def test_confirm_owned_from_recovery_never_unblocks_native():
    from services.spotify_coordinator import (
        SpotifyCoordinator,
        SpotifyLifecycle,
    )

    coordinator = SpotifyCoordinator()

    coordinator.enter_standby()
    coordinator.begin_acquisition()
    coordinator.begin_recovery()

    assert coordinator.state is SpotifyLifecycle.RECOVERING
    assert coordinator.native_blocked is True
    assert coordinator.can_native_play() is False

    coordinator.confirm_owned()

    assert coordinator.state is SpotifyLifecycle.OWNED
    assert coordinator.spotify_owner is True
    assert coordinator.native_blocked is True
    assert coordinator.can_native_play() is False


def test_cancel_recovery_without_spotify_claim_returns_disabled():
    from services.spotify_coordinator import (
        SpotifyCoordinator,
        SpotifyLifecycle,
    )

    coordinator = SpotifyCoordinator()

    coordinator.mark_unsafe_error()
    coordinator.begin_recovery()

    assert coordinator.state is SpotifyLifecycle.RECOVERING
    assert coordinator.native_blocked is True

    coordinator.cancel_recovery_without_spotify_claim(
        verified_no_spotify_claim=True
    )

    assert coordinator.state is SpotifyLifecycle.DISABLED
    assert coordinator.spotify_owner is False
    assert coordinator.native_blocked is False
    assert coordinator.can_native_play() is True


def test_cancel_recovery_without_spotify_claim_requires_explicit_assertion():
    import pytest

    from services.spotify_coordinator import (
        SpotifyCoordinator,
        SpotifyLifecycle,
        SpotifySafetyVerificationRequired,
    )

    coordinator = SpotifyCoordinator()

    coordinator.mark_unsafe_error()
    coordinator.begin_recovery()

    with pytest.raises(SpotifySafetyVerificationRequired):
        coordinator.cancel_recovery_without_spotify_claim(
            verified_no_spotify_claim=False
        )

    assert coordinator.state is SpotifyLifecycle.RECOVERING
    assert coordinator.native_blocked is True
