"""Render a QR matrix (from core.qr) to a pygame surface.

Kept separate from core.qr so the encoder stays pure-stdlib and unit-testable
without pygame. Used by the settings overlay to show the web-companion pairing
QR on the DATA tab.
"""
import pygame

from core import qr

_QUIET = 4        # quiet-zone width in modules (QR spec minimum)


def to_surface(text: str, module_px: int = 4,
               dark=(0, 0, 0), light=(255, 255, 255)) -> pygame.Surface:
    """Encode `text` and return a square surface with a light quiet zone.

    module_px is the pixel size of one QR module; the surface side is
    (matrix + 2*quiet) * module_px. `dark`/`light` are RGB tuples so the caller
    can match the active theme (a light background is required for scanners —
    keep `light` pale)."""
    matrix = qr.encode(text)
    n = len(matrix)
    side = (n + 2 * _QUIET) * module_px
    surf = pygame.Surface((side, side))
    surf.fill(light)
    off = _QUIET * module_px
    for r, row in enumerate(matrix):
        for c, on in enumerate(row):
            if on:
                pygame.draw.rect(surf, dark,
                                 (off + c * module_px, off + r * module_px,
                                  module_px, module_px))
    return surf


def fit_module_px(text: str, max_side_px: int) -> int:
    """Largest whole-pixel module size so the QR (incl. quiet zone) fits in
    max_side_px. At least 1."""
    n = len(qr.encode(text))
    return max(1, max_side_px // (n + 2 * _QUIET))
