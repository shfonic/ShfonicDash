"""
Shfonic Dash sessionlog — driver debrief (shared library; canonical home
is ShfonicDash/src/sessionlog/, vendored into the companion app by
sync_shared.py — see the package docstring).

The post-session debrief is the short exchange a race engineer has with a
driver in the pits: 2–3 multiple-choice taps, never more. Feeling is always
asked; the driver's goal is asked ONLY when no pre-session focus was
committed (an ``F`` row) — re-asking "what was your goal?" when the driver
already picked one on the NEXT GOAL card is redundant, so a focused session
skips it. Then at most ONE reaction question is added, chosen from what
actually happened in the session (a corner that kept catching them out, a
new PB, invalid laps, …) — so the questionnaire is adaptive rather than a
survey.

Answers are stored in the session CSV as `D` rows (`D,<question_id>,
<answer_id>`, appended after the Z rows once the session has closed) and
exposed by the parser as session["debrief"] = {question_id: answer_id}.
Subjective context like "driver was frustrated despite improving PB" is
gold for coaching — see debrief_lines() for the share-text rendering.
"""

# ---------------------------------------------------------------------------
# Question bank
#
# Each question: {"id", "text", "options": [(answer_id, label), ...]}.
# Ids are stable identifiers written to CSVs — never rename them; add new
# ones instead. Labels are display defaults; UIs may restyle.
# ---------------------------------------------------------------------------

QUESTIONS = {
    "feeling": {
        "id": "feeling",
        "text": "How are you feeling?",
        "options": [
            ("great", "Great"),
            ("good", "Good"),
            ("neutral", "Neutral"),
            ("frustrated", "Frustrated"),
            ("tired", "Tired"),
        ],
    },
    "goal": {
        "id": "goal",
        "text": "What was your goal today?",
        "options": [
            ("learn_track", "Learn the track"),
            ("pace", "Improve pace"),
            ("consistency", "Improve consistency"),
            ("race_prep", "Prepare for a race"),
            ("setup", "Test setup"),
            ("fun", "Just having fun"),
        ],
    },
    "pb_change": {
        "id": "pb_change",
        "text": "New personal best — what made the difference?",
        "options": [
            ("braking", "Better braking"),
            ("line", "Better racing line"),
            ("exits", "Better exits"),
            ("confidence", "More confidence"),
            ("setup", "Setup changes"),
            ("not_sure", "Not sure"),
        ],
    },
    "invalid_cause": {
        "id": "invalid_cause",
        "text": "What caused most of the invalid laps?",
        "options": [
            ("track_limits", "Track limits"),
            ("spin", "Spin"),
            ("lockup", "Lock-up"),
            ("avoiding", "Avoiding another car"),
            ("pushing", "Pushing too hard"),
            ("not_sure", "Not sure"),
        ],
    },
    "corner_trouble": {
        "id": "corner_trouble",
        # select_questions swaps "That corner" for the specific corner name
        # when one dominated the session's mistakes. The base text stays
        # placeholder-free so any consumer showing it raw (history Q&A) reads
        # cleanly. The stored answer is the cause, not the corner.
        "text": "That corner kept catching you out — what's going wrong there?",
        "options": [
            ("brake_late", "Braking too late"),
            ("entry_speed", "Too much entry speed"),
            ("power_early", "On power too early"),
            ("kerb", "Kerb unsettles it"),
            ("line", "Wrong line"),
            ("not_sure", "Not sure"),
        ],
    },
    "rewind_cause": {
        "id": "rewind_cause",
        "text": "Why did you rewind?",
        "options": [
            ("braking_point", "Missed braking point"),
            ("spin", "Spin"),
            ("track_limits", "Track limits"),
            ("experimenting", "Experimenting"),
            ("learning", "Learning the track"),
            ("interrupted", "Interrupted"),
        ],
    },
    "theo_gap": {
        "id": "theo_gap",
        "text": "What stopped you putting the lap together?",
        "options": [
            ("track_limits", "Track limits"),
            ("small_mistakes", "Small mistakes"),
            ("pressure", "Pressure"),
            ("no_chance", "Didn't get another chance"),
            ("consistency", "Consistency"),
            ("not_sure", "Not sure"),
        ],
    },
    # ── Qualifying ──────────────────────────────────────────────────────
    "quali_cost": {
        "id": "quali_cost",
        "text": "What cost you the lap?",
        "options": [
            ("traffic", "Traffic"),
            ("track_limits", "Track limits"),
            ("pressure", "Pressure"),
            ("small_mistakes", "Small mistakes"),
            ("no_clean_lap", "No clean lap"),
            ("not_sure", "Not sure"),
        ],
    },
    # ── Race ────────────────────────────────────────────────────────────
    # A race's goal isn't a lap time — it's a result. Asked in place of the
    # lap-session "goal" question when no focus was committed.
    "goal_race": {
        "id": "goal_race",
        "text": "What was your goal for this race?",
        "options": [
            ("finish_clean", "Finish clean"),
            ("positions", "Gain positions"),
            ("points", "Score points"),
            ("racecraft", "Practice racecraft"),
            ("pace", "Race pace"),
            ("fun", "Just racing"),
        ],
    },
    "race_start": {
        "id": "race_start",
        "text": "How was your start?",
        "options": [
            ("made_places", "Made places"),
            ("held", "Held position"),
            ("lost_places", "Lost places"),
            ("caution", "Caution / chaos"),
            ("not_sure", "Not sure"),
        ],
    },
    "contact_fault": {
        "id": "contact_fault",
        "text": "The contact — how would you call it?",
        "options": [
            ("my_mistake", "My mistake"),
            ("racing_incident", "Racing incident"),
            ("hit_by_other", "Hit by another"),
            ("unavoidable", "Unavoidable"),
            ("not_sure", "Not sure"),
        ],
    },
    "penalty_cause": {
        "id": "penalty_cause",
        "text": "What drew the penalties?",
        "options": [
            ("track_limits", "Track limits"),
            ("contact", "Contact"),
            ("corner_cut", "Cutting a corner"),
            ("speeding_pits", "Pit speeding"),
            ("jump_start", "Jump start"),
            ("not_sure", "Not sure"),
        ],
    },
    "positions_lost": {
        "id": "positions_lost",
        "text": "You lost places — where did it slip away?",
        "options": [
            ("start", "The start"),
            ("traffic", "Stuck in traffic"),
            ("pace", "Not enough pace"),
            ("mistake", "A mistake"),
            ("tyres", "Tyres went off"),
            ("not_sure", "Not sure"),
        ],
    },
}

# Conditional trigger thresholds
_THEO_GAP_TRIGGER = 0.5    # seconds between best and theoretical
_MIN_INVALID      = 2      # invalid laps before asking why
_MIN_REWINDS      = 2      # rewinds before asking why

# Share-text phrasing per question (see debrief_lines)
_LINE_TEMPLATES = {
    "feeling":       "Driver felt {answer} after the session.",
    "goal":          "Driver's stated goal: {answer}.",
    "goal_race":     "Driver's race goal: {answer}.",
    "pb_change":     "Driver credits the new personal best to: {answer}.",
    "invalid_cause": "Driver attributes most invalid laps to: {answer}.",
    "corner_trouble": "Driver's read on the corner that kept catching them "
                      "out: {answer}.",
    "rewind_cause":  "Driver's reason for rewinding: {answer}.",
    "theo_gap":      "What stopped a complete lap, per the driver: {answer}.",
    "quali_cost":    "What cost the qualifying lap, per the driver: {answer}.",
    "race_start":    "Driver's read on the start: {answer}.",
    "contact_fault": "Driver's call on the contact: {answer}.",
    "penalty_cause": "Driver attributes the penalties to: {answer}.",
    "positions_lost": "Where the driver lost places: {answer}.",
}

# Canonical asked-order for share text / Q&A rendering — feeling, then the
# goal, then the reaction questions grouped by session type.
_QUESTION_ORDER = (
    "feeling", "goal", "goal_race", "pb_change", "corner_trouble",
    "invalid_cause", "rewind_cause", "theo_gap", "quali_cost",
    "race_start", "contact_fault", "penalty_cause", "positions_lost",
)


def select_questions(facts, prior_best=None, focus_id=None, location=None):
    """The questions to ask for one finished session, tuned to its type.

    facts — session_db scan record or grading.session_facts() dict. Its
    ``session_type`` selects the reaction ladder (see below).
    prior_best — best clean lap before this session (enables the PB
    question when this session beat it).
    focus_id — the driver's committed pre-session focus (the session's
    ``F`` row / sessionlog.focus id), if any. When set (and not
    "just_drive"), the goal question is dropped — the driver already
    declared intent on the NEXT GOAL card, so re-asking it is redundant.
    location — the corner label that dominated the session's mistakes
    (caller-derived, e.g. from pace.track_limit_counts), or None. When
    given with invalid laps, a lap session's reaction becomes the
    corner-specific ``corner_trouble`` question, its text naming that corner.

    Always feeling; then the driver's goal (race sessions get the
    race-specific ``goal_race``) ONLY when no focus was set; then at most one
    reaction, chosen by session type:
      * race       — contact > penalties > lost places > the start
      * qualifying — new PB > theoretical gap > what cost the lap
      * hotlap/TT  — new PB > theoretical gap > rewinds > corner > invalids
      * practice   — new PB > corner > invalids > rewinds > theoretical gap
    """
    facts = facts or {}
    stype = (facts.get("session_type") or "").strip().lower()
    is_race = stype == "race"

    out = [QUESTIONS["feeling"]]
    if not focus_id or focus_id == "just_drive":
        out.append(QUESTIONS["goal_race"] if is_race else QUESTIONS["goal"])

    reaction = _race_reaction(facts) if is_race \
        else _lap_reaction(stype, facts, prior_best, location)
    if reaction:
        out.append(reaction)
    return out


def _race_reaction(facts):
    """The one reaction question for a race — always something to ask, since
    every race has a start worth a word. Evidence-first: a logged contact or
    penalty, or places lost from the grid, take precedence."""
    if (facts.get("collision_count") or 0) >= 1:
        return QUESTIONS["contact_fault"]
    if (facts.get("penalty_count") or 0) >= 1:
        return QUESTIONS["penalty_cause"]
    start, finish = facts.get("start_position"), facts.get("position")
    if start and finish and finish > start:
        return QUESTIONS["positions_lost"]
    return QUESTIONS["race_start"]


def _lap_reaction(stype, facts, prior_best, location):
    """The one reaction question for a lap session (hotlap/qualifying/
    practice). A new PB always wins; otherwise the ladder is type-specific."""
    best = facts.get("best_lap_time")
    if best and prior_best and best < prior_best:
        return QUESTIONS["pb_change"]

    lap_count = facts.get("lap_count") or 0
    valid = facts.get("valid_lap_count")
    invalid = (lap_count - valid) if (lap_count and valid is not None) else 0
    rewinds = facts.get("rewind_count") or 0
    theo = facts.get("theo_time")
    big_theo_gap = bool(best and theo and best - theo >= _THEO_GAP_TRIGGER)
    corner = None
    if location and invalid >= 1:
        # A corner clearly dominated the mistakes — ask about it by name
        # rather than the generic "what caused the invalids".
        corner = dict(QUESTIONS["corner_trouble"],
                      text=f"{location} kept catching you out — "
                           "what's going wrong there?")

    if stype == "hotlap":
        # One perfect lap is the whole game: what stopped it, then why the
        # restarts, then the corner/invalids behind them.
        if big_theo_gap:
            return QUESTIONS["theo_gap"]
        if rewinds >= _MIN_REWINDS:
            return QUESTIONS["rewind_cause"]
        if corner:
            return corner
        if invalid >= _MIN_INVALID:
            return QUESTIONS["invalid_cause"]
        return None

    if stype == "qualifying":
        # One-shot pace under pressure: the theoretical gap, then the
        # broader "what cost you" (traffic / pressure / limits).
        if big_theo_gap:
            return QUESTIONS["theo_gap"]
        if invalid >= 1 or rewinds >= 1:
            return QUESTIONS["quali_cost"]
        if corner:
            return corner
        return None

    # practice (and any unknown lap type): mistakes first — it's the session
    # for ironing them out.
    if corner:
        return corner
    if invalid >= _MIN_INVALID:
        return QUESTIONS["invalid_cause"]
    if rewinds >= _MIN_REWINDS:
        return QUESTIONS["rewind_cause"]
    if big_theo_gap:
        return QUESTIONS["theo_gap"]
    return None


def answer_label(question_id, answer_id):
    """Display label for a stored answer; the raw id when unknown (a
    newer app version may know questions this one doesn't)."""
    q = QUESTIONS.get(question_id)
    if q:
        for aid, label in q["options"]:
            if aid == answer_id:
                return label
    return (answer_id or "").replace("_", " ")


def debrief_lines(session):
    """Human sentences for the AI-coach share text, from a parsed
    session's debrief answers. Empty list when no debrief was recorded."""
    answers = session.get("debrief") or {}
    lines = []
    for qid in _QUESTION_ORDER:
        if qid in answers and qid in _LINE_TEMPLATES:
            label = answer_label(qid, answers[qid]).lower()
            lines.append(_LINE_TEMPLATES[qid].format(answer=label))
    return lines


def debrief_qa(session):
    """[(question_text, answer_text), ...] for this session's answered
    debrief questions, in the order they were asked. Unlike debrief_lines()
    (prose for the AI-coach share text), this keeps the raw question and
    answer for a UI that shows what was actually asked and answered — e.g.
    the history browser's session detail view. Empty list when no debrief
    was recorded."""
    answers = session.get("debrief") or {}
    pairs = []
    for qid in _QUESTION_ORDER:
        if qid in answers:
            q = QUESTIONS.get(qid)
            if not q:
                continue
            pairs.append((q["text"], answer_label(qid, answers[qid])))
    return pairs
