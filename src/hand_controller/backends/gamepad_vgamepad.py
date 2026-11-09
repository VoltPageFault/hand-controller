"""Controller Xbox 360 virtuale su Windows tramite vgamepad (driver ViGEmBus)."""
from __future__ import annotations

from .base import GamepadBackend, PadState


class VGamepadBackend(GamepadBackend):
    name = "vgamepad"

    def __init__(self):
        import vgamepad as vg

        B = vg.XUSB_BUTTON
        self._map = {
            "A": B.XUSB_GAMEPAD_A, "B": B.XUSB_GAMEPAD_B,
            "X": B.XUSB_GAMEPAD_X, "Y": B.XUSB_GAMEPAD_Y,
            "LB": B.XUSB_GAMEPAD_LEFT_SHOULDER, "RB": B.XUSB_GAMEPAD_RIGHT_SHOULDER,
            "BACK": B.XUSB_GAMEPAD_BACK, "START": B.XUSB_GAMEPAD_START,
            "GUIDE": B.XUSB_GAMEPAD_GUIDE,
            "LS": B.XUSB_GAMEPAD_LEFT_THUMB, "RS": B.XUSB_GAMEPAD_RIGHT_THUMB,
            "DPAD_UP": B.XUSB_GAMEPAD_DPAD_UP, "DPAD_DOWN": B.XUSB_GAMEPAD_DPAD_DOWN,
            "DPAD_LEFT": B.XUSB_GAMEPAD_DPAD_LEFT, "DPAD_RIGHT": B.XUSB_GAMEPAD_DPAD_RIGHT,
        }
        self._pad = vg.VX360Gamepad()
        self._pressed: set[str] = set()

    def send(self, state: PadState) -> None:
        p = self._pad
        p.left_joystick_float(x_value_float=state.lx, y_value_float=state.ly)
        p.right_joystick_float(x_value_float=state.rx, y_value_float=state.ry)
        p.left_trigger_float(value_float=state.lt)
        p.right_trigger_float(value_float=state.rt)
        for b in state.buttons - self._pressed:
            p.press_button(button=self._map[b])
        for b in self._pressed - state.buttons:
            p.release_button(button=self._map[b])
        self._pressed = set(state.buttons)
        p.update()
