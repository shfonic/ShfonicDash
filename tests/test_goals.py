"""Shared tests for sessionlog.goals — the pre-session "NEXT GOAL" engine.

Run in both the ShfonicDash repo and (via sync_shared.py) the
companion app.
"""
import pytest

from sessionlog.goals import baseline_goal, pre_session_goal


def _record(**overrides):
    """A gradeable scan record; tests override what they probe."""
    base = {
        'filename':        'session_20260701_1400_practice.csv',
        'date':            '2026-07-01T14:00:00',
        'game':            'f1_25',
        'car_class':       'formula1_2026',
        'track':           'Silverstone',
        'session_type':    'practice',
        'lap_count':       12,
        'valid_lap_count': 12,
        'clean_lap_count': 12,
        'clean_std_dev':   0.30,
        'theo_time':       88.0,
        'rewind_count':    0,
        'best_lap_time':   88.2,
    }
    base.update(overrides)
    return base


class TestBaselineGoal:
    def test_shape_matches_pre_session_goal(self):
        b = baseline_goal()
        # Same keys a real goal carries, so the card renderer is happy.
        for key in ("session_count", "prior_best", "last_grade",
                    "grade_letter", "next_letter", "estimated_gain",
                    "missions"):
            assert key in b
        assert b["session_count"] == 0
        assert b["prior_best"] is None
        assert b["grade_letter"] is None

    def test_has_generic_learn_the_track_missions(self):
        titles = [m["title"] for m in baseline_goal()["missions"]]
        assert titles                      # never empty
        assert any("baseline" in t.lower() for t in titles)
        assert any("track" in t.lower() for t in titles)

    def test_lap_session_learn_track_is_a_tracked_objective(self):
        # For a hotlap/practice first visit the "Learn the track" mission
        # carries the LEARN_TRACK objective type, so it's written as an O row
        # and scored (pace-trend) in the summary.
        from sessionlog import objectives
        for stype in ("hotlap", "practice", "qualifying"):
            learn = next(m for m in baseline_goal(stype)["missions"]
                         if "track" in m["title"].lower())
            assert learn.get("type") == objectives.LEARN_TRACK

    def test_race_learn_track_is_plain_advice(self):
        # A race first visit keeps "Learn the track" as advice with no type —
        # fuel burn and tyre deg make an early-vs-late pace read meaningless.
        learn = next(m for m in baseline_goal("race")["missions"]
                     if "track" in m["title"].lower())
        assert "type" not in learn

    def test_no_session_type_leaves_learn_track_untyped(self):
        learn = next(m for m in baseline_goal()["missions"]
                     if "track" in m["title"].lower())
        assert "type" not in learn


class TestPreSessionGoal:
    def test_no_history_returns_none(self):
        assert pre_session_goal([]) is None
        assert pre_session_goal(None) is None

    def test_single_session_history(self):
        g = pre_session_goal([_record()])
        assert g['session_count'] == 1
        assert g['prior_best'] == 88.2
        assert g['grade_letter'] is not None
        assert g['missions']    # never empty with history

    def test_recommended_focus_from_last_session(self):
        # Last session had invalid laps → the card recommends the clean focus.
        from sessionlog import focus
        g = pre_session_goal([_record(valid_lap_count=8)])   # 12 laps, 8 valid
        assert g['recommended_focus'] == focus.CLEAN

    def test_next_letter_is_one_step_up(self):
        g = pre_session_goal([_record()])
        from sessionlog.goals import _LETTER_LADDER
        idx = _LETTER_LADDER.index(g['grade_letter'])
        assert g['next_letter'] == _LETTER_LADDER[idx + 1]

    def test_prior_best_is_best_across_history(self):
        g = pre_session_goal([
            _record(best_lap_time=89.0, filename='a.csv',
                    date='2026-06-01T10:00:00'),
            _record(best_lap_time=88.2, filename='b.csv',
                    date='2026-07-01T10:00:00'),
        ])
        assert g['prior_best'] == 88.2

    def test_estimated_gain_is_theo_gap_of_last_session(self):
        g = pre_session_goal([_record(best_lap_time=88.6, theo_time=88.0)])
        assert g['estimated_gain'] == pytest.approx(0.6)

    def test_tiny_theo_gap_is_not_a_goal(self):
        g = pre_session_goal([_record(best_lap_time=88.05, theo_time=88.0)])
        assert g['estimated_gain'] is None

    def test_history_order_does_not_matter(self):
        newest = _record(best_lap_time=90.0, rewind_count=2,
                         filename='b.csv', date='2026-07-01T10:00:00')
        oldest = _record(filename='a.csv', date='2026-06-01T10:00:00')
        assert (pre_session_goal([oldest, newest])['missions'] ==
                pre_session_goal([newest, oldest])['missions'])


class TestMissions:
    def _titles(self, g):
        return [m['title'] for m in g['missions']]

    def test_invalid_laps_produce_valid_lap_mission(self):
        g = pre_session_goal([_record(valid_lap_count=8, clean_lap_count=8)])
        assert 'Complete 3 consecutive valid laps' in self._titles(g)

    def test_rewinds_produce_no_flashback_mission(self):
        g = pre_session_goal([_record(rewind_count=3, clean_lap_count=9)])
        assert 'No flashbacks this session' in self._titles(g)

    def test_clean_history_offers_beat_best(self):
        g = pre_session_goal([_record(best_lap_time=88.1, theo_time=88.0)])
        assert any(t.startswith('Beat 1:28.1') for t in self._titles(g))

    def test_missions_capped_at_three(self):
        g = pre_session_goal([_record(valid_lap_count=6, clean_lap_count=5,
                                      rewind_count=4, clean_std_dev=0.8,
                                      best_lap_time=89.5, theo_time=88.0)])
        assert len(g['missions']) == 3

    def test_every_mission_has_icon_title_detail(self):
        g = pre_session_goal([_record(valid_lap_count=8, rewind_count=1)])
        for m in g['missions']:
            assert m['icon'] and m['title'] and m['detail']

    def test_ungradeable_history_still_gives_missions(self):
        # Too few laps to grade — counts still back missions.
        g = pre_session_goal([_record(lap_count=2, valid_lap_count=1,
                                      clean_lap_count=1)])
        assert g['last_grade'] is None
        assert g['grade_letter'] is None
        assert 'Complete 3 consecutive valid laps' in self._titles(g)

    def test_single_assist_used_produces_reduce_reliance_mission(self):
        g = pre_session_goal([_record(tc_used_lap_count=3)])
        assert 'Reduce assist reliance' in self._titles(g)
        mission = next(m for m in g['missions']
                       if m['title'] == 'Reduce assist reliance')
        assert mission['detail'] == 'TC was on last session — try a lap with it off'
        assert mission['icon'] == '🎚'

    def test_multiple_assists_used_named_together(self):
        g = pre_session_goal([_record(racing_line_used_lap_count=2,
                                      tc_used_lap_count=1,
                                      abs_used_lap_count=4)])
        mission = next(m for m in g['missions']
                       if m['title'] == 'Reduce assist reliance')
        assert mission['detail'] == (
            'the racing line, TC and ABS were on last session — try a lap '
            'with them off')

    def test_no_assist_usage_omits_mission(self):
        g = pre_session_goal([_record()])   # _record() has no assist counts
        assert 'Reduce assist reliance' not in self._titles(g)

    def test_assist_mission_absent_for_history_predating_the_feature(self):
        # Old scan records have no assist_*_used_lap_count keys at all.
        record = _record()
        for key in ('tc_used_lap_count', 'abs_used_lap_count',
                    'racing_line_used_lap_count',
                    'gearbox_assist_used_lap_count'):
            record.pop(key, None)
        g = pre_session_goal([record])
        assert 'Reduce assist reliance' not in self._titles(g)

    def test_track_limit_hotspot_produces_watch_your_line_mission(self):
        hotspot = {'label': 'Raidillon', 'count': 3, 'total': 4}
        g = pre_session_goal([_record()], track_limit_hotspot=hotspot)
        assert 'Watch your line' in self._titles(g)
        mission = next(m for m in g['missions'] if m['title'] == 'Watch your line')
        assert mission['detail'] == (
            'Raidillon — 3 of 4 track-limits warnings there last session')
        assert mission['icon'] == '⚠️'

    def test_no_track_limit_hotspot_omits_mission(self):
        g = pre_session_goal([_record()])   # default: no hotspot arg
        assert 'Watch your line' not in self._titles(g)
        g2 = pre_session_goal([_record()], track_limit_hotspot=None)
        assert 'Watch your line' not in self._titles(g2)

    def test_line_hotspot_produces_tighten_your_line_mission(self):
        line_hot = {'label': 'Maggotts', 'offset_m': 2.1}
        g = pre_session_goal(
            [_record(best_lap_time=88.0, theo_time=88.0, clean_std_dev=0.10)],
            line_hotspot=line_hot)
        assert 'Tighten your line' in self._titles(g)
        mission = next(m for m in g['missions']
                       if m['title'] == 'Tighten your line')
        assert 'Maggotts' in mission['detail']
        assert mission['type'] == 'corner_line'
        assert mission['target'] == 'Maggotts'
        assert mission['baseline'] == 2.1

    def test_no_line_hotspot_omits_mission(self):
        g = pre_session_goal([_record()])
        assert 'Tighten your line' not in self._titles(g)


def _race_record(**overrides):
    base = {
        'filename':        'session_20260701_1600_race.csv',
        'date':            '2026-07-01T16:00:00',
        'game':            'f1_25',
        'car_class':       'formula1_2026',
        'track':           'Silverstone',
        'session_type':    'race',
        'lap_count':       15,
        'valid_lap_count': 15,
        'clean_lap_count': 15,
        'clean_std_dev':   0.30,
        'rewind_count':    0,
        'collision_count': 0,
        'penalty_count':   0,
        'start_position':  8,
        'position':        8,
        'best_lap_time':   88.2,
        'theo_time':       88.0,
    }
    base.update(overrides)
    return base


class TestRaceMissions:
    """Races get craft/position/pace missions, not the lap-time set."""

    def _titles(self, g):
        return [m['title'] for m in g['missions']]

    def test_incidents_produce_clean_race_mission(self):
        from sessionlog import objectives
        g = pre_session_goal([_race_record(collision_count=1, penalty_count=1)])
        assert 'Bring home a clean race' in self._titles(g)
        types = [m.get('type') for m in g['missions']]
        assert objectives.FINISH_CLEAN in types

    def test_lost_places_produce_positions_mission(self):
        from sessionlog import objectives
        g = pre_session_goal([_race_record(start_position=6, position=11)])
        titles = self._titles(g)
        assert any('Finish no worse' in t for t in titles)
        assert objectives.GAIN_POSITIONS in [m.get('type') for m in g['missions']]

    def test_race_never_offers_lap_time_missions(self):
        # A clean race that gained places → no "beat time" / "put the sectors
        # together" lap-chasing missions leak in.
        g = pre_session_goal([_race_record(position=4)])
        titles = self._titles(g)
        assert not any('Beat' in t or 'sectors' in t.lower() for t in titles)

    def test_session_type_arg_overrides_record_type(self):
        # Even if the history rows are tagged practice, an upcoming race gets
        # race missions.
        g = pre_session_goal([_race_record(session_type='practice',
                                           collision_count=2)],
                             session_type='race')
        assert 'Bring home a clean race' in self._titles(g)

    def test_race_missions_capped_at_three(self):
        g = pre_session_goal([_race_record(collision_count=2, penalty_count=1,
                                           rewind_count=2, clean_std_dev=0.9,
                                           start_position=4, position=12)])
        assert len(g['missions']) <= 3
