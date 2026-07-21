"""Session history browser — browse past sessions from the main menu.

A History button on the game menu opens a touch-scrollable list of every
session in logs/ (via the sessionlog records index, which heals itself —
sessions copied back from the companion appear automatically). Tapping a
row opens a detail view: the Phase 2 summary blocks plus the full lap
table with the companion's flag colours, standings for multi-car
sessions, and all Race Engineer Notes.

Rows come from records.all_sessions(), which orders by filename
(descending) — filenames embed the session date, so copied-back files
with fresh mtimes still sort by when they were driven.
"""
import logging
import os

import pygame

from core.flip import flip_pos, flip_surface
from sessionlog import circuits

log = logging.getLogger("history")


def _row_track(row) -> str:
    """The circuit's real name for a session row, falling back to the bare
    telemetry name; safe when game/track are missing."""
    return circuits.display_name(row.get("game"), row.get("track"))

# Companion-app badge language (theme.py BADGE_COLOR / BADGE_TEXT)
_BADGE_TEXT = {
    "race":              "RACE",
    "qualifying":        "QUALI",
    "practice":          "PRACTICE",
    "hotlap":            "HOTLAP",
    "sprint_qualifying": "SPRINT Q",
}

_TAP_SLOP = 12          # finger movement below this is a tap, not a drag

# Short chip labels for the game filter row (fallback: game id upper-cased)
_GAME_ABBR = {
    "f1_25":  "F1 25",
    "pcars2": "PC2",
    "fh6":    "FORZA H",
    "fm":     "FORZA M",
    "acc":    "ACC",
    "ac":     "AC",
}


def _csv_float(value) -> float | None:
    """Raw CSV cell ('' / '92.104' / None) → float or None."""
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _badge_color(session_type: str, subtype: str = ""):
    from dashboard.widgets import design_system as DS
    colors = {
        "race":       DS.RED,
        "qualifying": DS.PURPLE,
        "practice":   DS.AMBER,
        "hotlap":     DS.GREEN,
    }
    return colors.get(session_type, DS.TEXT3)


def _badge_text(session_type: str, subtype: str = "") -> str:
    return _BADGE_TEXT.get(subtype or session_type,
                           (subtype or session_type or "?").upper())


_FLAG_COLORS = None


def _flag_color(flag: str | None):
    """parser lap/sector flag string → design-system colour (None = TEXT)."""
    global _FLAG_COLORS
    from dashboard.widgets import design_system as DS
    if _FLAG_COLORS is None:
        _FLAG_COLORS = {
            "magenta": DS.MAGENTA,   # session best
            "purple":  DS.PURPLE,    # PB at the time
            "green":   DS.GREEN,     # within 0.30s of best
            "yellow":  DS.AMBER,     # within 1.00s of best
            "red":     DS.RED,       # invalid
        }
    # on_panel keeps these bright on dark themes and darkens them just enough
    # to read on a light panel (applied at return, not cached, so it tracks
    # the live theme).
    return DS.on_panel(_FLAG_COLORS.get(flag or "", DS.TEXT))


def _ellipsize(font, text: str, max_w: int) -> str:
    """Truncate text with a trailing ellipsis so it renders within max_w
    (long ACC track names overflowed into the lap-time column and the
    DELETE button, observed 2026-07-08)."""
    if max_w <= 0 or font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


class ScrollPane:
    """Vertical drag-to-scroll state for a touch viewport.

    Feed it the raw pointer events; release() reports a tap (with its
    position) only when the finger barely moved, so list rows can tell
    taps from scroll gestures.
    """

    def __init__(self, viewport_h: int, content_h: int = 0):
        self._viewport_h = viewport_h
        self._content_h  = content_h
        self.offset      = 0
        self._down_pos   = None
        self._last_y     = 0
        self._moved      = 0.0

    def set_content_height(self, h: int) -> None:
        self._content_h = h
        self._clamp()

    def press(self, pos) -> None:
        self._down_pos = pos
        self._last_y   = pos[1]
        self._moved    = 0.0

    def motion(self, pos) -> None:
        if self._down_pos is None:
            return
        dy = pos[1] - self._last_y
        self._last_y = pos[1]
        self._moved = max(self._moved,
                          abs(pos[0] - self._down_pos[0]),
                          abs(pos[1] - self._down_pos[1]))
        self.offset -= dy
        self._clamp()

    def release(self, pos) -> tuple | None:
        """Returns the tap position, or None if this was a drag."""
        if self._down_pos is None:
            return None
        was_tap = self._moved <= _TAP_SLOP
        tap_pos = self._down_pos
        self._down_pos = None
        return tap_pos if was_tap else None

    def _clamp(self) -> None:
        max_off = max(0, self._content_h - self._viewport_h)
        self.offset = max(0, min(self.offset, max_off))


class HistoryBrowser:
    W, H    = 800, 480
    HDR_H   = 56
    FILTER_H = 44          # game filter chip row (shown with 2+ games)
    PAD     = 28
    ROW_H   = 64
    ROW_GAP = 8

    def __init__(self, screen: pygame.Surface, logs_dir: str, flip: bool = False):
        from dashboard.widgets.fonts import load_ui
        self._screen   = screen
        self._logs_dir = logs_dir
        self._flip     = flip
        self._f_hdr    = load_ui(16)
        self._f_row    = load_ui(16)
        self._f_sub    = load_ui(12)
        self._f_badge  = load_ui(12)
        self._f_best   = load_ui(18)
        self._f_cell   = load_ui(14)
        self._f_label  = load_ui(12)
        self._all_rows = []           # every indexed session
        self._rows     = []           # after the game filter
        self._games    = []           # ordered distinct (game, game_name)
        self._game_filter = None      # game id, or None = all
        self._filter_init = False     # first load picks the newest game
        self._delete_armed = False    # detail DELETE tapped once
        self._direct      = False     # opened straight into a detail
        self._list_pane   = ScrollPane(self.H - self.HDR_H)
        self._detail_pane = ScrollPane(self.H - self.HDR_H)
        self._detail      = None      # (row, content Surface) when open

    # ── public ───────────────────────────────────────────────────────────

    def run(self, open_file: str | None = None) -> str:
        """Blocking browse loop. Returns "menu" (back) or "quit".

        open_file — a logs/ filename to open straight into its detail view
        (used by the menu's milestone panel); back returns to the list.
        """
        self._load_rows()
        # Opened straight into a detail (trophies / milestone panel):
        # the caller is the previous screen, not our list — back from
        # the detail must exit rather than reveal a list the user never
        # came from.
        self._direct = False
        if open_file:
            row = next((r for r in self._all_rows
                        if r.get("filename") == open_file), None)
            if row is not None:
                self._open_detail(row)
                self._direct = True
        clock = pygame.time.Clock()
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "quit"
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if self._detail is not None and not self._direct:
                        self._detail = None
                        self._delete_armed = False
                    else:
                        return "menu"
                pane = self._detail_pane if self._detail else self._list_pane
                if event.type == pygame.MOUSEBUTTONDOWN:
                    pane.press(flip_pos(event.pos, self._flip))
                elif event.type == pygame.MOUSEMOTION:
                    pane.motion(flip_pos(event.pos, self._flip))
                elif event.type == pygame.MOUSEBUTTONUP:
                    tap = pane.release(flip_pos(event.pos, self._flip))
                    if tap is not None:
                        action = self._on_tap(tap)
                        if action is not None:
                            return action

            if self._detail is not None:
                self._draw_detail()
            else:
                self._draw_list()
            flip_surface(self._screen, self._flip)
            pygame.display.flip()
            clock.tick(30)

    # ── data ─────────────────────────────────────────────────────────────

    def _load_rows(self) -> None:
        self._all_rows = []
        if self._logs_dir and os.path.isdir(self._logs_dir):
            try:
                from sessionlog import records
                records.set_cache_dir(self._logs_dir)
                records.sync()
                self._all_rows = records.all_sessions()
            except Exception as e:
                log.warning(f"history: records unavailable: {e}")
        games = {}
        for r in self._all_rows:
            g = r.get("game")
            if g and g not in games:
                games[g] = r.get("game_name") or g
        self._games = list(games.items())
        if self._game_filter is not None and self._game_filter not in games:
            self._game_filter = None
        if not self._filter_init:
            # Open on the game you drove most recently — one tap on ALL
            # (or another chip) widens from there.
            self._filter_init = True
            if self._all_rows:
                self._game_filter = self._all_rows[0].get("game")
        self._apply_filter()

    def _apply_filter(self) -> None:
        self._rows = (self._all_rows if self._game_filter is None else
                      [r for r in self._all_rows
                       if r.get("game") == self._game_filter])
        self._list_pane = ScrollPane(
            self.H - self._list_top(),
            len(self._rows) * (self.ROW_H + self.ROW_GAP) + self.ROW_GAP)

    def _list_top(self) -> int:
        """Top of the scrolling list area (below header + filter row)."""
        return self.HDR_H + (self.FILTER_H if len(self._games) > 1 else 0)

    def _open_detail(self, row: dict) -> None:
        from core.session_summary import build_summary
        from sessionlog.parser import parse
        path = os.path.join(self._logs_dir, row["filename"])
        try:
            summary = build_summary(path)
            with open(path, encoding="utf-8") as f:
                session = parse(f.read(), row["filename"])
        except Exception:
            log.exception(f"history: cannot open {path}")
            return
        if summary is None:
            return
        content = self._build_detail_surface(summary, session)
        self._detail = (row, content)
        self._detail_pane = ScrollPane(self.H - self.HDR_H,
                                       content.get_height())

    # ── input ────────────────────────────────────────────────────────────

    def _back_rect(self) -> pygame.Rect:
        return pygame.Rect(12, 10, 104, 36)

    def _delete_rect(self) -> pygame.Rect:
        return pygame.Rect(self.W - 128, 10, 116, 36)

    def _filter_rects(self) -> list:
        """[(game_id | None, label, rect)] for the game filter chips."""
        if len(self._games) <= 1:
            return []
        chips = [(None, "ALL")] + [
            (g, _GAME_ABBR.get(g, (name or g).upper()))
            for g, name in self._games]
        out = []
        x = 16
        cy = self.HDR_H + (self.FILTER_H - 28) // 2
        for gid, label in chips:
            w = self._f_badge.size(label)[0] + 28
            out.append((gid, label, pygame.Rect(x, cy, w, 28)))
            x += w + 10
        return out

    def _on_tap(self, pos) -> str | None:
        if self._detail is not None:
            if self._delete_rect().collidepoint(pos):
                if self._delete_armed:
                    self._delete_current()
                    if self._direct:
                        return "menu"   # nothing of ours left to show
                else:
                    self._delete_armed = True
                return None
            self._delete_armed = False
            if self._back_rect().collidepoint(pos):
                if self._direct:
                    return "menu"       # back to the caller, not our list
                self._detail = None
            return None
        if self._back_rect().collidepoint(pos):
            return "menu"
        for gid, _label, rect in self._filter_rects():
            if rect.collidepoint(pos):
                if gid != self._game_filter:
                    self._game_filter = gid
                    self._apply_filter()
                return None
        if pos[1] >= self._list_top():
            idx = self._row_index_at(pos)
            if idx is not None:
                self._open_detail(self._rows[idx])
        return None

    def _delete_current(self) -> None:
        """Move the open session to logs/.trash/ and drop it everywhere."""
        row, _ = self._detail
        from core.session_logger import trash_session
        if trash_session(self._logs_dir, row["filename"]):
            try:
                from sessionlog import records
                records.remove(row["filename"])
            except Exception as e:
                log.warning(f"history: index remove failed: {e}")
        self._detail = None
        self._delete_armed = False
        self._load_rows()

    def _row_index_at(self, pos) -> int | None:
        y = pos[1] - self._list_top() + self._list_pane.offset - self.ROW_GAP
        idx, rem = divmod(y, self.ROW_H + self.ROW_GAP)
        if 0 <= rem <= self.ROW_H and 0 <= idx < len(self._rows):
            return int(idx)
        return None

    # ── list screen ──────────────────────────────────────────────────────

    def _draw_list(self) -> None:
        from dashboard.widgets import design_system as DS
        s = self._screen
        s.fill(DS.BG)
        n = len(self._rows)
        self._draw_header("SESSION HISTORY",
                          f"{n} session{'s' if n != 1 else ''}" if n else "")

        # Game filter chips (only when more than one game has sessions)
        for gid, label, rect in self._filter_rects():
            active = gid == self._game_filter
            hov_c  = DS.CYAN if active else DS.BORDER
            pygame.draw.rect(s, DS.PANEL2 if active else DS.PANEL, rect,
                             border_radius=14)
            pygame.draw.rect(s, hov_c, rect, width=2 if active else 1,
                             border_radius=14)
            c = self._f_badge.render(label, True,
                                     DS.CYAN if active else DS.TEXT3)
            s.blit(c, c.get_rect(center=rect.center))

        top = self._list_top()
        if not self._rows:
            msg = self._f_row.render("No sessions recorded yet", True, DS.TEXT3)
            s.blit(msg, msg.get_rect(center=(self.W // 2, (top + self.H) // 2)))
            return

        clip = s.get_clip()
        s.set_clip(pygame.Rect(0, top, self.W, self.H - top))
        y = top + self.ROW_GAP - self._list_pane.offset
        for row in self._rows:
            if y > self.H:
                break
            if y + self.ROW_H > top:
                self._draw_row(row, y)
            y += self.ROW_H + self.ROW_GAP
        s.set_clip(clip)
        self._draw_scrollbar(self._list_pane, top)

    def _draw_row(self, row: dict, y: int) -> None:
        from dashboard.widgets import design_system as DS
        from sessionlog.parser import format_lap_time
        s    = self._screen
        rect = pygame.Rect(16, y, self.W - 32, self.ROW_H)
        pygame.draw.rect(s, DS.PANEL, rect, border_radius=10)
        pygame.draw.rect(s, DS.BORDER, rect, width=1, border_radius=10)

        stype   = row.get("session_type") or ""
        subtype = row.get("session_subtype") or ""
        color   = _badge_color(stype, subtype)
        badge   = self._f_badge.render(_badge_text(stype, subtype), True, color)
        bw      = max(86, badge.get_width() + 20)
        brect   = pygame.Rect(rect.x + 12, rect.centery - 13, bw, 26)
        pygame.draw.rect(s, DS.PANEL2, brect, border_radius=13)
        pygame.draw.rect(s, color, brect, width=1, border_radius=13)
        s.blit(badge, badge.get_rect(center=brect.center))

        tx    = brect.right + 16
        title = " · ".join(b for b in (_row_track(row), row.get("car")) if b) \
                or row.get("game_name") or row["filename"]
        # Right column holds the best lap (top) and lap count (bottom) —
        # both lines must stop short of it.
        title = _ellipsize(self._f_row, title, rect.right - 16 - 110 - tx)
        t = self._f_row.render(title, True, DS.TEXT)
        s.blit(t, (tx, rect.y + 10))
        date = row.get("date")
        when = date.strftime("%a %d %b %Y  %H:%M") if date else ""
        subs = "    ".join(b for b in (row.get("game_name"), when) if b)
        subs = _ellipsize(self._f_sub, subs, rect.right - 16 - 70 - tx)
        sub  = self._f_sub.render(subs, True, DS.TEXT3)
        s.blit(sub, (tx, rect.y + 36))

        best = row.get("best_lap_time")
        if best:
            b = self._f_best.render(format_lap_time(best), True, DS.MAGENTA)
            s.blit(b, b.get_rect(topright=(rect.right - 16, rect.y + 10)))
        laps = row.get("lap_count")
        if laps:
            l = self._f_sub.render(f"{laps} laps", True, DS.TEXT3)
            s.blit(l, l.get_rect(topright=(rect.right - 16, rect.y + 38)))

    # ── detail screen ────────────────────────────────────────────────────

    def _draw_detail(self) -> None:
        from dashboard.widgets import design_system as DS
        row, content = self._detail
        s = self._screen
        s.fill(DS.BG)
        title = " · ".join(b for b in (_row_track(row), row.get("car")) if b) \
                or row.get("game_name") or ""
        date  = row.get("date")
        self._draw_header(title, date.strftime("%d %b %Y  %H:%M") if date else "",
                          badge=(_badge_text(row.get("session_type") or "",
                                             row.get("session_subtype") or ""),
                                 _badge_color(row.get("session_type") or "")))
        s.set_clip(pygame.Rect(0, self.HDR_H, self.W, self.H - self.HDR_H))
        s.blit(content, (0, self.HDR_H - self._detail_pane.offset))
        s.set_clip(None)
        self._draw_scrollbar(self._detail_pane, self.HDR_H)

    def _build_detail_surface(self, summary: dict, session: dict) -> pygame.Surface:
        """Render the scrollable detail content onto one tall surface."""
        from dashboard.widgets import design_system as DS
        from core.session_summary import SessionSummaryView
        from sessionlog.parser import format_lap_time, format_sector_time

        laps      = session.get("laps") or []
        standings = session.get("standings") or []
        notes     = (summary.get("notes_detailed")
                     or [{"text": t, "locations": []} for t in summary["notes"]])
        # A located note draws a thumbnail block that can wrap to two rows.
        n_thumb_notes = sum(1 for n in notes if n.get("locations"))
        est_h = (240 + 30 + len(laps) * 26 + 90 + len(standings) * 24
                 + 60 + len(notes) * 66 + n_thumb_notes * 170 + 200
                 + 240    # racing-line mini-map (when the session has line data)
                 + 260    # journal section (label + up to 10 wrapped lines)
                 + 100    # focus verdict banner + detail line
                 + 60 + len(summary.get("objectives") or []) * 70  # session goals
                 + 450)   # debrief Q&A (label + up to 6 question/answer pairs)
        # depth=24: a default 32-bit offscreen surface carries garbage
        # alpha bytes that corrupt the blit to screen (text renders as
        # solid boxes) and PNG saves.
        surf = pygame.Surface((self.W, est_h), depth=24)
        surf.fill(DS.BG)

        # Summary blocks — reuse the Phase 2 view's rect-driven primitives
        view = SessionSummaryView(summary, self.W, self.H)
        px, pw = self.PAD, self.W - self.PAD * 2
        fmt = summary["fmt"]
        y = 12
        # "Where we raced" — the circuit's real location under the header's
        # full-name title. Only F1 tracks resolve; others render nothing.
        loc = circuits.location(session.get("game"), session.get("track"))
        if loc:
            lt = self._f_sub.render(loc.upper(), True, DS.TEXT3)
            surf.blit(lt, (px, y))
            y += lt.get_height() + 8
        panel_h, grade_w, gap = 108, 258, 12
        view._draw_grade_panel(surf, pygame.Rect(px, y, grade_w, panel_h))
        stats = [
            ("FASTEST",     fmt(summary["fastest"]) if summary["fastest"] else "—",
             DS.MAGENTA if summary["fastest"] else DS.TEXT),
            ("THEORETICAL", fmt(summary["theo"]) if summary["theo"] else "—",
             DS.GREEN if summary["theo"] else DS.TEXT),
            ("AVG CLEAN",   fmt(summary["avg_clean"]) if summary["avg_clean"] else "—",
             DS.TEXT),
            ("CONSISTENCY", f"±{summary['std_dev']:.3f}s" if summary["std_dev"] else "—",
             DS.TEXT),
        ]
        tile_w = (pw - grade_w - gap * len(stats)) // len(stats)
        tx = px + grade_w + gap
        for label, value, color in stats:
            view._draw_stat_tile(surf, pygame.Rect(tx, y, tile_w, panel_h),
                                 label, value, color)
            tx += tile_w + gap
        y += panel_h + 10

        # All-time record at this combo (companion parity)
        if summary.get("overall_best") is not None:
            if summary.get("overall_holds"):
                txt, color = "OVERALL BEST — THIS SESSION", DS.MAGENTA
            else:
                ogap = (f"  +{summary['fastest'] - summary['overall_best']:.3f}"
                        if summary["fastest"] is not None else "")
                txt   = f"OVERALL  {fmt(summary['overall_best'])}{ogap}"
                color = DS.PURPLE
            ob = self._f_sub.render(txt, True, color)
            surf.blit(ob, ob.get_rect(topright=(px + pw, y)))
            y += ob.get_height() + 8
        else:
            y += 8

        g = summary["grade"]
        if g:
            y = view._draw_wrapped(surf, g.get("explanation", ""),
                                   px, y, pw, DS.TEXT2, max_lines=4)
            if g.get("focus"):
                y = view._draw_wrapped(surf, f"FOCUS:  {g['focus']}",
                                       px, y + 4, pw, DS.AMBER, max_lines=2)
            y += 14

        # The driver's chosen goal for this session and how it tracked
        # (sessionlog.focus — distinct from the grading engine's algorithmic
        # "FOCUS:" line above, which the driver never picked). Reuses the
        # live end-of-session banner drawer; build_summary() already
        # computes focus_verdict independently of the live-flow gating, so
        # it's available here even though the driver's debrief (below)
        # hadn't happened yet when the live summary itself was shown.
        fv = summary.get("focus_verdict")
        if fv:
            view._draw_focus_banner(surf, px, y, pw, fv)
            y += 30 + 6
            if fv.get("detail"):
                y = view._draw_wrapped(surf, fv["detail"], px, y, pw,
                                       DS.TEXT2, max_lines=2) + 8

        # Tracked objectives (O rows) and how each one turned out — the
        # closed-loop follow-up to the pre-session NEXT GOAL card. The fixed
        # end-of-session summary has no room, so this scrollable detail view
        # is where the per-goal ✓/✗ review lives.
        y = view._draw_objectives(surf, px, y, pw)

        # Lap table
        if laps:
            from sessionlog.grading import RACE_TYPES
            y = self._section_label(surf, "LAPS", px, y)
            has_s  = any(lap.get("s1") is not None for lap in laps)
            # Lap-end position only means anything in a race — in
            # practice/quali it is just the live timesheet order.
            stype   = (session.get("session_type") or "").strip().lower()
            has_pos = (stype in RACE_TYPES
                       and any(lap.get("position") is not None for lap in laps))
            has_rw  = any(lap.get("rewinds") for lap in laps)
            # Tyre chip lives inside the LAP cell (companion parity) — it
            # only widens LAP rather than adding a column.
            has_tyre = any(lap.get("tyre_compound") for lap in laps)
            cols = [("LAP", 84 if has_tyre else 54)]
            cols.append(("TIME", 110))
            if has_s:
                cols += [("S1", 92), ("S2", 92), ("S3", 92)]
            if has_pos:
                cols.append(("POS", 60))
            if has_rw:
                cols.append(("RW", 40))   # rewinds/flashbacks this lap
            cx = px
            for name, w in cols:
                if name:
                    h = self._f_label.render(name, True, DS.TEXT3)
                    surf.blit(h, (cx, y))
                cx += w
            y += 22
            for lap in laps:
                cx = px
                num = self._f_cell.render(str(lap["num"]), True, DS.TEXT3)
                surf.blit(num, (cx, y))
                if has_tyre and lap.get("tyre_compound"):
                    from dashboard.widgets.tyre_chip import draw_chip
                    draw_chip(surf, self._f_badge, lap["tyre_compound"],
                              px + 30, y + num.get_height() // 2)
                cx += cols[0][1]
                t_color = _flag_color("red" if not lap.get("valid", True)
                                      else lap.get("lap_flag"))
                t = self._f_cell.render(format_lap_time(lap["time"]), True, t_color)
                surf.blit(t, (cx, y))
                cx += cols[1][1]
                if has_s:
                    for key in ("s1", "s2", "s3"):
                        val = lap.get(key)
                        c = self._f_cell.render(
                            format_sector_time(val) if val is not None else "—",
                            True, _flag_color(lap.get(f"{key}_flag")))
                        surf.blit(c, (cx, y))
                        cx += 92
                if has_pos:
                    pos = lap.get("position")
                    p = self._f_cell.render(f"P{pos}" if pos else "—", True, DS.TEXT2)
                    surf.blit(p, (cx, y))
                    cx += 60
                if has_rw and lap.get("rewinds"):
                    r = self._f_cell.render(str(lap["rewinds"]), True, DS.AMBER)
                    surf.blit(r, (cx, y))
                y += 26
            y += 14

        # Standings — R-row values are raw CSV strings (see parser docstring)
        if standings:
            y = self._section_label(surf, "STANDINGS", px, y)
            me = (session.get("driver_name") or "").strip().upper()
            # Race gap column baseline: the winner's total race time — the
            # rest show their gap to it, not their own absolute total
            # (companion parity, v0.30.4).
            leader_time = next((_csv_float(p.get("race_time")) for p in standings
                                if str(p.get("position", "")) == "1"), None)
            for p in standings:
                name  = (p.get("name") or "").strip()
                is_me = me and name.upper() == me
                color = DS.CYAN if is_me else DS.TEXT2
                pos = self._f_cell.render(f"P{p.get('position', '')}", True, DS.TEXT3)
                surf.blit(pos, (px, y))
                n = self._f_cell.render(name, True, color)
                surf.blit(n, (px + 54, y))
                best = _csv_float(p.get("best_lap"))
                if best:
                    b = self._f_cell.render(format_lap_time(best), True, color)
                    surf.blit(b, b.get_rect(topright=(px + pw - 130, y)))
                rt = _csv_float(p.get("race_time"))
                if rt is not None:
                    if str(p.get("position", "")) == "1" or leader_time is None:
                        r_str = format_lap_time(rt)
                    else:
                        r_str = f"+{rt - leader_time:.3f}"
                    r = self._f_cell.render(r_str, True, DS.TEXT3)
                    surf.blit(r, r.get_rect(topright=(px + pw, y)))
                y += 24
            y += 14

        # Career badges this session earned (no emoji on the Pi — text
        # lines in amber, same wording as the summary banner).
        awards = summary.get("awards") or []
        if awards:
            from core.session_summary import _award_banner
            y = self._section_label(surf, "ACHIEVEMENTS", px, y)
            for a in awards:
                line = _award_banner([a])
                bullet = self._f_cell.render("·", True, DS.on_panel(DS.AMBER))
                surf.blit(bullet, (px, y))
                y = view._draw_wrapped(surf, line, px + 16, y, pw - 16,
                                       DS.on_panel(DS.AMBER), max_lines=2) + 6
            y += 8

        # Race Engineer Notes — the full list (the live summary shows three),
        # each located note followed by a row of mini-map thumbnails.
        if notes:
            from core import track_thumb
            from sessionlog import trackmap
            track_map = summary.get("track_map")

            def _geom(loc):
                return trackmap.crop_geometry(track_map, loc.get("distance"))

            y = self._section_label(surf, "RACE ENGINEER NOTES", px, y)
            for note in notes:
                bullet = self._f_cell.render("·", True, DS.on_panel(DS.CYAN))
                surf.blit(bullet, (px, y))
                y = view._draw_wrapped(surf, note["text"], px + 16, y, pw - 16,
                                       DS.TEXT2, max_lines=4) + 6
                locs = note.get("locations") or []
                if locs and track_map:
                    y = track_thumb.draw_row(surf, px + 16, y, locs, _geom,
                                             font=self._f_cell,
                                             avail_w=pw - 16) + 6

        # (The full-track racing-line map was removed here: at the 7" screen's
        # ~210px it was too small to read the driven-vs-racing difference. The
        # zoomed corner thumbnails on the Race Engineer Notes above carry the
        # off-line story legibly; the full zoomable line view lives in the web
        # companion's session viewer.)

        # Journal — the session's story (sessionlog.journal): the biggest
        # thing that happened drives the entry, debrief answers woven in.
        try:
            from sessionlog import records
            from sessionlog.achievements import session_awards
            from sessionlog.journal import journal_entry
            hist = records.combo_history(
                session.get("game"), session.get("car_class"),
                session.get("track"), session.get("session_type"))
            awards = session_awards(records.all_sessions(),
                                    session.get("filename") or "")
            entry = journal_entry(session,
                                  prior_best=summary.get("prior_best"),
                                  history=hist, awards=awards)["text"]
        except Exception:
            entry = ""
        if entry:
            y += 8
            y = self._section_label(surf, "JOURNAL", px, y)
            y = view._draw_wrapped(surf, entry, px, y, pw,
                                   DS.TEXT2, max_lines=10) + 6

        # Debrief — the raw end-of-session Q&A (sessionlog.debrief), so the
        # driver can see exactly what they answered, not just the journal's
        # narrative synthesis of it above.
        from sessionlog.debrief import debrief_qa
        qa = debrief_qa(session)
        if qa:
            y += 8
            y = self._section_label(surf, "DEBRIEF", px, y)
            for question, answer in qa:
                y = view._draw_wrapped(surf, question, px, y, pw,
                                       DS.TEXT3, max_lines=1) + 2
                y = view._draw_wrapped(surf, answer, px, y, pw,
                                       DS.TEXT, max_lines=2) + 8

        return surf.subsurface(pygame.Rect(0, 0, self.W,
                                           min(est_h, y + 24))).copy()

    def _section_label(self, surf, text, x, y) -> int:
        from dashboard.widgets import design_system as DS
        lbl = self._f_label.render(text, True, DS.TEXT3)
        surf.blit(lbl, (x, y))
        return y + lbl.get_height() + 8

    # ── chrome ───────────────────────────────────────────────────────────

    def _draw_header(self, title: str, right: str = "", badge=None) -> None:
        from dashboard.widgets import design_system as DS
        s = self._screen
        back = self._back_rect()
        pygame.draw.rect(s, DS.PANEL, back, border_radius=back.height // 2)
        pygame.draw.rect(s, DS.BORDER, back, width=1, border_radius=back.height // 2)
        lbl = self._f_sub.render("‹  BACK" if self._detail else "‹  MENU",
                                 True, DS.TEXT3)
        s.blit(lbl, lbl.get_rect(center=back.center))

        # Budget the right side (DELETE pill + right label) BEFORE drawing
        # the title, so a long track name is ellipsized instead of running
        # underneath them.
        title_limit = self.W - 16
        if self._detail is not None:
            title_limit = self._delete_rect().left - 14
        if right:
            title_limit -= self._f_sub.size(right)[0] + 20
        x = back.right + 16
        badge_w = 0
        if badge:
            badge_w = self._f_badge.size(badge[0])[0] + 16 + 12
        title = _ellipsize(self._f_hdr, title, title_limit - badge_w - x)
        t = self._f_hdr.render(title, True, DS.TEXT)
        s.blit(t, (x, back.centery - t.get_height() // 2))
        if badge:
            text, color = badge
            b  = self._f_badge.render(text, True, color)
            bx = x + t.get_width() + 12
            br = pygame.Rect(bx, back.centery - 12, b.get_width() + 16, 24)
            pygame.draw.rect(s, DS.PANEL2, br, border_radius=12)
            pygame.draw.rect(s, color, br, width=1, border_radius=12)
            s.blit(b, b.get_rect(center=br.center))
        right_edge = self.W - 16
        if self._detail is not None:
            # DELETE (two-tap): armed state turns red and asks to confirm
            drect = self._delete_rect()
            label = "CONFIRM?" if self._delete_armed else "DELETE"
            color = DS.RED if self._delete_armed else DS.TEXT3
            pygame.draw.rect(s, DS.PANEL, drect, border_radius=drect.height // 2)
            pygame.draw.rect(s, DS.RED if self._delete_armed else DS.BORDER,
                             drect, width=2 if self._delete_armed else 1,
                             border_radius=drect.height // 2)
            d = self._f_sub.render(label, True, color)
            s.blit(d, d.get_rect(center=drect.center))
            right_edge = drect.left - 14
        if right:
            r = self._f_sub.render(right, True, DS.TEXT3)
            s.blit(r, r.get_rect(midright=(right_edge, back.centery)))
        pygame.draw.line(s, DS.BORDER, (0, self.HDR_H - 1),
                         (self.W, self.HDR_H - 1))

    def _draw_scrollbar(self, pane: ScrollPane, top: int) -> None:
        from dashboard.widgets import design_system as DS
        content_h = pane._content_h
        view_h    = pane._viewport_h
        if content_h <= view_h:
            return
        track_y = top + 4
        track_h = self.H - top - 8
        bar_h   = max(24, int(track_h * view_h / content_h))
        max_off = content_h - view_h
        bar_y   = track_y + int((track_h - bar_h) * pane.offset / max_off)
        pygame.draw.rect(self._screen, DS.BORDER2,
                         pygame.Rect(self.W - 6, bar_y, 3, bar_h),
                         border_radius=2)
