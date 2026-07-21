"""Tests for the Pi trophies gallery and the history browser's
long-title ellipsis."""
import os

import pygame
import pytest

from core.history_browser import _ellipsize
from core.trophies_browser import TrophiesBrowser


@pytest.fixture(autouse=True)
def _pygame():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    from dashboard.widgets import fonts
    fonts.clear_cache()
    yield
    pygame.quit()


def _session_csv(n_laps=8):
    rows = ["S,version,1", "S,game,f1_25", "S,session_type,practice",
            "S,car_class,formula1", "S,driver_name,HAWES",
            "S,track,Silverstone", "S,started_at,2026-07-01T19:00:00",
            "H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,"
            "tyre_compound,fuel_remaining,fuel_per_lap,position,delta,"
            "invalid,rewinds"]
    for i in range(1, n_laps + 1):
        t = 90.0 + (i % 3) * 0.2
        rows.append(f"L,{i},{t},28.0,30.0,{t - 58.0:.3f},,,,,,,,,,0,0")
    return "\n".join(rows) + "\n"


def _browser(tmp_path, with_history=True):
    logs = tmp_path / "logs"
    logs.mkdir()
    if with_history:
        (logs / "session_20260701_1900_practice.csv").write_text(
            _session_csv())
    screen = pygame.Surface((800, 480))
    b = TrophiesBrowser(screen, str(logs))
    b._load()
    return b


class TestGallery:
    def test_all_badges_listed_even_with_no_history(self, tmp_path):
        from sessionlog.achievements import BADGES, CATEGORIES
        b = _browser(tmp_path, with_history=False)
        badges = [e for e in b._entries if e[0] == "badge"]
        sections = [e for e in b._entries if e[0] == "section"]
        assert len(badges) == len(BADGES)
        assert len(sections) == len(CATEGORIES)
        assert b._earned_n == 0

    def test_history_earns_badges(self, tmp_path):
        b = _browser(tmp_path)
        assert b._earned_n >= 1          # 8 valid laps = Clean Sweep
        earned = [e for e in b._entries
                  if e[0] == "badge" and e[2] is not None]
        assert any(e[1]["id"] == "clean_sweep" for e in earned)

    def test_draw_smoke(self, tmp_path):
        from dashboard.widgets import design_system as DS
        b = _browser(tmp_path)
        b._draw()
        assert any(b._screen.get_at((x, y))[:3] != DS.BG
                   for x, y in ((30, 30), (60, 100), (400, 200)))

    def _tap_badge(self, b, predicate):
        """Tap the first badge row whose (bdef, state) matches predicate."""
        y = b.HDR_H + b.ROW_GAP - b._pane.offset
        for entry in b._entries:
            if entry[0] == "section":
                y += b.SEC_H
                continue
            if predicate(entry[1], entry[2]):
                b._on_tap((400, y + b.ROW_H // 2))
                return entry[1]
            y += b.ROW_H + b.ROW_GAP
        return None

    def test_tap_earned_badge_opens_detail_with_sessions(self, tmp_path):
        b = _browser(tmp_path)
        bdef = self._tap_badge(
            b, lambda d, s: s is not None and s.get("sessions"))
        assert bdef is not None
        assert b._detail is not None and b._detail[0]["id"] == bdef["id"]
        # the detail lists at least one tappable session row
        assert any(it["kind"] == "sess" for it in b._detail_items)

    def test_tap_session_row_opens_it(self, tmp_path, monkeypatch):
        b = _browser(tmp_path)
        opened = []
        monkeypatch.setattr(b, "_open_session",
                            lambda fn: opened.append(fn) or None)
        self._tap_badge(b, lambda d, s: s is not None and s.get("sessions"))
        # Walk the detail geometry to the first session row and tap it.
        y = b.HDR_H + b.ROW_GAP - b._detail_pane.offset
        for it in b._detail_items:
            if it["kind"] == "sess":
                assert b._on_detail_tap((400, y + b.ROW_H // 2)) is None
                break
            y += it["h"]
        assert opened == ["session_20260701_1900_practice.csv"]

    def test_tap_unearned_badge_opens_howto(self, tmp_path):
        b = _browser(tmp_path, with_history=False)
        bdef = self._tap_badge(b, lambda d, s: s is None)
        assert bdef is not None
        assert b._detail is not None and b._detail[1] is None
        # a how-to card, no session rows
        assert any(it["kind"] == "howto" for it in b._detail_items)
        assert not any(it["kind"] == "sess" for it in b._detail_items)

    def test_detail_back_returns_to_gallery(self, tmp_path):
        b = _browser(tmp_path)
        self._tap_badge(b, lambda d, s: True)
        assert b._detail is not None
        assert b._on_detail_tap(b._back_rect().center) is None
        assert b._detail is None

    def test_back_pill(self, tmp_path):
        b = _browser(tmp_path, with_history=False)
        assert b._on_tap(b._back_rect().center) == "menu"


class TestDirectDetailBack:
    """Opened straight into a detail (trophies / milestone panel), BACK
    exits to the caller instead of revealing the history list."""

    def _history(self, tmp_path, direct):
        from core.history_browser import HistoryBrowser
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "session_20260701_1900_practice.csv").write_text(
            _session_csv())
        h = HistoryBrowser(pygame.Surface((800, 480)), str(logs))
        h._load_rows()
        h._open_detail(h._all_rows[0])
        h._direct = direct
        return h

    def test_direct_back_exits(self, tmp_path):
        h = self._history(tmp_path, direct=True)
        assert h._on_tap(h._back_rect().center) == "menu"

    def test_list_entry_back_shows_list(self, tmp_path):
        h = self._history(tmp_path, direct=False)
        assert h._on_tap(h._back_rect().center) is None
        assert h._detail is None


class TestEllipsize:
    def test_short_text_unchanged(self):
        from dashboard.widgets.fonts import load_ui
        f = load_ui(16)
        assert _ellipsize(f, "Monza", 400) == "Monza"

    def test_long_text_truncates_within_width(self):
        from dashboard.widgets.fonts import load_ui
        f = load_ui(16)
        long = ("Barcelona (Circuit de Barcelona-Catalunya) · "
                "McLaren Racing McLaren 570S GT4")
        out = _ellipsize(f, long, 300)
        assert out.endswith("…")
        assert f.size(out)[0] <= 300


class TestMenuPillRow:
    def test_three_pills_fit_without_overlap(self):
        pygame.display.set_mode((800, 480))
        from core.game_menu import GameMenu
        m = GameMenu(pygame.display.get_surface(), {})
        rects = [m._trophies_rect(), m._history_rect(), m._settings_rect()]
        for r in rects:
            assert 0 <= r.left and r.right <= 800
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                assert not a.colliderect(b)
