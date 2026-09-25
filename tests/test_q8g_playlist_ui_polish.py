import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src" / "ui_web" / "ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "src" / "ui_web" / "srova.css").read_text(encoding="utf-8")
INDEX = (ROOT / "src" / "ui_web" / "index.html").read_text(encoding="utf-8")


def function_source(name):
    match = re.search(
        r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{",
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

    raise AssertionError("unterminated " + name)


def test_q8g_qobuz_queue_uses_canonical_provider_label():
    source = function_source("sourceLabelForTrack")
    assert 'id.indexOf("qobuz:") === 0' in source
    assert 'return "QOBUZ"' in source
    assert source.index('id.indexOf("qobuz:") === 0') < source.index('return "TIDAL"')


def test_q8g_both_playlist_providers_prefer_track_artwork_in_queue_payload():
    source = function_source("buildTrackPayload")
    assert 'currentViewEndpoint.indexOf("/tidal/playlist/") === 0' in source
    assert 'currentViewEndpoint.indexOf("qobuz:playlist:") === 0' in source
    assert "streamingPlaylist" in source
    assert "preferTrackCover ? trackCover" in source


def test_q8g_playlist_trackmap_prefers_individual_track_artwork():
    source = function_source("renderTrackList")
    assert "streamingPlaylistDetail" in source
    assert "? (rowTrackCover || ctxCover)" in source
    assert '" streamingPlaylistTrack"' in source


def test_q8g_playlist_actions_are_permanently_visible():
    start = CSS.index(".streamingPlaylistTrack .trackAddBtn,")
    end = CSS.index("}", start)
    block = CSS[start:end]

    assert ".playlistEditableTrack .trackRemoveBtn" in block
    assert "opacity: 1 !important;" in block
    assert "visibility: visible !important;" in block


def test_q8g_playlist_header_uses_existing_low_key_placeholder():
    assert "setupArtworkFallback(albumArt);" in UI
    assert ".srovaArtworkPlaceholder {" in CSS
    assert "SROVA_ARTWORK_PLACEHOLDER_SRC" in UI


def test_q8g_static_assets_have_single_new_cache_tokens():
    css_marker = "/ui_web/srova.css?v="
    js_marker = "/ui_web/ui.js?v="

    # Q8G owns playlist UI behavior, not permanent ownership of the
    # literal cache token. Later release streams legitimately advance it.
    assert INDEX.count(css_marker) == 1
    assert INDEX.count(js_marker) == 1

    css_token = INDEX.split(css_marker, 1)[1].split('"', 1)[0]
    js_token = INDEX.split(js_marker, 1)[1].split('"', 1)[0]

    assert css_token
    assert js_token
    assert not any(ch.isspace() for ch in css_token)
    assert not any(ch.isspace() for ch in js_token)


def test_q8g_playlist_list_thumbnail_uses_same_local_artwork_fallback():
    source = function_source("renderPlaylistRows")

    assert "SROVA_ARTWORK_PLACEHOLDER_SRC" in source
    assert 'row.querySelector(".playlistThumb")' in source
    assert "setupArtworkFallback(" in source
