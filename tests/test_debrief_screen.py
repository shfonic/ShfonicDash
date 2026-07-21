"""Pi-side tests for core.debrief — building, appending and rendering."""
import os

import pygame
import pytest

from core.debrief import DebriefScreen, append_debrief, build_debrief

LAP_HEADER = ('H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,'
              'tyre_compound,fuel_remaining,fuel_per_lap,position,delta,invalid,rewinds')


def _session_csv(times, invalid=None):
    invalid = invalid or set()
    rows = [
        'S,version,1', 'S,started_at,2026-07-07T10:00:00',
        'S,game,f1_25', 'S,session_type,hotlap',
        'S,car_class,formula1_2026', 'S,track,Monaco', LAP_HEADER,
    ]
    for i, t in enumerate(times, start=1):
        inv = 1 if i in invalid else 0
        rows.append(f'L,{i},{t},28.0,30.0,{round(t - 58.0, 3)},,,,,,,,,,{inv},0')
    return '\n'.join(rows) + '\n'


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding='utf-8')
    return str(p)


class TestBuildDebrief:
    def test_returns_questions_and_context(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_hotlap.csv',
                      _session_csv([89.2, 88.6, 88.9, 89.4], invalid={3, 4}))
        built = build_debrief(path)
        assert built is not None
        questions, sub = built
        ids = [q["id"] for q in questions]
        assert ids[:2] == ["feeling", "goal"]
        assert "invalid_cause" in ids       # 2 invalid laps triggered it
        assert "Monaco" in sub and "4 laps" in sub

    def test_no_laps_means_no_debrief(self, tmp_path):
        path = _write(tmp_path, 'session_20260707_1000_hotlap.csv',
                      'S,version,1\nS,game,f1_25\n')
        assert build_debrief(path) is None


class TestAppendDebrief:
    def test_appends_d_rows_and_parser_reads_them(self, tmp_path):
        from sessionlog.parser import parse
        path = _write(tmp_path, 'session_20260707_1000_hotlap.csv',
                      _session_csv([89.2, 88.6]))
        assert append_debrief(path, {"feeling": "good", "goal": "pace"})
        with open(path, encoding='utf-8') as f:
            session = parse(f.read(), os.path.basename(path))
        assert session["debrief"] == {"feeling": "good", "goal": "pace"}

    def test_empty_answers_do_nothing(self, tmp_path):
        path = _write(tmp_path, 's.csv', _session_csv([89.2]))
        before = open(path).read()
        assert append_debrief(path, {}) is False
        assert open(path).read() == before


class TestDebriefOverlay:
    """The non-blocking variant used after a rotation summary."""

    @pytest.fixture(autouse=True)
    def _pygame(self):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        pygame.init()
        from dashboard.widgets import fonts
        fonts.clear_cache()
        yield
        pygame.quit()

    def _overlay(self, tmp_path):
        from core.debrief import DebriefOverlay
        path = _write(tmp_path, 'session_20260707_1000_hotlap.csv',
                      _session_csv([89.2, 88.6]))
        questions, sub = build_debrief(path)
        return path, DebriefOverlay(path, questions, sub)

    def _debrief_of(self, path):
        from sessionlog.parser import parse
        with open(path, encoding='utf-8') as f:
            return parse(f.read(), os.path.basename(path))["debrief"]

    def test_tapping_through_appends_answers(self, tmp_path):
        path, ov = self._overlay(tmp_path)
        done = False
        while not done:
            _aid, _lbl, rect = ov._view._rects[0]
            done = ov.tap(rect.center)
        d = self._debrief_of(path)
        assert d.get("feeling") and d.get("goal")

    def test_skip_keeps_earlier_answers(self, tmp_path):
        path, ov = self._overlay(tmp_path)
        ov.tap(ov._view._rects[0][2].center)          # answer feeling
        assert ov.tap(ov._view.skip_rect().center)    # skip the rest
        d = self._debrief_of(path)
        assert "feeling" in d and "goal" not in d

    def test_dead_space_tap_stays_on_question(self, tmp_path):
        path, ov = self._overlay(tmp_path)
        assert ov.tap((400, 470)) is False
        assert self._debrief_of(path) == {}

    def test_finish_with_no_answers_writes_nothing(self, tmp_path):
        path, ov = self._overlay(tmp_path)
        before = open(path).read()
        ov.finish()   # drive-away before any answer
        assert open(path).read() == before

    def test_app_chains_rotation_summary_into_debrief(self, tmp_path):
        from core.app import App
        from core.debrief import DebriefOverlay
        from core.telemetry_model import TelemetryData

        class _Src:
            def connect(self): pass
            def read(self): return TelemetryData()
            def disconnect(self): pass

        class _Mgr:
            def reset_touch(self): pass

        pygame.display.set_mode((800, 480))
        path = _write(tmp_path, 'session_20260707_1000_hotlap.csv',
                      _session_csv([89.2, 88.6]))
        app = App(_Src(), debrief_enabled=True)
        app._summary_view = object()      # the rotation summary (no .tap)
        app._debrief_after = path
        app._dismiss_summary(_Mgr())      # user taps the summary away
        assert isinstance(app._summary_view, DebriefOverlay)

        # …but a drive-away dismissal must NOT chain into questions
        app2 = App(_Src(), debrief_enabled=True)
        app2._summary_view = object()
        app2._debrief_after = None        # cleared by the drive-away branch
        app2._dismiss_summary(_Mgr())
        assert app2._summary_view is None


class TestDebriefScreen:
    @pytest.fixture(autouse=True)
    def _pygame(self):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        pygame.init()
        from dashboard.widgets import fonts
        fonts.clear_cache()
        yield
        pygame.quit()

    def _screen(self, qid="goal"):
        from sessionlog.debrief import QUESTIONS
        return DebriefScreen(QUESTIONS[qid], 1, 3, sub="Monaco · Hotlap")

    def test_renders_all_question_kinds(self):
        from sessionlog.debrief import QUESTIONS
        surface = pygame.Surface((800, 480), depth=24)
        for qid in QUESTIONS:
            DebriefScreen(QUESTIONS[qid], 1, 3).render(surface)

    def test_hit_maps_taps_to_answer_ids(self):
        view = self._screen()
        aid, _label, rect = view._rects[0]
        assert view.hit(rect.center) == aid

    def test_skip_and_miss(self):
        view = self._screen()
        assert view.hit(view.skip_rect().center) == "skip"
        assert view.hit((400, 470)) is None

    def test_option_buttons_do_not_overlap(self):
        for qid in ("feeling", "goal"):
            rects = [r for _, _, r in self._screen(qid)._rects]
            for i, a in enumerate(rects):
                for b in rects[i + 1:]:
                    assert not a.colliderect(b)
