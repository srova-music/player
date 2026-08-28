from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DISPLAY = (
    ROOT /
    "src" /
    "ui_web" /
    "srovacast" /
    "display.html"
).read_text()


class SrovaCastPresentationAuthorityBridgeTest(unittest.TestCase):
    def test_versioned_presentation_authority_contract(self):
        self.assertIn(
            "SROVACAST_PRESENTATION_AUTHORITY_V1",
            DISPLAY,
        )
        self.assertIn(
            "PRESENTATION_AUTHORITY_MESSAGE_VERSION = 1",
            DISPLAY,
        )

    def test_embedded_display_defaults_deauthorized(self):
        self.assertIn(
            "let presentationAuthorized =\n"
            "    window.parent === window;",
            DISPLAY,
        )

    def test_only_parent_window_can_change_authority(self):
        self.assertIn(
            "event.source !== window.parent",
            DISPLAY,
        )
        self.assertIn(
            'typeof event.data.authorized !== "boolean"',
            DISPLAY,
        )

    def test_deauthorized_presentation_forces_existing_inactive_path(self):
        refresh = DISPLAY.split(
            "async function refresh()",
            1,
        )[1].split(
            "initialiseFooter();",
            1,
        )[0]
        self.assertIn(
            "if (!presentationAuthorized) {",
            refresh,
        )
        self.assertIn(
            '"inactive"',
            refresh,
        )
        self.assertIn(
            "playing: false",
            DISPLAY,
        )

    def test_deauthorization_forces_ready_without_waiting_for_fetch(self):
        handler = DISPLAY.split(
            "function handlePresentationAuthorityMessage(",
            1,
        )[1].split(
            "window.addEventListener(",
            1,
        )[0]

        self.assertIn(
            "if (!presentationAuthorized) {",
            handler,
        )
        self.assertIn(
            'presentationStatusFromStatus({})',
            handler,
        )
        self.assertIn(
            '"inactive"',
            handler,
        )
        self.assertIn(
            "retainedNowPlayingState = null;",
            handler,
        )
        self.assertIn(
            "return;",
            handler,
        )

    def test_authority_change_reuses_refresh_not_new_status_loop(self):
        self.assertIn(
            'lastPlaybackState = "unknown";',
            DISPLAY,
        )
        self.assertIn(
            "void refresh();",
            DISPLAY,
        )
        self.assertEqual(
            DISPLAY.count(
                "`/status?_=${Date.now()}`"
            ),
            1,
        )

    def test_playback_truth_is_still_posted_before_presentation_gate(self):
        post = DISPLAY.index(
            "postPlaybackState(\n"
            "        nextPlaybackState"
        )
        gated = DISPLAY.index(
            "if (!presentationAuthorized) {",
            post,
        )
        self.assertLess(post, gated)


if __name__ == "__main__":
    unittest.main()
