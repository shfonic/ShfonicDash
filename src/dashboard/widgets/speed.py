import pygame
from .base import Widget
from .fonts import load_display, load_ui
from . import design_system as DS
from . import units


class SpeedWidget(Widget):
    """Large speed readout in Saira Semi Condensed Bold."""

    def __init__(self, x: int, y: int, width: int, height: int, unit: str = 'km/h'):
        super().__init__(x, y, width, height)
        self.speed = 0.0
        # `unit` kwarg kept for config compatibility; the live unit system
        # (see dashboard.widgets.units) controls the displayed unit instead.
        # Saira Semi Condensed renders taller than the point size (≈1.6×).
        # Use 0.40× so speed + unit block fits without clipping.
        self._font      = load_display(max(30, int(height * 0.40)))
        self._unit_font = load_ui(max(13, int(height * 0.16)))

    def update(self, telemetry) -> None:
        self.speed = float(getattr(telemetry, 'speed', 0.0))

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface)

        cx = self.x + self.width // 2

        speed_surf = self._font.render(str(int(units.convert_speed(self.speed))), True, DS.TEXT)
        unit_surf  = self._unit_font.render(units.speed_label().upper(), True, DS.TEXT2)

        # Vertically centre speed+unit as a block
        gap = 3
        block_h = speed_surf.get_height() + gap + unit_surf.get_height()
        top_y   = self.y + (self.height - block_h) // 2

        speed_rect = speed_surf.get_rect(midtop=(cx, top_y))
        unit_rect  = unit_surf.get_rect(midtop=(cx, speed_rect.bottom + gap))
        surface.blit(speed_surf, speed_rect)
        surface.blit(unit_surf,  unit_rect)

        surface.set_clip(None)
