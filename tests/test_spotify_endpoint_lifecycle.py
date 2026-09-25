import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services.spotify_endpoint_lifecycle import (  # noqa: E402
    SpotifyEndpointLifecycle,
    SpotifyEndpointLifecycleError,
)


STATUS = {
    "phase": "standby",
    "endpoint_available": True,
    "coordinator_state": "standby",
    "spotify_owner": False,
    "native_blocked": False,
    "observer_ready": True,
    "is_active": False,
    "playback_status": None,
}


class Inner:
    def __init__(self, events):
        self.events = events
        self.status = dict(STATUS)
        self.enable_changed = True
        self.disable_changed = True
        self.reconcile_changed = False
        self.reconcile_endpoint_available = None
        self.native_result = True
        self.deactivate_changed = True
        self.fail_disable = False
        self.fail_deactivate = False
        self.fail_native_prepare = False

    def enable(self):
        self.events.append("inner.enable")
        return self.enable_changed

    def disable(self):
        self.events.append("inner.disable")
        if self.fail_disable:
            raise RuntimeError("private inner detail")
        self.status["endpoint_available"] = False
        return self.disable_changed

    def deactivate(self):
        self.events.append("inner.deactivate")
        if self.fail_deactivate:
            raise RuntimeError("private inner deactivate detail")
        return self.deactivate_changed

    def reconcile(self):
        self.events.append("inner.reconcile")
        if self.reconcile_endpoint_available is not None:
            self.status["endpoint_available"] = self.reconcile_endpoint_available
        return self.reconcile_changed

    def prepare_native_claim(self):
        self.events.append("inner.prepare_native_claim")
        if self.fail_native_prepare:
            raise RuntimeError("private inner native detail")
        return self.native_result

    def status_snapshot(self):
        self.events.append("inner.status")
        return dict(self.status)


class Network:
    def __init__(self, events):
        self.events = events
        self.fail_activate = False
        self.fail_preflight = False
        self.fail_release = False
        self.fail_cleanup = False
        self.active = False

    def preflight(self):
        self.events.append("network.preflight")
        if self.fail_preflight:
            raise RuntimeError("private preflight detail")
        return False

    def activate(self):
        self.events.append("network.activate")
        if self.fail_activate:
            raise RuntimeError("private network detail")
        changed = not self.active
        self.active = True
        return changed

    def release(self):
        self.events.append("network.release")
        if self.fail_release:
            raise RuntimeError("private network release")
        changed = self.active
        self.active = False
        return changed

    def cleanup_stale(self):
        self.events.append("network.cleanup")
        if self.fail_cleanup:
            raise RuntimeError("private cleanup detail")
        self.active = False
        return True


def _lifecycle():
    events = []
    inner = Inner(events)
    network = Network(events)
    lifecycle = SpotifyEndpointLifecycle(
        orchestrator=inner,
        network_access=network,
    )
    return lifecycle, inner, network, events


def test_enable_exact_order_holds_network_barrier_before_reconcile():
    lifecycle, _inner, _network, events = _lifecycle()

    assert lifecycle.enable() is True
    assert events == [
        "network.preflight",
        "inner.enable",
        "network.activate",
        "inner.reconcile",
        "inner.status",
    ]


def test_enable_withdraws_lease_when_final_reconcile_removes_endpoint():
    lifecycle, inner, network, events = _lifecycle()
    inner.reconcile_endpoint_available = False

    with pytest.raises(SpotifyEndpointLifecycleError) as raised:
        lifecycle.enable()

    assert "private" not in str(raised.value)
    assert events == [
        "network.preflight",
        "inner.enable",
        "network.activate",
        "inner.reconcile",
        "inner.status",
        "network.release",
        "network.cleanup",
        "inner.disable",
    ]
    assert events.count("network.cleanup") == 1
    assert network.active is False
    snapshot = lifecycle.status_snapshot()
    assert snapshot["endpoint_available"] is False
    rendered = repr(snapshot).lower()
    for forbidden in ("pid", "port", "interface", "cidr", "private"):
        assert forbidden not in rendered


def test_activation_failure_releases_and_always_withdraws_inner_endpoint():
    lifecycle, inner, network, events = _lifecycle()
    network.fail_activate = True

    with pytest.raises(SpotifyEndpointLifecycleError) as raised:
        lifecycle.enable()

    assert "private" not in str(raised.value)
    assert events == [
        "network.preflight",
        "inner.enable",
        "network.activate",
        "network.release",
        "network.cleanup",
        "inner.disable",
    ]
    assert inner.status["endpoint_available"] is False
    assert lifecycle.status_snapshot()["endpoint_available"] is False


def test_preflight_failure_never_calls_inner_enable():
    lifecycle, _inner, network, events = _lifecycle()
    network.fail_preflight = True

    with pytest.raises(SpotifyEndpointLifecycleError):
        lifecycle.enable()

    assert "inner.enable" not in events
    assert events == [
        "network.preflight",
        "network.release",
        "network.cleanup",
        "inner.disable",
    ]


def test_release_occurs_before_inner_disable():
    lifecycle, _inner, network, events = _lifecycle()
    network.active = True

    assert lifecycle.disable() is True
    assert events[:2] == ["network.release", "inner.disable"]


def test_inner_disable_runs_and_cleanup_retries_when_release_fails():
    lifecycle, inner, network, events = _lifecycle()
    network.fail_release = True

    assert lifecycle.disable() is True
    assert events == ["network.release", "inner.disable", "network.cleanup"]
    assert inner.status["coordinator_state"] == "standby"


def test_cleanup_failure_after_audio_safe_raises_only_outer_error():
    lifecycle, inner, network, events = _lifecycle()
    network.fail_release = True
    network.fail_cleanup = True

    with pytest.raises(SpotifyEndpointLifecycleError):
        lifecycle.disable()

    assert "inner.disable" in events
    assert inner.status["coordinator_state"] == "standby"
    assert inner.status["endpoint_available"] is False


def test_rejected_native_claim_preserves_active_endpoint_network_lease():
    lifecycle, inner, network, events = _lifecycle()
    inner.native_result = False
    network.active = True

    assert lifecycle.prepare_native_claim() is False
    assert events == ["inner.prepare_native_claim"]
    assert network.active is True


def test_approved_native_claim_releases_network_after_inner_authority():
    lifecycle, _inner, network, events = _lifecycle()
    network.active = True

    assert lifecycle.prepare_native_claim() is True
    assert events == ["inner.prepare_native_claim", "network.release"]
    assert network.active is False


def test_approved_native_claim_survives_release_failure_after_cleanup():
    lifecycle, _inner, network, events = _lifecycle()
    network.fail_release = True

    assert lifecycle.prepare_native_claim() is True
    assert events == [
        "inner.prepare_native_claim",
        "network.release",
        "network.cleanup",
    ]


def test_approved_native_claim_survives_all_network_cleanup_failures():
    lifecycle, _inner, network, events = _lifecycle()
    network.fail_release = True
    network.fail_cleanup = True

    assert lifecycle.prepare_native_claim() is True
    assert events == [
        "inner.prepare_native_claim",
        "network.release",
        "network.cleanup",
    ]
    rendered = repr(lifecycle.status_snapshot()).lower()
    assert "private network" not in rendered


def test_inner_native_claim_failure_is_sanitized_and_never_withdraws_network():
    lifecycle, inner, network, events = _lifecycle()
    inner.fail_native_prepare = True
    network.active = True

    with pytest.raises(SpotifyEndpointLifecycleError) as raised:
        lifecycle.prepare_native_claim()

    assert str(raised.value) == "Spotify native claim preparation failed"
    assert "private" not in str(raised.value)
    assert events == ["inner.prepare_native_claim"]
    assert network.active is True


def test_reconcile_absent_endpoint_releases_without_activation():
    lifecycle, inner, network, events = _lifecycle()
    inner.status["endpoint_available"] = False
    network.active = True

    assert lifecycle.reconcile() is True
    assert events == ["inner.reconcile", "inner.status", "network.release"]
    assert "network.activate" not in events


def test_repeated_enable_and_disable_are_idempotent():
    lifecycle, inner, _network, _events = _lifecycle()
    assert lifecycle.enable() is True
    inner.enable_changed = False
    assert lifecycle.enable() is False
    assert lifecycle.disable() is True
    inner.disable_changed = False
    assert lifecycle.disable() is False


def test_status_key_set_is_exact_and_contains_no_network_or_secret_fields():
    lifecycle, _inner, _network, _events = _lifecycle()

    snapshot = lifecycle.status_snapshot()

    assert set(snapshot) == set(STATUS)
    rendered = repr(snapshot).lower()
    for forbidden in ("pid", "port", "interface", "cidr", "firewall", "secret", "api"):
        assert forbidden not in rendered


def test_first_retire_disables_safely_and_seals_lifecycle():
    lifecycle, _inner, network, events = _lifecycle()
    network.active = True

    assert lifecycle.retire() is True
    assert events == ["network.release", "inner.disable"]
    assert network.active is False

    events.clear()
    with pytest.raises(SpotifyEndpointLifecycleError) as raised:
        lifecycle.enable()
    assert str(raised.value) == "Spotify endpoint lifecycle is retired"
    assert events == []


def test_repeated_retire_is_idempotent_without_side_effects():
    lifecycle, _inner, _network, events = _lifecycle()
    assert lifecycle.retire() is True
    events.clear()

    assert lifecycle.retire() is False
    assert events == []


def test_retirement_failure_does_not_seal_lifecycle():
    lifecycle, _inner, network, events = _lifecycle()
    network.fail_release = True
    network.fail_cleanup = True

    with pytest.raises(SpotifyEndpointLifecycleError) as raised:
        lifecycle.retire()
    assert str(raised.value) == "Spotify endpoint could not be retired safely"

    network.fail_release = False
    network.fail_cleanup = False
    events.clear()
    assert lifecycle.retire() is True
    assert events == ["network.release", "inner.disable"]


def test_retired_operations_are_inert_and_native_claim_is_safe():
    lifecycle, _inner, _network, events = _lifecycle()
    assert lifecycle.retire() is True
    events.clear()

    assert lifecycle.reconcile() is False
    assert lifecycle.disable() is False
    assert lifecycle.prepare_native_claim() is True
    assert events == []


def test_retired_status_preserves_schema_and_forces_endpoint_unavailable():
    lifecycle, inner, _network, events = _lifecycle()
    assert lifecycle.retire() is True
    inner.status["endpoint_available"] = True
    events.clear()

    snapshot = lifecycle.status_snapshot()

    assert set(snapshot) == set(STATUS)
    assert snapshot["endpoint_available"] is False
    assert events == ["inner.status"]
    assert "retired" not in snapshot

def test_concurrent_enable_and_retire_are_serialized_without_interleave():
    import threading
    import time

    lifecycle, inner, _network, events = _lifecycle()

    enable_entered = threading.Event()
    allow_enable = threading.Event()
    retire_started = threading.Event()

    results = {}
    errors = []

    def blocked_enable():
        events.append("inner.enable.enter")
        enable_entered.set()
        assert allow_enable.wait(2.0)
        events.append("inner.enable.exit")
        return True

    inner.enable = blocked_enable

    def run_enable():
        try:
            results["enable"] = lifecycle.enable()
        except BaseException as exc:
            errors.append(("enable", exc))

    def run_retire():
        retire_started.set()
        try:
            results["retire"] = lifecycle.retire()
        except BaseException as exc:
            errors.append(("retire", exc))

    enable_thread = threading.Thread(target=run_enable)
    retire_thread = threading.Thread(target=run_retire)

    enable_thread.start()
    assert enable_entered.wait(2.0)

    retire_thread.start()
    assert retire_started.wait(2.0)

    # enable() owns the lifecycle RLock at this point, so retire() must
    # remain blocked until enable() has completed its whole transaction.
    time.sleep(0.05)
    assert retire_thread.is_alive()
    assert "retire" not in results
    assert "network.release" not in events
    assert "inner.disable" not in events

    allow_enable.set()

    enable_thread.join(timeout=2.0)
    retire_thread.join(timeout=2.0)

    assert not enable_thread.is_alive()
    assert not retire_thread.is_alive()
    assert errors == []
    assert results == {
        "enable": True,
        "retire": True,
    }
    assert events == [
        "network.preflight",
        "inner.enable.enter",
        "inner.enable.exit",
        "network.activate",
        "inner.reconcile",
        "inner.status",
        "network.release",
        "inner.disable",
    ]

    events.clear()
    with pytest.raises(SpotifyEndpointLifecycleError):
        lifecycle.enable()
    assert lifecycle.reconcile() is False
    assert lifecycle.disable() is False
    assert events == []


def test_deactivate_keeps_network_endpoint_advertised():
    lifecycle, inner, network, events = _lifecycle()
    network.active = True

    assert lifecycle.deactivate() is True

    assert events == ["inner.deactivate"]
    assert network.active is True
    assert "network.release" not in events
    assert "inner.disable" not in events


def test_deactivate_failure_is_sanitized_without_network_release():
    lifecycle, inner, network, events = _lifecycle()
    network.active = True
    inner.fail_deactivate = True

    with pytest.raises(SpotifyEndpointLifecycleError) as raised:
        lifecycle.deactivate()

    assert "private" not in str(raised.value)
    assert network.active is True
    assert events == ["inner.deactivate"]
