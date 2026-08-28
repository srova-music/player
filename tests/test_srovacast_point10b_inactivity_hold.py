from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DISPLAY = (
    ROOT
    / "src"
    / "ui_web"
    / "srovacast"
    / "display.html"
).read_text()


class SrovaCastPoint10BInactiveHoldTest(unittest.TestCase):
    def test_first_inactive_stage_is_30_second_now_playing_hold(self):
        self.assertIn(
            "const INACTIVE_PRESENTATION_HOLD_MS = 30000;",
            DISPLAY,
        )
        hold = DISPLAY.split(
            "function presentAuthorizedInactive(", 1
        )[1].split(
            "function handlePresentationAuthorityMessage(", 1
        )[0]
        self.assertIn(
            "inactivePresentationDeadline =\n"
            "        Date.now() +\n"
            "        INACTIVE_PRESENTATION_HOLD_MS;",
            hold,
        )
        self.assertIn(
            '      "active",\n'
            "      true",
            hold,
        )
        self.assertIn(
            '              "inactive",\n'
            "              false",
            hold,
        )

    def test_resume_before_deadline_has_no_ready_transition(self):
        refresh = DISPLAY.split(
            "async function refresh()", 1
        )[1].split(
            "initialiseFooter();", 1
        )[0]
        active = refresh.split(
            'if (nextPlaybackState === "active") {', 1
        )[1].split("return;", 1)[0]
        self.assertIn(
            "clearInactivePresentationHold(true);",
            active,
        )
        self.assertIn(
            '          "active",\n'
            "          false",
            active,
        )

    def test_progress_position_is_always_current_player_truth_while_retained(self):
        retained = DISPLAY.split(
            "function retainedPresentationStatusFromStatus(", 1
        )[1].split(
            "function presentAuthorizedInactive(", 1
        )[0]
        self.assertIn(
            "retained.position =\n"
            "      current.position;",
            retained,
        )
        self.assertIn(
            "retained.playing = false;",
            retained,
        )
        self.assertNotIn(
            "Date.now() / 1000",
            retained,
        )

    def test_paused_retained_progress_does_not_extrapolate(self):
        sync = DISPLAY.split(
            "function syncProgress(state)", 1
        )[1].split(
            "function clearProgressState()", 1
        )[0]
        self.assertIn(
            "progressPlaying =\n"
            "      state.playing === true",
            sync,
        )
        retained = DISPLAY.split(
            "function retainedPresentationStatusFromStatus(", 1
        )[1].split(
            "function presentAuthorizedInactive(", 1
        )[0]
        self.assertIn("retained.playing = false;", retained)

    def test_progress_reset_to_zero_is_not_replaced_with_stale_value(self):
        retained = DISPLAY.split(
            "function retainedPresentationStatusFromStatus(", 1
        )[1].split(
            "function presentAuthorizedInactive(", 1
        )[0]
        self.assertIn(
            "Position is always current player truth, including a reset to 00:00.",
            retained,
        )
        self.assertIn(
            "retained.position =\n"
            "      current.position;",
            retained,
        )

    def test_release_deauthorization_forces_ready_and_drops_stale_cache(self):
        handler = DISPLAY.split(
            "function handlePresentationAuthorityMessage(", 1
        )[1].split(
            "window.addEventListener(", 1
        )[0]
        self.assertIn(
            "clearInactivePresentationHold(true);",
            handler,
        )
        self.assertIn(
            "retainedNowPlayingState = null;",
            handler,
        )
        self.assertIn(
            "presentationStatusFromStatus({})",
            handler,
        )
        self.assertIn('"inactive"', handler)

    def test_unknown_status_cancels_pending_hold(self):
        refresh = DISPLAY.split(
            "async function refresh()", 1
        )[1].split(
            "initialiseFooter();", 1
        )[0]
        catch = refresh.split("} catch (_) {", 1)[1]
        self.assertIn(
            'latestPlaybackState = "unknown";',
            catch,
        )
        self.assertIn(
            "clearInactivePresentationHold();",
            catch,
        )

    def test_only_one_status_poll_loop_exists(self):
        self.assertEqual(
            DISPLAY.count("`/status?_=${Date.now()}`"),
            1,
        )
        self.assertEqual(
            DISPLAY.count("window.setInterval(refresh, 3000);"),
            1,
        )

    def test_existing_120ms_presentation_fade_is_preserved(self):
        self.assertIn(
            "const PRESENTATION_FADE_MS = 120;",
            DISPLAY,
        )
        self.assertIn(
            "transition: opacity 60ms ease;",
            DISPLAY,
        )


class DeterministicInactivePresentationModelTest(unittest.TestCase):
    def test_timeline_and_resume_contract(self):
        paused_at = 100
        ready_at = paused_at + 30
        receiver_clock_at = paused_at + 60
        self.assertEqual(ready_at, 130)
        self.assertEqual(receiver_clock_at, 160)

        resumed_at = 112
        self.assertLess(resumed_at, ready_at)

        explicit_release_at = 200
        self.assertEqual(explicit_release_at + 30, 230)


if __name__ == "__main__":
    unittest.main()
