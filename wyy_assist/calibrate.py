from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .config import save_settings
from .model import Settings, TemplateSpec, VALID_STATES


def _write_png(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("模板 PNG 编码失败")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(path)


def calibrate_template(settings: Settings, screen: np.ndarray, state: str) -> Path | None:
    if state not in VALID_STATES:
        raise ValueError(f"状态必须是: {', '.join(VALID_STATES)}")
    title = f"Select {state} template - ENTER save / ESC cancel"
    x, y, width, height = (int(value) for value in cv2.selectROI(title, screen, showCrosshair=True))
    cv2.destroyWindow(title)
    if width <= 0 or height <= 0:
        return None

    crop = screen[y : y + height, x : x + width]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    relative_path = Path("templates") / f"{state}_{stamp}.png"
    output_path = settings.config_path.parent / relative_path
    _write_png(output_path, crop)

    screen_height, screen_width = screen.shape[:2]
    padding_x = max(16, width)
    padding_y = max(16, height)
    left = max(0, x - padding_x)
    top = max(0, y - padding_y)
    right = min(screen_width, x + width + padding_x)
    bottom = min(screen_height, y + height + padding_y)
    normalized_roi = (
        left / screen_width,
        top / screen_height,
        (right - left) / screen_width,
        (bottom - top) / screen_height,
    )
    settings.templates.setdefault(state, []).append(
        TemplateSpec(path=relative_path.as_posix(), search_roi=normalized_roi)
    )
    save_settings(settings)
    return output_path
