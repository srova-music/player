import os
import re
import sys
import threading
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
from backend.tidal import TidalBackend


ROOT = Path(__file__).resolve().parents[1]

QOBUZ_SOURCE = (
    ROOT
    / "src"
    / "backend"
    / "qobuz.py"
)

TIDAL_SOURCE = (
    ROOT
    / "src"
    / "backend"
    / "tidal.py"
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


def qobuz_playlist_payload(
    playlist_id,
    owner_id,
    name="Test",
):
    return {
        "id": int(playlist_id),
        "name": name,
        "description": "",
        "owner": {
            "id": int(owner_id),
            "name": "Owner",
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


def make_qobuz_backend(
    request=None,
    user_id="1772594",
):
    backend = object.__new__(
        QobuzBackend
    )

    backend._auth_lock = (
        threading.RLock()
    )

    backend.authenticated = bool(
        user_id
    )

    backend._session = (
        {
            "user_id":
                str(user_id),
            "user_auth_token":
                "test-token",
        }
        if user_id
        else None
    )

    if request is not None:
        backend._catalog_request = (
            request
        )

    return backend


def test_f3b_qobuz_user_playlist_rows_are_ownership_annotated():
    def request(
        path,
        **kwargs,
    ):
        assert (
            path
            == "/playlist/getUserPlaylists"
        )

        return {
            "playlists": {
                "items": [
                    qobuz_playlist_payload(
                        1,
                        1772594,
                        "Owned",
                    ),
                    qobuz_playlist_payload(
                        2,
                        263468,
                        "Foreign",
                    ),
                ]
            }
        }

    backend = make_qobuz_backend(
        request
    )

    rows = (
        backend.get_user_playlists()
    )

    assert (
        rows[0]["playlist_editable"]
        is True
    )

    assert (
        rows[1]["playlist_editable"]
        is False
    )


def test_f3b_qobuz_owned_delete_reverifies_then_uses_signed_auth_get():
    calls = []

    def request(
        path,
        **kwargs,
    ):
        calls.append(
            (
                path,
                kwargs,
            )
        )

        return {
            "ok": True
        }

    backend = make_qobuz_backend(
        request
    )

    backend.get_playlist = (
        lambda playlist_id, **kwargs:
            {
                "playlist_id":
                    str(playlist_id),
                "owner_id":
                    "1772594",
            }
    )

    result = backend.delete_playlist(
        "69813971"
    )

    assert result == {
        "ok": True,
        "playlist_id":
            "69813971",
    }

    assert calls == [
        (
            "/playlist/delete",
            {
                "method_name":
                    "playlistdelete",
                "params": {
                    "playlist_id":
                        "69813971",
                },
                "signature_params": {
                    "playlist_id":
                        "69813971",
                },
                "require_auth":
                    True,
                "signed":
                    True,
            },
        )
    ]


def test_f3b_qobuz_foreign_delete_fails_before_provider_delete():
    calls = []

    backend = make_qobuz_backend(
        lambda *args, **kwargs:
            calls.append(
                (
                    args,
                    kwargs,
                )
            )
    )

    backend.get_playlist = (
        lambda playlist_id, **kwargs:
            {
                "playlist_id":
                    str(playlist_id),
                "owner_id":
                    "263468",
            }
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.delete_playlist(
            "55768465"
        )

    assert (
        exc.value.code
        == "not_editable"
    )

    assert calls == []


def test_f3b_qobuz_delete_requires_authenticated_runtime_user():
    backend = make_qobuz_backend(
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "provider delete must not run"
                )
            ),
        user_id="",
    )

    backend.get_playlist = (
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "playlist lookup must not run"
                )
            )
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.delete_playlist(
            "69813971"
        )

    assert (
        exc.value.code
        == "not_authenticated"
    )


def test_f3b_qobuz_delete_route_is_separate_and_safe():
    src = MAIN_SOURCE.read_text(
        encoding="utf-8"
    )

    assert (
        'if self.path == "/qobuz/playlist/delete":'
        in src
    )

    assert (
        "backend.delete_playlist("
        in src
    )

    start = src.index(
        'if self.path == "/qobuz/playlist/delete":'
    )

    end = src.index(
        "# -- Playlist: create empty TIDAL playlist",
        start,
    )

    route = src[
        start:
        end
    ]

    assert (
        "safe_payload"
        in route
    )

    assert (
        "postTidalQueueReplace"
        not in route
    )

    assert (
        "player."
        not in route
    )


def test_f3b_qobuz_delete_does_not_extend_catalog_transport():
    src = CATALOG_SOURCE.read_text(
        encoding="utf-8"
    )

    assert "def _network_get(" in src
    assert "def _network_post(" not in src


class FakeTidalPlaylist:
    def __init__(self):
        self.id = "test-playlist"
        self.deleted = 0

    def delete(self):
        self.deleted += 1
        return True


def test_f3b_tidal_unowned_delete_fails_closed():
    backend = object.__new__(
        TidalBackend
    )

    playlist = FakeTidalPlaylist()

    backend._resolve_user_playlist = (
        lambda _playlist_id:
            playlist
    )

    backend._is_owned_user_playlist = (
        lambda _playlist:
            False
    )

    result = (
        backend.delete_cloud_playlist(
            "test-playlist"
        )
    )

    assert result["ok"] is False
    assert playlist.deleted == 0
    assert "not editable" in (
        result["error"].lower()
    )


def test_f3b_tidal_owned_delete_still_works():
    backend = object.__new__(
        TidalBackend
    )

    playlist = FakeTidalPlaylist()

    backend._resolve_user_playlist = (
        lambda _playlist_id:
            playlist
    )

    backend._is_owned_user_playlist = (
        lambda _playlist:
            True
    )

    result = (
        backend.delete_cloud_playlist(
            "test-playlist"
        )
    )

    assert result["ok"] is True
    assert playlist.deleted == 1


def test_f3b_tidal_list_serializes_creator_ownership():
    src = MAIN_SOURCE.read_text(
        encoding="utf-8"
    )

    route_start = src.index(
        'if self.path == "/tidal/myplaylists":'
    )

    route_end = src.index(
        "# -- Playlists: find duplicates",
        route_start,
    )

    route = src[
        route_start:
        route_end
    ]

    assert (
        'pl.get("creator")'
        in route
    )

    assert (
        '"creator_id":'
        in route
    )

    assert (
        '"playlist_editable":'
        in route
    )

    assert (
        "current_user_id"
        in route
    )


def test_f3b_tidal_http_route_does_not_convert_denial_to_success():
    src = MAIN_SOURCE.read_text(
        encoding="utf-8"
    )

    start = src.index(
        'if self.path == "/tidal/playlist/delete":'
    )

    end = src.index(
        "# -- Playlist: create from explicit track list",
        start,
    )

    route = src[
        start:
        end
    ]

    assert (
        'result.get("ok") is not True'
        in route
    )

    assert (
        '(result or {}).get("error")'
        in route
    )


def test_f3b_ui_qobuz_adapter_preserves_manageability():
    source = js_function(
        "adaptQobuzUserPlaylist"
    )

    assert "owner_id:" in source
    assert "owner_name:" in source
    assert "playlist_editable:" in source


def test_f3b_ui_delete_button_is_positive_ownership_gated_for_both_providers():
    source = js_function(
        "renderPlaylistRows"
    )

    assert (
        "item.playlist_editable"
        in source
    )

    assert (
        'provider === "tidal"'
        in source
    )

    assert (
        'provider === "qobuz"'
        in source
    )

    assert (
        "showDeleteTidalPlaylistModal"
        in source
    )

    assert (
        "showDeleteQobuzPlaylistModal"
        in source
    )


def test_f3b_ui_qobuz_delete_requires_explicit_confirmation_and_local_removal():
    source = js_function(
        "showDeleteQobuzPlaylistModal"
    )

    assert (
        "playlist.playlist_editable"
        in source
    )

    assert (
        "postDeleteQobuzPlaylist("
        in source
    )

    assert (
        "data.ok !== true"
        in source
    )

    assert (
        "removeQobuzPlaylistLocal("
        in source
    )

    assert (
        "reconcileQobuzPlaylistsAfterDelete("
        in source
    )

    assert (
        "DELETE PLAYLIST"
        in source
    )


def test_f3b_qobuz_delete_reconciliation_is_bounded_and_read_only():
    source = js_function(
        "reconcileQobuzPlaylistsAfterDelete"
    )

    for delay in (
        "3000",
        "10000",
        "30000",
    ):
        assert delay in source

    assert (
        '"/qobuz/catalog?op=playlists"'
        in source
    )

    assert (
        "postJson("
        not in source
    )

    assert (
        "/qobuz/playlist/delete"
        not in source
    )

    assert (
        "stillPresent"
        in source
    )

    assert (
        "attempt + 1"
        in source
    )


def test_f3b_qobuz_delete_tombstone_prevents_stale_row_render():
    source = js_function(
        "renderPlaylistRows"
    )

    assert (
        "isQobuzPlaylistDeleteTombstoned("
        in source
    )


def test_f3b_q8f_supersedes_rename_absence():
    src = UI_SOURCE.read_text(
        encoding="utf-8"
    )

    assert (
        "postRenameQobuzPlaylist"
        in src
    )

    assert (
        "postAddTracksToQobuzPlaylist"
        in src
    )

    assert (
        "postRemoveTracksFromQobuzPlaylist"
        in src
    )
