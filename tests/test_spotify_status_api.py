import io
import json
import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402
from services.spotify_coordinator import SpotifyCoordinator  # noqa: E402
from services.spotify_secret_store import SpotifySecretStore  # noqa: E402


class _FakeSpotifySecretStore:
    def __init__(self, configured=False):
        self.configured = bool(configured)

    def key_configured(self):
        return bool(self.configured)


def _get(path):
    handler = object.__new__(backend.ControlHandler)
    handler.path = path
    response = {}

    def send_json(payload, no_store=False):
        response.update(status=200, payload=payload, no_store=no_store)

    def send_error(status, message=None, explain=None):
        response.update(status=status, message=message, explain=explain)

    handler._send_json = send_json
    handler.send_error = send_error
    handler.do_GET()
    return response


@pytest.fixture
def app(monkeypatch):
    instance = backend.HeadlessApp()
    instance.spotify_secret_store = _FakeSpotifySecretStore()
    monkeypatch.setattr(backend, "APP_INSTANCE", instance)
    return instance


def test_headless_app_owns_one_disabled_coordinator(app):
    assert isinstance(app.spotify_coordinator, SpotifyCoordinator)
    assert app.spotify_coordinator.status_snapshot() == {
        "state": "disabled",
        "spotify_owner": False,
        "native_blocked": False,
    }
    assert isinstance(
        backend.HeadlessApp().spotify_secret_store,
        SpotifySecretStore,
    )


def test_status_returns_exact_sanitized_snapshot_without_storage(app):
    app.spotify_coordinator._device_name = "secret device"
    app.spotify_coordinator._bitrate = 320
    app.spotify_coordinator._runtime = object()

    response = _get("/api/spotify/status")

    assert response == {
        "status": 200,
        "payload": {
            "state": "disabled",
            "spotify_owner": False,
            "native_blocked": False,
            "key_configured": False,
            "enabled": False,
        },
        "no_store": True,
    }
    assert set(response["payload"]) == {
        "state",
        "spotify_owner",
        "native_blocked",
        "key_configured",
        "enabled",
    }
    assert "secret device" not in repr(response["payload"])
    assert "320" not in repr(response["payload"])


def test_repeated_status_reads_do_not_mutate_coordinator(app):
    before = dict(vars(app.spotify_coordinator))

    first = _get("/api/spotify/status")
    second = _get("/api/spotify/status")

    assert first == second
    assert vars(app.spotify_coordinator) == before


def test_status_reflects_existing_coordinator_state(app):
    app.spotify_coordinator.enter_standby()
    standby = _get("/api/spotify/status")
    assert standby["payload"] == {
        "state": "standby",
        "spotify_owner": False,
        "native_blocked": False,
        "key_configured": False,
        "enabled": False,
    }

    app.spotify_coordinator.begin_acquisition()
    acquiring = _get("/api/spotify/status")
    assert acquiring["payload"] == {
        "state": "acquiring",
        "spotify_owner": False,
        "native_blocked": True,
        "key_configured": False,
        "enabled": False,
    }


def test_status_does_not_construct_another_coordinator(app, monkeypatch):
    def fail_if_constructed(*args, **kwargs):
        raise AssertionError("status endpoint constructed a coordinator")

    monkeypatch.setattr(backend, "SpotifyCoordinator", fail_if_constructed)
    response = _get("/api/spotify/status")

    assert response["status"] == 200
    expected = app.spotify_coordinator.status_snapshot()
    expected["key_configured"] = False
    expected["enabled"] = False
    assert response["payload"] == expected


def test_missing_coordinator_fails_safe(monkeypatch):
    instance = backend.HeadlessApp()
    del instance.spotify_coordinator
    monkeypatch.setattr(backend, "APP_INSTANCE", instance)

    response = _get("/api/spotify/status")

    assert response["status"] == 503
    assert "payload" not in response


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        {"state": "disabled", "spotify_owner": False},
        {
            "state": "disabled",
            "spotify_owner": False,
            "native_blocked": False,
            "secret": "must-not-leak",
        },
    ],
)
def test_invalid_snapshot_contract_fails_safe(app, monkeypatch, snapshot):
    monkeypatch.setattr(
        app.spotify_coordinator,
        "status_snapshot",
        lambda: snapshot,
    )

    response = _get("/api/spotify/status")

    assert response["status"] == 503
    assert "payload" not in response


def test_snapshot_failure_fails_safe(app, monkeypatch):
    def fail():
        raise RuntimeError("private failure detail")

    monkeypatch.setattr(app.spotify_coordinator, "status_snapshot", fail)

    response = _get("/api/spotify/status")

    assert response["status"] == 503
    assert "payload" not in response
    assert "private failure detail" not in repr(response)


def test_status_read_does_not_touch_runtime_controls(app, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("read-only status touched a runtime control")

    monkeypatch.setattr(backend.subprocess, "run", forbidden)
    monkeypatch.setattr(backend.subprocess, "Popen", forbidden)
    monkeypatch.setattr(backend.os, "kill", forbidden)
    monkeypatch.setattr(backend.os, "system", forbidden)

    response = _get("/api/spotify/status")

    assert response["status"] == 200


def test_no_store_json_response_emits_cache_prevention_headers():
    handler = object.__new__(backend.ControlHandler)
    statuses = []
    headers = {}
    handler.wfile = io.BytesIO()
    handler.send_response = statuses.append
    handler.send_header = headers.__setitem__
    handler.end_headers = lambda: None

    backend.ControlHandler._send_json(
        handler,
        {
            "state": "disabled",
            "spotify_owner": False,
            "native_blocked": False,
        },
        no_store=True,
    )

    assert statuses == [200]
    assert "no-store" in headers["Cache-Control"]
    assert headers["Pragma"] == "no-cache"
    assert headers["Expires"] == "0"
    assert json.loads(handler.wfile.getvalue()) == {
        "state": "disabled",
        "spotify_owner": False,
        "native_blocked": False,
    }


def test_status_route_rejects_query_parameters(app):
    response = _get("/api/spotify/status?enable=true")

    assert response["status"] == 404
    assert "payload" not in response



def test_status_reports_key_configured_boolean_without_secret_echo(app):
    app.spotify_secret_store.configured = True
    app.spotify_secret_store.private_marker = (
        "SROVA_TEST_ONLY_SECRET_MUST_NOT_ECHO"
    )

    response = _get("/api/spotify/status")

    assert response["status"] == 200
    assert response["payload"]["key_configured"] is True
    assert (
        "SROVA_TEST_ONLY_SECRET_MUST_NOT_ECHO"
        not in repr(response["payload"])
    )


def test_missing_secret_store_fails_safe(monkeypatch):
    instance = backend.HeadlessApp()
    del instance.spotify_secret_store
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        instance,
    )

    response = _get("/api/spotify/status")

    assert response["status"] == 503
    assert "payload" not in response


def test_secret_store_status_failure_fails_safe(app):
    class BrokenStore:
        def key_configured(self):
            raise RuntimeError(
                "SROVA_TEST_ONLY_PRIVATE_FAILURE"
            )

    app.spotify_secret_store = BrokenStore()

    response = _get("/api/spotify/status")

    assert response["status"] == 503
    assert "payload" not in response
    assert (
        "SROVA_TEST_ONLY_PRIVATE_FAILURE"
        not in repr(response)
    )


def test_invalid_secret_store_status_contract_fails_safe(app):
    class InvalidStore:
        def key_configured(self):
            return "yes"

    app.spotify_secret_store = InvalidStore()

    response = _get("/api/spotify/status")

    assert response["status"] == 503
    assert "payload" not in response
