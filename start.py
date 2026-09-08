from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from wyy_assist.adb import AdbClient, AdbError
from wyy_assist.automation import preview_once, run_live, run_startup_navigation
from wyy_assist.config import load_settings
from wyy_assist.emulator import EmulatorController, EmulatorError
from wyy_assist.executor import ExecutionBlocked

# com.netease.cloudmusic
PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_DIR / "config.json"


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
    return parser


def run(config_path: Path) -> int:
    settings = load_settings(config_path)
    adb = AdbClient(settings.adb_path, settings.serial)
    emulator = EmulatorController(settings)

    print(f"配置文件：{config_path}")
    print(f"目标包名：{settings.package}")
    print(f"点击开关：{'开启' if settings.execution_enabled else '关闭'}")
    emulator.launch_if_needed(adb)
    device, _ = emulator.wait_for_frame(adb)
    print(f"ADB 设备：{device}")

    if not package_is_configured(settings.package):
        print("\n目标包名尚未配置，将只识别当前页面并演练下一步动作。")
        print("填写 config.json 的 package 后，双击启动即可进入连续状态机。\n")
        result = preview_once(settings, adb)
    elif not settings.execution_enabled:
        print("\n点击功能当前关闭，将只识别当前页面并演练下一步动作。")
        print("若要测试连续点击，请在 config.json 中启用 execution_enabled。\n")
        result = preview_once(settings, adb)
    else:
        print("\n测试点击已开启，先执行启动识别，再进入连续状态机。按 Ctrl+C 可随时停止。\n")
        run_startup_navigation(settings, adb, execute_requested=True)
        result = run_live(settings, adb, execute_requested=True)

    if result.reason == "limit" and settings.close_emulator_on_limit:
        emulator.close()

    print(f"\n程序结束：{result.reason}；状态转换 {result.transitions} 次")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.chdir(PROJECT_DIR)
    code = 0
    try:
        code = run(choose_config(args.config))
    except KeyboardInterrupt:
        print("\n已由用户停止。")
        code = 130
    except (AdbError, EmulatorError, ExecutionBlocked, FileNotFoundError, ValueError, RuntimeError) as exc:
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
