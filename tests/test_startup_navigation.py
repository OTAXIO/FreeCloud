from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from wyy_assist.automation import run_startup_navigation
from wyy_assist.model import Match, Settings


class StartupAdb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def screenshot(self) -> np.ndarray:
        return np.zeros((1920, 1080, 3), dtype=np.uint8)

    def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", x, y))


def match(state: str, center: tuple[int, int]) -> Match:
    return Match(state, 1.0, center, Path(f"{state}.png"))


class StartupNavigationTests(unittest.TestCase):
    @patch("wyy_assist.automation.time.sleep", return_value=None)
    @patch("wyy_assist.automation.StateRecognizer")
    def test_clicks_launcher_then_skip_and_hands_off_to_original_state_machine(
        self,
        recognizer_type: Mock,
        _sleep: Mock,
    ) -> None:
        recognizer_type.return_value.best_match.side_effect = [
            match("launcher_icon", (120, 420)),
            match("splash_skip", (1018, 80)),
            match("home", (540, 120)),
        ]
        settings = Settings(
            package="com.example.school.mockads",
            execution_enabled=True,
            consecutive_hits=1,
            startup_navigation_timeout_seconds=10.0,
        )
        adb = StartupAdb()

        result = run_startup_navigation(settings, adb, execute_requested=True)

        self.assertEqual(result.reason, "startup-home")
        self.assertEqual(
            adb.calls,
            [("tap", 120, 420), ("tap", 1018, 80)],
        )


if __name__ == "__main__":
    unittest.main()
