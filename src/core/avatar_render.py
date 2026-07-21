"""
Pygame driver-avatar renderer — the Pi's counterpart to the companion's
`ui_components.AvatarView`.

Builds a circular badge for the driver's profile avatar:
  • initials — initials on an amber disc,
  • helmet   — the shared helmet composited from three PNG layers on a light
               disc: base-tinted shell (+ accent pattern), visor-tinted glass,
               then the fixed trim (white edge + vent).

Colours/patterns/layer names come from the shared `sessionlog.avatar`, so the
Pi renders a profile identically to the phone. Tinting a white mask is
`surface.fill(rgb, special_flags=BLEND_RGBA_MULT)` — the pygame equivalent of
the companion's SOURCE_ATOP fill. Results are cached (avatars rarely change).
"""

import os

import pygame

from sessionlog import avatar

_IMG_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard", "images")

_DISC_INITIALS = (245, 158, 26)    # amber (matches the companion initials disc)
_DISC_HELMET   = (204, 209, 224)   # light disc so any shell colour reads
_INK           = (20, 20, 24)

_layer_cache = {}     # filename -> native Surface (convert_alpha)
_avatar_cache = {}    # cache key -> Surface


def _rgb255(key):
    r, g, b = avatar.colour_rgb(key)
    return (int(r * 255), int(g * 255), int(b * 255))


def _layer(name):
    surf = _layer_cache.get(name)
    if surf is None:
        surf = pygame.image.load(os.path.join(_IMG_DIR, name)).convert_alpha()
        _layer_cache[name] = surf
    return surf


def _tinted(mask_name, rgb, size):
    """A helmet mask scaled to `size` and multiplied by `rgb` (white mask →
    rgb, alpha preserved)."""
    surf = pygame.transform.smoothscale(_layer(mask_name), (size, size)).copy()
    surf.fill((*rgb, 255), special_flags=pygame.BLEND_RGBA_MULT)
    return surf


def _apply_pattern(shell, pattern, rgb, size):
    """Draw the accent pattern (crown bands) onto the shell, masked to the shell
    shape so stripes never spill off it. Mirrors the companion `_draw_pattern`."""
    if pattern == "solid":
        return
    band = pygame.Surface((size, size), pygame.SRCALPHA)
    col = (*rgb, 255)
    if pattern == "stripe":
        band.fill(col, pygame.Rect(0, int(size * 0.12), size, int(size * 0.16)))
    elif pattern == "twin":
        band.fill(col, pygame.Rect(0, int(size * 0.10), size, int(size * 0.08)))
        band.fill(col, pygame.Rect(0, int(size * 0.26), size, int(size * 0.08)))
    elif pattern == "halo":
        band.fill(col, pygame.Rect(0, int(size * 0.02), size, int(size * 0.11)))
    # Keep the band only where the shell is opaque (white mask * band).
    mask = pygame.transform.smoothscale(_layer("helmet.png"), (size, size))
    band.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    shell.blit(band, (0, 0))


def _helmet_surface(helmet, size):
    h = avatar.normalise_helmet(helmet)
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(surf, _DISC_HELMET, (size // 2, size // 2), size // 2)
    inset = int(size * 0.14)
    box = size - 2 * inset
    if box <= 0:
        return surf
    shell = _tinted("helmet.png", _rgb255(h["base"]), box)
    _apply_pattern(shell, h["pattern"], _rgb255(h["accent"]), box)
    surf.blit(shell, (inset, inset))
    surf.blit(_tinted("helmet_visor.png", _rgb255(h["visor"]), box), (inset, inset))
    trim = pygame.transform.smoothscale(_layer("helmet_trim.png"), (box, box))
    surf.blit(trim, (inset, inset))
    return surf


def _initials_surface(name, size, font=None):
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(surf, _DISC_INITIALS, (size // 2, size // 2), size // 2)
    text = avatar.initials(name)
    if text:
        font = font or pygame.font.SysFont(None, int(size * 0.5))
        label = font.render(text, True, _INK)
        surf.blit(label, label.get_rect(center=(size // 2, size // 2)))
    return surf


def avatar_surface(profile, size, font=None):
    """A `size`×`size` avatar Surface for a profile dict (`avatar_kind` +
    `avatar_helmet` + `name`). Cached; `font` (for initials) is not part of the
    key, so pass a stable font."""
    profile = profile or {}
    kind = avatar.normalise_kind(profile.get("avatar_kind"))
    if kind == "helmet":
        h = avatar.normalise_helmet(profile.get("avatar_helmet"))
        key = ("helmet", h["base"], h["visor"], h["accent"], h["pattern"], size)
    else:
        key = ("initials", (profile.get("name") or "").strip().upper(), size)
    surf = _avatar_cache.get(key)
    if surf is None:
        surf = (_helmet_surface(profile.get("avatar_helmet"), size)
                if kind == "helmet"
                else _initials_surface(profile.get("name"), size, font))
        _avatar_cache[key] = surf
    return surf
