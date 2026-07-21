from core.session_history import SessionHistory
from core.telemetry_model import TelemetryData


def _tick(session, **kwargs):
    session.update(TelemetryData(**kwargs))


def test_laps_accumulate_newest_first():
    s = SessionHistory()
    _tick(s, lap_number=1, lap_time=5.0)
    _tick(s, lap_number=2, lap_time=0.2, last_lap=90.0)
    _tick(s, lap_number=3, lap_time=0.2, last_lap=88.0)

    assert [l["num"] for l in s.laps] == [2, 1]
    assert s.laps[0]["time"] == 88.0


def test_lap_records_tyre_compound():
    s = SessionHistory()
    _tick(s, lap_number=1, lap_time=5.0, tyre_compound="Soft")
    _tick(s, lap_number=2, lap_time=0.2, last_lap=90.0, tyre_compound="Soft")
    _tick(s, lap_number=3, lap_time=0.2, last_lap=88.0, tyre_compound="Medium")

    assert [l["compound"] for l in s.laps] == ["Medium", "Soft"]


def test_best_lap_excludes_invalid_laps():
    s = SessionHistory()
    _tick(s, lap_number=1, lap_time=5.0)
    _tick(s, lap_number=1, lap_time=10.0, lap_invalid=True)
    _tick(s, lap_number=2, lap_time=0.2, last_lap=85.0)   # invalid — not best
    assert s.best_lap == 0.0

    _tick(s, lap_number=3, lap_time=0.2, last_lap=90.0)   # valid
    assert s.best_lap == 90.0


def test_sf_rewind_removes_future_laps():
    s = SessionHistory()
    _tick(s, lap_number=1, lap_time=5.0)
    _tick(s, lap_number=2, lap_time=0.2, last_lap=90.0)
    _tick(s, lap_number=3, lap_time=0.2, last_lap=88.0)
    # Rewind back across S/F into lap 2 — lap 2's committed entry is now future
    _tick(s, lap_number=2, lap_time=80.0)

    assert [l["num"] for l in s.laps] == [1]


def test_participants_kept_from_last_nonempty_snapshot():
    s = SessionHistory()
    parts = [{"position": 1, "name": "VER", "best_lap": 88.0}]
    _tick(s, participants=parts)
    _tick(s)   # empty tick must not clear them
    assert s.participants == parts


def test_reset_clears_everything():
    s = SessionHistory()
    _tick(s, lap_number=1, lap_time=5.0, session_type="practice", car_class="gt3")
    _tick(s, lap_number=2, lap_time=0.2, last_lap=90.0)
    s.reset()

    assert s.laps == []
    assert s.best_lap == 0.0
    assert s.participants == []
    assert s.session_type == ""
