"""Retro LCD dashboard (Sage palette) — used for Formula Ford, Karting, and similar classes.

Matches the HTML reference design:
  - Dark outer frame + sage LCD panel with inset shadow and highlight wash
  - 3D LED shift bar in brushed-metal pill housing (12 LEDs, green→amber→red)
  - Spine-based curved arc rev bar: quarter-circle + horizontal arm, radial ticks
  - DSEG segmented readouts with ghost-segment backing (all-8 dim behind lit value)
  - Best Lap (top-left), LAP (centre), GEAR (large), SPEED (right), times (bottom)
  - Arc major-tick labels scale automatically to d.max_rpm
"""

import math
import pygame

from dashboard.base import Dashboard
from dashboard.widgets.fonts import load_digital, load_ui
from dashboard.widgets.units import convert_speed, speed_label

# ── Colour palette ─────────────────────────────────────────────────────────
_BG_OUTER = (  7,   8,   9)     # near-black outer frame
_BG_PANEL = (156, 162, 149)     # sage LCD panel  #9ca295

_ON    = ( 21,  23,  14)        # lit ticks / text / segments
_OFF   = (134, 140, 127)        # unlit / ghost (blended against panel bg)
_LABEL = ( 25,  28,  17)        # DSEG14-style label text

# LED shift-bar housing (brushed metal approximation)
_METAL_TOP = (190, 194, 198)    # housing top highlight
_METAL_MID = ( 74,  80,  83)    # housing body
_METAL_BOT = ( 44,  47,  50)    # housing base shadow
_RING      = ( 15,  15,  14)    # LED outer bezel ring
_LED_UNLIT = ( 86,  90,  92)    # unlit LED surface
_LED_GREEN = ( 54, 224, 122)    # #36e07a
_LED_AMBER = (255, 179,   0)    # #ffb300
_LED_RED   = (255,  59,  48)    # #ff3b30
_LED_FLASH = (127, 208, 255)    # over-rev flash

# ── Panel / outer layout (px) ──────────────────────────────────────────────
_PAD_H      = 10    # outer horizontal padding (each side)
_PAD_T      =  8    # outer top padding
_PAD_B      = 10    # outer bottom padding
_LEDBAR_H   = 56    # LED bar height
_LEDBAR_GAP =  8    # gap between LED bar and panel

_PANEL_L = _PAD_H                               # 10
_PANEL_T = _PAD_T + _LEDBAR_H + _LEDBAR_GAP    # 72
_PANEL_W = 800 - 2 * _PAD_H                    # 780
_PANEL_H = 480 - _PAD_B - _PANEL_T             # 398
_PANEL_R = _PANEL_L + _PANEL_W                 # 790
_PANEL_B = _PANEL_T + _PANEL_H                 # 470

# ── LED bar geometry ───────────────────────────────────────────────────────
_LED_N     = 12
_LED_R_OUT = 18    # outer radius
_LED_R_IN  = 13    # inner fill radius
_BAR_IPAD  = 16    # inset each side inside the bar

_LED_CX0  = _PANEL_L + _BAR_IPAD + _LED_R_OUT      #  44
_LED_CX1  = _PANEL_R - _BAR_IPAD - _LED_R_OUT      # 756
_LED_STEP = (_LED_CX1 - _LED_CX0) / (_LED_N - 1)   # ≈ 64.7
_LED_CY   = _PAD_T + _LEDBAR_H // 2                #  36

# Colour zone boundaries (match HTML: 55 % green, 80 % amber, 100 % red)
_LED_GREEN_N = int(_LED_N * 0.55)   # 6
_LED_AMBER_N = int(_LED_N * 0.80)   # 9

# ── SVG → screen transform ─────────────────────────────────────────────────
# HTML arc uses SVG viewBox="0 0 800 402" inside a 780×398 px panel.
# preserveAspectRatio="xMidYMid meet" → scale = 780/800 = 0.975, dy = 3 px.
_SVG_SC = 780 / 800     # 0.975
_SVG_DY = 3             # vertical centering offset (panel-local)


def _s2s(x: float, y: float) -> tuple[int, int]:
    """SVG viewBox coordinates → screen pixel coordinates."""
    return (
        int(_PANEL_L + x * _SVG_SC),
        int(_PANEL_T + _SVG_DY + y * _SVG_SC),
    )


# ── Arc geometry (SVG coords matching HTML LcdArc cfg exactly) ─────────────
# Spine: quarter-circle at (cx, cy) with radius R, then horizontal arm right.
# Minor ticks radiate outward; major ticks protrude inward with RPM labels.
_ARC_CX    = 198
_ARC_CY    = 200
_ARC_R     = 103
_ARC_ARM_H = 562
_ARC_N     = 74        # minor tick count

_TICK_MIN  = 24        # shortest tick length (at s=0)
_TICK_MAX  = 90        # longest tick length (at s≥0.27)
_TICK_TAPER = 0.27     # s at which ticks reach full length

_MAJOR_NUB = 14        # major tick inward protrusion
_MAJOR_LBL = 30        # dist from spine to label centre (inward)


def _arc_lc() -> float:
    """Quarter-circle arc length."""
    return _ARC_R * math.pi / 2


def _spine(s: float) -> tuple[float, float, float, float]:
    """Return (px, py, dx, dy) for spine position at parameter s ∈ [0, 1].

    The spine begins on the left side of the circle (at the 9 o'clock
    position), sweeps counter-clockwise to the 12 o'clock position, then
    continues as a horizontal arm extending to the right.
    """
    Lc    = _arc_lc()
    total = Lc + _ARC_ARM_H
    d     = s * total
    if d < Lc:
        th = math.pi - (d / Lc) * (math.pi / 2)
        px = _ARC_CX + _ARC_R * math.cos(th)
        py = _ARC_CY - _ARC_R * math.sin(th)
        return px, py, math.cos(th), -math.sin(th)
    else:
        return _ARC_CX + (d - Lc), _ARC_CY - _ARC_R, 0.0, -1.0


def _tick_len(s: float) -> float:
    return _TICK_MIN + (_TICK_MAX - _TICK_MIN) * min(1.0, s / _TICK_TAPER)


def _build_minor_ticks() -> list:
    """Pre-compute all minor tick screen endpoints (static, computed once)."""
    out = []
    for i in range(_ARC_N):
        s = i / (_ARC_N - 1)
        px, py, dx, dy = _spine(s)
        ln = _tick_len(s)
        x1, y1 = _s2s(px, py)
        x2, y2 = _s2s(px + dx * ln, py + dy * ln)
        out.append((s, x1, y1, x2, y2))
    return out


def _build_major_ticks(grads: int) -> list:
    """Pre-compute major tick endpoints + label positions for the given grad count."""
    out = []
    for g in range(grads + 1):
        s = g / grads if grads else 0.0
        px, py, dx, dy = _spine(s)
        x1, y1 = _s2s(px, py)
        x2, y2 = _s2s(px - dx * _MAJOR_NUB, py - dy * _MAJOR_NUB)
        nx, ny = _s2s(px - dx * _MAJOR_LBL,  py - dy * _MAJOR_LBL)
        out.append((g, x1, y1, x2, y2, nx, ny))
    return out


def _rpm_grads(max_rpm: int) -> tuple[int, int]:
    """Choose major-tick step and count so there are at most 12 intervals.

    Returns (grads, step_rpm).  grads is the number of intervals, so labels
    run 0 · step_rpm/1000 … grads · step_rpm/1000 (shown with ×1000 tag).
    Uses ceiling so the arc always covers the full max_rpm range even when
    max_rpm isn't a clean multiple of the step (e.g. 7700 → 8 grads, not 7).
    """
    for step in (500, 1000, 2000, 2500, 3000, 5000):
        grads = math.ceil(max_rpm / step)
        if grads <= 12:
            return grads, step
    return 10, math.ceil(max_rpm / 10)


# ── Misc helpers ────────────────────────────────────────────────────────────

def _rpm_frac(rpm: int, max_rpm: int) -> float:
    return max(0.0, min(1.0, rpm / max_rpm)) if max_rpm > 0 else 0.0


def _fmt_time(seconds: float) -> str:
    if seconds <= 0.0:
        return "--:--.---"
    m  = int(seconds // 60)
    s  = seconds % 60
    ms = int((s % 1) * 1000)
    return f"{m:02d}:{int(s):02d}.{ms:03d}"


def _ghost(s: str) -> str:
    """Replace every digit with '8' for the ghost-segment backing effect."""
    return "".join("8" if c.isdigit() else c for c in s)


class LCDDashboard(Dashboard):
    """Retro sage LCD dashboard for the Formula Ford / Formula Rookie."""

    def __init__(self, width: int, height: int):
        super().__init__(width, height)
        self._data = None
        self._flash_tick = 0

        # Fonts — DSEG14Classic for readouts and labels, Saira for arc ticks
        self._font_lbl   = load_digital(13)     # small label (LAP, GEAR…)
        self._font_large = load_digital(48)     # lap number
        self._font_gear  = load_digital(120)    # gear (large centrepiece)
        self._font_speed = load_digital(70)     # speed value
        self._font_time  = load_digital(22)     # bottom-bar lap times
        self._font_arc   = load_ui(13)          # arc major-tick labels (Saira)
        self._font_pos   = load_digital(36)     # position value (left panel)

        # Minor tick positions: static, computed once
        self._minor_ticks = _build_minor_ticks()

        # Major tick positions: rebuilt when max_rpm changes
        self._last_max_rpm: int = 0
        self._major_ticks: list = []
        self._grads: int       = 9
        self._step_rpm: int    = 1000

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def update(self, data) -> None:
        self._data = data

    def render(self, surface: pygame.Surface) -> None:
        surface.fill(_BG_OUTER)
        d    = self._data
        frac = _rpm_frac(d.rpm, d.max_rpm) if d else 0.0

        self._update_major_ticks(d.max_rpm if d else 8000)
        self._flash_tick = (self._flash_tick + 1) % 14

        # Arc fraction uses grads*step_rpm as the ceiling so the indicator
        # aligns with major tick labels even when max_rpm isn't a round multiple.
        arc_top  = self._grads * self._step_rpm
        arc_frac = _rpm_frac(d.rpm, arc_top) if d else 0.0

        self._draw_panel_bg(surface)
        self._draw_arc(surface, arc_frac)
        self._draw_led_bar(surface, frac)
        if d:
            self._draw_lap(surface, d)
            self._draw_gear(surface, d)
            self._draw_speed(surface, d)
            self._draw_bottom(surface, d)
            self._draw_left_panel(surface, d)

    def handle_event(self, event) -> None:
        pass

    # ── Panel background ─────────────────────────────────────────────────────

    def _draw_panel_bg(self, surface: pygame.Surface) -> None:
        r = pygame.Rect(_PANEL_L, _PANEL_T, _PANEL_W, _PANEL_H)
        pygame.draw.rect(surface, _BG_PANEL, r, border_radius=8)

    # ── Major-tick cache ─────────────────────────────────────────────────────

    def _update_major_ticks(self, max_rpm: int) -> None:
        if max_rpm == self._last_max_rpm:
            return
        self._last_max_rpm = max_rpm
        self._grads, self._step_rpm = _rpm_grads(max_rpm)
        self._major_ticks = _build_major_ticks(self._grads)

    # ── LED shift bar ─────────────────────────────────────────────────────────

    def _draw_led_bar(self, surface: pygame.Surface, frac: float) -> None:
        bx, by, bw, bh = _PANEL_L, _PAD_T, _PANEL_W, _LEDBAR_H
        br = bh // 2  # pill border radius

        # Brushed-metal housing (3-layer gradient approximation)
        pygame.draw.rect(surface, _METAL_MID, (bx, by, bw, bh),     border_radius=br)
        pygame.draw.rect(surface, _METAL_TOP, (bx, by, bw, 6),      border_radius=br)
        pygame.draw.rect(surface, _METAL_BOT, (bx, by + bh - 7, bw, 7), border_radius=br)

        over_rev = frac > 0.965
        flash    = over_rev and (self._flash_tick < 7)
        # +1 shifts "all lit" to ~92 % of max_rpm so the last LED is reachable
        # in normal driving rather than requiring exactly 100 % RPM.
        lit_n    = max(0, min(_LED_N, int(frac * (_LED_N + 1)))) if frac > 0.30 else 0

        for i in range(_LED_N):
            cx = int(_LED_CX0 + i * _LED_STEP)
            cy = _LED_CY

            pygame.draw.circle(surface, _RING, (cx, cy), _LED_R_OUT)

            if i < lit_n:
                col = (_LED_FLASH if flash
                       else _LED_GREEN if i < _LED_GREEN_N
                       else _LED_AMBER if i < _LED_AMBER_N
                       else _LED_RED)
                pygame.draw.circle(surface, col, (cx, cy), _LED_R_IN)
                # Specular highlight spot
                hx = cx - int(_LED_R_IN * 0.32)
                hy = cy - int(_LED_R_IN * 0.32)
                pygame.draw.circle(surface, (255, 255, 255),
                                   (hx, hy), int(_LED_R_IN * 0.28))
            else:
                pygame.draw.circle(surface, _LED_UNLIT, (cx, cy), _LED_R_IN)
                pygame.draw.circle(surface, (170, 174, 176),
                                   (cx - int(_LED_R_IN * 0.25),
                                    cy - int(_LED_R_IN * 0.25)),
                                   int(_LED_R_IN * 0.22))

    # ── RPM arc ───────────────────────────────────────────────────────────────

    def _draw_arc(self, surface: pygame.Surface, frac: float) -> None:
        # Clip to panel so arc ticks can't paint outside the rounded rect
        surface.set_clip(pygame.Rect(_PANEL_L, _PANEL_T, _PANEL_W, _PANEL_H))

        # Minor ticks (lit vs unlit by frac position)
        for s, x1, y1, x2, y2 in self._minor_ticks:
            col = _ON if s <= frac else _OFF
            pygame.draw.line(surface, col, (x1, y1), (x2, y2), 4)

        # Major ticks (inward protrusion) + RPM labels
        for g, x1, y1, x2, y2, nx, ny in self._major_ticks:
            pygame.draw.line(surface, _ON, (x1, y1), (x2, y2), 3)
            lbl = self._font_arc.render(str(g * self._step_rpm // 1000), True, _ON)
            surface.blit(lbl, lbl.get_rect(center=(nx, ny)))

        # ×1000 RPM unit tag
        tag = self._font_arc.render("×1000", True, _LABEL)
        sx, sy = _s2s(690, 150)
        surface.blit(tag, (sx, sy))

        surface.set_clip(None)

    # ── Lap number ────────────────────────────────────────────────────────────

    def _draw_lap(self, surface: pygame.Surface, d) -> None:
        lap_str = str(d.lap_number) if d.lap_number > 0 else "0"
        ghost_surf = self._font_large.render("88",    True, _OFF)
        val_surf   = self._font_large.render(lap_str, True, _ON)
        x, y = _PANEL_L + 250, _PANEL_T + 170
        gr = ghost_surf.get_rect(left=x, top=y)
        vr = val_surf.get_rect(right=gr.right, top=y)
        lbl = self._font_lbl.render("LAP", True, _LABEL)
        surface.blit(lbl, lbl.get_rect(centerx=gr.centerx, top=_PANEL_T + 150))
        surface.blit(ghost_surf, gr)
        surface.blit(val_surf,   vr)

    # ── Gear ──────────────────────────────────────────────────────────────────

    def _draw_gear(self, surface: pygame.Surface, d) -> None:
        gear_str = d.gear if d.gear else "N"
        x, y = _PANEL_L + 396, _PANEL_T + 172
        ghost_surf = self._font_gear.render(_ghost(gear_str), True, _OFF)
        val_surf   = self._font_gear.render(gear_str,         True, _ON)
        lbl = self._font_lbl.render("GEAR", True, _LABEL)
        surface.blit(lbl, lbl.get_rect(centerx=x + ghost_surf.get_width() // 2,
                                       top=_PANEL_T + 150))
        surface.blit(ghost_surf, (x, y))
        surface.blit(val_surf,   (x, y))

    # ── Speed ─────────────────────────────────────────────────────────────────

    def _draw_speed(self, surface: pygame.Surface, d) -> None:
        spd = convert_speed(d.speed)
        spd_str = str(int(spd)) if spd >= 1.0 else "0"
        x, y = _PANEL_L + 556, _PANEL_T + 194
        lbl = self._font_lbl.render("SPEED", True, _LABEL)
        surface.blit(lbl, (_PANEL_L + 556, _PANEL_T + 150))
        # Always ghost 3 digits so the empty positions show faint segments
        self._blit_seg_rj(surface, self._font_speed, "888", spd_str, x, y)
        unit = self._font_lbl.render(speed_label().upper(), True, _LABEL)
        surface.blit(unit, (_PANEL_L + 700, _PANEL_T + 286))

    # ── Bottom bar ────────────────────────────────────────────────────────────

    def _draw_bottom(self, surface: pygame.Surface, d) -> None:
        sep_y  = _PANEL_T + 338
        lbl_y  = _PANEL_T + 344
        val_y  = _PANEL_T + 362
        pygame.draw.line(surface, _OFF,
                         (_PANEL_L + 10, sep_y), (_PANEL_R - 10, sep_y), 1)

        # Three items evenly spread: LAST LAP | BEST LAP | LAP TIME
        cols = [175, 400, 625]
        items = [
            ("LAST LAP", _fmt_time(d.last_lap)),
            ("BEST LAP", _fmt_time(d.best_lap)),
            ("LAP TIME", _fmt_time(d.lap_time)),
        ]
        for cx, (label, value) in zip(cols, items):
            lbl = self._font_lbl.render(label, True, _LABEL)
            surface.blit(lbl, lbl.get_rect(centerx=cx, top=lbl_y))
            self._blit_seg_cx_fixed(surface, self._font_time,
                                    "88:88.888", value, cx, val_y)

    # ── Left panel: position + fuel ──────────────────────────────────────────

    def _draw_left_panel(self, surface: pygame.Surface, d) -> None:
        """Position readout and fuel bar, side by side below the main readouts."""
        # Both items sit below the gear digit (which ends at y≈364) and above
        # the bottom separator (y=410).  Neither x overlaps the gear (x=406+).
        cx_pos  = 175   # position column centre
        cx_fuel = 310   # fuel column centre
        y_lbl   = _PANEL_T + 273   # 345 — shared label row
        y_val   = _PANEL_T + 290   # 362 — value / bar row

        # ── Position ──────────────────────────────────────────────────────────
        lbl = self._font_lbl.render("POS", True, _LABEL)
        surface.blit(lbl, lbl.get_rect(centerx=cx_pos, top=y_lbl))

        pos_str = str(d.position) if d.position > 0 else "--"
        # Ghost always 2 digits wide; value right-aligned within it, whole block centred
        ghost_surf = self._font_pos.render("88", True, _OFF)
        val_surf   = self._font_pos.render(pos_str, True, _ON)
        gr = ghost_surf.get_rect(centerx=cx_pos, top=y_val)
        vr = val_surf.get_rect(right=gr.right, top=y_val)
        surface.blit(ghost_surf, gr)
        surface.blit(val_surf,   vr)

        # ── Fuel horizontal segmented bar ─────────────────────────────────────
        lbl = self._font_lbl.render("FUEL", True, _LABEL)
        surface.blit(lbl, lbl.get_rect(centerx=cx_fuel, top=y_lbl))

        fuel_frac = (d.fuel_remaining / d.fuel_capacity
                     if d.fuel_capacity > 0 else 0.0)
        fuel_frac = max(0.0, min(1.0, fuel_frac))

        # 6 segments × 10 px + 5 gaps × 3 px = 75 px inner, 2 px border → 79 × 16
        seg_n, seg_w, seg_gap = 6, 10, 3
        bar_inner_w = seg_n * seg_w + (seg_n - 1) * seg_gap    # 75
        bar_w, bar_h = bar_inner_w + 4, 16
        bar_x = cx_fuel - bar_w // 2
        bar_y = y_val + 10    # nudge bar down to optically centre vs POS digit

        pygame.draw.rect(surface, _ON, (bar_x, bar_y, bar_w, bar_h), 1)

        lit   = round(fuel_frac * seg_n)
        seg_h = bar_h - 4

        for i in range(seg_n):
            sx  = bar_x + 2 + i * (seg_w + seg_gap)
            col = _ON if i < lit else _OFF
            pygame.draw.rect(surface, col, (sx, bar_y + 2, seg_w, seg_h))

        # Remaining fuel readout below bar
        num = self._font_lbl.render(f"{d.fuel_remaining:.0f}L", True, _LABEL)
        surface.blit(num, num.get_rect(centerx=cx_fuel, top=bar_y + bar_h + 4))

    # ── Segment helpers ───────────────────────────────────────────────────────

    def _blit_seg(self, surface: pygame.Surface, font: pygame.font.Font,
                  value: str, x: int, y: int) -> None:
        """Render value with ghost-segment backing, left-aligned."""
        ghost_surf = font.render(_ghost(value), True, _OFF)
        val_surf   = font.render(value,         True, _ON)
        surface.blit(ghost_surf, (x, y))
        surface.blit(val_surf,   (x, y))

    def _blit_seg_cx(self, surface: pygame.Surface, font: pygame.font.Font,
                     value: str, cx: int, y: int) -> None:
        """Render value with ghost-segment backing, centred on cx."""
        ghost_surf = font.render(_ghost(value), True, _OFF)
        val_surf   = font.render(value,         True, _ON)
        r = val_surf.get_rect(centerx=cx, top=y)
        surface.blit(ghost_surf, r)
        surface.blit(val_surf,   r)

    def _blit_seg_cx_fixed(self, surface: pygame.Surface, font: pygame.font.Font,
                           ghost: str, value: str, cx: int, y: int) -> None:
        """Render value with a fixed-width ghost, both centred on cx."""
        ghost_surf = font.render(ghost, True, _OFF)
        val_surf   = font.render(value, True, _ON)
        gr = ghost_surf.get_rect(centerx=cx, top=y)
        vr = val_surf.get_rect(centerx=cx, top=y)
        surface.blit(ghost_surf, gr)
        surface.blit(val_surf,   vr)

    def _blit_seg_rj(self, surface: pygame.Surface, font: pygame.font.Font,
                     ghost: str, value: str, x: int, y: int) -> None:
        """Render value right-aligned within a fixed-width ghost string.

        Keeps all ghost-segment positions visible regardless of digit count.
        """
        ghost_surf = font.render(ghost, True, _OFF)
        val_surf   = font.render(value, True, _ON)
        val_x = x + ghost_surf.get_width() - val_surf.get_width()
        surface.blit(ghost_surf, (x, y))
        surface.blit(val_surf,   (val_x, y))
