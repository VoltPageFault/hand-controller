"""Ascolto di colpi secchi (battiti di mani, schiocchi di dita) in una finestra di tempo breve.

Il microfono resta spento finché un gesto non apre la finestra di ascolto; dentro la finestra si
contano i colpi e alla fine il numero di colpi sceglie l'azione da eseguire. L'audio viene solo
analizzato in memoria, mai salvato.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

import numpy as np

BLOCK_S = 0.01   # analisi a blocchi di 10 ms


@dataclass
class OnsetDetector:
    """Riconosce attacchi secchi: picco ben sopra il rumore di fondo e salita improvvisa."""

    rise_db: float = 25.0        # quanto sopra il fondo deve arrivare il picco
    jump_db: float = 20.0        # salita minima rispetto al blocco precedente (suono "secco")
    min_level_db: float = -15.0  # livello minimo assoluto (dBFS)
    min_gap_s: float = 0.15      # distanza minima tra due colpi (evita di contare l'eco)
    floor_db: float = -60.0
    _prev_db: float = -120.0
    _last_hit: float = -1e9
    _blocks: int = 0
    events: list = field(default_factory=list)   # (tempo, picco dB, fondo dB)

    def process(self, block: np.ndarray, t: float) -> bool:
        peak = float(np.max(np.abs(block))) if block.size else 0.0
        db = 20.0 * math.log10(peak + 1e-9)
        rms_db = 10.0 * math.log10(float(np.mean(block.astype(np.float64) ** 2)) + 1e-12)
        self._blocks += 1
        hit = (db >= max(self.floor_db + self.rise_db, self.min_level_db)
               and db - self._prev_db >= self.jump_db
               and t - self._last_hit >= self.min_gap_s
               and self._blocks > 5)                 # i primi 50 ms servono a stimare il fondo
        if hit:
            self._last_hit = t
            self.events.append((t, db, self.floor_db))
        elif t - self._last_hit > 0.08:
            # il fondo segue lentamente il rumore della stanza (ma non i colpi)
            a = 0.5 if self._blocks <= 5 else 0.05
            self.floor_db = (1 - a) * self.floor_db + a * rms_db if self._blocks > 1 else rms_db
        self._prev_db = db
        return hit


class ClapListener:
    """Apre il microfono per una finestra di tempo e conta i colpi secchi.

    Uso: ``start()``; poi a ogni frame ``poll()`` restituisce None finché la finestra è aperta,
    e il numero di colpi quando si è chiusa.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.window_s = float(cfg.get("window_s", 3.0))
        self.end_after_silence_s = float(cfg.get("end_after_silence_s", 1.0))
        self._lock = threading.Lock()
        self._stream = None
        self._det: OnsetDetector | None = None
        self._t0 = 0.0
        self._hits: list[float] = []
        self._result: int | None = None
        self.error: str | None = None

    @property
    def active(self) -> bool:
        return self._stream is not None

    def _detector(self) -> OnsetDetector:
        c = self.cfg
        return OnsetDetector(rise_db=float(c.get("rise_db", 25.0)),
                             jump_db=float(c.get("jump_db", 20.0)),
                             min_level_db=float(c.get("min_level_db", -15.0)),
                             min_gap_s=float(c.get("min_gap_ms", 150)) / 1000.0)

    def start(self) -> bool:
        if self.active:
            return True
        try:
            import sounddevice as sd
        except Exception as exc:
            self.error = f"libreria audio mancante: {exc}"
            return False
        device = self.cfg.get("device") or None
        try:
            info = sd.query_devices(device, "input")
            rate = int(info["default_samplerate"])
        except Exception as exc:
            self.error = f"microfono non trovato ({device or 'predefinito'}): {exc}"
            return False
        self._det = self._detector()
        self._hits, self._result, self.error = [], None, None
        self._t0 = time.monotonic()
        block = max(1, int(rate * BLOCK_S))

        def callback(indata, frames, time_info, status):
            t = time.monotonic()
            mono = indata[:, 0] if indata.ndim > 1 else indata
            with self._lock:
                if self._det is not None and self._det.process(mono, t - self._t0):
                    self._hits.append(t)

        try:
            self._stream = sd.InputStream(device=device, channels=1, samplerate=rate,
                                          blocksize=block, dtype="float32", callback=callback)
            self._stream.start()
        except Exception as exc:
            self._stream = None
            self.error = f"impossibile aprire il microfono: {exc}"
            return False
        return True

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def status(self, now: float | None = None) -> tuple[float, int]:
        """(frazione di tempo rimasta 0..1, colpi finora) per l'overlay."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = len(self._hits)
        return max(0.0, 1.0 - (now - self._t0) / self.window_s), hits

    def poll(self, now: float | None = None) -> int | None:
        """Numero di colpi quando la finestra è finita; None mentre è ancora aperta."""
        if not self.active:
            r, self._result = self._result, None
            return r
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = list(self._hits)
        timeout = now - self._t0 >= self.window_s
        # dopo l'ultimo colpo, un po' di silenzio chiude la finestra senza aspettare la fine
        settled = hits and now - hits[-1] >= self.end_after_silence_s
        if timeout or settled:
            self.stop()
            return len(hits)
        return None

    @property
    def events(self) -> list:
        with self._lock:
            return list(self._det.events) if self._det else []


def list_input_devices() -> list[str]:
    """Nomi dei microfoni disponibili (API WASAPI su Windows, per evitare i doppioni)."""
    try:
        import sounddevice as sd
        apis = sd.query_hostapis()
        preferred = next((i for i, a in enumerate(apis) if a["name"] == "Windows WASAPI"), None)
        names = []
        for d in sd.query_devices():
            if d["max_input_channels"] > 0 and (preferred is None or d["hostapi"] == preferred):
                if d["name"] not in names:
                    names.append(d["name"])
        return names
    except Exception:
        return []
