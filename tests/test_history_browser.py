"""Tests for core.history_browser — the session history browser.

Pi-repo only. ScrollPane logic is exercised directly; the list and
detail views are smoke-rendered against real CSVs in a tmp logs dir
(records index included), following the same pattern as
test_session_summary.py.
"""
import pygame
import pytest

from core.history_browser import (
    HistoryBrowser,
    ScrollPane,
    _badge_text,
)

LAP_HEADER = ('H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,'
              'tyre_compound,fuel_remaining,fuel_per_lap,position,delta,invalid,rewinds')


def _session_csv(times, session_type='practice', started='2026-07-07T10:00:00',
                 track='Monaco', rewinds=None):
    rewinds = rewinds or {}
    rows = [
        'S,version,1',
        f'S,started_at,{started}',
        'S,game,f1_25',
        f'S,session_type,{session_type}',
        'S,car_class,formula1',
        'S,car_name,McLaren',
        'S,driver_name,PIASTRI',
        f'S,track,{track}',
        LAP_HEADER,
    ]
    for i, t in enumerate(times, start=1):
        s1, s2 = round(t * 0.31, 3), round(t * 0.33, 3)
        s3 = round(t - s1 - s2, 3)
        rows.append(f'L,{i},{t},{s1},{s2},{s3},,,,,,,,{i},,0,{rewinds.get(i, 0)}')
    if session_type in ('race', 'qualifying'):
        rows.append('RH,position,race_num,name,best_lap,race_time')
        rows.append(f'R,1,81,PIASTRI,{min(times)},')
        rows.append('R,2,4,NORRIS,,')
    return '\n'.join(rows) + '\n'


def _write_sessions(tmp_path, n=3):
    for i in range(n):
        name = f'session_2026070{i + 1}_1000_practice.csv'
        (tmp_path / name).write_text(
            _session_csv([91.0 + i, 90.5 + i, 90.9 + i],
                         started=f'2026-07-0{i + 1}T10:00:00'),
            encoding='utf-8')


class TestScrollPane:

    def test_content_smaller_than_viewport_never_scrolls(self):
        p = ScrollPane(400, content_h=100)
        p.press((10, 300)); p.motion((10, 100)); p.release((10, 100))
        assert p.offset == 0

    def test_drag_scrolls_and_clamps(self):
        p = ScrollPane(400, content_h=1000)
        p.press((10, 300))
        p.motion((10, 100))            # dragged up 200 -> scrolled down 200
        assert p.offset == 200
        p.motion((10, -5000))          # way past the end
        assert p.offset == 600         # clamped to content_h - viewport
        assert p.release((10, -5000)) is None   # a drag is not a tap

    def test_small_movement_is_a_tap(self):
        p = ScrollPane(400, content_h=1000)
        p.press((50, 200)); p.motion((52, 195))
        assert p.release((52, 195)) == (50, 200)
        assert p.offset == 5           # tiny drift still applied, then kept

    def test_release_without_press_is_not_a_tap(self):
        assert ScrollPane(400).release((10, 10)) is None

    def test_set_content_height_reclamps(self):
        p = ScrollPane(400, content_h=1000)
        p.press((0, 300)); p.motion((0, 0)); p.release((0, 0))
        assert p.offset == 300
        p.set_content_height(500)
        assert p.offset == 100


class TestBadges:

    def test_subtype_wins(self):
        assert _badge_text('qualifying', 'sprint_qualifying') == 'SPRINT Q'

    def test_plain_types(self):
        assert _badge_text('race') == 'RACE'
        assert _badge_text('practice') == 'PRACTICE'

    def test_unknown_type_upper_cased(self):
        assert _badge_text('warmup') == 'WARMUP'


class TestBrowser:

    @pytest.fixture(autouse=True)
    def _pygame(self):
        pygame.init()
        from dashboard.widgets import fonts
        fonts.clear_cache()
        yield
        pygame.quit()

    def _browser(self, tmp_path):
        screen = pygame.Surface((800, 480))
        b = HistoryBrowser(screen, str(tmp_path))
        b._load_rows()
        return b, screen

    def test_rows_load_newest_first(self, tmp_path):
        _write_sessions(tmp_path, 3)
        b, _ = self._browser(tmp_path)
        assert len(b._rows) == 3
        dates = [r['date'] for r in b._rows]
        assert dates == sorted(dates, reverse=True)

    def test_row_hit_testing_respects_scroll(self, tmp_path):
        _write_sessions(tmp_path, 3)
        b, _ = self._browser(tmp_path)
        first_row_y = b.HDR_H + b.ROW_GAP + 10
        assert b._row_index_at((400, first_row_y)) == 0
        b._list_pane.offset = b.ROW_H + b.ROW_GAP
        assert b._row_index_at((400, first_row_y)) == 1

    def test_list_render_smoke(self, tmp_path):
        _write_sessions(tmp_path, 3)
        b, screen = self._browser(tmp_path)
        b._draw_list()
        from dashboard.widgets import design_system as DS
        assert any(screen.get_at((x, y))[:3] != DS.BG
                   for x, y in ((60, 100), (400, 100), (60, 30)))

    def test_empty_logs_dir_renders_empty_state(self, tmp_path):
        b, screen = self._browser(tmp_path)
        assert b._rows == []
        b._draw_list()   # must not crash

    def test_detail_opens_and_renders(self, tmp_path):
        (tmp_path / 'session_20260707_1930_race.csv').write_text(
            _session_csv([93.5, 92.1, 92.5, 92.9], session_type='race',
                         started='2026-07-07T19:30:00', rewinds={3: 1}),
            encoding='utf-8')
        b, screen = self._browser(tmp_path)
        b._open_detail(b._rows[0])
        assert b._detail is not None
        _, content = b._detail
        assert content.get_height() > 200
        b._draw_detail()

    def test_detail_back_returns_to_list(self, tmp_path):
        _write_sessions(tmp_path, 1)
        b, _ = self._browser(tmp_path)
        b._open_detail(b._rows[0])
        assert b._on_tap((20, 20)) is None      # back button: close detail
        assert b._detail is None
        assert b._on_tap((20, 20)) == 'menu'    # back again: leave browser

    def test_tap_on_row_opens_detail(self, tmp_path):
        _write_sessions(tmp_path, 2)
        b, _ = self._browser(tmp_path)
        b._on_tap((400, b.HDR_H + b.ROW_GAP + 10))
        assert b._detail is not None
        assert b._detail[0] is b._rows[0]


class TestFocusAndDebriefSections:
    """The detail view shows the driver's chosen goal + verdict, and the
    raw end-of-session debrief Q&A — not just the journal's narrative."""

    @pytest.fixture(autouse=True)
    def _pygame(self):
        pygame.init()
        from dashboard.widgets import fonts
        fonts.clear_cache()
        yield
        pygame.quit()

    def _browser(self, tmp_path):
        screen = pygame.Surface((800, 480))
        b = HistoryBrowser(screen, str(tmp_path))
        b._load_rows()
        return b, screen

    def test_focus_banner_and_debrief_appear_in_detail(self, tmp_path):
        text = (_session_csv([91.2, 90.5, 90.9, 91.4], session_type='practice')
               .replace(LAP_HEADER, f'F,clean\n{LAP_HEADER}')
               + 'D,feeling,good\nD,goal,consistency\n')
        (tmp_path / 'session_20260707_1000_practice.csv').write_text(
            text, encoding='utf-8')
        b, _ = self._browser(tmp_path)
        b._open_detail(b._rows[0])
        assert b._detail is not None
        _, content = b._detail
        assert content.get_height() > 200
        b._draw_detail()   # must not crash

        from core.session_summary import build_summary
        from sessionlog.parser import parse
        path = str(tmp_path / 'session_20260707_1000_practice.csv')
        summary = build_summary(path)
        with open(path, encoding='utf-8') as f:
            session = parse(f.read(), 'session_20260707_1000_practice.csv')
        assert summary['focus_verdict'] is not None
        assert summary['focus_verdict']['title'] == 'CLEAN LAPS'
        assert session['debrief'] == {'feeling': 'good', 'goal': 'consistency'}

    def test_no_focus_or_debrief_renders_without_those_sections(self, tmp_path):
        _write_sessions(tmp_path, 1)
        b, _ = self._browser(tmp_path)
        b._open_detail(b._rows[0])
        assert b._detail is not None
        b._draw_detail()   # must not crash with neither section present


class TestGameFilterAndDelete:

    @pytest.fixture(autouse=True)
    def _pygame(self):
        pygame.init()
        from dashboard.widgets import fonts
        fonts.clear_cache()
        yield
        pygame.quit()

    def _two_game_logs(self, tmp_path):
        (tmp_path / 'session_20260701_1000_practice.csv').write_text(
            _session_csv([91.0, 90.5, 90.9], started='2026-07-01T10:00:00'),
            encoding='utf-8')
        f1 = _session_csv([92.0, 91.5, 91.9], started='2026-07-05T10:00:00')
        (tmp_path / 'session_20260705_1000_practice.csv').write_text(
            f1.replace('S,game,f1_25', 'S,game,pcars2'), encoding='utf-8')

    def _browser(self, tmp_path):
        screen = pygame.Surface((800, 480))
        b = HistoryBrowser(screen, str(tmp_path))
        b._load_rows()
        return b

    def test_default_filter_is_most_recent_game(self, tmp_path):
        self._two_game_logs(tmp_path)
        b = self._browser(tmp_path)
        assert b._game_filter == 'pcars2'        # newest session's game
        assert all(r['game'] == 'pcars2' for r in b._rows)

    def test_all_chip_clears_the_filter(self, tmp_path):
        self._two_game_logs(tmp_path)
        b = self._browser(tmp_path)
        gid, _label, rect = b._filter_rects()[0]  # ALL chip
        assert gid is None
        b._on_tap(rect.center)
        assert b._game_filter is None
        assert len(b._rows) == 2

    def test_single_game_shows_no_filter_row(self, tmp_path):
        _write_sessions(tmp_path, 2)
        b = self._browser(tmp_path)
        assert b._filter_rects() == []
        assert b._list_top() == b.HDR_H

    def test_filter_row_shifts_list_hit_testing(self, tmp_path):
        self._two_game_logs(tmp_path)
        b = self._browser(tmp_path)
        first_row_y = b._list_top() + b.ROW_GAP + 10
        assert b._row_index_at((400, first_row_y)) == 0

    def test_delete_needs_two_taps_and_trashes(self, tmp_path):
        import os
        self._two_game_logs(tmp_path)
        b = self._browser(tmp_path)
        b._open_detail(b._rows[0])
        fname = b._detail[0]['filename']
        b._on_tap(b._delete_rect().center)       # arm
        assert b._delete_armed and b._detail is not None
        assert os.path.exists(tmp_path / fname)
        b._on_tap(b._delete_rect().center)       # confirm
        assert b._detail is None
        assert not os.path.exists(tmp_path / fname)
        assert os.path.exists(tmp_path / '.trash' / fname)
        assert all(r['filename'] != fname for r in b._all_rows)

    def test_any_other_tap_disarms_delete(self, tmp_path):
        self._two_game_logs(tmp_path)
        b = self._browser(tmp_path)
        b._open_detail(b._rows[0])
        b._on_tap(b._delete_rect().center)       # arm
        b._on_tap((400, 300))                    # tap elsewhere
        assert b._delete_armed is False
        assert b._detail is not None             # still open

    def test_list_render_with_filter_row(self, tmp_path):
        self._two_game_logs(tmp_path)
        b = self._browser(tmp_path)
        b._draw_list()   # smoke: chips + rows
