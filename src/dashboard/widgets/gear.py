import pygame
from .base import Widget
from .fonts import load_display, load_ui
from . import design_system as DS

_SHIFT_FRAC = 0.94   # RPM fraction above which gear number turns amber


class GearWidget(Widget):
    """
    Large gear indicator using Saira Semi Condensed Bold.

    Colour: white normally, amber when approaching the shift point.
    """

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self.gear    = 'N'
        self._near_shift = False
        self._pit_limiter = False
        font_sz = max(48, int(height * 0.68))
        self._font     = load_display(font_sz)
        self._lbl_font = load_ui(max(11, int(height * 0.09)))

    def update(self, telemetry) -> None:
        self.gear = str(getattr(telemetry, 'gear', 'N'))
        rpm     = int(getattr(telemetry, 'rpm',     0))
        max_rpm = int(getattr(telemetry, 'max_rpm', 8000)) or 8000
        self._near_shift = (rpm / max_rpm) > _SHIFT_FRAC
        self._pit_limiter = bool(getattr(telemetry, 'pit_limiter', False))

    def draw(self, surface: pygame.Surface) -> None:
        self._draw_bg(surface)

        cx = self.x + self.width  // 2
        cy = self.y + self.height // 2 - int(self.height * 0.04)

        gear_color = DS.AMBER if self._near_shift else DS.TEXT
        gear_surf = self._font.render(self.gear, True, gear_color)
        surface.blit(gear_surf, gear_surf.get_rect(center=(cx, cy)))

        if self._pit_limiter:
            bar_h = max(20, int(self.height * 0.20))
            bar_rect = pygame.Rect(self.x, self.y + self.height - bar_h, self.width, bar_h)
            pygame.draw.rect(surface, DS.AMBER, bar_rect)
            pit_surf = self._lbl_font.render('PIT LIMITER', True, DS.CHIP_AMBER[1])
            surface.blit(pit_surf, pit_surf.get_rect(center=bar_rect.center))
        else:
            lbl = self._lbl_font.render('GEAR', True, DS.TEXT3)
            surface.blit(lbl, lbl.get_rect(midbottom=(cx, self.y + self.height - 6)))
