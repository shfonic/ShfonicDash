"""End-of-session summary screen — key stats, grade and Race Engineer Notes.

Shown when a session file closes (session-type rotation in-app, or exit
back to the menu), gated by the `show_session_summary` setting. The data
path deliberately re-parses the just-written CSV through the shared
sessionlog library instead of reading live state: the numbers on this
screen are then guaranteed to match what the companion app computes from
the same file.

build_summary() is the pure data step (parse -> records index ->
pace facts -> grade -> Race Engineer Notes); SessionSummaryView renders it;
DriveAwayDetector implements the "player started driving the next
session" auto-dismiss; run_summary_screen() is a small blocking loop for
showing the summary on the way back to the game menu, where there is no
telemetry loop to piggyback on.
"""
import logging
import os

import pygame

from core.flip import flip_surface

log = logging.getLogger("summary")

# Auto-dismiss when the car is clearly moving in the next session:
# sustained speed above walking-out-of-the-garage pace.
_DRIVE_SPEED_KMH = 30.0
_DRIVE_FRAMES    = 15          # consecutive frames (~0.5 s at 30 fps)


def build_summary(csv_path: str) -> dict | None:
    """Parse a closed session CSV into everything the summary screen shows.

    Returns None when there is nothing worth summarising (no completed
    laps, unreadable file). Records-index failures degrade gracefully:
    the summary just loses its prior-best references.
    """
    from sessionlog import focus, grading, objectives, records, trackmap
    from sessionlog.pace import (race_engineer_notes_detailed, pace_facts,
                                 track_limit_counts)
    from sessionlog.parser import (format_lap_time, parse, session_label,
                                   tyre_stints)

    try:
        with open(csv_path, encoding="utf-8") as f:
            session = parse(f.read(), os.path.basename(csv_path))
    except (OSError, ValueError) as e:
        log.warning(f"summary: could not parse {csv_path}: {e}")
        return None
    if not session.get("laps"):
        return None

    # Index the finished session and look up the prior best clean lap at
    # the same game / car class / track / session type — the race-pace
    # reference and PB-comparison baseline. The index lives next to the
    # CSVs (logs/.sessions.db) and is disposable.
    prior = None
    history = []           # combo history as of this session (oldest first)
    prev = None            # the single most recent PRIOR session at this combo
    overall = None
    awards = []
    try:
        records.set_cache_dir(os.path.dirname(os.path.abspath(csv_path)))
        records.sync()   # index the finished session + heal any missing rows
        prior_rec = records.prior_best(
            session.get("game"), session.get("car_class"),
            session.get("track"), session.get("session_type"),
            session.get("date"), session.get("filename") or "")
        prior = prior_rec.get("best_lap_time") if prior_rec else None
        # Every session at this combo STRICTLY BEFORE this one (oldest
        # first) — up_to_date/up_to_filename keeps this history-browser-safe:
        # re-opening an old session must never compare it against results
        # that hadn't happened yet (same guard combo_history() documents for
        # grading.trend()). Fed to focus.session_verdict() (which derives the
        # focus's prior references from it); its chronologically LAST entry is
        # "the previous session", used here for the track-limits hotspot
        # comparison (recency, not best-ever).
        current_fn = session.get("filename") or ""
        history = [r for r in records.combo_history(
                       session.get("game"), session.get("car_class"),
                       session.get("track"), session.get("session_type"),
                       up_to_date=session.get("date"),
                       up_to_filename=current_fn)
                   if r.get("filename") != current_fn]
        prev = history[-1] if history else None
        # All-time record at this combo (includes the session just indexed)
        overall = records.overall_best(
            session.get("game"), session.get("car_class"),
            session.get("track"), session.get("session_type"))
        # Career badges this session earned (archive-wide, not per-combo)
        from sessionlog.achievements import session_awards
        awards = session_awards(records.all_sessions(),
                                session.get("filename") or "")
    except Exception as e:                       # sqlite/fs — never fatal
        log.warning(f"summary: records lookup failed: {e}")

    # Track map for location-aware notes ('at Turn 3, before the apex') —
    # tracks/ is a sibling of logs/ (see main.py), same relationship
    # records.set_cache_dir relies on above. Best-effort: no map for this
    # game/track (not recorded yet, or a non-F1 source) just means the
    # notes read as they did before this existed.
    logs_dir = os.path.dirname(os.path.abspath(csv_path))
    track_map = None
    try:
        trackmap.set_tracks_dir(os.path.join(logs_dir, "..", "tracks"))
        track_map = trackmap.find_map(session.get("game"), session.get("track"))
    except Exception as e:                        # fs — never fatal
        log.warning(f"summary: track map lookup failed: {e}")

    # Track-limits hotspot from the PREVIOUS session (`prev`, above) — the
    # same corner sessionlog.goals/core.pre_session would have flagged as
    # "watch your line" before this session started (re-derived here, not
    # persisted, so the two can never drift apart). Needs a full re-parse of
    # the prior CSV: corner-level detail isn't indexed, only the events list
    # in a fully parsed session carries it (same pattern as
    # history_browser._open_detail).
    prior_track_limit_hotspot = None
    if prev and track_map:
        try:
            prev_path = os.path.join(logs_dir, prev["filename"])
            with open(prev_path, encoding="utf-8") as f:
                prev_session = parse(f.read(), prev["filename"])
            counts = track_limit_counts(prev_session.get("events") or [], track_map)
            if counts:
                label, n = max(counts.items(), key=lambda kv: kv[1])
                if n >= 2:
                    prior_track_limit_hotspot = {"label": label, "count": n}
        except (OSError, ValueError) as e:
            log.warning(f"summary: prior-session track-limit lookup failed: {e}")

    facts = pace_facts(session)
    sf = grading.session_facts(session)
    grade = grading.grade(sf, prior)

    # Focus verdict: how the session tracked against the driver's chosen
    # focus (F row). None when no focus was set or it was "just drive".
    # session_verdict() derives the prior references from the same combo
    # history, so the companion's session detail shows identical numbers.
    focus_id = (session.get("focus") or "").strip()
    focus_verdict = focus.session_verdict(session, sf, history, prior_best=prior)
    # Detailed notes carry per-note locations (contact / track-limits) for the
    # mini-map thumbnails; the plain string list stays the `text` fields.
    notes_detailed = race_engineer_notes_detailed(
        session, facts, prior, track_map=track_map,
        focus_id=focus_id, focus_verdict=focus_verdict,
        prior_track_limit_hotspot=prior_track_limit_hotspot)
    notes = [n["text"] for n in notes_detailed]

    # Objective outcomes: how each pre-session goal (O rows) turned out. The
    # corner objectives need this session's per-corner warning counts (track
    # limits) and line deviations.
    corner_warnings = (track_limit_counts(session.get("events") or [], track_map)
                       if track_map else None)
    from sessionlog.lines import corner_deviations
    corner_line_dev = (corner_deviations(session, track_map)
                       if track_map else None)
    # LEARN_TRACK (first-visit) objective is scored from the ordered session's
    # pace trend — did the clean laps come down as the driver learned it.
    from sessionlog.progression import progression_facts
    prog_facts = progression_facts(session)
    objective_outcomes = objectives.evaluate_all(
        session.get("objectives") or [], sf, corner_warnings, corner_line_dev,
        prog_facts)

    # All-time record line (companion parity): magenta "this session"
    # when this session holds the record, else purple record + gap.
    ob_time = overall.get("best_lap_time") if overall else None
    fastest = facts.get("fastest")
    overall_holds = bool(ob_time is not None and (
        overall.get("filename") == session.get("filename")
        or (fastest is not None and fastest <= ob_time)))

    # Z-row stats, with fallbacks computed from the lap data — a file cut
    # short (crash, power loss) has laps but no Z rows.
    zsum  = session.get("summary") or {}
    clean = facts.get("clean_laps") or []
    valid = facts.get("valid_times") or []
    avg_clean = zsum.get("avg_clean_lap")
    if avg_clean is None and valid:
        avg_clean = sum(valid) / len(valid)
    std_dev = zsum.get("std_dev")
    if std_dev is None and len(valid) >= 2:
        import statistics
        std_dev = statistics.stdev(valid)
    return {
        "filename":   session.get("filename", ""),
        "label":      (session_label(session) or "session").replace("_", " ").upper(),
        "track":      session.get("track") or "",
        "car":        session.get("car") or session.get("car_class_name") or "",
        "game_name":  session.get("game_name") or "",
        "date":       session.get("date"),
        "laps_total": len(session["laps"]),
        "laps_clean": len(clean),
        # Tyre usage, in running order: [("Soft", 8), ("Medium", 4)].
        # Empty when no lap carries a compound (PC2/older files).
        "stints":     [(s["compound"], len(s["laps"]))
                       for s in tyre_stints(session) if s["compound"]],
        "fastest":    facts.get("fastest"),
        "theo":       facts.get("theo"),
        "avg_clean":  avg_clean,
        "std_dev":    std_dev,
        "prior_best": prior,
        "overall_best":  ob_time,
        "overall_holds": overall_holds,
        "grade":      grade,
        "focus_verdict": focus_verdict,
        "objectives": objective_outcomes,
        "notes":      notes,
        "notes_detailed": notes_detailed,
        "track_map":  track_map,
        "awards":     awards,
        "fmt":        format_lap_time,
    }


class DriveAwayDetector:
    """Dismiss trigger: the player is driving the next session.

    update() returns True once speed has stayed above the threshold for
    `frames` consecutive updates — brief blips (grid teleports, replay
    scrubbing) don't dismiss the summary.
    """

    def __init__(self, speed_kmh: float = _DRIVE_SPEED_KMH,
                 frames: int = _DRIVE_FRAMES):
        self._speed_kmh = speed_kmh
        self._frames    = frames
        self._count     = 0

    def update(self, speed_kmh: float) -> bool:
        if speed_kmh > self._speed_kmh:
            self._count += 1
        else:
            self._count = 0
        return self._count >= self._frames


def _award_banner(awards) -> str | None:
    """One-line badge celebration from session_awards(): the most notable
    award (they arrive sorted), with a count of any others."""
    if not awards:
        return None
    a = awards[0]
    name = a["name"].upper()
    if a["kind"] == "unlocked":
        line = f"NEW BADGE — {name}"
    elif a["kind"] == "upgraded":
        line = f"{name} ×{a['count']} — {(a['tier'] or '').upper()}"
    else:
        line = f"{name} ×{a['count']}"
    if len(awards) > 1:
        line += f"  (+{len(awards) - 1} MORE)"
    return line


class SessionSummaryView:
    """Full-screen 800x480 renderer for a build_summary() dict."""

    _PAD = 28

    def __init__(self, summary: dict, width: int = 800, height: int = 480,
                 caption: str = "SESSION SUMMARY"):
        from dashboard.widgets.fonts import load_display, load_ui
        self._s = summary
        self._w, self._h = width, height
        self._caption = caption
        self._f_caption = load_ui(12)
        self._f_label   = load_ui(12)
        self._f_title   = load_ui(22)
        self._f_sub     = load_ui(14)
        self._f_stat    = load_ui(24)
        self._f_body    = load_ui(14)
        self._f_letter  = load_display(56)
        self._f_letter2 = load_ui(20)

    # ── drawing ──────────────────────────────────────────────────────────

    def render(self, screen: pygame.Surface) -> None:
        from dashboard.widgets import design_system as DS
        s  = self._s
        px = self._PAD
        pw = self._w - px * 2
        fmt = s["fmt"]

        screen.fill(DS.BG)

        # Header: caption + session badge left, dismiss hint right
        y = 20
        cap = self._f_caption.render(self._caption, True, DS.TEXT3)
        screen.blit(cap, (px, y))
        badge = self._f_caption.render(s["label"], True, DS.on_panel(DS.CYAN))
        screen.blit(badge, (px + cap.get_width() + 16, y))
        hint = self._f_caption.render("TAP TO DISMISS", True, DS.TEXT3)
        screen.blit(hint, hint.get_rect(topright=(self._w - px, y)))

        # Session card: track / car / date / laps
        y = 44
        title_bits = [b for b in (s["track"], s["car"]) if b]
        title = self._f_title.render("  ·  ".join(title_bits) or s["game_name"]
                                     or "Session", True, DS.TEXT)
        screen.blit(title, (px, y))
        when = s["date"].strftime("%d %b %Y  %H:%M") if s["date"] else ""
        sub  = (f"{when}    {s['laps_total']} laps"
                f" ({s['laps_clean']} clean)")
        sub_y = y + title.get_height() + 6
        sub_s = self._f_sub.render(sub.strip(), True, DS.TEXT3)
        screen.blit(sub_s, (px, sub_y))

        # Tyres used, in running order — chip + lap count per stint
        if s.get("stints"):
            from dashboard.widgets.tyre_chip import draw_chip
            cx = px + sub_s.get_width() + 20
            cy = sub_y + sub_s.get_height() // 2
            for compound, n in s["stints"][:6]:
                cx += draw_chip(screen, self._f_caption, compound, cx, cy) + 4
                cnt = self._f_sub.render(f"×{n}", True, DS.TEXT3)
                screen.blit(cnt, (cx, sub_y))
                cx += cnt.get_width() + 12

        # All-time record at this combo (companion parity), right-aligned
        if s.get("overall_best") is not None:
            if s.get("overall_holds"):
                txt, color = "OVERALL BEST — THIS SESSION", DS.on_panel(DS.MAGENTA)
            else:
                gap = (f"  +{s['fastest'] - s['overall_best']:.3f}"
                       if s["fastest"] is not None else "")
                txt   = f"OVERALL  {fmt(s['overall_best'])}{gap}"
                color = DS.on_panel(DS.PURPLE)
            ob = self._f_sub.render(txt, True, color)
            screen.blit(ob, ob.get_rect(topright=(self._w - px, sub_y)))

        # Career badge earned this session — the cockpit's moment.
        # Most notable award only; the full gallery lives on the phone.
        line = _award_banner(s.get("awards"))
        if line:
            aw = self._f_sub.render(line, True, DS.on_panel(DS.AMBER))
            screen.blit(aw, aw.get_rect(topright=(self._w - px, sub_y + 22)))

        # Focus verdict banner — how the session tracked against the driver's
        # chosen focus. Shifts the blocks below down only when present, so a
        # focus-less session keeps the original layout exactly.
        fv = s.get("focus_verdict")
        panel_top = 122
        if fv:
            self._draw_focus_banner(screen, px, 124, pw, fv)
            panel_top = 160

        # Grade panel (left) + stat tiles (right)
        y = panel_top
        panel_h = 108
        grade_w = 258   # wide enough for the RACE DISCIPLINE label
        self._draw_grade_panel(screen, pygame.Rect(px, y, grade_w, panel_h))
        # Value colours follow the companion's flag language: magenta =
        # session best, green = theoretical best.
        stats = [
            ("FASTEST",     fmt(s["fastest"]) if s["fastest"] else "—",
             DS.on_panel(DS.MAGENTA) if s["fastest"] else DS.TEXT),
            ("THEORETICAL", fmt(s["theo"]) if s["theo"] else "—",
             DS.on_panel(DS.GREEN) if s["theo"] else DS.TEXT),
            ("AVG CLEAN",   fmt(s["avg_clean"]) if s["avg_clean"] else "—",
             DS.TEXT),
            ("CONSISTENCY", f"±{s['std_dev']:.3f}s" if s["std_dev"] else "—",
             DS.TEXT),
        ]
        gap    = 12
        tile_w = (pw - grade_w - gap * len(stats)) // len(stats)
        tx     = px + grade_w + gap
        for label, value, color in stats:
            self._draw_stat_tile(screen, pygame.Rect(tx, y, tile_w, panel_h),
                                 label, value, color)
            tx += tile_w + gap

        # Explanation + focus (from grading), then Race Engineer Notes
        y = panel_top + panel_h + 18
        g = s["grade"]
        if g:
            y = self._draw_wrapped(screen, g.get("explanation", ""),
                                   px, y, pw, DS.TEXT2, max_lines=3)
            focus = g.get("focus")
            if focus:
                y = self._draw_wrapped(screen, f"FOCUS:  {focus}",
                                       px, y + 4, pw, DS.on_panel(DS.AMBER), max_lines=2)
            y += 10

        # Compact goals strip — how the session's tracked objectives turned
        # out, one glanceable row. Sits just above the notes so it only eats
        # into the flexible bottom region (a note or two), not the layout.
        y = self._draw_objectives_strip(screen, px, y, pw)

        notes = (s.get("notes_detailed")
                 or [{"text": t, "locations": []} for t in s["notes"]])[:3]
        if notes:
            from core import track_thumb
            from sessionlog import trackmap
            track_map = s.get("track_map")

            def _geom(loc):
                return trackmap.crop_geometry(track_map, loc.get("distance"))

            lbl = self._f_label.render("RACE ENGINEER NOTES", True, DS.TEXT3)
            screen.blit(lbl, (px, y))
            y += lbl.get_height() + 8
            for note in notes:
                if y > self._h - 40:
                    break
                bullet = self._f_body.render("·", True, DS.on_panel(DS.CYAN))
                screen.blit(bullet, (px, y))
                y = self._draw_wrapped(screen, note["text"], px + 16, y,
                                       pw - 16, DS.TEXT2, max_lines=3) + 6
                # Mini-map thumbnails for located notes — only when there is
                # vertical room (the summary never scrolls).
                locs = note.get("locations") or []
                if locs and track_map and y < self._h - (
                        track_thumb.THUMB_H + track_thumb.LABEL_H + 8):
                    # Summary never scrolls — keep to a single row that fits.
                    y = track_thumb.draw_row(screen, px + 16, y, locs, _geom,
                                             font=self._f_label,
                                             avail_w=pw - 16, max_rows=1) + 6

    def _draw_grade_panel(self, screen, rect):
        from dashboard.widgets import design_system as DS
        s = self._s
        g = s["grade"]
        pygame.draw.rect(screen, DS.PANEL, rect, border_radius=10)
        pygame.draw.rect(screen, DS.BORDER2, rect, width=1, border_radius=10)

        lbl = self._f_label.render("OVERALL", True, DS.TEXT3)
        screen.blit(lbl, (rect.x + 16, rect.y + 12))

        if not g:
            # Ungraded: no letter / right column — just say why, wrapped
            # inside the panel so nothing overlaps or clips.
            self._draw_wrapped(screen, "Not graded — too few timed laps",
                               rect.x + 16, rect.y + 44,
                               rect.width - 32, DS.TEXT3, max_lines=3)
            return

        let_s = self._f_letter.render(g["letter"], True, DS.on_panel(DS.CYAN))
        screen.blit(let_s, (rect.x + 16, rect.y + 26))

        # Right column: secondary grade (session-aware label) + pace rating,
        # two evenly spaced blocks inside the 108px panel.
        rx = rect.x + 116
        ry = rect.y + 10
        if g.get("cleanliness"):
            c = g["cleanliness"]
            l1 = self._f_label.render(c.get("label", "Cleanliness").upper(),
                                      True, DS.TEXT3)
            v1 = self._f_letter2.render(c["letter"], True, DS.TEXT)
            screen.blit(l1, (rx, ry))
            screen.blit(v1, (rx, ry + 15))
        if g.get("pace_rating") is not None:
            pl = "RACE PACE" if g.get("pace_kind") == "race" else "PACE RATING"
            l2 = self._f_label.render(pl, True, DS.TEXT3)
            v2 = self._f_letter2.render(f"{g['pace_rating']}", True, DS.TEXT)
            screen.blit(l2, (rx, ry + 44))
            screen.blit(v2, (rx, ry + 59))

    def _draw_stat_tile(self, screen, rect, label, value, color=None):
        from dashboard.widgets import design_system as DS
        pygame.draw.rect(screen, DS.PANEL, rect, border_radius=10)
        pygame.draw.rect(screen, DS.BORDER, rect, width=1, border_radius=10)
        lbl = self._f_label.render(label, True, DS.TEXT3)
        val = self._f_stat.render(value, True, color or DS.TEXT)
        screen.blit(lbl, (rect.x + 14, rect.y + 14))
        screen.blit(val, (rect.x + 14, rect.centery + 2))

    def _draw_focus_banner(self, screen, x, y, w, verdict) -> None:
        """One-line strip: "YOU CHOSE {title} — {headline}" with a left accent
        bar coloured by outcome (green met / amber missed / cyan neutral)."""
        from dashboard.widgets import design_system as DS
        met    = verdict.get("met")
        accent = (DS.GREEN if met is True
                  else DS.AMBER if met is False else DS.CYAN)
        h = 30
        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(screen, DS.PANEL, rect, border_radius=6)
        pygame.draw.rect(screen, DS.BORDER, rect, width=1, border_radius=6)
        pygame.draw.rect(screen, accent, pygame.Rect(x, y, 5, h),
                         border_top_left_radius=6, border_bottom_left_radius=6)
        cap = self._f_label.render(
            "YOU CHOSE  " + (verdict.get("title") or ""), True, DS.TEXT3)
        cy = y + (h - cap.get_height()) // 2
        screen.blit(cap, (x + 16, cy))
        hx = x + 16 + cap.get_width() + 14
        head = self._f_sub.render(
            self._fit(verdict.get("headline") or "", self._f_sub,
                      x + w - 14 - hx), True, DS.on_panel(accent))
        screen.blit(head, (hx, y + (h - head.get_height()) // 2))

    def _draw_objectives_strip(self, screen, x, y, w) -> int:
        """One compact row — "GOALS  ✓ clean run  ✗ no flashbacks  · beat time"
        — for the fixed end-of-session summary, where there's no room for the
        full per-goal block the scrollable history detail shows. A no-op
        (returns y unchanged) when the session had no objectives. Pills that
        would overflow the width are dropped rather than wrapped."""
        from dashboard.widgets import design_system as DS
        from sessionlog import objectives as _obj
        outcomes = self._s.get("objectives") or []
        if not outcomes:
            return y
        lbl = self._f_label.render("GOALS", True, DS.TEXT3)
        screen.blit(lbl, (x, y + 2))
        cx = x + lbl.get_width() + 14
        limit = x + w
        for o in outcomes:
            met = o.get("met")
            accent = (DS.GREEN if met is True
                      else DS.AMBER if met is False else DS.CYAN)
            cap = self._f_sub.render(_obj.short_label(o), True, DS.on_panel(accent))
            pill_w = 20 + cap.get_width() + 16
            if cx + pill_w > limit:
                break
            gy = y + self._f_label.get_height() // 2 + 1
            if met is True:
                pygame.draw.lines(screen, accent, False,
                                  [(cx, gy), (cx + 4, gy + 4), (cx + 11, gy - 5)], 2)
            elif met is False:
                pygame.draw.line(screen, accent, (cx, gy - 4), (cx + 10, gy + 5), 2)
                pygame.draw.line(screen, accent, (cx + 10, gy - 4), (cx, gy + 5), 2)
            else:
                pygame.draw.circle(screen, accent, (cx + 5, gy), 3)
            screen.blit(cap, (cx + 18, y))
            cx += pill_w
        return y + lbl.get_height() + 10

    def _draw_objectives(self, screen, x, y, w) -> int:
        """The session's tracked objectives (O rows) and how each turned out —
        a ✓ met / ✗ missed / · still-open glyph, the headline, and the detail.
        Returns the new y. A no-op (returns y unchanged) when the session had
        no objectives. Used by the scrollable history detail view; the fixed
        end-of-session summary shows only the headline focus banner for space.
        """
        from dashboard.widgets import design_system as DS
        outcomes = self._s.get("objectives") or []
        if not outcomes:
            return y
        lbl = self._f_label.render("SESSION GOALS", True, DS.TEXT3)
        screen.blit(lbl, (x, y))
        y += lbl.get_height() + 8
        for o in outcomes:
            met = o.get("met")
            accent = (DS.GREEN if met is True
                      else DS.AMBER if met is False else DS.CYAN)
            gy = y + self._f_sub.get_height() // 2
            if met is True:                       # check
                pygame.draw.lines(screen, accent, False,
                                  [(x + 2, gy), (x + 7, gy + 5), (x + 15, gy - 6)], 3)
            elif met is False:                    # cross
                pygame.draw.line(screen, accent, (x + 2, gy - 6), (x + 14, gy + 6), 3)
                pygame.draw.line(screen, accent, (x + 14, gy - 6), (x + 2, gy + 6), 3)
            else:                                 # neutral dot
                pygame.draw.circle(screen, accent, (x + 8, gy), 4)
            head = self._f_sub.render(o.get("headline") or "", True,
                                      DS.on_panel(accent))
            screen.blit(head, (x + 26, y))
            yy = y + head.get_height() + 2
            detail = o.get("detail") or ""
            if detail:
                yy = self._draw_wrapped(screen, detail, x + 26, yy,
                                        w - 26, DS.TEXT2, max_lines=2)
            y = yy + 8
        return y + 4

    def _fit(self, text: str, font, width: int) -> str:
        """Truncate text with an ellipsis to fit within width px."""
        if font.size(text)[0] <= width:
            return text
        while text and font.size(text + "…")[0] > width:
            text = text[:-1]
        return text + "…"

    def _draw_wrapped(self, screen, text, x, y, width, color,
                      max_lines: int = 3) -> int:
        """Render word-wrapped text; returns the y below the last line."""
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


def run_summary_screen(screen: pygame.Surface, summary: dict,
                       flip: bool = False, fps: int = 30) -> None:
    """Blocking summary display for the exit-to-menu path.

    Returns on tap / ESC / window close. There is no telemetry here, so
    the drive-away auto-dismiss does not apply — the next thing the user
    sees is the game menu they asked for.
    """
    view  = SessionSummaryView(summary, screen.get_width(), screen.get_height())
    clock = pygame.time.Clock()
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return
            if event.type == pygame.MOUSEBUTTONUP:
                return
        view.render(screen)
        flip_surface(screen, flip)
        pygame.display.flip()
        clock.tick(fps)
