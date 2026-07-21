"""Dashboard colour theme presets — panel/background palette variants.

Each preset carries the *full* surface + text set (BG…TEXT4) so switching
themes always fully overwrites the previous one — critical for the light
theme, whose primary TEXT is dark: without every dark preset also declaring
TEXT, switching light → dark would leave the text unreadable. Accent colours
(AMBER/GREEN/CYAN/…) live on a separate axis in accents.py and are not touched
here."""

# Primary text shared by every dark preset (near-white); the light preset
# overrides it to near-black.
_DARK_TEXT = (243, 245, 248)

THEMES = {
    "charcoal": {
        "name":    "Charcoal",
        "BG":      (12,  13,  16),
        "BG2":     (16,  18,  22),
        "PANEL":   (22,  25,  31),
        "PANEL2":  (28,  32,  39),
        "PANEL3":  (35,  39,  47),
        "INSET":   (10,  11,  14),
        "BORDER":  (37,  40,  46),
        "BORDER2": (50,  54,  62),
        "TEXT":    _DARK_TEXT,
        "TEXT2":   (174, 180, 190),
        "TEXT3":   (118, 124, 135),
        "TEXT4":   ( 77,  82,  92),
    },
    "obsidian": {
        "name":    "Obsidian",
        "BG":      (14,  10,  10),
        "BG2":     (19,  14,  14),
        "PANEL":   (26,  19,  19),
        "PANEL2":  (33,  24,  24),
        "PANEL3":  (41,  30,  30),
        "INSET":   (11,   8,   8),
        "BORDER":  (50,  37,  37),
        "BORDER2": (64,  48,  48),
        "TEXT":    _DARK_TEXT,
        "TEXT2":   (174, 180, 190),
        "TEXT3":   (118, 124, 135),
        "TEXT4":   ( 77,  82,  92),
    },
    "navy": {
        "name":    "Navy",
        "BG":      ( 8,  11,  20),
        "BG2":     (12,  16,  28),
        "PANEL":   (18,  24,  40),
        "PANEL2":  (24,  30,  50),
        "PANEL3":  (30,  38,  60),
        "INSET":   ( 6,   9,  17),
        "BORDER":  (36,  46,  72),
        "BORDER2": (48,  60,  90),
        "TEXT":    _DARK_TEXT,
        "TEXT2":   (174, 180, 190),
        "TEXT3":   (118, 124, 135),
        "TEXT4":   ( 77,  82,  92),
    },
    "slate": {
        "name":    "Slate",
        "BG":      (20,  22,  26),
        "BG2":     (26,  28,  33),
        "PANEL":   (34,  37,  44),
        "PANEL2":  (42,  46,  54),
        "PANEL3":  (51,  55,  65),
        "INSET":   (16,  18,  22),
        "BORDER":  (60,  65,  75),
        "BORDER2": (78,  83,  95),
        "TEXT":    _DARK_TEXT,
        "TEXT2":   (174, 180, 190),
        "TEXT3":   (118, 124, 135),
        "TEXT4":   ( 77,  82,  92),
    },
    "high_contrast": {
        "name":    "High Contrast",
        "BG":      ( 4,   4,   6),
        "BG2":     ( 8,   8,  11),
        "PANEL":   (42,  46,  54),
        "PANEL2":  (58,  63,  74),
        "PANEL3":  (74,  80,  94),
        "INSET":   ( 2,   2,   3),
        "BORDER":  (100, 106, 120),
        "BORDER2": (140, 146, 162),
        "TEXT":    (255, 255, 255),
        "TEXT2":   (220, 224, 230),
        "TEXT3":   (185, 190, 198),
        "TEXT4":   (140, 145, 155),
    },
    "light": {
        "name":    "Light",
        "BG":      (236, 238, 242),   # page fill — light grey, not glare-white
        "BG2":     (228, 231, 236),
        "PANEL":   (255, 255, 255),   # cards
        "PANEL2":  (243, 245, 248),   # secondary cells, tiles
        "PANEL3":  (234, 237, 241),   # innermost inset
        "INSET":   (216, 220, 227),   # dark-enough bar trough to read fills
        "BORDER":  (205, 210, 218),
        "BORDER2": (181, 188, 199),
        "TEXT":    ( 22,  25,  31),   # near-black primary value text
        "TEXT2":   ( 72,  79,  90),
        "TEXT3":   (108, 116, 128),
        "TEXT4":   (150, 157, 168),
    },
}

THEME_ORDER   = ["charcoal", "obsidian", "navy", "slate", "high_contrast", "light"]
DEFAULT_THEME = "charcoal"


def apply_theme(theme_id: str) -> None:
    """Mutate design_system module attributes in-place.

    All widgets read DS.ATTR at render time, so every widget reflects the
    change on the next frame with no restarts or reloads required. Every
    preset declares the full surface+text set, so this fully overwrites the
    previous theme (no stale attributes survive a switch).
    """
    from dashboard.widgets import design_system as DS
    preset = THEMES.get(theme_id, THEMES[DEFAULT_THEME])
    for attr, value in preset.items():
        if attr != "name" and hasattr(DS, attr):
            setattr(DS, attr, value)
