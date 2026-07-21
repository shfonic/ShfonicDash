"""
Shfonic Dash sessionlog — pace facts + Race Engineer Notes (shared library;
canonical home is ShfonicDash/src/sessionlog/, vendored into the
companion app by sync_shared.py — see the package docstring).

The Race Engineer Notes engine, extracted from the companion's dashboard.py:
pace_facts() distils a parsed session dict into the metrics every
consumer needs (fastest clean lap, theoretical best, gap, sectors set on
non-clean laps), and race_engineer_notes() turns those facts into the
driver-facing, evidence-only note list. Consumers compose the notes with
grading output themselves (the companion prepends the grade explanation
and milestones; the Pi shows the headline plus the top few notes).

The notes are session-aware: races never get gap-to-theoretical advice
(the theoretical lap is nearly irrelevant under fuel, tyres and
traffic) — they get a race-engineer summary against the prior best race
lap instead, and when the pace was there but the session was incident-
heavy, a synthesis over the whole race (net_positions() start → finish,
pace vs prior best, incidents as the limiter) — and qualifying points
out when a low grid slot came with
a lap close to the PB (the field's competitiveness, not
underperformance). contact_incidents() groups collision→rewind→
collision chains into distinct contact events, so a rewound-and-
repeated incident is reported once, not three times — but two bare
collisions with no rewind between them only fold together when they're
seconds apart (a genuine pileup); otherwise they're unrelated incidents
even if both land inside the same half-minute.

Given a `track_map` (trackmap.find_map()), contact incidents and
track-limits warnings are placed against the map's labelled `sections`
('at Turn 3, before the apex') instead of a bare lap number — see
trackmap.py. Without one, the caller doesn't have a map for this
game/track (or none exists yet) and the notes read as they always did.
"""

from . import assists as _assists
from . import lines as _lines
from . import progression as _progression
from . import trackmap
from .grading import RACE_TYPES
from .parser import classify_laps, format_lap_time, penalty_detail, qualifying_outcome

_NUM_WORDS = ('zero', 'one', 'two', 'three', 'four', 'five', 'six',
              'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve')

# Gap (s) to the theoretical best at or under which the fastest lap counts as
# already holding every best clean sector — i.e. theoretical IS the fastest
# lap. Sector times are logged to 3dp, so this is a rounding tolerance, not a
# judgement call: at 0.0 the driver has provably assembled the lap.
_THEO_ASSEMBLED_S = 0.05


def _num_word(n):
    """Small count → word ('four'); falls back to digits beyond twelve."""
    return _NUM_WORDS[n] if 0 <= n < len(_NUM_WORDS) else str(n)


def pace_facts(session):
    """Pace metrics shared by the share text and the dashboard's Race Engineer panel.

    clean = game-valid AND no rewinds used.
    """
    laps       = session.get('laps', [])
    clean_laps = [lap for lap in laps if lap.get('valid', True) and not lap.get('rewinds', 0)]
    dirty_laps = [lap for lap in laps if lap not in clean_laps]

    valid_times = [lap['time'] for lap in clean_laps if lap.get('time') is not None]
    # Representative push laps: clean minus out/in/SC/start/cooldown laps.
    classes   = classify_laps(session)
    rep_times = [lap['time'] for lap in clean_laps
                 if lap.get('time') is not None
                 and lap.get('num') not in classes]
    s1s = [lap['s1'] for lap in clean_laps if lap.get('s1') is not None]
    s2s = [lap['s2'] for lap in clean_laps if lap.get('s2') is not None]
    s3s = [lap['s3'] for lap in clean_laps if lap.get('s3') is not None]

    facts = {
        'clean_laps': clean_laps, 'valid_times': valid_times,
        'rep_times': rep_times,
        's1s': s1s, 's2s': s2s, 's3s': s3s,
        'fastest': None, 'fastest_num': None,
        'dirty_best': None,       # (time, lap_num) of the quickest non-clean lap
        'dirty_faster': False,    # quickest non-clean lap beats the fastest clean lap
        'theo': None, 'gap': None,
        'pushed_sectors': [],     # (sector_key, time, lap_num) beating clean bests
    }

    if valid_times:
        fastest = min(valid_times)
        facts['fastest'] = fastest
        facts['fastest_num'] = next(lap['num'] for lap in clean_laps
                                    if lap.get('time') == fastest)
        dirty_times = [(lap['time'], lap['num']) for lap in dirty_laps
                       if lap.get('time') is not None]
        if dirty_times:
            facts['dirty_best'] = min(dirty_times)
            facts['dirty_faster'] = facts['dirty_best'][0] < fastest

    if s1s and s2s and s3s:
        facts['theo'] = min(s1s) + min(s2s) + min(s3s)
        if facts['fastest'] is not None:
            facts['gap'] = facts['fastest'] - facts['theo']
        # Sector bests set on non-clean laps — pace shown but never converted.
        for key, best_clean in (('s1', min(s1s)), ('s2', min(s2s)), ('s3', min(s3s))):
            dirty = [(lap[key], lap['num']) for lap in dirty_laps
                     if lap.get(key) is not None]
            if dirty and min(dirty)[0] < best_clean:
                v, n = min(dirty)
                facts['pushed_sectors'].append((key, v, n))
    return facts


def contact_incidents(events, window=30.0, pileup_window=8.0):
    """Group collision/rewind chains into distinct contact incidents.

    A rewind duplicates events: contact → rewind → contact → rewind →
    contact may all be the same incident retried, so a collision or rewind
    following one within `window` seconds of a **rewind** chains into the
    open incident (wall-clock 't' when both events carry it, same lap
    number otherwise) — generous, since the driver needs time to react,
    flash back and get going again.

    A bare collision directly following another collision, with no rewind
    between them, only chains within the much tighter `pileup_window`: two
    contacts a genuine multi-car pileup apart (same corner, seconds apart)
    are one incident, but two contacts that both happen to land inside the
    same half-minute — different drivers, hundreds of metres apart — are
    two unrelated incidents, not a retry of the same one (nothing was
    rewound in between to justify folding them together).

    A rewind with no open incident is not a contact incident, and breaks
    any chain.

    Returns, in session order:
      [{'lap_num':  lap of the first contact,
        'drivers':  distinct 'detail' names involved, in order,
        'contacts': raw collision events folded into this incident,
        'rewound':  True when a flashback followed the contact,
        't':        wall-clock seconds of the first contact | None,
        'distance': metres into the lap of the first contact | None
                    (F1 only — see trackmap.describe_location)}, ...]
    """
    incidents      = []
    open_inc       = None
    last_t         = None
    last_lap       = None
    last_was_rewind = False
    for e in events or []:
        etype = e.get('type')
        if etype not in ('collision', 'rewind'):
            continue
        t, lap  = e.get('t'), e.get('lap_num')
        chained = False
        if open_inc is not None:
            w = window if (etype == 'rewind' or last_was_rewind) else pileup_window
            if t is not None and last_t is not None:
                chained = 0 <= t - last_t <= w
            else:
                chained = lap is not None and lap == last_lap
        if etype == 'collision':
            who = e.get('detail')
            if chained:
                open_inc['contacts'] += 1
                if who and who not in open_inc['drivers']:
                    open_inc['drivers'].append(who)
            else:
                open_inc = {'lap_num': lap,
                            'drivers': [who] if who else [],
                            'contacts': 1, 'rewound': False, 't': t,
                            'distance': e.get('distance')}
                incidents.append(open_inc)
            last_t, last_lap, last_was_rewind = t, lap, False
        elif open_inc is not None and chained:
            open_inc['rewound'] = True
            last_t, last_lap, last_was_rewind = t, lap, True
        else:
            # A stray rewind (no recent contact) ends any chain: a later
            # collision is a new incident, not part of this one.
            open_inc = None
            last_t = last_lap = None
            last_was_rewind = False
    return incidents


def _row_pos(row):
    """Grid/standings row position → int | None (values are raw strings)."""
    try:
        return int(str(row.get('position') or '').strip())
    except ValueError:
        return None


def net_positions(session):
    """Race start → finish for the player → (start, finish, gained) | None.

    Start from the G (grid) rows, finish from the R (standings) rows,
    falling back to the last lap carrying a position; gained =
    start − finish (positive = places made up). None unless this is a
    race with both ends known.
    """
    if (session.get('session_type') or '').strip().lower() not in RACE_TYPES:
        return None
    driver = (session.get('driver_name') or '').strip().lower()
    if not driver:
        return None
    start  = next((_row_pos(g) for g in session.get('grid') or []
                   if (g.get('name') or '').strip().lower() == driver), None)
    finish = next((_row_pos(s) for s in session.get('standings') or []
                   if (s.get('name') or '').strip().lower() == driver), None)
    if finish is None:
        finish = next((lap['position']
                       for lap in reversed(session.get('laps') or [])
                       if lap.get('position') is not None), None)
    if start is None or finish is None:
        return None
    return (start, finish, start - finish)


def _incident_phrase(n_incidents, n_rewinds):
    """'two contact events and three flashbacks' (either part optional)."""
    bits = []
    if n_incidents:
        bits.append(f"{_num_word(n_incidents)} contact event"
                    f"{'s' if n_incidents != 1 else ''}")
    if n_rewinds:
        bits.append(f"{_num_word(n_rewinds)} flashback"
                    f"{'s' if n_rewinds != 1 else ''}")
    return " and ".join(bits)


def _collision_severity(events):
    """Worst recorded collision severity per other driver, from the stewards'
    penalty infringements ('small collision' / 'big collision', which name the
    other driver). Returns {DRIVER_UPPER: 'big' | 'small'} — 'big' always wins.
    Used to colour a contact marker red (major) vs orange (ordinary contact)."""
    sev = {}
    for e in events:
        if e.get('type') != 'penalty':
            continue
        info = penalty_detail(e.get('detail'))
        infr = (info.get('infringement') or '').lower()
        if 'collision' not in infr:
            continue
        drv = (info.get('driver') or '').strip().upper()
        if not drv:
            continue
        if 'big' in infr:
            sev[drv] = 'big'
        elif drv not in sev:
            sev[drv] = 'small'
    return sev


def track_limit_counts(events, track_map):
    """{label: count} of track-limit warnings per resolved section — the
    reusable bucketing `_track_limit_note` (this session) and
    `_track_limit_hotspot_comparison` (against the previous session) both
    build on. {} without a track map, without any warnings, or when none
    resolve to a labelled section (map has no `sections`)."""
    if not track_map:
        return {}
    warns = [e for e in events if e.get('type') == 'track_limit_warning']
    if not warns:
        return {}
    sections     = track_map.get('sections') or []
    track_length = track_map.get('game_track_length_m')
    counts = {}
    for e in warns:
        sec = trackmap.locate_section(e.get('distance'), sections, track_length)
        if sec is None:
            continue
        label = trackmap.section_label(sec)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _track_limit_note(events, track_map):
    """('Three track-limits warnings — two at Turn 8, one at Turn 3.',
        [{'label': 'Turn 8', 'distance': …}, …]).

    (None, []) without a track map, without any warnings, or when none of
    the warnings resolve to a labelled section (map has no `sections`). The
    locations are one per distinct section, ordered by warning count
    (matching the sentence), each carrying the first warning's distance so
    a caller can crop a thumbnail of that corner.
    """
    counts = track_limit_counts(events, track_map)
    if not counts:
        return None, []
    sections     = (track_map or {}).get('sections') or []
    track_length = (track_map or {}).get('game_track_length_m')
    first_dist = {}
    for e in events:
        if e.get('type') != 'track_limit_warning':
            continue
        sec = trackmap.locate_section(e.get('distance'), sections, track_length)
        if sec is None:
            continue
        label = trackmap.section_label(sec)
        if label not in first_dist:
            first_dist[label] = e.get('distance')
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    locations = [{'label': label, 'distance': first_dist[label],
                  'kind': 'track_limit', 'rewound': False}
                 for label, _ in ranked]
    n = sum(counts.values())
    if len(ranked) == 1 and ranked[0][1] == n:
        text = (f"All {_num_word(n)} track-limits warning{'s' if n != 1 else ''} "
                f"were flagged at {ranked[0][0]}.")
    else:
        parts = [f"{_num_word(c)} at {label}" for label, c in ranked[:3]]
        text = (f"{_num_word(n).capitalize()} track-limits warning"
                f"{'s' if n != 1 else ''} recorded — {', '.join(parts)}.")
    return text, locations


def _track_limit_hotspot_comparison(events, track_map, prior_hotspot):
    """(text, locations) comparing this session's warning count, at the
    corner that dominated the PREVIOUS session's warnings, against that
    prior count. (None, []) without a prior hotspot or a track map — this
    only fires when a pre-session "watch this corner" goal was actually
    shown (sessionlog.goals' track_limit_hotspot mission), so the follow-up
    always answers the question the goal posed.

    prior_hotspot — {'label': str, 'count': int} for the corner that
    dominated the previous session's warnings (see core.pre_session /
    sessionlog.goals — both re-derive this the same way, nothing is
    persisted, so the two can never drift out of sync).
    """
    if not prior_hotspot or not track_map:
        return None, []
    counts = track_limit_counts(events, track_map)
    label = prior_hotspot['label']
    n = counts.get(label, 0)
    prior_n = prior_hotspot['count']
    if n == 0:
        text = (f"{label} caught you out {_num_word(prior_n)} times last "
                f"session — clean there this time.")
    elif n < prior_n:
        text = (f"{label}: {_num_word(n)} warning{'s' if n != 1 else ''} "
                f"this session, down from {prior_n}.")
    else:
        text = (f"{label} is still catching you out — {_num_word(n)} "
                f"warning{'s' if n != 1 else ''} again.")
    return text, [{'label': label, 'distance': None,
                   'kind': 'track_limit', 'rewound': False}]


def _quali_result_note(session):
    """The lap that classified the driver, stated plainly — the result of a
    one-shot / lone-lap qualifying, which stands even when no lap passed the
    "clean" filter (a flashback on the only run). Evidence-only: the time and
    grid slot from the standings, plus the gap to pole. None when there is no
    classified qualifying result.
    """
    outcome = qualifying_outcome(session)
    if not outcome or not outcome.get('best'):
        return None
    pos, total, best = outcome['position'], outcome['total'], outcome['best']
    txt = f"You classified P{pos}"
    if total:
        txt += f" of {total}"
    txt += f" on a {format_lap_time(best)}"
    pole = outcome.get('pole')
    if pole and pole.get('gap') is not None:
        txt += f", {pole['gap']:.3f}s off pole"
    txt += "."
    # If the lap wasn't clean, say why it isn't a benchmark — but the time
    # still counts as the session's result.
    rewinds = sum(1 for e in session.get('events') or []
                  if e.get('type') == 'rewind')
    invalid = any(not lap.get('valid', True) for lap in session.get('laps') or [])
    if rewinds or invalid:
        reason = ("a flashback" if rewinds and not invalid
                  else "track limits" if invalid and not rewinds
                  else "a flashback and track limits")
        txt += (f" The lap involved {reason}, so it isn't a clean benchmark, "
                "but it's the time that set your grid slot.")
    return txt


def _quali_position_note(session, facts, prior_best):
    """A low grid slot with a lap close to the PB is the field being
    fast, not a poor lap — say so. None when that story doesn't hold."""
    fastest = facts.get('fastest')
    if fastest is None or not prior_best:
        return None
    delta = fastest - prior_best
    if delta > 0.3:
        return None
    outcome = qualifying_outcome(session)
    if not outcome:
        return None
    pos, total = outcome.get('position'), outcome.get('total')
    if not pos or not total or total < 4 or pos <= total / 2:
        return None
    lap_txt = ("a new personal best" if delta < 0 else
               "level with your personal best" if delta < 0.005 else
               f"within {delta:.3f}s of your personal best here")
    return (f"Your best lap was {lap_txt}, suggesting you extracted close "
            f"to your current pace — P{pos} of {total} reflects the "
            "field's competitiveness more than an unusually poor lap.")


# Which of the ad-hoc note categories (tagged on _add() below) are relevant
# to each driver-chosen focus (sessionlog.focus ids) — those notes float to
# the top, right after the focus verdict itself.
#
# 'consistency' tags the gap-to-theoretical notes that explicitly advise
# repeatability over outright speed ("focus on consistency rather than
# outright speed") — the notes a driver chasing consistency wants first.
# They are still pace findings, so 'faster' claims them too: a driver
# chasing time needs to know the pace is already in their sectors.
_FOCUS_NOTE_CATEGORIES = {
    'clean':       {'incidents'},
    'faster':      {'pace', 'consistency'},
    'consistency': {'consistency'},
}


def race_engineer_notes(session, facts=None, prior_best=None, track_map=None,
                        focus_id=None, focus_verdict=None,
                        prior_track_limit_hotspot=None):
    """Driver-facing, session-specific Race Engineer Notes (list of strings).

    A thin wrapper over race_engineer_notes_detailed() that discards the
    per-note location metadata — the form used by the AI share text and any
    consumer that only wants the sentences. See that function for the
    parameters.
    """
    return [n['text'] for n in
            race_engineer_notes_detailed(session, facts, prior_best, track_map,
                                         focus_id, focus_verdict,
                                         prior_track_limit_hotspot)]


def race_engineer_notes_detailed(session, facts=None, prior_best=None,
                                 track_map=None, focus_id=None,
                                 focus_verdict=None,
                                 prior_track_limit_hotspot=None):
    """Driver-facing, session-specific Race Engineer Notes, with locations.

    Returns a list of
    ``{'text': str, 'locations': [{'label', 'distance', 'kind', 'rewound'}]}``.
    ``locations`` is non-empty only for the contact-incident and track-limits
    notes when a ``track_map`` resolved them to labelled sections — a renderer
    can crop a mini-map of each. ``kind`` is the marker's severity fill —
    ``'track_limit'`` (warning), ``'contact'``, or ``'major'`` (a big collision
    per the stewards' penalty) — and ``rewound`` is a separate flag so a
    renderer can show a contact *and* that it was flashed back on one marker
    (e.g. a blue rim). Mapping these to colours is the renderer's job — this
    stays toolkit-free. Every other note carries ``locations: []``.
    Evidence only — state what the data shows, don't infer why laps went
    invalid (the driver's reflection section covers intent).

    prior_best — the best clean lap across earlier sessions at the same
    game / car class / track / SESSION TYPE (session_db.prior_best()):
    the prior best race lap for races, the prior PB for qualifying.
    Optional; the race pace summary and the qualifying position note
    need it.

    track_map — the parsed track JSON for this game/track (trackmap.find_map()),
    or None. When given, contact incidents and track-limits warnings are
    placed against the map's labelled `sections` ('at Turn 3, before the
    apex') and carry `locations`; without one, notes read exactly as they
    did before this existed and `locations` is always empty.

    focus_id / focus_verdict — the driver's chosen pre-session focus
    (sessionlog.focus id) and its already-computed verdict
    (focus.evaluate()'s ``{met, headline, detail, title}``; the caller
    computes it, this function never imports sessionlog.focus). When given,
    the verdict is woven in as the FIRST note (it's already comparison-aware
    once the caller supplies prior_best/prior_std/prior_clean_frac to
    focus.evaluate()), and notes matching the focus's category are promoted
    above unrelated ones — everything else keeps its existing order.

    prior_track_limit_hotspot — {'label', 'count'} for the corner that
    dominated the PREVIOUS session's track-limit warnings (see
    core.pre_session / sessionlog.goals), or None. When given, adds a note
    comparing this session's count at that same corner against it.
    """
    if facts is None:
        facts = pace_facts(session)
    laps     = session.get('laps', [])
    total    = len(laps)
    inv_laps = [lap for lap in laps if not lap.get('valid', True)]

    coach = []

    def _add(text, locations=None, category=None):
        coach.append({'text': text, 'locations': locations or [],
                      'category': category})

    def _finish():
        return [{'text': n['text'], 'locations': n['locations']} for n in coach]

    stype   = (session.get('session_type') or '').strip().lower()
    is_race = stype in RACE_TYPES

    # Qualifying with fewer than two representative timed laps: state
    # why the usual analysis is missing instead of scoring a lone run
    # (grading returns None for the same reason — keep in agreement).
    n_rep = len(facts.get('rep_times') or [])
    if stype == 'qualifying' and n_rep < 2:
        # Lead with the lap that actually classified you — a one-shot quali
        # (or a lone lap spoiled by a flashback) still put a real time on the
        # grid, and that result is the story. Only then note that the deeper
        # grading needs more laps.
        result_note = _quali_result_note(session)
        if result_note:
            _add(result_note)
        lead = ("Only one representative timed lap was" if n_rep == 1
                else "No further representative timed laps were" if result_note
                else "No representative timed laps were")
        _add(f"{lead} recorded — consistency, repeatability and "
             "execution grading require multiple timed laps and "
             "are therefore not shown.")
        pos_note = _quali_position_note(session, facts, prior_best)
        if pos_note:
            _add(pos_note)
        return _finish()

    # Car contacts — evidence only: collision events don't record fault.
    # Grouped into incidents so a contact retried via flashback is one
    # event, not three (a rewind duplicates the log rows).
    notes_events = session.get('events') or []
    incidents    = contact_incidents(notes_events)
    n_rewinds    = sum(1 for e in notes_events if e.get('type') == 'rewind')
    if incidents:
        sections     = (track_map or {}).get('sections') or []
        track_length = (track_map or {}).get('game_track_length_m')
        severity     = _collision_severity(notes_events)
        bits = []
        locations = []
        seen_labels = set()
        for inc in incidents:
            who = " and ".join(inc['drivers']) or "another car"
            dist = inc.get('distance')
            sec  = (trackmap.locate_section(dist, sections, track_length)
                    if track_map else None)
            loc  = (trackmap.describe_location(dist, sections, track_length)
                    if track_map else None)
            bits.append(f"{who} on lap {inc['lap_num']}"
                        + (f" {loc}" if loc else "")
                        + (" (followed by a flashback)"
                           if inc['rewound'] else ""))
            # Marker fill = severity (a big collision per the stewards' penalty
            # is major, else ordinary contact); `rewound` is a separate flag so
            # the renderer can show both — an orange/red triangle for the
            # contact and a blue rim when it was flashed back.
            kind = 'major' if any(
                (d or '').upper() in severity
                and severity[(d or '').upper()] == 'big'
                for d in inc['drivers']) else 'contact'
            rewound = bool(inc['rewound'])
            # One thumbnail per distinct spot (a retried contact and two hits at
            # the same corner share a crop). A contact in an unlabelled gap
            # still gets a thumbnail, captioned by the corners it sits between.
            label = None
            if track_map and dist is not None:
                if sec is not None:
                    label = trackmap.section_label(sec)
                else:
                    br = trackmap.bracket_corners(dist, sections, track_length)
                    if br:
                        label = trackmap.bracket_label(*br)
            if label and label not in seen_labels:
                seen_labels.add(label)
                locations.append({'label': label, 'distance': dist,
                                  'kind': kind, 'rewound': rewound})
        n = len(incidents)
        _add(f"{_num_word(n).capitalize()} contact event"
             f"{'s' if n != 1 else ''}: {'; '.join(bits)}. "
             "Contact events record involvement, not fault"
             + (" — the penalty details may say more."
                if any(e.get('type') == 'penalty'
                       for e in notes_events) else "."),
             locations, category='incidents')

    track_limit_note, tl_locations = _track_limit_note(notes_events, track_map)
    if track_limit_note:
        _add(track_limit_note, tl_locations, category='incidents')

    hotspot_note, hotspot_locations = _track_limit_hotspot_comparison(
        notes_events, track_map, prior_track_limit_hotspot)
    if hotspot_note:
        _add(hotspot_note, hotspot_locations, category='incidents')

    if is_race:
        # Race-engineer summary — the theoretical lap is nearly
        # irrelevant in race conditions; the reference is the prior
        # best race lap at this combination.
        fastest = facts.get('fastest')
        busy    = len(incidents) >= 2 or n_rewinds >= 2
        if fastest is not None and prior_best:
            delta = fastest - prior_best
            net   = net_positions(session)
            if busy and delta <= 0.3 and net:
                # The full race-engineer read: pace at/near the driver's
                # best race lap AND an incident-heavy session — the
                # incidents, not speed, were the limiter. Evidence only:
                # every clause states recorded data.
                start, finish, gained = net
                pace_txt = (f"running within {delta:.3f}s of your best "
                            "race lap at this combination" if delta >= 0
                            else "setting a new best race lap "
                                 f"({-delta:.3f}s under the previous)")
                move_txt = (f"You recovered from P{start} to P{finish}"
                            if gained > 0 else
                            f"You finished P{finish} from P{start} on "
                            "the grid")
                _add(
                    f"{move_txt} while {pace_txt}. The limiting factor "
                    "was not speed but incidents: "
                    f"{_incident_phrase(len(incidents), n_rewinds)} kept "
                    "the result from matching the underlying execution. "
                    "Prioritise cleaner side-by-side racing over finding "
                    "extra lap time — the pace is already there.",
                    category='pace')
            elif delta < 0:
                _add(f"Fastest race lap {format_lap_time(fastest)} "
                             f"(lap {facts['fastest_num']}) — a new best "
                             "race lap at this combination, "
                             f"{-delta:.3f}s under the previous.",
                             category='pace')
            elif busy:
                _add(f"Your fastest lap was +{delta:.3f}s off your "
                             "best race lap at this combination, but the "
                             "session included "
                             f"{_incident_phrase(len(incidents), n_rewinds)}."
                             " Treat this as a racecraft session rather "
                             "than a pure pace benchmark.",
                             category='pace')
            else:
                _add(f"Fastest race lap {format_lap_time(fastest)} "
                             f"(lap {facts['fastest_num']}), +{delta:.3f}s "
                             "off your best race lap at this combination.",
                             category='pace')
        elif busy:
            _add("A busy race — "
                         f"{_incident_phrase(len(incidents), n_rewinds)} "
                         "shaped the lap times. Treat this as a racecraft "
                         "session rather than a pure pace benchmark.",
                         category='pace')
    else:
        # Gap-to-theoretical note — tiered so the advice adapts to the
        # session. Never shown for races.
        #
        # Order matters. "Pace on an invalidated lap" is checked FIRST: when
        # your clean sectors are already assembled the gap collapses toward
        # zero, and a gap-first chain would answer "nothing to gain" while a
        # faster sector sits on a lap you binned — the more useful, more
        # actionable fact. Then the exactly-assembled case, which must not be
        # described as merely "very close".
        gap = facts['gap']
        if gap is not None:
            if facts['pushed_sectors'] or facts['dirty_faster']:
                n_inv = len(inv_laps)
                note = (f"{_num_word(n_inv).capitalize()} lap{'s were' if n_inv != 1 else ' was'} "
                        "invalidated. " if n_inv else "")
                if facts['dirty_faster'] and facts['pushed_sectors']:
                    note += ("Your fastest overall lap and your fastest individual sectors "
                             "were recorded on laps that were not completed cleanly.")
                elif facts['dirty_faster']:
                    note += "Your fastest overall lap was not completed cleanly."
                else:
                    note += ("Your fastest individual sectors were recorded on laps that "
                             "were not completed cleanly.")
                note += (" This indicates additional pace is available, but it has not yet "
                         "been converted into a valid lap. Focus on completing one clean lap "
                         "at that pace rather than chasing more outright speed.")
                _add(note, category='pace')
            elif gap <= _THEO_ASSEMBLED_S:
                # Your fastest lap holds every best clean sector — theoretical
                # IS your fastest, so there is no assembly left to describe.
                _add("Your fastest lap already strings together your best sector "
                             "times — there is no time left to find by putting a "
                             "cleaner lap together. More pace now has to come from "
                             "the driving itself.",
                             category='pace')
            elif gap <= 0.3:
                _add("Theoretical pace is very close to your best valid lap — "
                             "focus on consistency rather than outright speed.",
                             category='consistency')
            elif gap <= 0.5:
                _add("Theoretical best is within 0.5s of fastest lap — prioritise "
                             "consistency over outright pace.",
                             category='consistency')
            else:
                _add("Gap to theoretical is >0.5s — there is meaningful outright pace still to find.",
                             category='pace')

        pos_note = _quali_position_note(session, facts, prior_best)
        if pos_note:
            _add(pos_note, category='pace')

    if total >= 4 and inv_laps and len(inv_laps) / total > 0.4:
        _add(f"A high proportion of laps were invalidated ({len(inv_laps)} of {total}). "
                     "Reducing invalidations is likely to unlock more lap time than "
                     "attempting to drive faster.",
                     category='incidents')

    # Within-session progression — % clean + longest clean run, the clean-up
    # trend, the pace trend, and which sector is leaking time. Routed through
    # _add so its categories join the focus weighting below. Skipped for races
    # and short sessions (returns []). Not shown for a lone-lap qualifying —
    # that path returns above.
    for note in _progression.progression_notes(session):
        _add(note['text'], note['locations'], category=note.get('category'))

    # Racing-line adherence — where the driven line strayed from the recorded
    # line (F1 hotlap/quali at a mapped track). Already in the detailed shape,
    # with off_line locations for corner thumbnails; a no-op without line data.
    coach.extend(_lines.line_notes_detailed(session, track_map))

    # Assist usage (racing line / TC / ABS / gearbox) — evidence-only, no
    # location (session-wide setting, not a track position).
    coach.extend(_assists.assist_notes(session))

    # Weight toward the driver's chosen focus: notes matching its category
    # float to the top (stable sort — everything else keeps its existing
    # relative order), then the focus verdict itself leads everything (it's
    # already comparison-aware once the caller supplies prior_best/
    # prior_std/prior_clean_frac to focus.evaluate()).
    relevant = _FOCUS_NOTE_CATEGORIES.get(focus_id, set())
    if relevant:
        coach.sort(key=lambda n: n.get('category') not in relevant)
    if focus_verdict:
        verdict_text = (f"{focus_verdict['title']} — {focus_verdict['headline']}. "
                        f"{focus_verdict['detail']}")
        coach.insert(0, {'text': verdict_text, 'locations': []})

    return _finish()
