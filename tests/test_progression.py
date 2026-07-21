"""
Tests for sessionlog.progression — within-session progression facts and
notes.

Shared test: lives canonically in ShfonicDash/tests/ and is copied
into the companion repo by sync_shared.py.
"""

from sessionlog.progression import progression_facts, progression_notes


def _lap(num, time, s1=None, s2=None, s3=None, valid=True, rewinds=0):
    return {'num': num, 'time': time, 's1': s1, 's2': s2, 's3': s3,
            'valid': valid, 'rewinds': rewinds}


def _session(laps, session_type='practice', events=None):
    return {'laps': laps, 'session_type': session_type,
            'events': events or []}


def _texts(session):
    return [n['text'] for n in progression_notes(session)]


class TestProgressionFacts:

    def test_counts_streak_and_first_clean_lap(self):
        s = _session([
            _lap(1, 90.0, valid=False),
            _lap(2, 90.0, valid=False),
            _lap(3, 89.0),
            _lap(4, 89.0),
            _lap(5, 89.0),
        ])
        f = progression_facts(s)
        assert f['timed'] == 5
        assert f['clean'] == 3
        assert f['best_streak'] == 3
        assert f['first_clean_num'] == 3

    def test_early_late_clean_fraction_needs_enough_laps(self):
        short = progression_facts(_session([_lap(1, 90.0), _lap(2, 90.0)]))
        assert short['early_clean_frac'] is None

        s = _session([
            _lap(1, 90.0, valid=False), _lap(2, 90.0, valid=False),
            _lap(3, 90.0, valid=False), _lap(4, 89.0),
            _lap(5, 89.0), _lap(6, 89.0),
        ])
        f = progression_facts(s)
        assert f['early_clean_frac'] == 0.0
        assert f['late_clean_frac'] == 1.0

    def test_pace_trend_negative_when_getting_quicker(self):
        s = _session([
            _lap(1, 91.0), _lap(2, 91.0), _lap(3, 90.0), _lap(4, 90.0),
        ])
        f = progression_facts(s)
        assert f['pace_trend'] == -1.0

    def test_sector_std_needs_three_full_clean_laps(self):
        s = _session([
            _lap(1, 90.0, 30.0, 30.0, 30.0),
            _lap(2, 90.0, 30.0, 30.5, 30.0),
            _lap(3, 90.0, 30.0, 29.5, 30.0),
        ])
        f = progression_facts(s)
        assert f['sector_std']['s1'] == 0.0
        assert f['sector_std']['s2'] > 0.0


class TestProgressionNotes:

    def test_races_get_no_progression_notes(self):
        s = _session([_lap(n, 90.0) for n in range(1, 8)],
                     session_type='race')
        assert progression_notes(s) == []

    def test_clean_summary_reports_percentage_and_streak(self):
        s = _session([
            _lap(1, 90.0, valid=False), _lap(2, 89.0), _lap(3, 89.0),
            _lap(4, 89.0),
        ])
        text = _texts(s)[0]
        assert "3 of 4 laps clean (75%)" in text
        assert "best run 3 in a row" in text

    def test_all_clean_reads_as_tidy(self):
        s = _session([_lap(n, 90.0) for n in range(1, 5)])
        text = _texts(s)[0]
        assert "All 4 laps were clean" in text

    def test_tidied_up_trend_called_out(self):
        s = _session([
            _lap(1, 90.0, valid=False), _lap(2, 90.0, valid=False),
            _lap(3, 90.0, valid=False), _lap(4, 89.0),
            _lap(5, 89.0), _lap(6, 89.0),
        ])
        joined = " ".join(_texts(s))
        assert "tidied up as the session went on" in joined

    def test_pace_trend_note_when_quicker(self):
        s = _session([
            _lap(1, 91.0), _lap(2, 91.0), _lap(3, 90.0), _lap(4, 90.0),
        ])
        joined = " ".join(_texts(s))
        assert "pace kept coming down" in joined

    def test_sector_variation_names_the_culprit(self):
        s = _session([
            _lap(1, 90.0, 30.0, 29.4, 30.0),
            _lap(2, 90.0, 30.0, 30.0, 30.0),
            _lap(3, 90.0, 30.0, 30.6, 30.0),
            _lap(4, 90.0, 30.0, 29.7, 30.0),
        ])
        joined = " ".join(_texts(s))
        assert "Sector 2" in joined
        assert "leaking" in joined
