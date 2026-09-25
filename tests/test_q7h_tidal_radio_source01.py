from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

UI = (
    ROOT /
    "src/ui_web/ui.js"
).read_text(
    encoding="utf-8"
)

BACKEND = (
    ROOT /
    "src/main_headless.py"
).read_text(
    encoding="utf-8"
)

TIDAL_BACKEND = (
    ROOT /
    "src/backend/tidal.py"
).read_text(
    encoding="utf-8"
)


def _slice(text, start, end):
    left = text.index(start)
    right = text.index(
        end,
        left,
    )
    return text[left:right]


def test_h2_selects_exact_native_tidal_personal_radio_section():
    code = _slice(
        UI,
        "function tidalPersonalRadioSection(homeData)",
        "function tidalPersonalRadioItems(homeData)",
    )

    assert (
        '"personal radio stations"'
        in code
    )

    assert (
        "Custom mixes"
        not in code
    )


def test_h2_accepts_only_native_tidal_mix_items():
    code = _slice(
        UI,
        "function tidalPersonalRadioItems(homeData)",
        "function renderTidalRadioSourceSection(",
    )

    assert (
        'item.type || ""'
        in code
    )

    assert (
        '"mix"'
        in code
    )

    assert (
        "item.id"
        in code
    )


def test_h2_source01_label_is_tidal_radio():
    code = _slice(
        UI,
        "function renderTidalRadioSourceSection(",
        "function refreshTidalRadioSourceSection(shell)",
    )

    assert (
        '"TIDAL RADIO"'
        in code
    )

    assert (
        "buildScrollSection("
        in code
    )


def test_h2_reuses_existing_tidal_mix_navigation():
    code = _slice(
        UI,
        "function renderTidalRadioSourceSection(",
        "function refreshTidalRadioSourceSection(shell)",
    )

    assert (
        "handleTidalWallItemClick("
        in code
    )

    assert (
        'item,\n'
        '                    "radio",'
        in code
    )

    generic = _slice(
        UI,
        "function handleItemClick(item, fromView)",
        "function handleTidalWallItemClick(",
    )

    assert (
        'type === "mix"'
        in generic
    )

    assert (
        '"/tidal/mix/"'
        in generic
    )


def test_h2_provider_section_respects_h1_effective_visibility():
    code = _slice(
        UI,
        "function refreshTidalRadioSourceSection(shell)",
        "var providerRadioVisibilityState = {",
    )

    assert (
        'providerRadioEffectiveVisibility(\n'
        '                "tidal"'
        in code
    )

    assert (
        "loadProviderRadioVisibilitySettings()"
        in code
    )

    assert (
        "refreshStreamingProviderPresentation()"
        in code
    )

    assert (
        '"/tidal/home"'
        in code
    )


def test_h2_provider_slot_is_outside_custom_station_array():
    custom = _slice(
        UI,
        "function radioStationItems(stations)",
        "function buildRadioShelfFromStations(stations)",
    )

    assert (
        "providerRadio"
        not in custom
    )

    signature = _slice(
        UI,
        "function radioStationSignature(stations)",
        "function supersedeRadioSourcePreparation()",
    )

    assert (
        "providerRadio"
        not in signature
    )

    assert (
        "tidal"
        not in signature.lower()
    )


def test_h2_provider_section_has_no_custom_reorder_path():
    h2 = _slice(
        UI,
        "function ensureTidalRadioSourceSlot(shell)",
        "var providerRadioVisibilityState = {",
    )

    forbidden = (
        "enhanceRadioShelfOrdering",
        "radioDragHandle",
        "/api/radio/stations/order",
        "persistRadioStationOrder",
    )

    for token in forbidden:
        assert token not in h2


def test_h2_provider_section_has_no_custom_live_radio_playback():
    h2 = _slice(
        UI,
        "function ensureTidalRadioSourceSlot(shell)",
        "var providerRadioVisibilityState = {",
    )

    forbidden = (
        "/api/radio/play/",
        "buildRadioStationPayload",
        "playRadioStation(",
        "radio:station:",
        "RADIO_MODE",
        "radio_mode:",
        'source: "radio"',
        'context_type: "radio"',
    )

    for token in forbidden:
        assert token not in h2


def test_h2_mix_detail_returns_to_source01_radio():
    expected = (
        '    } else if (previousView === "radio") {\n'
        '        showRadioSource(false, true);\n'
        '    } else if (previousView === "playlists") {'
    )

    assert expected in UI


def test_h2_cached_radio_wall_refreshes_provider_section_independently():
    show_radio = _slice(
        UI,
        "function showRadioSource(",
        "function tidalSourceSearchHasResults(",
    )

    assert (
        "refreshTidalRadioSourceSection("
        in show_radio
    )

    custom_signature = _slice(
        UI,
        "function radioStationSignature(stations)",
        "function supersedeRadioSourcePreparation()",
    )

    assert (
        "TIDAL RADIO"
        not in custom_signature
    )


def test_h2_native_mix_keeps_normal_finite_tidal_track_contract():
    assert (
        'if self.path.startswith("/tidal/mix/"):'
        in BACKEND
    )

    mix_handler = _slice(
        BACKEND,
        'if self.path.startswith("/tidal/mix/"):',
        "# -- Queue: read state",
    )

    assert (
        'CURRENT_CONTEXT["context_type"]  = "mix"'
        in mix_handler
    )

    assert (
        "_build_track_list("
        in mix_handler
    )

    builder = _slice(
        BACKEND,
        "def _build_track_list(",
        "_STREAMING_PLAYLIST_MAX_TRACKS",
    )

    assert (
        '"duration":'
        in builder
    )

    assert (
        '"quality":'
        in builder
    )


def test_h2_tidal_mix_remains_provider_queue_identity_not_custom_radio():
    source = _slice(
        BACKEND,
        "def _queue_item_source(",
        "def _active_queue_auto_advance_snapshot()",
    )

    assert (
        'if ":" not in track_id:\n'
        '        return "tidal"'
        in source
    )

    assert (
        'track_id.startswith("radio:station:")'
        in source
    )

    # H2 itself never manufactures a radio:station identity.
    h2 = _slice(
        UI,
        "function ensureTidalRadioSourceSlot(shell)",
        "var providerRadioVisibilityState = {",
    )

    assert (
        "radio:station:"
        not in h2
    )


def test_h2_does_not_require_new_tidal_backend_radio_model():
    # Existing TIDAL provider semantics are Home + native Mix.
    assert (
        "def get_home_page(self):"
        in TIDAL_BACKEND
    )

    assert (
        "self.session.mix(item_id)"
        in TIDAL_BACKEND
    )

    assert (
        "def get_radio_artist("
        not in TIDAL_BACKEND
    )

    assert (
        "def get_radio_track("
        not in TIDAL_BACKEND
    )

    assert (
        "def get_radio_album("
        not in TIDAL_BACKEND
    )


def test_h2_custom_my_radio_reorder_remains_present_and_separate():
    assert (
        "function enhanceRadioShelfOrdering(block, items)"
        in UI
    )

    assert (
        'fetch("/api/radio/stations/order"'
        in UI
    )

    assert (
        'handle.className = "radioDragHandle"'
        in UI
    )

    custom = _slice(
        UI,
        "function buildRadioShelfFromStations(stations)",
        "function buildRadioSourceShellFromStations(stations)",
    )

    assert (
        "enhanceRadioShelfOrdering(block, items);"
        in custom
    )

    assert (
        "TIDAL RADIO"
        not in custom
    )
