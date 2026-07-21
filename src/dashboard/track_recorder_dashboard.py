"""Live track-recorder view.

A full-screen top-down plot that draws the line as you drive it, phase by phase,
with big touch buttons for ACCEPT / RE-DRIVE / FINISH / ADD PIT LANE / SAVE. It
stands in for the DashboardManager while recorder mode is armed, so it exposes
the same ``update`` / ``render`` / ``handle_event`` / ``reset_touch`` surface the
App drives.

It renders the ``TrackRecorder``'s exposed state — it holds no capture logic of
its own.
"""

import json
import logging
import math
import os

import pygame

from core.track_recorder import Phase, State, TrackMap, TrackRecorder, _slug


def _deg(radians: float) -> float:
    """Heading in [0, 360) degrees for the debug readout."""
    return math.degrees(radians) % 360.0

log = logging.getLogger("track_recorder")

# Fixed palette — this is a utility screen, deliberately independent of the
# dashboard theme so it always reads the same while recording.
_BG        = (10, 12, 16)
_BANNER_BG = (18, 21, 27)
_TEXT      = (236, 240, 245)
_SUBTLE    = (150, 158, 170)
_LEFT_COL  = (90, 150, 245)     # left edge
_RIGHT_COL = (245, 150, 90)     # right edge
_RACE_COL  = (120, 230, 140)    # accepted racing line
_ATTEMPT   = (60, 96, 70)       # faint racing-line attempts
_CURRENT   = (255, 232, 90)     # the line being driven right now
_PIT_COL   = (200, 120, 230)    # pit lane
_SF_COL    = (240, 240, 240)    # start/finish line
_CAR       = (255, 70, 70)
_SECTOR    = (235, 205, 70)

_STEP_DONE    = (120, 230, 140)
_STEP_CURRENT = (255, 232, 90)
_STEP_PENDING = (110, 118, 130)

_BANNER_H   = 52
_PROGRESS_H = 34
_BTN_H      = 66
_GRID_BTN_H = 58        # DONE-screen edit grid (two rows)
_GRID_GAP   = 12
_MARGIN     = 16


class TrackRecorderDashboard:

    def __init__(self, width: int, height: int, tracks_dir: str = "",
                 recorder: TrackRecorder = None, author: str = ""):
        self.width = width
        self.height = height
        self._tracks_dir = tracks_dir
        self.recorder = recorder or TrackRecorder(author=author)
        self._data = None
        self._notes: list = []          # recent event strings, newest last
        self._note_ttl = 0              # frames the current note stays up
        self._saved_path = ""
        self._buttons: list = []        # [(rect, action)] rebuilt each render
        self._show_debug = True         # live telemetry readout (tap it to hide)
        self._debug_rect = None
        # Existing-track prompt: once the track name is known and a matching file
        # exists, offer EDIT (load it) or RE-RECORD (start fresh) before anything
        # is captured.
        self._existing_map = None       # TrackMap found on disk, awaiting a choice
        self._existing_path = ""
        self._existing_resolved = False  # the prompt has been answered / dismissed
        pygame.font.init()
        self._font_lg = pygame.font.SysFont(None, 34)
        self._font_md = pygame.font.SysFont(None, 26)
        self._font_sm = pygame.font.SysFont(None, 22)
        self._font_dbg = pygame.font.SysFont("monospace", 15)

    # ── App-facing surface (mirrors DashboardManager) ─────────────────────

    def update(self, data) -> None:
        self._data = data
        notes = self.recorder.update(data)
        if notes:
            self._notes = notes
            self._note_ttl = 90        # ~3 s at 30 fps
        elif self._note_ttl > 0:
            self._note_ttl -= 1
        self._maybe_find_existing()

    def _maybe_find_existing(self) -> None:
        """Once the track name is known and nothing is captured yet, look for a
        saved map so the driver can choose to edit it rather than start over."""
        if self._existing_resolved or self._existing_map is not None:
            return
        rec = self.recorder
        if not (self._tracks_dir and rec.is_untouched
                and rec.track_name and rec.game):
            return
        fname = f"{_slug(rec.game)}_{_slug(rec.track_name)}.json"
        path = os.path.join(self._tracks_dir, fname)
        if not os.path.isfile(path):
            return
        try:
            with open(path, encoding="utf-8") as fh:
                self._existing_map = TrackMap.from_dict(json.load(fh))
                self._existing_path = path
        except Exception:
            log.exception("failed to read existing track map %s", path)
            self._existing_resolved = True   # don't retry a broken file every frame

    def handle_event(self, event) -> None:
        if event.type == pygame.MOUSEBUTTONUP:
            self._on_tap(event.pos)

    def reset_touch(self) -> None:
        pass

    def set_session(self, session) -> None:
        pass

    # ── Interaction ───────────────────────────────────────────────────────

    def _on_tap(self, pos) -> None:
        if self._debug_rect is not None and self._debug_rect.collidepoint(pos):
            self._show_debug = not self._show_debug
            return
        for rect, action in self._buttons:
            if rect.collidepoint(pos):
                self._do(action)
                return

    def _do(self, action: str) -> None:
        rec = self.recorder
        if action == "accept":
            rec.accept()
        elif action == "redo":
            rec.redo()
        elif action == "finish":
            rec.finish_racing()
        elif action == "start":
            rec.arm()
        elif action == "cancel":
            rec.cancel_arm()
        elif action == "add_pit":
            rec.start_pit_lane()
        elif action == "redrive_left":
            rec.redrive(Phase.LEFT)
        elif action == "redrive_right":
            rec.redrive(Phase.RIGHT)
        elif action == "redrive_racing":
            rec.redrive(Phase.RACING)
        elif action == "redrive_pit":
            rec.redrive_pit()
        elif action == "discard":
            rec.discard_all()
            self._saved_path = ""
            self._notes = []
            self._note_ttl = 0
        elif action == "edit_existing":
            if self._existing_map is not None:
                rec.load_existing(self._existing_map)
            self._existing_resolved = True
        elif action == "rerecord":
            self._existing_resolved = True
        elif action == "restart":
            rec.restart()
            self._saved_path = ""
            self._notes = []
            self._note_ttl = 0
        elif action == "save":
            self._save()

    def _save(self) -> None:
        try:
            self._saved_path = self.recorder.save(self._tracks_dir)
            log.info(f"Saved track map to {self._saved_path}")
        except Exception:
            log.exception("failed to save track map")

    # ── Projection ────────────────────────────────────────────────────────

    def _all_points(self) -> list:
        rec = self.recorder
        pts = []
        pts += rec.left_edge
        pts += rec.right_edge
        pts += rec.racing_line
        for a in rec.attempt_lines:
            pts += a
        pts += rec.current_line
        pts += rec.pit_lane
        if rec.sf_line.get("pos"):
            pts.append(tuple(rec.sf_line["pos"]))
        return pts

    def _make_projector(self):
        """Return a function mapping world (x, z) → screen (px, py), auto-fit to
        everything captured so far, aspect-preserving, north-up. X is negated
        (like track_viewer.html's `sx`) so the live trace matches the real
        driving direction instead of appearing mirrored."""
        pts = self._all_points()
        top = _BANNER_H + _PROGRESS_H
        area_x = _MARGIN
        area_y = top + _MARGIN
        area_w = self.width - 2 * _MARGIN
        area_h = self.height - area_y - self._bottom_reserved()
        if len(pts) < 2:
            return None
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        minx, maxx = min(xs), max(xs)
        minz, maxz = min(zs), max(zs)
        span_x = max(maxx - minx, 1.0)
        span_z = max(maxz - minz, 1.0)
        scale = min(area_w / span_x, area_h / span_z)
        # Centre the drawing within the plot area.
        off_x = area_x + (area_w - span_x * scale) / 2
        off_y = area_y + (area_h - span_z * scale) / 2
        cx, cz = maxx, maxz     # top-right world corner maps near plot origin (x negated)

        def project(x, z):
            px = off_x + (cx - x) * scale   # negate x to match real driving direction
            py = off_y + (cz - z) * scale   # invert z so north is up
            return int(px), int(py)

        return project

    # ── Render ────────────────────────────────────────────────────────────

    def _show_prompt(self) -> bool:
        return self._existing_map is not None and not self._existing_resolved

    def _bottom_reserved(self) -> int:
        """Vertical space (incl. bottom margin) the button area needs, so the
        map plot fits above it. The DONE edit grid is two rows tall."""
        if self.recorder.state == State.DONE and not self._saved_path:
            return 2 * _GRID_BTN_H + _GRID_GAP + 2 * _MARGIN
        return _BTN_H + 2 * _MARGIN

    def render(self, surface) -> None:
        surface.fill(_BG)
        self._buttons = []
        project = self._make_projector()
        if project is not None:
            self._draw_track(surface, project)
        self._draw_banner(surface)
        self._draw_progress(surface)
        self._draw_debug(surface)
        if self._show_prompt():
            self._draw_existing_prompt(surface)
        else:
            self._draw_buttons(surface)

    def _poly(self, surface, project, pts, colour, width=2):
        if len(pts) < 2:
            return
        screen_pts = [project(x, z) for x, z in pts]
        pygame.draw.lines(surface, colour, False, screen_pts, width)

    def _draw_track(self, surface, project) -> None:
        rec = self.recorder
        # Faint racing-line attempts first (background).
        for a in rec.attempt_lines:
            self._poly(surface, project, a, _ATTEMPT, 1)
        self._poly(surface, project, rec.left_edge, _LEFT_COL, 2)
        self._poly(surface, project, rec.right_edge, _RIGHT_COL, 2)
        self._poly(surface, project, rec.racing_line, _RACE_COL, 3)
        self._poly(surface, project, rec.pit_lane, _PIT_COL, 3)

        # The line being driven / under review — brightest.
        if rec.state in (State.RECORDING, State.REVIEW):
            self._poly(surface, project, rec.current_line, _CURRENT, 2)

        # Sector boundary dots.
        for m in rec.sector_marks:
            px, py = project(*m["pos"])
            pygame.draw.circle(surface, _SECTOR, (px, py), 5)

        # Start/finish marker.
        if rec.sf_line.get("pos"):
            px, py = project(*rec.sf_line["pos"])
            pygame.draw.circle(surface, _SF_COL, (px, py), 6, 2)
            label = self._font_sm.render("S/F", True, _SF_COL)
            surface.blit(label, (px + 8, py - 8))

        # The car.
        if self._data is not None and getattr(self._data, "pos_valid", False):
            px, py = project(self._data.pos_x, self._data.pos_z)
            pygame.draw.circle(surface, _CAR, (px, py), 6)

    def _draw_banner(self, surface) -> None:
        pygame.draw.rect(surface, _BANNER_BG, (0, 0, self.width, _BANNER_H))
        rec = self.recorder
        status = rec.status_text
        # Flash the most recent event note over the status if fresh — but never
        # over the completion screen, where the standing status matters.
        if self._note_ttl > 0 and self._notes and rec.state != State.DONE:
            status = self._notes[-1]
        surface.blit(self._font_lg.render(status, True, _TEXT), (_MARGIN, 10))

        track = rec.track_name or "UNKNOWN TRACK"
        info = track
        if rec.state in (State.RECORDING,):
            info = f"{track}   ·   {rec.point_count} pts"
        label = self._font_sm.render(info, True, _SUBTLE)
        surface.blit(label, (self.width - label.get_width() - _MARGIN, 16))

    def _draw_progress(self, surface) -> None:
        """Phase checklist (LEFT LINE → RIGHT LINE → RACING LINE → PIT) with a
        RESTART button, so it's always clear what's captured and what's next."""
        y = _BANNER_H
        pygame.draw.rect(surface, _BANNER_BG, (0, y, self.width, _PROGRESS_H))
        cy = y + _PROGRESS_H // 2

        # RESTART button, right-aligned in the strip.
        btn_w, btn_h = 92, _PROGRESS_H - 10
        rrect = pygame.Rect(self.width - btn_w - _MARGIN, y + 5, btn_w, btn_h)
        pygame.draw.rect(surface, (70, 50, 50), rrect, border_radius=6)
        pygame.draw.rect(surface, (150, 90, 90), rrect, 1, border_radius=6)
        rt = self._font_sm.render("RESTART", True, _TEXT)
        surface.blit(rt, rt.get_rect(center=rrect.center))
        self._buttons.append((rrect, "restart"))

        # Phase chips, left to right, separated by ">".
        x = _MARGIN
        phases = self.recorder.phases
        for i, (label, state) in enumerate(phases):
            colour = {"done": _STEP_DONE, "current": _STEP_CURRENT,
                      "pending": _STEP_PENDING}[state]
            chip = self._font_sm.render(label, True, colour)
            if x + chip.get_width() > rrect.left - 20:
                break
            surface.blit(chip, (x, cy - chip.get_height() // 2))
            x += chip.get_width()
            if i < len(phases) - 1:
                sep = self._font_sm.render("  >  ", True, _SUBTLE)
                surface.blit(sep, (x, cy - sep.get_height() // 2))
                x += sep.get_width()

    def _draw_buttons(self, surface) -> None:
        rec = self.recorder
        specs = []   # (label, action, colour)

        if self._saved_path:
            self._draw_footer_text(surface, "SAVED  ·  hold to return to menu")
            return

        if rec.state == State.DONE:
            self._draw_done_grid(surface)
            return

        if rec.state == State.REVIEW:
            specs.append(("RE-DRIVE", "redo", (120, 70, 70)))
            if rec.phase == Phase.RACING and rec.can_finish_racing:
                specs.append(("FINISH", "finish", (70, 110, 90)))
            specs.append(("ACCEPT", "accept", (70, 120, 90)))
        elif rec.can_start:
            specs.append(("START", "start", (70, 120, 90)))
        elif rec.is_armed:
            specs.append(("CANCEL", "cancel", (120, 70, 70)))
        else:
            # Recording / pit / no telemetry — driving, no buttons. Show a hint.
            if rec.phase == Phase.PIT:
                if rec.state == State.ARMING:
                    hint = ("Leave the pits first, then drive a lap into the pit entry"
                            if rec.pit_arming_in_box
                            else "Drive into the pits to begin")
                else:
                    hint = ("Keep the pit limiter ON until you rejoin the track "
                            "(pit assist off)")
            elif rec.state == State.RECORDING:
                hint = "Recording — cross the start/finish line to finish the lap"
            else:
                hint = "Waiting for telemetry…"
            self._draw_footer_text(surface, hint)
            return

        if not specs:
            return
        gap = _MARGIN
        n = len(specs)
        total_w = self.width - 2 * _MARGIN
        btn_w = (total_w - gap * (n - 1)) // n
        y = self.height - _BTN_H - _MARGIN
        x = _MARGIN
        for label, action, colour in specs:
            rect = pygame.Rect(x, y, btn_w, _BTN_H)
            pygame.draw.rect(surface, colour, rect, border_radius=8)
            pygame.draw.rect(surface, _TEXT, rect, 1, border_radius=8)
            txt = self._font_md.render(label, True, _TEXT)
            surface.blit(txt, txt.get_rect(center=rect.center))
            self._buttons.append((rect, action))
            x += btn_w + gap

    def _draw_done_grid(self, surface) -> None:
        """The completion / edit screen: re-drive any single line, add/replace the
        pit lane, discard everything, or save. Available for a freshly-recorded
        map as well as one loaded from disk, so a bad line can be fixed without
        redoing the whole circuit."""
        rec = self.recorder
        pit_label = "REPLACE PIT" if rec.has_pit else "ADD PIT LANE"
        racing_label = "RE-DRIVE RACING" if rec.has_racing_line else "ADD RACING LINE"
        grid = [
            ("RE-DRIVE LEFT",   "redrive_left",   (40, 70, 120)),
            ("RE-DRIVE RIGHT",  "redrive_right",  (120, 80, 40)),
            (racing_label,      "redrive_racing", (45, 95, 60)),
            (pit_label,         "redrive_pit",    (90, 70, 110)),
            ("DISCARD ALL",     "discard",        (120, 70, 70)),
            ("SAVE TRACK",      "save",           (70, 120, 90)),
        ]
        cols = 3
        total_w = self.width - 2 * _MARGIN
        btn_w = (total_w - _GRID_GAP * (cols - 1)) // cols
        grid_h = 2 * _GRID_BTN_H + _GRID_GAP
        y0 = self.height - grid_h - _MARGIN
        for i, (label, action, colour) in enumerate(grid):
            r, c = divmod(i, cols)
            x = _MARGIN + c * (btn_w + _GRID_GAP)
            y = y0 + r * (_GRID_BTN_H + _GRID_GAP)
            rect = pygame.Rect(x, y, btn_w, _GRID_BTN_H)
            pygame.draw.rect(surface, colour, rect, border_radius=8)
            pygame.draw.rect(surface, _TEXT, rect, 1, border_radius=8)
            txt = self._font_sm.render(label, True, _TEXT)
            surface.blit(txt, txt.get_rect(center=rect.center))
            self._buttons.append((rect, action))

    def _draw_existing_prompt(self, surface) -> None:
        """Centred card offered when a saved map for this track is found: EDIT it
        (load onto the DONE grid) or RE-RECORD from scratch."""
        tmap = self._existing_map
        cw, ch = 560, 210
        cx = (self.width - cw) // 2
        cy = (self.height - ch) // 2
        card = pygame.Rect(cx, cy, cw, ch)
        pygame.draw.rect(surface, _BANNER_BG, card, border_radius=12)
        pygame.draw.rect(surface, _CURRENT, card, 2, border_radius=12)

        title = self._font_lg.render("TRACK ALREADY RECORDED", True, _TEXT)
        surface.blit(title, (cx + 24, cy + 20))
        sub = f"{tmap.track or 'Unknown'}   ·   {tmap.game or ''}".strip(" ·")
        surface.blit(self._font_md.render(sub, True, _SUBTLE), (cx + 24, cy + 58))

        parts = []
        if tmap.left_edge and tmap.right_edge:
            parts.append("edges")
        if tmap.pit_lane:
            parts.append("pit lane")
        if tmap.lines:
            parts.append("lines: " + ", ".join(tmap.lines.keys()))
        summary = "  ·  ".join(parts) or "partial recording"
        surface.blit(self._font_sm.render(summary, True, _SUBTLE), (cx + 24, cy + 90))

        # Whether the class being driven right now already has a line.
        cur = self.recorder.car_class
        if cur and cur not in tmap.lines:
            hint = f"No line for {cur} yet — EDIT to add it"
            surface.blit(self._font_sm.render(hint, True, _CURRENT), (cx + 24, cy + 116))

        gap = _MARGIN
        btn_w = (cw - 3 * gap) // 2
        by = cy + ch - _BTN_H - 20
        for i, (label, action, colour) in enumerate(
                [("RE-RECORD", "rerecord", (90, 70, 70)),
                 ("EDIT", "edit_existing", (70, 120, 90))]):
            rect = pygame.Rect(cx + gap + i * (btn_w + gap), by, btn_w, _BTN_H)
            pygame.draw.rect(surface, colour, rect, border_radius=8)
            pygame.draw.rect(surface, _TEXT, rect, 1, border_radius=8)
            txt = self._font_md.render(label, True, _TEXT)
            surface.blit(txt, txt.get_rect(center=rect.center))
            self._buttons.append((rect, action))

    def _draw_debug(self, surface) -> None:
        """Live telemetry readout, top-left. Tap to collapse/expand. Most useful
        for verifying the world-position parse against a real game: if pos_valid
        is False nothing records, and mirrored/scrambled coords show up here
        before the trace does."""
        x0 = _MARGIN
        y0 = _BANNER_H + _PROGRESS_H + 8

        if not self._show_debug:
            # Collapsed: a small chip that re-opens the panel.
            chip = self._font_dbg.render(" DBG ", True, _SUBTLE)
            rect = chip.get_rect(topleft=(x0, y0)).inflate(8, 6)
            pygame.draw.rect(surface, _BANNER_BG, rect, border_radius=4)
            pygame.draw.rect(surface, (60, 66, 78), rect, 1, border_radius=4)
            surface.blit(chip, (rect.x + 4, rect.y + 3))
            self._debug_rect = rect
            return

        d = self._data
        valid = bool(getattr(d, "pos_valid", False)) if d else False
        if d is None:
            lines = [("waiting for telemetry…", _SUBTLE)]
        else:
            sect = f"{d.sector + 1}/3"
            ok = _STEP_DONE if valid else _CAR
            lines = [
                (f"pos_valid : {valid}", ok),
                (f"x/z/y (m) : {d.pos_x:8.1f} {d.pos_z:8.1f} {d.pos_y:6.1f}", _TEXT),
                (f"heading   : {_deg(d.heading):5.1f} deg", _TEXT),
                (f"dist S/F  : {d.lap_distance:8.1f} m", _TEXT),
                (f"sector    : {sect}", _TEXT),
                (f"speed     : {d.speed:5.0f} km/h", _TEXT),
                (f"lap       : {d.lap_number}", _TEXT),
                (f"in_pits   : {'yes' if d.in_pits else 'no'}", _TEXT),
                (f"captured  : {self.recorder.point_count} pts", _SUBTLE),
                (f"car_class : {d.car_class!r} (rec: {self.recorder.car_class!r})", _TEXT),
                (f"has_line  : {self.recorder.has_racing_line}", _TEXT),
            ]

        line_h = self._font_dbg.get_height() + 2
        w = max(self._font_dbg.size(t)[0] for t, _ in lines) + 16
        h = line_h * len(lines) + 12
        rect = pygame.Rect(x0, y0, w, h)
        panel = pygame.Surface((w, h))
        panel.set_alpha(215)
        panel.fill(_BANNER_BG)
        surface.blit(panel, (x0, y0))
        pygame.draw.rect(surface, (60, 66, 78), rect, 1, border_radius=4)
        y = y0 + 6
        for text, colour in lines:
            surface.blit(self._font_dbg.render(text, True, colour), (x0 + 8, y))
            y += line_h
        self._debug_rect = rect

    def _draw_footer_text(self, surface, text: str) -> None:
        txt = self._font_sm.render(text, True, _SUBTLE)
        y = self.height - _BTN_H - _MARGIN + (_BTN_H - txt.get_height()) // 2
        surface.blit(txt, txt.get_rect(midtop=(self.width // 2, y)))
