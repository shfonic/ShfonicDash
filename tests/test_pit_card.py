"""Tests for the mid-session pit card gate (App._maybe_show_pit_card).

The card shows the session-so-far summary when the player is stopped in
the pits during practice/qualifying with laps banked — once per pit
visit, never while driving, never in races, never over the pause path.
"""
import os

import pygame
import pytest

from core.app import App
from core.telemetry_model import TelemetryData


class _FakeSource:
    def connect(self): pass
    def read(self): return TelemetryData()
    def disconnect(self): pass


class _FakeLogger:
    def __init__(self, laps=3, active="session_x.csv"):
        self.lap_count = laps
        self.active_file = active


@pytest.fixture(autouse=True)
def _pygame():
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    pygame.init()
    from dashboard.widgets import fonts
    fonts.clear_cache()
    yield
    pygame.quit()


@pytest.fixture
def app(monkeypatch):
    a = App(_FakeSource(), show_session_summary=True)
    a._session_logger = _FakeLogger()
    shown = []
    monkeypatch.setattr(
        a, "_show_summary_for",
        lambda path, caption="SESSION SUMMARY": (
            shown.append(caption), setattr(a, "_summary_view", object())))
    a._shown = shown
    return a


def _pit(**overrides):
    base = dict(session_type="practice", in_pits=True, speed=0.0)
    base.update(overrides)
    return TelemetryData(**base)


class TestPitCardGate:
    def test_stopped_in_pits_shows_session_so_far(self, app):
        app._maybe_show_pit_card(_pit())
        assert app._shown == ["SESSION SO FAR"]

    def test_once_per_pit_visit(self, app):
        app._maybe_show_pit_card(_pit())
        app._summary_view = None   # user tapped it away
        app._maybe_show_pit_card(_pit())
        assert len(app._shown) == 1

    def test_rearms_after_leaving_pits(self, app):
        app._maybe_show_pit_card(_pit())
        app._summary_view = None
        app._maybe_show_pit_card(_pit(in_pits=False, speed=120.0))
        app._maybe_show_pit_card(_pit())
        assert len(app._shown) == 2

    def test_not_while_driving_the_pit_lane(self, app):
        app._maybe_show_pit_card(_pit(speed=60.0))
        assert app._shown == []

    def test_not_in_races(self, app):
        app._maybe_show_pit_card(_pit(session_type="race"))
        assert app._shown == []

    def test_qualifying_is_included(self, app):
        app._maybe_show_pit_card(_pit(session_type="qualifying"))
        assert app._shown == ["SESSION SO FAR"]

    def test_pause_path_owns_menu_returns(self, app):
        app._maybe_show_pit_card(_pit(game_paused=True))
        assert app._shown == []

    def test_needs_laps_banked(self, app):
        app._session_logger = _FakeLogger(laps=0)
        app._maybe_show_pit_card(_pit())
        assert app._shown == []

    def test_not_over_an_existing_overlay(self, app):
        app._summary_view = object()
        app._maybe_show_pit_card(_pit())
        assert app._shown == []

    def test_pause_summary_in_garage_counts_as_this_visits_card(self, app):
        # Menu garage return: pause path already showed a summary. Once
        # it's dismissed, the pit card must not re-show the same content.
        app._summary_view = object()
        app._maybe_show_pit_card(_pit())   # latches the visit
        app._summary_view = None           # user taps the summary away
        app._maybe_show_pit_card(_pit())
        assert app._shown == []
