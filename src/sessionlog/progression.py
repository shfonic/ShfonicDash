"""
Shfonic Dash sessionlog — within-session progression (shared library;
canonical home is ShfonicDash/src/sessionlog/, vendored into the
companion app by sync_shared.py — see the package docstring).

Every other coaching signal (grading, focus verdict, most of the Race
Engineer Notes) reads a session as one flat aggregate: a session that
started a mess and ended clean scores the same as one that fell apart. A
40%-invalid number hides whether the driver was *learning* — track limits
early, tidying up lap by lap, pace only coming down once the laps were
clean.

This module reads the session as an ordered story instead:
  * progression_facts() — early-vs-late clean rate, first clean lap, the
    pace trend over representative clean laps, and per-sector spread.
  * progression_notes() — the driver-facing notes those facts support:
    a clean summary (% clean + longest consecutive run), a within-session
    cleanliness trend ("you tidied up as the session went on"), a pace
    trend, and which sector is leaking the time.

Evidence only — every note states what the ordered laps show; nothing is
invented, and no cause is attributed (the debrief covers intent). Pure
standard library, Python 3.10-safe (the companion floor).
"""

from statistics import pstdev

from .parser import classify_laps, format_lap_time

# --- thresholds -------------------------------------------------------------
# A progression read needs enough laps to have a first half and a second
# half worth comparing; a single bad out-lap shouldn't read as "a rough
# start".
_MIN_TIMED_PROGRESS = 6      # timed laps before a clean-up trend is meaningful
_CLEAN_JUMP = 0.25           # late clean-frac must beat early by this to count
_MIN_CLEAN_TREND = 4         # representative clean laps before a pace trend
_PACE_TREND_S = 0.15         # median pace shift (s) that reads as a real trend
_MIN_FULL_SECTORS = 3        # clean full laps before a sector-spread read
_SECTOR_DOMINANT = 1.6       # worst sector spread must exceed the next by this
_SECTOR_LOOSE_S = 0.08       # ...and be at least this loose to bother flagging
_SECTOR_TIGHT_S = 0.05       # all three under this reads as "very consistent"


def _is_clean(lap):
    return lap.get('valid', True) and not lap.get('rewinds', 0)


def _timed(session):
    """Timed laps in lap order (parser order, made explicit by num)."""
    laps = [lap for lap in session.get('laps') or []
            if lap.get('time') is not None]
    return sorted(laps, key=lambda lap: (lap.get('num') is None,
                                         lap.get('num') or 0))


def _median(values):
    s = sorted(values)
    n = len(s)
    if not n:
        return None
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _best_streak(laps):
    """Longest run of consecutive clean laps (mirrors grading.session_facts
    so the two never disagree)."""
    streak = best = 0
    for lap in laps:
        streak = streak + 1 if _is_clean(lap) else 0
        best = max(best, streak)
    return best


def progression_facts(session):
    """Ordered-session metrics the progression notes are built from.

    {
      'timed':            int,     # timed laps
      'clean':            int,     # clean laps (valid, no rewind)
      'best_streak':      int,     # longest consecutive clean run
      'first_clean_num':  int | None,   # lap number of the first clean lap
      'early_clean_frac': float | None, # clean fraction, first half of timed
      'late_clean_frac':  float | None, # clean fraction, second half of timed
      'pace_trend':       float | None, # late median − early median over
                                        # representative clean laps
                                        # (negative = getting quicker)
      'sector_std':       {'s1','s2','s3': float} | None,  # spread per sector
    }

    The *_frac and pace_trend fields are None until there are enough laps to
    read a trend (a two-lap session has no "second half" worth comparing).
    """
    timed = _timed(session)
    n = len(timed)
    clean_laps = [lap for lap in timed if _is_clean(lap)]

    facts = {
        'timed': n,
        'clean': len(clean_laps),
        'best_streak': _best_streak(timed),
        'first_clean_num': next((lap.get('num') for lap in timed
                                 if _is_clean(lap)), None),
        'early_clean_frac': None,
        'late_clean_frac': None,
        'pace_trend': None,
        'sector_std': None,
    }

    if n >= _MIN_TIMED_PROGRESS:
        half = n // 2
        early, late = timed[:half], timed[half:]
        facts['early_clean_frac'] = sum(_is_clean(l) for l in early) / len(early)
        facts['late_clean_frac'] = sum(_is_clean(l) for l in late) / len(late)

    # Pace trend over REPRESENTATIVE clean laps only — an out-lap or a
    # cool-down isn't the driver's pace dropping off. Same exclusion set the
    # consistency grade uses.
    excluded = set(classify_laps(session))
    rep = [lap['time'] for lap in clean_laps if lap.get('num') not in excluded]
    if len(rep) >= _MIN_CLEAN_TREND:
        half = len(rep) // 2
        early_m, late_m = _median(rep[:half]), _median(rep[half:])
        if early_m is not None and late_m is not None:
            facts['pace_trend'] = late_m - early_m

    full = [lap for lap in clean_laps
            if lap.get('s1') is not None and lap.get('s2') is not None
            and lap.get('s3') is not None]
    if len(full) >= _MIN_FULL_SECTORS:
        facts['sector_std'] = {
            key: pstdev([lap[key] for lap in full])
            for key in ('s1', 's2', 's3')
        }
    return facts


def _note(text, category=None):
    return {'text': text, 'locations': [], 'category': category}


def _clean_note(facts):
    """% clean + longest consecutive run, with the within-session clean-up
    trend woven in when the driver clearly tidied up as they went."""
    total = facts['timed']
    if total < 3:
        return None
    clean = facts['clean']
    pct = round(clean / total * 100)
    streak = facts['best_streak']

    if clean == total:
        text = (f"All {total} laps were clean"
                + (f", {streak} in a row" if streak >= 3 else "")
                + " — a tidy session.")
        return _note(text, category='incidents')

    text = f"{clean} of {total} laps clean ({pct}%)"
    if streak >= 2:
        text += f", best run {streak} in a row"
    text += "."

    early, late = facts['early_clean_frac'], facts['late_clean_frac']
    if (early is not None and late is not None
            and late - early >= _CLEAN_JUMP and early < 1.0):
        text += (" You tidied up as the session went on — the second half "
                 f"was {round(late * 100)}% clean against {round(early * 100)}% "
                 "in the first.")
    return _note(text, category='incidents')


def _pace_trend_note(facts):
    """Whether the representative clean laps got quicker or drifted off."""
    trend = facts['pace_trend']
    if trend is None:
        return None
    if trend <= -_PACE_TREND_S:
        return _note(
            "Your pace kept coming down — the later clean laps were about "
            f"{-trend:.2f}s quicker than the earlier ones.", category='pace')
    if trend >= _PACE_TREND_S:
        return _note(
            "Your clean-lap pace drifted the other way — the later laps were "
            f"about {trend:.2f}s slower than the earlier ones.",
            category='consistency')
    return None


_SECTOR_LABEL = {'s1': 'Sector 1', 's2': 'Sector 2', 's3': 'Sector 3'}


def _sector_variation_note(facts):
    """Which sector is leaking the time — or that all three were steady."""
    std = facts['sector_std']
    if not std:
        return None
    ranked = sorted(std.items(), key=lambda kv: -kv[1])
    worst_key, worst = ranked[0]
    second = ranked[1][1]
    if worst >= _SECTOR_LOOSE_S and worst >= _SECTOR_DOMINANT * second:
        return _note(
            f"Your sector times were steady except {_SECTOR_LABEL[worst_key]}, "
            f"which swung ±{worst:.2f}s — that's where the lap time is "
            "leaking.", category='consistency')
    if all(v <= _SECTOR_TIGHT_S for v in std.values()):
        widest = max(std.values())
        return _note(
            "Your sector times were very consistent — within "
            f"±{widest:.2f}s across all three.", category='consistency')
    return None


def progression_notes(session, facts=None):
    """Within-session progression notes, in the
    ``pace.race_engineer_notes_detailed`` shape
    (``{text, locations, category}`` — ``locations`` always empty, these are
    session-wide reads, not track positions). ``category`` lets the caller's
    focus weighting float them like any other note.

    Skipped for races (start traffic, fuel burn and tyre deg make an
    early-vs-late read meaningless) and for sessions too short to show a
    trend. A no-op that returns ``[]`` rather than noise when nothing is
    provable.
    """
    stype = (session.get('session_type') or '').strip().lower()
    if stype == 'race':
        return []
    if facts is None:
        facts = progression_facts(session)

    notes = []
    for builder in (_clean_note, _pace_trend_note, _sector_variation_note):
        note = builder(facts)
        if note:
            notes.append(note)
    return notes
