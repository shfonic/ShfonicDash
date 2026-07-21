import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS

_BAR_W = 40
_BAR_H = 6


def _fmt_lap(seconds: float) -> str:
    if seconds <= 0:
        return "--:--.---"
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:06.3f}"


def _fmt_sector(seconds: float) -> str:
    if seconds <= 0:
        return "–"
    t = seconds
    if t >= 60.0:
        return f"{int(t // 60)}:{t % 60:06.3f}"
    return f"{t:06.3f}"


class LapListWidget(Widget):
    """Scrolling lap history for practice / hotlap mode."""

    _COL_LAP  = 0.10
    _COL_TIME = 0.36
    _COL_S    = 0.18
    # With tyre chips the LAP cell widens and TIME gives up the space
    # (companion parity: the chip lives in the LAP cell, no new column).
    _COL_LAP_TYRE  = 0.17
    _COL_TIME_TYRE = 0.29

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self._session = None   # SessionHistory — set via set_session()

        row_sz = max(11, int(height * 0.11))
        hdr_sz = max(9,  int(height * 0.09))
        self._row_font = load_ui(row_sz)
        self._hdr_font = load_ui(hdr_sz)
        self._sec_font = load_ui(max(9, int(height * 0.095)))

    def _cols(self, has_tyre: bool = False):
        pad    = 8
        uw     = self.width - pad * 2
        lap_w  = int(uw * (self._COL_LAP_TYRE if has_tyre else self._COL_LAP))
        time_w = int(uw * (self._COL_TIME_TYRE if has_tyre else self._COL_TIME))
        s_w    = int(uw * self._COL_S)
        lap_cx  = self.x + pad + lap_w  // 2
        time_cx = self.x + pad + lap_w  + time_w // 2
        s1_cx   = self.x + pad + lap_w  + time_w + s_w // 2
        s2_cx   = s1_cx + s_w
        s3_cx   = s2_cx + s_w
        return lap_cx, time_cx, s1_cx, s2_cx, s3_cx

    def set_session(self, session) -> None:
        self._session = session

    def update(self, telemetry) -> None:
        pass  # all lap accumulation lives in SessionHistory (core.lap_tracker)

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface)

        pad  = 8
        y    = self.y + pad
        source   = self._session.laps if self._session is not None else []
        has_tyre = any(l.get('compound') for l in source)
        lap_cx, time_cx, s1_cx, s2_cx, s3_cx = self._cols(has_tyre)

        # Header
        for text, cx in (("LAP", lap_cx), ("TIME", time_cx),
                         ("S1", s1_cx), ("S2", s2_cx), ("S3", s3_cx)):
            s = self._hdr_font.render(text, True, DS.TEXT3)
            surface.blit(s, s.get_rect(midtop=(cx, y)))

        y += self._hdr_font.get_height() + 3
        pygame.draw.line(surface, DS.BORDER,
                         (self.x + pad, y), (self.x + self.width - pad, y))
        y += 4

        row_h   = self._row_font.get_height() + 2
        visible = max(1, (self.y + self.height - y - pad) // row_h)
        laps    = source[:visible]

        # Current bests — recomputed each frame so colors update retroactively
        valid_times = [l['time'] for l in laps if not l['invalid'] and l['time'] > 0]
        best_time   = min(valid_times) if valid_times else 0.0

        def _best(key):
            vals = [l[key] for l in laps if l[key] > 0]
            return min(vals) if vals else 0.0

        best_s1 = _best('s1_t')
        best_s2 = _best('s2_t')
        best_s3 = _best('s3_t')

        def _sector_color(val: float, best: float) -> tuple:
            if val <= 0 or best <= 0:
                return DS.TEXT4
            return DS.PURPLE if abs(val - best) < 0.001 else DS.TEXT

        for lap in laps:
            n = self._row_font.render(str(lap['num']), True, DS.TEXT3)
            surface.blit(n, n.get_rect(midtop=(lap_cx, y)))
            if lap.get('compound'):
                from .tyre_chip import draw_chip
                draw_chip(surface, self._hdr_font, lap['compound'],
                          lap_cx + n.get_width() // 2 + 5, y + row_h // 2 - 1)

            if lap['invalid']:
                time_color = DS.RED
            elif best_time > 0 and abs(lap['time'] - best_time) < 0.001:
                time_color = DS.PURPLE
            else:
                time_color = DS.TEXT

            t = self._row_font.render(_fmt_lap(lap['time']), True, time_color)
            surface.blit(t, t.get_rect(midtop=(time_cx, y)))

            for time_key, best, cx in (
                ('s1_t', best_s1, s1_cx),
                ('s2_t', best_s2, s2_cx),
                ('s3_t', best_s3, s3_cx),
            ):
                t_val = lap.get(time_key, 0.0)
                color = _sector_color(t_val, best)
                if t_val > 0:
                    ts = self._sec_font.render(_fmt_sector(t_val), True, color)
                    surface.blit(ts, ts.get_rect(midtop=(cx, y)))
                else:
                    mid_y = y + row_h // 2
                    rect  = pygame.Rect(cx - _BAR_W // 2, mid_y - _BAR_H // 2, _BAR_W, _BAR_H)
                    pygame.draw.rect(surface, color, rect, border_radius=3)

            y += row_h

        surface.set_clip(None)
