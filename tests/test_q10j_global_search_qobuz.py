from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

UI_PATH = ROOT / "src/ui_web/ui.js"
MAIN_PATH = ROOT / "src/main_headless.py"
INDEX_PATH = ROOT / "src/ui_web/index.html"

UI = UI_PATH.read_text(
    encoding="utf-8"
)

MAIN = MAIN_PATH.read_text(
    encoding="utf-8"
)

INDEX = INDEX_PATH.read_text(
    encoding="utf-8"
)


def fn(name):
    match = re.search(
        rf"\bfunction\s+{re.escape(name)}\s*"
        rf"\([^)]*\)\s*\{{",
        UI,
    )

    assert match, (
        f"missing function: {name}"
    )

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
            if char in (
                "'",
                '"',
                "`",
            ):
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1

                if depth == 0:
                    return UI[
                        start:
                        cursor + 1
                    ]

        cursor += 1

    raise AssertionError(
        f"unterminated function: {name}"
    )


def test_q10j_three_source_availability_is_independent():
    ready = fn(
        "globalSearchHasReadySource"
    )

    for token in (
        "globalSearchTidalReady",
        "globalSearchQobuzReady",
        "globalSearchLocalReady",
    ):
        assert token in ready

    qobuz = fn(
        "applyGlobalSearchQobuzStatus"
    )

    assert (
        "data.authenticated === true"
        in qobuz
    )

    assert (
        "data.usable === true"
        in qobuz
    )

    refresh = fn(
        "refreshGlobalSearchAvailability"
    )

    for call in (
        "refreshGlobalSearchTidalAvailability()",
        "refreshGlobalSearchQobuzAvailability()",
        "refreshGlobalSearchLocalAvailability()",
    ):
        assert call in refresh


def test_q10j_locked_ready_source_declaration_contract_is_preserved():
    source = fn(
        "doSearch"
    )

    assert (
        "var localRequest = "
        "globalSearchLocalReady"
        in source
    )

    assert (
        "var tidalRequest = "
        "globalSearchTidalReady"
        in source
    )

    assert (
        "var qobuzRequest = "
        "globalSearchQobuzReady"
        in source
    )


def test_q10j_search_fans_out_to_existing_routes_before_join():
    source = fn(
        "doSearch"
    )

    assert (
        '"/api/local/library/search?q="'
        in source
    )

    assert (
        '"/tidal/search?q="'
        in source
    )

    assert (
        '"/qobuz/catalog?"'
        in source
    )

    assert (
        '"op=search_catalog"'
        in source
    )

    assert (
        "Promise.all(["
        in source
    )

    tail = source[
        source.index(
            "Promise.all(["
        ):
    ]

    for request in (
        "localRequest",
        "tidalRequest",
        "qobuzRequest",
    ):
        assert request in tail


def test_q10j_local_search_transport_semantics_remain_q10i_compatible():
    source = fn(
        "doSearch"
    )

    start = source.index(
        "var localRequest = "
        "globalSearchLocalReady"
    )

    end = source.index(
        "var tidalRequest = "
        "globalSearchTidalReady",
        start,
    )

    local_source = source[
        start:
        end
    ]

    assert (
        '"/api/local/library/search?q="'
        in local_source
    )

    assert (
        "return res.json();"
        in local_source
    )

    assert (
        "res.ok"
        not in local_source
    )

    assert (
        "data.ok"
        not in local_source
    )

    assert (
        "ok: true"
        in local_source
    )

    assert (
        "searched: true"
        in local_source
    )

    assert (
        "searched: false"
        in local_source
    )


def test_q10j_logged_out_provider_is_not_provider_failure():
    source = fn(
        "doSearch"
    )

    assert (
        source.count(
            "searched: false"
        )
        >= 3
    )

    normalizer = fn(
        "normalizeSrovaSearchPayload"
    )

    assert (
        "qobuz.searched === true"
        in normalizer
    )

    assert (
        "qobuzFailed"
        in normalizer
    )


def test_q10j_stale_and_rapid_queries_are_generation_guarded():
    source = fn(
        "doSearch"
    )

    assert (
        "++globalSearchRequestSerial"
        in source
    )

    assert (
        "requestSerial !=="
        in source
    )

    assert (
        "lastSearchQuery"
        in source
    )

    input_source = fn(
        "onSearchInput"
    )

    assert (
        "globalSearchRequestSerial += 1"
        in input_source
    )

    assert "400" in input_source

    clear = fn(
        "clearSearch"
    )

    assert (
        "globalSearchRequestSerial += 1"
        in clear
    )


def test_q10j_global_taxonomy_remains_existing_three_types():
    normalizer = fn(
        "normalizeSrovaSearchPayload"
    )

    assert "tracks: []" in normalizer
    assert "albums: []" in normalizer
    assert "artists: []" in normalizer
    assert "playlists: []" not in normalizer

    shell = fn(
        "renderSrovaSearchShellInto"
    )

    assert (
        '["tracks", "TRACKS"]'
        in shell
    )

    assert (
        '["albums", "ALBUMS"]'
        in shell
    )

    assert (
        '["artists", "ARTISTS"]'
        in shell
    )

    assert (
        '["playlists"'
        not in shell
    )


def test_q10j_qobuz_uses_existing_combined_catalog_sections():
    source = fn(
        "normalizeSrovaSearchPayload"
    )

    for category in (
        "qobuzData.tracks.items",
        "qobuzData.albums.items",
        "qobuzData.artists.items",
    ):
        assert category in source

    assert (
        "qobuzData.playlists.items"
        not in source
    )


def test_q10j_cloud_identity_is_explicit_and_collision_safe():
    track_fn = fn(
        "normalizeSearchTrack"
    )

    script = r'''
const assert = require("assert");

function qobuzSourceSearchResultSeed(item, kind) {
    if (kind !== "track") {
        return null;
    }

    return {
        id: item.id,
        name: item.title || "",
        sub_title: item.artist || "",
        image_url: item.artwork_url || ""
    };
}

''' + track_fn + r'''

const tidal = normalizeSearchTrack(
    {
        id: 123,
        name: "TIDAL"
    },
    "tidal"
);

const qobuz = normalizeSearchTrack(
    {
        id: "qobuz:123",
        provider_track_id: "123",
        title: "Qobuz"
    },
    "qobuz"
);

assert.strictEqual(
    tidal.provider,
    "tidal"
);

assert.strictEqual(
    tidal.native_id,
    "123"
);

assert.strictEqual(
    tidal.id,
    "123"
);

assert.strictEqual(
    qobuz.provider,
    "qobuz"
);

assert.strictEqual(
    qobuz.native_id,
    "123"
);

assert.strictEqual(
    qobuz.id,
    "qobuz:123"
);

assert.notStrictEqual(
    tidal.id,
    qobuz.id
);
'''

    result = subprocess.run(
        [
            "node",
            "-e",
            script,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert (
        result.returncode == 0
    ), result.stderr


def test_q10j_qobuz_navigation_reuses_locked_q7_paths():
    seed = fn(
        "globalSearchQobuzSeed"
    )

    album = fn(
        "openGlobalSearchQobuzAlbum"
    )

    artist = fn(
        "openGlobalSearchQobuzArtist"
    )

    menu = fn(
        "showGlobalSearchQobuzTrackMenu"
    )

    play = fn(
        "playSrovaSearchTrack"
    )

    assert (
        "qobuzSourceSearchResultSeed("
        in seed
    )

    assert (
        "loadQobuzAlbumDetail("
        in album
    )

    assert '"search"' in album

    assert (
        "loadQobuzArtistDetail("
        in artist
    )

    assert '"search"' in artist

    assert (
        "showQobuzTrackArtworkMenu("
        in menu
    )

    assert '"search"' in menu

    assert (
        "playQobuzWallTrackNow("
        in play
    )


def test_q10j_top_results_balance_providers_per_content_type():
    helper = fn(
        "globalSearchBalancedTopItems"
    )

    top = fn(
        "renderSrovaSearchTopPanel"
    )

    assert (
        top.count(
            "globalSearchBalancedTopItems("
        )
        == 3
    )

    assert "data.tracks," in top
    assert "data.albums," in top
    assert "data.artists," in top
    assert "rows.slice(" not in top

    script = r"""
const assert = require("assert");

""" + helper + r"""

const items = [
    {source: "local", id: "l1"},
    {source: "local", id: "l2"},
    {source: "tidal", id: "t1"},
    {source: "tidal", id: "t2"},
    {source: "qobuz", id: "q1"},
    {source: "qobuz", id: "q2"}
];

assert.deepStrictEqual(
    globalSearchBalancedTopItems(
        items,
        3
    ).map(x => x.id),
    [
        "l1",
        "t1",
        "q1"
    ]
);

assert.deepStrictEqual(
    globalSearchBalancedTopItems(
        items,
        6
    ).map(x => x.id),
    [
        "l1",
        "t1",
        "q1",
        "l2",
        "t2",
        "q2"
    ]
);

const tidalOnly = [
    {source: "tidal", id: "t1"},
    {source: "tidal", id: "t2"},
    {source: "tidal", id: "t3"}
];

assert.deepStrictEqual(
    globalSearchBalancedTopItems(
        tidalOnly,
        3
    ).map(x => x.id),
    [
        "t1",
        "t2",
        "t3"
    ]
);
"""

    result = subprocess.run(
        [
            "node",
            "-e",
            script,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert (
        result.returncode == 0
    ), result.stderr


def test_q10j_qobuz_labels_and_favorites_are_provider_specific():
    label = fn(
        "globalSearchProviderLabel"
    )

    top = fn(
        "renderSrovaSearchTopRow"
    )

    track = fn(
        "renderSrovaSearchTrackRow"
    )

    album = fn(
        "renderSrovaSearchAlbumCard"
    )

    artist = fn(
        "renderSrovaSearchArtistCard"
    )

    combined = "\n".join(
        [
            top,
            track,
            album,
            artist,
        ]
    )

    assert '"LOCAL"' in label
    assert '"TIDAL"' in label
    assert '"QOBUZ"' in label

    for source in (
        top,
        track,
        album,
        artist,
    ):
        assert (
            "globalSearchProviderLabel("
            in source
        )

    for legacy in (
        "Track · Local",
        "Track · Qobuz",
        "Album · Local",
        "Album · Qobuz",
        "Artist · Local",
        "Artist · Qobuz",
        "LOCAL ALBUM",
        "QOBUZ ALBUM",
    ):
        assert legacy not in combined

    assert (
        "appendQobuzSearchTrackFavoriteHeart("
        in combined
    )

    assert (
        "appendQobuzSearchEntityFavoriteHeart("
        in combined
    )


def test_q10j_qobuz_missing_artwork_uses_provider_standby_not_local_generated_art():
    top = fn(
        "renderSrovaSearchTopRow"
    )

    track = fn(
        "renderSrovaSearchTrackRow"
    )

    album = fn(
        "renderSrovaSearchAlbumCard"
    )

    artist = fn(
        "renderSrovaSearchArtistCard"
    )

    assert (
        "SROVA_STANDBY_ART"
        in top
    )

    assert (
        "SROVA_STANDBY_ART"
        in track
    )

    assert (
        "SROVA_STANDBY_ART"
        in album
    )

    assert (
        "SROVA_STANDBY_ART"
        in artist
    )


def test_q10j_tidal_provider_failure_is_not_cached_as_empty_success():
    marker = (
        'if self.path.startswith("/tidal/search"):'
    )

    start = MAIN.index(
        marker
    )

    end = MAIN.index(
        "# -- Artist discography",
        start,
    )

    source = MAIN[
        start:
        end
    ]

    assert (
        '"ok": True'
        in source
    )

    assert (
        'out["ok"] = False'
        in source
    )

    assert (
        'if out.get("ok"):'
        in source
    )

    assert (
        source.index(
            'if out.get("ok"):'
        )
        <
        source.index(
            "cache_set("
            "cache_key, "
            "out, "
            "TTL_SEARCH"
            ")"
        )
    )


def test_q10j_cache_token_extends_complete_q10i_token():
    q10i_token = (
        "q10i_empty_artist_header_heart_js15"
    )

    q10j_token = (
        q10i_token
        + "_q10j_global_search_qobuz_js16"
        + "_q10j_global_search_parity_js17"
    )

    assert q10j_token in INDEX

    assert (
        INDEX.count(
            "/ui_web/ui.js?v="
        )
        == 1
    )


def test_q10j_ui_parses():
    result = subprocess.run(
        [
            "node",
            "--check",
            str(
                UI_PATH
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert (
        result.returncode == 0
    ), result.stderr
