from pathlib import Path


BACKEND_SOURCE = (
    Path(__file__).resolve().parents[1] / "src" / "main_headless.py"
).read_text(encoding="utf-8")


def _route_block(path, next_path):
    start_marker = f'if self.path == "{path}":'
    end_marker = f'if self.path == "{next_path}":'
    start = BACKEND_SOURCE.index(start_marker)

    try:
        end = BACKEND_SOURCE.index(end_marker, start)
    except ValueError:
        # Some routes intentionally expose compatibility aliases through
        # an ``if self.path in (...)`` block. Locate next_path inside that
        # tuple and use the tuple statement itself as the route boundary.
        tuple_member = f'"{next_path}",'
        member = BACKEND_SOURCE.index(tuple_member, start)
        end = BACKEND_SOURCE.rfind(
            "if self.path in (",
            start,
            member,
        )
        if end < start:
            raise

    return BACKEND_SOURCE[start:end]


def test_add_to_queue_appends_without_trimming_active_local_album():
    append_block = _route_block(
        "/tidal/queue/append",
        "/tidal/queue/insert_next",
    )

    assert "_queue_ensure_canonical_locked()" in append_block
    assert "_trim_future_local_cue_album_queue_locked" not in append_block
    assert "PLAY_QUEUE.append(tid)" in append_block
    assert "ORIGINAL_QUEUE.append(tid)" in append_block
    assert append_block.index("PLAY_QUEUE.append(tid)") < append_block.index(
        'save_queue()'
    )


def test_play_next_retains_intentional_local_cue_trim():
    insert_next_block = _route_block(
        "/tidal/queue/insert_next",
        "/api/tidal/infinite-play/refill",
    )

    assert (
        '_trim_future_local_cue_album_queue_locked("insert_next")'
        in insert_next_block
    )
    assert "PLAY_QUEUE.insert(insert_at + i, tid)" in insert_next_block
