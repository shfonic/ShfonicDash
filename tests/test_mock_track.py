"""Mock synthetic-circuit geometry — the position source the track recorder
is developed against. Pure helpers only (no threads), so these are fast and
deterministic."""
import math

import pytest

from telemetry import mock


def test_track_is_a_closed_loop():
    """Start (u=0) and end (u→1) coincide, so laps join seamlessly."""
    x0, z0 = mock._track_point(0.0)
    x1, z1 = mock._track_point(1.0 - 1e-6)
    assert math.hypot(x1 - x0, z1 - z0) < 1.0  # within a metre


def test_track_length_is_plausible():
    """A club circuit, not a dot or a continent."""
    assert 1000.0 < mock._TRACK_LENGTH < 5000.0


def test_track_point_moves_around_the_lap():
    """Distinct fractions map to distinct places (no degenerate collapse)."""
    pts = [mock._track_point(u / 8.0) for u in range(8)]
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            assert math.dist(pts[i], pts[j]) > 5.0


def test_heading_follows_the_tangent():
    """Heading points from the current sample toward the next one along track,
    in the shared model convention (F1 yaw: 0 faces +Z, atan2(dx, dz))."""
    u = 0.2
    x0, z0 = mock._track_point(u)
    x1, z1 = mock._track_point(u + 1e-3)
    expected = math.atan2(x1 - x0, z1 - z0)
    got = mock._track_heading(u)
    # Compare as unit vectors to sidestep the ±pi wrap.
    assert math.cos(got - expected) > 0.999


def test_phantom_opponents_shapes():
    """Three phantom cars with the opponents_pos dict shape, each within a
    few metres of the centreline near the player's lap fraction."""
    u = 0.3
    cars = mock._phantom_opponents(u, now=12.0)
    assert len(cars) == 3
    assert [c["idx"] for c in cars] == [1, 2, 3]
    for car in cars:
        assert set(car) == {"idx", "x", "z", "yaw"}
        # Each car sits within its longitudinal offset (≤45 m) + lateral
        # offset of the player's track point.
        px, pz = mock._track_point(u)
        assert math.hypot(car["x"] - px, car["z"] - pz) < 60.0


def test_phantom_opponent_comes_alongside():
    """Car A periodically sweeps fully alongside the centreline point —
    within the spotter's red 'alongside' box (|ahead| ≤ 5.6 m, |right| ≤ 4 m
    of a car on the centreline)."""
    from dashboard.widgets import spotter

    u = 0.3
    px, pz = mock._track_point(u)
    heading = mock._track_heading(u)
    alongside = False
    for tick in range(0, 220):          # ~22 s of mock time, one full sweep
        cars = mock._phantom_opponents(u, now=tick * 0.1)
        right, ahead = spotter.to_local(cars[0]["x"] - px, cars[0]["z"] - pz, heading)
        if spotter.threat_level(right, ahead) == 2:
            alongside = True
            break
    assert alongside


def test_mock_emits_valid_position():
    """A running mock populates world position + lap distance on every frame."""
    src = mock.MockTelemetry(preset="f1", session_type="hotlap")
    src.connect()
    try:
        # Poll briefly for the worker thread's first frame.
        data = None
        for _ in range(50):
            data = src.read()
            if data.pos_valid:
                break
            import time
            time.sleep(0.02)
        assert data is not None and data.pos_valid is True
        assert data.track == "Mock Circuit"
        assert 0.0 <= data.lap_distance <= mock._TRACK_LENGTH + 1.0
        assert -2000.0 < data.pos_x < 2000.0
        assert -2000.0 < data.pos_z < 2000.0
    finally:
        src.disconnect()
