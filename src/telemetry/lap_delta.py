"""
LapDeltaTracker — live delta vs personal-best lap, game-agnostic.

Approach (see ROADMAP.md § Implementation Reference → Live Delta): record
(distance, time) profile points while driving; when a completed lap is a new
personal best its profile becomes the reference; afterwards the reference time
at the current distance is interpolated on every packet and
delta = current − reference.

The tracker owns the profile/reference lifecycle: down-sampled recording,
invalidation on pits / pause / flashbacks, and the quality gate for promoting
a profile to reference. The game parser stays responsible for *when* to call
each hook, because packet semantics (pit status, pause, lap distance source)
differ per game — F1 25 uses `m_lapDistance`, PC2 `mCurrentLapDistance`,
Forza a lap-start-relative `distanceTraveled` (see the ROADMAP table).
"""

_RECORD_SPACING_M = 5.0    # down-sample: record a point every ~5 m of progress
_FLASHBACK_JUMP_M = 50.0   # backwards jump in lap distance that counts as a flashback
_REF_MAX_START_M  = 200.0  # reference must start within 200 m of the S/F line
_REF_MIN_POINTS   = 50     # …and have ≥50 points; rejects mid-lap connects and
                           # spurious 1-point profiles from double completion firings


def interpolate_profile(profile: list, dist: float) -> float:
    """Return the profile's lap time at the given distance via linear interpolation."""
    if not profile:
        return 0.0
    if dist <= profile[0][0]:
        return profile[0][1]
    if dist >= profile[-1][0]:
        return profile[-1][1]
    lo, hi = 0, len(profile) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if profile[mid][0] <= dist:
            lo = mid
        else:
            hi = mid
    d0, t0 = profile[lo]
    d1, t1 = profile[hi]
    frac = (dist - d0) / (d1 - d0) if d1 > d0 else 0.0
    return t0 + frac * (t1 - t0)


class LapDeltaTracker:

    def __init__(self):
        self._ref_lap: list = []          # (dist_m, time_s) of the best lap
        self._current_profile: list = []  # recording of the in-progress lap
        self._last_rec_dist: float = -999.0

    # ── State queries ────────────────────────────────────────────────────

    @property
    def has_reference(self) -> bool:
        return bool(self._ref_lap)

    @property
    def profile_points(self) -> int:
        return len(self._current_profile)

    # ── Lifecycle hooks ──────────────────────────────────────────────────

    def reset(self) -> None:
        """Full reset including the reference (new session)."""
        self._ref_lap = []
        self.discard_profile()

    def discard_profile(self) -> None:
        """Invalidate the in-progress profile (pit transition, pause resume,
        S/F-crossing rewind). The reference deliberately survives."""
        self._current_profile = []
        self._last_rec_dist = -999.0

    def trim_flashback(self, lap_dist: float) -> bool:
        """Detect a within-lap flashback (lap_dist jumped backwards past the
        threshold) and trim the profile to points before the rewind position,
        so the pre-rewind (inflated) times don't corrupt the reference.
        Returns True when a flashback was handled."""
        if not self._current_profile or lap_dist >= self._last_rec_dist - _FLASHBACK_JUMP_M:
            return False
        trimmed = [(rd, rt) for rd, rt in self._current_profile if rd <= lap_dist]
        self._current_profile = trimmed
        self._last_rec_dist = trimmed[-1][0] if trimmed else -999.0
        return True

    def record_point(self, lap_dist: float, curr_time: float) -> bool:
        """Append a profile point if the car progressed ≥ the record spacing.
        Returns True when this was the first point of a fresh profile."""
        if lap_dist - self._last_rec_dist < _RECORD_SPACING_M:
            return False
        started = not self._current_profile
        self._current_profile.append((lap_dist, curr_time))
        self._last_rec_dist = lap_dist
        return started

    def finish_lap(self) -> list:
        """Swap out the completed lap's profile and start recording fresh."""
        finished = self._current_profile
        self.discard_profile()
        return finished

    def set_reference(self, profile: list) -> bool:
        """Promote a finished profile to reference if it meets the quality bar,
        otherwise clear the reference too — keeping a slower old reference
        would make every future lap look artificially fast against the new
        (unrecorded) best. Call on a new personal best. Returns True if promoted."""
        if (profile and profile[0][0] <= _REF_MAX_START_M
                and len(profile) >= _REF_MIN_POINTS):
            self._ref_lap = profile
            return True
        self._ref_lap = []
        return False

    def live_delta(self, lap_dist: float, curr_time: float) -> float | None:
        """Delta vs the reference at this distance, or None where the reference
        has no coverage (e.g. it starts mid-lap after a mid-lap connect)."""
        if not self._ref_lap or lap_dist < self._ref_lap[0][0]:
            return None
        ref_time = interpolate_profile(self._ref_lap, lap_dist)
        if ref_time <= 0:
            return None
        return curr_time - ref_time
