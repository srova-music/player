from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

UI = (
    ROOT / "src/ui_web/ui.js"
).read_text(encoding="utf-8")

CSS = (
    ROOT / "src/ui_web/srova.css"
).read_text(encoding="utf-8")


def function_slice(name: str) -> str:
    marker = f"function {name}("
    start = UI.index(marker)

    next_fn = UI.find(
        "\nfunction ",
        start + len(marker),
    )

    if next_fn < 0:
        return UI[start:]

    return UI[start:next_fn]


def radio_css_slice() -> str:
    marker = (
        "Q7H H4 PROVIDER RADIO MOBILE "
        "PORTRAIT BACK UPPER RIGHT"
    )

    start = CSS.index(marker)

    next_section = CSS.find(
        "/* ================================================================",
        start + len(marker),
    )

    if next_section < 0:
        return CSS[start:]

    return CSS[start:next_section]


def test_detail_kind_clears_provider_radio_marker():
    body = function_slice(
        "setAlbumViewKind"
    )

    assert (
        'classList.remove("providerRadioDetail")'
        in body
    )

    assert (
        "tidalWallMixTopRightBack"
        not in body
    )


def test_qobuz_radio_detail_gets_provider_marker():
    body = function_slice(
        "startQobuzRadioFromSeed"
    )

    assert (
        'setAlbumViewKind("tidal-detail")'
        in body
        or
        'setAlbumViewKind(\n        "tidal-detail"\n    );'
        in body
    )

    assert (
        '"providerRadioDetail"'
        in body
    )


def test_tidal_source01_radio_gets_provider_marker():
    body = function_slice(
        "loadTrackList"
    )

    assert (
        '"/tidal/mix/"'
        in body
    )

    assert (
        'fromView === "radio"'
        in body
    )

    assert (
        '"providerRadioDetail"'
        in body
    )


def test_ordinary_tidal_wall_mix_has_no_h4_special_case():
    body = function_slice(
        "loadTrackList"
    )

    assert (
        "tidalWallMixTopRightBack"
        not in body
    )

    assert (
        "tidalWallMixTopRightBack"
        not in UI
    )

    assert (
        "tidalWallMixTopRightBack"
        not in CSS
    )


def test_radio_back_css_is_mobile_portrait_only():
    block = radio_css_slice()

    assert (
        "(max-width: 640px)"
        in block
    )

    assert (
        "(orientation: portrait)"
        in block
    )

    assert (
        "#albumView.tidalTrackDetail.providerRadioDetail"
        in block
    )

    assert (
        "#albumHeader > #backBtn"
        in block
    )

    assert (
        "position: absolute !important;"
        in block
    )

    assert (
        "top: 16px !important;"
        in block
    )

    assert (
        "right: 14px !important;"
        in block
    )


def test_mobile_radio_grid_reclaims_old_back_cell():
    block = radio_css_slice()

    assert (
        '"art . actions"'
        in block
    )

    assert (
        '"art . actions back"'
        not in block
    )


def test_radio_back_section_does_not_target_other_details():
    block = radio_css_slice()

    for selector in (
        "tidalAlbumDetail",
        "tidalArtistDetail",
        "tidalFeaturedTrackList",
        "localAlbumDetail",
    ):
        assert selector not in block


def test_no_out_of_scope_radio_presentation_expansion():
    assert (
        "decorateProviderRadioShelfPresentation"
        not in UI
    )

    assert (
        "enrichQobuzRadioArtistArtwork"
        not in UI
    )

    assert (
        "providerRadioArtworkRow"
        not in UI
    )

    assert (
        "Q7H H4 PROVIDER RADIO SHARED "
        "ARTWORK PRESENTATION"
        not in CSS
    )
