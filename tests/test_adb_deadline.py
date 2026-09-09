from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wyy_assist.adb import AdbClient, AdbError


class AdbDeadlineTests(unittest.TestCase):
    def test_deadline_bounds_io_and_prevents_commands_after_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / "adb.exe"
            exe.touch()
            adb = AdbClient(exe)
            result = Mock(returncode=0, stdout=b"", stderr=b"")
            with patch("wyy_assist.adb.time.monotonic", return_value=10), \
                 patch("wyy_assist.adb.subprocess.run", return_value=result) as run:
                with adb.command_deadline(11):
                    adb.run("devices", timeout=20)
                self.assertEqual(run.call_args.kwargs["timeout"], 1)
                adb.run("devices", timeout=20)
                self.assertEqual(run.call_args.kwargs["timeout"], 20)
                with adb.command_deadline(9):
                    with self.assertRaises(AdbError):
                        adb.run("devices")
                self.assertEqual(run.call_count, 2)
