from __future__ import annotations

import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from wyy_assist.automation import _run_live_attempt, run_live
from wyy_assist.adb import AdbError
from wyy_assist.executor import ActionExecutor
from wyy_assist.model import Match, Settings
from wyy_assist.recovery import RecoveryFailed, recover_page


def found(state: str) -> Match:
    return Match(state, 0.99, (90, 40), Path(state + ".png"))


class Clock:
    now = 0.0

    def sleep(self, seconds):
        self.now += seconds


class Device:
    def __init__(self, clock):
        self.clock = clock
        self.actions = []

    def command_deadline(self, deadline):
        self.deadline = deadline
        return nullcontext()

    def screenshot(self):
        return np.zeros((200, 100, 3), dtype=np.uint8)

    def foreground_window(self):
        return "com.example.school.mockads/.Main"

    def tap(self, *point):
        self.actions.append(("tap", self.clock.now, point))

    def back(self):
        self.actions.append(("back", self.clock.now))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.settings = Settings(package="com.example.school.mockads", execution_enabled=True,
                                 poll_interval_seconds=1, consecutive_hits=2)
        self.device = Device(self.clock)
        self.executor = ActionExecutor(self.settings, self.device, execute_requested=True)
        self.enterContext(patch("time.monotonic", side_effect=lambda: self.clock.now))
        self.enterContext(patch("time.sleep", side_effect=self.clock.sleep))

    def test_exit_overlay_wins_over_background_and_requires_stable_normal_page(self):
        exit_recognizer = Mock()
        exit_recognizer.best_match.side_effect = [found("ad_close"), None, None]
        recognizer = Mock()
        recognizer.best_match.return_value = found("ready")
        with patch("wyy_assist.recovery.recovery_recognizer", return_value=exit_recognizer):
            result = recover_page(self.settings, self.device, recognizer, self.executor, cause="unknown")
        self.assertEqual(result.state, "ready")
        self.assertEqual(self.device.actions, [("tap", 0.0, (90, 40))])
        self.assertEqual(self.clock.now, 2.0)

    def test_unknown_uses_back_and_fails_at_30_seconds_even_when_exits_are_found(self):
        for target in (None, found("ad_close")):
            with self.subTest(target=target):
                self.clock.now = 0
                self.device.actions.clear()
                recognizer = Mock()
                recognizer.best_match.return_value = None
                exits = Mock()
                exits.best_match.return_value = target
                with patch("wyy_assist.recovery.recovery_recognizer", return_value=exits):
                    with self.assertRaisesRegex(RecoveryFailed, "30 秒"):
                        recover_page(self.settings, self.device, recognizer, self.executor, cause="unknown")
                self.assertEqual(self.clock.now, 30.0)
                self.assertEqual(self.device.actions[0][0], "back" if target is None else "tap")
                self.assertEqual(len(self.device.actions), 10)

    def test_stalled_page_alone_cannot_confirm_recovery(self):
        recognizer = Mock()
        recognizer.best_match.side_effect = lambda screen, allowed_states: found("ready") if "ready" in allowed_states else None
        exits = Mock()
        exits.best_match.return_value = None
        with patch("wyy_assist.recovery.recovery_recognizer", return_value=exits):
            with self.assertRaises(RecoveryFailed):
                recover_page(self.settings, self.device, recognizer, self.executor,
                             cause="stalled-ready", blocked_state="ready")
        self.assertTrue(self.device.actions)

    def test_foreign_page_only_uses_back_not_template_taps(self):
        self.device.foreground_window = lambda: "com.android.browser/.Page"
        recognizer = Mock()
        exits = Mock()
        exits.best_match.return_value = found("ad_close")
        with patch("wyy_assist.recovery.recovery_recognizer", return_value=exits):
            with self.assertRaises(RecoveryFailed):
                recover_page(self.settings, self.device, recognizer, self.executor, cause="foreign")
        exits.best_match.assert_not_called()
        self.assertTrue(all(action[0] == "back" for action in self.device.actions))

    def test_waits_finish_before_missing_exit_enters_recovery(self):
        def observe(screen, allowed_states=None):
            return found("ad_interaction")
        recognizer = Mock()
        recognizer.best_match.side_effect = observe
        with patch("wyy_assist.automation.StateRecognizer", return_value=recognizer):
            result = _run_live_attempt(self.settings, self.device, execute_requested=True)
        self.assertEqual(result.reason, "ad-exit-not-found")
        self.assertEqual(self.clock.now, 25.0)
        self.assertEqual(self.device.actions, [("tap", 15.0, (50, 100))])

    def test_single_limit_frame_cannot_stop_or_click(self):
        recognizer = Mock()
        recognizer.best_match.side_effect = [found("limit"), None]
        with patch("wyy_assist.automation.StateRecognizer", return_value=recognizer):
            result = _run_live_attempt(self.settings, self.device, execute_requested=True)
        self.assertNotEqual(result.reason, "limit")
        self.assertFalse(self.device.actions)

    def test_confirmed_limit_stops_without_clicking(self):
        recognizer = Mock()
        recognizer.best_match.return_value = found("limit")
        with patch("wyy_assist.automation.StateRecognizer", return_value=recognizer):
            result = _run_live_attempt(self.settings, self.device, execute_requested=True)
        self.assertEqual(result.reason, "limit")
        self.assertFalse(self.device.actions)

    def test_recovery_limit_is_propagated_as_completion(self):
        from wyy_assist.automation import AutomationResult
        with patch("wyy_assist.automation._run_live_attempt", return_value=AutomationResult("stalled-ready", 3)), \
             patch("wyy_assist.automation.recover_page", return_value=found("limit")):
            result = run_live(self.settings, self.device, execute_requested=True)
        self.assertEqual(result.reason, "limit")

    def test_ad_screenshot_interruption_preserves_pending_wait(self):
        def fail(settings, adb, *, ad_cycle, **kwargs):
            ad_cycle.arm(0)
            ad_cycle.observe_screen("ad_interaction", 0)
            self.clock.now = 3
            raise AdbError("screenshot interrupted")
        recovered_at = []
        def recover(*args, **kwargs):
            recovered_at.append(self.clock.now)
            return found("limit")
        with patch("wyy_assist.automation._run_live_attempt", side_effect=fail), \
             patch("wyy_assist.automation.recover_page", side_effect=recover):
            run_live(self.settings, self.device, execute_requested=True)
        self.assertEqual(recovered_at, [15])
