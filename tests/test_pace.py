"""
Tests for sessionlog.pace — pace facts + coaching notes.

Shared test: lives canonically in ShfonicDash/tests/ and is copied
into the companion repo by sync_shared.py.

These functions previously lived untested inside the companion's
dashboard.py; the cases below pin their behaviour now that they are
shared library surface.
"""

from sessionlog.pace import (
    contact_incidents,
    net_positions,
    pace_facts,
    race_engineer_notes,
    race_engineer_notes_detailed,
    track_limit_counts,
)


def _lap(num, time, s1=None, s2=None, s3=None, valid=True, rewinds=0):
    return {'num': num, 'time': time, 's1': s1, 's2': s2, 's3': s3,
            'valid': valid, 'rewinds': rewinds}


def _session(laps, session_type='practice', events=None):
    return {'laps': laps, 'session_type': session_type,
            'events': events or []}


class TestPaceFacts:

    def test_fastest_theo_and_gap_from_clean_laps(self):
        s = _session([
            _lap(1, 91.0, 28.5, 29.6, 32.9),
            _lap(2, 90.5, 28.2, 29.5, 32.8),
            _lap(3, 92.0, 28.4, 29.7, 33.9),
        ])
        f = pace_facts(s)
        assert f['fastest'] == 90.5
        assert f['fastest_num'] == 2
        assert f['theo'] == 28.2 + 29.5 + 32.8
        assert f['gap'] == f['fastest'] - f['theo']

    def test_invalid_and_rewound_laps_are_not_clean(self):
        s = _session([
            _lap(1, 90.0, valid=False),
            _lap(2, 89.0, rewinds=1),
            _lap(3, 91.0),
        ])
        f = pace_facts(s)
        assert f['fastest'] == 91.0
        assert f['dirty_best'] == (89.0, 2)
        assert f['dirty_faster'] is True

    def test_pushed_sectors_flag_dirty_sector_bests(self):
        s = _session([
            _lap(1, 91.0, 28.5, 29.6, 32.9),
            _lap(2, 90.5, 28.2, 29.5, 32.8),
            _lap(3, 95.0, 28.0, 29.9, 34.0, valid=False),
        ])
        f = pace_facts(s)
        assert f['pushed_sectors'] == [('s1', 28.0, 3)]
        assert f['dirty_faster'] is False

    def test_no_laps_yields_empty_facts(self):
        f = pace_facts(_session([]))
        assert f['fastest'] is None
        assert f['theo'] is None
        assert f['gap'] is None


class TestCoachingNotes:

    def test_close_theoretical_recommends_consistency(self):
        # A small but REAL gap: the fastest lap gives up 0.1s of s1 to lap 1,
        # so there is genuinely a tenth left to assemble. (These laps used to
        # share identical sectors, i.e. theo == fastest — a gap of zero, which
        # is the "already assembled" case, not a "close" one.)
        s = _session([
            _lap(1, 90.6, 28.2, 29.5, 32.9),
            _lap(2, 90.5, 28.3, 29.5, 32.7),
        ])
        notes = race_engineer_notes(s)
        assert any('focus on consistency' in n for n in notes)

    def test_large_gap_reports_pace_to_find(self):
        s = _session([
            _lap(1, 92.0, 28.2, 30.5, 33.3),
            _lap(2, 91.8, 29.0, 29.5, 32.8),
        ])
        notes = race_engineer_notes(s)
        assert any('meaningful outright pace' in n for n in notes)

    def test_unconverted_dirty_pace_is_called_out(self):
        s = _session([
            _lap(1, 91.0, 28.5, 29.6, 32.9),
            _lap(2, 90.9, 28.9, 29.2, 32.8),
            _lap(3, 89.0, 27.9, 29.0, 31.9, valid=False),
        ])
        notes = race_engineer_notes(s)
        assert pace_facts(s)['gap'] > 0.3   # otherwise the consistency note wins
        assert any('not yet been converted into a valid lap' in n
                   for n in notes)

    def test_high_invalid_share_note(self):
        laps = [_lap(n, 91.0 + n / 10, 28.2, 29.5, 32.8) for n in range(1, 4)]
        laps += [_lap(n, 91.0, valid=False) for n in range(4, 7)]
        notes = race_engineer_notes(_session(laps))
        assert any('high proportion of laps were invalidated' in n
                   for n in notes)

    def test_single_rep_lap_qualifying_short_circuits(self):
        s = _session([_lap(1, 90.5, 28.2, 29.5, 32.8)],
                     session_type='qualifying')
        notes = race_engineer_notes(s)
        assert len(notes) == 1
        assert 'representative timed lap' in notes[0]

    def test_contact_paired_with_flashback(self):
        events = [
            {'type': 'collision', 'lap_num': 2, 'lap_time': 38.1,
             'distance': 1740.2, 't': 131.6, 'detail': 'VERSTAPPEN'},
            {'type': 'rewind', 'lap_num': 2, 'lap_time': 44.7,
             'distance': None, 't': 138.2, 'detail': None},
        ]
        s = _session([
            _lap(1, 91.0, 28.5, 29.6, 32.9),
            _lap(2, 90.5, 28.2, 29.5, 32.8, rewinds=1),
        ], events=events)
        notes = race_engineer_notes(s)
        contact = next(n for n in notes if 'contact event' in n)
        assert contact.startswith('One contact event:')
        assert 'VERSTAPPEN on lap 2 (followed by a flashback)' in contact
        assert 'involvement, not fault' in contact

    def test_contact_rewind_contact_chain_is_one_event(self):
        # A rewind duplicates events — contact → rewind → contact →
        # rewind → contact retried within seconds is ONE incident.
        events = [
            {'type': 'collision', 'lap_num': 2, 't': 131.6, 'detail': 'OCON'},
            {'type': 'rewind',    'lap_num': 2, 't': 138.2, 'detail': None},
            {'type': 'collision', 'lap_num': 2, 't': 150.9, 'detail': 'OCON'},
            {'type': 'rewind',    'lap_num': 2, 't': 155.0, 'detail': None},
            {'type': 'collision', 'lap_num': 2, 't': 168.3, 'detail': 'OCON'},
        ]
        s = _session([
            _lap(1, 91.0, 28.5, 29.6, 32.9),
            _lap(2, 90.5, 28.2, 29.5, 32.8, rewinds=2),
        ], events=events)
        notes = race_engineer_notes(s)
        contact = next(n for n in notes if 'contact event' in n)
        assert contact.startswith('One contact event:')

    def test_contact_location_uses_track_map_when_given(self):
        events = [
            {'type': 'collision', 'lap_num': 2, 'lap_time': 38.1,
             'distance': 175, 't': 131.6, 'detail': 'VERSTAPPEN'},
        ]
        s = _session([
            _lap(1, 91.0, 28.5, 29.6, 32.9),
            _lap(2, 90.5, 28.2, 29.5, 32.8),
        ], events=events)
        track_map = {'sections': [{'turn': '1', 'name': 'Turn 1',
                                   'type': 'corner', 'start_m': 100,
                                   'end_m': 240, 'apex_m': 175}]}
        notes = race_engineer_notes(s, track_map=track_map)
        contact = next(n for n in notes if 'contact event' in n)
        assert 'VERSTAPPEN on lap 2 at the apex of Turn 1' in contact

    def test_track_limits_note_names_the_recurring_corner(self):
        events = [{'type': 'track_limit_warning', 'lap_num': n,
                   'lap_time': 20.0, 'distance': 940, 't': None}
                  for n in (1, 2)] + [
            {'type': 'track_limit_warning', 'lap_num': 3,
             'lap_time': 20.0, 'distance': 175, 't': None},
        ]
        s = _session([_lap(1, 91.0), _lap(2, 90.8), _lap(3, 90.5)],
                     events=events)
        track_map = {'sections': [
            {'turn': '1', 'type': 'corner', 'start_m': 100, 'end_m': 240,
             'apex_m': 175},
            {'turn': '8', 'type': 'corner', 'start_m': 900, 'end_m': 980},
        ]}
        notes = race_engineer_notes(s, track_map=track_map)
        limit_note = next(n for n in notes if 'track-limits warning' in n)
        assert 'two at Turn 8' in limit_note
        assert 'one at Turn 1' in limit_note

    def test_no_track_limits_note_without_a_track_map(self):
        events = [{'type': 'track_limit_warning', 'lap_num': 1,
                   'lap_time': 20.0, 'distance': 940, 't': None}]
        s = _session([_lap(1, 91.0)], events=events)
        notes = race_engineer_notes(s)
        assert not any('track-limits warning' in n for n in notes)


class TestDetailedNotes:
    """race_engineer_notes_detailed() carries per-note locations; the plain
    string API is exactly its `text` fields."""

    _MAP = {'game_track_length_m': 5000, 'sections': [
        {'turn': '1', 'name': 'Turn 1', 'type': 'corner',
         'start_m': 100, 'end_m': 240, 'apex_m': 175},
        {'turn': '8', 'type': 'corner', 'start_m': 900, 'end_m': 980},
    ]}

    def test_string_api_is_the_text_fields(self):
        events = [{'type': 'collision', 'lap_num': 2, 'lap_time': 38.1,
                   'distance': 175, 't': 131.6, 'detail': 'OCON'}]
        s = _session([_lap(1, 91.0), _lap(2, 90.5)], events=events)
        plain    = race_engineer_notes(s, track_map=self._MAP)
        detailed = race_engineer_notes_detailed(s, track_map=self._MAP)
        assert plain == [n['text'] for n in detailed]

    def test_contact_note_carries_one_location_per_distinct_corner(self):
        events = [
            {'type': 'collision', 'lap_num': 1, 't': 10.0,
             'distance': 175, 'detail': 'A'},           # Turn 1
            {'type': 'collision', 'lap_num': 5, 't': 300.0,
             'distance': 940, 'detail': 'B'},           # Turn 8
            {'type': 'collision', 'lap_num': 6, 't': 400.0,
             'distance': 180, 'detail': 'C'},           # Turn 1 again
        ]
        s = _session([_lap(n, 91.0) for n in (1, 5, 6)], events=events)
        detailed = race_engineer_notes_detailed(s, track_map=self._MAP)
        contact = next(n for n in detailed if 'contact event' in n['text'])
        labels = [loc['label'] for loc in contact['locations']]
        assert labels == ['Turn 1', 'Turn 8']   # de-duped, in first-seen order
        assert contact['locations'][0]['distance'] == 175

    def test_track_limits_locations_track_the_sentence_order(self):
        events = [{'type': 'track_limit_warning', 'lap_num': n,
                   'lap_time': 20.0, 'distance': 940} for n in (1, 2)] + [
            {'type': 'track_limit_warning', 'lap_num': 3,
             'lap_time': 20.0, 'distance': 175}]
        s = _session([_lap(n, 91.0) for n in (1, 2, 3)], events=events)
        detailed = race_engineer_notes_detailed(s, track_map=self._MAP)
        tl = next(n for n in detailed if 'track-limits warning' in n['text'])
        # Ranked by count: Turn 8 (2) before Turn 1 (1), matching the text.
        assert [loc['label'] for loc in tl['locations']] == ['Turn 8', 'Turn 1']
        assert all(loc['kind'] == 'track_limit' for loc in tl['locations'])

    def test_location_kind_and_rewound_flag(self):
        # Turn 1: ordinary contact (fill=contact, not rewound). Turn 8: a
        # contact that was flashed back — still fill=contact, but rewound=True
        # so the renderer can add the blue rim (both shown on one marker).
        events = [
            {'type': 'collision', 'lap_num': 1, 't': 10.0,
             'distance': 175, 'detail': 'ALONSO'},          # Turn 1, contact
            {'type': 'collision', 'lap_num': 2, 't': 120.0,
             'distance': 940, 'detail': 'OCON'},            # Turn 8 …
            {'type': 'rewind', 'lap_num': 2, 't': 128.0},   # … rewound
        ]
        s = _session([_lap(1, 91.0), _lap(2, 90.8, rewinds=1)], events=events)
        by_label = {loc['label']: loc for loc in
                    next(n for n in race_engineer_notes_detailed(
                        s, track_map=self._MAP)
                        if 'contact event' in n['text'])['locations']}
        assert by_label['Turn 1']['kind'] == 'contact'
        assert by_label['Turn 1']['rewound'] is False
        assert by_label['Turn 8']['kind'] == 'contact'
        assert by_label['Turn 8']['rewound'] is True

    def test_big_collision_penalty_makes_the_marker_major(self):
        events = [
            {'type': 'collision', 'lap_num': 1, 't': 10.0,
             'distance': 175, 'detail': 'VERSTAPPEN'},
            {'type': 'penalty', 'lap_num': 1, 'lap_time': 12.0, 't': 12.0,
             'distance': 180, 'detail': 'time_penalty:big_collision:VERSTAPPEN'},
        ]
        s = _session([_lap(1, 91.0), _lap(2, 90.8)], events=events)
        contact = next(n for n in race_engineer_notes_detailed(
            s, track_map=self._MAP) if 'contact event' in n['text'])
        assert contact['locations'][0]['kind'] == 'major'

    def test_no_locations_without_a_track_map(self):
        events = [{'type': 'collision', 'lap_num': 1, 't': 10.0,
                   'distance': 175, 'detail': 'A'}]
        s = _session([_lap(1, 91.0)], events=events)
        detailed = race_engineer_notes_detailed(s)   # no map
        assert all(n['locations'] == [] for n in detailed)

    def test_contact_in_a_gap_is_bracketed_by_corners(self):
        # 600 m sits between Turn 1 (…240) and Turn 8 (900…) — no section
        # covers it, so the note names the corners it's between and still
        # gets a thumbnail location captioned compactly.
        events = [{'type': 'collision', 'lap_num': 1, 't': 10.0,
                   'distance': 600, 'detail': 'GASLY'}]
        s = _session([_lap(1, 91.0)], events=events)
        detailed = race_engineer_notes_detailed(s, track_map=self._MAP)
        contact = next(n for n in detailed if 'contact event' in n['text'])
        assert 'between Turn 1 and Turn 8' in contact['text']
        assert contact['locations'][0]['label'] == 'T1–T8'
        assert contact['locations'][0]['distance'] == 600


class TestContactIncidents:

    def test_chain_within_window_is_one_incident(self):
        events = [
            {'type': 'collision', 'lap_num': 2, 't': 100.0, 'detail': 'OCON'},
            {'type': 'rewind',    'lap_num': 2, 't': 110.0, 'detail': None},
            {'type': 'collision', 'lap_num': 2, 't': 125.0, 'detail': 'OCON'},
        ]
        incidents = contact_incidents(events)
        assert len(incidents) == 1
        assert incidents[0]['contacts'] == 2
        assert incidents[0]['rewound'] is True
        assert incidents[0]['drivers'] == ['OCON']
        assert incidents[0]['lap_num'] == 2

    def test_separate_drivers_within_window_but_no_rewind_are_distinct(self):
        # Real-world regression: a chaotic opening lap where the player
        # collects three different, unrelated cars in quick succession —
        # different drivers, ~600-950m apart on track, no flashback linking
        # any of them. All three land inside the old 30s window, but that
        # window exists for the "crash -> flashback -> retry" story, not
        # for folding unrelated contacts together.
        events = [
            {'type': 'collision', 'lap_num': 1, 't': 14.7, 'detail': 'PEREZ'},
            {'type': 'collision', 'lap_num': 1, 't': 26.5, 'detail': 'BORTOLETO'},
            {'type': 'collision', 'lap_num': 1, 't': 42.6, 'detail': 'LINDBLAD'},
        ]
        incidents = contact_incidents(events)
        assert len(incidents) == 3
        assert [i['drivers'] for i in incidents] == [
            ['PEREZ'], ['BORTOLETO'], ['LINDBLAD']]
        assert all(i['contacts'] == 1 for i in incidents)

    def test_rapid_pileup_with_no_rewind_is_still_one_incident(self):
        # Two contacts a few seconds apart, no rewind — genuinely a single
        # multi-car pileup moment, not two separate incidents.
        events = [
            {'type': 'collision', 'lap_num': 1, 't': 10.0, 'detail': 'A'},
            {'type': 'collision', 'lap_num': 1, 't': 14.0, 'detail': 'B'},
        ]
        incidents = contact_incidents(events)
        assert len(incidents) == 1
        assert incidents[0]['contacts'] == 2
        assert incidents[0]['drivers'] == ['A', 'B']

    def test_rewind_still_bridges_the_full_window_after_a_pileup(self):
        # A rewind following any collision (even one already folded into a
        # pileup) still gets the generous retry window, not the tight one.
        events = [
            {'type': 'collision', 'lap_num': 5, 't': 439.9, 'detail': 'LINDBLAD'},
            {'type': 'collision', 'lap_num': 5, 't': 473.4, 'detail': 'LINDBLAD',
             'distance': 5536.1},
            {'type': 'rewind',    'lap_num': 5, 't': 481.6},
            {'type': 'collision', 'lap_num': 5, 't': 485.9, 'detail': 'OCON'},
        ]
        incidents = contact_incidents(events)
        # 439.9 is its own incident (24.1s from 464.0-style gaps N/A here;
        # 473.4 is 33.5s later — outside even the full window — so it opens
        # a second incident, which the rewind then bridges to the OCON hit).
        assert len(incidents) == 2
        assert incidents[1]['drivers'] == ['LINDBLAD', 'OCON']
        assert incidents[1]['rewound'] is True
        assert incidents[1]['contacts'] == 2

    def test_captures_distance_of_the_opening_contact(self):
        events = [
            {'type': 'collision', 'lap_num': 2, 't': 100.0,
             'distance': 1740.2, 'detail': 'OCON'},
            {'type': 'rewind', 'lap_num': 2, 't': 110.0, 'detail': None},
        ]
        incidents = contact_incidents(events)
        assert incidents[0]['distance'] == 1740.2

    def test_separated_contacts_are_distinct_incidents(self):
        events = [
            {'type': 'collision', 'lap_num': 2, 't': 100.0, 'detail': 'OCON'},
            {'type': 'collision', 'lap_num': 7, 't': 620.0, 'detail': 'NORRIS'},
        ]
        incidents = contact_incidents(events)
        assert len(incidents) == 2
        assert [i['drivers'] for i in incidents] == [['OCON'], ['NORRIS']]

    def test_rewind_alone_is_not_an_incident(self):
        events = [{'type': 'rewind', 'lap_num': 3, 't': 200.0, 'detail': None}]
        assert contact_incidents(events) == []

    def test_stray_rewind_breaks_the_chain(self):
        # rewind → long gap → the next contact is a NEW incident even
        # though it lands within the window of the rewind.
        events = [
            {'type': 'collision', 'lap_num': 2, 't': 100.0, 'detail': 'OCON'},
            {'type': 'rewind',    'lap_num': 2, 't': 160.0, 'detail': None},
            {'type': 'collision', 'lap_num': 2, 't': 170.0, 'detail': 'OCON'},
        ]
        assert len(contact_incidents(events)) == 2

    def test_missing_t_falls_back_to_lap_grouping(self):
        events = [
            {'type': 'collision', 'lap_num': 2, 't': None, 'detail': 'OCON'},
            {'type': 'rewind',    'lap_num': 2, 't': None, 'detail': None},
            {'type': 'collision', 'lap_num': 2, 't': None, 'detail': 'OCON'},
            {'type': 'collision', 'lap_num': 5, 't': None, 'detail': 'SAINZ'},
        ]
        incidents = contact_incidents(events)
        assert len(incidents) == 2
        assert incidents[0]['contacts'] == 2
        assert incidents[1]['drivers'] == ['SAINZ']


class TestRaceNotes:

    def _race(self, events=None):
        return _session([
            _lap(1, 95.0, 29.5, 30.6, 34.9),
            _lap(2, 93.4, 28.9, 30.0, 34.5),
            _lap(3, 93.2, 28.8, 29.9, 34.5),
            _lap(4, 93.5, 28.9, 30.1, 34.5),
        ], session_type='race', events=events)

    def test_race_never_gets_theoretical_notes(self):
        notes = race_engineer_notes(self._race(), prior_best=93.0)
        assert not any('theoretical' in n.lower() for n in notes)

    def test_race_pace_vs_prior_race_best(self):
        notes = race_engineer_notes(self._race(), prior_best=93.0)
        assert any('+0.200s off your best race lap at this combination' in n
                   for n in notes)

    def test_new_best_race_lap_is_reported(self):
        notes = race_engineer_notes(self._race(), prior_best=93.4)
        assert any('a new best race lap at this combination' in n
                   for n in notes)

    def test_busy_race_is_framed_as_racecraft(self):
        events = [
            {'type': 'collision', 'lap_num': 1, 't': 30.0, 'detail': 'OCON'},
            {'type': 'collision', 'lap_num': 3, 't': 300.0, 'detail': 'SAINZ'},
            {'type': 'rewind',    'lap_num': 3, 't': 310.0, 'detail': None},
        ]
        notes = race_engineer_notes(self._race(events), prior_best=91.0)
        assert any('racecraft session rather than a pure pace benchmark' in n
                   for n in notes)

    def test_quiet_race_without_prior_has_no_pace_note(self):
        notes = race_engineer_notes(self._race())
        assert notes == []

    def _busy_recovery(self, grid=19, finish=13):
        # On-pace (+0.2s vs prior 93.0) but incident-heavy, with a known
        # grid slot and finishing position — the full race-engineer read.
        s = self._race(events=[
            {'type': 'collision', 'lap_num': 1, 't': 30.0,
             'detail': 'PÉREZ'},
            {'type': 'collision', 'lap_num': 3, 't': 300.0,
             'detail': 'OCON'},
            {'type': 'rewind',    'lap_num': 3, 't': 310.0,
             'detail': None},
        ])
        s['driver_name'] = 'ME'
        s['grid']      = [{'position': str(grid), 'name': 'ME'}]
        s['standings'] = [{'position': str(finish), 'name': 'ME'}]
        return s

    def test_on_pace_busy_race_gets_the_synthesis_note(self):
        notes = race_engineer_notes(self._busy_recovery(), prior_best=93.0)
        note = next(n for n in notes if 'limiting factor' in n)
        assert 'You recovered from P19 to P13' in note
        assert 'within 0.200s of your best race lap' in note
        assert 'two contact events and one flashback' in note
        assert 'the pace is already there' in note
        # The synthesis replaces the plain gap line, not duplicates it.
        assert not any('racecraft session rather than' in n for n in notes)

    def test_synthesis_wording_when_positions_were_lost(self):
        notes = race_engineer_notes(self._busy_recovery(grid=8, finish=12),
                               prior_best=93.0)
        note = next(n for n in notes if 'limiting factor' in n)
        assert 'You finished P12 from P8 on the grid' in note

    def test_synthesis_covers_a_new_best_race_lap(self):
        notes = race_engineer_notes(self._busy_recovery(), prior_best=93.4)
        note = next(n for n in notes if 'limiting factor' in n)
        assert 'setting a new best race lap' in note

    def test_off_pace_busy_race_keeps_the_racecraft_framing(self):
        notes = race_engineer_notes(self._busy_recovery(), prior_best=91.0)
        assert any('racecraft session rather than' in n for n in notes)
        assert not any('limiting factor' in n for n in notes)

    def test_no_position_data_falls_back_to_the_plain_lines(self):
        s = self._busy_recovery()
        s['grid'] = []
        notes = race_engineer_notes(s, prior_best=93.0)
        assert any('racecraft session rather than' in n for n in notes)


class TestNetPositions:

    def _race(self):
        s = _session([_lap(1, 95.0, 29.5, 30.6, 34.9)],
                     session_type='race')
        s['driver_name'] = 'ME'
        s['grid']      = [{'position': '19', 'name': 'ME'},
                          {'position': '1', 'name': 'LECLERC'}]
        s['standings'] = [{'position': '13', 'name': 'ME'}]
        return s

    def test_start_finish_and_gain(self):
        assert net_positions(self._race()) == (19, 13, 6)

    def test_finish_falls_back_to_the_last_lap_position(self):
        s = self._race()
        s['standings'] = []
        s['laps'] = [dict(_lap(1, 95.0), position=14),
                     dict(_lap(2, 94.0), position=12)]
        assert net_positions(s) == (19, 12, 7)

    def test_none_outside_races_or_without_both_ends(self):
        s = self._race()
        s['session_type'] = 'practice'
        assert net_positions(s) is None
        s = self._race()
        s['grid'] = []
        assert net_positions(s) is None
        s = self._race()
        s['driver_name'] = ''
        assert net_positions(s) is None


class TestQualiPositionNote:

    def _quali(self, position=18, total=20):
        standings = [{'position': str(p), 'name': f'DRIVER{p}',
                      'best_lap': f'{90.0 + p * 0.1:.3f}'}
                     for p in range(1, total + 1)]
        standings[position - 1]['name'] = 'ME'
        laps = [_lap(1, 93.0, 28.2, 30.0, 34.8),
                _lap(2, 91.8, 28.0, 29.5, 34.3)]
        s = _session(laps, session_type='qualifying')
        s['driver_name'] = 'ME'
        s['standings']   = standings
        return s

    def test_close_to_pb_but_low_grid_is_contextualised(self):
        notes = race_engineer_notes(self._quali(), prior_best=91.7)
        assert any("field's competitiveness" in n for n in notes)

    def test_no_note_when_gap_to_pb_is_large(self):
        notes = race_engineer_notes(self._quali(), prior_best=90.5)
        assert not any("field's competitiveness" in n for n in notes)

    def test_no_note_in_the_top_half(self):
        notes = race_engineer_notes(self._quali(position=4), prior_best=91.7)
        assert not any("field's competitiveness" in n for n in notes)

    def test_fires_from_the_single_rep_lap_path_too(self):
        s = self._quali()
        s['laps'] = [_lap(2, 91.8, 28.0, 29.5, 34.3)]
        notes = race_engineer_notes(s, prior_best=91.7)
        # The classified result leads; the grading-limitation note follows.
        assert notes[0].startswith('You classified')
        assert any('representative timed lap' in n for n in notes)
        assert any("field's competitiveness" in n for n in notes)

    def test_lone_rewound_lap_still_reports_the_grid_result(self):
        # The reported bug: one lap, spoiled by a flashback, so no clean lap —
        # the coach must still state the time and grid slot it earned, not just
        # "no representative timed laps".
        s = self._quali()
        s['laps'] = [_lap(2, 91.8, 28.0, 29.5, 34.3, valid=True, rewinds=1)]
        s['events'] = [{'type': 'rewind', 'lap_num': 2}]
        notes = race_engineer_notes(s)
        assert notes[0].startswith('You classified P18 of 20 on a 1:31.800')
        assert 'off pole' in notes[0]
        assert 'flashback' in notes[0]


class TestGapToTheoreticalNote:
    """The tiered gap-to-theoretical advice. Regression: a driver whose
    fastest lap held every best sector (gap == 0.0) was told "theoretical
    pace is very close" — there was nothing to be close to — and the more
    useful "your quick sector is on a binned lap" note never fired because
    the gap check pre-empted it (observed at Spa, 2026-07-17)."""

    def test_assembled_lap_is_not_described_as_merely_close(self):
        # Lap 2 holds the best s1, s2 and s3 → theoretical == fastest.
        s = _session([
            _lap(1, 91.0, 30.0, 30.0, 31.0),
            _lap(2, 89.0, 29.0, 29.5, 30.5),
        ])
        notes = race_engineer_notes(s)
        assert any('already strings together your best sector' in n
                   for n in notes)
        assert not any('very close' in n for n in notes)

    def test_pace_on_an_invalidated_lap_beats_the_gap_advice(self):
        # Clean sectors are fully assembled (gap == 0), but a faster s2 sits
        # on an invalidated lap — that's the actionable fact, not "nothing
        # to gain".
        s = _session([
            _lap(1, 91.0, 30.0, 30.0, 31.0),
            _lap(2, 89.0, 29.0, 29.5, 30.5),
            _lap(3, 88.0, 29.5, 28.0, 30.5, valid=False),   # binned, quick s2
        ])
        notes = race_engineer_notes(s)
        assert any('has not yet been converted into a valid lap' in n
                   for n in notes)
        assert not any('very close' in n for n in notes)
        assert not any('already strings together' in n for n in notes)

    def test_real_gap_still_gets_the_consistency_advice(self):
        # theo 88.9 vs fastest 89.0 → a real 0.1s left to assemble.
        s = _session([
            _lap(1, 91.0, 28.5, 29.6, 32.9),
            _lap(2, 89.0, 28.6, 29.4, 31.0),
        ])
        notes = race_engineer_notes(s)
        assert any('focus on consistency' in n for n in notes)
        assert not any('already strings together' in n for n in notes)


class TestFocusWeighting:
    """race_engineer_notes(_detailed)() folds the driver's chosen focus
    verdict in as the first note and promotes notes matching its category."""

    _MAP = TestDetailedNotes._MAP

    def test_focus_verdict_prepended_as_first_note(self):
        s = _session([_lap(1, 91.0), _lap(2, 90.5)])
        verdict = {'met': True, 'headline': 'All clean',
                   'detail': 'No invalid laps.', 'title': 'CLEAN LAPS'}
        notes = race_engineer_notes(s, focus_verdict=verdict)
        assert notes[0] == 'CLEAN LAPS — All clean. No invalid laps.'

    def test_no_verdict_note_without_focus_verdict(self):
        s = _session([_lap(1, 91.0), _lap(2, 90.5)])
        notes = race_engineer_notes(s)
        assert not any(n.startswith('CLEAN LAPS —') for n in notes)

    def test_faster_focus_promotes_pace_note_above_incidents(self):
        events = [{'type': 'track_limit_warning', 'lap_num': 1,
                   'lap_time': 20.0, 'distance': 940}]
        s = _session([
            _lap(1, 91.0, 28.5, 29.6, 32.9),
            _lap(2, 89.0, 27.0, 28.0, 30.0),
        ], events=events)

        notes_default = race_engineer_notes(s, track_map=self._MAP)
        tl_i  = next(i for i, n in enumerate(notes_default)
                     if 'track-limits warning' in n)
        gap_i = next(i for i, n in enumerate(notes_default)
                     if 'Gap to theoretical is >0.5s' in n)
        assert tl_i < gap_i   # default order: incidents note precedes pace note

        notes_faster = race_engineer_notes(s, track_map=self._MAP, focus_id='faster')
        tl_i2  = next(i for i, n in enumerate(notes_faster)
                      if 'track-limits warning' in n)
        gap_i2 = next(i for i, n in enumerate(notes_faster)
                      if 'Gap to theoretical is >0.5s' in n)
        assert gap_i2 < tl_i2   # promoted: pace note now precedes incidents note

    def _consistency_session(self):
        """Sectors chosen so theoretical sits a real, small gap (0.1s) under
        the fastest lap — that fires the 'focus on consistency rather than
        outright speed' note (category 'consistency') alongside a track-limits
        note. The gap must be non-zero: at zero the lap is already assembled
        and a different note fires."""
        events = [{'type': 'track_limit_warning', 'lap_num': 1,
                   'lap_time': 20.0, 'distance': 940}]
        return _session([
            _lap(1, 91.0, 28.5, 29.6, 32.9),
            _lap(2, 89.0, 28.6, 29.4, 31.0),
        ], events=events)

    def test_consistency_focus_promotes_consistency_note(self):
        s = self._consistency_session()
        notes_default = race_engineer_notes(s, track_map=self._MAP)
        tl_i = next(i for i, n in enumerate(notes_default)
                    if 'track-limits warning' in n)
        cons_i = next(i for i, n in enumerate(notes_default)
                      if 'focus on consistency' in n)
        assert tl_i < cons_i    # default order: incidents note precedes it

        notes_cons = race_engineer_notes(s, track_map=self._MAP,
                                         focus_id='consistency')
        tl_i2 = next(i for i, n in enumerate(notes_cons)
                     if 'track-limits warning' in n)
        cons_i2 = next(i for i, n in enumerate(notes_cons)
                       if 'focus on consistency' in n)
        assert cons_i2 < tl_i2  # promoted for a consistency focus

    def test_faster_focus_also_promotes_consistency_notes(self):
        # The gap-to-theoretical notes are consistency-tagged but are still
        # pace findings — a driver chasing time needs to know the pace is
        # already in their sectors, so 'faster' claims them too.
        s = self._consistency_session()
        notes_faster = race_engineer_notes(s, track_map=self._MAP,
                                           focus_id='faster')
        tl_i = next(i for i, n in enumerate(notes_faster)
                    if 'track-limits warning' in n)
        cons_i = next(i for i, n in enumerate(notes_faster)
                      if 'focus on consistency' in n)
        assert cons_i < tl_i

    def test_focus_with_no_matching_notes_leaves_order_unchanged(self):
        # 'clean' promotes incidents; this session's non-incident note is
        # pace-tagged, so nothing moves relative to the default order.
        events = [{'type': 'track_limit_warning', 'lap_num': 1,
                   'lap_time': 20.0, 'distance': 940}]
        s = _session([
            _lap(1, 91.0, 28.5, 29.6, 32.9),
            _lap(2, 89.0, 27.0, 28.0, 30.0),
        ], events=events)
        notes_default = race_engineer_notes(s, track_map=self._MAP)
        notes_unmapped = race_engineer_notes(s, track_map=self._MAP,
                                             focus_id='just_drive')
        assert notes_default == notes_unmapped


class TestTrackLimitHotspot:
    """track_limit_counts() (the shared bucketing helper) and the
    session-over-session comparison note it feeds."""

    _MAP = TestDetailedNotes._MAP

    def test_track_limit_counts_buckets_by_corner(self):
        events = [{'type': 'track_limit_warning', 'lap_num': n,
                   'lap_time': 20.0, 'distance': 940} for n in (1, 2)] + [
            {'type': 'track_limit_warning', 'lap_num': 3,
             'lap_time': 20.0, 'distance': 175}]
        assert track_limit_counts(events, self._MAP) == {'Turn 8': 2, 'Turn 1': 1}

    def test_track_limit_counts_empty_without_map_or_warnings(self):
        events = [{'type': 'track_limit_warning', 'lap_num': 1,
                   'lap_time': 20.0, 'distance': 940}]
        assert track_limit_counts(events, None) == {}
        assert track_limit_counts([], self._MAP) == {}

    def test_hotspot_comparison_fewer_warnings_this_session(self):
        events = [{'type': 'track_limit_warning', 'lap_num': 1,
                   'lap_time': 20.0, 'distance': 940}]
        s = _session([_lap(1, 91.0)], events=events)
        hotspot = {'label': 'Turn 8', 'count': 3}
        notes = race_engineer_notes(s, track_map=self._MAP,
                                    prior_track_limit_hotspot=hotspot)
        note = next(n for n in notes if 'Turn 8' in n and 'down from' in n)
        assert 'down from 3' in note

    def test_hotspot_comparison_clean_this_time(self):
        s = _session([_lap(1, 91.0)])   # no track-limit events at all
        hotspot = {'label': 'Turn 8', 'count': 3}
        notes = race_engineer_notes(s, track_map=self._MAP,
                                    prior_track_limit_hotspot=hotspot)
        note = next(n for n in notes if 'Turn 8' in n)
        assert 'clean there this time' in note

    def test_hotspot_comparison_still_an_issue(self):
        events = [{'type': 'track_limit_warning', 'lap_num': n,
                   'lap_time': 20.0, 'distance': 940} for n in (1, 2, 3)]
        s = _session([_lap(1, 91.0)], events=events)
        hotspot = {'label': 'Turn 8', 'count': 2}
        notes = race_engineer_notes(s, track_map=self._MAP,
                                    prior_track_limit_hotspot=hotspot)
        note = next(n for n in notes if 'Turn 8' in n and 'still catching' in n)
        assert note

    def test_no_hotspot_comparison_without_prior_hotspot(self):
        s = _session([_lap(1, 91.0)])
        notes = race_engineer_notes(s, track_map=self._MAP)
        assert not any('down from' in n or 'still catching' in n
                       or 'clean there this time' in n for n in notes)
