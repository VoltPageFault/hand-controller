"""Backend fittizi: non producono input reale, utili per test e per piattaforme non supportate."""
from __future__ import annotations

from .base import GamepadBackend, MouseBackend, PadState


class NullGamepadBackend(GamepadBackend):
    name = "null"

    def __init__(self):
        self.last = PadState()

    def send(self, state: PadState) -> None:
        self.last = state


class NullMouseBackend(MouseBackend):
    name = "null"

    def __init__(self, size: tuple[int, int] = (1920, 1080)):
        self._size = size
        self.position = (0, 0)
        self.events: list[tuple] = []

    def screen_size(self) -> tuple[int, int]:
        return self._size

    def move_to(self, x: int, y: int) -> None:
        self.position = (x, y)

    def press(self, button: str) -> None:
        self.events.append(("press", button))

    def release(self, button: str) -> None:
        self.events.append(("release", button))

    def scroll(self, dy: int) -> None:
        self.events.append(("scroll", dy))
