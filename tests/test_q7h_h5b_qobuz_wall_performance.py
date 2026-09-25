from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
UI_PATH = ROOT / "src/ui_web/ui.js"
UI = UI_PATH.read_text(encoding="utf-8")


def function_block(name):
    marker = "function " + name + "("
    start = UI.index(marker)
    brace = UI.index("{", start)

    depth = 0
    quote = None
    escape = False

    for index in range(brace, len(UI)):
        char = UI[index]

        if quote is not None:
            if escape:
                escape = False
                continue

            if char == "\\":
                escape = True
                continue

            if char == quote:
                quote = None

            continue

        if char in ('"', "'", "`"):
            quote = char
            continue

        if char == "{":
            depth += 1

        elif char == "}":
            depth -= 1

            if depth == 0:
                return UI[start:index + 1]

    raise AssertionError(
        "unterminated function: " + name
    )


def run_node(source):
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, (
        result.stdout + result.stderr
    )

    return result.stdout


def test_h5b_scheduler_is_fifo_and_bounded_to_four():
    assert (
        "var QOBUZ_WALL_FETCH_CONCURRENCY = 4;"
        in UI
    )

    drain = function_block(
        "drainQobuzWallFetchQueue"
    )

    schedule = function_block(
        "scheduleQobuzWallFetch"
    )

    run_node(
        r'''
const assert = require("assert");

var QOBUZ_WALL_FETCH_CONCURRENCY = 4;
var qobuzWallFetchActive = 0;
var qobuzWallFetchQueue = [];

'''
        + drain
        + "\n"
        + schedule
        + r'''

let running = 0;
let maximum = 0;
let started = [];

function job(value) {
    return scheduleQobuzWallFetch(
        function() {
            started.push(value);

            running += 1;

            maximum = Math.max(
                maximum,
                running
            );

            return new Promise(
                function(resolve) {
                    setTimeout(
                        function() {
                            running -= 1;
                            resolve(value);
                        },
                        20
                    );
                }
            );
        }
    );
}

Promise.all(
    Array.from(
        {length: 12},
        function(_, index) {
            return job(index);
        }
    )
)
.then(function(values) {
    assert.strictEqual(
        maximum,
        4
    );

    assert.deepStrictEqual(
        started,
        Array.from(
            {length: 12},
            function(_, index) {
                return index;
            }
        )
    );

    assert.deepStrictEqual(
        values,
        Array.from(
            {length: 12},
            function(_, index) {
                return index;
            }
        )
    );

    console.log(
        "SCHEDULER_RUNTIME=PASS"
    );
})
.catch(function(error) {
    console.error(error);
    process.exitCode = 1;
});
'''
    )


def test_h5b_all_initial_sections_queue_without_120ms_stagger():
    show = function_block(
        "showQobuzSource"
    )

    assert (
        "loadQobuzWallSection("
        in show
    )

    assert "index * 120" not in show
    assert "setTimeout(" not in show


def test_h5b_wall_and_artist_fallback_share_scheduler():
    load = function_block(
        "loadQobuzWallSection"
    )

    enrich = function_block(
        "enrichQobuzArtistWallArtwork"
    )

    assert (
        "scheduleQobuzWallFetch("
        in load
    )

    assert (
        "scheduleQobuzWallFetch("
        in enrich
    )

    assert (
        "var chain = Promise.resolve();"
        not in enrich
    )


def test_h5b_preserves_artist_release_art_fallback():
    enrich = function_block(
        "enrichQobuzArtistWallArtwork"
    )

    fallback = function_block(
        "qobuzArtistPageFallbackArtwork"
    )

    assert (
        '"/qobuz/catalog?op=artist_page"'
        in enrich
    )

    assert (
        "qobuzArtistPageFallbackArtwork("
        in enrich
    )

    assert "page.artwork_url" in fallback
    assert "page.last_release" in fallback
    assert "page.release_groups" in fallback
    assert "page.top_tracks" in fallback


def test_h5b_preserves_exact_wall_feed_contract():
    required = (
        '"MY ALBUMS"',
        '"MY TRACKS"',
        '"MY ARTISTS"',
        '"NEW RELEASES"',
        '"QOBUZISSIME"',
        '"MOST STREAMED"',
        '"PRESS AWARDS"',
        'endpoint: "/discover/newReleases"',
        'endpoint: "/discover/qobuzissims"',
        'featured_type: "most-streamed"',
        'featured_type: "press-awards"',
        "var QOBUZ_WALL_PAGE_LIMIT = 24;",
    )

    for value in required:
        assert value in UI

    q7d_start = UI.index(
        "// Q7D_QOBUZ_SOURCE_WALL"
    )

    q7d_end = UI.index(
        "function showTidalSource(",
        q7d_start,
    )

    qobuz_wall = UI[
        q7d_start:
        q7d_end
    ]

    assert "discover_index" not in qobuz_wall


def test_h5b_scheduler_is_qobuz_wall_local():
    show_tidal = UI.index(
        "function showTidalSource("
    )

    tidal_and_later = UI[
        show_tidal:
    ]

    assert (
        "scheduleQobuzWallFetch("
        not in tidal_and_later
    )
