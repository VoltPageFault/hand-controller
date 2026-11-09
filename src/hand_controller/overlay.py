"""Finestra di debug: mani tracciate, modalità corrente e stato del controller."""
from __future__ import annotations

import cv2
import numpy as np

from .backends import PadState
from .gestures import HandFeatures
from .tracker import HAND_CONNECTIONS, Hand

MODE_COLORS = {"mouse": (255, 200, 0), "gamepad": (0, 220, 0), "paused": (0, 0, 255)}


FONT = cv2.FONT_HERSHEY_SIMPLEX


class _Painter:
    """Disegna testo e grafica alla risoluzione finale della finestra, così il testo resta nitido.

    La grafica (stick, barre, marker) scala con la larghezza dell'immagine; il testo ha invece una
    dimensione fissa in pixel, leggibile anche in una finestra piccola.
    """

    def __init__(self, img: np.ndarray, font_scale: float = 1.0):
        self.img = img
        self.h, self.w = img.shape[:2]
        self.k = self.w / 640.0            # fattore per la grafica (progettata a 640 px)
        self.fs = font_scale

    def g(self, v: float) -> int:          # dimensione grafica scalata
        return max(1, int(round(v * self.k)))

    def text(self, s, org, color=(255, 255, 255), size=0.5, align="left", bold=False):
        scale = size * self.fs
        th = 2 if bold else 1
        (tw, tht), _ = cv2.getTextSize(s, FONT, scale, th)
        x, y = org
        if align == "right":
            x -= tw
        elif align == "center":
            x -= tw // 2
        x = int(min(max(2, x), self.w - tw - 2))
        y = int(min(max(tht + 2, y), self.h - 3))
        # contorno nero: stesso spessore, spostato (uno spessore maggiore allargherebbe le lettere)
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, 2), (2, 0), (-2, 0), (0, -2)):
            cv2.putText(self.img, s, (x + dx, y + dy), FONT, scale, (0, 0, 0), th, cv2.LINE_AA)
        cv2.putText(self.img, s, (x, y), FONT, scale, color, th, cv2.LINE_AA)
        return tht

    def stick(self, center, x, y, label):
        r = self.g(32)
        cv2.circle(self.img, center, r, (200, 200, 200), 1, cv2.LINE_AA)
        tip = (int(center[0] + x * r), int(center[1] - y * r))
        cv2.line(self.img, center, tip, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(self.img, tip, self.g(5) + 1, (0, 255, 255), -1, cv2.LINE_AA)
        self.text(label, (center[0], center[1] + r + 18), size=0.55, align="center")


def draw(frame: np.ndarray, hands: list[Hand], feats: dict[str, HandFeatures], mode: str,
         fps: float, pad: PadState | None, mouse_region, switch_progress: float,
         foreground: str | None, mouse_info: str | None = None,
         out_width: int | None = None, font_scale: float = 1.0) -> np.ndarray:
    if out_width and out_width != frame.shape[1]:
        out_h = int(round(frame.shape[0] * out_width / frame.shape[1]))
        img = cv2.resize(frame, (out_width, out_h), interpolation=cv2.INTER_AREA)
    else:
        img = frame.copy()
    P = _Painter(img, font_scale)
    h, w, g = P.h, P.w, P.g
    mcolor = MODE_COLORS["mouse"]

    if mode == "mouse" and mouse_region is not None:
        x0, y0, x1, y1 = mouse_region
        cv2.rectangle(img, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), mcolor, 1)
        cx, cy = int((x0 + x1) / 2 * w), int((y0 + y1) / 2 * h)
        cv2.drawMarker(img, (cx, cy), mcolor, cv2.MARKER_CROSS, g(14), 1)

    for hand in hands:
        pts = (hand.landmarks[:, :2] * [w, h]).astype(int)
        for a, b in HAND_CONNECTIONS:
            cv2.line(img, tuple(pts[a]), tuple(pts[b]), (255, 255, 255), 1, cv2.LINE_AA)
        for p in pts:
            cv2.circle(img, tuple(p), g(3), (0, 128, 255), -1, cv2.LINE_AA)
        f = feats.get(hand.label)
        if f is not None:
            cv2.circle(img, (int(f.palm[0] * w), int(f.palm[1] * h)), g(7), (0, 255, 0), -1)
            active = [k for k, v in f.pinches.items() if v]
            if active:
                P.text(",".join(active), (pts[0][0], pts[0][1] + 18), (0, 255, 0),
                       size=0.55, align="center")

    # riga in alto: modalità a sinistra, fps a destra
    th = P.text(mode.upper(), (6, 24), MODE_COLORS.get(mode, (255, 255, 255)), size=0.75, bold=True)
    P.text(f"{fps:.0f} fps", (w - 6, 24), size=0.55, align="right")
    y = 24 + th + 12
    if switch_progress > 0:
        cv2.rectangle(img, (6, y - 6), (6 + int((w // 2) * switch_progress), y), (0, 255, 255), -1)
        y += 10
    if mode == "mouse" and mouse_info:
        P.text(mouse_info, (6, y + 8), mcolor, size=0.6, bold=True)
    if foreground and mode != "gamepad":
        P.text(foreground, (6, h - 6), (220, 220, 220), size=0.5)

    if mode == "gamepad" and pad is not None:
        base = h - g(70) - 18
        P.stick((g(50) + 4, base), pad.lx, pad.ly, "L")
        P.stick((w - g(50) - 4, base), pad.rx, pad.ry, "R")
        for i, (name, v) in enumerate((("LT", pad.lt), ("RT", pad.rt))):
            bw, bh = g(16), g(60)
            x = g(100) + 4 if i == 0 else w - g(100) - 4 - bw
            yb = base + g(30)
            cv2.rectangle(img, (x, yb - bh), (x + bw, yb), (200, 200, 200), 1)
            cv2.rectangle(img, (x, yb - int(bh * v)), (x + bw, yb), (0, 200, 255), -1)
            P.text(name, (x + bw // 2, yb + 18), size=0.5, align="center")
        if pad.buttons:
            P.text(" ".join(sorted(pad.buttons)), (w // 2, h - 8), (0, 255, 0), size=0.75,
                   align="center", bold=True)
    return img


# ---- posizionamento della finestra -------------------------------------------------------
def _work_area() -> tuple[int, int, int, int] | None:
    """Area utile dello schermo principale (esclusa la barra delle applicazioni), solo Windows."""
    import sys
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # coordinate in pixel reali
    except Exception:
        pass
    rect = wintypes.RECT()
    if not ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def create_window(name: str, cfg: dict, frame_shape: tuple[int, ...]) -> None:
    """Crea la finestra dell'overlay, piccola e in un angolo dello schermo (default: basso a destra)."""
    import sys
    h, w = frame_shape[:2]
    width = int(cfg.get("width", 320))
    height = int(round(width * h / w))
    cv2.namedWindow(name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    cv2.resizeWindow(name, width, height)
    if cfg.get("always_on_top", False):
        cv2.setWindowProperty(name, cv2.WND_PROP_TOPMOST, 1)

    corner = cfg.get("position", "bottom-right")
    margin = int(cfg.get("margin", 12))
    area = _work_area()
    if area is None:
        return
    left, top, right, bottom = area

    if sys.platform == "win32":
        # misura la cornice reale (barra del titolo, bordi) e posiziona con precisione
        import ctypes
        from ctypes import wintypes
        cv2.waitKey(1)
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, name)
        if hwnd:
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            ow, oh = r.right - r.left, r.bottom - r.top
            x = right - ow - margin if "right" in corner else left + margin
            y = bottom - oh - margin if "bottom" in corner else top + margin
            SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
            user32.SetWindowPos(hwnd, 0, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            return
    x = right - width - margin if "right" in corner else left + margin
    y = bottom - height - 40 - margin if "bottom" in corner else top + margin
    cv2.moveWindow(name, x, y)


def window_closed(name: str) -> bool:
    """True se l'utente ha chiuso la finestra con la X."""
    try:
        return cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True
