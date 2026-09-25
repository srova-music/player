
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest

import backend.qobuz as qobuz_module
from backend.qobuz import QobuzBackend
from backend.qobuz_catalog import QobuzCatalogError


def qtrack(track_id):
    track_id = str(track_id)
    return {
        "source": "qobuz",
        "id": "qobuz:" + track_id,
        "provider_track_id": track_id,
    }


def make_backend(track_ids=None, *, owner_id="1772594", user_id="1772594"):
    backend = object.__new__(QobuzBackend)
    backend._auth_lock = threading.RLock()
    backend.authenticated = bool(user_id)
    backend._session = (
        {
            "user_id": str(user_id),
            "user_auth_token": "test-token",
        }
        if user_id
        else None
    )

    state = {
        "track_ids": [str(value) for value in (track_ids or [])],
        "owner_id": str(owner_id),
        "calls": [],
    }

    def get_playlist(playlist_id, *, limit=None, offset=None):
        limit = int(limit or 100)
        offset = int(offset or 0)
        items = [
            qtrack(value)
            for value in state["track_ids"][offset:offset + limit]
        ]
        return {
            "playlist_id": str(playlist_id),
            "owner_id": state["owner_id"],
            "tracks": {
                "items": items,
                "total": len(state["track_ids"]),
                "offset": offset,
                "limit": limit,
            },
        }

    backend.get_playlist = get_playlist
    return backend, state


def test_q8d_native_add_success_and_wire_contract():
    backend, state = make_backend(["1"])

    def request(path, **kwargs):
        state["calls"].append((path, kwargs))
        assert path == "/playlist/addTracks"
        state["track_ids"].append("2")
        return {"status": "success"}

    backend._catalog_request = request

    result = backend.add_tracks_to_playlist(
        "77",
        [qtrack("2")],
    )

    assert result["ok"] is True
    assert result["confirmed"] is True
    assert result["items_added"] == 1
    assert result["duplicates_skipped"] == 0
    assert result["total_before"] == 1
    assert result["total_after"] == 2

    assert state["calls"] == [
        (
            "/playlist/addTracks",
            {
                "method_name": "playlistaddTracks",
                "params": {
                    "playlist_id": "77",
                    "track_ids": "2",
                },
                "signature_params": {
                    "playlist_id": "77",
                    "track_ids": "2",
                },
                "require_auth": True,
                "signed": True,
            },
        )
    ]


def test_q8d_duplicate_is_skipped_without_provider_mutation():
    backend, state = make_backend(["2"])

    backend._catalog_request = (
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "provider add must not run for duplicate"
                )
            )
    )

    result = backend.add_tracks_to_playlist(
        "77",
        [qtrack("2")],
    )

    assert result["ok"] is True
    assert result["items_added"] == 0
    assert result["duplicates_skipped"] == 1
    assert result["provider_request_sent"] is False
    assert state["track_ids"] == ["2"]


def test_q8d_duplicate_input_is_collapsed_and_order_is_preserved():
    backend, state = make_backend([])

    sent = []

    def request(_path, **kwargs):
        sent.append(
            kwargs["params"]["track_ids"]
        )
        state["track_ids"].extend(
            kwargs["params"]["track_ids"].split(",")
        )
        return {}

    backend._catalog_request = request

    result = backend.add_tracks_to_playlist(
        "77",
        [
            qtrack("3"),
            qtrack("2"),
            qtrack("3"),
            qtrack("1"),
        ],
    )

    assert sent == ["3,2,1"]
    assert result["items_added"] == 3
    assert result["duplicates_skipped"] == 1
    assert state["track_ids"] == ["3", "2", "1"]


def test_q8d_read_only_playlist_is_rejected_before_provider_mutation():
    backend, state = make_backend(
        [],
        owner_id="263468",
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "provider add must not run for foreign playlist"
                )
            )
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.add_tracks_to_playlist(
            "77",
            [qtrack("2")],
        )

    assert exc.value.code == "not_editable"
    assert state["calls"] == []


def test_q8d_wrong_provider_identity_is_rejected():
    backend, _state = make_backend([])

    backend._catalog_request = (
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "provider add must not run"
                )
            )
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.add_tracks_to_playlist(
            "77",
            [{
                "source": "tidal",
                "id": "123",
                "provider_track_id": "123",
            }],
        )

    assert exc.value.code == "invalid_request"


def test_q8d_missing_provider_track_id_is_rejected():
    backend, _state = make_backend([])

    with pytest.raises(QobuzCatalogError) as exc:
        backend.add_tracks_to_playlist(
            "77",
            [{
                "source": "qobuz",
                "id": "qobuz:123",
            }],
        )

    assert exc.value.code == "invalid_request"


def test_q8d_provider_mutation_failure_is_not_reported_as_success():
    backend, _state = make_backend([])

    def request(*_args, **_kwargs):
        raise QobuzCatalogError(
            "provider_error",
            "Provider rejected add.",
        )

    backend._catalog_request = request

    with pytest.raises(QobuzCatalogError) as exc:
        backend.add_tracks_to_playlist(
            "77",
            [qtrack("2")],
        )

    assert exc.value.code == "provider_error"


def test_q8d_explicit_failure_envelope_is_rejected():
    backend, _state = make_backend([])
    backend._catalog_request = (
        lambda *_args, **_kwargs:
            {
                "ok": False,
                "error": "rejected",
            }
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.add_tracks_to_playlist(
            "77",
            [qtrack("2")],
        )

    assert exc.value.code == "provider_error"


def test_q8d_reconciliation_timeout_is_bounded_and_never_returns_success(
    monkeypatch,
):
    backend, _state = make_backend([])
    backend._catalog_request = (
        lambda *_args, **_kwargs: {}
    )

    sleeps = []
    monkeypatch.setattr(
        qobuz_module.time,
        "sleep",
        lambda value: sleeps.append(value),
    )

    with pytest.raises(QobuzCatalogError) as exc:
        backend.add_tracks_to_playlist(
            "77",
            [qtrack("2")],
        )

    assert exc.value.code == "reconcile_timeout"
    assert sleeps == [1.0, 3.0]


def test_q8d_large_playlist_duplicate_detection_reads_beyond_first_page():
    ids = [
        str(value)
        for value in range(1, 251)
    ]

    backend, state = make_backend(ids)

    offsets = []
    original_get = backend.get_playlist

    def recorded_get(
        playlist_id,
        *,
        limit=None,
        offset=None,
    ):
        offsets.append(int(offset or 0))
        return original_get(
            playlist_id,
            limit=limit,
            offset=offset,
        )

    backend.get_playlist = recorded_get

    backend._catalog_request = (
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "existing track on page three must be skipped"
                )
            )
    )

    result = backend.add_tracks_to_playlist(
        "77",
        [qtrack("205")],
    )

    assert result["items_added"] == 0
    assert result["duplicates_skipped"] == 1
    assert offsets == [0, 100, 200]
    assert state["track_ids"][204] == "205"



ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
MAIN_SOURCE = (ROOT / "src/main_headless.py").read_text(encoding="utf-8")


def js_function(name):
    marker = "function " + name + "("
    start = UI_SOURCE.index(marker)
    brace = UI_SOURCE.index("{", start)
    depth = 0
    quote = None
    escape = False

    for index in range(brace, len(UI_SOURCE)):
        char = UI_SOURCE[index]

        if quote is not None:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue

        if char in ("'", '"', "`"):
            quote = char
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return UI_SOURCE[start:index + 1]

    raise AssertionError("unterminated function " + name)


def test_q8d_picker_exposes_only_editable_qobuz_targets():
    source = js_function(
        "fetchQobuzPlaylistsForPicker"
    )

    assert '"/qobuz/catalog?op=playlists"' in source
    assert "adaptQobuzUserPlaylist" in source
    assert "playlist.playlist_editable === true" in source


def test_q8d_picker_uses_existing_tidal_geometry_without_cross_provider_mapping():
    source = js_function(
        "showAddToQobuzPlaylistModal"
    )

    for token in (
        '"tidalPlaylistModal"',
        '"tidalPlaylistCard tidalPlaylistPickerCard"',
        '"tidalPlaylistPickerControls"',
        '"tidalPlaylistPickerList"',
        '"tidalPlaylistPickerRow"',
        '"Add to Playlist"',
    ):
        assert token in source

    assert "postAddTracksToQobuzPlaylist(" in source
    assert "postCreateQobuzPlaylist(" not in source
    assert "showAddToTidalPlaylistModal" not in source
    assert "ISRC" not in source
    assert "isrc" not in source


def test_q8d_qobuz_identity_normalizer_fails_closed():
    source = js_function(
        "normalizeQobuzPlaylistTracks"
    )

    assert 'source !== "qobuz"' in source
    assert 'canonicalId !== "qobuz:" + providerTrackId' in source
    assert "provider_track_id" in source
    assert "/^[0-9]+$/" in source


def test_q8d_shared_queue_popover_keeps_tidal_and_adds_qobuz_branch():
    source = js_function(
        "showQueuePopover"
    )

    assert "showAddToQobuzPlaylistModal(" in source
    assert "showAddToTidalPlaylistModal(tidalTrackIds)" in source
    assert "allQobuzTracks" in source


def test_q8d_qobuz_wall_menu_exposes_provider_specific_add():
    source = js_function(
        "showQobuzTrackArtworkMenu"
    )

    assert '"Add to Playlist"' in source
    assert "showAddToQobuzPlaylistModal(" in source
    assert "showAddToTidalPlaylistModal" not in source


def test_q8d_headless_route_is_provider_specific_and_confirmed_only():
    start = MAIN_SOURCE.index(
        'if self.path == "/qobuz/playlist/add_tracks":'
    )
    end = MAIN_SOURCE.index(
        '# -- Playlist: delete one owned Qobuz playlist',
        start,
    )
    route = MAIN_SOURCE[start:end]

    assert "backend.add_tracks_to_playlist(" in route
    assert 'result.get("ok")' in route
    assert '"confirmed"' in route
    assert "tidal" not in route.lower()
    assert "player." not in route
    assert "PLAY_QUEUE" not in route




def test_q8d_q8f_authorizes_qobuz_rename_route_and_ui():
    assert (
        'if self.path == "/qobuz/playlist/rename":'
        in MAIN_SOURCE
    )

    assert (
        '"/qobuz/playlist/rename"'
        in UI_SOURCE
    )

    assert (
        "postRenameQobuzPlaylist"
        in UI_SOURCE
    )
