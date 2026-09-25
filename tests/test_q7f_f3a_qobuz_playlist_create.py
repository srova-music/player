import os
import re
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


from backend.qobuz import (
    QobuzBackend,
    QobuzCatalogError,
)


ROOT = Path(__file__).resolve().parents[1]

QOBUZ_SOURCE = (
    ROOT
    / "src"
    / "backend"
    / "qobuz.py"
)

MAIN_SOURCE = (
    ROOT
    / "src"
    / "main_headless.py"
)

UI_SOURCE = (
    ROOT
    / "src"
    / "ui_web"
    / "ui.js"
)

CATALOG_SOURCE = (
    ROOT
    / "src"
    / "backend"
    / "qobuz_catalog.py"
)


def js_function(name):
    src = UI_SOURCE.read_text(
        encoding="utf-8"
    )

    match = re.search(
        rf"function\s+{re.escape(name)}"
        rf"\s*\([^)]*\)\s*\{{",
        src,
    )

    assert match, name

    brace = src.find(
        "{",
        match.start(),
    )

    depth = 0
    quote = None
    escaped = False

    for index in range(
        brace,
        len(src),
    ):
        char = src[index]

        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

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
                return src[
                    match.start():
                    index + 1
                ]

    raise AssertionError(
        "unterminated " + name
    )


def make_backend(request):
    backend = object.__new__(
        QobuzBackend
    )

    backend._catalog_request = request

    return backend


def created_playlist_payload():
    return {
        "id": 987654321,
        "name": "SROVA F3A Test",
        "description": "Created by test",
        "owner": {
            "id": 1772594,
            "name": "Sasha",
        },
        "images300": [],
        "images150": [],
        "images": [],
        "tracks_count": 0,
        "duration": 0,
        "is_public": False,
        "slug": None,
        "users_count": 0,
    }


def test_f3a_backend_uses_existing_signed_authenticated_get_contract():
    calls = []

    def request(
        path,
        **kwargs,
    ):
        calls.append(
            (path, kwargs)
        )

        return (
            created_playlist_payload()
        )

    backend = make_backend(
        request
    )

    result = backend.create_playlist(
        "  SROVA F3A Test  ",
        "  Created by test  ",
        is_public=False,
    )

    assert result["ok"] is True
    assert result["id"] == "987654321"
    assert result["playlist"]["playlist_id"] == "987654321"
    assert result["name"] == "SROVA F3A Test"
    assert result["is_public"] is False

    assert calls == [
        (
            "/playlist/create",
            {
                "method_name":
                    "playlistcreate",
                "params": {
                    "name":
                        "SROVA F3A Test",
                    "is_public":
                        "false",
                    "description":
                        "Created by test",
                },
                "signature_params": {
                    "name":
                        "SROVA F3A Test",
                    "is_public":
                        "false",
                    "description":
                        "Created by test",
                },
                "require_auth":
                    True,
                "signed":
                    True,
            },
        )
    ]


@pytest.mark.parametrize(
    "name",
    [
        None,
        "",
        "   ",
        "x" * 4097,
    ],
)
def test_f3a_invalid_name_fails_before_provider_request(
    name,
):
    def unexpected(
        *_args,
        **_kwargs,
    ):
        raise AssertionError(
            "provider request must not run"
        )

    backend = make_backend(
        unexpected
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.create_playlist(
            name
        )

    assert (
        exc.value.code
        == "invalid_request"
    )


@pytest.mark.parametrize(
    "description",
    [
        123,
        "bad\x00description",
        "x" * 65537,
    ],
)
def test_f3a_invalid_description_fails_before_provider_request(
    description,
):
    backend = make_backend(
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "provider request must not run"
                )
            )
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.create_playlist(
            "Valid",
            description,
        )

    assert (
        exc.value.code
        == "invalid_request"
    )


def test_f3a_privacy_must_be_boolean():
    backend = make_backend(
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "provider request must not run"
                )
            )
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.create_playlist(
            "Valid",
            is_public="false",
        )

    assert (
        exc.value.code
        == "invalid_request"
    )


def test_f3a_empty_description_is_not_sent_to_provider():
    calls = []

    def request(
        path,
        **kwargs,
    ):
        calls.append(
            (path, kwargs)
        )

        return (
            created_playlist_payload()
        )

    backend = make_backend(
        request
    )

    backend.create_playlist(
        "Valid",
        "   ",
        is_public=False,
    )

    params = calls[0][1]["params"]

    assert "description" not in params
    assert params["is_public"] == "false"


def test_f3a_headless_route_is_separate_from_catalog_get_gateway():
    src = MAIN_SOURCE.read_text(
        encoding="utf-8"
    )

    assert (
        'if self.path == "/qobuz/playlist/create":'
        in src
    )

    assert (
        "backend.create_playlist("
        in src
    )

    route_start = src.index(
        'if self.path == "/qobuz/playlist/create":'
    )

    tidal_start = src.index(
        '# -- Playlist: create empty TIDAL playlist',
        route_start,
    )

    route = src[
        route_start:
        tidal_start
    ]

    assert "/qobuz/catalog" not in route
    assert "postTidalQueueReplace" not in route
    assert "player." not in route


def test_f3a_ui_posts_private_qobuz_playlist_create():
    source = js_function(
        "postCreateQobuzPlaylist"
    )

    assert (
        '"/qobuz/playlist/create"'
        in source
    )

    assert "is_public: false" in source


def test_f3a_qobuz_modal_stabilizes_local_cache_before_reconcile():
    source = js_function(
        "showCreateQobuzPlaylistModal"
    )

    # The original F3A candidate cleared the successful local result and
    # immediately re-read Qobuz. That was superseded after live acceptance
    # proved an eventual-consistency race.
    assert (
        "qobuzPlaylistsLoaded = false"
        not in source
    )

    assert (
        "qobuzPlaylists = []"
        not in source
    )

    assert (
        "loadQobuzPlaylists()"
        not in source
    )

    assert (
        "upsertQobuzPlaylistLocal("
        in source
    )

    assert (
        "renderPlaylistsList("
        in source
    )

    assert (
        "reconcileQobuzPlaylistsAfterCreate("
        in source
    )

    assert (
        "invalidateTidalPlaylistUiCache"
        not in source
    )


def test_f3a_dual_auth_qobuz_modal_title_is_explicit():
    source = js_function(
        "qobuzPlaylistModalPresentationTitle"
    )

    assert (
        '"Create QOBUZ Playlist"'
        in source
    )

    assert "availability.dual !== true" in source


def test_f3a_qobuz_playlist_header_exposes_create_button():
    source = js_function(
        "renderPlaylistsList"
    )

    assert (
        "showCreateQobuzPlaylistModal"
        in source
    )

    assert (
        "qobuzCreateBtn"
        in source
    )


def test_f3a_catalog_transport_remains_get_only():
    src = CATALOG_SOURCE.read_text(
        encoding="utf-8"
    )

    assert "def _network_get(" in src
    assert "def _network_post(" not in src

    request_match = re.search(
        r"def request_json\(",
        src,
    )

    assert request_match

    request_tail = src[
        request_match.start():
    ]

    assert (
        "response = self._network_get("
        in request_tail
    )


def test_f3a_backend_create_does_not_touch_playback_or_queue():
    src = QOBUZ_SOURCE.read_text(
        encoding="utf-8"
    )

    start = src.index(
        "    def create_playlist("
    )

    end = src.index(
        "    def get_playlist(",
        start,
    )

    function = src[
        start:end
    ]

    for forbidden in (
        "player",
        "queue",
        "PLAY_QUEUE",
        "resolve_track_delivery",
        "qobuz_stream",
    ):
        assert forbidden not in function


def test_f3a_postcreate_success_requires_explicit_ok_and_playlist():
    source = js_function(
        "showCreateQobuzPlaylistModal"
    )

    assert "data.ok !== true" in source
    assert "!data.playlist" in source


def test_f3a_postcreate_uses_local_upsert_before_render():
    source = js_function(
        "showCreateQobuzPlaylistModal"
    )

    assert (
        "upsertQobuzPlaylistLocal("
        in source
    )

    assert (
        "renderPlaylistsList("
        in source
    )

    assert (
        "reconcileQobuzPlaylistsAfterCreate("
        in source
    )

    assert (
        "loadQobuzPlaylists()"
        not in source
    )

    assert (
        "qobuzPlaylists = []"
        not in source
    )


def test_f3a_local_upsert_deduplicates_created_playlist():
    source = js_function(
        "upsertQobuzPlaylistLocal"
    )

    assert (
        "adaptQobuzUserPlaylist("
        in source
    )

    assert (
        "qobuzPlaylists.forEach("
        in source
    )

    assert (
        "existing.id"
        in source
    )

    assert (
        "qobuzPlaylists = next"
        in source
    )

    assert (
        "qobuzPlaylistsLoaded = true"
        in source
    )


def test_f3a_reconciliation_never_replaces_local_cache_when_created_id_missing():
    source = js_function(
        "reconcileQobuzPlaylistsAfterCreate"
    )

    assert (
        "var confirmed"
        in source
    )

    assert (
        "if (!confirmed)"
        in source
    )

    assert (
        "attempt + 1"
        in source
    )

    missing_index = source.index(
        "if (!confirmed)"
    )

    assignment_index = source.index(
        "qobuzPlaylists ="
    )

    assert (
        assignment_index
        > missing_index
    )


def test_f3a_reconciliation_is_bounded_and_read_only():
    source = js_function(
        "reconcileQobuzPlaylistsAfterCreate"
    )

    assert (
        "3000"
        in source
    )

    assert (
        "10000"
        in source
    )

    assert (
        "30000"
        in source
    )

    assert (
        '"/qobuz/catalog?op=playlists"'
        in source
    )

    assert (
        '"/qobuz/playlist/create"'
        not in source
    )

    assert (
        "postCreateQobuzPlaylist"
        not in source
    )
