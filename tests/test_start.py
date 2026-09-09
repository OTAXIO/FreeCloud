from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import start
from wyy_assist.automation import AutomationResult
from wyy_assist.emulator import EmulatorError
from wyy_assist.model import Settings


class StartTests(unittest.TestCase):
    def test_explicit_relative_config_resolves_from_project(self) -> None:
        expected = (start.PROJECT_DIR / "custom.json").resolve()
        self.assertEqual(start.choose_config("custom.json"), expected)

    def test_default_config_is_used(self) -> None:
        self.assertEqual(start.choose_config(), start.DEFAULT_CONFIG)

    def test_none_package_is_not_configured(self) -> None:
        self.assertFalse(start.package_is_configured("none"))
        self.assertFalse(start.package_is_configured(" NONE "))
        self.assertFalse(start.package_is_configured(""))

    def test_real_test_package_is_configured(self) -> None:
        self.assertTrue(start.package_is_configured("com.example.school.mockads"))

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
        run_live.return_value = AutomationResult("limit", 8)

        self.assertEqual(start.run(start.DEFAULT_CONFIG), 0)
        run_startup_navigation.assert_called_once_with(
            load_settings.return_value,
            adb_client.return_value,
            execute_requested=True,
        )
        run_live.assert_called_once_with(
            load_settings.return_value,
            adb_client.return_value,
            execute_requested=True,
        )
        preview_once.assert_not_called()
        emulator_controller.return_value.launch_if_needed.assert_called_once_with(
            adb_client.return_value
        )
        emulator_controller.return_value.close.assert_called_once_with()

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
    def test_wait_failure_still_closes_launched_emulator(
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

        emulator_controller.return_value.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
