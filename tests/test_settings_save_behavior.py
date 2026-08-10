from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
HTML = (ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")
BACKEND = (ROOT / "src/main_headless.py").read_text(encoding="utf-8")


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


def test_dac_selection_auto_saves_and_keeps_release_gate():
    source = function_source("buildDacSection")

    assert "Save DAC" not in source
    assert 'driverSelect.addEventListener("change", saveSelectedDac);' in source
    assert 'deviceSelect.addEventListener("change", saveSelectedDac);' in source
    assert 'fetch("/api/audio/output", {' in source
    assert (
        "driverSelect.disabled = locked || dacSaveInFlight || "
        "!hasSelectedDevice;"
    ) in source
    assert (
        "deviceSelect.disabled = locked || dacSaveInFlight || "
        "!hasAvailableDevice;"
    ) in source
    assert "Use Release DAC to stop playback" in source
    assert "DAC saved automatically." in source
    assert 'loadDacUi("DAC was not saved:' in source

    route_start = BACKEND.index('if self.path == "/api/audio/output":', BACKEND.index("def do_POST"))
    route_end = BACKEND.index('if self.path == "/api/settings/tidal-infinite-play":', route_start)
    route = BACKEND[route_start:route_end]
    assert 'if locked.get("dac_locked"):' in route
    assert "_set_audio_output_preference(driver, device, name)" in route


def test_my_music_has_one_ordered_save_and_scan_action():
    source = function_source("buildLocalMusicLibrarySection")
    scan_helper = function_source("startSavedMusicRootsScan")

    assert 'saveBtn.textContent = "Save & Scan";' in source
    assert 'saveBtn.textContent = "Save Folders";' not in source
    assert 'scanBtn.textContent = "Scan Now";' not in source
    assert 'fetch("/api/local/library/scan", {method: "POST"})' in scan_helper

    handler_start = source.index("saveBtn.onclick = function()")
    handler_end = source.index("refreshBtn.onclick", handler_start)
    handler = source[handler_start:handler_end]
    assert 'saveCurrentMusicRoots("Music folders saved. Starting scan...")' in handler
    assert "return startSavedMusicRootsScan();" in handler
    assert handler.index("saveCurrentMusicRoots") < handler.index("startSavedMusicRootsScan")
    assert 'fetch("/api/local/library/scan"' not in handler


def test_my_music_edits_are_explicitly_unsaved_until_save_and_scan():
    source = function_source("buildLocalMusicLibrarySection")
    browser = function_source("openLocalLibraryFolderBrowser")

    assert "function markLocalLibraryRootsUnsaved()" in source
    assert (
        "Folder changes are not saved. Select Save & Scan to accept them."
        in source
    )
    assert 'pathInput.addEventListener("input", markLocalLibraryRootsUnsaved);' in source
    assert "markLocalLibraryRootsUnsaved();" in source
    assert "if (!localLibraryRootsDirty)" in source
    assert (
        '".localLibraryPathInput, .localLibraryBrowseBtn, '
        '.localLibraryRemoveFolderBtn"'
        in source
    )
    assert 'pathInput.dispatchEvent(new Event("input", {bubbles: true}));' in browser


def test_save_and_scan_copy_and_cache_token_are_current():
    assert "Press Scan Now" not in UI
    assert "Press Scan Now" not in BACKEND
    assert (
        "Music folders saved. Select Save & Scan to update the SROVA index."
        in BACKEND
    )
    assert "/ui_web/ui.js?v=20260806_v1_1_about_version1" in HTML
