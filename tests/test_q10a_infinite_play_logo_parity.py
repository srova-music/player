from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
INDEX = (ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")
BACKEND = (ROOT / "src/main_headless.py").read_text(encoding="utf-8")


EXPECTED_HELPER = '''function shouldShowInfinitePlayUi(enabled) {
    if (!enabled) { return false; }

    var status = lastKnownPlaybackStatus || {};
    var effectiveProvider = String(
        status.infinite_play_effective_provider || ""
    ).trim().toLowerCase();

    if (effectiveProvider !== "tidal" && effectiveProvider !== "qobuz") {
        return false;
    }

    if (playerHasActiveMedia) {
        return playerBarActivePlaybackSource === effectiveProvider;
    }

    return currentSourceSection === "streaming" &&
        currentStreamingProvider === effectiveProvider;
}'''


def test_q10a_player_bar_visibility_uses_runtime_effective_provider():
    assert UI.count(EXPECTED_HELPER) == 1

    assert 'if (!enabled) { return false; }' in EXPECTED_HELPER
    assert "lastKnownPlaybackStatus || {}" in EXPECTED_HELPER
    assert "status.infinite_play_effective_provider" in EXPECTED_HELPER

    assert (
        'effectiveProvider !== "tidal" && '
        'effectiveProvider !== "qobuz"'
        in EXPECTED_HELPER
    )

    assert (
        "playerBarActivePlaybackSource === effectiveProvider"
        in EXPECTED_HELPER
    )
    assert (
        'currentSourceSection === "streaming"'
        in EXPECTED_HELPER
    )
    assert (
        "currentStreamingProvider === effectiveProvider"
        in EXPECTED_HELPER
    )


def test_q10a_paused_streaming_track_remains_provider_aware():
    # Active media keeps the same provider/effective-provider contract
    # whether transport is playing or paused.
    assert "if (playing)" not in EXPECTED_HELPER

    assert (
        "return playerBarActivePlaybackSource === effectiveProvider;"
        in EXPECTED_HELPER
    )

    # The former provider-neutral paused rule must not return.
    assert (
        'playerBarActivePlaybackSource === "tidal" ||'
        not in EXPECTED_HELPER
    )
    assert (
        'playerBarActivePlaybackSource === "qobuz"'
        not in EXPECTED_HELPER
    )


def test_q10a_removes_tidal_only_active_playback_visibility():
    # Active playback must follow the backend-owned effective provider.
    assert (
        "return playerBarActivePlaybackSource === effectiveProvider;"
        in EXPECTED_HELPER
    )

    # The old active-playback TIDAL-only rule must not return.
    assert (
        'return playerBarActivePlaybackSource === "tidal";'
        not in EXPECTED_HELPER
    )

    # Idle/browsing visibility also remains provider-aware.
    assert (
        'currentStreamingProvider === "tidal"'
        not in EXPECTED_HELPER
    )


def test_q10a_keeps_existing_player_control_contract():
    assert "function updatePlayerInfinitePlayControl()" in UI
    assert "var enabled = !!tidalInfinitePlayEnabled;" in UI
    assert "var uiVisible = shouldShowInfinitePlayUi(enabled);" in UI

    assert INDEX.count('id="playerInfinitePlayControl"') == 1
    assert INDEX.count('id="playerInfinitePlayBtn"') == 1

    # Q10A reuses the existing provider-neutral control.
    assert 'id="playerQobuzInfinitePlayControl"' not in INDEX
    assert 'id="qobuzInfinitePlayBtn"' not in INDEX


def test_q10a_runtime_effective_provider_remains_backend_owned():
    assert (
        '"infinite_play_effective_provider": '
        '_effective_infinite_play_provider()'
        in BACKEND
    )

    # Existing Q9 refill runtime contract remains provider-aware.
    assert 's.infinite_play_effective_provider || ""' in UI
    assert (
        'if (effectiveProvider !== "tidal" && '
        'effectiveProvider !== "qobuz")'
        in UI
    )
    assert "activeProvider !== effectiveProvider" in UI


def test_q10a_helper_does_not_use_saved_settings_provider():
    assert "q9dInfinitePlayProvider" not in EXPECTED_HELPER
    assert "normalizeQ9dProvider" not in EXPECTED_HELPER


def test_q10a_js_cache_token_is_bumped():
    assert (
        "/ui_web/ui.js?"
        "v=20260912_v2_0_q10a_infinite_play_pause_logo_js4"
        in INDEX
    )

    assert (
        "20260912_v2_0_q9d_provider_title_row_js3"
        not in INDEX
    )


def test_q10a_infinite_play_provider_change_is_guarded_only_while_playing():
    save = UI[
        UI.index("function saveQ9dProviderPreference("):
        UI.index("function buildQ9dProviderSelector(")
    ]

    assert 'featureKey === "infinite_play"' in save
    assert "playing" in save
    assert "playerHasActiveMedia" not in save

    assert (
        '"Pause playback to change Infinite Play provider."'
        in save
    )
    assert (
        '"Stop playback to change Infinite Play provider."'
        not in save
    )
    assert "showQueueActionToast(" in save

    # Auto-Mix continues using the same shared save path without
    # acquiring the Infinite Play playback guard.
    assert (
        'featureKey === "automix" && playing'
        not in save
    )


def test_q10a_provider_guard_syncs_immediately_on_pause_resume_and_status():
    toggle = UI[
        UI.index("function togglePlayPause()"):
        UI.index("function _onTrackChange()")
    ]

    poll = UI[
        UI.index("function pollStatus()"):
        UI.index("function updateProgress(")
    ]

    assert "playing = false;" in toggle
    assert "playing   = true;" in toggle
    assert toggle.count("syncQ9dProviderSelectors();") >= 2

    assert "var statusPlaying = !!s.playing;" in poll
    assert "playing = statusPlaying;" in poll
    assert "syncQ9dProviderSelectors();" in poll


def test_q10a_infinite_play_selector_has_clickable_grey_guard_state():
    sync = UI[
        UI.index("function syncQ9dProviderSelectors("):
        UI.index("function saveQ9dProviderPreference(")
    ]

    assert 'featureKey === "infinite_play"' in sync
    assert "playing" in sync
    assert "playerHasActiveMedia" not in sync
    assert "q9dProviderSelectorPlaybackLocked" in sync
    assert '"aria-disabled"' in sync

    css = (
        ROOT / "src/ui_web/srova.css"
    ).read_text(encoding="utf-8")

    marker = (
        ".q9dProviderSelectorRow."
        "q9dProviderSelectorPlaybackLocked"
    )

    assert marker in css
    locked_css = css[css.index(marker):]

    assert "grayscale(1)" in locked_css
    assert "cursor: not-allowed !important;" in locked_css

    # The control must still receive clicks so the save guard can
    # show its explanatory toast.
    assert "pointer-events: none" not in locked_css[:900]


def test_q10a_guard_cache_tokens_are_current():
    assert (
        "/ui_web/ui.js?"
        "v=20260912_v2_0_q10a_infinite_play_pause_logo_js4"
        in INDEX
    )

    assert (
        "/ui_web/srova.css?"
        "v=20260914_v2_0_q10d_auth_ux_css2_q10f_provider_aware_go_to_album_css3"
        in INDEX
    )
