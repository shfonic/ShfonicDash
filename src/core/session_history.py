"""
SessionHistory — accumulates per-session state that must survive dashboard switches.

Owned by DashboardManager and updated every tick regardless of which dashboard
is currently active.  Widgets that need historical data receive a reference via
set_session() and read from here instead of maintaining their own state.

Lap completion / rewind detection lives in core.lap_tracker.LapTracker (shared
with SessionLogger).  See CLAUDE.md § "Session History".
"""

from core.lap_tracker import LapCompleted, LapTracker, Rewind
from core.telemetry_model import TelemetryData

_MAX_LAPS = 30


class SessionHistory:

    def __init__(self):
        self._tracker = LapTracker()
        self.laps: list = []        # completed laps, newest-first
        self.best_lap: float = 0.0  # personal best this session (valid laps only)
        # Live qualifying / race leaderboard (populated by sources that broadcast it)
        self.participants: list = []
        self.session_type: str = ""
        self.car_class: str = ""

    def reset(self) -> None:
        self._tracker.reset()
        self.laps = []
        self.best_lap = 0.0
        self.participants = []
        self.session_type = ""
        self.car_class = ""

    def update(self, data: TelemetryData) -> None:
        self.session_type = data.session_type
        self.car_class    = data.car_class

        if data.participants:
            self.participants = data.participants

        for event in self._tracker.update(data):
            if isinstance(event, Rewind):
                if event.crossed_sf:
                    # Remove committed laps that are now in the future again
                    while self.laps and self.laps[0]['num'] >= data.lap_number:
                        self.laps.pop(0)
            elif isinstance(event, LapCompleted):
                self.laps.insert(0, {
                    "num":      event.num,
                    "time":     event.time,
                    "invalid":  event.invalid,
                    "s1_t":     event.s1,
                    "s2_t":     event.s2,
                    "s3_t":     event.s3,
                    "compound": data.tyre_compound,
                })
                if len(self.laps) > _MAX_LAPS:
                    self.laps.pop()
                if not event.invalid and (self.best_lap == 0.0 or event.time < self.best_lap):
                    self.best_lap = event.time
