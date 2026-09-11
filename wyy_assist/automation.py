from __future__ import annotations

import time
from collections.abc import Collection
from dataclasses import dataclass, field
from enum import Enum

from .actions import ActionPlanner
from .adb import AdbClient, AdbError
from .executor import ActionExecutor, ExecutionBlocked
from .model import Settings
from .navigation import (LOGIC_1_STATES, NAVIGATION_STATES, STARTUP_STATES,
                         AD_ENTRY_STATES, filter_navigation_states)
from .result import AutomationResult
from .tracker import StableStateTracker
from .timing import jitter_wait_seconds
from .vision import StateRecognizer
from .recovery import RecoveryFailed, RESUME_STATES, recover_page


RETRYABLE_STATES = frozenset(
    {
        "ready",
        "download_prompt",
        "landing",
        "ad_close",
    }
)
UNKNOWN_CENTER_FALLBACK_STATES = frozenset({"ready", "ad_interaction"})


def runtime_recognition_states(settings: Settings) -> set[str]:
    """The shared ad loop only recognizes ready/ad/completion states."""

    return set(settings.templates).difference(STARTUP_STATES | NAVIGATION_STATES)


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
    pre_click_wait_seconds: float = field(init=False, default=0.0)
    post_click_wait_seconds: float = field(init=False, default=0.0)

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

    def _enter(self, now: float) -> None:
        # Sample once per actual entry, never on every screenshot or retry.
        self.pre_click_wait_seconds = jitter_wait_seconds(self.pre_click_seconds)
        self.post_click_wait_seconds = jitter_wait_seconds(self.post_click_seconds)
        self.phase = AdCyclePhase.PRE_CLICK
        self.entered_at = now

    def observe_screen(self, state: str | None, now: float) -> str | None:
        if self.phase is AdCyclePhase.IDLE and state in AD_ENTRY_STATES:
            self._enter(now)
            return "entered"
        if self.phase is not AdCyclePhase.AWAITING_ENTRY:
            return None
        if state is None or state in AD_ENTRY_STATES:
            self._enter(now)
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
            and now >= self.entered_at + self.pre_click_wait_seconds
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
            and now >= self.clicked_at + self.post_click_wait_seconds
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


def preview_once(
    settings: Settings, adb: AdbClient, *, steps: tuple[str, ...] = ("my_tab", "menu_button", "free_listen_vip"),
) -> AutomationResult:
    from .entry_navigation import EntryActionPlanner, find_entry_match

    screen = adb.screenshot()
    recognizer = StateRecognizer(settings)
    match = find_entry_match(recognizer, screen, steps)
    if match is None:
        match = recognizer.best_match(
            screen, allowed_states=filter_navigation_states(settings.templates, steps)
        )
    if match is None:
        return AutomationResult("unknown", 0)
    planner = EntryActionPlanner(settings, steps) if match.state in steps else ActionPlanner(settings)
    executor = ActionExecutor(settings, adb, execute_requested=False)
    executor.run_all(planner.plan(match, (screen.shape[1], screen.shape[0])))
    return AutomationResult(match.state, 1)


def run_live(
    settings: Settings, adb: AdbClient, *, execute_requested: bool,
    navigation_states: Collection[str] = LOGIC_1_STATES,
) -> AutomationResult:
    transitions = 0
    recoveries_without_progress = 0
    while transitions < 100:
        cycle = AdCycleTimer(settings.minimum_ad_seconds, settings.ad_post_click_wait_seconds)
        try:
            result = _run_live_attempt(settings, adb, execute_requested=execute_requested, ad_cycle=cycle)
            transitions += result.transitions
            if result.reason == "limit":
                return AutomationResult("limit", transitions)
            cause = result.reason
            if result.transitions >= 2:
                recoveries_without_progress = 0
        except (AdbError, ExecutionBlocked) as exc:
            cause = str(exc)
            # A transient screenshot/foreground failure cannot authorize an
            # early Back or close while a previously started wait is locked.
            wait_until = None
            if cycle.phase is AdCyclePhase.PRE_CLICK and cycle.entered_at is not None:
                wait_until = cycle.entered_at + cycle.pre_click_wait_seconds
            elif cycle.phase is AdCyclePhase.POST_CLICK and cycle.clicked_at is not None:
                wait_until = cycle.clicked_at + cycle.post_click_wait_seconds
            if wait_until is not None:
                remaining = wait_until - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
        recoveries_without_progress += 1
        if recoveries_without_progress > 3:
            raise RecoveryFailed(f"本次运行失败：连续恢复后仍无法推进流程（{cause}）")
        blocked = cause.removeprefix("stalled-") if cause.startswith("stalled-") else None
        recovered = recover_page(
            settings, adb, StateRecognizer(settings),
            ActionExecutor(settings, adb, execute_requested=execute_requested),
            cause=cause, blocked_state=blocked, navigation_states=navigation_states,
        )
        if recovered.state == "limit":
            return AutomationResult("limit", transitions)
        if recovered.state in navigation_states:
            # start.py owns route ordering, including a recovered entry page.
            return AutomationResult("navigation-required", transitions)
    raise RecoveryFailed("本次运行失败：状态转换次数达到限制，仍未识别到 limit")


def _run_live_attempt(
    settings: Settings, adb: AdbClient, *, execute_requested: bool,
    ad_cycle: AdCycleTimer | None = None,
) -> AutomationResult:
    executor = ActionExecutor(settings, adb, execute_requested=execute_requested)
    executor.verify_live_execution()
    recognizer = StateRecognizer(settings)
    runtime_states = runtime_recognition_states(settings)
    planner = ActionPlanner(settings)
    tracker = StableStateTracker(settings.consecutive_hits)
    transitions = 0
    retry_policy = StateRetryPolicy()
    ad_cycle = ad_cycle or AdCycleTimer(
        pre_click_seconds=settings.minimum_ad_seconds,
        post_click_seconds=settings.ad_post_click_wait_seconds,
    )
    limit_hits = 0

    while transitions < 100:
        screen = adb.screenshot()
        match = recognizer.best_match(screen, allowed_states=runtime_states)
        now = time.monotonic()
        state = match.state if match is not None else None

        limit_hits = limit_hits + 1 if state == "limit" else 0
        if state == "limit":
            if limit_hits >= settings.consecutive_hits:
                return AutomationResult("limit", transitions)
            time.sleep(settings.poll_interval_seconds)
            continue

        timer_event = ad_cycle.observe_screen(state, now)
        if timer_event == "entered":
            print(
                f"[计时] 已进入广告页；锁定退出动作，先等待 "
                f"{ad_cycle.pre_click_wait_seconds:.1f} 秒"
            )
        elif timer_event == "entry-retry":
            print("[计时] 广告页未出现，允许重新点击入口")

        if ad_cycle.phase is AdCyclePhase.PRE_CLICK:
            if ad_cycle.interaction_due(now):
                if state in RESUME_STATES:
                    return AutomationResult("unexpected-page-before-interaction", transitions)
                executor.run(planner.ad_interaction_tap((screen.shape[1], screen.shape[0])))
                ad_cycle.mark_interaction(time.monotonic())
                print(
                    f"[计时] 已完成互动点击；继续锁定退出动作 "
                    f"{ad_cycle.post_click_wait_seconds:.1f} 秒"
                )
            time.sleep(settings.poll_interval_seconds)
            continue

        if ad_cycle.phase is AdCyclePhase.POST_CLICK:
            if not ad_cycle.advance_post_click(now):
                time.sleep(settings.poll_interval_seconds)
                continue
            print("[计时] 点击后停留已完成；现在允许取消下载、返回或关闭广告")
            retry_policy = StateRetryPolicy()
            tracker = StableStateTracker(settings.consecutive_hits)

        if ad_cycle.phase is AdCyclePhase.AWAITING_ENTRY:
            if state not in {"ready", "limit"}:
                return AutomationResult("unexpected-page-after-entry", transitions)
            time.sleep(settings.poll_interval_seconds)
            continue

        if ad_cycle.phase is AdCyclePhase.EXIT:
            if state == "ready":
                ad_cycle.reset()
                retry_policy = StateRetryPolicy()
                tracker = StableStateTracker(settings.consecutive_hits)
            elif state in {"ad", "ad_interaction"}:
                return AutomationResult("ad-exit-not-found", transitions)

        if match is None:
            return AutomationResult("unexpected-page", transitions)

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
