from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import load_settings
from .daily import limit_reached_today
from .shutdown import shutdown_pending


def watch_parent(parent_pid: int) -> None:
    """Stop the click worker if its supervisor disappears (e.g. console closed)."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, parent_pid)  # SYNCHRONIZE
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    def wait() -> None:
        result = kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.CloseHandle(handle)
        # Fail closed if the parent handle can no longer be monitored.
        if result in (0, 0xFFFFFFFF):
            os._exit(130)

    threading.Thread(target=wait, name="supervisor-watch", daemon=True).start()


@contextmanager
def single_instance(config_path: Path):
    """The OS releases this mutex even if the supervisor crashes."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    key = hashlib.sha256(os.path.normcase(str(config_path.resolve())).encode()).hexdigest()
    handle = kernel.CreateMutexW(None, False, "Local\\WyyAssist-" + key)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    already_running = ctypes.get_last_error() == 183
    try:
        yield not already_running
    finally:
        kernel.CloseHandle(handle)


def ask_continue(detail: str) -> bool:
    # The dialog belongs to the supervisor and survives a worker crash.
    import tkinter as tk
    from tkinter import scrolledtext, ttk

    root = tk.Tk()
    root.title("本次运行失败 — 是否继续")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    selected = False

    def finish(value: bool) -> None:
        nonlocal selected
        selected = value
        root.destroy()

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="本次运行中断或未能完成，是否重新启动流程？",
              font=("Microsoft YaHei UI", 11)).pack(anchor="w")
    details = scrolledtext.ScrolledText(frame, height=12, width=76, wrap="word")
    details.insert("1.0", detail[-1500:])
    details.configure(state="disabled")
    details.pack(fill="x", pady=12)
    ttk.Label(frame, text="继续：手动重新运行。放弃：结束本次运行。\n"
                         "放弃不会记录今日 limit；模拟器保持当前状态。").pack(anchor="w")
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(18, 0))
    ttk.Button(buttons, text="继续", command=lambda: finish(True)).pack(side="left", padx=(0, 14))
    ttk.Button(buttons, text="放弃", command=lambda: finish(False)).pack(side="left")
    root.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - root.winfo_width()) // 2)
    y = max(0, (root.winfo_screenheight() - root.winfo_height()) // 2)
    root.geometry(f"+{x}+{y}")
    root.lift()
    root.mainloop()
    return selected


def launch_worker(config_path: Path, log_path: Path) -> int:
    command = [sys.executable, "-u", str(Path(__file__).resolve().parents[1] / "start.py"),
               "--worker", "--no-pause", "--parent-pid", str(os.getpid()), "--config", str(config_path)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   cwd=str(config_path.parent), env=env, creationflags=flags)
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            return 130


def supervise(config_path: Path) -> int:
    with single_instance(config_path) as acquired:
        if not acquired:
            print("[运行] 已有本项目流程正在运行，跳过重复启动。")
            return 0
        settings = load_settings(config_path)
        tracking = (settings.daily_run_enabled and settings.execution_enabled
                    and settings.package.strip().lower() not in {"", "none"})
        if tracking and limit_reached_today(settings) and not shutdown_pending(settings):
            print("[每日] 今日已经达到 limit，跳过运行。")
            return 0
        log_dir = config_path.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        attempt = 0
        while True:
            attempt += 1
            log_path = log_dir / ("run-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                                  + f"-{os.getpid()}-{attempt}.log")
            print(f"[运行] 开始执行，详细日志：{log_path}", flush=True)
            try:
                code = launch_worker(config_path, log_path)
                if code == 0:
                    print("[运行] 已正常完成。")
                    return 0
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
                detail = f"退出码：{code}\n日志：{log_path}\n\n{tail}"
            except (OSError, subprocess.SubprocessError) as exc:
                detail = f"无法完成运行：{exc}\n日志：{log_path}"
            print(f"[运行] 本次运行失败：{detail}", flush=True)
            if ask_continue(detail):
                print("[运行] 已选择继续，重新启动流程。")
                continue
            print("[运行] 已放弃，结束本次运行。")
            return 2
