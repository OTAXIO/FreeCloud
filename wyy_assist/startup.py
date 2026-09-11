from __future__ import annotations

import time
from collections.abc import Collection

from .actions import ActionPlanner
from .adb import AdbClient, AdbError, foreground_package
from .executor import ActionExecutor
from .model import Settings
from .navigation import (LOGIC_1_STATES, STARTUP_STATES,
                         application_recognition_states, filter_navigation_states)
from .recovery import RecoveryFailed
from .result import AutomationResult
from .tracker import StableStateTracker
from .vision import StateRecognizer


def run_startup_navigation(
    settings: Settings,
    adb: AdbClient,
    *,
    execute_requested: bool,
    navigation_states: Collection[str] = LOGIC_1_STATES,
) -> AutomationResult:
    """Open the test app from the launcher and dismiss an optional splash page."""

    executor = ActionExecutor(settings, adb, execute_requested=execute_requested)
    executor.verify_input_enabled()
    for attempt in range(2):
        deadline = time.monotonic() + settings.startup_navigation_timeout_seconds
        try:
            with adb.command_deadline(deadline):
                if attempt:
                    print("[启动] 应用未响应，强制停止后重新启动（仅重试一次）")
                    adb.restart_app(settings.package.strip())
                return _run_startup_navigation_attempt(
                    settings, adb, execute_requested=execute_requested,
                    deadline=deadline, app_restarted=bool(attempt),
                    navigation_states=navigation_states,
                )
        except (AdbError, RecoveryFailed) as exc:
            if attempt:
                raise RecoveryFailed(f"应用重启后再次失败，中断本次运行：{exc}") from exc
            print(f"[启动] 首次尝试失败：{exc}")
    raise AssertionError("unreachable")


def _run_startup_navigation_attempt(
    settings: Settings, adb: AdbClient, *, execute_requested: bool,
    deadline: float, app_restarted: bool, navigation_states: Collection[str],
) -> AutomationResult:
    """One bounded attempt; failures are handled only by the restart budget."""

    executor = ActionExecutor(settings, adb, execute_requested=execute_requested)
    executor.verify_input_enabled()
    recognizer = StateRecognizer(settings)
    planner = ActionPlanner(settings)
    tracker = StableStateTracker(settings.consecutive_hits)
    transitions = 0
    action_state: str | None = None
    action_count = 0
    last_action_at: float | None = None
    unknown_since: float | None = None
    try:
        foreground = adb.foreground_window()
    except AdbError:
        # Recognition can still launch the app when dumpsys is temporarily
        # unavailable during Android startup.
        foreground = ""
    app_launch_requested = app_restarted or bool(
        settings.package.strip()
        and settings.package.strip() == foreground_package(foreground)
    )
    if app_launch_requested:
        print("[启动] 目标应用已在前台，直接接管当前页面")

    while time.monotonic() < deadline:
        screen = adb.screenshot()
        # The home marker is cheap to match and ends startup immediately. Before
        # the app icon is clicked (or is known to be foreground), scan only the
        # launcher icon so launcher search widgets cannot become click targets.
        handoff_states = filter_navigation_states({"limit", "home"}, navigation_states)
        if app_launch_requested:
            # Confirm entry markers before skip: the skip glyph also resembles
            # text on the VIP page. Startup never clicks navigation buttons.
            handoff_states.update(set(navigation_states) | {"ready"})
        match = recognizer.best_match(screen, allowed_states=handoff_states)
        if match is None:
            if app_launch_requested:
                # Restore the old hand-off behavior for scripts started while
                # the app is already on splash, a business page, or an ad page.
                startup_states = application_recognition_states(settings, navigation_states)
                startup_states.add("splash_skip")
            else:
                startup_states = {"launcher_icon"}
            match = recognizer.best_match(screen, allowed_states=startup_states)
        if match is None and app_launch_requested:
            if unknown_since is None:
                unknown_since = time.monotonic()
            if time.monotonic() - unknown_since >= 10.0:
                raise RecoveryFailed("点击应用后 10 秒内未进入可识别页面")
        else:
            unknown_since = None
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
            print(f"[启动] 应用启动完成，当前页面: {match.state}")
            return AutomationResult(f"startup-{match.state}", transitions)

        now = time.monotonic()
        retry_due = last_action_at is None or now - last_action_at >= 3.0
        if retry_due and action_count < 3:
            actions = planner.plan(match, (screen.shape[1], screen.shape[0]))
            executor.run_all(actions, require_target_foreground=False)
            if match.state == "launcher_icon":
                app_launch_requested = True
            action_state = match.state
            action_count += 1
            last_action_at = time.monotonic()
        elif action_state == match.state and action_count >= 3 and retry_due:
            raise RecoveryFailed(f"启动页面 {match.state} 连续点击 3 次后仍未变化")

        time.sleep(settings.poll_interval_seconds)

    raise RecoveryFailed("启动导航超时")
