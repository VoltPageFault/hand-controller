"""Finestra di debug: mani tracciate, modalità corrente e stato del controller."""
from __future__ import annotations

import cv2
import numpy as np

from .backends import PadState
from .gestures import HandFeatures
from .tracker import HAND_CONNECTIONS, Hand

MODE_COLORS = {"mouse": (255, 200, 0), "gamepad": (0, 220, 0), "paused": (0, 0, 255)}


def _text(img, s, org, color=(255, 255, 255), scale=0.55):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def _stick(img, center, x, y, label, r=32):
    cv2.circle(img, center, r, (200, 200, 200), 1, cv2.LINE_AA)
    tip = (int(center[0] + x * r), int(center[1] - y * r))
    cv2.line(img, center, tip, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.circle(img, tip, 5, (0, 255, 255), -1, cv2.LINE_AA)
    _text(img, label, (center[0] - 8, center[1] + r + 16), scale=0.45)


def draw(frame: np.ndarray, hands: list[Hand], feats: dict[str, HandFeatures], mode: str,
         fps: float, pad: PadState | None, mouse_region, switch_progress: float,
         foreground: str | None, mouse_info: str | None = None) -> np.ndarray:
    img = frame.copy()
    h, w = img.shape[:2]

    if mode == "mouse" and mouse_region is not None:
        x0, y0, x1, y1 = mouse_region
        cv2.rectangle(img, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)),
                      MODE_COLORS["mouse"], 1)

    for hand in hands:
        pts = (hand.landmarks[:, :2] * [w, h]).astype(int)
        for a, b in HAND_CONNECTIONS:
            cv2.line(img, tuple(pts[a]), tuple(pts[b]), (255, 255, 255), 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(img, tuple(p), 3, (0, 128, 255), -1, cv2.LINE_AA)
        f = feats.get(hand.label)
        if f is not None:
            c = (int(f.palm[0] * w), int(f.palm[1] * h))
            cv2.circle(img, c, 7, (0, 255, 0), -1)
            active = [k for k, v in f.pinches.items() if v]
            info = f"{hand.label}  curl {f.curl:.2f}" + (f"  pinch {','.join(active)}" if active else "")
            _text(img, info, (pts[0][0] - 60, min(h - 8, pts[0][1] + 24)))

    _text(img, f"MODE: {mode.upper()}", (10, 24), MODE_COLORS.get(mode, (255, 255, 255)), 0.7)
    _text(img, f"{fps:4.1f} fps", (w - 90, 24))
    if mode == "mouse" and mouse_info:
        _text(img, mouse_info, (10, 62), MODE_COLORS["mouse"])
    if mode == "mouse" and mouse_region is not None:
        cx, cy = int((mouse_region[0] + mouse_region[2]) / 2 * w), int((mouse_region[1] + mouse_region[3]) / 2 * h)
        cv2.drawMarker(img, (cx, cy), MODE_COLORS["mouse"], cv2.MARKER_CROSS, 12, 1)
    if foreground:
        _text(img, foreground, (10, h - 10), scale=0.45)
    if switch_progress > 0:
        cv2.rectangle(img, (10, 34), (10 + int(160 * switch_progress), 42), (0, 255, 255), -1)

    if mode == "gamepad" and pad is not None:
        _stick(img, (50, h - 70), pad.lx, pad.ly, "L")
        _stick(img, (w - 50, h - 70), pad.rx, pad.ry, "R")
        for i, (name, v) in enumerate((("LT", pad.lt), ("RT", pad.rt))):
            x = 100 if i == 0 else w - 120
            cv2.rectangle(img, (x, h - 100), (x + 16, h - 40), (200, 200, 200), 1)
            cv2.rectangle(img, (x, h - 40 - int(60 * v)), (x + 16, h - 40), (0, 200, 255), -1)
            _text(img, name, (x - 2, h - 26), scale=0.45)
        if pad.buttons:
            _text(img, " ".join(sorted(pad.buttons)), (w // 2 - 60, h - 20), (0, 255, 0), 0.7)
    return img
