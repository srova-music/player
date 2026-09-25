from pathlib import Path


UI = Path("src/ui_web/ui.js").read_text(encoding="utf-8")
INDEX = Path("src/ui_web/index.html").read_text(encoding="utf-8")
CSS = Path("src/ui_web/srova.css").read_text(encoding="utf-8")
MAIN = Path("src/main_headless.py").read_text(encoding="utf-8")
QOBUZ = Path("src/backend/qobuz.py").read_text(encoding="utf-8")


def test_q7i_visible_settings_tab_is_online_but_internal_id_stays_tidal():
    assert '{ id: "tidal", label: "ONLINE" }' in UI
    assert '{ id: "tidal", label: "TIDAL" }' not in UI


def test_q7i_account_section_order_is_tidal_qobuz_automix():
    tidal = (
        'panels.tidal.appendChild('
        'buildTidalSection({_tidal_status_loading: true}));'
    )
    qobuz = (
        'panels.tidal.appendChild('
        'buildQobuzSection({_qobuz_status_loading: true}));'
    )
    automix = (
        'panels.tidal.appendChild(buildAutoMixSection(st));'
    )

    assert tidal in UI
    assert qobuz in UI
    assert automix in UI

    assert UI.index(tidal) < UI.index(qobuz) < UI.index(automix)


def test_q7i_uses_existing_q2_http_contract():
    assert '"/qobuz/status?_="' in UI
    assert '"/qobuz/login/start"' in UI
    assert '"/qobuz/login/poll?attempt_id="' in UI
    assert 'encodeURIComponent(' in UI
    assert '_qobuzLoginAttemptId' in UI
    assert '"/qobuz/logout"' in UI


def test_q7i_has_signed_out_pending_connected_and_logout_surfaces():
    assert "function buildQobuzSection(st)" in UI
    assert '"Not logged in to Qobuz."' in UI
    assert '"Qobuz sign-in is waiting for authorisation."' in UI
    assert 'qobuzUser.display_name' in UI
    assert '"Continue Login"' in UI
    assert '"Logout"' in UI


def test_q7i_qobuz_auth_refresh_updates_shared_provider_state():
    assert (
        "streamingProviderAuthState.qobuz =\n"
        "        st.authenticated;"
    ) in UI

    assert "applyStreamingProviderPresentation();" in UI
    assert "syncProviderRadioSettingsControls();" in UI
    assert "refreshQobuzProviderAuthSurfaces()" in UI


def test_q7i_settings_reentry_refreshes_both_accounts():
    assert UI.count(
        "refreshTidalSettingsStatus(renderToken);"
    ) >= 2

    assert UI.count(
        "refreshQobuzSettingsStatus(renderToken);"
    ) >= 2


def test_q7i_existing_modal_is_provider_aware_without_new_password_capture():
    assert "configureLoginModalForProvider" in UI
    assert (
        '"Open the link below in your browser and log in to Qobuz:"'
        in UI
    )
    assert '_loginModalProvider === "qobuz"' in UI


def test_q7i_qobuz_buttons_reuse_two_axis_centered_settings_button():
    assert 'retryBtn.className = "settingsBtn";' in UI
    assert 'continueBtn.className = "settingsBtn";' in UI
    assert 'loginButton.className = "settingsBtn";' in UI

    assert (
        'logoutBtn.className =\n'
        '            "settingsBtn settingsBtnDanger";'
    ) in UI

    import re

    blocks = re.findall(
        r"(?m)^\s*\.settingsBtn\s*\{([^}]*)\}",
        CSS,
    )

    assert blocks

    assert any(
        "display: inline-flex !important;" in block
        and "align-items: center !important;" in block
        and "justify-content: center !important;" in block
        and "line-height: 1 !important;" in block
        for block in blocks
    )


def test_q7i_does_not_rename_or_remove_locked_radio_controls():
    assert '"Show TIDAL Radio"' in UI
    assert '"Show Qobuz Radio"' in UI
    assert '"settingsShowTidalRadioToggle"' in UI
    assert '"settingsShowQobuzRadioToggle"' in UI


def test_q7i_headless_login_restores_original_q2_loopback_callback():
    assert "def start_login(self):" in QOBUZ

    assert (
        'redirect = f"http://localhost:{port}/{nonce}"'
        in QOBUZ
    )

    assert (
        'listener.bind(("127.0.0.1", 0))'
        in QOBUZ
    )

    start = MAIN.index(
        'if static_path == "/qobuz/login/start":'
    )
    end = MAIN.index(
        'if static_path == "/qobuz/login/poll":',
        start,
    )

    login_start = MAIN[start:end]

    assert "getsockname" not in login_start
    assert "callback_host" not in login_start


def test_q7i_has_client_neutral_qobuz_completion_endpoint():
    assert (
        'if self.path == "/qobuz/login/complete":'
        in MAIN
    )

    assert "backend.complete_login(" in MAIN
    assert "def complete_login(" in QOBUZ

    assert (
        '"/qobuz/login/complete"'
        in UI
    )

    assert "attempt_id:" in UI
    assert "callback_url:" in UI


def test_q7i_browser_fallback_uses_full_callback_url():
    assert 'id="qobuzLoginComplete"' in INDEX
    assert 'id="qobuzCallbackUrl"' in INDEX
    assert 'type="url"' in INDEX
    assert 'autocomplete="off"' in INDEX

    assert (
        'id="qobuzCompleteLoginBtn"'
        in INDEX
    )

    assert (
        'onclick="completeQobuzLogin()"'
        in INDEX
    )

    assert (
        "function completeQobuzLogin()"
        in UI
    )


def test_q7i_browser_fallback_does_not_capture_password_or_token():
    start = INDEX.index(
        'id="qobuzLoginComplete"'
    )

    end = INDEX.index(
        '<button class="loginCancelBtn"',
        start,
    )

    block = INDEX[start:end].lower()

    assert 'type="password"' not in block
    assert "user_auth_token" not in block
    assert "private_key" not in block


def test_q7i_completion_button_uses_two_axis_centered_settings_button():
    assert (
        'class="settingsBtn qobuzCompleteBtn"'
        in INDEX
    )

    import re

    blocks = re.findall(
        r"(?m)^\s*\.settingsBtn\s*\{([^}]*)\}",
        CSS,
    )

    assert any(
        "display: inline-flex !important;" in block
        and "align-items: center !important;" in block
        and "justify-content: center !important;" in block
        for block in blocks
    )
