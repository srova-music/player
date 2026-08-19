from pathlib import Path


UI_SOURCE = Path("src/ui_web/ui.js").read_text(encoding="utf-8")


def test_playerbar_radio_presentation_does_not_follow_browsing_while_media_active():
    """
    Browsing the Radio source must not put an actively playing Local/TIDAL
    playerbar into Radio presentation. Actual playback source wins while
    media is active.
    """
    assert (
        'var radioContext = activeRadio || (!playerHasActiveMedia && browsingRadio);'
        in UI_SOURCE
    )

    assert 'var radioContext = browsingRadio || activeRadio;' not in UI_SOURCE


def test_music_to_radio_transition_refreshes_open_play_queue():
    """
    Radio /status intentionally has current_track_id=null. The finite-track
    -> Radio transition must therefore explicitly refresh an open Play Queue
    instead of relying only on the current_track_id-change branch.
    """
    assert "previousPlayingIdBeforeRadioTransition" in UI_SOURCE
    assert "refreshQueueForRadioTransition" in UI_SOURCE
    assert "loadQueue();" in UI_SOURCE
