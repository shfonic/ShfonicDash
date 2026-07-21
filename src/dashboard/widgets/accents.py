"""Accent colour modes — functional colours used to convey meaning
(shift lights, flags, sector times, DRS/ERS chips, tyre temps).

Separate axis from themes.py: themes only adjust panel/background colours,
these adjust the meaning-bearing accents.
"""

ACCENT_MODES = {
    "standard": {
        "name":    "Standard",
        "RED":     (255,  59,  48),
        "GREEN":   ( 47, 224, 122),
        "AMBER":   (255, 179,   0),
        "BLUE":    ( 46, 155, 255),
        "PURPLE":  (122, 108, 255),
        "CYAN":    ( 51, 225, 237),
        "MAGENTA": (255,  69, 200),
    },
    "colourblind": {
        "name":    "Colour-blind safe",
        "RED":     (240, 100,  20),   # vermillion — was pure red
        "GREEN":   (  0, 191, 165),   # teal / bluish-green — was lime-green
        "AMBER":   (255, 214,   0),   # bright yellow
        "BLUE":    ( 64, 156, 255),
        "PURPLE":  (180, 140, 255),
        "CYAN":    ( 90, 220, 255),
        "MAGENTA": (255, 130, 210),
    },
}

ACCENT_ORDER   = ["standard", "colourblind"]
DEFAULT_ACCENT = "standard"


def apply_accent_mode(mode_id: str) -> None:
    """Mutate design_system module attributes in-place.

    Mirrors themes.apply_theme(). Also recomputes the CHIP_* tuples, which
    pair each accent colour with a contrasting text colour for chip/badge fills.
    """
    from dashboard.widgets import design_system as DS
    preset = ACCENT_MODES.get(mode_id, ACCENT_MODES[DEFAULT_ACCENT])
    for attr, value in preset.items():
        if attr != "name" and hasattr(DS, attr):
            setattr(DS, attr, value)

    DS.CHIP_GREEN = (DS.GREEN, DS._lerp(DS.GREEN, (0, 0, 0), 0.92))
    DS.CHIP_AMBER = (DS.AMBER, DS._lerp(DS.AMBER, (0, 0, 0), 0.92))
    DS.CHIP_BLUE  = (DS.BLUE,  DS._lerp(DS.BLUE,  (0, 0, 0), 0.92))
    DS.CHIP_RED   = (DS.RED,   (255, 255, 255))
