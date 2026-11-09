"""Controller Xbox 360 virtuale su Linux tramite uinput (python-evdev).

Richiede accesso in scrittura a /dev/uinput (es. utente nel gruppo 'input' + regola udev).
Il dispositivo usa VID/PID del pad Xbox 360, così SDL/Steam/Proton lo riconoscono come tale.
"""
from __future__ import annotations

from .base import GamepadBackend, PadState

AXIS_MAX = 32767


class UInputGamepadBackend(GamepadBackend):
    name = "uinput"

    def __init__(self):
        from evdev import AbsInfo, UInput
        from evdev import ecodes as e

        self._e = e
        self._map = {
            "A": e.BTN_SOUTH, "B": e.BTN_EAST, "X": e.BTN_NORTH, "Y": e.BTN_WEST,
            "LB": e.BTN_TL, "RB": e.BTN_TR, "BACK": e.BTN_SELECT, "START": e.BTN_START,
            "GUIDE": e.BTN_MODE, "LS": e.BTN_THUMBL, "RS": e.BTN_THUMBR,
        }
        stick = AbsInfo(value=0, min=-AXIS_MAX - 1, max=AXIS_MAX, fuzz=16, flat=128, resolution=0)
        trig = AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)
        hat = AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)
        caps = {
            e.EV_KEY: list(self._map.values()),
            e.EV_ABS: [
                (e.ABS_X, stick), (e.ABS_Y, stick), (e.ABS_RX, stick), (e.ABS_RY, stick),
                (e.ABS_Z, trig), (e.ABS_RZ, trig), (e.ABS_HAT0X, hat), (e.ABS_HAT0Y, hat),
            ],
        }
        self._dev = UInput(caps, name="Microsoft X-Box 360 pad", vendor=0x045E,
                           product=0x028E, version=0x110, bustype=e.BUS_USB)

    def send(self, state: PadState) -> None:
        e, w = self._e, self._dev.write
        w(e.EV_ABS, e.ABS_X, int(state.lx * AXIS_MAX))
        w(e.EV_ABS, e.ABS_Y, int(-state.ly * AXIS_MAX))   # evdev: y positivo = giù
        w(e.EV_ABS, e.ABS_RX, int(state.rx * AXIS_MAX))
        w(e.EV_ABS, e.ABS_RY, int(-state.ry * AXIS_MAX))
        w(e.EV_ABS, e.ABS_Z, int(state.lt * 255))
        w(e.EV_ABS, e.ABS_RZ, int(state.rt * 255))
        b = state.buttons
        w(e.EV_ABS, e.ABS_HAT0X, ("DPAD_RIGHT" in b) - ("DPAD_LEFT" in b))
        w(e.EV_ABS, e.ABS_HAT0Y, ("DPAD_DOWN" in b) - ("DPAD_UP" in b))
        for name, code in self._map.items():
            w(e.EV_KEY, code, int(name in b))
        self._dev.syn()

    def close(self) -> None:
        super().close()
        self._dev.close()
