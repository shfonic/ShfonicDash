import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS

_SEGMENTS = 20
_SEG_GAP  = 2


class PedalsWidget(Widget):
    """Throttle / brake vertical segmented bar pair."""

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self.throttle    = 0.0
        self.brake       = 0.0
        self._label_font = load_ui(max(9, int(height * 0.09)))

    def update(self, telemetry) -> None:
        self.throttle = float(getattr(telemetry, 'throttle', 0.0))
        self.brake    = float(getattr(telemetry, 'brake',    0.0))

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface)

        pad     = 8
        lbl_h   = self._label_font.get_height() + 3
        bar_top = self.y + pad + lbl_h
        bar_h   = self.height - pad * 2 - lbl_h
        bar_w   = max(8, (self.width - pad * 3) // 2)

        thr_x = self.x + pad
        brk_x = self.x + pad * 2 + bar_w

        self._draw_bar(surface, thr_x, bar_top, bar_w, bar_h, self.throttle, DS.GREEN)
        self._draw_bar(surface, brk_x, bar_top, bar_w, bar_h, self.brake,    DS.RED)

        for label, cx_lbl in (('THR', thr_x + bar_w // 2), ('BRK', brk_x + bar_w // 2)):
            lbl = self._label_font.render(label, True, DS.TEXT3)
            surface.blit(lbl, lbl.get_rect(midbottom=(cx_lbl, bar_top - 2)))

        surface.set_clip(None)

    def _draw_bar(self, surface, x, y, w, h, value, on_color):
        active = int(max(0.0, min(1.0, value)) * _SEGMENTS)
        seg_h  = max(2, int((h - (_SEGMENTS - 1) * _SEG_GAP) / _SEGMENTS))
        # When seg_h is clamped to minimum, reduce gap so segments don't overflow bar_h
        gap    = _SEG_GAP if seg_h > 2 else max(0, (h - _SEGMENTS * seg_h) // max(1, _SEGMENTS - 1))
        for i in range(_SEGMENTS):
            sy   = y + h - (i + 1) * seg_h - i * gap
            rect = pygame.Rect(x, sy, w, seg_h)
            color = on_color if i < active else DS.INSET
            pygame.draw.rect(surface, color, rect, border_radius=1)
