from types import SimpleNamespace

import src.main_headless as backend


TRACK_ID = "local:point5-seek"
DURATION = 240.0


class FakePlayer:
    def __init__(self, *, playing=True, position=80.0, fail_seek=False):
        self._playing = bool(playing)
        self._position = float(position)
        self.fail_seek = bool(fail_seek)
        self.calls = []

    def is_playing(self):
        return self._playing

    def pause(self):
        self.calls.append("pause")
        self._playing = False

    def seek(self, value):
        target = float(value)
        self.calls.append(("seek", target))
        if self.fail_seek:
            raise RuntimeError("synthetic seek failure")
        self._position = target

    def play(self):
        self.calls.append("play")
        self._playing = True


def prepare_seek(
    monkeypatch,
    player,
    *,
    driver="alsa_mmap",
    source="local",
    radio=False,
    cue=False,
    delayed_resume=False,
):
    events = []
    sleeps = []
    clock_positions = []
    armed = []
    disarmed = []

    context = {
        "track_id": TRACK_ID,
        "title": "Point 5 Seek Test",
        "artist": "SROVA",
        "album": "Regression",
        "duration": DURATION,
        "context_type": "local_queue" if source == "local" else "tidal_queue",
        "is_cue_track": 1 if cue else 0,
        "cue_start_seconds": 30.0 if cue else 0.0,
    }
    playback_context = {
        "source": source,
        "radio_mode": bool(radio),
        "current_track_valid": True,
        "current_track_id": TRACK_ID,
        "context": context,
    }

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(player=player),
    )
    monkeypatch.setattr(backend, "ALSA_DRIVER", driver)
    monkeypatch.setattr(backend, "RADIO_MODE", bool(radio))
    monkeypatch.setattr(backend, "QUEUE_INDEX", 0)
    monkeypatch.setattr(backend, "QUEUE_AUTO_ADVANCE_ARMED_KEY", "")
    monkeypatch.setattr(backend, "PLAYBACK_START_TIME", 0.0)
    monkeypatch.setattr(backend, "PAUSED_PLAYBACK_POSITION", 0.0)
    monkeypatch.setattr(backend, "PAUSED_PLAYBACK_TRACK_ID", "")

    monkeypatch.setattr(
        backend,
        "_status_playback_context",
        lambda _player=None: playback_context,
    )
    monkeypatch.setattr(
        backend,
        "_player_position_seconds",
        lambda _player=None: float(player._position),
    )
    monkeypatch.setattr(
        backend,
        "_set_playback_clock_position",
        lambda position: clock_positions.append(float(position)),
    )
    monkeypatch.setattr(
        backend,
        "_arm_active_queue_auto_advance",
        lambda: armed.append(True),
    )
    monkeypatch.setattr(
        backend,
        "_disarm_queue_auto_advance",
        lambda reason: disarmed.append(str(reason)),
    )
    monkeypatch.setattr(
        backend.time,
        "sleep",
        lambda seconds: (
            sleeps.append(float(seconds)),
            events.append(("sleep", float(seconds))),
        )[-1],
    )

    def fake_pause_payload():
        events.append("pause_payload")
        backend.PAUSED_PLAYBACK_POSITION = float(player._position)
        backend.PAUSED_PLAYBACK_TRACK_ID = TRACK_ID
        player.pause()
        return {
            "result": "paused",
            "position": backend.PAUSED_PLAYBACK_POSITION,
        }

    def fake_resume_payload():
        events.append(
            (
                "resume_payload",
                float(backend.PAUSED_PLAYBACK_POSITION),
                str(backend.PAUSED_PLAYBACK_TRACK_ID),
            )
        )
        if not delayed_resume:
            player.play()
        return {
            "result": "playing",
            "source": source,
            "position": backend.PAUSED_PLAYBACK_POSITION,
        }

    monkeypatch.setattr(
        backend,
        "_tidal_pause_payload",
        fake_pause_payload,
    )
    monkeypatch.setattr(
        backend,
        "_tidal_resume_payload",
        fake_resume_payload,
    )

    original_seek = player.seek

    def traced_seek(value):
        events.append(("seek", float(value)))
        return original_seek(value)

    player.seek = traced_seek

    return events, sleeps, clock_positions, armed, disarmed


def test_active_local_mmap_seek_reuses_stock_pause_resume_state_machine(monkeypatch):
    player = FakePlayer(playing=True, position=80.0)
    events, sleeps, clock_positions, armed, disarmed = prepare_seek(
        monkeypatch,
        player,
        driver="alsa_mmap",
        source="local",
    )

    result = backend._tidal_seek_payload(140)

    assert result["ok"] is True
    assert result["source"] == "local"
    assert result["position"] == 140.0
    assert result["playing"] is True
    assert result["resumed"] is True
    assert events == [
        "pause_payload",
        ("sleep", 0.35),
        ("seek", 140.0),
        ("sleep", 0.35),
        ("resume_payload", 140.0, TRACK_ID),
    ]
    assert player.calls == ["pause", ("seek", 140.0), "play"]
    assert sleeps == [0.35, 0.35]
    assert clock_positions == [140.0]
    assert armed == [True]
    assert disarmed == ["seek-while-paused"]


def test_active_tidal_mmap_seek_reuses_stock_pause_resume_state_machine(monkeypatch):
    player = FakePlayer(playing=True, position=170.0)
    events, sleeps, clock_positions, armed, disarmed = prepare_seek(
        monkeypatch,
        player,
        driver="alsa_mmap",
        source="tidal",
    )

    result = backend._tidal_seek_payload(22)

    assert result["ok"] is True
    assert result["source"] == "tidal"
    assert result["position"] == 22.0
    assert result["playing"] is True
    assert result["resumed"] is True
    assert events == [
        "pause_payload",
        ("sleep", 0.35),
        ("seek", 22.0),
        ("sleep", 0.35),
        ("resume_payload", 22.0, TRACK_ID),
    ]
    assert player.calls == ["pause", ("seek", 22.0), "play"]
    assert sleeps == [0.35, 0.35]
    assert clock_positions == [22.0]
    assert armed == [True]
    assert disarmed == ["seek-while-paused"]


def test_active_mmap_seek_preserves_playing_intent_during_delayed_reopen(monkeypatch):
    player = FakePlayer(playing=True, position=170.0)
    events, sleeps, clock_positions, armed, disarmed = prepare_seek(
        monkeypatch,
        player,
        driver="alsa_mmap",
        source="tidal",
        delayed_resume=True,
    )

    result = backend._tidal_seek_payload(22)

    assert result["ok"] is True
    assert result["playing"] is True
    assert result["resumed"] is True
    assert player.is_playing() is False
    assert events[-1] == ("resume_payload", 22.0, TRACK_ID)
    assert backend.PAUSED_PLAYBACK_POSITION == 22.0
    assert backend.PAUSED_PLAYBACK_TRACK_ID == TRACK_ID
    assert clock_positions == [22.0]
    assert armed == [True]
    assert disarmed == ["seek-while-paused"]


def test_active_mmap_seek_refuses_seek_if_paused_state_cannot_be_verified(monkeypatch):
    player = FakePlayer(playing=True, position=80.0)
    events, sleeps, clock_positions, armed, disarmed = prepare_seek(
        monkeypatch,
        player,
        driver="alsa_mmap",
        source="tidal",
    )

    original_is_playing = player.is_playing
    checks = {"count": 0}

    def fail_after_pause():
        checks["count"] += 1
        if checks["count"] == 1:
            return original_is_playing()
        raise RuntimeError("synthetic state-query failure")

    player.is_playing = fail_after_pause

    result = backend._tidal_seek_payload(22)

    assert result["ok"] is False
    assert result["error"] == "seek_pause_failed"
    assert result["position"] == 80.0
    assert result["playing"] is True
    assert events == [
        "pause_payload",
        ("sleep", 0.35),
        ("resume_payload", 80.0, TRACK_ID),
    ]
    assert player.calls == ["pause", "play"]
    assert sleeps == [0.35]
    assert clock_positions == []
    assert armed == []
    assert disarmed == []



def test_paused_mmap_seek_stays_paused(monkeypatch):
    player = FakePlayer(playing=False, position=80.0)
    events, sleeps, clock_positions, armed, disarmed = prepare_seek(
        monkeypatch,
        player,
        driver="alsa_mmap",
    )

    result = backend._tidal_seek_payload(140)

    assert result["ok"] is True
    assert result["position"] == 140.0
    assert result["playing"] is False
    assert result["resumed"] is False
    assert events == [("seek", 140.0)]
    assert player.calls == [("seek", 140.0)]
    assert sleeps == []
    assert clock_positions == []
    assert armed == []
    assert disarmed == ["seek-while-paused"]
    assert backend.PAUSED_PLAYBACK_POSITION == 140.0
    assert backend.PAUSED_PLAYBACK_TRACK_ID == TRACK_ID


def test_non_mmap_active_seek_keeps_existing_direct_behavior(monkeypatch):
    player = FakePlayer(playing=True, position=80.0)
    events, sleeps, clock_positions, armed, disarmed = prepare_seek(
        monkeypatch,
        player,
        driver="ALSA",
    )

    result = backend._tidal_seek_payload(140)

    assert result["ok"] is True
    assert result["playing"] is True
    assert result["resumed"] is True
    assert events == [("seek", 140.0)]
    assert player.calls == [("seek", 140.0), "play"]
    assert sleeps == []
    assert clock_positions == [140.0]
    assert armed == [True]
    assert disarmed == []


def test_failed_active_mmap_seek_restores_stock_playback_state(monkeypatch):
    player = FakePlayer(
        playing=True,
        position=80.0,
        fail_seek=True,
    )
    events, sleeps, clock_positions, armed, disarmed = prepare_seek(
        monkeypatch,
        player,
        driver="alsa_mmap",
    )

    result = backend._tidal_seek_payload(140)

    assert result["ok"] is False
    assert result["error"] == "synthetic seek failure"
    assert result["position"] == 80.0
    assert result["playing"] is True
    assert events == [
        "pause_payload",
        ("sleep", 0.35),
        ("seek", 140.0),
        ("sleep", 0.35),
        ("resume_payload", 80.0, TRACK_ID),
    ]
    assert player.calls == ["pause", ("seek", 140.0), "play"]
    assert sleeps == [0.35, 0.35]
    assert clock_positions == []
    assert armed == []
    assert disarmed == []


def test_local_cue_manual_seek_remains_blocked(monkeypatch):
    player = FakePlayer(playing=True, position=80.0)
    events, sleeps, clock_positions, armed, disarmed = prepare_seek(
        monkeypatch,
        player,
        driver="alsa_mmap",
        source="local",
        cue=True,
    )

    result = backend._tidal_seek_payload(140)

    assert result["ok"] is False
    assert result["error"] == "seek_unsupported_for_local_cue"
    assert events == []
    assert player.calls == []
    assert sleeps == []
    assert clock_positions == []
    assert armed == []
    assert disarmed == []


def test_radio_seek_remains_blocked(monkeypatch):
    player = FakePlayer(playing=True, position=80.0)
    events, sleeps, clock_positions, armed, disarmed = prepare_seek(
        monkeypatch,
        player,
        driver="alsa_mmap",
        source="radio",
        radio=True,
    )

    result = backend._tidal_seek_payload(140)

    assert result["ok"] is False
    assert result["error"] == "seek_unsupported_for_radio"
    assert events == []
    assert player.calls == []
    assert sleeps == []
    assert clock_positions == []
    assert armed == []
    assert disarmed == []
