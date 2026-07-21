"""Shared tests for sessionlog.debrief — the post-session driver debrief.

Run in both the ShfonicDash repo and (via sync_shared.py) the
companion app.
"""
from sessionlog.debrief import (
    QUESTIONS,
    answer_label,
    debrief_lines,
    debrief_qa,
    select_questions,
)
from sessionlog.parser import parse


def _facts(**overrides):
    base = {
        'lap_count':       10,
        'valid_lap_count': 10,
        'clean_lap_count': 10,
        'best_lap_time':   88.2,
        'theo_time':       88.0,
        'rewind_count':    0,
    }
    base.update(overrides)
    return base


class TestSelectQuestions:
    def _ids(self, facts, prior=None):
        return [q["id"] for q in select_questions(facts, prior)]

    def test_clean_session_asks_only_the_two_base_questions(self):
        assert self._ids(_facts()) == ["feeling", "goal"]

    def test_never_more_than_three_questions(self):
        # Everything triggers at once — still one conditional.
        ids = self._ids(_facts(valid_lap_count=5, rewind_count=4,
                               best_lap_time=89.0, theo_time=88.0),
                        prior=90.0)
        assert len(ids) == 3

    def test_new_pb_outranks_everything(self):
        ids = self._ids(_facts(valid_lap_count=5, rewind_count=4),
                        prior=99.0)
        assert ids[2] == "pb_change"

    def test_invalid_laps_ask_why(self):
        assert self._ids(_facts(valid_lap_count=7))[2] == "invalid_cause"

    def test_rewinds_ask_why(self):
        assert self._ids(_facts(rewind_count=3))[2] == "rewind_cause"

    def test_big_theo_gap_asks_what_stopped_you(self):
        assert self._ids(_facts(best_lap_time=88.8))[2] == "theo_gap"

    def test_one_invalid_lap_is_not_interrogated(self):
        assert self._ids(_facts(valid_lap_count=9)) == ["feeling", "goal"]

    def test_empty_facts_are_safe(self):
        assert self._ids({}) == ["feeling", "goal"]
        assert self._ids(None) == ["feeling", "goal"]

    def test_focus_set_drops_the_goal_question(self):
        # The driver committed a focus pre-session — don't re-ask the goal.
        ids = [q["id"] for q in select_questions(_facts(), focus_id="clean")]
        assert ids == ["feeling"]

    def test_just_drive_focus_still_asks_goal(self):
        ids = [q["id"] for q in
               select_questions(_facts(), focus_id="just_drive")]
        assert ids == ["feeling", "goal"]

    def test_focus_set_keeps_the_reaction_question(self):
        ids = [q["id"] for q in
               select_questions(_facts(valid_lap_count=7), focus_id="clean")]
        assert ids == ["feeling", "invalid_cause"]

    def test_dominant_corner_asks_corner_trouble_naming_it(self):
        qs = select_questions(_facts(valid_lap_count=8), location="Turn 8")
        assert [q["id"] for q in qs] == ["feeling", "goal", "corner_trouble"]
        assert "Turn 8" in qs[2]["text"]

    def test_corner_trouble_needs_an_invalid_lap(self):
        # A clean session at a mapped track doesn't get the corner question.
        ids = [q["id"] for q in
               select_questions(_facts(), location="Turn 8")]
        assert ids == ["feeling", "goal"]

    def test_new_pb_outranks_corner_trouble(self):
        qs = select_questions(_facts(valid_lap_count=8), prior_best=99.0,
                              location="Turn 8")
        assert qs[-1]["id"] == "pb_change"

    def test_corner_trouble_base_text_has_no_raw_placeholder(self):
        assert "{location}" not in QUESTIONS["corner_trouble"]["text"]


class TestSessionTypeReactions:
    """The reaction ladder branches on facts['session_type']."""

    def _ids(self, stype, prior=None, **facts):
        base = {'session_type': stype, 'lap_count': 10,
                'valid_lap_count': 10, 'clean_lap_count': 10,
                'best_lap_time': 88.2, 'theo_time': 88.1, 'rewind_count': 0}
        base.update(facts)
        return [q["id"] for q in select_questions(base, prior)]

    # ── hotlap ──────────────────────────────────────────────────────────
    def test_hotlap_theo_gap_outranks_rewinds(self):
        ids = self._ids("hotlap", best_lap_time=88.8, rewind_count=4)
        assert ids[-1] == "theo_gap"

    def test_hotlap_rewinds_when_no_theo_gap(self):
        ids = self._ids("hotlap", best_lap_time=88.15, rewind_count=4)
        assert ids[-1] == "rewind_cause"

    # ── qualifying ──────────────────────────────────────────────────────
    def test_quali_theo_gap_first(self):
        assert self._ids("qualifying", best_lap_time=88.8)[-1] == "theo_gap"

    def test_quali_cost_when_mistakes_but_no_gap(self):
        ids = self._ids("qualifying", best_lap_time=88.12, rewind_count=1)
        assert ids[-1] == "quali_cost"

    def test_quali_clean_no_reaction(self):
        assert self._ids("qualifying", best_lap_time=88.12) == \
            ["feeling", "goal"]

    # ── practice ────────────────────────────────────────────────────────
    def test_practice_invalids_ask_why(self):
        assert self._ids("practice", valid_lap_count=6)[-1] == "invalid_cause"

    # ── race ────────────────────────────────────────────────────────────
    def test_race_uses_race_goal(self):
        ids = self._ids("race", collision_count=0, penalty_count=0,
                        start_position=8, position=8)
        assert ids[:2] == ["feeling", "goal_race"]

    def test_race_contact_asks_fault(self):
        assert self._ids("race", collision_count=1)[-1] == "contact_fault"

    def test_race_penalty_when_no_contact(self):
        ids = self._ids("race", collision_count=0, penalty_count=2)
        assert ids[-1] == "penalty_cause"

    def test_race_lost_places_asks_where(self):
        ids = self._ids("race", collision_count=0, penalty_count=0,
                        start_position=5, position=9)
        assert ids[-1] == "positions_lost"

    def test_race_clean_result_asks_about_start(self):
        ids = self._ids("race", collision_count=0, penalty_count=0,
                        start_position=8, position=6)
        assert ids[-1] == "race_start"

    def test_race_focus_drops_goal_keeps_reaction(self):
        base = {'session_type': 'race', 'lap_count': 10, 'collision_count': 1}
        ids = [q["id"] for q in select_questions(base, focus_id="clean_race")]
        assert ids == ["feeling", "contact_fault"]


class TestAnswerLabels:
    def test_known_answer(self):
        assert answer_label("feeling", "frustrated") == "Frustrated"

    def test_unknown_answer_falls_back_to_readable_id(self):
        assert answer_label("feeling", "very_spicy") == "very spicy"
        assert answer_label("brand_new_question", "some_answer") == "some answer"

    def test_every_bank_option_has_a_label(self):
        for q in QUESTIONS.values():
            for aid, _ in q["options"]:
                assert answer_label(q["id"], aid)


class TestDebriefLines:
    def test_lines_from_parsed_session(self):
        text = ("S,game,f1_25\n"
                "H,lap_num,lap_time\nL,1,88.5\n"
                "D,feeling,frustrated\nD,goal,consistency\n"
                "D,invalid_cause,track_limits\n")
        session = parse(text)
        assert session["debrief"] == {"feeling": "frustrated",
                                      "goal": "consistency",
                                      "invalid_cause": "track_limits"}
        lines = debrief_lines(session)
        assert "Driver felt frustrated after the session." in lines
        assert any("improve consistency" in line for line in lines)
        assert any("track limits" in line for line in lines)

    def test_no_debrief_no_lines(self):
        session = parse("S,game,f1_25\nH,lap_num,lap_time\nL,1,88.5\n")
        assert session["debrief"] == {}
        assert debrief_lines(session) == []


class TestDebriefQA:
    def test_qa_pairs_in_asked_order_with_real_question_text(self):
        text = ("S,game,f1_25\n"
                "H,lap_num,lap_time\nL,1,88.5\n"
                "D,goal,consistency\nD,feeling,frustrated\n"
                "D,invalid_cause,track_limits\n")
        session = parse(text)
        qa = debrief_qa(session)
        # "feeling" was asked before "goal" before "invalid_cause",
        # regardless of the order the D rows were written.
        assert [q for q, _ in qa] == [
            QUESTIONS["feeling"]["text"],
            QUESTIONS["goal"]["text"],
            QUESTIONS["invalid_cause"]["text"],
        ]
        assert ("Frustrated" in a for q, a in qa if "feeling" in q.lower())
        answers = dict(qa)
        assert answers[QUESTIONS["feeling"]["text"]] == "Frustrated"
        assert answers[QUESTIONS["invalid_cause"]["text"]] == "Track limits"

    def test_no_debrief_no_pairs(self):
        session = parse("S,game,f1_25\nH,lap_num,lap_time\nL,1,88.5\n")
        assert debrief_qa(session) == []

    def test_unknown_question_id_skipped(self):
        # A file from a newer app version with a question this one
        # doesn't know — skipped rather than crashing.
        session = parse("S,game,f1_25\nH,lap_num,lap_time\nL,1,88.5\n"
                        "D,feeling,good\nD,brand_new_question,whatever\n")
        qa = debrief_qa(session)
        assert len(qa) == 1
        assert qa[0][0] == QUESTIONS["feeling"]["text"]
