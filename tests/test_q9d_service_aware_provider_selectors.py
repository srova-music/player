from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/ui_web/srova.css").read_text(encoding="utf-8")
INDEX = (ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")
BACKEND = (ROOT / "src/main_headless.py").read_text(encoding="utf-8")


def test_q9d_has_two_independent_saved_provider_values():
    assert 'var q9dInfinitePlayProvider = "tidal";' in UI
    assert 'var q9dAutoMixProvider = "tidal";' in UI

    assert '"infinite_play_provider"' in BACKEND
    assert '"automix_provider"' in BACKEND


def test_q9d_selector_is_dual_auth_only():
    block = UI[
        UI.index("function q9dProviderSelectorsVisible()"):
        UI.index("function q9dProviderSavedValue(")
    ]

    assert "streamingProviderAuthState.tidal === true" in block
    assert "streamingProviderAuthState.qobuz === true" in block


def test_q9d_selector_orientation_is_tidal_left_qobuz_right():
    block = UI[
        UI.index("function buildQ9dProviderSelector("):
        UI.index("function buildAutoMixSection(")
    ]

    compact = " ".join(block.split())

    tidal_marker = (
        'makeProviderLabel( "tidal", "TIDAL" )'
    )

    toggle_marker = (
        'toggle.className = "q9dProviderSelectorSwitch";'
    )

    qobuz_marker = (
        'makeProviderLabel( "qobuz", "QOBUZ" )'
    )

    assert tidal_marker in compact
    assert toggle_marker in compact
    assert qobuz_marker in compact

    assert (
        compact.index(tidal_marker)
        <
        compact.index(toggle_marker)
        <
        compact.index(qobuz_marker)
    )

def test_q9d_uses_existing_provider_setting_endpoints():
    block = UI[
        UI.index("function q9dProviderSettingsEndpoint("):
        UI.index("function syncQ9dProviderSelectors(")
    ]

    assert '"/api/settings/infinite-play"' in block
    assert '"/api/settings/automix"' in block


def test_q9d_provider_save_posts_only_provider_configuration():
    block = UI[
        UI.index("function saveQ9dProviderPreference("):
        UI.index("function buildQ9dProviderSelector(")
    ]

    assert "JSON.stringify({" in block
    assert "provider: provider" in block

    # Selecting a provider must not create a mix or refill a queue.
    assert "/api/automix/create" not in block
    assert "/api/infinite-play/refill" not in block


def test_q9d_both_feature_sections_get_provider_selector():
    automix = UI[
        UI.index("function buildAutoMixSection("):
        UI.index("function buildInfinitePlaySection(")
    ]

    infinite = UI[
        UI.index("function buildInfinitePlaySection("):
        UI.index("function normalizeTidalInfinitePlayMode(")
    ]

    assert 'buildQ9dProviderSelector(' in automix
    assert '"automix"' in automix
    assert '"Auto-Mix provider"' in automix

    assert 'buildQ9dProviderSelector(' in infinite
    assert '"infinite_play"' in infinite
    assert '"Infinite Play provider"' in infinite


def test_q9d_saved_provider_not_overwritten_by_single_provider_fallback():
    visibility = UI[
        UI.index("function q9dProviderSelectorsVisible()"):
        UI.index("function q9dProviderSavedValue(")
    ]

    sync = UI[
        UI.index("function syncQ9dProviderSelectors()"):
        UI.index("function saveQ9dProviderPreference(")
    ]

    # Auth loss may hide the selector, but visibility/sync must not
    # rewrite the user's saved provider preference.
    assert "setQ9dProviderSavedValue(" not in visibility
    assert "setQ9dProviderSavedValue(" not in sync


def test_q9d_auth_refresh_updates_open_settings_selector_visibility():
    assert "streamingProviderAuthState.tidal =" in UI
    assert "streamingProviderAuthState.qobuz =" in UI
    assert UI.count("syncQ9dProviderSelectors();") >= 5


def test_q9d_selector_css_centers_text_on_both_axes():
    start = CSS.index(
        "Q9D — SERVICE-AWARE INFINITE PLAY / AUTO-MIX PROVIDER SELECTORS"
    )
    block = CSS[start:]

    assert "display: inline-flex !important;" in block
    assert "align-items: center !important;" in block
    assert "justify-content: center !important;" in block
    assert "text-align: center !important;" in block
    assert "line-height: 1 !important;" in block


def test_q9d_hidden_selector_is_really_hidden():
    start = CSS.index(
        "#settingsView .q9dProviderSelectorRow[hidden]"
    )
    block = CSS[start:start + 180]

    assert "display: none !important;" in block


def test_q9d_backend_saved_effective_separation_remains_present():
    assert "def _infinite_play_saved_provider():" in BACKEND
    assert "def _effective_infinite_play_provider():" in BACKEND
    assert "def _automix_saved_provider():" in BACKEND
    assert "def _effective_automix_provider():" in BACKEND

    assert (
        'if static_path == "/api/settings/automix":'
        in BACKEND
    )
    assert (
        '"/api/settings/infinite-play",'
        in BACKEND
    )

def test_q9d_infinite_play_copy_is_provider_neutral():
    block = UI[
        UI.index("function buildInfinitePlaySection("):
        UI.index("function normalizeTidalInfinitePlayMode(")
    ]

    assert (
        "Requires the selected streaming service, Last.fm setup, "
        "and a playable seed track."
        in block
    )

    assert "Requires TIDAL login" not in block
    assert "playable TIDAL seed track" not in block


def test_q9d_auth_status_errors_hide_selector_until_reconfirmed():
    tidal = UI[
        UI.index("function refreshTidalSettingsStatus("):
        UI.index("function buildQobuzSection(")
    ]

    qobuz = UI[
        UI.index("function refreshQobuzSettingsStatus("):
        UI.index("function refreshQobuzProviderAuthSurfaces(")
    ]

    assert "streamingProviderAuthState.tidal = null;" in tidal
    assert "streamingProviderAuthState.qobuz = null;" in qobuz

    assert "syncQ9dProviderSelectors();" in tidal
    assert "syncQ9dProviderSelectors();" in qobuz

def test_q9d_static_assets_have_q9d_cache_busters():
    assert (
        "/ui_web/srova.css?"
        "v=20260914_v2_0_q10d_auth_ux_css2_q10f_provider_aware_go_to_album_css3"
        in INDEX
    )

    assert (
        "/ui_web/ui.js?"
        "v=20260912_v2_0_q10a_infinite_play_pause_logo_js4"
        in INDEX
    )

    assert (
        "20260912_v2_0_q9d_provider_title_row_css3"
        not in INDEX
    )

    assert (
        "20260912_v2_0_q9d_provider_toggle_js2"
        not in INDEX
    )

def test_q9d_selector_uses_physical_two_position_switch():
    block = UI[
        UI.index("function buildQ9dProviderSelector("):
        UI.index("function buildAutoMixSection(")
    ]

    assert '"q9dProviderSelectorSwitch"' in block
    assert '"data-q9d-provider-toggle"' in block
    assert '"switch"' in block

    start = CSS.index(
        "Q9D — SERVICE-AWARE INFINITE PLAY / AUTO-MIX PROVIDER SELECTORS"
    )
    css_block = CSS[start:]

    assert ".q9dProviderSelectorSwitch::before" in css_block
    assert ".q9dProviderSelectorSwitchQobuz::before" in css_block
    assert "transform: translateX(28px) !important;" in css_block
    assert ".q9dProviderSelectorLabelActive" in css_block

def test_q9d_provider_selectors_are_inside_section_title_rows():
    automix = UI[
        UI.index("function buildAutoMixSection("):
        UI.index("function buildInfinitePlaySection(")
    ]

    infinite = UI[
        UI.index("function buildInfinitePlaySection("):
        UI.index("function normalizeTidalInfinitePlayMode(")
    ]

    for block, feature in (
        (automix, '"automix"'),
        (infinite, '"infinite_play"'),
    ):
        compact = " ".join(block.split())

        assert (
            '"settingsSectionTitle q9dProviderTitleRow"'
            in compact
        )

        selector = compact.index(
            "titleRow.appendChild( "
            "buildQ9dProviderSelector("
        )

        title_attach = compact.index(
            "sec.appendChild(titleRow);"
        )

        description = compact.index(
            'var desc = document.createElement("div");'
        )

        assert feature in compact
        assert selector < title_attach < description


def test_q9d_title_row_wraps_cleanly_for_mobile():
    start = CSS.index(
        "Q9D — SERVICE-AWARE INFINITE PLAY / AUTO-MIX PROVIDER SELECTORS"
    )

    block = CSS[start:]

    assert "#settingsView .q9dProviderTitleRow" in block
    assert "flex-wrap: wrap !important;" in block
    assert "#settingsView .q9dProviderTitleLead" in block
    assert "white-space: nowrap !important;" in block

def test_q9d_mobile_title_row_selector_is_compact_but_can_still_wrap():
    start = CSS.index(
        "Q9D — SERVICE-AWARE INFINITE PLAY / AUTO-MIX PROVIDER SELECTORS"
    )

    block = CSS[start:]

    assert "@media (max-width: 700px)" in block
    assert "column-gap: 8px !important;" in block

    assert (
        "minmax(48px, auto)\n"
        "            58px\n"
        "            minmax(48px, auto) !important;"
        in block
    )

    assert "gap: 6px !important;" in block
    assert "min-width: 48px !important;" in block

    # Do not force nowrap: narrower screens must retain safe wrapping.
    mobile = block[
        block.index("@media (max-width: 700px)"):
    ]

    assert "flex-wrap: nowrap" not in mobile
