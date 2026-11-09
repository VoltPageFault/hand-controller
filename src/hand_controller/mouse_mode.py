"""Modalità mouse: il palmo muove il cursore, i pinch fanno click/drag/scroll."""
from __future__ import annotations

import numpy as np

from .backends import MouseBackend
from .gestures import HandFeatures

BUTTON_ACTIONS = {"left", "right", "middle"}


class MouseMapper:
    def __init__(self, cfg: dict, mouse: MouseBackend):
        self.mouse = mouse
        self.hand = cfg.get("hand", "right").lower()
        self.region = np.array(cfg.get("active_region", [0.25, 0.2, 0.75, 0.65]), dtype=float)
        self.freeze_s = cfg.get("click_freeze_ms", 150) / 1000.0
        self.scroll_speed = cfg.get("scroll_speed", 40)
        self.bindings: dict[str, str] = cfg.get("bindings", {})
        self._held: set[str] = set()       # pulsanti mouse attualmente premuti
        self._freeze_until = 0.0
        self._scroll_ref: float | None = None
        self._scroll_acc = 0.0
        self.cursor: tuple[int, int] | None = None

    def _pick(self, hands: dict[str, HandFeatures]) -> HandFeatures | None:
        if self.hand == "any":
            return hands.get("Right") or hands.get("Left")
        return hands.get(self.hand.capitalize())

    def to_screen(self, palm: np.ndarray) -> tuple[int, int]:
        x0, y0, x1, y1 = self.region
        u = np.clip((palm[0] - x0) / (x1 - x0), 0.0, 1.0)
        v = np.clip((palm[1] - y0) / (y1 - y0), 0.0, 1.0)
        w, h = self.mouse.screen_size()
        return int(round(u * (w - 1))), int(round(v * (h - 1)))

    def release_all(self) -> None:
        for b in list(self._held):
            self.mouse.release(b)
        self._held.clear()
        self._scroll_ref = None
        self._scroll_acc = 0.0

    def update(self, hands: dict[str, HandFeatures], now: float) -> None:
        f = self._pick(hands)
        if f is None:
            self.release_all()
            self.cursor = None
            return

        if f.pressed:
            self._freeze_until = now + self.freeze_s
        if now >= self._freeze_until or self.cursor is None:
            self.cursor = self.to_screen(f.palm)
            self.mouse.move_to(*self.cursor)

        for finger, action in self.bindings.items():
            if finger in f.pressed:
                if action in BUTTON_ACTIONS and action not in self._held:
                    self.mouse.press(action)
                    self._held.add(action)
                elif action == "scroll":
                    self._scroll_ref = float(f.palm[1])
                    self._scroll_acc = 0.0
            elif finger in f.released:
                if action in self._held:
                    self.mouse.release(action)
                    self._held.discard(action)
                elif action == "scroll":
                    self._scroll_ref = None

        if self._scroll_ref is not None:
            # mano verso l'alto (y diminuisce) = scroll su
            delta = (self._scroll_ref - float(f.palm[1])) * self.scroll_speed
            self._scroll_ref = float(f.palm[1])
            self._scroll_acc += delta
            ticks = int(self._scroll_acc)
            if ticks:
                self.mouse.scroll(ticks)
                self._scroll_acc -= ticks
