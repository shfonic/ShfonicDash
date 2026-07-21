import time

import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS

_CLOSE = 0.5            # seconds — gap turns red when within this (no-trend fallback)
_TREND_INTERVAL = 1.0   # seconds between trend samples
_TREND_DEADBAND = 0.03  # seconds — gap change smaller than this counts as holding


class GapTrend:
    """
    Tracks whether a gap is shrinking, holding or growing.

    The gap is sampled once per interval and compared with the previous
    sample; per-frame comparison would flicker because the game's delta
    fields jitter by a few milliseconds.
    """

    def __init__(self, interval: float = _TREND_INTERVAL, deadband: float = _TREND_DEADBAND):
        self._interval = interval
        self._deadband = deadband
        self._sample = None       # (monotonic time, gap) of last sample
        self.direction = 0        # -1 shrinking, 0 holding, +1 growing

    def update(self, value: float) -> None:
        if value <= 0:
            self.direction = 0
            self._sample = None
            return
        now = time.monotonic()
        if self._sample is None:
            self._sample = (now, value)
        elif now - self._sample[0] >= self._interval:
            diff = value - self._sample[1]
            if diff > self._deadband:
                self.direction = 1
            elif diff < -self._deadband:
                self.direction = -1
            else:
                self.direction = 0
            self._sample = (now, value)


def trend_color(value: float, direction: int, closing_is_good: bool) -> tuple:
    """
    Green when the gap moves in the player's favour (closing on the car
    ahead / pulling away from the car behind), amber when it moves against
    them, red-when-close fallback while the gap is holding steady.
    """
    if value <= 0 or direction == 0:
        return DS.RED if 0 < value < _CLOSE else DS.TEXT
    favourable = direction < 0 if closing_is_good else direction > 0
    return DS.GREEN if favourable else DS.AMBER


class GapWidget(Widget):
    """
    Two gap rows (ahead / behind) in chip-style PANEL2 tiles.

    The label shows the first three letters of the other driver's name when
    the telemetry source provides it (name_ahead / name_behind), otherwise
    the generic AHEAD / BEHIND text. Values are trend-coloured.
    """

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self._values = [0.0, 0.0]              # [ahead, behind]
        self._names  = ["", ""]
        self._trends = [GapTrend(), GapTrend()]
        row_h = height // 2
        self._val_font = load_ui(max(14, int(row_h * 0.52)))
        self._lbl_font = load_ui(max(9,  int(row_h * 0.28)))

    def update(self, telemetry) -> None:
        self._names = [
            str(getattr(telemetry, 'name_ahead',  '') or ''),
            str(getattr(telemetry, 'name_behind', '') or ''),
        ]
        for i, value in enumerate((
            float(getattr(telemetry, 'gap_ahead',  0.0)),
            float(getattr(telemetry, 'gap_behind', 0.0)),
        )):
            self._values[i] = value
            self._trends[i].update(value)

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface)

        gap  = 4
        row_h = (self.height - gap) // 2

        for i, (arrow, fallback) in enumerate((("▲", "AHEAD"), ("▼", "BEHIND"))):
            row_y = self.y + i * (row_h + gap)
            tile  = pygame.Rect(self.x + 4, row_y + 2, self.width - 8, row_h - 4)
            DS.draw_panel2(surface, tile, radius=7)

            label = self._names[i][:3].upper() or fallback
            value = self._values[i]
            val_color = trend_color(value, self._trends[i].direction,
                                    closing_is_good=(i == 0))

            # Arrow + label left
            arrow_s = self._lbl_font.render(arrow, True, DS.TEXT4)
            label_s = self._lbl_font.render(label, True, DS.TEXT3)
            surface.blit(arrow_s, (tile.left + 8, tile.centery - arrow_s.get_height() // 2))
            surface.blit(label_s, (tile.left + 8 + arrow_s.get_width() + 5,
                                   tile.centery - label_s.get_height() // 2))

            # Value right-aligned
            val_str = f"+{value:.3f}" if value >= 0 else f"{value:.3f}"
            val_s = self._val_font.render(val_str, True, val_color)
            surface.blit(val_s, val_s.get_rect(midright=(tile.right - 8, tile.centery)))

        surface.set_clip(None)
