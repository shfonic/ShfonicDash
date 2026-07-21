"""Tests for sessionlog.profile — the canonical driver-identity vocabulary."""
from sessionlog import profile


def test_lists_present_and_shaped():
    assert profile.EXPERIENCE_LEVELS and profile.DISCIPLINES and profile.GOALS
    # (value, label, ...) — value first, label second.
    for v, lbl, *_ in profile.EXPERIENCE_LEVELS:
        assert v and lbl


def test_label_helpers():
    assert profile.experience_label("experienced") == "Experienced"
    assert profile.discipline_label("gt") == "GT"
    assert profile.goal_label("pace") == "Outright pace"     # not title-cased
    assert profile.goal_label("nope") == ""


def test_options_view_drops_descriptions():
    opts = profile.options("experience")
    assert ("beginner", "Beginner") in opts
    assert all(len(o) == 2 for o in opts)
    assert profile.options("unknown") == []


def test_label_by_field():
    assert profile.label("goal", "consistency") == "Consistency"
    assert profile.label("discipline", "road") == "Road / Street"
