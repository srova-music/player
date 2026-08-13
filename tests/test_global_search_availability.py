from pathlib import Path
import re
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from local_library import LocalLibraryIndex


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


def insert_track(index, root, track_id):
    path = root / f"{track_id}.flac"
    with index._connect() as con:
        con.execute(
            """
            INSERT INTO local_tracks (
                id, root, path, uri, title, artist, album, duration,
                codec, file_size, mtime, scanned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track_id,
                str(root.resolve()),
                str(path),
                path.as_uri(),
                track_id,
                "Artist",
                "Album",
                60,
                "FLAC",
                1,
                1.0,
                1.0,
            ),
        )


def test_track_count_for_roots_excludes_inactive_indexed_rows(tmp_path):
    active_root = tmp_path / "active"
    inactive_root = tmp_path / "inactive"
    active_root.mkdir()
    inactive_root.mkdir()
    index = LocalLibraryIndex(
        roots=[],
        db_path=str(tmp_path / "state" / "local.sqlite3"),
    )
    insert_track(index, active_root, "active-track")
    insert_track(index, inactive_root, "inactive-track")

    assert index.track_count_for_roots([str(active_root)]) == 1
    assert index.track_count_for_roots([]) == 0


def test_local_search_ready_requires_completed_usable_active_library():
    from src import main_headless as backend

    availability = {
        "configured_roots": ["/music"],
        "active_roots": ["/music"],
        "unavailable_roots": [],
    }
    ready = {
        "ok": True,
        "last_scan_at": 123.0,
        "last_scan_error": None,
        "searchable_track_count": 10,
        "scan_running": True,
        "rebuild_running": False,
        "maintenance_mode": None,
    }

    assert backend._local_library_search_ready(ready, availability)

    for field, value in (
        ("last_scan_at", None),
        ("last_scan_error", "scan failed"),
        ("searchable_track_count", 0),
        ("busy", True),
        ("rebuild_running", True),
        ("maintenance_mode", "local_library_rebuild"),
    ):
        state = dict(ready)
        state[field] = value
        assert not backend._local_library_search_ready(state, availability)

    assert not backend._local_library_search_ready(
        ready,
        {
            "configured_roots": ["/music"],
            "active_roots": [],
            "unavailable_roots": ["/music"],
        },
    )


def test_local_status_exposes_active_root_scoped_search_readiness():
    from src import main_headless as backend

    class FakeIndex:
        def __init__(self, roots):
            assert roots == []

        def status(self):
            return {
                "ok": True,
                "track_count": 25,
                "last_scan_at": 123.0,
                "last_scan_error": None,
                "rebuild_running": False,
                "maintenance_mode": None,
            }

        def track_count_for_roots(self, roots):
            assert roots == ["/music"]
            return 12

    availability = {
        "configured_roots": ["/music", "/offline"],
        "active_roots": ["/music"],
        "unavailable_roots": ["/offline"],
    }
    with mock.patch.object(
        backend,
        "_sync_local_library_artwork_policy",
    ), mock.patch.object(
        backend,
        "_music_root_availability",
        return_value=availability,
    ), mock.patch.object(
        backend,
        "LocalLibraryIndex",
        FakeIndex,
    ):
        result = backend._local_library_status_payload()

    assert result["searchable_track_count"] == 12
    assert result["search_ready"] is True


def test_global_search_starts_hidden_and_refreshes_from_home():
    assert (
        '<div id="searchBox" class="hidden" '
        'style="display:none !important">'
    ) in HTML
    source = function_source("loadHome")
    assert "setGlobalSearchVisible(true);" in source
    assert "refreshGlobalSearchAvailability();" in source


def test_tidal_search_ready_requires_authenticated_online_status():
    source = function_source("applyGlobalSearchTidalStatus")
    assert "data.logged_in === true" in source
    assert "data.tidal_online === true" in source
    assert "data.offline !== true" in source
    assert "onlineSourcesAvailable" in source


def test_global_search_only_queries_ready_sources():
    source = function_source("doSearch")
    assert "if (!globalSearchHasReadySource())" in source
    assert "var localRequest = globalSearchLocalReady" in source
    assert "var tidalRequest = globalSearchTidalReady" in source


def test_global_search_cache_token_updated():
    assert "/ui_web/ui.js?v=20260812_v1_2_queue_drag2" in HTML
