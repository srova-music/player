from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = (
    ROOT /
    "src" /
    "ui_web" /
    "ui.js"
).read_text(encoding="utf-8")


def h3_block():
    start = UI.index(
        "Q7H H3 — provider-native Qobuz Radio."
    )
    end = UI.index(
        "var providerRadioVisibilityState = {",
        start,
    )
    return UI[start:end]


def test_qobuz_provider_radio_source01_foundation():
    block = h3_block()

    assert "function ensureQobuzRadioSourceSlot(" in block
    assert "function refreshQobuzRadioSourceSection(" in block
    assert "function renderQobuzRadioSourceSection(" in block
    assert '"QOBUZ RADIO"' in block
    assert 'data-provider-radio="qobuz"' in block


def test_qobuz_radio_uses_authenticated_provider_library_seeds():
    block = h3_block()

    assert "op=library_artists" in block
    assert "op=library_tracks" in block
    assert '"artist"' in block
    assert '"track"' in block


def test_qobuz_radio_uses_native_q7c_operations():
    block = h3_block()

    assert '"radio_artist"' in block
    assert '"radio_track"' in block
    assert '"/qobuz/catalog?op="' in block


def test_qobuz_radio_prefers_artists_and_falls_back_to_tracks():
    block = h3_block()

    artist_pos = block.index(
        "op=library_artists"
    )
    track_pos = block.index(
        "op=library_tracks"
    )

    assert artist_pos < track_pos
    assert '"Artist Radio"' in block
    assert '" · Track Radio"' in block


def test_qobuz_radio_respects_h1_effective_visibility():
    block = h3_block()

    assert (
        'providerRadioEffectiveVisibility(\n'
        '                "qobuz"\n'
        '            )'
    ) in block

    assert (
        "loadProviderRadioVisibilitySettings()"
        in block
    )

    assert (
        "refreshStreamingProviderPresentation()"
        in block
    )


def test_qobuz_radio_keeps_canonical_provider_track_identity():
    block = h3_block()

    assert "track.source ===" in block
    assert '"qobuz"' in block

    assert "track.provider_track_id" in block
    assert '"qobuz:" +' in block
    assert "qobuzAlbumTrackPayload(" in block


def test_qobuz_radio_uses_shared_provider_queue():
    block = h3_block()

    assert "postTidalQueueReplace({" in block
    assert "tracks: payload" in block
    assert "start_index: startIndex" in block
    assert "context_type: contextType" in block


def test_qobuz_radio_context_is_provider_specific_not_custom_radio():
    block = h3_block()

    assert '"qobuz_radio_artist"' in block
    assert '"qobuz_radio_track"' in block
    assert "_setPlaybackSource(" in block
    assert '"qobuz"' in block

    assert 'context_type: "radio"' not in block
    assert 'source: "radio"' not in block


def test_qobuz_radio_never_enters_custom_internet_radio_model():
    block = h3_block()

    forbidden = [
        "/api/radio/play/",
        "radio:station:",
        "playRadioStation(",
        "enhanceRadioShelfOrdering(",
        "RADIO_MODE",
        "set_live_radio_mode",
    ]

    for token in forbidden:
        assert token not in block


def test_qobuz_provider_shelf_is_outside_custom_station_adapter():
    custom_start = UI.index(
        "function radioStationItems("
    )

    custom_end = UI.index(
        "function buildRadioSourceShellFromStations(",
        custom_start,
    )

    custom = UI[
        custom_start:
        custom_end
    ]

    # This slice contains only the custom My Radio station adapter
    # and its reorder-enabled shelf builder. Provider SOURCE 01
    # sibling slots are created after this boundary.
    assert "qobuz" not in custom.lower()
    assert "enhanceRadioShelfOrdering(" in custom


def test_qobuz_provider_refresh_hooks_are_optional_for_legacy_harnesses():
    token = (
        'typeof refreshQobuzRadioSourceSection '
        '=== "function"'
    )

    assert UI.count(token) == 3


def test_qobuz_provider_slot_is_built_as_sibling_of_tidal():
    build_start = UI.index(
        "function buildRadioSourceShellFromStations("
    )

    build_end = UI.index(
        "function buildRadioShelf(",
        build_start,
    )

    build = UI[
        build_start:
        build_end
    ]

    assert "ensureTidalRadioSourceSlot(shell);" in build
    assert "ensureQobuzRadioSourceSlot(shell);" in build

    assert (
        build.index(
            "ensureTidalRadioSourceSlot(shell);"
        )
        <
        build.index(
            "ensureQobuzRadioSourceSlot(shell);"
        )
    )


def test_qobuz_cards_are_not_custom_radio_cards():
    block = h3_block()

    assert (
        "adaptQobuzWallItem(\n"
        "                    raw,\n"
        "                    seedKind"
    ) in block

    assert 'adapted.sub_title =\n                    "Artist Radio"' in block

    # buildScrollSection receives adapted Artist/Track items;
    # no item is retyped as the custom "radio" card type.
    assert 'adapted.type = "radio"' not in block
    assert 'type: "radio"' not in block


def test_h2_tidal_provider_radio_remains_present():
    assert "function ensureTidalRadioSourceSlot(" in UI
    assert "function refreshTidalRadioSourceSection(" in UI
    assert '"TIDAL RADIO"' in UI
    assert '"personal radio stations"' in UI


def function_block(name):
    start = UI.index(
        "function " + name + "("
    )

    next_function = UI.find(
        "\nfunction ",
        start + 1,
    )

    if next_function < 0:
        next_function = len(UI)

    return UI[
        start:
        next_function
    ]


def test_qobuz_radio_card_opens_detail_without_autoplay():
    start = function_block(
        "startQobuzRadioFromSeed"
    )

    assert 'previousView =\n        "radio"' in start
    assert '"qobuz:radio:" +' in start
    assert 'showView(\n        "album"\n    )' in start
    assert "Loading Qobuz Radio" in start

    # Opening the SOURCE 01 card must not replace the queue.
    assert "postTidalQueueReplace(" not in start
    assert "playQobuzRadioTracks(" not in start


def test_qobuz_radio_detail_has_finite_provider_track_renderer():
    block = function_block(
        "renderQobuzRadioTracks"
    )

    assert "row.className =" in block
    assert '"track trackWide"' in block
    assert ': "track"' in block
    assert '"track-duration"' in block
    assert "formatTime(" in block
    assert "trackAddBtn" in block
    assert "showQueuePopover(" in block


def test_qobuz_radio_detail_row_starts_provider_queue():
    renderer = function_block(
        "renderQobuzRadioTracks"
    )

    player = function_block(
        "playQobuzRadioTracks"
    )

    assert "playQobuzRadioTracks(" in renderer
    assert "postTidalQueueReplace({" in player
    assert "tracks: payload" in player
    assert "start_index: startIndex" in player
    assert "context_type: contextType" in player
    assert '_setPlaybackSource(\n        "qobuz"' in player


def test_qobuz_radio_detail_preserves_provider_contexts():
    player = function_block(
        "playQobuzRadioTracks"
    )

    detail = function_block(
        "showQobuzRadioDetail"
    )

    assert '"qobuz_radio_artist"' in player
    assert '"qobuz_radio_artist"' in detail
    assert '"qobuz_radio_track"' in detail
    assert 'source:\n            "qobuz"' in detail


def test_qobuz_radio_detail_back_target_is_source01_radio():
    start = function_block(
        "startQobuzRadioFromSeed"
    )

    assert 'previousView =\n        "radio"' in start

    go_back_start = UI.index(
        "function goBack("
    )

    go_back_end = UI.index(
        "function ",
        go_back_start + len(
            "function goBack("
        ),
    )

    go_back = UI[
        go_back_start:
        go_back_end
    ]

    assert 'previousView === "radio"' in go_back
    assert "showRadioSource(false, true)" in go_back


def test_qobuz_radio_detail_does_not_inherit_custom_live_radio():
    names = [
        "playQobuzRadioTracks",
        "renderQobuzRadioTracks",
        "showQobuzRadioDetail",
        "startQobuzRadioFromSeed",
    ]

    block = "\n".join(
        function_block(name)
        for name in names
    )

    for forbidden in (
        "/api/radio/play/",
        "radio:station:",
        'source: "radio"',
        'context_type: "radio"',
        "RADIO_MODE",
        "playRadioStation(",
        "set_live_radio_mode",
    ):
        assert forbidden not in block


def test_qobuz_radio_detail_uses_established_wide_track_grid():
    renderer = function_block(
        "renderQobuzRadioTracks"
    )

    assert "hasArtist" in renderer
    assert '"trackListWide"' in renderer
    assert '"track trackWide"' in renderer
    assert '"track-artist"' in renderer
    assert '"track-duration"' in renderer


def test_qobuz_radio_detail_matches_tidal_mix_compact_header():
    detail = function_block(
        "showQobuzRadioDetail"
    )

    assert (
        'artist:\n'
        '            ""'
    ) in detail

    assert (
        'albumStatsLine.textContent =\n'
        '        ""'
    ) in detail

    assert (
        'albumStatsLine.className =\n'
        '        "hidden"'
    ) in detail

    assert "streamingAlbumStatsText(" not in detail


def test_qobuz_radio_detail_uses_bounded_15_second_cold_enrichment_window():
    """
    Qobuz /radio/* omits artist metadata. H3 enriches missing artists from
    authoritative track detail, so a cold 30-track Radio response may exceed
    the generic 8-second catalog UI window. Keep this detail route bounded at
    15 seconds without changing other Qobuz catalog request timeouts.
    """
    start = UI.index(
        "function startQobuzRadioFromSeed("
    )
    end = UI.index(
        "\nfunction qobuzRadioSeedCards(",
        start,
    )

    block = UI[start:end]

    assert (
        'fetchWithTimeout(\n'
        '        requestUrl,\n'
        '        {\n'
        '            cache: "no-store"\n'
        '        },\n'
        '        15000\n'
        '    )'
        in block
    )

    assert (
        '        8000\n'
        '    )'
        not in block
    )
