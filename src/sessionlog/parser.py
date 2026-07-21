"""
Shfonic Dash sessionlog — session log parser (shared library; canonical
home is ShfonicDash/src/sessionlog/, vendored into the companion
app by sync_shared.py — see the package docstring).

Supports two CSV formats produced by the Pi:

  NEW (typed-row) format — one row-type code per line:
    S   — session metadata key/value pairs
    GH  — column headers for G rows
    G   — starting grid / participant roster
    H   — column headers for L rows
    L   — one completed lap
    RH  — column headers for R rows
    R   — final standings
    (anything else is silently ignored)

  OLD (flat) format — plain header row + data rows:
    lap_num,lap_time,s1,...,car_class,session_type,game
    1,77.503,...
    No track name; metadata embedded in every data row.

Format is auto-detected from the first non-empty line.

Output session dict shape:
  {
    "filename":      str,
    "date":          datetime | None,
    "track":         str | None,          # from S row; populated by F1 25
    "layout":        None,                # not in log format
    "car":           str,                 # car_name if present, else car_class display name
    "car_name":      str | None,          # e.g. "Red Bull Racing"
    "car_class":     str,                 # e.g. "formula1_2026"
    "car_class_name": str,                # e.g. "F1 2026"
    "session_type":  str,                 # "race" | "qualifying" | "practice" | "hotlap"
    "session_subtype": str,               # finer variant, e.g. "sprint_qualifying";
                                          # "" for a plain session / pre-v0.1.133 files.
                                          # Display label rule: subtype or session_type
                                          # (see session_label()); analysis keys off
                                          # session_type.
    "game":          str,                 # e.g. "f1_25"
    "game_name":     str,                 # e.g. "F1 25"
    "weather":       str,                 # last S-row value: "clear", "light_cloud",
                                          # "overcast", "light_rain", "heavy_rain",
                                          # "storm", "snow"; "" = not recorded
                                          # (pre-v0.2.0 files, Forza)
    "air_temp":      int | None,          # ambient °C (v0.2.0+)
    "track_temp":    int | None,          # track surface °C (v0.2.0+)
    "best_lap_time": float | None,
    "laps": [
      {
        "num":            int,
        "time":           float,
        "s1":             float | None,
        "s2":             float | None,
        "s3":             float | None,
        "valid":          bool,           # False if game flagged lap invalid (track limits etc.)
        "rewinds":        int,            # number of flashbacks/rewinds used during this lap (0 = clean)
        "restarts":       int,            # F1 TT "restart lap" resets during this lap's attempts
                                          # (derived from restart events; completed lap is still clean)
        "lap_flag":       str | None,     # "magenta" | "purple" | None
        "s1_flag":        str | None,     # "magenta"|"purple"|"green"|"yellow"|None
        "s2_flag":        str | None,
        "s3_flag":        str | None,
        "position":       int | None,
        "tyre_compound":  str | None,
        "fuel_remaining": float | None,
        "fuel_per_lap":   float | None,
        "delta":          float | None,
        "tyre_fl":        float | None,
        "tyre_fr":        float | None,
        "tyre_rl":        float | None,
        "tyre_rr":        float | None,
        # Highest assist level reached at any point during the lap (v0.40.0+;
        # None for older files — column absent, NOT the same as 0/off).
        # F1 only, always 0 for other games. See docs/session-log-format.md
        # for the per-field 0/1/2 meanings.
        "assist_tc":            int | None,
        "assist_abs":           int | None,
        "assist_racing_line":   int | None,
        "assist_steering":      int | None,
        "assist_braking":       int | None,
        "assist_gearbox":       int | None,
        "assist_pit":           int | None,
        "assist_pit_release":   int | None,
        "assist_ers":           int | None,
        "assist_drs":           int | None,
      },
      ...
    ],
    "grid":      [ {"position", "race_num", "name"}, ... ],
    "standings": [ {"position", "race_num", "name", "best_lap", "race_time"}, ... ],
    "events":    [ {"lap_num": int, "lap_time": float, "type": str,
                    "distance": float | None,   # metres around the lap (F1 only)
                    "t": float | None,          # wall-clock s since file open
                                                # (v0.1.133+; None in older files).
                                                # Use t for durations — lap_time
                                                # resets across pit teleports.
                    "detail": str | None}, ...],# event context (v0.1.135+):
                                                # other driver for collision/
                                                # overtake/overtaken; penalty
                                                # spec (see penalty_detail())
    "debrief":   { question_id: answer_id, ... },  # driver debrief D rows
                                                   # (v0.6.0+; {} when absent —
                                                   # see sessionlog.debrief)
    "summary":   { "fastest_lap", "avg_clean_lap", "std_dev",     # floats | None (from Z rows)
                   "invalid_laps", "rewinds", "restarts" },       # ints | None
    "rewinds_reliable": bool,   # False for pre-v0.1.133 files with pit events:
                                # their rewind/restart events and per-lap rewinds
                                # column contain spurious entries around pit stops.
  }
"""

import csv
import io
from datetime import datetime

from . import circuits
from . import lines as _lines
from . import trackmap as _trackmap

_GREEN_THRESHOLD  = 0.30
_YELLOW_THRESHOLD = 1.00

GAME_NAMES = {
    "f1_25":  "F1 25",
    "pcars2": "Project CARS 2",
    "fh6":    "Forza Horizon 6",
    "fm":     "Forza Motorsport",
    "acc":    "Assetto Corsa Competizione",
    "ac":     "Assetto Corsa",
}

CAR_CLASS_NAMES = {
    "formula1":      "F1 2025",
    "formula1_2026": "F1 2026",
    "f2":            "Formula 2",
    "formula_ford":  "Formula Ford",
    "gt3":           "GT3",
    "gt4":           "GT4",
    "gte":           "GTE",
    "fh6":           "Forza Horizon",
    "fm":            "Forza Motorsport",
}

# session_subtype → parent session_type. Analysis keys off session_type;
# the subtype is display/grouping only. Unrecognised subtypes fall back to
# their session_type (per the format spec).
SESSION_SUBTYPE_TYPES = {
    "sprint_qualifying": "qualifying",
}

# Circuit lengths in metres for the F1 track set, derived from the circuit
# reference table (which also carries each track's real name and location).
# Lap rows carry no distance, so a session's driven distance is estimated as
# lap_count * length. F1 only for now ("F1 now, extend later"); other games
# store NULL and count as zero until their track lengths / map geometry are
# wired in. Kept as a module-level name because it is part of this module's
# published surface.
F1_TRACK_LENGTHS_M = {
    name: info[-1]
    for name, info in circuits._F1_CIRCUITS.items()
    if info[-1] is not None
}


def _session_distance_m(game, track, lap_count):
    """Estimated driven distance in metres for one session, or None when the
    game/track has no known length. Currently F1 only (game 'f1_25'); the
    track set is the same for the 2025/2026/F2 car classes."""
    if not lap_count:
        return None
    length = circuits.length_m(game, track)
    return length * lap_count if length else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_session(filepath):
    """
    Fast scan of a cached CSV for stats aggregation and the session index DB.

    Handles both the new typed-row format and the old flat CSV format.
    Returns a compact record dict, or None if unreadable or has no timed laps.
    track may be None (old flat format does not store track name).

    Record keys (this shape is the session_db.py row contract):
      filename, date (datetime|None), track (str|None), car, car_name,
      car_class, car_class_name, session_type,
      session_subtype (str — e.g. "sprint_qualifying"; "" for a plain
        session and for files/formats that predate subtypes),
      driver_name, game, game_name,
      best_lap_time (float|None — best CLEAN lap: game-valid, no rewinds),
      best_s1/best_s2/best_s3 (sectors of that best lap, float|None),
      race_time (float|None — player's classified race time from R rows),
      position (int|None — final R-row position, else last lap's position),
      lap_count (int),
      distance_m (float|None — estimated driven distance: lap_count times the
        circuit length. F1 only for now (game 'f1_25', track in
        F1_TRACK_LENGTHS_M); None for other games and flat-format files, which
        count as zero in career totals until their lengths are wired in),
      valid_lap_count (int — timed laps the game scored valid),
      clean_lap_count (int — valid AND no rewinds),
      clean_std_dev (float|None — spread of clean lap times, excluding
        pit-stop and SC/VSC laps, cool-down laps between push laps in
        non-race sessions, and lap 1 in races (standing start). Pooled
        WITHIN tyre stints (stint_std_dev) so a compound change doesn't
        read as inconsistency; None when no stint has 2 such laps),
      theo_time (float|None — min S1+S2+S3 over clean laps; None when
        fewer than 2 clean laps carry all three sectors),
      rewind_count (int|None — total rewinds across timed laps; None when
        the file predates v0.1.133 and contains pit events, because such
        files log spurious rewinds around pit stops — treat as unknown),
      collision_count (int — player-involved car contacts, from collision
        events; 0 for files/games without them (v0.1.135+)),
      penalty_count (int — stewards' penalty/warning events (v0.1.135+)),
      start_position (int|None — the player's grid slot from the G rows;
        None for non-races, flat-format files and files without grid
        rows. Same source as pace.net_positions, so racecraft badges
        and the journal agree),
      perfect_lap (int 0/1 — all three session-best sectors set on one
        clean lap; needs 3+ clean laps carrying all sectors),
      clean_streak (int — longest run of consecutive clean timed laps),
      cons_lap_count (int — consistency-eligible laps: clean, minus
        pit/SC and cool-down laps),
      cons_band_count (int — of those, laps within 1% of the session's
        best such lap: "on-pace" laps for the driver profile),
      tc_used_lap_count (int — laps where traction control reached above
        off at any point; 0 for non-F1 and files predating v0.40.0),
      abs_used_lap_count (int — same for ABS),
      racing_line_used_lap_count (int — same for the dynamic racing line
        assist),
      gearbox_assist_used_lap_count (int — same for the gearbox assist).
    """
    import os as _os
    filename = _os.path.basename(filepath)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return None

    if _is_typed_format(content):
        return _scan_typed(content, filename)
    else:
        return _scan_flat_summary(content, filename)


def parse(csv_text, filename=""):
    """
    Parse a CSV string into a session dict.

    Handles both the new typed-row format and the old flat CSV format.
    csv_text — full text of the CSV.
    filename — used as a date fallback when the CSV has no date metadata.
    """
    if _is_typed_format(csv_text):
        return _parse_typed(csv_text, filename)
    else:
        return _parse_flat(csv_text, filename)


# ---------------------------------------------------------------------------
# Formatting helpers — used by dashboard.py and mock_data.py
# ---------------------------------------------------------------------------

def session_label(session):
    """
    Display label for a session dict / scan record / picker entry:
    session_subtype when present, else session_type ('' if neither).
    Raw key, not prettified — callers upper()/replace('_', ' ') as needed.
    """
    return (session.get("session_subtype") or session.get("session_type")
            or "").strip()


def qualifying_outcome(session):
    """
    The driver's qualifying result from the final standings: position
    and best-lap gaps to pole and to the cars either side. None unless
    this is a qualifying session with a named driver who appears in the
    standings with a best lap.

      {'position': int,           # driver's classified position
       'total':    int,           # cars classified
       'pole':     {'name', 'gap'} | None,   # gap = my best − pole's
                                             # (None when on pole)
       'ahead':    {'name', 'gap'} | None,   # gap = my best − theirs
       'behind':   {'name', 'gap'} | None}   # gap = theirs − my best
                                             # (positive = my margin)

    Cars without a best lap (no clean timed lap) are skipped for gap
    lookups but still count towards 'total'.
    """
    if (session.get("session_type") or "").strip().lower() != "qualifying":
        return None
    driver = (session.get("driver_name") or "").strip().lower()
    standings = session.get("standings") or []
    if not driver or not standings:
        return None

    rows = []
    for st in standings:
        try:
            pos  = int((st.get("position") or "").strip())
            best = float((st.get("best_lap") or "").strip())
        except (ValueError, AttributeError):
            continue
        rows.append((pos, (st.get("name") or "").strip(), best))
    rows.sort()

    me = next((r for r in rows if r[1].lower() == driver), None)
    if me is None:
        return None
    pos, _, my_best = me

    def _row(p):
        return next((r for r in rows if r[0] == p), None)

    pole, ahead, behind = _row(1), _row(pos - 1), _row(pos + 1)
    return {
        "position": pos,
        "total":    len(standings),
        # The driver's classified best lap — the time that put them on the
        # grid. From the standings, so it's present even when no lap passed
        # our "clean" filter (a flashback on the only lap, say).
        "best":     my_best,
        "pole":     ({"name": pole[1], "gap": my_best - pole[2]}
                     if pole and pos > 1 else None),
        "ahead":    ({"name": ahead[1], "gap": my_best - ahead[2]}
                     if ahead and pos > 1 else None),
        "behind":   ({"name": behind[1], "gap": behind[2] - my_best}
                     if behind else None),
    }


def _stint_indices(compounds):
    """
    Tyre-stint index per position from compound strings in running
    order. A new stint starts when a lap broadcasts a compound different
    from the stint's known compound; an empty compound continues the
    current stint (the game didn't broadcast it, not a tyre change —
    compound changes coincide with a pit visit).
    """
    out = []
    current = ''   # known compound of the open stint
    idx = -1
    for compound in compounds:
        compound = (compound or '').strip()
        if idx < 0 or (compound and current and compound != current):
            idx += 1
            current = compound
        elif compound and not current:
            current = compound
        out.append(idx)
    return out


def tyre_stints(session):
    """
    Consecutive-lap stints split on tyre compound change, in running
    order:  [{'compound': str|None, 'laps': [lap dicts]}, ...]

    Split rule per _stint_indices; sessions where no lap carries a
    compound return a single None-compound stint. Analyse pace within a
    stint, never across compounds.
    """
    laps = session.get("laps") or []
    stints = []
    for lap, idx in zip(laps, _stint_indices(
            lap.get("tyre_compound") for lap in laps)):
        if idx == len(stints):
            stints.append({"compound": None, "laps": []})
        stints[idx]["laps"].append(lap)
        if stints[idx]["compound"] is None:
            compound = (lap.get("tyre_compound") or "").strip()
            stints[idx]["compound"] = compound or None
    return stints


def stint_std_dev(groups):
    """
    Pooled within-stint sample standard deviation over groups of lap
    times (one group per tyre stint): spread is measured against each
    stint's own mean, so a compound change doesn't read as
    inconsistency. Identical to statistics.stdev for a single group.
    Groups with fewer than 2 laps contribute nothing; None when no
    group has 2.
    """
    dev_sq = 0.0
    dof    = 0
    for times in groups:
        if len(times) >= 2:
            mean    = sum(times) / len(times)
            dev_sq += sum((t - mean) ** 2 for t in times)
            dof    += len(times) - 1
    return (dev_sq / dof) ** 0.5 if dof else None


def format_lap_time(seconds):
    """float → '1:08.731'. Returns '--:--.---' for None."""
    if seconds is None:
        return "--:--.---"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}:{secs:06.3f}"


def format_sector_time(seconds):
    """float → '21.199'. Returns '---.---' for None."""
    if seconds is None:
        return "---.---"
    return f"{seconds:.3f}"


def _pit_sc_lap_reasons(events, last_lap=None):
    """
    Lap number → why the lap's time is unrepresentative, from events:
    'in' / 'out' / 'in/out' (pit entry, exit, or both on one lap) or
    'sc' (inside an SC/VSC window). Pit labels win over 'sc' — the pit
    visit is the more specific story. last_lap bounds an SC/VSC window
    never seen clearing.
    """
    reasons   = {}
    open_from = {}

    def _pit(num, label, other):
        reasons[num] = 'in/out' if reasons.get(num) == other else label

    for ev in events:
        etype = ev.get('type')
        num   = ev.get('lap_num')
        if num is None:
            continue
        if etype == 'pit_in':
            _pit(num, 'in', 'out')
        elif etype == 'pit_out':
            _pit(num, 'out', 'in')
        elif etype in ('sc_deploy', 'vsc_deploy'):
            open_from.setdefault(etype, num)
        elif etype in ('sc_clear', 'vsc_clear'):
            start = open_from.pop(etype.replace('clear', 'deploy'), num)
            for n in range(start, num + 1):
                reasons.setdefault(n, 'sc')
    for start in open_from.values():
        for n in range(start, (last_lap if last_lap is not None
                               else start) + 1):
            reasons.setdefault(n, 'sc')
    return reasons


# A pit-tagged lap within this fraction of the session's best clean lap
# is at push pace — see _drop_on_pace_pit_tags.
_PIT_PACE_TOLERANCE = 0.02


def _drop_on_pace_pit_tags(reasons, clean_laps):
    """
    Remove 'in'/'out'/'in/out' tags from laps completed at push pace.
    F1 books garage transit onto the adjacent flyer's lap number (the
    garage teleport resets the lap clock, so the transit never gets its
    own completed lap): in qualifying, the pit events land on the same
    lap number as the flying lap. A genuine transit lap — race pit stop,
    practice out/in lap — is many seconds slower, so a pit-tagged lap
    within _PIT_PACE_TOLERANCE of the best clean lap is the flyer, not
    the transit. clean_laps — [(lap_num, time)] of clean timed laps.
    """
    times = {num: t for num, t in clean_laps if num is not None
             and t is not None}
    if not times:
        return reasons
    cutoff = min(times.values()) * (1 + _PIT_PACE_TOLERANCE)
    for num in [n for n, r in reasons.items()
                if r in ('in', 'out', 'in/out')
                and times.get(n) is not None and times[n] <= cutoff]:
        del reasons[num]
    return reasons


def consistency_excluded_laps(events, last_lap=None, session_type=None,
                              clean_laps=None):
    """
    Lap numbers whose times are not representative for consistency
    analysis: laps with a pit entry/exit, laps inside an SC/VSC period,
    and — in race sessions — lap 1 (standing start and first-lap
    traffic, never representative of race pace). Used by the scan's
    clean_std_dev and grading.session_facts() (both must agree).
    events — dicts with 'type' and 'lap_num' keys. last_lap — highest
    lap number, for an SC/VSC never seen clearing. clean_laps — clean
    [(lap_num, time)] pairs; when given, pit tags on laps completed at
    push pace are dropped (F1 qualifying books garage transit onto the
    flyer's lap number — see _drop_on_pace_pit_tags).
    """
    reasons = _pit_sc_lap_reasons(events, last_lap)
    if clean_laps is not None:
        _drop_on_pace_pit_tags(reasons, clean_laps)
    excluded = set(reasons)
    if (session_type or '').strip().lower() == 'race':
        excluded.add(1)
    return excluded


def classify_laps(session):
    """
    Lap number → why that lap is not a representative push lap:
      'in' / 'out' / 'in/out' — pit entry, exit, or both on one lap
      'sc'       — inside a Safety Car / VSC window
      'start'    — race lap 1 (standing start, first-lap traffic)
      'cooldown' — deliberate slow lap between push laps (non-race)
    Laps absent from the dict are representative. Priorities: pit > sc >
    start > cooldown. Agrees with the consistency exclusions used by
    scan_session() and grading.session_facts().
    """
    laps  = session.get('laps') or []
    stype = (session.get('session_type') or '').strip().lower()
    nums  = [lap['num'] for lap in laps if lap.get('num') is not None]
    clean = [(lap['num'], lap['time']) for lap in laps
             if lap.get('valid', True) and not lap.get('rewinds', 0)]

    classes = _pit_sc_lap_reasons(session.get('events') or [],
                                  max(nums, default=None))
    _drop_on_pace_pit_tags(classes, clean)
    if stype == 'race' and 1 in nums:
        classes.setdefault(1, 'start')

    eligible = [(lap['num'], lap['time']) for lap in laps
                if lap.get('num') is not None and lap.get('time') is not None
                and lap.get('valid', True) and not lap.get('rewinds', 0)
                and lap['num'] not in classes]
    for num in cooldown_laps(eligible, stype, set(classes)):
        classes[num] = 'cooldown'
    return classes


# A clean lap this much slower than the session's fastest clean lap is a
# push-lap candidate no more; runs of such laps BETWEEN push laps are
# cool-downs (see cooldown_laps).
_COOLDOWN_THRESHOLD = 0.05

# A consistency-eligible lap within this fraction of the session's best
# such lap counts as "on pace" (cons_band_count). Baked in at scan time —
# changing it needs a Resync Database, so it is a constant, not config.
_PACE_BAND = 0.01


def cooldown_laps(ordered, session_type=None, blocked=()):
    """
    Cool-down laps in qualifying / practice / hotlap running: deliberate
    slow laps (tyre prep, ERS recharge) sandwiched between push laps —
    push → slow → push. They are clean laps driven slowly on purpose, so
    the consistency maths must not read them as inconsistency. Race
    sessions return empty: a slow race lap is real.

    ordered — [(lap_num, time), ...] in running order, clean
    consistency-eligible laps only (pit/SC laps already removed).
    blocked — lap numbers removed as pit/SC laps: if one of them sits
    between a slow run and its bounding "push" lap, those laps were not
    actually adjacent on track and the pattern is NOT claimed — a pit
    visit anywhere in the push→cool→push triple disqualifies it.

    A lap is "slow" when more than _COOLDOWN_THRESHOLD over the fastest
    clean lap; a slow run counts as cool-down only when push laps bound
    it on BOTH sides (a slow lap at the end of the session is not
    assumed to be deliberate).
    """
    if (session_type or '').strip().lower() == 'race' or len(ordered) < 3:
        return set()
    fastest = min(t for _, t in ordered)
    cutoff  = fastest * (1 + _COOLDOWN_THRESHOLD)
    push    = [t <= cutoff for _, t in ordered]
    blocked = set(blocked)

    def _pit_free(num_a, num_b):
        """No blocked (pit/SC) lap between two lap numbers."""
        if num_a is None or num_b is None:
            return False
        return not (set(range(num_a + 1, num_b)) & blocked)

    out = set()
    i, n = 0, len(ordered)
    while i < n:
        if push[i]:
            i += 1
            continue
        j = i
        while j < n and not push[j]:
            j += 1
        if (i > 0 and j < n                     # bounded by push laps…
                and _pit_free(ordered[i - 1][0], ordered[i][0])
                and _pit_free(ordered[j - 1][0], ordered[j][0])):
            out.update(num for num, _ in ordered[i:j])
        i = j
    return out


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

_TYPED_TOKENS = frozenset(('S', 'H', 'L', 'GH', 'RH', 'G', 'R'))


def _is_typed_format(csv_text):
    """Return True if the CSV uses the new typed-row format."""
    for line in csv_text.split('\n'):
        line = line.strip()
        if line:
            return line.split(',', 1)[0] in _TYPED_TOKENS
    return False


# ---------------------------------------------------------------------------
# Typed-row format — parse and scan
# ---------------------------------------------------------------------------

def _parse_typed(csv_text, filename=""):
    (meta, grid, lap_rows, standings, event_rows, summary_raw,
     debrief, focus, objectives, paths) = _parse_typed_rows(csv_text)

    car_name        = meta.get("car_name") or None
    car_class       = meta.get("car_class", "")
    session_type    = meta.get("session_type", "")
    session_subtype = (meta.get("session_subtype") or "").strip()
    game            = meta.get("game", "")
    track           = meta.get("track") or None
    driver_name     = (meta.get("driver_name") or "").strip()
    weather         = (meta.get("weather") or "").strip()
    air_temp        = _int(meta, "air_temp")
    track_temp      = _int(meta, "track_temp")

    date = _parse_started_at(meta.get("started_at", ""))
    if date is None:
        date, _, _ = _parse_filename(filename)

    lap_rows = _remove_rewinds(lap_rows)
    laps = [_build_lap(r) for r in lap_rows]
    laps, best_lap_time = _apply_flags(laps)
    events = _build_events(event_rows)
    rewinds_reliable = _rewinds_reliable(
        any("t" in r for r in event_rows), [e["type"] for e in events])

    # Restarts (F1 TT "restart lap") live only in E rows — the L row's rewinds
    # column excludes them because the attempt that completes is a clean lap.
    restart_counts = {}
    for ev in events:
        if ev["type"] == "restart":
            restart_counts[ev["lap_num"]] = restart_counts.get(ev["lap_num"], 0) + 1
    for lap in laps:
        lap["restarts"] = restart_counts.get(lap["num"], 0)
        # Racing-line offset profile (metres per station) from the P row, when
        # the session recorded one (F1 hotlap/quali at a mapped track).
        lap["line_offsets"] = paths.get(lap["num"])

    car_class_name = CAR_CLASS_NAMES.get(car_class, car_class)

    def _z_float(key):
        v = summary_raw.get(key, "").strip()
        try: return float(v) if v else None
        except ValueError: return None

    def _z_int(key):
        v = summary_raw.get(key, "").strip()
        try: return int(v) if v else None
        except ValueError: return None

    summary = {
        "fastest_lap":    _z_float("fastest_lap"),
        "avg_clean_lap":  _z_float("avg_clean_lap"),
        "std_dev":        _z_float("std_dev"),
        "invalid_laps":   _z_int("invalid_laps"),
        "rewinds":        _z_int("rewinds"),
        "restarts":       _z_int("restarts"),
    }

    return {
        "filename":       filename,
        "date":           date,
        "track":          track,
        # Real circuit name / location resolved from the bare telemetry name
        # (circuits.py). track_name falls back to `track`, so it is always a
        # safe display string; track_location is None when unknown.
        "track_name":     circuits.display_name(game, track),
        "track_location": circuits.location(game, track),
        "layout":         None,
        "car":            car_name or car_class_name,
        "car_name":       car_name,
        "car_class":      car_class,
        "car_class_name": car_class_name,
        "session_type":   session_type,
        "session_subtype": session_subtype,
        "driver_name":    driver_name,
        "game":           game,
        "game_name":      GAME_NAMES.get(game, game),
        "weather":        weather,      # last value seen ("" = not recorded)
        "air_temp":       air_temp,     # °C int or None
        "track_temp":     track_temp,   # °C int or None
        "best_lap_time":  best_lap_time,
        "laps":           laps,
        "events":         events,
        "grid":           grid,
        "standings":      standings,
        "summary":        summary,
        "debrief":        debrief,   # {question_id: answer_id} from D rows
        "focus":          focus,     # driver-selected focus id ('' none) from the F row
        "objectives":     objectives,  # tracked objectives from O rows
        "rewinds_reliable": rewinds_reliable,
        "line_ref":       (meta.get("line_ref") or "").strip(),  # attempts of the line captured against
    }


def _row_is_clean(row):
    """Game-valid and no rewinds used — the same rule as _apply_flags."""
    if (row.get('invalid') or '').strip() == '1':
        return False
    rew = (row.get('rewinds') or '').strip()
    try:
        return not (int(rew) if rew else 0)
    except ValueError:
        return True


def _scan_best(timed_rows):
    """
    Best clean lap from [(time, row), ...] → (best_time, s1, s2, s3).
    All None when no clean timed lap exists (records need a clean lap).
    """
    clean = [(t, row) for t, row in timed_rows if _row_is_clean(row)]
    if not clean:
        return None, None, None, None
    best_time, best_row = min(clean, key=lambda tr: tr[0])
    return (best_time, _float(best_row, 's1'),
            _float(best_row, 's2'), _float(best_row, 's3'))


def _scan_facts(timed, events=(), session_type=None):
    """
    Session-grading facts over [(time, row), ...] — the valid_lap_count /
    clean_lap_count / clean_std_dev / theo_time / rewind_count /
    clean_streak record keys (see the scan_session docstring).
    grading.session_facts() computes the same values from a fully parsed
    session; keep the two in agreement.
    """
    valid = [(t, row) for t, row in timed
             if (row.get('invalid') or '').strip() != '1']
    clean = [(t, row) for t, row in timed if _row_is_clean(row)]

    # Reconciled with rewind EVENTS: a flashback on a lap whose L row
    # was never logged (e.g. a race's final lap) is invisible to the
    # per-lap column but must still count — keep session_facts() in
    # agreement.
    rewind_count = 0
    for _, row in timed:
        rewind_count += _int(row, 'rewinds') or 0
    rewind_count = max(rewind_count,
                       sum(1 for e in events if e.get('type') == 'rewind'))

    streak = best_streak = 0
    for _, row in timed:
        streak = streak + 1 if _row_is_clean(row) else 0
        best_streak = max(best_streak, streak)

    last_lap = max((n for n in (_int(row, 'lap_num') for _, row in timed)
                    if n is not None), default=None)
    pit_sc    = consistency_excluded_laps(
        events, last_lap, session_type,
        [(_int(row, 'lap_num'), t) for t, row in clean])
    sidx      = _stint_indices(row.get('tyre_compound') for _, row in timed)
    eligible  = [(_int(row, 'lap_num'), t, sidx[i])
                 for i, (t, row) in enumerate(timed)
                 if _row_is_clean(row)
                 and _int(row, 'lap_num') not in pit_sc]
    cooldowns = cooldown_laps([(num, t) for num, t, _ in eligible],
                              session_type, pit_sc)
    cons   = [(t, s) for num, t, s in eligible if num not in cooldowns]
    stints = {}
    for t, s in cons:
        stints.setdefault(s, []).append(t)
    cons = [t for t, _ in cons]

    band = 0
    if cons:
        cutoff = min(cons) * (1 + _PACE_BAND)
        band = sum(1 for t in cons if t <= cutoff)

    full = [row for _, row in clean
            if _float(row, 's1') is not None
            and _float(row, 's2') is not None
            and _float(row, 's3') is not None]
    theo = None
    if len(full) >= 2:
        theo = (min(_float(r, 's1') for r in full)
                + min(_float(r, 's2') for r in full)
                + min(_float(r, 's3') for r in full))

    # All three session-best sectors on one clean lap. Needs 3+ full
    # laps — with fewer there is no field to beat and every lap is
    # trivially "perfect".
    perfect = 0
    if len(full) >= 3:
        eps = 0.0005
        m1 = min(_float(r, 's1') for r in full)
        m2 = min(_float(r, 's2') for r in full)
        m3 = min(_float(r, 's3') for r in full)
        perfect = int(any(_float(r, 's1') <= m1 + eps
                          and _float(r, 's2') <= m2 + eps
                          and _float(r, 's3') <= m3 + eps
                          for r in full))

    return {
        'perfect_lap':     perfect,
        'valid_lap_count': len(valid),
        'clean_lap_count': len(clean),
        'clean_std_dev':   stint_std_dev(stints.values()),
        'theo_time':       theo,
        'rewind_count':    rewind_count,
        'collision_count': sum(1 for e in events
                               if e.get('type') == 'collision'),
        'penalty_count':   sum(1 for e in events
                               if e.get('type') == 'penalty'),
        'clean_streak':    best_streak,
        'cons_lap_count':  len(cons),
        'cons_band_count': band,
        # Laps where the assist reached above off/manual at any point —
        # feeds the pre-session "reduce assist reliance" mission
        # (sessionlog.goals). F1 only; 0 for other games and for files
        # older than v0.40.0 (missing assist_* L-row columns → _int() None).
        'tc_used_lap_count':             sum(1 for _, row in timed
                                              if (_int(row, 'assist_tc') or 0) > 0),
        'abs_used_lap_count':            sum(1 for _, row in timed
                                              if (_int(row, 'assist_abs') or 0) > 0),
        'racing_line_used_lap_count':    sum(1 for _, row in timed
                                              if (_int(row, 'assist_racing_line') or 0) > 0),
        'gearbox_assist_used_lap_count': sum(1 for _, row in timed
                                              if (_int(row, 'assist_gearbox') or 0) > 0),
    }


def _scan_typed(content, filename):
    """Fast metadata + lap-count scan of a typed-row CSV."""
    meta = {}
    hh   = []
    rh   = []
    eh   = []
    gh   = []
    timed     = []
    standings = []
    events    = []
    grid      = []
    paths     = {}   # lap_num -> [offset metres] from P rows
    for line in content.split('\n'):
        s = line.strip()
        if s.startswith('P,'):
            parts = s.split(',')
            ln = _path_lap_num(parts)
            if ln is not None:
                paths[ln] = _path_offsets(parts)
        elif s.startswith('S,'):
            parts = s.split(',', 2)
            if len(parts) >= 3:
                meta[parts[1]] = parts[2]
        elif s.startswith('H,'):
            hh = s.split(',')[1:]
        elif s.startswith('RH,'):
            rh = s.split(',')[1:]
        elif s.startswith('EH,'):
            eh = s.split(',')[1:]
        elif s.startswith('GH,'):
            gh = s.split(',')[1:]
        elif s.startswith('G,') and gh:
            grid.append(dict(zip(gh, s.split(',')[1:])))
        elif s.startswith('L,') and hh:
            row = dict(zip(hh, s.split(',')[1:]))
            try:
                t = float(row.get('lap_time', '') or '')
                if t > 0:
                    timed.append((t, row))
            except ValueError:
                pass
        elif s.startswith('R,') and rh:
            standings.append(dict(zip(rh, s.split(',')[1:])))
        elif s.startswith('E,') and eh:
            row = dict(zip(eh, s.split(',')[1:]))
            events.append({'lap_num': _int(row, 'lap_num'),
                           'type':    _str(row, 'type')})

    if not timed:
        return None

    car_name        = (meta.get('car_name') or '').strip() or None
    car_class       = (meta.get('car_class') or '').strip()
    car_class_name  = CAR_CLASS_NAMES.get(car_class, car_class)
    weather         = (meta.get('weather') or '').strip()
    session_type    = (meta.get('session_type') or '').strip()
    session_subtype = (meta.get('session_subtype') or '').strip()
    game            = (meta.get('game') or '').strip()
    track           = (meta.get('track') or '').strip() or None
    driver_name     = (meta.get('driver_name') or '').strip()

    date = None
    raw  = (meta.get('started_at') or '').strip()
    if raw:
        try:
            date = datetime.fromisoformat(raw)
        except ValueError:
            pass
    if date is None:
        date, _, _ = _parse_filename(filename)

    best_lap, best_s1, best_s2, best_s3 = _scan_best(timed)

    # Player's final classification: the R row whose name matches driver_name.
    # Position falls back to the last lap's position column.
    race_time = None
    position  = None
    if driver_name:
        for st in standings:
            if (st.get('name') or '').strip().lower() == driver_name.lower():
                race_time = _float(st, 'race_time')
                position  = _int(st, 'position')
                break
    if position is None:
        position = _int(timed[-1][1], 'position')

    # Grid slot from the G rows — same source as pace.net_positions, so
    # racecraft badges and the journal quote the same start position.
    start_position = None
    if driver_name:
        for g in grid:
            if (g.get('name') or '').strip().lower() == driver_name.lower():
                start_position = _int(g, 'position')
                break

    facts = _scan_facts(timed, events, session_type)
    if not _rewinds_reliable('t' in eh, [e['type'] for e in events]):
        facts['rewind_count'] = None

    line_facts = _scan_line_facts(paths, timed, session_type, game, track)

    return {
        'filename':       filename,
        'date':           date,
        'track':          track,
        'car':            car_name or car_class_name or '',
        'car_name':       car_name,
        'car_class':      car_class,
        'car_class_name': car_class_name,
        'session_type':   session_type,
        'session_subtype': session_subtype,
        'driver_name':    driver_name,
        'game':           game,
        'game_name':      GAME_NAMES.get(game, game),
        'weather':        weather,
        'air_temp':       _int(meta, 'air_temp'),
        'track_temp':     _int(meta, 'track_temp'),
        'best_lap_time':  best_lap,
        'best_s1':        best_s1,
        'best_s2':        best_s2,
        'best_s3':        best_s3,
        'race_time':      race_time,
        'position':       position,
        'start_position': start_position,
        'lap_count':      len(timed),
        'distance_m':     _session_distance_m(game, track, len(timed)),
        **facts,
        **line_facts,
    }


# ---------------------------------------------------------------------------
# Flat (old) format — parse and scan
# ---------------------------------------------------------------------------

def _parse_flat(csv_text, filename=""):
    """Parse the old flat CSV (header row + data rows, no type codes)."""
    reader = csv.reader(io.StringIO(csv_text.strip()))
    rows   = list(reader)
    if len(rows) < 2:
        return _empty_session(filename)

    headers  = [h.strip() for h in rows[0]]
    raw_rows = [
        dict(zip(headers, row))
        for row in rows[1:]
        if any(c.strip() for c in row)
    ]
    if not raw_rows:
        return _empty_session(filename)

    raw_rows = _remove_rewinds(raw_rows)

    first        = raw_rows[0]
    car_class    = (first.get('car_class')    or '').strip()
    car_name     = (first.get('car_name')     or '').strip() or None
    session_type = (first.get('session_type') or '').strip()
    game         = (first.get('game')         or '').strip()

    car_class_name = CAR_CLASS_NAMES.get(car_class, car_class)
    date, st, _    = _parse_filename(filename)
    if not session_type and st:
        session_type = st

    laps, best_lap_time = _apply_flags([_build_lap(r) for r in raw_rows])

    return {
        "filename":       filename,
        "date":           date,
        "track":          None,   # not stored in flat format
        "track_name":     "",     # no track name to resolve
        "track_location": None,
        "layout":         None,
        "car":            car_name or car_class_name,
        "car_name":       car_name,
        "car_class":      car_class,
        "car_class_name": car_class_name,
        "session_type":   session_type,
        "session_subtype": "",   # flat format predates subtypes
        "game":           game,
        "game_name":      GAME_NAMES.get(game, game),
        "weather":        "",    # not stored in flat format
        "air_temp":       None,
        "track_temp":     None,
        "best_lap_time":  best_lap_time,
        "laps":           laps,
        "events":         [],
        "grid":           [],
        "standings":      [],
        "summary":        {},
        "debrief":        {},
        "focus":          None,   # flat format predates the F row
        "objectives":     [],     # flat format predates the O row
        "rewinds_reliable": True,   # no events, so nothing spurious
    }


def _scan_line_facts(paths, timed, session_type, game, track):
    """Per-session racing-line facts for the index record. Only touches the
    track map when the file actually carries offset profiles (P rows) — so the
    vast majority of sessions (no line data) skip the map lookup entirely and
    get the all-zero default."""
    if not paths:
        return _lines.session_line_facts({}, None)
    laps = []
    for t, row in timed:
        num = _int(row, 'lap_num')
        laps.append({'num': num, 'time': t,
                     'invalid': (row.get('invalid') or '').strip() == '1',
                     'line_offsets': paths.get(num)})
    session = {'laps': laps, 'session_type': session_type}
    track_map = _trackmap.find_map(game, track)
    return _lines.session_line_facts(session, track_map)


def _scan_flat_summary(content, filename):
    """Fast metadata + lap-count scan of an old flat CSV."""
    reader    = csv.reader(io.StringIO(content.strip()))
    rows      = list(reader)
    if len(rows) < 2:
        return None

    headers   = [h.strip() for h in rows[0]]
    timed     = []
    first_row = None

    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        d = dict(zip(headers, row))
        try:
            t = float(d.get('lap_time', '') or '')
            if t > 0:
                timed.append((t, d))
                if first_row is None:
                    first_row = d
        except ValueError:
            pass

    if not timed or not first_row:
        return None

    car_class    = (first_row.get('car_class')    or '').strip()
    car_name     = (first_row.get('car_name')     or '').strip() or None
    session_type = (first_row.get('session_type') or '').strip()
    game         = (first_row.get('game')         or '').strip()

    car_class_name = CAR_CLASS_NAMES.get(car_class, car_class)
    date, st, _    = _parse_filename(filename)
    if not session_type and st:
        session_type = st

    best_lap, best_s1, best_s2, best_s3 = _scan_best(timed)

    return {
        'filename':       filename,
        'date':           date,
        'track':          None,   # not stored in flat format
        'car':            car_name or car_class_name or '',
        'car_name':       car_name,
        'car_class':      car_class,
        'car_class_name': car_class_name,
        'session_type':   session_type,
        'session_subtype': '',    # flat format predates subtypes
        'driver_name':    '',     # not stored in flat format
        'game':           game,
        'game_name':      GAME_NAMES.get(game, game),
        'weather':        '',     # not stored in flat format
        'air_temp':       None,
        'track_temp':     None,
        'best_lap_time':  best_lap,
        'best_s1':        best_s1,
        'best_s2':        best_s2,
        'best_s3':        best_s3,
        'race_time':      None,   # no standings in flat format
        'position':       _int(timed[-1][1], 'position'),
        'start_position': None,   # no grid rows in flat format
        'lap_count':      len(timed),
        'distance_m':     None,   # flat format stores no track name
        **_scan_facts(timed, session_type=session_type),
    }


# ---------------------------------------------------------------------------
# Typed-row parsing (mirrors the reference snippet in session-log-format.md)
# ---------------------------------------------------------------------------

def _parse_typed_rows(csv_text):
    meta      = {}
    grid      = []
    lap_rows  = []
    standings = []
    events    = []
    summary   = {}
    debrief   = {}
    focus     = None   # driver-selected focus id from the F row
    objectives = []    # tracked objectives (O rows) — see sessionlog.objectives
    paths     = {}   # lap_num -> [offset metres per station] from P rows
    gh = hh = rh = eh = []

    reader = csv.reader(io.StringIO(csv_text.strip()))
    for row in reader:
        if not row:
            continue
        t = row[0]
        if   t == "S":  meta[row[1]] = row[2]
        elif t == "D" and len(row) >= 3:
            debrief[row[1]] = row[2]
        elif t == "F" and len(row) >= 2:
            focus = row[1]
        elif t == "O" and len(row) >= 2:
            # Tracked objective: O,<type>,<target>,<baseline>. Stored raw
            # (like debrief D rows) — sessionlog.objectives interprets the
            # target/baseline strings per type when it evaluates them.
            objectives.append({
                "type":     row[1],
                "target":   row[2] if len(row) >= 3 else "",
                "baseline": row[3] if len(row) >= 4 else "",
            })
        elif t == "GH": gh = row[1:]
        elif t == "H":  hh = row[1:]
        elif t == "RH": rh = row[1:]
        elif t == "EH": eh = row[1:]
        elif t == "G":  grid.append(dict(zip(gh, row[1:])))
        elif t == "L":  lap_rows.append(dict(zip(hh, row[1:])))
        elif t == "R":  standings.append(dict(zip(rh, row[1:])))
        elif t == "E":  events.append(dict(zip(eh, row[1:])))
        elif t == "Z":  summary[row[1]] = row[2]
        elif t == "P":  paths[_path_lap_num(row)] = _path_offsets(row)
        # silently ignore unknown row types

    return (meta, grid, lap_rows, standings, events, summary, debrief,
            focus, objectives, paths)


def _path_lap_num(row):
    """Lap number from a P row (P,lap_num,o0,o1,…), or None."""
    try:
        return int(row[1])
    except (IndexError, ValueError):
        return None


def _path_offsets(row):
    """A P row's stored decimetre offsets converted to signed metres per
    station; malformed cells are dropped (they never carry left/right meaning)."""
    out = []
    for cell in row[2:]:
        try:
            out.append(int(cell) / 10.0)
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_started_at(value):
    """Parse S.started_at ('2026-06-17T14:30:00') → datetime, or None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_filename(filename):
    """
    Extract (datetime, session_type, session_subtype) from
    'session_YYYYMMDD_HHMM_<label>.csv'. Fallback only — the S rows are
    preferred. <label> is the subtype when the session has one
    ('sprint_qualifying'), else the type; a numeric collision suffix
    ('..._race_2.csv') is stripped. Unknown labels are returned as the
    session_type with an empty subtype.
    """
    import re
    m = re.match(r"session_(\d{8})_(\d{4})_(.+?)(?:_\d+)?\.csv", filename)
    if not m:
        return None, None, None
    date_part, time_part, label = m.groups()
    if label in SESSION_SUBTYPE_TYPES:
        session_type, subtype = SESSION_SUBTYPE_TYPES[label], label
    else:
        session_type, subtype = label, ""
    try:
        date = datetime.strptime(date_part + time_part, "%Y%m%d%H%M")
    except ValueError:
        date = None
    return date, session_type, subtype


def _remove_rewinds(lap_rows):
    """
    Remove consecutive duplicate lap numbers (glitch deduplication).

    Only drops a row when its lap_num is identical to the immediately preceding
    row — this catches the Pi occasionally double-logging a lap.  It does NOT
    drop rows when the counter resets (e.g. 13 → 1 between qualifying runs),
    so multiple stints in one session are preserved.
    """
    clean = []
    prev_num = None
    for row in lap_rows:
        try:
            num = int(row.get("lap_num", ""))
        except (ValueError, TypeError):
            continue
        if num != prev_num:
            clean.append(row)
        prev_num = num
    return clean


def _build_events(event_rows):
    events = []
    for row in event_rows:
        lap_num  = _int(row,   "lap_num")
        lap_time = _float(row, "lap_time")
        etype    = _str(row,   "type")
        distance = _float(row, "distance")
        t        = _float(row, "t")
        detail   = _str(row,   "detail")
        if lap_num is not None and lap_time is not None and etype:
            events.append({"lap_num": lap_num, "lap_time": lap_time,
                           "type": etype, "distance": distance, "t": t,
                           "detail": detail})
    return events


def penalty_detail(detail):
    """
    Split a penalty event's detail string
    ('penalty_type:infringement[:other_driver]', v0.1.135+) into
    {'penalty': str|None, 'infringement': str|None, 'driver': str|None}
    with underscores humanised to spaces in the first two (the driver
    name is kept as broadcast). All None for an empty/missing detail.
    """
    parts = [p.strip() for p in (detail or "").split(":")]
    def _word(i):
        return (parts[i].replace("_", " ")
                if len(parts) > i and parts[i] else None)
    return {
        "penalty":      _word(0),
        "infringement": _word(1),
        "driver":       (parts[2] if len(parts) > 2 and parts[2] else None),
    }


def _rewinds_reliable(has_t_column, event_types):
    """
    Whether the file's rewind/restart data can be trusted. Files written
    before dashboard v0.1.133 logged spurious rewind/restart events around
    pit stops and garage visits, and bumped the per-lap rewinds column
    with them. The E-row `t` column arrived in the same release, so its
    presence marks a fixed file; without it, the data is only safe when
    there are no pit events for the spurious detections to cluster around.
    """
    return has_t_column or not any(t in ("pit_in", "pit_out")
                                   for t in event_types)


def _build_lap(row):
    invalid_val = _int(row, "invalid")
    rewinds_val = _int(row, "rewinds") or 0
    return {
        "num":            _int(row,   "lap_num"),
        "time":           _float(row, "lap_time"),
        "s1":             _float(row, "s1"),
        "s2":             _float(row, "s2"),
        "s3":             _float(row, "s3"),
        "valid":          invalid_val != 1,
        "rewinds":        rewinds_val,
        "restarts":       0,   # filled in from restart events in _parse_typed
        "lap_flag":       None,
        "s1_flag":        None,
        "s2_flag":        None,
        "s3_flag":        None,
        "position":       _int(row,   "position"),
        "tyre_compound":  _str(row,   "tyre_compound"),
        "fuel_remaining": _float(row, "fuel_remaining"),
        "fuel_per_lap":   _float(row, "fuel_per_lap"),
        "delta":          None,   # always recomputed by _apply_flags, below
        "tyre_fl":        _float(row, "tyre_fl"),
        "tyre_fr":        _float(row, "tyre_fr"),
        "tyre_rl":        _float(row, "tyre_rl"),
        "tyre_rr":        _float(row, "tyre_rr"),
        "assist_tc":            _int(row, "assist_tc"),
        "assist_abs":           _int(row, "assist_abs"),
        "assist_racing_line":   _int(row, "assist_racing_line"),
        "assist_steering":      _int(row, "assist_steering"),
        "assist_braking":       _int(row, "assist_braking"),
        "assist_gearbox":       _int(row, "assist_gearbox"),
        "assist_pit":           _int(row, "assist_pit"),
        "assist_pit_release":   _int(row, "assist_pit_release"),
        "assist_ers":           _int(row, "assist_ers"),
        "assist_drs":           _int(row, "assist_drs"),
    }


def _apply_flags(laps):
    """
    Assign lap_flag and s1/s2/s3_flag to each lap in-place.

    lap_flag  — "magenta" (session best) | "purple" (PB at the time) | "red" (invalid) | None
    sector flags — "magenta" | "purple" | "green" (≤ GREEN_THRESHOLD off best)
                   | "yellow" (≥ YELLOW_THRESHOLD off best) | None
    """
    def _is_clean(lap):
        return lap["valid"] and not lap.get("rewinds", 0)

    valid_timed = [lap for lap in laps if lap["time"] is not None and _is_clean(lap)]
    if not valid_timed:
        for lap in laps:
            lap["lap_flag"] = "red" if not lap["valid"] else None
            lap["delta"] = None   # no clean lap yet — nothing to compare against
        return laps, None

    best_lap_time = min(lap["time"] for lap in valid_timed)
    running_best = float("inf")
    for lap in laps:
        # Delta vs the best CLEAN lap so far — recomputed here rather than
        # trusted from the stored CSV column, so a fix to this logic (or a
        # session recorded before one existed, e.g. pre-v0.44.0 files with
        # the live-telemetry-race-condition bug) is retroactive without
        # rewriting old CSVs, matching how best_lap_time/clean_lap_count
        # etc. are already recomputed from raw laps rather than trusted as
        # stored aggregates. running_best is read here BEFORE this lap can
        # update it, so an invalid/rewound lap still gets a delta (vs the
        # current clean best) without ever becoming the new best itself.
        if lap["time"] is not None and running_best < float("inf"):
            lap["delta"] = round(lap["time"] - running_best, 3)
        else:
            lap["delta"] = None

        if not lap["valid"]:
            lap["lap_flag"] = "red"
            continue
        if lap.get("rewinds", 0):
            lap["lap_flag"] = None  # game-valid; ↺ in lap column flags the rewind
            continue
        if lap["time"] is None:
            lap["lap_flag"] = None
            continue
        if lap["time"] == best_lap_time:
            lap["lap_flag"] = "magenta"
        elif running_best < float("inf") and lap["time"] < running_best:
            lap["lap_flag"] = "purple"
        elif lap["time"] <= best_lap_time + _GREEN_THRESHOLD:
            lap["lap_flag"] = "green"
        elif lap["time"] >= best_lap_time + _YELLOW_THRESHOLD:
            lap["lap_flag"] = "yellow"
        else:
            lap["lap_flag"] = None
        running_best = min(running_best, lap["time"])

    for key in ("s1", "s2", "s3"):
        flag_key = f"{key}_flag"
        sector_times = [lap[key] for lap in laps if lap[key] is not None and _is_clean(lap)]
        if not sector_times:
            for lap in laps:
                lap[flag_key] = None
            continue
        best = min(sector_times)
        running_best = float("inf")
        for lap in laps:
            if not _is_clean(lap):
                lap[flag_key] = None
                continue
            val = lap[key]
            if val is None:
                lap[flag_key] = None
                continue
            if val == best:
                flag = "magenta"
            elif running_best < float("inf") and val < running_best:
                flag = "purple"
            elif val <= best + _GREEN_THRESHOLD:
                flag = "green"
            elif val >= best + _YELLOW_THRESHOLD:
                flag = "yellow"
            else:
                flag = None
            lap[flag_key] = flag
            running_best = min(running_best, val)

    return laps, best_lap_time


def _empty_session(filename):
    date, session_type, session_subtype = _parse_filename(filename)
    return {
        "filename": filename, "date": date,
        "track": None, "track_name": "", "track_location": None, "layout": None,
        "car": "", "car_name": None, "car_class": "", "car_class_name": "",
        "session_type": session_type or "",
        "session_subtype": session_subtype or "",
        "game": "", "game_name": "",
        "weather": "", "air_temp": None, "track_temp": None,
        "best_lap_time": None, "laps": [], "events": [], "grid": [], "standings": [],
        "summary": {}, "debrief": {}, "focus": None, "objectives": [],
        "rewinds_reliable": True,
    }


# ---------------------------------------------------------------------------
# Row field extractors
# ---------------------------------------------------------------------------

def _float(row, key):
    v = row.get(key, "").strip()
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _int(row, key):
    v = row.get(key, "").strip()
    try:
        return int(v) if v else None
    except ValueError:
        return None


def _str(row, key):
    v = row.get(key, "").strip()
    return v if v else None
