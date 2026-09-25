from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

UI_PATH = ROOT / "src/ui_web/ui.js"
CSS_PATH = ROOT / "src/ui_web/srova.css"

UI = UI_PATH.read_text(encoding="utf-8")
CSS = CSS_PATH.read_text(encoding="utf-8")


def fn(name):
    match = re.search(
        r"\bfunction\s+"
        + re.escape(name)
        + r"\s*\(",
        UI,
    )

    assert match, name

    brace = UI.find("{", match.start())

    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    pos = brace

    while pos < len(UI):
        char = UI[pos]
        nxt = UI[pos + 1] if pos + 1 < len(UI) else ""

        if line_comment:
            if char == "\n":
                line_comment = False
            pos += 1
            continue

        if block_comment:
            if char == "*" and nxt == "/":
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

        if char == "/" and nxt == "/":
            line_comment = True
            pos += 2
            continue

        if char == "/" and nxt == "*":
            block_comment = True
            pos += 2
            continue

        if char in ("'", '"', "`"):
            quote = char
            pos += 1
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return UI[match.start():pos + 1]

        pos += 1

    raise AssertionError(name)


def node(source):
    proc = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert proc.returncode == 0, proc.stderr


def test_streaming_album_stats_matches_local_style():
    source = fn("streamingAlbumStatsText")

    node(
        """
const assert = require("assert");
function formatDuration(v) {
    return Math.floor(v / 60) + "m";
}
"""
        + source
        + """
assert.strictEqual(
    streamingAlbumStatsText([
        {duration: 120},
        {duration: 180}
    ]),
    "2 tracks · 5m"
);
"""
    )


def test_qobuz_catalog_hires_is_gold_class():
    source = fn("qobuzAlbumCatalogTech")

    node(
        """
const assert = require("assert");
"""
        + source
        + """
const out = qobuzAlbumCatalogTech({
    quality: {
        maximum_bit_depth: 24,
        maximum_sampling_rate_khz: 96
    }
});

assert.strictEqual(
    out.text,
    "24-bit · 96 kHz"
);

assert.ok(
    out.className.includes(
        "qobuzAlbumTechInfoHiRes"
    )
);
"""
    )


def test_qobuz_catalog_cd_is_cyan_class():
    source = fn("qobuzAlbumCatalogTech")

    node(
        """
const assert = require("assert");
"""
        + source
        + """
const out = qobuzAlbumCatalogTech({
    quality: {
        maximum_bit_depth: 16,
        maximum_sampling_rate_khz: 44.1
    }
});

assert.strictEqual(
    out.text,
    "16-bit · 44.1 kHz"
);

assert.ok(
    out.className.includes(
        "qobuzAlbumTechInfoCd"
    )
);
"""
    )


def test_qobuz_album_header_uses_four_line_local_hierarchy():
    source = fn("loadQobuzAlbumDetail")

    assert "currentContext.artist" in source
    assert "qobuzAlbumCatalogTech(album)" in source
    assert "streamingAlbumStatsText(tracks)" in source
    assert '"streamingAlbumStatsLine"' in source

    assert "qobuzAlbumMeta(" not in source


def test_tidal_album_header_uses_artist_and_stats_not_provider_label():
    source = fn("loadTrackList")

    assert "var isTidalAlbum" in source
    assert "streamingAlbumStatsText(tracks)" in source
    assert '"streamingAlbumStatsLine"' in source

    # Q7H6 added a special visible label for personal Radio
    # carried by the native Mix endpoint. Ordinary album/detail
    # pages must still fall back to the supplied artist metadata.
    assert "albumArtist.textContent =" in source
    assert 'fromView === "radio"' in source
    assert '"Artist Radio · TIDAL"' in source
    assert ': (context.artist || "");' in source


def test_tidal_album_does_not_present_first_track_quality_as_album_tech():
    source = fn("loadTrackList")

    expected = """if (isTidalAlbum) {
                    albumTechInfo.textContent = "";
                    albumTechInfo.className = "hidden";
                }"""

    assert expected in source


def test_css_streaming_album_order_matches_local_reference():
    assert (
        "#albumView.tidalAlbumDetail #albumArtist"
        in CSS
    )

    assert (
        "#albumView.tidalAlbumDetail #albumTitle"
        in CSS
    )

    assert "order: 1 !important" in CSS
    assert "order: 2 !important" in CSS

    assert (
        "#albumTechInfo.qobuzAlbumTechInfo"
        in CSS
    )

    assert (
        "#albumStatsLine.streamingAlbumStatsLine"
        in CSS
    )


def test_qobuz_quality_colors_follow_srova_logic():
    assert (
        "#albumTechInfo.qobuzAlbumTechInfoHiRes"
        in CSS
    )

    assert "color: var(--srova-gold) !important" in CSS

    assert (
        "#albumTechInfo.qobuzAlbumTechInfoCd"
        in CSS
    )

    assert "color: var(--srova-cyan) !important" in CSS


def test_local_album_renderer_still_exists():
    assert "function renderLocalAlbumDetail(" in UI



def test_album_source_label_exists_in_shared_dom():
    index = (
        ROOT / "src/ui_web/index.html"
    ).read_text(encoding="utf-8")

    assert (
        '<div id="albumSourceLabel" class="hidden"></div>'
        in index
    )


def test_album_source_labels_match_current_section_names():
    source = fn("setAlbumViewKind")

    assert 'sourceLabel = "MUSIC"' in source
    assert 'sourceLabel = "TIDAL"' in source
    assert 'sourceLabel = "QOBUZ"' in source

    assert "MY MUSIC" not in source


def test_album_source_label_is_hidden_outside_album_kinds():
    source = fn("setAlbumViewKind")

    assert 'var sourceLabel = ""' in source
    assert (
        'sourceLabel\n'
        '                ? "albumSourceLabel"\n'
        '                : "hidden"'
        in source
    )


def test_album_source_label_is_restrained_eyebrow():
    assert (
        "#albumSourceLabel.albumSourceLabel"
        in CSS
    )

    assert "font-size: 10px !important" in CSS
    assert "letter-spacing: 0.22em !important" in CSS
    assert "text-transform: uppercase !important" in CSS


def test_qobuz_tech_line_no_longer_says_catalog():
    source = fn("qobuzAlbumCatalogTech")

    assert 'var bits = []' in source
    assert '"Catalog"' not in source
