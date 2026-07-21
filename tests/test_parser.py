"""
Tests for sessionlog.parser — the session-log CSV parser.

Shared test: lives canonically in ShfonicDash/tests/ and is copied
into the companion repo by sync_shared.py.

Fixtures are small inline CSVs plus a checked-in sample session (found in
whichever repo the test runs in — see SAMPLE below). The typed-row format
is specified in docs/session-log-format.md.
"""

import os
from datetime import datetime

import pytest

from sessionlog.parser import (
    classify_laps,
    format_lap_time,
    format_sector_time,
    parse,
    penalty_detail,
    qualifying_outcome,
    scan_session,
    session_label,
    stint_std_dev,
    tyre_stints,
)

# The sample session lives in tests/fixtures/ in the Pi repo and
# SampleData/ in the companion repo — same file, first hit wins.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SAMPLE_NAME = 'session_20260629_0000_qualifying_mock.csv'
SAMPLE = next(p for p in (
    os.path.join(_HERE, 'fixtures', _SAMPLE_NAME),
    os.path.join(os.path.dirname(_HERE), 'SampleData', _SAMPLE_NAME),
) if os.path.exists(p))

LAP_HEADER = ('H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,'
              'tyre_compound,fuel_remaining,fuel_per_lap,position,delta,invalid,rewinds')


def _typed_csv(*rows):
    return '\n'.join(rows) + '\n'


def _lap(num, time, s1='', s2='', s3='', invalid='0', rewinds='0', **extra):
    tyres = extra.get('tyres', ',,,')
    compound = extra.get('compound', '')
    return (f'L,{num},{time},{s1},{s2},{s3},{tyres},{compound},,,'
            f'{extra.get("position", "")},{extra.get("delta", "")},{invalid},{rewinds}')


# ---------------------------------------------------------------------------
# Sample file — full worked example
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def session():
    with open(SAMPLE, encoding='utf-8') as f:
        return parse(f.read(), os.path.basename(SAMPLE))


class TestSampleSession:
    def test_metadata(self, session):
        assert session['track'] == 'Monaco'
        assert session['game'] == 'f1_25'
        assert session['game_name'] == 'F1 25'
        assert session['car_name'] == 'Red Bull Racing'
        assert session['car_class'] == 'formula1_2026'
        assert session['car_class_name'] == 'F1 2026'
        assert session['session_type'] == 'qualifying'

    def test_started_at_preferred_over_filename(self, session):
        assert session['date'] == datetime(2026, 6, 28, 21, 14)

    def test_laps_and_best(self, session):
        assert len(session['laps']) == 3
        assert session['best_lap_time'] == 68.6

    def test_grid_standings_events(self, session):
        assert len(session['grid']) == 20
        assert session['grid'][0] == {'position': '1', 'race_num': '1', 'name': 'Verstappen'}
        assert len(session['standings']) == 20
        assert session['events'] == [
            {'lap_num': 1, 'lap_time': 52.341, 'type': 'rewind',
             'distance': None, 't': None, 'detail': None}]

    def test_invalid_and_rewound_lap(self, session):
        lap1 = session['laps'][0]
        assert lap1['valid'] is False
        assert lap1['rewinds'] == 1
        assert lap1['lap_flag'] == 'red'

    def test_summary_z_rows(self, session):
        assert session['summary']['fastest_lap'] == 68.6
        assert session['summary']['invalid_laps'] == 1
        assert session['summary']['rewinds'] == 1


class TestFocusRow:
    def test_focus_parsed(self):
        text = _typed_csv('S,game,f1_25', 'F,consistency',
                          LAP_HEADER, _lap(1, 80.0))
        assert parse(text)['focus'] == 'consistency'

    def test_no_focus_row_is_none(self):
        text = _typed_csv('S,game,f1_25', LAP_HEADER, _lap(1, 80.0))
        assert parse(text)['focus'] is None

    def test_malformed_focus_row_ignored(self):
        # A bare 'F' with no id must not crash the parser.
        text = _typed_csv('S,game,f1_25', 'F', LAP_HEADER, _lap(1, 80.0))
        assert parse(text)['focus'] is None


# ---------------------------------------------------------------------------
# Format auto-detection
# ---------------------------------------------------------------------------

class TestFormatDetection:
    def test_typed_format_detected(self):
        text = _typed_csv('S,game,f1_25', LAP_HEADER, _lap(1, 80.0))
        assert parse(text)['game'] == 'f1_25'

    def test_flat_format_detected(self):
        text = ('lap_num,lap_time,s1,s2,s3,car_class,session_type,game\n'
                '1,77.503,,,,gt3,practice,acc\n')
        session = parse(text)
        assert session['game'] == 'acc'
        assert session['car_class_name'] == 'GT3'
        assert session['track'] is None       # flat format has no track
        assert session['best_lap_time'] == 77.503

    def test_flat_session_type_falls_back_to_filename(self):
        text = 'lap_num,lap_time,game\n1,90.0,fm\n'
        session = parse(text, 'session_20260101_1200_race.csv')
        assert session['session_type'] == 'race'
        assert session['date'] == datetime(2026, 1, 1, 12, 0)

    def test_unknown_row_types_ignored(self):
        text = _typed_csv('S,game,f1_25', 'X,junk,row', LAP_HEADER, _lap(1, 80.0))
        assert len(parse(text)['laps']) == 1


# ---------------------------------------------------------------------------
# Nullable fields — "" maps to None
# ---------------------------------------------------------------------------

class TestNullableFields:
    def test_empty_fields_become_none(self):
        session = parse(_typed_csv('S,game,f1_25', LAP_HEADER, _lap(1, 80.0)))
        lap = session['laps'][0]
        for key in ('s1', 's2', 's3', 'position', 'delta',
                    'tyre_compound', 'fuel_remaining'):
            assert lap[key] is None, key

    def test_missing_assist_columns_become_none_not_zero(self):
        # LAP_HEADER predates v0.40.0 assist logging — a file without the
        # columns must read as "unknown", not "off" (which would falsely
        # claim a driver ran with everything off).
        session = parse(_typed_csv('S,game,f1_25', LAP_HEADER, _lap(1, 80.0)))
        lap = session['laps'][0]
        for key in ('assist_tc', 'assist_abs', 'assist_racing_line',
                    'assist_steering', 'assist_braking', 'assist_gearbox',
                    'assist_pit', 'assist_pit_release', 'assist_ers',
                    'assist_drs'):
            assert lap[key] is None, key

    def test_assist_columns_parsed_when_present(self):
        header = ('H,lap_num,lap_time,assist_tc,assist_abs,assist_racing_line,'
                  'assist_steering,assist_braking,assist_gearbox,assist_pit,'
                  'assist_pit_release,assist_ers,assist_drs')
        row = 'L,1,80.0,2,1,2,1,1,2,1,1,1,1'
        session = parse(_typed_csv('S,game,f1_25', header, row))
        lap = session['laps'][0]
        assert lap['assist_tc'] == 2
        assert lap['assist_abs'] == 1
        assert lap['assist_racing_line'] == 2
        assert lap['assist_steering'] == 1
        assert lap['assist_braking'] == 1
        assert lap['assist_gearbox'] == 2
        assert lap['assist_pit'] == 1
        assert lap['assist_pit_release'] == 1
        assert lap['assist_ers'] == 1
        assert lap['assist_drs'] == 1

    def test_car_falls_back_to_class_name_when_car_name_empty(self):
        session = parse(_typed_csv(
            'S,car_class,gt3', 'S,car_name,', LAP_HEADER, _lap(1, 80.0)))
        assert session['car_name'] is None
        assert session['car'] == 'GT3'


# ---------------------------------------------------------------------------
# Weather metadata (v0.1.142+)
# ---------------------------------------------------------------------------

class TestWeather:
    def test_weather_and_temps_parsed(self):
        session = parse(_typed_csv(
            'S,game,f1_25', 'S,weather,overcast', 'S,air_temp,19',
            'S,track_temp,31', LAP_HEADER, _lap(1, 80.0)))
        assert session['weather'] == 'overcast'
        assert session['air_temp'] == 19
        assert session['track_temp'] == 31

    def test_repeated_weather_rows_keep_last_value(self):
        # Dynamic weather writes one S row per change — last value wins.
        session = parse(_typed_csv(
            'S,game,f1_25', 'S,weather,clear', LAP_HEADER, _lap(1, 80.0),
            'S,weather,heavy_rain'))
        assert session['weather'] == 'heavy_rain'

    def test_missing_weather_fields_default(self):
        session = parse(_typed_csv('S,game,f1_25', LAP_HEADER, _lap(1, 80.0)))
        assert session['weather'] == ''
        assert session['air_temp'] is None
        assert session['track_temp'] is None


# ---------------------------------------------------------------------------
# Flag computation
# ---------------------------------------------------------------------------

class TestFlags:
    def _laps(self, *times, invalid=(), rewinds=()):
        rows = [
            _lap(i + 1, t,
                 invalid='1' if (i + 1) in invalid else '0',
                 rewinds='1' if (i + 1) in rewinds else '0')
            for i, t in enumerate(times)
        ]
        return parse(_typed_csv('S,game,f1_25', LAP_HEADER, *rows))['laps']

    def test_session_best_is_magenta(self):
        laps = self._laps(80.0, 79.0, 78.0)
        assert laps[2]['lap_flag'] == 'magenta'

    def test_personal_best_at_the_time_is_purple(self):
        # Lap 2 beats lap 1 but is later beaten by lap 3 → purple.
        laps = self._laps(80.0, 78.5, 78.0)
        assert laps[1]['lap_flag'] == 'purple'

    def test_green_within_030_of_best(self):
        laps = self._laps(78.0, 78.25)
        assert laps[1]['lap_flag'] == 'green'

    def test_yellow_at_or_beyond_100_off_best(self):
        laps = self._laps(78.0, 79.5)
        assert laps[1]['lap_flag'] == 'yellow'

    def test_dead_zone_between_thresholds_has_no_flag(self):
        laps = self._laps(78.0, 78.6)
        assert laps[1]['lap_flag'] is None

    def test_invalid_lap_is_red_and_excluded_from_best(self):
        laps = self._laps(70.0, 78.0, invalid=(1,))
        assert laps[0]['lap_flag'] == 'red'
        assert laps[1]['lap_flag'] == 'magenta'   # best among clean laps

    def test_rewound_lap_unflagged_and_excluded_from_best(self):
        laps = self._laps(70.0, 78.0, rewinds=(1,))
        assert laps[0]['lap_flag'] is None
        assert laps[1]['lap_flag'] == 'magenta'

    def test_sector_flags(self):
        rows = [_lap(1, 80.0, s1='20.0', s2='30.0', s3='30.0'),
                _lap(2, 79.0, s1='19.5', s2='29.8', s3='29.7')]
        laps = parse(_typed_csv('S,game,f1_25', LAP_HEADER, *rows))['laps']
        assert laps[1]['s1_flag'] == 'magenta'
        assert laps[0]['s1_flag'] is None         # 0.5 off best → dead zone

    def test_all_invalid_session_has_no_best(self):
        session = parse(_typed_csv(
            'S,game,f1_25', LAP_HEADER, _lap(1, 80.0, invalid='1')))
        assert session['best_lap_time'] is None
        assert session['laps'][0]['lap_flag'] == 'red'


class TestDeltaRecomputed:
    """delta is recomputed from the raw laps (best CLEAN lap so far), never
    trusted from the stored CSV column — so a fix to this logic, or a file
    written before one existed (e.g. pre-v0.44.0's live-telemetry race
    condition), is retroactive without rewriting old CSVs. Same convention
    as best_lap_time/clean_lap_count elsewhere."""

    def _laps(self, *times, invalid=(), rewinds=(), stored_delta=None):
        rows = [
            _lap(i + 1, t,
                 invalid='1' if (i + 1) in invalid else '0',
                 rewinds='1' if (i + 1) in rewinds else '0',
                 delta=(stored_delta or {}).get(i + 1, ''))
            for i, t in enumerate(times)
        ]
        return parse(_typed_csv('S,game,f1_25', LAP_HEADER, *rows))['laps']

    def test_first_clean_lap_has_no_delta(self):
        laps = self._laps(90.0)
        assert laps[0]['delta'] is None

    def test_delta_is_vs_the_running_clean_best_not_the_previous_lap(self):
        laps = self._laps(90.0, 89.0, 92.0)
        assert laps[1]['delta'] == -1.0    # 89.0 - 90.0 — lap 2 becomes the new best
        assert laps[2]['delta'] == 3.0     # 92.0 - 89.0, not vs lap 2's own time

    def test_stored_csv_delta_is_ignored_not_trusted(self):
        # A file written by the buggy pre-v0.44.0 logger — the stored value
        # must never leak through; it's fully recomputed.
        laps = self._laps(90.0, 89.0, stored_delta={1: '0.0', 2: '-0.004'})
        assert laps[0]['delta'] is None
        assert laps[1]['delta'] == -1.0

    def test_invalid_lap_gets_a_delta_but_never_becomes_the_new_best(self):
        laps = self._laps(90.0, 85.0, 89.0, invalid=(2,))
        assert laps[1]['delta'] == -5.0    # 85.0 - 90.0 — vs the clean best
        assert laps[2]['delta'] == -1.0    # 89.0 - 90.0 — lap 2 never became best

    def test_rewound_lap_gets_a_delta_but_never_becomes_the_new_best(self):
        laps = self._laps(90.0, 85.0, 89.0, rewinds=(2,))
        assert laps[1]['delta'] == -5.0
        assert laps[2]['delta'] == -1.0

    def test_no_clean_lap_at_all_gives_every_delta_none(self):
        laps = self._laps(90.0, 85.0, invalid=(1, 2))
        assert laps[0]['delta'] is None
        assert laps[1]['delta'] is None


# ---------------------------------------------------------------------------
# Rewind / duplicate-row handling
# ---------------------------------------------------------------------------

class TestRowDeduplication:
    def test_consecutive_duplicate_lap_numbers_dropped(self):
        rows = [_lap(1, 80.0), _lap(2, 79.0), _lap(2, 79.0), _lap(3, 78.0)]
        laps = parse(_typed_csv('S,game,f1_25', LAP_HEADER, *rows))['laps']
        assert [lap['num'] for lap in laps] == [1, 2, 3]

    def test_counter_reset_between_stints_preserved(self):
        rows = [_lap(1, 80.0), _lap(2, 79.0), _lap(1, 81.0)]
        laps = parse(_typed_csv('S,game,f1_25', LAP_HEADER, *rows))['laps']
        assert [lap['num'] for lap in laps] == [1, 2, 1]


# ---------------------------------------------------------------------------
# Events → per-lap restarts
# ---------------------------------------------------------------------------

class TestEvents:
    def test_restart_events_counted_per_lap(self):
        text = _typed_csv(
            'S,game,f1_25',
            'EH,lap_num,lap_time,type',
            'E,2,45.1,restart',
            'E,2,50.3,restart',
            LAP_HEADER, _lap(1, 80.0), _lap(2, 79.0))
        session = parse(text)
        assert session['laps'][0]['restarts'] == 0
        assert session['laps'][1]['restarts'] == 2

    def test_incomplete_event_rows_skipped(self):
        text = _typed_csv(
            'S,game,f1_25',
            'EH,lap_num,lap_time,type',
            'E,,52.0,rewind',
            LAP_HEADER, _lap(1, 80.0))
        assert parse(text)['events'] == []


# ---------------------------------------------------------------------------
# scan_session — fast summary scan
# ---------------------------------------------------------------------------

class TestScanSession:
    def test_scan_sample_file(self):
        record = scan_session(SAMPLE)
        assert record['best_lap_time'] == 68.6
        assert record['lap_count'] == 3
        assert record['track'] == 'Monaco'
        assert record['session_type'] == 'qualifying'

    def test_scan_unreadable_file_returns_none(self):
        assert scan_session('/nonexistent/nope.csv') is None

    def test_scan_file_without_laps_returns_none(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_practice.csv'
        p.write_text('S,game,f1_25\n')
        assert scan_session(str(p)) is None

    def test_scan_best_excludes_invalid_and_rewound_laps(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_practice.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', 'S,track,Monza', LAP_HEADER,
            _lap(1, 66.0, s1='20.0', s2='24.0', s3='22.0', invalid='1'),
            _lap(2, 67.0, s1='20.5', s2='24.2', s3='22.3', rewinds='2'),
            _lap(3, 68.0, s1='20.9', s2='24.5', s3='22.6')))
        record = scan_session(str(p))
        assert record['best_lap_time'] == 68.0
        assert record['best_s1'] == 20.9
        assert record['best_s2'] == 24.5
        assert record['best_s3'] == 22.6
        assert record['lap_count'] == 3

    def test_scan_counts_rewind_events_off_the_lap_table(self, tmp_path):
        # A flashback on a lap with no L row (e.g. a race's final lap)
        # only exists in the event stream — the scan must still count
        # it so the graded record agrees with the coaching notes.
        p = tmp_path / 'session_20260101_1200_race.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', 'S,session_type,race', LAP_HEADER,
            _lap(1, 70.0), _lap(2, 69.5), _lap(3, 69.8),
            'EH,lap_num,lap_time,type,distance,t',
            'E,4,95.2,rewind,,481.6'))
        record = scan_session(str(p))
        assert record['rewind_count'] == 1
        assert record['lap_count'] == 3

    def test_scan_no_clean_laps_gives_none_best(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_practice.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', LAP_HEADER, _lap(1, 66.0, invalid='1')))
        record = scan_session(str(p))
        assert record is not None
        assert record['best_lap_time'] is None
        assert record['best_s1'] is None
        assert record['lap_count'] == 1

    def test_scan_driver_race_time_and_position_from_standings(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_race.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', 'S,session_type,race', 'S,driver_name,PIASTRI',
            LAP_HEADER,
            _lap(1, 70.0, position='3'), _lap(2, 69.5, position='2'),
            'RH,position,race_num,name,best_lap,race_time',
            'R,1,1,Verstappen,68.9,5120.334',
            'R,2,81,Piastri,69.5,5123.001'))
        record = scan_session(str(p))
        assert record['driver_name'] == 'PIASTRI'
        assert record['race_time'] == 5123.001
        assert record['position'] == 2

    def test_scan_position_falls_back_to_last_lap(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_race.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', LAP_HEADER,
            _lap(1, 70.0, position='5'), _lap(2, 69.5, position='4')))
        record = scan_session(str(p))
        assert record['race_time'] is None
        assert record['position'] == 4


# ---------------------------------------------------------------------------
# scan_session — grading facts (valid/clean counts, std dev, theo, rewinds)
# ---------------------------------------------------------------------------

class TestScanGradingFacts:
    def test_counts_std_dev_theo_and_rewinds(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_practice.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', 'S,track,Silverstone', 'S,session_type,practice',
            LAP_HEADER,
            _lap(1, 90.0, s1='30.0', s2='30.0', s3='30.0'),
            _lap(2, 88.0, s1='29.5', s2='29.3', s3='29.2'),
            _lap(3, 92.0, invalid='1'),
            _lap(4, 89.0, rewinds='2'),
            _lap(5, 95.0, s1='29.8', s2='29.9', s3='29.8'),
            'EH,lap_num,lap_time,type,distance,t',
            'E,5,12.0,pit_in,,410.5'))
        record = scan_session(str(p))
        assert record['lap_count'] == 5
        assert record['valid_lap_count'] == 4       # lap 3 invalid
        assert record['clean_lap_count'] == 3       # lap 4 rewound too
        assert record['rewind_count'] == 2
        # Theoretical: best clean sectors (laps 1, 2, 5).
        assert record['theo_time'] == pytest.approx(29.5 + 29.3 + 29.2)
        # Consistency: clean laps minus the pit lap 5 → [90.0, 88.0].
        assert record['clean_std_dev'] == pytest.approx(2 ** 0.5)

    def test_assist_used_lap_counts(self, tmp_path):
        # Feeds sessionlog.goals' "reduce assist reliance" mission — counts
        # laps where each of the 4 coached assists reached above off/manual.
        header = ('H,lap_num,lap_time,assist_tc,assist_abs,assist_racing_line,'
                  'assist_gearbox')
        p = tmp_path / 'session_20260101_1200_practice.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', header,
            'L,1,90.0,0,0,0,0',
            'L,2,88.0,2,0,1,0',   # TC + racing line on
            'L,3,89.0,0,1,0,2',   # ABS + auto gearbox on
        ))
        record = scan_session(str(p))
        assert record['tc_used_lap_count'] == 1
        assert record['abs_used_lap_count'] == 1
        assert record['racing_line_used_lap_count'] == 1
        assert record['gearbox_assist_used_lap_count'] == 1

    def test_assist_used_lap_counts_zero_when_columns_absent(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_practice.csv'
        p.write_text(_typed_csv('S,game,f1_25', LAP_HEADER, _lap(1, 90.0)))
        record = scan_session(str(p))
        assert record['tc_used_lap_count'] == 0
        assert record['abs_used_lap_count'] == 0
        assert record['racing_line_used_lap_count'] == 0
        assert record['gearbox_assist_used_lap_count'] == 0

    def test_race_lap_1_excluded_from_std_dev(self, tmp_path):
        # Standing start and first-lap traffic — lap 1 never represents
        # race pace. Std dev over laps 2–4 only.
        fn   = 'session_20260101_1200_race.csv'
        text = _typed_csv(
            'S,game,f1_25', 'S,session_type,race', LAP_HEADER,
            _lap(1, 99.0), _lap(2, 90.0), _lap(3, 88.0), _lap(4, 89.0))
        p = tmp_path / fn
        p.write_text(text)
        record = scan_session(str(p))
        from statistics import stdev
        assert record['clean_std_dev'] == pytest.approx(stdev([90.0, 88.0, 89.0]))
        assert record['cons_lap_count'] == 3
        # Dashboard path (session_facts) must apply the same exclusion.
        from sessionlog.grading import session_facts
        facts = session_facts(parse(text, filename=fn))
        assert facts['clean_std_dev'] == record['clean_std_dev']
        assert facts['cons_lap_count'] == record['cons_lap_count']

    def test_non_race_lap_1_stays_in_std_dev(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_practice.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', 'S,session_type,practice', LAP_HEADER,
            _lap(1, 90.0), _lap(2, 88.0), _lap(3, 89.0)))
        record = scan_session(str(p))
        assert record['cons_lap_count'] == 3

    def test_sc_period_laps_excluded_from_std_dev(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_race.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', LAP_HEADER,
            _lap(1, 90.0), _lap(2, 110.0), _lap(3, 111.0), _lap(4, 88.0),
            'EH,lap_num,lap_time,type,distance',
            'E,2,5.0,sc_deploy,', 'E,3,40.0,sc_clear,'))
        record = scan_session(str(p))
        assert record['clean_std_dev'] == pytest.approx(2 ** 0.5)

    def test_std_dev_and_theo_none_when_insufficient_laps(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_practice.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', LAP_HEADER, _lap(1, 66.0, s1='20.0', s2='24.0', s3='22.0')))
        record = scan_session(str(p))
        assert record['clean_std_dev'] is None
        assert record['theo_time'] is None
        assert record['rewind_count'] == 0

    def test_clean_streak(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_practice.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', LAP_HEADER,
            _lap(1, 90.0), _lap(2, 90.1), _lap(3, 92.0, invalid='1'),
            _lap(4, 90.2), _lap(5, 90.3), _lap(6, 90.1)))
        assert scan_session(str(p))['clean_streak'] == 3

    def test_cooldown_laps_excluded_from_std_dev(self, tmp_path):
        # Qualifying pattern: push, cool-down, push — the deliberate slow
        # lap must not read as inconsistency.
        p = tmp_path / 'session_20260101_1200_qualifying.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', 'S,session_type,qualifying', LAP_HEADER,
            _lap(1, 90.0), _lap(2, 110.0), _lap(3, 88.0)))
        record = scan_session(str(p))
        assert record['clean_std_dev'] == pytest.approx(2 ** 0.5)

    def test_cooldown_detection_is_race_safe_and_needs_bounding_push_laps(self):
        from sessionlog.parser import cooldown_laps
        laps = [(1, 90.0), (2, 110.0), (3, 88.0)]
        assert cooldown_laps(laps, 'qualifying') == {2}
        # A slow race lap is real — never excluded.
        assert cooldown_laps(laps, 'race') == set()
        # Trailing slow lap (no push lap after it) is not assumed deliberate.
        assert cooldown_laps([(1, 90.0), (2, 88.0), (3, 110.0)],
                             'qualifying') == set()
        # A run of consecutive cool-downs between push laps is excluded.
        assert cooldown_laps([(1, 90.0), (2, 108.0), (3, 111.0), (4, 88.5)],
                             'practice') == {2, 3}

    def test_pit_lap_in_the_triple_disqualifies_the_pattern(self):
        from sessionlog.parser import cooldown_laps
        # Lap 2 was a pit lap (already stripped) — laps 1 and 3 were not
        # adjacent on track, so lap 3 must not be claimed as a cool-down.
        eligible = [(1, 90.0), (3, 108.0), (4, 90.0)]
        assert cooldown_laps(eligible, 'qualifying', blocked={2}) == set()
        # A pit lap between the slow lap and the FOLLOWING push lap
        # disqualifies too.
        eligible = [(1, 90.0), (2, 108.0), (4, 90.0)]
        assert cooldown_laps(eligible, 'qualifying', blocked={3}) == set()
        # An invalid lap in the gap is not a pit lap — pattern still holds
        # (the eligible sequence skips it, but nothing was pit-flagged).
        eligible = [(1, 90.0), (3, 108.0), (4, 90.0)]
        assert cooldown_laps(eligible, 'qualifying', blocked=set()) == {3}

    def test_scan_pit_adjacent_slow_lap_stays_in_std_dev(self, tmp_path):
        # push, pit lap, slow, push — the slow lap follows a pit visit, so
        # it is NOT a push→cool→push cool-down and must stay in the maths.
        p = tmp_path / 'session_20260101_1200_qualifying.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', 'S,session_type,qualifying', LAP_HEADER,
            _lap(1, 90.0), _lap(2, 115.0), _lap(3, 108.0), _lap(4, 90.0),
            'EH,lap_num,lap_time,type,distance',
            'E,2,10.0,pit_in,', 'E,2,40.0,pit_out,'))
        record = scan_session(str(p))
        # std dev over [90.0, 108.0, 90.0] — lap 2 out (pit), lap 3 in.
        from statistics import stdev
        assert record['clean_std_dev'] == pytest.approx(stdev([90.0, 108.0, 90.0]))

    def test_on_pace_band_counts(self, tmp_path):
        # Band = within 1% of the session's best consistency-eligible lap;
        # cool-down laps are outside the denominator entirely.
        p = tmp_path / 'session_20260101_1200_qualifying.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', 'S,session_type,qualifying', LAP_HEADER,
            _lap(1, 90.0), _lap(2, 110.0), _lap(3, 90.5), _lap(4, 93.0),
            _lap(5, 90.2)))
        record = scan_session(str(p))
        # Lap 2 is a cool-down (push→slow→push); of [90.0, 90.5, 93.0,
        # 90.2], within 90.0×1.01 = 90.9 → laps 1, 3, 5.
        assert record['cons_lap_count'] == 4
        assert record['cons_band_count'] == 3

    def test_flat_format_gets_facts_too(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_practice.csv'
        p.write_text('lap_num,lap_time,car_class,session_type,game\n'
                     '1,77.5,gt3,practice,acc\n'
                     '2,78.1,gt3,practice,acc\n')
        record = scan_session(str(p))
        assert record['valid_lap_count'] == 2
        assert record['clean_lap_count'] == 2
        assert record['rewind_count'] == 0
        assert record['theo_time'] is None

    def test_scan_facts_agree_with_session_facts_on_parsed_session(self, tmp_path):
        # The DB row (picker grade) and the parsed session (dashboard grade)
        # must produce identical facts for the same CSV.
        from sessionlog.grading import session_facts
        text = _typed_csv(
            'S,game,f1_25', 'S,track,Silverstone', 'S,session_type,practice',
            LAP_HEADER,
            _lap(1, 90.0, s1='30.0', s2='30.0', s3='30.0'),
            _lap(2, 88.0, s1='29.5', s2='29.3', s3='29.2'),
            _lap(3, 92.0, invalid='1'),
            _lap(4, 89.0, s1='29.9', s2='29.8', s3='29.7', rewinds='1'),
            _lap(5, 89.5, s1='29.8', s2='29.9', s3='29.8'),
            'EH,lap_num,lap_time,type,distance,t',
            'E,5,12.0,pit_in,,388.0')
        fn = 'session_20260101_1200_practice.csv'
        p = tmp_path / fn
        p.write_text(text)
        record = scan_session(str(p))
        facts = session_facts(parse(text, filename=fn))
        for key in ('lap_count', 'valid_lap_count', 'clean_lap_count',
                    'clean_std_dev', 'theo_time', 'rewind_count',
                    'clean_streak', 'cons_lap_count', 'cons_band_count',
                    'best_lap_time'):
            assert facts[key] == record[key], key


# ---------------------------------------------------------------------------
# Session subtype (v0.1.133+) — sprint qualifying etc.
# ---------------------------------------------------------------------------

class TestSessionSubtype:
    def test_subtype_parsed_from_s_rows(self):
        session = parse(_typed_csv(
            'S,game,f1_25', 'S,session_type,qualifying',
            'S,session_subtype,sprint_qualifying', 'S,session_type_raw,10',
            LAP_HEADER, _lap(1, 80.0)))
        assert session['session_type'] == 'qualifying'
        assert session['session_subtype'] == 'sprint_qualifying'

    def test_subtype_empty_when_missing(self):
        # Plain sessions and pre-v0.1.133 files have no subtype key.
        session = parse(_typed_csv(
            'S,game,f1_25', 'S,session_type,qualifying',
            LAP_HEADER, _lap(1, 80.0)))
        assert session['session_subtype'] == ''

    def test_scan_carries_subtype(self, tmp_path):
        p = tmp_path / 'session_20260712_1405_sprint_qualifying.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', 'S,session_type,qualifying',
            'S,session_subtype,sprint_qualifying',
            LAP_HEADER, _lap(1, 80.0)))
        record = scan_session(str(p))
        assert record['session_type'] == 'qualifying'
        assert record['session_subtype'] == 'sprint_qualifying'

    def test_session_label_prefers_subtype(self):
        assert session_label({'session_type': 'qualifying',
                              'session_subtype': 'sprint_qualifying'}) \
            == 'sprint_qualifying'
        assert session_label({'session_type': 'race',
                              'session_subtype': ''}) == 'race'
        assert session_label({}) == ''


# ---------------------------------------------------------------------------
# Filename fallback — collision suffixes and subtype labels
# ---------------------------------------------------------------------------

class TestFilenameFallback:
    # Exercised through the flat format, which has no S rows to prefer.
    FLAT = 'lap_num,lap_time,game\n1,90.0,fm\n'

    def test_collision_suffix_stripped(self):
        session = parse(self.FLAT, 'session_20260101_1200_race_2.csv')
        assert session['session_type'] == 'race'
        assert session['date'] == datetime(2026, 1, 1, 12, 0)

    def test_subtype_label_maps_to_parent_type(self):
        session = parse(self.FLAT,
                        'session_20260712_1405_sprint_qualifying.csv')
        assert session['session_type'] == 'qualifying'


# ---------------------------------------------------------------------------
# Event t column (v0.1.133+) and rewind-data reliability
# ---------------------------------------------------------------------------

class TestEventTimeAndReliability:
    def test_event_t_column_parsed(self):
        session = parse(_typed_csv(
            'S,game,f1_25',
            'EH,lap_num,lap_time,type,distance,t',
            'E,2,5.1,pit_in,88.2,192.4',
            'E,2,28.4,pit_out,441.0,215.7',
            LAP_HEADER, _lap(1, 80.0), _lap(2, 81.0)))
        assert session['events'][0]['t'] == 192.4
        # Pit stop duration comes from t, never lap_time deltas.
        assert session['events'][1]['t'] - session['events'][0]['t'] \
            == pytest.approx(23.3)
        assert session['rewinds_reliable'] is True

    def test_old_file_with_pit_events_has_untrusted_rewinds(self, tmp_path):
        # Pre-v0.1.133 (no t column) files log spurious rewinds around pit
        # stops — the rewind count must read as unknown, not as mistakes.
        text = _typed_csv(
            'S,game,f1_25',
            'EH,lap_num,lap_time,type,distance',
            'E,2,5.1,pit_in,', 'E,2,7.0,rewind,',
            LAP_HEADER, _lap(1, 80.0), _lap(2, 81.0, rewinds='1'))
        session = parse(text)
        assert session['rewinds_reliable'] is False
        fn = 'session_20260101_1200_practice.csv'
        p = tmp_path / fn
        p.write_text(text)
        record = scan_session(str(p))
        assert record['rewind_count'] is None
        from sessionlog.grading import session_facts
        assert session_facts(session)['rewind_count'] is None

    def test_old_file_without_pit_events_keeps_rewinds(self, tmp_path):
        # No pit visits → nothing for the spurious detection to cluster
        # around, so the rewinds were real.
        p = tmp_path / 'session_20260101_1200_hotlap.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25',
            'EH,lap_num,lap_time,type,distance',
            'E,2,7.0,rewind,',
            LAP_HEADER, _lap(1, 80.0), _lap(2, 81.0, rewinds='1')))
        record = scan_session(str(p))
        assert record['rewind_count'] == 1

    def test_new_file_with_pit_events_keeps_rewinds(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_race.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25',
            'EH,lap_num,lap_time,type,distance,t',
            'E,2,5.1,pit_in,,192.4', 'E,3,7.0,rewind,,300.2',
            LAP_HEADER, _lap(1, 80.0), _lap(2, 81.0),
            _lap(3, 80.5, rewinds='1')))
        record = scan_session(str(p))
        assert record['rewind_count'] == 1


# ---------------------------------------------------------------------------
# Lap classification — out / in / sc / start / cooldown
# ---------------------------------------------------------------------------

class TestClassifyLaps:
    def test_out_in_and_inout_laps(self):
        # Genuine transit laps are many seconds off push pace.
        session = parse(_typed_csv(
            'S,game,f1_25', 'S,session_type,practice',
            'EH,lap_num,lap_time,type,distance,t',
            'E,1,2.0,pit_out,,5.0',        # leaves garage on lap 1
            'E,3,80.0,pit_in,,250.0',      # enters pits on lap 3
            'E,5,10.0,pit_in,,400.0',      # in and out on lap 5
            'E,5,40.0,pit_out,,430.0',
            LAP_HEADER,
            _lap(1, 108.0), _lap(2, 90.0), _lap(3, 111.0),
            _lap(4, 90.2), _lap(5, 122.0), _lap(6, 90.1)))
        classes = classify_laps(session)
        assert classes[1] == 'out'
        assert classes[3] == 'in'
        assert classes[5] == 'in/out'
        assert 2 not in classes and 4 not in classes and 6 not in classes

    def test_pit_tagged_lap_at_push_pace_is_the_flyer(self):
        # F1 qualifying books garage transit onto the flyer's lap number
        # (real race-weekend data): pit events land on laps completed at
        # full pace. Those laps are flyers, not transit — no tag, and
        # they stay in the consistency maths.
        session = parse(_typed_csv(
            'S,game,f1_25', 'S,session_type,qualifying',
            'EH,lap_num,lap_time,type,distance,t',
            'E,1,0.0,pit_in,68.7,0.0',       # session opens in garage
            'E,1,0.0,pit_out,-5512.6,38.7',  # garage-exit teleport
            'E,2,89.8,pit_in,5574.5,318.5',  # between-runs garage visit
            'E,2,0.0,pit_out,378.4,525.7',
            LAP_HEADER,
            _lap(1, 92.123), _lap(2, 92.131)))
        assert classify_laps(session) == {}
        from sessionlog.grading import session_facts
        facts = session_facts(session)
        assert facts['cons_lap_count'] == 2
        assert facts['clean_std_dev'] == pytest.approx(0.008 / 2 ** 0.5,
                                                       rel=1e-3)

    def test_race_lap_1_is_start_and_sc_window_marked(self):
        session = parse(_typed_csv(
            'S,game,f1_25', 'S,session_type,race',
            'EH,lap_num,lap_time,type,distance,t',
            'E,3,5.0,sc_deploy,,200.0', 'E,4,40.0,sc_clear,,320.0',
            LAP_HEADER,
            *[_lap(i, 90.0) for i in range(1, 6)]))
        classes = classify_laps(session)
        assert classes[1] == 'start'
        assert classes[3] == 'sc' and classes[4] == 'sc'
        assert 5 not in classes

    def test_pit_label_wins_over_sc(self):
        session = parse(_typed_csv(
            'S,game,f1_25', 'S,session_type,race',
            'EH,lap_num,lap_time,type,distance,t',
            'E,2,5.0,sc_deploy,,100.0',
            'E,3,10.0,pit_in,,200.0',      # pit stop under the SC
            'E,3,40.0,pit_out,,230.0',
            'E,4,20.0,sc_clear,,300.0',
            LAP_HEADER,
            _lap(1, 90.0), _lap(2, 105.0), _lap(3, 115.0),
            _lap(4, 104.0), _lap(5, 90.2)))
        classes = classify_laps(session)
        assert classes[3] == 'in/out'
        assert classes[2] == 'sc' and classes[4] == 'sc'

    def test_cooldown_marked_in_non_race(self):
        session = parse(_typed_csv(
            'S,game,f1_25', 'S,session_type,qualifying', LAP_HEADER,
            _lap(1, 90.0), _lap(2, 110.0), _lap(3, 88.0)))
        assert classify_laps(session) == {2: 'cooldown'}

    def test_no_events_race_free_session_is_all_representative(self):
        session = parse(_typed_csv(
            'S,game,f1_25', 'S,session_type,hotlap', LAP_HEADER,
            _lap(1, 90.0), _lap(2, 90.2)))
        assert classify_laps(session) == {}


# ---------------------------------------------------------------------------
# Qualifying outcome — position and gaps from the standings
# ---------------------------------------------------------------------------

class TestQualifyingOutcome:
    STANDINGS = (
        'RH,position,race_num,name,best_lap,race_time',
        'R,1,1,Verstappen,88.0,',
        'R,2,4,Norris,88.5,',
        'R,3,81,Piastri,88.9,',
        'R,4,16,Leclerc,89.2,',
        'R,5,55,Sainz,,',          # no clean lap — skipped for gaps
    )

    def _session(self, driver='PIASTRI', session_type='qualifying'):
        return parse(_typed_csv(
            'S,game,f1_25', f'S,session_type,{session_type}',
            f'S,driver_name,{driver}',
            LAP_HEADER, _lap(1, 88.9),
            *self.STANDINGS))

    def test_position_and_gaps(self):
        o = qualifying_outcome(self._session())
        assert o['position'] == 3
        assert o['total'] == 5
        assert o['best'] is not None   # the classified lap that set the grid
        assert o['pole']['name'] == 'Verstappen'
        assert o['pole']['gap'] == pytest.approx(0.9)
        assert o['ahead']['name'] == 'Norris'
        assert o['ahead']['gap'] == pytest.approx(0.4)
        assert o['behind']['name'] == 'Leclerc'
        assert o['behind']['gap'] == pytest.approx(0.3)

    def test_pole_sitter_has_no_pole_or_ahead_gap(self):
        o = qualifying_outcome(self._session(driver='Verstappen'))
        assert o['position'] == 1
        assert o['pole'] is None
        assert o['ahead'] is None
        assert o['behind']['name'] == 'Norris'
        assert o['behind']['gap'] == pytest.approx(0.5)

    def test_none_outside_qualifying_or_without_driver(self):
        assert qualifying_outcome(self._session(session_type='race')) is None
        assert qualifying_outcome(self._session(driver='')) is None
        assert qualifying_outcome(self._session(driver='HAMILTON')) is None

    def test_car_without_best_lap_is_skipped_for_gaps(self):
        o = qualifying_outcome(self._session(driver='Leclerc'))
        assert o['position'] == 4
        assert o['behind'] is None    # P5 has no best lap → no gap


# ---------------------------------------------------------------------------
# Tyre stints — consecutive laps split on compound change
# ---------------------------------------------------------------------------

class TestTyreStints:
    def _session(self, *compounds):
        rows = [_lap(i + 1, 90.0 + i * 0.1, compound=c)
                for i, c in enumerate(compounds)]
        return parse(_typed_csv('S,game,f1_25', LAP_HEADER, *rows))

    def test_split_on_compound_change(self):
        stints = tyre_stints(self._session('Medium', 'Medium', 'Hard', 'Hard'))
        assert [(s['compound'], len(s['laps'])) for s in stints] == [
            ('Medium', 2), ('Hard', 2)]
        assert [lap['num'] for lap in stints[1]['laps']] == [3, 4]

    def test_missing_compound_continues_the_stint(self):
        stints = tyre_stints(self._session('Medium', '', 'Medium'))
        assert [(s['compound'], len(s['laps'])) for s in stints] == [
            ('Medium', 3)]

    def test_leading_unknown_laps_join_the_first_named_stint(self):
        stints = tyre_stints(self._session('', 'Soft', 'Soft'))
        assert [(s['compound'], len(s['laps'])) for s in stints] == [
            ('Soft', 3)]

    def test_no_compound_data_is_one_unknown_stint(self):
        stints = tyre_stints(self._session('', '', ''))
        assert [(s['compound'], len(s['laps'])) for s in stints] == [
            (None, 3)]

    def test_empty_session_has_no_stints(self):
        assert tyre_stints({'laps': []}) == []


class TestStintStdDev:
    def test_single_group_matches_stdev(self):
        from statistics import stdev
        times = [90.0, 90.4, 90.2]
        assert stint_std_dev([times]) == pytest.approx(stdev(times))

    def test_pooled_within_groups(self):
        # Two tight stints 2s apart: within-stint spread is small even
        # though the combined spread is large.
        pooled = stint_std_dev([[90.0, 90.2], [92.0, 92.2]])
        assert pooled == pytest.approx((0.04 / 2) ** 0.5)
        from statistics import stdev
        assert pooled < stdev([90.0, 90.2, 92.0, 92.2])

    def test_single_lap_groups_contribute_nothing(self):
        assert stint_std_dev([[90.0], [92.0]]) is None
        assert stint_std_dev([]) is None

    def test_scan_std_dev_is_within_stints(self, tmp_path):
        # Practice: Medium run, pit for Hards, Hard run — the 2s compound
        # offset must not read as inconsistency.
        fn   = 'session_20260101_1200_practice.csv'
        text = _typed_csv(
            'S,game,f1_25', 'S,session_type,practice', LAP_HEADER,
            _lap(1, 90.0, compound='Medium'),
            _lap(2, 90.2, compound='Medium'),
            _lap(3, 95.0, compound='Medium'),   # pit lap — excluded anyway
            _lap(4, 92.0, compound='Hard'),
            _lap(5, 92.2, compound='Hard'),
            'EH,lap_num,lap_time,type,distance,t',
            'E,3,10.0,pit_in,,300.0', 'E,3,40.0,pit_out,,330.0')
        p = tmp_path / fn
        p.write_text(text)
        record = scan_session(str(p))
        assert record['clean_std_dev'] == pytest.approx((0.04 / 2) ** 0.5)
        # Dashboard path must agree.
        from sessionlog.grading import session_facts
        facts = session_facts(parse(text, filename=fn))
        assert facts['clean_std_dev'] == pytest.approx(record['clean_std_dev'])


# ---------------------------------------------------------------------------
# v0.1.135 events — detail column, collisions, penalties, overtakes
# ---------------------------------------------------------------------------

class TestDetailEvents:
    CSV = (
        'S,game,f1_25', 'S,session_type,race',
        'EH,lap_num,lap_time,type,distance,t,detail',
        'E,2,38.115,collision,1740.2,131.6,VERSTAPPEN',
        'E,2,44.712,rewind,,138.2,',
        'E,3,55.310,overtake,3105.8,242.6,LECLERC',
        'E,4,12.402,overtaken,801.1,350.9,SAINZ',
        'E,4,30.001,penalty,,368.5,warning:big_collision:VERSTAPPEN',
        LAP_HEADER,
        *[f'L,{i},9{i}.0,,,,,,,,,,,,,0,0' for i in range(1, 6)],
    )

    def test_detail_parsed_and_empty_is_none(self):
        events = parse(_typed_csv(*self.CSV))['events']
        by_type = {e['type']: e for e in events}
        assert by_type['collision']['detail'] == 'VERSTAPPEN'
        assert by_type['overtake']['detail'] == 'LECLERC'
        assert by_type['overtaken']['detail'] == 'SAINZ'
        assert by_type['rewind']['detail'] is None

    def test_scan_counts_collisions_and_penalties(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_race.csv'
        p.write_text(_typed_csv(*self.CSV))
        record = scan_session(str(p))
        assert record['collision_count'] == 1
        assert record['penalty_count'] == 1
        from sessionlog.grading import session_facts
        facts = session_facts(parse(_typed_csv(*self.CSV)))
        assert facts['collision_count'] == record['collision_count']
        assert facts['penalty_count'] == record['penalty_count']

    def test_old_files_count_zero(self, tmp_path):
        p = tmp_path / 'session_20260101_1200_race.csv'
        p.write_text(_typed_csv(
            'S,game,f1_25', LAP_HEADER, _lap(1, 90.0), _lap(2, 90.1),
            _lap(3, 90.2)))
        record = scan_session(str(p))
        assert record['collision_count'] == 0
        assert record['penalty_count'] == 0


class TestPenaltyDetail:
    def test_full_detail(self):
        assert penalty_detail('warning:big_collision:VERSTAPPEN') == {
            'penalty': 'warning', 'infringement': 'big collision',
            'driver': 'VERSTAPPEN'}

    def test_without_driver(self):
        assert penalty_detail('time_penalty:corner_cutting_gained_time') == {
            'penalty': 'time penalty',
            'infringement': 'corner cutting gained time', 'driver': None}

    def test_empty(self):
        assert penalty_detail('') == {'penalty': None, 'infringement': None,
                                      'driver': None}
        assert penalty_detail(None) == {'penalty': None, 'infringement': None,
                                        'driver': None}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_format_lap_time(self):
        assert format_lap_time(68.731) == '1:08.731'
        assert format_lap_time(None) == '--:--.---'

    def test_format_sector_time(self):
        assert format_sector_time(21.199) == '21.199'
        assert format_sector_time(None) == '---.---'


# ---------------------------------------------------------------------------
# Racing-line offset profiles (P rows)
# ---------------------------------------------------------------------------

_LINE_HEADER = ("H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,"
                "tyre_compound,fuel_remaining,fuel_per_lap,position,delta,"
                "invalid,rewinds")


def _line_csv():
    return "\n".join([
        "S,version,1", "S,game,f1_25", "S,session_type,hotlap",
        "S,car_class,formula1", "S,track,Ring",
        "S,started_at,2026-07-11T10:00:00", "S,line_ref,3",
        _LINE_HEADER,
        "L,1,90.0,,,,,,,,,,,,,0,0",
        "P,1,5,-3,12,0,-8",
        "L,2,89.5,,,,,,,,,,,,,0,0",
        "P,2,2,-1,4,0,-2",
    ]) + "\n"


def test_p_rows_attach_offsets_in_metres():
    s = parse(_line_csv(), "session_20260711_1000_hotlap.csv")
    assert s["laps"][0]["line_offsets"] == [0.5, -0.3, 1.2, 0.0, -0.8]
    assert s["laps"][1]["line_offsets"] == [0.2, -0.1, 0.4, 0.0, -0.2]
    assert s["line_ref"] == "3"


def test_laps_without_p_rows_have_none_offsets():
    csv = "\n".join([
        "S,version,1", "S,game,f1_25", "S,session_type,hotlap",
        "S,car_class,formula1", _LINE_HEADER, "L,1,90.0,,,,,,,,,,,,,0,0",
    ]) + "\n"
    s = parse(csv, "session_20260711_1000_hotlap.csv")
    assert s["laps"][0]["line_offsets"] is None


def test_scan_line_facts_default_without_profiles(tmp_path):
    csv = "\n".join([
        "S,version,1", "S,game,f1_25", "S,session_type,hotlap",
        "S,car_class,formula1", _LINE_HEADER, "L,1,90.0,,,,,,,,,,,,,0,0",
    ]) + "\n"
    p = tmp_path / "session_20260711_1000_hotlap.csv"
    p.write_text(csv)
    rec = scan_session(str(p))
    assert rec["push_lap_count"] == 0
    assert rec["on_line_session"] is False


def test_scan_line_facts_with_track_map(tmp_path):
    import json
    import math

    from sessionlog import trackmap
    n = 400
    length = 1000.0
    racing = [[100 * math.cos(2 * math.pi * i / n),
               100 * math.sin(2 * math.pi * i / n)] for i in range(n)]
    tmap = {"game": "f1_25", "track": "Ring", "game_track_length_m": length,
            "lines": {"formula1": {"racing_line": racing}},
            "sections": [{"type": "corner", "turn": "1", "name": "Turn 1",
                          "start_m": 100, "end_m": 300, "apex_m": 200}]}
    (tmp_path / "f1-25_ring.json").write_text(json.dumps(tmap))
    trackmap.set_tracks_dir(str(tmp_path))

    on_line = ",".join(["3"] * n)   # 0.3 m everywhere
    rows = ["S,version,1", "S,game,f1_25", "S,session_type,hotlap",
            "S,car_class,formula1", "S,track,Ring",
            "S,started_at,2026-07-11T10:00:00", _LINE_HEADER]
    for ln in (1, 2, 3):
        rows.append(f"L,{ln},90.0,,,,,,,,,,,,,0,0")
        rows.append(f"P,{ln},{on_line}")
    p = tmp_path / "session_20260711_1000_hotlap.csv"
    p.write_text("\n".join(rows) + "\n")

    rec = scan_session(str(p))
    assert rec["push_lap_count"] == 3
    assert rec["on_line_lap_count"] == 3
    assert rec["on_line_session"] is True
    trackmap.set_tracks_dir(None)
