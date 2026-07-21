import pygame
from .base import Widget
from .fonts import load_display, load_ui
from . import design_system as DS


class PositionWidget(Widget):
    """Race position: large 'P3' with optional '/ 20' below."""

    def __init__(self, x: int, y: int, width: int, height: int,
                 show_total: bool = True):
        super().__init__(x, y, width, height)
        self._show_total = show_total
        self._position   = 0
        self._total      = 0
        self._pos_font   = load_display(max(28, int(height * 0.50)))
        self._sub_font   = load_ui(max(10, int(height * 0.20)))
        self._lbl_font   = load_ui(max(9,  int(height * 0.15)))

    def update(self, telemetry) -> None:
        self._position = int(getattr(telemetry, 'position',   0))
        self._total    = int(getattr(telemetry, 'total_cars', 0))

    def draw(self, surface: pygame.Surface) -> None:
        self._draw_bg(surface)

        cx = self.x + self.width  // 2
        cy = self.y + self.height // 2

        lbl = self._lbl_font.render("POS", True, DS.TEXT3)
        surface.blit(lbl, lbl.get_rect(midtop=(cx, self.y + 4)))

        total_str = f"/ {self._total}" if (self._show_total and self._total > 0) else ""
        tot_surf  = self._sub_font.render(total_str, True, DS.TEXT3) if total_str else None

        # Reserve label space at top and total space at bottom; number fills the middle
        top_reserve = lbl.get_height() + 4
        bot_reserve = (tot_surf.get_height() + 4) if tot_surf else 0
        num_cy = self.y + top_reserve + (self.height - top_reserve - bot_reserve) // 2

        pos_str  = str(self._position) if self._position > 0 else "–"
        pos_surf = self._pos_font.render(pos_str, True, DS.TEXT)
        surface.blit(pos_surf, pos_surf.get_rect(center=(cx, num_cy)))

        if tot_surf:
            surface.blit(tot_surf, tot_surf.get_rect(midbottom=(cx, self.y + self.height - 4)))
