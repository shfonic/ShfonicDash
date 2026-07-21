# src/dashboard/text_dashboard.py
import pygame
import math
from dataclasses import fields
from dashboard.base import Dashboard
from core.telemetry_model import TelemetryData


class TextDashboard(Dashboard):
    """A simple text-only dashboard for debugging: shows attribute names and raw values in columns."""

    BG = (0, 0, 0)
    KEY_COLOR = (180, 180, 180)
    VAL_COLOR = (240, 240, 240)

    def __init__(self, width: int, height: int):
        super().__init__(width, height)
        self.data = TelemetryData()
        # font must be created after pygame.init(); App does that before creating dashboards
        size = max(12, int(height * 0.035))
        self.font = pygame.font.SysFont(None, size)

    def update(self, data: TelemetryData):
        self.data = data

    def render(self, surface):
        # Fill background
        surface.fill(self.BG)

        # Gather ordered fields from the dataclass so display order is stable
        try:
            field_names = [f.name for f in fields(TelemetryData)]
        except Exception:
            # fallback: use instance dict ordering
            field_names = list(self.data.__dict__.keys())

        lines = []
        for name in field_names:
            val = getattr(self.data, name, None)
            if isinstance(val, float):
                val_s = f"{val:.3f}"
            elif isinstance(val, int):
                val_s = f"{val:d}"
            else:
                val_s = str(val)
            lines.append((name, val_s))

        pad = 8
        col_gap = 18
        line_height = self.font.get_linesize()
        max_rows = max(1, (self.height - 2 * pad) // line_height)
        n = len(lines)
        cols = max(1, math.ceil(n / max_rows))

        col_width = (self.width - 2 * pad - (cols - 1) * col_gap) / cols

        for idx, (k, v) in enumerate(lines):
            col = idx // max_rows
            row = idx % max_rows
            x = int(pad + col * (col_width + col_gap))
            y = int(pad + row * line_height)

            key_s = self.font.render(f"{k}:", True, self.KEY_COLOR)
            surface.blit(key_s, (x, y))

            val_s = self.font.render(v, True, self.VAL_COLOR)
            # right-align value within column to keep columns tidy
            val_rect = val_s.get_rect()
            val_rect.top = y
            val_rect.right = int(x + col_width)
            surface.blit(val_s, val_rect)

    def handle_event(self, event):
        pass
