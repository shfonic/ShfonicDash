"""
Project CARS 2 UDP telemetry parser.

Listens on port 5606 (default PCARS2 UDP output port).
Packet types handled:
  eCarPhysics (0)               — gear, speed, RPM, throttle, brake, tyre data, fuel
  eTimings (3)                  — per-participant lap/sector/position timing
  eRaceDefinition (1)           — personal best lap & sector times, laps in event
  eGameState (4)                — session type (practice / qualifying / race)
  eParticipantVehicleNames (8)  — vehicle name, class name, tyre name per participant

All struct layouts follow the official PCARS2 UDP specification.
"""

import logging
import struct
import threading
import time
from enum import IntEnum

from telemetry.base import TelemetrySource
from telemetry.threaded_source import TelemetryThread
from core.telemetry_model import TelemetryData

log = logging.getLogger("pcars2")

_UDP_PORT = 5606

_MAX_PARTICIPANTS = 32
_PARTICIPANT_INFO_SIZE = 32

# Car physics struct format (full packet)
_PHYS_FMT = (
    '<IIBBBBbBBbBBhHhHHBBBBffHHbBBBf3f3f3f3f3f3f3f'
    '4B4B4f4f4B4f4B4B4B4h4H4H4H4H4H4H4H4H4f4f4f4f'
    '4H4Hff2BBBBIB40c40c40c40cf3fBI'
)

# Timings packet header — 33 bytes.
# Source: MacManley/project-cars-2-udp (PacketTimingsData.h)
# 12-byte base + sNumParticipants(b) + sParticipantsChangedTimestamp(I)
# + sEventTimeRemaining(f) + sSplitTimeAhead(f) + sSplitTimeBehind(f) + sSplitTime(f)
_TIMINGS_HEADER_FMT = '<12s b I f f f f'
_TIMINGS_HEADER_SIZE = struct.calcsize(_TIMINGS_HEADER_FMT)  # 33 bytes

# Per-participant info struct — 32 bytes each, #pragma pack(push,1).
# Source: MacManley/project-cars-2-udp ParticipantsInfo struct.
# sWorldPosition[3](3h) + sOrientation[3](3h) + sCurrentLapDistance(H)
# + sRacePosition(B) + sSector(B) + sHighestFlag(B) + sPitModeSchedule(B)
# + sCarIndex(H) + sRaceState(B) + sCurrentLap(B)
# + sCurrentTime(f) + sCurrentSectorTime(f) + sMPParticipantIndex(H)
_PART_FMT = '<6h H 4B H 2B 2f H'
_PART_SIZE = struct.calcsize(_PART_FMT)  # 32 bytes

# Packet tail layout (after 32 participant slots):
# sLocalParticipantIndex (uint16, 2 bytes) then TickCount (uint32, 4 bytes) = 6 bytes total.
_TAIL_SIZE = 6

# Race definition (sRaceData) struct — personal best times
_TRACKNAME_LEN = 64
_RACEDATA_FMT = (
    f'<12s f f f f f f f f f '
    f'{_TRACKNAME_LEN}s {_TRACKNAME_LEN}s {_TRACKNAME_LEN}s {_TRACKNAME_LEN}s '
    f'Hb'
)
_RACEDATA_SIZE = struct.calcsize(_RACEDATA_FMT)

# Game state packet — for session type extraction
_GAMESTATE_FMT = '<12s H B'
_GAMESTATE_SIZE = struct.calcsize(_GAMESTATE_FMT)

# Extended sGameStateData (SMS UDP protocol v2) — weather fields follow the
# game-state byte: ambientTemperature(s8), trackTemperature(s8),
# rainDensity(u8 0–255), snowDensity(u8 0–255), windSpeed(s8),
# windDirectionX(s8), windDirectionY(s8).
_GAMESTATE_WEATHER_FMT = '<12s H B b b B B b b b'
_GAMESTATE_WEATHER_SIZE = struct.calcsize(_GAMESTATE_WEATHER_FMT)

# Type-8 partial 1: sParticipantVehicleNamesData (1164 B) — 16 × sVehicleInfo
# sIndex(u16) + sClass(u32) + sName[64] + paddingC(s16) = 72 bytes each
_VEHICLE_INFO_FMT = '<H I 64s h'
_VEHICLE_INFO_SIZE = struct.calcsize(_VEHICLE_INFO_FMT)   # 72
_VEHICLES_PER_PACKET = 16

# Map PC2 vehicle name strings (lower-cased) → our car_class identifiers.
_CLASS_MAP: dict[str, str] = {
    "formula rookie": "lcd",
    "kart": "lcd",
}

# Session state bits (bits 3-5 of the game state byte)
_SESSION_MAP = {
    1: "practice",    # SESSION_PRACTICE
    2: "practice",    # SESSION_TEST
    3: "qualifying",  # SESSION_QUALIFY
    4: "race",        # SESSION_FORMATION_LAP
    5: "race",        # SESSION_RACE
    6: "hotlap",      # SESSION_TIME_ATTACK
}

GEAR_NAMES = ['N', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', 'R']


def _normalize(v: float) -> float:
    """Normalize a throttle/brake value to 0.0–1.0."""
    f = float(v)
    if f > 1.5 and f <= 255.0:
        f /= 255.0
    if f > 1.0:
        f /= 100.0
    return max(0.0, min(1.0, f))


class _F(IntEnum):
    """Field indices within the car physics struct."""
    mPacketNumber = 0
    mCategoryPacketNumber = 1
    mPartialPacketIndex = 2
    mPartialPacketNumber = 3
    mPacketType = 4
    mPacketVersion = 5
    sViewedParticipantIndex = 6
    sUnfilteredThrottle = 7
    sUnfilteredBrake = 8
    sUnfilteredSteering = 9
    sUnfilteredClutch = 10
    sCarFlags = 11
    sOilTempCelsius = 12
    sOilPressureKPa = 13
    sWaterTempCelsius = 14
    sWaterPressureKpa = 15
    sFuelPressureKpa = 16
    sFuelCapacity = 17
    sBrake = 18
    sThrottle = 19
    sClutch = 20
    sFuelLevel = 21
    sSpeed = 22
    sRpm = 23
    sMaxRpm = 24
    sSteering = 25
    sGearNumGears = 26
    # … (many more; see enum below for tyre fields)
    sTyreTemp1 = 67
    sTyreTemp2 = 68
    sTyreTemp3 = 69
    sTyreTemp4 = 70
    sTyreWear1 = 75
    sTyreWear2 = 76
    sTyreWear3 = 77
    sTyreWear4 = 78
    sTyreTreadTemp1 = 91
    sTyreTreadTemp2 = 92
    sTyreTreadTemp3 = 93
    sTyreTreadTemp4 = 94
    sAirPressure1 = 143
    sAirPressure2 = 144
    sAirPressure3 = 145
    sAirPressure4 = 146


class _PKT(IntEnum):
    eCarPhysics = 0
    eRaceDefinition = 1
    eParticipants = 2
    eTimings = 3
    eGameState = 4
    eWeatherState = 5
    eVehicleNames = 6
    eTimeStats = 7
    eParticipantVehicleNames = 8


class PCARS2Telemetry(TelemetrySource):
    """Receives PCARS2 UDP packets and populates TelemetryData."""

    def __init__(self, port: int = _UDP_PORT, record_path: str | None = None):
        self._port = port
        self._record_path = record_path
        self._recorder = None
        self._car_class = "pcars2"
        self._lock = threading.Lock()
        self._phys_raw: bytes | None = None
        self._timing_raw: bytes | None = None
        self._racedata_raw: bytes | None = None
        self._gamestate_raw: bytes | None = None
        self._type8_partials: dict[int, bytes] = {}  # keyed by mPartialPacketIndex
        self._class_detected = False
        self._thread: TelemetryThread | None = None

        # Sector split and lap tracking
        self._sector_prev: int = -1
        self._lap_prev: int = -1
        self._s1_time: float = 0.0       # cumulative lap time at end of S1
        self._s2_time: float = 0.0       # cumulative lap time at end of S2
        self._last_lap_time: float = 0.0 # most recently completed lap time
        self._prev_lap_time: float = 0.0 # sCurrentTime from previous frame
        self._best_lap_local: float = 0.0  # locally-tracked session best lap
        self._best_s1: float = 0.0         # cached from eRaceDefinition
        self._best_s2: float = 0.0
        self._best_s3: float = 0.0
        self._s1_flag: str = ""            # sector colour flags ("purple"/"green"/"")
        self._s2_flag: str = ""
        self._s3_flag: str = ""
        self._session_type: str = "race"  # updated once eGameState arrives
        self._last_packet_at: float = 0.0  # monotonic time of the last packet

    # ── TelemetrySource interface ────────────────────────────────────────

    def connect(self):
        if self._record_path:
            from telemetry.capture import PacketRecorder
            self._recorder = PacketRecorder(self._record_path, game="pcars2", port=self._port)
        self._thread = TelemetryThread(self._on_packet, port=self._port,
                                       recorder=self._recorder)
        self._thread.start()
        log.info(f"Listening on UDP port {self._port}")

    def disconnect(self):
        if self._thread:
            self._thread.stop()
            self._thread = None
        if self._recorder:
            self._recorder.close()
            self._recorder = None
        log.info("Disconnected")

    # PC2 stops broadcasting UDP entirely while the game is paused / in an
    # in-game menu, so the eGameState pause flag never arrives. Treat stream
    # silence after data has been flowing as the pause state instead — it
    # drives the PAUSED overlay and the pause-triggered session summary.
    _PAUSE_SILENCE_S = 2.0

    def read(self) -> TelemetryData:
        with self._lock:
            phys = self._phys_raw
            timing = self._timing_raw
            racedata = self._racedata_raw
            gamestate = self._gamestate_raw
            type8 = dict(self._type8_partials)
            last_at = self._last_packet_at

        data = self._build(phys, timing, racedata, gamestate, type8)
        if last_at and (time.monotonic() - last_at) > self._PAUSE_SILENCE_S:
            data.game_paused = True
        return data

    # ── Packet dispatcher ────────────────────────────────────────────────

    def _on_packet(self, packet: bytes):
        if len(packet) < 12:
            return
        pkt_type = struct.unpack_from('<B', packet, 10)[0]
        with self._lock:
            self._last_packet_at = time.monotonic()
            if pkt_type == _PKT.eCarPhysics:
                self._phys_raw = packet
            elif pkt_type == _PKT.eTimings:
                self._timing_raw = packet
            elif pkt_type == _PKT.eRaceDefinition:
                self._racedata_raw = packet
            elif pkt_type == _PKT.eGameState:
                self._gamestate_raw = packet
            elif pkt_type == _PKT.eParticipantVehicleNames:
                partial_idx = struct.unpack_from('<B', packet, 8)[0]
                self._type8_partials[partial_idx] = packet
                if len(packet) == 1164:  # new vehicle-names data → re-detect class
                    self._class_detected = False

    # ── Data assembly ────────────────────────────────────────────────────

    def _build(self, phys: bytes | None, timing: bytes | None,
               racedata: bytes | None, gamestate: bytes | None,
               type8_partials: dict) -> TelemetryData:
        if phys is None:
            return TelemetryData()

        gear = "N"
        speed = 0.0
        rpm = 0
        max_rpm = 8000
        throttle = 0.0
        brake = 0.0
        steer = 0.0
        fuel_remaining = 0.0
        fuel_capacity = 0.0
        tyre_temp = (0.0,) * 4
        tyre_wear = (0.0,) * 4
        tyre_pressure = (0.0,) * 4
        viewed_participant = 0

        if phys:
            try:
                f = struct.unpack(_PHYS_FMT, phys)
                gear_idx = f[_F.sGearNumGears] & 0x0F
                gear = GEAR_NAMES[gear_idx] if gear_idx < len(GEAR_NAMES) else "N"
                speed = f[_F.sSpeed] * 3.6   # m/s → km/h
                rpm = int(f[_F.sRpm])
                max_rpm = int(f[_F.sMaxRpm]) or 8000
                throttle = _normalize(f[_F.sThrottle])
                brake = _normalize(f[_F.sBrake])
                steer = float(f[_F.sSteering]) / 127.0  # -1 to 1

                fuel_level_frac = float(f[_F.sFuelLevel])  # 0.0–1.0
                fuel_cap_raw = float(f[_F.sFuelCapacity])   # litres or kg
                fuel_capacity = fuel_cap_raw if fuel_cap_raw > 0 else 45.0
                fuel_remaining = fuel_level_frac * fuel_capacity

                # Tyre tread temps (uint16, Kelvin → Celsius)
                tyre_temp = tuple(
                    max(0.0, float(f[_F.sTyreTreadTemp1 + i]) - 273.15) for i in range(4)
                )
                # Tyre wear (uint8, 0-255 → 0.0-1.0)
                tyre_wear = tuple(
                    max(0.0, min(1.0, float(f[_F.sTyreWear1 + i]) / 255.0)) for i in range(4)
                )
                # Air pressure (uint16, PSI × 10 → divide by 10)
                tyre_pressure = tuple(
                    float(f[_F.sAirPressure1 + i]) / 10.0 for i in range(4)
                )
                viewed_participant = max(0, int(f[_F.sViewedParticipantIndex]))
            except (struct.error, IndexError):
                pass

        # ── Car class detection ───────────────────────────────────────────
        # type-8 is sent as multiple partials; 1164-byte partials contain
        # sParticipantVehicleNamesData (16 × sVehicleInfo).  Each sVehicleInfo
        # has a sVName[64] that names the car model, e.g. "Formula Rookie Renault".
        # We match this name directly against _CLASS_MAP (substring, lower-cased)
        # using the first non-empty entry — in a single-class session all cars
        # share the same class, so entry 0 represents the player's class too.
        if not self._class_detected:
            veh_pkt = next((p for p in type8_partials.values() if len(p) == 1164), None)
            if veh_pkt:
                try:
                    for i in range(_VEHICLES_PER_PACKET):
                        offset = 12 + i * _VEHICLE_INFO_SIZE
                        if offset + _VEHICLE_INFO_SIZE > len(veh_pkt):
                            break
                        _, _, v_name_b, _ = struct.unpack_from(
                            _VEHICLE_INFO_FMT, veh_pkt, offset)
                        v_name = v_name_b.rstrip(b'\x00').decode(
                            'utf-8', errors='ignore').strip()
                        if not v_name:
                            continue
                        key = v_name.lower()
                        detected = next(
                            (v for k, v in _CLASS_MAP.items() if k in key),
                            "pcars2",
                        )
                        if detected != self._car_class:
                            log.info(f"vehicle='{v_name}' → {detected}")
                        self._car_class = detected
                        self._class_detected = True
                        break
                except Exception:
                    pass

        # ── Timing data ───────────────────────────────────────────────────
        gap_ahead = 0.0
        gap_behind = 0.0
        session_time_remaining = 0.0
        lap_time = 0.0
        last_lap = 0.0
        lap_number = 0
        position = 0
        total_cars = 0
        sector = 0
        lap_invalid = False

        if timing and len(timing) >= _TIMINGS_HEADER_SIZE:
            try:
                th = struct.unpack(_TIMINGS_HEADER_FMT, timing[:_TIMINGS_HEADER_SIZE])
                session_time_remaining = float(th[3])   # sEventTimeRemaining
                gap_ahead  = float(th[4])               # sSplitTimeAhead
                gap_behind = float(th[5])               # sSplitTimeBehind
                num_participants = int(th[1])            # sNumParticipants (signed)
                total_cars = max(0, num_participants)

                # sLocalParticipantIndex (uint16) sits at timing[-6:-4];
                # TickCount (uint32) is the final 4 bytes (timing[-4:]).
                # Fall back to sViewedParticipantIndex from physics if out of range.
                player_idx = viewed_participant
                if len(timing) >= _TIMINGS_HEADER_SIZE + _PART_SIZE + _TAIL_SIZE:
                    end_idx = struct.unpack_from('<H', timing, len(timing) - _TAIL_SIZE)[0]
                    candidate_start = _TIMINGS_HEADER_SIZE + end_idx * _PART_SIZE
                    if candidate_start + _PART_SIZE <= len(timing) - _TAIL_SIZE:
                        player_idx = int(end_idx)

                blob_start = _TIMINGS_HEADER_SIZE + player_idx * _PART_SIZE
                if len(timing) >= blob_start + _PART_SIZE:
                    p = struct.unpack(_PART_FMT, timing[blob_start:blob_start + _PART_SIZE])
                    # p[0]-p[2] = sWorldPosition[3], p[3]-p[5] = sOrientation[3]
                    # p[6] = sCurrentLapDistance
                    # p[7] = sRacePosition: bit 7 = participant active, bits 0-6 = position (1-based)
                    race_pos_byte = int(p[7])
                    is_active  = bool(race_pos_byte & 0x80)
                    race_pos   = race_pos_byte & 0x7F
                    position   = race_pos if (is_active and total_cars > 0 and 1 <= race_pos <= total_cars) else 0
                    # p[8] = sSector: lower 2 bits = sector (0/1/2), upper bits = position precision
                    sector      = int(p[8]) & 0x03
                    # p[9] = sHighestFlag, p[10] = sPitModeSchedule
                    # p[11] = sCarIndex (top bit = human player)
                    # p[12] = sRaceState: lower 3 bits = race state, bit 3 = lap invalid
                    lap_invalid = bool(int(p[12]) & 0x08)
                    lap_number  = int(p[13])              # sCurrentLap (1-based)
                    lap_time    = max(0.0, float(p[14]))  # sCurrentTime (running lap timer)
                    # sLastLapTime is not in eTimings; track via lap-number transitions.
                    if lap_number != self._lap_prev and self._lap_prev > 0:
                        self._last_lap_time = self._prev_lap_time
                        if self._last_lap_time > 0:
                            if self._best_lap_local <= 0 or self._last_lap_time < self._best_lap_local:
                                self._best_lap_local = self._last_lap_time
                        # Compute S3 flag before resetting sector times
                        if self._s2_time > 0:
                            s3_dur = self._last_lap_time - self._s2_time
                            self._s3_flag = "purple" if (self._best_s3 <= 0 or s3_dur < self._best_s3) else ""
                        else:
                            self._s3_flag = ""
                        self._s1_time = 0.0
                        self._s2_time = 0.0
                        # _s1_flag/_s2_flag persist until next sector transition
                    self._lap_prev    = lap_number
                    self._prev_lap_time = lap_time
                    last_lap = self._last_lap_time

                    if sector == 1 and self._sector_prev == 0 and lap_time > 0:
                        self._s1_time = lap_time
                        self._s1_flag = "purple" if (self._best_s1 <= 0 or self._s1_time < self._best_s1) else ""
                        self._s2_flag = ""  # entering S2; reset S2 flag for current lap
                    elif sector == 2 and self._sector_prev == 1 and lap_time > 0:
                        self._s2_time = lap_time
                        s2_dur = self._s2_time - self._s1_time if self._s1_time > 0 else self._s2_time
                        self._s2_flag = "purple" if (self._best_s2 <= 0 or s2_dur < self._best_s2) else ""
                    self._sector_prev = sector

            except (struct.error, IndexError):
                pass

        # ── Race definition: personal best lap / sectors ──────────────────
        best_lap = 0.0
        best_s1 = 0.0
        best_s2 = 0.0
        best_s3 = 0.0
        total_laps = 0

        if racedata and len(racedata) >= _RACEDATA_SIZE:
            try:
                r = struct.unpack(_RACEDATA_FMT, racedata[:_RACEDATA_SIZE])
                best_lap = max(0.0, float(r[2]))   # sPersonalFastestLapTime
                best_s1  = float(r[3])             # sPersonalFastestSector1Time
                best_s2  = float(r[4])             # sPersonalFastestSector2Time
                best_s3  = float(r[5])             # sPersonalFastestSector3Time
                total_laps = int(r[14])            # sLapsTimeInEvent
                # Cache best sector times for use in sector-flag computation
                if best_s1 > 0: self._best_s1 = best_s1
                if best_s2 > 0: self._best_s2 = best_s2
                if best_s3 > 0: self._best_s3 = best_s3
            except (struct.error, IndexError):
                pass

        # ── Session type and game pause state from game state packet ─────────
        game_paused = False
        weather = ""
        air_temp = 0.0
        track_temp = 0.0
        if gamestate and len(gamestate) >= _GAMESTATE_SIZE:
            try:
                gs = struct.unpack(_GAMESTATE_FMT, gamestate[:_GAMESTATE_SIZE])
                session_bits = (int(gs[2]) >> 3) & 0x07
                self._session_type = _SESSION_MAP.get(session_bits, "race")
                # bits 0-2: 3=INGAME_PAUSED, 4=INGAME_INMENU
                game_paused = (int(gs[2]) & 0x07) in (3, 4)
            except (struct.error, IndexError):
                pass
        if gamestate and len(gamestate) >= _GAMESTATE_WEATHER_SIZE:
            try:
                gw = struct.unpack(_GAMESTATE_WEATHER_FMT,
                                   gamestate[:_GAMESTATE_WEATHER_SIZE])
                air_temp = float(gw[3])
                track_temp = float(gw[4])
                rain, snow = int(gw[5]), int(gw[6])
                if snow > 0:
                    weather = "snow"
                elif rain > 0:
                    weather = "light_rain" if rain < 128 else "heavy_rain"
                else:
                    weather = "clear"
            except (struct.error, IndexError):
                pass

        # Delta vs personal best lap; fall back to locally-tracked best if game hasn't sent one yet
        eff_best = best_lap if best_lap > 0 else self._best_lap_local
        delta = round(lap_time - eff_best, 3) if eff_best > 0 and lap_time > 0 else 0.0

        return TelemetryData(
            game="pcars2",
            car_class=self._car_class,
            gear=gear,
            speed=round(speed, 1),
            rpm=rpm,
            max_rpm=max_rpm,
            throttle=round(throttle, 3),
            brake=round(brake, 3),
            steer=round(steer, 3),
            fuel_remaining=round(fuel_remaining, 2),
            fuel_capacity=fuel_capacity,
            tyre_temp=tuple(round(t, 1) for t in tyre_temp),
            tyre_wear=tuple(round(w, 4) for w in tyre_wear),
            tyre_pressure=tuple(round(p, 2) for p in tyre_pressure),
            lap_time=round(lap_time, 3),
            lap_invalid=lap_invalid,
            last_lap=round(last_lap, 3),
            best_lap=round(eff_best, 3),
            delta=delta,
            lap_number=lap_number,
            total_laps=total_laps,
            sector=sector,
            sector1_time=round(self._s1_time, 3),
            sector2_time=round(self._s2_time, 3),
            sector1_flag=self._s1_flag,
            sector2_flag=self._s2_flag,
            sector3_flag=self._s3_flag,
            best_sector1=best_s1,
            best_sector2=best_s2,
            best_sector3=best_s3,
            position=position,
            total_cars=total_cars,
            gap_ahead=round(max(0.0, gap_ahead), 3),
            gap_behind=round(max(0.0, gap_behind), 3),
            session_time_remaining=session_time_remaining,
            session_type=self._session_type,
            game_paused=game_paused,
            weather=weather,
            air_temp=air_temp,
            track_temp=track_temp,
        )

