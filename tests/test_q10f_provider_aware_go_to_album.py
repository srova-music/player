from pathlib import Path
from types import SimpleNamespace

import pytest

import src.main_headless as backend


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "src" / "main_headless.py").read_text(encoding="utf-8")
UI = (ROOT / "src" / "ui_web" / "ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "src" / "ui_web" / "srova.css").read_text(encoding="utf-8")


class FakeQobuzBackend:
    def __init__(
        self,
        *,
        authenticated=True,
        tracks=None,
        track_detail=None,
    ):
        self.authenticated = authenticated
        self.tracks = list(tracks or [])
        self.track_detail = dict(track_detail or {})
        self.search_calls = 0
        self.get_track_calls = 0

    def status(self):
        return {
            "authenticated": bool(self.authenticated),
        }

    def search_tracks(
        self,
        query,
        *,
        limit=None,
        offset=None,
        search_type=None,
    ):
        self.search_calls += 1
        return {
            "ok": True,
            "items": list(self.tracks),
            "offset": int(offset or 0),
            "limit": int(limit or 30),
            "total": len(self.tracks),
        }

    def get_track(self, track_id):
        self.get_track_calls += 1
        result = dict(self.track_detail)
        result.setdefault(
            "provider_track_id",
            str(track_id),
        )
        result.setdefault(
            "id",
            "qobuz:" + str(track_id),
        )
        return result


def install_app(
    monkeypatch,
    *,
    qobuz_backend=None,
    tidal_session=None,
):
    app = SimpleNamespace(
        backend=SimpleNamespace(
            session=tidal_session,
        ),
        qobuz_backend=qobuz_backend,
        player=object(),
    )
    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        app,
    )
    return app


def qobuz_track(
    *,
    title="Night Drive",
    artist="Point Ten",
    album="Midnight Roads",
    album_id="qb-album-1",
    duration=240,
    track_id="101",
):
    return {
        "source": "qobuz",
        "provider_track_id": str(track_id),
        "id": "qobuz:" + str(track_id),
        "title": title,
        "artist": artist,
        "album": album,
        "album_id": album_id,
        "duration": duration,
        "artwork_url": "qobuz-cover",
        "isrc": "GBQ101234567",
    }


def destination(
    provider,
    album_id,
):
    return {
        "available": True,
        "provider": provider,
        "album_id": album_id,
        "album_title": provider.upper() + " Album",
        "album_artist": "Point Ten",
        "album_cover": provider + "-cover",
        "confidence": "strict_metadata",
    }


def active_playback(source="local"):
    return {
        "playback_state": "playing",
        "current_track_valid": True,
        "source": source,
        "current_track_id": (
            "qobuz:101"
            if source == "qobuz"
            else "local:test"
        ),
        "context": {
            "track_id": (
                "qobuz:101"
                if source == "qobuz"
                else "local:test"
            ),
            "artist": "Point Ten",
            "title": "Night Drive",
            "album": "Midnight Roads",
            "album_id": (
                "qb-native-album"
                if source == "qobuz"
                else ""
            ),
            "duration": 240,
            "cover": "current-cover",
        },
    }


def test_native_qobuz_track_id_accepts_canonical_identity():
    playback = {
        "current_track_id": "qobuz:12345",
        "context": {},
    }
    assert (
        backend._q10f_qobuz_native_track_id(
            playback
        )
        == "12345"
    )


def test_qobuz_direct_album_id_does_not_fetch_track(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        authenticated=True,
    )
    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    playback = active_playback("qobuz")

    result = (
        backend._resolve_now_playing_qobuz_album(
            playback
        )
    )

    assert result["available"] is True
    assert result["provider"] == "qobuz"
    assert result["album_id"] == "qb-native-album"
    assert result["confidence"] == "direct"
    assert qb.get_track_calls == 0
    assert qb.search_calls == 0


def test_qobuz_native_track_fallback_supplies_album_identity(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        authenticated=True,
        track_detail=qobuz_track(
            album_id="qb-fetched-album",
        ),
    )
    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    playback = active_playback("qobuz")
    playback["context"]["album_id"] = ""
    playback["context"]["album"] = ""
    playback["context"]["title"] = ""

    result = (
        backend._resolve_now_playing_qobuz_album(
            playback
        )
    )

    assert result["available"] is True
    assert result["album_id"] == "qb-fetched-album"
    assert result["confidence"] == "native_track"
    assert qb.get_track_calls == 1


def test_qobuz_logged_out_never_searches(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        authenticated=False,
        tracks=[
            qobuz_track(),
        ],
    )
    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    result = (
        backend._resolve_now_playing_qobuz_album(
            active_playback("local")
        )
    )

    assert result["available"] is False
    assert result["reason"] == "qobuz_logged_out"
    assert qb.search_calls == 0
    assert qb.get_track_calls == 0


def test_qobuz_exact_cross_provider_match_is_accepted(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        tracks=[
            qobuz_track(
                album_id="qb-exact",
                duration=241,
            ),
            qobuz_track(
                title="Night Drive",
                artist="Point Ten",
                album="Wrong Release",
                album_id="qb-wrong",
                duration=240,
                track_id="102",
            ),
        ],
    )
    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    result = backend._q10f_strict_qobuz_album_match(
        "local",
        "Point Ten",
        "Night Drive",
        album="Midnight Roads",
        duration=240,
    )

    assert result is not None
    assert result["album_id"] == "qb-exact"
    assert qb.search_calls == 1


def test_qobuz_wrong_release_is_rejected(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        tracks=[
            qobuz_track(
                album="Deluxe Edition",
                album_id="qb-deluxe",
            ),
        ],
    )
    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    assert (
        backend._q10f_strict_qobuz_album_match(
            "local",
            "Point Ten",
            "Night Drive",
            album="Midnight Roads",
            duration=240,
        )
        is None
    )



def test_qobuz_multiple_exact_album_ids_choose_deterministically(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        tracks=[
            qobuz_track(
                album_id="qb-b",
                track_id="101",
            ),
            qobuz_track(
                album_id="qb-a",
                track_id="102",
            ),
        ],
    )

    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    result = backend._q10f_strict_qobuz_album_match(
        "local",
        "Point Ten",
        "Night Drive",
        album="Midnight Roads",
        duration=240,
    )

    assert result is not None
    assert result["album_id"] == "qb-a"
    assert result["confidence"] == "strict_metadata"

@pytest.mark.parametrize(
    (
        "tidal_result",
        "qobuz_result",
        "expected_available",
        "expected_tidal",
        "expected_qobuz",
    ),
    [
        (
            destination("tidal", "t-1"),
            {
                "available": False,
                "provider": "qobuz",
                "reason": "no_confident_match",
            },
            True,
            True,
            False,
        ),
        (
            {
                "available": False,
                "provider": "tidal",
                "reason": "no_confident_match",
            },
            destination("qobuz", "q-1"),
            True,
            False,
            True,
        ),
        (
            destination("tidal", "t-2"),
            destination("qobuz", "q-2"),
            True,
            True,
            True,
        ),
        (
            {
                "available": False,
                "provider": "tidal",
                "reason": "no_confident_match",
            },
            {
                "available": False,
                "provider": "qobuz",
                "reason": "no_confident_match",
            },
            False,
            False,
            False,
        ),
    ],
)
def test_provider_neutral_four_result_states(
    monkeypatch,
    tidal_result,
    qobuz_result,
    expected_available,
    expected_tidal,
    expected_qobuz,
):
    install_app(
        monkeypatch,
        qobuz_backend=FakeQobuzBackend(),
    )

    playback = active_playback("local")

    monkeypatch.setattr(
        backend,
        "_status_playback_context",
        lambda player: playback,
    )
    monkeypatch.setattr(
        backend,
        "_resolve_now_playing_tidal_album",
        lambda: dict(tidal_result),
    )
    monkeypatch.setattr(
        backend,
        "_resolve_now_playing_qobuz_album",
        lambda playback=None: dict(qobuz_result),
    )

    result = (
        backend._resolve_now_playing_album_destinations()
    )

    assert result["available"] is expected_available
    assert (
        result["tidal"].get("available") is True
    ) is expected_tidal
    assert (
        result["qobuz"].get("available") is True
    ) is expected_qobuz


def test_qobuz_failure_does_not_suppress_tidal(
    monkeypatch,
):
    install_app(
        monkeypatch,
        qobuz_backend=FakeQobuzBackend(),
    )

    monkeypatch.setattr(
        backend,
        "_status_playback_context",
        lambda player: active_playback("local"),
    )
    monkeypatch.setattr(
        backend,
        "_resolve_now_playing_tidal_album",
        lambda: destination(
            "tidal",
            "tidal-safe",
        ),
    )

    def fail_qobuz(playback=None):
        raise RuntimeError("qobuz down")

    monkeypatch.setattr(
        backend,
        "_resolve_now_playing_qobuz_album",
        fail_qobuz,
    )

    result = (
        backend._resolve_now_playing_album_destinations()
    )

    assert result["available"] is True
    assert result["tidal"]["available"] is True
    assert (
        result["tidal"]["album_id"]
        == "tidal-safe"
    )
    assert result["qobuz"] == {
        "available": False,
        "provider": "qobuz",
        "reason": "provider_error",
    }


def test_tidal_failure_does_not_suppress_qobuz(
    monkeypatch,
):
    install_app(
        monkeypatch,
        qobuz_backend=FakeQobuzBackend(),
    )

    monkeypatch.setattr(
        backend,
        "_status_playback_context",
        lambda player: active_playback("local"),
    )

    def fail_tidal():
        raise RuntimeError("tidal down")

    monkeypatch.setattr(
        backend,
        "_resolve_now_playing_tidal_album",
        fail_tidal,
    )
    monkeypatch.setattr(
        backend,
        "_resolve_now_playing_qobuz_album",
        lambda playback=None: destination(
            "qobuz",
            "qobuz-safe",
        ),
    )

    result = (
        backend._resolve_now_playing_album_destinations()
    )

    assert result["available"] is True
    assert result["qobuz"]["available"] is True
    assert (
        result["qobuz"]["album_id"]
        == "qobuz-safe"
    )
    assert result["tidal"] == {
        "available": False,
        "provider": "tidal",
        "reason": "provider_error",
    }


def test_qobuz_source_resolves_both_providers_independently(
    monkeypatch,
):
    install_app(
        monkeypatch,
        qobuz_backend=FakeQobuzBackend(),
    )

    playback = active_playback("qobuz")

    monkeypatch.setattr(
        backend,
        "_status_playback_context",
        lambda player: playback,
    )
    monkeypatch.setattr(
        backend,
        "_resolve_now_playing_tidal_for_qobuz",
        lambda current: destination(
            "tidal",
            "tidal-cross",
        ),
    )
    monkeypatch.setattr(
        backend,
        "_resolve_now_playing_qobuz_album",
        lambda current=None: destination(
            "qobuz",
            "qobuz-native",
        ),
    )

    result = (
        backend._resolve_now_playing_album_destinations()
    )

    assert result["source"] == "qobuz"
    assert (
        result["tidal"]["album_id"]
        == "tidal-cross"
    )
    assert (
        result["qobuz"]["album_id"]
        == "qobuz-native"
    )


def test_new_endpoint_coexists_with_locked_tidal_endpoint():
    assert (
        'static_path == "/now-playing-albums"'
        in MAIN
    )
    assert (
        "_resolve_now_playing_album_destinations()"
        in MAIN
    )
    assert (
        'static_path == "/tidal/now-playing-album"'
        in MAIN
    )
    assert (
        "_resolve_now_playing_tidal_album()"
        in MAIN
    )


def test_frontend_watcher_uses_provider_neutral_endpoint_and_stale_guards():
    start = UI.index(
        "function syncNowPlayingAlbumWatcher(s) {"
    )
    end = UI.index(
        "function copyNowPlayingPlaybackSource() {",
        start,
    )
    block = UI[start:end]
    compact = "".join(block.split())

    assert (
        'fetchWithTimeout("/now-playing-albums"'
        in compact
    )
    assert (
        "serial!==nowPlayingAlbumWatchSerial"
        in compact
    )
    assert (
        "signature!==nowPlayingAlbumWatchKey"
        in compact
    )
    assert (
        "nowPlayingAlbumWatchSignature(latest)!==signature"
        in compact
    )
    assert (
        "tidal:q10fNormalizeAlbumDestination"
        not in compact
    )
    assert (
        'q10fNormalizeAlbumDestination("tidal",data.tidal,latest)'
        in compact
    )
    assert (
        'q10fNormalizeAlbumDestination("qobuz",data.qobuz,latest)'
        in compact
    )


def test_frontend_single_result_navigates_directly_and_both_show_chooser():
    start = UI.index(
        "function openNowPlayingResolvedAlbum() {"
    )
    end = UI.index(
        "function goBackToNowPlayingFromAlbum() {",
        start,
    )
    block = UI[start:end]
    compact = "".join(block.split())

    assert (
        "if(count>1){showNowPlayingAlbumProviderMenu();return;}"
        in compact
    )
    assert (
        'openNowPlayingAlbumDestination(resolved.tidal?"tidal":"qobuz");'
        in compact
    )


def test_frontend_navigation_reuses_existing_provider_album_pages():
    start = UI.index(
        "function openNowPlayingAlbumDestination("
    )
    end = UI.index(
        "function openNowPlayingResolvedAlbum() {",
        start,
    )
    block = UI[start:end]
    compact = "".join(block.split())

    assert (
        "loadQobuzAlbumDetail("
        in block
    )
    assert (
        '"/tidal/album/"+destination.albumId'
        in compact
    )
    assert '"nowplaying"' in block


def test_provider_choice_text_is_centered_both_axes():
    start = CSS.index(
        ".nowPlayingAlbumProviderMenu\n"
        ".playerInfinitePlayMenuBtn {"
    )
    block = CSS[start:start + 500]

    assert (
        "align-items: center !important;"
        in block
    )
    assert (
        "justify-content: center !important;"
        in block
    )
    assert (
        "text-align: center !important;"
        in block
    )


def test_q10f_does_not_create_provider_preference():
    q10f_ui_start = UI.index(
        "function ensureNowPlayingAlbumProviderMenu()"
    )
    q10f_ui_end = UI.index(
        "function goBackToNowPlayingFromAlbum()",
        q10f_ui_start,
    )
    block = UI[q10f_ui_start:q10f_ui_end].lower()

    assert "localstorage" not in block
    assert "save" not in block
    assert "preference" not in block


def test_tidal_source_can_resolve_qobuz_album(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        authenticated=True,
        tracks=[
            qobuz_track(
                album_id="qb-from-tidal",
                duration=240,
            ),
        ],
    )
    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    playback = {
        "playback_state": "playing",
        "current_track_valid": True,
        "source": "tidal",
        "current_track_id": "tidal-track-1",
        "context": {
            "artist": "Point Ten",
            "title": "Night Drive",
            "album": "Midnight Roads",
            "album_id": "tidal-album-1",
            "duration": 240,
            "cover": "tidal-cover",
        },
    }

    result = (
        backend._resolve_now_playing_qobuz_album(
            playback
        )
    )

    assert result["available"] is True
    assert result["provider"] == "qobuz"
    assert result["source"] == "tidal"
    assert result["album_id"] == "qb-from-tidal"
    assert qb.search_calls == 1


def test_radio_source_can_resolve_one_exact_qobuz_album(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        authenticated=True,
        tracks=[
            qobuz_track(
                title="Radio Song",
                artist="Point Ten",
                album="Broadcast Album",
                album_id="qb-radio",
                track_id="201",
            ),
        ],
    )
    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    playback = {
        "playback_state": "playing",
        "current_track_valid": True,
        "source": "radio",
        "current_track_id": None,
        "context": {},
    }

    monkeypatch.setattr(
        backend,
        "build_current_scrobble_track",
        lambda source=None: {
            "source": "radio",
            "id": "radio:test",
            "artist": "Point Ten",
            "title": "Radio Song",
            "album": "Broadcast Album",
            "duration": 0,
        },
    )

    result = (
        backend._resolve_now_playing_qobuz_album(
            playback
        )
    )

    assert result["available"] is True
    assert result["provider"] == "qobuz"
    assert result["source"] == "radio"
    assert result["album_id"] == "qb-radio"
    assert qb.search_calls == 1


def test_unreliable_radio_metadata_never_searches_qobuz(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        authenticated=True,
        tracks=[
            qobuz_track(
                album_id="must-not-be-used",
            ),
        ],
    )
    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    playback = {
        "playback_state": "playing",
        "current_track_valid": True,
        "source": "radio",
        "current_track_id": None,
        "context": {},
    }

    monkeypatch.setattr(
        backend,
        "build_current_scrobble_track",
        lambda source=None: None,
    )

    result = (
        backend._resolve_now_playing_qobuz_album(
            playback
        )
    )

    assert result["available"] is False
    assert result["reason"] == "radio_metadata_unreliable"
    assert qb.search_calls == 0



def test_q10f_static_asset_tokens_are_current():
    index = (
        ROOT / "src" / "ui_web" / "index.html"
    ).read_text(encoding="utf-8")

    assert (
        "/ui_web/srova.css?"
        "v=20260914_v2_0_q10d_auth_ux_css2_q10f_provider_aware_go_to_album_css3"
        in index
    )

    assert (
        "q10e_qobuz_lyrics_js11_"
        "q10f_provider_aware_go_to_album_js12"
        in index
    )

    assert index.count("/ui_web/srova.css?v=") == 1
    assert index.count("/ui_web/ui.js?v=") == 1



def test_album_family_normalization_accepts_remaster_qualifier():
    assert (
        backend._q10f_album_family_norm(
            "Come Away With Me (Remastered)"
        )
        == backend._q10f_album_family_norm(
            "Come Away With Me"
        )
    )

    assert (
        backend._q10f_album_family_norm(
            "Come Away With Me - 20th Anniversary Edition"
        )
        == backend._q10f_album_family_norm(
            "Come Away With Me"
        )
    )


def test_album_family_normalization_does_not_strip_meaningful_title_text():
    assert (
        backend._q10f_album_family_norm(
            "Live at the Village Vanguard"
        )
        != backend._q10f_album_family_norm(
            "Live"
        )
    )


def test_qobuz_cross_provider_accepts_unique_remastered_album_family(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        authenticated=True,
        tracks=[
            qobuz_track(
                title="Don't Know Why",
                artist="Norah Jones",
                album="Come Away With Me",
                album_id="qobuz-norah",
                duration=186,
            ),
        ],
    )

    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    result = backend._q10f_strict_qobuz_album_match(
        "tidal",
        "Norah Jones",
        "Don't Know Why",
        album="Come Away With Me (Remastered)",
        duration=186,
    )

    assert result is not None
    assert result["album_id"] == "qobuz-norah"
    assert result["confidence"] == "album_family"


def test_qobuz_exact_album_match_wins_over_family_alternative(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        authenticated=True,
        tracks=[
            qobuz_track(
                title="Don't Know Why",
                artist="Norah Jones",
                album="Come Away With Me (Remastered)",
                album_id="qobuz-exact",
                duration=186,
                track_id="301",
            ),
            qobuz_track(
                title="Don't Know Why",
                artist="Norah Jones",
                album="Come Away With Me",
                album_id="qobuz-family",
                duration=186,
                track_id="302",
            ),
        ],
    )

    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    result = backend._q10f_strict_qobuz_album_match(
        "tidal",
        "Norah Jones",
        "Don't Know Why",
        album="Come Away With Me (Remastered)",
        duration=186,
    )

    assert result is not None
    assert result["album_id"] == "qobuz-exact"
    assert result["confidence"] == "strict_metadata"



def test_qobuz_multiple_album_family_editions_choose_plain_release(
    monkeypatch,
):
    qb = FakeQobuzBackend(
        authenticated=True,
        tracks=[
            qobuz_track(
                title="Don't Know Why",
                artist="Norah Jones",
                album="Come Away With Me (Deluxe Edition)",
                album_id="qobuz-deluxe",
                duration=186,
                track_id="401",
            ),
            qobuz_track(
                title="Don't Know Why",
                artist="Norah Jones",
                album="Come Away With Me",
                album_id="qobuz-plain",
                duration=186,
                track_id="402",
            ),
        ],
    )

    install_app(
        monkeypatch,
        qobuz_backend=qb,
    )

    result = backend._q10f_strict_qobuz_album_match(
        "tidal",
        "Norah Jones",
        "Don't Know Why",
        album="Come Away With Me (2022 Remaster)",
        duration=186,
    )

    assert result is not None
    assert result["album_id"] == "qobuz-plain"
    assert result["confidence"] == "album_family"

def test_tidal_cross_provider_accepts_unique_album_family(
    monkeypatch,
):
    artist = SimpleNamespace(name="Norah Jones")
    album = SimpleNamespace(
        id="tidal-norah",
        name="Come Away With Me (Remastered)",
        artist=artist,
    )
    track = SimpleNamespace(
        name="Don't Know Why",
        artist=artist,
        album=album,
        duration=186,
    )

    class Session:
        def search(self, query, limit=30):
            return {
                "tracks": [track],
            }

    install_app(
        monkeypatch,
        qobuz_backend=FakeQobuzBackend(),
        tidal_session=Session(),
    )

    result = (
        backend._q10f_strict_tidal_cross_provider_match(
            "Norah Jones",
            "Don't Know Why",
            "Come Away With Me",
            duration=186,
        )
    )

    assert result == "tidal-norah"



def test_tidal_multiple_album_family_editions_choose_plain_release(
    monkeypatch,
):
    artist = SimpleNamespace(
        name="Norah Jones"
    )

    plain_album = SimpleNamespace(
        id="100",
        name="Come Away With Me",
        artist=artist,
    )

    deluxe_album = SimpleNamespace(
        id="200",
        name="Come Away With Me (Deluxe Edition)",
        artist=artist,
    )

    plain_track = SimpleNamespace(
        name="Don't Know Why",
        artist=artist,
        album=plain_album,
        duration=186,
    )

    deluxe_track = SimpleNamespace(
        name="Don't Know Why",
        artist=artist,
        album=deluxe_album,
        duration=186,
    )

    class Session:
        def search(self, query, limit=30):
            # Deliberately put the less-preferred edition first.
            return {
                "tracks": [
                    deluxe_track,
                    plain_track,
                ],
            }

    install_app(
        monkeypatch,
        qobuz_backend=FakeQobuzBackend(),
        tidal_session=Session(),
    )

    result = (
        backend._q10f_strict_tidal_cross_provider_match(
            "Norah Jones",
            "Don't Know Why",
            "Come Away With Me (2022 Remaster)",
            duration=186,
        )
    )

    assert result == "100"
