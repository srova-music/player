from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISPLAY = ROOT / "src" / "ui_web" / "srovacast" / "display.html"


def display_text():
    return DISPLAY.read_text()


def normalize_status_block():
    text = display_text()
    start = text.index("function normalizeStatus(status)")
    end = text.index("\n  function ", start + 1)
    return text[start:end]


def test_q10g_qobuz_has_cast_source_identity():
    block = normalize_status_block()

    assert 'rawSource === "tidal"' in block
    assert '? "TIDAL"' in block

    assert 'rawSource === "qobuz"' in block
    assert '? "QOBUZ"' in block

    assert 'rawSource === "local"' in block
    assert '? "MY MUSIC"' in block


def test_q10g_source_identity_reaches_existing_renderer():
    text = display_text()

    assert "if (state.radioStation)" in text
    assert (
        "radioStation.textContent = state.radioStation;"
        in text
    )
    assert (
        'radioStation.style.display = "block";'
        in text
    )


def test_q10g_does_not_turn_provider_tracks_into_internet_radio():
    block = normalize_status_block()

    assert (
        'status.radio_mode === true ||\n'
        '      rawSource === "radio"'
        in block
    )

    assert 'rawSource === "qobuz"' in block
    assert 'rawSource === "tidal"' in block

    # Provider identity belongs to the source-label branch only.
    radio_definition = block[
        block.index("const radio ="):
        block.index("const radioMetadata")
    ]

    assert '"qobuz"' not in radio_definition
    assert '"tidal"' not in radio_definition
