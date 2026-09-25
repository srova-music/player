from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "src/ui_web/ui.js"
CSS_PATH = ROOT / "src/ui_web/srova.css"

UI = UI_PATH.read_text(encoding="utf-8")
CSS = CSS_PATH.read_text(encoding="utf-8")


def fn(name):
    m = re.search(
        r"(?m)^function\s+" +
        re.escape(name) +
        r"\s*\(",
        UI,
    )
    assert m, name

    brace = UI.find("{", m.end())
    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    pos = brace

    while pos < len(UI):
        c = UI[pos]
        n = UI[pos + 1] if pos + 1 < len(UI) else ""

        if line_comment:
            if c == "\n":
                line_comment = False
            pos += 1
            continue

        if block_comment:
            if c == "*" and n == "/":
                block_comment = False
                pos += 2
                continue
            pos += 1
            continue

        if quote:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == quote:
                quote = None
            pos += 1
            continue

        if c == "/" and n == "/":
            line_comment = True
            pos += 2
            continue

        if c == "/" and n == "*":
            block_comment = True
            pos += 2
            continue

        if c in ("'", '"', "`"):
            quote = c
            pos += 1
            continue

        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return UI[m.start():pos + 1]

        pos += 1

    raise AssertionError(name)


def test_e2a_shared_artist_geometry():
    source = fn("setAlbumViewKind")

    assert 'kind === "qobuz-artist"' in source
    assert 'albumView.classList.add("tidalArtistDetail")' in source
    assert 'sourceLabel = "QOBUZ"' in source


def test_e2a_single_q7c_artist_page_request():
    source = fn("loadQobuzArtistDetail")

    assert (
        '"/qobuz/catalog?op=artist_page&artist_id="'
        in source
    )
    assert "_renderArtistPage(" in source
    assert "qobuzArtistPageFallbackArtwork(" in source

    for forbidden in (
        "op=artist_releases",
        "op=artist_story",
        "op=similar_artists",
        "op=search_",
    ):
        assert forbidden not in source


def test_e2a_qobuz_identity_preserved_by_shared_payload():
    source = fn("buildTrackPayload")

    assert 'indexOf("qobuz:") === 0' in source
    assert 'payload.source = "qobuz"' in source
    assert "payload.provider_track_id" in source


def test_e2a_qobuz_artist_row_has_no_tidal_favorite():
    source = fn("_buildArtistTrackRow")

    assert "qobuzTrack" in source
    assert "if (!qobuzTrack)" in source
    assert "buildTrackPayload(" in source
    assert "showQueuePopover(" in source


def test_e2a_artist_playback_uses_shared_q5_replace():
    source = fn("_playArtistTopTrack")

    assert "qobuzArtist" in source
    assert "buildTrackPayload(" in source
    assert "postTidalQueueReplace(" in source
    assert 'context_type:  "artist"' in source

    assert "/qobuz/play" not in source
    assert "/qobuz/queue" not in source


def test_e2a_qobuz_trackmap_keeps_actual_performer():
    source = fn("_playArtistTopTrack")

    assert "t.artist || artistName" in source


def test_e2a_discography_sort_remains_available():
    rerender = fn("_rerenderDiscography")
    renderer = fn("_renderArtistPage")

    assert 'if (_artistDiscogSort === "date")' in rerender
    assert '"Popularity"' in renderer
    assert '"Release Date"' in renderer


def test_e2a_qobuz_discography_uses_existing_card_builder():
    source = fn("_buildDiscoCard")

    assert 'alb.source === "qobuz"' in source
    assert "_qobuzArtistPageRestoreFn" in source
    assert "loadQobuzAlbumDetail(" in source
    assert '"artistpage"' in source


def test_e2a_album_artist_navigation():
    album = fn("loadQobuzAlbumDetail")
    wire = fn("wireQobuzAlbumArtistClick")

    assert "wireQobuzAlbumArtistClick(" in album
    assert "currentContext.artist_id" in wire
    assert "albumArtist.onclick" in wire
    assert "loadQobuzArtistDetail(" in wire


def test_e2a_wall_handler_remains_e1_album_only():
    source = fn("handleQobuzWallItemClick")

    assert 'type === "album"' in source
    assert "loadQobuzAlbumDetail(" in source
    assert 'type === "artist"' not in source
    assert "loadQobuzArtistDetail(" not in source


def test_e2a_artist_wall_entry_uses_section_callback():
    source = fn("renderQobuzWallSection")

    assert 'result.type === "artist"' in source
    assert 'captureDetailReturnScroll("qobuzsource")' in source
    assert "loadQobuzArtistDetail(" in source



def test_e2a_q10i_supersedes_only_the_historical_favorite_mutation_ban():
    assert '"/qobuz/playlist/create"' in UI
    assert "postCreateQobuzPlaylist" in UI

    assert '"/qobuz/playlist/delete"' in UI
    assert "postDeleteQobuzPlaylist" in UI

    assert '"/qobuz/playlist/remove_tracks"' in UI
    assert "postRemoveTracksFromQobuzPlaylist" in UI

    assert '"/qobuz/playlist/rename"' in UI
    assert "postRenameQobuzPlaylist" in UI

    # Q10I now authorizes exactly the provider-native Favorite set route.
    assert '"/qobuz/favorite/set"' in UI

    # Playback and queue mutation boundaries remain unchanged.
    for forbidden in (
        '"/qobuz/play"',
        '"/qobuz/queue"',
    ):
        assert forbidden not in UI


def test_e2a_centered_existing_controls_are_reused():
    assert ".trackAddBtn" in CSS
    assert ".albumQueueBtn" in CSS
    assert ".artistDiscoSort .artistSortBtn" in CSS
    assert "align-items: center !important;" in CSS
    assert "justify-content: center !important;" in CSS


def test_ui_parses():
    result = subprocess.run(
        ["node", "--check", str(UI_PATH)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr


def test_e2a_nested_album_artist_back_restores_parent_artist_stack():
    source = fn("wireQobuzAlbumArtistClick")

    assert (
        "var parentArtistRestore =\n"
        "        _artistPageRestoreFn;"
        in source
    )

    assert (
        "var restoreAlbum = function() {\n"
        "        _artistPageRestoreFn =\n"
        "            parentArtistRestore;\n"
        "        loadQobuzAlbumDetail("
        in source
    )

    capture_pos = source.index(
        "var parentArtistRestore"
    )

    restore_pos = source.index(
        "_artistPageRestoreFn =\n"
        "            parentArtistRestore;"
    )

    album_load_pos = source.index(
        "loadQobuzAlbumDetail(",
        restore_pos,
    )

    assert capture_pos < restore_pos < album_load_pos
