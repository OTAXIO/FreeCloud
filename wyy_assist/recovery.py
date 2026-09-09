from __future__ import annotations

import time
from dataclasses import replace

from .actions import Action, ActionKind
from .adb import AdbClient, AdbError
from .executor import ActionExecutor, ExecutionBlocked
from .model import Match, Settings
from .tracker import StableStateTracker
from .vision import StateRecognizer


RESUME_STATES = frozenset({
    "home", "free_listen", "free_listen_icon", "free_listen_page", "ready", "limit",
})
RECOVERY_SECONDS = 30.0


class RecoveryFailed(RuntimeError):
    pass


def recovery_recognizer(settings: Settings) -> StateRecognizer:
    # Reuse the actual close/cancel/back glyphs, but search beyond their usual
    # locations when an unexpected overlay moves them. Do not lower thresholds.
    templates = {
        state: [replace(spec, search_roi=None,
                        threshold=max(spec.threshold or settings.threshold, 0.88))
                for spec in settings.templates.get(state, [])]
        for state in ("download_prompt", "ad_close", "landing")
    }
    return StateRecognizer(replace(
        settings, templates=templates,
        state_priority=["download_prompt", "ad_close", "landing"],
    ))


def recover_page(
    settings: Settings,
    adb: AdbClient,
    recognizer: StateRecognizer,
    executor: ActionExecutor,
    *,
    cause: str,
    blocked_state: str | None = None,
) -> Match:
    """Return only after a stable normal page, with one fixed recovery deadline.

    Callers must finish any mandatory viewing/interaction wait before entering
    this routine. A stalled page is not proof of recovery until it changes.
    """
    deadline = time.monotonic() + RECOVERY_SECONDS
    print(f"[恢复] {cause}；尝试取消、叉或返回，最多 {RECOVERY_SECONDS:.0f} 秒")
    exits = recovery_recognizer(settings)
    stable = StableStateTracker(settings.consecutive_hits)
    next_action = time.monotonic()
    last_error = cause
    allowed_resume = RESUME_STATES.difference({blocked_state})
    with adb.command_deadline(deadline):
        while time.monotonic() < deadline:
            try:
                screen = adb.screenshot()
                foreground = adb.foreground_window()
                in_target = settings.package.strip() in foreground
                # An overlay is not a successful return to its visible background.
                exit_match = exits.best_match(screen) if in_target else None
                match = recognizer.best_match(screen, allowed_states=allowed_resume) if in_target else None
                if time.monotonic() >= deadline:
                    break
                if match is not None and (match.state == "limit" or exit_match is None):
                    transition = stable.observe(match.state)
                    if transition is not None:
                        print(f"[恢复] 已回到流程页面：{match.state}")
                        return match
                    # Await confirmation, never send Back on a candidate normal page.
                else:
                    stable.observe(None)
                    if time.monotonic() >= next_action:
                        if exit_match is not None and exit_match.state != "landing":
                            action = Action(ActionKind.TAP, "恢复：点击识别到的取消/叉", point=exit_match.center)
                        else:
                            action = Action(ActionKind.BACK, "恢复：返回上一页")
                        # Foreign landing pages may require Back to reach the app.
                        # Never tap arbitrary content outside the target package.
                        executor.run(action, require_target_foreground=action.kind is ActionKind.TAP)
                        next_action = time.monotonic() + 3.0
            except (AdbError, ExecutionBlocked) as exc:
                stable.observe(None)
                last_error = str(exc)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(settings.poll_interval_seconds, remaining))
    raise RecoveryFailed(f"本次运行失败：30 秒内未回到正常流程（{last_error}）")
