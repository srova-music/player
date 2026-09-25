from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")


def fn(name):
    m = re.search(r"\bfunction\s+" + re.escape(name) + r"\s*\(", UI)
    assert m, name
    brace = UI.find("{", m.start())
    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    i = brace

    while i < len(UI):
        ch = UI[i]
        nx = UI[i + 1] if i + 1 < len(UI) else ""

        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue

        if block_comment:
            if ch == "*" and nx == "/":
                block_comment = False
                i += 2
                continue
            i += 1
            continue

        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch == "/" and nx == "/":
            line_comment = True
            i += 2
            continue

        if ch == "/" and nx == "*":
            block_comment = True
            i += 2
            continue

        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return UI[m.start():i + 1]

        i += 1

    raise AssertionError(name)


def node(source):
    p = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert p.returncode == 0, p.stderr


def test_e1_album_wall_navigation_only():
    src = fn("handleQobuzWallItemClick")

    # E1 Album navigation remains locked.
    assert 'type === "album"' in src
    assert "loadQobuzAlbumDetail(" in src

    # Q7E-E3 later authorizes Track-card action-menu dispatch.
    assert 'type === "track"' in src
    assert "showQobuzTrackArtworkMenu(" in src
    assert "loadQobuzTrackDetail(" not in src

    # Track Detail remains reachable from the E3 menu.
    menu = fn("showQobuzTrackArtworkMenu")
    assert "loadQobuzTrackDetail(" in menu

    # Artist navigation remains owned by the section callback.
    assert "loadQobuzArtistDetail(" not in src
    assert "loadTrackList(" not in src


def test_e1_album_uses_locked_q7c_adapter():
    src = fn("loadQobuzAlbumDetail")
    assert '"/qobuz/catalog?op=album&album_id="' in src
    assert 'String(album.source || "") !== "qobuz"' in src
    assert 'setAlbumViewKind("qobuz-album")' in src

    for forbidden in (
        "op=track",
        "op=artist_page",
        "op=search_",
        "op=playlists",
        "/qobuz/login",
        "/qobuz/logout",
    ):
        assert forbidden not in src


def test_e1_payload_preserves_provider_identity():
    payload = fn("qobuzAlbumTrackPayload")

    node(
        """
const assert = require("assert");
var SROVA_STANDBY_ART = "standby.png";
"""
        + payload
        + """
const out = qobuzAlbumTrackPayload({
    id: "qobuz:404287984",
    provider_track_id: "404287984",
    source: "qobuz",
    title: "Track",
    artist: "Artist",
    artwork_url: "art.jpg",
    duration: 123
}, {});

assert.strictEqual(out.id, "qobuz:404287984");
assert.strictEqual(out.provider_track_id, "404287984");
assert.strictEqual(out.source, "qobuz");
"""
    )


def test_e1_playback_uses_q5_shared_replace_route():
    src = fn("qobuzPlayAlbumTracks")
    assert "postTidalQueueReplace({" in src
    assert 'context_type: "album"' in src
    assert "qobuzAlbumTrackPayload(" in src
    assert "/qobuz/test-play" not in src
    assert "/qobuz/play" not in src


def test_e1_add_to_queue_uses_existing_shared_popover():
    rows = fn("renderQobuzAlbumTracks")
    actions = fn("renderQobuzAlbumActions")

    assert "showQueuePopover(add, [payload], e)" in rows
    assert "showQueuePopover(" in actions


def test_e1_q10i_qobuz_album_favorites_remain_provider_aware():
    rows = fn("renderQobuzAlbumTracks")
    actions = fn("renderQobuzAlbumActions")
    loader = fn("loadQobuzAlbumDetail")

    assert "appendQobuzTrackFavoriteHeart(" in rows
    assert "makeQobuzFavoriteHeart(" in actions

    # Q10I supersedes the old no-Favorite rule, but these Qobuz
    # renderers must still never dispatch through TIDAL mutation.
    for source in (
        rows,
        actions,
        loader,
    ):
        assert "toggleTrackFavorite" not in source
        assert "toggleAlbumFavorite" not in source
        assert '"/tidal/favorite/' not in source


def test_e1_shared_popover_blocks_tidal_playlist_action_for_qobuz():
    src = fn("showQueuePopover")
    assert "hasQobuzTracks" in src
    assert "(hasLocalTracks || hasQobuzTracks)" in src
    assert "showAddToTidalPlaylistModal" in src


def test_e1_tidal_shared_detail_functions_not_rewritten():
    # E1 deliberately avoids extending these historical TIDAL/detail paths.
    for name in (
        "buildTrackPayload",
        "renderTrackList",
        "renderAlbumQueueBtn",
        "playTrack",
        "loadTrackList",
    ):
        assert fn(name)


def test_e1_icon_controls_use_existing_album_geometry():
    src = fn("renderQobuzAlbumActions")
    assert src.count('className = "albumQueueBtn"') == 2
    assert 'aria-label", "Play Album"' in src
    assert 'aria-label", "Add album to queue"' in src



def test_e1_q8f_authorizes_qobuz_playlist_rename_but_search_remains_bounded():
    assert "/qobuz/playlist/create" in UI
    assert "postCreateQobuzPlaylist" in UI

    assert "/qobuz/playlist/delete" in UI
    assert "postDeleteQobuzPlaylist" in UI

    assert "/qobuz/playlist/remove_tracks" in UI
    assert "postRemoveTracksFromQobuzPlaylist" in UI

    assert "/qobuz/playlist/rename" in UI
    assert "postRenameQobuzPlaylist" in UI

    assert "searchQobuz" not in UI
