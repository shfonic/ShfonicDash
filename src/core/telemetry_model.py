from dataclasses import dataclass, field


@dataclass
class TelemetryData:
    # === VEHICLE STATE ===
    gear: str = "N"
    speed: float = 0.0           # km/h
    rpm: int = 0
    max_rpm: int = 8000
    throttle: float = 0.0        # 0.0–1.0
    brake: float = 0.0           # 0.0–1.0
    steer: float = 0.0

    # === ELECTRONICS ===
    drs_available: bool = False
    drs_active: bool = False
    pit_limiter: bool = False
    in_pits: bool = False        # in pit lane or garage (authoritative game pit
                                 # status where available — not the pit limiter)
    driver_status: int = 4       # F1 lap phase: 0=garage, 1=flying lap, 2=in
                                 # lap, 3=out lap, 4=on track. Default 4 ("driving")
                                 # so non-F1 sources behave as if always on track.
    tc_level: int = 0
    abs_level: int = 0
    ers_deploy_mode: int = 0     # 0=None/Balanced, 1=Medium, 2=Hotlap, 3=Boost
    ers_stored_energy: float = 0.0   # 0.0–1.0
    ers_harvested_lap: float = 0.0
    ers_deployed_lap: float = 0.0
    # F1 2026 — Active Aero + Boost (MOR)
    active_aero_mode: str = ""       # "corner" (high downforce) / "straight" (low drag)
    active_aero_available: bool = False
    boost_active: bool = False       # MOR/Overtake mode currently deployed

    # Session-wide assist settings (F1 2025/2026 Session packet). Unlike
    # tc_level/abs_level above (live per-frame Car Status state), these only
    # change if the driver edits assist settings mid-session. 0 = off/manual.
    steering_assist: int = 0
    braking_assist: int = 0
    gearbox_assist: int = 0      # 0=manual, 1=manual + suggested gear, 2=auto
    pit_assist: int = 0
    pit_release_assist: int = 0
    ers_assist: int = 0
    drs_assist: int = 0
    racing_line_assist: int = 0  # 0=off, 1=corners only, 2=full

    # === TYRES (FL, FR, RL, RR order throughout) ===
    tyre_temp: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0, 0.0))      # °C inner (core)
    tyre_pressure: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0, 0.0))  # PSI
    tyre_wear: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0, 0.0))      # 0.0–1.0
    tyre_compound: str = ""      # "Soft", "Medium", "Hard", "Inter", "Wet", "DHE", "DHD", etc.

    # === FUEL ===
    fuel_remaining: float = 0.0  # kg
    fuel_capacity: float = 0.0   # kg
    fuel_per_lap: float = 0.0
    fuel_laps_remaining: float = 0.0

    # === LAP TIMING ===
    lap_time: float = 0.0        # current lap seconds
    lap_invalid: bool = False    # track limits / cut detected
    last_lap: float = 0.0
    best_lap: float = 0.0
    delta: float = 0.0           # vs best lap (+ = slower, - = faster)
    lap_number: int = 0
    total_laps: int = 0
    lap_distance: float = 0.0    # metres around the current lap; negative before
                                 # crossing the S/F line (F1 grid / TT restart run-up)
    corner_cut_warnings: int = 0 # cumulative track-limit warnings this session (F1)

    # === SECTORS ===
    sector: int = 0              # current sector 0/1/2
    sector1_time: float = 0.0   # time at end of sector 1 this lap
    sector2_time: float = 0.0   # time at end of sector 2 this lap
    best_sector1: float = 0.0
    best_sector2: float = 0.0
    best_sector3: float = 0.0
    sector1_flag: str = ""       # "purple", "green", "yellow"
    sector2_flag: str = ""
    sector3_flag: str = ""

    # === RACE INFO ===
    position: int = 0
    total_cars: int = 0
    finish_status: str = ""      # "" while racing; "finished", "dnf", "dsq",
                                 # "not_classified", "retired" once the player's
                                 # result is decided (F1 resultStatus)
    classification_received: bool = False  # final classification packet arrived —
                                           # race results are saved; safe to exit
    gap_ahead: float = 0.0       # seconds to car ahead
    gap_behind: float = 0.0      # seconds to car behind
    name_ahead: str = ""         # driver name of car ahead (empty if unknown / P1)
    name_behind: str = ""        # driver name of car behind (empty if unknown / last)

    # === FLAGS ===
    flag: str = ""               # "green", "yellow", "red", "blue", "white", "chequered", "penalty"
    safety_car: str = ""         # "", "sc", "vsc"

    # === SESSION ===
    session_type: str = ""       # "practice", "qualifying", "race", "hotlap"
    session_subtype: str = ""    # finer-grained variant, e.g. "sprint_qualifying";
                                 # empty when the session is the plain session_type
    session_type_raw: int = -1   # game-specific raw session id (-1 = not provided);
                                 # logged to session CSVs for empirical mapping work
    session_time_remaining: float = 0.0
    game_paused: bool = False    # game is paused or in-menu mid-session

    # === WEATHER (session context — logged for cross-session comparison) ===
    weather: str = ""            # "clear", "light_cloud", "overcast", "light_rain",
                                 # "heavy_rain", "storm", "snow" ("" = not provided)
    air_temp: float = 0.0        # ambient °C (0.0 = not provided)
    track_temp: float = 0.0      # track surface °C (0.0 = not provided)

    # === ONE-SHOT INCIDENT EVENTS ===
    # Game-reported incidents involving the player, drained on every source
    # read() — each snapshot carries only the events since the previous one.
    # Entries: {"type", "detail", "lap_num", "lap_time", "distance"}.
    # Types: "collision", "penalty", "overtake", "overtaken".
    events: list = field(default_factory=list)

    # === PARTICIPANTS (multi-car data — qualifying leaderboard, etc.) ===
    # List of dicts sorted by position: [{"position": int, "name": str, "best_lap": float}, ...]
    # Only populated by sources that broadcast multi-car data (e.g. F1 2025).
    participants: list = field(default_factory=list)

    # === WORLD POSITION (track mapping / on-track position widget) ===
    # Metres in the game's world frame, re-expressed by each source into one
    # common convention: X and Z span the horizontal plane (top-down map),
    # Y is elevation (up). Only populated by sources that broadcast motion
    # data (F1 Motion packet; PCARS2 / Forza / GT7 to follow). `pos_valid`
    # distinguishes a genuine (0, 0, 0) origin from "no data this frame".
    pos_x: float = 0.0
    pos_y: float = 0.0           # elevation
    pos_z: float = 0.0
    heading: float = 0.0         # radians; yaw about the vertical axis in the
                                 # F1 convention: 0 faces +Z, increasing toward
                                 # +X, so forward = (sin h, cos h) in (x, z)
    pos_valid: bool = False      # True once a source has populated position

    # Per-frame snapshot of other active cars' world positions (same X/Z
    # horizontal convention; yaw same convention as `heading`). Player
    # excluded. Rebuilt wholesale each motion packet — never mutated.
    # [{"idx": int, "x": float, "z": float, "yaw": float}, ...]
    opponents_pos: list = field(default_factory=list)

    # === META (set by each telemetry source) ===
    game: str = ""               # "f1_25", "pcars2"
    car_class: str = ""          # "gt3", "gt4", "formula1", "f2", "formula_rookie", "karting"
    car_name: str = ""
    driver_name: str = ""
    team_id_raw: int = -1        # game-specific raw team id (-1 = not provided);
                                 # logged to session CSVs for empirical mapping work
    track: str = ""
    car_ordinal: int = 0         # game-specific numeric car ID (Forza: CarOrdinal)
