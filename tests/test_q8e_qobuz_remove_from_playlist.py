import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest

import backend.qobuz as qobuz_module
from backend.qobuz import QobuzBackend
from backend.qobuz_catalog import QobuzCatalogError


def qrow(
    track_id,
    playlist_track_id=None,
    *,
    source="qobuz",
):
    track_id = str(track_id)

    row = {
        "source": source,
        "id": (
            "qobuz:" + track_id
            if source == "qobuz"
            else track_id
        ),
        "provider_track_id": track_id,
        "title": "Track " + track_id,
    }

    if playlist_track_id is not None:
        row["playlist_track_id"] = str(
            playlist_track_id
        )

    return row


def make_backend(
    rows,
    *,
    owner_id="1772594",
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

    state = {
        "rows": [
            dict(row)
            for row in rows
        ],
        "owner_id":
            str(owner_id),
        "calls": [],
        "offsets": [],
    }

    def get_playlist(
        playlist_id,
        *,
        limit=None,
        offset=None,
    ):
        limit = int(
            limit or 100
        )

        offset = int(
            offset or 0
        )

        state["offsets"].append(
            offset
        )

        return {
            "playlist_id":
                str(playlist_id),
            "name":
                "Owned Qobuz Playlist",
            "owner_id":
                state["owner_id"],
            "tracks": {
                "items": [
                    dict(row)
                    for row
                    in state["rows"][
                        offset:
                        offset + limit
                    ]
                ],
                "total":
                    len(state["rows"]),
                "offset":
                    offset,
                "limit":
                    limit,
            },
        }

    backend.get_playlist = (
        get_playlist
    )

    return backend, state


def test_q8e_playlist_normalizer_preserves_occurrence_identity(
    monkeypatch,
):
    monkeypatch.setattr(
        QobuzBackend,
        "_normalize_qobuz_track",
        classmethod(
            lambda cls, item:
                qrow(item["id"])
        ),
    )

    page = (
        QobuzBackend
        ._normalize_qobuz_playlist_tracks_page(
            {
                "items": [{
                    "id": "7",
                    "playlist_track_id":
                        901,
                }],
                "total": 1,
            },
            limit=100,
            offset=0,
        )
    )

    assert (
        page["items"][0][
            "playlist_track_id"
        ]
        == "901"
    )


def test_q8e_playlist_normalizer_never_synthesizes_occurrence_identity(
    monkeypatch,
):
    monkeypatch.setattr(
        QobuzBackend,
        "_normalize_qobuz_track",
        classmethod(
            lambda cls, item:
                qrow(item["id"])
        ),
    )

    page = (
        QobuzBackend
        ._normalize_qobuz_playlist_tracks_page(
            {
                "items": [{
                    "id": "7",
                }],
                "total": 1,
            },
            limit=100,
            offset=0,
        )
    )

    assert (
        "playlist_track_id"
        not in page["items"][0]
    )


def test_q8e_duplicate_catalog_track_removes_all_occurrences_and_uses_native_wire_contract():
    backend, state = make_backend([
        qrow("7", "101"),
        qrow("8", "102"),
        qrow("7", "103"),
    ])

    def request(
        path,
        **kwargs,
    ):
        state["calls"].append(
            (path, kwargs)
        )

        deleted = set(
            kwargs["params"][
                "playlist_track_ids"
            ].split(",")
        )

        state["rows"] = [
            row
            for row in state["rows"]
            if str(
                row.get(
                    "playlist_track_id"
                )
            )
            not in deleted
        ]

        return {
            "status": "success"
        }

    backend._catalog_request = (
        request
    )

    result = (
        backend.remove_tracks_from_playlist(
            "77",
            [
                qrow(
                    "7",
                    "101",
                )
            ],
        )
    )

    assert result["ok"] is True
    assert result["confirmed"] is True
    assert result["requested"] == 1
    assert result["items_removed"] == 1
    assert (
        result["occurrences_removed"]
        == 2
    )
    assert result["total_before"] == 3
    assert result["total_after"] == 1

    assert [
        row["provider_track_id"]
        for row in state["rows"]
    ] == ["8"]

    assert state["calls"] == [
        (
            "/playlist/deleteTracks",
            {
                "method_name":
                    "playlistdeleteTracks",
                "params": {
                    "playlist_id":
                        "77",
                    "playlist_track_ids":
                        "101,103",
                },
                "signature_params": {
                    "playlist_id":
                        "77",
                    "playlist_track_ids":
                        "101,103",
                },
                "require_auth":
                    True,
                "signed":
                    True,
            },
        )
    ]


def test_q8e_foreign_playlist_rejected_before_provider_mutation():
    backend, state = make_backend(
        [
            qrow(
                "7",
                "101",
            )
        ],
        owner_id="263468",
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "foreign playlist must not mutate"
                )
            )
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.remove_tracks_from_playlist(
            "77",
            [qrow("7", "101")],
        )

    assert (
        exc.value.code
        == "not_editable"
    )
    assert state["calls"] == []


def test_q8e_wrong_provider_rejected():
    backend, _state = make_backend(
        [qrow("7", "101")]
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.remove_tracks_from_playlist(
            "77",
            [
                qrow(
                    "7",
                    "101",
                    source="tidal",
                )
            ],
        )

    assert (
        exc.value.code
        == "invalid_request"
    )


def test_q8e_missing_selected_occurrence_rejected():
    backend, _state = make_backend(
        [qrow("7", "101")]
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.remove_tracks_from_playlist(
            "77",
            [qrow("7")],
        )

    assert (
        exc.value.code
        == "invalid_request"
    )


def test_q8e_stale_occurrence_rejected_before_provider_mutation():
    backend, _state = make_backend(
        [qrow("7", "101")]
    )

    backend._catalog_request = (
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "stale occurrence must not mutate"
                )
            )
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.remove_tracks_from_playlist(
            "77",
            [qrow("7", "999")],
        )

    assert (
        exc.value.code
        == "playlist_changed"
    )


def test_q8e_occurrence_must_belong_to_selected_catalog_track():
    backend, _state = make_backend([
        qrow("8", "102"),
    ])

    backend._catalog_request = (
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "mismatched occurrence must not mutate"
                )
            )
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.remove_tracks_from_playlist(
            "77",
            [qrow("7", "102")],
        )

    assert (
        exc.value.code
        == "invalid_request"
    )


def test_q8e_missing_duplicate_occurrence_fails_closed_before_mutation():
    backend, _state = make_backend([
        qrow("7", "101"),
        qrow("7"),
    ])

    backend._catalog_request = (
        lambda *_args, **_kwargs:
            (_ for _ in ()).throw(
                AssertionError(
                    "incomplete occurrence truth must not mutate"
                )
            )
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.remove_tracks_from_playlist(
            "77",
            [qrow("7", "101")],
        )

    assert (
        exc.value.code
        == "malformed_response"
    )


def test_q8e_large_playlist_resolves_target_beyond_first_page():
    rows = [
        qrow(
            str(index),
            str(10000 + index),
        )
        for index
        in range(1, 251)
    ]

    backend, state = make_backend(
        rows
    )

    def request(
        path,
        **kwargs,
    ):
        assert (
            path
            == "/playlist/deleteTracks"
        )

        deleted = set(
            kwargs["params"][
                "playlist_track_ids"
            ].split(",")
        )

        state["rows"] = [
            row
            for row in state["rows"]
            if row[
                "playlist_track_id"
            ]
            not in deleted
        ]

        return {}

    backend._catalog_request = (
        request
    )

    result = (
        backend.remove_tracks_from_playlist(
            "77",
            [
                qrow(
                    "205",
                    "10205",
                )
            ],
        )
    )

    assert result["confirmed"] is True

    assert (
        state["offsets"][:3]
        == [0, 100, 200]
    )


def test_q8e_explicit_provider_failure_is_not_success():
    backend, _state = make_backend([
        qrow("7", "101"),
    ])

    backend._catalog_request = (
        lambda *_args, **_kwargs:
            {
                "ok": False,
                "error": "rejected",
            }
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.remove_tracks_from_playlist(
            "77",
            [qrow("7", "101")],
        )

    assert (
        exc.value.code
        == "provider_error"
    )


def test_q8e_reconciliation_is_bounded_and_never_false_success(
    monkeypatch,
):
    backend, _state = make_backend([
        qrow("7", "101"),
    ])

    backend._catalog_request = (
        lambda *_args, **_kwargs:
            {}
    )

    sleeps = []

    monkeypatch.setattr(
        qobuz_module.time,
        "sleep",
        lambda value:
            sleeps.append(value),
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.remove_tracks_from_playlist(
            "77",
            [qrow("7", "101")],
        )

    assert (
        exc.value.code
        == "reconcile_timeout"
    )

    assert sleeps == [
        1.0,
        3.0,
    ]


ROOT = Path(
    __file__
).resolve().parents[1]

MAIN_SOURCE = (
    ROOT
    / "src"
    / "main_headless.py"
).read_text(
    encoding="utf-8"
)

UI_SOURCE = (
    ROOT
    / "src"
    / "ui_web"
    / "ui.js"
).read_text(
    encoding="utf-8"
)


def js_function(name):
    marker = (
        "function "
        + name
        + "("
    )

    start = UI_SOURCE.index(
        marker
    )

    brace = UI_SOURCE.index(
        "{",
        start,
    )

    depth = 0
    quote = None
    escape = False

    for index in range(
        brace,
        len(UI_SOURCE),
    ):
        char = UI_SOURCE[
            index
        ]

        if quote is not None:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None

            continue

        if char in (
            "'",
            '"',
            "`",
        ):
            quote = char
            continue

        if char == "{":
            depth += 1

        elif char == "}":
            depth -= 1

            if depth == 0:
                return UI_SOURCE[
                    start:
                    index + 1
                ]

    raise AssertionError(
        "unterminated function "
        + name
    )


def python_function_source(
    source,
    name,
):
    tree = ast.parse(
        source
    )

    lines = source.splitlines()

    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(
            node,
            ast.FunctionDef,
        )
        and node.name == name
    ]

    assert len(matches) == 1

    node = matches[0]

    return "\n".join(
        lines[
            node.lineno - 1:
            node.end_lineno
        ]
    )


import ast


def test_q8e_complete_playlist_detail_uses_positive_qobuz_ownership_gate():
    source = python_function_source(
        MAIN_SOURCE,
        "_complete_streaming_playlist_payload",
    )

    assert (
        "_playlist_owned_by_current_user"
        in source
    )

    assert (
        '"playlist_editable": playlist_editable'
        in source
    )


def test_q8e_headless_route_is_provider_specific_confirmed_only_and_queue_inert():
    start = MAIN_SOURCE.index(
        'if self.path == "/qobuz/playlist/remove_tracks":'
    )

    end = MAIN_SOURCE.index(
        "# -- Playlist: delete one owned Qobuz playlist",
        start,
    )

    route = MAIN_SOURCE[
        start:end
    ]

    assert (
        "backend.remove_tracks_from_playlist("
        in route
    )

    assert (
        'result.get('
        in route
    )

    assert (
        '"confirmed"'
        in route
    )

    assert (
        "PLAY_QUEUE"
        not in route
    )

    assert (
        "ORIGINAL_QUEUE"
        not in route
    )

    assert (
        "player."
        not in route
    )

    assert (
        "tidal"
        not in route.lower()
    )


def test_q8e_ui_posts_provider_occurrence_identity_only():
    source = js_function(
        "postRemoveTracksFromQobuzPlaylist"
    )

    assert (
        '"/qobuz/playlist/remove_tracks"'
        in source
    )

    assert (
        "normalizeQobuzPlaylistRemoveTracks"
        in source
    )

    assert (
        "playlist_track_id"
        in js_function(
            "normalizeQobuzPlaylistRemoveTracks"
        )
    )


def test_q8e_remove_modal_matches_tidal_visible_behavior_and_refreshes_truth():
    source = js_function(
        "showRemoveFromQobuzPlaylistModal"
    )

    for token in (
        '"tidalPlaylistModal"',
        '"tidalPlaylistCard tidalPlaylistDeleteCard"',
        '"Remove Track"',
        '"REMOVE FROM PLAYLIST"',
        '"Removing..."',
        '"Removing track..."',
        '"Removed from playlist"',
    ):
        assert token in source

    assert (
        "postRemoveTracksFromQobuzPlaylist("
        in source
    )

    assert (
        "loadStreamingPlaylistDetail("
        in source
    )

    assert (
        '"qobuz"'
        in source
    )


def test_q8e_owned_qobuz_detail_can_expose_remove_without_enabling_tidal_favorites():
    loader = js_function(
        "loadStreamingPlaylistDetail"
    )

    renderer = js_function(
        "renderTrackList"
    )

    assert (
        "resp.playlist_editable === true"
        in loader
    )

    assert (
        "canRemoveFromQobuzPlaylist"
        in renderer
    )

    assert (
        "currentContext.playlist_editable === true"
        in renderer
    )

    assert (
        "showRemoveFromQobuzPlaylistModal("
        in renderer
    )

    # The locked Q7F guard still blocks TIDAL favorite mutation
    # on every Qobuz playlist detail, including owned playlists.
    assert (
        "qobuzReadOnlyPlaylist"
        in renderer
    )

    assert (
        "if (!qobuzReadOnlyPlaylist)"
        in renderer
    )




def test_q8e_q8f_authorizes_qobuz_rename_route_and_ui():
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
