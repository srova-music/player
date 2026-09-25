import os
import socket
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_qobuz_backend_is_signed_out_without_functional_capabilities(tmp_path):
    from backend.qobuz import QobuzBackend

    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
    )

    assert backend.status() == {
        "provider_id": "qobuz",
        "display_name": "Qobuz",
        "available": False,
        "authenticated": False,
        "usable": False,
        "auth_state": "signed_out",
        "login_pending": False,
        "error": "",
        "initialization_error": "",
        "user": None,
        "capabilities": [],
    }


def test_qobuz_backend_construction_does_not_use_network(tmp_path, monkeypatch):
    from backend.qobuz import QobuzBackend

    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("Qobuz Q1 construction attempted network access")

    monkeypatch.setattr(socket, "socket", unexpected_network)
    monkeypatch.setattr(socket, "create_connection", unexpected_network)

    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
    )

    assert backend.available is False
    assert backend.authenticated is False


def test_runtime_attaches_qobuz_without_replacing_tidal(monkeypatch):
    pytest.importorskip("gi")

    from app import app_init_runtime as runtime
    import backend.qobuz as qobuz_module

    tidal_backend = object()
    qobuz_backend = object()

    monkeypatch.setattr(runtime, "TidalBackend", lambda: tidal_backend)
    monkeypatch.setattr(
        qobuz_module,
        "QobuzBackend",
        lambda: qobuz_backend,
    )

    app = SimpleNamespace()
    runtime._init_streaming_backends(app)

    assert app.backend is tidal_backend
    assert app.qobuz_backend is qobuz_backend


def test_runtime_isolates_qobuz_construction_failure(monkeypatch):
    pytest.importorskip("gi")

    from app import app_init_runtime as runtime
    import backend.qobuz as qobuz_module

    tidal_backend = object()

    def fail_qobuz_construction():
        raise RuntimeError("simulated Qobuz construction failure")

    monkeypatch.setattr(runtime, "TidalBackend", lambda: tidal_backend)
    monkeypatch.setattr(
        qobuz_module,
        "QobuzBackend",
        fail_qobuz_construction,
    )

    app = SimpleNamespace()
    runtime._init_streaming_backends(app)

    assert app.backend is tidal_backend
    assert app.qobuz_backend is None


def test_runtime_isolates_qobuz_import_failure(monkeypatch):
    pytest.importorskip("gi")

    from app import app_init_runtime as runtime

    tidal_backend = object()
    monkeypatch.setattr(runtime, "TidalBackend", lambda: tidal_backend)
    monkeypatch.setitem(sys.modules, "backend.qobuz", None)

    app = SimpleNamespace()
    runtime._init_streaming_backends(app)

    assert app.backend is tidal_backend
    assert app.qobuz_backend is None
