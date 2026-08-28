import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "src" / "ui_web" / "ui.js"
INDEX_PATH = ROOT / "src" / "ui_web" / "index.html"
UI = UI_PATH.read_text(encoding="utf-8")
INDEX = INDEX_PATH.read_text(encoding="utf-8")


def function_source(name):
    marker = f"function {name}("
    start = UI.index(marker)
    cursor = UI.index("{", start)
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


RADIO_FUNCTIONS = "\n".join(
    function_source(name)
    for name in (
        "radioStationSignature",
        "supersedeRadioSourcePreparation",
        "invalidateRadioSourceCache",
        "refreshRadioSourceCache",
        "waitForRadioSourceImageLoad",
        "prepareRadioSourceImage",
        "prepareRadioSourceImages",
        "radioSourcePreparationResult",
        "radioSourcePreparationResultIsCurrent",
        "consumeRadioSourcePreparation",
        "attachPreparedRadioSource",
        "startRadioSourcePreparation",
        "prepareRadioSourceAfterVisibilityResume",
        "retireCompletedRadioSourcePreparationAfterHide",
        "radioStationItems",
        "showRadioSource",
    )
)


HARNESS = r"""
const assert = require("assert");

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise(function(onResolve, onReject) {
        resolve = onResolve;
        reject = onReject;
    });
    return {promise: promise, resolve: resolve, reject: reject};
}

async function flush(count) {
    for (let i = 0; i < (count || 8); i += 1) {
        await Promise.resolve();
    }
}

let timerId = 1;
let timers = [];
const window = {
    setTimeout: function(callback, delay) {
        const timer = {id: timerId++, callback: callback, delay: delay, cancelled: false};
        timers.push(timer);
        return timer.id;
    },
    clearTimeout: function(id) {
        timers.forEach(function(timer) {
            if (timer.id === id) { timer.cancelled = true; }
        });
    }
};

function runDeadline() {
    const timer = timers.find(function(item) { return !item.cancelled; });
    assert.ok(timer, "expected an active deadline");
    timer.cancelled = true;
    timer.callback();
    return timer.delay;
}

function makeImage(src, mode) {
    const listeners = {load: [], error: []};
    const decodeDeferred = deferred();
    const image = {
        _src: String(src || ""),
        srcAssignments: 0,
        decodeCalls: 0,
        complete: mode === "resolved" || mode === "reject",
        addEventListener: function(type, callback) { listeners[type].push(callback); },
        removeEventListener: function(type, callback) {
            listeners[type] = listeners[type].filter(function(item) { return item !== callback; });
        },
        fire: function(type) {
            this.complete = true;
            listeners[type].slice().forEach(function(callback) { callback(); });
        },
        resolveDecode: function() {
            this.complete = true;
            decodeDeferred.resolve();
        }
    };
    Object.defineProperty(image, "src", {
        get: function() { return image._src; },
        set: function(value) {
            image._src = String(value || "");
            image.srcAssignments += 1;
        }
    });
    if (mode !== "missing") {
        image.decode = function() {
            image.decodeCalls += 1;
            if (mode === "resolved") { return Promise.resolve(); }
            if (mode === "reject") { return Promise.reject(new Error("decode failed")); }
            return decodeDeferred.promise;
        };
    }
    return image;
}

let shellNumber = 0;
let replacementModes = [];
function makeShell(name, stations, modes) {
    modes = modes || [];
    const images = (stations || []).map(function(station, index) {
        return makeImage(station.icon || "", modes[index] || "pending");
    });
    return {
        name: name,
        parentNode: null,
        stations: stations || [],
        images: images,
        querySelectorAll: function(selector) {
            assert.strictEqual(selector, '.album[data-type="radio"] img');
            return images;
        }
    };
}

function buildRadioSourceShellFromStations(stations) {
    shellNumber += 1;
    return makeShell("replacement-" + shellNumber, stations, replacementModes);
}

let appendNames = [];
let currentChild = null;
const homeSections = {
    appendChild: function(child) {
        currentChild = child;
        child.parentNode = homeSections;
        appendNames.push(child.name);
    }
};
Object.defineProperty(homeSections, "innerHTML", {
    set: function(_value) {
        if (currentChild) { currentChild.parentNode = null; }
        currentChild = null;
    },
    get: function() { return ""; }
});

function installHomeContent() {
    const home = {name: "home-content", parentNode: homeSections};
    currentChild = home;
    appendNames = [];
    return home;
}

let syncCalls = [];
function _syncHomePlayingTiles(shell) { syncCalls.push(shell.name); }

let fetchCalls = 0;
let fetches = [];
function fetch(url) {
    assert.strictEqual(url, "/api/radio/stations");
    fetchCalls += 1;
    const request = deferred();
    fetches.push(request);
    return request.promise.then(function(stations) {
        return {json: function() { return Promise.resolve({stations: stations}); }};
    });
}

function resolveNextFetch(stations) {
    assert.ok(fetches.length, "expected a station request");
    fetches.shift().resolve(stations);
}

const homeView = {style: {display: "block"}};
let currentSourceSection = "";
let onlineSourcesAvailable = true;
let _radioReorderMode = false;
function requireSrovaRadioDac(callback) { callback(); }
function showView(name) { homeView.style.display = name === "home" ? "block" : "none"; }
function setHomeGatewayAppPanel() {}
function setCurrentSourceSection(source) { currentSourceSection = source || ""; }
function setGlobalSearchVisible() {}
function _cancelHomeSlotPolls() {}
function buildSourcePageShell() { throw new Error("unexpected cache-miss shell build"); }
function buildRadioShelf() { throw new Error("unexpected cache-miss shelf build"); }

var RADIO_SOURCE_PREPARE_FAIL_OPEN_MS = 1200;
var _radioSourcePageCache = null;
var _radioSourceStationSignature = "";
var _radioSourceRefreshInFlight = false;
var _radioSourceCacheGeneration = 0;
var _radioSourcePreparationOperation = 0;
var _radioSourcePreparationGeneration = -1;
var _radioSourcePreparationPromise = null;
var _radioSourcePreparationFresh = false;
var _radioSourcePreparationTimedOut = false;
var _radioSourceShowRequest = 0;
var _radioSourcePendingAttachRequest = 0;

function station(id, name, url, icon) {
    return {id: id, name: name, url: url, icon: icon};
}

function installCachedRadio(stations, modes) {
    const shell = makeShell("cached", stations, modes);
    _radioSourcePageCache = shell;
    _radioSourceStationSignature = radioStationSignature(stations);
    _radioSourceCacheGeneration = 7;
    return shell;
}
"""


def run_scenario(body):
    script = (
        HARNESS
        + "\n"
        + RADIO_FUNCTIONS
        + "\n(async function() {\n"
        + body
        + "\n})().catch(function(error) { console.error(error); process.exit(1); });\n"
    )
    subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)


def test_resume_and_rapid_taps_share_hidden_preparation_and_reuse_exact_nodes():
    run_scenario(
        r"""
const stations = [
    station("one", "One", "/stream/one", "/art/one.png"),
    station("two", "Two", "/stream/two", "/art/two.png")
];
const home = installHomeContent();
const shell = installCachedRadio(stations, ["pending", "pending"]);
const originalImages = shell.images.slice();
const preparation = prepareRadioSourceAfterVisibilityResume();
assert.strictEqual(prepareRadioSourceAfterVisibilityResume(), preparation);
assert.strictEqual(fetchCalls, 1);

showRadioSource(false, true);
showRadioSource(false, true);
assert.strictEqual(fetchCalls, 1);
assert.strictEqual(currentChild, home);

resolveNextFetch(stations);
await flush();
assert.strictEqual(currentChild, home);
assert.deepStrictEqual(shell.images.map(function(img) { return img.decodeCalls; }), [1, 1]);
shell.images[0].resolveDecode();
await flush();
assert.strictEqual(currentChild, home);
shell.images[1].resolveDecode();
await preparation;
await flush();

assert.strictEqual(currentChild, shell);
assert.deepStrictEqual(shell.images, originalImages);
assert.deepStrictEqual(shell.images.map(function(img) { return img.srcAssignments; }), [0, 0]);
assert.deepStrictEqual(shell.images.map(function(img) { return img.src; }), ["/art/one.png", "/art/two.png"]);
assert.deepStrictEqual(appendNames, ["cached"]);
assert.deepStrictEqual(syncCalls, ["cached"]);

showRadioSource(false, true);
assert.strictEqual(fetchCalls, 1);
assert.deepStrictEqual(appendNames, ["cached"]);
"""
    )


def test_completed_resume_preparation_is_reused_by_first_entry_without_new_work():
    run_scenario(
        r"""
const stations = [station("one", "One", "/stream", "/art.png")];
const home = installHomeContent();
const shell = installCachedRadio(stations, ["resolved"]);
const preparation = prepareRadioSourceAfterVisibilityResume();
resolveNextFetch(stations);
await preparation;
assert.strictEqual(currentChild, home);
assert.strictEqual(shell.images[0].decodeCalls, 1);

showRadioSource(false, true);
await flush();
assert.strictEqual(fetchCalls, 1);
assert.strictEqual(currentChild, shell);
assert.strictEqual(shell.images[0].srcAssignments, 0);
"""
    )


def test_completed_preparation_retires_on_next_hide_but_inflight_work_is_shared():
    run_scenario(
        r"""
const stations = [station("one", "One", "/stream", "/art.png")];
installHomeContent();
const shell = installCachedRadio(stations, ["resolved"]);
const first = prepareRadioSourceAfterVisibilityResume();
retireCompletedRadioSourcePreparationAfterHide();
assert.strictEqual(prepareRadioSourceAfterVisibilityResume(), first);
assert.strictEqual(fetchCalls, 1);
resolveNextFetch(stations);
await first;
assert.strictEqual(_radioSourcePreparationFresh, true);

const generation = _radioSourceCacheGeneration;
retireCompletedRadioSourcePreparationAfterHide();
assert.strictEqual(_radioSourcePageCache, shell);
assert.strictEqual(_radioSourceCacheGeneration, generation);
const second = prepareRadioSourceAfterVisibilityResume();
assert.notStrictEqual(second, first);
assert.strictEqual(fetchCalls, 2);
resolveNextFetch(stations);
await second;
assert.strictEqual(shell.images[0].decodeCalls, 2);
"""
    )


@pytest.mark.parametrize(
    "mutation",
    ["id", "name", "url", "icon", "order", "add", "delete"],
)
def test_authoritative_station_changes_build_and_atomically_attach_latest_shell(mutation):
    run_scenario(
        f"""
const original = [
    station("one", "One", "/stream/one", "/art/one.png"),
    station("two", "Two", "/stream/two", "/art/two.png")
];
let changed = original.map(function(item) {{ return Object.assign({{}}, item); }});
const mutation = {mutation!r};
if (mutation === "id") {{ changed[0].id = "one-new"; }}
if (mutation === "name") {{ changed[0].name = "One New"; }}
if (mutation === "url") {{ changed[0].url = "/stream/new"; }}
if (mutation === "icon") {{ changed[0].icon = "/art/new.png"; }}
if (mutation === "order") {{ changed.reverse(); }}
if (mutation === "add") {{ changed.push(station("three", "Three", "/stream/three", "/art/three.png")); }}
if (mutation === "delete") {{ changed.pop(); }}

replacementModes = changed.map(function() {{ return "resolved"; }});
const home = installHomeContent();
const oldShell = installCachedRadio(original, ["pending", "pending"]);
showRadioSource(false, true);
assert.strictEqual(currentChild, home);
resolveNextFetch(changed);
await flush(16);

assert.notStrictEqual(_radioSourcePageCache, oldShell);
assert.strictEqual(currentChild, _radioSourcePageCache);
assert.strictEqual(_radioSourcePageCache.name, "replacement-1");
assert.deepStrictEqual(_radioSourcePageCache.stations, changed);
assert.strictEqual(_radioSourceStationSignature, radioStationSignature(changed));
assert.strictEqual(_radioSourceCacheGeneration, 8);
assert.deepStrictEqual(oldShell.images.map(function(img) {{ return img.decodeCalls; }}), [0, 0]);
assert.deepStrictEqual(appendNames, ["replacement-1"]);
"""
    )


def test_decode_rejection_settles_independently_without_rewriting_or_early_attach():
    run_scenario(
        r"""
const stations = [
    station("bad", "Bad", "/bad", "/art/bad.png"),
    station("good", "Good", "/good", "/art/good.png")
];
const home = installHomeContent();
const shell = installCachedRadio(stations, ["reject", "pending"]);
showRadioSource(false, true);
resolveNextFetch(stations);
await flush();
assert.strictEqual(shell.images[0].decodeCalls, 1);
assert.strictEqual(shell.images[1].decodeCalls, 1);
assert.strictEqual(currentChild, home);
shell.images[1].resolveDecode();
await flush(12);
assert.strictEqual(currentChild, shell);
assert.deepStrictEqual(shell.images.map(function(img) { return img.srcAssignments; }), [0, 0]);
"""
    )


def test_missing_decode_uses_load_error_fallback_and_one_failure_does_not_block():
    run_scenario(
        r"""
const stations = [
    station("old", "Old", "/old", "/art/old.png"),
    station("ready", "Ready", "/ready", "/art/ready.png")
];
const home = installHomeContent();
const shell = installCachedRadio(stations, ["missing", "resolved"]);
showRadioSource(false, true);
resolveNextFetch(stations);
await flush();
assert.strictEqual(currentChild, home);
assert.strictEqual(typeof shell.images[0].decode, "undefined");
assert.strictEqual(shell.images[1].decodeCalls, 1);
shell.images[0].fire("error");
await flush(12);
assert.strictEqual(currentChild, shell);
assert.deepStrictEqual(shell.images.map(function(img) { return img.srcAssignments; }), [0, 0]);
"""
    )


def test_fail_open_deadline_bounds_navigation_and_late_decode_does_not_reattach():
    run_scenario(
        r"""
const stations = [station("one", "One", "/stream", "/art.png")];
const home = installHomeContent();
const shell = installCachedRadio(stations, ["pending"]);
showRadioSource(false, true);
resolveNextFetch(stations);
await flush();
assert.strictEqual(currentChild, home);
assert.strictEqual(runDeadline(), 1200);
await flush();
assert.strictEqual(currentChild, shell);
assert.deepStrictEqual(appendNames, ["cached"]);

shell.images[0].resolveDecode();
await flush(16);
assert.strictEqual(currentChild, shell);
assert.deepStrictEqual(appendNames, ["cached"]);
assert.strictEqual(shell.images[0].srcAssignments, 0);
"""
    )


def test_navigation_away_before_completion_never_attaches_radio():
    run_scenario(
        r"""
const stations = [station("one", "One", "/stream", "/art.png")];
const home = installHomeContent();
const shell = installCachedRadio(stations, ["pending"]);
showRadioSource(false, true);
resolveNextFetch(stations);
await flush();
currentSourceSection = "";
shell.images[0].resolveDecode();
await flush(16);
assert.strictEqual(currentChild, home);
assert.deepStrictEqual(appendNames, []);
"""
    )


def test_invalidation_supersedes_stale_fetch_and_decode_callbacks():
    run_scenario(
        r"""
const stations = [station("one", "One", "/stream", "/art.png")];
const home = installHomeContent();
const staleFetchShell = installCachedRadio(stations, ["pending"]);
showRadioSource(false, true);
invalidateRadioSourceCache();
resolveNextFetch(stations);
await flush(16);
assert.strictEqual(currentChild, home);
assert.deepStrictEqual(appendNames, []);
assert.strictEqual(staleFetchShell.images[0].decodeCalls, 0);

const staleDecodeShell = installCachedRadio(stations, ["pending"]);
showRadioSource(false, true);
resolveNextFetch(stations);
await flush();
assert.strictEqual(staleDecodeShell.images[0].decodeCalls, 1);
invalidateRadioSourceCache();
staleDecodeShell.images[0].resolveDecode();
await flush(16);
assert.strictEqual(currentChild, home);
assert.deepStrictEqual(appendNames, []);
"""
    )


def test_visible_radio_resume_replaces_changed_data_only_after_replacement_is_ready():
    run_scenario(
        r"""
const original = [station("one", "One", "/stream", "/art/one.png")];
const changed = [station("one", "One New", "/stream", "/art/two.png")];
replacementModes = ["pending"];
const shell = installCachedRadio(original, ["resolved"]);
homeSections.appendChild(shell);
appendNames = [];
currentSourceSection = "radio";
const preparation = prepareRadioSourceAfterVisibilityResume();
resolveNextFetch(changed);
await flush();
assert.strictEqual(currentChild, shell);
assert.strictEqual(_radioSourcePageCache.name, "replacement-1");
_radioSourcePageCache.images[0].resolveDecode();
await preparation;
await flush();
assert.strictEqual(currentChild, _radioSourcePageCache);
assert.deepStrictEqual(appendNames, ["replacement-1"]);
"""
    )


def test_mapping_generation_visibility_and_existing_radio_contracts_remain_explicit():
    items = function_source("radioStationItems")
    assert "id:        s.id" in items
    assert 'name:      s.name  || ""' in items
    assert 'image_url: s.icon  || ""' in items
    assert 'type:      "radio"' in items
    assert 'url:       s.url   || ""' in items

    visibility = UI[UI.index('document.addEventListener("visibilitychange"'):]
    visibility = visibility[:visibility.index("// --- Session restore")]
    assert 'document.visibilityState === "visible"' in visibility
    assert "prepareRadioSourceAfterVisibilityResume();" in visibility
    assert "retireCompletedRadioSourcePreparationAfterHide();" in visibility
    assert visibility.index("prepareRadioSourceAfterVisibilityResume();") < visibility.index(
        "restoreSession();"
    )

    reorder = UI[UI.index("function enhanceRadioShelfOrdering"):UI.index("function radioStationSignature")]
    assert "_radioSourceCacheGeneration += 1;" in reorder
    assert "supersedeRadioSourcePreparation();" in reorder
    assert reorder.index("_radioSourceCacheGeneration += 1;") < reorder.index(
        "supersedeRadioSourcePreparation();"
    )

    show = function_source("showRadioSource")
    assert "var preparation = startRadioSourcePreparation();" in show
    assert "attachPreparedRadioSource(result, requestId" in show
    assert "homeSections.appendChild(_radioSourcePageCache);" in show
    assert "refreshRadioSourceCache();" in show
    assert "Date.now" not in show

    assert "function playRadioStation(item)" in UI
    assert "function syncRadioPlayingFromStation(station)" in UI
    assert "function radioQueueActionSummary(action, stationName)" in UI


def test_point5_cache_token_has_been_superseded():
    token = "20260823_v1_4_point5_radio_artwork_wake_stability1"
    assert f'/ui_web/ui.js?v={token}' not in INDEX
    assert INDEX.count("/ui_web/ui.js?v=") == 1
    assert "20260823_v1_4_point4_home_artwork_stability1" not in INDEX


def test_fail_open_bound_and_no_artwork_url_mutation_contract():
    assert "var RADIO_SOURCE_PREPARE_FAIL_OPEN_MS = 1200;" in UI
    preparation = function_source("startRadioSourcePreparation")
    assert 'fetch("/api/radio/stations")' in preparation
    assert "RADIO_SOURCE_PREPARE_FAIL_OPEN_MS" in preparation
    assert "Date.now" not in preparation
    assert ".src =" not in preparation
    assert "setAttribute" not in preparation

    image_preparation = function_source("prepareRadioSourceImage")
    assert "img.decode()" in image_preparation
    assert "waitForRadioSourceImageLoad(img)" in image_preparation
    assert ".src =" not in image_preparation
