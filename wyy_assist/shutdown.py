from __future__ import annotations

import json
from pathlib import Path

from .daily import state_path
from .model import Settings


def pending_path(settings: Settings) -> Path:
    daily = state_path(settings)
    return daily.with_name(daily.stem + ".shutdown.json")


def _target(settings: Settings) -> dict:
    return {"emulator_path": str(Path(settings.emulator_path).expanduser().resolve()),
            "emulator_index": settings.emulator_index}


def shutdown_pending(settings: Settings) -> bool:
    path = pending_path(settings)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    if saved != _target(settings):
        raise ValueError(f"关闭待重试记录与当前模拟器配置不符，请核对：{path}")
    return True


def mark_shutdown_pending(settings: Settings) -> None:
    path = pending_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(_target(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def clear_shutdown_pending(settings: Settings) -> None:
    pending_path(settings).unlink(missing_ok=True)
