"""Azioni collegabili ai gesti personalizzati: tasti, click, pulsanti gamepad, comandi dell'app.

Un'azione è un dizionario ``{"type": ..., "value": ...}``:

- ``app``   : toggle_mode | mouse_mode | gamepad_mode | toggle_pause | recenter | open_config | quit
- ``key``   : tasto o combinazione, es. ``alt+tab``, ``ctrl+shift+esc``, ``win+d``, ``media_volume_up``
- ``mouse`` : left | right | middle | double
- ``pad``   : pulsante del controller (A, B, X, Y, LB, RB, LT, RT, BACK, START, LS, RS, DPAD_UP, ...)
- ``run``   : riga di comando da avviare (es. ``notepad.exe`` o ``"C:\\Giochi\\gioco.exe"``)
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from typing import Callable

from .backends import BUTTONS, TRIGGERS, MouseBackend, PadState

APP_ACTIONS = {
    "toggle_mode": "Cambia modalità mouse/gamepad",
    "mouse_mode": "Passa al mouse",
    "gamepad_mode": "Passa al gamepad",
    "toggle_pause": "Pausa / riprendi",
    "recenter": "Ricentra il mouse",
    "open_config": "Apri la configurazione",
    "quit": "Esci dall'app",
}
MOUSE_ACTIONS = {"left": "Click sinistro", "right": "Click destro", "middle": "Click centrale",
                 "double": "Doppio click"}
PAD_ACTIONS = tuple(BUTTONS) + tuple(TRIGGERS)
ACTION_TYPES = {"app": "Comando dell'app", "key": "Tasto / combinazione", "mouse": "Mouse",
                "pad": "Pulsante gamepad", "run": "Avvia programma"}

KEY_ALIASES = {"win": "cmd", "windows": "cmd", "control": "ctrl", "escape": "esc",
               "return": "enter", "canc": "delete", "del": "delete", "pgup": "page_up",
               "pgdown": "page_down", "pagesu": "page_up", "pagegiu": "page_down",
               "stamp": "print_screen", "printscreen": "print_screen", "volume_up": "media_volume_up",
               "volume_down": "media_volume_down", "mute": "media_volume_mute",
               "play_pause": "media_play_pause", "next": "media_next", "previous": "media_previous",
               "spazio": "space", "invio": "enter"}


def parse_keys(combo: str) -> list:
    """'ctrl+shift+t' -> [Key.ctrl, Key.shift, 't']. Solleva ValueError se un tasto è sconosciuto."""
    from pynput.keyboard import Key, KeyCode

    keys = []
    for raw in str(combo).lower().replace(" ", "").split("+"):
        if not raw:
            raise ValueError(f"combinazione non valida: {combo!r}")
        name = KEY_ALIASES.get(raw, raw)
        if len(name) == 1:
            keys.append(KeyCode.from_char(name))
        elif hasattr(Key, name):
            keys.append(getattr(Key, name))
        else:
            raise ValueError(f"tasto sconosciuto: {raw!r}")
    return keys


def validate_action(action: dict) -> str | None:
    """Messaggio d'errore leggibile, oppure None se l'azione è valida."""
    t, v = (action or {}).get("type"), (action or {}).get("value")
    if t not in ACTION_TYPES:
        return f"tipo di azione sconosciuto: {t!r}"
    if t == "app" and v not in APP_ACTIONS:
        return f"comando dell'app sconosciuto: {v!r}"
    if t == "mouse" and v not in MOUSE_ACTIONS:
        return f"azione mouse sconosciuta: {v!r}"
    if t == "pad" and v not in PAD_ACTIONS:
        return f"pulsante gamepad sconosciuto: {v!r}"
    if t == "key":
        try:
            parse_keys(v or "")
        except ValueError as exc:
            return str(exc)
    if t == "run" and not str(v or "").strip():
        return "manca il comando da avviare"
    return None


def describe_action(action: dict) -> str:
    t, v = (action or {}).get("type"), (action or {}).get("value")
    if t == "app":
        return APP_ACTIONS.get(v, str(v))
    if t == "mouse":
        return MOUSE_ACTIONS.get(v, str(v))
    if t == "pad":
        return f"Gamepad {v}"
    if t == "key":
        return f"Tasti {v}"
    if t == "run":
        return f"Avvia {v}"
    return "—"


class ActionExecutor:
    """Esegue le azioni. ``press``/``release`` per quelle mantenute, ``fire`` per quelle istantanee."""

    PAD_TAP_S = 0.12

    def __init__(self, mouse: MouseBackend, app_commands: dict[str, Callable[[], None]],
                 dry_run: bool = False):
        self.mouse = mouse
        self.app_commands = app_commands
        self.dry_run = dry_run
        self._kb = None
        if not dry_run:
            try:
                from pynput.keyboard import Controller
                self._kb = Controller()
            except Exception as exc:   # es. Linux senza X
                print(f"[azioni] tastiera virtuale non disponibile: {exc}")
        self._pad_held: set[str] = set()
        self._pad_taps: dict[str, float] = {}
        self._keys_held: dict[str, list] = {}
        self._now = 0.0

    def _log(self, what: str) -> None:
        print(f"[gesto] {what}" + ("  (dry-run)" if self.dry_run else ""))

    # ---- azioni istantanee ---------------------------------------------------------------
    def fire(self, action: dict, now: float) -> None:
        t, v = action.get("type"), action.get("value")
        self._log(describe_action(action))
        if t == "app":
            cmd = self.app_commands.get(v)
            if cmd:
                cmd()
        elif t == "pad":
            self._pad_taps[v] = now + self.PAD_TAP_S
        elif self.dry_run:
            return
        elif t == "key" and self._kb:
            keys = parse_keys(v)
            for k in keys:
                self._kb.press(k)
            for k in reversed(keys):
                self._kb.release(k)
        elif t == "mouse":
            if v == "double":
                self.mouse.click("left")
                self.mouse.click("left")
            else:
                self.mouse.click(v)
        elif t == "run":
            try:
                args = v if sys.platform == "win32" else shlex.split(v)
                subprocess.Popen(args, shell=False)
            except Exception as exc:
                print(f"[gesto] impossibile avviare {v!r}: {exc}")

    # ---- azioni mantenute (finché il gesto è tenuto) -------------------------------------
    def press(self, action: dict, now: float) -> None:
        t, v = action.get("type"), action.get("value")
        if t == "pad":
            self._log(f"{describe_action(action)} premuto")
            self._pad_held.add(v)
        elif t == "key":
            self._log(f"{describe_action(action)} premuti")
            if self._kb and not self.dry_run:
                keys = parse_keys(v)
                for k in keys:
                    self._kb.press(k)
                self._keys_held[v] = keys
        elif t == "mouse" and v in ("left", "right", "middle"):
            self._log(f"{describe_action(action)} premuto")
            if not self.dry_run:
                self.mouse.press(v)
        else:                                       # app / run / doppio click: istantanee
            self.fire(action, now)

    def release(self, action: dict) -> None:
        t, v = action.get("type"), action.get("value")
        if t == "pad":
            self._pad_held.discard(v)
        elif t == "key":
            for k in reversed(self._keys_held.pop(v, [])):
                self._kb.release(k)
        elif t == "mouse" and v in ("left", "right", "middle") and not self.dry_run:
            self.mouse.release(v)

    def release_all(self) -> None:
        for v in list(self._keys_held):
            self.release({"type": "key", "value": v})
        self._pad_held.clear()
        self._pad_taps.clear()

    def merge_pad(self, state: PadState, now: float) -> PadState:
        """Aggiunge allo stato del controller i pulsanti premuti dai gesti personalizzati."""
        self._pad_taps = {b: t for b, t in self._pad_taps.items() if t > now}
        for b in self._pad_held | set(self._pad_taps):
            if b == "LT":
                state.lt = 1.0
            elif b == "RT":
                state.rt = 1.0
            else:
                state.buttons.add(b)
        return state
