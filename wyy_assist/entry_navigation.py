from __future__ import annotations

import time
from dataclasses import replace

from .actions import Action, ActionKind
from .adb import AdbClient
from .executor import ActionExecutor
from .model import Match, Settings
from .navigation import AD_ENTRY_STATES, NAVIGATION_STATES
from .recovery import RecoveryFailed
from .result import AutomationResult
from .tracker import StableStateTracker
from .vision import StateRecognizer


class EntryActionPlanner:
    """Reusable entry actions; start.py supplies their execution order."""

    def __init__(self, settings: Settings, steps: tuple[str, ...]) -> None:
        self.settings = settings
        self.steps = steps

    def plan(self, match: Match, screen_size: tuple[int, int]) -> list[Action]:
        if match.state not in self.steps:
            return []
        descriptions = {
            "my_tab": "点击最下方‘我的’",
            "menu_button": "点击‘我的’页面右上角菜单",
            "free_listen_vip": "点击免费听VIP歌曲",
        }
        if match.state in descriptions:
            return [Action(ActionKind.TAP, descriptions[match.state], point=match.center)]
        return self._plan_logic_2(match, screen_size)

    def _plan_logic_2(self, match: Match, screen_size: tuple[int, int]) -> list[Action]:
        """Legacy recommendation/channel route, used only when explicitly selected."""
        width, height = screen_size
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
        return []


def find_entry_match(recognizer: StateRecognizer, screen, steps: tuple[str, ...]) -> Match | None:
    # Terminal pages can be resumed without replaying completed navigation.
    match = recognizer.best_match(screen, allowed_states={"limit", "ready"})
    if match is not None:
        return match
    # Do not let a simultaneous menu match bypass the bottom My tab.
    for state in steps:
        match = recognizer.best_match(screen, allowed_states={state})
        if match is not None:
            return match
    return None


def run_entry_navigation(
    settings: Settings, adb: AdbClient, *, steps: tuple[str, ...], execute_requested: bool,
) -> AutomationResult:
    """Run ordered entry steps, stopping BEFORE the shared ready-button click.

    A resumed drawer/VIP page skips completed steps. After a tap, only later
    steps (or ready/limit) can advance; the last button may be retried three times.
    No icon fallback, vertical scrolling, or implicit route switch is performed.
    """
    if not steps or len(set(steps)) != len(steps) or set(steps) - NAVIGATION_STATES:
        raise ValueError("入口步骤为空、重复或包含未知动作")
    executor = ActionExecutor(settings, adb, execute_requested=execute_requested)
    executor.verify_live_execution()
    # Inactive routes are not even loaded by the entry module.
    allowed = set(steps) | {"limit", "ready"} | AD_ENTRY_STATES
    recognizer = StateRecognizer(replace(
        settings, templates={k: v for k, v in settings.templates.items() if k in allowed},
    ))
    planner = EntryActionPlanner(settings, steps)
    tracker = StableStateTracker(settings.consecutive_hits)
    deadline = time.monotonic() + settings.startup_navigation_timeout_seconds
    cursor = 0
    last_state: str | None = None
    last_action_at = 0.0
    attempts = 0
    transitions = 0
    print("[导航] 执行顺序：" + " → ".join(steps) + " → ready")
    with adb.command_deadline(deadline):
        while time.monotonic() < deadline:
            screen = adb.screenshot()
            match = find_entry_match(recognizer, screen, steps[cursor:])
            if match is None and last_state is None:
                # Attach to an existing ad only when no entry marker is visible.
                match = recognizer.best_match(screen, allowed_states=AD_ENTRY_STATES)
            if match is None and last_state is not None:
                match = recognizer.best_match(screen, allowed_states={last_state})
            stable = tracker.observe(match.state if match else None)
            now = time.monotonic()
            if stable is not None and match is not None:
                if match.state in {"ready", "limit"} | AD_ENTRY_STATES:
                    print(f"[导航] 已确认 {match.state}，交给共用流程")
                    return AutomationResult(match.state, transitions)
                if match.state != last_state:
                    attempts = 0
                if match.state != last_state or now - last_action_at >= 3.0:
                    if attempts >= 3:
                        raise RecoveryFailed(f"入口导航 {match.state} 点击 3 次后仍未变化，中断本次运行")
                    executor.run_all(planner.plan(match, (screen.shape[1], screen.shape[0])))
                    if match.state != last_state:
                        transitions += 1
                    last_state = match.state
                    cursor = steps.index(match.state) + 1
                    attempts += 1
                    last_action_at = time.monotonic()
                    tracker = StableStateTracker(settings.consecutive_hits)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(settings.poll_interval_seconds, remaining))
    expected = steps[cursor] if cursor < len(steps) else "看视频，点亮拼图"
    raise RecoveryFailed(f"入口导航超时，未找到 {expected}，中断本次运行")
