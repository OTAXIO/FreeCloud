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

    def ad_interaction_tap(self, screen_size: tuple[int, int]) -> Action:
        return Action(
            ActionKind.TAP,
            "前置计时结束，点击广告测试互动区域",
            point=_absolute_point(self.settings.ad_interaction_point, screen_size),
        )

    def plan(self, match: Match, screen_size: tuple[int, int]) -> list[Action]:
        width, height = screen_size
        if match.state == "launcher_icon":
            return [Action(ActionKind.TAP, "点击启动器中的测试应用图标", point=match.center)]
        if match.state == "splash_skip":
            return [Action(ActionKind.TAP, "跳过测试应用开屏页", point=match.center)]
        if match.state == "home":
            x1, y1, x2, y2, duration = self.settings.top_menu_swipe
            actions: list[Action] = []
            for attempt in range(3):
                actions.append(
                    Action(
                        ActionKind.TAP,
                        f"第 {attempt + 1}/3 次点击顶部推荐菜单，排除初次进入干扰",
                        point=match.center,
                    )
                )
                if attempt < 2:
                    actions.append(
                        Action(ActionKind.WAIT, "等待推荐页响应", seconds=0.5)
                    )
            actions.append(
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
            )
            return actions
        if match.state == "free_listen":
            return [Action(ActionKind.TAP, "点击免费听频道", point=match.center)]
        if match.state == "free_listen_icon":
            return [Action(ActionKind.TAP, "未找到顶部频道，点击识别到的“免”入口", point=match.center)]
        if match.state == "free_listen_page":
            return [
                Action(
                    ActionKind.SWIPE,
                    "向上滑动免费听页面，使下方拼图入口进入识别区域",
                    swipe=(
                        round(0.5 * width),
                        round(0.82 * height),
                        round(0.5 * width),
                        round(0.28 * height),
                        550,
                    ),
                )
            ]
        if match.state == "ready":
            return [Action(ActionKind.TAP, "点击看视频、点亮拼图入口", point=match.center)]
        if match.state in {"ad", "ad_interaction"}:
            return [
                Action(
                    ActionKind.WAIT,
                    "从进入广告页开始等待完整前置计时",
                    seconds=self.settings.minimum_ad_seconds,
                ),
                self.ad_interaction_tap(screen_size),
                Action(
                    ActionKind.WAIT,
                    "点击后继续停留，完成后才进入退出阶段",
                    seconds=self.settings.ad_post_click_wait_seconds,
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
            return [Action(ActionKind.BACK, "从测试落地页返回")]
        if match.state == "ad_close":
            return [Action(ActionKind.TAP, "关闭测试广告页", point=match.center)]
        if match.state == "limit":
            return [Action(ActionKind.STOP, "识别到今日已达上限，停止状态机")]
        if match.state == "success":
            return [Action(ActionKind.WAIT, "等待奖励页稳定", seconds=1.0)]
        return []
