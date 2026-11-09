"""Manuale HTML autosufficiente, generato con la configurazione attuale e aperto nel browser."""
from __future__ import annotations

import json
import webbrowser
from pathlib import Path

from . import __version__
from .actions import describe_action
from .config import user_config_path

TEMPLATE = Path(__file__).with_name("manual.html")
PLACEHOLDER = "/*__DATA__*/null"


def manual_data(cfg: dict) -> dict:
    pad = cfg.get("gamepad", {})

    def hand(h: dict) -> dict:
        return {"stick": h.get("stick"), "fist": h.get("fist"), "pinch": h.get("pinch") or {}}

    return {
        "version": __version__,
        "configPath": str(user_config_path()),
        "hotkeys": cfg.get("hotkeys", {}),
        "mouse": {"hand": cfg["mouse"].get("hand", "right"),
                  "bindings": cfg["mouse"].get("bindings", {})},
        "gamepad": {"left": hand(pad.get("left_hand", {})), "right": hand(pad.get("right_hand", {}))},
        "gestures": [{
            "name": g.get("name", ""), "enabled": g.get("enabled", True), "hand": g.get("hand", "any"),
            "hold_s": g.get("hold_s", 0), "trigger": g.get("trigger", "once"),
            "modes": g.get("modes", []), "fingers": g.get("fingers", {}),
            "action": describe_action(g.get("action", {})),
        } for g in cfg.get("custom_gestures", [])],
        "games": cfg.get("auto_switch", {}).get("game_processes", []),
    }


def build_manual(cfg: dict, out: Path | None = None) -> Path:
    html = TEMPLATE.read_text(encoding="utf-8")
    # "</" spezzato: nessun testo dell'utente può chiudere il tag <script>
    data = json.dumps(manual_data(cfg), ensure_ascii=False).replace("</", "<\\/")
    html = html.replace(PLACEHOLDER, data, 1)
    out = out or user_config_path().with_name("manuale.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def open_manual(cfg: dict) -> Path:
    path = build_manual(cfg)
    webbrowser.open(path.as_uri())
    return path
