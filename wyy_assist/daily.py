from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .model import Settings


@dataclass(frozen=True)
class DailyRunState:
    last_limit_date: date | None = None

    @classmethod
    def load(cls, path: Path) -> "DailyRunState":
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return cls()
        except json.JSONDecodeError as exc:
            raise ValueError(f"每日运行状态文件不是合法 JSON: {path}") from exc

        if not isinstance(raw, dict):
            raise ValueError(f"每日运行状态文件必须是 JSON 对象: {path}")
        value = raw.get("last_limit_date")
        if value in (None, ""):
            return cls()
        if not isinstance(value, str):
            raise ValueError("last_limit_date 必须是 YYYY-MM-DD 日期字符串")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"last_limit_date 不是有效的 YYYY-MM-DD 日期: {value}"
            ) from exc
        return cls(parsed)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp")
        payload = {
            "last_limit_date": (
                self.last_limit_date.isoformat()
                if self.last_limit_date is not None
                else None
            )
        }
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)


def state_path(settings: Settings) -> Path:
    path = Path(settings.daily_state_file).expanduser()
    if not path.is_absolute():
        path = settings.config_path.parent / path
    return path.resolve()


def limit_reached_today(settings: Settings, today: date | None = None) -> bool:
    current_date = today or date.today()
    path = state_path(settings)
    state = DailyRunState.load(path)
    print(f"[每日] 检查日期={current_date.isoformat()}，最后完成={state.last_limit_date or '无记录'}，状态文件={path}")
    return state.last_limit_date == current_date


def mark_limit_reached(settings: Settings, today: date | None = None) -> Path:
    current_date = today or date.today()
    path = state_path(settings)
    DailyRunState(last_limit_date=current_date).save(path)
    return path
