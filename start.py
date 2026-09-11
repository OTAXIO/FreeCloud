from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from wyy_assist.adb import AdbClient, AdbError
from wyy_assist.automation import preview_once, run_live
from wyy_assist.entry_navigation import run_entry_navigation
from wyy_assist.navigation import AD_ENTRY_STATES
from wyy_assist.recovery import RecoveryFailed
from wyy_assist.result import AutomationResult
from wyy_assist.startup import run_startup_navigation
from wyy_assist.config import load_settings
from wyy_assist.model import Settings
from wyy_assist.daily import limit_reached_today, mark_limit_reached
from wyy_assist.emulator import EmulatorController, EmulatorError
from wyy_assist.executor import ExecutionBlocked
from wyy_assist.supervisor import supervise, watch_parent
from wyy_assist.shutdown import clear_shutdown_pending, mark_shutdown_pending, shutdown_pending

# com.netease.cloudmusic
PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_DIR / "config.json"

# 在这里选择入口逻辑、调整操作顺序；未选择的路线不会执行。
NAVIGATION_LOGIC = 1
ENTRY_ROUTES = {
    1: ("my_tab", "menu_button", "free_listen_vip"),  # 我的 → 右上角菜单 → 免费听VIP
    2: ("home", "free_listen"),                    # 推荐频道 → 免费听频道
}


def navigation_steps() -> tuple[str, ...]:
    if NAVIGATION_LOGIC not in ENTRY_ROUTES:
        raise ValueError("NAVIGATION_LOGIC 只能为 1 或 2")
    return ENTRY_ROUTES[NAVIGATION_LOGIC]


def run_workflow(settings: Settings, adb: AdbClient, *, attach_only: bool = False) -> AutomationResult:
    """顺序：启动 App → 所选入口导航 → 共用广告流程；恢复后按所选路线重入。"""
    steps = navigation_steps()
    states = frozenset(steps)
    # 1. 启动 App，点击没有响应时重启一次，再失败则中断。
    startup = (AutomationResult("attached", 0) if attach_only else
               run_startup_navigation(settings, adb, execute_requested=True, navigation_states=states))
    if startup.reason == "startup-limit":
        return AutomationResult("limit", startup.transitions)
    transitions = startup.transitions
    resume_ad = startup.reason.removeprefix("startup-") in AD_ENTRY_STATES
    for entry_attempt in range(4):
        # 2. 入口导航只负责到达 ready，不点击‘看视频，点亮拼图’。
        if not resume_ad:
            entry = run_entry_navigation(settings, adb, steps=steps, execute_requested=True)
            transitions += entry.transitions
            if entry.reason == "limit":
                return AutomationResult("limit", transitions)
        # 3. ready 点击和之后的等待、互动、退出、上限判断使用共用流程。
        result = run_live(settings, adb, execute_requested=True, navigation_states=states)
        transitions += result.transitions
        if result.reason != "navigation-required":
            return AutomationResult(result.reason, transitions)
        if entry_attempt == 3 or transitions >= 100:
            raise RecoveryFailed("反复退回入口页面，无法推进流程，中断本次运行")
        print("[主流程] 恢复到入口页面，重新执行所选导航路线")
        resume_ad = False
    raise AssertionError("unreachable")


def package_is_configured(package: str) -> bool:
    return bool(package.strip()) and package.strip().lower() != "none"


def choose_config(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = PROJECT_DIR / path
        return path.resolve()
    return DEFAULT_CONFIG


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一键启动移动端图像识别测试")
    parser.add_argument("--config", help="指定配置文件；默认使用 config.json")
    parser.add_argument("--no-pause", action="store_true", help="结束时不等待按 Enter")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    return parser


def run(config_path: Path, *, attach_only: bool = False) -> int:
    settings = load_settings(config_path)
    daily_tracking = (
        settings.daily_run_enabled
        and settings.execution_enabled
        and package_is_configured(settings.package)
    )
    if shutdown_pending(settings):
        print("[结束] 上次流程已完成，但模拟器关闭未确认；先重试关闭，不重新进入应用。")
        EmulatorController(settings).close()
        clear_shutdown_pending(settings)
    if daily_tracking and limit_reached_today(settings):
        print(f"配置文件：{config_path}")
        print("[每日] 今日已经检测到 limit，跳过本次运行；明日可手动运行。")
        return 0

    adb = AdbClient(settings.adb_path, settings.serial)
    emulator = EmulatorController(settings)
    result = None
    emulator_shutdown_armed = False
    live = settings.execution_enabled and package_is_configured(settings.package)

    print(f"配置文件：{config_path}")
    print(f"目标包名：{settings.package}")
    print(f"点击开关：{'开启' if settings.execution_enabled else '关闭'}")
    try:
        if attach_only:
            # The CLI still attaches to an existing device, but shares the same
            # daily guard and host-emulator completion cleanup as start.py.
            device = adb.ensure_device()
            emulator.bind_device(adb)
        else:
            emulator.launch_if_needed(adb)
        # Remember whether launch succeeded; cleanup still requires completion.
        emulator_shutdown_armed = True
        if not attach_only:
            device, _ = emulator.wait_for_frame(adb)
        print(f"ADB 设备：{device}")

        if not package_is_configured(settings.package):
            print("\n目标包名尚未配置，将只识别当前页面并演练下一步动作。")
            print("填写 config.json 的 package 后，双击启动即可进入连续状态机。\n")
            result = preview_once(settings, adb, steps=navigation_steps())
        elif not settings.execution_enabled:
            print("\n点击功能当前关闭，将只识别当前页面并演练下一步动作。")
            print("若要测试连续点击，请在 config.json 中启用 execution_enabled。\n")
            result = preview_once(settings, adb, steps=navigation_steps())
        else:
            print("\n测试点击已开启：启动 App → 入口导航 → 共用广告流程。按 Ctrl+C 可随时停止。\n")
            result = run_workflow(settings, adb, attach_only=attach_only)
            if result.reason == "limit":
                print("[完成] 已确认‘已全部点亮，明天再来’，停止本次点击流程。")
                # Persist cleanup before today's limit, so a failed close (or a
                # terminated worker) cannot be hidden by the daily skip guard.
                if settings.close_emulator_on_limit or settings.close_emulator_on_exit:
                    mark_shutdown_pending(settings)
                if daily_tracking:
                    saved_path = mark_limit_reached(settings)
                    print(f"[每日] 已记录今日 limit：{saved_path}")
    finally:
        close_for_limit = (
            result is not None
            and result.reason == "limit"
            and settings.close_emulator_on_limit
        )
        # A failure remains visible for recovery/the retry dialog. Only a
        # confirmed limit (or a completed preview) permits automatic shutdown.
        completed = result is not None and (not live or result.reason == "limit")
        if emulator_shutdown_armed and completed and (settings.close_emulator_on_exit or close_for_limit):
            try:
                emulator.close()
                clear_shutdown_pending(settings)
            finally:
                emulator.release_handles()
        else:
            emulator.release_handles()

    assert result is not None
    print(f"\n程序结束：{result.reason}；状态转换 {result.transitions} 次")
    return 0 if not live or result.reason == "limit" else 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.chdir(PROJECT_DIR)
    code = 0
    try:
        config_path = choose_config(args.config)
        if args.worker and args.parent_pid:
            watch_parent(args.parent_pid)
        code = run(config_path) if args.worker else supervise(config_path)
    except KeyboardInterrupt:
        print("\n已由用户停止。")
        code = 130
    except (AdbError, EmulatorError, ExecutionBlocked, OSError, ValueError, RuntimeError) as exc:
        print(f"\n启动失败：{exc}", file=sys.stderr)
        code = 2
    finally:
        if not args.no_pause and sys.stdin.isatty():
            try:
                input("\n按 Enter 关闭窗口……")
            except (EOFError, KeyboardInterrupt):
                pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
