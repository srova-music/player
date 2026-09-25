from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/ui_web/srova.css").read_text(encoding="utf-8")
SW = (ROOT / "src/ui_web/sw.js").read_text(encoding="utf-8")

POINT8_JS_TOKEN = "20260824_v1_4_point8_tidal_library_loading1"
POINT6_CSS_TOKEN = "20260824_v1_4_point6_nas_discovery_modal1"
POINT9_JS_TOKEN = "20260824_v1_4_point9_home_wordmark_inert1"
POINT9_CSS_TOKEN = "20260824_v1_4_point9_home_wordmark_inert_css1"


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


def test_home_and_non_home_interaction_contract_across_navigation_and_restoration():
    functions = "\n".join(
        function_source(name)
        for name in (
            "isTrueHomeLandingViewActive",
            "syncHeaderHomeNavigationState",
            "activateHeaderHomeNavigation",
            "initHeaderHomeNavigation",
            "goHome",
        )
    )
    run_node(
        textwrap.dedent(
            f"""
            const assert = require("assert");

            function makeClassList(initial) {{
                const values = new Set(initial || []);
                return {{
                    contains: value => values.has(value),
                    add: value => values.add(value),
                    remove: value => values.delete(value)
                }};
            }}

            const attributes = {{
                tabindex: "-1",
                "aria-current": "page",
                "aria-label": "SROVA"
            }};
            const buttonListeners = {{}};
            const windowListeners = {{}};
            const headerHomeBtn = {{
                disabled: true,
                setAttribute(name, value) {{ attributes[name] = String(value); }},
                removeAttribute(name) {{ delete attributes[name]; }},
                getAttribute(name) {{ return Object.hasOwn(attributes, name) ? attributes[name] : null; }},
                addEventListener(type, handler) {{
                    (buttonListeners[type] || (buttonListeners[type] = [])).push(handler);
                }}
            }};
            const window = {{
                addEventListener(type, handler) {{
                    (windowListeners[type] || (windowListeners[type] = [])).push(handler);
                }}
            }};
            const nowPlayingView = {{classList: makeClassList(["hidden"])}};
            const searchInput = {{value: "unchanged"}};
            const searchClear = {{classList: makeClassList([])}};
            let currentSrovaView = "home";
            let currentSourceSection = "";
            let headerHomeNavigationBound = false;
            const effects = {{navigation: 0, rebuild: 0, scroll: 0, fetch: 0, history: 0, transition: 0}};
            function loadHome() {{
                effects.navigation += 1;
                effects.rebuild += 1;
                effects.scroll += 1;
                effects.fetch += 1;
                effects.history += 1;
                effects.transition += 1;
            }}

            {functions}

            function event() {{
                return {{prevented: 0, preventDefault() {{ this.prevented += 1; }}}};
            }}
            function nativeActivate(kind) {{
                if (headerHomeBtn.disabled) {{ return; }}
                assert.ok(["pointer", "touch", "Enter", "Space"].includes(kind));
                (buttonListeners.click || []).forEach(handler => handler(event()));
            }}
            function setContext(view, source, overlayOpen) {{
                currentSrovaView = view;
                currentSourceSection = source;
                if (overlayOpen) {{ nowPlayingView.classList.remove("hidden"); }}
                else {{ nowPlayingView.classList.add("hidden"); }}
                syncHeaderHomeNavigationState();
            }}
            function resetEffects() {{ Object.keys(effects).forEach(key => effects[key] = 0); }}

            initHeaderHomeNavigation();
            initHeaderHomeNavigation();
            assert.strictEqual(buttonListeners.click.length, 1);
            assert.strictEqual(windowListeners.pageshow.length, 1);
            assert.strictEqual(headerHomeBtn.disabled, true);
            assert.strictEqual(attributes.tabindex, "-1");
            assert.strictEqual(attributes["aria-current"], "page");
            assert.strictEqual(attributes["aria-label"], "SROVA");
            assert.strictEqual(attributes.title, undefined);

            ["pointer", "touch", "Enter", "Space"].forEach(kind => nativeActivate(kind));
            assert.deepStrictEqual(effects, {{navigation: 0, rebuild: 0, scroll: 0, fetch: 0, history: 0, transition: 0}});

            // The handler itself guards against stale presentation state.
            headerHomeBtn.disabled = false;
            activateHeaderHomeNavigation(event());
            assert.deepStrictEqual(effects, {{navigation: 0, rebuild: 0, scroll: 0, fetch: 0, history: 0, transition: 0}});
            syncHeaderHomeNavigationState();

            const nonHomeContexts = [
                ["home", "tidal", false],
                ["home", "radio", false],
                ["localmusic", "music", false],
                ["search", "", false],
                ["album", "tidal", false],
                ["playlists", "tidal", false],
                ["myalbums", "tidal", false],
                ["mysongs", "tidal", false],
                ["settings", "", false],
                ["queue", "", false],
                ["home", "", true],
                ["album", "music", false]
            ];
            nonHomeContexts.forEach(parts => {{
                setContext(parts[0], parts[1], parts[2]);
                assert.strictEqual(headerHomeBtn.disabled, false, parts.join("/"));
                assert.strictEqual(attributes.tabindex, undefined);
                assert.strictEqual(attributes["aria-current"], undefined);
                assert.strictEqual(attributes["aria-label"], "SROVA Home");
                assert.strictEqual(attributes.title, "Home");
            }});

            setContext("search", "", false);
            resetEffects();
            nativeActivate("pointer");
            assert.strictEqual(effects.navigation, 1);
            resetEffects();
            nativeActivate("Enter");
            assert.strictEqual(effects.navigation, 1);
            resetEffects();
            nativeActivate("Space");
            assert.strictEqual(effects.navigation, 1);

            setContext("home", "", false);
            assert.strictEqual(headerHomeBtn.disabled, true);
            const rapid = [
                ["home", "radio", false], ["search", "", false],
                ["home", "", false], ["settings", "", false],
                ["home", "tidal", false], ["home", "", false]
            ];
            rapid.forEach(parts => setContext(parts[0], parts[1], parts[2]));
            assert.strictEqual(headerHomeBtn.disabled, true);
            assert.strictEqual(attributes["aria-current"], "page");

            // A stale callback that only re-syncs cannot overwrite newer state.
            setContext("settings", "", false);
            syncHeaderHomeNavigationState();
            assert.strictEqual(headerHomeBtn.disabled, false);

            // BFCache/pageshow restoration re-derives semantics from current state.
            setContext("home", "", false);
            headerHomeBtn.disabled = false;
            delete attributes["aria-current"];
            windowListeners.pageshow[0]();
            assert.strictEqual(headerHomeBtn.disabled, true);
            assert.strictEqual(attributes["aria-current"], "page");
            """
        )
    )


def test_shared_view_state_hooks_cover_initial_load_sources_details_and_now_playing():
    show_view = function_source("showView")
    source_state = function_source("setCurrentSourceSection")
    open_now_playing = function_source("openNowPlaying")
    dom_ready = UI[UI.index('window.addEventListener("DOMContentLoaded"') :]

    assert 'currentSrovaView = name;' in show_view
    assert "syncHeaderHomeNavigationState();" in show_view
    assert "syncHeaderHomeNavigationState();" in source_state
    assert "syncHeaderHomeNavigationState();" in open_now_playing
    assert dom_ready.index("initHeaderHomeNavigation();") < dom_ready.index("loadHome();")
    assert UI.count('headerHomeBtn.addEventListener("click", activateHeaderHomeNavigation);') == 1
    assert UI.count('window.addEventListener("pageshow", syncHeaderHomeNavigationState);') == 1
    assert 'homeView.style.display !== "none"' not in function_source(
        "isTrueHomeLandingViewActive"
    )


def test_initial_markup_and_css_expose_an_inert_unchanged_wordmark_without_hover():
    header = INDEX[INDEX.index('<button id="headerHomeBtn"') : INDEX.index("</button>")]
    assert 'type="button"' in header
    assert " disabled" in header
    assert 'tabindex="-1"' in header
    assert 'aria-current="page"' in header
    assert 'aria-label="SROVA"' in header
    assert "onclick=" not in header
    assert 'src="/ui_web/assets/srova-wordmark.svg?v=20260512a"' in header
    assert "#headerHomeBtn:disabled" in CSS
    assert "pointer-events: none !important;" in CSS
    assert "#headerHomeBtn:not(:disabled):hover .srovaHeaderWordmark" in CSS
    assert "#headerHomeBtn:hover .srovaHeaderWordmark" not in CSS


def test_q8f_js_asset_token_advances_once_and_service_worker_identity_stays_put():
    q8f_js_token = "20260911_v2_0_q8f_qobuz_rename1"

    assert INDEX.count(
        f'/ui_web/ui.js?v={q8f_js_token}'
    ) == 1
    assert INDEX.count("/ui_web/ui.js?v=") == 1
    assert POINT9_JS_TOKEN not in INDEX
    assert POINT8_JS_TOKEN not in INDEX

    assert INDEX.count(
        f'/ui_web/srova.css?v={POINT9_CSS_TOKEN}'
    ) == 1
    assert INDEX.count("/ui_web/srova.css?v=") == 1
    assert POINT6_CSS_TOKEN not in INDEX

    assert 'const CACHE_NAME = "srova-shell-v3";' in SW
    assert INDEX.count(
        'navigator.serviceWorker.register("/ui_web/sw.js")'
    ) == 1


def test_desktop_and_android_webview_share_the_single_header_implementation():
    assert INDEX.count('id="headerHomeBtn"') == 1
    assert UI.count("function initHeaderHomeNavigation()") == 1
    android_marker = "(function markAndroidApkWebView()"
    assert UI.index(android_marker) < UI.index("var headerHomeBtn")
    assert "srovaAndroidApkWebView" not in function_source(
        "syncHeaderHomeNavigationState"
    )
