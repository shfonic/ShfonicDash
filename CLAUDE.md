# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Shfonic Dash is a Pygame-based telemetry dashboard for sim racing games, designed to run on a
Raspberry Pi 3 with a 7" touchscreen mounted in the cockpit. It listens
passively for UDP telemetry broadcast by the game on a console/PC and
renders a live, game-specific dashboard — gear, speed, RPM, tyres, fuel, lap
times, ERS, and more.

## Running the App

All commands must be run from `src/`:

```bash
cd src
```

### On Mac (development)

Always include `--no-flip` (display is not upside-down) and `--show-cursor` (no touchscreen on Mac — the cursor acts as the pointer). Both flags have config-file fallbacks in `src/config.json` (`"flip"`, `"show_cursor"`) used when the flag is omitted — set `"show_cursor": true` there once and the flag is no longer needed; `--hide-cursor` overrides the config in the other direction.

**With mock telemetry (no game required):**

```bash
# Show the game selection menu, mock mode
python main.py --mock --no-flip --show-cursor

# Jump straight to a specific game + preset (bypasses menu)
python main.py --mock --mock-preset gt3          --no-flip --show-cursor
python main.py --mock --mock-preset gt4          --no-flip --show-cursor
python main.py --mock --mock-preset f1           --no-flip --show-cursor
python main.py --mock --mock-preset f2           --no-flip --show-cursor
python main.py --mock --mock-preset f1_26        --no-flip --show-cursor
python main.py --mock --mock-preset formula_rookie --no-flip --show-cursor
python main.py --mock --mock-preset pcars2       --no-flip --show-cursor
python main.py --mock --mock-preset fm           --no-flip --show-cursor
python main.py --mock --mock-preset fh6          --no-flip --show-cursor
python main.py --mock --mock-preset gt7          --no-flip --show-cursor

# Override the session type
python main.py --mock --mock-preset gt3 --mock-session race       --no-flip --show-cursor
python main.py --mock --mock-preset f1  --mock-session qualifying --no-flip --show-cursor
python main.py --mock --mock-preset f1  --mock-session practice   --no-flip --show-cursor
python main.py --mock --mock-preset f1  --mock-session hotlap     --no-flip --show-cursor
```

Session choices: `race`, `practice`, `qualifying`, `hotlap`.

**With a real game (live UDP):**

```bash
python main.py --game f1_25  --no-flip --show-cursor   # F1 2025, port 20777
python main.py --game pcars2 --no-flip --show-cursor   # Project CARS 2, port 5606
python main.py --game fh6    --no-flip --show-cursor   # Forza Horizon 6, port 5301
python main.py --game fm     --no-flip --show-cursor   # Forza Motorsport, port 5606
python main.py --game gt7    --no-flip --show-cursor   # Gran Turismo 7, port 33740 (BETA — untested in-house)
python main.py --game gt7 --gt7-ip 192.168.1.30 --no-flip --show-cursor   # fixed console IP (default: broadcast auto-discovery, or "gt7_ip" in config.json)
```

**Recording and replaying real sessions:**

Real-session bugs are usually impossible to reproduce with mock data. Add `--record` to any live session to dump the raw UDP packets to `logs/captures/<game>_<timestamp>.srtc`, then replay them later on the Mac — the app runs completely unmodified (packets are re-sent over real UDP to localhost):

```bash
python main.py --game pcars2 --record --no-flip --show-cursor        # record while driving
python main.py --replay ../logs/captures/pcars2_20260702_183000.srtc --no-flip --show-cursor
python main.py --replay <file> --replay-speed 5 --no-flip --show-cursor   # 5x fast-forward
```

The game is auto-detected from the capture header — no `--game` needed with `--replay`. Captures double as regression-test fixtures; the format is documented in [capture.py](src/telemetry/capture.py). **When debugging a parser bug observed in a real session, ask for a capture first.**

### On Raspberry Pi

The Pi launches automatically on boot via `.bash_profile` → `startx run_dashboard.sh` (see `SETUP.md`). **The arguments are fixed in `run_dashboard.sh` and cannot be changed per run.** The display is mounted upside-down so `--flip` is the default and `--no-flip` must not be used. `--show-cursor` is also not needed — the touchscreen is used instead.

```bash
# run_dashboard.sh on the Pi (do not modify without reading SETUP.md):
export SDL_VIDEODRIVER=x11
cd ~/ShfonicDash/src
python3 main.py
```

To disable auto-start temporarily, create the lock file:
```bash
touch ~/.dashboard_disabled
```
To re-enable: `rm ~/.dashboard_disabled`.

## Architecture

### Data Flow

```
TelemetrySource (UDP / Mock)
    └── read() → TelemetryData (dataclass)  ← per-frame snapshot only
                    └── DashboardManager.update(data)
                            ├── SessionHistory.update(data)  ← always runs
                            └── ConfigDashboard / custom Dashboard
                                    └── Widget.render(surface)
                                            └── reads SessionHistory for cross-session state
```

### Core Layers

- **[src/core/telemetry_model.py](src/core/telemetry_model.py)** — `TelemetryData` dataclass; the single shared data contract between telemetry sources and dashboards. Add new fields here when extending. **This is a per-frame snapshot — do not store accumulated session state here.**
- **[src/core/app.py](src/core/app.py)** — Main Pygame loop: wires together a `TelemetrySource` and a `DashboardManager`, handles 2-second long-press exit, optional 180° display flip.
- **[src/core/dashboard_manager.py](src/core/dashboard_manager.py)** — Auto-selects the correct dashboard config based on `car_class` and `session_type` from telemetry. Supports touch swipe left/right to manually cycle through configs for the current car class.
- **[src/core/lap_tracker.py](src/core/lap_tracker.py)** — `LapTracker`; the single source of truth for lap-completion and rewind detection. Feed it `TelemetryData` snapshots, it returns `LapCompleted` / `Rewind` events. Used by both `SessionHistory` and `SessionLogger` (one instance each — they reset at different times). **Never reimplement lap/rewind detection elsewhere.**
- **[src/core/geometry.py](src/core/geometry.py)** — shared 2-D polyline geometry (`project_to_line`, `signed_offset`), factored out of the track recorder so it and the line tracker share one projection. `signed_offset` is positive to the *right* of travel (tangent rotated −90°); `sessionlog.lines` reconstructs the driven line with the same convention.
- **[src/core/line_tracker.py](src/core/line_tracker.py)** — `LineTracker`; records racing-line adherence during a driven session. Fed the same frames + `LapTracker` events as `SessionLogger` (it reacts to them, never re-detects laps), it buffers each frame's perpendicular offset from the class racing line and, on lap completion, resamples it onto the line's station grid → a per-lap **offset profile** the logger writes as a `P` row. Pure stdlib, unit-tested. **Any F1 session at a track with a recorded line for the driven class produces profiles** (all session types — race/practice are as worth reflecting on as a hotlap); `SessionLogger` arms it itself in `_open_session` via `trackmap.find_map` — never in record mode. `sessionlog.lines` derives all coaching from the `P` rows (see [session-log-format.md](docs/session-log-format.md)).
- **[src/core/resolve.py](src/core/resolve.py)** — Resolves dotted paths like `"telemetry.speed"` to actual attribute values; used by widget config.
- **[src/core/config_store.py](src/core/config_store.py)** — Persists user settings (theme, units, flip, show_cursor, share_logs, share_window_days, show_session_summary, enabled_games, show_record_button, web_app_mode, etc.) to a local JSON file. `enabled_games` (settings GAMES tab) filters which games the menu shows — missing ids default to enabled; the menu grid adapts to the enabled count. `share_window_days()` reads the share window with migration from the retired `log_retention_days` key. `web_app_mode()` (DATA tab, `off`/`menu`/`always`, default `menu`) controls when the browser web companion is reachable — see the web-companion bullet below.
- **[src/core/session_summary.py](src/core/session_summary.py)** — End-of-session summary screen (stats, grades, Race Engineer Notes), shown when a session file closes **or on the game-pause rising edge** (hotlap/TT sessions never rotate, so pause is their only end-of-stint signal; the still-open file is parseable because every row is flushed). Gated by the `show_session_summary` setting (DISPLAY tab, default on). `build_summary()` re-parses the CSV through `sessionlog` (never live state — keeps the Pi and companion numbers identical), indexes it into `logs/.sessions.db` and feeds `prior_best` into grading. Dismissed by tap or by `DriveAwayDetector` once the player is driving again; each new pause shows a fresh summary. The same screen doubles as the **mid-session pit card** ("SESSION SO FAR" caption): shown once per pit visit when stopped (<5 km/h) in the pits during practice/qualifying with laps banked (`App._maybe_show_pit_card`) — never in races, and the pause path owns menu-based garage returns.
- **[src/core/pre_session.py](src/core/pre_session.py)** — Pre-session "NEXT GOAL" card, shown on a **zero-lap** game-pause rising edge (hotlap/TT sessions start in the pause menu): grade step, prior best, provable sector gain and up to 3 data-backed missions from `sessionlog.goals.pre_session_goal()` over the records combo history. Hosted in the same modal slot as the summary (tap / drive-away dismisses); never shown without history or when the game has no track name (PC2/Forza). Gated by the same `show_session_summary` setting.
- **[src/core/debrief.py](src/core/debrief.py)** — Post-session driver debrief: 2–3 big-button questions **tuned to the session type** (always feeling; then the goal — the race-specific `goal_race` for races — when no focus was committed; then ≤1 reaction picked by `sessionlog.debrief.select_questions` from session facts, on a per-type ladder: races ask about contact/penalties/lost places/the start, quali about the theoretical gap or what cost the lap, hotlap/practice about the gap/rewinds/corner/invalids). Two hosts: the blocking flow after the exit-to-menu summary (`run_debrief_screen`), and `DebriefOverlay` in the App's modal slot when a **rotated-away** session's summary is tap-dismissed (in-game session switches — telemetry keeps flowing underneath; drive-away abandons, keeping given answers). Answers append to the closed CSV as `D` rows via `append_debrief()`. Skippable; gated by `debrief_enabled` (DISPLAY tab, default on). The companion asks the same questions on AC/ACC import.
- **[src/core/history_browser.py](src/core/history_browser.py)** — Session history browser (HISTORY button on the game menu): touch-scrollable list of `logs/` sessions from the records index with game filter chips (defaults to the most recently driven game), detail view with lap table (companion flag colours), standings, ACHIEVEMENTS earned, full Race Engineer Notes (contact / track-limits notes carry a row of **corner mini-map thumbnails** via `core/track_thumb.py` + `trackmap.crop_geometry`) and a two-tap DELETE that moves the CSV to `logs/.trash/`. `ScrollPane` is the reusable drag-to-scroll/tap-detection helper; `_ellipsize` truncates long titles to their column. **Offscreen surfaces must be created with `depth=24`** — default 32-bit offscreen surfaces carry garbage alpha that corrupts blits and PNG saves.
- **[src/core/trophies_browser.py](src/core/trophies_browser.py)** — Badge gallery (TROPHIES button on the game menu): every `sessionlog.achievements` badge grouped by category, tier-coloured medal rings (no emoji on the Pi). Tapping **any** badge — earned or not — opens a detail card: what the trophy is, how to earn it (with `achievements.tier_goals()` for repeatable badges), current standing, and the full list of sessions that count towards it (newest first, each tappable to open the history browser's detail view). Unearned badges open a how-to card, so the gallery doubles as a goals board.
- **[src/core/profile_browser.py](src/core/profile_browser.py)** — Driver profile (the **DRIVER PROFILE** hero card on the game-menu home, which taps through to this deep screen): the Pi's mirror of the companion's driver-profile hub. Overall recent-form grade + trend (`sessionlog.career.recent_form`), a per-game breakdown, career session/trophy counts, and a **Personal Records** grid — the "chase statistics" (`sessionlog.career.personal_records`): longest clean streak, best consistency, largest PB gain, most-driven track, favourite car, total distance. Reads the same records index as the trophies/history browsers, so all three agree. No arrow glyphs in the Pi UI font — trend is a word + a hand-drawn triangle. The summary maths are module functions (`compute_form` / `count_trophies` / `compute_records` / `record_tiles`) so the menu's home card derives identical numbers.
- **Log lifecycle:** session CSVs in `logs/` are never deleted by age — they are the history/records database. Zero-lap sessions are deleted at close (noise); user deletes go to `logs/.trash/` (pruned after 30 days by `cleanup_trash`). The DATA tab's share window (1/7/30 days/ALL) only limits what the Share Logs API lists; REBUILD SESSION INDEX re-scans `logs/` into `.sessions.db`. **The API is authenticated and read/write (v0.7.0):** every endpoint requires the PAIRING CODE (DATA tab; `config_store.api_token`, fail-closed) as a Bearer token, and `PUT /<filename>.csv` accepts companion uploads (ACC imports) — validated, marked synced, indexed on next scan. **The same server also syncs track maps (v0.19.0):** `GET /tracks/index.json` (lists `car_classes` per track), `GET /tracks/<file>.json`, and `PUT /tracks/<file>.json` (validated as a track map — accepts `lines`; 1 MB cap) over `tracks_dir`, set via `LogServer.set_tracks_dir`. Spec: [docs/session-log-format.md](docs/session-log-format.md), track maps: [docs/track-format.md](docs/track-format.md).
- **[src/core/web_app.py](src/core/web_app.py)** — **Web companion (v0.63.0):** a mobile browser mirror of the Pythonista companion, served under `/app` on the log server. Pure-stdlib server-rendered HTML (f-string templates, theme-matched to the apps in light + dark, near-zero JS); `core/log_server.py` owns the HTTP plumbing and delegates rendering here. It is a **third renderer over the same engine** — the home page reuses `core/profile_browser.py`'s `compute_form`/`compute_records`/`record_tiles` and detail reuses `core/session_summary.build_summary` + `parser`, so web app, Pi summary and companion show identical figures. Styled end-to-end on the **shfonic design system** (`APP_CSS`, v0.67.0): **IBM Plex Mono** everywhere, the **oklch** palette (accent amber, `--purple` = best-lap, `--magenta` = session-best), **flush/border-led** — no card boxes; sections and rows are edge-to-edge separated by hairlines (`.sec`/`.flush`), sharp 4–8 px radii, **outlined** session-type + filter chips, no shadows — matching the Claude-Design prototype in `ideas/` and the Pythonista app in light + dark. Race Engineer Notes are plain paragraphs (no `//`) each followed by **corner mini-map thumbnails** (`_corner_thumb_svg` over `trackmap.crop_geometry`, kind-coloured, blue rim for rewound), like the Pi/companion. The **combo leaf** leads with a prominent track title and its session rows drop the track name (date + grade + best + laps). A per-session **Share** screen (`/app/session/<file>/share`) shows the brief in a selectable textarea + a copy button that works over plain HTTP (`execCommand` fallback — the clipboard/Web-Share APIs need a secure context the LAN address lacks). Pages (companion-fidelity — per-row grade+score, condensed mono titles): `/app` (driver profile), `/app/sessions` (list + game filter chips), `/app/browse` (records-style **drill-down** Game → Class → Track → Session type → sessions, mirroring the companion `stats.py`), `/app/session/<file>` (grade·pace·trend + race position-change header, lap table with **tyre chips + per-lap delta + flag-coloured sectors**, an adaptive **position-by-lap** (races) / **lap-time-progress** (lap sessions) inline-SVG chart, the **circuit minimap** for any session at a mapped track — the driven-line-vs-racing-line via `lines.player_line_geometry` when a lap profile exists, else the racing line + `map_events` incident markers — standings, Race Engineer Notes), and `/app/session/<file>/lines` (the full zoomable **session line viewer** — the **vendored `src/core/session_viewer.html`** from the ShfonicDashTracks repo, served with `lines.session_line_export` baked in via `window.VIEWER_DATA`; keep it in sync with that repo's canonical copy). **SVG note:** emit self-closing SVG tags as `<tag ...></tag>` or with a space before `/>` and quote every attribute — an unquoted value like `opacity=0.7/>` swallows the self-close in the HTML parser and drops all following elements. **Auth:** browsers can't send the Bearer header on a navigation, so `?key=<token>` is validated once, sets an `HttpOnly` session cookie (HMAC of the token via `session_cookie()`), then 302-redirects to strip the key from the URL; later navigation authorises off the cookie (`cookie_valid()`). The JSON/CSV API stays Bearer-only — the cookie never opens it. **Lifetime** (`config_store.web_app_mode`): `off` disables `/app` (`LogServer.set_web_enabled(False)`); `menu` serves only while the menu/settings are open (the Share-Logs lifetime — never during 60fps gameplay); `always` keeps the server up mid-session for powerful Pis (`App._ensure_always_web_server`, and settings-close leaves it running). **Companion-fidelity page set (v0.65.0):** the home is the **driver hub** (avatar + OVERALL grade + stat-tile grid + RECENT + Journal/Trophies/Tracks buttons); `/app/driver` is an **editable** profile (name/experience/discipline/goal/helmet → cookie-authed `POST /app/driver/save` → `config_store.set_profile`); the **avatar reuses the Pi's own helmet mask PNGs** (`helmet.png`/`helmet_visor.png`/`helmet_trim.png`, served at `/app/img/…`) composited in-browser via CSS masks + tints — never a reinvented avatar; the Sessions screen has **SESSIONS / GAMES / FAVOURITES** sub-tabs (the GAMES drill-down **leaf** leads with the full **DRIVER PROFILE repeatability panel** — `grading.driver_profile()` over `records.combo_history()`, the browser mirror of the companion `stats.ProfileHeader`: PB, avg best, sessions, consistency stars, typical clean pace, pace trend, fast-lap repeatability %, profile confidence — then a progress chart with the clean-lap spread band, and session rows with only the fastest in magenta); plus `/app/trophies` (achievements gallery — every badge taps to **`/app/trophy/<id>`**: medal + earned status/tier, **HOW TO EARN** with `achievements.tier_goals()`, and every contributing session, each tappable; unearned badges show the how-to), `/app/journal` (`sessionlog.journal`), `/app/settings` (light/dark/size, per-browser via localStorage), `/app/tracks` + the vendored **`core/track_viewer.html`** map editor (Back bar + **Save to Pi** via `POST /app/track/<file>/save`), a per-session **Share** brief (Web Share/clipboard) and a **new-session banner** polling `/app/status.json`. **No companion Python is copied — every page renders over the shared `sessionlog` package (canonical here); the two vendored HTML editors come from ShfonicDashTracks (their canonical home).** **QR onboarding** has two entry points: a **COMPANION pill** on the game-menu home (`GameMenu._qr_rect`/`_draw_qr_pill`/`_show_companion_qr`, next to the SYNC pill, shown when `web_app_mode != "off"`), and the DATA tab's server-URL line — both tap to a full-screen scannable QR (`core/qr.py` vendored pure-stdlib encoder — no third-party dep, verified via the Thonky RS vector + OpenCV decode — rendered to a surface by `core/qr_render.py`) encoding `http://<lan-ip>:8765/app?key=<token>`. **Never a `sessionlog/` change — the web companion is Pi-only, not vendored to the companion.** Routes/auth spec: [docs/session-log-format.md](docs/session-log-format.md).
- **[src/core/app_logging.py](src/core/app_logging.py)** — Logging setup: console + size-capped rotating file (`logs/dashboard.log`, 1 MB × 3 files max — can never fill the Pi's SD card). Use `logging.getLogger(...)`, never `print()`; `--debug` raises the level to DEBUG.

### Shared sessionlog Library (`src/sessionlog/`)

The session-log analysis layer shared with the Pythonista companion app: `parser` (CSV → session dict, lap/sector flags, `scan_session`), `pace` (pace facts + Race Engineer Notes — `race_engineer_notes()` takes an optional `track_map` to place contact incidents and track-limits warnings against labelled track sections, e.g. "at Turn 3, before the apex"; without one it reads exactly as before. `race_engineer_notes_detailed()` returns the same notes as `{text, locations:[{label, distance, kind, rewound}]}` so a renderer can draw a corner thumbnail per located note — `kind` (track_limit / contact / major, classified evidence-only from collision events + penalty infringements) is the marker fill, and `rewound` adds a blue rim so a contact and its flashback show on one marker), `trackmap` (`find_map(game, track)` loads the matching track JSON — call `trackmap.set_tracks_dir(...)` before use, same pattern as `records.set_cache_dir`; `describe_location()` / `locate_section()` do the distance → section lookup, prioritising corner/chicane > complex > straight/drs > other, and when nothing covers the point `bracket_corners()` names the corners it sits between ("between Village and The Loop"); `crop_geometry(track_map, distance)` returns the edge-slice + marker + fit box a renderer needs for a zoomed corner thumbnail — pure data, drawn per-app; `resolve_line(track_map, game, car_class)` picks a class's own racing-line profile, falling back to a sibling's line only for shared-line games when the class has no profile yet), `grading` (session grades), `goals` (pre-session "NEXT GOAL" + data-backed missions, **session-type-specific** — races get craft/position missions, lap sessions get the lap-time set), `focus` (the one headline the driver commits to pre-session; the chip set varies by session type — pace-led for hotlap/quali, consistency-led for practice, and a race-native CLEAN RACE / POSITIONS / RACE PACE / MANAGE set for races), `progression` (within-session progression read — reads the session as an ordered story rather than one flat aggregate: `progression_facts()` = early-vs-late clean rate, first clean lap, pace trend over representative clean laps, per-sector spread; `progression_notes()` = the evidence-only Race Engineer Notes those support — % clean + longest consecutive clean run, the within-session clean-up trend, the pace trend, and which sector is leaking time; skipped for races/short sessions, folded into `pace.race_engineer_notes_detailed`), `objectives` (tracked objectives — the closed-loop follow-up to the pre-session missions: each data-backed goal is written to the CSV as an `O` row when the NEXT GOAL card is shown, then `evaluate_all()` scores it against the finished session — met / missed / still-open. Types: `clean_streak`, `no_flashbacks`, `beat_time`, `convert_sectors`, `tighten_spread`, `corner_limits`, `corner_line` (line deviation at a corner — F1 mapped tracks via `lines.corner_deviations`/`line_hotspot`), `reduce_assists`, plus race-only `finish_clean` (no contacts/penalties) and `gain_positions` (finish no worse than the grid slot). `goals.objectives_for()` extracts them from the missions; the summary/history browser show the outcomes), `debrief` (post-session question bank + adaptive selection + share-text lines), `share` (**canonical** coaching AI brief — `format_for_ai(session, *, profile, track_map, journal_entry)`, the pure-stdlib home of the companion's old `dashboard._format_for_ai`; role framing + full session debrief. Both apps supply the app-specific context as kwargs; every richer section is read from the session dict with `.get` guards so a raw parsed session degrades gracefully. The web companion Share screen renders it; the Pythonista `dashboard._format_for_ai` will call it on its next pass), `profile` (**canonical** driver-identity vocabulary — the Experience / Discipline / Goal `(value, label)` option lists + `experience_label()`/`discipline_label()`/`goal_label()`; both apps read these so synced profile values agree, and the companion's `driver.py` re-exports them), `journal` (story-driven diary entries; one badge per entry woven in via `awards`), `achievements` (career badges computed from the archive — `evaluate()` for the trophy gallery, `session_awards()` for "what did this session earn"; the CSVs are the save file, so both apps derive the same collection and history is retroactive), `records` (SQLite index over a CSV directory — call `records.set_cache_dir(...)` before use on the Pi; default is the companion's layout; carries `distance_m` per session, F1-only for now via `parser.F1_TRACK_LENGTHS_M`), `circuits` (circuit reference data keyed by the bare telemetry track name — `display_name(game, track)` = the real circuit name ("Albert Park Circuit"), `location(game, track)` = "Melbourne, Australia" for "where we raced", both falling back safely for unknown/non-F1 tracks; also the single source of `parser.F1_TRACK_LENGTHS_M` and the session dict's `track_name`/`track_location`. F1 only for now), `career` (driver-profile aggregates over the index rows: `recent_form()` = windowed overall grade + trend + per-game; `personal_records()` = the six "chase statistics" — longest clean streak, best consistency, largest PB gain, most-driven track, favourite car, total distance — shown identically on the Pi PROFILE screen and the companion Driver Profile), `lines` (racing-line adherence from the `P`-row offset profiles: `lap_adherence` / `session_line_facts` — corner-zone deviation, weighting corners only so straights don't count against you — drive the `on_the_line` achievement and the off-line Race Engineer Notes; `player_line_geometry(track_map, offsets)` returns the racing + reconstructed-driven polylines for the player-vs-racing mini-map, pure data drawn per-app like `crop_geometry`; `session_line_export(session, track_map)` packages a whole session (track map + every profiled lap's offsets, sector times and best-lap id, plus `map_events()` — track-limits/contact/flashback markers by lap distance) for the zoomable **session line viewer** — `session_viewer.html` in the ShfonicDashTracks repo, which the companion opens with the data baked in via `SHFONIC.load()` and reconstructs each driven line in JS with the same maths. `_lap_invalid()` reads validity from either the typed parser's `valid` field or the flat parser's `invalid`).

- **This repo is the canonical home.** The companion carries a vendored copy written by `sync_shared.py` (repo root); after changing anything under `src/sessionlog/` or its shared tests, run `python3 sync_shared.py` and commit both repos. `--check` reports drift. A manifest drift test fails the companion's CI if its copy is edited directly.
- **Pure standard library only** — no pygame, no Pythonista modules — and no Python 3.11+ syntax (floor is the companion's 3.10).
- Shared tests: the `SHARED_TESTS` list in `sync_shared.py` (the single source of truth for which test files travel with the package); the sample-session fixture lives in `tests/fixtures/`.
- Optional `src/grading.json` (gitignored) tunes grading locally; the format spec consumed by this package is `docs/session-log-format.md`.

### Session History (`src/core/session_history.py`)

`SessionHistory` is the home for any data that must survive a dashboard switch (e.g. user swipes from practice to qualifying mid-session and back).

**Why it exists:** `TelemetryData` is a per-frame snapshot and is not suitable for accumulated state. Widgets that stored their own history (e.g. `LapListWidget`) lost it when the active dashboard changed, because `widget.update()` is only called while that dashboard is visible.

**Public state:**

```python
class SessionHistory:
    laps: list[dict]         # {num, time, invalid, s1_t, s2_t, s3_t} — all completed laps, newest first
    best_lap: float          # player personal best this session
    participants: list[dict] # {position, name, best_lap} — live qualifying leaderboard
    session_type: str
    car_class: str

    def update(self, data: TelemetryData) -> None: ...
    def reset(self) -> None: ...
```

**Ownership:** `DashboardManager` creates and owns one `SessionHistory`. It calls `session.update(data)` on every tick **before** updating the active dashboard, and calls `session.reset()` whenever `car_class` or `session_type` changes.

**Widget opt-in:** The `Widget` base class has a `set_session(session)` no-op method. `ConfigDashboard` calls it on each widget after instantiation, and `DashboardManager` calls it on each dashboard when loaded. Widgets that need session data (e.g. `LapListWidget`, `QualifyingTableWidget`) override it, store the reference, and read from it in `draw()` instead of maintaining their own state.

**Scope of `SessionHistory`:** It should store everything that is:
- accumulated over time within a single session (lap list, stint data, position history), or
- needed by multiple dashboards simultaneously (qualifying leaderboard).

It should **not** duplicate data that is already live in `TelemetryData` (speed, RPM, current lap time, etc.) — widgets read those directly from the telemetry snapshot as they do today.

### Track Recorder (`src/core/track_recorder.py`, `src/dashboard/track_recorder_dashboard.py`)

A driver-controlled mode that builds a reusable circuit map by driving the track. Armed from the **RECORD** pill on the **SELECT GAME picker** (`GameMenu._pick_game` → `GameMenu._record_armed` → `record_track` in the selection kwargs → `App(record_track=True)`); currently exercised with **F1 25/26** (the only source that populates world position — needs the Motion packet). **The RECORD pill is hidden by default** (v0.24.0) and shown only when *Show RECORD button* is enabled in SETTINGS → DATA (`show_record_button` in config.json); arming resets each time the picker is opened. (Before v0.52.0 the pill lived on the flat game-menu; the home screen is now the last-game + driver-profile card layout and the grid moved to the picker.)

- **`TrackRecorder`** is a pure-stdlib, unit-tested state machine fed `TelemetryData`. Phases: **left edge → right edge → racing line** (several attempts, median-averaged onto a common distance-station grid) → optional **pit lane**. Each phase is **armed by the driver** (`arm()` — the START button): the driver positions, presses START, and recording begins at the next start/finish crossing (so you can record from the first flying lap, and the idle-until-START gap is the repositioning lap between phases). Each lap is reviewed (`accept()` / `redo()`). **S/F crossing is detected from the raw lap-number tick** (works from lap 1, unlike `LapTracker.LapCompleted` which needs a prior completed lap); **rewind/flashback detection stays with `LapTracker`** (never re-implemented) — a mid-lap rewind discards the lap and re-arms. The S/F line and **sector-boundary positions** (not times — for later sector colourising) are captured automatically from lap tickover and the live `sector` field. Pit frames (`in_pits`) are excluded from the track edges; the optional pit-lane pass instead captures the full driven trip — **entry road → pit lane → exit road** — not just the `in_pits`-flagged middle (which alone leaves the saved lane floating ~20–90 m off the circuit at both ends). It **buffers the on-track approach** (`_buffer_approach`/`_lead_in`) and **keeps capturing the exit** until the car rejoins the line (`_pit_exiting`), capped at `_PIT_LEAD_MAX_M`. "On the track" is the **perpendicular distance to the nearest racing-line segment** (`_project_to_line`, not vertex distance — the line's ~15 m vertex spacing means a car dead on the line is still ~7 m from any vertex) within a tight `_PIT_MERGE_M` (3 m) band, so the slip-road is followed all the way down to its actual merge with the line rather than stopping while still running parallel a few metres out. The **exit** merge is additionally gated on the **pit limiter being off** (`data.pit_limiter`): where the exit road runs *under* the circuit (Abu Dhabi's pit lane crosses beneath the main straight) the 2-D point sits on the racing line even though the car is still in the pit lane below, so proximity alone would cut the capture off at the crossover — the limiter is the true "still in the lane" signal, so the driver is asked to hold it (pit assist off) until they reach the track. Sources without a limiter report it `False`, keeping the old proximity-only behaviour. `_finish_pit` then **excises the garage box** (`_excise_box`: points within `_PIT_BOX_RADIUS` of the slowest in-pit point — the box — are dropped and bridged straight, only when a genuine stop under `_PIT_BOX_SPEED` happened), **speed-gates the box stop** (frames below `_PIT_MIN_SPEED` ≈ 8 km/h dropped), **removes any doubling-back spur** (`_drop_reversals`, turns sharper than `_PIT_SPUR_ANGLE` = 135°), and **pulls each end-tip onto the racing line** (`_snap_end`: the tip's position is replaced by its perpendicular foot — since the capture already converged onto the line, this closes the small discretisation gap as a shallow merge, not a perpendicular stub) when the residual gap is under `_PIT_SNAP_MAX_M` (8 m; a larger gap means the slip-road was never driven, e.g. a garage start, and is left rather than yanked across). The pass only starts capturing on a **genuine pit entry that follows an on-track stretch** (`_pit_seen_track`): arming while parked in the box (already `in_pits`) would otherwise grab only the box→exit half, so it waits until the driver has left the pits once (`pit_arming_in_box` drives the "leave the pits first" hint). A debug overlay (`pos_valid`, raw x/z/y, heading, dist, sector, speed…) aids verifying the position feed. Saves `tracks/<game>_<track>.json` (`TrackMap`, `FORMAT_VERSION`).
- **Per-class racing lines (`FORMAT_VERSION` 1).** The circuit geometry (edges, pit, S/F, sectors, `sections`) is **shared across car classes**; the racing line **and its gears** are per class, held in a `lines` map keyed by `car_class` (`{racing_line, racing_attempts, gears, notes}`) — one profile per class. The recorder edits only the **current live class** (`_car_class`) — `load_existing` stashes every class's entry in `_loaded_lines` and `build_map` writes them all back, so re-driving one class (or adding a new one at an already-mapped track — you keep the edges/pit/sections and just record its line) never disturbs another. **F1 classes share the same line but not the same gears** (2026 super-clipping uses different corner gears than 2025 / F2), so each F1 class (`formula1`, `formula1_2026`, `f2`) is its own profile with the line copied and gears filled per class. `sessionlog.trackmap.resolve_line(game, car_class)` returns the class's own entry; only when a class has no profile yet does it fall back to a sibling's line (shared-line games in `_SHARED_LINE_GAMES` — geometry only, never another class's gears). PC2/GT7/Forza keep true per-class lines and get no fallback. **Gears are never recorded** (you drive slower to hold the line, so live gear is wrong) — the `gears` slot stays `null` until filled via the map utility. `notes` exists track-level (`TrackMap.notes`) and per class. A track-level **`orientation`** (degrees, default 0) is a **cosmetic** display rotation: every top-down map view (Pi thumbnails/history maps, web-companion minimaps, both HTML viewers) applies the same `sessionlog.trackmap.rotate_xz(points, orientation)` (the HTML viewers as an SVG `rotate()` on the scene group) so a circuit can be turned to a more legible framing without touching the recorded world coordinates — arc-length distances, `sections` lookups and gears are unaffected. The recorder never sets it (not a driven quantity) and carries it through re-drives; the map utility's **Map orientation** control edits it. `sections` gains a **`complex`** type that groups a named corner sequence (e.g. Maggots/Becketts/Chapel) via a `members` list of turn ids. The **map utility** (`track_viewer.html`) switches the displayed line by class, edits notes and orientation, and creates complexes — it now lives in the separate **ShfonicDashTracks** repo (the community track-map database) alongside the track files it edits, not in this repo. (The earlier single-line layout never shipped — there is no legacy format to migrate.) Schema: [docs/track-format.md](docs/track-format.md).
- **Editing a saved map (v0.19.0).** `load_existing(TrackMap)` jumps straight to the DONE screen; `redrive(phase)` re-drives a single line (`_single_phase` → `accept()` returns to DONE, other lines untouched); `redrive_pit()` adds/replaces the pit lane; `discard_all()` wipes it for a fresh recording. Labelled corner/straight **`sections`** live inside the track JSON (populated by the viewer/companion) and are carried through edits untouched.
- **`TrackRecorderDashboard`** stands in for `DashboardManager` while recording (same `update`/`render`/`handle_event`/`reset_touch` surface) — a full-screen auto-fit top-down trace with the phase buttons. It holds no capture logic; it renders the recorder's exposed state. On entry, if a saved map exists for the detected game+track it offers an **EDIT / RE-RECORD** prompt; the completion screen is a 3×2 edit grid (re-drive a line, add/replace pit, discard, save).
- **It is never a driven session.** `App` forces `session_logger = None` in record mode, so no CSV, history entry, PB, achievement, pit card or debrief is ever produced. Recording and driving are fully separate paths.
- World position lives in `TelemetryData` as `pos_x`/`pos_y` (elevation)/`pos_z`/`heading`/`pos_valid`, in a common convention (X/Z horizontal, Y up) so map code stays game-agnostic. The mock source emits a synthetic circuit (`_track_point` in [mock.py](src/telemetry/mock.py)) so the recorder is fully testable on the Mac.

### Telemetry Sources (`src/telemetry/`)

All sources extend `TelemetrySource` (abstract: `connect()`, `read() → TelemetryData`, `disconnect()`).

- **[f1_2025.py](src/telemetry/f1_2025.py)** — Listens on UDP port 20777. Parses EA/Codemasters F1 packet format (2024/2025/2026 layouts). Sets `car_class` to `formula1` or `formula1_2026` (2026 Season Pack DLC), `f2`, etc. The **Motion packet (id 0)** populates the player's world position (`pos_x/pos_y/pos_z`) and `heading` (`_parse_motion`), consumed by the track recorder; g-force will come from the same packet.
- **[pcars2.py](src/telemetry/pcars2.py)** — Listens on UDP port 5606. Parses three PCARS2 packet types: `eCarPhysics`, `eTimings`, `eRaceDefinition`, `eGameState`, `eParticipantVehicleNames`. Car class is detected from the vehicle name string in `eParticipantVehicleNames` via `_CLASS_MAP` (substring match, lower-cased). Default class is `pcars2`; current mappings send `"formula rookie"` and `"kart"` to `lcd` (the LCD-style dashboard).
- **[fh6.py](src/telemetry/fh6.py)** — Listens on UDP port 5301. Identifies specific cars by `CarOrdinal` via `_KNOWN_CARS` dict (e.g. `1270 → delorean`). Falls back to Forza class letter (D/C/B/A/S1/S2/X) as `car_class`.
- **[fm.py](src/telemetry/fm.py)** — Forza Motorsport. Same 324-byte packet layout as FH6 but without the FH6-specific fields.
- **[gt7.py](src/telemetry/gt7.py)** — Gran Turismo 7 (**BETA — untested against a real console**; built from the community-documented layout, needs a `--record` capture from a GT7 owner to verify). Not a passive listener like the other sources: it sends heartbeat packets to the console on UDP 33739 (broadcast auto-discovery by default; fixed IP via `--gt7-ip` or the `"gt7_ip"` config key) and receives Salsa20-encrypted 296-byte packets on 33740. Sets `car_class` to `gt7`. Current-lap time is estimated from the 60 Hz packet counter; no sector times, participants, gaps or track name in the packet.
- **[salsa20.py](src/telemetry/salsa20.py)** — Pure stdlib Salsa20/20 stream cipher used by the GT7 source (no third-party crypto dependency); verified against a pycryptodome-generated known-answer vector in `tests/test_gt7.py`. Generates only the keystream blocks a caller needs (GT7 decrypts 3 of 5 per frame, full packet once a second for the car code).
- **[mock.py](src/telemetry/mock.py)** — Simulates realistic driving; oscillates speed/RPM/throttle/brake and briefly shows `"N"` during gear changes. Presets: `gt3`, `gt4`, `f1`, `f2`, `f1_26`, `formula_rookie`, `pcars2`, `fm`, `fh6`, `gt7`.
- **[threaded_source.py](src/telemetry/threaded_source.py)** — `TelemetryThread` binds a UDP socket and fires a callback per packet in a daemon thread.
- **[capture.py](src/telemetry/capture.py)** — `PacketRecorder` / `CaptureReplayer` for `--record` / `--replay`; raw UDP packet capture with timestamps (`.srtc` files in `logs/captures/`).
- **[lap_delta.py](src/telemetry/lap_delta.py)** — `LapDeltaTracker`; game-agnostic live-delta engine (lap profile recording + reference interpolation). Parsers own *when* to call its hooks; the tracker owns the profile/reference lifecycle. Reuse it when adding live delta to PC2/Forza — do not copy the logic.

### Dashboards (`src/dashboard/`)

All dashboards extend `Dashboard` (abstract: `update(data)`, `render(surface)`, `handle_event(event)`).

#### Config-Driven Dashboards (preferred)

Most dashboards are pure JSON files in `src/dashboard/configs/`. No Python code is needed to create a new layout — just write a JSON file:

```json
{
    "name": "GT3 Race",
    "background": [12, 13, 16],
    "widgets": [
        { "type": "ShiftLightsWidget", "x": 0, "y": 0, "width": 800, "height": 32 },
        { "type": "GearWidget",        "x": 0, "y": 112, "width": 210, "height": 190 },
        { "type": "SpeedWidget",       "x": 570, "y": 112, "width": 230, "height": 100, "unit": "km/h" }
    ]
}
```

`type`, `x`, `y`, `width`, `height` are reserved; any additional keys are forwarded as kwargs to the widget constructor.

#### Custom Python Dashboards

For dashboards that can't be expressed as a widget grid (e.g. fully custom rendering), set `python_class` in the JSON:

```json
{
    "name": "DeLorean DMC-12",
    "python_class": "dashboard.delorean_dashboard.DeLoreanDashboard"
}
```

The class is imported and instantiated with `(width, height)`. See [delorean_dashboard.py](src/dashboard/delorean_dashboard.py) as an example.

- **[lcd_dashboard.py](src/dashboard/lcd_dashboard.py)** — LCD-style legacy dashboard. Uses DSEG14Classic-Regular.ttf from `src/dashboard/fonts/`.
- **[text_dashboard.py](src/dashboard/text_dashboard.py)** — Debug view; renders all `TelemetryData` fields as key/value columns. Loaded automatically as a fallback if a config fails to load.

### Dashboard Config Resolution

`DashboardManager` auto-selects a config when `car_class` or `session_type` changes:

1. `{car_class}_{session_type}.json` — e.g. `gt3_race.json`
2. `{car_class}_default.json` — e.g. `gt3_default.json`
3. `default.json`

Swipe left/right on the touchscreen manually cycles through all configs for the current car class.

### Adding a New Car Dashboard

1. **Identify the car class** in the relevant telemetry source:
   - **PCARS2**: add a substring → class name mapping to `_CLASS_MAP` in [pcars2.py](src/telemetry/pcars2.py)
   - **FH6**: add a `CarOrdinal → class_name` entry to `_KNOWN_CARS` in [fh6.py](src/telemetry/fh6.py) (discover the ordinal by driving the car and reading `car_ordinal` from the text dashboard or logs)
   - **F1 2025**: car class is derived from participant data / packet format — see `_CLASS_MAP` in [f1_2025.py](src/telemetry/f1_2025.py)

2. **Create config JSON files** in `src/dashboard/configs/` named `{car_class}_{session_type}.json`. At minimum provide a `race` config; add `practice`, `qualifying`, `hotlap` as needed.

3. **Add a mock preset** in `src/telemetry/mock.py` `PRESETS` dict if you want to test the dashboard without a live game.

### Widgets (`src/dashboard/widgets/`)

Widgets are self-contained rendering units placed on the dashboard grid. Each widget receives the `TelemetryData` on every update.

Available widgets (registered in [registry.py](src/dashboard/widgets/registry.py)):

| Widget | JSON type key | Description |
|---|---|---|
| `GearWidget` | `GearWidget` | Current gear (large 7-seg style) |
| `SpeedWidget` | `SpeedWidget` | Speed; accepts `unit: "km/h"` or `"mph"` |
| `RPMGaugeWidget` | `RPMGaugeWidget` | Curved + bar RPM sweep |
| `PedalsWidget` | `PedalsWidget` | Throttle / brake vertical bars |
| `ShiftLightsWidget` | `ShiftLightsWidget` | Top-row LEDs, green→yellow→red; accepts `count` |
| `LapInfoWidget` | `LapInfoWidget` | Current / last / best lap times |
| `TyreWidget` | `TyreWidget` | Tyre temps + optional pressures (`show_pressure`, `cold_temp`, `hot_temp`) |
| `FuelWidget` | `FuelWidget` | Fuel level + optional laps remaining (`show_laps`) |
| `ERSWidget` | `ERSWidget` | ERS/hybrid battery level |
| `DRSWidget` | `DRSWidget` | DRS status indicator |
| `SectorTimesWidget` | `SectorTimesWidget` | S1/S2/S3 with delta colouring |
| `LapListWidget` | `LapListWidget` | Scrolling history of completed laps |
| `PositionWidget` | `PositionWidget` | Race position; `show_total: true` appends `/ N` |
| `LapCounterWidget` | `LapCounterWidget` | Current lap / total laps |
| `GapWidget` | `GapWidget` | Gap ahead / behind |
| `FlagWidget` | `FlagWidget` | Current flag colour |
| `ProximityWidget` | `ProximityWidget` | Ahead/behind gap proximity strip |
| `SpotterWidget` | `SpotterWidget` | Top-down spotter radar — cars around the player from `opponents_pos`, amber close / red alongside; accepts `range_m` (F1 + mock only; not in any shipped config yet) |
| `AeroWidget` | `AeroWidget` | Active aero / boost (F1 2026) |

To add a new widget: create a file in `src/dashboard/widgets/`, implement the `Widget` base class, then import and register it in [registry.py](src/dashboard/widgets/registry.py).

### Key Conventions

- `TelemetryData` fields are the only data passed between sources and dashboards — do not pass raw packets.
- The `src/` directory is the working directory / Python path root; all imports are relative to it (e.g., `from core.app import App`).
- Font files live in `src/dashboard/fonts/`. Image assets (splash screen, etc.) live in `src/dashboard/images/`.
- Display size is hardcoded to 800×480 in `App`.
- PCARS2 packets are identified by `mPacketType` byte at **offset 10** in the 12-byte header.

## Screenshots

The only images committed to the repo are the handful used by `README.md`, which
live in `docs/` (e.g. `docs/menu.png`, `docs/formula1_race.png`). The brand logos
live in `src/dashboard/images/`.

`take_screenshots.py` renders a full preview gallery of every dashboard config
headlessly using mock telemetry, writing PNGs to `screenshots/` — a scratch
directory that is **gitignored and never committed**. Run it from the project root
to preview a visual change:

```bash
python take_screenshots.py
```

When a change alters one of the images shown in the README, regenerate and copy the
relevant file(s) from `screenshots/` into `docs/` so the README stays current. Never
write screenshots to `/tmp`, the scratchpad, or any other location.

## Documentation Sync

CLAUDE.md and ROADMAP.md describe planned work as well as current state, and both are loaded as context by AI tooling — stale claims actively mislead future sessions.

- When implementing anything documented as "planned" / "not yet implemented" in CLAUDE.md, ROADMAP.md, or `docs/`, update that documentation **in the same change**.
- Keep each fact in exactly one place; reference other sections rather than duplicating lists (duplicated checklists always drift apart).

## Versioning & Changelog

Every notable code change (feature, fix, removal, or rename) must:

1. Bump the version in `src/version.py`: **minor for new features** (`0.1.5` → `0.2.0`), **patch for fixes to existing features** (`0.2.0` → `0.2.1`). A change containing both is a feature → minor. This rule is shared with the companion app (its `APP_VERSION` in `main.py`) — the two apps version independently but follow the same convention (agreed 2026-07-07).
2. Add a new `## [x.y.z] - YYYY-MM-DD` section to `CHANGELOG.md` (use today's date, placed above the previous version entry), with `### Added` / `### Fixed` / `### Changed` / `### Removed` subsections following the existing Keep a Changelog format.

Bump the major version only when the user explicitly calls out a larger milestone (e.g. a rewrite).

## Git Commits

**Always confirm with the user before committing**, even in auto mode. Never create a commit without explicit approval. This applies especially on the Pi where changes could affect the auto-start behaviour.
