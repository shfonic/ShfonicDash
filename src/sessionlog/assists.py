"""
Shfonic Dash sessionlog — assist-usage coaching (shared library; canonical
home is ShfonicDash/src/sessionlog/, vendored into the companion app
by sync_shared.py — see the package docstring).

F1 sessions log the highest level each assist reached on every lap (the
`assist_*` L-row columns — see docs/session-log-format.md). This module turns
those into Race Engineer Notes suggesting a driver reduce assist reliance as
their skill builds: racing line, TC, ABS and gearbox assist — the assists
tied to raw driving skill. Steering, braking, pit, pit release, ERS and DRS
assist are logged (same L-row columns) but not coached here.

Evidence only — a note names how many laps an assist was used, never claims
the driver is or isn't ready to drop it.
"""

# (lap dict key, sentence-ready subject, follow-up advice)
_CATEGORIES = [
    ("assist_racing_line", "The racing line assist",
     "Turning it off once the track layout is memorised sharpens braking "
     "and turn-in habits."),
    ("assist_tc", "Traction control",
     "Dropping a level at a time builds throttle control without a big "
     "lap-time hit."),
    ("assist_abs", "ABS",
     "Turning it off sharpens threshold-braking feel — expect some "
     "lock-ups while you adapt."),
    ("assist_gearbox", "The gearbox assist",
     "Full manual builds the habit of matching shifts to corner entry."),
]


def assist_notes(session):
    """Evidence-based Race Engineer Notes for racing line / TC / ABS /
    gearbox assist usage this session.

    One note per category used on at least one lap — never for a category
    that was off all session (nothing to suggest) or a file that predates
    assist logging (missing column reads as None, not 0/off).
    Returns [{'text': str, 'locations': []}, ...] — no locations, this is a
    session-wide setting, not a track position.
    """
    laps = session.get('laps', [])
    total = len(laps)
    notes = []
    if not total:
        return notes
    for key, subject, advice in _CATEGORIES:
        used = sum(1 for lap in laps if (lap.get(key) or 0) > 0)
        if not used:
            continue
        lap_word = "lap" if total == 1 else "laps"
        notes.append({
            'text': (f"{subject} was on for {used} of {total} {lap_word} "
                     f"this session. {advice}"),
            'locations': [],
        })
    return notes
