# Changelog

A curated highlights history of Shfonic Dash — a Pygame telemetry dashboard
for sim racing, built to run on a Raspberry Pi with a 7" touchscreen. Format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

The project was developed intensively as a solo sprint over June–July 2026
(prototype 2026-01-22, first public release 2026-07-21). The granular
per-release log below has been condensed into themed milestones; the full
history remains in git.

---

## [0.69.0] — Companion settings tab (2026-07-22)

Grouped all connectivity settings onto a dedicated **COMPANION** tab in Settings
— the web-companion mode plus its pairing URL / QR code lead, followed by the
Pythonista-app sync controls (share logs, share window). The top-left **SYNC**
pill on the game menu, which only matters to drivers running the iOS companion,
is now **hidden by default**; turn on *Show SYNC button* on the Companion tab to
bring it back. The Data tab slims down to session-data management (rebuild the
session index, toggle the track-recording button).

## [0.68.3] — Initial public release (2026-07-21)

The first public release. What Shfonic Dash does today:

**Live dashboards.** Passively listens for UDP telemetry broadcast by the game
and renders a live, game-specific 800×480 cockpit dashboard — gear, speed, RPM,
shift lights, pedals, tyres, fuel, lap/sector times, ERS/DRS, position, gaps,
flags and more. Layouts are pure JSON widget grids (no code needed for a new
one); fully custom Python dashboards are supported for special cases (e.g. the
DeLorean "Back to the Future" layout). A touch menu selects the game, and a
long-press exits back to it.

**Supported games:**
- **F1 25 / F1 2026** — full support (the flagship). Practice / qualifying /
  race / Time Trial auto-switching, live delta, sector timing, qualifying
  leaderboard, tyre compounds, team names and colours, weather, incident
  events, driver assists, and world-position (Motion) parsing that powers the
  track recorder and spotter radar. F1 2026 adds the AeroWidget / active-aero
  "S Mode" and boost.
- **Project CARS 2** — UDP port 5606; car-class detection from vehicle names,
  timing, sectors, fuel, tyres, weather.
- **Forza Horizon / Forza Motorsport** — passive listeners; car identification
  by ordinal via a ~1,100-car CSV, per-car dashboards, corrected redline
  calibration.
- **Gran Turismo 7 (beta)** — pure-stdlib Salsa20 decryption, console
  auto-discovery, no third-party crypto dependency. Built from community docs
  and verified against a simulated console only — unverified against real
  hardware, pending a community capture.

**Session logging, history & coaching.** Every driven session is logged to a
typed-row CSV (the records database). From it the shared `sessionlog` engine
produces: end-of-session summaries with letter grades and Race Engineer Notes,
a touch-scrollable history browser, pre-session "NEXT GOAL" cards, focus-driven
sessions with tracked/scored objectives, a post-session driver debrief, a
first-person driving journal, career achievements/trophies, and a driver
profile with recent-form grade and personal records. Grading, notes and figures
are re-derived from the CSVs so every renderer agrees.

**Web companion.** A mobile-browser mirror of the driver experience, served by
the Pi under `/app` over the LAN — no install. Driver hub, sessions with
drill-down, session detail (lap tables, charts, circuit minimaps, engineer
notes), trophies, journal, editable profile, a track-map editor, a zoomable
session line viewer, and an AI-coaching share brief. QR pairing with cookie
auth; a third renderer over the same `sessionlog` engine, so it matches the Pi.

**Track recorder & circuit maps.** A driver-controlled mode (F1 25/26) that
builds a reusable circuit map by driving it — track edges, per-class racing
lines, pit lane, and automatic start/finish + sector boundaries. Maps carry
labelled corner sections and drive racing-line coaching, incident placement and
minimaps everywhere.

**Utility.** Authenticated read/write LAN API (session + track-map sync), record
& replay of raw UDP sessions for offline debugging, rotating file logging, six
themes (incl. light and high-contrast) with a colour-blind-safe mode, and
metric/imperial units.

---

## Milestones

### Core telemetry & dashboards
- Complete rewrite (0.1.0) into a config-driven widget system: JSON dashboards,
  a multi-game touch menu, a settings overlay, and a design system (fonts,
  palette, chip/badge helpers). Grew from the original single-LCD prototype
  (0.0.1).
- Widget library covering shift lights, gear, speed, RPM, pedals, tyres, fuel,
  lap/sector info, lap list, position, lap counter, gaps, flags, DRS, ERS,
  proximity, active aero and a spotter radar.
- `TelemetryData` as the single per-frame contract between sources and
  dashboards; `SessionHistory` (0.1.80) as the accumulator that survives
  dashboard switches; a single shared `LapTracker` (0.1.118) as the one source
  of truth for lap-completion and rewind/flashback detection.
- Rebrand from "Sim Racing Telemetry" to **Shfonic Dash** (0.1.1), later a new
  brand logo and themed splash (0.51.0–0.53.0).
- Robustness: rotating file logging (0.1.121), crash tracebacks captured to
  file (0.1.125), on-screen config-error banners and widget-option validation
  (0.1.122), and clean UDP-thread shutdown/rebind (0.1.22, 0.1.130).
- Record & replay of raw UDP sessions (0.1.119) so real-session parser bugs are
  reproducible offline and captures double as regression fixtures.
- CI running pytest headlessly on the Mac and Pi Python versions (0.1.123).

### F1 25 / F1 2026 support
- Full EA/Codemasters packet parsing (2024/2025/2026 layouts): telemetry,
  lap data, sessions, participants, car status, events and final classification.
- Live delta engine (0.1.76 onward) — records a per-lap distance/time profile,
  saves the best lap as a reference and interpolates the gap live; hardened
  against pit stops, garage visits, pauses, flashbacks and cold starts through
  a long series of fixes, then extracted into a reusable `LapDeltaTracker`
  (0.1.120).
- Qualifying leaderboard with driver names, team colours and race numbers
  (0.1.78–0.1.85), across evolving F1 25 participant-packet variants.
- Session correctness: Time Trial mapping (0.1.10), Sprint Qualifying no longer
  logged as a race (0.1.133), pit teleports and flashbacks no longer counted as
  laps/rewinds, and per-session state cleanly reset between practice/qualifying.
- Team names resolved for the 2026 Season Pack and F1/F2 2024–2025 grids
  (0.2.0); F1 track IDs corrected against the official EA enum (0.23.0).
- Incident events from the event packet — collisions, penalties, overtakes,
  track-limits warnings, safety-car states (0.1.113–0.1.135) — each stamped with
  lap distance for later placement on a track map.
- Driver assists parsed, logged per lap and coached (0.40.0); assist tracking
  refined to ignore AI-driven out-laps and forced pit-lane assists so a clean
  lap isn't falsely flagged (0.43.0, 0.46.3, 0.62.1).
- World position from the Motion packet (0.14.0), with a 2026 stride/offset fix
  for race weekends (0.19.1) and all-cars parsing for the spotter radar (0.34.0).

### Forza & Project CARS 2
- Project CARS 2 (from 0.1.17): fixed the packet-type offset that broke all
  parsing, then corrected the participant struct, timing, sectors, positions,
  fuel, tyres (Kelvin→°C) and session-state detection; car class auto-detected
  from vehicle names (0.1.68).
- Forza Horizon and Motorsport: corrected gear byte mapping (0.1.15–0.1.16),
  redline calibration (`EngineMaxRpm` overstates the true limit), and car
  identification by `CarOrdinal` moved to a ~1,100-car CSV exposing real
  car names (0.1.62–0.1.64). The DeLorean DMC-12 (ordinal 1270) drives its own
  bespoke "Back to the Future" dashboard.
- A shared retro `LCDDashboard` (formerly Formula Ford), reused across PC2
  Formula Rookie / karting and other low-fidelity classes.

### Gran Turismo 7 (beta)
- First PlayStation and first active-protocol source (0.10.0): sends heartbeats,
  receives Salsa20-encrypted packets, decodes gear/speed/RPM/shift-lights/fuel/
  tyres/laps/position and the car code, and infers session type.
- Pure-Python Salsa20 (no new dependency), console broadcast auto-discovery, and
  record/replay support that falls out of the capture layer. Verified only
  against a simulated console — a real-hardware capture is still wanted.

### Session logging, history & grading
- Typed-row CSV session format (0.1.105) with metadata, grid, laps, events,
  standings and summary rows — the device's own records database (files are
  never deleted by age; a share window only limits what the sync API lists).
- Shared `sessionlog` library (0.1.136) as the canonical home for parsing, pace
  facts, grading and a SQLite records index — pure stdlib, unit-tested.
- Session-aware grading (0.1.137): races grade race craft/discipline and race
  pace against the prior best race lap rather than a theoretical lap; practice/
  qualifying/hotlap keep their own philosophies.
- End-of-session summary screen (0.1.138) and a full session history browser
  (0.1.139) with lap tables, standings, flag colours, all-time combo records and
  two-tap delete.
- Race-engineer coaching notes, later made track-aware — contacts and
  track-limits placed against labelled corners with severity-coloured minimap
  thumbnails (0.25.0–0.29.0), and within-session progression coaching that reads
  a session as an ordered story (0.55.0).
- Driver debrief (0.6.0), pre-session "NEXT GOAL" cards (0.3.0), focus-driven
  sessions (0.35.0) and closed-loop tracked objectives scored met/missed/open
  (0.56.0–0.64.0), all tuned to the session type (0.62.0).
- First-person driving journal (0.8.0), progressively richer and less repetitive
  (0.47.0–0.57.0), plus real circuit names and locations (0.49.0).
- Authenticated read/write LAN API (0.7.0): a pairing token gates every
  endpoint, and companion uploads (e.g. imported sessions) are validated and
  indexed.

### Achievements & driver profile
- Career-wide achievements/badges computed deterministically from the archive,
  so the collection is retroactive and identical on the Pi and web (0.9.0), with
  more milestone/craft/racecraft badges and a tap-through trophy detail that
  doubles as a goals board (0.13.0).
- Shared `sessionlog.career`: recent-form grade + trend (0.38.0) and six
  "chase statistics" personal records (0.46.0).
- Driver profile screen on the Pi (0.46.0), profile synced from the web
  companion with a customisable helmet avatar (0.54.0), and a home menu
  redesigned around the last game + a driver-profile hero card (0.52.0).

### Track recorder & circuit maps
- Track recorder mode (0.14.0): a driver-armed state machine that traces left
  edge → right edge → racing line (median-averaged over attempts) → optional pit
  lane, capturing start/finish and sector boundaries automatically; never a
  driven session (no logging/PBs/achievements).
- Explicit START button so recording can begin on the first flying lap (0.16.0);
  live debug readout confirmed the F1 Motion feed on real hardware (0.15.0).
- Extensive pit-lane capture work (0.21.x): follows the slip-roads to their true
  merge, excises the garage box, removes doubling-back spurs, snaps ends onto the
  line, and handles pit lanes that run under the circuit via the pit limiter.
- Track file format with shared circuit geometry and per-car-class racing lines +
  gears (0.22.0, 0.33.0), labelled corner/straight/complex sections, provenance
  metadata (0.23.0), and a cosmetic map orientation (0.67.0).
- Editing an existing map: re-drive a single line or add a pit lane later
  (0.19.0). A track-sync API and a standalone offline map editor (moved to the
  separate ShfonicDashTracks repo).
- Racing-line coaching (0.30.0): per-lap offset profiles drive off-line engineer
  notes, a player-vs-racing minimap, corner-line goals and an "On the Line"
  achievement; incidents placed on the lap's own driven line (0.61.0).
- A zoomable browser session line viewer overlaying every lap vs the racing line,
  with incident markers, sectors and smoothing (0.41.0–0.42.0).

### Web companion
- A phone-browser mirror served by the Pi under `/app`, for drivers without the
  native companion (0.63.0): driver profile, session list, records-style
  drill-down, and a companion-fidelity session detail with lap tables, adaptive
  charts, circuit minimaps and engineer notes — a third renderer over the same
  `sessionlog` engine.
- QR pairing with cookie auth (a `?key=` sets an HttpOnly session cookie; the
  JSON/CSV API stays Bearer-only) via a vendored pure-stdlib QR encoder; a
  COMPANION pill on the game menu; and an OFF / MENU / ALWAYS lifetime setting so
  a Pi 3 never runs the server during gameplay.
- Companion-fidelity redesign (0.65.0–0.66.0): driver-hub home with a real
  helmet avatar, editable driver profile, sessions with sub-tabs and a combo
  driver-profile repeatability panel, trophies gallery with per-badge detail,
  journal, settings and an embedded track editor + line viewer.
- Restyled end-to-end on the shfonic design system — IBM Plex Mono, oklch
  palette, flush border-led layout — with corner-thumbnail engineer notes, a
  dedicated Share screen that works over plain HTTP, and canonical shared
  driver-identity and AI-brief modules (0.67.0).

### Accessibility & UX
- Six themes including a Light theme (0.39.0) and a High Contrast preset, plus a
  colour-blind-safe accent mode; metric/imperial units throughout.
- Pause overlay and stream-silence pause detection (PC2 stops broadcasting when
  paused); a race-end "safe to exit" results banner (0.1.134).
- Menu quality-of-life: enable/disable games (0.5.0), a milestone panel, a SYNC
  pill with a waiting-to-download badge (0.1.132), a power-button sheet
  (0.46.0), and an idle screensaver to prevent LCD burn-in (0.21.0).
- Expected telemetry format shown up-front on the menu and waiting screen so a
  silent or mis-configured feed is diagnosable (0.20.0).
- Tyre compound markers wherever laps are shown, and a mid-session pit card
  (0.4.0).
- MIT License and a public-release README/SETUP restructure with a screenshots
  gallery and trademark disclaimer.
