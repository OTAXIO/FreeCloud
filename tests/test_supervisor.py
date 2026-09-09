from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from wyy_assist.model import Settings
from wyy_assist.supervisor import BootRunState, launch_worker, supervise


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.config = Path(directory) / "config.json"
        self.settings = Settings(config_path=self.config)
        self.enterContext(patch("wyy_assist.supervisor.single_instance", return_value=nullcontext(True)))
        self.enterContext(patch("wyy_assist.supervisor.boot_id", return_value="boot-A"))
        self.enterContext(patch("wyy_assist.supervisor.load_settings", return_value=self.settings))
        self.worker = self.enterContext(patch("wyy_assist.supervisor.launch_worker"))
        self.prompt = self.enterContext(patch("wyy_assist.supervisor.ask_continue"))
        self.control = BootRunState(self.config.with_name("session.control.json"))

    def worker_results(self, codes):
        remaining = iter(codes)
        def run(config, log):
            log.write_text("失败详情\n", encoding="utf-8")
            return next(remaining)
        self.worker.side_effect = run

    def test_continue_restarts_worker_and_does_not_record_abandon(self):
        self.worker_results([2, 0])
        self.prompt.return_value = True
        self.assertEqual(supervise(self.config, autorun=True), 0)
        self.assertEqual(self.worker.call_count, 2)
        self.prompt.assert_called_once()
        self.assertFalse(self.control.abandoned("boot-A"))

    def test_abandon_blocks_later_autorun_on_same_boot_but_not_next_boot(self):
        self.worker_results([2])
        self.prompt.return_value = False
        self.assertEqual(supervise(self.config, autorun=True), 0)
        self.assertTrue(self.control.abandoned("boot-A"))
        self.assertFalse(self.control.abandoned("boot-B"))
        self.worker.reset_mock()
        self.assertEqual(supervise(self.config, autorun=True), 0)
        self.worker.assert_not_called()
        self.assertFalse(self.config.with_name("session.json").exists())

    def test_manual_run_can_override_boot_abandon(self):
        self.control.abandon("boot-A")
        self.worker_results([0])
        self.assertEqual(supervise(self.config, autorun=False), 0)
        self.worker.assert_called_once()
        self.prompt.assert_not_called()

    def test_duplicate_start_does_not_create_second_worker(self):
        with patch("wyy_assist.supervisor.single_instance", return_value=nullcontext(False)):
            self.assertEqual(supervise(self.config, autorun=True), 0)
        self.worker.assert_not_called()

    def test_daily_limit_skip_never_prompts_or_launches_worker(self):
        self.settings.package = "com.example.school.mockads"
        self.settings.execution_enabled = self.settings.daily_run_enabled = True
        with patch("wyy_assist.supervisor.limit_reached_today", return_value=True):
            self.assertEqual(supervise(self.config, autorun=True), 0)
        self.worker.assert_not_called()
        self.prompt.assert_not_called()

    def test_daily_limit_does_not_skip_pending_shutdown(self):
        self.settings.package = "com.example.school.mockads"
        self.settings.execution_enabled = self.settings.daily_run_enabled = True
        self.worker_results([0])
        with patch("wyy_assist.supervisor.limit_reached_today", return_value=True), \
             patch("wyy_assist.supervisor.shutdown_pending", return_value=True):
            self.assertEqual(supervise(self.config, autorun=True), 0)
        self.worker.assert_called_once()

    def test_ctrl_c_stops_worker_before_retry_dialog_can_launch_another(self):
        process = Mock()
        process.wait.side_effect = [KeyboardInterrupt(), 130]
        with patch("wyy_assist.supervisor.subprocess.Popen", return_value=process):
            code = launch_worker(self.config, self.config.with_name("attempt.log"))
        self.assertEqual(code, 130)
        process.terminate.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
