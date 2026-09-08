from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model import Match, Settings


class ActionKind(str, Enum):
    TAP = "tap"
    SWIPE = "swipe"
    BACK = "back"
    WAIT = "wait"
    STOP = "stop"


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    description: str
    point: tuple[int, int] | None = None
    swipe: tuple[int, int, int, int, int] | None = None
    seconds: float = 0.0


def _absolute_point(point: tuple[float, float], screen_size: tuple[int, int]) -> tuple[int, int]:
    width, height = screen_size
    return round(point[0] * width), round(point[1] * height)


class ActionPlanner:
    """Maps recognized UI states to actions without performing any I/O."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def plan(self, match: Match, screen_size: tuple[int, int]) -> list[Action]:
        width, height = screen_size
        if match.state == "home":
            x1, y1, x2, y2, duration = self.settings.top_menu_swipe
            return [
                Action(
                    ActionKind.SWIPE,
                    "向左滑动顶部频道栏，显示右侧的免费听频道",
                    swipe=(
                        round(float(x1) * width),
                        round(float(y1) * height),
                        round(float(x2) * width),
                        round(float(y2) * height),
                        int(duration),
                    ),
                )
            ]
        if match.state == "free_listen":
            return [Action(ActionKind.TAP, "点击免费听频道", point=match.center)]
        if match.state == "ready":
            return [Action(ActionKind.TAP, "点击看视频、点亮拼图入口", point=match.center)]
        if match.state in {"ad", "ad_interaction"}:
            return [
                Action(ActionKind.WAIT, "等待广告测试的前置计时", seconds=self.settings.minimum_ad_seconds),
                Action(
                    ActionKind.TAP,
                    "点击测试广告的互动区域",
                    point=_absolute_point(self.settings.ad_interaction_point, screen_size),
                ),
                Action(ActionKind.WAIT, "等待点击后的测试计时", seconds=self.settings.ad_post_click_wait_seconds),
            ]
        if match.state == "download_prompt":
            return [
                Action(
                    ActionKind.TAP,
                    "取消测试下载弹窗",
                    point=_absolute_point(self.settings.download_cancel_point, screen_size),
                )
            ]
        if match.state == "landing":
            return [Action(ActionKind.BACK, "从测试落地页返回")]
        if match.state == "ad_close":
            return [Action(ActionKind.TAP, "关闭测试广告页", point=match.center)]
        if match.state == "limit":
            return [Action(ActionKind.STOP, "识别到今日已达上限，停止状态机")]
        if match.state == "success":
            return [Action(ActionKind.WAIT, "等待奖励页稳定", seconds=1.0)]
        return []
