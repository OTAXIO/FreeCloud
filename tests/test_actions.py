from __future__ import annotations

import unittest
from pathlib import Path

from wyy_assist.actions import ActionKind, ActionPlanner
from wyy_assist.automation import AdCyclePhase, AdCycleTimer, StateRetryPolicy, UnknownCenterFallback
from wyy_assist.executor import ActionExecutor, ExecutionBlocked
from wyy_assist.model import Match, Settings


class FakeAdb:
    def __init__(self, foreground: str = "com.example.school.mockads/.MainActivity") -> None:
        self.calls: list[tuple] = []
        self.foreground = foreground

    def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", x, y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> None:
        self.calls.append(("swipe", x1, y1, x2, y2, duration))

    def back(self) -> None:
        self.calls.append(("back",))

    def foreground_window(self) -> str:
        return self.foreground


def match(state: str, center: tuple[int, int] = (540, 960)) -> Match:
    return Match(state, 1.0, center, Path("template.png"))


class ActionTests(unittest.TestCase):
    def test_clicks_are_disabled_by_default(self) -> None:
        settings = Settings(package="com.example.school.mockads")
        executor = ActionExecutor(settings, FakeAdb(), execute_requested=True)
        with self.assertRaises(ExecutionBlocked):
            executor.verify_live_execution()

    def test_unconfigured_package_is_blocked(self) -> None:
        settings = Settings(package="none", execution_enabled=True)
        executor = ActionExecutor(settings, FakeAdb(), execute_requested=True)
        with self.assertRaisesRegex(ExecutionBlocked, "尚未配置"):
            executor.verify_live_execution()

    def test_test_package_executes_planned_tap(self) -> None:
        settings = Settings(package="com.example.school.mockads", execution_enabled=True)
        adb = FakeAdb()
        executor = ActionExecutor(settings, adb, execute_requested=True, sleeper=lambda _: None, output=lambda _: None)
        actions = ActionPlanner(settings).plan(match("ready", (123, 456)), (1080, 1920))
        self.assertTrue(executor.run_all(actions))
        self.assertEqual(adb.calls, [("tap", 123, 456)])

    def test_launcher_and_splash_actions_click_recognized_centers(self) -> None:
        planner = ActionPlanner(Settings())
        launcher = planner.plan(match("launcher_icon", (120, 420)), (1080, 1920))
        splash = planner.plan(match("splash_skip", (1018, 80)), (1080, 1920))
        self.assertEqual(launcher[0].point, (120, 420))
        self.assertEqual(splash[0].point, (1018, 80))

    def test_launcher_bootstrap_can_tap_before_target_is_foreground(self) -> None:
        settings = Settings(package="com.example.school.mockads", execution_enabled=True)
        adb = FakeAdb("com.android.launcher3/.Launcher")
        executor = ActionExecutor(
            settings,
            adb,
            execute_requested=True,
            sleeper=lambda _: None,
            output=lambda _: None,
        )
        action = ActionPlanner(settings).plan(
            match("launcher_icon", (120, 420)),
            (1080, 1920),
        )[0]
        self.assertTrue(executor.run(action, require_target_foreground=False))
        self.assertEqual(adb.calls, [("tap", 120, 420)])

    def test_home_repeats_recommend_tap_before_channel_swipe(self) -> None:
        actions = ActionPlanner(Settings()).plan(match("home", (420, 120)), (1080, 1920))
        self.assertEqual(
            [action.kind for action in actions],
            [
                ActionKind.TAP,
                ActionKind.WAIT,
                ActionKind.TAP,
                ActionKind.WAIT,
                ActionKind.TAP,
                ActionKind.SWIPE,
            ],
        )
        self.assertEqual(
            [action.point for action in actions if action.kind is ActionKind.TAP],
            [(420, 120), (420, 120), (420, 120)],
        )

    def test_free_listen_icon_fallback_clicks_match_center(self) -> None:
        actions = ActionPlanner(Settings()).plan(
            match("free_listen_icon", (160, 760)),
            (1080, 1920),
        )
        self.assertEqual(actions[0].kind, ActionKind.TAP)
        self.assertEqual(actions[0].point, (160, 760))

    def test_free_listen_page_scrolls_toward_lower_puzzle_section(self) -> None:
        actions = ActionPlanner(Settings()).plan(
            match("free_listen_page", (200, 160)),
            (1080, 1920),
        )
        self.assertEqual(actions[0].kind, ActionKind.SWIPE)
        self.assertEqual(actions[0].swipe, (540, 1574, 540, 538, 550))

    def test_foreground_must_match_configured_test_package(self) -> None:
        settings = Settings(package="com.example.school.mockads", execution_enabled=True)
        adb = FakeAdb("com.example.other/.MainActivity")
        executor = ActionExecutor(settings, adb, execute_requested=True)
        with self.assertRaisesRegex(ExecutionBlocked, "不一致"):
            executor.verify_live_execution()

    def test_ad_plan_contains_15s_tap_and_10s_wait(self) -> None:
        settings = Settings(minimum_ad_seconds=15.0, ad_post_click_wait_seconds=10.0)
        actions = ActionPlanner(settings).plan(match("ad_interaction"), (1080, 1920))
        self.assertEqual([action.kind for action in actions], [ActionKind.WAIT, ActionKind.TAP, ActionKind.WAIT])
        self.assertEqual(actions[0].seconds, 15.0)
        self.assertEqual(actions[1].point, (540, 960))
        self.assertEqual(actions[2].seconds, 10.0)

    def test_default_ad_timing_is_15s_then_click_then_10s(self) -> None:
        actions = ActionPlanner(Settings()).plan(match("ad_interaction"), (1080, 1920))
        self.assertEqual(
            [(action.kind, action.seconds) for action in actions],
            [
                (ActionKind.WAIT, 15.0),
                (ActionKind.TAP, 0.0),
                (ActionKind.WAIT, 10.0),
            ],
        )

    def test_ad_cycle_blocks_close_until_both_timers_finish(self) -> None:
        timer = AdCycleTimer(pre_click_seconds=15.0, post_click_seconds=10.0)
        timer.arm(100.0)

        self.assertEqual(timer.observe_screen("ad_close", 101.0), "entered")
        self.assertEqual(timer.phase, AdCyclePhase.PRE_CLICK)
        self.assertFalse(timer.interaction_due(115.9))
        self.assertTrue(timer.interaction_due(116.0))

        timer.mark_interaction(116.0)
        self.assertEqual(timer.phase, AdCyclePhase.POST_CLICK)
        self.assertFalse(timer.advance_post_click(125.9))
        self.assertTrue(timer.advance_post_click(126.0))
        self.assertEqual(timer.phase, AdCyclePhase.EXIT)

    def test_ad_cycle_starts_on_unknown_first_frame_after_ready(self) -> None:
        timer = AdCycleTimer(pre_click_seconds=15.0, post_click_seconds=10.0)
        timer.arm(10.0)
        self.assertEqual(timer.observe_screen(None, 10.7), "entered")
        self.assertEqual(timer.entered_at, 10.7)
        self.assertFalse(timer.interaction_due(25.6))
        self.assertTrue(timer.interaction_due(25.7))

    def test_ad_entry_can_retry_without_starting_timer_while_still_ready(self) -> None:
        timer = AdCycleTimer(pre_click_seconds=15.0, post_click_seconds=10.0)
        timer.arm(20.0)
        self.assertIsNone(timer.observe_screen("ready", 22.9))
        self.assertEqual(timer.observe_screen("ready", 23.0), "entry-retry")
        self.assertEqual(timer.phase, AdCyclePhase.IDLE)

    def test_download_prompt_clicks_recognized_cancel_center(self) -> None:
        settings = Settings(download_cancel_point=(0.1, 0.1))
        actions = ActionPlanner(settings).plan(
            match("download_prompt", (638, 1091)),
            (1080, 1920),
        )
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].kind, ActionKind.TAP)
        self.assertEqual(actions[0].point, (638, 1091))

    def test_landing_uses_android_back_instead_of_title_template_center(self) -> None:
        actions = ActionPlanner(Settings()).plan(match("landing", (70, 70)), (1080, 1920))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].kind, ActionKind.BACK)
        self.assertIsNone(actions[0].point)

    def test_limit_state_stops_without_any_click(self) -> None:
        actions = ActionPlanner(Settings()).plan(match("limit", (540, 960)), (1080, 1920))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].kind, ActionKind.STOP)
        self.assertIsNone(actions[0].point)

    def test_ready_state_retries_three_total_attempts_then_stalls(self) -> None:
        policy = StateRetryPolicy(retry_after_seconds=3.0, max_attempts=3)
        policy.begin("ready")
        policy.record_action(0.0)
        self.assertFalse(policy.retry_due("ready", 2.9))
        self.assertTrue(policy.retry_due("ready", 3.0))
        policy.record_action(3.0)
        self.assertTrue(policy.retry_due("ready", 6.0))
        policy.record_action(6.0)
        self.assertFalse(policy.retry_due("ready", 9.0))
        self.assertTrue(policy.stalled("ready", 9.0))

    def test_ad_interaction_is_not_retried_and_reports_stall(self) -> None:
        policy = StateRetryPolicy(non_retryable_stall_seconds=15.0)
        policy.begin("ad_interaction")
        policy.record_action(10.0)
        self.assertFalse(policy.retry_due("ad_interaction", 100.0))
        self.assertFalse(policy.stalled("ad_interaction", 24.9))
        self.assertTrue(policy.stalled("ad_interaction", 25.0))

    def test_unknown_ad_screen_gets_one_delayed_center_fallback(self) -> None:
        fallback = UnknownCenterFallback(delay_seconds=3.0)
        self.assertFalse(fallback.should_click("ready", 10.0))
        self.assertFalse(fallback.should_click("ready", 12.9))
        self.assertTrue(fallback.should_click("ready", 13.0))
        self.assertFalse(fallback.should_click("ready", 30.0))

    def test_unknown_fallback_does_not_click_after_unrelated_state(self) -> None:
        fallback = UnknownCenterFallback(delay_seconds=3.0)
        self.assertFalse(fallback.should_click("home", 10.0))
        self.assertFalse(fallback.should_click("home", 20.0))
        fallback.reset()
        self.assertFalse(fallback.should_click("ad_interaction", 30.0))
        self.assertTrue(fallback.should_click("ad_interaction", 33.0))


if __name__ == "__main__":
    unittest.main()
