import json
import os
import stat
import sys
import threading
import time

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend.qobuz import QobuzAuthError, QobuzBackend


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self._content = content

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_content(self, chunk_size=65536):
        for index in range(0, len(self._content), chunk_size):
            yield self._content[index:index + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeHttp:
    def __init__(self, get_responses=None, post_responses=None):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)


def make_backend(tmp_path, **kwargs):
    config = tmp_path / "config"
    cache = tmp_path / "cache"
    return QobuzBackend(
        config_dir=str(config),
        cache_dir=str(cache),
        **kwargs,
    )


def eligible_session(token="user-token"):
    return {
        "user_auth_token": token,
        "user": {
            "id": 42,
            "email": "private@example.invalid",
            "display_name": "Listener",
            "country_code": "IN",
            "language_code": "en",
            "credential": {
                "parameters": {
                    "short_label": "Studio",
                    "end_date": "2030-01-01",
                }
            },
        },
    }


def service_metadata():
    return {
        "version": 1,
        "bundle_url": "/resources/8.1.0-b019/bundle.js",
        "bundle_version": "8.1.0-b019",
        "app_id": "123456789",
        "private_key": "PrivateKey123",
        "app_secrets": ["CatalogSecret123"],
        "fetched_at": 1000,
    }


def test_default_status_is_signed_out_and_constructor_does_not_use_network(tmp_path):
    class NoNetwork:
        def get(self, *_args, **_kwargs):
            raise AssertionError("constructor attempted network")

        def post(self, *_args, **_kwargs):
            raise AssertionError("constructor attempted network")

    backend = make_backend(tmp_path, http_session=NoNetwork())
    status = backend.status()

    assert status["provider_id"] == "qobuz"
    assert status["display_name"] == "Qobuz"
    assert status["available"] is False
    assert status["authenticated"] is False
    assert status["usable"] is False
    assert status["auth_state"] == "signed_out"
    assert status["login_pending"] is False
    assert status["user"] is None
    assert status["capabilities"] == []


def test_listener_is_ipv4_loopback_only_and_ephemeral():
    listener = QobuzBackend._bind_login_listener()
    try:
        host, port = listener.getsockname()
        assert host == "127.0.0.1"
        assert 0 < port <= 65535
    finally:
        listener.close()


@pytest.mark.parametrize(
    ("request_line", "expected"),
    [
        ("GET /nonce?code_autorisation=abc%2Fdef HTTP/1.1", "abc/def"),
        ("GET /nonce?code=plain HTTP/1.1", "plain"),
        ("GET /wrong?code=plain HTTP/1.1", None),
        ("GET /?code=plain HTTP/1.1", None),
        ("POST /nonce?code=plain HTTP/1.1", None),
        ("malformed", None),
    ],
)
def test_callback_requires_matching_nonce_path(request_line, expected):
    assert QobuzBackend._parse_callback_request_line(request_line, "nonce") == expected


def test_second_login_start_reuses_the_single_pending_attempt(tmp_path, monkeypatch):
    backend = make_backend(tmp_path, http_session=FakeHttp(), auth_timeout=2)
    monkeypatch.setattr(backend, "_get_service_metadata", service_metadata)

    first = backend.start_login()
    thread = backend._login_thread
    second = backend.start_login()

    assert first == second
    assert first["pending"] is True
    assert first["callback_port"] > 0
    assert "state=" not in first["url"]
    assert "redirect_url=" in first["url"]
    assert backend.status()["auth_state"] == "login_pending"

    backend.logout()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert backend.status()["auth_state"] == "signed_out"


def test_expired_capture_is_bounded(tmp_path):
    backend = make_backend(tmp_path, http_session=FakeHttp())
    listener = backend._bind_login_listener()
    try:
        result = backend._capture_callback(
            listener,
            "nonce",
            threading.Event(),
            time.monotonic() - 1,
        )
    finally:
        listener.close()
    assert result is None


def test_service_metadata_is_extracted_and_cached_separately(tmp_path):
    login_html = (
        '<html><script src="/resources/8.1.0-b019/bundle.js"></script></html>'
    ).encode()
    bundle = (
        'production:{api:{appId:"123456789",other:1}'
        ' appSecret:"0123456789abcdef0123456789abcdef"'
        ' privateKey: "PrivateKey123"'
    ).encode()
    http = FakeHttp(
        get_responses=[
            FakeResponse(content=login_html),
            FakeResponse(content=bundle),
        ]
    )
    backend = make_backend(tmp_path, http_session=http, now=lambda: 1000)

    metadata = backend._get_service_metadata()

    assert metadata["version"] == 2
    assert metadata["app_id"] == "123456789"
    assert metadata["private_key"] == "PrivateKey123"
    assert metadata["app_secrets"] == [
        "0123456789abcdef0123456789abcdef"
    ]
    assert len(http.get_calls) == 2
    assert os.path.exists(backend._service_cache_file)
    assert not os.path.exists(backend._session_file)
    assert stat.S_IMODE(os.stat(backend._service_cache_file).st_mode) == 0o600


def test_catalog_secret_extraction_matches_qbz_bundle_layout():
    # Exact synthetic form of the pinned QBZ extraction
    # contract: seed + info + extras, remove final 44
    # characters, then base64-decode the remainder.
    encoded = "Y2F0YWxvZy1zaWduaW5nLXNlY3JldA=="

    bundle = (
        f'a.initialSeed("{encoded}",'
        'window.utimezone.berlin)'
        ' name:"x/Berlin",'
        f'info:"{"A" * 22}",'
        f'extras:"{"B" * 22}"'
    )

    assert QobuzBackend._extract_app_secrets(
        bundle
    ) == [
        "catalog-signing-secret"
    ]


def test_catalog_secret_simple_fallback():
    bundle = (
        'prefix '
        'appSecret:"0123456789abcdef0123456789abcdef" '
        'suffix'
    )

    assert QobuzBackend._extract_app_secrets(
        bundle
    ) == [
        "0123456789abcdef0123456789abcdef"
    ]


def test_q2_auth_cache_does_not_require_catalog_signing_secrets(
    tmp_path,
):
    class NoNetwork:
        def get(self, *_args, **_kwargs):
            raise AssertionError(
                "Q2-compatible cache unexpectedly used network"
            )

    backend = make_backend(
        tmp_path,
        http_session=NoNetwork(),
        now=lambda: 1000,
    )

    legacy = {
        "version": 1,
        "bundle_url": (
            "/resources/8.1.0-b019/bundle.js"
        ),
        "bundle_version": "8.1.0-b019",
        "app_id": "123456789",
        "private_key": "PrivateKey123",
        "fetched_at": 999,
    }

    backend._atomic_json_write(
        backend._service_cache_file,
        legacy,
    )

    backend._service_metadata = (
        backend._load_service_cache()
    )

    assert backend._get_service_metadata() == legacy


def test_q6_catalog_requirement_refreshes_legacy_cache(
    tmp_path,
):
    login_html = (
        '<html><script '
        'src="/resources/8.1.0-b019/bundle.js">'
        '</script></html>'
    ).encode()

    bundle = (
        'production:{api:{appId:"123456789",other:1}'
        ' appSecret:"fedcba9876543210fedcba9876543210"'
        ' privateKey: "PrivateKey123"'
    ).encode()

    http = FakeHttp(
        get_responses=[
            FakeResponse(content=login_html),
            FakeResponse(content=bundle),
        ]
    )

    backend = make_backend(
        tmp_path,
        http_session=http,
        now=lambda: 1000,
    )

    legacy = {
        "version": 1,
        "bundle_url": (
            "/resources/8.1.0-b019/bundle.js"
        ),
        "bundle_version": "8.1.0-b019",
        "app_id": "123456789",
        "private_key": "PrivateKey123",
        "fetched_at": 999,
    }

    backend._atomic_json_write(
        backend._service_cache_file,
        legacy,
    )

    backend._service_metadata = (
        backend._load_service_cache()
    )

    metadata = backend._get_service_metadata(
        require_app_secrets=True
    )

    assert metadata["version"] == 2

    assert metadata["app_secrets"] == [
        "fedcba9876543210fedcba9876543210"
    ]

    assert len(http.get_calls) == 2


def test_q6_catalog_requirement_fails_closed_without_signing_secret(
    tmp_path,
):
    login_html = (
        '<html><script '
        'src="/resources/8.1.0-b020/bundle.js">'
        '</script></html>'
    ).encode()

    bundle = (
        'production:{api:{appId:"123456789",other:1}'
        ' privateKey: "PrivateKey123"'
    ).encode()

    http = FakeHttp(
        get_responses=[
            FakeResponse(content=login_html),
            FakeResponse(content=bundle),
        ]
    )

    backend = make_backend(
        tmp_path,
        http_session=http,
        now=lambda: 1000,
    )

    with pytest.raises(
        QobuzAuthError,
        match="catalog signing metadata",
    ):
        backend._get_service_metadata(
            require_app_secrets=True
        )

    assert backend.authenticated is False


def test_persist_restore_and_logout_round_trip(tmp_path, monkeypatch):
    first = make_backend(tmp_path, http_session=FakeHttp())
    first._persist_session("saved-token")
    assert stat.S_IMODE(os.stat(first._session_file).st_mode) == 0o600

    http = FakeHttp(post_responses=[FakeResponse(payload=eligible_session("saved-token"))])
    restored = make_backend(tmp_path, http_session=http)
    monkeypatch.setattr(restored, "_get_service_metadata", service_metadata)

    assert restored.restore_session() is True
    status = restored.status()
    assert status["authenticated"] is True
    assert status["usable"] is True
    assert status["auth_state"] == "authenticated"
    assert status["user"] == {
        "display_name": "Listener",
        "subscription": "Studio",
        "subscription_valid_until": "2030-01-01",
        "country_code": "IN",
        "language_code": "en",
    }
    assert "user_auth_token" not in json.dumps(status)
    assert "private@example.invalid" not in json.dumps(status)

    assert restored.logout() is True
    assert not os.path.exists(restored._session_file)
    assert os.path.exists(restored._service_cache_file) is False
    assert restored.status()["auth_state"] == "signed_out"


def test_invalid_restored_token_is_cleared(tmp_path, monkeypatch):
    backend = make_backend(
        tmp_path,
        http_session=FakeHttp(post_responses=[FakeResponse(status_code=401)]),
    )
    backend._persist_session("rejected-token")
    monkeypatch.setattr(backend, "_get_service_metadata", service_metadata)

    assert backend.restore_session() is False
    assert not os.path.exists(backend._session_file)
    assert backend.status()["auth_state"] == "error"
    assert "rejected-token" not in json.dumps(backend.status())


def test_network_restore_failure_keeps_token_for_retry(tmp_path, monkeypatch):
    backend = make_backend(tmp_path, http_session=FakeHttp())
    backend._persist_session("keep-on-network-error")

    def fail_metadata():
        raise RuntimeError("offline")

    monkeypatch.setattr(backend, "_get_service_metadata", fail_metadata)
    assert backend.restore_session() is False
    assert os.path.exists(backend._session_file)
    assert "keep-on-network-error" not in json.dumps(backend.status())


def test_corrupt_state_fails_safely_and_logout_can_clear_it(tmp_path):
    backend = make_backend(tmp_path, http_session=FakeHttp())
    os.makedirs(os.path.dirname(backend._session_file), exist_ok=True)
    with open(backend._session_file, "w", encoding="utf-8") as handle:
        handle.write("not-json")

    assert backend.restore_session() is False
    assert backend.status()["auth_state"] == "error"
    assert backend.logout() is True
    assert not os.path.exists(backend._session_file)


def test_user_session_requires_subscription_and_never_exposes_email():
    payload = eligible_session()
    parsed = QobuzBackend._parse_user_session(payload, "fallback")
    assert parsed["subscription"] == "Studio"

    payload["user"]["credential"]["parameters"] = {}
    with pytest.raises(Exception):
        QobuzBackend._parse_user_session(payload, "fallback")


def test_qobuz_backend_keeps_q2_auth_independent_from_tidal_and_player():
    source_path = os.path.join(os.path.dirname(__file__), "..", "src", "backend", "qobuz.py")
    source = open(source_path, "r", encoding="utf-8").read().lower()

    assert "tidal" not in source
    assert "player.load" not in source


def test_headless_exposes_q2_routes_and_q7i_completion_route():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    source = open(
        os.path.join(root, "src", "main_headless.py"),
        "r",
        encoding="utf-8",
    ).read()

    for route in (
        "/qobuz/status",
        "/qobuz/login/start",
        "/qobuz/login/poll",
        "/qobuz/login/complete",
        "/qobuz/logout",
    ):
        assert route in source
    assert "_QOBUZ_OAUTH_LOCK" not in source
    assert "_QOBUZ_OAUTH_FUTURE" not in source


def test_desktop_and_headless_startup_restore_qobuz_independently():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    headless = open(
        os.path.join(root, "src", "main_headless.py"),
        "r",
        encoding="utf-8",
    ).read()
    lifecycle = open(
        os.path.join(root, "src", "app", "app_lifecycle.py"),
        "r",
        encoding="utf-8",
    ).read()

    assert "qobuz_backend.restore_session()" in headless
    assert "qobuz_backend.restore_session()" in lifecycle


def test_headless_completion_relays_to_existing_q2_callback_worker(
    tmp_path,
    monkeypatch,
):
    http = FakeHttp(
        get_responses=[
            FakeResponse(
                payload={"token": "user-token"}
            )
        ],
        post_responses=[
            FakeResponse(
                payload=eligible_session("user-token")
            )
        ],
    )

    backend = make_backend(
        tmp_path,
        http_session=http,
        auth_timeout=3,
    )

    monkeypatch.setattr(
        backend,
        "_get_service_metadata",
        service_metadata,
    )

    started = backend.start_login()
    thread = backend._login_thread

    callback_url = (
        "http://localhost:"
        f"{started['callback_port']}/"
        f"{backend._login_nonce}"
        "?code_autorisation=bridge-code"
    )

    result = backend.complete_login(
        started["attempt_id"],
        callback_url,
    )

    assert result["accepted"] is True
    assert result["pending"] is True

    assert (
        "bridge-code"
        not in json.dumps(result)
    )

    thread.join(timeout=3)
    assert not thread.is_alive()

    status = backend.status()

    assert status["authenticated"] is True
    assert (
        status["auth_state"]
        == "authenticated"
    )

    assert (
        status["user"]["display_name"]
        == "Listener"
    )

    assert os.path.exists(
        backend._session_file
    )

    assert http.get_calls

    exchange_kwargs = http.get_calls[0][1]

    assert (
        exchange_kwargs["params"]["code"]
        == "bridge-code"
    )


def test_headless_completion_rejects_wrong_attempt_without_ending_login(
    tmp_path,
    monkeypatch,
):
    backend = make_backend(
        tmp_path,
        http_session=FakeHttp(),
        auth_timeout=3,
    )

    monkeypatch.setattr(
        backend,
        "_get_service_metadata",
        service_metadata,
    )

    started = backend.start_login()
    thread = backend._login_thread

    callback_url = (
        "http://localhost:"
        f"{started['callback_port']}/"
        f"{backend._login_nonce}"
        "?code=valid-code"
    )

    result = backend.complete_login(
        "wrong-attempt",
        callback_url,
    )

    assert result["accepted"] is False
    assert result["pending"] is True

    assert (
        backend.status()["auth_state"]
        == "login_pending"
    )

    backend.logout()
    thread.join(timeout=3)

    assert not thread.is_alive()


@pytest.mark.parametrize(
    "callback_builder",
    [
        lambda port, nonce: (
            f"http://example.com:{port}/{nonce}?code=x"
        ),
        lambda port, nonce: (
            f"https://localhost:{port}/{nonce}?code=x"
        ),
        lambda port, nonce: (
            f"http://localhost:{port + 1}/{nonce}?code=x"
        ),
        lambda port, nonce: (
            f"http://localhost:{port}/wrong-nonce?code=x"
        ),
        lambda port, nonce: (
            f"http://localhost:{port}/{nonce}"
        ),
        lambda port, nonce: (
            f"http://localhost:{port}/{nonce}?code=x#fragment"
        ),
    ],
)
def test_headless_completion_rejects_untrusted_or_incomplete_url(
    tmp_path,
    monkeypatch,
    callback_builder,
):
    backend = make_backend(
        tmp_path,
        http_session=FakeHttp(),
        auth_timeout=3,
    )

    monkeypatch.setattr(
        backend,
        "_get_service_metadata",
        service_metadata,
    )

    started = backend.start_login()
    thread = backend._login_thread

    result = backend.complete_login(
        started["attempt_id"],
        callback_builder(
            started["callback_port"],
            backend._login_nonce,
        ),
    )

    assert result["accepted"] is False
    assert result["pending"] is True

    assert (
        backend.status()["auth_state"]
        == "login_pending"
    )

    backend.logout()
    thread.join(timeout=3)

    assert not thread.is_alive()


def test_headless_completion_never_exposes_nonce_or_callback_material(
    tmp_path,
    monkeypatch,
):
    backend = make_backend(
        tmp_path,
        http_session=FakeHttp(),
        auth_timeout=3,
    )

    monkeypatch.setattr(
        backend,
        "_get_service_metadata",
        service_metadata,
    )

    started = backend.start_login()
    thread = backend._login_thread

    nonce = backend._login_nonce

    status_json = json.dumps(
        backend.status()
    )

    poll_json = json.dumps(
        backend.poll_login(
            started["attempt_id"]
        )
    )

    assert nonce not in status_json
    assert nonce not in poll_json

    backend.logout()
    thread.join(timeout=3)

    assert not thread.is_alive()
