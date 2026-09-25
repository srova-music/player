from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CSS_PATH = ROOT / "src" / "ui_web" / "srova.css"
INDEX_PATH = ROOT / "src" / "ui_web" / "index.html"
UI_PATH = ROOT / "src" / "ui_web" / "ui.js"

CSS = CSS_PATH.read_text(encoding="utf-8")
INDEX = INDEX_PATH.read_text(encoding="utf-8")
UI = UI_PATH.read_text(encoding="utf-8")

MARKER = (
    "Q10H MOBILE PORTRAIT BACK-ARROW PARITY -- 150926"
)

TARGET = (
    "#albumView.tidalTrackDetail"
    ":not(.tidalAlbumDetail)"
    ":not(.providerRadioDetail)"
)


def q10h_block():
    start = CSS.index(MARKER)
    return CSS[start:]


def test_q10h_is_mobile_portrait_only():
    block = q10h_block()

    assert "(max-width: 640px)" in block
    assert "(orientation: portrait)" in block
    assert TARGET in block


def test_q10h_removes_back_from_lower_grid_row():
    block = q10h_block()

    assert (
        'grid-template-areas:\n'
        '            "info info info"\n'
        '            "art . actions" !important;'
    ) in block

    assert '"art . actions back"' not in block


def test_q10h_back_is_absolute_upper_right():
    block = q10h_block()

    assert "#albumHeader > #backBtn" in block
    assert "position: absolute !important;" in block
    assert "top: 16px !important;" in block
    assert "right: 14px !important;" in block
    assert "bottom: auto !important;" in block
    assert "left: auto !important;" in block


def test_q10h_reserves_title_space_for_back():
    block = q10h_block()

    assert (
        "#albumHeader > div:not(#albumQueueBtnGroup)"
        in block
    )

    assert "padding-right: 48px !important;" in block
    assert "box-sizing: border-box !important;" in block


def test_q10h_excludes_existing_album_and_radio_reference_views():
    block = q10h_block()

    assert ":not(.tidalAlbumDetail)" in block
    assert ":not(.providerRadioDetail)" in block

    assert (
        "#albumView.tidalTrackDetail.providerRadioDetail"
        in CSS
    )

    assert (
        "#albumView.tidalAlbumDetail #albumHeader > #backBtn"
        in CSS
    )


def test_q10h_does_not_target_other_back_controls():
    block = q10h_block()

    unrelated = (
        ".queueBackBtn",
        ".settingsBackBtn",
        ".libraryBackBtn",
        ".srovaSourceBack",
        ".tidalArtistDetail",
        ".tidalFeaturedTrackList",
    )

    for selector in unrelated:
        assert selector not in block


def test_shared_back_handler_is_unchanged():
    assert (
        '<button id="backBtn" onclick="goBack()">'
        in INDEX
    )

    assert "function goBack()" in UI


def test_q10h_css_cache_buster_present():
    # Q10I later extends the Q10H CSS cache key for persistent
    # touch-visible Favorite Hearts. The Q10H base token and all
    # Back-arrow presentation contracts remain protected.
    expected = (
        "/ui_web/srova.css?"
        "v=20260914_v2_0_q10d_auth_ux_css2_"
        "q10f_provider_aware_go_to_album_css3_"
        "q10h_mobile_back_arrow_css1_"
        "q10i_20260915_favorites_always_visible_css2_"
        "q10i_artist_top_track_heart_layout_css3_q10i_hover_parity_css4_q10i_artist_add_footer_css5_q10i_artist_list_isolation_css6_q10i_search_favorites_css7_q10i_search_favorite_gold_css8_q10i_search_layout_parity_css9"
    )

    assert expected in INDEX
