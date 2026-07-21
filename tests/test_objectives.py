"""
Tests for sessionlog.objectives — tracked-objective serialization and
evaluation, plus the O-row round-trip through the parser.

Shared test: lives canonically in ShfonicDash/tests/ and is copied
into the companion repo by sync_shared.py.
"""

from sessionlog import goals, objectives
from sessionlog.objectives import evaluate, evaluate_all, make, to_row
from sessionlog.parser import parse


class TestSerialization:

    def test_to_row_renders_cells(self):
        assert to_row(make(objectives.BEAT_TIME, target=78.412)) == \
            ["O", "beat_time", "78.412", ""]
        assert to_row(make(objectives.CLEAN_STREAK, target=3, baseline=1)) == \
            ["O", "clean_streak", "3", "1"]
        assert to_row(make(objectives.CORNER_LIMITS,
                           target="Turn 8", baseline=5)) == \
            ["O", "corner_limits", "Turn 8", "5"]

    def test_o_rows_round_trip_through_parser(self):
        csv_text = (
            "S,session_type,hotlap\n"
            "F,clean\n"
            "O,clean_streak,3,1\n"
            "O,beat_time,78.412,\n"
        )
        session = parse(csv_text, filename="session_20260101_1200_hotlap.csv")
        assert session["objectives"] == [
            {"type": "clean_streak", "target": "3", "baseline": "1"},
            {"type": "beat_time", "target": "78.412", "baseline": ""},
        ]

    def test_flat_format_has_empty_objectives(self):
        text = ('lap_num,lap_time,s1,s2,s3,car_class,session_type,game\n'
                '1,77.503,,,,gt3,practice,acc\n')
        assert parse(text)["objectives"] == []


class TestEvaluate:

    def test_clean_streak_met(self):
        v = evaluate(make(objectives.CLEAN_STREAK, target=3),
                     {"clean_streak": 4})
        assert v["met"] is True
        assert "4 clean laps in a row" in v["headline"]

    def test_clean_streak_missed_but_progress(self):
        v = evaluate(make(objectives.CLEAN_STREAK, target=3),
                     {"clean_streak": 2})
        assert v["met"] is False
        assert "Best run 2" in v["headline"]

    def test_clean_streak_neutral_without_any_clean_lap(self):
        v = evaluate(make(objectives.CLEAN_STREAK, target=3),
                     {"clean_streak": 0})
        assert v["met"] is None

    def test_no_flashbacks_met(self):
        v = evaluate(make(objectives.NO_FLASHBACKS, baseline=3),
                     {"rewind_count": 0})
        assert v["met"] is True
        assert "Down from 3" in v["detail"]

    def test_no_flashbacks_missed(self):
        v = evaluate(make(objectives.NO_FLASHBACKS, baseline=3),
                     {"rewind_count": 1})
        assert v["met"] is False
        assert "1 flashback used" in v["headline"]

    def test_beat_time_met(self):
        v = evaluate(make(objectives.BEAT_TIME, target=78.5),
                     {"best_lap_time": 78.2})
        assert v["met"] is True
        assert "New best" in v["headline"]

    def test_beat_time_missed(self):
        v = evaluate(make(objectives.BEAT_TIME, target=78.5),
                     {"best_lap_time": 78.9})
        assert v["met"] is False

    def test_convert_sectors_met_when_lap_reaches_theoretical(self):
        v = evaluate(make(objectives.CONVERT_SECTORS, target=78.0),
                     {"best_lap_time": 77.9})
        assert v["met"] is True

    def test_tighten_spread_met(self):
        v = evaluate(make(objectives.TIGHTEN_SPREAD, baseline=0.40),
                     {"clean_std_dev": 0.25, "clean_lap_count": 4})
        assert v["met"] is True

    def test_corner_limits_improved(self):
        obj = make(objectives.CORNER_LIMITS, target="Turn 8", baseline=5)
        v = evaluate(obj, {}, corner_warnings={"Turn 8": 2})
        assert v["met"] is True
        assert "Down from 5" in v["detail"]

    def test_corner_limits_clean(self):
        obj = make(objectives.CORNER_LIMITS, target="Turn 8", baseline=5)
        v = evaluate(obj, {}, corner_warnings={})
        assert v["met"] is True
        assert "Clean at Turn 8" in v["headline"]

    def test_corner_limits_neutral_without_counts(self):
        obj = make(objectives.CORNER_LIMITS, target="Turn 8", baseline=5)
        assert evaluate(obj, {})["met"] is None

    def test_corner_line_improved(self):
        obj = make(objectives.CORNER_LINE, target="Turn 8", baseline=2.4)
        v = evaluate(obj, {}, corner_line_dev={"Turn 8": 1.1})
        assert v["met"] is True
        assert "1.1m off at Turn 8" in v["headline"]
        assert "2.4m" in v["detail"]

    def test_corner_line_missed(self):
        obj = make(objectives.CORNER_LINE, target="Turn 8", baseline=2.0)
        v = evaluate(obj, {}, corner_line_dev={"Turn 8": 2.6})
        assert v["met"] is False

    def test_corner_line_neutral_without_deviations(self):
        obj = make(objectives.CORNER_LINE, target="Turn 8", baseline=2.0)
        assert evaluate(obj, {})["met"] is None

    def test_corner_line_neutral_when_corner_not_driven(self):
        obj = make(objectives.CORNER_LINE, target="Turn 8", baseline=2.0)
        assert evaluate(obj, {}, corner_line_dev={"Turn 3": 1.0})["met"] is None

    def test_finish_clean_met(self):
        v = evaluate(make(objectives.FINISH_CLEAN, target=0, baseline=3),
                     {"collision_count": 0, "penalty_count": 0,
                      "rewind_count": 0})
        assert v["met"] is True
        assert "Clean race" in v["headline"]
        assert "Down from 3" in v["detail"]

    def test_finish_clean_missed_counts_incidents(self):
        v = evaluate(make(objectives.FINISH_CLEAN, baseline=1),
                     {"collision_count": 2, "penalty_count": 1,
                      "rewind_count": 0})
        assert v["met"] is False
        assert "3 incidents" in v["headline"]

    def test_finish_clean_neutral_when_untracked(self):
        v = evaluate(make(objectives.FINISH_CLEAN),
                     {"collision_count": None, "penalty_count": None})
        assert v["met"] is None

    def test_gain_positions_met(self):
        v = evaluate(make(objectives.GAIN_POSITIONS, baseline=4),
                     {"start_position": 10, "position": 6})
        assert v["met"] is True
        assert "+4" in v["headline"]
        assert "P10 → P6" in v["headline"]

    def test_gain_positions_held(self):
        v = evaluate(make(objectives.GAIN_POSITIONS),
                     {"start_position": 5, "position": 5})
        assert v["met"] is True
        assert "Held" in v["headline"]

    def test_gain_positions_missed(self):
        v = evaluate(make(objectives.GAIN_POSITIONS),
                     {"start_position": 5, "position": 9})
        assert v["met"] is False

    def test_gain_positions_neutral_without_data(self):
        assert evaluate(make(objectives.GAIN_POSITIONS),
                        {"position": 5})["met"] is None

    def test_learn_track_met_when_pace_comes_down(self):
        v = evaluate(make(objectives.LEARN_TRACK), {},
                     progression_facts={"pace_trend": -0.42})
        assert v["met"] is True
        assert "0.42" in v["detail"]

    def test_learn_track_missed_when_pace_drifts_slower(self):
        v = evaluate(make(objectives.LEARN_TRACK), {},
                     progression_facts={"pace_trend": 0.30})
        assert v["met"] is False
        assert "0.30" in v["detail"]

    def test_learn_track_neutral_when_pace_flat(self):
        v = evaluate(make(objectives.LEARN_TRACK), {},
                     progression_facts={"pace_trend": 0.02})
        assert v["met"] is None
        assert "steady" in v["headline"].lower()

    def test_learn_track_neutral_without_a_trend(self):
        # Too few clean laps: progression can't read a trend.
        assert evaluate(make(objectives.LEARN_TRACK), {},
                        progression_facts={"pace_trend": None})["met"] is None
        assert evaluate(make(objectives.LEARN_TRACK), {})["met"] is None

    def test_unknown_type_returns_none(self):
        assert evaluate(make("mystery"), {}) is None


class TestEvaluateAll:

    def test_orders_and_drops_unknown(self):
        objs = [make("mystery"),
                make(objectives.BEAT_TIME, target=78.5),
                make(objectives.CLEAN_STREAK, target=3)]
        facts = {"clean_streak": 3, "best_lap_time": 79.0}
        result = evaluate_all(objs, facts)
        # clean_streak sorts before beat_time; mystery dropped.
        assert [r["type"] for r in result] == ["clean_streak", "beat_time"]

    def test_learn_track_scored_from_progression_facts(self):
        objs = [make(objectives.LEARN_TRACK)]
        result = evaluate_all(objs, {},
                              progression_facts={"pace_trend": -0.3})
        assert len(result) == 1
        assert result[0]["type"] == "learn_track"
        assert result[0]["met"] is True


class TestGoalsIntegration:

    def test_objectives_for_extracts_machine_missions(self):
        missions = [
            {"icon": "🎯", "title": "Focus", "detail": "..."},   # no type
            {"title": "x", "type": objectives.CLEAN_STREAK,
             "target": 3, "baseline": 1},
            {"title": "y", "type": objectives.BEAT_TIME, "target": 78.4},
        ]
        objs = goals.objectives_for(missions)
        assert [o["type"] for o in objs] == ["clean_streak", "beat_time"]
        assert objs[0]["target"] == 3
