"""
Shfonic Dash sessionlog — pre-session goals (shared library; canonical
home is ShfonicDash/src/sessionlog/, vendored into the companion
app by sync_shared.py — see the package docstring).

Builds the "NEXT GOAL" content shown before a session starts (the Pi's
pre-session card; the companion may reuse it). Every goal and mission is
derived from recorded history at the same game / car class / track /
session type — nothing is invented. If the data can't back a suggestion
("brake later into T3" needs corner data that doesn't exist), it is not
made.

Input records are session_db scan rows (records.combo_history() /
all_sessions() filtered to one combo) — the same shape grading.grade()
accepts.
"""

from . import objectives as _objectives
from .focus import recommended_focus
from .grading import grade
from .parser import format_lap_time

# letter() output, worst → best, for the "improve grade" step.
_LETTER_LADDER = ["F", "D-", "D", "D+", "C-", "C", "C+",
                  "B-", "B", "B+", "A-", "A", "A+"]

# Data thresholds for missions (seconds / lap-time spread).
_THEO_GAP_MIN = 0.15      # smaller gaps aren't a meaningful target
_STD_DEV_HIGH = 0.35      # clean-lap spread that reads as inconsistency


def _chrono_key(record):
    return (record.get("date") or "", record.get("filename") or "")


def baseline_goal(session_type=None):
    """First-visit goal card — no history at this combo yet.

    Same dict shape as pre_session_goal() but with everything data-derived
    left empty and generic, learn-the-track objectives instead. These are
    plain advice, not claims about the driver's data, so nothing is
    invented. Callers use this when pre_session_goal() returns None but a
    combo (game/track/...) is known, so a new track still gets a card.

    session_type — the UPCOMING session's type. For a lap session (hotlap /
    practice / qualifying) the "Learn the track" mission is a *tracked*
    LEARN_TRACK objective: the summary reads the ordered session and reports
    whether the clean-lap pace came down as the driver learned the layout. A
    race first visit keeps it as plain advice — fuel burn and tyre deg make an
    early-vs-late pace read meaningless, so it carries no objective type.
    """
    stype = (session_type or "").strip().lower()
    learn = {"icon": "🎯", "title": "Learn the track",
             "detail": "Build up gradually — smooth and consistent first, "
                       "then find the pace."}
    if stype and stype != "race":
        learn["type"] = _objectives.LEARN_TRACK
    return {
        "session_count":  0,
        "prior_best":     None,
        "last_grade":     None,
        "grade_letter":   None,
        "next_letter":    None,
        "estimated_gain": None,
        "missions": [
            {"icon": "📏", "title": "Set a baseline",
             "detail": "Bank a few clean laps for a time to beat next time."},
            learn,
            {"icon": "✅", "title": "Three clean laps",
             "detail": "No invalids, no flashbacks — get a read on the layout."},
        ],
    }


def pre_session_goal(history, track_limit_hotspot=None, line_hotspot=None,
                     session_type=None):
    """
    history — scan records for ONE game/car class/track/session type
    combo, any order. Returns the pre-session goal dict; None only when
    history is empty (first session at the combo — callers show a
    baseline_goal() card, or nothing).

    session_type — the UPCOMING session's type, which selects the mission
    set: a race gets craft/position/pace missions, lap sessions get the
    lap-time set. Defaults to the most recent record's own type.

    track_limit_hotspot — {"label", "count", "total"} for the corner that
    dominated the LAST session's track-limit warnings (computed by the
    caller — core.pre_session re-parses that session's raw CSV, since
    corner-level detail isn't indexed; see sessionlog.pace.
    track_limit_counts()), or None when there wasn't a clear one. Nothing
    here re-derives it — this module stays pure/file-I/O-free.

    line_hotspot — {"label", "offset_m"} for the corner where the driven
    line strayed furthest from the racing line last session (caller derives
    it via sessionlog.lines.line_hotspot on that session's P-row profiles;
    F1 mapped tracks only), or None. Drives the "Tighten your line" mission.

    {
      "session_count": int,
      "prior_best":    float | None,   # best clean lap across history
      "last_grade":    grade() dict | None,
      "grade_letter":  str | None,     # last session's overall letter
      "next_letter":   str | None,     # one step up the ladder (None at A+)
      "estimated_gain": float | None,  # last session's best - theoretical:
                                       # time provably available from own
                                       # already-driven sectors
      "missions": [ {"icon", "title", "detail"}, ... ]  # up to 3
    }
    """
    history = [r for r in (history or []) if r]
    if not history:
        return None
    history = sorted(history, key=_chrono_key)
    last = history[-1]
    session_type = (session_type or last.get("session_type") or "").strip().lower()

    bests = [r.get("best_lap_time") for r in history
             if r.get("best_lap_time")]
    prior_best = min(bests) if bests else None

    # Grade the most recent session as it was graded at the time —
    # against the best that existed BEFORE it.
    earlier = [r.get("best_lap_time") for r in history[:-1]
               if r.get("best_lap_time")]
    last_grade = grade(last, prior_best=min(earlier) if earlier else None)

    grade_letter = last_grade["letter"] if last_grade else None
    next_letter = None
    if grade_letter in _LETTER_LADDER:
        idx = _LETTER_LADDER.index(grade_letter)
        if idx + 1 < len(_LETTER_LADDER):
            next_letter = _LETTER_LADDER[idx + 1]

    best, theo = last.get("best_lap_time"), last.get("theo_time")
    estimated_gain = None
    if best and theo and best - theo >= _THEO_GAP_MIN:
        estimated_gain = round(best - theo, 3)

    return {
        "session_count":  len(history),
        "prior_best":     prior_best,
        "last_grade":     last_grade,
        "grade_letter":   grade_letter,
        "next_letter":    next_letter,
        "estimated_gain": estimated_gain,
        # The chip the pre-session card flags "Recommended" — the last
        # session's biggest shortfall, mapped to a focus (None if it was
        # solid across the board).
        "recommended_focus": recommended_focus(last, session_type),
        "missions":       _missions(last, last_grade, prior_best,
                                    estimated_gain, track_limit_hotspot,
                                    line_hotspot, session_type),
    }


def _assist_mission(last):
    """A single combined "reduce assist reliance" objective naming whichever
    of racing line / TC / ABS / gearbox assist were used last session — one
    slot, not one per assist. None when everything was off (or the history
    predates assist logging, v0.40.0 — missing counts read as None/0)."""
    used = []
    if last.get('racing_line_used_lap_count'):
        used.append('the racing line')
    if last.get('tc_used_lap_count'):
        used.append('TC')
    if last.get('abs_used_lap_count'):
        used.append('ABS')
    if last.get('gearbox_assist_used_lap_count'):
        used.append('the gearbox assist')
    if not used:
        return None
    if len(used) == 1:
        detail = f"{used[0]} was on last session — try a lap with it off"
    else:
        detail = (f"{', '.join(used[:-1])} and {used[-1]} were on last "
                  "session — try a lap with them off")
    return {"icon": "🎚", "title": "Reduce assist reliance", "detail": detail,
            "type": _objectives.REDUCE_ASSISTS,
            "baseline": ", ".join(used)}


def _track_limit_hotspot_mission(track_limit_hotspot):
    """"Watch your line" objective naming the corner that dominated last
    session's track-limit warnings. None without a clear hotspot."""
    if not track_limit_hotspot:
        return None
    h = track_limit_hotspot
    return {"icon": "⚠️", "title": "Watch your line",
            "detail": (f"{h['label']} — {h['count']} of {h['total']} "
                      "track-limits warnings there last session"),
            "type": _objectives.CORNER_LIMITS,
            "target": h["label"], "baseline": h["count"]}


def _line_hotspot_mission(line_hotspot):
    """"Tighten your line" objective naming the corner where the driven line
    strayed furthest from the racing line last session. None without one
    (needs F1 line-profile data at a mapped track — see sessionlog.lines)."""
    if not line_hotspot:
        return None
    h = line_hotspot
    return {"icon": "🎯", "title": "Tighten your line",
            "detail": (f"{h['label']} — about {h['offset_m']:.1f} m off the "
                       "racing line last session"),
            "type": _objectives.CORNER_LINE,
            "target": h["label"], "baseline": h["offset_m"]}


def _race_missions(last, last_grade):
    """Up to 3 data-backed RACE objectives — result before lap time. Built
    from the last race at this combo: incidents, then places lost, then
    flashbacks, then race-pace spread."""
    out = []
    focus = (last_grade or {}).get("focus")
    if focus:
        out.append({"icon": "🎯", "title": "Focus", "detail": focus})

    incidents = ((last.get("collision_count") or 0)
                 + (last.get("penalty_count") or 0))
    if incidents > 0:
        out.append({
            "icon": "✅", "title": "Bring home a clean race",
            "detail": f"{incidents} contact/penalty last race",
            "type": _objectives.FINISH_CLEAN, "target": 0,
            "baseline": incidents,
        })

    pos, start = last.get("position"), last.get("start_position")
    if pos and start and pos > start:
        lost = pos - start
        out.append({
            "icon": "🏆", "title": "Finish no worse than you start",
            "detail": f"lost {lost} place{'s' if lost != 1 else ''} last race "
                      f"(P{start} → P{pos})",
            "type": _objectives.GAIN_POSITIONS, "baseline": lost,
        })

    rewinds = last.get("rewind_count")
    if rewinds:
        out.append({
            "icon": "⏪", "title": "No flashbacks this race",
            "detail": f"{rewinds} used last time",
            "type": _objectives.NO_FLASHBACKS, "target": 0,
            "baseline": rewinds,
        })

    std = last.get("clean_std_dev")
    if std is not None and std > _STD_DEV_HIGH:
        out.append({
            "icon": "📏", "title": "Steady race pace",
            "detail": f"lap times varied ±{std:.3f}s last race",
            "type": _objectives.TIGHTEN_SPREAD, "baseline": std,
        })

    return out[:3]


def _missions(last, last_grade, prior_best, estimated_gain,
              track_limit_hotspot=None, line_hotspot=None, session_type=None):
    """Up to 3 data-backed objectives, most actionable first."""
    if (session_type or "").strip().lower() == "race":
        return _race_missions(last, last_grade)

    out = []

    # The grading engine already computes "one achievable objective for
    # the next session" from the full evidence — lead with it.
    focus = (last_grade or {}).get("focus")
    if focus:
        out.append({"icon": "🎯", "title": "Focus", "detail": focus})

    lap_count = last.get("lap_count") or 0
    valid = last.get("valid_lap_count")
    invalid = (lap_count - valid) if (lap_count and valid is not None) else 0
    if invalid > 0:
        out.append({
            "icon": "✅", "title": "Complete 3 consecutive valid laps",
            "detail": f"{invalid} invalid last session",
            "type": _objectives.CLEAN_STREAK, "target": 3,
            "baseline": last.get("clean_streak"),
        })

    rewinds = last.get("rewind_count")
    if rewinds:
        out.append({
            "icon": "⏪", "title": "No flashbacks this session",
            "detail": f"{rewinds} used last time",
            "type": _objectives.NO_FLASHBACKS, "target": 0,
            "baseline": rewinds,
        })

    if estimated_gain is not None and last.get("theo_time"):
        out.append({
            "icon": "⏱", "title": "Put the sectors together",
            "detail": (f"theoretical {format_lap_time(last['theo_time'])} — "
                       f"{estimated_gain:.3f}s already in your sectors"),
            "type": _objectives.CONVERT_SECTORS, "target": last["theo_time"],
            "baseline": estimated_gain,
        })

    std = last.get("clean_std_dev")
    if std is not None and std > _STD_DEV_HIGH:
        out.append({
            "icon": "📏", "title": "Tighten the spread",
            "detail": f"clean laps varied ±{std:.3f}s last session",
            "type": _objectives.TIGHTEN_SPREAD, "baseline": std,
        })

    assist_mission = _assist_mission(last)
    if assist_mission:
        out.append(assist_mission)

    hotspot_mission = _track_limit_hotspot_mission(track_limit_hotspot)
    if hotspot_mission:
        out.append(hotspot_mission)

    line_mission = _line_hotspot_mission(line_hotspot)
    if line_mission:
        out.append(line_mission)

    if prior_best:
        out.append({
            "icon": "🏆", "title": f"Beat {format_lap_time(prior_best)}",
            "detail": "your best at this combination",
            "type": _objectives.BEAT_TIME, "target": prior_best,
        })

    return out[:3]


def objectives_for(missions):
    """The tracked objectives to persist for a set of pre-session missions —
    one objectives.make() dict per mission that carries a machine ``type``
    (the "Focus" prose mission and the baseline-card advice have none, so
    they are not tracked). Callers write these as ``O`` rows and evaluate
    them at session end (sessionlog.objectives)."""
    return [_objectives.make(m["type"], m.get("target"), m.get("baseline"))
            for m in (missions or []) if m.get("type")]
