from pathlib import Path
from types import SimpleNamespace

import src.main_headless as backend


ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "src" / "ui_web" / "ui.js").read_text(encoding="utf-8")
HTML = (ROOT / "src" / "ui_web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "src" / "ui_web" / "srova.css").read_text(encoding="utf-8")


class FakeSession:
    def __init__(self, tracks=None):
        self.tracks = list(tracks or [])
        self.search_calls = 0
        self.album_calls = 0

    def search(self, query, limit=30):
        self.search_calls += 1
        return {"tracks": list(self.tracks)}

    def album(self, album_id):
        self.album_calls += 1
        for track in self.tracks:
            album = getattr(track, "album", None)
            if str(getattr(album, "id", "") or "") == str(album_id):
                return album
        return SimpleNamespace(
            id=str(album_id),
            name="Resolved Album",
            artist=SimpleNamespace(name="Resolved Artist"),
        )


def tidal_track(
    title,
    artist,
    album,
    album_id,
    duration=200,
):
    artist_obj = SimpleNamespace(name=artist)
    album_obj = SimpleNamespace(
        id=str(album_id),
        name=album,
        artist=artist_obj,
    )
    return SimpleNamespace(
        name=title,
        artist=artist_obj,
        album=album_obj,
        duration=duration,
    )


def install_app(monkeypatch, session):
    app = SimpleNamespace(
        backend=SimpleNamespace(session=session),
        player=object(),
    )
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    backend._NOW_PLAYING_ALBUM_CACHE.clear()
    return app


def test_metadata_normalisation_is_strict_but_punctuation_tolerant():
    assert (
        backend._now_playing_album_norm("Don’t Stop!")
        == backend._now_playing_album_norm("Don't Stop")
    )
    assert (
        backend._now_playing_album_norm("Track (Live)")
        != backend._now_playing_album_norm("Track")
    )
    assert (
        backend._now_playing_album_norm("Track - Remix")
        != backend._now_playing_album_norm("Track")
    )


def test_local_exact_artist_title_album_and_duration_resolves(monkeypatch):
    session = FakeSession([
        tidal_track(
            "Night Drive",
            "Point Eight",
            "Midnight Roads",
            "1001",
            241,
        )
    ])
    install_app(monkeypatch, session)

    result = backend._strict_tidal_album_match(
        "local",
        "Point Eight",
        "Night Drive",
        album="Midnight Roads",
        duration=240,
    )

    assert result == "1001"
    assert session.search_calls == 1


def test_local_wrong_album_is_rejected(monkeypatch):
    session = FakeSession([
        tidal_track(
            "Night Drive",
            "Point Eight",
            "Greatest Hits",
            "1002",
            240,
        )
    ])
    install_app(monkeypatch, session)

    assert backend._strict_tidal_album_match(
        "local",
        "Point Eight",
        "Night Drive",
        album="Midnight Roads",
        duration=240,
    ) == ""


def test_local_clearly_different_duration_is_rejected(monkeypatch):
    session = FakeSession([
        tidal_track(
            "Night Drive",
            "Point Eight",
            "Midnight Roads",
            "1003",
            280,
        )
    ])
    install_app(monkeypatch, session)

    assert backend._strict_tidal_album_match(
        "local",
        "Point Eight",
        "Night Drive",
        album="Midnight Roads",
        duration=240,
    ) == ""


def test_local_two_exact_catalogue_album_ids_are_rejected(monkeypatch):
    session = FakeSession([
        tidal_track(
            "Night Drive",
            "Point Eight",
            "Midnight Roads",
            "1004",
            240,
        ),
        tidal_track(
            "Night Drive",
            "Point Eight",
            "Midnight Roads",
            "1005",
            241,
        ),
    ])
    install_app(monkeypatch, session)

    assert backend._strict_tidal_album_match(
        "local",
        "Point Eight",
        "Night Drive",
        album="Midnight Roads",
        duration=240,
    ) == ""


def test_different_artist_is_never_accepted(monkeypatch):
    session = FakeSession([
        tidal_track(
            "Night Drive",
            "Another Artist",
            "Midnight Roads",
            "1006",
            240,
        )
    ])
    install_app(monkeypatch, session)

    assert backend._strict_tidal_album_match(
        "local",
        "Point Eight",
        "Night Drive",
        album="Midnight Roads",
        duration=240,
    ) == ""


def test_radio_unique_exact_artist_title_album_is_accepted(monkeypatch):
    session = FakeSession([
        tidal_track(
            "Radio Song",
            "Point Eight",
            "Broadcast Album",
            "2001",
        )
    ])
    install_app(monkeypatch, session)

    assert backend._strict_tidal_album_match(
        "radio",
        "Point Eight",
        "Radio Song",
    ) == "2001"


def test_radio_same_song_on_multiple_album_ids_is_rejected(monkeypatch):
    session = FakeSession([
        tidal_track(
            "Radio Song",
            "Point Eight",
            "Original Album",
            "2002",
        ),
        tidal_track(
            "Radio Song",
            "Point Eight",
            "Compilation",
            "2003",
        ),
    ])
    install_app(monkeypatch, session)

    assert backend._strict_tidal_album_match(
        "radio",
        "Point Eight",
        "Radio Song",
    ) == ""


def test_direct_tidal_album_id_never_uses_search(monkeypatch):
    class NoSearchSession(FakeSession):
        def search(self, query, limit=30):
            raise AssertionError("Direct TIDAL resolution must not search")

    session = NoSearchSession()
    app = install_app(monkeypatch, session)

    monkeypatch.setattr(
        backend,
        "_tidal_login_snapshot",
        lambda: True,
    )
    monkeypatch.setattr(
        backend,
        "_status_playback_context",
        lambda player: {
            "current_track_valid": True,
            "source": "tidal",
            "context": {
                "album_id": "3001",
                "album": "Direct Album",
                "artist": "Direct Artist",
                "cover": "direct-cover",
            },
        },
    )

    result = backend._resolve_now_playing_tidal_album()

    assert app.player is not None
    assert result == {
        "available": True,
        "source": "tidal",
        "album_id": "3001",
        "album_title": "Direct Album",
        "album_artist": "Direct Artist",
        "album_cover": "direct-cover",
        "confidence": "direct",
    }


def test_logged_out_resolver_never_exposes_album(monkeypatch):
    install_app(monkeypatch, FakeSession())
    monkeypatch.setattr(
        backend,
        "_tidal_login_snapshot",
        lambda: False,
    )

    assert backend._resolve_now_playing_tidal_album() == {
        "available": False,
        "reason": "tidal_logged_out",
    }


def test_local_missing_album_metadata_is_hidden_without_search(monkeypatch):
    session = FakeSession()
    install_app(monkeypatch, session)

    monkeypatch.setattr(
        backend,
        "_tidal_login_snapshot",
        lambda: True,
    )
    monkeypatch.setattr(
        backend,
        "_status_playback_context",
        lambda player: {
            "current_track_valid": True,
            "source": "local",
            "context": {
                "artist": "Point Eight",
                "title": "Night Drive",
                "album": "",
                "duration": 240,
            },
        },
    )

    result = backend._resolve_now_playing_tidal_album()

    assert result["available"] is False
    assert result["reason"] == "local_metadata_insufficient"
    assert session.search_calls == 0


def test_unreliable_radio_metadata_is_hidden_without_search(monkeypatch):
    session = FakeSession()
    install_app(monkeypatch, session)

    monkeypatch.setattr(
        backend,
        "_tidal_login_snapshot",
        lambda: True,
    )
    monkeypatch.setattr(
        backend,
        "_status_playback_context",
        lambda player: {
            "current_track_valid": True,
            "source": "radio",
            "context": {},
        },
    )
    monkeypatch.setattr(
        backend,
        "build_current_scrobble_track",
        lambda source=None: None,
    )

    result = backend._resolve_now_playing_tidal_album()

    assert result["available"] is False
    assert result["reason"] == "radio_metadata_unreliable"
    assert session.search_calls == 0


def test_successful_local_match_is_cached(monkeypatch):
    session = FakeSession([
        tidal_track(
            "Cached Song",
            "Point Eight",
            "Cached Album",
            "4001",
            220,
        )
    ])
    install_app(monkeypatch, session)

    monkeypatch.setattr(
        backend,
        "_tidal_login_snapshot",
        lambda: True,
    )
    monkeypatch.setattr(
        backend,
        "_status_playback_context",
        lambda player: {
            "current_track_valid": True,
            "source": "local",
            "context": {
                "artist": "Point Eight",
                "title": "Cached Song",
                "album": "Cached Album",
                "duration": 220,
                "cover": "cached-cover",
            },
        },
    )

    first = backend._resolve_now_playing_tidal_album()
    second = backend._resolve_now_playing_tidal_album()

    assert first["available"] is True
    assert second["available"] is True
    assert first["album_id"] == second["album_id"] == "4001"
    assert session.search_calls == 1


def test_now_playing_album_button_is_hidden_by_default():
    assert (
        'id="npBtnAlbum" class="hidden" '
        'onclick="openNowPlayingResolvedAlbum()"'
        in HTML
    )
    assert ".hidden { display: none !important; }" in CSS
    assert "#nowPlayingView #npBtnAlbum.hidden" in CSS
    assert "display: none !important;" in CSS[
        CSS.index("#nowPlayingView #npBtnAlbum.hidden"):
        CSS.index("#nowPlayingView #npBtnAlbum.hidden") + 180
    ]


def test_watcher_hides_before_lookup_and_rejects_stale_completion():
    start = UI.index("function syncNowPlayingAlbumWatcher(s) {")
    end = UI.index(
        "function copyNowPlayingPlaybackSource() {",
        start,
    )
    block = UI[start:end]

    assert block.index("hideNowPlayingAlbumAction();") < block.index(
        '"/tidal/now-playing-album"'
    )
    assert (
        "if (serial !== nowPlayingAlbumWatchSerial) { return; }"
        in block
    )
    assert (
        "if (signature !== nowPlayingAlbumWatchKey) { return; }"
        in block
    )
    assert (
        "nowPlayingAlbumWatchSignature(latest) !== signature"
        in block
    )
    assert 'npBtnAlbum.classList.remove("hidden");' in block


def test_status_polling_drives_confidence_watcher():
    start = UI.index("function pollStatus() {")
    end = UI.index(".catch(function", start)
    block = UI[start:end]

    assert "lastKnownPlaybackStatus = s;" in block
    assert "syncNowPlayingAlbumWatcher(s);" in block
    assert block.index("lastKnownPlaybackStatus = s;") < block.index(
        "syncNowPlayingAlbumWatcher(s);"
    )


def test_logout_immediately_hides_album_action():
    start = UI.index("function updateLoginBtn(loggedIn, options) {")
    end = UI.index("function handleLoginLogout()", start)
    block = UI[start:end]

    assert "if (!loggedIn) {" in block
    assert "hideNowPlayingAlbumAction();" in block


def test_go_to_album_uses_nowplaying_as_explicit_return_state():
    start = UI.index("function openNowPlayingResolvedAlbum() {")
    end = UI.index(
        "function goBackToNowPlayingFromAlbum() {",
        start,
    )
    block = UI[start:end]

    assert "underlyingView: nowPlayingFromView || \"home\"" in block
    assert '"/tidal/album/" + resolved.albumId' in block
    assert '"nowplaying"' in block


def test_album_back_arrow_returns_to_live_now_playing():
    start = UI.index("function goBack() {")
    end = UI.index("// --- My Playlists view ---", start)
    block = UI[start:end]

    assert 'if (previousView === "nowplaying") {' in block
    assert "goBackToNowPlayingFromAlbum();" in block

    start = UI.index("function goBackToNowPlayingFromAlbum() {")
    end = UI.index("var HOME_GATEWAY_APP_PANEL_CLASS", start)
    return_block = UI[start:end]

    assert "currentSignature = nowPlayingAlbumWatchSignature(status)" in return_block
    assert "applyNowPlayingPlaybackContextFromStatus(status);" in return_block
    assert "openNowPlaying();" in return_block


def test_track_change_while_album_open_uses_latest_status_context():
    start = UI.index("function goBackToNowPlayingFromAlbum() {")
    end = UI.index("var HOME_GATEWAY_APP_PANEL_CLASS", start)
    block = UI[start:end]

    assert "state.signature === currentSignature" in block
    assert "applyNowPlayingPlaybackContextSnapshot(state);" in block
    assert "} else {" in block
    assert "applyNowPlayingPlaybackContextFromStatus(status);" in block


def test_load_track_list_does_not_reclassify_nowplaying_as_tidal_source():
    start = UI.index("function loadTrackList(context, endpoint, fromView) {")
    end = UI.index("// --- Popover", start)
    block = UI[start:end]

    assert '(fromView || "") !== "nowplaying"' in block


def test_point8_cache_marker_is_current():
    assert "/ui_web/ui.js?v=" in HTML
