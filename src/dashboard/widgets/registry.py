"""
Widget registry — maps JSON ``"type"`` strings to widget classes.

To add a new widget, import it here and add an entry to ``REGISTRY``.
"""

from .gear         import GearWidget
from .speed        import SpeedWidget
from .rpm_gauge    import RPMGaugeWidget
from .pedals       import PedalsWidget
from .shift_lights import ShiftLightsWidget
from .lap_info     import LapInfoWidget
from .tyres        import TyreWidget
from .fuel         import FuelWidget
from .ers          import ERSWidget
from .drs          import DRSWidget
from .sectors      import SectorTimesWidget
from .lap_list     import LapListWidget
from .position     import PositionWidget
from .lap_counter  import LapCounterWidget
from .gap          import GapWidget
from .flag         import FlagWidget
from .proximity          import ProximityWidget
from .spotter            import SpotterWidget
from .aero               import AeroWidget
from .qualifying_table   import QualifyingTableWidget

REGISTRY: dict[str, type] = {
    'GearWidget':        GearWidget,
    'SpeedWidget':       SpeedWidget,
    'RPMGaugeWidget':    RPMGaugeWidget,
    'PedalsWidget':      PedalsWidget,
    'ShiftLightsWidget': ShiftLightsWidget,
    'LapInfoWidget':     LapInfoWidget,
    'TyreWidget':        TyreWidget,
    'FuelWidget':        FuelWidget,
    'ERSWidget':         ERSWidget,
    'DRSWidget':         DRSWidget,
    'SectorTimesWidget': SectorTimesWidget,
    'LapListWidget':     LapListWidget,
    'PositionWidget':    PositionWidget,
    'LapCounterWidget':  LapCounterWidget,
    'GapWidget':         GapWidget,
    'FlagWidget':        FlagWidget,
    'ProximityWidget':        ProximityWidget,
    'SpotterWidget':          SpotterWidget,
    'AeroWidget':             AeroWidget,
    'QualifyingTableWidget':  QualifyingTableWidget,
}
