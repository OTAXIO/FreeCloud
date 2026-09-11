from __future__ import annotations

import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from wyy_assist.automation import runtime_recognition_states
from wyy_assist.startup import run_startup_navigation as start_app
from wyy_assist.navigation import LOGIC_2_STATES


def run_startup_navigation(*args, **kwargs):
    return start_app(*args, **kwargs, navigation_states=LOGIC_2_STATES)
from wyy_assist.model import Match, Settings, TemplateSpec
from wyy_assist.adb import AdbError
from wyy_assist.recovery import RecoveryFailed


class StartupAdb:
    def __init__(self, foreground: str = "com.android.launcher") -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.foreground = foreground
        self.restart_app = Mock()

    def command_deadline(self, deadline):
        return nullcontext()

    def screenshot(self) -> np.ndarray:
        return np.zeros((1920, 1080, 3), dtype=np.uint8)

    def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", x, y))

    def foreground_window(self) -> str:
        return self.foreground


def match(state: str, center: tuple[int, int]) -> Match:
    return Match(state, 1.0, center, Path(f"{state}.png"))


class StartupNavigationTests(unittest.TestCase):
    def stalled_start(self, *, restart_effect=None, execute_requested=True):
        settings = Settings(package="com.example.test", execution_enabled=True,
                            consecutive_hits=1, poll_interval_seconds=1,
                            startup_navigation_timeout_seconds=30)
        adb = StartupAdb()
        adb.restart_app.side_effect = restart_effect
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
        def observe(screen, allowed_states):
            if "launcher_icon" in allowed_states:
                return match("launcher_icon", (120, 420))
            if adb.foreground == "com.example.test/.Main" and "home" in allowed_states:
                return match("home", (540, 120))
            return None
        with patch("wyy_assist.startup.StateRecognizer") as recognizer, \
             patch("wyy_assist.startup.time.monotonic", side_effect=lambda: now[0]), \
             patch("wyy_assist.startup.time.sleep", side_effect=sleep), \
             patch("wyy_assist.automation.recover_page") as recover:
            recognizer.return_value.best_match.side_effect = observe
            if restart_effect == "success":
                adb.restart_app.side_effect = lambda package: setattr(adb, "foreground", package + "/.Main")
            try:
                return run_startup_navigation(settings, adb, execute_requested=execute_requested), adb
            finally:
                recover.assert_not_called()
                if execute_requested:
                    adb.restart_app.assert_called_once_with(settings.package)
                    self.assertEqual(adb.calls, [("tap", 120, 420)])
                else:
                    adb.restart_app.assert_not_called()
                    self.assertEqual(adb.calls, [])

    def test_unresponsive_icon_restarts_once_then_resumes(self):
        result, _ = self.stalled_start(restart_effect="success")
        self.assertEqual(result.reason, "startup-home")

    def test_second_unresponsive_launch_aborts_without_page_recovery(self):
        with self.assertRaisesRegex(RecoveryFailed, "重启后再次失败"):
            self.stalled_start()

    def test_restart_command_failure_aborts_without_another_attempt(self):
        with self.assertRaisesRegex(RecoveryFailed, "重启后再次失败"):
            self.stalled_start(restart_effect=AdbError("launch failed"))

    def test_preview_cannot_restart_or_click(self):
        from wyy_assist.executor import ExecutionBlocked
        with self.assertRaises(ExecutionBlocked):
            self.stalled_start(execute_requested=False)

    def test_startup_limit_is_checked_before_home_actions(self):
        settings = Settings(package="com.example.test", execution_enabled=True, consecutive_hits=2)
        adb = StartupAdb("mCurrentFocus=com.example.test/.Main")
        with patch("wyy_assist.startup.StateRecognizer") as recognizer, \
             patch("wyy_assist.startup.time.sleep"):
            recognizer.return_value.best_match.return_value = match("limit", (500, 1700))
            result = run_startup_navigation(settings, adb, execute_requested=True)
        self.assertEqual(result.reason, "startup-limit")
        self.assertEqual(adb.calls, [])
        self.assertEqual(recognizer.return_value.best_match.call_count, 2)

    def test_main_state_machine_excludes_launcher_and_splash_states(self) -> None:
        settings = Settings(
            templates={
                "launcher_icon": [TemplateSpec("launcher.png")],
                "splash_skip": [TemplateSpec("skip.png")],
                "home": [TemplateSpec("home.png")],
                "ready": [TemplateSpec("ready.png")],
            }
        )
        self.assertEqual(runtime_recognition_states(settings), {"ready"})

    @patch("wyy_assist.startup.time.sleep", return_value=None)
    @patch("wyy_assist.startup.StateRecognizer")
    def test_clicks_launcher_then_skip_and_hands_off_to_original_state_machine(
        self,
        recognizer_type: Mock,
        _sleep: Mock,
    ) -> None:
        recognizer_type.return_value.best_match.side_effect = [
            None,
            match("launcher_icon", (120, 420)),
            None,
            match("splash_skip", (1018, 80)),
            match("home", (540, 120)),
        ]
        settings = Settings(
            package="com.example.school.mockads",
            execution_enabled=True,
            consecutive_hits=1,
            startup_navigation_timeout_seconds=10.0,
            templates={"ready": [TemplateSpec("ready.png")]},
        )
        adb = StartupAdb()

        result = run_startup_navigation(settings, adb, execute_requested=True)

        self.assertEqual(result.reason, "startup-home")
        self.assertEqual(
            adb.calls,
            [("tap", 120, 420), ("tap", 1018, 80)],
        )
        allowed = [call.kwargs["allowed_states"] for call in recognizer_type.return_value.best_match.call_args_list]
        self.assertEqual(allowed[0], {"limit", "home"})
        self.assertEqual(allowed[1], {"launcher_icon"})
        self.assertEqual(allowed[2], {"limit", "home", "free_listen", "ready"})
        self.assertIn("splash_skip", allowed[3])
        self.assertIn("ready", allowed[3])
        self.assertNotIn("launcher_icon", allowed[3])

    @patch("wyy_assist.startup.time.sleep", return_value=None)
    @patch("wyy_assist.startup.StateRecognizer")
    def test_skips_splash_when_target_app_was_already_foreground(
        self,
        recognizer_type: Mock,
        _sleep: Mock,
    ) -> None:
        recognizer_type.return_value.best_match.side_effect = [
            None,
            match("splash_skip", (1018, 80)),
            match("home", (540, 120)),
        ]
        settings = Settings(
            package="com.example.school.mockads",
            execution_enabled=True,
            consecutive_hits=1,
            startup_navigation_timeout_seconds=10.0,
        )
        adb = StartupAdb("mCurrentFocus=com.example.school.mockads/.SplashActivity")

        result = run_startup_navigation(settings, adb, execute_requested=True)

        self.assertEqual(result.reason, "startup-home")
        self.assertEqual(adb.calls, [("tap", 1018, 80)])

    @patch("wyy_assist.startup.StateRecognizer")
    def test_hands_off_when_target_app_was_already_on_business_page(
        self,
        recognizer_type: Mock,
    ) -> None:
        recognizer_type.return_value.best_match.side_effect = [
            None,
            match("ready", (540, 1180)),
        ]
        settings = Settings(
            package="com.example.school.mockads",
            execution_enabled=True,
            consecutive_hits=1,
            startup_navigation_timeout_seconds=10.0,
            templates={"ready": [TemplateSpec("ready.png")]},
        )
        adb = StartupAdb("mCurrentFocus=com.example.school.mockads/.MainActivity")

        result = run_startup_navigation(settings, adb, execute_requested=True)

        self.assertEqual(result.reason, "startup-ready")
        self.assertEqual(adb.calls, [])
        self.assertIn(
            "ready",
            recognizer_type.return_value.best_match.call_args_list[1].kwargs[
                "allowed_states"
            ],
        )


if __name__ == "__main__":
    unittest.main()
