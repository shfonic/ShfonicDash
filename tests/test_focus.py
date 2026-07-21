"""Tests for sessionlog.focus — session focus chips + verdict.

Shared (travels to the companion via sync_shared.py). Pure stdlib.
"""
from sessionlog import focus


class TestAvailableFocuses:
    def test_fixed_set_order(self):
        got = [f["id"] for f in focus.available_focuses()]
        assert got == [focus.FASTER, focus.CONSISTENCY, focus.CLEAN,
                       focus.JUST_DRIVE]

    def test_hotlap_leads_with_pace(self):
        got = [f["id"] for f in focus.available_focuses(session_type="hotlap")]
        assert got[0] == focus.FASTER
        assert focus.JUST_DRIVE in got

    def test_practice_leads_with_consistency(self):
        got = [f["id"] for f in focus.available_focuses(session_type="practice")]
        assert got[0] == focus.CONSISTENCY

    def test_race_gets_its_own_set(self):
        got = [f["id"] for f in focus.available_focuses(session_type="race")]
        assert got == [focus.CLEAN_RACE, focus.POSITIONS, focus.RACE_PACE,
                       focus.MANAGE]
        # No lap-time / free-session chips in a race.
        assert focus.FASTER not in got and focus.JUST_DRIVE not in got

    def test_unknown_type_falls_back_to_classic_set(self):
        got = [f["id"] for f in focus.available_focuses(session_type="warmup")]
        assert got == [focus.FASTER, focus.CONSISTENCY, focus.CLEAN,
                       focus.JUST_DRIVE]

    def test_faster_hint_from_goal(self):
        chips = focus.available_focuses({"prior_best": 78.412})
        faster = next(c for c in chips if c["id"] == focus.FASTER)
        assert "1:18.41" in faster["hint"]
        # Other chips carry no hint by default.
        clean = next(c for c in chips if c["id"] == focus.CLEAN)
        assert clean["hint"] == ""

    def test_no_goal_no_hints(self):
        assert all(c["hint"] == "" for c in focus.available_focuses())


class TestRecommendedFocus:
    def _rec(self, **over):
        base = {'lap_count': 8, 'valid_lap_count': 8, 'clean_lap_count': 8,
                'clean_std_dev': 0.15, 'rewind_count': 0,
                'best_lap_time': 89.0, 'theo_time': 88.95}
        base.update(over)
        return base

    def test_invalid_laps_recommend_clean(self):
        assert focus.recommended_focus(self._rec(valid_lap_count=5)) == focus.CLEAN

    def test_flashbacks_recommend_clean(self):
        assert focus.recommended_focus(self._rec(rewind_count=2)) == focus.CLEAN

    def test_theo_gap_recommends_faster(self):
        assert focus.recommended_focus(
            self._rec(best_lap_time=89.5, theo_time=89.0)) == focus.FASTER

    def test_loose_spread_recommends_consistency(self):
        assert focus.recommended_focus(
            self._rec(clean_std_dev=0.45)) == focus.CONSISTENCY

    def test_clean_first_even_with_pace_and_spread(self):
        # Completion outranks pace and consistency (grading's ladder).
        assert focus.recommended_focus(self._rec(
            valid_lap_count=5, best_lap_time=89.5, theo_time=89.0,
            clean_std_dev=0.5)) == focus.CLEAN

    def test_solid_session_recommends_nothing(self):
        assert focus.recommended_focus(self._rec()) is None

    def test_no_record_recommends_nothing(self):
        assert focus.recommended_focus(None) is None
        assert focus.recommended_focus({'lap_count': 0}) is None

    def test_available_focuses_flags_the_recommended_chip(self):
        chips = focus.available_focuses({'recommended_focus': focus.CLEAN})
        flagged = [c['id'] for c in chips if c['recommended']]
        assert flagged == [focus.CLEAN]

    def test_no_recommendation_flags_nothing(self):
        assert not any(c['recommended']
                       for c in focus.available_focuses({}))


class TestEvaluateFaster:
    def test_met_new_best(self):
        v = focus.evaluate(focus.FASTER, {"best_lap_time": 78.0},
                           prior_best=78.5)
        assert v["met"] is True
        assert "New best" in v["headline"]

    def test_not_met_off_pace(self):
        v = focus.evaluate(focus.FASTER, {"best_lap_time": 79.0},
                           prior_best=78.5)
        assert v["met"] is False
        assert "off" in v["headline"]

    def test_neutral_no_prior(self):
        v = focus.evaluate(focus.FASTER, {"best_lap_time": 78.0},
                           prior_best=None)
        assert v["met"] is None

    def test_neutral_no_lap(self):
        v = focus.evaluate(focus.FASTER, {"best_lap_time": None},
                           prior_best=78.5)
        assert v["met"] is None


class TestEvaluateConsistency:
    def test_met_tighter(self):
        v = focus.evaluate(focus.CONSISTENCY,
                           {"clean_std_dev": 0.18, "clean_lap_count": 4},
                           prior_std=0.34)
        assert v["met"] is True
        assert "±0.180s" in v["headline"]

    def test_not_met_wider(self):
        v = focus.evaluate(focus.CONSISTENCY,
                           {"clean_std_dev": 0.40, "clean_lap_count": 4},
                           prior_std=0.34)
        assert v["met"] is False

    def test_neutral_too_few_laps(self):
        v = focus.evaluate(focus.CONSISTENCY,
                           {"clean_std_dev": None, "clean_lap_count": 1},
                           prior_std=0.34)
        assert v["met"] is None

    def test_neutral_no_prior(self):
        v = focus.evaluate(focus.CONSISTENCY,
                           {"clean_std_dev": 0.20, "clean_lap_count": 3},
                           prior_std=None)
        assert v["met"] is None
        assert "baseline" in v["detail"]


class TestEvaluateClean:
    def test_met_all_clean(self):
        v = focus.evaluate(focus.CLEAN,
                           {"lap_count": 5, "valid_lap_count": 5,
                            "rewind_count": 0})
        assert v["met"] is True
        assert "All clean" in v["headline"]

    def test_not_met_invalids_and_flashbacks(self):
        v = focus.evaluate(focus.CLEAN,
                           {"lap_count": 5, "valid_lap_count": 3,
                            "rewind_count": 2})
        assert v["met"] is False
        assert "2 invalid" in v["headline"]
        assert "2 flashbacks" in v["headline"]

    def test_singular_flashback(self):
        v = focus.evaluate(focus.CLEAN,
                           {"lap_count": 3, "valid_lap_count": 3,
                            "rewind_count": 1})
        assert v["met"] is False
        assert "1 flashback" in v["headline"]
        assert "flashbacks" not in v["headline"]

    def test_neutral_no_laps(self):
        v = focus.evaluate(focus.CLEAN,
                           {"lap_count": 0, "valid_lap_count": 0,
                            "rewind_count": 0})
        assert v["met"] is None

    def test_unreliable_rewinds_treated_as_zero(self):
        # rewind_count None (pre-v0.1.133 files) → judged on invalids only.
        v = focus.evaluate(focus.CLEAN,
                           {"lap_count": 4, "valid_lap_count": 4,
                            "rewind_count": None})
        assert v["met"] is True

    def test_compares_against_previous_session_clean_rate(self):
        # 5/5 clean (100%) vs a previous session's 60% clean rate.
        v = focus.evaluate(focus.CLEAN,
                           {"lap_count": 5, "valid_lap_count": 5,
                            "rewind_count": 0, "clean_lap_count": 5},
                           prior_clean_frac=0.6)
        assert v["met"] is True
        assert "Better than your previous 60% clean" in v["detail"]

    def test_worse_than_previous_session_clean_rate(self):
        # 3/5 clean (60%) vs a previous session's 80% clean rate.
        v = focus.evaluate(focus.CLEAN,
                           {"lap_count": 5, "valid_lap_count": 3,
                            "rewind_count": 0, "clean_lap_count": 3},
                           prior_clean_frac=0.8)
        assert v["met"] is False
        assert "Your clean rate here was 80%" in v["detail"]

    def test_matches_previous_session_clean_rate(self):
        v = focus.evaluate(focus.CLEAN,
                           {"lap_count": 5, "valid_lap_count": 4,
                            "rewind_count": 0, "clean_lap_count": 4},
                           prior_clean_frac=0.8)
        assert v["met"] is True
        assert "Matches your previous 80% clean" in v["detail"]

    def test_no_prior_clean_rate_becomes_benchmark(self):
        v = focus.evaluate(focus.CLEAN,
                           {"lap_count": 5, "valid_lap_count": 5,
                            "rewind_count": 0, "clean_lap_count": 5},
                           prior_clean_frac=None)
        assert v["met"] is True
        assert "benchmark" in v["detail"]


def _hist(**overrides):
    base = {'filename': 'session_20260701_1000_hotlap.csv',
            'date': '2026-07-01T10:00:00',
            'lap_count': 5, 'clean_lap_count': 3,
            'clean_std_dev': 0.34, 'best_lap_time': 78.5}
    base.update(overrides)
    return base


class TestSessionVerdict:
    """The one entry point both apps use — priors derived from history."""

    def test_no_focus_returns_none(self):
        assert focus.session_verdict({'filename': 'x.csv'}, {}, []) is None

    def test_just_drive_returns_none(self):
        assert focus.session_verdict(
            {'filename': 'x.csv', 'focus': focus.JUST_DRIVE}, {}, []) is None

    def test_carries_title(self):
        v = focus.session_verdict(
            {'filename': 'now.csv', 'focus': focus.CLEAN},
            {'lap_count': 4, 'valid_lap_count': 4, 'rewind_count': 0,
             'clean_lap_count': 4}, [])
        assert v['title'] == 'CLEAN LAPS'

    def test_faster_uses_best_ever_from_history(self):
        # Best across ALL prior sessions (78.2), not just the latest (79.0).
        history = [_hist(filename='a.csv', date='2026-07-01', best_lap_time=78.2),
                   _hist(filename='b.csv', date='2026-07-02', best_lap_time=79.0)]
        v = focus.session_verdict(
            {'filename': 'now.csv', 'focus': focus.FASTER},
            {'best_lap_time': 78.4}, history)
        assert v['met'] is False          # 78.4 is not under the 78.2 best
        assert '1:18.200' in v['detail']

    def test_clean_uses_most_recent_prior_session(self):
        # Recency: the LAST prior session's clean rate (2/5 = 40%), not a.csv's.
        history = [_hist(filename='a.csv', date='2026-07-01',
                         lap_count=5, clean_lap_count=5),
                   _hist(filename='b.csv', date='2026-07-02',
                         lap_count=5, clean_lap_count=2)]
        v = focus.session_verdict(
            {'filename': 'now.csv', 'focus': focus.CLEAN},
            {'lap_count': 4, 'valid_lap_count': 4, 'rewind_count': 0,
             'clean_lap_count': 4}, history)
        assert v['met'] is True
        assert '40% clean' in v['detail']

    def test_current_session_row_is_ignored(self):
        # The session's own row in history must not become its own baseline.
        history = [_hist(filename='now.csv', best_lap_time=70.0)]
        v = focus.session_verdict(
            {'filename': 'now.csv', 'focus': focus.FASTER},
            {'best_lap_time': 78.4}, history)
        assert v['met'] is None           # no prior → benchmark, not "off pace"

    def test_unordered_history_is_sorted(self):
        # Rows arrive in any order; recency must come from the date.
        history = [_hist(filename='b.csv', date='2026-07-02',
                         lap_count=5, clean_lap_count=2),
                   _hist(filename='a.csv', date='2026-07-01',
                         lap_count=5, clean_lap_count=5)]
        v = focus.session_verdict(
            {'filename': 'now.csv', 'focus': focus.CLEAN},
            {'lap_count': 4, 'valid_lap_count': 4, 'rewind_count': 0,
             'clean_lap_count': 4}, history)
        assert '40% clean' in v['detail']   # b.csv is the previous session


class TestRecommendedFocusRace:
    def _race(self, **over):
        base = {'session_type': 'race', 'lap_count': 10,
                'valid_lap_count': 10, 'clean_lap_count': 10,
                'clean_std_dev': 0.15, 'rewind_count': 0,
                'collision_count': 0, 'penalty_count': 0,
                'start_position': 8, 'position': 8,
                'best_lap_time': 89.0, 'theo_time': 88.95}
        base.update(over)
        return base

    def test_contact_recommends_clean_race(self):
        assert focus.recommended_focus(self._race(collision_count=1)) \
            == focus.CLEAN_RACE

    def test_penalty_recommends_clean_race(self):
        assert focus.recommended_focus(self._race(penalty_count=2)) \
            == focus.CLEAN_RACE

    def test_lost_places_recommends_positions(self):
        assert focus.recommended_focus(self._race(position=11)) \
            == focus.POSITIONS

    def test_loose_pace_recommends_race_pace(self):
        assert focus.recommended_focus(self._race(clean_std_dev=0.45)) \
            == focus.RACE_PACE

    def test_solid_race_recommends_nothing(self):
        assert focus.recommended_focus(self._race()) is None

    def test_session_type_arg_overrides_record_type(self):
        # A practice record, but the UPCOMING session is a race.
        rec = self._race(session_type='practice', collision_count=1)
        assert focus.recommended_focus(rec, session_type='race') \
            == focus.CLEAN_RACE


class TestEvaluateRace:
    def test_clean_race_met(self):
        v = focus.evaluate(focus.CLEAN_RACE,
                           {"lap_count": 10, "collision_count": 0,
                            "penalty_count": 0, "rewind_count": 0})
        assert v["met"] is True
        assert "Clean race" in v["headline"]

    def test_clean_race_not_met_lists_incidents(self):
        v = focus.evaluate(focus.CLEAN_RACE,
                           {"lap_count": 10, "collision_count": 2,
                            "penalty_count": 1, "rewind_count": 0})
        assert v["met"] is False
        assert "2 contacts" in v["headline"]
        assert "1 penalty" in v["headline"]

    def test_positions_gained(self):
        v = focus.evaluate(focus.POSITIONS,
                           {"start_position": 10, "position": 6})
        assert v["met"] is True
        assert "+4" in v["headline"]
        assert "P10 → P6" in v["headline"]

    def test_positions_held(self):
        v = focus.evaluate(focus.POSITIONS,
                           {"start_position": 5, "position": 5})
        assert v["met"] is True
        assert "Held" in v["headline"]

    def test_positions_lost(self):
        v = focus.evaluate(focus.POSITIONS,
                           {"start_position": 5, "position": 9})
        assert v["met"] is False
        assert "-4" in v["headline"]

    def test_positions_neutral_without_data(self):
        assert focus.evaluate(focus.POSITIONS,
                              {"start_position": None,
                               "position": 5})["met"] is None

    def test_race_pace_uses_consistency_with_race_label(self):
        v = focus.evaluate(focus.RACE_PACE,
                           {"clean_std_dev": 0.18, "clean_lap_count": 6},
                           prior_std=0.34)
        assert v["met"] is True
        assert "Race pace" in v["headline"]

    def test_manage_is_neutral(self):
        v = focus.evaluate(focus.MANAGE,
                           {"lap_count": 10, "collision_count": 0})
        assert v["met"] is None


class TestEvaluateOther:
    def test_just_drive_has_no_banner(self):
        assert focus.evaluate(focus.JUST_DRIVE, {}) is None

    def test_unknown_focus(self):
        assert focus.evaluate("nonsense", {"best_lap_time": 78.0}) is None

    def test_focus_title(self):
        assert focus.focus_title(focus.CONSISTENCY) == "CONSISTENCY"
        assert focus.focus_title(focus.CLEAN_RACE) == "CLEAN RACE"
        assert focus.focus_title(focus.MANAGE) == "TYRE & FUEL"
        assert focus.focus_title("nonsense") == ""
