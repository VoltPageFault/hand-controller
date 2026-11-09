"""Cattura webcam su thread dedicato: il loop principale legge sempre l'ultimo fotogramma."""
from __future__ import annotations

import sys
import threading
import time

import cv2
import numpy as np


BACKENDS = {"msmf": cv2.CAP_MSMF, "dshow": cv2.CAP_DSHOW, "any": cv2.CAP_ANY}


def backend_order(preferred: str = "auto") -> list[str]:
    """Ordine dei sistemi di acquisizione da provare. Su Windows Media Foundation è più fluido."""
    if sys.platform != "win32":
        return ["any"]
    if preferred in ("msmf", "dshow"):
        return [preferred, "dshow" if preferred == "msmf" else "msmf"]
    return ["msmf", "dshow"]


def open_camera(cam: dict, prefer: str | None = None) -> "Camera":
    """Apre la webcam provando i sistemi di acquisizione in ordine (riserva se uno fallisce)."""
    order = backend_order(prefer or cam.get("backend", "auto"))
    last: Exception | None = None
    for name in order:
        try:
            return Camera(cam["index"], cam["width"], cam["height"], cam["fps"], cam["mirror"],
                          cam.get("exposure"), backend=name)
        except RuntimeError as exc:
            last = exc
    raise last or RuntimeError("webcam non disponibile")


class Camera:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480, fps: int = 30,
                 mirror: bool = True, exposure: float | None = None, backend: str = "dshow"):
        self.mirror = mirror
        self.backend = backend if sys.platform == "win32" else "any"
        self._cap = cv2.VideoCapture(index, BACKENDS.get(self.backend, cv2.CAP_ANY))
        if not self._cap.isOpened():
            raise RuntimeError(f"Impossibile aprire la webcam {index} ({self.backend})")
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_FPS, fps)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if exposure is not None:
            # Con poca luce l'esposizione automatica abbassa gli fps: fissarla li mantiene a 30.
            self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
            self._cap.set(cv2.CAP_PROP_EXPOSURE, exposure)

        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_id = 0
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            if self.mirror:
                frame = cv2.flip(frame, 1)
            with self._lock:
                self._frame = frame
                self._frame_id += 1

    def read(self, last_id: int = -1, timeout: float = 1.0) -> tuple[int, np.ndarray | None]:
        """Restituisce (id, frame) appena disponibile un fotogramma più recente di last_id."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._frame is not None and self._frame_id != last_id:
                    return self._frame_id, self._frame
            time.sleep(0.002)
        return last_id, None

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=1.0)
        self._cap.release()
