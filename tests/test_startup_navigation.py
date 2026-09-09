from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from wyy_assist.automation import run_startup_navigation, runtime_recognition_states
from wyy_assist.model import Match, Settings, TemplateSpec


class StartupAdb:
    def __init__(self, foreground: str = "com.android.launcher") -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.foreground = foreground

    def screenshot(self) -> np.ndarray:
        return np.zeros((1920, 1080, 3), dtype=np.uint8)

    def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", x, y))

    def foreground_window(self) -> str:
        return self.foreground


def match(state: str, center: tuple[int, int]) -> Match:
    return Match(state, 1.0, center, Path(f"{state}.png"))


class StartupNavigationTests(unittest.TestCase):
    def test_main_state_machine_excludes_launcher_and_splash_states(self) -> None:
        settings = Settings(
            templates={
                "launcher_icon": [TemplateSpec("launcher.png")],
                "splash_skip": [TemplateSpec("skip.png")],
                "home": [TemplateSpec("home.png")],
                "ready": [TemplateSpec("ready.png")],
            }
        )
        self.assertEqual(runtime_recognition_states(settings), {"home", "ready"})

    @patch("wyy_assist.automation.time.sleep", return_value=None)
    @patch("wyy_assist.automation.StateRecognizer")
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
        self.assertEqual(allowed[0], {"home"})
        self.assertEqual(allowed[1], {"launcher_icon"})
        self.assertEqual(allowed[2], {"home"})
        self.assertIn("splash_skip", allowed[3])
        self.assertIn("ready", allowed[3])
        self.assertNotIn("launcher_icon", allowed[3])

    @patch("wyy_assist.automation.time.sleep", return_value=None)
    @patch("wyy_assist.automation.StateRecognizer")
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

    @patch("wyy_assist.automation.StateRecognizer")
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
