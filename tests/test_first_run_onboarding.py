from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
HTML = (ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")


def function_source(name):
    match = re.search(
        rf"\bfunction\s+{re.escape(name)}\s*\([^)]*\)\s*\{{",
        UI,
    )
    assert match, f"missing function: {name}"

    start = match.start()
    cursor = match.end() - 1
    depth = 0
    quote = None
    escaped = False

    while cursor < len(UI):
        char = UI[cursor]

        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        else:
            if char in ("'", '"', "`"):
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return UI[start:cursor + 1]

        cursor += 1

    raise AssertionError(f"unterminated function: {name}")


def test_volume_warning_is_versioned_for_v1():
    assert (
        'SROVA_VOLUME_SAFETY_DISMISSED_KEY = '
        '"srovaVolumeSafetyWarningDismissedV1"'
    ) in UI
    assert "showSrovaVolumeSafetyModal();" in UI


def test_hidden_global_search_is_disabled():
    source = function_source("setGlobalSearchVisible")
    assert "searchInput.disabled = true;" in source
    assert "searchInput.disabled = false;" in source
    assert 'searchInput.setAttribute("aria-hidden", "true")' in source

    handler = function_source("onSearchInput")
    assert "searchInput.disabled" in handler

    settings = function_source("showSettings")
    assert "setGlobalSearchVisible(false);" in settings


def test_global_search_is_marked_as_non_credential_input():
    assert 'name="srova_global_search"' in HTML
    assert 'autocomplete="off"' in HTML
    assert 'autocapitalize="none"' in HTML
    assert 'autocorrect="off"' in HTML
    assert 'spellcheck="false"' in HTML


def test_tidal_and_playlists_require_login():
    tidal = function_source("showTidalSource")
    playlists = function_source("showPlaylists")

    assert "requireSrovaTidalLogin" in tidal
    assert "requireSrovaTidalLogin" in playlists
    assert "Please log in to your TIDAL account first." in UI


def test_my_music_requires_configured_root():
    local = function_source("showLocalMusic")

    assert "requireSrovaMusicFolder" in local
    assert (
        "Please go to Settings and select a music folder first."
        in UI
    )


def test_radio_requires_named_saved_dac():
    radio = function_source("showRadioSource")
    helper = function_source("requireSrovaRadioDac")

    assert "requireSrovaRadioDac" in radio
    assert 'String(data.dac_name || "").trim()' in helper
    assert 'String(data.alsa_device || "").trim()' in helper
    assert "Please go to Settings and select your DAC first." in UI


def test_failed_setup_checks_return_home_and_use_existing_toast():
    helper = function_source("_srovaSetupGuardBlocked")

    assert "loadHome();" in helper
    assert "showQueueActionToast(message, true);" in helper


def test_ui_cache_token_updated():
    assert (
        "/ui_web/ui.js?v=20260806_v1_1_about_version1"
        in HTML
    )
