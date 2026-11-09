"""Nome dell'eseguibile della finestra in primo piano (per l'auto-switch mouse/gamepad)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def _windows() -> str | None:
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(handle)


def _linux() -> str | None:
    if not shutil.which("xdotool"):  # su Wayland non esiste un metodo generico
        return None
    try:
        pid = subprocess.run(["xdotool", "getactivewindow", "getwindowpid"],
                             capture_output=True, text=True, timeout=0.5).stdout.strip()
        with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
            return f.read().strip().lower()
    except Exception:
        return None


def _macos() -> str | None:
    try:
        out = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get name of first '
             'application process whose frontmost is true'],
            capture_output=True, text=True, timeout=0.5).stdout.strip()
        return out.lower() or None
    except Exception:
        return None


def foreground_process() -> str | None:
    try:
        if sys.platform == "win32":
            return _windows()
        if sys.platform == "linux":
            return _linux()
        if sys.platform == "darwin":
            return _macos()
    except Exception:
        return None
    return None
