"""Build initial recognition templates from the screenshots supplied on 2026-09-08.

The desktop captures contain the emulator chrome and black margins.  We first
normalize the Android viewport to the live ADB resolution (1080x1920), then crop
small, stable UI fragments.  These are bootstrap templates; live ADB calibration
is still preferred if the emulator DPI or app layout changes.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


DESKTOP_VIEWPORT = (835, 51, 1666, 1529)
TARGET_SIZE = (1080, 1920)


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"cannot encode {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(path)


def desktop_viewport(image: np.ndarray) -> np.ndarray:
    left, top, right, bottom = DESKTOP_VIEWPORT
    if image.shape[1] < right or image.shape[0] < bottom:
        raise ValueError("desktop capture is smaller than the expected viewport")
    return cv2.resize(image[top:bottom, left:right], TARGET_SIZE, interpolation=cv2.INTER_CUBIC)


def crop(image: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, width, height = box
    return image[y : y + height, x : x + width]


def build(source: Path, output: Path, debug: Path | None = None) -> None:
    names = {
        "home": "屏幕截图 2026-09-08 183930.png",
        "free_listen": "屏幕截图 2026-09-08 183935.png",
        "ad_interaction": "屏幕截图 2026-09-08 183951.png",
        "ad_close": "屏幕截图 2026-09-08 184017.png",
    }
    screens = {state: desktop_viewport(read_image(source / name)) for state, name in names.items()}

    # Coordinates are in normalized live-ADB pixels after viewport extraction.
    boxes = {
        "home": (300, 92, 170, 115),
        "free_listen": (550, 92, 210, 115),
        "ready": (345, 1122, 390, 120),
        "ad_interaction": (42, 118, 515, 105),
        "ad_close": (470, 1415, 140, 140),
    }
    sources = {
        "home": screens["home"],
        "free_listen": screens["free_listen"],
        "ready": screens["free_listen"],
        "ad_interaction": screens["ad_interaction"],
        "ad_close": screens["ad_close"],
    }
    for state, box in boxes.items():
        write_image(output / f"{state}_reference.png", crop(sources[state], box))

    # A second ad-state template avoids depending on a particular countdown
    # number or sentence.  The top-right circular close glyph is more stable.
    write_image(
        output / "ad_interaction_close_reference.png",
        crop(screens["ad_interaction"], (930, 112, 120, 120)),
    )

    # The following two references were already cropped by the user.  Scale them
    # to approximate their size in the 1080px-wide live viewport.
    download = read_image(source / "屏幕截图 2026-09-08 184008.png")
    prompt = crop(download, (70, 650, 700, 210))
    prompt = cv2.resize(prompt, None, fx=1080 / download.shape[1], fy=1080 / download.shape[1], interpolation=cv2.INTER_CUBIC)
    write_image(output / "download_prompt_reference.png", prompt)

    header = read_image(source / "屏幕截图 2026-09-08 184012.png")
    header = cv2.resize(header, None, fx=1080 / 849, fy=1080 / 849, interpolation=cv2.INTER_CUBIC)
    write_image(output / "landing_reference.png", header)

    if debug is not None:
        for state, screen in screens.items():
            write_image(debug / f"viewport_{state}.png", screen)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--debug", type=Path)
    args = parser.parse_args()
    build(args.source, args.output, args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
