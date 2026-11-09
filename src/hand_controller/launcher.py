"""Avvio di programmi, script e comandi personalizzati collegati a gesti e colpi.

Due tipi di azione:

- ``run``   : un programma o uno script con eventuali argomenti, es.
  ``C:\\Script\\luci.py --stanza studio`` oppure ``"C:\\Giochi\\Il mio gioco\\gioco.exe"``.
  L'interprete si sceglie dall'estensione (.py, .ps1, .bat, ...); documenti, collegamenti e
  link (``steam://...``, ``https://...``) si aprono col programma associato.
- ``shell`` : una riga di comando completa per cmd (Windows) o sh (Linux/macOS), con pipe,
  ``&&``, variabili, ecc.

Allo script vengono passate variabili d'ambiente con il contesto:
``HC_SOURCE`` (gesto | audio), ``HC_NAME`` (nome del gesto), ``HC_COUNT`` (numero di colpi),
``HC_MODE`` (mouse | gamepad | paused).
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

WINDOWS = sys.platform == "win32"
URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*:(?!\\)", re.IGNORECASE)   # steam://, https://, ms-settings:
SCRIPT_EXTS = {".py", ".pyw", ".ps1", ".bat", ".cmd", ".vbs", ".js", ".sh"}
OPEN_WITH_ASSOCIATION = {".lnk", ".url", ".txt", ".pdf", ".html", ".htm", ".png", ".jpg",
                         ".mp3", ".mp4", ".docx", ".xlsx"}


@dataclass
class LaunchSpec:
    kind: str                       # "exec" | "shell" | "open"
    argv: list[str] = field(default_factory=list)
    command: str = ""               # per kind == "shell"
    target: str = ""                # per kind == "open"
    cwd: str | None = None
    console: bool = False           # True = lo script usa una console (nascondibile)


def split_command_line(line: str) -> list[str]:
    """Divide una riga di comando rispettando le virgolette (anche con percorsi Windows)."""
    line = line.strip()
    if WINDOWS:
        parts = shlex.split(line, posix=False)
        return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]
    return shlex.split(line)


def _find(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def build_launch(action: dict) -> LaunchSpec:
    """Traduce un'azione run/shell in come avviarla. Solleva ValueError se è vuota."""
    t, value = action.get("type"), str(action.get("value") or "").strip()
    if not value:
        raise ValueError("manca il comando da avviare")
    if t == "shell":
        return LaunchSpec("shell", command=value, console=True)

    if URL_RE.match(value) and not Path(value).exists():
        return LaunchSpec("open", target=value)
    parts = split_command_line(value)
    target, args = os.path.expandvars(os.path.expanduser(parts[0])), parts[1:]
    path = Path(target)
    cwd = str(path.parent) if path.parent != Path(".") and path.parent.exists() else None
    ext = path.suffix.lower()
    if ext in SCRIPT_EXTS and not path.exists():
        raise ValueError(f"file non trovato: {target}")

    if ext in (".py", ".pyw"):
        if WINDOWS:
            interp = _find("pyw" if ext == ".pyw" else "py", "python") or sys.executable
        else:
            interp = _find("python3", "python") or sys.executable
        return LaunchSpec("exec", [interp, target, *args], cwd=cwd, console=ext == ".py")
    if ext == ".ps1":
        shell = _find("pwsh", "powershell") or "powershell"
        return LaunchSpec("exec", [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                   target, *args], cwd=cwd, console=True)
    if ext in (".bat", ".cmd"):
        return LaunchSpec("exec", ["cmd", "/c", target, *args], cwd=cwd, console=True)
    if ext in (".vbs", ".js") and WINDOWS:
        return LaunchSpec("exec", ["wscript", target, *args], cwd=cwd)
    if ext == ".sh" and not WINDOWS:
        return LaunchSpec("exec", ["sh", target, *args], cwd=cwd, console=True)
    if ext in OPEN_WITH_ASSOCIATION and not args:
        return LaunchSpec("open", target=target, cwd=cwd)
    return LaunchSpec("exec", [target, *args], cwd=cwd)


def launch(action: dict, context: dict | None = None) -> str | None:
    """Avvia l'azione senza aspettarne la fine. Restituisce un messaggio d'errore o None."""
    try:
        spec = build_launch(action)
    except ValueError as exc:
        return str(exc)
    env = dict(os.environ)
    for key, val in (context or {}).items():
        if val is not None:
            env[f"HC_{key.upper()}"] = str(val)
    hide = bool(action.get("hidden", False))
    flags = 0
    if WINDOWS:
        if spec.console and hide:
            flags |= subprocess.CREATE_NO_WINDOW
        elif spec.console:
            flags |= subprocess.CREATE_NEW_CONSOLE
    try:
        if spec.kind == "open":
            if WINDOWS:
                os.startfile(spec.target)       # noqa: S606 - scelta esplicita dell'utente
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, spec.target], env=env)
        elif spec.kind == "shell":
            subprocess.Popen(spec.command, shell=True, env=env, creationflags=flags)
        else:
            exe = spec.argv[0]
            if not Path(exe).exists() and not shutil.which(exe):
                return f"programma non trovato: {exe}"
            subprocess.Popen(spec.argv, cwd=spec.cwd, env=env, creationflags=flags)
    except FileNotFoundError:
        return f"non trovato: {action.get('value')}"
    except OSError as exc:
        return f"impossibile avviare {action.get('value')}: {exc}"
    return None
