"""Tests for core.session_summary — the end-of-session summary screen.

Pi-repo only (drives core/ code, not the shared sessionlog package).
build_summary() is exercised against real CSVs in a tmp logs dir, so the
records index (.sessions.db) is created there and prior-best lookups run
for real. Rendering is smoke-tested onto a plain Surface.
"""
import os

import pygame
import pytest

from core.session_summary import (
    DriveAwayDetector,
    SessionSummaryView,
    build_summary,
)

LAP_HEADER = ('H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,'
              'tyre_compound,fuel_remaining,fuel_per_lap,position,delta,invalid,rewinds')


def _session_csv(times, track='Monaco', session_type='practice',
                 started='2026-07-07T10:00:00', invalid=None, focus=None):
    invalid = invalid or set()
    rows = [
        'S,version,1',
        f'S,started_at,{started}',
        'S,game,f1_25',
        f'S,session_type,{session_type}',
        'S,car_class,formula1',
        'S,car_name,McLaren',
        f'S,track,{track}',
    ]
    if focus:
        rows.append(f'F,{focus}')
    rows.append(LAP_HEADER)
    for i, t in enumerate(times, start=1):
        inv = 1 if i in invalid else 0
        s1, s2, s3 = round(t * 0.31, 3), round(t * 0.33, 3), round(t * 0.36, 3)
        rows.append(f'L,{i},{t},{s1},{s2},{s3},,,,,,,,,,{inv},0')
    return '\n'.join(rows) + '\n'


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return str(path)


class TestBuildSummary:

    def test_stints_from_compound_column(self, tmp_path):
        rows = [
            'S,version,1', 'S,started_at,2026-07-07T10:00:00',
            'S,game,f1_25', 'S,session_type,practice',
            'S,car_class,formula1', 'S,track,Monaco', LAP_HEADER,
        ]
        for i, (t, cmp_) in enumerate([(91.2, 'Soft'), (90.5, 'Soft'),
                                       (90.9, 'Medium'), (91.4, 'Medium')],
                                      start=1):
            rows.append(f'L,{i},{t},28.0,30.0,{t - 58.0},,,,,{cmp_},,,,,0,0')
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      '\n'.join(rows) + '\n')

        s = build_summary(path)

        assert s['stints'] == [('Soft', 2), ('Medium', 2)]

    def test_no_compounds_means_no_stints(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9, 91.4]))
        assert build_summary(path)['stints'] == []

    def test_full_summary_from_csv(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9, 91.4]))
        s = build_summary(path)
        assert s is not None
        assert s['label'] == 'PRACTICE'
        assert s['track'] == 'Monaco'
        assert s['car'] == 'McLaren'
        assert s['laps_total'] == 4
        assert s['laps_clean'] == 4
        assert s['fastest'] == 90.5
        assert s['theo'] is not None
        assert s['grade'] is not None
        assert isinstance(s['notes'], list)
        # The finished session was indexed next to its CSV
        assert os.path.exists(tmp_path / '.sessions.db')

    def test_no_laps_returns_none(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([]))
        assert build_summary(path) is None

    def test_unreadable_file_returns_none(self, tmp_path):
        assert build_summary(str(tmp_path / 'missing.csv')) is None

    def test_prior_best_comes_from_earlier_session_only(self, tmp_path):
        _write(tmp_path, 'session_20260701_1000_practice.csv',
               _session_csv([90.0, 89.5], started='2026-07-01T10:00:00'))
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9]))
        s = build_summary(path)
        assert s['prior_best'] == 89.5
        # The older session holds the combo record
        assert s['overall_best'] == 89.5
        assert s['overall_holds'] is False

    def test_only_session_holds_the_overall_record(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9]))
        s = build_summary(path)
        assert s['overall_best'] == 90.5
        assert s['overall_holds'] is True

    def test_no_history_means_no_prior_best(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9]))
        assert build_summary(path)['prior_best'] is None

    def test_too_few_laps_is_ungraded_but_still_summarised(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2]))
        s = build_summary(path)
        assert s is not None
        assert s['grade'] is None


class TestFocusVerdict:
    def test_clean_focus_met_on_clean_session(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9, 91.4], focus='clean'))
        v = build_summary(path)['focus_verdict']
        assert v is not None
        assert v['title'] == 'CLEAN LAPS'
        assert v['met'] is True

    def test_clean_focus_missed_with_invalids(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9, 91.4], invalid={3},
                                   focus='clean'))
        v = build_summary(path)['focus_verdict']
        assert v['met'] is False
        assert '1 invalid' in v['headline']

    def test_faster_focus_beats_prior(self, tmp_path):
        _write(tmp_path, 'session_20260701_1000_practice.csv',
               _session_csv([90.0, 90.2], started='2026-07-01T10:00:00'))
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([89.4, 89.8], focus='faster'))
        v = build_summary(path)['focus_verdict']
        assert v['met'] is True                      # 89.4 < prior 90.0
        assert 'New best' in v['headline']

    def test_just_drive_has_no_verdict(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5], focus='just_drive'))
        assert build_summary(path)['focus_verdict'] is None

    def test_no_focus_no_verdict(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5]))
        assert build_summary(path)['focus_verdict'] is None

    def test_clean_focus_compares_against_previous_session_rate(self, tmp_path):
        # Previous session: laps 3 and 4 invalid → 2/4 clean = 50%.
        _write(tmp_path, 'session_20260701_1000_practice.csv',
               _session_csv([91.2, 90.5, 90.9, 91.4], invalid={3, 4},
                            started='2026-07-01T10:00:00'))
        # This session: all clean → 4/4 = 100%.
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9, 91.4], focus='clean'))
        v = build_summary(path)['focus_verdict']
        assert v['met'] is True
        assert 'Better than your previous 50% clean' in v['detail']

    def test_focus_verdict_note_leads_race_engineer_notes(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9, 91.4], focus='clean'))
        s = build_summary(path)
        assert s['notes'][0].startswith('CLEAN LAPS —')


class TestTrackLimitHotspotComparison:
    """Phase C: the corner that dominated the PREVIOUS session's track-limit
    warnings compared against this session's count at that same corner —
    the follow-up to sessionlog.goals' "watch your line" mission.

    build_summary() looks for tracks/ as a SIBLING of the CSV's directory
    (logs/../tracks — see main.py's real layout), so these tests use their
    own logs/ + tracks/ pair nested under tmp_path rather than the plain
    _write(tmp_path, ...) helper the rest of this file uses directly.
    """

    def _setup(self, tmp_path):
        import json
        logs_dir = tmp_path / 'logs'
        tracks_dir = tmp_path / 'tracks'
        logs_dir.mkdir()
        tracks_dir.mkdir()
        (tracks_dir / 'f1_25_monaco.json').write_text(json.dumps({
            'game': 'f1_25', 'track': 'Monaco', 'game_track_length_m': 3337,
            'sections': [{'turn': '1', 'name': 'Sainte Devote', 'type': 'corner',
                         'start_m': 0, 'end_m': 100, 'apex_m': 50}],
        }))
        return logs_dir

    def _session_with_warnings(self, logs_dir, filename, started, n_warnings):
        rows = [
            'S,version,1', f'S,started_at,{started}',
            'S,game,f1_25', 'S,session_type,practice',
            'S,car_class,formula1', 'S,track,Monaco', LAP_HEADER,
            'L,1,91.2,,,,,,,,,,,,,0,0',
            'EH,lap_num,lap_time,type,distance,t,detail',
        ]
        for i in range(n_warnings):
            rows.append(f'E,1,{10.0 + i * 5},track_limit_warning,50,{5.0 + i * 5},')
        (logs_dir / filename).write_text('\n'.join(rows) + '\n')

    def test_fewer_warnings_at_the_hotspot_corner_this_session(self, tmp_path):
        logs_dir = self._setup(tmp_path)
        self._session_with_warnings(logs_dir, 'session_20260701_1000_practice.csv',
                                    '2026-07-01T10:00:00', 3)
        self._session_with_warnings(logs_dir, 'session_20260707_1000_practice.csv',
                                    '2026-07-07T10:00:00', 1)
        path = str(logs_dir / 'session_20260707_1000_practice.csv')

        s = build_summary(path)
        note = next(n for n in s['notes']
                    if 'Sainte Devote' in n and 'down from' in n)
        assert 'down from 3' in note

    def test_clean_this_time_when_previous_had_a_hotspot(self, tmp_path):
        logs_dir = self._setup(tmp_path)
        self._session_with_warnings(logs_dir, 'session_20260701_1000_practice.csv',
                                    '2026-07-01T10:00:00', 3)
        self._session_with_warnings(logs_dir, 'session_20260707_1000_practice.csv',
                                    '2026-07-07T10:00:00', 0)
        path = str(logs_dir / 'session_20260707_1000_practice.csv')

        s = build_summary(path)
        note = next(n for n in s['notes'] if 'Sainte Devote' in n)
        assert 'clean there this time' in note

    def test_no_comparison_without_a_prior_hotspot(self, tmp_path):
        logs_dir = self._setup(tmp_path)
        # Previous session: only 1 warning — below the n>=2 hotspot threshold.
        self._session_with_warnings(logs_dir, 'session_20260701_1000_practice.csv',
                                    '2026-07-01T10:00:00', 1)
        self._session_with_warnings(logs_dir, 'session_20260707_1000_practice.csv',
                                    '2026-07-07T10:00:00', 1)
        path = str(logs_dir / 'session_20260707_1000_practice.csv')

        s = build_summary(path)
        assert not any('down from' in n or 'clean there this time' in n
                       or 'still catching' in n for n in s['notes'])


class TestDriveAwayDetector:

    def test_sustained_speed_triggers(self):
        d = DriveAwayDetector(speed_kmh=30, frames=3)
        assert d.update(80) is False
        assert d.update(80) is False
        assert d.update(80) is True

    def test_blip_resets_the_count(self):
        d = DriveAwayDetector(speed_kmh=30, frames=3)
        d.update(80)
        d.update(80)
        assert d.update(0) is False      # stopped again — reset
        assert d.update(80) is False
        assert d.update(80) is False
        assert d.update(80) is True

    def test_garage_crawl_never_triggers(self):
        d = DriveAwayDetector(speed_kmh=30, frames=3)
        assert not any(d.update(15) for _ in range(20))


class TestRender:

    @pytest.fixture(autouse=True)
    def _pygame(self):
        pygame.init()
        # Earlier test files cycle pygame.init()/quit(); fonts cached
        # under a previous init are dead and segfault on render.
        from dashboard.widgets import fonts
        fonts.clear_cache()
        yield
        pygame.quit()

    def _surface_has_content(self, surface):
        from dashboard.widgets import design_system as DS
        return any(surface.get_at((x, y))[:3] != DS.BG
                   for x, y in ((40, 30), (40, 140), (400, 140)))

    def test_render_smoke(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9, 91.4], invalid={4}))
        summary = build_summary(path)
        surface = pygame.Surface((800, 480))
        SessionSummaryView(summary).render(surface)
        assert self._surface_has_content(surface)

    def test_render_ungraded_session(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2]))
        summary = build_summary(path)
        surface = pygame.Surface((800, 480))
        SessionSummaryView(summary).render(surface)
        assert self._surface_has_content(surface)

    def test_render_with_focus_banner(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9, 91.4], focus='clean'))
        summary = build_summary(path)
        assert summary['focus_verdict'] is not None
        surface = pygame.Surface((800, 480))
        SessionSummaryView(summary).render(surface)   # banner must not raise
        assert self._surface_has_content(surface)


class TestAwardBanner:
    def test_summary_carries_awards(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_practice.csv',
                      _session_csv([91.2, 90.5, 90.9, 91.4]))
        summary = build_summary(path)
        assert isinstance(summary.get("awards"), list)

    def test_banner_lines(self):
        from core.session_summary import _award_banner
        assert _award_banner([]) is None
        assert _award_banner(
            [{"name": "First Blood", "kind": "unlocked",
              "count": 1, "tier": None}]) == "NEW BADGE — FIRST BLOOD"
        assert _award_banner(
            [{"name": "Clean Sweep", "kind": "upgraded",
              "count": 5, "tier": "silver"}]) == "CLEAN SWEEP ×5 — SILVER"
        assert _award_banner(
            [{"name": "Winner", "kind": "repeat", "count": 3, "tier": None},
             {"name": "Podium", "kind": "repeat", "count": 4, "tier": None}]
        ) == "WINNER ×3  (+1 MORE)"
