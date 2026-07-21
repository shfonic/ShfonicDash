import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS

# flag → (chip state attr name on DS, label)
_FLAGS = {
    "green":     ("CHIP_GREEN",  "TRACK CLEAR"),
    "yellow":    ("CHIP_AMBER",  "YELLOW"),
    "red":       ("CHIP_RED",    "RED FLAG"),
    "blue":      ("CHIP_BLUE",   "LET BY"),
    "sc":        ("CHIP_AMBER",  "SAFETY CAR"),
    "vsc":       ("CHIP_AMBER",  "VIRTUAL SC"),
    "chequered": (None,          "FINAL LAP"),
}

_FLASH_RATE  = 4
_FLASH_FLAGS = {"red", "sc"}


class FlagWidget(Widget):
    """
    Racing flag chip — invisible when no flag is active.
    Flashes for red flag and safety car.
    """

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self._flag       = ""
        self._safety_car = ""
        self._tick       = 0
        self._font       = load_ui(max(11, int(height * 0.36)))

    def update(self, telemetry) -> None:
        self._flag       = getattr(telemetry, 'flag',       "")
        self._safety_car = getattr(telemetry, 'safety_car', "")

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)

        key = self._safety_car if self._safety_car else self._flag
        if not key or key not in _FLAGS:
            surface.set_clip(None)
            return

        self._tick = (self._tick + 1) % (_FLASH_RATE * 2)
        flash_visible = key not in _FLASH_FLAGS or self._tick < _FLASH_RATE

        state_attr, label = _FLAGS[key]
        state = getattr(DS, state_attr) if state_attr else None
        rect = pygame.Rect(self.x, self.y, self.width, self.height)

        if flash_visible:
            DS.draw_chip(surface, rect, label, self._font, state=state, dot=True)
        else:
            DS.draw_chip(surface, rect, label, self._font, state=None, dot=True)

        surface.set_clip(None)
