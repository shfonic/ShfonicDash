"""Startup splash screen — Shfonic Dash logo, fades in, holds, fades out.

Two brand lockups ship: ``logo-dark.png`` (opaque, black backdrop) for dark
themes and ``logo-light.png`` (transparent overlay) for the light theme. The
splash picks one from the saved theme and composites it over a matching fill,
scaled to *cover* the screen (no distortion — the 3:2 art is centre-cropped to
the 5:3 display).
"""
import os
import pygame

_IMAGE_DIR = os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'images')

_FADE_IN_MS  = 350
_HOLD_MS     = 900
_FADE_OUT_MS = 350

# Backdrop the logo composites over, per theme. Matches the light theme's page
# fill so the transparent light lockup blends; black for every dark theme.
_LIGHT_FILL = (236, 238, 242)
_DARK_FILL  = (0, 0, 0)


def _scale_to_cover(image: pygame.Surface, size: tuple) -> pygame.Surface:
    """Scale to fully cover ``size``, then centre-crop — like CSS
    ``background-size: cover``. Preserves aspect ratio (no stretch)."""
    sw, sh = size
    iw, ih = image.get_size()
    scale = max(sw / iw, sh / ih)
    scaled = pygame.transform.smoothscale(image, (round(iw * scale), round(ih * scale)))
    cw, ch = scaled.get_size()
    crop = pygame.Rect((cw - sw) // 2, (ch - sh) // 2, sw, sh)
    return scaled.subsurface(crop).copy()


def show_splash(screen: pygame.Surface, flip: bool = False, light: bool = False) -> bool:
    """
    Fade in the splash image, hold briefly, then fade to black.

    ``light`` selects the light-theme lockup + fill. Tapping/clicking or
    pressing any key skips to the end of the splash. Returns True if the user
    closed the window (caller should quit).
    """
    name = 'logo-light.png' if light else 'logo-dark.png'
    fill = _LIGHT_FILL if light else _DARK_FILL
    try:
        image = pygame.image.load(os.path.join(_IMAGE_DIR, name)).convert_alpha()
    except (pygame.error, FileNotFoundError):
        return False

    image = _scale_to_cover(image, screen.get_size())

    # Composite the (possibly transparent) lockup over the theme fill once, so
    # the per-frame fade only has to alpha-blit a single opaque frame.
    frame = pygame.Surface(screen.get_size())
    frame.fill(fill)
    frame.blit(image, (0, 0))

    clock = pygame.time.Clock()

    for duration_ms, fade in ((_FADE_IN_MS, "in"), (_HOLD_MS, None), (_FADE_OUT_MS, "out")):
        start = pygame.time.get_ticks()
        while True:
            elapsed = pygame.time.get_ticks() - start
            if elapsed >= duration_ms:
                break

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return True
                if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                    return False

            if fade is None:
                alpha = 255
            else:
                t = elapsed / duration_ms
                alpha = int((t if fade == "in" else 1 - t) * 255)

            screen.fill((0, 0, 0))
            frame.set_alpha(alpha)
            screen.blit(frame, (0, 0))
            if flip:
                screen.blit(pygame.transform.rotate(screen, 180), (0, 0))
            pygame.display.flip()
            clock.tick(60)

    return False
