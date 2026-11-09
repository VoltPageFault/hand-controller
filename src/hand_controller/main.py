"""Punto di ingresso: loop webcam -> tracking -> gesti -> mouse/gamepad virtuale."""
from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time

from .actions import ActionExecutor
from .backends import NullGamepadBackend, PadState, create_gamepad, create_mouse
from .backends.null import NullMouseBackend
from .config import CONFIG_WINDOW_TITLE, config_stamp, load_config
from .custom_gestures import GestureEngine
from .desktop import foreground_process
from .filters import OneEuroFilter
from .gamepad_mode import GamepadMapper
from .gestures import HandAnalyzer, HandFeatures
from .mouse_mode import MouseMapper

MODES = ("mouse", "gamepad", "paused")
HOTKEY_EVENTS = ("toggle_mode", "toggle_pause", "quit", "open_config")


def to_pynput_hotkey(combo: str) -> str:
    """'ctrl+f10' -> '<ctrl>+<f10>' (formato di pynput.GlobalHotKeys)."""
    parts = []
    for p in str(combo).lower().replace(" ", "").split("+"):
        p = {"win": "cmd", "windows": "cmd", "control": "ctrl", "escape": "esc"}.get(p, p)
        parts.append(p if len(p) == 1 else f"<{p}>")
    return "+".join(parts)


class Hotkeys:
    """Tasti globali (anche combinazioni) via pynput; le richieste sono consumate dal loop."""

    def __init__(self, cfg: dict):
        self.events = {name: threading.Event() for name in HOTKEY_EVENTS}
        self._listener = None
        mapping = {}
        for name in HOTKEY_EVENTS:
            combo = (cfg or {}).get(name)
            if combo:
                mapping[to_pynput_hotkey(combo)] = self.events[name].set
        if not mapping:
            return
        try:
            from pynput import keyboard
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
        except Exception as exc:
            print(f"[hotkeys] non disponibili: {exc}")

    def take(self, name: str) -> bool:
        ev = self.events[name]
        if ev.is_set():
            ev.clear()
            return True
        return False

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()


class App:
    def __init__(self, cfg: dict, dry_run: bool = False, profile: str | None = None):
        from .capture import Camera
        from .tracker import HandTracker

        self.cfg = cfg
        self.profile = profile
        self.dry_run = dry_run
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

        self.quit_requested = False
        self.executor = ActionExecutor(self.mouse, {
            "toggle_mode": self._toggle_active_mode,
            "mouse_mode": lambda: self.set_mode("mouse"),
            "gamepad_mode": lambda: self.set_mode("gamepad"),
            "toggle_pause": self._toggle_pause,
            "recenter": lambda: self.mouse_mapper.request_recenter(),
            "open_config": self.open_config,
            "quit": self._request_quit,
        }, dry_run=dry_run)

        self.mode = cfg.get("startup_mode", "mouse")
        self._last_active_mode = self.mode if self.mode != "paused" else "mouse"
        self._fg_checked = 0.0
        self._fg_name: str | None = None
        self.pad_state = PadState()
        self._config_proc: subprocess.Popen | None = None
        self._stamp = config_stamp()
        self._stamp_checked = 0.0
        self.window_dirty = True          # la finestra va (ri)posizionata
        self._build(cfg)

    def _build(self, cfg: dict) -> None:
        """Crea i componenti che dipendono dalla configurazione (anche al ricaricamento)."""
        self.mouse_mapper = MouseMapper(cfg["mouse"], self.mouse)
        self.pad_mapper: GamepadMapper | None = None   # creato al primo frame (serve l'aspect)
        self.filters: dict[str, OneEuroFilter] = {}
        self.analyzers: dict[str, HandAnalyzer] = {}
        self.hotkeys = Hotkeys(cfg.get("hotkeys", {}))
        self.engine = GestureEngine(cfg.get("custom_gestures", []), self.executor)

    # ---- configurazione a caldo -------------------------------------------------------------
    def _check_reload(self, now: float) -> None:
        if now - self._stamp_checked < 0.5:
            return
        self._stamp_checked = now
        stamp = config_stamp()
        if stamp == self._stamp:
            return
        self._stamp = stamp
        try:
            new = load_config(self.profile)
            GamepadMapper(new["gamepad"], 1.0)        # valida prima di applicare
        except Exception as exc:
            print(f"[config] configurazione non valida, ignorata: {exc}")
            return
        self.apply_config(new)

    def apply_config(self, new: dict) -> None:
        from .capture import Camera
        from .tracker import HandTracker

        old = self.cfg
        self.mouse_mapper.release_all()
        self.engine.release_all()
        self.executor.release_all()
        self.gamepad.reset()
        self.hotkeys.stop()

        if new["camera"] != old["camera"]:
            cam = new["camera"]
            self.camera.close()
            try:
                self.camera = Camera(cam["index"], cam["width"], cam["height"], cam["fps"],
                                     cam["mirror"], cam.get("exposure"))
            except Exception as exc:
                print(f"[config] webcam non disponibile ({exc}), torno alla precedente")
                c = old["camera"]
                self.camera = Camera(c["index"], c["width"], c["height"], c["fps"], c["mirror"],
                                     c.get("exposure"))
                new["camera"] = old["camera"]
        if new["tracking"] != old["tracking"] or new["camera"]["mirror"] != old["camera"]["mirror"]:
            self.tracker.close()
            self.tracker = HandTracker(new["tracking"], mirrored=new["camera"]["mirror"])
        if new["backend"] != old["backend"]:
            print("[config] il cambio di backend richiede il riavvio dell'app")
        if new["overlay"] != old["overlay"]:
            self.window_dirty = True

        self.cfg = new
        self._build(new)
        self._fg_name = None                          # rivaluta il cambio automatico
        print("[config] impostazioni applicate")

    def open_config(self) -> None:
        """Apre la finestra di configurazione in un processo separato (una sola istanza)."""
        if self._config_proc and self._config_proc.poll() is None:
            if sys.platform == "win32":
                import ctypes
                hwnd = ctypes.windll.user32.FindWindowW(None, CONFIG_WINDOW_TITLE)
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)      # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._config_proc = subprocess.Popen([sys.executable, "-m", "hand_controller.config_ui"],
                                             creationflags=flags)
        print("[app] finestra di configurazione aperta")

    def open_manual(self) -> None:
        from .manual import open_manual
        try:
            print(f"[app] manuale aperto: {open_manual(self.cfg)}")
        except Exception as exc:
            print(f"[app] impossibile aprire il manuale: {exc}")

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

    def _toggle_pause(self) -> None:
        self.set_mode(self._last_active_mode if self.mode == "paused" else "paused")

    def _request_quit(self) -> None:
        self.quit_requested = True

    def _handle_switches(self, now: float) -> None:
        if self.hotkeys.take("toggle_mode"):
            self._toggle_active_mode()
        if self.hotkeys.take("toggle_pause"):
            self._toggle_pause()
        if self.hotkeys.take("open_config"):
            self.open_config()
        if self.hotkeys.take("quit"):
            self._request_quit()

        auto = self.cfg["auto_switch"]
        if auto.get("enabled") and now - self._fg_checked > 0.5:
            self._fg_checked = now
            name = foreground_process()
            if name != self._fg_name:
                self._fg_name = name
                if name and self.mode != "paused" and "python" not in name:
                    self.set_mode("gamepad" if name in auto["game_processes"] else "mouse")

    # ---- loop principale ------------------------------------------------------------------
    def run(self, show_overlay: bool = True) -> None:
        import cv2

        from . import overlay

        frame_id, fps, last_t = -1, 0.0, time.monotonic()
        window = "Hand Controller"
        ui = {"hover": None, "click": None}
        buttons = {"config": overlay.config_button_rect, "info": overlay.info_button_rect}

        def on_mouse(event, x, y, flags, param):
            ui["hover"] = None
            for name, rect in buttons.items():
                bx0, by0, bx1, by1 = rect(*param)
                if bx0 <= x <= bx1 and by0 <= y <= by1:
                    ui["hover"] = name
                    if event == cv2.EVENT_LBUTTONUP:
                        ui["click"] = name

        print("[app] avviato. Overlay: q/ESC esci, m cambia modalità, p pausa, c configurazione, i manuale, "
              f"+/- sensibilità mouse. Hotkey globali: {self.cfg['hotkeys']}")
        try:
            while not self.quit_requested:
                frame_id, frame = self.camera.read(frame_id)
                if frame is None:
                    print("[app] nessun fotogramma dalla webcam")
                    continue
                now = time.monotonic()
                fps = 0.9 * fps + 0.1 / max(now - last_t, 1e-6)
                last_t = now
                h, w = frame.shape[:2]
                aspect = w / h
                self._check_reload(now)
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

                self._handle_switches(now)
                progress, gesture_name = self.engine.update(feats, self.mode, now)

                if self.mode == "mouse":
                    self.mouse_mapper.update(feats, now, aspect)
                elif self.mode == "gamepad":
                    self.pad_state = self.executor.merge_pad(self.pad_mapper.update(feats), now)
                    self.gamepad.send(self.pad_state)

                if show_overlay:
                    ocfg = self.cfg["overlay"]
                    mm = self.mouse_mapper
                    region, mouse_info = mm.current_region(), None
                    if mm.motion == "anchor":
                        mouse_info = f"area {mm.span:.2f}" + (
                            "  CENTRO" if mm.recentering else
                            "" if region is not None else "  pugno=centra")
                    img = overlay.draw(frame, hands, feats, self.mode, fps, self.pad_state,
                                       region, progress, self._fg_name, mouse_info,
                                       out_width=ocfg.get("width"),
                                       font_scale=ocfg.get("font_scale", 1.0),
                                       gesture_name=gesture_name,
                                       config_hover=ui["hover"] == "config",
                                       info_hover=ui["hover"] == "info")
                    if self.window_dirty:
                        overlay.create_window(window, ocfg, img.shape)
                        cv2.setMouseCallback(window, on_mouse, (img.shape[1], img.shape[0]))
                        self.window_dirty = False
                    elif overlay.window_closed(window):   # chiusa con la X: esci
                        break
                    cv2.imshow(window, img)
                    key = cv2.waitKey(1) & 0xFF
                    if ui["click"] == "config":
                        self.open_config()
                    elif ui["click"] == "info":
                        self.open_manual()
                    ui["click"] = None
                    if key in (27, ord("q")):
                        break
                    if key == ord("m"):
                        self._toggle_active_mode()
                    elif key == ord("c"):
                        self.open_config()
                    elif key == ord("i"):
                        self.open_manual()
                    elif key in (ord("+"), ord("=")):
                        # + = più sensibile = rettangolo più piccolo
                        print(f"[mouse] area {self.mouse_mapper.adjust_span(1 / 1.15):.2f} mani")
                    elif key == ord("-"):
                        print(f"[mouse] area {self.mouse_mapper.adjust_span(1.15):.2f} mani")
                    elif key == ord("p"):
                        self._toggle_pause()
        except KeyboardInterrupt:
            pass
        finally:
            self.close()
            if show_overlay:
                cv2.destroyAllWindows()

    def close(self) -> None:
        self.mouse_mapper.release_all()
        self.engine.release_all()
        self.executor.release_all()
        self.gamepad.close()
        self.mouse.close()
        self.hotkeys.stop()
        self.tracker.close()
        self.camera.close()


def list_cameras(max_index: int = 6) -> None:
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
    ap.add_argument("--config", help="profilo YAML con impostazioni da sovrascrivere")
    ap.add_argument("--camera", type=int, help="indice webcam")
    ap.add_argument("--mode", choices=MODES, help="modalità iniziale")
    ap.add_argument("--no-overlay", action="store_true", help="nessuna finestra di debug")
    ap.add_argument("--dry-run", action="store_true", help="non genera input reale (solo overlay)")
    ap.add_argument("--list-cameras", action="store_true", help="elenca le webcam disponibili")
    ap.add_argument("--settings", action="store_true", help="apre solo la finestra di configurazione")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):   # accenti corretti anche nelle console Windows
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if args.list_cameras:
        list_cameras()
        return
    if args.settings:
        from .config_ui import main as settings_main
        settings_main()
        return
    cfg = load_config(args.config)
    if args.camera is not None:
        cfg["camera"]["index"] = args.camera
    if args.mode:
        cfg["startup_mode"] = args.mode
    App(cfg, dry_run=args.dry_run, profile=args.config).run(
        show_overlay=not args.no_overlay and cfg["overlay"]["enabled"])


if __name__ == "__main__":
    main()
