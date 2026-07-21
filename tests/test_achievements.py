"""Shared tests for sessionlog.achievements — career badges.

Run in both the ShfonicDash repo and (via sync_shared.py) the
companion app.
"""
from datetime import datetime, timedelta

from sessionlog.achievements import (
    BADGES,
    badge,
    evaluate,
    session_awards,
    tier_for,
    tier_goals,
)

_T0 = datetime(2026, 6, 1, 19, 0)


def _record(i=0, **overrides):
    """A practice scan record; i orders the archive chronologically."""
    base = {
        'filename':        f'session_2026_{i:04d}_practice.csv',
        'date':            _T0 + timedelta(days=i),
        'game':            'f1_25',
        'car_class':       'formula1',
        'track':           'Silverstone',
        'session_type':    'practice',
        'session_subtype': '',
        'lap_count':       10,
        'valid_lap_count': 8,
        'clean_lap_count': 8,
        'clean_std_dev':   0.40,
        'cons_lap_count':  4,
        'cons_band_count': 3,
        'theo_time':       88.0,
        'rewind_count':    0,
        'collision_count': 0,
        'penalty_count':   0,
        'best_lap_time':   89.0,
        'perfect_lap':     0,
        'position':        None,
        'start_position':  None,
    }
    base.update(overrides)
    return base


def _race(i=0, **overrides):
    rec = _record(i, session_type='race', position=5, start_position=5,
                  lap_count=10)
    rec['filename'] = f'session_2026_{i:04d}_race.csv'
    rec.update(overrides)
    return rec


class TestRegistry:
    def test_ids_unique_and_categorised(self):
        ids = [b['id'] for b in BADGES]
        assert len(ids) == len(set(ids))
        assert all(b['category'] in ('milestones', 'craft', 'progress',
                                     'racecraft') for b in BADGES)

    def test_badge_lookup(self):
        assert badge('century')['name'] == 'Century'

    def test_tier_for(self):
        cs = badge('clean_sweep')          # tiers (5, 25)
        assert tier_for(cs, 0) is None
        assert tier_for(cs, 1) == 'bronze'
        assert tier_for(cs, 5) == 'silver'
        assert tier_for(cs, 25) == 'gold'
        assert tier_for(badge('winner'), 3) is None   # untiered

    def test_tier_goals(self):
        assert tier_goals(badge('clean_sweep')) == 'Silver at x5, Gold at x25'
        assert tier_goals(badge('winner')) is None          # untiered
        assert tier_goals(badge('century')) is None         # level badge


class TestMilestones:
    def test_century_levels(self):
        recs = [_record(i, lap_count=50) for i in range(21)]  # 1050 laps
        got = evaluate(recs)['century']
        assert got['count'] == 3                     # 100, 500, 1000
        assert got['tier'] == 'gold'
        # earned by the sessions that crossed each threshold
        assert got['sessions'][0][0] == recs[19]['filename']   # 1000th lap

    def test_century_unearned_below_threshold(self):
        assert 'century' not in evaluate([_record(0, lap_count=99)])

    def test_globetrotter_counts_distinct_tracks(self):
        recs = [_record(i, track=f'Track {i}') for i in range(5)]
        got = evaluate(recs)['globetrotter']
        assert got['count'] == 1 and got['tier'] == 'bronze'

    def test_multi_disciplined(self):
        recs = [_record(0), _record(1, game='pcars2'),
                _record(2, game='fm')]
        got = evaluate(recs)['multi_disciplined']
        assert got['count'] == 2 and got['tier'] == 'silver'

    def test_night_shift(self):
        rec = _record(0, date=datetime(2026, 6, 2, 0, 40))
        assert evaluate([rec])['night_shift']['count'] == 1
        assert 'night_shift' not in evaluate([_record(0)])   # 19:00 start

    def test_early_bird(self):
        rec = _record(0, date=datetime(2026, 6, 2, 6, 30))
        assert evaluate([rec])['early_bird']['count'] == 1
        assert 'early_bird' not in evaluate([_record(0)])            # 19:00
        # the small hours belong to Night Shift, not Early Bird
        assert 'early_bird' not in evaluate(
            [_record(0, date=datetime(2026, 6, 2, 3, 0))])

    def test_full_house_once_all_four_types(self):
        recs = [_record(0, session_type='practice'),
                _record(1, session_type='qualifying'),
                _record(2, session_type='hotlap')]
        assert 'full_house' not in evaluate(recs)                    # 3 of 4
        recs.append(_race(3, position=5))                            # race
        got = evaluate(recs)['full_house']
        assert got['count'] == 1                                     # one-time
        assert got['sessions'][0][0] == recs[3]['filename']

    def test_well_travelled_deep_track_counts(self):
        recs = [_record(i, track=f'Track {i}') for i in range(30)]
        got = evaluate(recs)['well_travelled']
        assert got['count'] == 1 and got['tier'] == 'bronze'         # 30 tracks
        assert 'well_travelled' not in evaluate(recs[:29])           # 29 tracks

    def test_dedicated_consecutive_days(self):
        # Mon 1 Jun 2026 onward — three days running earns bronze.
        recs = [_record(0, date=datetime(2026, 6, 1, 19)),
                _record(1, date=datetime(2026, 6, 2, 19)),
                _record(2, date=datetime(2026, 6, 3, 19))]
        got = evaluate(recs)['dedicated']
        assert got['count'] == 1 and got['tier'] == 'bronze'
        # a gap resets the run, so two-then-gap-then-two never reaches 3
        gapped = [_record(0, date=datetime(2026, 6, 1, 19)),
                  _record(1, date=datetime(2026, 6, 2, 19)),
                  _record(2, date=datetime(2026, 6, 5, 19)),
                  _record(3, date=datetime(2026, 6, 6, 19))]
        assert 'dedicated' not in evaluate(gapped)

    def test_weekend_warrior_saturday_and_sunday(self):
        # 6 Jun 2026 is a Saturday, 7 Jun a Sunday — same ISO week.
        recs = [_record(0, date=datetime(2026, 6, 6, 14)),
                _record(1, date=datetime(2026, 6, 7, 14))]
        assert evaluate(recs)['weekend_warrior']['count'] == 1
        # Saturday alone doesn't count
        assert 'weekend_warrior' not in evaluate([recs[0]])


class TestCraft:
    def test_clean_sweep_needs_min_laps_and_all_valid(self):
        good = _record(0, lap_count=8, valid_lap_count=8)
        assert evaluate([good])['clean_sweep']['count'] == 1
        assert 'clean_sweep' not in evaluate(
            [_record(0, lap_count=8, valid_lap_count=7)])
        assert 'clean_sweep' not in evaluate(
            [_record(0, lap_count=7, valid_lap_count=7)])

    def test_metronome_from_cons_band(self):
        assert 'metronome' in evaluate([_record(0, cons_band_count=5)])
        assert 'metronome' not in evaluate([_record(0, cons_band_count=4)])

    def test_no_time_left_behind(self):
        close = _record(0, best_lap_time=88.04, theo_time=88.0)
        assert evaluate([close])['no_time_left']['count'] == 1
        assert 'no_time_left' not in evaluate(
            [_record(0, best_lap_time=88.2, theo_time=88.0)])

    def test_perfect_lap_flag(self):
        assert 'perfect_lap' in evaluate([_record(0, perfect_lap=1)])
        assert 'perfect_lap' not in evaluate([_record(0)])

    def test_repeatable_count_and_tier(self):
        recs = [_record(i, lap_count=8, valid_lap_count=8)
                for i in range(5)]
        got = evaluate(recs)['clean_sweep']
        assert got['count'] == 5 and got['tier'] == 'silver'
        assert len(got['sessions']) == 5
        # newest first
        assert got['sessions'][0][0] == recs[4]['filename']

    def test_ice_cold_needs_clean_laps_and_tight_spread(self):
        good = _record(0, clean_lap_count=5, clean_std_dev=0.20)
        assert evaluate([good])['ice_cold']['count'] == 1
        assert 'ice_cold' not in evaluate(
            [_record(0, clean_lap_count=5, clean_std_dev=0.30)])  # too loose
        assert 'ice_cold' not in evaluate(
            [_record(0, clean_lap_count=4, clean_std_dev=0.10)])  # too few

    def test_long_haul_session_length(self):
        assert 'long_haul' in evaluate([_record(0, lap_count=20)])
        assert 'long_haul' not in evaluate([_record(0, lap_count=19)])


class TestProgress:
    def test_breakthrough_needs_prior_and_half_second(self):
        recs = [_record(0, best_lap_time=90.0),
                _record(1, best_lap_time=89.4)]
        assert evaluate(recs)['breakthrough']['count'] == 1
        # first session at a combo can't break through
        assert 'breakthrough' not in evaluate([_record(0)])
        # small improvement doesn't count
        assert 'breakthrough' not in evaluate(
            [_record(0, best_lap_time=90.0),
             _record(1, best_lap_time=89.8)])

    def test_on_a_roll_three_pb_sessions_running(self):
        times = [90.0, 89.8, 89.6, 89.4]   # 3 consecutive improvements
        recs = [_record(i, best_lap_time=t) for i, t in enumerate(times)]
        assert evaluate(recs)['on_a_roll']['count'] == 1
        # a non-PB session breaks the run
        times = [90.0, 89.8, 89.9, 89.6, 89.5]
        recs = [_record(i, best_lap_time=t) for i, t in enumerate(times)]
        assert 'on_a_roll' not in evaluate(recs)

    def test_hundred_home_once_per_track(self):
        recs = ([_record(i, lap_count=50) for i in range(3)]
                + [_record(i + 10, track='Spa', lap_count=50)
                   for i in range(2)])
        got = evaluate(recs)['hundred_home']
        assert got['count'] == 2     # Silverstone and Spa both crossed 100


class TestRacecraft:
    def test_win_unlocks_first_blood_and_winner(self):
        got = evaluate([_race(0, position=1)])
        assert got['first_blood']['count'] == 1
        assert got['winner']['count'] == 1
        assert got['podium']['count'] == 1

    def test_first_blood_only_once(self):
        got = evaluate([_race(0, position=1), _race(1, position=1)])
        assert got['first_blood']['count'] == 1
        assert got['winner']['count'] == 2

    def test_non_race_sessions_never_fire(self):
        assert 'winner' not in evaluate([_record(0, position=1)])

    def test_sprint_race_counts(self):
        rec = _race(0, position=1, session_type='race',
                    session_subtype='sprint_race')
        assert 'winner' in evaluate([rec])

    def test_charger_and_comeback(self):
        got = evaluate([_race(0, position=1, start_position=12)])
        assert got['charger']['count'] == 1
        assert got['comeback']['count'] == 1
        assert 'comeback' not in evaluate(
            [_race(1, position=1, start_position=9)])

    def test_untouched_requires_clean_win(self):
        assert 'untouched' in evaluate([_race(0, position=1)])
        assert 'untouched' not in evaluate(
            [_race(0, position=1, collision_count=1)])
        assert 'untouched' not in evaluate(
            [_race(0, position=1, penalty_count=1)])

    def test_aborted_race_ignored(self):
        assert 'winner' not in evaluate([_race(0, position=1, lap_count=2)])

    def test_lights_to_flag_pole_and_win(self):
        assert 'lights_to_flag' in evaluate(
            [_race(0, position=1, start_position=1)])
        assert 'lights_to_flag' not in evaluate(
            [_race(0, position=1, start_position=3)])   # won, not from pole

    def test_clean_racer_any_finish(self):
        # a clean midfield finish counts (Untouched needs the win)
        got = evaluate([_race(0, position=6)])
        assert got['clean_racer']['count'] == 1
        assert 'untouched' not in got
        assert 'clean_racer' not in evaluate(
            [_race(0, position=6, penalty_count=1)])

    def test_flag_to_flag_full_race_no_rewinds(self):
        assert 'flag_to_flag' in evaluate(
            [_race(0, position=4, lap_count=8, rewind_count=0)])
        assert 'flag_to_flag' not in evaluate(
            [_race(0, position=4, lap_count=8, rewind_count=2)])
        assert 'flag_to_flag' not in evaluate(
            [_race(0, position=4, lap_count=4)])        # too short

    def test_hat_trick_three_wins_running(self):
        wins = [_race(i, position=1) for i in range(3)]
        assert evaluate(wins)['hat_trick']['count'] == 1
        # a loss between wins breaks the run
        broken = [_race(0, position=1), _race(1, position=4),
                  _race(2, position=1), _race(3, position=1)]
        assert 'hat_trick' not in evaluate(broken)
        # six in a row is two hat-tricks
        assert evaluate([_race(i, position=1) for i in range(6)]
                        )['hat_trick']['count'] == 2

    def test_on_the_box_three_podiums_running(self):
        podiums = [_race(i, position=3) for i in range(3)]
        assert evaluate(podiums)['on_the_box']['count'] == 1
        broken = [_race(0, position=2), _race(1, position=8),
                  _race(2, position=3), _race(3, position=1)]
        assert 'on_the_box' not in evaluate(broken)


class TestSessionAwards:
    def test_unlock_and_repeat_kinds(self):
        a = _record(0, lap_count=8, valid_lap_count=8)
        b = _record(1, lap_count=8, valid_lap_count=8)
        first = session_awards([a], a['filename'])
        assert [(x['id'], x['kind']) for x in first] \
            == [('clean_sweep', 'unlocked')]
        repeat = session_awards([a, b], b['filename'])
        assert [(x['id'], x['kind']) for x in repeat] \
            == [('clean_sweep', 'repeat')]

    def test_tier_upgrade_kind(self):
        recs = [_record(i, lap_count=8, valid_lap_count=8)
                for i in range(5)]
        awards = session_awards(recs, recs[4]['filename'])
        cs = next(x for x in awards if x['id'] == 'clean_sweep')
        assert cs['kind'] == 'upgraded'
        assert cs['count'] == 5 and cs['tier'] == 'silver'

    def test_session_that_earned_nothing(self):
        a = _record(0, lap_count=8, valid_lap_count=8)
        b = _record(1, lap_count=6, valid_lap_count=5)
        assert session_awards([a, b], b['filename']) == []

    def test_most_notable_first(self):
        # A first win that is also a repeat clean sweep: unlocked first.
        sweeps = [_record(i, lap_count=8, valid_lap_count=8)
                  for i in range(2)]
        win = _race(5, position=1, valid_lap_count=10)   # also clean sweep
        awards = session_awards(sweeps + [win], win['filename'])
        assert awards[0]['kind'] == 'unlocked'
        assert 'first_blood' in [x['id'] for x in awards]

    def test_string_dates_tolerated(self):
        rec = _record(0, date='2026-06-01T19:00:00')
        assert 'clean_sweep' in evaluate(
            [dict(rec, lap_count=8, valid_lap_count=8)])


class TestOnTheLine:
    """The racing-line adherence badge — earned once per on-line session,
    tiered to reward doing it across several sessions."""

    def _hotlap(self, i, on_line):
        rec = _record(i, session_type='hotlap')
        rec['filename'] = f'session_2026_{i:04d}_hotlap.csv'
        rec['on_line_session'] = on_line
        return rec

    def test_earned_when_session_on_line(self):
        got = evaluate([self._hotlap(0, True)])['on_the_line']
        assert got['count'] == 1 and got['tier'] == 'bronze'

    def test_not_earned_without_line_data(self):
        # A plain record (no on_line_session key) never earns it.
        assert 'on_the_line' not in evaluate([_record(0, session_type='hotlap')])
        assert 'on_the_line' not in evaluate([self._hotlap(0, False)])

    def test_tiers_up_across_sessions(self):
        recs = [self._hotlap(i, True) for i in range(5)]
        got = evaluate(recs)['on_the_line']
        assert got['count'] == 5 and got['tier'] == 'silver'
        recs = [self._hotlap(i, True) for i in range(25)]
        assert evaluate(recs)['on_the_line']['tier'] == 'gold'

    def test_session_award_unlocks_it(self):
        prior = [self._hotlap(0, True)]
        new = self._hotlap(1, True)
        ids = [a['id'] for a in session_awards(prior + [new], new['filename'])]
        assert 'on_the_line' in ids
