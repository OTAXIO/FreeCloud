from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .adb import AdbClient, AdbError
from .model import Settings
from .process import OwnedProcess


class EmulatorError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstanceStatus:
    window: int
    render_window: int
    android_started: int
    pid: int
    vm_pid: int

    @property
    def stopped(self) -> bool:
        return not (self.window or self.render_window or self.android_started) and self.pid <= 0 and self.vm_pid <= 0


def parse_instance(output: str, index: int) -> InstanceStatus:
    for line in output.splitlines():
        fields = line.strip().split(",")
        if fields[0] != str(index):
            continue
        try:
            # LDPlayer 9 adds width/height/DPI after the original seven fields.
            return InstanceStatus(*(int(value) for value in fields[2:7]))
        except (ValueError, TypeError) as exc:
            raise EmulatorError(f"雷电实例状态无效: {line}") from exc
    raise EmulatorError(f"雷电实例列表中未找到配置的实例 {index}")


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
        process_factory: Callable[..., Any] = OwnedProcess,
    ) -> None:
        self.settings = settings
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.popen = popen
        self.runner = runner
        self.process_factory = process_factory

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
        try:
            self.popen(
                [str(executable)],
                cwd=str(executable.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise EmulatorError(f"无法启动雷电模拟器: {exc}") from exc
        if target_is_connected:
            # ADB may be kept alive by a background process even when the
            # player window is closed. Launching dnplayer again is harmless
            # for an active instance and makes a hidden/missing window visible.
            print("[启动] ADB 设备已在线，已请求显示雷电模拟器窗口")
        else:
            print(f"[启动] 已打开雷电模拟器: {executable}")
        return not target_is_connected

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
            executable.with_name("ldconsole.exe"),
            executable.with_name("dnconsole.exe"),
        ]
        console = next((path for path in candidates if path.is_file()), None)
        if console is None:
            raise EmulatorError(
                f"未找到雷电控制台程序: {candidates[0]} 或 {candidates[1]}"
            )
        deadline = self.monotonic() + 40.0
        graceful_deadline = deadline - 10.0
        index = str(self.settings.emulator_index)
        processes = {}
        last_error = "实例仍在运行"

        def command(*args: str) -> str:
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise EmulatorError("等待模拟器退出超时")
            try:
                result = self.runner(
                    [str(console), *args], cwd=str(executable.parent),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                    timeout=min(5.0, remaining),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise EmulatorError(f"雷电关闭/状态命令失败: {exc}") from exc
            if result.returncode:
                raise EmulatorError(result.stderr.decode("utf-8", errors="replace").strip()
                                    or f"雷电命令退出码 {result.returncode}")
            return result.stdout.decode("utf-8", errors="replace").strip()

        def status() -> InstanceStatus:
            current = parse_instance(command("list2"), self.settings.emulator_index)
            for pid in (current.pid, current.vm_pid):
                if pid > 0 and pid not in processes:
                    processes[pid] = self.process_factory(pid, executable.parent)
            return current

        def verified_stopped(current: InstanceStatus) -> bool:
            return (current.stopped and not any(process.alive() for process in processes.values())
                    and command("isrunning", "--index", index) == "stop")

        try:
            current = status()  # Capture the exact instance's process handles BEFORE quit.
            next_quit = self.monotonic()
            forced = False
            while self.monotonic() < deadline:
                if verified_stopped(current):
                    print(f"[结束] 已确认雷电模拟器实例 {index} 的窗口及进程退出")
                    return
                now = self.monotonic()
                if now >= next_quit:
                    try:
                        command("quit", "--index", index)
                        print(f"[结束] 已请求关闭雷电实例 {index}，等待退出确认")
                    except EmulatorError as exc:
                        last_error = str(exc)
                    next_quit = self.monotonic() + 8.0
                if self.monotonic() >= graceful_deadline and not forced:
                    forced = True
                    for process in processes.values():
                        if process.alive():
                            print(f"[结束] 常规退出超时，关闭已核验的本实例残留进程 PID {process.pid}")
                            process.terminate()
                self.sleeper(max(0, min(1.0, deadline - self.monotonic())))
                current = status()
            raise EmulatorError(f"未能确认雷电实例 {index} 已关闭：{last_error}")
        except OSError as exc:
            raise EmulatorError(f"无法安全关闭/核验雷电实例 {index}: {exc}") from exc
        finally:
            for process in processes.values():
                process.close()
