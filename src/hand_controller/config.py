"""Configurazione a livelli: default del pacchetto -> impostazioni utente -> profilo opzionale.

Le impostazioni utente (scritte dalla finestra di configurazione) contengono solo le differenze
rispetto al default; "Ripristina default" cancella semplicemente quel file.
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_config.yaml")
CONFIG_WINDOW_TITLE = "Hand Controller - Configurazione"


def user_config_path() -> Path:
    """%APPDATA%\\hand-controller\\config.yaml (Windows) o ~/.config/hand-controller/config.yaml."""
    override = os.environ.get("HAND_CONTROLLER_CONFIG")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "hand-controller" / "config.yaml"


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def diff_config(base: dict, cfg: dict) -> dict:
    """Solo le chiavi di ``cfg`` diverse da ``base`` (le liste vengono confrontate per intero)."""
    out: dict = {}
    for key, value in cfg.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            sub = diff_config(base[key], value)
            if sub:
                out[key] = sub
        elif key not in base or base[key] != value:
            out[key] = copy.deepcopy(value)
    return out


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _normalize(cfg: dict) -> dict:
    cfg["auto_switch"]["game_processes"] = [
        str(p).lower() for p in cfg["auto_switch"].get("game_processes") or []
    ]
    return cfg


def load_default_config() -> dict[str, Any]:
    return _normalize(_read_yaml(DEFAULT_CONFIG_PATH))


def load_config(user_path: str | Path | None = None, use_user_settings: bool = True) -> dict[str, Any]:
    """Default + impostazioni utente (se presenti) + profilo ``user_path`` (se indicato)."""
    cfg = _read_yaml(DEFAULT_CONFIG_PATH)
    if use_user_settings:
        up = user_config_path()
        if up.exists():
            try:
                cfg = deep_merge(cfg, _read_yaml(up))
            except Exception as exc:
                print(f"[config] impostazioni utente illeggibili ({up}): {exc} - uso i default")
    if user_path:
        cfg = deep_merge(cfg, _read_yaml(Path(user_path)))
    return _normalize(cfg)


def save_user_config(cfg: dict) -> Path:
    """Salva le differenze rispetto al default nel file utente (scrittura atomica)."""
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    diff = diff_config(load_default_config(), cfg)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# Impostazioni di Hand Controller (solo le differenze dal default).\n"
                "# Cancella questo file o usa 'Ripristina default' per tornare ai valori originali.\n")
        yaml.safe_dump(diff, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, path)
    return path


def reset_user_config() -> None:
    path = user_config_path()
    if path.exists():
        path.unlink()


def config_stamp() -> float | None:
    """Data di modifica del file utente (None se non esiste): serve per ricaricare a caldo."""
    try:
        return user_config_path().stat().st_mtime
    except FileNotFoundError:
        return None
