import io
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402


PRIVATE_SECRET = "SROVA_PRIVATE_API_KEY_MUST_NOT_APPEAR"


class Coordinator:
    def __init__(self, *, native_blocked=False):
        self.native_blocked = native_blocked

    def status_snapshot(self):
        return {
            "state": "owned" if self.native_blocked else "standby",
            "spotify_owner": bool(self.native_blocked),
            "native_blocked": bool(self.native_blocked),
        }


class Lifecycle:
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


def _app(*, lifecycle=None, native_blocked=False):
    return SimpleNamespace(
        spotify_coordinator=Coordinator(native_blocked=native_blocked),
        spotify_orchestrator=lifecycle,
        spotify_orchestrator_binding=(
            backend.SpotifyOutputBinding(0, 0)
            if lifecycle is not None
            else None
        ),
        spotify_secret_store=SimpleNamespace(private_api_key=PRIVATE_SECRET),
        spotify_managed=object(),
        spotify_runtime=object(),
    )


@pytest.fixture
def device_name_environment(monkeypatch):
    settings = dict(backend._APP_SETTINGS)
    settings["spotify_device_name"] = ""
    monkeypatch.setattr(backend, "_APP_SETTINGS", settings)
    monkeypatch.setattr(backend, "ALSA_DEVICE", "hw:0,0")
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "Reference DAC")
    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_SELECTED", True)
    monkeypatch.setattr(backend, "APP_INSTANCE", _app())
    monkeypatch.setattr(
        backend,
        "_spotify_selected_dac_available",
        lambda: True,
    )
    return settings


def _get(path):
    handler = object.__new__(backend.ControlHandler)
    handler.path = path
    response = {}
    handler._send_json = lambda payload, no_store=False: response.update(
        status=200,
        payload=payload,
        no_store=no_store,
    )
    handler.send_error = lambda status, *args, **kwargs: response.update(
        status=status,
    )
    handler.do_GET()
    return response


def _post_raw(path, body, *, content_type="application/json", content_length=None):
    handler = object.__new__(backend.ControlHandler)
    handler.path = path
    if isinstance(body, str):
        body = body.encode("utf-8")
    handler.rfile = io.BytesIO(body)
    handler.headers = {}
    if content_type is not None:
        handler.headers["Content-Type"] = content_type
    handler.headers["Content-Length"] = str(
        len(body) if content_length is None else content_length
    )
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


def _post(path, payload, **kwargs):
    return _post_raw(
        path,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        **kwargs,
    )


def test_get_default_uses_dac_fallback_and_is_not_configured(
    device_name_environment,
):
    response = _get("/api/spotify/device-name")

    assert response == {
        "status": 200,
        "payload": {
            "device_name": "Reference DAC",
            "configured": False,
        },
        "no_store": True,
    }


def test_get_falls_back_to_selected_device_when_dac_name_is_empty(
    device_name_environment,
    monkeypatch,
):
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "")

    assert _get("/api/spotify/device-name")["payload"] == {
        "device_name": "hw:0,0",
        "configured": False,
    }


def test_get_configured_name_is_exact_and_exposes_no_secret(
    device_name_environment,
):
    device_name_environment["spotify_device_name"] = "Living Room SROVA"

    response = _get("/api/spotify/device-name")

    assert response["payload"] == {
        "device_name": "Living Room SROVA",
        "configured": True,
    }
    assert set(response["payload"]) == {"device_name", "configured"}
    assert PRIVATE_SECRET not in repr(response)


def test_get_query_string_is_rejected(device_name_environment):
    assert _get("/api/spotify/device-name?private=value") == {"status": 404}


def test_valid_post_persists_exact_non_secret_setting(
    device_name_environment,
    monkeypatch,
):
    saves = []
    monkeypatch.setattr(
        backend,
        "_save_app_settings",
        lambda: saves.append(device_name_environment["spotify_device_name"]) or True,
    )

    response = _post(
        "/api/spotify/device-name",
        {"device_name": "SROVA Listening Room"},
    )

    assert response == {
        "status": 200,
        "payload": {
            "ok": True,
            "device_name": "SROVA Listening Room",
            "configured": True,
        },
        "no_store": True,
    }
    assert saves == ["SROVA Listening Room"]
    assert PRIVATE_SECRET not in repr(response)


def test_persisted_value_survives_app_settings_reload(
    device_name_environment,
    monkeypatch,
    tmp_path,
):
    settings_path = tmp_path / "hiresti" / "srova_settings.json"
    monkeypatch.setattr(backend, "_APP_SETTINGS_FILE", str(settings_path))

    response = _post(
        "/api/spotify/device-name",
        {"device_name": "Persistent SROVA"},
    )
    assert response["payload"]["ok"] is True

    reloaded = dict(device_name_environment)
    reloaded["spotify_device_name"] = ""
    monkeypatch.setattr(backend, "_APP_SETTINGS", reloaded)
    backend._load_app_settings()

    assert _get("/api/spotify/device-name")["payload"] == {
        "device_name": "Persistent SROVA",
        "configured": True,
    }


@pytest.mark.parametrize(
    "configured_name",
    ["SROVA", "Living Room", "Spotify Test"],
)
def test_arbitrary_presentation_name_is_independent_at_composition(
    device_name_environment,
    monkeypatch,
    configured_name,
):
    device_name_environment["spotify_device_name"] = configured_name
    app = _app()
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    built = object()
    calls = []
    monkeypatch.setattr(
        backend,
        "build_spotify_endpoint_lifecycle",
        lambda **kwargs: calls.append(kwargs) or built,
    )

    assert backend._spotify_orchestrator_for_current_output() is built
    assert calls[0]["binding"] == backend.SpotifyOutputBinding(
        0,
        0,
    )
    assert calls[0]["device_name"] == configured_name


def test_absent_setting_preserves_current_binding_fallback(
    device_name_environment,
):
    device_name_environment.pop("spotify_device_name", None)

    assert backend._spotify_current_output_binding() == backend.SpotifyOutputBinding(
        0,
        0,
    )


def test_invalid_loaded_setting_fails_closed_to_current_fallback(
    device_name_environment,
):
    device_name_environment["spotify_device_name"] = " Invalid Stored Name"

    assert _get("/api/spotify/device-name")["payload"] == {
        "device_name": "Reference DAC",
        "configured": False,
    }
    assert backend._spotify_current_output_binding() == backend.SpotifyOutputBinding(
        0,
        0,
    )


def test_driver_only_dac_change_keeps_configured_name_binding_and_lifecycle(
    device_name_environment,
    monkeypatch,
):
    device_name_environment["spotify_device_name"] = "Configured Connect Name"
    events = []
    lifecycle = Lifecycle(events)
    app = _app(lifecycle=lifecycle)
    app.spotify_orchestrator_binding = backend.SpotifyOutputBinding(
        0,
        0,
    )
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_find_discovered_audio_device",
        lambda _device: {
            "device": "hw:0,0",
            "name": "Reference DAC",
            "recommended": True,
        },
    )
    monkeypatch.setattr(
        backend,
        "_recommended_audio_outputs_only",
        lambda: False,
    )
    monkeypatch.setattr(backend, "_save_audio_output_config", lambda *_args: None)
    monkeypatch.setattr(backend, "_audio_output_settings_state", lambda: {})

    backend._set_audio_output_preference("alsa_mmap", "hw:0,0")

    assert lifecycle.retire_calls == 0
    assert app.spotify_orchestrator is lifecycle
    assert app.spotify_orchestrator_binding == backend.SpotifyOutputBinding(0, 0)


@pytest.mark.parametrize(
    "value",
    [
        "",
        " Leading",
        "Trailing ",
        "Control\x00Name",
        "Control\nName",
        "Delete\x7fName",
        123,
        None,
        True,
    ],
)
def test_invalid_names_are_rejected_before_retirement_or_persistence(
    device_name_environment,
    monkeypatch,
    value,
):
    events = []
    lifecycle = Lifecycle(events)
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(lifecycle=lifecycle))
    saves = []
    monkeypatch.setattr(
        backend,
        "_save_app_settings",
        lambda: saves.append("save") or True,
    )

    response = _post(
        "/api/spotify/device-name",
        {"device_name": value},
    )

    assert response["payload"] == {
        "ok": False,
        "error": "invalid_device_name",
    }
    assert lifecycle.retire_calls == 0
    assert saves == []
    assert device_name_environment["spotify_device_name"] == ""


def test_exact_maximum_encoded_boundary_is_accepted(
    device_name_environment,
    monkeypatch,
):
    monkeypatch.setattr(backend, "_save_app_settings", lambda: True)
    name = "é" * 128
    assert len(name.encode("utf-8")) == backend._SPOTIFY_DEVICE_NAME_MAX_ENCODED_BYTES

    response = _post("/api/spotify/device-name", {"device_name": name})

    assert response["payload"] == {
        "ok": True,
        "device_name": name,
        "configured": True,
    }


def test_first_oversized_encoded_byte_is_rejected_before_side_effects(
    device_name_environment,
    monkeypatch,
):
    events = []
    lifecycle = Lifecycle(events)
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(lifecycle=lifecycle))
    monkeypatch.setattr(
        backend,
        "_save_app_settings",
        lambda: pytest.fail("257-byte name must not persist"),
    )
    name = ("a" * 255) + "é"
    assert len(name.encode("utf-8")) == (
        backend._SPOTIFY_DEVICE_NAME_MAX_ENCODED_BYTES + 1
    )

    response = _post("/api/spotify/device-name", {"device_name": name})

    assert response["payload"] == {
        "ok": False,
        "error": "invalid_device_name",
    }
    assert lifecycle.retire_calls == 0
    assert events == []
    assert device_name_environment["spotify_device_name"] == ""


def test_oversized_encoded_name_is_rejected_before_side_effects(
    device_name_environment,
    monkeypatch,
):
    events = []
    lifecycle = Lifecycle(events)
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(lifecycle=lifecycle))
    monkeypatch.setattr(
        backend,
        "_save_app_settings",
        lambda: pytest.fail("oversized name must not persist"),
    )
    name = "é" * 129
    assert len(name.encode("utf-8")) == 258

    response = _post("/api/spotify/device-name", {"device_name": name})

    assert response["payload"]["error"] == "invalid_device_name"
    assert lifecycle.retire_calls == 0


@pytest.mark.parametrize(
    ("raw", "content_type"),
    [
        (b'{"device_name":', "application/json"),
        (b"\xff", "application/json"),
        (b'{"device_name":"Valid"}', "text/plain"),
    ],
)
def test_malformed_requests_are_deterministically_rejected(
    device_name_environment,
    raw,
    content_type,
):
    response = _post_raw(
        "/api/spotify/device-name",
        raw,
        content_type=content_type,
    )

    assert response["payload"] == {
        "ok": False,
        "error": "invalid_request",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "Wrong Field"},
        {"device_name": "Valid", "extra": True},
        ["not", "an", "object"],
    ],
)
def test_request_schema_is_exact(device_name_environment, payload):
    response = _post("/api/spotify/device-name", payload)

    assert response["payload"] == {
        "ok": False,
        "error": "invalid_request",
    }


def test_post_query_string_is_rejected_without_mutation(
    device_name_environment,
    monkeypatch,
):
    monkeypatch.setattr(
        backend,
        "_save_app_settings",
        lambda: pytest.fail("query variant must not persist"),
    )

    response = _post(
        "/api/spotify/device-name?private=value",
        {"device_name": "Valid Name"},
    )

    assert response["payload"] == {"ok": False, "error": "invalid_request"}
    assert device_name_environment["spotify_device_name"] == ""


def test_native_blocked_rejects_without_retire_persist_or_runtime_actions(
    device_name_environment,
    monkeypatch,
):
    events = []
    lifecycle = Lifecycle(events)
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        _app(lifecycle=lifecycle, native_blocked=True),
    )
    monkeypatch.setattr(
        backend,
        "_save_app_settings",
        lambda: pytest.fail("blocked mutation must not persist"),
    )
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        lambda: pytest.fail("blocked mutation must not compose"),
    )

    response = _post(
        "/api/spotify/device-name",
        {"device_name": "Blocked Name"},
    )

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_device_name_blocked",
    }
    assert lifecycle.retire_calls == 0
    assert events == []
    assert device_name_environment["spotify_device_name"] == ""


def test_dormant_lifecycle_retires_and_clears_before_persistence(
    device_name_environment,
    monkeypatch,
):
    events = []
    lifecycle = Lifecycle(events)
    app = _app(lifecycle=lifecycle)
    monkeypatch.setattr(backend, "APP_INSTANCE", app)

    def save():
        events.append("save")
        assert app.spotify_orchestrator is None
        assert app.spotify_orchestrator_binding is None
        assert device_name_environment["spotify_device_name"] == "New Name"
        return True

    monkeypatch.setattr(backend, "_save_app_settings", save)

    response = _post(
        "/api/spotify/device-name",
        {"device_name": "New Name"},
    )

    assert response["payload"]["ok"] is True
    assert events == ["retire", "save"]
    assert app.spotify_orchestrator is None
    assert app.spotify_orchestrator_binding is None


def test_retirement_failure_preserves_setting_and_composition_without_recompose(
    device_name_environment,
    monkeypatch,
):
    private = "SROVA_PRIVATE_RETIREMENT_DETAIL"
    events = []
    lifecycle = Lifecycle(events, RuntimeError(private))
    app = _app(lifecycle=lifecycle)
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_save_app_settings",
        lambda: pytest.fail("failed retirement must not persist"),
    )
    monkeypatch.setattr(
        backend,
        "build_spotify_endpoint_lifecycle",
        lambda **_kwargs: pytest.fail("failed retirement must not recompose"),
    )

    response = _post(
        "/api/spotify/device-name",
        {"device_name": "Rejected Name"},
    )

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_device_name_update_failed",
    }
    assert private not in repr(response)
    assert device_name_environment["spotify_device_name"] == ""
    assert app.spotify_orchestrator is lifecycle
    assert app.spotify_orchestrator_binding is not None


def test_successful_change_does_not_enable_start_or_touch_firewall(
    device_name_environment,
    monkeypatch,
):
    monkeypatch.setattr(backend, "_save_app_settings", lambda: True)
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        lambda: pytest.fail("name mutation must not compose or enable"),
    )
    monkeypatch.setattr(
        backend,
        "build_spotify_endpoint_lifecycle",
        lambda **_kwargs: pytest.fail("name mutation must not build runtime"),
    )

    response = _post(
        "/api/spotify/device-name",
        {"device_name": "Dormant Name"},
    )

    assert response["payload"]["ok"] is True


def test_persistence_failure_restores_previous_setting_after_safe_retirement(
    device_name_environment,
    monkeypatch,
):
    device_name_environment["spotify_device_name"] = "Previous Name"
    events = []
    lifecycle = Lifecycle(events)
    app = _app(lifecycle=lifecycle)
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(backend, "_save_app_settings", lambda: False)

    response = _post(
        "/api/spotify/device-name",
        {"device_name": "Unpersisted Name"},
    )

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_device_name_update_failed",
    }
    assert device_name_environment["spotify_device_name"] == "Previous Name"
    assert app.spotify_orchestrator is None
    assert app.spotify_orchestrator_binding is None
    assert events == ["retire"]


def test_device_name_query_material_is_suppressed_from_http_logs(
    device_name_environment,
    monkeypatch,
):
    handler = object.__new__(backend.ControlHandler)
    handler.path = "/api/spotify/device-name?private=SROVA_PRIVATE_QUERY"
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


def test_install_update_route_does_not_enter_device_name_branch():
    source = inspect.getsource(backend.ControlHandler.do_POST)
    branch_start = source.index("# -- Public Spotify Connect device name")
    branch_end = source.index("# -- Radio routes")
    device_name_branch = source[branch_start:branch_end]

    assert "/api/spotify/artifact/update" not in device_name_branch
    assert "install_or_update(" not in device_name_branch


# BF4_DAC_ABSENT_DEVICE_NAME_GUARD
def test_absent_dac_rejects_device_name_before_retire_or_persistence(
    device_name_environment,
    monkeypatch,
):
    events = []
    lifecycle = Lifecycle(events)
    app = _app(lifecycle=lifecycle)
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_spotify_selected_dac_available",
        lambda: False,
    )
    monkeypatch.setattr(
        backend,
        "_save_app_settings",
        lambda: pytest.fail("absent DAC must not persist device name"),
    )

    response = _post(
        "/api/spotify/device-name",
        {"device_name": "SROVA Living Room"},
    )

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_dac_unavailable",
    }
    assert lifecycle.retire_calls == 0
    assert events == []
    assert device_name_environment["spotify_device_name"] == ""
