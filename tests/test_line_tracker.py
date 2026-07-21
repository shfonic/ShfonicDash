"""
Tests for core.line_tracker — buffering per-frame racing-line offsets and
resampling a completed lap into an offset profile, driven by LapTracker events.

Pi-only (imports core.*, not shared with the companion).
"""

import math

from core.lap_tracker import LapCompleted, Restart, Rewind
from core.line_tracker import LineTracker
from core.telemetry_model import TelemetryData

N = 360
RADIUS = 100.0
LENGTH = 2 * math.pi * RADIUS   # circle circumference
RACING = [(RADIUS * math.cos(2 * math.pi * i / N),
           RADIUS * math.sin(2 * math.pi * i / N)) for i in range(N)]


def _frame(u, player_radius, lap_number=1):
    """A telemetry frame at lap fraction u, driving a circle of player_radius."""
    ang = 2 * math.pi * u
    return TelemetryData(
        pos_x=player_radius * math.cos(ang),
        pos_z=player_radius * math.sin(ang),
        pos_valid=True,
        lap_distance=u * LENGTH,
        lap_number=lap_number,
    )


def _drive_lap(tracker, player_radius, steps=720, lap_number=1):
    for i in range(steps):
        tracker.update(_frame(i / steps, player_radius, lap_number), [])


def test_active_requires_line_and_length():
    assert LineTracker(RACING, LENGTH).active is True
    assert LineTracker([], LENGTH).active is False
    assert LineTracker(RACING, 0).active is False


def test_completed_lap_profile_matches_constant_offset():
    tr = LineTracker(RACING, LENGTH)
    _drive_lap(tr, RADIUS + 2.0)                      # 2 m outside the line
    tr.update(_frame(0.0, RADIUS + 2.0, lap_number=2),
              [LapCompleted(num=1, time=90.0, invalid=False, s1=0, s2=0, s3=0,
                            rewinds=0)])
    prof = tr.take(1)
    assert prof is not None and len(prof) == N
    # Outward offset ⇒ positive (right of travel on a CCW circle); ~+20 dm.
    assert all(18 <= v <= 22 for v in prof)


def test_take_is_one_shot():
    tr = LineTracker(RACING, LENGTH)
    _drive_lap(tr, RADIUS + 1.0)
    tr.update(_frame(0.0, RADIUS + 1.0, lap_number=2),
              [LapCompleted(num=1, time=90.0, invalid=False, s1=0, s2=0, s3=0,
                            rewinds=0)])
    assert tr.take(1) is not None
    assert tr.take(1) is None


def test_rewind_discards_in_progress_lap():
    tr = LineTracker(RACING, LENGTH)
    # Drive half a lap, then a rewind wipes the buffer...
    for i in range(360):
        tr.update(_frame(i / 720, RADIUS + 5.0), [])
    tr.update(_frame(0.0, RADIUS + 5.0),
              [Rewind(lap_num=1, lap_time=45.0, lap_distance=0.0,
                      crossed_sf=False)])
    # ...then a clean lap at a different offset is what gets recorded.
    _drive_lap(tr, RADIUS + 1.0)
    tr.update(_frame(0.0, RADIUS + 1.0, lap_number=2),
              [LapCompleted(num=1, time=90.0, invalid=False, s1=0, s2=0, s3=0,
                            rewinds=0)])
    prof = tr.take(1)
    assert prof is not None
    assert all(8 <= v <= 12 for v in prof)     # ~+10 dm, not the discarded +50


def test_restart_discards_in_progress_lap():
    tr = LineTracker(RACING, LENGTH)
    for i in range(200):
        tr.update(_frame(i / 720, RADIUS + 8.0), [])
    tr.update(_frame(0.0, RADIUS + 8.0),
              [Restart(lap_num=1, lap_time=20.0, lap_distance=-5.0)])
    _drive_lap(tr, RADIUS + 1.0)
    tr.update(_frame(0.0, RADIUS + 1.0, lap_number=2),
              [LapCompleted(num=1, time=90.0, invalid=False, s1=0, s2=0, s3=0,
                            rewinds=0)])
    assert all(8 <= v <= 12 for v in tr.take(1))


def test_invalid_position_frames_skipped():
    tr = LineTracker(RACING, LENGTH)
    # A frame with no valid position must not enter the buffer.
    tr.update(TelemetryData(pos_valid=False, lap_distance=10.0), [])
    _drive_lap(tr, RADIUS + 1.0)
    tr.update(_frame(0.0, RADIUS + 1.0, lap_number=2),
              [LapCompleted(num=1, time=90.0, invalid=False, s1=0, s2=0, s3=0,
                            rewinds=0)])
    assert tr.take(1) is not None


def test_inactive_tracker_is_noop():
    tr = LineTracker([], LENGTH)
    tr.update(_frame(0.1, RADIUS + 1.0), [])
    tr.update(_frame(0.0, RADIUS + 1.0, lap_number=2),
              [LapCompleted(num=1, time=90.0, invalid=False, s1=0, s2=0, s3=0,
                            rewinds=0)])
    assert tr.take(1) is None
