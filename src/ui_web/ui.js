console.log("SROVA UI loaded");

(function markAndroidApkWebView() {
    var ua = (typeof navigator !== "undefined" && navigator.userAgent) ? navigator.userAgent : "";
    var isAndroid = /Android/i.test(ua);
    var isWebView = /\bwv\b/i.test(ua) || /; wv\)/i.test(ua) ||
        (isAndroid && /Version\/[\d.]+/i.test(ua) && /Chrome\/[\d.]+ Mobile Safari\/[\d.]+/i.test(ua) &&
            !/(EdgA|OPR|Firefox|SamsungBrowser)/i.test(ua));

    if (isAndroid && isWebView && document.documentElement) {
        document.documentElement.classList.add("srovaAndroidApkWebView");
    }
}());

var homeView      = document.getElementById("homeView");
var albumView     = document.getElementById("albumView");
var searchView    = document.getElementById("searchView");
var playlistsView = document.getElementById("playlistsView");
var queueView     = document.getElementById("queueView");
var settingsView  = document.getElementById("settingsView");
var myAlbumsView  = document.getElementById("myAlbumsView");
var mySongsView   = document.getElementById("mySongsView");
var localMusicView = document.getElementById("localMusicView");

var homeSections    = document.getElementById("homeSections");
var playlistsContent = document.getElementById("playlistsContent");
var searchResults   = document.getElementById("searchResults");
var localMusicContent = document.getElementById("localMusicContent");

var albumArt      = document.getElementById("albumArt");
var albumTitle    = document.getElementById("albumTitle");
var albumArtist   = document.getElementById("albumArtist");
var albumTechInfo = document.getElementById("albumTechInfo");
var albumStatsLine = document.getElementById("albumStatsLine");
var trackList     = document.getElementById("trackList");

var playerBar    = document.getElementById("playerBar");
var playerArt    = document.getElementById("playerArt");
var playerTrack  = document.getElementById("playerTrack");
var playerArtist = document.getElementById("playerArtist");
var playerTechTrayToggle = document.getElementById("playerTechTrayToggle");
var playerTechTrayInlineToggle = document.getElementById("playerTechTrayInlineToggle");
var playerTechTray       = document.getElementById("playerTechTray");
var playerTechTrayInner  = playerTechTray ? playerTechTray.querySelector(".playerTechTrayInner") : null;
var playerTechTrayControls = playerTechTray ? playerTechTray.querySelector(".playerTechTrayControls") : null;
var playerTrayTrackInfo = document.getElementById("playerTrayTrackInfo");
var playerTrayTrackInfoText = document.getElementById("playerTrayTrackInfoText");
var playerInfinitePlayControl = document.getElementById("playerInfinitePlayControl");
var playerInfinitePlayBtn     = document.getElementById("playerInfinitePlayBtn");
var playerInfinitePlayMenu    = document.getElementById("playerInfinitePlayMenu");
var playerInfinitePlayMenuBtns = playerInfinitePlayMenu ? Array.prototype.slice.call(playerInfinitePlayMenu.querySelectorAll("[data-mode]")) : [];
var exclusiveLock   = document.getElementById("exclusiveLock");
var npExclusiveLock = document.getElementById("npExclusiveLock");
var bitPerfect      = document.getElementById("bitPerfect");
var npBitPerfect    = document.getElementById("npBitPerfect");

var radioArtistPlayerBar  = document.getElementById("radioArtistPlayerBar");
var radioTitlePlayerBar   = document.getElementById("radioTitlePlayerBar");
var radioArtistNowPlaying = document.getElementById("radioArtistNowPlaying");
var radioTitleNowPlaying  = document.getElementById("radioTitleNowPlaying");

var _lastRadioMetaRaw = null;
var RADIO_IDLE_STANDBY_DELAY_MS = 10000;
var radioIdleStandbyTimer = null;
var radioIdleStandbyApplied = false;
var radioIdleStandbyDueAt = 0;
var radioIdleStandbyRequestInFlight = false;
var lastKnownPlaybackStatus = null;
var currentSourceSection = "";
var playerBarActivePlaybackSource = "";
var playerHasActiveMedia = false;
var homeHeroNowPlayingStateKey = "";
var homeHeroNowPlayingToken = 0;
var playerInfinitePlayOriginalParent = null;
var playerInfinitePlayOriginalNextSibling = null;
// Test22 Point 3: Local CUE virtual tracks cannot use manual seek-to-zero safely.
// Keep a frontend hint so Previous goes to the previous virtual track instead of blocked seek.
var currentPlayingIsLocalCue = false;
var playerInfinitePlayPhoneTrayQuery = window.matchMedia ? window.matchMedia("(max-width: 640px) and (orientation: portrait)") : null;

var progressFill  = document.getElementById("progressFill");
var progressBar   = document.getElementById("progressBar");
var currentTimeEl = document.getElementById("currentTime");
var totalTimeEl   = document.getElementById("totalTime");

var btnPlayPause  = document.getElementById("btnPlayPause");
var btnRepeat     = document.getElementById("btnRepeat");
var btnShuffle    = document.getElementById("btnShuffle");
var loginBtn      = document.getElementById("loginBtn");
var playlistsBtn  = document.getElementById("playlistsBtn");
var queueBtn      = document.getElementById("queueBtn");
var settingsBtn   = document.getElementById("settingsBtn");
var settingsUpdateDot = document.getElementById("settingsUpdateDot");

var searchInput = document.getElementById("searchInput");
var searchClear = document.getElementById("searchClear");
var searchBox   = document.getElementById("searchBox");
var srovaInstanceLabel = document.getElementById("srovaInstanceLabel");

var nowPlayingView    = document.getElementById("nowPlayingView");
var nowPlayingArt     = document.getElementById("nowPlayingArt");
var nowPlayingTrack   = document.getElementById("nowPlayingTrack");
var nowPlayingArtist  = document.getElementById("nowPlayingArtist");
var nowPlayingFrom    = document.getElementById("nowPlayingFromTitle");
var nowPlayingQuality = document.getElementById("nowPlayingQuality");
var playerDacName     = document.getElementById("playerDacName");
var nowPlayingDacName = document.getElementById("nowPlayingDacName");
var nowPlayingFill    = document.getElementById("nowPlayingFill");
var nowPlayingCurrent = document.getElementById("nowPlayingCurrent");
var nowPlayingTotal   = document.getElementById("nowPlayingTotal");
var nowPlayingProgress = document.getElementById("nowPlayingProgress");
var npBtnPlay   = document.getElementById("npBtnPlay");
var npBtnRepeat = document.getElementById("npBtnRepeat");
var npBtnShuffle = document.getElementById("npBtnShuffle");
var npBtnHeart  = document.getElementById("npBtnHeart");
var npBtnNext   = document.getElementById("npBtnNext");
var npBtnPrev   = document.getElementById("npBtnPrev");
var npBtnLyrics = document.getElementById("npBtnLyrics");
var npBtnAlbum  = document.getElementById("npBtnAlbum");
var btnNext     = document.getElementById("btnNext");
var btnPrev     = document.getElementById("btnPrev");
var nowPlayingProgressWrap = document.getElementById("nowPlayingProgressWrap");

var SROVA_ARTWORK_PLACEHOLDER_SRC = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1' height='1'%3E%3C/svg%3E";
var TIDAL_SEARCH_LIMIT = 30;
var localLibraryMaintenanceState = {
    rebuild_running: false,
    maintenance_mode: null,
    scan_running: false,
    last_scan_stats: null
};
var localLibraryMaintenancePoll = null;
var currentSearchTab = "top";
var currentLocalMusicSearchTab = "top";
var lastLocalMusicSearchQuery = "";
var lastLocalMusicSearchPayload = null;
var lastSearchPayload = null;
var onlineSourcesAvailable = true;
var onlineSourcePollTimer = null;
var ONLINE_SOURCE_OFFLINE_MESSAGE = "You are offline. Local Music remains available.";
var globalSearchRequestedVisible = false;
var globalSearchTidalReady = false;
var globalSearchLocalReady = false;
var globalSearchTidalRequestSerial = 0;
var globalSearchLocalRequestSerial = 0;

function fetchWithTimeout(url, options, timeoutMs) {
    options = options || {};
    timeoutMs = timeoutMs || 6000;
    if (typeof AbortController === "undefined") {
        return fetch(url, options);
    }
    var controller = new AbortController();
    var timer = setTimeout(function() { controller.abort(); }, timeoutMs);
    var nextOptions = {};
    Object.keys(options).forEach(function(key) { nextOptions[key] = options[key]; });
    nextOptions.signal = controller.signal;
    return fetch(url, nextOptions).finally(function() {
        clearTimeout(timer);
    });
}

function globalSearchHasReadySource() {
    return !!(globalSearchTidalReady || globalSearchLocalReady);
}

function applyGlobalSearchTidalStatus(data) {
    data = data || {};
    globalSearchTidalReady = !!(
        data.logged_in === true &&
        data.tidal_online === true &&
        data.offline !== true &&
        onlineSourcesAvailable
    );
    setGlobalSearchVisible(globalSearchRequestedVisible);
}

function applyGlobalSearchLocalStatus(data) {
    globalSearchLocalReady = !!(data && data.search_ready === true);
    setGlobalSearchVisible(globalSearchRequestedVisible);
}

function refreshGlobalSearchTidalAvailability() {
    var requestSerial = ++globalSearchTidalRequestSerial;
    return fetchWithTimeout(
        "/tidal/status?_=" + encodeURIComponent(String(Date.now())),
        {cache: "no-store"},
        4000
    )
        .then(function(res) {
            if (!res.ok) { throw new Error("TIDAL status unavailable"); }
            return res.json();
        })
        .then(function(data) {
            if (requestSerial !== globalSearchTidalRequestSerial) { return null; }
            applyGlobalSearchTidalStatus(data || {});
            return data || {};
        })
        .catch(function() {
            if (requestSerial !== globalSearchTidalRequestSerial) { return null; }
            applyGlobalSearchTidalStatus({});
            return null;
        });
}

function refreshGlobalSearchLocalAvailability() {
    var requestSerial = ++globalSearchLocalRequestSerial;
    return fetchWithTimeout(
        "/api/local/library/status",
        {cache: "no-store"},
        4000
    )
        .then(function(res) {
            if (!res.ok) { throw new Error("Local library status unavailable"); }
            return res.json();
        })
        .then(function(data) {
            if (requestSerial !== globalSearchLocalRequestSerial) { return null; }
            applyGlobalSearchLocalStatus(data || {});
            return data || {};
        })
        .catch(function() {
            if (requestSerial !== globalSearchLocalRequestSerial) { return null; }
            applyGlobalSearchLocalStatus({});
            return null;
        });
}

function refreshGlobalSearchAvailability() {
    return Promise.all([
        refreshGlobalSearchTidalAvailability(),
        refreshGlobalSearchLocalAvailability()
    ]);
}

function applyOnlineSourceAvailability(online) {
    var wasOnline = onlineSourcesAvailable;
    onlineSourcesAvailable = online !== false;
    if (document.body) {
        document.body.classList.toggle("srovaOnlineSourcesOffline", !onlineSourcesAvailable);
    }
    var input = document.getElementById("tidalSourceSearchInput");
    if (input) {
        input.disabled = !onlineSourcesAvailable;
        input.placeholder = onlineSourcesAvailable ? "Search TIDAL..." : ONLINE_SOURCE_OFFLINE_MESSAGE;
    }
    if (!onlineSourcesAvailable) {
        globalSearchTidalReady = false;
        setGlobalSearchVisible(globalSearchRequestedVisible);
    } else if (!wasOnline && globalSearchRequestedVisible) {
        refreshGlobalSearchTidalAvailability();
    }
    if (wasOnline && !onlineSourcesAvailable && lastKnownPlaybackStatus) {
        var source = String(lastKnownPlaybackStatus.source || "").toLowerCase();
        var contextType = String(lastKnownPlaybackStatus.context_type || "").toLowerCase();
        var activeRadioLive = source === "radio" || lastKnownPlaybackStatus.radio_mode === true || contextType === "radio";
        if (activeRadioLive) {
            console.log("Online-source offline UI fallback skipped: active radio live stream");
            return;
        }
        var trackId = String(lastKnownPlaybackStatus.current_track_id || currentPlayingId || "");
        var localActive = source === "local" || trackId.indexOf("local:") === 0;
        if (!localActive && (source === "tidal" || lastKnownPlaybackStatus.radio_mode)) {
            clearRadioIdleStandbyTimer();
            updateRadioMetadata({});
            document.body.classList.remove("radioMode");
            applyStandbyPlayerBar();
            updateHomeHeroNowPlaying({playing: false, current_track_valid: false, playback_state: "idle"});
        }
    }
}

function markOnlineSourcesOffline() {
    applyOnlineSourceAvailability(false);
}

function showOfflineSourceToast() {
    showQueueActionToast(ONLINE_SOURCE_OFFLINE_MESSAGE, true);
}

function requireOnlineSource() {
    if (onlineSourcesAvailable) { return true; }
    showOfflineSourceToast();
    return false;
}

function handleOnlineSourceFailure(message) {
    showQueueActionToast(message || ONLINE_SOURCE_OFFLINE_MESSAGE, true);
    refreshOnlineSourceState();
}

function refreshOnlineSourceState() {
    fetchWithTimeout("/api/online-state?_=" + encodeURIComponent(String(Date.now())), {cache: "no-store"}, 3500)
        .then(function(res) {
            if (res.status === 404) { return {online: true, confidence: "unknown"}; }
            if (!res.ok) { throw new Error("online state unavailable"); }
            return res.json();
        })
        .then(function(data) {
            var confidence = String((data && data.confidence) || "").toLowerCase();
            var confirmedOffline = !!data && data.online === false && confidence === "all_failed";
            applyOnlineSourceAvailability(!confirmedOffline);
        })
        .catch(function() {
            applyOnlineSourceAvailability(true);
        })
        .then(function() {
            if (globalSearchRequestedVisible) {
                refreshGlobalSearchLocalAvailability();
            }
        });
}

function startOnlineSourcePolling() {
    refreshOnlineSourceState();
    if (onlineSourcePollTimer) { clearInterval(onlineSourcePollTimer); }
    onlineSourcePollTimer = setInterval(refreshOnlineSourceState, 10000);
}

function initSrovaInstanceLabel() {
    if (!srovaInstanceLabel || typeof fetch !== "function") { return; }

    fetch("/api/network")
        .then(function(res) {
            if (!res.ok) { throw new Error("Network info unavailable"); }
            return res.json();
        })
        .then(function(data) {
            data = data || {};
            var isAndroidApkWebView = !!(document.documentElement &&
                document.documentElement.classList.contains("srovaAndroidApkWebView"));
            var host = String(
                (isAndroidApkWebView ? "" : data.hostname_short) ||
                data.lan_address ||
                data.lan_ip ||
                ""
            ).trim();
            var target = "";

            if (host) {
                target = host;
            } else if (data.url) {
                target = String(data.url).replace(/^https?:\/\//, "").replace(/\/$/, "").split(":")[0];
            }

            if (!target) { return; }
            srovaInstanceLabel.textContent = target;
            srovaInstanceLabel.title = "Connected: SROVA " + target;
            srovaInstanceLabel.classList.remove("hidden");
        })
        .catch(function() {
            srovaInstanceLabel.classList.add("hidden");
        });
}

initSrovaInstanceLabel();

function useArtworkPlaceholder(img) {
    if (!img) { return; }
    img.classList.add("srovaArtworkPlaceholder");
    if (img.getAttribute("src") !== SROVA_ARTWORK_PLACEHOLDER_SRC) {
        img.src = SROVA_ARTWORK_PLACEHOLDER_SRC;
    }
}

function syncArtworkPlaceholder(img) {
    if (!img) { return; }
    var src = img.getAttribute("src") || "";
    if (!src || src === SROVA_ARTWORK_PLACEHOLDER_SRC) {
        useArtworkPlaceholder(img);
    } else {
        img.classList.remove("srovaArtworkPlaceholder");
    }
}

function setupArtworkFallback(img) {
    if (!img) { return; }
    img.onerror = function() { useArtworkPlaceholder(img); };
    syncArtworkPlaceholder(img);
    if (typeof MutationObserver !== "undefined") {
        var observer = new MutationObserver(function() { syncArtworkPlaceholder(img); });
        observer.observe(img, { attributes: true, attributeFilter: ["src"] });
    }
}

setupArtworkFallback(playerArt);
setupArtworkFallback(nowPlayingArt);
setupArtworkFallback(document.getElementById("vpbArt"));

var loginModal   = document.getElementById("loginModal");
var loginWaiting = document.getElementById("loginWaiting");
var loginError   = document.getElementById("loginError");
var loginUrlEl   = document.getElementById("loginUrl");

var _addRadioModal = document.getElementById("add-radio-modal");
var _editingRadioStationId = "";
var _radioReorderMode = false;
var _radioOrderSavePending = false;

/*
 * Point 4: retain the rendered Radio source page between source switches.
 *
 * The station artwork URLs are remote URLs, so destroying/recreating the
 * Radio DOM makes browsers/WebViews create fresh <img> elements and repeat
 * image load/decode work on every return. Keep the actual DOM node alive and
 * validate the saved station data in the background before deciding whether
 * a rebuild is necessary.
 */
var _radioSourcePageCache = null;
var _radioSourceStationSignature = "";
var _radioSourceRefreshInFlight = false;
var _radioSourceCacheGeneration = 0;
var SROVA_STANDBY_ART = "/ui_web/assets/srova-square-logo.png";
if (_addRadioModal) {
    _addRadioModal.addEventListener("click", function(e) {
        if (e.target === _addRadioModal) { closeAddRadioModal(); }
    });
}

var currentDuration  = 0;
var startTime        = 0;
var playing          = false;
var repeatMode       = "off";
var shuffleOn        = false;
var currentPlayingId = null;
var isLoggedIn       = false;
var trackMap         = {};   // id -> {title, artist, cover, duration} for player bar updates
var tidalInfinitePlayEnabled = false;
var tidalInfinitePlayMode = "similar_artist";
var tidalInfinitePlayLastfmConnected = null;
var tidalInfinitePlayRefillInFlight = false;
var tidalInfinitePlayLastRefillKey = "";
var pendingSessionPositionResetTrackId = "";
var pendingSessionPositionResetExpiresAt = 0;
var resumeVisualGuardUntil = 0;
var resumeVisualGuardTrackId = "";
var resumeVisualGuardPosition = 0;
var SESSION_POSITION_RESET_SUPPRESS_MS = 3000;
var seekInFlight = false;
var seekGuardTrackId = "";
var seekGuardPosition = 0;
var seekGuardExpiresAt = 0;
var SEEK_SESSION_GUARD_MS = 1500;

var originalTracks = [];
var shuffledTracks = [];
var currentContext = null;
var previousView      = "home";
var lastTidalSourceSearchQuery = "";
var lastTidalSourceSearchPayload = null;
var currentTidalSourceSearchTab = "top";

var lastSearchQuery   = "";
var lastSearchTab     = "top";

function isRadioLiveStatus(s) {
    s = s || {};
    var source = String(s.source || "").toLowerCase();
    var contextType = String(s.context_type || (s.context && s.context.context_type) || "").toLowerCase();
    var duration = Number(s.duration || (s.context && s.context.duration) || 0);
    return source === "radio" || s.radio_mode === true || contextType === "radio" || duration <= 0;
}

function skipRadioRestoreSeek() {
    console.log("Radio restore/seek skipped: live stream");
}


var previousQueueView = "home";   // view active before entering queue view
var nowPlayingFromView = "home";  // view active when now playing was opened

// Point 8: the album action exists only after the current metadata signature
// resolves to one confident TIDAL album.
var nowPlayingAlbumResolved = null;
var nowPlayingAlbumWatchKey = "";
var nowPlayingAlbumWatchSerial = 0;
var nowPlayingAlbumReturnState = null;

var searchTimer    = null;
var loginPollTimer = null;
var _tidalLoginReturnToSettings = false;
var playlistsLoaded = false;
progressFill._elapsed = 0;

function resetLocalPlaybackProgress() {
    startTime = Date.now() / 1000;
    progressFill._elapsed = 0;
    progressFill.style.width = "0%";
    currentTimeEl.textContent = "0:00";
    if (nowPlayingFill) { nowPlayingFill.style.width = "0%"; }
    if (nowPlayingCurrent) { nowPlayingCurrent.textContent = "0:00"; }
}

function suppressNextSessionPositionForTrack(trackId) {
    pendingSessionPositionResetTrackId = String(trackId || "");
    pendingSessionPositionResetExpiresAt = Date.now() + SESSION_POSITION_RESET_SUPPRESS_MS;
}

function consumeSessionPositionResetForTrack(trackId) {
    if (!pendingSessionPositionResetTrackId) { return false; }
    if (Date.now() > pendingSessionPositionResetExpiresAt) {
        pendingSessionPositionResetTrackId = "";
        pendingSessionPositionResetExpiresAt = 0;
        return false;
    }
    if (String(trackId || "") !== pendingSessionPositionResetTrackId) { return false; }
    pendingSessionPositionResetTrackId = "";
    pendingSessionPositionResetExpiresAt = 0;
    return true;
}

function applyPlaybackPosition(position, isPlaying) {
    var pos = Math.max(0, Number(position || 0));
    if (currentDuration > 0) { pos = Math.min(pos, currentDuration); }
    startTime = Date.now() / 1000 - pos;
    progressFill._elapsed = pos;
    var pct = currentDuration > 0 ? Math.min((pos / currentDuration) * 100, 100) : 0;
    progressFill.style.width = pct + "%";
    currentTimeEl.textContent = formatTime(pos);
    if (nowPlayingFill) { nowPlayingFill.style.width = pct + "%"; }
    if (nowPlayingCurrent) { nowPlayingCurrent.textContent = formatTime(pos); }
    if (nowPlayingTotal && currentDuration > 0) { nowPlayingTotal.textContent = formatTime(currentDuration); }
    playing = !!isPlaying;
    updatePlayPauseIcon();
}

function setSeekSessionGuard(trackId, position) {
    seekGuardTrackId = String(trackId || currentPlayingId || "");
    seekGuardPosition = Math.max(0, Number(position || 0));
    seekGuardExpiresAt = Date.now() + SEEK_SESSION_GUARD_MS;
}

function guardedSessionPosition(trackId, position) {
    if (!seekGuardTrackId) { return Number(position || 0); }
    if (Date.now() > seekGuardExpiresAt) {
        seekGuardTrackId = "";
        seekGuardPosition = 0;
        seekGuardExpiresAt = 0;
        return Number(position || 0);
    }
    if (String(trackId || "") === seekGuardTrackId) {
        return seekGuardPosition;
    }
    return Number(position || 0);
}

var LOCAL_MUSIC_SORT_STORAGE_KEY = "srovaLocalMusicAlbumSort";
var ARTWORK_VIEW_MODE_STORAGE_KEY = "srovaArtworkViewMode";
var localMusicAlbumSort = (function() {
    try {
        var stored = localStorage.getItem(LOCAL_MUSIC_SORT_STORAGE_KEY);
        if (stored === "latest" || stored === "oldest" || stored === "alpha_asc" || stored === "alpha_desc") {
            return stored;
        }
    } catch (e) {}
    return "latest";
}());

function getArtworkViewMode() {
    try {
        var stored = localStorage.getItem(ARTWORK_VIEW_MODE_STORAGE_KEY);
        if (stored === "list" || stored === "grid") { return stored; }
    } catch (e) {}
    return "grid";
}

function setArtworkViewMode(mode) {
    mode = (mode === "list") ? "list" : "grid";
    try { localStorage.setItem(ARTWORK_VIEW_MODE_STORAGE_KEY, mode); } catch (e) {}
    refreshArtworkViewMode();
}

function applyArtworkViewModeClass(container) {
    if (!container) { return; }
    var mode = getArtworkViewMode();
    container.classList.remove("artworkViewGrid");
    container.classList.remove("artworkViewList");
    container.classList.add(mode === "list" ? "artworkViewList" : "artworkViewGrid");
}

function updateArtworkViewToggle(toggle) {
    if (!toggle) { return; }
    var mode = getArtworkViewMode();
    var buttons = toggle.querySelectorAll("button[data-artwork-view-mode]");
    for (var i = 0; i < buttons.length; i++) {
        var btn = buttons[i];
        var active = btn.getAttribute("data-artwork-view-mode") === mode;
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
    }
}

function buildArtworkViewToggle() {
    var toggle = document.createElement("div");
    toggle.className = "artworkViewToggle";
    toggle.setAttribute("aria-label", "Artwork view mode");
    [
        ["grid", "grid_view", "Grid view"],
        ["list", "view_list", "List view"]
    ].forEach(function(item) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "artworkViewToggleBtn";
        btn.setAttribute("data-artwork-view-mode", item[0]);
        btn.setAttribute("title", item[2]);
        btn.setAttribute("aria-label", item[2]);
        btn.innerHTML = '<span class="material-icons">' + item[1] + '</span>';
        btn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            setArtworkViewMode(item[0]);
        };
        toggle.appendChild(btn);
    });
    updateArtworkViewToggle(toggle);
    return toggle;
}

function appendArtworkViewToggle(parent) {
    if (!parent) { return; }
    parent.appendChild(buildArtworkViewToggle());
}

function refreshArtworkViewMode() {
    var containers = document.querySelectorAll(
        ".localMusicCardGrid, .tidalArtworkGrid, .tidalSongList, .srovaSearchAlbumGrid, #tidalSourceSearchResults .searchSection.artworkViewSupported, .artistTopTracksSection, .artistDiscoGrid"
    );
    for (var i = 0; i < containers.length; i++) {
        applyArtworkViewModeClass(containers[i]);
    }
    var toggles = document.querySelectorAll(".artworkViewToggle");
    for (var j = 0; j < toggles.length; j++) {
        updateArtworkViewToggle(toggles[j]);
    }
}

// Last known tech info -- used to populate Now Playing badge from any view
var lastTechText  = "";
var lastTechClass = "hidden";
var localAlbumDetailTechState = null;
var currentDacName = "";
var currentDacLocked = true;
var currentBitPerfect = false;
var currentBitPerfectReason = "Bit Perfect Unconfirmed";

// Tracks loaded in the current album/artist/mix/playlist view.
// Used when building the queue payload on track tap or "+" actions.
var currentViewTracks = [];

// Active popover element (queue-action), closed on outside click.
var activePopover = null;
var queueToastTimer = null;

// Endpoint used to load the current album/artist/playlist/mix view.
// Used by renderAlbumQueueBtn to detect artist context for Save button.
var currentViewEndpoint = "";

// Favorites: in-memory sets mirrored from backend (plain objects as sets).
// {id: true} for each favorited item. Populated by loadFavoriteIds().
var favTrackIds  = {};
var favAlbumIds  = {};
var favArtistIds = {};

// Playback source tracking -- set at every queue/replace entry point
var playbackSource = { type: "", id: "", title: "" };

// Artist page state
var _artistPageRestoreFn = null;   // called by goBack() when previousView === "artistpage"
var _artistDiscogSort    = "default";  // "default" (Tidal order) or "date"

function _setPlaybackSource(type, id, title) {
    playbackSource.type  = type  || "";
    playbackSource.id    = String(id || "");
    playbackSource.title = title || "";
    if (type && type !== "radio") {
        playerBarActivePlaybackSource = "";
        syncPlayerBarRadioProgressState();
        updatePlayerInfinitePlayControl();
    }
}

function syncPlayerBarRadioProgressState() {
    if (!playerBar) { return; }
    var browsingRadio = currentSourceSection === "radio";
    var activeRadio = playerBarActivePlaybackSource === "radio";
    var radioContext = activeRadio || (!playerHasActiveMedia && browsingRadio);
    playerBar.classList.toggle("srovaPlayerBarRadioProgressHidden", radioContext);
    playerBar.classList.toggle("srovaPlayerBarRadioControlsMuted", radioContext);
}

function isRadioSourceSectionActive() {
    return currentSourceSection === "radio" && homeView && homeView.style.display !== "none";
}

function syncRadioSourceSectionState() {
    if (document.body) {
        document.body.classList.toggle("srovaRadioSourceActive", isRadioSourceSectionActive());
    }
    updatePlayerInfinitePlayControl();
}

function setCurrentSourceSection(source) {
    currentSourceSection = source || "";
    syncPlayerBarRadioProgressState();
    syncRadioSourceSectionState();
}

function setPlayerBarActivePlaybackSource(source) {
    playerBarActivePlaybackSource = source || "";
    syncPlayerBarRadioProgressState();
    updatePlayerInfinitePlayControl();
}

function inferStatusPlaybackSource(s) {
    s = s || {};
    var source = String(s.source || "").toLowerCase();
    var contextType = String(s.context_type || "").toLowerCase();
    if (s.radio_mode || source === "radio" || contextType === "radio") { return "radio"; }
    if (source === "tidal") { return "tidal"; }
    if (source === "local") { return "local"; }
    if (String(s.current_track_id || "").indexOf("local:") === 0) { return "local"; }
    if (contextType === "local" || contextType === "local_album" || contextType === "local_queue") { return "local"; }
    return "tidal";
}

function shouldShowInfinitePlayUi(enabled) {
    if (!enabled) { return false; }
    if (playerHasActiveMedia) {
        return playerBarActivePlaybackSource === "tidal";
    }
    return currentSourceSection === "tidal";
}

function syncPlayerInfinitePlayPhoneTrayPlacement() {
    if (!playerInfinitePlayControl || !playerTechTrayInner || !playerTechTrayControls) { return; }

    if (!playerInfinitePlayOriginalParent) {
        playerInfinitePlayOriginalParent = playerInfinitePlayControl.parentNode;
        playerInfinitePlayOriginalNextSibling = playerInfinitePlayControl.nextSibling;
    }

    var usePhoneTray = playerInfinitePlayPhoneTrayQuery ? playerInfinitePlayPhoneTrayQuery.matches : false;
    if (usePhoneTray) {
        if (playerInfinitePlayControl.parentNode !== playerTechTrayInner) {
            playerTechTrayInner.insertBefore(playerInfinitePlayControl, playerTechTrayControls);
        }
    } else if (playerInfinitePlayControl.parentNode !== playerInfinitePlayOriginalParent) {
        if (playerInfinitePlayOriginalNextSibling && playerInfinitePlayOriginalNextSibling.parentNode === playerInfinitePlayOriginalParent) {
            playerInfinitePlayOriginalParent.insertBefore(playerInfinitePlayControl, playerInfinitePlayOriginalNextSibling);
        } else {
            playerInfinitePlayOriginalParent.appendChild(playerInfinitePlayControl);
        }
    }
}

// RC3 Point 4: focused mobile-portrait metadata line.
function _cleanPlayerTrayTrackValue(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
}

function syncPlayerTrayTrackInfoOverflow() {
    if (!playerTrayTrackInfo || !playerTrayTrackInfoText || !playerBar) {
        return;
    }

    var usePhonePortrait = playerInfinitePlayPhoneTrayQuery
        ? playerInfinitePlayPhoneTrayQuery.matches
        : false;
    var trayOpen = playerBar.classList.contains("tech-tray-open");
    var hasText = !!_cleanPlayerTrayTrackValue(
        playerTrayTrackInfoText.textContent
    );

    if (!usePhonePortrait || !trayOpen || !hasText) {
        playerTrayTrackInfoText.classList.remove("is-overflowing");
        playerTrayTrackInfoText.style.removeProperty(
            "--player-tray-scroll-distance"
        );
        playerTrayTrackInfoText.style.removeProperty(
            "--player-tray-scroll-duration"
        );
        playerTrayTrackInfoText.removeAttribute("data-scroll-distance");
        return;
    }

    window.requestAnimationFrame(function() {
        var overflowDistance = Math.ceil(
            playerTrayTrackInfoText.scrollWidth -
            playerTrayTrackInfo.clientWidth
        );

        if (overflowDistance <= 4) {
            playerTrayTrackInfoText.classList.remove("is-overflowing");
            playerTrayTrackInfoText.style.removeProperty(
                "--player-tray-scroll-distance"
            );
            playerTrayTrackInfoText.style.removeProperty(
                "--player-tray-scroll-duration"
            );
            playerTrayTrackInfoText.removeAttribute(
                "data-scroll-distance"
            );
            return;
        }

        var previousDistance = Number(
            playerTrayTrackInfoText.getAttribute(
                "data-scroll-distance"
            ) || 0
        );

        if (
            Math.abs(previousDistance - overflowDistance) > 1 ||
            !playerTrayTrackInfoText.classList.contains("is-overflowing")
        ) {
            var duration = Math.max(
                11,
                Math.min(28, 7 + (overflowDistance / 22))
            );

            playerTrayTrackInfoText.style.setProperty(
                "--player-tray-scroll-distance",
                (-overflowDistance) + "px"
            );
            playerTrayTrackInfoText.style.setProperty(
                "--player-tray-scroll-duration",
                duration.toFixed(1) + "s"
            );
            playerTrayTrackInfoText.setAttribute(
                "data-scroll-distance",
                String(overflowDistance)
            );
            playerTrayTrackInfoText.classList.add("is-overflowing");
        }
    });
}

function syncPlayerTrayTrackInfo(status) {
    if (!playerTrayTrackInfo || !playerTrayTrackInfoText) { return; }

    status = status || lastKnownPlaybackStatus || {};

    if (!playerHasActiveMedia) {
        if (playerTrayTrackInfoText.textContent) {
            playerTrayTrackInfoText.textContent = "";
        }
        playerTrayTrackInfo.removeAttribute("title");
        playerTrayTrackInfo.setAttribute("aria-hidden", "true");
        syncPlayerTrayTrackInfoOverflow();
        return;
    }

    var source = _cleanPlayerTrayTrackValue(
        status.source || status.context_type || ""
    ).toLowerCase();
    var radioActive = source === "radio" ||
        status.radio_mode === true ||
        playerBarActivePlaybackSource === "radio";

    var title = "";
    var artist = "";
    var albumOrStation = "";

    if (radioActive) {
        var radioMeta = status.radio_metadata || {};
        var stationValue = status.radio_station || {};

        title = _cleanPlayerTrayTrackValue(
            radioMeta.title ||
            (radioTitlePlayerBar
                ? radioTitlePlayerBar.textContent
                : "")
        );
        artist = _cleanPlayerTrayTrackValue(
            radioMeta.artist ||
            (radioArtistPlayerBar
                ? radioArtistPlayerBar.textContent
                : "")
        );

        if (typeof stationValue === "string") {
            albumOrStation = _cleanPlayerTrayTrackValue(stationValue);
        } else {
            albumOrStation = _cleanPlayerTrayTrackValue(
                stationValue.name || ""
            );
        }

        if (!albumOrStation && playerTrack) {
            albumOrStation = _cleanPlayerTrayTrackValue(
                playerTrack.textContent
            );
        }
    } else {
        var mappedTrack = (
            currentPlayingId &&
            trackMap[currentPlayingId]
        ) || {};

        title = _cleanPlayerTrayTrackValue(
            status.title ||
            mappedTrack.title ||
            (playerTrack ? playerTrack.textContent : "")
        );
        artist = _cleanPlayerTrayTrackValue(
            status.artist ||
            mappedTrack.artist ||
            (playerArtist ? playerArtist.textContent : "")
        );
        albumOrStation = _cleanPlayerTrayTrackValue(
            status.album ||
            mappedTrack.album ||
            ""
        );
    }

    var parts = [title, artist, albumOrStation].filter(function(value) {
        return !!value;
    });
    var nextText = parts.join(" \u2022 ");

    if (playerTrayTrackInfoText.textContent !== nextText) {
        playerTrayTrackInfoText.classList.remove("is-overflowing");
        playerTrayTrackInfoText.removeAttribute("data-scroll-distance");
        playerTrayTrackInfoText.textContent = nextText;
    }

    if (nextText) {
        playerTrayTrackInfo.title = nextText;
        playerTrayTrackInfo.setAttribute("aria-hidden", "false");
    } else {
        playerTrayTrackInfo.removeAttribute("title");
        playerTrayTrackInfo.setAttribute("aria-hidden", "true");
    }

    syncPlayerTrayTrackInfoOverflow();
}

function setPlayerHasActiveMedia(active) {
    playerHasActiveMedia = !!active;
    if (document.body) {
        document.body.classList.toggle("srovaHasActivePlayerMedia", playerHasActiveMedia);
    }
    if (playerTechTrayInlineToggle) {
        playerTechTrayInlineToggle.disabled = !playerHasActiveMedia;
        playerTechTrayInlineToggle.setAttribute("aria-disabled", playerHasActiveMedia ? "false" : "true");
        playerTechTrayInlineToggle.classList.toggle("is-disabled", !playerHasActiveMedia);
    }
    if (playerBar) {
        playerBar.classList.toggle("srovaPlayerBarHasActiveMedia", playerHasActiveMedia);
        if (!playerHasActiveMedia) {
            playerBar.classList.remove("tech-tray-open");
        }
    }
    if (!playerHasActiveMedia) {
        [playerTechTrayToggle, playerTechTrayInlineToggle].forEach(function(toggle) {
            if (!toggle) { return; }
            toggle.setAttribute("aria-expanded", "false");
            toggle.setAttribute("aria-label", "Show audio path details");
            var toggleIcon = toggle.querySelector(".material-icons");
            if (toggleIcon) { toggleIcon.textContent = "keyboard_arrow_up"; }
        });
    }
    if (!playerHasActiveMedia && playerTechTray) {
        playerTechTray.setAttribute("aria-hidden", "true");
    }
    if (!playerHasActiveMedia) {
        syncPlayerTrayTrackInfo({});
    }
}

function escapeHtml(value) {
    return String(value == null ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function setAlbumViewKind(kind) {
    if (!albumView) { return; }
    albumView.classList.remove("localAlbumDetail");
    albumView.classList.remove("localMusicLocked");
    albumView.classList.remove("tidalAlbumDetail");
    albumView.classList.remove("tidalTrackDetail");
    albumView.classList.remove("tidalArtistDetail");
    albumView.classList.remove("tidalFeaturedTrackList");
    if (kind === "local") {
        albumView.classList.add("localAlbumDetail");
        albumView.classList.toggle("localMusicLocked", isLocalLibraryMaintenance());
    } else {
        localAlbumDetailTechState = null;
    }
    if (kind === "tidal-album") {
        albumView.classList.add("tidalAlbumDetail");
        albumView.classList.add("tidalTrackDetail");
    } else if (kind === "tidal-detail") {
        albumView.classList.add("tidalTrackDetail");
    } else if (kind === "tidal-artist") {
        albumView.classList.add("tidalArtistDetail");
    } else if (kind === "tidal-featured-tracks") {
        albumView.classList.add("tidalFeaturedTrackList");
    }
    if (kind !== "local" && albumStatsLine) {
        albumStatsLine.textContent = "";
        albumStatsLine.className = "hidden";
    }
}

function isLocalAlbumDetailVisible() {
    return albumView &&
        albumView.classList.contains("localAlbumDetail") &&
        albumView.style.display !== "none";
}

function restoreLocalAlbumDetailTechInfo() {
    if (!isLocalAlbumDetailVisible() || !albumTechInfo || !localAlbumDetailTechState) { return false; }
    if (localAlbumDetailTechState.text) {
        albumTechInfo.textContent = localAlbumDetailTechState.text;
        albumTechInfo.className = localAlbumDetailTechState.className;
    } else {
        albumTechInfo.textContent = "";
        albumTechInfo.className = "hidden";
    }
    return true;
}

function localAlbumArtDataUri(title, artist) {
    var mark = escapeHtml(localInitials(title || artist || "S").slice(0, 2));
    var svg =
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">' +
        '<defs>' +
        '<radialGradient id="g" cx="50%" cy="45%" r="62%"><stop offset="0" stop-color="#2a2412"/><stop offset="0.48" stop-color="#10100d"/><stop offset="1" stop-color="#050505"/></radialGradient>' +
        '</defs>' +
        '<rect width="400" height="400" fill="url(#g)"/>' +
        '<rect x="1.5" y="1.5" width="397" height="397" fill="none" stroke="#7b6426" stroke-width="3"/>' +
        '<circle cx="200" cy="200" r="136" fill="none" stroke="#4e401d" stroke-width="2"/>' +
        '<circle cx="200" cy="200" r="96" fill="none" stroke="#a8893a" stroke-width="3"/>' +
        '<circle cx="200" cy="200" r="22" fill="#c9a84c"/>' +
        '<text x="200" y="216" text-anchor="middle" font-family="Josefin Sans, Arial, sans-serif" font-size="56" font-weight="300" fill="#ede6d3">' + mark + '</text>' +
        '</svg>';
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

function localAlbumArtworkUrl(source, title, artist) {
    source = source || {};
    return source.cover || source.cover_url || source.artwork_url || source.image_url ||
        source.album_art || source.album_art_url || localAlbumArtDataUri(title, artist);
}

function applyLocalArtworkFallback(img, title, artist) {
    if (!img) { return; }
    img.classList.remove("localArtworkFallback");
    img.onerror = function() {
        img.onerror = null;
        img.classList.add("localArtworkFallback");
        img.src = localAlbumArtDataUri(title, artist);
    };
    if (!img.getAttribute("src")) {
        img.classList.add("localArtworkFallback");
        img.src = localAlbumArtDataUri(title, artist);
    }
}


// --- Utilities ---

function formatTime(sec) {
    sec = Math.floor(sec);
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return m + ":" + (s < 10 ? "0" + s : s);
}

function queueActionSummary(action, tracksList) {
    var tracks = Array.isArray(tracksList) ? tracksList : [];
    var count = tracks.length || 1;
    var total = 0;
    var hasDuration = false;
    for (var i = 0; i < tracks.length; i++) {
        var dur = Number(tracks[i] && tracks[i].duration);
        if (dur > 0) {
            total += dur;
            hasDuration = true;
        }
    }
    var label = count === 1 ? "track" : "tracks";
    var target = action === "next" ? "play next" : "queue";
    if (hasDuration && total > 0) {
        return "Added " + count + " " + label + " \u00b7 " + formatTime(total) + " to " + target;
    }
    return "Added " + count + " " + label + " to " + target;
}

function showQueueActionToast(message, isError) {
    var toast = document.getElementById("queueActionToast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "queueActionToast";
        toast.className = "queueActionToast";
        document.body.appendChild(toast);
    }
    var text = normalizePlaybackErrorMessage(message) || "";
    toast.textContent = text;
    toast.className = "queueActionToast" + (isError ? " error" : "") +
        (text === DAC_PLAYBACK_ERROR_MESSAGE ? " dacAlert" : "");
    toast.classList.add("visible");
    if (queueToastTimer) { clearTimeout(queueToastTimer); }
    queueToastTimer = setTimeout(function() {
        toast.classList.remove("visible");
    }, 2600);
}

var DAC_PLAYBACK_ERROR_KEY = "dac_not_detected";
var DAC_PLAYBACK_ERROR_TEXT = "DAC not detected. Please connect or switch on your DAC before playback.";
var DAC_PLAYBACK_ERROR_MESSAGE = "DAC not detected.\nPlease connect or switch on your DAC before playback.";

function normalizePlaybackErrorMessage(value) {
    if (value === null || typeof value === "undefined") { return ""; }
    var text = "";
    if (typeof value === "string") {
        text = value;
    } else if (value && typeof value.message === "string") {
        text = value.message;
    } else {
        text = String(value || "");
    }
    var compact = text.replace(/\s+/g, " ").trim();
    if (compact === DAC_PLAYBACK_ERROR_KEY || compact === DAC_PLAYBACK_ERROR_TEXT) {
        return DAC_PLAYBACK_ERROR_MESSAGE;
    }
    return text;
}

function playbackErrorMessage(data, fallback) {
    data = data || {};
    var error = normalizePlaybackErrorMessage(data.error);
    if (error === DAC_PLAYBACK_ERROR_MESSAGE) { return error; }
    var message = normalizePlaybackErrorMessage(data.message);
    if (message) { return message; }
    if (error) { return error; }
    message = normalizePlaybackErrorMessage(data);
    if (message) { return message; }
    return normalizePlaybackErrorMessage(fallback) || "Playback failed";
}

function formatDuration(sec) {
    sec = Math.floor(sec);
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    if (h > 0) { return h + "h " + m + "m"; }
    return m + "m";
}

function _dacDisplayName(name, driver, device) {
    var n = String(name || "").trim();
    if (n) { return n; }
    var d = String(device || "").trim();
    var r = String(driver || "").trim();
    if (r && d) { return r + " / " + d; }
    return d || "";
}

function _audioInfoClassForState() {
    if (exclusiveLock && exclusiveLock.classList.contains("exclusiveLockHiRes")) { return "audioInfoBox audioInfoHiRes"; }
    if (exclusiveLock && exclusiveLock.classList.contains("exclusiveLockCD"))    { return "audioInfoBox audioInfoCD"; }
    return "audioInfoBox audioInfoOff";
}

function syncDacNameDisplay() {
    var text = currentDacName || "";
    var cls = _audioInfoClassForState();
    [playerDacName, nowPlayingDacName].forEach(function(el) {
        if (!el) { return; }
        el.textContent = text ? text.toUpperCase() : "";
        el.className = cls;
        if (!text) { el.classList.add("hidden"); }
        else       { el.classList.remove("hidden"); }
    });
}

function updateDacStateFromStatus(s) {
    currentDacName = _dacDisplayName(s.dac_name, s.alsa_driver, s.alsa_device);
    currentDacLocked = !!s.dac_locked;
    syncDacNameDisplay();
}

function updateBitPerfectReadout(s, isHiRes) {
    currentBitPerfect = !!(s && s.bit_perfect_path_confirmed === true);
    currentBitPerfectReason = (s && s.bit_perfect_reason) ? String(s.bit_perfect_reason) : "Bit Perfect Unconfirmed";

    var cls = "bitPerfectReadout bitPerfectOff";
    var ttl = currentBitPerfectReason || "Bit Perfect Unconfirmed";
    if (currentBitPerfect) {
        cls = "bitPerfectReadout " + (isHiRes ? "bitPerfectHiRes" : "bitPerfectCD");
        ttl = "Bit Perfect Path Confirmed — " + currentBitPerfectReason;
    }

    [bitPerfect, npBitPerfect].forEach(function(el) {
        if (!el) { return; }
        el.className = cls;
        el.title = ttl;
        el.setAttribute("aria-label", ttl);
    });
}


// --- Now Playing full screen ---

function openNowPlaying() {
    if (!playing && !currentPlayingId) { return; }
    if (albumView.style.display !== "none")         { nowPlayingFromView = "album"; }
    else if (searchView.style.display !== "none")   { nowPlayingFromView = "search"; }
    else if (playlistsView && playlistsView.style.display !== "none") { nowPlayingFromView = "playlists"; }
    else if (queueView && queueView.style.display !== "none") { nowPlayingFromView = "queue"; }
    else                                            { nowPlayingFromView = "home"; }
    var meta = (currentPlayingId && trackMap[currentPlayingId]) || {};
    var art    = playerArt.src            || meta.cover    || "";
    var title  = playerTrack.textContent  || meta.title    || "";
    var artist = playerArtist.textContent || meta.artist   || "";
    var total  = totalTimeEl.textContent  || formatTime(meta.duration || 0) || "0:00";

    // "Playing from" label -- derive from playbackSource
    var srcType  = playbackSource.type  || "";
    var srcTitle = playbackSource.title || (currentContext ? (currentContext.title || "") : "") || (meta.contextTitle || "");
    var fromLabel = "PLAYING FROM";
    if      (srcType === "album")    { fromLabel = "PLAYING FROM ALBUM"; }
    else if (srcType === "playlist") { fromLabel = "PLAYING FROM PLAYLIST"; }
    else if (srcType === "mix")      { fromLabel = "PLAYING FROM MIX"; }
    else if (srcType === "artist")   { fromLabel = "ARTIST TOP TRACKS"; }
    else if (srcType === "search")   { fromLabel = "FROM SEARCH"; }
    else if (srcType === "mysongs")  { fromLabel = "FROM MY SONGS"; }
    else if (srcType === "myalbums") { fromLabel = "FROM MY ALBUMS"; }
    else if (srcType === "hires")    { fromLabel = "FROM HI-RES"; }
    else if (srcType === "home")     { fromLabel = "PLAYING FROM"; }
    else if (srcType === "radio")    { fromLabel = "LIVE RADIO"; }

    var fromLabelEl = document.getElementById("nowPlayingFromLabel");
    if (fromLabelEl) { fromLabelEl.textContent = fromLabel; }

    nowPlayingArt.src            = art;
    nowPlayingTrack.textContent  = title;
    nowPlayingArtist.textContent = artist;
    nowPlayingFrom.textContent   = srcTitle;
    nowPlayingTotal.textContent  = total;
    if (lastTechText) {
        nowPlayingQuality.textContent = lastTechText;
        nowPlayingQuality.className   = lastTechClass + " npQuality";
    } else {
        nowPlayingQuality.textContent = "";
        nowPlayingQuality.className   = "hidden";
    }
    syncDacNameDisplay();
    syncNowPlayingButtons();
    updateNpHeart();
    nowPlayingView.classList.remove("hidden");
    document.body.classList.add("nowPlayingOpen");
}

function closeNowPlaying() {
    closeMetaPanel();
    closeLyricsPanel();
    closeVuPanel();
    nowPlayingView.classList.add("hidden");
    document.body.classList.remove("nowPlayingOpen");
    showView(nowPlayingFromView);
}

function syncNowPlayingButtons() {
    if (!npBtnPlay) { return; }
    _setPlayIconButton(npBtnPlay, playing);
    var repIcon = npBtnRepeat.querySelector(".material-icons");
    if (repeatMode === "one") {
        repIcon.textContent = "repeat_one";
        npBtnRepeat.classList.add("active");
    } else if (repeatMode === "all") {
        repIcon.textContent = "repeat";
        npBtnRepeat.classList.add("active");
    } else {
        repIcon.textContent = "repeat";
        npBtnRepeat.classList.remove("active");
    }
    if (shuffleOn) { npBtnShuffle.classList.add("active"); }
    else           { npBtnShuffle.classList.remove("active"); }
}




function hideNowPlayingAlbumAction() {
    nowPlayingAlbumResolved = null;
    if (npBtnAlbum) {
        npBtnAlbum.classList.add("hidden");
    }
}

function nowPlayingAlbumWatchSignature(s) {
    s = s || {};
    var source = inferStatusPlaybackSource(s);
    var radio = s.radio_metadata || {};
    var station = s.radio_station || {};
    return [
        s.logged_in === true ? "logged-in" : "logged-out",
        source || "",
        String(s.current_track_id || s.track_id || ""),
        String(s.context_id || ""),
        String(s.album_id || ""),
        String(s.artist || ""),
        String(s.title || ""),
        String(s.album || ""),
        String(radio.raw || ""),
        String(radio.artist || ""),
        String(radio.title || ""),
        String(station.id || station.name || "")
    ].join("\0");
}

function syncNowPlayingAlbumWatcher(s) {
    if (!npBtnAlbum) { return; }

    s = s || {};
    var valid = (
        s.logged_in === true &&
        s.current_track_valid !== false &&
        s.playback_state !== "idle"
    );

    if (!valid) {
        nowPlayingAlbumWatchKey = "";
        nowPlayingAlbumWatchSerial += 1;
        hideNowPlayingAlbumAction();
        return;
    }

    var signature = nowPlayingAlbumWatchSignature(s);
    if (!signature || signature === nowPlayingAlbumWatchKey) {
        return;
    }

    nowPlayingAlbumWatchKey = signature;
    var serial = ++nowPlayingAlbumWatchSerial;
    hideNowPlayingAlbumAction();

    fetchWithTimeout(
        "/tidal/now-playing-album",
        {cache: "no-store"},
        8000
    )
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (serial !== nowPlayingAlbumWatchSerial) { return; }
        if (signature !== nowPlayingAlbumWatchKey) { return; }

        var latest = lastKnownPlaybackStatus || {};
        if (nowPlayingAlbumWatchSignature(latest) !== signature) { return; }

        data = data || {};
        var albumId = String(data.album_id || "").trim();
        if (data.available !== true || !albumId) {
            hideNowPlayingAlbumAction();
            return;
        }

        nowPlayingAlbumResolved = {
            signature: signature,
            albumId: albumId,
            albumTitle: String(data.album_title || latest.album || "").trim(),
            albumArtist: String(data.album_artist || latest.artist || "").trim(),
            albumCover: String(
                data.album_cover ||
                latest.cover ||
                latest.radio_cover_art_url ||
                ""
            ).trim()
        };
        npBtnAlbum.classList.remove("hidden");
    })
    .catch(function() {
        if (serial === nowPlayingAlbumWatchSerial) {
            hideNowPlayingAlbumAction();
        }
    });
}

function copyNowPlayingPlaybackSource() {
    return {
        type: playbackSource.type || "",
        id: playbackSource.id || "",
        title: playbackSource.title || ""
    };
}

function copyNowPlayingCurrentContext() {
    if (!currentContext || typeof currentContext !== "object") {
        return null;
    }
    var out = {};
    Object.keys(currentContext).forEach(function(key) {
        out[key] = currentContext[key];
    });
    return out;
}

function applyNowPlayingPlaybackContextSnapshot(state) {
    state = state || {};
    var savedSource = state.playbackSource || {};
    playbackSource.type = savedSource.type || "";
    playbackSource.id = savedSource.id || "";
    playbackSource.title = savedSource.title || "";
    currentContext = state.currentContext ?
        copyObjectShallow(state.currentContext) :
        null;
}

function copyObjectShallow(source) {
    if (!source || typeof source !== "object") { return null; }
    var out = {};
    Object.keys(source).forEach(function(key) {
        out[key] = source[key];
    });
    return out;
}

function applyNowPlayingPlaybackContextFromStatus(s) {
    s = s || {};
    if (s.current_track_valid === false || s.playback_state === "idle") {
        playbackSource.type = "";
        playbackSource.id = "";
        playbackSource.title = "";
        currentContext = null;
        return;
    }

    var source = inferStatusPlaybackSource(s);
    var type = String(s.context_type || "").trim();
    if (source === "radio") {
        type = "radio";
    } else if (!type) {
        type = source || "";
    }

    var station = s.radio_station || {};
    var contextTitle = String(
        s.context_title ||
        s.album ||
        station.name ||
        ""
    );

    playbackSource.type = type;
    playbackSource.id = String(
        s.context_id ||
        s.album_id ||
        s.current_track_id ||
        ""
    );
    playbackSource.title = contextTitle;

    currentContext = {
        id: playbackSource.id,
        title: contextTitle,
        artist: String(s.artist || ""),
        cover: String(s.cover || s.radio_cover_art_url || "")
    };
}

function openNowPlayingResolvedAlbum() {
    var resolved = nowPlayingAlbumResolved;
    var status = lastKnownPlaybackStatus || {};

    if (
        !resolved ||
        !resolved.albumId ||
        resolved.signature !== nowPlayingAlbumWatchSignature(status)
    ) {
        hideNowPlayingAlbumAction();
        syncNowPlayingAlbumWatcher(status);
        return;
    }

    nowPlayingAlbumReturnState = {
        underlyingView: nowPlayingFromView || "home",
        signature: resolved.signature,
        playbackSource: copyNowPlayingPlaybackSource(),
        currentContext: copyNowPlayingCurrentContext()
    };

    closeMetaPanel();
    closeLyricsPanel();
    closeVuPanel();

    nowPlayingView.classList.add("hidden");
    document.body.classList.remove("nowPlayingOpen");

    // Restore the view that was underneath Now Playing before using the normal
    // album detail renderer. The album renderer may temporarily set browsing
    // context; the Back path below restores the live playback context.
    showView(nowPlayingAlbumReturnState.underlyingView);

    loadTrackList(
        {
            id: resolved.albumId,
            cover: resolved.albumCover || "",
            title: resolved.albumTitle || "TIDAL Album",
            artist: resolved.albumArtist || ""
        },
        "/tidal/album/" + resolved.albumId,
        "nowplaying"
    );
}

function goBackToNowPlayingFromAlbum() {
    var state = nowPlayingAlbumReturnState || {};
    nowPlayingAlbumReturnState = null;

    var status = lastKnownPlaybackStatus || {};
    var currentSignature = nowPlayingAlbumWatchSignature(status);

    // If playback did not change while browsing the album, restore the exact
    // pre-drill-down playback context. Otherwise rebuild it from the newest
    // authoritative status snapshot.
    if (state.signature && state.signature === currentSignature) {
        applyNowPlayingPlaybackContextSnapshot(state);
    } else {
        applyNowPlayingPlaybackContextFromStatus(status);
    }

    showView(state.underlyingView || nowPlayingFromView || "home");
    openNowPlaying();
}


var HOME_GATEWAY_APP_PANEL_CLASS = "srovaHomeGatewayAppPanel";
var homeGatewayAppPanelResizeBound = false;
var homeGatewayAppPanelResizeObserver = null;
var homeGatewayAppPanelMutationObserver = null;

function syncHomeGatewayAppPanelMetrics() {
    if (!homeView ||
        !homeView.classList.contains(HOME_GATEWAY_APP_PANEL_CLASS)) {
        return;
    }

    var headerEl = document.querySelector("body > header");
    var headerBottom = headerEl ?
        Math.max(0, Math.ceil(headerEl.getBoundingClientRect().bottom)) :
        0;

    var occupiedBottom = 0;
    if (playerBar) {
        var playerRect = playerBar.getBoundingClientRect();
        if (playerRect.height > 0) {
            occupiedBottom = Math.max(
                0,
                Math.ceil(window.innerHeight - playerRect.top)
            );
        }
    }

    homeView.style.setProperty(
        "--srova-home-app-top",
        headerBottom + "px"
    );
    homeView.style.setProperty(
        "--srova-home-app-bottom",
        occupiedBottom + "px"
    );

    var panelHeight = Math.max(
        0,
        window.innerHeight - headerBottom - occupiedBottom
    );

    var computed = window.getComputedStyle(homeView);
    var reservedHeight = parseFloat(
        computed.getPropertyValue("--srova-home-nonart-h")
    ) || 320;

    var widthLimit = Math.max(0, window.innerWidth - 28);
    var heightLimit = Math.max(0, panelHeight - reservedHeight);

    var artworkSize = Math.floor(
        Math.min(420, widthLimit, heightLimit)
    );

    /*
     * The normal supported phone range remains well above this guard.
     * It prevents a zero-sized image during transient viewport changes.
     */
    artworkSize = Math.max(120, artworkSize);

    homeView.style.setProperty(
        "--srova-home-art-size",
        artworkSize + "px"
    );
}

function setHomeGatewayAppPanel(active) {
    active = !!active;

    if (!homeView) { return; }

    homeView.classList.toggle(
        HOME_GATEWAY_APP_PANEL_CLASS,
        active
    );

    if (document.documentElement) {
        document.documentElement.classList.toggle(
            HOME_GATEWAY_APP_PANEL_CLASS,
            active
        );
    }

    if (document.body) {
        document.body.classList.toggle(
            HOME_GATEWAY_APP_PANEL_CLASS,
            active
        );
    }

    if (!active) {
        homeView.style.removeProperty("--srova-home-app-top");
        homeView.style.removeProperty("--srova-home-app-bottom");
        homeView.style.removeProperty("--srova-home-art-size");
        return;
    }

    if (!homeGatewayAppPanelResizeBound) {
        window.addEventListener(
            "resize",
            syncHomeGatewayAppPanelMetrics
        );
        window.addEventListener(
            "orientationchange",
            syncHomeGatewayAppPanelMetrics
        );

        /*
         * Android WebView and mobile browsers can change the usable
         * visual viewport without producing a dependable layout resize.
         */
        if (window.visualViewport) {
            window.visualViewport.addEventListener(
                "resize",
                syncHomeGatewayAppPanelMetrics
            );
        }

        /*
         * Recalculate whenever the actual header or fixed Player Bar
         * geometry changes. This covers the Player Bar appearing after
         * restoreSession() and responsive height changes.
         */
        if (window.ResizeObserver) {
            homeGatewayAppPanelResizeObserver =
                new window.ResizeObserver(function() {
                    syncHomeGatewayAppPanelMetrics();
                });

            var observedHeader =
                document.querySelector("body > header");

            if (observedHeader) {
                homeGatewayAppPanelResizeObserver.observe(
                    observedHeader
                );
            }

            if (playerBar) {
                homeGatewayAppPanelResizeObserver.observe(
                    playerBar
                );
            }
        }

        /*
         * ResizeObserver normally catches hidden-to-visible geometry,
         * while this class/style observer provides a deterministic
         * fallback for WebViews where display changes are reported late.
         */
        if (window.MutationObserver && playerBar) {
            homeGatewayAppPanelMutationObserver =
                new window.MutationObserver(function(mutations) {
                    var geometryMayHaveChanged =
                        mutations.some(function(mutation) {
                            return mutation.type === "attributes" &&
                                (
                                    mutation.attributeName === "class" ||
                                    mutation.attributeName === "style"
                                );
                        });

                    if (geometryMayHaveChanged) {
                        window.requestAnimationFrame(
                            syncHomeGatewayAppPanelMetrics
                        );
                    }
                });

            homeGatewayAppPanelMutationObserver.observe(
                playerBar,
                {
                    attributes: true,
                    attributeFilter: ["class", "style"]
                }
            );
        }

        homeGatewayAppPanelResizeBound = true;
    }

    setSrovaPageScrollTop(0);
    syncHomeGatewayAppPanelMetrics();

    window.requestAnimationFrame(function() {
        syncHomeGatewayAppPanelMetrics();
        window.requestAnimationFrame(
            syncHomeGatewayAppPanelMetrics
        );
    });
}


// --- View switching ---

function showView(name) {
    if (name !== "home") {
        setHomeGatewayAppPanel(false);
        _cancelHomeSlotPolls();
    }
    homeView.style.display      = (name === "home")      ? "block" : "none";
    searchView.style.display    = (name === "search")    ? "block" : "none";
    albumView.style.display     = (name === "album")     ? "block" : "none";
    if (playlistsView) {
        playlistsView.style.display = (name === "playlists") ? "block" : "none";
    }
    if (settingsView) {
        settingsView.style.display = (name === "settings") ? "block" : "none";
    }
    if (queueView) {
        queueView.style.display = (name === "queue") ? "block" : "none";
    }
    if (myAlbumsView) {
        myAlbumsView.style.display = (name === "myalbums") ? "block" : "none";
    }
    if (mySongsView) {
        mySongsView.style.display = (name === "mysongs") ? "block" : "none";
    }
    if (localMusicView) {
        localMusicView.style.display = (name === "localmusic") ? "block" : "none";
    }

    if (name === "home" &&
        homeSections &&
        homeSections.querySelector("#srovaGateway")) {
        setHomeGatewayAppPanel(true);
    }

    if (name !== "album") {
        playerBar.classList.add("hidden");
    }
    // Show player bar when something is playing (except playlists -- cleaner)
    if (playing && name !== "album" && name !== "playlists") {
        playerBar.classList.remove("hidden");
    }
    // Player bar always visible in queue view if queue exists
    if (name === "queue" && currentPlayingId) {
        playerBar.classList.remove("hidden");
    }
    if (playlistsBtn) {
        if (name === "playlists") { playlistsBtn.classList.add("active"); }
        else                      { playlistsBtn.classList.remove("active"); }
    }
    if (settingsBtn) {
        if (name === "settings") { settingsBtn.classList.add("active"); }
        else                     { settingsBtn.classList.remove("active"); }
    }
    if (queueBtn) {
        if (name === "queue") { queueBtn.classList.add("active"); }
        else                  { queueBtn.classList.remove("active"); }
    }
    if (name === "album" && lastTechText && albumTechInfo) {
        if (!restoreLocalAlbumDetailTechInfo()) {
            albumTechInfo.textContent = lastTechText;
            albumTechInfo.className   = lastTechClass;
        }
    }
    // Dismiss any open popover when switching views
    closeActivePopover();
    syncPlayerBarRadioProgressState();
    syncRadioSourceSectionState();
}

function getSrovaDocumentScrollElement() {
    return document.scrollingElement || document.documentElement || document.body;
}

function getSrovaPageScrollTop() {
    var el = getSrovaDocumentScrollElement();
    return window.pageYOffset || (el && el.scrollTop) || (document.documentElement && document.documentElement.scrollTop) || (document.body && document.body.scrollTop) || 0;
}

function setSrovaPageScrollTop(value) {
    value = Math.max(0, Number(value) || 0);
    if (document.documentElement) { document.documentElement.scrollTop = value; }
    if (document.body) { document.body.scrollTop = value; }
    window.scrollTo(0, value);
}

function getSrovaElementScrollTop(scroller) {
    if (!scroller || scroller === getSrovaDocumentScrollElement() || scroller === document.documentElement || scroller === document.body) {
        return getSrovaPageScrollTop();
    }
    return scroller.scrollTop || 0;
}

function setSrovaElementScrollTop(scroller, value) {
    value = Math.max(0, Number(value) || 0);
    if (!scroller || scroller === getSrovaDocumentScrollElement() || scroller === document.documentElement || scroller === document.body) {
        setSrovaPageScrollTop(value);
        return;
    }
    scroller.scrollTop = value;
}

function getSrovaBestScrollContainer(preferred) {
    if (preferred && preferred.scrollHeight > preferred.clientHeight + 4) {
        return preferred;
    }
    return getSrovaDocumentScrollElement();
}

function getSrovaElementTopInScroller(el, scroller) {
    if (!el) { return 0; }
    if (!scroller || scroller === getSrovaDocumentScrollElement() || scroller === document.documentElement || scroller === document.body) {
        return el.getBoundingClientRect().top + getSrovaPageScrollTop();
    }
    var er = el.getBoundingClientRect();
    var sr = scroller.getBoundingClientRect();
    return (er.top - sr.top) + (scroller.scrollTop || 0);
}

var _detailReturnScrollState = null;

function captureDetailReturnScroll(viewName) {
    viewName = String(viewName || "").trim();
    if (!viewName) { return; }
    _detailReturnScrollState = {
        view: viewName,
        top: getSrovaPageScrollTop()
    };
    try {
        sessionStorage.setItem("srovaDetailReturnScrollState", JSON.stringify(_detailReturnScrollState));
    } catch (e) {}
}

function readDetailReturnScrollState() {
    if (_detailReturnScrollState) { return _detailReturnScrollState; }
    try {
        var raw = sessionStorage.getItem("srovaDetailReturnScrollState") || "";
        if (raw) {
            _detailReturnScrollState = JSON.parse(raw);
            return _detailReturnScrollState;
        }
    } catch (e) {}
    return null;
}

function restoreDetailReturnScroll(viewName) {
    viewName = String(viewName || "").trim();
    var state = readDetailReturnScrollState();
    if (!state || !viewName || state.view !== viewName) { return; }
    var target = Math.max(0, Number(state.top) || 0);
    var attempts = 0;
    function apply() {
        setSrovaPageScrollTop(target);
        attempts += 1;
        if (attempts < 16) {
            setTimeout(apply, 100);
        }
    }
    requestAnimationFrame(apply);
}

function resetAlbumDetailScroll() {
    if (albumView) { albumView.scrollTop = 0; }
    if (trackList) { trackList.scrollTop = 0; }
    setSrovaPageScrollTop(0);
    requestAnimationFrame(function() {
        if (albumView) { albumView.scrollTop = 0; }
        if (trackList) { trackList.scrollTop = 0; }
        setSrovaPageScrollTop(0);
    });
}

function shouldResetTrackListDetailScroll(endpoint) {
    return endpoint &&
        (endpoint.indexOf("/tidal/album/") === 0 ||
         endpoint.indexOf("/tidal/playlist/") === 0 ||
         endpoint.indexOf("/tidal/mix/") === 0);
}

function setGlobalSearchVisible(visible) {
    globalSearchRequestedVisible = visible === true;
    visible = globalSearchRequestedVisible && globalSearchHasReadySource();
    if (searchBox) {
        if (visible) {
            searchBox.classList.remove("hidden");
            searchBox.style.removeProperty("display");
        } else {
            searchBox.classList.add("hidden");
            searchBox.style.setProperty("display", "none", "important");
        }
    }
    if (searchInput) {
        if (visible) {
            searchInput.disabled = false;
            searchInput.removeAttribute("aria-hidden");
            if (!searchInput.value && searchClear) {
                searchClear.classList.add("hidden");
            }
        } else {
            clearTimeout(searchTimer);
            searchInput.value = "";
            searchInput.disabled = true;
            searchInput.setAttribute("aria-hidden", "true");
            if (searchClear) { searchClear.classList.add("hidden"); }
        }
    }
    if (
        globalSearchRequestedVisible &&
        !visible &&
        searchView &&
        searchView.style.display !== "none"
    ) {
        if (searchResults) { searchResults.innerHTML = ""; }
        showView("home");
    }
}

function showHome() { loadHome(); }

function goHome() {
    searchInput.value = "";
    searchClear.classList.add("hidden");
    loadHome();
}


function persistSearchRestorePayload() {
    try {
        if (lastSearchPayload && lastSearchPayload.query) {
            sessionStorage.setItem("srovaLastSearchQuery", String(lastSearchPayload.query || ""));
            sessionStorage.setItem("srovaLastSearchPayload", JSON.stringify(lastSearchPayload));
        } else if (lastSearchPayload && lastSearchPayload.hasAny) {
            sessionStorage.setItem("srovaLastSearchPayload", JSON.stringify(lastSearchPayload));
        }
        sessionStorage.setItem("srovaLastSearchTab", currentSearchTab || "top");
    } catch (e) {}
}

function captureSearchRestoreState() {
    var q = "";
    if (lastSearchPayload && lastSearchPayload.query) {
        q = String(lastSearchPayload.query || "").trim();
    }
    if (!q && searchInput && searchInput.value) {
        q = searchInput.value.trim();
    }
    if (q) {
        lastSearchQuery = q;
        try { sessionStorage.setItem("srovaLastSearchQuery", q); } catch (e) {}
    }
    lastSearchTab = currentSearchTab || lastSearchTab || "top";
    try { sessionStorage.setItem("srovaLastSearchTab", lastSearchTab); } catch (e) {}
    persistSearchRestorePayload();
}

function readSavedSearchPayload() {
    try {
        var raw = sessionStorage.getItem("srovaLastSearchPayload") || "";
        if (!raw) { return null; }
        var parsed = JSON.parse(raw);
        return parsed && parsed.hasAny ? parsed : null;
    } catch (e) {
        return null;
    }
}

function restoreSearchView() {
    if (!globalSearchHasReadySource()) {
        setGlobalSearchVisible(true);
        showView("home");
        return;
    }
    showView("search");

    var savedTab = "";
    try { savedTab = sessionStorage.getItem("srovaLastSearchTab") || ""; } catch (e) {}
    currentSearchTab = savedTab || lastSearchTab || currentSearchTab || "top";

    var payload = (lastSearchPayload && lastSearchPayload.hasAny) ? lastSearchPayload : readSavedSearchPayload();
    if (payload && payload.hasAny) {
        lastSearchPayload = payload;
        lastSearchQuery = payload.query || lastSearchQuery || "";
        if (searchInput && lastSearchQuery) {
            searchInput.value = lastSearchQuery;
            if (searchClear) { searchClear.classList.remove("hidden"); }
        }
        renderSrovaSearchShell(payload);
        return;
    }

    var q = String(lastSearchQuery || "").trim();
    if (!q) {
        try { q = String(sessionStorage.getItem("srovaLastSearchQuery") || "").trim(); } catch (e) {}
    }
    if (!q && searchInput && searchInput.value) {
        q = searchInput.value.trim();
    }

    if (q) {
        if (searchInput) { searchInput.value = q; }
        if (searchClear) { searchClear.classList.remove("hidden"); }
        searchResults.innerHTML = '<div class="searchLoading">Restoring search results...</div>';
        doSearch(q, { restore: true });
        return;
    }

    if (searchResults) {
        searchResults.innerHTML = '<div class="searchLoading">Search results are no longer available. Please search again.</div>';
    }
}

function goBack() {
    if (previousView === "nowplaying") {
        goBackToNowPlayingFromAlbum();
        return;
    }
    if (previousView === "search") {
        restoreSearchView();
        restoreDetailReturnScroll("search");
    } else if (previousView === "tidalsource") {
        restoreTidalSourceView();
        restoreDetailReturnScroll("tidalsource");
    } else if (previousView === "playlists") {
        showView("playlists");
        restoreDetailReturnScroll("playlists");
    } else if (previousView === "localmusic") {
        showView("localmusic");
        restoreDetailReturnScroll("localmusic");
    } else if (previousView === "artistpage" && _artistPageRestoreFn) {
        _artistPageRestoreFn();
    } else {
        showView("home");
    }
}


// --- My Playlists view ---

function showPlaylists(setupVerified) {
    if (setupVerified !== true) {
        requireSrovaTidalLogin(function() {
            showPlaylists(true);
        });
        return;
    }
    showView("playlists");
    if (!playlistsLoaded) { loadMyPlaylists(0); }
}


// --- Queue view ---

function showQueue() {
    // Remember which view we came from so the back button works
    if (!nowPlayingView.classList.contains("hidden")) {
        // Came from Now Playing -- store that so back reopens it
        previousQueueView = "nowplaying";
        nowPlayingView.classList.add("hidden");
        document.body.classList.remove("nowPlayingOpen");
    } else if (albumView.style.display !== "none")       { previousQueueView = "album"; }
    else if (searchView.style.display !== "none") { previousQueueView = "search"; }
    else if (playlistsView && playlistsView.style.display !== "none") { previousQueueView = "playlists"; }
    else                                          { previousQueueView = "home"; }
    showView("queue");
    loadQueue();
}

function goBackFromQueue() {
    if (previousQueueView === "nowplaying") {
        showView(nowPlayingFromView);   // restore underlying view first
        openNowPlaying();               // then re-open the Now Playing overlay
    } else {
        showView(previousQueueView);
    }
}


// --- Settings view ---

var _settingsPreviousView = "home";
var _localLibrarySettingsPoll = null;
var LOCAL_LIBRARY_SCAN_ACTIVITY_MIN_MS = 2500;
var currentSettingsTab = "audio";
var _settingsRenderToken = 0;
var _tidalStatusRequestToken = 0;
var srovaUpdateState = null;
var SROVA_VOLUME_SAFETY_DISMISSED_KEY = "srovaVolumeSafetyWarningDismissedV1";
var SROVA_OTHER_AUDIO_OUTPUT_WARNING_VERSION = 1;
var SETTINGS_TABS = [
    { id: "audio", label: "Audio" },
    { id: "tidal", label: "TIDAL" },
    { id: "local", label: "My Music" },
    { id: "radio", label: "Radio" },
    { id: "scrobbling", label: "Scrobbling" },
    { id: "system", label: "System" },
    { id: "about", label: "About" }
];

function showSettings() {
    setGlobalSearchVisible(false);
    // Capture where we came from before showView overwrites anything
    _settingsPreviousView =
        albumView.style.display     !== "none" ? "album"     :
        searchView.style.display    !== "none" ? "search"    :
        playlistsView && playlistsView.style.display !== "none" ? "playlists" :
        queueView && queueView.style.display    !== "none" ? "queue"     :
        myAlbumsView && myAlbumsView.style.display !== "none" ? "myalbums" :
        mySongsView && mySongsView.style.display   !== "none" ? "mysongs"  :
        "home";
    currentSettingsTab = "audio";
    showView("settings");
    renderSettings();
}

function settingsTabExists(tabId) {
    return SETTINGS_TABS.some(function(tab) { return tab.id === tabId; });
}

function setSettingsTab(tabId) {
    if (!settingsTabExists(tabId)) { tabId = "audio"; }
    currentSettingsTab = tabId;
    var tabs = settingsView ? settingsView.querySelectorAll(".settingsTab") : [];
    var panels = settingsView ? settingsView.querySelectorAll(".settingsTabPanel") : [];
    Array.prototype.forEach.call(tabs, function(tab) {
        var active = tab.getAttribute("data-settings-tab") === tabId;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    Array.prototype.forEach.call(panels, function(panel) {
        var active = panel.getAttribute("data-settings-panel") === tabId;
        panel.classList.toggle("active", active);
        panel.hidden = !active;
    });
}

function buildSettingsTabs() {
    var tabs = document.createElement("div");
    tabs.className = "settingsTabs";
    tabs.setAttribute("role", "tablist");
    tabs.setAttribute("aria-label", "Settings sections");
    SETTINGS_TABS.forEach(function(tabDef) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "settingsTab";
        var label = document.createElement("span");
        label.className = "settingsTabLabel";
        label.textContent = tabDef.label;
        btn.appendChild(label);
        btn.setAttribute("role", "tab");
        btn.setAttribute("data-settings-tab", tabDef.id);
        btn.setAttribute("aria-controls", "settings-tab-panel-" + tabDef.id);
        if (tabDef.id === "about") {
            var dot = document.createElement("img");
            dot.className = "srovaUpdateDot settingsTabUpdateDot hidden";
            dot.src = "/ui_web/assets/srova-red-update-dot.png";
            dot.alt = "";
            dot.setAttribute("aria-hidden", "true");
            dot.classList.toggle("hidden", !updateAvailableNow());
            btn.appendChild(dot);
        }
        btn.onclick = function() { setSettingsTab(tabDef.id); };
        tabs.appendChild(btn);
    });
    return tabs;
}

function buildSettingsTabPanels() {
    var wrap = document.createElement("div");
    wrap.className = "settingsTabPanels";
    var panels = {};
    SETTINGS_TABS.forEach(function(tabDef) {
        var panel = document.createElement("div");
        panel.id = "settings-tab-panel-" + tabDef.id;
        panel.className = "settingsTabPanel";
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("data-settings-panel", tabDef.id);
        panel.setAttribute("aria-label", tabDef.label);
        panel.hidden = true;
        panels[tabDef.id] = panel;
        wrap.appendChild(panel);
    });
    return { wrap: wrap, panels: panels };
}

function appendSettingsSections(st, panels) {
    st = st || {};
    panels.audio.appendChild(buildDacSection());
    panels.tidal.appendChild(buildTidalSection({_tidal_status_loading: true}));
    panels.tidal.appendChild(buildAutoMixSection(st));
    panels.tidal.appendChild(buildInfinitePlaySection(st));
    panels.tidal.appendChild(buildPlaylistMaintenanceSection());
    panels.local.appendChild(buildLocalMusicLibrarySection());
    panels.radio.appendChild(buildRadioSection());
    panels.scrobbling.appendChild(buildLastfmSection(st));
    panels.scrobbling.appendChild(buildLbzSection(st));
    panels.system.appendChild(buildSrovaServiceSection());
    panels.system.appendChild(buildRemoteAccessSection());
    panels.about.appendChild(buildAboutSection());
}

function loadAboutVersion(versionEl) {
    if (!versionEl || typeof fetch !== "function") { return; }

    fetch("/api/version?_=" + encodeURIComponent(String(Date.now())), {
        cache: "no-store"
    })
        .then(function(res) {
            if (!res.ok) { throw new Error("Version information unavailable"); }
            return res.json();
        })
        .then(function(data) {
            var displayVersion = String(
                data && data.display_version ? data.display_version : ""
            ).trim();
            if (displayVersion) {
                versionEl.textContent = "Ver " + displayVersion;
            }
        })
        .catch(function() {
            // Keep the neutral placeholder if release metadata cannot be read.
        });
}

function updateAvailableNow() {
    return !!(srovaUpdateState && srovaUpdateState.update_available === true);
}

function syncUpdateIndicators() {
    var available = updateAvailableNow();
    if (settingsUpdateDot) { settingsUpdateDot.classList.toggle("hidden", !available); }
    if (settingsBtn) {
        settingsBtn.title = available ? "Settings — SROVA update available" : "Settings";
        settingsBtn.setAttribute("aria-label", settingsBtn.title);
    }
    var tabDots = settingsView ? settingsView.querySelectorAll(".settingsTabUpdateDot") : [];
    Array.prototype.forEach.call(tabDots, function(dot) {
        dot.classList.toggle("hidden", !available);
    });
}

function checkSrovaUpdate() {
    if (typeof fetch !== "function") { return; }
    fetchWithTimeout("/api/update-status", {cache: "no-store"}, 6000)
        .then(function(res) {
            if (!res.ok) { throw new Error("Update status unavailable"); }
            return res.json();
        })
        .then(function(data) {
            srovaUpdateState = data || null;
            syncUpdateIndicators();
            var about = document.querySelector(".settingsAboutSection");
            if (about) { renderAboutUpdateStatus(about); }
        })
        .catch(function() {
            srovaUpdateState = null;
            syncUpdateIndicators();
        });
}

function renderAboutUpdateStatus(section) {
    if (!section) { return; }
    var previous = section.querySelector(".settingsAboutUpdate");
    if (previous) { previous.remove(); }
    if (!updateAvailableNow()) { return; }

    var latest = String(srovaUpdateState.latest_version || "").trim();
    if (!latest || latest === "unknown") { return; }
    var update = document.createElement("div");
    update.className = "settingsAboutUpdate";

    var message = document.createElement("div");
    message.className = "settingsAboutUpdateMessage";
    message.textContent = "Update available — Version " + latest;
    update.appendChild(message);

    var url = String(srovaUpdateState.download_url || "").trim();
    if (url) {
        var action = document.createElement("a");
        action.className = "settingsBtn settingsAboutUpdateAction";
        action.href = url;
        action.target = "_blank";
        action.rel = "noopener";
        action.textContent = srovaUpdateState.download_kind === "package"
            ? "Download " + String(srovaUpdateState.architecture || "").toUpperCase() + " package"
            : "Open download page";
        update.appendChild(action);
    }
    section.appendChild(update);
}

function buildAboutSection() {
    var sec = document.createElement("div");
    sec.className = "settingsSection settingsAboutSection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle";
    titleRow.innerHTML = '<span class="material-icons">info</span><span class="settingsSectionText">About SROVA</span>';
    sec.appendChild(titleRow);

    var description = document.createElement("div");
    description.className = "settingsSectionDesc settingsAboutDescription";
    description.textContent = "A lightweight, Linux-native audio engine for Tidal, internet radio, and local music, built for audiophiles who want zero UI overhead, a confirmed BP path, and full remote control — without compromise.";
    sec.appendChild(description);

    var version = document.createElement("div");
    version.className = "settingsStatus settingsAboutVersion";
    version.textContent = "Ver …";
    sec.appendChild(version);
    loadAboutVersion(version);

    var websiteRow = document.createElement("div");
    websiteRow.className = "settingsAboutWebsiteRow";

    var websiteIcon = document.createElement("span");
    websiteIcon.className = "material-icons settingsAboutWebsiteIcon";
    websiteIcon.setAttribute("aria-hidden", "true");
    websiteIcon.textContent = "public";
    websiteRow.appendChild(websiteIcon);

    var website = document.createElement("a");
    website.href = "https://srova.music";
    website.target = "_blank";
    website.rel = "noopener";
    website.className = "settingsHelpLink settingsAboutWebsiteLink";
    website.textContent = "srova.music";
    websiteRow.appendChild(website);

    sec.appendChild(websiteRow);

    renderAboutUpdateStatus(sec);

    return sec;
}

function renderSettings() {
    if (!settingsView) { return; }
    var renderToken = ++_settingsRenderToken;
    var statusUrl = "/scrobble/status?_=" + encodeURIComponent(String(Date.now()));
    if (_localLibrarySettingsPoll) {
        clearInterval(_localLibrarySettingsPoll);
        _localLibrarySettingsPoll = null;
    }
    settingsView.innerHTML = "";

    var header = document.createElement("div");
    header.className = "settingsHeader";

    var backBtn = document.createElement("button");
    backBtn.className = "settingsBackBtn";
    backBtn.innerHTML = '<span class="material-icons">arrow_back</span>';
    backBtn.title     = "Back";
    backBtn.onclick   = function() {
        if (_settingsPreviousView === "artistpage" && _artistPageRestoreFn) {
            _artistPageRestoreFn();
        } else {
            showView(_settingsPreviousView);
        }
    };
    header.appendChild(backBtn);

    var title = document.createElement("div");
    title.className   = "settingsTitle";
    title.textContent = "Settings";
    header.appendChild(title);
    settingsView.appendChild(header);

    settingsView.appendChild(buildSettingsTabs());
    var tabPanelData = buildSettingsTabPanels();
    settingsView.appendChild(tabPanelData.wrap);
    setSettingsTab(currentSettingsTab);

    // Fetch current status then render both sections
    fetch(statusUrl, {cache: "no-store"})
        .then(function(res) { return res.json(); })
        .then(function(st) {
            if (renderToken !== _settingsRenderToken) { return; }
            tidalInfinitePlayLastfmConnected = !!(st && st.lastfm_connected);
            updatePlayerInfinitePlayControl();
            appendSettingsSections(st, tabPanelData.panels);
            setSettingsTab(currentSettingsTab);
            refreshTidalSettingsStatus(renderToken);
        })
        .catch(function() {
            if (renderToken !== _settingsRenderToken) { return; }
            appendSettingsSections({}, tabPanelData.panels);
            setSettingsTab(currentSettingsTab);
            refreshTidalSettingsStatus(renderToken);
        });
}

function formatLocalLibraryTime(value) {
    var n = Number(value || 0);
    if (!n) { return "Never"; }
    try {
        return new Date(n * 1000).toLocaleString();
    } catch (e) {
        return "Unknown";
    }
}

function localLibraryStat(stats, key) {
    if (!stats || stats[key] === undefined || stats[key] === null) { return 0; }
    return stats[key];
}

function localLibraryScanCountsText(stats) {
    if (!stats) { return ""; }
    return [
        "Scanned: " + localLibraryStat(stats, "scanned"),
        "Added: " + localLibraryStat(stats, "added"),
        "Updated: " + localLibraryStat(stats, "updated"),
        "Other files ignored: " + localLibraryStat(stats, "unsupported_files_ignored"),
        "Lossy ignored by design: " + localLibraryStat(stats, "lossy_audio_ignored"),
        "Errors: " + (stats.errors ? stats.errors.length : 0)
    ].join(" · ");
}

function managedNetworkShareName(mount) {
    mount = mount && typeof mount === "object" ? mount : {};
    var protocol = String(mount.protocol || "").toLowerCase();
    var source = String(mount.source || "");
    var pathPart = "";
    if (protocol === "smb" && source.indexOf("//") === 0) {
        var smbParts = source.slice(2).split("/").filter(function(part) { return !!part; });
        if (smbParts.length >= 2) { return smbParts[smbParts.length - 1]; }
    } else if (protocol === "nfs") {
        var colonIndex = source.indexOf(":");
        pathPart = colonIndex >= 0 ? source.slice(colonIndex + 1) : "";
        var nfsParts = pathPart.split("/");
        for (var i = nfsParts.length - 1; i >= 0; i--) {
            if (nfsParts[i]) { return nfsParts[i]; }
        }
    }
    if (protocol === "smb") { return "SMB Share"; }
    if (protocol === "nfs") { return "NFS Share"; }
    return "Network Share";
}

function managedNetworkShareDetail(mount) {
    mount = mount && typeof mount === "object" ? mount : {};
    var protocol = String(mount.protocol || "").toLowerCase();
    var protocolLabel = protocol === "smb" ? "SMB" : (protocol === "nfs" ? "NFS" : "Network");
    var source = String(mount.source || "");
    var parts = [protocolLabel];
    if (source) { parts.push(source); }
    parts.push(mount.mounted ? "mounted read-only" : "not mounted");
    return parts.join(" • ");
}

function buildLocalMusicLibrarySection() {
    var sec = document.createElement("div");
    sec.className = "settingsSection localLibrarySettingsSection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle localLibraryOverviewTitle";
    titleRow.innerHTML = '<span class="material-icons">library_music</span><span class="settingsSectionText">My Music Library</span>';
    sec.appendChild(titleRow);

    var desc = document.createElement("div");
    desc.className = "settingsSectionDesc localLibraryOverviewDesc";
    desc.textContent = "SROVA indexes supported lossless music without changing your files.";
    sec.appendChild(desc);

    var formatsNote = document.createElement("div");
    formatsNote.className = "settingsDependencyNote localLibraryInfoNote localLibraryFormatsNote";
    formatsNote.innerHTML = '<span class="material-icons">info</span><span>Supported: FLAC, ALAC/M4A, WAV/WAVE and AIFF/AIF. Lossy formats are ignored.</span>';
    sec.appendChild(formatsNote);

    var localFoldersTitle = document.createElement("div");
    localFoldersTitle.className = "settingsSectionTitle localLibrarySubsectionTitle localLibraryLocalFoldersTitle";
    localFoldersTitle.innerHTML = '<span class="material-icons">folder</span><span class="settingsSectionText">Local Music Folders</span>';
    sec.appendChild(localFoldersTitle);

    var localPathList = document.createElement("div");
    localPathList.className = "localLibraryPathList localLibraryLocalPathList";
    sec.appendChild(localPathList);

    var localAddFolderRow = document.createElement("div");
    localAddFolderRow.className = "localLibraryAddFolderRow";

    var localAddFolderBtn = document.createElement("button");
    localAddFolderBtn.className = "settingsBtn localLibraryAddFolderBtn";
    localAddFolderBtn.type = "button";
    localAddFolderBtn.textContent = "+ Add Folder";
    localAddFolderBtn.title = "Add another local music folder to the same SROVA library.";
    localAddFolderRow.appendChild(localAddFolderBtn);
    sec.appendChild(localAddFolderRow);

    var localHelper = document.createElement("div");
    localHelper.className = "settingsSectionDesc localLibraryHelper";
    localHelper.textContent = "Add music stored on this device or an attached USB drive.";
    sec.appendChild(localHelper);

    var networkFoldersTitle = document.createElement("div");
    networkFoldersTitle.className = "settingsSectionTitle localLibrarySubsectionTitle localLibraryNetworkFoldersTitle";
    networkFoldersTitle.innerHTML = '<span class="material-icons">storage</span><span class="settingsSectionText">Network Music Folders</span>';
    sec.appendChild(networkFoldersTitle);

    var networkPathList = document.createElement("div");
    networkPathList.className = "localLibraryPathList localLibraryNetworkPathList";
    sec.appendChild(networkPathList);

    var networkAddFolderRow = document.createElement("div");
    networkAddFolderRow.className = "localLibraryAddFolderRow";

    var networkAddFolderBtn = document.createElement("button");
    networkAddFolderBtn.className = "settingsBtn localLibraryAddFolderBtn localLibraryAddNetworkFolderBtn";
    networkAddFolderBtn.type = "button";
    networkAddFolderBtn.textContent = "+ Add Network Folder";
    networkAddFolderBtn.title = "Add an already-mounted NAS or network-share folder to the same SROVA library.";
    networkAddFolderRow.appendChild(networkAddFolderBtn);

    var networkDiscoverBtn = document.createElement("button");
    networkDiscoverBtn.className = "settingsBtn localLibraryDiscoverNetworkBtn";
    networkDiscoverBtn.type = "button";
    networkDiscoverBtn.textContent = "Discover Shares";
    networkDiscoverBtn.title = "Discover and connect an NFS or SMB share read-only.";
    networkAddFolderRow.appendChild(networkDiscoverBtn);
    sec.appendChild(networkAddFolderRow);

    var networkHelper = document.createElement("div");
    networkHelper.className = "settingsSectionDesc localLibraryHelper";
    networkHelper.textContent = "Add mounted NAS or network shares. SROVA scans them read-only.";
    sec.appendChild(networkHelper);

    var networkDiscoveryNote = document.createElement("div");
    networkDiscoveryNote.className = "settingsDependencyNote localLibraryInfoNote localLibraryNetworkDiscoveryNote";
    networkDiscoveryNote.innerHTML = '<span class="material-icons">info</span><span>Discovery requires the same network and an NFS or SMB share.</span>';
    sec.appendChild(networkDiscoveryNote);

    var maintenanceTitle = document.createElement("div");
    maintenanceTitle.className = "settingsSectionTitle localLibrarySubsectionTitle localLibraryMaintenanceTitle";
    maintenanceTitle.innerHTML = '<span class="material-icons">build</span><span class="settingsSectionText">Library Maintenance</span>';
    sec.appendChild(maintenanceTitle);

    var maintenanceDesc = document.createElement("div");
    maintenanceDesc.className = "settingsSectionDesc localLibraryMaintenanceDesc";
    maintenanceDesc.textContent = "Save the folders shown above and scan them in one reliable step, or refresh the current status.";
    sec.appendChild(maintenanceDesc);

    var actions = document.createElement("div");
    actions.className = "localLibraryActions localLibraryMaintenanceActions";

    var saveBtn = document.createElement("button");
    saveBtn.className = "settingsBtn";
    saveBtn.textContent = "Save & Scan";
    saveBtn.title = "Validate and save the folders shown above, then scan those saved folders.";
    actions.appendChild(saveBtn);

    var refreshBtn = document.createElement("button");
    refreshBtn.className = "settingsBtn";
    refreshBtn.textContent = "Refresh Status";
    actions.appendChild(refreshBtn);

    var repairLabel = document.createElement("div");
    repairLabel.className = "settingsLabel localLibraryRepairLabel";
    repairLabel.textContent = "Repair Tools";
    actions.appendChild(repairLabel);

    var cleanupBtn = document.createElement("button");
    cleanupBtn.className = "settingsBtn settingsBtnDanger";
    cleanupBtn.textContent = "Cleanup Missing";
    cleanupBtn.title = "Removes missing entries from the SROVA database only, not music files.";
    actions.appendChild(cleanupBtn);

    var rebuildBtn = document.createElement("button");
    rebuildBtn.className = "settingsBtn localLibraryRebuildBtn";
    rebuildBtn.textContent = "Rebuild Library";
    rebuildBtn.title = "Deletes and recreates only SROVA's local library index, then scans configured folders.";
    actions.appendChild(rebuildBtn);
    sec.appendChild(actions);

    var status = document.createElement("div");
    status.className = "settingsStatus localLibraryStatus";
    status.textContent = "Loading local library status...";
    sec.appendChild(status);

    var scanActivity = document.createElement("div");
    scanActivity.className = "localLibraryScanActivity hidden";

    var scanActivityTop = document.createElement("div");
    scanActivityTop.className = "localLibraryScanActivityTop";

    var scanActivityText = document.createElement("div");
    scanActivityText.className = "localLibraryScanActivityText";
    scanActivityTop.appendChild(scanActivityText);

    var scanActivityCounts = document.createElement("div");
    scanActivityCounts.className = "localLibraryScanActivityCounts";
    scanActivityTop.appendChild(scanActivityCounts);

    var scanActivityBar = document.createElement("div");
    scanActivityBar.className = "localLibraryScanActivityBar";
    var scanActivityFill = document.createElement("div");
    scanActivityFill.className = "localLibraryScanActivityFill";
    scanActivityBar.appendChild(scanActivityFill);

    scanActivity.appendChild(scanActivityTop);
    scanActivity.appendChild(scanActivityBar);
    sec.appendChild(scanActivity);

    var statsGrid = document.createElement("div");
    statsGrid.className = "localLibraryStatsGrid";
    sec.appendChild(statsGrid);

    var errorBox = document.createElement("div");
    errorBox.className = "settingsStatus localLibraryErrorBox";
    sec.appendChild(errorBox);

    var dbPath = document.createElement("div");
    dbPath.className = "settingsStatus localLibraryDbPath";
    sec.appendChild(dbPath);

    var scanActivityVisibleUntil = 0;
    var scanActivitySeenRunning = false;
    var scanActivityHideTimer = null;
    var lastLocalLibraryStatusData = null;
    var lastManagedNetworkMounts = [];
    var localLibraryStatusRequestSerial = 0;
    var localLibrarySaveMessage = "";
    var localLibrarySaveMessageUntil = 0;
    var localLibraryPathInputs = [];
    var networkLibraryPathInputs = [];
    var managedDisconnectInFlight = {};
    var localLibraryRootsDirty = false;

    function normalizeLocalLibraryRoots(roots) {
        var clean = [];
        var seen = {};
        if (!Array.isArray(roots)) { roots = []; }
        for (var i = 0; i < roots.length; i++) {
            var value = String(roots[i] || "").trim();
            if (!value || seen[value]) { continue; }
            seen[value] = true;
            clean.push(value);
        }
        return clean;
    }

    function markLocalLibraryRootsUnsaved() {
        localLibraryRootsDirty = true;
        localLibrarySaveMessage = "";
        localLibrarySaveMessageUntil = 0;
        status.textContent = "Folder changes are not saved. Select Save & Scan to accept them.";
    }

    function updateLocalLibraryPathLabels() {
        var rows = localPathList.querySelectorAll(".localLibraryPathRow");
        for (var i = 0; i < rows.length; i++) {
            if (rows[i]._localLibraryLabel) {
                rows[i]._localLibraryLabel.textContent = "Music Folder " + (i + 1);
            }
            if (rows[i]._localLibraryRemoveBtn) {
                rows[i]._localLibraryRemoveBtn.disabled = false;
                rows[i]._localLibraryRemoveBtn.title = "Remove this local music folder row.";
            }
        }

        var networkRows = networkPathList.querySelectorAll(".localLibraryPathRow");
        for (var j = 0; j < networkRows.length; j++) {
            if (networkRows[j]._localLibraryLabel) {
                networkRows[j]._localLibraryLabel.textContent = "Network Folder " + (j + 1);
            }
            if (networkRows[j]._localLibraryRemoveBtn) {
                networkRows[j]._localLibraryRemoveBtn.disabled = false;
                networkRows[j]._localLibraryRemoveBtn.title = "Remove this network music folder row.";
            }
        }
    }

    function addMusicFolderRow(targetList, inputList, value, placeholder) {
        var row = document.createElement("div");
        row.className = "settingsField localLibraryPathField localLibraryPathRow";

        var label = document.createElement("label");
        label.className = "settingsLabel";
        row._localLibraryLabel = label;
        row.appendChild(label);

        var pathInput = document.createElement("input");
        pathInput.className = "settingsInput localLibraryPathInput";
        pathInput.type = "text";
        pathInput.autocomplete = "off";
        pathInput.placeholder = placeholder || "/mnt/music";
        pathInput.value = String(value || "");
        pathInput.addEventListener("input", markLocalLibraryRootsUnsaved);
        row.appendChild(pathInput);

        var browseBtn = document.createElement("button");
        browseBtn.className = "settingsBtn localLibraryBrowseBtn";
        browseBtn.type = "button";
        browseBtn.textContent = "Browse";
        browseBtn.onclick = function() {
            openLocalLibraryFolderBrowser(pathInput);
        };
        row.appendChild(browseBtn);

        var removeBtn = document.createElement("button");
        removeBtn.className = "settingsBtn settingsBtnDanger localLibraryRemoveFolderBtn";
        removeBtn.type = "button";
        removeBtn.textContent = "Remove";
        removeBtn.onclick = function() {
            if (targetList === localPathList && inputList.length <= 1) { return; }
            if (row.parentNode) { row.parentNode.removeChild(row); }
            var idx = inputList.indexOf(pathInput);
            if (idx >= 0) { inputList.splice(idx, 1); }
            updateLocalLibraryPathLabels();
            markLocalLibraryRootsUnsaved();
        };
        row._localLibraryRemoveBtn = removeBtn;
        row.appendChild(removeBtn);

        targetList.appendChild(row);
        inputList.push(pathInput);
        updateLocalLibraryPathLabels();
        return pathInput;
    }

    function addLocalLibraryPathRow(value) {
        return addMusicFolderRow(localPathList, localLibraryPathInputs, value, "/mnt/music");
    }

    function addNetworkLibraryPathRow(value) {
        return addMusicFolderRow(networkPathList, networkLibraryPathInputs, value, "/mnt/nas/Music");
    }

    function disconnectManagedNetworkRoot(mount, button) {
        var mountId = String(mount && mount.id || "");
        if (!mountId || managedDisconnectInFlight[mountId]) { return; }
        if (!window.confirm("Disconnect this managed network share?")) { return; }
        managedDisconnectInFlight[mountId] = true;
        button.disabled = true;
        status.textContent = "Disconnecting managed network share...";
        fetch("/api/local/library/network/disconnect", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({id: mount.id})
        })
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (!data || !data.ok) {
                    throw new Error((data && data.error) || "Could not disconnect managed network share.");
                }
                applyCanonicalMusicRootRows(data);
                var message = "Managed network share disconnected.";
                status.textContent = message;
                if (typeof showQueueActionToast === "function") { showQueueActionToast(message, false); }
                return loadStatus();
            })
            .catch(function(err) {
                var message = (err && err.message) || "Could not disconnect managed network share.";
                status.textContent = message;
                if (typeof showQueueActionToast === "function") { showQueueActionToast(message, true); }
            })
            .then(function() {
                delete managedDisconnectInFlight[mountId];
                if (button && button.parentNode) { button.disabled = false; }
            });
    }

    function addManagedNetworkLibraryPathRow(root, mount) {
        var row = document.createElement("div");
        row.className = "settingsField localLibraryManagedPathRow";

        var display = document.createElement("div");
        display.className = "localLibraryManagedPathDisplay";

        var name = document.createElement("div");
        name.className = "localLibraryManagedPathName";
        name.textContent = managedNetworkShareName(mount);
        display.appendChild(name);

        var detail = document.createElement("div");
        detail.className = "localLibraryManagedPathDetail";
        detail.textContent = managedNetworkShareDetail(mount);
        display.appendChild(detail);
        row.appendChild(display);

        var internalRoot = document.createElement("input");
        internalRoot.className = "localLibraryManagedPathValue";
        internalRoot.type = "hidden";
        internalRoot.value = root;
        row.appendChild(internalRoot);
        networkLibraryPathInputs.push(internalRoot);

        var disconnectBtn = document.createElement("button");
        disconnectBtn.className = "settingsBtn settingsBtnDanger localLibraryManagedDisconnectBtn";
        disconnectBtn.type = "button";
        disconnectBtn.textContent = "Disconnect";
        disconnectBtn.disabled = !!managedDisconnectInFlight[String(mount.id || "")];
        disconnectBtn.onclick = function() { disconnectManagedNetworkRoot(mount, disconnectBtn); };
        row.appendChild(disconnectBtn);

        networkPathList.appendChild(row);
        return internalRoot;
    }

    function setLocalLibraryRows(roots) {
        var clean = normalizeLocalLibraryRoots(roots);
        localPathList.innerHTML = "";
        localLibraryPathInputs = [];
        for (var i = 0; i < clean.length; i++) {
            addLocalLibraryPathRow(clean[i]);
        }
        updateLocalLibraryPathLabels();
    }

    function setNetworkLibraryRows(roots, managedMounts) {
        var clean = normalizeLocalLibraryRoots(roots);
        var mounts = Array.isArray(managedMounts) ? managedMounts : [];
        networkPathList.innerHTML = "";
        networkLibraryPathInputs = [];
        for (var i = 0; i < clean.length; i++) {
            var root = clean[i];
            var matchedMount = null;
            for (var j = 0; j < mounts.length; j++) {
                var mount = mounts[j];
                if (mount && typeof mount === "object" && root === mount.mount_path) {
                    matchedMount = mount;
                    break;
                }
            }
            if (matchedMount) {
                addManagedNetworkLibraryPathRow(root, matchedMount);
            } else {
                addNetworkLibraryPathRow(root);
            }
        }
        updateLocalLibraryPathLabels();
    }

    function applyCanonicalMusicRootRows(data, managedMounts) {
        data = data && typeof data === "object" ? data : {};
        localLibraryRootsDirty = false;
        if (Array.isArray(managedMounts)) {
            lastManagedNetworkMounts = managedMounts.slice();
        }

        var networkRoots = Array.isArray(data.network_roots)
            ? data.network_roots
            : [];
        var configuredRoots = Array.isArray(data.configured_roots)
            ? data.configured_roots
            : (Array.isArray(data.roots) ? data.roots : []);
        var localRoots = Array.isArray(data.local_roots)
            ? data.local_roots
            : configuredRoots.filter(function(root) {
                return networkRoots.indexOf(root) < 0;
            });

        setLocalLibraryRows(localRoots);
        setNetworkLibraryRows(networkRoots, lastManagedNetworkMounts);
    }

    function getRootsFromInputs(inputs) {
        var roots = [];
        var seen = {};
        for (var i = 0; i < inputs.length; i++) {
            var value = String(inputs[i].value || "").trim();
            if (!value || seen[value]) { continue; }
            seen[value] = true;
            roots.push(value);
        }
        return roots;
    }

    function getCombinedLocalLibraryRoots(localRoots, networkRoots) {
        return normalizeLocalLibraryRoots([].concat(localRoots || [], networkRoots || []));
    }

    function saveCurrentMusicRoots(messagePrefix) {
        var localRoots = getRootsFromInputs(localLibraryPathInputs);
        var networkRoots = getRootsFromInputs(networkLibraryPathInputs);
        var roots = getCombinedLocalLibraryRoots(localRoots, networkRoots);
        return fetch("/api/local/library/roots", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({roots: roots, network_roots: networkRoots})
        })
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (!data || !data.ok) {
                    throw new Error((data && data.error) || "Could not save music folders.");
                }
                applyCanonicalMusicRootRows(data);
                var msg = messagePrefix || data.message || "Music folders saved. Select Save & Scan to update the SROVA index.";
                localLibrarySaveMessage = msg;
                localLibrarySaveMessageUntil = Date.now() + 9000;
                status.textContent = msg;
                if (typeof showQueueActionToast === "function") { showQueueActionToast(msg, false); }
                return loadStatus().then(function() { return data; });
            });
    }

    function setBusy(isBusy) {
        saveBtn.disabled = !!isBusy;
        cleanupBtn.disabled = !!isBusy;
        rebuildBtn.disabled = !!isBusy;
        localAddFolderBtn.disabled = !!isBusy;
        networkAddFolderBtn.disabled = !!isBusy;
        networkDiscoverBtn.disabled = !!isBusy;
        var editableControls = sec.querySelectorAll(
            ".localLibraryPathInput, .localLibraryBrowseBtn, .localLibraryRemoveFolderBtn"
        );
        for (var i = 0; i < editableControls.length; i++) {
            editableControls[i].disabled = !!isBusy;
        }
        if (!isBusy) {
            saveBtn.textContent = "Save & Scan";
        } else if (lastLocalLibraryStatusData && lastLocalLibraryStatusData.scan_running) {
            saveBtn.textContent = isLocalLibraryMaintenance(lastLocalLibraryStatusData)
                ? "Rebuilding..."
                : "Scanning...";
        }
    }

    function clearScanActivityHideTimer() {
        if (scanActivityHideTimer) {
            clearTimeout(scanActivityHideTimer);
            scanActivityHideTimer = null;
        }
    }

    function setScanActivityVisibleForMinimum() {
        var until = Date.now() + LOCAL_LIBRARY_SCAN_ACTIVITY_MIN_MS;
        if (until > scanActivityVisibleUntil) { scanActivityVisibleUntil = until; }
    }

    function localLibraryActionErrorMessage(data, fallback) {
        if (data && data.message) { return data.message; }
        if (data && data.error === "network_music_autofs_scan_blocked") {
            return "This Network Music folder uses systemd automount/autofs. Scanning this type of mount is blocked because it can hang the scanner. Please mount the share as a normal NFS/SMB path, then scan again.";
        }
        return (data && data.error) || fallback || "Local Music action failed.";
    }

    function showLocalLibraryActionError(data, fallback) {
        var message = localLibraryActionErrorMessage(data, fallback);
        clearScanActivityHideTimer();
        scanActivitySeenRunning = false;
        scanActivityVisibleUntil = 0;
        scanActivity.classList.add("hidden");
        scanActivity.classList.remove("isRunning");
        scanActivity.classList.remove("isComplete");
        scanActivityText.textContent = "";
        scanActivityCounts.textContent = "";
        status.textContent = message;
        errorBox.textContent = message;
        setBusy(false);
        stopPolling();
        if (typeof showQueueActionToast === "function") { showQueueActionToast(message, true); }
    }

    function renderScanActivity(data, stats) {
        var now = Date.now();
        var isRunning = !!(data && data.scan_running);
        var isRebuild = isLocalLibraryMaintenance(data);
        var keepVisible = isRunning || scanActivitySeenRunning || now < scanActivityVisibleUntil;
        var countsText = localLibraryScanCountsText(stats);
        clearScanActivityHideTimer();

        if (isRunning) {
            scanActivitySeenRunning = true;
            setScanActivityVisibleForMinimum();
            scanActivity.classList.remove("hidden");
            scanActivity.classList.add("isRunning");
            scanActivity.classList.remove("isComplete");
            scanActivityText.textContent = isRebuild ? "Rebuilding library..." : "Scanning library...";
            scanActivityCounts.textContent = countsText;
            return;
        }

        if (scanActivitySeenRunning) {
            setScanActivityVisibleForMinimum();
            scanActivitySeenRunning = false;
            keepVisible = true;
        }

        if (keepVisible) {
            scanActivity.classList.remove("hidden");
            scanActivity.classList.remove("isRunning");
            scanActivity.classList.add("isComplete");
            scanActivityText.textContent = "Scan complete";
            scanActivityCounts.textContent = countsText;
            var delay = Math.max(0, scanActivityVisibleUntil - now);
            scanActivityHideTimer = setTimeout(function() {
                scanActivityVisibleUntil = 0;
                renderScanActivity(lastLocalLibraryStatusData || {}, lastLocalLibraryStatusData && lastLocalLibraryStatusData.last_scan_stats ? lastLocalLibraryStatusData.last_scan_stats : {});
            }, delay);
            return;
        }

        scanActivity.classList.add("hidden");
        scanActivity.classList.remove("isRunning");
        scanActivity.classList.remove("isComplete");
        scanActivityText.textContent = "";
        scanActivityCounts.textContent = "";
    }

    function renderStats(data, managedMounts) {
        lastLocalLibraryStatusData = data || {};
        applyGlobalSearchLocalStatus(data || {});
        var stats = data && data.last_scan_stats ? data.last_scan_stats : {};
        var rows = [
            ["Tracks indexed", data && data.track_count !== undefined && data.track_count !== null ? data.track_count : "Unknown"],
            ["Scanned", localLibraryStat(stats, "scanned")],
            ["Added", localLibraryStat(stats, "added")],
            ["Updated", localLibraryStat(stats, "updated")],
            ["Unchanged", localLibraryStat(stats, "unchanged")],
            ["Other files ignored", localLibraryStat(stats, "unsupported_files_ignored")],
            ["Lossy ignored", localLibraryStat(stats, "lossy_audio_ignored")],
            ["Stale", localLibraryStat(stats, "stale")],
            ["Errors", stats && stats.errors ? stats.errors.length : 0]
        ];
        statsGrid.innerHTML = rows.map(function(row) {
            return '<div class="localLibraryStat"><span>' + row[0] + '</span><strong>' + row[1] + '</strong></div>';
        }).join("");

        var bits = [];
        if (data && data.scan_running) {
            bits.push(isLocalLibraryMaintenance(data) ? "Rebuilding library..." : "Scanning library...");
            if (data.scan_started_at) {
                bits.push("Started " + formatLocalLibraryTime(data.scan_started_at));
            }
        } else if (data && data.last_scan_error) {
            bits.push("Error: " + data.last_scan_error);
        } else if (data && data.last_scan_at) {
            bits.push("Last scan complete");
            bits.push(formatLocalLibraryTime(data.last_scan_at));
        } else {
            bits.push("Ready");
        }
        var statusText = bits.join(" - ");
        if (localLibraryRootsDirty) {
            statusText = "Folder changes are not saved. Select Save & Scan to accept them.";
        } else if (localLibrarySaveMessage && Date.now() < localLibrarySaveMessageUntil) {
            statusText = localLibrarySaveMessage;
        }
        status.textContent = statusText;
        renderScanActivity(data, stats);

        var errors = stats && stats.errors ? stats.errors.slice(0, 3) : [];
        errorBox.innerHTML = "";
        if (errors.length) {
            errors.forEach(function(item) {
                var line = document.createElement("div");
                line.textContent = (item.path || "Unknown path") + ": " + (item.error || "scan error");
                errorBox.appendChild(line);
            });
        } else if (data && data.last_scan_error) {
            errorBox.textContent = data.last_scan_error;
        } else {
            errorBox.textContent = "";
        }

        dbPath.textContent = data && data.db_path ? "DB: " + data.db_path : "";
        if (!localLibraryRootsDirty) {
            applyCanonicalMusicRootRows(data, managedMounts);
        }
        applyLocalLibraryMaintenanceState(data || {});
        setBusy(data && (data.scan_running || isLocalLibraryMaintenance(data)));
    }

    function stopPolling() {
        if (_localLibrarySettingsPoll) {
            clearInterval(_localLibrarySettingsPoll);
            _localLibrarySettingsPoll = null;
        }
    }

    function loadStatus() {
        var requestSerial = ++localLibraryStatusRequestSerial;
        return fetch("/api/local/library/status", {cache: "no-store"})
            .then(function(res) { return res.json(); })
            .then(function(data) {
                return fetch("/api/local/library/network/mounts", {cache: "no-store"})
                    .then(function(res) { return res.json(); })
                    .then(function(mountData) {
                        return mountData && Array.isArray(mountData.mounts) ? mountData.mounts : [];
                    })
                    .catch(function() { return []; })
                    .then(function(managedMounts) {
                        if (requestSerial !== localLibraryStatusRequestSerial) { return data; }
                        renderStats(data || {}, managedMounts);
                        if (data && (data.scan_running || isLocalLibraryMaintenance(data))) {
                            if (!_localLibrarySettingsPoll) {
                                _localLibrarySettingsPoll = setInterval(loadStatus, 2000);
                            }
                        } else {
                            stopPolling();
                        }
                        return data;
                    });
            })
            .catch(function() {
                if (requestSerial !== localLibraryStatusRequestSerial) { return null; }
                status.textContent = "Error loading local library status.";
                stopPolling();
                return null;
            });
    }

    function startSavedMusicRootsScan() {
        setBusy(true);
        saveBtn.textContent = "Starting Scan...";
        status.textContent = "Starting local library scan... SROVA is designed to be a bit-perfect lossless audio player. Supported lossless formats: FLAC, ALAC/M4A, WAV/WAVE and AIFF/AIF. MP3, AAC and other lossy formats are ignored by design.";
        scanActivitySeenRunning = true;
        setScanActivityVisibleForMinimum();
        renderScanActivity({scan_running: true, last_scan_stats: lastLocalLibraryStatusData && lastLocalLibraryStatusData.last_scan_stats}, lastLocalLibraryStatusData && lastLocalLibraryStatusData.last_scan_stats ? lastLocalLibraryStatusData.last_scan_stats : {});
        if (!_localLibrarySettingsPoll) {
            _localLibrarySettingsPoll = setInterval(loadStatus, 2000);
        }
        return fetch("/api/local/library/scan", {method: "POST"})
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (!data || !data.ok) {
                    showLocalLibraryActionError(data, "Could not start scan.");
                    return false;
                }
                saveBtn.textContent = "Scanning...";
                loadStatus();
                return true;
            })
            .catch(function() {
                showLocalLibraryActionError(null, "Could not start scan.");
                return false;
            });
    }

    saveBtn.onclick = function() {
        var localRoots = getRootsFromInputs(localLibraryPathInputs);
        var networkRoots = getRootsFromInputs(networkLibraryPathInputs);
        var roots = getCombinedLocalLibraryRoots(localRoots, networkRoots);
        if (!roots.length) {
            var emptyMessage = "Enter at least one music folder.";
            status.textContent = emptyMessage;
            if (typeof showQueueActionToast === "function") { showQueueActionToast(emptyMessage, true); }
            return;
        }
        setBusy(true);
        saveBtn.textContent = "Saving...";
        status.textContent = "Saving music folders...";
        saveCurrentMusicRoots("Music folders saved. Starting scan...")
            .then(function() {
                return startSavedMusicRootsScan();
            })
            .catch(function(err) {
                var errorMessage = (err && err.message) || "Could not save music folders.";
                localLibraryRootsDirty = true;
                setBusy(false);
                status.textContent = errorMessage;
                if (typeof showQueueActionToast === "function") { showQueueActionToast(errorMessage, true); }
            });
    };

    refreshBtn.onclick = function() {
        status.textContent = "Refreshing local library status...";
        loadStatus();
    };

    function runCleanupMissing() {
        cleanupBtn.disabled = true;
        status.textContent = "Cleaning missing local library entries...";
        fetch("/api/local/library/cleanup-stale", {method: "POST"})
            .then(function(res) { return res.json(); })
            .then(function(data) {
                cleanupBtn.disabled = false;
                if (!data || !data.ok) {
                    showLocalLibraryActionError(data, "Cleanup failed.");
                    return;
                }
                status.textContent = "Cleanup complete. Removed " + (data.deleted || 0) + " missing entries.";
                loadStatus();
            })
            .catch(function() {
                cleanupBtn.disabled = false;
                status.textContent = "Cleanup failed.";
            });
    }

    cleanupBtn.onclick = function() {
        openLocalLibraryCleanupConfirm(runCleanupMissing);
    };

    function runRebuildLibrary() {
        rebuildBtn.disabled = true;
        saveBtn.disabled = true;
        saveBtn.textContent = "Rebuilding...";
        cleanupBtn.disabled = true;
        status.textContent = "Starting local library rebuild...";
        scanActivitySeenRunning = true;
        setScanActivityVisibleForMinimum();
        applyLocalLibraryMaintenanceState({
            rebuild_running: true,
            maintenance_mode: "local_library_rebuild",
            scan_running: true,
            last_scan_stats: lastLocalLibraryStatusData && lastLocalLibraryStatusData.last_scan_stats
        });
        renderScanActivity({scan_running: true, rebuild_running: true, maintenance_mode: "local_library_rebuild"}, lastLocalLibraryStatusData && lastLocalLibraryStatusData.last_scan_stats ? lastLocalLibraryStatusData.last_scan_stats : {});
        if (!_localLibrarySettingsPoll) {
            _localLibrarySettingsPoll = setInterval(loadStatus, 2000);
        }
        fetch("/api/local/library/rebuild", {method: "POST"})
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (!data || !data.ok) {
                    showLocalLibraryActionError(data, "Could not start rebuild.");
                    return;
                }
                loadStatus();
            })
            .catch(function() {
                status.textContent = "Could not start rebuild.";
                rebuildBtn.disabled = false;
            });
    }

    rebuildBtn.onclick = function() {
        openLocalLibraryRebuildConfirm(runRebuildLibrary);
    };

    localAddFolderBtn.onclick = function() {
        var input = addLocalLibraryPathRow("");
        markLocalLibraryRootsUnsaved();
        setTimeout(function() { input.focus(); }, 0);
    };

    networkAddFolderBtn.onclick = function() {
        var input = addNetworkLibraryPathRow("");
        markLocalLibraryRootsUnsaved();
        setTimeout(function() { input.focus(); }, 0);
    };

    networkDiscoverBtn.onclick = function() {
        openNetworkShareDiscoveryModal({
            addNetworkPath: function(path) {
                var existing = getRootsFromInputs(networkLibraryPathInputs);
                if (existing.indexOf(path) < 0) {
                    addNetworkLibraryPathRow(path);
                }
            },
            removeNetworkPath: function(path) {
                for (var i = networkLibraryPathInputs.length - 1; i >= 0; i--) {
                    if (String(networkLibraryPathInputs[i].value || "").trim() === path) {
                        var row = networkLibraryPathInputs[i].closest(".localLibraryPathRow");
                        if (row && row.parentNode) { row.parentNode.removeChild(row); }
                        networkLibraryPathInputs.splice(i, 1);
                    }
                }
                updateLocalLibraryPathLabels();
            },
            reloadStatus: loadStatus,
            setStatus: function(message, isError) {
                status.textContent = message;
                if (typeof showQueueActionToast === "function") { showQueueActionToast(message, !!isError); }
            }
        });
    };

    setLocalLibraryRows([]);
    setNetworkLibraryRows([]);
    loadStatus();
    return sec;
}

function openNetworkShareDiscoveryModal(options) {
    options = options || {};
    var modal = document.createElement("div");
    modal.className = "networkShareModal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    var card = document.createElement("div");
    card.className = "networkShareCard";

    var title = document.createElement("div");
    title.className = "networkShareTitle";
    title.textContent = "Discover Network Shares";
    card.appendChild(title);

    var status = document.createElement("div");
    status.className = "settingsStatus networkShareStatus";
    status.textContent = "Scanning NFS and SMB hosts on your LAN. This is bounded and may take up to 8 seconds.";
    card.appendChild(status);

    var serverList = document.createElement("div");
    serverList.className = "networkShareServerList";
    card.appendChild(serverList);

    var sharePanel = document.createElement("div");
    sharePanel.className = "networkSharePanel";
    card.appendChild(sharePanel);

    var mountsTitle = document.createElement("div");
    mountsTitle.className = "networkShareSubTitle";
    mountsTitle.textContent = "Managed Mounts";
    card.appendChild(mountsTitle);

    var mountsList = document.createElement("div");
    mountsList.className = "networkShareMountsList";
    card.appendChild(mountsList);

    var actions = document.createElement("div");
    actions.className = "localFolderBrowserActions networkShareActions";

    var refreshBtn = document.createElement("button");
    refreshBtn.className = "settingsBtn";
    refreshBtn.type = "button";
    refreshBtn.textContent = "Refresh";
    actions.appendChild(refreshBtn);

    var closeBtn = document.createElement("button");
    closeBtn.className = "settingsBtn settingsBtnDanger";
    closeBtn.type = "button";
    closeBtn.textContent = "Close";
    actions.appendChild(closeBtn);

    card.appendChild(actions);
    modal.appendChild(card);
    document.body.appendChild(modal);

    var selected = null;
    var passwordInput = null;
    var currentCredentials = {};
    var connectInFlight = false;
    var connectButton = null;
    var disconnectInFlight = {};

    function closeModal() {
        if (passwordInput) { passwordInput.value = ""; }
        currentCredentials = {};
        document.removeEventListener("keydown", onKeyDown);
        if (modal.parentNode) { modal.parentNode.removeChild(modal); }
    }

    function onKeyDown(e) {
        if (e.key === "Escape") { closeModal(); }
    }

    function setStatus(text, isError) {
        status.textContent = text;
        status.classList.toggle("networkShareStatusError", !!isError);
    }

    function clearSharePanel() {
        selected = null;
        passwordInput = null;
        connectButton = null;
        sharePanel.innerHTML = "";
    }

    function addText(parent, className, text) {
        var el = document.createElement("div");
        el.className = className;
        el.textContent = text;
        parent.appendChild(el);
        return el;
    }

    function fetchJson(url, fetchOptions) {
        return fetch(url, fetchOptions).then(function(res) { return res.json(); });
    }

    function renderServers(data) {
        serverList.innerHTML = "";
        clearSharePanel();
        var servers = data && Array.isArray(data.servers) ? data.servers : [];
        if (!servers.length) {
            addText(serverList, "networkShareEmpty", "No NFS or SMB servers were discovered.");
            return;
        }
        servers.forEach(function(server) {
            var row = document.createElement("div");
            row.className = "networkShareServerRow";
            var main = document.createElement("div");
            main.className = "networkShareServerMain";
            var name = document.createElement("div");
            name.className = "networkShareServerName";
            name.textContent = server.name ? server.name + " (" + server.host + ")" : server.host;
            main.appendChild(name);
            var proto = document.createElement("div");
            proto.className = "networkShareServerProto";
            proto.textContent = (server.protocols || []).join(" + ").toUpperCase();
            main.appendChild(proto);
            row.appendChild(main);
            (server.protocols || []).forEach(function(protocol) {
                var btn = document.createElement("button");
                btn.className = "settingsBtn";
                btn.type = "button";
                btn.textContent = protocol === "nfs" ? "List NFS" : "List SMB";
                btn.onclick = function() { listShares(server.host, protocol, {}); };
                row.appendChild(btn);
            });
            serverList.appendChild(row);
        });
    }

    function renderAuth(host, protocol, message) {
        clearSharePanel();
        addText(sharePanel, "networkShareSubTitle", "SMB credentials");
        addText(sharePanel, "settingsSectionDesc", message || "This SMB server requires a username and password.");

        var user = document.createElement("input");
        user.className = "settingsInput networkShareInput";
        user.type = "text";
        user.autocomplete = "username";
        user.placeholder = "Username";
        sharePanel.appendChild(user);

        passwordInput = document.createElement("input");
        passwordInput.className = "settingsInput networkShareInput";
        passwordInput.type = "password";
        passwordInput.autocomplete = "current-password";
        passwordInput.placeholder = "Password";
        sharePanel.appendChild(passwordInput);

        var domain = document.createElement("input");
        domain.className = "settingsInput networkShareInput";
        domain.type = "text";
        domain.placeholder = "Domain or workgroup (optional)";
        sharePanel.appendChild(domain);

        var btn = document.createElement("button");
        btn.className = "settingsBtn";
        btn.type = "button";
        btn.textContent = "List SMB Shares";
        btn.onclick = function() {
            listShares(host, protocol, {
                username: user.value,
                password: passwordInput.value,
                domain: domain.value
            });
        };
        sharePanel.appendChild(btn);
        setTimeout(function() { user.focus(); }, 0);
    }

    function renderShares(host, protocol, items) {
        clearSharePanel();
        addText(sharePanel, "networkShareSubTitle", protocol === "nfs" ? "NFS exports" : "SMB disk shares");
        if (!items.length) {
            addText(sharePanel, "networkShareEmpty", "No selectable shares were returned.");
            return;
        }
        function updateShareRowSelection(selectedRow) {
            var rows = sharePanel.querySelectorAll(".networkShareShareRow");
            Array.prototype.forEach.call(rows, function(shareRow) {
                var isSelected = shareRow === selectedRow;
                shareRow.classList.toggle("networkShareShareRowSelected", isSelected);
                shareRow.setAttribute("aria-pressed", isSelected ? "true" : "false");
                var shareHint = shareRow.querySelector(".networkShareShareHint");
                if (shareHint) { shareHint.textContent = isSelected ? "Selected" : "Select"; }
            });
        }
        items.forEach(function(item) {
            var row = document.createElement("button");
            row.className = "networkShareShareRow";
            row.type = "button";
            row.setAttribute("aria-pressed", "false");
            var label = document.createElement("span");
            label.textContent = protocol === "nfs" ? item.path : item.name;
            row.appendChild(label);
            var hint = document.createElement("span");
            hint.className = "networkShareShareHint";
            hint.textContent = "Select";
            row.appendChild(hint);
            row.onclick = function() {
                updateShareRowSelection(row);
                selected = {host: host, protocol: protocol, value: protocol === "nfs" ? item.path : item.name};
                renderConnect();
            };
            sharePanel.appendChild(row);
        });
    }

    function renderConnect() {
        var existing = sharePanel.querySelector(".networkShareConnectBox");
        if (existing && existing.parentNode) { existing.parentNode.removeChild(existing); }
        if (!selected) { return; }
        var box = document.createElement("div");
        box.className = "networkShareConnectBox";
        addText(box, "settingsSectionDesc", "Connect this share read-only and add it as a Network Music Folder.");
        connectButton = document.createElement("button");
        connectButton.className = "settingsBtn";
        connectButton.type = "button";
        connectButton.textContent = "Connect & Add";
        connectButton.disabled = connectInFlight;
        connectButton.onclick = connectSelected;
        box.appendChild(connectButton);
        sharePanel.appendChild(box);
    }

    function listShares(host, protocol, credentials) {
        currentCredentials = credentials || {};
        setStatus("Listing " + protocol.toUpperCase() + " shares on " + host + "...", false);
        fetchJson("/api/local/library/network/shares", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({host: host, protocol: protocol, credentials: credentials || {}})
        }).then(function(data) {
            if (!data || !data.ok) {
                if (protocol === "smb" && (!credentials || !credentials.username) && data && data.auth_required) {
                    renderAuth(host, protocol, data.error);
                    setStatus("SMB authentication is required.", false);
                    return;
                }
                setStatus((data && data.error) || "Could not list shares.", true);
                return;
            }
            var items = protocol === "nfs" ? (data.exports || []) : (data.shares || []);
            renderShares(host, protocol, items);
            setStatus("Choose one share, then connect it read-only.", false);
        }).catch(function() {
            setStatus("Could not list network shares.", true);
        });
    }

    function connectSelected() {
        if (!selected || connectInFlight) { return; }
        connectInFlight = true;
        if (connectButton) { connectButton.disabled = true; }
        var payload = {host: selected.host, protocol: selected.protocol};
        if (selected.protocol === "nfs") {
            payload.export = selected.value;
        } else {
            payload.share = selected.value;
            payload.username = currentCredentials.username || "";
            payload.password = currentCredentials.password || "";
            payload.domain = currentCredentials.domain || "";
        }
        setStatus("Connecting share read-only...", false);
        fetchJson("/api/local/library/network/connect", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload)
        }).then(function(data) {
            if (!data || !data.ok) {
                setStatus((data && data.error) || "Could not connect share.", true);
                return;
            }
            if (options.addNetworkPath && data.mount_path) { options.addNetworkPath(data.mount_path); }
            var message = "Share connected read-only. Select Save & Scan to update the SROVA index.";
            setStatus(message, false);
            if (options.setStatus) { options.setStatus(message, false); }
            if (options.reloadStatus) { options.reloadStatus(); }
            loadMounts();
        }).catch(function() {
            setStatus("Could not connect share.", true);
        }).then(function() {
            if (passwordInput) { passwordInput.value = ""; }
            currentCredentials.password = "";
            connectInFlight = false;
            if (connectButton) { connectButton.disabled = false; }
        });
    }

    function renderMounts(data) {
        mountsList.innerHTML = "";
        var mounts = data && Array.isArray(data.mounts) ? data.mounts : [];
        if (!mounts.length) {
            addText(mountsList, "networkShareEmpty", "No managed mounts yet.");
            return;
        }
        mounts.forEach(function(mount) {
            var row = document.createElement("div");
            row.className = "networkShareMountRow";
            var info = document.createElement("div");
            info.className = "networkShareMountInfo";
            addText(info, "networkShareMountSource", managedNetworkShareName(mount));
            addText(info, "networkShareMountDetail", managedNetworkShareDetail(mount));
            row.appendChild(info);
            var btn = document.createElement("button");
            btn.className = "settingsBtn settingsBtnDanger";
            btn.type = "button";
            btn.textContent = "Disconnect";
            btn.disabled = !!disconnectInFlight[mount.id];
            btn.onclick = function() { disconnectMount(mount, btn, row); };
            row.appendChild(btn);
            mountsList.appendChild(row);
        });
    }

    function loadMounts() {
        fetchJson("/api/local/library/network/mounts").then(renderMounts).catch(function() {
            mountsList.innerHTML = "";
            addText(mountsList, "networkShareEmpty", "Could not load managed mounts.");
        });
    }

    function disconnectMount(mount, button, row) {
        if (disconnectInFlight[mount.id]) { return; }
        if (!window.confirm("Disconnect this managed network share?")) { return; }
        disconnectInFlight[mount.id] = true;
        if (button) { button.disabled = true; }
        setStatus("Disconnecting managed mount...", false);
        fetchJson("/api/local/library/network/disconnect", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({id: mount.id})
        }).then(function(data) {
            if (!data || !data.ok) {
                setStatus((data && data.error) || "Could not disconnect mount.", true);
                return;
            }
            if (options.removeNetworkPath && data.mount_path) { options.removeNetworkPath(data.mount_path); }
            if (row && row.parentNode) { row.parentNode.removeChild(row); }
            var message = "Managed network share disconnected.";
            setStatus(message, false);
            if (options.setStatus) { options.setStatus(message, false); }
            if (options.reloadStatus) { options.reloadStatus(); }
            loadMounts();
        }).catch(function() {
            setStatus("Could not disconnect mount.", true);
        }).then(function() {
            delete disconnectInFlight[mount.id];
            if (button && button.parentNode) { button.disabled = false; }
        });
    }

    function discover(refresh) {
        serverList.innerHTML = "";
        clearSharePanel();
        addText(serverList, "networkShareEmpty", "Scanning NFS port 2049 and SMB port 445. This scan is capped and time-bounded.");
        setStatus("Scanning network shares...", false);
        fetchJson("/api/local/library/network/discover" + (refresh ? "?refresh=1" : "")).then(function(data) {
            if (!data || !data.ok) {
                setStatus((data && data.error) || "Network discovery failed.", true);
                return;
            }
            setStatus("Discovery complete. " + (data.servers || []).length + " server(s) found.", false);
            renderServers(data);
        }).catch(function() {
            setStatus("Network discovery failed.", true);
        });
    }

    refreshBtn.onclick = function() { discover(true); loadMounts(); };
    closeBtn.onclick = closeModal;
    modal.addEventListener("click", function(e) {
        if (e.target === modal) { closeModal(); }
    });
    document.addEventListener("keydown", onKeyDown);
    discover(false);
    loadMounts();
}

function openLocalLibraryCleanupConfirm(onConfirm) {
    var modal = document.createElement("div");
    modal.className = "localLibraryCleanupModal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "localLibraryCleanupTitle");
    modal.setAttribute("aria-describedby", "localLibraryCleanupBody");

    var card = document.createElement("div");
    card.className = "localLibraryCleanupCard";

    var title = document.createElement("div");
    title.id = "localLibraryCleanupTitle";
    title.className = "localLibraryCleanupTitle";
    title.textContent = "Cleanup missing local tracks?";
    card.appendChild(title);

    var body = document.createElement("div");
    body.id = "localLibraryCleanupBody";
    body.className = "localLibraryCleanupBody";
    body.textContent = "SROVA will remove missing/stale entries from its local library database. Your music files and folders will not be deleted or modified. This is useful after moving, deleting, or replacing albums outside SROVA.";
    card.appendChild(body);

    var actions = document.createElement("div");
    actions.className = "localLibraryCleanupActions";

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "settingsBtn";
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";
    actions.appendChild(cancelBtn);

    var confirmBtn = document.createElement("button");
    confirmBtn.className = "settingsBtn settingsBtnDanger localLibraryCleanupConfirm";
    confirmBtn.type = "button";
    confirmBtn.textContent = "Cleanup Missing";
    actions.appendChild(confirmBtn);

    card.appendChild(actions);
    modal.appendChild(card);
    document.body.appendChild(modal);

    function closeModal() {
        document.removeEventListener("keydown", onKeyDown);
        if (modal.parentNode) { modal.parentNode.removeChild(modal); }
    }

    function onKeyDown(e) {
        if (e.key === "Escape") { closeModal(); }
    }

    cancelBtn.onclick = closeModal;
    confirmBtn.onclick = function() {
        closeModal();
        if (typeof onConfirm === "function") { onConfirm(); }
    };
    modal.addEventListener("click", function(e) {
        if (e.target === modal) { closeModal(); }
    });
    document.addEventListener("keydown", onKeyDown);
    setTimeout(function() { cancelBtn.focus(); }, 0);
}

function openLocalLibraryRebuildConfirm(onConfirm) {
    var modal = document.createElement("div");
    modal.className = "localLibraryCleanupModal localLibraryRebuildModal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "localLibraryRebuildTitle");
    modal.setAttribute("aria-describedby", "localLibraryRebuildBody");

    var card = document.createElement("div");
    card.className = "localLibraryCleanupCard localLibraryRebuildCard";

    var title = document.createElement("div");
    title.id = "localLibraryRebuildTitle";
    title.className = "localLibraryCleanupTitle";
    title.textContent = "Rebuild Local Music Library?";
    card.appendChild(title);

    var body = document.createElement("div");
    body.id = "localLibraryRebuildBody";
    body.className = "localLibraryCleanupBody";
    [
        "This will delete and recreate SROVA’s local library index, then perform a fresh scan from your configured music folders.",
        "Your music files and folders will not be modified. Nothing will be written into your music library.",
        "This may take some time depending on the size of your collection.",
        "Please do not use Local Music until the rebuild finishes.",
        "SROVA is designed to be a bit-perfect lossless audio player. Supported lossless formats: FLAC, ALAC/M4A, WAV/WAVE and AIFF/AIF. MP3, AAC and other lossy formats are ignored by design.",
        "Continue?"
    ].forEach(function(text) {
        var p = document.createElement("p");
        p.textContent = text;
        body.appendChild(p);
    });
    card.appendChild(body);

    var actions = document.createElement("div");
    actions.className = "localLibraryCleanupActions";

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "settingsBtn";
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";
    actions.appendChild(cancelBtn);

    var confirmBtn = document.createElement("button");
    confirmBtn.className = "settingsBtn localLibraryRebuildConfirm";
    confirmBtn.type = "button";
    confirmBtn.textContent = "Rebuild Library";
    actions.appendChild(confirmBtn);

    card.appendChild(actions);
    modal.appendChild(card);
    document.body.appendChild(modal);

    function closeModal() {
        document.removeEventListener("keydown", onKeyDown);
        if (modal.parentNode) { modal.parentNode.removeChild(modal); }
    }

    function onKeyDown(e) {
        if (e.key === "Escape") { closeModal(); }
    }

    cancelBtn.onclick = closeModal;
    confirmBtn.onclick = function() {
        closeModal();
        if (typeof onConfirm === "function") { onConfirm(); }
    };
    modal.addEventListener("click", function(e) {
        if (e.target === modal) { closeModal(); }
    });
    document.addEventListener("keydown", onKeyDown);
    setTimeout(function() { cancelBtn.focus(); }, 0);
}

function openLocalLibraryFolderBrowser(pathInput) {
    var modal = document.createElement("div");
    modal.className = "localFolderBrowserModal";
    modal.setAttribute("aria-hidden", "false");

    var card = document.createElement("div");
    card.className = "localFolderBrowserCard";

    var title = document.createElement("div");
    title.className = "localFolderBrowserTitle";
    title.textContent = "Choose Music Folder";
    card.appendChild(title);

    var current = document.createElement("div");
    current.className = "localFolderBrowserCurrent";
    current.textContent = "Loading folders...";
    card.appendChild(current);

    var list = document.createElement("div");
    list.className = "localFolderBrowserList";
    card.appendChild(list);

    var error = document.createElement("div");
    error.className = "settingsStatus localFolderBrowserError";
    card.appendChild(error);

    var actions = document.createElement("div");
    actions.className = "localFolderBrowserActions";

    var backBtn = document.createElement("button");
    backBtn.className = "settingsBtn";
    backBtn.textContent = "Back";
    actions.appendChild(backBtn);

    var selectBtn = document.createElement("button");
    selectBtn.className = "settingsBtn";
    selectBtn.textContent = "Select This Folder";
    actions.appendChild(selectBtn);

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "settingsBtn settingsBtnDanger";
    cancelBtn.textContent = "Cancel";
    actions.appendChild(cancelBtn);
    card.appendChild(actions);

    modal.appendChild(card);
    document.body.appendChild(modal);

    var currentPath = null;
    var parentPath = null;

    function closeModal() {
        if (modal.parentNode) { modal.parentNode.removeChild(modal); }
    }

    function setLoading(text) {
        list.innerHTML = "";
        error.textContent = "";
        current.textContent = text || "Loading folders...";
        backBtn.disabled = true;
        selectBtn.disabled = true;
    }

    function addEmpty(text) {
        var empty = document.createElement("div");
        empty.className = "localFolderBrowserEmpty";
        empty.textContent = text;
        list.appendChild(empty);
    }

    function addFolderRow(item, isRoot) {
        var row = document.createElement("button");
        row.className = "localFolderBrowserRow";
        row.type = "button";
        if (item.readable === false) {
            row.className += " localFolderBrowserRowDisabled";
            row.disabled = true;
        }
        var name = document.createElement("span");
        name.className = "localFolderBrowserName";
        name.textContent = item.name || item.path || "Folder";
        row.appendChild(name);
        var hint = document.createElement("span");
        hint.className = "localFolderBrowserHint";
        hint.textContent = item.readable === false ? "Unavailable" : (isRoot ? "Mounted/readable" : "Open");
        row.appendChild(hint);
        row.onclick = function() {
            if (item.path) { loadPath(item.path); }
        };
        list.appendChild(row);
    }

    function render(data) {
        list.innerHTML = "";
        error.textContent = "";
        currentPath = data && data.path ? data.path : null;
        parentPath = data && data.parent ? data.parent : null;
        backBtn.disabled = !currentPath;
        selectBtn.disabled = !currentPath;

        if (!data || !data.ok) {
            current.textContent = "Folder Browser";
            error.textContent = (data && data.error) || "Could not load folders.";
            addEmpty("No folders found here.");
            return;
        }

        if (!currentPath) {
            current.textContent = "Safe browse roots";
            var roots = data.roots || [];
            if (!roots.length) {
                addEmpty("No allowed browse roots are available.");
                return;
            }
            roots.forEach(function(item) { addFolderRow(item, true); });
            return;
        }

        current.textContent = currentPath;
        var dirs = data.directories || [];
        if (!dirs.length) {
            addEmpty("No folders found here.");
            return;
        }
        dirs.forEach(function(item) { addFolderRow(item, false); });
    }

    function loadPath(path) {
        setLoading(path ? "Loading " + path + "..." : "Loading safe browse roots...");
        var url = "/api/local/library/browse";
        if (path) { url += "?path=" + encodeURIComponent(path); }
        fetch(url)
            .then(function(res) { return res.json(); })
            .then(function(data) { render(data || {}); })
            .catch(function() {
                render({ok: false, error: "Could not load server folders."});
            });
    }

    backBtn.onclick = function() {
        if (parentPath) {
            loadPath(parentPath);
        } else {
            loadPath("");
        }
    };

    selectBtn.onclick = function() {
        if (currentPath && pathInput) {
            pathInput.value = currentPath;
            pathInput.dispatchEvent(new Event("input", {bubbles: true}));
        }
        closeModal();
    };

    cancelBtn.onclick = closeModal;
    modal.addEventListener("click", function(e) {
        if (e.target === modal) { closeModal(); }
    });

    var initial = pathInput && pathInput.value ? pathInput.value.trim() : "";
    loadPath(initial || "");
}

function buildScrobblingSignupLink(href, text, extraClassName) {
    var link = document.createElement("a");
    link.href        = href;
    link.target      = "_blank";
    link.rel         = "noopener";
    link.className   = "settingsHelpLink settingsSignupLink " + extraClassName;
    link.textContent = text;
    return link;
}

function buildLastfmSection(st) {
    var sec = document.createElement("div");
    sec.className = "settingsSection settingsLastfmSection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle settingsSectionTitleLastfm";
    titleRow.setAttribute("data-settings-title", "Last.fm");
    titleRow.innerHTML = '<span class="material-icons">music_note</span><span class="settingsSectionText">Last.fm</span>'; 
    sec.appendChild(titleRow);

    var benefits = document.createElement("div");
    benefits.className = "settingsLastfmBenefits";

    var benefitsTitle = document.createElement("div");
    benefitsTitle.className = "settingsLastfmBenefitsTitle";
    benefitsTitle.textContent = "Get more from SROVA with Last.fm";
    benefits.appendChild(benefitsTitle);

    var benefitsDesc = document.createElement("div");
    benefitsDesc.className = "settingsSectionDesc settingsLastfmBenefitsDesc";
    benefitsDesc.textContent = "Creating and connecting a free Last.fm account is a quick, one-time setup that unlocks additional features across SROVA:";
    benefits.appendChild(benefitsDesc);

    var benefitsList = document.createElement("ul");
    benefitsList.className = "settingsLastfmBenefitsList";
    [
        "See automatic song artwork while listening to Internet Radio",
        "Discover new music with Auto-Mix and Infinite Play",
        "Scrobble everything you play from TIDAL, My Music and Internet Radio"
    ].forEach(function(text) {
        var item = document.createElement("li");
        item.textContent = text;
        benefitsList.appendChild(item);
    });
    benefits.appendChild(benefitsList);

    if (!st.lastfm_connected) {
        var signupLink = buildScrobblingSignupLink(
            "https://www.last.fm/join",
            "Create a free Last.fm account",
            "settingsLastfmSignupLink"
        );
        benefits.appendChild(signupLink);
    }

    sec.appendChild(benefits);

    if (st.lastfm_connected) {
        var info = document.createElement("div");
        info.className   = "settingsConnected";
        info.textContent = "Connected as " + (st.lastfm_username || "");
        sec.appendChild(info);
        var dis = document.createElement("button");
        dis.className   = "settingsBtn settingsBtnDanger";
        dis.textContent = "Disconnect";
        dis.onclick = function() {
            fetch("/scrobble/lastfm/disconnect").then(function() { renderSettings(); });
        };
        sec.appendChild(dis);
    } else {
        var desc = document.createElement("div");
        desc.className   = "settingsSectionDesc";
        desc.textContent = "Enter your Last.fm credentials and API key to enable scrobbling.";
        sec.appendChild(desc);

        var flds = [
            { id: "lfmUser",   label: "Username",   type: "text",     ph: "Last.fm username"   },
            { id: "lfmPass",   label: "Password",   type: "password", ph: "Last.fm password"   },
            { id: "lfmKey",    label: "API Key",    type: "text",     ph: "API key"             },
            { id: "lfmSecret", label: "API Secret", type: "password", ph: "API secret"          }
        ];
        flds.forEach(function(f) {
            var row = document.createElement("div");
            row.className = "settingsField";
            var lbl = document.createElement("label");
            lbl.className   = "settingsLabel";
            lbl.textContent = f.label;
            var inp = document.createElement("input");
            inp.id          = f.id;
            inp.type        = f.type;
            inp.placeholder = f.ph;
            inp.className   = "settingsInput";
            row.appendChild(lbl);
            row.appendChild(inp);
            sec.appendChild(row);
        });

        var status = document.createElement("div");
        status.className = "settingsStatus";
        sec.appendChild(status);

        var btn = document.createElement("button");
        btn.className   = "settingsBtn";
        btn.textContent = "Connect";
        btn.onclick = function() {
            var u  = document.getElementById("lfmUser").value.trim();
            var p  = document.getElementById("lfmPass").value.trim();
            var k  = document.getElementById("lfmKey").value.trim();
            var s  = document.getElementById("lfmSecret").value.trim();
            if (!u || !p || !k || !s) { status.textContent = "All fields required."; return; }
            btn.disabled     = true;
            btn.textContent  = "Connecting...";
            status.textContent = "";
            fetch("/scrobble/lastfm/connect", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: u, password: p, api_key: k, api_secret: s })
            })
            .then(function(res) { return res.json(); })
            .then(function() {
                status.textContent = "Connecting... checking in 3s";
                setTimeout(function() { renderSettings(); }, 3000);
            })
            .catch(function() {
                status.textContent = "Connection failed. Check your credentials.";
                btn.disabled    = false;
                btn.textContent = "Connect";
            });
        };
        sec.appendChild(btn);
    }
    return sec;
}

function buildLbzSection(st) {
    var sec = document.createElement("div");
    sec.className = "settingsSection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle";
    titleRow.innerHTML = '<span class="material-icons">headphones</span> ListenBrainz';
    sec.appendChild(titleRow);

    if (st.lbz_connected) {
        var info = document.createElement("div");
        info.className   = "settingsConnected";
        info.textContent = "Connected as " + (st.lbz_username || "");
        sec.appendChild(info);
        var dis = document.createElement("button");
        dis.className   = "settingsBtn settingsBtnDanger";
        dis.textContent = "Disconnect";
        dis.onclick = function() {
            fetch("/scrobble/lbz/disconnect").then(function() { renderSettings(); });
        };
        sec.appendChild(dis);
    } else {
        var desc = document.createElement("div");
        desc.className   = "settingsSectionDesc";
        desc.textContent = "Paste your ListenBrainz user token to enable scrobbling.";
        sec.appendChild(desc);

        var signupLink = buildScrobblingSignupLink(
            "https://musicbrainz.org/register?returnto=%2F",
            "Create a free MusicBrainz account for ListenBrainz",
            "settingsListenBrainzSignupLink"
        );
        sec.appendChild(signupLink);

        var row = document.createElement("div");
        row.className = "settingsField";
        var lbl = document.createElement("label");
        lbl.className   = "settingsLabel";
        lbl.textContent = "User Token";
        var inp = document.createElement("input");
        inp.id          = "lbzToken";
        inp.type        = "password";
        inp.placeholder = "Paste token from listenbrainz.org/profile";
        inp.className   = "settingsInput";
        row.appendChild(lbl);
        row.appendChild(inp);
        sec.appendChild(row);

        var status = document.createElement("div");
        status.className = "settingsStatus";
        sec.appendChild(status);

        var btn = document.createElement("button");
        btn.className   = "settingsBtn";
        btn.textContent = "Connect";
        btn.onclick = function() {
            var t = document.getElementById("lbzToken").value.trim();
            if (!t) { status.textContent = "Token required."; return; }
            btn.disabled    = true;
            btn.textContent = "Connecting...";
            status.textContent = "";
            fetch("/scrobble/lbz/connect", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ token: t })
            })
            .then(function(res) { return res.json(); })
            .then(function() {
                status.textContent = "Connecting... checking in 3s";
                setTimeout(function() { renderSettings(); }, 3000);
            })
            .catch(function() {
                status.textContent = "Connection failed. Check your token.";
                btn.disabled    = false;
                btn.textContent = "Connect";
            });
        };
        sec.appendChild(btn);
    }
    return sec;
}


function buildTidalSection(st) {
    st = st || {};
    var sec = document.createElement("div");
    sec.className = "settingsSection tidalAccountSettingsSection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle";
    titleRow.innerHTML = '<span class="material-icons">account_circle</span> Tidal Account';
    sec.appendChild(titleRow);

    var loggedIn =
        typeof st.tidal_logged_in === "boolean" ? st.tidal_logged_in :
        typeof st.logged_in === "boolean" ? st.logged_in :
        null;

    if (st._tidal_status_loading) {
        var loading = document.createElement("div");
        loading.className = "settingsSectionDesc";
        loading.textContent = "Checking TIDAL login status...";
        sec.appendChild(loading);
    } else if (st._tidal_status_error) {
        var error = document.createElement("div");
        error.className = "settingsSectionDesc";
        error.textContent = st._tidal_status_message || "TIDAL is unavailable. Local Music remains available.";
        sec.appendChild(error);
    } else if (loggedIn === true) {
        var info = document.createElement("div");
        info.className   = "settingsConnected";
        var tidalUsername = String(st.tidal_username || st.username || "").trim();
        var tidalDisplayName = tidalUsername.indexOf("@") >= 0 ? tidalUsername.split("@")[0].trim() : tidalUsername;
        info.textContent = tidalDisplayName ? ("Logged in as " + tidalDisplayName) : "Logged in";
        sec.appendChild(info);
        var btn = document.createElement("button");
        btn.className   = "settingsBtn settingsBtnDanger";
        btn.textContent = "Logout";
        btn.onclick = function() { doLogout({returnToSettings: true}); };
        sec.appendChild(btn);
    } else if (loggedIn === false) {
        var desc = document.createElement("div");
        desc.className   = "settingsSectionDesc";
        desc.textContent = "Not logged in to Tidal.";
        sec.appendChild(desc);
        var btn = document.createElement("button");
        btn.className   = "settingsBtn";
        btn.textContent = "Login";
        btn.onclick = function() { startLogin({returnToSettings: true}); };
        sec.appendChild(btn);
    } else {
        var unknown = document.createElement("div");
        unknown.className = "settingsSectionDesc";
        unknown.textContent = "Checking TIDAL login status...";
        sec.appendChild(unknown);
    }
    return sec;
}

function updateTidalSettingsSection(st) {
    if (!settingsView) { return; }
    var panel = settingsView.querySelector('[data-settings-panel="tidal"]');
    if (!panel) { return; }
    var current = panel.querySelector(".tidalAccountSettingsSection");
    var next = buildTidalSection(st || {_tidal_status_loading: true});
    if (current && current.parentNode === panel) {
        panel.replaceChild(next, current);
    } else {
        panel.insertBefore(next, panel.firstChild);
    }
}

function refreshTidalSettingsStatus(renderToken) {
    if (!settingsView || settingsView.style.display === "none") { return; }
    var requestToken = ++_tidalStatusRequestToken;
    var expectedRenderToken = renderToken || _settingsRenderToken;
    var url = "/tidal/status?_=" + encodeURIComponent(String(Date.now()));

    updateTidalSettingsSection({_tidal_status_loading: true});

    fetchWithTimeout(url, {cache: "no-store"}, 4000)
        .then(function(res) {
            if (!res.ok) { throw new Error("TIDAL status unavailable"); }
            return res.json();
        })
        .then(function(st) {
            if (requestToken !== _tidalStatusRequestToken || expectedRenderToken !== _settingsRenderToken) { return; }
            st = st || {};
            if (st.offline) {
                updateLoginBtn(false, {skipSettingsRefresh: true});
                updateTidalSettingsSection({
                    _tidal_status_error: true,
                    _tidal_status_message: st.error || "TIDAL is unavailable. Local Music remains available."
                });
                return;
            }
            if (typeof st.logged_in === "boolean") {
                updateLoginBtn(st.logged_in, {skipSettingsRefresh: true});
            }
            updateTidalSettingsSection(st);
        })
        .catch(function() {
            if (requestToken !== _tidalStatusRequestToken || expectedRenderToken !== _settingsRenderToken) { return; }
            updateTidalSettingsSection({
                _tidal_status_error: true,
                _tidal_status_message: "TIDAL is unavailable. Local Music remains available."
            });
        });
}



function _escapeText(v) {
    return String(v == null ? "" : v)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function srovaVolumeSafetyDismissed() {
    try {
        return localStorage.getItem(SROVA_VOLUME_SAFETY_DISMISSED_KEY) === "1";
    } catch (e) {
        return false;
    }
}

function setSrovaVolumeSafetyDismissed() {
    try {
        localStorage.setItem(SROVA_VOLUME_SAFETY_DISMISSED_KEY, "1");
    } catch (e) {}
}

function buildSrovaVolumeSafetyPanel(compact) {
    var panel = document.createElement("div");
    panel.className = "srovaVolumeSafetyWarning" + (compact ? " srovaVolumeSafetyWarningCompact" : "");
    panel.setAttribute("role", compact ? "note" : "alertdialog");
    if (!compact) {
        panel.setAttribute("aria-modal", "true");
        panel.setAttribute("aria-labelledby", "srovaVolumeSafetyTitle");
    }

    var icon = document.createElement("div");
    icon.className = "srovaVolumeSafetyIcon";
    icon.textContent = "\u26A0";
    panel.appendChild(icon);

    var body = document.createElement("div");
    body.className = "srovaVolumeSafetyBody";

    var title = document.createElement(compact ? "div" : "h2");
    title.className = "srovaVolumeSafetyTitle";
    if (!compact) { title.id = "srovaVolumeSafetyTitle"; }
    title.textContent = compact ? "Volume Safety Warning" : "SROVA Volume Safety Warning";
    body.appendChild(title);

    var summary = document.createElement("p");
    summary.className = "srovaVolumeSafetySummary";
    summary.textContent = compact ?
        "SROVA uses exclusive DAC output at fixed 100% digital volume. OS, device, browser, PWA, or software volume controls may not work and should not be relied on to control playback volume." :
        "SROVA takes exclusive control of the DAC and outputs fixed 100% digital volume.";
    body.appendChild(summary);

    if (compact) {
        var compactDetail = document.createElement("p");
        compactDetail.textContent = "Use only with hardware volume control downstream before speakers or headphones.";
        body.appendChild(compactDetail);
    } else {
        var list = document.createElement("ul");
        [
            "PC, laptop, phone, tablet, browser, PWA, OS, or software volume controls may not control playback volume.",
            "You must have hardware volume control in the DAC, amplifier, powered speaker, or headphone chain before speakers or headphones.",
            "Do not use SROVA with DACs or audio devices that have no hardware volume control.",
            "Risk: speaker damage and/or hearing damage."
        ].forEach(function(text) {
            var item = document.createElement("li");
            item.textContent = text;
            list.appendChild(item);
        });
        body.appendChild(list);
    }

    panel.appendChild(body);
    return panel;
}

function showSrovaVolumeSafetyModal() {
    if (srovaVolumeSafetyDismissed() || document.getElementById("srovaVolumeSafetyModal")) { return; }

    var modal = document.createElement("div");
    modal.id = "srovaVolumeSafetyModal";
    modal.className = "srovaVolumeSafetyModal";

    var card = buildSrovaVolumeSafetyPanel(false);

    var controls = document.createElement("div");
    controls.className = "srovaVolumeSafetyControls";

    var checkboxLabel = document.createElement("label");
    checkboxLabel.className = "srovaVolumeSafetyCheckbox";
    var checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkboxLabel.appendChild(checkbox);
    var checkboxText = document.createElement("span");
    checkboxText.textContent = "I understand that only hardware volume control will work. Do not show this warning again.";
    checkboxLabel.appendChild(checkboxText);
    controls.appendChild(checkboxLabel);

    var countdown = document.createElement("div");
    countdown.className = "srovaVolumeSafetyCountdown";
    controls.appendChild(countdown);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "srovaVolumeSafetyButton";
    button.disabled = true;
    button.textContent = "I Understand";
    controls.appendChild(button);

    card.querySelector(".srovaVolumeSafetyBody").appendChild(controls);
    modal.appendChild(card);
    document.body.appendChild(modal);

    var remaining = 20;
    function syncCountdown() {
        if (remaining > 0) {
            button.disabled = true;
            countdown.textContent = "Please read this warning... " + remaining + "s";
        } else {
            button.disabled = false;
            countdown.textContent = "You may continue.";
            clearInterval(timer);
        }
    }
    var timer = setInterval(function() {
        remaining -= 1;
        syncCountdown();
    }, 1000);
    syncCountdown();

    button.onclick = function() {
        if (button.disabled) { return; }
        if (checkbox.checked) { setSrovaVolumeSafetyDismissed(); }
        clearInterval(timer);
        if (modal.parentNode) { modal.parentNode.removeChild(modal); }
    };
}


function showOtherAudioOutputsWarning(onAccept, onCancel) {
    if (document.getElementById("srovaOtherOutputsWarningModal")) { return; }

    var modal = document.createElement("div");
    modal.id = "srovaOtherOutputsWarningModal";
    modal.className = "srovaVolumeSafetyModal srovaOtherOutputsWarningModal";

    var card = document.createElement("div");
    card.className = "srovaVolumeSafetyWarning srovaOtherOutputsWarningPanel";
    card.setAttribute("role", "alertdialog");
    card.setAttribute("aria-modal", "true");
    card.setAttribute("aria-labelledby", "srovaOtherOutputsWarningTitle");
    card.setAttribute("aria-describedby", "srovaOtherOutputsWarningSummary");

    var icon = document.createElement("div");
    icon.className = "srovaVolumeSafetyIcon";
    icon.textContent = "\u26A0";
    card.appendChild(icon);

    var body = document.createElement("div");
    body.className = "srovaVolumeSafetyBody";

    var title = document.createElement("h2");
    title.id = "srovaOtherOutputsWarningTitle";
    title.className = "srovaVolumeSafetyTitle";
    title.textContent = "READ CAREFULLY \u2014 DANGER: RISK OF PERMANENT HEARING LOSS AND EQUIPMENT DAMAGE";
    body.appendChild(title);

    var summary = document.createElement("p");
    summary.id = "srovaOtherOutputsWarningSummary";
    summary.className = "srovaVolumeSafetySummary";
    summary.textContent =
        "SROVA uses exclusive audio output at a fixed 100% digital level. When you enable Other output devices\u2014including built-in speakers, headphone sockets, HDMI/DisplayPort outputs, or unverified audio devices\u2014the normal volume controls in your operating system, browser, phone, tablet, application, or connected device may not reduce the playback level.";
    body.appendChild(summary);

    var consequenceIntro = document.createElement("p");
    consequenceIntro.textContent =
        "Playback may begin suddenly at an extremely high level. This can cause:";
    body.appendChild(consequenceIntro);

    var consequenceList = document.createElement("ul");
    [
        "Immediate and permanent hearing loss or tinnitus.",
        "Permanent damage to headphones or in-ear monitors (IEMs).",
        "Damage to speakers, amplifiers, or other connected audio equipment."
    ].forEach(function(text) {
        var item = document.createElement("li");
        item.textContent = text;
        consequenceList.appendChild(item);
    });
    body.appendChild(consequenceList);

    var preparationIntro = document.createElement("p");
    preparationIntro.className = "srovaOtherOutputsWarningLead";
    preparationIntro.textContent = "Before continuing:";
    body.appendChild(preparationIntro);

    var preparationList = document.createElement("ul");
    [
        "Remove headphones or IEMs from your ears.",
        "Set the physical volume control on your DAC, amplifier, or powered speakers to its minimum level.",
        "Confirm that a working hardware volume control is present in the audio chain.",
        "Increase the hardware volume slowly only after playback has started safely."
    ].forEach(function(text) {
        var item = document.createElement("li");
        item.textContent = text;
        preparationList.appendChild(item);
    });
    body.appendChild(preparationList);

    var acknowledgement = document.createElement("p");
    acknowledgement.textContent =
        "By continuing, you confirm that you understand and voluntarily accept these risks. You are responsible for ensuring that suitable hardware volume control and safe listening levels are used.";
    body.appendChild(acknowledgement);

    var disclaimer = document.createElement("p");
    disclaimer.className = "srovaOtherOutputsDisclaimer";
    disclaimer.textContent =
        "To the fullest extent permitted by applicable law, SROVA and its developers disclaim responsibility for hearing injury or damage to audio equipment resulting from the use of non-recommended outputs or the absence or misuse of appropriate hardware volume control. This notice does not affect any rights or liabilities that cannot lawfully be excluded.";
    body.appendChild(disclaimer);

    var controls = document.createElement("div");
    controls.className = "srovaVolumeSafetyControls";

    var checkboxLabel = document.createElement("label");
    checkboxLabel.className = "srovaVolumeSafetyCheckbox";
    var checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkboxLabel.appendChild(checkbox);
    var checkboxText = document.createElement("span");
    checkboxText.textContent =
        "I understand that enabling Other output devices can cause permanent hearing loss and permanent damage to headphones, IEMs, speakers, amplifiers, or other equipment.";
    checkboxLabel.appendChild(checkboxText);
    controls.appendChild(checkboxLabel);

    var countdown = document.createElement("div");
    countdown.className = "srovaVolumeSafetyCountdown";
    controls.appendChild(countdown);

    var actions = document.createElement("div");
    actions.className = "srovaVolumeSafetyActions";

    var cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.className = "srovaVolumeSafetyCancelButton";
    cancelButton.textContent = "Cancel \u2014 Keep Recommended Devices Only";
    actions.appendChild(cancelButton);

    var acceptButton = document.createElement("button");
    acceptButton.type = "button";
    acceptButton.className = "srovaVolumeSafetyButton";
    acceptButton.disabled = true;
    acceptButton.textContent = "I Accept the Risk \u2014 Show All Devices";
    actions.appendChild(acceptButton);
    controls.appendChild(actions);

    body.appendChild(controls);
    card.appendChild(body);
    modal.appendChild(card);
    document.body.appendChild(modal);

    var remaining = 20;
    var timer = null;

    function syncAcceptanceState() {
        if (remaining > 0) {
            countdown.textContent = "Please read this warning carefully... " + remaining + "s";
        } else if (!checkbox.checked) {
            countdown.textContent = "Tick the acknowledgement box to continue.";
        } else {
            countdown.textContent = "You may continue.";
        }
        acceptButton.disabled = remaining > 0 || !checkbox.checked;
    }

    function closeWarning(accepted) {
        if (timer) { clearInterval(timer); }
        if (modal.parentNode) { modal.parentNode.removeChild(modal); }
        if (accepted) {
            if (typeof onAccept === "function") { onAccept(); }
        } else if (typeof onCancel === "function") {
            onCancel();
        }
    }

    checkbox.addEventListener("change", syncAcceptanceState);
    cancelButton.onclick = function() { closeWarning(false); };
    acceptButton.onclick = function() {
        if (acceptButton.disabled) { return; }
        closeWarning(true);
    };

    timer = setInterval(function() {
        remaining = Math.max(0, remaining - 1);
        syncAcceptanceState();
        if (remaining === 0 && timer) {
            clearInterval(timer);
            timer = null;
        }
    }, 1000);
    syncAcceptanceState();
    cancelButton.focus();
}


function formatSrovaServiceTime(value) {
    var n = Number(value || 0);
    if (!n) { return "Unavailable"; }
    try {
        return new Date(n * 1000).toLocaleString();
    } catch (e) {
        return "Unavailable";
    }
}

function fetchSrovaServiceState() {
    var url = "/api/network?_=" + encodeURIComponent(String(Date.now()));
    return fetchWithTimeout(url, {cache: "no-store"}, 3000)
        .then(function(res) {
            if (!res.ok) { throw new Error("SROVA status unavailable"); }
            return res.json();
        });
}

var _srovaRestartReturnBaseline = 0;

function srovaRestartTargetOrigin(targetUrl) {
    try {
        return new URL(targetUrl || window.location.origin, window.location.href).origin;
    } catch (e) {
        return window.location.origin;
    }
}

function buildSrovaRestartReturnUrl(targetUrl, previousStartedAt) {
    var url = new URL(targetUrl || window.location.origin, window.location.href);
    url.pathname = "/";
    url.searchParams.set("srova-restart-from", String(previousStartedAt || 0));
    url.searchParams.set("srova-settings-tab", "system");
    return url.toString();
}

function waitForSrovaTargetReachable(targetUrl) {
    var attempts = 0;
    var maxAttempts = 45;
    var retryDelayMs = 1500;
    var targetOrigin = srovaRestartTargetOrigin(targetUrl);

    return new Promise(function(resolve, reject) {
        function retry() {
            attempts += 1;

            var probe = new Image();
            var settled = false;
            var timer = setTimeout(function() {
                if (settled) { return; }
                settled = true;
                probe.onload = null;
                probe.onerror = null;
                nextAttempt();
            }, 3000);

            function finish(success) {
                if (settled) { return; }
                settled = true;
                clearTimeout(timer);
                probe.onload = null;
                probe.onerror = null;

                if (success) {
                    resolve();
                } else {
                    nextAttempt();
                }
            }

            function nextAttempt() {
                if (attempts >= maxAttempts) {
                    reject(new Error("SROVA target did not become reachable"));
                    return;
                }
                setTimeout(retry, retryDelayMs);
            }

            probe.onload = function() { finish(true); };
            probe.onerror = function() { finish(false); };
            probe.src =
                targetOrigin +
                "/ui_web/icon-32.png?_=" +
                encodeURIComponent(String(Date.now()));
        }

        setTimeout(retry, 900);
    });
}

function clearSrovaRestartReturnState() {
    _srovaRestartReturnBaseline = 0;

    if (!window.history || !window.history.replaceState) { return; }

    try {
        var url = new URL(window.location.href);
        url.searchParams.delete("srova-restart-from");
        url.searchParams.delete("srova-settings-tab");
        window.history.replaceState({}, document.title, url.toString());
    } catch (e) {}
}

function restoreSrovaRestartReturnView() {
    var params;

    try {
        params = new URLSearchParams(window.location.search || "");
    } catch (e) {
        return;
    }

    var baseline = Number(params.get("srova-restart-from") || 0);
    var tab = String(params.get("srova-settings-tab") || "");

    if (!baseline || tab !== "system") { return; }

    _srovaRestartReturnBaseline = baseline;
    currentSettingsTab = "system";
    showView("settings");
    renderSettings();
}

function waitForSrovaServiceRestart(previousStartedAt, onProgress) {
    var attempts = 0;
    var maxAttempts = 45;
    var retryDelayMs = 1500;

    return new Promise(function(resolve, reject) {
        function retry() {
            attempts += 1;
            fetchSrovaServiceState()
                .then(function(data) {
                    var startedAt = Number(data && data.process_started_at || 0);
                    var changed = startedAt &&
                        previousStartedAt &&
                        Math.abs(startedAt - previousStartedAt) > 0.001;

                    if (changed) {
                        resolve(data);
                        return;
                    }

                    if (typeof onProgress === "function") {
                        onProgress({
                            attempt: attempts,
                            reachable: true,
                            data: data || {}
                        });
                    }

                    if (attempts >= maxAttempts) {
                        reject(new Error("SROVA restart confirmation timed out"));
                        return;
                    }

                    setTimeout(retry, retryDelayMs);
                })
                .catch(function() {
                    if (typeof onProgress === "function") {
                        onProgress({
                            attempt: attempts,
                            reachable: false,
                            data: null
                        });
                    }

                    if (attempts >= maxAttempts) {
                        reject(new Error("SROVA restart confirmation timed out"));
                        return;
                    }

                    setTimeout(retry, retryDelayMs);
                });
        }

        setTimeout(retry, 900);
    });
}

function showRestartSrovaModal(targetUrl, onConfirm, options) {
    options = options || {};
    var existing = document.getElementById("srovaRestartModal");
    if (existing && existing.parentNode) { existing.parentNode.removeChild(existing); }

    var modal = document.createElement("div");
    modal.id = "srovaRestartModal";
    modal.className = "srovaRestartModal";
    modal.setAttribute("aria-hidden", "false");
    modal.setAttribute("data-restart-busy", "false");

    var card = document.createElement("div");
    card.className = "srovaRestartCard";

    var title = document.createElement("h2");
    title.textContent = "Restart SROVA?";
    card.appendChild(title);

    var body = document.createElement("div");
    body.className = "srovaRestartBody";
    if (options.autoReconnect) {
        body.innerHTML =
            '<p>SROVA will restart and playback will stop briefly.</p>' +
            '<p>This page will reconnect automatically.</p>' +
            '<div class="remoteUrlBox">' + _escapeText(targetUrl || "") + '</div>' +
            '<p>Continue?</p>';
    } else {
        body.innerHTML =
            '<p>SROVA will restart and this page may disconnect.</p>' +
            '<p>After restart, open:</p>' +
            '<div class="remoteUrlBox">' + _escapeText(targetUrl || "") + '</div>' +
            '<p>Continue?</p>';
    }
    card.appendChild(body);

    var actions = document.createElement("div");
    actions.className = "srovaRestartActions";

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "settingsBtn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.onclick = function() {
        if (modal.getAttribute("data-restart-busy") === "true") {
            return;
        }
        if (modal.parentNode) { modal.parentNode.removeChild(modal); }
    };
    actions.appendChild(cancelBtn);

    var restartBtn = document.createElement("button");
    restartBtn.className = "settingsBtn settingsBtnDanger";
    restartBtn.textContent = "Restart SROVA";
    restartBtn.onclick = function() {
        modal.setAttribute("data-restart-busy", "true");
        restartBtn.disabled = true;
        restartBtn.textContent = "Restarting…";
        cancelBtn.disabled = true;
        if (typeof onConfirm === "function") { onConfirm(modal, restartBtn); }
    };
    actions.appendChild(restartBtn);

    card.appendChild(actions);
    modal.appendChild(card);
    modal.addEventListener("click", function(e) {
        if (
            e.target === modal &&
            modal.getAttribute("data-restart-busy") !== "true" &&
            modal.parentNode
        ) {
            modal.parentNode.removeChild(modal);
        }
    });
    document.body.appendChild(modal);
}


function buildSrovaServiceSection() {
    var sec = document.createElement("div");
    sec.className = "settingsSection srovaServiceSection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle";
    titleRow.innerHTML =
        '<span class="material-icons">power_settings_new</span>' +
        '<span class="settingsSectionText">SROVA Service</span>';
    sec.appendChild(titleRow);

    var desc = document.createElement("div");
    desc.className = "settingsSectionDesc";
    desc.textContent =
        "Restart the SROVA music service. Playback will stop briefly and this page will reconnect automatically.";
    sec.appendChild(desc);

    var actionRow = document.createElement("div");
    actionRow.className = "srovaServiceActionRow";

    var restartBtn = document.createElement("button");
    restartBtn.type = "button";
    restartBtn.className = "settingsBtn settingsBtnDanger srovaServiceRestartBtn";
    restartBtn.textContent = "Restart SROVA";
    restartBtn.disabled = true;
    actionRow.appendChild(restartBtn);

    var refreshBtn = document.createElement("button");
    refreshBtn.type = "button";
    refreshBtn.className = "settingsBtn srovaServiceRefreshBtn";
    refreshBtn.title = "Refresh SROVA status";
    refreshBtn.setAttribute("aria-label", "Refresh SROVA status");
    refreshBtn.innerHTML = '<span class="material-icons" aria-hidden="true">refresh</span>';
    actionRow.appendChild(refreshBtn);

    sec.appendChild(actionRow);

    var lastRestart = document.createElement("div");
    lastRestart.className = "settingsStatus srovaServiceLastRestart";
    lastRestart.textContent = "SROVA last restarted: Checking…";
    sec.appendChild(lastRestart);

    var status = document.createElement("div");
    status.className = "settingsStatus srovaServiceStatus";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.textContent = "Checking SROVA service status…";
    sec.appendChild(status);

    var serviceState = null;
    var restartInProgress = false;
    var successHoldTimer = null;

    function setStatus(message, stateClass) {
        status.textContent = message || "";
        status.classList.remove("isSuccess");
        status.classList.remove("isError");
        if (stateClass) { status.classList.add(stateClass); }
    }

    function holdServiceControlsAfterSuccess() {
        if (successHoldTimer) {
            clearTimeout(successHoldTimer);
        }

        restartBtn.disabled = true;
        restartBtn.textContent = "Restart SROVA";
        refreshBtn.disabled = true;

        successHoldTimer = setTimeout(function() {
            if (
                status.classList.contains("isSuccess") &&
                status.textContent.indexOf(
                    "SROVA restarted successfully"
                ) === 0
            ) {
                setStatus("SROVA service is reachable.");
            }

            restartBtn.disabled =
                !(serviceState && serviceState.restart_supported);
            restartBtn.textContent = "Restart SROVA";
            refreshBtn.disabled = false;
            successHoldTimer = null;
        }, 2200);
    }

    function applyServiceState(data) {
        serviceState = data || {};
        lastRestart.textContent =
            "SROVA last restarted: " +
            formatSrovaServiceTime(serviceState.process_started_at);

        if (!restartInProgress && !successHoldTimer) {
            restartBtn.textContent = "Restart SROVA";
            restartBtn.disabled = !serviceState.restart_supported;
        }
    }

    function loadServiceState(options) {
        options = options || {};
        refreshBtn.disabled = true;
        if (options.announce) {
            setStatus("Refreshing SROVA status…");
        }

        return fetchSrovaServiceState()
            .then(function(data) {
                applyServiceState(data);

                if (_srovaRestartReturnBaseline) {
                    var returnedStartedAt =
                        Number(data && data.process_started_at || 0);
                    var restartConfirmed =
                        returnedStartedAt &&
                        Math.abs(
                            returnedStartedAt -
                            _srovaRestartReturnBaseline
                        ) > 0.001;

                    if (restartConfirmed) {
                        setStatus(
                            "SROVA restarted successfully at " +
                            formatSrovaServiceTime(returnedStartedAt) +
                            ".",
                            "isSuccess"
                        );
                        holdServiceControlsAfterSuccess();
                        clearSrovaRestartReturnState();
                        return data;
                    }

                    setStatus(
                        "SROVA is reachable, but the new service session could not be confirmed.",
                        "isError"
                    );
                    return data;
                }

                if (options.announce) {
                    setStatus("SROVA status refreshed.", "isSuccess");
                } else if (!restartInProgress) {
                    setStatus("SROVA service is reachable.");
                }
                return data;
            })
            .catch(function(err) {
                if (!restartInProgress) {
                    restartBtn.disabled = true;
                    setStatus(
                        "Could not refresh SROVA status. Check that the device is reachable.",
                        "isError"
                    );
                }
                throw err;
            })
            .finally(function() {
                if (!restartInProgress && !successHoldTimer) {
                    refreshBtn.disabled = false;
                }
            });
    }

    refreshBtn.onclick = function() {
        if (restartInProgress) { return; }
        loadServiceState({announce: true}).catch(function() {});
    };

    restartBtn.onclick = function() {
        if (restartInProgress || !serviceState) { return; }

        var targetUrl = serviceState.url || window.location.origin;
        var baselineStartedAt = Number(serviceState.process_started_at || 0);

        showRestartSrovaModal(targetUrl, function(modal, modalRestartBtn) {
            restartInProgress = true;
            restartBtn.disabled = true;
            restartBtn.textContent = "Restarting…";
            refreshBtn.disabled = true;
            setStatus("Restarting SROVA… reconnecting automatically.");

            var modalBody = modal ? modal.querySelector(".srovaRestartBody") : null;
            if (modalBody) {
                modalBody.innerHTML =
                    '<p>Restarting SROVA…</p>' +
                    '<p>This page will reconnect automatically.</p>' +
                    '<div class="remoteUrlBox">' + _escapeText(targetUrl) + '</div>';
            }

            function reconnect() {
                waitForSrovaServiceRestart(baselineStartedAt, function(progress) {
                    if (!progress.reachable) {
                        setStatus("Restarting SROVA… waiting for the service to return.");
                    } else {
                        setStatus("Restarting SROVA… confirming the new service session.");
                    }
                })
                .then(function(data) {
                    restartInProgress = false;
                    holdServiceControlsAfterSuccess();
                    applyServiceState(data);

                    var restartedText =
                        "SROVA restarted successfully at " +
                        formatSrovaServiceTime(data.process_started_at) +
                        ".";
                    setStatus(restartedText, "isSuccess");

                    if (modalRestartBtn) {
                        modalRestartBtn.disabled = true;
                        modalRestartBtn.textContent = "Restarted";
                    }

                    var modalActions = modal ?
                        modal.querySelector(".srovaRestartActions") :
                        null;

                    if (modalActions) {
                        modalActions.classList.add(
                            "srovaRestartSuccessActionsHidden"
                        );
                    }

                    if (modalBody) {
                        modalBody.innerHTML =
                            '<p class="srovaRestartSuccess">SROVA restarted successfully.</p>' +
                            '<p>' + _escapeText(formatSrovaServiceTime(data.process_started_at)) + '</p>';
                    }

                    setTimeout(function() {
                        if (modal && modal.parentNode) {
                            modal.parentNode.removeChild(modal);
                        }
                    }, 1800);
                })
                .catch(function() {
                    restartInProgress = false;
                    restartBtn.disabled = false;
                    restartBtn.textContent = "Restart SROVA";
                    refreshBtn.disabled = false;
                    if (modal) {
                        modal.setAttribute("data-restart-busy", "false");
                    }

                    setStatus(
                        "SROVA is taking longer than expected to restart. Use Refresh SROVA status to check again.",
                        "isError"
                    );

                    if (modalRestartBtn) {
                        modalRestartBtn.disabled = false;
                        modalRestartBtn.textContent = "Try Again";
                    }

                    if (modalBody) {
                        modalBody.innerHTML =
                            '<p>SROVA is taking longer than expected to restart.</p>' +
                            '<p>Close this message and use Refresh SROVA status to check again.</p>';
                    }

                    var cancel = modal ?
                        modal.querySelector(".srovaRestartActions .settingsBtn") :
                        null;
                    if (cancel) {
                        cancel.disabled = false;
                        cancel.textContent = "Close";
                    }
                });
            }

            fetch("/api/system/restart", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({})
            })
            .then(function(res) {
                if (!res.ok) { throw new Error("Restart request failed"); }
                return res.json();
            })
            .then(function(data) {
                if (data && data.process_started_at) {
                    baselineStartedAt = Number(data.process_started_at);
                }

                var responseUrl =
                    String(data && data.url || targetUrl || window.location.origin);
                var targetOrigin =
                    srovaRestartTargetOrigin(responseUrl);

                if (targetOrigin !== window.location.origin) {
                    setStatus(
                        "Restarting SROVA… waiting for the new web address."
                    );

                    if (modalBody) {
                        modalBody.innerHTML =
                            '<p>Restarting SROVA…</p>' +
                            '<p>This page will reconnect at the new address.</p>' +
                            '<div class="remoteUrlBox">' +
                            _escapeText(responseUrl) +
                            '</div>';
                    }

                    waitForSrovaTargetReachable(responseUrl)
                        .then(function() {
                            window.location.replace(
                                buildSrovaRestartReturnUrl(
                                    responseUrl,
                                    baselineStartedAt
                                )
                            );
                        })
                        .catch(function() {
                            restartInProgress = false;
                            restartBtn.disabled = false;
                            restartBtn.textContent = "Restart SROVA";
                            refreshBtn.disabled = false;
                            if (modal) {
                                modal.setAttribute(
                                    "data-restart-busy",
                                    "false"
                                );
                            }

                            setStatus(
                                "The new SROVA address is taking longer than expected. Open the address shown below or try again.",
                                "isError"
                            );

                            if (modalRestartBtn) {
                                modalRestartBtn.disabled = false;
                                modalRestartBtn.textContent = "Try Again";
                            }

                            if (modalBody) {
                                modalBody.innerHTML =
                                    '<p>The new SROVA address is taking longer than expected.</p>' +
                                    '<div class="remoteUrlBox">' +
                                    _escapeText(responseUrl) +
                                    '</div>';
                            }

                            var closeBtn = modal ?
                                modal.querySelector(
                                    ".srovaRestartActions .settingsBtn"
                                ) :
                                null;
                            if (closeBtn) {
                                closeBtn.disabled = false;
                                closeBtn.textContent = "Close";
                            }
                        });
                    return;
                }

                reconnect();
            })
            .catch(function() {
                /*
                 * The WebView can lose the response while the backend is
                 * already stopping. Continue with startup-identity polling
                 * rather than reporting a false failure.
                 */
                reconnect();
            });
        }, {autoReconnect: true});
    };

    loadServiceState().catch(function() {});
    return sec;
}

function buildRemoteAccessSection() {
    var sec = document.createElement("div");
    sec.className = "settingsSection remoteAccessSection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle";
    titleRow.innerHTML = '<span class="material-icons">lan</span><span class="settingsSectionText">Remote Access</span>';
    sec.appendChild(titleRow);

    var desc = document.createElement("div");
    desc.className = "settingsSectionDesc";
    desc.textContent = "View this SROVA server address on your LAN and change the web UI port. Port changes take effect after restarting SROVA.";
    sec.appendChild(desc);

    var grid = document.createElement("div");
    grid.className = "remoteAccessGrid";

    var lanRow = document.createElement("div");
    lanRow.className = "settingsField remoteLanField";
    var lanLabel = document.createElement("label");
    lanLabel.className = "settingsLabel";
    lanLabel.textContent = "LAN Address";
    var lanInput = document.createElement("input");
    lanInput.id = "remoteLanInput";
    lanInput.type = "text";
    lanInput.className = "settingsInput";
    lanInput.placeholder = "192.168.1.10";
    lanRow.appendChild(lanLabel);
    lanRow.appendChild(lanInput);
    grid.appendChild(lanRow);

    var portRow = document.createElement("div");
    portRow.className = "settingsField remotePortField";
    var portLabel = document.createElement("label");
    portLabel.className = "settingsLabel";
    portLabel.textContent = "Web UI Port";
    var portInput = document.createElement("input");
    portInput.id = "remotePortInput";
    portInput.type = "number";
    portInput.min = "1024";
    portInput.max = "65535";
    portInput.step = "1";
    portInput.className = "settingsInput";
    portInput.placeholder = "8081";
    portRow.appendChild(portLabel);
    portRow.appendChild(portInput);
    grid.appendChild(portRow);

    sec.appendChild(grid);

    var status = document.createElement("div");
    status.className = "settingsStatus remoteAccessStatus";
    status.textContent = "Changing the port requires restarting SROVA.";
    sec.appendChild(status);

    var afterRestart = document.createElement("div");
    afterRestart.className = "remoteAfterRestart hidden";
    sec.appendChild(afterRestart);

    var actionRow = document.createElement("div");
    actionRow.className = "remoteActionRow";

    var saveBtn = document.createElement("button");
    saveBtn.className = "settingsBtn";
    saveBtn.textContent = "Save Target";
    actionRow.appendChild(saveBtn);

    var restartBtn = document.createElement("button");
    restartBtn.className = "settingsBtn settingsBtnDanger hidden";
    restartBtn.textContent = "Restart SROVA";
    actionRow.appendChild(restartBtn);

    sec.appendChild(actionRow);

    var currentNetwork = null;

    function remoteTargetUrl(lanAddress, port) {
        var host = String(lanAddress || "").trim();
        var webPort = String(port || "").trim();
        if (!host || !webPort) { return ""; }
        return "http://" + host + ":" + webPort;
    }

    function updateNetworkUi(data) {
        currentNetwork = data || {};
        if (lanInput) { lanInput.value = currentNetwork.lan_address || currentNetwork.lan_ip || ""; }
        if (portInput && currentNetwork.port) { portInput.value = currentNetwork.port; }
        currentNetwork.url = remoteTargetUrl(lanInput ? lanInput.value : currentNetwork.lan_address, portInput ? portInput.value : currentNetwork.port);
        if (currentNetwork.restart_required) {
            restartBtn.classList.remove("hidden");
            afterRestart.classList.remove("hidden");
            afterRestart.innerHTML =
                '<div class="settingsLabel">After Restart, Open</div>' +
                '<div class="remoteUrlBox">' + _escapeText(currentNetwork.url) + '</div>';
        } else {
            restartBtn.classList.add("hidden");
            afterRestart.classList.add("hidden");
            afterRestart.innerHTML = "";
        }
    }

    function loadNetwork() {
        return fetch("/api/network")
            .then(function(res) { return res.json(); })
            .then(function(data) {
                updateNetworkUi(data);
                status.textContent = data.restart_required ?
                    "Target saved. Restart SROVA to apply the port change." :
                    "Changing the port requires restarting SROVA.";
            })
            .catch(function() {
                status.textContent = "Could not load remote access information. Check the server is reachable.";
            });
    }

    saveBtn.onclick = function() {
        var lanAddress = String(lanInput.value || "").trim();
        if (!lanAddress) {
            status.textContent = "Enter a LAN address.";
            return;
        }
        if (/[\s\/?#]/.test(lanAddress) || lanAddress.indexOf("://") !== -1) {
            status.textContent = "Enter only the LAN address, without http://, port, or path.";
            return;
        }
        var value = String(portInput.value || "").trim();
        var port = parseInt(value, 10);
        if (!value || isNaN(port)) {
            status.textContent = "Enter a numeric port.";
            return;
        }
        if (port < 1024 || port > 65535) {
            status.textContent = "Port must be between 1024 and 65535.";
            return;
        }
        saveBtn.disabled = true;
        saveBtn.textContent = "Saving…";
        status.textContent = "";
        fetch("/api/settings/web-port", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lan_address: lanAddress, port: port })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            saveBtn.disabled = false;
            saveBtn.textContent = "Save Target";
            if (data.error) {
                status.textContent = data.error;
                return;
            }
            updateNetworkUi(data);
            status.textContent = data.message || "Target saved. Restart SROVA to apply the port change.";
        })
        .catch(function() {
            saveBtn.disabled = false;
            saveBtn.textContent = "Save Target";
            status.textContent = "Save failed. Check the server is reachable.";
        });
    };

    restartBtn.onclick = function() {
        var serviceRestartBtn = settingsView ?
            settingsView.querySelector(".srovaServiceRestartBtn") :
            null;

        if (serviceRestartBtn && !serviceRestartBtn.disabled) {
            status.textContent =
                "Restarting through SROVA Service above. This page will reconnect automatically.";
            serviceRestartBtn.click();
            return;
        }

        status.textContent =
            "SROVA service status is still loading. Try Restart SROVA again in a moment.";
    };

    loadNetwork();
    return sec;
}

function buildDacSection() {
    var sec = document.createElement("div");
    sec.className = "settingsSection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle";
    titleRow.innerHTML = '<span class="material-icons">usb</span> DAC';
    sec.appendChild(titleRow);

    var desc = document.createElement("div");
    desc.className   = "settingsSectionDesc";
    desc.textContent = "Choose the ALSA output used by SROVA's existing bit-perfect path. Release the DAC before changing output; unlocked selections validate and save automatically.";
    sec.appendChild(desc);

    var recommendedOnly = true;
    var filterSaveInFlight = false;
    var audioOutputSafetyReady = false;
    var filterRow = document.createElement("div");
    filterRow.className = "settingsToggleRow dacDeviceFilterRow";

    var filterCopy = document.createElement("div");
    filterCopy.className = "settingsToggleCopy";
    var filterLabel = document.createElement("div");
    filterLabel.className = "settingsLabel";
    filterLabel.textContent = "Only show recommended devices";
    var filterSub = document.createElement("div");
    filterSub.className = "settingsToggleSub";
    filterSub.textContent = "Enabled \u2014 external USB DACs and supported audio HATs only";
    filterCopy.appendChild(filterLabel);
    filterCopy.appendChild(filterSub);

    var filterToggle = document.createElement("button");
    filterToggle.type = "button";
    filterToggle.className = "settingsToggleSwitch active";
    filterToggle.setAttribute("aria-label", "Only show recommended devices");
    filterToggle.setAttribute("aria-pressed", "true");
    filterToggle.innerHTML = "<span></span>";

    filterRow.appendChild(filterCopy);
    filterRow.appendChild(filterToggle);
    sec.appendChild(filterRow);

    var currentBox = document.createElement("div");
    currentBox.className = "dacCurrentOutput";
    currentBox.textContent = "Loading current output…";
    sec.appendChild(currentBox);

    var lockNotice = document.createElement("div");
    lockNotice.className = "dacLockNotice";
    sec.appendChild(lockNotice);

    var grid = document.createElement("div");
    grid.className = "dacSettingsGrid";

    var driverRow = document.createElement("div");
    driverRow.className = "settingsField";
    var driverLabel = document.createElement("label");
    driverLabel.className = "settingsLabel";
    driverLabel.textContent = "Driver";
    var driverSelect = document.createElement("select");
    driverSelect.className = "settingsInput";
    ["ALSA", "alsa_mmap"].forEach(function(d) {
        var opt = document.createElement("option");
        opt.value = d;
        opt.textContent = d === "alsa_mmap" ? "ALSA mmap (Recommended)" : d;
        driverSelect.appendChild(opt);
    });
    driverRow.appendChild(driverLabel);
    driverRow.appendChild(driverSelect);
    grid.appendChild(driverRow);

    var deviceRow = document.createElement("div");
    deviceRow.className = "settingsField";
    var deviceLabel = document.createElement("label");
    deviceLabel.className = "settingsLabel";
    deviceLabel.textContent = "Output Device";
    var deviceSelect = document.createElement("select");
    deviceSelect.className = "settingsInput";
    deviceRow.appendChild(deviceLabel);
    deviceRow.appendChild(deviceSelect);
    grid.appendChild(deviceRow);

    sec.appendChild(grid);

    var status = document.createElement("div");
    status.className = "settingsStatus";
    sec.appendChild(status);

    var actionRow = document.createElement("div");
    actionRow.className = "dacActionRow";

    var refreshBtn = document.createElement("button");
    refreshBtn.className = "settingsBtn";
    refreshBtn.textContent = "Refresh Devices";
    actionRow.appendChild(refreshBtn);

    var releaseBtn = document.createElement("button");
    releaseBtn.className   = "settingsBtn settingsBtnDanger";
    releaseBtn.textContent = "Release DAC";
    actionRow.appendChild(releaseBtn);

    var exclusiveBtn = document.createElement("button");
    exclusiveBtn.className   = "settingsBtn";
    exclusiveBtn.textContent = "Exclusive Mode";
    actionRow.appendChild(exclusiveBtn);

    sec.appendChild(actionRow);
    sec.appendChild(buildSrovaVolumeSafetyPanel(true));

    var dacSaveInFlight = false;

    function setFilterVisual(enabled) {
        recommendedOnly = !!enabled;
        filterToggle.className = "settingsToggleSwitch" + (recommendedOnly ? " active" : "");
        filterToggle.setAttribute("aria-pressed", recommendedOnly ? "true" : "false");
        filterSub.textContent = recommendedOnly ?
            "Enabled \u2014 external USB DACs and supported audio HATs only" :
            "Disabled \u2014 all detected system outputs are visible";
    }

    function selectedDeviceName() {
        var opt = deviceSelect.options[deviceSelect.selectedIndex];
        return opt ? (opt.getAttribute("data-name") || "") : "";
    }

    function setLockedState(state) {
        var locked = !!(state && state.dac_locked);
        var hasSelectedDevice = !!deviceSelect.value;
        var hasAvailableDevice = Array.prototype.some.call(
            deviceSelect.options,
            function(opt) { return !!opt.value; }
        );
        driverSelect.disabled = locked || dacSaveInFlight || !hasSelectedDevice;
        deviceSelect.disabled = locked || dacSaveInFlight || !hasAvailableDevice;
        currentDacName = _dacDisplayName(state && state.dac_name, state && state.alsa_driver, state && state.alsa_device);
        currentDacLocked = locked;
        syncDacNameDisplay();
        if (locked) {
            lockNotice.textContent = "Unlock DAC to change audio output. Use Release DAC to stop playback and release the current device.";
            lockNotice.classList.add("dacLocked");
        } else {
            lockNotice.textContent = "DAC released. Choose an output; the selection saves automatically. Then use Exclusive Mode when you are ready.";
            lockNotice.classList.remove("dacLocked");
        }
    }

    function renderDevices(devices, current, showRecommendedOnly) {
        var currentDevice = (current && (current.device || current.alsa_device)) || "hw:0,0";
        var currentDriver = (current && (current.driver || current.alsa_driver)) || "ALSA";
        deviceSelect.innerHTML = "";
        if (!devices || !devices.length) {
            var emptyOption = document.createElement("option");
            emptyOption.value = "";
            emptyOption.textContent = showRecommendedOnly ?
                "No recommended devices detected" :
                "No audio output devices detected";
            emptyOption.disabled = true;
            emptyOption.selected = true;
            deviceSelect.appendChild(emptyOption);
        }

        var recommendedGroup = null;
        var otherGroup = null;
        if (!showRecommendedOnly && devices && devices.length) {
            recommendedGroup = document.createElement("optgroup");
            recommendedGroup.label = "Recommended devices";
            otherGroup = document.createElement("optgroup");
            otherGroup.label = "Other system outputs";
        }

        (devices || []).forEach(function(d) {
            var opt = document.createElement("option");
            opt.value = d.device;
            var recommendationLabel = (!showRecommendedOnly && d.recommended) ?
                " (Recommended)" : "";
            opt.textContent = (d.name || "ALSA output") + recommendationLabel + " \u2014 " + d.device;
            opt.setAttribute("data-name", d.name || "");
            opt.setAttribute("data-recommended", d.recommended ? "true" : "false");
            if (showRecommendedOnly) {
                deviceSelect.appendChild(opt);
            } else if (d.recommended) {
                recommendedGroup.appendChild(opt);
            } else {
                otherGroup.appendChild(opt);
            }
        });
        if (!showRecommendedOnly && recommendedGroup) {
            if (recommendedGroup.children.length) { deviceSelect.appendChild(recommendedGroup); }
            if (otherGroup.children.length) { deviceSelect.appendChild(otherGroup); }
        }
        driverSelect.value = currentDriver;
        var currentOption = Array.prototype.some.call(deviceSelect.options, function(opt) {
            return opt.value === currentDevice;
        });
        if (currentOption) {
            deviceSelect.value = currentDevice;
        } else if (devices && devices.length) {
            var chooseOption = document.createElement("option");
            chooseOption.value = "";
            chooseOption.textContent = showRecommendedOnly ?
                "Select a recommended output" :
                "Select an audio output";
            chooseOption.disabled = true;
            chooseOption.selected = true;
            deviceSelect.insertBefore(chooseOption, deviceSelect.firstChild);
        }
    }

    function loadDacUi(message) {
        if (message) { status.textContent = message; }
        return Promise.all([
            fetch("/api/audio/output").then(function(res) { return res.json(); }),
            fetch("/api/audio/devices").then(function(res) { return res.json(); })
        ]).then(function(results) {
            var output = results[0] || {};
            var devicesPayload = results[1] || {};
            audioOutputSafetyReady =
                Number(devicesPayload.warning_version || 0) ===
                    SROVA_OTHER_AUDIO_OUTPUT_WARNING_VERSION &&
                typeof devicesPayload.recommended_only === "boolean";
            var devices = audioOutputSafetyReady ?
                (devicesPayload.devices || []) :
                [];
            var nextRecommendedOnly = audioOutputSafetyReady ?
                devicesPayload.recommended_only !== false :
                true;
            setFilterVisual(nextRecommendedOnly);
            renderDevices(devices, {
                driver: output.alsa_driver,
                device: output.alsa_device,
                dac_name: output.dac_name
            }, nextRecommendedOnly);
            var display = _dacDisplayName(output.dac_name, output.alsa_driver, output.alsa_device);
            var recommendationNote = "";
            if (output.device_available === false) {
                recommendationNote =
                    '<div class="dacOtherOutputNotice">Saved output is currently unavailable.</div>';
            } else if (output.device_recommended === false) {
                recommendationNote =
                    '<div class="dacOtherOutputNotice">Current output is an Other system device. Turn off the recommended-device filter to manage or reselect it.</div>';
            } else if (output.device_recommended === true) {
                recommendationNote =
                    '<div class="dacRecommendedOutputNotice">Recommended output</div>';
            }
            currentBox.innerHTML = '<div class="settingsLabel">Current Output</div>' +
                '<div class="dacCurrentMain">' + _escapeText(output.alsa_driver || "ALSA") + ' / ' + _escapeText(output.alsa_device || "hw:0,0") + '</div>' +
                '<div class="dacCurrentName">' + _escapeText(display || "Unknown DAC") + '</div>' +
                recommendationNote;
            setLockedState(output);
            filterToggle.disabled = filterSaveInFlight || !audioOutputSafetyReady;
            if (!audioOutputSafetyReady) {
                status.textContent =
                    "Restart SROVA to activate the new audio-output safety controls.";
                return;
            }
            if (!message) {
                if (output.device_recommended === false && nextRecommendedOnly) {
                    status.textContent =
                        "Your current output is not recommended. Turn off Only show recommended devices to view Other outputs.";
                } else if (!devices.length && nextRecommendedOnly) {
                    status.textContent =
                        "No recommended DAC is connected. You can show Other outputs after accepting the Volume Safety warning.";
                } else {
                    status.textContent = "";
                }
            }
        }).catch(function() {
            status.textContent = "Could not load DAC devices. Check the server is reachable.";
        });
    }

    function saveDeviceFilter(enabled, warningAcknowledged) {
        filterSaveInFlight = true;
        filterToggle.disabled = true;
        status.textContent = enabled ?
            "Showing recommended devices only\u2026" :
            "Enabling Other output devices\u2026";
        fetch("/api/audio/device-filter", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                recommended_only: !!enabled,
                warning_acknowledged: warningAcknowledged === true,
                warning_version: SROVA_OTHER_AUDIO_OUTPUT_WARNING_VERSION
            })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (!data || data.error || data.ok === false) {
                throw new Error((data && data.error) || "Could not update device visibility.");
            }
            setFilterVisual(data.recommended_only !== false);
            return loadDacUi(
                data.recommended_only !== false ?
                    "Only recommended devices are shown." :
                    "All detected devices are shown. Recommended devices remain at the top."
            );
        })
        .catch(function(error) {
            setFilterVisual(recommendedOnly);
            status.textContent = error && error.message ?
                error.message :
                "Could not update device visibility.";
        })
        .then(function() {
            filterSaveInFlight = false;
            filterToggle.disabled = false;
        });
    }

    filterToggle.onclick = function() {
        if (filterSaveInFlight || !audioOutputSafetyReady) { return; }
        if (recommendedOnly) {
            showOtherAudioOutputsWarning(function() {
                saveDeviceFilter(false, true);
            }, function() {
                setFilterVisual(true);
                status.textContent = "Recommended-device filtering remains enabled.";
            });
        } else {
            saveDeviceFilter(true, false);
        }
    };

    refreshBtn.onclick = function() {
        refreshBtn.disabled = true;
        status.textContent = "Refreshing devices…";
        loadDacUi("Refreshing devices…").then(function() {
            refreshBtn.disabled = false;
            status.textContent = "Devices refreshed.";
        }).catch(function() {
            refreshBtn.disabled = false;
        });
    };

    function saveSelectedDac() {
        if (dacSaveInFlight || currentDacLocked || !deviceSelect.value) { return; }
        dacSaveInFlight = true;
        driverSelect.disabled = true;
        deviceSelect.disabled = true;
        filterToggle.disabled = true;
        refreshBtn.disabled = true;
        releaseBtn.disabled = true;
        exclusiveBtn.disabled = true;
        status.textContent = "Validating and saving selected DAC...";
        fetch("/api/audio/output", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                alsa_driver: driverSelect.value,
                alsa_device: deviceSelect.value,
                dac_name: selectedDeviceName()
            })
        })
        .then(function(res) { return res.json(); })
        .then(function(d) {
            dacSaveInFlight = false;
            filterToggle.disabled = false;
            refreshBtn.disabled = false;
            releaseBtn.disabled = false;
            exclusiveBtn.disabled = false;
            if (d.error) {
                return loadDacUi("DAC was not saved: " + d.error);
            }
            return loadDacUi("DAC saved automatically. Use Exclusive Mode to reacquire the selected output.");
        })
        .catch(function() {
            dacSaveInFlight = false;
            filterToggle.disabled = false;
            refreshBtn.disabled = false;
            releaseBtn.disabled = false;
            exclusiveBtn.disabled = false;
            loadDacUi("DAC was not saved. Check the server is reachable.");
        });
    }

    driverSelect.addEventListener("change", saveSelectedDac);
    deviceSelect.addEventListener("change", saveSelectedDac);

    releaseBtn.onclick = function() {
        if (!confirm("Stop playback and release the DAC now?")) { return; }
        releaseBtn.disabled    = true;
        releaseBtn.textContent = "Releasing…";
        status.textContent = "";
        fetch("/tidal/dac/release")
            .then(function(res) { return res.json(); })
            .then(function(d) {
                releaseBtn.disabled    = false;
                releaseBtn.textContent = "Release DAC";
                if (d.error) {
                    status.textContent = "Failed: " + d.error;
                } else {
                    status.textContent = "DAC released. You can now change audio output.";
                    playing = false;
                    updatePlayPauseIcon();
                    loadDacUi("DAC released. You can now change audio output.");
                }
            })
            .catch(function() {
                releaseBtn.disabled    = false;
                releaseBtn.textContent = "Release DAC";
                status.textContent = "Request failed. Check the Pi is reachable.";
            });
    };

    exclusiveBtn.onclick = function() {
        exclusiveBtn.disabled    = true;
        exclusiveBtn.textContent = "Grabbing DAC…";
        status.textContent = "";
        fetch("/tidal/dac/exclusive")
            .then(function(res) { return res.json(); })
            .then(function(d) {
                exclusiveBtn.disabled    = false;
                exclusiveBtn.textContent = "Exclusive Mode";
                if (d.error) {
                    status.textContent = "Failed: " + d.error;
                } else {
                    status.textContent = "Exclusive mode set. Press Play to start bit-perfect playback.";
                    loadDacUi("Exclusive mode set. Press Play to start bit-perfect playback.");
                }
            })
            .catch(function() {
                exclusiveBtn.disabled    = false;
                exclusiveBtn.textContent = "Exclusive Mode";
                status.textContent = "Request failed. Check the Pi is reachable.";
            });
    };

    loadDacUi();
    return sec;
}


function buildLastfmFeatureNote(text) {
    var note = document.createElement("div");
    note.className = "settingsDependencyNote settingsLastfmNote";

    var icon = document.createElement("span");
    icon.className = "material-icons";
    icon.textContent = "info";

    var copy = document.createElement("span");
    copy.textContent = text;

    note.appendChild(icon);
    note.appendChild(copy);
    return note;
}

function buildAutoMixSection(st) {
    st = st || {};
    var lastfmReady = !!st.lastfm_connected;

    var sec = document.createElement("div");
    sec.className = "settingsSection";
    if (!lastfmReady) {
        sec.classList.add("settingsFeatureLocked", "settingsAutoMixLocked");
    }

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle";
    titleRow.innerHTML = '<span class="material-icons">auto_awesome</span> Auto-Mix';
    sec.appendChild(titleRow);

    var desc = document.createElement("div");
    desc.className   = "settingsSectionDesc";
    desc.textContent = "Create a Tidal playlist based on listener affinity for any artist.";
    sec.appendChild(desc);

    var amLastfmNote = buildLastfmFeatureNote(lastfmReady ?
        "Auto-Mix uses Last.fm listener affinity data. Last.fm is connected, so Auto-Mix is ready." :
        "Auto-Mix uses Last.fm listener affinity data. Connect Last.fm in Scrobbling settings and add your API key to enable Auto-Mix.");
    sec.appendChild(amLastfmNote);

    var artistRow = document.createElement("div");
    artistRow.className = "settingsField";
    var artistLabel = document.createElement("label");
    artistLabel.className   = "settingsLabel";
    artistLabel.textContent = "Artist";
    var artistWrap = document.createElement("div");
    artistWrap.style.position = "relative";
    var artistInput = document.createElement("input");
    artistInput.type        = "text";
    artistInput.placeholder = lastfmReady ? "Artist name" : "Connect Last.fm first";
    artistInput.className   = "settingsInput";
    artistInput.disabled    = !lastfmReady;
    var dropdown = document.createElement("div");
    dropdown.className    = "amDropdown";
    dropdown.style.display = "none";
    artistWrap.appendChild(artistInput);
    artistWrap.appendChild(dropdown);
    artistRow.appendChild(artistLabel);
    artistRow.appendChild(artistWrap);
    sec.appendChild(artistRow);

    var _amDebounceTimer = null;
    artistInput.oninput = function() {
        if (!lastfmReady) { dropdown.style.display = "none"; return; }
        clearTimeout(_amDebounceTimer);
        var q = artistInput.value.trim();
        if (!q) { dropdown.style.display = "none"; return; }
        _amDebounceTimer = setTimeout(function() {
            fetch("/api/automix/search?q=" + encodeURIComponent(q))
                .then(function(res) { return res.json(); })
                .then(function(names) {
                    dropdown.innerHTML = "";
                    if (!names || !names.length) { dropdown.style.display = "none"; return; }
                    names.forEach(function(name) {
                        var item = document.createElement("div");
                        item.className   = "amDropdownItem";
                        item.textContent = name;
                        item.onclick = function() {
                            artistInput.value      = name;
                            dropdown.style.display = "none";
                        };
                        dropdown.appendChild(item);
                    });
                    dropdown.style.display = "block";
                })
                .catch(function() { dropdown.style.display = "none"; });
        }, 300);
    };

    document.addEventListener("click", function(e) {
        if (!artistWrap.contains(e.target)) { dropdown.style.display = "none"; }
    });

    var depthRow = document.createElement("div");
    depthRow.className = "amDepthRow";
    var depths = ["Essential", "Balanced", "Deep"];
    var selectedDepth = "balanced";
    var depthBtns = {};
    depths.forEach(function(d) {
        var btn = document.createElement("button");
        btn.className   = "amDepthBtn" + (d.toLowerCase() === selectedDepth ? " amDepthBtnActive" : "");
        btn.textContent = d;
        btn.disabled = !lastfmReady;
        btn.onclick = function() {
            if (!lastfmReady) { return; }
            selectedDepth = d.toLowerCase();
            depths.forEach(function(x) {
                depthBtns[x].className = "amDepthBtn" + (x.toLowerCase() === selectedDepth ? " amDepthBtnActive" : "");
            });
        };
        depthBtns[d] = btn;
        depthRow.appendChild(btn);
    });
    sec.appendChild(depthRow);

    var status = document.createElement("div");
    status.className = "settingsStatus";
    sec.appendChild(status);

    var createBtn = document.createElement("button");
    createBtn.className   = "settingsBtn";
    createBtn.textContent = lastfmReady ? "CREATE MIX" : "CONNECT LAST.FM TO ENABLE";
    createBtn.disabled = !lastfmReady;
    createBtn.onclick = function() {
        if (!lastfmReady) {
            status.textContent = "Connect Last.fm in Scrobbling settings to enable Auto-Mix.";
            return;
        }
        var a = artistInput.value.trim();
        if (!a) { status.textContent = "Enter an artist name."; return; }
        createBtn.disabled = true;
        status.textContent = "Building mix for \"" + a + "\"...";
        var depthLabel = selectedDepth.charAt(0).toUpperCase() + selectedDepth.slice(1);
        fetch("/api/automix/create", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ artist: a, depth: selectedDepth, playlist_name: "Auto-Mix: " + a + " \u2014 " + depthLabel })
        })
        .then(function(res) { return res.json(); })
        .then(function(d) {
            createBtn.disabled = false;
            if (d.error) {
                status.textContent = "Failed: " + d.error;
            } else {
                status.textContent = "Created \"" + d.playlist_name + "\" \u2014 " + d.track_count + " tracks.";
            }
        })
        .catch(function() {
            createBtn.disabled = false;
            status.textContent = "Request failed. Check the server is reachable.";
        });
    };
    sec.appendChild(createBtn);

    return sec;
}

function buildInfinitePlaySection(st) {
    st = st || {};
    var lastfmReady = !!st.lastfm_connected;
    tidalInfinitePlayLastfmConnected = lastfmReady;
    tidalInfinitePlayEnabled = !!st.tidal_infinite_play_enabled;
    tidalInfinitePlayMode = normalizeTidalInfinitePlayMode(st.tidal_infinite_play_mode);
    updatePlayerInfinitePlayControl();
    if (!lastfmReady && tidalInfinitePlayMode !== "same_artist") {
        tidalInfinitePlayMode = "same_artist";
        updatePlayerInfinitePlayControl();
        fetch("/api/settings/tidal-infinite-play", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: tidalInfinitePlayEnabled, mode: tidalInfinitePlayMode })
        })
        .catch(function(e) {
            console.info("Infinite Play mode fallback save failed:", e);
        });
    }

    var sec = document.createElement("div");
    sec.className = "settingsSection settingsInfinitePlaySection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle";
    titleRow.innerHTML = '<span class="material-icons">all_inclusive</span> Infinite Play';
    sec.appendChild(titleRow);

    var desc = document.createElement("div");
    desc.className   = "settingsSectionDesc";
    desc.textContent = "When enabled, SROVA uses Last.fm recommendations from the ending track\u2019s artist and adds TIDAL tracks to the queue.";
    sec.appendChild(desc);

    var note = buildLastfmFeatureNote("Requires TIDAL login, Last.fm setup, and a playable TIDAL seed track.");
    sec.appendChild(note);

    var row = document.createElement("div");
    row.className = "settingsToggleRow";

    var labelWrap = document.createElement("div");
    labelWrap.className = "settingsToggleCopy";
    var label = document.createElement("div");
    label.className = "settingsLabel";
    label.textContent = "Infinite Play";
    var sub = document.createElement("div");
    sub.className = "settingsToggleSub";
    sub.textContent = tidalInfinitePlayEnabled ? "Enabled" : "Disabled";
    labelWrap.appendChild(label);
    labelWrap.appendChild(sub);

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "settingsToggleSwitch" + (tidalInfinitePlayEnabled ? " active" : "");
    toggle.setAttribute("aria-pressed", tidalInfinitePlayEnabled ? "true" : "false");
    toggle.innerHTML = '<span></span>';

    function setToggleVisual(enabled) {
        toggle.className = "settingsToggleSwitch" + (enabled ? " active" : "");
        toggle.setAttribute("aria-pressed", enabled ? "true" : "false");
        sub.textContent = enabled ? "Enabled" : "Disabled";
    }

    toggle.onclick = function() {
        var next = !tidalInfinitePlayEnabled;
        toggle.disabled = true;
        saveInfinitePlaySettings(next, tidalInfinitePlayMode, function() {
            setToggleVisual(tidalInfinitePlayEnabled);
            updateModeButtons();
        }, function() {
            toggle.disabled = false;
        }, function() {
            setToggleVisual(tidalInfinitePlayEnabled);
            updateModeButtons();
        });
    };

    row.appendChild(labelWrap);
    row.appendChild(toggle);
    sec.appendChild(row);

    var modeRow = document.createElement("div");
    modeRow.className = "amDepthRow infinitePlayModeRow";
    var modeButtons = {};
    [
        ["same_artist", "Same Artist"],
        ["similar_artist", "Similar Artists"],
        ["surprise_me", "Surprise Me"]
    ].forEach(function(modeDef) {
        var btn = document.createElement("button");
        btn.className = "amDepthBtn";
        btn.textContent = modeDef[1];
        btn.onclick = function() {
            var nextMode = modeDef[0];
            if (nextMode === tidalInfinitePlayMode) { return; }
            btn.disabled = true;
            saveInfinitePlaySettings(tidalInfinitePlayEnabled, nextMode, function() {
                setToggleVisual(tidalInfinitePlayEnabled);
                updateModeButtons();
            }, function() {
                btn.disabled = false;
            }, function() {
                setToggleVisual(tidalInfinitePlayEnabled);
                updateModeButtons();
            });
        };
        modeButtons[modeDef[0]] = btn;
        modeRow.appendChild(btn);
    });

    function updateModeButtons() {
        Object.keys(modeButtons).forEach(function(modeKey) {
            var unavailable = !lastfmReady && modeKey !== "same_artist";
            var active = modeKey === tidalInfinitePlayMode;
            var btn = modeButtons[modeKey];
            btn.className = "amDepthBtn " + getInfinitePlayModeClass(modeKey) + (active ? " amDepthBtnActive" : "") + (unavailable ? " infinitePlayModeDisabled" : "");
            btn.disabled = unavailable;
            btn.setAttribute("aria-pressed", active ? "true" : "false");
            btn.setAttribute("aria-disabled", unavailable ? "true" : "false");
            btn.title = unavailable ? "Connect Last.fm to use this mode." : "";
        });
    }

    updateModeButtons();
    sec.appendChild(modeRow);

    return sec;
}


function buildPlaylistMaintenanceSection() {
    var sec = document.createElement("div");
    sec.className = "settingsSection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle";
    titleRow.innerHTML = '<span class="material-icons">playlist_remove</span> Playlist Maintenance';
    sec.appendChild(titleRow);

    var desc = document.createElement("div");
    desc.className   = "settingsSectionDesc";
    desc.textContent = "Find and remove duplicate playlists. Two playlists are considered duplicates if they share the same name, track count, and total duration (within 30 seconds). The longer copy is always kept.";
    sec.appendChild(desc);

    var status = document.createElement("div");
    status.className = "settingsStatus";
    sec.appendChild(status);

    // Button row: Refresh Playlists | Find Duplicates
    var btnRow = document.createElement("div");
    btnRow.className = "dupBtnRow";

    // --- Refresh Playlists button ---
    var refreshBtn = document.createElement("button");
    refreshBtn.className   = "settingsBtn";
    refreshBtn.innerHTML   = '<span class="material-icons" style="font-size:16px;vertical-align:middle;margin-right:4px">refresh</span>Refresh Playlists';
    refreshBtn.onclick = function() {
        refreshBtn.disabled = true;
        findBtn.disabled    = true;
        status.textContent  = "Clearing cache...";
        resultsEl.innerHTML = "";
        // Invalidate server-side playlist cache
        fetch("/cache/clear").then(function() {
            status.textContent = "Fetching from Tidal...";
            // Trigger background fetch
            fetch("/tidal/myplaylists").catch(function() {});
            // Poll until playlists land in cache
            var attempts = 0;
            function _poll() {
                attempts++;
                fetch("/tidal/myplaylists")
                    .then(function(r) { return r.json(); })
                    .then(function(pls) {
                        if (pls && pls.length > 0) {
                            refreshBtn.disabled = false;
                            findBtn.disabled    = false;
                            playlistsLoaded     = false;
                            status.textContent  = pls.length + " playlists loaded. Ready to scan.";
                        } else if (attempts < 12) {
                            status.textContent = "Fetching from Tidal (" + attempts + "/12)...";
                            setTimeout(_poll, 15000);
                        } else {
                            refreshBtn.disabled = false;
                            findBtn.disabled    = false;
                            status.textContent  = "Could not load playlists. Try again.";
                        }
                    })
                    .catch(function() {
                        refreshBtn.disabled = false;
                        findBtn.disabled    = false;
                        status.textContent  = "Refresh failed.";
                    });
            }
            setTimeout(_poll, 3000);
        }).catch(function() {
            refreshBtn.disabled = false;
            findBtn.disabled    = false;
            status.textContent  = "Refresh failed.";
        });
    };
    btnRow.appendChild(refreshBtn);

    // --- Find Duplicates button ---
    var findBtn = document.createElement("button");
    findBtn.className   = "settingsBtn";
    findBtn.textContent = "Find Duplicates";
    findBtn.onclick = function() {
        findBtn.disabled    = true;
        findBtn.textContent = "Scanning...";
        status.textContent  = "";
        resultsEl.innerHTML = "";
        fetch("/tidal/playlists/find_duplicates")
            .then(function(res) { return res.json(); })
            .then(function(data) {
                findBtn.disabled    = false;
                findBtn.textContent = "Find Duplicates";
                if (data.error) {
                    status.textContent = data.message || "Could not scan. Refresh playlists first.";
                    return;
                }
                renderDupResults(data, resultsEl, status, findBtn);
            })
            .catch(function() {
                findBtn.disabled    = false;
                findBtn.textContent = "Find Duplicates";
                status.textContent  = "Scan failed. Please try again.";
            });
    };
    btnRow.appendChild(findBtn);

    sec.appendChild(btnRow);

    var resultsEl = document.createElement("div");
    resultsEl.className = "dupResults";
    sec.appendChild(resultsEl);

    return sec;
}

function renderDupResults(data, resultsEl, status, findBtn) {
    resultsEl.innerHTML = "";
    var groups = data.groups || [];
    var total  = data.total_to_delete || 0;

    if (groups.length === 0) {
        status.textContent = "No duplicates found.";
        return;
    }

    status.textContent = "Found " + total + " duplicate" + (total === 1 ? "" : "s") +
                         " across " + groups.length + " playlist name" +
                         (groups.length === 1 ? "" : "s") + ".";

    // Build id -> DOM row map so we can remove rows live after delete
    var rowMap = {};   // playlist_id -> {row, groupEl}

    // Collect all IDs to delete
    var toDeleteIds = [];
    groups.forEach(function(g) {
        g.delete.forEach(function(pl) { toDeleteIds.push(pl.id); });
    });

    // Render preview groups
    groups.forEach(function(g) {
        var groupEl = document.createElement("div");
        groupEl.className = "dupGroup";

        var nameEl = document.createElement("div");
        nameEl.className   = "dupGroupName";
        nameEl.textContent = g.name;
        groupEl.appendChild(nameEl);

        g.keep.forEach(function(pl) {
            var row = _dupRow(pl, true);
            groupEl.appendChild(row);
        });
        g.delete.forEach(function(pl) {
            var row = _dupRow(pl, false);
            groupEl.appendChild(row);
            rowMap[pl.id] = { row: row, groupEl: groupEl };
        });

        resultsEl.appendChild(groupEl);
    });

    // Confirm delete button
    var confirmBtn = document.createElement("button");
    confirmBtn.className   = "settingsBtn settingsBtnDanger dupConfirmBtn";
    confirmBtn.textContent = "Delete " + total + " Duplicate" + (total === 1 ? "" : "s");
    confirmBtn.onclick = function() {
        if (!confirm("Permanently delete " + total + " playlist" +
                     (total === 1 ? "" : "s") + " from Tidal? This cannot be undone.")) {
            return;
        }
        confirmBtn.disabled    = true;
        confirmBtn.textContent = "Deleting...";
        fetch("/tidal/playlists/delete_duplicates", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ ids: toDeleteIds })
        })
        .then(function(res) { return res.json(); })
        .then(function(d) {
            var deleted = d.deleted || [];
            var failed  = d.failed  || [];

            // Animate out each successfully deleted row
            deleted.forEach(function(pid) {
                var entry = rowMap[pid];
                if (!entry) { return; }
                entry.row.classList.add("dupRowDeleted");
                // After fade, remove row; if group is now empty (only name left) remove group too
                setTimeout(function() {
                    if (entry.row.parentNode) {
                        entry.row.parentNode.removeChild(entry.row);
                    }
                    // Remove group card if no dupDelete rows remain
                    var remaining = entry.groupEl.querySelectorAll(".dupDelete");
                    if (remaining.length === 0) {
                        if (entry.groupEl.parentNode) {
                            entry.groupEl.parentNode.removeChild(entry.groupEl);
                        }
                    }
                }, 350);
            });

            var n = deleted.length;
            var f = failed.length;
            if (f > 0) {
                status.textContent = "Deleted " + n + " playlist" + (n === 1 ? "" : "s") +
                                     ". " + f + " failed -- check logs.";
            } else {
                status.textContent = "Done! Deleted " + n + " duplicate playlist" +
                                     (n === 1 ? "" : "s") + ".";
            }
            // Remove confirm button, reset find button, mark playlists stale
            if (confirmBtn.parentNode) { confirmBtn.parentNode.removeChild(confirmBtn); }
            findBtn.disabled    = false;
            findBtn.textContent = "Find Duplicates";
            playlistsLoaded     = false;
        })
        .catch(function() {
            confirmBtn.disabled    = false;
            confirmBtn.textContent = "Delete " + total + " Duplicate" + (total === 1 ? "" : "s");
            status.textContent     = "Deletion failed. Please try again.";
        });
    };
    resultsEl.appendChild(confirmBtn);
}

function _dupRow(pl, isKeep) {
    var row = document.createElement("div");
    row.className = "dupRow " + (isKeep ? "dupKeep" : "dupDelete");
    var icon = document.createElement("span");
    icon.className = "material-icons dupRowIcon";
    icon.textContent = isKeep ? "check_circle" : "cancel";
    var info = document.createElement("div");
    info.className = "dupRowInfo";
    var durSecs = pl.duration || 0;
    var durStr  = Math.floor(durSecs / 60) + "m " + (durSecs % 60) + "s";
    info.innerHTML =
        '<div class="dupRowName">' + (pl.name || "") + '</div>' +
        '<div class="dupRowSub">' +
            (pl.num_tracks || 0) + " tracks &nbsp;&middot;&nbsp; " + durStr + " total" +
            (isKeep ? " &nbsp;&middot;&nbsp; <b>keep</b>" : " &nbsp;&middot;&nbsp; <b>remove</b>") +
        '</div>';
    row.appendChild(icon);
    row.appendChild(info);
    return row;
}


function updateLoginBtn(loggedIn, options) {
    options = options || {};
    var changed = (isLoggedIn !== loggedIn);
    isLoggedIn = loggedIn;
    if (!loggedIn) {
        hideNowPlayingAlbumAction();
        globalSearchTidalRequestSerial += 1;
        globalSearchTidalReady = false;
        setGlobalSearchVisible(globalSearchRequestedVisible);
    }
    // loginBtn is no longer in the header -- only update DOM if it still exists
    if (loginBtn) {
        var icon = loginBtn.querySelector(".material-icons");
        if (icon) {
            icon.textContent = loggedIn ? "logout" : "account_circle";
        }
    }
    // Only refresh settings page if login state actually changed and page is open
    if (!options.skipSettingsRefresh && changed && settingsView && settingsView.style.display !== "none") {
        renderSettings();
    }
}

function handleLoginLogout() {
    if (isLoggedIn) { doLogout(); }
    else            { startLogin(); }
}


// --- Login flow ---

function startLogin(options) {
    options = options || {};
    _tidalLoginReturnToSettings = !!options.returnToSettings ||
        !!(settingsView && settingsView.style.display !== "none" && currentSettingsTab === "tidal");
    loginError.classList.add("hidden");
    loginWaiting.classList.remove("hidden");
    loginModal.classList.remove("hidden");
    fetch("/tidal/login/start", {cache: "no-store"})
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.error) { showLoginError(); return; }
            loginUrlEl.href        = data.url;
            loginUrlEl.textContent = data.url;
            startLoginPoll();
        })
        .catch(function() { showLoginError(); });
}

function startLoginPoll() {
    clearInterval(loginPollTimer);
    loginPollTimer = setInterval(function() {
        fetch("/tidal/login/poll", {cache: "no-store"})
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (data.logged_in) {
                    clearInterval(loginPollTimer);
                    loginModal.classList.add("hidden");
                    updateLoginBtn(true, {skipSettingsRefresh: true});
                    playlistsLoaded = false;
                    if (_tidalLoginReturnToSettings) {
                        _tidalLoginReturnToSettings = false;
                        currentSettingsTab = "tidal";
                        showView("settings");
                        renderSettings();
                    } else {
                        loadHome();
                    }
                } else if (data.error && !data.pending) {
                    clearInterval(loginPollTimer);
                    showLoginError();
                }
            })
            .catch(function() {});
    }, 3000);
}

function showLoginError() {
    loginWaiting.classList.add("hidden");
    loginError.classList.remove("hidden");
}

function cancelLogin() {
    clearInterval(loginPollTimer);
    _tidalLoginReturnToSettings = false;
    loginModal.classList.add("hidden");
}

function doLogout(options) {
    options = options || {};
    fetch("/tidal/logout", {cache: "no-store"})
        .then(function(res) { return res.json(); })
        .then(function() {
            updateLoginBtn(false, {skipSettingsRefresh: true});
            if (homeSections) { homeSections.innerHTML = ""; }
            if (playlistsContent) { playlistsContent.innerHTML = ""; }
            playlistsLoaded = false;
            if (options.returnToSettings) {
                currentSettingsTab = "tidal";
                showView("settings");
                renderSettings();
            } else {
                loadHome();
            }
        })
        .catch(function() {
            updateLoginBtn(false, {skipSettingsRefresh: true});
            if (options.returnToSettings) {
                currentSettingsTab = "tidal";
                showView("settings");
                renderSettings();
            }
        });
}


function updateExclusiveLock(exclusive, isHiRes) {
    if (!exclusiveLock) { return; }
    var cls, ttl;
    if (!exclusive) {
        cls = "exclusiveLock exclusiveLockOff";
        ttl = "Exclusive mode off";
    } else if (isHiRes) {
        cls = "exclusiveLock exclusiveLockHiRes";
        ttl = "Exclusive mode \u2022 Hi-Res";
    } else {
        cls = "exclusiveLock exclusiveLockCD";
        ttl = "Exclusive mode \u2022 CD";
    }
    exclusiveLock.className = cls;
    exclusiveLock.title     = ttl;
    if (npExclusiveLock) {
        npExclusiveLock.className = cls;
        npExclusiveLock.title     = ttl;
    }
    syncDacNameDisplay();
}

// Lock click handler for the srova skin. Reuses the existing Settings DAC
// endpoints -- NO new release/reacquire logic. If the lock is lit (exclusive
// mode held), click releases. If the lock is grey (off), click re-acquires.
// Guarded by the "busy" class so rapid clicks don't double-fire.
function toggleExclusiveFromLock() {
    if (!exclusiveLock) { return; }
    if (exclusiveLock.classList.contains("busy")) { return; }
    var isOff = exclusiveLock.classList.contains("exclusiveLockOff");
    exclusiveLock.classList.add("busy");
    var endpoint = isOff ? "/tidal/dac/exclusive" : "/tidal/dac/release";
    fetch(endpoint)
        .then(function(res) { return res.json(); })
        .then(function(d) {
            exclusiveLock.classList.remove("busy");
            if (!isOff && !d.error) {
                // Mirror the Settings Release flow: stop the transport on success
                playing = false;
                updatePlayPauseIcon();
            }
        })
        .catch(function() {
            exclusiveLock.classList.remove("busy");
        });
}


// --- Status polling ---

function updateRadioMetadata(meta) {
    var raw = (meta && meta.raw) ? meta.raw : "";
    if (raw === _lastRadioMetaRaw) { return; }
    _lastRadioMetaRaw = raw;

    var artist = (meta && meta.artist) ? meta.artist : "";
    var title  = (meta && meta.title)  ? meta.title  : "";
    var hasData = !!(artist || title);

    playerArtist.style.display = hasData ? "none" : "";

    radioArtistPlayerBar.textContent  = artist;
    radioTitlePlayerBar.textContent   = title;
    radioArtistPlayerBar.style.display  = hasData ? "" : "none";
    radioTitlePlayerBar.style.display   = hasData ? "" : "none";

    radioArtistNowPlaying.textContent = artist;
    radioTitleNowPlaying.textContent  = title;
    radioArtistNowPlaying.style.display = hasData ? "" : "none";
    radioTitleNowPlaying.style.display  = hasData ? "" : "none";
}

function resetProgressDisplay() {
    startTime = Date.now() / 1000;
    currentDuration = 0;
    progressFill._elapsed = 0;
    progressFill.style.width = "0%";
    currentTimeEl.textContent = "0:00";
    totalTimeEl.textContent = "0:00";
    if (nowPlayingFill) { nowPlayingFill.style.width = "0%"; }
    if (nowPlayingCurrent) { nowPlayingCurrent.textContent = "0:00"; }
    if (nowPlayingTotal) { nowPlayingTotal.textContent = "0:00"; }
}

function clearPlaybackTechDisplay() {
    lastTechText = "";
    lastTechClass = "hidden";
    document.body.classList.remove("hires");
    if (albumTechInfo) { albumTechInfo.classList.add("hidden"); }
    if (nowPlayingQuality) {
        nowPlayingQuality.textContent = "";
        nowPlayingQuality.className = "hidden";
    }
    var playerMeta = document.getElementById("playerMeta");
    if (playerMeta) {
        playerMeta.textContent = "READY";
        playerMeta.className = "audioInfoBox audioInfoOff";
    }
}

function applyStandbyPlayerBar() {
    playing = false;
    currentPlayingId = "";
    setPlayerHasActiveMedia(false);
    setPlayerBarActivePlaybackSource("");
    resetProgressDisplay();
    clearPlaybackTechDisplay();
    updateRadioMetadata({});
    document.body.classList.remove("radioMode");
    playerArt.src = SROVA_STANDBY_ART;
    playerTrack.textContent = "SROVA";
    playerArtist.textContent = "Ready";
    playerArtist.style.display = "";
    playerBar.classList.remove("hidden");
    updatePlayPauseIcon();
    updateExclusiveLock(false, false);
    updateBitPerfectReadout({
        bit_perfect_path_confirmed: false,
        bit_perfect_reason: "Nothing playing"
    }, false);
    _updatePlayerBarLinks({});
    updateHomeHeroNowPlaying({
        playing: false,
        current_track_valid: false,
        playback_state: "idle"
    });
    if (nowPlayingView && !nowPlayingView.classList.contains("hidden")) {
        nowPlayingArt.src = SROVA_STANDBY_ART;
        nowPlayingTrack.textContent = "SROVA";
        nowPlayingArtist.textContent = "Ready";
        if (nowPlayingFrom) { nowPlayingFrom.textContent = ""; }
        if (nowPlayingQuality) {
            nowPlayingQuality.textContent = "";
            nowPlayingQuality.className = "hidden";
        }
    }
    highlightCurrentTrack();
    _syncHomePlayingTiles();
}

function isPausedRadioStatus(s) {
    return !!(s && s.radio_mode && s.radio_station && !s.playing && s.playback_state !== "playing");
}

function clearRadioIdleStandbyTimer() {
    if (radioIdleStandbyTimer) {
        clearTimeout(radioIdleStandbyTimer);
        radioIdleStandbyTimer = null;
    }
    radioIdleStandbyDueAt = 0;
    radioIdleStandbyRequestInFlight = false;
    radioIdleStandbyApplied = false;
}

function applyRadioIdleStandbyStatus() {
    lastKnownPlaybackStatus = {
        playing: false,
        playback_state: "idle",
        current_track_valid: false,
        source: null,
        radio_mode: false,
        radio_station: null,
        radio_metadata: {}
    };
    applyStandbyPlayerBar();
}

function postRadioIdleStandby() {
    var options = { method: "POST" };
    if (typeof fetchWithTimeout === "function") {
        return fetchWithTimeout("/api/radio/standby", options, 3500);
    }
    return fetch("/api/radio/standby", options);
}

function triggerRadioIdleStandby() {
    if (radioIdleStandbyApplied || radioIdleStandbyRequestInFlight) { return; }
    if (!isPausedRadioStatus(lastKnownPlaybackStatus)) { return; }
    radioIdleStandbyApplied = true;
    radioIdleStandbyRequestInFlight = true;
    if (radioIdleStandbyTimer) {
        clearTimeout(radioIdleStandbyTimer);
        radioIdleStandbyTimer = null;
    }
    postRadioIdleStandby()
        .then(function(res) { return res.json().catch(function() { return {}; }); })
        .then(function(data) {
            radioIdleStandbyRequestInFlight = false;
            if (data && data.ok && data.cleared && isPausedRadioStatus(lastKnownPlaybackStatus)) {
                radioIdleStandbyDueAt = 0;
                applyRadioIdleStandbyStatus();
            } else {
                radioIdleStandbyApplied = false;
            }
        })
        .catch(function() {
            radioIdleStandbyRequestInFlight = false;
            radioIdleStandbyApplied = false;
        });
}

function scheduleRadioIdleStandby() {
    if (!isPausedRadioStatus(lastKnownPlaybackStatus)) { return; }
    if (radioIdleStandbyApplied || radioIdleStandbyRequestInFlight) { return; }
    if (radioIdleStandbyDueAt && Date.now() >= radioIdleStandbyDueAt) {
        triggerRadioIdleStandby();
        return;
    }
    if (radioIdleStandbyTimer) { return; }
    radioIdleStandbyDueAt = Date.now() + RADIO_IDLE_STANDBY_DELAY_MS;
    radioIdleStandbyTimer = setTimeout(function() {
        radioIdleStandbyTimer = null;
        triggerRadioIdleStandby();
    }, RADIO_IDLE_STANDBY_DELAY_MS);
}

function homeHeroNowPlayingParts(title, artist, fallbackTitle) {
    title = String(title || "").trim();
    artist = String(artist || "").trim();
    fallbackTitle = String(fallbackTitle || "").trim();
    if (!title) {
        return {
            title: fallbackTitle,
            text: fallbackTitle
        };
    }
    return {
        title: title,
        text: artist ? title + " - " + artist : title
    };
}

function deriveHomeHeroNowPlayingModel(s) {
    var active = !!(s && s.playing && s.current_track_valid !== false && s.playback_state !== "idle");
    if (!active) {
        return {
            active: false,
            source: "",
            imageUrl: SROVA_STANDBY_ART,
            text: ""
        };
    }

    var source = "";
    var imageUrl = "";
    var parts = { title: "", text: "" };
    if (s.radio_mode && s.radio_station) {
        var station = s.radio_station || {};
        var meta = s.radio_metadata || {};
        source = "radio";
        imageUrl = s.radio_cover_art_url || s.radio_art_url || station.icon || SROVA_STANDBY_ART;
        parts = homeHeroNowPlayingParts(
            meta.title || s.radio_cover_art_title || "",
            meta.artist || s.radio_cover_art_artist || "",
            station.name || "Radio"
        );
    } else {
        source = inferStatusPlaybackSource(s);
        imageUrl = s.cover || SROVA_STANDBY_ART;
        parts = homeHeroNowPlayingParts(s.title || "", s.artist || "", "");
    }

    return {
        active: true,
        source: source,
        imageUrl: imageUrl || SROVA_STANDBY_ART,
        text: parts.text || ""
    };
}

function setHomeHeroActiveSource(source) {
    var nodes = document.querySelectorAll("[data-home-source]");
    for (var i = 0; i < nodes.length; i++) {
        var nodeSource = nodes[i].getAttribute("data-home-source") || "";
        nodes[i].classList.toggle("srovaHomeSourceActive", !!source && nodeSource === source);
    }
}

function applyHomeHeroNowPlayingModel(model) {
    var gateway = document.getElementById("srovaGateway");
    var logo = document.getElementById("srovaGatewayLogo");
    var nowPlaying = document.getElementById("srovaHomeNowPlaying");
    if (!gateway || !logo || !nowPlaying) { return; }

    var key = [
        model.active ? "1" : "0",
        model.source || "",
        model.imageUrl || "",
        model.text || ""
    ].join("|");
    if (key === homeHeroNowPlayingStateKey) { return; }
    homeHeroNowPlayingStateKey = key;

    var token = ++homeHeroNowPlayingToken;
    var targetImage = model.imageUrl || SROVA_STANDBY_ART;
    var targetText = model.text || "";
    var targetSource = model.source || "";

    function commitHero(imageUrl) {
        if (token !== homeHeroNowPlayingToken) { return; }
        gateway.classList.add("srovaHomeHeroSwapping");
        window.setTimeout(function() {
            if (token !== homeHeroNowPlayingToken) { return; }
            logo.src = imageUrl || SROVA_STANDBY_ART;
            nowPlaying.textContent = targetText;
            nowPlaying.classList.toggle("isActive", !!(model.active && targetText));
            gateway.classList.toggle("srovaHomeHeroNowPlaying", !!model.active);
            setHomeHeroActiveSource(targetSource);
            window.setTimeout(function() {
                if (token === homeHeroNowPlayingToken) {
                    gateway.classList.remove("srovaHomeHeroSwapping");
                }
            }, 320);
        }, 300);
    }

    if (targetImage === logo.getAttribute("src")) {
        commitHero(targetImage);
        return;
    }

    var preload = new Image();
    preload.onload = function() { commitHero(targetImage); };
    preload.onerror = function() { commitHero(SROVA_STANDBY_ART); };
    preload.src = targetImage;
}

function updateHomeHeroNowPlaying(s) {
    var gateway = document.getElementById("srovaGateway");
    if (!gateway) { return; }
    applyHomeHeroNowPlayingModel(deriveHomeHeroNowPlayingModel(s));
}

function resetTidalInfinitePlayGuard() {
    tidalInfinitePlayRefillInFlight = false;
    tidalInfinitePlayLastRefillKey = "";
}

function releaseTidalInfinitePlayRefillKey(refillKey) {
    if (tidalInfinitePlayLastRefillKey === refillKey) {
        tidalInfinitePlayLastRefillKey = "";
    }
}

function normalizeTidalInfinitePlayMode(mode) {
    mode = String(mode || "").toLowerCase();
    if (mode === "same_artist" || mode === "similar_artist" || mode === "surprise_me") {
        return mode;
    }
    return "similar_artist";
}

function getInfinitePlayModeLabel(mode) {
    mode = normalizeTidalInfinitePlayMode(mode);
    if (mode === "same_artist") { return "Same Artist"; }
    if (mode === "surprise_me") { return "Surprise Me"; }
    return "Similar Artists";
}

function getInfinitePlayModeClass(mode) {
    mode = normalizeTidalInfinitePlayMode(mode);
    if (mode === "same_artist") { return "infinitePlayModeSame srovaIpModeSame"; }
    if (mode === "surprise_me") { return "infinitePlayModeSurprise srovaIpModeSurprise"; }
    return "infinitePlayModeSimilar srovaIpModeSimilar";
}

function saveInfinitePlaySettings(nextEnabled, nextMode, onSuccess, onDone, onError) {
    fetch("/api/settings/tidal-infinite-play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            enabled: nextEnabled,
            mode: nextMode
        })
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (!data || data.ok === false) { throw new Error((data && data.error) || "setting failed"); }
        tidalInfinitePlayEnabled = !!data.enabled;
        tidalInfinitePlayMode = normalizeTidalInfinitePlayMode(data.mode);
        resetTidalInfinitePlayGuard();
        updatePlayerInfinitePlayControl();
        if (onSuccess) { onSuccess(data); }
    })
    .catch(function(e) {
        console.warn("Infinite Play setting failed:", e);
        updatePlayerInfinitePlayControl();
        if (onError) { onError(e); }
    })
    .then(function() {
        if (onDone) { onDone(); }
    });
}

function updatePlayerInfinitePlayControl() {
    if (!playerInfinitePlayControl || !playerInfinitePlayBtn || !playerInfinitePlayMenu) { return; }
    syncPlayerInfinitePlayPhoneTrayPlacement();

    var enabled = !!tidalInfinitePlayEnabled;
    var uiVisible = shouldShowInfinitePlayUi(enabled);
    var mode = normalizeTidalInfinitePlayMode(tidalInfinitePlayMode);
    var modeClass = getInfinitePlayModeClass(mode);
    var modeLabel = getInfinitePlayModeLabel(mode);
    var isOpen = playerInfinitePlayControl.classList.contains("infinite-play-menu-open");
    if (!uiVisible && isOpen) {
        closePlayerInfinitePlayMenu();
        isOpen = false;
    }

    // UI-only TIDAL visibility guard. Infinite Play behavior/settings are unchanged.
    if (document.body) {
        document.body.classList.toggle("srovaInfinitePlayUiVisible", uiVisible);
    }
    playerInfinitePlayControl.className = "playerInfinitePlayControl " + modeClass + (enabled ? " is-enabled" : " is-disabled") + (uiVisible ? " is-tidal-visible" : " is-source-hidden") + (isOpen ? " infinite-play-menu-open" : "");
    playerInfinitePlayControl.setAttribute("aria-hidden", uiVisible ? "false" : "true");
    playerInfinitePlayBtn.setAttribute("aria-expanded", uiVisible && isOpen ? "true" : "false");
    playerInfinitePlayBtn.setAttribute("aria-label", "Infinite Play: " + modeLabel);
    playerInfinitePlayBtn.title = "Infinite Play: " + modeLabel;
    playerInfinitePlayMenu.setAttribute("aria-hidden", uiVisible && isOpen ? "false" : "true");

    if (!uiVisible) {
        closePlayerInfinitePlayMenu();
        return;
    }

    playerInfinitePlayMenuBtns.forEach(function(btn) {
        var btnMode = normalizeTidalInfinitePlayMode(btn.getAttribute("data-mode"));
        var unavailable = tidalInfinitePlayLastfmConnected === false && btnMode !== "same_artist";
        var active = btnMode === mode;
        btn.className = "playerInfinitePlayMenuBtn " + getInfinitePlayModeClass(btnMode) + (active ? " is-active srovaIpMenuActive" : "") + (unavailable ? " is-disabled" : "");
        btn.disabled = unavailable;
        btn.setAttribute("aria-pressed", active ? "true" : "false");
        btn.setAttribute("aria-disabled", unavailable ? "true" : "false");
        btn.title = unavailable ? "Connect Last.fm to use this mode." : "";
    });
}

function openPlayerInfinitePlayMenu() {
    if (!playerInfinitePlayControl || !shouldShowInfinitePlayUi(tidalInfinitePlayEnabled)) { return; }
    playerInfinitePlayControl.classList.add("infinite-play-menu-open");
    updatePlayerInfinitePlayControl();
}

function closePlayerInfinitePlayMenu() {
    if (!playerInfinitePlayControl) { return; }
    playerInfinitePlayControl.classList.remove("infinite-play-menu-open");
    if (playerInfinitePlayBtn) { playerInfinitePlayBtn.setAttribute("aria-expanded", "false"); }
    if (playerInfinitePlayMenu) { playerInfinitePlayMenu.setAttribute("aria-hidden", "true"); }
}

function togglePlayerInfinitePlayMenu() {
    if (!playerInfinitePlayControl || !shouldShowInfinitePlayUi(tidalInfinitePlayEnabled)) { return; }
    if (playerInfinitePlayControl.classList.contains("infinite-play-menu-open")) {
        closePlayerInfinitePlayMenu();
    } else {
        openPlayerInfinitePlayMenu();
    }
}

function applyPlayerInfinitePlayMode(mode) {
    mode = normalizeTidalInfinitePlayMode(mode);
    if (tidalInfinitePlayLastfmConnected === false && mode !== "same_artist") { return; }

    var previousEnabled = tidalInfinitePlayEnabled;
    var previousMode = tidalInfinitePlayMode;
    tidalInfinitePlayEnabled = true;
    tidalInfinitePlayMode = mode;
    updatePlayerInfinitePlayControl();

    saveInfinitePlaySettings(true, mode, function() {
        closePlayerInfinitePlayMenu();
        updatePlayerInfinitePlayControl();
    }, null, function() {
        tidalInfinitePlayEnabled = previousEnabled;
        tidalInfinitePlayMode = previousMode;
        updatePlayerInfinitePlayControl();
    });
}

function maybeRefillTidalInfinitePlay(s) {
    if (!tidalInfinitePlayEnabled || tidalInfinitePlayRefillInFlight || !s) { return; }
    if (!s.playing || isRadioLiveStatus(s)) { return; }
    if (String(s.source || "").toLowerCase() === "local") { return; }
    var trackId = String(s.current_track_id || "").trim();
    if (!trackId || trackId.indexOf("local:") === 0) { return; }
    var queueLength = Number(s.queue_length || 0);
    var queueIndex = Number(s.queue_index || 0);
    if (!queueLength || queueIndex < queueLength - 1) { return; }
    var duration = Number(s.duration || currentDuration || 0);
    var position = Number(s.position || progressFill._elapsed || 0);
    position = stableResumeVisualPosition(
        position,
        s.track_id || s.current_track_id || currentPlayingId,
        !!s.playing
    );
    if (!duration || duration <= 0) { return; }
    var remaining = duration - position;
    if (remaining > 60) { return; }

    var refillKey = trackId + "|" + queueIndex + "|" + queueLength;
    if (tidalInfinitePlayLastRefillKey === refillKey) { return; }
    tidalInfinitePlayLastRefillKey = refillKey;
    tidalInfinitePlayRefillInFlight = true;

    fetch("/api/tidal/infinite-play/refill", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seed_id: trackId, mode: tidalInfinitePlayMode, limit: 10 })
    })
    .then(function(res) { return res.json().catch(function() { return {}; }); })
    .then(function(data) {
        if (!data || data.ok !== true) {
            console.info("Infinite Play refill skipped:", (data && data.error) || "no recommendation seed");
            releaseTidalInfinitePlayRefillKey(refillKey);
            return;
        }
        console.info("Infinite Play appended " + (data.added || 0) + " recommended tracks.");
        if (queueView && queueView.style.display !== "none") {
            loadQueue();
        }
    })
    .catch(function(e) {
        console.info("Infinite Play refill failed:", e);
        releaseTidalInfinitePlayRefillKey(refillKey);
    })
    .then(function() {
        tidalInfinitePlayRefillInFlight = false;
    });
}

function pollStatus() {
    fetchWithTimeout("/status", {}, 3500)
        .then(function(res) { return res.json(); })
        .then(function(s) {
            lastKnownPlaybackStatus = s;
            syncNowPlayingAlbumWatcher(s);
            if (typeof s.tidal_infinite_play_enabled === "boolean") {
                tidalInfinitePlayEnabled = s.tidal_infinite_play_enabled;
            }
            if (s.tidal_infinite_play_mode) {
                tidalInfinitePlayMode = normalizeTidalInfinitePlayMode(s.tidal_infinite_play_mode);
            }
            updatePlayerInfinitePlayControl();
            updateHomeHeroNowPlaying(s);
            var statusValid = s.current_track_valid !== false && s.playback_state !== "idle";
            var statusPlaying = !!s.playing;
            if (!statusValid) {
                resetTidalInfinitePlayGuard();
                clearRadioIdleStandbyTimer();
                if (typeof s.logged_in === "boolean") { updateLoginBtn(s.logged_in); }
                updateDacStateFromStatus(s);
                repeatMode = s.repeat || repeatMode;
                shuffleOn = typeof s.shuffle === "boolean" ? s.shuffle : shuffleOn;
                updateRepeatIcon();
                updateShuffleIcon();
                applyStandbyPlayerBar();
                return;
            }
            if (s.radio_mode && s.radio_station) {
                if (statusPlaying) {
                    clearRadioIdleStandbyTimer();
                } else {
                    scheduleRadioIdleStandby();
                }
            } else {
                clearRadioIdleStandbyTimer();
            }
            setPlayerHasActiveMedia(true);
            setPlayerBarActivePlaybackSource(
                (radioIdleStandbyApplied && !statusPlaying) ? "" : inferStatusPlaybackSource(s)
            );
            var previousPlayingIdBeforeRadioTransition = String(currentPlayingId || "");
            var statusIsRadioLive = isRadioLiveStatus(s);
            var refreshQueueForRadioTransition = !!(
                previousPlayingIdBeforeRadioTransition &&
                statusIsRadioLive &&
                (s.radio_mode || s.source === "radio" || s.context_type === "radio")
            );
            if (statusIsRadioLive && (s.radio_mode || s.source === "radio" || s.context_type === "radio")) {
                if (currentPlayingId || currentDuration > 0 || (progressFill && progressFill._elapsed)) {
                    skipRadioRestoreSeek();
                }
                currentPlayingId = null;
                currentDuration = 0;
                resetLocalPlaybackProgress();
                seekInFlight = false;
                pendingSessionPositionResetTrackId = "";
                seekGuardTrackId = "";
                if (refreshQueueForRadioTransition && queueView && queueView.style.display !== "none") {
                    loadQueue();
                }
            }
            if (statusPlaying !== playing) {
                playing = statusPlaying;
                updatePlayPauseIcon();
                if (playing) { playerBar.classList.remove("hidden"); }
            } else {
                // Keep DOM icons honest on a fresh browser load, where the
                // HTML fallback may not yet match the backend state.
                updatePlayPauseIcon();
            }
            if (s.repeat && s.repeat !== repeatMode) {
                repeatMode = s.repeat;
                updateRepeatIcon();
            }
            if (typeof s.shuffle === "boolean" && s.shuffle !== shuffleOn) {
                shuffleOn = s.shuffle;
                updateShuffleIcon();
            }
            if (s.current_track_id && String(s.current_track_id) !== String(currentPlayingId)) {
                var previousCurrentPlayingId = String(currentPlayingId || "");
                var nextCurrentPlayingId = String(s.current_track_id);
                if (previousCurrentPlayingId) {
                    suppressNextSessionPositionForTrack(nextCurrentPlayingId);
                }
                currentPlayingId = nextCurrentPlayingId;
                resetTidalInfinitePlayGuard();
                syncActiveTrackViews(true);
                // Immediately zero progress bar fills so they don't stay at 100%
                // while waiting for restoreSession to return the new position
                resetLocalPlaybackProgress();
                // Also reset tech badge and accent until new stream info arrives
                lastTechText  = "";
                lastTechClass = "hidden";
                document.body.classList.remove("hires");
                if (albumTechInfo)     { albumTechInfo.classList.add("hidden"); }
                if (nowPlayingQuality) { nowPlayingQuality.textContent = ""; nowPlayingQuality.className = "hidden"; }
                var _pmReset = document.getElementById("playerMeta");
                if (_pmReset) {
                    _pmReset.textContent = "";
                    _pmReset.className = "audioInfoBox audioInfoOff";
                }
                updateBitPerfectReadout({ bit_perfect_path_confirmed: false, bit_perfect_reason: "Bit Perfect Unconfirmed" }, false);
                // Update from trackMap immediately if available for zero-lag display
                var meta = trackMap[currentPlayingId];
                if (meta) {
                    playerArt.src            = meta.cover    || "";
                    playerTrack.textContent  = meta.title    || "";
                    playerArtist.textContent = meta.artist   || "";
                    currentDuration          = meta.duration || 0;
                    totalTimeEl.textContent  = formatTime(meta.duration || 0);
                    playerBar.classList.remove("hidden");
                    playing = true;
                    updatePlayPauseIcon();
                } else if (s.title || s.artist || s.cover) {
                    playerArt.src            = s.cover    || "";
                    playerTrack.textContent  = s.title    || "";
                    playerArtist.textContent = s.artist   || "";
                    currentDuration          = s.duration || 0;
                    totalTimeEl.textContent  = formatTime(s.duration || 0);
                }
                // Always call restoreSession to get authoritative cover/title/artist
                // from the backend -- covers auto-advance and cases where trackMap
                // has stale or missing data
                restoreSession();
            } else if (s.current_track_id) {
                syncActiveTrackViews(false);
            }
            if (typeof s.logged_in === "boolean") { updateLoginBtn(s.logged_in); }
            updateDacStateFromStatus(s);
            var hiRes = (s.bit_depth && s.bit_depth >= 24) || (s.sample_rate && s.sample_rate > 48000);
            if (radioIdleStandbyApplied && isPausedRadioStatus(s)) {
                clearPlaybackTechDisplay();
                updateExclusiveLock(false, false);
                updateBitPerfectReadout({
                    bit_perfect_path_confirmed: false,
                    bit_perfect_reason: "Nothing playing"
                }, false);
            } else {
                updateTechInfo(s.sample_rate, s.bit_depth, s.codec);
                updateExclusiveLock(s.exclusive || false, hiRes);
                updateBitPerfectReadout(s, hiRes);
            }
            document.body.classList.toggle("radioMode", !!(s.radio_mode && !(radioIdleStandbyApplied && !statusPlaying)));
            if (s.radio_mode && s.radio_station) {
                if (radioIdleStandbyApplied && !statusPlaying) {
                    playerBar.classList.remove("hidden");
                } else {
                    var radioCoverArt = s.radio_cover_art_url || s.radio_art_url || s.radio_station.icon || "";
                    playerArt.src            = radioCoverArt;
                    playerTrack.textContent  = s.radio_station.name || "";
                    playerArtist.textContent = "Radio";
                    totalTimeEl.textContent  = "";
                    currentTimeEl.textContent = "";
                    playerBar.classList.remove("hidden");
                    updateRadioMetadata(s.radio_metadata || {});
                }
            } else if (!s.radio_mode) {
                updateRadioMetadata({});
                playerArt.src            = s.cover    || "";
                playerTrack.textContent  = s.title    || "";
                playerArtist.textContent = s.artist   || "";
                playerArtist.style.display = "";
                currentDuration          = s.duration || 0;
                totalTimeEl.textContent  = formatTime(s.duration || 0);
                playerBar.classList.remove("hidden");
            }
            // Keep navigation IDs in the same status snapshot as the visible
            // player-bar metadata. Missing IDs deliberately clear stale links
            // while a new TIDAL track is still resolving.
            _updatePlayerBarLinks(s);
            syncPlayerTrayTrackInfo(s);
            if (nowPlayingView && !nowPlayingView.classList.contains("hidden")) {
                syncNowPlayingButtons();
                nowPlayingArt.src            = playerArt.src            || "";
                nowPlayingTrack.textContent  = playerTrack.textContent  || "";
                nowPlayingArtist.textContent = playerArtist.textContent || "";
                if (lastTechText) {
                    nowPlayingQuality.textContent = lastTechText;
                    nowPlayingQuality.className   = lastTechClass + " npQuality";
                }
                syncDacNameDisplay();
                if (radioIdleStandbyApplied && isPausedRadioStatus(s)) {
                    updateBitPerfectReadout({
                        bit_perfect_path_confirmed: false,
                        bit_perfect_reason: "Nothing playing"
                    }, false);
                } else {
                    updateBitPerfectReadout(s, hiRes);
                }
            }
            maybeRefillTidalInfinitePlay(s);
        })
        .catch(function() {});
}

setInterval(pollStatus, 1000);


// --- Track highlight ---

function highlightCurrentTrack() {
    var rows = trackList.querySelectorAll(".track");
    for (var i = 0; i < rows.length; i++) { rows[i].classList.remove("playing"); }
    if (!currentPlayingId) { return; }
    var target = trackList.querySelector('[data-track-id="' + currentPlayingId + '"]');
    if (target) { target.classList.add("playing"); }
}

function syncActiveTrackViews(trackChanged) {
    highlightCurrentTrack();
    _syncHomePlayingTiles();
    if (trackChanged && queueView && queueView.style.display !== "none") {
        loadQueue();
    }
}


// --- Icon updaters ---

function syncSrovaPlaybackVisualState() {
    var pausedWithTrack = !!(!playing && currentPlayingId);
    if (document.body) {
        document.body.classList.toggle("srovaPlaybackPaused", pausedWithTrack);
        document.body.classList.toggle("srovaPlaybackPlaying", !!playing);
    }
}

function _setPlayIconButton(btn, isPlaying) {
    if (!btn) { return; }
    var icon = btn.querySelector(".material-icons");
    if (!icon) { return; }
    icon.textContent = isPlaying ? "pause" : "play_arrow";
    btn.classList.toggle("is-playing", !!isPlaying);
    btn.classList.toggle("is-paused", !isPlaying);
    btn.setAttribute("aria-label", isPlaying ? "Pause" : "Play");
    btn.title = isPlaying ? "Pause" : "Play";
}

function updatePlayPauseIcon() {
    _setPlayIconButton(btnPlayPause, playing);
    _setPlayIconButton(npBtnPlay, playing);
    _setPlayIconButton(document.getElementById("vpbBtnPlay"), playing);
    if (playerBar) {
        playerBar.classList.toggle("srovaPlayerBarStandby", !playing && !currentPlayingId);
        syncSrovaPlaybackVisualState();
    }
    var _wb = document.getElementById("waveformBars");
    if (_wb) {
        if (playing) { _wb.classList.add("active"); }
        else         { _wb.classList.remove("active"); }
    }
    var _npWb = document.getElementById("npWaveformBars");
    if (_npWb) {
        if (playing) { _npWb.classList.add("active"); }
        else         { _npWb.classList.remove("active"); }
    }
}

function updateRepeatIcon() {
    var icon = btnRepeat.querySelector(".material-icons");
    if (repeatMode === "one") {
        icon.textContent = "repeat_one";
        btnRepeat.classList.add("active");
    } else if (repeatMode === "all") {
        icon.textContent = "repeat";
        btnRepeat.classList.add("active");
    } else {
        icon.textContent = "repeat";
        btnRepeat.classList.remove("active");
    }
}

function updateShuffleIcon() {
    if (shuffleOn) { btnShuffle.classList.add("active"); }
    else           { btnShuffle.classList.remove("active"); }
}


// --- Tech info badge ---

function updateTechInfo(sampleRate, bitDepth, codec) {
    var isHiRes = (bitDepth && bitDepth >= 24) || (sampleRate && sampleRate > 48000);
    // Always sync accent colour on body regardless of which view is active
    if (sampleRate || bitDepth || codec) {
        if (isHiRes) {
            document.body.classList.add("hires");
        } else {
            document.body.classList.remove("hires");
        }
        // Build badge text and store globally so Now Playing can use it from any view
        var parts = [];
        if (codec)      { parts.push(codec); }
        if (bitDepth)   { parts.push(bitDepth + "bit"); }
        if (sampleRate) { parts.push((sampleRate / 1000).toFixed(1) + "kHz"); }
        if (parts.length > 0) {
            lastTechText  = parts.join(" / ");
            lastTechClass = isHiRes ? "techInfoHiRes" : "techInfoCD";
        }
    }
    // Player-bar meta breadcrumb for the srova skin -- upper-cased, dot-separated.
    // No "Hi-Res"/"CD" word in here; the quality colour is carried by the lock icon.
    var playerMeta = document.getElementById("playerMeta");
    if (playerMeta) {
        var mparts = [];
        if (codec)      { mparts.push(String(codec).toUpperCase()); }
        if (bitDepth)   { mparts.push(bitDepth + "-BIT"); }
        if (sampleRate) {
            var kHz = (sampleRate / 1000).toFixed(1).replace(/\.0$/, "");
            mparts.push(kHz + "KHZ");
        }
        playerMeta.textContent = mparts.length > 0 ? mparts.join(" \u00b7 ") : "";
        if (mparts.length > 0) {
            playerMeta.className = "audioInfoBox " + (isHiRes ? "audioInfoHiRes techInfoHiRes" : "audioInfoCD techInfoCD");
        } else {
            playerMeta.className = "audioInfoBox audioInfoOff";
        }
    }
    // Update Now Playing quality badge directly (works from any view)
    if (nowPlayingQuality && lastTechText) {
        if (!nowPlayingView.classList.contains("hidden")) {
            nowPlayingQuality.textContent = lastTechText;
            nowPlayingQuality.className   = lastTechClass + " npQuality";
        }
    }
    // Album view badge
    if (!albumTechInfo) { return; }
    if (restoreLocalAlbumDetailTechInfo()) { return; }
    if (albumView.style.display === "none") {
        albumTechInfo.classList.add("hidden");
        return;
    }
    if (!sampleRate && !bitDepth && !codec) { return; }
    if (!lastTechText) { albumTechInfo.classList.add("hidden"); return; }
    albumTechInfo.textContent = lastTechText;
    albumTechInfo.className   = lastTechClass;
}


// --- Playback controls ---


function armResumeVisualGuard(trackId, resumePosition) {
    resumeVisualGuardUntil = Date.now() + 2600;
    resumeVisualGuardTrackId = String(trackId || currentPlayingId || "");
    resumeVisualGuardPosition = Math.max(0, Number(resumePosition || 0));
    if (progressFill) {
        progressFill._elapsed = resumeVisualGuardPosition;
    }
}

function stableResumeVisualPosition(serverPosition, trackId, isServerPlaying) {
    var pos = Number(serverPosition || 0);
    if (!isServerPlaying) {
        return pos;
    }
    if (!resumeVisualGuardUntil || Date.now() > resumeVisualGuardUntil) {
        return pos;
    }

    var activeId = String(trackId || currentPlayingId || "");
    if (resumeVisualGuardTrackId && activeId && resumeVisualGuardTrackId !== activeId) {
        return pos;
    }

    var localPos = Number(progressFill && progressFill._elapsed ? progressFill._elapsed : 0);
    if (startTime) {
        localPos = Math.max(0, Date.now() / 1000 - startTime);
    }
    if (currentDuration > 0) {
        localPos = Math.min(localPos, Number(currentDuration || 0));
    }

    var floorPos = Math.max(resumeVisualGuardPosition, localPos);

    // During clean reload, /status can briefly report the new pipeline at 0
    // before the backend resume seek has propagated. Do not let that one poll
    // yank the visible progress bar backwards.
    if (resumeVisualGuardPosition > 0 && pos + 2.0 < resumeVisualGuardPosition) {
        return floorPos;
    }

    // Hide tiny back/forth corrections during the settle window.
    if (Math.abs(pos - localPos) <= 3.0) {
        return Math.max(pos, localPos);
    }

    return pos;
}

function togglePlayPause() {
    if (playing) {
        fetch("/tidal/pause").then(function() {
            playing = false;
            updatePlayPauseIcon();
            if (lastKnownPlaybackStatus) {
                lastKnownPlaybackStatus.playing = false;
                lastKnownPlaybackStatus.playback_state = "paused";
                syncSrovaPlaybackVisualState();
                updateHomeHeroNowPlaying(lastKnownPlaybackStatus);
            }
            if (lastKnownPlaybackStatus && lastKnownPlaybackStatus.radio_mode) {
                scheduleRadioIdleStandby();
            }
        });
    } else {
        if (
            lastKnownPlaybackStatus &&
            lastKnownPlaybackStatus.current_track_valid === false &&
            lastKnownPlaybackStatus.playback_state === "idle"
        ) {
            applyStandbyPlayerBar();
            return;
        }
        clearRadioIdleStandbyTimer();
        fetch("/tidal/resume")
        .then(function(res) { return res.json().catch(function() { return {}; }); })
        .then(function(data) {
            if (data && (data.ok === false || data.error)) {
                showQueueActionToast(playbackErrorMessage(data, "Playback failed"), true);
                return;
            }
            if (data && data.result === "idle") {
                applyRadioIdleStandbyStatus();
                return;
            }
            playing   = true;
            setPlayerHasActiveMedia(true);
            var rawResumePos = (data && typeof data.position === "number") ? data.position : (progressFill._elapsed || 0);
            var resumePos = normalizeLocalCueUiPosition(rawResumePos, progressFill._elapsed || 0);
            startTime = Date.now() / 1000 - resumePos;
            progressFill._elapsed = resumePos;
            armResumeVisualGuard(currentPlayingId, resumePos);
            updatePlayPauseIcon();
            if (lastKnownPlaybackStatus) {
                lastKnownPlaybackStatus.playing = true;
                lastKnownPlaybackStatus.playback_state = "playing";
                syncSrovaPlaybackVisualState();
                updateHomeHeroNowPlaying(lastKnownPlaybackStatus);
            }
            setTimeout(restoreSession, 2200);
        });
    }
}

function handleTrackChangeResponse(res) {
    return res.json().catch(function() { return {}; }).then(function(data) {
        if (data && (data.ok === false || data.error)) {
            showQueueActionToast(playbackErrorMessage(data, "Playback failed"), true);
            return;
        }
        _onTrackChange();
    });
}

function _onTrackChange() {
    clearRadioIdleStandbyTimer();
    resetTidalInfinitePlayGuard();
    // Immediately clear stale stream info so old colour/badge don't linger
    startTime             = Date.now() / 1000;
    progressFill._elapsed = 0;
    playing               = true;   // assume playing so progress bar runs immediately
    setPlayerHasActiveMedia(true);
    updatePlayPauseIcon();
    lastTechText  = "";
    lastTechClass = "hidden";
    document.body.classList.remove("hires");
    if (albumTechInfo)     { albumTechInfo.classList.add("hidden"); }
    if (nowPlayingQuality) { nowPlayingQuality.textContent = ""; nowPlayingQuality.className = "hidden"; }
    var _pm = document.getElementById("playerMeta");
    if (_pm) {
        _pm.textContent = "";
        _pm.className = "audioInfoBox audioInfoOff";
    }
    syncDacNameDisplay();
    _syncHomePlayingTiles();
    // Reset meta and lyrics panels so they reload for the new track
    metaLastTrackId   = null;
    lyricsLastTrackId = null;
    _stopLyricsSync();
    if (lyricsPanel && lyricsPanel.classList.contains("open")) {
        closeLyricsPanel();
    }
    // After backend settles: restore metadata + duration, then fetch fresh stream info
    setTimeout(function() {
        fetch("/session")
            .then(function(r) { return r.json(); })
            .then(function(s) {
                if (!s.track_id) { return; }
                var sessionTrackId = String(s.track_id);
                var sessionTrackChanged = !!currentPlayingId && sessionTrackId !== String(currentPlayingId);
                var sessionPosition = sessionTrackChanged ? 0 : (s.position || 0);
                currentDuration       = s.duration || 0;
                var sessionSource = String((s && s.source) || "").toLowerCase();
                var sessionLooksLocal = sessionSource === "local" || sessionTrackId.indexOf("local:") === 0;
                if (!sessionLooksLocal) {
                    currentPlayingIsLocalCue = false;
                }
                if (sessionLooksLocal && currentDuration > 0 &&
                    Number(sessionPosition || 0) > Number(currentDuration || 0) + 5) {
                    // Local CUE /session can expose parent-file raw position.
                    // Keep UI progress on the virtual CUE-track timeline.
                    currentPlayingIsLocalCue = true;
                    sessionPosition = normalizeLocalCueUiPosition(sessionPosition, progressFill._elapsed || 0);
                }
                startTime             = Date.now() / 1000 - sessionPosition;
                progressFill._elapsed = sessionPosition;
                totalTimeEl.textContent = formatTime(currentDuration);
                // Delegate the rest to restoreSession for full metadata update
                restoreSession();
                pollStatus();
            })
            .catch(function() {
                restoreSession();
                pollStatus();
            });
    }, 700);
}

// Prev-track: restart-first flow (1.8.1 behaviour)
// -- position > 5s: seek to start of current track
// -- position <= 5s OR second press within 2s: go to previous track
var _prevTapTime = 0;


function normalizeLocalCueUiPosition(rawPosition, fallbackPosition) {
    var raw = Number(rawPosition || 0);
    var fallback = Number(fallbackPosition || 0);
    var duration = Number(currentDuration || 0);
    var source = "";
    try {
        source = String((lastKnownPlaybackStatus && lastKnownPlaybackStatus.source) || "").toLowerCase();
    } catch (e) {
        source = "";
    }
    var trackIdText = String(currentPlayingId || "");
    var localTrack = source === "local" || trackIdText.indexOf("local:") === 0;
    var looksLikeRawCueParentPosition = localTrack && duration > 0 && raw > duration + 5;

    if (looksLikeRawCueParentPosition || currentPlayingIsLocalCue) {
        currentPlayingIsLocalCue = true;
        if (looksLikeRawCueParentPosition) {
            // /session and /tidal/resume can expose the parent-FLAC raw CUE offset.
            // The UI progress bar must stay on the virtual CUE-track timeline.
            if (fallback >= 0 && fallback <= duration) {
                return fallback;
            }
            return 0;
        }
    }
    return raw;
}

function prevTrack() {
    var now     = Date.now();
    var elapsed = playing ? (now / 1000 - startTime) : (progressFill._elapsed || 0);
    var doubleTap = (now - _prevTapTime) < 2000;
    _prevTapTime = now;

    var trackIdText = String(currentPlayingId || "");
    var statusSource = (typeof lastKnownPlaybackStatus !== "undefined" && lastKnownPlaybackStatus)
        ? String(lastKnownPlaybackStatus.source || "").toLowerCase()
        : "";
    var localTrack = statusSource === "local" || trackIdText.indexOf("local:") === 0;
    var duration = Number(currentDuration || 0);
    var progressElapsed = progressFill ? Number(progressFill._elapsed || 0) : 0;
    var impossibleLocalPosition = localTrack && duration > 0 &&
        (Number(elapsed || 0) > duration + 5 || progressElapsed > duration + 5);

    if (localTrack && (currentPlayingIsLocalCue || impossibleLocalPosition)) {
        currentPlayingIsLocalCue = true;
        fetch("/tidal/prev").then(handleTrackChangeResponse);
        return;
    }

    if (!doubleTap && elapsed > 5) {
        // Restart current track
        requestSeekTo(0);
    } else {
        // Go to previous track
        fetch("/tidal/prev").then(handleTrackChangeResponse);
    }
}
function nextTrack() {
    fetch("/tidal/next").then(handleTrackChangeResponse);
}

function toggleRepeat() {
    fetch("/tidal/repeat")
        .then(function(res) { return res.json(); })
        .then(function(data) { repeatMode = data.repeat; updateRepeatIcon(); });
}

function toggleShuffle() {
    fetch("/tidal/shuffle")
        .then(function(res) { return res.json(); })
        .then(function(data) {
            shuffleOn = data.shuffle;
            updateShuffleIcon();
            shuffledTracks = [];
            currentViewTracks = originalTracks;
            loadQueue();
            pollStatus();
        });
}

function updateRowArrows(row, btnLeft, btnRight) {
    var atStart = row.scrollLeft <= 2;
    var atEnd   = row.scrollLeft >= row.scrollWidth - row.clientWidth - 2;
    btnLeft.style.opacity        = atStart ? "0" : "1";
    btnLeft.style.pointerEvents  = atStart ? "none" : "auto";
    btnRight.style.opacity       = atEnd   ? "0" : "1";
    btnRight.style.pointerEvents = atEnd   ? "none" : "auto";
}


// --- Generic horizontal section builder ---

function buildScrollSection(title, items, onCardClick, opts) {
    // opts (optional):
    //   kind            : "live" | "library" | "curated"   -- drives the small gold label
    //                                                         in srova.css via data-kind
    //   defaultQuality  : "hires" | "cd" | "radio" | null  -- fallback per-tile quality when
    //                                                         the item dict does not expose one
    opts = opts || {};
    var sectionKind = opts.kind || "curated";
    var defaultQ    = opts.defaultQuality || null;

    var block = document.createElement("div");
    block.className = "homeSection";
    block.setAttribute("data-kind", sectionKind);

    var h = document.createElement("h2");
    h.textContent = title;

    var rowWrapper = document.createElement("div");
    rowWrapper.className = "rowWrapper";

    var btnLeft = document.createElement("button");
    btnLeft.className = "rowArrow rowArrowLeft";
    btnLeft.innerHTML = '<span class="material-icons">chevron_left</span>';

    var row = document.createElement("div");
    row.className = "homeRow";

    var btnRight = document.createElement("button");
    btnRight.className = "rowArrow rowArrowRight";
    btnRight.innerHTML = '<span class="material-icons">chevron_right</span>';

    items.forEach(function(item) {
        var card = document.createElement("div");
        card.className = "album";

        // Per-tile quality -- drives the HI-RES/CD badge and the hover glow colour
        // in srova.css. Radio items never get a badge (no consistent format claim).
        var q = null;
        var itType = (item.type || "").toLowerCase();
        if (itType === "radio") {
            q = "radio";
        } else if (item.audio_quality) {
            var aq = String(item.audio_quality).toUpperCase();
            if (aq.indexOf("HI_RES") >= 0 || aq === "HIRES" || aq === "MASTER") { q = "hires"; }
            else if (aq === "LOSSLESS" || aq === "CD")                          { q = "cd"; }
        } else if (item.quality) {
            var qq = String(item.quality).toUpperCase();
            if (qq === "HI-RES" || qq === "HIRES")     { q = "hires"; }
            else if (qq === "CD" || qq === "LOSSLESS") { q = "cd"; }
        } else if (defaultQ) {
            q = defaultQ;
        }
        if (q)         { card.setAttribute("data-q", q); }
        if (item.id)   { card.setAttribute("data-id", String(item.id)); }
        if (item.type) { card.setAttribute("data-type", itType); }

        card.innerHTML =
            '<img src="' + (item.image_url || "") + '">' +
            '<div class="album-title">'  + (item.name      || "") + '</div>' +
            '<div class="album-artist">' + (item.sub_title || "") + '</div>';
        if (item.id) {
            (function(it, anchor) {
                card.onclick = function(e) { onCardClick(it, e, anchor); };
            }(item, card));
        }
        row.appendChild(card);
    });

    btnLeft.addEventListener("click",  function() { row.scrollBy({ left: -(row.clientWidth * 0.75), behavior: "smooth" }); });
    btnRight.addEventListener("click", function() { row.scrollBy({ left:   row.clientWidth * 0.75,  behavior: "smooth" }); });
    row.addEventListener("scroll", function() { updateRowArrows(row, btnLeft, btnRight); });

    rowWrapper.appendChild(btnLeft);
    rowWrapper.appendChild(row);
    rowWrapper.appendChild(btnRight);
    block.appendChild(h);
    block.appendChild(rowWrapper);

    requestAnimationFrame(function() { updateRowArrows(row, btnLeft, btnRight); });

    // Mark any tiles inside this new block whose album is the currently playing one
    _syncHomePlayingTiles(block);

    return block;
}

// Mark the home tile whose id matches the currently playing context with .playing
// so srova.css can paint the persistent inset glow. Callable with a scope element
// (e.g. a freshly built section) or with no args to sweep the whole home view.
function _syncHomePlayingTiles(scopeEl) {
    var root = scopeEl || document.getElementById("homeSections");
    if (!root) { return; }
    var curId = currentContext ? String(currentContext.id || "") : "";
    var tiles = root.querySelectorAll(".album");
    for (var i = 0; i < tiles.length; i++) {
        var t   = tiles[i];
        var tId = t.getAttribute("data-id") || "";
        if (tId && curId && tId === curId) {
            t.classList.add("playing");
        } else {
            t.classList.remove("playing");
        }
    }
}


// --- Home ---

// Tracks active slot-poll timers so navigating away cancels them
var _homeSlotTimers = [];

function _cancelHomeSlotPolls() {
    for (var i = 0; i < _homeSlotTimers.length; i++) { clearTimeout(_homeSlotTimers[i]); }
    _homeSlotTimers = [];
}

function playRadioStation(item) {
    var radioClickAllowed = currentSourceSection === "radio" ||
        !!(lastKnownPlaybackStatus && lastKnownPlaybackStatus.radio_mode) ||
        !!(document.body && document.body.classList.contains("radioMode"));
    if (!onlineSourcesAvailable && radioClickAllowed) {
        console.log("Radio click allowed despite stale online-source offline state");
    } else if (!requireOnlineSource()) {
        return;
    }
    clearRadioIdleStandbyTimer();
    fetchWithTimeout("/api/radio/play/" + encodeURIComponent(item.id), { method: "POST" }, 6000)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data && data.ok === false) {
                var message = playbackErrorMessage(data, ONLINE_SOURCE_OFFLINE_MESSAGE);
                showQueueActionToast(message, true);
                if (message !== DAC_PLAYBACK_ERROR_MESSAGE) { refreshOnlineSourceState(); }
                return;
            }
            currentPlayingId = null;
            currentDuration  = 0;
            startTime        = Date.now() / 1000;
            playing          = true;
            setPlayerHasActiveMedia(true);
            if (typeof progressFill !== "undefined" && progressFill) {
                progressFill._elapsed = 0;
            }
            if (typeof totalTimeEl !== "undefined" && totalTimeEl) {
                totalTimeEl.textContent = "";
            }
            if (typeof currentTimeEl !== "undefined" && currentTimeEl) {
                currentTimeEl.textContent = "";
            }
            if (typeof playerArt !== "undefined" && playerArt) {
                playerArt.src = item.image_url || "";
            }
            if (typeof playerTrack !== "undefined" && playerTrack) {
                playerTrack.textContent = item.name || "";
            }
            if (typeof playerArtist !== "undefined" && playerArtist) {
                playerArtist.textContent = "Radio";
            }
            if (typeof playerBar !== "undefined" && playerBar) {
                playerBar.classList.remove("hidden");
            }
            setPlayerBarActivePlaybackSource("radio");
            document.body.classList.add("radioMode");
            syncPlayerTrayTrackInfo({
                source: "radio",
                radio_mode: true,
                radio_station: {
                    name: item.name || "",
                    icon: item.image_url || ""
                },
                radio_metadata: {}
            });
            if (typeof updatePlayPauseIcon === "function") { updatePlayPauseIcon(); }
            updateHomeHeroNowPlaying({
                playing: true,
                current_track_valid: true,
                playback_state: "playing",
                source: "radio",
                radio_mode: true,
                radio_station: { name: item.name || "", icon: item.image_url || "" },
                radio_metadata: {},
                radio_cover_art_url: item.image_url || ""
            });
        })
        .catch(function() {
            handleOnlineSourceFailure(ONLINE_SOURCE_OFFLINE_MESSAGE);
        });
}

function buildRadioStationPayload(item) {
    item = item || {};
    var stationId = String(item.id || "").trim();
    return {
        id: stationId ? ("radio:station:" + stationId) : "radio:station",
        source: "radio",
        station_id: stationId,
        title: item.name || "Radio",
        artist: "Radio",
        album: "Radio",
        cover: item.image_url || item.icon || "",
        duration: 0,
        quality: "RADIO",
        url: item.url || "",
        icon: item.image_url || item.icon || "",
        context_type: "radio",
        context_id: stationId,
        context_title: item.name || "Radio"
    };
}

function isRadioCurrentlyActive() {
    return !!(
        (lastKnownPlaybackStatus && lastKnownPlaybackStatus.radio_mode) ||
        (document.body && document.body.classList.contains("radioMode"))
    );
}

function showRadioStationMenu(anchorEl, item, e) {
    if (e) { e.stopPropagation(); }
    if (!item || !item.id) { return; }

    closeActivePopover();

    var popover = document.createElement("div");
    popover.className = "queuePopover";

    function addMenuButton(icon, label, onClick) {
        var btn = document.createElement("button");
        btn.className = "queuePopoverBtn";
        btn.innerHTML = '<span class="material-icons">' + icon + '</span> ' + label;
        btn.onclick = function(ev) {
            ev.stopPropagation();
            closeActivePopover();
            onClick();
        };
        popover.appendChild(btn);
    }

    addMenuButton("play_arrow", "Play Now", function() {
        playRadioStation(item);
    });

    addMenuButton("queue_play_next", "Play Next", function() {
        if (isRadioCurrentlyActive()) {
            showQueueActionToast("Clear the Radio station from the Play Queue before adding to it.", true);
            return;
        }
        submitQueueTracks([buildRadioStationPayload(item)], "next");
    });

    addMenuButton("add_to_queue", "Add to Queue", function() {
        if (isRadioCurrentlyActive()) {
            showQueueActionToast("Clear the Radio station from the Play Queue before adding to it.", true);
            return;
        }
        submitQueueTracks([buildRadioStationPayload(item)], "queue");
    });

    positionQueuePopover(anchorEl, popover);
}

function persistRadioStationOrder(items) {
    return fetch("/api/radio/stations/order", {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            station_ids: items.map(function(item) { return String(item.id || ""); })
        })
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (!data || data.ok === false || data.error) {
            throw new Error((data && data.error) || "Could not save Radio station order.");
        }
        return data;
    });
}

function enhanceRadioShelfOrdering(block, items) {
    if (!block) { return; }
    block.classList.add("radioShelf");

    var cards = Array.prototype.slice.call(
        block.querySelectorAll(".homeRow .album")
    );
    var row = cards.length ? cards[0].parentNode : null;
    var originalCards = cards.slice();
    var activeCard = null;
    var activeHandle = null;
    var activePointerId = null;
    var dragPlaceholder = null;
    var dragReturnBefore = null;
    var dragOffsetX = 0;
    var dragOffsetY = 0;
    var dragInlineStyleText = null;
    var toggle = null;

    function currentCards() {
        if (!row) { return []; }
        return Array.prototype.slice.call(
            row.querySelectorAll(".album:not(.radioDragPlaceholder)")
        );
    }

    function currentItems() {
        return currentCards().map(function(card) {
            return card._radioOrderItem;
        }).filter(function(item) {
            return !!item;
        });
    }

    function orderChanged() {
        var ordered = currentCards();
        if (ordered.length !== originalCards.length) { return true; }
        for (var i = 0; i < ordered.length; i++) {
            if (ordered[i] !== originalCards[i]) { return true; }
        }
        return false;
    }

    function removeActivePointerListeners() {
        window.removeEventListener(
            "pointermove",
            handleActivePointerMove,
            true
        );
        window.removeEventListener(
            "pointerup",
            handleActivePointerEnd,
            true
        );
        window.removeEventListener(
            "pointercancel",
            handleActivePointerEnd,
            true
        );
        window.removeEventListener("blur", handleActiveBlur, true);
    }

    function positionActiveCard(e) {
        if (!activeCard) { return; }

        activeCard.style.setProperty(
            "--radio-drag-left",
            String(e.clientX - dragOffsetX) + "px"
        );
        activeCard.style.setProperty(
            "--radio-drag-top",
            String(e.clientY - dragOffsetY) + "px"
        );
    }

    function moveDragPlaceholder(e) {
        if (!row || !dragPlaceholder || !activeCard) { return; }

        var hit = document.elementFromPoint(e.clientX, e.clientY);
        var target = hit && hit.closest ? hit.closest(".album") : null;

        if (
            !target ||
            target === activeCard ||
            target === dragPlaceholder ||
            target.parentNode !== row
        ) {
            return;
        }

        var children = Array.prototype.slice.call(row.children);
        var placeholderIndex = children.indexOf(dragPlaceholder);
        var targetIndex = children.indexOf(target);

        if (placeholderIndex < 0 || targetIndex < 0) { return; }

        if (placeholderIndex < targetIndex) {
            row.insertBefore(dragPlaceholder, target.nextSibling);
        } else {
            row.insertBefore(dragPlaceholder, target);
        }
    }

    function handleActivePointerMove(e) {
        if (
            activePointerId === null ||
            activePointerId !== e.pointerId
        ) {
            return;
        }

        e.preventDefault();
        positionActiveCard(e);
        moveDragPlaceholder(e);
    }

    function handleActivePointerEnd(e) {
        if (
            activePointerId === null ||
            activePointerId !== e.pointerId
        ) {
            return;
        }

        e.preventDefault();
        e.stopPropagation();
        finishDrag(e.type === "pointerup");
    }

    function handleActiveBlur() {
        if (activePointerId !== null) {
            finishDrag(false);
        }
    }

    function finishDrag(commitOrder) {
        removeActivePointerListeners();

        var card = activeCard;
        var placeholder = dragPlaceholder;
        var returnBefore = dragReturnBefore;
        var originalInlineStyle = dragInlineStyleText;

        activeCard = null;
        activeHandle = null;
        activePointerId = null;
        dragPlaceholder = null;
        dragReturnBefore = null;
        dragOffsetX = 0;
        dragOffsetY = 0;
        dragInlineStyleText = null;

        if (card && row) {
            if (placeholder && placeholder.parentNode === row) {
                if (commitOrder !== false) {
                    row.insertBefore(card, placeholder);
                } else if (
                    returnBefore &&
                    returnBefore.parentNode === row
                ) {
                    row.insertBefore(card, returnBefore);
                } else {
                    row.appendChild(card);
                }
            }

            card.classList.remove("is-radio-dragging");

            if (originalInlineStyle === null) {
                card.removeAttribute("style");
            } else {
                card.setAttribute("style", originalInlineStyle);
            }
        }

        if (placeholder && placeholder.parentNode) {
            placeholder.parentNode.removeChild(placeholder);
        }

        block.classList.remove("is-radio-drag-active");
        if (document.body) {
            document.body.classList.remove("is-radio-reordering-drag");
        }
    }

    function restoreOriginalOrder() {
        if (!row) { return; }
        originalCards.forEach(function(card) {
            row.appendChild(card);
        });
    }

    function updateModeUi() {
        block.classList.toggle("is-reordering", _radioReorderMode);
        if (!toggle) { return; }

        toggle.setAttribute(
            "aria-pressed",
            _radioReorderMode ? "true" : "false"
        );
        toggle.textContent = _radioReorderMode ? "Done" : "Reorder";
    }

    function exitWithoutSaving() {
        finishDrag();
        _radioReorderMode = false;
        updateModeUi();
    }

    function saveStagedOrder() {
        if (_radioOrderSavePending) { return; }
        finishDrag();

        if (!orderChanged()) {
            exitWithoutSaving();
            return;
        }

        var reordered = currentItems();
        if (reordered.length !== items.length) {
            restoreOriginalOrder();
            exitWithoutSaving();
            showQueueActionToast(
                "Could not prepare the Radio station order.",
                true
            );
            return;
        }

        _radioOrderSavePending = true;
        if (toggle) {
            toggle.disabled = true;
            toggle.textContent = "Saving";
        }

        persistRadioStationOrder(reordered)
            .then(function() {
                _radioOrderSavePending = false;
                originalCards = currentCards();
                _radioSourceStationSignature = radioStationSignature(reordered);
                _radioSourceCacheGeneration += 1;
                _radioReorderMode = false;
                if (toggle) { toggle.disabled = false; }
                updateModeUi();
            })
            .catch(function(err) {
                _radioOrderSavePending = false;
                restoreOriginalOrder();
                _radioReorderMode = false;
                if (toggle) { toggle.disabled = false; }
                updateModeUi();
                showQueueActionToast(
                    (err && err.message) ||
                        "Could not save Radio station order.",
                    true
                );
            });
    }

    var heading = block.querySelector("h2");
    if (heading && heading.parentNode) {
        var header = document.createElement("div");
        header.className = "radioShelfHeader";
        heading.parentNode.insertBefore(header, heading);
        header.appendChild(heading);

        toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "radioReorderToggle";
        toggle.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();

            if (_radioOrderSavePending) { return; }

            if (_radioReorderMode) {
                saveStagedOrder();
                return;
            }

            originalCards = currentCards();
            _radioReorderMode = true;
            updateModeUi();
        };
        header.appendChild(toggle);
    }

    function moveCardByKeyboard(card, direction) {
        if (!row || !_radioReorderMode) { return; }

        var ordered = currentCards();
        var index = ordered.indexOf(card);
        var targetIndex = index + direction;

        if (index < 0 || targetIndex < 0 || targetIndex >= ordered.length) {
            return;
        }

        var target = ordered[targetIndex];
        if (direction < 0) {
            row.insertBefore(card, target);
        } else {
            row.insertBefore(card, target.nextSibling);
        }
    }

    cards.forEach(function(card, index) {
        card._radioOrderItem = items[index];

        var handle = document.createElement("button");
        handle.type = "button";
        handle.className = "radioDragHandle";
        handle.title = "Drag to reorder station";
        handle.setAttribute(
            "aria-label",
            "Drag to reorder " +
                String((items[index] && items[index].name) || "station")
        );
        handle.innerHTML =
            '<span class="material-icons">drag_indicator</span>';

        handle.addEventListener("click", function(e) {
            if (_radioReorderMode) {
                e.preventDefault();
                e.stopPropagation();
            }
        });

        handle.addEventListener("pointerdown", function(e) {
            if (
                !_radioReorderMode ||
                _radioOrderSavePending ||
                e.isPrimary === false ||
                (e.pointerType === "mouse" && e.button !== 0)
            ) {
                return;
            }

            e.preventDefault();
            e.stopPropagation();

            if (activePointerId !== null) {
                finishDrag(false);
            }

            var rect = card.getBoundingClientRect();

            /*
             * Preserve the complete pre-drag inline style. This lets the
             * lifted tile use strict viewport-independent dimensions while
             * restoring the card exactly after drop or cancellation.
             */
            dragInlineStyleText = card.getAttribute("style");

            dragPlaceholder = document.createElement("div");
            dragPlaceholder.className =
                "album radioDragPlaceholder";
            dragPlaceholder.setAttribute("aria-hidden", "true");
            dragPlaceholder.style.setProperty(
                "--radio-placeholder-width",
                String(rect.width) + "px"
            );
            dragPlaceholder.style.setProperty(
                "--radio-placeholder-height",
                String(rect.height) + "px"
            );

            dragReturnBefore = card.nextSibling;
            row.insertBefore(dragPlaceholder, card);

            activeCard = card;
            activeHandle = handle;
            activePointerId = e.pointerId;
            dragOffsetX = e.clientX - rect.left;
            dragOffsetY = e.clientY - rect.top;

            card.style.setProperty(
                "--radio-drag-left",
                String(rect.left) + "px"
            );
            card.style.setProperty(
                "--radio-drag-top",
                String(rect.top) + "px"
            );
            var dragWidth = String(rect.width) + "px";
            var dragHeight = String(rect.height) + "px";

            card.style.setProperty(
                "--radio-drag-width",
                dragWidth
            );
            card.style.setProperty(
                "--radio-drag-height",
                dragHeight
            );

            /*
             * Inline-important current/min/max dimensions outrank every
             * desktop, tablet and mobile grid rule. The fixed-position tile
             * therefore remains exactly the size measured before lifting.
             */
            card.style.setProperty(
                "box-sizing",
                "border-box",
                "important"
            );
            card.style.setProperty(
                "width",
                dragWidth,
                "important"
            );
            card.style.setProperty(
                "min-width",
                dragWidth,
                "important"
            );
            card.style.setProperty(
                "max-width",
                dragWidth,
                "important"
            );
            card.style.setProperty(
                "height",
                dragHeight,
                "important"
            );
            card.style.setProperty(
                "min-height",
                dragHeight,
                "important"
            );
            card.style.setProperty(
                "max-height",
                dragHeight,
                "important"
            );

            card.classList.add("is-radio-dragging");
            block.classList.add("is-radio-drag-active");
            if (document.body) {
                document.body.classList.add(
                    "is-radio-reordering-drag"
                );
            }

            window.addEventListener(
                "pointermove",
                handleActivePointerMove,
                {capture: true, passive: false}
            );
            window.addEventListener(
                "pointerup",
                handleActivePointerEnd,
                true
            );
            window.addEventListener(
                "pointercancel",
                handleActivePointerEnd,
                true
            );
            window.addEventListener(
                "blur",
                handleActiveBlur,
                true
            );
        });

        handle.addEventListener("keydown", function(e) {
            if (!_radioReorderMode || _radioOrderSavePending) { return; }

            var direction = 0;
            if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                direction = -1;
            } else if (
                e.key === "ArrowRight" ||
                e.key === "ArrowDown"
            ) {
                direction = 1;
            }

            if (!direction) { return; }

            e.preventDefault();
            e.stopPropagation();
            moveCardByKeyboard(card, direction);
        });

        handle.addEventListener("click", function(e) {
            e.preventDefault();
            e.stopPropagation();
        });

        card.appendChild(handle);
    });

    updateModeUi();
}


function radioStationSignature(stations) {
    stations = Array.isArray(stations) ? stations : [];
    return stations.map(function(station) {
        station = station || {};
        return [
            String(station.id || ""),
            String(station.name || ""),
            String(station.url || ""),
            String(station.icon || station.image_url || "")
        ].join("\u001f");
    }).join("\u001e");
}

function invalidateRadioSourceCache() {
    _radioSourcePageCache = null;
    _radioSourceStationSignature = "";
    _radioSourceCacheGeneration += 1;
}

function refreshRadioSourceCache() {
    if (_radioSourceRefreshInFlight) { return; }

    _radioSourceRefreshInFlight = true;
    var refreshGeneration = _radioSourceCacheGeneration;

    fetch("/api/radio/stations")
        .then(function(r) { return r.json(); })
        .then(function(data) {
            _radioSourceRefreshInFlight = false;

            /*
             * Ignore a response that began before an explicit add/edit/delete
             * invalidation or a successful reorder.
             */
            if (refreshGeneration !== _radioSourceCacheGeneration) { return; }

            var stations = (data && Array.isArray(data.stations)) ?
                data.stations :
                [];
            var signature = radioStationSignature(stations);

            if (signature === _radioSourceStationSignature) { return; }

            /*
             * The station set, order or artwork identity changed. Discard the
             * retained Radio page. If Radio is currently visible, rebuild it
             * immediately from authoritative station data; otherwise the next
             * visit will build it normally.
             */
            invalidateRadioSourceCache();
            if (currentSourceSection === "radio") {
                showRadioSource(false, true);
            }
        })
        .catch(function() {
            _radioSourceRefreshInFlight = false;
        });
}


function buildRadioShelf(onReady) {
    fetch("/api/radio/stations")
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var stations = (data && data.stations) ? data.stations : [];
            _radioSourceStationSignature = radioStationSignature(stations);
            if (!stations.length) {
                onReady(null);
                return;
            }
            var items = stations.map(function(s) {
                return {
                    id:        s.id,
                    name:      s.name  || "",
                    sub_title: "Radio",
                    image_url: s.icon  || "",
                    type:      "radio",
                    url:       s.url   || ""
                };
            });
            var block = buildScrollSection("My Radio", items, function(item, e, anchor) {
                if (_radioReorderMode) {
                    if (e) { e.stopPropagation(); }
                    return;
                }
                showRadioStationMenu(anchor || (e ? e.currentTarget : null), item, e);
            }, { kind: "live", defaultQuality: "radio" });
            enhanceRadioShelfOrdering(block, items);
            onReady(block);
        })
        .catch(function() { onReady(null); });
}

function loadHome() {
    showView("home");
    setCurrentSourceSection("");
    setGlobalSearchVisible(true);
    refreshGlobalSearchAvailability();
    _cancelHomeSlotPolls();
    if (!homeSections) { return; }
    homeSections.innerHTML =
        '<section id="srovaGateway">' +
          '<div class="srovaGatewayBrand">' +
            '<img id="srovaGatewayLogo" class="srovaGatewayLogo" src="' + SROVA_STANDBY_ART + '" alt="SROVA">' +
            '<div class="srovaGatewayName">SROVA</div>' +
            '<div id="srovaHomeNowPlaying" class="srovaHomeNowPlaying"></div>' +
          '</div>' +
          '<div class="srovaSourceGatewayGrid" aria-label="SROVA sources">' +
            '<button class="srovaSourcePortal srovaSourcePortalRadio" data-home-source="radio" onclick="showRadioSource()">' +
              '<span class="srovaSourcePortalIndex">01</span>' +
              '<span class="srovaSourcePortalIcon material-icons">radio</span>' +
              '<span class="srovaSourcePortalTitle">RADIO</span>' +
              '<span class="srovaSourcePortalSub">Live Streams</span>' +
            '</button>' +
            '<button class="srovaSourcePortal srovaSourcePortalLocal" data-home-source="local" onclick="showLocalMusic()">' +
              '<span class="srovaSourcePortalIndex">02</span>' +
              '<span class="srovaSourcePortalIcon material-icons">library_music</span>' +
              '<span class="srovaSourcePortalTitle">MUSIC</span>' +
              '<span class="srovaSourcePortalSub">Owned Library</span>' +
            '</button>' +
            '<button class="srovaSourcePortal srovaSourcePortalTidal" data-home-source="tidal" onclick="showTidalSource()">' +
              '<span class="srovaSourcePortalIndex">03</span>' +
              '<span class="srovaSourcePortalIcon material-icons">graphic_eq</span>' +
              '<span class="srovaSourcePortalTitle">TIDAL</span>' +
              '<span class="srovaSourcePortalSub">Streaming Library</span>' +
            '</button>' +
          '</div>' +
        '</section>';

    setHomeGatewayAppPanel(true);
    homeHeroNowPlayingStateKey = "";
    updateHomeHeroNowPlaying(lastKnownPlaybackStatus);
    applyOnlineSourceAvailability(onlineSourcesAvailable);
    refreshOnlineSourceState();
}

function buildSourceSwitcher(activeSource) {
    function item(key, label, handler) {
        var active = (activeSource === key);
        return '<button class="srovaSourceSwitchItem' + (active ? ' active' : '') + '" data-source-switch="' + key + '" onclick="' + handler + '">' + label + '</button>';
    }
    return '<nav class="srovaSourceSwitcher" aria-label="Switch source">' +
        item("radio", "RADIO", "showRadioSource()") +
        item("music", "MUSIC", "showLocalMusic()") +
        item("tidal", "TIDAL", "showTidalSource()") +
      '</nav>';
}

function buildSourcePageShell(sourceClass, label, title, subTitle, activeSource) {
    var wrap = document.createElement("section");
    wrap.className = "srovaSourcePage " + sourceClass;
    wrap.innerHTML =
        '<div class="srovaSourcePageHeader">' +
          '<button class="srovaSourceBack" onclick="loadHome()" title="Home">' +
            '<span class="material-icons">arrow_back</span>' +
          '</button>' +
          '<div class="srovaSourcePageIdentity">' +
            '<div class="srovaSourcePageLabel">' + label + '</div>' +
            '<div class="srovaSourcePageTitle">' + title + '</div>' +
            '<div class="srovaSourcePageSub">' + subTitle + '</div>' +
          '</div>' +
          buildSourceSwitcher(activeSource || "") +
        '</div>' +
        '<div class="srovaSourcePageBody"></div>';
    return wrap;
}

var _srovaSetupGuardInFlight = {
    tidal: false,
    local: false,
    radio: false
};

function _srovaSetupGuardBlocked(message) {
    loadHome();
    showQueueActionToast(message, true);
}

function requireSrovaTidalLogin(onReady) {
    if (_srovaSetupGuardInFlight.tidal) { return; }
    _srovaSetupGuardInFlight.tidal = true;

    fetchWithTimeout(
        "/tidal/status?_=" + encodeURIComponent(String(Date.now())),
        {cache: "no-store"},
        4000
    )
    .then(function(res) {
        if (!res.ok) { throw new Error("TIDAL status unavailable"); }
        return res.json();
    })
    .then(function(data) {
        _srovaSetupGuardInFlight.tidal = false;
        data = data || {};

        if (data.logged_in === true) {
            updateLoginBtn(true, {skipSettingsRefresh: true});
            if (typeof onReady === "function") { onReady(); }
            return;
        }

        updateLoginBtn(false, {skipSettingsRefresh: true});
        _srovaSetupGuardBlocked(
            "Please log in to your TIDAL account first."
        );
    })
    .catch(function() {
        _srovaSetupGuardInFlight.tidal = false;
        _srovaSetupGuardBlocked(
            "Could not verify TIDAL login. Please open Settings and try again."
        );
    });
}

function requireSrovaMusicFolder(onReady) {
    if (_srovaSetupGuardInFlight.local) { return; }
    _srovaSetupGuardInFlight.local = true;

    fetchWithTimeout(
        "/api/local/library/status",
        {cache: "no-store"},
        4000
    )
    .then(function(res) {
        if (!res.ok) { throw new Error("Local library status unavailable"); }
        return res.json();
    })
    .then(function(data) {
        _srovaSetupGuardInFlight.local = false;
        data = data || {};

        var roots = Array.isArray(data.configured_roots) ?
            data.configured_roots :
            (Array.isArray(data.roots) ? data.roots : []);

        var configured = roots.some(function(root) {
            return !!String(root || "").trim();
        });

        if (configured) {
            if (typeof onReady === "function") { onReady(); }
            return;
        }

        _srovaSetupGuardBlocked(
            "Please go to Settings and select a music folder first."
        );
    })
    .catch(function() {
        _srovaSetupGuardInFlight.local = false;
        _srovaSetupGuardBlocked(
            "Could not verify My Music setup. Please open Settings and try again."
        );
    });
}

function requireSrovaRadioDac(onReady) {
    if (_srovaSetupGuardInFlight.radio) { return; }
    _srovaSetupGuardInFlight.radio = true;

    fetchWithTimeout(
        "/api/audio/output",
        {cache: "no-store"},
        4000
    )
    .then(function(res) {
        if (!res.ok) { throw new Error("Audio output status unavailable"); }
        return res.json();
    })
    .then(function(data) {
        _srovaSetupGuardInFlight.radio = false;
        data = data || {};

        var dacName = String(data.dac_name || "").trim();
        var device = String(data.alsa_device || "").trim();
        if (dacName && device) {
            if (typeof onReady === "function") { onReady(); }
            return;
        }

        _srovaSetupGuardBlocked(
            "Please go to Settings and select your DAC first."
        );
    })
    .catch(function() {
        _srovaSetupGuardInFlight.radio = false;
        _srovaSetupGuardBlocked(
            "Could not verify DAC setup. Please open Settings and try again."
        );
    });
}

function showRadioSource(preserveReorderMode, setupVerified) {
    if (setupVerified !== true) {
        requireSrovaRadioDac(function() {
            showRadioSource(preserveReorderMode, true);
        });
        return;
    }
    if (preserveReorderMode !== true) {
        _radioReorderMode = false;
    }
    if (!onlineSourcesAvailable) {
        console.log("Radio click allowed despite stale online-source offline state");
    }
    showView("home");
    setHomeGatewayAppPanel(false);
    setCurrentSourceSection("radio");
    setGlobalSearchVisible(false);
    _cancelHomeSlotPolls();

    /*
     * Fast path: reattach the exact Radio page and image elements that were
     * already rendered. Do not recreate or reassign artwork src values.
     */
    if (_radioSourcePageCache) {
        if (_radioSourcePageCache.parentNode !== homeSections) {
            homeSections.innerHTML = "";
            homeSections.appendChild(_radioSourcePageCache);
        }
        _syncHomePlayingTiles(_radioSourcePageCache);
        refreshRadioSourceCache();
        return;
    }

    homeSections.innerHTML = "";
    var shell = buildSourcePageShell("srovaRadioSourcePage", "SOURCE 01", "Radio", "Live Streams", "radio");
    var body = shell.querySelector(".srovaSourcePageBody");
    var slot = document.createElement("div");
    slot.id = "homeRadioSlot";
    body.appendChild(slot);
    homeSections.appendChild(shell);

    buildRadioShelf(function(block) {
        if (block) {
            body.replaceChild(block, slot);
        } else {
            slot.className = "srovaSourceEmpty";
            slot.textContent = "No radio stations configured.";
        }
        _radioSourcePageCache = shell;
    });
}


function tidalSourceSearchHasResults(data) {
    data = data || {};
    return !!((data.tracks && data.tracks.length) ||
              (data.albums && data.albums.length) ||
              (data.artists && data.artists.length));
}

function persistTidalSourceSearchState(query, data) {
    query = String(query || "").trim();
    if (query) { lastTidalSourceSearchQuery = query; }
    if (data && tidalSourceSearchHasResults(data)) { lastTidalSourceSearchPayload = data; }
    try {
        if (lastTidalSourceSearchQuery) {
            sessionStorage.setItem("srovaTidalSourceSearchQuery", lastTidalSourceSearchQuery);
        }
        if (lastTidalSourceSearchPayload) {
            sessionStorage.setItem("srovaTidalSourceSearchPayload", JSON.stringify(lastTidalSourceSearchPayload));
        }
    } catch (e) {}
}

function clearTidalSourceSearchState() {
    lastTidalSourceSearchQuery = "";
    lastTidalSourceSearchPayload = null;
    try {
        sessionStorage.removeItem("srovaTidalSourceSearchQuery");
        sessionStorage.removeItem("srovaTidalSourceSearchPayload");
    } catch (e) {}
}

function setTidalSourceBackMode(searchActive) {
    var backBtn = document.querySelector(".srovaTidalSourcePage .srovaSourceBack");
    if (!backBtn) { return; }
    backBtn.onclick = searchActive ? function() {
        clearTidalSourceSearchAndLanding();
    } : function() {
        loadHome();
    };
}

function clearTidalSourceSearchAndLanding() {
    var input = document.getElementById("tidalSourceSearchInput");
    if (input) { input.value = ""; }
    currentTidalSourceSearchTab = "top";
    clearTidalSourceSearchState();
    setTidalSourceSearchStatus("");
    var results = document.getElementById("tidalSourceSearchResults");
    if (results) { results.innerHTML = ""; }
    setTidalSourceBackMode(false);
}

function readSavedTidalSourceSearchPayload() {
    if (lastTidalSourceSearchPayload && tidalSourceSearchHasResults(lastTidalSourceSearchPayload)) {
        return lastTidalSourceSearchPayload;
    }
    try {
        var raw = sessionStorage.getItem("srovaTidalSourceSearchPayload") || "";
        if (!raw) { return null; }
        var parsed = JSON.parse(raw);
        return tidalSourceSearchHasResults(parsed) ? parsed : null;
    } catch (e) {
        return null;
    }
}

function getSavedTidalSourceSearchQuery() {
    var q = String(lastTidalSourceSearchQuery || "").trim();
    if (q) { return q; }
    try { q = String(sessionStorage.getItem("srovaTidalSourceSearchQuery") || "").trim(); } catch (e) {}
    return q;
}

function captureTidalSourceSearchStateFromDom() {
    var input = document.getElementById("tidalSourceSearchInput");
    var q = input && input.value ? input.value.trim() : getSavedTidalSourceSearchQuery();
    persistTidalSourceSearchState(q, lastTidalSourceSearchPayload);
}

function restoreTidalSourceSearchIntoCurrentPage() {
    var input = document.getElementById("tidalSourceSearchInput");
    var results = document.getElementById("tidalSourceSearchResults");
    if (!results) { return; }

    var q = getSavedTidalSourceSearchQuery();
    if (input && q) { input.value = q; }

    var payload = readSavedTidalSourceSearchPayload();
    if (payload && tidalSourceSearchHasResults(payload)) {
        lastTidalSourceSearchPayload = payload;
        renderTidalSourceSearchResults(payload);
        return;
    }

    if (q) {
        searchTidalSource(q);
    }
}

function restoreTidalSourceView() {
    showTidalSource({ restoreSearch: true });
}

function isInsideTidalSourceSearch(el) {
    return !!(el && el.closest && el.closest("#tidalSourceSearchResults"));
}


function showTidalSource(opts) {
    opts = opts || {};
    if (opts.srovaSetupVerified !== true) {
        requireSrovaTidalLogin(function() {
            var verifiedOpts = {};
            Object.keys(opts).forEach(function(key) {
                verifiedOpts[key] = opts[key];
            });
            verifiedOpts.srovaSetupVerified = true;
            showTidalSource(verifiedOpts);
        });
        return;
    }
    if (!requireOnlineSource()) { return; }
    var restoreSourceSearch = !!opts.restoreSearch;
    showView("home");
    setHomeGatewayAppPanel(false);
    setCurrentSourceSection("tidal");
    setGlobalSearchVisible(false);
    homeSections.innerHTML = "";
    _cancelHomeSlotPolls();

    var shell = buildSourcePageShell("srovaTidalSourcePage", "SOURCE 03", "Tidal", "Streaming Library", "tidal");
    var body = shell.querySelector(".srovaSourcePageBody");
    homeSections.appendChild(shell);
    attachTidalSourceSearch(body, restoreSourceSearch);

    var tidalDone = false;
    var hiresDone = false;
    var tidalData = [];
    var hiresData = [];

    // Placeholder slots -- empty divs inserted into the page immediately.
    // _pollHomeSlot() replaces each one in-place when data arrives.
    var songSlot     = document.createElement("div");
    var albumSlot    = document.createElement("div");
    var featuredSlot = document.createElement("div");
    songSlot.id      = "homeSongSlot";
    albumSlot.id     = "homeAlbumSlot";
    featuredSlot.id  = "homeFeaturedSlot";

    // Phase 1: render fast sections as soon as hires + home land.
    // My Songs / My Albums / Featured slots are placed but empty -- they fill in async.
    function _renderFast() {
        if (!tidalDone || !hiresDone) { return; }
        body.innerHTML = "";
        attachTidalSourceSearch(body, restoreSourceSearch);

        hiresData.forEach(function(sec) {
            body.appendChild(buildScrollSection(
                sec.title, sec.items,
                function(item, e, anchorEl) { handleTidalWallItemClick(item, "home", e, anchorEl); },
                { kind: "curated", defaultQuality: "hires" }
            ));
        });

        body.appendChild(songSlot);
        body.appendChild(albumSlot);
        body.appendChild(featuredSlot);

        tidalData.forEach(function(sec) {
            var isTrackSec = sec.items && sec.items.some(function(it) {
                return (it.type || "").toLowerCase() === "track";
            });
            var block = buildScrollSection(
                sec.title, sec.items,
                function(item, e, anchorEl) { handleTidalWallItemClick(item, "home", e, anchorEl); },
                { kind: "curated" }
            );
            if (isTrackSec) {
                var h = block.querySelector("h2");
                if (h) {
                    h.style.cursor = "pointer";
                    h.title = "See all";
                    (function(title, items) {
                        h.onclick = function() { showFeaturedTrackList(title, items); };
                    }(sec.title, sec.items));
                }
            }
            body.appendChild(block);
        });

        // Phase 2: poll the slow sections independently every 1.5s.
        _pollHomeSlot("/tidal/mysongs",  songSlot,  "My Songs",
            function(d) { window._mySongsData  = d; },
            function(item, e, anchorEl) { handleTidalWallItemClick(item, "home", e, anchorEl); },
            function() { showMySongs(); },
            { kind: "library" }
        );
        _pollHomeSlot("/tidal/myalbums", albumSlot, "My Albums",
            function(d) { window._myAlbumsData = d; },
            function(item, e, anchorEl) { handleTidalWallItemClick(item, "home", e, anchorEl); },
            function() { showMyAlbums(); },
            { kind: "library" }
        );
        _pollFeaturedSlot(featuredSlot);
    }

    fetchWithTimeout("/tidal/hires", {}, 5000)
        .then(function(r) { return r.json(); })
        .then(function(d) { hiresData = Array.isArray(d) ? d : []; hiresDone = true; _renderFast(); })
        .catch(function()  { hiresDone = true; _renderFast(); });

    fetchWithTimeout("/tidal/home", {}, 5000)
        .then(function(r) { return r.json(); })
        .then(function(d) { tidalData = Array.isArray(d) ? d : []; tidalDone = true; _renderFast(); })
        .catch(function()  { tidalDone = true; _renderFast(); });
}

function attachTidalSourceSearch(body, restoreSearch) {
    if (!body) { return; }
    setTidalSourceBackMode(false);
    var toolbar = document.createElement("div");
    toolbar.id = "tidalSourceSearchToolbar";
    toolbar.innerHTML =
        '<div id="tidalSourceSearchBox">' +
          '<span class="material-icons">search</span>' +
          '<input id="tidalSourceSearchInput" type="text" placeholder="Search Tidal songs, albums, artists..." autocomplete="off">' +
        '</div>' +
        '<div id="tidalSourceSearchStatus"></div>';
    body.appendChild(toolbar);

    var wrap = document.createElement("div");
    wrap.id = "tidalSourceSearchWrap";
    wrap.innerHTML = '<div id="tidalSourceSearchResults"></div>';
    body.appendChild(wrap);

    var input = toolbar.querySelector("#tidalSourceSearchInput");
    if (!input) { return; }
    var timer = null;
    input.oninput = function() {
        var query = input.value.trim();
        clearTimeout(timer);
        timer = setTimeout(function() {
            if (query) {
                currentTidalSourceSearchTab = "top";
                searchTidalSource(query);
            } else {
                clearTidalSourceSearchAndLanding();
            }
        }, 300);
    };
    input.onkeydown = function(e) {
        if (e.key === "Escape") {
            clearTidalSourceSearchAndLanding();
        }
    };

    if (restoreSearch) {
        restoreTidalSourceSearchIntoCurrentPage();
    }
    applyOnlineSourceAvailability(onlineSourcesAvailable);
}

function setTidalSourceSearchStatus(text) {
    var el = document.getElementById("tidalSourceSearchStatus");
    if (el) { el.textContent = text || ""; }
}

function searchTidalSource(query) {
    if (!requireOnlineSource()) {
        setTidalSourceSearchStatus(ONLINE_SOURCE_OFFLINE_MESSAGE);
        return;
    }
    query = String(query || "").trim();
    persistTidalSourceSearchState(query, lastTidalSourceSearchPayload);
    var results = document.getElementById("tidalSourceSearchResults");
    if (!results) { return; }
    setTidalSourceSearchStatus("Searching Tidal...");
    fetchWithTimeout("/tidal/search?q=" + encodeURIComponent(query) + "&limit=" + TIDAL_SEARCH_LIMIT, {}, 4500)
        .then(function(res) { return res.json(); })
        .then(function(data) {
            setTidalSourceSearchStatus("");
            persistTidalSourceSearchState(query, data || {});
            renderTidalSourceSearchResults(data || {});
        })
        .catch(function() {
            refreshOnlineSourceState();
            setTidalSourceSearchStatus(ONLINE_SOURCE_OFFLINE_MESSAGE);
        });
}

function renderTidalSourceSearchResults(data) {
    var results = document.getElementById("tidalSourceSearchResults");
    if (!results) { return; }
    results.innerHTML = "";
    var hasSearchPayload = !!(data && (data.tracks || data.albums || data.artists));
    setTidalSourceBackMode(hasSearchPayload);
    var normalized = normalizeSrovaSearchPayload({
        query: getSavedTidalSourceSearchQuery(),
        local: { ok: true, data: {} },
        tidal: { ok: true, data: data || {} }
    });
    if (!normalized.hasAny) {
        if (!hasSearchPayload) { return; }
        results.innerHTML = '<div class="searchLoading">No Tidal results found.</div>';
        return;
    }
    renderSrovaSearchShellInto(results, normalized, {
        title: "TIDAL Search",
        sourceView: "tidalsource",
        getTab: function() { return currentTidalSourceSearchTab || "top"; },
        setTab: function(tab) { currentTidalSourceSearchTab = tab || "top"; }
    });
}

function buildLocalMusicSection() {
    var item = {
        id: "local-music",
        type: "local",
        name: "Music",
        sub_title: "Owned library"
    };
    return buildScrollSection(
        "Music",
        [item],
        function() { showLocalMusic(); },
        { kind: "library", defaultQuality: "cd" }
    );
}

function isLocalLibraryMaintenance(data) {
    data = data || localLibraryMaintenanceState || {};
    return !!(data.rebuild_running || data.maintenance_mode === "local_library_rebuild");
}

function applyLocalLibraryMaintenanceState(data) {
    data = data || {};
    localLibraryMaintenanceState = {
        rebuild_running: !!data.rebuild_running,
        maintenance_mode: data.maintenance_mode || null,
        scan_running: !!data.scan_running,
        scan_started_at: data.scan_started_at || null,
        scan_finished_at: data.scan_finished_at || null,
        last_scan_stats: data.last_scan_stats || localLibraryMaintenanceState.last_scan_stats || null
    };
    updateLocalMusicMaintenanceUi();
    if (isLocalLibraryMaintenance(localLibraryMaintenanceState)) {
        startLocalLibraryMaintenancePoll();
    } else {
        stopLocalLibraryMaintenancePoll();
    }
}

function localLibraryFinalStatsText(stats) {
    if (!stats) { return ""; }
    return localLibraryScanCountsText(stats);
}

function localMusicMaintenanceMessage() {
    return (
        '<div class="localMusicMaintenanceOverlay">' +
          '<div class="localMusicMaintenanceTitle">Rebuilding Local Music Library…</div>' +
          '<div class="localMusicMaintenanceBody">' +
            '<div>SROVA is recreating the local library index.</div>' +
            '<div>Your music files are safe and are not being modified.</div>' +
            '<div>Please wait until the scan finishes before using Local Music.</div>' +
          '</div>' +
        '</div>'
    );
}

function renderLocalMusicMaintenanceLockout() {
    var results = document.getElementById("localMusicResults");
    var browse = document.getElementById("localMusicBrowse");
    if (results) { results.innerHTML = ""; }
    if (browse) { browse.innerHTML = localMusicMaintenanceMessage(); }
    setLocalMusicStatus("Rebuilding local library...");
}

function updateLocalMusicMaintenanceUi() {
    var locked = isLocalLibraryMaintenance(localLibraryMaintenanceState);
    if (localMusicView) { localMusicView.classList.toggle("localMusicLocked", locked); }
    if (albumView && albumView.classList.contains("localAlbumDetail")) {
        albumView.classList.toggle("localMusicLocked", locked);
    }
    var input = document.getElementById("localMusicSearchInput");
    var dateBtn = document.getElementById("localMusicDateSortBtn");
    var alphaBtn = document.getElementById("localMusicAlphaSortBtn");
    if (input) { input.disabled = locked; }
    if (dateBtn) { dateBtn.disabled = locked; }
    if (alphaBtn) { alphaBtn.disabled = locked; }
    if (locked && localMusicView && localMusicView.style.display !== "none") {
        renderLocalMusicMaintenanceLockout();
    }
}

function fetchLocalLibraryStatus() {
    return fetch("/api/local/library/status")
        .then(function(res) { return res.json(); })
        .then(function(data) {
            applyGlobalSearchLocalStatus(data || {});
            applyLocalLibraryMaintenanceState(data || {});
            return data || {};
        });
}

function startLocalLibraryMaintenancePoll() {
    if (localLibraryMaintenancePoll) { return; }
    localLibraryMaintenancePoll = setInterval(function() {
        fetchLocalLibraryStatus().then(function(data) {
            if (!isLocalLibraryMaintenance(data)) {
                if (localMusicView && localMusicView.style.display !== "none") {
                    renderLocalMusicShell();
                    loadLocalMusicBrowse();
                    var text = localLibraryFinalStatsText(data && data.last_scan_stats);
                    if (text) { setLocalMusicStatus("Rebuild complete. " + text); }
                }
            }
        }).catch(function() {});
    }, 2000);
}

function stopLocalLibraryMaintenancePoll() {
    if (localLibraryMaintenancePoll) {
        clearInterval(localLibraryMaintenancePoll);
        localLibraryMaintenancePoll = null;
    }
}

function showLocalMusic(setupVerified) {
    if (setupVerified !== true) {
        requireSrovaMusicFolder(function() {
            showLocalMusic(true);
        });
        return;
    }
    showView("localmusic");
    setCurrentSourceSection("music");
    setGlobalSearchVisible(false);
    renderLocalMusicShell();
    fetchLocalLibraryStatus().then(function(data) {
        if (isLocalLibraryMaintenance(data)) {
            renderLocalMusicMaintenanceLockout();
            return;
        }
        loadLocalMusicBrowse();
    }).catch(function() {
        loadLocalMusicBrowse();
    });
}

function renderLocalMusicShell() {
    if (!localMusicContent) { return; }
    localMusicContent.innerHTML = "";
    var shell = buildSourcePageShell("srovaMusicSourcePage", "SOURCE 02", "Music", "Owned Library", "music");
    var body = shell.querySelector(".srovaSourcePageBody");
    body.innerHTML =
        '<div id="localMusicPanel" class="localMusicAlbumOnly">' +
          '<div class="homeSection localMusicLandingSection" data-kind="library">' +
            '<div id="localMusicSearchBox">' +
              '<span class="material-icons">search</span>' +
              '<input id="localMusicSearchInput" type="text" placeholder="Search local songs, albums, artists..." autocomplete="off">' +
            '</div>' +
            '<div id="localMusicSortControls" aria-label="Album sort controls">' +
              '<button id="localMusicDateSortBtn" class="localMusicSortBtn" type="button"></button>' +
              '<button id="localMusicAlphaSortBtn" class="localMusicSortBtn" type="button"></button>' +
            '</div>' +
          '</div>' +
          '<div id="localMusicStatus"></div>' +
          '<div id="localMusicResults"></div>' +
          '<div id="localMusicBrowse"></div>' +
        '</div>';
    localMusicContent.appendChild(shell);
    applyOnlineSourceAvailability(onlineSourcesAvailable);
    setupLocalMusicSortControls();
    var input = document.getElementById("localMusicSearchInput");
    if (input) {
        var timer = null;
        input.oninput = function() {
            if (isLocalLibraryMaintenance()) {
                renderLocalMusicMaintenanceLockout();
                return;
            }
            var query = input.value.trim();
            clearTimeout(timer);
            timer = setTimeout(function() {
                if (query) {
                    currentLocalMusicSearchTab = "top";
                    searchLocalMusic(query);
                } else {
                    clearLocalMusicSearchAndBrowse();
                }
            }, 250);
        };
        input.onkeydown = function(e) {
            if (isLocalLibraryMaintenance()) {
                renderLocalMusicMaintenanceLockout();
                return;
            }
            if (e.key === "Escape") {
                clearLocalMusicSearchAndBrowse();
            }
        };
    }
}

function setLocalMusicSourceBackMode(searchActive) {
    var backBtn = document.querySelector(".srovaMusicSourcePage .srovaSourceBack");
    if (!backBtn) { return; }
    backBtn.onclick = searchActive ? function() {
        clearLocalMusicSearchAndBrowse();
    } : function() {
        loadHome();
    };
}

function setLocalMusicArtistDetailBackMode() {
    var backBtn = document.querySelector(".srovaMusicSourcePage .srovaSourceBack");
    if (!backBtn) { return; }
    backBtn.onclick = function() {
        restoreLocalMusicSearchResults();
    };
}

function setLocalMusicGlobalSearchBackMode() {
    var backBtn = document.querySelector(".srovaMusicSourcePage .srovaSourceBack");
    if (!backBtn) { return; }
    backBtn.onclick = function() {
        setGlobalSearchVisible(true);
        restoreSearchView();
    };
}

function openLocalArtistFromGlobalSearch(artist, artistCover, artistAlbumArtwork) {
    captureSearchRestoreState();
    showView("localmusic");
    setCurrentSourceSection("music");
    setGlobalSearchVisible(false);
    renderLocalMusicShell();
    loadLocalArtist(
        artist || "",
        artistCover || "",
        artistAlbumArtwork || {}
    );
    setLocalMusicGlobalSearchBackMode();
}

function openLocalArtistFromPlayerBar(artist, artistCover) {
    artist = String(artist || "").trim();
    if (!artist) { return; }
    showView("localmusic");
    setCurrentSourceSection("music");
    setGlobalSearchVisible(false);
    renderLocalMusicShell();
    loadLocalArtist(artist, artistCover || "");
    var backBtn = document.querySelector(".srovaMusicSourcePage .srovaSourceBack");
    if (backBtn) {
        backBtn.onclick = function() { loadHome(); };
    }
}

function restoreLocalMusicSearchResults() {
    setLocalMusicSortControlsVisible(true);
    var input = document.getElementById("localMusicSearchInput");
    var query = String(lastLocalMusicSearchQuery || "").trim();
    var results = document.getElementById("localMusicResults");
    var browse = document.getElementById("localMusicBrowse");

    if (input && query) { input.value = query; }
    if (browse) { browse.innerHTML = ""; }
    setLocalMusicStatus("");

    if (lastLocalMusicSearchPayload) {
        renderLocalMusicResults(lastLocalMusicSearchPayload);
        return;
    }
    if (query) {
        searchLocalMusic(query);
        return;
    }
    if (results) { results.innerHTML = ""; }
    clearLocalMusicSearchAndBrowse();
}

function clearLocalMusicSearchAndBrowse() {
    var input = document.getElementById("localMusicSearchInput");
    if (input) { input.value = ""; }
    currentLocalMusicSearchTab = "top";
    lastLocalMusicSearchQuery = "";
    lastLocalMusicSearchPayload = null;
    setLocalMusicStatus("");
    var results = document.getElementById("localMusicResults");
    if (results) { results.innerHTML = ""; }
    loadLocalMusicBrowse();
}

function setLocalMusicAlbumSort(sort) {
    if (sort !== "latest" && sort !== "oldest" && sort !== "alpha_asc" && sort !== "alpha_desc") {
        sort = "latest";
    }
    localMusicAlbumSort = sort;
    try { localStorage.setItem(LOCAL_MUSIC_SORT_STORAGE_KEY, sort); } catch (e) {}
    updateLocalMusicSortControls();
}

function setLocalMusicSortControlsVisible(visible) {
    var controls = document.getElementById("localMusicSortControls");
    if (!controls) { return; }
    if (visible) {
        controls.style.removeProperty("display");
    } else {
        controls.style.setProperty("display", "none", "important");
    }
}

function setupLocalMusicSortControls() {
    var dateBtn = document.getElementById("localMusicDateSortBtn");
    var alphaBtn = document.getElementById("localMusicAlphaSortBtn");
    if (dateBtn) {
        dateBtn.onclick = function() {
            if (isLocalLibraryMaintenance()) { return; }
            setLocalMusicAlbumSort(localMusicAlbumSort === "latest" ? "oldest" : "latest");
            loadLocalMusicBrowse();
        };
    }
    if (alphaBtn) {
        alphaBtn.onclick = function() {
            if (isLocalLibraryMaintenance()) { return; }
            setLocalMusicAlbumSort(localMusicAlbumSort === "alpha_asc" ? "alpha_desc" : "alpha_asc");
            loadLocalMusicBrowse();
        };
    }
    updateLocalMusicSortControls();
}

function updateLocalMusicSortControls() {
    var dateBtn = document.getElementById("localMusicDateSortBtn");
    var alphaBtn = document.getElementById("localMusicAlphaSortBtn");
    if (dateBtn) {
        dateBtn.textContent = localMusicAlbumSort === "oldest" ? "Oldest" : "Latest";
        dateBtn.classList.toggle("active", localMusicAlbumSort === "latest" || localMusicAlbumSort === "oldest");
        dateBtn.title = localMusicAlbumSort === "oldest" ? "Oldest to newest" : "Latest to oldest";
    }
    if (alphaBtn) {
        alphaBtn.textContent = localMusicAlbumSort === "alpha_desc" ? "Z-A" : "A-Z";
        alphaBtn.classList.toggle("active", localMusicAlbumSort === "alpha_asc" || localMusicAlbumSort === "alpha_desc");
        alphaBtn.title = localMusicAlbumSort === "alpha_desc" ? "Z to A" : "A to Z";
    }
}

function setLocalMusicStatus(text) {
    var el = document.getElementById("localMusicStatus");
    if (el) { el.textContent = text || ""; }
}

function searchLocalMusic(query) {
    setLocalMusicSortControlsVisible(true);
    if (isLocalLibraryMaintenance()) {
        renderLocalMusicMaintenanceLockout();
        return;
    }
    lastLocalMusicSearchQuery = String(query || "").trim();
    lastLocalMusicSearchPayload = null;
    var results = document.getElementById("localMusicResults");
    var browse = document.getElementById("localMusicBrowse");
    if (!results) { return; }
    setLocalMusicStatus("Searching local library...");
    if (browse) { browse.innerHTML = ""; }
    fetch("/api/local/library/search?q=" + encodeURIComponent(query) + "&limit=100")
        .then(function(r) { return r.json(); })
        .then(function(data) {
            setLocalMusicStatus("");
            renderLocalMusicResults(data || {});
        })
        .catch(function() { setLocalMusicStatus("Local search failed."); });
}

function loadLocalMusicBrowse() {
    setLocalMusicSortControlsVisible(true);
    if (isLocalLibraryMaintenance()) {
        renderLocalMusicMaintenanceLockout();
        return;
    }
    var browse = document.getElementById("localMusicBrowse");
    if (!browse) { return; }
    setLocalMusicSourceBackMode(false);
    setLocalMusicStatus("Loading music library...");
    browse.innerHTML = "";
    fetch("/api/local/library/albums?limit=500&sort=" + encodeURIComponent(localMusicAlbumSort || "latest"))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            setLocalMusicStatus("");
            renderLocalMusicBrowse(data || {});
        })
        .catch(function() {
            setLocalMusicStatus("Could not load My Music.");
        });
}

function renderLocalMusicStats(status) {
    var tracks = document.getElementById("localMusicTrackCount");
    var scan = document.getElementById("localMusicScanState");
    var roots = document.getElementById("localMusicRootCount");
    if (tracks) { tracks.textContent = String(status.track_count || 0); }
    if (scan) { scan.textContent = status.scan_running ? "Scanning" : "Ready"; }
    if (roots) { roots.textContent = String((status.roots || []).length || 0); }
}

function renderLocalMusicResults(data) {
    var results = document.getElementById("localMusicResults");
    if (!results) { return; }
    var input = document.getElementById("localMusicSearchInput");
    var query = String(
        (data && data.query) ||
        (input && input.value) ||
        lastLocalMusicSearchQuery ||
        ""
    ).trim();
    lastLocalMusicSearchQuery = query;
    lastLocalMusicSearchPayload = data || {};
    setLocalMusicSourceBackMode(true);
    var normalized = normalizeSrovaSearchPayload({
        query: data && data.query ? data.query : "",
        local: { ok: true, data: data || {} },
        tidal: { ok: true, data: {} }
    });
    if (!normalized.hasAny) {
        results.innerHTML = '<div class="localMusicEmpty">No local results found.</div>';
        return;
    }
    renderSrovaSearchShellInto(results, normalized, {
        sourceView: "localmusic",
        title: "Music Search",
        getTab: function() { return currentLocalMusicSearchTab || "top"; },
        setTab: function(tab) { currentLocalMusicSearchTab = tab || "top"; }
    });
}

function renderLocalMusicBrowse(albumsData) {
    var browse = document.getElementById("localMusicBrowse");
    if (!browse) { return; }
    browse.innerHTML = "";
    var albums = albumsData.albums || [];

    var browseControls = document.getElementById("localMusicSortControls");
    if (browseControls) {
        var existingBrowseToggle = browseControls.querySelector(".artworkViewToggle");
        if (existingBrowseToggle && existingBrowseToggle.parentNode) {
            existingBrowseToggle.parentNode.removeChild(existingBrowseToggle);
        }
    }

    if (albums.length) {
        var albumSection = localMusicSection("Albums", albums, renderLocalAlbumRow, true);
        browse.appendChild(albumSection);

        var browseToggle = albumSection.querySelector(".artworkViewToggle");
        if (browseToggle && browseControls) {
            browseControls.appendChild(browseToggle);
        }
    }
    if (!albums.length) {
        browse.innerHTML = '<div class="localMusicEmpty">Run a local library scan to populate My Music.</div>';
    }
}

function localMusicSection(title, items, rowRenderer, asCards) {
    var sec = document.createElement("div");
    sec.className = "localMusicSection";
    if (asCards) { sec.classList.add("localMusicCardSection"); }
    var h = document.createElement("h2");
    h.textContent = title;
    if (asCards) {
        var hWrap = document.createElement("div");
        hWrap.className = "artworkViewHeader";
        hWrap.appendChild(h);
        appendArtworkViewToggle(hWrap);
        sec.appendChild(hWrap);
    } else {
        sec.appendChild(h);
    }
    var body = document.createElement("div");
    body.className = asCards ? "localMusicCardGrid" : "localMusicList";
    if (asCards) { applyArtworkViewModeClass(body); }
    items.forEach(function(item) { body.appendChild(rowRenderer(item)); });
    sec.appendChild(body);
    return sec;
}

function localInitials(value) {
    var text = String(value || "").trim();
    if (!text) { return "S"; }
    var parts = text.split(/\s+/).filter(Boolean);
    if (parts.length === 1) { return parts[0].slice(0, 2).toUpperCase(); }
    return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
}

function renderLocalSongRow(track) {
    var row = document.createElement("div");
    row.className = "localMusicRow localMusicSong";
    var artwork = track.cover || track.cover_url || track.artwork_url ||
        track.image_url || track.album_art || track.album_art_url || "";
    var leading = artwork
        ? '<img class="localMusicGlyph localMusicSongArtwork" src="' + escapeHtml(artwork) + '" alt="">'
        : '<div class="localMusicGlyph"><span class="material-icons">music_note</span></div>';
    row.innerHTML =
        leading +
        '<div class="localMusicMeta">' +
          '<div class="localMusicName">' + escapeHtml(track.title || "") + '</div>' +
          '<div class="localMusicSub">' + escapeHtml(track.artist || "") + ' - ' + escapeHtml(track.album || "") + '</div>' +
        '</div>' +
        '<div class="localMusicDuration">' + formatTime(track.duration || 0) + '</div>';
    applyLocalArtworkFallback(
        row.querySelector(".localMusicSongArtwork"),
        track.album || track.title || "",
        track.artist || ""
    );
    row.onclick = function() {
        if (isLocalLibraryMaintenance()) {
            showQueueActionToast("Local Music is rebuilding", true);
            return;
        }
        playLocalLibraryTrack(track);
    };
    return row;
}

function renderLocalAlbumRow(album) {
    var row = document.createElement("div");
    row.className = "localMusicCard localMusicAlbumCard";
    var title = album.album || "";
    var artist = album.artist || "";
    var art = localAlbumArtworkUrl(album, title, artist);
    row.setAttribute("data-local-album-id", album.album_id || album.group_id || "");
    row.setAttribute("data-local-album-artist", artist);
    row.setAttribute("data-local-album-title", title);
    row.innerHTML =
        '<img class="localAlbumArtwork localAlbumArt" src="' + escapeHtml(art) + '" alt="">' +
        '<div class="localMusicCardMeta">' +
          '<div class="localMusicName">' + escapeHtml(title) + '</div>' +
          '<div class="localMusicSub">' + escapeHtml(artist) + ' &middot; ' + (album.track_count || 0) + ' tracks</div>' +
        '</div>';
    applyLocalArtworkFallback(row.querySelector(".localAlbumArtwork"), title, artist);
    applyLocalAlbumCardQuality(row, localAlbumCardQualityClass(album.album_quality));
    row.onclick = function() {
        if (isLocalLibraryMaintenance()) {
            renderLocalMusicMaintenanceLockout();
            return;
        }
        loadLocalAlbum(album.artist || "", album.album || "", album.album_id || album.group_id || "");
    };
    return row;
}

function renderLocalArtistRow(artist) {
    var row = document.createElement("div");
    row.className = "localMusicCard localMusicArtistCard";
    row.innerHTML =
        '<div class="localArtPlaceholder localArtistArt"><span>' + escapeHtml(localInitials(artist.artist || "")) + '</span></div>' +
        '<div class="localMusicCardMeta">' +
          '<div class="localMusicName">' + escapeHtml(artist.artist || "") + '</div>' +
          '<div class="localMusicSub">' + (artist.album_count || 0) + ' albums &middot; ' + (artist.track_count || 0) + ' tracks</div>' +
        '</div>';
    row.onclick = function() {
        if (isLocalLibraryMaintenance()) {
            renderLocalMusicMaintenanceLockout();
            return;
        }
        loadLocalArtist(artist.artist || "");
    };
    return row;
}

function localDetailHeader(kind, title, sub, artworkUrl) {
    var wrap = document.createElement("div");
    wrap.className = "localDetailHeader";
    var artwork = String(artworkUrl || "");
    var detailArt = artwork
        ? '<img class="localDetailArt localDetailArtistArtwork" src="' + escapeHtml(artwork) + '" alt="">'
        : '<div class="localArtPlaceholder localDetailArt">' +
            '<span class="localArtRing"></span>' +
            '<span class="material-icons">' + (kind === "artist" ? "person" : "album") + '</span>' +
          '</div>';
    wrap.innerHTML =
        detailArt +
        '<div class="localDetailMeta">' +
          '<div class="localMusicEyebrow">' + (kind === "artist" ? "LOCAL ARTIST" : "LOCAL ALBUM") + '</div>' +
          '<div class="localDetailTitle">' + escapeHtml(title || "") + '</div>' +
          '<div class="localMusicSub">' + escapeHtml(sub || "") + '</div>' +
        '</div>';
    applyLocalArtworkFallback(
        wrap.querySelector(".localDetailArtistArtwork"),
        title || "",
        kind === "artist" ? title || "" : ""
    );
    return wrap;
}

function loadLocalAlbum(artist, album, albumId, fromView) {
    if (isLocalLibraryMaintenance()) {
        renderLocalMusicMaintenanceLockout();
        return;
    }
    setLocalMusicStatus("Loading album...");
    var url = albumId
        ? "/api/local/library/album?id=" + encodeURIComponent(albumId)
        : "/api/local/library/album?artist=" + encodeURIComponent(artist) + "&album=" + encodeURIComponent(album);
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            setLocalMusicStatus("");
            renderLocalAlbumDetail(data || {}, artist, album, fromView);
        })
        .catch(function() { setLocalMusicStatus("Album failed to load."); });
}

function normalizeLocalAlbumCodec(value) {
    var codec = String(value || "").trim();
    if (!codec || /^unknown$/i.test(codec) || /^n\/a$/i.test(codec) || /^none$/i.test(codec)) { return ""; }
    codec = codec.replace(/^audio\//i, "");
    return codec.toUpperCase();
}

function normalizeLocalAlbumSampleRate(value) {
    var rate = Number(value);
    if (!isFinite(rate) || rate <= 0) { return 0; }
    return rate < 1000 ? rate * 1000 : rate;
}

function formatLocalAlbumSampleRate(rate) {
    var khz = normalizeLocalAlbumSampleRate(rate) / 1000;
    if (!khz) { return ""; }
    return (Math.round(khz) === khz ? String(khz) : khz.toFixed(1).replace(/\.0$/, "")) + " kHz";
}

function localAlbumTrackTech(track) {
    track = track || {};
    var codec = normalizeLocalAlbumCodec(track.codec);
    var bitDepth = Number(track.bit_depth);
    var sampleRate = normalizeLocalAlbumSampleRate(track.sample_rate);
    if (!codec || !isFinite(bitDepth) || bitDepth <= 0 || !sampleRate) { return null; }
    return {
        codec: codec,
        bitDepth: bitDepth,
        sampleRate: sampleRate,
        hiRes: bitDepth > 16 || sampleRate > 48000,
        cdQuality: bitDepth <= 16 && sampleRate <= 48000
    };
}

function buildLocalAlbumTechSummary(tracks) {
    if (!Array.isArray(tracks) || tracks.length === 0) { return null; }

    var known = [];
    tracks.forEach(function(track) {
        var tech = localAlbumTrackTech(track);
        if (tech) { known.push(tech); }
    });
    if (!known.length) { return null; }

    var first = known[0];
    var codecMixed = known.some(function(tech) { return tech.codec !== first.codec; });
    var resolutionMixed = known.some(function(tech) {
        return tech.bitDepth !== first.bitDepth || tech.sampleRate !== first.sampleRate;
    });
    var hasMissingTech = known.length !== tracks.length;
    var anyHiRes = known.some(function(tech) { return tech.hiRes; });
    var allCdQuality = known.every(function(tech) { return tech.cdQuality; });
    var qualityClass = anyHiRes ? "localAlbumTechInfoHiRes" : (allCdQuality ? "localAlbumTechInfoCd" : "localAlbumTechInfoMixed");

    if (codecMixed) {
        return { text: "Mixed formats", className: "localAlbumTechInfo " + qualityClass };
    }
    if (resolutionMixed) {
        return { text: "Mixed resolution", className: "localAlbumTechInfo " + qualityClass };
    }
    if (hasMissingTech) {
        return null;
    }

    return {
        text: first.codec + " · " + first.bitDepth + "-bit · " + formatLocalAlbumSampleRate(first.sampleRate),
        className: "localAlbumTechInfo " + qualityClass
    };
}

function localAlbumCardQualityClass(value) {
    var quality = String(value || "").toLowerCase();
    if (quality === "hires" || quality === "hd") { return "localAlbumCardHiRes"; }
    if (quality === "cd" || quality === "sd") { return "localAlbumCardCd"; }
    return "";
}

function applyLocalAlbumCardQuality(row, qualityClass) {
    if (!row) { return; }
    row.classList.remove("localAlbumCardCd");
    row.classList.remove("localAlbumCardHiRes");
    if (qualityClass === "localAlbumCardCd" || qualityClass === "localAlbumCardHiRes") {
        row.classList.add(qualityClass);
    }
}

function localAlbumStatsText(trackCount, totalDuration) {
    var parts = [];
    if (trackCount) { parts.push(trackCount + (trackCount === 1 ? " track" : " tracks")); }
    if (totalDuration) { parts.push(formatDuration(totalDuration)); }
    return parts.join(" · ");
}

function renderLocalAlbumDetail(data, fallbackArtist, fallbackAlbum, fromView) {
    var tracks = Array.isArray(data.tracks) ? data.tracks : [];
    var title = data.album || fallbackAlbum || "Local Album";
    var artist = data.artist || data.album_artist || fallbackArtist || "Local Library";
    var totalDuration = data.duration || tracks.reduce(function(sum, t) {
        return sum + (Number(t.duration) || 0);
    }, 0);
    var techSummary = buildLocalAlbumTechSummary(tracks);
    var statsText = localAlbumStatsText(tracks.length, totalDuration);

    var returnView = fromView || "localmusic";
    captureDetailReturnScroll(returnView);
    previousView = returnView;
    currentViewEndpoint = "/local/album";
    var cover = localAlbumArtworkUrl(data, title, artist);
    currentContext = {
        id: data.album_id || data.group_id || (artist + "::" + title),
        cover: cover,
        title: title,
        artist: artist
    };
    originalTracks = tracks;
    shuffledTracks = [];
    currentViewTracks = tracks;
    _setPlaybackSource("local", currentContext.id, title);

    setAlbumViewKind("local");
    showView("album");
    albumArt.src = currentContext.cover;
    applyLocalArtworkFallback(albumArt, title, artist);
    albumTitle.textContent = title;
    albumArtist.textContent = artist;
    albumArtist.style.cursor = "";
    albumArtist.onclick = null;
    if (albumTechInfo) {
        if (techSummary && techSummary.text) {
            localAlbumDetailTechState = {
                text: techSummary.text,
                className: techSummary.className
            };
            albumTechInfo.textContent = techSummary.text;
            albumTechInfo.className = techSummary.className;
        } else {
            localAlbumDetailTechState = {
                text: "",
                className: "hidden"
            };
            albumTechInfo.textContent = "";
            albumTechInfo.className = "hidden";
        }
    }
    if (albumStatsLine) {
        albumStatsLine.textContent = statsText;
        albumStatsLine.className = statsText ? "localAlbumStatsLine" : "hidden";
    }

    renderLocalAlbumTrackList(tracks, artist);
    resetAlbumDetailScroll();
}

function normalizeLocalArtistName(value) {
    return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function isCompilationArtistName(value) {
    var name = normalizeLocalArtistName(value).replace(/\./g, "");
    return (
        name === "various artists" ||
        name === "various artist" ||
        name === "va" ||
        name === "compilation" ||
        name === "soundtrack"
    );
}

function localTrackArtistText(track) {
    return String((track && track.artist) || "").trim();
}

function shouldShowLocalTrackArtists(albumArtist, tracks) {
    if (!Array.isArray(tracks) || tracks.length === 0) { return false; }
    var albumName = normalizeLocalArtistName(albumArtist);
    if (isCompilationArtistName(albumArtist)) { return true; }

    var seen = {};
    var distinct = 0;
    var differing = 0;
    var populated = 0;
    tracks.forEach(function(track) {
        var artist = localTrackArtistText(track);
        var normalized = normalizeLocalArtistName(artist);
        if (!normalized || normalized === "unknown artist" || normalized === "unknown") { return; }
        populated += 1;
        if (!seen[normalized]) {
            seen[normalized] = true;
            distinct += 1;
        }
        if (albumName && normalized !== albumName) { differing += 1; }
    });
    if (distinct >= 2) { return true; }
    return populated > 0 && differing / populated >= 0.25;
}

function renderLocalAlbumTrackList(tracks, albumArtist) {
    trackList.innerHTML = "";
    trackList.classList.remove("trackListWide");
    renderAlbumQueueBtn([], "");

    if (!tracks || tracks.length === 0) {
        var msg = document.createElement("div");
        msg.className = "unavailableMsg";
        msg.textContent = "No local tracks found.";
        trackList.appendChild(msg);
        return;
    }

    renderLocalAlbumPlayBtn(tracks);
    var showArtists = shouldShowLocalTrackArtists(albumArtist, tracks);
    if (showArtists) { trackList.classList.add("trackListWide"); }

    tracks.forEach(function(track, idx) {
        var tid = String(track.id || "");
        var trackArtist = localTrackArtistText(track);
        trackMap[tid] = {
            title: track.title || "",
            artist: trackArtist || (currentContext ? currentContext.artist || "" : ""),
            cover: currentContext ? currentContext.cover || "" : "",
            duration: track.duration || 0,
            contextTitle: currentContext ? currentContext.title || "Local Library" : "Local Library"
        };

        var row = document.createElement("div");
        row.className = "track localAlbumTrack" + (showArtists ? " localAlbumTrackWide" : "");
        row.setAttribute("data-track-id", tid);
        var fallbackArtist = (!isCompilationArtistName(albumArtist) && albumArtist) ? albumArtist : "";
        row.innerHTML =
            '<div class="track-num">' + (idx + 1) + '</div>' +
            '<div class="track-title">' + escapeHtml(track.title || "") + '</div>' +
            (showArtists ? '<div class="track-artist">' + escapeHtml(trackArtist || fallbackArtist || "") + '</div>' : '') +
            '<div class="track-duration">' + formatTime(track.duration || 0) + '</div>';
        var addBtn = document.createElement("button");
        addBtn.className = "trackAddBtn";
        addBtn.innerHTML = '<span class="material-icons">add</span>';
        addBtn.title = "Add to queue";
        (function(t, btn) {
            btn.onclick = function(e) {
                var ctxCover = currentContext ? (currentContext.cover || "") : "";
                showLocalAlbumTrackMenu(btn, t, idx, ctxCover, e);
            };
        }(track, addBtn));
        row.appendChild(addBtn);
        row.onclick = function() {
            if (isLocalLibraryMaintenance()) {
                showQueueActionToast("Local Music is rebuilding", true);
                return;
            }
            playLocalLibraryTrack(track, idx);
        };
        trackList.appendChild(row);
    });
    highlightCurrentTrack();
}

function showLocalAlbumTrackMenu(anchorEl, track, indexInContext, ctxCover, e) {
    if (e) { e.stopPropagation(); }
    if (!track || !track.id) { return; }
    if (isLocalLibraryMaintenance()) {
        showQueueActionToast("Local Music is rebuilding", true);
        return;
    }

    var payload = [buildLocalTrackPayload(track, ctxCover)];
    closeActivePopover();

    var popover = document.createElement("div");
    popover.className = "queuePopover";

    function addMenuButton(icon, label, onClick) {
        var btn = document.createElement("button");
        btn.className = "queuePopoverBtn";
        btn.innerHTML = '<span class="material-icons">' + icon + '</span> ' + label;
        btn.onclick = function(ev) {
            ev.stopPropagation();
            closeActivePopover();
            onClick();
        };
        popover.appendChild(btn);
    }

    addMenuButton("play_arrow", "Play Now", function() {
        playLocalLibraryTrack(track, indexInContext);
    });
    addMenuButton("queue_play_next", "Play Next", function() {
        submitQueueTracks(payload, "next");
    });
    addMenuButton("add_to_queue", "Add to Queue", function() {
        submitQueueTracks(payload, "queue");
    });

    positionQueuePopover(anchorEl, popover);
}

function renderLocalAlbumPlayBtn(tracks) {
    if (!tracks || tracks.length === 0) { return; }
    var albumHeader = document.getElementById("albumHeader");
    if (!albumHeader) { return; }
    var ctxCover = currentContext ? (currentContext.cover || "") : "";

    var group = document.createElement("div");
    group.id = "albumQueueBtnGroup";
    group.className = "albumQueueBtnGroup";

    var playBtn = document.createElement("button");
    playBtn.className = "albumQueueBtn";
    playBtn.innerHTML = '<span class="material-icons">play_arrow</span>';
    playBtn.title = "Play Album";
    playBtn.setAttribute("aria-label", "Play Album");
    playBtn.onclick = function(e) {
        e.stopPropagation();
        if (isLocalLibraryMaintenance()) {
            showQueueActionToast("Local Music is rebuilding", true);
            return;
        }
        playLocalLibraryTrack(tracks[0], 0);
    };
    group.appendChild(playBtn);

    var addBtn = document.createElement("button");
    addBtn.className = "albumQueueBtn";
    addBtn.innerHTML = '<span class="material-icons">playlist_add</span>';
    addBtn.title = "Add album to queue";
    addBtn.setAttribute("aria-label", "Add album to queue");
    addBtn.onclick = function(e) {
        e.stopPropagation();
        if (isLocalLibraryMaintenance()) {
            showQueueActionToast("Local Music is rebuilding", true);
            return;
        }
        var payload = tracks.map(function(t) { return buildLocalTrackPayload(t, ctxCover); });
        showQueuePopover(addBtn, payload, e);
    };
    group.appendChild(addBtn);

    albumHeader.appendChild(group);
}

function loadLocalArtist(artist, artistCover, artistAlbumArtwork) {
    setLocalMusicSortControlsVisible(false);
    if (isLocalLibraryMaintenance()) {
        renderLocalMusicMaintenanceLockout();
        return;
    }
    setLocalMusicArtistDetailBackMode();
    setLocalMusicStatus("Loading artist...");
    fetch("/api/local/library/artist?artist=" + encodeURIComponent(artist) + "&limit=50")
        .then(function(r) { return r.json(); })
        .then(function(data) {
            setLocalMusicStatus("");
            var artistName = data.artist || artist;
            var albumArtwork = artistAlbumArtwork || {};
            var artistAlbums = (data.albums || []).map(function(album) {
                var enrichedAlbum = Object.assign({}, album || {});
                var albumTitle = enrichedAlbum.album || enrichedAlbum.name || "";
                var albumKey = String(albumTitle).trim().toLowerCase();
                var artwork = enrichedAlbum.cover ||
                    enrichedAlbum.cover_url ||
                    enrichedAlbum.artwork_url ||
                    enrichedAlbum.image_url ||
                    enrichedAlbum.album_art ||
                    enrichedAlbum.album_art_url ||
                    albumArtwork[albumKey] || "";

                enrichedAlbum.album = albumTitle;
                enrichedAlbum.artist = enrichedAlbum.artist || artistName;
                enrichedAlbum.album_artist =
                    enrichedAlbum.album_artist || artistName;

                if (artwork) {
                    enrichedAlbum.cover = artwork;
                    enrichedAlbum.artwork_url = artwork;
                }
                return enrichedAlbum;
            });
            var artistTracks = (data.tracks || []).map(function(track) {
                var enrichedTrack = Object.assign({}, track || {});
                var albumKey = String(enrichedTrack.album || "")
                    .trim().toLowerCase();
                var artwork = enrichedTrack.cover ||
                    enrichedTrack.cover_url ||
                    enrichedTrack.artwork_url ||
                    enrichedTrack.image_url ||
                    enrichedTrack.album_art ||
                    enrichedTrack.album_art_url ||
                    albumArtwork[albumKey] || "";
                if (artwork) {
                    enrichedTrack.cover = artwork;
                    enrichedTrack.artwork_url = artwork;
                }
                return enrichedTrack;
            });
            var results = document.getElementById("localMusicResults");
            var browse = document.getElementById("localMusicBrowse");
            if (browse) { browse.innerHTML = ""; }
            if (results) {
                results.innerHTML = "";
                results.appendChild(localDetailHeader(
                    "artist",
                    artistName,
                    (data.album_count || artistAlbums.length || 0) + " albums",
                    artistCover || ""
                ));
                if (artistAlbums.length) {
                    results.appendChild(localMusicSection(
                        "Albums",
                        artistAlbums,
                        renderLocalAlbumRow,
                        true
                    ));
                }
                if (artistTracks.length) {
                    results.appendChild(localMusicSection(
                        "Tracks",
                        artistTracks,
                        renderLocalSongRow
                    ));
                }
            }
        })
        .catch(function() { setLocalMusicStatus("Artist failed to load."); });
}

function playLocalLibraryTrack(track, indexInContext) {
    if (isLocalLibraryMaintenance()) {
        showQueueActionToast("Local Music is rebuilding", true);
        return;
    }
    currentPlayingIsLocalCue = !!(
        Number((track && track.is_cue_track) || 0) ||
        (track && (track.cue_path || track.cue_audio_path ||
                   track.cue_start_seconds !== undefined ||
                   track.cue_end_seconds !== undefined))
    );
    if (!track || !track.id) { return; }
    clearRadioIdleStandbyTimer();
    var body = {id: track.id};
    var inLocalAlbum = currentViewEndpoint === "/local/album" &&
        Array.isArray(currentViewTracks) &&
        currentViewTracks.length > 0 &&
        typeof indexInContext === "number";
    if (inLocalAlbum) {
        body.context_type = "local_album";
        body.context_id = currentContext ? String(currentContext.id || "") : "";
        body.context_title = currentContext ? (currentContext.title || "Local Library") : "Local Library";
        body.track_ids = currentViewTracks.map(function(t) { return String(t.id || ""); }).filter(Boolean);
        body.start_index = indexInContext;
    }
    fetch("/api/local/library/play", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
    }).then(function(r) { return r.json(); })
      .then(function(data) {
          if (!data || data.ok === false) {
              setLocalMusicStatus(playbackErrorMessage(data, "Local playback failed."));
              showQueueActionToast(playbackErrorMessage(data, "Local playback failed."), true);
              return;
          }
          _setPlaybackSource(data.context_type || "local", data.context_id || data.id || track.id, data.context_title || "Local Library");
          currentPlayingId = String(data.id || track.id);
          currentDuration = track.duration || data.duration || 0;
          startTime = Date.now() / 1000;
          playing = true;
          setPlayerHasActiveMedia(true);
          setPlayerBarActivePlaybackSource("local");
          progressFill._elapsed = 0;
          totalTimeEl.textContent = formatTime(currentDuration || 0);
          var localCover = data.artwork_url || track.artwork_url || track.cover ||
              (currentContext && currentContext.cover ? currentContext.cover : "");
          playerArt.src = localCover || localAlbumArtDataUri(track.album || data.album || "Local Library", data.artist || track.artist || "");
          playerTrack.textContent = data.title || track.title || "";
          playerArtist.textContent = data.artist || track.artist || "";
          _updatePlayerBarLinks({
              source: "local",
              current_track_id: currentPlayingId,
              artist: data.artist || track.artist || "",
              album: data.album || track.album || "",
              cover: playerArt.src || ""
          });
          syncPlayerTrayTrackInfo({
              source: "local",
              title: data.title || track.title || "",
              artist: data.artist || track.artist || "",
              album: data.album || track.album || ""
          });
          playerBar.classList.remove("hidden");
          updatePlayPauseIcon();
          updateHomeHeroNowPlaying({
              playing: true,
              current_track_valid: true,
              playback_state: "playing",
              source: "local",
              title: data.title || track.title || "",
              artist: data.artist || track.artist || "",
              cover: localCover || ""
          });
          trackMap[currentPlayingId] = {
              title: data.title || track.title || "",
              artist: data.artist || track.artist || "",
              album: data.album || track.album || "",
              cover: playerArt.src || "",
              duration: currentDuration || 0,
              contextTitle: data.context_title || "Local Library"
          };
          highlightCurrentTrack();
      })
      .catch(function() { setLocalMusicStatus("Local playback failed."); });
}

function buildLocalTrackPayload(track, ctxCover) {
    return {
        source: "local",
        id: String(track.id || ""),
        title: track.title || "",
        artist: track.artist || (currentContext ? currentContext.artist || "" : ""),
        album: track.album || (currentContext ? currentContext.title || "" : ""),
        cover: ctxCover || track.artwork_url || track.cover || "",
        artwork_url: ctxCover || track.artwork_url || track.cover || "",
        duration: track.duration || 0,
        quality: track.quality || "LOCAL"
    };
}

function sourceLabelForTrack(track) {
    var source = String((track && track.source) || "").toLowerCase();
    var id = track && track.id != null ? String(track.id) : "";
    if (source === "local" || id.indexOf("local:") === 0) { return "LOCAL"; }
    if (source === "radio") { return "RADIO"; }
    return "TIDAL";
}

// Poll a single endpoint until it returns data, then replace slotEl in-place.
// Max ~18s total (12 attempts x 1.5s). Cancels cleanly when loadHome() reruns.
function _pollHomeSlot(endpoint, slotEl, title, onData, onCardClick, onTitleClick, opts) {
    var MAX_ATTEMPTS = 12;
    var INTERVAL_MS  = 1500;
    var attempts     = 0;

    function _attempt() {
        fetchWithTimeout(endpoint, {}, 5000)
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (Array.isArray(d) && d.length > 0) {
                    onData(d);
                    // Build the section block
                    var block = buildScrollSection(title, d, onCardClick, opts || {});
                    var h = block.querySelector("h2");
                    if (h && onTitleClick) {
                        h.style.cursor = "pointer";
                        h.title = "See all";
                        h.onclick = onTitleClick;
                    }
                    // Swap slot for real content -- only if still in DOM
                    if (slotEl.parentNode) {
                        slotEl.parentNode.replaceChild(block, slotEl);
                    }
                } else if (attempts < MAX_ATTEMPTS) {
                    attempts++;
                    var t = setTimeout(_attempt, INTERVAL_MS);
                    _homeSlotTimers.push(t);
                }
            })
            .catch(function() {
                if (attempts < MAX_ATTEMPTS) {
                    attempts++;
                    var t = setTimeout(_attempt, INTERVAL_MS);
                    _homeSlotTimers.push(t);
                }
            });
    }
    _attempt();
}

// Open a featured track section (Top Tracks, Top Hits, New Tracks) as a
// full playable track list in albumView -- identical UX to an album or playlist.
function showFeaturedTrackList(title, items) {
    // Convert home card format {name, sub_title, image_url, id, type, duration}
    // into the track row format {id, title, artist, cover, duration, quality}
    var tracks = [];
    for (var i = 0; i < items.length; i++) {
        var it = items[i];
        if ((it.type || "").toLowerCase() !== "track" || !it.id) { continue; }
        tracks.push({
            id:       it.id,
            title:    it.name      || "",
            artist:   it.sub_title || "",
            cover:    it.image_url || "",
            duration: it.duration  || 0,
            quality:  ""
        });
    }
    if (tracks.length === 0) { return; }

    previousView        = "home";
    currentViewEndpoint = "";
    currentContext      = { id: "", cover: "", title: title, artist: "" };
    _setPlaybackSource("home", "", title);

    // Populate trackMap so player bar updates instantly on tap
    for (var j = 0; j < tracks.length; j++) {
        var t = tracks[j];
        trackMap[String(t.id)] = {
            title: t.title, artist: t.artist,
            cover: t.cover, duration: t.duration
        };
    }

    // Use first non-empty cover as the header artwork
    var headerCover = "";
    for (var k = 0; k < tracks.length; k++) {
        if (tracks[k].cover) { headerCover = tracks[k].cover; break; }
    }

    setAlbumViewKind("tidal-featured-tracks");
    showView("album");
    albumArt.src            = headerCover;
    albumTitle.textContent  = title;
    albumArtist.textContent = "";
    albumArtist.style.cursor = "";
    albumArtist.onclick      = null;
    albumTechInfo.classList.add("hidden");

    originalTracks    = tracks;
    shuffledTracks    = [];
    currentViewTracks = tracks;

    renderTrackList(tracks);
    resetAlbumDetailScroll();
}


// Poll /tidal/featured (returns array of {title, items} sections).
// Replaces featuredSlot with all sections at once when data arrives.
function _pollFeaturedSlot(slotEl) {
    var MAX_ATTEMPTS = 20;   // up to 30s -- top+new pages can be slow on first load
    var INTERVAL_MS  = 1500;
    var attempts     = 0;

    function _attempt() {
        fetchWithTimeout("/tidal/featured", {}, 5000)
            .then(function(r) { return r.json(); })
            .then(function(sections) {
                if (Array.isArray(sections) && sections.length > 0) {
                    var wrapper = document.createElement("div");
                    sections.forEach(function(sec) {
                        if (!sec.items || sec.items.length === 0) { return; }
                        var isTrackSection = sec.items.some(function(it) {
                            return (it.type || "").toLowerCase() === "track";
                        });
                        var block = buildScrollSection(
                            sec.title,
                            sec.items,
                            function(item, e, anchorEl) { handleTidalWallItemClick(item, "home", e, anchorEl); },
                            { kind: "curated" }
                        );
                        if (isTrackSection) {
                            var h = block.querySelector("h2");
                            if (h) {
                                h.style.cursor = "pointer";
                                h.title = "See all";
                                (function(title, items) {
                                    h.onclick = function() { showFeaturedTrackList(title, items); };
                                }(sec.title, sec.items));
                            }
                        }
                        wrapper.appendChild(block);
                    });
                    if (slotEl.parentNode) {
                        slotEl.parentNode.replaceChild(wrapper, slotEl);
                    }
                } else if (attempts < MAX_ATTEMPTS) {
                    attempts++;
                    var t = setTimeout(_attempt, INTERVAL_MS);
                    _homeSlotTimers.push(t);
                }
            })
            .catch(function() {
                if (attempts < MAX_ATTEMPTS) {
                    attempts++;
                    var t = setTimeout(_attempt, INTERVAL_MS);
                    _homeSlotTimers.push(t);
                }
            });
    }
    _attempt();
}


// --- Shared application-header sticky offset ---

function syncSrovaAppHeaderOffset() {
    var header = document.querySelector("body > header");
    if (!header) { return; }

    var rect = header.getBoundingClientRect();
    var offset = Math.max(0, Math.ceil(rect.bottom));

    document.documentElement.style.setProperty(
        "--srova-app-header-offset",
        offset + "px"
    );
}

(function initSrovaAppHeaderOffset() {
    var header = document.querySelector("body > header");
    if (!header) { return; }

    var pending = false;
    var raf = window.requestAnimationFrame ||
        function(callback) {
            return window.setTimeout(callback, 0);
        };

    function scheduleSrovaAppHeaderOffsetSync() {
        if (pending) { return; }

        pending = true;

        raf(function() {
            pending = false;
            syncSrovaAppHeaderOffset();
        });
    }

    scheduleSrovaAppHeaderOffsetSync();

    window.addEventListener(
        "load",
        scheduleSrovaAppHeaderOffsetSync
    );

    window.addEventListener(
        "resize",
        scheduleSrovaAppHeaderOffsetSync
    );

    window.addEventListener(
        "orientationchange",
        scheduleSrovaAppHeaderOffsetSync
    );

    window.addEventListener(
        "pageshow",
        scheduleSrovaAppHeaderOffsetSync
    );

    if (window.ResizeObserver) {
        var observer = new window.ResizeObserver(
            scheduleSrovaAppHeaderOffsetSync
        );

        observer.observe(header);
        window._srovaAppHeaderResizeObserver = observer;
    }

    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(
            scheduleSrovaAppHeaderOffsetSync,
            function() {}
        );
    }
}());


// --- My Albums / My Songs shared full-page toolbar ---

function renderLibraryViewToggle(mountId) {
    var mount = document.getElementById(mountId);
    if (!mount) { return; }

    mount.innerHTML = "";
    appendArtworkViewToggle(mount);
}


// --- My Albums full page ---

function showMyAlbums() {
    if (!requireOnlineSource()) { return; }
    showView("myalbums");
    var grid = document.getElementById("myAlbumsGrid");
    if (!grid) { return; }

    renderLibraryViewToggle("myAlbumsViewToggleMount");

    // Use cached data if available, else fetch
    var cached = window._myAlbumsData || [];
    if (cached.length > 0) {
        renderLibraryGrid(grid, cached, function(item) { handleItemClick(item, "myalbums"); });
        return;
    }
    grid.innerHTML = '<div class="libraryLoading">Loading...</div>';
    fetchWithTimeout("/tidal/myalbums", {}, 5000)
        .then(function(r) { return r.json(); })
        .then(function(d) {
            window._myAlbumsData = Array.isArray(d) ? d : [];
            renderLibraryGrid(grid, window._myAlbumsData, function(item) { handleItemClick(item, "myalbums"); });
        })
        .catch(function() {
            refreshOnlineSourceState();
            grid.innerHTML = '<div class="libraryLoading">Could not load albums.</div>';
        });
}

// --- My Songs full page ---

function showMySongs() {
    if (!requireOnlineSource()) { return; }
    showView("mysongs");
    var grid = document.getElementById("mySongsGrid");
    if (!grid) { return; }

    renderLibraryViewToggle("mySongsViewToggleMount");

    var cached = window._mySongsData || [];
    if (cached.length > 0) {
        renderSongsList(grid, cached);
        return;
    }
    grid.innerHTML = '<div class="libraryLoading">Loading...</div>';
    fetchWithTimeout("/tidal/mysongs", {}, 5000)
        .then(function(r) { return r.json(); })
        .then(function(d) {
            window._mySongsData = Array.isArray(d) ? d : [];
            renderSongsList(grid, window._mySongsData);
        })
        .catch(function() {
            refreshOnlineSourceState();
            grid.innerHTML = '<div class="libraryLoading">Could not load songs.</div>';
        });
}

function renderLibraryGrid(container, items, onCardClick) {
    container.innerHTML = "";
    if (!items || items.length === 0) {
        container.innerHTML = '<div class="libraryLoading">Nothing here yet.</div>';
        return;
    }
    var grid = document.createElement("div");
    grid.className = "libraryGrid tidalArtworkGrid";
    applyArtworkViewModeClass(grid);
    items.forEach(function(item) {
        var card = document.createElement("div");
        card.className = "libraryCard";
        card.innerHTML =
            '<img src="' + (item.image_url || "") + '" class="libraryCardImg">' +
            '<div class="libraryCardTitle">' + (item.name      || "") + '</div>' +
            '<div class="libraryCardSub">'   + (item.sub_title || "") + '</div>';
        if (item.id) {
            (function(it) { card.onclick = function() { onCardClick(it); }; }(item));
        }
        grid.appendChild(card);
    });
    container.appendChild(grid);
}

function renderSongsList(container, items) {
    container.innerHTML = "";
    if (!items || items.length === 0) {
        container.innerHTML = '<div class="libraryLoading">Nothing here yet.</div>';
        return;
    }
    var list = document.createElement("div");
    list.className = "librarySongList tidalSongList";
    applyArtworkViewModeClass(list);
    items.forEach(function(item, idx) {
        var row = document.createElement("div");
        row.className = "librarySongRow";
        row.innerHTML =
            '<img src="' + (item.image_url || "") + '" class="librarySongThumb">' +
            '<div class="librarySongMeta">' +
                '<div class="librarySongTitle">' + (item.name      || "") + '</div>' +
                '<div class="librarySongSub">'   + (item.sub_title || "") + '</div>' +
            '</div>' +
            '<div class="librarySongDur">' + formatTime(item.duration || 0) + '</div>';
        (function(it) {
            row.onclick = function() { handleItemClick(it, "mysongs"); };
        }(item));
        list.appendChild(row);
    });
    container.appendChild(list);
}


// --- My Playlists ---

function normalizeTidalTrackIds(items) {
    var ids = [];
    if (!Array.isArray(items)) { return ids; }
    items.forEach(function(item) {
        if (item == null) { return; }
        var source = "";
        var id = "";
        if (typeof item === "string" || typeof item === "number") {
            id = String(item).trim();
        } else {
            source = String(item.source || "").toLowerCase();
            id = String(item.track_id || item.id || "").trim();
        }
        if (!id || id.indexOf("local:") === 0 || source === "local") { return; }
        ids.push(id);
    });
    return ids;
}

function postJson(url, body) {
    return fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {})
    }).then(function(res) {
        return res.json().then(function(data) {
            if (!res.ok) {
                throw new Error((data && data.error) ? data.error : "Request failed");
            }
            return data || {};
        });
    });
}

function postCreateTidalPlaylist(name, description) {
    return postJson("/tidal/playlist/create", {
        name: String(name || "").trim(),
        description: String(description || "")
    });
}

function postCreateTidalPlaylistFromTracks(name, trackIds) {
    return postJson("/tidal/playlist/create_from_tracks", {
        name: String(name || "").trim(),
        track_ids: normalizeTidalTrackIds(trackIds)
    });
}

function postCreateTidalPlaylistFromQueue(name) {
    return postJson("/tidal/playlist/create_from_queue", {
        name: String(name || "").trim()
    });
}

function postAddTracksToTidalPlaylist(playlistId, trackIds) {
    return postJson("/tidal/playlist/add_tracks", {
        playlist_id: String(playlistId || "").trim(),
        track_ids: normalizeTidalTrackIds(trackIds)
    });
}

function postRemoveTracksFromTidalPlaylist(playlistId, trackIds) {
    return postJson("/tidal/playlist/remove_tracks", {
        playlist_id: String(playlistId || "").trim(),
        track_ids: normalizeTidalTrackIds(trackIds)
    });
}

function postDeleteTidalPlaylist(playlistId) {
    return postJson("/tidal/playlist/delete", {
        playlist_id: String(playlistId || "").trim()
    });
}

function postRenameTidalPlaylist(playlistId, name) {
    return postJson("/tidal/playlist/rename", {
        playlist_id: String(playlistId || "").trim(),
        name: String(name || "").trim()
    });
}

function invalidateTidalPlaylistUiCache() {
    playlistsLoaded = false;
    allPlaylists = [];
    window._myAlbumsData = window._myAlbumsData || [];
}

function refreshMyPlaylistsIfVisible() {
    if (playlistsView && playlistsView.style.display !== "none") {
        loadMyPlaylists(0);
    }
}

function closeTidalPlaylistModal(modal) {
    if (modal && modal.parentNode) {
        modal.parentNode.removeChild(modal);
    }
}

function updateTidalPlaylistNameInUi(playlistId, name) {
    playlistId = String(playlistId || "").trim();
    name = String(name || "").trim();
    if (!playlistId || !name) { return; }

    allPlaylists.forEach(function(item) {
        if (String((item || {}).id || "") === playlistId) {
            item.name = name;
        }
    });

    document.querySelectorAll(".playlistRow[data-playlist-id]").forEach(function(row) {
        if (String(row.getAttribute("data-playlist-id") || "") !== playlistId) {
            return;
        }
        var rowName = row.querySelector(".playlistName");
        if (rowName) { rowName.textContent = name; }
    });

    if (
        currentContext &&
        String(currentContext.id || "") === playlistId &&
        currentViewEndpoint.indexOf("/tidal/playlist/") === 0
    ) {
        currentContext.title = name;
        albumTitle.textContent = name;
    }
}

function showCreateTidalPlaylistModal(options) {
    options = options || {};
    if (options.mode === "rename" && options.editable !== true) {
        showQueueActionToast(
            "This TIDAL playlist cannot be renamed",
            true
        );
        return;
    }
    var existing = document.getElementById("tidalPlaylistModal");
    if (existing) { closeTidalPlaylistModal(existing); }

    var modal = document.createElement("div");
    modal.id = "tidalPlaylistModal";
    modal.className = "tidalPlaylistModal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    var card = document.createElement("div");
    card.className = "tidalPlaylistCard";

    var title = document.createElement("div");
    title.className = "tidalPlaylistTitle";
    title.textContent = options.title || "Create Playlist";

    var body = document.createElement("div");
    body.className = "tidalPlaylistBody";

    var nameInput = document.createElement("input");
    nameInput.className = "tidalPlaylistInput";
    nameInput.type = "text";
    nameInput.placeholder = "Playlist name";
    nameInput.value = options.defaultName || "";

    var descInput = document.createElement("textarea");
    descInput.className = "tidalPlaylistInput tidalPlaylistTextarea";
    descInput.placeholder = "Description";
    descInput.value = options.defaultDescription || "";
    if (options.hideDescription) { descInput.classList.add("hidden"); }

    var status = document.createElement("div");
    status.className = "tidalPlaylistStatus";

    var actions = document.createElement("div");
    actions.className = "tidalPlaylistActions";

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "settingsBtn";
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";

    var createBtn = document.createElement("button");
    createBtn.className = "settingsBtn settingsBtnPrimary";
    createBtn.type = "button";
    createBtn.textContent = options.submitLabel || "Create";

    function setBusy(busy) {
        createBtn.disabled = busy;
        cancelBtn.disabled = busy;
        nameInput.disabled = busy;
        descInput.disabled = busy;
        createBtn.textContent = busy
            ? (options.busyLabel || "Creating...")
            : (options.submitLabel || "Create");
    }

    function submit() {
        var name = nameInput.value.trim();
        var desc = descInput.value.trim();
        if (!name) {
            status.textContent = "Enter a playlist name.";
            status.className = "tidalPlaylistStatus error";
            nameInput.focus();
            return;
        }

        setBusy(true);
        status.textContent = "";
        status.className = "tidalPlaylistStatus";

        var mode = options.mode || "empty";
        var request;
        if (mode === "rename") {
            request = postRenameTidalPlaylist(options.playlistId, name);
        } else if (mode === "tracks") {
            request = postCreateTidalPlaylistFromTracks(name, options.trackIds || []);
        } else if (mode === "queue") {
            request = postCreateTidalPlaylistFromQueue(name);
        } else {
            request = postCreateTidalPlaylist(name, desc);
        }

        request.then(function(data) {
            if (data && data.ok === false) {
                throw new Error(
                    data.error ||
                    (mode === "rename"
                        ? "Could not rename playlist"
                        : "Could not create playlist")
                );
            }
            if (mode === "rename") {
                var renamedName = String(data.name || name).trim() || name;
                updateTidalPlaylistNameInUi(
                    options.playlistId,
                    renamedName
                );
                closeTidalPlaylistModal(modal);
                showQueueActionToast("Playlist renamed", false);
                if (typeof options.onSuccess === "function") {
                    options.onSuccess(data || {});
                }
                return;
            }
            invalidateTidalPlaylistUiCache();
            closeTidalPlaylistModal(modal);
            refreshMyPlaylistsIfVisible();
            showQueueActionToast("Playlist created", false);
            if (typeof options.onSuccess === "function") { options.onSuccess(data || {}); }
        }).catch(function(err) {
            setBusy(false);
            status.textContent = err && err.message ? err.message : "Could not create playlist.";
            status.className = "tidalPlaylistStatus error";
        });
    }

    cancelBtn.onclick = function() { closeTidalPlaylistModal(modal); };
    createBtn.onclick = submit;
    nameInput.onkeydown = function(e) {
        if (e.key === "Enter") { submit(); }
    };
    modal.addEventListener("click", function(e) {
        if (e.target === modal) { closeTidalPlaylistModal(modal); }
    });

    body.appendChild(nameInput);
    if (!options.hideDescription) { body.appendChild(descInput); }
    body.appendChild(status);
    actions.appendChild(cancelBtn);
    actions.appendChild(createBtn);
    card.appendChild(title);
    card.appendChild(body);
    card.appendChild(actions);
    modal.appendChild(card);
    document.body.appendChild(modal);
    setTimeout(function() { nameInput.focus(); }, 0);
}

function fetchTidalPlaylistsForPicker(retryCount) {
    retryCount = retryCount || 0;
    return fetch("/tidal/myplaylists")
        .then(function(res) { return res.json(); })
        .then(function(playlists) {
            playlists = Array.isArray(playlists) ? playlists : [];
            if (playlists.length || retryCount >= 5) { return playlists; }
            return new Promise(function(resolve) {
                setTimeout(function() {
                    resolve(fetchTidalPlaylistsForPicker(retryCount + 1));
                }, 1500);
            });
        });
}

function getPlaylistPickerSortMode() {
    try {
        var mode = localStorage.getItem("srovaPlaylistPickerSort");
        return mode === "latest" ? "latest" : "az";
    } catch (e) {
        return "az";
    }
}

function setPlaylistPickerSortMode(mode) {
    mode = mode === "latest" ? "latest" : "az";
    try { localStorage.setItem("srovaPlaylistPickerSort", mode); } catch (e) {}
    return mode;
}

function getPlaylistRecencyValue(pl) {
    var raw = "";
    if (pl) {
        raw = pl.dateAdded || pl.created || pl.createdAt || pl.updatedAt ||
              pl.lastUpdated || pl.modifiedAt || pl.last_updated || pl.created_at || "";
    }
    if (!raw) { return 0; }
    var parsed = Date.parse(raw);
    return isNaN(parsed) ? 0 : parsed;
}

function sortPlaylistsForPicker(playlists, mode) {
    return playlists.slice().sort(function(a, b) {
        if (mode === "latest") {
            var at = getPlaylistRecencyValue(a);
            var bt = getPlaylistRecencyValue(b);
            if (at || bt) {
                if (at !== bt) { return bt - at; }
            }
            return (a._pickerIndex || 0) - (b._pickerIndex || 0);
        }
        var an = String((a && a.name) || "").toLowerCase();
        var bn = String((b && b.name) || "").toLowerCase();
        if (an < bn) { return -1; }
        if (an > bn) { return 1; }
        return (a._pickerIndex || 0) - (b._pickerIndex || 0);
    });
}

function showAddToTidalPlaylistModal(trackIds, options) {
    options = options || {};
    trackIds = normalizeTidalTrackIds(trackIds);
    if (!trackIds.length) {
        showQueueActionToast("No valid TIDAL track id", true);
        return;
    }

    var existing = document.getElementById("tidalPlaylistModal");
    if (existing) { closeTidalPlaylistModal(existing); }

    var modal = document.createElement("div");
    modal.id = "tidalPlaylistModal";
    modal.className = "tidalPlaylistModal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    var card = document.createElement("div");
    card.className = "tidalPlaylistCard tidalPlaylistPickerCard";

    var title = document.createElement("div");
    title.className = "tidalPlaylistTitle";
    title.textContent = options.title || "Add to Playlist";

    var status = document.createElement("div");
    status.className = "tidalPlaylistStatus";
    status.textContent = "Loading playlists...";

    var controls = document.createElement("div");
    controls.className = "tidalPlaylistPickerControls";

    var searchInput = document.createElement("input");
    searchInput.className = "tidalPlaylistInput tidalPlaylistPickerSearch";
    searchInput.type = "search";
    searchInput.placeholder = "Search playlists";

    var sortWrap = document.createElement("div");
    sortWrap.className = "tidalPlaylistPickerSort";

    var sortAzBtn = document.createElement("button");
    sortAzBtn.className = "tidalPlaylistSortBtn";
    sortAzBtn.type = "button";
    sortAzBtn.textContent = "A-Z";

    var sortLatestBtn = document.createElement("button");
    sortLatestBtn.className = "tidalPlaylistSortBtn";
    sortLatestBtn.type = "button";
    sortLatestBtn.textContent = "Latest";

    sortWrap.appendChild(sortAzBtn);
    sortWrap.appendChild(sortLatestBtn);
    controls.appendChild(searchInput);
    controls.appendChild(sortWrap);

    var list = document.createElement("div");
    list.className = "tidalPlaylistPickerList";

    var createWrap = document.createElement("div");
    createWrap.className = "tidalPlaylistCreateInline";

    var nameInput = document.createElement("input");
    nameInput.className = "tidalPlaylistInput";
    nameInput.type = "text";
    nameInput.placeholder = "New playlist name";

    var createBtn = document.createElement("button");
    createBtn.className = "settingsBtn";
    createBtn.type = "button";
    createBtn.textContent = "Create and Add";

    createWrap.appendChild(nameInput);
    createWrap.appendChild(createBtn);

    var actions = document.createElement("div");
    actions.className = "tidalPlaylistActions";
    var cancelBtn = document.createElement("button");
    cancelBtn.className = "settingsBtn";
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";
    actions.appendChild(cancelBtn);

    function setStatus(text, isError) {
        status.textContent = text || "";
        status.className = "tidalPlaylistStatus" + (isError ? " error" : "");
    }

    function setBusy(busy) {
        var buttons = card.querySelectorAll("button");
        for (var i = 0; i < buttons.length; i++) { buttons[i].disabled = busy; }
        nameInput.disabled = busy;
    }

    function addToPlaylist(playlistId, playlistName) {
        setBusy(true);
        setStatus("Adding tracks...", false);
        postAddTracksToTidalPlaylist(playlistId, trackIds)
            .then(function(data) {
                if (data && data.ok === false) {
                    throw new Error(data.error || "Could not add to playlist");
                }
                invalidateTidalPlaylistUiCache();
                closeTidalPlaylistModal(modal);
                var added = data && data.items_added != null ? Number(data.items_added) : trackIds.length;
                showQueueActionToast("Added " + added + " to " + (playlistName || "playlist"), false);
                if (typeof options.onSuccess === "function") { options.onSuccess(data || {}); }
            })
            .catch(function(err) {
                setBusy(false);
                setStatus(err && err.message ? err.message : "Could not add to playlist.", true);
            });
    }

    var pickerPlaylists = [];
    var pickerSortMode = getPlaylistPickerSortMode();

    function updateSortButtons() {
        sortAzBtn.className = "tidalPlaylistSortBtn" + (pickerSortMode === "az" ? " active" : "");
        sortLatestBtn.className = "tidalPlaylistSortBtn" + (pickerSortMode === "latest" ? " active" : "");
    }

    function renderPlaylists() {
        list.innerHTML = "";
        if (!pickerPlaylists.length) {
            setStatus("No playlists found. Create a new playlist below.", false);
            return;
        }
        var q = searchInput.value.trim().toLowerCase();
        var filtered = pickerPlaylists.filter(function(pl) {
            return !q || String((pl && pl.name) || "").toLowerCase().indexOf(q) !== -1;
        });
        if (!filtered.length) {
            setStatus("No matching playlists.", false);
            return;
        }
        setStatus("", false);
        sortPlaylistsForPicker(filtered, pickerSortMode).forEach(function(pl) {
            var row = document.createElement("button");
            row.type = "button";
            row.className = "tidalPlaylistPickerRow";
            row.innerHTML =
                '<span class="material-icons">playlist_play</span>' +
                '<span class="tidalPlaylistPickerMeta">' +
                  '<span class="tidalPlaylistPickerName">' + escapeHtml(pl.name || "Untitled Playlist") + '</span>' +
                  '<span class="tidalPlaylistPickerSub">' + escapeHtml(pl.sub_title || "") + '</span>' +
                '</span>';
            row.onclick = function() { addToPlaylist(pl.id, pl.name || "playlist"); };
            list.appendChild(row);
        });
    }

    sortAzBtn.onclick = function() {
        pickerSortMode = setPlaylistPickerSortMode("az");
        updateSortButtons();
        renderPlaylists();
    };
    sortLatestBtn.onclick = function() {
        pickerSortMode = setPlaylistPickerSortMode("latest");
        updateSortButtons();
        renderPlaylists();
    };
    searchInput.oninput = renderPlaylists;

    createBtn.onclick = function() {
        var name = nameInput.value.trim();
        if (!name) {
            setStatus("Enter a playlist name.", true);
            nameInput.focus();
            return;
        }
        setBusy(true);
        setStatus("Creating playlist...", false);
        postCreateTidalPlaylist(name, "")
            .then(function(data) {
                if (data && data.ok === false) {
                    throw new Error(data.error || "Could not create playlist");
                }
                var playlistId = data.id || (data.playlist && data.playlist.id) || "";
                if (!playlistId) { throw new Error("Created playlist has no id"); }
                addToPlaylist(playlistId, data.name || name);
            })
            .catch(function(err) {
                setBusy(false);
                setStatus(err && err.message ? err.message : "Could not create playlist.", true);
            });
    };
    nameInput.onkeydown = function(e) {
        if (e.key === "Enter") { createBtn.click(); }
    };

    cancelBtn.onclick = function() { closeTidalPlaylistModal(modal); };
    modal.addEventListener("click", function(e) {
        if (e.target === modal) { closeTidalPlaylistModal(modal); }
    });

    card.appendChild(title);
    card.appendChild(status);
    card.appendChild(controls);
    card.appendChild(list);
    card.appendChild(createWrap);
    card.appendChild(actions);
    modal.appendChild(card);
    document.body.appendChild(modal);
    updateSortButtons();

    fetchTidalPlaylistsForPicker()
        .then(function(playlists) {
            pickerPlaylists = playlists.map(function(pl, index) {
                pl = pl || {};
                pl._pickerIndex = index;
                return pl;
            });
            renderPlaylists();
        })
        .catch(function(err) {
            setStatus(err && err.message ? err.message : "Could not load playlists.", true);
        });
}

function showDeleteTidalPlaylistModal(playlist) {
    playlist = playlist || {};
    var playlistId = String(playlist.id || "").trim();
    if (!playlistId) {
        showQueueActionToast("No playlist id", true);
        return;
    }

    var existing = document.getElementById("tidalPlaylistModal");
    if (existing) { closeTidalPlaylistModal(existing); }

    var modal = document.createElement("div");
    modal.id = "tidalPlaylistModal";
    modal.className = "tidalPlaylistModal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    var card = document.createElement("div");
    card.className = "tidalPlaylistCard tidalPlaylistDeleteCard";

    var title = document.createElement("div");
    title.className = "tidalPlaylistTitle";
    title.textContent = "Delete Playlist";

    var message = document.createElement("div");
    message.className = "tidalPlaylistDeleteMessage";
    message.textContent = "This deletes \"" + (playlist.name || "this playlist") + "\" from your TIDAL account.";

    var status = document.createElement("div");
    status.className = "tidalPlaylistStatus";

    var actions = document.createElement("div");
    actions.className = "tidalPlaylistActions";

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "settingsBtn";
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";

    var deleteBtn = document.createElement("button");
    deleteBtn.className = "settingsBtn tidalPlaylistDangerBtn";
    deleteBtn.type = "button";
    deleteBtn.textContent = "DELETE PLAYLIST";

    function setBusy(busy) {
        cancelBtn.disabled = busy;
        deleteBtn.disabled = busy;
        deleteBtn.textContent = busy ? "Deleting..." : "DELETE PLAYLIST";
    }

    deleteBtn.onclick = function() {
        setBusy(true);
        status.textContent = "Deleting playlist...";
        status.className = "tidalPlaylistStatus";
        postDeleteTidalPlaylist(playlistId)
            .then(function(data) {
                if (data && data.ok === false) {
                    throw new Error(data.error || "Could not delete playlist");
                }
                invalidateTidalPlaylistUiCache();
                closeTidalPlaylistModal(modal);
                showQueueActionToast("Playlist deleted", false);
                refreshMyPlaylistsIfVisible();
            })
            .catch(function(err) {
                setBusy(false);
                status.textContent = err && err.message ? err.message : "Could not delete playlist.";
                status.className = "tidalPlaylistStatus error";
            });
    };

    cancelBtn.onclick = function() { closeTidalPlaylistModal(modal); };
    modal.addEventListener("click", function(e) {
        if (e.target === modal) { closeTidalPlaylistModal(modal); }
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(deleteBtn);
    card.appendChild(title);
    card.appendChild(message);
    card.appendChild(status);
    card.appendChild(actions);
    modal.appendChild(card);
    document.body.appendChild(modal);
}

function showRemoveFromTidalPlaylistModal(track, rowEl) {
    track = track || {};
    var playlistId = currentContext ? String(currentContext.id || "").trim() : "";
    var trackId = String(track.id || "").trim();
    if (!playlistId || !trackId) {
        showQueueActionToast("No playlist or track id", true);
        return;
    }

    var existing = document.getElementById("tidalPlaylistModal");
    if (existing) { closeTidalPlaylistModal(existing); }

    var modal = document.createElement("div");
    modal.id = "tidalPlaylistModal";
    modal.className = "tidalPlaylistModal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    var card = document.createElement("div");
    card.className = "tidalPlaylistCard tidalPlaylistDeleteCard";

    var title = document.createElement("div");
    title.className = "tidalPlaylistTitle";
    title.textContent = "Remove Track";

    var message = document.createElement("div");
    message.className = "tidalPlaylistDeleteMessage";
    message.textContent = "Remove \"" + (track.title || "this song") + "\" from this TIDAL playlist? This does not delete the song from TIDAL or your account.";

    var status = document.createElement("div");
    status.className = "tidalPlaylistStatus";

    var actions = document.createElement("div");
    actions.className = "tidalPlaylistActions";

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "settingsBtn";
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";

    var removeBtn = document.createElement("button");
    removeBtn.className = "settingsBtn tidalPlaylistDangerBtn";
    removeBtn.type = "button";
    removeBtn.textContent = "REMOVE FROM PLAYLIST";

    function setBusy(busy) {
        cancelBtn.disabled = busy;
        removeBtn.disabled = busy;
        removeBtn.textContent = busy ? "Removing..." : "REMOVE FROM PLAYLIST";
    }

    removeBtn.onclick = function() {
        setBusy(true);
        status.textContent = "Removing track...";
        status.className = "tidalPlaylistStatus";
        postRemoveTracksFromTidalPlaylist(playlistId, [trackId])
            .then(function(data) {
                if (data && data.ok === false) {
                    throw new Error(data.error || "Could not remove track");
                }
                closeTidalPlaylistModal(modal);
                showQueueActionToast("Removed from playlist", false);
                if (rowEl && rowEl.parentNode) {
                    rowEl.parentNode.removeChild(rowEl);
                    currentViewTracks = currentViewTracks.filter(function(t) {
                        return String(t.id || "") !== trackId;
                    });
                    originalTracks = originalTracks.filter(function(t) {
                        return String(t.id || "") !== trackId;
                    });
                } else if (currentContext && currentContext.id) {
                    loadTrackList(currentContext, "/tidal/playlist/" + currentContext.id, "playlists");
                }
            })
            .catch(function(err) {
                setBusy(false);
                status.textContent = err && err.message ? err.message : "Could not remove track.";
                status.className = "tidalPlaylistStatus error";
            });
    };

    cancelBtn.onclick = function() { closeTidalPlaylistModal(modal); };
    modal.addEventListener("click", function(e) {
        if (e.target === modal) { closeTidalPlaylistModal(modal); }
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(removeBtn);
    card.appendChild(title);
    card.appendChild(message);
    card.appendChild(status);
    card.appendChild(actions);
    modal.appendChild(card);
    document.body.appendChild(modal);
}

var allPlaylists = [];

function loadMyPlaylists(retryCount) {
    retryCount = retryCount || 0;
    playlistsContent.innerHTML = '<div class="playlistsLoading">Loading playlists...</div>';
    fetch("/tidal/myplaylists")
        .then(function(res) { return res.json(); })
        .then(function(playlists) {
            if (!playlists || playlists.length === 0) {
                if (retryCount < 12) {
                    playlistsContent.innerHTML = '<div class="playlistsLoading">Fetching from Tidal (' + (retryCount + 1) + '/12)...</div>';
                    setTimeout(function() { loadMyPlaylists(retryCount + 1); }, 15000);
                } else {
                    playlistsContent.innerHTML = '<div class="playlistsLoading">No playlists found.</div>';
                }
                return;
            }
            playlistsLoaded = true;
            allPlaylists    = playlists;
            renderPlaylistsList(playlists);
        })
        .catch(function(e) {
            console.error("loadMyPlaylists failed:", e);
            playlistsContent.innerHTML = '<div class="playlistsLoading">Could not load playlists.</div>';
        });
}

function onPlaylistFilter(e) {
    var q = e.target.value.trim().toLowerCase();
    if (!q) { renderPlaylistRows(_sortPlaylists(allPlaylists)); return; }
    var filtered = allPlaylists.filter(function(p) {
        return (p.name || "").toLowerCase().indexOf(q) !== -1;
    });
    renderPlaylistRows(_sortPlaylists(filtered));
}

var _plSortKey = "name";   // name | tracks | last_updated | created_at
var _plSortAsc = true;

function _sortPlaylists(playlists) {
    var sorted = playlists.slice();
    sorted.sort(function(a, b) {
        var av, bv;
        if (_plSortKey === "name") {
            av = (a.name || "").toLowerCase();
            bv = (b.name || "").toLowerCase();
        } else if (_plSortKey === "tracks") {
            av = a.num_tracks || 0;
            bv = b.num_tracks || 0;
        } else if (_plSortKey === "last_updated") {
            av = a.last_updated || "";
            bv = b.last_updated || "";
        } else if (_plSortKey === "created_at") {
            av = a.created_at || "";
            bv = b.created_at || "";
        } else {
            av = (a.name || "").toLowerCase();
            bv = (b.name || "").toLowerCase();
        }
        if (av < bv) { return _plSortAsc ? -1 :  1; }
        if (av > bv) { return _plSortAsc ?  1 : -1; }
        return 0;
    });
    return sorted;
}

function renderPlaylistsList(playlists) {
    playlistsContent.innerHTML = "";

    var header = document.createElement("div");
    header.className = "playlistsHeader";

    var headingGroup = document.createElement("div");
    headingGroup.className = "playlistsHeadingGroup";

    var h = document.createElement("h2");
    h.textContent = "My Playlists";

    var count = document.createElement("span");
    count.className   = "playlistsCount";
    count.textContent = playlists.length + " playlists";

    var createBtn = document.createElement("button");
    createBtn.className = "playlistsCreateBtn";
    createBtn.type = "button";
    createBtn.innerHTML = '<span class="material-icons">add</span><span>Create Playlist</span>';
    createBtn.onclick = function() {
        showCreateTidalPlaylistModal({
            title: "Create Playlist",
            submitLabel: "Create"
        });
    };

    headingGroup.appendChild(h);
    headingGroup.appendChild(count);
    header.appendChild(headingGroup);
    header.appendChild(createBtn);
    playlistsContent.appendChild(header);

    // Sort controls
    var sortBar = document.createElement("div");
    sortBar.className = "playlistsSortBar";

    var sortLabel = document.createElement("span");
    sortLabel.className   = "playlistsSortLabel";
    sortLabel.textContent = "Sort:";
    sortBar.appendChild(sortLabel);

    var sortKeys = [
        { key: "name",         label: "Name"         },
        { key: "tracks",       label: "Tracks"       },
        { key: "last_updated", label: "Last Updated" },
        { key: "created_at",   label: "Created"      }
    ];

    sortKeys.forEach(function(sk) {
        var btn = document.createElement("button");
        btn.className = "playlistsSortBtn" + (_plSortKey === sk.key ? " active" : "");
        var arrow = _plSortKey === sk.key ? (_plSortAsc ? " \u2191" : " \u2193") : "";
        btn.textContent = sk.label + arrow;
        (function(k) {
            btn.onclick = function() {
                if (_plSortKey === k) {
                    _plSortAsc = !_plSortAsc;
                } else {
                    _plSortKey = k;
                    _plSortAsc = (k === "name");
                }
                renderPlaylistsList(allPlaylists);
            };
        }(sk.key));
        sortBar.appendChild(btn);
    });
    var filterWrap = document.createElement("div");
    filterWrap.className = "playlistsFilterWrap";

    var filterInput = document.createElement("input");
    filterInput.id          = "playlistsFilter";
    filterInput.type        = "text";
    filterInput.placeholder = "Filter playlists...";
    filterInput.className   = "playlistsFilterInput";
    filterInput.oninput     = onPlaylistFilter;

    filterWrap.appendChild(filterInput);
    sortBar.appendChild(filterWrap);
    playlistsContent.appendChild(sortBar);

    var list = document.createElement("div");
    list.id        = "playlistsList";
    list.className = "playlistList";
    playlistsContent.appendChild(list);

    renderPlaylistRows(_sortPlaylists(playlists));
}

function renderPlaylistRows(playlists) {
    var list = document.getElementById("playlistsList");
    if (!list) { return; }
    list.innerHTML = "";
    if (playlists.length === 0) {
        list.innerHTML = '<div class="playlistsLoading">No matching playlists.</div>';
        return;
    }
    playlists.forEach(function(item) {
        var row = document.createElement("div");
        row.className = "playlistRow";
        row.setAttribute(
            "data-playlist-id",
            String(item.id || "")
        );
        row.innerHTML =
            '<img src="' + (item.image_url || "") + '" class="playlistThumb">' +
            '<div class="playlistMeta">' +
                '<div class="playlistName">'  + (item.name      || "") + '</div>' +
                '<div class="playlistSub">'   + (item.sub_title || "") + '</div>' +
            '</div>' +
            '<button type="button" class="playlistDeleteBtn" title="Delete playlist" aria-label="Delete playlist">' +
                '<span class="material-icons">delete</span>' +
            '</button>';
        if (item.id) {
            (function(it) {
                var deleteBtn = row.querySelector(".playlistDeleteBtn");
                if (deleteBtn) {
                    deleteBtn.onclick = function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        showDeleteTidalPlaylistModal(it);
                    };
                }
                row.onclick = function() {
                    loadTrackList(
                        { id: it.id, cover: it.image_url, title: it.name, artist: it.sub_title || "" },
                        "/tidal/playlist/" + it.id,
                        "playlists"
                    );
                };
            }(item));
        }
        list.appendChild(row);
    });
}


// --- Search ---

function onSearchInput(e) {
    if (!searchInput || searchInput.disabled) {
        clearTimeout(searchTimer);
        if (e && e.target) { e.target.value = ""; }
        return;
    }
    var q = e.target.value.trim();
    if (q) {
        lastSearchQuery = q;
        try { sessionStorage.setItem("srovaLastSearchQuery", q); } catch (err) {}
    }
    if (q === "") {
        searchClear.classList.add("hidden");
        showView("home");
    } else {
        searchClear.classList.remove("hidden");
    }
    clearTimeout(searchTimer);
    if (!q) { return; }
    searchTimer = setTimeout(function() { doSearch(q); }, 400);
}

function onSearchKey(e) { if (e.key === "Escape") { clearSearch(); } }

function clearSearch() {
    searchInput.value = "";
    searchClear.classList.add("hidden");
    showView("home");
}

function doSearch(query, opts) {
    opts = opts || {};
    if (!globalSearchHasReadySource()) {
        setGlobalSearchVisible(true);
        showView("home");
        return;
    }
    lastSearchQuery = String(query || "").trim();
    showView("search");
    if (!opts.restore) { currentSearchTab = "top"; }
    searchResults.innerHTML = '<div class="searchLoading">Searching SROVA...</div>';
    var encoded = encodeURIComponent(query);
    var localRequest = globalSearchLocalReady
        ? fetch("/api/local/library/search?q=" + encoded + "&limit=100")
            .then(function(res) { return res.json(); })
            .then(function(data) { return { ok: true, data: data || {} }; })
            .catch(function() { return { ok: false, data: {} }; })
        : Promise.resolve({ok: true, data: {}});
    var tidalRequest = globalSearchTidalReady
        ? fetchWithTimeout("/tidal/search?q=" + encoded + "&limit=" + TIDAL_SEARCH_LIMIT, {}, 4500)
            .then(function(res) { return res.json(); })
            .then(function(data) { return { ok: true, data: data || {} }; })
            .catch(function() { return { ok: false, data: {} }; })
        : Promise.resolve({ok: true, data: {}});

    Promise.all([localRequest, tidalRequest]).then(function(parts) {
        renderGlobalSearchResults({
            query: query,
            local: parts[0],
            tidal: parts[1]
        });
    });
}

function renderGlobalSearchResults(payload) {
    searchResults.innerHTML = "";
    lastSearchPayload = normalizeSrovaSearchPayload(payload || {});
    lastSearchQuery = lastSearchPayload.query || lastSearchQuery || "";
    lastSearchTab = currentSearchTab || lastSearchTab || "top";
    persistSearchRestorePayload();
    if (!lastSearchPayload.hasAny && lastSearchPayload.localOk && lastSearchPayload.tidalOk) {
        searchResults.innerHTML = '<div class="searchLoading">No SROVA results found.</div>';
        return;
    }
    renderSrovaSearchShell(lastSearchPayload);
}

function normalizeSrovaSearchPayload(payload) {
    var local = payload.local || { ok: false, data: {} };
    var tidal = payload.tidal || { ok: false, data: {} };
    var localData = local.data || {};
    var tidalData = tidal.data || {};
    var out = {
        query: payload.query || "",
        localOk: !!local.ok,
        tidalOk: !!tidal.ok,
        localBusy: !!(localData.busy || isLocalLibraryMaintenance(localData)),
        localFailed: !local.ok,
        tidalFailed: !tidal.ok,
        tracks: [],
        albums: [],
        artists: [],
        hasAny: false
    };

    if (!out.localBusy && local.ok) {
        var localArtistArtworkByName = {};
        var localArtistAlbumArtworkByName = {};

        function rememberLocalArtistArtwork(name, item) {
            var key = String(name || "").trim().toLowerCase();
            if (!key) { return; }
            item = item || {};
            var artwork = item.cover || item.cover_url || item.artwork_url ||
                item.image_url || item.album_art || item.album_art_url || "";
            if (!artwork) { return; }

            if (!localArtistArtworkByName[key]) {
                localArtistArtworkByName[key] = artwork;
            }

            var albumKey = String(
                item.album || item.album_name || item.name || ""
            ).trim().toLowerCase();
            if (albumKey) {
                if (!localArtistAlbumArtworkByName[key]) {
                    localArtistAlbumArtworkByName[key] = {};
                }
                if (!localArtistAlbumArtworkByName[key][albumKey]) {
                    localArtistAlbumArtworkByName[key][albumKey] = artwork;
                }
            }
        }

        (localData.albums || []).forEach(function(album) {
            rememberLocalArtistArtwork(
                album.album_artist || album.artist || "",
                album
            );
        });
        (localData.songs || localData.tracks || []).forEach(function(track) {
            rememberLocalArtistArtwork(track.artist || "", track);
            out.tracks.push(normalizeSearchTrack(track, "local"));
        });
        (localData.albums || []).forEach(function(album) {
            out.albums.push(normalizeSearchAlbum(album, "local"));
        });
        (localData.artists || []).forEach(function(artist) {
            var normalizedArtist = normalizeSearchArtist(artist, "local");
            var artistKey = String(normalizedArtist.name || "").trim().toLowerCase();
            normalizedArtist.cover = normalizedArtist.cover ||
                localArtistArtworkByName[artistKey] || "";
            normalizedArtist.albumArtwork =
                localArtistAlbumArtworkByName[artistKey] || {};
            out.artists.push(normalizedArtist);
        });
    }
    if (tidal.ok) {
        (tidalData.tracks || []).forEach(function(track) {
            out.tracks.push(normalizeSearchTrack(track, "tidal"));
        });
        (tidalData.albums || []).forEach(function(album) {
            out.albums.push(normalizeSearchAlbum(album, "tidal"));
        });
        (tidalData.artists || []).forEach(function(artist) {
            out.artists.push(normalizeSearchArtist(artist, "tidal"));
        });
    }
    out.hasAny = !!(out.tracks.length || out.albums.length || out.artists.length);
    return out;
}

function normalizeSearchTrack(track, source) {
    track = track || {};
    return {
        type: "track",
        source: source,
        raw: track,
        id: String(track.id || ""),
        title: track.title || track.name || "",
        artist: track.artist || "",
        album: track.album || track.album_name || "",
        cover: track.artwork_url || track.cover || track.image_url || "",
        duration: Number(track.duration || 0),
        quality: track.quality || (source === "local" ? "LOCAL" : ""),
        explicit: !!track.explicit
    };
}

function normalizeSearchAlbum(album, source) {
    album = album || {};
    var year = album.year || "";
    var releaseDate = album.release_date || album.releaseDate || "";
    if (!year && releaseDate) { year = String(releaseDate).slice(0, 4); }
    return {
        type: "album",
        source: source,
        raw: album,
        id: String(album.id || album.album_id || album.group_id || ""),
        title: album.album || album.name || "",
        artist: album.artist || album.album_artist || "",
        cover: localAlbumArtworkUrl(album, album.album || album.name || "", album.artist || album.album_artist || "") || album.image_url || "",
        year: year || "",
        explicit: !!album.explicit,
        trackCount: album.track_count || album.num_tracks || 0
    };
}

function normalizeSearchArtist(artist, source) {
    artist = artist || {};
    return {
        type: "artist",
        source: source,
        raw: artist,
        id: String(artist.id || ""),
        name: artist.artist || artist.name || "",
        cover: artist.image_url || "",
        sub: source === "local"
            ? ((artist.album_count || 0) + " albums")
            : "Artist"
    };
}

function renderSrovaSearchShellInto(target, data, opts) {
    opts = opts || {};
    var getTab = opts.getTab || function() { return currentSearchTab || "top"; };
    var setTab = opts.setTab || function(tab) {
        currentSearchTab = tab || "top";
        lastSearchTab = currentSearchTab;
    };
    var renderAgain = opts.renderAgain || function(nextData) {
        renderSrovaSearchShellInto(target, nextData || data, opts);
    };
    var activeTab = getTab();
    var shell = document.createElement("div");
    shell.className = "srovaSearchShell";

    var header = document.createElement("div");
    header.className = "srovaSearchHeader";
    var title = document.createElement("div");
    title.className = "srovaGlobalSearchTitle";
    title.textContent = opts.title || "SROVA Search";
    header.appendChild(title);
    shell.appendChild(header);

    var tabs = document.createElement("div");
    tabs.className = "srovaSearchTabs";
    [
        ["top", "TOP RESULTS"],
        ["tracks", "TRACKS"],
        ["albums", "ALBUMS"],
        ["artists", "ARTISTS"]
    ].forEach(function(item) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "srovaSearchTab" + (activeTab === item[0] ? " active" : "");
        btn.setAttribute("data-search-tab", item[0]);
        btn.textContent = item[1];
        btn.onclick = function() {
            setTab(item[0]);
            renderAgain(data);
        };
        tabs.appendChild(btn);
    });
    shell.appendChild(tabs);

    if (data.localBusy) { shell.appendChild(globalSearchNotice("Local Music is rebuilding.")); }
    if (data.localFailed) { shell.appendChild(globalSearchNotice("Local Music search failed.")); }
    if (data.tidalFailed) { shell.appendChild(globalSearchNotice("Tidal search failed.")); }

    var panel = document.createElement("div");
    panel.className = "srovaSearchPanel";
    activeTab = getTab();
    if (activeTab === "tracks") {
        renderSrovaSearchTracksPanel(data, panel);
    } else if (activeTab === "albums") {
        renderSrovaSearchAlbumsPanel(data, panel, opts);
    } else if (activeTab === "artists") {
        renderSrovaSearchArtistsPanel(data, panel, opts);
    } else {
        renderSrovaSearchTopPanel(data, panel, opts);
    }
    shell.appendChild(panel);

    target.innerHTML = "";
    target.appendChild(shell);
}

function renderSrovaSearchShell(data) {
    renderSrovaSearchShellInto(searchResults, data, {
        sourceView: "search",
        title: "SROVA Search",
        getTab: function() { return currentSearchTab || "top"; },
        setTab: function(tab) {
            currentSearchTab = tab || "top";
            lastSearchTab = currentSearchTab;
        },
        renderAgain: function() {
            renderSrovaSearchShell(lastSearchPayload || data);
        }
    });
}

function globalSearchSourceGroup(title) {
    var group = document.createElement("div");
    group.className = "srovaGlobalSearchGroup";
    var h = document.createElement("h1");
    h.textContent = title;
    group.appendChild(h);
    return group;
}

function globalSearchNotice(text) {
    var div = document.createElement("div");
    div.className = "searchLoading srovaGlobalSearchNotice";
    div.textContent = text || "";
    return div;
}

function renderSrovaSearchTopPanel(data, panel, opts) {
    opts = opts || {};
    var rows = [];
    data.tracks.slice(0, 4).forEach(function(track) { rows.push(track); });
    data.albums.slice(0, 4).forEach(function(album) { rows.push(album); });
    data.artists.slice(0, 2).forEach(function(artist) { rows.push(artist); });

    if (!rows.length) {
        panel.appendChild(globalSearchNotice("No top results found."));
        return;
    }

    var list = document.createElement("div");
    list.className = "srovaSearchTopList";
    rows.slice(0, 8).forEach(function(item) {
        list.appendChild(renderSrovaSearchTopRow(item, opts));
    });
    panel.appendChild(list);
}

function renderSrovaSearchTracksPanel(data, panel) {
    if (!data.tracks.length) {
        panel.appendChild(globalSearchNotice("No track results found."));
        return;
    }
    var table = document.createElement("div");
    table.className = "srovaSearchTrackTable";
    table.innerHTML =
        '<div class="srovaSearchTrackHead">' +
          '<span>#</span><span></span><span>Title</span><span>Artist</span><span>Album</span><span>Time</span><span></span><span></span>' +
        '</div>';
    data.tracks.forEach(function(track, idx) {
        table.appendChild(renderSrovaSearchTrackRow(track, idx + 1, false));
    });
    panel.appendChild(table);
}

function renderSrovaSearchAlbumsPanel(data, panel, opts) {
    opts = opts || {};
    if (!data.albums.length) {
        panel.appendChild(globalSearchNotice("No album results found."));
        return;
    }
    var header = document.createElement("div");
    header.className = "artworkViewHeader srovaSearchArtworkHeader";
    var title = document.createElement("h2");
    title.textContent = "Albums";
    header.appendChild(title);
    appendArtworkViewToggle(header);
    panel.appendChild(header);

    var grid = document.createElement("div");
    grid.className = "srovaSearchAlbumGrid";
    applyArtworkViewModeClass(grid);
    data.albums.forEach(function(album) {
        grid.appendChild(renderSrovaSearchAlbumCard(album, false, opts));
    });
    panel.appendChild(grid);
}


function renderSrovaSearchArtistsPanel(data, panel, opts) {
    opts = opts || {};
    if (!data.artists.length) {
        panel.appendChild(globalSearchNotice("No artist results found."));
        return;
    }
    var header = document.createElement("div");
    header.className = "artworkViewHeader srovaSearchArtworkHeader";
    var title = document.createElement("h2");
    title.textContent = "Artists";
    header.appendChild(title);
    panel.appendChild(header);

    var grid = document.createElement("div");
    grid.className = "srovaSearchAlbumGrid srovaSearchArtistGrid";
    data.artists.forEach(function(artist) {
        grid.appendChild(renderSrovaSearchArtistCard(artist, false, opts));
    });
    panel.appendChild(grid);
}

function renderSrovaSearchArtistCard(artist, featured, opts) {
    opts = opts || {};
    var card = document.createElement("div");
    card.className = "srovaSearchArtistCard" + (featured ? " featured" : "");
    var img = artist.cover
        ? '<img src="' + escapeHtml(artist.cover) + '" alt="">'
        : '<div class="localArtPlaceholder localArtistArt"><span>' + escapeHtml(localInitials(artist.name || "")) + '</span></div>';
    card.innerHTML =
        img +
        '<div class="srovaSearchCardMeta">' +
          '<div class="srovaSearchEyebrow">' + escapeHtml(artist.source === "local" ? "LOCAL" : "TIDAL") + '</div>' +
          '<div class="srovaSearchCardTitle">' + escapeHtml(artist.name || "") + '</div>' +
          '<div class="srovaSearchCardSub">' + escapeHtml(artist.sub || "") + '</div>' +
        '</div>';
    card.onclick = function() {
        if (artist.source === "local") {
            openLocalArtistFromGlobalSearch(
                artist.name || "",
                artist.cover || "",
                artist.albumArtwork || {}
            );
        } else if (artist.id) {
            if (opts.sourceView === "tidalsource") {
                captureTidalSourceSearchStateFromDom();
            } else {
                captureSearchRestoreState();
            }
            loadArtistPage(
                artist.id,
                artist.name || "",
                artist.cover || "",
                opts.sourceView === "tidalsource" ? "tidalsource" : "search"
            );
        }
    };
    return card;
}

function renderSrovaSearchTopRow(item, opts) {
    opts = opts || {};
    var row = document.createElement("div");
    row.className = "srovaSearchTopRow";
    var art = "";
    var title = "";
    var typeLabel = "";
    var sub = "";
    var meta = "";

    if (item.type === "artist") {
        title = item.name || "";
        typeLabel = item.source === "local" ? "Artist · Local" : "Artist";
        sub = item.sub || "";
        art = item.cover
            ? '<img class="srovaSearchTopArt artist" src="' + escapeHtml(item.cover) + '" alt="">'
            : '<div class="srovaSearchTopArt localArtPlaceholder localArtistArt"><span>' + escapeHtml(localInitials(title)) + '</span></div>';
        row.onclick = function() {
            if (item.source === "local") {
                openLocalArtistFromGlobalSearch(
                    item.name || "",
                    item.cover || "",
                    item.albumArtwork || {}
                );
            }
            else if (item.id) {
                if (opts.sourceView === "tidalsource") {
                    captureTidalSourceSearchStateFromDom();
                    loadArtistPage(item.id, item.name || "", item.cover || "", "tidalsource");
                } else {
                    captureSearchRestoreState();
                    loadArtistPage(item.id, item.name || "", item.cover || "", "search");
                }
            }
        };
    } else if (item.type === "album") {
        title = item.title || "";
        typeLabel = item.source === "local" ? "Album · Local" : "Album";
        sub = item.artist || "";
        meta = item.year || "";
        art = '<img class="srovaSearchTopArt" src="' + escapeHtml(item.cover || localAlbumArtDataUri(item.title, item.artist)) + '" alt="">';
        row.onclick = function() {
            if (item.source === "local") {
                var localAlbumFromView = opts.sourceView || "search";
                if (localAlbumFromView === "tidalsource") {
                    captureTidalSourceSearchStateFromDom();
                } else if (localAlbumFromView === "search") {
                    captureSearchRestoreState();
                }
                loadLocalAlbum(item.raw.artist || item.artist || "", item.raw.album || item.title || "", item.raw.album_id || item.raw.group_id || item.id || "", localAlbumFromView);
            } else if (item.id) {
                if (opts.sourceView === "tidalsource") {
                    captureTidalSourceSearchStateFromDom();
                } else {
                    captureSearchRestoreState();
                }
                loadTrackList({ id: item.id, cover: item.cover, title: item.title, artist: item.artist },
                    "/tidal/album/" + item.id, opts.sourceView === "tidalsource" ? "tidalsource" : "search");
            }
        };
    } else {
        title = item.title || "";
        typeLabel = item.source === "local" ? "Track · Local" : "Track";
        sub = item.artist || "";
        meta = item.duration ? formatTime(item.duration) : "";
        art = '<img class="srovaSearchTopArt" src="' + escapeHtml(item.cover || localAlbumArtDataUri(item.title, item.artist)) + '" alt="">';
        row.onclick = function() { playSrovaSearchTrack(item); };
    }

    row.innerHTML =
        art +
        '<div class="srovaSearchTopMeta">' +
          '<div class="srovaSearchTopTitle">' + escapeHtml(title) + '</div>' +
          '<div class="srovaSearchTopSub">' +
            '<span class="srovaSearchTypePill">' + escapeHtml(typeLabel) + '</span>' +
            '<span>' + escapeHtml(sub) + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="srovaSearchTopExtra">' + escapeHtml(meta) + '</div>';
    if (item.type === "track" && (item.source === "tidal" || item.source === "local")) {
        var addBtn = document.createElement("button");
        addBtn.className = "srovaSearchActionBtn";
        addBtn.innerHTML = '<span class="material-icons">add</span>';
        addBtn.title = "Track actions";
        addBtn.setAttribute("aria-label", "Track actions");
        addBtn.onclick = function(e) {
            e.stopPropagation();
            if (item.source === "tidal") {
                showTidalSearchTrackMenu(addBtn, item, e);
                return;
            }
            showLocalSearchTrackMenu(addBtn, item, e);
        };
        row.appendChild(addBtn);
    }
    applyLocalArtworkFallback(row.querySelector("img"), title, sub);
    return row;
}

function renderSrovaSearchAlbumCard(album, featured, opts) {
    opts = opts || {};
    var card = document.createElement("div");
    card.className = "srovaSearchAlbumCard" + (featured ? " featured" : "");
    card.innerHTML =
        '<img src="' + escapeHtml(album.cover || localAlbumArtDataUri(album.title, album.artist)) + '" alt="">' +
        '<div class="srovaSearchCardMeta">' +
          '<div class="srovaSearchEyebrow">' + escapeHtml(album.source === "local" ? "LOCAL ALBUM" : "ALBUM") + '</div>' +
          '<div class="srovaSearchCardTitle">' + escapeHtml(album.title || "") + '</div>' +
          '<div class="srovaSearchCardSub">' + escapeHtml(album.artist || "") + '</div>' +
          '<div class="srovaSearchAlbumFacts">' +
            (album.year ? '<span>' + escapeHtml(album.year) + '</span>' : '') +
            (album.explicit ? '<span class="srovaSearchExplicit">E</span>' : '') +
          '</div>' +
        '</div>';
    applyLocalArtworkFallback(card.querySelector("img"), album.title, album.artist);
    card.onclick = function() {
        if (album.source === "local") {
            var localAlbumFromView = opts.sourceView || "search";
            if (localAlbumFromView === "tidalsource") {
                captureTidalSourceSearchStateFromDom();
            } else if (localAlbumFromView === "search") {
                captureSearchRestoreState();
            }
            loadLocalAlbum(album.raw.artist || album.artist || "", album.raw.album || album.title || "", album.raw.album_id || album.raw.group_id || album.id || "", localAlbumFromView);
        } else if (album.id) {
            if (opts.sourceView === "tidalsource") {
                captureTidalSourceSearchStateFromDom();
            } else {
                captureSearchRestoreState();
            }
            loadTrackList({ id: album.id, cover: album.cover, title: album.title, artist: album.artist },
                "/tidal/album/" + album.id, opts.sourceView === "tidalsource" ? "tidalsource" : "search");
        }
    };
    return card;
}

function renderSrovaSearchTrackRow(track, index, compact) {
    var row = document.createElement("div");
    row.className = "srovaSearchTrackRow" + (compact ? " compact" : "");
    row.setAttribute("data-track-id", track.id);
    row.innerHTML =
        '<div class="srovaSearchTrackNum">' + index + '</div>' +
        '<img class="srovaSearchTrackArt" src="' + escapeHtml(track.cover || localAlbumArtDataUri(track.title, track.artist)) + '" alt="">' +
        '<div class="srovaSearchTrackTitleCell">' +
          '<div class="srovaSearchTrackTitle">' + escapeHtml(track.title || "") + '</div>' +
          '<div class="srovaSearchSourcePill">' + escapeHtml(track.source === "local" ? "LOCAL" : "TIDAL") + '</div>' +
        '</div>' +
        '<div class="srovaSearchTrackArtist">' + escapeHtml(track.artist || "") + '</div>' +
        '<div class="srovaSearchTrackAlbum">' + escapeHtml(track.album || "") + '</div>' +
        '<div class="srovaSearchTrackTime">' + formatTime(track.duration || 0) + '</div>';

    var addBtn = document.createElement("button");
    addBtn.className = "srovaSearchActionBtn";
    addBtn.innerHTML = '<span class="material-icons">add</span>';
    addBtn.title = "Track actions";
    addBtn.setAttribute("aria-label", "Track actions");
    addBtn.onclick = function(e) {
        e.stopPropagation();
        if (track.source === "tidal") {
            showTidalSearchTrackMenu(addBtn, track, e);
            return;
        }
        if (track.source === "local") {
            showLocalSearchTrackMenu(addBtn, track, e);
        }
    };
    row.appendChild(addBtn);

    var heartBtn = document.createElement("button");
    heartBtn.className = "srovaSearchActionBtn srovaSearchHeart";
    heartBtn.innerHTML = '<span class="material-icons">favorite_border</span>';
    heartBtn.title = "Favorite";
    heartBtn.setAttribute("aria-label", "Favorite");
    if (track.source === "tidal" && track.id) {
        heartBtn.setAttribute("data-track-id", track.id);
        updateSingleHeartEl(heartBtn, !!favTrackIds[track.id]);
        heartBtn.onclick = function(e) {
            e.stopPropagation();
            toggleTrackFavorite(track.id, heartBtn);
        };
    } else {
        heartBtn.disabled = true;
        heartBtn.classList.add("disabled");
    }
    row.appendChild(heartBtn);

    applyLocalArtworkFallback(row.querySelector(".srovaSearchTrackArt"), track.title, track.artist);
    row.onclick = function() { playSrovaSearchTrack(track); };
    return row;
}

function searchTrackQueuePayload(track) {
    if (track.source === "local") {
        return buildLocalTrackPayload(track.raw, track.cover);
    }
    return {
        id: track.id,
        title: track.title || "",
        artist: track.artist || "",
        album: track.album || "",
        cover: track.cover || "",
        duration: track.duration || 0,
        quality: track.quality || ""
    };
}

function showTidalSearchTrackMenu(anchorEl, track, e) {
    if (!track || track.source !== "tidal" || !track.id) { return; }
    showTidalTrackArtworkMenu(anchorEl, {
        id: track.id,
        name: track.title || "",
        sub_title: track.artist || "",
        image_url: track.cover || "",
        duration: track.duration || 0,
        quality: track.quality || ""
    }, e);
}

function showLocalSearchTrackMenu(anchorEl, track, e) {
    if (e) { e.stopPropagation(); }
    if (!track || track.source !== "local") { return; }
    if (isLocalLibraryMaintenance()) {
        showQueueActionToast("Local Music is rebuilding", true);
        return;
    }

    var payload = [searchTrackQueuePayload(track)];
    closeActivePopover();

    var popover = document.createElement("div");
    popover.className = "queuePopover";

    function addMenuButton(icon, label, onClick) {
        var btn = document.createElement("button");
        btn.className = "queuePopoverBtn";
        btn.innerHTML = '<span class="material-icons">' + icon + '</span> ' + label;
        btn.onclick = function(ev) {
            ev.stopPropagation();
            closeActivePopover();
            onClick();
        };
        popover.appendChild(btn);
    }

    addMenuButton("play_arrow", "Play Now", function() {
        playLocalLibraryTrack(track.raw);
    });
    addMenuButton("queue_play_next", "Play Next", function() {
        submitQueueTracks(payload, "next");
    });
    addMenuButton("add_to_queue", "Add to Queue", function() {
        submitQueueTracks(payload, "queue");
    });

    positionQueuePopover(anchorEl, popover);
}

function playSrovaSearchTrack(track) {
    if (track.source === "local") {
        playLocalLibraryTrack(track.raw);
        return;
    }
    playSearchTrack(track.raw);
}

function tidalSearchSection(title, items, rowRenderer) {
    var sec = document.createElement("div");
    sec.className = "searchSection";
    var h = document.createElement("h2");
    h.textContent = title;
    sec.appendChild(h);
    items.forEach(function(item) { sec.appendChild(rowRenderer(item)); });
    return sec;
}

function renderSearchResults(data) {
    var normalized = normalizeSrovaSearchPayload({
        query: "",
        local: { ok: true, data: {} },
        tidal: { ok: true, data: data || {} }
    });
    lastSearchPayload = normalized;
    if (!normalized.hasAny) {
        searchResults.innerHTML = '<div class="searchLoading">No results found.</div>';
        return;
    }
    renderSrovaSearchShell(normalized);
}

function renderSearchTrack(track) {
    var row = document.createElement("div");
    row.className = "searchTrack";
    row.innerHTML =
        '<img src="' + (track.image_url || "") + '" class="searchThumb">' +
        '<div class="searchMeta"><div class="searchName">' + (track.name || "") + '</div>' +
        '<div class="searchSub">' + (track.artist || "") + '</div></div>' +
        '<div class="searchDuration">' + formatTime(track.duration || 0) + '</div>';
    row.onclick = function() { playSearchTrack(track); };
    return row;
}

function renderSearchAlbum(album) {
    var row = document.createElement("div");
    row.className = "searchAlbum";
    row.innerHTML =
        '<img src="' + (album.image_url || "") + '" class="searchThumb">' +
        '<div class="searchMeta"><div class="searchName">' + (album.name || "") + '</div>' +
        '<div class="searchSub">' + (album.artist || "") + '</div></div>';
    if (album.id) {
        row.onclick = function() {
            loadTrackList({ id: album.id, cover: album.image_url, title: album.name, artist: album.artist },
                "/tidal/album/" + album.id, "search");
        };
    }
    return row;
}

function renderSearchArtist(artist) {
    var row = document.createElement("div");
    row.className = "searchArtist";
    row.innerHTML =
        '<img src="' + (artist.image_url || "") + '" class="searchThumb searchThumbCircle">' +
        '<div class="searchMeta"><div class="searchName">' + (artist.name || "") + '</div>' +
        '<div class="searchSub">Top Tracks</div></div>' +
        '<span class="material-icons searchArrow">chevron_right</span>';
    if (artist.id) {
        row.onclick = function() {
            var fromView = isInsideTidalSourceSearch(row) ? "tidalsource" : "search";
            if (fromView === "tidalsource") {
                captureTidalSourceSearchStateFromDom();
            } else {
                captureSearchRestoreState();
            }
            loadArtistPage(artist.id, artist.name || "", artist.image_url || "", fromView);
        };
    }
    return row;
}

function postTidalQueueReplace(payload) {
    if (!requireOnlineSource()) {
        return Promise.reject(new Error(ONLINE_SOURCE_OFFLINE_MESSAGE));
    }
    return fetchWithTimeout("/tidal/queue/replace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {})
    }, 7000)
        .then(function(res) { return res.json().catch(function() { return {}; }); })
        .then(function(data) {
            if (data && (data.ok === false || data.offline || data.error)) {
                throw new Error(playbackErrorMessage(data, ONLINE_SOURCE_OFFLINE_MESSAGE));
            }
            pollStatus();
            return data || {};
        })
        .catch(function(err) {
            var message = normalizePlaybackErrorMessage(err) ||
                normalizePlaybackErrorMessage(ONLINE_SOURCE_OFFLINE_MESSAGE);
            if (message === DAC_PLAYBACK_ERROR_MESSAGE) {
                showQueueActionToast(message, true);
            } else {
                handleOnlineSourceFailure(message);
            }
            throw err;
        });
}

function playSearchTrack(track) {
    if (!requireOnlineSource()) { return; }
    clearRadioIdleStandbyTimer();
    resetTidalInfinitePlayGuard();
    _setPlaybackSource("search", "", track.name || "");
    var t = {
        id:      track.id,
        title:   track.name   || "",
        artist:  track.artist || "",
        cover:   track.image_url || "",
        duration: track.duration || 0,
        quality: ""
    };
    postTidalQueueReplace({
        tracks:        [t],
        start_index:   0,
        context_type:  "search",
        context_id:    "",
        context_title: track.name || ""
    }).then(function() {
        trackMap[String(track.id)] = {
            title: track.name || "", artist: track.artist || "",
            cover: track.image_url || "", duration: track.duration || 0
        };
    }).catch(function() {});
}


// --- Item routing ---

function handleItemClick(item, fromView) {
    if ((fromView || "") === "tidalsource") {
        captureTidalSourceSearchStateFromDom();
    }
    var type = (item.type || "Album").toLowerCase();
    if (type === "track") { playTrackDirect(item); return; }
    var context = { id: item.id, cover: item.image_url, title: item.name, artist: item.sub_title || "" };
    if      (type === "playlist") { loadTrackList(context, "/tidal/playlist/" + item.id, fromView); }
    else if (type === "mix")      { loadTrackList(context, "/tidal/mix/"      + item.id, fromView); }
    else                          { loadTrackList(context, "/tidal/album/"    + item.id, fromView); }
}

function handleTidalWallItemClick(item, fromView, e, anchorEl) {
    if (!requireOnlineSource()) { return; }
    var type = (item.type || "Album").toLowerCase();
    if (type !== "track") {
        handleItemClick(item, fromView);
        return;
    }
    showTidalTrackArtworkMenu(anchorEl, item, e);
}

function buildTidalWallTrackPayload(item) {
    item = item || {};
    return {
        id:       item.id,
        title:    item.name      || item.title  || "",
        artist:   item.sub_title || item.artist || "",
        cover:    item.image_url || item.cover  || "",
        duration: item.duration  || 0,
        quality:  item.quality   || ""
    };
}

function showTidalTrackArtworkMenu(anchorEl, item, e) {
    if (e) { e.stopPropagation(); }
    if (!requireOnlineSource()) { return; }
    if (!item || !item.id) { return; }
    closeActivePopover();

    var payload = [buildTidalWallTrackPayload(item)];
    var trackIds = normalizeTidalTrackIds(payload);
    var popover = document.createElement("div");
    popover.className = "queuePopover tidalTrackArtworkMenu";

    function addMenuButton(icon, label, onClick) {
        var btn = document.createElement("button");
        btn.className = "queuePopoverBtn";
        btn.innerHTML = '<span class="material-icons">' + icon + '</span> ' + label;
        btn.onclick = function(ev) {
            ev.stopPropagation();
            closeActivePopover();
            onClick();
        };
        popover.appendChild(btn);
    }

    addMenuButton("play_arrow", "Play Now", function() {
        playTrackDirect(item);
    });
    addMenuButton("queue_play_next", "Play Next", function() {
        submitQueueTracks(payload, "next");
    });
    addMenuButton("add_to_queue", "Add to Queue", function() {
        submitQueueTracks(payload, "queue");
    });
    if (trackIds.length) {
        addMenuButton("playlist_add", "Add to Playlist", function() {
            showAddToTidalPlaylistModal(trackIds);
        });
    }

    positionQueuePopover(anchorEl, popover);
}

function playTrackDirect(item) {
    if (!requireOnlineSource()) { return; }
    clearRadioIdleStandbyTimer();
    resetTidalInfinitePlayGuard();
    var fromView = previousView || "home";
    var ctxType  = (fromView === "mysongs")   ? "mysongs"
                 : (fromView === "myalbums")  ? "myalbums"
                 : "home";
    _setPlaybackSource(ctxType, "", item.name || "");
    var t = {
        id:      item.id,
        title:   item.name      || "",
        artist:  item.sub_title || "",
        cover:   item.image_url || "",
        duration: item.duration || 0,
        quality: ""
    };
    postTidalQueueReplace({
        tracks:        [t],
        start_index:   0,
        context_type:  ctxType,
        context_id:    "",
        context_title: item.name || ""
    }).then(function() {
        trackMap[String(item.id)] = {
            title: item.name || "", artist: item.sub_title || "",
            cover: item.image_url || "", duration: item.duration || 0
        };
    }).catch(function() {});
}



function isTidalSourcePageVisible() {
    var page = document.querySelector(".srovaTidalSourcePage");
    if (!page || !homeView) { return false; }
    return homeView.style.display !== "none" &&
        !homeView.classList.contains("hidden") &&
        page.style.display !== "none";
}


// --- Track list ---

function loadTrackList(context, endpoint, fromView) {
    endpoint = endpoint || "";
    if (endpoint.indexOf("/tidal/") === 0 && !requireOnlineSource()) { return; }

    if (
        (fromView || "") !== "artistpage" &&
        (fromView || "") !== "nowplaying" &&
        isTidalSourcePageVisible() &&
        endpoint.indexOf("/tidal/") === 0
    ) {
        if (typeof captureTidalSourceSearchStateFromDom === "function") {
            captureTidalSourceSearchStateFromDom();
        }
        fromView = "tidalsource";
    } else if ((fromView || "") === "search" || (searchView && searchView.style.display !== "none")) {
        captureSearchRestoreState();
    }

    if ((fromView || "") === "tidalsource" && typeof captureTidalSourceSearchStateFromDom === "function") {
        captureTidalSourceSearchStateFromDom();
    }

    fromView = fromView || "home";
    if (fromView === "tidalsource" || fromView === "playlists" || fromView === "search" || fromView === "localmusic") {
        captureDetailReturnScroll(fromView);
    }

    previousView        = fromView;
    currentViewEndpoint = endpoint;

    // Derive context type from endpoint for source tracking
    var srcType  = "album";
    var srcId    = String(context.id || "");
    var srcTitle = context.title || "";
    if      (endpoint.indexOf("/tidal/playlist/") === 0) { srcType = "playlist"; }
    else if (endpoint.indexOf("/tidal/mix/")      === 0) { srcType = "mix"; }
    else if (endpoint.indexOf("/tidal/artist/")   === 0) { srcType = "artist"; }
    _setPlaybackSource(srcType, srcId, srcTitle);
    fetchWithTimeout(endpoint, {}, endpoint.indexOf("/tidal/") === 0 ? 6000 : 0)
        .then(function(res) { return res.json(); })
        .then(function(resp) {
            // Album and playlist endpoints return metadata with tracks;
            // remaining detail endpoints may still return a plain array.
            var tracks;
            var respArtistId = "";
            var respArtistName = "";
            var respPlaylistName = "";
            var respPlaylistEditable = false;
            if (Array.isArray(resp)) {
                tracks = resp;
            } else if (resp && Array.isArray(resp.tracks)) {
                tracks = resp.tracks;
                respArtistId = resp.artist_id || "";
                respArtistName = resp.artist_name || "";
                respPlaylistName = resp.playlist_name || "";
                respPlaylistEditable = resp.playlist_editable === true;
            } else {
                tracks = [];
            }
            var tidalDetailKind =
                currentViewEndpoint.indexOf("/tidal/album/") === 0
                    ? "tidal-album"
                    : (
                        currentViewEndpoint.indexOf("/tidal/playlist/") === 0 ||
                        currentViewEndpoint.indexOf("/tidal/mix/") === 0
                    )
                        ? "tidal-detail"
                        : "";
            setAlbumViewKind(tidalDetailKind);
            showView("album");
            albumArt.src            = context.cover  || "";
            albumTitle.textContent  = context.title  || "";
            var albumMeta = context.artist || "";
            if (currentViewEndpoint.indexOf("/tidal/album/") === 0) {
                var totalDuration = tracks.reduce(function(sum, t) {
                    return sum + (Number(t.duration) || 0);
                }, 0);
                if (tracks.length) {
                    albumMeta += (albumMeta ? " · " : "") + tracks.length + (tracks.length === 1 ? " track" : " tracks");
                }
                if (totalDuration) {
                    albumMeta += (albumMeta ? " · " : "") + formatDuration(totalDuration);
                }
                albumMeta += (albumMeta ? " · " : "") + "Tidal";
            }
            albumArtist.textContent = albumMeta;
            albumArtist.style.cursor  = "";
            albumArtist.onclick       = null;
            currentContext = context;
            if (currentViewEndpoint.indexOf("/tidal/playlist/") === 0) {
                currentContext.playlist_editable = respPlaylistEditable;
                if (respPlaylistName) {
                    currentContext.title = respPlaylistName;
                    albumTitle.textContent = respPlaylistName;
                }
            }
            originalTracks  = tracks;
            shuffledTracks  = [];
            // Store the displayed list for queue-building (used by playTrack and "+" buttons)
            currentViewTracks = originalTracks;

            // Make albumArtist clickable when we have an artist_id from the album response
            if (respArtistId) {
                currentContext.artist_id   = respArtistId;
                currentContext.artist_name = respArtistName;
                _wireAlbumArtistClick(respArtistId, respArtistName || context.artist || "");
            }

            if (albumTechInfo && tracks.length > 0) {
                var firstQuality = tracks[0].quality || null;
                if (firstQuality === "HI-RES") {
                    albumTechInfo.textContent = "HI-RES FLAC";
                    albumTechInfo.className   = "techInfoHiRes";
                } else if (firstQuality === "CD") {
                    albumTechInfo.textContent = "CD FLAC";
                    albumTechInfo.className   = "techInfoCD";
                } else {
                    albumTechInfo.classList.add("hidden");
                }
            }

            if (tracks.length === 0) {
                trackList.innerHTML = "";
                var msg = document.createElement("div");
                msg.className   = "unavailableMsg";
                msg.textContent = !Array.isArray(resp) && !resp.tracks ? "Could not load tracks." : "No tracks found.";
                trackList.appendChild(msg);
                renderAlbumQueueBtn(
                    [],
                    currentContext ? (currentContext.cover || "") : ""
                );
                if (shouldResetTrackListDetailScroll(currentViewEndpoint)) {
                    resetAlbumDetailScroll();
                }
                return;
            }

            renderTrackList(originalTracks);
            if (shouldResetTrackListDetailScroll(currentViewEndpoint)) {
                resetAlbumDetailScroll();
            }
            // Fetch fresh favorite state for this view
            loadFavoriteIds();
        })
        .catch(function(e) { console.error("loadTrackList failed:", e); });
}


// --- Popover (queue actions) ---

function closeActivePopover() {
    if (activePopover && activePopover.parentNode) {
        activePopover.parentNode.removeChild(activePopover);
    }
    activePopover = null;
}

function queueTracksContainLocal(tracksList) {
    return Array.isArray(tracksList) && tracksList.some(function(t) {
        return t && (String(t.source || "").toLowerCase() === "local" || String(t.id || "").indexOf("local:") === 0);
    });
}

function queueTracksAllLocal(tracksList) {
    return Array.isArray(tracksList) && tracksList.length > 0 && tracksList.every(function(t) {
        return t && (String(t.source || "").toLowerCase() === "local" || String(t.id || "").indexOf("local:") === 0);
    });
}

function queueTracksContainRadio(tracksList) {
    tracksList = Array.isArray(tracksList) ? tracksList : [];
    return tracksList.some(function(t) {
        return !!(t && (String(t.source || "").toLowerCase() === "radio" || String(t.id || "").indexOf("radio:station:") === 0));
    });
}

function queueTracksAllRadio(tracksList) {
    tracksList = Array.isArray(tracksList) ? tracksList : [];
    return !!tracksList.length && tracksList.every(function(t) {
        return !!(t && (String(t.source || "").toLowerCase() === "radio" || String(t.id || "").indexOf("radio:station:") === 0));
    });
}

function submitQueueTracks(tracksList, action) {
    resetTidalInfinitePlayGuard();
    var hasLocalTracks = queueTracksContainLocal(tracksList);
    var hasRadioTracks = queueTracksContainRadio(tracksList);
    if (hasRadioTracks && isRadioCurrentlyActive()) {
        showQueueActionToast("Clear the Radio station from the Play Queue before adding to it.", true);
        return;
    }
    if (!queueTracksAllLocal(tracksList) && !requireOnlineSource()) { return; }
    if (hasLocalTracks && isLocalLibraryMaintenance()) {
        showQueueActionToast("Local Music is rebuilding", true);
        return;
    }
    var endpoint = action === "next" ? "/tidal/queue/insert_next" : "/tidal/queue/append";
    fetchWithTimeout(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tracks: tracksList })
    }, 7000)
    .then(function(res) {
        if (!res.ok) { throw new Error("queue action failed"); }
        return res.json().catch(function() { return {}; });
    })
    .then(function(data) {
        if (data && (data.ok === false || data.offline || data.error)) {
            var backendMessage = playbackErrorMessage(data, ONLINE_SOURCE_OFFLINE_MESSAGE);
            if ((data && data.radio_mode) || String(backendMessage || "").indexOf("Clear the Radio station from the Play Queue before adding to it.") >= 0) {
                showQueueActionToast(backendMessage || "Clear the Radio station from the Play Queue before adding to it.", true);
                return;
            }
            throw new Error(backendMessage);
        }
        showQueueActionToast(queueActionSummary(action, tracksList), false);
    })
    .catch(function(err) {
        var message = normalizePlaybackErrorMessage(err) ||
            normalizePlaybackErrorMessage(ONLINE_SOURCE_OFFLINE_MESSAGE);
        if (message === DAC_PLAYBACK_ERROR_MESSAGE || String(message || "").indexOf("Clear the Radio station from the Play Queue before adding to it.") >= 0) {
            showQueueActionToast(message, true);
            return;
        }
        if (!queueTracksAllLocal(tracksList)) {
            handleOnlineSourceFailure(message);
            return;
        }
        showQueueActionToast("Queue action failed", true);
    });
}

function positionQueuePopover(anchorEl, popover) {
    if (!anchorEl || !popover) { return; }
    document.body.appendChild(popover);
    var rect = anchorEl.getBoundingClientRect();
    var top  = rect.bottom + window.scrollY + 4;
    var left = rect.left   + window.scrollX;
    var pw = popover.offsetWidth || 180;
    if (left + pw > window.innerWidth - 8) {
        left = window.innerWidth - pw - 8;
    }
    if (left < 8) {
        left = 8;
    }
    popover.style.top  = top  + "px";
    popover.style.left = left + "px";
    activePopover = popover;
}

function showQueuePopover(anchorEl, tracksList, e) {
    e.stopPropagation();
    closeActivePopover();
    var hasLocalTracks = queueTracksContainLocal(tracksList);
    var tidalTrackIds = hasLocalTracks ? [] : normalizeTidalTrackIds(tracksList);
    if (hasLocalTracks && isLocalLibraryMaintenance()) {
        showQueueActionToast("Local Music is rebuilding", true);
        return;
    }

    var popover = document.createElement("div");
    popover.className = "queuePopover";

    var btnNext = document.createElement("button");
    btnNext.className = "queuePopoverBtn";
    btnNext.innerHTML = '<span class="material-icons">queue_play_next</span> Play Next';
    btnNext.onclick = function(ev) {
        ev.stopPropagation();
        closeActivePopover();
        submitQueueTracks(tracksList, "next");
    };

    var btnAdd = document.createElement("button");
    btnAdd.className = "queuePopoverBtn";
    btnAdd.innerHTML = '<span class="material-icons">add_to_queue</span> Add to Queue';
    btnAdd.onclick = function(ev) {
        ev.stopPropagation();
        closeActivePopover();
        submitQueueTracks(tracksList, "queue");
    };

    popover.appendChild(btnNext);
    popover.appendChild(btnAdd);
    if (!hasLocalTracks && tidalTrackIds.length) {
        var btnPlaylist = document.createElement("button");
        btnPlaylist.className = "queuePopoverBtn";
        btnPlaylist.innerHTML = '<span class="material-icons">playlist_add</span> Add to Playlist';
        btnPlaylist.onclick = function(ev) {
            ev.stopPropagation();
            closeActivePopover();
            showAddToTidalPlaylistModal(tidalTrackIds);
        };
        popover.appendChild(btnPlaylist);
    }

    positionQueuePopover(anchorEl, popover);
}

// Dismiss popover on outside click
document.addEventListener("click", function() { closeActivePopover(); });


// --- Build a track payload object from a track row data ---

function buildTrackPayload(t, ctxCover) {
    var viewCover = ctxCover || (currentContext ? (currentContext.cover || "") : "") || "";
    var preferTrackCover = currentViewEndpoint && currentViewEndpoint.indexOf("/tidal/artist/") === 0;
    return {
        id:       t.id,
        title:    t.title   || "",
        artist:   t.artist  || (currentContext ? (currentContext.artist || "") : ""),
        cover:    preferTrackCover ? (t.cover || viewCover) : (viewCover || t.cover || ""),
        duration: t.duration || 0,
        quality:  t.quality  || ""
    };
}


// --- Track list render ---

function renderTrackList(tracks) {
    trackList.innerHTML = "";
    var hasArtist = tracks.some(function(t) { return t.artist && t.artist.length > 0; });
    if (hasArtist) { trackList.classList.add("trackListWide"); }
    else           { trackList.classList.remove("trackListWide"); }

    var ctxCover = currentContext ? (currentContext.cover || "") : "";
    var canRemoveFromPlaylist = currentViewEndpoint &&
        currentViewEndpoint.indexOf("/tidal/playlist/") === 0 &&
        previousView === "playlists" &&
        currentContext &&
        currentContext.id;

    tracks.forEach(function(track, idx) {
        trackMap[String(track.id)] = {
            title:    track.title  || "",
            artist:   track.artist || (currentContext ? (currentContext.artist || "") : ""),
            cover:    ctxCover || track.cover || "",
            duration: track.duration || 0
        };
        var row = document.createElement("div");
        row.className = (hasArtist ? "track trackWide" : "track") + (canRemoveFromPlaylist ? " playlistEditableTrack" : "");
        row.setAttribute("data-track-id", String(track.id));

        // Inner content columns (no "+" button inside the grid columns --
        // the "+" button is appended outside the grid as an overlay button)
        if (hasArtist) {
            row.innerHTML =
                '<div class="track-num">'    + (idx + 1)           + '</div>' +
                '<div class="track-title">'  + (track.title || "") + '</div>' +
                '<div class="track-artist">' + (track.artist || "") + '</div>' +
                '<div class="track-duration">' + formatTime(track.duration) + '</div>';
        } else {
            row.innerHTML =
                '<div class="track-num">'      + (idx + 1)              + '</div>' +
                '<div class="track-title">'    + (track.title || "")    + '</div>' +
                '<div class="track-duration">' + formatTime(track.duration) + '</div>';
        }

        // Heart (favorite) button -- always rendered; faved ones stay visible in red
        var heartBtn = document.createElement("button");
        heartBtn.className = "trackHeart";
        heartBtn.setAttribute("data-track-id", String(track.id));
        heartBtn.innerHTML = '<span class="material-icons">favorite_border</span>';
        heartBtn.title = "Favorite";
        (function(tid, btn) {
            btn.onclick = function(e) {
                e.stopPropagation();
                toggleTrackFavorite(tid, btn);
            };
        }(String(track.id), heartBtn));
        row.appendChild(heartBtn);

        // "+" button -- appended after the grid columns, positioned via CSS
        var addBtn = document.createElement("button");
        addBtn.className = "trackAddBtn";
        addBtn.innerHTML = '<span class="material-icons">add</span>';
        addBtn.title = "Add to queue";
        (function(t, btn) {
            btn.onclick = function(e) {
                e.stopPropagation();
                var payload = [buildTrackPayload(t, ctxCover)];
                showQueuePopover(btn, payload, e);
            };
        }(track, addBtn));
        row.appendChild(addBtn);

        if (canRemoveFromPlaylist) {
            var removeBtn = document.createElement("button");
            removeBtn.className = "trackRemoveBtn";
            removeBtn.innerHTML = '<span class="material-icons">delete</span>';
            removeBtn.title = "Remove from playlist";
            removeBtn.setAttribute("aria-label", "Remove from playlist");
            (function(t, btn, rowRef) {
                btn.onclick = function(e) {
                    e.stopPropagation();
                    showRemoveFromTidalPlaylistModal(t, rowRef);
                };
            }(track, removeBtn, row));
            row.appendChild(removeBtn);
        }

        // Row click = replace queue with from this track onwards
        (function(t, i) {
            row.onclick = function() { playTrack(t, i); };
        }(track, idx));

        trackList.appendChild(row);
    });
    highlightCurrentTrack();

    // Render queue-all button in album header (idempotent)
    renderAlbumQueueBtn(tracks, ctxCover);
}


// --- Album header queue buttons ---

function renderAlbumQueueBtn(tracks, ctxCover) {
    var existing = document.getElementById("albumQueueBtnGroup");
    if (existing) { existing.parentNode.removeChild(existing); }

    tracks = Array.isArray(tracks) ? tracks : [];
    var canRenamePlaylist =
        currentViewEndpoint.indexOf("/tidal/playlist/") === 0 &&
        currentContext &&
        currentContext.playlist_editable === true &&
        String(currentContext.id || "").trim();

    if (tracks.length === 0 && !canRenamePlaylist) { return; }

    var albumHeader = document.getElementById("albumHeader");
    if (!albumHeader) { return; }

    var group = document.createElement("div");
    group.id        = "albumQueueBtnGroup";
    group.className = "albumQueueBtnGroup";

    // Header heart -- album or artist only (no API for mixes/playlists)
    var heartType = "";
    var heartId   = "";
    if (currentViewEndpoint.indexOf("/tidal/album/") === 0) {
        heartType = "album";
        heartId   = currentContext ? String(currentContext.id || "") : "";
    } else if (currentViewEndpoint.indexOf("/tidal/artist/") === 0) {
        heartType = "artist";
        heartId   = currentContext ? String(currentContext.id || "") : "";
    }
    if (heartType && heartId) {
        var heartBtn = document.createElement("button");
        heartBtn.id        = "albumHeaderHeart";
        heartBtn.className = "albumQueueBtn";
        heartBtn.innerHTML = '<span class="material-icons">favorite_border</span>';
        heartBtn.title     = heartType === "album" ? "Favorite album" : "Favorite artist";
        heartBtn.setAttribute("data-heart-type", heartType);
        heartBtn.setAttribute("data-heart-id",   heartId);
        (function(htype, hid, btn) {
            btn.onclick = function(e) {
                e.stopPropagation();
                if (htype === "album")  { toggleAlbumFavorite(hid, btn); }
                if (htype === "artist") { toggleArtistFavorite(hid, btn); }
            };
        }(heartType, heartId, heartBtn));
        group.appendChild(heartBtn);
    }

    if (canRenamePlaylist) {
        var renameBtn = document.createElement("button");
        renameBtn.id = "playlistRenameBtn";
        renameBtn.className = "albumQueueBtn";
        renameBtn.innerHTML = '<span class="material-icons">edit</span>';
        renameBtn.title = "Rename playlist";
        renameBtn.setAttribute("aria-label", "Rename playlist");
        renameBtn.onclick = function(e) {
            e.stopPropagation();
            showCreateTidalPlaylistModal({
                title: "Rename Playlist",
                submitLabel: "Rename",
                busyLabel: "Renaming...",
                defaultName: currentContext.title || "",
                hideDescription: true,
                mode: "rename",
                playlistId: currentContext.id,
                editable: currentContext.playlist_editable === true
            });
        };
        group.appendChild(renameBtn);
    }

    if (tracks.length > 0) {
        var addBtn = document.createElement("button");
        addBtn.className = "albumQueueBtn";
        addBtn.innerHTML = '<span class="material-icons">playlist_add</span>';
        addBtn.title = "Add to queue";
        addBtn.onclick = function(e) {
            e.stopPropagation();
            var payload = tracks.map(function(t) {
                return buildTrackPayload(t, ctxCover);
            });
            showQueuePopover(addBtn, payload, e);
        };
        group.appendChild(addBtn);
    }

    // Save as Playlist button -- only in artist top-tracks view
    if (
        tracks.length > 0 &&
        currentViewEndpoint.indexOf("/tidal/artist/") === 0
    ) {
        var saveBtn = document.createElement("button");
        saveBtn.className = "albumQueueBtn";
        saveBtn.innerHTML = '<span class="material-icons">playlist_add_check</span>';
        saveBtn.title = "Save as Playlist";
        saveBtn.onclick = function(e) {
            e.stopPropagation();
            saveViewTracksAsPlaylist(tracks);
        };
        group.appendChild(saveBtn);
    }

    albumHeader.appendChild(group);
}

function openPip() {
    var features = "width=340,height=160,resizable=yes,scrollbars=no," +
                   "toolbar=no,menubar=no,location=no,status=no";
    window.open("/ui_web/pip.html", "srova_pip", features);
}

// --- VU Meter Panel (slide-up over Now Playing, replaces popup) ---

var _vuPanel        = null;
var _vuRafActive    = false;
var _vuSpecInterval = null;
var _vuBarInterval  = null;
var _vuBarSeekWired = false;
var _vuLastRafTs    = 0;
var _vuTargetDbL    = -70.0;
var _vuTargetDbR    = -70.0;

var VU_ATTACK_TC = 0.180;
var VU_DECAY_TC  = 0.260;
var VU_MIN_DB    = -20.0;
var VU_MAX_DB    =   3.0;
var VU_INPUT_SENSITIVITY = 0.75;

var _vuNeedleL = { angle: 0, vel: 0 };
var _vuNeedleR = { angle: 0, vel: 0 };

function openVuPanel() {
    // Desktop (>= 1025px): open the dedicated popup window as before
    if (window.innerWidth >= 1025) {
        var features = "width=960,height=620,resizable=yes,scrollbars=no," +
                       "toolbar=no,menubar=no,location=no,status=no";
        window.open("/ui_web/vu.html", "srova_vu", features);
        return;
    }
    // Mobile / tablet: slide-up panel
    if (!_vuPanel) { _vuPanel = document.getElementById("vuPanel"); }
    if (!_vuPanel) { return; }
    if (metaPanel   && metaPanel.classList.contains("open"))   { closeMetaPanel(); }
    if (lyricsPanel && lyricsPanel.classList.contains("open")) { closeLyricsPanel(); }
    _vuPanel.classList.add("open");
    _vuSyncBar();
    setTimeout(function() { _vuResizeCanvases(); }, 50);
    setTimeout(function() { _vuResizeCanvases(); }, 260);
    if (!_vuRafActive) {
        _vuRafActive = true;
        _vuLastRafTs = 0;
        requestAnimationFrame(_vuRafLoop);
    }
    if (!_vuSpecInterval) {
        _vuSpecInterval = setInterval(_vuPollSpectrum, 40);
    }
    if (!_vuBarInterval) {
        _vuBarInterval = setInterval(_vuSyncBar, 2000);
    }
    // Wire seek on panel progress bar once
    if (!_vuBarSeekWired) {
        _vuBarSeekWired = true;
        var bar = document.getElementById("vpbProgressBar");
        if (bar) {
            bar.addEventListener("click", function(e) {
                if (!currentDuration) { return; }
                var rect    = bar.getBoundingClientRect();
                var pct     = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                var seekSec = Math.floor(pct * currentDuration);
                requestSeekTo(seekSec);
            });
        }
    }
}

function closeVuPanel() {
    if (!_vuPanel) { _vuPanel = document.getElementById("vuPanel"); }
    if (_vuPanel)  { _vuPanel.classList.remove("open"); }
    _vuRafActive = false;
    if (_vuSpecInterval) { clearInterval(_vuSpecInterval); _vuSpecInterval = null; }
    if (_vuBarInterval)  { clearInterval(_vuBarInterval);  _vuBarInterval  = null; }
}

function _vuSyncBar() {
    var art    = document.getElementById("vpbArt");
    var track  = document.getElementById("vpbTrack");
    var artist = document.getElementById("vpbArtist");
    var total  = document.getElementById("vpbTotal");
    var badge  = document.getElementById("vpbBadge");
    var btn    = document.getElementById("vpbBtnPlay");
    if (art)    { art.src            = playerArt.src            || ""; }
    if (track)  { track.textContent  = playerTrack.textContent  || ""; }
    if (artist) { artist.textContent = playerArtist.textContent || ""; }
    if (total)  { total.textContent  = totalTimeEl.textContent  || "0:00"; }
    if (badge) {
        if (lastTechText) {
            badge.textContent = lastTechText;
            badge.className   = lastTechClass;
        } else {
            badge.className = "hidden";
        }
    }
    if (btn) {
        _setPlayIconButton(btn, playing);
    }
}

function _vuResizeCanvases() {
    var wraps = document.querySelectorAll(".vuMeterWrap");
    for (var i = 0; i < wraps.length; i++) {
        var c = wraps[i].querySelector("canvas");
        if (!c) { continue; }
        var rect = wraps[i].getBoundingClientRect();
        var w = Math.max(1, Math.round(rect.width || wraps[i].clientWidth || 0));
        var h = Math.max(1, Math.round(rect.height || wraps[i].clientHeight || 0));
        if (c.width !== w) { c.width = w; }
        if (c.height !== h) { c.height = h; }
    }
}

function _vuDbToAngle(db) {
    var dbc = Math.max(VU_MIN_DB, Math.min(VU_MAX_DB, db));
    var t   = (dbc - VU_MIN_DB) / (VU_MAX_DB - VU_MIN_DB);
    return (t - 0.5) * 100.0 * Math.PI / 180.0;
}

function _vuClamp(value, lo, hi) {
    value = Number(value);
    if (!isFinite(value)) { return lo; }
    return Math.max(lo, Math.min(hi, value));
}

function _vuDbToMeter(db, floorDb, ceilingDb) {
    db = Number(db);
    if (!isFinite(db)) { return 0; }
    return _vuClamp((db - floorDb) / (ceilingDb - floorDb), 0, 1);
}

function _vuSpectrumToTargetDb(rmsDb, peakDb) {
    var rmsMeter  = _vuDbToMeter(rmsDb,  -62, -42);
    var peakMeter = _vuDbToMeter(peakDb, -58, -28);
    var meter = (rmsMeter * 0.72) + (peakMeter * 0.28);
    meter *= VU_INPUT_SENSITIVITY;
    return VU_MIN_DB + meter * (VU_MAX_DB - VU_MIN_DB);
}

function _vuUpdateNeedle(n, targetDb, dt) {
    var targetAngle = _vuDbToAngle(targetDb);
    var tc      = targetAngle > n.angle ? VU_ATTACK_TC : VU_DECAY_TC;
    var k       = 1.0 / tc;
    var damping = 1.9;
    var spring  = k * k;
    var err     = targetAngle - n.angle;
    n.vel   += (spring * err - damping * k * n.vel) * dt;
    n.angle += n.vel * dt;
    var minA = _vuDbToAngle(VU_MIN_DB - 2);
    var maxA = _vuDbToAngle(VU_MAX_DB + 0.5);
    if (n.angle < minA) { n.angle = minA; n.vel = 0; }
    if (n.angle > maxA) { n.angle = maxA; n.vel = 0; }
}

function _vuRoundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y,     x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

function _vuDraw(canvasId, needle, label) {
    var canvas = document.getElementById(canvasId);
    if (!canvas || !canvas.width || !canvas.height) { return; }
    var w   = canvas.width;
    var h   = canvas.height;
    var ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, w, h);

    var s = Math.min(w, h);
    var r = s * 0.045;
    var cx = w * 0.50;
    var cy = h * 0.78;
    var arc = s * 0.58;

    ctx.save();
    _vuRoundRect(ctx, 0, 0, w, h, r);
    ctx.clip();

    var caseBg = ctx.createLinearGradient(0, 0, 0, h);
    caseBg.addColorStop(0, "#8e4212");
    caseBg.addColorStop(0.46, "#c76318");
    caseBg.addColorStop(0.72, "#9a4713");
    caseBg.addColorStop(0.88, "#261007");
    caseBg.addColorStop(1, "#050505");
    ctx.fillStyle = caseBg;
    ctx.fillRect(0, 0, w, h);

    var dialGlow = ctx.createRadialGradient(cx, h * 0.42, s * 0.10, cx, h * 0.46, s * 0.78);
    dialGlow.addColorStop(0, "#ffd06f");
    dialGlow.addColorStop(0.42, "#f6a13a");
    dialGlow.addColorStop(0.76, "#cf721f");
    dialGlow.addColorStop(1, "#874011");
    ctx.fillStyle = dialGlow;
    ctx.beginPath();
    ctx.arc(cx, cy, arc * 1.08, Math.PI * 1.03, Math.PI * 1.97, false);
    ctx.lineTo(w, 0);
    ctx.lineTo(0, 0);
    ctx.closePath();
    ctx.fill();

    var faceShade = ctx.createLinearGradient(0, 0, 0, h);
    faceShade.addColorStop(0, "rgba(255,232,144,0.24)");
    faceShade.addColorStop(0.46, "rgba(255,156,38,0.00)");
    faceShade.addColorStop(0.74, "rgba(0,0,0,0.02)");
    faceShade.addColorStop(1, "rgba(0,0,0,0.32)");
    ctx.fillStyle = faceShade;
    ctx.fillRect(0, 0, w, h);

    var faceLift = ctx.createRadialGradient(cx, h * 0.53, s * 0.05, cx, h * 0.53, s * 0.46);
    faceLift.addColorStop(0, "rgba(255,173,58,0.28)");
    faceLift.addColorStop(0.66, "rgba(255,145,35,0.12)");
    faceLift.addColorStop(1, "rgba(255,145,35,0.00)");
    ctx.fillStyle = faceLift;
    ctx.fillRect(0, 0, w, h);

    ctx.beginPath();
    ctx.arc(cx, cy, arc * 1.11, Math.PI * 1.04, Math.PI * 1.96);
    ctx.strokeStyle = "rgba(0,0,0,0.28)";
    ctx.lineWidth = s * 0.026;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(cx, cy, arc * 1.06, Math.PI * 1.05, Math.PI * 1.95);
    ctx.strokeStyle = "rgba(255,184,67,0.18)";
    ctx.lineWidth = s * 0.012;
    ctx.stroke();

    // Scale arc background
    ctx.beginPath();
    ctx.arc(cx, cy, arc * 0.84, Math.PI * 1.13, Math.PI * 1.87);
    ctx.strokeStyle = "rgba(0,0,0,0.13)";
    ctx.lineWidth = s * 0.018;
    ctx.stroke();

    // Major scale marks
    var marks = [
        { db: -20, label: "20" }, { db: -10, label: "10" },
        { db:  -7, label:  "7" }, { db:  -5, label:  "5" },
        { db:  -3, label:  "3" }, { db:  -2, label:  "2" },
        { db:   0, label:  "0" }, { db:   3, label:  "3" }
    ];
    var innerR = arc * 0.73;
    var outerR = arc * 0.88;
    var labelR = arc * 0.64;
    var fs = Math.max(8, s * 0.040);
    ctx.textAlign    = "center";
    ctx.textBaseline = "middle";
    for (var i = 0; i < marks.length; i++) {
        var m    = marks[i];
        var ang  = _vuDbToAngle(m.db) - Math.PI * 0.5;
        var red  = m.db >= 0;
        var cosA = Math.cos(ang);
        var sinA = Math.sin(ang);
        ctx.beginPath();
        ctx.moveTo(cx + innerR * cosA, cy + innerR * sinA);
        ctx.lineTo(cx + outerR * cosA, cy + outerR * sinA);
        ctx.strokeStyle = red ? "#9d211b" : "#090604";
        ctx.lineWidth = red ? s * 0.009 : s * 0.008;
        ctx.stroke();
        ctx.font = "800 " + fs + "px sans-serif";
        ctx.fillStyle = red ? "#9d211b" : "#090604";
        ctx.fillText(m.label, cx + labelR * cosA, cy + labelR * sinA);
    }

    // Minor ticks
    var minorDbs = [-15, -9, -8, -6, -4, -0.5, 0.5, 1.5, 2.5];
    for (var j = 0; j < minorDbs.length; j++) {
        var ang2 = _vuDbToAngle(minorDbs[j]) - Math.PI * 0.5;
        ctx.beginPath();
        ctx.moveTo(cx + arc * 0.78 * Math.cos(ang2), cy + arc * 0.78 * Math.sin(ang2));
        ctx.lineTo(cx + arc * 0.88 * Math.cos(ang2), cy + arc * 0.88 * Math.sin(ang2));
        ctx.strokeStyle = minorDbs[j] >= 0 ? "#9d211b" : "#0b0704";
        ctx.lineWidth = s * 0.005;
        ctx.stroke();
    }

    // Red overload zone
    ctx.beginPath();
    var ang0 = _vuDbToAngle(0)         - Math.PI * 0.5;
    var ang3 = _vuDbToAngle(VU_MAX_DB) - Math.PI * 0.5;
    ctx.arc(cx, cy, arc * 0.96, ang0, ang3);
    ctx.strokeStyle = "rgba(154,32,26,0.88)";
    ctx.lineWidth = s * 0.015;
    ctx.stroke();

    // VU label
    ctx.font = "800 " + Math.max(18, s * 0.092) + "px sans-serif";
    ctx.fillStyle = "#100804";
    ctx.textAlign = "center";
    ctx.fillText("VU", cx, h * 0.51);

    // Channel label
    ctx.font = "800 " + Math.max(12, s * 0.052) + "px sans-serif";
    ctx.fillStyle = "rgba(42,20,4,0.82)";
    ctx.textAlign = "right";
    ctx.fillText(label, w * 0.90, h * 0.56);

    ctx.fillStyle = "rgba(8,5,4,0.78)";
    ctx.beginPath();
    ctx.arc(cx, cy + s * 0.02, s * 0.22, Math.PI, Math.PI * 2, false);
    ctx.lineTo(cx + s * 0.26, h);
    ctx.lineTo(cx - s * 0.26, h);
    ctx.closePath();
    ctx.fill();

    ctx.fillStyle = "rgba(160,30,24,0.50)";
    ctx.beginPath();
    ctx.arc(cx - s * 0.15, cy + s * 0.025, s * 0.042, Math.PI, Math.PI * 2);
    ctx.arc(cx + s * 0.15, cy + s * 0.025, s * 0.042, Math.PI, Math.PI * 2);
    ctx.fill();

    // Needle
    var needleLen = arc * 0.86;
    var nAng      = needle.angle - Math.PI * 0.5;
    var nx        = cx + needleLen * Math.cos(nAng);
    var ny        = cy + needleLen * Math.sin(nAng);
    ctx.beginPath();
    ctx.moveTo(cx + s * 0.004, cy + s * 0.004);
    ctx.lineTo(nx + s * 0.008, ny + s * 0.008);
    ctx.strokeStyle = "rgba(0,0,0,0.38)";
    ctx.lineWidth = Math.max(1, s * 0.006);
    ctx.lineCap = "round";
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(nx, ny);
    ctx.strokeStyle = "#070707";
    ctx.lineWidth = Math.max(1, s * 0.005);
    ctx.lineCap = "round";
    ctx.stroke();

    // Pivot hardware
    var hub = ctx.createRadialGradient(cx - s * 0.025, cy - s * 0.030, s * 0.005, cx, cy, s * 0.085);
    hub.addColorStop(0, "#ffd282");
    hub.addColorStop(0.20, "#b86b20");
    hub.addColorStop(0.55, "#3a2112");
    hub.addColorStop(1, "#050505");
    ctx.fillStyle = hub;
    ctx.beginPath();
    ctx.arc(cx, cy, s * 0.078, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,0.85)";
    ctx.lineWidth = s * 0.010;
    ctx.stroke();
    ctx.fillStyle = "rgba(255,204,112,0.80)";
    ctx.beginPath();
    ctx.arc(cx - s * 0.022, cy - s * 0.026, s * 0.012, 0, Math.PI * 2);
    ctx.fill();

    // Glass reflection
    var gloss = ctx.createLinearGradient(0, 0, 0, h * 0.5);
    gloss.addColorStop(0, "rgba(255,255,255,0.20)");
    gloss.addColorStop(0.40, "rgba(255,255,255,0.050)");
    gloss.addColorStop(1, "rgba(255,255,255,0.00)");
    ctx.fillStyle = gloss;
    _vuRoundRect(ctx, 0, 0, w, h * 0.5, r);
    ctx.fill();

    var sweep = ctx.createLinearGradient(0, 0, w, h);
    sweep.addColorStop(0, "rgba(255,255,255,0.00)");
    sweep.addColorStop(0.48, "rgba(255,255,255,0.055)");
    sweep.addColorStop(1, "rgba(255,255,255,0.00)");
    ctx.fillStyle = sweep;
    ctx.fillRect(0, 0, w, h);

    ctx.restore();

    // Outer bezel
    ctx.strokeStyle = "rgba(0,0,0,0.88)";
    ctx.lineWidth = s * 0.020;
    _vuRoundRect(ctx, 0, 0, w, h, r);
    ctx.stroke();
    ctx.strokeStyle = "rgba(240,178,70,0.16)";
    ctx.lineWidth = Math.max(1, s * 0.004);
    _vuRoundRect(ctx, s * 0.014, s * 0.014, w - s * 0.028, h - s * 0.028, r * 0.72);
    ctx.stroke();
}

function _vuRafLoop(ts) {
    if (!_vuRafActive) { return; }
    var dt       = _vuLastRafTs > 0 ? Math.min((ts - _vuLastRafTs) / 1000.0, 0.1) : 0.016;
    _vuLastRafTs = ts;
    _vuUpdateNeedle(_vuNeedleL, _vuTargetDbL, dt);
    _vuUpdateNeedle(_vuNeedleR, _vuTargetDbR, dt);
    _vuDraw("vuCanvasL", _vuNeedleL, "L");
    _vuDraw("vuCanvasR", _vuNeedleR, "R");
    // Update panel player bar progress
    var vpbFill = document.getElementById("vpbFill");
    var vpbCur  = document.getElementById("vpbCurrent");
    var vpbBtn  = document.getElementById("vpbBtnPlay");
    if (vpbFill && currentDuration > 0) {
        var el  = playing ? (Date.now() / 1000 - startTime) : (progressFill._elapsed || 0);
        el      = Math.max(0, Math.min(el, currentDuration));
        var pct = (el / currentDuration) * 100;
        vpbFill.style.width = pct + "%";
        if (vpbCur) { vpbCur.textContent = formatTime(el); }
    }
    if (vpbBtn) {
        _setPlayIconButton(vpbBtn, playing);
    }
    requestAnimationFrame(_vuRafLoop);
}

function _vuPollSpectrum() {
    fetch("/spectrum")
        .then(function(r) { return r.json(); })
        .then(function(d) {
            _vuTargetDbL = _vuSpectrumToTargetDb(d.left_rms, d.left_peak);
            _vuTargetDbR = _vuSpectrumToTargetDb(d.right_rms, d.right_peak);
        })
        .catch(function() {});
}

window.addEventListener("resize", function() {
    if (_vuPanel && _vuPanel.classList.contains("open")) { _vuResizeCanvases(); }
});

function saveViewTracksAsPlaylist(tracks) {
    var ids = [];
    for (var i = 0; i < tracks.length; i++) {
        if (tracks[i].id) { ids.push(String(tracks[i].id)); }
    }
    ids = normalizeTidalTrackIds(ids);
    if (ids.length === 0) {
        showQueueActionToast("No valid TIDAL track id", true);
        return;
    }
    showCreateTidalPlaylistModal({
        title: "Save as Playlist",
        submitLabel: "Save",
        hideDescription: true,
        mode: "tracks",
        trackIds: ids
    });
}


// --- Play track from album/detail view using full context queue ---

function playTrack(track, idx) {
    if (currentViewEndpoint && currentViewEndpoint.indexOf("/tidal/") === 0 && !requireOnlineSource()) { return; }
    clearRadioIdleStandbyTimer();
    resetTidalInfinitePlayGuard();
    var ctxCover = currentContext ? (currentContext.cover || "") : "";
    var tracks   = currentViewTracks;
    var payload  = [];
    for (var i = 0; i < tracks.length; i++) {
        payload.push(buildTrackPayload(tracks[i], ctxCover));
    }
    if (payload.length === 0) { return; }
    idx = Math.max(0, Math.min(Number(idx || 0), payload.length - 1));
    for (var markerIdx = 0; markerIdx < payload.length; markerIdx++) {
        payload[markerIdx]._srova_context_direct_start = true;
        payload[markerIdx]._srova_display_start_index = idx;
    }

    // Determine context type from current endpoint
    var ctxType  = "";
    var ctxId    = "";
    var ctxTitle = currentContext ? (currentContext.title || "") : "";
    if (currentViewEndpoint.indexOf("/tidal/album/")    === 0) {
        ctxType = "album";
        ctxId   = currentContext ? String(currentContext.id || "") : "";
    } else if (currentViewEndpoint.indexOf("/tidal/playlist/") === 0) {
        ctxType = "playlist";
        ctxId   = currentContext ? String(currentContext.id || "") : "";
    } else if (currentViewEndpoint.indexOf("/tidal/mix/")      === 0) {
        ctxType = "mix";
        ctxId   = currentContext ? String(currentContext.id || "") : "";
    } else if (currentViewEndpoint.indexOf("/tidal/artist/")   === 0) {
        ctxType = "artist";
        ctxId   = currentContext ? String(currentContext.id || "") : "";
    }
    _setPlaybackSource(ctxType || "album", ctxId, ctxTitle);

    postTidalQueueReplace({
        tracks:        payload,
        start_index:   idx,
        context_type:  ctxType,
        context_id:    ctxId,
        context_title: ctxTitle
    }).catch(function() {});
}


// --- Progress bar ---

function updateProgress() {
    if (!playing) { return; }
    if (lastKnownPlaybackStatus && isRadioLiveStatus(lastKnownPlaybackStatus)) { return; }
    var elapsed = Date.now() / 1000 - startTime;
    if (currentDuration <= 0) { return; }
    var displayElapsed = Math.min(elapsed, currentDuration);
    var pct = Math.min((displayElapsed / currentDuration) * 100, 100);
    progressFill.style.width  = pct + "%";
    progressFill._elapsed     = displayElapsed;
    currentTimeEl.textContent = formatTime(displayElapsed);
    if (nowPlayingFill) {
        nowPlayingFill.style.width      = pct + "%";
        nowPlayingCurrent.textContent   = formatTime(displayElapsed);
        nowPlayingTotal.textContent     = formatTime(currentDuration);
    }
}

function progressLoop() { updateProgress(); requestAnimationFrame(progressLoop); }
progressLoop();


// --- Seek on progress bar click ---

function handleSeekResponse(data, requestedPosition) {
    data = data || {};
    if (!data.ok && data.result !== "ok") {
        seekInFlight = false;
        pollStatus();
        return;
    }
    if (typeof data.duration === "number" && data.duration > 0) {
        currentDuration = data.duration;
        totalTimeEl.textContent = formatTime(currentDuration);
    }
    if (data.current_track_id) {
        currentPlayingId = String(data.current_track_id);
    }
    var nextPosition = (typeof data.position === "number") ? data.position : requestedPosition;
    setSeekSessionGuard(data.current_track_id || currentPlayingId, nextPosition);
    applyPlaybackPosition(nextPosition, !!data.playing);
    seekInFlight = false;
    setTimeout(pollStatus, 350);
}

function requestSeekTo(seekSec) {
    if (lastKnownPlaybackStatus && isRadioLiveStatus(lastKnownPlaybackStatus)) {
        skipRadioRestoreSeek();
        return;
    }
    if (!currentDuration || currentDuration <= 0) { return; }
    var target = Math.max(0, Math.min(Math.floor(Number(seekSec || 0)), Math.floor(currentDuration)));
    seekInFlight = true;
    fetch("/tidal/seek/" + target)
        .then(function(res) { return res.json(); })
        .then(function(data) { handleSeekResponse(data, target); })
        .catch(function() {
            seekInFlight = false;
            pollStatus();
        });
}

function seekToPosition(e) {
    if (lastKnownPlaybackStatus && isRadioLiveStatus(lastKnownPlaybackStatus)) {
        skipRadioRestoreSeek();
        return;
    }
    if (!currentDuration || currentDuration <= 0) { return; }
    var targetEl = (e.currentTarget && e.currentTarget.getBoundingClientRect) ? e.currentTarget : progressBar;
    var rect    = targetEl.getBoundingClientRect();
    var touch   = e.touches && e.touches.length ? e.touches[0] : (e.changedTouches && e.changedTouches.length ? e.changedTouches[0] : null);
    var clickX  = ((touch ? touch.clientX : e.clientX) || 0) - rect.left;
    var pct     = Math.max(0, Math.min(1, clickX / rect.width));
    var seekSec = Math.floor(pct * currentDuration);
    requestSeekTo(seekSec);
}

if (progressBar) {
    progressBar.addEventListener("click",     seekToPosition);
    progressBar.addEventListener("touchend",  seekToPosition);
}

if (nowPlayingProgress) {
    nowPlayingProgress.addEventListener("click",    seekToPosition);
    nowPlayingProgress.addEventListener("touchend", seekToPosition);
}


// --- Queue view ---

function loadQueue(options) {
    if (!queueView) { return; }
    options = options || {};

    var preserveScroll = options.preserveScroll === true;
    var preservedScroller = preserveScroll ? getSrovaBestScrollContainer(queueView) : null;
    var preservedScrollTop = preserveScroll ? getSrovaElementScrollTop(preservedScroller) : 0;

    fetch("/tidal/queue")
        .then(function(res) { return res.json(); })
        .then(function(data) {
            renderQueue(data, {skipAutoPosition: preserveScroll});

            if (preserveScroll) {
                requestAnimationFrame(function() {
                    setSrovaElementScrollTop(preservedScroller, preservedScrollTop);
                });
            }
        })
        .catch(function() {
            queueView.innerHTML = '<div class="queueEmpty">Could not load queue.</div>';
        });
}

function autoPositionPlayQueueOnCurrent(npRow) {
    if (!npRow || !queueView) { return; }
    requestAnimationFrame(function() {
        var scroller = getSrovaBestScrollContainer(queueView);
        var rowH = npRow.offsetHeight || 68;
        var rowTop = getSrovaElementTopInScroller(npRow, scroller);
        var viewportH = (scroller && scroller.clientHeight) || window.innerHeight || 0;
        var scrollH = (scroller && scroller.scrollHeight) || Math.max(document.body.scrollHeight || 0, document.documentElement.scrollHeight || 0);
        var maxTop = Math.max(0, scrollH - viewportH);
        var target = rowTop - (rowH * 3) - 36;
        setSrovaElementScrollTop(scroller, Math.min(maxTop, Math.max(0, target)));
    });
}

function renderQueue(data, options) {
    if (!queueView) { return; }
    options = options || {};
    var tracks     = data.tracks     || [];
    var queueIndex = data.queue_index || 0;
    var displayStartIndex = 0;
    if (tracks.length > 0) {
        var markerTrack = tracks[Math.max(0, Math.min(queueIndex, tracks.length - 1))] || tracks[0] || {};
        if (markerTrack && markerTrack._srova_context_direct_start) {
            displayStartIndex = Number(markerTrack._srova_display_start_index || 0);
        } else if (tracks[0] && tracks[0]._srova_context_direct_start) {
            displayStartIndex = Number(tracks[0]._srova_display_start_index || 0);
        }
        if (!isFinite(displayStartIndex)) { displayStartIndex = 0; }
        displayStartIndex = Math.max(0, Math.min(displayStartIndex, tracks.length - 1));
        if (displayStartIndex > queueIndex) { displayStartIndex = queueIndex; }
    }
    queueView.innerHTML = "";

    // ---- Single sticky header: back + title + all controls ---------------
    var bar = document.createElement("div");
    bar.className = "queueBar";

    var backBtn = document.createElement("button");
    backBtn.className = "queueBackBtn";
    backBtn.innerHTML = '<span class="material-icons">arrow_back</span>';
    backBtn.onclick   = function() { goBackFromQueue(); };

    var titleEl = document.createElement("div");
    titleEl.className   = "queueHeaderTitle";
    titleEl.textContent = "Play Queue";

    var repBtn = document.createElement("button");
    repBtn.className = "queueCtrlBtn" + (repeatMode !== "off" ? " active" : "");
    repBtn.title = "Repeat";
    repBtn.innerHTML = '<span class="material-icons">' + (repeatMode === "one" ? "repeat_one" : "repeat") + '</span>';
    repBtn.onclick = function() { toggleRepeat(); setTimeout(loadQueue, 200); };

    var shufBtn = document.createElement("button");
    shufBtn.className = "queueCtrlBtn" + (shuffleOn ? " active" : "");
    shufBtn.title = "Shuffle";
    shufBtn.innerHTML = '<span class="material-icons">shuffle</span>';
    shufBtn.onclick = function() { toggleShuffle(); setTimeout(loadQueue, 200); };

    var saveBtn = document.createElement("button");
    saveBtn.className   = "queueCtrlBtn queueCtrlText";
    saveBtn.textContent = "Save";
    saveBtn.title       = "Save as Playlist";
    saveBtn.onclick = function() {
        showCreateTidalPlaylistModal({
            title: "Save Queue as Playlist",
            submitLabel: "Save",
            hideDescription: true,
            mode: "queue"
        });
    };

    var clearUpBtn = document.createElement("button");
    clearUpBtn.className   = "queueCtrlBtn queueCtrlText";
    clearUpBtn.textContent = "Clear";
    clearUpBtn.title       = "Clear Upcoming";
    clearUpBtn.onclick = function() {
        fetch("/tidal/queue/clear/upcoming").then(function() { loadQueue(); });
    };

    var clearAllBtn = document.createElement("button");
    clearAllBtn.className   = "queueCtrlBtn queueCtrlText queueCtrlDanger";
    clearAllBtn.textContent = "Clear All";
    clearAllBtn.onclick = function() {
        fetch("/tidal/queue/clear").then(function() {
            loadQueue();
            applyStandbyPlayerBar();
            pollStatus();
        });
    };

    bar.appendChild(backBtn);
    bar.appendChild(titleEl);
    bar.appendChild(repBtn);
    bar.appendChild(shufBtn);
    bar.appendChild(saveBtn);
    bar.appendChild(clearUpBtn);
    bar.appendChild(clearAllBtn);
    queueView.appendChild(bar);

    if (tracks.length === 0) {
        var empty = document.createElement("div");
        empty.className   = "queueEmpty";
        empty.textContent = "Queue is empty.";
        queueView.appendChild(empty);
        return;
    }

    // ---- Earlier in Album/Context section -------------------------------
    var earlierEnd = Math.min(displayStartIndex, queueIndex);
    if (earlierEnd > 0) {
        var earlierHeader = document.createElement("div");
        earlierHeader.className   = "queueSectionHeader";
        earlierHeader.textContent = "Earlier in Album";
        queueView.appendChild(earlierHeader);
        for (var e = 0; e < earlierEnd; e++) {
            queueView.appendChild(buildQueueRow(tracks[e], e, false, false));
        }
    }

    // ---- Previously Played section ---------------------------------------
    if (queueIndex > displayStartIndex) {
        var ppHeader = document.createElement("div");
        ppHeader.className   = "queueSectionHeader";
        ppHeader.textContent = "Previously Played";
        queueView.appendChild(ppHeader);
        for (var p = displayStartIndex; p < queueIndex; p++) {
            queueView.appendChild(buildQueueRow(tracks[p], p, false, true));
        }
    }

    // ---- Now Playing section --------------------------------------------
    if (queueIndex < tracks.length) {
        var npHeader = document.createElement("div");
        npHeader.className   = "queueSectionHeader";
        npHeader.textContent = "Now Playing";
        queueView.appendChild(npHeader);
        var npRow = buildQueueRow(tracks[queueIndex], queueIndex, true, false);
        queueView.appendChild(npRow);
        if (!options.skipAutoPosition) {
            autoPositionPlayQueueOnCurrent(npRow);
        }
    }

    // ---- Up Next section ------------------------------------------------
    var upcoming = tracks.slice(queueIndex + 1);
    if (upcoming.length > 0) {
        var totalSecs = 0;
        for (var u = 0; u < upcoming.length; u++) {
            totalSecs += upcoming[u].duration || 0;
        }
        var unHeader = document.createElement("div");
        unHeader.className = "queueSectionHeader queueSectionHeaderRow";
        var unLabel = document.createElement("span");
        unLabel.textContent = "Up Next";
        var unTime = document.createElement("span");
        unTime.className   = "queueUpNextTime";
        unTime.textContent = formatDuration(totalSecs) + " remaining";
        unHeader.appendChild(unLabel);
        unHeader.appendChild(unTime);
        queueView.appendChild(unHeader);
        for (var i = 0; i < upcoming.length; i++) {
            queueView.appendChild(buildQueueRow(upcoming[i], queueIndex + 1 + i, false, false, true));
        }
    }
}

function persistUpcomingQueueMove(fromIndex, toIndex) {
    return fetch("/tidal/queue/reorder", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({from_index: fromIndex, to_index: toIndex})
    })
    .then(function(res) { return res.json().catch(function() { return {}; }); })
    .then(function(data) {
        if (!data || data.ok === false || data.error) {
            throw new Error((data && data.error) || "Could not reorder the Play Queue.");
        }
        return data;
    });
}

function enableUpcomingQueueDrag(row, handle, absIdx) {
    row.setAttribute("data-queue-reorderable", "true");
    row.setAttribute("data-queue-index", String(absIdx));

    function moveByKeyboard(direction) {
        var destination = absIdx + direction;
        var target = queueView.querySelector(
            '.queueRow[data-queue-reorderable="true"][data-queue-index="' +
            String(destination) + '"]'
        );
        if (!target) { return; }
        handle.disabled = true;
        persistUpcomingQueueMove(absIdx, destination)
            .then(function() {
                loadQueue({preserveScroll: true});
            })
            .catch(function(err) {
                loadQueue({preserveScroll: true});
                showQueueActionToast(err.message || "Could not reorder the Play Queue.", true);
            });
    }

    handle.addEventListener("keydown", function(e) {
        var direction = 0;
        if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
            direction = -1;
        } else if (e.key === "ArrowDown" || e.key === "ArrowRight") {
            direction = 1;
        }
        if (!direction) { return; }
        e.preventDefault();
        e.stopPropagation();
        moveByKeyboard(direction);
    });

    handle.addEventListener("click", function(e) {
        e.preventDefault();
        e.stopPropagation();
    });

    handle.addEventListener("pointerdown", function(e) {
        if (e.isPrimary === false || (e.pointerType === "mouse" && e.button !== 0)) {
            return;
        }
        e.preventDefault();
        e.stopPropagation();

        var parent = row.parentNode;
        if (!parent) { return; }
        var rect = row.getBoundingClientRect();
        var originalStyle = row.getAttribute("style");
        var originalIndexes = Array.prototype.map.call(
            parent.querySelectorAll('.queueRow[data-queue-reorderable="true"]'),
            function(item) { return Number(item.getAttribute("data-queue-index")); }
        ).sort(function(a, b) { return a - b; });
        var placeholder = document.createElement("div");
        placeholder.className = "queueRow queueDragPlaceholder";
        placeholder.setAttribute("aria-hidden", "true");
        placeholder.style.setProperty("--queue-placeholder-height", String(rect.height) + "px");
        parent.insertBefore(placeholder, row);

        var pointerId = e.pointerId;
        var offsetX = e.clientX - rect.left;
        var offsetY = e.clientY - rect.top;
        var dragScroller = getSrovaBestScrollContainer(queueView);
        var lastPointerX = e.clientX;
        var lastPointerY = e.clientY;
        var edgeScrollFrame = 0;
        var edgeScrollThreshold = 72;
        var edgeScrollMaxStep = 18;

        row.style.setProperty("--queue-drag-left", String(rect.left) + "px");
        row.style.setProperty("--queue-drag-top", String(rect.top) + "px");
        row.style.setProperty("--queue-drag-width", String(rect.width) + "px");
        row.style.setProperty("--queue-drag-height", String(rect.height) + "px");
        row.style.setProperty("width", String(rect.width) + "px", "important");
        row.style.setProperty("min-width", String(rect.width) + "px", "important");
        row.style.setProperty("max-width", String(rect.width) + "px", "important");
        row.style.setProperty("height", String(rect.height) + "px", "important");
        row.style.setProperty("min-height", String(rect.height) + "px", "important");
        row.style.setProperty("max-height", String(rect.height) + "px", "important");
        row.classList.add("is-queue-dragging");
        document.body.classList.add("is-queue-reordering-drag");

        function movePlaceholder(moveEvent) {
            var reorderableRows = Array.prototype.filter.call(
                parent.querySelectorAll('.queueRow[data-queue-reorderable="true"]'),
                function(item) { return item !== row; }
            );
            if (!reorderableRows.length) { return; }

            var hit = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY);
            var target = hit && hit.closest ?
                hit.closest('.queueRow[data-queue-reorderable="true"]') : null;

            if (target && target !== row && target.parentNode === parent) {
                var targetRect = target.getBoundingClientRect();
                if (moveEvent.clientY < targetRect.top + targetRect.height / 2) {
                    parent.insertBefore(placeholder, target);
                } else {
                    parent.insertBefore(placeholder, target.nextSibling);
                }
                return;
            }

            // The pointer may be over the sticky queue toolbar while scrolling
            // upward, or below the final row while scrolling downward. In those
            // areas elementFromPoint() cannot identify a queue row, so explicitly
            // allow the placeholder to reach the first or final queue position.
            var firstRow = reorderableRows[0];
            var lastRow = reorderableRows[reorderableRows.length - 1];
            var firstRect = firstRow.getBoundingClientRect();
            var lastRect = lastRow.getBoundingClientRect();

            if (moveEvent.clientY <= firstRect.top + firstRect.height / 2) {
                parent.insertBefore(placeholder, firstRow);
            } else if (moveEvent.clientY >= lastRect.top + lastRect.height / 2) {
                parent.insertBefore(placeholder, lastRow.nextSibling);
            }
        }

        function queueDragViewportBounds() {
            var viewportH = window.innerHeight ||
                (document.documentElement && document.documentElement.clientHeight) || 0;
            var docScroller = getSrovaDocumentScrollElement();
            var top = 0;
            var bottom = viewportH;

            if (dragScroller &&
                dragScroller !== docScroller &&
                dragScroller !== document.documentElement &&
                dragScroller !== document.body) {
                var scrollerRect = dragScroller.getBoundingClientRect();
                top = Math.max(top, scrollerRect.top);
                bottom = Math.min(bottom, scrollerRect.bottom);
            }

            var queueBar = queueView.querySelector(".queueBar");
            if (queueBar) {
                var queueBarRect = queueBar.getBoundingClientRect();
                if (queueBarRect.height > 0) {
                    top = Math.max(top, queueBarRect.bottom);
                }
            }

            if (playerBar) {
                var playerBarRect = playerBar.getBoundingClientRect();
                if (playerBarRect.height > 0 &&
                    playerBarRect.top > top &&
                    playerBarRect.top < bottom) {
                    bottom = playerBarRect.top;
                }
            }

            return {
                top: Math.max(0, Math.min(top, viewportH)),
                bottom: Math.max(top, Math.min(bottom, viewportH))
            };
        }

        function queueDragTopForPointer(clientY) {
            var bounds = queueDragViewportBounds();
            var minTop = bounds.top;
            var maxTop = Math.max(minTop, bounds.bottom - rect.height);
            return Math.min(
                maxTop,
                Math.max(minTop, clientY - offsetY)
            );
        }

        function queueDragEdgeScrollStep() {
            edgeScrollFrame = 0;

            var bounds = queueDragViewportBounds();
            var delta = 0;

            if (lastPointerY < bounds.top + edgeScrollThreshold) {
                var topStrength = Math.min(
                    1,
                    Math.max(
                        0,
                        (bounds.top + edgeScrollThreshold - lastPointerY) /
                        edgeScrollThreshold
                    )
                );
                delta = -Math.max(2, Math.round(edgeScrollMaxStep * topStrength));
            } else if (lastPointerY > bounds.bottom - edgeScrollThreshold) {
                var bottomStrength = Math.min(
                    1,
                    Math.max(
                        0,
                        (lastPointerY - (bounds.bottom - edgeScrollThreshold)) /
                        edgeScrollThreshold
                    )
                );
                delta = Math.max(2, Math.round(edgeScrollMaxStep * bottomStrength));
            }

            if (delta !== 0) {
                var beforeScrollTop = getSrovaElementScrollTop(dragScroller);
                setSrovaElementScrollTop(dragScroller, beforeScrollTop + delta);
                var afterScrollTop = getSrovaElementScrollTop(dragScroller);

                if (afterScrollTop !== beforeScrollTop) {
                    movePlaceholder({
                        clientX: lastPointerX,
                        clientY: lastPointerY
                    });
                }
            }

            edgeScrollFrame = requestAnimationFrame(queueDragEdgeScrollStep);
        }

        function onMove(moveEvent) {
            if (moveEvent.pointerId !== pointerId) { return; }
            moveEvent.preventDefault();

            lastPointerX = moveEvent.clientX;
            lastPointerY = moveEvent.clientY;

            row.style.setProperty("--queue-drag-left", String(moveEvent.clientX - offsetX) + "px");
            row.style.setProperty(
                "--queue-drag-top",
                String(queueDragTopForPointer(moveEvent.clientY)) + "px"
            );
            movePlaceholder(moveEvent);
        }

        edgeScrollFrame = requestAnimationFrame(queueDragEdgeScrollStep);

        function finish(endEvent, commit) {
            if (endEvent && endEvent.pointerId !== pointerId) { return; }
            window.removeEventListener("pointermove", onMove, true);
            window.removeEventListener("pointerup", onUp, true);
            window.removeEventListener("pointercancel", onCancel, true);
            window.removeEventListener("blur", onBlur, true);

            if (edgeScrollFrame) {
                cancelAnimationFrame(edgeScrollFrame);
                edgeScrollFrame = 0;
            }

            var position = 0;
            var sibling = placeholder.previousSibling;
            while (sibling) {
                if (sibling !== row && sibling.getAttribute && sibling.getAttribute("data-queue-reorderable") === "true") {
                    position += 1;
                }
                sibling = sibling.previousSibling;
            }
            var toIndex = originalIndexes[Math.min(position, originalIndexes.length - 1)];
            parent.insertBefore(row, placeholder);
            placeholder.remove();
            row.classList.remove("is-queue-dragging");
            document.body.classList.remove("is-queue-reordering-drag");
            if (originalStyle === null) { row.removeAttribute("style"); }
            else { row.setAttribute("style", originalStyle); }
            row._suppressQueueClickUntil = Date.now() + 350;

            if (!commit || toIndex === absIdx) { return; }
            handle.disabled = true;
            persistUpcomingQueueMove(absIdx, toIndex)
                .then(function() {
                    loadQueue({preserveScroll: true});
                })
                .catch(function(err) {
                    loadQueue({preserveScroll: true});
                    showQueueActionToast(err.message || "Could not reorder the Play Queue.", true);
                });
        }

        function onUp(upEvent) {
            upEvent.preventDefault();
            upEvent.stopPropagation();
            finish(upEvent, true);
        }
        function onCancel(cancelEvent) { finish(cancelEvent, false); }
        function onBlur() { finish(null, false); }

        window.addEventListener("pointermove", onMove, {capture: true, passive: false});
        window.addEventListener("pointerup", onUp, true);
        window.addEventListener("pointercancel", onCancel, true);
        window.addEventListener("blur", onBlur, true);
    });
}

function openQueueRemoveConfirm(track, onConfirm) {
    var modal = document.createElement("div");
    modal.className = "localLibraryCleanupModal queueRemoveConfirmModal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "queueRemoveConfirmTitle");
    modal.setAttribute("aria-describedby", "queueRemoveConfirmBody");

    var card = document.createElement("div");
    card.className = "localLibraryCleanupCard";

    var title = document.createElement("div");
    title.id = "queueRemoveConfirmTitle";
    title.className = "localLibraryCleanupTitle";
    title.textContent = "Remove from Play Queue?";
    card.appendChild(title);

    var body = document.createElement("div");
    body.id = "queueRemoveConfirmBody";
    body.className = "localLibraryCleanupBody";
    body.textContent = 'Remove "' + String((track && track.title) || "this track") + '" from the Play Queue?';
    card.appendChild(body);

    var actions = document.createElement("div");
    actions.className = "localLibraryCleanupActions";

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "settingsBtn";
    cancelBtn.type = "button";
    cancelBtn.textContent = "Cancel";
    actions.appendChild(cancelBtn);

    var confirmBtn = document.createElement("button");
    confirmBtn.className = "settingsBtn settingsBtnDanger localLibraryCleanupConfirm";
    confirmBtn.type = "button";
    confirmBtn.textContent = "Remove Track";
    actions.appendChild(confirmBtn);

    card.appendChild(actions);
    modal.appendChild(card);
    document.body.appendChild(modal);

    function closeModal() {
        document.removeEventListener("keydown", onKeyDown);
        if (modal.parentNode) { modal.parentNode.removeChild(modal); }
    }

    function onKeyDown(e) {
        if (e.key === "Escape") { closeModal(); }
    }

    cancelBtn.onclick = closeModal;
    confirmBtn.onclick = function() {
        closeModal();
        if (typeof onConfirm === "function") { onConfirm(); }
    };
    modal.addEventListener("click", function(e) {
        if (e.target === modal) { closeModal(); }
    });
    document.addEventListener("keydown", onKeyDown);
    setTimeout(function() { cancelBtn.focus(); }, 0);
}

function buildQueueRow(track, absIdx, isNowPlaying, isPlayed, isUpcoming) {
    var row = document.createElement("div");
    row.className = "queueRow" +
        (isNowPlaying ? " queueRowPlaying" : "") +
        (isPlayed     ? " queueRowPlayed"  : "");

    var art = document.createElement("img");
    art.className = "queueThumb";
    var artUrl = track.cover || track.artwork_url || "";
    var isLocalQueueTrack = String((track && track.source) || "").toLowerCase() === "local" ||
        String((track && track.id) || "").indexOf("local:") === 0;
    if (!artUrl && isLocalQueueTrack) {
        artUrl = localAlbumArtDataUri(track.album || track.title || "", track.artist || "");
    }
    art.src = artUrl;
    if (isLocalQueueTrack) {
        applyLocalArtworkFallback(art, track.album || track.title || "", track.artist || "");
    }

    var meta = document.createElement("div");
    meta.className = "queueMeta";
    var titleEl = document.createElement("div");
    titleEl.className   = "queueTitle";
    titleEl.textContent = track.title || "";
    var artistEl = document.createElement("div");
    artistEl.className   = "queueArtist";
    var artistText = track.artist || "";
    artistEl.textContent = artistText;
    var sourcePill = document.createElement("span");
    sourcePill.className = "queueSourcePill";
    sourcePill.textContent = sourceLabelForTrack(track);
    artistEl.appendChild(sourcePill);
    meta.appendChild(titleEl);
    meta.appendChild(artistEl);

    var dur = document.createElement("div");
    dur.className   = "queueDuration";
    dur.textContent = formatTime(track.duration || 0);

    var removeBtn = document.createElement("button");
    removeBtn.className = "queueRemoveBtn";
    removeBtn.innerHTML = '<span class="material-icons">close</span>';
    removeBtn.title     = "Remove";
    (function(idx) {
        removeBtn.onclick = function(e) {
            e.stopPropagation();
            function removeTrack() {
                fetch("/tidal/queue/remove/" + idx)
                .then(function(res) {
                    return res.json().catch(function() { return {}; });
                })
                .then(function(data) {
                    loadQueue();
                    if (data && data.stopped === true) {
                        applyStandbyPlayerBar();
                        pollStatus();
                    }
                });
            }

            if (isPlayed) {
                removeTrack();
                return;
            }
            openQueueRemoveConfirm(track, removeTrack);
        };
    }(absIdx));

    row.appendChild(art);
    row.appendChild(meta);
    row.appendChild(dur);
    row.appendChild(removeBtn);

    if (isUpcoming) {
        var dragHandle = document.createElement("button");
        dragHandle.type = "button";
        dragHandle.className = "queueDragHandle";
        dragHandle.title = "Drag to reorder track";
        dragHandle.setAttribute(
            "aria-label",
            "Drag to reorder " + String((track && track.title) || "track")
        );
        dragHandle.innerHTML = '<span class="material-icons">drag_indicator</span>';
        row.appendChild(dragHandle);
        enableUpcomingQueueDrag(row, dragHandle, absIdx);
    }

    // Tap row = jump to that track
    (function(idx) {
        row.onclick = function() {
            if (row._suppressQueueClickUntil && Date.now() < row._suppressQueueClickUntil) {
                return;
            }
            fetch("/tidal/queue/jump/" + idx)
            .then(function(res) { return res.json().catch(function() { return {}; }); })
            .then(function(data) {
                if (data && (data.ok === false || data.error)) {
                    showQueueActionToast(playbackErrorMessage(data, "Playback failed"), true);
                    return;
                }
                startTime = Date.now() / 1000;
                playing   = true;
                setPlayerHasActiveMedia(true);
                progressFill._elapsed = 0;
                updatePlayPauseIcon();
                setTimeout(loadQueue, 300);
            });
        };
    }(absIdx));

    return row;
}


// --- Favorites ---

function loadFavoriteIds() {
    fetch("/tidal/favorites/ids")
        .then(function(res) { return res.json(); })
        .then(function(data) {
            var i;
            favTrackIds  = {};
            favAlbumIds  = {};
            favArtistIds = {};
            for (i = 0; i < (data.track_ids  || []).length; i++) { favTrackIds[String(data.track_ids[i])]   = true; }
            for (i = 0; i < (data.album_ids  || []).length; i++) { favAlbumIds[String(data.album_ids[i])]   = true; }
            for (i = 0; i < (data.artist_ids || []).length; i++) { favArtistIds[String(data.artist_ids[i])] = true; }
            updateHeartStates();
        })
        .catch(function() {});
}

function updateSingleHeartEl(el, isFaved) {
    if (!el) { return; }
    var icon = el.querySelector(".material-icons");
    if (isFaved) {
        el.classList.add("faved");
        if (icon) { icon.textContent = "favorite"; }
    } else {
        el.classList.remove("faved");
        if (icon) { icon.textContent = "favorite_border"; }
    }
}

function updateNpHeart() {
    var el = document.getElementById("npBtnHeart");
    if (!el || !currentPlayingId) { return; }
    updateSingleHeartEl(el, !!favTrackIds[currentPlayingId]);
}

function updateHeaderHeart() {
    var el = document.getElementById("albumHeaderHeart");
    if (!el) { return; }
    var htype = el.getAttribute("data-heart-type");
    var hid   = el.getAttribute("data-heart-id");
    if (!htype || !hid) { return; }
    var isFaved = false;
    if (htype === "album")  { isFaved = !!favAlbumIds[hid]; }
    if (htype === "artist") { isFaved = !!favArtistIds[hid]; }
    updateSingleHeartEl(el, isFaved);
}

function updateHeartStates() {
    // Track row hearts in the album/artist/playlist/mix view
    var hearts = trackList ? trackList.querySelectorAll(".trackHeart") : [];
    var i;
    for (i = 0; i < hearts.length; i++) {
        var tid = hearts[i].getAttribute("data-track-id");
        updateSingleHeartEl(hearts[i], !!favTrackIds[tid]);
    }
    // Now Playing heart and header heart
    updateNpHeart();
    updateHeaderHeart();
}

function toggleTrackFavorite(tid, el) {
    var wasFaved = !!favTrackIds[tid];
    var nowFaved = !wasFaved;
    favTrackIds[tid] = nowFaved;
    updateSingleHeartEl(el, nowFaved);
    // Sync any other heart showing this track (NP heart or a row heart)
    if (currentPlayingId === String(tid)) { updateNpHeart(); }
    if (trackList) {
        var rowHeart = trackList.querySelector(".trackHeart[data-track-id=\"" + tid + "\"]");
        if (rowHeart && rowHeart !== el) { updateSingleHeartEl(rowHeart, nowFaved); }
    }
    fetch("/tidal/favorite/track/" + tid)
        .catch(function() {
            favTrackIds[tid] = wasFaved;
            updateSingleHeartEl(el, wasFaved);
            if (currentPlayingId === String(tid)) { updateNpHeart(); }
        });
}

function toggleNpHeart() {
    if (!currentPlayingId) { return; }
    var el = document.getElementById("npBtnHeart");
    toggleTrackFavorite(currentPlayingId, el);
}

function toggleAlbumFavorite(albumId, el) {
    var wasFaved = !!favAlbumIds[albumId];
    var nowFaved = !wasFaved;
    favAlbumIds[albumId] = nowFaved;
    updateSingleHeartEl(el, nowFaved);
    fetch("/tidal/favorite/album/" + albumId)
        .catch(function() {
            favAlbumIds[albumId] = wasFaved;
            updateSingleHeartEl(el, wasFaved);
        });
}

function toggleArtistFavorite(artistId, el) {
    var wasFaved = !!favArtistIds[artistId];
    var nowFaved = !wasFaved;
    favArtistIds[artistId] = nowFaved;
    updateSingleHeartEl(el, nowFaved);
    fetch("/tidal/favorite/artist/" + artistId)
        .catch(function() {
            favArtistIds[artistId] = wasFaved;
            updateSingleHeartEl(el, wasFaved);
        });
}


// --- Meta Panel (Track Info slide-up overlay) ---

var metaPanel   = document.getElementById("metaPanel");
var metaContent = document.getElementById("metaContent");
var metaBioExpanded = false;
var metaLastTrackId = null;

function getMetaPanelTrackKey() {
    if (currentPlayingId) { return String(currentPlayingId); }

    var s = lastKnownPlaybackStatus || {};
    var isRadio = !!(s.radio_mode || s.source === "radio" || s.context_type === "radio");
    if (!isRadio) { return ""; }

    var meta = s.radio_metadata || {};
    var artist = String(meta.artist || s.radio_cover_art_artist || "").trim();
    var title  = String(meta.title  || s.radio_cover_art_title  || "").trim();
    if (artist || title) {
        return "radio:" + artist + "\u0000" + title;
    }

    var station = s.radio_station || {};
    var stationId = String(station.id || s.context_id || station.name || "radio").trim();
    return stationId ? ("radio:station:" + stationId) : "";
}

function openMetaPanel() {
    var metaTrackKey = getMetaPanelTrackKey();
    if (!metaTrackKey) { return; }
    metaPanel.classList.add("open");
    // Only reload if the track changed since last open
    if (metaLastTrackId !== metaTrackKey) {
        metaBioExpanded = false;
        metaLastTrackId = metaTrackKey;
        renderMetaLoading();
        loadMeta();
    }
}

function closeMetaPanel() {
    metaPanel.classList.remove("open");
}

function renderMetaLoading() {
    metaContent.innerHTML =
        '<div class="metaLoading">' +
        '<div class="metaSpinner"></div>' +
        '<span>Fetching track info...</span>' +
        '</div>';
}

function loadMeta() {
    fetch("/meta/now")
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.error) {
                metaContent.innerHTML =
                    '<div class="metaLoading"><span>' +
                    (data.error === "nothing playing" ? "Nothing playing." :
                     data.error === "radio_metadata_unavailable" ? "Artist info is not available for this radio stream yet." :
                     "Could not load info.") +
                    '</span></div>';
                return;
            }
            renderMetaPanel(data);
        })
        .catch(function() {
            metaContent.innerHTML =
                '<div class="metaLoading"><span>Could not load info.</span></div>';
        });
}

function _fmtCount(n) {
    if (!n) { return ""; }
    var num = parseInt(n, 10);
    if (isNaN(num)) { return ""; }
    if (num >= 1000000) { return (num / 1000000).toFixed(1) + "M"; }
    if (num >= 1000)    { return (num / 1000).toFixed(0)    + "K"; }
    return String(num);
}

function renderMetaPanel(d) {
    metaContent.innerHTML = "";

    // --- Fanart banner ---
    if (d.fanart) {
        var img = document.createElement("img");
        img.className = "metaFanart";
        img.src = d.fanart;
        img.alt = "";
        metaContent.appendChild(img);
    }

    // --- Artist identity row ---
    var artistRow = document.createElement("div");
    artistRow.className = "metaArtistRow";
    if (d.artist_thumb) {
        var thumb = document.createElement("img");
        thumb.className = "metaArtistThumb";
        thumb.src = d.artist_thumb;
        thumb.alt = "";
        artistRow.appendChild(thumb);
    }
    var artistText = document.createElement("div");
    var nameEl = document.createElement("div");
    nameEl.className   = "metaArtistName";
    nameEl.textContent = d.artist || "";
    artistText.appendChild(nameEl);
    var subParts = [];
    if (d.country)    { subParts.push(d.country); }
    if (d.formed_year){ subParts.push("Est. " + d.formed_year); }
    if (d.genre)      { subParts.push(d.genre); }
    if (subParts.length > 0) {
        var subEl = document.createElement("div");
        subEl.className   = "metaArtistSub";
        subEl.textContent = subParts.join("  \u00b7  ");
        artistText.appendChild(subEl);
    }
    artistRow.appendChild(artistText);
    metaContent.appendChild(artistRow);

    // --- Stats ---
    var listeners = _fmtCount(d.listeners);
    var playcount  = _fmtCount(d.playcount);
    if (listeners || playcount) {
        var statsEl = document.createElement("div");
        statsEl.className = "metaStats";
        if (listeners) {
            var s1 = document.createElement("div");
            s1.className = "metaStat";
            s1.innerHTML = '<div class="metaStatVal">' + listeners + '</div>' +
                           '<div class="metaStatLabel">Listeners</div>';
            statsEl.appendChild(s1);
        }
        if (playcount) {
            var s2 = document.createElement("div");
            s2.className = "metaStat";
            s2.innerHTML = '<div class="metaStatVal">' + playcount + '</div>' +
                           '<div class="metaStatLabel">Plays</div>';
            statsEl.appendChild(s2);
        }
        metaContent.appendChild(statsEl);
    }

    // --- Tags ---
    if (d.tags && d.tags.length > 0) {
        var tagsEl = document.createElement("div");
        tagsEl.className = "metaTags";
        for (var i = 0; i < d.tags.length; i++) {
            var chip = document.createElement("span");
            chip.className   = "metaTag";
            chip.textContent = d.tags[i];
            tagsEl.appendChild(chip);
        }
        metaContent.appendChild(tagsEl);
    }

    // --- Track summary ---
    if (d.track_summary && d.track_summary.length > 20) {
        metaContent.appendChild(_metaDivider());
        metaContent.appendChild(_metaSection("About this track"));
        metaContent.appendChild(_metaBioBlock(d.track_summary, 600));
    }

    // --- Artist bio ---
    if (d.artist_bio && d.artist_bio.length > 20) {
        metaContent.appendChild(_metaDivider());
        metaContent.appendChild(_metaSection("About " + (d.artist || "the artist")));
        metaContent.appendChild(_metaBioBlock(d.artist_bio, 800));
    }

    // --- Similar artists ---
    if (d.similar_artists && d.similar_artists.length > 0) {
        metaContent.appendChild(_metaDivider());
        metaContent.appendChild(_metaSection("Similar artists"));
        var row = document.createElement("div");
        row.className = "metaSimilarRow";
        for (var j = 0; j < d.similar_artists.length; j++) {
            (function(name) {
                var chip = document.createElement("div");
                chip.className   = "metaSimilarChip";
                chip.textContent = name;
                chip.onclick = function() {
                    closeMetaPanel();
                    closeNowPlaying();
                    searchInput.value = name;
                    searchClear.classList.remove("hidden");
                    doSearch(name);
                };
                row.appendChild(chip);
            }(d.similar_artists[j]));
        }
        metaContent.appendChild(row);
    }
}

function _metaDivider() {
    var el = document.createElement("div");
    el.className = "metaDivider";
    return el;
}

function _metaSection(label) {
    var el = document.createElement("div");
    el.className   = "metaSection";
    el.textContent = label;
    return el;
}

function _metaBioBlock(text, limit) {
    var frag     = document.createDocumentFragment();
    var isShort  = text.length <= limit;
    var expanded = false;
    var bioEl    = document.createElement("div");
    bioEl.className   = "metaBioText";
    bioEl.textContent = isShort ? text : text.slice(0, limit).trimRight() + "...";
    frag.appendChild(bioEl);
    if (!isShort) {
        var btn = document.createElement("button");
        btn.className   = "metaReadMore";
        btn.textContent = "Read more";
        btn.onclick = function() {
            expanded = true;
            bioEl.textContent = text;
            btn.style.display = "none";
        };
        frag.appendChild(btn);
    }
    return frag;
}


// --- Lyrics Panel ---

var lyricsPanel      = document.getElementById("lyricsPanel");
var lyricsContent    = document.getElementById("lyricsContent");
var lyricsLastTrackId = null;
var _lyricsLines     = [];    // [{ms, text, el}] for synced lyrics
var _lyricsSynced    = false;
var _lyricsActiveIdx = -1;
var _lyricsRAF       = null;

function openLyricsPanel() {
    if (!currentPlayingId) { return; }
    // Close meta panel if open
    if (metaPanel && metaPanel.classList.contains("open")) { closeMetaPanel(); }
    lyricsPanel.classList.add("open");
    if (lyricsLastTrackId !== currentPlayingId) {
        lyricsLastTrackId = currentPlayingId;
        _lyricsLines      = [];
        _lyricsSynced     = false;
        _lyricsActiveIdx  = -1;
        renderLyricsLoading();
        loadLyrics();
    } else if (_lyricsSynced) {
        // Panel already populated and synced -- restart the highlight loop
        _startLyricsSync();
    }
}

function closeLyricsPanel() {
    lyricsPanel.classList.remove("open");
    _stopLyricsSync();
}

function renderLyricsLoading() {
    lyricsContent.innerHTML =
        '<div class="lyricsLoading">' +
        '<div class="metaSpinner"></div>' +
        '<span>Fetching lyrics...</span>' +
        '</div>';
}

function loadLyrics() {
    var trackId = String(currentPlayingId || "");
    var source = "";
    try {
        source = inferStatusPlaybackSource(lastKnownPlaybackStatus || {});
    } catch (e) {}
    var isLocal = source === "local" || trackId.indexOf("local:") === 0;
    var lyricsUrl = (isLocal ? "/api/local/library/lyrics/" : "/tidal/lyrics/") + encodeURIComponent(trackId);
    fetch(lyricsUrl)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                lyricsContent.innerHTML =
                    '<div class="lyricsLoading"><span>' +
                    (data.error === "no_lyrics" ? "No lyrics available for this track." : "Could not load lyrics.") +
                    '</span></div>';
                return;
            }
            if (data.synced) {
                renderSyncedLyrics(data.lines);
            } else {
                renderUnsyncedLyrics(data.text);
            }
        })
        .catch(function() {
            lyricsContent.innerHTML =
                '<div class="lyricsLoading"><span>Could not load lyrics.</span></div>';
        });
}

function renderUnsyncedLyrics(text) {
    _lyricsSynced = false;
    lyricsContent.innerHTML = "";
    var pre = document.createElement("div");
    pre.className   = "lyricsUnsynced";
    pre.textContent = text;
    lyricsContent.appendChild(pre);
}

function renderSyncedLyrics(lines) {
    _lyricsSynced = true;
    _lyricsLines  = [];
    _lyricsActiveIdx = -1;
    lyricsContent.innerHTML = "";

    var container = document.createElement("div");
    container.className = "lyricsSyncedContainer";

    // Top spacer so first line can scroll to centre
    var topSpacer = document.createElement("div");
    topSpacer.className = "lyricsSpacer";
    container.appendChild(topSpacer);

    for (var i = 0; i < lines.length; i++) {
        var el = document.createElement("div");
        el.className   = "lyricLine";
        el.textContent = lines[i].text;
        container.appendChild(el);
        _lyricsLines.push({ ms: lines[i].ms, text: lines[i].text, el: el });
    }

    // Bottom spacer
    var botSpacer = document.createElement("div");
    botSpacer.className = "lyricsSpacerBottom";
    container.appendChild(botSpacer);

    lyricsContent.appendChild(container);
    _startLyricsSync();
}

function _startLyricsSync() {
    _stopLyricsSync();
    function _tick() {
        // Keep the RAF alive as long as synced lyrics are loaded --
        // stopping on panel-closed caused the loop to die permanently
        if (!_lyricsSynced) { return; }
        if (lyricsPanel && lyricsPanel.classList.contains("open")) {
            var elapsed = 0;
            if (playing) {
                elapsed = (Date.now() / 1000 - startTime) * 1000;
            } else {
                elapsed = (progressFill._elapsed || 0) * 1000;
            }
            // Find current line
            var idx = -1;
            for (var i = 0; i < _lyricsLines.length; i++) {
                if (_lyricsLines[i].ms <= elapsed) { idx = i; }
                else { break; }
            }
            if (idx !== _lyricsActiveIdx) {
                // Deactivate old
                if (_lyricsActiveIdx >= 0 && _lyricsActiveIdx < _lyricsLines.length) {
                    _lyricsLines[_lyricsActiveIdx].el.classList.remove("lyricActive");
                }
                // Activate new
                if (idx >= 0 && idx < _lyricsLines.length) {
                    var activeEl = _lyricsLines[idx].el;
                    activeEl.classList.add("lyricActive");
                    // Scroll active line to centre of lyricsContent
                    var containerTop = lyricsContent.scrollTop;
                    var elTop        = activeEl.offsetTop;
                    var target       = elTop - (lyricsContent.clientHeight / 2) + (activeEl.offsetHeight / 2);
                    lyricsContent.scrollTop += (target - containerTop) * 0.15;
                }
                _lyricsActiveIdx = idx;
            }
        }
        _lyricsRAF = requestAnimationFrame(_tick);
    }
    _lyricsRAF = requestAnimationFrame(_tick);
}

function _stopLyricsSync() {
    if (_lyricsRAF) { cancelAnimationFrame(_lyricsRAF); _lyricsRAF = null; }
}


// --- Login dots animation ---
(function() {
    var dots = document.querySelector(".loginDots");
    if (!dots) { return; }
    var count = 0;
    setInterval(function() {
        count = (count + 1) % 4;
        dots.textContent = ".".repeat(count);
    }, 500);
}());


// ============================================================
// --- Artist Page ---
// ============================================================

function _wireAlbumArtistClick(artistId, artistName) {
    if (!albumArtist || !artistId) { return; }
    albumArtist.style.cursor = "pointer";
    albumArtist.title        = artistName || "";
    albumArtist.onclick = function() {
        loadArtistPage(artistId, artistName, albumArt.src || "", previousView);
    };
}

function loadArtistPage(artistId, artistName, artistCover, fromView) {
    if (!requireOnlineSource()) { return; }
    previousView        = fromView || "home";
    currentViewEndpoint = "/tidal/artist/" + artistId;
    currentContext      = { id: artistId, cover: artistCover || "", title: artistName, artist: "" };

    // Store restore function so Back works when drilling into a discography album
    (function(id, name, cover, from) {
        _artistPageRestoreFn = function() { loadArtistPage(id, name, cover, from); };
    }(artistId, artistName, artistCover, fromView));

    // Mark this shared albumView instance as Artist-only.
    // Artist-specific layout remains isolated from albums,
    // playlists, mixes and featured track lists.
    setAlbumViewKind("tidal-artist");
    showView("album");
    albumArt.src            = artistCover || "";
    albumTitle.textContent  = artistName  || "";
    albumArtist.textContent = "";
    albumArtist.style.cursor = "";
    albumArtist.onclick      = null;
    albumTechInfo.classList.add("hidden");
    trackList.innerHTML = '<div class="trackListLoading">Loading artist\u2026</div>';

    var tracksData = null;
    var albumsData = null;
    var done = 0;

    function _checkDone() {
        done++;
        if (done < 2) { return; }
        _renderArtistPage(artistId, artistName, artistCover, tracksData || [], albumsData || []);
    }

    fetch("/tidal/artist/" + artistId)
        .then(function(r) { return r.json(); })
        .then(function(d) {
            tracksData = Array.isArray(d) ? d : [];
            currentViewTracks = tracksData;
            _checkDone();
        })
        .catch(function() { _checkDone(); });

    fetch("/tidal/artist/" + artistId + "/albums")
        .then(function(r) { return r.json(); })
        .then(function(d) {
            albumsData = Array.isArray(d) ? d : [];
            _checkDone();
        })
        .catch(function() { _checkDone(); });
}

function _renderArtistPage(artistId, artistName, artistCover, tracks, albums) {
    trackList.innerHTML = "";

    // ---- Top Tracks section ----
    var tracksSection = document.createElement("div");
    tracksSection.className = "artistSection artistTopTracksSection";
    applyArtworkViewModeClass(tracksSection);

    var tracksHdr = document.createElement("div");
    tracksHdr.className   = "artistSectionHdr";
    tracksHdr.textContent = "Top Tracks";
    tracksSection.appendChild(tracksHdr);

    if (tracks.length === 0) {
        var noTracks = document.createElement("div");
        noTracks.className   = "artistEmpty";
        noTracks.textContent = "No tracks available.";
        tracksSection.appendChild(noTracks);
    } else {
        for (var ti = 0; ti < tracks.length; ti++) {
            tracksSection.appendChild(
                _buildArtistTrackRow(tracks[ti], ti, tracks, artistName, artistCover)
            );
        }
    }
    trackList.appendChild(tracksSection);

    // ---- Discography section ----
    var discoSection = document.createElement("div");
    discoSection.className = "artistSection";

    var discoHdr = document.createElement("div");
    discoHdr.className = "artistSectionHdr artistSectionHdrFlex";

    var discoTitle = document.createElement("span");
    discoTitle.textContent = "Discography";

    var sortWrap = document.createElement("div");
    sortWrap.className = "artistDiscoSort";

    var btnPop  = document.createElement("button");
    var btnDate = document.createElement("button");
    btnPop.className  = "artistSortBtn" + (_artistDiscogSort === "default" ? " active" : "");
    btnDate.className = "artistSortBtn" + (_artistDiscogSort === "date"    ? " active" : "");
    btnPop.textContent  = "Popularity";
    btnDate.textContent = "Release Date";

    (function(bPop, bDate, sec, aName) {
        bPop.onclick = function() {
            _artistDiscogSort = "default";
            bPop.classList.add("active");
            bDate.classList.remove("active");
            _rerenderDiscography(albums, sec, aName);
        };
        bDate.onclick = function() {
            _artistDiscogSort = "date";
            bDate.classList.add("active");
            bPop.classList.remove("active");
            _rerenderDiscography(albums, sec, aName);
        };
    }(btnPop, btnDate, discoSection, artistName));

    sortWrap.appendChild(btnPop);
    sortWrap.appendChild(btnDate);
    discoHdr.appendChild(discoTitle);
    discoHdr.appendChild(sortWrap);
    discoSection.appendChild(discoHdr);
    _rerenderDiscography(albums, discoSection, artistName);
    trackList.appendChild(discoSection);

    // Render artist header actions and one shared Top Tracks/Discography view toggle.
    renderAlbumQueueBtn(tracks, artistCover);
    var artistActionGroup = document.getElementById("albumQueueBtnGroup");
    if (artistActionGroup) {
        artistActionGroup.classList.add("artistHeaderActionGroup");
        appendArtworkViewToggle(artistActionGroup);
    }
    loadFavoriteIds();
}

function _rerenderDiscography(albums, container, artistName) {
    var existing = container.querySelector(".artistDiscoGrid");
    if (existing) { existing.parentNode.removeChild(existing); }

    var grid = document.createElement("div");
    grid.className = "artistDiscoGrid";
    applyArtworkViewModeClass(grid);

    var sorted = albums.slice();
    if (_artistDiscogSort === "date") {
        sorted.sort(function(a, b) {
            var da = a.release_date || "";
            var db = b.release_date || "";
            if (da > db) { return -1; }
            if (da < db) { return  1; }
            return 0;
        });
    }

    if (sorted.length === 0) {
        var empty = document.createElement("div");
        empty.className   = "artistEmpty";
        empty.textContent = "No albums found.";
        grid.appendChild(empty);
    } else {
        for (var ai = 0; ai < sorted.length; ai++) {
            grid.appendChild(_buildDiscoCard(sorted[ai], artistName || ""));
        }
    }
    container.appendChild(grid);
}

function _buildDiscoCard(album, artistName) {
    var card = document.createElement("div");
    card.className = "artistDiscoCard";

    var img = document.createElement("img");
    img.src       = album.image_url || "";
    img.className = "artistDiscoImg";

    var info = document.createElement("div");
    info.className = "artistDiscoInfo";

    var nameEl = document.createElement("div");
    nameEl.className   = "artistDiscoName";
    nameEl.textContent = album.name || "";

    var metaEl = document.createElement("div");
    metaEl.className = "artistDiscoMeta";
    var year      = album.release_date ? album.release_date.slice(0, 4) : "";
    var typeLabel = _albumTypeLabel(album.type || "ALBUM");
    metaEl.textContent = [year, typeLabel].filter(Boolean).join(" \u00b7 ");

    info.appendChild(nameEl);
    info.appendChild(metaEl);
    card.appendChild(img);
    card.appendChild(info);

    if (album.id) {
        (function(alb, aName) {
            card.onclick = function() {
                loadTrackList(
                    { id: alb.id, cover: alb.image_url || "", title: alb.name || "", artist: aName || "" },
                    "/tidal/album/" + alb.id,
                    "artistpage"
                );
            };
        }(album, artistName || ""));
    }
    return card;
}

function _albumTypeLabel(type) {
    var t = String(type || "").toUpperCase();
    if (t === "ALBUM")       { return "Album"; }
    if (t === "EP")          { return "EP"; }
    if (t === "SINGLE")      { return "Single"; }
    if (t === "COMPILATION") { return "Compilation"; }
    return "";
}

function _buildArtistTrackRow(t, idx, allTracks, artistName, artistCover) {
    var row = document.createElement("div");
    var trackCover = t.cover || artistCover || "";
    row.className = "track";
    row.setAttribute("data-track-id", String(t.id || ""));
    if (currentPlayingId && String(t.id) === String(currentPlayingId)) {
        row.classList.add("playing");
    }
    row.innerHTML =
        '<img src="' + trackCover + '" class="artistTrackThumb">' +
        '<div class="track-num">'      + (idx + 1)              + '</div>' +
        '<div class="track-title">'    + (t.title  || "")       + '</div>' +
        '<div class="track-artist">'   + (artistName || t.artist || "") + '</div>' +
        '<div class="track-duration">' + formatTime(t.duration) + '</div>';

    var heartBtn = document.createElement("button");
    heartBtn.className = "trackHeart";
    heartBtn.setAttribute("data-track-id", String(t.id));
    heartBtn.innerHTML = '<span class="material-icons">favorite_border</span>';
    heartBtn.title = "Favorite";
    (function(tid, btn) {
        btn.onclick = function(e) { e.stopPropagation(); toggleTrackFavorite(tid, btn); };
    }(String(t.id), heartBtn));
    row.appendChild(heartBtn);

    var addBtn = document.createElement("button");
    addBtn.className = "trackAddBtn";
    addBtn.innerHTML = '<span class="material-icons">add</span>';
    addBtn.title = "Add to queue";
    (function(track, btn, fallbackCover) {
        btn.onclick = function(e) {
            e.stopPropagation();
            showQueuePopover(btn, [{
                id: track.id, title: track.title || "", artist: artistName || "",
                cover: track.cover || fallbackCover || "", duration: track.duration || 0,
                quality: track.quality || ""
            }], e);
        };
    }(t, addBtn, artistCover));
    row.appendChild(addBtn);

    (function(track, i, all, aName, aCover) {
        row.onclick = function() { _playArtistTopTrack(track, i, all, aName, aCover); };
    }(t, idx, allTracks, artistName, artistCover));
    return row;
}

function _playArtistTopTrack(t, idx, allTracks, artistName, artistCover) {
    if (!requireOnlineSource()) { return; }
    clearRadioIdleStandbyTimer();
    resetTidalInfinitePlayGuard();
    _setPlaybackSource("artist", "", t.title || "");
    var payload = [];
    for (var i = idx; i < allTracks.length; i++) {
        var tr = allTracks[i];
        payload.push({
            id:       tr.id,
            title:    tr.title    || "",
            artist:   artistName  || tr.artist || "",
            cover:    tr.cover || artistCover || "",
            duration: tr.duration || 0,
            quality:  tr.quality  || ""
        });
    }
    if (!payload.length) { return; }
    postTidalQueueReplace({
        tracks:        payload,
        start_index:   0,
        context_type:  "artist",
        context_id:    "",
        context_title: artistName || ""
    }).then(function() {
        trackMap[String(t.id)] = {
            title: t.title || "", artist: artistName || t.artist || "",
            cover: t.cover || artistCover || "", duration: t.duration || 0
        };
    }).catch(function() {});
}


window.addEventListener("DOMContentLoaded", function() {
    updatePlayPauseIcon();
    startOnlineSourcePolling();
    loadHome();
    restoreSession();
    loadFavoriteIds();
    initPlayerTechTray();
    initPlayerInfinitePlayControl();
    showSrovaVolumeSafetyModal();
    checkSrovaUpdate();
    setTimeout(restoreSrovaRestartReturnView, 0);
});

function initPlayerTechTray() {
    if (!playerBar || !playerTechTray || (!playerTechTrayToggle && !playerTechTrayInlineToggle)) { return; }

    var compactTrayQuery = window.matchMedia ? window.matchMedia("(max-width: 900px), (orientation: landscape) and (max-height: 560px) and (max-width: 1180px)") : null;
    var playerTechTrayToggles = [playerTechTrayToggle, playerTechTrayInlineToggle].filter(function(toggle) {
        return !!toggle;
    });

    function syncPlayerTechTrayA11y() {
        var isCompact = compactTrayQuery ? compactTrayQuery.matches : true;
        var isOpen = playerBar.classList.contains("tech-tray-open");

        if (!isCompact && isOpen) {
            playerBar.classList.remove("tech-tray-open");
            isOpen = false;
        }

        playerTechTrayToggles.forEach(function(toggle) {
            var toggleIcon = toggle.querySelector(".material-icons");
            toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
            toggle.setAttribute("aria-label", isOpen ? "Hide audio path details" : "Show audio path details");
            if (toggleIcon) {
                toggleIcon.textContent = isOpen ? "keyboard_arrow_down" : "keyboard_arrow_up";
            }
        });
        playerTechTray.setAttribute("aria-hidden", isCompact && !isOpen ? "true" : "false");
        syncPlayerTrayTrackInfoOverflow();
    }

    playerTechTrayToggles.forEach(function(toggle) {
        toggle.addEventListener("click", function() {
            if (toggle === playerTechTrayInlineToggle && !playerHasActiveMedia) {
                syncPlayerTechTrayA11y();
                return;
            }
            playerBar.classList.toggle("tech-tray-open");
            syncPlayerTechTrayA11y();
        });
    });

    if (compactTrayQuery && compactTrayQuery.addEventListener) {
        compactTrayQuery.addEventListener("change", syncPlayerTechTrayA11y);
    } else if (compactTrayQuery && compactTrayQuery.addListener) {
        compactTrayQuery.addListener(syncPlayerTechTrayA11y);
    }

    if (playerInfinitePlayPhoneTrayQuery && playerInfinitePlayPhoneTrayQuery.addEventListener) {
        playerInfinitePlayPhoneTrayQuery.addEventListener("change", function() {
            syncPlayerInfinitePlayPhoneTrayPlacement();
            updatePlayerInfinitePlayControl();
        });
    } else if (playerInfinitePlayPhoneTrayQuery && playerInfinitePlayPhoneTrayQuery.addListener) {
        playerInfinitePlayPhoneTrayQuery.addListener(function() {
            syncPlayerInfinitePlayPhoneTrayPlacement();
            updatePlayerInfinitePlayControl();
        });
    }

    window.addEventListener("resize", syncPlayerTrayTrackInfoOverflow);
    syncPlayerInfinitePlayPhoneTrayPlacement();
    syncPlayerTechTrayA11y();
}

function initPlayerInfinitePlayControl() {
    if (!playerInfinitePlayControl || !playerInfinitePlayBtn || !playerInfinitePlayMenu) { return; }

    playerInfinitePlayBtn.addEventListener("click", function(event) {
        event.preventDefault();
        event.stopPropagation();
        togglePlayerInfinitePlayMenu();
    });

    playerInfinitePlayMenu.addEventListener("click", function(event) {
        event.stopPropagation();
    });

    playerInfinitePlayMenuBtns.forEach(function(btn) {
        btn.addEventListener("click", function(event) {
            event.preventDefault();
            event.stopPropagation();
            if (btn.disabled || btn.getAttribute("aria-disabled") === "true") { return; }
            applyPlayerInfinitePlayMode(btn.getAttribute("data-mode"));
        });
    });

    document.addEventListener("click", function(event) {
        if (!playerInfinitePlayControl.contains(event.target)) {
            closePlayerInfinitePlayMenu();
        }
    });

    document.addEventListener("keydown", function(event) {
        if (event.key === "Escape") {
            closePlayerInfinitePlayMenu();
        }
    });

    updatePlayerInfinitePlayControl();
}

document.addEventListener("visibilitychange", function() {
    if (document.visibilityState === "visible") {
        restoreSession();
        if (settingsView && settingsView.style.display !== "none") {
            refreshTidalSettingsStatus(_settingsRenderToken);
        }
    }
});


// --- Session restore for multi-device sync ---

function restoreSession() {
    fetch("/session")
        .then(function(res) { return res.json(); })
        .then(function(s) {
            if (isRadioLiveStatus(s) && (s.radio_mode || s.source === "radio" || s.context_type === "radio")) {
                skipRadioRestoreSeek();
                currentPlayingId = null;
                currentDuration = 0;
                resetLocalPlaybackProgress();
                playing = !!s.playing;
                setPlayerHasActiveMedia(true);
                playerBar.classList.remove("hidden");
                updatePlayPauseIcon();
                return;
            }
            if (s.current_track_valid === false || s.playback_state === "idle" || !s.track_id) {
                playing = !!s.playing;
                applyStandbyPlayerBar();
                return;
            }

            var restoredTrackId = String(s.track_id);
            var previousTrackId = String(currentPlayingId || "");
            var trackChanged = restoredTrackId !== previousTrackId;
            var hadPreviousTrack = !!previousTrackId;
            var suppressSessionPosition = consumeSessionPositionResetForTrack(restoredTrackId);
            currentPlayingId = restoredTrackId;
            currentDuration  = s.duration || 0;
            playing          = s.playing  || false;
            setPlayerHasActiveMedia(true);
            repeatMode       = s.repeat   || "off";
            shuffleOn        = s.shuffle  || false;

            var serverPos = suppressSessionPosition ? 0 : guardedSessionPosition(restoredTrackId, s.position || 0);
            serverPos = normalizeLocalCueUiPosition(serverPos, progressFill._elapsed || 0);
            serverPos = stableResumeVisualPosition(serverPos, restoredTrackId, !!s.playing);
            var localPos  = progressFill._elapsed || 0;
            if (suppressSessionPosition || (trackChanged && hadPreviousTrack)) {
                resetLocalPlaybackProgress();
            } else if (serverPos > 2) {
                startTime             = Date.now() / 1000 - serverPos;
                progressFill._elapsed = serverPos;
            } else if (localPos < 1 || s.playing) {
                startTime             = Date.now() / 1000;
                progressFill._elapsed = 0;
            }
            if (!s.playing && !seekInFlight) {
                progressFill._elapsed = serverPos;
            }

            playerArt.src            = s.cover  || "";
            playerTrack.textContent  = s.title  || "";
            playerArtist.textContent = s.artist || "";
            totalTimeEl.textContent  = formatTime(s.duration || 0);
            playerBar.classList.remove("hidden");
            if (!s.playing && !seekInFlight) {
                applyPlaybackPosition(serverPos, false);
            }

            updatePlayPauseIcon();
            updateRepeatIcon();
            updateShuffleIcon();

            if (s.sample_rate || s.bit_depth) {
                updateTechInfo(s.sample_rate, s.bit_depth, s.codec);
            }

            trackMap[currentPlayingId] = {
                title:        s.title        || "",
                artist:       s.artist       || "",
                artistId:     s.artist_id    || "",
                album:        s.album        || "",
                albumId:      s.album_id     || "",
                cover:        s.cover        || "",
                duration:     s.duration     || 0,
                contextTitle: s.context_title || ""
            };
            syncActiveTrackViews(trackChanged);
            syncPlayerTrayTrackInfo(s);
            // Restore playbackSource from session so Now Playing label is correct
            // after page reload or on a second device
            if (s.context_type && !playbackSource.type) {
                _setPlaybackSource(
                    s.context_type,
                    s.context_id  || "",
                    s.context_title || s.album || ""
                );
            }
            if (!currentContext) {
                currentContext = {
                    title:  s.context_title || "",
                    artist: s.artist        || "",
                    cover:  s.cover         || ""
                };
            }
            // Wire up Now Playing clickable album/artist if view is open
            _updateNowPlayingLinks(s);
            // Wire up player bar clickable artist/album
            _updatePlayerBarLinks(s);
            // Sync heart states (NP heart reflects current track)
            updateHeartStates();
        })
        .catch(function() {});
}

function _updateNowPlayingLinks(s) {
    // Make nowPlayingArtist clickable -> artist page
    if (nowPlayingArtist && s.artist_id) {
        nowPlayingArtist.style.cursor = "pointer";
        nowPlayingArtist.onclick = function() {
            closeNowPlaying();
            loadArtistPage(s.artist_id, s.artist || "", s.cover || "", nowPlayingFromView);
        };
    }
    // "Playing from" label + navigation for all context types
    var ctxType  = s.context_type  || "";
    var ctxId    = s.context_id    || "";
    var ctxTitle = s.context_title || s.album || "";
    if (nowPlayingFrom) {
        nowPlayingFrom.textContent = ctxTitle;
        if (ctxType && ctxId) {
            nowPlayingFrom.style.cursor = "pointer";
            (function(type, id, title, artist, cover) {
                nowPlayingFrom.onclick = function() {
                    closeNowPlaying();
                    if (type === "album") {
                        loadTrackList(
                            { id: id, cover: cover, title: title, artist: artist },
                            "/tidal/album/" + id, nowPlayingFromView
                        );
                    } else if (type === "playlist") {
                        loadTrackList(
                            { id: id, cover: cover, title: title, artist: "" },
                            "/tidal/playlist/" + id, nowPlayingFromView
                        );
                    } else if (type === "mix") {
                        loadTrackList(
                            { id: id, cover: cover, title: title, artist: "" },
                            "/tidal/mix/" + id, nowPlayingFromView
                        );
                    } else if (type === "artist") {
                        loadTrackList(
                            { id: id, cover: cover, title: title, artist: "Top Tracks" },
                            "/tidal/artist/" + id, nowPlayingFromView
                        );
                    } else {
                        // home / hires / mysongs / myalbums / search -- just go back
                        showView(nowPlayingFromView);
                    }
                };
            }(ctxType, ctxId, ctxTitle, s.artist || "", s.cover || ""));
        } else if (s.album_id) {
            // Fallback: album context from track metadata
            nowPlayingFrom.style.cursor = "pointer";
            (function(albumId, albumTitle, artist, cover) {
                nowPlayingFrom.onclick = function() {
                    closeNowPlaying();
                    loadTrackList(
                        { id: albumId, cover: cover, title: albumTitle, artist: artist },
                        "/tidal/album/" + albumId, nowPlayingFromView
                    );
                };
            }(s.album_id, s.album || ctxTitle, s.artist || "", s.cover || ""));
        } else {
            nowPlayingFrom.style.cursor = "";
            nowPlayingFrom.onclick = null;
        }
    }
}

function _updatePlayerBarLinks(s) {
    s = s || {};
    var source = String(s.source || "").toLowerCase();
    var contextType = String(s.context_type || "").toLowerCase();
    var statusTrackId = String(s.current_track_id || s.track_id || "");
    var isLocal = source === "local" ||
        contextType.indexOf("local") === 0 ||
        statusTrackId.indexOf("local:") === 0;

    if (isLocal) {
        var localArtist = String(s.artist || "").trim();
        if (playerArtist && localArtist) {
            playerArtist.style.cursor = "pointer";
            playerArtist.title = localArtist;
            playerArtist.onclick = function() {
                openLocalArtistFromPlayerBar(localArtist, s.cover || "");
            };
        } else if (playerArtist) {
            playerArtist.style.cursor = "";
            playerArtist.title = "";
            playerArtist.onclick = null;
        }
        if (playerTrack) {
            playerTrack.style.cursor = "";
            playerTrack.title = "";
            playerTrack.onclick = null;
        }
        return;
    }

    // Make player bar artist clickable -> artist page
    if (playerArtist && s.artist_id) {
        playerArtist.style.cursor = "pointer";
        playerArtist.title = s.artist || "";
        playerArtist.onclick = function() {
            loadArtistPage(s.artist_id, s.artist || "", s.cover || "", "home");
        };
    } else if (playerArtist) {
        playerArtist.style.cursor = "";
        playerArtist.title = "";
        playerArtist.onclick = null;
    }
    // Make player bar track title clickable -> album view
    if (playerTrack && s.album_id) {
        playerTrack.style.cursor = "pointer";
        playerTrack.title = s.album || "";
        playerTrack.onclick = function() {
            loadTrackList(
                { id: s.album_id, cover: s.cover || "", title: s.album || "", artist: s.artist || "" },
                "/tidal/album/" + s.album_id,
                "home"
            );
        };
    } else if (playerTrack) {
        playerTrack.style.cursor = "";
        playerTrack.title = "";
        playerTrack.onclick = null;
    }
}


// =========================================================================
// My Radio
// =========================================================================

function loadRadioStations() {
    fetch("/api/radio/stations")
        .then(function(res) { return res.json(); })
        .then(function(data) { renderRadioStations(data.stations || []); })
        .catch(function() { renderRadioStations([]); });
}

function renderRadioStations(stations) {
    var list = document.getElementById("radio-stations-list");
    if (!list) { return; }
    list.innerHTML = "";
    if (!stations.length) {
        var empty = document.createElement("div");
        empty.className   = "settingsSectionDesc";
        empty.textContent = "No stations yet. Tap \u201cAdd station\u201d to add one.";
        list.appendChild(empty);
        return;
    }
    for (var i = 0; i < stations.length; i++) {
        (function(station) {
            var row = document.createElement("div");
            row.className = "radio-station-row";

            if (station.icon) {
                var img = document.createElement("img");
                img.className = "icon";
                img.src = station.icon;
                img.alt = "";
                row.appendChild(img);
            } else {
                var ph = document.createElement("div");
                ph.className = "icon-placeholder";
                row.appendChild(ph);
            }

            var meta = document.createElement("div");
            meta.className = "meta";

            var nameEl = document.createElement("div");
            nameEl.className   = "name";
            nameEl.textContent = station.name;
            meta.appendChild(nameEl);

            var urlEl = document.createElement("div");
            urlEl.className   = "url";
            urlEl.textContent = station.url;
            meta.appendChild(urlEl);

            row.appendChild(meta);

            var editBtn = document.createElement("button");
            editBtn.className   = "edit-btn";
            editBtn.textContent = "\u270e";
            editBtn.title       = "Edit";
            editBtn.onclick = function() { openEditRadioModal(station); };
            row.appendChild(editBtn);

            var delBtn = document.createElement("button");
            delBtn.className   = "delete-btn";
            delBtn.textContent = "\u2715";
            delBtn.title       = "Remove";
            delBtn.onclick = function() { deleteRadioStation(station.id); };
            row.appendChild(delBtn);

            list.appendChild(row);
        })(stations[i]);
    }
}

function openAddRadioModal() {
    var modal = document.getElementById("add-radio-modal");
    if (!modal) { return; }
    _editingRadioStationId = "";
    var title = document.getElementById("radio-modal-title");
    var saveBtn = document.getElementById("radio-add");
    if (title) { title.textContent = "Add station"; }
    if (saveBtn) { saveBtn.textContent = "Add"; }
    document.getElementById("radio-name").value = "";
    document.getElementById("radio-url").value  = "";
    document.getElementById("radio-icon").value = "";
    var err = document.getElementById("radio-modal-error");
    if (err) { err.textContent = ""; err.classList.add("hidden"); }
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    document.getElementById("radio-name").focus();
}

function openEditRadioModal(station) {
    var modal = document.getElementById("add-radio-modal");
    if (!modal || !station) { return; }
    _editingRadioStationId = station.id || "";
    var title = document.getElementById("radio-modal-title");
    var saveBtn = document.getElementById("radio-add");
    if (title) { title.textContent = "Edit station"; }
    if (saveBtn) { saveBtn.textContent = "Save changes"; }
    document.getElementById("radio-name").value = station.name || "";
    document.getElementById("radio-url").value  = station.url || "";
    document.getElementById("radio-icon").value = station.icon || "";
    var err = document.getElementById("radio-modal-error");
    if (err) { err.textContent = ""; err.classList.add("hidden"); }
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    document.getElementById("radio-name").focus();
}

function closeAddRadioModal() {
    var modal = document.getElementById("add-radio-modal");
    if (!modal) { return; }
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    _editingRadioStationId = "";
    document.getElementById("radio-name").value = "";
    document.getElementById("radio-url").value  = "";
    document.getElementById("radio-icon").value = "";
    var title = document.getElementById("radio-modal-title");
    var saveBtn = document.getElementById("radio-add");
    if (title) { title.textContent = "Add station"; }
    if (saveBtn) { saveBtn.textContent = "Add"; }
}

function submitAddRadio() {
    var name = document.getElementById("radio-name").value.trim();
    var url  = document.getElementById("radio-url").value.trim();
    var icon = document.getElementById("radio-icon").value.trim();
    var err  = document.getElementById("radio-modal-error");

    if (!name || !url) {
        if (err) {
            err.textContent = "Name and URL are required.";
            err.classList.remove("hidden");
        }
        return;
    }

    if (err) { err.textContent = ""; err.classList.add("hidden"); }

    var editingId = _editingRadioStationId;
    var endpoint = editingId ? ("/api/radio/stations/" + encodeURIComponent(editingId)) : "/api/radio/stations";
    fetch(endpoint, {
        method:  editingId ? "PUT" : "POST",
        headers: {"Content-Type": "application/json"},
        body:    JSON.stringify({name: name, url: url, icon: icon})
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (data.error) {
            if (err) { err.textContent = data.error; err.classList.remove("hidden"); }
            return;
        }
        closeAddRadioModal();
        invalidateRadioSourceCache();
        loadRadioStations();
    })
    .catch(function() {
        if (err) { err.textContent = "Request failed."; err.classList.remove("hidden"); }
    });
}

function deleteRadioStation(id) {
    fetch("/api/radio/stations/" + id, {method: "DELETE"})
        .then(function() {
            invalidateRadioSourceCache();
            loadRadioStations();
        })
        .catch(function() { loadRadioStations(); });
}

function buildRadioSection() {
    var sec = document.createElement("div");
    sec.className = "settingsSection";

    var titleRow = document.createElement("div");
    titleRow.className = "settingsSectionTitle";
    titleRow.innerHTML = '<span class="material-icons">radio</span> My Radio';
    sec.appendChild(titleRow);

    var tabContent = document.createElement("div");
    tabContent.id        = "radio-settings-tab";
    var radioLastfmNote = buildLastfmFeatureNote("Automatic radio artwork uses Last.fm metadata. Connect Last.fm in Scrobbling settings and add your API key. Manually entered station icon URLs still work without Last.fm.");
    tabContent.appendChild(radioLastfmNote);

    tabContent.className = "settings-tab-content";

    var addBtn = document.createElement("button");
    addBtn.id        = "add-radio-btn";
    addBtn.className = "pill primary";
    addBtn.textContent = "Add station";
    addBtn.onclick = function() { openAddRadioModal(); };
    tabContent.appendChild(addBtn);

    var list = document.createElement("div");
    list.id = "radio-stations-list";
    tabContent.appendChild(list);

    sec.appendChild(tabContent);
    loadRadioStations();
    return sec;
}
