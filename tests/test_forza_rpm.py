from telemetry import forza_rpm
from telemetry.forza_rpm import RpmCalibrator


def test_calibrate_applies_redline_factor_when_below_observed():
    cal = RpmCalibrator()

    # First reading: nothing observed yet, falls back to reported_max * factor
    assert cal.calibrate(reported_max=8000, current_rpm=5000) == int(8000 * 0.93)


def test_calibrate_tracks_highest_observed_rpm():
    cal = RpmCalibrator()

    cal.calibrate(reported_max=8000, current_rpm=5000)
    # Observed RPM exceeds reported_max * REDLINE_FACTOR (7440) -> used instead
    result = cal.calibrate(reported_max=8000, current_rpm=7600)

    assert result == 7600


def test_calibrate_does_not_lower_redline_when_rpm_drops():
    cal = RpmCalibrator()

    cal.calibrate(reported_max=8000, current_rpm=7600)
    result = cal.calibrate(reported_max=8000, current_rpm=4000)

    assert result == 7600


def test_calibrate_resets_observed_max_when_reported_max_changes():
    cal = RpmCalibrator()

    cal.calibrate(reported_max=8000, current_rpm=7600)
    # Switching cars changes the reported max -> observed history resets
    result = cal.calibrate(reported_max=9000, current_rpm=5000)

    assert result == int(9000 * 0.93)


def test_calibrate_passes_through_when_reported_max_is_zero_or_negative():
    cal = RpmCalibrator()

    assert cal.calibrate(reported_max=0, current_rpm=5000) == 0
    assert cal.calibrate(reported_max=-1, current_rpm=5000) == -1


def test_calibrate_disabled_returns_reported_max_unchanged(monkeypatch):
    monkeypatch.setattr(forza_rpm, "ENABLED", False)
    cal = RpmCalibrator()

    assert cal.calibrate(reported_max=8000, current_rpm=7900) == 8000
