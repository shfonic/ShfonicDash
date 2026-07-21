# Project CARS 2 UDP Telemetry Reference

Applies to: Project CARS 2 (Slightly Mad Studios).

Reference source: [MacManley/project-cars-2-udp](https://github.com/MacManley/project-cars-2-udp) (C++ header files, `#pragma pack(push,1)`). Cross-checked against observed packet sizes.

---

## In-Game Setup

Options → Visual → HUD → UDP Race Data: On  
UDP Data Port: **5606**  
UDP Frequency: **1** (lowest value = most frequent packets — the scale is inverted; 1 sends fastest, 10 sends slowest)  
UDP Protocol Version: **Project CARS 2** (not "Project CARS 1" — different header layout, packet types will be misidentified)

Project CARS 2 broadcasts to the LAN broadcast address automatically — no IP configuration required. All devices on the same network will receive the packets.

---

## Protocol Overview

PCARS2 uses a fragmented UDP protocol. A single logical "frame" may be split across multiple UDP datagrams using a partial-packet mechanism. The 12-byte header identifies the packet type and fragmentation state. All structs are **packed** (no alignment padding).

### Packet header (12 bytes, every packet)

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 0 | U32 | `mPacketNumber` | Monotonically increasing packet counter |
| 4 | U32 | `mCategoryPacketNumber` | Per-type packet counter |
| 8 | U8 | `mPartialPacketIndex` | Fragment index (0-based) for split packets |
| 9 | U8 | `mPartialPacketNumber` | Total fragments for this logical packet |
| 10 | U8 | `mPacketType` | Identifies the packet type (see below) |
| 11 | U8 | `mPacketVersion` | Protocol version |

`mPacketType` is at **byte offset 10** in the raw buffer. Offset 8 is `mPartialPacketIndex` — a common mistake that causes all packets to be misidentified as type 0 (`eCarPhysics`).

---

## Packet Types

| ID | Name | Used | Notes |
|----|------|------|-------|
| 0 | `eCarPhysics` | ✓ | Primary data: gear, speed, RPM, throttle, brake, tyres, fuel |
| 1 | `eRaceDefinition` | ✓ | Personal best lap & sector times, total lap count |
| 2 | `eParticipants` | — | Driver names, car/class names (up to 32 participants) |
| 3 | `eTimings` | ✓ | Session timing: event time remaining, gaps, per-participant lap/sector/position data |
| 4 | `eGameState` | ✓ | Game state flags, session state (used for session type detection) |
| 5 | `eWeatherState` | — | Per-zone weather, ambient and track temperatures |
| 6 | `eVehicleNames` | — | Class name and vehicle name strings |
| 7 | `eTimeStats` | — | Per-participant full lap and sector time history |
| 8 | `eParticipantVehicleNames` | ✓ | Vehicle name, class name, tyre name per participant — parsed for car class auto-detection |

---

## Packet 0 — eCarPhysics

The primary real-time data packet. Sent at the configured UDP rate. Full struct is ~556 bytes.

Reference: [CarPhysicsPacket.java](https://github.com/ralfhergert/pc2-telemetry/blob/master/src/main/java/de/ralfhergert/telemetry/pc2/datagram/v2/CarPhysicsPacket.java)

### Complete field table

| Byte offset | Type | Field | Used | Notes |
|-------------|------|-------|------|-------|
| 12 | S8 | `viewedParticipantIndex` | ✓ | Index of participant currently viewed (player or spectated) |
| 13 | U8 | `unfilteredThrottle` | — | Raw throttle 0–255 |
| 14 | U8 | `unfilteredBrake` | — | Raw brake 0–255 |
| 15 | S8 | `unfilteredSteering` | — | Raw steering –127 to +127 |
| 16 | U8 | `unfilteredClutch` | — | Raw clutch 0–255 |
| 17 | U8 | `carFlags` | — | Bitmask: headlights, engine on, speed limiter, ABS, handbrake |
| 18 | S16 | `oilTempCelsius` | — | |
| 20 | U16 | `oilPressureKPa` | — | |
| 22 | S16 | `waterTempCelsius` | — | |
| 24 | U16 | `waterPressureKpa` | — | |
| 26 | U16 | `fuelPressureKpa` | — | |
| 28 | U8 | `fuelCapacity` | ✓ | Tank capacity (litres) |
| 29 | U8 | `brake` | ✓ | Filtered brake 0–255 (auto-normalised to 0.0–1.0) |
| 30 | U8 | `throttle` | ✓ | Filtered throttle 0–255 (auto-normalised to 0.0–1.0) |
| 31 | U8 | `clutch` | — | Clutch 0–255 |
| 32 | F32 | `fuelLevel` | ✓ | Fuel as fraction of capacity (0.0–1.0) |
| 36 | F32 | `speed` | ✓ | m/s; multiply × 3.6 for km/h |
| 40 | U16 | `rpm` | ✓ | Current RPM |
| 42 | U16 | `maxRpm` | ✓ | Rev limit |
| 44 | S8 | `steering` | ✓ | –127 to +127; divide by 127 for –1.0 to +1.0 |
| 45 | U8 | `gearNumGears` | ✓ | Lower nibble = current gear index; upper nibble = total gears |
| 46 | U8 | `boostAmount` | — | |
| 47 | U8 | `crashState` | — | |
| 48 | F32 | `odometerKM` | — | |
| 52 | F32×3 | `orientation` | — | X/Y/Z rotation (rad) |
| 64 | F32×3 | `localVelocity` | — | X/Y/Z local velocity (m/s) |
| 76 | F32×3 | `worldVelocity` | — | X/Y/Z world velocity (m/s) |
| 88 | F32×3 | `angularVelocity` | — | X/Y/Z angular velocity (rad/s) |
| 100 | F32×3 | `localAcceleration` | — | X/Y/Z local acceleration (m/s²) |
| 112 | F32×3 | `worldAcceleration` | — | X/Y/Z world acceleration (m/s²) |
| 124 | F32×3 | `extentsCentre` | — | X/Y/Z extents centre |
| 136 | U8×4 | `tyreFlags` | — | Per-wheel bitmask |
| 140 | U8×4 | `terrain` | — | Per-wheel surface type |
| 144 | F32×4 | `tyreY` | — | Per-wheel vertical displacement |
| 160 | F32×4 | `tyreRPS` | — | Per-wheel revolutions per second |
| 176 | U8×4 | `tyreTemp` | — | Per-wheel surface temp (°C) |
| 180 | F32×4 | `tyreHeightAboveGround` | — | Per-wheel height (m) |
| 196 | U8×4 | `tyreWear` | ✓ | Per-wheel wear 0–255 → 0.0–1.0; FL/FR/RL/RR |
| 200 | U8×4 | `brakeDamage` | — | Per-wheel brake damage 0–255 |
| 204 | U8×4 | `suspensionDamage` | — | Per-wheel suspension damage 0–255 |
| 208 | S16×4 | `brakeTempCelsius` | — | Per-wheel brake temperature (°C) |
| 216 | S16×4 | `tyreTreadTemp` | ✓ | Per-wheel tread temperature (Kelvin); subtract 273.15 for °C; FL/FR/RL/RR |
| 224 | S16×4 | `tyreLayerTemp` | — | Per-wheel layer temperature (K) |
| 232 | S16×4 | `tyreCarcassTemp` | — | Per-wheel carcass temperature (K) |
| 240 | S16×4 | `tyreRimTemp` | — | Per-wheel rim temperature (K) |
| 248 | S16×4 | `tyreInternalAirTemp` | — | Per-wheel internal air temperature (K) |
| 256 | S16×4 | `tyreTempLeft` | — | Per-wheel left-zone temperature (K) |
| 264 | S16×4 | `tyreTempCenter` | — | Per-wheel centre-zone temperature (K) |
| 272 | S16×4 | `tyreTempRight` | — | Per-wheel right-zone temperature (K) |
| 280 | F32×4 | `wheelLocalPositionY` | — | Per-wheel local Y position |
| 296 | F32×4 | `rideHeight` | — | Per-wheel ride height (m) |
| 312 | F32×4 | `suspensionTravel` | — | Per-wheel suspension travel (m) |
| 328 | F32×4 | `suspensionVelocity` | — | Per-wheel suspension velocity (m/s) |
| 344 | U16×4 | `suspensionRideHeight` | — | Per-wheel suspension ride height |
| 352 | U16×4 | `airPressure` | ✓ | Per-wheel tyre pressure (PSI × 10); divide by 10; FL/FR/RL/RR |
| 360 | F32 | `engineSpeed` | — | Engine speed (rad/s) |
| 364 | F32 | `engineTorque` | — | Engine torque (Nm) |
| 368 | U8×2 | `wings` | — | Front/rear wing angle |
| 370 | U8 | `handBrake` | — | |
| 371 | U8 | `aeroDamage` | — | |
| 372 | U8 | `engineDamage` | — | |
| 376 | U32 | `joyPad0` | — | Controller input state (3 bytes padding before this field in C struct) |
| 380 | U8 | `dPad` | — | D-pad state |
| 381 | C×40×4 | `tyreCompound` | — | 4 × 40-byte compound name strings (FL/FR/RL/RR) |
| 538 | F32 | `turboBoostPressure` | — | Turbo boost (bar) |
| 542 | F32×3 | `fullPosition` | — | High-precision world position X/Y/Z |
| 554 | U8 | `brakeBias` | — | Brake bias (quantized) |

### Gear index encoding

```
GEAR_NAMES = ['N', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', 'R']
```

Gear index 0 = Neutral, index 15 = Reverse. Extract with `gear_byte & 0x0F`.

### Throttle/brake normalisation

Values arrive as either 0–255 (uint8) or 0.0–1.0 (float). The parser auto-detects:
- If `value > 1.5` and `value ≤ 255`: divide by 255
- If `value > 1.0`: divide by 100
- Otherwise: use as-is

### Car flags bitmask (`carFlags`)

| Bit | Meaning |
|-----|---------|
| 0 | Headlights |
| 1 | Engine active |
| 2 | Engine warning (oil/water temp) |
| 3 | Speed limiter (pit lane) |
| 4 | ABS active |
| 5 | Handbrake active |

---

## Packet 1 — eRaceDefinition

Contains static session information and the player's personal best times. Sent on session start and periodically thereafter.

| Field index | Byte offset | Field name | Type | Used | Notes |
|-------------|-------------|-----------|------|------|-------|
| 1 | 12 | `mTrackLength` | F32 | — | Track length (m) |
| 2 | 16 | `mPersonalFastestLapTime` | F32 | ✓ | Session personal best lap time (s); 0 = no lap complete |
| 3 | 20 | `mPersonalFastestSector1Time` | F32 | ✓ | Session best S1 (s) |
| 4 | 24 | `mPersonalFastestSector2Time` | F32 | ✓ | Session best S2 (s) |
| 5 | 28 | `mPersonalFastestSector3Time` | F32 | ✓ | Session best S3 (s) |
| 6 | 32 | `mWorldFastestLapTime` | F32 | — | Lobby/world best lap (s) |
| 7 | 36 | `mWorldFastestSector1Time` | F32 | — | Lobby/world best S1 (s) |
| 8 | 40 | `mWorldFastestSector2Time` | F32 | — | Lobby/world best S2 (s) |
| 9 | 44 | `mWorldFastestSector3Time` | F32 | — | Lobby/world best S3 (s) |
| 10 | 48 | `mTranslatedTrackLocation` | C×64 | — | Track location name |
| 11 | 112 | `mTranslatedTrackVariation` | C×64 | — | Track layout name |
| 12 | 176 | `mTranslatedTrackName` | C×64 | — | Full track name |
| 13 | 240 | `mTranslatedClassRecord` | C×64 | — | Class name |
| 14 | 304 | `mLapsInEvent` | U16 | ✓ | Total laps in event (race length); 0 = timed session |
| 15 | 306 | `mEnforcedPitStopLap` | S8 | — | Mandatory pit stop lap; –1 = none |

---

## Packet 3 — eTimings

Sent at a lower rate than eCarPhysics. Total packet size = **1063 bytes** (33-byte header + 32 × 32B participant slots + 6B tail).

### Timing header — 33 bytes

| Byte offset | Type | Field | Used | Notes |
|-------------|------|-------|------|-------|
| 0–11 | — | base header | — | Standard 12-byte header |
| 12 | S8 | `sNumParticipants` | ✓ | Active participant count (–1 to 32) |
| 13 | U32 | `sParticipantsChangedTimestamp` | — | Timestamp of last roster change |
| 17 | F32 | `sEventTimeRemaining` | ✓ | Time remaining in timed session (s); –1 = lap-based |
| 21 | F32 | `sSplitTimeAhead` | ✓ | Gap to car ahead (s) |
| 25 | F32 | `sSplitTimeBehind` | ✓ | Gap to car behind (s) |
| 29 | F32 | `sSplitTime` | — | Combined split difference |

Format: `'<12s b I f f f f'` = 33 bytes.

### Per-participant info struct — **32 bytes each**, starts at byte 33

Source: `PacketTimingsData.h` from MacManley/project-cars-2-udp, `#pragma pack(push,1)`.

| Struct offset | Type | Field | Used | Notes |
|---------------|------|-------|------|-------|
| 0 | S16×3 | `sWorldPosition[3]` | — | Low-precision world X/Y/Z |
| 6 | S16×3 | `sOrientation[3]` | — | X/Y/Z orientation (low precision) |
| 12 | U16 | `sCurrentLapDistance` | — | Distance into current lap (m) |
| 14 | U8 | `sRacePosition` | ✓ | Bits 0–6 = 1-based position; **bit 7 = participant active flag** |
| 15 | U8 | `sSector` | ✓ | Bits 0–1 = sector (0=S1, 1=S2, 2=S3); upper bits = position precision |
| 16 | U8 | `sHighestFlag` | — | Highest flag shown to this participant |
| 17 | U8 | `sPitModeSchedule` | — | Pit mode/schedule flags |
| 18 | U16 | `sCarIndex` | — | Car index |
| 20 | U8 | `sRaceState` | ✓ | Bits 0–2 = race state; **bit 3 = lap invalid flag** |
| 21 | U8 | `sCurrentLap` | ✓ | Current lap number (1-based) |
| 22 | F32 | `sCurrentTime` | ✓ | Running lap timer (s); resets at S/F crossing |
| 26 | F32 | `sCurrentSectorTime` | — | Running sector timer (s); resets on sector transition |
| 30 | U16 | `sMPParticipantIndex` | — | Multiplayer participant index |

Field total: 6+6+2+1+1+1+1+2+1+1+4+4+2 = **32 bytes** ✓  
Python format: `'<6h H 4B H 2B 2f H'`

### Packet tail — 6 bytes

After the 32 participant slots (at byte 33 + 32×32 = 1057):

| Offset from packet end | Type | Field | Notes |
|------------------------|------|-------|-------|
| `[-6:-4]` | U16 | `sLocalParticipantIndex` | Index of the local player's slot; use this to locate the player row |
| `[-4:]` | U32 | `TickCount` | Packet sequence counter |

Packet size check: 33 + 32 × 32 + 6 = **1063 bytes** ✓

### Key parsing notes

- **`sOrientation[3]` must not be omitted.** Earlier implementations missing these 6 bytes caused every subsequent field (position, lap, sector, time) to be read 6 bytes late, producing garbage values.
- **`sRacePosition` bit 7** is the "participant active" flag (MacManley header: *"Race position, + top bit shows if the participant is active or not"*). Extract: `pos = byte & 0x7F`, `active = bool(byte & 0x80)`. Ignore the position if `active` is False.
- **`sSector` mask with `0x03`** — upper bits encode position precision, not the sector.
- **Lap invalid flag** is `sRaceState & 0x08` (bit 3). It is NOT in the sector byte.
- **`sLastLapTime` does not exist** in this struct. Last lap time is tracked by saving `sCurrentTime` when `sCurrentLap` increments.

---

## Packet 4 — eGameState

Used to detect the session type. Small packet (~15 bytes).

### Format

| Byte offset | Type | Field | Used | Notes |
|-------------|------|-------|------|-------|
| 0–11 | — | base header | — | Standard 12-byte header |
| 12 | U16 | `mGameState` | — | Game state bitmask |
| 14 | U8 | `mSessionStateRaceState` | ✓ | Packed byte: bits 0–2 = race state, bits 3–5 = session state |

### Session state mapping (bits 3–5 of byte 14)

| Value | Session |
|-------|---------|
| 1 | Practice |
| 2 | Test (also mapped to practice) |
| 3 | Qualifying |
| 4 | Formation lap (mapped to race) |
| 5 | Race |
| 6 | Time attack (hotlap) |

---

## Not Yet Implemented

| Packet | Field(s) | Potential use |
|--------|----------|--------------|
| eCarPhysics | `carFlags` bitmask | Speed limiter / ABS active indicators |
| eCarPhysics | `oilTempCelsius`, `waterTempCelsius` | Temperature warning widgets |
| eCarPhysics | `tyreTemp` (surface, not tread) | Alternate tyre temp source |
| eTimings | `mRacePosition` for all participants | Proximity widget (all-car positions) |
| eTimings | all participant slots | Retirement / finish / cut detection per car |
| eParticipants (pkt 2) | Driver and car names | Driver name overlay |
| eWeatherState (pkt 5) | Ambient/track temp, per-zone weather | Weather widget |
| eTimeStats (pkt 7) | Full lap history per participant | Lap time comparison / sector history |
| eRaceDefinition | `mWorldFastestLapTime`, `mWorldFastestSector*` | Rival (lobby best) comparison |
| eRaceDefinition | `mEnforcedPitStopLap` | Mandatory pit reminder |

### Car class auto-detection

Car class is auto-detected from packet 8 (`eParticipantVehicleNames`), which contains a class name string per participant slot. On receipt, the parser lower-cases the class name and checks it for substrings defined in `_CLASS_MAP` (e.g. `"formula rookie"` → `formula_rookie`, `"kart"` → `karting`). If no match is found the class falls back to `"pcars2"`. No manual flag is required.
