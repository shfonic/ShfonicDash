"""Tests for sessionlog.circuits — circuit reference data."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sessionlog import circuits, parser


def test_circuit_returns_all_fields():
    info = circuits.circuit("f1_25", "Melbourne")
    assert info == {
        "full_name": "Albert Park Circuit",
        "city": "Melbourne",
        "country": "Australia",
        "country_code": "AU",
        "length_m": 5278,
    }


def test_display_name_falls_back_to_raw_track():
    # Unknown track: never blank, always the bare name.
    assert circuits.display_name("f1_25", "Nürburgring") == "Nürburgring"
    assert circuits.display_name("f1_25", "Melbourne") == "Albert Park Circuit"


def test_display_name_safe_when_missing():
    assert circuits.display_name("f1_25", None) == ""
    assert circuits.display_name(None, None) == ""
    assert circuits.display_name("pcars2", "Spa") == "Spa"  # game has no table


def test_location_formats_city_country():
    assert circuits.location("f1_25", "Melbourne") == "Melbourne, Australia"
    assert circuits.location("f1_25", "Monaco") == "Monte Carlo, Monaco"


def test_location_collapses_city_equal_country():
    assert circuits.location("f1_25", "Singapore") == "Singapore"


def test_location_none_when_unknown():
    assert circuits.location("f1_25", "Nürburgring") is None
    assert circuits.location("pcars2", "Spa") is None


def test_length_helper_matches_table():
    assert circuits.length_m("f1_25", "Spa") == 7004
    assert circuits.length_m("f1_25", "Nürburgring") is None


def test_alternate_layouts_named_distinctly():
    assert circuits.display_name("f1_25", "Silverstone Reverse") \
        == "Silverstone Circuit (Reverse)"
    # A layout whose length isn't confirmed carries None (not counted).
    assert circuits.length_m("f1_25", "Suzuka Short") is None


def test_parser_length_table_derived_from_circuits():
    # F1_TRACK_LENGTHS_M is the confirmed-length subset of the circuit table.
    for name, length in parser.F1_TRACK_LENGTHS_M.items():
        assert length is not None
        assert circuits.length_m("f1_25", name) == length
    # Every circuit with a confirmed length appears in the derived table.
    for name, info in circuits._F1_CIRCUITS.items():
        if info[-1] is not None:
            assert parser.F1_TRACK_LENGTHS_M[name] == info[-1]


def test_track_ids_all_have_circuit_entries():
    # Every name the F1 source can emit should resolve, so the display never
    # falls back to a bare word for a track the game actually ships. Skipped
    # in the companion's shared-test run, which has no telemetry package.
    try:
        from telemetry.f1_2025 import _TRACK_ID_MAP
    except ImportError:
        import pytest
        pytest.skip("telemetry package not present (companion run)")
    for name in _TRACK_ID_MAP.values():
        assert circuits.circuit("f1_25", name) is not None, name
