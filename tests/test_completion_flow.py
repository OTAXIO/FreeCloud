from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from dataclasses import replace
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

import start
from wyy_assist.config import load_settings
from wyy_assist.daily import DailyRunState, state_path
from wyy_assist.emulator import EmulatorError
from wyy_assist.recovery import recover_page
from wyy_assist.result import AutomationResult
from wyy_assist.shutdown import shutdown_pending
from wyy_assist.vision import StateRecognizer

ROOT = Path(__file__).resolve().parents[1]


def read(relative):
    return cv2.imdecode(np.fromfile(ROOT / relative, dtype=np.uint8), cv2.IMREAD_COLOR)


def completed_screen(x=330, y=1140):
    screen = np.full((1920, 1080, 3), 245, dtype=np.uint8)
    text = read("tests/fixtures/navigation_completed_text.png")
    height, width = text.shape[:2]
    screen[y:y+height, x:x+width] = text
    return screen


def settings_at(directory):
    settings = load_settings(ROOT / "config.json")
    templates = {state: [replace(spec, path=str(ROOT / spec.path)) for spec in specs]
                 for state, specs in settings.templates.items()}
    return replace(settings, config_path=Path(directory) / "config.json", templates=templates,
                   daily_run_enabled=True, daily_state_file="session.json", consecutive_hits=2,
                   poll_interval_seconds=0.01, close_emulator_on_limit=True)


class CompletionFlowTests(unittest.TestCase):
    def test_completion_wins_over_ready_even_if_priority_omits_limit(self):
        settings = load_settings(ROOT / "config.json")
        settings.state_priority = ["ready", "ad_close", "home"]
        screen = read("tests/fixtures/navigation_vip_page.png")
        text = read("tests/fixtures/navigation_completed_text.png")
        screen[1500:1590, 330:750] = text
        recognizer = StateRecognizer(settings)
        self.assertEqual(recognizer.best_match(screen, {"ready"}).state, "ready")
        self.assertEqual(recognizer.best_match(screen, {"ready", "limit"}).state, "limit")
        self.assertEqual(recognizer.best_match(screen).state, "limit")

    def test_completion_text_can_move_across_the_screen(self):
        recognizer = StateRecognizer(load_settings(ROOT / "config.json"))
        for x, y in ((30, 250), (330, 1140), (580, 1750)):
            with self.subTest(x=x, y=y):
                self.assertEqual(recognizer.best_match(completed_screen(x, y), {"limit"}).state, "limit")
        blank = np.full((1920, 1080, 3), 245, dtype=np.uint8)
        self.assertIsNone(recognizer.best_match(blank, {"limit"}))

    def test_actual_end_text_in_every_stage_reaches_verified_close(self):
        completed = completed_screen()
        ready = read("tests/fixtures/navigation_vip_page.png")
        unknown = np.full_like(ready, 245)
        sequences = {
            "startup": [completed, completed],
            "entry": [completed, completed],
            "main": [ready, ready, ready, ready, completed, completed],
            "recovery": [ready, ready, ready, ready, unknown, completed, completed],
        }
        for stage, frames in sequences.items():
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                settings = settings_at(directory)
                adb = Mock()
                adb.foreground_window.return_value = settings.package + "/.Main"
                adb.command_deadline.return_value = nullcontext()
                adb.screenshot.side_effect = frames
                controller = Mock()
                controller.wait_for_frame.return_value = ("emulator-5554", frames[0])
                def close():
                    # Closing happens after durable completion/pending records.
                    self.assertEqual(DailyRunState.load(state_path(settings)).last_limit_date, date.today())
                    self.assertTrue(shutdown_pending(settings))
                controller.close.side_effect = close
                initial = (patch("start.run_startup_navigation", return_value=AutomationResult("startup-my_tab", 1))
                           if stage == "entry" else nullcontext())
                output = StringIO()
                with patch("start.load_settings", return_value=settings), \
                     patch("start.AdbClient", return_value=adb), \
                     patch("start.EmulatorController", return_value=controller), \
                     patch("wyy_assist.automation.recover_page", wraps=recover_page) as recovery, \
                     patch("time.sleep"), initial, redirect_stdout(output):
                    self.assertEqual(start.run(settings.config_path), 0)
                self.assertEqual(adb.screenshot.call_count, len(frames))
                adb.tap.assert_not_called()
                adb.swipe.assert_not_called()
                adb.back.assert_not_called()
                controller.close.assert_called_once()
                self.assertFalse(shutdown_pending(settings))
                self.assertEqual(recovery.call_count, int(stage == "recovery"))
                self.assertIn("已确认‘已全部点亮，明天再来’", output.getvalue())
                self.assertIn("程序结束：limit", output.getvalue())

    def test_unconfirmed_end_frame_never_triggers_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = settings_at(directory)
            adb = Mock()
            adb.foreground_window.return_value = settings.package + "/.Main"
            adb.command_deadline.return_value = nullcontext()
            adb.screenshot.side_effect = [completed_screen(), RuntimeError("screen lost before confirmation")]
            controller = Mock()
            controller.wait_for_frame.return_value = ("emulator-5554", Mock())
            with patch("start.load_settings", return_value=settings), \
                 patch("start.AdbClient", return_value=adb), \
                 patch("start.EmulatorController", return_value=controller), patch("time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "before confirmation"):
                    start.run(settings.config_path)
            controller.close.assert_not_called()
            self.assertFalse(state_path(settings).exists())
            self.assertFalse(shutdown_pending(settings))

    def test_close_failure_keeps_pending_and_next_run_only_retries_close(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = settings_at(directory)
            adb = Mock()
            adb.foreground_window.return_value = settings.package + "/.Main"
            adb.command_deadline.return_value = nullcontext()
            adb.screenshot.return_value = completed_screen()
            controller = Mock()
            controller.wait_for_frame.return_value = ("emulator-5554", Mock())
            controller.close.side_effect = [EmulatorError("still running"), None]
            with patch("start.load_settings", return_value=settings), \
                 patch("start.AdbClient", return_value=adb) as factory, \
                 patch("start.EmulatorController", return_value=controller), patch("time.sleep"):
                with self.assertRaises(EmulatorError):
                    start.run(settings.config_path)
                self.assertTrue(shutdown_pending(settings))
                self.assertEqual(DailyRunState.load(state_path(settings)).last_limit_date, date.today())
                factory.reset_mock()
                controller.launch_if_needed.reset_mock()
                self.assertEqual(start.run(settings.config_path), 0)
                factory.assert_not_called()
                controller.launch_if_needed.assert_not_called()
                self.assertFalse(shutdown_pending(settings))
                self.assertEqual(controller.close.call_count, 2)
