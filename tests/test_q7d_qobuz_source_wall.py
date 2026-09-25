from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]

UI = (
    ROOT / "src/ui_web/ui.js"
).read_text(encoding="utf-8")

CSS = (
    ROOT / "src/ui_web/srova.css"
).read_text(encoding="utf-8")


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
                return UI[start:pos + 1]

    raise AssertionError(
        f"unterminated function: {name}"
    )


def run_node(script):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, (
        result.stderr or result.stdout
    )


def css_block(selector):
    pattern = (
        re.escape(selector)
        + r"\s*\{([^}]*)\}"
    )

    match = re.search(
        pattern,
        CSS,
        flags=re.S,
    )

    assert match, selector

    return match.group(1)



def test_q7d_provider_selector_is_inside_source03_only():
    shell = function_source(
        "buildSourcePageShell"
    )

    selector = function_source(
        "buildStreamingProviderSelector"
    )

    source_switcher = function_source(
        "buildSourceSwitcher"
    )

    assert (
        'activeSource || "") === "streaming"'
        in shell
    )

    assert (
        "buildStreamingProviderSelector("
        in shell
    )

    assert (
        'item("streaming", "ONLINE", "showTidalSource()")'
        in source_switcher
    )

    assert (
        'item("streaming", "TIDAL", "showTidalSource()")'
        not in source_switcher
    )

    assert (
        'data-streaming-provider="'
        in selector
    )

    assert '"TIDAL"' in selector
    assert '"QOBUZ"' in selector

    assert (
        '"showTidalSource()"'
        in selector
    )

    assert (
        '"showQobuzSource()"'
        in selector
    )


def test_q7d_wall_section_set_is_exact_and_restrained():
    start = UI.index(
        "var QOBUZ_WALL_SECTION_SPECS = ["
    )

    end = UI.index(
        "\n];",
        start,
    ) + 3

    specs = UI[start:end]

    for title in (
        "MY ALBUMS",
        "MY TRACKS",
        "MY ARTISTS",
        "NEW RELEASES",
        "QOBUZISSIME",
        "MOST STREAMED",
        "PRESS AWARDS",
    ):
        assert specs.count(
            f'title: "{title}"'
        ) == 1

    for op in (
        "library_albums",
        "library_tracks",
        "library_artists",
        "discover_albums",
        "featured_albums",
    ):
        assert f'op: "{op}"' in specs

    assert (
        'endpoint: "/discover/newReleases"'
        in specs
    )

    assert (
        'endpoint: "/discover/qobuzissims"'
        in specs
    )

    assert (
        'endpoint: "/discover/mostStreamed"'
        not in specs
    )

    assert (
        'featured_type: "most-streamed"'
        in specs
    )

    assert (
        'featured_type: "press-awards"'
        in specs
    )

    for forbidden in (
        "search_catalog",
        "search_tracks",
        "search_albums",
        "search_artists",
        "search_playlists",
        'op: "playlists"',
        "radio_artist",
        "radio_track",
        "radio_album",
    ):
        assert forbidden not in specs

def test_q7d_qobuz_item_adapter_maps_q6_models_to_existing_cards():
    quality = function_source(
        "qobuzWallQualityLabel"
    )

    adapt = function_source(
        "adaptQobuzWallItem"
    )

    run_node(
        """
const assert = require("assert");
"""
        + quality
        + "\n"
        + adapt
        + """
let album = adaptQobuzWallItem({
    album_id: "a1",
    title: "Album One",
    artist: "Artist One",
    artwork_url: "https://img/a.jpg",
    quality: {
        maximum_sampling_rate_khz: 96,
        maximum_bit_depth: 24
    }
}, "album");

assert.strictEqual(album.id, "a1");
assert.strictEqual(album.type, "Album");
assert.strictEqual(album.name, "Album One");
assert.strictEqual(album.sub_title, "Artist One");
assert.strictEqual(album.image_url, "https://img/a.jpg");
assert.strictEqual(album.quality, "HI-RES");

let track = adaptQobuzWallItem({
    id: "qobuz:301",
    provider_track_id: "301",
    title: "Track One",
    artist: "Artist Two",
    artwork_url: "https://img/t.jpg",
    quality: {
        maximum_sampling_rate_khz: 44.1,
        maximum_bit_depth: 16
    }
}, "track");

assert.strictEqual(track.id, "qobuz:301");
assert.strictEqual(track.type, "Track");
assert.strictEqual(track.quality, "CD");

let artist = adaptQobuzWallItem({
    artist_id: "701",
    name: "Artist Three",
    artwork_url: "https://img/r.jpg"
}, "artist");

assert.strictEqual(artist.id, "701");
assert.strictEqual(artist.type, "Artist");
assert.strictEqual(artist.name, "Artist Three");
assert.strictEqual(artist.quality, "");
"""
    )



def test_q7d_wall_uses_one_bounded_page_and_tidal_style_row_arrows():
    url = function_source(
        "qobuzCatalogUrl"
    )

    load = function_source(
        "loadQobuzWallSection"
    )

    render = function_source(
        "renderQobuzWallSection"
    )

    section_builder = function_source(
        "buildScrollSection"
    )

    assert (
        "var QOBUZ_WALL_PAGE_LIMIT = 24;"
        in UI
    )

    # Qobuz now uses exactly the same horizontal row primitive
    # as TIDAL, including its conditional left/right arrows.
    assert "buildScrollSection(" in render
    assert "rowArrowLeft" in section_builder
    assert "rowArrowRight" in section_builder

    q7d_start = UI.index(
        "// Q7D_QOBUZ_SOURCE_WALL"
    )

    q7d_end = UI.index(
        "function showTidalSource(",
        q7d_start,
    )

    q7d = UI[q7d_start:q7d_end]

    for forbidden in (
        '"LOAD MORE"',
        '"RETRY LOAD MORE"',
        '"LOADING..."',
        "qobuzWallPageHasMore",
        "_qobuzWallHasMore",
        "_qobuzWallLoadMoreError",
        "_qobuzWallNextOffset",
        "/discover/mostStreamed",
    ):
        assert forbidden not in q7d

    assert (
        'featured_type: "most-streamed"'
        in q7d
    )

    assert (
        "qobuzCatalogUrl("
        in load
    )

    # H5B may nest the unchanged page-zero URL call inside a
    # bounded scheduler, so verify its semantics independently
    # of source indentation.
    compact_load = "".join(load.split())

    assert (
        "qobuzCatalogUrl(spec,0)"
        in compact_load
    )

    run_node(
        """
const assert = require("assert");
const QOBUZ_WALL_PAGE_LIMIT = 24;
"""
        + url
        + """
let spec = {
    op: "featured_albums",
    params: {
        featured_type: "most-streamed"
    }
};

let u = qobuzCatalogUrl(spec, 0);

assert.ok(u.startsWith("/qobuz/catalog?"));
assert.ok(u.includes("op=featured_albums"));
assert.ok(u.includes("limit=24"));
assert.ok(u.includes("offset=0"));
assert.ok(
    u.includes(
        "featured_type=most-streamed"
    )
);
"""
    )


def test_q7d_has_loading_empty_error_and_initial_retry_states():
    state = function_source(
        "renderQobuzWallState"
    )

    render = function_source(
        "renderQobuzWallSection"
    )

    load = function_source(
        "loadQobuzWallSection"
    )

    assert '"loading"' in load
    assert '"error"' in load
    assert '"empty"' in render
    assert '"RETRY"' in state

    assert '"LOAD MORE"' not in render
    assert '"RETRY LOAD MORE"' not in render
    assert '"LOADING..."' not in render

def test_q7d_detail_and_later_slices_remain_navigation_hooks_only():
    show = function_source(
        "showQobuzSource"
    )

    click = function_source(
        "handleQobuzWallItemClick"
    )

    assert (
        'setCurrentStreamingProvider("qobuz")'
        in show
    )

    assert (
        'setCurrentSourceSection("streaming")'
        in show
    )

    assert (
        '"SOURCE 03"'
        in show
    )

    assert '"Qobuz"' in show

    assert (
        'setGlobalSearchVisible(false)'
        in show
    )

    for forbidden in (
        "/qobuz/test-play",
        "showAlbum(",
        "showArtist(",
        "loadTrackList(",
        "showMyPlaylists(",
        "searchQobuz",
        "radio_artist",
        "radio_track",
        "radio_album",
        "/qobuz/login/",
        "/qobuz/logout",
    ):
        assert forbidden not in show
        assert forbidden not in click

    assert 'source: "qobuz"' in click


def test_q7d_new_boxed_text_controls_are_two_axis_centered():
    provider = css_block(
        "#homeView .srovaStreamingProviderBar "
        ".srovaSourceSwitchItem"
    )

    action = css_block(
        "#homeView .srovaQobuzActionButton"
    )

    for block in (
        provider,
        action,
    ):
        assert (
            "display: inline-flex !important;"
            in block
        )

        assert (
            "align-items: center !important;"
            in block
        )

        assert (
            "justify-content: center !important;"
            in block
        )

        assert (
            "text-align: center !important;"
            in block
        )

        assert (
            "line-height: 1 !important;"
            in block
        )

        assert re.search(
            r"height:\s*34px\s*!important;",
            block,
        )

        assert re.search(
            r"padding:\s*0\s+14px\s*!important;",
            block,
        )


def test_q7d_tidal_wall_fetch_contract_remains_intact():
    show_tidal = function_source(
        "showTidalSource"
    )

    for endpoint in (
        "/tidal/hires",
        "/tidal/home",
        "/tidal/mysongs",
        "/tidal/myalbums",
    ):
        assert endpoint in show_tidal

    assert (
        'setCurrentStreamingProvider("tidal");'
        in show_tidal
    )

    assert (
        'setCurrentSourceSection("streaming");'
        in show_tidal
    )

# Q7D_AUTH_HEADER_ART_REFINEMENT_TESTS


def test_q7d_streaming_identity_tracks_authenticated_provider_set():
    presentation = function_source(
        "streamingProviderPresentation"
    )

    playback_label = function_source(
        "streamingProviderPlaybackLabel"
    )

    infer_source = function_source(
        "inferStatusPlaybackSource"
    )

    poll_start = UI.index(
        "function pollStatus()"
    )
    poll_end = UI.index(
        "setInterval(pollStatus, 1000);",
        poll_start
    )
    poll_status = UI[
        poll_start:poll_end
    ]

    switcher = function_source(
        "buildSourceSwitcher"
    )

    selector = function_source(
        "buildStreamingProviderSelector"
    )

    refresh = function_source(
        "refreshStreamingProviderPresentation"
    )

    home = function_source(
        "loadHome"
    )

    assert "/tidal/status" in refresh
    assert "/qobuz/status" in refresh

    assert (
        "data.logged_in === true"
        in refresh
    )

    assert (
        "data.authenticated === true"
        in refresh
    )

    # Preserve the locked Q7B SOURCE03 navigation call shape.
    assert (
        'item("streaming", "ONLINE", "showTidalSource()")'
        in switcher
    )

    assert (
        "streamingPresentation.label"
        in switcher
    )

    assert (
        "streamingPresentation.handler"
        in switcher
    )

    assert "presentation.dual" in selector
    assert '" hidden"' in selector

    assert (
        "refreshStreamingProviderPresentation();"
        in home
    )

    # P12: every committed non-transitional /status snapshot repaints
    # SOURCE03 identity from authoritative playback truth.
    assert "applyStreamingProviderPresentation();" in poll_status
    assert (
        poll_status.index(
            "if (qobuzReplacementPending)"
        )
        <
        poll_status.index(
            "applyStreamingProviderPresentation();"
        )
        <
        poll_status.index(
            "updateHomeHeroNowPlaying(s);"
        )
    )

    run_node(
        """
const assert = require("assert");

let currentStreamingProvider = "tidal";
let lastKnownPlaybackStatus = null;

let streamingProviderAuthState = {
    tidal: null,
    qobuz: null,
    requestSerial: 0
};
"""
        + infer_source
        + playback_label
        + presentation
        + """
let p;

function setStatus(status) {
    lastKnownPlaybackStatus = status;
}

/* TIDAL-only remains TIDAL regardless of unrelated playback. */
streamingProviderAuthState.tidal = true;
streamingProviderAuthState.qobuz = false;
setStatus({
    current_track_valid: true,
    playback_state: "playing",
    source: "local"
});

p = streamingProviderPresentation();

assert.strictEqual(p.label, "TIDAL");
assert.strictEqual(
    p.handler,
    "showTidalSource()"
);
assert.strictEqual(p.dual, false);


/* Qobuz-only remains QOBUZ. */
streamingProviderAuthState.tidal = false;
streamingProviderAuthState.qobuz = true;
setStatus({
    current_track_valid: true,
    playback_state: "playing",
    source: "tidal"
});

p = streamingProviderPresentation();

assert.strictEqual(p.label, "QOBUZ");
assert.strictEqual(
    p.handler,
    "showQobuzSource()"
);
assert.strictEqual(p.dual, false);


/* Dual-auth idle is provider-neutral. */
streamingProviderAuthState.tidal = true;
streamingProviderAuthState.qobuz = true;
setStatus({
    current_track_valid: false,
    playback_state: "idle",
    source: null
});

p = streamingProviderPresentation();

assert.strictEqual(p.label, "ONLINE");
assert.strictEqual(
    p.handler,
    "showTidalSource()"
);
assert.strictEqual(p.dual, true);


/* Dual-auth follows committed TIDAL playback. */
setStatus({
    current_track_valid: true,
    playback_state: "playing",
    source: "tidal"
});

p = streamingProviderPresentation();

assert.strictEqual(p.label, "TIDAL");
assert.strictEqual(
    p.handler,
    "showTidalSource()"
);


/*
 * Navigation and playback identity are deliberately independent:
 * browsing Qobuz must not relabel active TIDAL playback.
 */
currentStreamingProvider = "qobuz";

p = streamingProviderPresentation();

assert.strictEqual(p.label, "TIDAL");
assert.strictEqual(
    p.handler,
    "showQobuzSource()"
);


/* Dual-auth follows committed Qobuz playback. */
setStatus({
    current_track_valid: true,
    playback_state: "playing",
    source: "qobuz"
});

p = streamingProviderPresentation();

assert.strictEqual(p.label, "QOBUZ");
assert.strictEqual(
    p.handler,
    "showQobuzSource()"
);


/*
 * Browsing TIDAL must not relabel active Qobuz playback.
 */
currentStreamingProvider = "tidal";

p = streamingProviderPresentation();

assert.strictEqual(p.label, "QOBUZ");
assert.strictEqual(
    p.handler,
    "showTidalSource()"
);


/* Paused valid provider media retains its provider identity. */
setStatus({
    current_track_valid: true,
    playback_state: "paused",
    source: "tidal"
});

p = streamingProviderPresentation();

assert.strictEqual(p.label, "TIDAL");


/* Local playback remains neutral. */
setStatus({
    current_track_valid: true,
    playback_state: "playing",
    source: "local",
    context_type: "local"
});

p = streamingProviderPresentation();

assert.strictEqual(p.label, "ONLINE");


/* Internet Radio remains neutral. */
setStatus({
    current_track_valid: true,
    playback_state: "playing",
    source: "radio",
    context_type: "radio",
    radio_mode: true
});

p = streamingProviderPresentation();

assert.strictEqual(p.label, "ONLINE");


/*
 * Provider-generated Radio remains provider-labelled when the backend
 * explicitly identifies the finite provider source.
 */
setStatus({
    current_track_valid: true,
    playback_state: "playing",
    source: "tidal",
    context_type: "radio",
    radio_mode: false
});

p = streamingProviderPresentation();

assert.strictEqual(p.label, "TIDAL");

setStatus({
    current_track_valid: true,
    playback_state: "playing",
    source: "qobuz",
    context_type: "radio",
    radio_mode: false
});

p = streamingProviderPresentation();

assert.strictEqual(p.label, "QOBUZ");


/* Neither authenticated is visibly provider-neutral. */
streamingProviderAuthState.tidal = false;
streamingProviderAuthState.qobuz = false;

p = streamingProviderPresentation();

assert.strictEqual(p.label, "ONLINE");
assert.strictEqual(
    p.handler,
    "showTidalSource()"
);
assert.strictEqual(p.dual, false);
"""
    )


def test_q7d_missing_artist_portrait_uses_real_release_art_before_placeholder():
    fallback = function_source(
        "qobuzArtistPageFallbackArtwork"
    )

    enrich = function_source(
        "enrichQobuzArtistWallArtwork"
    )

    adapt = function_source(
        "adaptQobuzWallItem"
    )

    load = function_source(
        "loadQobuzWallSection"
    )

    assert "page.artwork_url" in fallback
    assert "page.last_release" in fallback
    assert "page.release_groups" in fallback
    assert "page.top_tracks" in fallback

    assert (
        '"/qobuz/catalog?op=artist_page"'
        in enrich
    )

    assert (
        "qobuzArtistPageFallbackArtwork("
        in enrich
    )

    assert "SROVA_STANDBY_ART" in adapt

    assert (
        "qobuz_artwork_missing"
        in adapt
    )

    assert (
        "enrichQobuzArtistWallArtwork("
        in load
    )

    run_node(
        """
const assert = require("assert");
"""
        + fallback
        + """
assert.strictEqual(
    qobuzArtistPageFallbackArtwork({
        artwork_url: "portrait.jpg",
        release_groups: [{
            items: [{
                artwork_url: "release.jpg"
            }]
        }]
    }),
    "portrait.jpg"
);

assert.strictEqual(
    qobuzArtistPageFallbackArtwork({
        artwork_url: null,
        last_release: {
            artwork_url: "last.jpg"
        },
        release_groups: [{
            items: [{
                artwork_url: "release.jpg"
            }]
        }]
    }),
    "last.jpg"
);

assert.strictEqual(
    qobuzArtistPageFallbackArtwork({
        artwork_url: null,
        last_release: null,
        release_groups: [{
            items: [{
                artwork_url: "release.jpg"
            }]
        }]
    }),
    "release.jpg"
);

assert.strictEqual(
    qobuzArtistPageFallbackArtwork({
        artwork_url: null,
        last_release: null,
        release_groups: [],
        top_tracks: [{
            artwork_url: "track.jpg"
        }]
    }),
    "track.jpg"
);

assert.strictEqual(
    qobuzArtistPageFallbackArtwork({
        artwork_url: null,
        last_release: null,
        release_groups: [],
        top_tracks: []
    }),
    ""
);
"""
    )



def test_q7d_qobuz_header_has_every_tidal_header_geometry_rule():
    from pathlib import Path
    import re

    css = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ui_web"
        / "srova.css"
    ).read_text(
        encoding="utf-8"
    )

    targets = (
        (
            ".srovaSourcePageHeader",
            8,
        ),
        (
            ".srovaSourcePageIdentity",
            1,
        ),
        (
            ".srovaSourceBack",
            1,
        ),
        (
            ".srovaSourceSwitcher",
            3,
        ),
        (
            ".srovaSourceSwitcher::-webkit-scrollbar",
            1,
        ),
    )

    total = 0

    for suffix, expected in targets:
        tidal_pattern = re.compile(
            r"#homeView\s+"
            r"\.srovaTidalSourcePage"
            r"\s+"
            + re.escape(suffix)
            + r"\s*(?:,|\{)"
        )

        qobuz_pattern = re.compile(
            r"#homeView\s+"
            r"\.srovaQobuzSourcePage"
            r"\s+"
            + re.escape(suffix)
            + r"\s*\{"
        )

        tidal_count = len(
            tidal_pattern.findall(css)
        )

        qobuz_count = len(
            qobuz_pattern.findall(css)
        )

        assert tidal_count == expected
        assert qobuz_count == expected

        total += expected

    assert total == 14

    assert (
        "#homeView "
        ".srovaStreamingProviderBar[hidden]"
        in css
    )
