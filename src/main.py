import argparse
import os
import sys

# Ensure src/ is on the path when run directly
sys.path.insert(0, os.path.dirname(__file__))

import pygame
from core.app import App

import logging
log = logging.getLogger("main")

# Logs directory — one level above src/ (project root / logs/)
_LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
_TRACKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tracks")

# Default mock preset used when --mock is set and a game is chosen from the menu
_MOCK_PRESET_FOR_GAME = {
    "f1_25": "f1",
    "pcars2": "pcars2",
    "fh6": "fh6",
    "fm": "fm",
    "gt7": "gt7",
}


def _build_mock(preset: str, session: str | None):
    from telemetry.mock import MockTelemetry, PRESETS
    if preset not in PRESETS:
        print(f"Unknown mock preset '{preset}'. Available: {sorted(PRESETS)}")
        sys.exit(1)
    return MockTelemetry(preset=preset, session_type=session or None)


def _capture_path(game: str) -> str:
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(_LOGS_DIR, "captures", f"{game}_{ts}.srtc")


def _build_live(game: str, debug: bool = False, record: bool = False,
                port: int | None = None, gt7_ip: str | None = None):
    record_path = _capture_path(game) if record else None
    kwargs = {"record_path": record_path}
    if port is not None:
        kwargs["port"] = port

    if game == "f1_25":
        from telemetry.f1_2025 import F12025Telemetry
        return F12025Telemetry(debug=debug, **kwargs)
    elif game == "pcars2":
        from telemetry.pcars2 import PCARS2Telemetry
        return PCARS2Telemetry(**kwargs)
    elif game == "fh6":
        from telemetry.fh6 import FH6Telemetry
        return FH6Telemetry(**kwargs)
    elif game == "fm":
        from telemetry.fm import FMTelemetry
        return FMTelemetry(**kwargs)
    elif game == "gt7":
        from telemetry.gt7 import GT7Telemetry
        from core import config_store
        # CLI flag wins; otherwise config.json; otherwise broadcast discovery
        console_ip = gt7_ip or config_store.load().get("gt7_ip") or None
        return GT7Telemetry(console_ip=console_ip, **kwargs)
    else:
        print(f"Unknown game '{game}'. Choose from: f1_25, pcars2, fh6, fm, gt7")
        sys.exit(1)


def _init_display_and_splash(flip: bool, light: bool,
                             show_cursor: bool) -> pygame.Surface:
    """Create the fullscreen display and play the startup splash once, then
    return the screen. Shared by the menu path and the direct --game / --replay
    path so the splash shows on *every* launch. Exits if the user closes the
    window during the splash."""
    from core.splash import show_splash
    pygame.init()
    screen = pygame.display.set_mode((App.WIDTH, App.HEIGHT), pygame.FULLSCREEN)
    pygame.mouse.set_visible(show_cursor)
    pygame.display.set_caption("Shfonic Dash")
    if show_splash(screen, flip=flip, light=light):
        pygame.quit()
        sys.exit()
    return screen


def _run_menu_loop(fps: int, flip_arg: bool | None,
                   mock: bool = False, mock_preset: str | None = None,
                   mock_session: str | None = None,
                   show_cursor: bool | None = None,
                   debug: bool = False,
                   record: bool = False,
                   gt7_ip: str | None = None) -> None:
    """Show the game selection menu, run the chosen game, loop until quit."""
    from core.game_menu import GameMenu
    from core import config_store
    from core.log_server import LogServer
    from core.session_logger import SessionLogger, cleanup_trash
    from dashboard.widgets.themes import apply_theme, DEFAULT_THEME
    from dashboard.widgets.accents import apply_accent_mode, DEFAULT_ACCENT
    from dashboard.widgets.units import set_unit_system, DEFAULT_UNITS

    # CLI flag wins; otherwise the config file decides (default hidden — Pi
    # touchscreen). Same precedence pattern as --flip / --no-flip.
    if show_cursor is None:
        show_cursor = config_store.load().get("show_cursor", False)
    _splash_cfg  = config_store.load()
    initial_flip = flip_arg if flip_arg is not None else _splash_cfg.get("flip", True)
    screen = _init_display_and_splash(
        initial_flip, _splash_cfg.get("theme") == "light", show_cursor)

    # Create logging infrastructure once — shared across all game sessions.
    # Configure the tracks dir up front: the companion can sync track maps
    # while the Pi sits on the menu (DATA tab open), before any game session
    # has run — without this the /tracks PUT rejects with "tracks not
    # configured" (the in-game App path also sets it, but that's too late here).
    log_server     = LogServer()
    log_server.set_tracks_dir(_TRACKS_DIR)
    session_logger = SessionLogger(_LOGS_DIR)

    while True:
        config = config_store.load()
        theme  = config.get("theme", DEFAULT_THEME)
        apply_theme(theme)
        accent_mode = config.get("accent_mode", DEFAULT_ACCENT)
        apply_accent_mode(accent_mode)
        units = config.get("units", DEFAULT_UNITS)
        set_unit_system(units)
        flip = flip_arg if flip_arg is not None else config.get("flip", True)
        share_logs    = config.get("share_logs", False)
        window        = config_store.share_window_days(config)

        # Prune old trashed sessions on each menu return (session files in
        # logs/ itself are never deleted — they are the history database)
        cleanup_trash(_LOGS_DIR)

        menu = GameMenu(screen, config, mock_mode=mock, flip=flip,
                        log_server=log_server, logs_dir=_LOGS_DIR)
        selection = menu.run()

        if selection is None:
            break

        # Settings may have been changed from within the menu — reload
        config = config_store.load()
        theme = config.get("theme", DEFAULT_THEME)
        accent_mode = config.get("accent_mode", DEFAULT_ACCENT)
        units = config.get("units", DEFAULT_UNITS)
        set_unit_system(units)
        flip = flip_arg if flip_arg is not None else config.get("flip", True)
        share_logs = config.get("share_logs", False)
        window     = config_store.share_window_days(config)

        game_id, kwargs = selection
        game_label  = kwargs.get("game_name", "")
        game_color  = kwargs.get("game_color", None)
        record_track = kwargs.get("record_track", False)

        if mock:
            preset    = mock_preset or _MOCK_PRESET_FOR_GAME.get(game_id, "gt3")
            telemetry = _build_mock(preset, mock_session)
            log.info(f"Starting: mock ({preset}) | {fps} FPS | flip={'on' if flip else 'off'}")
        else:
            telemetry = _build_live(game_id, debug=debug, record=record, gt7_ip=gt7_ip)
            log.info(f"Starting: {game_id} | {fps} FPS | flip={'on' if flip else 'off'}")

        app = App(
            telemetry, fps=fps, flip_display=flip,
            game_label=game_label, game_color=game_color,
            theme=theme, accent_mode=accent_mode, units=units,
            show_cursor=show_cursor,
            session_logger=session_logger,
            log_server=log_server,
            share_logs=share_logs,
            share_window_days=window,
            logs_dir=_LOGS_DIR,
            show_session_summary=config.get("show_session_summary", True),
            debrief_enabled=config.get("debrief_enabled", True),
            record_track=record_track,
            tracks_dir=_TRACKS_DIR,
        )
        action = app.run(screen)

        if action == "quit":
            break

    session_logger.close()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shfonic Dash")

    parser.add_argument(
        "--game", type=str, default=None,
        choices=["f1_25", "pcars2", "fh6", "fm", "gt7"],
        help="Skip the menu and launch this game directly",
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="Use mock telemetry instead of live UDP",
    )
    parser.add_argument(
        "--mock-preset", type=str, default=None,
        metavar="PRESET",
        help="Mock preset: gt3, gt4, f1, f2, formula_rookie (auto-selected by game if omitted)",
    )
    parser.add_argument(
        "--mock-session", type=str, default=None,
        choices=["race", "practice", "qualifying", "hotlap"],
        help="Override session type for mock (default: from preset)",
    )
    parser.add_argument("--fps", type=int, default=30, help="Frames per second (default: 30)")
    parser.add_argument(
        "--flip", dest="flip", action="store_true",
        help="Flip display 180° (default on Pi)",
    )
    parser.add_argument(
        "--no-flip", dest="flip", action="store_false",
        help="Do not flip display (default on Mac/dev)",
    )
    parser.set_defaults(flip=None)
    parser.add_argument(
        "--show-cursor", dest="show_cursor", action="store_true",
        help="Show the mouse cursor (useful on Mac/dev without a touchscreen)",
    )
    parser.add_argument(
        "--hide-cursor", dest="show_cursor", action="store_false",
        help="Hide the mouse cursor (default on the Pi touchscreen)",
    )
    parser.set_defaults(show_cursor=None)   # None → use the config file value
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable verbose diagnostic output (delta milestones, reference profile details, etc.)",
    )
    parser.add_argument(
        "--gt7-ip", type=str, default=None, metavar="IP",
        help="PlayStation IP address for GT7 (default: config 'gt7_ip', else broadcast auto-discovery)",
    )
    parser.add_argument(
        "--record", action="store_true",
        help="Record raw UDP packets to logs/captures/ for later --replay",
    )
    parser.add_argument(
        "--replay", type=str, default=None, metavar="FILE",
        help="Replay a capture file recorded with --record (game auto-detected from the file)",
    )
    parser.add_argument(
        "--replay-speed", type=float, default=1.0,
        help="Replay speed multiplier (default: 1.0 = real time)",
    )
    args = parser.parse_args()

    # Console + size-capped rotating file log (logs/dashboard.log, ~3 MB max)
    from core import app_logging
    app_logging.setup(_LOGS_DIR, debug=args.debug)

    # --replay drives the direct-launch path with the game from the capture header
    _replayer = None
    if args.replay is not None:
        from telemetry.capture import CaptureReplayer
        _replayer = CaptureReplayer(args.replay, speed=args.replay_speed)
        args.game = _replayer.game
        args.mock = False
        _replayer.start()   # waits for the app's UDP source to bind before sending

    from core import config_store
    from dashboard.widgets.themes import apply_theme, DEFAULT_THEME
    from dashboard.widgets.accents import apply_accent_mode, DEFAULT_ACCENT
    from dashboard.widgets.units import set_unit_system, DEFAULT_UNITS

    _cfg    = config_store.load()
    _theme  = _cfg.get("theme", DEFAULT_THEME)
    apply_theme(_theme)
    _accent = _cfg.get("accent_mode", DEFAULT_ACCENT)
    apply_accent_mode(_accent)
    _units  = _cfg.get("units", DEFAULT_UNITS)
    set_unit_system(_units)
    _flip   = args.flip if args.flip is not None else _cfg.get("flip", True)
    _cursor = (args.show_cursor if args.show_cursor is not None
               else _cfg.get("show_cursor", False))

    # --game bypasses the menu — useful for autostart on Pi
    if args.game is not None:
        from core.game_menu import get_game_info
        from core.log_server import LogServer
        from core.session_logger import SessionLogger, cleanup_trash

        _share_logs = _cfg.get("share_logs", False)
        _window     = config_store.share_window_days(_cfg)
        _log_server     = LogServer()
        _log_server.set_window(_window)
        _log_server.set_token(config_store.api_token(_cfg))
        _log_server.set_tracks_dir(_TRACKS_DIR)
        _session_logger = SessionLogger(_LOGS_DIR)
        cleanup_trash(_LOGS_DIR)

        _info = get_game_info(args.game) or {}
        if args.mock:
            preset    = args.mock_preset or _MOCK_PRESET_FOR_GAME.get(args.game, "gt3")
            telemetry = _build_mock(preset, args.mock_session)
            mode      = f"mock ({preset})"
        else:
            telemetry = _build_live(
                args.game, debug=args.debug, record=args.record,
                port=_replayer.port if _replayer else None,
                gt7_ip=args.gt7_ip,
            )
            mode      = f"replay ({args.replay})" if _replayer else args.game
        log.info(f"Starting: {mode} | {args.fps} FPS | flip={'on' if _flip else 'off'}")
        # Splash first (same as the menu path), then reuse the screen for the App.
        _screen = _init_display_and_splash(_flip, _theme == "light", _cursor)
        App(
            telemetry, fps=args.fps, flip_display=_flip,
            game_label=_info.get("name", ""), game_color=_info.get("color", None),
            theme=_theme, accent_mode=_accent, units=_units,
            show_cursor=_cursor,
            session_logger=_session_logger,
            log_server=_log_server,
            share_logs=_share_logs,
            share_window_days=_window,
            logs_dir=_LOGS_DIR,
            show_session_summary=_cfg.get("show_session_summary", True),
            debrief_enabled=_cfg.get("debrief_enabled", True),
            tracks_dir=_TRACKS_DIR,
        ).run(_screen)
        _session_logger.close()
        pygame.quit()

    # Default: show the game selection menu (mock flag carried through)
    else:
        _run_menu_loop(
            fps=args.fps, flip_arg=_flip if args.flip is not None else None,
            mock=args.mock, mock_preset=args.mock_preset,
            mock_session=args.mock_session,
            show_cursor=args.show_cursor,
            debug=args.debug,
            record=args.record,
            gt7_ip=args.gt7_ip,
        )
