"""
Tests for sessionlog.records — the SQLite index over a session-CSV
directory (the companion's session_db).

Shared test: lives canonically in ShfonicDash/tests/ and is copied
into the companion repo by sync_shared.py.

Each test points the module's CACHE_DIR / DB_PATH at a tmp directory via
monkeypatch, writes small typed-row CSVs, and exercises sync / rebuild /
overall_best. The CSVs are the source of truth throughout.
"""

import sqlite3
from datetime import datetime

import pytest

from sessionlog import records as session_db

LAP_HEADER = ('H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,'
              'tyre_compound,fuel_remaining,fuel_per_lap,position,delta,invalid,rewinds')


def _session_csv(best, track='Monaco', session_type='qualifying',
                 game='f1_25', car_class='formula1_2026',
                 started='2026-06-28T21:14:00', s1='20.1', s2='24.2', s3='22.3'):
    return '\n'.join((
        'S,version,1',
        f'S,started_at,{started}',
        f'S,game,{game}',
        f'S,session_type,{session_type}',
        f'S,car_class,{car_class}',
        'S,car_name,Red Bull Racing',
        f'S,track,{track}',
        LAP_HEADER,
        f'L,1,{best + 1.0},,,,,,,,,,,,,0,0',
        f'L,2,{best},{s1},{s2},{s3},,,,,,,,,,0,0',
    )) + '\n'


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(session_db, 'CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(session_db, 'DB_PATH', str(tmp_path / '.sessions.db'))
    return tmp_path


def _write(cache, filename, text):
    (cache / filename).write_text(text, encoding='utf-8')


class TestSync:
    def test_sync_indexes_new_files(self, cache):
        _write(cache, 'session_20260628_2114_qualifying.csv', _session_csv(68.6))
        _write(cache, 'session_20260629_1000_practice.csv',
               _session_csv(69.2, session_type='practice'))
        added, removed, total = session_db.sync()
        assert (added, removed, total) == (2, 0, 2)

        records = session_db.all_sessions()
        assert [r['filename'] for r in records] == [
            'session_20260629_1000_practice.csv',
            'session_20260628_2114_qualifying.csv',
        ]
        r = records[1]
        assert r['best_lap_time'] == 68.6
        assert (r['best_s1'], r['best_s2'], r['best_s3']) == (20.1, 24.2, 22.3)
        assert r['date'] == datetime(2026, 6, 28, 21, 14)
        assert r['lap_count'] == 2
        # F1 driven distance = lap_count * circuit length (Monaco 3337 m).
        assert r['distance_m'] == 3337 * 2

    def test_distance_none_for_non_f1_game(self, cache):
        _write(cache, 'session_20260628_2114_qualifying.csv',
               _session_csv(68.6, game='acc'))
        session_db.sync()
        r = session_db.all_sessions()[0]
        assert r['distance_m'] is None

    def test_session_subtype_round_trips(self, cache):
        text = _session_csv(70.1).replace(
            'S,session_type,qualifying',
            'S,session_type,qualifying\nS,session_subtype,sprint_qualifying')
        _write(cache, 'session_20260712_1405_sprint_qualifying.csv', text)
        _write(cache, 'session_20260628_2114_qualifying.csv', _session_csv(68.6))
        session_db.sync()
        by_name = {r['filename']: r for r in session_db.all_sessions()}
        sprint = by_name['session_20260712_1405_sprint_qualifying.csv']
        plain  = by_name['session_20260628_2114_qualifying.csv']
        assert sprint['session_type'] == 'qualifying'
        assert sprint['session_subtype'] == 'sprint_qualifying'
        assert plain['session_subtype'] == ''

    def test_sync_is_incremental(self, cache):
        _write(cache, 'session_20260628_2114_qualifying.csv', _session_csv(68.6))
        session_db.sync()
        added, removed, total = session_db.sync()
        assert (added, removed, total) == (0, 0, 1)

    def test_sync_drops_rows_for_deleted_files(self, cache):
        _write(cache, 'session_20260628_2114_qualifying.csv', _session_csv(68.6))
        session_db.sync()
        (cache / 'session_20260628_2114_qualifying.csv').unlink()
        added, removed, total = session_db.sync()
        assert (added, removed, total) == (0, 1, 0)

    def test_sync_rescans_changed_files(self, cache):
        # Content heal: a row whose file size/mtime no longer match is
        # re-scanned in place — a CSV first scanned while still
        # materialising (iCloud mid-download) must not leave a bogus row
        # behind forever (it once put a +94s gap in the trend).
        import os
        fn = 'session_20260628_2114_qualifying.csv'
        _write(cache, fn, _session_csv(68.6))
        session_db.sync()
        _write(cache, fn, _session_csv(67.0))
        os.utime(cache / fn, (1e9, 1e9))     # force a visible mtime change
        added, removed, total = session_db.sync()
        assert (added, removed, total) == (1, 0, 1)
        assert session_db.all_sessions()[0]['best_lap_time'] == 67.0

    def test_sync_records_file_meta(self, cache):
        import os
        fn = 'session_20260628_2114_qualifying.csv'
        _write(cache, fn, _session_csv(68.6))
        session_db.sync()
        st = os.stat(cache / fn)
        r = session_db.all_sessions()[0]
        assert r['file_size'] == st.st_size
        assert r['file_mtime'] == st.st_mtime
        # …and an unchanged file is left alone on the next sync.
        added, removed, total = session_db.sync()
        assert (added, removed, total) == (0, 0, 1)

    def test_sync_drops_row_when_changed_file_unreadable(self, cache):
        # A changed file that can't be scanned (still being written) drops
        # its row; the next sync re-adds it once readable.
        import os
        fn = 'session_20260628_2114_qualifying.csv'
        _write(cache, fn, _session_csv(68.6))
        session_db.sync()
        _write(cache, fn, _session_csv(67.0))
        os.utime(cache / fn, (1e9, 1e9))
        real = session_db.scan_session
        session_db.scan_session = lambda path: None
        try:
            added, removed, total = session_db.sync()
        finally:
            session_db.scan_session = real
        assert (added, total) == (0, 0)
        added, removed, total = session_db.sync()
        assert (added, total) == (1, 1)
        assert session_db.all_sessions()[0]['best_lap_time'] == 67.0


class TestRebuild:
    def test_rebuild_rescans_edited_files(self, cache):
        fn = 'session_20260628_2114_qualifying.csv'
        _write(cache, fn, _session_csv(68.6))
        session_db.sync()
        _write(cache, fn, _session_csv(67.0))
        added, removed, total = session_db.rebuild()
        assert (added, total) == (1, 1)
        assert session_db.all_sessions()[0]['best_lap_time'] == 67.0

    def test_rebuild_reports_progress(self, cache):
        _write(cache, 'session_20260628_2114_qualifying.csv', _session_csv(68.6))
        _write(cache, 'session_20260629_1000_practice.csv',
               _session_csv(69.2, session_type='practice'))
        calls = []
        session_db.rebuild(progress=lambda done, total: calls.append((done, total)))
        assert calls == [(1, 2), (2, 2)]


class TestRemove:
    def test_remove_drops_row(self, cache):
        fn = 'session_20260628_2114_qualifying.csv'
        _write(cache, fn, _session_csv(68.6))
        session_db.sync()
        session_db.remove(fn)
        assert session_db.all_sessions() == []


class TestOverallBest:
    def test_picks_fastest_matching_session(self, cache):
        _write(cache, 'session_20260601_1000_qualifying.csv',
               _session_csv(68.9, started='2026-06-01T10:00:00'))
        _write(cache, 'session_20260615_1000_qualifying.csv',
               _session_csv(68.2, started='2026-06-15T10:00:00'))
        _write(cache, 'session_20260620_1000_qualifying.csv',
               _session_csv(69.5, started='2026-06-20T10:00:00'))
        session_db.sync()
        best = session_db.overall_best('f1_25', 'formula1_2026',
                                       'Monaco', 'qualifying')
        assert best['filename'] == 'session_20260615_1000_qualifying.csv'
        assert best['best_lap_time'] == 68.2
        assert best['date'] == datetime(2026, 6, 15, 10, 0)

    def test_scoped_by_track_and_session_type(self, cache):
        _write(cache, 'session_20260601_1000_qualifying.csv',
               _session_csv(66.0, track='Monza'))
        _write(cache, 'session_20260602_1000_race.csv',
               _session_csv(67.0, session_type='race'))
        _write(cache, 'session_20260603_1000_qualifying.csv', _session_csv(68.5))
        session_db.sync()
        best = session_db.overall_best('f1_25', 'formula1_2026',
                                       'Monaco', 'qualifying')
        assert best['best_lap_time'] == 68.5

    def test_none_when_no_match_or_missing_keys(self, cache):
        _write(cache, 'session_20260601_1000_qualifying.csv', _session_csv(68.6))
        session_db.sync()
        assert session_db.overall_best('f1_25', 'formula1_2026',
                                       'Spa', 'qualifying') is None
        # Flat-format files have no track — never part of a record lookup.
        assert session_db.overall_best('f1_25', 'formula1_2026',
                                       None, 'qualifying') is None


class TestPriorBest:
    def _seed(self, cache):
        _write(cache, 'session_20260601_1000_qualifying.csv',
               _session_csv(68.9, started='2026-06-01T10:00:00'))
        _write(cache, 'session_20260615_1000_qualifying.csv',
               _session_csv(68.2, started='2026-06-15T10:00:00'))
        _write(cache, 'session_20260620_1000_qualifying.csv',
               _session_csv(69.5, started='2026-06-20T10:00:00'))
        session_db.sync()

    def test_best_strictly_before_the_given_session(self, cache):
        self._seed(cache)
        prior = session_db.prior_best(
            'f1_25', 'formula1_2026', 'Monaco', 'qualifying',
            datetime(2026, 6, 20, 10, 0), 'session_20260620_1000_qualifying.csv')
        assert prior['best_lap_time'] == 68.2
        # Going into the 15 June session the PB was still 68.9 — the
        # 68.2 set that day must not count against itself.
        prior = session_db.prior_best(
            'f1_25', 'formula1_2026', 'Monaco', 'qualifying',
            datetime(2026, 6, 15, 10, 0), 'session_20260615_1000_qualifying.csv')
        assert prior['best_lap_time'] == 68.9

    def test_none_for_first_session_or_missing_keys(self, cache):
        self._seed(cache)
        assert session_db.prior_best(
            'f1_25', 'formula1_2026', 'Monaco', 'qualifying',
            datetime(2026, 6, 1, 10, 0), 'session_20260601_1000_qualifying.csv') is None
        assert session_db.prior_best(
            'f1_25', 'formula1_2026', None, 'qualifying',
            datetime(2026, 6, 20, 10, 0)) is None
        assert session_db.prior_best(
            'f1_25', 'formula1_2026', 'Monaco', 'qualifying', None) is None


class TestComboHistory:
    def test_oldest_first_and_scoped(self, cache):
        _write(cache, 'session_20260615_1000_qualifying.csv',
               _session_csv(68.2, started='2026-06-15T10:00:00'))
        _write(cache, 'session_20260601_1000_qualifying.csv',
               _session_csv(68.9, started='2026-06-01T10:00:00'))
        _write(cache, 'session_20260610_1000_qualifying.csv',
               _session_csv(66.0, track='Monza', started='2026-06-10T10:00:00'))
        session_db.sync()
        history = session_db.combo_history('f1_25', 'formula1_2026',
                                           'Monaco', 'qualifying')
        assert [r['best_lap_time'] for r in history] == [68.9, 68.2]

    def test_up_to_excludes_later_sessions(self, cache):
        _write(cache, 'session_20260601_1000_qualifying.csv',
               _session_csv(68.9, started='2026-06-01T10:00:00'))
        _write(cache, 'session_20260615_1000_qualifying.csv',
               _session_csv(68.2, started='2026-06-15T10:00:00'))
        session_db.sync()
        history = session_db.combo_history(
            'f1_25', 'formula1_2026', 'Monaco', 'qualifying',
            datetime(2026, 6, 1, 10, 0), 'session_20260601_1000_qualifying.csv')
        assert [r['filename'] for r in history] == [
            'session_20260601_1000_qualifying.csv']

    def test_missing_keys_give_empty(self, cache):
        assert session_db.combo_history('f1_25', 'formula1_2026',
                                        None, 'qualifying') == []


class TestGradingFactsColumns:
    def test_scan_facts_round_trip_through_the_db(self, cache):
        _write(cache, 'session_20260628_2114_qualifying.csv', _session_csv(68.6))
        session_db.sync()
        r = session_db.all_sessions()[0]
        assert r['valid_lap_count'] == 2
        assert r['clean_lap_count'] == 2
        assert r['rewind_count'] == 0
        assert r['clean_std_dev'] is not None
        assert r['clean_streak'] == 2
        # Fixture laps 69.6/68.6: one within 1% of the best (68.6×1.01).
        assert r['cons_lap_count'] == 2
        assert r['cons_band_count'] == 1
        # theo_time needs 2 full-sector clean laps; the fixture has one.
        assert r['theo_time'] is None


class TestFavourites:
    def test_set_and_read_favourite(self, cache):
        fn = 'session_20260628_2114_qualifying.csv'
        _write(cache, fn, _session_csv(68.6))
        session_db.sync()
        assert session_db.is_favourite(fn) is False

        session_db.set_favourite(fn, True)
        assert session_db.is_favourite(fn) is True
        favs = session_db.favourites()
        assert [r['filename'] for r in favs] == [fn]
        # The flag is exposed on the record and the flat listing too.
        assert session_db.all_sessions()[0]['favourite'] == 1

        session_db.set_favourite(fn, False)
        assert session_db.is_favourite(fn) is False
        assert session_db.favourites() == []

    def test_favourite_survives_rebuild(self, cache):
        fn = 'session_20260628_2114_qualifying.csv'
        _write(cache, fn, _session_csv(68.6))
        session_db.sync()
        session_db.set_favourite(fn, True)
        # A rebuild re-inserts every row with favourite defaulted to 0; sync
        # must restore it from the durable json store.
        session_db.rebuild()
        assert session_db.is_favourite(fn) is True
        assert [r['filename'] for r in session_db.favourites()] == [fn]

    def test_favourite_retained_while_file_absent(self, cache):
        # A CSV that vanishes from a sync (e.g. iCloud-evicted) drops out of the
        # queryable column, but the durable json mark is kept so it is not
        # silently forgotten — and it reappears if the file comes back.
        fn = 'session_20260628_2114_qualifying.csv'
        _write(cache, fn, _session_csv(68.6))
        session_db.sync()
        session_db.set_favourite(fn, True)

        (cache / fn).unlink()
        session_db.sync()
        assert session_db.favourites() == []      # no row → not surfaced
        assert session_db.is_favourite(fn) is True  # …but the mark is kept

        _write(cache, fn, _session_csv(68.6))       # file returns
        session_db.sync()
        assert [r['filename'] for r in session_db.favourites()] == [fn]

    def test_remove_clears_favourite(self, cache):
        fn = 'session_20260628_2114_qualifying.csv'
        _write(cache, fn, _session_csv(68.6))
        session_db.sync()
        session_db.set_favourite(fn, True)
        session_db.remove(fn)
        assert session_db.is_favourite(fn) is False


class TestSchemaAndCorruption:
    def test_schema_version_mismatch_drops_table(self, cache):
        _write(cache, 'session_20260628_2114_qualifying.csv', _session_csv(68.6))
        session_db.sync()
        conn = sqlite3.connect(session_db.DB_PATH)
        conn.execute('PRAGMA user_version = 999')
        conn.commit()
        conn.close()
        # Next connect sees the mismatch, rebuilds an empty table…
        assert session_db.all_sessions() == []
        # …and sync repopulates from the CSVs.
        added, _, total = session_db.sync()
        assert (added, total) == (1, 1)

    def test_corrupt_db_file_is_recreated(self, cache):
        _write(cache, 'session_20260628_2114_qualifying.csv', _session_csv(68.6))
        (cache / '.sessions.db').write_bytes(b'this is not a sqlite file')
        added, _, total = session_db.sync()
        assert (added, total) == (1, 1)
