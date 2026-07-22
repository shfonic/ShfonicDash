"""Game selection menu — shown on startup before any telemetry is started."""
import math
import threading
import time
from datetime import datetime

import pygame

from core.flip import flip_pos, flip_surface
from core.telemetry_formats import TELEMETRY_INFO
from dashboard.widgets import design_system as DS
from dashboard.widgets.design_system import (
    BG, PANEL, PANEL2, BORDER, BORDER2,
    TEXT, TEXT2, TEXT3, TEXT4,
    AMBER, RED, CYAN, MAGENTA, GREEN,
    _lerp,
)
from dashboard.widgets.fonts import load_display, load_ui


def _sync_palette() -> None:
    """Refresh this module's surface/text palette globals from the live
    design-system, so a theme change (in particular switching to/from the
    Light theme) reaches the menu.

    game_menu binds colours as bare module names for brevity; those are
    captured at import — before any theme is applied — so without this they
    would stay frozen at the charcoal defaults while the in-game dashboards
    (which read design_system live) followed the chosen theme. Accents
    (AMBER/RED/…) are left as imported constants: the game-tile brand colours
    in _GAMES are deliberately fixed, and accent *text* on light panels is
    handled per-site with DS.on_panel()."""
    global BG, PANEL, PANEL2, BORDER, BORDER2, TEXT, TEXT2, TEXT3, TEXT4
    BG, PANEL, PANEL2 = DS.BG, DS.PANEL, DS.PANEL2
    BORDER, BORDER2 = DS.BORDER, DS.BORDER2
    TEXT, TEXT2, TEXT3, TEXT4 = DS.TEXT, DS.TEXT2, DS.TEXT3, DS.TEXT4


_GAMES = [
    {
        "id": "f1_25",
        "abbr": "F1",
        "name": "F1 2025",
        "subtitle": "",
        "platform": "UDP :20777",
        "color": RED,
        "supports_recording": True,
    },
    {
        "id": "pcars2",
        "abbr": "PC2",
        "name": "Project CARS 2",
        "subtitle": "",
        "platform": "UDP :5606",
        "color": CYAN,
    },
    {
        "id": "fh6",
        "abbr": "FH",
        "name": "Forza Horizon",
        "subtitle": "",
        "platform": "FH4 / FH5 / FH6  ·  UDP :5301",
        "color": MAGENTA,
    },
    {
        "id": "fm",
        "abbr": "FM",
        "name": "Forza Motorsport",
        "subtitle": "",
        "platform": "UDP :5300",
        "color": AMBER,
    },
    {
        "id": "gt7",
        "abbr": "GT7",
        "name": "Gran Turismo 7",
        "subtitle": "BETA · UNTESTED",
        "platform": "UDP :33740",
        "color": GREEN,
    },
]

_BTN_GAP = 16
_PAD_X = 20
_POWER_D = 32    # top-right power button diameter
_BTN_H = 272     # game grid height (picker screen)
_BTN_Y = 60
_EXIT_Y = 418

# Home screen: two hero cards (CONTINUE WITH / DRIVER PROFILE), the last-session
# milestone strip, then a row of personal-record tiles.
_HOME_TOP    = 52
_HOME_ROW1_H = 178
_HOME_CARD_W = 372
_MS_Y = 244      # milestone / last-session panel (home)
_MS_H = 52
_REC_Y = 306     # personal-record tile row (home)
_REC_H = 80

# Picker screen: the "tap a game to record" hint sits below the grid, in the
# old milestone slot (the grid still occupies the top of the screen).
_PICK_HINT_Y = 344
_PICK_HINT_H = 56

# Hold the sync pill this long to open the settings DATA tab; a shorter tap toggles.
_LONG_PRESS_SECONDS = 0.6

# Idle time on the main menu before the screensaver engages — the Pi is
# often left running (ready for the track editor / web companion) with the
# bright static menu on screen, which risks burn-in on the 7" LCD.
_SCREENSAVER_IDLE_SECONDS = 300
_SAVER_MARGIN = 60
_SAVER_VX = 14   # px/sec — wordmark drift speed, keeps it off any one pixel
_SAVER_VY = 9


class GameMenu:
    W, H = 800, 480

    def __init__(self, screen: pygame.Surface, config: dict, mock_mode: bool = False,
                 flip: bool = False, log_server=None, logs_dir: str = ""):
        self._screen     = screen
        self._config     = config
        self._mock       = mock_mode
        self._flip       = flip
        self._log_server = log_server
        self._logs_dir   = logs_dir
        self._share_logs = config.get("share_logs", False)
        # The SYNC pill (Pythonista companion) is hidden by default — only
        # useful to drivers running the iOS app. Opt in on SETTINGS → COMPANION.
        self._show_sync  = config.get("show_sync_button", False)
        from core import config_store
        self._share_window = config_store.share_window_days(config)
        self._web_mode     = config_store.web_app_mode(config)
        self._waiting      = 0     # session CSVs waiting to be downloaded
        self._waiting_next = 0     # next get_ticks() at which to recount
        self._pill_down    = False # sync pill currently held?
        self._pill_start   = 0.0   # time.time() when the pill was pressed
        self._record_enabled = config.get("show_record_button", False)  # pill hidden by default
        self._record_armed = False # RECORD pill toggled — next game launches
                                   # into the track recorder instead of a dash
        self._screensaver_on = config.get("screensaver_enabled", True)
        self._last_activity  = time.time()
        self._saver_active   = False
        self._saver_start    = 0.0
        self._font_abbr = load_display(56)
        self._font_name = load_ui(20)
        self._font_sub = load_ui(15)
        self._font_detail = load_ui(13)
        # Compact set for multi-row grids (tiles half as tall from 5 games
        # up), and a mini abbr/name pair for three-row tiles (9+ games)
        self._font_abbr_sm = load_display(34)
        self._font_name_sm = load_ui(16)
        self._font_sub_sm = load_ui(12)
        self._font_detail_sm = load_ui(12)
        self._font_abbr_xs = load_display(26)
        self._font_name_xs = load_ui(14)
        self._font_header = load_ui(16)
        self._font_exit = load_ui(15)
        # Home hero cards (continue tile + driver-profile card).
        self._font_tile_abbr = load_display(46)
        self._font_grade = load_display(56)
        self._font_big = load_ui(19)
        self._font_start = load_ui(21)
        # Latest milestone / last-session panel (companion parity) — scanned in
        # the background, the draw loop picks it up whenever it lands. The menu
        # is reconstructed on every return from a session, so a fresh scan
        # (including the just-finished session) happens each time.
        self._milestone: dict | None = None
        # Home driver-profile card + resolved "last game" (both filled by the
        # background loader; None while loading or when there's no history).
        self._home: dict | None = None
        if logs_dir:
            self._scan_milestone()

    def _scan_milestone(self) -> None:
        threading.Thread(target=self._load_home, daemon=True).start()

    def run(self) -> tuple[str, dict] | None:
        """
        Runs the menu loop.
        Returns (game_id, kwargs) on selection, or None to quit.

        If log-sharing is enabled the log server runs for the whole time the
        menu is on screen, and is always stopped again on exit (so it never
        runs while a telemetry session is being driven).
        """
        if self._log_server is not None:
            from core import config_store
            self._web_mode = config_store.web_app_mode(self._config)
            self._log_server.set_window(self._share_window)
            self._log_server.set_token(config_store.api_token(self._config))
            self._log_server.set_web_enabled(self._web_mode != "off")
            if (self._share_logs or self._web_mode != "off") \
                    and not self._log_server.running:
                self._log_server.start(self._logs_dir)
        try:
            return self._loop()
        finally:
            # Keep the server up when leaving the menu only if the web companion
            # is set to run all the time; otherwise it stops (never runs blind).
            if self._log_server is not None and self._log_server.running \
                    and self._web_mode != "always":
                self._log_server.stop()

    def _loop(self) -> tuple[str, dict] | None:
        """Home screen: CONTINUE WITH (last game + START), DRIVER PROFILE card,
        the last-session milestone strip, and personal records. Choosing a
        different game drops into the blocking SELECT GAME picker."""
        clock = pygame.time.Clock()
        power_rect = self._power_rect()
        hovered = None

        while True:
            self._refresh_waiting()
            sync_rect     = self._sync_rect()
            qr_rect       = self._qr_rect()
            settings_rect = self._settings_rect()
            history_rect  = self._history_rect()
            trophies_rect = self._trophies_rect()
            continue_rect = self._continue_rect()
            start_rect    = self._start_rect()
            profile_rect  = self._profile_card_rect()
            has_game      = bool(self._home and self._home.get("game"))

            if (self._screensaver_on and not self._saver_active
                    and time.time() - self._last_activity >= _SCREENSAVER_IDLE_SECONDS):
                self._saver_active = True
                self._saver_start  = time.time()

            # Snapshotted once per batch: a single touch can raise several
            # events (e.g. MOUSEMOTION then MOUSEBUTTONDOWN/UP) and re-checking
            # self._saver_active per-event let the first one wake it, then let
            # a later event in the *same* batch fall through as a real tap.
            was_saver_active = self._saver_active

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if was_saver_active:
                    # Any touch/key just wakes the menu — it doesn't also act
                    # as a button press on whatever happened to be underneath.
                    if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                                      pygame.MOUSEMOTION, pygame.KEYDOWN):
                        self._saver_active  = False
                        self._last_activity = time.time()
                    continue
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                                  pygame.MOUSEMOTION, pygame.KEYDOWN):
                    self._last_activity = time.time()

                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_q):
                        return None
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    pos = flip_pos(event.pos, self._flip)
                    if has_game and start_rect.collidepoint(pos):
                        self._record_armed = False   # START always drives, never records
                        return self._select(self._home["game"])
                    elif continue_rect.collidepoint(pos):
                        picked = self._pick_game()   # blocking SELECT GAME screen
                        if picked == "quit":
                            return None
                        if picked:
                            return self._select(picked)
                        self._last_activity = time.time()
                    elif profile_rect.collidepoint(pos):
                        if self._open_profile():
                            return None
                        self._last_activity = time.time()
                    elif power_rect.collidepoint(pos):
                        action = self._power_menu()
                        if action in ("quit", "shutdown"):
                            if action == "shutdown":
                                import subprocess
                                subprocess.run(["sudo", "shutdown", "-h", "now"])
                            return None
                        self._last_activity = time.time()
                    elif settings_rect.collidepoint(pos):
                        if self._open_settings():
                            return None  # user hit QUIT from settings
                        self._scan_milestone()   # enabled games may have changed
                        self._last_activity = time.time()
                    elif history_rect.collidepoint(pos):
                        if self._open_history():
                            return None  # window closed from the browser
                        self._last_activity = time.time()
                    elif trophies_rect.collidepoint(pos):
                        if self._open_trophies():
                            return None
                        self._last_activity = time.time()
                    elif (self._milestone
                          and self._milestone_rect().collidepoint(pos)):
                        if self._open_history(self._milestone["filename"]):
                            return None
                        self._last_activity = time.time()
                    elif qr_rect.width and qr_rect.collidepoint(pos):
                        self._show_companion_qr()
                    elif sync_rect.collidepoint(pos):
                        self._pill_down  = True
                        self._pill_start = time.time()
                elif event.type == pygame.MOUSEBUTTONUP:
                    # Short tap on the pill toggles sharing; a long hold has
                    # already opened settings and cleared _pill_down.
                    if self._pill_down:
                        self._pill_down = False
                        self._toggle_share()
                elif event.type == pygame.MOUSEMOTION:
                    pos = flip_pos(event.pos, self._flip)
                    hovered = None
                    if has_game and start_rect.collidepoint(pos):
                        hovered = "_start"
                    elif continue_rect.collidepoint(pos):
                        hovered = "_continue"
                    elif profile_rect.collidepoint(pos):
                        hovered = "_profile"
                    elif power_rect.collidepoint(pos):
                        hovered = "_power"
                    elif settings_rect.collidepoint(pos):
                        hovered = "_settings"
                    elif history_rect.collidepoint(pos):
                        hovered = "_history"
                    elif trophies_rect.collidepoint(pos):
                        hovered = "_trophies"
                    elif (self._milestone
                          and self._milestone_rect().collidepoint(pos)):
                        hovered = "_milestone"
                    elif sync_rect.collidepoint(pos):
                        hovered = "_sync"
                    elif qr_rect.width and qr_rect.collidepoint(pos):
                        hovered = "_qr"

            # Long-press: open settings on the COMPANION tab (sync lives there)
            if self._pill_down and (time.time() - self._pill_start) >= _LONG_PRESS_SECONDS:
                self._pill_down = False
                if self._open_settings(start_tab="companion"):
                    return None
                self._scan_milestone()

            if self._saver_active:
                self._draw_screensaver(time.time() - self._saver_start)
            else:
                self._draw_home(sync_rect, power_rect, hovered)
            flip_surface(self._screen, self._flip)
            pygame.display.flip()
            clock.tick(30)

    def _pick_game(self):
        """Blocking SELECT GAME screen (the full game grid + RECORD arming).
        Returns the chosen game dict, None to go back to home, or "quit"."""
        self._record_armed = False   # a fresh picker session starts unarmed
        clock = pygame.time.Clock()
        buttons = self._build_buttons()
        back_rect = self._picker_pill_rect("_back")
        record_rect = (self._picker_pill_rect("_record")
                       if self._record_enabled else None)
        hovered = None

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "quit"
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_q):
                        self._record_armed = False
                        return None
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    pos = flip_pos(event.pos, self._flip)
                    for game, rect in buttons:
                        if rect.collidepoint(pos):
                            if self._record_armed and not game.get("supports_recording", False):
                                break   # tile disabled while recording is armed
                            return game
                    if back_rect.collidepoint(pos):
                        self._record_armed = False
                        return None
                    elif record_rect and record_rect.collidepoint(pos):
                        self._record_armed = not self._record_armed
                elif event.type == pygame.MOUSEMOTION:
                    pos = flip_pos(event.pos, self._flip)
                    hovered = None
                    for game, rect in buttons:
                        if rect.collidepoint(pos) and not (
                                self._record_armed
                                and not game.get("supports_recording", False)):
                            hovered = game["id"]
                    if back_rect.collidepoint(pos):
                        hovered = "_back"
                    elif record_rect and record_rect.collidepoint(pos):
                        hovered = "_record"

            self._draw_picker(buttons, back_rect, record_rect, hovered)
            flip_surface(self._screen, self._flip)
            pygame.display.flip()
            clock.tick(30)

    def _refresh_waiting(self) -> None:
        now = pygame.time.get_ticks()
        if now < self._waiting_next:
            return
        self._waiting_next = now + 1000
        if self._logs_dir:
            from core.log_server import count_waiting
            self._waiting = count_waiting(self._logs_dir, self._share_window)

    def _toggle_share(self) -> None:
        from core import config_store
        self._share_logs = not self._share_logs
        if self._log_server is not None:
            # The web companion may still want the server up even with sharing
            # off — only stop when neither feature needs it.
            want = self._share_logs or self._web_mode != "off"
            if want and not self._log_server.running:
                self._log_server.start(self._logs_dir)
            elif not want and self._log_server.running:
                self._log_server.stop()
        self._config["share_logs"] = self._share_logs
        config_store.save(self._config)

    def _select(self, game: dict) -> tuple[str, dict]:
        from core import config_store
        # Remember the last game the driver actually chose (home tile source of
        # truth) — never in record mode (arming isn't a "drive this game" choice).
        if not self._record_armed:
            config_store.set_last_game(self._config, game["id"])
        return (game["id"], {"game_name": game["name"], "game_color": game["color"],
                             "record_track": self._record_armed})

    def _enabled_games(self) -> list:
        """Games shown on the menu (GAMES settings tab); all when none
        are enabled — an empty menu helps nobody."""
        enabled = self._config.get("enabled_games") or {}
        games = [g for g in _GAMES if enabled.get(g["id"], True)]
        return games or list(_GAMES)

    def _build_buttons(self) -> list:
        """Lay the enabled games out in an adaptive grid: one row up to 4
        (buttons widen as games are disabled), wrapping to extra rows as
        the roster grows (e.g. 3×3 once GT7 and friends arrive)."""
        games = self._enabled_games()
        n     = len(games)
        cols  = min(n, 4) or 1
        rows  = -(-n // cols)   # ceil
        btn_w = (self.W - 2 * _PAD_X - _BTN_GAP * (cols - 1)) // cols
        btn_h = (_BTN_H - _BTN_GAP * (rows - 1)) // rows
        result = []
        for i, game in enumerate(games):
            r, c = divmod(i, cols)
            rect = pygame.Rect(_PAD_X + c * (btn_w + _BTN_GAP),
                               _BTN_Y + r * (btn_h + _BTN_GAP),
                               btn_w, btn_h)
            result.append((game, rect))
        return result

    # Home bottom pill row: TROPHIES · HISTORY · SETTINGS, centred as a group.
    # (PROFILE is now the driver-profile card; RECORD lives on the picker.)
    def _pill_keys(self) -> list:
        return ["_trophies", "_history", "_settings"]

    def _pill_row_rect(self, key: str) -> pygame.Rect:
        keys = self._pill_keys()
        w, h, gap, n = 140, 40, 12, len(keys)
        start = (self.W - (n * w + (n - 1) * gap)) // 2
        return pygame.Rect(start + keys.index(key) * (w + gap), _EXIT_Y, w, h)

    def _trophies_rect(self) -> pygame.Rect:
        return self._pill_row_rect("_trophies")

    def _history_rect(self) -> pygame.Rect:
        return self._pill_row_rect("_history")

    def _settings_rect(self) -> pygame.Rect:
        return self._pill_row_rect("_settings")

    def _sync_rect(self) -> pygame.Rect:
        """Bounds of the top-left sync pill; width depends on current state.
        Zero-width (hidden) unless the driver has opted the Pythonista SYNC
        pill in (SETTINGS → COMPANION → Show SYNC button)."""
        if not self._show_sync:
            return pygame.Rect(0, 0, 0, 0)
        pad = 12
        w = pad + 14 + self._font_exit.size("SYNC")[0] + pad
        if self._share_logs:
            ip = self._log_server.url if self._log_server else ""
            if ip:
                w += 10 + self._font_detail.size(ip)[0]
        if self._waiting > 0:
            w += 8 + self._font_detail.size(str(self._waiting))[0] + 12
        return pygame.Rect(12, 16, w, 32)

    def _qr_rect(self) -> pygame.Rect:
        """Companion-QR pill in the top bar, just left of the power button (clear
        of the centred SHFONIC DASH title and the left-hand sync pill). Zero-width
        (hidden) when the web companion is OFF — there's nothing to pair to."""
        if self._web_mode == "off":
            return pygame.Rect(0, 0, 0, 0)
        w = 12 + 16 + 8 + self._font_exit.size("COMPANION")[0] + 12
        power = self._power_rect()
        return pygame.Rect(power.x - 10 - w, 16, w, 32)

    def _power_rect(self) -> pygame.Rect:
        """Bounds of the top-right power button."""
        return pygame.Rect(self.W - 12 - _POWER_D, 12, _POWER_D, _POWER_D)

    # ── home layout rects ─────────────────────────────────────────────────
    def _continue_rect(self) -> pygame.Rect:
        return pygame.Rect(_PAD_X, _HOME_TOP, _HOME_CARD_W, _HOME_ROW1_H)

    def _start_rect(self) -> pygame.Rect:
        t = self._continue_rect()
        return pygame.Rect(t.x + 20, t.bottom - 50, t.w - 40, 38)

    def _profile_card_rect(self) -> pygame.Rect:
        return pygame.Rect(self.W - _PAD_X - _HOME_CARD_W, _HOME_TOP,
                           _HOME_CARD_W, _HOME_ROW1_H)

    def _milestone_rect(self) -> pygame.Rect:
        return pygame.Rect(_PAD_X, _MS_Y, self.W - 2 * _PAD_X, _MS_H)

    # ── picker layout rects ───────────────────────────────────────────────
    def _picker_pills(self) -> list:
        return (["_record"] if self._record_enabled else []) + ["_back"]

    def _picker_pill_rect(self, key: str) -> pygame.Rect:
        keys = self._picker_pills()
        w, h, gap, n = 140, 40, 12, len(keys)
        start = (self.W - (n * w + (n - 1) * gap)) // 2
        return pygame.Rect(start + keys.index(key) * (w + gap), _EXIT_Y, w, h)

    def _pick_hint_rect(self) -> pygame.Rect:
        return pygame.Rect(_PAD_X, _PICK_HINT_Y, self.W - 2 * _PAD_X, _PICK_HINT_H)

    def _draw_home(self, sync_rect, power_rect, hovered):
        _sync_palette()   # follow live theme changes (e.g. Light) each frame
        self._screen.fill(BG)
        self._draw_header()
        self._draw_sync_pill(sync_rect, hovered == "_sync")
        self._draw_qr_pill(self._qr_rect(), hovered == "_qr")
        self._draw_power_icon(power_rect, hovered == "_power")
        self._draw_continue_tile(hovered)
        self._draw_profile_card(hovered == "_profile")
        self._draw_records()
        self._draw_milestone(hovered == "_milestone")
        self._draw_pill_btn(self._settings_rect(), "SETTINGS", hovered == "_settings")
        self._draw_pill_btn(self._history_rect(), "HISTORY", hovered == "_history")
        self._draw_pill_btn(self._trophies_rect(), "TROPHIES", hovered == "_trophies")
        self._draw_version()

    def _draw_picker(self, buttons, back_rect, record_rect, hovered):
        _sync_palette()
        self._screen.fill(BG)
        surf = self._font_header.render("SELECT GAME", True, TEXT3)
        self._screen.blit(surf, surf.get_rect(center=(self.W // 2, 32)))
        self._draw_mock_badge()
        for game, rect in buttons:
            disabled = self._record_armed and not game.get("supports_recording", False)
            self._draw_button(game, rect, hovered == game["id"], disabled)
        if record_rect is not None:
            self._draw_record_pill(record_rect, hovered == "_record")
        self._draw_pill_btn(back_rect, "‹  BACK", hovered == "_back")
        # When armed, the "tap a game" prompt fills the slot below the grid.
        if self._record_armed:
            self._draw_record_hint(self._pick_hint_rect())

    def _draw_continue_tile(self, hovered):
        """Left hero card: the last driven game + a big START button, or a
        'choose a game' prompt when there's no (enabled) history yet."""
        rect = self._continue_rect()
        game = self._home["game"] if self._home else None
        active = hovered in ("_continue", "_start")
        pygame.draw.rect(self._screen, PANEL, rect, border_radius=16)
        pygame.draw.rect(self._screen, BORDER2 if active else BORDER, rect,
                         width=1, border_radius=16)
        # top-right chevron → the SELECT GAME picker
        self._draw_corner_chevron(pygame.Rect(rect.right - 42, rect.y + 14, 28, 28))

        if game is None:
            cap = self._font_detail.render("NO SESSIONS YET", True, TEXT3)
            self._screen.blit(cap, (rect.x + 28, rect.y + 44))
            big = self._font_name.render("CHOOSE A GAME", True, TEXT)
            self._screen.blit(big, (rect.x + 28, rect.y + 68))
            hint = self._font_sub.render("Tap to pick a game to connect to", True, TEXT3)
            self._screen.blit(hint, (rect.x + 28, rect.y + 100))
            return

        color = game["color"]
        pygame.draw.rect(self._screen, color,
                         pygame.Rect(rect.x, rect.y, 6, rect.h),
                         border_top_left_radius=16, border_bottom_left_radius=16)
        self._screen.blit(self._font_detail.render("CONTINUE WITH", True, TEXT3),
                          (rect.x + 26, rect.y + 16))
        self._screen.blit(self._font_tile_abbr.render(game["abbr"], True, color),
                          (rect.x + 24, rect.y + 34))
        self._screen.blit(self._font_name.render(game["name"], True, TEXT),
                          (rect.x + 108, rect.y + 40))
        when = self._home.get("when") or ""
        sub = game["platform"] + (f"  ·  {when}" if when else "")
        self._screen.blit(self._font_sub.render(sub, True, TEXT3),
                          (rect.x + 108, rect.y + 68))
        # START
        srect = self._start_rect()
        sbg = _lerp(color, TEXT, 0.12) if hovered == "_start" else color
        pygame.draw.rect(self._screen, sbg, srect, border_radius=11)
        pygame.draw.polygon(self._screen, BG,
                            [(srect.x + 24, srect.centery - 8),
                             (srect.x + 24, srect.centery + 8),
                             (srect.x + 38, srect.centery)])
        lbl = self._font_start.render("START", True, BG)
        self._screen.blit(lbl, lbl.get_rect(center=(srect.centerx + 7, srect.centery)))

    def _profile_config(self) -> dict:
        """Driver profile for the card, re-read from disk only when config.json
        changes (e.g. after a companion sync) so a sync shows without a Pi
        restart — cheap `getmtime` per frame, `load()` only on change."""
        import os

        from core import config_store
        try:
            mtime = os.path.getmtime(config_store._CONFIG_PATH)
        except OSError:
            mtime = 0
        if getattr(self, "_prof_mtime", None) != mtime:
            self._prof_cfg = config_store.load()
            self._prof_mtime = mtime
        return config_store.profile(self._prof_cfg)

    def _draw_profile_card(self, active: bool):
        """Right hero card: driver avatar + name (or "DRIVER PROFILE" until a
        companion sync), recent-form grade + trend + career counts. The whole
        card is a button that opens the deep PROFILE screen."""
        from core import avatar_render
        rect = self._profile_card_rect()
        pygame.draw.rect(self._screen, PANEL, rect, border_radius=16)
        pygame.draw.rect(self._screen, BORDER2 if active else BORDER, rect,
                         width=1, border_radius=16)
        # Avatar top-right (replaces the corner chevron); name-as-title once
        # the companion has synced a profile, else the "DRIVER PROFILE" label.
        prof = self._profile_config()
        # "Synced" = a profile was actually stored by a companion push (rather
        # than the computed Pi-only default). Don't gate on the `updated`
        # timestamp — profiles created before it existed have none.
        synced = bool(self._prof_cfg.get("profile"))
        av = 40
        ax, ay = rect.right - 16 - av, rect.y + 14
        self._screen.blit(avatar_render.avatar_surface(prof, av, self._font_sub),
                          (ax, ay))
        name = (prof.get("name") or "").strip()
        if synced and name:
            avail = ax - 10 - (rect.x + 22)
            self._screen.blit(self._fit_text(self._font_name, name, avail, TEXT),
                              (rect.x + 22, rect.y + 16))
        else:
            self._screen.blit(self._font_sub.render("DRIVER PROFILE", True, TEXT3),
                              (rect.x + 22, rect.y + 18))

        form = self._home.get("form") if self._home else None
        letter = form["letter"] if form else "—"
        g = self._font_grade.render(letter, True, AMBER if form else TEXT4)
        self._screen.blit(g, (rect.x + 22, rect.y + 44))
        tx = rect.x + 22 + 118
        if form:
            trend = form.get("trend")
            words = {"up": "Improving", "down": "Slipping", "flat": "Holding steady"}
            cols  = {"up": GREEN, "down": RED, "flat": TEXT3}
            head, hcol = words.get(trend, "Current form"), cols.get(trend, TEXT2)
            ht = self._font_big.render(head, True, hcol)
            self._screen.blit(ht, (tx, rect.y + 52))
            if trend in ("up", "down"):
                cx, cy = tx + ht.get_width() + 15, rect.y + 52 + 11
                up = trend == "up"
                pts = ([(cx, cy - 6), (cx - 6, cy + 6), (cx + 6, cy + 6)] if up
                       else [(cx, cy + 6), (cx - 6, cy - 6), (cx + 6, cy - 6)])
                pygame.draw.polygon(self._screen, hcol, pts)
            n = form["n"]
            sub = f"over your last {n} session{'s' if n != 1 else ''}"
            self._screen.blit(self._font_detail.render(sub, True, TEXT3),
                              (tx, rect.y + 84))
        else:
            self._screen.blit(self._font_big.render("No graded sessions yet",
                              True, TEXT2), (tx, rect.y + 60))
        # career counts
        pygame.draw.line(self._screen, BORDER, (rect.x + 22, rect.y + 116),
                         (rect.right - 22, rect.y + 116), 1)
        h = self._home or {}
        counts = [(str(h.get("games", 0)), "GAMES"),
                  (str(h.get("sessions", 0)), "SESSIONS"),
                  (str(h.get("trophies", 0)), "TROPHIES")]
        for i, (big, cap) in enumerate(counts):
            col = rect.x + 22 + i * 116
            self._screen.blit(self._font_big.render(big, True, TEXT),
                              (col, rect.y + 126))
            self._screen.blit(self._font_detail.render(cap, True, TEXT3),
                              (col, rect.y + 148))

    def _draw_records(self):
        """Row of up to four personal-record tiles (no section label)."""
        tiles = (self._home or {}).get("tiles") or []
        if not tiles:
            return
        tw = (self.W - 2 * _PAD_X - 12 * 3) // 4
        for i, (cap, big, sub) in enumerate(tiles[:4]):
            x = _PAD_X + i * (tw + 12)
            rect = pygame.Rect(x, _REC_Y, tw, _REC_H)
            pygame.draw.rect(self._screen, PANEL2, rect, border_radius=12)
            pygame.draw.rect(self._screen, BORDER, rect, width=1, border_radius=12)
            self._screen.blit(self._fit_text(self._font_detail, cap, tw - 24, TEXT3),
                              (rect.x + 12, rect.y + 10))
            self._screen.blit(self._fit_text(self._font_big, big, tw - 24, TEXT),
                              (rect.x + 12, rect.y + 28))
            self._screen.blit(self._fit_text(self._font_detail, sub, tw - 24, TEXT4),
                              (rect.x + 12, rect.y + 51))

    def _draw_corner_chevron(self, rect: pygame.Rect):
        """Small right-pointing chevron in a pill — the 'this is a button' cue
        shared by the two hero cards."""
        pygame.draw.circle(self._screen, PANEL2, rect.center, rect.width // 2)
        pygame.draw.circle(self._screen, BORDER2, rect.center, rect.width // 2, 1)
        cx, cy = rect.center
        pygame.draw.lines(self._screen, TEXT2, False,
                          [(cx - 3, cy - 6), (cx + 3, cy), (cx - 3, cy + 6)], 2)

    def _draw_record_pill(self, rect: pygame.Rect, hovered: bool):
        """RECORD pill. Armed → lit with a red 'recording' dot + REC; the dot is
        drawn (not a glyph) so it renders on every font."""
        armed = self._record_armed
        active = armed or hovered
        r = rect.height // 2
        pygame.draw.rect(self._screen, PANEL2 if active else PANEL, rect, border_radius=r)
        pygame.draw.rect(self._screen, RED if armed else BORDER, rect,
                         width=1, border_radius=r)
        text = "REC" if armed else "RECORD"
        lbl = self._font_exit.render(text, True, TEXT2 if active else TEXT4)
        if armed:
            # Centre the dot + label as a group.
            dot_r = 4
            gap = 8
            total_w = dot_r * 2 + gap + lbl.get_width()
            x = rect.centerx - total_w // 2
            pygame.draw.circle(self._screen, RED,
                               (x + dot_r, rect.centery), dot_r)
            self._screen.blit(lbl, (x + dot_r * 2 + gap,
                                    rect.centery - lbl.get_height() // 2))
        else:
            self._screen.blit(lbl, lbl.get_rect(center=rect.center))

    def _draw_record_hint(self, rect: pygame.Rect):
        """Amber prompt shown below the game grid while recording is armed."""
        pygame.draw.rect(self._screen, _lerp(BG, AMBER, 0.12), rect, border_radius=14)
        pygame.draw.rect(self._screen, AMBER, rect, width=1, border_radius=14)
        line = self._font_name.render("TAP A GAME TO RECORD ITS TRACK", True, DS.on_panel(AMBER))
        self._screen.blit(line, line.get_rect(center=rect.center))

    def _draw_sync_pill(self, rect: pygame.Rect, hovered: bool):
        if not rect.width:
            return
        on = self._share_logs
        r  = rect.height // 2
        pygame.draw.rect(self._screen, PANEL2 if hovered else PANEL, rect, border_radius=r)
        pygame.draw.rect(self._screen, GREEN if on else BORDER, rect, width=1, border_radius=r)

        cy = rect.centery
        pygame.draw.circle(self._screen, GREEN if on else TEXT4, (rect.x + 16, cy), 4)

        x = rect.x + 26
        lbl = self._font_exit.render("SYNC", True, TEXT2 if on else TEXT4)
        self._screen.blit(lbl, (x, cy - lbl.get_height() // 2))
        x += lbl.get_width()

        if on:
            ip = self._log_server.url if self._log_server else ""
            if ip:
                x += 10
                ip_s = self._font_detail.render(ip, True, DS.on_panel(CYAN))
                self._screen.blit(ip_s, (x, cy - ip_s.get_height() // 2))
                x += ip_s.get_width()

        if self._waiting > 0:
            x += 8
            num   = str(self._waiting)
            num_w = self._font_detail.size(num)[0]
            badge = pygame.Rect(x, cy - 9, num_w + 12, 18)
            pygame.draw.rect(self._screen, AMBER, badge, border_radius=9)
            num_s = self._font_detail.render(num, True, (12, 19, 0))
            self._screen.blit(num_s, num_s.get_rect(center=badge.center))

    def _draw_qr_pill(self, rect: pygame.Rect, hovered: bool):
        """Companion-QR pill: a small QR glyph + COMPANION, opens the pairing QR."""
        if not rect.width:
            return
        r = rect.height // 2
        pygame.draw.rect(self._screen, PANEL2 if hovered else PANEL, rect, border_radius=r)
        pygame.draw.rect(self._screen, AMBER if hovered else BORDER, rect,
                         width=1, border_radius=r)
        # Mini QR icon: three finder squares.
        gx, gy, s = rect.x + 12, rect.centery - 7, 14
        col = DS.on_panel(AMBER) if hovered else TEXT2
        q = s // 3 - 1
        for (ox, oy) in ((0, 0), (s - q, 0), (0, s - q)):
            pygame.draw.rect(self._screen, col, (gx + ox, gy + oy, q, q))
        lbl = self._font_exit.render("COMPANION", True, TEXT2 if hovered else TEXT4)
        self._screen.blit(lbl, (gx + s + 8, rect.centery - lbl.get_height() // 2))

    def _show_companion_qr(self):
        """Full-screen pairing QR for the web companion (reuses the settings
        overlay's modal). Starts the server if it isn't up yet."""
        from core import config_store
        from core.settings_overlay import SettingsOverlay
        if self._log_server is not None and not self._log_server.running:
            self._log_server.set_web_enabled(True)
            self._log_server.set_token(config_store.api_token(self._config))
            self._log_server.start(self._logs_dir)
        url = self._log_server.url if self._log_server else ""
        code = config_store.api_token(self._config)
        if url:
            SettingsOverlay()._show_qr_modal(self._screen, url, code, self._flip)
        self._last_activity = time.time()

    def _draw_power_icon(self, rect: pygame.Rect, hovered: bool):
        """Top-right power button — opens the DISMISS / QUIT / SHUTDOWN modal.
        The glyph is drawn (ring open at the top + a vertical stroke) rather
        than a font symbol so it renders identically on the Pi."""
        r = rect.width // 2
        pygame.draw.circle(self._screen, PANEL2 if hovered else PANEL, rect.center, r)
        pygame.draw.circle(self._screen, RED if hovered else BORDER, rect.center, r, 1)
        color = DS.on_panel(RED) if hovered else TEXT3
        glyph = self._power_glyph(rect.width, color)
        self._screen.blit(glyph, glyph.get_rect(center=rect.center))

    @staticmethod
    def _power_glyph(size: int, color) -> pygame.Surface:
        """A crisp power symbol (gapped ring + vertical stroke). Built at 4× and
        smooth-scaled down so the curves are anti-aliased — pygame.draw.arc gives
        an uneven, hand-drawn line, so the ring is punched from filled circles
        instead."""
        ss = 4
        d  = size * ss
        surf = pygame.Surface((d, d), pygame.SRCALPHA)
        cx = cy = d // 2
        R = int(d * 0.34)             # outer ring radius
        t = max(2, int(d * 0.11))     # ring / stroke thickness
        clear = (0, 0, 0, 0)
        pygame.draw.circle(surf, color, (cx, cy), R)
        pygame.draw.circle(surf, clear, (cx, cy), R - t)     # → ring
        gap = int(d * 0.11)
        pygame.draw.polygon(surf, clear,                     # gap at 12 o'clock
                            [(cx, cy), (cx - gap, cy - R - t),
                             (cx + gap, cy - R - t)])
        pygame.draw.rect(surf, color,                        # vertical stroke
                         (cx - t // 2, cy - int(d * 0.31), t, int(d * 0.31)),
                         border_radius=t // 2)
        return pygame.transform.smoothscale(surf, (size, size))

    def _power_menu(self) -> str:
        """Modal power sheet. Returns 'dismiss', 'quit' or 'shutdown'."""
        clock  = pygame.time.Clock()
        frozen = self._screen.copy()
        cw, ch = 360, 268
        cx = (self.W - cw) // 2
        cy = (self.H - ch) // 2
        card = pygame.Rect(cx, cy, cw, ch)
        options = [
            ("dismiss",  "DISMISS",  TEXT),
            ("quit",     "QUIT",     RED),
            ("shutdown", "SHUTDOWN", AMBER),
        ]
        bh, gap = 52, 12
        bx, bw  = cx + 24, cw - 48
        first_y = cy + 76
        rects = {key: pygame.Rect(bx, first_y + i * (bh + gap), bw, bh)
                 for i, (key, _, _) in enumerate(options)}
        hovered = None

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "quit"
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_q):
                        return "dismiss"
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    pos = flip_pos(event.pos, self._flip)
                    if not card.collidepoint(pos):
                        return "dismiss"
                    for key, rect in rects.items():
                        if rect.collidepoint(pos):
                            return key
                elif event.type == pygame.MOUSEMOTION:
                    pos = flip_pos(event.pos, self._flip)
                    hovered = next((k for k, rc in rects.items()
                                    if rc.collidepoint(pos)), None)

            self._screen.blit(frozen, (0, 0))
            scrim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            scrim.fill((0, 0, 0, 185))
            self._screen.blit(scrim, (0, 0))
            pygame.draw.rect(self._screen, PANEL, card, border_radius=12)
            pygame.draw.rect(self._screen, BORDER2, card, width=1, border_radius=12)
            title = self._font_header.render("POWER", True, TEXT3)
            self._screen.blit(title, title.get_rect(center=(self.W // 2, cy + 38)))
            for key, label, color in options:
                rect   = rects[key]
                is_hov = hovered == key
                pygame.draw.rect(self._screen, PANEL2, rect, border_radius=8)
                pygame.draw.rect(self._screen, color if is_hov else BORDER,
                                 rect, width=1, border_radius=8)
                s = self._font_exit.render(label, True,
                                           color if is_hov else TEXT3)
                self._screen.blit(s, s.get_rect(center=rect.center))
            flip_surface(self._screen, self._flip)
            pygame.display.flip()
            clock.tick(30)

    def _draw_header(self):
        surf = self._font_header.render("SHFONIC DASH", True, TEXT3)
        self._screen.blit(surf, surf.get_rect(center=(self.W // 2, 32)))
        self._draw_mock_badge()

    def _draw_mock_badge(self):
        if not self._mock:
            return
        badge = self._font_detail.render("MOCK", True, (12, 19, 0))
        r = badge.get_height() // 2 + 6
        bw = badge.get_width() + 20
        bh = badge.get_height() + 10
        # Sits to the left of the top-right power button.
        bx = self.W - 12 - _POWER_D - 8 - bw
        by = 12
        pygame.draw.rect(self._screen, AMBER,
                         pygame.Rect(bx, by, bw, bh), border_radius=r)
        self._screen.blit(badge, badge.get_rect(center=(bx + bw // 2, by + bh // 2)))

    def _draw_button(self, game: dict, rect: pygame.Rect, active: bool,
                     disabled: bool = False):
        color = game["color"]
        radius = 12

        if active:
            for expand, alpha in ((8, 0.15), (4, 0.28)):
                gr = pygame.Rect(
                    rect.x - expand, rect.y - expand,
                    rect.width + expand * 2, rect.height + expand * 2,
                )
                pygame.draw.rect(self._screen, _lerp(PANEL, color, alpha),
                                 gr, border_radius=radius + expand)

        pygame.draw.rect(self._screen, PANEL, rect, border_radius=radius)
        pygame.draw.rect(self._screen, color if active else BORDER,
                         rect, width=1, border_radius=radius)

        self._draw_button_content(game, rect, disabled)

        if disabled:
            # Dim the whole tile — recording is only supported for this
            # game once armed, so the rest are unselectable.
            overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
            overlay.fill((*BG, 165))
            self._screen.blit(overlay, rect.topleft)

    def _button_content(self, game: dict, rect: pygame.Rect,
                        disabled: bool = False) -> list:
        """Content lines (font, text, colour, gap) fitted to the tile:
        compact fonts on short tiles (multi-row grid), and trailing lines
        dropped rather than drawn across the tile border."""
        compact = rect.height < 200
        mini    = rect.height < 110
        f_abbr   = self._font_abbr_xs if mini else \
                   self._font_abbr_sm if compact else self._font_abbr
        f_name   = self._font_name_xs if mini else \
                   self._font_name_sm if compact else self._font_name
        f_sub    = self._font_sub_sm if compact else self._font_sub
        f_detail = self._font_detail_sm if compact else self._font_detail

        content = [
            (f_abbr, game["abbr"], TEXT4 if disabled else game["color"],
             6 if compact else 10),
        ]
        content.append((f_name, game["name"], TEXT4 if disabled else TEXT,
                        4 if compact else 6))
        if disabled:
            content.append((f_sub, "NOT SUPPORTED", TEXT4,
                            10 if compact else 14))
            return content
        if game["subtitle"]:
            content.append((f_sub, game["subtitle"], TEXT2, 10 if compact else 14))
        else:
            content[-1] = (content[-1][0], content[-1][1], content[-1][2],
                           12 if compact else 18)
        content.append((f_detail, game["platform"], TEXT3, 4))
        # Expected telemetry format — what the game must be set to output. Last,
        # so it's the first line dropped on very short tiles (the roomy
        # waiting-for-telemetry screen carries the full setup steps).
        info = TELEMETRY_INFO.get(game["id"])
        if info:
            content.append((f_detail, info["format"], TEXT4, 6))

        def total_h(lines):
            return sum(f.size(t)[1] + gap for f, t, c, gap in lines) - lines[-1][3]

        # Abbr and name always stay; platform goes first, then subtitle
        while len(content) > 2 and total_h(content) > rect.height - 8:
            content.pop()
        return content

    def _draw_button_content(self, game: dict, rect: pygame.Rect,
                             disabled: bool = False):
        content = self._button_content(game, rect, disabled)
        cx = rect.centerx
        total = sum(f.size(t)[1] + gap for f, t, c, gap in content) - content[-1][3]
        y = rect.top + (rect.height - total) // 2

        for font, text, text_color, gap in content:
            surf = font.render(text, True, text_color)
            self._screen.blit(surf, surf.get_rect(center=(cx, y + surf.get_height() // 2)))
            y += surf.get_height() + gap

    def _draw_pill_btn(self, rect: pygame.Rect, text: str, active: bool):
        bg = PANEL2 if active else PANEL
        border = BORDER2 if active else BORDER
        pygame.draw.rect(self._screen, bg, rect, border_radius=rect.height // 2)
        pygame.draw.rect(self._screen, border, rect, width=1, border_radius=rect.height // 2)
        label = self._font_exit.render(text, True, TEXT3 if active else TEXT4)
        self._screen.blit(label, label.get_rect(center=rect.center))

    def _open_profile(self) -> bool:
        """Open the driver profile. Returns True on window close."""
        from core.profile_browser import ProfileBrowser
        result = ProfileBrowser(self._screen, self._logs_dir,
                                flip=self._flip).run()
        return result == "quit"

    def _open_trophies(self) -> bool:
        """Open the badge gallery. Returns True on window close."""
        from core.trophies_browser import TrophiesBrowser
        result = TrophiesBrowser(self._screen, self._logs_dir,
                                 flip=self._flip).run()
        # Sessions can be deleted via the nested history detail — rescan.
        if self._logs_dir:
            self._milestone = None
            self._scan_milestone()
        return result == "quit"

    def _open_history(self, open_file: str | None = None) -> bool:
        """Open the session history browser. Returns True on window close."""
        from core.history_browser import HistoryBrowser
        result = HistoryBrowser(self._screen, self._logs_dir,
                                flip=self._flip).run(open_file=open_file)
        # Sessions can be deleted in the browser — rescan the panel.
        if self._logs_dir:
            self._milestone = None
            self._scan_milestone()
        return result == "quit"

    def _load_home(self):
        """Background loader (one records sync): the last-session milestone
        strip and the DRIVER PROFILE card + resolved 'last game'."""
        from core.profile_browser import load_rows
        recs = load_rows(self._logs_dir)
        if not recs:
            # No driven sessions yet, but a game may already have been picked
            # (e.g. Forza free-roam logs no laps) — still show it on the tile.
            self._home = self._build_home([])
            return
        self._milestone = self._build_milestone(recs)
        self._home = self._build_home(recs)

    def _resolve_last_game(self, recs):
        """(game tile dict, when-label) for the home "CONTINUE WITH" card.

        The last game the driver *selected* wins (persisted in config), so the
        card reflects the chosen game even when it produced no lap-based session
        record. Falls back to the most-recent driven + enabled game when no
        selection is stored (first run / upgrade). Returns (None, "") when
        neither is available → the tile shows the "choose a game" prompt."""
        from core import config_store
        enabled_ids = {g["id"]: g for g in self._enabled_games()}
        sel = config_store.last_game(self._config)
        if sel and sel in enabled_ids:
            when = ""
            for r in recs:                  # newest-first — match for the subtitle
                if r.get("date") and r.get("game") == sel:
                    when = self._relative_day(r.get("date"))
                    break
            return enabled_ids[sel], when
        for r in recs:                      # recs are newest-first
            if r.get("date") and r.get("game") in enabled_ids:
                return enabled_ids[r["game"]], self._relative_day(r.get("date"))
        return None, ""

    def _build_home(self, recs) -> dict:
        """DRIVER PROFILE summary + the resolved 'last game' tile (the last game
        selected, else the most-recent driven + enabled game, else None → the
        tile shows a 'choose a game' prompt). Same maths as the PROFILE screen,
        so the numbers agree."""
        from core.profile_browser import (compute_form, count_trophies,
                                           compute_records, record_tiles,
                                           HOME_RECORD_ORDER)
        last_game, last_when = self._resolve_last_game(recs)
        return {
            "game":     last_game,
            "when":     last_when if last_game else "",
            "form":     compute_form(recs),
            "games":    len({r.get("game") for r in recs if r.get("game")}),
            "sessions": len(recs),
            "trophies": count_trophies(recs),
            "tiles":    record_tiles(compute_records(recs), HOME_RECORD_ORDER),
        }

    @staticmethod
    def _relative_day(date) -> str:
        if not date:
            return ""
        delta = (datetime.now().date() - date.date()).days
        if delta <= 0:
            return "TODAY"
        if delta == 1:
            return "YESTERDAY"
        return date.strftime("%d %b").lstrip("0").upper()

    def _build_milestone(self, recs) -> dict | None:
        """Find the latest milestone across all logged sessions; falls back to
        the most recent session's info when none exists."""
        from sessionlog import grading
        from sessionlog.parser import format_lap_time, session_label
        try:
            latest = grading.latest_milestone(recs)
            badge = self._latest_badge(recs)
        except Exception:
            return None
        # A career badge newer than the latest per-combo milestone wins
        # the panel — "NEW BADGE — FIRST BLOOD" beats "new PB here".
        if badge and (not latest
                      or (badge[0].get("date") or datetime.min)
                      > (latest[0].get("date") or datetime.min)):
            record, title = badge
            icon, prefix, celebrate = "trophy", "NEW BADGE", True
        elif latest:
            record, ms = latest
            m = ms[0]
            icon = {"🏆": "trophy", "⭐": "star", "🔥": "flame"}.get(
                m.get("icon"), "trophy")
            title = f"{m['title']} — {m['detail']}"
            prefix, celebrate = "LATEST MILESTONE", True
        else:
            dated = [r for r in recs if r.get("date")]
            if not dated:
                return None
            record = max(dated, key=lambda r: r["date"])
            title = session_label(record).replace("_", " ") or "session"
            best = record.get("best_lap_time")
            if best:
                title += f" — best {format_lap_time(best)}"
            icon, prefix, celebrate = "flag", "LAST SESSION", False
        date = record.get("date")
        when = date.strftime("%d %b").lstrip("0") if date else ""
        game = record.get("game_name") or record.get("game") or ""
        car  = record.get("car") or ""    # team name when known, else car class
        track = record.get("track") or ""
        context = "  ·  ".join(p for p in (prefix, game, car, track, when) if p)
        return {
            "title":     title.upper(),
            "context":   context.upper(),
            "icon":      icon,
            "celebrate": celebrate,
            "filename":  record.get("filename", ""),
        }

    @staticmethod
    def _latest_badge(recs):
        """(record, title) for the most recent badge-earning session, or
        None. Unlocks and tier upgrades only — a routine repeat doesn't
        take over the menu panel."""
        from sessionlog.achievements import badge, evaluate, tier_for
        earned = evaluate(recs)
        by_fn = {r.get("filename"): r for r in recs}
        newest = None
        for bid, state in earned.items():
            b = badge(bid)
            # Walk occurrences newest-first; count at that occurrence is
            # total minus how many came after it.
            for i, (fn, date) in enumerate(state["sessions"]):
                count_then = state["count"] - i
                if count_then == 1:
                    kind = "unlocked"
                elif b.get("tiers") and tier_for(b, count_then) \
                        != tier_for(b, count_then - 1):
                    kind = "upgraded"
                else:
                    continue
                rec = by_fn.get(fn)
                if rec is None:
                    continue
                if b.get("levels"):
                    lv = b["levels"][min(count_then, len(b["levels"])) - 1]
                    title = f"{b['name']} — {lv:,} {b.get('unit', '')}"
                elif kind == "unlocked":
                    title = b["name"]
                else:
                    title = (f"{b['name']} ×{count_then} — "
                             f"{tier_for(b, count_then)}")
                key = date or datetime.min
                if newest is None or key > (newest[0].get("date")
                                            or datetime.min):
                    newest = (rec, title)
                break   # newest qualifying occurrence per badge is enough
        return newest

    def _draw_milestone(self, hovered: bool):
        data = self._milestone
        if not data:
            return
        rect = self._milestone_rect()
        radius = 14
        if data["celebrate"]:
            # Amber glow — same treatment as an active game button.
            for expand, alpha in ((6, 0.10), (3, 0.20)):
                gr = rect.inflate(expand * 2, expand * 2)
                pygame.draw.rect(self._screen, _lerp(BG, AMBER, alpha),
                                 gr, border_radius=radius + expand)
        pygame.draw.rect(self._screen, PANEL2 if hovered else PANEL,
                         rect, border_radius=radius)
        pygame.draw.rect(self._screen, AMBER if data["celebrate"] else BORDER,
                         rect, width=1, border_radius=radius)

        self._draw_ms_icon(data["icon"], rect.x + 36, rect.centery)

        tx = rect.x + 66
        max_w = rect.right - 40 - tx
        title = self._fit_text(self._font_exit, data["title"], max_w,
                               DS.on_panel(AMBER) if data["celebrate"] else TEXT)
        ctx = self._fit_text(self._font_detail, data["context"], max_w, TEXT3)
        self._screen.blit(title, (tx, rect.y + 9))
        self._screen.blit(ctx, (tx, rect.y + 32))

        # Chevron — this panel is tappable (opens the session's detail view)
        cx, cy = rect.right - 24, rect.centery
        pygame.draw.lines(self._screen, TEXT4, False,
                          [(cx - 4, cy - 7), (cx + 3, cy), (cx - 4, cy + 7)], 2)

    def _fit_text(self, font, text: str, max_w: int, color) -> pygame.Surface:
        surf = font.render(text, True, color)
        while surf.get_width() > max_w and "·" in text:
            text = text.rsplit("·", 1)[0].rstrip(" ·")
            surf = font.render(text, True, color)
        return surf

    def _draw_ms_icon(self, kind: str, cx: int, cy: int):
        s = self._screen
        if kind == "star":
            pts = []
            for i in range(10):
                ang = -math.pi / 2 + i * math.pi / 5
                r = 13 if i % 2 == 0 else 5.5
                pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
            pygame.draw.polygon(s, AMBER, pts)
        elif kind == "flame":
            c = _lerp(AMBER, RED, 0.35)
            pygame.draw.polygon(s, c, [(cx - 8, cy + 3), (cx, cy - 13),
                                       (cx + 8, cy + 3)])
            pygame.draw.circle(s, c, (cx, cy + 4), 9)
            pygame.draw.circle(s, _lerp(c, (255, 246, 214), 0.6), (cx, cy + 5), 4)
        elif kind == "flag":
            pygame.draw.line(s, TEXT4, (cx - 11, cy - 13), (cx - 11, cy + 13), 2)
            for row in range(3):
                for col in range(3):
                    color = TEXT2 if (row + col) % 2 == 0 else BORDER
                    pygame.draw.rect(s, color, pygame.Rect(
                        cx - 8 + col * 6, cy - 13 + row * 6, 6, 6))
        else:  # trophy
            c = AMBER
            pygame.draw.circle(s, c, (cx - 10, cy - 7), 5, 2)   # handles
            pygame.draw.circle(s, c, (cx + 10, cy - 7), 5, 2)
            pygame.draw.rect(s, c, pygame.Rect(cx - 8, cy - 13, 16, 13),
                             border_bottom_left_radius=7,
                             border_bottom_right_radius=7)      # cup
            pygame.draw.rect(s, c, pygame.Rect(cx - 2, cy, 4, 7))          # stem
            pygame.draw.rect(s, c, pygame.Rect(cx - 8, cy + 7, 16, 4),
                             border_radius=1)                   # base

    def _draw_version(self):
        from version import __version__
        surf = self._font_detail.render(f"v{__version__}", True, TEXT4)
        self._screen.blit(surf, surf.get_rect(center=(self.W // 2, 468)))

    def _draw_screensaver(self, elapsed: float):
        """Dark idle screen — the menu is often left on-screen for long
        stretches (track editor, future web companion), so the wordmark
        drifts slowly to avoid burning the same pixels on the LCD."""
        self._screen.fill(BG)
        surf = self._font_header.render("SHFONIC DASH", True, TEXT4)
        sw, sh = surf.get_size()
        x = self._bounce(elapsed, _SAVER_VX, _SAVER_MARGIN, self.W - _SAVER_MARGIN - sw)
        y = self._bounce(elapsed, _SAVER_VY, _SAVER_MARGIN, self.H - _SAVER_MARGIN - sh)
        self._screen.blit(surf, (x, y))

    @staticmethod
    def _bounce(t: float, speed: float, lo: int, hi: int) -> int:
        """Position at time t bouncing back and forth between lo and hi."""
        span = hi - lo
        if span <= 0:
            return lo
        period = span * 2
        pos = (t * speed) % period
        if pos > span:
            pos = period - pos
        return int(lo + pos)

    def _open_settings(self, start_tab: str = "display") -> bool:
        """Open the settings overlay. Returns True if the user chose to quit.

        The server is left running if sharing is still enabled on close (the menu
        keeps it up), and stopped only if the user turned sharing off.
        """
        from core.settings_overlay import SettingsOverlay
        from core import config_store
        from dashboard.widgets.themes import apply_theme, DEFAULT_THEME
        from dashboard.widgets.accents import apply_accent_mode, DEFAULT_ACCENT
        from dashboard.widgets.units import set_unit_system, DEFAULT_UNITS

        cfg          = config_store.load()
        share_logs   = cfg.get("share_logs", False)
        window       = config_store.share_window_days(cfg)
        web_mode     = config_store.web_app_mode(cfg)

        # Start server if sharing is ON (share-on-demand) or the web companion
        # is enabled (menu/always) so its /app pages are reachable here.
        if self._log_server is not None:
            self._log_server.set_window(window)
            self._log_server.set_token(config_store.api_token(cfg))
            self._log_server.set_web_enabled(web_mode != "off")
            if (share_logs or web_mode != "off") and not self._log_server.running:
                self._log_server.start(self._logs_dir)

        def _server_wanted() -> bool:
            return self._share_logs or self._web_mode != "off"

        self._web_mode = web_mode

        def _on_toggle(enabled: bool):
            self._share_logs = enabled
            if self._log_server is None:
                return
            if _server_wanted() and not self._log_server.running:
                self._log_server.start(self._logs_dir)
            elif not _server_wanted() and self._log_server.running:
                self._log_server.stop()

        def _on_web_mode(mode: str):
            self._web_mode = mode
            if self._log_server is None:
                return
            self._log_server.set_web_enabled(mode != "off")
            if _server_wanted() and not self._log_server.running:
                self._log_server.start(self._logs_dir)
            elif not _server_wanted() and self._log_server.running:
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
            self._screen,
            current_flip=self._flip,
            current_theme=cfg.get("theme", DEFAULT_THEME),
            current_accent_mode=cfg.get("accent_mode", DEFAULT_ACCENT),
            current_units=cfg.get("units", DEFAULT_UNITS),
            show_menu_action=False,
            show_data_tabs=True,
            share_logs_active=share_logs,
            log_server_url=_get_url(),
            on_share_logs_toggle=_on_toggle,
            get_server_url=_get_url,
            share_window_days=window,
            on_window_change=_on_window,
            on_rebuild_index=_rebuild_index if self._logs_dir else None,
            show_session_summary=cfg.get("show_session_summary", True),
            debrief_enabled=cfg.get("debrief_enabled", True),
            screensaver_enabled=cfg.get("screensaver_enabled", True),
            record_button_enabled=self._record_enabled,
            show_sync_button=self._show_sync,
            web_app_mode=web_mode,
            on_web_mode_change=_on_web_mode,
            pairing_code=config_store.api_token(cfg),
            games=[{"id": g["id"], "name": g["name"]} for g in _GAMES],
            enabled_games=cfg.get("enabled_games") or {},
            start_tab=start_tab,
        )

        # Reconcile the server with the (possibly changed) prefs: the menu keeps
        # it running while sharing OR the web companion is enabled, and stops it
        # only when both are off.
        self._share_logs = result["share_logs"]
        self._web_mode   = result.get("web_app_mode", "menu")
        if self._log_server is not None:
            self._log_server.set_web_enabled(self._web_mode != "off")
            want = self._share_logs or self._web_mode != "off"
            if want and not self._log_server.running:
                self._log_server.start(self._logs_dir)
            elif not want and self._log_server.running:
                self._log_server.stop()

        apply_theme(result["theme"])
        apply_accent_mode(result["accent_mode"])
        set_unit_system(result["units"])
        self._flip             = result["flip"]
        cfg["theme"]           = result["theme"]
        cfg["flip"]            = result["flip"]
        cfg["accent_mode"]     = result["accent_mode"]
        cfg["units"]           = result["units"]
        cfg["share_logs"]        = result["share_logs"]
        cfg["share_window_days"] = result["share_window_days"]
        cfg.pop("log_retention_days", None)   # migrated to share_window_days
        cfg["show_session_summary"] = result["show_session_summary"]
        cfg["debrief_enabled"]      = result["debrief_enabled"]
        cfg["screensaver_enabled"]  = result["screensaver_enabled"]
        cfg["show_record_button"]   = result["record_button_enabled"]
        cfg["show_sync_button"]     = result["show_sync_button"]
        cfg["web_app_mode"]         = result.get("web_app_mode", "menu")
        cfg["enabled_games"]        = result["enabled_games"]
        config_store.save(cfg)
        self._record_enabled = result["record_button_enabled"]
        self._show_sync      = result["show_sync_button"]
        if not self._record_enabled:
            self._record_armed = False   # can't stay armed via a hidden pill
        self._share_window = result["share_window_days"]
        self._screensaver_on = result["screensaver_enabled"]
        self._last_activity  = time.time()   # don't trigger immediately on return
        self._config = cfg

        # Quit / shutdown now live on the menu's power button — settings only
        # returns "quit" when its window is closed (pygame.QUIT).
        return result["action"] == "quit"


def get_game_info(game_id: str) -> dict | None:
    """Return the _GAMES entry for game_id (name, color, etc.), or None."""
    return next((g for g in _GAMES if g["id"] == game_id), None)
