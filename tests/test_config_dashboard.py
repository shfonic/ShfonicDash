import json

import pygame
import pytest

from dashboard.config_dashboard import ConfigDashboard


@pytest.fixture(autouse=True)
def _pygame():
    pygame.init()
    yield
    pygame.quit()


def _write_cfg(tmp_path, widgets):
    path = tmp_path / "test_dash.json"
    path.write_text(json.dumps({"name": "Test", "widgets": widgets}))
    return str(path)


def test_valid_config_loads(tmp_path):
    path = _write_cfg(tmp_path, [
        {"type": "SpeedWidget", "x": 0, "y": 0, "width": 200, "height": 100, "unit": "mph"},
    ])
    dash = ConfigDashboard(path, 800, 480)
    assert len(dash._widgets) == 1


def test_unknown_widget_type_names_file_and_lists_available(tmp_path):
    path = _write_cfg(tmp_path, [
        {"type": "NopeWidget", "x": 0, "y": 0, "width": 10, "height": 10},
    ])
    with pytest.raises(ValueError) as exc:
        ConfigDashboard(path, 800, 480)
    msg = str(exc.value)
    assert "test_dash.json" in msg
    assert "NopeWidget" in msg
    assert "SpeedWidget" in msg   # available types listed


def test_typoed_widget_option_is_named(tmp_path):
    path = _write_cfg(tmp_path, [
        {"type": "SpeedWidget", "x": 0, "y": 0, "width": 200, "height": 100, "unti": "mph"},
    ])
    with pytest.raises(ValueError) as exc:
        ConfigDashboard(path, 800, 480)
    msg = str(exc.value)
    assert "test_dash.json" in msg
    assert "unti" in msg    # the typo'd key is called out
    assert "unit" in msg    # accepted options listed
