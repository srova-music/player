from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "src" / "ui_web" / "ui.js"
CSS_PATH = ROOT / "src" / "ui_web" / "srova.css"
INDEX_PATH = ROOT / "src" / "ui_web" / "index.html"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"


def _function_section(source, start_name, end_name):
    start = source.index(start_name)
    end = source.index(end_name, start)
    return source[start:end]


def test_lastfm_section_explains_srova_benefits():
    source = UI_PATH.read_text(encoding="utf-8")

    assert 'sec.className = "settingsSection settingsLastfmSection";' in source
    assert '"Get more from SROVA with Last.fm"' in source
    assert (
        '"Creating and connecting a free Last.fm account is a quick, '
        'one-time setup that unlocks additional features across SROVA:"'
        in source
    )
    assert (
        '"See automatic song artwork while listening to Internet Radio"'
        in source
    )
    assert (
        '"Discover new music with Auto-Mix and Infinite Play"'
        in source
    )
    assert (
        '"Scrobble everything you play from TIDAL, My Music and Internet Radio"'
        in source
    )


def test_lastfm_benefits_do_not_claim_artist_info_dependency():
    source = UI_PATH.read_text(encoding="utf-8")
    section = _function_section(
        source,
        "function buildLastfmSection",
        "function buildLbzSection",
    )

    assert "Artist Info" not in section
    assert "biographies" not in section
    assert "similar artists" not in section.lower()


def test_signup_links_use_external_browser_attributes():
    source = UI_PATH.read_text(encoding="utf-8")

    assert 'link.target      = "_blank";' in source
    assert 'link.rel         = "noopener";' in source
    assert '"https://www.last.fm/join"' in source
    assert (
        '"https://musicbrainz.org/register?returnto=%2F"'
        in source
    )


def test_obsolete_scrobbling_help_links_are_removed():
    source = UI_PATH.read_text(encoding="utf-8")

    assert "https://www.last.fm/api/account/create" not in source
    assert "Get a Last.fm API key" not in source
    assert "https://listenbrainz.org/profile/" not in source
    assert "Get your ListenBrainz token" not in source


def test_lastfm_signup_link_is_only_shown_while_disconnected():
    source = UI_PATH.read_text(encoding="utf-8")
    section = _function_section(
        source,
        "function buildLastfmSection",
        "function buildLbzSection",
    )

    assert section.count("if (!st.lastfm_connected)") == 1
    assert section.count('"https://www.last.fm/join"') == 1

    link_position = section.index('"https://www.last.fm/join"')
    connected_position = section.index("if (st.lastfm_connected)")

    assert link_position < connected_position


def test_listenbrainz_signup_link_is_only_in_disconnected_branch():
    source = UI_PATH.read_text(encoding="utf-8")
    section = _function_section(
        source,
        "function buildLbzSection",
        "function buildTidalSection",
    )

    connected_start = section.index("if (st.lbz_connected)")
    disconnected_start = section.index("} else {", connected_start)
    signup_position = section.index(
        '"https://musicbrainz.org/register?returnto=%2F"'
    )

    assert signup_position > disconnected_start
    assert section.count(
        '"https://musicbrainz.org/register?returnto=%2F"'
    ) == 1

    connected_branch = section[connected_start:disconnected_start]
    assert "settingsListenBrainzSignupLink" not in connected_branch


def test_connected_listenbrainz_button_follows_block_status_row():
    source = UI_PATH.read_text(encoding="utf-8")
    section = _function_section(
        source,
        "function buildLbzSection",
        "function buildTidalSection",
    )

    connected_start = section.index("if (st.lbz_connected)")
    disconnected_start = section.index("} else {", connected_start)
    connected_branch = section[connected_start:disconnected_start]

    assert "sec.appendChild(info);" in connected_branch
    assert "sec.appendChild(signupLink);" not in connected_branch
    assert connected_branch.index(
        "sec.appendChild(info);"
    ) < connected_branch.index(
        'var dis = document.createElement("button");'
    )


def test_scrobbling_benefits_use_scoped_existing_theme_styles():
    css = CSS_PATH.read_text(encoding="utf-8")

    assert (
        "#settings-tab-panel-scrobbling .settingsLastfmBenefits"
        in css
    )
    assert (
        "#settings-tab-panel-scrobbling .settingsSignupLink"
        in css
    )
    assert "var(--srova-cream)" in css
    assert "var(--srova-cream-dim)" in css
    assert "var(--srova-body)" in css
    assert "var(--srova-display)" in css


def test_scrobbling_assets_use_valid_cache_tokens():
    import re

    index = INDEX_PATH.read_text(encoding="utf-8")
    asset_patterns = {
        "ui.js": r"/ui_web/ui\.js\?v=([A-Za-z0-9_.-]+)",
        "srova.css": r"/ui_web/srova\.css\?v=([A-Za-z0-9_.-]+)",
    }

    for asset, pattern in asset_patterns.items():
        tokens = re.findall(pattern, index)
        assert len(tokens) == 1, (asset, tokens)
        assert tokens[0]

    assert '<script src="/ui_web/ui.js"></script>' not in index
    assert (
        '<link rel="stylesheet" href="/ui_web/srova.css">'
        not in index
    )


def test_changelog_records_setup_only_signup_links():
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")

    assert (
        "Last.fm benefits guidance in Scrobbling Settings explaining "
        "the SROVA enhancements unlocked by a free, one-time setup"
        in changelog
    )
    assert (
        "External-browser signup links for free Last.fm and "
        "ListenBrainz-compatible accounts, shown only while setup is required"
        in changelog
    )
