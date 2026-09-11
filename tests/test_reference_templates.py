from __future__ import annotations

import unittest
from pathlib import Path

import cv2
import numpy as np

from wyy_assist.config import load_settings
from wyy_assist.vision import StateRecognizer
from wyy_assist.recovery import recovery_recognizer


ROOT = Path(__file__).resolve().parents[1]


class PackagedReferenceTests(unittest.TestCase):
    def test_live_landing_back_does_not_depend_on_title(self):
        settings = load_settings(ROOT / "config.json")
        header = cv2.imdecode(np.fromfile(ROOT / "tests/fixtures/landing_header.png", dtype=np.uint8),
                              cv2.IMREAD_COLOR)
        for recognizer in (StateRecognizer(settings), recovery_recognizer(settings)):
            for title in ("original", "changed", "absent"):
                with self.subTest(recovery=recognizer.settings is not settings, title=title):
                    screen = np.full((1920, 1080, 3), 255, dtype=np.uint8)
                    screen[:header.shape[0]] = header
                    if title != "original":
                        screen[80:220, 160:900] = 255
                    if title == "changed":
                        cv2.putText(screen, "Different page", (170, 165),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
                    result = recognizer.best_match(screen, allowed_states={"landing"})
                    self.assertIsNotNone(result)
                    self.assertEqual(result.center, (84, 150))
                    # A title alone must never authorize Back.
                    screen[80:220, :150] = 255
                    self.assertIsNone(recognizer.best_match(screen, allowed_states={"landing"}))

    def test_back_arrow_outside_upper_left_is_ignored_in_normal_and_recovery_modes(self):
        settings = load_settings(ROOT / "config.json")
        template = cv2.imdecode(np.fromfile(ROOT / "templates/landing_reference.png", dtype=np.uint8),
                                cv2.IMREAD_COLOR)
        height, width = template.shape[:2]
        for recognizer in (StateRecognizer(settings), recovery_recognizer(settings)):
            for x, y in ((850, 112), (44, 500), (450, 900)):
                with self.subTest(x=x, y=y):
                    screen = np.full((1920, 1080, 3), 255, dtype=np.uint8)
                    screen[y:y+height, x:x+width] = template
                    self.assertIsNone(recognizer.best_match(screen, allowed_states={"landing"}))

    def test_limit_text_outside_old_roi_wins_over_channel_heading(self):
        settings = load_settings(ROOT / "config.json")
        before = settings.to_dict()
        recognizer = StateRecognizer(settings)
        screen = np.zeros((1920, 1080, 3), dtype=np.uint8)
        for item in recognizer.templates:
            if item.state not in {"limit", "free_listen"}:
                continue
            x, y = (300, 1700) if item.state == "limit" else (550, 100)
            h, w = item.image.shape
            screen[y:y+h, x:x+w] = cv2.cvtColor(item.image, cv2.COLOR_GRAY2BGR)
        self.assertEqual(recognizer.best_match(screen).state, "limit")
        self.assertEqual(settings.to_dict(), before)

    def test_recovery_finds_relocated_exit_glyphs_without_changing_config(self) -> None:
        settings = load_settings(ROOT / "config.json")
        before = settings.to_dict()
        recognizer = recovery_recognizer(settings)
        for item in recognizer.templates:
            with self.subTest(template=item.path.name):
                screen = np.zeros((1920, 1080, 3), dtype=np.uint8)
                height, width = item.image.shape
                # Deliberately outside each template's normal screen region.
                screen[600:600 + height, 320:320 + width] = cv2.cvtColor(item.image, cv2.COLOR_GRAY2BGR)
                matched = recognizer.best_match(screen, allowed_states={item.state})
                if item.state == "landing":
                    self.assertIsNone(matched)
                    continue
                self.assertIsNotNone(matched)
                self.assertEqual(matched.center, (320 + width // 2, 600 + height // 2))
        self.assertEqual(before, settings.to_dict())

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

    def test_scrolled_fallback_page_is_recognized_as_ready(self) -> None:
        settings = load_settings(ROOT / "config.json")
        screen = cv2.imdecode(
            np.fromfile(ROOT / "templates" / "ready_scrolled_reference.png", dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        self.assertIsNotNone(screen)
        assert screen is not None
        match = StateRecognizer(settings).best_match(screen)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.state, "ready")

    def test_each_packaged_reference_is_recognized_in_its_search_area(self) -> None:
        settings = load_settings(ROOT / "config.json")
        recognizer = StateRecognizer(settings)
        placements = {
            "launcher_icon": (100, 400),
            "splash_skip": (950, 80),
            "home": (300, 100),
            "free_listen": (550, 100),
            "ready": (345, 1122),
            "ad_interaction": (42, 118),
            "download_prompt": (70, 900),
            "landing": (44, 112),
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
                match = recognizer.best_match(screen, allowed_states=set(placements))
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(match.state, state)


if __name__ == "__main__":
    unittest.main()
