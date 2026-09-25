import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402


class Coordinator:
    def __init__(self, state="disabled"):
        self.state = state

    def status_snapshot(self):
        return {
            "state": self.state,
            "spotify_owner": False,
            "native_blocked": False,
        }


class Lifecycle:
    def __init__(self):
        self.reconcile_calls = 0
        self.enable_calls = 0

    def reconcile(self):
        self.reconcile_calls += 1
        return False

    def enable(self):
        self.enable_calls += 1
        return True


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    settings = dict(backend._APP_SETTINGS)
    settings["spotify_enabled"] = False
    monkeypatch.setattr(backend, "_APP_SETTINGS", settings)
    monkeypatch.setattr(
        backend,
        "_APP_SETTINGS_FILE",
        str(tmp_path / "hiresti" / "srova_settings.json"),
    )
    monkeypatch.setattr(
        backend,
        "_spotify_selected_dac_available",
        lambda: True,
    )
    return settings


def _app(*, lifecycle=None, state="disabled"):
    return SimpleNamespace(
        spotify_coordinator=Coordinator(state),
        spotify_orchestrator=lifecycle,
        spotify_orchestrator_binding=None,
        spotify_runtime=SimpleNamespace(pcm_verifier=object()),
    )


def test_spotify_enabled_defaults_fail_closed():
    assert backend._APP_SETTINGS.get("spotify_enabled", False) is False


def test_enabled_intent_persists_and_reloads(isolated_settings, monkeypatch):
    assert backend._set_spotify_enabled_intent(True) is True
    assert backend._spotify_enabled_intent() is True

    reloaded = dict(isolated_settings)
    reloaded["spotify_enabled"] = False
    monkeypatch.setattr(backend, "_APP_SETTINGS", reloaded)

    backend._load_app_settings()

    assert backend._spotify_enabled_intent() is True


def test_persistence_failure_rolls_back_intent(isolated_settings, monkeypatch):
    monkeypatch.setattr(backend, "_save_app_settings", lambda: False)

    with pytest.raises(RuntimeError):
        backend._set_spotify_enabled_intent(True)

    assert backend._spotify_enabled_intent() is False


def test_disabled_intent_never_auto_composes(isolated_settings, monkeypatch):
    app = _app()
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_spotify_rearm_pcm_is_free",
        lambda: pytest.fail("disabled intent must not inspect PCM"),
    )
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        lambda: pytest.fail("disabled intent must not compose Spotify"),
    )

    assert backend._reconcile_existing_spotify_endpoint() is True


def test_enabled_intent_waits_while_pcm_busy(isolated_settings, monkeypatch):
    isolated_settings["spotify_enabled"] = True
    app = _app()
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(backend, "_spotify_rearm_pcm_is_free", lambda: False)
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        lambda: pytest.fail("busy PCM must not compose Spotify"),
    )

    assert backend._reconcile_existing_spotify_endpoint() is True


def test_enabled_intent_auto_composes_when_pcm_becomes_free(
    isolated_settings,
    monkeypatch,
):
    isolated_settings["spotify_enabled"] = True
    lifecycle = Lifecycle()
    app = _app()
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(backend, "_spotify_rearm_pcm_is_free", lambda: True)

    composed = []
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        lambda: composed.append(True) or lifecycle,
    )

    assert backend._reconcile_existing_spotify_endpoint() is True
    assert composed == [True]
    assert lifecycle.enable_calls == 1


def test_existing_withdrawn_endpoint_rearms_when_pcm_free(
    isolated_settings,
    monkeypatch,
):
    isolated_settings["spotify_enabled"] = True
    lifecycle = Lifecycle()
    app = _app(lifecycle=lifecycle)
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(backend, "_spotify_rearm_pcm_is_free", lambda: True)

    assert backend._reconcile_existing_spotify_endpoint() is True
    assert lifecycle.reconcile_calls == 1
    assert lifecycle.enable_calls == 1


def test_explicit_disabled_intent_suppresses_rearm_of_existing_lifecycle(
    isolated_settings,
    monkeypatch,
):
    lifecycle = Lifecycle()
    app = _app(lifecycle=lifecycle)
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_spotify_rearm_pcm_is_free",
        lambda: pytest.fail("disabled intent must not inspect PCM"),
    )

    assert backend._reconcile_existing_spotify_endpoint() is True
    assert lifecycle.reconcile_calls == 1
    assert lifecycle.enable_calls == 0
