"""Font-loading helpers shared by all widgets."""
import os
import pygame

_FONTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'fonts')

# Cache loaded fonts so the same file isn't opened repeatedly
_cache: dict[tuple, pygame.font.Font] = {}


def clear_cache() -> None:
    """Drop all cached fonts.

    Cached Font objects die with pygame.quit() — using one after a
    re-init crashes the interpreter. The app never re-inits pygame, but
    tests that cycle init()/quit() must call this after re-initialising.
    """
    _cache.clear()

# ── Saira Semi Condensed — main numeric readouts (gear, speed, RPM, lap times)
_DISPLAY_FILES = [
    'SairaSemiCondensed-Bold.ttf',
    'SairaSemiCondensed-SemiBold.ttf',
]
_DISPLAY_SYSTEM = ['impact', 'arial narrow', 'helvetica neue', 'roboto condensed']

# ── Saira — labels, chips, secondary text
_UI_FILES = [
    'Saira-Variable.ttf',
    'SairaSemiCondensed-SemiBold.ttf',
]
_UI_SYSTEM = ['helvetica neue', 'arial', 'roboto', 'ubuntu', 'sans-serif']

# ── DSEG — legacy 7-segment style (kept for fallback / retro widgets)
_DIGITAL_FILES = ['DSEG14Classic-Regular.ttf', 'DSEG7Classic-Bold.ttf']
_DIGITAL_SYSTEM = ['ds-digital', 'digital-7', 'courier new']


def _load_from_list(files: list, system_names: list, size: int,
                    bold: bool = False) -> pygame.font.Font:
    for fname in files:
        path = os.path.join(_FONTS_DIR, fname)
        if os.path.isfile(path):
            try:
                return pygame.font.Font(path, size)
            except Exception:
                pass
    for name in system_names:
        match = pygame.font.match_font(name, bold=bold)
        if match:
            try:
                return pygame.font.Font(match, size)
            except Exception:
                pass
    return pygame.font.SysFont(None, size, bold=bold)


def load_display(size: int) -> pygame.font.Font:
    """Saira Semi Condensed Bold — large numeric readouts."""
    key = ('display', size)
    if key not in _cache:
        _cache[key] = _load_from_list(_DISPLAY_FILES, _DISPLAY_SYSTEM, size, bold=True)
    return _cache[key]


def load_ui(size: int) -> pygame.font.Font:
    """Saira — labels, chips, secondary text."""
    key = ('ui', size)
    if key not in _cache:
        _cache[key] = _load_from_list(_UI_FILES, _UI_SYSTEM, size)
    return _cache[key]


def load_digital(size: int) -> pygame.font.Font:
    """DSEG 7-segment style — kept for legacy/retro widgets."""
    key = ('digital', size)
    if key not in _cache:
        _cache[key] = _load_from_list(_DIGITAL_FILES, _DIGITAL_SYSTEM, size)
    return _cache[key]


def load_system(size: int) -> pygame.font.Font:
    """Plain system font — use load_ui() for new widgets."""
    key = ('system', size)
    if key not in _cache:
        _cache[key] = pygame.font.SysFont(None, size)
    return _cache[key]
