"""Modalità gamepad: ogni mano è un joystick virtuale + pulsanti tramite pinch/pugno."""
from __future__ import annotations

import math

import numpy as np

from .backends import BUTTONS, TRIGGERS, PadState
from .gestures import HandFeatures


def apply_deadzone(x: float, y: float, deadzone: float) -> tuple[float, float]:
    """Deadzone radiale con riscalatura: niente salto di valore al bordo della zona morta."""
    mag = math.hypot(x, y)
    if mag < deadzone:
        return 0.0, 0.0
    scale = min(1.0, (mag - deadzone) / (1.0 - deadzone)) / mag
    return x * scale, y * scale


class GamepadMapper:
    def __init__(self, cfg: dict, aspect: float):
        self.aspect = aspect
        self.radius = cfg["stick"].get("radius", 0.8)
        self.deadzone = cfg["stick"].get("deadzone", 0.12)
        self.trigger_threshold = cfg.get("trigger_threshold", 0.05)
        self.hands_cfg = {"Left": cfg["left_hand"], "Right": cfg["right_hand"]}
        for hc in self.hands_cfg.values():
            names = list((hc.get("pinch") or {}).values()) + [hc.get("fist")]
            bad = [n for n in names if n and n not in BUTTONS and n not in TRIGGERS]
            if bad:
                raise ValueError(f"Pulsanti sconosciuti nella configurazione: {bad}")
        self._anchors: dict[str, np.ndarray] = {}

    def reset(self) -> None:
        self._anchors.clear()

    def stick_vector(self, f: HandFeatures) -> tuple[float, float]:
        anchor = self._anchors.setdefault(f.label, f.palm.copy())
        d = (f.palm - anchor) * np.array([self.aspect, 1.0]) / (f.size * self.radius)
        x, y = float(d[0]), float(-d[1])   # immagine: y verso il basso; stick: y verso l'alto
        mag = math.hypot(x, y)
        if mag > 1.0:
            x, y = x / mag, y / mag
        return apply_deadzone(x, y, self.deadzone)

    def update(self, hands: dict[str, HandFeatures]) -> PadState:
        state = PadState()
        for label in list(self._anchors):
            if label not in hands:   # mano uscita: al rientro lo stick si ricentra
                del self._anchors[label]

        for label, f in hands.items():
            hc = self.hands_cfg[label]
            x, y = self.stick_vector(f)
            if hc.get("stick") == "left":
                state.lx, state.ly = x, y
            elif hc.get("stick") == "right":
                state.rx, state.ry = x, y

            for finger, button in (hc.get("pinch") or {}).items():
                if button and f.pinches.get(finger):
                    self._apply(state, button, 1.0)

            fist = hc.get("fist")
            if fist:
                t = self.trigger_threshold
                value = max(0.0, (f.curl - t) / (1.0 - t)) if t < 1 else 0.0
                self._apply(state, fist, value)
        return state

    @staticmethod
    def _apply(state: PadState, name: str, value: float) -> None:
        if name == "LT":
            state.lt = max(state.lt, value)
        elif name == "RT":
            state.rt = max(state.rt, value)
        elif value >= 0.5:
            state.buttons.add(name)
