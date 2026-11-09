"""Crea un collegamento sul desktop per avviare Hand Controller (hand-controller --create-shortcut)."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

NAME = "Hand Controller"


def launcher_path() -> Path:
    """Il comando hand-controller installato nello stesso ambiente Python in uso."""
    scripts = Path(sys.executable).parent
    for cand in ("hand-controller.exe", "hand-controller"):
        if (scripts / cand).exists():
            return scripts / cand
    found = shutil.which("hand-controller")
    if found:
        return Path(found)
    raise FileNotFoundError("comando hand-controller non trovato: installa prima il pacchetto "
                            "(pip install -e .)")


def _windows_desktop() -> Path:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "[Environment]::GetFolderPath('Desktop')"],
                         capture_output=True, text=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    return Path(out) if out else Path.home() / "Desktop"


def create_shortcut() -> Path:
    target = launcher_path()
    if sys.platform == "win32":
        lnk = _windows_desktop() / f"{NAME}.lnk"
        ps = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:HC_LNK);"
            "$s.TargetPath = $env:HC_TARGET; $s.WorkingDirectory = $env:USERPROFILE;"
            "$s.Description = 'Mouse e controller Xbox con le mani via webcam';"
            "$s.IconLocation = \"$env:SystemRoot\\System32\\shell32.dll,43\";"
            "$s.WindowStyle = 7; $s.Save()"          # 7 = console ridotta a icona
        )
        env = dict(os.environ, HC_LNK=str(lnk), HC_TARGET=str(target))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return lnk
    if sys.platform == "darwin":
        path = Path.home() / "Desktop" / f"{NAME}.command"
        path.write_text(f'#!/bin/sh\nexec "{target}"\n', encoding="utf-8")
    else:
        entry = (
            "[Desktop Entry]\nType=Application\n"
            f"Name={NAME}\nComment=Mouse e controller Xbox con le mani via webcam\n"
            f'Exec="{target}"\nIcon=input-gaming\nTerminal=false\nCategories=Utility;Game;\n'
        )
        apps = Path.home() / ".local" / "share" / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        (apps / "hand-controller.desktop").write_text(entry, encoding="utf-8")
        desktop = Path(subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True,
                                      text=True).stdout.strip() or Path.home() / "Desktop") \
            if shutil.which("xdg-user-dir") else Path.home() / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        path = desktop / "hand-controller.desktop"
        path.write_text(entry, encoding="utf-8")
        if shutil.which("gio"):     # GNOME: segna il file come attendibile
            subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"],
                           capture_output=True)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path
