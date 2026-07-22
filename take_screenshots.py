#!/usr/bin/env python3
"""Regenerate all dashboard + menu screenshots."""

import os
import sys
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import pygame

pygame.init()
screen = pygame.display.set_mode((800, 480))

# Render every screenshot with the user's saved appearance settings (theme,
# accent, units) — mirrors main.py's startup so a "high contrast" config shows
# up in the shots rather than the default charcoal theme.
from core import config_store
from dashboard.widgets.themes import apply_theme, DEFAULT_THEME
from dashboard.widgets.accents import apply_accent_mode, DEFAULT_ACCENT
from dashboard.widgets.units import set_unit_system, DEFAULT_UNITS

_config = config_store.load()
apply_theme(_config.get("theme", DEFAULT_THEME))
apply_accent_mode(_config.get("accent_mode", DEFAULT_ACCENT))
set_unit_system(_config.get("units", DEFAULT_UNITS))
print(f'Appearance: theme={_config.get("theme", DEFAULT_THEME)}, '
      f'accent={_config.get("accent_mode", DEFAULT_ACCENT)}, '
      f'units={_config.get("units", DEFAULT_UNITS)}')

OUT = os.path.join(os.path.dirname(__file__), 'screenshots')
CFGS = os.path.join(os.path.dirname(__file__), 'src', 'dashboard', 'configs')


# ── helpers ───────────────────────────────────────────────────────────────────

def _manager(cfg_file):
    from core.dashboard_manager import DashboardManager
    return DashboardManager(800, 480, force_config=os.path.join(CFGS, cfg_file))


def _save(name):
    pygame.image.save(screen, os.path.join(OUT, f'{name}.png'))
    print(f'  {name}.png')


def _snapshot(preset, session, lap_num=8, total_laps=20, position=6):
    """Build a realistic mid-lap TelemetryData from a mock preset config."""
    from telemetry.mock import PRESETS, LAP_TIMES
    from core.telemetry_model import TelemetryData

    cfg  = PRESETS[preset]
    base = LAP_TIMES.get(cfg['car_class'], 90.0)

    # Mid-lap state: braking zone just passed, on throttle
    speed = round(cfg['max_speed'] * 0.72, 1)
    rpm   = int(cfg['max_rpm'] * 0.80)
    gear  = "5" if cfg['max_rpm'] >= 11000 else ("4" if cfg['max_rpm'] >= 8000 else "3")

    last_lap = round(base + random.uniform(-0.4, 1.2), 3)
    best_lap = round(base - 0.2, 3)
    lap_time = round(base * 0.55, 3)

    ers_energy      = 0.65 if cfg.get('has_ers') else 0.0
    ers_deploy_mode = 2    if cfg.get('has_ers') else 0
    drs_available   = cfg.get('has_drs', False)

    active_aero_mode      = ""
    active_aero_available = cfg.get('has_active_aero', False)
    if active_aero_available:
        active_aero_mode = "straight" if speed > 200 else "corner"
    boost_active = cfg.get('has_boost', False) and speed > 220

    fuel_remaining   = round(cfg['fuel_capacity'] * 0.48, 1)
    fuel_laps_left   = round(fuel_remaining / cfg['fuel_per_lap'], 1)

    return TelemetryData(
        gear=gear,
        speed=speed,
        rpm=rpm,
        max_rpm=cfg['max_rpm'],
        throttle=0.84,
        brake=0.0,
        lap_time=lap_time,
        last_lap=last_lap,
        best_lap=best_lap,
        delta=round(lap_time - base * 0.55 + random.uniform(-0.3, 0.5), 3),
        lap_number=lap_num,
        total_laps=total_laps,
        sector=1,
        sector1_time=round(base * 0.30, 3),
        best_sector1=round(base * 0.295, 3),
        best_sector2=round(base * 0.330, 3),
        best_sector3=round(base * 0.315, 3),
        sector1_flag='green',
        sector2_flag='',
        sector3_flag='',
        tyre_temp=tuple(cfg['tyre_temp_optimal']),
        tyre_pressure=tuple(cfg['tyre_pressure_target']),
        tyre_wear=(0.12, 0.11, 0.09, 0.08),
        tyre_compound=cfg['tyre_compound'],
        fuel_remaining=fuel_remaining,
        fuel_capacity=cfg['fuel_capacity'],
        fuel_per_lap=cfg['fuel_per_lap'],
        fuel_laps_remaining=fuel_laps_left,
        position=position,
        total_cars=total_laps,
        gap_ahead=1.84,
        gap_behind=0.52,
        name_ahead="VERSTAPPEN" if cfg['car_class'] in ('formula1', 'formula1_2026', 'f2') else "",
        name_behind="LECLERC"   if cfg['car_class'] in ('formula1', 'formula1_2026', 'f2') else "",
        session_type=session,
        game=cfg.get('game', 'pcars2'),
        car_class=cfg['car_class'],
        car_name=cfg.get('car_name', ''),
        flag='green',
        safety_car='',
        tc_level=cfg.get('tc_max', 0) // 2,
        abs_level=cfg.get('abs_max', 0) // 2,
        ers_stored_energy=ers_energy,
        ers_deploy_mode=ers_deploy_mode,
        drs_available=drs_available,
        drs_active=False,
        active_aero_mode=active_aero_mode,
        active_aero_available=active_aero_available,
        boost_active=boost_active,
    )


def race(name, preset, cfg, **overrides):
    random.seed(42)
    mgr  = _manager(cfg)
    data = _snapshot(preset, 'race')
    for k, v in overrides.items():
        setattr(data, k, v)
    mgr.update(data)
    mgr.render(screen)
    _save(name)


def practice(name, preset, cfg, prefill=8, **overrides):
    from telemetry.mock import MockTelemetry
    random.seed(42)
    mgr = _manager(cfg)
    # Populate lap history via prefill frames
    mock_pre = MockTelemetry(preset=preset, session_type='practice', prefill_laps=prefill)
    for frame in mock_pre.prefill_frames():
        mgr.update(frame)
    # Use a proper mid-lap snapshot as the current state
    data = _snapshot(preset, 'practice')
    for k, v in overrides.items():
        setattr(data, k, v)
    mgr.update(data)
    mgr.render(screen)
    _save(name)


_F2_GRID = [
    # (position, name, race_number, team_colour, best_lap_offset_from_p1)
    ( 1, "BORTOLETO",   5,  ( 82, 226, 155), 0.000),   # Sauber / Kick
    ( 2, "BEARMAN",    87,  (160, 160, 160), 0.187),   # Hitech
    ( 3, "HADJAR",      6,  ( 54, 113, 198), 0.334),   # DAMS
    ( 4, "CRAWFORD",   32,  (220,   0,   0), 0.491),   # Prema
    ( 5, "ANTONELLI",  12,  (  0, 210, 190), 0.623),   # ART
    ( 6, "DOOHAN",      7,  (255, 115, 160), 0.751),   # Carlin (player)
    ( 7, "MINI",       35,  (255, 135,   0), 0.889),   # MP
    ( 8, "STANEK",     37,  (100, 196, 255), 1.034),   # Trident
    ( 9, "MALONEY",    25,  ( 62,  97, 186), 1.192),   # Rodin
    (10, "MAINI",      10,  (200, 180,  50), 1.311),   # Invicta
    (11, "VERSCHOOR",  16,  (120,  80, 200), 1.453),
    (12, "O'SULLIVAN", 22,  (160, 160, 160), 1.574),
    (13, "FITTIPALDI",  4,  (220,   0,   0), 1.699),
    (14, "VESTI",       9,  (  0, 210, 190), 1.812),
    (15, "HAUGER",     27,  ( 54, 113, 198), 1.944),
    (16, "NOVALAK",    14,  (100, 196, 255), 2.083),
    (17, "COLAPINTO",  43,  (255, 115, 160), 2.218),
    (18, "PIZZI",      18,  ( 82, 226, 155), 2.367),
]

_F1_GRID = [
    # (position, name, race_number, team_colour, best_lap_offset_from_p1)
    ( 1, "NORRIS",      4,  (255, 135,   0), 0.000),   # McLaren papaya
    ( 2, "PIASTRI",    81,  (255, 135,   0), 0.213),
    ( 3, "VERSTAPPEN",  1,  ( 62,  97, 186), 0.381),   # Red Bull
    ( 4, "LECLERC",    16,  (220,   0,   0), 0.519),   # Ferrari
    ( 5, "HAMILTON",   44,  (220,   0,   0), 0.602),
    ( 6, "RUSSELL",    63,  (  0, 210, 190), 0.714),   # Mercedes (player)
    ( 7, "ANTONELLI",  12,  (  0, 210, 190), 0.851),
    ( 8, "SAINZ",      55,  (100, 196, 255), 1.073),   # Williams
    ( 9, "ALONSO",     14,  (  0, 111,  98), 1.244),   # Aston Martin
    (10, "HADJAR",      6,  ( 54, 113, 198), 1.388),   # Racing Bulls
    (11, "TSUNODA",    22,  ( 54, 113, 198), 1.512),
    (12, "HULKENBERG", 27,  ( 82, 226, 155), 1.634),   # Sauber
    (13, "LAWSON",     30,  ( 62,  97, 186), 1.719),
    (14, "STROLL",     18,  (  0, 111,  98), 1.843),
    (15, "ALBON",      23,  (100, 196, 255), 1.952),
    (16, "GASLY",      10,  (255, 115, 160), 2.084),   # Alpine
    (17, "DOOHAN",      7,  (255, 115, 160), 2.193),
    (18, "BORTOLETO",   5,  ( 82, 226, 155), 2.318),
    (19, "OCON",       31,  (160, 160, 160), 2.477),   # Haas
    (20, "BEARMAN",    87,  (160, 160, 160), 2.639),
]


def qualifying(name, preset, cfg, player_pos=6, prefill=6, grid=None, **overrides):
    from telemetry.mock import MockTelemetry, LAP_TIMES, PRESETS
    random.seed(42)
    mgr = _manager(cfg)

    mock_pre = MockTelemetry(preset=preset, session_type='qualifying', prefill_laps=prefill)
    for frame in mock_pre.prefill_frames():
        mgr.update(frame)

    data = _snapshot(preset, 'qualifying', position=player_pos)

    base = LAP_TIMES.get(PRESETS[preset]['car_class'], 90.0)
    p1_best = base - 1.5
    source = grid if grid is not None else _F1_GRID
    parts = [
        {
            "position":    pos,
            "name":        nm,
            "race_number": rn,
            "team_colour": col,
            "best_lap":    round(p1_best + offset, 3),
        }
        for pos, nm, rn, col, offset in source
    ]
    data.participants = parts
    data.total_cars   = len(parts)

    for k, v in overrides.items():
        setattr(data, k, v)
    mgr.update(data)
    mgr.render(screen)
    _save(name)


_REAL_LOGS = os.path.join(os.path.dirname(__file__), 'logs')


def menu(name, mock_mode=False, sync=False, picker=False, real=False,
         logs_dir=None):
    """Render the game menu. When `real` is set, the home screen is populated
    from the actual logs/ archive (DRIVER PROFILE grade, records, last game and
    real latest milestone) instead of the synthetic placeholder milestone.
    Pass `logs_dir` to populate the home from a specific archive (e.g. the
    synthetic one seeded by `_seed_home_archive()` — a believable driver profile
    with no personal data)."""
    from core.game_menu import GameMenu
    from core import config_store

    class _FakeServer:
        url = "127.0.0.1:8765"
        running = True

    home_dir = logs_dir if logs_dir is not None else (_REAL_LOGS if real else "")
    m = GameMenu(screen, config_store.load(), mock_mode=mock_mode,
                 log_server=_FakeServer() if sync else None,
                 logs_dir=home_dir)
    if real or logs_dir is not None:
        # _scan_milestone() kicks off a background thread; run the load
        # synchronously so the data is present before we draw a single frame.
        m._load_home()
    else:
        m._milestone = {
            "title":     "NEW PERSONAL BEST — 1:28.402",
            "context":   "LATEST MILESTONE  ·  F1 25  ·  F1 2026  ·  MONZA  ·  5 JUL",
            "icon":      "trophy",
            "celebrate": True,
            "filename":  "",
        }
    if sync:
        m._show_sync = True    # SYNC pill is opt-in (Pythonista companion)
        m._share_logs = True
        m._waiting = 3
    if picker:
        buttons = m._build_buttons()
        back_rect = m._picker_pill_rect("_back")
        record_rect = (m._picker_pill_rect("_record")
                       if m._record_enabled else None)
        m._draw_picker(buttons, back_rect, record_rect, None)
    else:
        m._draw_home(m._sync_rect(), m._power_rect(), None)
    _save(name)


_SUMMARY_LAP_HEADER = (
    'H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,'
    'tyre_compound,fuel_remaining,fuel_per_lap,position,delta,invalid,rewinds')


def _summary_csv(times, session_type, started, track='Silverstone',
                 invalid=(), rewound=(), positions=None, events=()):
    rows = [
        'S,version,1',
        f'S,started_at,{started}',
        'S,game,f1_25',
        f'S,session_type,{session_type}',
        'S,car_class,formula1',
        'S,car_name,McLaren',
        'S,driver_name,PIASTRI',
        f'S,track,{track}',
    ]
    if events:
        rows.append('EH,lap_num,lap_time,type,distance,t,detail')
        rows += [f'E,{e}' for e in events]
    rows.append(_SUMMARY_LAP_HEADER)
    for i, t in enumerate(times, start=1):
        inv = 1 if i in invalid else 0
        rew = 1 if i in rewound else 0
        pos = positions[i - 1] if positions else ''
        # Vary the sector split per lap so the theoretical best (best
        # sectors from different laps) lands under the fastest lap.
        j  = (i % 3) * 0.004
        s1 = round(t * (0.31 + j), 3)
        s2 = round(t * (0.33 - j * 2), 3)
        s3 = round(t - s1 - s2, 3)
        cmp_ = 'Soft' if i <= max(2, len(times) // 2) else 'Medium'
        rows.append(f'L,{i},{t},{s1},{s2},{s3},96,94,88,90,{cmp_},,,{pos},,{inv},{rew}')
    return '\n'.join(rows) + '\n'


def session_summary(name, session_type, times, prior_times=None, **csv_kwargs):
    """Render the end-of-session summary for a synthetic session CSV."""
    import tempfile
    from core.session_summary import SessionSummaryView, build_summary

    d = tempfile.mkdtemp()
    if prior_times:
        with open(os.path.join(d, f'session_20260701_1400_{session_type}.csv'),
                  'w') as f:
            f.write(_summary_csv(prior_times, session_type, '2026-07-01T14:00:00'))
    path = os.path.join(d, f'session_20260707_1930_{session_type}.csv')
    with open(path, 'w') as f:
        f.write(_summary_csv(times, session_type, '2026-07-07T19:30:00',
                             **csv_kwargs))
    summary = build_summary(path)
    SessionSummaryView(summary).render(screen)
    _save(name)


def _seed_home_archive():
    """Write a believable multi-game session archive to a temp dir so the menu
    home shows a populated DRIVER PROFILE (grade + games/sessions/trophies
    counts + a real latest-PB milestone) — synthetic data only, no personal
    logs. Returns the directory path."""
    import tempfile
    d = tempfile.mkdtemp()
    sessions = [
        # (filename, times, session_type, started, extra kwargs)
        ('session_20260612_1930_race.csv',
         [93.4, 92.6, 92.9, 92.5, 92.7, 92.4, 92.5, 92.3], 'race',
         '2026-06-12T19:30:00', dict(positions=[9, 8, 7, 7, 6, 6, 5, 5])),
        ('session_20260615_2015_qualifying.csv',
         [91.2, 90.7, 90.9], 'qualifying', '2026-06-15T20:15:00', {}),
        ('session_20260619_1000_hotlap.csv',
         [89.9, 89.3, 89.1, 89.4, 88.9], 'hotlap', '2026-06-19T10:00:00', {}),
        ('session_20260624_1930_practice.csv',
         [91.5, 90.9, 90.6, 90.8, 90.5, 90.7], 'practice',
         '2026-06-24T19:30:00', {}),
        ('session_20260628_2000_race.csv',
         [92.9, 92.1, 92.4, 92.0, 92.3, 92.1], 'race', '2026-06-28T20:00:00',
         dict(positions=[6, 5, 5, 4, 4, 3])),
        ('session_20260703_1945_qualifying.csv',
         [90.8, 90.2, 90.4], 'qualifying', '2026-07-03T19:45:00', {}),
        ('session_20260709_1000_hotlap.csv',
         [89.1, 88.7, 88.402, 88.6, 88.5], 'hotlap', '2026-07-09T10:00:00', {}),
        ('session_20260714_1930_practice.csv',
         [90.6, 90.1, 89.9, 90.2, 89.8, 90.0], 'practice',
         '2026-07-14T19:30:00', {}),
    ]
    for i, (fname, times, stype, started, kw) in enumerate(sessions):
        text = _summary_csv(times, stype, started, **kw)
        # A couple of sessions on a second game so GAMES reads > 1.
        if i in (1, 5):
            text = (text.replace('S,game,f1_25', 'S,game,pcars2')
                        .replace('S,car_name,McLaren', 'S,car_name,Formula Renault 3.5')
                        .replace('S,car_class,formula1', 'S,car_class,pcars2'))
        with open(os.path.join(d, fname), 'w') as f:
            f.write(text)
    return d


# ── generate ──────────────────────────────────────────────────────────────────

print('Generating screenshots...')

# Menu — the README/home shot is populated from a synthetic archive (grade,
# records, trophies, latest-PB milestone) so it shows a believable driver
# profile rather than an empty first-run state. No personal data.
menu('menu', logs_dir=_seed_home_archive())
menu('menu_empty')
menu('menu_mock', mock_mode=True)
menu('menu_sync', sync=True)
menu('menu_picker', picker=True)
menu('menu_picker_mock', mock_mode=True, picker=True)
menu('menu_real', real=True)            # home populated from the real logs/ archive

# Light-theme variants — the rest of the set renders in the saved theme; these
# two show how the menu + a live dashboard look under the Light theme. Restore
# the saved theme immediately afterwards so nothing below is affected.
apply_theme('light')
menu('menu_light', real=True)
race('formula1_race_light', 'f1', 'formula1_race.json')
apply_theme(_config.get('theme', DEFAULT_THEME))

# GT3
race('gt3_race',        'gt3', 'gt3_race.json')
race('gt3_race_yellow', 'gt3', 'gt3_race.json', flag='yellow')
race('gt3_race_sc',     'gt3', 'gt3_race.json', safety_car='sc')
practice('gt3_practice', 'gt3', 'gt3_practice.json')

# GT4
race('gt4_race',         'gt4', 'gt4_race.json')
practice('gt4_practice', 'gt4', 'gt4_practice.json')

# F1 2025
race('formula1_race',                  'f1', 'formula1_race.json')
race('formula1_race_red',              'f1', 'formula1_race.json', flag='red')
race('formula1_race_pit_limiter',      'f1', 'formula1_race.json', pit_limiter=True, speed=69.0, rpm=3750, gear='2')
practice('formula1_practice',          'f1', 'formula1_practice.json')
qualifying('formula1_qualifying',      'f1', 'formula1_qualifying.json')

# Formula Ford / Formula Rookie — LCD-style dashboard
race('formula_ford_race',        'formula_rookie', 'lcd_race.json')
practice('formula_ford_practice', 'formula_rookie', 'lcd_practice.json')

# F1 2026
race('formula1_2026_race',             'f1_26', 'formula1_2026_race.json')
race('formula1_2026_race_results_pending', 'f1_26', 'formula1_2026_race.json',
     finish_status='finished', speed=0.0, rpm=0, gear='N', throttle=0.0)
race('formula1_2026_race_results_saved',   'f1_26', 'formula1_2026_race.json',
     finish_status='finished', classification_received=True,
     speed=0.0, rpm=0, gear='N', throttle=0.0)
practice('formula1_2026_practice',     'f1_26', 'formula1_2026_practice.json')
qualifying('formula1_2026_qualifying', 'f1_26', 'formula1_2026_qualifying.json')

# F2
race('f2_race',             'f2', 'f2_race.json')
practice('f2_practice',     'f2', 'f2_practice.json')
qualifying('f2_qualifying', 'f2', 'f2_qualifying.json', player_pos=6, grid=_F2_GRID)

# Forza Horizon 6
race('fh6_race',         'fh6', 'fh6_race.json')
practice('fh6_practice', 'fh6', 'fh6_practice.json')

# Forza Motorsport
race('fm_race',         'fm', 'fm_race.json')
practice('fm_practice', 'fm', 'fm_practice.json')

# Gran Turismo 7
race('gt7_race',         'gt7', 'gt7_race.json')
practice('gt7_practice', 'gt7', 'gt7_practice.json')

def history_shots():
    """History browser list + detail over a synthetic logs dir."""
    import tempfile
    from core.history_browser import HistoryBrowser

    d = tempfile.mkdtemp()
    sessions = [
        ('session_20260701_1400_practice.csv',
         _summary_csv([91.0, 90.4, 90.8, 91.5], 'practice', '2026-07-01T14:00:00')),
        ('session_20260703_2010_qualifying.csv',
         _summary_csv([90.9, 90.1, 90.6], 'qualifying', '2026-07-03T20:10:00',
                      track='Monaco')
         .replace('S,game,f1_25', 'S,game,pcars2')
         .replace('S,car_name,McLaren', 'S,car_name,Formula Renault 3.5')
         .replace('S,car_class,formula1', 'S,car_class,pcars2')),
        ('session_20260705_1930_race.csv',
         _summary_csv([93.5, 92.1, 92.5, 92.9, 92.2, 92.7, 92.4, 92.5],
                      'race', '2026-07-05T19:30:00',
                      positions=[8, 7, 7, 6, 6, 6, 5, 5], rewound={3},
                      events=('2,20.5,collision,850.0,112.4,VERSTAPPEN',
                              '3,15.2,rewind,,205.0,'))
         + 'F,clean\nD,feeling,frustrated\nD,goal,race_prep\n'),
        ('session_20260707_1930_race.csv',
         _summary_csv([92.8, 92.0, 92.3, 92.6, 92.1, 92.4], 'race',
                      '2026-07-07T19:30:00', invalid={4})),
    ]
    for fname, text in sessions:
        with open(os.path.join(d, fname), 'w') as f:
            f.write(text)

    b = HistoryBrowser(screen, d)
    b._load_rows()
    b._draw_list()
    _save('history_list')

    b._open_detail(b._rows[1])   # the 2026-07-05 race (events + standings-rich)
    b._draw_detail()
    _save('history_detail')


history_shots()


def pre_session_shot():
    """Pre-session NEXT GOAL card over a synthetic logs dir."""
    import tempfile
    from core.pre_session import PreSessionView, build_pre_session
    from core.telemetry_model import TelemetryData

    d = tempfile.mkdtemp()
    with open(os.path.join(d, 'session_20260705_1000_hotlap.csv'), 'w') as f:
        f.write(_summary_csv([89.2, 88.61, 88.9, 89.4, 88.7, 89.0],
                             'hotlap', '2026-07-05T10:00:00',
                             invalid={4}, rewound={5}))
    goal = build_pre_session(d, TelemetryData(
        game='f1_25', car_class='formula1', track='Silverstone',
        session_type='hotlap'))
    PreSessionView(goal).render(screen)
    _save('pre_session')


pre_session_shot()


def trophies_shot():
    """Career badge gallery over a synthetic archive that earns a
    believable spread of trophies (mix of earned + unearned outlines)."""
    import tempfile
    from core.trophies_browser import TrophiesBrowser

    d = tempfile.mkdtemp()

    def _write(fname, times, session_type, started, **kw):
        with open(os.path.join(d, fname), 'w') as f:
            f.write(_summary_csv(times, session_type, started, **kw))

    # Four Silverstone practices, best lap improving each time → PB
    # streak (On a Roll), half-second leaps (Breakthrough), clean 10-lap
    # runs (Clean Sweep / Metronome). First is in the small hours
    # (Night Shift).
    _write('session_20260620_0215_practice.csv',
           [92.6, 92.3, 92.0, 92.4, 92.2, 92.1, 92.5, 92.3, 92.2, 92.4],
           'practice', '2026-06-20T02:15:00')
    _write('session_20260622_1930_practice.csv',
           [92.0, 91.7, 91.4, 91.8, 91.6, 91.5, 91.9, 91.6, 91.5, 91.7],
           'practice', '2026-06-22T19:30:00')
    _write('session_20260624_1930_practice.csv',
           [91.4, 91.1, 90.8, 91.2, 91.0, 90.9, 91.3, 91.0, 90.9, 91.1],
           'practice', '2026-06-24T19:30:00')
    _write('session_20260626_1930_practice.csv',
           [90.8, 90.5, 90.2, 90.6, 90.4, 90.3, 90.7, 90.4, 90.3, 90.5],
           'practice', '2026-06-26T19:30:00')

    # Four more tracks → Globetrotter, and career laps → Century.
    for i, track in enumerate(('Monaco', 'Spa', 'Suzuka', 'Monza')):
        _write(f'session_2026062{i}_1500_practice.csv',
               [91.5, 91.2, 90.9, 91.3, 91.1, 91.0, 91.4, 91.1, 90.9, 91.2,
                91.0, 90.8, 91.1, 90.9, 91.2],
               'practice', f'2026-06-2{i}T15:00:00', track=track)

    # A race win at Silverstone → First Blood + Winner + Podium.
    _write('session_20260628_2000_race.csv',
           [93.5, 92.8, 92.4, 92.6, 92.3, 92.5, 92.2, 92.4],
           'race', '2026-06-28T20:00:00',
           positions=[3, 2, 2, 1, 1, 1, 1, 1])
    # A P3 race at Monaco → another Podium.
    _write('session_20260630_2000_race.csv',
           [93.2, 92.6, 92.3, 92.5, 92.2, 92.4],
           'race', '2026-06-30T20:00:00', track='Monaco',
           positions=[6, 5, 4, 4, 3, 3])

    # A Project CARS 2 qualifying session → Multi-Disciplined (2 games).
    with open(os.path.join(d, 'session_20260702_1930_qualifying.csv'),
              'w') as f:
        f.write(_summary_csv([90.9, 90.4, 90.6, 90.3, 90.5],
                             'qualifying', '2026-07-02T19:30:00',
                             track='Brands Hatch')
                .replace('S,game,f1_25', 'S,game,pcars2')
                .replace('S,car_name,McLaren', 'S,car_name,Ginetta G40')
                .replace('S,car_class,formula1', 'S,car_class,pcars2'))

    b = TrophiesBrowser(screen, d)
    b._load()
    b._draw()
    _save('trophies')
    print(f'    ({b._earned_n} of {b._total_n} badges earned)')

    # Detail card for an earned badge with several sessions, and the
    # how-to card for one still on the board.
    earned = next((e for e in b._entries if e[0] == 'badge'
                   and e[2] is not None and len(e[2].get('sessions', [])) > 1),
                  None)
    if earned:
        b._open_detail(earned[1], earned[2])
        b._draw_detail()
        _save('trophies_detail')
    unearned = next((e for e in b._entries
                     if e[0] == 'badge' and e[2] is None), None)
    if unearned:
        b._open_detail(unearned[1], unearned[2])
        b._draw_detail()
        _save('trophies_detail_unearned')


trophies_shot()


def debrief_shots():
    """Post-session driver debrief question screens."""
    from core.debrief import DebriefScreen
    from sessionlog.debrief import QUESTIONS

    DebriefScreen(QUESTIONS['feeling'], 1, 3,
                  sub='Silverstone  ·  Hotlap  ·  7 laps just now').render(screen)
    _save('debrief_feeling')
    DebriefScreen(QUESTIONS['invalid_cause'], 3, 3).render(screen)
    _save('debrief_question')


debrief_shots()


# End-of-session summary
session_summary('session_summary_practice', 'practice',
                [92.104, 90.512, 90.887, 91.203, 90.699, 92.441, 90.523],
                prior_times=[91.0, 90.4, 90.8],
                invalid={6})
session_summary('session_summary_race', 'race',
                [93.511, 92.104, 92.512, 92.887, 92.203, 92.699, 92.441,
                 92.523, 92.310, 92.150],
                prior_times=[92.9, 92.3, 92.6, 92.5],
                positions=[8, 7, 7, 6, 6, 6, 5, 5, 5, 5],
                rewound={3},
                events=('2,20.5,collision,850.0,112.4,VERSTAPPEN',
                        '3,15.2,rewind,,205.0,',
                        '7,44.1,overtake,2100.0,610.2,LECLERC'))


def track_recorder_shots():
    """Track recorder live view, driven through its phases on the REAL
    Silverstone geometry so the on-screen trace matches the actual circuit.

    The recorder needs a driven sequence (not a static snapshot), so it is fed
    the recorded left edge, right edge, racing line and pit lane straight out of
    tracks/f1-25_silverstone.json — the same points the map already holds. Each
    phase drives its own polyline; the mid-lap 'recording' shot is caught while
    only part of a lap has been traced, the 'complete' and 'pit' shots after the
    full geometry is in."""
    import json
    import math
    import tempfile
    from core.telemetry_model import TelemetryData
    from dashboard.track_recorder_dashboard import TrackRecorderDashboard
    from core.track_recorder import State

    tm    = json.load(open(os.path.join(os.path.dirname(__file__),
                                        'tracks', 'f1-25_silverstone.json')))
    LEFT  = tm['left_edge']
    RIGHT = tm['right_edge']
    LINE  = tm['lines']['formula1']['racing_line']
    PIT   = tm['pit_lane']
    TL    = tm['game_track_length_m']
    SB    = [b['lap_dist_m'] for b in tm['sectors']]   # two sector boundaries

    dash = TrackRecorderDashboard(800, 480, tracks_dir=tempfile.mkdtemp())
    lap = [1]

    def _sector(dist):
        return 0 if dist < SB[0] else (1 if dist < SB[1] else 2)

    def frame(poly, i, last=0.0):
        """One frame at vertex i of a closed polyline: position, tangent
        heading (F1 convention forward = (sin h, cos h)) and the lap distance /
        sector that vertex sits at."""
        m = len(poly)
        x, z = poly[i % m]
        nx, nz = poly[(i + 1) % m]
        h = math.atan2(nx - x, nz - z)
        dist = (i % m) / m * TL
        return TelemetryData(
            pos_valid=True, pos_x=x, pos_z=z, heading=h,
            lap_distance=dist, sector=_sector(dist), lap_number=lap[0],
            lap_time=(i % m) / m * 90, last_lap=last, in_pits=False,
            track='Silverstone', game='f1_25', car_class='formula1')

    def cross(poly, last=88.5):
        lap[0] += 1
        dash.update(frame(poly, 0, last=last))

    def feed(poly, lo, hi):
        m = len(poly)
        for i in range(int(m * lo), int(m * hi)):
            dash.update(frame(poly, i))

    # Ready state — idling on the left edge with the START button, before the
    # first recording. (Advance past the transient note without crossing S/F.)
    for i in range(0, len(LEFT) - 1):
        dash.update(frame(LEFT, i))
    dash.render(screen); _save('track_recorder_ready')

    # Left edge — press START, cross the line, snapshot part-way round.
    dash._do('start'); cross(LEFT); feed(LEFT, 0.0, 0.6)
    dash.render(screen); _save('track_recorder_recording')
    feed(LEFT, 0.6, 1.0); cross(LEFT); dash._do('accept')

    # Right edge, then three racing-line laps → complete. Each begins with START.
    dash._do('start'); cross(RIGHT); feed(RIGHT, 0.0, 1.0); cross(RIGHT); dash._do('accept')
    for _ in range(3):
        dash._do('start'); cross(LINE); feed(LINE, 0.0, 1.0); cross(LINE); dash._do('accept')
    assert dash.recorder.state == State.DONE
    dash.render(screen); _save('track_recorder_complete')

    # Optional pit-lane pass — the real recorded pit trip (entry road → lane →
    # exit road). Densify the 15 saved vertices for a smooth trace, and drive an
    # on-track lead-in first so the pass registers a genuine pit entry.
    dash._do('add_pit')

    def pit_frame(x, z, in_pits, limiter=False):
        return TelemetryData(
            pos_valid=True, pos_x=x, pos_z=z, heading=0.0, speed=60.0,
            lap_distance=-1, sector=0, lap_number=lap[0], lap_time=0,
            in_pits=in_pits, pit_limiter=limiter,
            track='Silverstone', game='f1_25', car_class='formula1')

    # Lead-in on the racing line up to the pit entry (so _pit_seen_track arms).
    for i in range(345, 360):
        x, z = LINE[i % len(LINE)]
        dash.update(pit_frame(x, z, in_pits=False))
    # The pit lane itself — densified, limiter on, in the pits.
    for a, b in zip(PIT, PIT[1:]):
        for k in range(8):
            t = k / 8.0
            dash.update(pit_frame(a[0] + (b[0] - a[0]) * t,
                                  a[1] + (b[1] - a[1]) * t,
                                  in_pits=True, limiter=True))
    # Rejoin the racing line — limiter off, back on track → capture ends.
    ex, ez = PIT[-1]
    dash.update(pit_frame(ex, ez, in_pits=False, limiter=False))
    dash.render(screen); _save('track_recorder_pit')


track_recorder_shots()

pygame.quit()
print('\nDone.')
