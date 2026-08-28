import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPLAY = (ROOT / "src" / "ui_web" / "srovacast" / "display.html").read_text()

class SrovaCastPhysicalFadeTuningTest(unittest.TestCase):
    def test_fast_player_fade_contract(self):
        self.assertIn("transition: opacity 60ms ease;", DISPLAY)
        self.assertIn("const PRESENTATION_FADE_MS = 120;", DISPLAY)
        self.assertNotIn("transition: opacity 140ms ease;", DISPLAY)
        self.assertNotIn("const PRESENTATION_FADE_MS = 280;", DISPLAY)

if __name__ == "__main__":
    unittest.main()
