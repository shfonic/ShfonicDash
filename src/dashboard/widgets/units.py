"""Unit system — controls the display units for speed, tyre temperature,
and tyre pressure.

Separate axis from themes.py / accents.py: those mutate design_system colours,
this exposes conversion + label functions that widgets call at draw time so
the displayed numbers update live when the setting changes.
"""

UNIT_SYSTEMS = {
    "metric": {
        "name":     "Metric",
        "speed":    "km/h",
        "temp":     "°C",
        "pressure": "bar",
    },
    "imperial": {
        "name":     "Imperial",
        "speed":    "mph",
        "temp":     "°F",
        "pressure": "psi",
    },
}

UNIT_ORDER    = ["metric", "imperial"]
DEFAULT_UNITS = "metric"

_current = DEFAULT_UNITS


def set_unit_system(mode: str) -> None:
    global _current
    _current = mode if mode in UNIT_SYSTEMS else DEFAULT_UNITS


def get_unit_system() -> str:
    return _current


def speed_label() -> str:
    return UNIT_SYSTEMS[_current]["speed"]


def convert_speed(kmh: float) -> float:
    return kmh if _current == "metric" else kmh * 0.621371


def temp_label() -> str:
    return UNIT_SYSTEMS[_current]["temp"]


def convert_temp(celsius: float) -> float:
    return celsius if _current == "metric" else celsius * 9 / 5 + 32


def pressure_label() -> str:
    return UNIT_SYSTEMS[_current]["pressure"]


def convert_pressure(psi: float) -> float:
    """TelemetryData.tyre_pressure is always PSI — convert to bar for metric."""
    return psi * 0.0689476 if _current == "metric" else psi
