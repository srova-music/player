import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.main_headless as backend


MAIN_PATH = ROOT / "src" / "main_headless.py"
UI_PATH = ROOT / "src" / "ui_web" / "ui.js"
INDEX_PATH = ROOT / "src" / "ui_web" / "index.html"
CSS_PATH = ROOT / "src" / "ui_web" / "srova.css"
SW_PATH = ROOT / "src" / "ui_web" / "sw.js"

MAIN = MAIN_PATH.read_text(encoding="utf-8")
UI = UI_PATH.read_text(encoding="utf-8")
INDEX = INDEX_PATH.read_text(encoding="utf-8")
CSS = CSS_PATH.read_text(encoding="utf-8")
SW = SW_PATH.read_text(encoding="utf-8")

POINT6_CSS_TOKEN = "20260824_v1_4_point6_nas_discovery_modal1"
POINT8_JS_TOKEN = "20260824_v1_4_point8_tidal_library_loading1"


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for background cache worker")


def _inflight_for(resource):
    with backend._CACHE_LOCK:
        return [
            key
            for key in backend._TIDAL_LIBRARY_CACHE_INFLIGHT
            if key[0] == resource
        ]


def _run_simultaneous_starts(resource, fetch_result, request_count=12, **kwargs):
    barrier = threading.Barrier(request_count)
    results = []
    results_lock = threading.Lock()

    def _request():
        barrier.wait(timeout=2.0)
        started = backend._start_tidal_library_cache_worker(
            resource,
            fetch_result,
            **kwargs,
        )
        with results_lock:
            results.append(started)

    requests = [threading.Thread(target=_request) for _ in range(request_count)]
    for request in requests:
        request.start()
    for request in requests:
        request.join(timeout=2.0)
        assert not request.is_alive()
    return results


@pytest.fixture(autouse=True)
def isolated_tidal_library_cache_state():
    with backend._CACHE_LOCK:
        saved_cache = dict(backend._CACHE)
        saved_generations = dict(backend._TIDAL_LIBRARY_CACHE_GENERATIONS)
        saved_inflight = set(backend._TIDAL_LIBRARY_CACHE_INFLIGHT)
        saved_account = backend._TIDAL_LIBRARY_CACHE_ACCOUNT
        backend._CACHE.clear()
        backend._TIDAL_LIBRARY_CACHE_INFLIGHT.clear()
        for resource in backend._TIDAL_LIBRARY_CACHE_RESOURCES:
            backend._TIDAL_LIBRARY_CACHE_GENERATIONS[resource] = 0
        backend._TIDAL_LIBRARY_CACHE_ACCOUNT = (
            backend._TIDAL_LIBRARY_CACHE_ACCOUNT_UNSET
        )

    yield

    _wait_until(lambda: not backend._TIDAL_LIBRARY_CACHE_INFLIGHT)
    with backend._CACHE_LOCK:
        backend._CACHE.clear()
        backend._CACHE.update(saved_cache)
        backend._TIDAL_LIBRARY_CACHE_GENERATIONS.clear()
        backend._TIDAL_LIBRARY_CACHE_GENERATIONS.update(saved_generations)
        backend._TIDAL_LIBRARY_CACHE_INFLIGHT.clear()
        backend._TIDAL_LIBRARY_CACHE_INFLIGHT.update(saved_inflight)
        backend._TIDAL_LIBRARY_CACHE_ACCOUNT = saved_account


@pytest.mark.parametrize("resource", ["mysongs", "myalbums", "myplaylists"])
def test_simultaneous_resource_misses_start_exactly_one_worker(resource):
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def _fetch():
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=2.0)
        return [{"id": resource + "-1"}]

    starts = _run_simultaneous_starts(resource, _fetch)
    assert entered.wait(timeout=2.0)
    assert starts.count(True) == 1
    assert starts.count(False) == 11
    assert calls == 1
    assert len(_inflight_for(resource)) == 1

    release.set()
    _wait_until(lambda: backend.cache_get(resource) is not None)


def test_different_resources_run_independently_without_global_serialization():
    releases = {resource: threading.Event() for resource in backend._TIDAL_LIBRARY_CACHE_RESOURCES}
    entered = {resource: threading.Event() for resource in backend._TIDAL_LIBRARY_CACHE_RESOURCES}

    def _fetch_for(resource):
        def _fetch():
            entered[resource].set()
            assert releases[resource].wait(timeout=2.0)
            return [{"id": resource}]

        return _fetch

    for resource in backend._TIDAL_LIBRARY_CACHE_RESOURCES:
        assert backend._start_tidal_library_cache_worker(
            resource,
            _fetch_for(resource),
        )

    assert all(event.wait(timeout=2.0) for event in entered.values())
    with backend._CACHE_LOCK:
        assert len(backend._TIDAL_LIBRARY_CACHE_INFLIGHT) == 3

    for event in releases.values():
        event.set()
    _wait_until(lambda: not backend._TIDAL_LIBRARY_CACHE_INFLIGHT)


def test_worker_exception_clears_inflight_and_allows_retry():
    def _fail():
        raise RuntimeError("expected test worker failure")

    assert backend._start_tidal_library_cache_worker("mysongs", _fail)
    _wait_until(lambda: not _inflight_for("mysongs"))
    assert backend.cache_get("mysongs") is None

    assert backend._start_tidal_library_cache_worker(
        "mysongs",
        lambda: [{"id": "retry-track"}],
    )
    _wait_until(lambda: backend.cache_get("mysongs") is not None)
    assert backend.cache_get("mysongs") == [{"id": "retry-track"}]


def test_completion_clears_inflight_atomically_and_warm_hit_starts_no_worker():
    calls = 0

    def _fetch():
        nonlocal calls
        calls += 1
        return [{"id": "album-1"}]

    assert backend._start_tidal_library_cache_worker("myalbums", _fetch)
    _wait_until(lambda: backend.cache_get("myalbums") is not None)
    assert not _inflight_for("myalbums")
    assert not backend._start_tidal_library_cache_worker("myalbums", _fetch)
    assert calls == 1


def test_invalidation_during_work_allows_fresh_generation_and_blocks_stale_publish():
    old_entered = threading.Event()
    old_release = threading.Event()

    def _old_fetch():
        old_entered.set()
        assert old_release.wait(timeout=2.0)
        return [{"id": "stale"}]

    assert backend._start_tidal_library_cache_worker("myplaylists", _old_fetch)
    assert old_entered.wait(timeout=2.0)
    backend.cache_invalidate("myplaylists")

    assert backend._start_tidal_library_cache_worker(
        "myplaylists",
        lambda: [{"id": "fresh"}],
        publish_empty=True,
    )
    _wait_until(lambda: backend.cache_get("myplaylists") is not None)
    assert backend.cache_get("myplaylists") == [{"id": "fresh"}]

    old_release.set()
    _wait_until(lambda: not backend._TIDAL_LIBRARY_CACHE_INFLIGHT)
    assert backend.cache_get("myplaylists") == [{"id": "fresh"}]


def test_logout_and_login_generation_changes_block_old_account_publication():
    entered = threading.Event()
    release = threading.Event()

    def _old_account_fetch():
        entered.set()
        assert release.wait(timeout=2.0)
        return [{"id": "old-account-track"}]

    assert backend._start_tidal_library_cache_worker("mysongs", _old_account_fetch)
    assert entered.wait(timeout=2.0)
    backend.cache_invalidate()  # logout
    backend.cache_invalidate()  # login
    assert backend._start_tidal_library_cache_worker(
        "mysongs",
        lambda: [{"id": "new-account-track"}],
    )
    _wait_until(lambda: backend.cache_get("mysongs") is not None)
    release.set()
    _wait_until(lambda: not backend._TIDAL_LIBRARY_CACHE_INFLIGHT)
    assert backend.cache_get("mysongs") == [{"id": "new-account-track"}]


def test_recovered_account_identity_change_supersedes_old_work():
    account_backend = SimpleNamespace(
        user=SimpleNamespace(id="account-a"),
        session=None,
    )
    assert backend._sync_tidal_library_cache_account(account_backend) is False

    entered = threading.Event()
    release = threading.Event()

    def _fetch():
        entered.set()
        assert release.wait(timeout=2.0)
        return [{"id": "account-a-album"}]

    assert backend._start_tidal_library_cache_worker(
        "myalbums",
        _fetch,
        account_backend=account_backend,
    )
    assert entered.wait(timeout=2.0)
    account_backend.user = SimpleNamespace(id="account-b")
    release.set()
    _wait_until(lambda: not backend._TIDAL_LIBRARY_CACHE_INFLIGHT)
    assert backend.cache_get("myalbums") is None
    assert backend._sync_tidal_library_cache_account(account_backend) is True


@pytest.mark.parametrize("resource", ["mysongs", "myalbums", "myplaylists"])
def test_relevant_mutation_invalidation_supersedes_old_work(resource):
    entered = threading.Event()
    release = threading.Event()

    def _fetch():
        entered.set()
        assert release.wait(timeout=2.0)
        return [{"id": "pre-mutation"}]

    assert backend._start_tidal_library_cache_worker(resource, _fetch)
    assert entered.wait(timeout=2.0)
    generation = backend._TIDAL_LIBRARY_CACHE_GENERATIONS[resource]
    backend.cache_invalidate(resource)
    assert backend._TIDAL_LIBRARY_CACHE_GENERATIONS[resource] == generation + 1
    release.set()
    _wait_until(lambda: not backend._TIDAL_LIBRARY_CACHE_INFLIGHT)
    assert backend.cache_get(resource) is None


@pytest.mark.parametrize(
    ("resource", "publish_empty"),
    [("mysongs", False), ("myalbums", False), ("myplaylists", True)],
)
def test_empty_results_never_create_overlapping_workers(resource, publish_empty):
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def _empty_fetch():
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=2.0)
        return []

    assert backend._start_tidal_library_cache_worker(
        resource,
        _empty_fetch,
        publish_empty=publish_empty,
    )
    assert entered.wait(timeout=2.0)
    for _ in range(20):
        assert not backend._start_tidal_library_cache_worker(
            resource,
            _empty_fetch,
            publish_empty=publish_empty,
        )
    assert calls == 1
    release.set()
    _wait_until(lambda: not _inflight_for(resource))

    if publish_empty:
        assert backend.cache_get(resource) == []
        assert not backend._start_tidal_library_cache_worker(
            resource,
            _empty_fetch,
            publish_empty=True,
        )


def test_endpoints_use_coordinator_and_preserve_limits_order_and_transformations():
    playlists = MAIN[MAIN.index('if self.path == "/tidal/myplaylists":'):MAIN.index(
        "# -- Playlists: find duplicates"
    )]
    albums = MAIN[MAIN.index('if self.path == "/tidal/myalbums":'):MAIN.index(
        "# -- My Songs"
    )]
    songs = MAIN[MAIN.index('if self.path == "/tidal/mysongs":'):MAIN.index(
        "# -- Home page"
    )]

    for resource, block in (
        ("myplaylists", playlists),
        ("myalbums", albums),
        ("mysongs", songs),
    ):
        assert f'"{resource}",\n' in block
        assert "_start_tidal_library_cache_worker(" in block
        assert "account_backend=backend" in block
        assert "threading.Thread(" not in block
        assert "_sync_tidal_library_cache_account(backend)" in block

    assert "backend.get_recent_albums(limit=2000)" in albums
    assert "backend.get_favorite_tracks(limit=500)" in songs
    for block in (albums, songs):
        assert 'getattr(a, "user_date_added", None)' in block or (
            'getattr(t, "user_date_added", None)' in block
        )
        assert "reverse=True" in block
        assert '"id":' in block
        assert '"name":' in block
        assert '"sub_title":' in block
        assert '"image_url":' in block
        assert '"quality":' in block
    assert '"type":      "Album"' in albums
    assert '"type":      "Track"' in songs
    assert '"duration":' in songs


def test_complete_playlist_cursor_pagination_and_publication_contract_is_preserved():
    block = MAIN[MAIN.index('if self.path == "/tidal/myplaylists":'):MAIN.index(
        "# -- Playlists: find duplicates"
    )]
    for contract in (
        "limit    = 50",
        '"includeOnly":    "PLAYLIST"',
        '"order":          "NAME"',
        '"orderDirection": "ASC"',
        'params["cursor"] = cursor',
        'params["offset"] = 0',
        "if len(items) < limit:",
        "if total > 0 and len(result) >= total:",
        '"id":           pid',
        '"name":         name',
        '"num_tracks":   num_tracks',
        '"last_updated": last_updated',
        '"created_at":   created_at',
        "publish_empty=True",
    ):
        assert contract in block
    assert block.index("while True:") < block.index("return result")
    assert "cache_set(" not in block
    assert "_send_json(result)" not in block
    assert "return _TIDAL_LIBRARY_CACHE_NO_PUBLISH" in block


def test_login_logout_and_all_relevant_mutation_routes_advance_generations():
    assert MAIN.count("cache_invalidate()") >= 3
    assert 'cache_invalidate("mysongs")' in MAIN
    assert 'cache_invalidate("myalbums")' in MAIN

    for route in (
        "/tidal/playlist/create_from_queue",
        "/tidal/playlist/create",
        "/tidal/playlist/add_tracks",
        "/tidal/playlist/remove_tracks",
        "/tidal/playlist/rename",
        "/tidal/playlist/delete",
        "/tidal/playlist/create_from_tracks",
        "/tidal/playlists/delete_duplicates",
        "/api/automix/create",
    ):
        start = MAIN.index(f'self.path == "{route}"')
        next_route = MAIN.find("\n        if self.path", start + 1)
        block = MAIN[start:next_route if next_route >= 0 else len(MAIN)]
        assert 'cache_invalidate("myplaylists")' in block, route


def _playlist_loader_source():
    start = UI.index("var tidalLibraryUiGeneration = 0;")
    end = UI.index("function onPlaylistFilter", start)
    return UI[start:end]


def _run_playlist_loader_node(responses, run_all_timers=False):
    script = r'''
var playlistsContent = {innerHTML: ""};
var playlistsLoaded = false;
var rendered = [];
var timers = [];
var fetchCount = 0;
var responseQueue = RESPONSES;
function fetch() {
    var data = responseQueue.length ? responseQueue.shift() : [];
    fetchCount += 1;
    return Promise.resolve({json: function() { return Promise.resolve(data); }});
}
function setTimeout(callback, delay) {
    timers.push({callback: callback, delay: delay});
    return timers.length;
}
function renderPlaylistsList(items) { rendered.push(items); }
function renderPlaylistsState(target, mode, message) {
    target.innerHTML =
        '<div class="playlistsState" data-state="' +
        mode +
        '">' +
        message +
        '</div>';
}
SOURCE
function flush() { return new Promise(function(resolve) { setImmediate(resolve); }); }
(async function() {
    loadMyPlaylists(0);
    await flush();
    var first = {
        delay: timers.length ? timers[0].delay : null,
        renders: rendered.length,
        html: playlistsContent.innerHTML
    };
    if (RUN_ALL) {
        var guard = 0;
        while (timers.length) {
            var timer = timers.shift();
            timer.callback();
            await flush();
            guard += 1;
            if (guard > 130) { throw new Error("playlist retry did not remain bounded"); }
        }
    } else {
        timers.shift().callback();
        await flush();
    }
    process.stdout.write(JSON.stringify({
        first: first,
        fetchCount: fetchCount,
        renders: rendered,
        timersRemaining: timers.length,
        html: playlistsContent.innerHTML
    }));
}()).catch(function(error) {
    process.stderr.write(String(error && error.stack || error));
    process.exit(1);
});
'''
    script = script.replace("RESPONSES", json.dumps(responses), 1)
    script = script.replace("SOURCE", _playlist_loader_source(), 1)
    script = script.replace("RUN_ALL", "true" if run_all_timers else "false", 1)
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_frontend_retries_at_1_5_seconds_and_renders_complete_next_poll():
    complete = [
        {"id": "playlist-1", "name": "First"},
        {"id": "playlist-2", "name": "Second"},
    ]
    state = _run_playlist_loader_node([[], complete])
    assert state["first"]["delay"] == 1500
    assert state["first"]["renders"] == 0
    assert state["renders"] == [complete]
    assert state["fetchCount"] == 2
    assert state["timersRemaining"] == 0


def test_frontend_empty_loading_is_bounded_to_the_preserved_180_seconds():
    state = _run_playlist_loader_node([], run_all_timers=True)
    assert state["first"]["delay"] == 1500
    assert state["fetchCount"] == 121
    assert state["renders"] == []
    assert state["timersRemaining"] == 0
    assert "No playlists found." in state["html"]
    assert "var MY_PLAYLISTS_MAX_RETRIES = 120;" in UI
    assert 120 * 1500 == 12 * 15000


def test_frontend_account_generation_rejects_late_library_responses():
    update_login = UI[UI.index("function updateLoginBtn"):UI.index(
        "function handleLoginLogout"
    )]
    home = UI[UI.index("function showTidalSource(opts)"):UI.index(
        "function attachTidalSourceSearch", UI.index("function showTidalSource(opts)")
    )]
    albums = UI[UI.index("function showMyAlbums()"):UI.index("// --- My Songs")]
    songs = UI[UI.index("function showMySongs()"):UI.index("function renderLibraryGrid")]

    assert "tidalLibraryUiGeneration += 1;" in update_login
    assert "window._mySongsData = [];" in update_login
    assert "window._myAlbumsData = [];" in update_login
    assert "allPlaylists = [];" in update_login
    assert home.count("libraryGeneration === tidalLibraryUiGeneration") == 2
    assert "libraryGeneration !== tidalLibraryUiGeneration" in albums
    assert "libraryGeneration !== tidalLibraryUiGeneration" in songs
    assert "libraryGeneration !== tidalLibraryUiGeneration" in _playlist_loader_source()


def test_point8_asset_tokens_are_preserved_or_advanced_once_without_sw_change():
    js_marker = "/ui_web/ui.js?v="
    css_marker = "/ui_web/srova.css?v="
    js_token = INDEX.split(js_marker, 1)[1].split('"', 1)[0]
    css_token = INDEX.split(css_marker, 1)[1].split('"', 1)[0]

    # Later release streams legitimately replace historical cache tokens.
    # Point 8 therefore protects singleton cache-busted references and
    # service-worker isolation; the active feature test owns the exact
    # current token suffix.
    assert INDEX.count(js_marker) == 1
    assert INDEX.count(css_marker) == 1
    assert js_token
    assert css_token
    assert not any(ch.isspace() for ch in js_token)
    assert not any(ch.isspace() for ch in css_token)

    assert POINT8_JS_TOKEN not in CSS
    assert 'const CACHE_NAME = "srova-shell-v3";' in SW
    assert POINT8_JS_TOKEN not in SW
