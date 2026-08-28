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


def test_radio_helper_uses_only_trimmed_authoritative_station_name():
    block = function_block(
        'var currentRadioPlayingFromName = "";',
        "function syncPlayerBarRadioProgressState() {",
    )

    assert 'String(station.name || "").trim()' in block
    assert 'fromLabelEl.textContent = "PLAYING FROM";' in block
    assert "nowPlayingFrom.textContent = currentRadioPlayingFromName;" in block
    assert 'nowPlayingFrom.style.cursor = "";' in block
    assert "nowPlayingFrom.onclick = null;" in block
    for forbidden in (
        "radio_metadata",
        "context_title",
        "station.title",
        "station.url",
        '|| "Radio"',
    ):
        assert forbidden not in block


def test_radio_helper_trims_clears_and_rejects_fallbacks_at_runtime():
    helper = function_block(
        'var currentRadioPlayingFromName = "";',
        "function syncPlayerBarRadioProgressState() {",
    )
    script = """
var label = {textContent: "OLD LABEL"};
var oldClick = function() {};
var nowPlayingFrom = {
    textContent: "STALE TIDAL CONTEXT",
    style: {cursor: "pointer"},
    onclick: oldClick
};
var document = {
    getElementById: function(id) {
        return id === "nowPlayingFromLabel" ? label : null;
    }
};
%s
syncRadioPlayingFromStation({
    name: "  Naim Jazz  ",
    title: "Programme title",
    url: "https://stream.invalid/live",
    context_title: "Context fallback"
});
var named = {
    label: label.textContent,
    value: nowPlayingFrom.textContent,
    cursor: nowPlayingFrom.style.cursor,
    clickable: nowPlayingFrom.onclick !== null
};
syncRadioPlayingFromStation({
    name: "   ",
    title: "Programme title",
    url: "https://stream.invalid/live",
    context_title: "Context fallback",
    radio_metadata: {title: "Programme title"}
});
var blank = {
    label: label.textContent,
    value: nowPlayingFrom.textContent,
    cursor: nowPlayingFrom.style.cursor,
    clickable: nowPlayingFrom.onclick !== null
};
console.log(JSON.stringify({named: named, blank: blank}));
""" % helper
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    state = json.loads(result.stdout)

    assert state["named"] == {
        "label": "PLAYING FROM",
        "value": "Naim Jazz",
        "cursor": "",
        "clickable": False,
    }
    assert state["blank"] == {
        "label": "PLAYING FROM",
        "value": "",
        "cursor": "",
        "clickable": False,
    }


def test_successful_radio_start_uses_authoritative_response_station():
    block = function_block(
        "function playRadioStation(item) {",
        "function buildRadioStationPayload(item) {",
    )

    assert "syncRadioPlayingFromStation((data && data.station) || {});" in block
    assert "syncRadioPlayingFromStation(item" not in block
    assert block.index("if (data && data.ok === false)") < block.index(
        "syncRadioPlayingFromStation((data && data.station) || {});"
    )


def test_radio_status_refreshes_station_name_including_open_now_playing():
    block = function_block("function pollStatus() {", "setInterval(pollStatus, 1000);")

    assert "lastKnownPlaybackStatus = s;" in block
    assert "if (s.radio_mode) {" in block
    assert "syncRadioPlayingFromStation(s.radio_station || {});" in block
    assert block.index("syncRadioPlayingFromStation(s.radio_station || {});") < block.index(
        "if (nowPlayingView && !nowPlayingView.classList.contains(\"hidden\"))"
    )


def test_radio_session_restore_syncs_before_early_return():
    block = function_block("function restoreSession() {", "function _updateNowPlayingLinks(s) {")
    radio_start = block.index(
        'if (isRadioLiveStatus(s) && (s.radio_mode || s.source === "radio" || s.context_type === "radio"))'
    )
    radio_end = block.index("            }", radio_start)
    radio_block = block[radio_start:radio_end]

    assert 'setPlayerBarActivePlaybackSource("radio");' in radio_block
    assert "syncRadioPlayingFromStation(s.radio_station || {});" in radio_block
    assert radio_block.index("syncRadioPlayingFromStation") < radio_block.index("return;")


def test_open_now_playing_overrides_stale_context_only_for_active_radio():
    block = function_block("function openNowPlaying() {", "function closeNowPlaying() {")

    assert 'var radioPlayingFromActive = playerBarActivePlaybackSource === "radio";' in block
    assert 'fromLabel = "PLAYING FROM";' in block
    assert "srcTitle = currentRadioPlayingFromName;" in block
    assert "if (radioPlayingFromActive) { renderRadioPlayingFromPresentation(); }" in block
    assert 'else if (srcType === "radio")    { fromLabel = "LIVE RADIO"; }' in block
    assert block.index('else if (srcType === "radio")') < block.index(
        "if (radioPlayingFromActive) {"
    )


def test_existing_tidal_and_local_playing_from_paths_are_unchanged():
    open_block = function_block("function openNowPlaying() {", "function closeNowPlaying() {")
    links_block = function_block(
        "function _updateNowPlayingLinks(s) {",
        "function _updatePlayerBarLinks(s) {",
    )

    assert (
        'var srcTitle = playbackSource.title || (currentContext ? (currentContext.title || "") : "") || (meta.contextTitle || "");'
        in open_block
    )
    for mapping in (
        'srcType === "album"',
        'srcType === "playlist"',
        'srcType === "mix"',
        'srcType === "artist"',
        'srcType === "search"',
        'srcType === "mysongs"',
        'srcType === "myalbums"',
        'srcType === "hires"',
        'srcType === "home"',
    ):
        assert mapping in open_block
    assert "var ctxTitle = s.context_title || s.album || \"\";" in links_block
    assert "nowPlayingFrom.textContent = ctxTitle;" in links_block
    assert '_setPlaybackSource(data.context_type || "local"' in UI
    assert "_setPlaybackSource(ctxType || \"album\", ctxId, ctxTitle);" in UI


def test_point1_ui_cache_versioning_contract_remains_current():
    marker = '/ui_web/ui.js?v='
    assert marker in HTML
    token = HTML.split(marker, 1)[1].split('"', 1)[0].strip()
    assert token
    assert token != "20260823_v1_4_point1_radio_playing_from1"
