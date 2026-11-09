"""Punto di ingresso: loop webcam -> tracking -> gesti -> mouse/gamepad virtuale."""
from __future__ import annotations

import argparse
import sys
import threading
import time

from .backends import NullGamepadBackend, PadState, create_gamepad, create_mouse
from .backends.null import NullMouseBackend
from .config import load_config
from .desktop import foreground_process
from .filters import OneEuroFilter
from .gamepad_mode import GamepadMapper
from .gestures import HandAnalyzer, HandFeatures
from .mouse_mode import MouseMapper

MODES = ("mouse", "gamepad", "paused")


class Hotkeys:
    """Tasti globali via pynput; le richieste vengono consumate dal loop principale."""

    def __init__(self, cfg: dict):
        self.toggle_mode = threading.Event()
        self.toggle_pause = threading.Event()
        self._listener = None
        try:
            from pynput import keyboard

            def key(name):
                return getattr(keyboard.Key, name, None) or keyboard.KeyCode.from_char(name)

            k_mode, k_pause = key(cfg.get("toggle_mode", "f9")), key(cfg.get("toggle_pause", "f10"))

            def on_press(k):
                if k == k_mode:
                    self.toggle_mode.set()
                elif k == k_pause:
                    self.toggle_pause.set()

            self._listener = keyboard.Listener(on_press=on_press, daemon=True)
            self._listener.start()
        except Exception as exc:
            print(f"[hotkeys] non disponibili: {exc}")

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()


class App:
    def __init__(self, cfg: dict, dry_run: bool = False):
        from .capture import Camera
        from .tracker import HandTracker

        self.cfg = cfg
        cam = cfg["camera"]
        self.camera = Camera(cam["index"], cam["width"], cam["height"], cam["fps"], cam["mirror"],
                             cam.get("exposure"))
        self.tracker = HandTracker(cfg["tracking"], mirrored=cam["mirror"])

        if dry_run:
            self.mouse, self.gamepad = NullMouseBackend(), NullGamepadBackend()
        else:
            self.mouse = create_mouse(cfg["backend"]["mouse"])
            self.gamepad = create_gamepad(cfg["backend"]["gamepad"])
        print(f"[app] backend mouse={self.mouse.name} gamepad={self.gamepad.name}")

        self.mouse_mapper = MouseMapper(cfg["mouse"], self.mouse)
        self.pad_mapper: GamepadMapper | None = None  # creato al primo frame (serve l'aspect)
        self.filters: dict[str, OneEuroFilter] = {}
        self.analyzers: dict[str, HandAnalyzer] = {}
        self.hotkeys = Hotkeys(cfg.get("hotkeys", {}))

        self.mode = cfg.get("startup_mode", "mouse")
        self._last_active_mode = self.mode if self.mode != "paused" else "mouse"
        self._horns_since: float | None = None
        self._horns_latched = False
        self._fg_checked = 0.0
        self._fg_name: str | None = None
        self.pad_state = PadState()

    # ---- modalità -------------------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        if self.mode == "mouse":
            self.mouse_mapper.release_all()
        if self.mode == "gamepad":
            self.gamepad.reset()
            if self.pad_mapper:
                self.pad_mapper.reset()
            self.pad_state = PadState()
        print(f"[app] modalità: {self.mode} -> {mode}")
        self.mode = mode
        if mode != "paused":
            self._last_active_mode = mode

    def _toggle_active_mode(self) -> None:
        current = self.mode if self.mode != "paused" else self._last_active_mode
        self.set_mode("gamepad" if current == "mouse" else "mouse")

    def _handle_switches(self, feats: dict[str, HandFeatures], now: float) -> float:
        if self.hotkeys.toggle_mode.is_set():
            self.hotkeys.toggle_mode.clear()
            self._toggle_active_mode()
        if self.hotkeys.toggle_pause.is_set():
            self.hotkeys.toggle_pause.clear()
            self.set_mode(self._last_active_mode if self.mode == "paused" else "paused")

        auto = self.cfg["auto_switch"]
        if auto.get("enabled") and now - self._fg_checked > 0.5:
            self._fg_checked = now
            name = foreground_process()
            if name != self._fg_name:
                self._fg_name = name
                if name and self.mode != "paused":
                    self.set_mode("gamepad" if name in auto["game_processes"] else "mouse")

        # Gesto "corna" mantenuto: cambia modalità (una volta per gesto)
        hold = self.cfg["gestures"].get("mode_switch_hold_s", 1.0)
        if any(f.horns for f in feats.values()):
            if self._horns_since is None:
                self._horns_since = now
            progress = min(1.0, (now - self._horns_since) / hold)
            if progress >= 1.0 and not self._horns_latched:
                self._horns_latched = True
                self._toggle_active_mode()
            return 0.0 if self._horns_latched else progress
        self._horns_since = None
        self._horns_latched = False
        return 0.0

    # ---- loop principale ------------------------------------------------------------------
    def run(self, show_overlay: bool = True) -> None:
        import cv2

        from . import overlay

        frame_id, fps, last_t = -1, 0.0, time.monotonic()
        window = "Hand Controller"
        print("[app] avviato. Overlay: q/ESC esci, m cambia modalità, p pausa. "
              f"Hotkey globali: {self.cfg['hotkeys']}")
        try:
            while True:
                frame_id, frame = self.camera.read(frame_id)
                if frame is None:
                    print("[app] nessun fotogramma dalla webcam")
                    continue
                now = time.monotonic()
                fps = 0.9 * fps + 0.1 / max(now - last_t, 1e-6)
                last_t = now
                h, w = frame.shape[:2]
                aspect = w / h
                if self.pad_mapper is None:
                    self.pad_mapper = GamepadMapper(self.cfg["gamepad"], aspect)

                hands = self.tracker.process(frame, now * 1000)
                feats: dict[str, HandFeatures] = {}
                for hand in hands:
                    flt = self.filters.setdefault(hand.label, OneEuroFilter(**self.cfg["filter"]))
                    an = self.analyzers.setdefault(hand.label, HandAnalyzer(self.cfg["gestures"]))
                    hand.landmarks = flt(hand.landmarks, now)
                    feats[hand.label] = an.update(hand.label, hand.landmarks, aspect)
                for label in set(self.filters) - set(feats):   # mano persa: reset dello stato
                    self.filters.pop(label).reset()
                    self.analyzers.pop(label, None)

                progress = self._handle_switches(feats, now)

                if self.mode == "mouse":
                    self.mouse_mapper.update(feats, now)
                elif self.mode == "gamepad":
                    self.pad_state = self.pad_mapper.update(feats)
                    self.gamepad.send(self.pad_state)

                if show_overlay:
                    img = overlay.draw(frame, hands, feats, self.mode, fps, self.pad_state,
                                       self.mouse_mapper.region, progress, self._fg_name)
                    cv2.imshow(window, img)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (27, ord("q")):
                        break
                    if key == ord("m"):
                        self._toggle_active_mode()
                    elif key == ord("p"):
                        self.set_mode(self._last_active_mode if self.mode == "paused" else "paused")
        except KeyboardInterrupt:
            pass
        finally:
            self.close()
            if show_overlay:
                cv2.destroyAllWindows()

    def close(self) -> None:
        self.mouse_mapper.release_all()
        self.gamepad.close()
        self.mouse.close()
        self.hotkeys.stop()
        self.tracker.close()
        self.camera.close()


def list_cameras(max_index: int = 6) -> None:
    import sys

    import cv2
    api = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    for i in range(max_index):
        cap = cv2.VideoCapture(i, api)
        ok = cap.isOpened() and cap.read()[0]
        if ok:
            print(f"  webcam {i}: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
                  f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
        cap.release()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="hand-controller",
                                 description="Mouse e controller Xbox virtuali tramite hand tracking")
    ap.add_argument("--config", help="file YAML con le impostazioni da sovrascrivere")
    ap.add_argument("--camera", type=int, help="indice webcam")
    ap.add_argument("--mode", choices=MODES, help="modalità iniziale")
    ap.add_argument("--no-overlay", action="store_true", help="nessuna finestra di debug")
    ap.add_argument("--dry-run", action="store_true", help="non genera input reale (solo overlay)")
    ap.add_argument("--list-cameras", action="store_true", help="elenca le webcam disponibili")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):   # accenti corretti anche nelle console Windows
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if args.list_cameras:
        list_cameras()
        return
    cfg = load_config(args.config)
    if args.camera is not None:
        cfg["camera"]["index"] = args.camera
    if args.mode:
        cfg["startup_mode"] = args.mode
    App(cfg, dry_run=args.dry_run).run(show_overlay=not args.no_overlay and cfg["overlay"]["enabled"])


if __name__ == "__main__":
    main()
