"""Interfacce astratte dei dispositivi virtuali. Ogni piattaforma fornisce un'implementazione."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Nomi pulsanti indipendenti dalla piattaforma (layout Xbox)
BUTTONS = (
    "A", "B", "X", "Y", "LB", "RB", "BACK", "START", "GUIDE", "LS", "RS",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
)
TRIGGERS = ("LT", "RT")


@dataclass
class PadState:
    lx: float = 0.0   # stick in [-1, 1], y positivo = su
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    lt: float = 0.0   # grilletti in [0, 1]
    rt: float = 0.0
    buttons: set[str] = field(default_factory=set)


class GamepadBackend(ABC):
    name = "abstract"

    @abstractmethod
    def send(self, state: PadState) -> None: ...

    def reset(self) -> None:
        self.send(PadState())

    def close(self) -> None:
        self.reset()


class MouseBackend(ABC):
    name = "abstract"

    @abstractmethod
    def screen_size(self) -> tuple[int, int]: ...

    @abstractmethod
    def move_to(self, x: int, y: int) -> None: ...

    @abstractmethod
    def press(self, button: str) -> None: ...   # "left" | "right" | "middle"

    @abstractmethod
    def release(self, button: str) -> None: ...

    @abstractmethod
    def scroll(self, dy: int) -> None: ...      # positivo = su

    def click(self, button: str) -> None:
        self.press(button)
        self.release(button)

    def close(self) -> None:
        pass
