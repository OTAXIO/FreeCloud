from __future__ import annotations

import unittest
from pathlib import Path

import cv2
import numpy as np

from wyy_assist.config import load_settings
from wyy_assist.vision import StateRecognizer


ROOT = Path(__file__).resolve().parents[1]


class PackagedReferenceTests(unittest.TestCase):
    def test_top_ad_close_icon_is_classified_as_close_not_interaction(self) -> None:
        settings = load_settings(ROOT / "config.json")
        interaction_paths = {spec.path for spec in settings.templates["ad_interaction"]}
        close_paths = {spec.path for spec in settings.templates["ad_close"]}
        path = "templates/ad_interaction_close_reference.png"
        self.assertNotIn(path, interaction_paths)
        self.assertIn(path, close_paths)

    def test_ready_button_is_not_misclassified_as_limit_text(self) -> None:
        settings = load_settings(ROOT / "config.json")
        settings.templates = {"limit": settings.templates["limit"]}
        settings.state_priority = ["limit"]
        recognizer = StateRecognizer(settings)
        ready = cv2.imdecode(
            np.fromfile(ROOT / "templates" / "ready_reference.png", dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(ready)
        assert ready is not None
        screen = np.zeros((1920, 1080, 3), dtype=np.uint8)
        height, width = ready.shape[:2]
        screen[1122 : 1122 + height, 345 : 345 + width] = ready
        self.assertIsNone(recognizer.best_match(screen))

    def test_each_packaged_reference_is_recognized_in_its_search_area(self) -> None:
        settings = load_settings(ROOT / "config.json")
        recognizer = StateRecognizer(settings)
        placements = {
            "home": (300, 100),
            "free_listen": (550, 100),
            "ready": (345, 1122),
            "ad_interaction": (42, 118),
            "download_prompt": (70, 900),
            "landing": (50, 20),
            "ad_close": (470, 1415),
            "limit": (150, 800),
        }
        for state, (x, y) in placements.items():
            with self.subTest(state=state):
                template_path = ROOT / "templates" / f"{state}_reference.png"
                template = cv2.imdecode(np.fromfile(template_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                self.assertIsNotNone(template)
                assert template is not None
                screen = np.zeros((1920, 1080, 3), dtype=np.uint8)
                height, width = template.shape[:2]
                screen[y : y + height, x : x + width] = template
                match = recognizer.best_match(screen)
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(match.state, state)


if __name__ == "__main__":
    unittest.main()
