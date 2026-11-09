"""Cattura webcam su thread dedicato: il loop principale legge sempre l'ultimo fotogramma."""
from __future__ import annotations

import sys
import threading
import time

import cv2
import numpy as np


class Camera:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480, fps: int = 30,
                 mirror: bool = True, exposure: float | None = None):
        self.mirror = mirror
        api = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(index, api)
        if not self._cap.isOpened():
            self._cap = cv2.VideoCapture(index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Impossibile aprire la webcam con indice {index}")
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
