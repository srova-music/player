from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "src/ui_web/ui.js"
CSS_PATH = ROOT / "src/ui_web/srova.css"

UI = UI_PATH.read_text(encoding="utf-8")
CSS = CSS_PATH.read_text(encoding="utf-8")


def fn(name):
    pattern = re.compile(
        r"(?m)^function\s+" +
        re.escape(name) +
        r"\s*\("
    )

    match = pattern.search(UI)
    assert match, name

    start = match.start()

    brace = UI.find("{", match.end())
    assert brace >= 0, name

    depth = 0
    i = brace

    in_string = None
    escaped = False

    while i < len(UI):
        c = UI[i]

        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == in_string:
                in_string = None

            i += 1
            continue

        if c in ('"', "'", "`"):
            in_string = c
            i += 1
            continue

        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1

            if depth == 0:
                return UI[start:i + 1]

        i += 1

    raise AssertionError(name)


def node(source):
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr


def test_e3_reuses_locked_shared_track_detail_geometry():
    source = fn("setAlbumViewKind")

    assert 'kind === "qobuz-track"' in source
    assert 'albumView.classList.add("tidalTrackDetail")' in source
    assert 'sourceLabel = "QOBUZ"' in source

    # No new CSS family is required: use the established responsive
    # shared detail geometry.
    assert "tidalTrackDetail" in CSS


def test_e3_wall_track_uses_action_menu_before_detail():
    source = fn("handleQobuzWallItemClick")

    assert 'type === "track"' in source
    assert "showQobuzTrackArtworkMenu(" in source
    assert "loadQobuzTrackDetail(" not in source
    assert "playTrackDirect(" not in source

    menu = fn("showQobuzTrackArtworkMenu")

    for label in (
        '"Play Now"',
        '"Play Next"',
        '"Add to Queue"',
        '"Track Details"',
    ):
        assert label in menu

    assert "loadQobuzTrackDetail(" in menu
    assert "showAddToTidalPlaylistModal" not in menu
    assert "/qobuz/playlist/" not in menu


def test_e3_loader_uses_existing_q7c_single_track_adapter():
    source = fn("loadQobuzTrackDetail")

    assert (
        '"/qobuz/catalog?op=track&track_id="'
        in source
    )

    assert (
        'currentViewEndpoint =\n'
        '        "qobuz:track:" + nativeId'
        in source
    )

    assert 'setAlbumViewKind("qobuz-track")' in source

    for forbidden in (
        "/qobuz/play",
        "/qobuz/queue",
        "op=search_",
        "op=radio_",
        "/qobuz/playlist/",
        "/qobuz/login",
        "/qobuz/logout",
    ):
        assert forbidden not in source


def test_e3_loader_fails_closed_on_provider_identity():
    source = fn("loadQobuzTrackDetail")

    assert 'String(track.source || "") !==\n                "qobuz"' in source
    assert "track.provider_track_id" in source
    assert '"qobuz:" + nativeId' in source
    assert "qobuzAlbumTrackPayload(" in source


def test_e3_single_track_view_preserves_canonical_identity():
    payload = fn("qobuzAlbumTrackPayload")

    node(
        """
const assert = require("assert");
var SROVA_STANDBY_ART = "standby.png";
"""
        + payload
        + """
const out = qobuzAlbumTrackPayload({
    id: "qobuz:161150239",
    provider_track_id: "161150239",
    source: "qobuz",
    title: "Sultans Of Swing",
    artist: "Dire Straits",
    artwork_url: "cover.jpg",
    duration: 350
}, {});

assert.strictEqual(
    out.id,
    "qobuz:161150239"
);
assert.strictEqual(
    out.provider_track_id,
    "161150239"
);
assert.strictEqual(
    out.source,
    "qobuz"
);
"""
    )


def test_e3_uses_single_track_as_shared_view_queue():
    source = fn("loadQobuzTrackDetail")

    assert "originalTracks = [\n            detailTrack\n        ]" in source
    assert "currentViewTracks =\n            originalTracks" in source
    assert "renderTrackList(" in source


def test_e3_qobuz_track_does_not_expose_tidal_favorite():
    source = fn("renderTrackList")

    assert "qobuzReadOnlyTrack" in source
    assert 'indexOf("qobuz:track:") === 0' in source
    assert "qobuzReadOnlyDetail" in source

    # Preserve the exact locked Q7F-F2 playlist guard and add the
    # standalone-track exclusion inside it.
    assert "if (!qobuzReadOnlyPlaylist)" in source
    assert "if (!qobuzReadOnlyTrack)" in source


def test_e3_playback_uses_existing_q5_shared_replace_path():
    source = fn("playTrack")

    assert 'indexOf("qobuz:track:") === 0' in source
    assert 'ctxType = "track"' in source
    assert "postTidalQueueReplace({" in source

    assert "/qobuz/play" not in source
    assert "/qobuz/queue" not in source


def test_e3_header_action_reuses_existing_centered_icon_control():
    loader = fn("loadQobuzTrackDetail")
    queue = fn("renderAlbumQueueBtn")

    assert "renderAlbumQueueBtn(" in loader
    assert 'className = "albumQueueBtn"' in queue

    # Existing locked geometry already centers icon buttons.
    assert ".albumQueueBtn" in CSS
    assert ".trackAddBtn" in CSS


def test_e3_does_not_begin_q7g_or_other_deferred_scope():
    changed_contract = (
        fn("loadQobuzTrackDetail") +
        fn("handleQobuzWallItemClick")
    )

    for forbidden in (
        "searchQobuz",
        "radio_track",
        "radio_album",
        "radio_artist",
        "Infinite Play",
        "Auto Mix",
        "Cast",
        "Settings",
    ):
        assert forbidden not in changed_contract


def test_e3_ui_parses():
    result = subprocess.run(
        ["node", "--check", str(UI_PATH)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr

def test_e3_qobuz_wall_menu_uses_shared_provider_aware_queue():
    payload = fn("buildQobuzWallTrackPayload")
    play_now = fn("playQobuzWallTrackNow")
    menu = fn("showQobuzTrackArtworkMenu")

    assert 'source: "qobuz"' in payload
    assert '"qobuz:" + providerTrackId' in payload
    assert "provider_track_id:" in payload

    assert "postTidalQueueReplace({" in play_now
    assert 'context_type: "track"' in play_now
    assert 'context_id: track.id' in play_now

    assert 'submitQueueTracks(\n                payload,\n                "next"' in menu
    assert 'submitQueueTracks(\n                payload,\n                "queue"' in menu

    for forbidden in (
        "/qobuz/play",
        "/qobuz/queue",
        "/qobuz/playlist/add_tracks",
        "/qobuz/playlist/remove_tracks",
        "showAddToTidalPlaylistModal",
    ):
        assert forbidden not in menu


def test_e3_qobuz_quality_classifier_drives_existing_data_q():
    quality = fn("qobuzWallQualityLabel")
    section = fn("buildScrollSection")

    node(
        """
const assert = require("assert");
"""
        + quality
        + """
assert.strictEqual(
    qobuzWallQualityLabel({
        quality: {
            hires: true,
            hires_streamable: true,
            maximum_bit_depth: 24,
            maximum_sampling_rate_khz: 96
        }
    }),
    "HI-RES"
);

assert.strictEqual(
    qobuzWallQualityLabel({
        quality: {
            hires: false,
            hires_streamable: false,
            maximum_bit_depth: 16,
            maximum_sampling_rate_khz: 44.1
        }
    }),
    "CD"
);
"""
    )

    assert "item.quality" in section
    assert 'card.setAttribute("data-q", q)' in section


def test_e3_qobuz_wall_caption_colours_match_local_music_logic():
    assert (
        '#homeView .srovaQobuzSourcePage\n'
        '    .album[data-q="cd"] .album-title'
        in CSS
    )
    assert (
        "color: rgba(0, 191, 255, 0.74) !important;"
        in CSS
    )
    assert (
        "color: rgba(0, 191, 255, 0.58) !important;"
        in CSS
    )

    assert (
        '#homeView .srovaQobuzSourcePage\n'
        '    .album[data-q="hires"] .album-title'
        in CSS
    )
    assert (
        "color: rgba(201, 168, 76, 0.84) !important;"
        in CSS
    )
    assert (
        "color: rgba(201, 168, 76, 0.64) !important;"
        in CSS
    )
