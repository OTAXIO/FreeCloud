from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from wyy_assist.daily import (
    DailyRunState,
    limit_reached_today,
    mark_limit_reached,
    state_path,
)
from wyy_assist.model import Settings


class DailyRunTests(unittest.TestCase):
    def test_missing_state_has_not_reached_limit_today(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                daily_state_file="session.json",
                config_path=Path(directory) / "config.json",
            )
            self.assertFalse(limit_reached_today(settings, date(2026, 9, 9)))

    def test_limit_is_skipped_only_on_the_same_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                daily_state_file="session.json",
                config_path=Path(directory) / "config.json",
            )
            saved = mark_limit_reached(settings, date(2026, 9, 9))

            self.assertEqual(saved, state_path(settings))
            self.assertTrue(limit_reached_today(settings, date(2026, 9, 9)))
            self.assertFalse(limit_reached_today(settings, date(2026, 9, 10)))
            self.assertEqual(
                json.loads(saved.read_text(encoding="utf-8")),
                {"last_limit_date": "2026-09-09"},
            )

    def test_invalid_stored_date_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            path.write_text('{"last_limit_date": "tomorrow"}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
                DailyRunState.load(path)
