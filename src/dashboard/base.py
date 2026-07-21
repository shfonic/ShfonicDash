# dashboard/base.py
from abc import ABC, abstractmethod
from core.telemetry_model import TelemetryData

class Dashboard(ABC):

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height


    @abstractmethod
    def update(self, data: TelemetryData) -> None:
        pass

    @abstractmethod
    def render(self, surface) -> None:
        pass

    @abstractmethod
    def handle_event(self, event) -> None:
        pass

    def set_session(self, session) -> None:
        """Forward the shared SessionHistory to any widgets that opt in."""
