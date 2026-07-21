"""Tests for core.web_app — the Pi-served browser companion renderers.

Covers the cookie/token auth helpers and that the three pages render valid,
well-formed HTML over a real session CSV (the shared sample fixture), driven
entirely through the sessionlog engine + records index (same source the Pi's
own summary screens and the Pythonista companion read).
"""
import os
import shutil
from html.parser import HTMLParser

import pytest

from core import web_app

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "session_20260629_0000_qualifying_mock.csv")


@pytest.fixture
def logs_dir(tmp_path):
    """A logs directory containing the sample session (named to match the
    server's session_*.csv pattern)."""
    dest = tmp_path / "session_20260629_0000_qualifying.csv"
    shutil.copy(FIXTURE, dest)
    return str(tmp_path), dest.name


class _WellFormed(HTMLParser):
    VOID = {"meta", "link", "br", "hr", "img", "input", "area", "base",
            "col", "embed", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass
        else:
            self.errors.append(f"stray </{tag}>")


def _assert_well_formed(html):
    assert html.startswith("<!doctype html>")
    assert "</html>" in html
    p = _WellFormed()
    p.feed(html)
    assert not p.errors, p.errors
    assert [t for t in p.stack if t != "html"] == []


class TestAuthHelpers:
    TOKEN = "A1B2C3D4"

    def test_session_cookie_is_deterministic(self):
        assert web_app.session_cookie(self.TOKEN) == web_app.session_cookie(self.TOKEN)

    def test_cookie_valid_roundtrip(self):
        cookie = web_app.session_cookie(self.TOKEN)
        assert web_app.cookie_valid(cookie, self.TOKEN) is True

    def test_cookie_rejects_wrong_token_and_empty(self):
        cookie = web_app.session_cookie(self.TOKEN)
        assert web_app.cookie_valid(cookie, "OTHER0000") is False
        assert web_app.cookie_valid("", self.TOKEN) is False
        assert web_app.cookie_valid(cookie, "") is False

    def test_cookie_is_not_the_raw_token(self):
        # The cookie must never expose the pairing token directly.
        assert self.TOKEN not in web_app.session_cookie(self.TOKEN)

    def test_key_valid_is_case_insensitive(self):
        assert web_app.key_valid("a1b2c3d4", self.TOKEN) is True
        assert web_app.key_valid("nope", self.TOKEN) is False
        assert web_app.key_valid("", self.TOKEN) is False


class TestShell:
    def test_shell_is_well_formed_and_links_css(self):
        html = web_app.render_shell("Hi", "<div class=card>body</div>", "home")
        _assert_well_formed(html)
        assert "/app/app.css" in html
        assert "Shfonic Dash" in html                # logo alt / brand

    def test_shell_escapes_title(self):
        html = web_app.render_shell("<b>hi</b>", "x")
        assert "<title><b>hi</b>" not in html      # raw title not injected
        assert "&lt;b&gt;hi&lt;/b&gt;" in html      # escaped instead


class TestPages:
    def test_home_renders(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_home(d)
        _assert_well_formed(html)
        assert "SESSIONS" in html and "TROPHIES" in html

    def test_sessions_list_renders_the_session(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_sessions(d)
        _assert_well_formed(html)
        assert "srow" in html                       # at least one row
        assert "/app/session/" in html              # links to detail

    def test_session_detail_renders(self, logs_dir):
        d, fname = logs_dir
        html = web_app.render_session(d, fname)
        _assert_well_formed(html)
        assert "<th>Lap</th>" in html                 # lap table header
        assert "BEST" in html                        # header fastest line

    def test_missing_session_is_friendly(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_session(d, "session_20200101_0000_race.csv")
        _assert_well_formed(html)
        assert "no longer exists" in html.lower()

    def test_empty_logs_dir_is_graceful(self, tmp_path):
        html = web_app.render_sessions(str(tmp_path))
        _assert_well_formed(html)
        assert "No sessions" in html


class TestBrowse:
    def test_browse_root_lists_games(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_browse(d, {"g": None, "c": None, "t": None, "s": None})
        _assert_well_formed(html)
        assert "Games" in html
        assert "drow" in html or "No sessions" in html

    def test_browse_drills_into_a_game(self, logs_dir):
        d, _ = logs_dir
        rows = web_app._load_rows(d)
        game = rows[0].get("game_name") or rows[0].get("game")
        html = web_app.render_browse(d, {"g": game, "c": None, "t": None, "s": None})
        _assert_well_formed(html)
        # breadcrumb back to All, and the next level (car classes).
        assert "/app/browse" in html
        assert "Car classes" in html or "Sessions" in html

    def test_browse_deepest_level_lists_sessions(self, logs_dir):
        d, _ = logs_dir
        r = web_app._load_rows(d)[0]
        sel = {"g": r.get("game_name") or r.get("game"),
               "c": r.get("car_class_name") or r.get("car_class"),
               "t": r.get("track"), "s": r.get("session_type")}
        html = web_app.render_browse(d, sel)
        _assert_well_formed(html)
        assert "srow" in html                        # actual session rows


class TestHubPages:
    def test_home_is_driver_hub(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_home(d)
        _assert_well_formed(html)
        assert "class=av" in html                    # avatar SVG
        assert "OVERALL" in html
        assert "SESSIONS" in html

    def test_settings_has_theme_and_size(self):
        html = web_app.render_settings()
        _assert_well_formed(html)
        assert "opt-theme" in html and "opt-fs" in html
        assert "shfonic_theme" in html                # persists to localStorage

    def test_driver_page_renders(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_driver(d)
        _assert_well_formed(html)
        assert "class=av" in html

    def test_favourites_empty_is_graceful(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_favourites(d)
        _assert_well_formed(html)
        assert "Favourites" in html

    def test_sessions_has_subtabs(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_sessions(d)
        assert "subtabs" in html
        assert "/app/browse" in html and "/app/favourites" in html

    def test_trophies_renders(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_trophies(d)
        _assert_well_formed(html)
        assert "Trophies" in html

    def test_trophy_detail_unearned_is_howto(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_trophy(d, "century")
        _assert_well_formed(html)
        assert "How to earn" in html
        assert "Not yet earned" in html
        assert "/app/trophies" in html                # back link

    def test_trophy_detail_lists_earning_sessions(self, logs_dir, monkeypatch):
        # Force one badge earned by this session so the sessions list renders.
        d, fname = logs_dir
        import datetime
        from sessionlog import achievements
        state = {"century": {"count": 3, "tier": "silver",
                             "sessions": [(fname, datetime.datetime(2026, 6, 29))]}}
        monkeypatch.setattr(achievements, "evaluate", lambda rows: state)
        html = web_app.render_trophy(d, "century")
        _assert_well_formed(html)
        assert "Sessions" in html
        assert "/app/session/" in html                # tappable earning session
        assert "Earned" in html and "Silver" in html

    def test_trophy_detail_unknown_is_friendly(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_trophy(d, "no_such_badge")
        _assert_well_formed(html)
        assert "Unknown trophy" in html

    def test_browse_leaf_has_driver_profile(self, logs_dir):
        d, _ = logs_dir
        r = web_app._load_rows(d)[0]
        sel = {"g": r.get("game_name") or r.get("game"),
               "c": r.get("car_class_name") or r.get("car_class"),
               "t": r.get("track"), "s": r.get("session_type")}
        html = web_app.render_browse(d, sel)
        _assert_well_formed(html)
        assert "DRIVER PROFILE" in html
        assert "Personal best" in html

    def test_journal_renders(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_journal(d)
        _assert_well_formed(html)
        assert "Journal" in html

    def test_status_json(self, logs_dir):
        import json
        d, _ = logs_dir
        s = json.loads(web_app.render_status(d))
        assert s["count"] >= 1 and s["latest"].endswith(".csv")

    def test_detail_has_share(self, logs_dir):
        d, fname = logs_dir
        html = web_app.render_session(d, fname)
        assert "sharebtn" in html
        assert "AI ANALYSIS GUIDANCE" in _share_probe(d, fname)   # canonical brief
        # the detail links to the dedicated share screen (no inline clipboard JS,
        # which fails over plain http)
        assert f"/app/session/{fname}/share" in html

    def test_share_screen_has_textarea_and_copy(self, logs_dir):
        d, fname = logs_dir
        html = web_app.render_share(d, fname)
        _assert_well_formed(html)
        assert "sharearea" in html                    # selectable textarea
        assert "copybtn" in html and "execCommand" in html   # http-safe copy
        assert "AI ANALYSIS GUIDANCE" in html         # the canonical brief itself


def _share_probe(d, fname):
    from core.session_summary import build_summary
    from sessionlog.parser import parse
    import os
    summary = build_summary(os.path.join(d, fname))
    with open(os.path.join(d, fname)) as f:
        session = parse(f.read(), fname)
    return web_app._share_text(summary, session, summary["fmt"])


class TestEditableDriver:
    def test_driver_has_form(self, logs_dir):
        d, _ = logs_dir
        html = web_app.render_driver(d)
        assert 'action="/app/driver/save"' in html
        assert 'name=name' in html                    # editable name field
        assert "swatches" in html                     # helmet colour pickers

    def test_avatar_uses_real_masks(self):
        html = web_app._avatar_html(
            {"avatar_kind": "helmet",
             "avatar_helmet": {"base": "red", "visor": "blue",
                               "accent": "white", "pattern": "twin"}})
        assert "/app/img/helmet.png" in html          # same PNG the Pi uses
        assert "helmet_visor.png" in html


class TestTracks:
    def test_tracks_list(self, tmp_path):
        import json
        (tmp_path / "f1_spa.json").write_text(json.dumps({
            "format_version": 1, "game": "f1_25", "track": "Spa",
            "left_edge": [[0, 0]], "sections": [{"turn": "1"}],
            "lines": {"formula1": {"racing_line": [[0, 0]]}}}))
        html = web_app.render_tracks(str(tmp_path))
        _assert_well_formed(html)
        assert "Spa" in html
        assert "/app/track/f1_spa.json/map" in html

    def test_track_viewer_bakes_data(self, tmp_path):
        import json
        (tmp_path / "f1_spa.json").write_text(json.dumps({
            "format_version": 1, "track": "Spa", "left_edge": [[0, 0]]}))
        html = web_app.render_track_viewer(str(tmp_path), "f1_spa.json")
        assert html is not None
        assert "SHFONIC.load" in html and "sfSave" in html

    def test_track_viewer_rejects_bad_name(self, tmp_path):
        assert web_app.render_track_viewer(str(tmp_path), "../etc/passwd") is None
        assert web_app.render_track_viewer(str(tmp_path), "missing.json") is None


class TestLineViewer:
    def test_returns_none_without_racing_line(self, logs_dir):
        # The sample session has no track map, so no line data.
        d, fname = logs_dir
        assert web_app.render_line_viewer(d, fname) is None

    def test_returns_none_for_missing_file(self, logs_dir):
        d, _ = logs_dir
        assert web_app.render_line_viewer(d, "session_20200101_0000_race.csv") is None
