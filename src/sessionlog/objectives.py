"""
Shfonic Dash sessionlog — tracked objectives (shared library; canonical
home is ShfonicDash/src/sessionlog/, vendored into the companion app
by sync_shared.py — see the package docstring).

An *objective* is a data-backed thing the driver is working on for one
session — "complete three clean laps in a row", "beat 1:18.412", "keep it
clean at Turn 8". Where sessionlog.goals *proposes* them before a session
(from the combo history) and sessionlog.focus is the ONE headline the
driver taps, objectives are the specific targets that get written into the
session CSV as ``O`` rows and then **followed up**: at the end of the
session — and in the history browser afterwards — each one is reported met
/ missed / neutral against what actually happened.

This closes the loop goals opened. Nothing here is invented: an objective
carries a numeric ``target`` and a ``baseline`` snapshotted when it was set,
and evaluate() compares them to the recorded facts.

CSV form (see docs/session-log-format.md):
    O,<type>,<target>,<baseline>
``target`` and ``baseline`` are type-interpreted strings (a lap time, a
lap count, a corner id, …); an empty cell means "not applicable".

Pure standard library, Python 3.10-safe (the companion floor).
"""

from .parser import format_lap_time

# --- objective type ids (stable strings written to CSV O rows) -------------
CLEAN_STREAK    = "clean_streak"     # target = N consecutive clean laps
NO_FLASHBACKS   = "no_flashbacks"    # target = 0 rewinds; baseline = prior count
BEAT_TIME       = "beat_time"        # target = a lap time to beat (seconds)
CONVERT_SECTORS = "convert_sectors"  # target = the theoretical to reach (seconds)
TIGHTEN_SPREAD  = "tighten_spread"   # baseline = prior clean-lap spread (seconds)
CORNER_LIMITS   = "corner_limits"    # target = corner label; baseline = prior warnings
CORNER_LINE     = "corner_line"      # target = corner label; baseline = prior line deviation (m)
REDUCE_ASSISTS  = "reduce_assists"   # baseline = names of assists used last time
FINISH_CLEAN    = "finish_clean"     # target = 0 incidents; baseline = prior contacts+penalties
GAIN_POSITIONS  = "gain_positions"   # baseline = places lost from the grid last race
LEARN_TRACK     = "learn_track"      # first visit — did lap times come down as you learned it

# Ordered for display — most actionable first, matching goals._missions.
# Race objectives (finish clean / gain positions) lead, since a race's job is
# the result before the lap time.
_ORDER = [FINISH_CLEAN, GAIN_POSITIONS, CLEAN_STREAK, NO_FLASHBACKS,
          CONVERT_SECTORS, TIGHTEN_SPREAD, CORNER_LIMITS, CORNER_LINE,
          BEAT_TIME, LEARN_TRACK, REDUCE_ASSISTS]

# Compact captions for a glanceable goals strip (the end-of-session summary
# and the companion's session card). Both apps caption goals identically.
_SHORT_LABELS = {
    CLEAN_STREAK:    "clean run",
    NO_FLASHBACKS:   "no flashbacks",
    CONVERT_SECTORS: "sectors",
    TIGHTEN_SPREAD:  "spread",
    CORNER_LIMITS:   "corner",
    CORNER_LINE:     "line",
    BEAT_TIME:       "beat time",
    REDUCE_ASSISTS:  "assists",
    FINISH_CLEAN:    "clean race",
    GAIN_POSITIONS:  "positions",
    LEARN_TRACK:     "learn track",
}


def short_label(outcome):
    """A short caption for one objective/outcome — the corner's own name for
    a corner objective, else a fixed per-type word ('clean run', 'spread')."""
    t = outcome.get("type")
    if t in (CORNER_LIMITS, CORNER_LINE) and outcome.get("target"):
        return str(outcome["target"])
    return _SHORT_LABELS.get(t, (t or "").replace("_", " "))


def make(obj_type, target=None, baseline=None):
    """Build an objective dict. ``target``/``baseline`` may be numbers,
    strings or None — normalise() renders them for the CSV."""
    return {"type": obj_type, "target": target, "baseline": baseline}


def _cell(value):
    """A target/baseline value → its CSV cell string ('' for None)."""
    if value is None:
        return ""
    if isinstance(value, float):
        # Lap times to 3dp; whole numbers stay clean.
        return ("%.3f" % value).rstrip("0").rstrip(".") if value % 1 else str(int(value))
    return str(value)


def to_row(obj):
    """Objective dict → ``O`` CSV row (list of strings)."""
    return ["O", obj.get("type", ""),
            _cell(obj.get("target")), _cell(obj.get("baseline"))]


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value):
    f = _as_float(value)
    return int(f) if f is not None else None


def _verdict(met, headline, detail=""):
    return {"met": met, "headline": headline, "detail": detail}


def evaluate(obj, facts, corner_warnings=None, corner_line_dev=None,
             progression_facts=None):
    """How one objective turned out, against a finished session.

    obj    — a parsed O-row dict ({"type","target","baseline"}) or a make()
             dict; target/baseline may be strings (from the CSV) or numbers.
    facts  — grading.session_facts() for the session the objective belongs to.
    corner_warnings — {corner_label: count} of this session's track-limit
             warnings per section (pace.track_limit_counts()), needed only to
             score a CORNER_LIMITS objective; omit and that type stays neutral.
    corner_line_dev — {corner_label: offset_m} of this session's line
             deviation per corner (lines.corner_deviations()), needed only to
             score a CORNER_LINE objective; omit and that type stays neutral.
    progression_facts — progression.progression_facts() for the session,
             needed only to score a LEARN_TRACK objective (did the clean-lap
             pace come down as the driver learned the track); omit and that
             type stays neutral.

    Returns {"met": True|False|None, "headline": str, "detail": str}, or None
    for an unknown type. ``met`` is None when the objective can't be scored
    yet (no clean lap, missing inputs) — a neutral "still open", never a fail.
    """
    facts = facts or {}
    t = obj.get("type")
    if t == CLEAN_STREAK:
        return _eval_clean_streak(obj, facts)
    if t == NO_FLASHBACKS:
        return _eval_no_flashbacks(obj, facts)
    if t == BEAT_TIME:
        return _eval_beat_time(obj, facts)
    if t == CONVERT_SECTORS:
        return _eval_convert_sectors(obj, facts)
    if t == TIGHTEN_SPREAD:
        return _eval_tighten_spread(obj, facts)
    if t == CORNER_LIMITS:
        return _eval_corner_limits(obj, corner_warnings)
    if t == CORNER_LINE:
        return _eval_corner_line(obj, corner_line_dev)
    if t == REDUCE_ASSISTS:
        return _eval_reduce_assists(obj, facts)
    if t == FINISH_CLEAN:
        return _eval_finish_clean(obj, facts)
    if t == GAIN_POSITIONS:
        return _eval_gain_positions(obj, facts)
    if t == LEARN_TRACK:
        return _eval_learn_track(obj, progression_facts)
    return None


def _eval_clean_streak(obj, facts):
    target = _as_int(obj.get("target")) or 3
    streak = facts.get("clean_streak") or 0
    label = "%d clean laps in a row" % target
    if streak >= target:
        return _verdict(True, "%d clean laps in a row" % streak,
                        "Target was %d — done." % target)
    if streak == 0:
        return _verdict(None, "No clean laps yet", "Target: " + label + ".")
    return _verdict(False, "Best run %d in a row" % streak,
                    "Target was %d clean in a row." % target)


def _eval_no_flashbacks(obj, facts):
    rew = facts.get("rewind_count")
    if rew is None:
        return _verdict(None, "Flashbacks not tracked", "")
    baseline = _as_int(obj.get("baseline"))
    if rew == 0:
        detail = ("Down from %d last session." % baseline) if baseline else ""
        return _verdict(True, "No flashbacks", detail)
    word = "flashback" if rew == 1 else "flashbacks"
    detail = ("Was %d last session." % baseline) if baseline else ""
    return _verdict(False, "%d %s used" % (rew, word), detail)


def _eval_beat_time(obj, facts):
    target = _as_float(obj.get("target"))
    best = facts.get("best_lap_time")
    if not target:
        return _verdict(None, "No target time", "")
    if not best:
        return _verdict(None, "No clean lap yet",
                        "Target: beat " + format_lap_time(target) + ".")
    gap = best - target
    if gap < 0:
        return _verdict(True, "New best " + format_lap_time(best),
                        "Beat " + format_lap_time(target) + " by %.3fs." % -gap)
    return _verdict(False, format_lap_time(best) + "  ·  +%.3fs" % gap,
                    "Target was " + format_lap_time(target) + ".")


def _eval_convert_sectors(obj, facts):
    target = _as_float(obj.get("target"))
    best = facts.get("best_lap_time")
    if not target:
        return _verdict(None, "No theoretical to reach", "")
    if not best:
        return _verdict(None, "No clean lap yet",
                        "Target: string the sectors into a "
                        + format_lap_time(target) + ".")
    if best <= target:
        return _verdict(True, "Assembled " + format_lap_time(best),
                        "Reached your prior theoretical "
                        + format_lap_time(target) + ".")
    gap = best - target
    return _verdict(False, format_lap_time(best) + "  ·  +%.3fs" % gap,
                    "Your prior theoretical was " + format_lap_time(target) + ".")


def _eval_tighten_spread(obj, facts):
    baseline = _as_float(obj.get("baseline"))
    std = facts.get("clean_std_dev")
    n = facts.get("clean_lap_count") or 0
    if std is None or n < 2:
        return _verdict(None, "Not enough clean laps yet", "")
    cur = "spread ±%.3fs" % std
    if not baseline:
        return _verdict(None, cur, "No earlier spread to compare.")
    if std < baseline:
        return _verdict(True, cur, "Tighter than your previous ±%.3fs." % baseline)
    return _verdict(False, cur, "Your tightest was ±%.3fs." % baseline)


def _eval_corner_limits(obj, corner_warnings):
    label = str(obj.get("target") or "").strip()
    baseline = _as_int(obj.get("baseline"))
    if not label or corner_warnings is None:
        return _verdict(None, "Corner not scored", "")
    n = corner_warnings.get(label, 0)
    if n == 0:
        detail = ("Caught you out %d times last session." % baseline
                  if baseline else "")
        return _verdict(True, "Clean at " + label, detail)
    word = "warning" if n == 1 else "warnings"
    if baseline and n < baseline:
        return _verdict(True, "%d %s at %s" % (n, word, label),
                        "Down from %d last session." % baseline)
    detail = ("Was %d last session." % baseline) if baseline else ""
    return _verdict(False, "%d %s at %s" % (n, word, label), detail)


def _eval_corner_line(obj, corner_line_dev):
    label = str(obj.get("target") or "").strip()
    baseline = _as_float(obj.get("baseline"))
    if not label or corner_line_dev is None:
        return _verdict(None, "Corner line not scored", "")
    dev = corner_line_dev.get(label)
    if dev is None:
        return _verdict(None, "No line at " + label + " this session", "")
    cur = "%.1fm off at %s" % (dev, label)
    if not baseline:
        return _verdict(None, cur, "No earlier line here to compare.")
    if dev < baseline:
        return _verdict(True, cur, "Tighter than %.1fm last session." % baseline)
    return _verdict(False, cur, "Was %.1fm last session." % baseline)


def _eval_reduce_assists(obj, facts):
    # Assist lap counts aren't in grading.session_facts, so this stays a
    # neutral reminder rather than a scored objective (the assist Race
    # Engineer Note reports the actual usage).
    baseline = str(obj.get("baseline") or "").strip()
    detail = ("Used last session: " + baseline + ".") if baseline else ""
    return _verdict(None, "Assist reliance", detail)


def _eval_finish_clean(obj, facts):
    """Race objective: no contacts or penalties (flashbacks folded in — the
    race-clean yardstick, matching focus.CLEAN_RACE). baseline = prior
    incident count, for the "down from N" line."""
    col = facts.get("collision_count")
    pen = facts.get("penalty_count")
    if col is None and pen is None:
        return _verdict(None, "Incidents not tracked", "")
    incidents = (col or 0) + (pen or 0) + (facts.get("rewind_count") or 0)
    baseline = _as_int(obj.get("baseline"))
    if incidents == 0:
        detail = ("Down from %d last race." % baseline) if baseline else ""
        return _verdict(True, "Clean race", detail)
    detail = ("Was %d last race." % baseline) if baseline else ""
    word = "incident" if incidents == 1 else "incidents"
    return _verdict(False, "%d %s" % (incidents, word), detail)


def _eval_gain_positions(obj, facts):
    """Race objective: finish no worse than you started. baseline = places
    lost last race (context for the detail line)."""
    start = facts.get("start_position")
    finish = facts.get("position")
    if not start or not finish:
        return _verdict(None, "Positions not recorded", "")
    net = start - finish   # positive = made up
    line = "P%d → P%d" % (start, finish)
    baseline = _as_int(obj.get("baseline"))
    if net > 0:
        detail = ("Lost %d last race." % baseline) if baseline else ""
        return _verdict(True, "+%d  ·  %s" % (net, line), detail)
    if net == 0:
        return _verdict(True, "Held  ·  " + line, "Held your grid slot.")
    return _verdict(False, "%d  ·  %s" % (net, line),
                    "Lost %d place%s from the grid."
                    % (-net, "" if -net == 1 else "s"))


# A clean-lap pace shift (s) that reads as a real trend, not lap-to-lap
# scatter. Matches progression._PACE_TREND_S so the LEARN_TRACK verdict and
# the progression Race Engineer Note never disagree.
_LEARN_TREND_S = 0.15


def _eval_learn_track(obj, progression_facts):
    """First-visit objective: did the clean-lap pace come down as the driver
    got a read on the layout? Scored purely from the ordered session's pace
    trend — later representative clean laps quicker than the earlier ones.
    Neutral (still open) until there are enough clean laps to read a trend."""
    pf = progression_facts or {}
    trend = pf.get("pace_trend")
    if trend is None:
        return _verdict(None, "Still learning the track",
                        "Not enough clean laps yet to read a pace trend.")
    if trend <= -_LEARN_TREND_S:
        return _verdict(True, "Found time as you learned it",
                        "Later clean laps were about %.2fs quicker than the "
                        "earlier ones." % -trend)
    if trend >= _LEARN_TREND_S:
        return _verdict(False, "Pace drifted the other way",
                        "Later clean laps were about %.2fs slower than the "
                        "earlier ones." % trend)
    return _verdict(None, "Pace held steady",
                    "Clean-lap pace levelled off as you settled in.")


def evaluate_all(objectives, facts, corner_warnings=None, corner_line_dev=None,
                 progression_facts=None):
    """Every objective's verdict, in display order, dropping unknown types.

    Returns [{"type", "target", "baseline", "met", "headline", "detail"}, ...].
    """
    by_type = {}
    for obj in objectives or []:
        by_type.setdefault(obj.get("type"), obj)   # first of a type wins
    out = []
    for t in _ORDER:
        obj = by_type.get(t)
        if not obj:
            continue
        v = evaluate(obj, facts, corner_warnings, corner_line_dev,
                     progression_facts)
        if v is None:
            continue
        out.append({"type": t, "target": obj.get("target"),
                    "baseline": obj.get("baseline"), **v})
    return out
