from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

UI = (
    ROOT / "src" / "ui_web" / "ui.js"
).read_text(encoding="utf-8")

TIDAL = (
    ROOT / "src" / "backend" / "tidal.py"
).read_text(encoding="utf-8")


def function_block(name):
    match = re.search(
        r"^function\s+"
        + re.escape(name)
        + r"\s*\(",
        UI,
        re.M,
    )

    assert match, name

    nxt = re.search(
        r"^function\s+"
        r"[A-Za-z_$][A-Za-z0-9_$]*"
        r"\s*\(",
        UI[match.end():],
        re.M,
    )

    end = (
        match.end() + nxt.start()
        if nxt
        else len(UI)
    )

    return UI[match.start():end]


def test_h4_qobuz_radio_seed_supports_artist_album_track():
    seed = function_block(
        "qobuzRadioSeedNativeId"
    )

    assert 'seedKind === "artist"' in seed
    assert 'seedKind === "album"' in seed
    assert 'seedKind === "track"' in seed

    assert "raw.artist_id" in seed
    assert "raw.album_id" in seed
    assert "raw.provider_track_id" in seed


def test_h4_qobuz_album_radio_uses_existing_native_q7c_operation():
    start = function_block(
        "startQobuzRadioFromSeed"
    )

    assert '"radio_artist"' in start
    assert '"radio_album"' in start
    assert '"radio_track"' in start

    assert '"artist_id"' in start
    assert '"album_id"' in start
    assert '"track_id"' in start

    assert '"/qobuz/catalog?op="' in start


def test_h4_qobuz_radio_context_types_are_provider_specific():
    detail = function_block(
        "showQobuzRadioDetail"
    )

    assert '"qobuz_radio_artist"' in detail
    assert '"qobuz_radio_album"' in detail
    assert '"qobuz_radio_track"' in detail

    assert 'source:\n            "qobuz"' in detail

    assert 'source: "radio"' not in detail
    assert 'context_type: "radio"' not in detail


def test_h4_source01_default_back_target_is_preserved():
    start = function_block(
        "startQobuzRadioFromSeed"
    )

    assert (
        'previousView =\n'
        '        "radio"'
    ) in start

    assert '"qobuzradioorigin"' in start


def test_h4_contextual_radio_has_dedicated_return_route():
    go_back = function_block(
        "goBack"
    )

    assert (
        'previousView === "qobuzradioorigin"'
        in go_back
    )

    assert "_qobuzRadioReturnFn" in go_back


def test_h4_qobuz_artist_has_contextual_start_radio():
    artist = function_block(
        "loadQobuzArtistDetail"
    )

    assert (
        "appendQobuzStartRadioHeaderAction("
        in artist
    )

    assert '"artist"' in artist

    assert (
        "loadQobuzArtistDetail("
        in artist
    )


def test_h4_qobuz_album_has_contextual_start_radio():
    album = function_block(
        "renderQobuzAlbumActions"
    )

    assert (
        "appendQobuzStartRadioHeaderAction("
        in album
    )

    assert '"album"' in album

    assert (
        "loadQobuzAlbumDetail("
        in album
    )


def test_h4_qobuz_track_menu_preserves_existing_actions_and_adds_radio():
    menu = function_block(
        "showQobuzTrackArtworkMenu"
    )

    expected = [
        '"Play Now"',
        '"Play Next"',
        '"Add to Queue"',
        '"Track Details"',
        '"Start Radio"',
    ]

    positions = [
        menu.index(label)
        for label in expected
    ]

    assert positions == sorted(positions)

    assert (
        "startQobuzRadioFromSeed("
        in menu
    )

    assert '"track"' in menu


def test_h4_contextual_actions_do_not_depend_on_source01_visibility_setting():
    names = [
        "appendQobuzStartRadioHeaderAction",
        "renderQobuzAlbumActions",
        "showQobuzTrackArtworkMenu",
        "loadQobuzArtistDetail",
        "startQobuzRadioFromSeed",
    ]

    block = "\n".join(
        function_block(name)
        for name in names
    )

    assert (
        "providerRadioEffectiveVisibility("
        not in block
    )

    assert (
        "providerRadioStoredPreference("
        not in block
    )


def test_h4_contextual_qobuz_radio_never_enters_custom_radio_model():
    names = [
        "appendQobuzStartRadioHeaderAction",
        "startQobuzRadioFromSeed",
        "showQobuzRadioDetail",
    ]

    block = "\n".join(
        function_block(name)
        for name in names
    )

    forbidden = [
        "/api/radio/play/",
        "radio:station:",
        'source: "radio"',
        'context_type: "radio"',
        "RADIO_MODE",
        "playRadioStation(",
        "enhanceRadioShelfOrdering(",
        "set_live_radio_mode",
    ]

    for token in forbidden:
        assert token not in block


def test_h4_uses_existing_icon_button_and_menu_geometry_not_new_text_box():
    header = function_block(
        "appendQobuzStartRadioHeaderAction"
    )

    track_menu = function_block(
        "showQobuzTrackArtworkMenu"
    )

    assert (
        'radioBtn.className =\n'
        '        "albumQueueBtn"'
        in header
    )

    assert (
        '<span class="material-icons">radio</span>'
        in header
    )

    assert (
        'btn.className =\n'
        '            "queuePopoverBtn"'
        in track_menu
    )


def test_h4_does_not_invent_tidal_artist_album_track_radio_backend():
    assert "def get_radio_artist(" not in TIDAL
    assert "def get_radio_album(" not in TIDAL
    assert "def get_radio_track(" not in TIDAL

    tidal_menu = function_block(
        "showTidalTrackArtworkMenu"
    )

    # H4 now exposes contextual Start Radio in the UI while
    # deliberately reusing the existing shared radio route rather
    # than inventing provider-specific backend methods.
    assert '"Start Radio"' in tidal_menu
    assert "startTidalRadioFromSeed(" in tidal_menu
