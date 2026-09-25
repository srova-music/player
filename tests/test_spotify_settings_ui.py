import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "src" / "ui_web" / "ui.js"
CSS_PATH = ROOT / "src" / "ui_web" / "srova.css"
HTML_PATH = ROOT / "src" / "ui_web" / "index.html"
UI = UI_PATH.read_text(encoding="utf-8")
CSS = CSS_PATH.read_text(encoding="utf-8")
HTML = HTML_PATH.read_text(encoding="utf-8")


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


def spotify_source():
    return function_source("buildSpotifySettingsSection")


def test_spotify_settings_tab_and_management_section_exist():
    assert '{ id: "spotify", label: "Spotify" }' in UI
    assert "panels.spotify.appendChild(buildSpotifySettingsSection());" in UI
    source = spotify_source()
    assert 'settingsSection spotifySettingsSection' in source
    assert "Spotify Connect" in source


def test_settings_tab_order_remains_approved():
    tabs = UI[UI.index("var SETTINGS_TABS = ["):UI.index("];", UI.index("var SETTINGS_TABS = ["))]
    assert re.findall(r'\{ id: "([^"]+)", label: "([^"]+)" \}', tabs) == [
        ("audio", "Audio"),
        ("tidal", "ONLINE"),
        ("local", "My Music"),
        ("radio", "Radio"),
        ("spotify", "Spotify"),
        ("scrobbling", "Scrobbling"),
        ("system", "System"),
        ("about", "About"),
    ]


def test_spotify_is_not_added_as_a_music_source_or_provider_tile():
    assert 'data-home-source="spotify"' not in UI
    assert 'data-source-switch="spotify"' not in UI
    assert 'id: "spotify", label: "Spotify"' in UI


def test_opening_settings_loads_all_four_read_only_contracts():
    source = spotify_source()
    assert 'spotifySettingsRequest("/api/spotify/status", {cache: "no-store"})' in source
    assert 'spotifySettingsRequest("/api/spotify/device-name", {cache: "no-store"})' in source
    assert 'spotifySettingsRequest("/api/spotify/artifact/status", {cache: "no-store"})' in source
    assert '"/api/spotify/artifact/update-status"' in UI
    opening = source[source.rindex("updateControls();"):]
    assert "refreshStatus();" in opening
    assert "refreshDeviceName();" in opening
    assert "refreshArtifactStatus().then" in opening
    assert "checkSpotifySoloistUpdate();" in opening
    assert 'method: "POST"' not in opening


def test_api_key_is_masked_write_only_and_never_read_back():
    source = spotify_source()
    assert 'keyInput.type = "password";' in source
    assert 'keyInput.autocomplete = "new-password";' in source
    assert 'keyInput.value = "";' in source
    assert "data.api_key" not in source
    assert 'spotifySettingsRequest("/api/spotify/config", {cache:' not in source
    assert 'fetch("/api/spotify/config"' not in source


def test_api_key_post_body_contains_only_new_api_key_and_clears_on_success():
    source = spotify_source()
    start = source.index("keySaveBtn.onclick = function()")
    end = source.index("deviceSaveBtn.onclick = function()", start)
    handler = source[start:end]
    assert 'spotifySettingsRequest("/api/spotify/config", {' in handler
    assert 'method: "POST"' in handler
    assert "body: JSON.stringify({api_key: newApiKey})" in handler
    assert "data.ok !== true" in handler
    assert handler.index('keyInput.value = "";') > handler.index("data.ok !== true")
    assert "JSON.stringify({api_key: newApiKey," not in handler


def test_api_key_is_not_persisted_logged_or_put_in_a_url():
    source = spotify_source()
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "console." not in source
    assert "?api_key" not in source
    assert "encodeURIComponent(newApiKey)" not in source
    assert "location" not in source


def test_device_name_uses_exact_get_and_post_contracts():
    source = spotify_source()
    assert 'spotifySettingsRequest("/api/spotify/device-name", {cache: "no-store"})' in source
    start = source.index("deviceSaveBtn.onclick = function()")
    end = source.index("artifactUpdateBtn.onclick = function()", start)
    handler = source[start:end]
    assert 'spotifySettingsRequest("/api/spotify/device-name", {' in handler
    assert 'method: "POST"' in handler
    assert "body: JSON.stringify({device_name: deviceName})" in handler
    assert "api_key" not in handler
    assert ".disable(" not in handler
    assert 'runEndpointControl("disable")' not in handler


def test_device_name_blocked_has_safe_recovery_copy():
    source = spotify_source()
    assert "SPOTIFY_DEVICE_NAME_ERROR_MESSAGES" in source
    assert "spotify_device_name_blocked:" in UI
    assert "Disconnect or disable Spotify before changing the device name." in UI
    assert "deviceInput.maxLength = 256;" in source
    assert "spotifyUtf8ByteLength(deviceName) > 256" in source
    assert "256 UTF-8 bytes or fewer" in source


def test_config_and_device_errors_use_only_bounded_message_maps():
    source = spotify_source()
    assert "SPOTIFY_CONFIG_ERROR_MESSAGES" in source
    assert "SPOTIFY_DEVICE_NAME_ERROR_MESSAGES" in source
    assert "String(data && data.error" in source
    assert "spotifySettingsMessage(data.error" not in source
    assert "throw new Error(data.error" not in source


def test_artifact_update_is_bodyless_and_refreshes_public_status():
    source = spotify_source()
    start = source.index("artifactUpdateBtn.onclick = function()")
    end = source.index("function runEndpointControl", start)
    handler = source[start:end]
    assert 'spotifySettingsRequest("/api/spotify/artifact/update", {' in handler
    assert 'method: "POST"' in handler
    assert "body:" not in handler
    assert "}, 65000)" in handler
    assert "refreshArtifactStatus()" in handler
    assert "checkSpotifySoloistUpdate()" in handler
    assert "syncUpdateIndicators();" in handler


def test_all_artifact_success_actions_have_bounded_messages():
    source = spotify_source()
    assert 'installed: "Soloist installed."' in source
    assert 'updated: "Soloist updated."' in source
    assert 'unchanged: "Soloist is already up to date."' in source
    assert "successMessages[data.action]" in source


def test_all_bounded_artifact_update_errors_are_translated():
    expected = {
        "unsupported_architecture",
        "unsafe_install_directory",
        "download_failed",
        "unexpected_response",
        "download_too_large",
        "invalid_archive",
        "invalid_candidate",
        "candidate_expired",
        "downgrade_rejected",
        "same_build_conflict",
        "commit_failed",
    }
    mapping = UI[
        UI.index("var SPOTIFY_ARTIFACT_ERROR_MESSAGES"):
        UI.index("var SPOTIFY_ARTIFACT_STATUS_MESSAGES")
    ]
    assert expected == set(re.findall(r"^\s{4}([a-z_]+):", mapping, re.MULTILINE))
    assert "data.error_code" in spotify_source()
    assert "JSON.stringify(data)" not in spotify_source()


def test_artifact_display_uses_only_public_nonprivate_fields():
    source = spotify_source()
    render_start = source.index("function renderArtifact")
    render_end = source.index("function refreshArtifactStatus", render_start)
    render = source[render_start:render_end]
    for public_field in (
        "installed",
        "valid",
        "version",
        "architecture",
        "build_date",
        "expires_at",
        "expired",
        "error_code",
    ):
        assert f"spotifyArtifact.{public_field}" in render
    for private_field in (
        "sha256",
        "archive_sha256",
        "binary_sha256",
        "filesystem_path",
        "download_url",
        "build_identifier",
    ):
        assert private_field not in render


def test_enable_disable_use_exact_post_routes_and_check_payload_ok():
    source = spotify_source()
    control = source[source.index("function runEndpointControl"):]
    assert '"/api/spotify/enable"' in control
    assert '"/api/spotify/disable"' in control
    assert 'method: "POST"' in control
    assert "data.ok !== true" in control
    assert 'spotifyStatus && spotifyStatus.enabled === true' in control
    assert 'enabled ? "disable" : "enable"' in control


def test_all_backend_lifecycle_states_have_presentations():
    expected = {
        "disabled",
        "standby",
        "acquiring",
        "owned",
        "releasing",
        "recovering",
        "safe_error",
        "unsafe_error",
    }
    mapping = UI[
        UI.index("var SPOTIFY_SETTINGS_STATE_LABELS"):
        UI.index("var SPOTIFY_ARTIFACT_ERROR_MESSAGES")
    ]
    assert expected == set(re.findall(r"^\s{4}([a-z_]+):", mapping, re.MULTILINE))


def test_spotify_red_dot_requires_installed_and_update_available():
    authority = function_source("spotifySoloistUpdateAvailableNow")
    assert "spotifySoloistUpdateState.installed === true" in authority
    assert "spotifySoloistUpdateState.update_available === true" in authority
    sync = function_source("syncUpdateIndicators")
    assert "var available = srovaAvailable || soloistAvailable;" in sync
    assert 'kind === "about" ? !srovaAvailable : !soloistAvailable' in sync
    assert "SROVA and Spotify/Soloist updates available" in sync
    assert "Spotify/Soloist update available" in sync


def test_only_about_and_spotify_tabs_receive_existing_red_dot_asset():
    tabs = function_source("buildSettingsTabs")
    assert 'tabDef.id === "about" || tabDef.id === "spotify"' in tabs
    assert 'dot.src = "/ui_web/assets/srova-red-update-dot.png";' in tabs
    assert 'dot.setAttribute("data-update-kind", tabDef.id);' in tabs
    assert UI.count('dot.src = "/ui_web/assets/srova-red-update-dot.png";') == 1


def test_enable_is_guarded_by_minimal_visible_setup_state():
    source = spotify_source()
    assert "spotifyStatus.key_configured === true" in source
    assert "spotifyArtifact.installed === true" in source
    assert "spotifyArtifact.valid === true" in source
    assert "spotifyArtifact.expired === false" in source
    assert "spotifyStatus.enabled === true" in source
    assert "(!enabled && (!canEnable || !endpointReady()))" in source


def test_connect_status_uses_existing_gold_toggle_and_no_old_buttons():
    source = spotify_source()
    assert 'controlRow.className = "settingsToggleRow spotifyControlToggleRow";' in source
    assert 'controlToggle.className = "settingsToggleSwitch spotifyControlToggle";' in source
    assert 'controlKnob = document.createElement("span")' in source
    assert "spotifyEnableBtn" not in source
    assert "spotifyDisableBtn" not in source
    assert 'textContent = "Enable"' not in source
    assert 'textContent = "Disable"' not in source


def test_stacked_sections_have_approved_order_and_no_quadrant_grid():
    source = spotify_source()
    ordered = [
        "stack.appendChild(artifactCard);",
        "stack.appendChild(keyCard);",
        "stack.appendChild(statusCard);",
        "stack.appendChild(deviceCard);",
    ]
    positions = [source.index(item) for item in ordered]
    assert positions == sorted(positions)
    assert 'buildBlock("Soloist installation"' in source
    assert 'buildBlock("API key"' in source
    assert 'buildBlock("Spotify Connect status"' in source
    assert 'buildBlock("Device name"' in source
    assert "spotifySettingsGrid" not in source
    assert "spotifySettingsGrid" not in CSS


def test_soloist_button_labels_and_eligibility_cover_all_states():
    source = spotify_source()
    assert 'artifactUpdateBtn.textContent = notInstalled ? "INSTALL" : "UPDATE";' in source
    assert 'installing ? "INSTALLING…" : "UPDATING…"' in source
    assert "var needsRepair = spotifyArtifact && spotifyArtifact.installed === true" in source
    assert "spotifyArtifact.valid !== true || spotifyArtifact.expired !== false" in source
    assert "(!notInstalled && !needsRepair && !updateAvailable)" in source


def test_no_spotify_playback_now_playing_volume_or_catalog_ui_is_added():
    source = spotify_source()
    for forbidden in (
        "spotifyPlay",
        "spotifyPause",
        "spotifyQueue",
        "spotifyVolume",
        "spotifySearch",
        "spotifyLibrary",
        "nowPlayingView",
        "playerBar",
        "PLAYING FROM",
    ):
        assert forbidden not in source


def test_settings_status_feeds_the_single_global_native_block_authority():
    source = spotify_source()
    assert "spotifyStatus.native_blocked === true" in source
    assert "syncSpotifyNativeBlockedFromStatus(data);" in source
    synchronizer = function_source("syncSpotifyNativeBlockedFromStatus")
    assert 'typeof status.native_blocked !== "boolean"' in synchronizer
    assert "spotifyNativeBlocked = status.native_blocked;" in synchronizer
    assert "spotify_owner" not in synchronizer


def test_product_copy_preserves_external_connect_model():
    source = spotify_source()
    assert "Playback and quality remain controlled from Spotify." in source
    assert "temporarily owns the selected DAC" in source
    assert "native SROVA playback is unavailable" in source
    assert "An API key" in source
    assert "bit-perfect" not in source.lower()
    assert "lossless" not in source.lower()


def test_new_spotify_buttons_are_centered_on_both_axes():
    rule = re.search(
        r"#settingsView \.spotifySettingsAction\s*\{(?P<body>.*?)\n\}",
        CSS,
        re.DOTALL,
    )
    assert rule
    body = rule.group("body")
    assert "display: inline-flex !important;" in body
    assert "align-items: center !important;" in body
    assert "justify-content: center !important;" in body
    assert "text-align: center !important;" in body


def test_spotify_desktop_stack_is_shrink_safe():
    assert "#settingsView .spotifySettingsStack" in CSS
    assert "display: block !important;" in CSS
    assert "#settingsView .spotifySettingsInput" in CSS
    assert "width: 100% !important;" in CSS
    assert "max-width: 100% !important;" in CSS
    assert "overflow-wrap: anywhere !important;" in CSS


def test_spotify_mobile_portrait_layout_stays_stacked_and_contains_actions():
    assert "spotifySettingsGrid" not in CSS
    assert "#settingsView .spotifySettingsStack" in CSS
    assert "@media (max-width: 520px)" in CSS
    assert "flex-direction: column !important;" in CSS
    assert "#settingsView .spotifySettingsAction" in CSS
    assert "width: 100% !important;" in CSS


def test_android_webview_uses_plain_dom_and_explicit_button_centering():
    source = spotify_source()
    assert "async function" not in source
    assert "await " not in source
    assert "?." not in source
    webview = CSS[CSS.rindex("html.srovaAndroidApkWebView #settingsView .spotifySettingsAction"):]
    assert "display: inline-flex !important;" in webview
    assert "align-items: center !important;" in webview
    assert "justify-content: center !important;" in webview


def test_cache_bust_tokens_match_sp3c_asset_changes():
    assert "srova.css?v=" in HTML
    assert "ui.js?v=" in HTML
    assert "_sp3b_spotify_settings_css3" in HTML
    assert "_bf4_spotify_status_sync_js9" in HTML
    assert "_bf4_spotify_dac_guard_js7" not in HTML
    assert "_bf2_spotify_handoff_js6" not in HTML
    assert "_sp3b_spotify_settings_js5" not in HTML
    assert HTML.count("_sp3b_spotify_settings_css3") == 1
    assert HTML.count("_bf4_spotify_status_sync_js9") == 1
    assert "_sp3b_spotify_settings_css2" not in HTML
    assert "_sp3b_spotify_settings_js4" not in HTML

def test_dirty_scope_stays_within_explicitly_authorized_paths():
    completed = subprocess.run(
        [
            "git", "status", "--short",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    changed = {
        line[3:]
        for line in completed.stdout.splitlines()
        if len(line) > 3
    }
    assert changed <= {
        "CHANGELOG.md",
        "src/main_headless.py",
        "src/services/spotify_alsa_pcm_verifier.py",
        "src/services/spotify_endpoint_lifecycle.py",
        "src/services/spotify_orchestrator.py",
        "src/services/spotify_soloist_supervisor.py",
        "src/ui_web/index.html",
        "src/ui_web/srova.css",
        "src/ui_web/ui.js",
        "tests/test_audio_output_recommendations.py",
        "tests/test_first_run_dac_selection_authority.py",
        "tests/test_first_run_onboarding.py",
        "tests/test_spotify_alsa_pcm_verifier.py",
        "tests/test_spotify_coordinator.py",
        "tests/test_spotify_device_name_api.py",
        "tests/test_spotify_enabled_intent.py",
        "tests/test_spotify_endpoint_control.py",
        "tests/test_spotify_endpoint_lifecycle.py",
        "tests/test_spotify_global_native_blocker_ui.py",
        "tests/test_spotify_managed_components.py",
        "tests/test_spotify_orchestrator.py",
        "tests/test_spotify_runtime_components.py",
        "tests/test_spotify_settings_ui.py",
        "tests/test_spotify_soloist_supervisor.py",
        "tests/test_spotify_status_api.py",
        "tests/test_v1_4_point3_mmap_fresh_default.py",
    }


def test_cast_and_remote_application_surfaces_are_unchanged():
    completed = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = set(completed.stdout.splitlines())
    assert not any("cast" in path.lower() for path in changed)
    assert not any(path.startswith("remote/") for path in changed)


# BF4_SPOTIFY_SETTINGS_DAC_ENTRY_GUARD
def test_spotify_settings_entry_requires_present_selected_dac():
    source = function_source("requestSettingsTab")
    tabs = function_source("buildSettingsTabs")

    assert '"/api/audio/output"' in source
    assert "data.output_selected !== true" in source
    assert "data.device_available !== true" in source
    assert "Connect a DAC to enter SPOTIFY Settings." in source
    assert 'setSettingsTab("spotify");' in source
    assert "requestSettingsTab(tabDef.id)" in tabs


def test_spotify_absent_dac_backend_error_has_exact_bounded_copy():
    assert (
        'spotify_dac_unavailable: '
        '"Connect a DAC to enter SPOTIFY Settings."'
    ) in UI
def test_spotify_settings_status_tracks_global_poll_until_standby():
    source = spotify_source()
    poll = function_source("pollSpotifyNativeBlockStatus")

    assert "var spotifySettingsStatusSink = null;" in UI
    assert "spotifySettingsStatusSink = renderStatus;" in source

    assert 'currentSrovaView === "settings"' in poll
    assert 'currentSettingsTab === "spotify"' in poll
    assert 'typeof spotifySettingsStatusSink === "function"' in poll
    assert "spotifySettingsStatusSink(status);" in poll

    mapping = UI[
        UI.index("var SPOTIFY_SETTINGS_STATE_LABELS"):
        UI.index("var SPOTIFY_ARTIFACT_ERROR_MESSAGES")
    ]

    assert 'standby: "Disconnected"' in mapping
    assert 'releasing: "Disconnecting…"' in mapping

    # Standby remains an enabled/discoverable endpoint, not master-disabled.
    assert "SROVA is available in Spotify\'s device picker." in source
