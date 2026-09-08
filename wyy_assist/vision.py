from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .model import Match, Settings, TemplateSpec


@dataclass(frozen=True)
class LoadedTemplate:
    state: str
    spec: TemplateSpec
    path: Path
    image: np.ndarray


def normalized_roi_to_pixels(
    roi: tuple[float, float, float, float] | None,
    image_shape: tuple[int, ...],
) -> tuple[int, int, int, int]:
    height, width = image_shape[:2]
    if roi is None:
        return 0, 0, width, height
    x, y, roi_width, roi_height = roi
    left = max(0, min(width - 1, round(x * width)))
    top = max(0, min(height - 1, round(y * height)))
    right = max(left + 1, min(width, round((x + roi_width) * width)))
    bottom = max(top + 1, min(height, round((y + roi_height) * height)))
    return left, top, right - left, bottom - top


def _read_template(path: Path) -> np.ndarray:
    # cv2.imread has inconsistent Unicode-path behavior on Windows.
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise FileNotFoundError(f"无法读取模板: {path}") from exc
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"模板不是有效图片: {path}")
    return image


class StateRecognizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        base = settings.config_path.parent
        self.templates: list[LoadedTemplate] = []
        for state, specs in settings.templates.items():
            for spec in specs:
                path = Path(spec.path)
                if not path.is_absolute():
                    path = (base / path).resolve()
                image = _read_template(path)
                if spec.template_roi is not None:
                    x, y, width, height = normalized_roi_to_pixels(spec.template_roi, image.shape)
                    image = image[y : y + height, x : x + width].copy()
                self.templates.append(LoadedTemplate(state, spec, path, image))

    def best_match(self, screen: np.ndarray) -> Match | None:
        if screen.size == 0:
            raise ValueError("截图为空")
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY) if screen.ndim == 3 else screen
        matches: dict[str, Match] = {}
        for item in self.templates:
            x, y, width, height = normalized_roi_to_pixels(item.spec.search_roi, gray.shape)
            search = gray[y : y + height, x : x + width]
            for scale in self.settings.template_scales:
                template = item.image
                if scale != 1.0:
                    template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                if template.shape[0] < 3 or template.shape[1] < 3:
                    continue
                if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
                    continue
                response = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, location = cv2.minMaxLoc(response)
                threshold = item.spec.threshold or self.settings.threshold
                if score < threshold:
                    continue
                center = (
                    x + location[0] + template.shape[1] // 2,
                    y + location[1] + template.shape[0] // 2,
                )
                candidate = Match(item.state, float(score), center, item.path)
                previous = matches.get(item.state)
                if previous is None or candidate.score > previous.score:
                    matches[item.state] = candidate

        for state in self.settings.state_priority:
            if state in matches:
                return matches[state]
        return max(matches.values(), key=lambda match: match.score, default=None)
