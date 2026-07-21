import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS

# Sector flag → color mapping
def _flag_color(flag: str) -> tuple:
    return {
        "purple": DS.PURPLE,
        "green":  DS.GREEN,
        "yellow": DS.AMBER,
    }.get(flag, DS.TEXT4)


_ACCENT_H = 2   # top-border accent thickness

_TIME_FIELDS = ["sector1_time", "sector2_time"]
_FLAG_FIELDS = ["sector1_flag", "sector2_flag", "sector3_flag"]


def _fmt_sector(seconds: float) -> str:
    if seconds <= 0:
        return "–  –  –"
    t = abs(seconds)
    if t >= 60.0:
        m = int(t // 60)
        s = t % 60
        return f"{m}:{s:06.3f}"
    return f"{t:06.3f}"


class SectorTimesWidget(Widget):
    """
    Three sector tiles, each with a coloured top-border accent.

    Completed: purple (pb) / green (ok) / amber (yellow flag).
    In progress: white/grey running time.
    Pending: dashes.
    """

    def __init__(self, x: int, y: int, width: int, height: int, count: int = 3):
        super().__init__(x, y, width, height)
        self._count    = max(2, min(count, 3))
        self._times    = [0.0, 0.0]
        self._flags    = ["", "", ""]
        self._sector   = 0
        self._lap_time = 0.0

        self._time_font = load_ui(max(14, int(height * 0.42)))
        self._lbl_font  = load_ui(max(9,  int(height * 0.22)))

    def update(self, telemetry) -> None:
        self._times    = [float(getattr(telemetry, f, 0.0)) for f in _TIME_FIELDS]
        self._flags    = [getattr(telemetry, f, '') for f in _FLAG_FIELDS]
        self._sector   = int(getattr(telemetry, 'sector', 0))
        self._lap_time = float(getattr(telemetry, 'lap_time', 0.0))

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface, radius=6)

        n     = self._count
        gap   = 4
        tile_w = (self.width - gap * (n - 1)) // n

        for i in range(n):
            tx    = self.x + i * (tile_w + gap)
            tile  = pygame.Rect(tx, self.y, tile_w, self.height)
            flag  = self._flags[i] if i < len(self._flags) else ""
            color = _flag_color(flag)

            completed   = self._sector > i
            in_progress = self._sector == i

            # Tile background
            DS.draw_panel2(surface, tile, radius=5)

            # Top accent strip
            if completed or in_progress:
                accent_color = DS.TEXT3 if in_progress else color
                accent = pygame.Rect(tx, self.y, tile_w, _ACCENT_H)
                pygame.draw.rect(surface, accent_color, accent)

            # "S#" label centred top
            lbl = self._lbl_font.render(f"S{i + 1}", True, DS.TEXT3)
            surface.blit(lbl, lbl.get_rect(midtop=(tx + tile_w // 2, self.y + 4)))

            # Time
            if completed:
                if i == 0:
                    dur = self._times[0]
                elif i == 1:
                    dur = self._times[1] - self._times[0] if self._times[1] > 0 else 0.0
                else:
                    dur = 0.0
                txt_color = color
                txt = self._time_font.render(_fmt_sector(dur), True, txt_color)
            elif in_progress:
                base = self._times[i - 1] if i > 0 else 0.0
                elapsed = self._lap_time - base
                txt = self._time_font.render(_fmt_sector(max(0.0, elapsed)), True, DS.TEXT3)
            else:
                txt = self._time_font.render("– – –", True, DS.PANEL3)

            cy = self.y + self.height // 2 + 2
            surface.blit(txt, txt.get_rect(center=(tx + tile_w // 2, cy)))

        surface.set_clip(None)
