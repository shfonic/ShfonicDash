"""Per-lap CSV logger — writes one file per session type, rotates on session change."""
import csv
import math
import os
from datetime import datetime, timedelta

from core.lap_tracker import LapCompleted, LapInvalidated, LapTracker, Restart, Rewind
from core.line_tracker import LineTracker
from core.telemetry_model import TelemetryData
from sessionlog import trackmap
from version import __version__

_LOG_VERSION = 1

# Sessions and games for which we record the player's line against the recorded
# racing line (racing-line adherence coaching). F1 25/26 is the only source that
# populates world position. We capture in **every** session type — a race or a
# practice run is just as worth reflecting on as a hotlap — and let the analysis
# layer (sessionlog.lines) decide what counts (push laps, on-line laps). A track
# with no recorded line for the driven class still records no `P` rows.
_LINE_SESSIONS = {"hotlap", "qualifying", "practice", "race"}
_LINE_GAMES = {"f1_25"}

_META_KEYS = ["version", "app_version", "started_at", "game", "session_type",
              "session_subtype", "session_type_raw", "car_class", "car_name",
              "driver_name", "track", "team_id_raw",
              "weather", "air_temp", "track_temp"]

_LAP_COLS = [
    "lap_num", "lap_time", "s1", "s2", "s3",
    "tyre_fl", "tyre_fr", "tyre_rl", "tyre_rr", "tyre_compound",
    "fuel_remaining", "fuel_per_lap",
    "position", "delta", "invalid", "rewinds",
    "assist_tc", "assist_abs", "assist_racing_line", "assist_steering",
    "assist_braking", "assist_gearbox", "assist_pit", "assist_pit_release",
    "assist_ers", "assist_drs",
]

# (CSV column, TelemetryData attribute) pairs for the "highest assist level
# used" per lap — tracked as a running max in `update()`, read for the L row
# on LapCompleted, then reset. F1-only; always 0 for other games.
_ASSIST_FIELDS = [
    ("assist_tc", "tc_level"),
    ("assist_abs", "abs_level"),
    ("assist_racing_line", "racing_line_assist"),
    ("assist_steering", "steering_assist"),
    ("assist_braking", "braking_assist"),
    ("assist_gearbox", "gearbox_assist"),
    ("assist_pit", "pit_assist"),
    ("assist_pit_release", "pit_release_assist"),
    ("assist_ers", "ers_assist"),
    ("assist_drs", "drs_assist"),
]

# F1 driver_status values where the driver is actually driving the lap:
# 1 = flying lap, 4 = on track. Garage (0), in-lap (2) and out-lap (3) are
# transit — the game may be auto-driving with assists forced on, so their
# assist readings must not fold into the lap's "assist used" max. Non-F1
# sources leave driver_status at its default 4.
_DRIVING_STATUSES = (1, 4)

_GRID_COLS   = ["position", "race_num", "name"]
_RESULT_COLS = ["position", "race_num", "name", "best_lap", "race_time"]
# `t` = wall-clock seconds since the session file opened. lap_time resets on
# pit teleports and lap boundaries, so durations (e.g. pit stops) must be
# computed from `t`, never from lap_time deltas.
# `detail` = event-specific context: other driver for collision/overtake rows,
# "penalty_type:infringement[:other_driver]" for penalty rows.
_EVENT_COLS  = ["lap_num", "lap_time", "type", "distance", "t", "detail"]

# Solo sessions have no real grid or standings — F1 Time Trial broadcasts
# ghost/rival slots as nameless cars all at position 1, which is noise.
_SOLO_SESSIONS = {"hotlap"}


_TRASH_DIR = ".trash"


def trash_session(logs_dir: str, filename: str) -> bool:
    """Move one session CSV into logs/.trash/ (recoverable). Returns success.

    Session files in logs/ are the dashboard's history database (records
    index, prior bests, trends) — user deletes go to the trash folder
    instead of being destroyed. cleanup_trash() prunes the trash later.
    """
    src = os.path.join(logs_dir, filename)
    if not os.path.isfile(src):
        return False
    trash = os.path.join(logs_dir, _TRASH_DIR)
    os.makedirs(trash, exist_ok=True)
    dst  = os.path.join(trash, filename)
    stem, ext = os.path.splitext(filename)
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(trash, f"{stem}_{n}{ext}")
        n += 1
    try:
        os.replace(src, dst)
        return True
    except OSError:
        return False


def cleanup_trash(logs_dir: str, keep_days: int = 30) -> None:
    """Delete trashed CSVs whose mtime is older than keep_days.

    Session CSVs in logs/ itself are never deleted: since v0.1.138 they
    are the dashboard's own history/records database. The share window
    setting controls what is *exposed* for download, not what is kept.
    """
    trash = os.path.join(logs_dir, _TRASH_DIR)
    if not os.path.isdir(trash):
        return
    cutoff = datetime.now() - timedelta(days=keep_days)
    for fname in os.listdir(trash):
        if not fname.endswith(".csv"):
            continue
        path = os.path.join(trash, fname)
        try:
            if datetime.fromtimestamp(os.path.getmtime(path)) < cutoff:
                os.remove(path)
        except OSError:
            pass


class SessionLogger:

    def __init__(self, logs_dir: str):
        self._logs_dir = logs_dir
        os.makedirs(logs_dir, exist_ok=True)
        self._file = None
        self._writer = None
        self._active_file: str | None = None
        self._current_session_type = ""
        self._tracker = LapTracker()        # lap completion / rewind detection
        self._line_tracker: LineTracker | None = None   # racing-line adherence
        self._grid_written = False
        self._lap_header_written = False
        self._last_participants: list = []
        # Per-session tracking for summary stats
        self._rewind_count = 0
        self._restart_count = 0
        self._completed_laps: list = []     # (lap_time, was_invalid) per completed lap
        self._event_header_written = False
        self._prev_pit_limiter = False
        self._prev_in_pits = False
        self._seen_pit_status = False   # source provides real pit status → ignore limiter
        self._prev_safety_car = ""
        self._prev_warnings: int | None = None   # corner-cut warnings baseline
        self._lap_assist_max: dict = {}   # highest assist level seen this lap
        self._session_best_lap = 0.0      # best CLEAN lap so far — for the L row's delta
        self._written_car_name = ""
        self._written_driver_name = ""
        self._written_team_id = -1
        self._written_weather = ""
        self._current_subtype = ""
        self._current_track = ""      # rotate the file when the track changes
        self._opened_at: datetime | None = None
        self._focus_written = False   # F row written once per session
        self._objectives_written = False   # O rows written once per session

    @property
    def active_file(self) -> str | None:
        return self._active_file

    @property
    def lap_count(self) -> int:
        """Completed laps in the current session file."""
        return len(self._completed_laps)

    def set_focus(self, focus_id: str) -> None:
        """Record the driver's chosen session focus as an `F` row.

        Written once per session (the first pick sticks) when the driver
        taps a focus chip on the pre-session card. Silently ignored with no
        open file or no id. The summary reads it back to report against it.
        """
        if not focus_id or self._writer is None or self._focus_written:
            return
        self._focus_written = True
        self._writer.writerow(["F", focus_id])
        self._file.flush()

    def set_objectives(self, objs) -> None:
        """Record the session's tracked objectives as `O` rows.

        Written once per session when the pre-session card is shown (the
        objectives are auto-committed — unlike the focus chip they need no
        tap, so they're captured even if the driver just drives away).
        Silently ignored with no open file, no objectives, or if already
        written. The summary reads them back to report how each one went.
        """
        if not objs or self._writer is None or self._objectives_written:
            return
        from sessionlog import objectives as _objectives
        self._objectives_written = True
        for obj in objs:
            self._writer.writerow(_objectives.to_row(obj))
        self._file.flush()

    def update(self, data: TelemetryData) -> None:
        # Rotate file when the session type (or its variant, e.g. sprint
        # qualifying vs qualifying) changes, OR when the track changes within
        # the same session type — switching circuits in Time Trial keeps
        # session_type == "hotlap", so without this the new track's laps would
        # append to the previous track's file and its summary/history would be
        # wrong. Only rotate on a track change between two *known* tracks (both
        # non-empty), so late/blank track metadata at load never spuriously
        # rotates.
        track_changed = bool(data.track and self._current_track
                             and data.track != self._current_track)
        if data.session_type and (data.session_type != self._current_session_type
                                  or data.session_subtype != self._current_subtype
                                  or track_changed):
            self._open_session(data)

        # Late-arriving metadata — participant packets often arrive after session open.
        # Write extra S rows so parsers (taking the last value) always get the real data.
        if self._file:
            if data.car_name and data.car_name != self._written_car_name:
                self._writer.writerow(["S", "car_name", data.car_name])
                self._written_car_name = data.car_name
                self._file.flush()
            if data.driver_name and data.driver_name != self._written_driver_name:
                self._writer.writerow(["S", "driver_name", data.driver_name])
                self._written_driver_name = data.driver_name
                self._file.flush()
            if data.team_id_raw >= 0 and data.team_id_raw != self._written_team_id:
                self._writer.writerow(["S", "team_id_raw", data.team_id_raw])
                self._written_team_id = data.team_id_raw
                self._file.flush()
            # Weather is dynamic (F1 rain arriving mid-session) — a repeated S
            # row per change records the transition; parsers keep the last value.
            if data.weather and data.weather != self._written_weather:
                self._writer.writerow(["S", "weather", data.weather])
                self._written_weather = data.weather
                self._file.flush()

        # Grid and standings only make sense with other cars on track
        if self._current_session_type not in _SOLO_SESSIONS:
            # Capture grid (starting positions) from the first participant snapshot we receive
            if not self._grid_written and self._writer and data.participants:
                self._write_grid(data.participants)
                self._grid_written = True

            # Keep a running snapshot of participants for the final standings at close
            if data.participants:
                self._last_participants = data.participants

        events = self._tracker.update(data)
        # Feed the same frame + events to the line tracker (it reacts to the
        # lap/rewind events rather than re-detecting them) before draining them.
        if self._line_tracker is not None:
            self._line_tracker.update(data, events)
        for event in events:
            if isinstance(event, Rewind):
                self._rewind_count += 1
                self._write_event(event.lap_num, event.lap_time, "rewind",
                                  event.lap_distance)
            elif isinstance(event, Restart):
                self._restart_count += 1
                self._write_event(event.lap_num, event.lap_time, "restart",
                                  event.lap_distance)
            elif isinstance(event, LapInvalidated):
                self._write_event(event.lap_num, event.lap_time, "invalid",
                                  data.lap_distance)
            elif isinstance(event, LapCompleted):
                self._write_lap(data, event, self._lap_assist_max)
                self._lap_assist_max = {}
                if self._line_tracker is not None:
                    profile = self._line_tracker.take(event.num)
                    if profile:
                        self._write_path(event.num, profile)

        # Highest assist level seen this lap — a running max, folded in every
        # frame (after LapCompleted has read/reset it above, so a frame that
        # completes lap N belongs to lap N+1's max, never N's — the same
        # first-frame-of-the-new-lap boundary LapTracker handles for
        # `_pending_invalid`, see its "already belongs to the new lap" comment).
        # Frames the driver isn't driving are excluded — the assist levels
        # they report are the game's, not the driver's setting:
        #   - Pit-lane frames (`in_pits`): F1 forces TC/ABS on under the limiter.
        #   - Run-up frames (`lap_distance` < 0, before the S/F line): an F1
        #     hotlap/TT start auto-drives the car for the last few corners
        #     under a countdown, and the AI drives it with ABS on. Those frames
        #     carry the upcoming lap's number, so without this they land in lap
        #     1's max (observed 2026-07-17: a clean Spa TT logged "ABS on for 1
        #     of 12 laps" purely from the auto-driven flying start).
        #   - Transit frames (F1 driver_status not flying-lap/on-track): leaving
        #     the garage via the "flying lap" option AI-drives the whole out-lap
        #     with ABS/TC forced on, and F1 books that transit onto the flyer's
        #     lap number (see parser `_drop_on_pace_pit_tags`), so the flyer gets
        #     tagged. driver_status 3 (out lap) / 2 (in lap) / 0 (garage) are the
        #     game driving, not the driver; only 1 (flying lap) and 4 (on track)
        #     are a real driven lap. Non-F1 sources default to 4, unchanged.
        if (not data.in_pits and data.lap_distance >= 0
                and data.driver_status in _DRIVING_STATUSES):
            for col, attr in _ASSIST_FIELDS:
                v = getattr(data, attr, 0) or 0
                if v > self._lap_assist_max.get(col, 0):
                    self._lap_assist_max[col] = v

        # Game-reported incidents (F1 event packet): collisions, penalties,
        # overtakes — one-shot events drained from this snapshot.
        for ev in data.events:
            self._write_event(ev["lap_num"], ev["lap_time"], ev["type"],
                              ev["distance"], ev.get("detail", ""))

        # Track-limit warnings — the game's cumulative cornerCuttingWarnings
        # counter. An `invalid` event at the same lap_time was a track-limits
        # violation. The first observed value is the baseline (it may carry
        # warnings from before the logger started).
        if data.corner_cut_warnings != self._prev_warnings:
            if (self._prev_warnings is not None
                    and data.corner_cut_warnings > self._prev_warnings):
                self._write_event(data.lap_number, data.lap_time,
                                  "track_limit_warning", data.lap_distance)
            self._prev_warnings = data.corner_cut_warnings

        # Pit transitions — the game's pit status (in_pits) is authoritative;
        # the pit limiter is only a fallback for sources that don't provide it
        # (the limiter flaps while the car sits in the garage, producing
        # spurious pit_in/pit_out pairs).
        if data.in_pits:
            self._seen_pit_status = True
        if data.in_pits != self._prev_in_pits:
            self._write_event(data.lap_number, data.lap_time,
                              "pit_in" if data.in_pits else "pit_out",
                              data.lap_distance)
        elif not self._seen_pit_status:
            if data.pit_limiter and not self._prev_pit_limiter:
                self._write_event(data.lap_number, data.lap_time, "pit_in", data.lap_distance)
            elif not data.pit_limiter and self._prev_pit_limiter:
                self._write_event(data.lap_number, data.lap_time, "pit_out", data.lap_distance)
        self._prev_in_pits = data.in_pits
        self._prev_pit_limiter = data.pit_limiter

        # Safety car transitions
        sc = data.safety_car
        if sc != self._prev_safety_car:
            if sc == "sc":
                self._write_event(data.lap_number, data.lap_time, "sc_deploy")
            elif sc == "vsc":
                self._write_event(data.lap_number, data.lap_time, "vsc_deploy")
            elif self._prev_safety_car == "sc":
                self._write_event(data.lap_number, data.lap_time, "sc_clear")
            elif self._prev_safety_car == "vsc":
                self._write_event(data.lap_number, data.lap_time, "vsc_clear")
            self._prev_safety_car = sc

    def close(self) -> str | None:
        """Close the open session file. Returns its path (the trigger for
        the end-of-session summary), or None if nothing was open.

        A session that completed no laps is deleted instead of kept:
        menu browsing, quitting before the first flying lap, etc. produce
        metadata-only files with no analytical value — they would clutter
        the history browser and inflate the sync badge forever.
        """
        if self._file:
            had_laps = bool(self._completed_laps)
            self._write_final_standings()
            self._write_summary()
            self._file.flush()
            self._file.close()
            self._file = None
            self._writer = None
            # Forget the session type: the logger is shared across the menu
            # loop, so after a menu round-trip the game may still be in the
            # same session. Without this reset update() sees "no change" and
            # never reopens a file — every row is then silently dropped.
            self._current_session_type = ""
            self._current_subtype = ""
            self._current_track = ""
            if not had_laps:
                try:
                    os.remove(self._active_file)
                except OSError:
                    pass
                self._active_file = None
                return None
            return self._active_file
        return None

    def _open_session(self, data: TelemetryData) -> None:
        self.close()
        self._current_session_type = data.session_type
        self._current_subtype = data.session_subtype
        self._current_track = data.track
        self._tracker.reset()
        self._line_tracker = None
        self._grid_written = False
        self._lap_header_written = False
        self._last_participants = []
        self._rewind_count = 0
        self._restart_count = 0
        self._completed_laps = []
        self._event_header_written = False
        self._prev_pit_limiter = False
        self._prev_in_pits = False
        self._seen_pit_status = False
        self._prev_safety_car = ""
        self._prev_warnings = None
        self._lap_assist_max = {}
        self._session_best_lap = 0.0
        self._written_car_name = data.car_name
        self._written_driver_name = data.driver_name
        self._written_team_id = data.team_id_raw
        self._written_weather = data.weather
        self._focus_written = False
        self._objectives_written = False

        now   = datetime.now()
        self._opened_at = now
        ts    = now.strftime("%Y%m%d_%H%M")
        label = data.session_subtype or data.session_type
        fname = f"session_{ts}_{label}.csv"
        path  = os.path.join(self._logs_dir, fname)
        # Never truncate an earlier fragment (e.g. close + reopen within the
        # same minute after a menu round-trip) — suffix instead.
        n = 2
        while os.path.exists(path):
            path = os.path.join(self._logs_dir,
                                f"session_{ts}_{label}_{n}.csv")
            n += 1

        self._file   = open(path, "w", newline="")
        self._writer = csv.writer(self._file)

        meta = {
            "version":      _LOG_VERSION,
            "app_version":  __version__,
            "started_at":   now.strftime("%Y-%m-%dT%H:%M:%S"),
            "game":         data.game,
            "session_type": data.session_type,
            "session_subtype": data.session_subtype,
            "session_type_raw": data.session_type_raw if data.session_type_raw >= 0 else "",
            "car_class":    data.car_class,
            "car_name":     data.car_name,
            "driver_name":  data.driver_name,
            "track":        data.track,
            "team_id_raw":  data.team_id_raw if data.team_id_raw >= 0 else "",
            "weather":      data.weather,
            "air_temp":     round(data.air_temp) if data.air_temp else "",
            "track_temp":   round(data.track_temp) if data.track_temp else "",
        }
        for key in _META_KEYS:
            self._writer.writerow(["S", key, meta[key]])
        # Racing-line adherence: if this is an F1 hotlap/quali at a mapped track
        # with a recorded line for the driven class, arm the line tracker and
        # note the line's attempt count (a staleness signal if it's re-recorded).
        self._setup_line_tracker(data)
        if data.session_type not in _SOLO_SESSIONS:
            self._writer.writerow(["GH"] + _GRID_COLS)
        self._file.flush()
        self._active_file = path

    def _setup_line_tracker(self, data: TelemetryData) -> None:
        if data.session_type not in _LINE_SESSIONS or data.game not in _LINE_GAMES:
            return
        try:
            trackmap.set_tracks_dir(os.path.join(self._logs_dir, "..", "tracks"))
            tmap = trackmap.find_map(data.game, data.track)
        except Exception:
            tmap = None
        if not tmap:
            return
        entry = trackmap.resolve_line(tmap, data.game, data.car_class)
        racing_line = entry.get("racing_line")
        length = tmap.get("game_track_length_m") or 0.0
        if not racing_line or not length:
            return
        tracker = LineTracker(racing_line, length)
        if not tracker.active:
            return
        self._line_tracker = tracker
        self._writer.writerow(["S", "line_ref", entry.get("racing_attempts") or ""])

    def _write_grid(self, participants: list) -> None:
        for p in participants:
            self._writer.writerow(["G",
                p.get("position", ""),
                p.get("race_number") or "",
                p.get("name", ""),
            ])
        self._file.flush()

    def _write_lap(self, data: TelemetryData, lap: LapCompleted,
                   assist_max: dict) -> None:
        if self._writer is None:
            return
        if not self._lap_header_written:
            self._writer.writerow(["H"] + _LAP_COLS)
            self._lap_header_written = True

        tyres = data.tyre_temp
        tfl   = round(tyres[0], 1) if tyres[0] else ""
        tfr   = round(tyres[1], 1) if tyres[1] else ""
        trl   = round(tyres[2], 1) if tyres[2] else ""
        trr   = round(tyres[3], 1) if tyres[3] else ""

        invalid = 1 if lap.invalid else 0
        self._completed_laps.append((round(lap.time, 3), bool(invalid)))

        # Delta vs the best CLEAN lap so far this session — tracked here,
        # independent of the live telemetry delta/best_lap fields. Those
        # update continuously from raw UDP packets on a background thread
        # to drive the live in-race HUD delta; by the time this snapshot is
        # taken (the app's render loop noticing the lap completed), both
        # have already moved on to track the lap that just STARTED, not the
        # one that just finished — every logged delta read as a near-zero
        # value instead of the true gap to the prior best (observed
        # 2026-07-15). This computation only ever sees completed-lap
        # snapshots, so it can't be raced by the live UDP thread.
        prior_best = self._session_best_lap
        delta = round(lap.time - prior_best, 3) if prior_best > 0 else ""
        if not lap.invalid and not lap.rewinds and (
                self._session_best_lap == 0.0 or lap.time < self._session_best_lap):
            self._session_best_lap = lap.time

        self._writer.writerow(["L",
            lap.num,
            round(lap.time, 3),
            round(lap.s1, 3) if lap.s1 else "",
            round(lap.s2, 3) if lap.s2 else "",
            round(lap.s3, 3) if lap.s3 else "",
            tfl, tfr, trl, trr,
            data.tyre_compound,
            round(data.fuel_remaining, 2) if data.fuel_remaining else "",
            round(data.fuel_per_lap, 3) if data.fuel_per_lap else "",
            data.position if data.position else "",
            delta,
            invalid,
            lap.rewinds,
            *[assist_max.get(col, 0) for col, _ in _ASSIST_FIELDS],
        ])
        self._file.flush()

    def _write_path(self, lap_num: int, offsets: list) -> None:
        """One `P` row: the completed lap's racing-line offset profile — a signed
        offset in decimetres (right of travel +) per racing-line station. Powers
        the coaching notes, the on-line achievement and the player-vs-line
        mini-map, all derived in sessionlog from this raw profile."""
        if self._writer is None:
            return
        self._writer.writerow(["P", lap_num] + list(offsets))
        self._file.flush()

    def _write_event(self, lap_num: int, lap_time: float, event_type: str,
                     distance: float = 0.0, detail: str = "") -> None:
        if self._writer is None:
            return
        if not self._event_header_written:
            self._writer.writerow(["EH"] + _EVENT_COLS)
            self._event_header_written = True
        t = ((datetime.now() - self._opened_at).total_seconds()
             if self._opened_at else 0.0)
        self._writer.writerow(["E", lap_num, round(lap_time, 3), event_type,
                               round(distance, 1) if distance else "",
                               round(t, 1), detail])
        self._file.flush()

    def _write_final_standings(self) -> None:
        if self._writer is None or not self._last_participants:
            return
        self._writer.writerow(["RH"] + _RESULT_COLS)
        is_race = self._current_session_type == "race"
        for p in self._last_participants:
            best      = p.get("best_lap", 0.0)
            race_time = p.get("race_time", 0.0)
            self._writer.writerow(["R",
                p.get("position", ""),
                p.get("race_number") or "",
                p.get("name", ""),
                round(best, 3) if best else "",
                round(race_time, 3) if (is_race and race_time) else "",
            ])

    def _write_summary(self) -> None:
        if self._writer is None or not self._completed_laps:
            return
        clean = [t for t, inv in self._completed_laps if not inv]
        fastest   = round(min(t for t, _ in self._completed_laps), 3)
        avg_clean = round(sum(clean) / len(clean), 3) if clean else ""
        if len(clean) >= 2:
            mean = sum(clean) / len(clean)
            std_dev = round(math.sqrt(sum((t - mean) ** 2 for t in clean) / (len(clean) - 1)), 3)
        else:
            std_dev = ""
        invalid_count = sum(1 for _, inv in self._completed_laps if inv)
        self._writer.writerow(["Z", "fastest_lap",   fastest])
        self._writer.writerow(["Z", "avg_clean_lap", avg_clean])
        self._writer.writerow(["Z", "std_dev",       std_dev])
        self._writer.writerow(["Z", "invalid_laps",  invalid_count])
        self._writer.writerow(["Z", "rewinds",       self._rewind_count])
        self._writer.writerow(["Z", "restarts",      self._restart_count])
        self._writer.writerow(["Z", "spins",         ""])
