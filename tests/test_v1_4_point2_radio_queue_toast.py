import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src" / "ui_web" / "ui.js").read_text(encoding="utf-8")
HTML = (ROOT / "src" / "ui_web" / "index.html").read_text(encoding="utf-8")


def function_block(name, next_marker):
    start = UI.index(name)
    end = UI.index(next_marker, start)
    return UI[start:end]


SUMMARY_HELPERS = function_block(
    "function queueActionSummary(action, tracksList) {",
    "function showQueueActionToast(message, isError) {",
)
QUEUE_HELPERS = function_block(
    "function queueTracksContainLocal(tracksList) {",
    "function positionQueuePopover(anchorEl, popover) {",
)


def run_queue_script(body):
    script = """
var ONLINE_SOURCE_OFFLINE_MESSAGE = "You are offline. Local Music remains available.";
var DAC_PLAYBACK_ERROR_MESSAGE = "DAC unavailable";
var radioActive = false;
var localMaintenance = false;
var fetchCalls = 0;
var pendingFetches = [];
var toasts = [];
var onlineFailures = [];

function resetTidalInfinitePlayGuard() {}
function formatTime(sec) {
    sec = Math.floor(sec);
    var minutes = Math.floor(sec / 60);
    var seconds = sec %% 60;
    return minutes + ":" + (seconds < 10 ? "0" + seconds : seconds);
}
function isRadioCurrentlyActive() { return radioActive; }
function requireOnlineSource() { return true; }
function isLocalLibraryMaintenance() { return localMaintenance; }
function playbackErrorMessage(data, fallback) {
    return (data && data.error) || fallback;
}
function normalizePlaybackErrorMessage(value) {
    if (value && value.message) { return String(value.message); }
    return value ? String(value) : "";
}
function handleOnlineSourceFailure(message) { onlineFailures.push(String(message || "")); }
function showQueueActionToast(message, isError) {
    toasts.push({message: String(message || ""), isError: !!isError});
}
function fetchWithTimeout() {
    fetchCalls += 1;
    return new Promise(function(resolve, reject) {
        pendingFetches.push({resolve: resolve, reject: reject});
    });
}
function response(data, ok) {
    return {
        ok: ok !== false,
        json: function() { return Promise.resolve(data); }
    };
}
function settle() {
    return new Promise(function(resolve) { setImmediate(resolve); });
}

%s
%s

(async function() {
%s
})().catch(function(err) {
    console.error(err && err.stack ? err.stack : err);
    process.exit(1);
});
""" % (SUMMARY_HELPERS, QUEUE_HELPERS, body)
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_radio_summary_exact_wording_capitalization_trimming_and_fallbacks():
    state = run_queue_script(
        """
    console.log(JSON.stringify({
        add: radioQueueActionSummary("queue", "60 North Radio"),
        next: radioQueueActionSummary("next", "60 North Radio"),
        capitalization: radioQueueActionSummary("queue", "  nAiM Jazz  "),
        addFallback: radioQueueActionSummary("queue", "   "),
        nextFallback: radioQueueActionSummary("next", null)
    }));
"""
    )

    assert state == {
        "add": "Added 60 North Radio to the queue",
        "next": "Added 60 North Radio to play next",
        "capitalization": "Added nAiM Jazz to the queue",
        "addFallback": "Added Radio station to the queue",
        "nextFallback": "Added Radio station to play next",
    }


def test_radio_success_waits_for_backend_and_retains_independent_request_names():
    state = run_queue_script(
        """
    var stationA = {
        id: "radio:station:a",
        source: "radio",
        title: "Payload fallback A",
        url: "https://stream.invalid/a",
        context_title: "Programme A"
    };
    var stationB = {
        id: "radio:station:b",
        source: "radio",
        title: "Payload fallback B",
        url: "https://stream.invalid/b",
        context_title: "Programme B"
    };
    submitQueueTracks([stationA], "queue", {radioStationName: "  Station A  "});
    submitQueueTracks([stationB], "next", {radioStationName: "Station B"});
    var beforeBackend = toasts.slice();
    pendingFetches[1].resolve(response({result: "ok", queue_length: 2}));
    await settle();
    pendingFetches[0].resolve(response({result: "ok", queue_length: 1}));
    await settle();
    console.log(JSON.stringify({
        beforeBackend: beforeBackend,
        afterBackend: toasts,
        fetchCalls: fetchCalls
    }));
"""
    )

    assert state == {
        "beforeBackend": [],
        "afterBackend": [
            {"message": "Added Station B to play next", "isError": False},
            {"message": "Added Station A to the queue", "isError": False},
        ],
        "fetchCalls": 2,
    }


def test_missing_name_uses_only_safe_fallback_not_payload_or_technical_data():
    state = run_queue_script(
        """
    var station = {
        id: "radio:station:technical-id",
        source: "radio",
        title: "Radio",
        artist: "Programme Artist",
        url: "https://stream.invalid/live",
        context_title: "Programme Metadata"
    };
    submitQueueTracks([station], "queue", {radioStationName: "   "});
    pendingFetches[0].resolve(response({result: "ok", queue_length: 1}));
    await settle();
    console.log(JSON.stringify(toasts));
"""
    )

    assert state == [
        {"message": "Added Radio station to the queue", "isError": False}
    ]
    message = state[0]["message"]
    for forbidden in (
        "undefined",
        "stream.invalid",
        "Programme",
        "technical-id",
        "Payload",
    ):
        assert forbidden not in message


def test_no_radio_success_toast_on_http_or_backend_failure():
    state = run_queue_script(
        """
    var station = {id: "radio:station:test", source: "radio", title: "Test"};
    function submit() {
        submitQueueTracks([station], "queue", {radioStationName: "Test Radio"});
    }

    submit();
    pendingFetches[0].resolve(response({}, false));
    await settle();

    submit();
    pendingFetches[1].resolve(response({ok: false, error: "Rejected"}));
    await settle();

    submit();
    pendingFetches[2].resolve(response({offline: true, error: "Offline"}));
    await settle();

    submit();
    pendingFetches[3].resolve(response({error: "Queue error"}));
    await settle();

    console.log(JSON.stringify({toasts: toasts, onlineFailures: onlineFailures}));
"""
    )

    assert not [toast for toast in state["toasts"] if toast["isError"] is False]
    assert len(state["onlineFailures"]) == 4


def test_tidal_and_local_shared_summaries_are_unchanged():
    state = run_queue_script(
        """
    console.log(JSON.stringify({
        tidalQueue: queueActionSummary("queue", [{source: "tidal", duration: 0}]),
        tidalNext: queueActionSummary("next", [
            {source: "tidal", duration: 0},
            {source: "tidal", duration: 0}
        ]),
        localQueue: queueActionSummary("queue", [{source: "local", duration: 60}])
    }));
"""
    )

    assert state == {
        "tidalQueue": "Added 1 track to queue",
        "tidalNext": "Added 2 tracks to play next",
        "localQueue": "Added 1 track \u00b7 1:00 to queue",
    }


def test_radio_active_blocking_message_is_unchanged_and_skips_request():
    state = run_queue_script(
        """
    radioActive = true;
    submitQueueTracks(
        [{id: "radio:station:test", source: "radio", title: "Test"}],
        "queue",
        {radioStationName: "Test Radio"}
    );
    console.log(JSON.stringify({toasts: toasts, fetchCalls: fetchCalls}));
"""
    )

    assert state == {
        "toasts": [
            {
                "message": (
                    "Clear the Radio station from the Play Queue before adding to it."
                ),
                "isError": True,
            }
        ],
        "fetchCalls": 0,
    }


def test_radio_menu_passes_only_trimmed_saved_name_as_success_context():
    block = function_block(
        "function showRadioStationMenu(anchorEl, item, e) {",
        "function persistRadioStationOrder(items) {",
    )

    assert block.count('radioStationName: String(item.name || "").trim()') == 2
    for forbidden in (
        "item.url",
        "context_title",
        "radio_metadata",
        "item.artist",
        'item.name || "Radio"',
    ):
        assert forbidden not in block


def test_point2_ui_cache_token_was_advanced_by_later_ui_work():
    marker = '/ui_web/ui.js?v='
    assert marker in HTML
    token = HTML.split(marker, 1)[1].split('"', 1)[0].strip()
    assert token
    assert token != "20260823_v1_4_point2_radio_queue_toast1"
    assert token != "20260823_v1_4_point1_radio_playing_from1"
