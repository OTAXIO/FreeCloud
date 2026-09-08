from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from .actions import Action, ActionKind, ActionPlanner
from .adb import AdbClient
from .executor import ActionExecutor
from .model import Settings
from .tracker import StableStateTracker
from .vision import StateRecognizer


@dataclass(frozen=True)
class AutomationResult:
    reason: str
    transitions: int


RETRYABLE_STATES = frozenset(
    {
        "home",
        "free_listen",
        "free_listen_icon",
        "free_listen_page",
        "ready",
        "download_prompt",
        "landing",
        "ad_close",
    }
)
UNKNOWN_CENTER_FALLBACK_STATES = frozenset({"ready", "ad_interaction"})
AD_ENTRY_STATES = frozenset({"ad", "ad_interaction", "ad_close", "download_prompt", "landing"})
STARTUP_STATES = frozenset({"launcher_icon", "splash_skip"})


def runtime_recognition_states(settings: Settings) -> set[str]:
    """Main automation must never reuse launcher-only recognition states."""

    return set(settings.templates).difference(STARTUP_STATES)


class AdCyclePhase(str, Enum):
    IDLE = "idle"
    AWAITING_ENTRY = "awaiting-entry"
    PRE_CLICK = "pre-click"
    POST_CLICK = "post-click"
    EXIT = "exit"


@dataclass
class AdCycleTimer:
    """Owns ad timing so visual states cannot bypass either waiting period."""

    pre_click_seconds: float
    post_click_seconds: float
    entry_retry_seconds: float = 3.0
    phase: AdCyclePhase = AdCyclePhase.IDLE
    armed_at: float | None = None
    entered_at: float | None = None
    clicked_at: float | None = None

    def arm(self, now: float) -> None:
        self.phase = AdCyclePhase.AWAITING_ENTRY
        self.armed_at = now
        self.entered_at = None
        self.clicked_at = None

    def reset(self) -> None:
        self.phase = AdCyclePhase.IDLE
        self.armed_at = None
        self.entered_at = None
        self.clicked_at = None

    def observe_screen(self, state: str | None, now: float) -> str | None:
        if self.phase is AdCyclePhase.IDLE and state in AD_ENTRY_STATES:
            self.phase = AdCyclePhase.PRE_CLICK
            self.entered_at = now
            return "entered"
        if self.phase is not AdCyclePhase.AWAITING_ENTRY:
            return None
        if state is None or state in AD_ENTRY_STATES:
            self.phase = AdCyclePhase.PRE_CLICK
            self.entered_at = now
            return "entered"
        if (
            state == "ready"
            and self.armed_at is not None
            and now - self.armed_at >= self.entry_retry_seconds
        ):
            self.reset()
            return "entry-retry"
        return None

    def interaction_due(self, now: float) -> bool:
        return (
            self.phase is AdCyclePhase.PRE_CLICK
            and self.entered_at is not None
            and now - self.entered_at >= self.pre_click_seconds
        )

    def mark_interaction(self, now: float) -> None:
        if self.phase is not AdCyclePhase.PRE_CLICK:
            raise RuntimeError("广告互动点击只能发生在前置计时结束后")
        self.phase = AdCyclePhase.POST_CLICK
        self.clicked_at = now

    def advance_post_click(self, now: float) -> bool:
        if (
            self.phase is AdCyclePhase.POST_CLICK
            and self.clicked_at is not None
            and now - self.clicked_at >= self.post_click_seconds
        ):
            self.phase = AdCyclePhase.EXIT
            return True
        return False


@dataclass
class UnknownCenterFallback:
    """Allows one center tap after an actionable state becomes unrecognized."""

    delay_seconds: float = 3.0
    unknown_since: float | None = None
    clicked: bool = False

    def reset(self) -> None:
        self.unknown_since = None
        self.clicked = False

    def should_click(self, previous_state: str | None, now: float) -> bool:
        if previous_state not in UNKNOWN_CENTER_FALLBACK_STATES or self.clicked:
            return False
        if self.unknown_since is None:
            self.unknown_since = now
            return False
        if now - self.unknown_since < self.delay_seconds:
            return False
        self.clicked = True
        return True


@dataclass
class StateRetryPolicy:
    """Tracks attempts for a stable state without changing user configuration."""

    retry_after_seconds: float = 3.0
    max_attempts: int = 3
    non_retryable_stall_seconds: float = 15.0
    state: str | None = None
    attempts: int = 0
    last_action_at: float | None = None

    def begin(self, state: str) -> None:
        self.state = state
        self.attempts = 0
        self.last_action_at = None

    def record_action(self, completed_at: float) -> None:
        self.attempts += 1
        self.last_action_at = completed_at

    def retry_due(self, state: str, now: float) -> bool:
        return (
            state == self.state
            and state in RETRYABLE_STATES
            and self.last_action_at is not None
            and self.attempts < self.max_attempts
            and now - self.last_action_at >= self.retry_after_seconds
        )

    def stalled(self, state: str, now: float) -> bool:
        if state != self.state or self.last_action_at is None:
            return False
        elapsed = now - self.last_action_at
        if state in RETRYABLE_STATES:
            return self.attempts >= self.max_attempts and elapsed >= self.retry_after_seconds
        return elapsed >= self.non_retryable_stall_seconds


def preview_once(settings: Settings, adb: AdbClient) -> AutomationResult:
    screen = adb.screenshot()
    match = StateRecognizer(settings).best_match(screen)
    if match is None:
        return AutomationResult("unknown", 0)
    planner = ActionPlanner(settings)
    executor = ActionExecutor(settings, adb, execute_requested=False)
    executor.run_all(planner.plan(match, (screen.shape[1], screen.shape[0])))
    return AutomationResult(match.state, 1)


def run_startup_navigation(
    settings: Settings,
    adb: AdbClient,
    *,
    execute_requested: bool,
) -> AutomationResult:
    """Open the test app from the launcher and dismiss an optional splash page."""

    executor = ActionExecutor(settings, adb, execute_requested=execute_requested)
    executor.verify_input_enabled()
    recognizer = StateRecognizer(settings)
    planner = ActionPlanner(settings)
    tracker = StableStateTracker(settings.consecutive_hits)
    deadline = time.monotonic() + settings.startup_navigation_timeout_seconds
    transitions = 0
    action_state: str | None = None
    action_count = 0
    last_action_at: float | None = None

    while time.monotonic() < deadline:
        screen = adb.screenshot()
        match = recognizer.best_match(screen)
        transition = tracker.observe(match.state if match is not None else None)
        if match is None or transition is None:
            time.sleep(settings.poll_interval_seconds)
            continue

        if transition.changed:
            transitions += 1
            action_state = match.state
            action_count = 0
            last_action_at = None

        if match.state not in STARTUP_STATES:
            print(f"[启动] 已进入原状态机页面: {match.state}")
            return AutomationResult(f"startup-{match.state}", transitions)

        now = time.monotonic()
        retry_due = last_action_at is None or now - last_action_at >= 3.0
        if retry_due and action_count < 3:
            actions = planner.plan(match, (screen.shape[1], screen.shape[0]))
            executor.run_all(actions, require_target_foreground=False)
            action_state = match.state
            action_count += 1
            last_action_at = time.monotonic()
        elif action_state == match.state and action_count >= 3 and retry_due:
            raise RuntimeError(f"启动页面 {match.state} 连续点击 3 次后仍未变化")

        time.sleep(settings.poll_interval_seconds)

    raise RuntimeError(
        f"启动导航超过 {settings.startup_navigation_timeout_seconds:.1f} 秒，"
        "未识别到应用图标、跳过按钮或原状态机页面"
    )


def run_live(settings: Settings, adb: AdbClient, *, execute_requested: bool) -> AutomationResult:
    executor = ActionExecutor(settings, adb, execute_requested=execute_requested)
    executor.verify_live_execution()
    recognizer = StateRecognizer(settings)
    runtime_states = runtime_recognition_states(settings)
    planner = ActionPlanner(settings)
    tracker = StableStateTracker(settings.consecutive_hits)
    last_known_at = time.monotonic()
    transitions = 0
    retry_policy = StateRetryPolicy()
    unknown_fallback = UnknownCenterFallback()
    ad_cycle = AdCycleTimer(
        pre_click_seconds=settings.minimum_ad_seconds,
        post_click_seconds=settings.ad_post_click_wait_seconds,
    )
    limit_hits = 0

    while transitions < 100:
        screen = adb.screenshot()
        match = recognizer.best_match(screen, allowed_states=runtime_states)
        if (
            match is not None
            and match.state == "home"
            and retry_policy.state == "home"
            and retry_policy.attempts >= 1
        ):
            fallback = recognizer.best_match(
                screen,
                allowed_states={"free_listen_icon"},
            )
            if fallback is not None:
                print("[导航] 顶部频道滑动后仍停留在推荐页，改用右上角“免”入口")
                match = fallback
        now = time.monotonic()
        state = match.state if match is not None else None

        limit_hits = limit_hits + 1 if state == "limit" else 0
        if limit_hits >= settings.consecutive_hits:
            return AutomationResult("limit", transitions)

        timer_event = ad_cycle.observe_screen(state, now)
        if timer_event == "entered":
            print(
                f"[计时] 已进入广告页；锁定退出动作，先等待 "
                f"{settings.minimum_ad_seconds:.1f} 秒"
            )
        elif timer_event == "entry-retry":
            print("[计时] 广告页未出现，允许重新点击入口")

        if ad_cycle.phase is AdCyclePhase.PRE_CLICK:
            if ad_cycle.interaction_due(now):
                executor.run(planner.ad_interaction_tap((screen.shape[1], screen.shape[0])))
                ad_cycle.mark_interaction(time.monotonic())
                print(
                    f"[计时] 已完成互动点击；继续锁定退出动作 "
                    f"{settings.ad_post_click_wait_seconds:.1f} 秒"
                )
            time.sleep(settings.poll_interval_seconds)
            continue

        if ad_cycle.phase is AdCyclePhase.POST_CLICK:
            if not ad_cycle.advance_post_click(now):
                time.sleep(settings.poll_interval_seconds)
                continue
            print("[计时] 点击后停留已完成；现在允许取消下载、返回或关闭广告")
            retry_policy = StateRetryPolicy()
            unknown_fallback.reset()

        if ad_cycle.phase is AdCyclePhase.AWAITING_ENTRY:
            time.sleep(settings.poll_interval_seconds)
            continue

        if ad_cycle.phase is AdCyclePhase.EXIT:
            if state == "ready":
                ad_cycle.reset()
                retry_policy = StateRetryPolicy()
                unknown_fallback.reset()
            elif state in {"ad", "ad_interaction"}:
                # The close glyph may need another frame to become recognizable.
                # Never restart the 15+10 second sequence within the same cycle.
                time.sleep(settings.poll_interval_seconds)
                continue

        if match is None:
            if unknown_fallback.should_click(tracker.current, now):
                center = (screen.shape[1] // 2, screen.shape[0] // 2)
                executor.run(
                    Action(
                        ActionKind.TAP,
                        "广告测试画面未识别，执行一次屏幕中心回退点击",
                        point=center,
                    )
                )
            if now - last_known_at >= settings.unknown_timeout_seconds:
                return AutomationResult("unknown-timeout", transitions)
            time.sleep(settings.poll_interval_seconds)
            continue

        unknown_fallback.reset()
        last_known_at = now
        transition = tracker.observe(match.state)
        state_changed = transition is not None and transition.changed
        if state_changed:
            retry_policy.begin(match.state)
        elif tracker.current != match.state:
            time.sleep(settings.poll_interval_seconds)
            continue

        should_run = state_changed or retry_policy.retry_due(match.state, now)
        if not should_run:
            if retry_policy.stalled(match.state, now):
                return AutomationResult(f"stalled-{match.state}", transitions)
            time.sleep(settings.poll_interval_seconds)
            continue

        if state_changed:
            transitions += 1
        else:
            print(
                f"[重试] 状态 {match.state} 点击后未发生变化；"
                f"执行第 {retry_policy.attempts + 1}/{retry_policy.max_attempts} 次尝试"
            )
        actions = planner.plan(match, (screen.shape[1], screen.shape[0]))
        if not executor.run_all(actions):
            return AutomationResult("limit", transitions)
        retry_policy.record_action(time.monotonic())
        if match.state == "ready":
            ad_cycle.arm(time.monotonic())
        time.sleep(settings.poll_interval_seconds)

    return AutomationResult("transition-limit", transitions)
