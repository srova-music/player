from pathlib import Path

import pytest

from backend.qobuz import QobuzBackend


ROOT = Path(__file__).resolve().parents[1]
QOBUZ_PATH = ROOT / "src/backend/qobuz.py"
QOBUZ = QOBUZ_PATH.read_text(encoding="utf-8")


def bare_backend():
    backend = object.__new__(QobuzBackend)
    backend._qobuz_radio_track_artist_cache = {}
    return backend


def radio_response(*items):
    return {
        "source": "qobuz",
        "type": "radio-artist",
        "title": "Seed Artist",
        "tracks": {
            "items": [
                dict(item)
                for item in items
            ],
            "total": len(items),
            "offset": 0,
            "limit": len(items),
        },
    }


def test_h3_radio_enrichment_uses_authoritative_track_detail_only():
    backend = bare_backend()
    calls = []

    def get_track(track_id):
        calls.append(str(track_id))
        return {
            "source": "qobuz",
            "provider_track_id": str(track_id),
            "id": "qobuz:" + str(track_id),
            "title": "Resolved",
            "artist": "Authoritative Artist",
            "artist_id": "700",
        }

    backend.get_track = get_track

    response = radio_response(
        {
            "source": "qobuz",
            "provider_track_id": "101",
            "id": "qobuz:101",
            "title": "Radio Track",
            "artist": "",
            "artist_id": None,
            "album": "Compilation",
            "album_id": "album-1",
            "duration": 321,
        }
    )

    result = backend._enrich_qobuz_radio_response_artists(
        response
    )

    item = result["tracks"]["items"][0]

    assert calls == ["101"]
    assert item["artist"] == "Authoritative Artist"
    assert item["artist_id"] == "700"


def test_h3_radio_enrichment_preserves_identity_order_and_radio_fields():
    backend = bare_backend()

    details = {
        "101": {
            "artist": "Artist One",
            "artist_id": "1",
        },
        "202": {
            "artist": "Artist Two",
            "artist_id": "2",
        },
    }

    def get_track(track_id):
        value = details[str(track_id)]
        return {
            "source": "qobuz",
            "provider_track_id": str(track_id),
            "id": "qobuz:" + str(track_id),
            **value,
        }

    backend.get_track = get_track

    response = radio_response(
        {
            "source": "qobuz",
            "provider_track_id": "101",
            "id": "qobuz:101",
            "title": "First",
            "artist": "",
            "album": "Album One",
            "album_id": "a1",
            "artwork_url": "https://example/1.jpg",
            "duration": 111,
        },
        {
            "source": "qobuz",
            "provider_track_id": "202",
            "id": "qobuz:202",
            "title": "Second",
            "artist": "",
            "album": "Album Two",
            "album_id": "a2",
            "artwork_url": "https://example/2.jpg",
            "duration": 222,
        },
    )

    before = [
        (
            item["id"],
            item["provider_track_id"],
            item["title"],
            item["album"],
            item["album_id"],
            item["artwork_url"],
            item["duration"],
        )
        for item in response["tracks"]["items"]
    ]

    result = backend._enrich_qobuz_radio_response_artists(
        response
    )

    after = [
        (
            item["id"],
            item["provider_track_id"],
            item["title"],
            item["album"],
            item["album_id"],
            item["artwork_url"],
            item["duration"],
        )
        for item in result["tracks"]["items"]
    ]

    assert after == before
    assert [
        item["artist"]
        for item in result["tracks"]["items"]
    ] == [
        "Artist One",
        "Artist Two",
    ]


def test_h3_radio_enrichment_does_not_replace_existing_artist():
    backend = bare_backend()
    calls = []

    def get_track(track_id):
        calls.append(str(track_id))
        raise AssertionError(
            "existing artist must not be re-resolved"
        )

    backend.get_track = get_track

    response = radio_response(
        {
            "source": "qobuz",
            "provider_track_id": "101",
            "id": "qobuz:101",
            "title": "Already Complete",
            "artist": "Provider Artist",
            "artist_id": "9",
        }
    )

    result = backend._enrich_qobuz_radio_response_artists(
        response
    )

    item = result["tracks"]["items"][0]

    assert calls == []
    assert item["artist"] == "Provider Artist"
    assert item["artist_id"] == "9"


def test_h3_radio_enrichment_positive_cache_avoids_repeat_track_lookup():
    backend = bare_backend()
    calls = []

    def get_track(track_id):
        calls.append(str(track_id))
        return {
            "artist": "Cached Artist",
            "artist_id": "88",
        }

    backend.get_track = get_track

    first = radio_response(
        {
            "source": "qobuz",
            "provider_track_id": "101",
            "id": "qobuz:101",
            "title": "First Visit",
            "artist": "",
        }
    )

    second = radio_response(
        {
            "source": "qobuz",
            "provider_track_id": "101",
            "id": "qobuz:101",
            "title": "Second Visit",
            "artist": "",
        }
    )

    backend._enrich_qobuz_radio_response_artists(
        first
    )

    backend._enrich_qobuz_radio_response_artists(
        second
    )

    assert calls == ["101"]

    assert (
        second["tracks"]["items"][0]["artist"]
        == "Cached Artist"
    )


def test_h3_radio_enrichment_failure_is_salvageable_and_never_fakes_artist():
    backend = bare_backend()

    def get_track(track_id):
        raise RuntimeError(
            "provider detail unavailable"
        )

    backend.get_track = get_track

    response = radio_response(
        {
            "source": "qobuz",
            "provider_track_id": "101",
            "id": "qobuz:101",
            "title": "Radio Track",
            "artist": "",
            "album": "Do Not Use As Artist",
            "composer": {
                "name": "Do Not Use Composer",
            },
        }
    )

    result = backend._enrich_qobuz_radio_response_artists(
        response
    )

    item = result["tracks"]["items"][0]

    assert item["artist"] == ""
    assert item["album"] == "Do Not Use As Artist"
    assert (
        item["composer"]["name"]
        == "Do Not Use Composer"
    )


@pytest.mark.parametrize(
    "method_name",
    (
        "get_radio_artist",
        "get_radio_track",
        "get_radio_album",
    ),
)
def test_h3_all_provider_radio_methods_apply_artist_enrichment(method_name):
    marker = (
        "    def "
        + method_name
        + "(\n"
    )

    start = QOBUZ.index(marker)

    next_def = QOBUZ.find(
        "\n    def ",
        start + len(marker),
    )

    next_classmethod = QOBUZ.find(
        "\n    @classmethod",
        start + len(marker),
    )

    candidates = [
        value
        for value in (
            next_def,
            next_classmethod,
        )
        if value >= 0
    ]

    end = min(candidates)

    block = QOBUZ[start:end]

    assert (
        "_enrich_qobuz_radio_response_artists("
        in block
    )

    assert (
        "_normalize_qobuz_radio_response("
        in block
    )


def test_h3_artist_enrichment_does_not_touch_custom_internet_radio_model():
    helper_start = QOBUZ.index(
        "    def _enrich_qobuz_radio_response_artists("
    )

    helper_end = QOBUZ.index(
        "\n    def get_radio_artist(",
        helper_start,
    )

    helper = QOBUZ[
        helper_start:
        helper_end
    ]

    for forbidden in (
        "/api/radio/play/",
        "radio:station:",
        "RADIO_MODE",
        "context_type",
        "source = \"radio\"",
        "composer.get",
        "album.get",
    ):
        assert forbidden not in helper


def test_h3_artist_enrichment_only_mutates_artist_fields():
    backend = bare_backend()

    backend.get_track = lambda track_id: {
        "artist": "Correct Artist",
        "artist_id": "42",
        "title": "Wrong Replacement Title",
        "album": "Wrong Replacement Album",
        "duration": 9999,
    }

    original = {
        "source": "qobuz",
        "provider_track_id": "101",
        "id": "qobuz:101",
        "title": "Radio Native Title",
        "artist": "",
        "artist_id": None,
        "album": "Radio Native Album",
        "album_id": "radio-album",
        "duration": 123,
        "artwork_url": "https://example/native.jpg",
        "streamable": False,
    }

    response = radio_response(
        original
    )

    result = backend._enrich_qobuz_radio_response_artists(
        response
    )

    item = result["tracks"]["items"][0]

    assert item["artist"] == "Correct Artist"
    assert item["artist_id"] == "42"

    for key in (
        "source",
        "provider_track_id",
        "id",
        "title",
        "album",
        "album_id",
        "duration",
        "artwork_url",
        "streamable",
    ):
        assert item[key] == original[key]
