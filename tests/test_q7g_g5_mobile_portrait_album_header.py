from pathlib import Path


CSS_PATH = Path("src/ui_web/srova.css")
UI_PATH = Path("src/ui_web/ui.js")

CSS = CSS_PATH.read_text(encoding="utf-8")
UI = UI_PATH.read_text(encoding="utf-8")

MARKER = "Q7G G5 -- MOBILE PORTRAIT ALBUM BACK UPPER RIGHT"


def g5_block():
    start = CSS.index(MARKER)
    return CSS[start:]


def test_g5_override_is_final_and_mobile_portrait_only():
    block = g5_block()

    assert CSS.index(MARKER) > CSS.index(
        "RC3 POINT 6 TIDAL MOBILE PORTRAIT RIGHT ALIGNED CONTROLS"
    )

    assert CSS.index(MARKER) > CSS.index(
        "RC3 POINT 6 MY MUSIC LOCAL ALBUM BACK CONTROL"
    )

    assert "(max-width: 640px)" in block
    assert "(orientation: portrait)" in block


def test_g5_targets_album_views_only():
    block = g5_block()

    assert "#albumView.localAlbumDetail #albumHeader" in block
    assert "#albumView.tidalAlbumDetail #albumHeader" in block

    # Do not broaden G5 to the shared playlist/mix track-detail class.
    assert "#albumView.tidalTrackDetail" not in block

    # Do not alter artist or featured-track layouts.
    assert "#albumView.tidalArtistDetail" not in block
    assert "#albumView.tidalFeaturedTrackList" not in block


def test_g5_qobuz_album_coverage_comes_from_existing_shared_album_class():
    assert (
        'if (kind === "tidal-album" || kind === "qobuz-album") {'
        in UI
    )

    assert (
        'albumView.classList.add("tidalAlbumDetail");'
        in UI
    )


def test_g5_mobile_portrait_removes_back_from_bottom_grid_row():
    block = g5_block()

    assert '"info info info"' in block
    assert '"art . actions"' in block

    assert '"art . actions back"' not in block
    assert '"art actions back ."' not in block


def test_g5_back_is_absolute_upper_right():
    block = g5_block()

    assert "#albumHeader > #backBtn" in block
    assert "position: absolute !important;" in block
    assert "top: 16px !important;" in block
    assert "right: 14px !important;" in block
    assert "bottom: auto !important;" in block
    assert "left: auto !important;" in block


def test_g5_remaining_album_actions_are_right_aligned():
    block = g5_block()

    assert "#albumQueueBtnGroup" in block
    assert "grid-area: actions !important;" in block
    assert "justify-self: end !important;" in block
    assert "justify-content: flex-end !important;" in block


def test_g5_reserves_upper_right_space_for_back_control():
    block = g5_block()

    assert "#albumHeader > div:not(#albumQueueBtnGroup)" in block
    assert "padding-right: 48px !important;" in block
