"""Tests for the game menu's enabled-games filter and adaptive grid."""
import os

import pygame
import pytest

from core import game_menu
from core.game_menu import _BTN_GAP, _BTN_H, _BTN_Y, _PAD_X, GameMenu


@pytest.fixture(autouse=True)
def _pygame():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    from dashboard.widgets import fonts
    fonts.clear_cache()
    yield
    pygame.quit()


def _menu(config=None):
    screen = pygame.display.set_mode((800, 480))
    return GameMenu(screen, config or {})


class TestEnabledGames:
    def test_default_shows_all(self):
        assert len(_menu()._enabled_games()) == len(game_menu._GAMES)

    def test_disabled_games_are_hidden(self):
        m = _menu({"enabled_games": {"pcars2": False, "fh6": False}})
        ids = [g["id"] for g in m._enabled_games()]
        assert ids == ["f1_25", "fm", "gt7"]

    def test_unknown_ids_in_config_are_ignored(self):
        m = _menu({"enabled_games": {"gt99": False}})
        assert len(m._enabled_games()) == len(game_menu._GAMES)

    def test_all_disabled_falls_back_to_all(self):
        m = _menu({"enabled_games": {g["id"]: False
                                     for g in game_menu._GAMES}})
        assert len(m._enabled_games()) == len(game_menu._GAMES)


class TestAdaptiveGrid:
    def test_four_games_one_row(self):
        m = _menu({"enabled_games": {"gt7": False}})
        buttons = m._build_buttons()
        assert len(buttons) == 4
        assert len({rect.y for _, rect in buttons}) == 1
        assert all(rect.height == _BTN_H for _, rect in buttons)

    def test_full_roster_wraps_to_two_rows(self):
        buttons = _menu()._build_buttons()
        assert len(buttons) == len(game_menu._GAMES)
        assert len({rect.y for _, rect in buttons}) == 2

    def test_two_games_widen(self):
        m = _menu({"enabled_games": {"fh6": False, "fm": False, "gt7": False}})
        buttons = m._build_buttons()
        assert len(buttons) == 2
        wide = buttons[0][1].width
        four = _menu({"enabled_games": {"gt7": False}})._build_buttons()
        assert wide > four[0][1].width

    def test_tile_content_fits_inside_tiles(self):
        # Regression: with 5+ games the tiles halve in height and the
        # full-size content stack used to spill across the tile borders.
        m = _menu()
        for game, rect in m._build_buttons():
            content = m._button_content(game, rect)
            total = sum(f.size(t)[1] + gap for f, t, _c, gap in content)
            total -= content[-1][3]   # no gap after the last line
            assert total <= rect.height, game["id"]

    def test_tile_content_fits_three_row_roster(self, monkeypatch):
        fake = [dict(game_menu._GAMES[-1], id=f"g{i}", name=f"Game {i}")
                for i in range(9)]   # gt7-style tile: subtitle + platform
        monkeypatch.setattr(game_menu, "_GAMES", fake)
        m = _menu()
        for game, rect in m._build_buttons():
            content = m._button_content(game, rect)
            total = sum(f.size(t)[1] + gap for f, t, _c, gap in content)
            total -= content[-1][3]
            assert total <= rect.height, game["id"]
            assert len(content) >= 2   # abbr + name always survive

    def test_more_than_four_wraps_to_grid(self, monkeypatch):
        # Future roster (e.g. GT7): 6 games → 2 rows of up to 4, all
        # inside the original button band.
        fake = [dict(game_menu._GAMES[0], id=f"g{i}", name=f"Game {i}")
                for i in range(6)]
        monkeypatch.setattr(game_menu, "_GAMES", fake)
        buttons = _menu()._build_buttons()
        rows = sorted({rect.y for _, rect in buttons})
        assert len(rows) == 2
        for _, rect in buttons:
            assert rect.bottom <= _BTN_Y + _BTN_H
            assert rect.left >= _PAD_X
            assert rect.right <= 800 - _PAD_X
        # No overlaps
        rects = [rect for _, rect in buttons]
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                assert not a.colliderect(b.inflate(-_BTN_GAP, -_BTN_GAP))


class TestLatestBadge:
    def _rec(self, i, **over):
        from datetime import datetime, timedelta
        base = {
            "filename": f"session_{i:04d}_practice.csv",
            "date": datetime(2026, 6, 1, 19) + timedelta(days=i),
            "game": "f1_25", "car_class": "formula1",
            "track": "Silverstone", "session_type": "practice",
            "session_subtype": "", "lap_count": 10, "valid_lap_count": 8,
            "clean_lap_count": 8, "cons_band_count": 3,
            "collision_count": 0, "penalty_count": 0,
            "best_lap_time": 89.0, "perfect_lap": 0,
            "position": None, "start_position": None,
        }
        base.update(over)
        return base

    def test_unlock_found_with_title(self):
        recs = [self._rec(0, lap_count=8, valid_lap_count=8)]
        rec, title = GameMenu._latest_badge(recs)
        assert rec["filename"] == recs[0]["filename"]
        assert title == "Clean Sweep"

    def test_levels_badge_names_the_threshold(self):
        # Sub-20-lap sessions so only Century fires (Long Haul needs 20+).
        recs = [self._rec(i, lap_count=17) for i in range(6)]  # 102 laps
        rec, title = GameMenu._latest_badge(recs)
        assert "Century — 100 laps" in title

    def test_no_badges_returns_none(self):
        assert GameMenu._latest_badge(
            [self._rec(0, lap_count=5, valid_lap_count=4)]) is None
