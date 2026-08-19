import threading
import time
from pathlib import Path

import pytest

import src.main_headless as backend


ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = (ROOT / "src" / "ui_web" / "ui.js").read_text(encoding="utf-8")


def prepare_backend(monkeypatch):
    monkeypatch.setattr(backend, "PLAY_QUEUE", ["100"])
    monkeypatch.setattr(backend, "ORIGINAL_QUEUE", ["100"])
    monkeypatch.setattr(backend, "QUEUE_INDEX", 0)
    monkeypatch.setattr(
        backend,
        "PLAY_QUEUE_META_CACHE",
        {"100": {"source": "tidal", "artist": "Point Seven"}},
    )
    monkeypatch.setattr(backend, "RADIO_MODE", False)
    monkeypatch.setattr(backend, "_tidal_infinite_play_enabled", lambda: True)
    monkeypatch.setattr(
        backend,
        "_INFINITE_PLAY_GENERATION_LOCK",
        threading.Lock(),
    )


@pytest.mark.parametrize(
    "mode",
    ["same_artist", "similar_artist", "surprise_me"],
)
def test_generation_coordinator_preserves_all_three_infinite_play_modes(
    monkeypatch,
    mode,
):
    prepare_backend(monkeypatch)
    calls = []

    def fake_append(seed_id=None, limit=10, autoplay=False, mode=None):
        calls.append(
            {
                "seed_id": seed_id,
                "limit": limit,
                "autoplay": autoplay,
                "mode": mode,
            }
        )
        return {
            "ok": True,
            "added": 10,
            "mode": mode,
            "queue_length": 11,
        }

    monkeypatch.setattr(
        backend,
        "_append_infinite_play_recommendations",
        fake_append,
    )

    result = backend._coordinated_infinite_play_refill(
        seed_id="100",
        limit=10,
        autoplay=False,
        mode=mode,
    )

    assert result["ok"] is True
    assert calls == [
        {
            "seed_id": "100",
            "limit": 10,
            "autoplay": False,
            "mode": mode,
        }
    ]


def test_eos_waits_for_existing_generation_then_plays_first_appended_track(
    monkeypatch,
):
    prepare_backend(monkeypatch)

    generation_started = threading.Event()
    release_generation = threading.Event()
    append_calls = []
    played_indexes = []
    proactive_result = {}
    eos_result = {}

    def fake_append(seed_id=None, limit=10, autoplay=False, mode=None):
        append_calls.append((seed_id, limit, autoplay, mode))
        generation_started.set()
        assert release_generation.wait(timeout=2.0)
        backend.PLAY_QUEUE.append("200")
        backend.ORIGINAL_QUEUE.append("200")
        return {
            "ok": True,
            "added": 1,
            "mode": mode,
            "queue_length": len(backend.PLAY_QUEUE),
        }

    def fake_idle_add(callback, *args):
        return callback(*args)

    monkeypatch.setattr(
        backend,
        "_append_infinite_play_recommendations",
        fake_append,
    )
    monkeypatch.setattr(
        backend,
        "play_queue_index",
        lambda index: played_indexes.append(index),
    )
    monkeypatch.setattr(backend.GLib, "idle_add", fake_idle_add)

    def proactive():
        proactive_result.update(
            backend._coordinated_infinite_play_refill(
                seed_id="100",
                limit=10,
                autoplay=False,
                mode="similar_artist",
            )
        )

    def eos():
        eos_result.update(
            backend._coordinated_infinite_play_refill(
                limit=10,
                autoplay=True,
                mode="similar_artist",
            )
        )

    proactive_thread = threading.Thread(target=proactive)
    proactive_thread.start()

    assert generation_started.wait(timeout=2.0)

    eos_thread = threading.Thread(target=eos)
    eos_thread.start()

    time.sleep(0.05)
    assert len(append_calls) == 1
    assert eos_thread.is_alive()

    release_generation.set()

    proactive_thread.join(timeout=2.0)
    eos_thread.join(timeout=2.0)

    assert not proactive_thread.is_alive()
    assert not eos_thread.is_alive()

    # The EOS path must not create Batch B. It should observe Batch A and
    # play its first item.
    assert len(append_calls) == 1
    assert proactive_result["added"] == 1
    assert eos_result["added"] == 0
    assert eos_result["already_filled"] is True
    assert played_indexes == [1]


def test_second_client_does_not_generate_duplicate_batch(monkeypatch):
    prepare_backend(monkeypatch)
    backend.PLAY_QUEUE.append("200")
    backend.ORIGINAL_QUEUE.append("200")

    def should_not_generate(*args, **kwargs):
        raise AssertionError("duplicate Infinite Play generation attempted")

    monkeypatch.setattr(
        backend,
        "_append_infinite_play_recommendations",
        should_not_generate,
    )

    result = backend._coordinated_infinite_play_refill(
        seed_id="100",
        limit=10,
        autoplay=False,
        mode="surprise_me",
    )

    assert result["ok"] is True
    assert result["added"] == 0
    assert result["already_filled"] is True
    assert result["queue_length"] == 2


def test_ui_failed_refill_becomes_retryable_without_changing_timing():
    start = UI_SOURCE.index("function maybeRefillTidalInfinitePlay(s) {")
    end = UI_SOURCE.index("function pollStatus() {", start)
    block = UI_SOURCE[start:end]

    # Preserve the existing pre-EOS behavior exactly.
    assert "if (remaining > 60) { return; }" in block

    # Both an API-level failure and a fetch failure must release the key,
    # allowing the existing 1-second status polling to try again.
    assert "data.ok !== true" in block
    assert block.count(
        "releaseTidalInfinitePlayRefillKey(refillKey);"
    ) == 2

    retry_start = UI_SOURCE.index(
        "function releaseTidalInfinitePlayRefillKey(refillKey) {"
    )
    retry_end = UI_SOURCE.index(
        "function normalizeTidalInfinitePlayMode(mode) {",
        retry_start,
    )
    retry_block = UI_SOURCE[retry_start:retry_end]

    assert 'tidalInfinitePlayLastRefillKey = "";' in retry_block

    # Point 7 must not invent a new retry timer or alter the 60s threshold.
    assert "tidalInfinitePlayRetryAfter" not in UI_SOURCE
    assert "Date.now() + 10000" not in UI_SOURCE


def test_backend_has_single_shared_generation_lock_for_http_and_eos():
    backend_source = (
        ROOT / "src" / "main_headless.py"
    ).read_text(encoding="utf-8")

    assert "_INFINITE_PLAY_GENERATION_LOCK = threading.Lock()" in backend_source
    assert "with _INFINITE_PLAY_GENERATION_LOCK:" in backend_source
    assert (
        "result = _coordinated_infinite_play_refill("
        in backend_source
    )
    assert (
        "_coordinated_infinite_play_refill(\n"
        "            limit=10,\n"
        "            autoplay=True,"
        in backend_source
    )
