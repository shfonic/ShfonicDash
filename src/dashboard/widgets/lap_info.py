import pygame
from .base import Widget
from .fonts import load_display, load_ui
from . import design_system as DS


def _fmt_time(seconds: float) -> str:
    t = abs(float(seconds))
    if t >= 60.0:
        m = int(t // 60)
        s = t % 60
        return f'{m}:{s:05.2f}'
    return f'{t:05.2f}'


class LapInfoWidget(Widget):
    """
    Three-column lap info bar:  LAP TIME  |  BEST  |  DELTA

    Delta is green (faster) / red (slower).
    """

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self.lap_time    = 0.0
        self.lap_invalid = False
        self.best_lap    = 0.0
        self.delta       = 0.0
        self._session    = None   # SessionHistory — owns the session best lap
        self._val_font = load_display(max(14, int(height * 0.40)))
        self._lbl_font = load_ui(max(10,  int(height * 0.20)))

    def set_session(self, session) -> None:
        self._session = session

    def update(self, telemetry) -> None:
        self.lap_time    = float(getattr(telemetry, 'lap_time',    0.0))
        self.lap_invalid = bool(getattr(telemetry,  'lap_invalid', False))
        self.delta       = float(getattr(telemetry, 'delta',       0.0))
        # SessionHistory owns the session best (valid laps only); the telemetry
        # field is the fallback for sources without session tracking.
        if self._session is not None and self._session.best_lap > 0:
            self.best_lap = self._session.best_lap
        else:
            self.best_lap = float(getattr(telemetry, 'best_lap', 0.0))

    def draw(self, surface: pygame.Surface) -> None:
        self._draw_bg(surface, radius=6)

        col_w   = self.width // 3
        label_y = self.y + 5
        val_y   = self.y + self.height - 6

        sign = '+' if self.delta >= 0 else '−'
        delta_color = DS.RED if self.delta > 0 else (DS.GREEN if self.delta < 0 else DS.TEXT)

        lap_color = DS.RED if self.lap_invalid else DS.TEXT
        columns = [
            ('LAP TIME', _fmt_time(self.lap_time), lap_color),
            ('BEST',     _fmt_time(self.best_lap),  DS.PURPLE),
            ('DELTA',    f'{sign}{abs(self.delta):.3f}', delta_color),
        ]

        for i, (label, value, color) in enumerate(columns):
            cx = self.x + i * col_w + col_w // 2

            if i > 0:
                div_x = self.x + i * col_w
                pygame.draw.line(surface, DS.BORDER,
                                 (div_x, self.y + 4), (div_x, self.y + self.height - 4))

            lbl_s = self._lbl_font.render(label, True, DS.TEXT3)
            surface.blit(lbl_s, lbl_s.get_rect(midtop=(cx, label_y)))

            val_s = self._val_font.render(value, True, color)
            surface.blit(val_s, val_s.get_rect(midbottom=(cx, val_y)))
