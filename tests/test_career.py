"""Shared tests for sessionlog.career — overall recent-form grade.

Runs in both the ShfonicDash repo and (via sync_shared.py) the
companion app.
"""
from sessionlog import career
from sessionlog.grading import letter


def _g(score, game='f1_25', day=0):
    return {'date': day, 'game': game, 'score': score}


def test_empty_is_none():
    assert career.recent_form([]) is None


def test_headline_averages_recent_window():
    graded = [_g(90), _g(80), _g(70)]
    form = career.recent_form(graded, n=10)
    assert form['n'] == 3
    assert abs(form['score'] - 80.0) < 1e-9
    assert form['letter'] == letter(80.0)


def test_window_caps_at_n():
    # 12 sessions, n=10 → headline uses only the first 10 (newest).
    graded = [_g(100)] * 10 + [_g(0)] * 2
    form = career.recent_form(graded, n=10)
    assert form['n'] == 10
    assert form['score'] == 100.0


def test_trend_none_without_prior_window():
    form = career.recent_form([_g(80)] * 5, n=10)
    assert form['trend'] is None


def test_trend_up_and_down():
    # newest 10 average 90, previous 10 average 70 → improving.
    up = career.recent_form([_g(90)] * 10 + [_g(70)] * 10, n=10)
    assert up['trend'] == 'up'
    down = career.recent_form([_g(70)] * 10 + [_g(90)] * 10, n=10)
    assert down['trend'] == 'down'


def test_trend_flat_within_margin():
    form = career.recent_form([_g(80.5)] * 10 + [_g(80.0)] * 10, n=10)
    assert form['trend'] == 'flat'


def test_per_game_breakdown_sorted_best_first():
    graded = [_g(95, 'acc'), _g(85, 'acc'),
              _g(70, 'f1_25'), _g(60, 'f1_25')]
    form = career.recent_form(graded, n=10)
    games = [pg['game'] for pg in form['per_game']]
    assert games == ['acc', 'f1_25']          # 90 avg before 65 avg
    acc = form['per_game'][0]
    assert acc['n'] == 2
    assert abs(acc['score'] - 90.0) < 1e-9
    assert acc['letter'] == letter(90.0)


def test_per_game_window_caps_per_game():
    graded = [_g(100, 'acc')] * 10 + [_g(0, 'acc')] * 5
    form = career.recent_form(graded, n=10)
    assert form['per_game'][0]['n'] == 10
    assert form['per_game'][0]['score'] == 100.0


# ── personal_records ─────────────────────────────────────────────────────────

def _s(filename='s.csv', **over):
    """A session_db-shaped row with sensible defaults for the records tests."""
    rec = {
        'filename': filename, 'date': 1, 'game': 'f1_25',
        'car_class': 'formula1', 'car_class_name': 'F1 2025',
        'track': 'Monza', 'session_type': 'hotlap',
        'best_lap_time': None, 'clean_streak': 0, 'clean_std_dev': None,
        'clean_lap_count': 0, 'distance_m': None,
    }
    rec.update(over)
    return rec


def test_records_empty_archive_all_none():
    rec = career.personal_records([])
    assert all(v is None for v in rec.values())


def test_records_longest_clean_streak():
    recs = [_s('a.csv', clean_streak=8), _s('b.csv', clean_streak=27),
            _s('c.csv', clean_streak=12)]
    out = career.personal_records(recs)
    assert out['clean_streak']['value'] == 27
    assert 'Monza' in out['clean_streak']['label']


def test_records_best_consistency_needs_enough_clean_laps():
    # The 0.02 session is too short (2 clean laps) to count; 0.08 wins.
    recs = [_s('a.csv', clean_std_dev=0.02, clean_lap_count=2),
            _s('b.csv', clean_std_dev=0.08, clean_lap_count=6),
            _s('c.csv', clean_std_dev=0.15, clean_lap_count=9)]
    out = career.personal_records(recs)
    assert abs(out['consistency']['value'] - 0.08) < 1e-9


def test_records_largest_pb_is_biggest_gain_over_prior_best():
    # Same combo improving 90.0 → 89.1 (0.9) → 89.05 (0.05); best gain 0.9.
    combo = dict(game='f1_25', car_class='formula1', track='Spa',
                 session_type='hotlap')
    recs = [_s('1.csv', date=1, best_lap_time=90.0, **combo),
            _s('2.csv', date=2, best_lap_time=89.1, **combo),
            _s('3.csv', date=3, best_lap_time=89.05, **combo)]
    out = career.personal_records(recs)
    assert abs(out['largest_pb']['value'] - 0.9) < 1e-9
    assert 'Spa' in out['largest_pb']['label']


def test_records_most_sessions_and_favourite_car():
    recs = [_s('1.csv', track='Monza', car_class_name='F1 2026'),
            _s('2.csv', track='Monza', car_class_name='F1 2026'),
            _s('3.csv', track='Spa', car_class_name='F1 2025')]
    out = career.personal_records(recs)
    assert out['most_sessions'] == {'name': 'Monza', 'count': 2}
    assert out['favourite_car'] == {'name': 'F1 2026', 'count': 2}


def test_records_total_distance_sums_and_converts_to_km():
    recs = [_s('1.csv', distance_m=5793 * 3), _s('2.csv', distance_m=None),
            _s('3.csv', distance_m=7004 * 2)]
    out = career.personal_records(recs)
    assert out['total_distance_km'] == round((5793 * 3 + 7004 * 2) / 1000.0, 1)
