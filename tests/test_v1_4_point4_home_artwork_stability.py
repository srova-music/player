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


HOME_FUNCTIONS = "\n".join(
    function_source(name)
    for name in (
        "inferStatusPlaybackSource",
        "homeHeroNowPlayingParts",
        "deriveHomeHeroNowPlayingModel",
        "setHomeHeroActiveSource",
        "homeHeroArtworkIdentity",
        "isHomeHeroFiniteArtworkSource",
        "applyHomeHeroPresentation",
        "cancelHomeHeroArtworkRequest",
        "applyHomeHeroNowPlayingModel",
    )
)


HARNESS = r"""
const assert = require("assert");
const SROVA_STANDBY_ART = "/ui_web/assets/srova-square-logo.png";
const events = [];
const images = [];
let timers = [];
let nextTimerId = 1;

class FakeClassList {
    constructor(owner) {
        this.owner = owner;
        this.values = new Set();
    }
    add(name) {
        this.values.add(name);
        events.push(["class-add", this.owner, name]);
    }
    remove(name) {
        this.values.delete(name);
        events.push(["class-remove", this.owner, name]);
    }
    toggle(name, force) {
        const enabled = force === undefined ? !this.values.has(name) : !!force;
        if (enabled) { this.values.add(name); } else { this.values.delete(name); }
        events.push(["class-toggle", this.owner, name, enabled]);
        return enabled;
    }
    contains(name) { return this.values.has(name); }
}

function makeElement(id, initialSrc) {
    const element = {
        id: id,
        classList: new FakeClassList(id),
        textContent: "",
        _src: initialSrc || "",
        srcAssignments: 0,
        getAttribute: function(name) {
            if (name === "src") { return this._src; }
            if (name === "data-home-source") { return this.homeSource || ""; }
            return "";
        }
    };
    Object.defineProperty(element, "src", {
        get: function() {
            try { return new URL(this._src || "", document.baseURI).href; }
            catch (e) { return this._src || ""; }
        },
        set: function(value) {
            this._src = String(value || "");
            this.srcAssignments += 1;
            events.push(["src", id, this._src]);
        }
    });
    return element;
}

let gateway;
let logo;
let nowPlaying;
const sourceNodes = ["radio", "local", "tidal"].map(function(source) {
    const node = makeElement("source-" + source);
    node.homeSource = source;
    return node;
});

function replaceHome(initialSrc) {
    gateway = makeElement("srovaGateway");
    logo = makeElement("srovaGatewayLogo", initialSrc || SROVA_STANDBY_ART);
    nowPlaying = makeElement("srovaHomeNowPlaying");
    homeHeroNowPlayingStateKey = "";
}

const document = {
    baseURI: "http://srova.test/",
    getElementById: function(id) {
        if (id === "srovaGateway") { return gateway; }
        if (id === "srovaGatewayLogo") { return logo; }
        if (id === "srovaHomeNowPlaying") { return nowPlaying; }
        return null;
    },
    querySelectorAll: function(selector) {
        return selector === "[data-home-source]" ? sourceNodes : [];
    }
};

const window = {
    setTimeout: function(callback, delay) {
        const timer = {id: nextTimerId++, callback: callback, delay: delay, cancelled: false};
        timers.push(timer);
        events.push(["timer", delay]);
        return timer.id;
    },
    clearTimeout: function(id) {
        timers.forEach(function(timer) {
            if (timer.id === id) { timer.cancelled = true; }
        });
        events.push(["clear-timer", id]);
    }
};

function runNextTimer() {
    while (timers.length) {
        const timer = timers.shift();
        if (!timer.cancelled) {
            timer.callback();
            return timer.delay;
        }
    }
    return null;
}

function runAllTimers() {
    const delays = [];
    let delay;
    while ((delay = runNextTimer()) !== null) { delays.push(delay); }
    return delays;
}

class Image {
    constructor() {
        this.onload = null;
        this.onerror = null;
        this._src = "";
        images.push(this);
        events.push(["image-new", images.length]);
    }
    set src(value) {
        this._src = String(value || "");
        events.push(["image-src", this._src]);
    }
    get src() { return this._src; }
    fireLoad() {
        const callback = this.onload;
        if (callback) { callback(); }
    }
    fireError() {
        const callback = this.onerror;
        if (callback) { callback(); }
    }
}

var homeHeroNowPlayingStateKey = "";
var homeHeroNowPlayingToken = 0;
var homeHeroArtworkElement = null;
var homeHeroArtworkInitialized = false;
var homeHeroDisplayedArtworkKey = "";
var homeHeroDisplayedArtworkSource = "";
var homeHeroPendingArtworkKey = "";
var homeHeroPendingArtworkSource = "";
var homeHeroArtworkPreload = null;
var homeHeroFadeOutTimer = null;
var homeHeroFadeInTimer = null;

function status(source, overrides) {
    const base = {
        playing: true,
        current_track_valid: true,
        playback_state: "playing",
        source: source,
        current_track_id: source + ":track-1",
        title: "Track One",
        artist: "Artist",
        cover: "/art/album.jpg"
    };
    return Object.assign(base, overrides || {});
}

function applyStatus(value) {
    applyHomeHeroNowPlayingModel(deriveHomeHeroNowPlayingModel(value));
}

function settleLatestImageLoad() {
    assert.ok(images.length, "expected an image preload");
    images[images.length - 1].fireLoad();
    return runAllTimers();
}

function countEvent(type, detail) {
    return events.filter(function(event) {
        return event[0] === type && (detail === undefined || event.indexOf(detail) !== -1);
    }).length;
}

replaceHome(SROVA_STANDBY_ART);
"""


def run_scenario(body):
    script = HARNESS + "\n" + HOME_FUNCTIONS + "\n" + body
    subprocess.run(["node", "-e", script], check=True, text=True, capture_output=True)


@pytest.mark.parametrize("source", ["local", "tidal", "qobuz"])
def test_pause_extended_pause_resume_and_mmap_seek_keep_artwork_stable(source):
    run_scenario(
        f"""
const playingStatus = status({source!r});
applyStatus(playingStatus);
assert.deepStrictEqual(settleLatestImageLoad(), []);
const assignments = logo.srcAssignments;
const preloadCount = images.length;
events.length = 0;

const pausedStatus = status({source!r}, {{
    playing: false,
    playback_state: "paused",
    title: "Paused Metadata",
    position: 80
}});
applyStatus(pausedStatus);
for (let poll = 0; poll < 5; poll += 1) {{ applyStatus(pausedStatus); }}

// Model both directions of mmap Pause/Seek/Resume without introducing any
// seek-specific Home state: only position and the temporary pause change.
applyStatus(status({source!r}, {{
    playing: false,
    playback_state: "paused",
    title: "Paused Metadata",
    position: 140
}}));
applyStatus(status({source!r}, {{title: "Paused Metadata", position: 140}}));
applyStatus(status({source!r}, {{
    playing: false,
    playback_state: "paused",
    title: "Paused Metadata",
    position: 22
}}));
applyStatus(status({source!r}, {{title: "Paused Metadata", position: 22}}));

assert.strictEqual(nowPlaying.textContent, "Paused Metadata - Artist");
assert.strictEqual(logo.srcAssignments, assignments);
assert.strictEqual(images.length, preloadCount);
assert.strictEqual(countEvent("class-add", "srovaHomeHeroSwapping"), 0);
assert.strictEqual(countEvent("timer"), 0);
assert.strictEqual(logo.getAttribute("src"), "/art/album.jpg");
"""
    )


def test_idle_and_cleared_current_item_still_transition_to_hero():
    run_scenario(
        r"""
applyStatus(status("local"));
assert.deepStrictEqual(settleLatestImageLoad(), []);
events.length = 0;

applyStatus({
    playing: false,
    current_track_valid: false,
    playback_state: "idle",
    source: null,
    current_track_id: null,
    cover: null
});

assert.strictEqual(images.length, 2);
images[1].fireLoad();

assert.deepStrictEqual(runAllTimers(), []);
assert.strictEqual(
    gateway.classList.contains("srovaHomeHeroSwapping"),
    false
);
assert.strictEqual(
    logo.getAttribute("src"),
    SROVA_STANDBY_ART
);
assert.strictEqual(nowPlaying.textContent, "");
assert.strictEqual(
    gateway.classList.contains("srovaHomeHeroNowPlaying"),
    false
);
"""
    )


def test_same_album_next_previous_restart_and_relative_absolute_identity_are_metadata_only():
    run_scenario(
        r"""
const relativeCover = "/api/local/library/artwork?p=%2Fmusic%2FAlbum%2Fcover.jpg";
applyStatus(status("local", {cover: relativeCover}));
settleLatestImageLoad();
const assignments = logo.srcAssignments;
const preloadCount = images.length;
events.length = 0;

applyStatus(status("local", {
    current_track_id: "local:track-2",
    title: "Track Two",
    cover: "http://srova.test/api/local/library/artwork?p=%2Fmusic%2FAlbum%2Fcover.jpg"
}));
applyStatus(status("local", {
    current_track_id: "local:track-1",
    title: "Track One",
    cover: relativeCover
}));
applyStatus(status("local", {
    current_track_id: "local:track-1",
    title: "Track One Restarted",
    cover: relativeCover
}));

assert.strictEqual(nowPlaying.textContent, "Track One Restarted - Artist");
assert.strictEqual(logo.srcAssignments, assignments);
assert.strictEqual(images.length, preloadCount);
assert.strictEqual(countEvent("class-add", "srovaHomeHeroSwapping"), 0);
assert.strictEqual(countEvent("timer"), 0);
"""
    )


def test_pending_equivalent_artwork_is_not_preloaded_twice_and_metadata_does_not_wait():
    run_scenario(
        r"""
applyStatus(status("tidal", {
    cover: "https://resources.tidal.com/images/a/320x320.jpg"
}));
assert.deepStrictEqual(settleLatestImageLoad(), []);
events.length = 0;

applyStatus(status("tidal", {
    current_track_id: "tidal:track-2",
    title: "Track Two",
    cover: "https://resources.tidal.com/images/b/320x320.jpg"
}));
assert.strictEqual(images.length, 2);
assert.strictEqual(nowPlaying.textContent, "Track Two - Artist");

applyStatus(status("tidal", {
    current_track_id: "tidal:track-3",
    title: "Track Three",
    cover: "https://resources.tidal.com/images/b/320x320.jpg"
}));
assert.strictEqual(images.length, 2);
assert.strictEqual(nowPlaying.textContent, "Track Three - Artist");
assert.strictEqual(
    countEvent("class-add", "srovaHomeHeroSwapping"),
    0
);
assert.strictEqual(countEvent("timer"), 0);

images[1].fireLoad();

assert.deepStrictEqual(runAllTimers(), []);
assert.strictEqual(
    logo.getAttribute("src"),
    "https://resources.tidal.com/images/b/320x320.jpg"
);
assert.strictEqual(nowPlaying.textContent, "Track Three - Artist");
"""
    )


def test_complete_url_identity_preserves_queries_signatures_cache_tokens_and_local_modes():
    run_scenario(
        r"""
assert.strictEqual(
    homeHeroArtworkIdentity("/art/cover.jpg?token=abc"),
    homeHeroArtworkIdentity("http://srova.test/art/cover.jpg?token=abc")
);
assert.notStrictEqual(
    homeHeroArtworkIdentity("/art/cover.jpg?token=abc"),
    homeHeroArtworkIdentity("/art/cover.jpg?token=def")
);
assert.notStrictEqual(
    homeHeroArtworkIdentity("/art/cover.jpg?v=1"),
    homeHeroArtworkIdentity("/art/cover.jpg?v=2")
);
assert.notStrictEqual(
    homeHeroArtworkIdentity("/api/local/library/artwork?p=%2Fmusic%2Fcover.jpg"),
    homeHeroArtworkIdentity("/api/local/library/artwork?e=%2Fmusic%2Fcover.jpg")
);
assert.notStrictEqual(
    homeHeroArtworkIdentity("https://resources.tidal.com/images/a/320x320.jpg"),
    homeHeroArtworkIdentity("https://resources.tidal.com/images/a/1280x1280.jpg")
);
assert.strictEqual(homeHeroArtworkIdentity("data:image/png;base64,AA=="), "data:image/png;base64,AA==");
assert.strictEqual(homeHeroArtworkIdentity("http://[invalid"), "http://[invalid");
"""
    )


def test_different_artwork_preloads_then_commits_directly_and_latest_failure_falls_back():
    run_scenario(
        r"""
applyStatus(status("local", {cover: "/art/a.jpg"}));
assert.deepStrictEqual(settleLatestImageLoad(), []);
events.length = 0;

applyStatus(status("local", {
    title: "Different",
    cover: "/art/b.jpg?sig=two"
}));
assert.strictEqual(images.length, 2);
assert.strictEqual(countEvent("timer"), 0);

images[1].fireLoad();

assert.strictEqual(
    gateway.classList.contains("srovaHomeHeroSwapping"),
    false
);
assert.deepStrictEqual(runAllTimers(), []);
assert.strictEqual(
    logo.getAttribute("src"),
    "/art/b.jpg?sig=two"
);

applyStatus(status("local", {
    title: "Broken",
    cover: "/art/missing.jpg"
}));
assert.strictEqual(images.length, 3);

images[2].fireError();

assert.deepStrictEqual(runAllTimers(), []);
assert.strictEqual(
    gateway.classList.contains("srovaHomeHeroSwapping"),
    false
);
assert.strictEqual(
    logo.getAttribute("src"),
    SROVA_STANDBY_ART
);
assert.strictEqual(
    nowPlaying.textContent,
    "Broken - Artist"
);
"""
    )


def test_stale_load_error_callbacks_cannot_override_latest_artwork_or_hide_it():
    run_scenario(
        r"""
applyStatus(status("tidal", {cover: "/art/a.jpg"}));
assert.deepStrictEqual(settleLatestImageLoad(), []);
events.length = 0;

applyStatus(status("tidal", {
    title: "B",
    cover: "/art/b.jpg"
}));

const staleLoad = images[1].onload;
const staleError = images[1].onerror;

applyStatus(status("tidal", {
    title: "C",
    cover: "/art/c.jpg"
}));

staleLoad();
staleError();

assert.strictEqual(countEvent("timer"), 0);
assert.strictEqual(
    logo.getAttribute("src"),
    "/art/a.jpg"
);

images[2].fireLoad();

assert.strictEqual(
    logo.getAttribute("src"),
    "/art/c.jpg"
);
assert.strictEqual(countEvent("timer"), 0);
assert.strictEqual(
    gateway.classList.contains("srovaHomeHeroSwapping"),
    false
);

applyStatus(status("tidal", {
    title: "Back to A",
    cover: "/art/a.jpg"
}));

assert.strictEqual(images.length, 4);
assert.strictEqual(
    logo.getAttribute("src"),
    "/art/c.jpg"
);
assert.strictEqual(
    nowPlaying.textContent,
    "Back to A - Artist"
);
assert.strictEqual(countEvent("timer"), 0);

images[3].fireLoad();

assert.strictEqual(
    logo.getAttribute("src"),
    "/art/a.jpg"
);
assert.strictEqual(
    gateway.classList.contains("srovaHomeHeroSwapping"),
    false
);
assert.strictEqual(
    nowPlaying.textContent,
    "Back to A - Artist"
);
"""
    )


def test_initial_hero_and_new_home_dom_do_not_reassign_identical_standby_artwork():
    run_scenario(
        r"""
applyStatus({
    playing: false,
    current_track_valid: false,
    playback_state: "idle"
});

assert.strictEqual(images.length, 0);
assert.strictEqual(
    gateway.classList.contains("srovaHomeHeroSwapping"),
    false
);
assert.deepStrictEqual(runAllTimers(), []);
assert.strictEqual(logo.srcAssignments, 0);

applyStatus(status("local", {
    cover: "/art/media.jpg"
}));

assert.strictEqual(images.length, 1);
images[0].fireLoad();

assert.deepStrictEqual(runAllTimers(), []);
assert.strictEqual(
    logo.getAttribute("src"),
    "/art/media.jpg"
);
assert.strictEqual(
    gateway.classList.contains("srovaHomeHeroSwapping"),
    false
);

replaceHome(SROVA_STANDBY_ART);

applyStatus({
    playing: false,
    current_track_valid: false,
    playback_state: "idle"
});

assert.strictEqual(
    gateway.classList.contains("srovaHomeHeroSwapping"),
    false
);
assert.deepStrictEqual(runAllTimers(), []);
assert.strictEqual(logo.srcAssignments, 0);
"""
    )


def test_radio_selection_and_same_artwork_metadata_update_preserve_artwork_identity():
    run_scenario(
        r"""
const pausedRadio = deriveHomeHeroNowPlayingModel({
    playing: false,
    current_track_valid: true,
    playback_state: "paused",
    source: "radio",
    radio_mode: true,
    radio_station: {
        name: "Station",
        icon: "/radio/station.png"
    }
});

assert.strictEqual(pausedRadio.active, false);
assert.strictEqual(
    pausedRadio.imageUrl,
    SROVA_STANDBY_ART
);

assert.strictEqual(
    deriveHomeHeroNowPlayingModel({
        playing: false,
        current_track_valid: true,
        playback_state: "paused",
        source: "radio",
        radio_mode: false,
        radio_station: null
    }).active,
    false
);

const radioOne = {
    playing: true,
    current_track_valid: true,
    playback_state: "playing",
    source: "radio",
    radio_mode: true,
    radio_station: {
        name: "Station",
        icon: "/radio/station.png"
    },
    radio_metadata: {
        title: "Song One",
        artist: "Artist"
    },
    radio_cover_art_url: "/radio/song.png"
};

applyStatus(radioOne);
assert.deepStrictEqual(settleLatestImageLoad(), []);

const assignments = logo.srcAssignments;
events.length = 0;

applyStatus(Object.assign({}, radioOne, {
    radio_metadata: {
        title: "Song Two",
        artist: "Artist"
    }
}));

assert.strictEqual(images.length, 1);
assert.strictEqual(
    gateway.classList.contains("srovaHomeHeroSwapping"),
    false
);
assert.deepStrictEqual(runAllTimers(), []);
assert.strictEqual(
    logo.srcAssignments,
    assignments
);
assert.strictEqual(
    logo.getAttribute("src"),
    "/radio/song.png"
);
assert.strictEqual(
    nowPlaying.textContent,
    "Song Two - Artist"
);
"""
    )


def test_p7_apply_path_has_no_opacity_zero_artwork_swap():
    apply_model = function_source(
        "applyHomeHeroNowPlayingModel"
    )

    assert (
        'classList.add("srovaHomeHeroSwapping")'
        not in apply_model
    )
    assert (
        "homeHeroFadeOutTimer = window.setTimeout"
        not in apply_model
    )
    assert (
        "homeHeroFadeInTimer = window.setTimeout"
        not in apply_model
    )

    # Existing preload and stale-request ownership must remain.
    assert "var preload = new Image();" in apply_model
    assert (
        "token !== homeHeroNowPlayingToken"
        in apply_model
    )
    assert (
        "homeHeroArtworkElement !== logo"
        in apply_model
    )


def test_p7_initial_home_waits_for_session_truth_and_reuses_stable_hero_state():
    initial = function_source(
        "loadInitialHomeAfterStreamingProviderResolution"
    )
    home = function_source("loadHome")
    update = function_source(
        "updateHomeHeroNowPlaying"
    )
    restore = function_source("restoreSession")

    assert "Promise.all([" in initial
    assert (
        "Promise.resolve(sessionReady).catch(function() {})"
        in initial
    )
    assert (
        initial.index("Promise.all([")
        < initial.index("loadHome();")
    )

    assert (
        "deriveHomeHeroNowPlayingModel("
        "lastKnownHomeHeroStatus"
        ")"
        in home
    )
    assert (
        "initialHeroLogo.src = initialHeroImage;"
        in home
    )
    assert (
        "updateHomeHeroNowPlaying("
        "lastKnownHomeHeroStatus"
        ");"
        in home
    )

    assert (
        "if (s && s.qobuz_replacement_pending) "
        "{ return; }"
        in update
    )
    assert "lastKnownHomeHeroStatus = s;" in update

    assert 'return fetch("/session")' in restore
    assert (
        restore.index("updateHomeHeroNowPlaying(s);")
        < restore.index("if (isRadioLiveStatus(s)")
    )

    bootstrap_start = UI.index(
        'window.addEventListener("DOMContentLoaded"'
    )
    bootstrap_end = UI.index(
        "function initPlayerTechTray",
        bootstrap_start,
    )
    bootstrap = UI[
        bootstrap_start:bootstrap_end
    ]

    assert (
        "var initialSessionRestore = restoreSession();"
        in bootstrap
    )
    assert (
        "loadInitialHomeAfterStreamingProviderResolution("
        "initialSessionRestore"
        ");"
        in bootstrap
    )


def test_point4_cache_token_has_advanced_and_seek_guard_contract_remains_present():
    marker = "/ui_web/ui.js?v="
    assert marker in INDEX
    token = INDEX.split(marker, 1)[1].split('"', 1)[0].strip()
    assert token != "20260823_v1_4_point4_home_artwork_stability1"

    if "_v1_4_point" in token:
        point = int(
            token.split(
                "_v1_4_point",
                1,
            )[1].split(
                "_",
                1,
            )[0]
        )
        assert point >= 5
    else:
        assert token == "20260911_v2_0_q8f_qobuz_rename1"

    assert "var SEEK_SESSION_GUARD_MS = 1500;" in UI
    assert 'fetch("/tidal/seek/" + target)' in UI
