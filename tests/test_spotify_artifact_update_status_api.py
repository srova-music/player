import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402


UPDATE_STATUS_PATH = "/api/spotify/artifact/update-status"
PRIVATE_DETAIL = "PRIVATE_URL_PATH_HASH_MUST_NOT_LEAK"


def _snapshot(*, installed=True, valid=True, sha256="a" * 64):
    return {
        "installed": installed,
        "valid": valid if installed else False,
        "version": "1.3.8" if installed else None,
        "build_timestamp": 1789538504 if installed and valid else None,
        "build_date": "20260916" if installed and valid else None,
        "build_identifier": "private-build" if installed and valid else None,
        "platform": "linux" if installed and valid else None,
        "architecture": "x86_64" if installed and valid else None,
        "sha256": sha256 if installed and valid else None,
        "expires_at": "2026-12-15T00:00:00Z" if installed and valid else None,
        "expired": False if installed and valid else None,
        "seconds_remaining": 100 if installed and valid else None,
        "error_code": "valid" if installed and valid else (
            "invalid_file" if installed else "not_installed"
        ),
        "filesystem_path": "/private/soloist",
        "download_url": "https://private.invalid/soloist",
        "private_detail": PRIVATE_DETAIL,
    }


class Authority:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = 0

    def status_snapshot(self):
        self.calls += 1
        return dict(self.snapshot)


class Installer:
    def __init__(self, result, delay=0):
        self.result = result
        self.delay = delay
        self.calls = 0
        self.lock = threading.Lock()

    def check_for_update(self):
        with self.lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return self.result


def _result(*, available=False, ok=True):
    return SimpleNamespace(
        ok=ok,
        installed=True,
        update_available=available,
        error_code=(
            "update_available" if available else ("current" if ok else "check_failed")
        ),
        download_url="https://private.invalid/archive",
        sha256="b" * 64,
        filesystem_path="/private/candidate",
        private_detail=PRIVATE_DETAIL,
    )


def _app(authority, installer):
    return SimpleNamespace(
        spotify_managed=SimpleNamespace(
            artifact_authority=authority,
            installer=installer,
        )
    )


def _get(monkeypatch, authority, installer, path=UPDATE_STATUS_PATH):
    handler = object.__new__(backend.ControlHandler)
    handler.path = path
    response = {}
    handler._send_json = lambda payload, no_store=False: response.update(
        status=200,
        payload=payload,
        no_store=no_store,
    )
    handler.send_error = lambda status, *_args, **_kwargs: response.update(
        status=status,
    )
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(authority, installer))
    handler.do_GET()
    return response


@pytest.fixture(autouse=True)
def clear_cache():
    backend._invalidate_spotify_artifact_update_status_cache()
    yield
    backend._invalidate_spotify_artifact_update_status_cache()


def test_not_installed_is_false_and_does_not_invoke_update_probe(monkeypatch):
    authority = Authority(_snapshot(installed=False))
    installer = Installer(_result())

    response = _get(monkeypatch, authority, installer)

    assert response["payload"] == {
        "ok": True,
        "installed": False,
        "update_available": False,
        "error_code": "not_installed",
    }
    assert installer.calls == 0


@pytest.mark.parametrize("available", [False, True])
def test_installed_update_state_maps_to_minimal_public_contract(
    monkeypatch,
    available,
):
    authority = Authority(_snapshot())
    installer = Installer(_result(available=available))

    response = _get(monkeypatch, authority, installer)

    assert response["payload"]["installed"] is True
    assert response["payload"]["update_available"] is available
    assert set(response["payload"]) == {
        "ok",
        "installed",
        "update_available",
        "error_code",
    }
    rendered = repr(response)
    for private_value in (
        "private.invalid",
        "/private/",
        "sha256",
        "build_identifier",
        PRIVATE_DETAIL,
    ):
        assert private_value not in rendered


def test_failed_probe_fails_closed(monkeypatch):
    response = _get(
        monkeypatch,
        Authority(_snapshot()),
        Installer(_result(ok=False)),
    )

    assert response["payload"] == {
        "ok": False,
        "installed": True,
        "update_available": False,
        "error_code": "check_failed",
    }


def test_repeated_and_concurrent_calls_share_one_cached_probe(monkeypatch):
    authority = Authority(_snapshot())
    installer = Installer(_result(available=True), delay=0.05)
    monkeypatch.setattr(backend, "APP_INSTANCE", _app(authority, installer))

    def invoke(_index):
        handler = object.__new__(backend.ControlHandler)
        handler.path = UPDATE_STATUS_PATH
        result = {}
        handler._send_json = lambda payload, no_store=False: result.update(
            payload=payload,
            no_store=no_store,
        )
        handler.send_error = lambda *_args, **_kwargs: pytest.fail(
            "exact route must not send an HTTP error"
        )
        handler.do_GET()
        return result

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(invoke, range(4)))

    assert installer.calls == 1
    assert all(item["payload"]["update_available"] is True for item in responses)


def test_cache_is_bound_to_installed_artifact_identity(monkeypatch):
    authority = Authority(_snapshot(sha256="a" * 64))
    installer = Installer(_result())

    _get(monkeypatch, authority, installer)
    authority.snapshot = _snapshot(sha256="b" * 64)
    _get(monkeypatch, authority, installer)

    assert installer.calls == 2


def test_cache_expires_after_six_hour_ttl(monkeypatch):
    authority = Authority(_snapshot())
    installer = Installer(_result())
    clock = iter([100.0, 100.0 + (6 * 60 * 60) - 1, 100.0 + (6 * 60 * 60)])
    monkeypatch.setattr(backend.time, "monotonic", lambda: next(clock))

    _get(monkeypatch, authority, installer)
    _get(monkeypatch, authority, installer)
    _get(monkeypatch, authority, installer)

    assert backend._SPOTIFY_ARTIFACT_UPDATE_STATUS_TTL_SECONDS == 6 * 60 * 60
    assert installer.calls == 2


def test_query_string_is_rejected_before_probe(monkeypatch):
    authority = Authority(_snapshot())
    installer = Installer(_result())

    response = _get(
        monkeypatch,
        authority,
        installer,
        path=UPDATE_STATUS_PATH + "?url=" + PRIVATE_DETAIL,
    )

    assert response["payload"] == {"ok": False, "error": "invalid_request"}
    assert installer.calls == 0
    assert PRIVATE_DETAIL not in repr(response)
