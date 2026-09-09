from __future__ import annotations

import subprocess
import re
import time
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np


class AdbError(RuntimeError):
    pass


def foreground_package(output: str) -> str:
    """CurrentFocus wins over a stale FocusedApp left behind by a crash."""
    lines = output.splitlines()
    focused = [line for line in lines if "mCurrentFocus=" in line]
    if not focused:
        focused = [line for line in lines if "mFocusedApp=" in line] or lines
    match = re.search(r"\b([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)/[A-Za-z0-9_.$]+", "\n".join(focused))
    return match.group(1) if match else ""


class AdbClient:
    """Minimal, read-mostly ADB adapter used by the visual monitor."""

    def __init__(self, adb_path: str | Path, serial: str = "") -> None:
        self.adb_path = Path(adb_path).expanduser()
        self.serial = serial.strip()
        self._command_deadline: float | None = None
        self._launcher_package: str | None = None

    @contextmanager
    def command_deadline(self, deadline: float):
        previous = self._command_deadline
        self._command_deadline = min(previous, deadline) if previous is not None else deadline
        try:
            yield
        finally:
            self._command_deadline = previous

    def _base_command(self) -> list[str]:
        command = [str(self.adb_path)]
        if self.serial:
            command.extend(["-s", self.serial])
        return command

    def run(self, *args: str, binary: bool = False, timeout: float = 15.0) -> bytes | str:
        if not self.adb_path.is_file():
            raise AdbError(f"ADB 不存在: {self.adb_path}")
        command = [*self._base_command(), *args]
        if self._command_deadline is not None:
            remaining = self._command_deadline - time.monotonic()
            if remaining <= 0:
                raise AdbError("恢复操作已超过时间限制")
            timeout = min(timeout, remaining)
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"ADB 命令超时: {' '.join(command)}") from exc
        except OSError as exc:
            raise AdbError(f"ADB 命令无法执行: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise AdbError(detail or f"ADB 命令失败，退出码 {result.returncode}")
        if binary:
            return result.stdout
        return result.stdout.decode("utf-8", errors="replace")

    def devices(self) -> list[str]:
        output = str(self.run("devices", "-l"))
        devices: list[str] = []
        for line in output.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 2 and fields[1] == "device":
                devices.append(fields[0])
        return devices

    def ensure_device(self) -> str:
        devices = self.devices()
        if self.serial:
            if self.serial not in devices:
                raise AdbError(f"指定设备未连接: {self.serial}; 当前设备: {devices or '无'}")
            return self.serial
        if not devices:
            raise AdbError("没有找到 ADB 设备；请先启动模拟器并启用 ADB")
        if len(devices) > 1:
            raise AdbError(f"检测到多个设备，请在 config.json 设置 serial: {devices}")
        self.serial = devices[0]
        return self.serial

    def screenshot(self) -> np.ndarray:
        payload = self.run("exec-out", "screencap", "-p", binary=True, timeout=20.0)
        assert isinstance(payload, bytes)
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise AdbError("ADB 截图无法解码")
        return image

    def tap(self, x: int, y: int) -> None:
        if x < 0 or y < 0:
            raise ValueError("tap coordinates must be non-negative")
        self.run("shell", "input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 450) -> None:
        if min(x1, y1, x2, y2) < 0:
            raise ValueError("swipe coordinates must be non-negative")
        if duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        self.run(
            "shell",
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        )

    def back(self) -> None:
        self.run("shell", "input", "keyevent", "BACK")

    def open_deep_link(self, uri: str, package: str = "") -> None:
        if not uri:
            raise AdbError("config.json 中没有设置 deep_link")
        args = ["shell", "am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", uri]
        if package:
            args.extend(["-p", package])
        self.run(*args, timeout=20.0)

    def foreground_window(self) -> str:
        output = str(self.run("shell", "dumpsys", "window", "windows", timeout=15.0))
        focused = [
            line.strip()
            for line in output.splitlines()
            if "mCurrentFocus=" in line or "mFocusedApp=" in line
        ]
        return "\n".join(focused)

    def launcher_package(self) -> str:
        if self._launcher_package is None:
            output = str(self.run("shell", "cmd", "package", "resolve-activity", "--brief",
                                  "-a", "android.intent.action.MAIN",
                                  "-c", "android.intent.category.HOME", timeout=3.0))
            package = foreground_package(output)
            if not package:
                raise AdbError("无法确定 Android 桌面的包名")
            self._launcher_package = package
        return self._launcher_package

    def launch_app(self, package: str) -> None:
        # Resolve only this configured app, never use a generic intent or an
        # arbitrary tap on the launcher (where icons can change position).
        if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", package):
            raise AdbError("无效的目标包名")
        output = str(self.run("shell", "cmd", "package", "resolve-activity", "--brief",
                              "-a", "android.intent.action.MAIN",
                              "-c", "android.intent.category.LAUNCHER", "-p", package,
                              timeout=3.0))
        component = next((line.strip() for line in output.splitlines()
                          if re.fullmatch(re.escape(package) + r"/[A-Za-z0-9_.$]+", line.strip())), None)
        if component is None:
            raise AdbError(f"无法找到应用启动入口：{package}")
        result = str(self.run("shell", "am", "start", "-W", "-n", component, timeout=5.0))
        if "Error:" in result or "Exception" in result:
            raise AdbError(f"应用重新启动失败：{result.strip()}")
