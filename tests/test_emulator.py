from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

from wyy_assist.adb import AdbError
from wyy_assist.emulator import EmulatorController
from wyy_assist.model import Settings


class FakeAdb:
    def __init__(self, devices: list[str]) -> None:
        self.connected = devices
        self.serial = ""
        self.frames = 0

    def devices(self) -> list[str]:
        return self.connected

    def ensure_device(self) -> str:
        if not self.connected:
            raise AdbError("not ready")
        self.serial = self.connected[0]
        return self.serial

    def screenshot(self) -> np.ndarray:
        self.frames += 1
        return np.zeros((1920, 1080, 3), dtype=np.uint8)


class EmulatorTests(unittest.TestCase):
    def test_launches_configured_player_when_device_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            player = Path(directory) / "dnplayer.exe"
            player.touch()
            popen = Mock()
            controller = EmulatorController(
                Settings(emulator_path=str(player)),
                popen=popen,
            )
            self.assertTrue(controller.launch_if_needed(FakeAdb([])))
            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0], [str(player)])
            self.assertEqual(popen.call_args.kwargs["cwd"], str(player.parent))

    def test_reuses_an_already_connected_emulator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            player = Path(directory) / "dnplayer.exe"
            player.touch()
            popen = Mock()
            controller = EmulatorController(
                Settings(emulator_path=str(player)),
                popen=popen,
            )
            self.assertFalse(controller.launch_if_needed(FakeAdb(["emulator-5554"])))
            popen.assert_not_called()

    def test_wait_for_frame_returns_only_after_screenshot_succeeds(self) -> None:
        adb = FakeAdb(["emulator-5554"])
        controller = EmulatorController(Settings(), sleeper=lambda _: None)
        device, screen = controller.wait_for_frame(adb)
        self.assertEqual(device, "emulator-5554")
        self.assertEqual(screen.shape, (1920, 1080, 3))
        self.assertEqual(adb.frames, 1)

    def test_close_uses_ldplayer_console_and_configured_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            player = root / "dnplayer.exe"
            console = root / "ldconsole.exe"
            player.touch()
            console.touch()
            runner = Mock(return_value=Mock(returncode=0, stderr=b""))
            controller = EmulatorController(
                Settings(emulator_path=str(player), emulator_index=2),
                runner=runner,
            )
            controller.close()
            self.assertEqual(
                runner.call_args.args[0],
                [str(console), "quit", "--index", "2"],
            )

    def test_close_prefers_ldconsole_when_both_console_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            player = root / "dnplayer.exe"
            ldconsole = root / "ldconsole.exe"
            player.touch()
            ldconsole.touch()
            (root / "dnconsole.exe").touch()
            runner = Mock(return_value=Mock(returncode=0, stderr=b""))
            controller = EmulatorController(
                Settings(emulator_path=str(player)),
                runner=runner,
            )
            controller.close()
            self.assertEqual(runner.call_args.args[0][0], str(ldconsole))


if __name__ == "__main__":
    unittest.main()
