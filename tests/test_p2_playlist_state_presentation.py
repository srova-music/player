from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/ui_web/srova.css").read_text(encoding="utf-8")
INDEX = (ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")


def function_source(name):
    match = re.search(
        rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{",
        UI,
    )
    assert match, name

    brace = UI.find("{", match.start())
    depth = 0
    quote = None
    escaped = False

    for index in range(brace, len(UI)):
        char = UI[index]

        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in ("'", '"', "`"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return UI[match.start():index + 1]

    raise AssertionError(name)


def test_p2_shared_playlist_state_component_has_semantic_modes():
    source = function_source("renderPlaylistsState")

    assert '"loading"' in source
    assert '"error"' in source
    assert '"empty"' in source
    assert '"filter-empty"' in source

    assert 'state.className = "playlistsState"' in source
    assert 'state.setAttribute("data-state", mode)' in source
    assert '"aria-live"' in source
    assert '"aria-busy"' in source
    assert 'mode === "error" ? "alert" : "status"' in source

    assert source.count('"playlistsStateBar') >= 1
    assert "for (var i = 1; i <= 5; i++)" in source


def test_p2_tidal_loader_keeps_locked_retry_semantics_but_hides_counter():
    source = function_source("loadMyPlaylists")

    assert 'fetch("/tidal/myplaylists")' in source
    assert "MY_PLAYLISTS_MAX_RETRIES" in source
    assert "MY_PLAYLISTS_RETRY_MS" in source
    assert "retryCount + 1" in source
    assert "tidalLibraryUiGeneration" in source

    assert "retryCount === 0" in source
    assert "renderPlaylistsState(" in source
    assert '"loading"' in source
    assert '"Loading Playlists…"' in source

    assert "Fetching from Tidal (" not in source

    assert '"empty"' in source
    assert '"No playlists found."' in source

    assert '"error"' in source
    assert '"Could not load playlists."' in source


def test_p2_qobuz_uses_same_visual_state_language_without_api_change():
    source = function_source("loadQobuzPlaylists")

    assert '"/qobuz/catalog?op=playlists"' in source
    assert "8000" in source

    assert 'renderPlaylistsState(' in source
    assert '"loading"' in source
    assert '"Loading Playlists…"' in source

    assert '"empty"' in source
    assert '"No playlists found."' in source

    assert '"error"' in source
    assert '"Could not load playlists."' in source

    assert "Loading Qobuz playlists..." not in source


def test_p2_filter_empty_uses_related_static_state():
    source = function_source("renderPlaylistRows")

    assert "renderPlaylistsState(" in source
    assert '"filter-empty"' in source
    assert '"No matching playlists."' in source


def test_p2_loader_is_centered_on_both_axes_and_only_loading_animates():
    assert ".playlistsState {" in CSS
    assert "align-items: center !important;" in CSS
    assert "justify-content: center !important;" in CSS
    assert "text-align: center !important;" in CSS
    assert "min-height: clamp(" in CSS

    assert '.playlistsState[data-state="loading"] .playlistsStateCore' in CSS
    assert "srovaRoundLogoRingGlow" in CSS
    assert "srovaRoundLogoEq1" in CSS
    assert "srovaRoundLogoEq5" in CSS

    assert '.playlistsState[data-state="error"]' in CSS
    assert '.playlistsState[data-state="empty"]' in CSS
    assert '.playlistsState[data-state="filter-empty"]' in CSS

    assert "@media (prefers-reduced-motion: reduce)" in CSS


def test_p2_asset_tokens_advanced_once():
    assert INDEX.count("/ui_web/ui.js?v=") == 1
    assert INDEX.count("/ui_web/srova.css?v=") == 1

    js_token = INDEX.split("/ui_web/ui.js?v=", 1)[1].split('"', 1)[0]
    css_token = INDEX.split("/ui_web/srova.css?v=", 1)[1].split('"', 1)[0]

    assert js_token.endswith("_p2_playlist_states_js1")
    assert css_token.endswith("_p2_playlist_states_css1")
