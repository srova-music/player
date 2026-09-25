import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402


TEST_KEY = "SROVA_TEST_ONLY_SPOTIFY_API_KEY-12345"
QUERY_SECRET = "SROVA_TEST_ONLY_QUERY_SECRET_MUST_NOT_LOG"
FAILURE_SECRET = "SROVA_TEST_ONLY_FAILURE_DETAIL_MUST_NOT_LEAK"


class FakeSecretStore:
    def __init__(self):
        self.saved = None
        self.calls = 0

    def set_api_key(self, value):
        self.calls += 1
        self.saved = value

    def key_configured(self):
        return self.saved is not None


class BrokenSecretStore:
    def set_api_key(self, value):
        raise RuntimeError(FAILURE_SECRET)

    def key_configured(self):
        raise RuntimeError(FAILURE_SECRET)


def _post_raw(
    monkeypatch,
    path,
    raw_body,
    *,
    content_type="application/json",
    content_length=None,
    store=None,
):
    handler = object.__new__(backend.ControlHandler)
    handler.path = path

    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")

    handler.rfile = io.BytesIO(raw_body)
    handler.headers = {}

    if content_type is not None:
        handler.headers["Content-Type"] = content_type

    if content_length is None:
        content_length = len(raw_body)

    handler.headers["Content-Length"] = str(content_length)

    response = {}

    def send_json(payload, no_store=False):
        response.update(
            status=200,
            payload=payload,
            no_store=no_store,
        )

    def send_error(status, message=None, explain=None):
        response.update(
            status=status,
            message=message,
            explain=explain,
        )

    handler._send_json = send_json
    handler.send_error = send_error

    app = SimpleNamespace(
        spotify_secret_store=(
            store
            if store is not None
            else FakeSecretStore()
        )
    )

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        app,
    )

    handler.do_POST()

    return response, app.spotify_secret_store


def _post_json(
    monkeypatch,
    path,
    payload,
    **kwargs,
):
    return _post_raw(
        monkeypatch,
        path,
        json.dumps(payload).encode("utf-8"),
        **kwargs,
    )


def test_exact_config_post_saves_key_without_echo(monkeypatch):
    response, store = _post_json(
        monkeypatch,
        "/api/spotify/config",
        {"api_key": TEST_KEY},
    )

    assert store.saved == TEST_KEY
    assert response == {
        "status": 200,
        "payload": {
            "ok": True,
            "key_configured": True,
        },
        "no_store": True,
    }
    assert TEST_KEY not in repr(response)


def test_config_query_string_is_rejected_before_secret_store(monkeypatch):
    store = FakeSecretStore()

    response, store = _post_json(
        monkeypatch,
        "/api/spotify/config?api_key=" + QUERY_SECRET,
        {"api_key": TEST_KEY},
        store=store,
    )

    assert store.calls == 0
    assert response["payload"] == {
        "ok": False,
        "error": "invalid_request",
    }
    assert response["no_store"] is True
    assert QUERY_SECRET not in repr(response)


def test_config_rejects_extra_fields(monkeypatch):
    response, store = _post_json(
        monkeypatch,
        "/api/spotify/config",
        {
            "api_key": TEST_KEY,
            "extra": "not-allowed",
        },
    )

    assert store.calls == 0
    assert response["payload"]["ok"] is False
    assert response["payload"]["error"] == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"api_key": None},
        {"api_key": 123},
        {"api_key": ""},
    ],
)
def test_config_rejects_invalid_key_payloads(monkeypatch, payload):
    class ValidatingStore(FakeSecretStore):
        def set_api_key(self, value):
            if not isinstance(value, str) or not value:
                raise ValueError("invalid")
            super().set_api_key(value)

    response, store = _post_json(
        monkeypatch,
        "/api/spotify/config",
        payload,
        store=ValidatingStore(),
    )

    assert response["payload"]["ok"] is False
    assert response["payload"]["error"] in {
        "invalid_request",
        "invalid_api_key",
    }
    assert store.saved is None


def test_config_requires_json_content_type(monkeypatch):
    response, store = _post_json(
        monkeypatch,
        "/api/spotify/config",
        {"api_key": TEST_KEY},
        content_type="text/plain",
    )

    assert store.calls == 0
    assert response["payload"] == {
        "ok": False,
        "error": "invalid_request",
    }


def test_config_accepts_json_content_type_with_charset(monkeypatch):
    response, store = _post_json(
        monkeypatch,
        "/api/spotify/config",
        {"api_key": TEST_KEY},
        content_type="application/json; charset=utf-8",
    )

    assert store.saved == TEST_KEY
    assert response["payload"]["key_configured"] is True


def test_config_body_size_is_bounded_before_read(monkeypatch):
    handler = object.__new__(backend.ControlHandler)
    handler.path = "/api/spotify/config"

    class NoRead:
        def read(self, length):
            raise AssertionError(
                "oversized Spotify body was read"
            )

    handler.rfile = NoRead()
    handler.headers = {
        "Content-Type": "application/json",
        "Content-Length": "16385",
    }

    response = {}

    handler._send_json = lambda payload, no_store=False: response.update(
        status=200,
        payload=payload,
        no_store=no_store,
    )
    handler.send_error = lambda *args, **kwargs: response.update(
        status=args[0] if args else 500
    )

    store = FakeSecretStore()
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(
            spotify_secret_store=store,
        ),
    )

    handler.do_POST()

    assert store.calls == 0
    assert response == {
        "status": 200,
        "payload": {
            "ok": False,
            "error": "request_too_large",
        },
        "no_store": True,
    }


def test_malformed_json_does_not_reach_secret_store(monkeypatch):
    raw = (
        '{"api_key":"'
        + TEST_KEY
        + '"'
    )

    response, store = _post_raw(
        monkeypatch,
        "/api/spotify/config",
        raw,
    )

    assert store.calls == 0
    assert response["payload"] == {
        "ok": False,
        "error": "invalid_request",
    }
    assert TEST_KEY not in repr(response)


def test_missing_secret_store_fails_without_echo(monkeypatch):
    handler = object.__new__(backend.ControlHandler)
    handler.path = "/api/spotify/config"

    body = json.dumps(
        {"api_key": TEST_KEY}
    ).encode("utf-8")

    handler.rfile = io.BytesIO(body)
    handler.headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }

    response = {}
    handler._send_json = lambda payload, no_store=False: response.update(
        status=200,
        payload=payload,
        no_store=no_store,
    )
    handler.send_error = lambda *args, **kwargs: response.update(
        status=args[0] if args else 500
    )

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(),
    )

    handler.do_POST()

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_config_unavailable",
    }
    assert TEST_KEY not in repr(response)


def test_store_failure_does_not_leak_private_detail(monkeypatch):
    response, _store = _post_json(
        monkeypatch,
        "/api/spotify/config",
        {"api_key": TEST_KEY},
        store=BrokenSecretStore(),
    )

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_config_unavailable",
    }
    assert TEST_KEY not in repr(response)
    assert FAILURE_SECRET not in repr(response)


def test_config_route_log_is_suppressed_even_with_query_secret(
    monkeypatch,
):
    handler = object.__new__(backend.ControlHandler)
    handler.path = (
        "/api/spotify/config?api_key="
        + QUERY_SECRET
    )
    handler.address_string = lambda: "127.0.0.1"

    calls = []

    monkeypatch.setattr(
        backend.logger,
        "info",
        lambda *args, **kwargs: calls.append(
            (args, kwargs)
        ),
    )

    backend.ControlHandler.log_message(
        handler,
        '"%s" %s',
        handler.path,
        "404",
    )

    assert calls == []


def test_config_success_does_not_mutate_coordinator(monkeypatch):
    coordinator = SimpleNamespace(
        marker="ownership-only",
    )
    store = FakeSecretStore()

    handler = object.__new__(backend.ControlHandler)
    handler.path = "/api/spotify/config"

    body = json.dumps(
        {"api_key": TEST_KEY}
    ).encode("utf-8")

    handler.rfile = io.BytesIO(body)
    handler.headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }

    response = {}
    handler._send_json = lambda payload, no_store=False: response.update(
        payload=payload,
        no_store=no_store,
    )
    handler.send_error = lambda *args, **kwargs: None

    app = SimpleNamespace(
        spotify_coordinator=coordinator,
        spotify_secret_store=store,
    )

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        app,
    )

    before = dict(vars(coordinator))
    handler.do_POST()

    assert vars(coordinator) == before
    assert store.saved == TEST_KEY
    assert "api_key" not in vars(coordinator)
