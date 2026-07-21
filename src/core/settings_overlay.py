"""Settings overlay — shown when the user long-presses during a session."""
import pygame

from core.flip import flip_pos, flip_surface
from dashboard.widgets.fonts import load_ui
from dashboard.widgets.themes import THEMES, THEME_ORDER, apply_theme
from dashboard.widgets.accents import apply_accent_mode
from dashboard.widgets import units

# ── Card geometry ─────────────────────────────────────────────────────────────
_CW, _CH = 640, 444
_CX = (800 - _CW) // 2   # 80
_CY = (480 - _CH) // 2   # 18
_PAD = 24                 # horizontal inset inside card
_PW  = _CW - _PAD * 2    # 592  usable content width

# ── Tab definitions ───────────────────────────────────────────────────────────
_TABS_BASE = [("display", "DISPLAY"), ("units", "UNITS")]
_TABS_MENU = [("display", "DISPLAY"), ("units", "UNITS"),
              ("games", "GAMES"), ("data", "DATA")]
_TAB_H    = 28
_TAB_GAP  = 10
_Y_TABS   = 4

# ── Row y-offsets from _CY ────────────────────────────────────────────────────
_Y_SEP1      = 46
_Y_THEME_LBL = 60
_Y_THEME_BTN = 78
_THEME_BTN_H = 70
_Y_SEP2      = _Y_THEME_BTN + _THEME_BTN_H + 6     # 154
_Y_DISP_LBL  = _Y_SEP2 + 10                        # 164
_Y_FLIP_ROW  = _Y_DISP_LBL + 12                    # 176
_TGL_ROW_H   = 40
_Y_CVD_ROW         = _Y_FLIP_ROW + _TGL_ROW_H          # 216
_Y_SUMMARY_ROW     = _Y_CVD_ROW + _TGL_ROW_H           # 256  end-of-session summary
_Y_DEBRIEF_ROW     = _Y_SUMMARY_ROW + _TGL_ROW_H       # 296  post-session questions
_Y_SCREENSAVER_ROW = _Y_DEBRIEF_ROW + _TGL_ROW_H       # 336  main-menu screensaver
_Y_SEP3        = _Y_SCREENSAVER_ROW + _TGL_ROW_H + 8   # 384
_Y_ACTIONS     = _Y_SEP3 + 10                           # 394
_ACTION_H      = 42

# ── DATA tab y-offsets (fits within same _CH) ─────────────────────────────────
_Y_DATA_SHARE_LBL = 60
_Y_DATA_SHARE_ROW = 76     # Share Logs toggle row (height _TGL_ROW_H)
_Y_DATA_URL       = 120    # URL text row (22 px gap between row and sep)
_Y_DATA_SEP       = 142
_Y_DATA_WIN_LBL   = 156
_Y_DATA_WIN_BTNS  = 172    # share-window button row
_WIN_BTN_H        = 48
_Y_DATA_REBUILD   = _Y_DATA_WIN_BTNS + _WIN_BTN_H + 12   # 232
_REBUILD_BTN_H    = 42     # ends at 274, well above sep3 (330)
_Y_DATA_SEP2      = _Y_DATA_REBUILD + _REBUILD_BTN_H + 12 # 286
_Y_DATA_RECORD    = _Y_DATA_SEP2 + 10                     # 296  Show RECORD button
_Y_DATA_WEB_LBL   = _Y_DATA_RECORD + _TGL_ROW_H + 4       # 340  WEB COMPANION label
_Y_DATA_WEB_BTNS  = _Y_DATA_WEB_LBL + 14                  # 354  off/menu/always row
_WEB_BTN_H        = 28                                    # ends at 382, above sep3
_WEB_OPTIONS      = [("off", "OFF"), ("menu", "MENU"), ("always", "ALWAYS")]
_WEB_GAP          = 10
_WEB_BTN_W        = (_PW - _WEB_GAP * (len(_WEB_OPTIONS) - 1)) // len(_WEB_OPTIONS)

# ── GAMES tab y-offsets ───────────────────────────────────────────────────────
_Y_GAMES_LBL  = 60
_Y_GAMES_ROW0 = 76     # first game toggle row; pitch is _TGL_ROW_H + 4

# Share window options: sessions from the last N days are listed for
# download; -1 = everything. Session files themselves are always kept —
# they are the dashboard's history database.
_WIN_OPTIONS = [(1, "1 DAY"), (7, "7 DAYS"), (30, "30 DAYS"), (-1, "ALL")]
_WIN_GAP     = 12
_WIN_BTN_W   = (_PW - _WIN_GAP * (len(_WIN_OPTIONS) - 1)) // len(_WIN_OPTIONS)

# ── Theme button geometry ─────────────────────────────────────────────────────
_TBTN_GAP = 10
_TBTN_W   = (_PW - _TBTN_GAP * (len(THEME_ORDER) - 1)) // len(THEME_ORDER)

# ── Units button geometry ─────────────────────────────────────────────────────
_UBTN_GAP = 16
_UBTN_W   = (_PW - _UBTN_GAP) // 2
_Y_UNITS_BTN = _Y_SEP1 + 12
_UNITS_BTN_H = _Y_SEP3 - _Y_UNITS_BTN - 12

# ── Action button geometry ────────────────────────────────────────────────────
_ABTN_GAP = 12

# ── Toggle pill geometry ──────────────────────────────────────────────────────
_FTGL_W, _FTGL_H = 90, 34


class SettingsOverlay:

    def __init__(self):
        self._font_hdr   = load_ui(17)
        self._font_label = load_ui(12)
        self._font_btn   = load_ui(14)
        self._font_url   = load_ui(11)

    # ── Public ───────────────────────────────────────────────────────────────

    def run(self, screen: pygame.Surface,
            current_flip: bool, current_theme: str, current_accent_mode: str = "standard",
            current_units: str = "metric",
            show_menu_action: bool = True,
            show_data_tabs: bool = False,
            share_logs_active: bool = False,
            log_server_url: str = "",
            on_share_logs_toggle=None,
            get_server_url=None,
            share_window_days: int = 7,
            on_window_change=None,
            on_rebuild_index=None,
            show_session_summary: bool = True,
            debrief_enabled: bool = True,
            screensaver_enabled: bool = True,
            record_button_enabled: bool = False,
            web_app_mode: str = "menu",
            on_web_mode_change=None,
            pairing_code: str = "",
            games: list | None = None,
            enabled_games: dict | None = None,
            start_tab: str = "display") -> dict:
        """Run the overlay loop.

        Returns dict with keys: action, flip, theme, accent_mode, units,
        share_logs, share_window_days, show_session_summary, enabled_games,
        debrief_enabled, screensaver_enabled.

        games: [{"id", "name"}, ...] — shown on the GAMES tab (menu only)
        with per-game visibility toggles; enabled_games maps game id →
        bool (missing = enabled). The last enabled game cannot be turned
        off (an empty menu helps nobody).

        show_menu_action=False hides the MENU button (use when already on menu).
        show_data_tabs=True adds the GAMES and DATA tabs (game menu only). Quit
        and shutdown live on the menu's own power button, not in here.
        on_share_logs_toggle: optional callable(bool) invoked immediately when toggled.
        get_server_url: optional callable() → str; refreshes the displayed URL.
        on_window_change: optional callable(days) invoked immediately when the
        share window changes (applies to the running log server live).
        on_rebuild_index: optional callable() → int (sessions indexed); enables
        the REBUILD SESSION INDEX button on the DATA tab.
        """
        pending_flip      = current_flip
        pending_theme     = current_theme
        pending_accent    = current_accent_mode
        pending_units     = current_units
        pending_share     = share_logs_active
        pending_window    = share_window_days
        pending_summary   = show_session_summary
        pending_debrief   = debrief_enabled
        pending_saver     = screensaver_enabled
        pending_record    = record_button_enabled
        pending_web_mode  = web_app_mode if web_app_mode in ("off", "menu", "always") else "menu"
        current_url       = log_server_url
        self._pairing_code = pairing_code
        self._games       = games or []
        enabled_games     = enabled_games or {}
        pending_games     = {g["id"]: bool(enabled_games.get(g["id"], True))
                             for g in self._games}
        # "data"/"games" tabs only exist on the game menu (show_data_tabs)
        active_tab        = (start_tab if (start_tab not in ("data", "games")
                                           or show_data_tabs) else "display")
        rebuild_state     = "idle"    # idle → done
        rebuilt_count     = 0
        frozen            = screen.copy()
        clock             = pygame.time.Clock()
        hovered           = None
        rects             = self._build_rects(show_menu_action, active_tab, show_data_tabs)

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return _out("quit", pending_flip, pending_theme, pending_accent,
                                pending_units, pending_share, pending_window, pending_summary, pending_games, pending_debrief, pending_saver, pending_record, pending_web_mode)

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return _out("dismiss", pending_flip, pending_theme, pending_accent,
                                    pending_units, pending_share, pending_window, pending_summary, pending_games, pending_debrief, pending_saver, pending_record, pending_web_mode)

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    pos = flip_pos(event.pos, pending_flip)
                    if not pygame.Rect(_CX, _CY, _CW, _CH).collidepoint(pos):
                        return _out("dismiss", pending_flip, pending_theme, pending_accent,
                                    pending_units, pending_share, pending_window, pending_summary, pending_games, pending_debrief, pending_saver, pending_record, pending_web_mode)
                    hit = _hit(rects, pos)
                    if hit and hit.startswith("tab:"):
                        tab = hit[4:]
                        if tab != active_tab:
                            active_tab = tab
                            hovered = None
                            rects = self._build_rects(show_menu_action, active_tab,
                                                      show_data_tabs)
                    elif hit and hit.startswith("theme:"):
                        t = hit[6:]
                        if t != pending_theme:
                            pending_theme = t
                            apply_theme(t)
                    elif hit and hit.startswith("units:"):
                        u = hit[6:]
                        if u != pending_units:
                            pending_units = u
                            units.set_unit_system(u)
                    elif hit and hit.startswith("win:"):
                        pending_window = int(hit[4:])
                        if on_window_change:
                            on_window_change(pending_window)
                    elif hit and hit.startswith("game:"):
                        gid = hit[5:]
                        if pending_games.get(gid, True):
                            # Refuse to disable the last enabled game
                            if sum(pending_games.values()) > 1:
                                pending_games[gid] = False
                        else:
                            pending_games[gid] = True
                    elif hit == "flip":
                        pending_flip = not pending_flip
                    elif hit == "summary":
                        pending_summary = not pending_summary
                    elif hit == "debrief":
                        pending_debrief = not pending_debrief
                    elif hit == "screensaver":
                        pending_saver = not pending_saver
                    elif hit == "record":
                        pending_record = not pending_record
                    elif hit and hit.startswith("web:"):
                        pending_web_mode = hit[4:]
                        if on_web_mode_change:
                            on_web_mode_change(pending_web_mode)
                        if get_server_url:
                            current_url = get_server_url()
                    elif hit == "show_qr":
                        if current_url and self._pairing_code:
                            self._show_qr_modal(screen, current_url,
                                                self._pairing_code, pending_flip)
                    elif hit == "cvd":
                        pending_accent = "colourblind" if pending_accent != "colourblind" else "standard"
                        apply_accent_mode(pending_accent)
                    elif hit == "rebuild_index":
                        if rebuild_state == "idle" and on_rebuild_index:
                            rebuilt_count = on_rebuild_index()
                            rebuild_state = "done"
                    elif hit == "share_logs":
                        pending_share = not pending_share
                        if on_share_logs_toggle:
                            on_share_logs_toggle(pending_share)
                        if get_server_url:
                            current_url = get_server_url()
                    elif hit in ("dismiss", "menu"):
                        return _out(hit, pending_flip, pending_theme, pending_accent,
                                    pending_units, pending_share, pending_window, pending_summary, pending_games, pending_debrief, pending_saver, pending_record, pending_web_mode)

                elif event.type == pygame.MOUSEMOTION:
                    hovered = _hit(rects, flip_pos(event.pos, pending_flip))

            self._draw(screen, frozen, pending_flip, pending_theme, pending_accent,
                       pending_units, active_tab, hovered, rects,
                       show_data_tabs, pending_share, current_url, pending_window,
                       rebuild_state, rebuilt_count, pending_summary, pending_games, pending_debrief,
                       pending_saver, pending_record, pending_web_mode)
            pygame.display.flip()
            clock.tick(30)

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_rects(self, show_menu_action: bool = True, active_tab: str = "display",
                     show_data_tabs: bool = False) -> dict:
        rects = {}
        px    = _CX + _PAD
        cx    = _CX + _CW // 2
        tabs  = _TABS_MENU if show_data_tabs else _TABS_BASE
        tab_w = _PW // len(tabs) - _TAB_GAP + (_TAB_GAP // len(tabs))

        # Compute a clean uniform tab width that fits
        total_gap = _TAB_GAP * (len(tabs) - 1)
        tab_w     = (_PW - total_gap) // len(tabs)

        # Tab bar — centred
        total_w = tab_w * len(tabs) + _TAB_GAP * (len(tabs) - 1)
        tx = cx - total_w // 2
        for tab_id, _ in tabs:
            rects[f"tab:{tab_id}"] = pygame.Rect(tx, _CY + _Y_TABS, tab_w, _TAB_H)
            tx += tab_w + _TAB_GAP

        if active_tab == "display":
            for i, tid in enumerate(THEME_ORDER):
                bx = px + i * (_TBTN_W + _TBTN_GAP)
                rects[f"theme:{tid}"] = pygame.Rect(bx, _CY + _Y_THEME_BTN, _TBTN_W, _THEME_BTN_H)

            rects["flip"] = pygame.Rect(
                px + _PW - _FTGL_W,
                _CY + _Y_FLIP_ROW + (_TGL_ROW_H - _FTGL_H) // 2,
                _FTGL_W, _FTGL_H,
            )
            rects["cvd"] = pygame.Rect(
                px + _PW - _FTGL_W,
                _CY + _Y_CVD_ROW + (_TGL_ROW_H - _FTGL_H) // 2,
                _FTGL_W, _FTGL_H,
            )
            rects["summary"] = pygame.Rect(
                px + _PW - _FTGL_W,
                _CY + _Y_SUMMARY_ROW + (_TGL_ROW_H - _FTGL_H) // 2,
                _FTGL_W, _FTGL_H,
            )
            rects["debrief"] = pygame.Rect(
                px + _PW - _FTGL_W,
                _CY + _Y_DEBRIEF_ROW + (_TGL_ROW_H - _FTGL_H) // 2,
                _FTGL_W, _FTGL_H,
            )
            rects["screensaver"] = pygame.Rect(
                px + _PW - _FTGL_W,
                _CY + _Y_SCREENSAVER_ROW + (_TGL_ROW_H - _FTGL_H) // 2,
                _FTGL_W, _FTGL_H,
            )

        elif active_tab == "units":
            for i, sid in enumerate(units.UNIT_ORDER):
                bx = px + i * (_UBTN_W + _UBTN_GAP)
                rects[f"units:{sid}"] = pygame.Rect(bx, _CY + _Y_UNITS_BTN, _UBTN_W, _UNITS_BTN_H)

        elif active_tab == "games":
            for i, game in enumerate(getattr(self, "_games", [])):
                ry = _CY + _Y_GAMES_ROW0 + i * (_TGL_ROW_H + 4)
                rects[f"game:{game['id']}"] = pygame.Rect(
                    px + _PW - _FTGL_W,
                    ry + (_TGL_ROW_H - _FTGL_H) // 2,
                    _FTGL_W, _FTGL_H,
                )

        elif active_tab == "data":
            rects["share_logs"] = pygame.Rect(
                px + _PW - _FTGL_W,
                _CY + _Y_DATA_SHARE_ROW + (_TGL_ROW_H - _FTGL_H) // 2,
                _FTGL_W, _FTGL_H,
            )
            for i, (days, _label) in enumerate(_WIN_OPTIONS):
                bx = px + i * (_WIN_BTN_W + _WIN_GAP)
                rects[f"win:{days}"] = pygame.Rect(bx, _CY + _Y_DATA_WIN_BTNS,
                                                   _WIN_BTN_W, _WIN_BTN_H)
            rects["rebuild_index"] = pygame.Rect(px, _CY + _Y_DATA_REBUILD,
                                                 _PW, _REBUILD_BTN_H)
            rects["record"] = pygame.Rect(
                px + _PW - _FTGL_W,
                _CY + _Y_DATA_RECORD + (_TGL_ROW_H - _FTGL_H) // 2,
                _FTGL_W, _FTGL_H,
            )
            for i, (mode, _label) in enumerate(_WEB_OPTIONS):
                bx = px + i * (_WEB_BTN_W + _WEB_GAP)
                rects[f"web:{mode}"] = pygame.Rect(bx, _CY + _Y_DATA_WEB_BTNS,
                                                   _WEB_BTN_W, _WEB_BTN_H)
            # The server URL line doubles as the "show pairing QR" affordance.
            rects["show_qr"] = pygame.Rect(px, _CY + _Y_DATA_URL - 2, _PW, 24)

        # Quit / shutdown moved to the game menu's power button; settings only
        # ever closes itself (DISMISS) or returns to the menu mid-session (MENU).
        # A lone DISMISS is a normal-width button centred in the card rather than
        # a heavy full-width bar, matching the mid-session DISMISS/MENU pair.
        actions = ("dismiss", "menu") if show_menu_action else ("dismiss",)
        abw     = (_PW - _ABTN_GAP) // 2
        group_w = len(actions) * abw + _ABTN_GAP * (len(actions) - 1)
        start_x = cx - group_w // 2
        for i, key in enumerate(actions):
            rects[key] = pygame.Rect(
                start_x + i * (abw + _ABTN_GAP),
                _CY + _Y_ACTIONS,
                abw, _ACTION_H,
            )

        return rects

    # ── Rendering ────────────────────────────────────────────────────────────

    def _draw(self, screen, frozen, flip, theme_id, accent_mode, units_mode, active_tab,
              hovered, rects, in_menu: bool = False, share_logs: bool = False,
              server_url: str = "", window_days: int = 7,
              rebuild_state: str = "idle", rebuilt_count: int = 0,
              show_summary: bool = True, enabled_games: dict | None = None,
              debrief_on: bool = True, screensaver_on: bool = True,
              record_on: bool = False, web_mode: str = "menu"):
        from dashboard.widgets import design_system as DS

        screen.blit(frozen, (0, 0))

        scrim = pygame.Surface((800, 480), pygame.SRCALPHA)
        scrim.fill((0, 0, 0, 185))
        screen.blit(scrim, (0, 0))

        # Card
        card = pygame.Rect(_CX, _CY, _CW, _CH)
        pygame.draw.rect(screen, DS.PANEL, card, border_radius=12)
        pygame.draw.rect(screen, DS.BORDER2, card, width=1, border_radius=12)

        px   = _CX + _PAD
        tabs = _TABS_MENU if in_menu else _TABS_BASE

        # Tab bar
        for tab_id, label in tabs:
            rect      = rects[f"tab:{tab_id}"]
            is_active = tab_id == active_tab
            is_hov    = hovered == f"tab:{tab_id}"
            pygame.draw.rect(screen, DS.PANEL2, rect, border_radius=6)
            border_c = DS.CYAN if is_active else (DS.BORDER2 if is_hov else DS.BORDER)
            pygame.draw.rect(screen, border_c, rect, width=2 if is_active else 1, border_radius=6)
            text_c = DS.on_panel(DS.CYAN) if is_active else DS.TEXT3
            s = self._font_btn.render(label, True, text_c)
            screen.blit(s, s.get_rect(center=rect.center))

        # Sep 1
        pygame.draw.line(screen, DS.BORDER, (px, _CY + _Y_SEP1), (px + _PW, _CY + _Y_SEP1))

        if active_tab == "display":
            lbl = self._font_label.render("THEME", True, DS.TEXT3)
            screen.blit(lbl, (px, _CY + _Y_THEME_LBL))

            for tid in THEME_ORDER:
                rect = rects[f"theme:{tid}"]
                self._draw_theme_btn(screen, rect, tid, theme_id, hovered == f"theme:{tid}")

            pygame.draw.line(screen, DS.BORDER, (px, _CY + _Y_SEP2), (px + _PW, _CY + _Y_SEP2))

            lbl = self._font_label.render("DISPLAY", True, DS.TEXT3)
            screen.blit(lbl, (px, _CY + _Y_DISP_LBL))

            fl = self._font_btn.render("Flip display  180°", True, DS.TEXT2)
            screen.blit(fl, (px, _CY + _Y_FLIP_ROW + (_TGL_ROW_H - fl.get_height()) // 2))
            self._draw_toggle(screen, rects["flip"], flip, hovered == "flip")

            cvd = self._font_btn.render("Colour-blind safe colours", True, DS.TEXT2)
            screen.blit(cvd, (px, _CY + _Y_CVD_ROW + (_TGL_ROW_H - cvd.get_height()) // 2))
            self._draw_toggle(screen, rects["cvd"], accent_mode == "colourblind", hovered == "cvd")

            sm = self._font_btn.render("End-of-session summary", True, DS.TEXT2)
            screen.blit(sm, (px, _CY + _Y_SUMMARY_ROW + (_TGL_ROW_H - sm.get_height()) // 2))
            self._draw_toggle(screen, rects["summary"], show_summary, hovered == "summary")

            db = self._font_btn.render("Post-session questions", True, DS.TEXT2)
            screen.blit(db, (px, _CY + _Y_DEBRIEF_ROW + (_TGL_ROW_H - db.get_height()) // 2))
            self._draw_toggle(screen, rects["debrief"], debrief_on, hovered == "debrief")

            ss = self._font_btn.render("Menu screensaver", True, DS.TEXT2)
            screen.blit(ss, (px, _CY + _Y_SCREENSAVER_ROW + (_TGL_ROW_H - ss.get_height()) // 2))
            self._draw_toggle(screen, rects["screensaver"], screensaver_on, hovered == "screensaver")

        elif active_tab == "units":
            for sid in units.UNIT_ORDER:
                rect = rects[f"units:{sid}"]
                self._draw_units_btn(screen, rect, sid, units_mode, hovered == f"units:{sid}")

        elif active_tab == "games":
            lbl = self._font_label.render("GAMES SHOWN ON THE MENU", True, DS.TEXT3)
            screen.blit(lbl, (px, _CY + _Y_GAMES_LBL))
            for i, game in enumerate(getattr(self, "_games", [])):
                ry = _CY + _Y_GAMES_ROW0 + i * (_TGL_ROW_H + 4)
                name = self._font_btn.render(game["name"], True, DS.TEXT2)
                screen.blit(name, (px, ry + (_TGL_ROW_H - name.get_height()) // 2))
                key = f"game:{game['id']}"
                self._draw_toggle(screen, rects[key],
                                  (enabled_games or {}).get(game["id"], True),
                                  hovered == key)

        elif active_tab == "data":
            # Share Logs section
            lbl = self._font_label.render("SHARE LOGS", True, DS.TEXT3)
            screen.blit(lbl, (px, _CY + _Y_DATA_SHARE_LBL))

            sl = self._font_btn.render("Share logs over Wi-Fi", True, DS.TEXT2)
            screen.blit(sl, (px, _CY + _Y_DATA_SHARE_ROW + (_TGL_ROW_H - sl.get_height()) // 2))
            self._draw_toggle(screen, rects["share_logs"], share_logs, hovered == "share_logs")

            code = getattr(self, "_pairing_code", "")
            server_live = (share_logs or web_mode != "off") and server_url
            if server_live:
                url_s = self._font_url.render(server_url, True, DS.on_panel(DS.CYAN))
                screen.blit(url_s, (px, _CY + _Y_DATA_URL))
                # Tap hint — the URL row opens the scannable pairing QR.
                if code and web_mode != "off":
                    tip = self._font_url.render("· TAP FOR QR", True, DS.TEXT3)
                    screen.blit(tip, (px + url_s.get_width() + 10, _CY + _Y_DATA_URL))
            if server_live and code:
                # The companion asks for this once when pairing.
                code_s = self._font_url.render(f"PAIRING CODE  {code}",
                                               True, DS.on_panel(DS.AMBER))
                screen.blit(code_s, code_s.get_rect(
                    topright=(px + _PW, _CY + _Y_DATA_URL)))

            # Separator
            pygame.draw.line(screen, DS.BORDER,
                             (px, _CY + _Y_DATA_SEP), (px + _PW, _CY + _Y_DATA_SEP))

            # Share window section — what index.json lists for download.
            # Session files themselves are always kept (history database).
            lbl = self._font_label.render("SHARE SESSIONS FROM THE LAST", True, DS.TEXT3)
            screen.blit(lbl, (px, _CY + _Y_DATA_WIN_LBL))

            for i, (days, label) in enumerate(_WIN_OPTIONS):
                rect      = rects[f"win:{days}"]
                is_active = days == window_days
                is_hov    = hovered == f"win:{days}"
                self._draw_window_btn(screen, rect, label, is_active, is_hov)

            self._draw_rebuild_btn(screen, rects["rebuild_index"],
                                   rebuild_state, rebuilt_count,
                                   hovered == "rebuild_index")

            pygame.draw.line(screen, DS.BORDER, (px, _CY + _Y_DATA_SEP2),
                             (px + _PW, _CY + _Y_DATA_SEP2))
            rc = self._font_btn.render("Show RECORD button (track mapping)",
                                       True, DS.TEXT2)
            screen.blit(rc, (px, _CY + _Y_DATA_RECORD + (_TGL_ROW_H - rc.get_height()) // 2))
            self._draw_toggle(screen, rects["record"], record_on, hovered == "record")

            # Web companion — when the browser dashboard is reachable.
            wl = self._font_label.render("WEB COMPANION (BROWSER)", True, DS.TEXT3)
            screen.blit(wl, (px, _CY + _Y_DATA_WEB_LBL))
            for mode, label in _WEB_OPTIONS:
                self._draw_seg_btn(screen, rects[f"web:{mode}"], label,
                                   web_mode == mode, hovered == f"web:{mode}")

        # Sep 3
        pygame.draw.line(screen, DS.BORDER, (px, _CY + _Y_SEP3), (px + _PW, _CY + _Y_SEP3))

        # Action buttons — only draw ones present in rects
        _ACTION_STYLES = {
            "dismiss":  (DS.TEXT,  "DISMISS"),
            "menu":     (DS.AMBER, "MENU"),
        }
        for key, (color, label) in _ACTION_STYLES.items():
            if key not in rects:
                continue
            rect   = rects[key]
            is_hov = hovered == key
            pygame.draw.rect(screen, DS.PANEL2, rect, border_radius=6)
            pygame.draw.rect(screen, color if is_hov else DS.BORDER, rect, width=1, border_radius=6)
            s = self._font_btn.render(label, True, color if is_hov else DS.TEXT3)
            screen.blit(s, s.get_rect(center=rect.center))

        flip_surface(screen, flip)

    def _draw_toggle(self, screen, rect, on, hovered):
        from dashboard.widgets import design_system as DS
        r = rect.height // 2
        if on:
            pygame.draw.rect(screen, DS.CYAN, rect, border_radius=r)
            ts = self._font_btn.render("ON", True, DS.INK)
        else:
            pygame.draw.rect(screen, DS.PANEL2, rect, border_radius=r)
            border_c = DS.BORDER2 if hovered else DS.BORDER
            pygame.draw.rect(screen, border_c, rect, width=1, border_radius=r)
            ts = self._font_btn.render("OFF", True, DS.TEXT3)
        screen.blit(ts, ts.get_rect(center=rect.center))

    def _draw_rebuild_btn(self, screen, rect, state: str, count: int, hovered: bool):
        from dashboard.widgets import design_system as DS
        pygame.draw.rect(screen, DS.PANEL2, rect, border_radius=6)
        if state == "done":
            pygame.draw.rect(screen, DS.BORDER, rect, width=1, border_radius=6)
            label = ("1 SESSION INDEXED" if count == 1
                     else f"{count} SESSIONS INDEXED")
            color = DS.TEXT3
        else:
            pygame.draw.rect(screen, DS.CYAN if hovered else DS.BORDER, rect,
                             width=1, border_radius=6)
            label, color = "REBUILD SESSION INDEX", (DS.on_panel(DS.CYAN) if hovered else DS.TEXT3)
        s = self._font_btn.render(label, True, color)
        screen.blit(s, s.get_rect(center=rect.center))

    def _draw_window_btn(self, screen, rect, label: str, is_active: bool, hovered: bool):
        from dashboard.widgets import design_system as DS
        r = 8
        pygame.draw.rect(screen, DS.PANEL2, rect, border_radius=r)
        if is_active:
            pygame.draw.rect(screen, DS.CYAN, rect, width=2, border_radius=r)
        elif hovered:
            pygame.draw.rect(screen, DS.BORDER2, rect, width=1, border_radius=r)
        else:
            pygame.draw.rect(screen, DS.BORDER, rect, width=1, border_radius=r)
        text_c = DS.TEXT if is_active else DS.TEXT3
        s = self._font_btn.render(label, True, text_c)
        screen.blit(s, s.get_rect(center=rect.center))
        if is_active:
            pygame.draw.circle(screen, DS.CYAN, (rect.centerx, rect.bottom - 10), 3)
        else:
            pygame.draw.circle(screen, DS.BORDER2, (rect.centerx, rect.bottom - 10), 3, 1)

    def _draw_seg_btn(self, screen, rect, label: str, is_active: bool, hovered: bool):
        """Compact segmented-control button (web-companion off/menu/always)."""
        from dashboard.widgets import design_system as DS
        r = 7
        pygame.draw.rect(screen, DS.PANEL2, rect, border_radius=r)
        if is_active:
            pygame.draw.rect(screen, DS.CYAN, rect, width=2, border_radius=r)
        elif hovered:
            pygame.draw.rect(screen, DS.BORDER2, rect, width=1, border_radius=r)
        else:
            pygame.draw.rect(screen, DS.BORDER, rect, width=1, border_radius=r)
        s = self._font_label.render(label, True, DS.TEXT if is_active else DS.TEXT3)
        screen.blit(s, s.get_rect(center=rect.center))

    def _show_qr_modal(self, screen, server_url: str, code: str, flip: bool):
        """Full-screen scannable QR for the web-companion pairing URL. Blocks
        until any tap / ESC, then returns to the settings overlay."""
        from core import qr_render
        from dashboard.widgets import design_system as DS
        url = f"http://{server_url}/app?key={code}"
        try:
            module_px = min(7, max(3, qr_render.fit_module_px(url, 320)))
            qr_surf = qr_render.to_surface(url, module_px=module_px,
                                           dark=(20, 20, 20), light=(245, 245, 245))
        except Exception:
            return
        frozen = screen.copy()
        clock  = pygame.time.Clock()
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    return
                if event.type == pygame.MOUSEBUTTONDOWN:
                    return
            screen.blit(frozen, (0, 0))
            scrim = pygame.Surface((800, 480), pygame.SRCALPHA)
            scrim.fill((0, 0, 0, 220))
            screen.blit(scrim, (0, 0))
            qr_rect = qr_surf.get_rect(center=(400, 218))
            pad = pygame.Rect(qr_rect.x - 14, qr_rect.y - 14,
                              qr_rect.width + 28, qr_rect.height + 28)
            pygame.draw.rect(screen, (245, 245, 245), pad, border_radius=12)
            screen.blit(qr_surf, qr_rect)
            cap = self._font_label.render("SCAN TO OPEN THE WEB COMPANION",
                                          True, DS.TEXT2)
            screen.blit(cap, cap.get_rect(center=(400, qr_rect.bottom + 34)))
            sub = self._font_url.render(f"{server_url}/app   ·   TAP TO CLOSE",
                                        True, DS.TEXT3)
            screen.blit(sub, sub.get_rect(center=(400, qr_rect.bottom + 56)))
            flip_surface(screen, flip)
            pygame.display.flip()
            clock.tick(30)

    def _draw_theme_btn(self, screen, rect, theme_id, active_id, hovered):
        from dashboard.widgets import design_system as DS
        preset    = THEMES[theme_id]
        is_active = theme_id == active_id
        r         = 8

        pygame.draw.rect(screen, preset["PANEL"], rect, border_radius=r)

        sw_rect = pygame.Rect(rect.x + 8, rect.y + 10, rect.width - 16, 16)
        pygame.draw.rect(screen, preset["BG"], sw_rect, border_radius=3)
        bw = (sw_rect.width - 8) // 3
        for i in range(3):
            br = pygame.Rect(sw_rect.x + 2 + i * (bw + 2), sw_rect.y + 3, bw, sw_rect.height - 6)
            pygame.draw.rect(screen, preset["PANEL2"], br, border_radius=2)

        name_s = self._font_btn.render(preset["name"], True, DS.TEXT if is_active else DS.TEXT3)
        screen.blit(name_s, name_s.get_rect(center=(rect.centerx, rect.y + rect.height - 22)))

        dot_y = rect.bottom - 9
        if is_active:
            pygame.draw.circle(screen, DS.CYAN, (rect.centerx, dot_y), 3)
        else:
            pygame.draw.circle(screen, preset["BORDER2"], (rect.centerx, dot_y), 3, 1)

        if is_active:
            pygame.draw.rect(screen, DS.CYAN, rect, width=2, border_radius=r)
        elif hovered:
            pygame.draw.rect(screen, DS.BORDER2, rect, width=1, border_radius=r)
        else:
            pygame.draw.rect(screen, preset["BORDER"], rect, width=1, border_radius=r)

    def _draw_units_btn(self, screen, rect, sys_id, active_id, hovered):
        from dashboard.widgets import design_system as DS
        preset    = units.UNIT_SYSTEMS[sys_id]
        is_active = sys_id == active_id
        r         = 10

        pygame.draw.rect(screen, DS.PANEL2, rect, border_radius=r)

        title_s = self._font_hdr.render(preset["name"], True, DS.TEXT if is_active else DS.TEXT3)
        screen.blit(title_s, title_s.get_rect(midtop=(rect.centerx, rect.y + 18)))

        rows = [
            ("Speed",         preset["speed"]),
            ("Temperature",   preset["temp"]),
            ("Tyre pressure", preset["pressure"]),
        ]
        row_y = rect.y + 18 + title_s.get_height() + 18
        for label, value in rows:
            lbl_s = self._font_btn.render(label, True, DS.TEXT3)
            val_s = self._font_btn.render(value, True, DS.TEXT2)
            screen.blit(lbl_s, (rect.x + 24, row_y))
            screen.blit(val_s, val_s.get_rect(topright=(rect.right - 24, row_y)))
            row_y += lbl_s.get_height() + 12

        dot_y = rect.bottom - 14
        if is_active:
            pygame.draw.circle(screen, DS.CYAN, (rect.centerx, dot_y), 3)
        else:
            pygame.draw.circle(screen, DS.BORDER2, (rect.centerx, dot_y), 3, 1)

        if is_active:
            pygame.draw.rect(screen, DS.CYAN, rect, width=2, border_radius=r)
        elif hovered:
            pygame.draw.rect(screen, DS.BORDER2, rect, width=1, border_radius=r)
        else:
            pygame.draw.rect(screen, DS.BORDER, rect, width=1, border_radius=r)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _out(action: str, flip: bool, theme: str, accent_mode: str, units_mode: str,
         share_logs: bool = False, share_window_days: int = 7,
         show_session_summary: bool = True,
         enabled_games: dict | None = None,
         debrief_enabled: bool = True,
         screensaver_enabled: bool = True,
         record_button_enabled: bool = False,
         web_app_mode: str = "menu") -> dict:
    return {
        "action":               action,
        "flip":                 flip,
        "theme":                theme,
        "accent_mode":          accent_mode,
        "units":                units_mode,
        "share_logs":           share_logs,
        "share_window_days":    share_window_days,
        "show_session_summary": show_session_summary,
        "enabled_games":        enabled_games or {},
        "debrief_enabled":      debrief_enabled,
        "screensaver_enabled":  screensaver_enabled,
        "record_button_enabled": record_button_enabled,
        "web_app_mode":         web_app_mode,
    }


def _hit(rects: dict, pos) -> str | None:
    for key, rect in rects.items():
        if rect.collidepoint(pos):
            return key
    return None
