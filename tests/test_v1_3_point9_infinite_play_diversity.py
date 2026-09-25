import random
from types import SimpleNamespace

import src.main_headless as backend


def track(tid, title, artist, album_id, album_name=None):
    return SimpleNamespace(
        id=str(tid),
        name=title,
        artist=SimpleNamespace(name=artist),
        album=SimpleNamespace(
            id=str(album_id),
            name=album_name or str(album_id),
        ),
    )


def names(items):
    return [item.name for item in items]


def artists(items):
    return [item.artist.name for item in items]


def ids(items):
    return [str(item.id) for item in items]


def album_ids(items):
    return [str(item.album.id) for item in items]


def test_selector_removes_duplicate_ids_and_current_queue_ids():
    candidates = [
        track("1", "One", "Artist A", "a"),
        track("1", "One duplicate object", "Artist A", "a"),
        track("2", "Two", "Artist B", "b"),
        track("3", "Three", "Artist C", "c"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=10,
        mode="similar_artist",
        existing_ids={"2"},
        rng=random.Random(1),
    )

    assert ids(selected) == ["1", "3"] or ids(selected) == ["3", "1"]
    assert len(ids(selected)) == len(set(ids(selected)))
    assert "2" not in ids(selected)


def test_same_artist_spreads_albums_before_returning_to_one():
    candidates = [
        track("1", "A1", "Solo", "album-a"),
        track("2", "A2", "Solo", "album-a"),
        track("3", "B1", "Solo", "album-b"),
        track("4", "B2", "Solo", "album-b"),
        track("5", "C1", "Solo", "album-c"),
        track("6", "C2", "Solo", "album-c"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=3,
        mode="same_artist",
        rng=random.Random(2),
    )

    assert len(selected) == 3
    assert len(set(album_ids(selected))) == 3
    assert set(artists(selected)) == {"Solo"}


def test_similar_artists_uses_one_per_artist_before_second_round():
    candidates = []
    for artist_idx, artist_name in enumerate(("A", "B", "C", "D"), start=1):
        for song_idx in range(3):
            candidates.append(
                track(
                    f"{artist_idx}-{song_idx}",
                    f"{artist_name}{song_idx}",
                    artist_name,
                    f"album-{artist_name}",
                )
            )

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=4,
        mode="similar_artist",
        rng=random.Random(3),
    )

    assert len(selected) == 4
    assert len(set(artists(selected))) == 4


def test_similar_artists_never_places_same_artist_back_to_back_when_possible():
    candidates = [
        track("1", "A1", "Artist A", "a"),
        track("2", "A2", "Artist A", "a"),
        track("3", "A3", "Artist A", "b"),
        track("4", "B1", "Artist B", "c"),
        track("5", "B2", "Artist B", "d"),
        track("6", "C1", "Artist C", "e"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=6,
        mode="similar_artist",
        rng=random.Random(4),
    )

    artist_order = artists(selected)
    for left, right in zip(artist_order, artist_order[1:]):
        assert left != right


def test_surprise_me_never_places_same_artist_back_to_back_when_possible():
    candidates = [
        track("1", "A1", "Artist A", "a"),
        track("2", "A2", "Artist A", "b"),
        track("3", "B1", "Artist B", "c"),
        track("4", "B2", "Artist B", "d"),
        track("5", "C1", "Artist C", "e"),
        track("6", "C2", "Artist C", "f"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=6,
        mode="surprise_me",
        rng=random.Random(5),
    )

    artist_order = artists(selected)
    for left, right in zip(artist_order, artist_order[1:]):
        assert left != right


def test_same_song_title_covers_are_not_back_to_back():
    candidates = [
        track("1", "My Way", "Artist A", "a"),
        track("2", "My Way", "Artist B", "b"),
        track("3", "Different Song", "Artist C", "c"),
        track("4", "Another Song", "Artist D", "d"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=4,
        mode="surprise_me",
        rng=random.Random(6),
    )

    title_order = [
        backend._normalise_infinite_play_title(item.name)
        for item in selected
    ]
    for left, right in zip(title_order, title_order[1:]):
        assert left != right


def test_same_title_adjacency_rule_also_applies_to_same_artist_mode():
    candidates = [
        track("1", "Song X", "Solo", "a"),
        track("2", "Song X", "Solo", "b"),
        track("3", "Song Y", "Solo", "c"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=3,
        mode="same_artist",
        rng=random.Random(7),
    )

    title_order = [
        backend._normalise_infinite_play_title(item.name)
        for item in selected
    ]
    for left, right in zip(title_order, title_order[1:]):
        assert left != right


def test_recent_history_is_avoided_when_enough_fresh_tracks_exist():
    candidates = [
        track(str(i), f"Song {i}", f"Artist {i}", f"album-{i}")
        for i in range(1, 21)
    ]
    history = [
        {
            "id": str(i),
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "album_id": f"album-{i}",
        }
        for i in range(1, 11)
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=10,
        mode="surprise_me",
        recent_history=history,
        rng=random.Random(8),
    )

    assert set(ids(selected)) == {str(i) for i in range(11, 21)}


def test_sparse_pool_relaxes_old_history_before_new_history():
    candidates = [
        track("1", "Song 1", "Artist 1", "a"),
        track("2", "Song 2", "Artist 2", "b"),
        track("3", "Song 3", "Artist 3", "c"),
        track("4", "Song 4", "Artist 4", "d"),
    ]
    history = [
        {"id": "1", "title": "Song 1", "artist": "Artist 1", "album_id": "a"},
        {"id": "2", "title": "Song 2", "artist": "Artist 2", "album_id": "b"},
        {"id": "3", "title": "Song 3", "artist": "Artist 3", "album_id": "c"},
        {"id": "4", "title": "Song 4", "artist": "Artist 4", "album_id": "d"},
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=1,
        mode="surprise_me",
        recent_history=history,
        rng=random.Random(9),
    )

    assert ids(selected)[0] in {"1", "2"}


def test_selector_never_recycles_same_track_to_fake_full_batch():
    candidates = [
        track("1", "One", "Artist A", "a"),
        track("2", "Two", "Artist B", "b"),
        track("3", "Three", "Artist C", "c"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=10,
        mode="surprise_me",
        rng=random.Random(10),
    )

    assert len(selected) == 3
    assert len(ids(selected)) == len(set(ids(selected)))


def test_full_candidate_supply_still_returns_requested_ten_tracks():
    candidates = [
        track(
            str(i),
            f"Song {i}",
            f"Artist {i % 12}",
            f"album-{i}",
        )
        for i in range(1, 41)
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=10,
        mode="surprise_me",
        rng=random.Random(11),
    )

    assert len(selected) == 10
    assert len(ids(selected)) == 10


def test_repeated_cover_title_is_balanced_across_other_titles():
    candidates = [
        track("1", "My Way", "Artist A", "a"),
        track("2", "My Way", "Artist B", "b"),
        track("3", "My Way", "Artist C", "c"),
        track("4", "Different One", "Artist D", "d"),
        track("5", "Different Two", "Artist E", "e"),
        track("6", "Different Three", "Artist F", "f"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=6,
        mode="surprise_me",
        rng=random.Random(12),
    )

    title_order = [
        backend._normalise_infinite_play_title(item.name)
        for item in selected
    ]

    assert len(selected) == 6
    for left, right in zip(title_order, title_order[1:]):
        assert left != right


def test_first_generated_track_avoids_seed_artist_in_similar_mode():
    candidates = [
        track("1", "A Next", "Artist A", "a"),
        track("2", "B Next", "Artist B", "b"),
        track("3", "C Next", "Artist C", "c"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=3,
        mode="similar_artist",
        previous_entry={
            "id": "seed",
            "title": "Seed Song",
            "artist": "Artist A",
            "album_id": "seed-album",
        },
        rng=random.Random(13),
    )

    assert len(selected) == 3
    assert selected[0].artist.name != "Artist A"


def test_first_generated_track_avoids_seed_artist_in_surprise_mode():
    candidates = [
        track("1", "A Next", "Artist A", "a"),
        track("2", "B Next", "Artist B", "b"),
        track("3", "C Next", "Artist C", "c"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=3,
        mode="surprise_me",
        previous_entry={
            "id": "seed",
            "title": "Seed Song",
            "artist": "Artist A",
            "album_id": "seed-album",
        },
        rng=random.Random(14),
    )

    assert len(selected) == 3
    assert selected[0].artist.name != "Artist A"


def test_first_generated_track_avoids_same_song_title_cover():
    candidates = [
        track("1", "My Way", "Artist B", "a"),
        track("2", "Different Song", "Artist C", "b"),
        track("3", "Another Song", "Artist D", "c"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=3,
        mode="surprise_me",
        previous_entry={
            "id": "seed",
            "title": "My Way",
            "artist": "Artist A",
            "album_id": "seed-album",
        },
        rng=random.Random(15),
    )

    assert len(selected) == 3
    assert (
        backend._normalise_infinite_play_title(selected[0].name)
        != "my way"
    )


def test_same_artist_mode_also_avoids_seed_title_at_batch_boundary():
    candidates = [
        track("1", "Song X", "Solo", "a"),
        track("2", "Song Y", "Solo", "b"),
        track("3", "Song Z", "Solo", "c"),
    ]

    selected = backend._select_infinite_play_diverse_tracks(
        candidates,
        limit=3,
        mode="same_artist",
        previous_entry={
            "id": "seed",
            "title": "Song X",
            "artist": "Solo",
            "album_id": "seed-album",
        },
        rng=random.Random(16),
    )

    assert len(selected) == 3
    assert (
        backend._normalise_infinite_play_title(selected[0].name)
        != "song x"
    )


def test_history_recording_is_bounded_to_fifty():
    original = backend.INFINITE_PLAY_HISTORY
    try:
        backend.INFINITE_PLAY_HISTORY = []

        candidates = [
            track(
                str(i),
                f"Song {i}",
                f"Artist {i}",
                f"album-{i}",
            )
            for i in range(1, 61)
        ]

        backend._record_infinite_play_history_tracks(candidates)

        assert len(backend.INFINITE_PLAY_HISTORY) == 50
        assert backend.INFINITE_PLAY_HISTORY[0]["id"] == "11"
        assert backend.INFINITE_PLAY_HISTORY[-1]["id"] == "60"
    finally:
        backend.INFINITE_PLAY_HISTORY = original


def test_queue_save_and_load_persists_infinite_play_history(
    monkeypatch,
    tmp_path,
):
    queue_file = tmp_path / "queue.json"

    monkeypatch.setattr(backend, "_QUEUE_FILE", str(queue_file))
    monkeypatch.setattr(backend, "PLAY_QUEUE", ["100"])
    monkeypatch.setattr(backend, "ORIGINAL_QUEUE", ["100"])
    monkeypatch.setattr(backend, "QUEUE_INDEX", 0)
    monkeypatch.setattr(backend, "REPEAT_MODE", "off")
    monkeypatch.setattr(backend, "SHUFFLE_ON", False)
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {
            "100": {
                "id": "100",
                "title": "Seed",
                "artist": "Seed Artist",
            }
        },
    )
    monkeypatch.setattr(
        backend,
        "INFINITE_PLAY_HISTORY",
        [
            {
                "id": str(i),
                "title": f"Song {i}",
                "artist": f"Artist {i}",
                "album_id": f"album-{i}",
            }
            for i in range(1, 61)
        ],
    )

    save_thread = backend.save_queue()
    save_thread.join(timeout=2.0)
    assert not save_thread.is_alive()

    backend.INFINITE_PLAY_HISTORY.clear()
    backend.load_queue()

    assert len(backend.INFINITE_PLAY_HISTORY) == 50
    assert backend.INFINITE_PLAY_HISTORY[0]["id"] == "11"
    assert backend.INFINITE_PLAY_HISTORY[-1]["id"] == "60"


def test_live_append_uses_diversity_selector_and_records_history(
    monkeypatch,
):
    candidates = [
        track("1", "Seed Artist Song", "Seed Artist", "a"),
        track("2", "Artist B Song", "Artist B", "b"),
        track("3", "Artist C Song", "Artist C", "c"),
        track("4", "Artist D Song", "Artist D", "d"),
    ]

    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE",
        ["seed"],
    )
    monkeypatch.setattr(
        backend,
        "ORIGINAL_QUEUE",
        ["seed"],
    )
    monkeypatch.setattr(backend, "QUEUE_INDEX", 0)
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {
            "seed": {
                "id": "seed",
                "title": "Seed Song",
                "artist": "Seed Artist",
                "source": "tidal",
            }
        },
    )
    monkeypatch.setattr(backend, "INFINITE_PLAY_HISTORY", [])
    monkeypatch.setattr(
        backend,
        "_recommended_tracks_for_seed",
        lambda *args, **kwargs: list(candidates),
    )
    monkeypatch.setattr(backend, "save_queue", lambda: None)
    monkeypatch.setattr(backend, "_quality_badge", lambda _track: "LOSSLESS")

    result = backend._append_infinite_play_recommendations(
        seed_id="seed",
        limit=4,
        autoplay=False,
        mode="similar_artist",
        provider="tidal",
    )

    assert result["ok"] is True
    assert result["added"] == 4

    generated = backend.PLAY_QUEUE[1:]
    generated_artists = [
        backend.PLAY_QUEUE_META_CACHE[tid]["artist"]
        for tid in generated
    ]

    # Cross-boundary Similar Artists rule: the first recommendation must not
    # repeat the seed artist while another artist is available.
    assert generated_artists[0] != "Seed Artist"

    for left, right in zip(
        generated_artists,
        generated_artists[1:],
    ):
        assert left != right

    assert len(backend.INFINITE_PLAY_HISTORY) == 4
    assert {
        entry["id"]
        for entry in backend.INFINITE_PLAY_HISTORY
    } == set(generated)


def test_recent_persisted_history_changes_next_batch_selection(
    monkeypatch,
):
    candidates = [
        track(
            str(i),
            f"Song {i}",
            f"Artist {i}",
            f"album-{i}",
        )
        for i in range(1, 21)
    ]

    monkeypatch.setattr(backend, "PLAY_QUEUE", ["seed"])
    monkeypatch.setattr(backend, "ORIGINAL_QUEUE", ["seed"])
    monkeypatch.setattr(backend, "QUEUE_INDEX", 0)
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {
            "seed": {
                "id": "seed",
                "title": "Seed",
                "artist": "Seed Artist",
                "source": "tidal",
            }
        },
    )
    monkeypatch.setattr(
        backend,
        "INFINITE_PLAY_HISTORY",
        [
            {
                "id": str(i),
                "title": f"Song {i}",
                "artist": f"Artist {i}",
                "album_id": f"album-{i}",
            }
            for i in range(1, 11)
        ],
    )
    monkeypatch.setattr(
        backend,
        "_recommended_tracks_for_seed",
        lambda *args, **kwargs: list(candidates),
    )
    monkeypatch.setattr(backend, "save_queue", lambda: None)
    monkeypatch.setattr(backend, "_quality_badge", lambda _track: "LOSSLESS")

    result = backend._append_infinite_play_recommendations(
        seed_id="seed",
        limit=10,
        autoplay=False,
        mode="surprise_me",
        provider="tidal",
    )

    assert result["ok"] is True
    assert result["added"] == 10
    assert set(backend.PLAY_QUEUE[1:]) == {
        str(i)
        for i in range(11, 21)
    }


def test_queue_replace_does_not_clear_infinite_play_history():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "main_headless.py"
    ).read_text(encoding="utf-8")

    start = source.index('if self.path == "/tidal/queue/replace":')
    end = source.index(
        '# -- Queue: append tracks to end',
        start,
    )
    block = source[start:end]

    assert "PLAY_QUEUE.clear()" in block
    assert "PLAY_QUEUE_META_CACHE.clear()" in block
    assert "INFINITE_PLAY_HISTORY.clear()" not in block
