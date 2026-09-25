import inspect
import sys
from collections import deque
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services import spotify_orchestrator as orchestrator_module  # noqa: E402
from services.spotify_coordinator import (  # noqa: E402
    SpotifyCoordinator,
    SpotifyLifecycle,
)
from services.spotify_orchestrator import (  # noqa: E402
    SpotifyOrchestrator,
    SpotifyOrchestratorError,
)


SYNTHETIC_KEY = "synthetic-key-never-retained-9c"
PRIVATE_DETAIL = "synthetic-private-dependency-detail"
PRIVATE_ENVIRONMENT_VALUE = "synthetic-private-environment"


class RecordingCoordinator:
    def __init__(self, events):
        self._coordinator = SpotifyCoordinator()
        self._events = events

    @property
    def state(self):
        return self._coordinator.state

    def status_snapshot(self):
        return self._coordinator.status_snapshot()

    def enter_standby(self):
        self._events.append("coordinator.enter_standby")
        return self._coordinator.enter_standby()

    def begin_acquisition(self):
        self._events.append("coordinator.begin_acquisition")
        return self._coordinator.begin_acquisition()

    def confirm_owned(self):
        self._events.append("coordinator.confirm_owned")
        return self._coordinator.confirm_owned()

    def cancel_recovery_without_spotify_claim(
        self,
        *,
        verified_no_spotify_claim,
    ):
        self._events.append(
            "coordinator.cancel_recovery_without_spotify_claim:"
            f"{verified_no_spotify_claim}"
        )
        return self._coordinator.cancel_recovery_without_spotify_claim(
            verified_no_spotify_claim=verified_no_spotify_claim
        )

    def begin_release(self):
        self._events.append("coordinator.begin_release")
        return self._coordinator.begin_release()

    def begin_recovery(self):
        self._events.append("coordinator.begin_recovery")
        return self._coordinator.begin_recovery()

    def complete_release(self, *, verified_safe):
        self._events.append(
            f"coordinator.complete_release:{verified_safe}"
        )
        return self._coordinator.complete_release(
            verified_safe=verified_safe
        )

    def complete_recovery(self, *, verified_safe):
        self._events.append(
            f"coordinator.complete_recovery:{verified_safe}"
        )
        return self._coordinator.complete_recovery(
            verified_safe=verified_safe
        )

    def mark_safe_error(self, *, verified_safe):
        self._events.append(
            f"coordinator.mark_safe_error:{verified_safe}"
        )
        return self._coordinator.mark_safe_error(
            verified_safe=verified_safe
        )

    def mark_unsafe_error(self):
        self._events.append("coordinator.mark_unsafe_error")
        return self._coordinator.mark_unsafe_error()

    def disable(self):
        self._events.append("coordinator.disable")
        return self._coordinator.disable()


class FakeSecretStore:
    def __init__(self, events):
        self._events = events
        self.configured = True
        self.key = SYNTHETIC_KEY
        self.fail_configured = False
        self.fail_get = False

    def key_configured(self):
        self._events.append("secret.key_configured")
        if self.fail_configured:
            raise RuntimeError(f"configured {PRIVATE_DETAIL}")
        return self.configured

    def get_api_key(self):
        self._events.append("secret.get_api_key")
        if self.fail_get:
            raise RuntimeError(f"get {PRIVATE_DETAIL}")
        return self.key


class FakeRuntime:
    def __init__(self, events):
        self._events = events
        self.pipewire_running = False
        self.wireplumber_running = False
        self.fail_start = False
        self.fail_environment = False
        self.fail_stop = False
        self.fail_status = False

    def start_private_graph(self):
        self._events.append("runtime.start")
        if self.fail_start:
            raise RuntimeError(f"runtime start {PRIVATE_DETAIL}")
        self.pipewire_running = True
        self.wireplumber_running = True
        return True

    def private_environment(self):
        self._events.append("runtime.environment")
        if self.fail_environment:
            raise RuntimeError(f"environment {PRIVATE_DETAIL}")
        return {"PRIVATE": PRIVATE_ENVIRONMENT_VALUE}

    def stop_private_graph(self):
        self._events.append("runtime.stop")
        if self.fail_stop:
            raise RuntimeError(f"runtime stop {PRIVATE_DETAIL}")
        self.pipewire_running = False
        self.wireplumber_running = False

    def status_snapshot(self):
        self._events.append("runtime.status")
        if self.fail_status:
            raise RuntimeError(f"runtime status {PRIVATE_DETAIL}")
        return {
            "pipewire_running": self.pipewire_running,
            "wireplumber_running": self.wireplumber_running,
        }


class FakeResolver:
    def __init__(self, events):
        self._events = events
        self.fail = False
        self.node_name = "synthetic.node"

    def resolve(self, *, card_number, device_number, environment):
        self._events.append(
            (
                "resolver.resolve",
                card_number,
                device_number,
                dict(environment),
            )
        )
        if self.fail:
            raise RuntimeError(f"resolver {PRIVATE_DETAIL}")
        return self.node_name


class FakePrearm:
    def __init__(self, events):
        self._events = events
        self.fail = False

    def prearm(
        self,
        *,
        card_number,
        device_number,
        pipewire_node_name,
        environment,
    ):
        self._events.append(
            (
                "prearm.prearm",
                card_number,
                device_number,
                pipewire_node_name,
                dict(environment),
            )
        )
        if self.fail:
            raise RuntimeError(f"prearm {PRIVATE_DETAIL}")


class FakeSoloist:
    def __init__(self, events):
        self._events = events
        self.running = False
        self.ready = False
        self.ws_port = 43123
        self.fail_start = False
        self.fail_stop = False
        self.fail_status = False
        self.fail_deactivate = False

    def start(
        self,
        *,
        api_key,
        device_name,
        pipewire_node_name,
        environment,
    ):
        self._events.append(
            (
                "soloist.start",
                api_key,
                device_name,
                pipewire_node_name,
                dict(environment),
            )
        )
        if self.fail_start:
            raise RuntimeError(f"soloist start {PRIVATE_DETAIL} {api_key}")
        self.running = True
        self.ready = True
        return True

    def deactivate(self):
        self._events.append("soloist.deactivate")
        if self.fail_deactivate:
            raise RuntimeError(
                f"soloist deactivate {PRIVATE_DETAIL}"
            )
        return True

    def stop(self):
        self._events.append("soloist.stop")
        if self.fail_stop:
            raise RuntimeError(f"soloist stop {PRIVATE_DETAIL}")
        self.running = False
        self.ready = False
        self.ws_port = None

    def status_snapshot(self):
        self._events.append("soloist.status")
        if self.fail_status:
            raise RuntimeError(f"soloist status {PRIVATE_DETAIL}")
        return {
            "soloist_running": self.running,
            "ready": self.ready,
            "ws_port": self.ws_port,
        }


class FakeObserver:
    def __init__(self, events):
        self._events = events
        self.running = False
        self.ready = False
        self.faulted = False
        self.is_active = False
        self.playback_status = None
        self.fail_start = False
        self.fail_stop = False
        self.fail_status = False
        self.status_override = None

    def start(self, *, ws_port):
        self._events.append(("observer.start", ws_port))
        if self.fail_start:
            raise RuntimeError(f"observer start {PRIVATE_DETAIL}")
        self.running = True
        self.ready = True
        self.faulted = False
        return True

    def stop(self):
        self._events.append("observer.stop")
        if self.fail_stop:
            raise RuntimeError(f"observer stop {PRIVATE_DETAIL}")
        self.running = False
        self.ready = False
        self.faulted = False
        self.is_active = None
        self.playback_status = None

    def status_snapshot(self):
        self._events.append("observer.status")
        if self.fail_status:
            raise RuntimeError(f"observer status {PRIVATE_DETAIL}")
        if self.status_override is not None:
            return dict(self.status_override)
        return {
            "observer_running": self.running,
            "ready": self.ready,
            "faulted": self.faulted,
            "is_active": self.is_active,
            "playback_status": self.playback_status,
        }


class FakePcmVerifier:
    def __init__(self, events):
        self._events = events
        self.is_free_values = deque([True])
        self.wait_values = deque([True])
        self.is_free_error = False
        self.wait_error = False
        self.absent = False
        self.absent_error = False

    @staticmethod
    def _next(values):
        return values.popleft() if len(values) > 1 else values[0]

    def is_free(self, *, card_number, device_number):
        self._events.append(("pcm.is_free", card_number, device_number))
        if self.is_free_error:
            raise RuntimeError(f"pcm is_free {PRIVATE_DETAIL}")
        return self._next(self.is_free_values)

    def wait_until_free(self, *, card_number, device_number):
        self._events.append(("pcm.wait_until_free", card_number, device_number))
        if self.wait_error:
            raise RuntimeError(f"pcm wait {PRIVATE_DETAIL}")
        return self._next(self.wait_values)

    def is_absent(self, *, card_number, device_number):
        if self.absent_error:
            raise RuntimeError(f"pcm absent {PRIVATE_DETAIL}")
        return self.absent


class System:
    pass


def _system(*, card=0, device=0, name="Synthetic Device"):
    system = System()
    system.events = []
    system.coordinator = RecordingCoordinator(system.events)
    system.secret = FakeSecretStore(system.events)
    system.runtime = FakeRuntime(system.events)
    system.resolver = FakeResolver(system.events)
    system.prearm = FakePrearm(system.events)
    system.soloist = FakeSoloist(system.events)
    system.observer = FakeObserver(system.events)
    system.pcm = FakePcmVerifier(system.events)
    system.orchestrator = SpotifyOrchestrator(
        coordinator=system.coordinator,
        secret_store=system.secret,
        runtime_supervisor=system.runtime,
        dac_resolver=system.resolver,
        pipewire_prearm=system.prearm,
        soloist_supervisor=system.soloist,
        observer=system.observer,
        pcm_verifier=system.pcm,
        card_number=card,
        device_number=device,
        device_name=name,
    )
    return system


def _expected_initial_status():
    return {
        "phase": "disabled",
        "endpoint_available": False,
        "coordinator_state": "disabled",
        "spotify_owner": False,
        "native_blocked": False,
        "observer_ready": False,
        "is_active": None,
        "playback_status": None,
    }


def _enable(system, *, active=False, playback=None):
    system.observer.is_active = active
    system.observer.playback_status = playback
    return system.orchestrator.enable()


def _set_state(system, state):
    coordinator = system.coordinator._coordinator
    if state is SpotifyLifecycle.DISABLED:
        return
    if state is SpotifyLifecycle.SAFE_ERROR:
        coordinator.mark_safe_error(verified_safe=True)
        return
    if state is SpotifyLifecycle.UNSAFE_ERROR:
        coordinator.mark_unsafe_error()
        return
    coordinator.enter_standby()
    if state is SpotifyLifecycle.STANDBY:
        return
    coordinator.begin_acquisition()
    if state is SpotifyLifecycle.ACQUIRING:
        return
    if state is SpotifyLifecycle.RECOVERING:
        coordinator.begin_recovery()
        return
    coordinator.confirm_owned()
    if state is SpotifyLifecycle.OWNED:
        return
    coordinator.begin_release()


def test_constructor_is_side_effect_free_with_exact_initial_status():
    system = _system()

    assert system.events == []
    assert system.orchestrator.status_snapshot() == _expected_initial_status()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("card_number", -1),
        ("card_number", True),
        ("card_number", 0.0),
        ("card_number", "0"),
        ("device_number", -1),
        ("device_number", False),
        ("device_number", 0.0),
        ("device_number", "0"),
        ("device_name", ""),
        ("device_name", "   "),
        ("device_name", 123),
    ],
)
def test_invalid_constructor_inputs_are_rejected(field, value):
    system = _system()
    values = {
        "coordinator": system.coordinator,
        "secret_store": system.secret,
        "runtime_supervisor": system.runtime,
        "dac_resolver": system.resolver,
        "pipewire_prearm": system.prearm,
        "soloist_supervisor": system.soloist,
        "observer": system.observer,
        "pcm_verifier": system.pcm,
        "card_number": 0,
        "device_number": 0,
        "device_name": "Device",
    }
    values[field] = value

    with pytest.raises(SpotifyOrchestratorError):
        SpotifyOrchestrator(**values)

    assert system.events == []


def test_enable_inactive_happy_path_has_exact_order_and_standby_status():
    system = _system(card=3, device=2, name="Living Room")

    assert _enable(system, active=False) is True

    assert system.events == [
        "secret.key_configured",
        "secret.get_api_key",
        "coordinator.mark_unsafe_error",
        "coordinator.begin_recovery",
        ("pcm.is_free", 3, 2),
        "runtime.start",
        "runtime.environment",
        (
            "resolver.resolve",
            3,
            2,
            {"PRIVATE": PRIVATE_ENVIRONMENT_VALUE},
        ),
        (
            "prearm.prearm",
            3,
            2,
            "synthetic.node",
            {"PRIVATE": PRIVATE_ENVIRONMENT_VALUE},
        ),
        (
            "soloist.start",
            SYNTHETIC_KEY,
            "Living Room",
            "synthetic.node",
            {"PRIVATE": PRIVATE_ENVIRONMENT_VALUE},
        ),
        "soloist.status",
        ("observer.start", 43123),
        "observer.status",
        ("pcm.is_free", 3, 2),
        "coordinator.complete_recovery:True",
    ]
    snapshot = system.orchestrator.status_snapshot()
    assert snapshot["phase"] == "standby"
    assert snapshot["endpoint_available"] is True
    assert snapshot["coordinator_state"] == "standby"
    assert snapshot["native_blocked"] is False


def test_enable_active_happy_path_finishes_owned_without_pcm_open_check():
    system = _system()

    assert _enable(system, active=True, playback="paused") is True

    assert system.coordinator.state is SpotifyLifecycle.OWNED
    assert "coordinator.complete_recovery:True" not in system.events
    assert "coordinator.begin_acquisition" not in system.events
    assert system.events[-1] == "coordinator.confirm_owned"
    snapshot = system.orchestrator.status_snapshot()
    assert snapshot["phase"] == "owned"
    assert snapshot["spotify_owner"] is True
    assert snapshot["native_blocked"] is True


@pytest.mark.parametrize("active", [False, True])
def test_repeated_enable_is_idempotent_for_healthy_endpoint(active):
    system = _system()
    _enable(system, active=active)
    system.events.clear()

    assert system.orchestrator.enable() is False

    assert "runtime.start" not in system.events
    assert "secret.key_configured" not in system.events
    assert not any(
        isinstance(event, tuple) and event[0] == "observer.start"
        for event in system.events
    )


@pytest.mark.parametrize("mode", ["not_configured", "missing", "error"])
def test_key_failure_has_no_runtime_side_effects(mode):
    system = _system()
    if mode == "not_configured":
        system.secret.configured = False
    elif mode == "missing":
        system.secret.key = None
    else:
        system.secret.fail_configured = True

    with pytest.raises(SpotifyOrchestratorError) as raised:
        system.orchestrator.enable()

    assert PRIVATE_DETAIL not in str(raised.value)
    assert "runtime.start" not in system.events
    assert system.coordinator.state is SpotifyLifecycle.DISABLED


@pytest.mark.parametrize("mode", ["busy", "error"])
def test_pcm_not_positively_free_prevents_endpoint_start(mode):
    system = _system()
    if mode == "busy":
        system.pcm.is_free_values = deque([False])
    else:
        system.pcm.is_free_error = True

    with pytest.raises(SpotifyOrchestratorError):
        system.orchestrator.enable()

    assert "runtime.start" not in system.events
    assert system.coordinator.state is SpotifyLifecycle.DISABLED
    assert system.orchestrator.status_snapshot()["endpoint_available"] is False


@pytest.mark.parametrize(
    "failure",
    [
        "runtime_start",
        "environment",
        "resolver",
        "prearm",
        "soloist_start",
        "soloist_status",
        "invalid_ws_port",
        "observer_start",
        "observer_unready",
        "observer_active_unknown",
    ],
)
@pytest.mark.parametrize("release_verified", [True, False])
def test_startup_failures_cleanup_and_end_in_safe_or_unsafe_error(
    failure,
    release_verified,
):
    system = _system()
    system.pcm.wait_values = deque([release_verified])
    if failure == "runtime_start":
        system.runtime.fail_start = True
    elif failure == "environment":
        system.runtime.fail_environment = True
    elif failure == "resolver":
        system.resolver.fail = True
    elif failure == "prearm":
        system.prearm.fail = True
    elif failure == "soloist_start":
        system.soloist.fail_start = True
    elif failure == "soloist_status":
        system.soloist.fail_status = True
    elif failure == "invalid_ws_port":
        system.soloist.ws_port = 0
    elif failure == "observer_start":
        system.observer.fail_start = True
    elif failure == "observer_unready":
        system.observer.status_override = {
            "observer_running": True,
            "ready": False,
            "faulted": False,
            "is_active": False,
        }
    else:
        system.observer.is_active = None

    with pytest.raises(SpotifyOrchestratorError) as raised:
        system.orchestrator.enable()

    assert PRIVATE_DETAIL not in str(raised.value)
    cleanup = [
        event
        for event in system.events
        if (
            isinstance(event, str)
            and event in {"observer.stop", "soloist.stop", "runtime.stop"}
        )
        or (isinstance(event, tuple) and event[0] == "pcm.wait_until_free")
    ]
    assert cleanup == [
        "observer.stop",
        "soloist.stop",
        "runtime.stop",
        ("pcm.wait_until_free", 0, 0),
    ]
    expected = (
        SpotifyLifecycle.SAFE_ERROR
        if release_verified
        else SpotifyLifecycle.UNSAFE_ERROR
    )
    assert system.coordinator.state is expected


def test_cleanup_failure_still_attempts_every_component_and_blocks_native():
    system = _system()
    system.resolver.fail = True
    system.observer.fail_stop = True
    system.pcm.wait_values = deque([True])

    with pytest.raises(SpotifyOrchestratorError):
        system.orchestrator.enable()

    assert "observer.stop" in system.events
    assert "soloist.stop" in system.events
    assert "runtime.stop" in system.events
    assert ("pcm.wait_until_free", 0, 0) in system.events
    assert system.coordinator.state is SpotifyLifecycle.UNSAFE_ERROR
    assert system.orchestrator.status_snapshot()["native_blocked"] is True


def test_prearm_failure_never_starts_soloist_and_uses_cleanup_order():
    system = _system()
    system.prearm.fail = True

    with pytest.raises(SpotifyOrchestratorError):
        system.orchestrator.enable()

    assert not any(
        isinstance(event, tuple) and event[0] == "soloist.start"
        for event in system.events
    )
    cleanup = [
        event
        for event in system.events
        if (
            isinstance(event, str)
            and event in {"observer.stop", "soloist.stop", "runtime.stop"}
        )
        or (isinstance(event, tuple) and event[0] == "pcm.wait_until_free")
    ]
    assert cleanup == [
        "observer.stop",
        "soloist.stop",
        "runtime.stop",
        ("pcm.wait_until_free", 0, 0),
    ]
    assert system.coordinator.state is SpotifyLifecycle.SAFE_ERROR


def test_reconcile_standby_inactive_is_noop():
    system = _system()
    _enable(system, active=False)
    system.events.clear()

    assert system.orchestrator.reconcile() is False
    assert system.coordinator.state is SpotifyLifecycle.STANDBY


def test_reconcile_standby_active_acquires_ownership():
    system = _system()
    _enable(system, active=False)
    system.observer.is_active = True
    system.events.clear()

    assert system.orchestrator.reconcile() is True

    assert system.events[-2:] == [
        "coordinator.begin_acquisition",
        "coordinator.confirm_owned",
    ]
    assert system.coordinator.state is SpotifyLifecycle.OWNED


@pytest.mark.parametrize("verified", [True, False])
def test_reconcile_standby_health_loss_recovers_fail_closed(verified):
    system = _system()
    _enable(system, active=False)
    system.observer.faulted = True
    system.pcm.wait_values = deque([verified])
    system.events.clear()

    assert system.orchestrator.reconcile() is True

    assert system.events.index("coordinator.mark_unsafe_error") < system.events.index(
        "observer.stop"
    )
    assert system.coordinator.state is (
        SpotifyLifecycle.SAFE_ERROR
        if verified
        else SpotifyLifecycle.UNSAFE_ERROR
    )


@pytest.mark.parametrize("playback", ["playing", "paused", "buffering"])
def test_active_owned_remains_owned_regardless_of_playback_status(playback):
    system = _system()
    _enable(system, active=True, playback=playback)
    system.observer.playback_status = playback
    system.events.clear()

    assert system.orchestrator.reconcile() is False
    assert system.coordinator.state is SpotifyLifecycle.OWNED
    assert system.orchestrator.status_snapshot()["native_blocked"] is True


def test_owned_inactive_waits_for_pcm_before_completing_release():
    system = _system()
    _enable(system, active=True)
    system.observer.is_active = False
    system.events.clear()

    assert system.orchestrator.reconcile() is True

    assert system.events == [
        "runtime.status",
        "soloist.status",
        "observer.status",
        "coordinator.begin_release",
        ("pcm.wait_until_free", 0, 0),
        "coordinator.complete_release:True",
    ]
    assert system.coordinator.state is SpotifyLifecycle.STANDBY
    assert system.runtime.pipewire_running is True
    assert system.orchestrator.status_snapshot()["endpoint_available"] is True


@pytest.mark.parametrize("recovery_verified", [True, False])
def test_owned_release_failure_tears_down_and_recovers(recovery_verified):
    system = _system()
    _enable(system, active=True)
    system.observer.is_active = False
    system.pcm.wait_values = deque([False, recovery_verified])
    system.events.clear()

    assert system.orchestrator.reconcile() is True

    assert system.events[:3] == [
        "runtime.status",
        "soloist.status",
        "observer.status",
    ]
    assert "coordinator.begin_release" in system.events
    first_wait = system.events.index(("pcm.wait_until_free", 0, 0))
    recovery = system.events.index("coordinator.begin_recovery")
    cleanup = system.events.index("observer.stop")
    assert first_wait < recovery < cleanup
    assert system.coordinator.state is (
        SpotifyLifecycle.SAFE_ERROR
        if recovery_verified
        else SpotifyLifecycle.UNSAFE_ERROR
    )


@pytest.mark.parametrize(
    "failure",
    ["observer", "soloist", "pipewire", "wireplumber"],
)
def test_owned_component_health_loss_enters_recovery(failure):
    system = _system()
    _enable(system, active=True)
    if failure == "observer":
        system.observer.running = False
    elif failure == "soloist":
        system.soloist.running = False
    elif failure == "pipewire":
        system.runtime.pipewire_running = False
    else:
        system.runtime.wireplumber_running = False
    system.events.clear()

    assert system.orchestrator.reconcile() is True
    assert "coordinator.begin_recovery" in system.events
    assert system.coordinator.state is SpotifyLifecycle.SAFE_ERROR


def test_disabled_reconcile_does_not_enable_endpoint():
    system = _system()

    assert system.orchestrator.reconcile() is False

    assert "secret.key_configured" not in system.events
    assert "runtime.start" not in system.events


def test_safe_error_reconcile_does_not_restart_endpoint():
    system = _system()
    _set_state(system, SpotifyLifecycle.SAFE_ERROR)
    system.events.clear()

    assert system.orchestrator.reconcile() is False
    assert "runtime.start" not in system.events


@pytest.mark.parametrize("verified", [True, False])
def test_unsafe_error_reconcile_attempts_bounded_recovery(verified):
    system = _system()
    _set_state(system, SpotifyLifecycle.UNSAFE_ERROR)
    system.pcm.wait_values = deque([verified])
    system.events.clear()

    assert system.orchestrator.reconcile() is True
    assert system.events[0] == "coordinator.begin_recovery"
    assert system.coordinator.state is (
        SpotifyLifecycle.SAFE_ERROR
        if verified
        else SpotifyLifecycle.UNSAFE_ERROR
    )


@pytest.mark.parametrize(
    "state",
    [
        SpotifyLifecycle.ACQUIRING,
        SpotifyLifecycle.RELEASING,
        SpotifyLifecycle.RECOVERING,
    ],
)
def test_transitional_reconcile_recovers_conservatively(state):
    system = _system()
    _set_state(system, state)
    system.events.clear()

    assert system.orchestrator.reconcile() is True
    assert system.coordinator.state is SpotifyLifecycle.SAFE_ERROR


def test_disable_is_idempotent_when_already_cleanly_disabled():
    system = _system()

    assert system.orchestrator.disable() is False
    assert "observer.stop" not in system.events


@pytest.mark.parametrize("owned", [False, True])
def test_disable_withdraws_endpoint_and_verifies_release(owned):
    system = _system()
    _enable(system, active=owned)
    system.events.clear()

    assert system.orchestrator.disable() is True

    assert system.events.index("observer.stop") < system.events.index(
        "soloist.stop"
    ) < system.events.index("runtime.stop")
    assert system.events.index("runtime.stop") < system.events.index(
        ("pcm.wait_until_free", 0, 0)
    )
    assert system.coordinator.state is SpotifyLifecycle.DISABLED
    assert system.orchestrator.status_snapshot()["native_blocked"] is False


def test_disable_safe_error_performs_defensive_cleanup_then_disables():
    system = _system()
    _set_state(system, SpotifyLifecycle.SAFE_ERROR)
    system.events.clear()

    assert system.orchestrator.disable() is True
    assert system.coordinator.state is SpotifyLifecycle.DISABLED
    assert "observer.stop" in system.events


@pytest.mark.parametrize("mode", ["busy", "error", "cleanup_failure"])
def test_disable_cannot_reach_disabled_without_safe_cleanup(mode):
    system = _system()
    _enable(system, active=True)
    system.events.clear()
    if mode == "busy":
        system.pcm.wait_values = deque([False])
    elif mode == "error":
        system.pcm.wait_error = True
    else:
        system.observer.fail_stop = True

    with pytest.raises(SpotifyOrchestratorError):
        system.orchestrator.disable()

    assert system.coordinator.state is SpotifyLifecycle.UNSAFE_ERROR
    assert system.orchestrator.status_snapshot()["native_blocked"] is True


@pytest.mark.parametrize("mode", ["free", "busy", "error"])
def test_prepare_native_claim_from_disabled_requires_positive_pcm(mode):
    system = _system()
    if mode == "busy":
        system.pcm.is_free_values = deque([False])
    elif mode == "error":
        system.pcm.is_free_error = True

    result = system.orchestrator.prepare_native_claim()

    assert result is (mode == "free")
    assert system.coordinator.state is (
        SpotifyLifecycle.DISABLED
        if mode == "free"
        else SpotifyLifecycle.UNSAFE_ERROR
    )


def test_prepare_native_claim_withdraws_inactive_standby_endpoint():
    system = _system()
    _enable(system, active=False)
    system.events.clear()

    assert system.orchestrator.prepare_native_claim() is True

    assert "observer.stop" in system.events
    assert "soloist.stop" in system.events
    assert "runtime.stop" in system.events
    assert ("pcm.wait_until_free", 0, 0) in system.events
    assert system.coordinator.state is SpotifyLifecycle.DISABLED


def test_prepare_native_claim_detects_pending_active_standby():
    system = _system()
    _enable(system, active=False)
    system.observer.is_active = True
    system.events.clear()

    assert system.orchestrator.prepare_native_claim() is False
    assert system.coordinator.state is SpotifyLifecycle.OWNED
    assert system.orchestrator.status_snapshot()["native_blocked"] is True


def test_prepare_native_claim_owned_paused_remains_blocked():
    system = _system()
    _enable(system, active=True, playback="paused")

    assert system.orchestrator.prepare_native_claim() is False
    assert system.coordinator.state is SpotifyLifecycle.OWNED


@pytest.mark.parametrize(
    "state",
    [
        SpotifyLifecycle.ACQUIRING,
        SpotifyLifecycle.RELEASING,
        SpotifyLifecycle.RECOVERING,
        SpotifyLifecycle.UNSAFE_ERROR,
    ],
)
def test_prepare_native_claim_rejects_blocked_or_uncertain_states(state):
    system = _system()
    _set_state(system, state)
    system.events.clear()

    assert system.orchestrator.prepare_native_claim() is False
    assert system.coordinator.state is state


def test_prepare_native_claim_safe_error_cleans_and_disables():
    system = _system()
    _set_state(system, SpotifyLifecycle.SAFE_ERROR)
    system.events.clear()

    assert system.orchestrator.prepare_native_claim() is True
    assert system.coordinator.state is SpotifyLifecycle.DISABLED


@pytest.mark.parametrize("mode", ["cleanup", "pcm"])
def test_prepare_native_claim_uncertainty_returns_false_and_blocks_native(mode):
    system = _system()
    _enable(system, active=False)
    system.events.clear()
    if mode == "cleanup":
        system.soloist.fail_stop = True
    else:
        system.pcm.wait_error = True

    assert system.orchestrator.prepare_native_claim() is False
    assert system.coordinator.state is SpotifyLifecycle.UNSAFE_ERROR
    assert system.orchestrator.status_snapshot()["native_blocked"] is True


def test_secret_and_launch_environment_are_never_retained_or_exposed():
    system = _system()
    _enable(system, active=False)

    assert SYNTHETIC_KEY not in repr(system.orchestrator.__dict__)
    assert PRIVATE_ENVIRONMENT_VALUE not in repr(system.orchestrator.__dict__)
    assert SYNTHETIC_KEY not in repr(system.orchestrator.status_snapshot())
    assert PRIVATE_ENVIRONMENT_VALUE not in repr(
        system.orchestrator.status_snapshot()
    )


def test_dependency_failure_detail_is_absent_from_public_exception():
    system = _system()
    system.runtime.fail_start = True

    with pytest.raises(SpotifyOrchestratorError) as raised:
        system.orchestrator.enable()

    assert PRIVATE_DETAIL not in str(raised.value)
    assert SYNTHETIC_KEY not in str(raised.value)


def test_status_schema_is_exact_and_allowlisted():
    system = _system()
    _enable(system, active=False, playback="stopped")

    snapshot = system.orchestrator.status_snapshot()

    assert set(snapshot) == {
        "phase",
        "endpoint_available",
        "coordinator_state",
        "spotify_owner",
        "native_blocked",
        "observer_ready",
        "is_active",
        "playback_status",
    }
    assert snapshot["endpoint_available"] is True
    forbidden = (
        "ws_port",
        "pid",
        "command",
        "environment",
        "node",
        "path",
        "secret",
        "key",
    )
    assert not any(token in repr(snapshot).lower() for token in forbidden)


@pytest.mark.parametrize("dependency", ["runtime", "soloist", "observer"])
def test_status_dependency_failure_is_generic_and_fail_closed(dependency):
    system = _system()
    _enable(system, active=False)
    setattr(getattr(system, dependency), "fail_status", True)

    snapshot = system.orchestrator.status_snapshot()

    assert snapshot["endpoint_available"] is False
    assert PRIVATE_DETAIL not in repr(snapshot)
    assert snapshot["is_active"] is None


def test_invalid_coordinator_status_fails_closed_without_throwing():
    system = _system()
    system.coordinator.status_snapshot = lambda: (_ for _ in ()).throw(
        RuntimeError(PRIVATE_DETAIL)
    )

    snapshot = system.orchestrator.status_snapshot()

    assert snapshot["phase"] == "unsafe_error"
    assert snapshot["coordinator_state"] == "unsafe_error"
    assert snapshot["native_blocked"] is True
    assert PRIVATE_DETAIL not in repr(snapshot)


def test_public_surface_has_no_credential_or_restore_parameter():
    public = {
        name: inspect.signature(getattr(SpotifyOrchestrator, name))
        for name in (
            "enable",
            "disable",
            "reconcile",
            "prepare_native_claim",
            "status_snapshot",
        )
    }

    assert all(
        set(signature.parameters) == {"self"}
        for signature in public.values()
    )


def test_component_has_no_forbidden_mechanism_or_integration_references():
    source = Path(orchestrator_module.__file__).read_text(encoding="utf-8").lower()
    forbidden = (
        "main_headless",
        "import subprocess",
        "fuser",
        "lsof",
        '"/proc',
        "http",
        "firewall",
        "ufw",
        "tailscale",
        "websocket",
        "socket",
        "os.system",
        "shell=true",
        "threading.thread",
        "package",
        "install",
        "download",
    )
    assert not any(token in source for token in forbidden)
    assert "wait_until_free" in source
    assert "is_free" in source


def _sp2c9c3_startup_fixture(*, active, coordinator=None):
    from services.spotify_coordinator import SpotifyCoordinator
    from services.spotify_orchestrator import SpotifyOrchestrator

    events = []

    if coordinator is None:
        coordinator = SpotifyCoordinator()

    class Secret:
        def key_configured(self):
            events.append("key_configured")
            return True

        def get_api_key(self):
            events.append("get_api_key")
            return "SP2C9C3-SYNTHETIC-NOT-REAL"

    class Runtime:
        def __init__(self):
            self.started = False

        def start_private_graph(self):
            events.append("runtime_start")
            self.started = True
            return True

        def private_environment(self):
            events.append("runtime_environment")
            return {"SP2C9C3": "1"}

        def stop_private_graph(self):
            events.append("runtime_stop")
            self.started = False

        def status_snapshot(self):
            return {
                "pipewire_running": self.started,
                "wireplumber_running": self.started,
            }

    class Resolver:
        def resolve(self, **_kwargs):
            events.append("resolve")
            return "sp2c9c3-synthetic-sink"

    class Prearm:
        def prearm(self, **_kwargs):
            events.append("prearm")

    class Soloist:
        def __init__(self):
            self.started = False

        def start(self, **_kwargs):
            events.append("soloist_start")
            self.started = True
            return True

        def stop(self):
            events.append("soloist_stop")
            self.started = False

        def status_snapshot(self):
            return {
                "soloist_running": self.started,
                "ready": self.started,
                "ws_port": 12345 if self.started else None,
            }

    class Observer:
        def __init__(self):
            self.started = False

        def start(self, **_kwargs):
            events.append("observer_start")
            self.started = True
            return True

        def stop(self):
            events.append("observer_stop")
            self.started = False

        def status_snapshot(self):
            events.append("observer_status")
            return {
                "observer_running": self.started,
                "ready": self.started,
                "faulted": False,
                "logged_in": True,
                "is_active": active,
                "playback_status": (
                    "paused" if active else None
                ),
                "device_name": "SP2C9C3 Synthetic",
                "last_event_type": "auth_state",
                "event_sequence": 1,
            }

    class Pcm:
        def __init__(self):
            self.is_free_calls = 0
            self.wait_calls = 0
            self.native_blocked_at_probe = []

        def is_free(self, **_kwargs):
            self.is_free_calls += 1
            self.native_blocked_at_probe.append(
                coordinator.native_blocked
            )
            events.append(
                "pcm_is_free_"
                + str(self.is_free_calls)
            )
            return True

        def wait_until_free(self, **_kwargs):
            self.wait_calls += 1
            events.append(
                "pcm_wait_"
                + str(self.wait_calls)
            )
            return True

    runtime = Runtime()
    soloist = Soloist()
    observer = Observer()
    pcm = Pcm()

    orchestrator = SpotifyOrchestrator(
        coordinator=coordinator,
        secret_store=Secret(),
        runtime_supervisor=runtime,
        dac_resolver=Resolver(),
        pipewire_prearm=Prearm(),
        soloist_supervisor=soloist,
        observer=observer,
        pcm_verifier=pcm,
        card_number=0,
        device_number=0,
        device_name="SP2C9C3 Synthetic",
    )

    return orchestrator, coordinator, pcm, events


def test_sp2c9c3_startup_blocks_native_before_first_pcm_probe():
    from services.spotify_coordinator import SpotifyLifecycle

    orchestrator, coordinator, pcm, events = (
        _sp2c9c3_startup_fixture(active=False)
    )

    assert orchestrator.enable() is True

    assert coordinator.state is SpotifyLifecycle.STANDBY

    # One probe before process construction and one fresh probe after
    # observer readiness. Native must remain blocked for both.
    assert pcm.is_free_calls == 2
    assert pcm.native_blocked_at_probe == [True, True]

    assert events.index("pcm_is_free_1") < events.index(
        "runtime_start"
    )

    assert events.index("observer_status") < events.index(
        "pcm_is_free_2"
    )


def test_sp2c9c3_active_startup_never_enters_native_safe_standby():
    from services.spotify_coordinator import (
        SpotifyCoordinator,
        SpotifyLifecycle,
    )

    class ProbeCoordinator(SpotifyCoordinator):
        def __init__(self):
            super().__init__()
            self.complete_recovery_calls = 0
            self.confirm_owned_before = None
            self.confirm_owned_before_blocked = None
            self.confirm_owned_after = None
            self.confirm_owned_after_blocked = None

        def complete_recovery(self, *, verified_safe):
            self.complete_recovery_calls += 1
            return super().complete_recovery(
                verified_safe=verified_safe
            )

        def confirm_owned(self):
            self.confirm_owned_before = self.state
            self.confirm_owned_before_blocked = (
                self.native_blocked
            )

            result = super().confirm_owned()

            self.confirm_owned_after = self.state
            self.confirm_owned_after_blocked = (
                self.native_blocked
            )

            return result

    coordinator = ProbeCoordinator()

    orchestrator, _coordinator, pcm, _events = (
        _sp2c9c3_startup_fixture(
            active=True,
            coordinator=coordinator,
        )
    )

    assert orchestrator.enable() is True

    assert coordinator.complete_recovery_calls == 0

    assert (
        coordinator.confirm_owned_before
        is SpotifyLifecycle.RECOVERING
    )
    assert coordinator.confirm_owned_before_blocked is True

    assert (
        coordinator.confirm_owned_after
        is SpotifyLifecycle.OWNED
    )
    assert coordinator.confirm_owned_after_blocked is True

    assert coordinator.native_blocked is True
    assert coordinator.can_native_play() is False

    # Active ownership does not require a second PCM-free probe.
    assert pcm.is_free_calls == 1


def test_sp2c9c3_inactive_startup_rechecks_pcm_after_observer_ready():
    from services.spotify_coordinator import SpotifyLifecycle

    orchestrator, coordinator, pcm, events = (
        _sp2c9c3_startup_fixture(active=False)
    )

    assert orchestrator.enable() is True

    assert pcm.is_free_calls == 2

    observer_index = events.index("observer_status")
    second_pcm_index = events.index("pcm_is_free_2")

    assert observer_index < second_pcm_index

    assert coordinator.state is SpotifyLifecycle.STANDBY
    assert coordinator.native_blocked is False
    assert coordinator.can_native_play() is True


def test_sp2c9c5_initial_pcm_busy_rolls_back_without_endpoint_cleanup():
    from services.spotify_coordinator import SpotifyLifecycle
    from services.spotify_orchestrator import SpotifyOrchestratorError

    orchestrator, coordinator, pcm, events = (
        _sp2c9c3_startup_fixture(active=False)
    )

    def busy_pcm(**_kwargs):
        pcm.is_free_calls += 1
        pcm.native_blocked_at_probe.append(
            coordinator.native_blocked
        )
        events.append(
            "pcm_is_free_" + str(pcm.is_free_calls)
        )
        return False

    pcm.is_free = busy_pcm

    with pytest.raises(SpotifyOrchestratorError):
        orchestrator.enable()

    assert coordinator.state is SpotifyLifecycle.DISABLED
    assert coordinator.native_blocked is False
    assert coordinator.can_native_play() is True

    assert pcm.is_free_calls == 1
    assert pcm.wait_calls == 0
    assert pcm.native_blocked_at_probe == [True]

    assert "runtime_start" not in events
    assert "runtime_stop" not in events
    assert "soloist_start" not in events
    assert "soloist_stop" not in events
    assert "observer_start" not in events
    assert "observer_stop" not in events


# BF4_ABSENT_DAC_SAFE_RETIREMENT
def test_unsafe_error_can_disable_when_pcm_absent_and_all_managed_runtime_gone():
    system = _system()
    _set_state(system, SpotifyLifecycle.UNSAFE_ERROR)
    system.pcm.wait_error = True
    system.pcm.absent = True
    system.events.clear()

    assert system.orchestrator.disable() is True
    assert system.coordinator.state is SpotifyLifecycle.DISABLED
    status = system.coordinator.status_snapshot()
    assert status["spotify_owner"] is False
    assert status["native_blocked"] is False


def test_absent_pcm_does_not_unlock_when_managed_absence_cannot_be_verified():
    system = _system()
    _set_state(system, SpotifyLifecycle.UNSAFE_ERROR)
    system.pcm.wait_error = True
    system.pcm.absent = True
    system.runtime.fail_status = True
    system.events.clear()

    with pytest.raises(SpotifyOrchestratorError):
        system.orchestrator.disable()

    assert system.coordinator.state is SpotifyLifecycle.UNSAFE_ERROR
    assert system.coordinator.status_snapshot()["native_blocked"] is True


def test_owned_deactivate_requests_soloist_release_without_premature_unblock():
    system = _system()
    _enable(system, active=True, playback="playing")
    system.events.clear()

    assert system.orchestrator.deactivate() is True

    assert system.events == ["soloist.deactivate"]
    assert system.coordinator.state is SpotifyLifecycle.OWNED
    snapshot = system.orchestrator.status_snapshot()
    assert snapshot["spotify_owner"] is True
    assert snapshot["native_blocked"] is True


def test_deactivate_then_observed_inactive_uses_existing_verified_release_path():
    system = _system()
    _enable(system, active=True, playback="playing")
    system.events.clear()

    assert system.orchestrator.deactivate() is True
    system.observer.is_active = False

    assert system.orchestrator.reconcile() is True
    assert system.coordinator.state is SpotifyLifecycle.STANDBY
    snapshot = system.orchestrator.status_snapshot()
    assert snapshot["spotify_owner"] is False
    assert snapshot["native_blocked"] is False
    assert system.soloist.running is True


def test_standby_deactivate_is_idempotent_without_soloist_control():
    system = _system()
    _enable(system, active=False)
    system.events.clear()

    assert system.orchestrator.deactivate() is False
    assert "soloist.deactivate" not in system.events
    assert system.coordinator.state is SpotifyLifecycle.STANDBY
