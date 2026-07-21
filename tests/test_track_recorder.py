"""Track recorder state machine + geometry. Drives synthetic telemetry laps
around the mock circuit through the full LEFT → RIGHT → RACING flow."""
import json
import math

import pytest

from telemetry import mock
from core.telemetry_model import TelemetryData
from core.track_recorder import (
    Phase, State, TrackMap, TrackRecorder,
    _average_lines, _resample_line, _drop_reversals, _LINE_POINTS,
    _PIT_SPUR_ANGLE,
)

_TRACK_LEN = 3752.0


class _Driver:
    """Feeds the recorder frames for laps around the mock circuit. A recorded
    lap = cross() to begin, lap_around() for the body, cross() to end (review)."""

    def __init__(self, rec: TrackRecorder, n: int = 40, car_class: str = "formula1",
                 game: str = "f1_25"):
        self.rec = rec
        self.n = n
        self.lap = 1
        self.last_notes = []
        self.car_class = car_class
        self.game = game
        # Prime the LapTracker's previous-lap number without capturing anything.
        for i in range(1, 5):
            self.rec.update(self._frame(i / 100.0, 0.0))

    def _frame(self, u: float, offset: float, last_lap: float = 0.0,
               in_pits: bool = False, speed: float = 100.0) -> TelemetryData:
        x, z = mock._track_point(u)
        head = mock._track_heading(u)
        sector = 0 if u < 1 / 3 else (1 if u < 2 / 3 else 2)
        return TelemetryData(
            pos_valid=True,
            pos_x=x - math.sin(head) * offset,
            pos_z=z + math.cos(head) * offset,
            heading=head,
            speed=speed,
            lap_distance=u * _TRACK_LEN,
            sector=sector,
            lap_number=self.lap,
            lap_time=u * 90.0,
            last_lap=last_lap,
            in_pits=in_pits,
            track="Test Circuit",
            game=self.game,
            car_class=self.car_class,
        )

    def cross(self, last_lap: float = 88.5) -> None:
        self.lap += 1
        self.last_notes = self.rec.update(self._frame(0.0, 0.0, last_lap=last_lap))

    def lap_around(self, offset: float = 0.0, pit_at=None) -> None:
        for i in range(1, self.n):
            u = i / self.n
            in_pits = pit_at is not None and pit_at[0] <= u < pit_at[1]
            self.rec.update(self._frame(u, offset, in_pits=in_pits))

    def record_lap(self, offset: float = 0.0, pit_at=None) -> None:
        self.rec.arm()          # press START
        self.cross()            # crossing the line begins the recorded lap
        self.lap_around(offset, pit_at=pit_at)
        self.cross()            # next crossing ends it (review)


# ── Geometry ─────────────────────────────────────────────────────────────────

def test_resample_line_produces_fixed_point_count():
    raw = [(math.cos(i / 20), math.sin(i / 20), float(i)) for i in range(20)]
    line = _resample_line(raw, n=100)
    assert len(line) == 100


def test_resample_line_drops_backwards_distance():
    # A glitch point with a smaller distance must not break interpolation.
    raw = [(0.0, 0.0, 0.0), (1.0, 0.0, 10.0), (0.5, 0.0, 3.0), (2.0, 0.0, 20.0)]
    line = _resample_line(raw, n=5)
    assert len(line) == 5
    assert line[0] == pytest.approx((0.0, 0.0))
    assert line[-1] == pytest.approx((2.0, 0.0))


def test_average_lines_is_the_median_per_station():
    a = [(0.0, 0.0), (10.0, 0.0)]
    b = [(2.0, 0.0), (12.0, 0.0)]
    c = [(4.0, 0.0), (14.0, 0.0)]
    avg = _average_lines([a, b, c])
    assert avg[0] == pytest.approx((2.0, 0.0))
    assert avg[1] == pytest.approx((12.0, 0.0))


# ── State machine ──────────────────────────────────────────────────────────

def test_full_recording_flow_reaches_done():
    rec = TrackRecorder(racing_attempts=3)
    d = _Driver(rec)

    assert rec.phase == Phase.LEFT and rec.state == State.ARMING

    d.record_lap(offset=-6.0)
    assert rec.phase == Phase.LEFT and rec.can_accept
    rec.accept()

    assert rec.phase == Phase.RIGHT and rec.state == State.ARMING
    d.record_lap(offset=+6.0)
    assert rec.can_accept
    rec.accept()

    assert rec.phase == Phase.RACING
    for _ in range(3):
        d.record_lap(offset=0.0)
        assert rec.can_accept
        rec.accept()

    assert rec.phase == Phase.DONE and rec.state == State.DONE

    tmap = rec.build_map()
    assert len(tmap.left_edge) == _LINE_POINTS
    assert len(tmap.right_edge) == _LINE_POINTS
    line = tmap.lines["formula1"]                       # keyed by the driven class
    assert len(line["racing_line"]) == _LINE_POINTS
    assert line["racing_attempts"] == 3
    assert tmap.track == "Test Circuit"


def test_edges_are_laterally_separated():
    rec = TrackRecorder(racing_attempts=1)
    d = _Driver(rec)
    d.record_lap(offset=-6.0); rec.accept()   # left
    d.record_lap(offset=+6.0); rec.accept()   # right

    left = rec.left_edge
    right = rec.right_edge
    # Average separation should be near the 12 m between the two offset lines.
    seps = [math.dist(left[i], right[i]) for i in range(0, _LINE_POINTS, 20)]
    assert sum(seps) / len(seps) > 8.0


def test_sector_boundaries_are_captured():
    rec = TrackRecorder(racing_attempts=1)
    d = _Driver(rec)
    d.record_lap(offset=0.0); rec.accept()   # left captures sector marks

    tmap = rec.build_map()
    indices = {m["index"] for m in tmap.sectors}
    assert 1 in indices and 2 in indices
    for m in tmap.sectors:
        assert "pos" in m and "lap_dist_m" in m


def test_sf_line_captured_at_crossing():
    rec = TrackRecorder(racing_attempts=1)
    d = _Driver(rec)
    d.record_lap(offset=0.0)
    assert "pos" in rec.sf_line and "heading" in rec.sf_line


def test_status_reports_missing_position_data():
    """Without world position the recorder can't do anything — it must say so
    rather than misleadingly telling the driver to cross the start line."""
    rec = TrackRecorder()
    assert "WAITING FOR POSITION" in rec.status_text
    # Frames with no valid position keep the diagnostic up.
    rec.update(TelemetryData(pos_valid=False, lap_number=1, game="f1_25"))
    assert "WAITING FOR POSITION" in rec.status_text
    # Once position arrives, the normal arming prompt returns.
    rec.update(TelemetryData(pos_valid=True, pos_x=1.0, pos_z=2.0, lap_number=1))
    assert "WAITING FOR POSITION" not in rec.status_text
    assert "PRESS START" in rec.status_text


def test_start_button_arms_then_begins_at_crossing():
    """Recording must not begin until START is pressed AND the line is crossed —
    this is the repositioning gap between phases (idle until you're ready)."""
    rec = TrackRecorder(racing_attempts=1)
    d = _Driver(rec)
    d.record_lap(offset=-6.0); rec.accept()   # left done → idle for right
    assert rec.state == State.ARMING and rec.phase == Phase.RIGHT

    # Crossing the line without START does nothing (still repositioning).
    d.cross()
    assert rec.state == State.ARMING
    assert rec.point_count == 0

    # START arms; the next crossing begins recording.
    rec.arm()
    assert rec.is_armed
    d.cross()
    assert rec.state == State.RECORDING


def test_can_record_first_flying_lap():
    """START + a single S/F crossing begins recording with no prior completed
    lap (the hotlap case: start on the run-up, press START, cross the line)."""
    rec = TrackRecorder(racing_attempts=1)
    meta = dict(track="T", game="f1_25", car_class="formula1")
    rec.update(TelemetryData(pos_valid=True, pos_x=0.0, pos_z=0.0, lap_number=1, **meta))
    rec.arm()
    assert rec.is_armed
    # First-ever S/F crossing (lap 1 → 2); no LapCompleted required.
    rec.update(TelemetryData(pos_valid=True, pos_x=1.0, pos_z=1.0, lap_number=2, **meta))
    assert rec.state == State.RECORDING


def test_start_begins_on_runup_crossing_without_lap_tick():
    """Time Trial / hotlap: crossing S/F from the negative run-up starts a timed
    lap WITHOUT bumping the lap number. Recording must still begin at that
    crossing (this also covers the in-game 'restart lap')."""
    rec = TrackRecorder(racing_attempts=1)
    meta = dict(track="T", game="f1_25", car_class="formula1")
    # On the run-up before the S/F line: negative distance, lap 1.
    rec.update(TelemetryData(pos_valid=True, pos_x=0, pos_z=0, lap_number=1,
                             lap_distance=-120.0, **meta))
    rec.arm()
    rec.update(TelemetryData(pos_valid=True, pos_x=1, pos_z=1, lap_number=1,
                             lap_distance=-30.0, **meta))
    assert rec.is_armed  # not across the line yet
    # Cross S/F: distance goes >= 0, lap number unchanged.
    rec.update(TelemetryData(pos_valid=True, pos_x=2, pos_z=2, lap_number=1,
                             lap_distance=5.0, **meta))
    assert rec.state == State.RECORDING


def test_cancel_arm_returns_to_idle():
    rec = TrackRecorder()
    rec.update(TelemetryData(pos_valid=True, pos_x=0.0, pos_z=0.0, lap_number=1))
    rec.arm()
    assert rec.is_armed
    rec.cancel_arm()
    assert rec.state == State.ARMING and not rec.is_armed


def test_redo_discards_lap_and_rearms_same_phase():
    rec = TrackRecorder(racing_attempts=1)
    d = _Driver(rec)
    d.record_lap(offset=-6.0)
    assert rec.can_accept and rec.phase == Phase.LEFT
    rec.redo()
    assert rec.state == State.ARMING and rec.phase == Phase.LEFT
    assert rec.left_edge == []


def test_rewind_during_recording_rearms():
    rec = TrackRecorder(racing_attempts=1)
    d = _Driver(rec)
    rec.arm()
    d.cross()                 # begin recording the left edge
    d.lap_around(offset=-6.0)
    assert rec.state == State.RECORDING
    # A rewind: lap number jumps backwards.
    d.lap -= 2
    notes = rec.update(d._frame(0.4, -6.0))
    # Re-armed for an automatic retry at the next crossing (no re-press of START).
    assert rec.state == State.ARMED
    assert "REWIND — RE-DRIVE" in notes


def test_pit_frames_are_excluded():
    rec = TrackRecorder(racing_attempts=1)
    d = _Driver(rec)
    rec.arm()
    d.cross()
    d.lap_around(offset=0.0, pit_at=(0.4, 0.6))   # 20% of the lap in the pits
    before = rec.point_count
    d.cross()
    # Roughly 80% of the interior frames captured (pit window skipped).
    assert before < d.n
    assert before > d.n * 0.6


def test_racing_line_averages_multiple_attempts():
    rec = TrackRecorder(racing_attempts=3)
    d = _Driver(rec)
    d.record_lap(offset=-6.0); rec.accept()   # left
    d.record_lap(offset=+6.0); rec.accept()   # right
    # Three racing attempts at -3, 0, +3 → median line ≈ centre (0).
    d.record_lap(offset=-3.0); rec.accept()
    assert rec.phase == Phase.RACING          # still going
    d.record_lap(offset=0.0); rec.accept()
    d.record_lap(offset=+3.0); rec.accept()
    assert rec.phase == Phase.DONE
    assert len(rec.racing_line) == _LINE_POINTS


def test_finish_racing_early():
    rec = TrackRecorder(racing_attempts=5)
    d = _Driver(rec)
    d.record_lap(offset=-6.0); rec.accept()
    d.record_lap(offset=+6.0); rec.accept()
    d.record_lap(offset=0.0); rec.accept()    # one racing attempt banked
    assert rec.can_finish_racing
    rec.finish_racing()
    assert rec.phase == Phase.DONE
    assert len(rec.racing_line) == _LINE_POINTS


def _drive_to_done(rec: TrackRecorder, car_class: str = "formula1",
                   game: str = "f1_25") -> "_Driver":
    d = _Driver(rec, car_class=car_class, game=game)
    d.record_lap(offset=-6.0); rec.accept()
    d.record_lap(offset=+6.0); rec.accept()
    d.record_lap(offset=0.0); rec.accept()
    assert rec.phase == Phase.DONE
    return d


def test_pit_lane_capture_bounded_by_in_pits_flag():
    rec = TrackRecorder(racing_attempts=1)
    d = _drive_to_done(rec)

    assert rec.can_add_pit
    rec.start_pit_lane()
    assert rec.phase == Phase.PIT and rec.state == State.ARMING

    rec.update(d._frame(0.0, 0.0, in_pits=False))   # on track — arms the entry
    # Drive in (rising edge starts capture), through, and out (falling edge ends).
    for i in range(10):
        rec.update(d._frame(0.05 * i, 0.0, in_pits=True))
    assert rec.state == State.RECORDING
    rec.update(d._frame(0.6, 0.0, in_pits=False))   # exit
    assert rec.state == State.REVIEW

    rec.accept()
    assert rec.phase == Phase.DONE
    tmap = rec.build_map()
    assert len(tmap.pit_lane) >= 2      # simplified open polyline
    assert not rec.can_add_pit          # only one pit lane


def test_pit_arm_in_box_waits_for_a_clean_entry():
    """Arming the pit pass while parked in the box must NOT start on the drive-out
    (that captures only the box→exit half). It waits until the driver has been on
    track, then the next real entry captures the full lane."""
    rec = TrackRecorder(racing_attempts=1)
    d = _drive_to_done(rec)
    rec.start_pit_lane()

    # Sitting in the box: already in_pits, but capture is held off.
    for u in (0.90, 0.92):
        rec.update(d._frame(u, 0.0, in_pits=True, speed=0.0))
    assert rec.state == State.ARMING
    assert rec.pit_arming_in_box

    # Drive out onto the track — still armed, but now a clean entry is allowed.
    rec.update(d._frame(0.95, 0.0, in_pits=False, speed=80.0))
    assert rec.state == State.ARMING
    assert not rec.pit_arming_in_box

    # A lap on track, then a genuine pit entry starts the capture.
    rec.update(d._frame(0.5, 0.0, in_pits=False, speed=80.0))
    for u in (0.10, 0.12, 0.14):
        rec.update(d._frame(u, 0.0, in_pits=True, speed=80.0))
    assert rec.state == State.RECORDING
    rec.update(d._frame(0.20, 0.0, in_pits=False, speed=80.0))   # exit → review
    assert rec.state == State.REVIEW

    rec.accept()
    assert rec.phase == Phase.DONE and len(rec.pit_lane) >= 2


def test_drop_reversals_removes_garage_uturn_spur():
    """A near-180° reversal (the line doubling back into the garage bay) is
    removed; gentle pit-lane corners well under the threshold survive."""
    # Straight run with a bay spur: out to (25, 8), then straight back.
    pts = [(0, 0), (10, 0), (20, 0), (25, 0), (25, 8), (25.1, 0.2),
           (30, 0), (40, 0), (50, 0)]
    out = _drop_reversals(pts, _PIT_SPUR_ANGLE)
    assert out[0] == (0, 0) and out[-1] == (50, 0)   # endpoints preserved
    assert (25, 8) not in out                        # the U-turn apex is gone

    # A gentle line (no sharp reversal) is returned unchanged.
    gentle = [(0, 0), (10, 1), (20, 3), (30, 6), (40, 10)]
    assert _drop_reversals(gentle, _PIT_SPUR_ANGLE) == gentle


def test_excise_box_removes_the_garage_detour():
    """The detour into the garage bay (points near a genuine stop) is dropped and
    the through-lane bridges straight past it. No stop → nothing excised."""
    rec = TrackRecorder(racing_attempts=1)
    rec._pit_box = (50.0, 15.0)
    rec._pit_box_speed = 0.0                       # a real stop happened
    # Straight through-lane along x with a bulge into the box at (50, 15).
    pts = [(0.0, 0.0), (20.0, 0.0), (45.0, 0.0), (50.0, 15.0),
           (55.0, 0.0), (80.0, 0.0), (100.0, 0.0)]
    out = rec._excise_box(pts)
    assert (50.0, 15.0) not in out                 # the bay detour is gone
    assert out[0] == (0.0, 0.0) and out[-1] == (100.0, 0.0)   # through-lane preserved

    rec._pit_box_speed = 80.0                      # never stopped → leave it alone
    assert rec._excise_box(pts) == pts


def test_finish_pit_pulls_close_ends_onto_the_track():
    """The capture reaches the merge, so a tip within the snap band is pulled
    exactly onto the racing line (no perpendicular stub); a tip still far off
    (slip-road never driven) is left where it is."""
    rec = TrackRecorder(racing_attempts=1)
    rec._racing_line = [(float(x), 0.0) for x in range(0, 101, 5)]  # line along z=0

    rec._pit_raw = [(10.0, 5.0), (40.0, 30.0), (90.0, 5.0)]         # ends 5 m off (<= snap max)
    lane = rec._finish_pit()
    assert lane[0] == (10.0, 0.0) and lane[-1] == (90.0, 0.0)       # tips pulled onto the line

    rec._pit_raw = [(10.0, 20.0), (40.0, 30.0), (90.0, 20.0)]       # ends 20 m off (> snap max)
    lane = rec._finish_pit()
    assert lane[0][1] != 0.0 and lane[-1][1] != 0.0                 # left alone


def test_pit_lead_in_keeps_the_entry_slip_road():
    """The buffered on-track approach is trimmed to where the car left the racing
    line, so the entry slip-road is kept but the shared straight before it isn't."""
    rec = TrackRecorder(racing_attempts=1)
    rec._racing_line = [(float(x), 0.0) for x in range(0, 101, 5)]
    # On the line, then peeling away in +z toward the pit entry.
    rec._pit_track_buf = [(35.0, 0.0), (40.0, 0.0), (45.0, 0.0),
                          (48.0, 6.0), (50.0, 20.0), (52.0, 35.0)]
    lead = rec._lead_in()
    assert lead[-1] == (52.0, 35.0)          # ends at the pit entry
    assert lead[0] == (45.0, 0.0)            # captured back onto the line (within the 3 m band)
    assert (48.0, 6.0) in lead               # the peel-off point is kept
    assert (50.0, 20.0) in lead              # the slip-road divergence is kept
    assert (40.0, 0.0) not in lead           # shared straight before the merge trimmed
    assert (35.0, 0.0) not in lead


def test_pit_lane_is_optional():
    rec = TrackRecorder(racing_attempts=1)
    _drive_to_done(rec)
    # Never entering the pit pass leaves an empty pit lane — still saveable.
    tmap = rec.build_map()
    assert tmap.pit_lane == []


# ── Pit speed-gating ───────────────────────────────────────────────────────────

def test_pit_speed_gate_drops_stationary_box_stop():
    """The stationary box stop (speed ≈ 0) is dropped so the lane bridges cleanly
    across it rather than collapsing into a point cluster."""
    rec = TrackRecorder(racing_attempts=1)
    d = _drive_to_done(rec)
    rec.start_pit_lane()
    assert rec.phase == Phase.PIT and rec.state == State.ARMING

    rec.update(d._frame(0.05, 0.0, in_pits=False, speed=80.0))   # on track first
    for u in (0.10, 0.12, 0.14):                     # drive in (rising edge seeds)
        rec.update(d._frame(u, 0.0, in_pits=True, speed=80.0))
    for _ in range(3):                               # stop in the box (dropped)
        rec.update(d._frame(0.16, 0.0, in_pits=True, speed=0.0))
    for u in (0.18, 0.20, 0.22):                     # drive out
        rec.update(d._frame(u, 0.0, in_pits=True, speed=80.0))
    rec.update(d._frame(0.24, 0.0, in_pits=False, speed=80.0))   # exit → review
    assert rec.state == State.REVIEW

    raw = rec._pit_raw
    # lead-in(0.05) + entry(0.10) + 2 in + 3 out + exit(0.24) — the box stop gone.
    assert len(raw) == 8
    box = mock._track_point(0.16)
    assert all(abs(x - box[0]) > 1e-6 or abs(z - box[1]) > 1e-6 for x, z in raw)

    rec.accept()
    assert rec.phase == Phase.DONE
    assert len(rec.pit_lane) >= 2


# ── Editing an existing map ─────────────────────────────────────────────────────

def _reprime(rec: TrackRecorder, d: "_Driver", offset: float = 0.0) -> None:
    """redrive() nulls the S/F-crossing detector (update() doesn't track it while
    DONE); feed a few idle frames so the next crossing is seen, as telemetry does
    before the driver reaches the line."""
    for i in range(1, 5):
        rec.update(d._frame(i / 100.0, offset))


def test_track_map_sections_round_trip():
    secs = [{"turn": "1", "name": "Turn 1", "type": "corner",
             "start_m": 100, "end_m": 200, "apex_m": 150}]
    m = TrackMap(game="f1_25", track="X", sections=secs, left_edge=[(0, 0), (1, 1)])
    d = m.to_dict()
    assert d["sections"] == secs
    assert TrackMap.from_dict(d).sections == secs


def test_track_map_orientation_round_trip():
    m = TrackMap(game="f1_25", track="X", orientation=75.0)
    assert m.to_dict()["orientation"] == 75.0
    assert TrackMap.from_dict(m.to_dict()).orientation == 75.0
    # Absent/blank orientation defaults to 0.0 (old files predate the field).
    assert TrackMap.from_dict({"game": "f1_25"}).orientation == 0.0
    assert TrackMap().to_dict()["orientation"] == 0.0


def test_load_existing_jumps_to_done_and_preserves_data():
    src = TrackRecorder(racing_attempts=1)
    d = _drive_to_done(src)
    src.start_pit_lane()
    src.update(d._frame(0.05, 0.0, in_pits=False, speed=80.0))   # on track first
    for u in (0.10, 0.12, 0.14):
        src.update(d._frame(u, 0.0, in_pits=True, speed=80.0))
    src.update(d._frame(0.16, 0.0, in_pits=False, speed=80.0))
    src.accept()
    tmap = src.build_map()
    tmap.sections = [{"turn": "1", "type": "corner", "start_m": 10, "end_m": 20}]

    rec = TrackRecorder(racing_attempts=1)
    rec.update(d._frame(0.02, 0.0))          # prime the live class (formula1) being edited
    rec.load_existing(tmap)
    assert rec.state == State.DONE and rec.phase == Phase.DONE
    assert rec.is_loaded and not rec.is_untouched
    assert rec.left_edge and rec.right_edge and rec.racing_line and rec.has_pit

    out = rec.build_map()
    assert (out.lines["formula1"]["racing_attempts"]
            == tmap.lines["formula1"]["racing_attempts"])   # kept (raw laps aren't stored)
    assert out.sections == tmap.sections                    # carried through unchanged


def test_file_reads_and_writes_per_class_lines():
    """A track file carries its racing lines under `lines`, keyed by car class,
    with no stray top-level racing_line/car_class."""
    src = {
        "format_version": 1,
        "game": "f1_25", "track": "Silverstone",
        "left_edge": [[0, 0]], "right_edge": [[1, 1]],
        "sections": [{"turn": "1", "type": "corner"}],
        "lines": {
            "formula1_2026": {"racing_line": [[0.0, 0.0], [10.0, 1.0]],
                              "racing_attempts": 3, "gears": None, "notes": ""},
        },
    }
    tmap = TrackMap.from_dict(src)
    assert list(tmap.lines) == ["formula1_2026"]
    assert tmap.lines["formula1_2026"]["racing_line"] == [(0.0, 0.0), (10.0, 1.0)]
    assert tmap.lines["formula1_2026"]["racing_attempts"] == 3
    out = tmap.to_dict()
    assert out["format_version"] == 1
    assert "racing_line" not in out and "car_class" not in out   # no stray top-level fields


def test_second_class_line_added_without_disturbing_the_first():
    """In a multi-class game (PC2), re-driving a second car class adds its line
    alongside the first; the shared geometry and the other class's line are
    untouched."""
    src = TrackRecorder(racing_attempts=1)
    _drive_to_done(src, car_class="gt3", game="pcars2")
    tmap = src.build_map()
    assert list(tmap.lines) == ["gt3"]
    gt3_line = list(tmap.lines["gt3"]["racing_line"])
    gt3_edge = list(tmap.left_edge)

    rec = TrackRecorder(racing_attempts=1)
    d2 = _Driver(rec, car_class="formula_rookie", game="pcars2")   # a different class
    rec.load_existing(tmap)                         # keeps the live class
    rec.redrive(Phase.RACING)
    _reprime(rec, d2, offset=2.0)
    d2.record_lap(offset=2.0); rec.accept()

    out = rec.build_map()
    assert set(out.lines) == {"gt3", "formula_rookie"}
    assert out.lines["gt3"]["racing_line"] == gt3_line        # first class untouched
    assert out.lines["formula_rookie"]["racing_line"]         # second class added
    assert out.left_edge == gt3_edge                          # shared edges unchanged


def test_f1_classes_seed_all_three_siblings():
    """F1 titles share one racing line across classes, so recording any ONE
    class seeds all three profiles (`formula1`, `formula1_2026`, `f2`) with the
    same line — each still carries its own `gears`, filled in independently
    later (2026 super-clip gearing differs from 2025)."""
    src = TrackRecorder(racing_attempts=1)
    _drive_to_done(src, car_class="formula1", game="f1_25")
    tmap = src.build_map()
    assert set(tmap.lines) == {"formula1", "formula1_2026", "f2"}
    assert tmap.lines["formula1_2026"]["racing_line"] == tmap.lines["formula1"]["racing_line"]
    assert tmap.lines["formula1_2026"]["gears"] is None       # not driven — gears unfilled

    # Re-driving one sibling's line replaces only that profile; the other two
    # (already seeded) are left untouched.
    rec = TrackRecorder(racing_attempts=1)
    d2 = _Driver(rec, car_class="formula1_2026", game="f1_25")
    rec.load_existing(tmap)
    rec.redrive(Phase.RACING)
    _reprime(rec, d2, offset=2.0)
    d2.record_lap(offset=2.0); rec.accept()

    out = rec.build_map()
    assert set(out.lines) == {"formula1", "formula1_2026", "f2"}
    assert out.lines["formula1"]["racing_line"] == tmap.lines["formula1"]["racing_line"]  # untouched
    assert out.lines["f2"]["racing_line"] == tmap.lines["f2"]["racing_line"]              # untouched


def test_notes_and_gears_survive_a_redrive():
    """Track notes, per-class notes, and editor-added gears are preserved when a
    class's line is re-driven (the recorder never writes gears itself)."""
    src = TrackRecorder(racing_attempts=1)
    d = _drive_to_done(src)
    tmap = src.build_map()
    tmap.notes = "Missing F2 line"
    tmap.lines["formula1"]["gears"] = [7, 6, 5]         # added later via the editor
    tmap.lines["formula1"]["notes"] = "S2 still rough"

    rec = TrackRecorder(racing_attempts=1)
    rec.update(d._frame(0.02, 0.0))                     # live class formula1
    rec.load_existing(tmap)
    rec.redrive(Phase.RACING)
    _reprime(rec, d, offset=1.0)
    d.record_lap(offset=1.0); rec.accept()

    out = rec.build_map()
    assert out.notes == "Missing F2 line"
    assert out.lines["formula1"]["gears"] == [7, 6, 5]  # never touched by the recorder
    assert out.lines["formula1"]["notes"] == "S2 still rough"


def test_redrive_left_replaces_only_left():
    rec = TrackRecorder(racing_attempts=1)
    d = _drive_to_done(rec)
    left_orig = list(rec.left_edge)
    right_orig = list(rec.right_edge)
    racing_orig = list(rec.racing_line)

    rec.redrive(Phase.LEFT)
    assert rec.phase == Phase.LEFT and rec.state == State.ARMING
    _reprime(rec, d, offset=-12.0)
    d.record_lap(offset=-12.0)
    rec.accept()

    assert rec.phase == Phase.DONE
    assert rec.right_edge == right_orig      # untouched
    assert rec.racing_line == racing_orig    # untouched
    assert rec.left_edge != left_orig        # replaced


def test_redrive_racing_returns_to_done():
    rec = TrackRecorder(racing_attempts=1)
    d = _drive_to_done(rec)
    left_orig = list(rec.left_edge)

    rec.redrive(Phase.RACING)
    assert rec.phase == Phase.RACING
    _reprime(rec, d, offset=2.0)
    d.record_lap(offset=2.0)
    rec.accept()

    assert rec.phase == Phase.DONE and rec.state == State.DONE
    assert rec.left_edge == left_orig        # edges untouched
    assert rec.racing_line                   # re-driven


def test_discard_all_clears_everything():
    rec = TrackRecorder(racing_attempts=1)
    _drive_to_done(rec)
    rec.discard_all()
    assert rec.is_untouched
    assert rec.phase == Phase.LEFT and rec.state == State.ARMING
    assert not (rec.left_edge or rec.right_edge or rec.racing_line)
    assert not rec.is_loaded


def test_rdp_simplifies_collinear_points():
    from core.track_recorder import _rdp
    line = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0), (4.0, 0.0)]
    assert _rdp(line, eps=0.5) == [(0.0, 0.0), (4.0, 0.0)]
    # A kink is preserved.
    kinked = [(0.0, 0.0), (2.0, 5.0), (4.0, 0.0)]
    assert len(_rdp(kinked, eps=0.5)) == 3


def test_restart_clears_everything():
    rec = TrackRecorder(racing_attempts=1)
    d = _Driver(rec)
    d.record_lap(offset=-6.0); rec.accept()   # left banked
    d.record_lap(offset=+6.0)                  # right under review
    assert rec.left_edge and rec.can_accept

    rec.restart()
    assert rec.phase == Phase.LEFT and rec.state == State.ARMING
    assert rec.left_edge == [] and rec.right_edge == []
    assert rec.point_count == 0


def test_phases_progress_states():
    rec = TrackRecorder(racing_attempts=1)
    d = _Driver(rec)
    # At the start: left is current, the rest pending.
    labels = dict(rec.phases)
    assert labels["LEFT EDGE"] == "current"
    assert labels["RIGHT EDGE"] == "pending"

    d.record_lap(offset=-6.0); rec.accept()    # left done → right current
    labels = dict(rec.phases)
    assert labels["LEFT EDGE"] == "done"
    assert labels["RIGHT EDGE"] == "current"

    d.record_lap(offset=+6.0); rec.accept()    # right done
    d.record_lap(offset=0.0); rec.accept()     # racing done → all done
    labels = dict(rec.phases)
    assert labels["RACING LINE"] == "done"
    # Pit only appears once its pass is started.
    assert "PIT LANE" not in labels
    rec.start_pit_lane()
    assert dict(rec.phases)["PIT LANE"] == "current"


def test_save_writes_roundtrippable_json(tmp_path):
    rec = TrackRecorder(racing_attempts=1)
    d = _Driver(rec)
    d.record_lap(offset=-6.0); rec.accept()
    d.record_lap(offset=+6.0); rec.accept()
    d.record_lap(offset=0.0); rec.accept()
    assert rec.phase == Phase.DONE

    path = rec.save(str(tmp_path), name="Silverstone GP")
    with open(path) as fh:
        loaded = json.load(fh)
    tmap = TrackMap.from_dict(loaded)
    assert tmap.track == "Silverstone GP"
    assert tmap.game == "f1_25"
    assert len(tmap.left_edge) == _LINE_POINTS
    assert len(tmap.lines["formula1"]["racing_line"]) == _LINE_POINTS
    assert loaded["format_version"] == 1
    assert path.endswith("f1-25_silverstone-gp.json")


def test_metadata_stamped_and_preserved_across_edits():
    """created/updated/author are stamped on save; a re-drive keeps the original
    created + author (config author only fills a blank) and refreshes updated."""
    import re as _re
    iso = _re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    rec = TrackRecorder(racing_attempts=1, author="Richard Hawes")
    _drive_to_done(rec)
    m1 = rec.build_map()
    assert iso.match(m1.created) and iso.match(m1.updated)
    assert m1.created == m1.updated          # first save: created == updated
    assert m1.author == "Richard Hawes"

    # Round-trips through JSON untouched.
    assert TrackMap.from_dict(m1.to_dict()).author == "Richard Hawes"

    # Editing an existing map keeps created + author, even if the editor was
    # started with a different (or empty) config author.
    rec2 = TrackRecorder(racing_attempts=1, author="")
    d2 = _Driver(rec2, car_class="formula1_2026")
    rec2.load_existing(m1)
    rec2.redrive(Phase.RACING)
    _reprime(rec2, d2, offset=2.0)
    d2.record_lap(offset=2.0); rec2.accept()
    m2 = rec2.build_map()
    assert m2.created == m1.created          # original creation stamp kept
    assert m2.author == "Richard Hawes"      # original author preserved


def test_orientation_preserved_across_a_redrive():
    """The cosmetic display rotation, set only in the map utility, is carried
    through a re-drive of one line untouched (the recorder never sets it)."""
    rec = TrackRecorder(racing_attempts=1)
    m1 = rec.build_map()
    m1.orientation = 75.0                    # as if set in the editor
    rec2 = TrackRecorder(racing_attempts=1)
    d2 = _Driver(rec2, car_class="formula1_2026")
    rec2.load_existing(m1)
    rec2.redrive(Phase.RACING)
    _reprime(rec2, d2, offset=2.0)
    d2.record_lap(offset=2.0); rec2.accept()
    assert rec2.build_map().orientation == 75.0


def _pit_frame(x, z, in_pits=False, pit_limiter=False, speed=100.0):
    return TelemetryData(pos_valid=True, pos_x=x, pos_z=z, speed=speed,
                         in_pits=in_pits, pit_limiter=pit_limiter,
                         game="f1_25", car_class="formula1")


def test_pit_exit_holds_through_under_track_crossover_while_limiter_on():
    """Abu Dhabi's pit exit road runs *under* the main straight — the 2-D point
    sits on the racing line there even though the car is still in the pit lane.
    Proximity alone would cut the capture off at the crossover; the limiter gate
    keeps it going until the driver actually rejoins the track (limiter off)."""
    rec = TrackRecorder(racing_attempts=1)
    rec._racing_line = [(float(x), 0.0) for x in range(0, 101, 5)]  # line along z=0
    rec._state = State.RECORDING
    rec._pit_exiting = False
    rec._pit_raw = [(10.0, 40.0)]                       # in the pit lane, 40 m off

    # Out the far end of the pit lane, still on the exit road (limiter held on).
    rec._update_pit(_pit_frame(20.0, 40.0, in_pits=False, pit_limiter=True))
    assert rec._pit_exiting is True and rec.state == State.RECORDING

    # The crossover: dead on the racing line (z=0) but under it — limiter still
    # on, so this must NOT be read as rejoining.
    rec._update_pit(_pit_frame(50.0, 0.0, in_pits=False, pit_limiter=True))
    assert rec.state == State.RECORDING

    # Reached the track and switched the limiter off → now it rejoins.
    rec._update_pit(_pit_frame(60.0, 0.0, in_pits=False, pit_limiter=False))
    assert rec.state == State.REVIEW


def test_pit_exit_rejoins_on_proximity_when_no_limiter():
    """Sources that don't populate the limiter (it reads False) keep the old
    proximity-only behaviour: on the line ⇒ rejoined."""
    rec = TrackRecorder(racing_attempts=1)
    rec._racing_line = [(float(x), 0.0) for x in range(0, 101, 5)]
    rec._state = State.RECORDING
    rec._pit_exiting = False
    rec._pit_raw = [(10.0, 40.0)]

    rec._update_pit(_pit_frame(20.0, 40.0, in_pits=False, pit_limiter=False))
    assert rec.state == State.RECORDING          # still 40 m off the line
    rec._update_pit(_pit_frame(50.0, 0.0, in_pits=False, pit_limiter=False))
    assert rec.state == State.REVIEW             # on the line, no limiter → rejoined
