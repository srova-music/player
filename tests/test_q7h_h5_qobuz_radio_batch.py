from backend.qobuz import QobuzBackend
from backend.qobuz_catalog import (
    QobuzCatalogClient,
)
from backend.qobuz_cmaf import (
    compute_request_signature,
)


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self):
        self.calls = []

    def post(
        self,
        url,
        *,
        headers,
        params,
        json,
        timeout,
    ):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
                "timeout": timeout,
            }
        )

        return FakeResponse(
            {
                "tracks": {
                    "items": [],
                }
            }
        )


def test_h5a_catalog_post_signs_query_and_sends_json_body():
    http = FakeHttp()

    metadata = {
        "app_id": "123456789",
        "app_secrets": ["candidate-secret"],
        "bundle_url": "https://example/bundle.js",
        "bundle_version": "1",
    }

    client = QobuzCatalogClient(
        http_session=http,
        api_base_url=(
            "https://www.qobuz.com/api.json/0.2"
        ),
        metadata_loader=lambda: metadata,
        token_loader=lambda: "token-value",
        now=lambda: 1700000000,
    )

    client._secret = (
        lambda loaded, token: "real-secret"
    )

    payload = client.request_json_post(
        "/track/getList",
        method_name="trackgetList",
        json_body={
            "tracks_id": [
                101,
                202,
            ],
        },
        signature_params={
            "tracks_id": "101,202",
        },
        require_auth=True,
    )

    assert payload == {
        "tracks": {
            "items": [],
        }
    }

    assert len(http.calls) == 1

    call = http.calls[0]

    assert call["url"].endswith(
        "/track/getList"
    )

    assert call["json"] == {
        "tracks_id": [
            101,
            202,
        ],
    }

    assert call["headers"] == {
        "X-App-Id": "123456789",
        "X-User-Auth-Token": "token-value",
    }

    expected_sig = compute_request_signature(
        "trackgetList",
        {
            "tracks_id": "101,202",
        },
        1700000000,
        "real-secret",
    )

    assert call["params"] == {
        "request_ts": "1700000000",
        "request_sig": expected_sig,
    }

    assert call["timeout"] == (
        client.CONNECT_TIMEOUT_SECONDS,
        client.READ_TIMEOUT_SECONDS,
    )


class FakeBatchCatalog:
    def __init__(self):
        self.calls = []

    def request_json_post(
        self,
        path,
        *,
        method_name,
        json_body,
        signature_params,
        require_auth,
    ):
        self.calls.append(
            {
                "path": path,
                "method_name": method_name,
                "json_body": json_body,
                "signature_params": (
                    signature_params
                ),
                "require_auth": require_auth,
            }
        )

        ids = list(
            json_body["tracks_id"]
        )

        # Deliberately reverse provider response order.
        # SROVA must restore requested input order.
        return {
            "tracks": {
                "items": [
                    {
                        "id": track_id,
                        "title": (
                            "Track "
                            + str(track_id)
                        ),
                        "performer": {
                            "id": (
                                track_id
                                + 1000
                            ),
                            "name": (
                                "Artist "
                                + str(track_id)
                            ),
                        },
                    }
                    for track_id in reversed(
                        ids
                    )
                ],
            },
        }


def test_h5a_track_getlist_caps_chunks_at_50_and_preserves_order():
    backend = object.__new__(
        QobuzBackend
    )

    backend._catalog = (
        FakeBatchCatalog()
    )

    requested = [
        str(value)
        for value in range(
            1,
            52,
        )
    ]

    tracks = backend.get_tracks_batch(
        requested
    )

    assert [
        track["provider_track_id"]
        for track in tracks
    ] == requested

    assert len(
        backend._catalog.calls
    ) == 2

    first, second = (
        backend._catalog.calls
    )

    assert len(
        first["json_body"]["tracks_id"]
    ) == 50

    assert len(
        second["json_body"]["tracks_id"]
    ) == 1

    assert first["path"] == (
        "/track/getList"
    )

    assert first["method_name"] == (
        "trackgetList"
    )

    assert first[
        "signature_params"
    ]["tracks_id"] == ",".join(
        requested[:50]
    )

    assert second[
        "signature_params"
    ]["tracks_id"] == "51"


def radio_response(*items):
    return {
        "source": "qobuz",
        "type": "radio-artist",
        "title": "Seed",
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


def test_h5a_radio_uses_one_deduplicated_batch_and_no_serial_lookup():
    backend = object.__new__(
        QobuzBackend
    )

    backend._qobuz_radio_track_artist_cache = {}

    batch_calls = []
    serial_calls = []

    def get_tracks_batch(track_ids):
        batch_calls.append(
            list(track_ids)
        )

        # Return in a different order to prove
        # association is by provider track ID.
        return [
            {
                "provider_track_id": "202",
                "artist": "Artist Two",
                "artist_id": "2",
            },
            {
                "provider_track_id": "101",
                "artist": "Artist One",
                "artist_id": "1",
            },
        ]

    def get_track(track_id):
        serial_calls.append(
            str(track_id)
        )
        raise AssertionError(
            "normal H5 batch path must not "
            "perform serial track lookup"
        )

    backend.get_tracks_batch = (
        get_tracks_batch
    )
    backend.get_track = get_track

    response = radio_response(
        {
            "source": "qobuz",
            "provider_track_id": "101",
            "id": "qobuz:101",
            "title": "First",
            "artist": "",
            "artist_id": None,
            "album": "Album One",
            "duration": 111,
        },
        {
            "source": "qobuz",
            "provider_track_id": "202",
            "id": "qobuz:202",
            "title": "Second",
            "artist": "",
            "artist_id": None,
            "album": "Album Two",
            "duration": 222,
        },
        {
            "source": "qobuz",
            "provider_track_id": "101",
            "id": "qobuz:101",
            "title": "Duplicate ID",
            "artist": "",
            "artist_id": None,
            "album": "Album Three",
            "duration": 333,
        },
    )

    before = [
        (
            item["id"],
            item["provider_track_id"],
            item["title"],
            item["album"],
            item["duration"],
        )
        for item in response[
            "tracks"
        ]["items"]
    ]

    result = (
        backend
        ._enrich_qobuz_radio_response_artists(
            response
        )
    )

    assert batch_calls == [
        [
            "101",
            "202",
        ]
    ]

    assert serial_calls == []

    items = result[
        "tracks"
    ]["items"]

    assert [
        item["artist"]
        for item in items
    ] == [
        "Artist One",
        "Artist Two",
        "Artist One",
    ]

    assert [
        item["artist_id"]
        for item in items
    ] == [
        "1",
        "2",
        "1",
    ]

    after = [
        (
            item["id"],
            item["provider_track_id"],
            item["title"],
            item["album"],
            item["duration"],
        )
        for item in items
    ]

    assert after == before


def test_h5a_batch_partial_result_falls_back_only_for_missing_id():
    backend = object.__new__(
        QobuzBackend
    )

    backend._qobuz_radio_track_artist_cache = {}

    batch_calls = []
    serial_calls = []

    def get_tracks_batch(track_ids):
        batch_calls.append(
            list(track_ids)
        )

        return [
            {
                "provider_track_id": "101",
                "artist": "Batch Artist",
                "artist_id": "1",
            },
        ]

    def get_track(track_id):
        serial_calls.append(
            str(track_id)
        )

        return {
            "provider_track_id": str(
                track_id
            ),
            "artist": "Fallback Artist",
            "artist_id": "2",
        }

    backend.get_tracks_batch = (
        get_tracks_batch
    )
    backend.get_track = get_track

    response = radio_response(
        {
            "provider_track_id": "101",
            "id": "qobuz:101",
            "title": "One",
            "artist": "",
        },
        {
            "provider_track_id": "202",
            "id": "qobuz:202",
            "title": "Two",
            "artist": "",
        },
    )

    backend._enrich_qobuz_radio_response_artists(
        response
    )

    assert batch_calls == [
        [
            "101",
            "202",
        ]
    ]

    assert serial_calls == [
        "202"
    ]

    assert [
        item["artist"]
        for item in response[
            "tracks"
        ]["items"]
    ] == [
        "Batch Artist",
        "Fallback Artist",
    ]
