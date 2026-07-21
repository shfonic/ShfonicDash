import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS


class DRSWidget(Widget):
    """
    DRS indicator as a chip.

    Unavailable → idle chip.
    Available   → CHIP_AMBER.
    Active      → CHIP_GREEN.
    """

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self._available = False
        self._active    = False
        self._lbl_font  = load_ui(max(9,  int(height * 0.16)))
        self._chip_font = load_ui(max(12, int(height * 0.28)))

    def update(self, telemetry) -> None:
        self._available = bool(getattr(telemetry, 'drs_available', False))
        self._active    = bool(getattr(telemetry, 'drs_active',    False))

    def draw(self, surface: pygame.Surface) -> None:
        self._draw_bg(surface)

        pad = 6
        cx  = self.x + self.width // 2

        lbl = self._lbl_font.render("DRS", True, DS.TEXT3)
        surface.blit(lbl, lbl.get_rect(midtop=(cx, self.y + pad)))

        chip_h = max(22, int(self.height * 0.44))
        chip_w = self.width - pad * 2
        chip_y = self.y + self.height // 2 - chip_h // 2 + 4
        chip   = pygame.Rect(self.x + pad, chip_y, chip_w, chip_h)

        if self._active:
            state = DS.CHIP_GREEN
            text  = "OPEN >"
        elif self._available:
            state = DS.CHIP_AMBER
            text  = "AVAIL"
        else:
            state = None
            text  = "OFF"

        DS.draw_chip(surface, chip, text, self._chip_font, state=state)
