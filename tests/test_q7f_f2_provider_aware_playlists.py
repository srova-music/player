from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "src/ui_web/srova.css").read_text(encoding="utf-8")


def js_function(name):
    import re

    match = re.search(
        rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{",
        UI,
    )
    assert match, name

    brace = UI.find("{", match.start())
    depth = 0
    quote = None
    escaped = False

    for index in range(brace, len(UI)):
        char = UI[index]

        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in ("'", '"', "`"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return UI[match.start():index + 1]

    raise AssertionError(name)


def test_f2_provider_rules_are_auth_state_driven():
    source = js_function("showPlaylists")

    assert "refreshStreamingProviderPresentation()" in source
    assert "playlistsProviderAvailability()" in source
    assert "availability.dual" in source
    assert "availability.qobuz" in source
    assert 'openPlaylistsProvider("tidal")' in source


def test_f2_dual_provider_bar_only_exists_for_dual_auth():
    source = js_function("buildPlaylistsProviderBar")

    assert "availability.dual" in source
    assert '["tidal", "TIDAL"]' in source
    assert '["qobuz", "QOBUZ"]' in source
    assert "switchPlaylistsProvider(provider)" in source


def test_f2_qobuz_playlist_list_uses_existing_q7c_operation():
    source = js_function("loadQobuzPlaylists")

    assert '"/qobuz/catalog?op=playlists"' in source
    assert "adaptQobuzUserPlaylist" in source
    assert "/qobuz/playlist/create" not in source
    assert "/qobuz/playlist/delete" not in source


def test_f2_complete_detail_uses_locked_f1_resolver():
    source = js_function("loadStreamingPlaylistDetail")

    assert '"/api/playlists/complete?provider="' in source
    assert "resp.complete !== true" in source
    assert "currentViewTracks = tracks" in source
    assert 'provider === "tidal"' in source
    assert "loadFavoriteIds()" in source


def test_f2_qobuz_detail_has_provider_identity_and_read_only_endpoint():
    source = js_function("loadStreamingPlaylistDetail")

    assert '"qobuz:playlist:" + playlistId' in source
    assert 'source: provider' in source
    assert 'type: "playlist"' in source
    assert 'playlist_editable: false' in source


def test_f2_playlist_row_delete_rule_is_narrowly_superseded_by_f3b():
    source = js_function("renderPlaylistRows")

    # F2 originally permitted Delete only for TIDAL and kept Qobuz
    # read-only. F3B explicitly supersedes only that destructive-control
    # rule with provider-neutral positive ownership gating.
    assert "item.playlist_editable" in source
    assert 'provider === "tidal"' in source
    assert 'provider === "qobuz"' in source
    assert "showDeleteTidalPlaylistModal" in source
    assert "showDeleteQobuzPlaylistModal" in source
    assert "loadStreamingPlaylistDetail" in source


def test_f2_qobuz_tracks_do_not_expose_tidal_favorite_mutation():
    source = js_function("renderTrackList")

    assert "qobuzReadOnlyPlaylist" in source
    assert "if (!qobuzReadOnlyPlaylist)" in source
    assert "toggleTrackFavorite" in source


def test_f2_qobuz_playlist_playback_stays_on_shared_q5_queue():
    source = js_function("playTrack")

    assert 'currentViewEndpoint.indexOf("qobuz:playlist:") === 0' in source
    assert 'ctxType = "playlist"' in source
    assert "buildTrackPayload(" in source
    assert "postTidalQueueReplace(" in source
    assert "/qobuz/play" not in source
    assert "/qobuz/queue" not in source


def test_f2_qobuz_playlist_loader_stays_read_only():
    source = js_function("loadQobuzPlaylists")

    for endpoint in (
        "/qobuz/playlist/create",
        "/qobuz/playlist/delete",
        "/qobuz/playlist/rename",
        "/qobuz/playlist/add_tracks",
        "/qobuz/playlist/remove_tracks",
    ):
        assert endpoint not in source


def test_f2_provider_buttons_are_centered():
    assert "#playlistsContent > .playlistsProviderBar" in CSS
    assert "align-items: center !important;" in CSS
    assert "justify-content: center !important;" in CSS
    assert "text-align: center !important;" in CSS


# ----------------------------------------------------------------------
# Q7F-F2 parity refinements
# ----------------------------------------------------------------------

def _q7f_f2_ui_source():
    from pathlib import Path
    return (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ui_web"
        / "ui.js"
    ).read_text(encoding="utf-8")


def _q7f_f2_function_source(name):
    import re

    src = _q7f_f2_ui_source()

    match = re.search(
        r"function\s+"
        + re.escape(name)
        + r"\s*\([^)]*\)\s*\{",
        src,
    )

    assert match, name

    brace = src.find("{", match.start())
    depth = 0
    quote = None
    escaped = False

    for index in range(brace, len(src)):
        char = src[index]

        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue

        if char in ("'", '"', "`"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return src[match.start():index + 1]

    raise AssertionError("unterminated " + name)


def test_f2_parity_qobuz_playlist_payload_prefers_track_artwork():
    source = _q7f_f2_function_source(
        "buildTrackPayload"
    )

    assert (
        'currentViewEndpoint.indexOf("qobuz:playlist:") === 0'
        in source
    )

    assert (
        "streamingTrackArtworkUrl("
        in source
    )

    assert (
        "preferTrackCover ? trackCover"
        in source
    )


def test_f2_parity_artwork_helper_supports_qobuz_normalized_shape():
    source = _q7f_f2_function_source(
        "streamingTrackArtworkUrl"
    )

    assert "track.cover" in source
    assert "track.artwork_url" in source
    assert "artworkObject.url" in source


def test_f2_parity_qobuz_playlist_trackmap_uses_track_artwork():
    source = _q7f_f2_function_source(
        "renderTrackList"
    )

    assert "rowTrackCover" in source
    assert "qobuzReadOnlyPlaylist" in source
    assert "? (rowTrackCover || ctxCover)" in source


def test_f2_parity_dual_auth_modal_identifies_tidal_destination():
    source = _q7f_f2_function_source(
        "tidalPlaylistModalPresentationTitle"
    )

    assert "presentation.dual !== true" in source
    assert '"Create TIDAL Playlist"' in source
    assert '"Save as TIDAL Playlist"' in source
    assert '"Save Queue as TIDAL Playlist"' in source


def test_f2_parity_single_provider_modal_keeps_implicit_title():
    source = _q7f_f2_function_source(
        "tidalPlaylistModalPresentationTitle"
    )

    assert (
        "return title;"
        in source
    )

    assert (
        "presentation.dual !== true"
        in source
    )


def test_f2_parity_qobuz_sort_does_not_fabricate_missing_dates():
    adapt = _q7f_f2_function_source(
        "adaptQobuzUserPlaylist"
    )

    render = _q7f_f2_function_source(
        "renderPlaylistsList"
    )

    assert 'last_updated: ""' in adapt
    assert 'created_at: ""' in adapt

    assert (
        'provider === "qobuz"'
        in render
    )

    assert (
        'key: "name"'
        in render
    )

    assert (
        'key: "tracks"'
        in render
    )


def test_f2_parity_tidal_modal_core_remains_provider_write_specific():
    source = _q7f_f2_function_source(
        "showCreateTidalPlaylistModal"
    )

    assert "postCreateTidalPlaylist(" in source
    assert "postCreateTidalPlaylistFromTracks(" in source
    assert "postCreateTidalPlaylistFromQueue(" in source
    assert "postRenameTidalPlaylist(" in source

    assert "/qobuz/" not in source
