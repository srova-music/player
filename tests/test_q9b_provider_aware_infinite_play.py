import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.main_headless as backend


ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = (
    ROOT / "src" / "ui_web" / "ui.js"
).read_text(encoding="utf-8")


def qtrack(track_id, title, artist, album):
    native = str(track_id)
    return {
        "source": "qobuz",
        "provider_track_id": native,
        "id": "qobuz:" + native,
        "title": title,
        "artist": artist,
        "artist_id": "artist-" + artist.lower().replace(" ", "-"),
        "album": album,
        "album_id": "album-" + native,
        "duration": 180,
        "streamable": True,
        "artwork_url": "https://img/" + native + ".jpg",
        "quality": {
            "hires": False,
            "hires_streamable": False,
            "maximum_sampling_rate_khz": 44.1,
            "maximum_bit_depth": 16,
        },
    }


class FakeQobuz:
    def __init__(self, usable=True):
        self.usable = usable
        self.search_calls = []
        self.page_calls = []

    def status(self):
        return {
            "usable": self.usable,
            "authenticated": self.usable,
            "available": True,
        }

    def search_artists(
        self,
        query,
        *,
        limit=None,
        offset=None,
        search_type=None,
    ):
        self.search_calls.append(query)
        artist_id = str(
            abs(hash(query)) % 100000
            + 1
        )
        return {
            "ok": True,
            "items": [
                {
                    "source": "qobuz",
                    "artist_id": artist_id,
                    "name": query,
                }
            ],
            "total": 1,
            "offset": 0,
            "limit": 1,
        }

    def get_artist_page(self, artist_id):
        self.page_calls.append(str(artist_id))

        # Recover the search name that produced this artist page.
        artist_name = (
            self.search_calls[-1]
            if self.search_calls
            else "Artist"
        )

        base = len(self.page_calls) * 1000

        return {
            "ok": True,
            "artist_id": str(artist_id),
            "name": artist_name,
            "top_tracks": [
                qtrack(
                    base + idx,
                    f"{artist_name} Song {idx}",
                    artist_name,
                    f"{artist_name} Album {idx % 3}",
                )
                for idx in range(1, 11)
            ],
        }


def test_q9b_effective_provider_rules_preserve_saved_preference(
    monkeypatch,
):
    qobuz = FakeQobuz(True)

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(qobuz_backend=qobuz),
    )

    original_settings = backend._APP_SETTINGS
    try:
        backend._APP_SETTINGS = dict(original_settings)
        backend._APP_SETTINGS["infinite_play_provider"] = "qobuz"

        monkeypatch.setattr(
            backend,
            "_tidal_login_snapshot",
            lambda: True,
        )

        assert (
            backend._effective_infinite_play_provider()
            == "qobuz"
        )

        qobuz.usable = False

        assert (
            backend._effective_infinite_play_provider()
            == "tidal"
        )
        assert (
            backend._infinite_play_saved_provider()
            == "qobuz"
        )

        monkeypatch.setattr(
            backend,
            "_tidal_login_snapshot",
            lambda: False,
        )

        assert (
            backend._effective_infinite_play_provider()
            is None
        )

        qobuz.usable = True

        assert (
            backend._effective_infinite_play_provider()
            == "qobuz"
        )
        assert (
            backend._infinite_play_saved_provider()
            == "qobuz"
        )
    finally:
        backend._APP_SETTINGS = original_settings


def test_q9b_provider_setting_is_independent_and_persisted(
    monkeypatch,
):
    qobuz = FakeQobuz(True)

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(qobuz_backend=qobuz),
    )
    monkeypatch.setattr(
        backend,
        "_tidal_login_snapshot",
        lambda: True,
    )
    monkeypatch.setattr(
        backend,
        "_save_app_settings",
        lambda: None,
    )

    original_settings = backend._APP_SETTINGS

    try:
        backend._APP_SETTINGS = dict(original_settings)

        state = backend._set_tidal_infinite_play_settings(
            enabled=True,
            mode="surprise_me",
            provider="qobuz",
        )

        assert state["enabled"] is True
        assert state["mode"] == "surprise_me"
        assert state["provider"] == "qobuz"
        assert state["effective_provider"] == "qobuz"

        # Temporarily losing Qobuz falls back to TIDAL without
        # overwriting the saved Qobuz preference.
        qobuz.usable = False

        assert (
            backend._effective_infinite_play_provider()
            == "tidal"
        )
        assert (
            backend._infinite_play_saved_provider()
            == "qobuz"
        )

        with pytest.raises(ValueError):
            backend._set_tidal_infinite_play_settings(
                provider="spotify"
            )
    finally:
        backend._APP_SETTINGS = original_settings


@pytest.mark.parametrize(
    "mode",
    [
        "same_artist",
        "similar_artist",
        "surprise_me",
    ],
)
def test_q9b_qobuz_realizes_all_existing_modes_without_native_similarity(
    monkeypatch,
    mode,
):
    qobuz = FakeQobuz(True)

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(
            qobuz_backend=qobuz,
            backend=SimpleNamespace(),
        ),
    )

    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {
            "qobuz:900": {
                "id": "qobuz:900",
                "source": "qobuz",
                "provider_track_id": "900",
                "title": "Seed Song",
                "artist": "Seed Artist",
                "album": "Seed Album",
            }
        },
    )

    monkeypatch.setattr(
        backend,
        "_lastfm_api_key_for_recommendations",
        lambda: True,
    )

    pool_calls = []

    def fake_pool(seed_artist, requested_mode):
        pool_calls.append(
            (seed_artist, requested_mode)
        )
        return [
            "Related Artist A",
            "Related Artist B",
            "Related Artist C",
        ]

    monkeypatch.setattr(
        backend,
        "_infinite_play_artist_pool",
        fake_pool,
    )

    tracks = backend._recommended_tracks_for_seed(
        "qobuz:900",
        limit=6,
        mode=mode,
        provider="qobuz",
    )

    assert tracks
    assert all(
        track["source"] == "qobuz"
        for track in tracks
    )
    assert all(
        track["id"]
        == "qobuz:" + track["provider_track_id"]
        for track in tracks
    )

    if mode == "same_artist":
        assert pool_calls == []
        assert qobuz.search_calls[0] == "Seed Artist"
    else:
        assert pool_calls == [
            ("Seed Artist", mode)
        ]
        assert "Seed Artist" not in qobuz.search_calls[:1]


def test_q9b_qobuz_lastfm_unavailable_falls_back_to_same_artist(
    monkeypatch,
):
    qobuz = FakeQobuz(True)

    monkeypatch.setattr(
        backend,
        "APP_INSTANCE",
        SimpleNamespace(
            qobuz_backend=qobuz,
            backend=SimpleNamespace(),
        ),
    )

    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {
            "qobuz:901": {
                "id": "qobuz:901",
                "source": "qobuz",
                "provider_track_id": "901",
                "artist": "Fallback Artist",
            }
        },
    )

    monkeypatch.setattr(
        backend,
        "_lastfm_api_key_for_recommendations",
        lambda: False,
    )

    tracks = backend._recommended_tracks_for_seed(
        "qobuz:901",
        limit=5,
        mode="similar_artist",
        provider="qobuz",
    )

    assert tracks
    assert qobuz.search_calls
    assert set(qobuz.search_calls) == {
        "Fallback Artist"
    }


def test_q9b_qobuz_append_keeps_canonical_identity_and_shared_queue(
    monkeypatch,
):
    candidates = [
        qtrack(
            1001,
            "One",
            "Artist A",
            "Album A",
        ),
        qtrack(
            1002,
            "Two",
            "Artist B",
            "Album B",
        ),
        qtrack(
            1003,
            "Three",
            "Artist C",
            "Album C",
        ),
    ]

    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE",
        ["qobuz:900"],
    )
    monkeypatch.setattr(
        backend,
        "ORIGINAL_QUEUE",
        ["qobuz:900"],
    )
    monkeypatch.setattr(
        backend,
        "QUEUE_INDEX",
        0,
    )
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {
            "qobuz:900": {
                "id": "qobuz:900",
                "source": "qobuz",
                "provider_track_id": "900",
                "title": "Seed",
                "artist": "Seed Artist",
                "album": "Seed Album",
            }
        },
    )
    monkeypatch.setattr(
        backend,
        "INFINITE_PLAY_HISTORY",
        [],
    )
    monkeypatch.setattr(
        backend,
        "_recommended_tracks_for_seed",
        lambda *args, **kwargs: list(candidates),
    )
    monkeypatch.setattr(
        backend,
        "save_queue",
        lambda: None,
    )

    result = backend._append_infinite_play_recommendations(
        seed_id="qobuz:900",
        limit=3,
        autoplay=False,
        mode="similar_artist",
        provider="qobuz",
    )

    assert result["ok"] is True
    assert result["provider"] == "qobuz"
    assert result["added"] == 3

    assert backend.PLAY_QUEUE == backend.ORIGINAL_QUEUE

    generated = backend.PLAY_QUEUE[1:]
    assert len(generated) == 3

    for queue_id in generated:
        assert queue_id.startswith("qobuz:")

        meta = backend.PLAY_QUEUE_META_CACHE[
            queue_id
        ]

        assert meta["source"] == "qobuz"
        assert (
            queue_id
            == "qobuz:"
            + meta["provider_track_id"]
        )
        assert meta["id"] == queue_id
        assert meta["title"]
        assert meta["artist"]
        assert meta["album"]
        assert "quality" in meta

    assert len(backend.INFINITE_PLAY_HISTORY) == 3
    assert {
        item["id"]
        for item in backend.INFINITE_PLAY_HISTORY
    } == set(generated)


def test_q9b_wrong_provider_seed_is_rejected_before_generation(
    monkeypatch,
):
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE",
        ["100"],
    )
    monkeypatch.setattr(
        backend,
        "ORIGINAL_QUEUE",
        ["100"],
    )
    monkeypatch.setattr(
        backend,
        "QUEUE_INDEX",
        0,
    )
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {
            "100": {
                "id": "100",
                "source": "tidal",
                "artist": "Tidal Artist",
            }
        },
    )
    monkeypatch.setattr(
        backend,
        "RADIO_MODE",
        False,
    )
    monkeypatch.setattr(
        backend,
        "_tidal_infinite_play_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        backend,
        "_effective_infinite_play_provider",
        lambda: "qobuz",
    )
    monkeypatch.setattr(
        backend,
        "_INFINITE_PLAY_GENERATION_LOCK",
        threading.Lock(),
    )

    called = []

    monkeypatch.setattr(
        backend,
        "_append_infinite_play_recommendations",
        lambda *args, **kwargs: called.append(True),
    )

    result = backend._coordinated_infinite_play_refill(
        seed_id="100",
        limit=10,
        autoplay=False,
        mode="same_artist",
    )

    assert result["ok"] is False
    assert (
        result["error"]
        == "active track provider does not match Infinite Play provider"
    )
    assert called == []


def test_q9b_manual_future_queue_blocks_qobuz_refill(
    monkeypatch,
):
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE",
        [
            "qobuz:900",
            "qobuz:901",
        ],
    )
    monkeypatch.setattr(
        backend,
        "ORIGINAL_QUEUE",
        [
            "qobuz:900",
            "qobuz:901",
        ],
    )
    monkeypatch.setattr(
        backend,
        "QUEUE_INDEX",
        0,
    )
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {
            "qobuz:900": {
                "id": "qobuz:900",
                "source": "qobuz",
                "provider_track_id": "900",
                "artist": "Seed Artist",
            },
            "qobuz:901": {
                "id": "qobuz:901",
                "source": "qobuz",
                "provider_track_id": "901",
                "artist": "Manual Artist",
            },
        },
    )
    monkeypatch.setattr(
        backend,
        "RADIO_MODE",
        False,
    )
    monkeypatch.setattr(
        backend,
        "_tidal_infinite_play_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        backend,
        "_effective_infinite_play_provider",
        lambda: "qobuz",
    )
    monkeypatch.setattr(
        backend,
        "_INFINITE_PLAY_GENERATION_LOCK",
        threading.Lock(),
    )

    monkeypatch.setattr(
        backend,
        "_append_infinite_play_recommendations",
        lambda *args, **kwargs: pytest.fail(
            "manual future queue must block refill"
        ),
    )

    result = backend._coordinated_infinite_play_refill(
        seed_id="qobuz:900",
        limit=10,
        autoplay=False,
        mode="same_artist",
    )

    assert result["ok"] is True
    assert result["added"] == 0
    assert result["already_filled"] is True
    assert result["provider"] == "qobuz"


def test_q9b_qobuz_tail_eos_enters_existing_serialized_autofill(
    monkeypatch,
):
    started = []

    class FakeThread:
        def __init__(
            self,
            *,
            target=None,
            daemon=None,
            **kwargs,
        ):
            self.target = target
            self.daemon = daemon

        def start(self):
            started.append(
                (self.target, self.daemon)
            )

    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE",
        ["qobuz:900"],
    )
    monkeypatch.setattr(
        backend,
        "ORIGINAL_QUEUE",
        ["qobuz:900"],
    )
    monkeypatch.setattr(
        backend,
        "QUEUE_INDEX",
        0,
    )
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {
            "qobuz:900": {
                "id": "qobuz:900",
                "source": "qobuz",
                "provider_track_id": "900",
                "artist": "Seed Artist",
            }
        },
    )
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_PENDING_AFTER_CONTEXT",
        False,
    )
    monkeypatch.setattr(
        backend,
        "RADIO_MODE",
        False,
    )
    monkeypatch.setattr(
        backend,
        "REPEAT_MODE",
        "off",
    )
    monkeypatch.setattr(
        backend,
        "_is_local_album_playback_context",
        lambda: False,
    )
    monkeypatch.setattr(
        backend,
        "_tidal_infinite_play_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        backend,
        "_effective_infinite_play_provider",
        lambda: "qobuz",
    )
    monkeypatch.setattr(
        backend.threading,
        "Thread",
        FakeThread,
    )

    backend.play_next_track()

    assert len(started) == 1
    assert started[0][0] is backend._autofill_queue
    assert started[0][1] is True


def test_q9b_proactive_refill_uses_effective_provider_and_neutral_route():
    start = UI_SOURCE.index(
        "function maybeRefillTidalInfinitePlay(s) {"
    )
    end = UI_SOURCE.index(
        "function pollStatus() {",
        start,
    )
    block = UI_SOURCE[start:end]

    assert "s.infinite_play_effective_provider" in block
    assert "activeProvider !== effectiveProvider" in block
    assert 'effectiveProvider === "qobuz"' in block
    assert 'trackId.indexOf("qobuz:") !== 0' in block

    # Preserve the mature pre-EOS timing.
    assert "if (remaining > 60) { return; }" in block

    assert 'fetch("/api/infinite-play/refill"' in block

    # Existing retry semantics remain intact.
    assert "data.ok !== true" in block
    assert block.count(
        "releaseTidalInfinitePlayRefillKey(refillKey);"
    ) == 2


def test_q9b_qobuz_dict_candidates_reuse_existing_diversity_selector():
    candidates = [
        qtrack(1, "A1", "Artist A", "Album A"),
        qtrack(2, "A2", "Artist A", "Album B"),
        qtrack(3, "B1", "Artist B", "Album C"),
        qtrack(4, "C1", "Artist C", "Album D"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=4,
        mode="similar_artist",
        previous_entry={
            "id": "qobuz:999",
            "title": "Seed",
            "artist": "Artist A",
            "album_id": "seed",
        },
    )

    assert len(selected) == 4
    assert selected[0]["artist"] != "Artist A"

    for left, right in zip(
        selected,
        selected[1:],
    ):
        assert left["artist"] != right["artist"]


def test_q9b_settings_and_status_publish_provider_state():
    source = (
        ROOT / "src" / "main_headless.py"
    ).read_text(encoding="utf-8")

    assert (
        '"infinite_play_provider": "tidal"'
        in source
    )
    assert (
        '"infinite_play_provider": '
        "_infinite_play_saved_provider()"
        in source
    )
    assert (
        '"infinite_play_effective_provider": '
        "_effective_infinite_play_provider()"
        in source
    )
    assert (
        '"/api/settings/infinite-play"'
        in source
    )
    assert (
        '"/api/infinite-play/refill"'
        in source
    )
