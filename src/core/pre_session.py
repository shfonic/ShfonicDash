"""Pre-session goals card — "NEXT GOAL" shown when a session begins paused.

Hotlap/TT sessions start in the pause menu; practice and qualifying often
do too. Before any lap is driven there is nothing to summarise — but there
IS history: this card shows data-backed goals for the upcoming stint
(grade step, provable time in your own sectors, missions) built by
sessionlog.goals from the records index. Everything shown is derived from
recorded sessions at the same game/car class/track/session type — nothing
is invented.

Shares the summary modal slot in App.run(): tap dismisses, driving away
dismisses, and the next zero-lap pause shows it again.
"""
import logging
import os

import pygame

log = logging.getLogger("pre_session")


def _track_limit_hotspot(logs_dir: str, history: list, track_map) -> dict | None:
    """The corner that dominated the LAST session's track-limit warnings, or
    None. Corner-level detail isn't indexed (records.py is whole-session
    aggregates only), so this re-parses that one prior session's raw CSV —
    same move as history_browser._open_detail(). Best-effort: any read/parse
    failure just means no hotspot mission, never fatal to the goal card."""
    if not history or not track_map:
        return None
    from sessionlog.pace import track_limit_counts
    from sessionlog.parser import parse

    prev = history[-1]   # same "last session" pre_session_goal() itself uses
    try:
        path = os.path.join(logs_dir, prev["filename"])
        with open(path, encoding="utf-8") as f:
            prev_session = parse(f.read(), prev["filename"])
    except (OSError, ValueError, KeyError):
        return None
    counts = track_limit_counts(prev_session.get("events") or [], track_map)
    if not counts:
        return None
    label, n = max(counts.items(), key=lambda kv: kv[1])
    if n < 2:
        return None
    return {"label": label, "count": n, "total": sum(counts.values())}


def _line_hotspot(logs_dir: str, history: list, track_map) -> dict | None:
    """The corner where the LAST session's driven line strayed furthest from
    the racing line, or None. Like _track_limit_hotspot, the line profiles (P
    rows) aren't indexed, so this re-parses that one prior session's CSV.
    Best-effort — any failure just means no "tighten your line" mission."""
    if not history or not track_map:
        return None
    from sessionlog.lines import line_hotspot
    from sessionlog.parser import parse

    prev = history[-1]
    try:
        path = os.path.join(logs_dir, prev["filename"])
        with open(path, encoding="utf-8") as f:
            prev_session = parse(f.read(), prev["filename"])
    except (OSError, ValueError, KeyError):
        return None
    return line_hotspot(prev_session, track_map)


def build_pre_session(logs_dir: str, data) -> dict | None:
    """Assemble the NEXT GOAL card dict for the upcoming session.

    data — the current TelemetryData snapshot (identifies the combo).
    Returns None when there is no usable history: first visit to the
    combo, or the game doesn't provide a track name (PC2/Forza).
    """
    if not (logs_dir and data.game and data.car_class
            and data.track and data.session_type):
        return None
    from sessionlog import records, trackmap
    from sessionlog.goals import baseline_goal, pre_session_goal
    from sessionlog.parser import format_lap_time

    records.set_cache_dir(logs_dir)
    records.sync()
    history = records.combo_history(data.game, data.car_class,
                                    data.track, data.session_type)

    track_map = None
    try:
        trackmap.set_tracks_dir(os.path.join(logs_dir, "..", "tracks"))
        track_map = trackmap.find_map(data.game, data.track)
    except Exception as e:                        # fs — never fatal
        log.warning(f"pre_session: track map lookup failed: {e}")
    hotspot = _track_limit_hotspot(logs_dir, history, track_map)
    line_hot = _line_hotspot(logs_dir, history, track_map)

    # No history at this combo → a first-visit baseline card ("learn the
    # track / set a baseline") rather than nothing. We still have a track
    # name here (guarded above), so it's a real combo the driver is about to
    # run — just one the app hasn't seen before.
    goal = (pre_session_goal(history, track_limit_hotspot=hotspot,
                             line_hotspot=line_hot,
                             session_type=data.session_type)
            or baseline_goal(data.session_type))
    goal["track"]        = data.track
    goal["car_class"]    = data.car_class
    goal["session_type"] = data.session_type
    goal["fmt"]          = format_lap_time
    return goal


# Emoji icons from sessionlog.goals → drawn glyphs (the Pi's fonts have
# no emoji; same approach as the menu's milestone panel).
_ICON_KIND = {"🎯": "target", "✅": "check", "⏪": "rewind",
              "⏱": "clock", "📏": "ruler", "🏆": "trophy", "🎚": "dial",
              "⚠️": "warning"}


class PreSessionView:
    """Full-screen 800x480 renderer for a build_pre_session() dict.

    Implements the same modal interface as SessionSummaryView so
    App.run() can host either in the summary slot.
    """

    _PAD = 28

    def __init__(self, goal: dict, width: int = 800, height: int = 480,
                 on_focus=None):
        from dashboard.widgets.fonts import load_display, load_ui
        from sessionlog import focus
        self._g = goal
        self._w, self._h = width, height
        self._f_caption = load_ui(12)
        self._f_label   = load_ui(12)
        self._f_title   = load_ui(22)
        self._f_sub     = load_ui(14)
        self._f_stat    = load_ui(24)
        self._f_body    = load_ui(14)
        self._f_mission = load_ui(16)
        self._f_chip    = load_ui(15)
        self._f_letter  = load_display(44)
        # Focus chips the driver commits to (writes an F row via on_focus).
        # The chip set is session-type-specific (race gets its own).
        self._on_focus   = on_focus
        self._focuses    = focus.available_focuses(goal, goal.get("session_type"))
        self._selected   = None
        self._chip_rects: list = []   # [(pygame.Rect, focus_id)], set in render()

    # ── drawing ──────────────────────────────────────────────────────────

    def render(self, screen: pygame.Surface) -> None:
        from dashboard.widgets import design_system as DS
        g   = self._g
        px  = self._PAD
        pw  = self._w - px * 2
        fmt = g["fmt"]

        screen.fill(DS.BG)

        y = 20
        cap = self._f_caption.render("NEXT GOAL", True, DS.TEXT3)
        screen.blit(cap, (px, y))
        badge = self._f_caption.render(
            g["session_type"].replace("_", " ").upper(), True, DS.on_panel(DS.CYAN))
        screen.blit(badge, (px + cap.get_width() + 16, y))
        hint = self._f_caption.render("TAP TO DISMISS  ·  DRIVE TO START",
                                      True, DS.TEXT3)
        screen.blit(hint, hint.get_rect(topright=(self._w - px, y)))

        y = 44
        title = self._f_title.render(g["track"], True, DS.TEXT)
        screen.blit(title, (px, y))
        n = g["session_count"]
        if n == 0:
            sub = "First visit — no history here yet"
        else:
            sub = f"{n} previous session{'s' if n != 1 else ''} here"
            if g.get("prior_best"):
                sub += f"    best {fmt(g['prior_best'])}"
        sub_s = self._f_sub.render(sub, True, DS.TEXT3)
        screen.blit(sub_s, (px, y + title.get_height() + 6))

        # Grade-step panel (left) + stat tiles (right)
        y = 122
        panel_h = 96
        grade_w = 258
        self._draw_grade_panel(screen, pygame.Rect(px, y, grade_w, panel_h))
        stats = [
            ("BEST HERE", fmt(g["prior_best"]) if g.get("prior_best") else "—",
             DS.on_panel(DS.MAGENTA) if g.get("prior_best") else DS.TEXT),
            ("IN YOUR SECTORS",
             f"-{g['estimated_gain']:.3f}s" if g.get("estimated_gain") else "—",
             DS.on_panel(DS.GREEN) if g.get("estimated_gain") else DS.TEXT),
            ("SESSIONS", str(g["session_count"]), DS.TEXT),
        ]
        gap    = 12
        tile_w = (pw - grade_w - gap * len(stats)) // len(stats)
        tx     = px + grade_w + gap
        for label, value, color in stats:
            self._draw_stat_tile(screen, pygame.Rect(tx, y, tile_w, panel_h),
                                 label, value, color)
            tx += tile_w + gap

        # Missions — capped at 2 to leave room for the focus chip row.
        y = 234
        lbl = self._f_label.render("MISSIONS", True, DS.TEXT3)
        screen.blit(lbl, (px, y))
        y += lbl.get_height() + 10
        chips_top = self._h - self._CHIP_H - 22
        for m in g["missions"][:2]:
            if y > chips_top - 78:
                break
            y = self._draw_mission(screen, m, px, y, pw) + 10

        self._draw_focus_chips(screen, chips_top)

    _CHIP_H = 46

    def _draw_focus_chips(self, screen, y: int) -> None:
        from dashboard.widgets import design_system as DS
        px = self._PAD
        pw = self._w - px * 2
        lbl = self._f_label.render("CHOOSE YOUR FOCUS  ·  TAP ONE", True, DS.TEXT3)
        screen.blit(lbl, (px, y - lbl.get_height() - 4))

        chips = self._focuses
        gap   = 10
        cw    = (pw - gap * (len(chips) - 1)) // len(chips)
        self._chip_rects = []
        x = px
        for c in chips:
            rect = pygame.Rect(x, y, cw, self._CHIP_H)
            selected = (self._selected == c["id"])
            recommended = c.get("recommended")
            pygame.draw.rect(screen, DS.PANEL, rect, border_radius=8)
            if selected:
                border, width = DS.CYAN, 2
            elif recommended:
                border, width = DS.AMBER, 2
            else:
                border, width = DS.BORDER, 1
            pygame.draw.rect(screen, border, rect, width=width, border_radius=8)
            col = (DS.on_panel(DS.CYAN) if selected
                   else DS.on_panel(DS.AMBER) if recommended else DS.TEXT)
            name = self._f_chip.render(c["chip"], True, col)
            # The recommended chip labels itself; otherwise show any data hint.
            sub = "RECOMMENDED" if recommended else c["hint"]
            if sub:
                screen.blit(name, name.get_rect(
                    center=(rect.centerx, rect.centery - 7)))
                sub_col = DS.on_panel(DS.AMBER) if recommended else DS.TEXT3
                sub_s = self._f_caption.render(sub, True, sub_col)
                screen.blit(sub_s, sub_s.get_rect(
                    center=(rect.centerx, rect.centery + 11)))
            else:
                screen.blit(name, name.get_rect(center=rect.center))
            self._chip_rects.append((rect, c["id"]))
            x += cw + gap

    def tap(self, pos) -> bool:
        """Handle a tap on the card. Tapping a focus chip commits it (writes
        the F row via the on_focus callback); any tap dismisses the card
        (a tap outside the chips = no focus, "just drive")."""
        for rect, focus_id in self._chip_rects:
            if rect.collidepoint(pos):
                self._selected = focus_id
                if self._on_focus is not None:
                    try:
                        self._on_focus(focus_id)
                    except Exception:
                        log.exception("focus callback failed")
                break
        return True

    def _draw_grade_panel(self, screen, rect):
        from dashboard.widgets import design_system as DS
        g = self._g
        pygame.draw.rect(screen, DS.PANEL, rect, border_radius=10)
        pygame.draw.rect(screen, DS.BORDER2, rect, width=1, border_radius=10)
        first_visit = not g.get("session_count")
        lbl = self._f_label.render(
            "YOUR FIRST RUN" if first_visit else "IMPROVE GRADE",
            True, DS.TEXT3)
        screen.blit(lbl, (rect.x + 16, rect.y + 12))

        if not g.get("grade_letter"):
            msg = ("Bank a clean lap to set your baseline here — the app "
                   "tracks it from now on"
                   if first_visit else
                   "Last session wasn't graded — drive enough timed laps for "
                   "a grade this time")
            self._draw_wrapped(screen, msg, rect.x + 16, rect.y + 40,
                               rect.width - 32, DS.TEXT3, max_lines=3)
            return

        cur = self._f_letter.render(g["grade_letter"], True, DS.TEXT2)
        cy = rect.y + 30
        screen.blit(cur, (rect.x + 16, cy))
        x = rect.x + 16 + cur.get_width() + 14
        if g.get("next_letter"):
            mid = cur.get_height() // 2 + cy
            pygame.draw.line(screen, DS.TEXT3, (x, mid), (x + 24, mid), 3)
            pygame.draw.polygon(screen, DS.TEXT3,
                                [(x + 24, mid - 6), (x + 24, mid + 6),
                                 (x + 32, mid)])
            nxt = self._f_letter.render(g["next_letter"], True, DS.on_panel(DS.CYAN))
            screen.blit(nxt, (x + 42, cy))

    def _draw_stat_tile(self, screen, rect, label, value, color=None):
        from dashboard.widgets import design_system as DS
        pygame.draw.rect(screen, DS.PANEL, rect, border_radius=10)
        pygame.draw.rect(screen, DS.BORDER, rect, width=1, border_radius=10)
        lbl = self._f_label.render(label, True, DS.TEXT3)
        val = self._f_stat.render(value, True, color or DS.TEXT)
        screen.blit(lbl, (rect.x + 14, rect.y + 14))
        screen.blit(val, (rect.x + 14, rect.centery + 2))

    def _draw_mission(self, screen, mission: dict, x: int, y: int,
                      width: int) -> int:
        from dashboard.widgets import design_system as DS
        kind = _ICON_KIND.get(mission.get("icon", ""), "target")
        self._draw_icon(screen, kind, x + 14, y + 14)
        tx = x + 40
        title = self._f_mission.render(mission["title"], True, DS.AMBER)
        screen.blit(title, (tx, y))
        y2 = y + title.get_height() + 2
        return self._draw_wrapped(screen, mission["detail"], tx, y2,
                                  width - 40, DS.TEXT2, max_lines=2)

    def _draw_icon(self, s, kind: str, cx: int, cy: int):
        from dashboard.widgets import design_system as DS
        if kind == "check":
            pygame.draw.lines(s, DS.GREEN, False,
                              [(cx - 8, cy), (cx - 2, cy + 6), (cx + 8, cy - 7)], 3)
        elif kind == "rewind":
            for off in (0, 9):
                pygame.draw.polygon(s, DS.CYAN,
                                    [(cx + off + 2, cy - 7), (cx + off + 2, cy + 7),
                                     (cx + off - 7, cy)])
        elif kind == "clock":
            pygame.draw.circle(s, DS.CYAN, (cx, cy), 9, 2)
            pygame.draw.line(s, DS.CYAN, (cx, cy), (cx, cy - 5), 2)
            pygame.draw.line(s, DS.CYAN, (cx, cy), (cx + 4, cy + 2), 2)
        elif kind == "ruler":
            pygame.draw.rect(s, DS.TEXT2,
                             pygame.Rect(cx - 10, cy - 5, 20, 10), 2,
                             border_radius=2)
            for i in (-5, 0, 5):
                pygame.draw.line(s, DS.TEXT2, (cx + i, cy - 5), (cx + i, cy - 1), 1)
        elif kind == "trophy":
            c = DS.AMBER
            pygame.draw.circle(s, c, (cx - 8, cy - 5), 4, 2)
            pygame.draw.circle(s, c, (cx + 8, cy - 5), 4, 2)
            pygame.draw.rect(s, c, pygame.Rect(cx - 6, cy - 10, 12, 10),
                             border_bottom_left_radius=5,
                             border_bottom_right_radius=5)
            pygame.draw.rect(s, c, pygame.Rect(cx - 1, cy, 3, 5))
            pygame.draw.rect(s, c, pygame.Rect(cx - 6, cy + 5, 12, 3))
        elif kind == "dial":
            pygame.draw.line(s, DS.TEXT2, (cx - 9, cy), (cx + 9, cy), 2)
            pygame.draw.circle(s, DS.AMBER, (cx + 3, cy), 4)
        elif kind == "warning":
            pygame.draw.polygon(s, DS.AMBER,
                                [(cx, cy - 10), (cx - 9, cy + 7), (cx + 9, cy + 7)], 2)
            pygame.draw.line(s, DS.AMBER, (cx, cy - 3), (cx, cy + 2), 2)
            pygame.draw.circle(s, DS.AMBER, (cx, cy + 5), 1)
        else:  # target
            pygame.draw.circle(s, DS.AMBER, (cx, cy), 9, 2)
            pygame.draw.circle(s, DS.AMBER, (cx, cy), 3)

    def _draw_wrapped(self, screen, text, x, y, width, color,
                      max_lines: int = 3) -> int:
        words, lines, cur = text.split(), [], ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if self._f_body.size(trial)[0] <= width:
                cur = trial
            else:
                lines.append(cur)
                cur = w
                if len(lines) == max_lines:
                    lines[-1] = lines[-1].rstrip(".") + "…"
                    cur = ""
                    break
        if cur:
            lines.append(cur)
        for line in lines:
            surf = self._f_body.render(line, True, color)
            screen.blit(surf, (x, y))
            y += surf.get_height() + 3
        return y
