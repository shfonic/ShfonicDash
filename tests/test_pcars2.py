import re
import struct

import pytest

from telemetry import pcars2
from telemetry.pcars2 import PCARS2Telemetry, _F, _PKT, _normalize


# ── _normalize ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    (0.0, 0.0),
    (0.5, 0.5),
    (1.0, 1.0),
    (255.0, 1.0),     # 0-255 range, fully pressed
    (128.0, pytest.approx(128 / 255)),
    (300.0, 1.0),     # out of range, clamps high
    (-10.0, 0.0),     # out of range, clamps low
])
def test_normalize(raw, expected):
    assert _normalize(raw) == expected


# ── Packet builders ─────────────────────────────────────────────────────────

_FMT_ITEM_RE = re.compile(r"(\d*)([a-zA-Z])")


def _zero_items(fmt: str) -> list:
    items = []
    for count_str, code in _FMT_ITEM_RE.findall(fmt.lstrip("<>!=@")):
        count = int(count_str) if count_str else 1
        if code == "x":
            continue
        if code == "s":
            items.append(b"\x00" * count)
        elif code == "c":
            items.extend([b"\x00"] * count)
        elif code in "fd":
            items.extend([0.0] * count)
        else:
            items.extend([0] * count)
    return items


def _header(pkt_type: int) -> bytes:
    """12-byte shared packet header; mPacketType lives at offset 10."""
    header = bytearray(12)
    header[10] = pkt_type
    return bytes(header)


def build_phys_packet(**field_values) -> bytes:
    """Build an eCarPhysics packet, overriding named _F fields."""
    items = _zero_items(pcars2._PHYS_FMT)
    items[int(_F.mPacketType)] = int(_PKT.eCarPhysics)
    for name, value in field_values.items():
        items[int(_F[name])] = value
    return struct.pack(pcars2._PHYS_FMT, *items)


def build_timing_packet(time_remaining=0.0, gap_ahead=0.0, gap_behind=0.0,
                        num_participants=0, participant: dict | None = None) -> bytes:
    """eTimings packet: 33-byte header, optional participant slot 0, 6-byte tail."""
    pkt = struct.pack(pcars2._TIMINGS_HEADER_FMT,
                      _header(int(_PKT.eTimings)), num_participants, 0,
                      time_remaining, gap_ahead, gap_behind, 0.0)
    if participant is not None:
        p = participant
        blob = struct.pack(pcars2._PART_FMT,
                           0, 0, 0, 0, 0, 0,                  # world pos + orientation
                           p.get("lap_distance", 0),
                           p.get("race_pos_byte", 0),         # bit7 active, bits0-6 position
                           p.get("sector_byte", 0),
                           0, 0,                              # highestFlag, pitModeSchedule
                           0,                                 # carIndex
                           p.get("race_state_byte", 0),       # bit3 = lap invalid
                           p.get("current_lap", 0),
                           p.get("current_time", 0.0),
                           0.0,                               # currentSectorTime
                           0)                                 # mpParticipantIndex
        pkt += blob + struct.pack("<HI", 0, 0)   # tail: local idx 0 + tick count
    return pkt


def build_racedata_packet(best_lap=0.0, best_s1=0.0, best_s2=0.0, best_s3=0.0,
                          total_laps=0) -> bytes:
    items = _zero_items(pcars2._RACEDATA_FMT)
    items[0] = _header(int(_PKT.eRaceDefinition))
    items[2] = best_lap
    items[3] = best_s1
    items[4] = best_s2
    items[5] = best_s3
    items[14] = total_laps
    return struct.pack(pcars2._RACEDATA_FMT, *items)


def build_gamestate_packet(session_bits=5, pause_bits=0) -> bytes:
    state_byte = (session_bits << 3) | pause_bits
    return struct.pack(pcars2._GAMESTATE_FMT, _header(int(_PKT.eGameState)), 0, state_byte)


def build_gamestate_weather_packet(session_bits=5, pause_bits=0, ambient=18,
                                   track=27, rain=0, snow=0) -> bytes:
    state_byte = (session_bits << 3) | pause_bits
    return struct.pack(pcars2._GAMESTATE_WEATHER_FMT, _header(int(_PKT.eGameState)),
                       0, state_byte, ambient, track, rain, snow, 0, 0, 0)


def _build(source, phys=None, timing=None, racedata=None, gamestate=None, type8=None):
    return source._build(phys, timing, racedata, gamestate, type8 or {})


# ── _build (no packets) ──────────────────────────────────────────────────────

def test_build_with_no_physics_packet_returns_defaults():
    source = PCARS2Telemetry()

    data = _build(source)

    from core.telemetry_model import TelemetryData
    assert data == TelemetryData()


# ── _build: car physics ──────────────────────────────────────────────────────

@pytest.mark.parametrize("gear_idx, expected", [
    (0, "N"),
    (1, "1"),
    (6, "6"),
    (15, "R"),
])
def test_build_decodes_gear(gear_idx, expected):
    source = PCARS2Telemetry()
    phys = build_phys_packet(sGearNumGears=gear_idx)

    data = _build(source, phys)

    assert data.gear == expected


def test_build_converts_speed_mps_to_kmh():
    source = PCARS2Telemetry()
    phys = build_phys_packet(sSpeed=10.0)  # m/s

    data = _build(source, phys)

    assert data.speed == pytest.approx(36.0)


def test_build_passes_through_rpm_and_max_rpm():
    source = PCARS2Telemetry()
    phys = build_phys_packet(sRpm=6500, sMaxRpm=8000)

    data = _build(source, phys)

    assert data.rpm == 6500
    assert data.max_rpm == 8000


def test_build_falls_back_to_default_max_rpm_when_zero():
    source = PCARS2Telemetry()
    phys = build_phys_packet(sMaxRpm=0)

    data = _build(source, phys)

    assert data.max_rpm == 8000


def test_build_normalizes_throttle_and_brake_from_uint8():
    source = PCARS2Telemetry()
    phys = build_phys_packet(sThrottle=255, sBrake=128)

    data = _build(source, phys)

    assert data.throttle == 1.0
    assert data.brake == pytest.approx(128 / 255, abs=1e-3)


def test_build_normalizes_steering_to_unit_range():
    source = PCARS2Telemetry()
    phys = build_phys_packet(sSteering=127)

    data = _build(source, phys)

    assert data.steer == pytest.approx(1.0, abs=1e-3)


def test_build_computes_fuel_remaining_from_level_fraction():
    source = PCARS2Telemetry()
    phys = build_phys_packet(sFuelLevel=0.5, sFuelCapacity=60)

    data = _build(source, phys)

    assert data.fuel_capacity == 60
    assert data.fuel_remaining == pytest.approx(30.0)


def test_build_uses_default_fuel_capacity_when_unset():
    source = PCARS2Telemetry()
    phys = build_phys_packet(sFuelLevel=1.0, sFuelCapacity=0)

    data = _build(source, phys)

    assert data.fuel_capacity == 45.0
    assert data.fuel_remaining == pytest.approx(45.0)


def test_build_extracts_tyre_data():
    source = PCARS2Telemetry()
    phys = build_phys_packet(
        # tread temps are integer Kelvin in the wire format: 358 K = 84.85 °C → 84.9
        sTyreTreadTemp1=358, sTyreTreadTemp2=359, sTyreTreadTemp3=360, sTyreTreadTemp4=361,
        sTyreWear1=255, sTyreWear2=0, sTyreWear3=128, sTyreWear4=64,
        sAirPressure1=200, sAirPressure2=205, sAirPressure3=210, sAirPressure4=215,
    )

    data = _build(source, phys)

    assert data.tyre_temp == (84.9, 85.9, 86.9, 87.9)
    assert data.tyre_wear[0] == pytest.approx(1.0)
    assert data.tyre_wear[1] == pytest.approx(0.0)
    assert data.tyre_wear[2] == pytest.approx(128 / 255, abs=1e-3)
    # uint16 PSI x10 -> /10
    assert data.tyre_pressure == (20.0, 20.5, 21.0, 21.5)


def test_build_sets_game_and_default_car_class():
    source = PCARS2Telemetry()
    phys = build_phys_packet()

    data = _build(source, phys)

    assert data.game == "pcars2"
    assert data.car_class == "pcars2"
    assert data.session_type == "race"


# ── _build: timing & race definition ────────────────────────────────────────

def test_build_includes_timing_header_data():
    source = PCARS2Telemetry()
    phys = build_phys_packet()
    timing = build_timing_packet(time_remaining=120.5, gap_ahead=1.234, gap_behind=2.5)

    data = _build(source, phys, timing)

    assert data.session_time_remaining == pytest.approx(120.5)
    assert data.gap_ahead == pytest.approx(1.234)
    assert data.gap_behind == pytest.approx(2.5)


def test_build_clamps_negative_gaps_to_zero():
    source = PCARS2Telemetry()
    phys = build_phys_packet()
    timing = build_timing_packet(gap_ahead=-5.0, gap_behind=-1.0)

    data = _build(source, phys, timing)

    assert data.gap_ahead == 0.0
    assert data.gap_behind == 0.0


def test_build_reads_player_participant_slot():
    source = PCARS2Telemetry()
    phys = build_phys_packet()
    timing = build_timing_packet(num_participants=10, participant={
        "race_pos_byte": 0x80 | 3,     # active, P3
        "sector_byte": 1,              # S2
        "race_state_byte": 0x08,       # lap invalid
        "current_lap": 4,
        "current_time": 45.5,
    })

    data = _build(source, phys, timing)

    assert data.position == 3
    assert data.total_cars == 10
    assert data.sector == 1
    assert data.lap_invalid is True
    assert data.lap_number == 4
    assert data.lap_time == pytest.approx(45.5)


def test_build_tracks_last_lap_across_lap_transition():
    source = PCARS2Telemetry()
    phys = build_phys_packet()

    def timing_for(lap, t):
        return build_timing_packet(num_participants=5, participant={
            "race_pos_byte": 0x80 | 1, "current_lap": lap, "current_time": t,
        })

    _build(source, phys, timing_for(1, 30.0))
    _build(source, phys, timing_for(1, 91.2))
    data = _build(source, phys, timing_for(2, 0.4))   # crossed the line

    assert data.last_lap == pytest.approx(91.2)
    assert data.best_lap == pytest.approx(91.2)   # locally-tracked session best


def test_build_includes_race_definition_data():
    source = PCARS2Telemetry()
    phys = build_phys_packet()
    racedata = build_racedata_packet(best_lap=90.123, best_s1=30.0, best_s2=30.5,
                                     best_s3=29.6, total_laps=10)

    data = _build(source, phys, racedata=racedata)

    assert data.best_lap == pytest.approx(90.123)
    assert data.best_sector1 == pytest.approx(30.0)
    assert data.best_sector2 == pytest.approx(30.5)
    assert data.best_sector3 == pytest.approx(29.6)
    assert data.total_laps == 10


# ── _build: game state ───────────────────────────────────────────────────────

@pytest.mark.parametrize("session_bits, expected", [
    (1, "practice"),
    (3, "qualifying"),
    (5, "race"),
    (6, "hotlap"),
    (0, "race"),   # unmapped falls back
])
def test_build_maps_session_type(session_bits, expected):
    source = PCARS2Telemetry()
    data = _build(source, build_phys_packet(),
                  gamestate=build_gamestate_packet(session_bits=session_bits))
    assert data.session_type == expected


def test_build_detects_game_paused():
    source = PCARS2Telemetry()
    data = _build(source, build_phys_packet(),
                  gamestate=build_gamestate_packet(session_bits=5, pause_bits=3))
    assert data.game_paused is True


@pytest.mark.parametrize("rain, snow, expected", [
    (0,   0, "clear"),
    (40,  0, "light_rain"),
    (200, 0, "heavy_rain"),
    (0,  60, "snow"),
])
def test_build_maps_weather(rain, snow, expected):
    source = PCARS2Telemetry()
    data = _build(source, build_phys_packet(),
                  gamestate=build_gamestate_weather_packet(rain=rain, snow=snow))
    assert data.weather == expected


def test_build_reads_temperatures():
    source = PCARS2Telemetry()
    data = _build(source, build_phys_packet(),
                  gamestate=build_gamestate_weather_packet(ambient=-3, track=12))
    assert data.air_temp == -3.0
    assert data.track_temp == 12.0


def test_build_short_gamestate_leaves_weather_unset():
    # Pre-weather packet (session/pause byte only) must not invent conditions.
    source = PCARS2Telemetry()
    data = _build(source, build_phys_packet(),
                  gamestate=build_gamestate_packet())
    assert data.weather == ""
    assert data.air_temp == 0.0
    assert data.track_temp == 0.0


# ── _on_packet dispatcher ────────────────────────────────────────────────────

def test_on_packet_routes_by_packet_type():
    source = PCARS2Telemetry()
    phys = build_phys_packet(sRpm=1234)
    timing = build_timing_packet(time_remaining=99.0)
    racedata = build_racedata_packet(best_lap=88.0)

    source._on_packet(phys)
    source._on_packet(timing)
    source._on_packet(racedata)

    assert source._phys_raw == phys
    assert source._timing_raw == timing
    assert source._racedata_raw == racedata

    data = source.read()
    assert data.rpm == 1234
    assert data.session_time_remaining == pytest.approx(99.0)
    assert data.best_lap == pytest.approx(88.0)


def test_on_packet_ignores_short_packets():
    source = PCARS2Telemetry()

    source._on_packet(b"\x00" * 11)

    assert source._phys_raw is None
    assert source._timing_raw is None
    assert source._racedata_raw is None


# ── Stream-silence pause detection (v0.1.141) ─────────────────────────────────
# PC2 stops broadcasting UDP while paused / in an in-game menu, so the
# eGameState pause flag never arrives — silence after data IS the pause.

def test_stream_silence_reads_as_paused(monkeypatch):
    source = PCARS2Telemetry()
    source._on_packet(build_phys_packet(sRpm=1234))
    assert source.read().game_paused is False        # packets flowing

    import time as _time
    monkeypatch.setattr(pcars2.time, "monotonic",
                        lambda: source._last_packet_at + 3.0)
    assert source.read().game_paused is True         # 3s of silence

    # Packets resume -> pause clears
    monkeypatch.undo()
    source._on_packet(build_phys_packet(sRpm=1500))
    assert source.read().game_paused is False


def test_no_packets_yet_is_not_paused():
    source = PCARS2Telemetry()
    assert source.read().game_paused is False        # waiting, not paused
