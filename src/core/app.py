import math
import sys
import time
import pygame

from core.dashboard_manager import DashboardManager
from core.flip import flip_pos, flip_surface

# Long-press starts showing the indicator after this many seconds of holding
_INDICATOR_DELAY = 0.2

# Below this speed (km/h) a zero-lap car counts as sitting in the garage —
# the pre-session card's "in the garage" signal when the game isn't paused
# (F1 Time Trial reports neither game_paused nor in_pits there).
_GARAGE_SPEED_KMH = 5.0


class App:
    WIDTH, HEIGHT = 800, 480
    QUIT_HOLD_SECONDS = 2.0

    def __init__(
        self,
        telemetry_source,
        fps: int = 30,
        flip_display: bool = True,
        force_config: str = None,
        game_label: str = "",
        game_color: tuple = None,
        theme: str = "charcoal",
        accent_mode: str = "standard",
        units: str = "metric",
        show_cursor: bool = False,
        session_logger=None,
        log_server=None,
        share_logs: bool = False,
        share_window_days: int = 7,
        logs_dir: str = "",
        show_session_summary: bool = True,
        debrief_enabled: bool = True,
        record_track: bool = False,
        tracks_dir: str = "",
    ):
        self._telemetry          = telemetry_source
        self._fps                = fps
        self._flip               = flip_display
        self._force_config       = force_config
        self._game_label         = game_label
        self._game_color         = game_color
        self._current_theme      = theme
        self._current_accent     = accent_mode
        self._current_units      = units
        self._show_cursor        = show_cursor
        self._session_logger     = session_logger
        self._log_server         = log_server
        self._share_logs         = share_logs
        self._share_window       = share_window_days
        self._logs_dir           = logs_dir
        self._show_summary       = show_session_summary
        self._debrief_enabled    = debrief_enabled
        self._record_track       = record_track
        self._tracks_dir         = tracks_dir
        # Recording a track is not a driven session — never log it as an attempt.
        if record_track:
            self._session_logger = None
        # End-of-session summary overlay state (set on session rotation)
        self._summary_view       = None
        self._pit_card_shown     = False
        self._pre_session_shown  = False   # per-session latch for the
                                           # zero-lap garage NEXT GOAL card
        self._pre_session_diag   = False   # one-shot "why not shown" log
        self._debrief_after      = None   # csv path to debrief once its
                                          # rotation summary is dismissed
        self._drive_detector     = None

    def _ensure_always_web_server(self) -> None:
        """Start the log server for the web companion when web_app_mode is
        'always' so /app is reachable during gameplay. Modes 'menu'/'off' leave
        the gameplay server down (started only while settings are open)."""
        if self._log_server is None:
            return
        from core import config_store
        mode = config_store.web_app_mode(config_store.load())
        self._log_server.set_web_enabled(mode != "off")
        if mode == "always":
            self._log_server.set_token(config_store.api_token(config_store.load()))
            self._log_server.set_window(self._share_window)
            self._log_server.set_tracks_dir(self._tracks_dir)
            if not self._log_server.running:
                self._log_server.start(self._logs_dir)

    def run(self, screen: pygame.Surface | None = None) -> str:
        """
        Run the dashboard loop.

        Pass an existing pygame Surface to reuse it (menu-flow mode).
        When screen is None, pygame is initialised here and sys.exit() is called
        on shutdown (legacy / direct-launch behaviour).

        Returns "menu" (go back to game menu) or "quit" (exit completely).
        Long-press (2 s) returns "menu"; Ctrl+Q / window-close returns "quit".
        """
        own_pygame = screen is None
        if own_pygame:
            pygame.init()
            screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT), pygame.FULLSCREEN)
            pygame.mouse.set_visible(self._show_cursor)
            pygame.display.set_caption("Shfonic Dash")

        # Web companion set to "always" keeps the server up during gameplay so a
        # phone on the LAN works mid-session (opt-in — for powerful Pis).
        self._ensure_always_web_server()

        clock = pygame.time.Clock()
        if self._record_track:
            # Track-recorder mode: a full-screen live tracing view stands in for
            # the dashboard manager. No session logger, summary, pit card or
            # debrief runs (the logger is None), so recording never surfaces as
            # a driven session.
            from dashboard.track_recorder_dashboard import TrackRecorderDashboard
            from core import config_store
            manager = TrackRecorderDashboard(
                self.WIDTH, self.HEIGHT, tracks_dir=self._tracks_dir,
                author=config_store.author(config_store.load()))
        else:
            manager = DashboardManager(
                self.WIDTH, self.HEIGHT,
                force_config=self._force_config,
                game_label=self._game_label,
                game_color=self._game_color,
                telemetry_port=self._telemetry.port,
            )

        self._telemetry.connect()

        result = "menu"
        running = True
        touch_start_time = None
        touch_active = False
        prev_session_file = (self._session_logger.active_file
                             if self._session_logger else None)
        prev_paused = False

        while running:
            for event in pygame.event.get():
                if hasattr(event, "pos"):
                    event.pos = flip_pos(event.pos, self._flip)

                if event.type == pygame.QUIT:
                    result = "quit"
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        result = "menu"
                        running = False
                    elif event.key == pygame.K_q and pygame.key.get_mods() & pygame.KMOD_CTRL:
                        result = "quit"
                        running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    touch_start_time = time.time()
                    touch_active = True

                elif event.type == pygame.MOUSEBUTTONUP:
                    touch_start_time = None
                    touch_active = False
                    if self._summary_view is not None:
                        # Tap dismisses the summary (or answers a debrief
                        # question); don't let the release reach the
                        # dashboard as a swipe.
                        if hasattr(self._summary_view, "tap"):
                            if self._summary_view.tap(event.pos):
                                self._dismiss_summary(manager)
                        else:
                            self._dismiss_summary(manager)
                        continue

                # The summary is a full-screen modal — the dashboard
                # doesn't receive events (no accidental config swipes).
                if self._summary_view is None:
                    manager.handle_event(event)

            hold_duration = (time.time() - touch_start_time) if touch_active and touch_start_time else 0.0

            data = self._telemetry.read()
            manager.update(data)
            if self._session_logger is not None:
                self._session_logger.update(data)
                new_file = self._session_logger.active_file
                if new_file != prev_session_file:
                    # A fresh session file — re-arm the pre-session card so the
                    # new session gets its own NEXT GOAL if it starts paused.
                    self._pre_session_shown = False
                    self._pre_session_diag = False
                    if prev_session_file is not None:
                        # Session rotated (e.g. practice -> qualifying): the old
                        # file just closed — summarise it over the new session,
                        # and queue its debrief for when the summary is tapped
                        # away (the only end-of-session moment an in-game switch
                        # ever gets).
                        self._show_summary_for(prev_session_file)
                        if self._debrief_enabled and self._summary_view is not None:
                            self._debrief_after = prev_session_file
                prev_session_file = new_file

            # Pre-session goals card (see _pre_session_due): latched, not
            # edge-triggered, because the combo metadata arrives after pause.
            if self._pre_session_due(
                    data,
                    pre_session_shown=self._pre_session_shown,
                    summary_active=self._summary_view is not None,
                    active_file=(self._session_logger.active_file
                                 if self._session_logger else None),
                    lap_count=(self._session_logger.lap_count
                               if self._session_logger else 0)):
                self._pre_session_shown = True
                self._show_pre_session_for(data)

            # Pause-screen summary: sessions that never rotate (hotlap/TT has
            # no "next session") and are never exited to the menu would
            # otherwise never show one. On the pause rising edge, summarise
            # the session so far from the still-open file (writes are
            # flushed per row; Z-row stats fall back to computed values).
            # Resuming and driving auto-dismisses; the next pause shows a
            # fresh summary including the new laps.
            elif (data.game_paused and not prev_paused
                    and self._summary_view is None
                    and self._session_logger is not None
                    and self._session_logger.active_file
                    and self._session_logger.lap_count > 0):
                self._show_summary_for(self._session_logger.active_file)
            prev_paused = data.game_paused

            # Diagnostic (once per session): we're in a garage-like state
            # (paused or in the pits) with no card up and the trigger hasn't
            # fired — log exactly which precondition is missing so a "card not
            # showing" report is traceable without a capture. _pre_session_due
            # needs game_paused AND a track AND an open file AND zero laps.
            if (not self._pre_session_shown and not self._pre_session_diag
                    and self._summary_view is None
                    and self._session_logger is not None
                    and (data.game_paused or data.in_pits)):
                self._pre_session_diag = True
                import logging
                logging.getLogger("pre_session").info(
                    "pre-session not triggered yet: paused=%s in_pits=%s "
                    "track=%r active_file=%s laps=%s",
                    data.game_paused, data.in_pits, data.track,
                    bool(self._session_logger.active_file),
                    self._session_logger.lap_count)

            # Mid-session pit card: stopped in the box during practice or
            # qualifying with laps banked → "how you're tracking" (the
            # session so far, same screen as the summary). Once per pit
            # visit; the pause path above covers menu-based garage returns.
            self._maybe_show_pit_card(data)

            # Auto-dismiss once the player is clearly driving the new session.
            # A pending or active debrief is abandoned (answers given so far
            # are kept) — never hold questions over a moving car.
            if (self._summary_view is not None and self._drive_detector is not None
                    and self._drive_detector.update(data.speed)):
                self._debrief_after = None
                if hasattr(self._summary_view, "finish"):
                    self._summary_view.finish()
                self._dismiss_summary(manager)

            if self._summary_view is not None:
                self._summary_view.render(screen)
            else:
                manager.render(screen)

            if hold_duration >= _INDICATOR_DELAY:
                _draw_hold_indicator(screen, hold_duration, self.QUIT_HOLD_SECONDS)

            if hold_duration >= self.QUIT_HOLD_SECONDS:
                action = self._open_settings(screen)
                if action in ("menu", "quit"):
                    result = action
                    running = False
                touch_start_time = None
                touch_active = False
                # Discard any leftover button-up from dismissing the overlay
                # and clear swipe tracking — otherwise it can be misread as
                # a swipe gesture and switch to a different dashboard config.
                pygame.event.clear()
                manager.reset_touch()

            flip_surface(screen, self._flip)

            pygame.display.flip()
            clock.tick(self._fps)

        closed_file = None
        if self._session_logger is not None:
            closed_file = self._session_logger.close()
        self._telemetry.disconnect()

        # Exit-to-menu summary: the session that just closed gets its
        # summary screen before the menu appears (skipped on quit).
        if closed_file and result == "menu" and self._show_summary:
            summary = self._build_summary(closed_file)
            if summary is not None:
                from core.session_summary import run_summary_screen
                run_summary_screen(screen, summary, flip=self._flip, fps=self._fps)

        # Driver debrief: 2–3 tap questions after the summary, appended to
        # the closed CSV as D rows. Own toggle; never blocks the menu.
        if closed_file and result == "menu" and self._debrief_enabled:
            try:
                from core.debrief import (append_debrief, build_debrief,
                                          run_debrief_screen)
                built = build_debrief(closed_file)
                if built:
                    questions, sub = built
                    answers = run_debrief_screen(screen, questions, sub,
                                                 flip=self._flip, fps=self._fps)
                    if answers:
                        append_debrief(closed_file, answers)
            except Exception:
                import logging
                logging.getLogger("debrief").exception("debrief failed")

        if own_pygame:
            pygame.quit()
            sys.exit()

        return result

    # ── End-of-session summary ────────────────────────────────────────────────

    def _build_summary(self, csv_path: str):
        """build_summary() that never raises — a summary failure must not
        take the dashboard down."""
        from core.session_summary import build_summary
        try:
            return build_summary(csv_path)
        except Exception:
            import logging
            logging.getLogger("summary").exception(
                f"failed to build session summary for {csv_path}")
            return None

    def _show_summary_for(self, csv_path: str,
                          caption: str = "SESSION SUMMARY") -> None:
        if not self._show_summary:
            return
        summary = self._build_summary(csv_path)
        if summary is None:
            self._summary_view = None
            self._drive_detector = None
            return
        from core.session_summary import DriveAwayDetector, SessionSummaryView
        self._summary_view   = SessionSummaryView(summary, self.WIDTH, self.HEIGHT,
                                                  caption=caption)
        self._drive_detector = DriveAwayDetector()

    _PIT_CARD_SESSIONS = ("practice", "qualifying")
    _PIT_CARD_MAX_KMH  = 5.0   # only when stopped — never over a live dash
                               # while driving the pit lane

    def _maybe_show_pit_card(self, data) -> None:
        if not data.in_pits:
            self._pit_card_shown = False   # left the pits — re-arm
            return
        if self._summary_view is not None:
            # A card is already up this pit visit (e.g. the pause-path
            # summary after a menu garage return) — don't re-show the same
            # content the moment it's dismissed.
            self._pit_card_shown = True
            return
        if (self._pit_card_shown
                or data.game_paused          # pause path owns menu returns
                or data.session_type not in self._PIT_CARD_SESSIONS
                or data.speed > self._PIT_CARD_MAX_KMH
                or self._session_logger is None
                or self._session_logger.lap_count == 0
                or not self._session_logger.active_file):
            return
        self._pit_card_shown = True
        self._show_summary_for(self._session_logger.active_file,
                               caption="SESSION SO FAR")

    @staticmethod
    def _pre_session_due(data, *, pre_session_shown: bool,
                         summary_active: bool, active_file, lap_count: int) -> bool:
        """Whether to show the zero-lap NEXT GOAL card this frame.

        The card belongs in the garage, before the first lap. It is latched
        (`pre_session_shown`, reset on session open) and gated on an open
        session file, zero laps and a resolved track — build_pre_session
        needs the track and re-syncs the records DB, too costly to retry per
        frame, so the caller latches on the first genuine attempt.

        The "in the garage" signal depends on the game state:
          * a **paused** menu (practice/qualifying often load paused), OR
          * a **stationary** car that hasn't started a lap — the Time-Trial
            / hotlap case. The F1 TT garage reports neither `game_paused`
            nor `in_pits` (v0.36.1 diagnostics confirmed both false there),
            so the old pause-only trigger never fired at the start and
            instead fired on quit-to-menu. A stationary zero-lap car is the
            only reliable "not driving yet" signal.
        Races are excluded from the stationary path — a full-screen modal
        over the grid would cover the launch — so a race still needs a pause.
        """
        if (pre_session_shown or summary_active or not active_file
                or lap_count != 0 or not data.track):
            return False
        if data.game_paused:
            return True
        return (data.session_type != "race"
                and data.speed < _GARAGE_SPEED_KMH)

    def _show_pre_session_for(self, data) -> None:
        """Zero-lap pause: show NEXT GOAL goals for the upcoming session.
        Hosted in the summary modal slot — same dismissal semantics.

        Everything (goal build AND view construction) is inside one guard so
        a failure never crashes the loop or silently blanks with no trace —
        the outcome is always logged so the Pi's dashboard.log explains why
        the card did or didn't appear."""
        import logging
        log = logging.getLogger("pre_session")
        if not self._show_summary:
            return
        try:
            from core.pre_session import PreSessionView, build_pre_session
            goal = build_pre_session(self._logs_dir, data)
            if goal is None:
                log.info("pre-session card skipped — no goal for "
                         "%s/%s/%s/%s (first visit or no track)",
                         data.game, data.car_class, data.track,
                         data.session_type)
                return   # no history at this combo (or no track name)
            on_focus = (self._session_logger.set_focus
                        if self._session_logger is not None else None)
            # Auto-commit the data-backed objectives (O rows) as the card is
            # shown — they need no tap, so they're captured even if the driver
            # just drives away. The summary reports how each one went.
            if self._session_logger is not None:
                try:
                    from sessionlog.goals import objectives_for
                    self._session_logger.set_objectives(
                        objectives_for(goal.get("missions")))
                except Exception:
                    log.exception("failed to record session objectives")
            self._summary_view = PreSessionView(goal, self.WIDTH, self.HEIGHT,
                                                on_focus=on_focus)
            from core.session_summary import DriveAwayDetector
            self._drive_detector = DriveAwayDetector()
            log.info("pre-session card shown for %s at %s",
                     data.session_type, data.track)
        except Exception:
            log.exception("failed to build/show pre-session card")

    def _dismiss_summary(self, manager) -> None:
        # A rotated-away session's summary chains into its debrief: the
        # questions take over the modal slot instead of closing it.
        if self._debrief_after and not hasattr(self._summary_view, "tap"):
            path, self._debrief_after = self._debrief_after, None
            try:
                from core.debrief import DebriefOverlay, build_debrief
                built = build_debrief(path)
            except Exception:
                import logging
                logging.getLogger("debrief").exception("debrief overlay failed")
                built = None
            if built is not None:
                questions, sub = built
                self._summary_view = DebriefOverlay(path, questions, sub,
                                                    self.WIDTH, self.HEIGHT)
                pygame.event.clear()
                manager.reset_touch()
                return
        self._debrief_after = None
        self._summary_view = None
        self._drive_detector = None
        # Discard leftover touch state so the dismissing tap can't be
        # misread as a dashboard swipe.
        pygame.event.clear()
        manager.reset_touch()

    def _open_settings(self, screen: pygame.Surface) -> str:
        """Open the settings overlay; apply and persist any changes. Returns action string.

        The log server (if any) is started before opening and always stopped on close —
        it only runs while the overlay is visible so it never impacts gameplay.
        """
        from core.settings_overlay import SettingsOverlay
        from core import config_store
        from dashboard.widgets.themes import apply_theme
        from dashboard.widgets.accents import apply_accent_mode
        from dashboard.widgets.units import set_unit_system

        # Start the server if the preference is ON (share-on-demand), or if the
        # web companion is enabled (menu/always) so its pages are reachable
        # while settings are open.
        _web_mode = config_store.web_app_mode(config_store.load())
        if self._log_server is not None:
            self._log_server.set_window(self._share_window)
            self._log_server.set_token(config_store.api_token(config_store.load()))
            self._log_server.set_tracks_dir(self._tracks_dir)
            self._log_server.set_web_enabled(_web_mode != "off")
            if (self._share_logs or _web_mode != "off") \
                    and not self._log_server.running:
                self._log_server.start(self._logs_dir)

        def _on_toggle(enabled: bool):
            if self._log_server is None:
                return
            if enabled and not self._log_server.running:
                self._log_server.start(self._logs_dir)
            elif not enabled and self._log_server.running:
                self._log_server.stop()

        def _get_url() -> str:
            return self._log_server.url if self._log_server else ""

        def _on_window(days: int) -> None:
            self._share_window = days
            if self._log_server is not None:
                self._log_server.set_window(days)

        def _rebuild_index() -> int:
            from sessionlog import records
            records.set_cache_dir(self._logs_dir)
            _, _, total = records.rebuild()
            return total

        result = SettingsOverlay().run(
            screen,
            current_flip=self._flip,
            current_theme=self._current_theme,
            current_accent_mode=self._current_accent,
            current_units=self._current_units,
            share_logs_active=self._share_logs,
            log_server_url=_get_url(),
            on_share_logs_toggle=_on_toggle,
            get_server_url=_get_url,
            share_window_days=self._share_window,
            on_window_change=_on_window,
            on_rebuild_index=_rebuild_index if self._logs_dir else None,
            show_session_summary=self._show_summary,
            debrief_enabled=self._debrief_enabled,
            pairing_code=config_store.api_token(config_store.load()),
        )

        # Server stops when settings close — never runs during gameplay UNLESS
        # the web companion is set to "always" (for powerful Pis that can serve
        # the browser dashboard mid-session).
        if self._log_server is not None and self._log_server.running \
                and config_store.web_app_mode(config_store.load()) != "always":
            self._log_server.stop()

        new_theme     = result["theme"]
        new_flip      = result["flip"]
        new_accent    = result["accent_mode"]
        new_units     = result["units"]
        new_share     = result["share_logs"]
        new_window    = result["share_window_days"]
        new_summary   = result["show_session_summary"]
        new_debrief   = result["debrief_enabled"]

        if new_theme != self._current_theme:
            apply_theme(new_theme)
            self._current_theme = new_theme
        if new_accent != self._current_accent:
            apply_accent_mode(new_accent)
            self._current_accent = new_accent
        if new_units != self._current_units:
            set_unit_system(new_units)
            self._current_units = new_units
        self._flip               = new_flip
        self._share_logs         = new_share
        self._share_window       = new_window
        self._show_summary       = new_summary
        self._debrief_enabled    = new_debrief

        cfg = config_store.load()
        cfg["theme"]               = new_theme
        cfg["flip"]                = new_flip
        cfg["accent_mode"]         = new_accent
        cfg["units"]               = new_units
        cfg["share_logs"]          = new_share
        cfg["share_window_days"]   = new_window
        cfg.pop("log_retention_days", None)   # migrated to share_window_days
        cfg["show_session_summary"] = new_summary
        cfg["debrief_enabled"]      = new_debrief
        config_store.save(cfg)

        return result["action"]


def _draw_hold_indicator(surface: pygame.Surface, held: float, total: float) -> None:
    """
    Draw a circular progress arc in the bottom-left corner.
    Appears after _INDICATOR_DELAY seconds and fills to 100% at `total` seconds.
    """
    progress = min(1.0, (held - _INDICATOR_DELAY) / (total - _INDICATOR_DELAY))

    cx, cy = 36, surface.get_height() - 36
    outer_r = 22
    inner_r = 14
    start_angle = -math.pi / 2  # 12 o'clock

    # Dark background disc
    pygame.draw.circle(surface, (22, 25, 31), (cx, cy), outer_r)

    # Arc drawn as a filled polygon
    if progress > 0:
        sweep = 2 * math.pi * progress
        steps = max(3, int(steps_for_arc(sweep)))
        points = [(cx, cy)]
        for i in range(steps + 1):
            angle = start_angle + sweep * i / steps
            points.append((
                cx + outer_r * math.cos(angle),
                cy + outer_r * math.sin(angle),
            ))
        if len(points) >= 3:
            color = _arc_color(progress)
            pygame.draw.polygon(surface, color, points)

    # Punch out the inner circle to make it a ring
    pygame.draw.circle(surface, (12, 13, 16), (cx, cy), inner_r)

    # Subtle border ring
    pygame.draw.circle(surface, (37, 40, 46), (cx, cy), outer_r, 1)

    # "⟵" home hint — only show once the ring is mostly full
    if progress > 0.7:
        font = pygame.font.SysFont(None, 14)
        label = font.render("MENU", True, (174, 180, 190))
        surface.blit(label, label.get_rect(center=(cx, cy)))


def steps_for_arc(sweep_radians: float) -> int:
    return max(4, int(sweep_radians / (2 * math.pi) * 48))


def _arc_color(progress: float) -> tuple:
    """Green → amber → red as progress approaches 1."""
    if progress < 0.5:
        t = progress / 0.5
        return (
            int(47 + (255 - 47) * t),
            int(224 + (179 - 224) * t),
            int(122 + (0 - 122) * t),
        )
    t = (progress - 0.5) / 0.5
    return (
        255,
        int(179 + (59 - 179) * t),
        0,
    )
