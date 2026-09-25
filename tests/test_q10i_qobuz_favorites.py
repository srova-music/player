from pathlib import Path
import os
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(
    0,
    str(ROOT / "src"),
)

from backend.qobuz import QobuzBackend
from backend.qobuz_catalog import (
    QobuzCatalogError,
)


MAIN = (
    ROOT /
    "src/main_headless.py"
).read_text(
    encoding="utf-8",
)


def backend(tmp_path):
    return QobuzBackend(
        config_dir=str(
            tmp_path / "config"
        ),
        cache_dir=str(
            tmp_path / "cache"
        ),
    )


def test_q10i_favorite_ids_use_lightweight_native_endpoint(
    tmp_path,
):
    qobuz = backend(
        tmp_path
    )

    calls = []

    def request(
        path,
        **kwargs,
    ):
        calls.append(
            (path, kwargs)
        )

        assert (
            path
            == "/favorite/getUserFavoriteIds"
        )

        return {
            "tracks": [
                123,
                "456",
                123,
            ],
            "albums": [
                "0634904032432",
                "album-opaque-id",
                "0634904032432",
            ],
            "artists": [
                77,
                "88",
                77,
            ],
        }

    qobuz._catalog_request = (
        request
    )

    result = (
        qobuz.get_favorite_ids()
    )

    assert result == {
        "ok": True,
        "track_ids": [
            "123",
            "456",
        ],
        "album_ids": [
            "0634904032432",
            "album-opaque-id",
        ],
        "artist_ids": [
            "77",
            "88",
        ],
    }

    assert len(calls) == 1

    _, kwargs = calls[0]

    assert (
        kwargs[
            "method_name"
        ]
        == "favoritegetUserFavoriteIds"
    )

    assert (
        kwargs["require_auth"]
        is True
    )

    assert (
        kwargs["signed"]
        is False
    )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "tracks": [],
            "albums": [],
        },
        {
            "tracks": "not-list",
            "albums": [],
            "artists": [],
        },
        {
            "tracks": [
                "qobuz:123"
            ],
            "albums": [],
            "artists": [],
        },
        {
            "tracks": [],
            "albums": [],
            "artists": [
                "artist-x"
            ],
        },
    ],
)
def test_q10i_favorite_ids_reject_malformed_provider_state(
    tmp_path,
    payload,
):
    qobuz = backend(
        tmp_path
    )

    qobuz._catalog_request = (
        lambda *_args, **_kwargs:
        payload
    )

    with pytest.raises(
        QobuzCatalogError
    ):
        qobuz.get_favorite_ids()


@pytest.mark.parametrize(
    "favorite_type,item_id",
    [
        (
            "track",
            "qobuz:123",
        ),
        (
            "track",
            "0",
        ),
        (
            "artist",
            "artist-x",
        ),
        (
            "album",
            "",
        ),
        (
            "playlist",
            "123",
        ),
    ],
)
def test_q10i_rejects_non_native_or_unsupported_identity(
    tmp_path,
    favorite_type,
    item_id,
):
    qobuz = backend(
        tmp_path
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        qobuz.get_favorite_status(
            favorite_type,
            item_id,
        )

    assert (
        exc.value.code
        == "invalid_request"
    )


def test_q10i_status_uses_provider_native_unsigned_read(
    tmp_path,
):
    qobuz = backend(
        tmp_path
    )

    calls = []

    def request(
        path,
        **kwargs,
    ):
        calls.append(
            (path, kwargs)
        )

        return {
            "status": True,
        }

    qobuz._catalog_request = (
        request
    )

    result = (
        qobuz.get_favorite_status(
            "track",
            "123",
        )
    )

    assert result == {
        "ok": True,
        "type": "track",
        "id": "123",
        "is_favorite": True,
    }

    path, kwargs = calls[0]

    assert (
        path
        == "/favorite/status"
    )

    assert kwargs["params"] == {
        "type": "track",
        "item_id": "123",
    }

    assert (
        kwargs["require_auth"]
        is True
    )

    assert (
        kwargs["signed"]
        is False
    )


def test_q10i_set_favorite_is_idempotent_when_state_already_matches(
    tmp_path,
):
    qobuz = backend(
        tmp_path
    )

    calls = []

    def request(
        path,
        **kwargs,
    ):
        calls.append(
            (path, kwargs)
        )

        assert (
            path
            == "/favorite/status"
        )

        return {
            "status": True,
        }

    qobuz._catalog_request = (
        request
    )

    result = (
        qobuz.set_favorite(
            "album",
            "0634904032432",
            True,
        )
    )

    assert result[
        "is_favorite"
    ] is True

    assert result[
        "changed"
    ] is False

    assert result[
        "provider_request_sent"
    ] is False

    assert len(calls) == 1


def test_q10i_add_track_uses_signed_native_create_and_readback(
    tmp_path,
):
    qobuz = backend(
        tmp_path
    )

    calls = []
    statuses = iter(
        (
            False,
            True,
        )
    )

    def request(
        path,
        **kwargs,
    ):
        calls.append(
            (path, kwargs)
        )

        if (
            path
            == "/favorite/status"
        ):
            return {
                "status":
                    next(statuses),
            }

        if (
            path
            == "/favorite/create"
        ):
            return {
                "status": "success",
            }

        raise AssertionError(
            path
        )

    qobuz._catalog_request = (
        request
    )

    result = (
        qobuz.set_favorite(
            "track",
            "123",
            True,
        )
    )

    assert result[
        "is_favorite"
    ] is True

    assert result[
        "changed"
    ] is True

    assert result[
        "confirmed"
    ] is True

    assert result[
        "provider_request_sent"
    ] is True

    assert [
        call[0]
        for call in calls
    ] == [
        "/favorite/status",
        "/favorite/create",
        "/favorite/status",
    ]

    mutation = calls[1][1]

    assert mutation[
        "method_name"
    ] == "favoritecreate"

    assert mutation[
        "params"
    ] == {
        "track_ids": "123",
    }

    assert mutation[
        "signature_params"
    ] == {
        "track_ids": "123",
    }

    assert mutation[
        "require_auth"
    ] is True


def test_q10i_remove_album_preserves_opaque_native_id(
    tmp_path,
):
    qobuz = backend(
        tmp_path
    )

    statuses = iter(
        (
            True,
            False,
        )
    )

    calls = []

    def request(
        path,
        **kwargs,
    ):
        calls.append(
            (path, kwargs)
        )

        if (
            path
            == "/favorite/status"
        ):
            return {
                "status":
                    next(statuses),
            }

        if (
            path
            == "/favorite/delete"
        ):
            return {
                "status": "success",
            }

        raise AssertionError(
            path
        )

    qobuz._catalog_request = (
        request
    )

    result = (
        qobuz.set_favorite(
            "album",
            "album-opaque-id",
            False,
        )
    )

    assert result[
        "is_favorite"
    ] is False

    mutation = calls[1][1]

    assert mutation[
        "params"
    ] == {
        "album_ids":
            "album-opaque-id",
    }


def test_q10i_successful_unreadable_mutation_body_can_be_reconciled(
    tmp_path,
):
    qobuz = backend(
        tmp_path
    )

    statuses = iter(
        (
            False,
            True,
        )
    )

    def request(
        path,
        **kwargs,
    ):
        if (
            path
            == "/favorite/status"
        ):
            return {
                "status":
                    next(statuses),
            }

        if (
            path
            == "/favorite/create"
        ):
            raise QobuzCatalogError(
                "malformed_response",
                (
                    "Qobuz returned "
                    "an invalid response."
                ),
                http_status=200,
            )

        raise AssertionError(
            path
        )

    qobuz._catalog_request = (
        request
    )

    result = (
        qobuz.set_favorite(
            "artist",
            "77",
            True,
        )
    )

    assert result[
        "confirmed"
    ] is True

    assert result[
        "mutation_response_unreadable"
    ] is True


def test_q10i_reconcile_mismatch_fails_safely(
    tmp_path,
):
    qobuz = backend(
        tmp_path
    )

    statuses = iter(
        (
            False,
            False,
        )
    )

    def request(
        path,
        **kwargs,
    ):
        if (
            path
            == "/favorite/status"
        ):
            return {
                "status":
                    next(statuses),
            }

        if (
            path
            == "/favorite/create"
        ):
            return {
                "status": "success",
            }

        raise AssertionError(
            path
        )

    qobuz._catalog_request = (
        request
    )

    with pytest.raises(
        QobuzCatalogError
    ) as exc:
        qobuz.set_favorite(
            "track",
            "123",
            True,
        )

    assert (
        exc.value.code
        == "reconcile_timeout"
    )

    assert (
        exc.value.transient
        is True
    )


def test_q10i_http_surface_is_provider_explicit_and_set_state_based():
    assert (
        'static_path == "/qobuz/favorites/ids"'
        in MAIN
    )

    assert (
        'self.path == "/qobuz/favorite/set"'
        in MAIN
    )

    assert (
        "backend.get_favorite_ids()"
        in MAIN
    )

    assert (
        "backend.set_favorite("
        in MAIN
    )

    assert (
        "is_favorite = payload.get("
        in MAIN
    )

    assert (
        '"is_favorite"'
        in MAIN
    )


def test_q10i_does_not_repurpose_tidal_favorite_routes():
    for route in (
        "/tidal/favorites/ids",
        "/tidal/favorite/track/",
        "/tidal/favorite/album/",
        "/tidal/favorite/artist/",
    ):
        assert route in MAIN


# ==================================================================
# Q10I-B PROVIDER-AWARE HEART / FAVORITES UI
# ==================================================================

Q10I_UI_PATH = (
    ROOT /
    "src/ui_web/ui.js"
)

Q10I_UI = (
    Q10I_UI_PATH.read_text(
        encoding="utf-8"
    )
)


def q10i_js_function(name):
    marker = f"function {name}("
    start = Q10I_UI.index(marker)

    end = Q10I_UI.find(
        "\nfunction ",
        start + len(marker),
    )

    if end < 0:
        end = len(Q10I_UI)

    return Q10I_UI[
        start:end
    ]


def test_q10i_ui_keeps_provider_favorite_maps_separate():
    for token in (
        "var favTrackIds",
        "var favAlbumIds",
        "var favArtistIds",
        "var qobuzFavTrackIds",
        "var qobuzFavAlbumIds",
        "var qobuzFavArtistIds",
    ):
        assert token in Q10I_UI

    native = q10i_js_function(
        "qobuzFavoriteNativeId"
    )

    assert '"qobuz:"' in native
    assert '"qobuz:album:"' in native
    assert '"qobuz:artist:"' in native


def test_q10i_ui_loads_native_qobuz_id_sets_not_per_track_status():
    source = q10i_js_function(
        "loadQobuzFavoriteIds"
    )

    assert (
        '"/qobuz/favorites/ids?_="'
        in source
    )

    assert "data.track_ids" in source
    assert "data.album_ids" in source
    assert "data.artist_ids" in source

    # State painting is one ID-set load, not a per-track asynchronous
    # status request that could race rapid Next/Previous.
    assert "/favorite/status" not in source


def test_q10i_ui_qobuz_mutation_is_explicit_set_state():
    source = q10i_js_function(
        "setQobuzFavoriteState"
    )

    assert (
        '"/qobuz/favorite/set"'
        in source
    )

    assert (
        "is_favorite:"
        in source
    )

    assert (
        "qobuzFavoriteMutationSerial"
        in source
    )

    assert (
        "previousState"
        in source
    )

    assert (
        "updateQobuzFavoriteElements("
        in source
    )


def test_q10i_ui_now_playing_dispatches_by_committed_provider():
    update = q10i_js_function(
        "updateNpHeart"
    )

    toggle = q10i_js_function(
        "toggleNpHeart"
    )

    provider = q10i_js_function(
        "qobuzNowPlayingFavoriteActive"
    )

    assert (
        "playerBarActivePlaybackSource"
        in provider
    )

    assert (
        "inferStatusPlaybackSource("
        in provider
    )

    assert (
        "qobuzNowPlayingFavoriteActive()"
        in update
    )

    assert (
        "qobuzFavTrackIds"
        in update
    )

    assert (
        "qobuzNowPlayingFavoriteActive()"
        in toggle
    )

    assert (
        "toggleQobuzFavorite("
        in toggle
    )

    # Historical TIDAL dispatch remains present.
    assert (
        "toggleTrackFavorite("
        in toggle
    )


def test_q10i_ui_shared_detail_supports_qobuz_playlist_and_track_hearts():
    source = q10i_js_function(
        "renderTrackList"
    )

    assert (
        "qobuzReadOnlyPlaylist"
        in source
    )

    assert (
        "qobuzReadOnlyTrack"
        in source
    )

    assert (
        source.count(
            "appendQobuzTrackFavoriteHeart("
        )
        >= 2
    )

    # TIDAL row mutation remains intact.
    assert (
        "toggleTrackFavorite("
        in source
    )


def test_q10i_ui_qobuz_album_has_header_and_track_hearts():
    rows = q10i_js_function(
        "renderQobuzAlbumTracks"
    )

    actions = q10i_js_function(
        "renderQobuzAlbumActions"
    )

    assert (
        "appendQobuzTrackFavoriteHeart("
        in rows
    )

    assert (
        "makeQobuzFavoriteHeart("
        in actions
    )

    assert (
        '"album"'
        in actions
    )

    assert (
        '"albumHeaderHeart"'
        in actions
    )


def test_q10i_ui_qobuz_artist_has_header_and_top_track_hearts():
    rows = q10i_js_function(
        "_buildArtistTrackRow"
    )

    header = q10i_js_function(
        "renderAlbumQueueBtn"
    )

    assert (
        "if (qobuzTrack)"
        in rows
    )

    assert (
        "appendQobuzTrackFavoriteHeart("
        in rows
    )

    assert (
        '"qobuz:artist:"'
        in header
    )

    assert (
        'heartProvider = "qobuz"'
        in header
    )

    # Historical TIDAL header mutation remains present.
    assert (
        "toggleArtistFavorite("
        in header
    )


def test_q10i_ui_qobuz_radio_tracks_have_normal_finite_track_hearts():
    source = q10i_js_function(
        "renderQobuzRadioTracks"
    )

    assert (
        "appendQobuzTrackFavoriteHeart("
        in source
    )

    assert (
        "showQueuePopover("
        in source
    )


def test_q10i_ui_qobuz_provider_search_tracks_have_provider_heart():
    source = q10i_js_function(
        "renderQobuzSourceSearchTrackRow"
    )

    assert (
        "appendQobuzSearchTrackFavoriteHeart("
        in source
    )

    assert (
        "qobuzSourceSearchTrackMenu("
        in source
    )

    assert (
        "toggleTrackFavorite("
        not in source
    )


def test_q10i_ui_qobuz_auth_loads_and_logout_clears_favorite_state():
    refresh = q10i_js_function(
        "refreshStreamingProviderPresentation"
    )

    assert (
        "loadQobuzFavoriteIds("
        in refresh
    )

    assert (
        "clearQobuzFavoriteIds()"
        in refresh
    )

    assert (
        Q10I_UI.count(
            "clearQobuzFavoriteIds();"
        )
        >= 3
    )


def test_q10i_ui_status_repaint_is_synchronous_map_lookup():
    source = q10i_js_function(
        "pollStatus"
    )

    assert (
        "updateNpHeart();"
        in source
    )

    assert (
        'fetch("/qobuz/favorite'
        not in source
    )


def test_q10i_tidal_mutation_functions_remain_provider_local():
    for name, route in (
        (
            "toggleTrackFavorite",
            "/tidal/favorite/track/",
        ),
        (
            "toggleAlbumFavorite",
            "/tidal/favorite/album/",
        ),
        (
            "toggleArtistFavorite",
            "/tidal/favorite/artist/",
        ),
    ):
        source = q10i_js_function(
            name
        )

        assert route in source
        assert "/qobuz/" not in source


def test_q10i_advances_only_the_ui_js_cache_delivery_token():
    index = (
        ROOT /
        "src/ui_web/index.html"
    ).read_text(
        encoding="utf-8"
    )

    old_token = (
        "20260912_v2_0_q10a_infinite_play_pause_logo_js4_"
        "q10b_20260913_v2_0_q10b_qobuz_transition_js1_"
        "v1_4_point5_compat_q10b_readiness_js2_"
        "q10b_pending_presentation_js3_"
        "q10b_atomic_presentation_js4_"
        "q10b_infinite_visibility_latch_js5_"
        "q10b_infinite_commit_order_js6_"
        "q10a_provider_aware_pause_js7_"
        "q10c_playlist_maintenance_provider_js8_"
        "q10d_manual_browser_auth_js9_"
        "q10d_auth_ux_js10_"
        "q10e_qobuz_lyrics_js11_"
        "q10f_provider_aware_go_to_album_js12"
    )

    new_token = (
        old_token
        + "_q10i_20260915_qobuz_favorites_js13_q10i_search_favorites_js14_q10i_empty_artist_header_heart_js15"
    )

    old_ref = (
        '<script src="/ui_web/ui.js?v='
        + old_token
        + '"></script>'
    )

    new_ref = (
        '<script src="/ui_web/ui.js?v='
        + new_token
        + '"></script>'
    )

    assert index.count(
        "/ui_web/ui.js?v="
    ) == 1

    assert old_ref not in index
    assert (
        '<script src="/ui_web/ui.js?v='
        + new_token
    ) in index

    # Q10I needs no CSS presentation change.
    assert index.count(
        "/ui_web/srova.css?v="
    ) == 1



def test_q10i_favorite_hearts_are_persistent_touch_controls():
    css = (
        ROOT /
        "src/ui_web/srova.css"
    ).read_text(
        encoding="utf-8"
    )

    marker = (
        "Q10I FAVORITE HEARTS ALWAYS VISIBLE -- 150926"
    )

    start = css.index(marker)
    block = css[start:]

    for selector in (
        ".trackHeart",
        ".artistTopTracksSection .trackHeart",
        "#albumView .artistTopTracksSection.artworkViewList .trackHeart",
        ".srovaSearchHeart",
        "#albumHeaderHeart",
        "#npBtnHeart",
    ):
        assert selector in block

    assert "opacity: 1 !important;" in block
    assert "visibility: visible !important;" in block

    # Historical hover styling may remain for colour only.
    assert ".trackHeart:hover" in css

    # The radio-specific semantic exclusion remains intact.
    assert "body.radioMode #npBtnHeart" in css
    assert "display: none !important;" in css


def test_q10i_advances_css_cache_for_persistent_hearts():
    index = (
        ROOT /
        "src/ui_web/index.html"
    ).read_text(
        encoding="utf-8"
    )

    old_token = (
        "20260914_v2_0_q10d_auth_ux_css2_"
        "q10f_provider_aware_go_to_album_css3_"
        "q10h_mobile_back_arrow_css1"
    )

    new_token = (
        old_token
        + "_q10i_20260915_favorites_always_visible_css2_q10i_artist_top_track_heart_layout_css3_q10i_hover_parity_css4"
    )

    assert index.count(
        "/ui_web/srova.css?v="
    ) == 1

    assert (
        "/ui_web/srova.css?v="
        + new_token
    ) in index




def test_q10i_artist_top_track_heart_is_off_artwork():
    css = (
        ROOT /
        "src/ui_web/srova.css"
    ).read_text(
        encoding="utf-8"
    )

    marker = (
        "Q10I ARTIST TOP TRACK HEART "
        "METADATA PLACEMENT -- 150926"
    )
    end_marker = (
        "Q10I POINTER PARITY AND ARTIST ACTION CLEANUP "
        "-- 150926"
    )

    start = css.index(marker)
    end = css.index(end_marker, start)
    block = css[start:end]

    assert (
        "#albumView .artistTopTracksSection:not(.artworkViewList) "
        "> .track"
        in block
    )

    assert (
        "minmax(0, 1fr) 30px !important;"
        in block
    )

    assert (
        "#albumView .artistTopTracksSection:not(.artworkViewList) "
        ".track-duration"
        in block
    )

    assert (
        "#albumView .artistTopTracksSection:not(.artworkViewList) "
        ".trackHeart"
        in block
    )

    assert (
        ".artistTopTracksSection.artworkViewList .trackHeart"
        not in block
    )

    assert "grid-column: 2 !important;" in block
    assert "grid-row: 4 !important;" in block
    assert "position: static !important;" in block
    assert "top: auto !important;" in block
    assert "right: auto !important;" in block
    assert "opacity: 1 !important;" in block
    assert "visibility: visible !important;" in block

def test_q10i_artist_heart_layout_advances_css_cache_token():
    index = (
        ROOT /
        "src/ui_web/index.html"
    ).read_text(
        encoding="utf-8"
    )

    expected = (
        "/ui_web/srova.css?v="
        "20260914_v2_0_q10d_auth_ux_css2_"
        "q10f_provider_aware_go_to_album_css3_"
        "q10h_mobile_back_arrow_css1_"
        "q10i_20260915_favorites_always_visible_css2_"
        "q10i_artist_top_track_heart_layout_css3_q10i_hover_parity_css4"
    )

    assert index.count(
        "/ui_web/srova.css?v="
    ) == 1

    assert expected in index

def test_q10i_pointer_parity_and_artist_rank_cleanup_source_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    css = (
        root / "src" / "ui_web" / "srova.css"
    ).read_text(encoding="utf-8")

    index = (
        root / "src" / "ui_web" / "index.html"
    ).read_text(encoding="utf-8")

    assert (
        "Q10I POINTER PARITY AND ARTIST ACTION CLEANUP "
        "-- 150926"
    ) in css

    assert ".track:hover .trackHeart" not in css
    assert ".track:hover .trackAddBtn" not in css
    assert ".track:hover .trackRemoveBtn" not in css

    assert (
        ".artistTopTracksSection > .track:hover "
        ".trackHeart"
    ) not in css

    assert (
        ".artistTopTracksSection > .track:hover "
        ".trackAddBtn"
    ) not in css

    assert (
        ".searchSection > .searchArtist:hover "
        ".searchArrow"
    ) not in css

    assert ".rowWrapper:hover .rowArrow" not in css

    assert (
        ".searchSection > .searchArtist .searchArrow"
    ) in css

    assert ".rowWrapper .rowArrow" in css

    assert (
        ".artistTopTracksSection:not(.artworkViewList)"
    ) in css

    assert "display: none !important;" in css

    # Decorative hover feedback remains valid.
    assert ".trackHeart:hover" in css
    assert ".trackAddBtn:hover" in css

    expected_token = (
        "20260914_v2_0_q10d_auth_ux_css2_"
        "q10f_provider_aware_go_to_album_css3_"
        "q10h_mobile_back_arrow_css1_"
        "q10i_20260915_favorites_always_visible_css2_"
        "q10i_artist_top_track_heart_layout_css3_"
        "q10i_hover_parity_css4"
    )

    assert (
        "/ui_web/srova.css?v=" + expected_token
    ) in index



def test_q10i_artist_top_track_add_moves_off_artwork():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    css = (
        root / "src" / "ui_web" / "srova.css"
    ).read_text(encoding="utf-8")

    index = (
        root / "src" / "ui_web" / "index.html"
    ).read_text(encoding="utf-8")

    marker = (
        "Q10I ARTIST TOP TRACK ADD FOOTER PLACEMENT -- 150926"
    )

    assert marker in css

    block = css.split(marker, 1)[1]

    assert (
        "#albumView .artistTopTracksSection:not(.artworkViewList) "
        ".trackAddBtn"
        in block
    )

    assert (
        ".artistTopTracksSection.artworkViewList .trackAddBtn"
        not in block
    )

    assert "position: static !important;" in block
    assert "grid-column: 3 !important;" in block
    assert "grid-row: 4 !important;" in block
    assert "background: transparent !important;" in block
    assert "border-color: transparent !important;" in block
    assert "box-shadow: none !important;" in block
    assert "opacity: 1 !important;" in block
    assert "visibility: visible !important;" in block

    # Radio reorder remains outside this persistent-artwork pass.
    assert ".radioDragHandle" not in block

    expected_href = (
        'href="/ui_web/srova.css?'
        'v=20260914_v2_0_q10d_auth_ux_css2_'
        'q10f_provider_aware_go_to_album_css3_'
        'q10h_mobile_back_arrow_css1_'
        'q10i_20260915_favorites_always_visible_css2_'
        'q10i_artist_top_track_heart_layout_css3_'
        'q10i_hover_parity_css4_'
        'q10i_artist_add_footer_css5_'
        'q10i_artist_list_isolation_css6_q10i_search_favorites_css7_q10i_search_favorite_gold_css8_q10i_search_layout_parity_css9_q10i_short_detail_scroll_css10"'
    )

    assert expected_href in index



def test_q10i_artist_top_track_list_mode_geometry_isolated():
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1]

    css = (
        root / "src" / "ui_web" / "srova.css"
    ).read_text(encoding="utf-8")

    heart_marker = (
        "Q10I ARTIST TOP TRACK HEART METADATA PLACEMENT -- 150926"
    )
    pointer_marker = (
        "Q10I POINTER PARITY AND ARTIST ACTION CLEANUP -- 150926"
    )
    add_marker = (
        "Q10I ARTIST TOP TRACK ADD FOOTER PLACEMENT -- 150926"
    )

    heart_start = css.index(heart_marker)
    pointer_start = css.index(pointer_marker, heart_start)
    add_start = css.index(add_marker, pointer_start)

    legacy = css[:heart_start]
    heart_block = css[heart_start:pointer_start]
    add_block = css[add_start:]

    # Q10I artwork/card geometry must not target list mode.
    assert (
        ".artistTopTracksSection.artworkViewList .trackHeart"
        not in heart_block
    )
    assert (
        ".artistTopTracksSection.artworkViewList .trackAddBtn"
        not in add_block
    )

    # Established desktop list-mode action columns remain authoritative.
    assert re.search(
        r"#albumView "
        r"\.artistTopTracksSection\.artworkViewList "
        r"\.trackHeart\s*\{\s*"
        r"grid-column:\s*5\s*!important;",
        legacy,
        re.S,
    )

    assert re.search(
        r"#albumView "
        r"\.artistTopTracksSection\.artworkViewList "
        r"\.trackAddBtn\s*\{\s*"
        r"grid-column:\s*6\s*!important;",
        legacy,
        re.S,
    )

    # Established mobile list-mode action columns remain present.
    assert re.search(
        r"@media \(max-width:\s*640px\).*?"
        r"\.artistTopTracksSection\.artworkViewList "
        r"\.trackHeart\s*\{.*?"
        r"grid-column:\s*3\s*!important;.*?"
        r"\.artistTopTracksSection\.artworkViewList "
        r"\.trackAddBtn\s*\{.*?"
        r"grid-column:\s*4\s*!important;",
        legacy,
        re.S,
    )

    # Pointer/touch parity remains intentional in every mode.
    assert (
        ".artistTopTracksSection .trackHeart,"
        in css
    )
    assert (
        ".artistTopTracksSection .trackAddBtn"
        in css
    )
    assert "opacity: 1 !important;" in css
    assert "visibility: visible !important;" in css

def test_q10i_provider_search_favorites_cover_all_native_entity_types():
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1]

    ui = (
        root / "src" / "ui_web" / "ui.js"
    ).read_text(encoding="utf-8")

    css = (
        root / "src" / "ui_web" / "srova.css"
    ).read_text(encoding="utf-8")

    index = (
        root / "src" / "ui_web" / "index.html"
    ).read_text(encoding="utf-8")

    def fn(name):
        pattern = re.compile(
            rf"(?ms)^function {re.escape(name)}\s*\(.*?"
            rf"(?=^function |\Z)"
        )
        match = pattern.search(ui)
        assert match, name
        return match.group(0)

    assert "function appendTidalSearchFavoriteHeart(" in ui
    assert "function appendQobuzSearchEntityFavoriteHeart(" in ui

    q_top = fn("renderQobuzSourceSearchTopRow")
    q_tracks = fn("renderQobuzSourceSearchTrackRow")
    q_albums = fn("renderQobuzSourceSearchAlbumCard")
    q_artists = fn("renderQobuzSourceSearchArtistCard")

    assert "appendQobuzSearchTrackFavoriteHeart(" in q_top
    assert "appendQobuzSearchEntityFavoriteHeart(" in q_top
    assert 'kind === "album"' in q_top
    assert 'kind === "artist"' in q_top

    assert "appendQobuzSearchTrackFavoriteHeart(" in q_tracks
    assert "appendQobuzSearchEntityFavoriteHeart(" in q_albums
    assert '"album"' in q_albums
    assert "appendQobuzSearchEntityFavoriteHeart(" in q_artists
    assert '"artist"' in q_artists

    t_top = fn("renderSrovaSearchTopRow")
    t_tracks = fn("renderSrovaSearchTrackRow")
    t_albums = fn("renderSrovaSearchAlbumCard")
    t_artists = fn("renderSrovaSearchArtistCard")

    assert "appendTidalSearchFavoriteHeart(" in t_top
    assert 'item.source === "tidal"' in t_top
    assert 'item.type === "track"' in t_top
    assert 'item.type === "album"' in t_top
    assert 'item.type === "artist"' in t_top

    assert "appendTidalSearchFavoriteHeart(" in t_tracks
    assert 'track.source === "tidal"' in t_tracks
    assert "heartBtn.disabled" not in t_tracks

    assert "appendTidalSearchFavoriteHeart(" in t_albums
    assert 'album.source === "tidal"' in t_albums
    assert '"album"' in t_albums

    assert "appendTidalSearchFavoriteHeart(" in t_artists
    assert 'artist.source === "tidal"' in t_artists
    assert '"artist"' in t_artists

    q_playlist = fn("renderQobuzSourceSearchPlaylistCard")
    assert "FavoriteHeart" not in q_playlist

    update = fn("updateHeartStates")
    assert '[data-heart-provider="tidal"]' in update
    assert "tidalSearchFavoriteMap(" in update

    assert ".srovaSearchTopActions" in css
    assert ".srovaSearchCardActions" in css
    assert "max-content !important;" in css

    assert (
        "q10i_20260915_qobuz_favorites_js13_"
        "q10i_search_favorites_js14"
    ) in index

    assert (
        "q10i_artist_list_isolation_css6_"
        "q10i_search_favorites_css7_q10i_search_favorite_gold_css8_q10i_search_layout_parity_css9"
    ) in index

def test_q10i_search_filled_favorite_uses_srova_gold():
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1]

    css = (
        root / "src" / "ui_web" / "srova.css"
    ).read_text(encoding="utf-8")

    index = (
        root / "src" / "ui_web" / "index.html"
    ).read_text(encoding="utf-8")

    match = re.search(
        r"\.srovaSearchHeart\.faved\s*\{([^}]*)\}",
        css,
        re.S,
    )

    assert match
    body = match.group(1)

    assert "color: var(--srova-gold) !important;" in body
    assert "#d75c5c" not in body

    assert (
        "q10i_search_favorites_css7_"
        "q10i_search_favorite_gold_css8_q10i_search_layout_parity_css9"
    ) in index

def test_q10i_search_provider_presentation_geometry_parity():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    css = (
        root / "src" / "ui_web" / "srova.css"
    ).read_text(encoding="utf-8")

    index = (
        root / "src" / "ui_web" / "index.html"
    ).read_text(encoding="utf-8")

    qobuz_desktop = """.qobuzSourceSearchTrackHead,
.qobuzSourceSearchTrackRow {
    grid-template-columns:
        38px
        46px
        minmax(160px, 1.5fr)
        minmax(120px, 1fr)
        minmax(120px, 1fr)
        58px
        36px
        36px
        !important;
}
"""

    qobuz_mobile = """    .qobuzSourceSearchTrackRow {
        grid-template-columns:
            30px
            42px
            minmax(0, 1fr)
            34px
            34px
            !important;
    }
"""

    assert css.count(qobuz_desktop) == 1
    assert css.count(qobuz_mobile) == 1

    assert (
        "grid-template-columns: "
        "62px minmax(0, 1fr) 34px !important;"
    ) in css

    actions = """.srovaSearchAlbumGrid.artworkViewList
.srovaSearchCardActions {
    grid-column: 3 !important;
    grid-row: 1 / 3 !important;
    align-self: center !important;
    justify-self: end !important;
    margin: 0 !important;
    min-height: 30px !important;
}
"""

    assert css.count(actions) == 1

    assert (
        "Q10I SEARCH PROVIDER PRESENTATION PARITY -- 150926"
    ) in css

    assert (
        "q10i_search_favorite_gold_css8_"
        "q10i_search_layout_parity_css9"
    ) in index

def test_q10i_tidal_search_track_serializer_preserves_album_name():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    main = (
        root / "src" / "main_headless.py"
    ).read_text(encoding="utf-8")

    serializer = '''                for t in results.get("tracks", []):
                    artist_name = ""
                    try:
                        artist_name = _safe_str(t.artist.name if t.artist else "")
                    except Exception:
                        pass

                    album_name = ""
                    try:
                        album_obj = getattr(t, "album", None)
                        album_name = _safe_str(
                            getattr(album_obj, "name", "")
                            if album_obj else ""
                        )
                    except Exception:
                        pass

                    out["tracks"].append({
                        "id":        getattr(t, "id",       None),
                        "name":      _safe_str(getattr(t, "name", "")),
                        "duration":  getattr(t, "duration", 0),
                        "artist":    artist_name,
                        "album":     album_name,
                        "image_url": _safe_artwork(backend, t, 320)
                    })
'''

    assert main.count(serializer) == 1


def test_q10i_empty_artist_keeps_provider_favorite_header_action():
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1]

    ui = (
        root / "src" / "ui_web" / "ui.js"
    ).read_text(encoding="utf-8")

    start = ui.index(
        "function renderAlbumQueueBtn("
    )

    match = re.search(
        r"\nfunction\s+[A-Za-z0-9_$]+\s*\(",
        ui[start + 1:],
    )

    assert match

    end = (
        start +
        1 +
        match.start()
    )

    body = ui[start:end]

    assert "var canRenderHeaderFavorite =" in body
    assert '"/tidal/album/"' in body
    assert '"/tidal/artist/"' in body
    assert '"qobuz:artist:"' in body
    assert "!canRenderHeaderFavorite" in body

    assert (
        "tracks.length === 0 && !canRenamePlaylist"
        not in body
    )

    assert "makeQobuzFavoriteHeart(" in body
    assert '"albumHeaderHeart"' in body


def test_q10i_short_detail_page_does_not_force_viewport_plus_header_scroll():
    """
    Q10I physical acceptance found that #albumView's historical 100vh
    minimum creates one header-height of phantom document overflow on
    short provider detail pages.  The final cascade must allow natural
    content height without removing the existing Player Bar clearance.
    """
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1]
    css = (root / "src/ui_web/srova.css").read_text()
    index = (root / "src/ui_web/index.html").read_text()

    marker = (
        "Q10I SHORT DETAIL PAGE PHANTOM-SCROLL "
        "CORRECTION -- 160926"
    )

    assert css.count(marker) == 1

    tail = css.split(marker, 1)[1]

    assert re.search(
        r"#albumView\s*\{[^}]*"
        r"min-height\s*:\s*0\s*!important\s*;",
        tail,
        re.S,
    )

    # Preserve the established Player Bar/detail-page clearance rather
    # than "fixing" the issue by deleting bottom reserve spacing.
    assert "padding-bottom: 160px !important;" in css

    token = (
        "20260914_v2_0_q10d_auth_ux_css2_"
        "q10f_provider_aware_go_to_album_css3_"
        "q10h_mobile_back_arrow_css1_"
        "q10i_20260915_favorites_always_visible_css2_"
        "q10i_artist_top_track_heart_layout_css3_"
        "q10i_hover_parity_css4_"
        "q10i_artist_add_footer_css5_"
        "q10i_artist_list_isolation_css6_"
        "q10i_search_favorites_css7_"
        "q10i_search_favorite_gold_css8_"
        "q10i_search_layout_parity_css9_"
        "q10i_short_detail_scroll_css10"
    )

    assert index.count("/ui_web/srova.css?v=" + token) == 1


def test_q10i_same_numeric_id_is_provider_namespaced_end_to_end():
    """
    TIDAL and Qobuz may legitimately expose the same numeric native ID.
    Favorite presentation must therefore select a provider namespace
    before looking up that numeric value.
    """

    # Independent provider-owned stores are the primary namespace
    # boundary.  A value such as "12345" can exist in both without
    # sharing state.
    for token in (
        "var favTrackIds  = {};",
        "var favAlbumIds  = {};",
        "var favArtistIds = {};",
        "var qobuzFavTrackIds  = {};",
        "var qobuzFavAlbumIds  = {};",
        "var qobuzFavArtistIds = {};",
    ):
        assert token in Q10I_UI

    qobuz_map = q10i_js_function(
        "qobuzFavoriteMap"
    )

    assert (
        "return qobuzFavTrackIds;"
        in qobuz_map
    )
    assert (
        "return qobuzFavAlbumIds;"
        in qobuz_map
    )
    assert (
        "return qobuzFavArtistIds;"
        in qobuz_map
    )

    # The Now Playing path must make its provider decision before
    # consulting either same-shaped numeric-ID map.
    np_source = q10i_js_function(
        "updateNpHeart"
    )

    provider_pos = np_source.index(
        "qobuzNowPlayingFavoriteActive()"
    )
    qobuz_map_pos = np_source.index(
        "qobuzFavTrackIds"
    )
    qobuz_return_pos = np_source.index(
        "return;",
        qobuz_map_pos,
    )
    tidal_map_pos = np_source.index(
        "favTrackIds",
        qobuz_return_pos,
    )

    assert (
        provider_pos <
        qobuz_map_pos <
        qobuz_return_pos <
        tidal_map_pos
    )

    # Header Favorite state is likewise provider-tagged before
    # selecting Qobuz or historical TIDAL storage.
    header_source = q10i_js_function(
        "updateHeaderHeart"
    )

    assert (
        '"data-heart-provider"'
        in header_source
    )
    assert '"qobuz"' in header_source
    assert (
        "qobuzFavoriteState("
        in header_source
    )
    assert "favAlbumIds" in header_source
    assert "favArtistIds" in header_source

    # Shared row/search repainting also has an explicit provider
    # namespace rather than relying on the numeric ID alone.
    state_source = q10i_js_function(
        "updateHeartStates"
    )

    assert (
        '[data-heart-provider="tidal"]'
        in state_source
    )
    assert (
        '[data-heart-provider="qobuz"]'
        in state_source
    )
    assert (
        "qobuzFavoriteState("
        in state_source
    )
    assert (
        "!!favTrackIds[tid]"
        in state_source
    )

    qobuz_heart = q10i_js_function(
        "makeQobuzFavoriteHeart"
    )

    assert (
        '"data-heart-provider"'
        in qobuz_heart
    )
    assert '"qobuz"' in qobuz_heart

    print(
        "Q10I_SAME_NUMERIC_ID_PROVIDER_NAMESPACE=PASS"
    )


def test_q10i_qobuz_playlist_favorite_does_not_confer_editability():
    """
    A Qobuz playlist row may expose a native track Favorite Heart
    regardless of playlist ownership. Favorite state must never make
    Rename/Remove playlist controls available.
    """

    render = q10i_js_function(
        "renderTrackList"
    )

    favorite = q10i_js_function(
        "setQobuzFavoriteState"
    )

    header = q10i_js_function(
        "renderAlbumQueueBtn"
    )

    # Playlist identity and ownership are established independently
    # of Favorite state.
    assert (
        'currentViewEndpoint.indexOf("qobuz:playlist:")'
        in render
    )

    assert (
        'currentContext.source === "qobuz"'
        in render
    )

    assert (
        "var canRemoveFromQobuzPlaylist"
        in render
    )

    assert (
        "currentContext.playlist_editable === true"
        in render
    )

    # Every Qobuz playlist row may still receive a native track Heart.
    assert (
        "var qobuzReadOnlyPlaylist"
        in render
    )

    assert (
        "appendQobuzTrackFavoriteHeart("
        in render
    )

    # The Remove control exists only behind the independent ownership
    # gate calculated above. Heart state is not part of that condition.
    remove_gate = render.index(
        "if (canRemoveFromPlaylist)"
    )

    heart_path = render.index(
        "appendQobuzTrackFavoriteHeart("
    )

    assert heart_path < remove_gate

    remove_section = render[
        remove_gate:
    ]

    assert (
        "showRemoveFromQobuzPlaylistModal("
        in remove_section
    )

    # Favorite mutation has no path into playlist ownership/edit APIs.
    assert (
        '"/qobuz/favorite/set"'
        in favorite
    )

    for forbidden in (
        "playlist_editable",
        "remove_tracks",
        "rename",
        "showRemoveFromQobuzPlaylistModal",
        "postRemoveTracksFromQobuzPlaylist",
    ):
        assert forbidden not in favorite

    # Header Rename is also independently gated by playlist_editable.
    assert (
        "var canRenameQobuzPlaylist"
        in header
    )

    assert (
        'currentContext.source === "qobuz"'
        in header
    )

    assert (
        'currentContext.type === "playlist"'
        in header
    )

    assert (
        "currentContext.playlist_editable === true"
        in header
    )

    # Playlist/mix detail intentionally never gets a header Favorite;
    # Q10I adds only per-track Favorites there.
    assert (
        "Header Heart -- provider-aware album/artist Favorites only."
        in header
    )

    print(
        "Q10I_QOBUZ_PLAYLIST_FAVORITE_OWNERSHIP_ISOLATION=PASS"
    )
