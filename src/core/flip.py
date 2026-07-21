"""Shared helpers for the 180° software display-flip feature.

The flip is applied as a final whole-frame rotation right before
``pygame.display.flip()``. Any screen that does this must also map
incoming mouse/touch coordinates back into the same un-rotated
("logical") space before hit-testing, otherwise clicks land on the
wrong element.
"""
import pygame

WIDTH, HEIGHT = 800, 480


def flip_pos(pos: tuple[int, int], flip: bool) -> tuple[int, int]:
    """Map a raw mouse/touch position into logical (un-rotated) space."""
    if not flip:
        return pos
    x, y = pos
    return (WIDTH - x, HEIGHT - y)


def flip_surface(screen: pygame.Surface, flip: bool) -> None:
    """Rotate the fully-rendered frame 180° in place, if flip is on."""
    if flip:
        screen.blit(pygame.transform.rotate(screen, 180), (0, 0))
