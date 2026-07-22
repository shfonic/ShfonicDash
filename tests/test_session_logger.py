"""Format-level tests for the session CSV log.

The typed-row CSV (S/GH/G/H/L/EH/E/RH/R/Z) is a versioned format consumed by
external tools (Pythonista companion app) — see docs/session-log-format.md.
These tests feed synthetic TelemetryData through SessionLogger and assert on
the rows actually written.
"""
import csv

import pytest

from core.session_logger import SessionLogger
from core.telemetry_model import TelemetryData


@pytest.fixture
def logger(tmp_path):
    lg = SessionLogger(str(tmp_path))
    yield lg
    lg.close()


def _tick(lg, session_type="practice", **kwargs):
    lg.update(TelemetryData(game="f1_25", session_type=session_type, **kwargs))


def _rows(lg):
    """Close and read the finished file. The session must have completed at
    least one lap — close() deletes zero-lap files (noise sessions)."""
    lg.close()
    with open(lg.active_file, newline="") as f:
        return list(csv.reader(f))


def _rows_live(lg):
    """Read the still-open file (every write is flushed). For tests whose
    sessions never complete a lap: closing would delete the file. Rows
    written at close (R standings, Z summary) are not present."""
    with open(lg.active_file, newline="") as f:
        return list(csv.reader(f))


def _rows_of_type(rows, row_type):
    return [r for r in rows if r and r[0] == row_type]


def test_set_focus_writes_f_row_once(logger):
    _tick(logger, car_class="gt3", track="Monza")
    logger.set_focus("consistency")
    logger.set_focus("faster")           # second pick ignored — first sticks
    rows = _rows_live(logger)
    f_rows = _rows_of_type(rows, "F")
    assert f_rows == [["F", "consistency"]]


def test_set_focus_ignored_with_no_open_file(tmp_path):
    lg = SessionLogger(str(tmp_path))
    lg.set_focus("clean")                # no session open yet — must not raise
    _tick(lg, car_class="gt3", track="Monza")
    assert _rows_of_type(_rows_live(lg), "F") == []
    lg.close()


def test_set_focus_resets_on_new_session(logger):
    _tick(logger, session_type="practice", track="Monza")
    logger.set_focus("clean")
    _tick(logger, session_type="qualifying", track="Monza")   # rotates file
    logger.set_focus("faster")
    assert _rows_of_type(_rows_live(logger), "F") == [["F", "faster"]]


def test_metadata_rows_written_on_open(logger):
    _tick(logger, car_class="gt3", track="Monza")
    rows = _rows_live(logger)

    s = {r[1]: r[2] for r in _rows_of_type(rows, "S")}
    assert s["version"] == "1"
    from version import __version__
    assert s["app_version"] == __version__
    assert s["game"] == "f1_25"
    assert s["session_type"] == "practice"
    assert s["car_class"] == "gt3"
    assert s["track"] == "Monza"


def test_weather_metadata_written_and_updated(logger):
    _tick(logger, weather="clear", air_temp=21.0, track_temp=34.0)
    _tick(logger, weather="clear", air_temp=21.0, track_temp=34.0)   # no change → no new row
    _tick(logger, weather="light_rain", air_temp=21.0, track_temp=34.0)
    rows = _rows_live(logger)

    s = {r[1]: r[2] for r in _rows_of_type(rows, "S")}
    assert s["air_temp"] == "21"
    assert s["track_temp"] == "34"
    weather_rows = [r for r in _rows_of_type(rows, "S") if r[1] == "weather"]
    assert [r[2] for r in weather_rows] == ["clear", "light_rain"]
    assert s["weather"] == "light_rain"   # parsers keep the last value


def test_weather_unknown_is_empty(logger):
    _tick(logger)   # Forza-style source: no weather fields set
    rows = _rows_live(logger)

    s = {r[1]: r[2] for r in _rows_of_type(rows, "S")}
    assert s["weather"] == ""
    assert s["air_temp"] == ""
    assert s["track_temp"] == ""


def test_team_id_raw_written_when_participants_arrive_late(logger):
    _tick(logger)                     # session opens before participant packet
    _tick(logger, team_id_raw=142)    # 2026 DLC id arrives later
    rows = _rows_live(logger)

    s = {r[1]: r[2] for r in _rows_of_type(rows, "S")}
    assert s["team_id_raw"] == "142"


def test_lap_row_contents(logger):
    _tick(logger, lap_number=1, lap_time=10.0, sector1_time=28.5)
    _tick(logger, lap_number=1, lap_time=60.0, sector1_time=28.5, sector2_time=59.0)
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=90.0,
          tyre_temp=(80.0, 81.0, 82.0, 83.0), tyre_compound="Soft",
          fuel_remaining=42.5, position=3)
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    laps   = _rows_of_type(rows, "L")
    assert len(laps) == 1
    lap = dict(zip(header[1:], laps[0][1:]))
    assert lap["lap_num"] == "1"
    assert lap["lap_time"] == "90.0"
    assert lap["s1"] == "28.5"
    assert lap["s2"] == "30.5"
    assert lap["s3"] == "31.0"
    assert lap["tyre_fl"] == "80.0"
    assert lap["tyre_compound"] == "Soft"
    assert lap["position"] == "3"
    assert lap["invalid"] == "0"
    assert lap["rewinds"] == "0"
    assert lap["assist_tc"] == "0"
    assert lap["assist_racing_line"] == "0"
    assert lap["delta"] == ""   # no prior best yet


def test_final_race_lap_logged_on_finish(logger):
    # The last lap of a race is never followed by a counter tick (the game
    # marks the driver "finished" instead), so it must be flushed on the
    # finish frame — with that frame's final classified position.
    _tick(logger, session_type="race", lap_number=1, lap_time=10.0)
    _tick(logger, session_type="race", lap_number=2, lap_time=0.2,
          last_lap=90.0, position=12)                       # lap 1 -> P12
    _tick(logger, session_type="race", lap_number=2, lap_time=60.0,
          position=12)
    # Cross the line to finish: counter stays on 2, last_lap is the final
    # time, and the classified position has dropped to P13.
    _tick(logger, session_type="race", lap_number=2, lap_time=0.1,
          last_lap=91.5, position=13, finish_status="finished")
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    laps   = _rows_of_type(rows, "L")
    assert len(laps) == 2                                   # both laps logged
    final = dict(zip(header[1:], laps[-1][1:]))
    assert final["lap_num"] == "2"
    assert final["lap_time"] == "91.5"
    assert final["position"] == "13"                        # the finish drop


def test_lap_row_delta_is_tracked_independently_of_live_telemetry(logger):
    """The CSV delta is `lap.time - best CLEAN lap so far`, computed by the
    logger itself — not read from TelemetryData.delta/best_lap, which by
    the time this snapshot is polled has already moved on to track the lap
    that just started (a live in-race HUD value, raced by the background
    UDP thread — observed 2026-07-15: every delta read as near-zero)."""
    _tick(logger, lap_number=1, lap_time=10.0)
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=90.0,
          delta=999.0, best_lap=999.0)   # live telemetry fields must be ignored
    _tick(logger, lap_number=2, lap_time=10.0)
    _tick(logger, lap_number=3, lap_time=0.2, last_lap=88.5,
          delta=-0.001, best_lap=88.5)
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    laps   = _rows_of_type(rows, "L")
    lap1 = dict(zip(header[1:], laps[0][1:]))
    lap2 = dict(zip(header[1:], laps[1][1:]))
    assert lap1["delta"] == ""          # first lap — nothing to compare against
    assert lap2["delta"] == "-1.5"      # 88.5 - 90.0, not live telemetry's -0.001


def test_invalid_lap_gets_a_delta_but_never_becomes_the_new_best(logger):
    _tick(logger, lap_number=1, lap_time=10.0, lap_distance=500.0)
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=90.0, lap_distance=10.0)
    _tick(logger, lap_number=2, lap_time=5.0, lap_distance=300.0)
    _tick(logger, lap_number=2, lap_time=6.0, lap_distance=350.0, lap_invalid=True)
    # Lap 2: 85.0s — faster than the lap 1 best, but invalid.
    _tick(logger, lap_number=3, lap_time=0.2, last_lap=85.0, lap_distance=10.0)
    _tick(logger, lap_number=3, lap_time=10.0, lap_distance=500.0)
    # Lap 3: 89.0s clean — should compare against lap 1's 90.0, not lap 2's 85.0.
    _tick(logger, lap_number=4, lap_time=0.2, last_lap=89.0, lap_distance=10.0)
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    laps   = _rows_of_type(rows, "L")
    lap2 = dict(zip(header[1:], laps[1][1:]))
    lap3 = dict(zip(header[1:], laps[2][1:]))
    assert lap2["invalid"] == "1"
    assert lap2["delta"] == "-5.0"   # 85.0 - 90.0 — still against the clean best
    assert lap3["delta"] == "-1.0"   # 89.0 - 90.0 — lap 2 never became the new best


def test_rewound_lap_never_becomes_the_new_best(logger):
    _tick(logger, lap_number=1, lap_time=10.0)
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=90.0)
    _tick(logger, lap_number=2, lap_time=5.0)
    _tick(logger, lap_number=2, lap_time=3.0)   # backwards jump -> rewind
    _tick(logger, lap_number=3, lap_time=0.2, last_lap=85.0)   # lap 2: 85.0, rewound
    _tick(logger, lap_number=3, lap_time=10.0)
    _tick(logger, lap_number=4, lap_time=0.2, last_lap=89.0)   # lap 3: clean
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    laps   = _rows_of_type(rows, "L")
    lap2 = dict(zip(header[1:], laps[1][1:]))
    lap3 = dict(zip(header[1:], laps[2][1:]))
    assert lap2["rewinds"] == "1"
    assert lap2["delta"] == "-5.0"   # 85.0 - 90.0 — still against the clean best
    assert lap3["delta"] == "-1.0"   # 89.0 - 90.0 — lap 2 never became the new best


def test_lap_row_assist_columns_track_highest_seen(logger):
    """A driver can toggle an assist on mid-lap and back off before the
    line — the lap must still log the raised value, not a snapshot."""
    _tick(logger, lap_number=1, lap_time=10.0, tc_level=0)
    _tick(logger, lap_number=1, lap_time=30.0, tc_level=2)   # raised mid-lap
    _tick(logger, lap_number=1, lap_time=60.0, tc_level=0)   # lowered again
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=90.0, tc_level=0)
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    laps   = _rows_of_type(rows, "L")
    lap = dict(zip(header[1:], laps[0][1:]))
    assert lap["assist_tc"] == "2"


def test_assist_reading_on_lap_completing_frame_belongs_to_new_lap(logger):
    """LapTracker fires LapCompleted on the FIRST frame of the NEW lap (its
    lap_number is already incremented) — that frame's own assist reading
    must count towards the new lap, never leak into the one that just
    finished."""
    _tick(logger, lap_number=1, lap_time=10.0, tc_level=0)
    _tick(logger, lap_number=1, lap_time=60.0, tc_level=0)
    # This frame completes lap 1 and carries a raised tc_level — belongs to lap 2.
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=90.0, tc_level=2)
    _tick(logger, lap_number=2, lap_time=30.0, tc_level=0)
    _tick(logger, lap_number=3, lap_time=0.1, last_lap=91.0, tc_level=0)
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    laps   = _rows_of_type(rows, "L")
    lap1 = dict(zip(header[1:], laps[0][1:]))
    lap2 = dict(zip(header[1:], laps[1][1:]))
    assert lap1["assist_tc"] == "0"
    assert lap2["assist_tc"] == "2"


def test_assist_forced_in_pits_excluded_from_lap_max(logger):
    """F1 forces TC/ABS on while the pit limiter is engaged, exiting the
    garage — that's a safety mechanic, not the driver's setting, so it must
    not count as "assist used" for the out-lap (observed 2026-07-15: a
    driver with everything off the whole session had lap 1 falsely show
    TC/ABS on, purely from the garage/pit-lane exit)."""
    _tick(logger, lap_number=1, lap_time=1.0, tc_level=2, abs_level=1, in_pits=True)
    _tick(logger, lap_number=1, lap_time=5.0, tc_level=0, abs_level=0, in_pits=False)
    _tick(logger, lap_number=1, lap_time=60.0, tc_level=0, abs_level=0)
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=90.0, tc_level=0, abs_level=0)
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    lap = dict(zip(header[1:], _rows_of_type(rows, "L")[0][1:]))
    assert lap["assist_tc"] == "0"
    assert lap["assist_abs"] == "0"


def test_assists_on_the_auto_driven_run_up_excluded_from_lap_max(logger):
    """An F1 hotlap/TT start auto-drives the car for the last few corners
    before the S/F line under a countdown, and the AI drives it with ABS on.
    Those frames are before the line (negative lap_distance) but already carry
    lap 1's number — they are not the driver driving, so they must not count
    as "assist used" (observed 2026-07-17: a clean Spa TT logged "ABS on for 1
    of 12 laps" purely from the flying start)."""
    _tick(logger, session_type="hotlap", lap_number=1, lap_time=0.0,
          lap_distance=-6978.8, abs_level=1)      # auto-driven run-up
    _tick(logger, session_type="hotlap", lap_number=1, lap_time=0.0,
          lap_distance=-500.0, abs_level=1)       # still the AI, still before the line
    _tick(logger, session_type="hotlap", lap_number=1, lap_time=30.0,
          lap_distance=1500.0, abs_level=0)       # driver has taken over
    _tick(logger, session_type="hotlap", lap_number=2, lap_time=0.2,
          lap_distance=5.0, last_lap=90.0, abs_level=0)
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    lap = dict(zip(header[1:], _rows_of_type(rows, "L")[0][1:]))
    assert lap["assist_abs"] == "0"


def test_assist_raised_by_the_driver_on_the_timed_lap_still_counts(logger):
    """The run-up exclusion must not swallow a genuine mid-lap toggle once
    the car is past the line and the driver is driving it."""
    _tick(logger, session_type="hotlap", lap_number=1, lap_time=0.0,
          lap_distance=-500.0, abs_level=1)       # auto-driven — ignored
    _tick(logger, session_type="hotlap", lap_number=1, lap_time=30.0,
          lap_distance=1500.0, abs_level=1)       # driver's own ABS — counts
    _tick(logger, session_type="hotlap", lap_number=2, lap_time=0.2,
          lap_distance=5.0, last_lap=90.0, abs_level=0)
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    lap = dict(zip(header[1:], _rows_of_type(rows, "L")[0][1:]))
    assert lap["assist_abs"] == "1"


def test_assists_on_the_flying_lap_out_lap_excluded_from_lap_max(logger):
    """Leaving the garage via the "flying lap" option AI-drives the whole
    out-lap with ABS/TC forced on, and F1 books that transit onto the flyer's
    lap number — so without a guard the flyer gets tagged even though the
    driver ran it assist-free. The out-lap frames are on-track distance
    (positive, not in pits) but report driver_status 3 (out lap): the game is
    driving, so they must not count as the driver's assist use."""
    _tick(logger, lap_number=1, lap_time=25.0, lap_distance=2000.0,
          driver_status=3, tc_level=2, abs_level=1)   # AI-driven out lap
    _tick(logger, lap_number=1, lap_time=45.0, lap_distance=4000.0,
          driver_status=3, tc_level=2, abs_level=1)   # still the AI on the out lap
    _tick(logger, lap_number=2, lap_time=30.0, last_lap=88.0,
          lap_distance=1500.0, driver_status=1, tc_level=0, abs_level=0)  # driver's flyer
    _tick(logger, lap_number=3, lap_time=0.2, last_lap=85.0,
          lap_distance=5.0, driver_status=1, tc_level=0, abs_level=0)
    rows = _rows(logger)

    header = _rows_of_type(rows, "H")[0]
    # The flyer is lap 2 (the out-lap frames landed on lap 1 before the flyer began).
    laps = {r[1]: dict(zip(header[1:], r[1:])) for r in _rows_of_type(rows, "L")}
    assert laps["2"]["assist_tc"] == "0"
    assert laps["2"]["assist_abs"] == "0"


def test_mid_lap_rewind_writes_event_and_lap_counts_it(logger):
    _tick(logger, lap_number=1, lap_time=5.0)
    _tick(logger, lap_number=1, lap_time=45.0)
    _tick(logger, lap_number=1, lap_time=38.0)   # lap time jumped backwards
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=95.0)
    rows = _rows(logger)

    events = _rows_of_type(rows, "E")
    # r[:5] — the trailing `t` column is wall-clock and not asserted exactly
    assert ["E", "1", "45.0", "rewind", ""] in [r[:5] for r in events]
    header = _rows_of_type(rows, "H")[0]
    lap = dict(zip(header[1:], _rows_of_type(rows, "L")[0][1:]))
    assert lap["rewinds"] == "1"


def test_rewind_event_carries_lap_distance(logger):
    # A rewind's `distance` locates it on a track map (v0.25.0+) — same
    # treatment as `invalid`, so Race Engineer Notes can name the corner.
    _tick(logger, lap_number=1, lap_time=5.0, lap_distance=300.0)
    _tick(logger, lap_number=1, lap_time=45.0, lap_distance=1740.2)
    _tick(logger, lap_number=1, lap_time=38.0, lap_distance=1690.0)
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=95.0)
    rows = _rows(logger)

    events = _rows_of_type(rows, "E")
    assert ["E", "1", "45.0", "rewind", "1740.2"] in [r[:5] for r in events]


def test_restart_lap_writes_restart_event_not_rewind(logger):
    _tick(logger, lap_number=1, lap_time=5.0, lap_distance=300.0)
    _tick(logger, lap_number=1, lap_time=20.0, lap_distance=1200.0)
    # Time Trial "restart lap": clock reset, car before the S/F line
    _tick(logger, lap_number=1, lap_time=0.0, lap_distance=-150.0)
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=93.0, lap_distance=10.0)
    rows = _rows(logger)

    types = [r[3] for r in _rows_of_type(rows, "E")]
    assert types == ["restart"]
    header = _rows_of_type(rows, "H")[0]
    lap = dict(zip(header[1:], _rows_of_type(rows, "L")[0][1:]))
    assert lap["rewinds"] == "0"   # a restarted lap is a clean attempt, not a rewind
    z = {r[1]: r[2] for r in _rows_of_type(rows, "Z")}
    assert z["restarts"] == "1"
    assert z["rewinds"] == "0"


def test_lap_invalidated_writes_event_with_time_and_distance(logger):
    _tick(logger, lap_number=1, lap_time=5.0, lap_distance=300.0)
    _tick(logger, lap_number=1, lap_time=31.2, lap_distance=1842.7, lap_invalid=True)
    rows = _rows_live(logger)

    events = _rows_of_type(rows, "E")
    assert ["E", "1", "31.2", "invalid", "1842.7"] in [r[:5] for r in events]
    assert len([r for r in events if r[3] == "invalid"]) == 1
    # every E row carries a parseable wall-clock `t` as its final column
    assert all(float(r[5]) >= 0.0 for r in events)


def test_track_limit_warning_event_on_counter_increment(logger):
    # First observed value is the baseline — no event for pre-existing warnings
    _tick(logger, lap_number=1, lap_time=5.0, corner_cut_warnings=2)
    _tick(logger, lap_number=1, lap_time=31.2, lap_distance=1842.7,
          corner_cut_warnings=3)
    _tick(logger, lap_number=1, lap_time=40.0, corner_cut_warnings=3)
    rows = _rows_live(logger)

    events = [r[:5] for r in _rows_of_type(rows, "E") if r[3] == "track_limit_warning"]
    assert events == [["E", "1", "31.2", "track_limit_warning", "1842.7"]]


def test_pit_and_safety_car_events(logger):
    _tick(logger, lap_number=1, lap_time=5.0)
    _tick(logger, lap_number=1, lap_time=10.0, pit_limiter=True)
    _tick(logger, lap_number=1, lap_time=30.0)
    _tick(logger, lap_number=1, lap_time=40.0, safety_car="vsc")
    _tick(logger, lap_number=1, lap_time=50.0)
    rows = _rows_live(logger)

    types = [r[3] for r in _rows_of_type(rows, "E")]
    assert types == ["pit_in", "pit_out", "vsc_deploy", "vsc_clear"]


def test_pit_teleport_not_logged_as_rewind_or_restart(logger):
    # Practice tyre change: entering the pits teleports the car to the garage,
    # jumping lap_time backwards. Regression: this wrote rewind/restart events
    # (observed 2026-07-05 practice session).
    _tick(logger, lap_number=4, lap_time=10.0, lap_distance=600.0)
    _tick(logger, lap_number=4, lap_time=95.3, lap_distance=5574.0)
    _tick(logger, lap_number=4, lap_time=95.5, lap_distance=5590.0, in_pits=True)
    _tick(logger, lap_number=4, lap_time=4.9, lap_distance=71.7, in_pits=True)    # garage teleport
    _tick(logger, lap_number=4, lap_time=31.5, lap_distance=300.0, in_pits=True)
    _tick(logger, lap_number=4, lap_time=0.0, lap_distance=68.7, in_pits=True)    # second teleport
    _tick(logger, lap_number=4, lap_time=12.0, lap_distance=700.0)                # pit exit
    _tick(logger, lap_number=5, lap_time=0.2, lap_distance=10.0, last_lap=92.897)
    rows = _rows(logger)

    types = [r[3] for r in _rows_of_type(rows, "E")]
    assert types == ["pit_in", "pit_out"]   # one clean pair, nothing else
    header = _rows_of_type(rows, "H")[0]
    lap = dict(zip(header[1:], _rows_of_type(rows, "L")[0][1:]))
    assert lap["rewinds"] == "0"            # rewinds column untouched
    z = {r[1]: r[2] for r in _rows_of_type(rows, "Z")}
    assert z["rewinds"] == "0"
    assert z["restarts"] == "0"


def test_in_pits_suppresses_limiter_pit_events(logger):
    # With real pit status available, the limiter flapping in the garage must
    # not produce extra pit_in/pit_out pairs.
    _tick(logger, lap_number=1, lap_time=5.0)
    _tick(logger, lap_number=1, lap_time=10.0, in_pits=True, pit_limiter=True)
    _tick(logger, lap_number=1, lap_time=15.0, in_pits=True, pit_limiter=False)
    _tick(logger, lap_number=1, lap_time=18.0, in_pits=True, pit_limiter=True)
    _tick(logger, lap_number=1, lap_time=25.0, pit_limiter=False)
    rows = _rows_live(logger)

    types = [r[3] for r in _rows_of_type(rows, "E")]
    assert types == ["pit_in", "pit_out"]


def test_session_subtype_in_filename_and_meta(logger):
    _tick(logger, session_type="qualifying",
          session_subtype="sprint_qualifying", session_type_raw=10,
          lap_number=1, lap_time=5.0)
    rows = _rows_live(logger)

    assert "sprint_qualifying" in logger.active_file
    s = {r[1]: r[2] for r in _rows_of_type(rows, "S")}
    assert s["session_type"] == "qualifying"
    assert s["session_subtype"] == "sprint_qualifying"
    assert s["session_type_raw"] == "10"


def test_subtype_change_rotates_file(logger):
    _tick(logger, session_type="qualifying",
          session_subtype="sprint_qualifying", lap_number=1, lap_time=5.0)
    first = logger.active_file
    _tick(logger, session_type="qualifying", lap_number=1, lap_time=6.0)

    assert logger.active_file != first
    assert "sprint_qualifying" not in logger.active_file


def test_grid_and_final_standings(logger):
    parts = [
        {"position": 1, "race_number": 1,  "name": "VER", "best_lap": 88.123},
        {"position": 2, "race_number": 81, "name": "PIA", "best_lap": 88.456},
    ]
    _tick(logger, participants=parts, lap_number=1, lap_time=5.0)
    _tick(logger, participants=parts, lap_number=2, lap_time=0.2, last_lap=90.0)
    rows = _rows(logger)

    grid = _rows_of_type(rows, "G")
    assert grid[0] == ["G", "1", "1", "VER"]
    results = _rows_of_type(rows, "R")
    assert results[1] == ["R", "2", "81", "PIA", "88.456", ""]


def test_race_standings_include_race_time(logger):
    parts = [
        {"position": 1, "race_number": 4, "name": "NOR", "best_lap": 70.167, "race_time": 5401.5},
        {"position": 2, "race_number": 0, "name": "PIA", "best_lap": 70.47,  "race_time": 5403.211},
        {"position": 3, "race_number": 1, "name": "VER", "best_lap": 70.549, "race_time": 0.0},
    ]
    _tick(logger, session_type="race", participants=parts, lap_number=1, lap_time=5.0)
    _tick(logger, session_type="race", participants=parts, lap_number=2,
          lap_time=0.2, last_lap=90.0)
    rows = _rows(logger)

    results = _rows_of_type(rows, "R")
    assert results[0] == ["R", "1", "4", "NOR", "70.167", "5401.5"]
    # Unknown race number (0) → empty cell, not a literal 0
    assert results[1] == ["R", "2", "", "PIA", "70.47", "5403.211"]
    # DNF — no classified race time
    assert results[2] == ["R", "3", "1", "VER", "70.549", ""]


def test_hotlap_session_has_no_grid_or_standings(logger):
    # F1 Time Trial broadcasts ghost/rival slots as nameless cars at position 1
    parts = [{"position": 1, "race_number": 0, "name": "Shfonic", "best_lap": 0.0}]
    _tick(logger, session_type="hotlap", participants=parts, lap_number=1, lap_time=5.0)
    _tick(logger, session_type="hotlap", participants=parts, lap_number=2, lap_time=0.2, last_lap=95.0)
    rows = _rows(logger)

    assert not [r for r in rows if r[0] in ("GH", "G", "RH", "R")]
    assert len(_rows_of_type(rows, "L")) == 1   # laps still logged


def test_summary_rows(logger):
    _tick(logger, lap_number=1, lap_time=5.0)
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=90.0)
    _tick(logger, lap_number=3, lap_time=0.2, last_lap=92.0)
    rows = _rows(logger)

    z = {r[1]: r[2] for r in _rows_of_type(rows, "Z")}
    assert z["fastest_lap"] == "90.0"
    assert z["avg_clean_lap"] == "91.0"
    assert z["invalid_laps"] == "0"
    assert z["rewinds"] == "0"


def test_session_change_rotates_file(logger):
    _tick(logger, session_type="practice", lap_number=1, lap_time=5.0)
    first = logger.active_file
    _tick(logger, session_type="qualifying", lap_number=1, lap_time=5.0)
    assert logger.active_file != first


def test_track_change_rotates_file(logger):
    # Switching circuits in Time Trial keeps session_type == "hotlap" — the
    # file must still rotate so the new track doesn't append to the old one.
    # (Bank a lap first so the first file survives close and the new file is
    # a genuinely different path, not the reused name of a deleted zero-lap
    # fragment.)
    _tick(logger, session_type="hotlap", track="Melbourne", lap_number=1, lap_time=5.0)
    _tick(logger, session_type="hotlap", track="Melbourne", lap_number=2, lap_time=0.2, last_lap=90.0)
    first = logger.active_file
    _tick(logger, session_type="hotlap", track="Silverstone", lap_number=1, lap_time=5.0)
    assert logger.active_file != first


def test_late_or_blank_track_does_not_rotate(logger):
    # A blank/late track (load glitch) must not spuriously rotate the file.
    _tick(logger, session_type="hotlap", track="Melbourne", lap_number=1, lap_time=5.0)
    first = logger.active_file
    _tick(logger, session_type="hotlap", track="", lap_number=2, lap_time=0.2, last_lap=90.0)
    assert logger.active_file == first


def test_reopens_after_close_when_same_session_continues(logger):
    """Menu round-trip mid-race: App.run() closes the shared logger on exit to
    the menu; re-entering the game while the race is still running must reopen
    a fresh file — previously every subsequent row was silently dropped."""
    _tick(logger, session_type="race", lap_number=1, lap_time=5.0)
    _tick(logger, session_type="race", lap_number=2, lap_time=0.5, last_lap=70.0)
    first = logger.active_file
    logger.close()   # user long-presses back to the menu

    # User re-enters F1 — the game is still in the same race session
    _tick(logger, session_type="race", lap_number=3, lap_time=5.0)
    assert logger.active_file is not None
    assert logger.active_file != first   # fresh file, first fragment untouched
    _tick(logger, session_type="race", lap_number=4, lap_time=0.5, last_lap=71.0)

    rows = _rows(logger)
    laps = _rows_of_type(rows, "L")
    assert len(laps) == 1
    assert laps[0][1] == "3" and laps[0][2] == "71.0"

    with open(first, newline="") as f:
        first_laps = _rows_of_type(list(csv.reader(f)), "L")
    assert len(first_laps) == 1   # lap from before the menu exit still there


def test_incident_events_written_with_detail(logger):
    _tick(logger, lap_number=7, lap_time=5.0)
    _tick(logger, lap_number=7, lap_time=31.2, events=[
        {"type": "collision", "detail": "VERSTAPPEN",
         "lap_num": 7, "lap_time": 31.2, "distance": 1842.7},
        {"type": "penalty", "detail": "time_penalty:corner_cutting_gained_time",
         "lap_num": 7, "lap_time": 31.2, "distance": 1842.7},
    ])
    _tick(logger, lap_number=7, lap_time=40.0, events=[
        {"type": "overtake", "detail": "NORRIS",
         "lap_num": 7, "lap_time": 40.0, "distance": 2400.0},
    ])
    rows = _rows_live(logger)

    header = _rows_of_type(rows, "EH")[0]
    assert header[1:] == ["lap_num", "lap_time", "type", "distance", "t", "detail"]
    events = [dict(zip(header[1:], r[1:])) for r in _rows_of_type(rows, "E")]
    assert [(e["type"], e["detail"], e["distance"]) for e in events] == [
        ("collision", "VERSTAPPEN", "1842.7"),
        ("penalty", "time_penalty:corner_cutting_gained_time", "1842.7"),
        ("overtake", "NORRIS", "2400.0"),
    ]


# ── Zero-lap sessions and the trash (v0.1.140) ─────────────────────────────────

def test_zero_lap_session_deleted_on_close(logger, tmp_path):
    _tick(logger, lap_number=1, lap_time=5.0)   # opened, but no lap completed
    path = logger.active_file
    import os
    assert os.path.exists(path)
    assert logger.close() is None
    assert not os.path.exists(path)
    assert logger.active_file is None


def test_zero_lap_session_deleted_on_rotation(logger):
    _tick(logger, session_type="practice", lap_number=1, lap_time=5.0)
    first = logger.active_file
    _tick(logger, session_type="qualifying", lap_number=1, lap_time=1.0)
    import os
    assert not os.path.exists(first)            # noise fragment removed


def test_session_with_laps_survives_close(logger):
    _tick(logger, lap_number=1, lap_time=5.0)
    _tick(logger, lap_number=2, lap_time=0.2, last_lap=90.0)
    path = logger.close()
    import os
    assert path and os.path.exists(path)


def test_trash_session_moves_file(tmp_path):
    from core.session_logger import trash_session
    (tmp_path / "session_20260707_1000_race.csv").write_text("S,version,1\n")
    assert trash_session(str(tmp_path), "session_20260707_1000_race.csv")
    assert not (tmp_path / "session_20260707_1000_race.csv").exists()
    assert (tmp_path / ".trash" / "session_20260707_1000_race.csv").exists()
    # Same name again: suffixed, never overwritten
    (tmp_path / "session_20260707_1000_race.csv").write_text("S,version,1\n")
    assert trash_session(str(tmp_path), "session_20260707_1000_race.csv")
    assert (tmp_path / ".trash" / "session_20260707_1000_race_2.csv").exists()


def test_trash_session_missing_file_is_false(tmp_path):
    from core.session_logger import trash_session
    assert trash_session(str(tmp_path), "nope.csv") is False


def test_cleanup_trash_prunes_old_only(tmp_path):
    import os
    import time
    from core.session_logger import cleanup_trash
    trash = tmp_path / ".trash"
    trash.mkdir()
    old = trash / "session_20260101_1000_race.csv"
    new = trash / "session_20260707_1000_race.csv"
    keep = tmp_path / "session_20260101_1000_race.csv"   # NOT in trash
    for f in (old, new, keep):
        f.write_text("S,version,1\n")
    stale = time.time() - 40 * 86400
    os.utime(old, (stale, stale))
    os.utime(keep, (stale, stale))
    cleanup_trash(str(tmp_path), keep_days=30)
    assert not old.exists()
    assert new.exists()
    assert keep.exists()   # session files outside the trash are never touched


# ---------------------------------------------------------------------------
# Racing-line offset profiles (P rows) — the LineTracker wiring
# ---------------------------------------------------------------------------

def _write_ring_map(tracks_dir, radius=100.0, n=60):
    import json
    import math
    import os
    os.makedirs(tracks_dir, exist_ok=True)
    racing = [[radius * math.cos(2 * math.pi * i / n),
               radius * math.sin(2 * math.pi * i / n)] for i in range(n)]
    tmap = {"format_version": 1, "game": "f1_25", "track": "TestRing",
            "game_track_length_m": 2 * math.pi * radius,
            "lines": {"formula1": {"racing_line": racing, "racing_attempts": 3}},
            "sections": [{"type": "corner", "turn": "1", "name": "Turn 1",
                          "start_m": 50, "end_m": 250, "apex_m": 150}]}
    with open(os.path.join(tracks_dir, "f1-25_testring.json"), "w") as f:
        json.dump(tmap, f)
    return 2 * math.pi * radius, n


def _drive_ring_lap(lg, length, lap_number, player_radius, steps=120):
    import math
    for i in range(steps):
        u = i / steps
        ang = 2 * math.pi * u
        lg.update(TelemetryData(
            game="f1_25", session_type="hotlap", car_class="formula1",
            track="TestRing", lap_number=lap_number, lap_distance=u * length,
            last_lap=(90.0 if lap_number > 1 else 0.0),
            pos_x=player_radius * math.cos(ang),
            pos_z=player_radius * math.sin(ang), pos_valid=True))


def test_p_rows_written_for_f1_hotlap_with_map(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    length, n = _write_ring_map(str(tmp_path / "tracks"))
    lg = SessionLogger(str(logs))
    # Lap 1 driven 2 m outside the line, then cross S/F to complete it.
    _drive_ring_lap(lg, length, 1, 102.0)
    _drive_ring_lap(lg, length, 2, 102.0)
    lg.update(TelemetryData(game="f1_25", session_type="hotlap",
                            car_class="formula1", track="TestRing",
                            lap_number=3, lap_distance=1.0, last_lap=90.0,
                            pos_x=102.0, pos_z=0.0, pos_valid=True))
    rows = _rows(lg)
    p_rows = [r for r in rows if r and r[0] == "P"]
    assert p_rows, "expected P rows for an F1 hotlap at a mapped track"
    # First profile is lap 1; offsets are decimetres, ~+20 (2 m outside → right).
    assert p_rows[0][1] == "1"
    vals = [int(v) for v in p_rows[0][2:]]
    assert len(vals) == n
    assert all(17 <= v <= 23 for v in vals)
    # The line_ref S row records the line's attempt count.
    assert any(r[:2] == ["S", "line_ref"] and r[2] == "3" for r in rows)


def test_no_p_rows_without_map(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    # No tracks dir → no racing line → no P rows, everything else unchanged.
    lg = SessionLogger(str(logs))
    length = 628.318
    _drive_ring_lap(lg, length, 1, 102.0)
    _drive_ring_lap(lg, length, 2, 102.0)
    lg.update(TelemetryData(game="f1_25", session_type="hotlap",
                            car_class="formula1", track="TestRing",
                            lap_number=3, lap_distance=1.0, last_lap=90.0,
                            pos_valid=True))
    rows = _rows(lg)
    assert not [r for r in rows if r and r[0] == "P"]
    assert [r for r in rows if r and r[0] == "L"]   # laps still logged
