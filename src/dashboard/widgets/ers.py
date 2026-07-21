import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS

_MODE_LABELS = {0: "BALANCED", 1: "MEDIUM", 2: "HOTLAP", 3: "BOOST"}


class ERSWidget(Widget):
    """
    ERS battery bar with DEPLOY and BOOST/OVERRIDE chips.

    Layout:
        "ERS · BATTERY"  label    |  percentage value
        ──────────── amber bar ───────────────────────
        [ DEPLOY chip ]  [ BOOST chip ]
    """

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self._energy = 0.0
        self._mode   = 0
        self._deploy = False
        self._boost  = False

        self._lbl_font  = load_ui(max(10, int(height * 0.18)))
        self._chip_font = load_ui(max(9,  int(height * 0.16)))

    def update(self, telemetry) -> None:
        self._energy = float(getattr(telemetry, 'ers_stored_energy', 0.0))
        self._mode   = int(getattr(telemetry, 'ers_deploy_mode', 0))
        self._deploy = self._mode in (2, 3)   # hotlap or boost = deploying
        self._boost  = self._mode == 3

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface)

        pad  = 10
        x0   = self.x + pad
        w    = self.width - pad * 2

        # Pin chips to the bottom so they never overflow
        chip_h   = max(16, int(self.height * 0.26))
        chip_top = self.y + self.height - chip_h - pad
        chip_w   = (w - 6) // 2

        # ── Row 1: label left, percentage right (same font keeps row short) ──
        lbl_surf = self._lbl_font.render("ERS · BATTERY", True, DS.TEXT3)
        pct_surf = self._lbl_font.render(f"{self._energy * 100:.0f}%", True, DS.AMBER)

        row1_y   = self.y + pad
        row1_h   = max(lbl_surf.get_height(), pct_surf.get_height())
        surface.blit(lbl_surf, (x0, row1_y + (row1_h - lbl_surf.get_height()) // 2))
        surface.blit(pct_surf, pct_surf.get_rect(topright=(self.x + self.width - pad, row1_y)))
        row1_bot = row1_y + row1_h

        # ── Row 2: bar — fills space between row 1 and chips ─────────────────
        gap_above = 5
        gap_below = 6
        bar_top = row1_bot + gap_above
        bar_h   = chip_top - bar_top - gap_below   # hard-capped; never bleeds into chips
        if bar_h > 0:
            DS.draw_bar_h(surface, pygame.Rect(x0, bar_top, w, bar_h), self._energy, DS.AMBER)

        # ── Row 3: chips ──────────────────────────────────────────────────────

        deploy_rect = pygame.Rect(x0, chip_top, chip_w, chip_h)
        boost_rect  = pygame.Rect(x0 + chip_w + 6, chip_top, chip_w, chip_h)

        DS.draw_chip(surface, deploy_rect, "DEPLOY", self._chip_font,
                     state=DS.CHIP_AMBER if self._deploy else None, dot=True)
        DS.draw_chip(surface, boost_rect,
                     "BOOST" if self._boost else _MODE_LABELS.get(self._mode, "BALANCED"),
                     self._chip_font,
                     state=DS.CHIP_RED if self._boost else None, dot=True)

        surface.set_clip(None)
