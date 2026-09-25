from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")


def function_source(name):
    marker = f"function {name}("
    start = UI.index(marker)
    brace = UI.index("{", start)
    depth = 0
    quote = None
    escaped = False

    for pos in range(brace, len(UI)):
        char = UI[pos]

        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in ('"', "'", "`"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return UI[start : pos + 1]

    raise AssertionError(f"unterminated function: {name}")


def run_node(script):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout



def test_q7b_source03_state_is_provider_neutral_while_tidal_ui_is_preserved():
    show_tidal = function_source(
        "showTidalSource"
    )

    load_home = function_source(
        "loadHome"
    )

    switcher = function_source(
        "buildSourceSwitcher"
    )

    source_setter = function_source(
        "setCurrentSourceSection"
    )

    provider_setter = function_source(
        "setCurrentStreamingProvider"
    )

    presentation = function_source(
        "streamingProviderPresentation"
    )

    assert (
        'var currentSourceSection = "";'
        in UI
    )

    assert (
        'var currentStreamingProvider = "tidal";'
        in UI
    )

    # Q7B provider-neutral SOURCE03 state remains locked.
    assert (
        "currentStreamingProvider"
        not in source_setter
    )

    assert (
        'provider === "qobuz" ? "qobuz" : "tidal"'
        in provider_setter
    )

    assert (
        'setCurrentStreamingProvider("tidal");'
        in show_tidal
    )

    assert (
        'setCurrentSourceSection("streaming");'
        in show_tidal
    )

    assert (
        'setCurrentSourceSection("tidal");'
        not in UI
    )

    assert (
        'data-home-source="streaming"'
        in load_home
    )

    # Q7D evolves only the visible SOURCE03 identity:
    # TIDAL-only -> TIDAL
    # Qobuz-only -> QOBUZ
    # both -> ONLINE.
    assert (
        "streamingProviderPresentation()"
        in load_home
    )

    assert (
        "streamingPresentation.label"
        in load_home
    )

    assert (
        "streamingPresentation.handler"
        in load_home
    )

    # Preserve the historical TIDAL default for the dual-provider
    # source-switch construction and signed-out compatibility path.
    assert (
        'item("streaming", "ONLINE", "showTidalSource()")'
        in switcher
    )

    assert (
        'label: "TIDAL"'
        in presentation
    )

    assert (
        'handler: "showTidalSource()"'
        in presentation
    )

    # Q7D adds provider-aware visible identities without changing
    # the provider-neutral SOURCE03 internal key.
    assert (
        'label: "QOBUZ"'
        in presentation
    )

    assert (
        'handler: "showQobuzSource()"'
        in presentation
    )

    assert (
        'label: "ONLINE"'
        in presentation
    )

def test_q7b_real_qobuz_playback_never_falls_through_to_tidal():
    infer_source = function_source("inferStatusPlaybackSource")

    run_node(
        """
const assert = require("assert");
"""
        + infer_source
        + """
assert.strictEqual(
    inferStatusPlaybackSource({source: "qobuz"}),
    "qobuz"
);
assert.strictEqual(
    inferStatusPlaybackSource({current_track_id: "qobuz:5966783"}),
    "qobuz"
);
assert.strictEqual(
    inferStatusPlaybackSource({context_type: "qobuz"}),
    "qobuz"
);
assert.strictEqual(
    inferStatusPlaybackSource({context_type: "qobuz_album"}),
    "qobuz"
);
assert.strictEqual(
    inferStatusPlaybackSource({
        source: "qobuz",
        radio_mode: true
    }),
    "radio"
);
assert.strictEqual(
    inferStatusPlaybackSource({source: "tidal"}),
    "tidal"
);
assert.strictEqual(
    inferStatusPlaybackSource({source: "local"}),
    "local"
);
assert.strictEqual(
    inferStatusPlaybackSource({current_track_id: "local:abc"}),
    "local"
);
assert.strictEqual(
    inferStatusPlaybackSource({current_track_id: "123456"}),
    "tidal"
);
"""
    )


def test_q7b_infinite_play_remains_tidal_only_after_source03_split():
    fn = function_source("shouldShowInfinitePlayUi")

    run_node(
        """
const assert = require("assert");
let playerHasActiveMedia = false;
let playerBarActivePlaybackSource = "";
let currentSourceSection = "streaming";
let currentStreamingProvider = "tidal";
"""
        + fn
        + """
assert.strictEqual(shouldShowInfinitePlayUi(true), true);

currentStreamingProvider = "qobuz";
assert.strictEqual(shouldShowInfinitePlayUi(true), false);

playerHasActiveMedia = true;
playerBarActivePlaybackSource = "qobuz";
assert.strictEqual(shouldShowInfinitePlayUi(true), false);

playerBarActivePlaybackSource = "tidal";
assert.strictEqual(shouldShowInfinitePlayUi(true), true);

playerBarActivePlaybackSource = "radio";
assert.strictEqual(shouldShowInfinitePlayUi(true), false);

assert.strictEqual(shouldShowInfinitePlayUi(false), false);
"""
    )


def test_q7b_home_gateway_maps_both_streaming_providers_to_source03():
    fn = function_source("setHomeHeroActiveSource")

    run_node(
        """
const assert = require("assert");

function makeNode(source) {
    return {
        source,
        active: false,
        getAttribute(name) {
            return name === "data-home-source" ? this.source : "";
        },
        classList: {
            _owner: null,
            toggle(name, enabled) {
                if (name === "srovaHomeSourceActive") {
                    this._owner.active = !!enabled;
                }
            }
        }
    };
}

const radio = makeNode("radio");
const music = makeNode("local");
const streaming = makeNode("streaming");
[radio, music, streaming].forEach(
    node => node.classList._owner = node
);

const document = {
    querySelectorAll() {
        return [radio, music, streaming];
    }
};
"""
        + fn
        + """
setHomeHeroActiveSource("tidal");
assert.strictEqual(streaming.active, true);
assert.strictEqual(radio.active, false);
assert.strictEqual(music.active, false);

setHomeHeroActiveSource("qobuz");
assert.strictEqual(streaming.active, true);
assert.strictEqual(radio.active, false);
assert.strictEqual(music.active, false);

setHomeHeroActiveSource("radio");
assert.strictEqual(streaming.active, false);
assert.strictEqual(radio.active, true);
assert.strictEqual(music.active, false);
"""
    )


def test_q7b_qobuz_is_a_finite_home_artwork_source():
    fn = function_source("isHomeHeroFiniteArtworkSource")

    run_node(
        """
const assert = require("assert");
"""
        + fn
        + """
assert.strictEqual(isHomeHeroFiniteArtworkSource("tidal"), true);
assert.strictEqual(isHomeHeroFiniteArtworkSource("qobuz"), true);
assert.strictEqual(isHomeHeroFiniteArtworkSource("local"), true);
assert.strictEqual(isHomeHeroFiniteArtworkSource("radio"), false);
"""
    )


def test_q7b_does_not_implement_later_qobuz_ui_slices():
    show_tidal = function_source("showTidalSource")

    # Q7B originally proved that later Qobuz UI slices were absent.
    # Once the authorized Q7D marker exists, those historical
    # absence assertions are intentionally superseded while the
    # provider-neutral Q7B foundation remains protected.
    q7d_present = "Q7D_QOBUZ_SOURCE_WALL" in UI

    if not q7d_present:
        assert "/qobuz/catalog" not in UI
        assert "showQobuzSource(" not in UI
        assert "buildQobuz" not in UI

    # Q7B preserves the existing TIDAL-facing SOURCE 03 wall.
    assert "/tidal/hires" in show_tidal
    assert "/tidal/home" in show_tidal
    assert "/tidal/mysongs" in show_tidal
    assert "/tidal/myalbums" in show_tidal
