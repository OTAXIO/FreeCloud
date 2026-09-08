from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from .adb import AdbClient, AdbError
from .model import Settings


class EmulatorError(RuntimeError):
    pass


class EmulatorController:
    """Starts one configured LDPlayer instance and waits for an ADB frame."""

    def __init__(
        self,
        settings: Settings,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        popen: Callable[..., Any] = subprocess.Popen,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.settings = settings
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.popen = popen
        self.runner = runner

    @property
    def executable(self) -> Path:
        return Path(self.settings.emulator_path).expanduser()

    def launch_if_needed(self, adb: AdbClient) -> bool:
        executable = self.executable
        if not self.settings.emulator_path.strip():
            raise EmulatorError("config.json 的 emulator_path 尚未配置")
        if not executable.is_file():
            raise EmulatorError(f"雷电模拟器不存在: {executable}")

        devices = adb.devices()
        target_is_connected = (
            self.settings.serial in devices if self.settings.serial else bool(devices)
        )
        if target_is_connected:
            print("[启动] 雷电模拟器已有可用 ADB 设备，直接复用")
            return False

        try:
            self.popen(
                [str(executable)],
                cwd=str(executable.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise EmulatorError(f"无法启动雷电模拟器: {exc}") from exc
        print(f"[启动] 已打开雷电模拟器: {executable}")
        return True

    def wait_for_frame(self, adb: AdbClient) -> tuple[str, np.ndarray]:
        deadline = self.monotonic() + self.settings.emulator_start_timeout_seconds
        last_error = "ADB 设备尚未出现"
        while True:
            try:
                device = adb.ensure_device()
                screen = adb.screenshot()
                print(
                    f"[启动] 已识别模拟器画面: {screen.shape[1]}x{screen.shape[0]}"
                )
                return device, screen
            except AdbError as exc:
                last_error = str(exc)

            now = self.monotonic()
            if now >= deadline:
                raise EmulatorError(
                    "等待雷电模拟器画面超时；请检查 ADB 设置。"
                    f"最后错误: {last_error}"
                )
            self.sleeper(min(1.0, deadline - now))

    def close(self) -> None:
        executable = self.executable
        candidates = [
            executable.with_name("dnconsole.exe"),
            executable.with_name("ldconsole.exe"),
        ]
        console = next((path for path in candidates if path.is_file()), None)
        if console is None:
            raise EmulatorError(
                f"未找到雷电控制台程序: {candidates[0]} 或 {candidates[1]}"
            )
        command = [
            str(console),
            "quit",
            "--index",
            str(self.settings.emulator_index),
        ]
        try:
            result = self.runner(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30.0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EmulatorError(f"关闭雷电模拟器失败: {exc}") from exc
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise EmulatorError(stderr or f"关闭雷电模拟器失败，退出码 {result.returncode}")
        print(f"[结束] 已关闭雷电模拟器实例 {self.settings.emulator_index}")
