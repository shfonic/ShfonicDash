# Forza Data Out — Telemetry Reference

Applies to: Forza Horizon 4 / 5 / 6 and Forza Motorsport 7 / 2023.  
All titles share the same `Sled + CarDash` base format. FM2023 appends an extra 20-byte block.

---

## In-Game Setup

| Game | Menu path | Default port |
|------|-----------|-------------|
| Forza Horizon (any) | Settings → HUD and Gameplay → Data Out | 5301 (FH6 default; configurable) |
| Forza Motorsport 7 | Settings → Gameplay & HUD → Data Out | 5300 |
| Forza Motorsport 2023 | Settings → Gameplay & HUD → Data Out | 5300 |

Set IP to the Pi's LAN address. Forza pushes packets passively — no registration needed.

---

## Packet Sizes

| Variant | Size | Composition |
|---------|------|-------------|
| FH4 / FH5 / FH6 / FM7 base | 311 bytes | Sled (232) + CarDash (79) |
| Forza Motorsport 2023 | 331 bytes | Sled (232) + CarDash (79) + MotorsportExtras (20) |
| FH6 | 324 bytes | Sled (232) + CarDash (79) + FH6Extras (12) + 1 pad byte |

FH6 inserts `CarGroup` (U32), `SmashableVelDiff` (F32), and `SmashableMass` (F32) between `NumCylinders` and `PositionX/Y/Z`, which shifts the position and CarDash fields relative to the FM layout.

---

## Full Field Reference

All fields little-endian. Offsets are byte offsets from the start of the packet.

### Sled block (offset 0–231, shared)

| Offset | Type | Field | Unit | Used | Notes |
|--------|------|-------|------|------|-------|
| 0 | S32 | `IsRaceOn` | — | ✓ | 0 = in menus / paused; skip packet if 0 |
| 4 | U32 | `TimestampMS` | ms | — | Packet timestamp; useful for packet-rate monitoring |
| 8 | F32 | `EngineMaxRpm` | rpm | ✓ | Overstates true redline by ~5–10%; corrected by `RpmCalibrator` |
| 12 | F32 | `EngineIdleRpm` | rpm | — | Idle speed |
| 16 | F32 | `CurrentEngineRpm` | rpm | ✓ | Current engine RPM |
| 20 | F32 | `AccelerationX` | m/s² | — | Lateral G (car-local space) |
| 24 | F32 | `AccelerationY` | m/s² | — | Vertical G (car-local space) |
| 28 | F32 | `AccelerationZ` | m/s² | — | Longitudinal G (car-local space, + = braking) |
| 32 | F32 | `VelocityX` | m/s | — | World-space X velocity |
| 36 | F32 | `VelocityY` | m/s | — | World-space Y velocity |
| 40 | F32 | `VelocityZ` | m/s | — | World-space Z velocity. **World-space only — sign depends on car heading, not direction of travel. Do not use to detect reverse.** |
| 44 | F32 | `AngularVelocityX` | rad/s | — | |
| 48 | F32 | `AngularVelocityY` | rad/s | — | Yaw rate; useful for oversteer detection |
| 52 | F32 | `AngularVelocityZ` | rad/s | — | |
| 56 | F32 | `Yaw` | rad | — | Car heading (world-space); combine with VelocityX/Z for local forward velocity |
| 60 | F32 | `Pitch` | rad | — | |
| 64 | F32 | `Roll` | rad | — | |
| 68 | F32×4 | `NormSuspTravelFL/FR/RL/RR` | 0–1 | — | Suspension travel as fraction of range |
| 84 | F32×4 | `TireSlipRatioFL/FR/RL/RR` | — | — | Longitudinal slip ratio per wheel |
| 100 | F32×4 | `WheelRotationSpeedFL/FR/RL/RR` | rad/s | — | Wheel angular velocity. Positive = forward. **Reportedly signed — negative when rolling backward — but unconfirmed; needs testing.** |
| 116 | S32×4 | `WheelOnRumbleStripFL/FR/RL/RR` | bool | — | 1 = wheel on rumble strip |
| 132 | S32×4 | `WheelInPuddleDepthFL/FR/RL/RR` | 0–1 | — | Depth fraction |
| 148 | F32×4 | `SurfaceRumbleFL/FR/RL/RR` | — | — | |
| 164 | F32×4 | `TireSlipAngleFL/FR/RL/RR` | rad | — | Lateral slip angle per wheel |
| 180 | F32×4 | `TireCombinedSlipFL/FR/RL/RR` | — | — | Combined slip magnitude per wheel |
| 196 | F32×4 | `SuspensionTravelMetersFL/FR/RL/RR` | m | — | Absolute suspension travel |
| 212 | S32 | `CarOrdinal` | — | ✓ | Unique car ID — matched against `_KNOWN_CARS` to identify specific cars and override `car_class` |
| 216 | S32 | `CarClass` | 0–6 | ✓ | 0=D, 1=C, 2=B, 3=A, 4=S1, 5=S2, 6=X |
| 220 | S32 | `CarPerformanceIndex` | 100–999 | ✓ | PI value shown in-game |
| 224 | S32 | `DrivetrainType` | 0–2 | — | 0=FWD, 1=RWD, 2=AWD |
| 228 | S32 | `NumCylinders` | — | — | Engine cylinder count |

### FH6-only fields (offset 232–243, between Sled and CarDash)

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 232 | U32 | `CarGroup` | FH6-specific car group ID |
| 236 | F32 | `SmashableVelDiff` | Collision velocity differential |
| 240 | F32 | `SmashableMass` | Colliding object mass |

### CarDash block (FM: offset 232; FH6: offset 244)

| Offset (FM) | Offset (FH6) | Type | Field | Unit | Used | Notes |
|-------------|--------------|------|-------|------|------|-------|
| 232 | 244 | F32×3 | `PositionX/Y/Z` | m | — | World position; useful for circuit mapping |
| 244 | 256 | F32 | `Speed` | m/s | ✓ | Multiply × 3.6 for km/h |
| 248 | 260 | F32 | `Power` | W | — | Engine power output |
| 252 | 264 | F32 | `Torque` | N·m | — | Engine torque |
| 256 | 268 | F32×4 | `TireTempFL/FR/RL/RR` | °C | ✓ | Surface tyre temperature |
| 272 | 284 | F32 | `Boost` | — | — | Boost pressure (turbo) |
| 276 | 288 | F32 | `Fuel` | 0–1 | ✓ | Fraction of full tank; multiply × 100 for % |
| 280 | 292 | F32 | `DistanceTraveled` | m | — | Odometer for session |
| 284 | 296 | F32 | `BestLap` | s | ✓ | Personal best lap time (-1 if none) |
| 288 | 300 | F32 | `LastLap` | s | ✓ | Most recently completed lap time (-1 if none) |
| 292 | 304 | F32 | `CurrentLap` | s | ✓ | Running current lap time |
| 296 | 308 | F32 | `CurrentRaceTime` | s | — | Total session time elapsed |
| 300 | 312 | U16 | `LapNumber` | — | ✓ | Current lap number (0-based) |
| 302 | 314 | U8 | `RacePosition` | — | ✓ | 0 = no position data |
| 303 | 315 | U8 | `Accel` | 0–255 | ✓ | Throttle input; divide by 255 |
| 304 | 316 | U8 | `Brake` | 0–255 | ✓ | Brake input; divide by 255 |
| 305 | 317 | U8 | `Clutch` | 0–255 | — | Clutch input |
| 306 | 318 | U8 | `HandBrake` | 0–255 | — | Handbrake input |
| 307 | 319 | U8 | `Gear` | — | ✓ | **0 = R, 1–10 = gears 1–10, 11 = N** |
| 308 | 320 | S8 | `Steer` | -127–127 | ✓ | Divide by 127 for -1 to 1 |
| 309 | 321 | S8 | `NormalizedDrivingLine` | — | — | AI racing line deviation |
| 310 | 322 | S8 | `NormalizedAIBrakeDifference` | — | — | |

### MotorsportExtras block (FM2023 only, offset 311)

| Offset | Type | Field | Unit | Used | Notes |
|--------|------|-------|------|------|-------|
| 311 | F32×4 | `TireWearFL/FR/RL/RR` | 0–1 | ✓ | Tyre wear fraction (FM2023 only) |
| 327 | S32 | `TrackOrdinal` | — | — | Unique track ID; useful for circuit name lookup |

---

## Gear Byte

**The gear byte encoding is not obvious:**

| Value | Meaning |
|-------|---------|
| `0` | Reverse (R) |
| `1`–`10` | Forward gears 1–10 |
| `11` | Neutral (N) — used for both parked neutral and transient neutral during gear changes |

There is no separate park or handbrake state in the gear byte.

---

## Known Quirks

- **`EngineMaxRpm` overstates redline** by approximately 5–10%. The `RpmCalibrator` (`src/telemetry/forza_rpm.py`) corrects this by tracking the highest `CurrentEngineRpm` seen and using that as the effective redline.
- **`VelocityX/Y/Z` are world-space**, not car-local. Their sign depends on which direction the car faces, not whether it's moving forward or backward. Do not use these to detect reverse gear.
- **`BestLap` and `LastLap` return `-1.0`** when no data exists (first lap, not yet completed). Check `> 0` before using.
- **`IsRaceOn = 0`** is sent during menus and loading screens. The parser discards these packets.
- **`Fuel` field** reports a fraction (0.0–1.0) of tank capacity, not an absolute volume. Multiply by a known tank size or display as a percentage.

---

## Not Yet Implemented

These fields are available in the packet but not currently extracted:

| Field | Potential use |
|-------|--------------|
| `PositionX/Y/Z` | Mini-map, circuit trace overlay |
| `WheelRotationSpeedFL/FR/RL/RR` | Wheel-spin / lockup indicator; possibly signed for direction |
| `TireSlipRatioFL/FR/RL/RR` | Individual wheel slip indicator |
| `TireSlipAngleFL/FR/RL/RR` | Oversteer / understeer angle per wheel |
| `TireCombinedSlipFL/FR/RL/RR` | Combined grip usage per corner |
| `NormSuspTravelFL/FR/RL/RR` | Suspension widget |
| `AngularVelocityY` | Yaw-rate oversteer gauge |
| `DrivetrainType` | FWD/RWD/AWD label |
| `TrackOrdinal` | Circuit name lookup from Forza database |
| `Power` + `Torque` | Power/torque gauge |
| `HandBrake` | Handbrake indicator |
| `Boost` | Turbo boost gauge |
| `CurrentRaceTime` | Session clock |
| `DistanceTraveled` | Odometer / stint tracker |
