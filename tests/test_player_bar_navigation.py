import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
HTML = (ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")
BACKEND = (ROOT / "src/main_headless.py").read_text(encoding="utf-8")


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


def test_status_exposes_navigation_ids_from_the_visible_track_context():
    route_start = BACKEND.index('if static_path == "/status":')
    payload_start = BACKEND.index("status_payload = {", route_start)
    payload_end = BACKEND.index("status_payload.update({", payload_start)
    payload = BACKEND[payload_start:payload_end]

    assert '"artist_id":        context_for_status.get("artist_id")' in payload
    assert '"album_id":         context_for_status.get("album_id")' in payload


def test_status_poll_synchronizes_links_after_visible_player_metadata():
    start = UI.index("function pollStatus()")
    end = UI.index("setInterval(pollStatus", start)
    source = UI[start:end]

    visible_artist_update = source.rindex(
        'playerArtist.textContent = s.artist   || "";'
    )
    link_update = source.index("_updatePlayerBarLinks(s);")

    assert link_update > visible_artist_update
    assert source.count("_updatePlayerBarLinks(s);") == 1


def test_album_switch_replaces_or_clears_stale_player_bar_links():
    source = function_source("_updatePlayerBarLinks")
    script = f"""
const events = [];
const playerArtist = {{style: {{}}, title: "", onclick: null}};
const playerTrack = {{style: {{}}, title: "", onclick: null}};
function loadArtistPage(id, name, cover, fromView) {{
    events.push(["artist", id, name, cover, fromView]);
}}
function loadTrackList(context, endpoint, fromView) {{
    events.push(["album", context.id, context.title, endpoint, fromView]);
}}
function openLocalArtistFromPlayerBar(name, cover) {{
    events.push(["local-artist", name, cover]);
}}
{source}

_updatePlayerBarLinks({{
    artist_id: "artist-a",
    artist: "Artist A",
    album_id: "album-a",
    album: "Album A",
    cover: "cover-a"
}});
playerArtist.onclick();
playerTrack.onclick();

_updatePlayerBarLinks({{
    source: "local",
    current_track_id: "local:track-b",
    artist: "Dido",
    album_id: "local-album:still-on-my-mind",
    album: "Still On My Mind",
    cover: "cover-local"
}});
if (playerTrack.onclick !== null) {{
    throw new Error("local track title retained an album navigation handler");
}}
playerArtist.onclick();

_updatePlayerBarLinks({{
    artist_id: "",
    artist: "Artist B",
    album_id: "",
    album: "Album B",
    cover: "cover-b"
}});
if (playerArtist.onclick !== null || playerTrack.onclick !== null) {{
    throw new Error("transitional status retained an old navigation handler");
}}

_updatePlayerBarLinks({{
    artist_id: "artist-b",
    artist: "Artist B",
    album_id: "album-b",
    album: "Album B",
    cover: "cover-b"
}});
playerArtist.onclick();
playerTrack.onclick();
process.stdout.write(JSON.stringify(events));
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [
        ["artist", "artist-a", "Artist A", "cover-a", "home"],
        ["album", "album-a", "Album A", "/tidal/album/album-a", "home"],
        ["local-artist", "Dido", "cover-local"],
        ["artist", "artist-b", "Artist B", "cover-b", "home"],
        ["album", "album-b", "Album B", "/tidal/album/album-b", "home"],
    ]


def test_local_player_bar_artist_uses_the_existing_local_artist_page():
    source = function_source("openLocalArtistFromPlayerBar")
    local_play = function_source("playLocalLibraryTrack")

    assert 'showView("localmusic");' in source
    assert 'setCurrentSourceSection("music");' in source
    assert "renderLocalMusicShell();" in source
    assert 'loadLocalArtist(artist, artistCover || "");' in source
    assert "backBtn.onclick = function() { loadHome(); };" in source
    assert "_updatePlayerBarLinks({" in local_play
    assert 'source: "local"' in local_play


def test_player_navigation_cache_token_is_current():
    assert "/ui_web/ui.js?v=20260812_v1_2_queue_drag2" in HTML
