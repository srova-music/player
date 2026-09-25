import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402


PUBLIC_STATE = {
    "state": "standby",
    "spotify_owner": False,
    "native_blocked": False,
}
PUBLIC_CONTROL_KEYS = {
    "ok",
    "changed",
    "state",
    "spotify_owner",
    "native_blocked",
}


class Coordinator:
    def __init__(self):
        self.snapshot = dict(PUBLIC_STATE)
        self.private_secret = "SROVA_PRIVATE_COORDINATOR_SECRET"

    def status_snapshot(self):
        return dict(self.snapshot)


class Lifecycle:
    def __init__(self, *, enable_results=(True,), disable_results=(True,)):
        self.enable_results = list(enable_results)
        self.disable_results = list(disable_results)
        self.enable_calls = 0
        self.disable_calls = 0
        self.deactivate_calls = 0
        self.reconcile_calls = 0
        self.enable_error = None
        self.disable_error = None
        self.deactivate_error = None
        self.reconcile_error = None

    def enable(self):
        self.enable_calls += 1
        if self.enable_error is not None:
            raise self.enable_error
        return self.enable_results[min(self.enable_calls - 1, len(self.enable_results) - 1)]

    def disable(self):
        self.disable_calls += 1
        if self.disable_error is not None:
            raise self.disable_error
        return self.disable_results[
            min(self.disable_calls - 1, len(self.disable_results) - 1)
        ]

    def deactivate(self):
        self.deactivate_calls += 1
        if self.deactivate_error is not None:
            raise self.deactivate_error
        return True

    def reconcile(self):
        self.reconcile_calls += 1
        if self.reconcile_error is not None:
            raise self.reconcile_error
        return False


def _app(*, lifecycle=None):
    return SimpleNamespace(
        spotify_coordinator=Coordinator(),
        spotify_orchestrator=lifecycle,
        spotify_orchestrator_binding=None,
    )


def _post(path):
    handler = object.__new__(backend.ControlHandler)
    handler.path = path
    handler.headers = {}

    class NoRead(io.BytesIO):
        def read(self, *_args, **_kwargs):
            raise AssertionError("Spotify endpoint control must not read a body")

    handler.rfile = NoRead()
    response = {}
    handler._send_json = lambda payload, no_store=False: response.update(
        status=200,
        payload=payload,
        no_store=no_store,
    )
    handler.send_error = lambda status, *args, **kwargs: response.update(
        status=status,
    )
    handler.do_POST()
    return response


def _forbidden(*_args, **_kwargs):
    raise AssertionError("forbidden construction or side effect")


@pytest.fixture(autouse=True)
def _isolated_spotify_enabled_intent(monkeypatch):
    settings = dict(backend._APP_SETTINGS)
    settings["spotify_enabled"] = False
    monkeypatch.setattr(backend, "_APP_SETTINGS", settings)
    monkeypatch.setattr(backend, "_save_app_settings", lambda: True)
    monkeypatch.setattr(
        backend,
        "_spotify_rearm_pcm_is_free",
        lambda: True,
    )
    monkeypatch.setattr(
        backend,
        "_spotify_selected_dac_available",
        lambda: True,
    )


def test_enable_while_native_pcm_busy_persists_intent_without_composition(
    monkeypatch,
):
    app = _app()
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_spotify_rearm_pcm_is_free",
        lambda: False,
    )
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        _forbidden,
    )

    response = _post("/api/spotify/enable")

    assert backend._spotify_enabled_intent() is True
    assert response == {
        "status": 200,
        "payload": {
            "ok": True,
            "changed": True,
            **PUBLIC_STATE,
        },
        "no_store": True,
    }


def test_enable_lazily_composes_once_calls_once_and_returns_exact_public_state(
    monkeypatch,
):
    lifecycle = Lifecycle()
    app = _app()
    compositions = []
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        lambda: compositions.append("compose") or lifecycle,
    )

    response = _post("/api/spotify/enable")

    assert compositions == ["compose"]
    assert lifecycle.enable_calls == 1
    assert response == {
        "status": 200,
        "payload": {
            "ok": True,
            "changed": True,
            **PUBLIC_STATE,
        },
        "no_store": True,
    }
    assert set(response["payload"]) == PUBLIC_CONTROL_KEYS


@pytest.mark.parametrize(
    "path",
    [
        "/api/spotify/enable?api_key=must-not-be-read",
        "/api/spotify/disable?api_key=must-not-be-read",
        "/api/spotify/deactivate?api_key=must-not-be-read",
    ],
)
def test_control_query_string_is_rejected_without_composition(monkeypatch, path):
    lifecycle = Lifecycle()
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        _app(lifecycle=lifecycle),
    )
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        _forbidden,
    )

    response = _post(path)

    assert response == {"status": 404}
    assert lifecycle.enable_calls == 0
    assert lifecycle.disable_calls == 0


def test_control_query_material_is_suppressed_from_http_logs(monkeypatch):
    handler = object.__new__(backend.ControlHandler)
    handler.path = "/api/spotify/enable?private=SROVA_CONTROL_SECRET"
    handler.address_string = lambda: "127.0.0.1"
    calls = []
    monkeypatch.setattr(
        backend.logger,
        "info",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    backend.ControlHandler.log_message(
        handler,
        '"%s" %s',
        handler.path,
        "404",
    )

    assert calls == []


def test_enable_failure_is_sanitized(monkeypatch):
    private = "SROVA_PRIVATE_ENABLE_PID_4321_PORT_9876"
    lifecycle = Lifecycle()
    lifecycle.enable_error = RuntimeError(private)
    monkeypatch.setattr(backend, "APP_INSTANCE", _app())
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        lambda: lifecycle,
    )

    response = _post("/api/spotify/enable")

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_endpoint_enable_failed",
    }
    assert response["no_store"] is True
    assert private not in repr(response)


def test_disable_without_existing_lifecycle_is_idempotent_and_never_composes(
    monkeypatch,
):
    monkeypatch.setattr(backend, "APP_INSTANCE", _app())
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        _forbidden,
    )

    response = _post("/api/spotify/disable")

    assert response["payload"] == {
        "ok": True,
        "changed": False,
        **PUBLIC_STATE,
    }
    assert set(response["payload"]) == PUBLIC_CONTROL_KEYS


def test_disable_existing_lifecycle_calls_once(monkeypatch):
    lifecycle = Lifecycle()
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(lifecycle=lifecycle))

    response = _post("/api/spotify/disable")

    assert lifecycle.disable_calls == 1
    assert response["payload"]["changed"] is True


def test_repeated_disable_remains_idempotent(monkeypatch):
    lifecycle = Lifecycle(disable_results=(True, False))
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(lifecycle=lifecycle))

    first = _post("/api/spotify/disable")
    second = _post("/api/spotify/disable")

    assert lifecycle.disable_calls == 2
    assert first["payload"]["changed"] is True
    assert second["payload"]["changed"] is False


def test_disable_failure_is_sanitized(monkeypatch):
    private = "SROVA_PRIVATE_DISABLE_INTERFACE_CIDR_FIREWALL"
    lifecycle = Lifecycle()
    lifecycle.disable_error = RuntimeError(private)
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(lifecycle=lifecycle))

    response = _post("/api/spotify/disable")

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_endpoint_disable_failed",
    }
    assert private not in repr(response)


@pytest.mark.parametrize("path", ["/api/spotify/enable", "/api/spotify/disable"])
def test_control_success_contains_no_private_runtime_or_network_fields(
    monkeypatch,
    path,
):
    lifecycle = Lifecycle()
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(lifecycle=lifecycle))
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        lambda: lifecycle,
    )

    response = _post(path)

    assert set(response["payload"]) == PUBLIC_CONTROL_KEYS
    rendered = repr(response["payload"]).lower()
    for forbidden in (
        "secret",
        "api_key",
        "pid",
        "port",
        "interface",
        "cidr",
        "firewall",
        "observer",
    ):
        assert forbidden not in rendered


def test_reconcile_without_lifecycle_never_composes(monkeypatch):
    monkeypatch.setattr(backend, "APP_INSTANCE", _app())
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        _forbidden,
    )

    assert backend._reconcile_existing_spotify_endpoint() is True


def test_reconcile_existing_lifecycle_runs_outside_lookup_lock(monkeypatch):
    lock_state = {"held": False}

    class Lock:
        def __enter__(self):
            assert lock_state["held"] is False
            lock_state["held"] = True

        def __exit__(self, *_args):
            lock_state["held"] = False

    lifecycle = Lifecycle()

    def reconcile():
        assert lock_state["held"] is False
        lifecycle.reconcile_calls += 1
        return False

    lifecycle.reconcile = reconcile
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(lifecycle=lifecycle))
    monkeypatch.setattr(backend, "_SPOTIFY_ORCHESTRATOR_LOCK", Lock())

    assert backend._reconcile_existing_spotify_endpoint() is True
    assert lifecycle.reconcile_calls == 1



def test_reconcile_dac_loss_withdraws_endpoint_without_clearing_master_intent(
    monkeypatch,
):
    lifecycle = Lifecycle()
    app = _app(lifecycle=lifecycle)
    app.spotify_coordinator.snapshot = {
        "state": "owned",
        "spotify_owner": True,
        "native_blocked": True,
    }

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        app,
    )

    backend._APP_SETTINGS["spotify_enabled"] = True

    monkeypatch.setattr(
        backend,
        "_spotify_selected_dac_available",
        lambda: False,
    )
    monkeypatch.setattr(
        backend,
        "_set_spotify_enabled_intent",
        _forbidden,
    )
    monkeypatch.setattr(
        backend,
        "_spotify_rearm_pcm_is_free",
        _forbidden,
    )

    assert backend._reconcile_existing_spotify_endpoint() is True

    assert lifecycle.disable_calls == 1
    assert lifecycle.reconcile_calls == 0
    assert lifecycle.enable_calls == 0
    assert backend._spotify_enabled_intent() is True


def test_reconcile_dac_loss_withdraw_failure_is_sanitized_and_intent_survives(
    monkeypatch,
):
    private = "SROVA_PRIVATE_DAC_LOSS_WITHDRAW_FAILURE"
    lifecycle = Lifecycle()
    lifecycle.disable_error = RuntimeError(private)

    app = _app(lifecycle=lifecycle)
    app.spotify_coordinator.snapshot = {
        "state": "owned",
        "spotify_owner": True,
        "native_blocked": True,
    }

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        app,
    )

    backend._APP_SETTINGS["spotify_enabled"] = True
    warnings = []

    monkeypatch.setattr(
        backend,
        "_spotify_selected_dac_available",
        lambda: False,
    )
    monkeypatch.setattr(
        backend,
        "_set_spotify_enabled_intent",
        _forbidden,
    )
    monkeypatch.setattr(
        backend.logger,
        "warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    assert backend._reconcile_existing_spotify_endpoint() is True

    assert lifecycle.disable_calls == 1
    assert lifecycle.reconcile_calls == 0
    assert backend._spotify_enabled_intent() is True
    assert private not in repr(warnings)
    assert warnings == [
        (("Spotify endpoint reconciliation failed safely",), {}),
    ]

def test_reconcile_failure_is_sanitized_and_scheduler_stays_alive(monkeypatch):
    private = "SROVA_PRIVATE_RECONCILE_PID_4321"
    lifecycle = Lifecycle()
    lifecycle.reconcile_error = RuntimeError(private)
    warnings = []
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(lifecycle=lifecycle))
    monkeypatch.setattr(
        backend.logger,
        "warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    assert backend._reconcile_existing_spotify_endpoint() is True
    assert lifecycle.reconcile_calls == 1
    assert private not in repr(warnings)
    assert warnings == [
        (("Spotify endpoint reconciliation failed safely",), {}),
    ]


# BF4_DAC_ABSENT_ENABLE_GUARD
def test_enable_rejects_absent_dac_before_intent_or_composition(monkeypatch):
    app = _app()
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_spotify_selected_dac_available",
        lambda: False,
    )
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        _forbidden,
    )

    response = _post("/api/spotify/enable")

    assert backend._spotify_enabled_intent() is False
    assert response == {
        "status": 200,
        "payload": {
            "ok": False,
            "error": "spotify_dac_unavailable",
        },
        "no_store": True,
    }


def test_deactivate_preserves_enabled_intent_and_calls_lifecycle_once(
    monkeypatch,
):
    lifecycle = Lifecycle()
    app = _app(lifecycle=lifecycle)
    app.spotify_coordinator.snapshot = {
        "state": "owned",
        "spotify_owner": True,
        "native_blocked": True,
    }

    backend._APP_SETTINGS["spotify_enabled"] = True
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        app,
    )

    response = _post("/api/spotify/deactivate")

    assert lifecycle.deactivate_calls == 1
    assert lifecycle.disable_calls == 0
    assert backend._spotify_enabled_intent() is True
    assert response["payload"] == {
        "ok": True,
        "changed": True,
        "state": "owned",
        "spotify_owner": True,
        "native_blocked": True,
    }
    assert response["no_store"] is True


def test_deactivate_failure_never_turns_off_master_intent(monkeypatch):
    private = "SROVA_PRIVATE_DEACTIVATE_DETAIL"
    lifecycle = Lifecycle()
    lifecycle.deactivate_error = RuntimeError(private)

    backend._APP_SETTINGS["spotify_enabled"] = True
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        _app(lifecycle=lifecycle),
    )

    response = _post("/api/spotify/deactivate")

    assert backend._spotify_enabled_intent() is True
    assert lifecycle.disable_calls == 0
    assert response["payload"] == {
        "ok": False,
        "error": "spotify_endpoint_deactivate_failed",
    }
    assert private not in repr(response)
