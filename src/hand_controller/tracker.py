"""Tracciamento mani con MediaPipe Hand Landmarker (Tasks API)."""
from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")
DEFAULT_MODEL_PATH = Path.home() / ".cache" / "hand_controller" / "hand_landmarker.task"

# Connessioni tra i 21 landmark (per il disegno dell'overlay)
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]


@dataclass
class Hand:
    label: str            # "Left" | "Right" (mano reale dell'utente)
    landmarks: np.ndarray  # (21, 3): x, y normalizzati [0,1] sul fotogramma, z relativo
    score: float


def ensure_model(path: str | Path | None) -> Path:
    p = Path(path).expanduser() if path else DEFAULT_MODEL_PATH
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        print(f"[tracker] Download modello in {p} ...")
        tmp = p.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, tmp)
        tmp.replace(p)
    return p


class HandTracker:
    def __init__(self, cfg: dict, mirrored: bool = True):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        # MediaPipe assume un'immagine specchiata: se non lo è, le etichette vanno invertite.
        self._swap_labels = not mirrored
        model = ensure_model(cfg.get("model_path"))
        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=cfg.get("max_hands", 2),
            min_hand_detection_confidence=cfg.get("min_detection_confidence", 0.6),
            min_hand_presence_confidence=cfg.get("min_presence_confidence", 0.5),
            min_tracking_confidence=cfg.get("min_tracking_confidence", 0.5),
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_ts = -1

    def process(self, frame_bgr: np.ndarray, timestamp_ms: int) -> list[Hand]:
        ts = max(int(timestamp_ms), self._last_ts + 1)  # deve essere strettamente crescente
        self._last_ts = ts
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, ts)

        hands: list[Hand] = []
        for lms, handed in zip(result.hand_landmarks, result.handedness):
            label = handed[0].category_name
            if self._swap_labels:
                label = "Left" if label == "Right" else "Right"
            arr = np.array([[lm.x, lm.y, lm.z] for lm in lms], dtype=np.float64)
            hands.append(Hand(label=label, landmarks=arr, score=handed[0].score))

        # Se entrambe le mani ricevono la stessa etichetta, assegna per posizione orizzontale
        if len(hands) == 2 and hands[0].label == hands[1].label:
            hands.sort(key=lambda h: h.landmarks[0, 0])
            hands[0].label, hands[1].label = "Left", "Right"
        return hands

    def close(self) -> None:
        self._landmarker.close()
