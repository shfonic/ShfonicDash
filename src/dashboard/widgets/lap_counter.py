import pygame
from .base import Widget
from .fonts import load_display, load_ui
from . import design_system as DS


class LapCounterWidget(Widget):
    """Current lap number with optional total laps below."""

    def __init__(self, x: int, y: int, width: int, height: int,
                 show_total: bool = False):
        super().__init__(x, y, width, height)
        self._show_total  = show_total
        self._lap_number  = 0
        self._total_laps  = 0
        self._num_font    = load_display(max(28, int(height * 0.50)))
        self._sub_font    = load_ui(max(10, int(height * 0.20)))
        self._lbl_font    = load_ui(max(9,  int(height * 0.15)))

    def update(self, telemetry) -> None:
        self._lap_number = int(getattr(telemetry, 'lap_number',  0))
        self._total_laps = int(getattr(telemetry, 'total_laps',  0))

    def draw(self, surface: pygame.Surface) -> None:
        self._draw_bg(surface)

        cx = self.x + self.width  // 2

        lbl = self._lbl_font.render("LAP", True, DS.TEXT3)
        surface.blit(lbl, lbl.get_rect(midtop=(cx, self.y + 4)))

        total_str = f"/ {self._total_laps}" if (self._show_total and self._total_laps > 0) else ""
        tot_surf  = self._sub_font.render(total_str, True, DS.TEXT3) if total_str else None

        top_reserve = lbl.get_height() + 4
        bot_reserve = (tot_surf.get_height() + 4) if tot_surf else 0
        num_cy = self.y + top_reserve + (self.height - top_reserve - bot_reserve) // 2

        num_str  = str(self._lap_number) if self._lap_number > 0 else "–"
        num_surf = self._num_font.render(num_str, True, DS.TEXT)
        surface.blit(num_surf, num_surf.get_rect(center=(cx, num_cy)))

        if tot_surf:
            surface.blit(tot_surf, tot_surf.get_rect(midbottom=(cx, self.y + self.height - 4)))
