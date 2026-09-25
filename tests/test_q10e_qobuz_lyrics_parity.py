import json
import os
import sys
from pathlib import Path

import pytest


sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
    ),
)


from backend.qobuz import QobuzBackend
from backend.qobuz_catalog import QobuzCatalogError


class StreamResponse:
    def __init__(self, payload, status_code=200):
        self.status_code = int(status_code)
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False

    def iter_content(self, chunk_size=65536):
        for offset in range(
            0,
            len(self._body),
            int(chunk_size),
        ):
            yield self._body[
                offset : offset + int(chunk_size)
            ]


class LyricsHttp:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = int(status_code)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(
            {
                "url": url,
                **kwargs,
            }
        )
        return StreamResponse(
            self.payload,
            status_code=self.status_code,
        )


def make_backend(tmp_path, document):
    http = LyricsHttp(document)

    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=http,
        now=lambda: 1234567890,
    )

    return backend, http


def test_qobuz_native_synced_lyrics_normalize(
    tmp_path,
):
    document = {
        "track_id": 266725027,
        "album_id": "album",
        "original": {
            "type": "wsync",
            "lang": "en",
            "lines": [
                {
                    "line": "First test line",
                    "start": 1250,
                    "end": 3000,
                    "words": [],
                },
                {
                    "line": "",
                    "words": [],
                },
                {
                    "line": "Second test line",
                    "start": 3250,
                    "end": 5000,
                    "words": [],
                },
            ],
        },
    }

    backend, http = make_backend(
        tmp_path,
        document,
    )

    catalog_calls = []

    def catalog_request(path, **kwargs):
        catalog_calls.append(
            (path, kwargs)
        )
        return {
            "track_id": 266725027,
            "album_id": "album",
            "lyrics_url":
                "https://lyrics.example.net/doc.json",
        }

    backend._catalog_request = catalog_request

    result = backend.get_lyrics("266725027")

    assert result == {
        "synced": True,
        "lines": [
            {
                "ms": 1250,
                "text": "First test line",
            },
            {
                "ms": 3250,
                "text": "Second test line",
            },
        ],
    }

    assert len(catalog_calls) == 1

    path, kwargs = catalog_calls[0]

    assert path == "/track/lyricsUrl"
    assert kwargs["method_name"] == "tracklyricsUrl"
    assert kwargs["params"] == {
        "track_id": "266725027"
    }
    assert kwargs["require_auth"] is True

    assert len(http.calls) == 1
    assert (
        http.calls[0]["url"]
        == "https://lyrics.example.net/doc.json"
    )
    assert (
        http.calls[0]["allow_redirects"]
        is False
    )


def test_qobuz_native_plain_lyrics_normalize(
    tmp_path,
):
    document = {
        "track_id": "4001",
        "original": {
            "type": "plain",
            "lang": "en",
            "lines": [
                {"line": "Alpha"},
                {"line": "Beta"},
            ],
        },
    }

    backend, _http = make_backend(
        tmp_path,
        document,
    )

    backend._catalog_request = (
        lambda _path, **_kwargs: {
            "track_id": 4001,
            "lyrics_url":
                "https://lyrics.example.net/plain.json",
        }
    )

    assert backend.get_lyrics("4001") == {
        "synced": False,
        "text": "Alpha\nBeta",
    }


def test_qobuz_native_404_is_no_lyrics(
    tmp_path,
):
    backend, _http = make_backend(
        tmp_path,
        {},
    )

    def catalog_request(_path, **_kwargs):
        raise QobuzCatalogError(
            "not_found",
            "No lyrics found.",
            http_status=404,
        )

    backend._catalog_request = catalog_request

    assert backend.get_lyrics("4001") is None


@pytest.mark.parametrize(
    "track_id",
    [
        "",
        "qobuz:4001",
        "abc",
        "-1",
        "0",
    ],
)
def test_qobuz_backend_requires_native_numeric_id(
    tmp_path,
    track_id,
):
    backend, _http = make_backend(
        tmp_path,
        {},
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.get_lyrics(track_id)

    assert exc.value.code == "invalid_request"


def test_q10e_web_provider_dispatch_and_stale_guard():
    root = Path(__file__).resolve().parents[1]

    ui = (
        root / "src" / "ui_web" / "ui.js"
    ).read_text(encoding="utf-8")

    headless = (
        root / "src" / "main_headless.py"
    ).read_text(encoding="utf-8")

    index = (
        root / "src" / "ui_web" / "index.html"
    ).read_text(encoding="utf-8")

    assert 'var lyricsRequestSerial = 0;' in ui
    assert 'lyricsRequestSerial += 1;' in ui
    assert (
        'var requestSerial = ++lyricsRequestSerial;'
        in ui
    )
    assert (
        'requestSerial !== lyricsRequestSerial'
        in ui
    )
    assert 'source === "qobuz"' in ui
    assert '"/qobuz/lyrics/"' in ui

    assert (
        'if static_path.startswith("/qobuz/lyrics/"):'
        in headless
    )
    assert 'backend.get_lyrics(track_id)' in headless

    # Existing TIDAL and Local routes remain present.
    assert '"/tidal/lyrics/"' in headless
    assert '"/api/local/library/lyrics/"' in headless

    # Browser cache bust advances for the Q10E JS.
    assert "q10e_qobuz_lyrics_js11" in index


def test_qobuz_lyrics_success_is_cached(
    tmp_path,
):
    document = {
        "track_id": "5001",
        "original": {
            "type": "plain",
            "lang": "en",
            "lines": [
                {"line": "Cached test line"},
            ],
        },
    }

    backend, http = make_backend(
        tmp_path,
        document,
    )

    catalog_calls = []

    def catalog_request(path, **kwargs):
        catalog_calls.append((path, kwargs))
        return {
            "track_id": 5001,
            "lyrics_url":
                "https://lyrics.example.net/cache.json",
        }

    backend._catalog_request = catalog_request

    first = backend.get_lyrics("5001")
    second = backend.get_lyrics("5001")

    assert first == {
        "synced": False,
        "text": "Cached test line",
    }
    assert second == first

    assert len(catalog_calls) == 1
    assert len(http.calls) == 1


def test_qobuz_no_lyrics_is_cached(
    tmp_path,
):
    backend, http = make_backend(
        tmp_path,
        {},
    )

    calls = []

    def catalog_request(path, **kwargs):
        calls.append((path, kwargs))
        raise QobuzCatalogError(
            "not_found",
            "No lyrics found.",
            http_status=404,
        )

    backend._catalog_request = catalog_request

    assert backend.get_lyrics("5002") is None
    assert backend.get_lyrics("5002") is None

    assert len(calls) == 1
    assert http.calls == []


def test_qobuz_lyrics_cache_is_bounded(
    tmp_path,
):
    backend, _http = make_backend(
        tmp_path,
        {},
    )

    backend._lyrics_cache_max_entries = 3

    backend._lyrics_cache_store("1", {"text": "1"})
    backend._lyrics_cache_store("2", {"text": "2"})
    backend._lyrics_cache_store("3", {"text": "3"})

    # Touch 1 so 2 becomes the least recently used.
    hit, value = backend._lyrics_cache_lookup("1")
    assert hit is True
    assert value == {"text": "1"}

    backend._lyrics_cache_store("4", {"text": "4"})

    assert list(backend._lyrics_cache) == [
        "3",
        "1",
        "4",
    ]
    assert "2" not in backend._lyrics_cache
