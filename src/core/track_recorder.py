"""Track recorder — builds a circuit map from live telemetry.

Fed ``TelemetryData`` frames, it walks a phase state machine and accumulates a
``TrackMap``: the drivable corridor (left + right edges), the racing line
(averaged over several attempts), the start/finish line and the sector-boundary
positions (so the map can be colourised by sector later — the boundary *places*
matter here, not the times).

Design notes
------------
* **Lap / rewind detection is delegated to ``LapTracker``** — the project's
  single source of truth — never re-implemented here. The recorder reacts to
  its ``LapCompleted`` / ``Rewind`` / ``Restart`` events.
* **It never touches the session logger or ``logs/``.** Recording a track is
  not a driven session and must never surface as an attempt, a PB, a badge or
  a debrief. The only file it writes is the track map JSON under ``tracks/``.
* **Pure logic + stdlib only** (no pygame), so it is unit-testable and can
  later move to the shared ``sessionlog`` package for companion-side editing.

The live view drives it with ``update(data)`` each frame and ``accept()`` /
``redo()`` on the phase buttons; it reads the exposed properties to render.
"""

import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from core.geometry import project_to_line as _project_to_line
from core.geometry import pt_dist as _pt_dist
from core.lap_tracker import LapTracker, Restart, Rewind
from sessionlog import trackmap
from core.telemetry_model import TelemetryData


def _utc_now() -> str:
    """Current UTC time as an ISO-8601 stamp for created/updated metadata."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Points per stored line. Every line (edges + racing line) is resampled to this
# many points evenly along the lap, which keeps files small, makes rendering
# trivial and — crucially — puts every racing-line attempt on the same station
# grid so they can be averaged point-by-point.
_LINE_POINTS = 400

# Default number of racing-line laps to average.
_RACING_ATTEMPTS = 3

# Per-class racing lines under `lines`, plus track-level and per-class `notes`.
# (An earlier single-line layout never shipped, so there's no legacy to migrate.)
FORMAT_VERSION = 1


class Phase(str, Enum):
    LEFT = "left_edge"
    RIGHT = "right_edge"
    RACING = "racing_line"
    PIT = "pit_lane"         # optional extra pass, entered from the DONE screen
    DONE = "done"


class State(str, Enum):
    ARMING = "arming"        # idle — waiting for the START button (position first)
    ARMED = "armed"          # START pressed — recording begins at the next S/F line
    RECORDING = "recording"  # capturing points around the lap
    REVIEW = "review"        # lap captured, awaiting accept / redo
    DONE = "done"            # all phases complete, ready to name + save


_PHASE_ORDER = [Phase.LEFT, Phase.RIGHT, Phase.RACING]
_PHASE_LABEL = {
    Phase.LEFT: "LEFT EDGE",
    Phase.RIGHT: "RIGHT EDGE",
    Phase.RACING: "RACING LINE",
    Phase.PIT: "PIT LANE",
    Phase.DONE: "DONE",
}

# Pit-lane simplification tolerance (metres) — the lane is short and doesn't
# need the ~metre fidelity the racing surface gets.
_PIT_RDP_EPS = 2.0

# Below this speed (km/h) a frame is treated as stationary (the box stop, a
# garage detour, or repositioning) and dropped, so the saved line bridges cleanly
# instead of collapsing into a point cluster.
_PIT_MIN_SPEED = 8.0

# ── Pit-lane joining (see _finish_pit) ───────────────────────────────────────
# A driven pit trip is: leave the racing line -> entry road -> pit lane -> exit
# road -> rejoin the racing line. The in_pits flag only covers the middle, so we
# capture the on-track approach/exit too and stitch the whole thing together.
#
# Within this distance (m) of the racing line the car counts as "on the track".
# The entry lead-in captures back to where it leaves this band and the exit
# lead-out runs until it re-enters it. Kept tight so the capture *follows the
# slip-road down onto the line* rather than stopping while it's still running
# parallel a few metres out (which left the lane floating with a perpendicular
# hop to the line). The exit merge is additionally gated on the pit limiter being
# OFF: proximity alone is fooled where the exit road runs *under* the circuit
# (Abu Dhabi's pit lane crosses beneath the main straight), so the driver is
# asked to hold the limiter — pit assist off — until they reach the track.
_PIT_MERGE_M = 3.0
# Cap how much on-track approach/exit is stitched on, so a long out-lap or a
# missed merge can't splice half the circuit onto the pit lane.
_PIT_LEAD_MAX_M = 450.0
# A tip already this close to the line is pulled exactly onto it (the capture
# reached the merge, this just closes the last discretisation gap). A larger gap
# means the slip-road was never driven (e.g. a garage start) — left as-is.
_PIT_SNAP_MAX_M = 8.0
# A turn sharper than this (deg) is the line doubling back into the garage box —
# the spur is removed so the lane runs straight past the boxes.
_PIT_SPUR_ANGLE = 135.0
# The garage box: a pit frame slower than this marks a real stop, and captured
# lane points within the radius of it are excised (bridged straight) so the detour
# into the box doesn't bulge off the through-lane.
_PIT_BOX_SPEED = 20.0
_PIT_BOX_RADIUS = 22.0


# ── Geometry helpers (pure) ──────────────────────────────────────────────────

def _clean_monotonic(raw: list) -> list:
    """Drop points whose lap distance went backwards (packet glitches, the S/F
    wrap), leaving a strictly non-decreasing distance profile for one lap."""
    out = []
    last = None
    for p in raw:
        if last is None or p[2] >= last:
            out.append(p)
            last = p[2]
    return out


def _resample_line(raw: list, n: int = _LINE_POINTS) -> list:
    """Resample ``[(x, z, dist), ...]`` to ``n`` points spread evenly by lap
    distance, so two laps of the same track share a common station grid.
    Returns ``[(x, z), ...]``."""
    pts = _clean_monotonic(raw)
    if len(pts) < 2:
        return [(p[0], p[1]) for p in pts]
    d0, d1 = pts[0][2], pts[-1][2]
    span = d1 - d0
    if span <= 0:
        return [(pts[0][0], pts[0][1])] * n
    out = []
    j = 0
    for i in range(n):
        target = d0 + span * (i / (n - 1))
        while j < len(pts) - 2 and pts[j + 1][2] < target:
            j += 1
        pa, pb = pts[j], pts[j + 1]
        da, db = pa[2], pb[2]
        t = 0.0 if db <= da else (target - da) / (db - da)
        out.append((pa[0] + (pb[0] - pa[0]) * t,
                    pa[1] + (pb[1] - pa[1]) * t))
    return out


def _rdp(pts: list, eps: float) -> list:
    """Ramer–Douglas–Peucker simplification of a ``[(x, z), ...]`` polyline —
    used for the pit lane, an open path with no distance stations to resample
    against."""
    if len(pts) < 3:
        return list(pts)
    ax, az = pts[0]
    bx, bz = pts[-1]
    dx, dz = bx - ax, bz - az
    seg = math.hypot(dx, dz)
    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        px, pz = pts[i]
        if seg == 0:
            d = math.hypot(px - ax, pz - az)
        else:
            d = abs(dx * (az - pz) - (ax - px) * dz) / seg
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = _rdp(pts[:idx + 1], eps)
        right = _rdp(pts[idx:], eps)
        return left[:-1] + right
    return [pts[0], pts[-1]]


def _drop_reversals(pts: list, max_turn: float) -> list:
    """Remove near-U-turn spurs — where the line doubles back on itself, e.g. the
    detour into a garage box — by dropping the sharpest reversal apex until no turn
    exceeds ``max_turn`` degrees. Genuine pit-lane corners (well under 180°) stay."""
    pts = list(pts)
    while len(pts) >= 3:
        worst, worst_turn = -1, max_turn
        for i in range(1, len(pts) - 1):
            ax, az = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
            bx, bz = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
            turn = abs(math.degrees(math.atan2(ax * bz - az * bx, ax * bx + az * bz)))
            if turn > worst_turn:
                worst, worst_turn = i, turn
        if worst < 0:
            break
        del pts[worst]
    return pts


def _median(values: list) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _average_lines(lines: list) -> list:
    """Point-by-point median of equal-length resampled lines (median rejects a
    single wild attempt without needing an explicit outlier pass)."""
    if not lines:
        return []
    if len(lines) == 1:
        return list(lines[0])
    n = min(len(ln) for ln in lines)
    out = []
    for i in range(n):
        out.append((_median([ln[i][0] for ln in lines]),
                    _median([ln[i][1] for ln in lines])))
    return out


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "track"


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class TrackMap:
    # ── Shared circuit geometry (one per track, class-independent) ──
    game: str = ""
    track: str = ""
    game_track_length_m: float = 0.0   # from the game (m_trackLength), for a sanity check
    notes: str = ""                    # free-text track notes (e.g. "missing F2 line")
    orientation: float = 0.0           # display rotation (deg) for top-down maps; cosmetic, world coords untouched
    # ── Provenance (optional; absent on pre-metadata files) ──
    created: str = ""                  # ISO-8601 UTC, stamped once at first save
    updated: str = ""                  # ISO-8601 UTC, refreshed on every save/edit
    author: str = ""                   # who recorded it; from config, preserved on edits
    left_edge: list = field(default_factory=list)     # [(x, z), ...]
    right_edge: list = field(default_factory=list)
    pit_lane: list = field(default_factory=list)        # open polyline: entry → exit
    sf_line: dict = field(default_factory=dict)        # {"pos": [x, z], "heading": rad}
    sectors: list = field(default_factory=list)        # [{"index", "pos": [x, z], "lap_dist_m"}]
    sections: list = field(default_factory=list)       # labelled corners/straights/complexes
    # ── Per car class ──
    # {car_class: {"racing_line": [(x,z),...], "racing_attempts": int,
    #              "gears": list|None (editor-filled, never recorded), "notes": str}}
    lines: dict = field(default_factory=dict)

    @staticmethod
    def _line_out(ln: dict) -> dict:
        return {
            "racing_line": [[round(x, 2), round(z, 2)] for x, z in ln.get("racing_line", [])],
            "racing_attempts": ln.get("racing_attempts", 0),
            "gears": ln.get("gears"),          # None or an editor-filled list, carried as-is
            "notes": ln.get("notes", ""),
        }

    @staticmethod
    def _line_in(ln: dict) -> dict:
        return {
            "racing_line": [tuple(p) for p in ln.get("racing_line", [])],
            "racing_attempts": ln.get("racing_attempts", 0),
            "gears": ln.get("gears"),
            "notes": ln.get("notes", ""),
        }

    def to_dict(self) -> dict:
        return {
            "format_version": FORMAT_VERSION,
            "game": self.game,
            "track": self.track,
            "game_track_length_m": round(self.game_track_length_m, 1),
            "notes": self.notes,
            "orientation": round(self.orientation, 2),
            "created": self.created,
            "updated": self.updated,
            "author": self.author,
            "left_edge": [[round(x, 2), round(z, 2)] for x, z in self.left_edge],
            "right_edge": [[round(x, 2), round(z, 2)] for x, z in self.right_edge],
            "pit_lane": [[round(x, 2), round(z, 2)] for x, z in self.pit_lane],
            "sf_line": self.sf_line,
            "sectors": self.sectors,
            "sections": self.sections,
            "lines": {cls: self._line_out(ln) for cls, ln in self.lines.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TrackMap":
        raw = d.get("lines")
        lines = {c: cls._line_in(ln) for c, ln in raw.items()} if isinstance(raw, dict) else {}
        return cls(
            game=d.get("game", ""),
            track=d.get("track", ""),
            game_track_length_m=d.get("game_track_length_m", 0.0),
            notes=d.get("notes", "") or "",
            orientation=float(d.get("orientation") or 0.0),
            created=d.get("created", "") or "",
            updated=d.get("updated", "") or "",
            author=d.get("author", "") or "",
            left_edge=[tuple(p) for p in d.get("left_edge", [])],
            right_edge=[tuple(p) for p in d.get("right_edge", [])],
            pit_lane=[tuple(p) for p in d.get("pit_lane", [])],
            sf_line=d.get("sf_line", {}) or {},
            sectors=d.get("sectors", []),
            sections=d.get("sections", []),
            lines=lines,
        )


# ── Recorder state machine ───────────────────────────────────────────────────

class TrackRecorder:

    def __init__(self, racing_attempts: int = _RACING_ATTEMPTS,
                 author: str = ""):
        self._target_attempts = max(1, racing_attempts)
        self._author = author             # from config; stamped onto saved maps
        self._loaded_created = ""         # created stamp of a loaded map, preserved
        self._lap = LapTracker()
        self._phase_idx = 0
        self._state = State.ARMING
        # Edit mode: re-driving one line of an already-complete map. Set while a
        # single phase is being re-driven so accept() returns to DONE instead of
        # advancing linearly through the phases.
        self._single_phase = False
        self._loaded = False              # map was loaded from disk for editing
        self._loaded_attempts = 0         # racing_attempts of a loaded map (raw laps aren't kept)
        # Current lap capture
        self._raw: list = []              # [(x, z, dist), ...] this lap
        self._sector_marks: list = []     # marks captured this lap
        self._prev_sector = 0
        self._sf: dict = {}               # S/F pos/heading from the last boundary
        # Accepted results
        self._left: list = []
        self._right: list = []
        self._attempts: list = []         # list of resampled racing-line laps
        self._racing_line: list = []      # averaged, once finished — the CURRENT class
        self._sectors: list = []          # boundary marks kept for the map
        self._sections: list = []         # labelled corners/straights (carried, never recorded here)
        # All car classes' line entries from a loaded map, preserved on save so
        # re-driving one class never disturbs another (and keeps each class's
        # editor-added gears / notes). Plus track-level notes.
        self._loaded_lines: dict = {}
        self._notes: str = ""
        self._orientation: float = 0.0    # cosmetic display rotation (deg); set only when editing a saved map
        # Optional pit-lane pass (bounded by the in_pits flag, not lap crossings)
        self._pit_mode = False
        self._pit_raw: list = []
        self._pit_lane: list = []
        # True once we've seen the driver on-track during a pit pass, so a genuine
        # pit entry (not "armed while parked in the box") starts the capture.
        self._pit_seen_track = False
        # Rolling buffer of the recent on-track approach (before the pit entry) and
        # a flag for the exit lead-out (after the pit exit, until we rejoin track).
        self._pit_track_buf: list = []
        self._pit_exiting = False
        self._pit_exit_dist = 0.0
        # Garage box: the slowest point inside the pits, used to excise the detour.
        self._pit_box = None
        self._pit_box_speed = float("inf")
        # Meta captured from telemetry
        self._game = ""
        self._track = ""
        self._car_class = ""
        self._track_len = 0.0
        self._pos_ever_valid = False   # have we ever received world position?
        self._prev_lap_num = None      # for raw S/F-crossing detection
        self._prev_dist = None         # lap_distance, for run-up S/F crossing

    # ── Feed ──────────────────────────────────────────────────────────────

    def update(self, data: TelemetryData) -> list:
        """Feed one telemetry frame. Returns a list of short event strings the
        view can flash (e.g. "LAP CAPTURED", "REWIND — RE-DRIVE")."""
        notes: list = []
        if data.track:
            self._track = data.track
        if data.game:
            self._game = data.game
        if data.car_class:
            self._car_class = data.car_class
        if data.pos_valid:
            self._pos_ever_valid = True

        events = self._lap.update(data)

        if self._pit_mode:
            return self._update_pit(data)
        if self._state == State.DONE:
            return notes
        if not data.pos_valid:
            return notes

        # A rewind / flashback mid-lap corrupts the traced line — discard it and
        # re-arm (auto-retry at the next crossing, no need to press START again).
        # Rewind detection stays with LapTracker; we never re-implement it.
        for ev in events:
            if isinstance(ev, (Rewind, Restart)) and self._state == State.RECORDING:
                self._raw = []
                self._sector_marks = []
                self._state = State.ARMED
                notes.append("REWIND — RE-DRIVE")

        # Forward start/finish crossing. Two signals, because one alone misses
        # cases (and neither is LapTracker's LapCompleted, which needs a prior
        # completed lap so can't begin a first flying lap):
        #   - the lap number ticks up — normal race/practice lap completion;
        #   - lap_distance crosses 0 from a negative run-up — Time Trial / hotlap
        #     start and in-game "restart lap", which place the car before the S/F
        #     line WITHOUT bumping the lap number. Without this the recording only
        #     starts a whole lap late.
        lap_ticked = (self._prev_lap_num is not None
                      and data.lap_number > self._prev_lap_num)
        ran_up = (self._prev_dist is not None
                  and self._prev_dist < 0.0 <= data.lap_distance)
        crossed = lap_ticked or ran_up
        self._prev_lap_num = data.lap_number
        self._prev_dist = data.lap_distance

        if crossed:
            self._sf = {"pos": [round(data.pos_x, 2), round(data.pos_z, 2)],
                        "heading": round(data.heading, 4)}
            if self._state == State.ARMED:
                self._begin_lap(data)
                notes.append("RECORDING")
            elif self._state == State.RECORDING:
                self._finish_lap()
                notes.append("LAP CAPTURED")

        if self._state == State.RECORDING:
            self._capture(data)

        return notes

    def _capture(self, data: TelemetryData) -> None:
        if data.in_pits:
            return  # pit lane / garage teleport — never part of the track line
        self._raw.append((data.pos_x, data.pos_z, data.lap_distance))
        if data.sector != self._prev_sector:
            self._sector_marks.append({
                "index": int(data.sector),
                "pos": [round(data.pos_x, 2), round(data.pos_z, 2)],
                "lap_dist_m": round(data.lap_distance, 1),
            })
            self._prev_sector = data.sector

    def _update_pit(self, data: TelemetryData) -> list:
        """Pit-lane capture. A driven pit trip runs entry road -> pit lane ->
        exit road, but the ``in_pits`` flag only covers the pit lane itself, so
        capturing it alone leaves the saved line floating off the circuit at both
        ends. We therefore stitch on the on-track slip-roads:

        - **Lead-in.** While armed and on-track we buffer the recent approach.
          A pit trip only counts once we've seen the driver on-track
          (``_pit_seen_track``), so arming while parked in the box waits for a
          genuine entry rather than grabbing only the box -> exit half. At the
          entry the buffered approach (trimmed to where it left the racing line)
          is prepended.
        - **Pit lane.** Points while ``in_pits`` and moving (the stationary box
          stop is dropped by the speed gate).
        - **Lead-out.** After the exit we keep capturing until the car rejoins
          the racing line — the limiter off *and* back within ``_PIT_MERGE_M`` of
          the line — so the exit road is part of the lane too. The limiter gate
          means a pit lane that runs under the circuit (Abu Dhabi) is followed
          past the crossover instead of cutting off there.

        ``_finish_pit`` then removes the garage-box spur and snaps the ends."""
        notes: list = []
        pt = (data.pos_x, data.pos_z)
        moving = data.pos_valid and data.speed > _PIT_MIN_SPEED

        if self._state == State.ARMING:
            if not data.in_pits:
                self._pit_seen_track = True
                if moving:
                    self._buffer_approach(pt)
            elif data.pos_valid and self._pit_seen_track:
                self._state = State.RECORDING
                self._pit_exiting = False
                self._pit_raw = self._lead_in() + [pt]
                notes.append("RECORDING PIT LANE")

        elif self._state == State.RECORDING:
            if not self._pit_exiting and data.in_pits:
                # Track the slowest in-pit point — the garage box — even when the
                # frame itself is dropped by the speed gate, so _finish_pit can
                # excise the detour into the bay.
                if data.pos_valid and data.speed < self._pit_box_speed:
                    self._pit_box_speed = data.speed
                    self._pit_box = pt
                if moving:
                    self._pit_raw.append(pt)
            else:
                # Out the far end — capture the exit road until we rejoin the
                # racing line (or a safety cap), then finish.
                if not self._pit_exiting:
                    self._pit_exiting = True
                    self._pit_exit_dist = 0.0
                    notes.append("PIT EXIT — KEEP LIMITER ON UNTIL ON TRACK")
                if moving:
                    if self._pit_raw:
                        self._pit_exit_dist += _pt_dist(self._pit_raw[-1], pt)
                    self._pit_raw.append(pt)
                # "Rejoined the track" needs BOTH the pit limiter off and
                # proximity to the racing line. Proximity alone is fooled where
                # the exit road runs under the circuit (Abu Dhabi's pit lane
                # crosses beneath the main straight — the 2-D point sits on the
                # racing line even though the car is still in the pit lane below),
                # cutting the capture short. The limiter is the true "still in
                # the pit lane" signal, so we ask the driver to hold it until
                # they reach the track (pit assist off). Sources without a
                # limiter report it False, falling back to proximity as before.
                rejoined = (not data.in_pits and not data.pit_limiter
                            and _project_to_line(pt, self._merge_ref())[2] <= _PIT_MERGE_M)
                if rejoined or self._pit_exit_dist > _PIT_LEAD_MAX_M:
                    self._state = State.REVIEW
                    notes.append("PIT LANE CAPTURED")
        return notes

    # ── Pit-lane geometry helpers ─────────────────────────────────────────────

    def _merge_ref(self) -> list:
        """The line a pit trip leaves from / rejoins — the racing line, falling
        back to the track edges before the racing line is captured."""
        return self._racing_line or (self._left + self._right)

    def _buffer_approach(self, pt: tuple) -> None:
        """Keep the most recent ``_PIT_LEAD_MAX_M`` of on-track approach so it can
        be prepended at the pit entry."""
        buf = self._pit_track_buf
        buf.append(pt)
        while len(buf) > 2 and self._lead_len(buf) > _PIT_LEAD_MAX_M:
            buf.pop(0)

    def _lead_in(self) -> list:
        """The approach slip-road: the buffered on-track points from where the car
        last left the racing line up to the pit entry. Older shared-track points
        (still on the racing line) are trimmed so the lane doesn't overlay the
        main circuit."""
        buf = self._pit_track_buf
        if not buf:
            return []
        ref = self._merge_ref()
        out = []
        for pt in reversed(buf):
            out.append(pt)
            if ref and _project_to_line(pt, ref)[2] <= _PIT_MERGE_M:
                break  # reached where the slip-road meets the track
        out.reverse()
        return out

    @staticmethod
    def _lead_len(pts: list) -> float:
        return sum(_pt_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    def _excise_box(self, pts: list) -> list:
        """Drop captured points within ``_PIT_BOX_RADIUS`` of the garage box (a
        genuine stop) so the detour into the bay is bridged straight and the lane
        runs through past the boxes. No-op if no real stop happened."""
        box = self._pit_box
        if box is None or self._pit_box_speed >= _PIT_BOX_SPEED:
            return list(pts)
        kept = [p for p in pts if _pt_dist(p, box) > _PIT_BOX_RADIUS]
        return kept if len(kept) >= 2 else list(pts)

    def _snap_end(self, lane: list, ref: list, at_start: bool) -> list:
        """Pull the lane's end-tip exactly onto the racing line. The capture
        already followed the slip-road to its merge (within ``_PIT_MERGE_M``), so
        the tip is only a small discretisation gap off the line — moving it onto
        its perpendicular foot closes that gap while the converging segment before
        it stays a shallow tangent merge (no perpendicular stub). A gap over
        ``_PIT_SNAP_MAX_M`` (slip-road never driven, e.g. a garage start) is left
        as-is rather than yanked across."""
        tip = lane[0] if at_start else lane[-1]
        foot, _seg, gap = _project_to_line(tip, ref)
        if foot is None or not (0.01 < gap <= _PIT_SNAP_MAX_M):
            return lane
        lane = list(lane)
        lane[0 if at_start else -1] = foot
        return lane

    def _finish_pit(self) -> list:
        """Turn the raw pit capture into the saved lane: excise the garage-box
        detour, drop any doubling-back spur, simplify, then join each end onto the
        racing line with a tangent stub so it flows straight in and out."""
        lane = self._excise_box(self._pit_raw)
        lane = _drop_reversals(lane, _PIT_SPUR_ANGLE)
        lane = _rdp(lane, _PIT_RDP_EPS)
        ref = self._merge_ref()
        if len(lane) >= 2 and ref:
            lane = self._snap_end(lane, ref, at_start=True)
            lane = self._snap_end(lane, ref, at_start=False)
        return lane

    def _begin_lap(self, data: TelemetryData) -> None:
        # The trailing capture in update() adds this frame's point — don't seed
        # it here or the S/F point lands in the line twice.
        self._state = State.RECORDING
        self._raw = []
        self._sector_marks = []
        self._prev_sector = data.sector

    def _begin_arming(self) -> None:
        # Idle again — the driver repositions, then presses START. Recording only
        # begins at the S/F crossing after START, so between phases (left → right
        # → racing line) there's a natural repositioning lap.
        self._state = State.ARMING
        self._raw = []
        self._sector_marks = []

    def _finish_lap(self) -> None:
        self._state = State.REVIEW
        self._track_len = max(self._track_len, self._raw[-1][2] if self._raw else 0.0)

    # ── Phase buttons ─────────────────────────────────────────────────────

    def accept(self) -> None:
        """Accept the lap under review and advance the phase."""
        if self._state != State.REVIEW:
            return
        if self._pit_mode:
            self._pit_lane = self._finish_pit()
            self._pit_mode = False
            self._state = State.DONE
            return
        line = _resample_line(self._raw)
        phase = self.phase
        if phase == Phase.LEFT:
            self._left = line
            self._sectors = list(self._sector_marks)
            self._advance_or_done()
        elif phase == Phase.RIGHT:
            self._right = line
            self._advance_or_done()
        elif phase == Phase.RACING:
            self._attempts.append(line)
            self._sectors = list(self._sector_marks)  # freshest boundary marks
            if len(self._attempts) >= self._target_attempts:
                self._finish_racing()
            else:
                self._begin_arming()  # go again for the next attempt

    def redo(self) -> None:
        """Discard the lap under review and re-drive the same phase / attempt."""
        if self._state != State.REVIEW:
            return
        if self._pit_mode:
            self._reset_pit_capture()
            self._state = State.ARMING
            return
        self._begin_arming()

    def restart(self) -> None:
        """Throw away everything and start the whole recording over from the
        left edge. Keeps the captured game/track/car metadata."""
        self._phase_idx = 0
        self._state = State.ARMING
        self._raw = []
        self._sector_marks = []
        self._prev_sector = 0
        self._sf = {}
        self._left = []
        self._right = []
        self._attempts = []
        self._racing_line = []
        self._sectors = []
        self._sections = []
        self._loaded_lines = {}
        self._notes = ""
        self._orientation = 0.0        # display rotation (deg); set only when editing a saved map
        self._pit_mode = False
        self._pit_raw = []
        self._pit_lane = []
        self._pit_seen_track = False
        self._pit_track_buf = []
        self._pit_exiting = False
        self._pit_exit_dist = 0.0
        self._pit_box = None
        self._pit_box_speed = float("inf")
        self._prev_lap_num = None
        self._prev_dist = None
        self._single_phase = False
        self._loaded = False
        self._loaded_attempts = 0
        self._loaded_created = ""     # a fresh recording has no prior created stamp
        self._lap.reset()

    # discard_all is the DONE-screen "start over" button; a full wipe like the
    # progress-strip RESTART.
    discard_all = restart

    def load_existing(self, tmap: "TrackMap") -> None:
        """Load a saved map for editing: everything is already captured, so jump
        straight to the DONE screen where an individual line can be re-driven or
        the pit lane added/replaced. Raw racing-line attempts aren't stored on
        disk, so the averaged line is loaded as-is and its attempt count kept.

        The shared geometry is loaded once; the racing line is per car class. The
        CURRENT class (from live telemetry, ``_car_class``) is the one being
        edited — its line is loaded if present, else left empty so it can be
        recorded. Every other class's entry is stashed in ``_other_lines`` and
        written straight back on save, untouched."""
        self._left = list(tmap.left_edge)
        self._right = list(tmap.right_edge)
        self._notes = tmap.notes
        self._orientation = tmap.orientation   # cosmetic display rotation, preserved on edits
        # Provenance: keep the original creation stamp and author; a re-drive is
        # still the same map by the same person (config author only fills a blank).
        self._loaded_created = tmap.created
        if tmap.author:
            self._author = tmap.author
        # Stash every class's entry (preserved verbatim on save); load the current
        # class's line for editing.
        self._loaded_lines = {c: dict(ln) for c, ln in tmap.lines.items()}
        # Load the current class's own line for editing (per-class profiles);
        # if the class has no profile yet, fall back to a sibling's line for
        # shared-line games so the DONE screen starts from the shared geometry.
        cur = trackmap.resolve_line(
            {"lines": tmap.lines}, tmap.game or self._game, self._car_class)
        self._racing_line = list(cur.get("racing_line", []))
        self._loaded_attempts = cur.get("racing_attempts", 0)
        self._attempts = []
        self._pit_lane = list(tmap.pit_lane)
        self._sectors = list(tmap.sectors)
        self._sections = list(tmap.sections)
        self._sf = dict(tmap.sf_line)
        if tmap.game:
            self._game = tmap.game
        if tmap.track:
            self._track = tmap.track
        # car_class is intentionally NOT taken from the file — it's the live class.
        self._track_len = tmap.game_track_length_m or self._track_len
        self._loaded = True
        self._single_phase = False
        self._pit_mode = False
        self._phase_idx = len(_PHASE_ORDER)
        self._state = State.DONE

    def redrive(self, phase: Phase) -> None:
        """Re-drive a single line of a complete map, replacing just that line and
        returning to the DONE screen — the other lines are untouched."""
        if self._state != State.DONE or self._pit_mode:
            return
        if phase not in _PHASE_ORDER:
            return
        self._phase_idx = _PHASE_ORDER.index(phase)
        self._single_phase = True
        if phase == Phase.RACING:
            self._attempts = []
        # Clear stale crossing state so the next crossing after START begins the
        # lap cleanly (update() doesn't track these while DONE).
        self._prev_lap_num = None
        self._prev_dist = None
        self._begin_arming()

    def _reset_pit_capture(self) -> None:
        """Clear all pit-pass capture state (raw line, approach buffer, exit and
        box tracking) so a fresh pass starts clean."""
        self._pit_raw = []
        self._pit_track_buf = []
        self._pit_exiting = False
        self._pit_exit_dist = 0.0
        self._pit_seen_track = False
        self._pit_box = None
        self._pit_box_speed = float("inf")

    def start_pit_lane(self) -> None:
        """Begin the optional pit-lane pass from the DONE screen."""
        if self._state == State.DONE and not self._pit_mode:
            self._pit_mode = True
            self._reset_pit_capture()
            self._state = State.ARMING

    def redrive_pit(self) -> None:
        """Add or replace the pit lane from the DONE screen (clears any existing
        lane so a re-drive fully replaces it)."""
        if self._state == State.DONE and not self._pit_mode:
            self._pit_mode = True
            self._reset_pit_capture()
            self._pit_lane = []
            self._state = State.ARMING

    def finish_racing(self) -> None:
        """Finish the racing-line phase early with the attempts banked so far."""
        if self.phase == Phase.RACING and self._attempts:
            self._finish_racing()

    def _finish_racing(self) -> None:
        self._racing_line = _average_lines(self._attempts)
        self._advance_or_done()

    def _advance_or_done(self) -> None:
        """After accepting a line: return to DONE when re-driving a single line,
        otherwise advance to the next phase."""
        if self._single_phase:
            self._return_to_done()
        else:
            self._advance_phase()

    def _return_to_done(self) -> None:
        self._single_phase = False
        self._phase_idx = len(_PHASE_ORDER)
        self._raw = []
        self._sector_marks = []
        self._state = State.DONE

    def _advance_phase(self) -> None:
        self._phase_idx += 1
        if self._phase_idx >= len(_PHASE_ORDER):
            self._state = State.DONE
        else:
            # Back to idle — the driver repositions for the next phase, then
            # presses START (recording begins at the following S/F crossing).
            self._begin_arming()

    def arm(self) -> None:
        """START button — begin recording at the next start/finish crossing.
        Lets you record from your first flying lap (start on the run-up, press
        START, cross the line)."""
        if self._state == State.ARMING and not self._pit_mode:
            self._state = State.ARMED

    def cancel_arm(self) -> None:
        """Un-arm back to idle without recording."""
        if self._state == State.ARMED:
            self._state = State.ARMING

    # ── Exposed state (for the live view) ─────────────────────────────────

    @property
    def phase(self) -> Phase:
        if self._pit_mode:
            return Phase.PIT
        if self._phase_idx >= len(_PHASE_ORDER):
            return Phase.DONE
        return _PHASE_ORDER[self._phase_idx]

    @property
    def state(self) -> State:
        return self._state

    @property
    def phase_label(self) -> str:
        return _PHASE_LABEL[self.phase]

    @property
    def phases(self) -> list:
        """Progress checklist for the UI: ``[(label, state), ...]`` where state
        is 'done' / 'current' / 'pending'. The pit lane only appears once the
        optional pass has been started or completed."""
        cur = self.phase
        done = {
            Phase.LEFT: bool(self._left),
            Phase.RIGHT: bool(self._right),
            Phase.RACING: bool(self._racing_line),
            Phase.PIT: bool(self._pit_lane),
        }
        order = [Phase.LEFT, Phase.RIGHT, Phase.RACING]
        if self._pit_mode or self._pit_lane:
            order.append(Phase.PIT)
        out = []
        for ph in order:
            if done[ph]:
                out.append((_PHASE_LABEL[ph], "done"))
            elif ph == cur:
                out.append((_PHASE_LABEL[ph], "current"))
            else:
                out.append((_PHASE_LABEL[ph], "pending"))
        return out

    @property
    def attempt(self) -> int:
        return len(self._attempts) + 1  # 1-based, current attempt in progress

    @property
    def target_attempts(self) -> int:
        return self._target_attempts

    @property
    def can_accept(self) -> bool:
        return self._state == State.REVIEW

    @property
    def can_start(self) -> bool:
        """START button available — idle, positioned, with telemetry flowing."""
        return (self._state == State.ARMING and not self._pit_mode
                and self._pos_ever_valid)

    @property
    def is_armed(self) -> bool:
        return self._state == State.ARMED

    @property
    def can_finish_racing(self) -> bool:
        return self.phase == Phase.RACING and bool(self._attempts)

    @property
    def point_count(self) -> int:
        return len(self._raw)

    @property
    def current_line(self) -> list:
        """The in-progress or under-review lap as ``[(x, z), ...]`` for drawing."""
        if self._pit_mode:
            return list(self._pit_raw)
        return [(p[0], p[1]) for p in self._raw]

    @property
    def pit_lane(self) -> list:
        return self._pit_lane

    @property
    def can_add_pit(self) -> bool:
        return self._state == State.DONE and not self._pit_lane

    @property
    def has_pit(self) -> bool:
        return bool(self._pit_lane)

    @property
    def has_racing_line(self) -> bool:
        """Whether the CURRENT live class already has a recorded racing line —
        drives the DONE-screen button's ADD vs RE-DRIVE label."""
        return bool(self._racing_line)

    @property
    def pit_arming_in_box(self) -> bool:
        """True while a pit pass is armed but the driver is still parked in the
        pits — they must leave first so the next entry captures the full lane."""
        return (self._pit_mode and self._state == State.ARMING
                and not self._pit_seen_track)

    @property
    def is_loaded(self) -> bool:
        """True when the current map was loaded from disk for editing."""
        return self._loaded

    @property
    def is_untouched(self) -> bool:
        """Nothing captured or loaded yet — the very start of a fresh session,
        where an existing-track prompt may still be offered."""
        return (self._state == State.ARMING and not self._pit_mode
                and self._phase_idx == 0 and not self._single_phase
                and not (self._left or self._right or self._racing_line
                         or self._attempts or self._loaded))

    @property
    def left_edge(self) -> list:
        return self._left

    @property
    def right_edge(self) -> list:
        return self._right

    @property
    def racing_line(self) -> list:
        return self._racing_line

    @property
    def attempt_lines(self) -> list:
        return self._attempts

    @property
    def sf_line(self) -> dict:
        return self._sf

    @property
    def sector_marks(self) -> list:
        return self._sector_marks

    @property
    def track_name(self) -> str:
        return self._track

    @property
    def game(self) -> str:
        return self._game

    @property
    def car_class(self) -> str:
        return self._car_class

    @property
    def has_position(self) -> bool:
        return self._pos_ever_valid

    @property
    def status_text(self) -> str:
        if self._state == State.DONE:
            return "TRACK LOADED — EDIT OR SAVE" if self._loaded else "RECORDING COMPLETE"
        if not self._pos_ever_valid:
            # No world position yet — the recorder can't do anything without it,
            # so say so plainly rather than "cross the start line".
            return "WAITING FOR POSITION DATA — CHECK TELEMETRY"
        label = self.phase_label
        if self.phase == Phase.RACING:
            label = f"{label} ({self.attempt}/{self._target_attempts})"
        if self.phase == Phase.PIT:
            if self._state == State.ARMING:
                return "PIT LANE — DRIVE INTO THE PITS TO BEGIN"
            if self._state == State.RECORDING:
                return "RECORDING PIT LANE — DRIVE OUT TO FINISH"
            if self._state == State.REVIEW:
                return "PIT LANE — ACCEPT OR RE-DRIVE"
        if self._state == State.ARMING:
            return f"{label} — POSITION, THEN PRESS START"
        if self._state == State.ARMED:
            return f"ARMED — {label} RECORDS AT THE START/FINISH LINE"
        if self._state == State.RECORDING:
            return f"RECORDING {label}"
        if self._state == State.REVIEW:
            return f"{label} — ACCEPT OR RE-DRIVE"
        return label

    # ── Build + save ──────────────────────────────────────────────────────

    def build_map(self) -> TrackMap:
        # Racing lines are per car class: each class is its own profile so it can
        # carry its own gears (in the F1 titles the lines are near-identical, but
        # 2026 super-clip gearing differs from 2025 / F2, so the profiles stay
        # separate). Preserve every other class's entry and only (re)write the
        # current class's; editor-added gears / notes carry across untouched.
        lines = {c: dict(ln) for c, ln in self._loaded_lines.items()}
        if self._racing_line:
            prev = self._loaded_lines.get(self._car_class, {})
            attempts = len(self._attempts) or self._loaded_attempts
            lines[self._car_class] = {
                "racing_line": self._racing_line,
                "racing_attempts": attempts,
                "gears": prev.get("gears"),        # never recorded — filled via the editor
                "notes": prev.get("notes", ""),
            }
            # Shared-line games (F1 titles): seed any sibling class that has no
            # profile yet from this one — same geometry, gears left null until
            # filled per class. Never overwrites a sibling that already has its
            # own line (each class re-drives independently once seeded).
            for sib in trackmap.sibling_classes(self._game):
                if sib != self._car_class and not lines.get(sib, {}).get("racing_line"):
                    lines[sib] = {
                        "racing_line": self._racing_line,
                        "racing_attempts": attempts,
                        "gears": None,
                        "notes": "",
                    }
        now = _utc_now()
        return TrackMap(
            game=self._game,
            track=self._track,
            game_track_length_m=self._track_len,
            notes=self._notes,
            orientation=self._orientation,        # cosmetic display rotation, carried through edits
            created=self._loaded_created or now,   # first save stamps; edits keep it
            updated=now,
            author=self._author,
            left_edge=self._left,
            right_edge=self._right,
            pit_lane=self._pit_lane,
            sf_line=self._sf,
            sectors=self._sectors,
            sections=self._sections,
            lines=lines,
        )

    def save(self, tracks_dir: str, name: str = "") -> str:
        """Write the track map JSON and return its path."""
        tmap = self.build_map()
        if name:
            tmap.track = name
            self._track = name
        os.makedirs(tracks_dir, exist_ok=True)
        fname = f"{_slug(tmap.game)}_{_slug(tmap.track)}.json"
        path = os.path.join(tracks_dir, fname)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(tmap.to_dict(), fh, indent=2)
        return path
