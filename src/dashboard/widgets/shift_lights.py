import pygame
from .base import Widget
from . import design_system as DS

_RPM_START_DEFAULT = 0.70
_RPM_SHIFT_DEFAULT = 0.97

_UNLIT = (10, 11, 13)   # very dark glass


def _glow_colors() -> dict:
    """Per-color glow stages (outer, inner) blended against PANEL.

    Computed fresh each call so theme/accent colour changes apply immediately.
    """
    return {
        'g': DS.led_glow_color(DS.GREEN),
        'a': DS.led_glow_color(DS.AMBER),
        'r': DS.led_glow_color(DS.RED),
        'b': DS.led_glow_color(DS.BLUE),
    }


class ShiftLightsWidget(Widget):
    """
    Horizontal row of rectangular LED shift lights.
    Green (left 40%) → amber (middle 32%) → red (right 28%).
    All LEDs flash blue at redline.
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 count: int = 15, rpm_start: float = _RPM_START_DEFAULT,
                 rpm_shift: float = _RPM_SHIFT_DEFAULT):
        super().__init__(x, y, width, height)
        self.rpm       = 0
        self.max_rpm   = 8000
        self.count     = count
        self._rpm_start = rpm_start
        self._rpm_shift = rpm_shift
        self._flash    = False

    def update(self, telemetry) -> None:
        self.rpm     = int(getattr(telemetry, 'rpm', 0))
        self.max_rpm = int(getattr(telemetry, 'max_rpm', 8000)) or 8000
        frac = self._rpm_frac()
        self._flash = frac >= self._rpm_shift

    def draw(self, surface: pygame.Surface) -> None:
        self._draw_bg(surface, radius=4)
        self._draw_leds(surface)

    def _draw_leds(self, surface: pygame.Surface) -> None:
        n      = self.count
        active = self._active_count()
        glow_colors = _glow_colors()

        margin  = 6
        gap     = 4
        usable  = self.width - 2 * margin - gap * (n - 1)
        led_w   = max(4, usable // n)
        led_h   = max(8, int(self.height * 0.55))
        cy      = self.y + self.height // 2

        green_end  = int(n * 0.40)
        amber_end  = int(n * 0.72)

        for i in range(n):
            lx = self.x + margin + i * (led_w + gap)
            rect = pygame.Rect(lx, cy - led_h // 2, led_w, led_h)

            if self._flash:
                color_key = 'b'
            elif i < active:
                color_key = 'g' if i < green_end else ('a' if i < amber_end else 'r')
            else:
                color_key = None

            if color_key:
                color = {'g': DS.GREEN, 'a': DS.AMBER, 'r': DS.RED, 'b': DS.BLUE}[color_key]
                glow  = glow_colors[color_key]
                # Outer glow
                gr = pygame.Rect(rect.x - 3, rect.y - 3, rect.width + 6, rect.height + 6)
                pygame.draw.rect(surface, glow[0], gr, border_radius=5)
                # Inner glow
                gr2 = pygame.Rect(rect.x - 1, rect.y - 1, rect.width + 2, rect.height + 2)
                pygame.draw.rect(surface, glow[1], gr2, border_radius=4)
                # LED face
                pygame.draw.rect(surface, color, rect, border_radius=3)
                # Specular highlight — top-left quarter, very light
                hl_w, hl_h = max(2, led_w // 3), max(2, led_h // 4)
                hl = pygame.Rect(rect.x + 2, rect.y + 2, hl_w, hl_h)
                hl_color = DS._lerp(color, (255, 255, 255), 0.55)
                pygame.draw.rect(surface, hl_color, hl, border_radius=2)
            else:
                pygame.draw.rect(surface, _UNLIT, rect, border_radius=3)

    def _rpm_frac(self) -> float:
        if self.max_rpm <= 0:
            return 0.0
        return max(0.0, min(1.0, self.rpm / self.max_rpm))

    def _active_count(self) -> int:
        frac = self._rpm_frac()
        rpm_start = self._rpm_start
        rpm_shift = self._rpm_shift
        if frac < rpm_start:
            return 0
        if frac >= rpm_shift:
            return self.count
        return max(0, min(self.count,
                          int((frac - rpm_start) / (rpm_shift - rpm_start) * self.count)))
