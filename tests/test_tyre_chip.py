"""Tests for the shared tyre compound chip (companion colour parity)."""
import os

import pygame
import pytest

from dashboard.widgets.tyre_chip import draw_chip, tyre_style


class TestTyreStyle:
    @pytest.mark.parametrize("compound, label", [
        ("Soft", "S"), ("Medium", "M"), ("Hard", "H"),
        ("Inter", "I"), ("Wet", "W"),
        ("soft", "S"),            # case-insensitive
        ("DHE", "H"), ("DHD", "H"),   # Forza compounds map to neutral hard
    ])
    def test_known_compounds(self, compound, label):
        assert tyre_style(compound)[0] == label

    def test_empty_is_none(self):
        assert tyre_style("") is None
        assert tyre_style(None) is None

    def test_unknown_gets_grey_chip_with_first_letter(self):
        label, fill, _ = tyre_style("Classic dry")
        assert label == "C"
        assert fill == (120, 124, 135)

    def test_soft_is_red_medium_is_yellow(self):
        # The F1 signal colours, matching the companion's chips exactly.
        assert tyre_style("Soft")[1] == (230, 46, 46)
        assert tyre_style("Medium")[1] == (255, 209, 46)


class TestDrawChip:
    @pytest.fixture(autouse=True)
    def _pygame(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        pygame.init()
        from dashboard.widgets import fonts
        fonts.clear_cache()
        yield
        pygame.quit()

    def test_draws_and_returns_width(self):
        from dashboard.widgets.fonts import load_ui
        surf = pygame.Surface((100, 40), depth=24)
        w = draw_chip(surf, load_ui(12), "Soft", 10, 20)
        assert w > 0
        painted = any(surf.get_at((x, y))[:3] != (0, 0, 0)
                      for x in range(10, 10 + w)
                      for y in range(20 - w // 2, 20 + w // 2))
        assert painted

    def test_empty_compound_draws_nothing(self):
        from dashboard.widgets.fonts import load_ui
        surf = pygame.Surface((100, 40), depth=24)
        assert draw_chip(surf, load_ui(12), "", 10, 20) == 0
