"""Tyre compound chips — shared by the lap widget, summary and history.

Compound colours are the F1-standard signal set and match the companion
app's chips (its theme.py TYRE_COMPOUNDS): soft red, medium yellow, hard
white, inter green, wet blue. They are deliberately NOT themed — a red
soft is a red soft in every theme. (TyreWidget's temperature grid lives
in tyres.py; this module is only the small per-lap compound chip.)
"""
import pygame

# compound (lower-case) → (label, fill, ink)
_COMPOUNDS = {
    "soft":   ("S", (230, 46, 46),   (243, 245, 248)),
    "medium": ("M", (255, 209, 46),  (12, 13, 16)),
    "hard":   ("H", (230, 230, 230), (12, 13, 16)),
    "inter":  ("I", (67, 176, 42),   (243, 245, 248)),
    "wet":    ("W", (0, 122, 194),   (243, 245, 248)),
    "dhe":    ("H", (120, 124, 135), (243, 245, 248)),   # Forza hard
    "dhd":    ("H", (120, 124, 135), (243, 245, 248)),   # Forza default
}
_UNKNOWN_FILL = (120, 124, 135)
_UNKNOWN_INK  = (243, 245, 248)


def tyre_style(compound):
    """Compound string → (label, fill, ink), or None when empty.

    Unknown compounds get a neutral grey chip labelled with their first
    letter so unexpected values still render rather than vanishing
    (same rule as the companion).
    """
    if not compound:
        return None
    key = compound.strip().lower()
    if key in _COMPOUNDS:
        return _COMPOUNDS[key]
    return (compound.strip()[:1].upper(), _UNKNOWN_FILL, _UNKNOWN_INK)


def draw_chip(surface: pygame.Surface, font: pygame.font.Font,
              compound, x: int, cy: int) -> int:
    """Draw a compound marker with its left edge at x, centred on cy.

    A thin ring in the compound colour with the letter inside — the same
    marking as a real F1 tyre sidewall, and far quieter on a live dash
    than a filled pill (user feedback 2026-07-07). Returns the width
    drawn (0 when compound is empty) so callers can advance their cursor.
    """
    style = tyre_style(compound)
    if style is None:
        return 0
    label, color, _ink = style
    txt = font.render(label, True, color)
    r = max(txt.get_height() // 2 + 1, txt.get_width() // 2 + 3)
    pygame.draw.circle(surface, color, (x + r, cy), r, 1)
    surface.blit(txt, txt.get_rect(center=(x + r, cy)))
    return r * 2
