from abc import ABC, abstractmethod
from core.telemetry_model import TelemetryData

class TelemetrySource(ABC):

    @abstractmethod
    def connect(self) -> None:
        pass

    @abstractmethod
    def read(self) -> TelemetryData:
        """Return latest telemetry snapshot"""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @property
    def port(self) -> int | None:
        """UDP port this source listens on; None for non-network sources."""
        return getattr(self, "_port", None)
