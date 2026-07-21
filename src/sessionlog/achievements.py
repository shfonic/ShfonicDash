"""
Shfonic Dash sessionlog — achievements (shared library; canonical home
is ShfonicDash/src/sessionlog/, vendored into the companion app by
sync_shared.py — see the package docstring).

Career-wide badges computed deterministically from the session archive:
the CSVs are the save file. Both apps evaluate their own archive and
arrive at the same trophies; a session pushed to the Dash or imported
from ACC unlocks the same badge on both sides, and history is
retroactive — the day this ships, the existing archive earns its medals.

Everything here is provable from indexed session facts (session_db-shaped
rows). Where grading.milestones() celebrates per-combo progress ("new PB
here"), achievements celebrate the career ("your first race win",
"a thousand laps banked").

Badge natures:
  - one-time firsts        (count capped at 1: First Blood)
  - cumulative levels      (one badge, bronze/silver/gold thresholds on a
                            career total: Century at 100/500/1,000 laps)
  - repeatable feats       (a per-session accomplishment; count shown as a
                            multiplier, optionally tiered on the count:
                            Clean Sweep ×12)

evaluate() returns the earned state for the gallery; session_awards()
diffs one session out of the archive to answer "what did THIS session
earn" for the Pi's end-of-session banner and the journal.
"""

from datetime import datetime

from .grading import RACE_TYPES, grade

# Tunables — occurrence thresholds referenced by the registry below.
_CLEAN_SWEEP_MIN_LAPS = 8      # laps needed before zero-invalid is a feat
_METRONOME_LAPS       = 5      # on-pace laps (cons band) in one session
_THEO_CLOSE           = 0.05   # best clean lap within this of theoretical
_BREAKTHROUGH_GAIN    = 0.5    # PB improvement that reads as a leap
_ON_A_ROLL_STREAK     = 3      # consecutive PB sessions at one combo
_HOME_LAPS            = 100    # career laps at one track
_CHARGER_GAIN         = 5      # places gained in one race
_COMEBACK_FROM        = 10     # winning from this grid slot or worse
_RACE_MIN_LAPS        = 3      # ignore aborted races
_ICE_COLD_STD         = 0.25   # clean-lap spread that reads as machine-like
_ICE_COLD_LAPS        = 5      # clean laps needed to prove the consistency
_LONG_HAUL_LAPS       = 20     # laps in one session that read as endurance
_STREAK_RUN           = 3      # wins / podiums in a row for the streak feats
_EARLY_HOUR_FROM      = 5      # early-bird window: this hour (inclusive) ...
_EARLY_HOUR_TO        = 8      # ... to this hour (exclusive)
_FLAG_TO_FLAG_LAPS    = 5      # min race length for a "full race" no-rewind
_SESSION_KINDS        = ('race', 'qualifying', 'practice', 'hotlap')

_TIER_NAMES = ('bronze', 'silver', 'gold')

CATEGORIES = (
    ('milestones', 'Milestones'),
    ('craft',      'Craft'),
    ('progress',   'Progress'),
    ('racecraft',  'Racecraft'),
)

# The registry drives the gallery: order here is display order. The
# 'icon' emoji renders on the companion and is ignored on the Pi. 'tiers'
# maps occurrence counts to silver/gold ((s, g); bronze is the first
# occurrence); None means the count itself is the story. 'levels' badges
# earn one occurrence per career threshold crossed, so their tiers are
# always (2, 3): silver at the second level, gold at the third.
BADGES = (
    # -- Milestones ------------------------------------------------------
    {'id': 'century', 'icon': '💯', 'category': 'milestones', 'name': 'Century',
     'desc': 'Bank 100 career laps — 500 for silver, 1,000 for gold',
     'levels': (100, 500, 1000), 'unit': 'laps', 'tiers': (2, 3)},
    {'id': 'regular', 'icon': '📅', 'category': 'milestones', 'name': 'Regular',
     'desc': 'Log 25 sessions — 100 for silver, 250 for gold',
     'levels': (25, 100, 250), 'unit': 'sessions', 'tiers': (2, 3)},
    {'id': 'globetrotter', 'icon': '🗺️', 'category': 'milestones', 'name': 'Globetrotter',
     'desc': 'Drive 5 different tracks — 10 for silver, 20 for gold',
     'levels': (5, 10, 20), 'unit': 'tracks', 'tiers': (2, 3)},
    {'id': 'multi_disciplined', 'icon': '🎮', 'category': 'milestones',
     'name': 'Multi-Disciplined',
     'desc': 'Drive 2 different games — 3 for silver, 4 for gold',
     'levels': (2, 3, 4), 'unit': 'games', 'tiers': (2, 3)},
    {'id': 'night_shift', 'icon': '🌙', 'category': 'milestones', 'name': 'Night Shift',
     'desc': 'Start a session in the small hours (midnight to 5am)',
     'tiers': None},
    {'id': 'early_bird', 'icon': '🐦', 'category': 'milestones', 'name': 'Early Bird',
     'desc': 'Start a session in the early morning (5am to 8am)',
     'tiers': None},
    {'id': 'well_travelled', 'icon': '🧭', 'category': 'milestones',
     'name': 'Well Travelled',
     'desc': 'Drive 30 different tracks — 50 for silver, 100 for gold',
     'levels': (30, 50, 100), 'unit': 'tracks', 'tiers': (2, 3)},
    {'id': 'full_house', 'icon': '🃏', 'category': 'milestones', 'name': 'Full House',
     'desc': 'Drive all four session types — race, quali, practice, hotlap',
     'one_time': True, 'tiers': None},
    {'id': 'dedicated', 'icon': '🗓️', 'category': 'milestones', 'name': 'Dedicated',
     'desc': 'Drive 3 days running — 7 for silver, 14 for gold',
     'levels': (3, 7, 14), 'unit': 'days', 'tiers': (2, 3)},
    {'id': 'weekend_warrior', 'icon': '🏖️', 'category': 'milestones',
     'name': 'Weekend Warrior',
     'desc': 'Drive both Saturday and Sunday of one weekend',
     'tiers': (3, 10)},

    # -- Craft -----------------------------------------------------------
    {'id': 'clean_sweep', 'icon': '✨', 'category': 'craft', 'name': 'Clean Sweep',
     'desc': '8+ laps with none invalidated', 'tiers': (5, 25)},
    {'id': 'metronome', 'icon': '⏱️', 'category': 'craft', 'name': 'Metronome',
     'desc': 'Five on-pace laps in one session', 'tiers': (5, 25)},
    {'id': 'no_time_left', 'icon': '⚡', 'category': 'craft', 'name': 'No Time Left Behind',
     'desc': 'A clean lap within 0.05s of your theoretical best',
     'tiers': None},
    {'id': 'perfect_lap', 'icon': '💠', 'category': 'craft', 'name': 'Perfect Lap',
     'desc': 'Session-best S1, S2 and S3 all set on one lap', 'tiers': None},
    {'id': 'top_marks', 'icon': '🎓', 'category': 'craft', 'name': 'Top Marks',
     'desc': 'An A-range session grade', 'tiers': (5, 25)},
    {'id': 'ice_cold', 'icon': '🧊', 'category': 'craft', 'name': 'Ice Cold',
     'desc': 'Five clean laps within a 0.25s spread', 'tiers': (5, 25)},
    {'id': 'long_haul', 'icon': '🛣️', 'category': 'craft', 'name': 'Long Haul',
     'desc': 'Complete 20 or more laps in one session', 'tiers': (3, 10)},
    {'id': 'on_the_line', 'icon': '🎯', 'category': 'craft', 'name': 'On the Line',
     'desc': 'Drive an F1 session on the recorded racing line',
     'tiers': (5, 25)},

    # -- Progress --------------------------------------------------------
    {'id': 'breakthrough', 'icon': '🚀', 'category': 'progress', 'name': 'Breakthrough',
     'desc': 'Beat your PB at a combo by half a second or more',
     'tiers': None},
    {'id': 'on_a_roll', 'icon': '🔥', 'category': 'progress', 'name': 'On a Roll',
     'desc': 'A new PB at the same combo three sessions running',
     'tiers': None},
    {'id': 'hundred_home', 'icon': '🏠', 'category': 'progress', 'name': 'Hundred at Home',
     'desc': '100 career laps at a single track', 'tiers': None},

    # -- Racecraft -------------------------------------------------------
    {'id': 'first_blood', 'icon': '⚔️', 'category': 'racecraft', 'name': 'First Blood',
     'desc': 'Your first race win', 'one_time': True, 'tiers': None},
    {'id': 'winner', 'icon': '🏆', 'category': 'racecraft', 'name': 'Winner',
     'desc': 'Win a race', 'tiers': None},
    {'id': 'podium', 'icon': '🍾', 'category': 'racecraft', 'name': 'Podium',
     'desc': 'Finish a race in the top three', 'tiers': None},
    {'id': 'charger', 'icon': '📈', 'category': 'racecraft', 'name': 'Charger',
     'desc': 'Gain 5 or more places in one race', 'tiers': (5, 20)},
    {'id': 'comeback', 'icon': '💪', 'category': 'racecraft', 'name': 'The Comeback',
     'desc': 'Win from P10 or lower', 'tiers': None},
    {'id': 'untouched', 'icon': '🛡️', 'category': 'racecraft', 'name': 'Untouched',
     'desc': 'Win with no contact and no penalties', 'tiers': (3, 10)},
    {'id': 'lights_to_flag', 'icon': '🚥', 'category': 'racecraft',
     'name': 'Lights to Flag',
     'desc': 'Start on pole and win the race', 'tiers': (3, 10)},
    {'id': 'hat_trick', 'icon': '🎩', 'category': 'racecraft', 'name': 'Hat Trick',
     'desc': 'Win three races in a row', 'tiers': None},
    {'id': 'on_the_box', 'icon': '🥈', 'category': 'racecraft', 'name': 'On the Box',
     'desc': 'Finish on the podium three races running', 'tiers': None},
    {'id': 'clean_racer', 'icon': '🕊️', 'category': 'racecraft', 'name': 'Clean Racer',
     'desc': 'Finish a race with no contact and no penalties', 'tiers': (5, 25)},
    {'id': 'flag_to_flag', 'icon': '🏁', 'category': 'racecraft', 'name': 'Flag to Flag',
     'desc': 'Run a full race with no rewinds', 'tiers': (5, 25)},
)

_BY_ID = {b['id']: b for b in BADGES}


def badge(badge_id):
    """The registry entry for one badge id (KeyError when unknown)."""
    return _BY_ID[badge_id]


def _date(rec):
    """The record's date as a datetime (rows carry datetimes, some test
    fixtures ISO strings), or None."""
    raw = rec.get('date')
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return raw


def _chrono(rec):
    return (_date(rec) or datetime.min, rec.get('filename') or '')


def _is_race(rec):
    label = ((rec.get('session_subtype') or rec.get('session_type') or '')
             .strip().lower())
    return label in RACE_TYPES


def _combo(rec):
    key = (rec.get('game'), rec.get('car_class'), rec.get('track'),
           rec.get('session_type'))
    return key if all(key) else None


def tier_for(badge_def, count):
    """'bronze' / 'silver' / 'gold' for an earned tiered badge, None for
    an unearned or untiered one."""
    if count <= 0 or not badge_def.get('tiers'):
        return None
    silver, gold = badge_def['tiers']
    if count >= gold:
        return 'gold'
    if count >= silver:
        return 'silver'
    return 'bronze'


def tier_goals(badge_def):
    """A short 'Silver at x5, Gold at x25' line for a repeatable tiered
    badge, or None for level / untiered badges (a level badge's own desc
    already spells its thresholds out). Used by the trophy detail screens
    to explain what raises the medal."""
    tiers = badge_def.get('tiers')
    if not tiers or badge_def.get('levels'):
        return None
    silver, gold = tiers
    return f'Silver at x{silver}, Gold at x{gold}'


def evaluate(records):
    """
    Earned badges over session_db-shaped rows (any order).

    -> {badge_id: {'count': int, 'tier': str|None,
                   'sessions': [(filename, date), ...] newest first}}
    Only earned badges appear; the gallery unions this with BADGES for
    the unearned outlines.
    """
    recs = sorted((r for r in records if r.get('filename')), key=_chrono)

    earned = {}

    def _hit(badge_id, rec, times=1):
        state = earned.setdefault(badge_id, {'count': 0, 'sessions': []})
        state['count'] += times
        state['sessions'].insert(0, (rec['filename'], _date(rec)))

    # Career accumulators for the sweep.
    total_laps = total_sessions = 0
    tracks, games = set(), set()
    track_laps = {}                    # (game, track) -> career laps
    combo_best = {}                    # combo -> best clean lap so far
    combo_pb_streak = {}               # combo -> consecutive-PB run length
    won_before = False
    kinds_seen = set()                 # base session types driven (full_house)
    full_house_done = False
    prev_day = None                    # last calendar day driven (dedicated)
    day_streak = 0                     # consecutive-day run length
    day_streak_max = 0                 # high-water mark, so levels award once
    weekend_days = {}                  # (iso year, iso week) -> {weekday, ...}
    weekends_done = set()              # weekends already credited
    win_streak = 0                     # consecutive race wins (hat_trick)
    podium_streak = 0                  # consecutive race podiums (on_the_box)

    for rec in recs:
        laps = rec.get('lap_count') or 0

        # ---- cumulative levels (award each threshold crossed) ----------
        for badge_id, before, after in (
                ('century', total_laps, total_laps + laps),
                ('regular', total_sessions, total_sessions + 1)):
            crossed = sum(1 for lv in _BY_ID[badge_id]['levels']
                          if before < lv <= after)
            if crossed:
                _hit(badge_id, rec, crossed)
        total_laps += laps
        total_sessions += 1

        track, game = rec.get('track'), rec.get('game')
        if track and track not in tracks:
            tracks.add(track)
            n = len(tracks)
            for badge_id in ('globetrotter', 'well_travelled'):
                if n in _BY_ID[badge_id]['levels']:
                    _hit(badge_id, rec)
        if game and game not in games:
            games.add(game)
            if len(games) in _BY_ID['multi_disciplined']['levels']:
                _hit('multi_disciplined', rec)
        if track and game:
            key = (game, track)
            before = track_laps.get(key, 0)
            track_laps[key] = before + laps
            if before < _HOME_LAPS <= track_laps[key]:
                _hit('hundred_home', rec)

        # Variety: all four base session types driven at least once.
        kind = (rec.get('session_type') or '').strip().lower()
        if kind in _SESSION_KINDS:
            kinds_seen.add(kind)
            if not full_house_done and len(kinds_seen) == len(_SESSION_KINDS):
                full_house_done = True
                _hit('full_house', rec)

        date = _date(rec)
        if date is not None and date.hour < 5:
            _hit('night_shift', rec)
        if date is not None and _EARLY_HOUR_FROM <= date.hour < _EARLY_HOUR_TO:
            _hit('early_bird', rec)

        # Dedication: consecutive calendar days, and weekend doubles.
        if date is not None:
            day = date.date()
            if prev_day is None or (day - prev_day).days > 1:
                day_streak = 1
            elif (day - prev_day).days == 1:
                day_streak += 1
            # same day -> streak unchanged
            prev_day = day
            if day_streak > day_streak_max:
                crossed = sum(1 for lv in _BY_ID['dedicated']['levels']
                              if day_streak_max < lv <= day_streak)
                if crossed:
                    _hit('dedicated', rec, crossed)
                day_streak_max = day_streak
            iso = date.isocalendar()
            week_key = (iso[0], iso[1])
            days = weekend_days.setdefault(week_key, set())
            days.add(date.weekday())      # Sat = 5, Sun = 6
            if 5 in days and 6 in days and week_key not in weekends_done:
                weekends_done.add(week_key)
                _hit('weekend_warrior', rec)

        # ---- per-session craft feats -----------------------------------
        valid = rec.get('valid_lap_count')
        if (laps >= _CLEAN_SWEEP_MIN_LAPS and valid is not None
                and valid == laps):
            _hit('clean_sweep', rec)
        if (rec.get('cons_band_count') or 0) >= _METRONOME_LAPS:
            _hit('metronome', rec)
        best, theo = rec.get('best_lap_time'), rec.get('theo_time')
        if best is not None and theo is not None \
                and best - theo <= _THEO_CLOSE:
            _hit('no_time_left', rec)
        if rec.get('perfect_lap'):
            _hit('perfect_lap', rec)
        g = grade(rec)
        if g and (g.get('letter') or '').startswith('A'):
            _hit('top_marks', rec)
        clean_laps = rec.get('clean_lap_count') or 0
        std = rec.get('clean_std_dev')
        if (clean_laps >= _ICE_COLD_LAPS and std is not None
                and std <= _ICE_COLD_STD):
            _hit('ice_cold', rec)
        if laps >= _LONG_HAUL_LAPS:
            _hit('long_haul', rec)
        # Racing-line adherence: a full session driven on the recorded line
        # (hotlap needs several on-line laps; quali needs all its push laps).
        if rec.get('on_line_session'):
            _hit('on_the_line', rec)

        # ---- per-combo progress ----------------------------------------
        combo = _combo(rec)
        if combo and best is not None:
            prior = combo_best.get(combo)
            is_pb = prior is None or best < prior
            if prior is not None and is_pb \
                    and prior - best >= _BREAKTHROUGH_GAIN:
                _hit('breakthrough', rec)
            # A PB streak needs improvement, so the opening session of a
            # combo starts the count at 0 — nothing to improve on.
            streak = (combo_pb_streak.get(combo, 0) + 1
                      if is_pb and prior is not None else 0)
            combo_pb_streak[combo] = streak
            if streak == _ON_A_ROLL_STREAK:
                _hit('on_a_roll', rec)
            if is_pb:
                combo_best[combo] = best

        # ---- racecraft --------------------------------------------------
        pos = rec.get('position')
        if _is_race(rec) and laps >= _RACE_MIN_LAPS and pos is not None:
            start = rec.get('start_position')
            clean = ((rec.get('collision_count') or 0) == 0
                     and (rec.get('penalty_count') or 0) == 0)
            if pos == 1:
                if not won_before:
                    won_before = True
                    _hit('first_blood', rec)
                _hit('winner', rec)
                if start is not None and start >= _COMEBACK_FROM:
                    _hit('comeback', rec)
                if clean:
                    _hit('untouched', rec)
                if start == 1:
                    _hit('lights_to_flag', rec)
            if pos <= 3:
                _hit('podium', rec)
            if start is not None and start - pos >= _CHARGER_GAIN:
                _hit('charger', rec)
            if clean:
                _hit('clean_racer', rec)
            if (rec.get('rewind_count') or 0) == 0 and laps >= _FLAG_TO_FLAG_LAPS:
                _hit('flag_to_flag', rec)

            # Streak feats — credited each time the run reaches a multiple
            # of the target length (a fresh hat-trick every three wins).
            win_streak = win_streak + 1 if pos == 1 else 0
            if win_streak and win_streak % _STREAK_RUN == 0:
                _hit('hat_trick', rec)
            podium_streak = podium_streak + 1 if pos <= 3 else 0
            if podium_streak and podium_streak % _STREAK_RUN == 0:
                _hit('on_the_box', rec)

    for badge_id, state in earned.items():
        state['tier'] = tier_for(_BY_ID[badge_id], state['count'])
    return earned


def session_awards(records, filename):
    """
    What one session added to the career — for the end-of-session banner
    and the journal. records must INCLUDE the session.

    -> [{'id', 'name', 'category', 'kind', 'count', 'tier'}, ...]
    kind: 'unlocked' (first ever), 'upgraded' (tier rose), 'repeat'
    (count rose). Most notable first; empty when the session earned
    nothing.
    """
    with_it  = evaluate(records)
    without  = evaluate([r for r in records
                         if r.get('filename') != filename])
    rank = {'unlocked': 0, 'upgraded': 1, 'repeat': 2}
    out = []
    for badge_def in BADGES:
        bid = badge_def['id']
        now, was = with_it.get(bid), without.get(bid)
        if now is None or (was and was['count'] >= now['count']):
            continue
        if not any(fn == filename for fn, _ in now['sessions']):
            continue
        if was is None:
            kind = 'unlocked'
        elif now['tier'] != was['tier']:
            kind = 'upgraded'
        else:
            kind = 'repeat'
        out.append({'id': bid, 'name': badge_def['name'],
                    'category': badge_def['category'], 'kind': kind,
                    'count': now['count'], 'tier': now['tier']})
    out.sort(key=lambda a: rank[a['kind']])
    return out
