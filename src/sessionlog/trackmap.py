"""
Shfonic Dash sessionlog — locate a lap-distance against a track map's
labelled `sections`, turning "310m into the lap" into "Turn 3, before the
apex" for Race Engineer Notes and the AI share text.

Track maps are recorded by the Pi's track recorder (core/track_recorder.py)
and stored as one JSON file per track — see docs/track-format.md for the
on-disk shape. This module never writes them; it only reads whatever the
host app points it at via `set_tracks_dir()` (the Pi's `tracks/` directory,
or the companion's local track cache — same pattern as
`records.set_cache_dir()`). A missing directory, no matching file, or a
section-less map all degrade to `None` rather than raising — callers fall
back to their previous (distance-only) behaviour when this returns nothing.

Section type priority (corner/chicane > complex > straight/drs > other)
follows the driver's mental model: "which corner was I in" beats "which
straight", and a named complex (e.g. Maggots/Becketts/Chapel) is more
useful than the raw dump of every corner inside it — but a specific corner
membership still wins when one applies. Braking-zone / speed-based lookups
are a later addition once that coaching exists; the priority order leaves
room for it in `_TYPE_RANK`.
"""

import json
import math
import os

_TYPE_RANK = {
    'corner': 0, 'chicane': 0,
    'complex': 1,
    'straight': 2, 'drs': 2,
    'other': 3,
}

_APEX_TOLERANCE_M = 12.0   # within this many metres of apex_m -> "at the apex"


def orientation_deg(track_map):
    """The track's display rotation in degrees (0 = north-up, as recorded).

    A **cosmetic** field, editable in the map utility: it turns every top-down
    map view (Pi thumbnails, the web companion minimaps, the HTML viewers) to a
    more legible orientation without touching the recorded world coordinates.
    Because it only rotates the drawn geometry, arc-length distances, section
    lookups and gears are unaffected. Missing/garbage ⇒ 0.0."""
    try:
        return float((track_map or {}).get('orientation') or 0.0)
    except (TypeError, ValueError):
        return 0.0


def rotate_xz(points, deg):
    """Rotate ``[[x, z], …]`` points (or heading unit vectors — direction
    vectors rotate by the same transform) by ``deg`` degrees about the origin.

    A no-op for 0. Every map renderer re-fits the rotated geometry to its
    viewport (bounding-box centre), so the pivot only has to be consistent, not
    the centroid — the origin is fine and keeps this a one-liner shared by the
    Pi, the companion and the browser viewers alike."""
    if not deg:
        return [[p[0], p[1]] for p in points]
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    return [[p[0] * c - p[1] * s, p[0] * s + p[1] * c] for p in points]


def _bounds_of(*point_lists):
    """Padded (minx, minz, maxx, maxz) fit box over one or more point lists,
    with the same 8% pad the map helpers use. At least one non-empty list."""
    xs, zs = [], []
    for pl in point_lists:
        for p in pl:
            xs.append(p[0])
            zs.append(p[1])
    minx, maxx = min(xs), max(xs)
    minz, maxz = min(zs), max(zs)
    pad = 0.08 * max(maxx - minx, maxz - minz, 1.0)
    return (minx - pad, minz - pad, maxx + pad, maxz + pad)


_tracks_dir = None


def set_tracks_dir(path):
    """Point lookups at `path` (mirrors records.set_cache_dir)."""
    global _tracks_dir
    _tracks_dir = path


def tracks_dir():
    return _tracks_dir


def find_map(game, track):
    """The parsed track map for `game`/`track`, or None.

    Matches on the file's own `game`/`track` fields (case/whitespace
    insensitive) rather than guessing a filename slug, so it stays correct
    even if a file was renamed by hand. Never raises: a missing directory,
    unreadable file or no match all return None.
    """
    d = _tracks_dir
    if not d or not game or not track:
        return None
    game_l, track_l = game.strip().lower(), track.strip().lower()
    try:
        names = os.listdir(d)
    except OSError:
        return None
    for name in names:
        if not name.endswith('.json'):
            continue
        try:
            with open(os.path.join(d, name), encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if ((data.get('game') or '').strip().lower() == game_l
                and (data.get('track') or '').strip().lower() == track_l):
            return data
    return None


# Games where every car class drives the same racing line (F1/F2 differ by
# under a metre — recording noise). Lines are still stored PER CLASS so each
# class carries its own gears, but when a class has no profile yet any sibling's
# line is a valid stand-in. Games with real class variety (PC2/GT7/Forza) are
# absent, so a missing class there resolves to nothing rather than borrowing
# another class's line. Mirror `_LINE_GAMES` in core/session_logger.py.
_SHARED_LINE_GAMES = {"f1_25"}

# The classes a shared-line game's recorder seeds together — driving any ONE
# of these records a profile for all three (line copied, gears left null for
# the ones not actually driven). `formula1_classic` / `formula3` are excluded:
# real cars, not confirmed to share the current-season line.
_SHARED_LINE_CLASSES = {"f1_25": ("formula1", "formula1_2026", "f2")}


def sibling_classes(game):
    """The car classes that share one racing line for `game` — empty tuple if
    the game doesn't pool lines (see `_SHARED_LINE_GAMES`)."""
    return _SHARED_LINE_CLASSES.get(game, ())


def resolve_line(track_map, game, car_class):
    """The racing-line entry (`{racing_line, racing_attempts, gears, notes}`)
    for `game`+`car_class`, or ``{}``.

    Exact class match first; then, only for a shared-line game, any sibling
    entry that carries a line (they are the same line, so a class whose profile
    hasn't been filled in still gets geometry). Per-class gears always come from
    the class's own entry — read that directly, not via the fallback. Never
    raises.
    """
    lines = (track_map.get('lines') or {}) if track_map else {}
    entry = lines.get(car_class)
    if (not entry or not entry.get('racing_line')) and game in _SHARED_LINE_GAMES:
        for e in lines.values():
            if isinstance(e, dict) and e.get('racing_line'):
                entry = e
                break
    return entry or {}


def _station(distance_m, track_length_m):
    if track_length_m and track_length_m > 0:
        return distance_m % track_length_m
    return distance_m


def _signed_gap(a, b, track_length_m):
    """a - b, wrapped to (-L/2, L/2] when the track length is known."""
    d = a - b
    if track_length_m and track_length_m > 0:
        d = ((d + track_length_m / 2) % track_length_m) - track_length_m / 2
    return d


def _covers(section, station):
    start, end = section.get('start_m'), section.get('end_m')
    if start is None or end is None:
        return False
    if start <= end:
        return start <= station <= end
    return station >= start or station <= end   # wraps across S/F


def _span_length(section, track_length_m):
    start, end = section['start_m'], section['end_m']
    if start <= end:
        return end - start
    return (track_length_m - start + end) if track_length_m else float('inf')


def locate_section(distance_m, sections, track_length_m=None):
    """The most relevant labelled section covering `distance_m`, or None.

    Priority is corner/chicane, then complex, then straight/drs, then
    other (`_TYPE_RANK`); ties broken by the shortest covering span (the
    more specific label).
    """
    if distance_m is None or not sections:
        return None
    station = _station(distance_m, track_length_m)
    hits = [s for s in sections if _covers(s, station)]
    if not hits:
        return None
    hits.sort(key=lambda s: (_TYPE_RANK.get(s.get('type'), 9),
                              _span_length(s, track_length_m)))
    return hits[0]


def section_label(section):
    """Short name for a section dict, e.g. 'Turn 3' or 'Maggots/Becketts/Chapel'."""
    return (section.get('name') or
            (f"Turn {section['turn']}" if section.get('turn') else None) or
            (section.get('type') or 'this part of the track').replace('_', ' '))


# Sections used as landmarks when bracketing an unlabelled stretch — the named
# things a driver navigates by. Straights/DRS/other aren't landmarks (a gap
# between two corners is the very thing we're naming).
_LANDMARK_TYPES = ('corner', 'chicane', 'complex')


def bracket_corners(distance_m, sections, track_length_m=None):
    """The nearest named landmark (corner/chicane/complex) *before* and *after*
    `distance_m`, as `(prev, next)` section dicts — for describing a point that
    falls in an unlabelled gap ('between Turn 2 and Turn 4'). Returns None
    without two distinct landmarks to bracket it (so callers can stay silent).

    Bracketing is by lap distance and wraps across the start/finish line: prev
    is the landmark whose exit the car most recently passed, next the one whose
    entry it reaches soonest.
    """
    if distance_m is None or not sections:
        return None
    marks = [s for s in sections
             if s.get('type') in _LANDMARK_TYPES
             and s.get('start_m') is not None and s.get('end_m') is not None]
    if len(marks) < 2:
        return None
    L = track_length_m if (track_length_m and track_length_m > 0) else None
    station = _station(distance_m, track_length_m)

    def _fwd(a, b):
        """Forward distance from a to b around the lap (wraps when L known)."""
        d = b - a
        if L:
            return d % L
        return d if d >= 0 else float('inf')

    nxt = min(marks, key=lambda s: _fwd(station, s['start_m']))
    prv = min(marks, key=lambda s: _fwd(s['end_m'], station))
    if prv is nxt:
        return None
    return prv, nxt


def bracket_label(prev, nxt):
    """Compact caption for a bracketed thumbnail, e.g. 'T2–T4' or 'T13–Abbey'
    (turn number preferred over the full name to keep it short)."""
    def _short(s):
        if s.get('turn'):
            return f"T{s['turn']}"
        return s.get('name') or (s.get('type') or '?')
    return f"{_short(prev)}–{_short(nxt)}"


def describe_location(distance_m, sections, track_length_m=None):
    """Prepositional location phrase for `distance_m`, or None.

    Always includes its own leading preposition ('at Turn 3, before the
    apex' / 'on the Pit Straight') so callers can drop it straight into a
    sentence without knowing the section type. When no section covers the
    point, falls back to naming the corners it sits between ('between Turn 2
    and Turn 4') so a note never goes location-less on an unlabelled gap.
    """
    section = locate_section(distance_m, sections, track_length_m)
    if section is None:
        br = bracket_corners(distance_m, sections, track_length_m)
        if br:
            return f"between {section_label(br[0])} and {section_label(br[1])}"
        return None
    label = section_label(section)
    apex_m = section.get('apex_m')
    if section.get('type') in ('corner', 'chicane') and apex_m is not None:
        station = _station(distance_m, track_length_m)
        gap = _signed_gap(station, apex_m, track_length_m)
        if abs(gap) <= _APEX_TOLERANCE_M:
            return f"at the apex of {label}"
        return (f"at {label}, after the apex" if gap > 0
                else f"at {label}, before the apex")
    if section.get('type') in ('straight', 'drs'):
        prefix = "on " if label.lower().startswith('the ') else "on the "
        return f"{prefix}{label}"
    return f"at {label}"


_DEFAULT_HALF_WINDOW_M = 150.0


def crop_geometry(track_map, distance_m, half_window_m=_DEFAULT_HALF_WINDOW_M):
    """Geometry for a zoomed-in mini-map of the track around `distance_m`.

    Returns the *data* a renderer needs — this module stays free of any
    drawing toolkit (pygame on the Pi, `ui` on the companion each draw it):

      {'left':    [[x, z], …],  # slice of the left edge through the window
       'right':   [[x, z], …],  # matching slice of the right edge
       'marker':  [x, z],       # the event point (track centre at distance_m)
       'heading': [ux, uz],     # unit direction of travel at the marker, so a
                                #   renderer can draw a which-way arrow
       'bounds':  (minx, minz, maxx, maxz)}  # padded fit box for the slice

    None when there is no usable geometry: no map, no edges, no known track
    length (needed to map a lap distance to an edge station), or a bad
    distance. The edges are resampled to a common per-lap station grid (see
    docs/track-format.md), so left[i] and right[i] share a lap distance and
    the window is taken symmetrically in stations around `distance_m`. The
    window wraps across the start/finish line — the edge polylines are a
    closed loop, so station 0 and the last station are adjacent on track.
    """
    if not track_map or distance_m is None:
        return None
    left  = track_map.get('left_edge') or []
    right = track_map.get('right_edge') or []
    if not left or not right:
        return None
    length = track_map.get('game_track_length_m') or 0.0
    if length <= 0:
        return None
    n = min(len(left), len(right))
    station_m = length / n
    center = int(round((distance_m % length) / length * n)) % n
    half = max(1, int(round(half_window_m / station_m)))
    idxs = [(center + k) % n for k in range(-half, half + 1)]
    left_slice  = [list(left[i]) for i in idxs]
    right_slice = [list(right[i]) for i in idxs]

    def _centre(i):
        return ((left[i][0] + right[i][0]) / 2.0,
                (left[i][1] + right[i][1]) / 2.0)

    marker = list(_centre(center))
    # Direction of travel = the centreline tangent at the marker, taken
    # across the neighbouring stations (stations increase with lap distance,
    # so this points the way the car is going through the corner).
    prev_c = _centre((center - 1) % n)
    next_c = _centre((center + 1) % n)
    hx, hz = next_c[0] - prev_c[0], next_c[1] - prev_c[1]
    mag = math.hypot(hx, hz) or 1.0
    heading = [hx / mag, hz / mag]

    # Cosmetic display rotation (see orientation_deg): turn the drawn slice, the
    # marker and its heading vector together so the crop matches every other view.
    deg = orientation_deg(track_map)
    if deg:
        left_slice  = rotate_xz(left_slice, deg)
        right_slice = rotate_xz(right_slice, deg)
        marker  = rotate_xz([marker], deg)[0]
        heading = rotate_xz([heading], deg)[0]

    bounds = _bounds_of(left_slice, right_slice, [marker])
    return {'left': left_slice, 'right': right_slice,
            'marker': marker, 'heading': heading, 'bounds': bounds}
