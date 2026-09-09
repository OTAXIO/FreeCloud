from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


VALID_STATES = (
    "launcher_icon",
    "splash_skip",
    "home",
    "free_listen",
    "free_listen_icon",
    "free_listen_page",
    "ready",
    "ad",
    "ad_interaction",
    "download_prompt",
    "landing",
    "ad_close",
    "success",
    "limit",
)


@dataclass(frozen=True)
class TemplateSpec:
    path: str
    search_roi: tuple[float, float, float, float] | None = None
    threshold: float | None = None
    template_roi: tuple[float, float, float, float] | None = None
    scales: tuple[float, ...] | None = None

    @staticmethod
    def _read_roi(value: object, name: str) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ValueError(f"{name} 必须是 [x, y, width, height]")
        roi = tuple(float(item) for item in value)
        if not all(0.0 <= item <= 1.0 for item in roi):
            raise ValueError(f"{name} 必须使用 0..1 的归一化坐标")
        if roi[2] <= 0.0 or roi[3] <= 0.0:
            raise ValueError(f"{name} 的 width 和 height 必须大于 0")
        return roi

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TemplateSpec":
        raw_scales = value.get("scales")
        scales: tuple[float, ...] | None = None
        if raw_scales is not None:
            if not isinstance(raw_scales, (list, tuple)) or not raw_scales:
                raise ValueError("模板 scales 必须是非空数组")
            scales = tuple(float(item) for item in raw_scales)
            if any(item <= 0 for item in scales):
                raise ValueError("模板 scales 必须全部为正数")
        return cls(
            path=str(value["path"]),
            search_roi=cls._read_roi(value.get("search_roi"), "search_roi"),
            threshold=float(value["threshold"]) if value.get("threshold") is not None else None,
            template_roi=cls._read_roi(value.get("template_roi"), "template_roi"),
            scales=scales,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"path": self.path}
        if self.search_roi is not None:
            result["search_roi"] = [round(item, 6) for item in self.search_roi]
        if self.threshold is not None:
            result["threshold"] = self.threshold
        if self.template_roi is not None:
            result["template_roi"] = [round(item, 6) for item in self.template_roi]
        if self.scales is not None:
            result["scales"] = list(self.scales)
        return result


@dataclass
class Settings:
    adb_path: str = r"D:\others\TOOLS\platform-tools\adb.exe"
    serial: str = ""
    emulator_path: str = ""
    emulator_index: int = 0
    emulator_start_timeout_seconds: float = 180.0
    startup_navigation_timeout_seconds: float = 90.0
    close_emulator_on_limit: bool = True
    close_emulator_on_exit: bool = True
    daily_run_enabled: bool = False
    daily_state_file: str = "session.json"
    package: str = "none"
    deep_link: str = ""
    threshold: float = 0.86
    template_scales: list[float] = field(default_factory=lambda: [0.9, 0.95, 1.0, 1.05, 1.1])
    state_priority: list[str] = field(
        default_factory=lambda: [
            "limit",
            "splash_skip",
            "success",
            "download_prompt",
            "ad_close",
            "ad_interaction",
            "ad",
            "ready",
            "free_listen_page",
            "free_listen",
            "landing",
            "home",
            "free_listen_icon",
            "launcher_icon",
        ]
    )
    poll_interval_seconds: float = 0.7
    consecutive_hits: int = 2
    minimum_ad_seconds: float = 15.0
    daily_success_target: int = 2
    expected_ad_entries: int = 10
    unknown_timeout_seconds: float = 30.0
    execution_enabled: bool = False
    ad_post_click_wait_seconds: float = 10.0
    top_menu_swipe: tuple[float, float, float, float, int] = (0.85, 0.08, 0.25, 0.08, 450)
    ad_interaction_point: tuple[float, float] = (0.5, 0.5)
    download_cancel_point: tuple[float, float] = (0.59, 0.57)
    templates: dict[str, list[TemplateSpec]] = field(default_factory=dict)
    config_path: Path = field(default=Path("config.json"), repr=False)

    @classmethod
    def from_dict(cls, value: dict[str, Any], config_path: Path) -> "Settings":
        raw_templates = value.get("templates", {})
        templates: dict[str, list[TemplateSpec]] = {}
        for state, specs in raw_templates.items():
            if state not in VALID_STATES:
                raise ValueError(f"未知模板状态: {state}")
            templates[state] = [TemplateSpec.from_dict(item) for item in specs]

        settings = cls(
            adb_path=str(value.get("adb_path", cls.adb_path)),
            serial=str(value.get("serial", "")),
            emulator_path=str(value.get("emulator_path", "")),
            emulator_index=int(value.get("emulator_index", 0)),
            emulator_start_timeout_seconds=float(value.get("emulator_start_timeout_seconds", 180.0)),
            startup_navigation_timeout_seconds=float(value.get("startup_navigation_timeout_seconds", 90.0)),
            close_emulator_on_limit=bool(value.get("close_emulator_on_limit", True)),
            close_emulator_on_exit=bool(value.get("close_emulator_on_exit", True)),
            daily_run_enabled=bool(value.get("daily_run_enabled", False)),
            daily_state_file=str(value.get("daily_state_file", "session.json")),
            package=str(value.get("package", "none")),
            deep_link=str(value.get("deep_link", "")),
            threshold=float(value.get("threshold", 0.86)),
            template_scales=[float(item) for item in value.get("template_scales", [0.9, 0.95, 1.0, 1.05, 1.1])],
            state_priority=[str(item) for item in value.get("state_priority", cls().state_priority)],
            poll_interval_seconds=float(value.get("poll_interval_seconds", 0.7)),
            consecutive_hits=int(value.get("consecutive_hits", 2)),
            minimum_ad_seconds=float(value.get("minimum_ad_seconds", 15.0)),
            daily_success_target=int(value.get("daily_success_target", 2)),
            expected_ad_entries=int(value.get("expected_ad_entries", 10)),
            unknown_timeout_seconds=float(value.get("unknown_timeout_seconds", 30.0)),
            execution_enabled=bool(value.get("execution_enabled", False)),
            ad_post_click_wait_seconds=float(value.get("ad_post_click_wait_seconds", 10.0)),
            top_menu_swipe=tuple(value.get("top_menu_swipe", [0.85, 0.08, 0.25, 0.08, 450])),
            ad_interaction_point=tuple(value.get("ad_interaction_point", [0.5, 0.5])),
            download_cancel_point=tuple(value.get("download_cancel_point", [0.59, 0.57])),
            templates=templates,
            config_path=config_path,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 0.0 < self.threshold <= 1.0:
            raise ValueError("threshold 必须在 (0, 1] 范围内")
        if not self.template_scales or any(item <= 0 for item in self.template_scales):
            raise ValueError("template_scales 必须包含正数")
        if len(self.state_priority) != len(set(self.state_priority)):
            raise ValueError("state_priority 不能包含重复状态")
        unknown_priorities = set(self.state_priority) - set(VALID_STATES)
        if unknown_priorities:
            raise ValueError(f"state_priority 含未知状态: {sorted(unknown_priorities)}")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds 必须大于 0")
        if self.emulator_index < 0:
            raise ValueError("emulator_index 不能为负数")
        if self.emulator_start_timeout_seconds <= 0:
            raise ValueError("emulator_start_timeout_seconds 必须大于 0")
        if self.startup_navigation_timeout_seconds <= 0:
            raise ValueError("startup_navigation_timeout_seconds 必须大于 0")
        if not self.daily_state_file.strip():
            raise ValueError("daily_state_file 不能为空")
        if self.consecutive_hits < 1:
            raise ValueError("consecutive_hits 必须至少为 1")
        if self.minimum_ad_seconds < 0:
            raise ValueError("minimum_ad_seconds 不能为负数")
        if not 1 <= self.daily_success_target <= 20:
            raise ValueError("daily_success_target 必须在 1..20 范围内")
        if not 1 <= self.expected_ad_entries <= 100:
            raise ValueError("expected_ad_entries 必须在 1..100 范围内")
        if self.unknown_timeout_seconds <= 0:
            raise ValueError("unknown_timeout_seconds 必须大于 0")
        if self.ad_post_click_wait_seconds < 0:
            raise ValueError("ad_post_click_wait_seconds 不能为负数")
        if len(self.top_menu_swipe) != 5:
            raise ValueError("top_menu_swipe 必须为 [x1, y1, x2, y2, duration_ms]")
        if len(self.ad_interaction_point) != 2 or len(self.download_cancel_point) != 2:
            raise ValueError("点击点必须为 [x, y]")
        normalized_values = [
            *self.top_menu_swipe[:4],
            *self.ad_interaction_point,
            *self.download_cancel_point,
        ]
        if any(not 0.0 <= float(item) <= 1.0 for item in normalized_values):
            raise ValueError("动作坐标必须使用 0..1 的归一化坐标")
        if int(self.top_menu_swipe[4]) <= 0:
            raise ValueError("滑动时间必须大于 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "adb_path": self.adb_path,
            "serial": self.serial,
            "emulator_path": self.emulator_path,
            "emulator_index": self.emulator_index,
            "emulator_start_timeout_seconds": self.emulator_start_timeout_seconds,
            "startup_navigation_timeout_seconds": self.startup_navigation_timeout_seconds,
            "close_emulator_on_limit": self.close_emulator_on_limit,
            "close_emulator_on_exit": self.close_emulator_on_exit,
            "daily_run_enabled": self.daily_run_enabled,
            "daily_state_file": self.daily_state_file,
            "package": self.package,
            "deep_link": self.deep_link,
            "threshold": self.threshold,
            "template_scales": self.template_scales,
            "state_priority": self.state_priority,
            "poll_interval_seconds": self.poll_interval_seconds,
            "consecutive_hits": self.consecutive_hits,
            "minimum_ad_seconds": self.minimum_ad_seconds,
            "daily_success_target": self.daily_success_target,
            "expected_ad_entries": self.expected_ad_entries,
            "unknown_timeout_seconds": self.unknown_timeout_seconds,
            "execution_enabled": self.execution_enabled,
            "ad_post_click_wait_seconds": self.ad_post_click_wait_seconds,
            "top_menu_swipe": list(self.top_menu_swipe),
            "ad_interaction_point": list(self.ad_interaction_point),
            "download_cancel_point": list(self.download_cancel_point),
            "templates": {
                state: [spec.to_dict() for spec in specs]
                for state, specs in sorted(self.templates.items())
            },
        }


@dataclass(frozen=True)
class Match:
    state: str
    score: float
    center: tuple[int, int]
    template_path: Path
