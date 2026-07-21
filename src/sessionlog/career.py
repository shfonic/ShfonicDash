"""
Career form — the driver's overall recent-form grade across every game.

``grading.driver_profile()`` answers "who is the driver at ONE combo" (typical
pace + consistency). This answers a different question: "what grade is the
driver driving to *right now*, overall" — the headline on the driver card.

It is deliberately **recent form**, not a career average: the first fumbling
sessions of a beginner should not weigh down the number forever. The windowing,
trend rule and letter mapping live here (not in the UI) so the Pi dashboard and
the companion show the same grade.

Pure aggregation: the caller grades each session (``grading.grade(...)['score']``)
and passes ``{'date', 'game', 'score'}`` rows, newest first, with ungradable
sessions already dropped. Standard library only; unit-tested.

``personal_records()`` is the sibling that answers "what are the driver's best
career numbers" — the Personal Records ("chase statistics") shown on both apps'
driver profile. It takes the raw session_db rows (not graded) and derives each
stat from the indexed columns.
"""

from datetime import datetime

from sessionlog.grading import letter

# How many of the most-recent gradable sessions define "current form".
RECENT_N = 10

# Clean laps a session needs before its clean-lap spread is allowed to stand
# as the "best consistency" record — a 2-lap session can be trivially tight.
_MIN_CONSISTENCY_LAPS = 3

# Score-point move (0–100) below which the trend reads as "flat" — smaller than
# a single letter third, so only a real shift shows an arrow.
_TREND_MARGIN = 1.5


def recent_form(graded, n=RECENT_N):
    """Overall recent-form grade from already-graded sessions.

    graded — list of ``{'date', 'game', 'score'}`` dicts, newest first,
             ungradable sessions already excluded (score is the 0–100 OVERALL
             score from ``grading.grade``).
    n      — window size for the headline + per-game figures.

    Returns None when ``graded`` is empty, else::

        {'score':    float 0–100,          # mean of the last n
         'letter':   'A+'…'F',
         'n':        int,                  # sessions the headline averages
         'trend':    'up'|'down'|'flat'|None,   # vs the previous window
         'per_game': [{'game', 'score', 'letter', 'n'}, ...]}  # best first

    ``trend`` is None until there is a second window of history to compare
    against, so a brand-new driver never sees a misleading arrow.
    """
    if not graded:
        return None

    recent = [g['score'] for g in graded[:n]]
    overall = sum(recent) / len(recent)

    prev = [g['score'] for g in graded[n:2 * n]]
    trend = None
    if prev:
        delta = overall - sum(prev) / len(prev)
        if delta > _TREND_MARGIN:
            trend = 'up'
        elif delta < -_TREND_MARGIN:
            trend = 'down'
        else:
            trend = 'flat'

    by_game = {}
    for g in graded:
        by_game.setdefault(g['game'] or '', []).append(g['score'])
    per_game = []
    for game, scores in by_game.items():
        window = scores[:n]
        s = sum(window) / len(window)
        per_game.append({'game': game, 'score': s,
                         'letter': letter(s), 'n': len(window)})
    per_game.sort(key=lambda pg: pg['score'], reverse=True)

    return {'score': overall, 'letter': letter(overall), 'n': len(recent),
            'trend': trend, 'per_game': per_game}


# ---------------------------------------------------------------------------
# Personal records — the "chase statistics" for the driver profile.
# ---------------------------------------------------------------------------

def _rec_date(rec):
    """The row's date as a datetime (rows carry datetimes; some fixtures ISO
    strings), or None."""
    raw = rec.get('date')
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return raw


def _chrono(rec):
    return (_rec_date(rec) or datetime.min, rec.get('filename') or '')


def _combo(rec):
    """The grading combo key (game, car_class, track, session_type), or None
    when any part is missing."""
    key = (rec.get('game'), rec.get('car_class'), rec.get('track'),
           rec.get('session_type'))
    return key if all(key) else None


def _combo_label(rec):
    """A short 'Track · Car' subcaption for a record tile, best-effort."""
    car = rec.get('car_class_name') or rec.get('car') or rec.get('car_name')
    parts = [rec.get('track'), car]
    return ' · '.join(p for p in parts if p)


def _top_count(counts):
    """The most-frequent key as ``{'name', 'count'}``, or None when empty.
    Ties break on the name so the pick is deterministic."""
    if not counts:
        return None
    name, count = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    return {'name': name, 'count': count}


def personal_records(records):
    """Career 'chase' statistics over session_db-shaped rows (any order).

    Every value is None (or, for distance, None) when the archive holds no
    data for it, so the UI can hide empty tiles::

        {'clean_streak':      {'value': int,   'label': str} | None,
         'consistency':       {'value': float, 'label': str} | None,
         'largest_pb':        {'value': float, 'label': str} | None,
         'most_sessions':     {'name': str, 'count': int}     | None,
         'favourite_car':     {'name': str, 'count': int}     | None,
         'total_distance_km': float | None}

    ``value`` is the raw figure (laps / seconds / seconds gained); ``label``
    names where it happened. Largest PB reuses the same chronological
    per-combo walk as the ``breakthrough`` badge: the biggest single
    improvement over the personal best that stood going into a session.
    """
    recs = list(records)

    clean_streak = None
    consistency = None
    track_counts = {}
    car_counts = {}
    total_m = 0.0
    for rec in recs:
        streak = rec.get('clean_streak')
        if streak and (clean_streak is None or streak > clean_streak['value']):
            clean_streak = {'value': int(streak), 'label': _combo_label(rec)}

        std = rec.get('clean_std_dev')
        if (std is not None and (rec.get('clean_lap_count') or 0)
                >= _MIN_CONSISTENCY_LAPS
                and (consistency is None or std < consistency['value'])):
            consistency = {'value': float(std), 'label': _combo_label(rec)}

        track = rec.get('track')
        if track:
            track_counts[track] = track_counts.get(track, 0) + 1
        car = rec.get('car_class_name') or rec.get('car') or rec.get('car_name')
        if car:
            car_counts[car] = car_counts.get(car, 0) + 1

        total_m += rec.get('distance_m') or 0

    # Largest PB — walk each combo in time order, tracking the running best.
    largest_pb = None
    combo_best = {}
    for rec in sorted(recs, key=_chrono):
        best = rec.get('best_lap_time')
        combo = _combo(rec)
        if combo is None or best is None:
            continue
        prior = combo_best.get(combo)
        if prior is not None and best < prior:
            gain = prior - best
            if largest_pb is None or gain > largest_pb['value']:
                largest_pb = {'value': gain, 'label': _combo_label(rec)}
        if prior is None or best < prior:
            combo_best[combo] = best

    return {
        'clean_streak':      clean_streak,
        'consistency':       consistency,
        'largest_pb':        largest_pb,
        'most_sessions':     _top_count(track_counts),
        'favourite_car':     _top_count(car_counts),
        'total_distance_km': round(total_m / 1000.0, 1) if total_m else None,
    }
