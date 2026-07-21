"""
dashboard.widgets
=================
Self-contained telemetry display widgets.

Each widget follows the same minimal interface::

    widget = SomeWidget(x, y, width, height)
    widget.update(telemetry_data)   # call every frame (or when data changes)
    widget.draw(surface)            # call every render frame

All widgets share the dark racing-HUD colour palette defined in ``base.py``.

Available widgets
-----------------
- :class:`GearWidget`       — current gear (N, 1–6, R)
- :class:`SpeedWidget`      — vehicle speed with unit label
- :class:`RPMGaugeWidget`   — segmented arc + bar RPM gauge
- :class:`PedalsWidget`     — throttle / brake vertical bar pair
- :class:`ShiftLightsWidget`— shift-light LED row (green → yellow → red)
- :class:`LapInfoWidget`    — lap time, best lap, and delta in one bar
"""

from .gear         import GearWidget
from .speed        import SpeedWidget
from .rpm_gauge    import RPMGaugeWidget
from .pedals       import PedalsWidget
from .shift_lights import ShiftLightsWidget
from .lap_info     import LapInfoWidget
from .base         import Widget, PALETTE

__all__ = [
    'Widget',
    'PALETTE',
    'GearWidget',
    'SpeedWidget',
    'RPMGaugeWidget',
    'PedalsWidget',
    'ShiftLightsWidget',
    'LapInfoWidget',
]
