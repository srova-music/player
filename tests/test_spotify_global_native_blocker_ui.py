import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/ui_web/srova.css").read_text(encoding="utf-8")
HTML = (ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")


def function_source(name):
    match = re.search(
        rf"\bfunction\s+{re.escape(name)}\s*\([^)]*\)\s*\{{",
        UI,
    )
    assert match, f"missing function: {name}"
    start = match.start()
    cursor = match.end() - 1
    depth = 0
    quote = None
    escaped = False
    while cursor < len(UI):
        char = UI[cursor]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        else:
            if char in ("'", '"', "`"):
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return UI[start:cursor + 1]
        cursor += 1
    raise AssertionError(f"unterminated function: {name}")


def test_existing_spotify_status_contract_is_the_global_poll_source():
    poll = function_source("pollSpotifyNativeBlockStatus")
    start = function_source("startSpotifyNativeBlockPolling")
    assert 'fetchWithTimeout("/api/spotify/status", {cache: "no-store"}, 4000)' in poll
    assert "syncSpotifyNativeBlockedFromStatus(status);" in poll
    assert "SPOTIFY_NATIVE_BLOCK_POLL_INTERVAL_MS = 1000" in UI
    assert "window.setInterval(" in start
    assert "pollSpotifyNativeBlockStatus" in start
    assert "/api/spotify/native" not in UI


def test_native_blocked_boolean_remains_the_native_playback_guard_authority():
    synchronizer = function_source("syncSpotifyNativeBlockedFromStatus")
    guard = function_source("requireNativePlaybackAvailable")
    presentation = function_source("syncNativePlaybackBlockerPresentation")

    assert 'typeof status.native_blocked !== "boolean"' in synchronizer
    assert "spotifyNativeBlocked = status.native_blocked;" in synchronizer
    assert "spotifyNativeBlockState" in synchronizer

    assert "spotifyNativeBlocked === true" in guard
    assert "spotifyNativeBlockState" not in guard
    assert "spotify_owner" not in guard
    assert ".state" not in guard

    assert "spotifyNativeBlocked === true" in presentation
    assert "spotifyNativeBlockState" in presentation

    for lifecycle_state in (
        "disabled",
        "standby",
        "acquiring",
        "owned",
        "releasing",
        "recovering",
        "safe_error",
        "unsafe_error",
    ):
        assert lifecycle_state not in guard


def test_malformed_status_does_not_change_last_authoritative_value():
    synchronizer = function_source("syncSpotifyNativeBlockedFromStatus")
    script = f"""
let spotifyNativeBlocked = true;
let spotifyNativeBlockState = "";
let syncCount = 0;
function syncNativePlaybackBlockerPresentation() {{ syncCount += 1; }}
{synchronizer}
const malformed = [null, {{}}, {{native_blocked: "false"}}, {{native_blocked: 0}}];
const results = malformed.map(function(value) {{
    const accepted = syncSpotifyNativeBlockedFromStatus(value);
    return [accepted, spotifyNativeBlocked, syncCount];
}});
syncSpotifyNativeBlockedFromStatus({{native_blocked: false}});
results.push([true, spotifyNativeBlocked, syncCount]);
process.stdout.write(JSON.stringify(results));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == [
        [False, True, 0],
        [False, True, 0],
        [False, True, 0],
        [False, True, 0],
        [True, False, 1],
    ]


def test_failed_poll_preserves_last_authoritative_value():
    poll = function_source("pollSpotifyNativeBlockStatus")
    failure = poll[poll.index(".catch(function()") :]
    assert "Preserve the last authoritative native_blocked value." in failure
    assert "spotifyNativeBlocked =" not in failure
    assert "syncSpotifyNativeBlockedFromStatus" not in failure


def test_global_blocked_presentation_and_accessibility_exist():
    assert 'id="nativePlaybackBlocker"' in HTML
    assert 'class="nativePlaybackBlocker hidden"' in HTML
    assert 'role="alert"' in HTML
    assert 'aria-live="assertive"' in HTML
    assert 'aria-hidden="true"' in HTML
    assert "SROVA PLAYBACK UNAVAILABLE" in HTML
    assert "Spotify Connect is currently using the selected DAC." in HTML
    assert "disconnect this device in Spotify" in HTML
    assert "STOP SPOTIFY CONNECT" in HTML
    presentation = function_source("syncNativePlaybackBlockerPresentation")
    assert 'nativePlaybackBlocker.setAttribute("aria-hidden", visible ? "false" : "true")' in presentation
    assert 'document.body.classList.toggle("nativePlaybackBlocked", visible)' in presentation

def test_blocker_stop_action_posts_deactivate_without_settings_navigation():
    stop = function_source("stopSpotifyConnectFromNativeBlocker")
    init = function_source("initNativePlaybackBlocker")
    assert '"/api/spotify/deactivate"' in stop
    assert '"/api/spotify/disable"' not in stop
    assert 'method: "POST"' in stop
    assert "data.ok !== true" in stop
    assert "pollSpotifyNativeBlockStatus();" in stop
    assert "showSettings(" not in stop
    assert "setSettingsTab(" not in stop
    assert "stopSpotifyConnectFromNativeBlocker" in init
    assert 'id="nativePlaybackBlockerStopBtn"' in HTML
    assert 'aria-label="Stop Spotify Connect"' in HTML

def test_show_view_immediately_resynchronizes_blocker_presentation():
    source = function_source("showView")
    assert "currentSrovaView = name;" in source
    assert "syncNativePlaybackBlockerPresentation();" in source


def assert_guard_precedes(function_name, operation):
    source = function_source(function_name)
    guard = "requireNativePlaybackAvailable()"
    assert guard in source
    assert operation in source
    assert source.index(guard) < source.index(operation)


def test_all_canonical_native_playback_gateways_use_the_central_guard():
    assert_guard_precedes("postTidalQueueReplace", 'fetchWithTimeout("/tidal/queue/replace"')
    assert_guard_precedes("playLocalLibraryTrack", 'fetch("/api/local/library/play"')
    assert_guard_precedes("playRadioStation", 'fetchWithTimeout("/api/radio/play/"')
    assert_guard_precedes("togglePlayPause", 'fetch("/tidal/pause")')
    assert_guard_precedes("prevTrack", 'fetch("/tidal/prev")')
    assert_guard_precedes("nextTrack", 'fetch("/tidal/next")')
    assert_guard_precedes("requestSeekTo", 'fetch("/tidal/seek/"')


def test_direct_queue_jump_uses_central_guard_before_request():
    start = UI.index("// Tap row = jump to that track")
    end = UI.index("return row;", start)
    source = UI[start:end]
    assert "requireNativePlaybackAvailable()" in source
    assert 'fetch("/tidal/queue/jump/" + idx)' in source
    assert source.index("requireNativePlaybackAvailable()") < source.index(
        'fetch("/tidal/queue/jump/" + idx)'
    )


def test_central_guard_uses_normal_toast_and_no_inferred_authority():
    guard = function_source("requireNativePlaybackAvailable")
    assert "showQueueActionToast(SPOTIFY_NATIVE_BLOCKED_MESSAGE, true);" in guard
    assert "return false;" in guard
    assert "return true;" in guard
    assert "spotify_owner" not in guard
    assert ".state" not in guard


def test_central_guard_allows_unknown_and_false_but_blocks_true():
    guard = function_source("requireNativePlaybackAvailable")
    script = f"""
let spotifyNativeBlocked = null;
const SPOTIFY_NATIVE_BLOCKED_MESSAGE = "blocked";
const toasts = [];
function showQueueActionToast(message, isError) {{ toasts.push([message, isError]); }}
{guard}
const results = [requireNativePlaybackAvailable()];
spotifyNativeBlocked = false;
results.push(requireNativePlaybackAvailable());
spotifyNativeBlocked = true;
results.push(requireNativePlaybackAvailable());
process.stdout.write(JSON.stringify([results, toasts]));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == [
        [True, True, False],
        [["blocked", True]],
    ]


def test_normal_handoff_states_suppress_only_full_page_blocker_presentation():
    presentation = function_source("syncNativePlaybackBlockerPresentation")

    script = f"""
let spotifyNativeBlocked = true;
let spotifyNativeBlockState = "";
let currentSrovaView = "home";
let spotifyNativeBlockStopBusy = false;

const visibleHistory = [];

const nativePlaybackBlocker = {{
    classList: {{
        toggle: function(name, hidden) {{
            if (name === "hidden") {{
                visibleHistory.push(!hidden);
            }}
        }}
    }},
    setAttribute: function() {{}}
}};

const document = {{
    body: {{
        classList: {{
            toggle: function() {{}}
        }}
    }}
}};

function setNativePlaybackBlockerStopBusy() {{}}

{presentation}

function sample(state, blocked, view) {{
    spotifyNativeBlockState = state;
    spotifyNativeBlocked = blocked;
    currentSrovaView = view || "home";
    syncNativePlaybackBlockerPresentation();
    return visibleHistory[visibleHistory.length - 1];
}}

const result = {{
    acquiring: sample("acquiring", true),
    releasing: sample("releasing", true),
    recovering: sample("recovering", true),
    owned: sample("owned", true),
    unsafe_error: sample("unsafe_error", true),
    standby_fail_closed: sample("standby", true),
    unblocked: sample("owned", false),
    settings_owned: sample("owned", true, "settings")
}};

process.stdout.write(JSON.stringify(result));
"""

    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "acquiring": False,
        "releasing": False,
        "recovering": False,
        "owned": True,
        "unsafe_error": True,
        "standby_fail_closed": True,
        "unblocked": False,
        "settings_owned": False,
    }


def test_blocker_adds_no_spotify_transport_metadata_artwork_or_volume_ui():
    blocker_start = HTML.index('<div id="nativePlaybackBlocker"')
    blocker_end = HTML.index('<div id="add-radio-modal"', blocker_start)
    blocker = HTML[blocker_start:blocker_end].lower()
    for forbidden in (
        "play spotify",
        "pause spotify",
        "spotify metadata",
        "spotify artwork",
        "spotify volume",
        "now playing",
    ):
        assert forbidden not in blocker

def test_sp3c_cache_bust_tokens_are_exact_and_stale_tokens_are_absent():
    assert HTML.count("_sp3b_spotify_settings_css3") == 1
    assert HTML.count("_bf4_spotify_status_sync_js9") == 1
    assert "_bf2_spotify_handoff_js6" not in HTML
    assert "_sp3b_spotify_settings_css2" not in HTML
    assert "_sp3b_spotify_settings_js4" not in HTML
    assert "_sp3b_spotify_settings_js5" not in HTML

def test_desktop_mobile_and_android_webview_presentation_contracts_exist():
    assert ".nativePlaybackBlocker {" in CSS
    assert "position: fixed !important;" in CSS
    assert "z-index: 30000 !important;" in CSS
    assert "body.nativePlaybackBlocked > #playerBar" in CSS
    mobile = CSS[CSS.rindex("@media (max-width: 520px)") :]
    assert ".nativePlaybackBlockerCard" in mobile
    assert ".nativePlaybackBlockerAction" in mobile
    assert "width: 100% !important;" in mobile
    assert "html.srovaAndroidApkWebView .nativePlaybackBlocker" in CSS
    assert "env(safe-area-inset-bottom)" in CSS
