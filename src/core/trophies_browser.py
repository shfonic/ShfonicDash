"""
Trophies browser — the career badge gallery on the Dash (TROPHIES button
on the game menu).

Touch-scrollable list of every badge in sessionlog.achievements, grouped
by category: earned ones with a tier-coloured medal ring, multiplier and
date; unearned ones as dim outlines with how to earn them. Tapping ANY
badge — earned or not — opens a detail screen: what the trophy is, how to
earn it, and (when earned) the full list of sessions that count towards
it, newest first. Tapping a session there opens it in the history
browser's detail view.

Same interaction grammar as the history browser (ScrollPane, ‹ MENU
pill, ESC), and the same data as the companion's Trophies screen — both
evaluate the same archive, so the collections always match. No emoji on
the Pi: the medal ring carries the badge state instead.
"""

import logging
import os

import pygame

from core.flip import flip_pos, flip_surface
from core.history_browser import ScrollPane, _ellipsize

log = logging.getLogger(__name__)

_TIER_COLORS = {
    "bronze": (205, 127, 50),
    "silver": (192, 198, 205),
    "gold":   (255, 200, 40),
}


class TrophiesBrowser:
    """Blocking gallery loop over the records index in logs_dir."""

    W, H    = 800, 480
    HDR_H   = 64
    PAD     = 28
    ROW_H   = 56
    ROW_GAP = 8
    SEC_H   = 40

    def __init__(self, screen: pygame.Surface, logs_dir: str,
                 flip: bool = False):
        from dashboard.widgets.fonts import load_ui
        self._screen   = screen
        self._logs_dir = logs_dir
        self._flip     = flip
        self._f_hdr    = load_ui(16)
        self._f_big    = load_ui(22)
        self._f_name   = load_ui(16)
        self._f_body   = load_ui(14)
        self._f_sub    = load_ui(12)
        self._entries  = []   # ('section', label) | ('badge', bdef, state)
        self._records_by_fn = {}
        self._earned_n = 0
        self._total_n  = 0
        self._pane     = ScrollPane(self.H - self.HDR_H)
        self._detail   = None   # (bdef, state) when a badge is open
        self._detail_items = []
        self._detail_pane  = ScrollPane(self.H - self.HDR_H)

    # ── public ───────────────────────────────────────────────────────────

    def run(self) -> str:
        """Blocking loop. Returns "menu" (back) or "quit"."""
        self._load()
        clock = pygame.time.Clock()
        while True:
            pane = self._detail_pane if self._detail else self._pane
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "quit"
                if event.type == pygame.KEYDOWN \
                        and event.key == pygame.K_ESCAPE:
                    if self._detail is not None:
                        self._detail = None
                    else:
                        return "menu"
                    continue
                if event.type == pygame.MOUSEBUTTONDOWN:
                    pane.press(flip_pos(event.pos, self._flip))
                elif event.type == pygame.MOUSEMOTION:
                    pane.motion(flip_pos(event.pos, self._flip))
                elif event.type == pygame.MOUSEBUTTONUP:
                    tap = pane.release(flip_pos(event.pos, self._flip))
                    if tap is not None:
                        action = (self._on_detail_tap(tap) if self._detail
                                  else self._on_tap(tap))
                        if action is not None:
                            return action
            if self._detail is not None:
                self._draw_detail()
            else:
                self._draw()
            flip_surface(self._screen, self._flip)
            pygame.display.flip()
            clock.tick(30)

    # ── data ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        from sessionlog.achievements import BADGES, CATEGORIES, evaluate
        earned = {}
        self._records_by_fn = {}
        if self._logs_dir and os.path.isdir(self._logs_dir):
            try:
                from sessionlog import records
                records.set_cache_dir(self._logs_dir)
                records.sync()
                rows = records.all_sessions()
                self._records_by_fn = {r.get("filename"): r for r in rows}
                earned = evaluate(rows)
            except Exception as e:
                log.warning(f"trophies: records unavailable: {e}")
        self._entries = []
        for cat_id, cat_name in CATEGORIES:
            self._entries.append(("section", cat_name.upper()))
            for bdef in BADGES:
                if bdef["category"] == cat_id:
                    self._entries.append(("badge", bdef,
                                          earned.get(bdef["id"])))
        self._total_n  = len(BADGES)
        self._earned_n = sum(1 for e in self._entries
                             if e[0] == "badge" and e[2] is not None)
        self._pane = ScrollPane(self.H - self.HDR_H, self._content_h())

    def _content_h(self) -> int:
        h = self.ROW_GAP
        for entry in self._entries:
            h += self.SEC_H if entry[0] == "section" \
                else self.ROW_H + self.ROW_GAP
        return h + self.PAD

    # ── interaction ──────────────────────────────────────────────────────

    def _on_tap(self, pos) -> str | None:
        if pos[1] < self.HDR_H:
            if self._back_rect().collidepoint(pos):
                return "menu"
            return None
        y = self.HDR_H + self.ROW_GAP - self._pane.offset
        for entry in self._entries:
            if entry[0] == "section":
                y += self.SEC_H
                continue
            rect = pygame.Rect(16, y, self.W - 32, self.ROW_H)
            if rect.collidepoint(pos):
                self._open_detail(entry[1], entry[2])
                return None
            y += self.ROW_H + self.ROW_GAP
        return None

    def _open_detail(self, bdef: dict, state) -> None:
        self._detail = (bdef, state)
        self._detail_items = self._build_detail_items(bdef, state)
        h = self.ROW_GAP + sum(it["h"] for it in self._detail_items) + self.PAD
        self._detail_pane = ScrollPane(self.H - self.HDR_H, h)

    def _build_detail_items(self, bdef: dict, state) -> list:
        """Flat list of drawables so draw and hit-test share one geometry.

        kinds: 'medal' (badge name + status), 'howto' (wrapped desc +
        tier goals), 'label' (section caption), 'sess' (session row),
        'note' (a plain wrapped line)."""
        from sessionlog.achievements import tier_goals
        items = [{"kind": "medal", "h": 84}]

        how_lines = self._wrap(self._f_body, bdef["desc"], self.W - self.PAD * 2)
        goals = tier_goals(bdef)
        if goals:
            how_lines.append(goals)
        items.append({"kind": "label", "text": "HOW TO EARN", "h": self.SEC_H})
        items.append({"kind": "howto", "lines": how_lines,
                      "h": len(how_lines) * 22 + 10})

        sessions = state.get("sessions") if state else None
        if sessions:
            items.append({"kind": "label",
                          "text": f"SESSIONS  ·  {len(sessions)}",
                          "h": self.SEC_H})
            for fn, date in sessions:
                rec = self._records_by_fn.get(fn)
                if rec is not None:
                    items.append({"kind": "sess", "rec": rec, "fn": fn,
                                  "h": self.ROW_H + self.ROW_GAP})
        else:
            note = ("Not yet earned — this one's still on the board."
                    if state is None else "Earned.")
            lines = self._wrap(self._f_body, note, self.W - self.PAD * 2)
            items.append({"kind": "note", "lines": lines,
                          "h": len(lines) * 22 + 10})
        return items

    def _on_detail_tap(self, pos) -> str | None:
        if pos[1] < self.HDR_H:
            if self._back_rect().collidepoint(pos):
                self._detail = None
            return None
        y = self.HDR_H + self.ROW_GAP - self._detail_pane.offset
        for it in self._detail_items:
            if it["kind"] == "sess":
                rect = pygame.Rect(16, y, self.W - 32, self.ROW_H)
                if rect.collidepoint(pos):
                    return self._open_session(it["fn"])
            y += it["h"]
        return None

    def _open_session(self, filename: str) -> str | None:
        """Open one earning session in the history browser's detail view;
        returns "quit" if the window was closed there."""
        from core.history_browser import HistoryBrowser
        result = HistoryBrowser(self._screen, self._logs_dir,
                                flip=self._flip).run(open_file=filename)
        if result == "quit":
            return "quit"
        # The session may have been deleted in the detail view — badges
        # are archive-derived, so recompute and refresh what we show.
        bid = self._detail[0]["id"] if self._detail else None
        self._load()
        if bid is not None:
            for entry in self._entries:
                if entry[0] == "badge" and entry[1]["id"] == bid:
                    self._open_detail(entry[1], entry[2])
                    break
        return None

    def _back_rect(self) -> pygame.Rect:
        return pygame.Rect(16, 14, 104, 36)

    # ── gallery drawing ──────────────────────────────────────────────────

    def _draw(self) -> None:
        from dashboard.widgets import design_system as DS
        s = self._screen
        s.fill(DS.BG)
        self._draw_header("TROPHIES",
                          f"{self._earned_n} OF {self._total_n} EARNED")

        clip = s.get_clip()
        s.set_clip(pygame.Rect(0, self.HDR_H, self.W, self.H - self.HDR_H))
        y = self.HDR_H + self.ROW_GAP - self._pane.offset
        for entry in self._entries:
            if entry[0] == "section":
                if -self.SEC_H < y < self.H:
                    sec = self._f_sub.render(entry[1], True, DS.TEXT3)
                    s.blit(sec, (self.PAD, y + 16))
                y += self.SEC_H
            else:
                if -self.ROW_H < y < self.H:
                    self._draw_badge_row(entry[1], entry[2], y)
                y += self.ROW_H + self.ROW_GAP
        s.set_clip(clip)

    def _draw_header(self, title: str, right: str = "") -> None:
        from dashboard.widgets import design_system as DS
        s = self._screen
        back = self._back_rect()
        pygame.draw.rect(s, DS.PANEL, back, border_radius=back.height // 2)
        pygame.draw.rect(s, DS.BORDER, back, width=1,
                         border_radius=back.height // 2)
        lbl = self._f_sub.render("‹  BACK" if self._detail else "‹  MENU",
                                 True, DS.TEXT3)
        s.blit(lbl, lbl.get_rect(center=back.center))
        limit = self.W - 16 - (self._f_sub.size(right)[0] + 24 if right else 0)
        title = _ellipsize(self._f_hdr, title, limit - (back.right + 16))
        t = self._f_hdr.render(title, True, DS.TEXT)
        s.blit(t, (back.right + 16, back.centery - t.get_height() // 2))
        if right:
            r = self._f_sub.render(right, True, DS.TEXT3)
            s.blit(r, r.get_rect(midright=(self.W - 16, back.centery)))
        pygame.draw.line(s, DS.BORDER, (0, self.HDR_H - 1),
                         (self.W, self.HDR_H - 1))

    def _draw_medal(self, cx: int, cy: int, accent, earned: bool,
                    r: int = 13) -> None:
        s = self._screen
        pygame.draw.circle(s, accent, (cx, cy), r, width=2)
        if earned:
            pygame.draw.circle(s, accent, (cx, cy), r - 7)

    def _draw_badge_row(self, bdef: dict, state, y: int) -> None:
        from dashboard.widgets import design_system as DS
        s      = self._screen
        earned = state is not None
        tier   = state.get("tier") if earned else None
        accent = _TIER_COLORS.get(tier, DS.AMBER if earned else DS.BORDER)

        rect = pygame.Rect(16, y, self.W - 32, self.ROW_H)
        pygame.draw.rect(s, DS.PANEL if earned else DS.BG, rect,
                         border_radius=10)
        pygame.draw.rect(s, accent, rect, width=2 if earned else 1,
                         border_radius=10)

        # Medal ring — the Pi's stand-in for the companion's emoji icon.
        self._draw_medal(rect.x + 30, rect.centery, accent, earned)

        name_c = DS.TEXT if earned else DS.TEXT4
        n = self._f_name.render(bdef["name"], True, name_c)
        s.blit(n, (rect.x + 56, rect.y + 8))

        if earned:
            bits = []
            if state["count"] > 1 or bdef.get("tiers"):
                bits.append(f"×{state['count']}")
            if tier:
                bits.append(tier.upper())
            when = state["sessions"][0][1] if state["sessions"] else None
            if when:
                bits.append(when.strftime("%d %b %Y"))
            sub_text, sub_c = "  ·  ".join(bits) or "EARNED", accent
        else:
            sub_text, sub_c = bdef["desc"], DS.TEXT4
        sub_text = _ellipsize(self._f_sub, sub_text,
                              rect.right - 16 - (rect.x + 56))
        sub = self._f_sub.render(sub_text, True, sub_c)
        s.blit(sub, (rect.x + 56, rect.y + 32))

        # Every badge is tappable now (unearned opens the how-to card).
        ch = self._f_name.render("›", True, DS.TEXT3 if earned else DS.TEXT4)
        s.blit(ch, ch.get_rect(midright=(rect.right - 16, rect.centery)))

    # ── detail drawing ───────────────────────────────────────────────────

    def _draw_detail(self) -> None:
        from dashboard.widgets import design_system as DS
        bdef, state = self._detail
        s = self._screen
        s.fill(DS.BG)
        cat = {"milestones": "MILESTONE", "craft": "CRAFT",
               "progress": "PROGRESS", "racecraft": "RACECRAFT"}.get(
                   bdef["category"], "")
        self._draw_header("TROPHIES", cat)

        clip = s.get_clip()
        s.set_clip(pygame.Rect(0, self.HDR_H, self.W, self.H - self.HDR_H))
        y = self.HDR_H + self.ROW_GAP - self._detail_pane.offset
        for it in self._detail_items:
            if it["kind"] == "medal":
                self._draw_detail_medal(bdef, state, y)
            elif it["kind"] == "label":
                lbl = self._f_sub.render(it["text"], True, DS.TEXT3)
                s.blit(lbl, (self.PAD, y + 16))
            elif it["kind"] in ("howto", "note"):
                color = DS.TEXT2 if it["kind"] == "howto" else DS.TEXT4
                ly = y
                for line in it["lines"]:
                    ln = self._f_body.render(line, True, color)
                    s.blit(ln, (self.PAD, ly))
                    ly += 22
            elif it["kind"] == "sess":
                self._draw_session_row(it["rec"], y)
            y += it["h"]
        s.set_clip(clip)

    def _draw_detail_medal(self, bdef: dict, state, y: int) -> None:
        from dashboard.widgets import design_system as DS
        s      = self._screen
        earned = state is not None
        tier   = state.get("tier") if earned else None
        accent = _TIER_COLORS.get(tier, DS.AMBER if earned else DS.BORDER)

        cx, cy = self.PAD + 26, y + 34
        self._draw_medal(cx, cy, accent, earned, r=24)

        name = self._f_big.render(bdef["name"], True,
                                  DS.TEXT if earned else DS.TEXT2)
        s.blit(name, (cx + 44, y + 6))

        if earned:
            bits = [f"×{state['count']}"] if (state["count"] > 1
                                              or bdef.get("tiers")) else []
            if tier:
                bits.append(tier.upper())
            sessions = state.get("sessions") or []
            if sessions:
                newest = sessions[0][1]
                oldest = sessions[-1][1]
                if newest:
                    span = newest.strftime("%d %b %Y")
                    if oldest and oldest != newest:
                        span = f"{oldest.strftime('%d %b %Y')} – {span}"
                    bits.append(span)
            status, color = "  ·  ".join(bits) or "EARNED", accent
        else:
            status, color = "NOT YET EARNED", DS.TEXT4
        st = self._f_sub.render(status, True, color)
        s.blit(st, (cx + 44, y + 40))

    def _draw_session_row(self, rec: dict, y: int) -> None:
        from dashboard.widgets import design_system as DS
        from core.history_browser import _badge_color, _badge_text
        from sessionlog.parser import format_lap_time
        s    = self._screen
        rect = pygame.Rect(16, y, self.W - 32, self.ROW_H)
        pygame.draw.rect(s, DS.PANEL, rect, border_radius=10)
        pygame.draw.rect(s, DS.BORDER, rect, width=1, border_radius=10)

        stype   = rec.get("session_type") or ""
        subtype = rec.get("session_subtype") or ""
        color   = _badge_color(stype, subtype)
        badge   = self._f_sub.render(_badge_text(stype, subtype), True, color)
        bw      = max(76, badge.get_width() + 18)
        brect   = pygame.Rect(rect.x + 12, rect.centery - 12, bw, 24)
        pygame.draw.rect(s, DS.PANEL2, brect, border_radius=12)
        pygame.draw.rect(s, color, brect, width=1, border_radius=12)
        s.blit(badge, badge.get_rect(center=brect.center))

        tx = brect.right + 14
        title = " · ".join(b for b in (rec.get("track"), rec.get("car")) if b) \
            or rec.get("game_name") or rec.get("filename") or ""
        title = _ellipsize(self._f_name, title, rect.right - 16 - 100 - tx)
        s.blit(self._f_name.render(title, True, DS.TEXT), (tx, rect.y + 8))
        date = rec.get("date")
        when = date.strftime("%a %d %b %Y  %H:%M") if date else ""
        subs = "    ".join(b for b in (rec.get("game_name"), when) if b)
        subs = _ellipsize(self._f_sub, subs, rect.right - 16 - 100 - tx)
        s.blit(self._f_sub.render(subs, True, DS.TEXT3), (tx, rect.y + 32))

        best = rec.get("best_lap_time")
        if best:
            b = self._f_name.render(format_lap_time(best), True, DS.MAGENTA)
            s.blit(b, b.get_rect(midright=(rect.right - 16, rect.centery)))

    # ── helpers ──────────────────────────────────────────────────────────

    def _wrap(self, font, text: str, max_w: int) -> list:
        """Greedy word-wrap into lines that render within max_w."""
        words, lines, cur = text.split(), [], ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if cur and font.size(trial)[0] > max_w:
                lines.append(cur)
                cur = w
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines or [""]
