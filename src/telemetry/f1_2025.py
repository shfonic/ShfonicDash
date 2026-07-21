"""
F1 2025 UDP telemetry parser.

EA / Codemasters F1 games broadcast UDP packets on port 20777.
The format is documented at:
  https://answers.ea.com/t5/General-Discussion/F1-24-UDP-Specification/m-p/13745808

F1 2025 uses the same packet header as F1 2024 (format version 2024).
The F1 25: 2026 Season Pack broadcasts `m_packetFormat == 2026` and extends
CarStatusData with a new `m_ersHarvestLimitPerLap` float (see _STS_CAR_SIZE_2026
below) — everything else (header, CarTelemetryData, LapData, CarTelemetry2Data)
is unchanged from the 2024/2025 layout.

All integers are little-endian. Floats are IEEE 754 single-precision.

Packet header (24 bytes):
  uint16 packetFormat       (2024)
  uint8  gameYear
  uint8  gameMajorVersion
  uint8  gameMinorVersion
  uint8  packetVersion
  uint8  packetId
  uint8  sessionUID[8]
  float  sessionTime
  uint32 frameIdentifier
  uint32 overallFrameIdentifier
  uint8  playerCarIndex
  uint8  secondaryPlayerCarIndex

Packet IDs used here:
  0  — Motion
  1  — Session
  2  — Lap Data
  4  — Participants
  6  — Car Telemetry
  7  — Car Status
  8  — Final Classification
"""

import logging
import struct
import threading

from telemetry.base import TelemetrySource
from telemetry.lap_delta import LapDeltaTracker, interpolate_profile
from telemetry.threaded_source import TelemetryThread
from core.telemetry_model import TelemetryData

log = logging.getLogger("f1_25")

_UDP_PORT = 20777
_HEADER_SIZE = 29  # bytes (F1 2024/2025/2026 header — unchanged across formats)
_PLAYER_IDX_OFFSET = 27  # playerCarIndex inside header
_PACKET_FORMAT_2026 = 2026  # m_packetFormat value used by the 2026 Season Pack

# ── Packet IDs ───────────────────────────────────────────────────────────────
_PKT_MOTION      = 0
_PKT_SESSION     = 1
_PKT_LAP         = 2
_PKT_EVENT       = 3    # incident events — collisions, penalties, overtakes
_PKT_PARTICIPANT = 4
_PKT_TELEMETRY   = 6
_PKT_STATUS      = 7
_PKT_FINAL       = 8    # Final Classification — sent once at session end
_PKT_TELEMETRY2  = 16   # F1 2026 DLC — Active Aero + Boost (MOR)

# ── Motion packet (id 0) ──────────────────────────────────────────────────────
# Layout: 29-byte header + CarMotionData[22]. Each CarMotionData is 60 bytes:
#   float m_worldPosition{X,Y,Z}    (0, 4, 8)
#   float m_worldVelocity{X,Y,Z}    (12, 16, 20)
#   int16 m_worldForwardDir{X,Y,Z}  (24, 26, 28)
#   int16 m_worldRightDir{X,Y,Z}    (30, 32, 34)
#   float m_gForce{Lateral,Longitudinal,Vertical}  (36, 40, 44)
#   float m_yaw, m_pitch, m_roll    (48, 52, 56)
# F1's world frame is Y-up: X (east/west) and Z (north/south) form the ground
# plane, Y is elevation — which already matches TelemetryData's convention, so
# the coordinates are stored as-is.
# F1 2026 shrank CarMotionData by 6 bytes (stride 60 → 54) and shifted
# yaw/pitch/roll forward from offset 48 → 42. worldPosition (0/4/8) is unchanged.
# This only bit multi-car sessions: at playerCarIndex 0 (Time Trial) the first
# car lands right regardless of stride; at a race-weekend grid slot (e.g. 21) the
# 60-byte stride overshot into the packet's trailer and read zeros. Confirmed
# from a real F1 2026 race-weekend capture (packet len 1325, player idx 21).
_MOTION_CAR_SIZE = 60        # 2024 / 2025
_MOTION_CAR_SIZE_2026 = 54   # 2026+
_MOTION_NUM_CARS = 22
_M_WORLD_POS_X = 0
_M_WORLD_POS_Y = 4
_M_WORLD_POS_Z = 8
_M_YAW         = 48          # 2024 / 2025
_M_YAW_2026    = 42          # 2026+

# ── Participants packet ───────────────────────────────────────────────────────
# Packet layout: 29-byte header + 1 byte numActiveCars + N × ParticipantData
#
# Three observed variants:
#
# V1_22 — F1 24 standard (60 bytes, 22 slots → 1350-byte packet):
#   uint8  aiControlled (0), driverId (1), networkId (2), teamId (3),
#   uint8  myTeam (4), raceNumber (5), nationality (6)
#   char[48] name (7)   null-terminated UTF-8
#   uint8  yourTelemetry (55), showOnlineNames (56)
#   uint16 techLevel (57), uint8 platform (59)
#
# V1_24 — F1 25 My Career (60 bytes, 24 slots → 1470-byte packet):
#   The struct was reorganised.  Empirically confirmed from live packet dumps:
#   byte 0: aiControlled, byte 1: driverId, byte 2: networkId(?)
#   bytes 3-4: unknown (always 0xff 0xff in observed data)
#   bytes 5-6: teamId (uint16 LE — widened by the 2026 Season Pack, whose team
#     ids are 476–486; "shares value across teammates" and the observed
#     constant 0x01 at byte 6 are the low/high bytes of a 2026 team id)
#   byte 7: showOnlineNames? (always 0x00)
#   bytes 8-9: techLevel? (uint16, varies per car)
#   char[...] name (10)   null-terminated UTF-8  ← empirically confirmed
#   raceNumber location TBD (not in first 20 bytes)
#
# V2 — F1 25 v3 post-patch (57 bytes, 22 slots → 1284-byte packet):
#   uint8  aiControlled (0), driverId (1), networkId (2), teamId (3),
#   uint8  myTeam (4), raceNumber (5), nationality (6)
#   char[32] name (7)   null-terminated UTF-8  ← reduced from 48
#   uint8  yourTelemetry (39), showOnlineNames (40)
#   uint16 techLevel (41), uint8 platform (43)
#   uint8  numColours (44)
#   LiveryColour[4] (45)   3 bytes each (R, G, B) = 12 bytes
_PART_CAR_SIZE_V1   = 60   # F1 24 (22 slots) or F1 25 My Career (24 slots)
_PART_CAR_SIZE_V2   = 57   # F1 25 v3 post-patch
_PART_RACE_NUM_OFFSET = 5  # V1_22 and V2 only; V1_24 location TBD
_PART_COLOUR_OFFSET  = 44  # V2 only: offset of m_numColours

# ── Final Classification packet ───────────────────────────────────────────────
# Packet 8 — sent once when the session ends.  Layout: 29-byte header +
# 1 byte numCars + N × FinalClassificationData.  Two struct sizes:
#
# V45 — F1 24 (45 bytes):
#   uint8  position (0), numLaps (1), gridPosition (2), points (3),
#   uint8  numPitStops (4), resultStatus (5)
#   uint32 bestLapTimeInMS (6)
#   double totalRaceTime (10)   seconds, excluding penalties
#   uint8  penaltiesTime (18), numPenalties (19), numTyreStints (20)
#   uint8[8] tyreStintsActual (21), Visual (29), EndLaps (37)
#
# V46 — F1 25 (46 bytes): uint8 m_resultReason inserted at offset 6;
#   everything after shifts by 1 (bestLapTimeInMS 7, totalRaceTime 11,
#   penaltiesTime 19).
_FINAL_CAR_SIZE_V45 = 45
_FINAL_CAR_SIZE_V46 = 46
_FINAL_STATUS_FINISHED = 3   # m_resultStatus: 3 = finished (4 DNF, 5 DSQ, 7 retired)

_F1_FLAG_MAP = {-1: "", 0: "", 1: "green", 2: "blue", 3: "yellow", 4: "red"}
_F1_SC_MAP   = {0: "", 1: "sc", 2: "vsc", 3: "sc"}   # 3 = SC forming lap

# ── Session type mapping ─────────────────────────────────────────────────────
# F1 23+ enum: Sprint Shootout occupies 10–14, Race moved to 15–17, Time Trial
# to 18. TT=18 is empirically confirmed (hotlap sessions work), which pins the
# whole enum — under the old F1 22 layout TT was 13. Race sessions previously
# only mapped correctly because 15 fell through to the "race" default; 10–12
# were mislabelled "race", which is why Sprint Qualifying logged as a race.
_SESSION_MAP = {
    0:  "unknown",
    1:  "practice",    # P1
    2:  "practice",    # P2
    3:  "practice",    # P3
    4:  "practice",    # Short Practice
    5:  "qualifying",  # Q1
    6:  "qualifying",  # Q2
    7:  "qualifying",  # Q3
    8:  "qualifying",  # Short Qualifying
    9:  "qualifying",  # One-Shot Qualifying
    10: "qualifying",  # Sprint Shootout 1
    11: "qualifying",  # Sprint Shootout 2
    12: "qualifying",  # Sprint Shootout 3
    13: "qualifying",  # Short Sprint Shootout
    14: "qualifying",  # One-Shot Sprint Shootout
    15: "race",
    16: "race",        # Race 2 — possibly the sprint race; raw id is logged
    17: "race",        # Race 3     to session CSVs so this can be confirmed
    18: "hotlap",      # Time Trial
}

# Finer-grained variant recorded in session CSVs (and their filenames).
# 16/17 may turn out to be "sprint_race" — pending a raw id from a real
# sprint weekend (session_type_raw in the CSV meta / dashboard.log).
_SESSION_SUBTYPE_MAP = {
    10: "sprint_qualifying",
    11: "sprint_qualifying",
    12: "sprint_qualifying",
    13: "sprint_qualifying",
    14: "sprint_qualifying",
}

# ── Event packet (ID 3) ──────────────────────────────────────────────────────
# Header, then uint8[4] eventStringCode, then a payload union. Only the codes
# below are handled; everything else is ignored.
#   "COLL": uint8 vehicle1Idx, uint8 vehicle2Idx
#   "OVTK": uint8 overtakingVehicleIdx, uint8 beingOvertakenVehicleIdx
#   "PENA": uint8 penaltyType, infringementType, vehicleIdx, otherVehicleIdx,
#           time, lapNum, placesGained
_EVT_CODE_OFFSET    = _HEADER_SIZE
_EVT_PAYLOAD_OFFSET = _HEADER_SIZE + 4

_PENALTY_TYPES = {
    0: "drive_through", 1: "stop_go", 2: "grid_penalty", 3: "penalty_reminder",
    4: "time_penalty", 5: "warning", 6: "disqualified",
    7: "removed_from_formation_lap", 8: "parked_too_long_timer",
    9: "tyre_regulations", 10: "lap_invalidated",
    11: "this_and_next_lap_invalidated", 12: "lap_invalidated_no_reason",
    13: "this_and_next_lap_invalidated_no_reason",
    14: "this_and_previous_lap_invalidated",
    15: "this_and_previous_lap_invalidated_no_reason",
    16: "retired", 17: "black_flag_timer",
}

_INFRINGEMENT_TYPES = {
    0:  "blocking_slow_driving", 1: "blocking_wrong_way", 2: "reversing_off_start_line",
    3:  "big_collision", 4: "small_collision",
    5:  "collision_failed_to_hand_back_single", 6: "collision_failed_to_hand_back_multiple",
    7:  "corner_cutting_gained_time", 8: "corner_cutting_overtake_single",
    9:  "corner_cutting_overtake_multiple", 10: "crossed_pit_exit_lane",
    11: "ignoring_blue_flags", 12: "ignoring_yellow_flags", 13: "ignoring_drive_through",
    14: "too_many_drive_throughs", 15: "drive_through_reminder_n_laps",
    16: "drive_through_reminder_this_lap", 17: "pit_lane_speeding",
    18: "parked_too_long", 19: "ignoring_tyre_regulations", 20: "too_many_penalties",
    21: "multiple_warnings", 22: "approaching_disqualification",
    23: "tyre_regulations_select_single", 24: "tyre_regulations_select_multiple",
    25: "lap_invalidated_corner_cutting", 26: "lap_invalidated_running_wide",
    27: "corner_cutting_ran_wide_minor", 28: "corner_cutting_ran_wide_significant",
    29: "corner_cutting_ran_wide_extreme", 30: "lap_invalidated_wall_riding",
    31: "lap_invalidated_flashback_used", 32: "lap_invalidated_reset_to_track",
    33: "blocking_the_pitlane", 34: "jump_start",
    35: "safety_car_collision", 36: "safety_car_illegal_overtake",
    37: "safety_car_exceeding_pace", 38: "vsc_exceeding_pace",
    39: "formation_lap_below_speed", 40: "formation_lap_parking",
    41: "retired_mechanical_failure", 42: "retired_terminally_damaged",
    43: "safety_car_falling_too_far_back", 44: "black_flag_timer",
    45: "unserved_stop_go", 46: "unserved_drive_through",
    47: "engine_component_change", 48: "gearbox_change", 49: "parc_ferme_change",
    50: "league_grid_penalty", 51: "retry_penalty", 52: "illegal_time_gain",
    53: "mandatory_pitstop", 54: "attribute_assigned",
}

# ── Track ID mapping (EA F1 UDP spec) ───────────────────────────────────────
_TRACK_ID_MAP = {
    0:  "Melbourne",
    1:  "Paul Ricard",
    2:  "Shanghai",
    3:  "Sakhir",
    4:  "Catalunya",
    5:  "Monaco",
    6:  "Montreal",
    7:  "Silverstone",
    8:  "Hockenheim",
    9:  "Hungaroring",
    10: "Spa",
    11: "Monza",
    12: "Singapore",
    13: "Suzuka",
    14: "Abu Dhabi",
    15: "Austin",
    16: "Interlagos",
    17: "Red Bull Ring",
    18: "Sochi",
    19: "Mexico City",
    20: "Baku",
    21: "Sakhir Short",
    22: "Silverstone Short",
    23: "Austin Short",
    24: "Suzuka Short",
    # Modern-era tracks — ids per the F1Game.UDP TrackId enum
    # (github.com/volodymyr-fed/F1Game.UDP, tracks the official EA spec;
    # verified 2026-07-10 after Imola was mis-reporting as "Las Vegas").
    # 25, 28 and 33–38 are unused gaps; Hanoi/Portimão are retired from the
    # current spec, so they are intentionally absent.
    26: "Zandvoort",
    27: "Imola",
    29: "Jeddah",
    30: "Miami",
    31: "Las Vegas",
    32: "Lusail",
    39: "Silverstone Reverse",
    40: "Red Bull Ring Reverse",
    41: "Zandvoort Reverse",
    42: "Madrid",
}

# ── Team ID mapping (EA F1 UDP spec) ────────────────────────────────────────
# Display names deliberately drop the spec's year suffixes ("McLaren '26" is
# just McLaren on the dash); the exact id is preserved in the session CSV as
# S,team_id_raw. 2026 Season Pack / F2 2025 ids sourced from the F1Game.UDP
# parser (github.com/volodymyr-fed/F1Game.UDP, tracks the official EA spec).
_TEAM_ID_MAP = {
    # F1 2025 season
    0:  "Mercedes",
    1:  "Ferrari",
    2:  "Red Bull Racing",
    3:  "Williams",
    4:  "Aston Martin",
    5:  "Alpine",
    6:  "Racing Bulls",
    7:  "Haas",
    8:  "McLaren",
    9:  "Sauber",
    # Specials
    41:  "F1 Generic",
    85:  "My Team",
    104: "Custom Team",
    129: "Konnersport",       # Braking Point
    142: "APXGP",             # F1 The Movie
    154: "APXGP",
    155: "Konnersport",
    # F2 2024 season
    158: "ART Grand Prix",
    159: "Campos",
    160: "Rodin Motorsport",
    161: "AIX Racing",
    162: "DAMS",
    163: "Hitech",
    164: "MP Motorsport",
    165: "Prema",
    166: "Trident",
    167: "Van Amersfoort Racing",
    168: "Invicta",
    # F1 2024 season
    185: "Mercedes",
    186: "Ferrari",
    187: "Red Bull Racing",
    188: "Williams",
    189: "Aston Martin",
    190: "Alpine",
    191: "Racing Bulls",
    192: "Haas",
    193: "McLaren",
    194: "Sauber",
    # F2 2025 season
    465: "ART Grand Prix",
    466: "Campos",
    467: "Rodin Motorsport",
    468: "AIX Racing",
    469: "DAMS",
    470: "Hitech",
    471: "MP Motorsport",
    472: "Prema",
    473: "Trident",
    474: "Van Amersfoort Racing",
    475: "Invicta",
    # F1 2026 season (2026 Season Pack DLC)
    476: "Mercedes",
    477: "Ferrari",
    478: "Red Bull Racing",
    479: "Williams",
    480: "Aston Martin",
    481: "Alpine",
    482: "Racing Bulls",
    483: "Haas",
    484: "McLaren",
    485: "Audi",
    486: "Cadillac",
}

# ── Tyre compound mapping ────────────────────────────────────────────────────
_VISUAL_TYRE = {
    16: "Soft", 17: "Medium", 18: "Hard",
    7:  "Inter", 8:  "Wet",
    15: "Classic dry", 19: "Super soft",
    20: "Hyper soft",
}

# ── Formula class mapping ────────────────────────────────────────────────────
_FORMULA_CLASS = {
    0:  "formula1",
    1:  "formula1_classic",
    2:  "f2",
    3:  "formula3",
    4:  "formula1",   # test car
    6:  "f2",
    13: "formula1_2026",  # F1 2026 DLC season pack
}

# ── Car telemetry packet ─────────────────────────────────────────────────────
# F1 2025 (2026 Season Pack format) expanded from 22 to 24 car slots (to
# support My Career 12-team / 24-driver grids) and shrunk the per-car struct
# by 1 byte — surfaceType reduced from uint8[4] to uint8[3].  All fields
# through tyresPressure are at identical offsets to the F1 2024 spec.
#
# Struct per car (59 bytes):
#   uint16 speed km/h                                    (offset 0)
#   float  throttle                                      (offset 2)
#   float  steer                                         (offset 6)
#   float  brake                                         (offset 10)
#   uint8  clutch                                        (offset 14)
#   int8   gear                                          (offset 15)
#   uint16 engineRPM                                     (offset 16)
#   uint8  drs                                           (offset 18)
#   uint8  revLightsPercent                              (offset 19)
#   uint16 revLightsBitValue                             (offset 20)
#   uint16[4] brakesTemp                                 (offset 22)
#   uint8[4]  tyresSurfaceTemp                           (offset 30)
#   uint8[4]  tyresInnerTemp                             (offset 34)
#   uint16 engineTemp                                    (offset 38)
#   float[4]  tyresPressure                              (offset 40)
#   uint8[3]  surfaceType  ← was [4] in F1 2024         (offset 56)
# Total per car = 59 bytes
#
# Packet layout: 29-byte header + 24×59 car array + 3-byte trailer = 1448 bytes
_TELEM_CAR_SIZE = 59
_TELEM_NUM_CARS = 24

# Offsets within each car block
_T_SPEED     = 0   # uint16 km/h
_T_THROTTLE  = 2   # float
_T_STEER     = 6   # float
_T_BRAKE     = 10  # float
_T_GEAR      = 15  # int8
_T_RPM       = 16  # uint16
_T_DRS       = 18  # uint8 (0=off, 1=on)
_T_TYRE_SURF_TEMP  = 30  # uint8[4] RL,RR,FL,FR  (unchanged from F1 2024)
_T_TYRE_INNER_TEMP = 34  # uint8[4] RL,RR,FL,FR  core temp — what the HUD shows
_T_TYRE_PRESSURE   = 40  # float[4]              (unchanged from F1 2024)

# ── Lap data packet ──────────────────────────────────────────────────────────
# Struct per car (57 bytes):
#   uint32 lastLapTimeMs              (offset 0)
#   uint32 currentLapTimeMs           (offset 4)
#   uint16 sector1TimeMs              (offset 8)   (ms part)
#   uint8  sector1TimeMin             (offset 10)
#   uint16 sector2TimeMs              (offset 11)
#   uint8  sector2TimeMin             (offset 13)
#   uint16 deltaToCarInFrontMs        (offset 14)
#   uint8  deltaToCarInFrontMin       (offset 16)
#   uint16 deltaToRaceLeaderMs        (offset 17)
#   uint8  deltaToRaceLeaderMin       (offset 19)
#   float  lapDistance                (offset 20)
#   float  totalDistance              (offset 24)
#   float  safetyCarDelta             (offset 28)
#   uint8  carPosition                (offset 32)
#   uint8  currentLapNum              (offset 33)
#   uint8  pitStatus                  (offset 34)
#   uint8  numPitStops                (offset 35)
#   uint8  sector                     (offset 36)
#   uint8  currentLapInvalid          (offset 37)
#   uint8  penalties                  (offset 38)
#   …
#   uint8  driverStatus                (offset 44)
#   uint8  resultStatus                (offset 45)
#   uint8  pitLaneTimerActive          (offset 46)
#   uint16 pitLaneTimeMs               (offset 47)
# Total per car = 57 bytes
_LAP_CAR_SIZE = 57

_L_LAST_LAP_MS      = 0
_L_CURR_LAP_MS      = 4
_L_S1_MS            = 8   # uint16 (ms part, max 59999)
_L_S1_MIN           = 10  # uint8 minutes
_L_S2_MS            = 11  # uint16
_L_S2_MIN           = 13  # uint8
_L_DELTA_AHEAD_MS   = 14  # uint16 — gap to car in front (ms part)
_L_DELTA_AHEAD_MIN  = 16  # uint8  — gap to car in front (minutes)
_L_LAP_DISTANCE     = 20  # float32 (metres around current lap)
_L_CAR_POS          = 32
_L_LAP_NUM          = 33
_L_PIT_STATUS       = 34  # uint8 (0=none, 1=pitting, 2=in pits)
_L_NUM_PIT_STOPS    = 35  # uint8
_L_SECTOR           = 36
_L_INVALID          = 37
_L_CORNER_CUT_WARN  = 40  # uint8 cumulative cornerCuttingWarnings
_L_DRIVER_STATUS    = 44  # uint8 (0=garage, 1=flying lap, 2=in lap,
                          #        3=out lap, 4=on track)
_L_RESULT_STATUS    = 45  # uint8 (2=active, 3=finished, 4=DNF, 5=DSQ,
                          #        6=not classified, 7=retired)

_RESULT_STATUS_MAP = {3: "finished", 4: "dnf", 5: "dsq",
                      6: "not_classified", 7: "retired"}

# ── Car status packet ────────────────────────────────────────────────────────
# Per car struct (55 bytes, F1 2024/2025; 59 bytes, 2026 Season Pack):
#   uint8  tractionControl        (offset 0)
#   uint8  antiLockBrakes         (offset 1)
#   uint8  fuelMix                (offset 2)
#   uint8  frontBrakeBias         (offset 3)
#   uint8  pitLimiterStatus       (offset 4)
#   float  fuelInTank             (offset 5)
#   float  fuelCapacity           (offset 9)
#   float  fuelRemainingLaps      (offset 13)
#   uint16 maxRPM                 (offset 17)
#   uint16 idleRPM                (offset 19)
#   uint8  maxGears               (offset 21)
#   uint8  drsAllowed             (offset 22)
#   uint16 drsActivationDistance  (offset 23)
#   uint8  actualTyreCompound     (offset 25)
#   uint8  visualTyreCompound     (offset 26)
#   uint8  tyresAgeLaps           (offset 27)
#   int8   vehicleFiaFlags        (offset 28)
#   float  enginePowerICE         (offset 29)  skip
#   float  enginePowerMGUK        (offset 33)  skip
#   float  ersStoreEnergy         (offset 37)  (J, max ~4MJ)
#   uint8  ersDeployMode          (offset 41)  (0=None,1=Med,2=Hotlap,3=Overtake)
#   float  ersHarvestedThisLapMGUK (offset 42)
#   float  ersHarvestedThisLapMGUH (offset 46)
#   float  ersHarvestLimitPerLap  (offset 50)  2026 Season Pack only, skip
#   float  ersDeployedThisLap     (offset 50 / 54 in 2026)
#   uint8  networkPaused          (offset 54 / 58 in 2026)
_STS_CAR_SIZE_2025 = 55
_STS_CAR_SIZE_2026 = 59

_S_TC            = 0
_S_ABS           = 1
_S_PIT_LIMITER   = 4   # uint8
_S_FIA_FLAGS     = 28  # int8 vehicleFiaFlags: -1=invalid,0=none,1=green,2=blue,3=yellow,4=red
_S_FUEL_TANK     = 5   # float
_S_FUEL_CAP      = 9   # float
_S_FUEL_LAPS     = 13  # float
_S_MAX_RPM       = 17  # uint16
_S_DRS_ALLOWED   = 22  # uint8
_S_VISUAL_TYRE   = 26  # uint8
_S_ERS_ENERGY    = 37  # float (joules)
_S_ERS_MODE      = 41  # uint8
_S_ERS_HARV_MGUK = 42  # float
_S_ERS_DEPLOYED_2025 = 50  # float
_S_ERS_DEPLOYED_2026 = 54  # float (shifted by the new ersHarvestLimitPerLap field)

_ERS_MAX_JOULES = 4_000_000.0  # 4 MJ store

# ── Session packet offsets (post-header) ─────────────────────────────────────
# PacketSessionData body (after 29-byte header):
#   uint8  m_weather              (offset 0)
#   int8   m_trackTemperature     (offset 1)
#   int8   m_airTemperature       (offset 2)
#   uint8  m_totalLaps            (offset 3)
#   uint16 m_trackLength          (offset 4)
#   uint8  m_sessionType          (offset 6)
#   int8   m_trackId              (offset 7)
#   uint8  m_formula              (offset 8)
#   uint16 m_sessionTimeLeft      (offset 9)
#   uint16 m_sessionDuration      (offset 11)
#   uint8  m_pitSpeedLimit        (offset 13)
#   uint8  m_gamePaused           (offset 14)
#   uint8  m_isSpectating         (offset 15)
#   uint8  m_spectatorCarIndex    (offset 16)
#   uint8  m_sliProNativeSupport  (offset 17)
#   uint8  m_numMarshalZones      (offset 18)
#   MarshalZone[21] × 5 bytes     (offset 19–123)
#   uint8  m_safetyCarStatus      (offset 124)
_SES_WEATHER      = 0    # uint8
_SES_TRACK_TEMP   = 1    # int8 (°C)
_SES_AIR_TEMP     = 2    # int8 (°C)
_SES_TOTAL_LAPS   = 3    # uint8
_SES_SESSION_TYPE = 6    # uint8
_SES_TRACK_ID     = 7    # int8 (signed; -1 = no track)
_SES_FORMULA      = 8    # uint8
_SES_TIME_LEFT    = 9    # uint16 (little-endian seconds remaining)
_SES_GAME_PAUSED  = 14   # uint8  (1 = paused)
_SES_SAFETY_CAR   = 124  # uint8

# Assist settings sit further into the body, after: m_networkGame (offset 125),
# m_numWeatherForecastSamples (126), WeatherForecastSample[56] × 8 bytes
# (127–574), m_forecastAccuracy/m_aiDifficulty (575–576), three uint32 link
# ids (577–588), m_pitStopWindowIdealLap/LatestLap/RebookedThisLap (589–591).
# Verified byte-for-byte against a real capture
# (logs/captures/f1_25_20260709_142515.srtc, 193 Session packets, all
# identically 926 bytes — confirmed fixed-size arrays regardless of the
# in-use counts) — cross-checked by decoding the already-trusted fields
# above (weather/trackTemp/sessionType) plus the marshal-zone and
# weather-forecast arrays themselves against that same capture. Used
# unconditionally regardless of packetFormat, matching the rest of
# _parse_session (which already doesn't branch between 2025/2026 here).
_SES_STEERING_ASSIST    = 592  # uint8, 0=off 1=on
_SES_BRAKING_ASSIST     = 593  # uint8, 0=off 1=on
_SES_GEARBOX_ASSIST     = 594  # uint8, 0=manual 1=manual+suggested gear 2=auto
_SES_PIT_ASSIST         = 595  # uint8, 0=off 1=on
_SES_PIT_RELEASE_ASSIST = 596  # uint8, 0=off 1=on
_SES_ERS_ASSIST         = 597  # uint8, 0=off 1=on
_SES_DRS_ASSIST         = 598  # uint8, 0=off 1=on
_SES_RACING_LINE        = 599  # uint8, m_dynamicRacingLine: 0=off 1=corners only 2=full

# m_weather enum (EA F1 UDP spec, stable since F1 2018)
_WEATHER_MAP = {
    0: "clear",
    1: "light_cloud",
    2: "overcast",
    3: "light_rain",
    4: "heavy_rain",
    5: "storm",
}

# ── Car Telemetry 2 packet (ID 16) — F1 2026 DLC ────────────────────────────
# Per-car struct (10 bytes), no extra header byte before array:
#   uint8  activeAeroMode               (0=Corner, 1=Straight)
#   uint8  activeAeroAvailable          (0/1)
#   uint16 activeAeroActivationDistance (metres, skip)
#   uint8  overtakeAvailable            (0/1)
#   uint8  overtakeActive               (0/1)
#   uint16 overtakeActivationDistance   (metres, skip)
#   uint8  m_2026Regulations            (0=pre-2026, 1=2026 car)
#   uint8  drivingWrongWay              (skip)
_TELEM2_CAR_SIZE = 10
_T2_AERO_MODE    = 0
_T2_AERO_AVAIL   = 1
_T2_OVT_AVAIL    = 4
_T2_OVT_ACTIVE   = 5
_T2_2026_REGS    = 8


def _ms_to_s(ms: int) -> float:
    return ms / 1000.0 if ms > 0 else 0.0


def _decode_gear(raw: int) -> str:
    if raw == -1:
        return "R"
    if raw == 0:
        return "N"
    return str(raw)


class F12025Telemetry(TelemetrySource):
    """Receives F1 2025 UDP packets and populates TelemetryData."""

    def __init__(self, port: int = _UDP_PORT, debug: bool = False,
                 record_path: str | None = None):
        self._port = port
        self._debug = debug
        self._record_path = record_path
        self._recorder = None
        self._lock = threading.Lock()
        self._data = TelemetryData(game="f1_25", car_class="formula1")
        self._thread: TelemetryThread | None = None
        self._player_idx = 0
        self._total_cars = 20
        self._packet_format = _PACKET_FORMAT_2026  # updated per-packet from m_packetFormat
        # Sector flag tracking — written only from the UDP thread
        self._prev_sector   = 0
        self._prev_lap_num  = 0
        self._best_s1       = 0.0   # standalone S1 time
        self._best_s2       = 0.0   # standalone S2 time
        self._best_s3       = 0.0   # standalone S3 time
        self._current_delta = 0.0   # live delta vs reference lap
        # Live delta engine — profile recording + reference interpolation
        self._delta_tracker = LapDeltaTracker()
        self._game_paused:     bool  = False   # tracks Session-packet pause state
        self._delta_print_dist: float = 0.0   # last 500m milestone logged for delta
        self._prev_pit_status:  int  = 0      # previous pit_status for transition detection
        self._prev_session_int: int  = -1     # last raw m_sessionType — logged on change
        self._pending_events:   list = []     # incident events since the last read()
        # Multi-car data for qualifying leaderboard (UDP thread only, no lock needed)
        self._session_uid:      int  = 0    # m_sessionUID from header — reset on change
        self._car_names:        dict = {}   # car_idx → driver name string
        self._car_best_laps:    dict = {}   # car_idx → best lap seconds
        self._car_positions:    dict = {}   # car_idx → current qualifying position
        self._car_race_numbers: dict = {}   # car_idx → race number int
        self._car_colours:      dict = {}   # car_idx → (r, g, b) tuple or absent
        self._car_lap_numbers:  dict = {}   # car_idx → last seen lap number
        self._car_last_ms:      dict = {}   # car_idx → lastLapTimeMs at last lap increment
        self._car_race_times:   dict = {}   # car_idx → classified race time (incl. penalties)
        self._unmapped_team_logged: int = -1  # last unmapped team_id logged (once per id)

    # ── TelemetrySource interface ────────────────────────────────────────

    def connect(self):
        if self._record_path:
            from telemetry.capture import PacketRecorder
            self._recorder = PacketRecorder(self._record_path, game="f1_25", port=self._port)
        self._thread = TelemetryThread(self._on_packet, port=self._port,
                                       recorder=self._recorder)
        self._thread.start()
        log.info(f"Listening on UDP port {self._port}")

    def read(self) -> TelemetryData:
        with self._lock:
            snap = self._data.__class__(**self._data.__dict__)
            # Hand the incident buffer to exactly one snapshot — each event
            # appears once, in the frame after it arrived.
            snap.events = self._pending_events
            self._pending_events = []
            return snap

    def disconnect(self):
        if self._thread:
            self._thread.stop()
            self._thread = None
        if self._recorder:
            self._recorder.close()
            self._recorder = None
        log.info("Disconnected")

    # ── Packet dispatcher ────────────────────────────────────────────────

    def _reset_session_caches(self):
        """Clear all per-session accumulated data when a new session starts."""
        self._car_names.clear()
        self._car_best_laps.clear()
        self._car_positions.clear()
        self._car_race_numbers.clear()
        self._car_colours.clear()
        self._car_lap_numbers.clear()
        self._car_last_ms.clear()
        self._car_race_times.clear()
        # Reset one-time diagnostic flags so the new session logs fresh
        self._part_logged = False
        self._part_warned = False

    def _reset_player_lap_state(self):
        """Reset player-specific per-session lap tracking (called on session type change)."""
        self._best_s1         = 0.0
        self._best_s2         = 0.0
        self._best_s3         = 0.0
        self._current_delta   = 0.0
        self._delta_tracker.reset()
        self._delta_print_dist  = 0.0
        self._prev_lap_num      = 0
        self._prev_sector       = 0
        self._prev_pit_status   = 0

    def _on_packet(self, data: bytes):
        if len(data) < _HEADER_SIZE:
            return
        pkt_id = data[6]
        player_idx = data[_PLAYER_IDX_OFFSET]
        self._player_idx = player_idx
        self._packet_format = struct.unpack_from("<H", data, 0)[0]

        # m_sessionUID (uint64 at header offset 7) changes with each new session.
        # Reset all per-session state — caches, lap tracking, and best lap — so data
        # from one session (e.g. practice) never bleeds into the next (e.g. qualifying).
        uid = struct.unpack_from("<Q", data, 7)[0]
        if uid != 0 and uid != self._session_uid:
            if self._session_uid != 0:
                log.info(f"New session detected (UID {self._session_uid:#x} → {uid:#x}) — resetting all session state")
                self._reset_player_lap_state()
                with self._lock:
                    d = self._data
                    d.best_lap = 0.0
                    d.last_lap = 0.0
                    d.delta = 0.0
            self._session_uid = uid
            self._reset_session_caches()
            # A new session UID can mean a same-type restart (race restarted
            # from the menu) — clear the finished/classified state so a stale
            # "results saved" banner can't carry over.
            with self._lock:
                self._data.finish_status = ""
                self._data.classification_received = False
                self._data.opponents_pos = []

        try:
            if   pkt_id == _PKT_MOTION:      self._parse_motion(data, player_idx)
            elif pkt_id == _PKT_TELEMETRY:   self._parse_telemetry(data, player_idx)
            elif pkt_id == _PKT_LAP:          self._parse_lap(data, player_idx)
            elif pkt_id == _PKT_EVENT:        self._parse_event(data)
            elif pkt_id == _PKT_STATUS:       self._parse_status(data, player_idx)
            elif pkt_id == _PKT_SESSION:      self._parse_session(data)
            elif pkt_id == _PKT_TELEMETRY2:   self._parse_telemetry2(data, player_idx)
            elif pkt_id == _PKT_PARTICIPANT:  self._parse_participants(data)
            elif pkt_id == _PKT_FINAL:        self._parse_final_classification(data)
        except (struct.error, IndexError):
            pass
        except Exception as exc:
            log.exception(f"Unhandled error in packet id={pkt_id}: {exc}")

    # ── Parsers ──────────────────────────────────────────────────────────

    def _parse_motion(self, data: bytes, idx: int):
        if idx >= _MOTION_NUM_CARS:  # 255 = no player / spectator
            return
        # F1 2026 uses a smaller CarMotionData stride and a shifted yaw offset.
        if self._packet_format >= _PACKET_FORMAT_2026:
            stride, yaw_off = _MOTION_CAR_SIZE_2026, _M_YAW_2026
        else:
            stride, yaw_off = _MOTION_CAR_SIZE, _M_YAW
        num_cars = min(_MOTION_NUM_CARS, (len(data) - _HEADER_SIZE) // stride)
        if idx >= num_cars:
            return

        # All cars' slots, not just the player's: opponents feed the spotter
        # radar. Empty grid slots are all-zero and skipped.
        opponents = []
        pos_x = pos_y = pos_z = yaw = 0.0
        for car in range(num_cars):
            b = data[_HEADER_SIZE + car * stride:]
            x = struct.unpack_from("<f", b, _M_WORLD_POS_X)[0]
            z = struct.unpack_from("<f", b, _M_WORLD_POS_Z)[0]
            h = struct.unpack_from("<f", b, yaw_off)[0]
            if car == idx:
                pos_x, pos_z, yaw = x, z, h
                pos_y = struct.unpack_from("<f", b, _M_WORLD_POS_Y)[0]
            elif x != 0.0 or z != 0.0:
                opponents.append({"idx": car, "x": x, "z": z, "yaw": h})

        with self._lock:
            d = self._data
            d.pos_x = pos_x
            d.pos_y = pos_y
            d.pos_z = pos_z
            d.heading = yaw
            d.pos_valid = True
            d.opponents_pos = opponents

    def _parse_telemetry(self, data: bytes, idx: int):
        if idx >= _TELEM_NUM_CARS:  # 255 = no player / spectator
            return
        car_start = _HEADER_SIZE + idx * _TELEM_CAR_SIZE
        if car_start + _TELEM_CAR_SIZE > len(data):
            return

        b = data[car_start:]
        speed = struct.unpack_from("<H", b, _T_SPEED)[0]          # km/h
        throttle = struct.unpack_from("<f", b, _T_THROTTLE)[0]
        steer = struct.unpack_from("<f", b, _T_STEER)[0]
        brake = struct.unpack_from("<f", b, _T_BRAKE)[0]
        gear_raw = struct.unpack_from("<b", b, _T_GEAR)[0]        # int8
        rpm = struct.unpack_from("<H", b, _T_RPM)[0]
        drs_active = bool(b[_T_DRS])
        tyre_surf  = struct.unpack_from("<4B", b, _T_TYRE_SURF_TEMP)   # °C outer surface
        tyre_inner = struct.unpack_from("<4B", b, _T_TYRE_INNER_TEMP)  # °C core (HUD value)
        pressures  = struct.unpack_from("<4f", b, _T_TYRE_PRESSURE)

        gear = _decode_gear(gear_raw)

        with self._lock:
            d = self._data
            d.speed = float(speed)
            d.throttle = max(0.0, min(1.0, throttle))
            d.steer = steer
            d.brake = max(0.0, min(1.0, brake))
            d.gear = gear
            d.rpm = rpm
            d.drs_active = drs_active
            d.tyre_temp = tuple(float(t) for t in tyre_inner)
            d.tyre_pressure = tuple(round(p, 2) for p in pressures)

    def _parse_lap(self, data: bytes, idx: int):
        if idx >= 24:  # 24-slot My Career grids; bounds check below guards short packets
            return
        car_start = _HEADER_SIZE + idx * _LAP_CAR_SIZE
        if car_start + _LAP_CAR_SIZE > len(data):
            return

        b = data[car_start:]
        last_ms  = struct.unpack_from("<I", b, _L_LAST_LAP_MS)[0]
        curr_ms  = struct.unpack_from("<I", b, _L_CURR_LAP_MS)[0]
        s1_ms    = struct.unpack_from("<H", b, _L_S1_MS)[0]
        s1_min   = b[_L_S1_MIN]
        s2_ms    = struct.unpack_from("<H", b, _L_S2_MS)[0]
        s2_min   = b[_L_S2_MIN]
        delta_ahead_ms  = struct.unpack_from("<H", b, _L_DELTA_AHEAD_MS)[0]
        delta_ahead_min = b[_L_DELTA_AHEAD_MIN]
        lap_dist        = struct.unpack_from("<f", b, _L_LAP_DISTANCE)[0]
        pos             = b[_L_CAR_POS]
        lap_num         = b[_L_LAP_NUM]
        pit_status      = b[_L_PIT_STATUS]
        num_pit_stops   = b[_L_NUM_PIT_STOPS]
        sector          = b[_L_SECTOR]
        invalid         = bool(b[_L_INVALID])
        driver_status   = b[_L_DRIVER_STATUS]
        result_status   = b[_L_RESULT_STATUS]

        gap_ahead = delta_ahead_min * 60.0 + delta_ahead_ms / 1000.0

        sector1 = s1_min * 60.0 + s1_ms / 1000.0 if (s1_ms or s1_min) else 0.0
        sector2_raw = s2_min * 60.0 + s2_ms / 1000.0 if (s2_ms or s2_min) else 0.0
        # sector2_time in TelemetryData = cumulative time at end of S2
        sector2 = sector1 + sector2_raw if sector1 > 0 and sector2_raw > 0 else 0.0

        # ── Sector flag tracking (UDP thread only — no lock needed) ──────────
        sector_int  = int(sector)
        lap_num_int = int(lap_num)
        last        = _ms_to_s(last_ms)
        curr        = _ms_to_s(curr_ms)

        # Pit lane / garage transitions — suppress delta and recording while in pits.
        # The reference lap is deliberately NOT cleared so it survives garage visits.
        if self._prev_pit_status == 0 and pit_status != 0:
            self._delta_tracker.discard_profile()
            self._current_delta   = 0.0
            self._delta_print_dist = 0.0
            log.info(f"Entered pits (status={pit_status}) at dist={lap_dist:.0f}m — recording paused")
        elif self._prev_pit_status != 0 and pit_status == 0:
            self._delta_tracker.discard_profile()
            self._current_delta   = 0.0
            self._delta_print_dist = 0.0
            log.info(f"Exited pits — recording and delta reset")

        # Rewind / flashback detection — skip while in pit lane (lap_dist is unreliable there)
        if lap_num_int < self._prev_lap_num:
            self._delta_tracker.discard_profile()
        elif (pit_status == 0
              and lap_num_int == self._prev_lap_num
              and self._delta_tracker.trim_flashback(lap_dist)):
            # Within-lap flashback: lap_dist jumped backwards; the tracker trimmed
            # the profile to points before the rewind position.
            self._current_delta = 0.0
            log.info(f"Flashback detected at dist={lap_dist:.0f}m: "
                  f"profile trimmed to {self._delta_tracker.profile_points} pts")

        s1_flag = s2_flag = s3_flag = None  # None = no change

        if self._prev_sector == 0 and sector_int == 1 and sector1 > 0 and pit_status == 0:
            # Sector-boundary delta (baseline — overridden by live interpolation when ready)
            if self._best_s1 > 0:
                self._current_delta = sector1 - self._best_s1
            is_pb = self._best_s1 == 0 or sector1 < self._best_s1
            s1_flag = "purple" if is_pb else "green"
            if is_pb:
                self._best_s1 = sector1

        if self._prev_sector == 1 and sector_int == 2 and pit_status == 0:
            s2_standalone = sector2_raw
            if s2_standalone > 0:
                if self._best_s2 > 0:  # only once we have a previous S2 to compare against
                    best_cum = self._best_s1 + self._best_s2
                    self._current_delta = sector2 - best_cum
                is_pb = self._best_s2 == 0 or s2_standalone < self._best_s2
                s2_flag = "purple" if is_pb else "green"
                if is_pb:
                    self._best_s2 = s2_standalone

        lap_completed = lap_num_int > self._prev_lap_num > 0 and last >= 1.0
        if lap_num_int > self._prev_lap_num > 0:
            log.info(f"Lap {self._prev_lap_num}→{lap_num_int}: last={last:.3f}s "
                  f"profile_pts={self._delta_tracker.profile_points} pit_stops={num_pit_stops} "
                  f"pit_status={pit_status} completed={lap_completed}")
        finished_profile = None
        if lap_completed:
            s3 = last - sector2 if sector2 > 0 and last > sector2 else 0.0
            if s3 > 0:
                is_pb = self._best_s3 == 0 or s3 < self._best_s3
                s3_flag = "purple" if is_pb else "green"
                if is_pb:
                    self._best_s3 = s3
            # Swap lap profiles: save completed lap, start fresh
            finished_profile       = self._delta_tracker.finish_lap()
            self._delta_print_dist = 0.0

        self._prev_sector     = sector_int
        self._prev_lap_num    = lap_num_int
        self._prev_pit_status = pit_status

        # Record current position to lap profile (down-sampled every 5 m)
        if lap_dist > 0 and curr > 0 and pit_status == 0:
            if self._delta_tracker.record_point(lap_dist, curr) and self._debug:
                log.debug(f"Lap profile recording started: dist={lap_dist:.1f} m, curr={curr:.3f} s")
        elif self._delta_tracker.profile_points == 0 and lap_dist <= 0 and curr > 0:
            # lap_dist is 0 / negative — offset may be wrong; log once per lap
            if not hasattr(self, '_lap_dist_warned'):
                self._lap_dist_warned = True
                log.warning(f"lap_dist={lap_dist!r} — offset {_L_LAP_DISTANCE} may be wrong; live delta disabled")

        # Live delta: interpolate reference lap at current track distance.
        # Overrides the sector-boundary baseline above when the reference has
        # coverage at this distance.
        if lap_dist > 0 and curr > 0 and pit_status == 0 and not lap_completed:
            live = self._delta_tracker.live_delta(lap_dist, curr)
            if live is not None:
                self._current_delta = live
                if self._debug:
                    milestone = int(lap_dist // 500) * 500
                    if milestone > 0 and milestone != self._delta_print_dist:
                        self._delta_print_dist = milestone
                        log.debug(f"δ@{milestone}m: curr={curr:.3f}s "
                              f"ref={curr - live:.3f}s Δ={live:+.3f}s")
        # ────────────────────────────────────────────────────────────────────

        # ── All-car scan: update qualifying leaderboard + gap behind ─────────────
        player_pos = int(pos)
        gap_behind = 0.0
        idx_ahead = idx_behind = None
        num_slots = min((len(data) - _HEADER_SIZE) // _LAP_CAR_SIZE, 24)
        for car_idx in range(num_slots):
            c_start = _HEADER_SIZE + car_idx * _LAP_CAR_SIZE
            if c_start + _LAP_CAR_SIZE > len(data):
                break
            cb = data[c_start:]
            c_last_ms = struct.unpack_from("<I", cb, _L_LAST_LAP_MS)[0]
            c_pos     = cb[_L_CAR_POS]
            c_lap_num = cb[_L_LAP_NUM]
            if player_pos > 1 and int(c_pos) == player_pos - 1:
                idx_ahead = car_idx
            # Car immediately behind the player reports the gap to us as their gap_ahead
            if int(c_pos) == player_pos + 1:
                idx_behind  = car_idx
                c_delta_ms  = struct.unpack_from("<H", cb, _L_DELTA_AHEAD_MS)[0]
                c_delta_min = cb[_L_DELTA_AHEAD_MIN]
                gap_behind  = c_delta_min * 60.0 + c_delta_ms / 1000.0
            if c_pos > 0:
                self._car_positions[car_idx] = int(c_pos)

            prev_lap = self._car_lap_numbers.get(car_idx)
            self._car_lap_numbers[car_idx] = c_lap_num

            # A backwards lap number (garage return between quali runs, flashback)
            # does NOT invalidate already-completed bests — those laps still stand.
            # Genuine session restarts change m_sessionUID, which clears these
            # caches wholesale, so no per-car discard is needed here.
            if prev_lap is not None and c_lap_num > prev_lap and prev_lap > 0:
                # Lap number incremented from a non-zero base — genuine completion
                # in the current session, but only if lastLapTimeMs actually changed:
                # after a garage return the game rewinds the player's lap counter and
                # re-advances it while the car sits still, and recording here again
                # would store the stale in-lap time as a fresh lap.
                if c_last_ms != self._car_last_ms.get(car_idx):
                    self._car_last_ms[car_idx] = c_last_ms
                    c_last_s = _ms_to_s(c_last_ms)
                    if 30.0 < c_last_s < 600.0:
                        prev_best = self._car_best_laps.get(car_idx, 0.0)
                        if prev_best == 0.0 or c_last_s < prev_best:
                            self._car_best_laps[car_idx] = c_last_s
            # If prev_lap is None (first packet seen for this car in this session),
            # skip c_last_ms entirely — it carries the stale time from the previous
            # session or from before a restart.

        # Build sorted participant list for the dashboard
        parts = self._build_participants()

        with self._lock:
            d = self._data
            best = d.best_lap
            if lap_completed and best > 0:
                self._current_delta = last - best
            if lap_completed and last > 0 and (best == 0 or last < best):
                best = last
                # Quality gating (start ≤200 m, ≥50 points) lives in the tracker;
                # a rejected profile also clears the old reference.
                if self._delta_tracker.set_reference(finished_profile):
                    fp_start = finished_profile[0][0]
                    fp_end   = finished_profile[-1][0]
                    fp_pts   = len(finished_profile)
                    log.info(f"Reference lap saved: {fp_pts} points, "
                          f"dist {fp_start:.0f}–{fp_end:.0f} m")
                    if self._debug:
                        sample_parts = []
                        sample_d = 1000.0
                        while sample_d < fp_end:
                            sample_parts.append(f"t({sample_d:.0f}m)={interpolate_profile(finished_profile, sample_d):.3f}s")
                            sample_d += 1000.0
                        sample_parts.append(f"t({fp_end:.0f}m)={finished_profile[-1][1]:.3f}s")
                        log.debug(f"Reference times: {', '.join(sample_parts)}")
                        max_gap = 0.0
                        max_gap_start = 0.0
                        for i in range(1, len(finished_profile)):
                            gap = finished_profile[i][0] - finished_profile[i - 1][0]
                            if gap > max_gap:
                                max_gap = gap
                                max_gap_start = finished_profile[i - 1][0]
                        if max_gap > 10.0:
                            log.debug(f"Reference largest gap: {max_gap:.0f}m starting at dist={max_gap_start:.0f}m")
                elif self._debug:
                    if finished_profile:
                        log.debug(f"Reference cleared (new best but profile rejected:"
                              f" start={finished_profile[0][0]:.0f} m, pts={len(finished_profile)})")
                    else:
                        log.debug("Reference cleared (new best but profile was empty)")

            d.last_lap = last
            d.lap_time = curr
            d.lap_invalid = invalid
            d.best_lap = best
            d.delta = self._current_delta
            d.position = int(pos)
            d.gap_ahead = gap_ahead
            d.gap_behind = gap_behind
            d.name_ahead  = self._car_names.get(idx_ahead,  "") if idx_ahead  is not None else ""
            d.name_behind = self._car_names.get(idx_behind, "") if idx_behind is not None else ""
            d.lap_number = lap_num_int
            d.lap_distance = lap_dist
            d.in_pits = pit_status != 0
            d.driver_status = int(driver_status)
            d.finish_status = _RESULT_STATUS_MAP.get(result_status, "")
            d.corner_cut_warnings = int(b[_L_CORNER_CUT_WARN])
            d.sector = sector_int
            d.sector1_time = sector1
            d.sector2_time = sector2
            d.participants = parts
            if s1_flag is not None:
                d.sector1_flag = s1_flag
            if s2_flag is not None:
                d.sector2_flag = s2_flag
            if s3_flag is not None:
                d.sector3_flag = s3_flag

    def _parse_event(self, data: bytes):
        """Packet 3 — incident events. Only events involving the player are
        kept; each is stamped with the player's current lap time and distance
        so it can later be placed on a track map."""
        if len(data) < _EVT_PAYLOAD_OFFSET:
            return
        code = data[_EVT_CODE_OFFSET:_EVT_CODE_OFFSET + 4].decode("ascii", "ignore")
        if code not in ("COLL", "OVTK", "PENA"):
            return
        p = _EVT_PAYLOAD_OFFSET
        player = self._player_idx

        event_type = detail = None
        if code == "COLL" and len(data) >= p + 2:
            v1, v2 = data[p], data[p + 1]
            if player in (v1, v2):
                other = v2 if v1 == player else v1
                event_type = "collision"
                detail = self._car_names.get(other, f"CAR {other + 1}")
        elif code == "OVTK" and len(data) >= p + 2:
            overtaker, overtaken = data[p], data[p + 1]
            if overtaker == player:
                event_type = "overtake"
                detail = self._car_names.get(overtaken, f"CAR {overtaken + 1}")
            elif overtaken == player:
                event_type = "overtaken"
                detail = self._car_names.get(overtaker, f"CAR {overtaker + 1}")
        elif code == "PENA" and len(data) >= p + 7:
            penalty, infringement, vehicle, other = data[p], data[p + 1], data[p + 2], data[p + 3]
            if vehicle == player:
                event_type = "penalty"
                detail = (f"{_PENALTY_TYPES.get(penalty, f'penalty_{penalty}')}"
                          f":{_INFRINGEMENT_TYPES.get(infringement, f'infringement_{infringement}')}")
                if other != 255 and other != player:
                    detail += f":{self._car_names.get(other, f'CAR {other + 1}')}"

        if event_type is None:
            return
        with self._lock:
            d = self._data
            ev = {
                "type":     event_type,
                "detail":   detail,
                "lap_num":  d.lap_number,
                "lap_time": d.lap_time,
                "distance": d.lap_distance,
            }
            self._pending_events.append(ev)
        log.info(f"Event {ev['type']}: {ev['detail']} (lap {ev['lap_num']}, "
                 f"t={ev['lap_time']:.1f}s, dist={ev['distance']:.0f}m)")

    def _build_participants(self) -> list:
        """Sorted per-car snapshot for dashboards and the session logger."""
        parts: list = []
        for car_idx, c_pos in self._car_positions.items():
            parts.append({
                "position":    c_pos,
                "name":        self._car_names.get(car_idx, f"CAR {car_idx + 1}"),
                "best_lap":    self._car_best_laps.get(car_idx, 0.0),
                "race_number": self._car_race_numbers.get(car_idx, 0),
                "race_time":   self._car_race_times.get(car_idx, 0.0),
                "team_colour": self._car_colours.get(car_idx),
            })
        parts.sort(key=lambda p: p["position"])
        return parts

    def _parse_final_classification(self, data: bytes):
        """Packet 8 — final standings with total race times, sent at session end."""
        if len(data) < _HEADER_SIZE + 1:
            return
        num_cars   = data[_HEADER_SIZE]
        body_bytes = len(data) - _HEADER_SIZE - 1
        if num_cars == 0 or body_bytes <= 0:
            return
        if body_bytes % _FINAL_CAR_SIZE_V46 == 0:
            car_size, best_off, time_off, pen_off = _FINAL_CAR_SIZE_V46, 7, 11, 19
        elif body_bytes % _FINAL_CAR_SIZE_V45 == 0:
            car_size, best_off, time_off, pen_off = _FINAL_CAR_SIZE_V45, 6, 10, 18
        else:
            log.warning(f"Unknown final classification packet size: len={len(data)}, body={body_bytes}")
            return
        array_slots = body_bytes // car_size

        for car_idx in range(min(num_cars, array_slots)):
            cs       = _HEADER_SIZE + 1 + car_idx * car_size
            position = data[cs]
            status   = data[cs + 5]
            best_ms  = struct.unpack_from("<I", data, cs + best_off)[0]
            total_s  = struct.unpack_from("<d", data, cs + time_off)[0]
            pen_s    = data[cs + pen_off]
            # Classification is authoritative — override the live-scan values.
            if position > 0:
                self._car_positions[car_idx] = int(position)
            if 0 < best_ms < 600_000:
                self._car_best_laps[car_idx] = _ms_to_s(best_ms)
            if status == _FINAL_STATUS_FINISHED and total_s > 0:
                # totalRaceTime excludes penalties; the classified time includes them
                self._car_race_times[car_idx] = round(total_s + pen_s, 3)

        log.info(f"Final classification: {num_cars} cars, "
                 f"{len(self._car_race_times)} finished with race times")
        # Publish immediately — lap packets may stop once the session is over,
        # so waiting for the next _parse_lap would lose the final standings.
        parts = self._build_participants()
        with self._lock:
            self._data.participants = parts
            self._data.classification_received = True

    def _parse_status(self, data: bytes, idx: int):
        if idx >= 24:  # 24-slot My Career grids; bounds check below guards short packets
            return
        is_2026 = self._packet_format >= _PACKET_FORMAT_2026
        car_size = _STS_CAR_SIZE_2026 if is_2026 else _STS_CAR_SIZE_2025
        ers_deployed_offset = _S_ERS_DEPLOYED_2026 if is_2026 else _S_ERS_DEPLOYED_2025

        car_start = _HEADER_SIZE + idx * car_size
        if car_start + car_size > len(data):
            return

        b = data[car_start:]
        tc = b[_S_TC]
        abs_lvl = b[_S_ABS]
        pit_limiter = bool(b[_S_PIT_LIMITER])
        fuel = struct.unpack_from("<f", b, _S_FUEL_TANK)[0]
        fuel_cap = struct.unpack_from("<f", b, _S_FUEL_CAP)[0]
        fuel_laps = struct.unpack_from("<f", b, _S_FUEL_LAPS)[0]
        max_rpm = struct.unpack_from("<H", b, _S_MAX_RPM)[0]
        drs_allowed = bool(b[_S_DRS_ALLOWED])
        visual_tyre = b[_S_VISUAL_TYRE]
        ers_energy_j = struct.unpack_from("<f", b, _S_ERS_ENERGY)[0]
        ers_mode = b[_S_ERS_MODE]
        ers_harv = struct.unpack_from("<f", b, _S_ERS_HARV_MGUK)[0]
        ers_depl = struct.unpack_from("<f", b, ers_deployed_offset)[0]

        ers_pct = max(0.0, min(1.0, ers_energy_j / _ERS_MAX_JOULES))
        tyre_compound = _VISUAL_TYRE.get(visual_tyre, "")

        fia_flag = _F1_FLAG_MAP.get(struct.unpack_from("<b", b, _S_FIA_FLAGS)[0], "")

        with self._lock:
            d = self._data
            d.tc_level = int(tc)
            d.abs_level = int(abs_lvl)
            d.pit_limiter = pit_limiter
            d.fuel_remaining = max(0.0, fuel)
            d.fuel_capacity = max(1.0, fuel_cap)
            d.fuel_laps_remaining = max(0.0, fuel_laps)
            if max_rpm > 0:
                d.max_rpm = int(max_rpm)
            d.drs_available = drs_allowed
            d.tyre_compound = tyre_compound
            d.ers_stored_energy = round(ers_pct, 3)
            d.ers_deploy_mode = int(ers_mode)
            d.ers_harvested_lap = max(0.0, ers_harv)
            d.ers_deployed_lap = max(0.0, ers_depl)
            d.flag = fia_flag

    def _parse_telemetry2(self, data: bytes, idx: int):
        """Packet 16 — F1 2026 DLC: Active Aero + Boost (MOR) per car."""
        car_start = _HEADER_SIZE + idx * _TELEM2_CAR_SIZE
        if car_start + _TELEM2_CAR_SIZE > len(data):
            return

        b = data[car_start:]
        aero_mode_raw  = b[_T2_AERO_MODE]
        aero_available = bool(b[_T2_AERO_AVAIL])
        boost_available = bool(b[_T2_OVT_AVAIL])
        boost_active   = bool(b[_T2_OVT_ACTIVE])
        is_2026        = bool(b[_T2_2026_REGS])

        aero_mode = "straight" if aero_mode_raw == 1 else "corner"

        with self._lock:
            d = self._data
            d.active_aero_mode = aero_mode
            d.active_aero_available = aero_available
            d.boost_active = boost_active
            if is_2026 and d.car_class != "formula1_2026":
                d.car_class = "formula1_2026"
            elif not is_2026 and d.car_class == "formula1_2026":
                d.car_class = "formula1"

    def _parse_participants(self, data: bytes):
        """Packet 4 — extract driver names, race numbers and livery colours."""
        if len(data) < _HEADER_SIZE + 1:
            return

        num_active = data[_HEADER_SIZE]
        if num_active == 0:
            return

        # Detect struct version from packet body size — the two sizes never produce
        # the same quotient for realistic slot counts, so modulo is unambiguous.
        body_bytes = len(data) - _HEADER_SIZE - 1
        if body_bytes % _PART_CAR_SIZE_V2 == 0:
            car_size    = _PART_CAR_SIZE_V2
            name_len    = 32
            has_colours = True
        elif body_bytes % _PART_CAR_SIZE_V1 == 0:
            car_size    = _PART_CAR_SIZE_V1
            name_len    = 48
            has_colours = False
        else:
            if not getattr(self, '_part_warned', False):
                self._part_warned = True
                if self._debug:
                    log.debug(f"[F1 PART] Unknown packet size: len={len(data)}, body={body_bytes}")
            return

        array_slots = body_bytes // car_size

        # V1_24: 24-slot My Career packets (empirically: name at offset 10, not 7)
        # V1_22: 22-slot standard packets (name at offset 7, per F1 24 spec)
        # V2:    57-byte post-patch packets (name at offset 7, per F1 25 v3 spec)
        if car_size == _PART_CAR_SIZE_V1 and array_slots == 24:
            name_offset      = 10   # empirically confirmed from live packet dump
            has_race_num     = False  # race number offset TBD for this variant
        elif car_size == _PART_CAR_SIZE_V2:
            name_offset      = 7
            has_race_num     = True
        else:
            name_offset      = 7    # V1_22 (F1 24 standard)
            has_race_num     = True

        # One-time diagnostic — raw hex of the first few full car structs so the
        # actual layout can be verified empirically (e.g. the V1_24 raceNumber
        # offset is still TBD — match known driver numbers against these bytes).
        if self._debug and not getattr(self, '_part_logged', False):
            self._part_logged = True
            log.debug(f"[F1 PART] len={len(data)}, num_active={num_active}, "
                  f"array_slots={array_slots}, car_size={car_size}, "
                  f"name_offset={name_offset}, has_colours={has_colours}, "
                  f"player_idx={self._player_idx}")
            for ci in range(min(4, array_slots)):
                cs = _HEADER_SIZE + 1 + ci * car_size
                raw_hex = ' '.join(f'{b:02x}' for b in data[cs:cs + car_size])
                log.debug(f"[F1 PART]   car{ci} bytes[0:{car_size}]: {raw_hex}")
                n_raw = data[cs + name_offset: cs + name_offset + 16]
                n_str = n_raw.split(b'\x00')[0].decode('utf-8', errors='replace')
                n_str = ''.join(c if c.isprintable() else f'\\x{ord(c):02x}' for c in n_str)
                log.debug(f"[F1 PART]   car{ci} name@{name_offset}: {n_str!r}")

        # teamId: uint8 at offset 3 in V1_22 and V2. In V1_24 the 2026 Season
        # Pack widened it to uint16 LE at offset 5 (2026 ids are 476–486, so
        # the "always 0x01" byte 6 in observed dumps is the high byte).
        team_id_is_u16 = (car_size == _PART_CAR_SIZE_V1 and array_slots == 24)
        player_team = ""
        player_name = ""
        player_team_id = -1

        for car_idx in range(min(num_active, array_slots)):
            car_start = _HEADER_SIZE + 1 + car_idx * car_size
            if car_start + car_size > len(data):
                break

            # Race number — only where the offset is known to be correct.
            # For V1_24 (24-slot My Career) the offset is TBD; skip to avoid garbage.
            if has_race_num:
                race_num = data[car_start + _PART_RACE_NUM_OFFSET]
                if 0 < race_num <= 99:   # sanity-check: F1 race numbers are 1–99
                    self._car_race_numbers[car_idx] = int(race_num)

            # Driver name
            raw  = data[car_start + name_offset: car_start + name_offset + name_len]
            name = raw.split(b'\x00')[0].decode('utf-8', errors='replace').strip()
            if name:
                self._car_names[car_idx] = name
            elif car_idx == self._player_idx:
                # F1 2025 leaves the player's own name field empty; use a placeholder.
                self._car_names[car_idx] = "YOU"

            # Capture player's name and team
            if car_idx == self._player_idx:
                player_name = name   # actual parsed name ("PIASTRI") or "" if packet was empty
                if team_id_is_u16:
                    team_id = struct.unpack_from("<H", data, car_start + 5)[0]
                else:
                    team_id = data[car_start + 3]
                player_team = _TEAM_ID_MAP.get(team_id, "")
                player_team_id = int(team_id)
                # Unmapped ids (e.g. the 2026 Season Pack teams) are logged at
                # INFO — the Pi runs without --debug, and the raw id is the only
                # way to grow _TEAM_ID_MAP from real sessions.
                if not player_team and team_id != self._unmapped_team_logged:
                    self._unmapped_team_logged = team_id
                    log.info(f"[F1 PART] player team_id={team_id} has no name mapping "
                             f"(car_size={car_size}, slots={array_slots}, "
                             f"name={name!r}) — add it to _TEAM_ID_MAP")

            # Livery colours (V2 only)
            if has_colours:
                num_colours = data[car_start + _PART_COLOUR_OFFSET]
                if num_colours > 0:
                    c_start = car_start + _PART_COLOUR_OFFSET + 1
                    self._car_colours[car_idx] = (
                        data[c_start],
                        data[c_start + 1],
                        data[c_start + 2],
                    )

        if player_team or player_name or player_team_id >= 0:
            with self._lock:
                d = self._data
                if player_team:
                    d.car_name = player_team
                if player_name:
                    d.driver_name = player_name
                if player_team_id >= 0:
                    d.team_id_raw = player_team_id

    def _parse_session(self, data: bytes):
        if len(data) < _HEADER_SIZE + _SES_RACING_LINE + 1:
            return

        session_int = data[_HEADER_SIZE + _SES_SESSION_TYPE]
        session_type = _SESSION_MAP.get(session_int, "race")
        session_subtype = _SESSION_SUBTYPE_MAP.get(session_int, "")
        if session_int != self._prev_session_int:
            self._prev_session_int = session_int
            sub = f" ({session_subtype})" if session_subtype else ""
            log.info(f"Session type raw={session_int} → {session_type}{sub}")

        track_id_raw = struct.unpack_from("<b", data, _HEADER_SIZE + _SES_TRACK_ID)[0]
        track = _TRACK_ID_MAP.get(track_id_raw, "")

        formula_int = data[_HEADER_SIZE + _SES_FORMULA]
        car_class = _FORMULA_CLASS.get(formula_int, "formula1")

        total_laps = data[_HEADER_SIZE + _SES_TOTAL_LAPS]

        time_left = struct.unpack_from('<H', data, _HEADER_SIZE + _SES_TIME_LEFT)[0]
        game_paused = bool(data[_HEADER_SIZE + _SES_GAME_PAUSED])

        # When the game resumes from pause, discard the current lap profile.
        # While paused, m_currentLapTimeMs keeps ticking but m_lapDistance is frozen.
        # The first profile point recorded after unpausing would have an inflated curr
        # (pause duration baked in), corrupting the reference if this lap sets a PB.
        if self._game_paused and not game_paused:
            self._delta_tracker.discard_profile()
            if self._debug:
                log.debug("Game resumed — lap profile reset (pause may have inflated curr)")
        self._game_paused = game_paused

        sc_raw = data[_HEADER_SIZE + _SES_SAFETY_CAR]
        safety_car = _F1_SC_MAP.get(sc_raw, "")

        weather = _WEATHER_MAP.get(data[_HEADER_SIZE + _SES_WEATHER], "")
        track_temp = struct.unpack_from("<b", data, _HEADER_SIZE + _SES_TRACK_TEMP)[0]
        air_temp = struct.unpack_from("<b", data, _HEADER_SIZE + _SES_AIR_TEMP)[0]

        steering_assist = data[_HEADER_SIZE + _SES_STEERING_ASSIST]
        braking_assist = data[_HEADER_SIZE + _SES_BRAKING_ASSIST]
        gearbox_assist = data[_HEADER_SIZE + _SES_GEARBOX_ASSIST]
        pit_assist = data[_HEADER_SIZE + _SES_PIT_ASSIST]
        pit_release_assist = data[_HEADER_SIZE + _SES_PIT_RELEASE_ASSIST]
        ers_assist = data[_HEADER_SIZE + _SES_ERS_ASSIST]
        drs_assist = data[_HEADER_SIZE + _SES_DRS_ASSIST]
        racing_line_assist = data[_HEADER_SIZE + _SES_RACING_LINE]

        with self._lock:
            d = self._data
            # Don't let session packet downgrade 2026 detection from telemetry2 packets
            if d.car_class == "formula1_2026" and car_class == "formula1":
                car_class = d.car_class

            # Only reset when transitioning between two *known* session types.
            # Excludes "" (initial) and "unknown" (sent during loading screens) so
            # that transient packets between sessions don't clear a valid best lap.
            _KNOWN = {"practice", "qualifying", "race", "hotlap"}
            session_changed = (session_type in _KNOWN
                               and d.session_type in _KNOWN
                               and session_type != d.session_type)
            if session_changed:
                log.info(f"Session changed: {d.session_type!r} → {session_type!r} — resetting lap state")
                self._reset_player_lap_state()
                self._reset_session_caches()

            d.session_type = session_type
            d.session_subtype = session_subtype
            d.session_type_raw = int(session_int)
            d.car_class = car_class
            d.track = track
            d.total_laps = int(total_laps)
            d.game = "f1_25"
            d.safety_car = safety_car
            d.session_time_remaining = float(time_left)
            d.game_paused = game_paused
            d.weather = weather
            d.track_temp = float(track_temp)
            d.air_temp = float(air_temp)
            d.steering_assist = int(steering_assist)
            d.braking_assist = int(braking_assist)
            d.gearbox_assist = int(gearbox_assist)
            d.pit_assist = int(pit_assist)
            d.pit_release_assist = int(pit_release_assist)
            d.ers_assist = int(ers_assist)
            d.drs_assist = int(drs_assist)
            d.racing_line_assist = int(racing_line_assist)
            if session_changed:
                d.best_lap = 0.0
                d.last_lap = 0.0
                d.delta = 0.0
                d.finish_status = ""
                d.classification_received = False
