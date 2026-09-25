from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "src/main_headless.py"
MAIN = MAIN_PATH.read_text(encoding="utf-8")

ADAPTER_START = "# -- Q7C Qobuz normalized HTTP adapter --"
ADAPTER_END = "# -- Q7C Qobuz normalized HTTP adapter end"


def adapter_namespace():
    start = MAIN.index(ADAPTER_START)
    end = MAIN.index(ADAPTER_END, start)
    end = MAIN.index("\n", end) + 1

    namespace = {}
    exec(
        MAIN[start:end],
        namespace,
    )
    return namespace


def handler_method_source(name):
    tree = ast.parse(MAIN)

    handler = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ControlHandler"
    )

    method = next(
        node
        for node in handler.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    )

    return ast.get_source_segment(
        MAIN,
        method,
    )


class FakeBackend:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append(
                (name, args, kwargs)
            )
            return {
                "ok": True,
                "called": name,
            }

        return call


EXPECTED_OPS = {
    "album",
    "album_suggest",
    "artist",
    "artist_page",
    "artist_releases",
    "artist_story",
    "discover_albums",
    "discover_index",
    "discover_playlists",
    "featured_albums",
    "genres",
    "library_albums",
    "library_artists",
    "library_tracks",
    "playlist",
    "playlist_tags",
    "playlists",
    "radio_album",
    "radio_artist",
    "radio_track",
    "release_watch",
    "search_albums",
    "search_artists",
    "search_catalog",
    "search_playlists",
    "search_tracks",
    "similar_artists",
    "track",
}


def test_q7c_has_one_read_only_normalized_catalog_route():
    get_source = handler_method_source("do_GET")
    post_source = handler_method_source("do_POST")

    assert (
        get_source.count(
            'static_path == "/qobuz/catalog"'
        )
        == 1
    )

    assert "/qobuz/catalog" not in post_source

    assert (
        "_qobuz_catalog_http_dispatch("
        in get_source
    )

    assert "no_store=True" in get_source

    assert "safe_payload" in get_source

    assert (
        "Qobuz catalog request could not "
        in get_source
    )


def test_q7c_allowlist_is_exactly_the_declared_q7_read_surface():
    ns = adapter_namespace()

    assert (
        set(ns["_QOBUZ_CATALOG_HTTP_OPS"])
        == EXPECTED_OPS
    )

    adapter = MAIN[
        MAIN.index(ADAPTER_START):
        MAIN.index(ADAPTER_END)
    ]

    for forbidden in (
        "resolve_track_delivery",
        "fetch_decrypt_cmaf_segment",
        "reconstruct_flac_for_validation",
        "logout",
        "start_login",
        "poll_login",
        "get_user_purchases",
        "get_user_purchases_ids",
    ):
        assert forbidden not in adapter

    assert "getattr(backend" not in adapter
    assert "qobuz.com/api" not in adapter
    assert "play.qobuz.com/api" not in adapter


def test_q7c_dispatch_maps_representative_q6_methods_exactly():
    ns = adapter_namespace()
    dispatch = ns[
        "_qobuz_catalog_http_dispatch"
    ]

    backend = FakeBackend()

    result = dispatch(
        backend,
        {
            "op": ["track"],
            "track_id": ["5966783"],
        },
    )

    assert result["called"] == "get_track"
    assert backend.calls[-1] == (
        "get_track",
        ("5966783",),
        {},
    )

    dispatch(
        backend,
        {
            "op": ["library_albums"],
            "limit": ["25"],
            "offset": ["50"],
        },
    )

    assert backend.calls[-1] == (
        "get_library_albums",
        (),
        {
            "limit": 25,
            "offset": 50,
        },
    )

    dispatch(
        backend,
        {
            "op": ["discover_albums"],
            "endpoint": [
                "/discover/newReleases"
            ],
            "genre_ids": ["10,20"],
            "genre_id": ["30"],
            "limit": ["12"],
            "offset": ["4"],
        },
    )

    assert backend.calls[-1] == (
        "get_discover_albums",
        ("/discover/newReleases",),
        {
            "genre_ids": ["10", "20", "30"],
            "limit": 12,
            "offset": 4,
        },
    )

    dispatch(
        backend,
        {
            "op": ["artist_releases"],
            "artist_id": ["77"],
            "release_type": ["albums"],
            "sort": ["release_date"],
            "limit": ["20"],
            "offset": ["5"],
        },
    )

    assert backend.calls[-1] == (
        "get_artist_releases_grid",
        ("77", "albums"),
        {
            "limit": 20,
            "offset": 5,
            "sort": "release_date",
        },
    )

    dispatch(
        backend,
        {
            "op": ["search_tracks"],
            "q": ["Miles Davis"],
            "search_type": ["MainArtist"],
            "limit": ["15"],
            "offset": ["1"],
        },
    )

    assert backend.calls[-1] == (
        "search_tracks",
        ("Miles Davis",),
        {
            "limit": 15,
            "offset": 1,
            "search_type": "MainArtist",
        },
    )

    dispatch(
        backend,
        {
            "op": ["radio_album"],
            "album_id": ["12345"],
        },
    )

    assert backend.calls[-1] == (
        "get_radio_album",
        ("12345",),
        {},
    )


def test_q7c_dispatch_rejects_unknown_or_malformed_requests():
    ns = adapter_namespace()
    dispatch = ns[
        "_qobuz_catalog_http_dispatch"
    ]

    backend = FakeBackend()

    cases = (
        {},
        {"op": ["not_real"]},
        {"op": ["track"]},
        {
            "op": ["library_tracks"],
            "limit": ["not-an-int"],
        },
        {
            "op": ["library_tracks"],
            "offset": ["-1"],
        },
        {
            "op": ["search_catalog"],
            "q": [""],
        },
    )

    for query in cases:
        try:
            dispatch(
                backend,
                query,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(
                "Malformed Q7C request was accepted: "
                + repr(query)
            )


def test_q7c_genre_id_parser_matches_q6_list_contract():
    ns = adapter_namespace()
    parse_genres = ns[
        "_qobuz_catalog_http_genre_ids"
    ]

    assert (
        parse_genres({})
        is None
    )

    assert parse_genres({
        "genre_ids": [
            "1,2",
            "3",
        ],
        "genre_id": [
            "4, 5",
        ],
    }) == [
        "1",
        "2",
        "3",
        "4",
        "5",
    ]


def test_q7c_does_not_modify_q7b_ui_or_create_q7d_ui():
    ui = (
        ROOT / "src/ui_web/ui.js"
    ).read_text(encoding="utf-8")

    assert (
        'var currentStreamingProvider = "tidal";'
        in ui
    )

    assert (
        'setCurrentSourceSection("streaming");'
        in ui
    )

    # Q7C originally proved Q7D was not yet present. Preserve that
    # historical assertion until the authorized Q7D marker appears.
    if "Q7D_QOBUZ_SOURCE_WALL" not in ui:
        assert "showQobuzSource(" not in ui
        assert "/qobuz/catalog?op=" not in ui
