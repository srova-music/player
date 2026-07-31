from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN = (REPO_ROOT / "src/main_headless.py").read_text(encoding="utf-8")
UI = (REPO_ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
CSS = (REPO_ROOT / "src/ui_web/srova.css").read_text(encoding="utf-8")
INDEX = (REPO_ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")


def test_backend_exposes_process_start_identity_without_cache():
    assert "_SROVA_PROCESS_STARTED_AT = time.time()" in MAIN
    assert '"process_started_at": _SROVA_PROCESS_STARTED_AT' in MAIN
    assert 'if static_path == "/api/network":' in MAIN
    assert "self._send_json(_network_payload(), no_store=True)" in MAIN


def test_system_settings_contains_always_visible_service_section():
    service = "panels.system.appendChild(buildSrovaServiceSection());"
    remote = "panels.system.appendChild(buildRemoteAccessSection());"
    assert service in UI
    assert remote in UI
    assert UI.index(service) < UI.index(remote)
    assert "function buildSrovaServiceSection()" in UI
    assert "SROVA last restarted:" in UI


def test_restart_confirmation_uses_changed_backend_start_identity():
    assert "function waitForSrovaServiceRestart(previousStartedAt, onProgress)" in UI
    assert "Math.abs(startedAt - previousStartedAt) > 0.001" in UI
    assert "SROVA restarted successfully at " in UI
    assert "This page will reconnect automatically." in UI


def test_port_change_reconnects_at_new_origin_and_confirms_restart():
    assert "function waitForSrovaTargetReachable(targetUrl)" in UI
    assert "buildSrovaRestartReturnUrl" in UI
    assert '"srova-restart-from"' in UI
    assert "window.location.replace(" in UI
    assert "restoreSrovaRestartReturnView" in UI
    assert "clearSrovaRestartReturnState" in UI


def test_manual_refresh_is_distinct_from_restart():
    assert 'aria-label", "Refresh SROVA status"' in UI
    assert "srovaServiceRefreshBtn" in UI
    assert "loadServiceState({announce: true})" in UI
    assert "Refresh SROVA status to check again." in UI


def test_restart_modal_cannot_be_dismissed_while_busy():
    import re

    assert 'modal.setAttribute("data-restart-busy", "false")' in UI
    assert 'modal.setAttribute("data-restart-busy", "true")' in UI
    assert (
        'modal.getAttribute("data-restart-busy") !== "true"'
        in UI
    )

    false_assignments = re.findall(
        r"""modal\.setAttribute\(\s*
            ["']data-restart-busy["']\s*,\s*
            ["']false["']\s*
            \)""",
        UI,
        flags=re.VERBOSE,
    )

    assert len(false_assignments) >= 3


def test_remote_access_restart_flow_is_preserved():
    assert "function buildRemoteAccessSection()" in UI
    assert 'fetch("/api/settings/web-port"' in UI
    assert 'fetch("/api/system/restart"' in UI
    assert "After Restart, Open" in UI
    assert 'settingsView.querySelector(".srovaServiceRestartBtn")' in UI
    assert "serviceRestartBtn.click()" in UI


def test_service_section_css_is_scoped_and_mobile_safe():
    assert "#settingsView .srovaServiceSection" in CSS
    assert "#settingsView .srovaServiceRefreshBtn" in CSS
    assert "#settingsView .srovaServiceRestartBtn" in CSS
    assert "@media (max-width: 640px)" in CSS
    assert "#d88a7a" not in CSS
    assert "--srova-danger" not in CSS


def test_system_restart_assets_use_valid_cache_tokens():
    import re

    asset_patterns = {
        "ui.js": r"/ui_web/ui\.js\?v=([A-Za-z0-9_.-]+)",
        "srova.css": r"/ui_web/srova\.css\?v=([A-Za-z0-9_.-]+)",
    }

    for asset, pattern in asset_patterns.items():
        tokens = re.findall(pattern, INDEX)
        assert len(tokens) == 1, (asset, tokens)
        assert tokens[0]

    assert '<script src="/ui_web/ui.js"></script>' not in INDEX
    assert (
        '<link rel="stylesheet" href="/ui_web/srova.css">'
        not in INDEX
    )


def test_remote_access_restart_hidden_rule_wins_settings_cascade():
    assert (
        "#settingsView .remoteAccessSection "
        ".remoteActionRow .settingsBtn.hidden"
        in CSS
    )
    assert "display: none !important;" in CSS



def test_backend_restart_uses_systemd_managed_self_exit():
    start = MAIN.index("def _restart_srova_service_later")
    end = MAIN.index(
        "# =========================================================================",
        start,
    )
    restart = MAIN[start:end]

    assert "_SROVA_RESTART_EXIT_CODE = 75" in MAIN
    assert "_SROVA_RESTART_SCHEDULED" in restart
    assert "save_thread.join(timeout=2.0)" in restart
    assert "player.stop()" in restart
    assert "logging.shutdown()" in restart
    assert "os._exit(_SROVA_RESTART_EXIT_CODE)" in restart

    assert '["systemctl", "restart"' not in restart
    assert '["sudo", "-n"' not in restart
    assert "subprocess.Popen(cmd" not in restart


def test_packaged_services_restart_after_controlled_failure_exit():
    source = (REPO_ROOT / "package.sh").read_text(
        encoding="utf-8",
    )

    assert "Restart=on-failure" in source



def test_restart_busy_and_success_actions_are_safe():
    assert 'restartBtn.textContent = "Restarting…";' in UI
    assert "holdServiceControlsAfterSuccess" in UI
    assert 'setStatus("SROVA service is reachable.");' in UI
    assert "srovaRestartSuccessActionsHidden" in UI

    assert (
        "#settingsView .srovaServiceRestartBtn:disabled"
        in CSS
    )
    assert (
        ".srovaRestartModal .settingsBtnDanger:disabled"
        in CSS
    )
    assert (
        ".srovaRestartActions.srovaRestartSuccessActionsHidden"
        in CSS
    )
