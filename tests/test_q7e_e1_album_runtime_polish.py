from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "src/ui_web/ui.js"
UI = UI_PATH.read_text(encoding="utf-8")


def fn(name):
    match = re.search(
        r"(?m)^function\s+" +
        re.escape(name) +
        r"\s*\(",
        UI,
    )

    assert match, name

    brace = UI.find(
        "{",
        match.end(),
    )

    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    pos = brace

    while pos < len(UI):
        char = UI[pos]
        nxt = (
            UI[pos + 1]
            if pos + 1 < len(UI)
            else ""
        )

        if line_comment:
            if char == "\n":
                line_comment = False
            pos += 1
            continue

        if block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                pos += 2
                continue
            pos += 1
            continue

        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            pos += 1
            continue

        if char == "/" and nxt == "/":
            line_comment = True
            pos += 2
            continue

        if char == "/" and nxt == "*":
            block_comment = True
            pos += 2
            continue

        if char in ("'", '"', "`"):
            quote = char
            pos += 1
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1

            if depth == 0:
                return UI[
                    match.start():pos + 1
                ]

        pos += 1

    raise AssertionError(name)


def node(source):
    proc = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert proc.returncode == 0, proc.stderr


def test_qobuz_album_has_retained_catalog_tech_state():
    assert (
        "var qobuzAlbumCatalogTechState = null;"
        in UI
    )

    source = fn(
        "loadQobuzAlbumDetail"
    )

    assert (
        "qobuzAlbumCatalogTechState = {"
        in source
    )

    assert (
        "restoreQobuzAlbumCatalogTechInfo();"
        in source
    )


def test_qobuz_catalog_tech_restore_is_album_specific():
    source = fn(
        "isQobuzAlbumDetailVisible"
    )

    assert (
        'currentViewEndpoint.indexOf("qobuz:album:") === 0'
        in source
    )

    restore = fn(
        "restoreQobuzAlbumCatalogTechInfo"
    )

    assert (
        "qobuzAlbumCatalogTechState.text"
        in restore
    )

    assert (
        "qobuzAlbumCatalogTechState.className"
        in restore
    )


def test_shared_owned_tech_restore_keeps_local_first():
    source = fn(
        "restoreOwnedAlbumDetailTechInfo"
    )

    assert (
        "restoreLocalAlbumDetailTechInfo() ||"
        in source
    )

    assert (
        "restoreQobuzAlbumCatalogTechInfo()"
        in source
    )


def test_status_quality_cannot_replace_qobuz_catalog_tech():
    source = fn("updateTechInfo")

    assert (
        "restoreOwnedAlbumDetailTechInfo()"
        in source
    )


def test_track_change_cannot_hide_qobuz_catalog_tech():
    poll = fn("pollStatus")
    change = fn("_onTrackChange")

    assert (
        "!restoreOwnedAlbumDetailTechInfo()"
        in poll
    )

    assert (
        "!restoreOwnedAlbumDetailTechInfo()"
        in change
    )


def test_show_view_restores_owned_album_tech_without_playback_data():
    source = fn("showView")

    assert (
        'if (name === "album" && albumTechInfo)'
        in source
    )

    assert (
        "!restoreOwnedAlbumDetailTechInfo()"
        in source
    )


def test_streaming_provider_locked_semantics_remain_in_core_function():
    source = fn(
        "streamingProviderPresentation"
    )

    assert 'label: "ONLINE"' in source
    assert 'label: "QOBUZ"' in source
    assert 'label: "TIDAL"' in source


def test_initial_home_provider_render_is_neutral_until_auth_refresh():
    source = fn(
        "streamingProviderInitialHomePresentation"
    )

    node(
        """
const assert = require("assert");
var streamingProviderAuthState = {
    tidal: null,
    qobuz: null,
    requestSerial: 0,
    initialRefreshComplete: false
};
function streamingProviderPresentation() {
    return {
        label: "TIDAL",
        handler: "showTidalSource()",
        dual: false
    };
}
"""
        + source
        + """
let pending =
    streamingProviderInitialHomePresentation();

assert.strictEqual(
    pending.label,
    "\\u00a0"
);

assert.strictEqual(
    pending.handler,
    "return false"
);

assert.strictEqual(
    pending.pending,
    true
);

streamingProviderAuthState.initialRefreshComplete =
    true;

let resolved =
    streamingProviderInitialHomePresentation();

assert.strictEqual(
    resolved.label,
    "TIDAL"
);
"""
    )


def test_load_home_preserves_q7b_presentation_contract_and_neutral_first_paint():
    source = fn("loadHome")

    assert (
        "streamingProviderPresentation()"
        in source
    )

    assert (
        "streamingProviderInitialHomePresentation()"
        in source
    )

    assert (
        "!streamingProviderAuthState.initialRefreshComplete"
        in source
    )

    assert (
        source.index("streamingProviderPresentation()")
        <
        source.index("streamingProviderInitialHomePresentation()")
    )


def test_provider_refresh_marks_first_auth_resolution_complete():
    source = fn(
        "refreshStreamingProviderPresentation"
    )

    assert (
        "streamingProviderAuthState.initialRefreshComplete"
        in source
    )

    complete_at = source.index(
        "streamingProviderAuthState.initialRefreshComplete"
    )

    apply_at = source.index(
        "applyStreamingProviderPresentation();"
    )

    assert complete_at < apply_at


def test_current_streaming_provider_default_is_unchanged():
    assert (
        'var currentStreamingProvider = "tidal";'
        in UI
    )


def test_initial_home_waits_for_provider_resolution_with_bounded_fallback():
    source = fn(
        "loadInitialHomeAfterStreamingProviderResolution"
    )

    # Q7E provider-auth readiness remains bounded by the established
    # 1800 ms fallback.
    assert (
        "refreshStreamingProviderPresentation()"
        in source
    )
    assert "1800" in source
    assert "setTimeout(" in source

    assert (
        ".then(finishProviderResolution)"
        in source
    )
    assert (
        ".catch(finishProviderResolution)"
        in source
    )

    # P7 adds session readiness to first-Home construction. Provider
    # resolution and /session settlement must both complete before loadHome.
    assert "var providerReady = new Promise(" in source
    assert "return Promise.all([" in source
    assert (
        "Promise.resolve(sessionReady).catch(function() {})"
        in source
    )
    assert "loadHome();" in source

    assert (
        source.index("Promise.all([")
        < source.index("loadHome();")
    )


def test_initial_home_coordinator_finishes_only_once():
    source = fn(
        "loadInitialHomeAfterStreamingProviderResolution"
    )

    # The provider side of the coordinator can complete either from the
    # normal refresh or the bounded fallback, but only the first completion
    # resolves providerReady.
    assert (
        "var providerCompleted = false;"
        in source
    )
    assert (
        "if (providerCompleted) { return; }"
        in source
    )
    assert (
        "providerCompleted = true;"
        in source
    )
    assert source.count("resolve();") == 1

    # Promise.all supplies the single first-Home continuation after both
    # provider readiness and P7 session readiness have settled.
    assert source.count("Promise.all([") == 1
    assert source.count("loadHome();") == 1


def test_domcontentloaded_resolves_provider_before_initial_home():
    marker = 'window.addEventListener("DOMContentLoaded"'
    start = UI.index(marker)
    end = UI.index(
        "function initPlayerTechTray",
        start,
    )
    bootstrap = UI[start:end]

    assert (
        "startOnlineSourcePolling();"
        in bootstrap
    )

    # P7 starts /session immediately and passes that promise into the
    # existing provider-resolution coordinator. Home itself is not built
    # directly from DOMContentLoaded.
    assert (
        "var initialSessionRestore = restoreSession();"
        in bootstrap
    )
    assert (
        "loadInitialHomeAfterStreamingProviderResolution("
        "initialSessionRestore"
        ");"
        in bootstrap
    )

    assert (
        bootstrap.index(
            "startOnlineSourcePolling();"
        )
        < bootstrap.index(
            "var initialSessionRestore = restoreSession();"
        )
        < bootstrap.index(
            "loadInitialHomeAfterStreamingProviderResolution("
        )
    )

    assert "loadHome();" not in bootstrap


def test_load_home_q7b_q7d_presentation_contract_remains_present():
    source = fn("loadHome")

    assert (
        "streamingProviderPresentation()"
        in source
    )

    assert (
        "streamingProviderInitialHomePresentation()"
        in source
    )

    assert (
        "refreshStreamingProviderPresentation();"
        in source
    )
