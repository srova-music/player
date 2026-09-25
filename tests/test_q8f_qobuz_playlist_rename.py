import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(REPO_ROOT / "src"),
)

import backend.qobuz as qobuz_module
from backend.qobuz import QobuzBackend
from backend.qobuz_catalog import QobuzCatalogError


MAIN_SOURCE = (
    REPO_ROOT
    / "src"
    / "main_headless.py"
).read_text(
    encoding="utf-8"
)


def make_backend(
    *,
    owner_id="7",
    current_user_id="7",
    before_name="Original Name",
    after_names=None,
    response_id="77",
    provider_payload=None,
):
    backend = object.__new__(
        QobuzBackend
    )

    state = {
        "reads": [],
        "requests": [],
    }

    if after_names is None:
        after_names = [
            "Renamed Playlist",
        ]

    after_names = list(
        after_names
    )

    backend._current_session_user_id = (
        lambda: current_user_id
    )

    def get_playlist(
        playlist_id,
        *,
        limit=None,
        offset=None,
    ):
        state["reads"].append(
            (
                playlist_id,
                limit,
                offset,
            )
        )

        if len(
            state["reads"]
        ) == 1:
            name = before_name
        else:
            index = min(
                len(state["reads"]) - 2,
                len(after_names) - 1,
            )

            name = after_names[
                index
            ]

        return {
            "playlist_id":
                str(playlist_id),
            "owner_id":
                owner_id,
            "name":
                name,
        }

    def catalog_request(
        path,
        *,
        method_name,
        params,
        signature_params,
        require_auth,
        signed,
        **_kwargs,
    ):
        state["requests"].append({
            "path":
                path,
            "method_name":
                method_name,
            "params":
                dict(params),
            "signature_params":
                dict(signature_params),
            "require_auth":
                require_auth,
            "signed":
                signed,
        })

        if provider_payload is not None:
            return provider_payload

        return {
            "id":
                int(response_id),
            "name":
                params["name"],
        }

    backend.get_playlist = (
        get_playlist
    )

    backend._catalog_request = (
        catalog_request
    )

    backend._normalize_qobuz_playlist = (
        lambda payload: {
            "playlist_id":
                str(
                    payload.get(
                        "id",
                        "",
                    )
                ),
            "name":
                str(
                    payload.get(
                        "name",
                        "",
                    )
                ),
        }
    )

    return backend, state


def test_q8f_owned_rename_trims_and_uses_native_update_contract():
    backend, state = make_backend()

    result = backend.rename_playlist(
        77,
        "  Renamed Playlist  ",
    )

    assert result["ok"] is True
    assert result["confirmed"] is True
    assert result["playlist_id"] == "77"
    assert result["name"] == "Renamed Playlist"

    assert state["requests"] == [{
        "path":
            "/playlist/update",
        "method_name":
            "playlistupdate",
        "params": {
            "playlist_id":
                "77",
            "name":
                "Renamed Playlist",
        },
        "signature_params": {
            "playlist_id":
                "77",
            "name":
                "Renamed Playlist",
        },
        "require_auth":
            True,
        "signed":
            True,
    }]

    assert state["reads"] == [
        ("77", 1, 0),
        ("77", 1, 0),
    ]


def test_q8f_native_request_is_rename_only():
    backend, state = make_backend()

    backend.rename_playlist(
        "77",
        "Renamed Playlist",
    )

    params = state[
        "requests"
    ][0]["params"]

    assert set(
        params
    ) == {
        "playlist_id",
        "name",
    }

    assert (
        "description"
        not in params
    )

    assert (
        "is_public"
        not in params
    )


def test_q8f_same_name_is_not_locally_short_circuited():
    backend, state = make_backend(
        before_name="Same Name",
        after_names=[
            "Same Name",
        ],
    )

    result = backend.rename_playlist(
        "77",
        " Same Name ",
    )

    assert result["ok"] is True

    assert len(
        state["requests"]
    ) == 1

    assert state[
        "requests"
    ][0]["params"]["name"] == "Same Name"


def test_q8f_blank_name_fails_before_provider_or_read():
    backend, state = make_backend()

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.rename_playlist(
            "77",
            "   ",
        )

    assert (
        exc.value.code
        == "invalid_request"
    )

    assert state["requests"] == []
    assert state["reads"] == []


def test_q8f_foreign_playlist_fails_closed_before_provider():
    backend, state = make_backend(
        owner_id="999",
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.rename_playlist(
            "77",
            "Not Allowed",
        )

    assert (
        exc.value.code
        == "not_editable"
    )

    assert state["requests"] == []

    assert state["reads"] == [
        ("77", 1, 0),
    ]


def test_q8f_unknown_session_identity_fails_closed():
    backend, state = make_backend(
        current_user_id="",
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.rename_playlist(
            "77",
            "Not Allowed",
        )

    assert (
        exc.value.code
        == "not_authenticated"
    )

    assert state["requests"] == []
    assert state["reads"] == []


def test_q8f_explicit_provider_failure_is_never_success():
    backend, state = make_backend(
        provider_payload={
            "ok": False,
            "error": "rejected",
        },
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.rename_playlist(
            "77",
            "Renamed Playlist",
        )

    assert (
        exc.value.code
        == "provider_error"
    )

    assert len(
        state["requests"]
    ) == 1


def test_q8f_update_response_identity_must_match_target():
    backend, state = make_backend(
        response_id="88",
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.rename_playlist(
            "77",
            "Renamed Playlist",
        )

    assert (
        exc.value.code
        == "malformed_response"
    )

    assert len(
        state["requests"]
    ) == 1


def test_q8f_delayed_provider_readback_can_confirm(
    monkeypatch,
):
    backend, state = make_backend(
        before_name="Original",
        after_names=[
            "Original",
            "Renamed Playlist",
        ],
    )

    sleeps = []

    monkeypatch.setattr(
        qobuz_module.time,
        "sleep",
        lambda seconds:
            sleeps.append(seconds),
    )

    result = backend.rename_playlist(
        "77",
        "Renamed Playlist",
    )

    assert result[
        "confirmed"
    ] is True

    assert sleeps == [
        1.0,
    ]

    assert state["reads"] == [
        ("77", 1, 0),
        ("77", 1, 0),
        ("77", 1, 0),
    ]


def test_q8f_stale_provider_readback_never_false_succeeds(
    monkeypatch,
):
    backend, state = make_backend(
        before_name="Original",
        after_names=[
            "Original",
            "Original",
            "Original",
        ],
    )

    sleeps = []

    monkeypatch.setattr(
        qobuz_module.time,
        "sleep",
        lambda seconds:
            sleeps.append(seconds),
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        backend.rename_playlist(
            "77",
            "Renamed Playlist",
        )

    assert (
        exc.value.code
        == "reconcile_timeout"
    )

    assert sleeps == [
        1.0,
        3.0,
    ]

    assert len(
        state["requests"]
    ) == 1

    assert state["reads"] == [
        ("77", 1, 0),
        ("77", 1, 0),
        ("77", 1, 0),
        ("77", 1, 0),
    ]


def q8f_route_source():
    start = MAIN_SOURCE.index(
        'if self.path == "/qobuz/playlist/rename":'
    )

    end = MAIN_SOURCE.index(
        "# -- Playlist: delete one owned Qobuz playlist",
        start,
    )

    return MAIN_SOURCE[
        start:end
    ]


def test_q8f_route_is_qobuz_only_confirmed_only_and_queue_inert():
    route = q8f_route_source()

    assert (
        "backend.rename_playlist("
        in route
    )

    assert (
        '"confirmed"'
        in route
    )

    assert (
        "is not True"
        in route
    )

    assert (
        '"qobuz_backend"'
        in route
    )

    assert (
        "safe_payload"
        in route
    )

    assert (
        '"qobuz_playlist_rename_failed"'
        in route
    )

    assert (
        "PLAY_QUEUE"
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


def test_q8f_route_validates_id_and_name_before_dispatch():
    route = q8f_route_source()

    assert (
        "raw_playlist_id"
        in route
    )

    assert (
        "raw_name"
        in route
    )

    assert (
        "(str, int)"
        in route
    )

    assert (
        '"Qobuz playlist ID is invalid."'
        in route
    )

    assert (
        '"Qobuz playlist name is invalid."'
        in route
    )


def test_q8f_route_has_safe_generic_failure_and_no_store():
    route = q8f_route_source()

    assert (
        "safe_payload"
        in route
    )

    assert (
        '"Qobuz playlist could not be renamed."'
        in route
    )

    assert (
        "no_store=True"
        in route
    )


UI_SOURCE = (
    REPO_ROOT
    / "src"
    / "ui_web"
    / "ui.js"
).read_text(
    encoding="utf-8"
)

INDEX_SOURCE = (
    REPO_ROOT
    / "src"
    / "ui_web"
    / "index.html"
).read_text(
    encoding="utf-8"
)


def js_function(name):
    markers = [
        "function " + name + "(",
        "async function " + name + "(",
    ]

    starts = [
        UI_SOURCE.find(marker)
        for marker in markers
        if UI_SOURCE.find(marker) >= 0
    ]

    assert len(starts) == 1

    start = starts[0]
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
        "function end not found: "
        + name
    )


def test_q8f_ui_posts_only_playlist_id_and_name():
    source = js_function(
        "postRenameQobuzPlaylist"
    )

    assert (
        '"/qobuz/playlist/rename"'
        in source
    )

    assert (
        "playlist_id"
        in source
    )

    assert (
        "name:"
        in source
    )

    assert (
        "description"
        not in source
    )

    assert (
        "is_public"
        not in source
    )


def test_q8f_qobuz_modal_reuses_existing_visual_system_and_rename_behavior():
    source = js_function(
        "showCreateQobuzPlaylistModal"
    )

    assert (
        'mode === "rename"'
        in source
    )

    assert (
        "options.editable !== true"
        in source
    )

    assert (
        '"This Qobuz playlist cannot be renamed"'
        in source
    )

    assert (
        "options.defaultName"
        in source
    )

    assert (
        "options.hideDescription"
        in source
    )

    assert (
        "options.busyLabel"
        in source
    )

    assert (
        "postRenameQobuzPlaylist("
        in source
    )

    assert (
        "data.confirmed !== true"
        in source
    )

    assert (
        "updateQobuzPlaylistNameInUi("
        in source
    )

    assert (
        '"Playlist renamed"'
        in source
    )

    for existing_class in (
        "tidalPlaylistModal",
        "tidalPlaylistCard",
        "tidalPlaylistInput",
        "tidalPlaylistActions",
        "settingsBtn",
    ):
        assert (
            existing_class
            in source
        )


def test_q8f_confirmed_name_updates_qobuz_local_rows_picker_and_detail():
    source = js_function(
        "updateQobuzPlaylistNameInUi"
    )

    assert (
        "qobuzPlaylists.forEach"
        in source
    )

    assert (
        'data-playlist-provider="qobuz"'
        in source
    )

    assert (
        ".playlistName"
        in source
    )

    assert (
        ".tidalPlaylistPickerRow"
        in source
    )

    assert (
        ".tidalPlaylistPickerName"
        in source
    )

    assert (
        'currentContext.source ==='
        in source
    )

    assert (
        '"qobuz"'
        in source
    )

    assert (
        'currentContext.type ==='
        in source
    )

    assert (
        '"playlist"'
        in source
    )

    assert (
        "currentContext.title"
        in source
    )

    assert (
        "albumTitle.textContent"
        in source
    )


def test_q8f_qobuz_picker_rows_have_provider_and_playlist_identity():
    source = js_function(
        "showAddToQobuzPlaylistModal"
    )

    assert (
        '"data-playlist-id"'
        in source
    )

    assert (
        '"data-playlist-provider"'
        in source
    )

    assert (
        '"qobuz"'
        in source
    )


def test_q8f_header_rename_is_provider_aware_and_ownership_gated():
    source = js_function(
        "renderAlbumQueueBtn"
    )

    assert (
        "canRenameTidalPlaylist"
        in source
    )

    assert (
        "canRenameQobuzPlaylist"
        in source
    )

    assert (
        'currentContext.source === "qobuz"'
        in source
    )

    assert (
        'currentContext.type === "playlist"'
        in source
    )

    assert (
        "currentContext.playlist_editable === true"
        in source
    )

    assert (
        "showCreateQobuzPlaylistModal("
        in source
    )

    assert (
        "showCreateTidalPlaylistModal("
        in source
    )

    assert (
        'renameBtn.id = "playlistRenameBtn"'
        in source
    )

    assert (
        'renameBtn.className = "albumQueueBtn"'
        in source
    )


def test_q8f_does_not_add_row_level_rename_control():
    source = js_function(
        "renderPlaylistRows"
    )

    assert (
        "Rename playlist"
        not in source
    )

    assert (
        "postRenameQobuzPlaylist"
        not in source
    )

    assert (
        "showCreateQobuzPlaylistModal"
        not in source
    )


def test_q8f_ui_cache_key_is_bumped_without_css_key_change():
    assert (
        'ui.js?v=20260911_v2_0_q8f_qobuz_rename1'
        in INDEX_SOURCE
    )

    assert (
        'srova.css?v=20260824_v1_4_point9_home_wordmark_inert_css1'
        in INDEX_SOURCE
    )
