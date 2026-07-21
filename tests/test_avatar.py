"""Tests for sessionlog.avatar — shared driver-avatar data + helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sessionlog import avatar


def test_normalise_kind_valid_and_default():
    assert avatar.normalise_kind("helmet") == "helmet"
    assert avatar.normalise_kind("initials") == "initials"
    assert avatar.normalise_kind("emoji") == avatar.DEFAULT_KIND   # legacy
    assert avatar.normalise_kind(None) == avatar.DEFAULT_KIND
    assert avatar.normalise_kind("") == avatar.DEFAULT_KIND


def test_initials():
    assert avatar.initials("Richard Hawes") == "RH"
    assert avatar.initials("Ayrton") == "AY"
    assert avatar.initials("  max  verstappen ") == "MV"
    assert avatar.initials("") == ""
    assert avatar.initials(None) == ""


def test_colour_rgb_known_and_fallback():
    assert avatar.colour_rgb("green") == (0.16, 0.62, 0.24)
    # Unknown key falls back to the named fallback colour.
    assert avatar.colour_rgb("chartreuse") == avatar.colour_rgb("red")
    assert avatar.colour_rgb("nope", fallback="blue") == avatar.colour_rgb("blue")


def test_normalise_helmet_fills_defaults():
    assert avatar.normalise_helmet(None) == avatar.DEFAULT_HELMET
    assert avatar.normalise_helmet({}) == avatar.DEFAULT_HELMET
    merged = avatar.normalise_helmet({"base": "green", "pattern": "twin"})
    assert merged["base"] == "green"
    assert merged["pattern"] == "twin"
    # Untouched keys keep their defaults.
    assert merged["visor"] == avatar.DEFAULT_HELMET["visor"]
    assert merged["accent"] == avatar.DEFAULT_HELMET["accent"]


def test_helmet_keys_and_palette_are_consistent():
    # Every DEFAULT_HELMET colour key exists in the palette.
    keys = {k for k, _label, _rgb in avatar.COLOURS}
    for slot in ("base", "visor", "accent"):
        assert avatar.DEFAULT_HELMET[slot] in keys
    assert avatar.DEFAULT_HELMET["pattern"] in {k for k, _l in avatar.PATTERNS}
    assert avatar.HELMET_LAYERS[0] == "helmet.png"
