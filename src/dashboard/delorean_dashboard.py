"""DeLorean DMC-12 dashboard.

Light grey instrument panel with dark display windows and red printed labels.
Speed is always shown in MPH.
"""

import pygame

from dashboard.base import Dashboard
from dashboard.widgets.fonts import load_digital, load_display, load_ui

# Panel colours — warm brushed-metal grey
_BG        = (196, 192, 186)
_BG2       = (176, 172, 167)
_SHADOW    = (148, 145, 140)
_HIGHLIGHT = (222, 219, 214)

# Display windows
_WIN_BG  = (16,  14,  13)
_WIN_BDR = (82,  80,  76)

# Printed labels
_LABEL_R = (190,  18,  12)   # red chip background
_LABEL_W = (255, 255, 255)   # white label text

# Default digit colour (amber)
_DIGIT   = (255, 162,  18)

# Panel text
_TXT_DARK = (50,  46,  42)
_TXT_MID  = (115, 111, 106)

_MAGIC_MPH = 88.0

# Race flag colours and short names
_FLAG_COLORS = {
    "green":     (40, 200,  80),
    "yellow":    (220, 200,  10),
    "red":       (220,  35,  25),
    "blue":      ( 60, 130, 220),
    "white":     (210, 210, 208),
    "chequered": (180, 180, 178),
    "penalty":   (220, 200,  10),
    "safety_car":(220, 200,  10),
    "vsc":       (220, 200,  10),
}
_FLAG_SHORT = {
    "green":     "GRN",  "yellow": "YEL", "red":      "RED",
    "blue":      "BLU",  "white":  "WHT", "chequered":"CHQ",
    "penalty":   "PEN",  "safety_car": "SC",  "vsc":  "VSC",
}


def _lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class DeLoreanDashboard(Dashboard):
    """Grey instrument-panel dashboard for the DeLorean DMC-12."""

    _TITLE_H = 38
    _INFO_W  = 130   # position/lap column left of circuit rows
    _ROW_H   = 82
    _ROW_GAP = 3
    _PEDAL_H = 26

    def __init__(self, width: int, height: int):
        super().__init__(width, height)
        self._data = None

        self._font_title     = load_ui(13)
        self._font_col_label = load_ui(10)
        self._font_row_label = load_display(13)
        self._font_time      = load_digital(36)
        self._font_info      = load_digital(60)   # position / lap numbers
        self._font_gear      = load_digital(100)
        self._font_speed     = load_digital(64)
        self._font_tyre      = load_display(16)   # tyre temperature values
        self._font_small     = load_ui(10)

    # ------------------------------------------------------------------

    def update(self, data) -> None:
        self._data = data

    def render(self, surface: pygame.Surface) -> None:
        if self._data is None:
            surface.fill(_BG)
            return
        d = self._data
        speed_mph = d.speed / 1.60934
        surface.fill(_BG)
        self._draw_title(surface, d)
        self._draw_info_column(surface, d)
        self._draw_time_circuits(surface, d)
        self._draw_driving(surface, d, speed_mph)
        self._draw_pedals(surface, d)

    def handle_event(self, event) -> None:
        pass

    # ------------------------------------------------------------------
    # Title bar

    def _draw_title(self, surface: pygame.Surface, d) -> None:
        h  = self._TITLE_H
        cx = self.width // 2
        pygame.draw.line(surface, _SHADOW,    (0, h - 2), (self.width, h - 2))
        pygame.draw.line(surface, _HIGHLIGHT, (0, h - 1), (self.width, h - 1))

        title = self._font_title.render("DELOREAN  DMC-12", True, _TXT_DARK)
        surface.blit(title, title.get_rect(centerx=cx, centery=h // 2))

        # Race flag chip — right-aligned, hidden when no flag
        if d.flag:
            flag_col   = _FLAG_COLORS.get(d.flag, _TXT_MID)
            flag_label = _FLAG_SHORT.get(d.flag, d.flag[:3].upper())
            fs = self._font_col_label.render(flag_label, True, _LABEL_W)
            fpx = 8
            fr  = pygame.Rect(self.width - fs.get_width() - fpx * 2 - 10,
                               h // 2 - 7,
                               fs.get_width() + fpx * 2, 14)
            pygame.draw.rect(surface, flag_col, fr)
            surface.blit(fs, fs.get_rect(center=fr.center))

    # ------------------------------------------------------------------
    # Info column — position and lap

    def _draw_info_column(self, surface: pygame.Surface, d) -> None:
        total_h = (self._ROW_H + self._ROW_GAP) * 3
        cell_h  = (total_h - self._ROW_GAP) // 2

        pos_val = str(d.position)   if d.position   > 0 else "--"
        lap_val = str(d.lap_number) if d.lap_number > 0 else "--"

        y1 = self._TITLE_H
        y2 = y1 + cell_h + self._ROW_GAP
        self._draw_info_cell(surface, 0, y1, self._INFO_W, cell_h,     "POSITION", pos_val)
        self._draw_info_cell(surface, 0, y2, self._INFO_W, cell_h + 1, "LAP",      lap_val)

        sx = self._INFO_W
        y_top, y_bot = self._TITLE_H, self._TITLE_H + total_h
        pygame.draw.line(surface, _SHADOW,    (sx,     y_top), (sx,     y_bot))
        pygame.draw.line(surface, _HIGHLIGHT, (sx + 1, y_top), (sx + 1, y_bot))

    def _draw_info_cell(self, surface, x, y, w, h, label, value):
        pygame.draw.rect(surface, _BG2, (x, y, w, h))
        pygame.draw.line(surface, _HIGHLIGHT, (x, y),         (x + w, y))
        pygame.draw.line(surface, _SHADOW,    (x, y + h - 1), (x + w, y + h - 1))

        strip_h = 16
        bot_pad = 3
        pad_x   = 8
        win_rect = pygame.Rect(x + pad_x, y + 8, w - pad_x * 2,
                               h - 8 - strip_h - bot_pad)
        self._draw_window(surface, win_rect)
        val_surf = self._font_info.render(value, True, _DIGIT)
        surface.blit(val_surf, val_surf.get_rect(center=win_rect.center))

        lbl_surf = self._font_row_label.render(label, True, _LABEL_W)
        lbl_px   = 10
        strip_y  = y + h - strip_h - bot_pad
        lbl_rect = pygame.Rect(x + w // 2 - lbl_surf.get_width() // 2 - lbl_px, strip_y,
                               lbl_surf.get_width() + lbl_px * 2, strip_h)
        pygame.draw.rect(surface, (10, 8, 8), lbl_rect)
        surface.blit(lbl_surf, lbl_surf.get_rect(center=lbl_rect.center))

    # ------------------------------------------------------------------
    # Time circuits

    def _draw_time_circuits(self, surface: pygame.Surface, d) -> None:
        rows = [
            ("BEST LAP",    d.best_lap,  (220,  35,  25)),
            ("CURRENT LAP", d.lap_time,  ( 40, 200,  80)),
            ("LAST LAP",    d.last_lap,  (255, 155,  15)),
        ]
        x, row_w, y = self._INFO_W, self.width - self._INFO_W, self._TITLE_H
        for label, secs, digit_color in rows:
            self._draw_circuit_row(surface, x, y, row_w, label, secs, digit_color)
            y += self._ROW_H + self._ROW_GAP

    def _draw_circuit_row(self, surface, x, y, w, label, seconds, digit_color):
        h = self._ROW_H
        pygame.draw.rect(surface, _BG2, (x, y, w, h))
        pygame.draw.line(surface, _HIGHLIGHT, (x, y),         (x + w, y))
        pygame.draw.line(surface, _SHADOW,    (x, y + h - 1), (x + w, y + h - 1))

        if seconds > 0.0:
            m  = int(seconds // 60)
            s  = int(seconds % 60)
            cs = int(round((seconds % 1) * 100)) % 100
            digit_strs = [f"{m:02d}", f"{s:02d}", f"{cs:02d}"]
        else:
            digit_strs = ["--", "--", "--"]

        col_labels = ["MIN", "SEC", "1/100"]
        top_pad, chip_h, chip_gap = 3, 14, 3
        strip_h, bot_pad = 16, 3
        win_y = y + top_pad + chip_h + chip_gap
        win_h = h - top_pad - chip_h - chip_gap - strip_h - bot_pad
        pad_x = 10
        col_w = (w - pad_x * 2) // 3

        for i, (col_lbl, digit_str) in enumerate(zip(col_labels, digit_strs)):
            cx = x + pad_x + i * col_w + col_w // 2
            chip_surf = self._font_col_label.render(col_lbl, True, _LABEL_W)
            chip_px   = 8
            chip_rect = pygame.Rect(cx - chip_surf.get_width() // 2 - chip_px, y + top_pad,
                                    chip_surf.get_width() + chip_px * 2, chip_h)
            pygame.draw.rect(surface, _LABEL_R, chip_rect)
            surface.blit(chip_surf, chip_surf.get_rect(center=chip_rect.center))

            win_rect = pygame.Rect(x + pad_x + i * col_w + 8, win_y, col_w - 16, win_h)
            self._draw_window(surface, win_rect)

            if seconds > 0.0:
                ghost_col = tuple(max(0, int(c * 0.18)) for c in digit_color)
                ghost_surf = self._font_time.render("8" * len(digit_str), True, ghost_col)
                surface.blit(ghost_surf, ghost_surf.get_rect(center=win_rect.center))

            digit_surf = self._font_time.render(digit_str, True, digit_color)
            surface.blit(digit_surf, digit_surf.get_rect(center=win_rect.center))

        strip_y  = y + h - strip_h - bot_pad
        lbl_surf = self._font_row_label.render(label, True, _LABEL_W)
        lbl_px   = 10
        lbl_rect = pygame.Rect(x + w // 2 - lbl_surf.get_width() // 2 - lbl_px, strip_y,
                               lbl_surf.get_width() + lbl_px * 2, strip_h)
        pygame.draw.rect(surface, (10, 8, 8), lbl_rect)
        surface.blit(lbl_surf, lbl_surf.get_rect(center=lbl_rect.center))

    # ------------------------------------------------------------------
    # Driving section

    def _driving_top(self) -> int:
        return self._TITLE_H + (self._ROW_H + self._ROW_GAP) * 3

    def _driving_height(self) -> int:
        return self.height - self._driving_top() - self._PEDAL_H

    def _draw_driving(self, surface: pygame.Surface, d, speed_mph: float) -> None:
        y0 = self._driving_top()
        dh = self._driving_height()
        pygame.draw.line(surface, _SHADOW,    (0, y0),     (self.width, y0))
        pygame.draw.line(surface, _HIGHLIGHT, (0, y0 + 1), (self.width, y0 + 1))

        rpm_w  = 148
        gear_w = 200
        tyre_w = 230
        spd_w  = self.width - rpm_w - gear_w - tyre_w   # 222

        self._draw_rpm_bar(surface, 0,                      y0, rpm_w,  dh, d)
        self._draw_gear   (surface, rpm_w,                  y0, gear_w, dh, d)
        self._draw_tyres_fuel(surface, rpm_w + gear_w,      y0, tyre_w, dh, d)
        self._draw_speed  (surface, self.width - spd_w,     y0, spd_w,  dh, speed_mph)

    def _draw_col_chip(self, surface, cx: int, y: int, text: str):
        """Red printed-label chip (column identifier), centered at cx."""
        surf   = self._font_col_label.render(text, True, _LABEL_W)
        px     = 8
        rect   = pygame.Rect(cx - surf.get_width() // 2 - px, y,
                             surf.get_width() + px * 2, 14)
        pygame.draw.rect(surface, _LABEL_R, rect)
        surface.blit(surf, surf.get_rect(center=rect.center))

    def _draw_row_chip(self, surface, cx: int, y: int, h: int, text: str):
        """Black printed-label chip (row/data identifier), centered at cx."""
        surf   = self._font_row_label.render(text, True, _LABEL_W)
        px     = 10
        rect   = pygame.Rect(cx - surf.get_width() // 2 - px, y,
                             surf.get_width() + px * 2, h)
        pygame.draw.rect(surface, (10, 8, 8), rect)
        surface.blit(surf, surf.get_rect(center=rect.center))

    def _draw_rpm_bar(self, surface, x, y, w, h, d):
        frac     = d.rpm / max(d.max_rpm, 1)
        top_pad  = 3
        chip_h   = 14
        chip_gap = 3
        strip_h  = 16
        bot_pad  = 3
        cx       = x + w // 2

        # Red "RPM" chip at top
        self._draw_col_chip(surface, cx, y + top_pad, "RPM")

        # Dark window between chips
        pad  = 8
        wy   = y + top_pad + chip_h + chip_gap
        wh   = h - top_pad - chip_h - chip_gap - strip_h - bot_pad
        win_rect = pygame.Rect(x + pad, wy, w - pad * 2, wh)
        self._draw_window(surface, win_rect, radius=4)

        inner   = win_rect.inflate(-6, -6)
        n, seg_gap = 10, 2
        seg_h   = max(4, (inner.height - seg_gap * (n - 1)) // n)

        for i in range(n):
            seg_y   = inner.bottom - (i + 1) * seg_h - i * seg_gap
            lit_col = (220, 35, 25) if i >= 8 else (220, 148, 12) if i >= 6 else (40, 200, 80)
            ghost   = tuple(max(0, int(c * 0.15)) for c in lit_col)
            pygame.draw.rect(surface, ghost, (inner.x, seg_y, inner.width, seg_h), border_radius=2)

        for i in range(n):
            if (i / n) < frac:
                seg_y = inner.bottom - (i + 1) * seg_h - i * seg_gap
                col   = (220, 35, 25) if i >= 8 else (220, 148, 12) if i >= 6 else (40, 200, 80)
                pygame.draw.rect(surface, col, (inner.x, seg_y, inner.width, seg_h), border_radius=2)

        # Black "REVS" chip at bottom
        self._draw_row_chip(surface, cx, y + h - strip_h - bot_pad, strip_h, "REVS")

    def _draw_gear(self, surface, x, y, w, h, d):
        top_pad  = 3
        chip_h   = 14
        chip_gap = 3
        strip_h  = 16
        bot_pad  = 3
        cx       = x + w // 2

        # Red "GEAR" chip at top
        self._draw_col_chip(surface, cx, y + top_pad, "GEAR")

        # Dark window between chips
        pad  = 10
        wy   = y + top_pad + chip_h + chip_gap
        wh   = h - top_pad - chip_h - chip_gap - strip_h - bot_pad
        win_rect = pygame.Rect(x + pad, wy, w - pad * 2, wh)
        self._draw_window(surface, win_rect)

        frac  = d.rpm / max(d.max_rpm, 1)
        color = (220, 50, 35) if frac > 0.92 else _DIGIT
        ghost_surf = self._font_gear.render("8", True, tuple(max(0, int(c * 0.18)) for c in color))
        surface.blit(ghost_surf, ghost_surf.get_rect(center=win_rect.center))
        gear_surf = self._font_gear.render(d.gear, True, color)
        surface.blit(gear_surf, gear_surf.get_rect(center=win_rect.center))

        # Black "GEAR" label at bottom
        self._draw_row_chip(surface, cx, y + h - strip_h - bot_pad, strip_h, "GEAR")

    def _draw_tyres_fuel(self, surface, x, y, w, h, d):
        temps   = d.tyre_temp   # (FL, FR, RL, RR) in °C
        top_pad = 4
        chip_h  = 14
        chip_gap = 3
        strip_h = 16   # FUEL label chip
        bar_h   = 10   # fuel bar
        bar_gap = 3
        bot_pad = 4
        pad_x   = 4
        cx      = x + w // 2

        # Red "TYRES" chip at top
        chip_surf = self._font_col_label.render("TYRES", True, _LABEL_W)
        chip_px   = 8
        chip_rect = pygame.Rect(cx - chip_surf.get_width() // 2 - chip_px, y + top_pad,
                                chip_surf.get_width() + chip_px * 2, chip_h)
        pygame.draw.rect(surface, _LABEL_R, chip_rect)
        surface.blit(chip_surf, chip_surf.get_rect(center=chip_rect.center))

        # Grid bounds (between chip and fuel area)
        grid_top = y + top_pad + chip_h + chip_gap
        grid_bot = y + h - bot_pad - strip_h - bar_gap - bar_h - bar_gap
        grid_h   = grid_bot - grid_top
        col_gap  = 3
        row_gap  = 3
        cell_w   = (w - pad_x * 2 - col_gap) // 2
        cell_h   = (grid_h - row_gap) // 2

        # Each tyre cell: window + small corner label below
        lbl_h   = 11
        lbl_gap = 2
        win_h_c = cell_h - lbl_h - lbl_gap
        positions = [
            ("FL", temps[0], x + pad_x,                    grid_top),
            ("FR", temps[1], x + pad_x + cell_w + col_gap, grid_top),
            ("RL", temps[2], x + pad_x,                    grid_top + cell_h + row_gap),
            ("RR", temps[3], x + pad_x + cell_w + col_gap, grid_top + cell_h + row_gap),
        ]
        for name, temp, cx_c, cy_c in positions:
            col      = self._tyre_color(temp)
            win_rect = pygame.Rect(cx_c, cy_c, cell_w, win_h_c)
            self._draw_window(surface, win_rect, radius=3)
            if temp > 0:
                pygame.draw.rect(surface, col, win_rect, 1, border_radius=3)
                ts = self._font_tyre.render(str(int(temp)), True, col)
            else:
                ts = self._font_tyre.render("--", True, _TXT_MID)
            surface.blit(ts, ts.get_rect(center=win_rect.center))
            ls = self._font_small.render(name, True, _TXT_MID)
            surface.blit(ls, ls.get_rect(centerx=win_rect.centerx, top=win_rect.bottom + lbl_gap))

        # Fuel bar
        bar_y    = y + h - bot_pad - strip_h - bar_gap - bar_h
        bar_rect = pygame.Rect(x + pad_x, bar_y, w - pad_x * 2, bar_h)
        pygame.draw.rect(surface, _WIN_BG, bar_rect, border_radius=3)
        frac = min(1.0, d.fuel_remaining / max(d.fuel_capacity, 1))
        if frac > 0:
            fill_col = _lerp((220, 35, 25), (40, 200, 80), frac)
            fill_w   = max(1, int(bar_rect.width * frac))
            pygame.draw.rect(surface, fill_col,
                             pygame.Rect(bar_rect.x, bar_rect.y, fill_w, bar_h), border_radius=3)
        pygame.draw.rect(surface, _WIN_BDR, bar_rect, 1, border_radius=3)

        # Tight "FUEL" black label chip at the very bottom
        strip_y  = y + h - bot_pad - strip_h
        lbl_surf = self._font_row_label.render("FUEL", True, _LABEL_W)
        lbl_px   = 10
        lbl_rect = pygame.Rect(cx - lbl_surf.get_width() // 2 - lbl_px, strip_y,
                               lbl_surf.get_width() + lbl_px * 2, strip_h)
        pygame.draw.rect(surface, (10, 8, 8), lbl_rect)
        surface.blit(lbl_surf, lbl_surf.get_rect(center=lbl_rect.center))

    def _tyre_color(self, temp: float) -> tuple:
        if temp <= 0:
            return _TXT_MID
        if temp < 50:
            return (60, 100, 220)
        if temp < 70:
            return _lerp((60, 100, 220), (40, 200, 80), (temp - 50) / 20)
        if temp < 90:
            return (40, 200, 80)
        if temp < 110:
            return _lerp((40, 200, 80), (220, 148, 12), (temp - 90) / 20)
        return (220, 35, 25)

    def _draw_speed(self, surface, x, y, w, h, speed_mph: float):
        strip_h = 16
        bot_pad = 3
        left_w  = 48
        top_pad = 8

        win_y    = y + top_pad
        win_h    = h - top_pad - strip_h - bot_pad
        win_rect = pygame.Rect(x + left_w, win_y, w - left_w - 8, win_h)
        cx_full  = x + w // 2

        # "SET / TO" dark block + "88" red chip on the left
        col_x     = x + 4
        col_w     = left_w - 8
        item_h    = 14
        inner_gap = 3
        red88_h   = 14
        red88_gap = 4
        group_h   = item_h * 2 + inner_gap + red88_gap + red88_h
        group_top = win_y + (win_h - group_h) // 2

        dark_rect = pygame.Rect(col_x, group_top, col_w, item_h * 2 + inner_gap)
        pygame.draw.rect(surface, _WIN_BG,  dark_rect)
        pygame.draw.rect(surface, _WIN_BDR, dark_rect, 1)
        for txt, top_off in [("SET", 2), ("TO", item_h + inner_gap)]:
            ts = self._font_col_label.render(txt, True, _LABEL_W)
            surface.blit(ts, ts.get_rect(centerx=dark_rect.centerx, top=dark_rect.top + top_off))
        red88_rect = pygame.Rect(col_x, dark_rect.bottom + red88_gap, col_w, red88_h)
        pygame.draw.rect(surface, _LABEL_R, red88_rect)
        s88 = self._font_col_label.render("88", True, _LABEL_W)
        surface.blit(s88, s88.get_rect(center=red88_rect.center))

        # Digit window
        self._draw_window(surface, win_rect)
        digit_color = (220, 35, 25)
        spd_str     = f"{int(speed_mph):03d}"
        ghost_col   = tuple(max(0, int(c * 0.18)) for c in digit_color)
        ghost_surf  = self._font_speed.render("888", True, ghost_col)
        surface.blit(ghost_surf, ghost_surf.get_rect(center=win_rect.center))
        spd_surf = self._font_speed.render(spd_str, True, digit_color)
        surface.blit(spd_surf, spd_surf.get_rect(center=win_rect.center))

        # "MPH" label chip at the bottom
        strip_y  = y + h - strip_h - bot_pad
        lbl_surf = self._font_row_label.render("MPH", True, _LABEL_W)
        lbl_px   = 10
        lbl_rect = pygame.Rect(cx_full - lbl_surf.get_width() // 2 - lbl_px, strip_y,
                               lbl_surf.get_width() + lbl_px * 2, strip_h)
        pygame.draw.rect(surface, (10, 8, 8), lbl_rect)
        surface.blit(lbl_surf, lbl_surf.get_rect(center=lbl_rect.center))

        # "ROADS?" flash at 88 mph — centred at bottom of digit window
        if speed_mph >= _MAGIC_MPH:
            ticks = pygame.time.get_ticks()
            if (ticks // 400) % 2 == 0:
                fs   = self._font_col_label.render("ROADS? WHERE WE'RE GOING...", True, (255, 240, 70))
                prev = surface.get_clip()
                surface.set_clip(win_rect)
                surface.blit(fs, fs.get_rect(centerx=win_rect.centerx, bottom=win_rect.bottom - 4))
                surface.set_clip(prev)

    # ------------------------------------------------------------------
    # Pedals

    def _draw_pedals(self, surface: pygame.Surface, d) -> None:
        y    = self.height - self._PEDAL_H
        h    = self._PEDAL_H - 2
        half = self.width // 2
        pygame.draw.line(surface, _SHADOW,    (0, y - 1), (self.width, y - 1))
        pygame.draw.line(surface, _HIGHLIGHT, (0, y),     (self.width, y))

        trough = pygame.Rect(10, y + 4, half - 20, h - 8)
        pygame.draw.rect(surface, _WIN_BG, trough, border_radius=3)
        fw = int(trough.width * d.throttle)
        if fw > 0:
            pygame.draw.rect(surface, (40, 200, 80),
                             pygame.Rect(trough.x, trough.y, fw, trough.height), border_radius=3)
        pygame.draw.rect(surface, _WIN_BDR, trough, 1, border_radius=3)

        trough2 = pygame.Rect(half + 10, y + 4, half - 20, h - 8)
        pygame.draw.rect(surface, _WIN_BG, trough2, border_radius=3)
        fw2 = int(trough2.width * d.brake)
        if fw2 > 0:
            pygame.draw.rect(surface, (220, 35, 25),
                             pygame.Rect(trough2.x, trough2.y, fw2, trough2.height), border_radius=3)
        pygame.draw.rect(surface, _WIN_BDR, trough2, 1, border_radius=3)

    # ------------------------------------------------------------------
    # Helpers

    def _draw_window(self, surface: pygame.Surface, rect: pygame.Rect, radius: int = 5) -> None:
        pygame.draw.rect(surface, _SHADOW,    rect.inflate(2, 2), border_radius=radius + 1)
        hr = rect.inflate(0, 0)
        hr.topleft = (rect.left + 1, rect.top + 1)
        pygame.draw.rect(surface, _HIGHLIGHT, hr, border_radius=radius)
        pygame.draw.rect(surface, _WIN_BG,    rect, border_radius=radius)
        pygame.draw.rect(surface, _WIN_BDR,   rect, 1, border_radius=radius)
