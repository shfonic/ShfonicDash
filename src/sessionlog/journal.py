"""
Shfonic Dash sessionlog — driving journal (shared library; canonical home
is ShfonicDash/src/sessionlog/, vendored into the companion app by
sync_shared.py — see the package docstring).

Writes the session's STORY, not a report: the biggest thing that happened
drives the entry, and everything else supports it.

  🏆  "New personal best by 0.087s. Two laps invalidated for track limits
       suggest there is still more pace to unlock."
  🏁  "Gained six places from P19 to P13. Strong race pace, but seven
       contacts limited the overall result."
  📈  "Consistency locked in — clean laps within ±0.142s. Theoretical
       pace is within two tenths of my fastest clean lap."
      "Tough session. Pace was competitive, but repeated track limits
       prevented a representative benchmark."

The entry is written in the driver's own first-person voice — it is their
diary, not a report addressed to them. It opens with their own framing
where it exists: when they drove ("Out this evening at Spa.") and the
focus they committed to before the stint, with whether it came off ("I
set out to keep it clean — and did.").

Rules of the notebook: evidence-only (nothing invented), the driver's
debrief answers are woven in when present — kept as their own read, and
set against the data rather than passed off as measurement ("I came away
frustrated — worth remembering I left faster than I arrived.") — and
NO letter grades: the grade panel sits right next to the journal
everywhere it is shown, and the entry should describe the achievement,
not the score.

journal_entry() returns {"icon": str, "text": str}; the icon is an emoji
for surfaces that can render one (the companion), and safely skippable
on the Pi.
"""

import hashlib

from .debrief import answer_label
from .focus import session_verdict
from .grading import session_facts, trend
from .parser import format_lap_time


def _pick(options, session, salt):
    """One phrasing from `options`, chosen stably from the session itself.

    The diary should not read identically session after session, but it must
    also not reword itself: the same entry is re-rendered every time it is
    opened, on the Pi and in the companion, and yesterday's page has to say
    today what it said yesterday. So the choice is *derived*, not random —
    keyed on the session's own identity (its file, when it started, the lap
    it turned), which is fixed the moment the session ends.

    Deliberately NOT `random` (different every render) and NOT the builtin
    `hash()` (Python salts string hashing per process, so it would differ
    between runs and between the two apps).

    `salt` names the slot being filled, so the phrases in one entry vary
    independently — without it every slot would land on the same index and
    the whole entry would move in lockstep.
    """
    key = "|".join((salt,
                    session.get("filename") or "",
                    str(session.get("date") or ""),
                    str(session.get("best_lap_time") or "")))
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return options[int.from_bytes(digest, "big") % len(options)]


_PB_CLOSE  = 0.3    # within this of the PB reads as "on my pace"
_THEO_MIN  = 0.15   # smaller sector gaps aren't worth writing about
_TIGHT_STD = 0.20   # clean-lap spread that reads as locked-in consistency
_ROUGH_INVALID_FRAC = 0.4   # ≥ this share invalid reads as a tough session

_NUM_WORDS = ("zero", "one", "two", "three", "four", "five", "six",
              "seven", "eight", "nine", "ten")


def _num(n):
    return _NUM_WORDS[n] if 0 <= n < len(_NUM_WORDS) else str(n)


def journal_entry(session, prior_best=None, grade_info=None, history=None,
                  awards=None):
    """The notebook entry for a parsed session.

    Returns {"icon": str, "text": str}; text is "" when there is nothing
    to write about (no timed laps).

    prior_best — best clean lap at the combo BEFORE this session.
    grade_info — unused (kept for call-site compatibility; grades never
    appear in the journal).
    history    — records.combo_history() rows; enables the trend line.
    awards     — achievements.session_awards() for this session; at most
    ONE badge is woven in (a career first can lead the entry, a
    milestone gets a closing clause, routine repeats get nothing — the
    multiplier on the badge itself carries those).
    """
    facts = session_facts(session)
    if not facts or not (facts.get("lap_count") or 0):
        return {"icon": "", "text": ""}
    debrief = session.get("debrief") or {}
    laps    = session.get("laps") or []

    best      = facts.get("best_lap_time")
    lap_count = facts.get("lap_count") or 0
    invalid_n = sum(1 for lap in laps if not lap.get("valid", True))
    improved  = bool(best and prior_best and best < prior_best)

    from .pace import net_positions
    from .parser import qualifying_outcome
    race = net_positions(session)
    # A qualifying session with no clean lap (a one-shot run, or a lone lap
    # spoiled by a flashback) still classified a real time — that grid result
    # is the story, not "no representative time".
    quali = qualifying_outcome(session) if not best else None

    if race and race[2] != 0:
        icon, parts = _race_story(session, facts, prior_best, race, debrief)
    elif quali:
        icon, parts = _qualifying_story(session, quali)
    elif improved:
        icon, parts = _pb_story(session, facts, prior_best, laps, debrief)
    elif lap_count and invalid_n / lap_count >= _ROUGH_INVALID_FRAC:
        icon, parts = _tough_story(session, facts, prior_best, invalid_n, debrief)
    elif _consistency_locked(session, facts, debrief):
        icon, parts = _consistency_story(session, facts, debrief)
    else:
        icon, parts = _steady_story(session, facts, prior_best, debrief)

    lead, badge_line = _award_lines(awards)
    if lead:
        parts.insert(0, lead)
    if badge_line:
        parts.append(badge_line)

    trend_line = _trend_line(session, history)
    if trend_line:
        parts.append(trend_line)
    feeling = _feeling_line(session, debrief, improved, facts)
    if feeling:
        parts.append(feeling)

    # The goal the driver committed to before the stint frames everything that
    # follows, so it goes above the story (and above a badge lead) — then the
    # scene-setter tops it, diary-style.
    # prior_best is passed through: the entry's own PB story is measured
    # against it, so the goal verdict must use the same baseline or the two
    # can contradict ("didn't come together" beside "new personal best").
    goal = _goal_line(session, session_verdict(session, facts, history or [],
                                               prior_best=prior_best))
    if goal:
        parts.insert(0, goal)
    when = _when_line(session)
    if when:
        parts.insert(0, when)

    return {"icon": icon, "text": " ".join(p for p in parts if p)}


# ── badges in the diary ─────────────────────────────────────────────────────

def _award_lines(awards):
    """(lead, closing) from the session's badge awards — at most one of
    each, and only where a badge adds something the story doesn't
    already say. Repeats never appear; badges whose feat IS the story
    (a win, a PB) have no phrase and fall through."""
    lead = None
    for a in awards or []:
        if a["id"] == "first_blood":
            lead = "My first race win."
            break
    for a in awards or []:
        if a["kind"] == "repeat" or a["id"] == "first_blood":
            continue
        line = _award_phrase(a)
        if line:
            return lead, line
    return lead, None


def _award_phrase(a):
    from .achievements import badge
    bid, count, kind = a["id"], a["count"], a["kind"]
    if bid in ("century", "regular", "globetrotter", "multi_disciplined"):
        levels = badge(bid)["levels"]
        lv = levels[min(count, len(levels)) - 1]
        return {
            "century":  f"That took the career past {lv:,} laps banked.",
            "regular":  f"That made it {lv} sessions in the book.",
            "globetrotter": f"Track number {lv} ticked off.",
            "multi_disciplined": f"That's {_num(lv)} games driven now.",
        }[bid]
    if bid == "hundred_home":
        return "That crossed a hundred career laps at this track."
    if bid == "clean_sweep":
        return ("Every lap came back clean — a first." if kind == "unlocked"
                else f"Clean sweep number {_num(count)} — becoming a habit.")
    if bid == "perfect_lap" and kind == "unlocked":
        return ("And for the first time, every best sector landed on "
                "the same lap.")
    if bid == "untouched":
        return ("Not a scratch on the car, either." if kind == "unlocked"
                else f"That makes {_num(count)} spotless wins.")
    return None


# ── stories ────────────────────────────────────────────────────────────────
#
# Story bodies are structural, but a few clauses recur across many entries of
# the same kind (every PB says "new personal best…"), so those carry variants
# picked deterministically per session — same rule as the framing lines.

_PB_OPENER = (
    "New personal best by {delta}s — {time} after {n} {attempts}.",
    "Personal best here, {delta}s quicker — {time} after {n} {attempts}.",
    "A new best at this track by {delta}s — {time}, {n} {attempts} in.",
    "Best here yet, down {delta}s — {time} after {n} {attempts}.",
)
_PB_MORE_PACE = (
    "{N} {laps} invalidated{cause} {suggest} there is still more pace to unlock.",
    "{N} {laps} invalidated{cause} — more pace is on the table once they stick.",
    "There is more to come: {n_low} {laps} went invalid{cause} this time.",
)
_PB_IN_SECTORS = (
    "Another {gap}s is still sitting in my best sectors.",
    "My best sectors are worth a further {gap}s together.",
    "Put the best sectors on one lap and there's {gap}s more.",
)


def _pb_story(session, facts, prior_best, laps, debrief):
    best  = facts["best_lap_time"]
    delta = prior_best - best
    n     = facts.get("lap_count") or 0
    parts = [_pick(_PB_OPENER, session, "pb").format(
        delta=f"{delta:.3f}", time=format_lap_time(best), n=_num(n),
        attempts="attempt" if n == 1 else "attempts")]

    # Where it came and what it took — the arc of the session.
    placement = _best_lap_placement(laps, best)
    invalid_n = sum(1 for lap in laps if not lap.get("valid", True))
    if invalid_n:
        parts.append(_pick(_PB_MORE_PACE, session, "pb-pace").format(
            N=_num(invalid_n).capitalize(), n_low=_num(invalid_n),
            laps="lap" if invalid_n == 1 else "laps",
            suggest="suggests" if invalid_n == 1 else "suggest",
            cause=_invalid_cause(debrief)))
    elif placement == "final":
        parts.append("It came on the final lap.")
    theo = facts.get("theo_time")
    if best and theo and best - theo >= _THEO_MIN:
        parts.append(_pick(_PB_IN_SECTORS, session, "pb-sectors").format(
            gap=f"{best - theo:.3f}"))
    if debrief.get("pb_change"):
        parts.append(f"I put the breakthrough down to "
                     f"{answer_label('pb_change', debrief['pb_change']).lower()}.")
    return "🏆", parts


def _qualifying_story(session, outcome):
    """A qualifying result when no clean lap was set — the classified grid
    slot and the lap that earned it, honest about a flashback / limits."""
    pos, total, best = outcome['position'], outcome['total'], outcome.get('best')
    head = f"Qualified P{pos}"
    if total:
        head += f" of {total}"
    if best:
        head += f" on a {format_lap_time(best)}"
    pole = outcome.get('pole')
    if pole and pole.get('gap') is not None:
        head += f", {pole['gap']:.3f}s off pole"
    parts = [head + "."]
    rewinds = sum(1 for e in session.get('events') or []
                  if e.get('type') == 'rewind')
    invalid = any(not lap.get('valid', True) for lap in session.get('laps') or [])
    if rewinds or invalid:
        reason = ("a flashback" if rewinds and not invalid
                  else "track limits" if invalid and not rewinds
                  else "a flashback and track limits")
        parts.append(f"The lap wasn't clean — {reason} — so it's no benchmark, "
                     "but it's the time that set my grid slot.")
    return "🏁", parts


def _race_story(session, facts, prior_best, race, debrief):
    start, finish, gained = race
    if gained > 0:
        head = (f"Gained {_num(gained)} "
                f"place{'s' if gained != 1 else ''} from P{start} to P{finish}.")
    else:
        head = (f"Slipped from P{start} to P{finish}.")
    parts = [head]

    best = facts.get("best_lap_time")
    pace_bit = ""
    if best and prior_best:
        if best <= prior_best + _PB_CLOSE:
            pace_bit = "Strong race pace"
        else:
            pace_bit = f"Race pace {best - prior_best:.3f}s off my best"
    incidents = (facts.get("collision_count") or 0) + \
                (facts.get("penalty_count") or 0)
    if pace_bit and incidents:
        parts.append(f"{pace_bit}, but {_num(incidents)} "
                     f"incident{'s' if incidents != 1 else ''} limited the "
                     f"overall result.")
    elif pace_bit:
        parts.append(f"{pace_bit} throughout.")
    elif incidents:
        parts.append(f"{_num(incidents).capitalize()} "
                     f"incident{'s' if incidents != 1 else ''} shaped the "
                     f"result more than pace did.")
    return "🏁", parts


_TOUGH_OPENER = ("Tough session.", "A scrappy one.", "Hard going today.",
                 "A messy session.")


def _tough_story(session, facts, prior_best, invalid_n, debrief):
    parts = [_pick(_TOUGH_OPENER, session, "tough")]
    best = facts.get("best_lap_time")
    cause = _invalid_cause(debrief) or " to invalidation"
    competitive = bool(best and prior_best and best <= prior_best + _PB_CLOSE)
    repeated = f"losing {_num(invalid_n)} laps{cause}"
    if competitive:
        parts.append(f"The pace was competitive, but {repeated} prevented a "
                     f"representative benchmark.")
    else:
        parts.append(f"{repeated.capitalize()} left little to measure — "
                     f"the best that counted was "
                     f"{format_lap_time(best) if best else 'incomplete'}.")
    return "", parts


def _consistency_locked(session, facts, debrief):
    # The consistency intent now lives in the committed focus (an F row); the
    # debrief only carries "goal" for a focus-less session, so check both.
    std = facts.get("clean_std_dev")
    wanted = ((session.get("focus") or "").strip() == "consistency"
              or debrief.get("goal") == "consistency")
    return std is not None and (std <= _TIGHT_STD or wanted)


_CONS_LOCKED = (
    "Consistency locked in — clean laps within ±{std}s.",
    "Metronomic — clean laps inside ±{std}s.",
    "Dialled in — the clean laps held to ±{std}s.",
)
_CONS_DAY = (
    "A consistency day: clean laps within ±{std}s.",
    "A rhythm session — clean laps within ±{std}s.",
    "Working on repeatability: clean laps within ±{std}s.",
)
_CONS_WAITING = (
    "{gap}s of sector pace is still waiting to be put together.",
    "There's {gap}s to gain by stringing my best sectors into one lap.",
    "My sectors are worth {gap}s more on a single lap.",
)


def _consistency_story(session, facts, debrief):
    std  = facts.get("clean_std_dev")
    best = facts.get("best_lap_time")
    theo = facts.get("theo_time")
    opener = _CONS_LOCKED if (std is not None and std <= _TIGHT_STD) else _CONS_DAY
    parts = [_pick(opener, session, "cons").format(std=f"{std:.3f}")]
    if best and theo:
        gap = best - theo
        if gap < 0.2:
            parts.append("Theoretical pace is within two tenths of my "
                         "fastest clean lap — the laps are already complete.")
        elif gap >= _THEO_MIN:
            parts.append(_pick(_CONS_WAITING, session, "cons-wait").format(
                gap=f"{gap:.3f}"))
    return "📈", parts


_BASELINE_HEAD = (
    "First marker here — {time} from {laps}.",
    "A baseline set here — {time} from {laps}.",
    "First time on record here — {time} from {laps}.",
    "Marker down at this track — {time} from {laps}.",
)


def _steady_story(session, facts, prior_best, debrief):
    best = facts.get("best_lap_time")
    n    = facts.get("lap_count") or 0
    clean = facts.get("clean_lap_count")
    laps_bit = f"{_num(n)} lap{'s' if n != 1 else ''}"
    if clean is not None and clean != n:
        laps_bit += f", {_num(clean)} clean"
    if best and prior_best:
        gap = best - prior_best
        if gap <= _PB_CLOSE:
            head = (f"On my pace — {format_lap_time(best)} from {laps_bit}, "
                    f"within {gap:.3f}s of my best here.")
        else:
            head = (f"{format_lap_time(best)} from {laps_bit}, "
                    f"{gap:.3f}s off my best here.")
    elif best:
        head = _pick(_BASELINE_HEAD, session, "baseline").format(
            time=format_lap_time(best), laps=laps_bit)
    else:
        head = f"{laps_bit.capitalize()} without a representative time."
    parts = [head]
    theo = facts.get("theo_time")
    if best and theo and best - theo >= _THEO_MIN:
        parts.append(f"My best sectors add up to "
                     f"{format_lap_time(theo)} — the complete lap is there.")
    return "", parts


# ── shared clauses ─────────────────────────────────────────────────────────

def _best_lap_placement(laps, best):
    """'final' when the session's best lap was the last one driven."""
    if not laps or not best:
        return ""
    newest = laps[0] if laps[0].get("num", 0) >= laps[-1].get("num", 0) else laps[-1]
    return "final" if abs((newest.get("time") or 0) - best) < 0.001 else ""


def _invalid_cause(debrief):
    """' for track limits' — the driver's own explanation when asked. Reads
    the invalid-cause answer, or the corner-trouble reaction (' to braking
    too late') when a single corner dominated the session's mistakes and that
    question was asked instead."""
    aid = debrief.get("invalid_cause")
    if aid and aid != "not_sure":
        return f" for {answer_label('invalid_cause', aid).lower()}"
    aid = debrief.get("corner_trouble")
    if aid and aid != "not_sure":
        return f" to {answer_label('corner_trouble', aid).lower()}"
    return ""


# What each focus was an attempt to DO — the diary records the intent in the
# driver's terms, not the chip label.
_FOCUS_AIM = {
    "faster":      "chase a faster lap",
    "consistency": "string consistent laps together",
    "clean":       "keep it clean",
}


# Phrasings per outcome. Each entry picks one via _pick(), so the diary
# varies between sessions without ever rewording an entry you've already read.
_GOAL_MET = (
    "I set out to {aim} — and did.",
    "The plan was to {aim}, and it came off.",
    "I went out to {aim}; job done.",
    "The brief was to {aim} — delivered.",
    "I wanted to {aim}, and I got it.",
    "Out to {aim}, and that is exactly what happened.",
    "I asked myself to {aim}, and I answered.",
)
_GOAL_MISSED = (
    "I set out to {aim}; it didn't come together this time.",
    "The plan was to {aim} — not this time.",
    "I went out to {aim}, but it didn't land today.",
    "The brief was to {aim}; that one got away.",
    "I wanted to {aim} — it stayed out of reach.",
    "Out to {aim}, but it wouldn't come together.",
    "I asked myself to {aim}; not today.",
)
_GOAL_OPEN = (
    "I set out to {aim}.",
    "The plan was to {aim}.",
    "I went out to {aim}.",
    "The brief was to {aim}.",
    "Out to {aim} today.",
)


def _goal_line(session, verdict):
    """The focus committed to before the stint, and whether it came off.

    Intent and outcome only — the verdict's numbers stay in the Race Engineer
    Notes. A "just drive" / unset focus has no verdict and writes nothing.
    """
    if not verdict:
        return ""
    aim = _FOCUS_AIM.get((session.get("focus") or "").strip())
    if not aim:
        return ""
    met = verdict.get("met")
    options = (_GOAL_MET if met is True
               else _GOAL_MISSED if met is False else _GOAL_OPEN)
    return _pick(options, session, "goal").format(aim=aim)


# Hour (exclusive) → how the driver would refer to that part of their day.
_WHEN_BANDS = ((12, "this morning"), (17, "this afternoon"),
               (22, "this evening"))


# No "back at {track}" / "another run" phrasings: a return visit is not
# something the scene-setter has checked, and the notebook never asserts what
# it hasn't seen.
_WHEN_AT_TRACK = (
    "Out {when} at {track}.",
    "{When} at {track}.",
    "A run at {track} {when}.",
    "{track}, {when}.",
    "{When}, out at {track}.",
    "A stint at {track} {when}.",
    "{when} at {track} — and it went like this.",
)
_WHEN_ONLY = (
    "Out {when}.",
    "{When}.",
    "A run {when}.",
    "A stint {when}.",
)


def _when_line(session):
    """Diary scene-setter — 'Out this evening at Spa.'

    session['date'] is the S,started_at wall time (Pi local, no timezone),
    which is exactly the driver's own sense of when they drove — so the
    present-tense diary voice ("this evening") stays true when re-read later.
    """
    when = _when_phrase(session.get("date"))
    if not when:
        return ""
    track = (session.get("track") or "").strip()
    options = _WHEN_AT_TRACK if track else _WHEN_ONLY
    return _pick(options, session, "when").format(
        when=when, When=when.capitalize(), track=track)


def _when_phrase(date):
    hour = getattr(date, "hour", None)   # datetime | None (flat/old files)
    if hour is None:
        return ""
    for cutoff, phrase in _WHEN_BANDS:
        if hour < cutoff:
            return phrase
    return "late tonight"


_TREND_IMPROVING = (
    "The pace trend here keeps improving.",
    "My times here have been trending the right way.",
    "Recent visits here have been getting quicker.",
    "The arc across recent runs here points upward.",
    "I've been finding time here visit on visit.",
)
_TREND_DECLINING = (
    "Pace has slipped across recent visits.",
    "The last few visits here have drifted slower.",
    "Recent runs here have been off my earlier pace.",
    "The trend here has softened lately.",
    "Recent visits here haven't matched my earlier pace.",
)

# Whether an entry carries the trend line at all — ~1 in 2, chosen per
# session so it's stable but breaks up runs. The trend is a combo-level fact
# (the same across nearby sessions here), so stating it every single time —
# even reworded — nags; it also lives in full on the records/profile screens.
_TREND_SHOW = (True, False)


def _trend_line(session, history):
    t = trend(history) if history else None
    if not t:
        return ""
    options = {"improving": _TREND_IMPROVING,
               "declining": _TREND_DECLINING}.get(t.get("direction"))
    if not options or not _pick(_TREND_SHOW, session, "trend-show"):
        return ""
    return _pick(options, session, "trend")


# The driver's own word for the session, set against what the data shows.
# Several phrasings each so a run of similar sessions doesn't read identically.
_FEEL_FRUSTRATED_IMPROVED = (
    "I came away frustrated — worth remembering I left faster than I "
    "arrived.",
    "It left me frustrated, though I went home quicker than I came.",
    "Frustrating, I know — but the lap times moved the right way.",
    "Frustrating as it was, the clock still says I improved.",
    "Frustration aside, I left quicker than I turned up.",
    "It rankled — even so, I ended the day faster than I started it.",
)
_FEEL_FRUSTRATED = (
    "I came away frustrated; the numbers are the honest reference.",
    "Frustrating, I know — the numbers are the level head here.",
    "Frustrating as it felt, the data is the fairer judge.",
    "It left me frustrated — let the numbers, not the mood, be the record.",
    "Frustrating, I thought; the figures are the cooler read.",
    "I finished frustrated. The log keeps its own counsel.",
)
_FEEL_TIRED_SPREAD = (
    "I was tired, and the lap spread showed it.",
    "Tired — and the scatter in the laps backs that up.",
    "I finished tired, and the laps wandered to match.",
    "Tired by the end, and the spread agrees.",
    "I was tired; the lap-to-lap scatter says the same.",
    "Tired — and the laps drifted about as much as that suggests.",
)
_FEEL_TIRED = (
    "I finished tired.",
    "I came away tired.",
    "Tired by the end.",
    "A tired one.",
    "Tired when I stopped.",
)
_FEEL_GOOD_IMPROVED = (
    "It felt {feeling} out there, and the stopwatch agreed.",
    "A {feeling} one, and the stopwatch backed me up.",
    "Felt {feeling} to me — and the times say the same.",
    "A {feeling} one by my reckoning, and the clock concurs.",
    "It felt {feeling}; the lap times said so too.",
    "My read of {feeling} matched what the clock did.",
)
_FEEL_GOOD = (
    "It felt {feeling} out there.",
    "A {feeling} one, by my own reckoning.",
    "I came away feeling {feeling}.",
    "That one felt {feeling}.",
    "It felt {feeling} by the end.",
)


def _feeling_line(session, debrief, improved, facts):
    feeling = debrief.get("feeling")
    if not feeling:
        return ""
    std = facts.get("clean_std_dev")
    if feeling == "frustrated":
        options = _FEEL_FRUSTRATED_IMPROVED if improved else _FEEL_FRUSTRATED
    elif feeling == "tired":
        options = (_FEEL_TIRED_SPREAD
                   if std is not None and std > 0.35 else _FEEL_TIRED)
    elif feeling in ("great", "good"):
        options = _FEEL_GOOD_IMPROVED if improved else _FEEL_GOOD
    else:
        return ""
    return _pick(options, session, "feeling").format(feeling=feeling)
