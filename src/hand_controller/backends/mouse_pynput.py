"""Mouse virtuale multipiattaforma via pynput (Windows, macOS, Linux/X11)."""
from __future__ import annotations

import sys

from .base import MouseBackend


def _enable_windows_dpi_awareness() -> None:
    """Senza questo, con scaling 125%/150% le coordinate del cursore non corrispondono ai pixel."""
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _screen_size() -> tuple[int, int]:
    if sys.platform == "win32":
        import ctypes
        u = ctypes.windll.user32
        return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    import tkinter
    root = tkinter.Tk()
    root.withdraw()
    size = root.winfo_screenwidth(), root.winfo_screenheight()
    root.destroy()
    return size


class PynputMouseBackend(MouseBackend):
    name = "pynput"

    def __init__(self):
        if sys.platform == "win32":
            _enable_windows_dpi_awareness()
        from pynput.mouse import Button, Controller

        self._mouse = Controller()
        self._buttons = {"left": Button.left, "right": Button.right, "middle": Button.middle}
        self._size = _screen_size()

    def screen_size(self) -> tuple[int, int]:
        return self._size

    def move_to(self, x: int, y: int) -> None:
        self._mouse.position = (x, y)

    def position(self) -> tuple[int, int] | None:
        x, y = self._mouse.position
        return int(x), int(y)

    def press(self, button: str) -> None:
        self._mouse.press(self._buttons[button])

    def release(self, button: str) -> None:
        self._mouse.release(self._buttons[button])

    def scroll(self, dy: int) -> None:
        self._mouse.scroll(0, dy)
