import pytest

from dashboard.widgets import units


@pytest.fixture(autouse=True)
def reset_units():
    """Each test starts from the default unit system and restores it after."""
    units.set_unit_system(units.DEFAULT_UNITS)
    yield
    units.set_unit_system(units.DEFAULT_UNITS)


def test_default_unit_system_is_metric():
    assert units.get_unit_system() == "metric"
    assert units.speed_label() == "km/h"
    assert units.temp_label() == "°C"
    assert units.pressure_label() == "bar"


def test_metric_conversions_are_passthrough_except_pressure():
    assert units.convert_speed(100.0) == 100.0
    assert units.convert_temp(20.0) == 20.0
    # tyre_pressure is stored as PSI; metric converts to bar
    assert units.convert_pressure(29.0) == pytest.approx(29.0 * 0.0689476)


def test_set_unit_system_to_imperial():
    units.set_unit_system("imperial")

    assert units.get_unit_system() == "imperial"
    assert units.speed_label() == "mph"
    assert units.temp_label() == "°F"
    assert units.pressure_label() == "psi"


def test_imperial_conversions():
    units.set_unit_system("imperial")

    assert units.convert_speed(100.0) == pytest.approx(62.1371)
    assert units.convert_temp(0.0) == pytest.approx(32.0)
    assert units.convert_temp(100.0) == pytest.approx(212.0)
    # tyre_pressure is already PSI; imperial passes it through unchanged
    assert units.convert_pressure(29.0) == 29.0


def test_set_unit_system_with_invalid_value_falls_back_to_default():
    units.set_unit_system("imperial")
    units.set_unit_system("not-a-real-unit-system")

    assert units.get_unit_system() == units.DEFAULT_UNITS
