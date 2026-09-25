import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402
from services.spotify_coordinator import (  # noqa: E402
    SpotifyCoordinator,
    SpotifyLifecycle,
)


def _coordinator_in_state(state):
    coordinator = SpotifyCoordinator()
    if state is SpotifyLifecycle.DISABLED:
        return coordinator
    if state is SpotifyLifecycle.SAFE_ERROR:
        coordinator.mark_safe_error(verified_safe=True)
        return coordinator
    if state is SpotifyLifecycle.UNSAFE_ERROR:
        coordinator.mark_unsafe_error()
        return coordinator
    coordinator.enter_standby()
    if state is SpotifyLifecycle.STANDBY:
        return coordinator
    coordinator.begin_acquisition()
    if state is SpotifyLifecycle.ACQUIRING:
        return coordinator
    if state is SpotifyLifecycle.RECOVERING:
        coordinator.begin_recovery()
        return coordinator
    coordinator.confirm_owned()
    if state is SpotifyLifecycle.OWNED:
        return coordinator
    coordinator.begin_release()
    assert state is SpotifyLifecycle.RELEASING
    return coordinator


class _Orchestrator:
    def __init__(self, result=True, error=None):
        self.result = result
        self.error = error
        self.prepare_calls = 0

    def prepare_native_claim(self):
        self.prepare_calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _selected_binding(monkeypatch):
    monkeypatch.setattr(backend, "ALSA_DRIVER", "ALSA")
    monkeypatch.setattr(backend, "ALSA_DEVICE", "hw:2,0")
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "Test DAC")
    return backend.SpotifyOutputBinding(2, 0)


def _handoff_app(monkeypatch, orchestrator, coordinator=None, player=None):
    binding = _selected_binding(monkeypatch)
    app = SimpleNamespace(
        spotify_orchestrator=orchestrator,
        spotify_orchestrator_binding=binding,
        spotify_coordinator=coordinator or SpotifyCoordinator(),
        player=player or SimpleNamespace(),
    )
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    return app, binding


@pytest.mark.parametrize(
    ("state", "allowed"),
    [
        (SpotifyLifecycle.DISABLED, True),
        (SpotifyLifecycle.STANDBY, True),
        (SpotifyLifecycle.ACQUIRING, False),
        (SpotifyLifecycle.OWNED, False),
        (SpotifyLifecycle.RELEASING, False),
        (SpotifyLifecycle.RECOVERING, False),
        (SpotifyLifecycle.UNSAFE_ERROR, False),
        (SpotifyLifecycle.SAFE_ERROR, True),
    ],
)
def test_playback_require_boundary_follows_coordinator(
    monkeypatch,
    state,
    allowed,
):
    probes = []
    app = SimpleNamespace(spotify_coordinator=_coordinator_in_state(state))
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_selected_audio_output_available_for_playback",
        lambda: (probes.append(True) or True, ""),
    )

    if allowed:
        assert backend._require_audio_output_for_playback("test") is True
        assert probes == [True]
        return

    with pytest.raises(backend.AudioOutputUnavailable) as raised:
        backend._require_audio_output_for_playback("test")

    assert raised.value.error_code == "spotify_native_playback_blocked"
    assert raised.value.to_payload() == {
        "ok": False,
        "error": "spotify_native_playback_blocked",
        "message": "spotify_native_playback_blocked",
    }
    assert probes == []


def test_missing_coordinator_after_app_exists_fails_closed(monkeypatch):
    monkeypatch.setattr(backend, "APP_INSTANCE", SimpleNamespace())
    monkeypatch.setattr(
        backend,
        "_selected_audio_output_available_for_playback",
        lambda: pytest.fail("DAC probe must not run"),
    )

    with pytest.raises(backend.AudioOutputUnavailable):
        backend._require_audio_output_for_playback("missing coordinator")


def test_coordinator_exception_fails_closed(monkeypatch):
    class BrokenCoordinator:
        def can_native_play(self):
            raise RuntimeError("private coordinator detail")

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_coordinator=BrokenCoordinator()),
    )
    monkeypatch.setattr(
        backend,
        "_selected_audio_output_available_for_playback",
        lambda: pytest.fail("DAC probe must not run"),
    )

    with pytest.raises(backend.AudioOutputUnavailable) as raised:
        backend._require_audio_output_for_playback("broken coordinator")

    assert "private coordinator detail" not in repr(raised.value.to_payload())


def test_import_time_without_app_preserves_existing_permission(monkeypatch):
    probes = []
    monkeypatch.setattr(backend, "APP_INSTANCE", None)
    monkeypatch.setattr(
        backend,
        "_selected_audio_output_available_for_playback",
        lambda: (probes.append(True) or True, ""),
    )

    assert backend._require_audio_output_for_playback("startup") is True
    assert probes == [True]


def test_adapter_guard_install_uses_explicit_hook(monkeypatch):
    callbacks = []
    player = SimpleNamespace(
        set_native_audio_guard=lambda callback: callbacks.append(callback)
    )

    assert backend._install_native_audio_guard(player) is True
    assert callbacks == [backend._native_audio_allowed]


def test_configure_audio_denial_restores_player_state(monkeypatch):
    coordinator = SpotifyCoordinator()
    player = SimpleNamespace(
        requested_driver="old-driver",
        requested_device_id="old-device",
        bit_perfect_mode=False,
        exclusive_lock_mode=False,
        active_rate_switch=False,
        set_output=lambda *_args: False,
    )
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(
            spotify_coordinator=coordinator,
            spotify_orchestrator=None,
            spotify_orchestrator_binding=None,
            player=player,
        ),
    )

    assert backend.configure_audio() is False
    assert vars(player) == {
        "requested_driver": "old-driver",
        "requested_device_id": "old-device",
        "bit_perfect_mode": False,
        "exclusive_lock_mode": False,
        "active_rate_switch": False,
        "set_output": player.set_output,
    }


def test_configure_audio_blocked_before_player_mutation(monkeypatch):
    coordinator = SpotifyCoordinator()
    coordinator.enter_standby()
    coordinator.begin_acquisition()

    def forbidden(*_args):
        raise AssertionError("blocked configure_audio reached player.set_output")

    player = SimpleNamespace(
        requested_driver="old-driver",
        requested_device_id="old-device",
        bit_perfect_mode=False,
        exclusive_lock_mode=False,
        active_rate_switch=False,
        set_output=forbidden,
    )
    before = dict(vars(player))
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(
            spotify_coordinator=coordinator,
            player=player,
        ),
    )

    assert backend.configure_audio() is False
    assert vars(player) == before


def test_manual_exclusive_route_does_not_report_blocked_claim(monkeypatch):
    coordinator = SpotifyCoordinator()
    coordinator.enter_standby()
    coordinator.begin_acquisition()
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(
            spotify_coordinator=coordinator,
            player=SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(
        backend,
        "_cancel_idle_release",
        lambda: pytest.fail("blocked claim scheduled DAC work"),
    )

    response = {}
    handler = object.__new__(backend.ControlHandler)
    handler.path = "/tidal/dac/exclusive"
    handler._send_json = lambda payload, no_store=False: response.update(
        payload=payload,
        no_store=no_store,
    )

    handler.do_GET()

    assert response == {
        "payload": {
            "ok": False,
            "error": "spotify_native_playback_blocked",
            "message": "spotify_native_playback_blocked",
        },
        "no_store": True,
    }


def test_ensure_audio_output_reports_permission_change_during_claim(monkeypatch):
    coordinator = SpotifyCoordinator()
    coordinator.enter_standby()

    def deny_during_claim(*_args):
        coordinator.begin_acquisition()
        return False

    player = SimpleNamespace(
        requested_driver="ALSA",
        requested_device_id="hw:1,0",
        bit_perfect_mode=False,
        exclusive_lock_mode=False,
        active_rate_switch=False,
        set_output=deny_during_claim,
    )
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(
            spotify_coordinator=coordinator,
            spotify_orchestrator=None,
            spotify_orchestrator_binding=None,
            player=player,
        ),
    )
    monkeypatch.setattr(
        backend,
        "_selected_audio_output_available_for_playback",
        lambda: (True, ""),
    )

    with pytest.raises(backend.AudioOutputUnavailable) as raised:
        backend._ensure_audio_output_for_playback("race")

    assert raised.value.error_code == "spotify_native_playback_blocked"
    assert player.exclusive_lock_mode is False


def test_prepare_helper_no_orchestrator_is_side_effect_free(monkeypatch):
    app, _binding = _handoff_app(monkeypatch, None)
    app.spotify_orchestrator_binding = None
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        lambda: pytest.fail("native playback must not lazily compose Spotify"),
    )
    monkeypatch.setattr(
        backend,
        "build_spotify_endpoint_lifecycle",
        lambda **_kwargs: pytest.fail("native playback must not build Spotify"),
    )
    monkeypatch.setattr(
        backend,
        "_selected_audio_output_available_for_playback",
        lambda: pytest.fail("native handoff must not probe PCM"),
    )

    assert backend._prepare_spotify_for_native_output_claim() is True
    assert backend._native_audio_allowed(
        "output_claim",
        source="set-output",
    ) is True


@pytest.mark.parametrize(
    ("orchestrator_present", "binding_present"),
    [(False, True), (True, False)],
)
def test_prepare_helper_rejects_inconsistent_composition_state(
    monkeypatch,
    orchestrator_present,
    binding_present,
):
    orchestrator = _Orchestrator() if orchestrator_present else None
    app, binding = _handoff_app(monkeypatch, orchestrator)
    app.spotify_orchestrator_binding = binding if binding_present else None

    assert backend._prepare_spotify_for_native_output_claim() is False
    if orchestrator is not None:
        assert orchestrator.prepare_calls == 0


def test_prepare_helper_rejects_binding_mismatch_without_prepare(monkeypatch):
    orchestrator = _Orchestrator()
    app, _binding = _handoff_app(monkeypatch, orchestrator)
    app.spotify_orchestrator_binding = backend.SpotifyOutputBinding(1, 0)

    assert backend._prepare_spotify_for_native_output_claim() is False
    assert orchestrator.prepare_calls == 0


def test_prepare_helper_ignores_presentation_name_mismatch(monkeypatch):
    orchestrator = _Orchestrator()
    _handoff_app(monkeypatch, orchestrator)
    monkeypatch.setitem(
        backend._APP_SETTINGS,
        "spotify_device_name",
        "Living Room",
    )
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "Test DAC")

    assert backend._prepare_spotify_for_native_output_claim() is True
    assert orchestrator.prepare_calls == 1


@pytest.mark.parametrize(("result", "expected"), [(True, True), (False, False)])
def test_prepare_helper_propagates_existing_orchestrator_result(
    monkeypatch,
    result,
    expected,
):
    orchestrator = _Orchestrator(result=result)
    _handoff_app(monkeypatch, orchestrator)

    assert backend._prepare_spotify_for_native_output_claim() is expected
    assert orchestrator.prepare_calls == 1


def test_prepare_helper_exception_fails_closed(monkeypatch):
    orchestrator = _Orchestrator(error=RuntimeError("private failure"))
    _handoff_app(monkeypatch, orchestrator)

    assert backend._prepare_spotify_for_native_output_claim() is False
    assert orchestrator.prepare_calls == 1


def _native_owned_player(**overrides):
    values = {
        "requested_driver": "ALSA",
        "requested_device_id": "hw:2,0",
        "bit_perfect_mode": True,
        "exclusive_lock_mode": True,
        "current_driver": "ALSA",
        "current_device_id": "hw:2,0",
        "output_state": "active",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_prepare_helper_bypasses_clean_self_owned_output(monkeypatch):
    orchestrator = _Orchestrator()
    _handoff_app(monkeypatch, orchestrator, player=_native_owned_player())

    assert backend._prepare_spotify_for_native_output_claim() is True
    assert orchestrator.prepare_calls == 0


@pytest.mark.parametrize(
    "state",
    [
        SpotifyLifecycle.STANDBY,
        SpotifyLifecycle.ACQUIRING,
        SpotifyLifecycle.OWNED,
        SpotifyLifecycle.RELEASING,
        SpotifyLifecycle.RECOVERING,
        SpotifyLifecycle.SAFE_ERROR,
        SpotifyLifecycle.UNSAFE_ERROR,
    ],
)
def test_prepare_helper_rejects_self_owned_output_unless_coordinator_disabled(
    monkeypatch,
    state,
):
    orchestrator = _Orchestrator()
    _handoff_app(
        monkeypatch,
        orchestrator,
        coordinator=_coordinator_in_state(state),
        player=_native_owned_player(),
    )

    assert backend._prepare_spotify_for_native_output_claim() is False
    assert orchestrator.prepare_calls == 0


@pytest.mark.parametrize(
    "coordinator",
    [
        SimpleNamespace(status_snapshot=lambda: {"state": "disabled"}),
        SimpleNamespace(status_snapshot=lambda: {
            "state": "disabled",
            "spotify_owner": 0,
            "native_blocked": False,
        }),
    ],
)
def test_prepare_helper_rejects_invalid_self_owned_coordinator_snapshot(
    monkeypatch,
    coordinator,
):
    orchestrator = _Orchestrator()
    _handoff_app(
        monkeypatch,
        orchestrator,
        coordinator=coordinator,
        player=_native_owned_player(),
    )

    assert backend._prepare_spotify_for_native_output_claim() is False
    assert orchestrator.prepare_calls == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"bit_perfect_mode": False},
        {"current_device_id": "hw:1,0"},
        {"current_driver": "PipeWire"},
        {
            "requested_device_id": "hw:2,0",
            "current_device_id": "hw:1,0",
        },
        {
            "requested_driver": "ALSA",
            "requested_device_id": "hw:2,0",
            "current_driver": "",
            "current_device_id": "",
            "output_state": "switching",
        },
    ],
)
def test_prepare_helper_requires_positive_current_native_route(
    monkeypatch,
    overrides,
):
    orchestrator = _Orchestrator()
    _handoff_app(
        monkeypatch,
        orchestrator,
        player=_native_owned_player(**overrides),
    )

    assert backend._prepare_spotify_for_native_output_claim() is True
    assert orchestrator.prepare_calls == 1


def _active_selected_output_restore():
    return {
        "requested_driver": "ALSA",
        "requested_device_id": "hw:2,0",
        "current_driver": "ALSA",
        "current_device_id": "hw:2,0",
        "output_state": "active",
        "output_error": None,
    }


def test_prepare_helper_bypasses_proven_self_owned_same_route_switch(
    monkeypatch,
):
    orchestrator = _Orchestrator()
    player = _native_owned_player(
        output_state="switching",
        _output_switch_inflight=True,
        _output_switch_pending=None,
        _output_switch_restore=_active_selected_output_restore(),
    )
    _handoff_app(
        monkeypatch,
        orchestrator,
        player=player,
    )

    assert backend._prepare_spotify_for_native_output_claim() is True
    assert orchestrator.prepare_calls == 0


@pytest.mark.parametrize(
    ("inflight", "restore"),
    [
        (False, _active_selected_output_restore()),
        (True, None),
        (
            True,
            {
                **_active_selected_output_restore(),
                "output_state": "idle",
            },
        ),
        (
            True,
            {
                **_active_selected_output_restore(),
                "current_device_id": "hw:1,0",
            },
        ),
        (
            True,
            {
                **_active_selected_output_restore(),
                "current_driver": "PipeWire",
            },
        ),
    ],
)
def test_prepare_helper_switching_requires_proven_prior_self_owned_route(
    monkeypatch,
    inflight,
    restore,
):
    orchestrator = _Orchestrator()
    player = _native_owned_player(
        output_state="switching",
        _output_switch_inflight=inflight,
        _output_switch_pending=None,
        _output_switch_restore=restore,
    )
    _handoff_app(
        monkeypatch,
        orchestrator,
        player=player,
    )

    assert backend._prepare_spotify_for_native_output_claim() is True
    assert orchestrator.prepare_calls == 1


@pytest.mark.parametrize("source", ["set-output", "configure-audio"])
def test_output_claim_prepare_sources_invoke_handoff(monkeypatch, source):
    calls = []
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_coordinator=SpotifyCoordinator()),
    )
    monkeypatch.setattr(
        backend,
        "_prepare_spotify_for_native_output_claim",
        lambda: calls.append(source) or True,
    )

    assert backend._native_audio_allowed("output_claim", source=source) is True
    assert calls == [source]


@pytest.mark.parametrize(
    "source",
    ["apply-output-switch", "pipewire-rate-rebind", "ensure-audio-output"],
)
@pytest.mark.parametrize("allowed", [True, False])
def test_nested_output_claim_sources_are_permission_only(
    monkeypatch,
    source,
    allowed,
):
    coordinator = SimpleNamespace(can_native_play=lambda: allowed)
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_coordinator=coordinator),
    )
    monkeypatch.setattr(
        backend,
        "_prepare_spotify_for_native_output_claim",
        lambda: pytest.fail("nested output guard attempted another handoff"),
    )

    assert backend._native_audio_allowed("output_claim", source=source) is allowed


@pytest.mark.parametrize("allowed", [True, False])
def test_non_output_claim_preserves_coordinator_permission(monkeypatch, allowed):
    coordinator = SimpleNamespace(can_native_play=lambda: allowed)
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_coordinator=coordinator),
    )
    monkeypatch.setattr(
        backend,
        "_prepare_spotify_for_native_output_claim",
        lambda: pytest.fail("playback permission attempted output handoff"),
    )

    assert backend._native_audio_allowed("playback_start") is allowed


def test_configure_audio_prepare_denial_precedes_player_mutation(monkeypatch):
    player = _native_owned_player(requested_driver="old", requested_device_id="old")
    player.set_output = lambda *_args: pytest.fail("denied claim reached set_output")
    before = dict(vars(player))
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_coordinator=SpotifyCoordinator(), player=player),
    )
    monkeypatch.setattr(
        backend,
        "_prepare_spotify_for_native_output_claim",
        lambda: False,
    )

    assert backend.configure_audio() is False
    assert vars(player) == before


def test_configure_audio_post_prepare_denial_precedes_player_mutation(monkeypatch):
    answers = iter((True, False))
    coordinator = SimpleNamespace(can_native_play=lambda: next(answers))
    player = _native_owned_player(requested_driver="old", requested_device_id="old")
    player.set_output = lambda *_args: pytest.fail("post-check denial reached set_output")
    before = dict(vars(player))
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_coordinator=coordinator, player=player),
    )
    monkeypatch.setattr(
        backend,
        "_prepare_spotify_for_native_output_claim",
        lambda: True,
    )

    assert backend.configure_audio() is False
    assert vars(player) == before


def test_configure_audio_success_preserves_assignments_and_set_output(monkeypatch):
    calls = []
    player = _native_owned_player(
        requested_driver="old-driver",
        requested_device_id="old-device",
        bit_perfect_mode=False,
        exclusive_lock_mode=False,
    )
    player.active_rate_switch = False
    player.set_output = lambda *args: calls.append(args) or True
    _selected_binding(monkeypatch)
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_coordinator=SpotifyCoordinator(), player=player),
    )
    monkeypatch.setattr(
        backend,
        "_prepare_spotify_for_native_output_claim",
        lambda: True,
    )

    assert backend.configure_audio() is True
    assert calls == [("ALSA", "hw:2,0")]
    assert player.requested_driver == "ALSA"
    assert player.requested_device_id == "hw:2,0"
    assert player.bit_perfect_mode is True
    assert player.exclusive_lock_mode is True
    assert player.active_rate_switch is True


def test_configure_audio_set_output_failure_rolls_back(monkeypatch):
    player = _native_owned_player(
        requested_driver="old-driver",
        requested_device_id="old-device",
        bit_perfect_mode=False,
        exclusive_lock_mode=False,
    )
    player.active_rate_switch = False
    player.set_output = lambda *_args: False
    before = dict(vars(player))
    _selected_binding(monkeypatch)
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(spotify_coordinator=SpotifyCoordinator(), player=player),
    )
    monkeypatch.setattr(
        backend,
        "_prepare_spotify_for_native_output_claim",
        lambda: True,
    )

    assert backend.configure_audio() is False
    assert vars(player) == before


def test_prepare_helper_holds_orchestrator_lock_while_reading_state(monkeypatch):
    held = {"value": False}

    class TrackingLock:
        def __enter__(self):
            held["value"] = True

        def __exit__(self, *_args):
            held["value"] = False

    class TrackingApp:
        @property
        def spotify_orchestrator(self):
            assert held["value"] is True
            return None

        @property
        def spotify_orchestrator_binding(self):
            assert held["value"] is True
            return None

    monkeypatch.setattr(backend, "_SPOTIFY_ORCHESTRATOR_LOCK", TrackingLock())
    monkeypatch.setattr(backend, "APP_INSTANCE", TrackingApp())

    assert backend._prepare_spotify_for_native_output_claim() is True
    assert held["value"] is False


def test_prepare_helper_lock_order_is_orchestrator_then_audio(monkeypatch):
    held = []
    events = []

    class TrackingLock:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            if self.name == "orchestrator":
                assert "audio" not in held
            held.append(self.name)
            events.append(("enter", self.name))

        def __exit__(self, *_args):
            events.append(("exit", self.name))
            held.remove(self.name)

    orchestrator = _Orchestrator()
    _handoff_app(monkeypatch, orchestrator)
    monkeypatch.setattr(
        backend,
        "_SPOTIFY_ORCHESTRATOR_LOCK",
        TrackingLock("orchestrator"),
    )
    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_LOCK", TrackingLock("audio"))

    assert backend._prepare_spotify_for_native_output_claim() is True
    assert events[0] == ("enter", "orchestrator")
    assert events[-1] == ("exit", "orchestrator")
    assert events.count(("enter", "audio")) == 2
    assert "with _SPOTIFY_ORCHESTRATOR_LOCK" in inspect.getsource(
        backend._prepare_spotify_for_native_output_claim
    )
