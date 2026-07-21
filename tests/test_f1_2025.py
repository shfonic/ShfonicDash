import struct

import pytest

from telemetry import f1_2025 as f1
from telemetry.f1_2025 import F12025Telemetry


# ── Pure helpers ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [(-1, "R"), (0, "N"), (1, "1"), (8, "8")])
def test_decode_gear(raw, expected):
    assert f1._decode_gear(raw) == expected


@pytest.mark.parametrize("ms, expected", [(0, 0.0), (1500, 1.5), (-100, 0.0)])
def test_ms_to_s(ms, expected):
    assert f1._ms_to_s(ms) == expected


# ── Packet builder ───────────────────────────────────────────────────────────

def _packet(total_len: int, fields: list[tuple[int, str, object]]) -> bytes:
    buf = bytearray(total_len)
    for offset, fmt, value in fields:
        if isinstance(value, tuple):
            struct.pack_into(fmt, buf, offset, *value)
        else:
            struct.pack_into(fmt, buf, offset, value)
    return bytes(buf)


# ── _parse_telemetry ─────────────────────────────────────────────────────────

def test_parse_telemetry_for_player_car():
    source = F12025Telemetry()
    car_start = f1._HEADER_SIZE  # idx == 0
    total_len = car_start + f1._TELEM_CAR_SIZE
    data = _packet(total_len, [
        (car_start + f1._T_SPEED, "<H", 250),
        (car_start + f1._T_THROTTLE, "<f", 1.5),     # clamps to 1.0
        (car_start + f1._T_STEER, "<f", -0.3),
        (car_start + f1._T_BRAKE, "<f", -0.5),       # clamps to 0.0
        (car_start + f1._T_GEAR, "<b", -1),          # reverse
        (car_start + f1._T_RPM, "<H", 11000),
        (car_start + f1._T_DRS, "<B", 1),
        (car_start + f1._T_TYRE_SURF_TEMP, "<4B", (50, 51, 52, 53)),   # ignored
        (car_start + f1._T_TYRE_INNER_TEMP, "<4B", (90, 91, 92, 93)),  # core temp — what the HUD shows
        (car_start + f1._T_TYRE_PRESSURE, "<4f", (22.5, 22.6, 22.7, 22.8)),
    ])

    source._parse_telemetry(data, 0)
    d = source._data

    assert d.speed == 250.0
    assert d.throttle == 1.0
    assert d.steer == pytest.approx(-0.3)
    assert d.brake == 0.0
    assert d.gear == "R"
    assert d.rpm == 11000
    assert d.drs_active is True
    assert d.tyre_temp == (90.0, 91.0, 92.0, 93.0)
    assert d.tyre_pressure == (22.5, 22.6, 22.7, 22.8)


def test_parse_motion_for_player_car():
    source = F12025Telemetry()
    source._packet_format = 2025           # 60-byte CarMotionData, yaw @48
    car_start = f1._HEADER_SIZE  # idx == 0
    total_len = car_start + f1._MOTION_CAR_SIZE
    data = _packet(total_len, [
        (car_start + f1._M_WORLD_POS_X, "<f", 123.5),
        (car_start + f1._M_WORLD_POS_Y, "<f", 4.25),    # elevation
        (car_start + f1._M_WORLD_POS_Z, "<f", -678.0),
        (car_start + f1._M_YAW, "<f", 1.5),
    ])

    source._parse_motion(data, 0)
    d = source._data

    assert d.pos_x == pytest.approx(123.5)
    assert d.pos_y == pytest.approx(4.25)
    assert d.pos_z == pytest.approx(-678.0)
    assert d.heading == pytest.approx(1.5)
    assert d.pos_valid is True


def test_parse_motion_reads_correct_car_slot():
    """Player at a non-zero grid index reads its own 60-byte slot, not car 0."""
    source = F12025Telemetry()
    source._packet_format = 2025
    idx = 5
    car_start = f1._HEADER_SIZE + idx * f1._MOTION_CAR_SIZE
    total_len = car_start + f1._MOTION_CAR_SIZE
    data = _packet(total_len, [
        (car_start + f1._M_WORLD_POS_X, "<f", 42.0),
        (car_start + f1._M_WORLD_POS_Z, "<f", 99.0),
    ])

    source._parse_motion(data, idx)
    d = source._data

    assert d.pos_x == pytest.approx(42.0)
    assert d.pos_z == pytest.approx(99.0)


def test_parse_motion_2026_layout_nonzero_slot():
    """F1 2026 shrank CarMotionData to 54 bytes and moved yaw to offset 42. A
    race-weekend player sits at a non-zero grid slot (here 21) — the regression
    that returned (0,0,0) because the old 60-byte stride overshot the slot."""
    source = F12025Telemetry()
    source._packet_format = 2026
    idx = 21
    car_start = f1._HEADER_SIZE + idx * f1._MOTION_CAR_SIZE_2026
    total_len = car_start + f1._MOTION_CAR_SIZE_2026
    data = _packet(total_len, [
        (car_start + f1._M_WORLD_POS_X, "<f", -315.8),
        (car_start + f1._M_WORLD_POS_Y, "<f", 4.4),
        (car_start + f1._M_WORLD_POS_Z, "<f", -500.4),
        (car_start + f1._M_YAW_2026, "<f", 1.44),
    ])

    source._parse_motion(data, idx)
    d = source._data

    assert d.pos_x == pytest.approx(-315.8)
    assert d.pos_y == pytest.approx(4.4)
    assert d.pos_z == pytest.approx(-500.4)
    assert d.heading == pytest.approx(1.44)
    assert d.pos_valid is True


def test_parse_motion_ignores_truncated_packet():
    source = F12025Telemetry()
    before = source.read()   # independent snapshot (parsers mutate in place)
    data = bytes(f1._HEADER_SIZE)  # too short for motion data

    source._parse_motion(data, 0)

    assert source.read() == before


def test_parse_motion_collects_opponents_2025():
    """All populated non-player slots land in opponents_pos; all-zero (empty)
    slots between them are skipped, and the player is excluded."""
    source = F12025Telemetry()
    source._packet_format = 2025
    stride = f1._MOTION_CAR_SIZE
    total_len = f1._HEADER_SIZE + 8 * stride
    slot = lambda i: f1._HEADER_SIZE + i * stride
    data = _packet(total_len, [
        (slot(0) + f1._M_WORLD_POS_X, "<f", 100.0),   # player
        (slot(0) + f1._M_WORLD_POS_Z, "<f", 200.0),
        (slot(0) + f1._M_YAW, "<f", 0.5),
        (slot(3) + f1._M_WORLD_POS_X, "<f", 110.0),
        (slot(3) + f1._M_WORLD_POS_Z, "<f", 195.0),
        (slot(3) + f1._M_YAW, "<f", 0.6),
        (slot(7) + f1._M_WORLD_POS_X, "<f", -50.0),
        (slot(7) + f1._M_WORLD_POS_Z, "<f", 400.0),
        (slot(7) + f1._M_YAW, "<f", -1.2),
    ])

    source._parse_motion(data, 0)
    d = source._data

    assert d.pos_x == pytest.approx(100.0)
    assert d.heading == pytest.approx(0.5)
    assert [o["idx"] for o in d.opponents_pos] == [3, 7]
    assert d.opponents_pos[0]["x"] == pytest.approx(110.0)
    assert d.opponents_pos[0]["z"] == pytest.approx(195.0)
    assert d.opponents_pos[0]["yaw"] == pytest.approx(0.6)
    assert d.opponents_pos[1]["x"] == pytest.approx(-50.0)
    assert d.opponents_pos[1]["yaw"] == pytest.approx(-1.2)


def test_parse_motion_collects_opponents_2026():
    """The 2026 layout (54-byte stride, yaw @42) flows through the same
    all-cars loop — an opponent in the last slot catches stride bugs."""
    source = F12025Telemetry()
    source._packet_format = 2026
    stride = f1._MOTION_CAR_SIZE_2026
    total_len = f1._HEADER_SIZE + f1._MOTION_NUM_CARS * stride
    slot = lambda i: f1._HEADER_SIZE + i * stride
    data = _packet(total_len, [
        (slot(4) + f1._M_WORLD_POS_X, "<f", 10.0),    # player at idx 4
        (slot(4) + f1._M_WORLD_POS_Z, "<f", 20.0),
        (slot(4) + f1._M_YAW_2026, "<f", 1.0),
        (slot(21) + f1._M_WORLD_POS_X, "<f", 15.0),
        (slot(21) + f1._M_WORLD_POS_Z, "<f", 25.0),
        (slot(21) + f1._M_YAW_2026, "<f", 1.1),
    ])

    source._parse_motion(data, 4)
    d = source._data

    assert d.pos_x == pytest.approx(10.0)
    assert d.heading == pytest.approx(1.0)
    assert len(d.opponents_pos) == 1
    opp = d.opponents_pos[0]
    assert opp["idx"] == 21
    assert opp["x"] == pytest.approx(15.0)
    assert opp["z"] == pytest.approx(25.0)
    assert opp["yaw"] == pytest.approx(1.1)


def test_parse_motion_clears_stale_opponents():
    """A packet with only the player populated replaces the previous
    opponents list with an empty one — no ghost cars."""
    source = F12025Telemetry()
    source._packet_format = 2025
    source._data.opponents_pos = [{"idx": 9, "x": 1.0, "z": 2.0, "yaw": 0.0}]
    car_start = f1._HEADER_SIZE
    data = _packet(car_start + f1._MOTION_CAR_SIZE, [
        (car_start + f1._M_WORLD_POS_X, "<f", 5.0),
    ])

    source._parse_motion(data, 0)

    assert source._data.opponents_pos == []


def test_parse_telemetry_ignores_truncated_packet():
    source = F12025Telemetry()
    before = source.read()   # independent snapshot (parsers mutate in place)
    data = bytes(f1._HEADER_SIZE)  # too short for car data

    source._parse_telemetry(data, 0)

    assert source.read() == before


# ── _parse_lap ───────────────────────────────────────────────────────────────

def _lap_packet(lap_num, curr_ms=0, last_ms=0, s1_ms=0, s2_ms=0, pos=0, sector=0,
                lap_dist=0.0, warnings=0, result_status=2):
    car_start = f1._HEADER_SIZE  # idx == 0
    total_len = car_start + f1._LAP_CAR_SIZE
    return _packet(total_len, [
        (car_start + f1._L_LAST_LAP_MS, "<I", last_ms),
        (car_start + f1._L_CURR_LAP_MS, "<I", curr_ms),
        (car_start + f1._L_S1_MS, "<H", s1_ms),
        (car_start + f1._L_S2_MS, "<H", s2_ms),
        (car_start + f1._L_LAP_DISTANCE, "<f", lap_dist),
        (car_start + f1._L_CAR_POS, "<B", pos),
        (car_start + f1._L_LAP_NUM, "<B", lap_num),
        (car_start + f1._L_SECTOR, "<B", sector),
        (car_start + f1._L_CORNER_CUT_WARN, "<B", warnings),
        (car_start + f1._L_RESULT_STATUS, "<B", result_status),
    ])


def test_parse_lap_for_player_car():
    source = F12025Telemetry()
    data = _lap_packet(lap_num=5, curr_ms=45_000, last_ms=80_000,
                       s1_ms=28_500, s2_ms=29_000, pos=3, sector=2,
                       lap_dist=2350.5, warnings=2)

    source._parse_lap(data, 0)
    d = source._data

    assert d.last_lap == pytest.approx(80.0)
    assert d.lap_time == pytest.approx(45.0)
    assert d.position == 3
    assert d.lap_number == 5
    assert d.sector == 2
    assert d.lap_distance == pytest.approx(2350.5)
    assert d.corner_cut_warnings == 2
    assert d.sector1_time == pytest.approx(28.5)
    assert d.sector2_time == pytest.approx(57.5)   # cumulative S1 + S2
    # First packet seen mid-session: lastLapTime belongs to a lap we didn't
    # observe, so it must NOT become the best lap.
    assert d.best_lap == 0.0


def test_parse_lap_completion_sets_best_and_delta():
    source = F12025Telemetry()
    source._parse_lap(_lap_packet(lap_num=5, curr_ms=45_000), 0)
    # Lap 5 → 6 completes lap 5 in 80 s
    source._parse_lap(_lap_packet(lap_num=6, curr_ms=200, last_ms=80_000), 0)
    d = source._data

    assert d.last_lap == pytest.approx(80.0)
    assert d.best_lap == pytest.approx(80.0)
    assert d.delta == 0.0   # no previous best to compare against

    # Lap 6 → 7 completes lap 6 in 78 s: new best, delta pinned to last − previous best
    source._parse_lap(_lap_packet(lap_num=7, curr_ms=200, last_ms=78_000), 0)
    d = source._data
    assert d.best_lap == pytest.approx(78.0)
    assert d.delta == pytest.approx(-2.0)


def test_parse_lap_best_lap_only_improves():
    source = F12025Telemetry()
    source._parse_lap(_lap_packet(lap_num=1, curr_ms=1_000), 0)

    source._parse_lap(_lap_packet(lap_num=2, curr_ms=200, last_ms=80_000), 0)
    assert source._data.best_lap == pytest.approx(80.0)

    source._parse_lap(_lap_packet(lap_num=3, curr_ms=200, last_ms=70_000), 0)
    assert source._data.best_lap == pytest.approx(70.0)

    source._parse_lap(_lap_packet(lap_num=4, curr_ms=200, last_ms=90_000), 0)
    assert source._data.best_lap == pytest.approx(70.0)  # slower lap doesn't overwrite


def test_leaderboard_best_survives_garage_return():
    """F1 25 rewinds the player's lap counter on a garage return between runs,
    then re-advances it while the car sits in the garage with the in-lap time
    still in lastLapTimeMs. The leaderboard best must survive the backwards
    jump and the stale time must not be re-recorded as a fresh lap."""
    source = F12025Telemetry()

    def leaderboard_best():
        parts = source._data.participants
        return parts[0]["best_lap"] if parts else 0.0

    # Out lap, then flying lap completes in 1:07.600
    source._parse_lap(_lap_packet(lap_num=1, curr_ms=1_000, pos=5), 0)
    source._parse_lap(_lap_packet(lap_num=2, curr_ms=200, last_ms=67_600, pos=5), 0)
    assert leaderboard_best() == pytest.approx(67.6)

    # In-lap completes in 1:17.994 — slower, so best is unchanged
    source._parse_lap(_lap_packet(lap_num=3, curr_ms=200, last_ms=77_994, pos=5), 0)
    assert leaderboard_best() == pytest.approx(67.6)

    # Garage return: lap counter rewinds — best must not be discarded
    source._parse_lap(_lap_packet(lap_num=1, curr_ms=0, last_ms=77_994, pos=5), 0)
    assert leaderboard_best() == pytest.approx(67.6)

    # Counter re-advances in the garage with the stale in-lap time still
    # in lastLapTimeMs — it must not be recorded again
    source._parse_lap(_lap_packet(lap_num=2, curr_ms=100, last_ms=77_994, pos=5), 0)
    source._parse_lap(_lap_packet(lap_num=3, curr_ms=100, last_ms=77_994, pos=5), 0)
    assert leaderboard_best() == pytest.approx(67.6)


# ── _parse_status ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("packet_format, car_size, ers_deployed_offset", [
    (2025, f1._STS_CAR_SIZE_2025, f1._S_ERS_DEPLOYED_2025),
    (2026, f1._STS_CAR_SIZE_2026, f1._S_ERS_DEPLOYED_2026),
])
def test_parse_status_for_player_car(packet_format, car_size, ers_deployed_offset):
    source = F12025Telemetry()
    source._packet_format = packet_format
    car_start = f1._HEADER_SIZE  # idx == 0
    # Real F1 packets are much larger than car_size (header + all cars);
    # pad by 1 byte so the highest field offset (ers_deployed_offset, a float) fits.
    total_len = car_start + car_size + 1
    data = _packet(total_len, [
        (car_start + f1._S_TC, "<B", 2),
        (car_start + f1._S_ABS, "<B", 1),
        (car_start + f1._S_FUEL_TANK, "<f", 35.5),
        (car_start + f1._S_FUEL_CAP, "<f", 110.0),
        (car_start + f1._S_FUEL_LAPS, "<f", 12.3),
        (car_start + f1._S_MAX_RPM, "<H", 12000),
        (car_start + f1._S_DRS_ALLOWED, "<B", 1),
        (car_start + f1._S_VISUAL_TYRE, "<B", 16),  # Soft
        (car_start + f1._S_ERS_ENERGY, "<f", 2_000_000.0),  # 50% of 4MJ
        (car_start + f1._S_ERS_MODE, "<B", 2),
        (car_start + f1._S_ERS_HARV_MGUK, "<f", 0.5),
        (car_start + ers_deployed_offset, "<f", 0.3),
        (car_start + f1._S_FIA_FLAGS, "<b", 3),  # yellow
    ])

    source._parse_status(data, 0)
    d = source._data

    assert d.tc_level == 2
    assert d.abs_level == 1
    assert d.fuel_remaining == pytest.approx(35.5)
    assert d.fuel_capacity == pytest.approx(110.0)
    assert d.fuel_laps_remaining == pytest.approx(12.3)
    assert d.max_rpm == 12000
    assert d.drs_available is True
    assert d.tyre_compound == "Soft"
    assert d.ers_stored_energy == pytest.approx(0.5, abs=1e-3)
    assert d.ers_deploy_mode == 2
    assert d.ers_harvested_lap == pytest.approx(0.5)
    assert d.ers_deployed_lap == pytest.approx(0.3)
    assert d.flag == "yellow"


def test_parse_status_clamps_negative_fuel_and_keeps_max_rpm_when_zero():
    source = F12025Telemetry()
    car_start = f1._HEADER_SIZE
    total_len = car_start + f1._STS_CAR_SIZE_2026 + 1
    data = _packet(total_len, [
        (car_start + f1._S_FUEL_TANK, "<f", -5.0),
        (car_start + f1._S_FUEL_CAP, "<f", 0.0),
        (car_start + f1._S_MAX_RPM, "<H", 0),
    ])

    source._parse_status(data, 0)
    d = source._data

    assert d.fuel_remaining == 0.0
    assert d.fuel_capacity == 1.0
    assert d.max_rpm == 8000  # default preserved when reported max is 0


# ── _parse_telemetry2 (F1 2026 DLC) ──────────────────────────────────────────

def test_parse_telemetry2_straight_line_mode_and_2026_regs():
    source = F12025Telemetry()
    car_start = f1._HEADER_SIZE
    total_len = car_start + f1._TELEM2_CAR_SIZE
    data = _packet(total_len, [
        (car_start + f1._T2_AERO_MODE, "<B", 1),   # straight
        (car_start + f1._T2_AERO_AVAIL, "<B", 1),
        (car_start + f1._T2_OVT_AVAIL, "<B", 1),
        (car_start + f1._T2_OVT_ACTIVE, "<B", 1),
        (car_start + f1._T2_2026_REGS, "<B", 1),
    ])

    source._parse_telemetry2(data, 0)
    d = source._data

    assert d.active_aero_mode == "straight"
    assert d.active_aero_available is True
    assert d.boost_active is True
    assert d.car_class == "formula1_2026"


def test_parse_telemetry2_corner_mode_and_pre_2026_car():
    source = F12025Telemetry()
    car_start = f1._HEADER_SIZE
    total_len = car_start + f1._TELEM2_CAR_SIZE
    data = _packet(total_len, [
        (car_start + f1._T2_AERO_MODE, "<B", 0),  # corner
        (car_start + f1._T2_2026_REGS, "<B", 0),
    ])

    source._parse_telemetry2(data, 0)
    d = source._data

    assert d.active_aero_mode == "corner"
    assert d.car_class == "formula1"  # unchanged


# ── _parse_session ───────────────────────────────────────────────────────────

_SESSION_PKT_LEN = f1._HEADER_SIZE + f1._SES_RACING_LINE + 1


def test_parse_session_known_values():
    source = F12025Telemetry()
    data = _packet(_SESSION_PKT_LEN, [
        (f1._HEADER_SIZE + f1._SES_SESSION_TYPE, "<B", 15),  # race (F1 23+ enum)
        (f1._HEADER_SIZE + f1._SES_FORMULA, "<B", 6),        # f2
        (f1._HEADER_SIZE + f1._SES_TOTAL_LAPS, "<B", 25),
        (f1._HEADER_SIZE + f1._SES_TRACK_ID, "<b", 11),      # Monza
        (f1._HEADER_SIZE + f1._SES_SAFETY_CAR, "<B", 1),     # SC deployed
    ])

    source._parse_session(data)
    d = source._data

    assert d.session_type == "race"
    assert d.session_subtype == ""
    assert d.session_type_raw == 15
    assert d.car_class == "f2"
    assert d.total_laps == 25
    assert d.track == "Monza"
    assert d.game == "f1_25"
    assert d.safety_car == "sc"


def test_parse_session_assist_settings():
    source = F12025Telemetry()
    data = _packet(_SESSION_PKT_LEN, [
        (f1._HEADER_SIZE + f1._SES_STEERING_ASSIST, "<B", 1),
        (f1._HEADER_SIZE + f1._SES_BRAKING_ASSIST, "<B", 1),
        (f1._HEADER_SIZE + f1._SES_GEARBOX_ASSIST, "<B", 2),      # auto
        (f1._HEADER_SIZE + f1._SES_PIT_ASSIST, "<B", 1),
        (f1._HEADER_SIZE + f1._SES_PIT_RELEASE_ASSIST, "<B", 1),
        (f1._HEADER_SIZE + f1._SES_ERS_ASSIST, "<B", 1),
        (f1._HEADER_SIZE + f1._SES_DRS_ASSIST, "<B", 1),
        (f1._HEADER_SIZE + f1._SES_RACING_LINE, "<B", 2),         # full
    ])

    source._parse_session(data)
    d = source._data

    assert d.steering_assist == 1
    assert d.braking_assist == 1
    assert d.gearbox_assist == 2
    assert d.pit_assist == 1
    assert d.pit_release_assist == 1
    assert d.ers_assist == 1
    assert d.drs_assist == 1
    assert d.racing_line_assist == 2


def test_parse_session_assist_settings_default_off():
    source = F12025Telemetry()
    data = _packet(_SESSION_PKT_LEN, [])   # everything zero-filled

    source._parse_session(data)
    d = source._data

    assert d.steering_assist == 0
    assert d.braking_assist == 0
    assert d.gearbox_assist == 0
    assert d.pit_assist == 0
    assert d.pit_release_assist == 0
    assert d.ers_assist == 0
    assert d.drs_assist == 0
    assert d.racing_line_assist == 0


def test_parse_session_weather_and_temps():
    source = F12025Telemetry()
    data = _packet(_SESSION_PKT_LEN, [
        (f1._HEADER_SIZE + f1._SES_WEATHER, "<B", 3),      # light rain
        (f1._HEADER_SIZE + f1._SES_TRACK_TEMP, "<b", 41),
        (f1._HEADER_SIZE + f1._SES_AIR_TEMP, "<b", -2),    # int8 is signed
    ])

    source._parse_session(data)
    d = source._data

    assert d.weather == "light_rain"
    assert d.track_temp == 41.0
    assert d.air_temp == -2.0


def test_parse_session_unknown_weather_is_empty():
    source = F12025Telemetry()
    data = _packet(_SESSION_PKT_LEN, [
        (f1._HEADER_SIZE + f1._SES_WEATHER, "<B", 255),
    ])

    source._parse_session(data)

    assert source._data.weather == ""


def test_parse_session_sprint_shootout_is_qualifying():
    # F1 23+ enum: ids 10–14 are Sprint Shootout variants, not races.
    # Regression: these were mapped to "race", labelling sprint quali sessions
    # as races (observed 2026-07-05).
    for session_int in (10, 11, 12, 13, 14):
        source = F12025Telemetry()
        data = _packet(_SESSION_PKT_LEN, [
            (f1._HEADER_SIZE + f1._SES_SESSION_TYPE, "<B", session_int),
        ])

        source._parse_session(data)
        d = source._data

        assert d.session_type == "qualifying"
        assert d.session_subtype == "sprint_qualifying"
        assert d.session_type_raw == session_int


def test_parse_session_unknown_values_fall_back_to_defaults():
    source = F12025Telemetry()
    data = _packet(_SESSION_PKT_LEN, [
        (f1._HEADER_SIZE + f1._SES_SESSION_TYPE, "<B", 255),  # unmapped session type
        (f1._HEADER_SIZE + f1._SES_FORMULA, "<B", 255),       # unmapped formula class
        (f1._HEADER_SIZE + f1._SES_SAFETY_CAR, "<B", 255),    # unmapped safety car state
    ])

    source._parse_session(data)
    d = source._data

    assert d.session_type == "race"
    assert d.car_class == "formula1"
    assert d.safety_car == ""


def test_parse_session_ignores_too_short_packet():
    source = F12025Telemetry()
    before = source._data

    source._parse_session(bytes(f1._HEADER_SIZE))

    assert source._data == before


# ── _parse_participants: player team ─────────────────────────────────────────

def _participants_packet(team_id=8, name=b"PIASTRI", num_slots=22):
    # V1_22 layout: teamId at offset 3, name at offset 7 within each 60-byte car.
    body = bytearray(num_slots * f1._PART_CAR_SIZE_V1)
    body[3] = team_id
    body[7:7 + len(name)] = name
    return bytes(f1._HEADER_SIZE) + bytes([1]) + bytes(body)


def test_participants_maps_known_team():
    source = F12025Telemetry()
    source._player_idx = 0

    source._parse_participants(_participants_packet(team_id=8))

    assert source._data.car_name == "McLaren"
    assert source._data.team_id_raw == 8
    assert source._data.driver_name == "PIASTRI"


def test_participants_records_unmapped_team_id():
    # Ids outside _TEAM_ID_MAP: the raw id must still reach the snapshot
    # (and the CSV) so the map can be grown from real sessions.
    source = F12025Telemetry()
    source._player_idx = 0

    source._parse_participants(_participants_packet(team_id=250))

    assert source._data.car_name == ""
    assert source._data.team_id_raw == 250


def _participants_packet_v124(team_id=484, name=b"PIASTRI"):
    # V1_24 My Career layout: 24 slots, teamId uint16 LE at offset 5 (2026
    # Season Pack ids exceed one byte), name at offset 10.
    body = bytearray(24 * f1._PART_CAR_SIZE_V1)
    struct.pack_into("<H", body, 5, team_id)
    body[10:10 + len(name)] = name
    return bytes(f1._HEADER_SIZE) + bytes([20]) + bytes(body)


@pytest.mark.parametrize("team_id, expected", [
    (484, "McLaren"),    # F1 2026 grid
    (485, "Audi"),
    (486, "Cadillac"),
    (472, "Prema"),      # F2 2025
])
def test_participants_v124_reads_u16_team_id(team_id, expected):
    source = F12025Telemetry()
    source._player_idx = 0

    source._parse_participants(_participants_packet_v124(team_id=team_id))

    assert source._data.car_name == expected
    assert source._data.team_id_raw == team_id


# ── _on_packet dispatcher ────────────────────────────────────────────────────

def test_on_packet_dispatches_lap_data_for_player_car():
    source = F12025Telemetry()
    car_start = f1._HEADER_SIZE
    total_len = car_start + f1._LAP_CAR_SIZE
    data = _packet(total_len, [
        (6, "<B", f1._PKT_LAP),
        (f1._PLAYER_IDX_OFFSET, "<B", 0),
        (car_start + f1._L_LAP_NUM, "<B", 7),
    ])

    source._on_packet(data)

    assert source._data.lap_number == 7


def test_on_packet_ignores_packet_shorter_than_header():
    source = F12025Telemetry()
    before = source._data

    source._on_packet(bytes(f1._HEADER_SIZE - 1))

    assert source._data == before


def test_on_packet_does_not_raise_on_truncated_known_packet():
    source = F12025Telemetry()
    before = source._data
    data = _packet(f1._HEADER_SIZE, [
        (6, "<B", f1._PKT_TELEMETRY),
        (f1._PLAYER_IDX_OFFSET, "<B", 0),
    ])

    source._on_packet(data)  # should not raise despite missing car data

    assert source._data == before


# ── read() ───────────────────────────────────────────────────────────────────

def test_read_returns_independent_copy():
    source = F12025Telemetry()

    data1 = source.read()
    data1.rpm = 9999

    data2 = source.read()
    assert data2.rpm == 0


# ── _parse_final_classification ──────────────────────────────────────────────

def _final_packet(car_size, entries, slots=22):
    """Build a packet-8 Final Classification packet.

    entries: list of dicts with position, status, best_ms, total_s, pen_s.
    """
    if car_size == f1._FINAL_CAR_SIZE_V46:
        best_off, time_off, pen_off = 7, 11, 19
    else:
        best_off, time_off, pen_off = 6, 10, 18
    total_len = f1._HEADER_SIZE + 1 + slots * car_size
    fields = [(f1._HEADER_SIZE, "<B", len(entries))]
    for i, e in enumerate(entries):
        cs = f1._HEADER_SIZE + 1 + i * car_size
        fields += [
            (cs, "<B", e["position"]),
            (cs + 5, "<B", e["status"]),
            (cs + best_off, "<I", e["best_ms"]),
            (cs + time_off, "<d", e["total_s"]),
            (cs + pen_off, "<B", e.get("pen_s", 0)),
        ]
    return _packet(total_len, fields)


@pytest.mark.parametrize("car_size", [f1._FINAL_CAR_SIZE_V45, f1._FINAL_CAR_SIZE_V46])
def test_parse_final_classification_publishes_race_times(car_size):
    source = F12025Telemetry()
    data = _final_packet(car_size, [
        {"position": 2, "status": 3, "best_ms": 70_470, "total_s": 5401.234, "pen_s": 5},
        {"position": 1, "status": 3, "best_ms": 70_167, "total_s": 5399.9},
        {"position": 3, "status": 4, "best_ms": 71_000, "total_s": 0.0},   # DNF
    ])

    source._parse_final_classification(data)
    parts = source._data.participants

    assert [p["position"] for p in parts] == [1, 2, 3]
    assert parts[0]["race_time"] == pytest.approx(5399.9)
    assert parts[0]["best_lap"] == pytest.approx(70.167)
    # Classified time includes the 5 s penalty
    assert parts[1]["race_time"] == pytest.approx(5406.234)
    # DNF — no classified time
    assert parts[2]["race_time"] == 0.0
    assert source._data.classification_received is True


def test_parse_final_classification_overrides_live_positions():
    source = F12025Telemetry()
    # Live scan had the cars the other way around (e.g. photo finish)
    source._car_positions = {0: 1, 1: 2}
    source._car_names = {0: "PIA", 1: "NOR"}
    data = _final_packet(f1._FINAL_CAR_SIZE_V46, [
        {"position": 2, "status": 3, "best_ms": 70_470, "total_s": 5401.0},
        {"position": 1, "status": 3, "best_ms": 70_167, "total_s": 5400.9},
    ])

    source._parse_final_classification(data)
    parts = source._data.participants

    assert [(p["position"], p["name"]) for p in parts] == [(1, "NOR"), (2, "PIA")]


def test_parse_final_classification_ignores_unknown_struct_size():
    source = F12025Telemetry()
    # Body not divisible by 45 or 46
    data = _packet(f1._HEADER_SIZE + 1 + 22 * 44, [(f1._HEADER_SIZE, "<B", 22)])

    source._parse_final_classification(data)

    assert source._data.participants == []
    assert source._car_race_times == {}


def test_on_packet_dispatches_final_classification():
    source = F12025Telemetry()
    data = bytearray(_final_packet(f1._FINAL_CAR_SIZE_V46, [
        {"position": 1, "status": 3, "best_ms": 70_167, "total_s": 5399.9},
    ]))
    data[6] = f1._PKT_FINAL

    source._on_packet(bytes(data))

    assert source._data.participants[0]["race_time"] == pytest.approx(5399.9)


# ── finish status / results banner signals ───────────────────────────────────

def test_lap_packet_finish_status():
    source = F12025Telemetry()

    source._parse_lap(_lap_packet(lap_num=18, curr_ms=200, result_status=2), 0)
    assert source._data.finish_status == ""          # still racing

    source._parse_lap(_lap_packet(lap_num=18, curr_ms=300, result_status=3), 0)
    assert source._data.finish_status == "finished"

    source._parse_lap(_lap_packet(lap_num=18, curr_ms=400, result_status=7), 0)
    assert source._data.finish_status == "retired"


def test_session_uid_change_clears_finished_state():
    # Same-type restart (new sessionUID): a stale "results saved" state must
    # not carry into the new race.
    source = F12025Telemetry()
    source._parse_lap(_lap_packet(lap_num=18, curr_ms=200, result_status=3), 0)
    source._parse_final_classification(_final_packet(f1._FINAL_CAR_SIZE_V46, [
        {"position": 1, "status": 3, "best_ms": 70_167, "total_s": 5399.9},
    ]))
    assert source._data.classification_received is True

    pkt = bytearray(_lap_packet(lap_num=1, curr_ms=100))
    pkt[6] = f1._PKT_LAP
    struct.pack_into("<Q", pkt, 7, 0xDEADBEEF)   # new m_sessionUID
    source._on_packet(bytes(pkt))

    assert source._data.classification_received is False
    assert source._data.finish_status == ""


# ── _parse_event (incident events) ───────────────────────────────────────────

def _event_packet(code, payload):
    data = bytearray(f1._EVT_PAYLOAD_OFFSET + max(len(payload), 8))
    data[6] = f1._PKT_EVENT
    data[f1._EVT_CODE_OFFSET:f1._EVT_CODE_OFFSET + 4] = code.encode()
    for i, b in enumerate(payload):
        data[f1._EVT_PAYLOAD_OFFSET + i] = b
    return bytes(data)


def _source_mid_lap(player_idx=0):
    source = F12025Telemetry()
    source._player_idx = player_idx
    source._car_names = {0: "PIASTRI", 1: "VERSTAPPEN", 2: "NORRIS"}
    source._parse_lap(_lap_packet(lap_num=7, curr_ms=31_200, lap_dist=1842.7), 0)
    return source


def test_event_collision_involving_player():
    source = _source_mid_lap()
    source._parse_event(_event_packet("COLL", [1, 0]))   # VER hits player

    events = source.read().events
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "collision"
    assert ev["detail"] == "VERSTAPPEN"
    assert ev["lap_num"] == 7
    assert ev["lap_time"] == pytest.approx(31.2)
    assert ev["distance"] == pytest.approx(1842.7)
    # Drained — next snapshot is clean
    assert source.read().events == []


def test_event_collision_between_ai_cars_ignored():
    source = _source_mid_lap()
    source._parse_event(_event_packet("COLL", [1, 2]))   # VER vs NOR
    assert source.read().events == []


def test_event_overtake_both_directions():
    source = _source_mid_lap()
    source._parse_event(_event_packet("OVTK", [0, 2]))   # player passes NOR
    source._parse_event(_event_packet("OVTK", [1, 0]))   # VER passes player
    source._parse_event(_event_packet("OVTK", [1, 2]))   # AI vs AI — ignored

    events = source.read().events
    assert [(e["type"], e["detail"]) for e in events] == [
        ("overtake", "NORRIS"), ("overtaken", "VERSTAPPEN")]


def test_event_penalty_for_player():
    source = _source_mid_lap()
    # time penalty (4), corner cutting gained time (7), player, no other car
    source._parse_event(_event_packet("PENA", [4, 7, 0, 255, 5, 7, 0]))
    # warning (5), big collision (3), player, other car VER
    source._parse_event(_event_packet("PENA", [5, 3, 0, 1, 0, 7, 0]))
    # penalty for another car — ignored
    source._parse_event(_event_packet("PENA", [4, 7, 2, 255, 5, 7, 0]))

    events = source.read().events
    assert [(e["type"], e["detail"]) for e in events] == [
        ("penalty", "time_penalty:corner_cutting_gained_time"),
        ("penalty", "warning:big_collision:VERSTAPPEN"),
    ]


def test_event_unknown_code_and_short_packet_ignored():
    source = _source_mid_lap()
    source._parse_event(_event_packet("CHQF", []))       # unhandled code
    source._parse_event(bytes(f1._HEADER_SIZE))          # too short
    assert source.read().events == []
