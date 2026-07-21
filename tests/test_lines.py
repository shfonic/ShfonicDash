"""
Tests for sessionlog.lines — racing-line adherence from the P-row offset
profiles: corner-zone adherence, the on_the_line achievement's session facts,
off-line Race Engineer Notes, and player-vs-racing mini-map geometry.

Shared test: lives canonically in ShfonicDash/tests/ and is copied
into the companion repo by sync_shared.py.
"""

import math

from sessionlog import lines

N = 400
LENGTH = 1000.0

# A circular racing line, with Turn 1 labelled over 100–300 m.
RACING = [[100.0 * math.cos(2 * math.pi * i / N),
           100.0 * math.sin(2 * math.pi * i / N)] for i in range(N)]
SECTIONS = [{'type': 'corner', 'turn': '1', 'name': 'Turn 1',
             'start_m': 100, 'end_m': 300, 'apex_m': 200}]
TRACK_MAP = {'game': 'f1_25', 'track': 'Ring', 'game_track_length_m': LENGTH,
             'lines': {'formula1': {'racing_line': RACING}}, 'sections': SECTIONS}


def _flat(value):
    return [value] * N


def _wide_in_corner(value):
    """A profile that is on-line everywhere except a fixed offset through the
    Turn 1 corner zone (100–300 m)."""
    prof = [0.0] * N
    for i in range(N):
        if 100 <= i * LENGTH / N <= 300:
            prof[i] = value
    return prof


def _lap(num, offsets, time=90.0, invalid=False):
    return {'num': num, 'time': time, 'invalid': invalid,
            'line_offsets': offsets}


# ---- lap_adherence --------------------------------------------------------

def test_adherence_on_line_when_tight():
    adh = lines.lap_adherence(_flat(0.4), SECTIONS, LENGTH)
    assert adh['on_line'] is True
    assert adh['corner_avg'] < 1.0


def test_adherence_flags_wide_corner():
    adh = lines.lap_adherence(_wide_in_corner(3.0), SECTIONS, LENGTH)
    assert adh['on_line'] is False
    assert round(adh['corner_max'], 1) == 3.0
    assert adh['worst'][0]['label'] == 'Turn 1'
    assert round(adh['worst'][0]['offset_m'], 1) == 3.0


def test_adherence_only_weights_corner_zones():
    # Wide on the straights but dead-on through the corner → still on-line.
    prof = [5.0] * N
    for i in range(N):
        if 100 <= i * LENGTH / N <= 300:
            prof[i] = 0.2
    adh = lines.lap_adherence(prof, SECTIONS, LENGTH)
    assert adh['on_line'] is True


def test_adherence_none_without_corner_sections():
    assert lines.lap_adherence(_flat(0.2), [], LENGTH) is None
    assert lines.lap_adherence([], SECTIONS, LENGTH) is None


# ---- session_line_facts ---------------------------------------------------

def test_facts_empty_without_map_or_profiles():
    assert lines.session_line_facts({}, None)['on_line_session'] is False
    sess = {'session_type': 'hotlap', 'laps': [{'num': 1, 'time': 90.0}]}
    assert lines.session_line_facts(sess, TRACK_MAP)['push_lap_count'] == 0


def test_facts_hotlap_needs_three_on_line_laps():
    two = {'session_type': 'hotlap',
           'laps': [_lap(1, _flat(0.3)), _lap(2, _flat(0.3))]}
    assert lines.session_line_facts(two, TRACK_MAP)['on_line_session'] is False
    three = {'session_type': 'hotlap',
             'laps': [_lap(i, _flat(0.3)) for i in range(1, 4)]}
    f = lines.session_line_facts(three, TRACK_MAP)
    assert f['on_line_lap_count'] == 3
    assert f['on_line_session'] is True


def test_facts_quali_all_push_must_be_on_line():
    one = {'session_type': 'qualifying', 'laps': [_lap(1, _flat(0.3))]}
    assert lines.session_line_facts(one, TRACK_MAP)['on_line_session'] is True
    # A second push lap that runs wide breaks the "all push laps" rule.
    mixed = {'session_type': 'qualifying',
             'laps': [_lap(1, _flat(0.3), time=90.0),
                      _lap(2, _wide_in_corner(3.0), time=90.5)]}
    f = lines.session_line_facts(mixed, TRACK_MAP)
    assert f['push_lap_count'] == 2 and f['on_line_lap_count'] == 1
    assert f['on_line_session'] is False


def test_facts_ignores_out_lap_outside_push_band():
    # A slow out-lap (well outside the push band) that runs wide must not
    # count as a push lap, so the quali still reads as on-line.
    sess = {'session_type': 'qualifying',
            'laps': [_lap(1, _wide_in_corner(4.0), time=120.0),   # out-lap
                     _lap(2, _flat(0.3), time=90.0)]}             # the push lap
    f = lines.session_line_facts(sess, TRACK_MAP)
    assert f['push_lap_count'] == 1
    assert f['on_line_session'] is True


# ---- mini-map geometry ----------------------------------------------------

def test_player_geometry_reconstructs_offset_side():
    # +5 m everywhere pushes the driven circle out to radius ~105 (the sign
    # convention must match core.geometry so it lands on the correct side).
    geom = lines.player_line_geometry(TRACK_MAP, _flat(5.0))
    r = math.hypot(geom['player'][0][0], geom['player'][0][1])
    assert 104.0 < r < 106.0
    assert len(geom['racing']) == len(geom['player'])


def test_player_geometry_crop_window():
    full = lines.player_line_geometry(TRACK_MAP, _flat(1.0))
    crop = lines.player_line_geometry(TRACK_MAP, _flat(1.0),
                                      distance=200.0, half_window=50.0)
    assert len(crop['player']) < len(full['player'])


def test_player_geometry_none_without_line():
    assert lines.player_line_geometry({'lines': {}}, _flat(1.0)) is None
    assert lines.player_line_geometry(TRACK_MAP, []) is None


# ---- notes ----------------------------------------------------------------

def test_line_notes_flag_wide_corner():
    sess = {'session_type': 'hotlap', 'laps': [_lap(1, _wide_in_corner(3.0))]}
    notes = lines.line_notes_detailed(sess, TRACK_MAP)
    assert notes and 'Turn 1' in notes[0]['text']
    assert notes[0]['locations'][0]['kind'] == 'off_line'


def test_line_notes_invalid_lap_context():
    sess = {'session_type': 'hotlap',
            'laps': [_lap(1, _flat(0.3)),
                     _lap(2, _wide_in_corner(3.5), invalid=True)]}
    notes = lines.line_notes_detailed(sess, TRACK_MAP)
    assert any('invalidated' in n['text'] for n in notes)


def test_line_notes_silent_when_on_line():
    sess = {'session_type': 'hotlap', 'laps': [_lap(1, _flat(0.3))]}
    assert lines.line_notes_detailed(sess, TRACK_MAP) == []


def test_best_line_offsets_picks_fastest_clean():
    sess = {'laps': [_lap(1, _flat(2.0), time=91.0),
                     _lap(2, _flat(0.3), time=90.0),
                     _lap(3, _wide_in_corner(5.0), time=89.0, invalid=True)]}
    # Fastest *clean* profiled lap is lap 2, not the invalid lap 3.
    assert lines.best_line_offsets(sess) == _flat(0.3)


# ---- session_line_export --------------------------------------------------

def test_export_none_without_map_or_line():
    sess = {'laps': [_lap(1, _flat(0.3))], 'car_class': 'formula1'}
    assert lines.session_line_export(sess, None) is None
    # A map with no racing line has nothing to draw against.
    assert lines.session_line_export(sess, {'lines': {}}) is None


def test_export_race_map_without_profiles():
    """A race/practice with no per-lap profiles still exports the map + its
    incident markers — the whole point of the map for races."""
    sess = {'car_class': 'formula1', 'session_type': 'race', 'laps': [],
            'events': [{'type': 'collision', 'distance': 300.0, 'lap_num': 4},
                       {'type': 'pit_in', 'distance': 5.0, 'lap_num': 4}]}
    out = lines.session_line_export(sess, TRACK_MAP)
    assert out is not None
    assert out['laps'] == []
    assert out['best_num'] is None
    assert out['events'] == [{'distance': 300.0, 'kind': 'contact',
                              'lap_num': 4, 'laps': [4]}]


def test_session_map_geometry_places_events():
    geom = lines.session_map_geometry(
        TRACK_MAP, 'formula1',
        events=[{'distance': 0.0, 'kind': 'track_limit', 'lap_num': 2}])
    assert len(geom['racing']) == N
    assert geom['player'] is None          # no offsets → no driven line
    assert len(geom['events']) == 1
    ev = geom['events'][0]
    assert ev['kind'] == 'track_limit' and ev['lap_num'] == 2
    # distance 0 sits on the first station of the racing line.
    assert ev['pos'][0] == RACING[0][0] and ev['pos'][1] == RACING[0][1]


def test_session_map_geometry_reconstructs_player_with_offsets():
    geom = lines.session_map_geometry(TRACK_MAP, 'formula1', offsets=_flat(5.0))
    assert geom['player'] is not None and len(geom['player']) == N
    assert lines.session_map_geometry({'lines': {}}, 'formula1') is None


def test_session_map_geometry_events_on_their_lap_line():
    # Lap 2's driven line sits +10 m out (radius ~110). With that lap's offsets
    # supplied, its incident marker lands on the driven line, not the racing line.
    events = [{'distance': 250.0, 'kind': 'contact', 'lap_num': 2}]
    geom = lines.session_map_geometry(TRACK_MAP, 'formula1', events=events,
                                      lap_offsets={2: _flat(10.0)})
    x, z = geom['events'][0]['pos']
    assert 108.0 < math.hypot(x, z) < 112.0


def test_session_map_geometry_events_fall_back_to_racing_line():
    # No profile for the event's lap → marker sits on the racing line (~100).
    events = [{'distance': 250.0, 'kind': 'contact', 'lap_num': 2}]
    geom = lines.session_map_geometry(TRACK_MAP, 'formula1', events=events)
    x, z = geom['events'][0]['pos']
    assert 98.0 < math.hypot(x, z) < 102.0


def test_lap_offsets_map():
    sess = {'laps': [_lap(1, _flat(0.3)), _lap(2, _flat(1.0)),
                     {'num': 3, 'time': 90.0}]}   # lap 3 has no profile
    m = lines.lap_offsets_map(sess)
    assert set(m) == {1, 2} and m[2] == _flat(1.0)


def test_export_packages_every_profiled_lap():
    sess = {'car_class': 'formula1', 'car_class_name': 'F1 2025',
            'session_type': 'hotlap', 'game': 'f1_25', 'track': 'Ring',
            'laps': [_lap(1, _flat(2.0), time=91.0),
                     _lap(2, _flat(0.3), time=90.0),
                     _lap(3, None, time=88.0)]}    # no profile → excluded
    out = lines.session_line_export(sess, TRACK_MAP)
    assert out['track'] is TRACK_MAP
    assert out['car_class'] == 'formula1'
    assert out['session']['title'] == 'F1 2025'
    assert out['session']['session_type'] == 'hotlap'
    # Only the two laps that carry a profile travel; offsets stay in metres.
    assert [lap['num'] for lap in out['laps']] == [1, 2]
    assert out['laps'][0]['offsets'] == _flat(2.0)
    # Best clean profiled lap (fastest valid) is lap 2.
    assert out['best_num'] == 2


def test_export_carries_sectors_and_events():
    sess = {'car_class': 'formula1', 'session_type': 'hotlap',
            'laps': [{'num': 1, 'time': 90.0, 'valid': True,
                      's1': 30.0, 's2': 31.0, 's3': 29.0,
                      'line_offsets': _flat(0.3)}],
            'events': [{'type': 'invalid', 'distance': 250.0, 'lap_num': 1},
                       {'type': 'pit_in', 'distance': 5.0, 'lap_num': 1}]}
    out = lines.session_line_export(sess, TRACK_MAP)
    lap = out['laps'][0]
    assert (lap['s1'], lap['s2'], lap['s3']) == (30.0, 31.0, 29.0)
    # pit_in is not a map event; the invalidation becomes a track_limit marker.
    assert out['events'] == [{'distance': 250.0, 'kind': 'track_limit',
                              'lap_num': 1, 'laps': [1]}]


def test_export_invalid_from_valid_flag():
    """Typed-format laps carry `valid`, not `invalid` — the export must still
    flag them (the bug that hid the invalid badge in the viewer)."""
    sess = {'car_class': 'formula1',
            'laps': [{'num': 1, 'time': 90.0, 'valid': False,
                      'line_offsets': _flat(0.3)},
                     {'num': 2, 'time': 91.0, 'valid': True,
                      'line_offsets': _flat(0.3)}]}
    out = lines.session_line_export(sess, TRACK_MAP)
    assert [lap['invalid'] for lap in out['laps']] == [True, False]


def test_map_events_contact_flashback_and_lap_list():
    sess = {'events': [
        {'type': 'collision', 'distance': 400.0, 'lap_num': 2, 't': 10.0},
        {'type': 'rewind', 'distance': None, 'lap_num': 2, 't': 11.0},  # undoes it
        {'type': 'penalty', 'distance': 700.0, 'lap_num': 3, 't': 20.0,
         'detail': 'lap_invalidated_no_reason:lap_invalidated_running_wide'},
        {'type': 'invalid', 'distance': 705.0, 'lap_num': 5, 't': 21.0},  # merges
        {'type': 'penalty', 'distance': 900.0, 'lap_num': 4, 't': 30.0,
         'detail': 'time_penalty:speeding_in_pit_lane'},          # not mapped
    ]}
    by = {e['kind']: e for e in lines.map_events(sess)}
    # The flashback is placed at the contact it undid (rewind has no distance).
    assert by['contact']['distance'] == 400.0 and by['contact']['laps'] == [2]
    assert by['flashback']['distance'] == 400.0 and by['flashback']['laps'] == [2]
    # The two track-limits events at ~the same spot merge and list both laps.
    assert by['track_limit']['laps'] == [3, 5]
    assert by['track_limit']['lap_num'] == 3        # earliest lap is primary
    # Only contacts carry a drivers list.
    assert 'drivers' not in by['track_limit']
    assert 'drivers' not in by['flashback']


def test_map_events_contact_names_drivers():
    sess = {'events': [
        {'type': 'collision', 'distance': 400.0, 'lap_num': 2, 't': 10.0, 'detail': 'PÉREZ'},
        {'type': 'collision', 'distance': 402.0, 'lap_num': 2, 't': 11.0, 'detail': 'OCON'},
    ]}
    contact = [e for e in lines.map_events(sess) if e['kind'] == 'contact'][0]
    assert contact['drivers'] == ['PÉREZ', 'OCON']


def test_map_events_marks_invalid_lap_off_line():
    """An invalid lap's worst off-line corner becomes a marker even with no
    E-row event there — the map must show what the engineering notes call out
    (the Fagnes case: penalty logged elsewhere, big excursion in a corner)."""
    sess = {'laps': [{'num': 3, 'time': 90.0, 'valid': False,
                      'line_offsets': _wide_in_corner(5.0)}], 'events': []}
    evs = lines.map_events(sess, TRACK_MAP)
    assert len(evs) == 1
    assert evs[0]['kind'] == 'track_limit' and evs[0]['lap_num'] == 3
    assert 100 <= evs[0]['distance'] <= 300      # within the Turn 1 corner zone
    # A *valid* lap running wide is coaching, not an incident marker.
    sess['laps'][0]['valid'] = True
    assert lines.map_events(sess, TRACK_MAP) == []


def test_map_events_one_marker_per_corner():
    """Two invalid laps that ran wide at the same corner → a single marker."""
    sess = {'laps': [{'num': 1, 'time': 90.0, 'valid': False,
                      'line_offsets': _wide_in_corner(3.0)},
                     {'num': 2, 'time': 90.0, 'valid': False,
                      'line_offsets': _wide_in_corner(4.0)}], 'events': []}
    assert len(lines.map_events(sess, TRACK_MAP)) == 1


def _wide_at(start, end, value):
    prof = [0.0] * N
    for i in range(N):
        if start <= i * LENGTH / N <= end:
            prof[i] = value
    return prof


MULTI_SECTIONS = [
    {'type': 'corner', 'turn': '1', 'name': 'Turn 1', 'start_m': 50, 'end_m': 150},
    {'type': 'corner', 'turn': '2', 'name': 'Turn 2', 'start_m': 250, 'end_m': 350},
    {'type': 'corner', 'turn': '3', 'name': 'Turn 3', 'start_m': 450, 'end_m': 550},
]
MULTI_MAP = {'game': 'f1_25', 'track': 'Ring', 'game_track_length_m': LENGTH,
             'lines': {'formula1': {'racing_line': RACING}},
             'sections': MULTI_SECTIONS}


def test_notes_focus_on_single_worst_corner():
    # Off at all three corners, worst at Turn 2 → one note, not three.
    prof = [0.0] * N
    for i in range(N):
        d = i * LENGTH / N
        if 50 <= d <= 150:
            prof[i] = 2.0
        elif 250 <= d <= 350:
            prof[i] = 5.0     # the worst offender
        elif 450 <= d <= 550:
            prof[i] = 3.0
    sess = {'session_type': 'hotlap', 'laps': [_lap(1, prof)]}
    notes = lines.line_notes_detailed(sess, MULTI_MAP)
    wide = [n for n in notes if 'Ran wide' in n['text']]
    assert len(wide) == 1
    assert 'Turn 2' in wide[0]['text']
    assert 'widest of 3 corners' in wide[0]['text']


def test_notes_single_corner_has_no_count_tail():
    sess = {'session_type': 'hotlap',
            'laps': [_lap(1, _wide_at(50, 150, 3.0))]}
    notes = lines.line_notes_detailed(sess, MULTI_MAP)
    wide = [n for n in notes if 'Ran wide' in n['text']]
    assert len(wide) == 1 and 'widest of' not in wide[0]['text']


def test_notes_invalid_picks_worst_across_laps():
    sess = {'session_type': 'hotlap', 'laps': [
        _lap(1, _wide_at(50, 150, 2.5), invalid=True),
        _lap(2, _wide_at(250, 350, 6.0), invalid=True),   # worst invalid
    ]}
    notes = lines.line_notes_detailed(sess, MULTI_MAP)
    inv = [n for n in notes if 'invalidated' in n['text']]
    assert len(inv) == 1
    assert 'Lap 2' in inv[0]['text'] and 'Turn 2' in inv[0]['text']


# ---- corner_deviations / line_hotspot -------------------------------------

def test_corner_deviations_maps_labels_to_offset():
    sess = {'session_type': 'hotlap',
            'laps': [_lap(1, _wide_in_corner(2.5))]}
    dev = lines.corner_deviations(sess, TRACK_MAP)
    assert round(dev['Turn 1'], 1) == 2.5


def test_corner_deviations_uses_the_fastest_clean_lap():
    sess = {'session_type': 'hotlap',
            'laps': [_lap(1, _wide_in_corner(3.0), time=91.0),
                     _lap(2, _wide_in_corner(1.2), time=90.0)]}   # fastest, tighter
    dev = lines.corner_deviations(sess, TRACK_MAP)
    assert round(dev['Turn 1'], 1) == 1.2


def test_corner_deviations_empty_without_line_data():
    sess = {'session_type': 'hotlap', 'laps': [{'num': 1, 'time': 90.0}]}
    assert lines.corner_deviations(sess, TRACK_MAP) == {}


def test_line_hotspot_flags_worst_corner():
    sess = {'session_type': 'hotlap',
            'laps': [_lap(1, _wide_in_corner(2.5))]}
    hot = lines.line_hotspot(sess, TRACK_MAP)
    assert hot['label'] == 'Turn 1'
    assert round(hot['offset_m'], 1) == 2.5


def test_line_hotspot_none_when_on_the_line():
    sess = {'session_type': 'hotlap', 'laps': [_lap(1, _flat(0.3))]}
    assert lines.line_hotspot(sess, TRACK_MAP) is None


def test_orientation_rotates_player_line_geometry():
    # +90°: RACING[0] = [100, 0] rotates to [0, 100] (matches SVG rotate(90)).
    rot = dict(TRACK_MAP, orientation=90)
    g = lines.player_line_geometry(rot, _flat(0.0))
    assert math.isclose(g['racing'][0][0], 0.0, abs_tol=1e-6)
    assert math.isclose(g['racing'][0][1], 100.0, abs_tol=1e-6)
    # A circle about the origin is rotation-invariant, so the fit box is unchanged.
    g0 = lines.player_line_geometry(TRACK_MAP, _flat(0.0))
    for a, b in zip(g['bounds'], g0['bounds']):
        assert math.isclose(a, b, abs_tol=1e-6)


def test_orientation_rotates_session_map_events():
    # An incident marker rotates with the circuit: [x, z] -> [-z, x] at +90°.
    events = [{'distance': 0.0, 'kind': 'contact', 'lap_num': 1}]
    g = lines.session_map_geometry(dict(TRACK_MAP, orientation=90),
                                   'formula1', events=events)
    g0 = lines.session_map_geometry(TRACK_MAP, 'formula1', events=events)
    p, p0 = g['events'][0]['pos'], g0['events'][0]['pos']
    assert math.isclose(p[0], -p0[1], abs_tol=1e-6)
    assert math.isclose(p[1], p0[0], abs_tol=1e-6)
