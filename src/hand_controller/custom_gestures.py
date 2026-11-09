"""Gesti personalizzati: una posa della mano tenuta per un certo tempo esegue un'azione.

Esempio di voce in configurazione::

    - name: Corna = cambia modalità
      enabled: true
      hand: any                # any | Left | Right
      fingers: {thumb: any, index: up, middle: down, ring: down, pinky: up}
      hold_s: 1.0              # tempo di tenuta prima che scatti
      trigger: once            # once = una volta per gesto | hold = premuto finché tieni la posa
                               # release = una volta, quando abbassi la posa dopo averla tenuta
      modes: [mouse, gamepad, paused]
      action: {type: app, value: toggle_mode}
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .actions import ActionExecutor
from .gestures import FINGERS, HandFeatures, matches_pose

# Pose pronte, usate dalla finestra di configurazione
POSE_PRESETS: dict[str, dict[str, str]] = {
    "Corna (indice + mignolo)": {"thumb": "any", "index": "up", "middle": "down", "ring": "down", "pinky": "up"},
    "V (indice + medio)": {"thumb": "any", "index": "up", "middle": "up", "ring": "down", "pinky": "down"},
    "Indice": {"thumb": "any", "index": "up", "middle": "down", "ring": "down", "pinky": "down"},
    "Tre dita": {"thumb": "any", "index": "up", "middle": "up", "ring": "up", "pinky": "down"},
    "Mignolo": {"thumb": "any", "index": "down", "middle": "down", "ring": "down", "pinky": "up"},
    "Telefono (pollice + mignolo)": {"thumb": "up", "index": "down", "middle": "down", "ring": "down", "pinky": "up"},
    "Pistola (pollice + indice)": {"thumb": "up", "index": "up", "middle": "down", "ring": "down", "pinky": "down"},
    "Pollice su": {"thumb": "up", "index": "down", "middle": "down", "ring": "down", "pinky": "down"},
    "Spider-Man (pollice, indice, mignolo)": {"thumb": "up", "index": "up", "middle": "down", "ring": "down", "pinky": "up"},
}

GRACE_S = 0.12   # tolleranza a brevi perdite della posa (tremolio del tracciamento)


def describe_pose(fingers: dict[str, str]) -> str:
    for name, preset in POSE_PRESETS.items():
        if all(preset.get(k, "any") == (fingers or {}).get(k, "any") for k in FINGERS):
            return name.split(" (")[0]
    it = {"thumb": "pollice", "index": "indice", "middle": "medio", "ring": "anulare", "pinky": "mignolo"}
    up = [it[k] for k in FINGERS if (fingers or {}).get(k) == "up"]
    return ("tese: " + ", ".join(up)) if up else "personalizzata"


@dataclass
class _State:
    since: float | None = None
    last_seen: float = -1.0
    fired: bool = False      # once: già eseguita per questo gesto
    pressed: bool = False    # hold: azione attualmente premuta
    ready: bool = False      # release: tenuta raggiunta, scatta quando la posa finisce


@dataclass
class GestureEngine:
    defs: list[dict]
    executor: ActionExecutor
    _states: list[_State] = field(default_factory=list)

    def __post_init__(self):
        self.defs = [d for d in (self.defs or []) if d.get("enabled", True)]
        self._states = [_State() for _ in self.defs]

    def _matched(self, d: dict, feats: dict[str, HandFeatures]) -> bool:
        hand = d.get("hand", "any")
        for label, f in feats.items():
            if hand not in ("any", label):
                continue
            if matches_pose(f, d.get("fingers", {})):
                return True
        return False

    def update(self, feats: dict[str, HandFeatures], mode: str, now: float) -> tuple[float, str]:
        """Aggiorna i gesti; restituisce (avanzamento 0..1, nome) del gesto in carica, per l'overlay."""
        best = (0.0, "")
        for d, st in zip(self.defs, self._states):
            active_mode = mode in d.get("modes", ["mouse", "gamepad", "paused"])
            seen = active_mode and self._matched(d, feats)
            if seen:
                st.last_seen = now
                if st.since is None:
                    st.since = now
            elif st.since is not None and now - st.last_seen > GRACE_S:
                self._end(d, st, now)
            if st.since is None:
                continue

            hold = float(d.get("hold_s", 0.5))
            progress = 1.0 if hold <= 0 else min(1.0, (now - st.since) / hold)
            trigger = d.get("trigger", "once")
            if progress >= 1.0 and trigger == "release":
                st.ready = True
                best = max(best, (1.0, d.get("name", "") + " - abbassa"))
            elif progress >= 1.0:
                if trigger == "hold":
                    if not st.pressed:
                        st.pressed = True
                        self.executor.press(d["action"], now, self._ctx(d))
                elif not st.fired:
                    st.fired = True
                    self.executor.fire(d["action"], now, self._ctx(d))
            elif progress > best[0]:
                best = (progress, d.get("name", ""))
        return best

    @staticmethod
    def _ctx(d: dict) -> dict:
        return {"source": "gesto", "name": d.get("name", "")}

    def _end(self, d: dict, st: _State, now: float | None = None) -> None:
        if st.pressed:
            self.executor.release(d["action"])
        if st.ready and now is not None:
            self.executor.fire(d["action"], now, self._ctx(d))
        st.since, st.fired, st.pressed, st.ready = None, False, False, False

    def release_all(self) -> None:
        for d, st in zip(self.defs, self._states):
            self._end(d, st)
