import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402
from services.spotify_endpoint_lifecycle import (  # noqa: E402
    SpotifyEndpointLifecycle,
    SpotifyEndpointLifecycleError,
)


OLD_BINDING = backend.SpotifyOutputBinding(0, 0)
NEW_BINDING = backend.SpotifyOutputBinding(1, 0)


class Retirable:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error
        self.retire_calls = 0

    def retire(self):
        self.retire_calls += 1
        self.events.append("retire")
        if self.error is not None:
            raise self.error
        return True


class Inner:
    def __init__(self, events):
        self.events = events
        self.status = {
            "phase": "standby",
            "endpoint_available": True,
            "coordinator_state": "standby",
            "spotify_owner": False,
            "native_blocked": False,
            "observer_ready": True,
            "is_active": False,
            "playback_status": None,
        }

    def enable(self):
        self.events.append("inner.enable")
        return True

    def disable(self):
        self.events.append("inner.disable")
        self.status["endpoint_available"] = False
        return True

    def reconcile(self):
        self.events.append("inner.reconcile")
        return False

    def prepare_native_claim(self):
        self.events.append("inner.prepare_native_claim")
        return True

    def status_snapshot(self):
        self.events.append("inner.status")
        return dict(self.status)


class Network:
    def __init__(self, events):
        self.events = events

    def release(self):
        self.events.append("network.release")
        return True

    def cleanup_stale(self):
        self.events.append("network.cleanup")
        return True

    def preflight(self):
        self.events.append("network.preflight")
        return False

    def activate(self):
        self.events.append("network.activate")
        return True


def _sealed_lifecycle(events):
    return SpotifyEndpointLifecycle(
        orchestrator=Inner(events),
        network_access=Network(events),
    )


def _configure_output_test(
    monkeypatch,
    *,
    lifecycle=None,
    binding=None,
    save=None,
    app_fields=None,
):
    fields = {
        "spotify_orchestrator": lifecycle,
        "spotify_orchestrator_binding": binding,
    }
    fields.update(app_fields or {})
    app = SimpleNamespace(**fields)
    devices = {
        "hw:0,0": {
            "device": "hw:0,0",
            "name": "Old DAC",
            "recommended": True,
        },
        "hw:1,0": {
            "device": "hw:1,0",
            "name": "New DAC",
            "recommended": True,
        },
    }
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(backend, "ALSA_DRIVER", "ALSA")
    monkeypatch.setattr(backend, "ALSA_DEVICE", "hw:0,0")
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "Old DAC")
    monkeypatch.setattr(
        backend,
        "_find_discovered_audio_device",
        lambda device: devices.get(device),
    )
    monkeypatch.setattr(
        backend,
        "_recommended_audio_outputs_only",
        lambda: False,
    )
    monkeypatch.setattr(
        backend,
        "_save_audio_output_config",
        save or (lambda *_args: None),
    )
    monkeypatch.setattr(
        backend,
        "_audio_output_settings_state",
        lambda: {
            "alsa_driver": backend.ALSA_DRIVER,
            "alsa_device": backend.ALSA_DEVICE,
            "dac_name": backend.ALSA_DAC_NAME,
        },
    )
    return app


def test_physical_binding_change_retires_before_clear_save_and_mutation(monkeypatch):
    events = []
    lifecycle = Retirable(events)
    app = None

    def save(driver, device, name):
        events.append("save")
        assert lifecycle.retire_calls == 1
        assert app.spotify_orchestrator is None
        assert app.spotify_orchestrator_binding is None
        assert (backend.ALSA_DRIVER, backend.ALSA_DEVICE, backend.ALSA_DAC_NAME) == (
            "ALSA",
            "hw:0,0",
            "Old DAC",
        )
        assert (driver, device, name) == ("alsa_mmap", "hw:1,0", "New DAC")

    app = _configure_output_test(
        monkeypatch,
        lifecycle=lifecycle,
        binding=OLD_BINDING,
        save=save,
    )

    state = backend._set_audio_output_preference(
        "alsa_mmap",
        "hw:1,0",
        "Untrusted Browser Name",
    )

    assert events == ["retire", "save"]
    assert app.spotify_orchestrator is None
    assert app.spotify_orchestrator_binding is None
    assert state == {
        "alsa_driver": "alsa_mmap",
        "alsa_device": "hw:1,0",
        "dac_name": "New DAC",
    }


def test_stale_retired_reference_cannot_enable_or_reconcile(monkeypatch):
    events = []
    old_lifecycle = _sealed_lifecycle(events)
    app = _configure_output_test(
        monkeypatch,
        lifecycle=old_lifecycle,
        binding=OLD_BINDING,
    )

    backend._set_audio_output_preference("ALSA", "hw:1,0")

    assert events == ["network.release", "inner.disable"]
    assert app.spotify_orchestrator is None
    assert app.spotify_orchestrator_binding is None
    events.clear()
    with pytest.raises(SpotifyEndpointLifecycleError):
        old_lifecycle.enable()
    assert old_lifecycle.reconcile() is False
    assert events == []


def test_retirement_failure_preserves_selection_composition_and_persistence(
    monkeypatch,
):
    private = "SROVA_PRIVATE_RETIREMENT_FAILURE"
    events = []
    lifecycle = Retirable(events, RuntimeError(private))
    app = _configure_output_test(
        monkeypatch,
        lifecycle=lifecycle,
        binding=OLD_BINDING,
        save=lambda *_args: pytest.fail("retirement failure must not persist"),
    )

    with pytest.raises(backend.SpotifyRuntimeCompositionError) as raised:
        backend._set_audio_output_preference("ALSA", "hw:1,0")

    assert private not in str(raised.value)
    assert events == ["retire"]
    assert app.spotify_orchestrator is lifecycle
    assert app.spotify_orchestrator_binding == OLD_BINDING
    assert (backend.ALSA_DRIVER, backend.ALSA_DEVICE, backend.ALSA_DAC_NAME) == (
        "ALSA",
        "hw:0,0",
        "Old DAC",
    )


def test_persistence_failure_after_retirement_keeps_old_memory_and_no_resurrection(
    monkeypatch,
):
    events = []
    old_lifecycle = _sealed_lifecycle(events)
    app = _configure_output_test(
        monkeypatch,
        lifecycle=old_lifecycle,
        binding=OLD_BINDING,
        save=lambda *_args: (_ for _ in ()).throw(RuntimeError("private save")),
    )

    with pytest.raises(RuntimeError, match="private save"):
        backend._set_audio_output_preference("ALSA", "hw:1,0")

    assert app.spotify_orchestrator is None
    assert app.spotify_orchestrator_binding is None
    assert (backend.ALSA_DRIVER, backend.ALSA_DEVICE, backend.ALSA_DAC_NAME) == (
        "ALSA",
        "hw:0,0",
        "Old DAC",
    )
    events.clear()
    with pytest.raises(SpotifyEndpointLifecycleError):
        old_lifecycle.enable()
    assert events == []


def test_driver_only_change_for_same_physical_binding_does_not_retire(monkeypatch):
    lifecycle = Retirable([])
    saved = []
    app = _configure_output_test(
        monkeypatch,
        lifecycle=lifecycle,
        binding=OLD_BINDING,
        save=lambda *args: saved.append(args),
    )

    backend._set_audio_output_preference("alsa_mmap", "hw:0,0")

    assert lifecycle.retire_calls == 0
    assert app.spotify_orchestrator is lifecycle
    assert app.spotify_orchestrator_binding == OLD_BINDING
    assert saved == [("alsa_mmap", "hw:0,0", "Old DAC")]
    assert backend.ALSA_DRIVER == "alsa_mmap"


def test_no_existing_spotify_composition_allows_normal_output_save(monkeypatch):
    saved = []
    app = _configure_output_test(
        monkeypatch,
        save=lambda *args: saved.append(args),
    )

    backend._set_audio_output_preference("ALSA", "hw:1,0")

    assert saved == [("ALSA", "hw:1,0", "New DAC")]
    assert app.spotify_orchestrator is None
    assert app.spotify_orchestrator_binding is None
    assert backend.ALSA_DEVICE == "hw:1,0"


@pytest.mark.parametrize(
    ("lifecycle", "binding"),
    [
        (Retirable([]), None),
        (None, OLD_BINDING),
    ],
)
def test_inconsistent_composition_pair_fails_closed(monkeypatch, lifecycle, binding):
    app = _configure_output_test(
        monkeypatch,
        lifecycle=lifecycle,
        binding=binding,
        save=lambda *_args: pytest.fail("invalid composition must not persist"),
    )

    with pytest.raises(backend.SpotifyRuntimeCompositionError):
        backend._set_audio_output_preference("ALSA", "hw:1,0")

    assert app.spotify_orchestrator is lifecycle
    assert app.spotify_orchestrator_binding is binding
    assert backend.ALSA_DEVICE == "hw:0,0"


def test_next_explicit_enable_composes_against_new_binding(monkeypatch):
    events = []
    old_lifecycle = Retirable(events)
    app = _configure_output_test(
        monkeypatch,
        lifecycle=old_lifecycle,
        binding=OLD_BINDING,
        app_fields={
            "spotify_coordinator": object(),
            "spotify_secret_store": object(),
            "spotify_managed": object(),
            "spotify_runtime": object(),
        },
    )
    backend._set_audio_output_preference("ALSA", "hw:1,0")
    built = object()
    calls = []
    monkeypatch.setattr(
        backend,
        "build_spotify_endpoint_lifecycle",
        lambda **kwargs: calls.append(kwargs) or built,
    )

    result = backend._spotify_orchestrator_for_current_output()

    assert result is built
    assert calls[0]["binding"] == NEW_BINDING
    assert app.spotify_orchestrator is built
    assert app.spotify_orchestrator_binding == NEW_BINDING

def test_concurrent_stale_enable_reference_cannot_resurrect_retired_binding(
    monkeypatch,
):
    import threading

    events = []
    old_lifecycle = _sealed_lifecycle(events)
    app = _configure_output_test(
        monkeypatch,
        lifecycle=old_lifecycle,
        binding=OLD_BINDING,
    )

    reference_captured = threading.Event()
    allow_stale_call = threading.Event()
    result = {}

    def stale_enable():
        try:
            reference = backend._spotify_orchestrator_for_current_output()
            assert reference is old_lifecycle
            reference_captured.set()
            assert allow_stale_call.wait(2.0)
            reference.enable()
            result["unexpected_enable"] = True
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=stale_enable)
    thread.start()

    assert reference_captured.wait(2.0)

    state = backend._set_audio_output_preference("ALSA", "hw:1,0")

    assert state == {
        "alsa_driver": "ALSA",
        "alsa_device": "hw:1,0",
        "dac_name": "New DAC",
    }
    assert app.spotify_orchestrator is None
    assert app.spotify_orchestrator_binding is None
    assert events == ["network.release", "inner.disable"]

    allow_stale_call.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert "unexpected_enable" not in result
    assert isinstance(result.get("error"), SpotifyEndpointLifecycleError)
    assert str(result["error"]) == "Spotify endpoint lifecycle is retired"
    assert events == ["network.release", "inner.disable"]


def test_concurrent_stale_reconcile_reference_is_inert_after_retirement(
    monkeypatch,
):
    import threading

    events = []
    old_lifecycle = _sealed_lifecycle(events)
    app = _configure_output_test(
        monkeypatch,
        lifecycle=old_lifecycle,
        binding=OLD_BINDING,
    )

    reference_captured = threading.Event()
    allow_stale_call = threading.Event()
    result = {}

    def stale_reconcile():
        try:
            reference = backend._existing_spotify_endpoint_lifecycle()
            assert reference is old_lifecycle
            reference_captured.set()
            assert allow_stale_call.wait(2.0)
            result["reconcile"] = reference.reconcile()
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=stale_reconcile)
    thread.start()

    assert reference_captured.wait(2.0)

    backend._set_audio_output_preference("ALSA", "hw:1,0")

    assert app.spotify_orchestrator is None
    assert app.spotify_orchestrator_binding is None
    assert events == ["network.release", "inner.disable"]

    allow_stale_call.set()
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert "error" not in result
    assert result["reconcile"] is False
    assert events == ["network.release", "inner.disable"]
