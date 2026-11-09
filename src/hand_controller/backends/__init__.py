"""Selezione automatica del backend in base alla piattaforma."""
from __future__ import annotations

import sys

from .base import BUTTONS, TRIGGERS, GamepadBackend, MouseBackend, PadState
from .null import NullGamepadBackend, NullMouseBackend

__all__ = ["BUTTONS", "TRIGGERS", "GamepadBackend", "MouseBackend", "PadState",
           "create_gamepad", "create_mouse"]


def create_gamepad(kind: str = "auto") -> GamepadBackend:
    if kind == "auto":
        kind = {"win32": "vgamepad", "linux": "uinput"}.get(sys.platform, "null")
    try:
        if kind == "vgamepad":
            from .gamepad_vgamepad import VGamepadBackend
            return VGamepadBackend()
        if kind == "uinput":
            from .gamepad_uinput import UInputGamepadBackend
            return UInputGamepadBackend()
    except Exception as exc:  # driver mancante, permessi, ecc.
        print(f"[backend] Gamepad '{kind}' non disponibile ({exc}); uso backend nullo.")
    return NullGamepadBackend()


def create_mouse(kind: str = "auto") -> MouseBackend:
    if kind in ("auto", "pynput"):
        try:
            from .mouse_pynput import PynputMouseBackend
            return PynputMouseBackend()
        except Exception as exc:
            print(f"[backend] Mouse pynput non disponibile ({exc}); uso backend nullo.")
    return NullMouseBackend()
