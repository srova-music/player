from hashlib import sha256
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

DISPLAY_PATH = (
    ROOT /
    "src" /
    "ui_web" /
    "srovacast" /
    "display.html"
)

FONT_PATH = (
    ROOT /
    "src" /
    "ui_web" /
    "srovacast" /
    "fonts" /
    "SROVAClock-Regular.woff2"
)

DISPLAY = DISPLAY_PATH.read_text(
    encoding="utf-8"
)

EXPECTED_FONT_SHA256 = (
    "b9a64c5817b3d3b18c552c95f81daf0"
    "f6dec0c45ab10b7d9879ba6c8460117f1"
)


def test_exact_accepted_v1_105_clock_font_is_embedded():
    assert FONT_PATH.is_file()

    actual = sha256(
        FONT_PATH.read_bytes()
    ).hexdigest()

    assert actual == EXPECTED_FONT_SHA256

    assert (
        'url("fonts/SROVAClock-Regular.woff2") '
        'format("woff2")'
        in DISPLAY
    )


def test_clock_is_cast_display_only_and_lives_in_details_header():
    assert DISPLAY.count(
        'id="srovacastHeaderClock"'
    ) == 1

    details = re.search(
        r'<section class="details">(.*?)'
        r'<div class="heading">NOW PLAYING</div>',
        DISPLAY,
        flags=re.S,
    )

    assert details is not None

    assert (
        'id="srovacastHeaderClock"'
        in details.group(1)
    )


def test_clock_uses_24_hour_hours_and_minutes_only():
    block = DISPLAY.split(
        "function paintHeaderClock() {",
        1,
    )[1].split(
        "function scheduleHeaderClockTick() {",
        1,
    )[0]

    assert "now.getHours()" in block
    assert "now.getMinutes()" in block
    assert "getSeconds" not in block
    assert "toLocaleTimeString" not in block
    assert "`${hours}:${minutes}`" in block


def test_clock_uses_one_minute_aligned_local_timer():
    block = DISPLAY.split(
        "function scheduleHeaderClockTick() {",
        1,
    )[1].split(
        "function postPlaybackState(state) {",
        1,
    )[0]

    assert "paintHeaderClock();" in block
    assert "60000 -" in block
    assert "(Date.now() % 60000)" in block
    assert "window.setTimeout(" in block
    assert "fetch(" not in block


def test_existing_cast_status_poll_contract_is_unchanged():
    assert DISPLAY.count(
        "`/status?_=${Date.now()}`"
    ) == 1

    assert DISPLAY.count(
        "window.setInterval(refresh, 3000)"
    ) == 1


def test_existing_presentation_contract_is_unchanged():
    assert (
        "const PRESENTATION_FADE_MS = 120;"
        in DISPLAY
    )

    assert (
        "const INACTIVE_PRESENTATION_HOLD_MS = 30000;"
        in DISPLAY
    )

    assert (
        "SROVACAST_PRESENTATION_AUTHORITY_V1"
        in DISPLAY
    )

    assert (
        'heading.textContent = "READY";'
        in DISPLAY
    )

    assert (
        'heading.textContent = "NOW PLAYING";'
        in DISPLAY
    )


def test_clock_is_presentation_independent():
    render = DISPLAY.split(
        "function render(",
        1,
    )[1]

    assert "srovacastHeaderClock" not in render
    assert "paintHeaderClock" not in render
    assert "scheduleHeaderClockTick" not in render
