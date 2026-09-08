from __future__ import annotations

import time
from dataclasses import dataclass

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
    {"home", "free_listen", "ready", "download_prompt", "landing", "ad_close"}
)
UNKNOWN_CENTER_FALLBACK_STATES = frozenset({"ready", "ad_interaction"})


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


def run_live(settings: Settings, adb: AdbClient, *, execute_requested: bool) -> AutomationResult:
    executor = ActionExecutor(settings, adb, execute_requested=execute_requested)
    executor.verify_live_execution()
    recognizer = StateRecognizer(settings)
    planner = ActionPlanner(settings)
    tracker = StableStateTracker(settings.consecutive_hits)
    last_known_at = time.monotonic()
    transitions = 0
    retry_policy = StateRetryPolicy()
    unknown_fallback = UnknownCenterFallback()

    while transitions < 100:
        screen = adb.screenshot()
        match = recognizer.best_match(screen)
        now = time.monotonic()
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
        time.sleep(settings.poll_interval_seconds)

    return AutomationResult("transition-limit", transitions)
