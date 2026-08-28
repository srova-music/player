from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "src" / "ui_web" / "ui.js"
CSS_PATH = ROOT / "src" / "ui_web" / "srova.css"
INDEX_PATH = ROOT / "src" / "ui_web" / "index.html"

UI = UI_PATH.read_text(encoding="utf-8")
CSS = CSS_PATH.read_text(encoding="utf-8")
INDEX = INDEX_PATH.read_text(encoding="utf-8")

POINT6_TOKEN = "20260824_v1_4_point6_nas_discovery_modal1"
JAVASCRIPT_TOKEN = "20260824_v1_4_point8_tidal_library_loading1"


def modal_source():
    start = UI.index("function openNetworkShareDiscoveryModal")
    end = UI.index("function openLocalLibraryCleanupConfirm", start)
    return UI[start:end]


def test_scan_presentation_is_explicit_and_accessible():
    modal = modal_source()

    assert 'modal.setAttribute("aria-labelledby", "networkShareDiscoveryTitle")' in modal
    assert 'title.id = "networkShareDiscoveryTitle"' in modal
    assert 'status.setAttribute("role", "status")' in modal
    assert 'status.setAttribute("aria-live", "polite")' in modal
    assert 'status.setAttribute("aria-atomic", "true")' in modal
    assert '"Scanning for NAS and network shares…"' in modal
    assert (
        '"Checking NFS and SMB services on your local network. '
        'This may take a few seconds."'
    ) in modal


def test_active_state_is_applied_synchronously_before_discovery_fetch():
    modal = modal_source()
    discover = modal[modal.index("function discover(refresh)"):]

    active = discover.index("setDiscoveryActive(true);")
    request = discover.index('fetchJson("/api/local/library/network/discover"')
    assert active < request
    assert 'status.setAttribute("aria-busy", isActive ? "true" : "false")' in modal


def test_latest_discovery_request_wins_and_dismissal_invalidates_callbacks():
    modal = modal_source()

    assert "var discoveryRequestSerial = 0;" in modal
    assert "var dismissed = false;" in modal
    assert "var requestId = ++discoveryRequestSerial;" in modal
    assert "return !dismissed && requestId === discoveryRequestSerial;" in modal
    assert modal.count("if (!discoveryRequestIsCurrent(requestId)) { return; }") == 2
    close = modal[modal.index("function closeModal"):modal.index("function onKeyDown")]
    assert "dismissed = true;" in close
    assert "discoveryRequestSerial += 1;" in close
    assert "setDiscoveryActive(false);" in close


def test_success_empty_failure_and_rejection_end_active_state():
    modal = modal_source()

    assert '"Scan complete — " + servers.length + " network server(s) found."' in modal
    assert '"Scan complete — no NFS or SMB servers found."' in modal
    assert "function renderDiscoveryFailure(message)" in modal
    assert 'addText(serverList, "networkShareEmpty", "Network-share discovery did not complete.")' in modal
    assert modal.count("setDiscoveryActive(false);") >= 3
    assert '.catch(function() {' in modal


def test_refresh_stays_available_and_existing_discovery_semantics_are_preserved():
    modal = modal_source()

    assert 'refreshBtn.onclick = function() { discover(true); loadMounts(); };' in modal
    assert 'fetchJson("/api/local/library/network/discover" + (refresh ? "?refresh=1" : ""))' in modal
    assert "refreshBtn.disabled" not in modal


def test_share_management_contracts_remain_present():
    modal = modal_source()

    for contract in (
        "function renderAuth",
        "function renderShares",
        "function renderConnect",
        "function listShares",
        'fetchJson("/api/local/library/network/shares"',
        'connectButton.textContent = "Connect & Add"',
        'fetchJson("/api/local/library/network/connect"',
        "function disconnectMount",
        'fetchJson("/api/local/library/network/disconnect"',
        "options.addNetworkPath",
        "options.removeNetworkPath",
        "options.reloadStatus",
    ):
        assert contract in modal


def test_activity_rail_is_gold_only_and_reduced_motion_safe():
    start = CSS.index(".networkShareStatusActivity {")
    end = CSS.index(".networkShareServerList", start)
    activity_css = CSS[start:end]

    assert "networkShareStatusSweep 1.6s ease-in-out infinite" in activity_css
    assert "rgba(201, 168, 76" in activity_css
    assert "#F0D27A" in activity_css
    assert "00BFFF" not in activity_css
    assert "srova-cyan" not in activity_css
    assert "@media (prefers-reduced-motion: reduce)" in activity_css
    assert "animation: none !important;" in activity_css
    assert "pointer-events: none !important;" in activity_css


def test_status_hierarchy_is_larger_than_generic_settings_status():
    status_start = CSS.index(".networkShareStatusPrimary {")
    status_end = CSS.index(".networkShareStatusActive .networkShareStatusPrimary", status_start)
    primary_css = CSS[status_start:status_end]

    assert "font-size: 16px !important;" in primary_css
    assert "font-weight: 400 !important;" in primary_css


def test_button_optical_correction_is_modal_local():
    modal_button_start = CSS.index(".networkShareCard .settingsBtn {")
    modal_button_end = CSS.index("}", modal_button_start)
    modal_button_css = CSS[modal_button_start:modal_button_end]

    assert "min-height: 44px !important;" in modal_button_css
    assert "padding-top: 12px !important;" in modal_button_css
    assert "padding-bottom: 8px !important;" in modal_button_css

    global_start = CSS.index("\n.settingsBtn {") + 1
    global_end = CSS.index("}", global_start)
    global_button_css = CSS[global_start:global_end]
    assert "padding: 10px 22px !important;" in global_button_css
    assert "min-height: 44px" not in global_button_css
    assert modal_button_start > CSS.index("SROVA POINT 2 -- BOXED TEXT OPTICAL CENTERING")


def test_share_selection_grid_centring_is_preserved():
    rows_start = CSS.index(".networkShareServerRow,")
    rows_end = CSS.index("}", rows_start)
    row_group_css = CSS[rows_start:rows_end]

    assert "align-items: center !important;" in row_group_css
    assert ".networkShareShareRow" in row_group_css


def test_css_and_javascript_cache_tokens_advance_exactly_once():
    assert INDEX.count('/ui_web/srova.css?v=20260828_v1_4_release1') == 1
    assert INDEX.count('/ui_web/ui.js?v=20260828_v1_4_release1') == 1
    assert INDEX.count("/ui_web/srova.css?v=") == 1
    assert INDEX.count("/ui_web/ui.js?v=") == 1
