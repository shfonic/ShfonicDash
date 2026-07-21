import pytest

from telemetry.lap_delta import LapDeltaTracker, interpolate_profile


def _drive_lap(tracker, length_m=5000, pace_s_per_m=0.02, step_m=5.0):
    """Record a full lap profile at a constant pace; returns the profile."""
    d = step_m
    while d <= length_m:
        tracker.record_point(d, d * pace_s_per_m)
        d += step_m
    return tracker.finish_lap()


def test_interpolate_profile_linear():
    profile = [(0.0, 0.0), (100.0, 10.0)]
    assert interpolate_profile(profile, 50.0) == pytest.approx(5.0)
    assert interpolate_profile(profile, -10.0) == 0.0      # clamps to first
    assert interpolate_profile(profile, 200.0) == 10.0     # clamps to last
    assert interpolate_profile([], 50.0) == 0.0


def test_record_point_downsamples():
    t = LapDeltaTracker()
    assert t.record_point(5.0, 0.1) is True     # first point of fresh profile
    assert t.record_point(7.0, 0.14) is False   # < 5 m progress — not recorded
    assert t.profile_points == 1
    t.record_point(10.0, 0.2)
    assert t.profile_points == 2


def test_live_delta_against_reference():
    t = LapDeltaTracker()
    profile = _drive_lap(t, pace_s_per_m=0.02)   # reference: 0.02 s/m
    assert t.set_reference(profile) is True

    # Now 1 s slower at 1000 m than the reference predicts
    assert t.live_delta(1000.0, 21.0) == pytest.approx(1.0)
    # And 0.5 s faster at 2000 m
    assert t.live_delta(2000.0, 39.5) == pytest.approx(-0.5)


def test_live_delta_none_without_reference_coverage():
    t = LapDeltaTracker()
    assert t.live_delta(1000.0, 20.0) is None   # no reference at all

    # Reference recorded from a mid-lap connect starting at 500 m
    d = 500.0
    while d <= 5000.0:
        t.record_point(d, d * 0.02)
        d += 5.0
    t._ref_lap = t.finish_lap()   # bypass quality gate to simulate coverage hole
    assert t.live_delta(100.0, 2.0) is None       # before coverage start
    assert t.live_delta(600.0, 12.0) is not None  # inside coverage


def test_set_reference_rejects_mid_lap_start_and_clears_old():
    t = LapDeltaTracker()
    good = _drive_lap(t)
    assert t.set_reference(good) is True
    assert t.has_reference

    # New best with a profile starting at 515 m (mid-lap connect) — rejected,
    # and the old reference must be cleared too
    late = [(515.0 + i * 5.0, i * 0.1) for i in range(200)]
    assert t.set_reference(late) is False
    assert not t.has_reference


def test_set_reference_rejects_tiny_profile():
    t = LapDeltaTracker()
    assert t.set_reference([(5.0, 0.1)]) is False
    assert t.set_reference([]) is False
    assert t.set_reference(None) is False


def test_trim_flashback():
    t = LapDeltaTracker()
    for d in range(5, 1005, 5):
        t.record_point(float(d), d * 0.02)
    pts_before = t.profile_points

    assert t.trim_flashback(990.0) is False    # small jump back — not a flashback
    assert t.trim_flashback(600.0) is True     # > 50 m back — trimmed
    assert t.profile_points < pts_before
    assert t.trim_flashback(600.0) is False    # already trimmed; no repeat


def test_discard_profile_keeps_reference():
    t = LapDeltaTracker()
    t.set_reference(_drive_lap(t))
    t.record_point(100.0, 2.0)
    t.discard_profile()
    assert t.profile_points == 0
    assert t.has_reference   # reference survives pit visits / pauses
