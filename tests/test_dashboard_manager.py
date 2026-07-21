"""Race-end results banner state — warns until the final classification
packet (sent only at the official results screen) has been received."""
import pygame
import pytest

from core.dashboard_manager import DashboardManager, _results_state
from core.telemetry_model import TelemetryData


@pytest.mark.parametrize("session_type, finish_status, classified, expected", [
    ("race",       "",         False, None),        # still racing
    ("race",       "finished", False, "pending"),   # crossed the line, packet not yet in
    ("race",       "finished", True,  "saved"),
    ("race",       "dnf",      False, "pending"),   # DNF results also come with the packet
    ("race",       "retired",  True,  "saved"),
    ("qualifying", "finished", False, None),        # races only
    ("hotlap",     "",         False, None),
])
def test_results_state(session_type, finish_status, classified, expected):
    data = TelemetryData(session_type=session_type, finish_status=finish_status,
                         classification_received=classified)
    assert _results_state(data) == expected


@pytest.fixture(autouse=True)
def _pygame():
    pygame.init()
    yield
    pygame.quit()


def test_results_banner_renders():
    surface = pygame.Surface((800, 480))
    before = surface.copy()
    mgr = DashboardManager(800, 480)

    mgr.update(TelemetryData(session_type="race", finish_status="finished"))
    assert mgr._results_state == "pending"
    mgr._render_results_banner(surface)   # must not raise, must draw something
    assert surface.get_at((400, 5)) != before.get_at((400, 5))

    mgr.update(TelemetryData(session_type="race", finish_status="finished",
                             classification_received=True))
    assert mgr._results_state == "saved"
    mgr._render_results_banner(surface)

    # Back on track (race restart) — banner gone
    mgr.update(TelemetryData(session_type="race", finish_status=""))
    assert mgr._results_state is None
