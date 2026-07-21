import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS


class AeroWidget(Widget):
    """
    F1 2026 Active Aero / S Mode indicator.

    S Mode chip:
        not available  — dimmed  "–"
        available      — amber   "AVAIL"  (in zone, corner mode)
        active/ON      — blue    "ON"     (straight mode engaged)

    BOOST chip only appears when boost (MOR/Overtake) is actively deployed.
    """

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self._aero_mode      = ""
        self._aero_available = False
        self._boost_active   = False

        self._lbl_font  = load_ui(max(9,  int(height * 0.14)))
        self._mode_font = load_ui(max(12, int(height * 0.22)))
        self._chip_font = load_ui(max(9,  int(height * 0.16)))

    def update(self, telemetry) -> None:
        self._aero_mode      = getattr(telemetry, 'active_aero_mode',      "")
        self._aero_available = bool(getattr(telemetry, 'active_aero_available', False))
        self._boost_active   = bool(getattr(telemetry, 'boost_active',          False))

    def draw(self, surface: pygame.Surface) -> None:
        self._draw_bg(surface)

        pad  = 6
        cx   = self.x + self.width // 2
        chip_w = self.width - pad * 2
        straight = (self._aero_mode == "straight")

        # ── "S MODE" label ────────────────────────────────────────────────────
        lbl = self._lbl_font.render("S MODE", True, DS.TEXT3)
        surface.blit(lbl, lbl.get_rect(midtop=(cx, self.y + pad + 2)))
        lbl_bot = self.y + pad + 2 + lbl.get_height()

        # ── S Mode chip ───────────────────────────────────────────────────────
        chip_h   = max(22, int(self.height * 0.30))
        chip_top = lbl_bot + 4
        mode_rect = pygame.Rect(self.x + pad, chip_top, chip_w, chip_h)

        if straight:
            DS.draw_chip(surface, mode_rect, "ON",    self._mode_font, state=DS.CHIP_BLUE)
        elif self._aero_available:
            DS.draw_chip(surface, mode_rect, "AVAIL", self._mode_font, state=DS.CHIP_AMBER)
        else:
            DS.draw_chip(surface, mode_rect, "–",     self._mode_font, state=None)

        # ── Boost chip (only when actively deployed) ──────────────────────────
        if self._boost_active:
            boost_h   = max(16, int(self.height * 0.24))
            boost_top = self.y + self.height - boost_h - pad
            boost_rect = pygame.Rect(self.x + pad, boost_top, chip_w, boost_h)
            DS.draw_chip(surface, boost_rect, "BOOST >", self._chip_font, state=DS.CHIP_AMBER)
