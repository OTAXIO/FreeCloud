import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wyy_assist.cli import main, _parser
from wyy_assist.model import Settings


class CliLifecycleTests(unittest.TestCase):
    def test_default_config_is_absolute(self):
        self.assertTrue(Path(_parser().parse_args(["automate"]).config).is_absolute())

    def test_live_cli_shares_daily_and_emulator_lifecycle_before_adb_io(self):
        settings = Settings(package="com.example.test", execution_enabled=True)
        with patch("wyy_assist.cli.load_settings", return_value=settings), \
             patch("start.run", return_value=0) as run, patch("wyy_assist.cli.AdbClient") as adb:
            self.assertEqual(main(["automate", "--execute"]), 0)
            run.assert_called_once_with(settings.config_path, attach_only=True)
            adb.return_value.ensure_device.assert_not_called()

    def test_disabled_cli_never_runs_lifecycle(self):
        with patch("wyy_assist.cli.load_settings", return_value=Settings()), patch("start.run") as run:
            self.assertEqual(main(["automate", "--execute"]), 2)
            run.assert_not_called()
