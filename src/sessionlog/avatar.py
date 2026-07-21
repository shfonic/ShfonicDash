"""
Driver avatar data (shared, UI-free).

The driver can represent themselves two ways (see ``avatar_kind``):
  • initials — their initials on an amber disc (the default / fallback),
  • helmet   — a racing helmet (bundled glyph) with independently chosen base
               (shell), visor and accent (stripe) colours and a pattern.

This module holds only the *data* (palette, patterns, defaults) and pure
helpers, so it is importable anywhere (no ``pygame``/``ui``). Each app renders
from it: the companion via ``ui_components.AvatarView`` (Pythonista ui), the Pi
via ``core.avatar_render`` (pygame). Both consume the same palette + layer
filenames so a profile renders identically on phone and Pi.

Canonical here (Pi repo); vendored into the companion by ``sync_shared.py``.
The helmet is drawn from three PNG layers that live alongside each app's images
(``helmet.png`` shell mask, ``helmet_visor.png`` visor-glass mask,
``helmet_trim.png`` fixed white edge + vent).
"""

VALID_KINDS = ('initials', 'helmet')
DEFAULT_KIND = 'initials'

# Helmet PNG layer filenames (shared contract; each app resolves its own dir).
HELMET_LAYERS = ('helmet.png', 'helmet_visor.png', 'helmet_trim.png')


def normalise_kind(kind):
    """A valid avatar kind, defaulting unknown/legacy values (e.g. 'emoji')."""
    return kind if kind in VALID_KINDS else DEFAULT_KIND


# Colour palette — (key, label, rgb 0–1). Keys are what get stored in the
# profile; the rgb is resolved at render time so the stored value never depends
# on a live theme. rgb is 0–1 floats; pygame renderers scale to 0–255.
COLOURS = [
    ('red',    'Red',    (0.85, 0.15, 0.15)),
    ('amber',  'Amber',  (0.96, 0.62, 0.10)),
    ('green',  'Green',  (0.16, 0.62, 0.24)),
    ('blue',   'Blue',   (0.16, 0.40, 0.86)),
    ('cyan',   'Cyan',   (0.12, 0.70, 0.80)),
    ('purple', 'Purple', (0.52, 0.22, 0.74)),
    ('white',  'White',  (0.92, 0.92, 0.94)),
    ('black',  'Black',  (0.14, 0.14, 0.16)),
]

PATTERNS = [
    ('solid',  'Solid'),
    ('stripe', 'Stripe'),
    ('halo',   'Halo'),
    ('twin',   'Twin'),
]

# base = shell colour · visor = visor colour · accent = pattern-stripe colour ·
# pattern = stripe style. The three colours are picked independently.
DEFAULT_HELMET = {'base': 'red', 'visor': 'blue', 'accent': 'white',
                  'pattern': 'stripe'}

_COLOUR_RGB = {key: rgb for key, _label, rgb in COLOURS}


def colour_rgb(key, fallback='red'):
    """RGB (0–1) tuple for a colour key, falling back when the key is unknown."""
    return _COLOUR_RGB.get(key) or _COLOUR_RGB.get(fallback) or (0.85, 0.15, 0.15)


def initials(name):
    """Up to two initials from a declared name ('' when none is set)."""
    parts = [p for p in (name or '').split() if p]
    if not parts:
        return ''
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def normalise_helmet(helmet):
    """A complete helmet dict from a possibly-partial/absent stored value."""
    h = dict(DEFAULT_HELMET)
    if isinstance(helmet, dict):
        for k in ('base', 'visor', 'accent', 'pattern'):
            if helmet.get(k):
                h[k] = helmet[k]
    return h
