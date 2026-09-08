from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from .adb import AdbClient, AdbError
from .calibrate import calibrate_template
from .config import load_settings
from .model import VALID_STATES
from .monitor import run_monitor


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ADB/OpenCV 移动端视觉状态机测试工具")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="检查 Python、OpenCV、ADB 和模拟器连接")

    screenshot = subparsers.add_parser("screenshot", help="保存当前模拟器截图")
    screenshot.add_argument("output", help="PNG 输出路径")

    calibrate = subparsers.add_parser("calibrate", help="框选并保存一个状态模板")
    calibrate.add_argument("state", choices=VALID_STATES)

    monitor = subparsers.add_parser("monitor", help="持续识别页面状态")
    monitor.add_argument("--open-link", action="store_true", help="监控前打开 config.json 中的 deep_link")

    recognize = subparsers.add_parser("recognize", help="对当前 ADB 截图做一次识别")
    recognize.add_argument("--image", help="改为识别本地图片")

    automate = subparsers.add_parser("automate", help="演练动作；配置测试包后可显式开启执行")
    automate.add_argument("--execute", action="store_true", help="请求执行动作；仍需配置开关开启且前台包名匹配")
    return parser


def _write_png(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("截图 PNG 编码失败")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(path)


def _doctor(adb: AdbClient) -> int:
    print(f"Python: {sys.version.split()[0]}")
    print(f"OpenCV: {cv2.__version__}")
    print(f"ADB: {adb.adb_path}")
    devices = adb.devices()
    print(f"ADB 设备: {', '.join(devices) if devices else '无'}")
    if not devices:
        print("检查未通过：请先启动模拟器并启用 ADB。", file=sys.stderr)
        return 2
    selected = adb.ensure_device()
    screen = adb.screenshot()
    print(f"选中设备: {selected}")
    print(f"截图分辨率: {screen.shape[1]}x{screen.shape[0]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        adb = AdbClient(settings.adb_path, settings.serial)
        if args.command == "doctor":
            return _doctor(adb)

        if args.command == "recognize" and args.image:
            from .vision import StateRecognizer

            path = Path(args.image).expanduser().resolve()
            image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"无法读取图片: {path}")
            match = StateRecognizer(settings).best_match(image)
            if match is None:
                print("未识别到已配置状态。")
                return 1
            print(
                f"状态={match.state} 分数={match.score:.4f} "
                f"中心={match.center} 模板={match.template_path}"
            )
            return 0

        adb.ensure_device()
        if args.command == "automate":
            from .automation import preview_once, run_live

            result = (
                run_live(settings, adb, execute_requested=True)
                if args.execute
                else preview_once(settings, adb)
            )
            print(f"动作状态机结束: {result.reason}; 状态转换 {result.transitions} 次")
            return 0
        if args.command == "screenshot":
            output = Path(args.output).expanduser().resolve()
            _write_png(output, adb.screenshot())
            print(f"已保存截图: {output}")
            return 0
        if args.command == "calibrate":
            output = calibrate_template(settings, adb.screenshot(), args.state)
            if output is None:
                print("已取消校准。")
            else:
                print(f"已保存 {args.state} 模板: {output}")
            return 0
        if args.command == "monitor":
            if args.open_link:
                adb.open_deep_link(settings.deep_link, settings.package)
            result = run_monitor(settings, adb)
            print(
                f"监控结束: {result.reason}; 广告 {result.ad_count} 次，"
                f"最终奖励 {result.success_count} 次"
            )
            return 0
        if args.command == "recognize":
            from .vision import StateRecognizer

            match = StateRecognizer(settings).best_match(adb.screenshot())
            if match is None:
                print("未识别到已配置状态。")
                return 1
            print(
                f"状态={match.state} 分数={match.score:.4f} "
                f"中心={match.center} 模板={match.template_path}"
            )
            return 0
    except KeyboardInterrupt:
        print("\n已由用户停止。")
        return 130
    except (AdbError, FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    return 1
