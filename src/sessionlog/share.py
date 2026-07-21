"""Coaching-ready AI share brief for a session — the canonical home.

``format_for_ai(session)`` turns a parsed (and optionally enriched) session
dict into the plain-text debrief a driver pastes into an AI coach. It is the
single source of truth shared by the Pi dashboard's web companion and the
Pythonista companion (vendored via ``sync_shared.py``); the two apps supply
the app-specific context as keyword arguments so this module stays pure
standard library:

  profile        {'name', 'experience_label'} — the declared driver identity,
                 for the role-framing preamble (or None to omit it).
  track_map      the track map dict (``trackmap.find_map(...)``) so event
                 locations can be named ("at Turn 3"); None/omitted is fine.
  journal_entry  {'icon', 'text'} — the session's journal story, or None.

Every richer section (grade, trend, driver profile, milestones, awards,
standings, events…) is read from the session dict with ``.get`` guards, so a
raw parsed session simply omits the sections it has no data for.

Pure standard library only (no pygame, no Pythonista, no 3.11+ syntax) — it is
part of the shared ``sessionlog`` package.
"""
from collections import Counter

from sessionlog import grading
from sessionlog import trackmap
from sessionlog import circuits
from sessionlog.parser import (format_lap_time, format_sector_time,
                               session_label, classify_laps, tyre_stints,
                               penalty_detail, qualifying_outcome)
from sessionlog.pace import pace_facts, race_engineer_notes
from sessionlog.debrief import debrief_lines


def _row_pos(row):
    try:
        return int((row.get('position') or '').strip())
    except (ValueError, AttributeError):
        return None


def _median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _longest_valid_streak(laps):
    best = cur = 0
    for lap in laps:
        if lap.get('valid', True) and not lap.get('rewinds', 0):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _grid_position(session):
    """The player's starting grid slot from the G rows, or None."""
    driver = (session.get('driver_name') or '').strip().lower()
    if not driver:
        return None
    return next((_row_pos(g) for g in (session.get('grid') or [])
                 if (g.get('name') or '').strip().lower() == driver), None)


def _final_position(session):
    """The player's final classified position and field size.

    Position from the R (standings) rows, falling back to the last lap
    that carried a position; field size from the standings row count.
    (None, None) when unknown.
    """
    driver = (session.get('driver_name') or '').strip().lower()
    standings = session.get('standings') or []
    pos = None
    if driver:
        pos = next((_row_pos(s) for s in standings
                    if (s.get('name') or '').strip().lower() == driver), None)
    if pos is None:
        for lap in reversed(session.get('laps') or []):
            if lap.get('position') is not None:
                pos = lap['position']
                break
    return pos, (len(standings) or None)


def _net_positions(session):
    """Race start → finish for the player → (start, finish, places_gained).

    Returns None unless this is a race with the player's grid slot and a
    finishing position both known.  Start comes from the G (grid) rows,
    finish from _final_position().  places_gained is start − finish
    (positive = up).
    """
    if (session.get('session_type') or '').strip().lower() != 'race':
        return None
    start     = _grid_position(session)
    finish, _ = _final_position(session)
    if start is None or finish is None:
        return None
    return (start, finish, start - finish)


def _is_race(session):
    """Race semantics (incl. sprint races) — matches grading.RACE_TYPES."""
    return ((session.get('session_type') or '').strip().lower()
            in grading.RACE_TYPES)

# Lap-table columns are data-driven (Phase 5).  LAP / TIME / S1 / S2 / S3 are
# always present; POS is added only for sessions that log a per-lap position
# (races).  The tyre chip lives inside the LAP cell and the delta lives under
# the TIME cell, so neither adds a column — the tyre chip only widens LAP.


def _pair_events(events, deploy_type, clear_type):
    """Return list of (deploy_event, clear_event_or_None) pairs."""
    periods, start = [], None
    for ev in events:
        if ev['type'] == deploy_type:
            start = ev
        elif ev['type'] == clear_type and start is not None:
            periods.append((start, ev))
            start = None
    if start is not None:
        periods.append((start, None))
    return periods


def _score_dot(score):
    """Sub-score → coloured dot for the share-text breakdown, so the eye
    lands on the weak metric without reading the summary."""
    if score >= 85:
        return '🟢'
    if score >= 70:
        return '🟡'
    if score >= 50:
        return '🟠'
    return '🔴'


def _award_note(a):
    """One display line for a session_awards() entry."""
    from sessionlog.achievements import badge
    icon = badge(a['id']).get('icon', '🏅')
    if a['kind'] == 'unlocked':
        return f"{icon} New badge — {a['name']}"
    if a['kind'] == 'upgraded':
        return (f"{icon} {a['name']} ×{a['count']} — "
                f"{(a['tier'] or '').title()}")
    return f"{icon} {a['name']} ×{a['count']}"


def _leader_race_time(standings):
    """The winner's total race time (P1's R-row race_time) → float | None."""
    for s in standings:
        if str(s.get('position') or '') == '1':
            try:
                return float(s.get('race_time') or '')
            except (TypeError, ValueError):
                return None
    return None


def format_for_ai(session, *, profile=None, track_map=None, journal_entry=None):
    """Return a coaching-ready text summary of the session."""
    lines = []
    track_map = track_map or {}

    # Role + task framing, so a driver pasting this into a fresh chat with no
    # prompt of their own gets a coaching debrief rather than a raw data dump.
    # Kept short and evidence-first — the detailed how-to-read guidance lives
    # in the AI ANALYSIS GUIDANCE section further down.
    lines.append("You are an expert sim-racing coach giving a post-session "
                 "debrief.")
    lines.append("Analyse the telemetry below and give specific, actionable "
                 "feedback grounded only in this data; if a DRIVER SESSION "
                 "REFLECTION is provided, use it for context. Be concise and "
                 "constructive.")

    # Who is being coached, from the declared Driver Profile (name +
    # self-described experience level) — session-independent context so the
    # coach can address the driver and pitch advice to their level.
    _prof = profile or {}
    _prof_name = (_prof.get('name') or '').strip()
    _prof_exp = (_prof.get('experience_label') or '').strip()
    if _prof_name and _prof_exp:
        lines.append(f"The driver's name is {_prof_name}, and they describe "
                     f"their experience level as {_prof_exp}. Address them by "
                     f"name and pitch your feedback to that level.")
    elif _prof_name:
        lines.append(f"The driver's name is {_prof_name}. Address them by "
                     f"name in your feedback.")
    elif _prof_exp:
        lines.append(f"The driver describes their experience level as "
                     f"{_prof_exp}. Pitch your feedback to that level.")

    lines.append("")

    stype = (session_label(session) or 'Session').replace('_', ' ').upper()
    lines.append(f"SIM RACING SESSION — {stype}")

    game   = session.get('game_name') or session.get('game') or ''
    car    = session.get('car') or session.get('car_class_name') or ''
    cls    = session.get('car_class_name') or ''
    driver = session.get('driver_name') or ''
    track  = (circuits.display_name(session.get('game'), session.get('track')) or session.get('track') or 'Unknown track')
    layout = session.get('layout') or ''
    track_str = f"{track} ({layout})" if layout else track

    parts = []
    if game:   parts.append(f"Game: {game}")
    if car:    parts.append(f"Car: {car}")
    # Show the class only when "Car" is a specific model — otherwise "Car"
    # already IS the class name (F1 games log a class, not a model).
    if cls and cls != car: parts.append(f"Class: {cls}")
    if driver: parts.append(f"Driver: {driver}")
    parts.append(f"Track: {track_str}")
    lines.append("  ".join(parts))

    date = session.get('date')
    if date:
        lines.append(f"Date: {date.strftime('%d %b %Y %H:%M')}")

    # Conditions (Dash v0.2.0+ logs weather/temps; older files have none).
    # The recorded value is the session's final state — context that matters
    # when comparing against sessions run in different conditions.
    weather = (session.get('weather') or '').replace('_', ' ')
    if weather:
        temps = []
        if session.get('air_temp') is not None:
            temps.append(f"air {session['air_temp']}°C")
        if session.get('track_temp') is not None:
            temps.append(f"track {session['track_temp']}°C")
        suffix = f" ({', '.join(temps)})" if temps else ""
        lines.append(f"Conditions: {weather}{suffix}")

    # Driver debrief (Dash v0.6.0+ D rows) — the driver's own account of
    # the session. Subjective context the telemetry can't see: weigh the
    # coaching accordingly (e.g. "driver was tired" reframes messy laps).
    from sessionlog.debrief import debrief_lines
    debrief = debrief_lines(session)
    if debrief:
        lines.append("")
        lines.append("DRIVER DEBRIEF")
        lines.extend(debrief)

    # Journal — the session's story (sessionlog.journal); the
    # human-readable summary of everything below.
    entry = journal_entry or {'icon': '', 'text': ''}
    if entry["text"]:
        lines.append("")
        lines.append("JOURNAL")
        lines.append(f"{entry['icon']} {entry['text']}".strip())

    # ── session summary ──────────────────────────────────────────────────────
    laps        = session.get('laps', [])
    total       = len(laps)
    inv_laps    = [lap for lap in laps if not lap.get('valid', True)]
    rew_laps    = [lap for lap in laps if lap.get('rewinds', 0)]
    # clean = game-valid AND no rewinds used
    clean_laps  = [lap for lap in laps if lap.get('valid', True) and not lap.get('rewinds', 0)]
    n_clean     = len(clean_laps)

    lines.append("")
    lines.append("SESSION SUMMARY")

    pct = f"{100 * n_clean / total:.1f}%" if total else "–"
    lines.append(f"Valid laps: {n_clean}/{total} ({pct})")

    streak = _longest_valid_streak(laps)
    if streak:
        lines.append(f"Longest valid streak: {streak} lap{'s' if streak != 1 else ''}")

    places = _net_positions(session)
    if places is not None:
        start, finish, gain = places
        if gain > 0:
            gain_str = f"gained {gain} place{'s' if gain != 1 else ''}"
        elif gain < 0:
            gain_str = f"lost {-gain} place{'s' if gain != -1 else ''}"
        else:
            gain_str = "held position"
        lines.append(f"Positions: started P{start}, finished P{finish} ({gain_str})")
    elif (session.get('session_type') or '').strip().lower() != 'qualifying':
        # Practice timesheet / gridless race — qualifying has its own
        # QUALIFYING OUTCOME section.
        _fpos, _ftotal = _final_position(session)
        if _fpos is not None:
            lines.append(f"Final position: P{_fpos}"
                         + (f" of {_ftotal}" if _ftotal else ""))

    # Position by lap — the race's story in one line (mirrors the graph).
    pos_seq = [(lap['num'], lap['position']) for lap in laps
               if lap.get('position') is not None
               and lap.get('num') is not None]
    if _is_race(session) and len(pos_seq) >= 2:
        gp  = _grid_position(session)
        seq = " ".join(f"P{p}" for _, p in pos_seq)
        if gp is not None:
            seq = f"P{gp} (grid) → {seq}"
        lines.append(f"Position by lap: {seq}")
        low = max(p for _, p in pos_seq)
        ends = (gp if gp is not None else pos_seq[0][1], pos_seq[-1][1])
        if low > max(ends):
            low_lap = next(n for n, p in pos_seq if p == low)
            lines.append(f"Lowest: P{low} (lap {low_lap})")

    if inv_laps:
        nums = ", ".join(str(lap['num']) for lap in inv_laps)
        lines.append(f"Invalid laps: {nums}")

    if rew_laps:
        parts = [f"{lap['num']} (×{lap['rewinds']})" for lap in rew_laps]
        lines.append(f"Rewound laps: {', '.join(parts)}")

    res_laps = [lap for lap in laps if lap.get('restarts', 0)]
    if res_laps:
        parts = [f"{lap['num']} (×{lap['restarts']})" for lap in res_laps]
        lines.append(f"Restarted laps (abandoned attempts before completing): {', '.join(parts)}")

    # ── lap table ────────────────────────────────────────────────────────────
    has_s        = any(lap.get('s1') is not None for lap in laps)
    has_pos      = any(lap.get('position') is not None for lap in laps)
    has_tyre     = any(lap.get('tyre_compound') for lap in laps)
    has_rewinds  = any(lap.get('rewinds', 0) for lap in laps)
    has_restarts = any(lap.get('restarts', 0) for lap in laps)

    lap_classes = classify_laps(session)   # out/in/sc/start/cooldown per lap
    _CLASS_NOTE = {'in': 'in', 'out': 'out', 'in/out': 'in/out',
                   'sc': 'SC', 'start': 'start', 'cooldown': 'cool'}

    lines.append("")
    hdr = f"{'LAP':>3}  {'V':<1}"
    if has_rewinds:  hdr += f"  {'R':>2}"
    if has_restarts: hdr += f"  {'RS':>2}"
    hdr += f"  {'TIME':<10}"
    if has_s:    hdr += f"  {'S1':>7}  {'S2':>7}  {'S3':>7}"
    if has_tyre: hdr += f"  {'TYRE':<8}"
    if has_pos:  hdr += "  POS"
    if lap_classes: hdr += "  NOTE"
    lines.append(hdr)
    lines.append("-" * len(hdr))

    for lap in laps:
        v   = '✓' if lap.get('valid', True) else '✗'
        row = f"{lap['num']:>3}  {v:<1}"
        if has_rewinds:
            rw = lap.get('rewinds', 0)
            row += f"  {str(rw) if rw else '-':>2}"
        if has_restarts:
            rs = lap.get('restarts', 0)
            row += f"  {str(rs) if rs else '-':>2}"
        row += f"  {format_lap_time(lap['time']):<10}"
        if has_s:
            row += (f"  {format_sector_time(lap.get('s1')):>7}"
                    f"  {format_sector_time(lap.get('s2')):>7}"
                    f"  {format_sector_time(lap.get('s3')):>7}")
        if has_tyre:
            row += f"  {(lap.get('tyre_compound') or '-')[:8]:<8}"
        if has_pos:
            pos = lap.get('position')
            row += f"  {'P'+str(pos) if pos else '-':>3}"
        if lap_classes:
            row += f"  {_CLASS_NOTE.get(lap_classes.get(lap['num']), '')}"
        lines.append(row.rstrip())

    # ── pace analysis ────────────────────────────────────────────────────────
    lines.append("")
    lines.append("PACE ANALYSIS")

    facts       = pace_facts(session)
    valid_times = facts['valid_times']
    s1s, s2s, s3s = facts['s1s'], facts['s2s'], facts['s3s']

    if valid_times:
        fastest = facts['fastest']
        lines.append(f"Fastest valid:    {format_lap_time(fastest)}  (Lap {facts['fastest_num']})")
        if facts['dirty_faster']:
            t_all, n_all = facts['dirty_best']
            lines.append(f"Fastest overall:  {format_lap_time(t_all)}  (Lap {n_all}, not clean — excluded above)")
        # Aggregates over representative push laps only, so out/in/SC/
        # cooldown laps don't drag the median — matching the guidance.
        rep_times = facts['rep_times']
        base = rep_times if len(rep_times) >= 2 else valid_times
        note = ' (push laps only)' if base is rep_times \
               and len(rep_times) != len(valid_times) else ''
        if len(base) >= 2:
            lines.append(f"Median valid:     {format_lap_time(_median(base))}{note}")
            avg = sum(base) / len(base)
            lines.append(f"Average valid:    {format_lap_time(avg)}{note}")
        slowest = max(base)
        if slowest != fastest:
            lines.append(f"Valid lap range:  {format_lap_time(fastest)} – "
                         f"{format_lap_time(slowest)}{note}")

    # With fewer than two representative laps the theoretical best is
    # just the one push lap restated — hide it rather than mislead.
    if facts['theo'] is not None and len(facts['rep_times']) >= 2:
        lines.append(f"Theoretical best: {format_lap_time(facts['theo'])}")
        if facts['gap'] is not None:
            lines.append(f"Gap to theoretical: +{facts['gap']:.3f}s")
        lines.append(f"Best S1: {format_sector_time(min(s1s))}  "
                     f"Best S2: {format_sector_time(min(s2s))}  "
                     f"Best S3: {format_sector_time(min(s3s))}")
        if facts['pushed_sectors']:
            parts = [f"{k.upper()} {format_sector_time(v)} (lap {n})"
                     for k, v, n in facts['pushed_sectors']]
            lines.append(f"Faster sectors on non-clean laps: {', '.join(parts)}")

    summary = session.get('summary') or {}
    std = summary.get('std_dev')
    if std is not None:
        lines.append(f"Consistency (std dev): {std:.3f}s")

    # ── tyre stints — pace only compares within a compound ─────────────────
    stints = tyre_stints(session)
    if len(stints) >= 2:
        lines.append("")
        lines.append("TYRE STINTS")
        for st in stints:
            st_laps = st['laps']
            nums    = [lp['num'] for lp in st_laps if lp.get('num') is not None]
            rep     = [lp['time'] for lp in st_laps
                       if lp.get('time') is not None
                       and lp.get('valid', True) and not lp.get('rewinds', 0)
                       and lp.get('num') not in lap_classes]
            span = (f"laps {min(nums)}–{max(nums)}" if len(nums) > 1
                    else f"lap {nums[0]}" if nums else "—")
            line = (f"{(st['compound'] or 'Unknown'):<8} {span} "
                    f"({len(st_laps)} lap{'s' if len(st_laps) != 1 else ''})")
            if rep:
                line += f": best {format_lap_time(min(rep))}"
                if len(rep) >= 2:
                    line += f", avg push {format_lap_time(sum(rep) / len(rep))}"
            lines.append(line)

    # ── racecraft — overtakes and defending, separate from execution ───────
    if _is_race(session):
        rc_events = session.get('events') or []
        overtakes = [e for e in rc_events if e['type'] == 'overtake']
        overtaken = [e for e in rc_events if e['type'] == 'overtaken']
        if overtakes or overtaken:
            # v0.1.135+ files name names. Summarised, not listed raw —
            # "14 overtakes / 14 overtaken" with a name per event says
            # less than who it was against and where it happened.
            lines.append("")
            lines.append("RACECRAFT")
            lines.append(f"Overtakes made: {len(overtakes)} · "
                         f"Times overtaken: {len(overtaken)}")
            places = _net_positions(session)
            if places is not None:
                start, finish, gain = places
                lines.append(f"Net result: started P{start}, "
                             f"finished P{finish} ({gain:+d})")
            made = Counter((e.get('detail') or 'a car') for e in overtakes)
            if made:
                top = ", ".join(f"{n} ×{c}" for n, c in made.most_common(3))
                lines.append(f"Most overtaken: {top}")
            by = Counter((e.get('detail') or 'a car') for e in overtaken)
            if by:
                top = ", ".join(f"{n} ×{c}" for n, c in by.most_common(3))
                lines.append(f"Most overtaken by: {top}")
            battles = Counter((e.get('detail') or 'a car')
                              for e in overtakes + overtaken)
            if battles:
                name, swaps = battles.most_common(1)[0]
                if swaps >= 2:
                    lines.append(f"Most fought driver: {name} "
                                 f"({swaps} position changes)")
            busiest = Counter(e['lap_num'] for e in overtakes + overtaken)
            if busiest:
                lap_n, n_ch = busiest.most_common(1)[0]
                if n_ch >= 2:
                    lines.append(f"Most active lap: lap {lap_n} "
                                 f"({n_ch} position changes)")
        else:
            # Older files: derive from the per-lap position column.
            pitish  = {n for n, c in lap_classes.items()
                       if c in ('in', 'out', 'in/out')}
            gains, losses = [], []   # (lap_num, places)
            prev = None
            for lap in laps:
                pos, num = lap.get('position'), lap.get('num')
                if pos is None:
                    prev = None
                    continue
                # Lap 1 (start chaos) and pit laps are strategy, not racecraft.
                if prev is not None and pos != prev and num != 1 \
                        and num not in pitish:
                    (gains if pos < prev else losses).append(
                        (num, abs(prev - pos)))
                prev = pos
            if gains or losses:
                lines.append("")
                lines.append("RACECRAFT")
                if gains:
                    total = sum(p for _, p in gains)
                    at = ", ".join(f"lap {n} (+{p})" for n, p in gains)
                    lines.append(f"On-track places gained: {total} — {at}")
                if losses:
                    total = sum(p for _, p in losses)
                    at = ", ".join(f"lap {n} (−{p})" for n, p in losses)
                    lines.append(f"On-track places lost:   {total} — {at}")
                lines.append("(Lap 1 and pit-lap position changes excluded — "
                             "strategy, not racecraft.)")

    # ── session grade — execution quality relative to the driver's own
    #    ability (grading.py); never outright pace or finishing position ────
    g = session.get('grade')
    if g:
        is_race_g = _is_race(session)
        lines.append("")
        lines.append("SESSION GRADE")
        lines.append("Scored against this driver's own data — never outright "
                     "pace, raw lap time or finishing position.")
        ex = g.get('execution')
        cl = g.get('cleanliness')
        cl_label = (cl or {}).get('label', 'Cleanliness')
        # Column-align the grade labels; 'Race Discipline' is the widest.
        pad = max(len('Execution'), len(cl_label), len('Overall'),
                  len('Race pace' if g.get('pace_kind') == 'race'
                      else 'Pace rating')) + 2
        if ex:
            pillars = ("race pace, consistency, mistakes" if is_race_g
                       else "pace execution, consistency, PB comparison, "
                            "mistakes")
            lines.append(f"{'Execution:':<{pad}}{ex['letter']:<2} "
                         f"({ex['score']:.0f}/100) — {pillars}")
        if cl:
            lines.append(f"{cl_label + ':':<{pad}}{cl['letter']:<2} "
                         f"({cl['score']:.0f}/100) — {cl['detail']}")
        tail = ""
        if g.get('capped'):
            tail = (" — execution capped by the incident rate" if is_race_g
                    else " — execution capped by the invalid-lap rate")
        lines.append(f"{'Overall:':<{pad}}{g['letter']:<2} "
                     f"({g['score']:.0f}/100){tail}")
        if g.get('pace_rating') is not None:
            if g.get('pace_kind') == 'race':
                lines.append(f"{'Race pace:':<{pad}}{g['pace_rating']}/100 "
                             "— vs your best prior race lap at this "
                             "combination (the theoretical lap is nearly "
                             "irrelevant in race conditions)")
            else:
                # A new PB deliberately doesn't move this number (the
                # milestone carries the achievement) — say so, or a PB
                # session reading "88" feels like a verdict on the PB.
                pb_ref = session.get('prior_best')
                new_pb = (pb_ref is not None and facts['fastest'] is not None
                          and facts['fastest'] < pb_ref)
                note = (" (deliberately unmoved by the new PB — it measures "
                        "how much of this session's sector pace was "
                        "converted; the milestone carries the achievement)"
                        if new_pb else "")
                lines.append(f"{'Pace rating:':<{pad}}{g['pace_rating']}/100 "
                             "— how close the fastest clean lap came to "
                             f"today's theoretical best{note}")
        if g['components']:
            lines.append("Execution breakdown:")
            for c in g['components']:
                lines.append(f"  {_score_dot(c['score'])} {c['label']:<15} "
                             f"{c['score']:>5.1f}/100 "
                             f"({c['weight']:.0%} of execution) — {c['detail']}")
            for u in g.get('unscored') or []:
                lines.append(f"  ⚪ {u['label']:<15} not scored — {u['reason']}")
        lines.append(f"Summary: {g['explanation']}")
        if g.get('focus'):
            lines.append(f"Focus for next session: {g['focus']}")

    # ── career badges this session earned ────────────────────────────────
    awards = session.get('awards') or []
    if awards:
        lines.append("")
        lines.append("ACHIEVEMENTS")
        for a in awards:
            lines.append(_award_note(a))

    # ── milestones — personal firsts/records this session set ───────────────
    ms = session.get('milestones') or []
    if ms:
        lines.append("")
        lines.append("MILESTONES")
        for m in ms:
            lines.append(f"{m['icon']} {m['title']} — {m['detail']}")

    # ── trend — direction of travel over recent comparable sessions ─────────
    t = session.get('trend')
    if t:
        lines.append("")
        lines.append("TREND")
        n = len(t['gaps'])
        lines.append(f"{t['arrow']} {t['direction'].capitalize()} — last "
                     f"{n} comparable session{'s' if n != 1 else ''} "
                     "(same game, car class, track and session type)")
        gaps = "  ".join(f"+{gap:.3f}s" for _, gap in t['gaps'])
        lines.append(f"Gap to personal best, oldest → newest: {gaps}")

    # ── driver profile — repeatable performance at this combo ───────────────
    p = session.get('profile')
    if p:
        lines.append("")
        scope = ' · '.join(s for s in (
            session.get('track') or 'this track',
            session.get('car') or session.get('car_class_name') or '',
            (session.get('session_type') or '').lower(),
        ) if s)
        lines.append(f"DRIVER PROFILE — {scope}")
        lines.append(f"Personal best:        {format_lap_time(p['pb'])}")
        if p['sessions'] >= 2:
            lines.append(f"Average best session: {format_lap_time(p['avg_best'])}")
        lines.append(f"Sessions:             {p['sessions']}")
        if p.get('stars'):
            std_note = (f" (avg clean-lap std dev {p['avg_std']:.2f}s)"
                        if p.get('avg_std') is not None else "")
            lines.append(f"Consistency:          "
                         f"{grading.stars_text(p['stars'])}{std_note}")
        if p.get('typical'):
            lo, hi = p['typical']
            lines.append(f"Typical clean pace:   {format_lap_time(lo)} – "
                         f"{format_lap_time(hi)}")
        b = p.get('baseline')
        if b:
            change = ('stable' if b['direction'] == 'stable' else
                      f"{abs(b['shift']):.2f}s "
                      f"{'faster' if b['shift'] < 0 else 'slower'}")
            lines.append(f"Typical pace trend:   {b['arrow']} "
                         f"{format_lap_time(b['from'])} → "
                         f"{format_lap_time(b['to'])} ({change}, average "
                         "session best over the older vs newer half of "
                         "recent sessions)")
        if p.get('on_pace_pct') is not None:
            lines.append(f"Fast-lap repeatability: {p['on_pace_pct']:.0f}% of "
                         "clean laps within 1% of their session's best")
        conf = p.get('confidence')
        if conf:
            lines.append(f"Profile confidence:   "
                         f"{grading.stars_text(conf['stars'])} "
                         f"({conf['sessions']} session"
                         f"{'s' if conf['sessions'] != 1 else ''}, "
                         f"{conf['clean_laps']} clean laps)")

    # ── lap-time progress — best lap per session over time at this combo.
    #    Practice/quali/hotlap only (a race's story is position, not one lap);
    #    the series stands in for the on-screen chart, which can't be shared as
    #    an image. ────────────────────────────────────────────────────────────
    prog = session.get('progress') or []
    if not _is_race(session) and len(prog) >= 2:
        lines.append("")
        lines.append("LAP-TIME PROGRESS")
        lines.append("Best lap per session, oldest → newest (same game, car "
                     "class, track and session type):")
        shown = prog[-12:]
        if len(prog) > len(shown):
            lines.append(f"(showing the last {len(shown)} of {len(prog)} "
                         "sessions)")
        for pt in shown:
            when = pt.get('date')
            when_str = when.strftime('%d %b %Y') if when else '—'
            mark = '  ← this session' if pt.get('current') else ''
            spread = (f"  (clean-lap std dev {pt['hi'] - pt['best']:.2f}s)"
                      if pt.get('hi') is not None else "")
            lines.append(f"  {when_str}  {format_lap_time(pt['best'])}"
                         f"{spread}{mark}")
        first_b, last_b = shown[0]['best'], shown[-1]['best']
        delta = last_b - first_b
        if abs(delta) < 0.005:
            move = "unchanged"
        else:
            move = f"{abs(delta):.2f}s {'faster' if delta < 0 else 'slower'}"
        # F1 25 hotlaps are always clear; only caveat weather where it can vary.
        stype_l = (session.get('session_type') or '').strip().lower()
        weather_varies = not (session.get('game') == 'f1_25'
                              and stype_l == 'hotlap')
        caveat = (" Note: weather/track conditions vary between sessions and "
                  "are not accounted for here." if weather_varies else "")
        lines.append(f"Change across these {len(shown)} sessions: "
                     f"{format_lap_time(first_b)} → {format_lap_time(last_b)} "
                     f"({move}).{caveat}")

    # ── overall best comparison — record across all saved sessions with the
    #    same game / car class / track / session type (from session_db) ──────
    ob   = session.get('overall_best') or {}
    ob_t = ob.get('best_lap_time')
    if ob_t is not None:
        lines.append("")
        lines.append("OVERALL BEST COMPARISON")
        lines.append("Scope: all saved sessions with the same game, car class, "
                     "track and session type.")
        when = ob.get('date')
        when_str = f"  set {when.strftime('%d %b %Y %H:%M')}" if when else ""
        lines.append(f"Overall best lap: {format_lap_time(ob_t)}{when_str}")
        if any(ob.get(k) is not None for k in ('best_s1', 'best_s2', 'best_s3')):
            lines.append(f"Overall best sectors: "
                         f"S1 {format_sector_time(ob.get('best_s1'))}  "
                         f"S2 {format_sector_time(ob.get('best_s2'))}  "
                         f"S3 {format_sector_time(ob.get('best_s3'))} "
                         "(the sectors of the overall best lap itself, "
                         "not best individual sectors)")
        fastest = facts['fastest']
        if (ob.get('filename') == session.get('filename')
                or (fastest is not None and fastest <= ob_t)):
            lines.append("This session's fastest valid lap is the overall best.")
        elif fastest is not None:
            lines.append(f"Gap to overall best: +{fastest - ob_t:.3f}s "
                         f"(session fastest {format_lap_time(fastest)})")

    # ── events ───────────────────────────────────────────────────────────────
    events     = session.get('events') or []
    sc_periods  = _pair_events(events, 'sc_deploy',  'sc_clear')
    vsc_periods = _pair_events(events, 'vsc_deploy', 'vsc_clear')

    pit_laps = set()  # collected outside the block so Race Engineer Notes can reference them

    if events:
        lines.append("")
        lines.append("EVENTS")

        shown_sc  = set()
        shown_vsc = set()

        def _dist(ev):
            d = ev.get('distance')
            if d is None:
                return ""
            if track_map:
                loc = trackmap.describe_location(
                    d, track_map.get('sections') or [],
                    track_map.get('game_track_length_m'))
                if loc:
                    return f", {loc}"
            if d < 0:
                return f", {-d:.0f} m before the start line"
            return f", {d:.0f} m from start line"

        def _same_moment(ev, other_type):
            return any(e['type'] == other_type and e['lap_num'] == ev['lap_num']
                       and abs(e['lap_time'] - ev['lap_time']) < 0.5
                       for e in events)

        for i, ev in enumerate(events):
            lap   = ev['lap_num']
            t     = ev['lap_time']
            etype = ev['type']

            if etype == 'rewind':
                lines.append(f"  Lap {lap}  rewind at {t:.1f}s into lap{_dist(ev)}")

            elif etype == 'restart':
                lines.append(f"  Lap {lap}  restart — attempt abandoned {t:.1f}s into lap, "
                             f"car reset to start line")

            elif etype == 'invalid':
                # An invalidation PENALTY at the same moment carries the
                # infringement (e.g. running wide) — one line, not two.
                if _same_moment(ev, 'penalty'):
                    continue
                cause = " (track limits)" if _same_moment(ev, 'track_limit_warning') else ""
                lines.append(f"  Lap {lap}  lap invalidated at {t:.1f}s into lap"
                             f"{_dist(ev)}{cause}")

            elif etype == 'track_limit_warning':
                # Skip warnings already reported as the cause of an invalid.
                if not _same_moment(ev, 'invalid'):
                    lines.append(f"  Lap {lap}  track limits warning at {t:.1f}s into lap{_dist(ev)}")

            elif etype == 'collision':
                who = f" with {ev['detail']}" if ev.get('detail') else ""
                lines.append(f"  Lap {lap}  contact{who} at {t:.1f}s into "
                             f"lap{_dist(ev)}")

            elif etype == 'penalty':
                p    = penalty_detail(ev.get('detail'))
                what = p['penalty'] or 'penalty'
                if 'invalidated' in what:
                    # The game's raw enum ("this and next lap invalidated
                    # no reason") reads like debug output — rebuild it
                    # from the infringement, which names the real cause.
                    why = p['infringement'] or ''
                    if why.startswith('lap invalidated '):
                        why = why[len('lap invalidated '):]
                    if why and ('wide' in why or 'corner cutting' in why):
                        why += ' (track limits)'
                    what  = 'lap invalidated'
                    what += f" — {why}" if why else ""
                    if 'next lap' in (p['penalty'] or ''):
                        what += ", carrying into the next lap"
                    lines.append(f"  Lap {lap}  {what} at {t:.1f}s into lap"
                                 f"{_dist(ev)}")
                    continue
                why  = f" — {p['infringement']}" if p['infringement'] else ""
                who  = f" (with {p['driver']})" if p['driver'] else ""
                lines.append(f"  Lap {lap}  {what}{why}{who} at {t:.1f}s "
                             f"into lap{_dist(ev)}")

            elif etype == 'pit_in':
                # Events are chronological, so the next pit_out closes this
                # visit — even when the car exits on a later lap.
                pit_out = next((e for e in events[i + 1:]
                                if e['type'] == 'pit_out'), None)
                if lap not in pit_laps:
                    if pit_out:
                        # Stop length needs the wall clock (`t`, v0.1.133+):
                        # the lap clock resets across the garage teleport,
                        # so lap_time deltas can go negative.
                        stop = ''
                        if ev.get('t') is not None and pit_out.get('t') is not None:
                            stop = f" (stop: {pit_out['t'] - ev['t']:.1f}s)"
                        lines.append(f"  Lap {lap}  pit stop — in {t:.1f}s, "
                                     f"out {pit_out['lap_time']:.1f}s{stop}")
                        pit_laps.add(pit_out['lap_num'])
                    else:
                        lines.append(f"  Lap {lap}  pit in at {t:.1f}s")
                    pit_laps.add(lap)

            elif etype == 'sc_deploy' and lap not in shown_sc:
                clear = next((p[1] for p in sc_periods if p[0]['lap_num'] == lap), None)
                if clear:
                    lines.append(f"  Laps {lap}–{clear['lap_num']}  Safety Car")
                else:
                    lines.append(f"  Lap {lap}+  Safety Car deployed")
                shown_sc.add(lap)

            elif etype == 'vsc_deploy' and lap not in shown_vsc:
                clear = next((p[1] for p in vsc_periods if p[0]['lap_num'] == lap), None)
                if clear:
                    if clear['lap_num'] == lap:
                        lines.append(f"  Lap {lap}  Virtual Safety Car")
                    else:
                        lines.append(f"  Laps {lap}–{clear['lap_num']}  Virtual Safety Car")
                else:
                    lines.append(f"  Lap {lap}+  Virtual Safety Car deployed")
                shown_vsc.add(lap)

    # ── qualifying outcome — the result is the story in qualifying ─────────
    outcome = qualifying_outcome(session)
    if outcome:
        lines.append("")
        lines.append("QUALIFYING OUTCOME")
        lines.append(f"Qualified: P{outcome['position']} of {outcome['total']}")
        if outcome['position'] == 1:
            lines.append("Pole position.")
        if outcome['pole']:
            lines.append(f"Gap to pole ({outcome['pole']['name']}): "
                         f"{outcome['pole']['gap']:+.3f}s")
        if outcome['ahead'] and outcome['ahead'] != outcome['pole']:
            lines.append(f"Gap to P{outcome['position'] - 1} "
                         f"({outcome['ahead']['name']}): "
                         f"{outcome['ahead']['gap']:+.3f}s")
        if outcome['behind']:
            lines.append(f"Margin over P{outcome['position'] + 1} "
                         f"({outcome['behind']['name']}): "
                         f"{outcome['behind']['gap']:+.3f}s")

    # ── standings ────────────────────────────────────────────────────────────
    standings = session.get('standings') or []
    if standings:
        share_race = _is_race(session)
        stype_share = (session.get('session_type') or '').strip().lower()
        title = ('RACE RESULTS' if share_race else
                 'QUALIFYING RESULTS' if stype_share == 'qualifying' else
                 'SESSION RESULTS')
        # Gap column baseline for timesheets: the fastest best lap.
        st_bests = []
        for s in standings:
            try:
                st_bests.append(float(s.get('best_lap') or ''))
            except (TypeError, ValueError):
                pass
        fastest_best = min(st_bests) if st_bests else None
        # Gap column baseline for races: the winner's total race time.
        leader_time = _leader_race_time(standings) if share_race else None
        lines.append("")
        lines.append(title)
        lines.append("-" * 48)
        for s in standings:
            pos  = s.get('position') or ''
            name = s.get('name') or ''
            best = None
            try:
                best = float(s.get('best_lap') or '')
            except (TypeError, ValueError):
                pass
            best_str = format_lap_time(best) if best is not None else '--:--.---'
            if share_race:
                # Leader shows the total race time; the rest their gap
                # to the leader's total.
                try:
                    rt = float(s.get('race_time') or '')
                except (TypeError, ValueError):
                    rt = None
                if rt is None:
                    time_str = '--'
                elif str(pos) == '1':
                    time_str = format_lap_time(rt)
                elif leader_time is not None:
                    time_str = f'+{rt - leader_time:.3f}'
                else:
                    time_str = '--'
            else:
                if best is None or fastest_best is None:
                    time_str = '--'
                elif best <= fastest_best + 1e-9:
                    time_str = '—'
                else:
                    time_str = f'+{best - fastest_best:.3f}'
            lines.append(f"P{str(pos):<3}  {name:<20}  {best_str:<10}  "
                         f"{time_str}")

    # ── AI analysis guidance — instructions for the analysing model, not
    #    driver feedback (kept separate so it can be hidden in a driver-only
    #    view of the report) ────────────────────────────────────────────────
    lines.append("")
    lines.append("AI ANALYSIS GUIDANCE")
    lines.append("• Ignore invalid laps when assessing consistency.")
    lines.append("• Use invalid laps only to identify recurring driving mistakes.")
    lines.append("• Do not include pit laps or incomplete laps in pace analysis.")
    if session.get('grade'):
        g_ai = session['grade']
        pace_expl = ("the race pace rating, which compares the fastest "
                     "clean lap to this driver's prior best race lap at "
                     "this combination"
                     if g_ai.get('pace_kind') == 'race' else
                     "the pace rating, which says how much of today's "
                     "theoretical pace was converted")
        lines.append("• The SESSION GRADE scores execution quality against this "
                     "driver's own data only — it is deliberately independent of "
                     "outright pace and finishing position. Do not read a high "
                     f"grade as fast or a low grade as slow; pair it with {pace_expl}.")
        pb_ai = session.get('prior_best')
        if (g_ai.get('pace_kind') != 'race' and pb_ai is not None
                and facts['fastest'] is not None
                and facts['fastest'] < pb_ai):
            lines.append("• This session set a new personal best, and the "
                         "pace rating is deliberately unmoved by that: it "
                         "measures how much of THIS session's sector pace "
                         "was converted into one lap, so a PB with "
                         "unconverted sector time still rates below 100. "
                         "Let the milestone carry the achievement — do not "
                         "present the rating as a verdict on the PB.")
        if _is_race(session):
            lines.append("• Execution and Race Discipline are separate on "
                         "purpose: Execution is how well the driver drove "
                         "(race pace, consistency, mistakes — proximity to "
                         "the personal best is deliberately NOT scored in a "
                         "race); Race Discipline counts contacts, penalties "
                         "and flashbacks per lap. Being overtaken, finishing "
                         "low and slower pace are not incidents and do not "
                         "affect it. Overall is the execution score capped by "
                         "the incident rate.")
        else:
            lines.append("• Execution and Cleanliness are separate on purpose: "
                         "Execution is how well the driver drove when driving; "
                         "Cleanliness is lap completion. Overall is the execution "
                         "score capped by the invalid-lap rate — invalid laps bound "
                         "the grade rather than dominating the underlying score.")
    if (session.get('profile') or {}).get('typical'):
        lines.append("• The DRIVER PROFILE describes repeatable performance at "
                     "this combination. Judge laps against the typical clean "
                     "pace range rather than only the personal best — a lap "
                     "inside the range is normal performance for this driver, "
                     "not underperformance against a once-in-a-lifetime lap. "
                     "Fast-lap repeatability says how often the driver actually "
                     "delivers that pace: two drivers with the same PB can "
                     "differ hugely here. The typical pace trend tracks the "
                     "baseline itself — PBs rarely move; the baseline should. "
                     "Weight all of this by the profile confidence: a "
                     "4-session profile is indicative, a 50-session one is "
                     "representative.")
        baseline_ai = (session.get('profile') or {}).get('baseline')
        improving   = (baseline_ai or {}).get('direction') == 'improving'
        lines.append("• If the driver's reflection benchmarks against the AI "
                     "field (e.g. 'way off the AI times'), weigh it against "
                     "the DRIVER PROFILE and TREND sections before echoing "
                     "it: AI difficulty is an adjustable setting, not a "
                     "fixed standard. "
                     + ("This driver's typical-pace baseline is currently "
                        "improving — say so explicitly, with the numbers, "
                        "and anchor progress to their own data rather than "
                        "the AI gap. "
                        if improving else "")
                     + "AI difficulty can be adjusted independently if the "
                       "racing experience no longer matches the driver's "
                       "goals.")
    if rew_laps:
        lines.append("• Rewind (flashback) = time was rewound mid-lap; treat rewound laps "
                     "as assisted, not clean pace.")
    if res_laps:
        lines.append("• Restart = the in-progress attempt was abandoned and the car reset "
                     "to the start line (F1 Time Trial). Unlike a rewind, the lap that "
                     "eventually completed is a clean, representative lap; repeated "
                     "restarts on the same lap mean several attempts were abandoned "
                     "before one was completed.")
    inv_events = [e for e in events if e['type'] == 'invalid']
    if inv_events:
        lines.append("• Use lap invalidation events to identify recurring track limits "
                     "or shortcut locations.")
    if any(e['type'] == 'collision' for e in events):
        lines.append("• Collision events record contact involving the player "
                     "in either direction — they do NOT say who caused it. "
                     "Read them with the surrounding events: a rewind just "
                     "after reads as crashed-then-flashed-back, and a penalty "
                     "detail may name the infringement and the other driver.")
    is_f1 = (session.get('game') or '').lower().startswith('f1')
    cooldown_nums = sorted(n for n, c in lap_classes.items() if c == 'cooldown')
    if cooldown_nums:
        nums   = ", ".join(str(n) for n in cooldown_nums)
        plural = len(cooldown_nums) > 1
        lines.append(f"• Lap{'s' if plural else ''} {nums} "
                     f"{'are' if plural else 'is a'} deliberate cooldown "
                     f"lap{'s' if plural else ''} (slow running between push "
                     "laps — tyre prep, ERS recharge; marked 'cool' in the "
                     "lap table). Treat as intentional, not driving errors, "
                     "and exclude from pace and consistency analysis.")
    elif is_f1 and ('QUAL' in stype or 'PRACT' in stype):
        lines.append("• This is an F1 practice/qualifying session: slow laps before or after "
                     "a fast lap are likely deliberate cooldown/battery-recharge (ERS) laps "
                     "between runs — treat them as intentional, not driving errors, and "
                     "exclude them from pace and consistency analysis.")
    stype_l = (session.get('session_type') or '').strip().lower()
    if stype_l == 'qualifying':
        lines.append("• This is a qualifying session: the result is the story. "
                     "Coach the outcome — position, gap to pole and to the "
                     "cars either side — and sector strengths and weaknesses. "
                     "Do not coach consistency or repeatability across runs, "
                     "and mention tyre degradation only if the data shows it "
                     "mattered.")
    elif stype_l == 'hotlap':
        lines.append("• This is a time-trial session: every lap is a "
                     "maximum-attack attempt at the same conditions. Judge "
                     "outright pace and conversion — completing clean laps at "
                     "the pace shown. Fuel, tyre wear and traffic do not "
                     "apply; restarts are abandoned attempts, not mistakes.")
    elif stype_l == 'practice':
        lines.append("• This is a practice session: expect several run plans "
                     "(race sims, qualifying sims, tyre tests) with different "
                     "objectives. Judge each run against its own purpose and "
                     "compare pace within a run, not across the whole session "
                     "— spread between run programmes is planning, not "
                     "inconsistency. Account for tyre compound and fuel "
                     "differences between runs.")
    elif stype_l == 'race':
        lines.append("• This is a race: judge race pace over representative "
                     "laps, stint management and tyre degradation, and treat "
                     "racecraft (overtakes, defending — see RACECRAFT) as its "
                     "own skill, separate from lap-time execution. Proximity "
                     "to the personal best lap time is background noise — "
                     "fuel, tyres and traffic decide race lap times.")
    if len({st['compound'] for st in stints if st['compound']}) >= 2:
        lines.append("• Multiple tyre compounds were used (see TYRE STINTS) — "
                     "compare lap times within a stint, never across "
                     "compounds; a slower lap on a harder compound is the "
                     "tyre, not the driver.")
    for deploy, clear in sc_periods:
        d, c = deploy['lap_num'], clear['lap_num'] if clear else None
        if c and c != d:
            lines.append(f"• Laps {d}–{c} were under Safety Car — exclude from pace comparison.")
        elif c:
            lines.append(f"• Lap {d} had a Safety Car period — treat that lap time with caution.")
        else:
            lines.append(f"• Safety Car deployed lap {d} — session may have ended under SC.")
    for deploy, clear in vsc_periods:
        d, c = deploy['lap_num'], clear['lap_num'] if clear else None
        if c and c != d:
            lines.append(f"• Laps {d}–{c} were under Virtual Safety Car — lap times will be artificially slow.")
        elif c:
            lines.append(f"• Lap {d} had a Virtual Safety Car period — treat that lap time with caution.")
        else:
            lines.append(f"• Virtual Safety Car deployed lap {d} — session may have ended under VSC.")
    is_race = (session.get('session_type') or '').strip().lower() == 'race'
    if pit_laps and is_race:
        nums = ", ".join(str(n) for n in sorted(pit_laps))
        plural = len(pit_laps) > 1
        lines.append(f"• Lap{'s' if plural else ''} {nums} included a pit stop — "
                     f"{'these lap times include' if plural else 'this lap time includes'} "
                     f"pit lane time and {'are' if plural else 'is'} not representative of race pace.")
    elif pit_laps:
        # Qualifying/practice/hotlap: pit visits bound runs, so the pit
        # laps are out-laps and in-laps rather than racing pit stops.
        out_nums = sorted(n for n, c in lap_classes.items() if c in ('out', 'in/out'))
        in_nums  = sorted(n for n, c in lap_classes.items() if c in ('in', 'in/out'))
        parts = []
        if out_nums:
            parts.append(f"out-lap{'s' if len(out_nums) != 1 else ''} "
                         f"{', '.join(str(n) for n in out_nums)}")
        if in_nums:
            parts.append(f"in-lap{'s' if len(in_nums) != 1 else ''} "
                         f"{', '.join(str(n) for n in in_nums)}")
        if parts:
            lines.append(f"• Ignore {' and '.join(parts)} when evaluating pace "
                         "— pit-lane transit laps, not push laps (marked in "
                         "the lap table).")
    if is_race and any(lap.get('num') == 1 for lap in laps):
        lines.append("• Lap 1 is the race start — exclude it from consistency "
                     "analysis (standing start and first-lap traffic).")

    # ── Race Engineer Notes — session-specific findings for the driver ──────
    # Goal-aware, same as the session detail: the Session Goal verdict leads
    # and notes matching the chosen focus float above the rest.
    coach = race_engineer_notes(session, facts,
                           prior_best=session.get('prior_best'),
                           track_map=track_map,
                           focus_id=(session.get('focus') or '').strip() or None,
                           focus_verdict=session.get('focus_verdict'))
    if coach:
        lines.append("")
        lines.append("AI RACE ENGINEER NOTES")
        for i, note in enumerate(coach):
            if i:
                lines.append("")
            lines.append(note)

    # ── driver notes ───────────────────────────────────────────────────────
    # Placeholder for driver to add their reflection from that session
    lines.append("")
    lines.append("DRIVER SESSION REFLECTION")
    lines.append("-" * 38)
    lines.append("(Driver: add your own thoughts on the session below. "
                 "AI: treat the telemetry as the primary source of truth. "
                 "Use the driver's reflection to provide context, explain "
                 "anomalies, or prioritise coaching, but do not allow "
                 "subjective impressions to override objective telemetry. "
                 "If no reflection is provided, base coaching solely on "
                 "the telemetry.)")
    lines.append("")

    return "\n".join(lines)
