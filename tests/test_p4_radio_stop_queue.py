from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "src/main_headless.py").read_text()
UI = (ROOT / "src/ui_web/ui.js").read_text()


def _js_function(name, next_name):
    start = UI.index("function " + name)
    end = UI.index("function " + next_name, start)
    return UI[start:end]


def _py_function(name, next_name):
    start = MAIN.index("def " + name)
    end = MAIN.index("def " + next_name, start)
    return MAIN[start:end]


def test_p4_radio_transport_uses_stop_presentation_only_for_radio():
    block = _js_function("_setPlayIconButton", "updatePlayPauseIcon")
    updater = _js_function("updatePlayPauseIcon", "updateRepeatIcon")

    assert '"stop"' in block
    assert '"pause"' in block
    assert '"play_arrow"' in block
    assert '"Stop"' in block
    assert '"Pause"' in block
    assert "s.radio_mode === true" in updater
    assert "forceRadioStop === true" in updater


def test_p4_radio_start_requests_immediate_stop_presentation():
    start = UI.index("function playRadioStation")
    end = UI.index("function buildRadioStationPayload", start)
    block = UI[start:end]

    assert "updatePlayPauseIcon(true)" in block


def test_p4_non_radio_transport_calls_remain_generic():
    assert UI.count("updatePlayPauseIcon(true)") == 1
    assert "Provider-generated" in UI
    assert "TIDAL/Qobuz Radio remains finite-track playback and keeps Pause" in UI


def test_p4_radio_pause_removes_only_explicit_radio_queue_item():
    block = _py_function("_tidal_pause_payload", "_tidal_resume_payload")

    assert 'pause_source == "radio" and RADIO_MODE' in block
    assert '_queue_item_source(candidate_id, candidate_meta) == "radio"' in block
    assert "_queue_remove_active_index_locked(QUEUE_INDEX)" in block
    assert "PLAY_QUEUE_META_CACHE.pop(" in block
    assert "save_queue()" in block


def test_p4_preserves_existing_radio_pause_and_dac_release_lifecycle():
    block = _py_function("_tidal_pause_payload", "_tidal_resume_payload")

    assert "APP_INSTANCE.player.pause()" in block
    assert "_schedule_idle_release(5)" in block
    assert "stop_radio()" not in block
    assert "_reset_idle_playback_context()" not in block


def test_p4_visible_queue_refresh_is_radio_guarded():
    start = UI.index("function togglePlayPause")
    end = UI.index("function handleTrackChangeResponse", start)
    block = UI[start:end]

    assert "lastKnownPlaybackStatus.radio_mode" in block
    assert 'queueView.style.display !== "none"' in block
    assert "loadQueue();" in block
    assert "scheduleRadioIdleStandby();" in block
