from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from wyy_assist.model import Settings, TemplateSpec
from wyy_assist.vision import StateRecognizer, normalized_roi_to_pixels


def write_png(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise AssertionError("test fixture encoding failed")
    encoded.tofile(path)


class VisionTests(unittest.TestCase):
    def test_normalized_roi_is_clamped(self) -> None:
        self.assertEqual(normalized_roi_to_pixels((0.25, 0.2, 0.5, 0.6), (100, 200)), (50, 20, 100, 60))

    def test_best_match_finds_template_center(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screen = np.zeros((160, 240, 3), dtype=np.uint8)
            # Non-constant pattern avoids undefined normalized correlation.
            pattern = np.zeros((24, 32, 3), dtype=np.uint8)
            cv2.rectangle(pattern, (2, 2), (29, 21), (255, 255, 255), 2)
            cv2.line(pattern, (4, 19), (27, 4), (127, 127, 127), 2)
            screen[70:94, 120:152] = pattern
            template_path = root / "ready.png"
            write_png(template_path, pattern)
            settings = Settings(
                threshold=0.9,
                templates={"ready": [TemplateSpec("ready.png", (0.35, 0.25, 0.45, 0.55))]},
                config_path=root / "config.json",
            )
            match = StateRecognizer(settings).best_match(screen)
            self.assertIsNotNone(match)
            assert match is not None
            self.assertEqual(match.state, "ready")
            self.assertEqual(match.center, (136, 82))
            self.assertGreater(match.score, 0.99)

    def test_no_match_below_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rng = np.random.default_rng(42)
            screen = rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)
            template = rng.integers(0, 255, (18, 20, 3), dtype=np.uint8)
            write_png(root / "limit.png", template)
            settings = Settings(
                threshold=0.9999,
                templates={"limit": [TemplateSpec("limit.png")]},
                config_path=root / "config.json",
            )
            self.assertIsNone(StateRecognizer(settings).best_match(screen))

    def test_template_roi_matches_and_returns_cropped_target_center(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = np.zeros((60, 120, 3), dtype=np.uint8)
            target = template[30:54, 12:48]
            cv2.rectangle(target, (1, 1), (34, 22), (255, 255, 255), 2)
            cv2.line(target, (3, 20), (31, 3), (127, 127, 127), 2)
            write_png(root / "prompt.png", template)
            screen = np.zeros((160, 240, 3), dtype=np.uint8)
            screen[70:130, 80:200] = template
            settings = Settings(
                threshold=0.9,
                template_scales=[1.0],
                templates={
                    "download_prompt": [
                        TemplateSpec(
                            "prompt.png",
                            template_roi=(0.1, 0.5, 0.3, 0.4),
                        )
                    ]
                },
                config_path=root / "config.json",
            )

            match = StateRecognizer(settings).best_match(screen)
            self.assertIsNotNone(match)
            assert match is not None
            self.assertEqual(match.center, (110, 112))

    def test_state_priority_wins_when_overlay_and_background_both_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screen = np.zeros((180, 240, 3), dtype=np.uint8)
            background = np.zeros((25, 35, 3), dtype=np.uint8)
            overlay = np.zeros((22, 31, 3), dtype=np.uint8)
            cv2.circle(background, (17, 12), 9, (180, 180, 180), 2)
            cv2.line(background, (2, 2), (32, 22), (255, 255, 255), 2)
            cv2.rectangle(overlay, (2, 2), (28, 19), (255, 255, 255), 2)
            cv2.line(overlay, (4, 18), (27, 3), (130, 130, 130), 2)
            screen[40:65, 30:65] = background
            screen[90:112, 130:161] = overlay
            write_png(root / "landing.png", background)
            write_png(root / "prompt.png", overlay)
            settings = Settings(
                threshold=0.9,
                template_scales=[1.0],
                state_priority=["download_prompt", "landing"],
                templates={
                    "landing": [TemplateSpec("landing.png")],
                    "download_prompt": [TemplateSpec("prompt.png")],
                },
                config_path=root / "config.json",
            )
            match = StateRecognizer(settings).best_match(screen)
            self.assertIsNotNone(match)
            assert match is not None
            self.assertEqual(match.state, "download_prompt")


if __name__ == "__main__":
    unittest.main()
