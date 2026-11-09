"""Modalità mouse: il palmo muove il cursore, i pinch fanno click/drag/scroll.

Due modi di movimento:
- ``anchor`` (default): chiudendo il pugno il cursore va al centro dello schermo e la posizione
  della mano diventa il centro del movimento. Intorno c'è un rettangolo grande quanto la mano
  (``span`` dimensioni-mano di larghezza, proporzioni dello schermo) che corrisponde all'intero
  monitor: bastano piccoli movimenti del polso, col gomito appoggiato.
- ``absolute``: il rettangolo fisso ``active_region`` del fotogramma corrisponde allo schermo.
"""
from __future__ import annotations

import numpy as np

from .backends import MouseBackend
from .filters import OneEuroFilter
from .gestures import HandFeatures

BUTTON_ACTIONS = {"left", "right", "middle"}


class MouseMapper:
    def __init__(self, cfg: dict, mouse: MouseBackend):
        self.mouse = mouse
        self.hand = cfg.get("hand", "right").lower()
        self.motion = cfg.get("motion", "absolute").lower()
        self.region = np.array(cfg.get("active_region", [0.25, 0.2, 0.75, 0.65]), dtype=float)
        anc = cfg.get("anchor", {})
        self.span = float(anc.get("span", 1.0))
        self.recenter_curl = anc.get("recenter_curl", 0.65)
        sm = anc.get("smoothing", {})
        self._smooth = OneEuroFilter(sm.get("min_cutoff", 0.8), sm.get("beta", 4.0),
                                     sm.get("d_cutoff", 1.0))
        self.freeze_s = cfg.get("click_freeze_ms", 150) / 1000.0
        self.scroll_speed = cfg.get("scroll_speed", 40)
        self.bindings: dict[str, str] = cfg.get("bindings", {})
        self._held: set[str] = set()       # pulsanti mouse attualmente premuti
        self._freeze_until = 0.0
        self._scroll_ref: float | None = None
        self._scroll_acc = 0.0
        self.cursor: tuple[int, int] | None = None
        # stato modalità anchor
        self._anchor: np.ndarray | None = None   # centro del movimento (coordinate fotogramma)
        self._half: np.ndarray | None = None     # semi-larghezza/altezza del rettangolo
        self._aspect = 1.0
        self.recentering = False

    # ---- utilità per overlay e regolazioni ------------------------------------------------
    def current_region(self) -> np.ndarray | None:
        """Rettangolo del fotogramma (x0, y0, x1, y1) che corrisponde allo schermo."""
        if self.motion == "absolute":
            return self.region
        if self._anchor is None or self._half is None:
            return None
        return np.concatenate([self._anchor - self._half, self._anchor + self._half])

    def adjust_span(self, factor: float) -> float:
        """Cambia la grandezza del rettangolo mantenendo il centro (+ / - nell'overlay)."""
        self.span = float(np.clip(self.span * factor, 0.3, 4.0))
        if self._half is not None:
            self._half = self._half * factor
        return self.span

    def _pick(self, hands: dict[str, HandFeatures]) -> HandFeatures | None:
        if self.hand == "any":
            return hands.get("Right") or hands.get("Left")
        return hands.get(self.hand.capitalize())

    def _region_to_screen(self, palm: np.ndarray, x0, y0, x1, y1) -> np.ndarray:
        u = np.clip((palm[0] - x0) / (x1 - x0), 0.0, 1.0)
        v = np.clip((palm[1] - y0) / (y1 - y0), 0.0, 1.0)
        return np.array([u, v])

    def to_screen(self, palm: np.ndarray) -> tuple[int, int]:
        uv = self._region_to_screen(palm, *self.region)
        return self._uv_to_px(uv)

    def _uv_to_px(self, uv: np.ndarray) -> tuple[int, int]:
        w, h = self.mouse.screen_size()
        return int(round(uv[0] * (w - 1))), int(round(uv[1] * (h - 1)))

    def _move(self, xy: tuple[int, int]) -> None:
        if xy != self.cursor:
            self.cursor = xy
            self.mouse.move_to(*xy)

    def release_all(self) -> None:
        for b in list(self._held):
            self.mouse.release(b)
        self._held.clear()
        self._scroll_ref = None
        self._scroll_acc = 0.0

    # ---- modalità anchor ------------------------------------------------------------------
    def _half_size(self, f: HandFeatures) -> np.ndarray:
        w, h = self.mouse.screen_size()
        width = self.span * f.size                    # unità isotrope (x scalata per l'aspect)
        return np.array([width / self._aspect, width * h / w]) / 2.0

    def _anchor_move(self, f: HandFeatures, now: float, frozen: bool) -> None:
        palm = np.asarray(f.palm[:2], dtype=float)

        if self.recentering:
            # pugno: cursore al centro, la mano definisce il nuovo centro (segue finché è chiusa)
            self._anchor, self._half = palm.copy(), self._half_size(f)
            self._smooth.reset()
            self._smooth(np.array([0.5, 0.5]), now)
            self._move(self._uv_to_px(np.array([0.5, 0.5])))
            return

        if self._anchor is None or self._half is None:
            # prima volta (o mano rientrata): rettangolo posizionato in modo che il cursore
            # resti dov'è, senza salti
            self._half = self._half_size(f)
            cur = self.mouse.position()
            w, h = self.mouse.screen_size()
            uv = np.array([0.5, 0.5]) if cur is None else np.array(
                [cur[0] / max(w - 1, 1), cur[1] / max(h - 1, 1)])
            self._anchor = palm - (uv - 0.5) * 2 * self._half
            self._smooth.reset()
            self._smooth(uv, now)
            return

        lo, hi = self._anchor - self._half, self._anchor + self._half
        uv = self._smooth(self._region_to_screen(palm, lo[0], lo[1], hi[0], hi[1]), now)
        if not frozen:
            self._move(self._uv_to_px(uv))

    # ---- aggiornamento per frame ----------------------------------------------------------
    def update(self, hands: dict[str, HandFeatures], now: float, aspect: float = 1.0) -> None:
        self._aspect = aspect
        f = self._pick(hands)
        if f is None:
            self.release_all()
            self.cursor = None
            self._anchor = None           # al rientro il rettangolo si riposiziona sul cursore
            self.recentering = False
            return

        if f.pressed:
            self._freeze_until = now + self.freeze_s
        frozen = now < self._freeze_until or self._scroll_ref is not None

        if self.motion == "anchor":
            was = self.recentering
            self.recentering = f.curl >= self.recenter_curl
            if was and not self.recentering:
                # apertura del pugno: le dita che si distendono spostano un po' il palmo;
                # breve blocco per non far partire il cursore dal centro
                self._freeze_until = max(self._freeze_until, now + self.freeze_s)
                frozen = True
            self._anchor_move(f, now, frozen)
        elif not frozen or self.cursor is None:
            self._move(self.to_screen(f.palm))

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
            if self.motion == "anchor":
                delta *= 0.1 / f.size          # stessa sensazione a ogni distanza dalla webcam
            self._scroll_ref = float(f.palm[1])
            self._scroll_acc += delta
            ticks = int(self._scroll_acc)
            if ticks:
                self.mouse.scroll(ticks)
                self._scroll_acc -= ticks
