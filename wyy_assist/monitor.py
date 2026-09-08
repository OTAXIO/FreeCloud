from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from .adb import AdbClient
from .model import Settings
from .tracker import StableStateTracker, Transition
from .vision import StateRecognizer


STATE_MESSAGES = {
    "home": "识别到首页推荐频道；顶部频道需要继续向右浏览。",
    "free_listen": "识别到“免费听”频道标签。",
    "ready": "奖励页面已就绪；请在模拟器中手动发起一次观看。",
    "ad": "检测到广告页面；请正常观看并手动完成/关闭。",
    "ad_interaction": "检测到广告互动页；先等待 17 秒，再由你确认提示后人工点击并继续等待 10 秒。",
    "download_prompt": "检测到下载确认框；如不希望下载，请人工选择取消。",
    "landing": "检测到广告落地页；请人工返回广告页面。",
    "ad_close": "检测到广告底部关闭按钮；请人工确认后退出。",
    "success": "检测到本次奖励成功。",
    "limit": "检测到当天额度已用完。",
}


@dataclass(frozen=True)
class MonitorResult:
    reason: str
    success_count: int
    ad_count: int


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _announce_transition(transition: Transition) -> None:
    print(
        f"[{_timestamp()}] {STATE_MESSAGES[transition.current]} "
        f"(广告 {transition.ad_count} 次，最终奖励 {transition.success_count} 次)"
    )


def run_monitor(settings: Settings, adb: AdbClient) -> MonitorResult:
    recognizer = StateRecognizer(settings)
    if not recognizer.templates:
        raise ValueError("尚未校准任何模板，请先运行 calibrate")

    tracker = StableStateTracker(settings.consecutive_hits)
    last_known_at = time.monotonic()
    ad_started_at: float | None = None
    ad_timer_announced = False

    print("开始监控；按 Ctrl+C 停止。工具不会点击广告界面。")
    while True:
        match = recognizer.best_match(adb.screenshot())
        now = time.monotonic()
        state = match.state if match else None
        transition = tracker.observe(state)

        if match:
            last_known_at = now
        elif now - last_known_at >= settings.unknown_timeout_seconds:
            return MonitorResult("unknown-timeout", tracker.success_count, tracker.ad_count)

        if transition and transition.changed:
            _announce_transition(transition)
            if transition.current in {"ad", "ad_interaction"}:
                ad_started_at = now
                ad_timer_announced = False
            elif transition.current == "limit":
                return MonitorResult("limit", tracker.success_count, tracker.ad_count)
            elif transition.current == "success" and transition.success_count >= settings.daily_success_target:
                return MonitorResult("target", tracker.success_count, tracker.ad_count)

            if transition.ad_count == settings.expected_ad_entries:
                print(
                    f"[{_timestamp()}] 已进入广告 {transition.ad_count} 次，达到配置中的预期次数；"
                    "继续等待最终奖励或额度完成页面。"
                )

        if ad_started_at is not None and not ad_timer_announced:
            elapsed = now - ad_started_at
            if elapsed >= settings.minimum_ad_seconds:
                print(f"[{_timestamp()}] 已进入广告态 {elapsed:.1f} 秒；请本人确认页面提示后人工操作。")
                ad_timer_announced = True

        time.sleep(settings.poll_interval_seconds)
