import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
    ),
)

from backend.qobuz import QobuzBackend


ROOT = Path(
    os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
        )
    )
)

MAIN = (
    ROOT / "src" / "main_headless.py"
).read_text(
    encoding="utf-8"
)

UI = (
    ROOT / "src" / "ui_web" / "ui.js"
).read_text(
    encoding="utf-8"
)

INDEX = (
    ROOT / "src" / "ui_web" / "index.html"
).read_text(
    encoding="utf-8"
)


class FakeResponse:
    def __init__(
        self,
        status_code=200,
        payload=None,
    ):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(
        self,
        get_responses=None,
        post_responses=None,
    ):
        self.get_responses = list(
            get_responses or []
        )
        self.post_responses = list(
            post_responses or []
        )
        self.get_calls = []
        self.post_calls = []

    def get(
        self,
        url,
        **kwargs,
    ):
        self.get_calls.append(
            (
                url,
                kwargs,
            )
        )

        if not self.get_responses:
            raise AssertionError(
                "unexpected HTTP GET"
            )

        return self.get_responses.pop(0)

    def post(
        self,
        url,
        **kwargs,
    ):
        self.post_calls.append(
            (
                url,
                kwargs,
            )
        )

        if not self.post_responses:
            raise AssertionError(
                "unexpected HTTP POST"
            )

        return self.post_responses.pop(0)


def service_metadata():
    return {
        "version": 1,
        "bundle_url":
            "/resources/8.1.0-b019/bundle.js",
        "bundle_version":
            "8.1.0-b019",
        "app_id":
            "123456789",
        "private_key":
            "PrivateKey123",
        "app_secrets": [
            "CatalogSecret123",
        ],
        "fetched_at":
            1000,
    }


def eligible_session(
    token="user-token",
):
    return {
        "user_auth_token":
            token,
        "user": {
            "id":
                42,
            "display_name":
                "Listener",
            "country_code":
                "IN",
            "language_code":
                "en",
            "credential": {
                "parameters": {
                    "short_label":
                        "Studio",
                    "end_date":
                        "2030-01-01",
                }
            },
        },
    }


def make_backend(
    tmp_path,
    *,
    http_session=None,
    auth_timeout=3,
):
    return QobuzBackend(
        config_dir=str(
            tmp_path / "config"
        ),
        cache_dir=str(
            tmp_path / "cache"
        ),
        http_session=(
            http_session
            if http_session is not None
            else FakeHttp()
        ),
        auth_timeout=auth_timeout,
    )


def start_manual_attempt(
    backend,
    monkeypatch,
):
    monkeypatch.setattr(
        backend,
        "_get_service_metadata",
        service_metadata,
    )

    assert (
        backend.set_manual_callback_origin(
            "http://192.168.50.10:8081"
        )
        is True
    )

    started = backend.start_login()

    return (
        started,
        backend._login_thread,
        backend._login_nonce,
    )


def redirect_from_authorize_url(
    authorize_url,
):
    parsed = urlsplit(
        authorize_url
    )

    query = parse_qs(
        parsed.query
    )

    values = (
        query.get(
            "redirect_url"
        )
        or []
    )

    assert len(values) == 1

    return values[0]


def test_q10d_one_attempt_returns_unchanged_remote_url_and_manual_url(
    tmp_path,
    monkeypatch,
):
    backend = make_backend(
        tmp_path
    )

    started, thread, nonce = (
        start_manual_attempt(
            backend,
            monkeypatch,
        )
    )

    remote_redirect = (
        redirect_from_authorize_url(
            started["url"]
        )
    )

    manual_redirect = (
        redirect_from_authorize_url(
            started["manual_url"]
        )
    )

    assert remote_redirect == (
        "http://localhost:"
        + str(
            started[
                "callback_port"
            ]
        )
        + "/"
        + nonce
    )

    assert manual_redirect == (
        "http://192.168.50.10:8081"
        + backend.MANUAL_CALLBACK_PREFIX
        + nonce
    )

    assert (
        backend.start_login()
        == started
    )

    backend.logout()

    thread.join(
        timeout=3
    )

    assert not thread.is_alive()


def test_q10d_manual_origin_fails_closed_for_untrusted_origins(
    tmp_path,
):
    backend = make_backend(
        tmp_path
    )

    for origin in (
        "http://8.8.8.8:8081",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "https://192.168.50.10:8081",
        "http://example.com:8081",
        "http://192.168.50.10:8081/path",
    ):
        assert (
            backend._normalise_manual_callback_origin(
                origin
            )
            == ""
        )


def test_q10d_manual_callback_get_is_non_consuming(
    tmp_path,
    monkeypatch,
):
    http = FakeHttp()

    backend = make_backend(
        tmp_path,
        http_session=http,
    )

    _started, thread, nonce = (
        start_manual_attempt(
            backend,
            monkeypatch,
        )
    )

    request_target = (
        backend.MANUAL_CALLBACK_PREFIX
        + nonce
        + "?code_autorisation="
        + "presentation-code"
    )

    assert (
        backend.manual_callback_request_valid(
            request_target
        )
        is True
    )

    assert thread.is_alive()

    status = backend.status()

    assert (
        status["auth_state"]
        == "login_pending"
    )

    assert (
        status["authenticated"]
        is False
    )

    assert http.get_calls == []
    assert http.post_calls == []

    backend.logout()

    thread.join(
        timeout=3
    )

    assert not thread.is_alive()


def test_q10d_manual_callback_get_rejects_invalid_nonce_or_code(
    tmp_path,
    monkeypatch,
):
    backend = make_backend(
        tmp_path
    )

    _started, thread, nonce = (
        start_manual_attempt(
            backend,
            monkeypatch,
        )
    )

    invalid_targets = (
        (
            backend.MANUAL_CALLBACK_PREFIX
            + "0" * 48
            + "?code=x"
        ),
        (
            backend.MANUAL_CALLBACK_PREFIX
            + nonce
        ),
        (
            backend.MANUAL_CALLBACK_PREFIX
            + nonce
            + "?code="
        ),
        (
            backend.MANUAL_CALLBACK_PREFIX
            + nonce
            + "?other=x"
        ),
        (
            "/wrong/"
            + nonce
            + "?code=x"
        ),
    )

    for target in invalid_targets:
        assert (
            backend.manual_callback_request_valid(
                target
            )
            is False
        )

    assert (
        backend.status()[
            "auth_state"
        ]
        == "login_pending"
    )

    backend.logout()

    thread.join(
        timeout=3
    )

    assert not thread.is_alive()


def test_q10d_valid_manual_paste_reuses_existing_worker(
    tmp_path,
    monkeypatch,
):
    http = FakeHttp(
        get_responses=[
            FakeResponse(
                payload={
                    "token":
                        "user-token",
                }
            ),
        ],
        post_responses=[
            FakeResponse(
                payload=eligible_session(
                    "user-token"
                )
            ),
        ],
    )

    backend = make_backend(
        tmp_path,
        http_session=http,
    )

    started, thread, nonce = (
        start_manual_attempt(
            backend,
            monkeypatch,
        )
    )

    callback_url = (
        "http://192.168.50.10:8081"
        + backend.MANUAL_CALLBACK_PREFIX
        + nonce
        + "?code_autorisation="
        + "manual-code"
    )

    result = backend.complete_login(
        started[
            "attempt_id"
        ],
        callback_url,
    )

    assert (
        result["accepted"]
        is True
    )

    assert (
        result["pending"]
        is True
    )

    assert (
        "manual-code"
        not in json.dumps(
            result
        )
    )

    thread.join(
        timeout=3
    )

    assert not thread.is_alive()

    status = backend.status()

    assert (
        status["authenticated"]
        is True
    )

    assert (
        status["auth_state"]
        == "authenticated"
    )

    assert http.get_calls

    exchange_kwargs = (
        http.get_calls[0][1]
    )

    assert (
        exchange_kwargs[
            "params"
        ]["code"]
        == "manual-code"
    )

    backend.logout()


def test_q10d_manual_complete_validation_is_additive_and_exact(
    tmp_path,
    monkeypatch,
):
    backend = make_backend(
        tmp_path
    )

    started, thread, nonce = (
        start_manual_attempt(
            backend,
            monkeypatch,
        )
    )

    valid = (
        "http://192.168.50.10:8081"
        + backend.MANUAL_CALLBACK_PREFIX
        + nonce
        + "?code=x"
    )

    invalid_urls = (
        valid.replace(
            "192.168.50.10",
            "192.168.50.11",
            1,
        ),
        valid.replace(
            ":8081",
            ":8082",
            1,
        ),
        valid.replace(
            backend.MANUAL_CALLBACK_PREFIX,
            "/wrong/",
            1,
        ),
        valid.replace(
            "http://",
            "https://",
            1,
        ),
        valid + "#fragment",
        valid.split(
            "?",
            1,
        )[0],
    )

    for callback_url in invalid_urls:
        result = backend.complete_login(
            started[
                "attempt_id"
            ],
            callback_url,
        )

        assert (
            result["accepted"]
            is False
        )

        assert (
            result["pending"]
            is True
        )

    wrong_attempt = (
        backend.complete_login(
            "wrong-attempt",
            valid,
        )
    )

    assert (
        wrong_attempt[
            "accepted"
        ]
        is False
    )

    assert (
        wrong_attempt[
            "pending"
        ]
        is True
    )

    assert (
        backend.status()[
            "auth_state"
        ]
        == "login_pending"
    )

    backend.logout()

    thread.join(
        timeout=3
    )

    assert not thread.is_alive()


def test_q10d_headless_origin_is_server_owned_not_request_derived():
    start = MAIN.index(
        "def _qobuz_manual_callback_origin():"
    )

    end = MAIN.index(
        "class ControlHandler",
        start,
    )

    block = MAIN[
        start:end
    ]

    assert (
        "_load_srova_env_lan_address()"
        in block
    )

    assert (
        "_get_lan_ip()"
        in block
    )

    assert (
        "probe.bind("
        in block
    )

    for forbidden in (
        "self.headers",
        "X-Forwarded-Host",
        "Referer",
    ):
        assert (
            forbidden
            not in block
        )


def test_q10d_start_adds_manual_origin_without_replacing_start_login():
    start = MAIN.index(
        'if static_path == "/qobuz/login/start":'
    )

    end = MAIN.index(
        'if static_path == "/qobuz/login/poll":',
        start,
    )

    block = MAIN[
        start:end
    ]

    assert (
        "backend.set_manual_callback_origin("
        in block
    )

    assert (
        "_qobuz_manual_callback_origin()"
        in block
    )

    assert (
        "backend.start_login()"
        in block
    )


def test_q10d_callback_page_is_hardened_and_non_consuming():
    assert (
        '"/qobuz/login/callback/"'
        in MAIN
    )

    assert (
        "backend.manual_callback_request_valid("
        in MAIN
    )

    assert (
        "<h1>Sign-in complete</h1>"
        in MAIN
    )

    assert (
        "Copy the full URL shown in your "
        in MAIN
    )

    assert (
        "browser's address bar."
        in MAIN
    )

    assert (
        "Paste it into the open SROVA popup "
        in MAIN
    )

    assert (
        "to finish signing in."
        in MAIN
    )

    assert (
        "<h1>Sign-in couldn't be completed</h1>"
        in MAIN
    )

    assert (
        "qobuzHandoffBody"
        in MAIN
    )

    assert (
        "qobuzHandoffCard"
        in MAIN
    )

    for header in (
        '"Cache-Control",',
        '"Pragma",',
        '"Referrer-Policy",',
        '"X-Content-Type-Options",',
    ):
        assert (
            header
            in MAIN
        )

    assert (
        "style-src 'self'"
        in MAIN
    )

    assert (
        "img-src 'self'"
        in MAIN
    )

    route_start = MAIN.index(
        "# -- Q10D manual Qobuz browser callback"
    )

    route_end = MAIN.index(
        "# -- Audio output / DAC preference",
        route_start,
    )

    route = MAIN[
        route_start:
        route_end
    ]

    assert (
        "_exchange_code"
        not in route
    )

    assert (
        "_persist_session"
        not in route
    )

    assert (
        "complete_login("
        not in route
    )


def test_q10d_callback_request_line_is_suppressed_from_normal_http_log():
    start = MAIN.index(
        "    def log_message("
    )

    end = MAIN.index(
        "    def _send_json(",
        start,
    )

    block = MAIN[
        start:end
    ]

    assert (
        '"/qobuz/login/callback/"'
        in block
    )

    assert (
        "return"
        in block
    )


def test_q10d_ui_uses_explicit_manual_link_without_client_guessing():
    assert (
        "function setQobuzManualLoginUrl("
        in UI
    )

    assert (
        '"qobuzManualLoginUrl"'
        in UI
    )

    assert (
        '"Manual browser sign-in"'
        in UI
    )

    assert (
        "data.manual_url"
        in UI
    )

    start = UI.index(
        "function startQobuzLogin("
    )

    end = UI.index(
        "function cancelQobuzLogin(",
        start,
    )

    block = UI[
        start:end
    ]

    assert (
        "String(data.url)"
        in block
    )

    assert (
        "data.manual_url"
        in block
    )

    assert (
        "navigator.userAgent"
        not in block
    )

    assert (
        "Android"
        not in block
    )


def test_q10d_index_advances_ui_cache_key():
    assert (
        "q10d_manual_browser_auth_js9"
        in INDEX
    )
