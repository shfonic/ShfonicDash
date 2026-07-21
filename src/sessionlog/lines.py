"""Shfonic Dash sessionlog — racing-line adherence (shared library; canonical
home is ShfonicDash/src/sessionlog/, vendored into the companion by
sync_shared.py — see the package docstring).

During an F1 session at a mapped track, the dashboard records how far the player
drove from the recorded racing line as a per-station **offset profile**
(signed metres, right of travel +; see core.geometry for the sign convention),
written to the CSV as ``P`` rows. This module turns those raw profiles into
coaching:

* ``lap_adherence`` — how tightly one lap held the line *in the corner zones*
  (straights are ignored, so a wide entry onto a straight isn't punished).
* ``session_line_facts`` — the per-session summary the records index and the
  ``on_the_line`` achievement read (was this a clean-line session?).
* ``line_notes_detailed`` — Race Engineer Note lines for the worst corner
  excursions and for where invalid laps left the line.
* ``player_line_geometry`` — pure data (two polylines + fit box) for the
  player-vs-racing mini-map, drawn per-app (pygame on the Pi, ui on the phone).

Pure standard library only — the offsets are metres and the geometry is plain
lists, so the same numbers come out on the Pi and in the companion.
"""

import math

from . import trackmap

# Tolerances (metres). Corner-zone mean at/under _ON_LINE_CORNER_AVG_M reads as
# "on the line"; a single corner over _FLAG_CORNER_M is worth a note.
_ON_LINE_CORNER_AVG_M = 1.0
_FLAG_CORNER_M = 1.5

# A "push lap" is a valid lap within this fraction of the session's best valid
# lap — a genuine flying attempt, not an out/in/cool-down lap (which drift off
# the line for reasons that aren't a coaching signal).
_PUSH_BAND = 1.03

# Multi-lap (hotlap) sessions need this many on-line laps to count as a clean
# line session; one-shot qualifying is judged on all its push laps instead.
_ON_LINE_MIN_LAPS = 3

_CORNER_TYPES = ('corner', 'chicane', 'complex')


def _corner_stations(n, sections, track_length):
    """The set of station indices (0..n-1) that fall inside a corner/chicane/
    complex section — the zones where holding the line matters. Empty when the
    map has no such sections."""
    if not sections or not track_length or track_length <= 0 or n <= 0:
        return set()
    out = set()
    for i in range(n):
        dist = i * track_length / n
        sec = trackmap.locate_section(dist, sections, track_length)
        if sec is not None and sec.get('type') in _CORNER_TYPES:
            out.add(i)
    return out


def lap_adherence(offsets_m, sections, track_length, corner_idx=None):
    """How tightly one lap held the racing line through the corners.

    ``offsets_m`` is the signed per-station offset in metres. Returns
    ``{corner_avg, corner_max, on_line, worst}`` where ``worst`` is
    ``[{label, distance, offset_m}]`` for the corner sections with the largest
    excursion (most off-line first). Returns ``None`` when there are no offsets
    or no corner stations to judge (map without labelled corners)."""
    if not offsets_m:
        return None
    n = len(offsets_m)
    idx = corner_idx if corner_idx is not None else _corner_stations(
        n, sections, track_length)
    idx = [i for i in idx if 0 <= i < n]
    if not idx:
        return None
    mags = [abs(offsets_m[i]) for i in idx]
    corner_avg = sum(mags) / len(mags)
    corner_max = max(mags)

    # Worst excursion per labelled corner section (for the notes).
    per_section = {}
    for i in idx:
        dist = i * track_length / n
        sec = trackmap.locate_section(dist, sections, track_length)
        if sec is None:
            continue
        label = trackmap.section_label(sec)
        mag = abs(offsets_m[i])
        cur = per_section.get(label)
        if cur is None or mag > cur['offset_m']:
            per_section[label] = {'label': label, 'distance': dist,
                                  'offset_m': mag}
    worst = sorted(per_section.values(), key=lambda w: -w['offset_m'])
    return {'corner_avg': corner_avg, 'corner_max': corner_max,
            'on_line': corner_avg <= _ON_LINE_CORNER_AVG_M, 'worst': worst}


def _lap_invalid(lap):
    """Whether a parsed lap was flagged invalid, tolerant of both row shapes:
    the typed parser stores ``valid`` (bool), the legacy flat parser stores
    ``invalid``. Reading only ``invalid`` silently marked every typed-format lap
    valid — the bug that hid the invalid badge in the session line viewer."""
    if lap.get('invalid') is not None:
        return bool(lap.get('invalid'))
    return lap.get('valid') is False


def _profiled_laps(session):
    """Completed laps that carry a line-offset profile, as
    ``[{num, time, invalid, s1, s2, s3, offsets}]`` (offsets in metres, sector
    times in seconds or None). Empty when the session has no ``P`` rows."""
    out = []
    for lap in session.get('laps') or []:
        offs = lap.get('line_offsets')
        if offs:
            out.append({'num': lap.get('num'), 'time': lap.get('time'),
                        'invalid': _lap_invalid(lap),
                        's1': lap.get('s1'), 's2': lap.get('s2'),
                        's3': lap.get('s3'), 'offsets': offs})
    return out


def session_line_facts(session, track_map):
    """Per-session racing-line summary for the index / achievement, or an
    all-zero record when there is no line data.

      {'push_lap_count', 'on_line_lap_count', 'on_line_session', 'best_line_dev'}

    A push lap is a valid lap within ``_PUSH_BAND`` of the session's best valid
    lap. ``on_line_session`` is the achievement gate: hotlap needs
    ``_ON_LINE_MIN_LAPS`` on-line laps; qualifying needs at least one push lap
    with *every* push lap on-line (so a one-shot quali still qualifies)."""
    empty = {'push_lap_count': 0, 'on_line_lap_count': 0,
             'on_line_session': False, 'best_line_dev': None}
    if not track_map:
        return empty
    laps = _profiled_laps(session)
    if not laps:
        return empty
    sections = track_map.get('sections') or []
    track_length = track_map.get('game_track_length_m') or 0.0
    n = max(len(lap['offsets']) for lap in laps)
    corner_idx = _corner_stations(n, sections, track_length)
    if not corner_idx:
        return empty

    valid = [lap for lap in laps if not lap['invalid'] and lap['time']]
    best_valid = min((lap['time'] for lap in valid), default=None)

    push_count = on_line_count = 0
    best_dev = None
    for lap in laps:
        adh = lap_adherence(lap['offsets'], sections, track_length, corner_idx)
        if adh is None:
            continue
        if best_dev is None or adh['corner_avg'] < best_dev:
            best_dev = adh['corner_avg']
        is_push = (not lap['invalid'] and lap['time'] and best_valid
                   and lap['time'] <= best_valid * _PUSH_BAND)
        if is_push:
            push_count += 1
            if adh['on_line']:
                on_line_count += 1

    session_type = (session.get('session_type') or '').strip().lower()
    if session_type == 'qualifying':
        on_line_session = push_count >= 1 and on_line_count == push_count
    else:
        on_line_session = on_line_count >= _ON_LINE_MIN_LAPS

    return {'push_lap_count': push_count, 'on_line_lap_count': on_line_count,
            'on_line_session': on_line_session,
            'best_line_dev': round(best_dev, 2) if best_dev is not None else None}


def _best_clean_profiled(laps):
    """The fastest valid profiled lap (most representative of the driver's
    intended line), or the fastest profiled lap if none are valid."""
    valid = [lap for lap in laps if not lap['invalid'] and lap['time']]
    pool = valid or [lap for lap in laps if lap['time']]
    return min(pool, key=lambda lap: lap['time']) if pool else None


def best_line_offsets(session):
    """The offset profile (metres per station) of the session's fastest clean
    profiled lap — the driver's most representative line, for the mini-map — or
    ``None`` when the session recorded no line data."""
    best = _best_clean_profiled(_profiled_laps(session))
    return best['offsets'] if best else None


def corner_deviations(session, track_map):
    """``{corner_label: offset_m}`` — how far the driver's most representative
    line (the fastest clean profiled lap) strayed from the racing line at each
    labelled corner. ``{}`` without line data, a map, or labelled corners.

    The single source the pre-session line hotspot (line_hotspot) and the
    ``corner_line`` objective's follow-up (sessionlog.objectives) both read, so
    the goal that's set and the goal that's scored measure the same thing.
    """
    if not track_map:
        return {}
    best = _best_clean_profiled(_profiled_laps(session))
    if not best:
        return {}
    sections = track_map.get('sections') or []
    track_length = track_map.get('game_track_length_m') or 0.0
    adh = lap_adherence(best['offsets'], sections, track_length)
    if not adh:
        return {}
    return {w['label']: w['offset_m'] for w in adh['worst']}


def line_hotspot(session, track_map, min_offset=_FLAG_CORNER_M):
    """The corner where the driven line strayed most, for the pre-session
    "tighten your line here" goal — ``{'label', 'offset_m', 'distance'}`` or
    ``None`` when there's no line data or nothing strayed past ``min_offset``
    (a corner basically on the line isn't worth a mission)."""
    if not track_map:
        return None
    best = _best_clean_profiled(_profiled_laps(session))
    if not best:
        return None
    sections = track_map.get('sections') or []
    track_length = track_map.get('game_track_length_m') or 0.0
    adh = lap_adherence(best['offsets'], sections, track_length)
    if not adh or not adh['worst']:
        return None
    w = adh['worst'][0]
    if w['offset_m'] < min_offset:
        return None
    return {'label': w['label'], 'offset_m': round(w['offset_m'], 1),
            'distance': w['distance']}


# Map-marker kinds and the raw event → marker classification. The viewer draws
# a distinct icon per kind (red cross / contact burst / blue flashback), so the
# driver can see *where* on the lap each incident happened.
_EVENT_MERGE_M = 25.0   # events this close (same kind) collapse to one marker


def _classify_map_event(ev):
    """Map an ``E``-row event to a marker kind (``track_limit`` / ``contact`` /
    ``flashback``), or ``None`` for events that don't belong on the map (pit
    in/out, speeding penalties, restarts…)."""
    etype = ev.get('type')
    if etype == 'rewind':
        return 'flashback'
    if etype == 'collision':
        return 'contact'
    if etype in ('invalid', 'track_limit_warning'):
        return 'track_limit'
    if etype == 'penalty':
        from . import parser  # lazy: parser imports lines at module load
        infr = (parser.penalty_detail(ev.get('detail')).get('infringement')
                or '').lower()
        if 'collision' in infr:
            return 'contact'
        if ('wide' in infr or 'track limit' in infr or 'corner cut' in infr
                or 'cutting' in infr):
            return 'track_limit'
    return None


def map_events(session, track_map=None):
    """Incident markers for the session line viewer, one per corner per kind:
    ``[{'distance', 'kind', 'lap_num', 'laps'[, 'drivers']}]`` sorted along the
    lap, where ``laps`` is every lap that contributed to that marker (so a
    consolidated marker can list them all in its tooltip) and ``lap_num`` is the
    earliest. Contact markers also carry ``drivers`` — the other cars involved,
    so the tooltip can say who the contact was with.

    Sources, unioned so the map mirrors the engineering notes:

    * **Track limits** — raw ``invalid`` / running-wide ``penalty`` events, plus
      (with a ``track_map``) each invalid lap's worst off-line corner. The game
      often logs the *penalty* at a different point from where the driver ran
      wide, so the off-line corner catches incidents the notes call out ("Lap 7
      invalidated near Fagnes") that the raw events miss.
    * **Contact / flashback** — from :func:`pace.contact_incidents`, which
      groups collision→rewind chains into incidents at the first contact's
      distance. Rewind (``E``-row) events carry no distance of their own, so a
      flashback marker is placed at the contact it undid — that's why a contact
      and its flashback share a corner (the viewer fans them so both show).

    Markers of the same kind in the same labelled corner collapse to one; away
    from corners a ``_EVENT_MERGE_M`` distance merge applies."""
    sections = (track_map or {}).get('sections') or []
    track_length = (track_map or {}).get('game_track_length_m') or 0.0

    def _corner_key(dist):
        """The labelled corner a distance sits in (``None`` on a straight / with
        no map) — the unit markers dedupe by, so one marker per corner."""
        if sections and track_length:
            sec = trackmap.locate_section(dist, sections, track_length)
            if sec is not None and sec.get('type') in _CORNER_TYPES:
                return trackmap.section_label(sec)
        return None

    order = []
    index = {}

    def _add(dist, kind, lap_num, drivers=None):
        if dist is None or kind is None:
            return
        ck = _corner_key(dist)
        key = (kind, ck) if ck is not None else (kind, round(dist / _EVENT_MERGE_M))
        m = index.get(key)
        if m is None:
            m = {'distance': dist, 'kind': kind, 'laps': set(), 'drivers': []}
            index[key] = m
            order.append(m)
        if lap_num is not None:
            m['laps'].add(lap_num)
        for name in drivers or []:
            if name and name not in m['drivers']:
                m['drivers'].append(name)

    # Track limits.
    for ev in session.get('events') or []:
        if _classify_map_event(ev) == 'track_limit':
            _add(ev.get('distance'), 'track_limit', ev.get('lap_num'))
    if track_map:
        for lap in _profiled_laps(session):
            if not lap['invalid']:
                continue
            adh = lap_adherence(lap['offsets'], sections, track_length)
            if adh and adh['worst'] and adh['worst'][0]['offset_m'] >= _FLAG_CORNER_M:
                _add(adh['worst'][0]['distance'], 'track_limit', lap['num'])

    # Contacts and flashbacks (rewinds have no distance — placed at the contact).
    from . import pace  # lazy: pace imports lines at module load
    for inc in pace.contact_incidents(session.get('events') or []):
        d = inc.get('distance')
        if d is None:
            continue
        _add(d, 'contact', inc.get('lap_num'), inc.get('drivers'))
        if inc.get('rewound'):
            _add(d, 'flashback', inc.get('lap_num'))

    for m in order:
        m['laps'] = sorted(m['laps'])
        m['lap_num'] = m['laps'][0] if m['laps'] else None
        if not m['drivers']:
            del m['drivers']   # only contacts (with named drivers) carry them
    order.sort(key=lambda m: m['distance'])
    return order


def _resolve_racing_line(track_map, car_class):
    """The racing line to draw a session against: the driven class's own line,
    falling back to any class that has one (so a race in a class without its own
    recorded line still gets the shared circuit line). ``[]`` when the map has no
    line at all. Mirrors the viewer's own resolution so both draw the same line."""
    lines_map = (track_map or {}).get('lines') or {}
    entry = lines_map.get(car_class) if car_class else None
    if not (entry and entry.get('racing_line')):
        entry = next((e for e in lines_map.values()
                      if e and e.get('racing_line')), None)
    return (entry or {}).get('racing_line') or []


def _pos_at_distance(line, dist, length):
    """The [x, z] point ``dist`` metres along a racing line of total ``length``
    (linear interpolation between the evenly-spaced stations). ``None`` when the
    line is empty or the length is unknown."""
    if not line or not length or length <= 0:
        return None
    f = min(max(dist / length, 0.0), 1.0)
    idx = f * (len(line) - 1)
    i = int(idx)
    t = idx - i
    a = line[i]
    b = line[min(i + 1, len(line) - 1)]
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]


def lap_offsets_map(session):
    """``{lap_num: offsets}`` for every profiled lap — the per-lap offset
    profiles keyed by lap number, so a renderer can place an incident marker on
    the driven line of the lap it actually happened on. ``{}`` without line data."""
    return {lap['num']: lap['offsets'] for lap in _profiled_laps(session)
            if lap['num'] is not None}


def _driven_line(racing, normals, offsets):
    """Reconstruct a driven polyline from a racing line + its normals + a per-
    station offset profile (``racing[i] + offset·normal[i]``). ``None`` when the
    profile is too short to draw."""
    n = min(len(racing), len(offsets))
    if n < 2:
        return None
    return [[racing[i][0] + offsets[i] * normals[i][0],
             racing[i][1] + offsets[i] * normals[i][1]] for i in range(n)]


def session_map_geometry(track_map, car_class, events=None, offsets=None,
                         lap_offsets=None):
    """Pure geometry for a **session map thumbnail / overview**, drawn per-app
    (ui on the phone, pygame on the Pi) — the native counterpart of the browser
    viewer, which computes the same positions itself:

      {'racing': [[x, z], …],            # the class racing line
       'player': [[x, z], …] | None,     # reconstructed driven line (if offsets)
       'events': [{'pos':[x,z], 'kind', 'lap_num'}, …],   # markers, placed by dist
       'bounds': (minx, minz, maxx, maxz)}

    ``offsets`` is the one line drawn as ``player`` (typically the best lap).
    ``lap_offsets`` (``{lap_num: offsets}``, from :func:`lap_offsets_map`) places
    each incident marker on **the driven line of the lap it happened on** rather
    than the ideal racing line — so a contact shows where the car actually was,
    not where it should have been. An event whose lap has no profile (races /
    practice, or an unprofiled lap) falls back to the racing line.

    Works with no ``offsets`` (races / practice — just the circuit and where the
    incidents happened) and with no ``events``. ``None`` when the map has no
    racing line to draw."""
    racing = _resolve_racing_line(track_map, car_class)
    if len(racing) < 2:
        return None
    racing = [list(p) for p in racing]
    normals = _right_normals(racing)
    player = _driven_line(racing, normals, offsets) if offsets else None

    length = (track_map or {}).get('game_track_length_m') or 0.0
    driven_cache = {}

    def _line_for_lap(lap_num):
        """The driven line for a lap (cached), or the racing line as fallback."""
        if lap_num not in driven_cache:
            offs = (lap_offsets or {}).get(lap_num)
            driven_cache[lap_num] = (_driven_line(racing, normals, offs)
                                     if offs else None)
        return driven_cache[lap_num] or racing

    ev_out = []
    for ev in events or []:
        dist = ev.get('distance')
        if dist is None:
            continue
        pos = _pos_at_distance(_line_for_lap(ev.get('lap_num')), dist, length)
        if pos:
            ev_out.append({'pos': pos, 'kind': ev.get('kind'),
                           'lap_num': ev.get('lap_num')})
    # Cosmetic display rotation (see trackmap.orientation_deg): turn the racing
    # line, the driven line and every marker together so the overview matches.
    deg = trackmap.orientation_deg(track_map)
    if deg:
        racing = trackmap.rotate_xz(racing, deg)
        if player:
            player = trackmap.rotate_xz(player, deg)
        for ev in ev_out:
            ev['pos'] = trackmap.rotate_xz([ev['pos']], deg)[0]
    return {'racing': racing, 'player': player, 'events': ev_out,
            'bounds': trackmap._bounds_of(racing, player or [])}


def session_line_export(session, track_map):
    """Package a parsed session and its track map into the data object the HTML
    **session line viewer** consumes (``session_viewer.html`` in the
    ShfonicDashTracks repo): the full track map, every profiled lap's offset
    profile and sector times, and the session's incident markers, so the viewer
    can overlay each driven line against the racing line, filter laps, and show
    where events happened.

      {'track':      <track map dict, unchanged>,
       'car_class':  <driven class — which racing line to compare against>,
       'session':    {'title', 'session_type', 'game', 'track'},
       'best_num':   <lap number of the fastest clean profiled lap, or None>,
       'laps':       [{'num', 'time', 'invalid', 's1', 's2', 's3', 'offsets'}, …],
       'events':     [{'distance', 'kind', 'lap_num'}, …]}   # offsets: metres

    Returned for **any** session with a recorded racing line, not just the F1
    hotlap/qualifying ones that carry per-lap profiles — a race or practice with
    no ``laps`` still shows the circuit and its incident markers (``events``),
    which is the point of the map for races. ``None`` only when there is no track
    map or the map has no racing line to draw against. Sector times drive the
    wide-screen sector columns and theoretical-best highlighting; the viewer does
    the driven-line reconstruction itself (same ``racing_line[i] + offset·normal[i]``
    as :func:`player_line_geometry`), so the Pi, the companion and the browser
    all draw the identical line."""
    if not track_map or not _resolve_racing_line(track_map, session.get('car_class')):
        return None
    laps = _profiled_laps(session)
    best = _best_clean_profiled(laps)
    return {
        'track': track_map,
        'car_class': session.get('car_class'),
        'session': {
            'title': session.get('car_class_name') or session.get('car_class'),
            'session_type': session.get('session_type'),
            'game': session.get('game'),
            'track': session.get('track'),
        },
        'best_num': best['num'] if best else None,
        'laps': [{'num': lap['num'], 'time': lap['time'],
                  'invalid': lap['invalid'], 's1': lap['s1'], 's2': lap['s2'],
                  's3': lap['s3'], 'offsets': lap['offsets']}
                 for lap in laps],
        'events': map_events(session, track_map),
    }


def line_notes_detailed(session, track_map):
    """Race Engineer Note entries about the racing line, in the
    ``pace.race_engineer_notes_detailed`` shape
    (``{text, locations:[{label, distance, kind, rewound}]}``, ``kind='off_line'``)
    so they render with corner thumbnails. Empty without line data / a map."""
    if not track_map:
        return []
    laps = _profiled_laps(session)
    if not laps:
        return []
    sections = track_map.get('sections') or []
    track_length = track_map.get('game_track_length_m') or 0.0

    notes = []
    best = _best_clean_profiled(laps)
    if best is not None:
        adh = lap_adherence(best['offsets'], sections, track_length)
        if adh:
            # Focus on the single worst offender rather than listing every wide
            # corner — a driver who is off everywhere gets one actionable note,
            # not a wall of them. The tail names how many corners were off so
            # the breadth isn't lost.
            flagged = [w for w in adh['worst'] if w['offset_m'] >= _FLAG_CORNER_M]
            if flagged:
                w = flagged[0]
                tail = ("" if len(flagged) == 1 else
                        ", the widest of %d corners off the line" % len(flagged))
                notes.append({
                    'text': "Ran wide at %s — about %.1f m off the racing line%s."
                            % (w['label'], w['offset_m'], tail),
                    'locations': [{'label': w['label'], 'distance': w['distance'],
                                   'kind': 'off_line', 'rewound': False}]})

    # Where an invalid lap left the line — the single worst excursion across all
    # invalid laps (one note, the biggest offender, not one per invalid lap).
    worst_invalid = None
    for lap in laps:
        if not lap['invalid']:
            continue
        adh = lap_adherence(lap['offsets'], sections, track_length)
        if not adh or not adh['worst']:
            continue
        w = adh['worst'][0]
        if w['offset_m'] < _FLAG_CORNER_M:
            continue
        if worst_invalid is None or w['offset_m'] > worst_invalid[1]['offset_m']:
            worst_invalid = (lap['num'], w)
    if worst_invalid is not None:
        num, w = worst_invalid
        notes.append({
            'text': "Lap %s invalidated near %s, about %.1f m off the line."
                    % (num, w['label'], w['offset_m']),
            'locations': [{'label': w['label'], 'distance': w['distance'],
                           'kind': 'off_line', 'rewound': False}]})

    return notes


# ---------------------------------------------------------------------------
# Mini-map geometry — reconstruct the driven line from the offset profile.
# ---------------------------------------------------------------------------

def _right_normals(line):
    """Unit right-hand normal (tangent rotated −90°, matching
    core.geometry.signed_offset) at each vertex of a closed racing line, from the
    central-difference tangent — so ``racing[i] + offset·normal[i]`` puts a driven
    point back on the side it was captured."""
    n = len(line)
    out = []
    for i in range(n):
        ax, az = line[(i - 1) % n]
        bx, bz = line[(i + 1) % n]
        tx, tz = bx - ax, bz - az
        mag = math.hypot(tx, tz) or 1.0
        out.append((tz / mag, -tx / mag))
    return out


def player_line_geometry(track_map, offsets_m, distance=None, half_window=None):
    """Data for the player-vs-racing mini-map: the racing line and the
    reconstructed driven line as two ``[[x, z], …]`` polylines plus a padded fit
    box.

      {'racing': [...], 'player': [...], 'bounds': (minx, minz, maxx, maxz)}

    With ``distance``/``half_window`` (metres) it returns just the slice around
    that lap distance — a zoomed corner crop reusing the same reconstruction, so
    the note thumbnails and the full-lap map share one code path. ``None`` when
    there is no usable geometry."""
    if not track_map or not offsets_m:
        return None
    lines = track_map.get('lines') or {}
    racing = None
    for entry in lines.values():
        rl = entry.get('racing_line')
        if rl:
            racing = rl
            break
    if not racing:
        return None
    n = min(len(racing), len(offsets_m))
    if n < 2:
        return None
    racing = [list(p) for p in racing[:n]]
    normals = _right_normals(racing)
    player = [[racing[i][0] + offsets_m[i] * normals[i][0],
               racing[i][1] + offsets_m[i] * normals[i][1]] for i in range(n)]

    length = track_map.get('game_track_length_m') or 0.0
    if distance is not None and half_window and length > 0:
        center = int(round((distance % length) / length * n)) % n
        half = max(1, int(round(half_window / (length / n))))
        idxs = [(center + k) % n for k in range(-half, half + 1)]
        racing = [racing[i] for i in idxs]
        player = [player[i] for i in idxs]

    deg = trackmap.orientation_deg(track_map)      # cosmetic display rotation
    if deg:
        racing = trackmap.rotate_xz(racing, deg)
        player = trackmap.rotate_xz(player, deg)
    return {'racing': racing, 'player': player,
            'bounds': trackmap._bounds_of(racing, player)}
