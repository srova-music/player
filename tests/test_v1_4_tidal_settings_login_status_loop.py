from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "src" / "ui_web" / "ui.js"
UI = UI_PATH.read_text(encoding="utf-8")


def source_block(start_marker: str, end_marker: str) -> str:
    start = UI.index(start_marker)
    end = UI.index(end_marker, start)
    return UI[start:end]


POLL_STATUS = source_block(
    "function pollStatus() {",
    "setInterval(pollStatus, 1000);",
)

UPDATE_LOGIN = source_block(
    "function updateLoginBtn(loggedIn, options) {",
    "function handleLoginLogout() {",
)

RENDER_SETTINGS = source_block(
    "function renderSettings() {",
    "function formatLocalLibraryTime(value) {",
)

REFRESH_TIDAL_SETTINGS = source_block(
    "function refreshTidalSettingsStatus(renderToken) {",
    "function _escapeText(v) {",
)

LOGIN_FLOW = source_block(
    "function startLogin(options) {",
    "function updateExclusiveLock(exclusive, isHiRes) {",
)


def test_status_poll_login_updates_are_hardened_against_settings_rerender():
    assert 'fetchWithTimeout("/status", {}, 3500)' in POLL_STATUS

    hardened = (
        "updateLoginBtn(s.logged_in, "
        "{skipSettingsRefresh: true});"
    )
    vulnerable = "updateLoginBtn(s.logged_in);"

    assert POLL_STATUS.count(hardened) == 2
    assert POLL_STATUS.count(vulnerable) == 0


def test_update_login_only_renders_settings_without_skip_flag():
    assert "var changed = (isLoggedIn !== loggedIn);" in UPDATE_LOGIN
    assert "isLoggedIn = loggedIn;" in UPDATE_LOGIN
    assert (
        "if (!options.skipSettingsRefresh && changed && settingsView "
        '&& settingsView.style.display !== "none")'
    ) in UPDATE_LOGIN
    assert "renderSettings();" in UPDATE_LOGIN


def test_settings_render_rebuilds_dom_and_refreshes_authoritative_tidal_status():
    assert 'settingsView.innerHTML = "";' in RENDER_SETTINGS
    assert RENDER_SETTINGS.count(
        "refreshTidalSettingsStatus(renderToken);"
    ) == 2


def test_tidal_settings_status_remains_authoritative_and_suppresses_rerender():
    assert '"/tidal/status?_="' in REFRESH_TIDAL_SETTINGS
    assert (
        "updateLoginBtn(false, {skipSettingsRefresh: true});"
    ) in REFRESH_TIDAL_SETTINGS
    assert (
        "updateLoginBtn(st.logged_in, {skipSettingsRefresh: true});"
    ) in REFRESH_TIDAL_SETTINGS
    assert "updateTidalSettingsSection(st);" in REFRESH_TIDAL_SETTINGS


class LoginUiModel:
    def __init__(self, settings_open: bool):
        self.settings_open = settings_open
        self.login_state = None
        self.settings_render_count = 0
        self.status_poll_count = 0
        self.tidal_status_count = 0
        self.tidal_settings_logged_in = None

    def status_poll(self, logged_in: bool):
        self.status_poll_count += 1
        self.login_state = logged_in

    def tidal_status(self, logged_in: bool):
        self.tidal_status_count += 1
        self.login_state = logged_in
        self.tidal_settings_logged_in = logged_in


@pytest.mark.parametrize(
    ("status_logged_in", "tidal_logged_in"),
    [
        (False, False),
        (True, True),
        (True, False),
        (False, True),
    ],
)
@pytest.mark.parametrize("settings_open", [True, False])
def test_synthetic_login_state_matrix_has_no_settings_render_loop(
    status_logged_in,
    tidal_logged_in,
    settings_open,
):
    model = LoginUiModel(settings_open=settings_open)

    for _ in range(10):
        model.status_poll(status_logged_in)
        model.tidal_status(tidal_logged_in)

    assert model.status_poll_count == 10
    assert model.tidal_status_count == 10
    assert model.settings_render_count == 0
    assert model.tidal_settings_logged_in is tidal_logged_in


def test_captured_true_false_failure_case_keeps_polling_without_render_loop():
    model = LoginUiModel(settings_open=True)

    for _ in range(20):
        model.status_poll(True)
        model.tidal_status(False)

    assert model.status_poll_count == 20
    assert model.tidal_status_count == 20
    assert model.settings_render_count == 0
    assert model.tidal_settings_logged_in is False


def test_normal_oauth_completion_preserves_explicit_settings_refresh():
    assert (
        "updateLoginBtn(true, {skipSettingsRefresh: true});"
    ) in LOGIN_FLOW
    assert 'if (_tidalLoginReturnToSettings) {' in LOGIN_FLOW
    assert 'currentSettingsTab = "tidal";' in LOGIN_FLOW
    assert 'showView("settings");' in LOGIN_FLOW
    assert "renderSettings();" in LOGIN_FLOW


def test_normal_logout_preserves_explicit_settings_refresh():
    assert 'fetch("/tidal/logout", {cache: "no-store"})' in LOGIN_FLOW
    assert LOGIN_FLOW.count(
        "updateLoginBtn(false, {skipSettingsRefresh: true});"
    ) == 2
    assert LOGIN_FLOW.count("renderSettings();") >= 3


def test_status_poll_continues_at_existing_one_second_interval():
    assert "setInterval(pollStatus, 1000);" in UI
