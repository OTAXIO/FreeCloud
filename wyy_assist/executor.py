from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from .actions import Action, ActionKind
from .adb import AdbClient
from .model import Settings


class ExecutionBlocked(RuntimeError):
    pass


class ActionExecutor:
    def __init__(
        self,
        settings: Settings,
        adb: AdbClient,
        *,
        execute_requested: bool,
        sleeper: Callable[[float], None] = time.sleep,
        output: Callable[[str], None] = print,
    ) -> None:
        self.settings = settings
        self.adb = adb
        self.execute_requested = execute_requested
        self.sleeper = sleeper
        self.output = output

    @property
    def live(self) -> bool:
        return self.execute_requested and self.settings.execution_enabled

    def verify_input_enabled(self) -> None:
        if not self.execute_requested:
            raise ExecutionBlocked("命令行没有提供 --execute；当前为演练模式")
        if not self.settings.execution_enabled:
            raise ExecutionBlocked("config.json 的 execution_enabled=false；点击功能处于关闭状态")
        package = self.settings.package.strip()
        if not package or package.lower() == "none":
            raise ExecutionBlocked("config.json 的 package 尚未配置；请填写独立测试 APK 的包名")

    def verify_live_execution(self) -> None:
        self.verify_input_enabled()
        package = self.settings.package.strip()
        foreground = self.adb.foreground_window()
        if package not in foreground:
            raise ExecutionBlocked(
                f"前台窗口与配置的测试包不一致；期望 {package}，实际为 {foreground or '未知'}"
            )

    def run(self, action: Action, *, require_target_foreground: bool = True) -> bool:
        prefix = "执行" if self.live else "演练"
        self.output(f"[{prefix}] {action.description}: {self.describe(action)}")
        if not self.live:
            return action.kind is not ActionKind.STOP

        if require_target_foreground:
            self.verify_live_execution()
        else:
            self.verify_input_enabled()
        if action.kind is ActionKind.TAP:
            assert action.point is not None
            self.adb.tap(*action.point)
        elif action.kind is ActionKind.SWIPE:
            assert action.swipe is not None
            self.adb.swipe(*action.swipe)
        elif action.kind is ActionKind.BACK:
            self.adb.back()
        elif action.kind is ActionKind.WAIT:
            self.sleeper(action.seconds)
        elif action.kind is ActionKind.STOP:
            return False
        return True

    def run_all(
        self,
        actions: Iterable[Action],
        *,
        require_target_foreground: bool = True,
    ) -> bool:
        for action in actions:
            if not self.run(action, require_target_foreground=require_target_foreground):
                return False
        return True

    @staticmethod
    def describe(action: Action) -> str:
        if action.kind is ActionKind.TAP:
            return f"tap {action.point}"
        if action.kind is ActionKind.SWIPE:
            return f"swipe {action.swipe}"
        if action.kind is ActionKind.WAIT:
            return f"wait {action.seconds:.1f}s"
        return action.kind.value
