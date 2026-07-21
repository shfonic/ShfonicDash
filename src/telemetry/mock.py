import logging
import threading
import time
import random
import math
from dataclasses import replace

from telemetry.base import TelemetrySource, TelemetryData

log = logging.getLogger("mock")


# Per-preset configuration for mock simulation
PRESETS = {
    "gt3": {
        "game": "acc",
        "car_class": "gt3",
        "car_name": "Porsche 992 GT3-R",
        "max_rpm": 9000,
        "rpm_idle": 1000,
        "max_speed": 280.0,
        "gear_thresholds": [0, 60, 110, 160, 210, 245, 280],  # speed (km/h) per gear
        "fuel_capacity": 100.0,
        "fuel_per_lap": 3.2,
        "tyre_compound": "DHE",
        "tyre_temp_optimal": (88.0, 88.0, 86.0, 86.0),  # FL,FR,RL,RR
        "tyre_temp_cold": (40.0, 40.0, 40.0, 40.0),
        "tyre_pressure_target": (27.5, 27.5, 26.5, 26.5),  # PSI
        "has_ers": False,
        "has_drs": False,
        "tc_max": 10,
        "abs_max": 10,
        "session_type": "race",
    },
    "gt4": {
        "game": "acc",
        "car_class": "gt4",
        "car_name": "Porsche 718 Cayman GT4",
        "max_rpm": 7600,
        "rpm_idle": 900,
        "max_speed": 230.0,
        "gear_thresholds": [0, 50, 90, 130, 175, 210, 230],
        "fuel_capacity": 70.0,
        "fuel_per_lap": 2.8,
        "tyre_compound": "DHE",
        "tyre_temp_optimal": (85.0, 85.0, 83.0, 83.0),
        "tyre_temp_cold": (40.0, 40.0, 40.0, 40.0),
        "tyre_pressure_target": (27.0, 27.0, 26.0, 26.0),
        "has_ers": False,
        "has_drs": False,
        "tc_max": 8,
        "abs_max": 8,
        "session_type": "race",
    },
    "f1": {
        "game": "f1_25",
        "car_class": "formula1",
        "car_name": "McLaren",
        "max_rpm": 12500,
        "rpm_idle": 5000,
        "max_speed": 345.0,
        "gear_thresholds": [0, 80, 140, 195, 245, 280, 315, 345],
        "fuel_capacity": 110.0,
        "fuel_per_lap": 2.6,
        "tyre_compound": "Soft",
        "tyre_temp_optimal": (100.0, 100.0, 98.0, 98.0),
        "tyre_temp_cold": (50.0, 50.0, 50.0, 50.0),
        "tyre_pressure_target": (22.5, 22.5, 21.5, 21.5),
        "has_ers": True,
        "has_drs": True,
        "tc_max": 8,
        "abs_max": 8,
        "session_type": "hotlap",
    },
    "f2": {
        "game": "f1_25",
        "car_class": "f2",
        "car_name": "Prema",
        "max_rpm": 10750,
        "rpm_idle": 4500,
        "max_speed": 310.0,
        "gear_thresholds": [0, 70, 125, 175, 225, 265, 295, 310],
        "fuel_capacity": 85.0,
        "fuel_per_lap": 2.3,
        "tyre_compound": "Soft",
        "tyre_temp_optimal": (95.0, 95.0, 93.0, 93.0),
        "tyre_temp_cold": (45.0, 45.0, 45.0, 45.0),
        "tyre_pressure_target": (23.0, 23.0, 22.0, 22.0),
        "has_ers": False,
        "has_drs": True,
        "tc_max": 0,
        "abs_max": 0,
        "session_type": "race",
    },
    "f1_26": {
        "game": "f1_25",
        "car_class": "formula1_2026",
        "car_name": "Cadillac",
        "max_rpm": 12000,
        "rpm_idle": 5000,
        "max_speed": 360.0,
        "gear_thresholds": [0, 85, 145, 200, 255, 295, 330, 360],
        "fuel_capacity": 100.0,
        "fuel_per_lap": 2.2,
        "tyre_compound": "Soft",
        "tyre_temp_optimal": (102.0, 102.0, 100.0, 100.0),
        "tyre_temp_cold": (50.0, 50.0, 50.0, 50.0),
        "tyre_pressure_target": (22.0, 22.0, 21.0, 21.0),
        "has_ers": True,
        "has_drs": False,
        "has_active_aero": True,
        "has_boost": True,
        "tc_max": 8,
        "abs_max": 8,
        "session_type": "race",
    },
    "formula_rookie": {
        "game": "pcars2",
        "car_class": "lcd",
        "car_name": "Formula Rookie",
        "max_rpm": 6800,
        "rpm_idle": 900,
        "max_speed": 185.0,
        "gear_thresholds": [0, 40, 75, 110, 145, 175, 185],
        "fuel_capacity": 45.0,
        "fuel_per_lap": 1.8,
        "tyre_compound": "",
        "tyre_temp_optimal": (80.0, 80.0, 78.0, 78.0),
        "tyre_temp_cold": (35.0, 35.0, 35.0, 35.0),
        "tyre_pressure_target": (24.0, 24.0, 23.5, 23.5),
        "has_ers": False,
        "has_drs": False,
        "tc_max": 0,
        "abs_max": 0,
        "session_type": "race",
    },
    "pcars2": {
        "game": "pcars2",
        "car_class": "pcars2",
        "car_name": "Formula Rookie",
        "max_rpm": 6800,
        "rpm_idle": 900,
        "max_speed": 185.0,
        "gear_thresholds": [0, 40, 75, 110, 145, 175, 185],
        "fuel_capacity": 45.0,
        "fuel_per_lap": 1.8,
        "tyre_compound": "",
        "tyre_temp_optimal": (80.0, 80.0, 78.0, 78.0),
        "tyre_temp_cold": (35.0, 35.0, 35.0, 35.0),
        "tyre_pressure_target": (24.0, 24.0, 23.5, 23.5),
        "has_ers": False,
        "has_drs": False,
        "tc_max": 0,
        "abs_max": 0,
        "session_type": "race",
    },
    "fm": {
        "game": "fm",
        "car_class": "fm",
        "car_name": "Ford Mustang GT350R",
        "max_rpm": 8250,
        "rpm_idle": 850,
        "max_speed": 290.0,
        "gear_thresholds": [0, 65, 120, 170, 215, 255, 290],
        "fuel_capacity": 100.0,   # stored as 0-100% (FM sends fuel as 0.0-1.0)
        "fuel_per_lap": 4.0,
        "tyre_compound": "",
        "tyre_temp_optimal": (85.0, 85.0, 83.0, 83.0),
        "tyre_temp_cold": (35.0, 35.0, 35.0, 35.0),
        "tyre_pressure_target": (30.0, 30.0, 29.5, 29.5),
        "has_ers": False,
        "has_drs": False,
        "tc_max": 0,
        "abs_max": 0,
        "session_type": "race",
    },
    "fh6": {
        "game": "fh6",
        "car_class": "fh6",
        "car_name": "Honda Civic Type R",
        "max_rpm": 7500,
        "rpm_idle": 800,
        "max_speed": 260.0,
        "gear_thresholds": [0, 55, 105, 155, 200, 235, 260],
        "fuel_capacity": 100.0,   # stored as 0-100% (FH6 sends fuel as 0.0-1.0)
        "fuel_per_lap": 3.5,
        "tyre_compound": "",
        "tyre_temp_optimal": (80.0, 80.0, 78.0, 78.0),
        "tyre_temp_cold": (35.0, 35.0, 35.0, 35.0),
        "tyre_pressure_target": (32.0, 32.0, 32.0, 32.0),
        "has_ers": False,
        "has_drs": False,
        "tc_max": 0,
        "abs_max": 0,
        "session_type": "race",
    },
    "gt7": {
        "game": "gt7",
        "car_class": "gt7",
        "car_name": "Nissan GT-R Gr.3",
        "max_rpm": 8000,
        "rpm_idle": 900,
        "max_speed": 275.0,
        "gear_thresholds": [0, 58, 105, 152, 200, 240, 275],
        "fuel_capacity": 65.0,
        "fuel_per_lap": 3.0,
        "tyre_compound": "RH",
        "tyre_temp_optimal": (85.0, 85.0, 83.0, 83.0),
        "tyre_temp_cold": (40.0, 40.0, 40.0, 40.0),
        "tyre_pressure_target": (27.0, 27.0, 26.5, 26.5),
        "has_ers": False,
        "has_drs": False,
        "tc_max": 5,
        "abs_max": 3,
        "session_type": "race",
    },
    "delorean": {
        "game": "fh6",
        "car_class": "delorean",
        "car_name": "DeLorean DMC-12",
        "max_rpm": 6500,
        "rpm_idle": 750,
        "max_speed": 200.0,       # ~124 mph — crosses 88 mph during normal driving
        "gear_thresholds": [0, 42, 78, 115, 158, 200],   # 5-speed
        "fuel_capacity": 100.0,
        "fuel_per_lap": 4.0,
        "tyre_compound": "",
        "tyre_temp_optimal": (75.0, 75.0, 73.0, 73.0),
        "tyre_temp_cold": (35.0, 35.0, 35.0, 35.0),
        "tyre_pressure_target": (32.0, 32.0, 31.5, 31.5),
        "has_ers": False,
        "has_drs": False,
        "tc_max": 0,
        "abs_max": 0,
        "session_type": "race",
    },
}

# F1 driver last names for mock qualifying leaderboard (20-car grid)
_MOCK_F1_GRID = [
    # (name, race_number, team_colour_rgb) — 2025 F1 season grid
    ("VERSTAPPEN", 1,  (54,  113, 198)),   # Red Bull
    ("NORRIS",     4,  (255, 128,   0)),   # McLaren
    ("LECLERC",    16, (232,   0,  45)),   # Ferrari
    ("PIASTRI",    81, (255, 128,   0)),   # McLaren
    ("SAINZ",      55, (100, 196, 255)),   # Williams
    ("RUSSELL",    63, ( 39, 244, 210)),   # Mercedes
    ("HAMILTON",   44, (232,   0,  45)),   # Ferrari
    ("ALONSO",     14, ( 34, 153, 113)),   # Aston Martin
    ("TSUNODA",    22, ( 54, 113, 198)),   # Red Bull
    ("STROLL",     18, ( 34, 153, 113)),   # Aston Martin
    ("GASLY",      10, (255, 135, 188)),   # Alpine
    ("ANTONELLI",  12, ( 39, 244, 210)),   # Mercedes
    ("ALBON",      23, (100, 196, 255)),   # Williams
    ("BEARMAN",    87, (182, 186, 189)),   # Haas
    ("OCON",       31, (182, 186, 189)),   # Haas
    ("HULKENBERG", 27, ( 82, 226,  82)),   # Kick Sauber
    ("HADJAR",      6, (102, 146, 255)),   # Racing Bulls
    ("LAWSON",     30, (102, 146, 255)),   # Racing Bulls
    ("BORTOLETO",   5, ( 82, 226,  82)),   # Kick Sauber
    ("DOOHAN",      7, (255, 135, 188)),   # Alpine
]

# ── Synthetic circuit for mock world position ────────────────────────────────
# A closed loop built from low harmonics (period 1.0 in the lap fraction u), so
# the car returns to the same point every lap. Coordinates are metres in the
# same X/Z-horizontal, Y-up convention the real sources use, giving a ~2 km
# club circuit with a few distinct corners. This feeds pos_x/pos_z/heading and
# lap_distance so the track recorder / map can be developed against mock data
# without a live game.
def _track_point(u: float) -> tuple:
    """World (x, z) in metres for lap fraction u in [0, 1)."""
    th = 2.0 * math.pi * u
    x = 620.0 * math.cos(th) + 160.0 * math.cos(2.0 * th) + 70.0 * math.sin(3.0 * th)
    z = 430.0 * math.sin(th) - 150.0 * math.sin(2.0 * th) + 60.0 * math.cos(3.0 * th)
    return x, z


def _track_tangent(u: float) -> tuple:
    """Unit tangent (ux, uz) at lap fraction u, from a numeric derivative."""
    x0, z0 = _track_point((u - 1e-4) % 1.0)
    x1, z1 = _track_point((u + 1e-4) % 1.0)
    dx, dz = x1 - x0, z1 - z0
    norm = math.hypot(dx, dz) or 1.0
    return dx / norm, dz / norm


def _track_heading(u: float) -> float:
    """Tangent heading (radians) at lap fraction u, in the shared model
    convention (F1 yaw: 0 faces +Z, increasing toward +X)."""
    ux, uz = _track_tangent(u)
    return math.atan2(ux, uz)


def _phantom_opponents(u: float, now: float) -> list:
    """Three phantom cars around the player's lap fraction u, exercising the
    spotter radar: A sweeps through fully alongside (red), B hovers a few
    metres behind (amber), C drifts near the radar's edge ahead. Longitudinal
    offsets are metres along the centreline; lateral offsets are metres along
    the left normal (the player weaves ±3 m, so the closing distance varies)."""
    cars = []
    offsets = (
        (8.0 * math.sin(now * 0.3), 3.0),             # A: sweeps ±8 m through alongside
        (-(9.0 + 5.0 * math.sin(now * 0.13)), -1.0),  # B: oscillates 4–14 m behind
        (35.0 + 10.0 * math.sin(now * 0.05), 1.5),    # C: 25–45 m ahead, radar edge
    )
    # The loop's parameterisation is not arc-length (the harmonics compress
    # and stretch it locally), so convert metres → lap fraction with the
    # local track-metres-per-u, not the lap-average _TRACK_LENGTH.
    eps = 1e-3
    x0, z0 = _track_point((u - eps) % 1.0)
    x1, z1 = _track_point((u + eps) % 1.0)
    m_per_u = math.hypot(x1 - x0, z1 - z0) / (2.0 * eps) or _TRACK_LENGTH
    for i, (long_m, lat_m) in enumerate(offsets):
        cu = (u + long_m / m_per_u) % 1.0
        cx, cz = _track_point(cu)
        ux, uz = _track_tangent(cu)
        cars.append({
            "idx": i + 1,
            "x": round(cx - uz * lat_m, 2),
            "z": round(cz + ux * lat_m, 2),
            "yaw": round(math.atan2(ux, uz), 4),
        })
    return cars


def _track_length(samples: int = 720) -> float:
    """Total centreline length in metres (polyline approximation)."""
    total = 0.0
    prev = _track_point(0.0)
    for i in range(1, samples + 1):
        p = _track_point(i / samples)
        total += math.hypot(p[0] - prev[0], p[1] - prev[1])
        prev = p
    return total


_TRACK_LENGTH = _track_length()


# Typical lap lengths to simulate realistic sector/lap times
LAP_TIMES = {
    "gt3": 90.0,
    "gt4": 95.0,
    "formula1": 80.0,
    "formula1_2026": 78.0,
    "f2": 85.0,
    "lcd": 75.0,
    "pcars2": 75.0,
    "fm": 92.0,
    "fh6": 88.0,
    "gt7": 100.0,
    "delorean": 95.0,
}


class MockTelemetry(TelemetrySource):

    def __init__(self, preset: str = "gt3", session_type: str = None,
                 prefill_laps: int = 0):
        if preset not in PRESETS:
            raise ValueError(f"Unknown mock preset '{preset}'. Choose from: {list(PRESETS)}")
        self._cfg          = PRESETS[preset]
        self._session_type = session_type or self._cfg["session_type"]
        self._prefill_laps = prefill_laps
        self._lock         = threading.Lock()
        self._running      = False
        self._thread       = None
        self._data         = TelemetryData()
        # Pre-seeded lap entries — consumed by prefill_frames()
        self._seeded_frames: list[TelemetryData] = []
        if prefill_laps > 0:
            self._build_seeded_frames(prefill_laps)

    def connect(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        log.info(f"Connected (preset={self._cfg['car_class']}, session={self._session_type})")

    def _run(self):
        cfg = self._cfg
        thresholds = cfg["gear_thresholds"]
        max_gear = len(thresholds) - 1
        max_rpm = cfg["max_rpm"]
        max_speed = cfg["max_speed"]

        # Driving state
        speed = 0.0
        gear = 1
        gear_str = "1"
        throttle = 0.0
        brake = 0.0
        accelerating = True
        target_speed = random.uniform(max_speed * 0.7, max_speed * 0.95)
        pending_gear = None
        gear_transition_end = 0.0

        # Electronics
        ers_energy = 0.7 if cfg["has_ers"] else 0.0
        drs_zone = False
        tc_level = 3 if cfg["tc_max"] > 0 else 0
        abs_level = 3 if cfg["abs_max"] > 0 else 0

        # Tyres — start cold, warm up over first 2 laps
        tyre_temp = list(cfg["tyre_temp_cold"])
        tyre_pressure = list(cfg["tyre_pressure_target"])
        tyre_wear = [0.0, 0.0, 0.0, 0.0]
        tyre_compound = cfg["tyre_compound"]

        # Fuel
        fuel = cfg["fuel_capacity"]
        fuel_per_lap = cfg["fuel_per_lap"]
        fuel_per_tick = fuel_per_lap / (LAP_TIMES.get(cfg["car_class"], 90.0) * 10)  # 0.1s ticks

        # Lap timing
        lap_start = time.time()
        lap_number = 1
        lap_time = 0.0
        last_lap = 0.0
        best_lap = 0.0
        estimated_lap = LAP_TIMES.get(cfg["car_class"], 90.0)
        sector_len = estimated_lap / 3.0
        sector = 0
        sector1_time = 0.0
        sector2_time = 0.0
        best_s1 = sector_len * 0.97
        best_s2 = sector_len * 0.98
        best_s3 = sector_len * 0.99
        s1_flag = ""
        s2_flag = ""
        s3_flag = ""

        # Race info
        position = random.randint(3, 8)
        total_cars = 22 if cfg["car_class"] == "formula1_2026" else 20 if cfg["car_class"] in ("formula1", "f2") else 28
        gap_ahead = random.uniform(0.5, 5.0)
        gap_behind = random.uniform(0.5, 5.0)
        # Slow per-tick gap drift (s/s) so the GapWidget trend colouring is exercised
        gap_drift_ahead = random.uniform(-0.3, 0.3)
        gap_drift_behind = random.uniform(-0.3, 0.3)
        # Only the F1 source provides neighbour names — mirror that in mock
        has_names = cfg["car_class"] in ("formula1", "formula1_2026", "f2")
        total_laps = 30 if self._session_type == "race" else 0

        # Qualifying leaderboard — build AI competitor times once at session start
        qualy_participants: list = []
        if self._session_type == "qualifying":
            base = LAP_TIMES.get(cfg["car_class"], 80.0)
            ai_grid = _MOCK_F1_GRID[:19]
            # Spread AI times from ~base to base+2.3 s (roughly 0.12 s per position)
            ai_times = [base + i * 0.12 + random.uniform(-0.04, 0.04) for i in range(19)]
            qualy_participants = [
                {
                    "name":        name,
                    "race_number": rnum,
                    "team_colour": colour,
                    "best_lap":    t,
                }
                for (name, rnum, colour), t in zip(ai_grid, ai_times)
            ]

        def _build_qualy_participants(player_best: float) -> list:
            entries = list(qualy_participants) + [
                {"name": "YOU", "race_number": 0, "team_colour": None, "best_lap": player_best}
            ]
            entries.sort(key=lambda e: e["best_lap"] if e["best_lap"] > 0 else float("inf"))
            for i, e in enumerate(entries, 1):
                e["position"] = i
            return entries

        # Completed laps list for practice (lap_number → time)
        completed_laps = []

        while self._running:
            now = time.time()
            lap_time = now - lap_start

            # === DRIVING PHYSICS ===
            if accelerating and speed >= target_speed:
                accelerating = False
                target_speed = random.uniform(max_speed * 0.4, max_speed * 0.65)
            elif not accelerating and speed <= target_speed:
                accelerating = True
                target_speed = random.uniform(max_speed * 0.7, max_speed * 0.95)

            target_thr = 0.85 + random.uniform(-0.1, 0.05) if accelerating else 0.0
            throttle += (target_thr - throttle) * 0.12
            throttle = max(0.0, min(1.0, throttle))

            target_brk = 0.0 if accelerating else min(0.95, (1.0 - throttle) * random.uniform(0.3, 0.9))
            brake += (target_brk - brake) * 0.15
            brake = max(0.0, min(1.0, brake))

            accel = (throttle - 0.05) * (max_speed / 20.0)
            if not accelerating:
                accel -= (max_speed / 15.0) * (1.0 - throttle)
            speed = max(0.0, min(max_speed + 5.0, speed + accel * 0.1 + random.uniform(-1.0, 1.0)))

            # === GEAR ===
            target_gear = 1
            for i, threshold in enumerate(thresholds[1:], 1):
                if speed >= threshold:
                    target_gear = i
            target_gear = min(target_gear, max_gear)
            target_gear_str = str(target_gear)

            if target_gear_str != gear_str and pending_gear is None:
                pending_gear = target_gear_str
                gear_transition_end = now + 0.08
                gear_str = "N"
            elif pending_gear is not None:
                if now >= gear_transition_end:
                    gear_str = pending_gear
                    pending_gear = None
                else:
                    gear_str = "N"
            else:
                gear_str = target_gear_str

            # === RPM ===
            current_gear_num = int(gear_str) if gear_str not in ("N", "R") else 1
            gear_ratio = current_gear_num / max_gear
            base_rpm = cfg["rpm_idle"] + (max_rpm - cfg["rpm_idle"]) * (speed / max_speed) * (1.0 / max(gear_ratio, 0.2))
            rpm = int(max(cfg["rpm_idle"], min(max_rpm, base_rpm + throttle * 800 + random.uniform(-200, 200))))

            # === TYRES ===
            optimal = cfg["tyre_temp_optimal"]
            for i in range(4):
                # Warm up toward optimal; outer tyres (0,2=left) slightly different
                target_t = optimal[i] + (throttle - 0.5) * 5.0
                if not accelerating and brake > 0.3:
                    target_t += brake * 8.0  # braking heat on fronts
                tyre_temp[i] += (target_t - tyre_temp[i]) * 0.002
                tyre_temp[i] += random.uniform(-0.3, 0.3)
                # Pressure tracks temp roughly
                p_base = cfg["tyre_pressure_target"][i]
                tyre_pressure[i] = p_base + (tyre_temp[i] - optimal[i]) * 0.04 + random.uniform(-0.05, 0.05)
                # Wear
                tyre_wear[i] = min(1.0, tyre_wear[i] + (speed / max_speed) * 0.000015 + throttle * 0.000008)

            # === FUEL ===
            fuel = max(0.0, fuel - fuel_per_tick * (0.5 + throttle * 0.5 + speed / max_speed * 0.5))
            fuel_laps = fuel / fuel_per_lap if fuel_per_lap > 0 else 0.0

            # === ERS (F1 only) ===
            ers_mode = 0
            if cfg["has_ers"]:
                # Cycle through modes during lap
                t_frac = (lap_time % 30) / 30.0
                if t_frac < 0.3:
                    ers_mode = 3  # Overtake
                elif t_frac < 0.6:
                    ers_mode = 1  # Medium
                else:
                    ers_mode = 0  # Balanced
                harvest_rate = 0.003 if (not accelerating and brake > 0.1) else 0.001
                deploy_rate = 0.004 if ers_mode == 3 else 0.002 if ers_mode == 1 else 0.0
                ers_energy = max(0.0, min(1.0, ers_energy + harvest_rate - deploy_rate))

            # === DRS ===
            drs_available = False
            drs_active = False
            if cfg["has_drs"]:
                drs_available = (lap_time % 20) > 14
                drs_active = drs_available and speed > 180 and throttle > 0.7

            # === ACTIVE AERO + BOOST (F1 2026) ===
            active_aero_mode = ""
            active_aero_available = False
            boost_active = False
            if cfg.get("has_active_aero"):
                active_aero_available = True
                active_aero_mode = "straight" if speed > 200 and throttle > 0.75 else "corner"
            if cfg.get("has_boost"):
                boost_active = (lap_time % 25) > 20 and speed > 220

            # === SECTORS & LAPS ===
            prev_sector = sector
            if lap_time < sector_len:
                sector = 0
            elif lap_time < sector_len * 2:
                sector = 1
                if prev_sector == 0:
                    sector1_time = lap_time
                    s1_flag = _sector_flag(sector1_time, best_s1)
                    if s1_flag == "purple":
                        best_s1 = sector1_time
            else:
                sector = 2
                if prev_sector == 1:
                    sector2_time = lap_time
                    s2_flag = _sector_flag(sector2_time - sector1_time, best_s2)
                    if s2_flag == "purple":
                        best_s2 = sector2_time - sector1_time

            # Lap completion
            if lap_time >= estimated_lap + random.uniform(-3.0, 3.0):
                s3 = lap_time - sector2_time
                s3_flag = _sector_flag(s3, best_s3)
                if s3_flag == "purple":
                    best_s3 = s3

                last_lap = lap_time
                if best_lap == 0.0 or last_lap < best_lap:
                    best_lap = last_lap
                completed_laps.append(last_lap)
                lap_number += 1
                lap_start = time.time()
                sector = 0
                sector1_time = 0.0
                sector2_time = 0.0
                s1_flag = ""
                s2_flag = ""
                s3_flag = ""
                # Simulate position/gap changes in race
                if self._session_type == "race":
                    gap_ahead = max(0.0, gap_ahead + random.uniform(-0.5, 0.5))
                    gap_behind = max(0.0, gap_behind + random.uniform(-0.5, 0.5))
                    if random.random() < 0.1:
                        position = max(1, min(total_cars, position + random.choice([-1, 1])))

            delta = (lap_time - best_lap) if best_lap > 0 else 0.0

            # Drift the gaps continuously in race mode, re-rolling direction occasionally
            if self._session_type == "race":
                if random.random() < 0.008:
                    gap_drift_ahead = random.uniform(-0.3, 0.3)
                if random.random() < 0.008:
                    gap_drift_behind = random.uniform(-0.3, 0.3)
                gap_ahead = max(0.1, gap_ahead + gap_drift_ahead * 0.1)
                gap_behind = max(0.1, gap_behind + gap_drift_behind * 0.1)

            name_ahead = name_behind = ""
            if has_names:
                if position >= 2:
                    name_ahead = _MOCK_F1_GRID[(position - 2) % len(_MOCK_F1_GRID)][0]
                if position < total_cars:
                    name_behind = _MOCK_F1_GRID[(position - 1) % len(_MOCK_F1_GRID)][0]

            # Build qualifying participant list each tick (cheap — 20 entries)
            participants: list = []
            if self._session_type == "qualifying":
                participants = _build_qualy_participants(best_lap)
                qualy_pos = next((e["position"] for e in participants if e["name"] == "YOU"), position)
                position = qualy_pos

            # === WORLD POSITION ===
            # Follow the synthetic circuit by lap fraction, with a slow lateral
            # weave so successive laps differ slightly (exercises the recorder's
            # line-averaging without pretending to be a true left/right edge).
            u = (lap_time / estimated_lap) % 1.0
            tx, tz = _track_point(u)
            ux, uz = _track_tangent(u)
            head = math.atan2(ux, uz)
            lat = 3.0 * math.sin(now * 0.7)          # ±3 m off centreline
            pos_x = tx - uz * lat                    # left normal = (-uz, ux)
            pos_z = tz + ux * lat
            pos_y = 5.0 * math.sin(2.0 * math.pi * u)  # gentle ±5 m elevation
            lap_distance = u * _TRACK_LENGTH

            data = TelemetryData(
                # Vehicle
                gear=gear_str,
                speed=round(speed, 1),
                rpm=rpm,
                max_rpm=max_rpm,
                throttle=round(throttle, 3),
                brake=round(brake, 3),
                steer=round(math.sin(now * 0.3) * 0.4, 3),
                # Electronics
                drs_available=drs_available,
                drs_active=drs_active,
                tc_level=tc_level,
                abs_level=abs_level,
                ers_deploy_mode=ers_mode,
                ers_stored_energy=round(ers_energy, 3),
                # Tyres
                tyre_temp=tuple(round(t, 1) for t in tyre_temp),
                tyre_pressure=tuple(round(p, 2) for p in tyre_pressure),
                tyre_wear=tuple(round(w, 4) for w in tyre_wear),
                tyre_compound=tyre_compound,
                # Fuel
                fuel_remaining=round(fuel, 2),
                fuel_capacity=cfg["fuel_capacity"],
                fuel_per_lap=round(fuel_per_lap, 2),
                fuel_laps_remaining=round(fuel_laps, 1),
                # Lap timing
                lap_time=round(lap_time, 3),
                last_lap=round(last_lap, 3),
                best_lap=round(best_lap, 3),
                delta=round(delta, 3),
                lap_number=lap_number,
                total_laps=total_laps,
                lap_distance=round(lap_distance, 1),
                # World position
                pos_x=round(pos_x, 2),
                pos_y=round(pos_y, 2),
                pos_z=round(pos_z, 2),
                heading=round(head, 4),
                pos_valid=True,
                opponents_pos=_phantom_opponents(u, now),
                # Sectors
                sector=sector,
                sector1_time=round(sector1_time, 3),
                sector2_time=round(sector2_time, 3),
                best_sector1=round(best_s1, 3),
                best_sector2=round(best_s2, 3),
                best_sector3=round(best_s3, 3),
                sector1_flag=s1_flag,
                sector2_flag=s2_flag,
                sector3_flag=s3_flag,
                # F1 2026
                active_aero_mode=active_aero_mode,
                active_aero_available=active_aero_available,
                boost_active=boost_active,
                # Race info
                position=position,
                total_cars=total_cars,
                gap_ahead=round(gap_ahead, 2),
                gap_behind=round(gap_behind, 2),
                name_ahead=name_ahead,
                name_behind=name_behind,
                # Participants (qualifying leaderboard)
                participants=participants,
                # Session
                session_type=self._session_type,
                session_time_remaining=max(0.0, 3600.0 - (lap_number * estimated_lap)),
                # Meta
                game=cfg["game"],
                car_class=cfg["car_class"],
                car_name=cfg["car_name"],
                track="Mock Circuit",
            )

            with self._lock:
                self._data = data

            time.sleep(0.1)

    def read(self) -> TelemetryData:
        with self._lock:
            return replace(self._data)

    def disconnect(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            thread = self._thread

        if thread is not None:
            thread.join(timeout=1.0)
        log.info("Disconnected")

    def prefill_frames(self) -> list:
        """Return pre-seeded TelemetryData frames for LapListWidget population."""
        return list(self._seeded_frames)

    def _build_seeded_frames(self, n: int) -> None:
        """Generate n completed lap frames to pre-populate LapListWidget."""
        cfg  = self._cfg
        base = LAP_TIMES.get(cfg["car_class"], 90.0)
        best = None
        frames: list[TelemetryData] = []

        for lap in range(1, n + 2):  # +2: need lap N+1 to trigger recording of lap N
            lap_time = base + random.uniform(-2.5, 4.0) if lap <= n else base
            if best is None or lap_time < best:
                best = lap_time

            # Sector flags vs personal best
            s1 = base * 0.31 + random.uniform(-0.5, 1.0)
            s2 = base * 0.35 + random.uniform(-0.5, 1.0)
            s3 = lap_time - s1 - s2

            def _flag(t, b): return "purple" if t <= b else ("green" if t <= b * 1.005 else "yellow")
            best_s1 = base * 0.31
            best_s2 = base * 0.35
            best_s3 = base * 0.34

            frames.append(TelemetryData(
                gear="3", speed=120.0, rpm=6500, max_rpm=cfg["max_rpm"],
                throttle=0.7, brake=0.0,
                lap_number=lap,
                last_lap=round(lap_time if lap > 1 else 0.0, 3),
                best_lap=round(best, 3),
                lap_time=0.0,
                delta=0.0,
                sector1_time=round(s1, 3),
                sector2_time=round(s1 + s2, 3),
                sector1_flag=_flag(s1, best_s1),
                sector2_flag=_flag(s2, best_s2),
                sector3_flag=_flag(s3, best_s3),
                tyre_temp=tuple(cfg["tyre_temp_optimal"]),
                tyre_pressure=tuple(cfg["tyre_pressure_target"]),
                tyre_wear=(0.08, 0.07, 0.05, 0.05),
                tyre_compound=cfg["tyre_compound"],
                fuel_remaining=round(cfg["fuel_capacity"] - lap * cfg["fuel_per_lap"], 1),
                fuel_capacity=cfg["fuel_capacity"],
                fuel_per_lap=cfg["fuel_per_lap"],
                fuel_laps_remaining=round((cfg["fuel_capacity"] - lap * cfg["fuel_per_lap"]) / cfg["fuel_per_lap"], 1),
                position=max(1, 5 - lap // 3),
                total_cars=20,
                gap_ahead=round(random.uniform(0.3, 3.0), 3),
                gap_behind=round(random.uniform(0.3, 3.0), 3),
                name_ahead=_MOCK_F1_GRID[2][0] if cfg["car_class"] in ("formula1", "formula1_2026", "f2") else "",
                name_behind=_MOCK_F1_GRID[5][0] if cfg["car_class"] in ("formula1", "formula1_2026", "f2") else "",
                session_type=self._session_type,
                game=cfg["game"],
                car_class=cfg["car_class"],
                car_name=cfg["car_name"],
            ))
        self._seeded_frames = frames


def _sector_flag(time_val: float, best: float) -> str:
    if time_val <= best:
        return "purple"
    if time_val <= best * 1.005:
        return "green"
    return "yellow"
