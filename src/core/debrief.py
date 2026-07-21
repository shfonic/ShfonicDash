"""Post-session driver debrief — 2–3 tap questions after the summary.

The race-engineer exchange from the ideas list: when a session closes
(exit to menu) and the summary has been dismissed, ask how it went —
always feeling + goal, plus at most one question triggered by what
actually happened (new PB / invalid laps / rewinds / theoretical gap),
selected by sessionlog.debrief. Answers are appended to the closed
session CSV as `D` rows, so the companion and future analysis read them
with no extra transport.

Skippable at any point (TAP HERE TO SKIP keeps any answers already
given); gated by the `debrief_enabled` setting (DISPLAY tab, default on).
"""
import csv
import logging
import os

import pygame

from core.flip import flip_pos, flip_surface

log = logging.getLogger("debrief")

_PAD = 28


def build_debrief(csv_path: str) -> tuple[list, str] | None:
    """Questions + context sub-line for a just-closed session CSV.

    Returns None when the session isn't worth debriefing (no laps,
    unreadable) or no questions apply.
    """
    from sessionlog import records
    from sessionlog.debrief import select_questions
    from sessionlog.grading import session_facts
    from sessionlog.parser import parse, session_label

    try:
        with open(csv_path, encoding="utf-8") as f:
            session = parse(f.read(), os.path.basename(csv_path))
    except (OSError, ValueError) as e:
        log.warning(f"debrief: could not parse {csv_path}: {e}")
        return None
    if not session.get("laps"):
        return None

    prior = None
    try:
        records.set_cache_dir(os.path.dirname(os.path.abspath(csv_path)))
        prior_rec = records.prior_best(
            session.get("game"), session.get("car_class"),
            session.get("track"), session.get("session_type"),
            session.get("date"), session.get("filename") or "")
        prior = prior_rec.get("best_lap_time") if prior_rec else None
    except Exception:
        pass   # PB question just won't trigger

    # The corner that dominated THIS session's track-limit warnings, so the
    # reaction question can name it ("Turn 8 kept catching you out"). Needs
    # the track map to resolve distances → sections; best-effort, never fatal.
    location = None
    try:
        from sessionlog.pace import track_limit_counts
        from sessionlog.trackmap import find_map, set_tracks_dir
        logs_dir = os.path.dirname(os.path.abspath(csv_path))
        set_tracks_dir(os.path.join(logs_dir, "..", "tracks"))
        track_map = find_map(session.get("game"), session.get("track"))
        counts = track_limit_counts(session.get("events") or [], track_map)
        if counts:
            label, n = max(counts.items(), key=lambda kv: kv[1])
            if n >= 2:
                location = label
    except Exception:
        pass   # no map / no warnings → generic reaction question

    questions = select_questions(session_facts(session), prior,
                                 focus_id=(session.get("focus") or "").strip(),
                                 location=location)
    if not questions:
        return None
    label = (session_label(session) or "session").replace("_", " ").title()
    bits = [b for b in (session.get("track"), label,
                        f"{len(session['laps'])} laps just now") if b]
    return questions, "  ·  ".join(bits)


def append_debrief(csv_path: str, answers: dict) -> bool:
    """Append D rows to a closed session CSV and refresh its index row.

    The records index re-scans files whose size/mtime changed, so the
    next sync() heals the row automatically; we nudge it here so the
    change is visible immediately.
    """
    if not answers:
        return False
    try:
        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            for qid, aid in answers.items():
                writer.writerow(["D", qid, aid])
    except OSError:
        log.exception(f"debrief: could not append to {csv_path}")
        return False
    try:
        from sessionlog import records
        records.set_cache_dir(os.path.dirname(os.path.abspath(csv_path)))
        records.sync()
    except Exception:
        pass   # next sync heals it
    return True


# ── UI ─────────────────────────────────────────────────────────────────────

_FACE_COLOURS = ("GREEN", "CYAN", "TEXT3", "AMBER", "PURPLE")


def _draw_face(screen, idx: int, cx: int, cy: int):
    """Drawn mood faces for the feeling question (no emoji on the Pi)."""
    from dashboard.widgets import design_system as DS
    c = getattr(DS, _FACE_COLOURS[idx % len(_FACE_COLOURS)])
    pygame.draw.circle(screen, c, (cx, cy), 18, 2)
    if idx == 4:   # tired: half-closed eyes
        pygame.draw.line(screen, c, (cx - 9, cy - 5), (cx - 3, cy - 5), 2)
        pygame.draw.line(screen, c, (cx + 3, cy - 5), (cx + 9, cy - 5), 2)
    else:
        pygame.draw.circle(screen, c, (cx - 6, cy - 5), 2)
        pygame.draw.circle(screen, c, (cx + 6, cy - 5), 2)
    if idx == 0:
        pygame.draw.arc(screen, c, pygame.Rect(cx - 9, cy - 4, 18, 12), 3.5, 6.0, 2)
    elif idx == 1:
        pygame.draw.arc(screen, c, pygame.Rect(cx - 7, cy - 2, 14, 9), 3.5, 6.0, 2)
    elif idx == 3:
        pygame.draw.arc(screen, c, pygame.Rect(cx - 7, cy + 4, 14, 9), 0.5, 2.7, 2)
    else:
        pygame.draw.line(screen, c, (cx - 7, cy + 7), (cx + 7, cy + 7), 2)


class DebriefScreen:
    """Renders one question and hit-tests its option buttons."""

    def __init__(self, question: dict, step: int, total: int,
                 sub: str = "", width: int = 800, height: int = 480):
        from dashboard.widgets.fonts import load_ui
        self._q = question
        self._step, self._total = step, total
        self._sub = sub
        self._w, self._h = width, height
        self._f_cap = load_ui(12)
        self._f_q   = load_ui(24)
        self._f_opt = load_ui(17)
        self._f_sub = load_ui(13)
        self._rects = self._layout()

    def _layout(self) -> list:
        n = len(self._q["options"])
        cols = 5 if self._q["id"] == "feeling" else 3
        rows = -(-n // cols)
        gap = 14
        bw = (self._w - 2 * _PAD - gap * (cols - 1)) // cols
        bh = 150 if rows == 1 else 120
        y0 = 170 if rows == 1 else 150
        out = []
        for i, (aid, label) in enumerate(self._q["options"]):
            r, c = divmod(i, cols)
            out.append((aid, label,
                        pygame.Rect(_PAD + c * (bw + gap),
                                    y0 + r * (bh + gap), bw, bh)))
        return out

    def skip_rect(self) -> pygame.Rect:
        return pygame.Rect(self._w - 240, 8, 232, 40)

    def hit(self, pos) -> str | None:
        """Answer id at pos, "skip", or None."""
        if self.skip_rect().collidepoint(pos):
            return "skip"
        for aid, _label, rect in self._rects:
            if rect.collidepoint(pos):
                return aid
        return None

    def render(self, screen: pygame.Surface) -> None:
        from dashboard.widgets import design_system as DS
        screen.fill(DS.BG)
        cap = self._f_cap.render("DRIVER DEBRIEF", True, DS.TEXT3)
        screen.blit(cap, (_PAD, 20))
        stp = self._f_cap.render(f"{self._step} OF {self._total}", True, DS.on_panel(DS.CYAN))
        screen.blit(stp, (_PAD + cap.get_width() + 16, 20))
        skip = self._f_cap.render("TAP HERE TO SKIP", True, DS.TEXT3)
        screen.blit(skip, skip.get_rect(topright=(self._w - _PAD, 20)))

        q = self._f_q.render(self._q["text"], True, DS.TEXT)
        screen.blit(q, (_PAD, 64))
        if self._sub:
            s = self._f_sub.render(self._sub, True, DS.TEXT3)
            screen.blit(s, (_PAD, 64 + q.get_height() + 6))

        is_feeling = self._q["id"] == "feeling"
        for i, (aid, label, rect) in enumerate(self._rects):
            pygame.draw.rect(screen, DS.PANEL, rect, border_radius=12)
            pygame.draw.rect(screen, DS.BORDER, rect, width=1, border_radius=12)
            t = self._f_opt.render(label.upper(), True, DS.TEXT)
            if is_feeling:
                _draw_face(screen, i, rect.centerx, rect.y + 44)
                screen.blit(t, t.get_rect(centerx=rect.centerx, y=rect.y + 78))
            else:
                screen.blit(t, t.get_rect(center=rect.center))


class DebriefOverlay:
    """Hosts the debrief in App.run()'s modal slot after a rotated-away
    session's summary is dismissed (in-game session switches — the only
    hotlap end that never reaches the menu). Unlike the blocking
    exit-to-menu flow, telemetry keeps flowing underneath: the logger
    ticks for the new session while the driver answers, and driving away
    abandons the questions (keeping answers already given).
    """

    def __init__(self, csv_path: str, questions: list, sub: str,
                 width: int = 800, height: int = 480):
        self._path = csv_path
        self._questions = questions
        self._sub = sub
        self._answers: dict = {}
        self._idx = 0
        self._w, self._h = width, height
        self._view = self._make_view()

    def _make_view(self) -> DebriefScreen:
        return DebriefScreen(self._questions[self._idx], self._idx + 1,
                             len(self._questions),
                             self._sub if self._idx == 0 else "",
                             self._w, self._h)

    def render(self, screen: pygame.Surface) -> None:
        self._view.render(screen)

    def tap(self, pos) -> bool:
        """Handle a tap; returns True when the debrief is finished."""
        hit = self._view.hit(pos)
        if hit == "skip":
            self.finish()
            return True
        if hit is None:
            return False   # dead space — stay on this question
        self._answers[self._questions[self._idx]["id"]] = hit
        self._idx += 1
        if self._idx >= len(self._questions):
            self.finish()
            return True
        self._view = self._make_view()
        return False

    def finish(self) -> None:
        """Write whatever was answered (possibly nothing)."""
        if self._answers:
            append_debrief(self._path, self._answers)
            self._answers = {}


def run_debrief_screen(screen: pygame.Surface, questions: list, sub: str,
                       flip: bool = False, fps: int = 30) -> dict:
    """Blocking debrief flow. Returns {question_id: answer_id} — possibly
    partial (skip keeps earlier answers) or empty."""
    answers: dict = {}
    clock = pygame.time.Clock()
    total = len(questions)
    for step, question in enumerate(questions, start=1):
        view = DebriefScreen(question, step, total,
                             sub if step == 1 else "")
        answered = False
        while not answered:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return answers
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return answers
                if event.type == pygame.MOUSEBUTTONUP:
                    hit = view.hit(flip_pos(event.pos, flip))
                    if hit == "skip":
                        return answers
                    if hit is not None:
                        answers[question["id"]] = hit
                        answered = True
            view.render(screen)
            flip_surface(screen, flip)
            pygame.display.flip()
            clock.tick(fps)
    return answers
