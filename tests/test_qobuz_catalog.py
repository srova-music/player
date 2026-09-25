import hashlib
import os
import sys

import pytest
import requests


sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "src"),
)


from backend.qobuz import QobuzBackend
from backend.qobuz_catalog import (
    QobuzCatalogClient,
    QobuzCatalogError,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        payload=None,
        headers=None,
        json_error=None,
    ):
        self.status_code = status_code
        self._payload = (
            {"ok": True}
            if payload is None
            else payload
        )
        self.headers = dict(headers or {})
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeHttp:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def get(
        self,
        url,
        *,
        headers=None,
        params=None,
        timeout=None,
        **_kwargs,
    ):
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers or {}),
                "params": dict(params or {}),
                "timeout": timeout,
            }
        )

        if not self.responses:
            raise AssertionError(
                "unexpected Qobuz network request"
            )

        result = self.responses.pop(0)

        if isinstance(result, BaseException):
            raise result

        return result


def metadata(secrets=None, bundle_version="1"):
    return {
        "version": 2,
        "bundle_url": (
            f"/resources/8.1.0-b{bundle_version}/bundle.js"
        ),
        "bundle_version": f"8.1.0-b{bundle_version}",
        "app_id": "123456789",
        "private_key": "PrivateKey123",
        "app_secrets": list(
            secrets
            or ["0123456789abcdef0123456789abcdef"]
        ),
        "fetched_at": 1000,
    }


def make_client(
    http,
    *,
    secrets=None,
    token="UserToken123",
    bundle_version="1",
    sleep=None,
):
    return QobuzCatalogClient(
        http_session=http,
        api_base_url="https://www.qobuz.com/api.json/0.2",
        metadata_loader=lambda: metadata(
            secrets,
            bundle_version=bundle_version,
        ),
        token_loader=lambda: token,
        now=lambda: 1234567890,
        sleep=sleep or (lambda _seconds: None),
    )


def expected_signature(method, params, secret):
    material = [method]

    for key in sorted(params):
        material.extend(
            (str(key), str(params[key]))
        )

    material.extend(
        ("1234567890", secret)
    )

    return hashlib.md5(
        "".join(material).encode("utf-8")
    ).hexdigest()


def test_constructor_is_network_free():
    http = FakeHttp()
    make_client(http)
    assert http.calls == []


@pytest.mark.parametrize(
    "limit,offset,expected",
    [
        (None, None, (50, 0)),
        ("25", "10", (25, 10)),
        (100, 1_000_000, (100, 1_000_000)),
    ],
)
def test_page_bounds_accept_valid_values(
    limit,
    offset,
    expected,
):
    assert QobuzCatalogClient.page_bounds(
        limit,
        offset,
    ) == expected


@pytest.mark.parametrize(
    "limit,offset",
    [
        (0, 0),
        (101, 0),
        ("x", 0),
        (1, -1),
        (1, 1_000_001),
    ],
)
def test_page_bounds_reject_invalid_values(
    limit,
    offset,
):
    with pytest.raises(
        QobuzCatalogError,
        match="Qobuz",
    ) as exc:
        QobuzCatalogClient.page_bounds(
            limit,
            offset,
        )

    assert exc.value.code == "invalid_request"


def test_generic_request_signature_matches_pinned_qbz_contract():
    secret = "0123456789abcdef0123456789abcdef"

    http = FakeHttp(
        [
            FakeResponse(status_code=200),
            FakeResponse(
                payload={
                    "id": "album-id",
                    "title": "Album",
                }
            ),
        ]
    )

    client = make_client(
        http,
        secrets=[secret],
    )

    payload = client.request_json(
        "/album/get",
        method_name="albumget",
        params={
            "album_id": "abc123",
            "lang": "en",
        },
    )

    assert payload["id"] == "album-id"
    assert len(http.calls) == 2

    request = http.calls[1]

    expected = expected_signature(
        "albumget",
        {
            "album_id": "abc123",
            "lang": "en",
        },
        secret,
    )

    assert request["params"]["request_sig"] == expected
    assert request["params"]["request_ts"] == "1234567890"
    assert request["params"]["album_id"] == "abc123"
    assert request["params"]["lang"] == "en"

    assert request["headers"]["X-App-Id"] == "123456789"
    assert (
        request["headers"]["X-User-Auth-Token"]
        == "UserToken123"
    )

    assert request["timeout"] == (10, 30)


def test_search_signature_sorts_limit_offset_query_type():
    secret = "0123456789abcdef0123456789abcdef"

    http = FakeHttp(
        [
            FakeResponse(status_code=200),
            FakeResponse(
                payload={
                    "albums": {
                        "items": [],
                        "total": 0,
                    }
                }
            ),
        ]
    )

    client = make_client(
        http,
        secrets=[secret],
    )

    client.request_json(
        "/album/search",
        method_name="albumsearch",
        params={
            "query": "Miles Davis",
            "limit": "25",
            "offset": "50",
            "type": "MainArtist",
        },
    )

    request = http.calls[1]

    expected = expected_signature(
        "albumsearch",
        {
            "limit": "25",
            "offset": "50",
            "query": "Miles Davis",
            "type": "MainArtist",
        },
        secret,
    )

    assert request["params"]["request_sig"] == expected


def test_favorites_can_sign_empty_parameter_set():
    secret = "0123456789abcdef0123456789abcdef"

    http = FakeHttp(
        [
            FakeResponse(status_code=200),
            FakeResponse(
                payload={
                    "albums": {
                        "items": [],
                        "total": 0,
                    }
                }
            ),
        ]
    )

    client = make_client(
        http,
        secrets=[secret],
    )

    client.request_json(
        "/favorite/getUserFavorites",
        method_name="favoritegetUserFavorites",
        params={
            "type": "albums",
            "limit": "50",
            "offset": "0",
        },
        signature_params={},
        require_auth=True,
    )

    request = http.calls[1]

    expected = expected_signature(
        "favoritegetUserFavorites",
        {},
        secret,
    )

    assert request["params"]["request_sig"] == expected
    assert request["params"]["type"] == "albums"
    assert request["params"]["limit"] == "50"
    assert request["params"]["offset"] == "0"


def test_secret_candidates_are_validated_and_success_is_cached():
    first = "11111111111111111111111111111111"
    second = "22222222222222222222222222222222"

    http = FakeHttp(
        [
            FakeResponse(status_code=400),
            FakeResponse(status_code=200),
            FakeResponse(payload={"id": 1}),
            FakeResponse(payload={"id": 2}),
        ]
    )

    client = make_client(
        http,
        secrets=[first, second],
    )

    assert client.request_json(
        "/track/get",
        method_name="trackget",
        params={"track_id": "1"},
    ) == {"id": 1}

    assert client.request_json(
        "/track/get",
        method_name="trackget",
        params={"track_id": "2"},
    ) == {"id": 2}

    assert len(http.calls) == 4

    assert http.calls[0]["url"].endswith(
        "/track/getFileUrl"
    )
    assert http.calls[1]["url"].endswith(
        "/track/getFileUrl"
    )

    expected_second = expected_signature(
        "trackget",
        {"track_id": "1"},
        second,
    )

    assert (
        http.calls[2]["params"]["request_sig"]
        == expected_second
    )


def test_authenticated_request_fails_before_network_when_signed_out():
    http = FakeHttp()

    client = make_client(
        http,
        token=None,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        client.request_json(
            "/favorite/getUserFavorites",
            method_name="favoritegetUserFavorites",
            params={
                "type": "albums",
                "limit": "50",
                "offset": "0",
            },
            signature_params={},
            require_auth=True,
        )

    assert exc.value.code == "not_authenticated"
    assert http.calls == []


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "invalid_request"),
        (401, "not_authenticated"),
        (403, "unavailable"),
        (404, "not_found"),
        (500, "provider_unavailable"),
    ],
)
def test_http_statuses_map_to_safe_typed_errors(
    status,
    code,
):
    http = FakeHttp(
        [
            FakeResponse(status_code=200),
            FakeResponse(status_code=status),
        ]
    )

    client = make_client(http)

    with pytest.raises(QobuzCatalogError) as exc:
        client.request_json(
            "/album/get",
            method_name="albumget",
            params={"album_id": "x"},
        )

    assert exc.value.code == code

    payload = exc.value.safe_payload()

    assert payload["error"] == code
    assert "request_sig" not in str(payload)
    assert "UserToken123" not in str(payload)


def test_rate_limit_is_typed_and_retry_after_is_bounded():
    http = FakeHttp(
        [
            FakeResponse(status_code=200),
            FakeResponse(
                status_code=429,
                headers={"Retry-After": "17"},
            ),
        ]
    )

    client = make_client(http)

    with pytest.raises(QobuzCatalogError) as exc:
        client.request_json(
            "/album/get",
            method_name="albumget",
            params={"album_id": "x"},
        )

    assert exc.value.code == "rate_limited"
    assert exc.value.transient is True
    assert exc.value.retry_after == 17


def test_timeout_has_one_deterministic_retry():
    sleeps = []

    http = FakeHttp(
        [
            FakeResponse(status_code=200),
            requests.exceptions.Timeout("synthetic"),
            FakeResponse(payload={"id": "ok"}),
        ]
    )

    client = make_client(
        http,
        sleep=lambda value: sleeps.append(value),
    )

    payload = client.request_json(
        "/album/get",
        method_name="albumget",
        params={"album_id": "x"},
    )

    assert payload == {"id": "ok"}
    assert sleeps == [0.25]
    assert len(http.calls) == 3


def test_retryable_503_has_one_deterministic_retry():
    sleeps = []

    http = FakeHttp(
        [
            FakeResponse(status_code=200),
            FakeResponse(status_code=503),
            FakeResponse(payload={"ok": True}),
        ]
    )

    client = make_client(
        http,
        sleep=lambda value: sleeps.append(value),
    )

    payload = client.request_json(
        "/album/get",
        method_name="albumget",
        params={"album_id": "x"},
    )

    assert payload == {"ok": True}
    assert sleeps == [0.25]


def test_malformed_json_isolated_without_raw_body():
    http = FakeHttp(
        [
            FakeResponse(status_code=200),
            FakeResponse(
                json_error=ValueError(
                    "synthetic raw body must not escape"
                )
            ),
        ]
    )

    client = make_client(http)

    with pytest.raises(QobuzCatalogError) as exc:
        client.request_json(
            "/album/get",
            method_name="albumget",
            params={"album_id": "x"},
        )

    assert exc.value.code == "malformed_response"
    assert "synthetic raw body" not in str(exc.value)


def test_bundle_rotation_forces_secret_revalidation():
    current = {
        "value": metadata(
            ["11111111111111111111111111111111"],
            bundle_version="1",
        )
    }

    http = FakeHttp(
        [
            FakeResponse(status_code=200),
            FakeResponse(payload={"id": 1}),
            FakeResponse(status_code=200),
            FakeResponse(payload={"id": 2}),
        ]
    )

    client = QobuzCatalogClient(
        http_session=http,
        api_base_url=(
            "https://www.qobuz.com/api.json/0.2"
        ),
        metadata_loader=lambda: current["value"],
        token_loader=lambda: "UserToken123",
        now=lambda: 1234567890,
        sleep=lambda _seconds: None,
    )

    client.request_json(
        "/track/get",
        method_name="trackget",
        params={"track_id": "1"},
    )

    current["value"] = metadata(
        ["22222222222222222222222222222222"],
        bundle_version="2",
    )

    client.request_json(
        "/track/get",
        method_name="trackget",
        params={"track_id": "2"},
    )

    assert len(http.calls) == 4

    assert http.calls[0]["url"].endswith(
        "/track/getFileUrl"
    )
    assert http.calls[2]["url"].endswith(
        "/track/getFileUrl"
    )


def test_backend_status_never_exposes_catalog_secrets(tmp_path):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._service_metadata = metadata(
        ["TopSecretCatalogValue123456789"]
    )

    rendered = repr(backend.status())

    assert "TopSecretCatalogValue123456789" not in rendered
    assert "app_secrets" not in rendered
    assert "private_key" not in rendered


def test_backend_catalog_wrapper_uses_authenticated_boundary(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend._catalog_request(
            "/favorite/getUserFavorites",
            method_name="favoritegetUserFavorites",
            params={
                "type": "albums",
                "limit": "50",
                "offset": "0",
            },
            signature_params={},
            require_auth=True,
        )

    assert exc.value.code == "not_authenticated"


def test_q6d1_track_lookup_normalizes_queue_identity_quality_and_artwork(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "id": 5966783,
        "title": "Reference Track",
        "version": "Remastered",
        "work": "Reference Work",
        "isrc": "USABC1234567",
        "duration": 321,
        "track_number": 4,
        "media_number": 2,
        "performer": {
            "id": 77,
            "name": "Reference Artist",
        },
        "album": {
            "id": "album-abc",
            "title": "Reference Album",
            "image": {
                "small": "https://img/small.jpg",
                "large": "https://img/large.jpg",
                "mega": "https://img/mega.jpg",
            },
            "label": {
                "id": 9,
                "name": "Reference Label",
            },
            "genre": {
                "id": 10,
                "name": "Jazz",
            },
        },
        "hires": True,
        "hires_streamable": True,
        "maximum_sampling_rate": 96.0,
        "maximum_bit_depth": 24,
        "streamable": True,
        "parental_warning": True,
        "performers": "Reference Artist, MainArtist",
        "composer": {
            "id": 88,
            "name": "Reference Composer",
        },
        "copyright": "Reference Copyright",
        "raw_secret_field": "must-not-escape",
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    track = backend.get_track("5966783")

    assert calls == [
        (
            "/track/get",
            {
                "method_name": "trackget",
                "params": {
                    "track_id": "5966783",
                },
                "require_auth": True,
            },
        )
    ]

    assert track["source"] == "qobuz"
    assert track["provider_track_id"] == "5966783"
    assert track["id"] == "qobuz:5966783"

    assert track["title"] == "Reference Track"
    assert track["version"] == "Remastered"
    assert track["work"] == "Reference Work"

    assert track["artist"] == "Reference Artist"
    assert track["artist_id"] == "77"

    assert track["album"] == "Reference Album"
    assert track["album_id"] == "album-abc"

    assert track["duration"] == 321
    assert track["isrc"] == "USABC1234567"
    assert track["disc_number"] == 2
    assert track["track_number"] == 4
    assert track["explicit"] is True
    assert track["streamable"] is True

    assert track["artwork"]["url"] == "https://img/mega.jpg"
    assert track["artwork_url"] == "https://img/mega.jpg"

    assert track["quality"] == {
        "hires": True,
        "hires_streamable": True,
        "maximum_sampling_rate_khz": 96.0,
        "maximum_bit_depth": 24,
    }

    assert track["format_availability"] == {
        "streamable": True,
        "hires_streamable": True,
    }

    assert track["composer"] == {
        "id": "88",
        "name": "Reference Composer",
    }

    rendered = repr(track)
    assert "must-not-escape" not in rendered
    assert "raw_secret_field" not in rendered


def test_q6d1_album_lookup_prefers_modern_quality_and_preserves_track_order(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "id": "album-xyz",
        "title": "Parent Album",
        "version": "Deluxe Edition",
        "artist": {
            "id": 700,
            "name": "Album Artist",
        },
        "image": {
            "thumbnail": "https://img/thumb.jpg",
            "large": "https://img/large.jpg",
            "extralarge": "https://img/xl.jpg",
        },
        "release_date_original": "1999-01-01",
        "release_date_stream": "2000-01-01",
        "dates": {
            "original": "2025-01-02",
            "stream": "2025-01-03",
        },
        "streamable": True,
        "label": {
            "id": 33,
            "name": "Album Label",
        },
        "genre": {
            "id": 44,
            "name": "Classical",
        },
        "tracks_count": 99,
        "track_count": 2,
        "duration": 600,
        "hires": True,
        "hires_streamable": True,
        "maximum_sampling_rate": 44.1,
        "maximum_bit_depth": 16,
        "audio_info": {
            "maximum_sampling_rate": 192.0,
            "maximum_bit_depth": 24,
            "maximum_channel_count": 2,
        },
        "upc": "123456789012",
        "description": "Album description",
        "parental_warning": False,
        "tracks": {
            "items": [
                {
                    "id": 101,
                    "title": "First",
                    "duration": 100,
                    "track_number": 1,
                    "media_number": 1,
                    "performer": {
                        "id": 701,
                        "name": "Track Artist",
                    },
                    "streamable": True,
                    "hires": True,
                    "hires_streamable": True,
                    "maximum_sampling_rate": 192.0,
                    "maximum_bit_depth": 24,
                },
                {
                    "id": 102,
                    "title": "Second",
                    "duration": 200,
                    "track_number": 2,
                    "media_number": 1,
                    "streamable": True,
                    "hires": True,
                    "hires_streamable": True,
                    "maximum_sampling_rate": 192.0,
                    "maximum_bit_depth": 24,
                },
            ]
        },
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    album = backend.get_album("album-xyz")

    assert calls == [
        (
            "/album/get",
            {
                "method_name": "albumget",
                "params": {
                    "album_id": "album-xyz",
                },
                "require_auth": True,
            },
        )
    ]

    assert album["source"] == "qobuz"
    assert album["album_id"] == "album-xyz"
    assert album["title"] == "Parent Album"
    assert album["version"] == "Deluxe Edition"

    assert album["artist"] == "Album Artist"
    assert album["artist_id"] == "700"

    assert album["artwork"]["url"] == "https://img/xl.jpg"
    assert album["artwork_url"] == "https://img/xl.jpg"

    assert album["release_date"] == "2025-01-02"
    assert album["release_date_original"] == "2025-01-02"
    assert album["release_date_stream"] == "2025-01-03"

    assert album["track_count"] == 2
    assert album["duration"] == 600

    assert album["quality"] == {
        "hires": True,
        "hires_streamable": True,
        "maximum_sampling_rate_khz": 192.0,
        "maximum_bit_depth": 24,
        "maximum_channel_count": 2,
    }

    assert album["label"] == {
        "id": "33",
        "name": "Album Label",
    }

    assert album["genre"] == {
        "id": "44",
        "name": "Classical",
    }

    assert [
        track["id"]
        for track in album["tracks"]
    ] == [
        "qobuz:101",
        "qobuz:102",
    ]

    first = album["tracks"][0]
    second = album["tracks"][1]

    assert first["artist"] == "Track Artist"
    assert first["artist_id"] == "701"

    assert first["album"] == "Parent Album"
    assert first["album_id"] == "album-xyz"
    assert first["artwork_url"] == "https://img/xl.jpg"

    # The second shallow album track has no performer, so the
    # parent album artist is the correct provider-context fallback.
    assert second["artist"] == "Album Artist"
    assert second["artist_id"] == "700"

    assert second["album"] == "Parent Album"
    assert second["album_id"] == "album-xyz"
    assert second["artwork_url"] == "https://img/xl.jpg"


def test_q6d1_artist_lookup_normalizes_identity_and_exact_lang_contract(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "id": 1234,
        "name": "Reference Artist",
        "image": {
            "small": "https://img/small.jpg",
            "mega": "https://img/mega.jpg",
        },
        "albums_count": 42,
        "biography": {
            "content": "must not escape raw model",
        },
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    artist = backend.get_artist(
        1234,
        lang="EN",
    )

    assert calls == [
        (
            "/artist/get",
            {
                "method_name": "artistget",
                "params": {
                    "artist_id": "1234",
                    "lang": "en",
                },
                "require_auth": True,
            },
        )
    ]

    assert artist == {
        "source": "qobuz",
        "artist_id": "1234",
        "name": "Reference Artist",
        "artwork": {
            "url": "https://img/mega.jpg",
            "small": "https://img/small.jpg",
            "mega": "https://img/mega.jpg",
        },
        "artwork_url": "https://img/mega.jpg",
        "albums_count": 42,
    }


@pytest.mark.parametrize(
    "method,args",
    [
        ("get_track", ("abc",)),
        ("get_track", (0,)),
        ("get_artist", ("x",)),
        ("get_artist", (-1,)),
        ("get_album", ("",)),
        ("get_album", ("bad album id",)),
    ],
)
def test_q6d1_invalid_lookup_ids_fail_before_catalog_request(
    tmp_path,
    method,
    args,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError(
            "catalog request must not occur"
        )

    backend._catalog_request = unexpected

    with pytest.raises(QobuzCatalogError) as exc:
        getattr(backend, method)(*args)

    assert exc.value.code == "invalid_request"


def test_q6d1_invalid_artist_language_fails_before_catalog_request(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError(
            "catalog request must not occur"
        )

    backend._catalog_request = unexpected

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist(
            1234,
            lang="english",
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "method,payload",
    [
        (
            "_normalize_qobuz_track",
            {
                "id": 0,
                "title": "Bad",
            },
        ),
        (
            "_normalize_qobuz_album",
            {
                "id": "",
                "title": "Bad",
            },
        ),
        (
            "_normalize_qobuz_artist",
            {
                "id": "not-numeric",
                "name": "Bad",
            },
        ),
    ],
)
def test_q6d1_malformed_lookup_identity_is_isolated(
    method,
    payload,
):
    with pytest.raises(QobuzCatalogError) as exc:
        getattr(
            QobuzBackend,
            method,
        )(payload)

    assert exc.value.code == "malformed_response"


def test_q6d1_known_text_fields_never_stringify_nested_raw_payloads():
    marker = "nested-provider-value-must-not-escape"

    track = QobuzBackend._normalize_qobuz_track(
        {
            "id": 123,
            "title": {
                "secret_like": marker,
            },
            "performer": {
                "id": 77,
                "name": {
                    "unexpected": marker,
                },
            },
            "album": {
                "id": "album-safe",
                "title": [
                    marker,
                ],
                "image": {
                    "mega": {
                        "unexpected": marker,
                    },
                },
            },
            "streamable": True,
        }
    )

    assert track["id"] == "qobuz:123"
    assert track["provider_track_id"] == "123"

    assert track["title"] == ""
    assert track["artist"] == ""
    assert track["artist_id"] == "77"

    assert track["album"] == ""
    assert track["album_id"] == "album-safe"

    assert track["artwork"] is None
    assert track["artwork_url"] is None

    assert marker not in repr(track)


def test_q6d1_malformed_boolean_values_never_invent_provider_truth():
    track = QobuzBackend._normalize_qobuz_track(
        {
            "id": 123,
            "title": "Boolean Boundary",
            "hires": "false",
            "hires_streamable": 1,
            "streamable": "true",
            "parental_warning": "false",
        }
    )

    assert track["quality"] == {
        "hires": False,
        "hires_streamable": False,
        "maximum_sampling_rate_khz": None,
        "maximum_bit_depth": None,
    }

    assert track["format_availability"] == {
        "streamable": False,
        "hires_streamable": False,
    }

    assert track["streamable"] is False
    assert track["explicit"] is False

    album = QobuzBackend._normalize_qobuz_album(
        {
            "id": "album-bool",
            "title": "Boolean Boundary",
            "artist": {
                "id": 77,
                "name": "Artist",
            },
            "hires": "false",
            "hires_streamable": 1,
        }
    )

    assert album["hires"] is False
    assert album["hires_streamable"] is False
    assert album["quality"]["hires"] is False
    assert album["quality"]["hires_streamable"] is False


def test_q6e1_library_albums_uses_exact_favorites_contract_and_order(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "albums": {
            "items": [
                {
                    "id": "album-a",
                    "title": "First Album",
                    "artist": {
                        "id": 10,
                        "name": "Artist One",
                    },
                    "image": {
                        "large": "https://img/a.jpg",
                    },
                    "tracks_count": 9,
                    "hires": True,
                    "hires_streamable": True,
                    "maximum_sampling_rate": 96.0,
                    "maximum_bit_depth": 24,
                },
                {
                    "id": "album-b",
                    "title": "Second Album",
                    "artist": {
                        "id": 20,
                        "name": "Artist Two",
                    },
                    "image": {
                        "mega": "https://img/b.jpg",
                    },
                    "tracks_count": 11,
                    "hires": False,
                    "hires_streamable": False,
                    "maximum_sampling_rate": 44.1,
                    "maximum_bit_depth": 16,
                },
            ],
            "total": 222,
            "offset": 25,
            "limit": 2,
        }
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    page = backend.get_library_albums(
        limit=2,
        offset=25,
    )

    assert calls == [
        (
            "/favorite/getUserFavorites",
            {
                "method_name": "favoritegetUserFavorites",
                "params": {
                    "type": "albums",
                    "limit": "2",
                    "offset": "25",
                },
                "signature_params": {},
                "require_auth": True,
            },
        )
    ]

    assert page["ok"] is True
    assert page["offset"] == 25
    assert page["limit"] == 2
    assert page["total"] == 222

    assert [
        item["album_id"]
        for item in page["items"]
    ] == [
        "album-a",
        "album-b",
    ]

    assert page["items"][0]["artist_id"] == "10"
    assert page["items"][0]["quality"][
        "maximum_sampling_rate_khz"
    ] == 96.0

    assert page["items"][1]["artist_id"] == "20"
    assert page["items"][1]["artwork_url"] == "https://img/b.jpg"


def test_q6e1_library_tracks_normalize_q5_identity_and_preserve_order(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "tracks": {
            "items": [
                {
                    "id": 301,
                    "title": "First Track",
                    "duration": 100,
                    "performer": {
                        "id": 31,
                        "name": "Artist A",
                    },
                    "album": {
                        "id": "album-301",
                        "title": "Album A",
                        "image": {
                            "large": "https://img/301.jpg",
                        },
                    },
                    "streamable": True,
                },
                {
                    "id": 302,
                    "title": "Second Track",
                    "duration": 200,
                    "performer": {
                        "id": 32,
                        "name": "Artist B",
                    },
                    "album": {
                        "id": "album-302",
                        "title": "Album B",
                        "image": {
                            "large": "https://img/302.jpg",
                        },
                    },
                    "streamable": True,
                },
            ],
            "total": 900,
        }
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    page = backend.get_library_tracks(
        limit=2,
        offset=50,
    )

    assert len(calls) == 1

    assert calls[0] == (
        "/favorite/getUserFavorites",
        {
            "method_name": "favoritegetUserFavorites",
            "params": {
                "type": "tracks",
                "limit": "2",
                "offset": "50",
            },
            "signature_params": {},
            "require_auth": True,
        },
    )

    assert page["total"] == 900
    assert page["offset"] == 50
    assert page["limit"] == 2

    assert [
        item["id"]
        for item in page["items"]
    ] == [
        "qobuz:301",
        "qobuz:302",
    ]

    assert [
        item["provider_track_id"]
        for item in page["items"]
    ] == [
        "301",
        "302",
    ]


def test_q6e1_library_artists_reuse_d1_normalizer(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    payload = {
        "artists": {
            "items": [
                {
                    "id": 701,
                    "name": "First Artist",
                    "image": {
                        "thumbnail": "https://img/701-small.jpg",
                        "mega": "https://img/701.jpg",
                    },
                    "albums_count": 20,
                },
                {
                    "id": 702,
                    "name": "Second Artist",
                    "image": None,
                    "albums_count": 5,
                },
            ],
            "total": 12,
        }
    }

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    page = backend.get_library_artists()

    assert calls == [
        (
            "/favorite/getUserFavorites",
            {
                "method_name": "favoritegetUserFavorites",
                "params": {
                    "type": "artists",
                    "limit": "50",
                    "offset": "0",
                },
                "signature_params": {},
                "require_auth": True,
            },
        )
    ]

    assert page["offset"] == 0
    assert page["limit"] == 50
    assert page["total"] == 12

    assert [
        item["artist_id"]
        for item in page["items"]
    ] == [
        "701",
        "702",
    ]

    assert page["items"][0]["artwork_url"] == "https://img/701.jpg"
    assert page["items"][1]["artwork"] is None


def test_q6e1_library_page_is_single_bounded_request_not_auto_pagination(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "Q6E library read must not auto-fetch another page"
            )

        return {
            "tracks": {
                "items": [
                    {
                        "id": 801,
                        "title": "One Page Only",
                        "streamable": True,
                    }
                ],
                "total": 10000,
            }
        }

    backend._catalog_request = request

    page = backend.get_library_tracks(
        limit=1,
        offset=500,
    )

    assert len(calls) == 1
    assert page["offset"] == 500
    assert page["limit"] == 1
    assert page["total"] == 10000
    assert page["items"][0]["id"] == "qobuz:801"


@pytest.mark.parametrize(
    "method",
    [
        "get_library_albums",
        "get_library_tracks",
        "get_library_artists",
    ],
)
def test_q6e1_library_requires_auth_before_network(
    tmp_path,
    method,
):
    http = FakeHttp()

    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=http,
        now=lambda: 1234567890,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        getattr(backend, method)()

    assert exc.value.code == "not_authenticated"
    assert http.calls == []


@pytest.mark.parametrize(
    "method,limit,offset",
    [
        ("get_library_albums", 0, 0),
        ("get_library_tracks", 101, 0),
        ("get_library_artists", 1, -1),
        ("get_library_tracks", "bad", 0),
    ],
)
def test_q6e1_library_invalid_pagination_fails_before_request(
    tmp_path,
    method,
    limit,
    offset,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError(
            "catalog request must not occur"
        )

    backend._catalog_request = unexpected

    with pytest.raises(QobuzCatalogError) as exc:
        getattr(backend, method)(
            limit=limit,
            offset=offset,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"albums": None},
        {"albums": {}},
        {
            "albums": {
                "items": "not-a-list",
                "total": 0,
            }
        },
        {
            "albums": {
                "items": [],
                "total": "not-an-integer",
            }
        },
        {
            "albums": {
                "items": [],
                "total": -1,
            }
        },
    ],
)
def test_q6e1_library_malformed_envelope_is_typed_and_isolated(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_library_albums()

    assert exc.value.code == "malformed_response"


def test_q6e1_library_does_not_copy_unknown_raw_envelope_fields(
    tmp_path,
):
    marker = "raw-envelope-marker-must-not-escape"

    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: {
        "albums": {
            "items": [
                {
                    "id": "safe-album",
                    "title": "Safe Album",
                    "artist": {
                        "id": 1,
                        "name": "Safe Artist",
                    },
                    "unknown": marker,
                }
            ],
            "total": 1,
            "unknown_branch_field": marker,
        },
        "unknown_root_field": marker,
    }

    result = backend.get_library_albums()

    rendered = repr(result)

    assert result["items"][0]["album_id"] == "safe-album"
    assert marker not in rendered
    assert "unknown_root_field" not in rendered
    assert "unknown_branch_field" not in rendered


def test_q6e1_library_rejects_provider_page_larger_than_requested_limit(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        return {
            "tracks": {
                "items": [
                    {
                        "id": 901,
                        "title": "First",
                        "streamable": True,
                    },
                    {
                        "id": 902,
                        "title": "Unexpected Extra",
                        "streamable": True,
                    },
                ],
                "total": 2,
            }
        }

    backend._catalog_request = request

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_library_tracks(
            limit=1,
            offset=0,
        )

    assert exc.value.code == "malformed_response"

    assert calls == [
        (
            "/favorite/getUserFavorites",
            {
                "method_name": "favoritegetUserFavorites",
                "params": {
                    "type": "tracks",
                    "limit": "1",
                    "offset": "0",
                },
                "signature_params": {},
                "require_auth": True,
            },
        )
    ]


def test_q6f1_album_search_exact_wire_contract_filter_and_order(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "albums": {
                "items": [
                    {
                        "id": "a1",
                        "title": "First",
                        "artist": {
                            "id": 11,
                            "name": "Artist One",
                        },
                    },
                    {
                        "id": "a2",
                        "title": "Second",
                        "artist": {
                            "id": 12,
                            "name": "Artist Two",
                        },
                    },
                ],
                "total": 77,
            }
        }
    )

    page = backend.search_albums(
        "  Miles Davis  ",
        limit=2,
        offset=4,
        search_type="MainArtist",
    )

    assert calls == [
        (
            "/album/search",
            {
                "method_name": "albumsearch",
                "params": {
                    "query": "Miles Davis",
                    "limit": "2",
                    "offset": "4",
                    "type": "MainArtist",
                },
                "signature_params": {
                    "limit": "2",
                    "offset": "4",
                    "query": "Miles Davis",
                    "type": "MainArtist",
                },
                "require_auth": True,
            },
        )
    ]

    assert page["ok"] is True
    assert page["query"] == "Miles Davis"
    assert page["search_type"] == "MainArtist"
    assert page["offset"] == 4
    assert page["limit"] == 2
    assert page["total"] == 77

    assert [
        item["album_id"]
        for item in page["items"]
    ] == ["a1", "a2"]


def test_q6f1_track_search_preserves_q5_canonical_identity(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "tracks": {
                "items": [
                    {
                        "id": 501,
                        "title": "First",
                        "streamable": True,
                    },
                    {
                        "id": 502,
                        "title": "Second",
                        "streamable": True,
                    },
                ],
                "total": 2,
            }
        }
    )

    page = backend.search_tracks(
        "query",
        limit=2,
    )

    assert calls[0][0] == "/track/search"
    assert calls[0][1]["method_name"] == "tracksearch"
    assert calls[0][1]["signature_params"] == {
        "limit": "2",
        "offset": "0",
        "query": "query",
    }

    assert [
        item["id"]
        for item in page["items"]
    ] == [
        "qobuz:501",
        "qobuz:502",
    ]


def test_q6f1_playlist_normalizer_uses_pinned_cover_precedence_and_dedupe():
    playlist = QobuzBackend._normalize_qobuz_playlist(
        {
            "id": 901,
            "name": "Reference Playlist",
            "description": "Description",
            "owner": {
                "id": 77,
                "name": "Owner",
            },
            "images300": [
                "https://img/one.jpg",
                "https://img/one.jpg",
                "",
                "https://img/two.jpg",
                "https://img/three.jpg",
                "https://img/four.jpg",
                "https://img/five.jpg",
            ],
            "images150": [
                "https://img/lower.jpg",
            ],
            "images": [
                "https://img/lowest.jpg",
            ],
            "tracks_count": 42,
            "duration": 3600,
            "is_public": True,
            "slug": "reference",
            "users_count": 99,
        }
    )

    assert playlist["source"] == "qobuz"
    assert playlist["playlist_id"] == "901"
    assert playlist["title"] == "Reference Playlist"
    assert playlist["owner_id"] == "77"
    assert playlist["owner_name"] == "Owner"

    assert playlist["cover_urls"] == [
        "https://img/one.jpg",
        "https://img/two.jpg",
        "https://img/three.jpg",
        "https://img/four.jpg",
    ]

    assert playlist["artwork_url"] == "https://img/one.jpg"
    assert "https://img/lower.jpg" not in playlist["cover_urls"]
    assert playlist["track_count"] == 42
    assert playlist["duration"] == 3600
    assert playlist["is_public"] is True
    assert playlist["users_count"] == 99


def test_q6f1_playlist_search_exact_provider_contract(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "playlists": {
                "items": [
                    {
                        "id": 44,
                        "name": "Playlist",
                        "owner": {
                            "id": 4,
                            "name": "Owner",
                        },
                    }
                ],
                "total": 1,
            }
        }
    )

    page = backend.search_playlists(
        "playlist search",
        limit=10,
        offset=20,
    )

    assert calls == [
        (
            "/playlist/search",
            {
                "method_name": "playlistsearch",
                "params": {
                    "query": "playlist search",
                    "limit": "10",
                    "offset": "20",
                },
                "signature_params": {
                    "limit": "10",
                    "offset": "20",
                    "query": "playlist search",
                },
                "require_auth": True,
            },
        )
    ]

    assert page["items"][0]["playlist_id"] == "44"
    assert page["total"] == 1


def test_q6f1_combined_catalog_search_normalizes_all_provider_sections(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "albums": {
            "items": [
                {
                    "id": "album-1",
                    "title": "Album",
                    "artist": {
                        "id": 1,
                        "name": "Artist",
                    },
                }
            ],
            "total": 10,
        },
        "tracks": {
            "items": [
                {
                    "id": 101,
                    "title": "Track",
                    "streamable": True,
                }
            ],
            "total": 20,
        },
        "artists": {
            "items": [
                {
                    "id": 201,
                    "name": "Artist",
                }
            ],
            "total": 30,
        },
        "playlists": {
            "items": [
                {
                    "id": 301,
                    "name": "Playlist",
                    "owner": {
                        "id": 3,
                        "name": "Owner",
                    },
                }
            ],
            "total": 40,
        },
        "most_popular": {
            "items": [
                {
                    "type": "unsupported",
                    "content": {
                        "id": 1,
                    },
                },
                {
                    "type": "tracks",
                    "content": {
                        "id": 999,
                        "title": "Most Popular",
                        "streamable": True,
                    },
                },
            ]
        },
    }

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or payload
    )

    result = backend.search_catalog(
        "  jazz  ",
        limit=5,
        offset=10,
    )

    assert calls == [
        (
            "/catalog/search",
            {
                "method_name": "catalogsearch",
                "params": {
                    "query": "jazz",
                    "limit": "5",
                    "offset": "10",
                },
                "signature_params": {
                    "limit": "5",
                    "offset": "10",
                    "query": "jazz",
                },
                "require_auth": True,
            },
        )
    ]

    assert result["query"] == "jazz"
    assert result["offset"] == 10
    assert result["limit"] == 5

    assert result["albums"]["items"][0]["album_id"] == "album-1"
    assert result["tracks"]["items"][0]["id"] == "qobuz:101"
    assert result["artists"]["items"][0]["artist_id"] == "201"
    assert result["playlists"]["items"][0]["playlist_id"] == "301"

    assert result["albums"]["total"] == 10
    assert result["tracks"]["total"] == 20
    assert result["artists"]["total"] == 30
    assert result["playlists"]["total"] == 40

    assert result["most_popular"]["type"] == "tracks"
    assert (
        result["most_popular"]["content"]["id"]
        == "qobuz:999"
    )


def test_q6f1_combined_search_missing_sections_follow_pinned_lenient_shape(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {}
    )

    result = backend.search_catalog(
        "minimal",
        limit=7,
        offset=3,
    )

    for key in (
        "albums",
        "tracks",
        "artists",
        "playlists",
    ):
        assert result[key] == {
            "items": [],
            "offset": 3,
            "limit": 7,
            "total": 0,
        }

    assert result["most_popular"] is None


def test_q6f1_combined_search_skips_malformed_rows_without_reordering_valid_rows(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: {
        "tracks": {
            "items": [
                {
                    "id": 701,
                    "title": "First",
                    "streamable": True,
                },
                {
                    "id": {},
                    "title": "Malformed",
                },
                {
                    "id": 703,
                    "title": "Third",
                    "streamable": True,
                },
            ],
            "total": 3,
        }
    }

    result = backend.search_catalog(
        "rows",
        limit=10,
    )

    assert [
        item["id"]
        for item in result["tracks"]["items"]
    ] == [
        "qobuz:701",
        "qobuz:703",
    ]

    assert result["tracks"]["total"] == 3


@pytest.mark.parametrize(
    "method,args",
    [
        ("search_albums", ("query",)),
        ("search_tracks", ("query",)),
        ("search_artists", ("query",)),
        ("search_playlists", ("query",)),
        ("search_catalog", ("query",)),
    ],
)
def test_q6f1_search_requires_auth_before_network(
    tmp_path,
    method,
    args,
):
    http = FakeHttp()

    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=http,
        now=lambda: 1234567890,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        getattr(backend, method)(*args)

    assert exc.value.code == "not_authenticated"
    assert http.calls == []


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        None,
        {"query": "bad"},
        "a" * 4097,
        "bad\x00query",
    ],
)
def test_q6f1_invalid_search_query_fails_before_request(
    tmp_path,
    query,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("catalog request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.search_tracks(query)

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "search_type",
    [
        "",
        "mainartist",
        "Artist",
        1,
        {},
    ],
)
def test_q6f1_invalid_provider_search_type_fails_before_request(
    tmp_path,
    search_type,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("catalog request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.search_albums(
            "query",
            search_type=search_type,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "method,key",
    [
        ("search_albums", "albums"),
        ("search_tracks", "tracks"),
        ("search_artists", "artists"),
        ("search_playlists", "playlists"),
    ],
)
def test_q6f1_typed_search_rejects_provider_page_larger_than_requested(
    tmp_path,
    method,
    key,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: {
        key: {
            "items": [
                {},
                {},
            ],
            "total": 2,
        }
    }

    with pytest.raises(QobuzCatalogError) as exc:
        getattr(backend, method)(
            "query",
            limit=1,
        )

    assert exc.value.code == "malformed_response"


def test_q6f1_combined_search_rejects_oversized_provider_section(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: {
        "artists": {
            "items": [
                {"id": 1, "name": "One"},
                {"id": 2, "name": "Two"},
            ],
            "total": 2,
        }
    }

    with pytest.raises(QobuzCatalogError) as exc:
        backend.search_catalog(
            "query",
            limit=1,
        )

    assert exc.value.code == "malformed_response"


def test_q6f1_playlist_unknown_provider_fields_never_escape_normalized_model():
    marker = "raw-playlist-marker-must-not-escape"

    playlist = QobuzBackend._normalize_qobuz_playlist(
        {
            "id": 55,
            "name": "Safe",
            "owner": {
                "id": 5,
                "name": "Owner",
                "unknown": marker,
            },
            "unknown_root": marker,
            "images300": [
                "https://img/safe.jpg",
            ],
        }
    )

    rendered = repr(playlist)

    assert playlist["playlist_id"] == "55"
    assert marker not in rendered
    assert "unknown_root" not in rendered


def test_q6g1a_genres_exact_wire_contract_and_normalization(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "genres": {
                "items": [
                    {
                        "id": 112,
                        "name": "Jazz",
                        "color": "#123456",
                        "slug": "jazz",
                        "path": [10, 112],
                        "unknown": "must-not-escape",
                    },
                    {
                        "id": 119,
                        "name": "Fusion",
                        "path": [10, 112, 119],
                    },
                ]
            }
        }
    )

    result = backend.get_genres(
        parent_id=10,
    )

    assert calls == [
        (
            "/genre/list",
            {
                "method_name": "genrelist",
                "params": {
                    "lang": "en",
                    "parent_id": "10",
                },
                "signature_params": {
                    "lang": "en",
                    "parent_id": "10",
                },
                "require_auth": False,
            },
        )
    ]

    assert result["ok"] is True
    assert result["parent_id"] == "10"

    assert result["items"] == [
        {
            "source": "qobuz",
            "genre_id": "112",
            "name": "Jazz",
            "color": "#123456",
            "slug": "jazz",
            "path": ["10", "112"],
        },
        {
            "source": "qobuz",
            "genre_id": "119",
            "name": "Fusion",
            "color": None,
            "slug": None,
            "path": ["10", "112", "119"],
        },
    ]

    assert "must-not-escape" not in repr(result)


def test_q6g1a_genres_root_uses_exact_lang_only_contract(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "genres": {
                "items": [],
            }
        }
    )

    result = backend.get_genres()

    assert calls == [
        (
            "/genre/list",
            {
                "method_name": "genrelist",
                "params": {
                    "lang": "en",
                },
                "signature_params": {
                    "lang": "en",
                },
                "require_auth": False,
            },
        )
    ]

    assert result == {
        "ok": True,
        "parent_id": None,
        "items": [],
    }


def test_q6g1a_discover_index_exact_contract_and_normalized_sections(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    album = {
        "id": "discover-album-1",
        "title": "Discover Album",
        "version": "Deluxe",
        "track_count": 9,
        "duration": 3000,
        "parental_warning": False,
        "image": {
            "small": "https://img/small.jpg",
            "thumbnail": "https://img/thumb.jpg",
            "large": "https://img/large.jpg",
        },
        "artists": [
            {
                "id": 101,
                "name": "Primary Artist",
                "roles": ["main-artist"],
            },
            {
                "id": 102,
                "name": "Second Artist",
                "roles": ["featured-artist"],
            },
        ],
        "genre": {
            "id": 112,
            "name": "Jazz",
        },
        "dates": {
            "download": "2026-01-02",
            "stream": "2026-01-03",
        },
        "audio_info": {
            "maximum_sampling_rate": 192.0,
            "maximum_bit_depth": 24,
            "maximum_channel_count": 2,
        },
        "awards": [
            {
                "id": 88,
                "name": "Qobuzissime",
                "awarded_at": "2026-02-01",
            }
        ],
        "unknown_album_field": "must-not-escape",
    }

    playlist = {
        "id": 501,
        "name": "Editorial Playlist",
        "owner": {
            "id": 9,
            "name": "Qobuz",
        },
        "image": {
            "rectangle": "https://img/rectangle.jpg",
            "covers": [
                "https://img/cover1.jpg",
                "https://img/cover2.jpg",
            ],
        },
        "description": "Editorial description",
        "duration": 7200,
        "tracks_count": 40,
        "genres": [
            {
                "id": 112,
                "name": "Jazz",
                "slug": "jazz",
            }
        ],
        "tags": [
            {
                "id": 1,
                "slug": "editorial",
                "name": "Editorial",
            },
            {
                "id": 2,
                "slug": "label",
                "name": "Label",
            },
        ],
        "unknown_playlist_field": "must-not-escape",
    }

    tag = {
        "id": 7,
        "slug": "partner",
        "name": "Partner",
    }

    def container(container_id, item):
        return {
            "id": container_id,
            "data": {
                "has_more": True,
                "items": [item],
            },
        }

    payload = {
        "containers": {
            "playlists": container(
                "qobuzPlaylists",
                playlist,
            ),
            "ideal_discography": container(
                "idealDiscography",
                album,
            ),
            "playlists_tags": container(
                "playlistTags",
                tag,
            ),
            "new_releases": container(
                "newReleases",
                album,
            ),
            "qobuzissims": container(
                "qobuzissims",
                album,
            ),
            "most_streamed": container(
                "mostStreamed",
                album,
            ),
            "press_awards": container(
                "pressAwards",
                album,
            ),
            "album_of_the_week": container(
                "albumOfTheWeek",
                album,
            ),
            "unknown_container": {
                "raw": "must-not-escape",
            },
        },
        "unknown_root": "must-not-escape",
    }

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or payload
    )

    result = backend.get_discover_index(
        genre_ids=[112, "119"],
    )

    assert calls == [
        (
            "/discover/index",
            {
                "method_name": "discoverindex",
                "params": {
                    "genre_ids": "112,119",
                },
                "signature_params": {
                    "genre_ids": "112,119",
                },
                "require_auth": True,
            },
        )
    ]

    assert result["ok"] is True
    assert result["genre_ids"] == [
        "112",
        "119",
    ]

    assert list(result["containers"]) == [
        "playlists",
        "ideal_discography",
        "playlists_tags",
        "new_releases",
        "qobuzissims",
        "most_streamed",
        "press_awards",
        "album_of_the_week",
    ]

    discovered_album = (
        result["containers"]
        ["new_releases"]
        ["items"][0]
    )

    assert discovered_album["album_id"] == "discover-album-1"
    assert discovered_album["artist"] == "Primary Artist"
    assert discovered_album["artist_id"] == "101"
    assert discovered_album["artwork_url"] == "https://img/large.jpg"
    assert discovered_album["release_date"] == "2026-01-02"
    assert discovered_album["release_date_download"] == "2026-01-02"
    assert discovered_album["track_count"] == 9

    assert discovered_album["quality"] == {
        "hires": False,
        "hires_streamable": False,
        "maximum_sampling_rate_khz": 192.0,
        "maximum_bit_depth": 24,
        "maximum_channel_count": 2,
    }

    assert discovered_album["artists"] == [
        {
            "id": "101",
            "name": "Primary Artist",
            "roles": ["main-artist"],
        },
        {
            "id": "102",
            "name": "Second Artist",
            "roles": ["featured-artist"],
        },
    ]

    assert discovered_album["awards"] == [
        {
            "id": "88",
            "name": "Qobuzissime",
            "awarded_at": "2026-02-01",
        }
    ]

    discovered_playlist = (
        result["containers"]
        ["playlists"]
        ["items"][0]
    )

    assert discovered_playlist["playlist_id"] == "501"
    assert discovered_playlist["artwork_url"] == (
        "https://img/rectangle.jpg"
    )
    assert discovered_playlist["cover_urls"] == [
        "https://img/cover1.jpg",
        "https://img/cover2.jpg",
    ]
    assert discovered_playlist["category"] == "Editorial"
    assert discovered_playlist["tag_slugs"] == [
        "editorial",
        "label",
    ]
    assert discovered_playlist["track_count"] == 40

    assert discovered_playlist["genres"] == [
        {
            "id": "112",
            "name": "Jazz",
            "slug": "jazz",
        }
    ]

    discovered_tag = (
        result["containers"]
        ["playlists_tags"]
        ["items"][0]
    )

    assert discovered_tag == {
        "id": "7",
        "slug": "partner",
        "name": "Partner",
    }

    rendered = repr(result)

    assert "unknown_root" not in rendered
    assert "unknown_container" not in rendered
    assert "unknown_album_field" not in rendered
    assert "unknown_playlist_field" not in rendered
    assert "must-not-escape" not in rendered


def test_q6g1a_discover_playlist_falls_back_to_first_cover():
    playlist = (
        QobuzBackend._normalize_qobuz_discover_playlist(
            {
                "id": 77,
                "name": "Cover Fallback",
                "owner": {
                    "id": 1,
                    "name": "Qobuz",
                },
                "image": {
                    "rectangle": None,
                    "covers": [
                        "https://img/first.jpg",
                        "https://img/second.jpg",
                    ],
                },
                "duration": 10,
                "tracks_count": 2,
            }
        )
    )

    assert playlist["artwork_url"] == (
        "https://img/first.jpg"
    )

    assert playlist["rectangle_artwork_url"] is None
    assert playlist["cover_urls"] == [
        "https://img/first.jpg",
        "https://img/second.jpg",
    ]


def test_q6g1a_discover_album_artwork_and_date_precedence():
    album = QobuzBackend._normalize_qobuz_discover_album(
        {
            "id": "precedence-album",
            "title": "Precedence",
            "image": {
                "small": "https://img/small.jpg",
                "thumbnail": "https://img/thumb.jpg",
            },
            "artists": [
                {
                    "id": 1,
                    "name": "Artist",
                }
            ],
            "dates": {
                "original": "2020-01-01",
                "download": "2021-01-01",
                "stream": "2022-01-01",
            },
        }
    )

    assert album["artwork_url"] == (
        "https://img/thumb.jpg"
    )
    assert album["release_date"] == "2020-01-01"


def test_q6g1a_discover_missing_optional_containers_are_none(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "containers": {},
        }
    )

    result = backend.get_discover_index()

    assert result["genre_ids"] == []

    assert result["containers"] == {
        "playlists": None,
        "ideal_discography": None,
        "playlists_tags": None,
        "new_releases": None,
        "qobuzissims": None,
        "most_streamed": None,
        "press_awards": None,
        "album_of_the_week": None,
    }


@pytest.mark.parametrize(
    "genre_ids",
    [
        "112",
        112,
        {},
        [0],
        [-1],
        [True],
        ["x"],
        [""],
    ],
)
def test_q6g1a_invalid_discover_genre_ids_fail_before_request(
    tmp_path,
    genre_ids,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("catalog request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_discover_index(
            genre_ids=genre_ids,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "parent_id",
    [
        0,
        -1,
        True,
        "x",
        "",
        {},
    ],
)
def test_q6g1a_invalid_genre_parent_fails_before_request(
    tmp_path,
    parent_id,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("catalog request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_genres(
            parent_id=parent_id,
        )

    assert exc.value.code == "invalid_request"


def test_q6g1a_discover_index_requires_auth_before_network(
    tmp_path,
):
    http = FakeHttp()

    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=http,
        now=lambda: 1234567890,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_discover_index()

    assert exc.value.code == "not_authenticated"
    assert http.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"containers": []},
        {
            "containers": {
                "new_releases": [],
            }
        },
        {
            "containers": {
                "new_releases": {
                    "id": "newReleases",
                    "data": {
                        "has_more": "yes",
                        "items": [],
                    },
                },
            }
        },
        {
            "containers": {
                "new_releases": {
                    "id": "newReleases",
                    "data": {
                        "has_more": False,
                        "items": {},
                    },
                },
            }
        },
    ],
)
def test_q6g1a_malformed_discover_envelope_is_isolated(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_discover_index()

    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    "endpoint,method_name",
    [
        (
            "/discover/newReleases",
            "discovernewReleases",
        ),
        (
            "/discover/idealDiscography",
            "discoveridealDiscography",
        ),
        (
            "/discover/mostStreamed",
            "discovermostStreamed",
        ),
        (
            "/discover/qobuzissims",
            "discoverqobuzissims",
        ),
        (
            "/discover/albumOfTheWeek",
            "discoveralbumOfTheWeek",
        ),
        (
            "/discover/pressAward",
            "discoverpressAward",
        ),
    ],
)
def test_q6g1b_discover_album_browse_exact_allowlisted_wire_contract(
    tmp_path,
    endpoint,
    method_name,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "has_more": True,
            "items": [
                {
                    "id": "discover-album-1",
                    "title": "Discover Album",
                    "artists": [
                        {
                            "id": 11,
                            "name": "Discover Artist",
                            "roles": [
                                "main-artist",
                            ],
                        }
                    ],
                    "image": {
                        "large": "https://img/large.jpg",
                    },
                    "dates": {
                        "original": "2026-01-02",
                    },
                    "audio_info": {
                        "maximum_sampling_rate": 96.0,
                        "maximum_bit_depth": 24,
                        "maximum_channel_count": 2,
                    },
                }
            ],
        }
    )

    result = backend.get_discover_albums(
        endpoint,
        genre_ids=[
            112,
            "119",
        ],
        limit=2,
        offset=4,
    )

    assert calls == [
        (
            endpoint,
            {
                "method_name": method_name,
                "params": {
                    "genre_ids": "112,119",
                    "offset": "4",
                    "limit": "2",
                },
                "signature_params": {
                    "genre_ids": "112,119",
                    "offset": "4",
                    "limit": "2",
                },
                "require_auth": True,
            },
        )
    ]

    assert result["ok"] is True
    assert result["endpoint"] == endpoint
    assert result["genre_ids"] == [
        "112",
        "119",
    ]
    assert result["offset"] == 4
    assert result["limit"] == 2
    assert result["has_more"] is True

    assert [
        item["album_id"]
        for item in result["items"]
    ] == [
        "discover-album-1",
    ]

    assert (
        result["items"][0]["artwork_url"]
        == "https://img/large.jpg"
    )
    assert (
        result["items"][0]["quality"][
            "maximum_sampling_rate_khz"
        ]
        == 96.0
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "/discover/index",
        "/discover/playlists",
        "/discover/notReal",
        None,
        123,
        {},
    ],
)
def test_q6g1b_invalid_discover_album_endpoint_fails_before_request(
    tmp_path,
    endpoint,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("catalog request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_discover_albums(
            endpoint,
        )

    assert exc.value.code == "invalid_request"


def test_q6g1b_discover_playlist_browse_exact_wire_contract_and_model(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "has_more": True,
            "items": [
                {
                    "id": 901,
                    "name": "Editorial Playlist",
                    "description": "Provider description",
                    "owner": {
                        "id": 77,
                        "name": "Qobuz",
                    },
                    "image": {
                        "rectangle": (
                            "https://img/rectangle.jpg"
                        ),
                        "covers": [
                            "https://img/cover1.jpg",
                            "https://img/cover2.jpg",
                        ],
                    },
                    "duration": 3600,
                    "tracks_count": 25,
                    "tags": [
                        {
                            "id": 8,
                            "slug": "label",
                            "name": "Label",
                        }
                    ],
                    "genres": [
                        {
                            "id": 112,
                            "name": "Jazz",
                            "slug": "jazz",
                        }
                    ],
                }
            ],
        }
    )

    result = backend.get_discover_playlists(
        tag="  label  ",
        genre_ids=[
            112,
            119,
        ],
        limit=10,
        offset=20,
    )

    assert calls == [
        (
            "/discover/playlists",
            {
                "method_name": "discoverplaylists",
                "params": {
                    "tags": "label",
                    "genre_ids": "112,119",
                    "limit": "10",
                    "offset": "20",
                },
                "signature_params": {
                    "tags": "label",
                    "genre_ids": "112,119",
                    "limit": "10",
                    "offset": "20",
                },
                "require_auth": True,
            },
        )
    ]

    assert result["ok"] is True
    assert result["tag"] == "label"
    assert result["genre_ids"] == [
        "112",
        "119",
    ]
    assert result["offset"] == 20
    assert result["limit"] == 10
    assert result["has_more"] is True

    playlist = result["items"][0]

    assert playlist["playlist_id"] == "901"
    assert playlist["title"] == "Editorial Playlist"
    assert playlist["owner_id"] == "77"
    assert playlist["owner_name"] == "Qobuz"
    assert (
        playlist["artwork_url"]
        == "https://img/rectangle.jpg"
    )
    assert playlist["tag_slugs"] == [
        "label",
    ]
    assert playlist["category"] == "Label"
    assert playlist["genres"] == [
        {
            "id": "112",
            "name": "Jazz",
            "slug": "jazz",
        }
    ]


def test_q6g1b_discover_playlists_default_page_is_one_c2_bounded_request(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "has_more": True,
            "items": [],
        }
    )

    result = backend.get_discover_playlists()

    assert calls == [
        (
            "/discover/playlists",
            {
                "method_name": "discoverplaylists",
                "params": {
                    "limit": "50",
                    "offset": "0",
                },
                "signature_params": {
                    "limit": "50",
                    "offset": "0",
                },
                "require_auth": True,
            },
        )
    ]

    assert result == {
        "ok": True,
        "tag": None,
        "genre_ids": [],
        "items": [],
        "offset": 0,
        "limit": 50,
        "has_more": True,
    }


@pytest.mark.parametrize(
    "tag",
    [
        "",
        "   ",
        1,
        {},
        [],
        "bad\x00tag",
        "x" * 4097,
    ],
)
def test_q6g1b_invalid_discover_playlist_tag_fails_before_request(
    tmp_path,
    tag,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("catalog request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_discover_playlists(
            tag=tag,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "method,args,kwargs",
    [
        (
            "get_discover_albums",
            (
                "/discover/newReleases",
            ),
            {},
        ),
        (
            "get_discover_playlists",
            (),
            {},
        ),
    ],
)
def test_q6g1b_discover_browse_requires_auth_before_network(
    tmp_path,
    method,
    args,
    kwargs,
):
    http = FakeHttp()

    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=http,
        now=lambda: 1234567890,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        getattr(
            backend,
            method,
        )(
            *args,
            **kwargs,
        )

    assert exc.value.code == "not_authenticated"
    assert http.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "has_more": "true",
            "items": [],
        },
        {
            "has_more": True,
            "items": {},
        },
        {
            "has_more": None,
            "items": [],
        },
        [],
    ],
)
def test_q6g1b_discover_page_envelope_is_strict_and_isolated(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_discover_albums(
            "/discover/newReleases",
            limit=10,
        )

    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    "surface",
    [
        "albums",
        "playlists",
    ],
)
def test_q6g1b_discover_browse_rejects_provider_page_larger_than_requested(
    tmp_path,
    surface,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: {
        "has_more": True,
        "items": [
            {},
            {},
        ],
    }

    with pytest.raises(QobuzCatalogError) as exc:
        if surface == "albums":
            backend.get_discover_albums(
                "/discover/newReleases",
                limit=1,
            )
        else:
            backend.get_discover_playlists(
                limit=1,
            )

    assert exc.value.code == "malformed_response"


def test_q6g1b_discover_album_page_preserves_provider_order_without_auto_paging(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "has_more": True,
            "items": [
                {
                    "id": "first",
                    "title": "First",
                    "artists": [
                        {
                            "id": 1,
                            "name": "Artist One",
                        }
                    ],
                },
                {
                    "id": "second",
                    "title": "Second",
                    "artists": [
                        {
                            "id": 2,
                            "name": "Artist Two",
                        }
                    ],
                },
            ],
        }
    )

    result = backend.get_discover_albums(
        "/discover/mostStreamed",
        limit=2,
        offset=100,
    )

    assert len(calls) == 1

    assert [
        item["album_id"]
        for item in result["items"]
    ] == [
        "first",
        "second",
    ]

    assert result["offset"] == 100
    assert result["limit"] == 2
    assert result["has_more"] is True


def test_q6g1b_discover_browse_does_not_copy_unknown_provider_fields():
    marker = "q6g1b-raw-provider-marker-must-not-escape"

    album_page = QobuzBackend._normalize_qobuz_discover_page(
        {
            "has_more": False,
            "items": [
                {
                    "id": "safe-album",
                    "title": "Safe Album",
                    "artists": [
                        {
                            "id": 1,
                            "name": "Safe Artist",
                            "unknown": marker,
                        }
                    ],
                    "unknown": marker,
                }
            ],
            "unknown_root": marker,
        },
        QobuzBackend._normalize_qobuz_discover_album,
        page_limit=10,
        page_offset=0,
        label="album browse",
    )

    rendered = repr(album_page)

    assert album_page["items"][0]["album_id"] == "safe-album"
    assert marker not in rendered
    assert "unknown_root" not in rendered


# ============================================================
# Q6G2A_RELEASE_WATCH_TESTS_BEGIN
# ============================================================

def test_q6g2a_unsigned_authenticated_request_uses_no_signature_or_secret():
    http = FakeHttp(
        [
            FakeResponse(
                payload={
                    "has_more": False,
                    "items": [],
                }
            )
        ]
    )

    client = QobuzCatalogClient(
        http_session=http,
        api_base_url="https://www.qobuz.com/api.json/0.2",
        metadata_loader=lambda: {
            "app_id": "123456789",
        },
        token_loader=lambda: "UserToken123",
        now=lambda: (_ for _ in ()).throw(
            AssertionError(
                "unsigned request must not use request clock"
            )
        ),
        sleep=lambda _seconds: None,
    )

    payload = client.request_json(
        "/favorite/getNewReleases",
        method_name="favoritegetNewReleases",
        params={
            "type": "artists",
            "limit": "50",
            "offset": "0",
        },
        require_auth=True,
        signed=False,
    )

    assert payload == {
        "has_more": False,
        "items": [],
    }

    assert len(http.calls) == 1

    request = http.calls[0]

    assert request["url"].endswith(
        "/favorite/getNewReleases"
    )

    assert request["params"] == {
        "type": "artists",
        "limit": "50",
        "offset": "0",
    }

    assert "request_ts" not in request["params"]
    assert "request_sig" not in request["params"]

    assert request["headers"] == {
        "X-App-Id": "123456789",
        "X-User-Auth-Token": "UserToken123",
    }


def test_q6g2a_unsigned_authenticated_request_fails_before_network_when_signed_out():
    http = FakeHttp()

    client = QobuzCatalogClient(
        http_session=http,
        api_base_url="https://www.qobuz.com/api.json/0.2",
        metadata_loader=lambda: {
            "app_id": "123456789",
        },
        token_loader=lambda: None,
        now=lambda: 1234567890,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        client.request_json(
            "/favorite/getNewReleases",
            method_name="favoritegetNewReleases",
            params={
                "type": "artists",
                "limit": "50",
                "offset": "0",
            },
            require_auth=True,
            signed=False,
        )

    assert exc.value.code == "not_authenticated"
    assert http.calls == []


def test_q6g2a_unsigned_request_rejects_signature_params():
    http = FakeHttp()

    client = make_client(http)

    with pytest.raises(QobuzCatalogError) as exc:
        client.request_json(
            "/favorite/getNewReleases",
            method_name="favoritegetNewReleases",
            params={
                "type": "artists",
                "limit": "50",
                "offset": "0",
            },
            signature_params={},
            require_auth=True,
            signed=False,
        )

    assert exc.value.code == "invalid_request"
    assert http.calls == []


def test_q6g2a_release_watch_exact_unsigned_wire_contract_and_artist_backfill(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "has_more": True,
        "items": [
            {
                "id": "rw-album-1",
                "title": "Release One",
                "artists": [
                    {
                        "id": 101,
                        "name": "Followed Artist",
                    }
                ],
                "image": {
                    "large": "https://img/release-one.jpg",
                },
                "tracks_count": 10,
                "maximum_sampling_rate": 96.0,
                "maximum_bit_depth": 24,
                "hires": True,
                "hires_streamable": True,
                "unknown_provider_field": "must-not-escape",
            },
            {
                "id": "rw-album-2",
                "title": "Release Two",
                "artist": {
                    "id": 202,
                    "name": "Legacy Artist",
                },
                "artists": [
                    {
                        "id": 999,
                        "name": "Must Not Override Singular Artist",
                    }
                ],
                "image": {
                    "mega": "https://img/release-two.jpg",
                },
            },
        ],
        "unknown_envelope_field": "must-not-escape",
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    page = backend.get_release_watch(
        "ARTISTS",
        limit=2,
        offset=25,
    )

    assert calls == [
        (
            "/favorite/getNewReleases",
            {
                "method_name": "favoritegetNewReleases",
                "params": {
                    "type": "artists",
                    "limit": "2",
                    "offset": "25",
                },
                "require_auth": True,
                "signed": False,
            },
        )
    ]

    assert page["ok"] is True
    assert page["release_type"] == "artists"
    assert page["offset"] == 25
    assert page["limit"] == 2
    assert page["has_more"] is True
    assert "total" not in page

    assert [
        item["album_id"]
        for item in page["items"]
    ] == [
        "rw-album-1",
        "rw-album-2",
    ]

    assert page["items"][0]["artist"] == "Followed Artist"
    assert page["items"][0]["artist_id"] == "101"

    assert page["items"][1]["artist"] == "Legacy Artist"
    assert page["items"][1]["artist_id"] == "202"

    assert page["items"][0]["quality"][
        "maximum_sampling_rate_khz"
    ] == 96.0

    rendered = repr(page)

    assert "must-not-escape" not in rendered
    assert "unknown_provider_field" not in rendered
    assert "unknown_envelope_field" not in rendered


@pytest.mark.parametrize(
    "release_type,expected",
    [
        ("artists", "artists"),
        (" ARTISTS ", "artists"),
        ("labels", "labels"),
        ("LABELS", "labels"),
        ("awards", "awards"),
    ],
)
def test_q6g2a_release_watch_type_allowlist_normalizes_valid_values(
    release_type,
    expected,
):
    assert (
        QobuzBackend._catalog_release_watch_type(
            release_type
        )
        == expected
    )


@pytest.mark.parametrize(
    "release_type",
    [
        None,
        "",
        "artist",
        "albums",
        "playlists",
        "following",
        1,
        [],
    ],
)
def test_q6g2a_invalid_release_watch_type_fails_before_request(
    tmp_path,
    release_type,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError(
            "Release Watch provider request must not occur"
        )

    backend._catalog_request = unexpected

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_release_watch(
            release_type,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "limit,offset",
    [
        (0, 0),
        (101, 0),
        ("bad", 0),
        (1, -1),
        (1, 1_000_001),
    ],
)
def test_q6g2a_invalid_release_watch_pagination_fails_before_request(
    tmp_path,
    limit,
    offset,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError(
            "Release Watch provider request must not occur"
        )

    backend._catalog_request = unexpected

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_release_watch(
            "artists",
            limit=limit,
            offset=offset,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {
            "has_more": "true",
            "items": [],
        },
        {
            "has_more": False,
            "items": None,
        },
        {
            "has_more": None,
            "items": [],
        },
    ],
)
def test_q6g2a_release_watch_envelope_is_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_release_watch(
            "artists",
            limit=5,
            offset=0,
        )

    assert exc.value.code == "malformed_response"


def test_q6g2a_release_watch_rejects_provider_page_larger_than_requested_limit(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "has_more": True,
            "items": [
                {
                    "id": "one",
                    "title": "One",
                },
                {
                    "id": "two",
                    "title": "Two",
                },
            ],
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_release_watch(
            "artists",
            limit=1,
            offset=0,
        )

    assert exc.value.code == "malformed_response"


def test_q6g2a_release_watch_is_one_bounded_page_without_auto_paging(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "Release Watch must not auto-fetch another page"
            )

        return {
            "has_more": True,
            "items": [
                {
                    "id": "single-release",
                    "title": "Single Release",
                    "artists": [
                        {
                            "id": 77,
                            "name": "Artist",
                        }
                    ],
                }
            ],
        }

    backend._catalog_request = request

    page = backend.get_release_watch(
        "labels",
        limit=1,
        offset=500,
    )

    assert len(calls) == 1
    assert page["release_type"] == "labels"
    assert page["offset"] == 500
    assert page["limit"] == 1
    assert page["has_more"] is True
    assert page["items"][0]["album_id"] == "single-release"
    assert "total" not in page


def test_q6g2a_release_watch_requires_auth_before_network(
    tmp_path,
):
    http = FakeHttp()

    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=http,
        now=lambda: 1234567890,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_release_watch()

    assert exc.value.code == "not_authenticated"
    assert http.calls == []


def test_q6g2a_existing_signed_request_default_still_emits_signature():
    secret = "0123456789abcdef0123456789abcdef"

    http = FakeHttp(
        [
            FakeResponse(status_code=200),
            FakeResponse(
                payload={
                    "albums": {
                        "items": [],
                        "total": 0,
                    }
                }
            ),
        ]
    )

    client = make_client(
        http,
        secrets=[secret],
    )

    client.request_json(
        "/favorite/getUserFavorites",
        method_name="favoritegetUserFavorites",
        params={
            "type": "albums",
            "limit": "50",
            "offset": "0",
        },
        signature_params={},
        require_auth=True,
    )

    assert len(http.calls) == 2

    request = http.calls[1]

    assert request["params"]["request_ts"] == "1234567890"
    assert request["params"]["request_sig"] == expected_signature(
        "favoritegetUserFavorites",
        {},
        secret,
    )


# ============================================================
# Q6G2A_RELEASE_WATCH_TESTS_END
# ============================================================


# ============================================================
# Q6G2B_SUGGEST_SIMILAR_TESTS_BEGIN
# ============================================================

def test_q6g2b_similar_artists_exact_signed_wire_contract_and_order(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "artists": {
            "items": [
                {
                    "id": 701,
                    "name": "First Similar",
                    "image": {
                        "large": "https://img/701.jpg",
                    },
                    "albums_count": 12,
                    "unknown_artist_field": "must-not-escape",
                },
                {
                    "id": 702,
                    "name": "Second Similar",
                    "image": {
                        "mega": "https://img/702.jpg",
                    },
                    "albums_count": 8,
                },
            ],
            "total": 91,
            "offset": 25,
            "limit": 2,
            "unknown_page_field": "must-not-escape",
        },
        "unknown_root_field": "must-not-escape",
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    page = backend.get_similar_artists(
        123,
        limit=2,
        offset=25,
    )

    params = {
        "artist_id": "123",
        "limit": "2",
        "offset": "25",
    }

    assert calls == [
        (
            "/artist/getSimilarArtists",
            {
                "method_name": "artistgetSimilarArtists",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert page["ok"] is True
    assert page["artist_id"] == "123"
    assert page["offset"] == 25
    assert page["limit"] == 2
    assert page["total"] == 91

    assert [
        item["artist_id"]
        for item in page["items"]
    ] == [
        "701",
        "702",
    ]

    assert page["items"][0]["name"] == "First Similar"
    assert page["items"][0]["artwork_url"] == "https://img/701.jpg"
    assert page["items"][1]["artwork_url"] == "https://img/702.jpg"

    rendered = repr(page)

    assert "must-not-escape" not in rendered
    assert "unknown_artist_field" not in rendered
    assert "unknown_page_field" not in rendered
    assert "unknown_root_field" not in rendered


@pytest.mark.parametrize(
    "artist_id",
    [
        None,
        "",
        " ",
        "abc",
        "0",
        0,
        -1,
        "1.5",
    ],
)
def test_q6g2b_invalid_similar_artist_id_fails_before_request(
    tmp_path,
    artist_id,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError(
            "similar-artists provider request must not occur"
        )

    backend._catalog_request = unexpected

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_similar_artists(
            artist_id
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "limit,offset",
    [
        (0, 0),
        (101, 0),
        ("bad", 0),
        (1, -1),
        (1, 1_000_001),
    ],
)
def test_q6g2b_invalid_similar_pagination_fails_before_request(
    tmp_path,
    limit,
    offset,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError(
            "similar-artists provider request must not occur"
        )

    backend._catalog_request = unexpected

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_similar_artists(
            77,
            limit=limit,
            offset=offset,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {
            "artists": None,
        },
        {
            "artists": [],
        },
        {
            "artists": {
                "items": "bad",
                "total": 1,
            },
        },
        {
            "artists": {
                "items": [],
                "total": -1,
            },
        },
        {
            "artists": {
                "items": [],
                "total": True,
            },
        },
    ],
)
def test_q6g2b_similar_artists_requires_valid_artists_page(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_similar_artists(
            77,
            limit=5,
            offset=0,
        )

    assert exc.value.code == "malformed_response"


def test_q6g2b_similar_artists_rejects_page_larger_than_requested_limit(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "artists": {
                "items": [
                    {
                        "id": 1,
                        "name": "One",
                    },
                    {
                        "id": 2,
                        "name": "Two",
                    },
                ],
                "total": 2,
            }
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_similar_artists(
            77,
            limit=1,
            offset=0,
        )

    assert exc.value.code == "malformed_response"


def test_q6g2b_similar_artists_is_one_bounded_request_without_auto_paging(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "similar-artists must not auto-fetch another page"
            )

        return {
            "artists": {
                "items": [
                    {
                        "id": 901,
                        "name": "Only Page",
                    }
                ],
                "total": 9999,
            }
        }

    backend._catalog_request = request

    page = backend.get_similar_artists(
        88,
        limit=1,
        offset=500,
    )

    assert len(calls) == 1
    assert page["artist_id"] == "88"
    assert page["offset"] == 500
    assert page["limit"] == 1
    assert page["total"] == 9999
    assert page["items"][0]["artist_id"] == "901"


def test_q6g2b_album_suggest_exact_unsigned_wire_contract(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "algorithm": "  provider-similarity-v1  ",
        "albums": {
            "limit": 12,
            "items": [
                {
                    "id": "suggest-a",
                    "title": "Suggested A",
                    "artist": {
                        "id": 101,
                        "name": "Artist A",
                    },
                    "image": {
                        "large": "https://img/a.jpg",
                    },
                    "unknown_album_field": "must-not-escape",
                },
                {
                    "id": "suggest-b",
                    "title": "Suggested B",
                    "artist": {
                        "id": 202,
                        "name": "Artist B",
                    },
                    "image": {
                        "mega": "https://img/b.jpg",
                    },
                },
            ],
            # These may exist on some provider responses. Q6G2B deliberately
            # does not expose them because they are not a stable contract.
            "total": 500,
            "offset": 75,
            "unknown_page_field": "must-not-escape",
        },
        "unknown_root_field": "must-not-escape",
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    result = backend.get_album_suggest(
        "0060254735180"
    )

    assert calls == [
        (
            "/album/suggest",
            {
                "method_name": "albumsuggest",
                "params": {
                    "album_id": "0060254735180",
                },
                "require_auth": False,
                "signed": False,
            },
        )
    ]

    assert result["ok"] is True
    assert result["album_id"] == "0060254735180"
    assert result["algorithm"] == "provider-similarity-v1"
    assert result["limit"] == 12

    assert "total" not in result
    assert "offset" not in result

    assert [
        item["album_id"]
        for item in result["items"]
    ] == [
        "suggest-a",
        "suggest-b",
    ]

    assert result["items"][0]["artist"] == "Artist A"
    assert result["items"][0]["artist_id"] == "101"
    assert result["items"][1]["artist"] == "Artist B"
    assert result["items"][1]["artist_id"] == "202"

    rendered = repr(result)

    assert "must-not-escape" not in rendered
    assert "unknown_album_field" not in rendered
    assert "unknown_page_field" not in rendered
    assert "unknown_root_field" not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "algorithm": "algo",
        },
        {
            "algorithm": "algo",
            "albums": None,
        },
        {
            "albums": {
                "items": [],
            },
        },
    ],
)
def test_q6g2b_album_suggest_optional_album_branch_normalizes_empty(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    result = backend.get_album_suggest(
        "album-seed"
    )

    assert result["ok"] is True
    assert result["album_id"] == "album-seed"
    assert result["items"] == []
    assert "total" not in result
    assert "offset" not in result


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {
            "albums": [],
        },
        {
            "albums": {
                "items": "bad",
            },
        },
        {
            "albums": {
                "items": [],
                "limit": -1,
            },
        },
        {
            "albums": {
                "items": [],
                "limit": True,
            },
        },
        {
            "albums": {
                "items": [],
                "limit": "12",
            },
        },
    ],
)
def test_q6g2b_album_suggest_rejects_malformed_envelope(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_album_suggest(
            "album-seed"
        )

    assert exc.value.code == "malformed_response"


def test_q6g2b_album_suggest_malformed_album_row_fails_whole_read(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "albums": {
                "items": [
                    {
                        "id": "valid",
                        "title": "Valid",
                    },
                    {
                        "id": "",
                        "title": "Invalid ID",
                    },
                ]
            }
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_album_suggest(
            "album-seed"
        )

    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    "album_id",
    [
        None,
        "",
        " ",
        "bad id",
        "bad\tid",
        "bad\nid",
    ],
)
def test_q6g2b_invalid_album_suggest_id_fails_before_request(
    tmp_path,
    album_id,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError(
            "album-suggest provider request must not occur"
        )

    backend._catalog_request = unexpected

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_album_suggest(
            album_id
        )

    assert exc.value.code == "invalid_request"


def test_q6g2b_album_suggest_is_exactly_one_provider_request(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "album-suggest must make exactly one provider request"
            )

        return {
            "algorithm": None,
            "albums": {
                "items": [],
            },
        }

    backend._catalog_request = request

    result = backend.get_album_suggest(
        "one-request-seed"
    )

    assert len(calls) == 1
    assert result["items"] == []
    assert "limit" not in result
    assert "total" not in result
    assert "offset" not in result


def test_q6g2b_unsigned_optional_auth_request_needs_no_token_secret_or_clock():
    http = FakeHttp(
        [
            FakeResponse(
                payload={
                    "algorithm": None,
                    "albums": {
                        "items": [],
                    },
                }
            )
        ]
    )

    client = QobuzCatalogClient(
        http_session=http,
        api_base_url="https://www.qobuz.com/api.json/0.2",
        metadata_loader=lambda: {
            "app_id": "123456789",
        },
        token_loader=lambda: None,
        now=lambda: (_ for _ in ()).throw(
            AssertionError(
                "unsigned optional-auth request must not use request clock"
            )
        ),
        sleep=lambda _seconds: None,
    )

    payload = client.request_json(
        "/album/suggest",
        method_name="albumsuggest",
        params={
            "album_id": "album-seed",
        },
        require_auth=False,
        signed=False,
    )

    assert payload == {
        "algorithm": None,
        "albums": {
            "items": [],
        },
    }

    assert len(http.calls) == 1

    request = http.calls[0]

    assert request["url"].endswith(
        "/album/suggest"
    )

    assert request["params"] == {
        "album_id": "album-seed",
    }

    assert request["headers"] == {
        "X-App-Id": "123456789",
    }

    assert "request_ts" not in request["params"]
    assert "request_sig" not in request["params"]


# ============================================================
# Q6G2B_SUGGEST_SIMILAR_TESTS_END
# ============================================================


# ============================================================
# Q6G2C_FEATURED_PLAYLIST_TAG_TESTS_BEGIN
# ============================================================

@pytest.mark.parametrize(
    "value,expected",
    [
        ("new-releases", "new-releases"),
        (" NEW-RELEASES ", "new-releases"),
        ("press-awards", "press-awards"),
        ("PRESS-AWARDS", "press-awards"),
        ("most-streamed", "most-streamed"),
        (" MOST-STREAMED ", "most-streamed"),
    ],
)
def test_q6g2c_featured_type_allowlist_normalizes_valid_values(
    value,
    expected,
):
    assert QobuzBackend._catalog_featured_type(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "featured",
        "newReleases",
        "new_releases",
        "pressAward",
        "mostStreamed",
        "albums",
        1,
        [],
    ],
)
def test_q6g2c_invalid_featured_type_fails_before_request(
    tmp_path,
    value,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("featured provider request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_featured_albums(value)

    assert exc.value.code == "invalid_request"


def test_q6g2c_featured_exact_wire_contract_and_strict_album_model(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "albums": {
            "items": [
                {
                    "id": "featured-a",
                    "title": "First Featured",
                    "artist": {
                        "id": 101,
                        "name": "Artist One",
                    },
                    "image": {
                        "large": "https://img/a.jpg",
                    },
                    "tracks_count": 8,
                    "maximum_sampling_rate": 96.0,
                    "maximum_bit_depth": 24,
                    "unknown_provider_field": "must-not-escape",
                },
                {
                    "id": "featured-b",
                    "title": "Second Featured",
                    "artist": {
                        "id": 202,
                        "name": "Artist Two",
                    },
                    "image": {
                        "mega": "https://img/b.jpg",
                    },
                    "tracks_count": 12,
                },
            ],
            "total": 77,
            "offset": 999,
            "limit": 999,
            "unknown_branch_field": "must-not-escape",
        },
        "unknown_root_field": "must-not-escape",
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    page = backend.get_featured_albums(
        " NEW-RELEASES ",
        limit=2,
        offset=20,
        genre_id="112",
    )

    assert calls == [
        (
            "/album/getFeatured",
            {
                "method_name": "albumgetFeatured",
                "params": {
                    "type": "new-releases",
                    "limit": "2",
                    "offset": "20",
                    "genre_id": "112",
                },
                "signature_params": {
                    "type": "new-releases",
                    "limit": "2",
                    "offset": "20",
                    "genre_id": "112",
                },
                "require_auth": False,
            },
        )
    ]

    assert page["ok"] is True
    assert page["featured_type"] == "new-releases"
    assert page["genre_id"] == "112"
    assert page["offset"] == 20
    assert page["limit"] == 2
    assert page["total"] == 77

    assert [
        item["album_id"]
        for item in page["items"]
    ] == [
        "featured-a",
        "featured-b",
    ]

    assert page["items"][0]["artist_id"] == "101"
    assert page["items"][1]["artist_id"] == "202"

    rendered = repr(page)

    assert "must-not-escape" not in rendered
    assert "unknown_provider_field" not in rendered
    assert "unknown_branch_field" not in rendered
    assert "unknown_root_field" not in rendered


def test_q6g2c_featured_without_genre_uses_exact_three_params(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "albums": {
                "items": [],
            }
        }
    )

    page = backend.get_featured_albums(
        "most-streamed",
    )

    assert calls == [
        (
            "/album/getFeatured",
            {
                "method_name": "albumgetFeatured",
                "params": {
                    "type": "most-streamed",
                    "limit": "50",
                    "offset": "0",
                },
                "signature_params": {
                    "type": "most-streamed",
                    "limit": "50",
                    "offset": "0",
                },
                "require_auth": False,
            },
        )
    ]

    assert page == {
        "ok": True,
        "featured_type": "most-streamed",
        "genre_id": None,
        "items": [],
        "offset": 0,
        "limit": 50,
        "total": 0,
    }


@pytest.mark.parametrize(
    "limit,offset,genre_id",
    [
        (0, 0, None),
        (101, 0, None),
        ("bad", 0, None),
        (1, -1, None),
        (1, 1_000_001, None),
        (1, 0, 0),
        (1, 0, -1),
        (1, 0, "x"),
        (1, 0, ""),
    ],
)
def test_q6g2c_invalid_featured_bounds_or_genre_fail_before_request(
    tmp_path,
    limit,
    offset,
    genre_id,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("featured provider request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_featured_albums(
            "press-awards",
            limit=limit,
            offset=offset,
            genre_id=genre_id,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"albums": None},
        {"albums": []},
        {"albums": {"items": "bad"}},
        {"albums": {"items": [], "total": -1}},
        {"albums": {"items": [], "total": True}},
        {"albums": {"items": [], "total": "1"}},
    ],
)
def test_q6g2c_featured_page_envelope_is_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_featured_albums(
            "new-releases",
            limit=5,
        )

    assert exc.value.code == "malformed_response"


def test_q6g2c_featured_missing_items_and_total_follow_typed_defaults(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "albums": {},
        }
    )

    result = backend.get_featured_albums(
        "press-awards",
        limit=7,
        offset=11,
    )

    assert result["items"] == []
    assert result["total"] == 0
    assert result["offset"] == 11
    assert result["limit"] == 7


def test_q6g2c_featured_rejects_provider_page_larger_than_requested_limit(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "albums": {
                "items": [
                    {
                        "id": "one",
                        "title": "One",
                    },
                    {
                        "id": "two",
                        "title": "Two",
                    },
                ],
            },
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_featured_albums(
            "most-streamed",
            limit=1,
        )

    assert exc.value.code == "malformed_response"


def test_q6g2c_featured_malformed_album_row_fails_whole_read(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "albums": {
                "items": [
                    {
                        "id": "good",
                        "title": "Good",
                    },
                    {
                        "id": None,
                        "title": "Malformed",
                    },
                ],
            },
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_featured_albums(
            "new-releases",
            limit=2,
        )

    assert exc.value.code == "malformed_response"


def test_q6g2c_featured_is_one_bounded_request_without_auto_paging(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "featured albums must not auto-fetch another page"
            )

        return {
            "albums": {
                "items": [
                    {
                        "id": "one-page",
                        "title": "One Page",
                    }
                ],
                "total": 1000,
            }
        }

    backend._catalog_request = request

    result = backend.get_featured_albums(
        "new-releases",
        limit=1,
        offset=500,
    )

    assert len(calls) == 1
    assert result["offset"] == 500
    assert result["limit"] == 1
    assert result["total"] == 1000
    assert result["items"][0]["album_id"] == "one-page"


def test_q6g2c_playlist_tags_exact_wire_filter_localization_and_order(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    with backend._auth_lock:
        backend._session = {
            "language_code": "fr-FR",
        }

    calls = []

    payload = {
        "tags": [
            {
                "slug": "editorial",
                "name_json": (
                    '{"en":"Editorial","fr":"Éditorial"}'
                ),
                "position": "1",
                "is_discover": "true",
                "featured_tag_id": "7",
                "unknown": "must-not-escape",
            },
            {
                "slug": "not-discover",
                "name_json": '{"en":"Hidden"}',
                "is_discover": "True",
                "featured_tag_id": "8",
            },
            {
                "slug": "bad-json",
                "name_json": "{not-json",
                "is_discover": "true",
                "featured_tag_id": "9",
            },
            {
                "slug": "fallback",
                "name_json": '{"en":"English Fallback"}',
                "is_discover": "true",
                "featured_tag_id": "10",
            },
            {
                "slug": "bad-id",
                "name_json": '{"fr":"Identifiant"}',
                "is_discover": "true",
                "featured_tag_id": "not-a-number",
            },
            {
                "slug": "missing-id",
                "name_json": '{"fr":"Sans ID"}',
                "is_discover": "true",
                "featured_tag_id": None,
            },
        ],
        "unknown_root": "must-not-escape",
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return payload

    backend._catalog_request = request

    result = backend.get_playlist_tags()

    assert calls == [
        (
            "/playlist/getTags",
            {
                "method_name": "playlistgetTags",
                "params": {},
                "signature_params": {},
                "require_auth": True,
            },
        )
    ]

    assert result == {
        "ok": True,
        "items": [
            {
                "id": "7",
                "slug": "editorial",
                "name": "Éditorial",
            },
            {
                "id": "10",
                "slug": "fallback",
                "name": "English Fallback",
            },
            {
                "id": "0",
                "slug": "bad-id",
                "name": "Identifiant",
            },
            {
                "id": "0",
                "slug": "missing-id",
                "name": "Sans ID",
            },
        ],
    }

    rendered = repr(result)

    assert "must-not-escape" not in rendered
    assert "name_json" not in rendered
    assert "is_discover" not in rendered
    assert "featured_tag_id" not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"tags": None},
        {"tags": {}},
        {"tags": "bad"},
    ],
)
def test_q6g2c_playlist_tag_root_envelope_is_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_playlist_tags()

    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    "row",
    [
        None,
        {},
        {
            "slug": 123,
            "name_json": '{"en":"Name"}',
            "is_discover": "false",
        },
        {
            "slug": "tag",
            "name_json": 123,
            "is_discover": "false",
        },
        {
            "slug": "tag",
            "name_json": '{"en":"Name"}',
            "position": 1,
            "is_discover": "false",
        },
        {
            "slug": "tag",
            "name_json": '{"en":"Name"}',
            "is_discover": True,
        },
        {
            "slug": "tag",
            "name_json": '{"en":"Name"}',
            "is_discover": "false",
            "featured_tag_id": 7,
        },
    ],
)
def test_q6g2c_playlist_tag_raw_typed_shape_is_strict(
    tmp_path,
    row,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "tags": [row],
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_playlist_tags()

    assert exc.value.code == "malformed_response"


def test_q6g2c_playlist_tag_invalid_session_language_falls_back_to_en(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    with backend._auth_lock:
        backend._session = {
            "language_code": "english",
        }

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "tags": [
                {
                    "slug": "fallback",
                    "name_json": (
                        '{"en":"English","fr":"Français"}'
                    ),
                    "is_discover": "true",
                    "featured_tag_id": "1",
                }
            ]
        }
    )

    result = backend.get_playlist_tags()

    assert result["items"] == [
        {
            "id": "1",
            "slug": "fallback",
            "name": "English",
        }
    ]


def test_q6g2c_playlist_tag_missing_localized_name_is_dropped(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    with backend._auth_lock:
        backend._session = {
            "language_code": "fr",
        }

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "tags": [
                {
                    "slug": "missing-name",
                    "name_json": '{"de":"Deutsch"}',
                    "is_discover": "true",
                    "featured_tag_id": "2",
                },
                {
                    "slug": "kept",
                    "name_json": '{"en":"Kept"}',
                    "is_discover": "true",
                    "featured_tag_id": "3",
                },
            ]
        }
    )

    result = backend.get_playlist_tags()

    assert result["items"] == [
        {
            "id": "3",
            "slug": "kept",
            "name": "Kept",
        }
    ]


@pytest.mark.parametrize(
    "raw_id,expected",
    [
        ("0", "0"),
        ("7", "7"),
        ("007", "7"),
        ("", "0"),
        (" 7 ", "0"),
        ("-1", "0"),
        ("18446744073709551615", "18446744073709551615"),
        ("18446744073709551616", "0"),
        ("abc", "0"),
        (None, "0"),
    ],
)
def test_q6g2c_playlist_tag_featured_id_matches_qbz_u64_fallback(
    raw_id,
    expected,
):
    item = QobuzBackend._normalize_qobuz_raw_playlist_tag(
        {
            "slug": "tag",
            "name_json": '{"en":"Tag"}',
            "is_discover": "true",
            "featured_tag_id": raw_id,
        },
        language="en",
    )

    assert item["id"] == expected


def test_q6g2c_playlist_tags_requires_auth_before_network(
    tmp_path,
):
    http = FakeHttp()

    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=http,
        now=lambda: 1234567890,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_playlist_tags()

    assert exc.value.code == "not_authenticated"
    assert http.calls == []


def test_q6g2c_playlist_tags_is_one_nonpaged_provider_request(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    with backend._auth_lock:
        backend._session = {
            "language_code": "en",
        }

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "playlist tags must issue exactly one provider request"
            )

        return {
            "tags": [],
        }

    backend._catalog_request = request

    result = backend.get_playlist_tags()

    assert result == {
        "ok": True,
        "items": [],
    }

    assert len(calls) == 1
    assert "limit" not in calls[0][1]["params"]
    assert "offset" not in calls[0][1]["params"]


# ============================================================
# Q6G2C_FEATURED_PLAYLIST_TAG_TESTS_END
# ============================================================


# Q6H1_ARTIST_DETAIL_TESTS


def _q6h1_release_payload(
    release_id="artist-release-1",
):
    return {
        "id": release_id,
        "title": "Artist Release",
        "version": "Deluxe",
        "tracks_count": 9,
        "artist": {
            "id": 101,
            "name": {
                "display": "Primary Artist",
            },
        },
        "image": {
            "large": "https://img/release-large.jpg",
        },
        "label": {
            "id": 77,
            "name": "Reference Label",
        },
        "genre": {
            "id": 112,
            "name": "Jazz",
        },
        "release_type": "album",
        "release_tags": [
            "studio",
        ],
        "duration": 3000,
        "dates": {
            "original": "2026-01-01",
        },
        "parental_warning": False,
        "audio_info": {
            "maximum_sampling_rate": 192.0,
            "maximum_bit_depth": 24,
            "maximum_channel_count": 2,
        },
        "rights": {
            "streamable": True,
            "hires_streamable": True,
            "hires_purchasable": True,
            "purchasable": True,
            "downloadable": False,
            "previewable": True,
            "sampleable": True,
        },
        "awards": [
            {
                "id": 9,
                "name": "Reference Award",
                "awarded_at": "2026-01-02",
            },
        ],
        "unknown_release_field": "must-not-escape",
    }


def _q6h1_track_payload(
    track_id=5001,
):
    return {
        "id": track_id,
        "title": "Artist Page Track",
        "version": "Live",
        "duration": 300,
        "isrc": "XXABC1234567",
        "parental_warning": True,
        "artist": {
            "id": 101,
            "name": {
                "display": "Primary Artist",
            },
        },
        "audio_info": {
            "maximum_sampling_rate": 96.0,
            "maximum_bit_depth": 24,
            "maximum_channel_count": 2,
        },
        "rights": {
            "streamable": True,
            "hires_streamable": True,
        },
        "physical_support": {
            "media_number": 2,
            "track_number": 4,
        },
        "album": {
            "id": "track-album-1",
            "title": "Track Album",
            "version": "Edition",
            "image": {
                "small": "https://img/track-small.jpg",
                "large": "https://img/track-large.jpg",
            },
            "label": {
                "id": 77,
                "name": "Reference Label",
            },
            "genre": {
                "id": 112,
                "name": "Jazz",
            },
        },
        "unknown_track_field": "must-not-escape",
    }


def test_q6h1_artist_page_exact_wire_contract_and_provider_native_adapters(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "id": 123,
        "name": {
            "display": "Reference Artist",
        },
        "artist_category": "Performer",
        "biography": {
            "content": "<p>Provider biography</p>",
            "source": "Qobuz Magazine",
            "language": "en",
            "unknown_bio_field": "must-not-escape",
        },
        "images": {
            "portrait": {
                "hash": "abcdef",
                "format": "jpg",
                "unknown_portrait_field": "must-not-escape",
            },
        },
        "similar_artists": {
            "has_more": True,
            "items": [
                {
                    "id": 202,
                    "name": {
                        "display": "Similar Artist",
                    },
                    "images": {
                        "portrait": {
                            "hash": "similarhash",
                            "format": "webp",
                        },
                    },
                    "unknown_similar_field": "must-not-escape",
                },
            ],
        },
        "top_tracks": [
            _q6h1_track_payload(5001),
        ],
        "last_release": _q6h1_release_payload(
            "last-release"
        ),
        "releases": [
            {
                "type": "epSingle",
                "has_more": True,
                "items": [
                    _q6h1_release_payload(
                        "group-release"
                    ),
                ],
            },
            {
                "type": "futureBucket",
                "has_more": False,
                "items": [],
            },
        ],
        "tracks_appears_on": [
            _q6h1_track_payload(5002),
        ],
        "playlists": {
            "has_more": False,
            "items": [
                {
                    "id": 9001,
                    "title": "Artist Essentials",
                    "description": "Curated playlist",
                    "owner": {
                        "id": 1,
                        "name": "Qobuz",
                    },
                    "tracks_count": 25,
                    "duration": 7500,
                    "images": {
                        "rectangle": [
                            "",
                            "https://img/playlist-one.jpg",
                            "https://img/playlist-two.jpg",
                        ],
                    },
                    "unknown_playlist_field": "must-not-escape",
                },
            ],
        },
        "unknown_root_field": "must-not-escape",
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "artist page must use exactly one provider request"
            )

        return payload

    backend._catalog_request = request

    result = backend.get_artist_page(
        " 123 ",
    )

    params = {
        "artist_id": "123",
    }

    assert calls == [
        (
            "/artist/page",
            {
                "method_name": "artistpage",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert result["ok"] is True
    assert result["artist_id"] == "123"
    assert result["name"] == "Reference Artist"
    assert result["artist_category"] == "Performer"

    assert result["biography"] == {
        "content": "<p>Provider biography</p>",
        "source": "Qobuz Magazine",
        "language": "en",
    }

    assert (
        result["artwork_url"]
        == "https://static.qobuz.com/images/artists/"
        "covers/large/abcdef.jpg"
    )

    assert result["similar_artists"]["has_more"] is True
    assert [
        item["artist_id"]
        for item in result["similar_artists"]["items"]
    ] == [
        "202",
    ]
    assert (
        result["similar_artists"]["items"][0][
            "artwork_url"
        ]
        == "https://static.qobuz.com/images/artists/"
        "covers/large/similarhash.webp"
    )

    track = result["top_tracks"][0]

    assert track["id"] == "qobuz:5001"
    assert track["provider_track_id"] == "5001"
    assert track["artist"] == "Primary Artist"
    assert track["artist_id"] == "101"
    assert track["album_id"] == "track-album-1"
    assert track["album"] == "Track Album"
    assert track["disc_number"] == 2
    assert track["track_number"] == 4
    assert track["streamable"] is True
    assert track["quality"]["hires_streamable"] is True
    assert (
        track["quality"]["maximum_sampling_rate_khz"]
        == 96.0
    )
    assert track["quality"]["maximum_bit_depth"] == 24
    assert (
        track["artwork_url"]
        == "https://img/track-large.jpg"
    )

    last_release = result["last_release"]

    assert last_release["album_id"] == "last-release"
    assert last_release["artist"] == "Primary Artist"
    assert last_release["artist_id"] == "101"
    assert last_release["release_type"] == "album"
    assert last_release["release_tags"] == [
        "studio",
    ]
    assert last_release["streamable"] is True
    assert last_release["hires_streamable"] is True
    assert last_release["rights"] == {
        "streamable": True,
        "hires_streamable": True,
        "hires_purchasable": True,
        "purchasable": True,
        "downloadable": False,
        "previewable": True,
        "sampleable": True,
    }
    assert last_release["awards"][0]["id"] == "9"

    assert [
        group["release_type"]
        for group in result["release_groups"]
    ] == [
        "epSingle",
        "futureBucket",
    ]
    assert (
        result["release_groups"][0]["items"][0][
            "album_id"
        ]
        == "group-release"
    )
    assert result["release_groups"][0]["has_more"] is True

    appears = result["tracks_appears_on"][0]
    assert appears["id"] == "qobuz:5002"
    assert appears["artist"] == "Primary Artist"

    playlist = result["playlists"]["items"][0]

    assert playlist["playlist_id"] == "9001"
    assert playlist["title"] == "Artist Essentials"
    assert playlist["owner_id"] == "1"
    assert playlist["owner_name"] == "Qobuz"
    assert playlist["track_count"] == 25
    assert (
        playlist["artwork_url"]
        == "https://img/playlist-one.jpg"
    )
    assert playlist["rectangle_artwork_urls"] == [
        "https://img/playlist-one.jpg",
        "https://img/playlist-two.jpg",
    ]

    rendered = repr(result)

    assert "must-not-escape" not in rendered
    assert "unknown_root_field" not in rendered
    assert "unknown_release_field" not in rendered
    assert "unknown_track_field" not in rendered
    assert "unknown_playlist_field" not in rendered


def test_q6h1_artist_page_missing_optional_sections_use_stable_empty_forms(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "id": 44,
            "name": {
                "display": "Minimal Artist",
            },
        }
    )

    result = backend.get_artist_page(
        44
    )

    assert result == {
        "ok": True,
        "artist_id": "44",
        "name": "Minimal Artist",
        "artist_category": None,
        "biography": None,
        "artwork": None,
        "artwork_url": None,
        "similar_artists": {
            "has_more": False,
            "items": [],
        },
        "top_tracks": [],
        "last_release": None,
        "release_groups": [],
        "tracks_appears_on": [],
        "playlists": {
            "has_more": False,
            "items": [],
        },
    }


def test_q6h1_artist_page_nonstring_biography_source_is_not_exposed(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "id": 45,
            "name": {
                "display": "Artist",
            },
            "biography": {
                "content": "Biography",
                "source": {
                    "name": "must-not-escape",
                },
            },
        }
    )

    result = backend.get_artist_page(
        45
    )

    assert result["biography"] == {
        "content": "Biography",
        "source": None,
        "language": None,
    }
    assert "must-not-escape" not in repr(result)


@pytest.mark.parametrize(
    "artist_id",
    [
        None,
        "",
        0,
        -1,
        "abc",
    ],
)
def test_q6h1_invalid_artist_page_id_fails_before_request(
    tmp_path,
    artist_id,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("artist-page provider request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_page(
            artist_id
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {
            "id": 1,
            "name": "not-an-object",
        },
        {
            "id": 1,
            "name": {
                "display": "",
            },
        },
        {
            "id": 1,
            "name": {
                "display": "Artist",
            },
            "similar_artists": {
                "has_more": "yes",
                "items": [],
            },
        },
        {
            "id": 1,
            "name": {
                "display": "Artist",
            },
            "top_tracks": {},
        },
        {
            "id": 1,
            "name": {
                "display": "Artist",
            },
            "releases": {},
        },
        {
            "id": 1,
            "name": {
                "display": "Artist",
            },
            "playlists": [],
        },
    ],
)
def test_q6h1_artist_page_typed_envelope_is_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_page(
            1
        )

    assert exc.value.code == "malformed_response"


def test_q6h1_artist_page_track_adapter_rejects_typed_field_corruption():
    payload = _q6h1_track_payload()
    payload["rights"]["streamable"] = "true"

    with pytest.raises(QobuzCatalogError) as exc:
        QobuzBackend._normalize_qobuz_artist_page_track(
            payload
        )

    assert exc.value.code == "malformed_response"


def test_q6h1_artist_page_release_contributor_order_and_fallback():
    release = _q6h1_release_payload()
    release["artists"] = [
        {
            "id": 301,
            "name": "First Contributor",
            "roles": [
                "main-artist",
            ],
        },
        {
            "id": 302,
            "name": "Second Contributor",
            "roles": [],
        },
    ]

    item = QobuzBackend._normalize_qobuz_artist_page_release(
        release
    )

    assert item["artist"] == "First Contributor"
    assert item["artist_id"] == "301"
    assert [
        artist["id"]
        for artist in item["artists"]
    ] == [
        "301",
        "302",
    ]

    fallback = _q6h1_release_payload()
    fallback.pop("artists", None)

    fallback_item = (
        QobuzBackend._normalize_qobuz_artist_page_release(
            fallback
        )
    )

    assert fallback_item["artist"] == "Primary Artist"
    assert fallback_item["artist_id"] == "101"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("album", "album"),
        (" epSingle ", "epSingle"),
        ("awardedRelease", "awardedRelease"),
        ("futureBucket", "futureBucket"),
    ],
)
def test_q6h1_release_type_is_open_provider_token(
    value,
    expected,
):
    assert (
        QobuzBackend._catalog_artist_release_type(
            value
        )
        == expected
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        "",
        "   ",
        "bad type",
        "bad\ttype",
        "bad\ntype",
        "x" * 129,
        "café",
    ],
)
def test_q6h1_unsafe_release_type_fails_before_network_policy(
    value,
):
    with pytest.raises(QobuzCatalogError) as exc:
        QobuzBackend._catalog_artist_release_type(
            value
        )

    assert exc.value.code == "invalid_request"


def test_q6h1_artist_releases_grid_exact_wire_contract_without_sort(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return {
            "has_more": True,
            "items": [
                _q6h1_release_payload(
                    "grid-one"
                ),
                _q6h1_release_payload(
                    "grid-two"
                ),
            ],
            "total": 999,
            "unknown_page_field": "must-not-escape",
        }

    backend._catalog_request = request

    result = backend.get_artist_releases_grid(
        123,
        " epSingle ",
        limit=2,
        offset=50,
    )

    params = {
        "artist_id": "123",
        "release_type": "epSingle",
        "limit": "2",
        "offset": "50",
    }

    assert calls == [
        (
            "/artist/getReleasesGrid",
            {
                "method_name": "artistgetReleasesGrid",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert result["ok"] is True
    assert result["artist_id"] == "123"
    assert result["release_type"] == "epSingle"
    assert result["sort"] is None
    assert result["offset"] == 50
    assert result["limit"] == 2
    assert result["has_more"] is True
    assert "total" not in result
    assert [
        item["album_id"]
        for item in result["items"]
    ] == [
        "grid-one",
        "grid-two",
    ]
    assert "must-not-escape" not in repr(result)


def test_q6h1_artist_releases_grid_exact_release_date_sort_contract(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "has_more": False,
            "items": [],
        }
    )

    result = backend.get_artist_releases_grid(
        77,
        "futureBucket",
        limit=5,
        offset=0,
        sort=" release_date ",
    )

    params = {
        "artist_id": "77",
        "release_type": "futureBucket",
        "limit": "5",
        "offset": "0",
        "sort": "release_date",
    }

    assert calls == [
        (
            "/artist/getReleasesGrid",
            {
                "method_name": "artistgetReleasesGrid",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]
    assert result["sort"] == "release_date"


@pytest.mark.parametrize(
    "sort",
    [
        "",
        "newest",
        "oldest",
        "title-asc",
        1,
    ],
)
def test_q6h1_unsupported_artist_release_sort_fails_before_request(
    tmp_path,
    sort,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("release-grid provider request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_releases_grid(
            77,
            "album",
            sort=sort,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    ("limit", "offset"),
    [
        (0, 0),
        (101, 0),
        (1, -1),
        (1, 1000001),
    ],
)
def test_q6h1_artist_release_grid_invalid_bounds_fail_before_request(
    tmp_path,
    limit,
    offset,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("release-grid provider request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_releases_grid(
            77,
            "album",
            limit=limit,
            offset=offset,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {
            "has_more": "yes",
            "items": [],
        },
        {
            "has_more": False,
            "items": {},
        },
    ],
)
def test_q6h1_artist_release_grid_envelope_is_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_releases_grid(
            77,
            "album",
            limit=5,
        )

    assert exc.value.code == "malformed_response"


def test_q6h1_artist_release_grid_rejects_page_larger_than_requested_limit(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "has_more": True,
            "items": [
                _q6h1_release_payload("one"),
                _q6h1_release_payload("two"),
            ],
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_releases_grid(
            77,
            "album",
            limit=1,
        )

    assert exc.value.code == "malformed_response"


def test_q6h1_artist_release_grid_is_one_bounded_request_without_auto_paging(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "release grid must not auto-fetch another page"
            )

        return {
            "has_more": True,
            "items": [
                _q6h1_release_payload(
                    "single-page"
                ),
            ],
        }

    backend._catalog_request = request

    result = backend.get_artist_releases_grid(
        88,
        "album",
        limit=1,
        offset=500,
    )

    assert len(calls) == 1
    assert result["offset"] == 500
    assert result["limit"] == 1
    assert result["has_more"] is True
    assert result["items"][0]["album_id"] == "single-page"


def test_q6h1_artist_story_exact_signed_contract_and_typed_normalization(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "has_more": True,
        "items": [
            {
                "id": "story-1",
                "title": "Reference Story",
                "display_date": 1770000000,
                "image": "https://cdn/top.jpg",
                "images": [
                    {
                        "format": "landscape",
                        "url": "https://cdn/list.jpg",
                        "unknown_image_field": "must-not-escape",
                    },
                ],
                "description_short": "<p>Story excerpt</p>",
                "authors": [
                    {
                        "name": "Writer",
                        "id": "writer-1",
                        "slug": "writer",
                        "unknown_author_field": "must-not-escape",
                    },
                ],
                "section_slugs": [
                    "interviews",
                    "jazz",
                ],
                "unknown_story_field": "must-not-escape",
            },
            {
                "id": "story-2",
                "title": "Fallback Image Story",
                "images": [
                    {
                        "url": "https://cdn/fallback.jpg",
                    },
                ],
            },
        ],
        "unknown_root_field": "must-not-escape",
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "artist story must not auto-fetch another page"
            )

        return payload

    backend._catalog_request = request

    result = backend.get_artist_story(
        123,
        limit=2,
        offset=40,
    )

    params = {
        "artist_id": "123",
        "offset": "40",
        "limit": "2",
    }

    assert calls == [
        (
            "/artist/story",
            {
                "method_name": "artiststory",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert result["ok"] is True
    assert result["artist_id"] == "123"
    assert result["offset"] == 40
    assert result["limit"] == 2
    assert result["has_more"] is True
    assert "total" not in result

    first = result["items"][0]
    second = result["items"][1]

    assert first == {
        "id": "story-1",
        "title": "Reference Story",
        "display_date": 1770000000,
        "image": "https://cdn/top.jpg",
        "images": [
            {
                "format": "landscape",
                "url": "https://cdn/list.jpg",
            },
        ],
        "image_url": "https://cdn/top.jpg",
        "description_short": "<p>Story excerpt</p>",
        "authors": [
            {
                "name": "Writer",
                "id": "writer-1",
                "slug": "writer",
            },
        ],
        "section_slugs": [
            "interviews",
            "jazz",
        ],
    }

    assert second["image"] is None
    assert second["image_url"] == "https://cdn/fallback.jpg"

    rendered = repr(result)

    assert "must-not-escape" not in rendered
    assert "unknown_story_field" not in rendered
    assert "unknown_author_field" not in rendered
    assert "unknown_image_field" not in rendered
    assert "unknown_root_field" not in rendered


@pytest.mark.parametrize(
    "artist_id",
    [
        None,
        "",
        0,
        -1,
        "abc",
    ],
)
def test_q6h1_invalid_artist_story_id_fails_before_request(
    tmp_path,
    artist_id,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("artist-story provider request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_story(
            artist_id
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    ("limit", "offset"),
    [
        (0, 0),
        (101, 0),
        (1, -1),
        (1, 1000001),
    ],
)
def test_q6h1_artist_story_invalid_bounds_fail_before_request(
    tmp_path,
    limit,
    offset,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("artist-story provider request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_story(
            77,
            limit=limit,
            offset=offset,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {
            "has_more": "yes",
            "items": [],
        },
        {
            "has_more": False,
            "items": {},
        },
    ],
)
def test_q6h1_artist_story_envelope_is_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_story(
            77,
            limit=5,
        )

    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    "story",
    [
        {
            "id": 1,
            "title": "Numeric ID is not typed String",
        },
        {
            "id": "story",
            "title": 1,
        },
        {
            "id": "story",
            "title": "Title",
            "display_date": "yesterday",
        },
        {
            "id": "story",
            "title": "Title",
            "images": [
                {
                    "url": 1,
                },
            ],
        },
        {
            "id": "story",
            "title": "Title",
            "authors": [
                {
                    "name": 1,
                },
            ],
        },
        {
            "id": "story",
            "title": "Title",
            "section_slugs": [
                1,
            ],
        },
    ],
)
def test_q6h1_artist_story_rows_are_strict(
    tmp_path,
    story,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "has_more": False,
            "items": [
                story,
            ],
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_story(
            77,
            limit=1,
        )

    assert exc.value.code == "malformed_response"


def test_q6h1_artist_story_rejects_page_larger_than_requested_limit(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "has_more": True,
            "items": [
                {
                    "id": "one",
                    "title": "One",
                },
                {
                    "id": "two",
                    "title": "Two",
                },
            ],
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_artist_story(
            77,
            limit=1,
        )

    assert exc.value.code == "malformed_response"

# Q6H2A_LABEL_CORE_CANDIDATE_TESTS


def _q6h2a_album_payload(album_id="label-album-1"):
    return {
        "id": album_id,
        "title": "Label Album",
        "artist": None,
        "artists": [
            {
                "id": 202,
                "name": "Featured Artist",
                "roles": [
                    "featured-artist",
                ],
            },
            {
                "id": 101,
                "name": "Primary Artist",
                "roles": [
                    "main-artist",
                ],
            },
        ],
        "image": {
            "large": "https://img/label-album.jpg",
        },
        "tracks_count": 11,
        "audio_info": {
            "maximum_sampling_rate": 96.0,
            "maximum_bit_depth": 24,
        },
        "unknown_album_field": "must-not-escape",
    }


def _q6h2a_track_payload(track_id=7001):
    return {
        "id": track_id,
        "title": "Label Track",
        "duration": 240,
        "artists": [
            {
                "id": 302,
                "name": "Guest Artist",
                "roles": [
                    "featured-artist",
                ],
            },
            {
                "id": 301,
                "name": "Main Track Artist",
                "roles": [
                    "main-artist",
                ],
            },
        ],
        "performer": None,
        "artist": None,
        "audio_info": {
            "maximum_sampling_rate": 192.0,
            "maximum_bit_depth": 24,
        },
        "streamable": True,
        "hires_streamable": True,
        "album": {
            "id": "track-album",
            "title": "Track Album",
            "image": {
                "large": "https://img/track-album.jpg",
            },
        },
        "unknown_track_field": "must-not-escape",
    }


def test_q6h2a_label_page_exact_wire_and_flexible_adapters(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    payload = {
        "id": 77,
        "name": "Reference Label",
        "description": "<p>Provider description</p>",
        "image": {
            "thumbnail": "https://img/thumb.jpg",
            "large": "https://img/label-large.jpg",
            "mega": "https://img/label-mega.jpg",
        },
        "releases": [
            {
                "id": "critics",
                "data": {
                    "has_more": True,
                    "items": [
                        _q6h2a_album_payload(
                            "release-a"
                        ),
                    ],
                },
            },
        ],
        "top_tracks": [
            _q6h2a_track_payload(7001),
        ],
        "playlists": {
            "has_more": False,
            "items": [
                {
                    "id": 9001,
                    "name": "Label Selection",
                    "description": "Curated",
                    "owner": {
                        "id": 1,
                        "name": "Qobuz",
                    },
                    "tracks_count": 30,
                    "duration": 9000,
                    "image": {
                        "rectangle": "https://img/playlist.jpg",
                    },
                    "unknown_playlist_field": "must-not-escape",
                },
            ],
        },
        "top_artists": {
            "has_more": False,
            "items": [
                {
                    "id": 501,
                    "name": {
                        "display": "Top Artist",
                    },
                    "images": {
                        "portrait": {
                            "hash": "portrait-hash",
                            "format": "jpg",
                        },
                    },
                    "unknown_artist_field": "must-not-escape",
                },
            ],
        },
        "unknown_root_field": "must-not-escape",
    }

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "label page must use exactly one provider request"
            )

        return payload

    backend._catalog_request = request

    result = backend.get_label_page(
        " 77 "
    )

    params = {
        "label_id": "77",
    }

    assert calls == [
        (
            "/label/page",
            {
                "method_name": "labelpage",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert result["ok"] is True
    assert result["label_id"] == "77"
    assert result["name"] == "Reference Label"
    assert result["description"] == "<p>Provider description</p>"
    assert result["artwork_url"] == "https://img/label-mega.jpg"

    assert len(result["release_groups"]) == 1
    group = result["release_groups"][0]
    assert group["id"] == "critics"
    assert group["has_more"] is True
    assert group["items"][0]["album_id"] == "release-a"
    assert group["items"][0]["artist"] == "Primary Artist"
    assert group["items"][0]["artist_id"] == "101"
    assert [
        artist["id"]
        for artist in group["items"][0]["artists"]
    ] == [
        "202",
        "101",
    ]

    track = result["top_tracks"][0]
    assert track["id"] == "qobuz:7001"
    assert track["provider_track_id"] == "7001"
    assert track["artist"] == "Main Track Artist"
    assert track["artist_id"] == "301"
    assert track["album_id"] == "track-album"
    assert track["artwork_url"] == "https://img/track-album.jpg"
    assert track["quality"]["maximum_sampling_rate_khz"] == 192.0
    assert track["quality"]["maximum_bit_depth"] == 24

    playlist = result["playlists"]["items"][0]
    assert playlist == {
        "playlist_id": "9001",
        "title": "Label Selection",
        "description": "Curated",
        "owner_id": "1",
        "owner_name": "Qobuz",
        "track_count": 30,
        "duration": 9000,
        "artwork_url": "https://img/playlist.jpg",
    }

    artist = result["top_artists"]["items"][0]
    assert artist["artist_id"] == "501"
    assert artist["name"] == "Top Artist"
    assert (
        artist["artwork_url"]
        == "https://static.qobuz.com/images/artists/"
        "covers/medium/portrait-hash.jpg"
    )

    rendered = repr(result)

    assert "must-not-escape" not in rendered
    assert "unknown_root_field" not in rendered
    assert "unknown_album_field" not in rendered
    assert "unknown_track_field" not in rendered
    assert "unknown_playlist_field" not in rendered
    assert "unknown_artist_field" not in rendered


def test_q6h2a_label_page_missing_optional_sections_have_stable_forms(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "id": 88,
            "name": "Minimal Label",
        }
    )

    result = backend.get_label_page(
        88
    )

    assert result == {
        "ok": True,
        "label_id": "88",
        "name": "Minimal Label",
        "description": None,
        "artwork_url": None,
        "release_groups": [],
        "playlists": {
            "has_more": None,
            "items": [],
        },
        "top_tracks": [],
        "top_artists": {
            "has_more": None,
            "items": [],
        },
    }


@pytest.mark.parametrize(
    "label_id",
    [
        None,
        "",
        " ",
        0,
        -1,
        "abc",
    ],
)
def test_q6h2a_invalid_label_page_id_fails_before_request(
    tmp_path,
    label_id,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("label-page provider request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_label_page(
            label_id
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {
            "id": 1,
            "name": "",
        },
        {
            "id": 1,
            "name": "Label",
            "releases": {},
        },
        {
            "id": 1,
            "name": "Label",
            "top_tracks": {},
        },
        {
            "id": 1,
            "name": "Label",
            "playlists": [],
        },
        {
            "id": 1,
            "name": "Label",
            "top_artists": [],
        },
    ],
)
def test_q6h2a_label_page_required_envelope_is_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_label_page(
            1
        )

    assert exc.value.code == "malformed_response"


def test_q6h2a_label_page_drops_unusable_optional_rows_without_reordering(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "id": 9,
            "name": "Label",
            "top_tracks": [
                _q6h2a_track_payload(1),
                {
                    "id": None,
                    "title": "Bad",
                },
                _q6h2a_track_payload(2),
            ],
            "top_artists": {
                "has_more": False,
                "items": [
                    {
                        "id": 10,
                        "name": "First",
                    },
                    {
                        "id": None,
                        "name": "Bad",
                    },
                    {
                        "id": 11,
                        "name": "Second",
                    },
                ],
            },
        }
    )

    result = backend.get_label_page(
        9
    )

    assert [
        item["provider_track_id"]
        for item in result["top_tracks"]
    ] == [
        "1",
        "2",
    ]

    assert [
        item["artist_id"]
        for item in result["top_artists"]["items"]
    ] == [
        "10",
        "11",
    ]


def test_q6h2a_label_explore_exact_signed_contract_and_order(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "label explore must not auto-fetch another page"
            )

        return {
            "has_more": True,
            "items": [
                {
                    "id": 20,
                    "name": "First Label",
                    "image": {
                        "large": "https://img/20.jpg",
                    },
                },
                {
                    "id": None,
                    "name": "Bad Label",
                },
                {
                    "id": 21,
                    "name": "Second Label",
                    "image": "https://img/21.jpg",
                },
            ],
            "unknown_root": "must-not-escape",
        }

    backend._catalog_request = request

    result = backend.get_label_explore(
        limit=3,
        offset=40,
    )

    params = {
        "limit": "3",
        "offset": "40",
    }

    assert calls == [
        (
            "/label/explore",
            {
                "method_name": "labelexplore",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert result["offset"] == 40
    assert result["limit"] == 3
    assert result["has_more"] is True

    assert [
        item["label_id"]
        for item in result["items"]
    ] == [
        "20",
        "21",
    ]

    assert result["items"][0]["artwork_url"] == "https://img/20.jpg"
    assert result["items"][1]["artwork_url"] == "https://img/21.jpg"
    assert "must-not-escape" not in repr(result)


@pytest.mark.parametrize(
    ("limit", "offset"),
    [
        (0, 0),
        (101, 0),
        ("bad", 0),
        (1, -1),
        (1, 1000001),
    ],
)
def test_q6h2a_label_explore_invalid_bounds_fail_before_request(
    tmp_path,
    limit,
    offset,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("label-explore request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_label_explore(
            limit=limit,
            offset=offset,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {
            "has_more": "yes",
            "items": [],
        },
        {
            "has_more": False,
            "items": {},
        },
    ],
)
def test_q6h2a_label_explore_envelope_is_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_label_explore(
            limit=5,
        )

    assert exc.value.code == "malformed_response"


def test_q6h2a_label_explore_rejects_page_larger_than_requested_limit(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "has_more": True,
            "items": [
                {
                    "id": 1,
                    "name": "One",
                },
                {
                    "id": 2,
                    "name": "Two",
                },
            ],
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_label_explore(
            limit=1,
        )

    assert exc.value.code == "malformed_response"


def test_q6h2a_label_albums_exact_signed_contract_and_primary_artist(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "label albums must not auto-fetch another page"
            )

        return {
            "has_more": True,
            "items": [
                _q6h2a_album_payload(
                    "album-a"
                ),
                _q6h2a_album_payload(
                    "album-b"
                ),
            ],
            "total": 999,
            "offset": 25,
            "limit": 2,
            "unknown_root": "must-not-escape",
        }

    backend._catalog_request = request

    result = backend.get_label_albums(
        55,
        limit=2,
        offset=25,
    )

    params = {
        "label_id": "55",
        "limit": "2",
        "offset": "25",
    }

    assert calls == [
        (
            "/label/getAlbums",
            {
                "method_name": "labelgetalbums",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert result["ok"] is True
    assert result["label_id"] == "55"
    assert result["offset"] == 25
    assert result["limit"] == 2
    assert result["total"] == 999
    assert result["has_more"] is True

    assert [
        item["album_id"]
        for item in result["items"]
    ] == [
        "album-a",
        "album-b",
    ]

    assert result["items"][0]["artist"] == "Primary Artist"
    assert result["items"][0]["artist_id"] == "101"

    assert [
        artist["id"]
        for artist in result["items"][0]["artists"]
    ] == [
        "202",
        "101",
    ]

    rendered = repr(result)
    assert "must-not-escape" not in rendered
    assert "unknown_album_field" not in rendered


def test_q6h2a_label_albums_missing_items_uses_typed_default_empty(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {}
    )

    result = backend.get_label_albums(
        55,
        limit=7,
        offset=11,
    )

    assert result == {
        "ok": True,
        "label_id": "55",
        "items": [],
        "offset": 11,
        "limit": 7,
        "total": None,
        "has_more": None,
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {
            "items": {},
        },
        {
            "items": [],
            "has_more": "yes",
        },
        {
            "items": [],
            "total": True,
        },
        {
            "items": [],
            "total": -1,
        },
        {
            "items": [],
            "offset": "0",
        },
        {
            "items": [],
            "limit": "50",
        },
    ],
)
def test_q6h2a_label_albums_envelope_metadata_is_typed(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_label_albums(
            55,
            limit=5,
        )

    assert exc.value.code == "malformed_response"


def test_q6h2a_label_albums_malformed_typed_album_row_fails_whole_read(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "items": [
                _q6h2a_album_payload(
                    "valid"
                ),
                {
                    "id": None,
                    "title": "Malformed",
                },
            ],
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_label_albums(
            55,
            limit=2,
        )

    assert exc.value.code == "malformed_response"


def test_q6h2a_label_albums_rejects_page_larger_than_requested_limit(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "items": [
                _q6h2a_album_payload("one"),
                _q6h2a_album_payload("two"),
            ],
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_label_albums(
            55,
            limit=1,
        )

    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    "label_id",
    [
        None,
        "",
        0,
        -1,
        "abc",
    ],
)
def test_q6h2a_invalid_label_album_id_fails_before_request(
    tmp_path,
    label_id,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail("label-album provider request must not occur")
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_label_albums(
            label_id
        )

    assert exc.value.code == "invalid_request"

# Q6H2B_LABEL_SUBRESOURCES_CANDIDATE_TESTS


def _q6h2b_playlist_payload(
    playlist_id=9001,
    name="Label Playlist",
):
    return {
        "id": playlist_id,
        "name": name,
        "description": "Provider playlist",
        "owner": {
            "id": 1,
            "name": "Qobuz",
        },
        "tracks_count": 20,
        "duration": 6000,
        "image": {
            "covers": [
                "",
                f"https://img/playlist-{playlist_id}.jpg",
            ],
        },
        "unknown_playlist_field": "must-not-escape",
    }


def _q6h2b_artist_payload(
    artist_id=501,
    name="Label Artist",
):
    return {
        "id": artist_id,
        "name": name,
        "image": {
            "large": f"https://img/artist-{artist_id}.jpg",
        },
        "unknown_artist_field": "must-not-escape",
    }


def _q6h2b_valid_row(
    method_name,
    index,
):
    if method_name in {
        "get_label_next_releases",
        "get_label_awarded_releases",
    }:
        return _q6h2a_album_payload(
            f"album-{index}"
        )

    if method_name == "get_label_playlists":
        return _q6h2b_playlist_payload(
            9000 + index,
            f"Playlist {index}",
        )

    if method_name == "get_label_top_artists":
        return _q6h2b_artist_payload(
            500 + index,
            f"Artist {index}",
        )

    raise AssertionError(
        f"unsupported Q6H2B method: {method_name}"
    )


def test_q6h2b_next_releases_exact_signed_contract_and_album_normalization(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "label next releases must issue one provider request"
            )

        return {
            "has_more": True,
            "items": [
                _q6h2a_album_payload("next-a"),
                _q6h2a_album_payload("next-b"),
            ],
            "total": 77,
            "offset": 20,
            "limit": 2,
            "unknown_root": "must-not-escape",
        }

    backend._catalog_request = request

    result = backend.get_label_next_releases(
        " 55 ",
        limit=2,
        offset=20,
    )

    params = {
        "label_id": "55",
        "limit": "2",
        "offset": "20",
    }

    assert calls == [
        (
            "/label/getNextReleases",
            {
                "method_name": "labelgetnextreleases",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert result["ok"] is True
    assert result["label_id"] == "55"
    assert result["offset"] == 20
    assert result["limit"] == 2
    assert result["total"] == 77
    assert result["has_more"] is True

    assert [
        item["album_id"]
        for item in result["items"]
    ] == [
        "next-a",
        "next-b",
    ]

    first = result["items"][0]

    assert first["artist"] == "Primary Artist"
    assert first["artist_id"] == "101"

    assert [
        artist["id"]
        for artist in first["artists"]
    ] == [
        "202",
        "101",
    ]

    assert "genre_ids" not in calls[0][1]["params"]
    assert "must-not-escape" not in repr(result)


def test_q6h2b_awarded_releases_exact_signed_contract_without_deferred_filters(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    backend._catalog_request = lambda path, **kwargs: (
        calls.append((path, kwargs))
        or {
            "has_more": False,
            "items": [
                _q6h2a_album_payload(
                    "award-a"
                ),
                _q6h2a_album_payload(
                    "award-b"
                ),
            ],
            "total": 2,
        }
    )

    result = backend.get_label_awarded_releases(
        66,
        limit=2,
        offset=0,
    )

    params = {
        "label_id": "66",
        "limit": "2",
        "offset": "0",
    }

    assert calls == [
        (
            "/label/getAwardedReleases",
            {
                "method_name": "labelgetawardedreleases",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert [
        item["album_id"]
        for item in result["items"]
    ] == [
        "award-a",
        "award-b",
    ]

    request_params = calls[0][1]["params"]

    assert set(request_params) == {
        "label_id",
        "limit",
        "offset",
    }

    assert "sort" not in request_params
    assert "order" not in request_params
    assert "genre_ids" not in request_params


def test_q6h2b_label_playlists_exact_signed_contract_and_provider_order(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "label playlists must issue one provider request"
            )

        return {
            "has_more": True,
            "items": [
                _q6h2b_playlist_payload(
                    901,
                    "First",
                ),
                _q6h2b_playlist_payload(
                    902,
                    "Second",
                ),
            ],
            "total": 100,
        }

    backend._catalog_request = request

    result = backend.get_label_playlists(
        77,
        limit=2,
        offset=30,
    )

    params = {
        "label_id": "77",
        "limit": "2",
        "offset": "30",
    }

    assert calls == [
        (
            "/label/getPlaylists",
            {
                "method_name": "labelgetplaylists",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert [
        item["playlist_id"]
        for item in result["items"]
    ] == [
        "901",
        "902",
    ]

    assert [
        item["title"]
        for item in result["items"]
    ] == [
        "First",
        "Second",
    ]

    assert (
        result["items"][0]["artwork_url"]
        == "https://img/playlist-901.jpg"
    )
    assert "must-not-escape" not in repr(result)


def test_q6h2b_label_top_artists_exact_signed_contract_and_provider_order(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "label top artists must issue one provider request"
            )

        return {
            "has_more": False,
            "items": [
                _q6h2b_artist_payload(
                    301,
                    "First Artist",
                ),
                _q6h2b_artist_payload(
                    302,
                    "Second Artist",
                ),
            ],
            "total": 2,
        }

    backend._catalog_request = request

    result = backend.get_label_top_artists(
        88,
        limit=2,
        offset=5,
    )

    params = {
        "label_id": "88",
        "limit": "2",
        "offset": "5",
    }

    assert calls == [
        (
            "/label/getTopArtists",
            {
                "method_name": "labelgettopartists",
                "params": params,
                "signature_params": params,
                "require_auth": False,
            },
        )
    ]

    assert [
        item["artist_id"]
        for item in result["items"]
    ] == [
        "301",
        "302",
    ]

    assert [
        item["name"]
        for item in result["items"]
    ] == [
        "First Artist",
        "Second Artist",
    ]

    assert (
        result["items"][1]["artwork_url"]
        == "https://img/artist-302.jpg"
    )
    assert "must-not-escape" not in repr(result)


@pytest.mark.parametrize(
    "method_name",
    [
        "get_label_next_releases",
        "get_label_awarded_releases",
        "get_label_playlists",
        "get_label_top_artists",
    ],
)
@pytest.mark.parametrize(
    "label_id",
    [
        None,
        "",
        " ",
        0,
        -1,
        "abc",
    ],
)
def test_q6h2b_invalid_label_id_fails_before_request(
    tmp_path,
    method_name,
    label_id,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail(
            "Q6H2B provider request must not occur"
        )
    )

    method = getattr(
        backend,
        method_name,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        method(
            label_id
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "method_name",
    [
        "get_label_next_releases",
        "get_label_awarded_releases",
        "get_label_playlists",
        "get_label_top_artists",
    ],
)
@pytest.mark.parametrize(
    ("limit", "offset"),
    [
        (0, 0),
        (101, 0),
        ("bad", 0),
        (1, -1),
        (1, 1000001),
    ],
)
def test_q6h2b_invalid_bounds_fail_before_request(
    tmp_path,
    method_name,
    limit,
    offset,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail(
            "Q6H2B provider request must not occur"
        )
    )

    method = getattr(
        backend,
        method_name,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        method(
            77,
            limit=limit,
            offset=offset,
        )

    assert exc.value.code == "invalid_request"


@pytest.mark.parametrize(
    "method_name",
    [
        "get_label_next_releases",
        "get_label_awarded_releases",
        "get_label_playlists",
        "get_label_top_artists",
    ],
)
def test_q6h2b_missing_items_uses_typed_default_empty(
    tmp_path,
    method_name,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {}
    )

    method = getattr(
        backend,
        method_name,
    )

    result = method(
        77,
        limit=3,
        offset=7,
    )

    assert result["ok"] is True
    assert result["label_id"] == "77"
    assert result["items"] == []
    assert result["offset"] == 7
    assert result["limit"] == 3
    assert result["total"] is None
    assert result["has_more"] is None


@pytest.mark.parametrize(
    "method_name",
    [
        "get_label_next_releases",
        "get_label_awarded_releases",
        "get_label_playlists",
        "get_label_top_artists",
    ],
)
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {
            "items": {},
        },
        {
            "items": [],
            "has_more": "yes",
        },
        {
            "items": [],
            "total": True,
        },
        {
            "items": [],
            "total": -1,
        },
        {
            "items": [],
            "offset": "0",
        },
        {
            "items": [],
            "limit": "50",
        },
    ],
)
def test_q6h2b_typed_page_envelope_metadata_is_strict(
    tmp_path,
    method_name,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    method = getattr(
        backend,
        method_name,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        method(
            77,
            limit=5,
        )

    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    ("method_name", "bad_row"),
    [
        (
            "get_label_next_releases",
            {
                "id": None,
                "title": "Bad Album",
            },
        ),
        (
            "get_label_awarded_releases",
            {
                "id": None,
                "title": "Bad Album",
            },
        ),
        (
            "get_label_playlists",
            {
                "id": None,
                "name": "Bad Playlist",
            },
        ),
        (
            "get_label_top_artists",
            {
                "id": None,
                "name": "Bad Artist",
            },
        ),
    ],
)
def test_q6h2b_malformed_typed_row_fails_whole_read(
    tmp_path,
    method_name,
    bad_row,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "items": [
                _q6h2b_valid_row(
                    method_name,
                    1,
                ),
                bad_row,
            ],
        }
    )

    method = getattr(
        backend,
        method_name,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        method(
            77,
            limit=2,
        )

    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    "method_name",
    [
        "get_label_next_releases",
        "get_label_awarded_releases",
        "get_label_playlists",
        "get_label_top_artists",
    ],
)
def test_q6h2b_rejects_page_larger_than_requested_limit(
    tmp_path,
    method_name,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "items": [
                _q6h2b_valid_row(
                    method_name,
                    1,
                ),
                _q6h2b_valid_row(
                    method_name,
                    2,
                ),
            ],
        }
    )

    method = getattr(
        backend,
        method_name,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        method(
            77,
            limit=1,
        )

    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    "method_name",
    [
        "get_label_next_releases",
        "get_label_awarded_releases",
        "get_label_playlists",
        "get_label_top_artists",
    ],
)
def test_q6h2b_has_more_never_triggers_auto_paging(
    tmp_path,
    method_name,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "Q6H2B must not auto-fetch another page"
            )

        return {
            "has_more": True,
            "items": [
                _q6h2b_valid_row(
                    method_name,
                    1,
                ),
            ],
            "total": 9999,
        }

    backend._catalog_request = request

    method = getattr(
        backend,
        method_name,
    )

    result = method(
        77,
        limit=1,
        offset=500,
    )

    assert len(calls) == 1
    assert result["offset"] == 500
    assert result["limit"] == 1
    assert result["has_more"] is True
    assert result["total"] == 9999
    assert len(result["items"]) == 1

def test_q6h3a_award_request_id_accepts_provider_opaque_string_and_integer(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    assert backend._catalog_award_request_id(151) == "151"
    assert backend._catalog_award_request_id("press-award-151") == "press-award-151"
    assert backend._catalog_award_request_id("  award_abc-9  ") == "award_abc-9"


@pytest.mark.parametrize(
    "award_id",
    [
        None,
        "",
        " ",
        True,
        False,
        "award id",
        "award\tid",
        "award\nid",
        "café",
        "a" * 513,
        [],
        {},
    ],
)
def test_q6h3a_invalid_award_id_fails_before_request(
    tmp_path,
    award_id,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail(
            "Q6H3A provider request must not occur"
        )
    )

    for method_name in (
        "get_award_page",
        "get_award_albums",
    ):
        method = getattr(
            backend,
            method_name,
        )

        with pytest.raises(QobuzCatalogError) as exc:
            method(
                award_id
            )

        assert exc.value.code == "invalid_request"


def test_q6h3a_award_explore_exact_signed_authenticated_contract_and_provider_order(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "award explore must issue one provider request"
            )

        return {
            "has_more": True,
            "items": [
                {
                    "id": 151,
                    "name": "First Award",
                    "magazine": {
                        "name": "First Magazine",
                    },
                    "image": {
                        "mega": "https://img/mega.jpg",
                        "large": "https://img/large.jpg",
                        "small": "https://img/small.jpg",
                    },
                },
                {
                    "id": "award-two",
                    "name": "Second Award",
                    "image": "https://img/second.jpg",
                },
            ],
        }

    backend._catalog_request = request

    result = backend.get_award_explore(
        limit=2,
        offset=7,
    )

    params = {
        "limit": "2",
        "offset": "7",
    }

    assert calls == [
        (
            "/award/explore",
            {
                "method_name": "awardexplore",
                "params": params,
                "signature_params": params,
                "require_auth": True,
            },
        )
    ]

    assert result == {
        "ok": True,
        "items": [
            {
                "id": "151",
                "name": "First Award",
                "magazine": {
                    "name": "First Magazine",
                },
                "image": "https://img/large.jpg",
            },
            {
                "id": "award-two",
                "name": "Second Award",
                "magazine": None,
                "image": "https://img/second.jpg",
            },
        ],
        "offset": 7,
        "limit": 2,
        "has_more": True,
    }


def test_q6h3a_award_explore_drops_only_unusable_required_rows(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "items": [
                {
                    "id": 1,
                    "name": "Keep One",
                    "magazine": "unsupported optional",
                    "image": 123,
                },
                {
                    "id": None,
                    "name": "Drop Missing ID",
                },
                {
                    "id": 2,
                    "name": "",
                },
                "not-an-object",
                {
                    "id": "three",
                    "name": "Keep Three",
                    "magazine": {
                        "name": 123,
                    },
                    "image": {
                        "large": 123,
                        "small": "https://img/three.jpg",
                    },
                },
            ],
        }
    )

    result = backend.get_award_explore(
        limit=5
    )

    assert [
        item["id"]
        for item in result["items"]
    ] == [
        "1",
        "three",
    ]

    assert result["items"][0]["magazine"] is None
    assert result["items"][0]["image"] is None
    assert result["items"][1]["magazine"] is None
    assert result["items"][1]["image"] == "https://img/three.jpg"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {
            "items": {},
        },
        {
            "items": [],
            "has_more": "yes",
        },
    ],
)
def test_q6h3a_award_explore_envelope_is_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_award_explore(
            limit=5
        )

    assert exc.value.code == "malformed_response"


def test_q6h3a_award_explore_missing_items_defaults_empty_and_never_autopages(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "award explore must not auto-page"
            )

        return {
            "has_more": True,
        }

    backend._catalog_request = request

    result = backend.get_award_explore(
        limit=3,
        offset=500,
    )

    assert len(calls) == 1
    assert result["items"] == []
    assert result["offset"] == 500
    assert result["limit"] == 3
    assert result["has_more"] is True


def test_q6h3a_award_explore_rejects_page_larger_than_requested_limit(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "items": [
                {
                    "id": 1,
                    "name": "One",
                },
                {
                    "id": 2,
                    "name": "Two",
                },
            ],
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_award_explore(
            limit=1
        )

    assert exc.value.code == "malformed_response"


@pytest.mark.parametrize(
    ("limit", "offset"),
    [
        (0, 0),
        (101, 0),
        ("bad", 0),
        (1, -1),
        (1, 1000001),
    ],
)
def test_q6h3a_award_paged_reads_reject_invalid_c2_bounds_before_request(
    tmp_path,
    limit,
    offset,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = lambda *_args, **_kwargs: (
        pytest.fail(
            "invalid Q6H3A bounds must fail pre-request"
        )
    )

    with pytest.raises(QobuzCatalogError):
        backend.get_award_explore(
            limit=limit,
            offset=offset,
        )

    with pytest.raises(QobuzCatalogError):
        backend.get_award_albums(
            "award-1",
            limit=limit,
            offset=offset,
        )


def test_q6h3a_award_page_exact_signed_authenticated_contract_and_supported_fields(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "award page must issue one provider request"
            )

        return {
            "id": 151,
            "name": "Qobuzissime",
            "image": "https://img/award.jpg",
            "awarded_at": 1700000000,
            "magazine": {
                "id": "magazine-9",
                "name": "Qobuz",
                "image": "https://img/magazine.jpg",
            },
            "releases": [
                {
                    "must_not_escape": True,
                },
            ],
            "playlists": {
                "must_not_escape": True,
            },
        }

    backend._catalog_request = request

    result = backend.get_award_page(
        "award-151"
    )

    params = {
        "award_id": "award-151",
    }

    assert calls == [
        (
            "/award/page",
            {
                "method_name": "awardpage",
                "params": params,
                "signature_params": params,
                "require_auth": True,
            },
        )
    ]

    assert result == {
        "ok": True,
        "award_id": "award-151",
        "id": "151",
        "name": "Qobuzissime",
        "image": "https://img/award.jpg",
        "awarded_at": "1700000000",
        "magazine": {
            "id": "magazine-9",
            "name": "Qobuz",
            "image": "https://img/magazine.jpg",
        },
    }

    assert "must_not_escape" not in repr(result)


def test_q6h3a_award_page_minimal_empty_object_is_stable(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {}
    )

    result = backend.get_award_page(
        151
    )

    assert result == {
        "ok": True,
        "award_id": "151",
        "id": None,
        "name": None,
        "image": None,
        "awarded_at": None,
        "magazine": None,
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {
            "id": True,
        },
        {
            "name": 123,
        },
        {
            "image": {
                "large": "not-allowed-on-page",
            },
        },
        {
            "awarded_at": [],
        },
        {
            "magazine": [],
        },
        {
            "magazine": {
                "id": True,
            },
        },
        {
            "magazine": {
                "name": 123,
            },
        },
        {
            "magazine": {
                "image": {
                    "large": "not-allowed",
                },
            },
        },
    ],
)
def test_q6h3a_award_page_supported_typed_fields_are_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_award_page(
            "award-151"
        )

    assert exc.value.code == "malformed_response"


def test_q6h3a_award_albums_current_envelope_exact_contract_and_normalizer_reuse(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def request(path, **kwargs):
        calls.append((path, kwargs))

        if len(calls) > 1:
            raise AssertionError(
                "award albums must issue one provider request"
            )

        return {
            "has_more": True,
            "items": [
                _q6h2a_album_payload(
                    "award-album-1"
                ),
                _q6h2a_album_payload(
                    "award-album-2"
                ),
            ],
        }

    backend._catalog_request = request

    result = backend.get_award_albums(
        "press-151",
        limit=2,
        offset=9,
    )

    params = {
        "award_id": "press-151",
        "limit": "2",
        "offset": "9",
    }

    assert calls == [
        (
            "/award/getAlbums",
            {
                "method_name": "awardgetAlbums",
                "params": params,
                "signature_params": params,
                "require_auth": True,
            },
        )
    ]

    assert [
        item["album_id"]
        for item in result["items"]
    ] == [
        "award-album-1",
        "award-album-2",
    ]

    assert [
        item["source"]
        for item in result["items"]
    ] == [
        "qobuz",
        "qobuz",
    ]

    assert [
        item["artist_id"]
        for item in result["items"]
    ] == [
        "101",
        "101",
    ]

    assert result["items"][0]["artist"] == "Primary Artist"

    assert [
        artist["id"]
        for artist in result["items"][0]["artists"]
    ] == [
        "202",
        "101",
    ]

    assert result["items"][0]["artists"][1]["roles"] == [
        "main-artist"
    ]

    assert result["offset"] == 9
    assert result["limit"] == 2
    assert result["total"] is None
    assert result["has_more"] is True


def test_q6h3a_award_albums_supports_only_evidenced_legacy_albums_envelope(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "albums": {
                "items": [
                    _q6h2a_album_payload(
                        "legacy-award-album"
                    ),
                ],
                "total": 20,
                "offset": 5,
                "limit": 1,
            },
            "must_not_escape": True,
        }
    )

    result = backend.get_award_albums(
        "award-legacy",
        limit=1,
        offset=5,
    )

    assert len(result["items"]) == 1
    assert (
        result["items"][0]["album_id"]
        == "legacy-award-album"
    )
    assert result["items"][0]["source"] == "qobuz"
    assert result["items"][0]["artist_id"] == "101"
    assert result["total"] == 20
    assert result["offset"] == 5
    assert result["limit"] == 1
    assert result["has_more"] is None
    assert "must_not_escape" not in repr(result)


def test_q6h3a_award_albums_missing_items_defaults_empty(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {}
    )

    result = backend.get_award_albums(
        "award-empty",
        limit=3,
        offset=7,
    )

    assert result["items"] == []
    assert result["offset"] == 7
    assert result["limit"] == 3
    assert result["total"] is None
    assert result["has_more"] is None


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {
            "albums": [],
        },
        {
            "items": {},
        },
        {
            "items": [],
            "has_more": "yes",
        },
        {
            "items": [],
            "total": True,
        },
        {
            "items": [],
            "offset": "0",
        },
        {
            "items": [],
            "limit": "1",
        },
    ],
)
def test_q6h3a_award_album_envelope_and_metadata_are_strict(
    tmp_path,
    payload,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: payload
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_award_albums(
            "award-1",
            limit=2,
        )

    assert exc.value.code == "malformed_response"


def test_q6h3a_award_album_malformed_typed_row_fails_whole_read(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs: {
            "items": [
                _q6h2a_album_payload(
                    "good-award-album"
                ),
                {
                    "id": None,
                    "title": "Bad Award Album",
                },
            ],
        }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_award_albums(
            "award-1",
            limit=2,
        )

    assert exc.value.code == "malformed_response"


def test_q6h3a_award_albums_rejects_oversized_page_and_never_autopages(
    tmp_path,
):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=FakeHttp(),
        now=lambda: 1234567890,
    )

    calls = []

    def oversized(path, **kwargs):
        calls.append((path, kwargs))
        return {
            "has_more": True,
            "items": [
                _q6h2a_album_payload(
                    "award-a1"
                ),
                _q6h2a_album_payload(
                    "award-a2"
                ),
            ],
        }

    backend._catalog_request = oversized

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_award_albums(
            "award-1",
            limit=1,
        )

    assert exc.value.code == "malformed_response"
    assert len(calls) == 1

    calls.clear()

    backend._catalog_request = (
        lambda path, **kwargs: (
            calls.append((path, kwargs))
            or {
                "has_more": True,
                "items": [
                    _q6h2a_album_payload(
                        "award-a1"
                    ),
                ],
            }
        )
    )

    result = backend.get_award_albums(
        "award-1",
        limit=1,
        offset=500,
    )

    assert len(calls) == 1
    assert result["has_more"] is True
    assert result["offset"] == 500
    assert result["limit"] == 1
    assert len(result["items"]) == 1


def test_q6h4a_purchase_type_exact_allowlist_and_no_coercion():
    assert QobuzBackend._catalog_purchase_type(None) is None
    assert QobuzBackend._catalog_purchase_type("albums") == "albums"
    assert QobuzBackend._catalog_purchase_type("tracks") == "tracks"

    for value in (
        "",
        "Albums",
        "TRACKS",
        " albums ",
        "album",
        "track",
        1,
        True,
        [],
    ):
        with pytest.raises(Exception):
            QobuzBackend._catalog_purchase_type(value)


def test_q6h4a_get_user_purchases_exact_unsigned_authenticated_wire_contract(
    monkeypatch,
):
    calls = []

    def fake_request(self, path, **kwargs):
        calls.append((path, kwargs))
        return {
            "albums": {
                "items": [],
                "total": 0,
                "offset": 3,
                "limit": 7,
            }
        }

    monkeypatch.setattr(
        QobuzBackend,
        "_catalog_request",
        fake_request,
    )

    backend = object.__new__(QobuzBackend)

    result = backend.get_user_purchases(
        "albums",
        limit=7,
        offset=3,
    )

    assert len(calls) == 1

    path, kwargs = calls[0]

    assert path == "/purchase/getUserPurchases"
    assert kwargs["method_name"] == "purchasegetUserPurchases"
    assert kwargs["params"] == {
        "limit": 7,
        "offset": 3,
        "type": "albums",
    }
    assert kwargs["require_auth"] is True
    assert kwargs["signed"] is False
    assert "signature_params" not in kwargs

    assert result["source"] == "qobuz"
    assert result["albums"] == {
        "items": [],
        "total": 0,
        "offset": 3,
        "limit": 7,
    }
    assert result["tracks"] == {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 0,
    }


def test_q6h4a_get_user_purchases_ids_exact_unsigned_authenticated_wire_contract(
    monkeypatch,
):
    calls = []

    def fake_request(self, path, **kwargs):
        calls.append((path, kwargs))
        return {
            "tracks": {
                "items": [{"opaque": "ignored"}],
                "total": 17,
                "offset": 0,
                "limit": 1,
            }
        }

    monkeypatch.setattr(
        QobuzBackend,
        "_catalog_request",
        fake_request,
    )

    backend = object.__new__(QobuzBackend)

    result = backend.get_user_purchases_ids(
        "tracks",
        limit=1,
        offset=0,
    )

    assert len(calls) == 1

    path, kwargs = calls[0]

    assert path == "/purchase/getUserPurchasesIds"
    assert kwargs["method_name"] == "purchasegetUserPurchasesIds"
    assert kwargs["params"] == {
        "limit": 1,
        "offset": 0,
        "type": "tracks",
    }
    assert kwargs["require_auth"] is True
    assert kwargs["signed"] is False
    assert "signature_params" not in kwargs

    assert result["albums"] == {
        "total": 0,
        "offset": 0,
        "limit": 0,
    }
    assert result["tracks"] == {
        "total": 17,
        "offset": 0,
        "limit": 1,
    }
    assert "items" not in result["tracks"]


def test_q6h4a_none_purchase_type_omits_wire_type_parameter(
    monkeypatch,
):
    calls = []

    def fake_request(self, path, **kwargs):
        calls.append((path, kwargs))
        return {}

    monkeypatch.setattr(
        QobuzBackend,
        "_catalog_request",
        fake_request,
    )

    backend = object.__new__(QobuzBackend)

    backend.get_user_purchases(
        None,
        limit=5,
        offset=2,
    )
    backend.get_user_purchases_ids(
        None,
        limit=6,
        offset=4,
    )

    assert len(calls) == 2

    assert calls[0][1]["params"] == {
        "limit": 5,
        "offset": 2,
    }
    assert calls[1][1]["params"] == {
        "limit": 6,
        "offset": 4,
    }

    assert "type" not in calls[0][1]["params"]
    assert "type" not in calls[1][1]["params"]


def test_q6h4a_purchase_album_and_nested_tracks_normalize_provider_metadata_only():
    payload = {
        "id": 12345,
        "title": "Test Album",
        "artist": {
            "id": 99,
            "name": "Test Artist",
        },
        "image": {
            "large": "https://example.invalid/album.jpg",
        },
        "genre": "malformed optional provider field",
        "hires": True,
        "maximum_sampling_rate": 192.0,
        "maximum_bit_depth": 24,
        "purchased_at": 1700000000,
        "downloaded": True,
        "tracks": {
            "limit": 2,
            "offset": 0,
            "total": 2,
            "items": [
                {
                    "id": "777",
                    "title": "Track One",
                    "track_number": 1,
                    "media_number": 1,
                    "duration": 200,
                    "version": "Must Be Ignored",
                    "downloaded": True,
                    "downloaded_format_ids": [27],
                },
                {
                    "id": 778,
                    "title": "Track Two",
                    "track_number": 2,
                    "duration": 210,
                    "streamable": False,
                },
            ],
        },
    }

    album = QobuzBackend._normalize_qobuz_purchase_album(
        payload
    )

    assert album["source"] == "qobuz"
    assert album["album_id"] == "12345"
    assert album["title"] == "Test Album"
    assert album["artist"] == "Test Artist"
    assert album["downloadable"] is True
    assert album["purchased_at"] == 1700000000

    assert "downloaded" not in album
    assert "downloaded_format_ids" not in album

    nested = album["tracks"]

    assert nested["total"] == 2
    assert nested["offset"] == 0
    assert nested["limit"] == 2

    first = nested["items"][0]
    second = nested["items"][1]

    assert first["provider_track_id"] == "777"
    assert first["id"] == "qobuz:777"
    assert first["disc_number"] == 1
    assert first["streamable"] is True
    assert "version" not in first
    assert "downloaded" not in first
    assert "downloaded_format_ids" not in first

    assert second["provider_track_id"] == "778"
    assert second["id"] == "qobuz:778"
    assert second["streamable"] is False


def test_q6h4a_purchase_track_q5_identity_defaults_and_local_state_exclusion():
    track = QobuzBackend._normalize_qobuz_purchase_track(
        {
            "id": "606",
            "title": "Purchased Track",
            "track_number": 3,
            "media_number": 2,
            "duration": 240,
            "version": "Provider Stray Version",
            "purchased_at": 1700000123,
            "downloaded": True,
            "downloaded_format_ids": [27, 6],
        }
    )

    assert track["source"] == "qobuz"
    assert track["provider_track_id"] == "606"
    assert track["id"] == "qobuz:606"
    assert track["track_number"] == 3
    assert track["disc_number"] == 2
    assert track["streamable"] is True
    assert track["purchased_at"] == 1700000123

    assert "version" not in track
    assert "downloaded" not in track
    assert "downloaded_format_ids" not in track


def test_q6h4a_lenient_page_failure_isolated_to_only_malformed_page():
    response = QobuzBackend._normalize_qobuz_purchase_response(
        {
            "albums": {
                "items": "not-a-list",
                "total": 9,
                "offset": 0,
                "limit": 5,
            },
            "tracks": {
                "items": [
                    {
                        "id": 9001,
                        "title": "Still Usable",
                    }
                ],
                "total": 1,
                "offset": 0,
                "limit": 5,
            },
        }
    )

    assert response["albums"] == {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 0,
    }

    assert response["tracks"]["total"] == 1
    assert len(response["tracks"]["items"]) == 1
    assert (
        response["tracks"]["items"][0]["id"]
        == "qobuz:9001"
    )


def test_q6h4a_strict_purchase_item_decode_failure_empties_containing_page():
    response = QobuzBackend._normalize_qobuz_purchase_response(
        {
            "albums": {
                "items": [
                    {
                        "id": "album-1",
                        "title": 123,
                    }
                ],
                "total": 1,
                "offset": 0,
                "limit": 10,
            },
            "tracks": {
                "items": [
                    {
                        "id": 42,
                        "title": "Good Track",
                    }
                ],
                "total": 1,
                "offset": 0,
                "limit": 10,
            },
        }
    )

    assert response["albums"] == {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 0,
    }

    assert len(response["tracks"]["items"]) == 1
    assert response["tracks"]["items"][0]["id"] == "qobuz:42"


def test_q6h4a_lenient_optional_purchase_fields_become_none():
    album = QobuzBackend._normalize_qobuz_purchase_album(
        {
            "id": "album-optional",
            "title": "Optional Fields",
            "release_date_original": 123,
            "genre": "wrong-shape",
            "purchased_at": "not-an-integer",
        }
    )

    assert album["release_date_original"] is None
    assert album["genre"] is None
    assert album["purchased_at"] is None
    assert album["downloadable"] is True
    assert album["tracks"] is None

    album_with_bad_nested = (
        QobuzBackend._normalize_qobuz_purchase_album(
            {
                "id": "album-nested",
                "title": "Bad Optional Tracks",
                "tracks": "wrong-shape",
            }
        )
    )

    assert album_with_bad_nested["tracks"] is None


def test_q6h4a_purchase_ids_opaque_items_are_never_exposed_and_bad_page_zeros():
    result = QobuzBackend._normalize_qobuz_purchase_ids_response(
        {
            "albums": {
                "items": [
                    {"anything": [1, 2, 3]},
                    12345,
                ],
                "total": 42,
                "offset": 0,
                "limit": 1,
            },
            "tracks": {
                "items": [],
                "total": "bad-total",
                "offset": 0,
                "limit": 1,
            },
        }
    )

    assert result["albums"] == {
        "total": 42,
        "offset": 0,
        "limit": 1,
    }

    assert result["tracks"] == {
        "total": 0,
        "offset": 0,
        "limit": 0,
    }

    assert "items" not in result["albums"]
    assert "items" not in result["tracks"]


def test_q6h4a_invalid_type_and_c2_bounds_fail_before_provider_request(
    monkeypatch,
):
    calls = []

    def fake_request(self, path, **kwargs):
        calls.append((path, kwargs))
        return {}

    monkeypatch.setattr(
        QobuzBackend,
        "_catalog_request",
        fake_request,
    )

    backend = object.__new__(QobuzBackend)

    with pytest.raises(Exception):
        backend.get_user_purchases(
            "Albums",
            limit=1,
            offset=0,
        )

    with pytest.raises(Exception):
        backend.get_user_purchases(
            "albums",
            limit=101,
            offset=0,
        )

    with pytest.raises(Exception):
        backend.get_user_purchases_ids(
            "tracks",
            limit=1,
            offset=-1,
        )

    assert calls == []


def test_q6h4a_top_level_purchase_envelopes_are_strict_objects(
    monkeypatch,
):
    def fake_request(self, path, **kwargs):
        return []

    monkeypatch.setattr(
        QobuzBackend,
        "_catalog_request",
        fake_request,
    )

    backend = object.__new__(QobuzBackend)

    with pytest.raises(Exception):
        backend.get_user_purchases(
            "albums",
            limit=1,
            offset=0,
        )

    with pytest.raises(Exception):
        backend.get_user_purchases_ids(
            "tracks",
            limit=1,
            offset=0,
        )


def test_q6h5a_exact_unsigned_authenticated_radio_wire_contract(
    monkeypatch,
):
    calls = []

    def fake_request(self, path, **kwargs):
        calls.append((path, kwargs))
        return {
            "type": "provider-radio",
            "title": "Provider Radio",
            "tracks": {
                "items": [],
            },
        }

    monkeypatch.setattr(
        QobuzBackend,
        "_catalog_request",
        fake_request,
    )

    backend = object.__new__(QobuzBackend)

    artist = backend.get_radio_artist("123")
    track = backend.get_radio_track(456)
    album = backend.get_radio_album("0060254735180")

    assert calls == [
        (
            "/radio/artist",
            {
                "method_name": "radioartist",
                "params": {
                    "artist_id": "123",
                },
                "require_auth": True,
                "signed": False,
            },
        ),
        (
            "/radio/track",
            {
                "method_name": "radiotrack",
                "params": {
                    "track_id": "456",
                },
                "require_auth": True,
                "signed": False,
            },
        ),
        (
            "/radio/album",
            {
                "method_name": "radioalbum",
                "params": {
                    "album_id": "0060254735180",
                },
                "require_auth": True,
                "signed": False,
            },
        ),
    ]

    for result in (artist, track, album):
        assert result["source"] == "qobuz"
        assert result["type"] == "provider-radio"
        assert result["title"] == "Provider Radio"
        assert result["tracks"] == {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 0,
        }


def test_q6h5a_radio_request_ids_fail_before_network(
    monkeypatch,
):
    calls = []

    def fake_request(self, path, **kwargs):
        calls.append((path, kwargs))
        return {}

    monkeypatch.setattr(
        QobuzBackend,
        "_catalog_request",
        fake_request,
    )

    backend = object.__new__(QobuzBackend)

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_radio_artist(0)

    assert exc.value.code == "invalid_request"

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_radio_track("not-numeric")

    assert exc.value.code == "invalid_request"

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_radio_album("bad album id")

    assert exc.value.code == "invalid_request"
    assert calls == []


def test_q6h5a_radio_missing_pagination_preserves_salvageable_tracks():
    result = QobuzBackend._normalize_qobuz_radio_response(
        {
            "type": "album",
            "title": "Album Radio",
            "tracks": {
                "items": [
                    {
                        "id": 111,
                        "title": "One",
                    },
                    {
                        "id": "not-a-track-id",
                        "title": "Drop Me",
                    },
                    {
                        "id": 222,
                        "title": "Two",
                    },
                ],
            },
        }
    )

    assert result["source"] == "qobuz"
    assert result["type"] == "album"
    assert result["title"] == "Album Radio"

    tracks = result["tracks"]

    assert [
        item["id"]
        for item in tracks["items"]
    ] == [
        "qobuz:111",
        "qobuz:222",
    ]

    assert tracks["total"] == 2
    assert tracks["offset"] == 0
    assert tracks["limit"] == 2


def test_q6h5a_radio_valid_provider_pagination_survives_dropped_rows():
    result = QobuzBackend._normalize_qobuz_radio_response(
        {
            "tracks": {
                "items": [
                    {
                        "id": 901,
                        "title": "Usable",
                    },
                    {
                        "id": "bad",
                        "title": "Rejected",
                    },
                ],
                "total": 99,
                "offset": 12,
                "limit": 25,
            },
        }
    )

    assert [
        item["id"]
        for item in result["tracks"]["items"]
    ] == [
        "qobuz:901",
    ]

    assert result["tracks"]["total"] == 99
    assert result["tracks"]["offset"] == 12
    assert result["tracks"]["limit"] == 25


def test_q6h5a_radio_invalid_or_missing_page_scalars_use_qbz_fallbacks():
    result = QobuzBackend._normalize_qobuz_radio_response(
        {
            "tracks": {
                "items": [
                    {
                        "id": 777,
                        "title": "Only Good Row",
                    },
                    {
                        "id": "bad",
                        "title": "Rejected Row",
                    },
                ],
                "total": "bad-total",
                "offset": -1,
                "limit": None,
            },
        }
    )

    tracks = result["tracks"]

    assert [
        item["id"]
        for item in tracks["items"]
    ] == [
        "qobuz:777",
    ]

    assert tracks["total"] == 1
    assert tracks["offset"] == 0
    assert tracks["limit"] == 1


def test_q6h5a_radio_absent_null_or_malformed_tracks_page_is_empty():
    for payload in (
        {},
        {
            "tracks": None,
        },
        {
            "tracks": "wrong-shape",
        },
        {
            "tracks": [],
        },
    ):
        result = QobuzBackend._normalize_qobuz_radio_response(
            payload
        )

        assert result["tracks"] == {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 0,
        }


def test_q6h5a_radio_non_array_items_are_empty_but_valid_metadata_survives():
    result = QobuzBackend._normalize_qobuz_radio_response(
        {
            "tracks": {
                "items": "wrong-shape",
                "total": 8,
                "offset": 4,
                "limit": 2,
            },
        }
    )

    assert result["tracks"] == {
        "items": [],
        "total": 8,
        "offset": 4,
        "limit": 2,
    }


def test_q6h5a_radio_top_level_and_optional_text_fields_are_strict():
    with pytest.raises(QobuzCatalogError) as exc:
        QobuzBackend._normalize_qobuz_radio_response(
            []
        )

    assert exc.value.code == "malformed_response"

    with pytest.raises(QobuzCatalogError) as exc:
        QobuzBackend._normalize_qobuz_radio_response(
            {
                "type": 123,
            }
        )

    assert exc.value.code == "malformed_response"

    with pytest.raises(QobuzCatalogError) as exc:
        QobuzBackend._normalize_qobuz_radio_response(
            {
                "title": {
                    "bad": True,
                },
            }
        )

    assert exc.value.code == "malformed_response"

    result = QobuzBackend._normalize_qobuz_radio_response(
        {
            "type": None,
            "title": None,
        }
    )

    assert result["type"] is None
    assert result["title"] is None


def test_q6h5a_radio_q5_track_identity_and_provider_order_are_preserved():
    result = QobuzBackend._normalize_qobuz_radio_response(
        {
            "tracks": {
                "items": [
                    {
                        "id": 303,
                        "title": "Third",
                    },
                    {
                        "id": 101,
                        "title": "First",
                    },
                    {
                        "id": 202,
                        "title": "Second",
                    },
                ],
            },
        }
    )

    items = result["tracks"]["items"]

    assert [
        item["id"]
        for item in items
    ] == [
        "qobuz:303",
        "qobuz:101",
        "qobuz:202",
    ]

    assert [
        item["provider_track_id"]
        for item in items
    ] == [
        "303",
        "101",
        "202",
    ]

    assert all(
        item["source"] == "qobuz"
        for item in items
    )


def test_q6h5a_radio_unknown_fields_do_not_create_local_or_policy_state():
    result = QobuzBackend._normalize_qobuz_radio_response(
        {
            "type": "track",
            "title": "Track Radio",
            "unknown_top_level": {
                "ignored": True,
            },
            "tracks": {
                "items": [
                    {
                        "id": 5150,
                        "title": "Provider Track",
                        "downloaded": True,
                        "smart_radio_score": 999,
                    }
                ],
            },
        }
    )

    assert set(result) == {
        "source",
        "type",
        "title",
        "tracks",
    }

    item = result["tracks"]["items"][0]

    assert "downloaded" not in item
    assert "smart_radio_score" not in item


def test_q6h6a_user_playlists_exact_signed_authenticated_wire_contract(monkeypatch):
    backend = object.__new__(QobuzBackend)
    calls = []

    def fake_request(path, **kwargs):
        calls.append((path, kwargs))
        return {
            "playlists": {
                "items": [
                    {"id": 11, "name": "Owned One"},
                    {"id": 22, "name": "Owned Two"},
                ],
            },
        }

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        fake_request,
    )

    result = backend.get_user_playlists()

    assert [
        item["playlist_id"]
        for item in result
    ] == ["11", "22"]

    assert [
        item["title"]
        for item in result
    ] == [
        "Owned One",
        "Owned Two",
    ]

    assert calls == [
        (
            "/playlist/getUserPlaylists",
            {
                "method_name": "playlistgetUserPlaylists",
                "params": {},
                "signature_params": {},
                "require_auth": True,
                "signed": True,
            },
        ),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"playlists": None},
        {"playlists": []},
        {"playlists": {}},
        {"playlists": {"items": None}},
        {"playlists": {"items": {}}},
    ],
)
def test_q6h6a_user_playlist_envelope_is_strict(
    monkeypatch,
    payload,
):
    backend = object.__new__(QobuzBackend)

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        lambda path, **kwargs: payload,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_user_playlists()

    assert exc.value.code == "malformed_response"


def test_q6h6a_user_playlist_malformed_typed_row_fails_whole_read(
    monkeypatch,
):
    backend = object.__new__(QobuzBackend)

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        lambda path, **kwargs: {
            "playlists": {
                "items": [
                    {"id": 11, "name": "Good"},
                    {"id": 0, "name": "Bad"},
                ],
            },
        },
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_user_playlists()

    assert exc.value.code == "malformed_response"


def test_q6h6a_playlist_detail_exact_signed_optional_auth_wire_contract(
    monkeypatch,
):
    backend = object.__new__(QobuzBackend)
    calls = []

    def fake_request(path, **kwargs):
        calls.append((path, kwargs))
        return {
            "id": 77,
            "name": "Detail",
            "tracks": {
                "items": [],
                "total": 0,
            },
        }

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        fake_request,
    )

    result = backend.get_playlist(
        77,
        limit=25,
        offset=10,
    )

    expected_params = {
        "playlist_id": "77",
        "limit": "25",
        "offset": "10",
        "extra": "tracks",
    }

    assert calls == [
        (
            "/playlist/get",
            {
                "method_name": "playlistget",
                "params": expected_params,
                "signature_params": expected_params,
                "require_auth": False,
                "signed": True,
            },
        ),
    ]

    assert result["playlist_id"] == "77"

    assert result["tracks"] == {
        "items": [],
        "total": 0,
        "offset": 10,
        "limit": 25,
    }


@pytest.mark.parametrize(
    "playlist_id",
    [
        None,
        "",
        " ",
        0,
        -1,
        "abc",
        "1.5",
    ],
)
def test_q6h6a_invalid_playlist_id_fails_before_provider_request(
    monkeypatch,
    playlist_id,
):
    backend = object.__new__(QobuzBackend)
    calls = []

    def fake_request(path, **kwargs):
        calls.append((path, kwargs))
        raise AssertionError(
            "provider request must not occur"
        )

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        fake_request,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_playlist(playlist_id)

    assert exc.value.code == "invalid_request"
    assert calls == []


@pytest.mark.parametrize(
    ("limit", "offset"),
    [
        (0, 0),
        (101, 0),
        ("bad", 0),
        (1, -1),
        (1, 1_000_001),
    ],
)
def test_q6h6a_invalid_playlist_bounds_fail_before_provider_request(
    monkeypatch,
    limit,
    offset,
):
    backend = object.__new__(QobuzBackend)
    calls = []

    def fake_request(path, **kwargs):
        calls.append((path, kwargs))
        raise AssertionError(
            "provider request must not occur"
        )

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        fake_request,
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_playlist(
            77,
            limit=limit,
            offset=offset,
        )

    assert exc.value.code == "invalid_request"
    assert calls == []


@pytest.mark.parametrize(
    "tracks",
    [
        pytest.param("__ABSENT__", id="absent"),
        pytest.param(None, id="null"),
    ],
)
def test_q6h6a_playlist_missing_or_null_tracks_is_empty_page(
    monkeypatch,
    tracks,
):
    backend = object.__new__(QobuzBackend)

    payload = {
        "id": 77,
        "name": "Detail",
    }

    if tracks != "__ABSENT__":
        payload["tracks"] = tracks

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        lambda path, **kwargs: payload,
    )

    result = backend.get_playlist(
        77,
        limit=12,
        offset=7,
    )

    assert result["tracks"] == {
        "items": [],
        "total": 0,
        "offset": 7,
        "limit": 12,
    }


@pytest.mark.parametrize(
    "tracks",
    [
        [],
        "bad",
        {"items": None, "total": 0},
        {"items": {}, "total": 0},
        {"items": [], "total": None},
        {"items": [], "total": True},
        {"items": [], "total": -1},
        {"items": [], "total": "1"},
        {"items": []},
        {"items": [], "total": 0x100000000},
    ],
)
def test_q6h6a_playlist_track_page_is_strict(
    monkeypatch,
    tracks,
):
    backend = object.__new__(QobuzBackend)

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        lambda path, **kwargs: {
            "id": 77,
            "name": "Detail",
            "tracks": tracks,
        },
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_playlist(77)

    assert exc.value.code == "malformed_response"


def test_q6h6a_playlist_tracks_preserve_q5_identity_and_provider_order(
    monkeypatch,
):
    backend = object.__new__(QobuzBackend)

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        lambda path, **kwargs: {
            "id": 77,
            "name": "Detail",
            "tracks": {
                "items": [
                    {"id": 3003, "title": "Third"},
                    {"id": 1001, "title": "First"},
                    {"id": 2002, "title": "Second"},
                ],
                "total": 9,
            },
        },
    )

    result = backend.get_playlist(
        77,
        limit=3,
        offset=3,
    )

    tracks = result["tracks"]

    assert tracks["total"] == 9
    assert tracks["offset"] == 3
    assert tracks["limit"] == 3

    assert [
        item["provider_track_id"]
        for item in tracks["items"]
    ] == [
        "3003",
        "1001",
        "2002",
    ]

    assert [
        item["id"]
        for item in tracks["items"]
    ] == [
        "qobuz:3003",
        "qobuz:1001",
        "qobuz:2002",
    ]


def test_q6h6a_malformed_playlist_track_fails_whole_detail_read(
    monkeypatch,
):
    backend = object.__new__(QobuzBackend)

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        lambda path, **kwargs: {
            "id": 77,
            "name": "Detail",
            "tracks": {
                "items": [
                    {"id": 1, "title": "Good"},
                    {"id": 0, "title": "Bad"},
                ],
                "total": 2,
            },
        },
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_playlist(
            77,
            limit=2,
            offset=0,
        )

    assert exc.value.code == "malformed_response"


def test_q6h6a_playlist_rejects_provider_page_larger_than_requested_limit(
    monkeypatch,
):
    backend = object.__new__(QobuzBackend)

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        lambda path, **kwargs: {
            "id": 77,
            "name": "Detail",
            "tracks": {
                "items": [
                    {"id": 1, "title": "One"},
                    {"id": 2, "title": "Two"},
                ],
                "total": 2,
            },
        },
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_playlist(
            77,
            limit=1,
            offset=0,
        )

    assert exc.value.code == "malformed_response"


def test_q6h6a_playlist_detail_is_exactly_one_bounded_request_without_autopaging(
    monkeypatch,
):
    backend = object.__new__(QobuzBackend)
    calls = []

    def fake_request(path, **kwargs):
        calls.append((path, kwargs))
        return {
            "id": 77,
            "name": "Detail",
            "tracks": {
                "items": [
                    {
                        "id": 1,
                        "title": "Only Provider Page Item",
                    },
                ],
                "total": 5000,
            },
        }

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        fake_request,
    )

    result = backend.get_playlist(
        77,
        limit=1,
        offset=100,
    )

    assert len(calls) == 1
    assert result["tracks"]["total"] == 5000
    assert result["tracks"]["offset"] == 100
    assert result["tracks"]["limit"] == 1
    assert len(result["tracks"]["items"]) == 1


def test_q6h6a_unknown_playlist_and_track_fields_do_not_escape_normalized_models(
    monkeypatch,
):
    backend = object.__new__(QobuzBackend)

    monkeypatch.setattr(
        backend,
        "_catalog_request",
        lambda path, **kwargs: {
            "id": 77,
            "name": "Detail",
            "provider_secret_playlist_field":
                "must-not-escape",
            "tracks": {
                "items": [
                    {
                        "id": 1,
                        "title": "One",
                        "provider_secret_track_field":
                            "must-not-escape",
                    },
                ],
                "total": 1,
                "provider_secret_page_field":
                    "must-not-escape",
            },
        },
    )

    result = backend.get_playlist(77)

    assert (
        "provider_secret_playlist_field"
        not in result
    )
    assert (
        "provider_secret_page_field"
        not in result["tracks"]
    )
    assert (
        "provider_secret_track_field"
        not in result["tracks"]["items"][0]
    )
