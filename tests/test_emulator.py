from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from wyy_assist.adb import AdbError
from wyy_assist.emulator import EmulatorController, EmulatorError, parse_instance
from wyy_assist.model import Settings
from wyy_assist.process import is_emulator_binary


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


class Console:
    def __init__(self, index=0, quit_works=True):
        self.index = index
        self.running = True
        self.quit_works = quit_works
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[1] == "list2":
            state = "1,2,1,100,101" if self.running else "0,0,0,-1,-1"
            output = f"{self.index},player,{state},1080,1920,480"
        elif command[1] == "isrunning":
            output = "running" if self.running else "stop"
        else:
            output = ""
            if self.quit_works:
                self.running = False
        return Mock(returncode=0, stdout=output.encode(), stderr=b"")


class Process:
    def __init__(self, pid, console):
        self.pid = pid
        self.console = console
        self.terminated = self.closed = False

    def alive(self):
        return self.console.running

    def terminate(self):
        self.terminated = True
        self.console.running = False

    def close(self):
        self.closed = True


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

    def test_connected_adb_still_requests_visible_emulator_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            player = Path(directory) / "dnplayer.exe"
            player.touch()
            popen = Mock()
            controller = EmulatorController(
                Settings(emulator_path=str(player)),
                popen=popen,
            )
            self.assertFalse(controller.launch_if_needed(FakeAdb(["emulator-5554"])))
            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0], [str(player)])

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
            runner = Console(index=2)
            controller = EmulatorController(
                Settings(emulator_path=str(player), emulator_index=2),
                runner=runner, process_factory=lambda pid, root: Process(pid, runner),
                sleeper=lambda _: None,
            )
            controller.close()
            self.assertEqual(
                runner.calls[1][0],
                [str(console), "quit", "--index", "2"],
            )
            self.assertTrue(all(call[1]["cwd"] == str(root) for call in runner.calls))
            self.assertEqual(runner.calls[-1][0][1], "isrunning")

    def test_close_prefers_ldconsole_when_both_console_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            player = root / "dnplayer.exe"
            ldconsole = root / "ldconsole.exe"
            player.touch()
            ldconsole.touch()
            (root / "dnconsole.exe").touch()
            runner = Console()
            controller = EmulatorController(
                Settings(emulator_path=str(player)),
                runner=runner, process_factory=lambda pid, root: Process(pid, runner),
                sleeper=lambda _: None,
            )
            controller.close()
            self.assertTrue(all(call[0][0] == str(ldconsole) for call in runner.calls))

    def test_stuck_quit_retries_then_only_terminates_captured_instance_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ldconsole.exe").touch()
            runner = Console(quit_works=False)
            now = [0.0]
            owned = []
            def process(pid, installation):
                self.assertEqual(installation, root)
                item = Process(pid, runner)
                owned.append(item)
                return item
            controller = EmulatorController(Settings(emulator_path=str(root / "dnplayer.exe")),
                runner=runner, process_factory=process, monotonic=lambda: now[0],
                sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds))
            controller.close()
            self.assertGreaterEqual(now[0], 30)
            self.assertEqual([p.pid for p in owned], [100, 101])
            self.assertTrue(any(p.terminated for p in owned))
            self.assertTrue(all(p.closed for p in owned))
            self.assertGreater(len([c for c, _ in runner.calls if c[1] == "quit"]), 1)

    def test_successful_quit_return_is_not_proof_of_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ldconsole.exe").touch()
            runner = Console(quit_works=False)
            now = [0.0]
            owned = Mock(pid=100)
            owned.alive.return_value = True
            controller = EmulatorController(Settings(emulator_path=str(root / "dnplayer.exe")),
                runner=runner, process_factory=lambda *args: owned, monotonic=lambda: now[0],
                sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds))
            with self.assertRaises(EmulatorError):
                controller.close()
            self.assertEqual(now[0], 40)
            owned.close.assert_called()

    def test_missing_or_malformed_instance_is_not_treated_as_closed(self):
        for output in ("", "0,other,0,0,0,-1,-1", "2,player,0"):
            with self.subTest(output=output), self.assertRaises(EmulatorError):
                parse_instance(output, 2)

    def test_accepts_original_seven_field_status(self):
        self.assertTrue(parse_instance("2,player,0,0,0,-1,-1", 2).stopped)

    def test_separate_ldplayer_vm_installation_is_narrowly_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installation = root / "player"
            with patch.dict("os.environ", {"ProgramFiles": str(root)}):
                self.assertTrue(is_emulator_binary(root / "ldplayer9box" / "Ld9BoxHeadless.exe", installation))
                self.assertFalse(is_emulator_binary(root / "unrelated" / "Ld9BoxHeadless.exe", installation))
                self.assertFalse(is_emulator_binary(root / "ldplayer9box" / "anything.exe", installation))


if __name__ == "__main__":
    unittest.main()
