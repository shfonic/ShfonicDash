import pygame

from core import flip


def test_flip_pos_passthrough_when_not_flipped():
    assert flip.flip_pos((10, 20), flip=False) == (10, 20)


def test_flip_pos_maps_into_logical_space_when_flipped():
    assert flip.flip_pos((0, 0), flip=True) == (flip.WIDTH, flip.HEIGHT)
    assert flip.flip_pos((flip.WIDTH, flip.HEIGHT), flip=True) == (0, 0)
    assert flip.flip_pos((100, 50), flip=True) == (flip.WIDTH - 100, flip.HEIGHT - 50)


def test_flip_surface_noop_when_not_flipped():
    surface = pygame.Surface((flip.WIDTH, flip.HEIGHT))
    surface.fill((1, 2, 3))
    surface.set_at((0, 0), (255, 0, 0))

    flip.flip_surface(surface, flip=False)

    assert surface.get_at((0, 0)) == (255, 0, 0, 255)


def test_flip_surface_rotates_180_degrees_when_flipped():
    surface = pygame.Surface((flip.WIDTH, flip.HEIGHT))
    surface.fill((1, 2, 3))
    surface.set_at((0, 0), (255, 0, 0))

    flip.flip_surface(surface, flip=True)

    # The pixel originally at top-left should now be at bottom-right
    assert surface.get_at((flip.WIDTH - 1, flip.HEIGHT - 1)) == (255, 0, 0, 255)
    assert surface.get_at((0, 0)) == (1, 2, 3, 255)
