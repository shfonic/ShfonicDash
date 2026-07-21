import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS

_WARN_LAPS = 3.0
_CRIT_LAPS = 1.5


class FuelWidget(Widget):
    """
    Fuel remaining: label row (FUEL / kg value) + bar + laps remaining.
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 show_laps: bool = True):
        super().__init__(x, y, width, height)
        self._show_laps = show_laps
        self._fuel     = 0.0
        self._capacity = 100.0
        self._laps     = 0.0

        self._lbl_font = load_ui(max(9,  int(height * 0.16)))
        self._val_font = load_ui(max(14, int(height * 0.26)))

    def update(self, telemetry) -> None:
        self._fuel     = float(getattr(telemetry, 'fuel_remaining',      0.0))
        self._capacity = float(getattr(telemetry, 'fuel_capacity',       100.0)) or 100.0
        self._laps     = float(getattr(telemetry, 'fuel_laps_remaining', 0.0))

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface)

        pad   = 8
        cx    = self.x + self.width // 2
        color = self._value_color()

        lbl_h  = self._lbl_font.get_height()
        val_h  = self._val_font.get_height()
        bar_h  = max(8, int(self.height * 0.16))
        laps_h = lbl_h if self._show_laps else 0

        # FUEL label and value share one row, so content is val_h (not lbl_h + val_h)
        content = val_h + 6 + bar_h + (6 + laps_h if self._show_laps else 0)
        top     = self.y + max(4, (self.height - content) // 2)

        # "FUEL" label bottom-left, number + "kg" share the same baseline on the right
        lbl_s  = self._lbl_font.render("FUEL", True, DS.TEXT3)
        val_s  = self._val_font.render(f"{self._fuel:.1f}", True, color)
        unit_s = self._lbl_font.render("kg", True, DS.TEXT3)

        val_bottom = top + val_h   # shared baseline
        surface.blit(val_s,  val_s.get_rect(bottomright=(self.x + self.width - pad, val_bottom)))
        surface.blit(unit_s, unit_s.get_rect(bottomright=(
            self.x + self.width - pad - val_s.get_width() - 4, val_bottom)))
        surface.blit(lbl_s,  lbl_s.get_rect(bottomleft=(self.x + pad, val_bottom)))
        top += val_h + 6

        # Bar
        bar_rect = pygame.Rect(self.x + pad, top, self.width - pad * 2, bar_h)
        DS.draw_bar_h(surface, bar_rect, self._fuel / self._capacity, self._bar_color())
        top += bar_h + 6

        # Laps remaining
        if self._show_laps:
            laps_s = self._lbl_font.render(f"{self._laps:.1f}  LAPS", True, color)
            surface.blit(laps_s, laps_s.get_rect(midtop=(cx, top)))

        surface.set_clip(None)

    def _bar_color(self):
        if self._laps <= _CRIT_LAPS: return DS.RED
        if self._laps <= _WARN_LAPS: return DS.AMBER
        return DS.AMBER

    def _value_color(self):
        if self._laps <= _CRIT_LAPS: return DS.RED
        if self._laps <= _WARN_LAPS: return DS.AMBER
        return DS.TEXT
