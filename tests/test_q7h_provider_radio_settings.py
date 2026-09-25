from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = (ROOT / "src/main_headless.py").read_text(encoding="utf-8")
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/ui_web/srova.css").read_text(encoding="utf-8")


def _slice(text, start, end):
    left = text.index(start)
    right = text.index(end, left)
    return text[left:right]


def test_q7h_h1_provider_radio_preferences_default_off():
    assert '"show_tidal_radio": False' in BACKEND
    assert '"show_qobuz_radio": False' in BACKEND


def test_q7h_h1_uses_existing_app_settings_persistence():
    helper = _slice(
        BACKEND,
        "def _provider_radio_visibility_settings():",
        "# =========================================================================\n# Queue persistence",
    )

    assert '_APP_SETTINGS.get("show_tidal_radio", False)' in helper
    assert '_APP_SETTINGS.get("show_qobuz_radio", False)' in helper
    assert '_APP_SETTINGS[key] = value' in helper
    assert "_save_app_settings()" in helper

    assert "RADIO_MODE" not in helper
    assert "CURRENT_RADIO" not in helper
    assert "_load_radio_stations" not in helper
    assert "_save_radio_stations" not in helper


def test_q7h_h1_provider_radio_settings_http_contract_exists():
    assert (
        'if static_path == "/api/settings/provider-radio":'
        in BACKEND
    )

    assert (
        'if self.path == "/api/settings/provider-radio":'
        in BACKEND
    )

    assert (
        "_set_provider_radio_visibility_settings("
        in BACKEND
    )


def test_q7h_h1_provider_radio_settings_are_additive_to_my_radio():
    append = _slice(
        UI,
        "function appendSettingsSections",
        "function loadAboutVersion",
    )

    assert (
        "panels.radio.appendChild(buildProviderRadioSettingsSection());"
        in append
    )

    assert (
        "panels.radio.appendChild(buildRadioSection());"
        in append
    )

    assert append.index(
        "buildProviderRadioSettingsSection()"
    ) < append.index(
        "buildRadioSection()"
    )

    custom = _slice(
        UI,
        "function buildRadioSection()",
        "\n}",
    )

    assert "My Radio" in custom


def test_q7h_h1_signed_out_toggles_are_disabled_without_resetting_preference():
    provider = _slice(
        UI,
        "var providerRadioVisibilityState = {",
        "\n\nvar streamingProviderAuthState = {",
    )

    assert "providerRadioStoredPreference(provider)" in provider
    assert "providerRadioAuthenticated(provider)" in provider

    assert (
        "!providerRadioVisibilityState.loaded ||"
        in provider
    )

    assert (
        "!authenticated"
        in provider
    )

    assert (
        'toggle.classList.toggle(\n'
        '            "active",\n'
        '            enabled'
        in provider
    )

    assert (
        'toggle.setAttribute(\n'
        '            "aria-pressed",'
        in provider
    )

    assert (
        '" — sign in to "'
        in provider
        or '" \\u2014 sign in to "'
        in provider
    )


def test_q7h_h1_effective_visibility_is_preference_and_auth():
    provider = _slice(
        UI,
        "function providerRadioEffectiveVisibility(provider)",
        "function syncProviderRadioSettingsControls()",
    )

    assert "providerRadioVisibilityState.loaded" in provider
    assert "providerRadioStoredPreference(provider)" in provider
    assert "providerRadioAuthenticated(provider)" in provider


def test_q7h_h1_radio_settings_labels_and_controls_exist():
    section = _slice(
        UI,
        "function buildProviderRadioSettingsSection()",
        "function buildRadioSection()",
    )

    assert "Show TIDAL Radio" in section
    assert "Show Qobuz Radio" in section

    assert "settingsShowTidalRadioToggle" in section
    assert "settingsShowQobuzRadioToggle" in section

    assert "settingsToggleRow" in section
    assert "settingsToggleSwitch" in section

    assert 'toggle.innerHTML =\n            "<span></span>";' in section


def test_q7h_h1_does_not_route_provider_settings_into_custom_radio_playback():
    section = _slice(
        UI,
        "function buildProviderRadioSettingsSection()",
        "function buildRadioSection()",
    )

    forbidden = (
        "/api/radio/play/",
        "buildRadioStationPayload",
        "enhanceRadioShelfOrdering",
        "radioDragHandle",
        "radio:station:",
    )

    for token in forbidden:
        assert token not in section


def test_q7h_h1_existing_custom_reorder_path_remains_present():
    assert "function enhanceRadioShelfOrdering(block, items)" in UI
    assert 'fetch("/api/radio/stations/order"' in UI
    assert 'handle.className = "radioDragHandle"' in UI
    assert "enhanceRadioShelfOrdering(block, items);" in UI


def test_q7h_h1_existing_toggle_geometry_is_reused():
    assert ".settingsToggleRow {" in CSS
    assert "align-items: center !important;" in CSS
    assert "justify-content: space-between !important;" in CSS
    assert ".settingsToggleSwitch {" in CSS
    assert "width: 54px !important;" in CSS
    assert "height: 28px !important;" in CSS
    assert ".settingsToggleSwitch span {" in CSS
    assert "width: 18px !important;" in CSS
    assert "height: 18px !important;" in CSS


def test_q7h_h1_no_provider_playback_work_has_started():
    section = _slice(
        UI,
        "function buildProviderRadioSettingsSection()",
        "function buildRadioSection()",
    )

    assert "postTidalQueueReplace" not in section
    assert "submitQueueTracks" not in section
    assert "radio_artist" not in section
    assert "radio_track" not in section
    assert "radio_album" not in section
