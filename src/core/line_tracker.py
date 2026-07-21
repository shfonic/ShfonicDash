"""LineTracker — records how far the player drove from the recorded racing line.

Fed the same ``TelemetryData`` frames and the same ``LapTracker`` events as the
session logger, it buffers the per-frame perpendicular offset from the class
racing line and, on each completed lap, resamples that buffer onto the racing
line's station grid to produce one **offset profile** — a signed metre value per
station (see ``core.geometry`` for the sign convention). The logger writes the
profile as a ``P`` row; ``sessionlog.lines`` derives all coaching numbers (corner
adherence, notes, the player-vs-line mini-map) from it, so the Pi and the
companion always agree.

Design notes
------------
* **Lap / rewind detection is delegated to ``LapTracker``** (the project's single
  source of truth) — this tracker never re-detects them. It reacts to the
  ``LapCompleted`` / ``Rewind`` / ``Restart`` events the logger already computes,
  finalising a lap's buffer on completion and discarding it on a rewind/restart.
* **Pure logic + stdlib only** (no pygame), so it is unit-testable and mirrors
  ``LapTracker`` / ``LapDeltaTracker``.
* Only frames with valid world position and a non-negative lap distance are
  buffered (the Time-Trial run-up before the S/F line is skipped).

Offsets are stored as integer **decimetres** (metres × 10) — the unit written to
the CSV — bounded to a sane range so a projection glitch can't emit a wild value.
"""

import bisect

from core.geometry import signed_offset
from core.lap_tracker import LapCompleted, Restart, Rewind
from core.telemetry_model import TelemetryData

# Clamp a single station's offset to ±200 m in decimetres — beyond this the
# projection has gone wrong (wrong lap, teleport) and the value is meaningless.
_MAX_OFFSET_DM = 2000


def _resample_offsets(samples: list, n: int, length: float) -> list:
    """Resample ``samples`` — ``(station_m, offset_m)`` pairs taken around one lap
    — onto ``n`` evenly-spaced stations, returning integer decimetres per station.

    The car's lap distance increases monotonically, so the samples are ordered by
    station; each grid station's value is linearly interpolated between the two
    bracketing samples, wrapping across the start/finish line. Returns ``None``
    when there is nothing usable to resample."""
    pts = sorted((s % length, o) for s, o in samples if length > 0)
    if len(pts) < 2:
        return None
    stations = [p[0] for p in pts]
    offs = [p[1] for p in pts]
    first_s, first_o = stations[0], offs[0]
    last_s, last_o = stations[-1], offs[-1]
    out = []
    for i in range(n):
        s = i * length / n
        k = bisect.bisect_left(stations, s)
        if k == 0 or k >= len(stations):
            # Before the first / after the last sample: bridge the S/F gap
            # between the last and first samples (a wrap of `length`).
            span = (first_s + length) - last_s
            frac = 0.0 if span <= 0 else (
                ((s - last_s) if s >= last_s else (s + length - last_s)) / span)
            val = last_o + (first_o - last_o) * frac
        else:
            s0, s1 = stations[k - 1], stations[k]
            o0, o1 = offs[k - 1], offs[k]
            frac = 0.0 if s1 == s0 else (s - s0) / (s1 - s0)
            val = o0 + (o1 - o0) * frac
        dm = int(round(val * 10.0))
        out.append(max(-_MAX_OFFSET_DM, min(_MAX_OFFSET_DM, dm)))
    return out


class LineTracker:

    def __init__(self, racing_line: list, track_length_m: float,
                 n_stations: int = 0):
        self._line = [tuple(p) for p in racing_line]
        self._length = float(track_length_m) if track_length_m else 0.0
        self._n = n_stations or len(self._line)
        self._buf: list = []          # (station_m, offset_m) for the in-progress lap
        self._completed: dict = {}    # lap_num -> [offset decimetres]

    @property
    def active(self) -> bool:
        """True when a usable racing line and track length are present."""
        return len(self._line) >= 2 and self._length > 0 and self._n > 1

    def update(self, data: TelemetryData, events: list) -> None:
        """Feed one frame plus the LapTracker events already computed for it.

        Events are handled first (a completed lap finalises the buffer built from
        the *previous* frames; a rewind/restart discards it), then this frame's
        offset is buffered — so the frame that opens a new lap seeds the next
        buffer instead of contaminating the lap that just closed."""
        if not self.active:
            return
        for ev in events:
            if isinstance(ev, LapCompleted):
                profile = _resample_offsets(self._buf, self._n, self._length)
                if profile is not None:
                    self._completed[ev.num] = profile
                self._buf = []
            elif isinstance(ev, (Rewind, Restart)):
                self._buf = []
        if data.pos_valid and data.lap_distance >= 0.0:
            off = signed_offset((data.pos_x, data.pos_z), self._line)
            self._buf.append((data.lap_distance, off))

    def take(self, lap_num: int):
        """The finalised offset profile (decimetres per station) for ``lap_num``,
        or ``None`` if the lap produced none. Removes it once taken."""
        return self._completed.pop(lap_num, None)

    def reset(self) -> None:
        self._buf = []
        self._completed = {}
