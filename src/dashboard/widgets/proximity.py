import pygame
from .base import Widget
from .fonts import load_ui
from .gap import GapTrend, trend_color
from . import design_system as DS

_RED_GAP    = 0.5
_ORANGE_GAP = 2.0
_BAR_H      = 5


def _gap_color(gap: float) -> tuple:
    if gap <= 0:       return DS.TEXT4
    if gap <= _RED_GAP:    return DS.RED
    if gap <= _ORANGE_GAP: return DS.AMBER
    return DS.GREEN


def _fmt_gap(gap: float) -> str:
    if gap <= 0: return "+-.---"
    if gap >= 60: return f"+{gap:.1f}"
    return f"+{gap:.3f}"


class ProximityWidget(Widget):
    """Full-width bottom strip: car ahead | own position | car behind."""

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self._gap_ahead  = 0.0
        self._gap_behind = 0.0
        self._name_ahead  = ""
        self._name_behind = ""
        self._trend_ahead  = GapTrend()
        self._trend_behind = GapTrend()
        self._position   = 0
        self._total      = 0
        self._session    = ""

        self._gap_font = load_ui(max(14, int(height * 0.44)))
        self._lbl_font = load_ui(max(9,  int(height * 0.26)))
        self._pos_font = load_ui(max(11, int(height * 0.34)))

    def update(self, telemetry) -> None:
        self._gap_ahead  = float(getattr(telemetry, 'gap_ahead',  0.0))
        self._gap_behind = float(getattr(telemetry, 'gap_behind', 0.0))
        self._name_ahead  = str(getattr(telemetry, 'name_ahead',  '') or '')
        self._name_behind = str(getattr(telemetry, 'name_behind', '') or '')
        self._trend_ahead.update(self._gap_ahead)
        self._trend_behind.update(self._gap_behind)
        self._position   = int(getattr(telemetry, 'position',    0))
        self._total      = int(getattr(telemetry, 'total_cars',  0))
        self._session    = getattr(telemetry, 'session_type', '')

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface, radius=4)

        if self._session not in ('race', ''):
            txt = self._lbl_font.render("proximity  —  race only", True, DS.TEXT4)
            surface.blit(txt, txt.get_rect(center=(self.x + self.width // 2,
                                                    self.y + self.height // 2)))
            surface.set_clip(None)
            return

        panel_w  = int(self.width * 0.42)
        centre_w = self.width - 2 * panel_w

        self._draw_side(surface, self.x, panel_w,
                        self._gap_ahead,  self._position - 1, facing_right=True,
                        name=self._name_ahead, trend=self._trend_ahead.direction)
        self._draw_centre(surface, self.x + panel_w, centre_w)
        self._draw_side(surface, self.x + panel_w + centre_w, panel_w,
                        self._gap_behind, self._position + 1, facing_right=False,
                        name=self._name_behind, trend=self._trend_behind.direction)

        surface.set_clip(None)

    def _draw_side(self, surface, x, w, gap, pos, facing_right, name="", trend=0):
        # Bar keeps the absolute proximity colour (how close is the car);
        # the gap text is trend-coloured (is it getting closer or further).
        color     = _gap_color(gap)
        gap_color = trend_color(gap, trend, closing_is_good=facing_right)
        text_y  = self.y + (self.height - _BAR_H - 2) // 2
        bar_y   = self.y + self.height - _BAR_H - 2

        pos_str  = f"P{pos}" if 1 <= pos <= 99 else "–"
        if name:
            pos_str += f" {name[:3].upper()}"
        pos_surf = self._pos_font.render(pos_str, True, DS.TEXT3)
        gap_surf = self._gap_font.render(_fmt_gap(gap), True, gap_color)

        if facing_right:
            surface.blit(pos_surf, pos_surf.get_rect(midleft=(x + 8, text_y)))
            surface.blit(gap_surf, gap_surf.get_rect(midright=(x + w - 8, text_y)))
            self._draw_bar(surface, x, bar_y, w, gap, color, rtl=False)
        else:
            surface.blit(gap_surf, gap_surf.get_rect(midleft=(x + 8, text_y)))
            surface.blit(pos_surf, pos_surf.get_rect(midright=(x + w - 8, text_y)))
            self._draw_bar(surface, x, bar_y, w, gap, color, rtl=True)

        div_x = x + w if facing_right else x
        pygame.draw.line(surface, DS.BORDER,
                         (div_x, self.y + 4), (div_x, self.y + self.height - 4))

    def _draw_bar(self, surface, x, y, w, gap, color, rtl):
        track = pygame.Rect(x + 4, y, w - 8, _BAR_H)
        pygame.draw.rect(surface, DS.INSET, track, border_radius=2)
        frac = max(0.0, min(1.0, 1.0 - gap / 5.0)) if gap > 0 else 0
        fw   = int(track.width * frac)
        if fw > 0:
            rx = track.right - fw if rtl else track.left
            pygame.draw.rect(surface, color, pygame.Rect(rx, y, fw, _BAR_H), border_radius=2)

    def _draw_centre(self, surface, x, w):
        cx = x + w // 2
        cy = self.y + self.height // 2
        if self._position > 0:
            pos_surf = self._pos_font.render(str(self._position), True, DS.TEXT)
            surface.blit(pos_surf, pos_surf.get_rect(midbottom=(cx, cy + 2)))
            if self._total > 0:
                t = self._lbl_font.render(f"of {self._total}", True, DS.TEXT3)
                surface.blit(t, t.get_rect(midtop=(cx, cy + 4)))
