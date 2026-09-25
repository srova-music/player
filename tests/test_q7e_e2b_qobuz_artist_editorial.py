from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

UI_PATH = ROOT / "src/ui_web/ui.js"
CSS_PATH = ROOT / "src/ui_web/srova.css"

UI = UI_PATH.read_text(
    encoding="utf-8"
)

CSS = CSS_PATH.read_text(
    encoding="utf-8"
)


def fn(name):
    match = re.search(
        r"(?m)^function\s+" +
        re.escape(name) +
        r"\s*\(",
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
    pos = brace

    while pos < len(UI):
        char = UI[pos]

        if quote:
            if escaped:
                escaped = False

            elif char == "\\":
                escaped = True

            elif char == quote:
                quote = None

            pos += 1
            continue

        if char in ("'", '"', "`"):
            quote = char

        elif char == "{":
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


def test_e2b_reuses_existing_artist_page_response():
    source = fn(
        "loadQobuzArtistDetail"
    )

    assert (
        "renderQobuzArtistEditorial("
        in source
    )

    assert (
        "renderQobuzArtistEditorial(\n"
        "            page"
        in source
    )


def test_e2b_has_no_extra_qobuz_request():
    source = fn(
        "renderQobuzArtistEditorial"
    )

    assert "/qobuz/catalog" not in source
    assert "op=artist_story" not in source
    assert "op=similar_artists" not in source


def test_e2b_biography_plain_text_only():
    source = fn(
        "renderQobuzArtistEditorial"
    )

    normalizer = fn(
        "qobuzBiographyPlainText"
    )

    assert (
        "page.biography.content"
        in source
    )

    assert (
        "qobuzBiographyPlainText("
        in source
    )

    assert (
        ".replace(/<br"
        in normalizer
    )

    assert (
        ".replace(/<[^>]+>/g"
        in normalizer
    )

    assert (
        "&copy;?"
        in normalizer
    )

    assert (
        '\\u00a9'
        in normalizer
    )

    assert (
        'bioHeader.textContent =\n'
        '            "Biography"'
        in source
    )

    assert (
        "bioText.textContent =\n"
        "            biography"
        in source
    )

    assert "bioText.innerHTML" not in source


def test_e2b_empty_optionals_render_nothing():
    source = fn(
        "renderQobuzArtistEditorial"
    )

    assert (
        "!biography && !similar.length"
        in source
    )


def test_e2b_similar_uses_existing_adapter_and_shelf():
    source = fn(
        "renderQobuzArtistEditorial"
    )

    assert (
        'adaptQobuzWallItem(\n'
        '                item,\n'
        '                "artist"'
        in source
    )

    assert (
        'buildScrollSection(\n'
        '            "Similar Artists"'
        in source
    )


def test_e2b_removes_home_section_presentation():
    source = fn(
        "renderQobuzArtistEditorial"
    )

    assert (
        '"artistSection qobuzArtistSimilarSection"'
        in source
    )

    assert (
        'removeAttribute(\n'
        '        "data-kind"'
        in source
    )

    assert (
        'similarHeader.className =\n'
        '            "artistSectionHdr"'
        in source
    )


def test_e2b_similar_navigation_preserves_parent_restore():
    source = fn(
        "renderQobuzArtistEditorial"
    )

    assert (
        "var parentRestore ="
        in source
    )

    assert (
        "_qobuzArtistPageRestoreFn"
        in source
    )

    assert (
        "loadQobuzArtistDetail("
        in source
    )

    assert (
        '"artistpage"'
        in source
    )

    assert (
        "parentRestore"
        in source
    )


def test_e2b_missing_similar_artwork_uses_existing_fallback():
    adapter = fn(
        "adaptQobuzWallItem"
    )

    assert (
        "SROVA_STANDBY_ART"
        in adapter
    )


def test_e2b_no_new_direct_buttons_or_mutation_routes():
    source = fn(
        "renderQobuzArtistEditorial"
    )

    assert (
        'createElement("button")'
        not in source
    )

    for forbidden in (
        "/qobuz/favorite",
        "/qobuz/playlist",
        "/qobuz/play",
        "/qobuz/queue",
    ):
        assert forbidden not in source


def test_e2b_css_scoped_to_artist_detail():
    assert (
        "#albumView.tidalArtistDetail "
        ".qobuzArtistBiographyText"
        in CSS
    )

    assert (
        "#albumView.tidalArtistDetail "
        ".qobuzArtistSimilarSection"
        in CSS
    )

    assert (
        "@media (max-width: 640px)"
        in CSS
    )


def test_ui_parses():
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

    assert result.returncode == 0, (
        result.stderr
    )
