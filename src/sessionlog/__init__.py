"""
Shfonic Dash — shared session-log library.

Everything that understands session CSVs (the typed-row format specified in
docs/session-log-format.md) and turns them into analysis: parsing, lap-flag
computation, pace facts, Race Engineer Notes, grading and the records index.
Shared between the Pi dashboard (this repo — the canonical home) and the
Pythonista companion app, which receives a vendored copy via sync_shared.py.

Rules for this package:
  - Pure standard library only — no pygame, no Pythonista modules.
  - Python 3.10 floor (Pythonista 3.4); the Pi runs newer but the shared
    code must not use 3.11+ syntax.
  - Edit only in ShfonicDash/src/sessionlog/. The companion's copy
    is overwritten by sync_shared.py and guarded by a manifest drift test.

Modules:
  parser   — CSV -> session dict, scan_session(), lap/sector flags,
             display-name lookups
  pace     — pace_facts() / race_engineer_notes(): the Race Engineer Notes engine
  grading  — Execution / Cleanliness / Overall grades, pace rating,
             trend, driver profile (per-combo pace), milestones
  career   — recent_form(): the driver's overall recent-form grade across
             every game (the driver-card headline), with a per-game
             breakdown and an improving/declining trend
  goals    — pre_session_goal(): data-backed "NEXT GOAL" + missions
             shown before a session starts
  debrief  — post-session driver debrief: adaptive question selection
             (select_questions), answer labels and share-text lines
             for the D rows appended to session CSVs
  journal  — journal_entry(): the session's story — the biggest thing
             that happened drives the entry (PB / race / tough /
             consistency), debrief answers woven in, never a grade
  records  — SQLite index over a directory of session CSVs
             (overall_best / prior_best / combo_history)
  achievements — career-wide badges computed from the archive:
             evaluate() for the trophy gallery, session_awards() for
             "what did this session earn" (banner / journal)
  trackmap — find_map() / describe_location(): places a lap-distance
             against a track JSON's labelled `sections` ('at Turn 3,
             before the apex') for Race Engineer Notes and the share text;
             crop_geometry() returns the edge-slice + marker + bounds a
             renderer needs for a zoomed corner thumbnail
  lines    — racing-line adherence: turns the per-lap offset profiles
             (P rows) into corner adherence, the on_the_line achievement's
             session facts, off-line Race Engineer Notes and the
             player-vs-racing mini-map geometry
  circuits — circuit reference data keyed by the bare telemetry track name:
             display_name() (real circuit name) and location()
             ('Melbourne, Australia') for "where we raced"; also the source
             of parser.F1_TRACK_LENGTHS_M. F1 only for now
"""

# Bumped on every change to any module in this package; the companion's
# drift test compares it against the vendored manifest.
SESSIONLOG_VERSION = '1.28.0'
