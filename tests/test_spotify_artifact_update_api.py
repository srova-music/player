import inspect
import io
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402


UPDATE_PATH = "/api/spotify/artifact/update"
PRIVATE_DETAIL = "SROVA_PRIVATE_URL_PATH_SHA_PID_PORT_MUST_NOT_LEAK"
CONTROLLED_ERROR_CODES = {
    "unsupported_architecture",
    "unsafe_install_directory",
    "download_failed",
    "unexpected_response",
    "download_too_large",
    "invalid_archive",
    "invalid_candidate",
    "candidate_expired",
    "downgrade_rejected",
    "same_build_conflict",
    "commit_failed",
}


class Installer:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def install_or_update(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


class NoRead(io.BytesIO):
    def read(self, *_args, **_kwargs):
        raise AssertionError("artifact update bridge must not read a request body")


def _result(*, success=True, changed=True, action="installed", error_code=None):
    return SimpleNamespace(
        success=success,
        changed=changed,
        action=action,
        error_code=error_code,
        binary_sha256="b" * 64,
        archive_sha256="a" * 64,
        filesystem_path="/private/managed/soloist",
        download_url="https://private.invalid/soloist.tar.gz",
        private_detail=PRIVATE_DETAIL,
    )


def _app(installer):
    return SimpleNamespace(
        spotify_managed=SimpleNamespace(
            installer=installer,
            soloist_supervisor=SimpleNamespace(
                start=lambda: pytest.fail("supervisor start must not be called"),
                stop=lambda: pytest.fail("supervisor stop must not be called"),
            ),
        ),
        spotify_secret_store=SimpleNamespace(
            key_configured=lambda: pytest.fail("secret store must not be read"),
            get_api_key=lambda: pytest.fail("secret store must not be read"),
        ),
        spotify_coordinator=SimpleNamespace(
            transition=lambda *_args: pytest.fail("coordinator must not mutate"),
        ),
        spotify_orchestrator=SimpleNamespace(
            disable=lambda: pytest.fail("orchestrator must not retire"),
        ),
        spotify_runtime=SimpleNamespace(
            start=lambda: pytest.fail("runtime must not start"),
            stop=lambda: pytest.fail("runtime must not stop"),
        ),
        spotify_firewall_manager=SimpleNamespace(
            prepare=lambda *_args: pytest.fail("firewall must not change"),
        ),
    )


def _post(monkeypatch, installer, *, path=UPDATE_PATH, content_length=None):
    handler = object.__new__(backend.ControlHandler)
    handler.path = path
    handler.headers = {}
    if content_length is not None:
        handler.headers["Content-Length"] = str(content_length)
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
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(installer))
    handler.do_POST()
    return response


@pytest.mark.parametrize(
    ("action", "changed"),
    [
        ("installed", True),
        ("updated", True),
        ("unchanged", False),
    ],
)
def test_exact_post_maps_success_to_minimal_public_contract(
    monkeypatch,
    action,
    changed,
):
    installer = Installer(_result(action=action, changed=changed))

    response = _post(monkeypatch, installer)

    assert installer.calls == [((), {})]
    assert response == {
        "status": 200,
        "payload": {
            "ok": True,
            "changed": changed,
            "action": action,
        },
        "no_store": True,
    }
    serialized = repr(response)
    for private_value in (
        "binary_sha256",
        "archive_sha256",
        "/private/managed/soloist",
        "private.invalid",
        PRIVATE_DETAIL,
    ):
        assert private_value not in serialized


def test_zero_content_length_is_accepted_without_reading_body(monkeypatch):
    installer = Installer(_result())

    response = _post(monkeypatch, installer, content_length=0)

    assert response["payload"]["ok"] is True
    assert installer.calls == [((), {})]


def test_successful_install_update_invalidates_update_status_cache(monkeypatch):
    installer = Installer(_result(action="updated"))
    monkeypatch.setattr(
        backend,
        "_SPOTIFY_ARTIFACT_UPDATE_STATUS_CACHE",
        {"stale": True},
    )

    response = _post(monkeypatch, installer)

    assert response["payload"]["ok"] is True
    assert backend._SPOTIFY_ARTIFACT_UPDATE_STATUS_CACHE is None


@pytest.mark.parametrize(
    "body",
    [
        b'x',
        b'{"url":"https://private.invalid/soloist"}',
        b'{"path":"/tmp/soloist"}',
        b'{"command":"run-me"}',
        b'{"architecture":"x86_64"}',
    ],
    ids=["arbitrary", "url", "path", "command", "architecture"],
)
def test_nonzero_request_body_is_rejected_without_reading(monkeypatch, body):
    installer = Installer(_result())

    response = _post(monkeypatch, installer, content_length=len(body))

    assert response["payload"] == {"ok": False, "error": "invalid_request"}
    assert response["no_store"] is True
    assert installer.calls == []
    assert PRIVATE_DETAIL not in repr(response)


@pytest.mark.parametrize("content_length", ["invalid", -1])
def test_invalid_content_length_is_rejected(monkeypatch, content_length):
    installer = Installer(_result())

    response = _post(monkeypatch, installer, content_length=content_length)

    assert response["payload"] == {"ok": False, "error": "invalid_request"}
    assert installer.calls == []


def test_query_string_is_rejected_before_installer(monkeypatch):
    installer = Installer(_result())

    response = _post(
        monkeypatch,
        installer,
        path=UPDATE_PATH + "?url=" + PRIVATE_DETAIL,
    )

    assert response["payload"] == {"ok": False, "error": "invalid_request"}
    assert installer.calls == []
    assert PRIVATE_DETAIL not in repr(response)


def test_rejected_query_material_is_suppressed_from_http_logs(monkeypatch):
    handler = object.__new__(backend.ControlHandler)
    handler.path = UPDATE_PATH + "?url=" + PRIVATE_DETAIL
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
        "200",
    )

    assert calls == []


def test_get_update_path_is_unavailable(monkeypatch):
    installer = Installer(_result())
    handler = object.__new__(backend.ControlHandler)
    handler.path = UPDATE_PATH
    response = {}
    handler.send_error = lambda status, *args, **kwargs: response.update(
        status=status,
    )
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(installer))

    handler.do_GET()

    assert response == {"status": 404}
    assert installer.calls == []


@pytest.mark.parametrize("error_code", sorted(CONTROLLED_ERROR_CODES))
def test_controlled_installer_failures_expose_only_bounded_code(
    monkeypatch,
    error_code,
):
    installer = Installer(
        _result(
            success=False,
            changed=False,
            action="unchanged",
            error_code=error_code,
        )
    )

    response = _post(monkeypatch, installer)

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_soloist_install_update_failed",
        "error_code": error_code,
    }
    assert set(response["payload"]) == {"ok", "error", "error_code"}
    assert PRIVATE_DETAIL not in repr(response)


def test_unexpected_exception_collapses_to_generic_public_error(monkeypatch):
    installer = Installer(error=RuntimeError(PRIVATE_DETAIL))

    response = _post(monkeypatch, installer)

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_soloist_install_update_failed",
    }
    assert PRIVATE_DETAIL not in repr(response)


@pytest.mark.parametrize(
    "result",
    [
        None,
        _result(success=True, changed=False, action="installed"),
        _result(success=False, error_code="private_internal_failure"),
    ],
    ids=["missing", "invalid-success", "unbounded-error"],
)
def test_invalid_internal_result_collapses_to_generic_public_error(
    monkeypatch,
    result,
):
    response = _post(monkeypatch, Installer(result))

    assert response["payload"] == {
        "ok": False,
        "error": "spotify_soloist_install_update_failed",
    }
    assert "private_internal_failure" not in repr(response)


def test_bridge_uses_same_managed_installer_without_constructing_another(
    monkeypatch,
):
    installer = Installer(_result())
    monkeypatch.setattr(
        backend,
        "build_spotify_managed_components",
        lambda *_args, **_kwargs: pytest.fail("must not construct another installer"),
    )

    first = _post(monkeypatch, installer)
    second = _post(monkeypatch, installer)

    assert first["payload"]["ok"] is True
    assert second["payload"]["ok"] is True
    assert installer.calls == [((), {}), ((), {})]


def test_concurrent_bridge_calls_reach_same_managed_installer(monkeypatch):
    barrier = threading.Barrier(2)
    installer_ids = []

    class ConcurrentInstaller:
        def install_or_update(self):
            installer_ids.append(id(self))
            barrier.wait(timeout=2)
            return _result()

    installer = ConcurrentInstaller()
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(installer))
    monkeypatch.setattr(
        backend,
        "build_spotify_managed_components",
        lambda *_args, **_kwargs: pytest.fail("must not construct another installer"),
    )

    def invoke():
        handler = object.__new__(backend.ControlHandler)
        handler.path = UPDATE_PATH
        handler.headers = {}
        handler.rfile = NoRead()
        response = {}
        handler._send_json = lambda payload, no_store=False: response.update(
            payload=payload,
            no_store=no_store,
        )
        handler.send_error = lambda *_args, **_kwargs: pytest.fail(
            "exact update route must not send an HTTP error"
        )
        handler.do_POST()
        return response

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: invoke(), range(2)))

    assert installer_ids == [id(installer), id(installer)]
    assert all(response["payload"]["ok"] is True for response in responses)


def test_bridge_has_no_alternate_installer_or_lifecycle_activation_surface():
    source = inspect.getsource(backend.ControlHandler.do_POST)
    route_start = source.index("# -- Managed Spotify artifact install/update")
    route_end = source.index("# -- Spotify endpoint production control")
    route_source = source[route_start:route_end]

    assert route_source.count("install_or_update()") == 1
    assert "SpotifySoloistInstaller(" not in route_source
    assert "build_spotify_managed_components(" not in route_source
    for forbidden in (
        "spotify_secret_store",
        "spotify_coordinator",
        "spotify_orchestrator",
        "soloist_supervisor",
        "spotify_runtime",
        "firewall",
        "systemctl",
        "srova.service",
        "shell=True",
        "os.system",
    ):
        assert forbidden not in route_source
