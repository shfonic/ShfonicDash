"""
DashboardManager — auto-selects and loads dashboard configs based on the
car class and session type reported in TelemetryData.

Config resolution order (first found wins):
  {car_class}_{session_type}.json   e.g. gt3_race.json
  {car_class}_default.json          e.g. gt3_default.json
  default.json

Touch swipe left/right cycles through available configs for the current
car class (manual override).
"""

import logging
import math
import os
import pygame

from dashboard.config_dashboard import ConfigDashboard, find_config
from dashboard.text_dashboard import TextDashboard
from core.telemetry_model import TelemetryData
from core.session_history import SessionHistory

log = logging.getLogger("dashboard")

_CONFIGS_DIR = os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'configs')

# How many pixels of horizontal travel counts as a swipe
_SWIPE_THRESHOLD = 60


def _config_path(name: str) -> str | None:
    path = os.path.join(_CONFIGS_DIR, f"{name}.json")
    return path if os.path.isfile(path) else None


def _resolve_config(car_class: str, session_type: str) -> str | None:
    """Return the config file path for the given car/session, or None."""
    candidates = [
        f"{car_class}_{session_type}",
        f"{car_class}_default",
        "default",
    ]
    for name in candidates:
        path = _config_path(name)
        if path:
            return path
    return None


_SESSION_SUFFIXES = {"race", "practice", "qualifying", "hotlap", "default"}


def _results_state(data: TelemetryData) -> str | None:
    """Race-end banner state.

    Once the player's race result is decided (finished, DNF, ...), the final
    classification packet — sent only at the official results screen — is the
    last thing worth waiting for: it carries race times and the classified
    order. Warn until it lands, confirm once it has.
    """
    if data.session_type != "race" or not data.finish_status:
        return None
    return "saved" if data.classification_received else "pending"


def _configs_for_class(car_class: str) -> list[str]:
    """Return config file paths that belong exactly to car_class (not sub-namespaces)."""
    if not os.path.isdir(_CONFIGS_DIR):
        return []
    prefix = f"{car_class}_"
    results = []
    for fname in sorted(os.listdir(_CONFIGS_DIR)):
        if fname.endswith(".json") and fname.startswith(prefix):
            suffix = fname[len(prefix):-5]  # strip prefix and ".json"
            if suffix in _SESSION_SUFFIXES:
                results.append(os.path.join(_CONFIGS_DIR, fname))
    return results


class DashboardManager:
    """
    Owns the active dashboard. Automatically switches when car_class or
    session_type changes. Supports manual cycling via swipe.
    """

    def __init__(self, width: int, height: int, force_config: str = None,
                 game_label: str = "", game_color: tuple = None,
                 telemetry_port: int = None):
        self._width = width
        self._height = height
        self._force_config = force_config  # None = auto-manage
        self._game_label = game_label
        self._game_color = game_color
        self._game_id = ""            # from telemetry (data.game) — for the format hint
        self._telemetry_port = telemetry_port
        self._local_ip = None

        self._current_dashboard = None
        self._current_car_class = None
        self._current_session_type = None
        self._current_path = None

        # Manual cycling state
        self._cycle_paths: list[str] = []
        self._cycle_index: int = 0
        self._manual_override: bool = False

        # Swipe tracking
        self._touch_down_x: int | None = None

        # Lazy-loaded fonts for waiting screen and pause overlay
        self._wait_fonts = None
        self._pause_fonts = None

        # Pause overlay state
        self._paused: bool = False
        self._pause_surface: pygame.Surface | None = None

        # Race-end results banner: None | "pending" | "saved"
        self._results_state: str | None = None
        self._results_font = None

        # Last config load failure — shown as an on-screen banner until a
        # config loads successfully (a log line is invisible on the Pi).
        self._load_error: str | None = None
        self._error_font = None

        self._session = SessionHistory()

        if force_config:
            self._load_path(force_config)

    # ------------------------------------------------------------------
    # Main interface
    # ------------------------------------------------------------------

    def update(self, data: TelemetryData) -> None:
        if data.game:
            self._game_id = data.game
        self._paused = data.game_paused
        self._results_state = _results_state(data)
        self._session.update(data)
        if not self._manual_override:
            self._auto_switch(data)
        if self._current_dashboard:
            self._current_dashboard.update(data)

    def render(self, surface: pygame.Surface) -> None:
        if self._current_dashboard:
            self._current_dashboard.render(surface)
        else:
            self._render_waiting(surface)
        if self._load_error:
            self._render_error_banner(surface)
        if self._results_state:
            self._render_results_banner(surface)
        if self._paused:
            self._render_pause_overlay(surface)

    def _render_results_banner(self, surface: pygame.Surface) -> None:
        from dashboard.widgets.fonts import load_ui

        if self._results_font is None:
            self._results_font = load_ui(14)

        if self._results_state == "saved":
            bg, fg = (14, 82, 45), (190, 255, 215)
            text = "RESULTS SAVED — SAFE TO EXIT"
        else:
            bg, fg = (176, 122, 6), (24, 17, 0)
            text = "RACE FINISHED — WAIT FOR CLASSIFICATION BEFORE EXITING"

        w = surface.get_width()
        h = self._results_font.get_height() + 12
        banner = pygame.Surface((w, h), pygame.SRCALPHA)
        banner.fill((*bg, 235))
        lbl = self._results_font.render(text, True, fg)
        banner.blit(lbl, lbl.get_rect(center=(w // 2, h // 2)))
        surface.blit(banner, (0, 0))

    def _render_error_banner(self, surface: pygame.Surface) -> None:
        from dashboard.widgets.fonts import load_ui

        if self._error_font is None:
            self._error_font = load_ui(12)

        w = surface.get_width()
        pad, line_h = 6, self._error_font.get_height() + 2

        # Naive greedy wrap into at most 3 lines
        words, lines, cur = self._load_error.split(), [], ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if self._error_font.size(trial)[0] > w - pad * 2 and cur:
                lines.append(cur)
                cur = word
                if len(lines) == 3:
                    cur += " …"
                    break
            else:
                cur = trial
        lines.append(cur)

        banner = pygame.Surface((w, pad * 2 + line_h * len(lines)), pygame.SRCALPHA)
        banner.fill((120, 20, 20, 230))
        for i, line in enumerate(lines):
            banner.blit(self._error_font.render(line, True, (255, 220, 220)),
                        (pad, pad + i * line_h))
        surface.blit(banner, (0, 0))

    def _render_pause_overlay(self, surface: pygame.Surface) -> None:
        from dashboard.widgets.design_system import TEXT2, TEXT4
        from dashboard.widgets.fonts import load_ui

        if self._pause_fonts is None:
            self._pause_fonts = {
                'label': load_ui(22),
                'hint':  load_ui(12),
            }

        w, h = surface.get_size()

        # Semi-transparent veil — created once, reused every frame
        if self._pause_surface is None or self._pause_surface.get_size() != (w, h):
            self._pause_surface = pygame.Surface((w, h), pygame.SRCALPHA)
            self._pause_surface.fill((0, 0, 0, 160))

        surface.blit(self._pause_surface, (0, 0))

        cx, cy = w // 2, h // 2
        lbl = self._pause_fonts['label'].render("PAUSED", True, TEXT2)
        surface.blit(lbl, lbl.get_rect(center=(cx, cy)))
        hint = self._pause_fonts['hint'].render("Hold to return to menu", True, TEXT4)
        surface.blit(hint, hint.get_rect(center=(cx, cy + 28)))

    def _render_waiting(self, surface: pygame.Surface) -> None:
        from dashboard.widgets.design_system import BG, TEXT3, TEXT4, CYAN
        from dashboard.widgets.fonts import load_ui

        if self._wait_fonts is None:
            self._wait_fonts = {
                'hdr':   load_ui(13),
                'title': load_ui(30),
                'label': load_ui(16),
                'hint':  load_ui(12),
            }

        fonts  = self._wait_fonts
        accent = self._game_color or CYAN
        surface.fill(BG)
        w, h = surface.get_size()
        cx, cy = w // 2, h // 2

        # Subtle app header — matches the game menu header
        hdr = fonts['hdr'].render("SHFONIC DASH", True, TEXT4)
        surface.blit(hdr, hdr.get_rect(center=(cx, 28)))

        if self._game_label:
            # Game name in accent colour
            name_surf = fonts['title'].render(self._game_label.upper(), True, accent)
            surface.blit(name_surf, name_surf.get_rect(center=(cx, cy - 55)))

            # Thin separator
            dim = tuple(max(0, int(c * 0.30)) for c in accent)
            pygame.draw.line(surface, dim, (cx - 120, cy - 22), (cx + 120, cy - 22), 1)

        # Animated dots — each pulses at 1/3 cycle offset
        ticks  = pygame.time.get_ticks()
        dot_y  = cy + (8 if self._game_label else 0)
        for i in range(3):
            phase  = ((ticks / 1800) - i / 3) % 1.0
            bright = max(0.12, (math.cos(phase * 2 * math.pi) + 1) / 2)
            r = int(TEXT4[0] + (accent[0] - TEXT4[0]) * bright)
            g = int(TEXT4[1] + (accent[1] - TEXT4[1]) * bright)
            b = int(TEXT4[2] + (accent[2] - TEXT4[2]) * bright)
            pygame.draw.circle(surface, (r, g, b), (cx + (i - 1) * 26, dot_y), 5)

        # Status label
        offset = 52 if self._game_label else 44
        lbl = fonts['label'].render("Waiting for telemetry data", True, TEXT3)
        surface.blit(lbl, lbl.get_rect(center=(cx, dot_y + offset)))

        # Game-specific hint
        _HINTS = {
            "F1 2025":          "Settings  →  Telemetry Settings  →  UDP Telemetry  On",
            "Project CARS 2":   "Options  →  Visual  →  UDP Telemetry  On",
            "Forza Horizon":    "Settings  →  HUD and Gameplay  →  Data Out  On",
            "Forza Motorsport": "Settings  →  Gameplay and HUD  →  Data Out  On",
        }
        next_y = dot_y + offset + 34
        hint = _HINTS.get(self._game_label, "")
        if hint:
            hint_surf = fonts['hint'].render(hint, True, TEXT4)
            surface.blit(hint_surf, hint_surf.get_rect(center=(cx, next_y)))
            next_y += 22

        # Expected telemetry format the game must be set to output (e.g. F1's UDP
        # Format year) — so a mismatched/unsupported format is diagnosable.
        from core.telemetry_formats import TELEMETRY_INFO
        _info = TELEMETRY_INFO.get(self._game_id)
        if _info:
            fmt_surf = fonts['hint'].render(_info['format'], True, TEXT3)
            surface.blit(fmt_surf, fmt_surf.get_rect(center=(cx, next_y)))
            next_y += 22

        # Device IP / listening port — the address to enter in the game's
        # telemetry/Data Out settings.
        if self._telemetry_port is not None:
            if self._local_ip is None:
                from core.network import get_local_ip
                self._local_ip = get_local_ip()
            addr_surf = fonts['hint'].render(
                f"Listening on {self._local_ip} : {self._telemetry_port}", True, TEXT3,
            )
            surface.blit(addr_surf, addr_surf.get_rect(center=(cx, next_y)))

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._current_dashboard:
            self._current_dashboard.handle_event(event)

        # Swipe detection for manual cycle
        if event.type == pygame.MOUSEBUTTONDOWN:
            self._touch_down_x = event.pos[0]
        elif event.type == pygame.MOUSEBUTTONUP and self._touch_down_x is not None:
            dx = event.pos[0] - self._touch_down_x
            self._touch_down_x = None
            if abs(dx) >= _SWIPE_THRESHOLD:
                direction = 1 if dx > 0 else -1
                self._cycle(direction)

    def reset_touch(self) -> None:
        """Clear in-progress swipe tracking (e.g. after a settings overlay closes)."""
        self._touch_down_x = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auto_switch(self, data: TelemetryData) -> None:
        if data.car_class == self._current_car_class and data.session_type == self._current_session_type:
            return
        # Car or session changed — start a fresh session and drop any manual override.
        self._manual_override = False
        self._session.reset()

        path = _resolve_config(data.car_class, data.session_type)
        if path is None:
            return  # No config yet — keep existing dashboard

        if path == self._current_path:
            # Same file — just update tracking vars
            self._current_car_class = data.car_class
            self._current_session_type = data.session_type
            return

        self._current_car_class = data.car_class
        self._current_session_type = data.session_type
        self._cycle_paths = _configs_for_class(data.car_class)
        self._cycle_index = self._cycle_paths.index(path) if path in self._cycle_paths else 0
        self._load_path(path)

    def _cycle(self, direction: int) -> None:
        if not self._cycle_paths:
            return
        self._manual_override = True
        self._cycle_index = (self._cycle_index + direction) % len(self._cycle_paths)
        self._load_path(self._cycle_paths[self._cycle_index])

    def _load_path(self, path: str) -> None:
        try:
            dashboard = self._instantiate(path)
            dashboard.set_session(self._session)
            self._current_dashboard = dashboard
            self._current_path = path
            self._load_error = None
            log.info(f"Dashboard loaded: {os.path.basename(path)}")
        except Exception as e:
            log.error(f"Failed to load dashboard {path!r}: {e}")
            self._load_error = f"Dashboard config error — {e}"
            if self._current_dashboard is None:
                self._current_dashboard = TextDashboard(self._width, self._height)

    def _instantiate(self, path: str):
        """Return a Dashboard instance for the given config path.

        If the JSON contains a ``python_class`` key the named class is imported
        and instantiated directly (bypassing the widget config system).
        Otherwise a standard ConfigDashboard is returned.
        """
        import json
        import importlib

        with open(path) as f:
            cfg = json.load(f)

        python_class = cfg.get('python_class')
        if python_class:
            module_name, class_name = python_class.rsplit('.', 1)
            mod = importlib.import_module(module_name)
            cls = getattr(mod, class_name)
            return cls(self._width, self._height)

        return ConfigDashboard(path, self._width, self._height)
