"""RPM redline calibration shared by the Forza telemetry sources.

Forza's reported `EngineMaxRpm` tends to overstate the RPM the rev
limiter actually holds at by roughly 5-10%, so `rpm / max_rpm` rarely
reaches 1.0 in normal driving and the shift-light bar / RPM gauge never
read "full" near the limiter.

To compensate, the reported max is scaled down by REDLINE_FACTOR, and
refined upward over a session using the highest RPM actually observed
for the current car (in case the true ceiling is even closer to 100%).

Set ENABLED = False to report EngineMaxRpm unchanged.
"""

ENABLED = True
REDLINE_FACTOR = 0.93


class RpmCalibrator:
    """Tracks the effective redline RPM for the current car."""

    def __init__(self):
        self._reported_max = 0
        self._observed_max = 0

    def calibrate(self, reported_max: int, current_rpm: int) -> int:
        if not ENABLED or reported_max <= 0:
            return reported_max

        if reported_max != self._reported_max:
            self._reported_max = reported_max
            self._observed_max = 0

        if current_rpm > self._observed_max:
            self._observed_max = current_rpm

        return max(self._observed_max, int(reported_max * REDLINE_FACTOR))
