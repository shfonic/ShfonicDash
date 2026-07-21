"""Tests for core.pre_session — the pre-session NEXT GOAL card.

Pi-repo only (the goal engine itself is shared and tested in
tests/test_goals.py). build_pre_session() is exercised against real CSVs
in a tmp logs dir so the records index and combo lookup run for real.
"""
import os

import pygame
import pytest

from core.pre_session import PreSessionView, build_pre_session
from core.telemetry_model import TelemetryData

LAP_HEADER = ('H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,'
              'tyre_compound,fuel_remaining,fuel_per_lap,position,delta,invalid,rewinds')


def _session_csv(times, track='Monaco', session_type='hotlap',
                 started='2026-07-06T10:00:00', invalid=None, rewinds=None):
    invalid = invalid or set()
    rewinds = rewinds or set()
    rows = [
        'S,version,1',
        f'S,started_at,{started}',
        'S,game,f1_25',
        f'S,session_type,{session_type}',
        'S,car_class,formula1_2026',
        'S,car_name,McLaren',
        f'S,track,{track}',
        LAP_HEADER,
    ]
    for i, t in enumerate(times, start=1):
        inv = 1 if i in invalid else 0
        rew = 1 if i in rewinds else 0
        s1, s2, s3 = round(t * 0.31, 3), round(t * 0.33, 3), round(t * 0.36, 3)
        rows.append(f'L,{i},{t},{s1},{s2},{s3},,,,,,,,,,{inv},{rew}')
    return '\n'.join(rows) + '\n'


def _logs_with_history(tmp_path):
    (tmp_path / 'session_20260706_1000_hotlap.csv').write_text(
        _session_csv([89.2, 88.6, 88.9, 89.4, 88.7, 89.0], invalid={4},
                     rewinds={5}),
        encoding='utf-8')
    return str(tmp_path)


def _upcoming(track='Monaco', session_type='hotlap'):
    return TelemetryData(game='f1_25', car_class='formula1_2026',
                         track=track, session_type=session_type)


class TestBuildPreSession:
    def test_history_produces_goal(self, tmp_path):
        goal = build_pre_session(_logs_with_history(tmp_path), _upcoming())
        assert goal is not None
        assert goal['track'] == 'Monaco'
        assert goal['session_type'] == 'hotlap'
        assert goal['session_count'] == 1
        assert goal['missions']

    def test_no_track_returns_none(self, tmp_path):
        # PC2/Forza don't broadcast a track name — no combo, no card at all.
        goal = build_pre_session(_logs_with_history(tmp_path),
                                 _upcoming(track=''))
        assert goal is None

    def test_first_visit_returns_baseline(self, tmp_path):
        # A track with no history still gets a card — a "learn the track /
        # set a baseline" first-visit card, not nothing.
        goal = build_pre_session(_logs_with_history(tmp_path),
                                 _upcoming(track='Suzuka'))
        assert goal is not None
        assert goal['session_count'] == 0
        assert goal['prior_best'] is None
        assert goal['grade_letter'] is None
        assert goal['missions']            # generic objectives
        assert goal['track'] == 'Suzuka'

    def test_other_session_type_is_a_different_combo(self, tmp_path):
        # Different session type = different combo = no history → baseline.
        goal = build_pre_session(_logs_with_history(tmp_path),
                                 _upcoming(session_type='race'))
        assert goal['session_count'] == 0

    def test_empty_logs_dir_gives_baseline(self, tmp_path):
        goal = build_pre_session(str(tmp_path), _upcoming())
        assert goal['session_count'] == 0


class TestPreSessionDue:
    """The App trigger predicate — the actual hotlap/TT bug lived here.

    The card belongs in the garage, before the first lap. It fires on a
    paused menu OR a stationary zero-lap car (the F1 Time-Trial garage
    reports neither game_paused nor in_pits, so pausing was never the
    signal there — confirmed on-Pi: the old trigger fired on quit-to-menu
    instead of at the start). Latched once per session.
    """
    from core.app import App

    def _paused(self, track='Monaco'):
        d = _upcoming(track=track)
        d.game_paused = True
        return d

    def _garage(self, track='Monaco', session_type='hotlap', speed=0.0):
        d = _upcoming(track=track, session_type=session_type)
        d.game_paused = False
        d.speed = speed
        return d

    def test_fires_when_metadata_ready(self):
        assert self.App._pre_session_due(
            self._paused(), pre_session_shown=False, summary_active=False,
            active_file='s.csv', lap_count=0) is True

    def test_not_edge_triggered_metadata_arrives_after_pause(self):
        # Frame 1: paused but no file/track yet -> must NOT latch.
        d0 = _upcoming(track='')
        d0.game_paused = True
        assert self.App._pre_session_due(
            d0, pre_session_shown=False, summary_active=False,
            active_file=None, lap_count=0) is False
        # A later frame, still paused, now with metadata -> fires. An edge
        # on game_paused would have been missed by now; the latch is not.
        assert self.App._pre_session_due(
            self._paused(), pre_session_shown=False, summary_active=False,
            active_file='s.csv', lap_count=0) is True

    def test_latched_once_per_session(self):
        assert self.App._pre_session_due(
            self._paused(), pre_session_shown=True, summary_active=False,
            active_file='s.csv', lap_count=0) is False

    def test_suppressed_while_summary_up(self):
        assert self.App._pre_session_due(
            self._paused(), pre_session_shown=False, summary_active=True,
            active_file='s.csv', lap_count=0) is False

    def test_not_shown_with_laps_banked(self):
        # Laps done -> the pause-summary path owns this, not the goal card.
        assert self.App._pre_session_due(
            self._paused(), pre_session_shown=False, summary_active=False,
            active_file='s.csv', lap_count=3) is False

    def test_not_shown_without_track(self):
        # PC2/Forza never broadcast a track name.
        assert self.App._pre_session_due(
            self._paused(track=''), pre_session_shown=False,
            summary_active=False, active_file='s.csv', lap_count=0) is False

    def test_stationary_garage_fires_without_pause(self):
        # The Time-Trial/hotlap fix: unpaused but sitting still in the garage
        # with zero laps -> the card fires (the game never sets game_paused
        # there, so speed is the only "not driving yet" signal).
        assert self.App._pre_session_due(
            self._garage(), pre_session_shown=False, summary_active=False,
            active_file='s.csv', lap_count=0) is True

    def test_moving_car_not_due(self):
        # Already driving (out-lap) -> not the garage; don't cover the dash.
        assert self.App._pre_session_due(
            self._garage(speed=80.0), pre_session_shown=False,
            summary_active=False, active_file='s.csv', lap_count=0) is False

    def test_race_needs_a_pause_not_just_stationary(self):
        # A stationary car on the grid must NOT get a modal over the launch;
        # races only show the card when actually paused.
        assert self.App._pre_session_due(
            self._garage(session_type='race'), pre_session_shown=False,
            summary_active=False, active_file='s.csv', lap_count=0) is False
        paused_race = self._garage(session_type='race')
        paused_race.game_paused = True
        assert self.App._pre_session_due(
            paused_race, pre_session_shown=False, summary_active=False,
            active_file='s.csv', lap_count=0) is True


class TestPreSessionView:
    @pytest.fixture(autouse=True)
    def _pygame(self):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        pygame.init()
        # Earlier test files cycle pygame.init()/quit(); cached fonts from
        # a dead pygame segfault on use.
        from dashboard.widgets import fonts
        fonts.clear_cache()
        yield
        pygame.quit()

    def test_renders_goal_card(self, tmp_path):
        goal = build_pre_session(_logs_with_history(tmp_path), _upcoming())
        surface = pygame.Surface((800, 480), depth=24)
        PreSessionView(goal).render(surface)   # must not raise

    def test_renders_ungraded_history(self, tmp_path):
        (tmp_path / 'session_20260706_1000_hotlap.csv').write_text(
            _session_csv([89.2, 88.6]), encoding='utf-8')   # too few to grade
        goal = build_pre_session(str(tmp_path), _upcoming())
        assert goal is not None
        assert goal['grade_letter'] is None
        surface = pygame.Surface((800, 480), depth=24)
        PreSessionView(goal).render(surface)

    def test_renders_first_visit_baseline(self, tmp_path):
        # New track (no history) → baseline card must render cleanly.
        goal = build_pre_session(str(tmp_path), _upcoming(track='Suzuka'))
        assert goal['session_count'] == 0
        surface = pygame.Surface((800, 480), depth=24)
        PreSessionView(goal).render(surface)   # must not raise

    def test_renders_with_a_recommended_chip(self, tmp_path):
        goal = build_pre_session(_logs_with_history(tmp_path), _upcoming())
        goal['recommended_focus'] = 'clean'   # force the flag for the render
        view = PreSessionView(goal)
        surface = pygame.Surface((800, 480), depth=24)
        view.render(surface)                   # amber RECOMMENDED chip must not raise
        assert any(c[1] == 'clean' for c in view._chip_rects)

    def test_focus_chips_render_and_tap_commits(self, tmp_path):
        from sessionlog import focus
        goal = build_pre_session(_logs_with_history(tmp_path), _upcoming())
        chosen = []
        view = PreSessionView(goal, on_focus=chosen.append)
        surface = pygame.Surface((800, 480), depth=24)
        view.render(surface)                       # populates chip rects
        # The chip set is session-type-specific (hotlap here, not all FOCUSES).
        expected = focus.available_focuses(goal, goal.get("session_type"))
        assert len(view._chip_rects) == len(expected)

        rect, focus_id = view._chip_rects[1]       # second chip
        assert view.tap(rect.center) is True        # commits + dismisses
        assert chosen == [focus_id]
        assert view._selected == focus_id

    def test_tap_outside_chips_dismisses_without_focus(self, tmp_path):
        goal = build_pre_session(_logs_with_history(tmp_path), _upcoming())
        chosen = []
        view = PreSessionView(goal, on_focus=chosen.append)
        view.render(pygame.Surface((800, 480), depth=24))
        assert view.tap((5, 5)) is True             # top-left, no chip there
        assert chosen == []
        assert view._selected is None
