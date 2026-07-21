"""Forza Horizon 6 Data Out telemetry source.

Listens on UDP port 5301 (configure the same port in-game under
Settings → HUD and Gameplay → Data Out).

Packet format: 324-byte fixed little-endian struct, documented at:
  https://support.forza.net/hc/en-us/articles/51744149102611-Forza-Horizon-6-Data-Out-Documentation

No registration required — FH6 pushes packets passively while driving.
"""
import logging
import struct
import socket
import threading

from telemetry.base import TelemetrySource, TelemetryData
from telemetry.forza_rpm import RpmCalibrator
from telemetry.forza_cars import ForzaCar, load_forza_cars

log = logging.getLogger("fh6")

_PORT = 5301
_PACKET_SIZE = 324

# Full 324-byte packet format (little-endian).
# x = 1 padding byte at end to reach exactly 324 bytes.
_FMT = (
    '<'
    'i'      # IsRaceOn        S32
    'I'      # TimestampMS     U32
    'fff'    # EngineMaxRpm, EngineIdleRpm, CurrentEngineRpm
    'fff'    # AccelerationX/Y/Z
    'fff'    # VelocityX/Y/Z
    'fff'    # AngularVelocityX/Y/Z
    'fff'    # Yaw, Pitch, Roll
    'ffff'   # NormSuspTravelFL/FR/RL/RR
    'ffff'   # TireSlipRatioFL/FR/RL/RR
    'ffff'   # WheelRotSpeedFL/FR/RL/RR
    'iiii'   # WheelOnRumbleStripFL/FR/RL/RR
    'iiii'   # WheelInPuddleFL/FR/RL/RR
    'ffff'   # SurfaceRumbleFL/FR/RL/RR
    'ffff'   # TireSlipAngleFL/FR/RL/RR
    'ffff'   # TireCombinedSlipFL/FR/RL/RR
    'ffff'   # SuspTravelMetersFL/FR/RL/RR
    'iiiii'  # CarOrdinal, CarClass, CarPerformanceIndex, DrivetrainType, NumCylinders
    'I'      # CarGroup        U32  (FH6-specific)
    'ff'     # SmashableVelDiff, SmashableMass  (FH6-specific)
    'fff'    # PositionX/Y/Z
    'fff'    # Speed, Power, Torque
    'ffff'   # TireTempFL/FR/RL/RR
    'ff'     # Boost, Fuel
    'f'      # DistanceTraveled
    'fff'    # BestLap, LastLap, CurrentLap
    'f'      # CurrentRaceTime
    'H'      # LapNumber       U16
    'B'      # RacePosition    U8
    'BBBB'   # Accel, Brake, Clutch, HandBrake  U8 each
    'B'      # Gear            U8
    'b'      # Steer           S8
    'bb'     # NormalizedDrivingLine, NormalizedAIBrakeDifference  S8 each
    'x'      # padding → 324 bytes total
)

_STRUCT = struct.Struct(_FMT)
assert _STRUCT.size == _PACKET_SIZE, f"FH6 struct size mismatch: {_STRUCT.size} != {_PACKET_SIZE}"

_CLASS_NAMES = {0: 'D', 1: 'C', 2: 'B', 3: 'A', 4: 'S1', 5: 'S2', 6: 'X'}


def _gear_str(gear: int) -> str:
    if gear == 0:
        return 'R'
    if gear == 11:
        return 'N'
    return str(gear)



class FH6Telemetry(TelemetrySource):
    """Forza Horizon 6 Data Out UDP source."""

    def __init__(self, port: int = _PORT, record_path: str | None = None):
        self._port = port
        self._record_path = record_path
        self._recorder = None
        self._lock = threading.Lock()
        self._data = TelemetryData()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._rpm_cal = RpmCalibrator()
        self._last_ordinal: int | None = None
        self._cars: dict[int, ForzaCar] = {}

    def connect(self) -> None:
        self._cars = load_forza_cars()
        if self._record_path:
            from telemetry.capture import PacketRecorder
            self._recorder = PacketRecorder(self._record_path, game="fh6", port=self._port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('', self._port))
        self._sock.settimeout(1.0)
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()
        log.info(f"Listening on UDP port {self._port}")

    def read(self) -> TelemetryData:
        with self._lock:
            return self._data

    def disconnect(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._recorder:
            self._recorder.close()
            self._recorder = None
        log.info("Disconnected")

    def _recv_loop(self) -> None:
        while self._running:
            try:
                raw, _ = self._sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                break
            if self._recorder:
                self._recorder.write(raw)
            if len(raw) != _PACKET_SIZE:
                continue
            try:
                parsed = self._parse(raw)
                with self._lock:
                    if parsed is not None:
                        self._data = parsed
                    elif self._data.game_paused is False:
                        self._data = TelemetryData(**{**self._data.__dict__, "game_paused": True})
            except Exception:
                pass

    def _parse(self, raw: bytes) -> TelemetryData | None:
        (
            is_race_on, timestamp_ms,
            engine_max_rpm, engine_idle_rpm, engine_rpm,
            accel_x, accel_y, accel_z,
            vel_x, vel_y, vel_z,
            ang_vel_x, ang_vel_y, ang_vel_z,
            yaw, pitch, roll,
            susp_fl, susp_fr, susp_rl, susp_rr,
            slip_r_fl, slip_r_fr, slip_r_rl, slip_r_rr,
            whl_fl, whl_fr, whl_rl, whl_rr,
            rumble_fl, rumble_fr, rumble_rl, rumble_rr,
            puddle_fl, puddle_fr, puddle_rl, puddle_rr,
            surf_fl, surf_fr, surf_rl, surf_rr,
            slip_a_fl, slip_a_fr, slip_a_rl, slip_a_rr,
            comb_fl, comb_fr, comb_rl, comb_rr,
            susp_m_fl, susp_m_fr, susp_m_rl, susp_m_rr,
            car_ordinal, car_class_id, car_pi, drivetrain, num_cyl,
            car_group, smash_vel, smash_mass,
            pos_x, pos_y, pos_z,
            speed, power, torque,
            t_fl, t_fr, t_rl, t_rr,
            boost, fuel,
            dist,
            best_lap, last_lap, cur_lap,
            race_time,
            lap_num,
            race_pos,
            accel_in, brake_in, clutch_in, handbrake_in,
            gear,
            steer,
            norm_drive, norm_ai_brake,
        ) = _STRUCT.unpack_from(raw)

        if not is_race_on:
            return None

        class_name = _CLASS_NAMES.get(car_class_id, '?')
        known_car = self._cars.get(car_ordinal)
        active_car_class = known_car.slug if known_car and known_car.slug else 'fh6'
        display_name = known_car.name if known_car else f'{class_name} {car_pi}'

        if car_ordinal != self._last_ordinal:
            self._last_ordinal = car_ordinal
            slug_tag = f" → {active_car_class}" if active_car_class != 'fh6' else ""
            log.info(f"car_ordinal={car_ordinal}  {display_name}  PI={car_pi}{slug_tag}")

        return TelemetryData(
            gear=_gear_str(gear),
            speed=round(speed * 3.6, 1),
            rpm=int(engine_rpm),
            max_rpm=self._rpm_cal.calibrate(int(engine_max_rpm), int(engine_rpm)),
            throttle=round(accel_in / 255.0, 3),
            brake=round(brake_in / 255.0, 3),
            steer=round(steer / 127.0, 3),
            lap_time=round(cur_lap, 3),
            last_lap=round(last_lap, 3),
            best_lap=round(best_lap, 3),
            lap_number=int(lap_num),
            position=int(race_pos),
            tyre_temp=(round(t_fl, 1), round(t_fr, 1), round(t_rl, 1), round(t_rr, 1)),
            fuel_remaining=round(fuel * 100.0, 1),
            fuel_capacity=100.0,
            fuel_per_lap=0.0,
            session_type='race',
            game='fh6',
            car_class=active_car_class,
            car_name=display_name,
            car_ordinal=car_ordinal,
        )
