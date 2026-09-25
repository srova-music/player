from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]

UI_PATH = ROOT / "src/ui_web/ui.js"
CSS_PATH = ROOT / "src/ui_web/srova.css"
INDEX_PATH = ROOT / "src/ui_web/index.html"

UI = UI_PATH.read_text(encoding="utf-8")
CSS = CSS_PATH.read_text(encoding="utf-8")
INDEX = INDEX_PATH.read_text(encoding="utf-8")


def fn(name):
    pattern = re.compile(
        r"(?m)^function\s+" +
        re.escape(name) +
        r"\s*\("
    )

    match = pattern.search(UI)
    assert match, name

    start = match.start()
    brace = UI.find("{", match.end())
    assert brace >= 0, name

    depth = 0
    quote = None
    escaped = False

    for i in range(brace, len(UI)):
        c = UI[i]

        if quote:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == quote:
                quote = None
            continue

        if c in ('"', "'", "`"):
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1

            if depth == 0:
                return UI[start:i + 1]

    raise AssertionError(name)


def node(source):
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, (
        result.stderr or result.stdout
    )


def test_g1_only_requested_qobuz_library_titles_are_clickable():
    source = fn("renderQobuzWallSection")

    assert 'spec.key === "my-albums"' in source
    assert 'spec.key === "my-tracks"' in source

    assert "showQobuzMyAlbums" in source
    assert "showQobuzMyTracks" in source

    assert 'spec.key === "my-artists"' not in source

    assert '"pointer"' in source
    assert '"See all"' in source


def test_g1_qobuz_full_reads_stay_on_q7c_and_are_hard_bounded():
    source = fn("fetchAllQobuzLibraryItems")

    assert "qobuzCatalogUrl(" in source
    assert "QOBUZ_WALL_PAGE_LIMIT" in source
    assert "QOBUZ_LIBRARY_FULL_MAX_PAGES" in source
    assert "pageCount" in source
    assert "expectedTotal" in source

    for forbidden in (
        "qobuz.com/api",
        "play.qobuz.com/api",
        "/tidal/",
        "/qobuz/play",
        "/qobuz/queue",
    ):
        assert forbidden not in source


def test_g1_quality_data_mapping_matches_qobuz_source_wall_logic():
    source = fn("qobuzLibraryQualityDataValue")

    node(
        """
const assert = require("assert");
"""
        + source +
        """
assert.strictEqual(
    qobuzLibraryQualityDataValue({quality: "HI-RES"}),
    "hires"
);
assert.strictEqual(
    qobuzLibraryQualityDataValue({quality: "HIRES"}),
    "hires"
);
assert.strictEqual(
    qobuzLibraryQualityDataValue({quality: "CD"}),
    "cd"
);
assert.strictEqual(
    qobuzLibraryQualityDataValue({quality: "LOSSLESS"}),
    "cd"
);
assert.strictEqual(
    qobuzLibraryQualityDataValue({quality: ""}),
    ""
);
assert.strictEqual(
    qobuzLibraryQualityDataValue({quality: "UNKNOWN"}),
    ""
);
"""
    )


def test_g1_qobuz_album_wall_sets_quality_and_uses_q7e_detail():
    renderer = fn("renderQobuzSavedAlbumsGrid")
    view = fn("showQobuzMyAlbums")

    assert "qobuzLibraryGrid" in renderer
    assert 'setAttribute(' in renderer
    assert '"data-q"' in renderer
    assert "qobuzLibraryQualityDataValue(" in renderer

    assert "loadQobuzAlbumDetail(" in renderer
    assert '"home"' in renderer

    assert 'setCurrentStreamingProvider(' in view
    assert '"qobuz"' in view
    assert 'setCurrentSourceSection(' in view
    assert '"streaming"' in view

    assert 'qobuzLibrarySpecByKey(' in view
    assert '"my-albums"' in view
    assert 'adaptQobuzWallItem(' in view
    assert '"album"' in view


def test_g1_qobuz_track_wall_sets_quality_and_uses_locked_menu():
    renderer = fn("renderQobuzSavedTracksList")
    view = fn("showQobuzMyTracks")

    assert "qobuzSavedTracksList" in renderer
    assert '"data-q"' in renderer
    assert "qobuzLibraryQualityDataValue(" in renderer
    assert "showQobuzTrackArtworkMenu(" in renderer

    assert '"My Tracks"' in view
    assert 'qobuzLibrarySpecByKey(' in view
    assert '"my-tracks"' in view
    assert 'adaptQobuzWallItem(' in view
    assert '"track"' in view

    for forbidden in (
        "handleItemClick(",
        "playTrackDirect(",
        "showAddToTidalPlaylistModal",
        "/tidal/",
    ):
        assert forbidden not in renderer


def test_g1_existing_tidal_album_function_is_not_providerized():
    source = fn("showMyAlbums")

    assert '"/tidal/myalbums"' in source
    assert "handleItemClick(" in source
    assert '"myalbums"' in source

    assert "showQobuz" not in source
    assert "/qobuz/" not in source
    assert "provider" not in source


def test_g1_existing_tidal_song_renderer_is_not_providerized():
    source = fn("renderSongsList")

    assert "handleItemClick(" in source
    assert '"mysongs"' in source

    assert "showQobuz" not in source
    assert "onRowClick" not in source


def test_g1_tidal_my_songs_only_restores_shared_title():
    source = fn("showMySongs")

    assert '"My Songs"' in source
    assert '"/tidal/mysongs"' in source
    assert "renderSongsList(" in source

    assert "showQobuz" not in source
    assert "/qobuz/" not in source


def test_g1_quality_css_is_qobuz_full_wall_scoped():
    marker = (
        "Q7G-G1 QOBUZ FULL LIBRARY QUALITY PARITY"
    )

    assert marker in CSS

    assert ".qobuzLibraryGrid" in CSS
    assert ".qobuzSavedTracksList" in CSS

    assert '[data-q="cd"]' in CSS
    assert '[data-q="hires"]' in CSS

    assert "rgba(0, 191, 255, 0.74)" in CSS
    assert "rgba(0, 191, 255, 0.58)" in CSS

    assert "rgba(201, 168, 76, 0.84)" in CSS
    assert "rgba(201, 168, 76, 0.64)" in CSS


def test_g1_unknown_quality_has_no_fabricated_colour():
    source = fn("qobuzLibraryQualityDataValue")

    assert 'return "";' in source

    # No generic Qobuz full-wall rule may colour rows/cards without
    # an authoritative data-q classification.
    assert (
        ".qobuzLibraryGrid .libraryCard {"
        not in CSS
    )

    assert (
        ".qobuzSavedTracksList .librarySongRow {"
        not in CSS
    )


def test_g1_existing_static_views_and_back_controls_are_unchanged():
    assert (
        '<div class="libraryViewTitle">My Albums</div>'
        in INDEX
    )

    assert (
        '<div class="libraryViewTitle">My Songs</div>'
        in INDEX
    )

    assert INDEX.count(
        'onclick="showView(\'home\')"'
    ) >= 2


def test_g1_does_not_begin_provider_search_or_later_scope():
    contract = (
        fn("showQobuzMyAlbums") +
        fn("showQobuzMyTracks") +
        fn("renderQobuzSavedAlbumsGrid") +
        fn("renderQobuzSavedTracksList") +
        fn("fetchAllQobuzLibraryItems")
    )

    for forbidden in (
        "search_catalog",
        "searchQobuz",
        "globalSearchTidalReady",
        "globalSearchLocalReady",
        "radio_track",
        "radio_album",
        "radio_artist",
        "Infinite Play",
        "Auto Mix",
        "Cast",
    ):
        assert forbidden not in contract


def test_g1_ui_parses():
    result = subprocess.run(
        ["node", "--check", str(UI_PATH)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr


def test_g2_qobuz_provider_search_uses_only_normalized_q7c_gateway():
    source = fn("runQobuzSourceSearch")

    assert '"/qobuz/catalog?"' in source
    assert '"op=search_catalog"' in source
    assert '"&offset=0"' in source
    assert "QOBUZ_SOURCE_SEARCH_LIMIT" in source
    assert "encodeURIComponent(query)" in source

    for forbidden in (
        "/tidal/search",
        "qobuz.com/api",
        "play.qobuz.com/api",
        "globalSearchTidalReady",
        "globalSearchLocalReady",
    ):
        assert forbidden not in source


def test_g2_qobuz_search_explicitly_rejects_empty_query():
    source = fn("runQobuzSourceSearch")

    assert "String(" in source
    assert ".trim()" in source
    assert "if (!query)" in source
    assert "clearQobuzSourceSearchAndLanding(" in source


def test_g2_qobuz_search_has_independent_persistence_keys():
    persist = fn("persistQobuzSourceSearchState")
    clear = fn("clearQobuzSourceSearchState")

    assert "srovaQobuzSourceSearchQuery" in persist
    assert "srovaQobuzSourceSearchPayload" in persist

    assert "srovaQobuzSourceSearchQuery" in clear
    assert "srovaQobuzSourceSearchPayload" in clear

    for source in (persist, clear):
        assert "srovaTidalSourceSearch" not in source


def test_g2_qobuz_search_validates_all_four_normalized_pages():
    source = fn("qobuzSourceSearchPayloadIsValid")

    for category in (
        "tracks",
        "albums",
        "artists",
        "playlists",
    ):
        assert category in source

    assert "Array.isArray(page.items)" in source
    assert "data.ok !== true" in source


def test_g2_qobuz_search_exposes_all_required_tabs():
    source = fn("renderQobuzSourceSearchFoundationResults")

    for label in (
        '"Top Results"',
        '"Tracks"',
        '"Albums"',
        '"Artists"',
        '"Playlists"',
    ):
        assert label in source

    assert "srovaSearchTab" in source


def test_g2_foundation_handoff_to_g3_stays_provider_local():
    results = fn(
        "renderQobuzSourceSearchFoundationResults"
    )
    panel = fn(
        "renderQobuzSourceSearchFoundationPanel"
    )

    assert "renderQobuzSourceSearchTopPanel(" in panel
    assert "renderQobuzSourceSearchTracksPanel(" in panel
    assert "renderQobuzSourceSearchAlbumsPanel(" in panel
    assert "renderQobuzSourceSearchArtistsPanel(" in panel
    assert "renderQobuzSourceSearchPlaylistsPanel(" in panel

    contract = results + panel

    assert "/tidal/" not in contract
    assert "showTidalSearchTrackMenu(" not in contract
    assert "postTidalQueueReplace(" not in contract

def test_g2_qobuz_search_has_safe_error_and_retry_state():
    source = fn("renderQobuzSourceSearchError")

    assert '"error"' in source
    assert "qobuzSourceSearchRetry" in source
    assert '"Retry"' in source
    assert "runQobuzSourceSearch(" in source

    # The renderer receives only caller-controlled safe copy.
    assert "data.message" not in source
    assert "data.error" not in source


def test_g2_qobuz_search_has_idle_typing_loading_results_states():
    attach = fn("attachQobuzSourceSearch")
    run = fn("runQobuzSourceSearch")
    render = fn("renderQobuzSourceSearchFoundationResults")
    clear = fn("clearQobuzSourceSearchAndLanding")

    assert '"typing"' in attach
    assert '"loading"' in run
    assert '"results"' in render
    assert '"no-results"' in render
    assert '"idle"' in clear


def test_g2_qobuz_search_supports_escape_enter_and_debounce():
    source = fn("attachQobuzSourceSearch")

    assert 'e.key === "Escape"' in source
    assert 'e.key === "Enter"' in source
    assert "setTimeout(" in source
    assert "300" in source


def test_g2_qobuz_source_attaches_search_without_global_search():
    source = fn("showQobuzSource")

    assert "opts = opts || {}" in source
    assert "restoreSourceSearch" in source
    assert "attachQobuzSourceSearch(" in source

    assert "globalSearchTidalReady" not in source
    assert "globalSearchLocalReady" not in source


def test_g2_provider_selector_keeps_q7d_callbacks_and_restores_qobuz_on_switch():
    selector = fn(
        "buildStreamingProviderSelector"
    )

    qobuz = fn(
        "showQobuzSource"
    )

    # Locked Q7D markup/callback contract remains exact.
    assert (
        '"showQobuzSource()"'
        in selector
    )

    assert (
        '"showTidalSource()"'
        in selector
    )

    assert (
        "showQobuzSource({restoreSearch:true})"
        not in selector
    )

    # G2 restoration is derived internally from an actual
    # TIDAL -> Qobuz SOURCE 03 provider switch.
    assert (
        "switchingFromTidalSource"
        in qobuz
    )

    assert (
        'currentSourceSection === "streaming"'
        in qobuz
    )

    assert (
        'currentStreamingProvider === "tidal"'
        in qobuz
    )

    assert (
        "#homeSections .srovaTidalSourcePage"
        in qobuz
    )

    assert (
        "!!opts.restoreSearch ||"
        in qobuz
    )


def test_g2_online_state_controls_qobuz_input():
    source = fn("applyOnlineSourceAvailability")

    assert "qobuzSourceSearchInput" in source
    assert "qobuzInput.disabled" in source
    assert '"Search Qobuz..."' in source


def test_g2_qobuz_search_css_mirrors_sticky_tidal_geometry():
    assert (
        "Q7G-G2 QOBUZ PROVIDER-LOCAL SEARCH FOUNDATION"
        in CSS
    )

    required = (
        "#qobuzSourceSearchBox",
        "#qobuzSourceSearchInput",
        "#qobuzSourceSearchStatus",
        "#qobuzSourceSearchWrap",
        "#qobuzSourceSearchResults",
        ".qobuzSourceSearchRetry",
    )

    for token in required:
        assert token in CSS

    for value in (
        "top: 198px !important;",
        "top: 180px !important;",
        "top: 162px !important;",
        "top: 156px !important;",
        "top: 174px !important;",
        "top: 190px !important;",
    ):
        assert value in CSS


def test_g2_new_retry_control_is_physically_centered():
    pattern = re.compile(
        r"\.qobuzSourceSearchRetry\s*\{([^}]*)\}",
        flags=re.S,
    )

    match = pattern.search(CSS)
    assert match

    block = match.group(1)

    assert "display: inline-flex" in block
    assert "align-items: center" in block
    assert "justify-content: center" in block
    assert "text-align: center" in block


def test_g2_existing_generic_search_tabs_are_physically_centered():
    pattern = re.compile(
        r"\.srovaSearchTab\s*\{([^}]*)\}",
        flags=re.S,
    )

    match = pattern.search(CSS)
    assert match

    block = match.group(1)

    assert "display: inline-flex" in block
    assert "align-items: center" in block
    assert "justify-content: center" in block


def test_g2_display_count_never_presents_larger_provider_total_as_exact():
    page_fn = fn(
        "qobuzSourceSearchPage"
    )

    total_fn = fn(
        "qobuzSourceSearchCategoryTotal"
    )

    display_fn = fn(
        "qobuzSourceSearchDisplayCount"
    )

    node(
        """
const assert = require("assert");
"""
        + page_fn
        + "\n"
        + total_fn
        + "\n"
        + display_fn
        + """
const thirty = Array.from(
    {length: 30},
    (_, i) => ({id: i + 1})
);

assert.strictEqual(
    qobuzSourceSearchDisplayCount(
        {
            tracks: {
                items: thirty,
                offset: 0,
                limit: 30,
                total: 1000
            }
        },
        "tracks"
    ),
    "30+"
);

assert.strictEqual(
    qobuzSourceSearchDisplayCount(
        {
            artists: {
                items: Array.from(
                    {length: 27},
                    (_, i) => ({id: i + 1})
                ),
                offset: 0,
                limit: 30,
                total: 27
            }
        },
        "artists"
    ),
    "27"
);

assert.strictEqual(
    qobuzSourceSearchDisplayCount(
        {
            playlists: {
                items: [],
                offset: 0,
                limit: 30,
                total: 0
            }
        },
        "playlists"
    ),
    "0"
);
"""
    )


def test_g2p_all_three_source_search_boxes_have_clear_controls():
    assert 'id="localMusicSearchClear"' in UI
    assert 'id="tidalSourceSearchClear"' in UI
    assert 'id="qobuzSourceSearchClear"' in UI

    assert UI.count(
        'class="srovaInlineSearchClear hidden"'
    ) >= 3


def test_g2p_clear_controls_use_existing_provider_reset_contracts():
    local_shell = fn(
        "renderLocalMusicShell"
    )
    tidal_attach = fn(
        "attachTidalSourceSearch"
    )
    qobuz_attach = fn(
        "attachQobuzSourceSearch"
    )

    assert (
        "clearLocalMusicSearchAndBrowse();"
        in local_shell
    )

    assert (
        "clearTidalSourceSearchAndLanding();"
        in tidal_attach
    )

    assert (
        "clearQobuzSourceSearchAndLanding();"
        in qobuz_attach
    )


def test_g2p_clear_reset_functions_hide_their_x_control():
    local_clear = fn(
        "clearLocalMusicSearchAndBrowse"
    )
    tidal_clear = fn(
        "clearTidalSourceSearchAndLanding"
    )
    qobuz_clear = fn(
        "clearQobuzSourceSearchAndLanding"
    )

    assert "localMusicSearchClear" in local_clear
    assert "tidalSourceSearchClear" in tidal_clear
    assert "qobuzSourceSearchClear" in qobuz_clear

    for source in (
        local_clear,
        tidal_clear,
        qobuz_clear,
    ):
        compact = "".join(
            source.split()
        )
        assert 'classList.add("hidden")' in compact


def test_g2p_tidal_and_qobuz_mount_provider_bar_with_search():
    tidal = fn(
        "attachTidalSourceSearch"
    )
    qobuz = fn(
        "attachQobuzSourceSearch"
    )

    for source in (
        tidal,
        qobuz,
    ):
        assert (
            '"srovaStreamingStickyControls"'
            in source
        )

        assert (
            '".srovaStreamingProviderBar"'
            in source
        )

        assert (
            "stickyControls.appendChild("
            in source
        )


def test_g2p_tidal_fast_render_preserves_provider_bar():
    tidal = fn(
        "showTidalSource"
    )

    provider_position = tidal.find(
        '".srovaStreamingProviderBar"'
    )

    clear_position = tidal.find(
        'body.innerHTML = "";'
    )

    attach_position = tidal.find(
        "attachTidalSourceSearch("
    )

    assert provider_position >= 0
    assert clear_position > provider_position
    assert attach_position >= 0

    assert (
        "shell.insertBefore("
        in tidal
    )


def test_g2p_streaming_sticky_row_matches_local_control_pattern():
    assert (
        ".srovaStreamingStickyControls"
        in CSS
    )

    assert (
        "grid-template-columns:"
        in CSS
    )

    assert (
        "position: sticky !important;"
        in CSS
    )

    assert (
        "top: 198px !important;"
        in CSS
    )

    assert (
        "top: 162px !important;"
        in CSS
    )


def test_g2p_search_toolbar_is_not_independently_sticky_inside_host():
    marker = (
        ".srovaStreamingStickyControls"
    )

    assert marker in CSS

    tail = CSS[
        CSS.rfind(
            "Q7G-G2P -- SOURCE SEARCH STICKY CONTROL PARITY"
        ):
    ]

    assert (
        "position: static !important;"
        in tail
    )

    assert (
        "#tidalSourceSearchToolbar"
        in tail
    )

    assert (
        "#qobuzSourceSearchToolbar"
        in tail
    )


def test_g2p_clear_button_is_physically_centered():
    pattern = re.compile(
        r"\.srovaInlineSearchClear\s*\{"
        r"(?P<body>.*?)"
        r"\}",
        re.S,
    )

    match = pattern.search(CSS)

    assert match is not None

    block = match.group("body")

    assert "display: inline-flex" in block
    assert "align-items: center" in block
    assert "justify-content: center" in block
    assert "text-align: center" in block


def test_g2p_does_not_change_streaming_provider_selector_contract():
    selector = fn(
        "buildStreamingProviderSelector"
    )

    assert (
        '"showTidalSource()"'
        in selector
    )

    assert (
        '"showQobuzSource()"'
        in selector
    )

    assert (
        "showQobuzSource({"
        not in selector
    )



# Q7G-G3 QOBUZ PROVIDER SEARCH RESULT CONTRACTS


def test_g3_uses_locked_qobuz_normalized_adapters():
    source = fn(
        "qobuzSourceSearchResultSeed"
    )

    assert "adaptQobuzWallItem(" in source
    assert "adaptQobuzUserPlaylist(" in source

    for kind in (
        '"track"',
        '"album"',
        '"artist"',
        '"playlist"',
    ):
        assert kind in source


def test_g3_track_actions_use_locked_qobuz_menu_and_canonical_path():
    play = fn(
        "qobuzSourceSearchPlayTrack"
    )
    menu = fn(
        "qobuzSourceSearchTrackMenu"
    )

    assert '"qobuz:"' in play
    assert "playQobuzWallTrackNow(" in play

    assert "showQobuzTrackArtworkMenu(" in menu
    assert '"qobuzsourcesearch"' in menu

    assert "showTidalSearchTrackMenu(" not in menu
    assert "toggleTrackFavorite(" not in menu
    assert "Add to Playlist" not in menu


def test_g3_album_artist_playlist_open_locked_qobuz_details():
    album = fn(
        "qobuzSourceSearchOpenAlbum"
    )
    artist = fn(
        "qobuzSourceSearchOpenArtist"
    )
    playlist = fn(
        "qobuzSourceSearchOpenPlaylist"
    )

    assert "loadQobuzAlbumDetail(" in album
    assert '"qobuzsourcesearch"' in album

    assert "loadQobuzArtistDetail(" in artist
    assert '"qobuzsourcesearch"' in artist

    assert "loadStreamingPlaylistDetail(" in playlist
    assert '"qobuz"' in playlist
    assert '"qobuzsourcesearch"' in playlist


def test_g3_playlist_return_context_is_additive_and_defaults_to_playlists():
    source = fn(
        "loadStreamingPlaylistDetail"
    )

    assert "fromView" in source
    assert 'previousView = fromView || "playlists";' in source

    assert (
        'provider === "qobuz"'
        in source
    )

    assert (
        '"/api/playlists/complete?provider="'
        in source
    )


def test_g3_qobuz_search_detail_back_restores_saved_search():
    source = fn(
        "goBack"
    )

    assert (
        'previousView === "qobuzsourcesearch"'
        in source
    )

    compact = "".join(
        source.split()
    )

    assert (
        'showQobuzSource({restoreSearch:true});'
        in compact
    )

    assert (
        'restoreDetailReturnScroll("qobuzsource");'
        in source
    )


def test_g3_track_menu_preserves_existing_default_return_context():
    source = fn(
        "showQobuzTrackArtworkMenu"
    )

    assert "fromView" in source
    assert '"qobuzsource"' in source
    assert "detailFromView" in source
    assert "loadQobuzTrackDetail(" in source

    # Q8D later superseded only the original no-playlist-action rule.
    # The Q7G return-context and original track actions remain protected.
    for label in (
        '"Play Now"',
        '"Play Next"',
        '"Add to Queue"',
        '"Track Details"',
        '"Add to Playlist"',
    ):
        assert label in source

    assert (
        "showAddToQobuzPlaylistModal("
        in source
    )


def test_g3_renders_real_results_for_all_five_tabs():
    top = fn(
        "renderQobuzSourceSearchTopPanel"
    )
    tracks = fn(
        "renderQobuzSourceSearchTracksPanel"
    )
    albums = fn(
        "renderQobuzSourceSearchAlbumsPanel"
    )
    artists = fn(
        "renderQobuzSourceSearchArtistsPanel"
    )
    playlists = fn(
        "renderQobuzSourceSearchPlaylistsPanel"
    )

    assert "renderQobuzSourceSearchTopRow(" in top
    assert "renderQobuzSourceSearchTrackRow(" in tracks
    assert "renderQobuzSourceSearchAlbumCard(" in albums
    assert "renderQobuzSourceSearchArtistCard(" in artists
    assert "renderQobuzSourceSearchPlaylistCard(" in playlists


def test_g3_search_results_never_expose_playlist_mutation():
    names = (
        "renderQobuzSourceSearchTopRow",
        "renderQobuzSourceSearchTrackRow",
        "renderQobuzSourceSearchAlbumCard",
        "renderQobuzSourceSearchArtistCard",
        "renderQobuzSourceSearchPlaylistCard",
        "qobuzSourceSearchOpenPlaylist",
    )

    source = "\n".join(
        fn(name)
        for name in names
    )

    for forbidden in (
        "postCreateQobuzPlaylist(",
        "postDeleteQobuzPlaylist(",
        "showCreateQobuzPlaylistModal(",
        "showDeleteQobuzPlaylistModal(",
        "Add to Playlist",
    ):
        assert forbidden not in source


def test_g3_quality_reuses_existing_qobuz_data_q_vocabulary():
    seed = fn(
        "qobuzSourceSearchResultSeed"
    )
    apply = fn(
        "qobuzSourceSearchApplyQuality"
    )

    assert "adaptQobuzWallItem(" in seed
    assert "qobuzLibraryQualityDataValue(" in apply
    assert '"data-q"' in apply

    assert (
        "Q7G-G3 QOBUZ PROVIDER SEARCH RESULT INTEGRATION"
        in CSS
    )

    assert (
        '.qobuzSourceSearchAlbumCard[data-q="cd"]'
        in CSS
    )

    assert (
        '.qobuzSourceSearchTrackRow[data-q="hires"]'
        in CSS
    )


def test_g3_q10i_qobuz_track_rows_use_provider_aware_favorite_control():
    source = fn(
        "renderQobuzSourceSearchTrackRow"
    )

    assert "qobuzSourceSearchTrackMenu(" in source
    assert "qobuzSourceSearchPlayTrack(" in source

    assert (
        "appendQobuzSearchTrackFavoriteHeart("
        in source
    )

    # Provider search must never fall through to historical TIDAL mutation.
    assert "toggleTrackFavorite(" not in source
    assert '"/tidal/favorite/' not in source


def test_g3_qobuz_track_action_button_is_physically_centered_by_shared_css():
    assert ".srovaSearchActionBtn" in CSS
    assert "display: inline-flex !important;" in CSS
    assert "align-items: center !important;" in CSS
    assert "justify-content: center !important;" in CSS

    assert (
        ".qobuzSourceSearchTrackRow"
        in CSS
    )

    assert (
        "@media (max-width: 820px)"
        in CSS
    )


# ================================================================
# Q7G-G4 PROVIDER SWITCH / SEARCH-STATE PROTECTION
# ================================================================

def test_g4_tidal_restores_own_search_when_switching_from_qobuz():
    source = fn(
        "showTidalSource"
    )

    assert (
        "switchingFromQobuzSource"
        in source
    )

    assert (
        'currentSourceSection === "streaming"'
        in source
    )

    assert (
        'currentStreamingProvider === "qobuz"'
        in source
    )

    assert (
        '"#homeSections .srovaQobuzSourcePage"'
        in source
    )

    assert (
        "!!opts.restoreSearch ||"
        in source
    )

    assert (
        "switchingFromQobuzSource"
        in source[
            source.index(
                "var restoreSourceSearch"
            ):
        ]
    )


def test_g4_provider_switch_restore_is_symmetric():
    tidal = fn(
        "showTidalSource"
    )

    qobuz = fn(
        "showQobuzSource"
    )

    assert (
        "switchingFromQobuzSource"
        in tidal
    )

    assert (
        'currentStreamingProvider === "qobuz"'
        in tidal
    )

    assert (
        '"#homeSections .srovaQobuzSourcePage"'
        in tidal
    )

    assert (
        "switchingFromTidalSource"
        in qobuz
    )

    assert (
        'currentStreamingProvider === "tidal"'
        in qobuz
    )

    assert (
        '"#homeSections .srovaTidalSourcePage"'
        in qobuz
    )


def test_g4_provider_selector_callbacks_remain_locked():
    selector = fn(
        "buildStreamingProviderSelector"
    )

    assert (
        '"showTidalSource()"'
        in selector
    )

    assert (
        '"showQobuzSource()"'
        in selector
    )

    assert (
        "showTidalSource({"
        not in selector
    )

    assert (
        "showQobuzSource({"
        not in selector
    )


def test_g4_provider_search_storage_remains_disjoint():
    tidal = (
        fn(
            "persistTidalSourceSearchState"
        )
        +
        fn(
            "clearTidalSourceSearchState"
        )
        +
        fn(
            "readSavedTidalSourceSearchPayload"
        )
        +
        fn(
            "getSavedTidalSourceSearchQuery"
        )
    )

    qobuz = (
        fn(
            "persistQobuzSourceSearchState"
        )
        +
        fn(
            "clearQobuzSourceSearchState"
        )
        +
        fn(
            "readSavedQobuzSourceSearchPayload"
        )
        +
        fn(
            "getSavedQobuzSourceSearchQuery"
        )
    )

    assert (
        "srovaTidalSourceSearchQuery"
        in tidal
    )

    assert (
        "srovaTidalSourceSearchPayload"
        in tidal
    )

    assert (
        "srovaQobuzSourceSearchQuery"
        not in tidal
    )

    assert (
        "srovaQobuzSourceSearchPayload"
        not in tidal
    )

    assert (
        "srovaQobuzSourceSearchQuery"
        in qobuz
    )

    assert (
        "srovaQobuzSourceSearchPayload"
        in qobuz
    )

    assert (
        "srovaTidalSourceSearchQuery"
        not in qobuz
    )

    assert (
        "srovaTidalSourceSearchPayload"
        not in qobuz
    )


def test_g4_does_not_providerize_global_search():
    tidal = fn(
        "showTidalSource"
    )

    qobuz = fn(
        "showQobuzSource"
    )

    for source in (
        tidal,
        qobuz,
    ):
        assert (
            "globalSearchTidalReady"
            not in source
        )

        assert (
            "globalSearchLocalReady"
            not in source
        )
