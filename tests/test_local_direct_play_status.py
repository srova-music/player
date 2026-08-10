from types import SimpleNamespace

import src.main_headless as backend


SELECTED_ID = "local:selected"
OLD_ID = "local:old"
ARTWORK_URL = "/api/local/library/artwork?p=selected-cover"


def prepare_direct_play(monkeypatch, tmp_path, queue, queue_index=0):
    audio_path = tmp_path / "There Ain't No Sunshine.flac"
    audio_path.write_bytes(b"audio")
    track = {
        "id": SELECTED_ID,
        "path": str(audio_path),
        "cue_audio_path": "",
        "title": "There Ain't No Sunshine",
        "artist": "Eva Cassidy",
        "album": "Songbird",
        "duration": 220,
        "codec": "FLAC",
        "sample_rate": 44100,
        "bit_depth": 16,
        "channels": 2,
        "is_cue_track": 0,
        "cue_path": "",
        "cue_track_number": None,
        "cue_start_seconds": None,
        "cue_end_seconds": None,
    }

    class FakeLocalLibraryIndex:
        def __init__(self, roots):
            self.roots = roots

        def track_by_id(self, track_id):
            return dict(track) if track_id == SELECTED_ID else None

        def album_detail(self, **_kwargs):
            return {"artwork_url": ARTWORK_URL}

    callbacks = []
    save_calls = []
    monkeypatch.setattr(backend, "_local_test_roots", lambda: [str(tmp_path)])
    monkeypatch.setattr(backend, "local_library_rebuild_running", lambda: False)
    monkeypatch.setattr(backend, "LocalLibraryIndex", FakeLocalLibraryIndex)
    monkeypatch.setattr(
        backend,
        "_require_audio_output_for_playback",
        lambda _operation: None,
    )
    monkeypatch.setattr(
        backend,
        "_invalidate_tidal_stream_resolution",
        lambda _reason: None,
    )
    monkeypatch.setattr(
        backend.GLib,
        "idle_add",
        lambda callback: callbacks.append(callback) or 1,
    )
    monkeypatch.setattr(backend, "save_queue", lambda: save_calls.append(True))
    monkeypatch.setattr(backend, "PLAY_QUEUE", list(queue))
    monkeypatch.setattr(backend, "ORIGINAL_QUEUE", list(queue))
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {
            str(track_id): {
                "source": "local",
                "id": str(track_id),
                "title": "Fields Of Gold" if track_id == OLD_ID else track["title"],
                "artist": "Eva Cassidy",
                "album": "Songbird",
                "cover": ARTWORK_URL,
                "duration": 284 if track_id == OLD_ID else track["duration"],
            }
            for track_id in queue
        },
    )
    monkeypatch.setattr(backend, "QUEUE_INDEX", queue_index)
    monkeypatch.setattr(backend, "PLAY_QUEUE_PENDING_AFTER_CONTEXT", True)
    monkeypatch.setattr(backend, "LOCAL_PLAYBACK_ACTIVE", False)
    monkeypatch.setattr(backend, "LOCAL_PLAYBACK_CONTEXT", {})
    monkeypatch.setattr(
        backend,
        "CURRENT_CONTEXT",
        {
            "track_id": OLD_ID,
            "title": "Fields Of Gold",
            "artist": "Eva Cassidy",
            "album": "Songbird",
            "context_type": "local_queue",
        },
    )

    def apply_scheduled_playback(
        _real_path,
        _file_uri,
        _audio_ready=False,
        playback_meta=None,
    ):
        backend._set_local_playback_context(playback_meta or {})
        return False

    monkeypatch.setattr(
        backend,
        "play_local_test_file",
        apply_scheduled_playback,
    )
    return track, callbacks, save_calls


def test_direct_local_play_replaces_stale_queue_and_status(monkeypatch, tmp_path):
    track, callbacks, save_calls = prepare_direct_play(
        monkeypatch,
        tmp_path,
        [OLD_ID],
    )

    result = backend._local_library_play_payload({"id": SELECTED_ID})

    assert result["ok"] is True
    assert result["id"] == SELECTED_ID
    assert backend.PLAY_QUEUE == [SELECTED_ID]
    assert backend.ORIGINAL_QUEUE == [SELECTED_ID]
    assert backend.QUEUE_INDEX == 0
    assert backend.PLAY_QUEUE_PENDING_AFTER_CONTEXT is False
    assert backend.PLAY_QUEUE_META_CACHE[SELECTED_ID] == {
        "source": "local",
        "id": SELECTED_ID,
        "title": track["title"],
        "artist": track["artist"],
        "album": track["album"],
        "cover": ARTWORK_URL,
        "artwork_url": ARTWORK_URL,
        "duration": track["duration"],
        "quality": "LOCAL",
        "is_cue_track": 0,
        "cue_start_seconds": None,
        "cue_end_seconds": None,
    }
    assert save_calls == [True]
    assert len(callbacks) == 1

    callbacks[0]()
    status = backend._status_playback_context(
        SimpleNamespace(is_playing=lambda: True),
    )
    assert status["current_track_id"] == SELECTED_ID
    assert status["context"]["title"] == track["title"]
    assert status["context"]["artist"] == track["artist"]


def test_local_queue_play_preserves_existing_queue(monkeypatch, tmp_path):
    existing_queue = [OLD_ID, SELECTED_ID, "local:next"]
    _track, callbacks, save_calls = prepare_direct_play(
        monkeypatch,
        tmp_path,
        existing_queue,
        queue_index=1,
    )

    result = backend._local_library_play_payload({
        "id": SELECTED_ID,
        "context_type": "local_queue",
        "context_id": "queue",
        "context_title": "Play Queue",
    })

    assert result["ok"] is True
    assert backend.PLAY_QUEUE == existing_queue
    assert backend.ORIGINAL_QUEUE == existing_queue
    assert backend.QUEUE_INDEX == 1
    assert save_calls == []
    assert len(callbacks) == 1
