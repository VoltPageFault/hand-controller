"""Estrazione di feature e gesti dai 21 landmark di una mano."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

WRIST = 0
THUMB_TIP = 4
FINGER_TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
FINGER_PIPS = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}
PALM_POINTS = [0, 5, 9, 13, 17]


@dataclass
class HandFeatures:
    label: str
    palm: np.ndarray            # centro del palmo (x, y) normalizzato [0,1]
    size: float                 # polso -> MCP medio, in unità corrette per l'aspect ratio
    curl: float                 # 0 = mano aperta, 1 = pugno chiuso
    pinches: dict[str, bool] = field(default_factory=dict)
    pressed: set[str] = field(default_factory=set)   # pinch iniziati in questo frame
    released: set[str] = field(default_factory=set)  # pinch terminati in questo frame
    horns: bool = False         # gesto "corna" (indice + mignolo tesi): cambio modalità


def _scaled(lm: np.ndarray, aspect: float) -> np.ndarray:
    """Coordinate 2D con x scalata per l'aspect ratio, così le distanze sono isotrope."""
    return lm[:, :2] * np.array([aspect, 1.0])


class HandAnalyzer:
    """Mantiene lo stato (isteresi dei pinch) di una singola mano tra un frame e l'altro."""

    def __init__(self, cfg: dict):
        self.pinch_on = cfg.get("pinch_on", 0.30)
        self.pinch_off = cfg.get("pinch_off", 0.42)
        self.curl_open = cfg.get("curl_open", 1.75)
        self.curl_closed = cfg.get("curl_closed", 1.10)
        self._pinch_state = {name: False for name in FINGER_TIPS}

    def reset(self) -> None:
        self._pinch_state = {name: False for name in FINGER_TIPS}

    def update(self, label: str, landmarks: np.ndarray, aspect: float) -> HandFeatures:
        p = _scaled(landmarks, aspect)
        size = float(np.linalg.norm(p[9] - p[WRIST])) or 1e-6

        tip_wrist = {n: np.linalg.norm(p[i] - p[WRIST]) / size for n, i in FINGER_TIPS.items()}
        pip_wrist = {n: np.linalg.norm(p[i] - p[WRIST]) / size for n, i in FINGER_PIPS.items()}
        mean_ratio = float(np.mean(list(tip_wrist.values())))
        curl = (self.curl_open - mean_ratio) / (self.curl_open - self.curl_closed)
        curl = float(np.clip(curl, 0.0, 1.0))

        pressed, released = set(), set()
        for name, tip in FINGER_TIPS.items():
            d = np.linalg.norm(p[THUMB_TIP] - p[tip]) / size
            was = self._pinch_state[name]
            now = d < self.pinch_on if not was else d < self.pinch_off
            # Col pugno chiuso il pollice tocca le dita: non deve generare pinch.
            if curl > 0.6:
                now = False
            if now and not was:
                pressed.add(name)
            elif was and not now:
                released.add(name)
            self._pinch_state[name] = now

        extended = {n: tip_wrist[n] > pip_wrist[n] * 1.15 for n in FINGER_TIPS}
        horns = (extended["index"] and extended["pinky"]
                 and not extended["middle"] and not extended["ring"]
                 and not any(self._pinch_state.values()))

        palm = landmarks[PALM_POINTS, :2].mean(axis=0)
        return HandFeatures(label=label, palm=palm, size=size, curl=curl,
                            pinches=dict(self._pinch_state), pressed=pressed,
                            released=released, horns=horns)
