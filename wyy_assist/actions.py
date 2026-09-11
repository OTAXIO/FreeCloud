from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model import Match, Settings
from .timing import jitter_wait_seconds


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

    def ad_interaction_tap(self, screen_size: tuple[int, int]) -> Action:
        return Action(
            ActionKind.TAP,
            "前置计时结束，点击广告测试互动区域",
            point=_absolute_point(self.settings.ad_interaction_point, screen_size),
        )

    def plan(self, match: Match, screen_size: tuple[int, int]) -> list[Action]:
        if match.state == "launcher_icon":
            return [Action(ActionKind.TAP, "点击启动器中的测试应用图标", point=match.center)]
        if match.state == "splash_skip":
            return [Action(ActionKind.TAP, "跳过测试应用开屏页", point=match.center)]
        if match.state == "ready":
            return [Action(ActionKind.TAP, "点击看视频、点亮拼图入口", point=match.center)]
        if match.state in {"ad", "ad_interaction"}:
            return [
                Action(
                    ActionKind.WAIT,
                    "从进入广告页开始等待完整前置计时",
                    seconds=jitter_wait_seconds(self.settings.minimum_ad_seconds),
                ),
                self.ad_interaction_tap(screen_size),
                Action(
                    ActionKind.WAIT,
                    "点击后继续停留，完成后才进入退出阶段",
                    seconds=jitter_wait_seconds(self.settings.ad_post_click_wait_seconds),
                ),
            ]
        if match.state == "download_prompt":
            return [
                Action(
                    ActionKind.TAP,
                    "点击识别到的取消按钮",
                    point=match.center,
                )
            ]
        if match.state == "landing":
            return [Action(ActionKind.TAP, "点击左上角返回箭头，退出落地页", point=match.center)]
        if match.state == "ad_close":
            return [Action(ActionKind.TAP, "关闭测试广告页", point=match.center)]
        if match.state == "limit":
            return [Action(ActionKind.STOP, "识别到今日已达上限，停止状态机")]
        if match.state == "success":
            return [Action(ActionKind.WAIT, "等待奖励页稳定", seconds=1.0)]
        return []
