import tempfile
import unittest
from pathlib import Path

from wyy_assist.model import Settings
from wyy_assist.shutdown import (clear_shutdown_pending, mark_shutdown_pending,
                                 pending_path, shutdown_pending)


class ShutdownTests(unittest.TestCase):
    def test_pending_survives_reload_until_verified_close(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(config_path=Path(directory) / "config.json")
            self.assertFalse(shutdown_pending(settings))
            mark_shutdown_pending(settings)
            self.assertTrue(shutdown_pending(settings))
            self.assertEqual(pending_path(settings).parent, Path(directory))
            clear_shutdown_pending(settings)
            self.assertFalse(shutdown_pending(settings))

    def test_changed_instance_is_never_silently_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(config_path=Path(directory) / "config.json")
            mark_shutdown_pending(settings)
            settings.emulator_index += 1
            with self.assertRaises(ValueError):
                shutdown_pending(settings)
