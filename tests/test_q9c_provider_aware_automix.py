import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.main_headless as backend


ROOT = Path(__file__).resolve().parents[1]

MAIN_SOURCE = (
    ROOT / "src/main_headless.py"
).read_text(encoding="utf-8")

UI_SOURCE = (
    ROOT / "src/ui_web/ui.js"
).read_text(encoding="utf-8")


def qtrack(
    track_id,
    *,
    artist="Artist",
    streamable=True,
):
    native = str(track_id)

    return {
        "source": "qobuz",
        "provider_track_id": native,
        "id": "qobuz:" + native,
        "title": "Song " + native,
        "artist": artist,
        "artist_id": "artist-" + artist,
        "album": "Album " + native,
        "album_id": "album-" + native,
        "duration": 180,
        "streamable": streamable,
    }


class FakeQobuzAvailability:
    def __init__(self, usable):
        self.usable = usable

    def status(self):
        return {
            "usable": self.usable,
            "authenticated": self.usable,
            "available": True,
        }


class FakeQobuzCatalog:
    def __init__(self):
        self.search_results = {}
        self.pages = {}
        self.page_calls = []

    def search_artists(
        self,
        query,
        *,
        limit=None,
        offset=None,
        search_type=None,
    ):
        value = self.search_results.get(
            query,
            [],
        )

        if isinstance(value, Exception):
            raise value

        return {
            "ok": True,
            "items": list(value),
            "total": len(value),
            "offset": 0,
            "limit": 10,
        }

    def get_artist_page(self, artist_id):
        artist_id = str(artist_id)
        self.page_calls.append(artist_id)

        value = self.pages.get(
            artist_id,
            {
                "ok": True,
                "top_tracks": [],
            },
        )

        if isinstance(value, Exception):
            raise value

        return value


class FakeQobuzPlaylistBackend:
    def __init__(self):
        self.created = []
        self.added = []

    def create_playlist(
        self,
        name,
        description=None,
        *,
        is_public=False,
    ):
        self.created.append(
            (
                name,
                description,
                is_public,
            )
        )

        return {
            "ok": True,
            "id": "777",
        }

    def add_tracks_to_playlist(
        self,
        playlist_id,
        tracks,
    ):
        self.added.append(
            (
                str(playlist_id),
                list(tracks),
            )
        )

        return {
            "ok": True,
            "confirmed": True,
        }


def test_q9c_default_provider_is_tidal():
    assert (
        backend._APP_SETTINGS[
            "automix_provider"
        ]
        == "tidal"
    )


@pytest.mark.parametrize(
    "saved,tidal,qobuz,expected",
    [
        ("tidal", True, True, "tidal"),
        ("qobuz", True, True, "qobuz"),
        ("qobuz", True, False, "tidal"),
        ("tidal", False, True, "qobuz"),
        ("qobuz", False, True, "qobuz"),
        ("tidal", False, False, None),
    ],
)
def test_q9c_provider_matrix_preserves_saved_preference(
    monkeypatch,
    saved,
    tidal,
    qobuz,
    expected,
):
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(
            qobuz_backend=(
                FakeQobuzAvailability(
                    qobuz
                )
            )
        ),
    )

    monkeypatch.setattr(
        backend,
        "_tidal_login_snapshot",
        lambda: (
            {"ok": True}
            if tidal
            else None
        ),
    )

    original = backend._APP_SETTINGS

    try:
        backend._APP_SETTINGS = dict(
            original
        )

        backend._APP_SETTINGS[
            "automix_provider"
        ] = saved

        assert (
            backend._effective_automix_provider()
            == expected
        )

        assert (
            backend._automix_saved_provider()
            == saved
        )

    finally:
        backend._APP_SETTINGS = original


def test_q9c_preference_is_independent_from_infinite_play(
    monkeypatch,
):
    monkeypatch.setattr(
        backend,
        "_save_app_settings",
        lambda: None,
    )

    monkeypatch.setattr(
        backend,
        "_tidal_login_snapshot",
        lambda: True,
    )

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(
            qobuz_backend=(
                FakeQobuzAvailability(True)
            )
        ),
    )

    original = backend._APP_SETTINGS

    try:
        backend._APP_SETTINGS = dict(
            original
        )

        backend._APP_SETTINGS[
            "infinite_play_provider"
        ] = "tidal"

        state = (
            backend._set_automix_settings(
                provider="qobuz"
            )
        )

        assert state["provider"] == "qobuz"

        assert (
            backend._APP_SETTINGS[
                "infinite_play_provider"
            ]
            == "tidal"
        )

        with pytest.raises(ValueError):
            backend._set_automix_settings(
                provider="spotify"
            )

    finally:
        backend._APP_SETTINGS = original


def test_q9c_tidal_exact_name_first_and_dedupe():
    exact = SimpleNamespace(
        name="Seed Artist",
        id=1,
    )

    wrong = SimpleNamespace(
        name="Other",
        id=2,
    )

    class FakeTidal:
        def search_artist(self, name):
            return [wrong, exact]

        def get_artist_top_tracks(
            self,
            artist,
            limit=None,
        ):
            assert artist is exact
            assert limit == 3

            return [
                SimpleNamespace(id=10),
                SimpleNamespace(id=11),
                SimpleNamespace(id=11),
            ]

    assert (
        backend._automix_tidal_track_ids(
            FakeTidal(),
            ["Seed Artist"],
            3,
        )
        == ["10", "11"]
    )


def test_q9c_qobuz_exact_fallback_unresolved_dedupe_and_fill():
    qobuz = FakeQobuzCatalog()

    qobuz.search_results = {
        "Exact": [
            {
                "source": "qobuz",
                "artist_id": "wrong",
                "name": "Other",
            },
            {
                "source": "qobuz",
                "artist_id": "exact",
                "name": "Exact",
            },
        ],
        "Fallback": [
            {
                "source": "qobuz",
                "artist_id": "fallback",
                "name": "Not Exact",
            }
        ],
        "Missing": [],
        "Broken":
            RuntimeError("failure"),
    }

    qobuz.pages = {
        "exact": {
            "top_tracks": [
                qtrack(1),
                qtrack(2),
                qtrack(
                    3,
                    streamable=False,
                ),
                qtrack(4),
            ]
        },
        "fallback": {
            "top_tracks": [
                qtrack(2),
                qtrack(5),
                qtrack(6),
                qtrack(7),
            ]
        },
    }

    tracks = (
        backend._automix_qobuz_tracks(
            qobuz,
            [
                "Exact",
                "Fallback",
                "Missing",
                "Broken",
            ],
            3,
        )
    )

    assert [
        item["provider_track_id"]
        for item in tracks
    ] == [
        "1",
        "2",
        "4",
        "5",
        "6",
        "7",
    ]


def test_q9c_qobuz_rejects_invalid_identity():
    qobuz = FakeQobuzCatalog()

    qobuz.search_results = {
        "Artist": [
            {
                "artist_id": "a",
                "name": "Artist",
            }
        ]
    }

    qobuz.pages = {
        "a": {
            "top_tracks": [
                {
                    "source": "qobuz",
                    "provider_track_id": "x",
                    "id": "qobuz:x",
                    "streamable": True,
                },
                qtrack(99),
            ]
        }
    }

    tracks = (
        backend._automix_qobuz_tracks(
            qobuz,
            ["Artist"],
            1,
        )
    )

    assert [
        item["provider_track_id"]
        for item in tracks
    ] == ["99"]


def test_q9c_partial_artist_failure_is_skipped():
    qobuz = FakeQobuzCatalog()

    qobuz.search_results = {
        "A": [
            {
                "artist_id": "a",
                "name": "A",
            }
        ],
        "B": [
            {
                "artist_id": "b",
                "name": "B",
            }
        ],
        "C": [
            {
                "artist_id": "c",
                "name": "C",
            }
        ],
    }

    qobuz.pages = {
        "a": {
            "top_tracks": [
                qtrack(10)
            ]
        },
        "b":
            RuntimeError("page failure"),
        "c": {
            "top_tracks": [
                qtrack(20)
            ]
        },
    }

    tracks = (
        backend._automix_qobuz_tracks(
            qobuz,
            ["A", "B", "C"],
            3,
        )
    )

    assert [
        item["provider_track_id"]
        for item in tracks
    ] == ["10", "20"]


def test_q9c_over_100_tracks_delegate_to_q8_backend():
    qobuz = FakeQobuzPlaylistBackend()

    tracks = [
        qtrack(index)
        for index in range(
            1,
            106,
        )
    ]

    count = (
        backend._automix_create_qobuz_playlist(
            qobuz,
            "Large",
            tracks,
        )
    )

    assert count == 105
    assert len(qobuz.added) == 1
    assert len(qobuz.added[0][1]) == 105


def test_q9c_qobuz_never_false_success():
    class Rejecting(
        FakeQobuzPlaylistBackend
    ):
        def add_tracks_to_playlist(
            self,
            playlist_id,
            tracks,
        ):
            return {
                "ok": True,
                "confirmed": False,
            }

    with pytest.raises(RuntimeError):
        backend._automix_create_qobuz_playlist(
            Rejecting(),
            "Reject",
            [qtrack(1)],
        )


def test_q9c_helpers_are_queue_isolated():
    before_queue = copy.deepcopy(
        backend.PLAY_QUEUE
    )
    before_original = copy.deepcopy(
        backend.ORIGINAL_QUEUE
    )
    before_index = backend.QUEUE_INDEX
    before_meta = copy.deepcopy(
        backend.PLAY_QUEUE_META_CACHE
    )

    qobuz = FakeQobuzCatalog()

    qobuz.search_results = {
        "A": [
            {
                "artist_id": "a",
                "name": "A",
            }
        ]
    }

    qobuz.pages = {
        "a": {
            "top_tracks": [
                qtrack(1)
            ]
        }
    }

    tracks = (
        backend._automix_qobuz_tracks(
            qobuz,
            ["A"],
            1,
        )
    )

    backend._automix_create_qobuz_playlist(
        FakeQobuzPlaylistBackend(),
        "A",
        tracks,
    )

    assert backend.PLAY_QUEUE == before_queue
    assert backend.ORIGINAL_QUEUE == before_original
    assert backend.QUEUE_INDEX == before_index
    assert (
        backend.PLAY_QUEUE_META_CACHE
        == before_meta
    )


def _automix_route_block():
    import ast

    tree = ast.parse(
        MAIN_SOURCE
    )

    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(
            node,
            ast.FunctionDef,
        )
        and node.name == "do_POST"
    ]

    assert len(nodes) == 1

    lines = MAIN_SOURCE.splitlines(
        keepends=True
    )

    source = "".join(
        lines[
            nodes[0].lineno - 1:
            nodes[0].end_lineno
        ]
    )

    start = source.index(
        "# -- Auto-Mix: create playlist "
        "from artist affinity"
    )

    end = source.index(
        '        if self.path == '
        '"/api/radio/stations":',
        start,
    )

    return source[start:end]


def test_q9c_route_contract():
    block = _automix_route_block()

    assert (
        "_effective_automix_provider()"
        in block
    )

    assert (
        "Last.fm connection is required for Auto-Mix"
        in block
    )

    assert "n_tracks = 2" in block

    assert (
        block.count(
            "n_tracks = 3"
        )
        == 2
    )

    assert "limit=10," in block
    assert "limit=20," in block
    assert "first_degree[:5]" in block
    assert "limit=5," in block

    # Create requests cannot choose the provider directly.
    assert (
        'payload.get("provider")'
        not in block
    )

    # Preserve the existing playlist generation contract and
    # extend it to the Qobuz success branch.
    assert (
        'cache_invalidate("myplaylists")'
        in block
    )

    for forbidden in (
        "PLAY_QUEUE",
        "ORIGINAL_QUEUE",
        "QUEUE_INDEX",
        "PLAY_QUEUE_META_CACHE",
        "save_queue(",
        "_coordinated_infinite_play_refill(",
    ):
        assert forbidden not in block


def test_q9c_frontend_provider_neutral_without_q9d():
    assert (
        "Create a saved playlist based on "
        "listener affinity for any artist."
        in UI_SOURCE
    )

    assert (
        "Create a Tidal playlist based on "
        not in UI_SOURCE
    )

def test_q9c_automix_success_invalidates_provider_playlist_ui_cache():
    marker = "function buildAutoMixSection(st) {"

    start = UI_SOURCE.index(marker)

    end = UI_SOURCE.index(
        "\nfunction ",
        start + len(marker),
    )

    block = UI_SOURCE[start:end]

    assert "var createdProvider =" in block

    assert (
        'if (createdProvider === "qobuz")'
        in block
    )

    assert (
        "qobuzPlaylistsLoaded = false;"
        in block
    )

    assert (
        'else if (createdProvider === "tidal")'
        in block
    )

    assert (
        "playlistsLoaded = false;"
        in block
    )

    assert (
        "openPlaylistsProvider(createdProvider)"
        not in block
    )

    assert (
        "loadQobuzPlaylists();"
        not in block
    )
