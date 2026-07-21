"""
Shfonic Dash sessionlog — session focus (shared library; canonical home is
ShfonicDash/src/sessionlog/, vendored into the companion app by
sync_shared.py — see the package docstring).

A "focus" is one thing the driver commits to before a stint (picked on the
pre-session NEXT GOAL card, persisted as an ``F`` row in the session CSV).
The end-of-session summary — and the mid-session "SESSION SO FAR" card —
then report how the session tracked against *that* choice first.

Two halves:
  * ``available_focuses()`` — the fixed chip set the pre-session card offers.
  * ``evaluate()`` — given a session's grading facts (and prior-session
    references), a met / not-met / neutral verdict for the chosen focus.

Every verdict is derived from recorded facts (best lap, clean-lap spread,
invalid laps, flashbacks) — nothing is invented. Pure standard library,
Python 3.10-safe (the companion floor).
"""

from .parser import format_lap_time

# Focus ids — stable strings written to the CSV ``F`` row.
CONSISTENCY = "consistency"
FASTER      = "faster"
CLEAN       = "clean"
JUST_DRIVE  = "just_drive"
# Race-only focuses. A race isn't about one fast lap — it's craft, position
# and management — so it gets its own chip set (see _CHIPS_BY_TYPE).
CLEAN_RACE  = "clean_race"
POSITIONS   = "positions"
RACE_PACE   = "race_pace"
MANAGE      = "manage"

# Ordered registry (every focus, any session type). ``chip`` is the
# pre-session button label; ``title`` is the summary-banner caption
# ("YOU CHOSE: <title>"). The per-session-type chip *sets* live in
# _CHIPS_BY_TYPE; this flat list only backs focus_title()/id lookups.
FOCUSES = [
    {"id": FASTER,      "chip": "FASTER",      "title": "FASTER TIME"},
    {"id": CONSISTENCY, "chip": "CONSISTENCY", "title": "CONSISTENCY"},
    {"id": CLEAN,       "chip": "CLEAN LAPS",  "title": "CLEAN LAPS"},
    {"id": JUST_DRIVE,  "chip": "JUST DRIVE",  "title": "FREE SESSION"},
    {"id": CLEAN_RACE,  "chip": "CLEAN RACE",  "title": "CLEAN RACE"},
    {"id": POSITIONS,   "chip": "POSITIONS",   "title": "POSITIONS"},
    {"id": RACE_PACE,   "chip": "RACE PACE",   "title": "RACE PACE"},
    {"id": MANAGE,      "chip": "MANAGE",       "title": "TYRE & FUEL"},
]

_BY_ID = {f["id"]: f for f in FOCUSES}

# The chip set offered before each session type, in display order. A hotlap
# or qualifying run leads with pace; practice leads with consistency; a race
# swaps the lap-time chips entirely for its own craft/position/management
# set. Unknown/absent types fall back to the classic lap-time set.
_DEFAULT_CHIPS = [FASTER, CONSISTENCY, CLEAN, JUST_DRIVE]
_CHIPS_BY_TYPE = {
    "hotlap":     [FASTER, CLEAN, CONSISTENCY, JUST_DRIVE],
    "qualifying": [FASTER, CLEAN, CONSISTENCY, JUST_DRIVE],
    "practice":   [CONSISTENCY, CLEAN, FASTER, JUST_DRIVE],
    "race":       [CLEAN_RACE, POSITIONS, RACE_PACE, MANAGE],
}


def _chip_ids(session_type):
    return _CHIPS_BY_TYPE.get((session_type or "").strip().lower(),
                              _DEFAULT_CHIPS)


def focus_title(focus_id):
    """Summary-banner caption for a focus id ('' if unknown)."""
    f = _BY_ID.get(focus_id)
    return f["title"] if f else ""


# Thresholds for turning a session's shortfall into a recommended focus.
# Kept close to goals/grading so the chip agrees with the next-session
# objective the coach already computes.
_REC_THEO_GAP  = 0.15   # theoretical this far under the best → chase time
_REC_SPREAD    = 0.35   # clean-lap spread this loose → work on consistency


def recommended_focus(record, session_type=None):
    """The focus to flag "Recommended" — the single biggest opportunity from
    the driver's most recent session at this combo, as a chip id (or None).

    record — one records/scan row (the LAST session at the combo).
    session_type — the UPCOMING session's type; when it (or the record) is a
    race, the recommendation is drawn from the race chip set instead of the
    lap-time one. Defaults to the record's own type.

    For lap sessions this mirrors the grading focus ladder: completion first
    (invalid laps / flashbacks → clean), then converting pace already in your
    sectors (→ faster), then tightening the spread (→ consistency). For races:
    incidents (contacts / penalties / flashbacks → clean race), then lost
    places (→ positions), then a loose race-pace spread (→ race pace). None
    when the last session was solid across the board, or there is no prior.
    """
    if not record or not (record.get("lap_count") or 0):
        return None
    stype = (session_type or record.get("session_type") or "").strip().lower()
    if stype == "race":
        incidents = ((record.get("collision_count") or 0)
                     + (record.get("penalty_count") or 0)
                     + (record.get("rewind_count") or 0))
        if incidents > 0:
            return CLEAN_RACE
        pos, start = record.get("position"), record.get("start_position")
        if pos and start and pos > start:
            return POSITIONS
        std = record.get("clean_std_dev")
        if std is not None and std > _REC_SPREAD:
            return RACE_PACE
        return None

    lap_count = record["lap_count"]
    valid = record.get("valid_lap_count")
    invalid = (lap_count - valid) if valid is not None else 0
    if invalid > 0 or (record.get("rewind_count") or 0) > 0:
        return CLEAN
    best, theo = record.get("best_lap_time"), record.get("theo_time")
    if best and theo and best - theo >= _REC_THEO_GAP:
        return FASTER
    std = record.get("clean_std_dev")
    if std is not None and std > _REC_SPREAD:
        return CONSISTENCY
    return None


def available_focuses(goal=None, session_type=None):
    """The chip set for the pre-session card: [{id, chip, hint, recommended}].

    goal — the pre_session_goal() dict (optional). Used to attach a short
    data hint to a chip (e.g. FASTER → "beat 1:18.412") and to flag the one
    chip that answers the last session's biggest shortfall
    (goal["recommended_focus"]) with recommended=True.
    session_type — selects the chip set (see _CHIPS_BY_TYPE): pace-led for
    hotlap/qualifying, consistency-led for practice, a craft/position set for
    races. None keeps the classic lap-time set (backward-compatible default).
    """
    goal = goal or {}
    hints = {}
    pb = goal.get("prior_best")
    if pb:
        hints[FASTER] = "beat " + format_lap_time(pb)
    rec = goal.get("recommended_focus")
    return [{"id": fid, "chip": _BY_ID[fid]["chip"],
             "hint": hints.get(fid, ""), "recommended": fid == rec}
            for fid in _chip_ids(session_type)]


def session_verdict(session, facts, history, prior_best=None):
    """The focus verdict for one session — priors derived from its history.

    The one entry point both apps use, so the Pi's summary banner and the
    companion's session detail can never disagree. Wraps evaluate() with the
    prior-session references pulled from the combo history.

    session — parser.parse() dict (carries "focus" from the F row and
      "filename").
    facts   — grading.session_facts(session) for this session.
    history — combo_history() rows for the same game/car class/track/session
      type **as of this session** (callers pass up_to_date/up_to_filename so
      re-opening an old session never compares it against later results).
      Rows for the session itself are ignored; order doesn't matter.
    prior_best — the caller's own PB baseline, when it has one (e.g.
      records.prior_best()). It wins over the value derived from `history`.
      Pass it whenever the surrounding text also depends on a PB, so the two
      cannot contradict each other ("didn't come together" next to "new
      personal best"). Omit it and the best over `history` is used.

    Returns evaluate()'s dict plus "title", or None when no focus was
    chosen, it was "just drive", or the id is unknown (→ no banner).
    """
    focus_id = (session.get("focus") or "").strip()
    if not focus_id or focus_id == JUST_DRIVE:
        return None
    current_fn = session.get("filename") or ""
    prior = sorted((r for r in (history or [])
                    if r and r.get("filename") != current_fn),
                   key=_chrono_key)
    bests = [r.get("best_lap_time") for r in prior if r.get("best_lap_time")]
    stds  = [r.get("clean_std_dev") for r in prior if r.get("clean_std_dev")]
    # "Faster"/"consistency" are judged against your BEST here; "clean" against
    # your LAST session here (did you do better than last time).
    prev = prior[-1] if prior else None
    clean_frac = None
    if prev and prev.get("lap_count"):
        clean_frac = (prev.get("clean_lap_count") or 0) / prev["lap_count"]
    if prior_best is None:
        prior_best = min(bests) if bests else None
    v = evaluate(focus_id, facts,
                 prior_best=prior_best,
                 prior_std=min(stds) if stds else None,
                 prior_clean_frac=clean_frac)
    return dict(v, title=focus_title(focus_id)) if v else None


def _chrono_key(record):
    return (record.get("date") or "", record.get("filename") or "")


def evaluate(focus_id, facts, prior_best=None, prior_std=None,
            prior_clean_frac=None):
    """Verdict for the chosen focus against this session's facts.

    facts — grading.session_facts() output (best_lap_time, clean_std_dev,
    clean_lap_count, lap_count, valid_lap_count, rewind_count). Works
    mid-session too: the facts are computed from laps banked so far.
    prior_best — best clean lap across earlier sessions at this combo.
    prior_std  — best (lowest) clean-lap spread across earlier sessions.
    prior_clean_frac — clean-lap fraction (clean_lap_count / lap_count) of
    the single most recent PRIOR session at this combo (recency, not the
    best-ever rate — "did you do better than last time").

    Returns {"met": True|False|None, "headline": str, "detail": str}, or
    None for an unknown / free-session focus (no banner shown).
    """
    facts = facts or {}
    if focus_id == FASTER:
        return _eval_faster(facts, prior_best)
    if focus_id == CONSISTENCY:
        return _eval_consistency(facts, prior_std)
    if focus_id == CLEAN:
        return _eval_clean(facts, prior_clean_frac)
    if focus_id == CLEAN_RACE:
        return _eval_clean_race(facts)
    if focus_id == POSITIONS:
        return _eval_positions(facts)
    if focus_id == RACE_PACE:
        return _eval_consistency(facts, prior_std, label="Race pace")
    if focus_id == MANAGE:
        return _eval_manage(facts)
    return None   # just_drive / unknown → no verdict banner


def _eval_faster(facts, prior_best):
    best = facts.get("best_lap_time")
    if not best:
        return _verdict(None, "No clean lap yet",
                        "Set a clean lap to compare with your best here.")
    if not prior_best:
        return _verdict(None, "Best so far " + format_lap_time(best),
                        "No earlier best here — this becomes your benchmark.")
    gap = best - prior_best
    if gap < 0:
        return _verdict(True, "New best " + format_lap_time(best),
                        "Beat your previous " + format_lap_time(prior_best)
                        + " by " + _secs(-gap) + ".")
    return _verdict(False, format_lap_time(best) + "  ·  " + _secs(gap) + " off",
                    "Your best here is " + format_lap_time(prior_best) + ".")


def _eval_consistency(facts, prior_std, label="spread"):
    std = facts.get("clean_std_dev")
    n = facts.get("clean_lap_count") or 0
    if std is None or n < 2:
        return _verdict(None, "Not enough clean laps yet",
                        "Bank a few clean laps to measure your spread.")
    cur = label + " ±" + _secs(std) + " over " + _laps(n)
    if not prior_std:
        return _verdict(None, cur,
                        "No earlier spread here to compare — this is your baseline.")
    if std < prior_std:
        return _verdict(True, cur,
                        "Tighter than your previous best ±" + _secs(prior_std) + ".")
    return _verdict(False, cur,
                    "Your tightest here was ±" + _secs(prior_std) + ".")


def _eval_clean(facts, prior_clean_frac=None):
    lap_count = facts.get("lap_count") or 0
    if lap_count == 0:
        return _verdict(None, "No laps yet", "Keep every lap valid and flashback-free.")
    valid = facts.get("valid_lap_count")
    invalid = (lap_count - valid) if valid is not None else 0
    rew = facts.get("rewind_count") or 0
    streak = facts.get("clean_streak")
    if invalid == 0 and rew == 0:
        headline = "All clean — " + _laps(lap_count)
    else:
        bits = []
        if invalid:
            bits.append(str(invalid) + " invalid")
        if rew:
            bits.append(str(rew) + " flashback" + ("s" if rew != 1 else ""))
        headline = ", ".join(bits) or "Mistakes logged"
        # Surface the longest clean run alongside the mistakes — a driver
        # who binned two laps but strung five clean in a row is progressing.
        if streak and streak >= 2:
            headline += "  ·  best run " + _laps(streak)

    if prior_clean_frac is None:
        met = True if (invalid == 0 and rew == 0) else False
        return _verdict(met, headline,
                        "No earlier clean rate here — this becomes your benchmark.")
    frac = (facts.get("clean_lap_count") or 0) / lap_count
    if frac > prior_clean_frac:
        return _verdict(True, headline,
                        "Better than your previous " + _pct(prior_clean_frac) + " clean.")
    if frac < prior_clean_frac:
        return _verdict(False, headline,
                        "Your clean rate here was " + _pct(prior_clean_frac) + ".")
    return _verdict(True, headline,
                    "Matches your previous " + _pct(prior_clean_frac) + " clean.")


def _eval_clean_race(facts):
    """A race's answer to CLEAN: no contact, no penalties, no flashbacks.
    Invalid laps aren't the yardstick in a race (traffic/defending legitimately
    dirty a lap) — incidents are (mirrors grading's Race Discipline)."""
    if not (facts.get("lap_count") or 0):
        return _verdict(None, "No racing yet",
                        "Keep it clean — no contact, penalties or flashbacks.")
    col = facts.get("collision_count") or 0
    pen = facts.get("penalty_count") or 0
    rew = facts.get("rewind_count") or 0
    if col == 0 and pen == 0 and rew == 0:
        return _verdict(True, "Clean race",
                        "No contact, penalties or flashbacks.")
    bits = []
    if col:
        bits.append(str(col) + " contact" + ("s" if col != 1 else ""))
    if pen:
        bits.append(str(pen) + " penalt" + ("ies" if pen != 1 else "y"))
    if rew:
        bits.append(str(rew) + " flashback" + ("s" if rew != 1 else ""))
    return _verdict(False, ", ".join(bits),
                    "A clean race is contact-, penalty- and flashback-free.")


def _eval_positions(facts):
    """Did the race gain (or hold) track position? Grid slot vs finish."""
    start = facts.get("start_position")
    finish = facts.get("position")
    if not start or not finish:
        return _verdict(None, "Positions not recorded",
                        "Needs a grid slot and a finishing position.")
    net = start - finish   # positive = places made up
    line = "P" + str(start) + " → P" + str(finish)
    if net > 0:
        return _verdict(True, "+" + str(net) + "  ·  " + line,
                        "Made up " + _places(net) + " from the grid.")
    if net == 0:
        return _verdict(True, "Held  ·  " + line,
                        "Held your grid slot to the flag.")
    return _verdict(False, str(net) + "  ·  " + line,
                    "Lost " + _places(-net) + " from the grid.")


def _eval_manage(facts):
    """Tyre & fuel management — no automatic score yet (needs per-stint
    degradation data the facts don't carry). A neutral, honest reminder; the
    debrief captures the driver's own read. Surfaces incidents when present,
    since binning the car is the opposite of bringing it home."""
    if not (facts.get("lap_count") or 0):
        return _verdict(None, "No racing yet",
                        "Look after the tyres and fuel — bring it home.")
    col = facts.get("collision_count") or 0
    if col:
        return _verdict(None, "Brought it home",
                        "Managed the distance despite "
                        + str(col) + " contact" + ("s" if col != 1 else "")
                        + " — the debrief has your read.")
    return _verdict(None, "Race completed",
                    "Tyre and fuel management is your call — the debrief "
                    "captures how it went.")


def _places(n):
    return str(n) + (" place" if n == 1 else " places")


def _verdict(met, headline, detail):
    return {"met": met, "headline": headline, "detail": detail}


def _secs(x):
    return "{:.3f}s".format(x)


def _pct(frac):
    return "{:.0f}%".format(frac * 100)


def _laps(n):
    return str(n) + (" lap" if n == 1 else " laps")
