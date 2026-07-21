import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS
from . import units

_LABELS = ["FL", "FR", "RL", "RR"]
_GRID   = [(0, 0), (1, 0), (0, 1), (1, 1)]
_HEAT_H = 3   # heat strip at the bottom of each tyre cell

_COMPOUND_COLORS = {
    "soft":        (255,  59,  48),
    "medium":      (255, 179,   0),
    "hard":        (243, 245, 248),
    "super soft":  (160,  90, 255),
    "hyper soft":  (160,  90, 255),
    "inter":       ( 47, 224, 122),
    "wet":         ( 46, 155, 255),
}

def _compound_color(compound: str) -> tuple:
    return _COMPOUND_COLORS.get(compound.lower(), DS.TEXT3)


class TyreWidget(Widget):
    """
    2×2 tyre grid.

    Each cell: PANEL2 background, temperature coloured value, optional PSI,
    a heat strip at the bottom (cold=blue → optimal=green → amber → hot=red),
    and a corner tag (FL/FR/RL/RR).
    Compound label centred below the grid.
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 show_pressure: bool = True,
                 cold_temp: float = 70.0,
                 hot_temp: float  = 115.0):
        super().__init__(x, y, width, height)
        self._show_pressure = show_pressure
        self._cold     = cold_temp
        self._hot      = hot_temp
        self._temps     = [0.0] * 4
        self._pressures = [0.0] * 4
        self._compound  = ""

        cell_h = height // 2
        self._temp_font = load_ui(max(13, int(cell_h * 0.34)))
        self._lbl_font  = load_ui(max(8,  int(cell_h * 0.18)))
        self._cmp_font  = load_ui(max(11, int(height * 0.10)))

    def update(self, telemetry) -> None:
        self._temps     = list(getattr(telemetry, 'tyre_temp',     (0, 0, 0, 0)))
        self._pressures = list(getattr(telemetry, 'tyre_pressure', (0, 0, 0, 0)))
        self._compound  = getattr(telemetry, 'tyre_compound', '')

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface)

        # Compound label at top
        cmp_h = 0
        if self._compound:
            cmp = self._cmp_font.render(self._compound, True, _compound_color(self._compound))
            surface.blit(cmp, cmp.get_rect(midtop=(self.x + self.width // 2, self.y + 3)))
            cmp_h = cmp.get_height() + 3

        grid_top = self.y + cmp_h
        cell_w   = self.width  // 2
        cell_h   = (self.height - cmp_h) // 2
        pad      = 4

        for i, (col, row) in enumerate(_GRID):
            cx = self.x + col * cell_w
            cy = grid_top + row * cell_h
            temp  = self._temps[i]
            # Heat-strip/value colour is keyed off the raw °C value regardless
            # of display units (cold_temp/hot_temp thresholds are °C-based).
            color = DS.temp_color(temp, self._cold, self._hot)

            cell = pygame.Rect(cx + pad, cy + pad, cell_w - pad * 2, cell_h - pad * 2)
            DS.draw_panel2(surface, cell, radius=5)

            # Corner tag — top-left
            tag = self._lbl_font.render(_LABELS[i], True, DS.TEXT4)
            surface.blit(tag, (cell.left + 3, cell.top + 2))

            # Temperature
            temp_str = f"{units.convert_temp(temp):.0f}°"
            t_surf = self._temp_font.render(temp_str, True, color)

            if self._show_pressure:
                p_disp = units.convert_pressure(self._pressures[i])
                p_fmt  = "{:.2f}" if units.get_unit_system() == "metric" else "{:.1f}"
                p_str  = p_fmt.format(p_disp)
                p_surf = self._lbl_font.render(p_str, True, DS.TEXT3)
                gap    = 1
                total  = t_surf.get_height() + gap + p_surf.get_height()
                t_y    = cell.centery - total // 2
                surface.blit(t_surf, t_surf.get_rect(centerx=cell.centerx, top=t_y))
                surface.blit(p_surf, p_surf.get_rect(centerx=cell.centerx,
                                                      top=t_y + t_surf.get_height() + gap))
            else:
                # Shift text up slightly to leave room for heat strip
                surface.blit(t_surf, t_surf.get_rect(center=(cell.centerx,
                                                               cell.centery - _HEAT_H)))

            # Heat strip at the very bottom of the cell
            heat = pygame.Rect(cell.left, cell.bottom - _HEAT_H, cell.width, _HEAT_H)
            pygame.draw.rect(surface, color, heat)

        surface.set_clip(None)
