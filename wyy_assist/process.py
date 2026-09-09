from __future__ import annotations

import ctypes
import os
from pathlib import Path


def is_emulator_binary(path: Path, installation: Path) -> bool:
    name = path.name.lower()
    if path.is_relative_to(installation.resolve()):
        return name in {"dnplayer.exe", "ld9boxheadless.exe", "ldvboxheadless.exe"}
    # LDPlayer installs its VM engine separately in Program Files even when
    # dnplayer.exe is on another drive. Still accept only these exact binaries
    # and only PIDs supplied by the configured instance's console record.
    for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(key)
        if not root:
            continue
        for folder, binary in (("ldplayer9box", "Ld9BoxHeadless.exe"),
                               ("ldplayerbox", "LdVBoxHeadless.exe")):
            if path == (Path(root) / folder / binary).resolve():
                return True
    return False


class OwnedProcess:
    """Hold one process identity across shutdown; never kill by name or reused PID."""

    def __init__(self, pid: int, installation: Path) -> None:
        self.pid = pid
        self.handle = None
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        self.kernel.OpenProcess.restype = ctypes.c_void_p
        self.kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                         ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        self.kernel.QueryFullProcessImageNameW.restype = ctypes.c_bool
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.kernel.WaitForSingleObject.restype = ctypes.c_ulong
        self.kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self.kernel.TerminateProcess.restype = ctypes.c_bool
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        # SYNCHRONIZE | QUERY_LIMITED_INFORMATION | TERMINATE
        handle = self.kernel.OpenProcess(0x00101001, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # Process already gone.
                return
            raise ctypes.WinError(error)
        self.handle = handle
        try:
            name = ctypes.create_unicode_buffer(32768)
            length = ctypes.c_ulong(len(name))
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)):
                raise ctypes.WinError(ctypes.get_last_error())
            path = Path(name.value).resolve()
            if not is_emulator_binary(path, installation):
                raise OSError(f"拒绝关闭不属于配置雷电实例的进程 {pid}: {path}")
        except BaseException:
            self.close()
            raise

    def alive(self) -> bool:
        if self.handle is None:
            return False
        result = self.kernel.WaitForSingleObject(self.handle, 0)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 258

    def terminate(self) -> None:
        if self.alive() and not self.kernel.TerminateProcess(self.handle, 1):
            # It may have exited between the check and TerminateProcess.
            if self.alive():
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
