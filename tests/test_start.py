from __future__ import annotations

import unittest

import start


class StartTests(unittest.TestCase):
    def test_explicit_relative_config_resolves_from_project(self) -> None:
        expected = (start.PROJECT_DIR / "custom.json").resolve()
        self.assertEqual(start.choose_config("custom.json"), expected)

    def test_default_config_is_used(self) -> None:
        self.assertEqual(start.choose_config(), start.DEFAULT_CONFIG)


if __name__ == "__main__":
    unittest.main()
