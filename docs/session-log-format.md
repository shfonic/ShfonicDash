# Session Log Format

Shfonic Dash writes one CSV file per session type into the `logs/` directory at the project root. The Pythonista companion app (and any other consumer) can fetch these files via the Share Logs HTTP server (`GET /index.json`, `GET /<filename>.csv`).

---

## File Naming

```
session_YYYYMMDD_HHMM_<label>.csv
```

| Part | Example | Meaning |
|------|---------|---------|
| `YYYYMMDD` | `20260617` | Date the session file was created |
| `HHMM` | `1430` | Local time the session file was created (24h) |
| `<label>` | `race` | `session_subtype` when the session has one, otherwise `session_type` (see values below) |

**Example:** `session_20260617_1430_race.csv`, `session_20260712_1405_sprint_qualifying.csv`

A new file is opened whenever the session type or subtype changes (e.g. practice → qualifying → race). Returning to the same session type later in the day produces a new file with a later timestamp. If two files would collide on the same minute, a numeric suffix is appended (`session_20260617_1430_race_2.csv`) — **do not parse the label from the filename**; read the `S` rows instead.

### Session type values

`session_type` is the coarse category — it decides which dashboard is shown and how the session is analysed at the top level:

| Value | Meaning |
|-------|---------|
| `practice` | Free practice |
| `qualifying` | Qualifying / superpole (including Sprint Shootout — see subtype) |
| `race` | Race |
| `hotlap` | Time trial / hot lap |

### Session subtype values

`session_subtype` (v0.1.133+) is a finer-grained variant. It is an **empty string** for a plain session of its type, so the rule for consumers is:

```python
label = meta.get("session_subtype") or meta["session_type"]
```

| `session_type` | `session_subtype` | Meaning |
|----------------|-------------------|---------|
| `qualifying` | `sprint_qualifying` | F1 Sprint Shootout (SQ1/SQ2/SQ3, short and one-shot variants) |
| *(any)* | *(empty)* | Plain session of its `session_type` |

More subtypes may be added (e.g. `sprint_race` once the raw id a sprint race broadcasts has been confirmed — see `session_type_raw`). Consumers should treat any unrecognised subtype as its `session_type` for analysis purposes, while using the subtype string for display/grouping.

---

## File Format

Files use a **typed-row CSV** format. The first column of every row is a row type identifier; the meaning of subsequent columns depends on the type.

### Row types

| Type | Description |
|------|-------------|
| `S` | Session metadata — key/value pair. All `S` rows appear first. |
| `GH` | Column header for `G` rows — written immediately before the first `G` row. |
| `G` | Starting grid — one row per participant, written once from the first participant snapshot. For a race this is the starting grid; for qualifying/practice it is the participant roster. |
| `H` | Column header for `L` rows — written immediately before the first `L` row. |
| `L` | Lap data — one row per completed lap, in chronological order. |
| `RH` | Column header for `R` rows — written immediately before the first `R` row (at session close). |
| `R` | Final standings — one row per participant, written once when the session file closes. |
| `EH` | Column header for `E` rows — written immediately before the first `E` row. |
| `E` | In-session event — written in real time as events occur, interleaved between `L` rows. |
| `Z` | Session summary statistic — key/value pair, written once after `R` rows at session close. |
| `D` | Driver debrief answer — `D,<question_id>,<answer_id>`. Appended after the `Z` rows once the session has closed (the post-session questionnaire runs after the summary screen), so a file may gain `D` rows after first being read. v0.6.0+ |
| `P` | Racing-line offset profile for one completed lap — `P,<lap_num>,<o0>,<o1>,…`. Written interleaved with `L` rows (after the lap's `L` row) for any F1 session at a track with a recorded racing line (all session types since v0.61.0; F1 hotlap/qualifying only in v0.26.0–v0.60.x). v0.26.0+ |
| `F` | Driver-selected session focus — `F,<focus_id>`. Written once, near the top of the file, when the driver taps a focus chip on the pre-session card. The chip set is session-type-specific: lap sessions offer `faster`, `consistency`, `clean`, `just_drive`; races offer `clean_race`, `positions`, `race_pace`, `manage` (v0.62.0+). The summary reports how the session tracked against it. Absent when no focus was chosen. v0.35.0+ |
| `O` | Tracked objective — `O,<type>,<target>,<baseline>`. Written once, near the top of the file, when the pre-session NEXT GOAL card is shown (auto-committed — unlike the `F` focus chip these need no tap). One row per data-backed objective. The summary/history browser evaluate each against the session and report met / missed / still-open. Absent when there was no history to derive objectives from. v0.55.0+ |

Additional row types may be introduced in future versions. Parsers should silently skip any row type they do not recognise.

### Tracked objectives (`O` rows, v0.55.0+)

Data-backed goals the pre-session card set for the session, derived from the driver's history at the same combo (`sessionlog.goals`). The mission set is **session-type-specific** (v0.62.0+): lap sessions (hotlap/qualifying/practice) get the lap-time objectives; a race gets craft/position objectives instead. Written as `O,<type>,<target>,<baseline>`; `target`/`baseline` are type-interpreted strings (a lap time, a lap count, a corner id, …) and an empty cell means "not applicable". Types (stable ids in `sessionlog/objectives.py`): `clean_streak` (target = N consecutive clean laps; baseline = prior best streak), `no_flashbacks` (baseline = prior rewind count), `beat_time` (target = a lap time to beat, seconds), `convert_sectors` (target = the theoretical to reach), `tighten_spread` (baseline = prior clean-lap spread), `corner_limits` (target = corner label; baseline = prior track-limit warnings there), `corner_line` (target = corner label; baseline = prior line deviation in metres — F1 mapped tracks with line profiles only), `reduce_assists` (baseline = names of assists used last time), `finish_clean` (race — target = 0 incidents; baseline = prior contacts + penalties, v0.62.0+), `gain_positions` (race — baseline = places lost from the grid last race, v0.62.0+), `learn_track` (first visit — no target/baseline; scored from the ordered session's clean-lap pace trend, i.e. did lap times come down as the driver learned the layout. Written from the first-visit baseline card for lap sessions only, v0.64.0+). Parsers expose them as `session["objectives"] = [{"type", "target", "baseline"}, …]`; `sessionlog.objectives.evaluate_all()` scores them against the finished session (the `learn_track` verdict needs `progression_facts=` passed in). Consumers must tolerate unknown types (newer apps may add objectives).

### Driver debrief (`D` rows, v0.6.0+)

The dashboard asks 2–3 multiple-choice questions after a session closes (skippable; `debrief_enabled` setting). Question and answer ids are stable identifiers defined in `sessionlog/debrief.py`. The questionnaire is **session-type-specific** (v0.62.0+). `feeling` (`great`/`good`/`neutral`/`frustrated`/`tired`) is always asked. The goal question is asked **only when no pre-session focus was committed** (no `F` row, or `just_drive`): `goal` (`learn_track`/`pace`/`consistency`/`race_prep`/`setup`/`fun`) for lap sessions, or `goal_race` (`finish_clean`/`positions`/`points`/`racecraft`/`pace`/`fun`) for races. Then at most one reaction question, chosen by session type:

- **Race** — `contact_fault` (a contact was logged), else `penalty_cause` (a penalty was logged), else `positions_lost` (finished behind the grid slot), else `race_start`.
- **Qualifying** — `pb_change` (new PB), else `theo_gap`, else `quali_cost` (mistakes but no clean lap put together).
- **Hotlap/TT** — `pb_change`, else `theo_gap`, else `rewind_cause`, else `corner_trouble`/`invalid_cause`.
- **Practice** — `pb_change`, else `corner_trouble` (v0.57.0+ — a corner dominated the track-limit warnings; its display text names that corner, but the stored answer is the cause only), else `invalid_cause`, else `rewind_cause`, else `theo_gap`.

Parsers expose them as `session["debrief"] = {question_id: answer_id}`; repeated ids keep the last value. Consumers must tolerate unknown ids (newer apps may add questions).

### Parsing

```python
meta    = {}
grid    = []   # starting grid / participant roster
laps    = []   # one dict per completed lap
results = []   # final standings
events  = []   # in-session events (rewinds, pit stops, ...)

gh = hh = rh = eh = []   # column headers for G, L, R, E rows

summary = {}   # session summary stats

for row in csv.reader(f):
    t = row[0]
    if   t == 'S':  meta[row[1]] = row[2]
    elif t == 'GH': gh = row[1:]
    elif t == 'H':  hh = row[1:]
    elif t == 'RH': rh = row[1:]
    elif t == 'G':  grid.append(dict(zip(gh, row[1:])))
    elif t == 'L':  laps.append(dict(zip(hh, row[1:])))
    elif t == 'R':  results.append(dict(zip(rh, row[1:])))
    elif t == 'EH': eh = row[1:]
    elif t == 'E':  events.append(dict(zip(eh, row[1:])))
    elif t == 'Z':  summary[row[1]] = row[2]
    # silently ignore unknown row types
```

---

## Session Metadata (`S` rows)

| Key | Type | Notes |
|-----|------|-------|
| `version` | integer | Log format version. Currently `1`. Increment on breaking changes. |
| `app_version` | string | Shfonic Dash version that wrote the file (e.g. `0.1.134`). For debugging — lets consumers correlate data quirks with known fixes (e.g. spurious pit-stop rewinds before `0.1.133`). v0.1.134+ (missing in older files) |
| `started_at` | string | ISO 8601 local datetime the session file was created (e.g. `2026-06-17T14:30:00`). No timezone — Pi local time. |
| `game` | string | Game identifier (see values below) |
| `session_type` | string | `practice`, `qualifying`, `race`, or `hotlap` |
| `session_subtype` | string \| empty | Finer-grained variant, e.g. `sprint_qualifying`. Empty for a plain session of its type. v0.1.133+ (missing in older files — treat as empty) |
| `session_type_raw` | integer \| empty | The game's raw session id (F1: `m_sessionType`). Diagnostic — used to map ids the dashboard doesn't classify yet. Empty for games that don't provide one. v0.1.133+ |
| `car_class` | string | Car class (see values below) |
| `car_name` | string \| empty | Team name (F1: e.g. `McLaren`, `Ferrari`). Empty for games that don't expose it. |
| `driver_name` | string \| empty | Player's driver name (F1: e.g. `PIASTRI`). Populated from the participant packet; empty for games that don't expose it. |
| `track` | string \| empty | Circuit name (e.g. `Silverstone`, `Monaco`). Populated by F1 2025; empty for other games. |
| `team_id_raw` | integer \| empty | The game's raw team id for the player (F1: participant `teamId`). Diagnostic — used to map ids `car_name` can't resolve yet (e.g. 2026 Season Pack teams). Empty for games that don't provide one. v0.2.0+ |
| `weather` | string \| empty | `clear`, `light_cloud`, `overcast`, `light_rain`, `heavy_rain`, `storm`, or `snow`. F1 2025 + Project CARS 2 (PC2 can't distinguish cloud, so dry is always `clear`); empty for Forza and older files. A new S row is written on every change, so multiple rows record a dynamic-weather session; the last value is the session's final state. v0.2.0+ |
| `air_temp` | integer \| empty | Ambient temperature °C at session open. F1 2025 + Project CARS 2. v0.2.0+ |
| `track_temp` | integer \| empty | Track surface temperature °C at session open. F1 2025 + Project CARS 2. v0.2.0+ |
| `line_ref` | integer \| empty | Present only when the session recorded racing-line offset profiles (`P` rows): the `racing_attempts` count of the racing line the offsets were measured against, so a later re-recording of that line is a detectable staleness signal. v0.26.0+ |

> **Note:** `car_name`, `driver_name`, `team_id_raw` and `weather` S rows may appear more than once in a file. The participant packet often arrives after the session file is opened (so the first S row may be empty), and weather changes mid-session. Subsequent S rows with the same key carry the newer value. **Parsers must use the last value for any repeated S key.**

---

## Lap Columns (`H`/`L` rows)

Each `L` row represents one completed lap.

| Column | Type | Unit | Notes |
|--------|------|------|-------|
| `lap_num` | integer | — | Lap number that completed (1-based) |
| `lap_time` | float | seconds | Total lap time |
| `s1` | float \| empty | seconds | Sector 1 time. Empty if unavailable |
| `s2` | float \| empty | seconds | Sector 2 time (standalone, not cumulative). Empty if unavailable |
| `s3` | float \| empty | seconds | Sector 3 time (standalone). Empty if unavailable |
| `tyre_fl` | float \| empty | °C | Front-left tyre surface temp at lap end |
| `tyre_fr` | float \| empty | °C | Front-right tyre surface temp at lap end |
| `tyre_rl` | float \| empty | °C | Rear-left tyre surface temp at lap end |
| `tyre_rr` | float \| empty | °C | Rear-right tyre surface temp at lap end |
| `tyre_compound` | string \| empty | — | Compound name (see values below) |
| `fuel_remaining` | float \| empty | kg | Fuel remaining at lap end |
| `fuel_per_lap` | float \| empty | kg | Average fuel consumption per lap |
| `position` | integer \| empty | — | Race position at lap end. Empty in time trial / practice |
| `delta` | float \| empty | seconds | `last_lap − best_lap` at lap end. Positive = slower than PB. Empty if no best lap yet |
| `invalid` | integer | — | `1` if the lap was flagged invalid at any point (track limits, illegal shortcut, etc.), `0` otherwise |
| `rewinds` | integer | — | Number of F1 flashbacks / Forza rewinds used during this lap. `0` for a clean lap |
| `assist_tc` | integer | — | v0.40.0+. Highest traction control level reached during the lap: `0`=off, `1`=medium, `2`=full. F1 only, `0` for other games |
| `assist_abs` | integer | — | v0.40.0+. Highest ABS level reached during the lap: `0`=off, `1`=on. F1 only |
| `assist_racing_line` | integer | — | v0.40.0+. Highest dynamic racing line level reached during the lap: `0`=off, `1`=corners only, `2`=full. F1 only |
| `assist_steering` | integer | — | v0.40.0+. Highest steering assist level reached: `0`=off, `1`=on. F1 only |
| `assist_braking` | integer | — | v0.40.0+. Highest braking assist level reached: `0`=off, `1`=on. F1 only |
| `assist_gearbox` | integer | — | v0.40.0+. Highest gearbox assist level reached: `0`=manual, `1`=manual + suggested gear, `2`=auto. F1 only |
| `assist_pit` | integer | — | v0.40.0+. Highest pit assist level reached: `0`=off, `1`=on. F1 only |
| `assist_pit_release` | integer | — | v0.40.0+. Highest pit release assist level reached: `0`=off, `1`=on. F1 only |
| `assist_ers` | integer | — | v0.40.0+. Highest ERS assist level reached: `0`=off, `1`=on. F1 only |
| `assist_drs` | integer | — | v0.40.0+. Highest DRS assist level reached: `0`=off, `1`=on. F1 only |

All ten `assist_*` columns hold the **highest (most-assisted) level seen at any point
during the lap**, not a snapshot at lap end — toggling an assist on mid-lap and back
off before the line still logs it as used. Absent in files older than v0.40.0;
parsers should treat a missing column as unknown, not as `0`/off.

### Empty values

Fields are written as an empty string (`""`) when the data is not available for that game/session. Consumers should treat empty strings as `null`/`None`.

### Sector times

`s1`, `s2`, and `s3` are **standalone** times (i.e. each sector individually), not cumulative. They are captured at sector boundaries from the telemetry stream and may be missing (`""`) if the sector data wasn't received before the lap ended — this is more common in the first lap of a session.

---

## Grid Columns (`GH`/`G` rows)

Written once per file, immediately before the first `L` row, from the first participant snapshot received from the game. Not written for `hotlap` sessions (F1 Time Trial broadcasts ghost/rival slots as nameless cars all at position 1, so there is no meaningful grid).

| Column | Type | Notes |
|--------|------|-------|
| `position` | integer | Starting position. For a race this is the grid slot; for qualifying/practice this is the initial order (may be arbitrary before any timed laps). |
| `race_num` | integer \| empty | Car race number. Empty if not available. |
| `name` | string | Driver name as broadcast by the game. |

---

## Standings Columns (`RH`/`R` rows)

One set of `R` rows is written once when the session file closes (session type changes or app exits), showing the final standings. Only populated by games that broadcast multi-car data (F1 2025); no `R` rows are written for Forza or PCARS2, nor for `hotlap` sessions (see Grid Columns above).

| Column | Type | Notes |
|--------|------|-------|
| `position` | integer | Current position in the session |
| `race_num` | integer \| empty | Car race number (e.g. `44`, `1`). Empty if not available |
| `name` | string | Driver name as broadcast by the game |
| `best_lap` | float \| empty | Best lap time this session in seconds. Empty if no clean lap completed |
| `race_time` | float \| empty | Classified total race time in seconds, including time penalties (from the F1 Final Classification packet). Only written in `race` sessions for cars that finished; empty for DNF/DSQ/retired cars, non-race sessions, and races left before the classification packet arrives. **The game sends this packet at the official results screen, after the podium/champagne sequence** — quitting to the menu during the celebrations is too early and leaves `race_time` (and the final lap's `L` row) unwritten (confirmed 2026-07-05). From v0.1.134 the dashboard shows a banner at race end: amber "wait for classification" until the packet arrives, green "results saved" once it has |

### Delta semantics

`delta` is `last_lap_time − session_best_lap_time` computed at the moment the lap completes. A positive value means the lap was slower than the session PB; negative means faster. This is the **completed-lap** delta, not a live in-lap delta.

**Files written before v0.44.0 have an incorrect stored `delta` value** (a
live-telemetry race condition — see CHANGELOG). `sessionlog.parser` no
longer trusts the stored column: it recomputes `delta` from the raw laps on
every parse, so the Pi/companion display is correct for old files too
without any migration. A consumer reading the CSV directly (not through
`sessionlog.parser`) should recompute it the same way — best CLEAN
(valid, no rewinds) lap time so far — rather than trust the column as
written.

---

## Reference Values

### Tyre compounds

| Value | Description |
|-------|-------------|
| `Soft` | F1 soft |
| `Medium` | F1 medium |
| `Hard` | F1 hard |
| `Inter` | F1 intermediate |
| `Wet` | F1 full wet |
| `DHE` | Forza hard compound |
| `DHD` | Forza default hard |
| *(empty)* | Game does not expose compound data |

### Car classes

| Value | Description |
|-------|-------------|
| `formula1` | F1 2025 car |
| `formula1_2026` | F1 2026 regulation car (DLC) |
| `f2` | Formula 2 |
| `formula_ford` | Formula Ford (PC2) |
| `gt3` | GT3 class |
| `gt4` | GT4 class |
| `fh6` | Forza Horizon (FH4 / FH5 / FH6) |
| `fm` | Forza Motorsport (FM7 / FM2023) |
| `gt7` | Gran Turismo 7 |

### Game identifiers

| Value | Game |
|-------|------|
| `f1_25` | F1 2025 (EA Sports) |
| `pcars2` | Project CARS 2 |
| `fh6` | Forza Horizon series |
| `fm` | Forza Motorsport series |
| `gt7` | Gran Turismo 7 |

---

## Example File

```csv
S,version,1
S,app_version,0.1.134
S,started_at,2026-06-17T14:30:00
S,game,f1_25
S,session_type,race
S,session_subtype,
S,session_type_raw,15
S,car_class,formula1
S,car_name,
S,driver_name,
S,track,Silverstone
S,car_name,McLaren
S,driver_name,PIASTRI
GH,position,race_num,name
G,1,44,Hamilton
G,2,16,Leclerc
G,3,1,Verstappen
EH,lap_num,lap_time,type,distance,t,detail
E,2,38.115,collision,1740.2,131.6,VERSTAPPEN
E,2,44.712,rewind,,138.2,
H,lap_num,lap_time,s1,s2,s3,tyre_fl,tyre_fr,tyre_rl,tyre_rr,tyre_compound,fuel_remaining,fuel_per_lap,position,delta,invalid,rewinds,assist_tc,assist_abs,assist_racing_line,assist_steering,assist_braking,assist_gearbox,assist_pit,assist_pit_release,assist_ers,assist_drs
L,1,91.234,28.500,29.600,33.134,90.0,88.0,85.0,87.0,Medium,40.1,2.1,3,0.0,0,0,0,0,0,0,0,0,0,0,0,0
L,2,90.887,28.210,29.441,33.236,89.0,87.0,84.0,86.0,Medium,38.0,2.1,2,-0.347,0,1,0,0,0,0,0,0,0,0,0,0
E,3,5.123,pit_in,88.2,192.4,
E,3,28.441,pit_out,441.0,215.7,
E,3,55.310,overtake,3105.8,242.6,LECLERC
L,3,91.102,28.300,29.500,33.302,91.0,89.0,86.0,88.0,Hard,36.0,2.1,2,0.215,0,0,0,0,0,0,0,0,0,0,0,0
RH,position,race_num,name,best_lap,race_time
R,1,44,Hamilton,90.812,
R,2,1,Verstappen,90.887,
R,3,16,Leclerc,91.023,
Z,fastest_lap,90.887
Z,avg_clean_lap,91.074
Z,std_dev,0.178
Z,invalid_laps,0
Z,rewinds,1
Z,spins,
```

---

## Share Logs HTTP API

When **Share Logs** is enabled in the settings overlay (DATA tab, game-menu context only), the Pi serves `logs/` on port **8765**.

### `GET /index.json`

Returns a JSON object listing all available session files.

```json
{
  "sessions": [
    {
      "filename":     "session_20260617_1430_race.csv",
      "url":          "/session_20260617_1430_race.csv",
      "version":      1,
      "session_type": "race",
      "session_subtype": "",
      "car_class":    "formula1",
      "car_name":     "Red Bull Racing",
      "track":        "Silverstone",
      "weather":      "clear",
      "air_temp":     "21",
      "track_temp":   "34",
      "date":         "2026-06-17T14:30:00",
      "lap_count":    28
    }
  ],
  "server_time": "2026-06-17T15:45:00"
}
```

Sessions are listed newest-first. `version`, `session_type`, `session_subtype`, `car_class`, `car_name`, `track`, `weather`, `air_temp`, and `track_temp` are read from the `S` rows in the CSV. `lap_count` is the number of `L` rows. `car_name` and `track` may be empty strings for games that don't expose that data; `session_subtype` is empty for plain sessions and for files written before v0.1.133; the weather fields (v0.2.0+) are empty strings for older files and Forza. When repeated `S` rows exist (e.g. weather changes), the listed value is the last one in the file.

### Authentication (v0.7.0+)

Every endpoint requires the pairing token shown on the dashboard's SETTINGS → DATA tab ("PAIRING CODE", generated once and stored as `api_token` in `config.json`; delete the key to regenerate and re-pair). Send it as `Authorization: Bearer <code>` (case-insensitive; `X-Api-Key: <code>` also accepted). Requests without it get `401` — the API is read/write, so unauthenticated LAN clients get nothing at all.

### `GET /<filename>.csv`

Returns the raw CSV file. `Content-Type: text/csv; charset=utf-8`.

### `PUT /<filename>.csv` (v0.7.0+)

Pushes a session CSV **to** the dashboard — used by the companion for sessions the Pi never logged itself (AC/ACC screenshot imports). The filename must match `session_*.csv`, the body must be a typed-row CSV (starts with `S,`), and uploads are capped at 2 MB. Same-named files are the same session, so re-pushing overwrites harmlessly. Responds `201 {"ok": true, "filename": ...}`; pushed files are marked synced (they never count toward the sync badge) and the records index picks them up on its next scan.

### Share window (v0.1.140+)

`/index.json` only lists sessions from the configured share window (Pi DATA tab: last 1 / 7 / 30 days, or ALL; default 7 days), judged by the date in the filename. This bounds what clients see — and the per-request work on the Pi — when `logs/` holds hundreds of sessions. Direct `GET /<filename>.csv` still works for any session regardless of the window, so a client that already knows a filename can always (re-)download it.

Session files themselves are **never deleted by age**: since v0.1.138 the `logs/` directory is the dashboard's own history/records database (prior bests, race-pace references, trends). Sessions with zero completed laps are deleted at session close (v0.1.140 — they were metadata-only noise), and sessions deleted from the Pi's history browser move to `logs/.trash/` (pruned after 30 days).

### Availability

The server runs while the game menu / settings overlay is open (with Share Logs or the web companion enabled), and otherwise stops during gameplay so it never consumes resources — unless the web companion is set to **ALWAYS** (see below), which keeps it up mid-session. Connect from the Pythonista app while the DATA tab is visible on the Pi.

## Web Companion HTTP routes (`/app`, v0.63.0+)

The same server (port 8765) also serves a browser mirror of the companion under `/app` — see [core/web_app.py](../src/core/web_app.py). These routes are **HTML**, not JSON, and use a **different auth path** from the API above: browsers can't send the `Authorization` header on a plain navigation, so they authorise off a session **cookie** instead.

- `GET /app?key=<token>` — pairing. A valid `key` (checked against `api_token`, case-insensitive) responds `302` to `/app` with `Set-Cookie: shfonic_web=<hmac>; HttpOnly; SameSite=Strict; Path=/app`, stripping the key from the URL/history. The cookie value is an HMAC of the pairing token — the raw token never lands in the cookie jar.
- Cookie-gated **GET** pages: `/app` (driver hub), `/app/driver`, `/app/sessions[?game=]`, `/app/browse[?g=&c=&t=&s=]` (records drill-down), `/app/favourites`, `/app/trophies`, `/app/trophy/<badge_id>` (badge detail — how-to + contributing sessions), `/app/journal`, `/app/settings`, `/app/tracks`, `/app/session/<file>.csv`, `/app/session/<file>.csv/share` (copy-to-clipboard share brief), `/app/session/<file>.csv/lines` (full line viewer — `404` when no racing-line data), `/app/track/<file>.json/map` (map editor), plus `/app/app.css`, `/app/img/<asset>.png` (helmet/logo assets) and `/app/status.json` (new-session poll). Without a cookie (and without a `key`) the pages return a friendly "scan the QR again" page (`200`, no data), not a raw `401`.
- Cookie-gated **POST** actions (browser forms/fetch, not the Bearer API): `/app/session/<file>.csv/favourite` (toggle favourite, `303`), `/app/driver/save` (save the driver profile), `/app/track/<file>.json/save` (write an edited track map, same validation as the Bearer `PUT /tracks/`).
- **Public** (no cookie, no key) home-screen assets — the browser fetches a Web App Manifest *without* credentials, so these sit outside the cookie gate; both are non-sensitive brand assets: `GET /app/manifest.webmanifest` (`application/manifest+json` — `name`/`short_name`/`display: standalone`/icon) and `GET /app/img/app-icon.png` (the app icon named by the manifest). `render_shell` also emits an `apple-touch-icon` link + `apple-mobile-web-app-title` so iOS "Add to Home Screen" installs a named, iconed, standalone app over plain HTTP (no service worker). The offline/PWA layer is a future phase.

The JSON/CSV API endpoints above stay **Bearer-only** — the web cookie never authorises them, and the API path never accepts the cookie. When `web_app_mode` is `off` (Pi DATA tab), `/app` returns a "web companion is off" page even while the server runs for Share Logs. The QR shown on the DATA tab encodes `http://<lan-ip>:8765/app?key=<token>` for one-scan pairing.

---

## Behavioural Notes

- **Forza reverse gear:** Forza's UDP format uses gear byte `0` for reverse and `11` for neutral (both parked neutral and mid-shift transient neutral). The dashboard shows `R` when the gear byte is `0` and `N` when it is `11`.
- **Rewind / flashback:** Two cases are detected. (1) *Mid-lap rewind* — `lap_number` stays the same but `lap_time` jumps backwards (beyond a small float-noise epsilon); pending sector state is cleared and `rewinds` is incremented on the in-progress lap. (2) *Start/finish crossing rewind* — `lap_number` decreases; the previously completed lap row is already written and a new row for the same lap number will be written when the player crosses the line again. If the same `lap_num` appears more than once, **take the last row** — it is the one the player chose to keep.
- **Restart lap (F1 Time Trial):** also jumps `lap_time` backwards on the same lap, but the car lands *before* the S/F line (negative lap distance, lap clock at 0) instead of mid-lap. Logged as a `restart` event, not counted in the lap's `rewinds` column — the attempt that eventually completes is a clean full lap. A restart also clears any pending invalid flag from the abandoned attempt.
- **Pit stops / garage visits (v0.1.133+):** entering the pits (practice tyre change, return to garage) teleports the car, which jumps `lap_time` backwards exactly like a flashback. While the game reports the car in the pits (plus the first tick after leaving), backwards jumps are swallowed — they produce **no** `rewind`/`restart` events and don't increment the `rewinds` lap column. The pit visit itself is recorded as a `pit_in`/`pit_out` pair. Lap completions still fire in the pit lane, so racing pit stops count laps normally. Files written before v0.1.133 contain spurious `rewind`/`restart` events around pit stops.
- **Lap 0 / out-laps:** Only laps where `lap_number ≥ 1` at the time of completion are logged. The first lap (outlap) is logged once it crosses the line if `last_lap > 0`.
- **Tyre temps at lap end:** The values captured are the surface temps from the last telemetry frame before the lap boundary, not an average over the lap.
- **Fuel:** `fuel_remaining` is a point-in-time snapshot, not averaged. `fuel_per_lap` is the game's own rolling average.
- **`car_name` and `track` at session open:** These `S` rows are written when the session file is first created. If the telemetry source hasn't yet received the relevant packets (participant data for `car_name`, session packet for `track`), these fields may be empty in the file even though the game is running.

---

## Event Columns (`EH`/`E` rows)

Events are written in real time as they occur, interleaved between `L` rows in chronological order (before the `L` row of the lap they happened on). If a session has no events, no `EH` or `E` rows are written.

| Column | Type | Notes |
|--------|------|-------|
| `lap_num` | integer | Lap number during which the event occurred |
| `lap_time` | float | Seconds elapsed in the current lap when the event occurred — use this to identify the track position (corner) |
| `type` | string | Event type (see values below) |
| `distance` | float \| empty | Metres around the lap when the event occurred (F1 only; empty when the source does not broadcast lap distance, or for events where the position is not meaningful) |
| `t` | float | Wall-clock seconds since the session file opened. v0.1.133+ (missing in older files). Monotonic — **use `t` for durations** (e.g. pit stop length = `t` of `pit_out` − `t` of `pit_in`). `lap_time` resets across pit teleports and lap boundaries, so `lap_time` differences can go negative |
| `detail` | string \| empty | Event-specific context, v0.1.135+. Other driver's name for `collision` / `overtake` / `overtaken`; `penalty_type:infringement[:other_driver]` for `penalty` (e.g. `time_penalty:corner_cutting_gained_time`, `warning:big_collision:VERSTAPPEN`). Empty for all other event types |

### Event types

| Value | Trigger |
|-------|---------|
| `rewind` | F1 flashback or Forza rewind activated. `lap_time` is the elapsed lap time at the moment of the rewind — maps directly to a track position. `distance` locates it on a track map (F1 only, v0.25.0+) |
| `restart` | F1 Time Trial "restart lap" — the in-progress attempt was abandoned and the car reset to the start line. Distinguished from a rewind by where the car lands: before the S/F line (negative lap distance / zero lap time) instead of mid-lap. `distance` is stamped (v0.25.0+) but is generally near-zero/negative and not placed on a track map |
| `invalid` | The in-progress lap was flagged invalid at this moment. `lap_time` and `distance` locate where on track the violation happened. An `invalid` with a `track_limit_warning` at the same lap_time was a track-limits violation |
| `track_limit_warning` | The game's cumulative corner-cutting warning counter incremented (F1) |
| `collision` | The player made contact with another car (F1 event packet, v0.1.135+). `detail` names the other driver. Fired for contact in either direction — it does not say who caused it |
| `penalty` | The player was given a penalty or warning by the stewards (F1, v0.1.135+). `detail` carries `penalty_type:infringement[:other_driver]` — infringements include collisions, corner cutting, track limits, pit lane speeding, etc. |
| `overtake` | The player passed another car (F1, v0.1.135+). `detail` names who was passed. Racecraft signal, not an incident |
| `overtaken` | Another car passed the player (F1, v0.1.135+). `detail` names who got by |
| `pit_in` | Car entered the pit lane. From the game's pit status where available (F1, v0.1.133+); from the pit limiter for other games |
| `pit_out` | Car left the pit lane (same source as `pit_in`) |
| `sc_deploy` | Safety Car deployed |
| `sc_clear` | Safety Car withdrawn (racing resumed) |
| `vsc_deploy` | Virtual Safety Car deployed |
| `vsc_clear` | Virtual Safety Car withdrawn (racing resumed) |

Expect exactly one `pit_in`/`pit_out` pair per pit visit from v0.1.133. Older files derived pit events from the pit limiter, which flaps while the car sits in the garage — they may contain doubled pairs and spurious `rewind`/`restart` events around pit stops (see Behavioural Notes).

`collision`, `penalty`, `overtake` and `overtaken` come from the F1 event packet and are only recorded when the **player** is involved — AI-vs-AI incidents are ignored. Each is stamped with the player's live `lap_time` and `distance` at the moment the event arrived, so they can be placed on a track map. A `collision` immediately followed by a `rewind` at a similar distance reads as "crashed, flashed back".

A session that begins in the garage (typical for practice/qualifying) opens with a `pit_in` at `t≈0`; the first `pit_out` marks the moment the car first leaves the pits.

### Why lap time and not race/session time?

`lap_time` tells you *where on the circuit* the event happened. A rewind at `lap_time=3.2` on Monaco means corner 1 (Sainte-Dévote), regardless of which lap or where in the race. Race time is harder to map to track position without additional reference data. The `t` column complements it for *when* / *how long* questions.

---

## Racing-line offset profile (`P` rows, v0.26.0+)

During any F1 session at a track that has a **recorded racing line for the driven
car class** (see [track-format.md](track-format.md)), the dashboard records how
far the player drove from that line and writes one `P` row per completed lap
(all session types since v0.61.0 — a race or practice run is as worth reflecting
on as a hotlap; hotlap/qualifying only before then):

```
P,<lap_num>,<o0>,<o1>,…,<oN-1>
```

Each `o` is the **signed perpendicular offset in decimetres** (metres × 10, integer)
between where the player drove and the racing line, sampled at the same `N`
evenly-spaced lap-distance **stations** as the racing line itself (so `o[i]`
lines up with `racing_line[i]`). The sign is **positive to the right of the
direction of travel**, negative to the left — where "right" is the line's tangent
rotated −90° in the (x, z) plane. Divide by 10 for metres.

A `P` row is written immediately after the `L` row of the lap it belongs to.
Rows are absent for any lap/session without a loaded racing line, and for every
game other than F1 (no world position). Consumers reconstruct the driven line
for a mini-map as `racing_line[i] + (o[i]/10)·n[i]`, where `n[i]` is the line's
unit right-hand normal at station `i`; `sessionlog.lines` does exactly this and
derives the corner-adherence coaching, the `on_the_line` achievement and the
player-vs-racing mini-map from these rows — the Pi and companion agree because
both read the same profile.

## Session Summary (`Z` rows)

One set of `Z` rows is written once at session close, after any `R` rows. Each `Z` row is a key/value pair.

| Key | Type | Notes |
|-----|------|-------|
| `fastest_lap` | float | Fastest lap time in the session (seconds), across valid and invalid laps |
| `avg_clean_lap` | float \| empty | Mean lap time of valid laps only. Empty if no clean laps completed |
| `std_dev` | float \| empty | Sample standard deviation of clean lap times. Empty if fewer than 2 clean laps |
| `invalid_laps` | integer | Number of laps flagged invalid during the session |
| `rewinds` | integer | Number of rewinds/flashbacks used (restarts excluded) |
| `restarts` | integer | Number of "restart lap" resets (F1 Time Trial) |
| `spins` | empty | Reserved — not currently populated (requires motion data not yet decoded) |

### Parsing Z rows

```python
summary = {}
for row in csv.reader(f):
    if row[0] == 'Z':
        summary[row[1]] = row[2]

fastest  = float(summary['fastest_lap'])
avg      = float(summary['avg_clean_lap']) if summary['avg_clean_lap'] else None
std_dev  = float(summary['std_dev'])       if summary['std_dev']       else None
```
