import pygame
from .base import Widget
from .fonts import load_display, load_ui
from . import design_system as DS


class RPMGaugeWidget(Widget):
    """
    RPM numeric readout + thin horizontal progress bar.

    Bar color progresses green → amber → red as RPM climbs.
    """

    def __init__(self, x: int, y: int, width: int, height: int, **_):
        super().__init__(x, y, width, height)
        self.rpm     = 0
        self.max_rpm = 8000
        font_h = max(20, int(min(height * 0.46, width * 0.15)))
        self._val_font = load_display(font_h)
        self._lbl_font = load_ui(max(10, int(height * 0.12)))

    def update(self, telemetry) -> None:
        self.rpm     = int(getattr(telemetry, 'rpm',     0))
        self.max_rpm = int(getattr(telemetry, 'max_rpm', 8000)) or 8000

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface)

        cx    = self.x + self.width  // 2
        frac  = max(0.0, min(1.0, self.rpm / self.max_rpm))

        # Color: green below 70%, amber 70–90%, red above
        if frac < 0.70:
            bar_color = DS.GREEN
        elif frac < 0.90:
            bar_color = DS.AMBER
        else:
            bar_color = DS.RED

        lbl = self._lbl_font.render('RPM', True, DS.TEXT3)
        val = self._val_font.render(f'{self.rpm:,}', True, DS.TEXT)

        bar_h   = max(6, int(self.height * 0.08))
        pad     = 10
        content_h = lbl.get_height() + 4 + val.get_height() + 8 + bar_h
        top = self.y + (self.height - content_h) // 2

        surface.blit(lbl, lbl.get_rect(midtop=(cx, top)))
        top += lbl.get_height() + 4

        surface.blit(val, val.get_rect(midtop=(cx, top)))
        top += val.get_height() + 8

        bar_rect = pygame.Rect(self.x + pad, top, self.width - pad * 2, bar_h)
        DS.draw_bar_h(surface, bar_rect, frac, bar_color)

        surface.set_clip(None)
