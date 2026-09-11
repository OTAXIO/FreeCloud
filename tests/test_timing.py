from __future__ import annotations

import unittest
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from wyy_assist.actions import ActionKind, ActionPlanner
from wyy_assist.adb import AdbError
from wyy_assist.automation import AdCycleTimer, _run_live_attempt, run_live
from wyy_assist.model import Match, Settings
from wyy_assist.timing import jitter_wait_seconds


class WaitJitterTests(unittest.TestCase):
    def test_all_tenths_in_one_second_range_and_decimal_base(self):
        for base in (15.0, 10.0, 15.4):
            with self.subTest(base=base), patch(
                "wyy_assist.timing.random.randint", side_effect=range(-10, 11)
            ):
                waits = [jitter_wait_seconds(base) for _ in range(21)]
                self.assertEqual(waits, [round(base + offset / 10, 1) for offset in range(-10, 11)])
                self.assertTrue(all(value == round(value, 1) for value in waits))

    def test_short_wait_never_negative_and_zero_stays_disabled(self):
        with patch("wyy_assist.timing.random.randint", return_value=-10):
            self.assertEqual(jitter_wait_seconds(0.3), 0.0)
        with patch("wyy_assist.timing.random.randint") as draw:
            self.assertEqual(jitter_wait_seconds(0.0), 0.0)
            draw.assert_not_called()

    def test_cycle_samples_once_per_entry_and_never_accumulates_offsets(self):
        timer = AdCycleTimer(15.0, 10.0)
        with patch("wyy_assist.timing.random.randint", side_effect=[-7, 8, 10, -10]) as draw:
            timer.arm(100.0)
            draw.assert_not_called()
            self.assertIsNone(timer.observe_screen("ready", 101.0))
            timer.observe_screen("ad_interaction", 102.0)
            self.assertEqual((timer.pre_click_wait_seconds, timer.post_click_wait_seconds), (14.3, 10.8))
            for state in (None, "landing", "download_prompt", "ad_close"):
                self.assertIsNone(timer.observe_screen(state, 103.0))
            self.assertEqual(draw.call_count, 2)
            first_end = 102.0 + 14.3
            self.assertFalse(timer.interaction_due(first_end - 0.1))
            self.assertTrue(timer.interaction_due(first_end))
            timer.mark_interaction(first_end)
            second_end = first_end + 10.8
            self.assertFalse(timer.advance_post_click(second_end - 0.1))
            self.assertTrue(timer.advance_post_click(second_end))
            self.assertEqual(draw.call_count, 2)
            timer.reset()
            timer.arm(200.0)
            timer.observe_screen(None, 201.0)
            self.assertEqual((timer.pre_click_wait_seconds, timer.post_click_wait_seconds), (16.0, 9.0))
            self.assertEqual((timer.pre_click_seconds, timer.post_click_seconds), (15.0, 10.0))
            self.assertEqual(draw.call_count, 4)

    def test_preview_plan_uses_same_jitter_without_changing_settings(self):
        settings = Settings()
        before = settings.to_dict()
        with patch("wyy_assist.timing.random.randint", side_effect=[-7, 8]):
            actions = ActionPlanner(settings).plan(
                Match("ad_interaction", 1.0, (50, 100), Path("ad.png")), (100, 200)
            )
        self.assertEqual([(a.kind, a.seconds) for a in actions],
                         [(ActionKind.WAIT, 14.3), (ActionKind.TAP, 0.0), (ActionKind.WAIT, 10.8)])
        self.assertEqual(settings.to_dict(), before)

    def test_main_loop_waits_for_sampled_durations_and_logs_tenths(self):
        now = [0.0]
        taps = []
        def sleep(seconds):
            now[0] = round(now[0] + seconds, 10)
        settings = Settings(package="com.example.test", execution_enabled=True,
                            poll_interval_seconds=0.1, consecutive_hits=1)
        adb = Mock()
        adb.foreground_window.return_value = settings.package + "/.Main"
        adb.screenshot.return_value = np.zeros((200, 100, 3), dtype=np.uint8)
        adb.tap.side_effect = lambda *point: taps.append((now[0], point))
        recognizer = Mock()
        recognizer.best_match.return_value = Match("ad_interaction", 1.0, (50, 100), Path("ad.png"))
        output = StringIO()
        with patch("wyy_assist.timing.random.randint", side_effect=[-7, 8]) as draw, \
             patch("wyy_assist.automation.time.monotonic", side_effect=lambda: now[0]), \
             patch("wyy_assist.automation.time.sleep", side_effect=sleep), \
             patch("wyy_assist.automation.StateRecognizer", return_value=recognizer), redirect_stdout(output):
            result = _run_live_attempt(settings, adb, execute_requested=True)
        self.assertEqual(result.reason, "ad-exit-not-found")
        self.assertEqual(taps, [(14.3, (50, 100))])
        self.assertEqual(now[0], 25.1)
        self.assertEqual(draw.call_count, 2)
        self.assertIn("14.3 秒", output.getvalue())
        self.assertIn("10.8 秒", output.getvalue())

    def test_recovery_respects_sampled_deadline_before_and_after_click(self):
        for after_click, expected in ((False, 14.3), (True, 25.1)):
            with self.subTest(after_click=after_click):
                now = [0.0]
                recovered_at = []
                def fail(settings, adb, *, ad_cycle, **kwargs):
                    ad_cycle.observe_screen("ad_interaction", 0.0)
                    if after_click:
                        ad_cycle.mark_interaction(14.3)
                        now[0] = 16.0
                    else:
                        now[0] = 3.0
                    raise AdbError("screenshot interrupted")
                def sleep(seconds):
                    now[0] += seconds
                def recover(*args, **kwargs):
                    recovered_at.append(now[0])
                    return Match("limit", 1.0, (50, 100), Path("limit.png"))
                with patch("wyy_assist.timing.random.randint", side_effect=[-7, 8]) as draw, \
                     patch("wyy_assist.automation.time.monotonic", side_effect=lambda: now[0]), \
                     patch("wyy_assist.automation.time.sleep", side_effect=sleep), \
                     patch("wyy_assist.automation._run_live_attempt", side_effect=fail), \
                     patch("wyy_assist.automation.recover_page", side_effect=recover):
                    result = run_live(Settings(), Mock(), execute_requested=True)
                self.assertEqual(result.reason, "limit")
                self.assertAlmostEqual(recovered_at[0], expected)
                self.assertEqual(draw.call_count, 2)
