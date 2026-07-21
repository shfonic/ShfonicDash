"""
LapTracker — single source of truth for lap completion and rewind detection.

SessionHistory (on-screen lap list / best lap) and SessionLogger (session CSVs)
previously each implemented their own copy of this logic and the copies drifted
apart (e.g. only the logger detected mid-lap rewinds). Both now feed every
telemetry snapshot into their own LapTracker instance and react to the events
it returns — one instance per consumer because they reset at different times.

Rewind detection:
  * S/F-crossing rewind — lap_number goes backwards.
  * Mid-lap rewind — lap_number unchanged but the streamed lap_time jumps
    backwards. A rewind restores an earlier point of the lap, so lap_time is
    the reliable signal; no magnitude threshold is applied beyond a small
    epsilon for float noise.

Restart detection:
  * "Restart lap" (F1 Time Trial) also jumps lap_time backwards on the same
    lap, but places the car on the run-up *before* the S/F line: lap_distance
    is negative and the lap clock sits at 0 until the line is crossed. A
    flashback lands mid-lap (positive distance, non-zero time). Restarts are
    reported as Restart events and do not count towards the lap's rewinds —
    the attempt that eventually completes is a clean full lap.

Pit stops / garage visits:
  * Entering the pits (practice tyre change, return to garage) teleports the
    car, so lap_time and lap_number jump around exactly like a rewind. While
    `data.in_pits` is set — and on the first tick after it clears, which
    carries the exit teleport — backwards jumps are swallowed silently: they
    are game housekeeping, not player rewinds. Lap completions still fire so
    racing pit stops (where the lap continues through the pit lane) count.
"""

from dataclasses import dataclass

from core.telemetry_model import TelemetryData

# Tolerance for lap_time moving backwards within the same lap before it is
# treated as a rewind — absorbs float rounding in sources that derive lap_time
# from packet timestamps.
_REWIND_EPSILON_S = 0.05


@dataclass
class LapCompleted:
    num: int          # lap number that finished
    time: float       # final lap time in seconds
    invalid: bool     # lap was flagged invalid at any point
    s1: float         # sector splits in seconds (0.0 = unknown)
    s2: float
    s3: float
    rewinds: int      # rewinds used during this lap (restarts excluded)


@dataclass
class Rewind:
    lap_num: int         # lap the player was on when the rewind happened
    lap_time: float      # lap time immediately before the rewind
    lap_distance: float  # metres around the lap at that same instant —
                         # locates the rewind on a track map
    crossed_sf: bool     # True when the rewind crossed the start/finish line
                         # (lap_number went backwards)


@dataclass
class Restart:
    lap_num: int         # lap that was abandoned and restarted
    lap_time: float      # lap time immediately before the restart
    lap_distance: float  # metres around the lap at that same instant


@dataclass
class LapInvalidated:
    lap_num: int      # lap that just became invalid
    lap_time: float   # elapsed lap time at the moment of invalidation


class LapTracker:

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._prev_lap_num      = 0
        self._prev_lap_time     = 0.0
        self._prev_lap_distance = 0.0
        self._pending_s1 = 0.0   # latest non-zero sector1_time seen
        self._pending_s2 = 0.0   # latest non-zero sector2_time seen (cumulative)
        self._pending_invalid = False
        self._lap_rewinds = 0    # rewinds during the in-progress lap
        self._prev_in_pits = False

    def update(self, data: TelemetryData) -> list:
        """Feed one telemetry snapshot; return events
        (Rewind / Restart / LapInvalidated / LapCompleted)."""
        events = []

        # The pit/garage teleport spans the in_pits window plus the first tick
        # after it clears (the exit teleport arrives with pit status already 0).
        in_pits = data.in_pits or self._prev_in_pits
        self._prev_in_pits = data.in_pits

        if data.sector1_time > 0:
            self._pending_s1 = data.sector1_time
        if data.sector2_time > 0:
            self._pending_s2 = data.sector2_time

        lap_num = data.lap_number

        # Latch the invalid flag — but not while the car is still before the
        # S/F line (negative lap_distance: the Time Trial run-up / out-lap).
        # An off there doesn't belong to the timed lap; if the game carries
        # the invalidation across the line, the flag is still set on the
        # first tick past it and is latched then.
        if (lap_num == self._prev_lap_num and data.lap_invalid
                and not self._pending_invalid
                and data.lap_distance >= 0.0):
            self._pending_invalid = True
            events.append(LapInvalidated(lap_num, data.lap_time))

        # Mid-lap backwards jump: same lap, but the streamed lap time dropped.
        if (lap_num == self._prev_lap_num
                and self._prev_lap_time > 0.0
                and data.lap_time < self._prev_lap_time - _REWIND_EPSILON_S):
            self._pending_s1 = 0.0
            self._pending_s2 = 0.0
            if in_pits:
                # Pit/garage teleport — a fresh attempt begins, nothing to report.
                self._pending_invalid = False
            # Restart lap: car placed before the S/F line (negative distance)
            # with the lap clock reset — a fresh attempt, not a rewind.
            elif data.lap_distance < 0.0 or data.lap_time == 0.0:
                self._pending_invalid = False
                events.append(Restart(lap_num, self._prev_lap_time,
                                      self._prev_lap_distance))
            else:
                self._lap_rewinds += 1
                events.append(Rewind(lap_num, self._prev_lap_time,
                                     self._prev_lap_distance, crossed_sf=False))

        # S/F-crossing rewind: lap number went backwards.
        if lap_num < self._prev_lap_num:
            self._pending_s1 = 0.0
            self._pending_s2 = 0.0
            self._pending_invalid = False
            if not in_pits:
                self._lap_rewinds += 1
                events.append(Rewind(self._prev_lap_num, self._prev_lap_time,
                                     self._prev_lap_distance, crossed_sf=True))
            self._prev_lap_num      = lap_num
            self._prev_lap_time     = data.lap_time
            self._prev_lap_distance = data.lap_distance
            return events

        if lap_num > self._prev_lap_num and self._prev_lap_num > 0 and data.last_lap > 0:
            ps1, ps2 = self._pending_s1, self._pending_s2
            s2 = ps2 - ps1 if ps2 > ps1 else 0.0
            s3 = data.last_lap - ps2 if ps2 > 0 and data.last_lap > ps2 else 0.0
            events.append(LapCompleted(
                num=self._prev_lap_num,
                time=data.last_lap,
                invalid=self._pending_invalid,
                s1=ps1, s2=s2, s3=s3,
                rewinds=self._lap_rewinds,
            ))
            # The invalid flag on this tick already belongs to the new lap.
            self._pending_invalid = bool(data.lap_invalid)
            self._lap_rewinds = 0

        self._prev_lap_num      = lap_num
        self._prev_lap_time     = data.lap_time
        self._prev_lap_distance = data.lap_distance
        return events
