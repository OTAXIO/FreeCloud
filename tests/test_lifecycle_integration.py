from contextlib import nullcontext, redirect_stdout
from io import StringIO
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import start
from wyy_assist.automation import AutomationResult
from wyy_assist.daily import DailyRunState, state_path
from wyy_assist.model import Settings
from wyy_assist.shutdown import shutdown_pending


class LifecycleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("start.run_entry_navigation", return_value=AutomationResult("ready", 0)))

    def test_limit_persists_then_manual_run_skips_before_adb(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(config_path=Path(directory) / "config.json",
                                package="com.example.test", execution_enabled=True, daily_run_enabled=True)
            with patch("start.load_settings", return_value=settings), \
                 patch("start.AdbClient") as adb, patch("start.EmulatorController") as emulator, \
                 patch("start.run_startup_navigation", return_value=AutomationResult("startup-limit", 1)), \
                 patch("start.run_live") as live:
                emulator.return_value.wait_for_frame.return_value = ("emulator-5554", Mock())
                self.assertEqual(start.run(settings.config_path), 0)
                self.assertEqual(DailyRunState.load(state_path(settings)).last_limit_date, date.today())
                self.assertFalse(shutdown_pending(settings))
                emulator.return_value.close.assert_called_once()
                adb.reset_mock()
                emulator.reset_mock()
                output = StringIO()
                with redirect_stdout(output), \
                     patch("wyy_assist.supervisor.load_settings", return_value=settings), \
                     patch("wyy_assist.supervisor.single_instance", return_value=nullcontext(True)), \
                     patch("wyy_assist.supervisor.launch_worker") as worker:
                    self.assertEqual(start.main(["--no-pause", "--config", str(settings.config_path)]), 0)
                    worker.assert_not_called()
                adb.assert_not_called()
                emulator.assert_not_called()
                live.assert_not_called()
            self.assertIn("跳过运行", output.getvalue())
            self.assertIn(str(state_path(settings)), output.getvalue())

    def test_attached_cli_completion_closes_emulator_and_next_run_skips(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(config_path=Path(directory) / "config.json",
                                package="com.example.test", execution_enabled=True, daily_run_enabled=True)
            with patch("start.load_settings", return_value=settings), \
                 patch("start.AdbClient") as adb, patch("start.EmulatorController") as emulator, \
                 patch("start.run_startup_navigation") as startup, \
                 patch("start.run_live", return_value=AutomationResult("limit", 1)) as live:
                self.assertEqual(start.run(settings.config_path, attach_only=True), 0)
                emulator.return_value.bind_device.assert_called_once_with(adb.return_value)
                emulator.return_value.launch_if_needed.assert_not_called()
                startup.assert_not_called()
                emulator.return_value.close.assert_called_once()
                self.assertEqual(DailyRunState.load(state_path(settings)).last_limit_date, date.today())
                adb.reset_mock()
                emulator.reset_mock()
                live.reset_mock()
                self.assertEqual(start.run(settings.config_path, attach_only=True), 0)
                adb.assert_not_called()
                emulator.assert_not_called()
                live.assert_not_called()
