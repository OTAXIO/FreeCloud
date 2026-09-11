from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import start
from wyy_assist.automation import AutomationResult
from wyy_assist.emulator import EmulatorError
from wyy_assist.model import Settings


class StartTests(unittest.TestCase):
    def setUp(self):
        self.entry = self.enterContext(patch("start.run_entry_navigation", return_value=AutomationResult("ready", 0)))
        self.pending = self.enterContext(patch("start.shutdown_pending", return_value=False))
        self.mark_pending = self.enterContext(patch("start.mark_shutdown_pending"))
        self.clear_pending = self.enterContext(patch("start.clear_shutdown_pending"))

    def test_explicit_relative_config_resolves_from_project(self) -> None:
        expected = (start.PROJECT_DIR / "custom.json").resolve()
        self.assertEqual(start.choose_config("custom.json"), expected)

    def test_default_config_is_used(self) -> None:
        self.assertEqual(start.choose_config(), start.DEFAULT_CONFIG)

    def test_failed_app_restart_never_enters_main_loop_or_marks_completion(self):
        from wyy_assist.recovery import RecoveryFailed
        settings = Settings(package="com.example.test", execution_enabled=True)
        with patch("start.load_settings", return_value=settings), \
             patch("start.limit_reached_today", return_value=False), \
             patch("start.AdbClient"), patch("start.EmulatorController") as controller, \
             patch("start.run_startup_navigation", side_effect=RecoveryFailed("应用重启后再次失败")), \
             patch("start.run_live") as live, patch("start.mark_limit_reached") as mark:
            controller.return_value.wait_for_frame.return_value = ("emulator-5554", Mock())
            with self.assertRaisesRegex(RecoveryFailed, "再次失败"):
                start.run(start.DEFAULT_CONFIG)
            live.assert_not_called()
            mark.assert_not_called()
            self.mark_pending.assert_not_called()
            controller.return_value.close.assert_not_called()
            controller.return_value.release_handles.assert_called_once()

    def test_none_package_is_not_configured(self) -> None:
        self.assertFalse(start.package_is_configured("none"))
        self.assertFalse(start.package_is_configured(" NONE "))
        self.assertFalse(start.package_is_configured(""))

    def test_real_test_package_is_configured(self) -> None:
        self.assertTrue(start.package_is_configured("com.example.school.mockads"))

    @patch("start.load_settings")
    @patch("start.limit_reached_today", return_value=True)
    @patch("start.AdbClient")
    @patch("start.EmulatorController")
    def test_completed_daily_run_skips_before_starting_emulator(
        self,
        emulator_controller: Mock,
        adb_client: Mock,
        _limit_reached_today: Mock,
        load_settings: Mock,
    ) -> None:
        load_settings.return_value = Settings(
            package="com.example.school.mockads",
            execution_enabled=True,
            daily_run_enabled=True,
        )

        self.assertEqual(start.run(start.DEFAULT_CONFIG), 0)
        adb_client.assert_not_called()
        emulator_controller.assert_not_called()

    @patch("start.load_settings")
    @patch("start.AdbClient")
    @patch("start.EmulatorController")
    @patch("start.preview_once")
    @patch("start.run_startup_navigation")
    @patch("start.run_live")
    def test_unconfigured_default_previews_even_when_execution_is_enabled(
        self,
        run_live: Mock,
        run_startup_navigation: Mock,
        preview_once: Mock,
        emulator_controller: Mock,
        adb_client: Mock,
        load_settings: Mock,
    ) -> None:
        load_settings.return_value = Settings(package="none", execution_enabled=True)
        emulator_controller.return_value.wait_for_frame.return_value = (
            "emulator-5554",
            Mock(),
        )
        preview_once.return_value = AutomationResult("unknown", 0)

        self.assertEqual(start.run(start.DEFAULT_CONFIG), 0)
        preview_once.assert_called_once()
        run_startup_navigation.assert_not_called()
        run_live.assert_not_called()
        emulator_controller.return_value.close.assert_called_once_with()

    @patch("start.load_settings")
    @patch("start.AdbClient")
    @patch("start.EmulatorController")
    @patch("start.preview_once")
    @patch("start.run_startup_navigation")
    @patch("start.run_live")
    def test_configured_package_runs_the_continuous_state_machine(
        self,
        run_live: Mock,
        run_startup_navigation: Mock,
        preview_once: Mock,
        emulator_controller: Mock,
        adb_client: Mock,
        load_settings: Mock,
    ) -> None:
        load_settings.return_value = Settings(
            package="com.example.school.mockads",
            execution_enabled=True,
        )
        emulator_controller.return_value.wait_for_frame.return_value = (
            "emulator-5554",
            Mock(),
        )
        run_startup_navigation.return_value = AutomationResult("startup-my_tab", 1)
        run_live.return_value = AutomationResult("limit", 8)

        self.assertEqual(start.run(start.DEFAULT_CONFIG), 0)
        run_startup_navigation.assert_called_once_with(
            load_settings.return_value,
            adb_client.return_value,
            execute_requested=True,
            navigation_states=frozenset(start.navigation_steps()),
        )
        run_live.assert_called_once_with(
            load_settings.return_value,
            adb_client.return_value,
            execute_requested=True,
            navigation_states=frozenset(start.navigation_steps()),
        )
        preview_once.assert_not_called()
        emulator_controller.return_value.launch_if_needed.assert_called_once_with(
            adb_client.return_value
        )
        emulator_controller.return_value.close.assert_called_once_with()

    @patch("start.load_settings")
    @patch("start.limit_reached_today", return_value=False)
    @patch("start.mark_limit_reached")
    @patch("start.AdbClient")
    @patch("start.EmulatorController")
    @patch("start.run_startup_navigation")
    @patch("start.run_live")
    def test_limit_result_records_daily_completion(
        self,
        run_live: Mock,
        _run_startup_navigation: Mock,
        emulator_controller: Mock,
        _adb_client: Mock,
        mark_limit_reached: Mock,
        _limit_reached_today: Mock,
        load_settings: Mock,
    ) -> None:
        settings = Settings(
            package="com.example.school.mockads",
            execution_enabled=True,
            daily_run_enabled=True,
        )
        load_settings.return_value = settings
        emulator_controller.return_value.wait_for_frame.return_value = (
            "emulator-5554",
            Mock(),
        )
        _run_startup_navigation.return_value = AutomationResult("startup-my_tab", 1)
        run_live.return_value = AutomationResult("limit", 8)
        mark_limit_reached.return_value = start.PROJECT_DIR / "session.json"

        self.assertEqual(start.run(start.DEFAULT_CONFIG), 0)
        mark_limit_reached.assert_called_once_with(settings)

    @patch("start.load_settings")
    @patch("start.AdbClient")
    @patch("start.EmulatorController")
    @patch("start.preview_once")
    def test_close_on_exit_can_be_disabled(
        self,
        preview_once: Mock,
        emulator_controller: Mock,
        adb_client: Mock,
        load_settings: Mock,
    ) -> None:
        load_settings.return_value = Settings(
            package="none",
            execution_enabled=True,
            close_emulator_on_exit=False,
            close_emulator_on_limit=False,
        )
        emulator_controller.return_value.wait_for_frame.return_value = (
            "emulator-5554",
            Mock(),
        )
        preview_once.return_value = AutomationResult("unknown", 0)

        self.assertEqual(start.run(start.DEFAULT_CONFIG), 0)
        emulator_controller.return_value.close.assert_not_called()

    @patch("start.load_settings")
    @patch("start.AdbClient")
    @patch("start.EmulatorController")
    def test_wait_failure_keeps_emulator_for_retry_dialog(
        self,
        emulator_controller: Mock,
        adb_client: Mock,
        load_settings: Mock,
    ) -> None:
        load_settings.return_value = Settings(
            package="com.example.school.mockads",
            execution_enabled=True,
            close_emulator_on_exit=True,
        )
        emulator_controller.return_value.wait_for_frame.side_effect = EmulatorError(
            "ADB frame timeout"
        )

        with self.assertRaisesRegex(EmulatorError, "ADB frame timeout"):
            start.run(start.DEFAULT_CONFIG)

        emulator_controller.return_value.close.assert_not_called()

    def test_unfinished_run_is_failure_and_keeps_emulator(self) -> None:
        settings = Settings(package="com.example.school.mockads", execution_enabled=True,
                            daily_run_enabled=True)
        with patch("start.load_settings", return_value=settings), \
             patch("start.limit_reached_today", return_value=False), \
             patch("start.mark_limit_reached") as mark, \
             patch("start.AdbClient"), patch("start.EmulatorController") as controller, \
             patch("start.run_startup_navigation", return_value=AutomationResult("startup-home", 1)), \
             patch("start.run_live", return_value=AutomationResult("stalled-ready", 3)):
            controller.return_value.wait_for_frame.return_value = ("emulator-5554", Mock())
            self.assertEqual(start.run(start.DEFAULT_CONFIG), 2)
            controller.return_value.close.assert_not_called()
            mark.assert_not_called()

    def test_limit_during_startup_is_saved_without_starting_another_cycle(self) -> None:
        settings = Settings(package="com.example.school.mockads", execution_enabled=True,
                            daily_run_enabled=True)
        with patch("start.load_settings", return_value=settings), \
             patch("start.limit_reached_today", return_value=False), \
             patch("start.mark_limit_reached") as mark, \
             patch("start.AdbClient"), patch("start.EmulatorController") as controller, \
             patch("start.run_startup_navigation", return_value=AutomationResult("startup-limit", 1)), \
             patch("start.run_live") as live:
            controller.return_value.wait_for_frame.return_value = ("emulator-5554", Mock())
            self.assertEqual(start.run(start.DEFAULT_CONFIG), 0)
            controller.return_value.close.assert_called_once()
            mark.assert_called_once_with(settings)
            live.assert_not_called()

    def test_failed_close_preserves_pending_and_retry_only_closes(self):
        settings = Settings(package="com.example.school.mockads", execution_enabled=True,
                            daily_run_enabled=True)
        with patch("start.load_settings", return_value=settings), \
             patch("start.limit_reached_today", return_value=False) as reached, \
             patch("start.mark_limit_reached") as mark, \
             patch("start.AdbClient") as adb, patch("start.EmulatorController") as controller, \
             patch("start.run_startup_navigation", return_value=AutomationResult("startup-limit", 1)), \
             patch("start.run_live") as live:
            controller.return_value.wait_for_frame.return_value = ("emulator-5554", Mock())
            controller.return_value.close.side_effect = EmulatorError("still running")
            with self.assertRaises(EmulatorError):
                start.run(start.DEFAULT_CONFIG)
            self.mark_pending.assert_called_once_with(settings)
            mark.assert_called_once_with(settings)
            self.clear_pending.assert_not_called()

            controller.reset_mock()
            adb.reset_mock()
            reached.return_value = self.pending.return_value = True
            controller.return_value.close.side_effect = None
            self.assertEqual(start.run(start.DEFAULT_CONFIG), 0)
            controller.return_value.close.assert_called_once()
            controller.return_value.launch_if_needed.assert_not_called()
            adb.assert_not_called()
            live.assert_not_called()
            self.clear_pending.assert_called_once_with(settings)

    def test_failed_pending_cleanup_is_not_cleared_or_skipped(self):
        self.pending.return_value = True
        with patch("start.load_settings", return_value=Settings()), \
             patch("start.EmulatorController") as controller:
            controller.return_value.close.side_effect = EmulatorError("not stopped")
            with self.assertRaises(EmulatorError):
                start.run(start.DEFAULT_CONFIG)
            self.clear_pending.assert_not_called()


if __name__ == "__main__":
    unittest.main()
