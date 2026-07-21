"""
Tests for sessionlog.assists — Race Engineer Notes for racing line / TC /
ABS / gearbox assist usage, derived from the per-lap `assist_*` fields.

Shared test: lives canonically in ShfonicDash/tests/ and is copied
into the companion repo by sync_shared.py.
"""

from sessionlog.assists import assist_notes


def _lap(**overrides):
    base = {'assist_tc': 0, 'assist_abs': 0, 'assist_racing_line': 0,
            'assist_gearbox': 0}
    base.update(overrides)
    return base


def test_no_laps_gives_no_notes():
    assert assist_notes({'laps': []}) == []
    assert assist_notes({}) == []


def test_everything_off_gives_no_notes():
    session = {'laps': [_lap(), _lap(), _lap()]}
    assert assist_notes(session) == []


def test_one_assist_used_produces_one_note_with_count():
    session = {'laps': [_lap(), _lap(assist_tc=2), _lap(assist_tc=1)]}
    notes = assist_notes(session)
    assert len(notes) == 1
    assert 'Traction control was on for 2 of 3 laps' in notes[0]['text']
    assert notes[0]['locations'] == []


def test_lap_wording_agrees_with_the_session_total_not_the_used_count():
    """"1 of 12" is still twelve laps — the plural follows the total."""
    session = {'laps': [_lap(), _lap(assist_abs=1)]}
    notes = assist_notes(session)
    assert len(notes) == 1
    assert 'ABS was on for 1 of 2 laps ' in notes[0]['text']


def test_singular_lap_wording_for_a_one_lap_session():
    session = {'laps': [_lap(assist_abs=1)]}
    notes = assist_notes(session)
    assert len(notes) == 1
    assert 'ABS was on for 1 of 1 lap ' in notes[0]['text']


def test_multiple_assists_each_get_their_own_note():
    session = {'laps': [
        _lap(assist_racing_line=1, assist_tc=2),
        _lap(assist_abs=1, assist_gearbox=2),
    ]}
    notes = assist_notes(session)
    texts = [n['text'] for n in notes]
    assert len(notes) == 4
    assert any('racing line assist' in t for t in texts)
    assert any('Traction control' in t for t in texts)
    assert any('ABS' in t for t in texts)
    assert any('gearbox assist' in t for t in texts)


def test_missing_columns_read_as_unused_not_crash():
    # Old files (pre v0.40.0) have no assist_* keys at all.
    session = {'laps': [{'num': 1}, {'num': 2}]}
    assert assist_notes(session) == []
