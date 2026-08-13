from pathlib import Path

import pytest

import src.main_headless as backend


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def restore_queue_state():
    original_play = list(backend.PLAY_QUEUE)
    original_canonical = list(backend.ORIGINAL_QUEUE)
    original_index = backend.QUEUE_INDEX
    yield
    with backend._QUEUE_LOCK:
        backend.PLAY_QUEUE[:] = original_play
        backend.ORIGINAL_QUEUE[:] = original_canonical
        backend.QUEUE_INDEX = original_index


def test_reorder_moves_only_upcoming_and_preserves_current_track():
    with backend._QUEUE_LOCK:
        backend.PLAY_QUEUE[:] = ["played", "current", "local:a", "tidal:b", "local:c"]
        backend.ORIGINAL_QUEUE[:] = list(backend.PLAY_QUEUE)
        backend.QUEUE_INDEX = 1

        backend._queue_move_upcoming_index_locked(4, 2)

    assert backend.PLAY_QUEUE == ["played", "current", "local:c", "local:a", "tidal:b"]
    assert backend.ORIGINAL_QUEUE == backend.PLAY_QUEUE
    assert backend.QUEUE_INDEX == 1
    assert backend.PLAY_QUEUE[backend.QUEUE_INDEX] == "current"


@pytest.mark.parametrize("from_index,to_index", [(1, 2), (2, 1), (0, 3)])
def test_reorder_rejects_current_or_played_indexes(from_index, to_index):
    with backend._QUEUE_LOCK:
        backend.PLAY_QUEUE[:] = ["played", "current", "next-a", "next-b"]
        backend.ORIGINAL_QUEUE[:] = list(backend.PLAY_QUEUE)
        backend.QUEUE_INDEX = 1

        with pytest.raises(ValueError, match="only upcoming"):
            backend._queue_move_upcoming_index_locked(from_index, to_index)


def test_reorder_makes_visible_order_canonical_when_shuffle_diverged():
    with backend._QUEUE_LOCK:
        backend.PLAY_QUEUE[:] = ["current", "c", "a", "b"]
        backend.ORIGINAL_QUEUE[:] = ["current", "a", "b", "c"]
        backend.QUEUE_INDEX = 0

        backend._queue_move_upcoming_index_locked(3, 1)

    assert backend.PLAY_QUEUE == ["current", "b", "c", "a"]
    assert backend.ORIGINAL_QUEUE == backend.PLAY_QUEUE
    assert backend.QUEUE_INDEX == 0


def test_web_queue_uses_direct_handles_and_delete_confirmation():
    ui_source = (REPO_ROOT / "src" / "ui_web" / "ui.js").read_text(encoding="utf-8")

    assert 'className = "queueDragHandle"' in ui_source
    assert 'enableUpcomingQueueDrag(row, dragHandle, absIdx)' in ui_source
    assert 'fetch("/tidal/queue/reorder"' in ui_source
    assert 'className = "localLibraryCleanupModal queueRemoveConfirmModal"' in ui_source
    assert "openQueueRemoveConfirm(track, removeTrack)" in ui_source
    assert "if (isPlayed)" in ui_source
    assert "window.confirm" not in ui_source[ui_source.index("function buildQueueRow"):]
    assert 'buildQueueRow(upcoming[i], queueIndex + 1 + i, false, false, true)' in ui_source
    assert "Reorder / Done" not in ui_source


def test_reorder_route_persists_after_backend_validation():
    source = (REPO_ROOT / "src" / "main_headless.py").read_text(encoding="utf-8")
    get_start = source.index("    def do_GET(self):")
    post_start = source.index("    def do_POST(self):", get_start)
    start = source.index('if self.path == "/tidal/queue/reorder":')
    end = source.index('# -- Network / Remote Access', start)
    route = source[start:end]

    assert post_start < start
    assert '/tidal/queue/reorder' not in source[get_start:post_start]
    assert "payload = json.loads(body)" in source[post_start:start]
    assert "_queue_move_upcoming_index_locked(from_index, to_index)" in route
    assert route.index("_queue_move_upcoming_index_locked") < route.index("save_queue()")
    assert '"queue_index": QUEUE_INDEX' in route
