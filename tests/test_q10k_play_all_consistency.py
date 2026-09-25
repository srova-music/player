from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]

UI_PATH = (
    ROOT /
    "src" /
    "ui_web" /
    "ui.js"
)

UI = UI_PATH.read_text(
    encoding="utf-8"
)


def fn(name):
    match = re.search(
        r"(?m)^function\s+"
        + re.escape(name)
        + r"\s*\(",
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
            if (
                char == "*"
                and nxt == "/"
            ):
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

        if (
            char == "/"
            and nxt == "/"
        ):
            line_comment = True
            pos += 2
            continue

        if (
            char == "/"
            and nxt == "*"
        ):
            block_comment = True
            pos += 2
            continue

        if char in (
            "'",
            '"',
            "`",
        ):
            quote = char
            pos += 1
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1

            if depth == 0:
                return UI[
                    match.start():
                    pos + 1
                ]

        pos += 1

    raise AssertionError(name)


def test_q10k_generic_finite_header_has_play_all():
    source = fn(
        "renderAlbumQueueBtn"
    )

    assert (
        "playFiniteCollectionFromHeader("
        in source
    )

    assert (
        'playAllBtn.className =\n'
        '            "albumQueueBtn";'
        in source
    )

    assert (
        'playAllBtn.title =\n'
        '            "Play All";'
        in source
    )

    assert (
        '"aria-label",\n'
        '            "Play All"'
        in source
    )

    assert (
        "play_arrow"
        in source
    )


def test_q10k_generic_play_reuses_existing_context_queue():
    helper = fn(
        "playFiniteCollectionFromHeader"
    )

    row_play = fn(
        "playTrack"
    )

    assert (
        "playTrack("
        in helper
    )

    assert (
        "postTidalQueueReplace("
        in row_play
    )

    assert (
        "currentViewTracks"
        in row_play
    )

    # Q10K adds no parallel queue implementation.
    assert (
        "postTidalQueueReplace("
        not in helper
    )


def test_q10k_qobuz_artist_uses_top_tracks_provider_path():
    helper = fn(
        "playFiniteCollectionFromHeader"
    )

    qobuz_loader = fn(
        "loadQobuzArtistDetail"
    )

    artist_renderer = fn(
        "_renderArtistPage"
    )

    artist_play = fn(
        "_playArtistTopTrack"
    )

    assert (
        '"qobuz:artist:"'
        in helper
    )

    assert (
        "_playArtistTopTrack("
        in helper
    )

    assert (
        "page.top_tracks"
        in qobuz_loader
    )

    assert (
        "_renderArtistPage("
        in qobuz_loader
    )

    assert (
        "renderAlbumQueueBtn("
        in artist_renderer
    )

    assert (
        "renderAlbumQueueBtn(tracks, artistCover)"
        in artist_renderer
    )

    # Header Play All and row-one playback must share the
    # dedicated artist Top Tracks path for both providers.
    assert (
        '"/tidal/artist/"'
        in helper
    )

    assert (
        '"qobuz:artist:"'
        in helper
    )

    assert (
        "_playArtistTopTrack("
        in helper
    )

    assert (
        "postTidalQueueReplace("
        in artist_play
    )

    assert (
        'context_type:  "artist"'
        in artist_play
    )


def test_q10k_artist_play_all_does_not_flatten_discography():
    renderer = fn(
        "_renderArtistPage"
    )

    assert (
        '"Top Tracks"'
        in renderer
    )

    assert (
        "_rerenderDiscography("
        in renderer
    )

    assert (
        "renderAlbumQueueBtn("
        in renderer
    )

    assert (
        "renderAlbumQueueBtn(tracks, artistCover)"
        in renderer
    )


def test_q10k_tidal_provider_radio_has_play_all_only_header():
    source = fn(
        "startTidalRadioFromSeed"
    )

    assert (
        "renderProviderRadioPlayAllBtn("
        in source
    )

    assert (
        "data.tracks"
        in source
    )

    assert (
        "playTrack("
        in source
    )

    # Provider Radio remains finite-track TIDAL,
    # never the custom Internet-Radio model.
    for forbidden in (
        "/api/radio/play/",
        "radio:station:",
        "playRadioStation(",
        "RADIO_MODE",
    ):
        assert forbidden not in source


def test_q10k_qobuz_provider_radio_has_play_all_only_header():
    renderer = fn(
        "renderQobuzRadioTracks"
    )

    playback = fn(
        "playQobuzRadioTracks"
    )

    assert (
        "renderProviderRadioPlayAllBtn("
        in renderer
    )

    assert (
        "playQobuzRadioTracks("
        in renderer
    )

    assert (
        "postTidalQueueReplace("
        in playback
    )

    assert (
        "qobuzRadioTrackPayloads("
        in playback
    )


def test_q10k_radio_header_helper_is_compact_play_and_queue():
    source = fn(
        "renderProviderRadioPlayAllBtn"
    )

    assert (
        '"Play All"'
        in source
    )

    assert (
        "play_arrow"
        in source
    )

    assert (
        '"Add to queue"'
        in source
    )

    assert (
        "playlist_add"
        in source
    )

    assert (
        "showQueuePopover("
        in source
    )

    # Provider Radio remains a compact finite-collection header:
    # no Shuffle, custom Internet Radio route, or direct queue-submit
    # implementation is introduced here.
    for forbidden in (
        "submitQueueTracks(",
        "shuffle",
        "playRadioStation(",
        "/api/radio/",
    ):
        assert forbidden not in source




def test_q10k_existing_qobuz_album_play_contract_unchanged():
    actions = fn(
        "renderQobuzAlbumActions"
    )

    playback = fn(
        "qobuzPlayAlbumTracks"
    )

    assert (
        '"Play Album"'
        in actions
    )

    assert (
        "qobuzPlayAlbumTracks("
        in actions
    )

    assert (
        "postTidalQueueReplace("
        in playback
    )

    assert (
        'context_type: "album"'
        in playback
    )


def test_q10k_existing_local_album_play_contract_unchanged():
    source = fn(
        "renderLocalAlbumPlayBtn"
    )

    assert (
        '"Play Album"'
        in source
    )

    assert (
        "playLocalLibraryTrack("
        in source
    )

    assert (
        "tracks[0]"
        in source
    )


def test_q10k_shuffle_is_not_added_to_collection_headers():
    generic = fn(
        "renderAlbumQueueBtn"
    )

    radio = fn(
        "renderProviderRadioPlayAllBtn"
    )

    assert (
        "shuffle"
        not in generic.lower()
    )

    assert (
        "shuffle"
        not in radio.lower()
    )


def test_q10k_ui_parses():
    result = subprocess.run(
        [
            "node",
            "--check",
            str(UI_PATH),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert (
        result.returncode == 0
    ), result.stderr


def test_q10k_provider_radio_header_has_add_to_queue_parity():
    helper = fn(
        "renderProviderRadioPlayAllBtn"
    )

    tidal = fn(
        "startTidalRadioFromSeed"
    )

    qobuz = fn(
        "renderQobuzRadioTracks"
    )

    assert "play_arrow" in helper
    assert "playlist_add" in helper
    assert '"Add to queue"' in helper
    assert "showQueuePopover(" in helper

    assert (
        "data.tracks.map("
        in tidal
    )
    assert (
        "buildTrackPayload("
        in tidal
    )

    assert (
        "qobuzRadioTrackPayloads("
        in qobuz
    )
    assert (
        "playQobuzRadioTracks("
        in qobuz
    )
