import inspect
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402
from services.spotify_endpoint_lifecycle import SpotifyEndpointLifecycle  # noqa: E402
from services.spotify_firewall_manager import SpotifyFirewallManager  # noqa: E402


def _forbidden(*_args, **_kwargs):
    raise AssertionError("forbidden side effect")


def test_shutdown_without_composed_spotify_never_constructs_it(monkeypatch):
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_orchestrator=None),
    )
    monkeypatch.setattr(backend, "build_spotify_endpoint_lifecycle", _forbidden)

    assert backend._shutdown_existing_spotify_endpoint("test") is False


def test_shutdown_disables_only_existing_lifecycle(monkeypatch):
    calls = []
    lifecycle = SimpleNamespace(disable=lambda: calls.append("disable") or True)
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_orchestrator=lifecycle),
    )

    assert backend._shutdown_existing_spotify_endpoint("test") is True
    assert calls == ["disable"]


def test_sigterm_handler_only_requests_main_loop_quit(monkeypatch):
    installed = []
    loop = SimpleNamespace(quit=lambda: installed.append("quit"))
    monkeypatch.setattr(
        backend.signal,
        "signal",
        lambda signum, handler: installed.append((signum, handler)),
    )

    handler = backend._install_sigterm_main_loop_handler(loop)

    assert installed[0] == (signal.SIGTERM, handler)
    handler(signal.SIGTERM, None)
    assert installed[1:] == ["quit"]
    source = inspect.getsource(handler)
    for forbidden in ("firewall", "subprocess", "secret", "disable", "thread"):
        assert forbidden not in source.lower()


def test_main_finally_contains_existing_object_cleanup_before_qobuz():
    source = inspect.getsource(backend.main)
    spotify = source.index('_shutdown_existing_spotify_endpoint("main-loop-exit")')
    qobuz = source.index('_shutdown_qobuz_playback_bridge("main-loop-exit")')

    assert spotify < qobuz
    assert "except KeyboardInterrupt" in source


def test_controlled_restart_invokes_existing_endpoint_cleanup(monkeypatch):
    events = []

    class ExitCalled(BaseException):
        pass

    class Timer:
        daemon = False

        def __init__(self, _delay, target):
            self.target = target

        def start(self):
            self.target()

    lifecycle = SimpleNamespace(disable=lambda: events.append("spotify.disable"))
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_orchestrator=lifecycle, player=None),
    )
    monkeypatch.setattr(backend, "_SROVA_RESTART_SCHEDULED", False)
    monkeypatch.setattr(backend.threading, "Timer", Timer)
    monkeypatch.setattr(backend, "_invalidate_tidal_stream_resolution", lambda *_a: None)
    monkeypatch.setattr(backend, "_shutdown_qobuz_playback_bridge", lambda *_a: None)
    monkeypatch.setattr(backend, "_cancel_pending_radio_start", lambda: None)
    monkeypatch.setattr(backend._METADATA_REGISTRY, "detach", lambda: None)
    monkeypatch.setattr(backend, "_cancel_idle_release", lambda: None)
    monkeypatch.setattr(backend, "cancel_scrobble", lambda: None)
    monkeypatch.setattr(backend, "save_queue", lambda: None)
    monkeypatch.setattr(backend.logging, "shutdown", lambda: None)

    def exit_process(code):
        events.append(("exit", code))
        raise ExitCalled

    monkeypatch.setattr(backend.os, "_exit", exit_process)

    with pytest.raises(ExitCalled):
        backend._restart_srova_service_later(delay=0)

    assert events == [
        "spotify.disable",
        ("exit", backend._SROVA_RESTART_EXIT_CODE),
    ]


def test_normal_startup_constructs_no_firewall_activity(monkeypatch):
    monkeypatch.setattr(SpotifyFirewallManager, "inspect", _forbidden)
    monkeypatch.setattr(SpotifyFirewallManager, "prepare", _forbidden)
    monkeypatch.setattr(SpotifyFirewallManager, "release", _forbidden)
    monkeypatch.setattr(SpotifyFirewallManager, "cleanup_stale", _forbidden)

    app = backend.HeadlessApp()

    assert app.spotify_orchestrator is None
    assert app.spotify_orchestrator_binding is None
    assert app.spotify_runtime.endpoint_network_access is not None
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    assert backend._reconcile_existing_spotify_endpoint() is True


def test_reconcile_timer_registration_is_exact_and_persistent(monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        backend.GLib,
        "timeout_add",
        lambda interval, callback: scheduled.append((interval, callback)) or 71,
    )

    assert backend._register_spotify_endpoint_reconcile() == 71
    assert scheduled == [
        (
            backend._SPOTIFY_RECONCILE_INTERVAL_MS,
            backend._reconcile_existing_spotify_endpoint,
        )
    ]
    assert backend._reconcile_existing_spotify_endpoint() is True


def test_main_registers_exactly_one_spotify_reconcile_timer():
    source = inspect.getsource(backend.main)

    assert source.count("_register_spotify_endpoint_reconcile()") == 1


def test_lazy_composition_produces_endpoint_lifecycle(monkeypatch):
    app = backend.HeadlessApp()
    binding = backend.SpotifyOutputBinding(0, 0)
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_SELECTED", True)
    monkeypatch.setattr(backend, "_spotify_current_output_binding", lambda: binding)

    lifecycle = backend._spotify_orchestrator_for_current_output()

    assert isinstance(lifecycle, SpotifyEndpointLifecycle)
    assert app.spotify_orchestrator is lifecycle
    assert app.spotify_orchestrator_binding is binding
