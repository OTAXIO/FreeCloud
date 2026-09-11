from __future__ import annotations

import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

import start
from wyy_assist.actions import ActionKind, ActionPlanner
from wyy_assist.automation import _run_live_attempt, run_live, runtime_recognition_states
from wyy_assist.config import load_settings
from wyy_assist.entry_navigation import EntryActionPlanner, find_entry_match, run_entry_navigation
from wyy_assist.executor import ActionExecutor, ExecutionBlocked
from wyy_assist.model import Match
from wyy_assist.navigation import LOGIC_1_STATES, LOGIC_2_STATES, filter_navigation_states
from wyy_assist.recovery import RecoveryFailed, recover_page
from wyy_assist.result import AutomationResult
from wyy_assist.startup import run_startup_navigation
from wyy_assist.vision import StateRecognizer

ROOT = Path(__file__).resolve().parents[1]


def found(state):
    return Match(state, 1.0, (100, 100), Path(state + ".png"))


def read(name):
    return cv2.imdecode(np.fromfile(ROOT / name, dtype=np.uint8), cv2.IMREAD_COLOR)


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings(ROOT / "config.json")
        self.settings.consecutive_hits = 1
        self.settings.poll_interval_seconds = 0.1
        self.steps = start.navigation_steps()

    def device(self):
        adb = Mock()
        adb.foreground_window.return_value = self.settings.package + "/.Main"
        adb.command_deadline.return_value = nullcontext()
        adb.screenshot.return_value = np.zeros((200, 100, 3), dtype=np.uint8)
        return adb

    def test_start_selects_logic_1_and_only_explicit_switch_uses_logic_2(self):
        self.assertEqual(start.NAVIGATION_LOGIC, 1)
        self.assertEqual(self.steps, ("my_tab", "menu_button", "free_listen_vip"))
        for logic, active, inactive in ((1, LOGIC_1_STATES, LOGIC_2_STATES), (2, LOGIC_2_STATES, LOGIC_1_STATES)):
            with self.subTest(logic=logic), patch("start.NAVIGATION_LOGIC", logic):
                steps = start.navigation_steps()
                states = filter_navigation_states(self.settings.templates, steps)
                self.assertTrue(active <= states)
                self.assertFalse(inactive & states)
                planner = EntryActionPlanner(self.settings, steps)
                for state in inactive:
                    self.assertEqual(planner.plan(found(state), (1080, 1920)), [])
                for state in active:
                    self.assertTrue(planner.plan(found(state), (1080, 1920)))
        ad_states = runtime_recognition_states(self.settings)
        self.assertFalse((LOGIC_1_STATES | LOGIC_2_STATES) & ad_states)
        self.assertTrue({"ready", "landing", "limit", "ad_close"} <= ad_states)
        for state in LOGIC_1_STATES | LOGIC_2_STATES:
            self.assertEqual(ActionPlanner(self.settings).plan(found(state), (1080, 1920)), [])

    def test_bad_selector_stops_without_launching_or_using_legacy(self):
        with patch("start.NAVIGATION_LOGIC", 3), patch("start.run_startup_navigation") as startup:
            with self.assertRaises(ValueError):
                start.run_workflow(self.settings, self.device())
            startup.assert_not_called()

    def test_my_text_ignores_message_badge_and_selected_color(self):
        recognizer = StateRecognizer(self.settings)
        for fixture in ("navigation_home_footer.png", "navigation_my_footer.png"):
            for badge in (False, True):
                screen = np.full((1920, 1080, 3), 245, dtype=np.uint8)
                footer = read("tests/fixtures/" + fixture)
                screen[1680:] = footer
                if badge:
                    cv2.circle(screen, (990, 1740), 14, (0, 0, 255), -1)
                match = find_entry_match(recognizer, screen, self.steps)
                self.assertEqual(match.state, "my_tab")
                self.assertEqual(match.center, (946, 1842))
                screen[1810:1875, 890:1000] = 255
                self.assertIsNone(recognizer.best_match(screen, allowed_states={"my_tab"}))

    def test_my_is_preferred_when_home_menu_is_also_visible(self):
        recognizer = StateRecognizer(self.settings)
        screen = np.full((1920, 1080, 3), 245, dtype=np.uint8)
        header = read("tests/fixtures/navigation_home.png")
        screen[:header.shape[0], :header.shape[1]] = header
        screen[1680:] = read("tests/fixtures/navigation_home_footer.png")
        self.assertIsNotNone(recognizer.best_match(screen, allowed_states={"menu_button"}))
        self.assertEqual(find_entry_match(recognizer, screen, self.steps).state, "my_tab")

    def test_my_white_menu_is_recognized_after_my_step(self):
        screen = np.full((1920, 1080, 3), 245, dtype=np.uint8)
        screen[90:205, 910:1015] = read("tests/fixtures/navigation_my_menu.png")
        screen[1680:] = read("tests/fixtures/navigation_my_footer.png")
        recognizer = StateRecognizer(self.settings)
        self.assertEqual(find_entry_match(recognizer, screen, self.steps).state, "my_tab")
        match = find_entry_match(recognizer, screen, self.steps[1:])
        self.assertEqual(match.state, "menu_button")
        self.assertEqual(match.center, (963, 150))

    def test_vip_text_ignores_remaining_time(self):
        recognizer = StateRecognizer(self.settings)
        row = read("tests/fixtures/navigation_drawer_entry.png")
        for erase_remaining in (False, True):
            screen = np.full((1421, 580, 3), 245, dtype=np.uint8)
            screen[480:600] = row
            if erase_remaining:
                screen[490:590, 388:] = 255
            self.assertEqual(find_entry_match(recognizer, screen, self.steps).state, "free_listen_vip")
            screen[490:590, 135:385] = 255
            self.assertIsNone(recognizer.best_match(screen, allowed_states={"free_listen_vip"}))

    def simulate_entry(self, initial="home", *, stuck=False, no_ready=False, steps=None):
        adb = self.device()
        stage = [initial]
        clicks = []
        now = [0.0]
        self.settings.startup_navigation_timeout_seconds = 12.0
        steps = steps or self.steps
        visible = {"home": {"my_tab", "menu_button"}, "my": {"my_tab", "menu_button"},
                   "drawer": {"free_listen_vip"}, "ready": {"ready"}, "unknown": set(), "limit": {"limit"}}
        def observe(screen, allowed_states):
            self.assertFalse(LOGIC_2_STATES & allowed_states)
            state = next((s for s in allowed_states if s in visible[stage[0]]), None)
            return found(state) if state else None
        def tap(*point):
            clicks.append(stage[0])
            if not stuck:
                stage[0] = {"home": "my", "my": "drawer", "drawer": "unknown" if no_ready else "ready"}[stage[0]]
        adb.tap.side_effect = tap
        recognizer = Mock()
        recognizer.best_match.side_effect = observe
        def sleep(seconds):
            now[0] = round(now[0] + seconds, 10)
        try:
            with patch("wyy_assist.entry_navigation.StateRecognizer", return_value=recognizer), \
                 patch("wyy_assist.entry_navigation.time.monotonic", side_effect=lambda: now[0]), \
                 patch("wyy_assist.entry_navigation.time.sleep", side_effect=sleep):
                result = run_entry_navigation(self.settings, adb, steps=steps, execute_requested=True)
            return result, clicks, adb
        finally:
            adb.swipe.assert_not_called()
            adb.back.assert_not_called()

    def test_ordered_entry_stops_at_ready_without_clicking_it(self):
        result, clicks, adb = self.simulate_entry()
        self.assertEqual(result, AutomationResult("ready", 3))
        self.assertEqual(clicks, ["home", "my", "drawer"])
        self.assertEqual(adb.screenshot.call_count, 4)

    def test_existing_drawer_or_ready_skips_completed_steps(self):
        result, clicks, _ = self.simulate_entry("drawer")
        self.assertEqual(result.reason, "ready")
        self.assertEqual(clicks, ["drawer"])
        result, clicks, _ = self.simulate_entry("ready")
        self.assertEqual(result.reason, "ready")
        self.assertEqual(clicks, [])

    def test_entry_limit_stops_without_any_click(self):
        result, clicks, _ = self.simulate_entry("limit")
        self.assertEqual(result.reason, "limit")
        self.assertEqual(clicks, [])

    def test_stuck_button_aborts_after_three_attempts(self):
        with self.assertRaisesRegex(RecoveryFailed, "点击 3 次"):
            self.simulate_entry("drawer", stuck=True)

    def test_missing_ready_times_out_without_swipe_or_old_route(self):
        with self.assertRaisesRegex(RecoveryFailed, "未找到 看视频，点亮拼图"):
            self.simulate_entry("drawer", no_ready=True)

    def test_disabled_input_cannot_start_navigation(self):
        self.settings.execution_enabled = False
        adb = self.device()
        with self.assertRaises(ExecutionBlocked):
            run_entry_navigation(self.settings, adb, steps=self.steps, execute_requested=True)
        adb.tap.assert_not_called()

    def test_start_orders_modules_and_reuses_selected_route_after_recovery(self):
        calls = Mock()
        with patch("start.run_startup_navigation", return_value=AutomationResult("startup-my_tab", 1)) as startup, \
             patch("start.run_entry_navigation", return_value=AutomationResult("ready", 3)) as entry, \
             patch("start.run_live", side_effect=[AutomationResult("navigation-required", 2), AutomationResult("limit", 4)]) as live:
            for name, function in (("startup", startup), ("entry", entry), ("live", live)):
                calls.attach_mock(function, name)
            result = start.run_workflow(self.settings, self.device())
        self.assertEqual(result, AutomationResult("limit", 13))
        self.assertEqual([call[0] for call in calls.mock_calls], ["startup", "entry", "live", "entry", "live"])
        for call in entry.call_args_list:
            self.assertEqual(call.kwargs["steps"], self.steps)

    def test_start_passes_explicit_logic_2_to_all_modules(self):
        with patch("start.NAVIGATION_LOGIC", 2), \
             patch("start.run_startup_navigation", return_value=AutomationResult("startup-home", 1)) as startup, \
             patch("start.run_entry_navigation", return_value=AutomationResult("ready", 2)) as entry, \
             patch("start.run_live", return_value=AutomationResult("limit", 4)) as live:
            start.run_workflow(self.settings, self.device())
        self.assertEqual(startup.call_args.kwargs["navigation_states"], LOGIC_2_STATES)
        self.assertEqual(entry.call_args.kwargs["steps"], ("home", "free_listen"))
        self.assertEqual(live.call_args.kwargs["navigation_states"], LOGIC_2_STATES)

    def test_failed_navigation_prevents_ad_loop(self):
        with patch("start.run_entry_navigation", side_effect=RecoveryFailed("入口导航超时")), \
             patch("start.run_live") as live:
            with self.assertRaises(RecoveryFailed):
                start.run_workflow(self.settings, self.device(), attach_only=True)
            live.assert_not_called()

    def test_repeated_return_to_entry_is_bounded(self):
        with patch("start.run_entry_navigation", return_value=AutomationResult("ready", 0)) as entry, \
             patch("start.run_live", return_value=AutomationResult("navigation-required", 0)):
            with self.assertRaisesRegex(RecoveryFailed, "反复退回"):
                start.run_workflow(self.settings, self.device(), attach_only=True)
        self.assertEqual(entry.call_count, 4)

    def test_live_returns_entry_to_start_instead_of_clicking_navigation(self):
        adb = self.device()
        with patch("wyy_assist.automation._run_live_attempt", return_value=AutomationResult("unexpected-page", 1)), \
             patch("wyy_assist.automation.recover_page", return_value=found("my_tab")):
            result = run_live(self.settings, adb, execute_requested=True)
        self.assertEqual(result.reason, "navigation-required")
        adb.tap.assert_not_called()

    def test_shared_ad_cycle_still_waits_and_exits_in_order(self):
        adb = self.device()
        stage = ["ready"]
        now = [0.0]
        clicks = []
        def tap(*point):
            clicks.append((stage[0], now[0]))
            stage[0] = {"ready": "ad_interaction", "ad_interaction": "landing", "landing": "ad_close", "ad_close": "limit"}[stage[0]]
        adb.tap.side_effect = tap
        recognizer = Mock()
        def observe(screen, allowed_states):
            self.assertFalse((LOGIC_1_STATES | LOGIC_2_STATES) & allowed_states)
            return found(stage[0])
        recognizer.best_match.side_effect = observe
        def sleep(seconds):
            now[0] = round(now[0] + seconds, 10)
        with patch("wyy_assist.automation.StateRecognizer", return_value=recognizer), \
             patch("wyy_assist.automation.time.monotonic", side_effect=lambda: now[0]), \
             patch("wyy_assist.automation.time.sleep", side_effect=sleep), \
             patch("wyy_assist.timing.random.randint", return_value=0):
            result = _run_live_attempt(self.settings, adb, execute_requested=True)
        self.assertEqual(result.reason, "limit")
        self.assertEqual([state for state, _ in clicks], ["ready", "ad_interaction", "landing", "ad_close"])
        self.assertGreaterEqual(clicks[1][1] - clicks[0][1], 15.0)
        self.assertGreaterEqual(clicks[2][1] - clicks[1][1], 10.0)
        adb.swipe.assert_not_called()

    def test_actual_ready_page_hands_off_without_false_skip_or_navigation_click(self):
        screen = read("tests/fixtures/navigation_vip_page.png")
        adb = self.device()
        adb.screenshot.return_value = screen
        with patch("wyy_assist.startup.time.sleep"):
            result = run_startup_navigation(self.settings, adb, execute_requested=True)
        self.assertEqual(result.reason, "startup-ready")
        self.assertEqual(run_entry_navigation(self.settings, adb, steps=self.steps, execute_requested=True).reason, "ready")
        adb.tap.assert_not_called()
        adb.swipe.assert_not_called()

    def test_recovery_uses_only_selected_navigation_states(self):
        adb = self.device()
        recognizer = Mock()
        def observe(screen, allowed_states):
            self.assertFalse(LOGIC_2_STATES & allowed_states)
            return found("free_listen_vip")
        recognizer.best_match.side_effect = observe
        exits = Mock()
        exits.best_match.return_value = None
        with patch("wyy_assist.recovery.recovery_recognizer", return_value=exits):
            result = recover_page(self.settings, adb, recognizer,
                                  ActionExecutor(self.settings, adb, execute_requested=True), cause="unknown")
        self.assertEqual(result.state, "free_listen_vip")
        adb.tap.assert_not_called()
        adb.back.assert_not_called()

    def test_actual_completed_vip_layout_ends_entry_without_clicking(self):
        screen = np.full((1920, 1080, 3), 245, dtype=np.uint8)
        screen[1140:1230, 330:750] = read("tests/fixtures/navigation_completed_text.png")
        self.settings.consecutive_hits = 2
        adb = self.device()
        adb.screenshot.return_value = screen
        with patch("wyy_assist.entry_navigation.time.sleep"):
            result = run_entry_navigation(self.settings, adb, steps=self.steps, execute_requested=True)
        self.assertEqual(result.reason, "limit")
        self.assertEqual(adb.screenshot.call_count, 2)
        adb.tap.assert_not_called()
        adb.swipe.assert_not_called()
