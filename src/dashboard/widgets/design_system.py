"""
Shared design-system constants and drawing helpers.

Ported from the HTML/CSS reference design — charcoal palette, Saira typography,
and visual patterns (chips, gradient bars, glow effects).

Colors are pre-blended where possible to avoid SRCALPHA overhead in tight loops.
SRCALPHA is only used for chip/LED glow effects where accuracy matters most.
"""
import pygame

# ── Surfaces ─────────────────────────────────────────────────────────────────
BG     = (12,  13,  16)   # #0c0d10  — full-screen fill
BG2    = (16,  18,  22)   # #101216
PANEL  = (22,  25,  31)   # #16191f  — widget background
PANEL2 = (28,  32,  39)   # #1c2027  — secondary cells, tiles
PANEL3 = (35,  39,  47)   # #23272f  — innermost inset
INSET  = (10,  11,  14)   # dark trough for bar backgrounds

# Pre-blended 1px borders (avoids SRCALPHA per frame)
# LINE  = rgba(255,255,255, 0.06) on PANEL  → (37, 40, 46)
# LINE2 = rgba(255,255,255, 0.10) on PANEL2 → (50, 54, 62)
BORDER  = (37,  40,  46)
BORDER2 = (50,  54,  62)

# ── Text ─────────────────────────────────────────────────────────────────────
TEXT  = (243, 245, 248)   # #f3f5f8 — primary value text
TEXT2 = (174, 180, 190)   # #aeb4be
TEXT3 = (118, 124, 135)   # #767c87 — labels, units
TEXT4 = ( 77,  82,  92)   # #4d525c — dim / idle

# ── Accents ───────────────────────────────────────────────────────────────────
AMBER   = (255, 179,   0)  # #ffb300 — ERS, fuel warning, shift
ORANGE  = (255, 122,  24)  # #ff7a18 — contact-event marker (between amber/red)
GREEN   = ( 47, 224, 122)  # #2fe07a — DRS open, best sector, throttle
RED     = (255,  59,  48)  # #ff3b30 — alerts, brake, delta slow
BLUE    = ( 46, 155, 255)  # #2e9bff — active aero straight mode
PURPLE  = (122, 108, 255)  # #7a6cff — personal best sector
CYAN    = ( 51, 225, 237)  # #33e1ed
MAGENTA = (255,  69, 200)  # #ff45c8 — overall best (session fastest)

# Fixed dark ink for text/glyphs drawn *on top of* a bright accent fill
# (e.g. the "ON" label on a cyan toggle). Independent of the theme so it
# stays legible in light mode, where BG is near-white rather than near-black.
INK = (12, 13, 16)

# ── Chip active states: (background, text) ───────────────────────────────────
CHIP_GREEN = (GREEN,  ( 12,  20,  16))
CHIP_AMBER = (AMBER,  ( 26,  19,   0))
CHIP_BLUE  = (BLUE,   (  6,  18,  31))
CHIP_RED   = (RED,    (255, 255, 255))


# ── Drawing helpers ───────────────────────────────────────────────────────────

def draw_panel(surface: pygame.Surface, rect: pygame.Rect, radius: int = 8) -> None:
    """Standard dark widget panel with a subtle 1px border."""
    pygame.draw.rect(surface, PANEL, rect, border_radius=radius)
    pygame.draw.rect(surface, BORDER, rect, width=1, border_radius=radius)


def draw_panel2(surface: pygame.Surface, rect: pygame.Rect, radius: int = 6) -> None:
    """Slightly lighter inset panel — for secondary cells, tiles, gap rows."""
    pygame.draw.rect(surface, PANEL2, rect, border_radius=radius)
    pygame.draw.rect(surface, BORDER2, rect, width=1, border_radius=radius)


def draw_bar_h(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fraction: float,
    color: tuple,
    radius: int = 4,
) -> None:
    """Horizontal fill bar — dark inset trough + colored fill from the left."""
    pygame.draw.rect(surface, INSET, rect, border_radius=radius)
    fill_w = int(rect.width * max(0.0, min(1.0, fraction)))
    if fill_w > 0:
        pygame.draw.rect(surface, color,
                         pygame.Rect(rect.left, rect.top, fill_w, rect.height),
                         border_radius=radius)
    pygame.draw.rect(surface, BORDER, rect, width=1, border_radius=radius)


def draw_bar_v(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fraction: float,
    color: tuple,
    radius: int = 4,
) -> None:
    """Vertical fill bar — dark inset trough + colored fill from the bottom."""
    pygame.draw.rect(surface, INSET, rect, border_radius=radius)
    fill_h = int(rect.height * max(0.0, min(1.0, fraction)))
    if fill_h > 0:
        pygame.draw.rect(surface, color,
                         pygame.Rect(rect.left, rect.bottom - fill_h,
                                     rect.width, fill_h),
                         border_radius=radius)


def draw_chip(
    surface: pygame.Surface,
    rect: pygame.Rect,
    text: str,
    font: pygame.font.Font,
    state: tuple | None = None,
    dot: bool = False,
) -> None:
    """
    Draw a status chip/badge.

    state=None → idle (PANEL2 bg, muted text).
    state=CHIP_GREEN/AMBER/BLUE/RED → active (bright bg + soft glow + dark text).
    dot=True → draw a small filled circle before the text.
    """
    r = rect.height // 2

    if state:
        bg_color, fg_color = state
        # Soft glow halo — 2 steps, solid pre-blended rects
        for expand, blend_a in ((5, 0.18), (3, 0.30)):
            gr = pygame.Rect(
                rect.x - expand, rect.y - expand,
                rect.width + expand * 2, rect.height + expand * 2,
            )
            blend = _lerp(PANEL, bg_color, blend_a)
            pygame.draw.rect(surface, blend, gr, border_radius=r + expand)
        pygame.draw.rect(surface, bg_color, rect, border_radius=r)
        text_color = fg_color
    else:
        pygame.draw.rect(surface, PANEL2, rect, border_radius=r)
        pygame.draw.rect(surface, BORDER2, rect, width=1, border_radius=r)
        text_color = TEXT4

    if dot:
        dot_r = max(3, rect.height // 8)
        dot_cx = rect.left + 10 + dot_r
        txt = font.render(text, True, text_color)
        total_w = dot_r * 2 + 6 + txt.get_width()
        left = rect.centerx - total_w // 2
        pygame.draw.circle(surface, text_color, (left + dot_r, rect.centery), dot_r)
        surface.blit(txt, (left + dot_r * 2 + 6, rect.centery - txt.get_height() // 2))
    else:
        txt = font.render(text, True, text_color)
        surface.blit(txt, txt.get_rect(center=rect.center))


def led_glow_color(color: tuple, steps: int = 2) -> list[tuple]:
    """
    Return a list of [outer_glow, inner_glow] colors for a lit LED,
    pre-blended against PANEL. Avoids SRCALPHA in the render loop.
    """
    return [_lerp(PANEL, color, a) for a in (0.20, 0.45)]


def temp_color(temp: float, cold: float = 70.0, hot: float = 115.0) -> tuple:
    """Blue (cold) → GREEN (optimal) → AMBER → RED (hot)."""
    optimal = (cold + hot) / 2.0
    if temp <= cold:
        return BLUE
    if temp <= optimal:
        return _lerp(BLUE, GREEN, (temp - cold) / (optimal - cold))
    if temp <= hot:
        t = (temp - optimal) / (hot - optimal)
        # GREEN → AMBER at 75%, AMBER → RED for last 25%
        if t < 0.75:
            return _lerp(GREEN, AMBER, t / 0.75)
        return _lerp(AMBER, RED, (t - 0.75) / 0.25)
    return RED


def _luminance(c: tuple) -> float:
    """Perceived luminance (0–255) of an RGB tuple."""
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def on_panel(color: tuple) -> tuple:
    """Adapt a bright accent so small text drawn in it stays legible on the
    current PANEL. On dark themes the accent is returned unchanged; on a light
    PANEL (e.g. the Light theme) it is darkened enough to read on white.

    Use for accent-coloured *text* sitting on a panel (URLs, active labels).
    Accent *fills* — with dark ink drawn on top — should stay bright, so do
    not wrap those."""
    if _luminance(PANEL) < 128:
        return color
    return _lerp(color, (0, 0, 0), 0.55)


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    """Linear interpolation between two RGB tuples."""
    return (
        max(0, min(255, int(a[0] + (b[0] - a[0]) * t))),
        max(0, min(255, int(a[1] + (b[1] - a[1]) * t))),
        max(0, min(255, int(a[2] + (b[2] - a[2]) * t))),
    )
