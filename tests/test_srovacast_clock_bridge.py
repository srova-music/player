from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DISPLAY = ROOT / "src" / "ui_web" / "srovacast" / "display.html"


class SrovaCastClockBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DISPLAY.read_text()

    def test_versioned_minimal_message_contract(self):
        self.assertIn('"SROVACAST_PLAYBACK_STATE_V1"', self.text)
        self.assertIn("const PLAYBACK_MESSAGE_VERSION = 1;", self.text)
        self.assertIn('["active", "inactive", "unknown"]', self.text)
        block = re.search(
            r"function postPlaybackState\(state\).*?^  \}",
            self.text,
            flags=re.S | re.M,
        )
        self.assertIsNotNone(block)
        message = block.group(0).lower()
        for forbidden in ("token", "generation", "credential", "password"):
            self.assertNotIn(forbidden, message)

    def test_reuses_existing_status_poll(self):
        self.assertEqual(self.text.count("`/status?_=${Date.now()}`"), 1)
        self.assertEqual(self.text.count("window.setInterval(refresh, 3000)"), 1)

    def test_success_maps_playing_boolean(self):
        self.assertIn("status.playing === true", self.text)
        self.assertIn('? "active"\n      : "inactive";', self.text)

    def test_failure_reports_unknown(self):
        self.assertIn('postPlaybackState("unknown");', self.text)

    def test_ready_message_is_not_overloaded(self):
        self.assertIn('"SROVACAST_DISPLAY_READY_V1"', self.text)
        self.assertIn("SROVACAST_PLAYBACK_STATE_V1", self.text)

    def test_soft_transition_is_centralized(self):
        self.assertIn("const PRESENTATION_FADE_MS = 120;", self.text)
        self.assertIn("PRESENTATION_FADE_MS / 2", self.text)
        self.assertIn("transition: opacity 60ms ease;", self.text)

    def test_confirmed_inactive_retains_then_uses_existing_standby(self):
        self.assertIn(
            "const INACTIVE_PRESENTATION_HOLD_MS = 30000;",
            self.text,
        )
        self.assertIn(
            "function presentAuthorizedInactive(",
            self.text,
        )
        self.assertIn('heading.textContent = "READY";', self.text)
        self.assertIn('artist.textContent = "Waiting for playback";', self.text)
        self.assertNotIn('state.playing ? "NOW PLAYING" : "PAUSED"', self.text)


if __name__ == "__main__":
    unittest.main()
