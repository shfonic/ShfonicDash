"""Spotter radar projection + threat maths — pure module-level functions,
no pygame surfaces needed (same pattern as test_tyre_chip.py)."""
import math

import pytest

from dashboard.widgets.spotter import (
    ALONGSIDE_LAT_M,
    CAR_LENGTH_M,
    CAR_WIDTH_M,
    car_corners,
    threat_level,
    to_local,
)


# ── to_local ─────────────────────────────────────────────────────────────────
# Model heading convention: 0 faces +Z, increasing toward +X;
# forward = (sin h, cos h), right = (cos h, -sin h).

def test_to_local_heading_zero():
    """Facing +Z: a car 10 m up the +Z axis is dead ahead; +X is to the right."""
    assert to_local(0.0, 10.0, 0.0) == pytest.approx((0.0, 10.0))
    assert to_local(3.0, 0.0, 0.0) == pytest.approx((3.0, 0.0))


def test_to_local_heading_quarter_turn():
    """Facing +X (heading π/2): a car 10 m up the +X axis is dead ahead,
    and a car up the +Z axis is now on the LEFT (negative right)."""
    assert to_local(10.0, 0.0, math.pi / 2) == pytest.approx((0.0, 10.0))
    assert to_local(0.0, 10.0, math.pi / 2) == pytest.approx((-10.0, 0.0))


def test_to_local_heading_reversed():
    """Facing -Z (heading π): ahead/right both flip sign."""
    right, ahead = to_local(3.0, 10.0, math.pi)
    assert right == pytest.approx(-3.0)
    assert ahead == pytest.approx(-10.0)


# ── threat_level ─────────────────────────────────────────────────────────────

def test_threat_far_away_is_clear():
    assert threat_level(0.0, 30.0) == 0


def test_threat_close_is_amber():
    assert threat_level(0.0, 10.0) == 1
    assert threat_level(-8.0, -8.0) == 1


def test_threat_alongside_is_red():
    assert threat_level(3.0, 2.0) == 2
    assert threat_level(-3.5, -5.0) == 2


def test_threat_overlap_needs_both_axes():
    """Just outside the lateral alongside window → amber, not red; ditto a
    car 10 m directly ahead (no longitudinal overlap)."""
    assert threat_level(ALONGSIDE_LAT_M + 0.1, 2.0) == 1
    assert threat_level(0.0, CAR_LENGTH_M + 1.0) == 1


# ── car_corners ──────────────────────────────────────────────────────────────

def test_car_corners_axis_aligned():
    """rel_yaw 0 → rectangle spans width across, length along."""
    corners = car_corners(10.0, 20.0, 0.0)
    rights = [c[0] for c in corners]
    aheads = [c[1] for c in corners]
    assert max(rights) - min(rights) == pytest.approx(CAR_WIDTH_M)
    assert max(aheads) - min(aheads) == pytest.approx(CAR_LENGTH_M)


def test_car_corners_quarter_turn_swaps_extents():
    corners = car_corners(0.0, 0.0, math.pi / 2)
    rights = [c[0] for c in corners]
    aheads = [c[1] for c in corners]
    assert max(rights) - min(rights) == pytest.approx(CAR_LENGTH_M)
    assert max(aheads) - min(aheads) == pytest.approx(CAR_WIDTH_M)


def test_car_corners_centroid_is_the_car_position():
    corners = car_corners(-4.0, 7.5, 1.234)
    cx = sum(c[0] for c in corners) / 4.0
    cy = sum(c[1] for c in corners) / 4.0
    assert (cx, cy) == pytest.approx((-4.0, 7.5))
