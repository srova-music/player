import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "src" / "main_headless.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")


def _resolver_namespace():
    tree = ast.parse(SOURCE)

    wanted = {
        "_build_track_list",
        "_playlist_declared_track_count",
        "_complete_streaming_playlist_payload",
    }

    nodes = []

    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in wanted
        ):
            nodes.append(node)

    assert {
        node.name for node in nodes
    } == wanted

    module = ast.Module(
        body=nodes,
        type_ignores=[],
    )

    namespace = {
        "_safe_str": lambda value: str(value or ""),
        "_quality_badge": lambda _track: "CD",
        "_STREAMING_PLAYLIST_MAX_TRACKS": 10000,
        "_TIDAL_COMPLETE_PLAYLIST_PAGE_SIZE": 100,
        "_QOBUZ_COMPLETE_PLAYLIST_PAGE_SIZE": 100,
    }

    exec(
        compile(
            ast.fix_missing_locations(module),
            str(SOURCE_PATH),
            "exec",
        ),
        namespace,
    )

    return namespace


class FakeTidalTrack:
    def __init__(self, track_id, title, artist):
        self.id = track_id
        self.name = title
        self.artist = SimpleNamespace(name=artist)
        self.duration = 180
        self.album = SimpleNamespace(cover="")


class FakeTidalPlaylist:
    def __init__(self, count):
        self.name = "Large TIDAL Playlist"
        self.numberOfTracks = count


class FakeTidalBackend:
    def __init__(self, tracks, declared=None):
        self.tracks = list(tracks)
        self.calls = []
        count = (
            len(self.tracks)
            if declared is None
            else declared
        )
        self.playlist_obj = FakeTidalPlaylist(count)
        self.session = SimpleNamespace(
            playlist=lambda _playlist_id: self.playlist_obj
        )

    def get_playlist_tracks_page(
        self,
        playlist_or_id,
        *,
        limit,
        offset,
    ):
        assert playlist_or_id is self.playlist_obj
        self.calls.append((limit, offset))
        return self.tracks[offset:offset + limit]

    def _is_owned_user_playlist(self, playlist):
        assert playlist is self.playlist_obj
        return True


class FakeTidalEarlyEndBackend(FakeTidalBackend):
    def get_playlist_tracks_page(
        self,
        playlist_or_id,
        *,
        limit,
        offset,
    ):
        assert playlist_or_id is self.playlist_obj
        self.calls.append((limit, offset))

        if offset == 0:
            return self.tracks[:limit]

        return []


def _qobuz_track(native_id, title=None):
    native_id = str(native_id)

    return {
        "source": "qobuz",
        "provider_track_id": native_id,
        "id": "qobuz:" + native_id,
        "title": title or ("Track " + native_id),
        "artist": "Artist",
        "duration": 180,
        "quality": {
            "hires": True,
            "maximum_sampling_rate_khz": 96.0,
            "maximum_bit_depth": 24,
        },
    }


class FakeQobuzBackend:
    def __init__(self, tracks):
        self.tracks = list(tracks)
        self.calls = []

    def get_playlist(
        self,
        playlist_id,
        *,
        limit,
        offset,
    ):
        self.calls.append((playlist_id, limit, offset))

        return {
            "id": str(playlist_id),
            "name": "Large Qobuz Playlist",
            "tracks": {
                "items": self.tracks[offset:offset + limit],
                "total": len(self.tracks),
                "offset": offset,
                "limit": limit,
            },
        }


def test_tidal_complete_resolver_fetches_every_page_in_order():
    ns = _resolver_namespace()
    resolve = ns["_complete_streaming_playlist_payload"]

    tracks = [
        FakeTidalTrack(
            track_id=index + 1,
            title="Track %d" % (index + 1),
            artist="Artist %d" % (index + 1),
        )
        for index in range(450)
    ]

    backend = FakeTidalBackend(tracks)

    result = resolve(
        "tidal",
        "playlist-1",
        tidal_backend=backend,
    )

    assert result["ok"] is True
    assert result["provider"] == "tidal"
    assert result["playlist_id"] == "playlist-1"
    assert result["playlist_name"] == "Large TIDAL Playlist"
    assert result["playlist_editable"] is True
    assert result["declared_total"] == 450
    assert result["total"] == 450
    assert result["complete"] is True

    assert backend.calls == [
        (100, 0),
        (100, 100),
        (100, 200),
        (100, 300),
        (100, 400),
    ]

    assert [
        track["id"]
        for track in result["tracks"]
    ] == list(range(1, 451))

    assert result["tracks"][0]["source"] == "tidal"
    assert (
        result["tracks"][0]["provider_track_id"]
        == "1"
    )
    assert result["tracks"][-1]["track_number"] == 450


def test_tidal_declared_total_prevents_silent_partial_inventory():
    ns = _resolver_namespace()
    resolve = ns["_complete_streaming_playlist_payload"]

    tracks = [
        FakeTidalTrack(
            track_id=index + 1,
            title="Track",
            artist="Artist",
        )
        for index in range(200)
    ]

    backend = FakeTidalEarlyEndBackend(
        tracks,
        declared=250,
    )

    with pytest.raises(
        RuntimeError,
        match="declared track count",
    ):
        resolve(
            "tidal",
            "playlist-2",
            tidal_backend=backend,
        )


def test_qobuz_complete_resolver_satisfies_provider_total():
    ns = _resolver_namespace()
    resolve = ns["_complete_streaming_playlist_payload"]

    tracks = [
        _qobuz_track(index + 1)
        for index in range(230)
    ]

    backend = FakeQobuzBackend(tracks)

    result = resolve(
        "qobuz",
        "1285066",
        qobuz_backend=backend,
    )

    assert result["ok"] is True
    assert result["provider"] == "qobuz"
    assert result["playlist_id"] == "1285066"
    assert result["playlist_name"] == "Large Qobuz Playlist"
    assert result["playlist_editable"] is False
    assert result["declared_total"] == 230
    assert result["total"] == 230
    assert result["complete"] is True

    assert backend.calls == [
        ("1285066", 100, 0),
        ("1285066", 100, 100),
        ("1285066", 100, 200),
    ]

    assert result["tracks"][0]["id"] == "qobuz:1"
    assert (
        result["tracks"][0]["provider_track_id"]
        == "1"
    )
    assert result["tracks"][-1]["id"] == "qobuz:230"


def test_qobuz_duplicate_tracks_are_preserved_not_deduplicated():
    ns = _resolver_namespace()
    resolve = ns["_complete_streaming_playlist_payload"]

    tracks = [
        _qobuz_track("7", "First"),
        _qobuz_track("7", "Repeated"),
        _qobuz_track("8", "Third"),
    ]

    result = resolve(
        "qobuz",
        "55",
        qobuz_backend=FakeQobuzBackend(tracks),
    )

    assert result["total"] == 3
    assert [
        track["id"]
        for track in result["tracks"]
    ] == [
        "qobuz:7",
        "qobuz:7",
        "qobuz:8",
    ]

    assert [
        track["title"]
        for track in result["tracks"]
    ] == [
        "First",
        "Repeated",
        "Third",
    ]


def test_qobuz_canonical_identity_is_mandatory():
    ns = _resolver_namespace()
    resolve = ns["_complete_streaming_playlist_payload"]

    broken = _qobuz_track("99")
    broken["id"] = "99"

    with pytest.raises(
        RuntimeError,
        match="track identity",
    ):
        resolve(
            "qobuz",
            "77",
            qobuz_backend=FakeQobuzBackend([broken]),
        )


def test_invalid_provider_is_rejected():
    ns = _resolver_namespace()
    resolve = ns["_complete_streaming_playlist_payload"]

    with pytest.raises(
        ValueError,
        match="Provider must be tidal or qobuz",
    ):
        resolve(
            "spotify",
            "1",
        )


def test_provider_neutral_http_route_is_present_and_safe():
    assert (
        'static_path == "/api/playlists/complete"'
        in SOURCE
    )

    assert (
        "_complete_streaming_playlist_payload("
        in SOURCE
    )

    assert (
        '"error": "playlist_unavailable"'
        in SOURCE
    )

    assert (
        '"Playlist could not be loaded completely."'
        in SOURCE
    )

    # F1 is a resolver only.  It must not add a second queue path.
    assert SOURCE.count(
        'fetchWithTimeout("/tidal/queue/replace"'
    ) == 0


class FakeTidalProviderCapBackend(FakeTidalBackend):
    def get_playlist_tracks_page(
        self,
        playlist_or_id,
        *,
        limit,
        offset,
    ):
        assert playlist_or_id is self.playlist_obj
        self.calls.append((limit, offset))

        provider_cap = 50

        return self.tracks[
            offset:offset + min(limit, provider_cap)
        ]


def test_tidal_short_provider_pages_continue_until_declared_total():
    ns = _resolver_namespace()
    resolve = ns["_complete_streaming_playlist_payload"]

    tracks = [
        FakeTidalTrack(
            track_id=index + 1,
            title="Track %d" % (index + 1),
            artist="Artist",
        )
        for index in range(250)
    ]

    backend = FakeTidalProviderCapBackend(
        tracks,
        declared=250,
    )

    result = resolve(
        "tidal",
        "provider-cap-playlist",
        tidal_backend=backend,
    )

    assert result["complete"] is True
    assert result["declared_total"] == 250
    assert result["total"] == 250

    assert backend.calls == [
        (100, 0),
        (100, 50),
        (100, 100),
        (100, 150),
        (100, 200),
    ]

    assert result["tracks"][0]["id"] == 1
    assert result["tracks"][-1]["id"] == 250
