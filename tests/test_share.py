"""Tests for sessionlog.share — the canonical AI coaching brief.

Shared with the companion via sync_shared.py: format_for_ai() is the single
source of the share text both apps produce. Sessions are built inline via
parse() (no fixture file) so the test is portable across both repos.
"""
from sessionlog import share
from sessionlog.parser import parse

LAP_HEADER = ('H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,'
              'tyre_compound,fuel_remaining,fuel_per_lap,position,delta,invalid,rewinds')


def _session():
    rows = ['S,version,1', 'S,started_at,2026-07-17T19:11:00',
            'S,game,f1_25', 'S,session_type,qualifying',
            'S,car_class,formula1_2026', 'S,driver_name,PIASTRI',
            'S,track,Silverstone', LAP_HEADER,
            'L,1,91.853,28.5,29.6,33.753,,,,,,,,,,0,0',
            'L,2,90.512,28.1,29.2,33.212,,,,,,,,,,0,0']
    return parse('\n'.join(rows) + '\n', 'session_20260717_1911_qualifying.csv')


def test_brief_has_coach_framing_and_core_sections():
    txt = share.format_for_ai(_session())
    assert txt
    assert "sim-racing coach" in txt          # role preamble
    assert "SIM RACING SESSION" in txt         # header
    assert "PACE ANALYSIS" in txt              # pace section
    assert "AI ANALYSIS GUIDANCE" in txt       # analysing-model guidance


def test_profile_preamble_addresses_the_driver():
    txt = share.format_for_ai(
        _session(), profile={"name": "Alex", "experience_label": "Experienced"})
    assert "Alex" in txt
    assert "Experienced" in txt


def test_no_profile_omits_the_name_line():
    txt = share.format_for_ai(_session(), profile=None)
    assert "SIM RACING SESSION" in txt
    assert "The driver's name is" not in txt


def test_journal_entry_is_included_when_given():
    txt = share.format_for_ai(
        _session(), journal_entry={"icon": "🏁", "text": "A tidy qualifying run."})
    assert "JOURNAL" in txt
    assert "A tidy qualifying run." in txt


def test_real_track_name_used():
    # circuits.display_name turns the F1 short name into the real circuit name.
    txt = share.format_for_ai(_session())
    assert "Silverstone Circuit" in txt


def test_pure_stdlib_no_toolkit_imports():
    import sessionlog.share as s
    src = open(s.__file__, encoding="utf-8").read()
    assert "import pygame" not in src
    assert "import ui" not in src
