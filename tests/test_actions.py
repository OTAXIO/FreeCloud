from __future__ import annotations

import unittest
from pathlib import Path

from wyy_assist.actions import ActionKind, ActionPlanner
from wyy_assist.automation import StateRetryPolicy, UnknownCenterFallback
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

    def test_foreground_must_match_configured_test_package(self) -> None:
        settings = Settings(package="com.example.school.mockads", execution_enabled=True)
        adb = FakeAdb("com.example.other/.MainActivity")
        executor = ActionExecutor(settings, adb, execute_requested=True)
        with self.assertRaisesRegex(ExecutionBlocked, "不一致"):
            executor.verify_live_execution()

    def test_ad_plan_contains_17s_tap_and_10s_wait(self) -> None:
        settings = Settings(minimum_ad_seconds=17.0, ad_post_click_wait_seconds=10.0)
        actions = ActionPlanner(settings).plan(match("ad_interaction"), (1080, 1920))
        self.assertEqual([action.kind for action in actions], [ActionKind.WAIT, ActionKind.TAP, ActionKind.WAIT])
        self.assertEqual(actions[0].seconds, 17.0)
        self.assertEqual(actions[1].point, (540, 960))
        self.assertEqual(actions[2].seconds, 10.0)

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
