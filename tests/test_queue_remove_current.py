import unittest
from pathlib import Path

import src.main_headless as backend


REPO_ROOT = Path(__file__).resolve().parents[1]


class QueueRemoveCurrentTests(unittest.TestCase):
    def setUp(self):
        self.play_queue = list(backend.PLAY_QUEUE)
        self.original_queue = list(backend.ORIGINAL_QUEUE)
        self.queue_index = backend.QUEUE_INDEX

    def tearDown(self):
        with backend._QUEUE_LOCK:
            backend.PLAY_QUEUE[:] = self.play_queue
            backend.ORIGINAL_QUEUE[:] = self.original_queue
            backend.QUEUE_INDEX = self.queue_index

    def test_remove_current_item_reports_stop_required_and_preserves_remaining_queue(self):
        with backend._QUEUE_LOCK:
            backend.PLAY_QUEUE[:] = [
                "tidal:track:1",
                "local:track:2",
                "radio:station:test",
            ]
            backend.ORIGINAL_QUEUE[:] = list(backend.PLAY_QUEUE)
            backend.QUEUE_INDEX = 1

            removed_current = backend._queue_remove_active_index_locked(1)

        self.assertTrue(removed_current)
        self.assertEqual(
            backend.PLAY_QUEUE,
            ["tidal:track:1", "radio:station:test"],
        )
        self.assertEqual(
            backend.ORIGINAL_QUEUE,
            ["tidal:track:1", "radio:station:test"],
        )
        self.assertEqual(backend.QUEUE_INDEX, 1)

    def test_remove_non_current_item_does_not_request_playback_stop(self):
        with backend._QUEUE_LOCK:
            backend.PLAY_QUEUE[:] = [
                "tidal:track:1",
                "local:track:2",
                "tidal:track:3",
            ]
            backend.ORIGINAL_QUEUE[:] = list(backend.PLAY_QUEUE)
            backend.QUEUE_INDEX = 2

            removed_current = backend._queue_remove_active_index_locked(0)

        self.assertFalse(removed_current)
        self.assertEqual(
            backend.PLAY_QUEUE,
            ["local:track:2", "tidal:track:3"],
        )
        self.assertEqual(backend.QUEUE_INDEX, 1)

    def test_http_remove_route_stops_only_when_current_item_was_removed(self):
        source = (
            REPO_ROOT / "src" / "main_headless.py"
        ).read_text(encoding="utf-8")

        start = source.index(
            '# -- Queue: remove track at index'
        )
        end = source.index(
            '# -- Queue: clear upcoming',
            start,
        )
        route = source[start:end]

        self.assertIn(
            'removed_current = _queue_remove_active_index_locked(idx)',
            route,
        )
        self.assertIn(
            '_finalize_end_of_queue_playback("Current queue item removed")',
            route,
        )
        self.assertIn(
            '"stopped": removed_current',
            route,
        )

        ui_source = (
            REPO_ROOT / "src" / "ui_web" / "ui.js"
        ).read_text(encoding="utf-8")
        remove_start = ui_source.index(
            'removeBtn.onclick = function(e)'
        )
        remove_end = ui_source.index(
            'row.appendChild(art)',
            remove_start,
        )
        remove_handler = ui_source[remove_start:remove_end]

        self.assertIn(
            'if (data && data.stopped === true)',
            remove_handler,
        )
        self.assertIn(
            'applyStandbyPlayerBar();',
            remove_handler,
        )
        self.assertIn(
            'pollStatus();',
            remove_handler,
        )

        html = (
            REPO_ROOT / "src" / "ui_web" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            html,
            r'<script[^>]+src="/ui_web/ui\.js\?v=[^"]+"',
        )

    def test_radio_queue_wording_is_consistent(self):
        backend_source = (
            REPO_ROOT / "src" / "main_headless.py"
        ).read_text(encoding="utf-8")
        ui_source = (
            REPO_ROOT / "src" / "ui_web" / "ui.js"
        ).read_text(encoding="utf-8")

        expected = (
            "Clear the Radio station from the Play Queue before adding to it."
        )
        old = "Stop Radio before adding"

        self.assertIn(expected, backend_source)
        self.assertIn(expected, ui_source)
        self.assertNotIn(old, backend_source)
        self.assertNotIn(old, ui_source)


if __name__ == "__main__":
    unittest.main()
