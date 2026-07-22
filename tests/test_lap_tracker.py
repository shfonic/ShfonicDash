import pytest

from core.lap_tracker import LapCompleted, LapInvalidated, LapTracker, Restart, Rewind
from core.telemetry_model import TelemetryData


def _tick(tracker, lap_number=1, lap_time=0.0, last_lap=0.0,
          sector1_time=0.0, sector2_time=0.0, lap_invalid=False,
          lap_distance=0.0, finish_status=""):
    return tracker.update(TelemetryData(
        lap_number=lap_number, lap_time=lap_time, last_lap=last_lap,
        sector1_time=sector1_time, sector2_time=sector2_time,
        lap_invalid=lap_invalid, lap_distance=lap_distance,
        finish_status=finish_status,
    ))


def test_no_events_during_normal_lap():
    t = LapTracker()
    assert _tick(t, lap_number=1, lap_time=5.0) == []
    assert _tick(t, lap_number=1, lap_time=10.0) == []


def test_lap_completion_with_sectors():
    t = LapTracker()
    _tick(t, lap_number=1, lap_time=10.0, sector1_time=28.5)
    _tick(t, lap_number=1, lap_time=60.0, sector1_time=28.5, sector2_time=59.0)
    events = _tick(t, lap_number=2, lap_time=0.2, last_lap=90.0)

    assert len(events) == 1
    lap = events[0]
    assert isinstance(lap, LapCompleted)
    assert lap.num == 1
    assert lap.time == 90.0
    assert lap.s1 == pytest.approx(28.5)
    assert lap.s2 == pytest.approx(30.5)   # 59.0 cumulative − 28.5
    assert lap.s3 == pytest.approx(31.0)   # 90.0 − 59.0
    assert lap.invalid is False
    assert lap.rewinds == 0


def test_no_completion_on_first_lap_seen():
    # Connecting mid-session: lap_number jumps 0 → 3 must not commit a lap
    t = LapTracker()
    assert _tick(t, lap_number=3, lap_time=12.0, last_lap=88.0) == []


def test_invalid_flag_sticks_until_completion():
    t = LapTracker()
    _tick(t, lap_number=1, lap_time=5.0)
    _tick(t, lap_number=1, lap_time=10.0, lap_invalid=True)
    _tick(t, lap_number=1, lap_time=20.0)          # flag cleared in telemetry
    events = _tick(t, lap_number=2, lap_time=0.2, last_lap=90.0)
    assert events[0].invalid is True

    # Next lap starts clean
    events = _tick(t, lap_number=3, lap_time=0.2, last_lap=85.0)
    assert events[0].invalid is False


def test_invalid_on_completion_tick_belongs_to_new_lap():
    t = LapTracker()
    _tick(t, lap_number=1, lap_time=5.0)
    events = _tick(t, lap_number=2, lap_time=0.2, last_lap=90.0, lap_invalid=True)
    assert events[0].invalid is False   # completed lap was clean
    events = _tick(t, lap_number=3, lap_time=0.1, last_lap=91.0)
    assert events[0].invalid is True    # carried into the lap that was running


def test_mid_lap_rewind_detected_from_lap_time_jump_back():
    t = LapTracker()
    _tick(t, lap_number=2, lap_time=5.0)
    _tick(t, lap_number=2, lap_time=45.0, sector1_time=28.0)
    events = _tick(t, lap_number=2, lap_time=38.0)   # rewound 7 s

    assert len(events) == 1
    rw = events[0]
    assert isinstance(rw, Rewind)
    assert rw.crossed_sf is False
    assert rw.lap_num == 2
    assert rw.lap_time == pytest.approx(45.0)


def test_small_lap_time_jitter_is_not_a_rewind():
    t = LapTracker()
    _tick(t, lap_number=2, lap_time=45.0)
    assert _tick(t, lap_number=2, lap_time=44.99) == []


def test_sf_crossing_rewind():
    t = LapTracker()
    _tick(t, lap_number=3, lap_time=2.0)
    events = _tick(t, lap_number=2, lap_time=80.0)

    assert len(events) == 1
    rw = events[0]
    assert isinstance(rw, Rewind)
    assert rw.crossed_sf is True
    assert rw.lap_num == 3


def test_rewind_count_reported_on_completion():
    t = LapTracker()
    _tick(t, lap_number=1, lap_time=5.0)
    _tick(t, lap_number=1, lap_time=40.0)
    _tick(t, lap_number=1, lap_time=30.0)   # rewind 1
    _tick(t, lap_number=1, lap_time=50.0)
    _tick(t, lap_number=1, lap_time=42.0)   # rewind 2
    events = _tick(t, lap_number=2, lap_time=0.2, last_lap=95.0)
    assert events[0].rewinds == 2

    events = _tick(t, lap_number=3, lap_time=0.2, last_lap=94.0)
    assert events[0].rewinds == 0


def test_rewind_resets_pending_sectors():
    t = LapTracker()
    _tick(t, lap_number=1, lap_time=30.0, sector1_time=28.0)
    _tick(t, lap_number=1, lap_time=10.0)   # mid-lap rewind to before S1
    events = _tick(t, lap_number=2, lap_time=0.2, last_lap=90.0)
    assert events[0].s1 == 0.0              # stale sector was discarded


def test_restart_lap_detected_by_negative_distance():
    """F1 Time Trial 'restart lap': lap_time jumps back but the car lands on
    the run-up before the S/F line (negative lap_distance, clock at 0)."""
    t = LapTracker()
    _tick(t, lap_number=3, lap_time=20.0, lap_distance=1200.0)
    events = _tick(t, lap_number=3, lap_time=0.0, lap_distance=-150.0)

    assert len(events) == 1
    rs = events[0]
    assert isinstance(rs, Restart)
    assert rs.lap_num == 3
    assert rs.lap_time == pytest.approx(20.0)


def test_restart_not_counted_as_rewind_on_completion():
    t = LapTracker()
    _tick(t, lap_number=3, lap_time=20.0, lap_distance=1200.0)
    _tick(t, lap_number=3, lap_time=0.0, lap_distance=-150.0)   # restart
    _tick(t, lap_number=3, lap_time=45.0, lap_distance=2400.0)
    events = _tick(t, lap_number=4, lap_time=0.2, last_lap=93.0)
    assert isinstance(events[0], LapCompleted)
    assert events[0].rewinds == 0


def test_restart_clears_pending_invalid():
    # The abandoned attempt was invalid; the restarted attempt starts clean
    t = LapTracker()
    _tick(t, lap_number=3, lap_time=20.0, lap_invalid=True, lap_distance=1200.0)
    _tick(t, lap_number=3, lap_time=0.0, lap_distance=-150.0)   # restart
    _tick(t, lap_number=3, lap_time=45.0, lap_distance=2400.0)
    events = _tick(t, lap_number=4, lap_time=0.2, last_lap=93.0)
    assert events[0].invalid is False


def test_flashback_with_positive_distance_is_still_a_rewind():
    t = LapTracker()
    _tick(t, lap_number=2, lap_time=45.0, lap_distance=2400.0)
    events = _tick(t, lap_number=2, lap_time=38.0, lap_distance=2100.0)
    assert isinstance(events[0], Rewind)


def test_lap_invalidated_event_emitted_once_at_transition():
    t = LapTracker()
    _tick(t, lap_number=2, lap_time=5.0)
    events = _tick(t, lap_number=2, lap_time=31.2, lap_invalid=True)
    assert len(events) == 1
    inv = events[0]
    assert isinstance(inv, LapInvalidated)
    assert inv.lap_num == 2
    assert inv.lap_time == pytest.approx(31.2)

    # Still invalid on later ticks — no repeat event
    assert _tick(t, lap_number=2, lap_time=40.0, lap_invalid=True) == []


def test_invalid_on_outlap_runup_is_ignored():
    """TT sessions start a few corners before the S/F line (negative distance).
    An off there is not part of the timed lap: no event, and the lap that
    then crosses the line must not inherit the invalid flag."""
    t = LapTracker()
    _tick(t, lap_number=1, lap_time=0.0, lap_distance=-400.0)
    events = _tick(t, lap_number=1, lap_time=0.0, lap_invalid=True,
                   lap_distance=-295.7)
    assert events == []

    # Game clears the flag as the timed lap starts; lap completes clean
    _tick(t, lap_number=1, lap_time=30.0, lap_distance=1800.0)
    events = _tick(t, lap_number=2, lap_time=0.2, last_lap=92.9, lap_distance=5.0)
    assert isinstance(events[0], LapCompleted)
    assert events[0].invalid is False


def test_invalid_carried_across_line_is_latched_after_it():
    # If the game keeps the flag set past the S/F line, follow the game
    t = LapTracker()
    _tick(t, lap_number=1, lap_time=0.0, lap_invalid=True, lap_distance=-295.7)
    events = _tick(t, lap_number=1, lap_time=0.5, lap_invalid=True, lap_distance=12.0)
    assert isinstance(events[0], LapInvalidated)


def test_reset_clears_state():
    t = LapTracker()
    _tick(t, lap_number=5, lap_time=20.0)
    t.reset()
    # Lap 5 → 6 after reset must not commit (no known previous lap)
    assert _tick(t, lap_number=6, lap_time=0.2, last_lap=90.0) == []


def test_final_lap_flushed_on_race_finish():
    # A race finish marks the driver "finished" WITHOUT ticking the lap counter
    # past the final lap, so the increment path never completes it. The finish
    # flush must emit it once, using last_lap for the time.
    t = LapTracker()
    # Lap 1 completes normally on the tick to lap 2.
    _tick(t, lap_number=1, lap_time=10.0, sector1_time=28.5)
    _tick(t, lap_number=1, lap_time=60.0, sector1_time=28.5, sector2_time=59.0)
    assert len(_tick(t, lap_number=2, lap_time=0.2, last_lap=90.0)) == 1
    # Driving lap 2 (the final lap) — sectors stream in.
    _tick(t, lap_number=2, lap_time=30.0, sector1_time=29.0)
    _tick(t, lap_number=2, lap_time=60.0, sector1_time=29.0, sector2_time=60.0)
    # Cross the line to finish: counter stays on 2, last_lap = the final time,
    # finish_status flips to "finished".
    events = _tick(t, lap_number=2, lap_time=0.1, last_lap=91.5,
                   sector1_time=29.0, sector2_time=60.0,
                   finish_status="finished")
    laps = [e for e in events if isinstance(e, LapCompleted)]
    assert len(laps) == 1
    assert laps[0].num == 2
    assert laps[0].time == pytest.approx(91.5)
    assert laps[0].s1 == pytest.approx(29.0)
    assert laps[0].s2 == pytest.approx(31.0)   # 60.0 cumulative − 29.0
    assert laps[0].s3 == pytest.approx(31.5)   # 91.5 − 60.0


def test_finish_flush_fires_only_once():
    t = LapTracker()
    _tick(t, lap_number=1, lap_time=10.0)
    _tick(t, lap_number=2, lap_time=0.2, last_lap=90.0)   # completes lap 1
    _tick(t, lap_number=2, lap_time=60.0)
    first = _tick(t, lap_number=2, lap_time=0.1, last_lap=91.5,
                  finish_status="finished")
    assert len([e for e in first if isinstance(e, LapCompleted)]) == 1
    # Subsequent finished frames (cool-down) must not re-emit the final lap.
    again = _tick(t, lap_number=2, lap_time=5.0, last_lap=91.5,
                  finish_status="finished")
    assert [e for e in again if isinstance(e, LapCompleted)] == []


def test_no_finish_flush_when_counter_ticks_at_line():
    # A game that DOES advance the counter at the flag completes the final lap
    # via the normal increment path; the finish flush must not double-log it
    # (last_lap still equals the just-completed lap).
    t = LapTracker()
    _tick(t, lap_number=1, lap_time=10.0)
    _tick(t, lap_number=2, lap_time=0.2, last_lap=90.0)   # completes lap 1
    _tick(t, lap_number=2, lap_time=60.0)
    # Line crossing ticks 2 → 3 AND flags finished on the same frame.
    events = _tick(t, lap_number=3, lap_time=0.1, last_lap=91.5,
                   finish_status="finished")
    laps = [e for e in events if isinstance(e, LapCompleted)]
    assert len(laps) == 1 and laps[0].num == 2   # normal completion only
    # The next finished frame carries the same last_lap — no phantom lap.
    again = _tick(t, lap_number=3, lap_time=5.0, last_lap=91.5,
                  finish_status="finished")
    assert [e for e in again if isinstance(e, LapCompleted)] == []


def test_finish_status_reset_allows_next_race_flush():
    # finish_status clearing (new race) re-arms the flush.
    t = LapTracker()
    _tick(t, lap_number=1, lap_time=10.0)
    _tick(t, lap_number=2, lap_time=0.2, last_lap=90.0)
    _tick(t, lap_number=2, lap_time=60.0)
    _tick(t, lap_number=2, lap_time=0.1, last_lap=91.5, finish_status="finished")
    # Back to racing clears the flag; a fresh finish flushes again.
    _tick(t, lap_number=3, lap_time=30.0, last_lap=91.5)
    _tick(t, lap_number=3, lap_time=60.0, last_lap=91.5)
    events = _tick(t, lap_number=3, lap_time=0.1, last_lap=88.0,
                   finish_status="finished")
    laps = [e for e in events if isinstance(e, LapCompleted)]
    assert len(laps) == 1 and laps[0].num == 3 and laps[0].time == pytest.approx(88.0)
