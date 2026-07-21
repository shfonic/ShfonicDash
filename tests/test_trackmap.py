"""
Tests for sessionlog.trackmap — locating a lap-distance against a track
map's labelled `sections`.

Shared test: lives canonically in ShfonicDash/tests/ and is copied
into the companion repo by sync_shared.py.
"""

import json

import pytest

from sessionlog import trackmap

TURN1 = {'turn': '1', 'name': 'Turn 1', 'type': 'corner',
         'start_m': 100, 'end_m': 240, 'apex_m': 175}
TURN8_NO_APEX = {'turn': '8', 'type': 'corner', 'start_m': 900, 'end_m': 980}
COMPLEX = {'name': 'Maggots/Becketts/Chapel', 'type': 'complex',
           'start_m': 4200, 'end_m': 4750, 'members': ['10', '11', '13']}
STRAIGHT = {'name': 'Pit Straight', 'type': 'straight',
            'start_m': 4900, 'end_m': 100}   # wraps across S/F

SECTIONS = [TURN1, TURN8_NO_APEX, COMPLEX, STRAIGHT]
TRACK_LENGTH = 5000


@pytest.fixture(autouse=True)
def _reset_tracks_dir():
    trackmap.set_tracks_dir(None)
    yield
    trackmap.set_tracks_dir(None)


class TestLocateSection:

    def test_finds_covering_section(self):
        assert trackmap.locate_section(150, SECTIONS) is TURN1

    def test_outside_any_span_is_none(self):
        assert trackmap.locate_section(500, SECTIONS) is None

    def test_none_distance_is_none(self):
        assert trackmap.locate_section(None, SECTIONS) is None

    def test_empty_sections_is_none(self):
        assert trackmap.locate_section(150, []) is None

    def test_corner_beats_overlapping_complex(self):
        overlapping = [COMPLEX, {'turn': '10', 'type': 'corner',
                                  'start_m': 4300, 'end_m': 4350}]
        sec = trackmap.locate_section(4320, overlapping, TRACK_LENGTH)
        assert sec['type'] == 'corner'

    def test_wraps_across_start_finish(self):
        sec = trackmap.locate_section(4950, SECTIONS, TRACK_LENGTH)
        assert sec is STRAIGHT
        sec = trackmap.locate_section(50, SECTIONS, TRACK_LENGTH)
        assert sec is STRAIGHT

    def test_distance_beyond_track_length_wraps_via_modulo(self):
        # 150 + one full lap should resolve the same as 150.
        sec = trackmap.locate_section(150 + TRACK_LENGTH, SECTIONS, TRACK_LENGTH)
        assert sec is TURN1


class TestDescribeLocation:

    def test_at_apex_within_tolerance(self):
        assert trackmap.describe_location(175, SECTIONS) == "at the apex of Turn 1"

    def test_before_apex(self):
        assert trackmap.describe_location(110, SECTIONS) == "at Turn 1, before the apex"

    def test_after_apex(self):
        assert trackmap.describe_location(230, SECTIONS) == "at Turn 1, after the apex"

    def test_corner_without_apex_data(self):
        assert trackmap.describe_location(940, SECTIONS) == "at Turn 8"

    def test_complex_label(self):
        assert (trackmap.describe_location(4400, SECTIONS)
                == "at Maggots/Becketts/Chapel")

    def test_straight_label(self):
        assert (trackmap.describe_location(4950, SECTIONS, TRACK_LENGTH)
                == "on the Pit Straight")

    def test_uncovered_point_brackets_by_corners(self):
        # 500 m sits in the gap between Turn 1 (…240) and Turn 8 (900…).
        assert (trackmap.describe_location(500, SECTIONS)
                == "between Turn 1 and Turn 8")

    def test_none_when_fewer_than_two_landmarks(self):
        one = [{'turn': '1', 'type': 'corner', 'start_m': 100, 'end_m': 240}]
        assert trackmap.describe_location(500, one) is None

    def test_apex_gap_wraps_near_start_finish(self):
        # Apex near the S/F line: a station just the other side of the
        # wrap should still read as close, not ~track-length away.
        wrapping_corner = {'turn': '1', 'type': 'corner',
                            'start_m': 4950, 'end_m': 50, 'apex_m': 4995}
        phrase = trackmap.describe_location(10, [wrapping_corner], TRACK_LENGTH)
        assert phrase == "at Turn 1, after the apex"


class TestBracketCorners:

    def test_prev_and_next_by_distance(self):
        prv, nxt = trackmap.bracket_corners(500, SECTIONS, TRACK_LENGTH)
        assert prv is TURN1 and nxt is TURN8_NO_APEX

    def test_wraps_across_start_finish(self):
        # A point just before S/F: next landmark is Turn 1 (100…), previous
        # is the complex (…4750), wrapping backwards over the line.
        prv, nxt = trackmap.bracket_corners(4850, SECTIONS, TRACK_LENGTH)
        assert nxt is TURN1 and prv is COMPLEX

    def test_none_with_one_landmark(self):
        one = [{'turn': '1', 'type': 'corner', 'start_m': 100, 'end_m': 240}]
        assert trackmap.bracket_corners(500, one, TRACK_LENGTH) is None

    def test_compact_label_prefers_turn_number(self):
        assert trackmap.bracket_label(TURN1, TURN8_NO_APEX) == "T1–T8"
        named = {'name': 'Abbey', 'type': 'corner', 'start_m': 0, 'end_m': 5}
        assert trackmap.bracket_label(TURN1, named) == "T1–Abbey"


class TestFindMap:

    def test_matches_by_content_not_filename(self, tmp_path):
        data = {'game': 'f1_25', 'track': 'Melbourne', 'sections': []}
        (tmp_path / 'weirdly-named.json').write_text(json.dumps(data))
        trackmap.set_tracks_dir(str(tmp_path))
        found = trackmap.find_map('F1_25', '  melbourne  ')
        assert found == data

    def test_no_match_is_none(self, tmp_path):
        data = {'game': 'f1_25', 'track': 'Melbourne'}
        (tmp_path / 'a.json').write_text(json.dumps(data))
        trackmap.set_tracks_dir(str(tmp_path))
        assert trackmap.find_map('f1_25', 'Silverstone') is None

    def test_missing_dir_is_none(self):
        trackmap.set_tracks_dir('/no/such/directory')
        assert trackmap.find_map('f1_25', 'Melbourne') is None

    def test_no_dir_set_is_none(self):
        assert trackmap.find_map('f1_25', 'Melbourne') is None

    def test_bad_json_is_skipped_not_raised(self, tmp_path):
        (tmp_path / 'broken.json').write_text('{not json')
        good = {'game': 'f1_25', 'track': 'Melbourne'}
        (tmp_path / 'good.json').write_text(json.dumps(good))
        trackmap.set_tracks_dir(str(tmp_path))
        assert trackmap.find_map('f1_25', 'Melbourne') == good


# 8-station square-ish loop, 800 m round → 100 m per station.
_CROP_MAP = {
    'game_track_length_m': 800,
    'left_edge':  [[0, i] for i in range(8)],
    'right_edge': [[2, i] for i in range(8)],
}


class TestCropGeometry:

    def test_window_slice_and_marker(self):
        g = trackmap.crop_geometry(_CROP_MAP, 200, half_window_m=150)
        # center station 2, half = round(150/100) = 2 → stations 0..4.
        assert len(g['left']) == 5
        assert len(g['right']) == 5
        assert g['left'][0] == [0, 0] and g['left'][-1] == [0, 4]
        # marker is the track centre at that station.
        assert g['marker'] == [1.0, 2.0]

    def test_heading_points_along_increasing_distance(self):
        # Stations run in +z; travel at station 2 is the +z unit vector.
        g = trackmap.crop_geometry(_CROP_MAP, 200, half_window_m=150)
        assert g['heading'] == [0.0, 1.0]

    def test_bounds_enclose_the_slice_with_padding(self):
        g = trackmap.crop_geometry(_CROP_MAP, 200, half_window_m=150)
        minx, minz, maxx, maxz = g['bounds']
        assert minx < 0 and maxx > 2      # padded past the edges (x 0..2)
        assert minz < 0 and maxz > 4      # padded past the window (z 0..4)

    def test_window_wraps_across_start_finish(self):
        # distance ~0 → center 0, window reaches back over the S/F line.
        g = trackmap.crop_geometry(_CROP_MAP, 0, half_window_m=150)
        assert len(g['left']) == 5
        zs = [p[1] for p in g['left']]
        assert 6 in zs and 7 in zs and 0 in zs   # wrapped: 6,7,0,1,2

    def test_none_when_no_geometry(self):
        assert trackmap.crop_geometry(None, 100) is None
        assert trackmap.crop_geometry(_CROP_MAP, None) is None
        assert trackmap.crop_geometry({'game_track_length_m': 800}, 100) is None
        assert trackmap.crop_geometry(
            {'left_edge': [[0, 0]], 'right_edge': [[2, 0]]}, 100) is None  # no length


# F1 (a shared-line game) with a per-class profile each — each class carries its
# own gears; the lines happen to be identical but are stored separately.
_F1_MAP = {'lines': {
    'formula1':      {'racing_line': [[0, 0], [1, 1]], 'racing_attempts': 2,
                      'gears': [7, 6]},
    'formula1_2026': {'racing_line': [[0, 0], [1, 1]], 'racing_attempts': 2,
                      'gears': [6, 5]},   # super-clip gearing
}}
# A multi-class game (PC2) keeps a true line per class.
_PC2_MAP = {'lines': {
    'gt3':           {'racing_line': [[0, 0]], 'racing_attempts': 1},
    'formula_rookie': {'racing_line': [[9, 9]], 'racing_attempts': 1},
}}


class TestResolveLine:
    def test_returns_the_class_own_profile_with_its_gears(self):
        # Each class resolves to its OWN entry, so per-class gears are preserved.
        assert trackmap.resolve_line(_F1_MAP, 'f1_25', 'formula1')['gears'] == [7, 6]
        assert trackmap.resolve_line(
            _F1_MAP, 'f1_25', 'formula1_2026')['gears'] == [6, 5]

    def test_shared_line_game_falls_back_for_an_unfilled_class(self):
        # 'f2' has no profile yet, but on a shared-line game a sibling's line
        # stands in (geometry only — no gears of its own).
        entry = trackmap.resolve_line(_F1_MAP, 'f1_25', 'f2')
        assert entry.get('racing_line') == [[0, 0], [1, 1]]

    def test_multi_class_game_keeps_lines_distinct(self):
        assert trackmap.resolve_line(_PC2_MAP, 'pcars2', 'gt3')['racing_line'] == [[0, 0]]
        assert trackmap.resolve_line(
            _PC2_MAP, 'pcars2', 'formula_rookie')['racing_line'] == [[9, 9]]

    def test_multi_class_game_no_cross_class_fallback(self):
        # An un-recorded PC2 class must NOT borrow another class's line.
        assert trackmap.resolve_line(_PC2_MAP, 'pcars2', 'lmp1') == {}

    def test_empty_when_no_map_or_no_lines(self):
        assert trackmap.resolve_line(None, 'f1_25', 'formula1') == {}
        assert trackmap.resolve_line({'lines': {}}, 'f1_25', 'formula1') == {}


def _approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


class TestOrientation:

    def test_orientation_deg_reads_and_defaults(self):
        assert trackmap.orientation_deg({'orientation': 90}) == 90.0
        assert trackmap.orientation_deg({'orientation': 0}) == 0.0
        assert trackmap.orientation_deg({}) == 0.0            # missing → 0
        assert trackmap.orientation_deg(None) == 0.0
        assert trackmap.orientation_deg({'orientation': 'x'}) == 0.0   # garbage → 0

    def test_rotate_xz_90_and_noop(self):
        # +90°: [1,0] → [0,1], [0,1] → [-1,0] (matches SVG rotate(90)).
        r = trackmap.rotate_xz([[1, 0], [0, 1]], 90)
        assert _approx(r[0][0], 0.0) and _approx(r[0][1], 1.0)
        assert _approx(r[1][0], -1.0) and _approx(r[1][1], 0.0)
        # 0° is an identity copy (new list, not the input objects).
        pts = [[3, 4]]
        out = trackmap.rotate_xz(pts, 0)
        assert out == [[3, 4]] and out is not pts

    def test_rotate_preserves_lengths(self):
        # A rotation is rigid: pairwise distances are unchanged.
        a, b = trackmap.rotate_xz([[10, 5], [13, 9]], 37)
        import math
        assert _approx(math.hypot(a[0] - b[0], a[1] - b[1]), 5.0)

    def test_crop_geometry_rotates_marker_and_heading(self):
        m = dict(_CROP_MAP, orientation=90)
        g = trackmap.crop_geometry(m, 200, half_window_m=150)
        # marker [1,2] → [-2,1]; heading [0,1] → [-1,0] under +90°.
        assert _approx(g['marker'][0], -2.0) and _approx(g['marker'][1], 1.0)
        assert _approx(g['heading'][0], -1.0) and _approx(g['heading'][1], 0.0)
        # unrotated map keeps the north-up marker/heading.
        g0 = trackmap.crop_geometry(_CROP_MAP, 200, half_window_m=150)
        assert g0['marker'] == [1.0, 2.0] and g0['heading'] == [0.0, 1.0]
