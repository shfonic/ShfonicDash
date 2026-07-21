# Track map format & sync API

Recorded circuit maps live in `tracks/` as `<game>_<track>.json` (slugged), written by
the [track recorder](../src/core/track_recorder.py) and read by the HTML map utility
(`track_viewer.html`, in the **ShfonicDashTracks** repo), the companion's track editor,
and `sessionlog.trackmap` — which places Race Engineer Notes and share-text events
against the `sections` list below ("at Turn 3, before the apex") instead of a bare lap
distance. This is the canonical description of the on-disk shape and the LAN sync API.

## File shape

One JSON object per track (`TrackMap.to_dict`). Coordinates are world metres in the
recorder's game-agnostic convention: **X / Z horizontal, Y up** (elevation). Lines are
`[[x, z], …]`.

The circuit geometry is **shared across all car classes**; the racing line and its
gears are **per class**, so those live in a `lines` map keyed by `car_class` — one
profile per class, each carrying its own `gears`.

**F1 classes share the same line but not the same gears.** In the F1 titles the
F1, F2 and 2026 lines differ by under a metre (recording noise), but the gears
differ (2026 super-clipping to recharge the battery uses a lower gear at some
corners). So each F1 class gets its **own profile** — the line copied across, the
gears filled per class. `trackmap.resolve_line(game, car_class)` returns the
class's own entry; only when a class has **no profile yet** does it fall back to a
sibling's line (shared-line games only, geometry alone — never another class's
gears). Games with real class variety (PC2/GT7/Forza) are absent from
`_SHARED_LINE_GAMES`, so a missing class there resolves to nothing rather than
borrowing a line.

| Key | Type | Notes |
|---|---|---|
| `format_version` | int | `FORMAT_VERSION` (currently `1`) |
| `game` | str | source game id, e.g. `f1_25` |
| `track` | str | track name from telemetry, e.g. `Melbourne` |
| `game_track_length_m` | float | length from the game, for a sanity check |
| `notes` | str | free-text track notes (e.g. "missing F2 line"), all classes |
| `orientation` | float | **cosmetic** display rotation in degrees (0 = north-up, as recorded); turns every top-down map view, coordinates untouched *(optional, default 0)* |
| `created` | str | ISO-8601 UTC, stamped once at first save; kept across edits *(optional)* |
| `updated` | str | ISO-8601 UTC, refreshed on every save/edit *(optional)* |
| `author` | str | who recorded it — from `config.json` `"author"`; preserved on edits, not editable in the utility *(optional)* |
| `left_edge` / `right_edge` | list[400] | track edges, resampled to a common distance-station grid *(shared)* |
| `pit_lane` | list | open polyline (entry → exit), RDP-simplified; box stop speed-gated out *(shared)* |
| `sf_line` | dict | `{"pos": [x, z], "heading": rad}` — the start/finish line *(shared)* |
| `sectors` | list | `[{"index", "pos": [x, z], "lap_dist_m"}]` — boundary *positions* (for colourising) *(shared)* |
| `sections` | list | labelled corners/straights/complexes — **added by the viewer/companion**, see below *(shared)* |
| `lines` | dict | **per car class**: `{car_class: {racing_line, racing_attempts, gears, notes}}`, see below |

### `lines` (per car class)

Each class present gets one entry. The recorder only creates an entry for the class you
drove, but for the F1 titles — where every class shares the same line — all three F1
profiles (`formula1`, `formula1_2026`, `f2`) are seeded from that one line and differ only
in `gears`, so a class you haven't driven can still be present (line copied, `gears` null).
Re-driving one class never touches another, or the shared geometry.

```jsonc
"lines": {
  "formula1_2026": {
    "racing_line": [[x, z], …],   // list[400], median-averaged over racing_attempts laps
    "racing_attempts": 3,          // how many laps it was averaged from
    "gears": null,                 // suggested gear per line station — added later via the
                                   //   map utility, NEVER recorded live (see below); null until set
    "notes": ""                    // free-text notes for this class's line
  }
}
```

**Gears are never captured by the recorder** — during a recording you drive slower to hold
the line, so the live gear would be wrong. The slot stays `null` until filled in the map
utility.

### `orientation` (display rotation)

A **purely cosmetic** rotation, in degrees, applied to every top-down map view of
the track (the Pi corner thumbnails and history maps, the web companion minimaps,
and both HTML viewers). It exists because a recorded circuit's north-up framing is
often awkward on the 7" screen or a phone; the driver can rotate it to a more
legible orientation in the map utility without ever touching the recorded world
coordinates. Because it only rotates the *drawn* geometry, arc-length distances,
`sections` lookups and gears are unaffected. Every renderer applies the same
`sessionlog.trackmap.rotate_xz(points, orientation)` (the two HTML viewers apply
the identical rotation as an SVG `rotate()` on the scene group) so the Pi, the web
companion, the Pythonista companion and the browser viewers all agree. Absent or 0
means north-up, exactly as before. The recorder never sets it (it is not a driven
quantity); the map utility is where it is edited, and it is carried through
line/pit re-drives untouched.

### `sections` (labels)

Corner/straight labels are **embedded in the track file** (since v0.19.0 — no sidecar).
Each is a distance span in metres from the S/F line; a section wraps across S/F when
`start_m > end_m` (the main straight), and sections may overlap.

```jsonc
{
  "turn": "1",           // turn number (string; may be "1-2"); corner only
  "name": "Turn 1",      // common name; optional on a corner, required otherwise
  "type": "corner",      // corner | straight | chicane | complex | other
  "start_m": 100,        // span start (m from S/F)
  "end_m": 240,          // span end   (m from S/F); < start_m ⇒ wraps across S/F
  "apex_m": 175,         // optional apex station (corner only), within the span
  "severity": "med",     // optional: low | med | high (corner only)
  "overtake": "yes"      // optional: yes | no (corner / straight)
}
```

Fields are type-specific — the editor shows and validates only those that apply:

| Field | corner | chicane | complex | straight | other |
|---|:--:|:--:|:--:|:--:|:--:|
| `turn` | ✓ | – | – | – | – |
| `name` | optional | required | required | required | required |
| `apex_m` · `severity` | ✓ | – | – | – | – |
| `overtake` | ✓ | – | – | ✓ | – |
| `members` | – | optional | required | – | – |

A **`chicane`** and a **`complex`** are *grouping* types: they name a corner sequence and
list the corners they group by turn in `members`; those member corners exist in their own
right — the group overlays them. A `complex` must list its members; a `chicane` may or may
be a bare named span like "Bus Stop".

**Gear is not a section field** — it's car-specific (an F1 car, F2 and a GT3 take the same
corner in different gears), so it lives per class in `lines[car_class].gears`, not on the
shared, car-agnostic section. (Severity and overtake are roughly car-agnostic, so they stay
on the section.)

```jsonc
{ "name": "Maggots/Becketts/Chapel", "type": "complex",
  "start_m": 4200, "end_m": 4750, "members": ["10", "11", "13"] }
```

**DRS / override zones are not a section type.** DRS is regulation-specific (F1 25 / F2; the
2026 cars replace it with active aero + a manual override), whereas `sections` is shared,
car-agnostic geometry — so DRS/override zones belong in the (planned) per-car-class **Track
profiles** layer (see ROADMAP), not here.

The recorder never writes `sections`; it only carries them through when a saved map is
re-edited. The labeler and companion populate them.

## Sync API

Served by the same authenticated LAN server as session logs
([`core/log_server.py`](../src/core/log_server.py), port `8765`). Every request needs the
**pairing code** (DATA tab) as `Authorization: Bearer <CODE>` — fail-closed, no token ⇒
401. `tracks_dir` is supplied via `LogServer.set_tracks_dir`.

| Method & path | Purpose |
|---|---|
| `GET /tracks/index.json` | List saved maps: `{tracks: [{filename, url, game, track, car_classes, game_track_length_m, has_pit, section_count, has_notes, author, updated, sha, bytes}], server_time}` (`sha` = sha256 of the file, so a client can detect a changed copy even when `updated` wasn't bumped) |
| `GET /tracks/<file>.json` | Download one map (raw track JSON) |
| `PUT /tracks/<file>.json` | Upload/replace a map — companion / map-utility edits |

`car_classes` is the list of classes with a racing line (from `lines`). `PUT` validation:
filename `^[A-Za-z0-9][A-Za-z0-9_-]*\.json$` (no path separators), body ≤ 1 MB, valid JSON,
an object with `format_version` and at least one of `left_edge` / `right_edge` / `lines` /
`sections`. Success returns `201 {ok: true, filename}`.

### Examples

```bash
CODE=ABCD1234
curl -H "Authorization: Bearer $CODE" http://<pi>:8765/tracks/index.json
curl -H "Authorization: Bearer $CODE" http://<pi>:8765/tracks/f1-25_melbourne.json -o melbourne.json
# …edit melbourne.json (e.g. in the map utility), then push it back:
curl -T melbourne.json -H "Authorization: Bearer $CODE" \
     http://<pi>:8765/tracks/f1-25_melbourne.json
```

The map utility's (`track_viewer.html`, in the ShfonicDashTracks repo) **Download** button
writes a full `<game>_<track>.json`, so its output can be `PUT` straight back with no
reshaping.

## Future considerations

### Track variants / layouts

Some games ship several layouts of the same physical circuit — PC2 has Brands Hatch
*Indy* vs *GP*, Silverstone *National* vs *Grand Prix*, etc.; Forza Motorsport likely the
same. A map's identity is the `(game, track)` pair — [`find_map`](../src/sessionlog/trackmap.py)
matches on the file's own `game`/`track` fields (case-insensitive), **not** a parsed slug —
so **two layouts are already two distinct maps as long as their `track` string differs**. No
schema change (no `variant`/`config` subtype, no `FORMAT_VERSION` bump) is needed: fold the
layout into the `track` name (e.g. `"Brands Hatch GP"`). `game_track_length_m` doubles as a
sanity guard against a layout mismatch (Indy ≈ 1.9 km vs GP ≈ 3.9 km).

A structured subtype field buys little: the recorder could only learn the layout from the
same telemetry string it would otherwise put in the name, and it would cost a format bump, a
triple-key match, an index column, and filename-collision handling.

The real dependency is **what the game reports as the track-name string**, and that only
matters once these games can be recorded at all:

- **F1 25/26** — the only source with both world position *and* an automatic track name.
- **PC2 / Forza** — emit neither world position nor a track name today, so recording isn't
  wired up; when it is, verify the reported track string against a `--record` capture and, if
  the game doesn't distinguish layouts itself, append the layout to `track` at record time.
- **GT7** — the packet *does* carry world position (offset `0x04`, per the Nenkai/PDTools
  layout), but we don't parse it yet and the packet has **no track name at all**, so the
  driver would name the track (and its layout) by hand regardless.

**Clients.** The **Pythonista companion app** (v0.33.0+) is a full client of this API: its
*Tracks* screen `GET`s the index, downloads maps into an offline cache, edits them in the
embedded `track_viewer.html` (the same ShfonicDashTracks utility, hosted in a WebView), and
`PUT`s the edits back on the next sync. So this endpoint is now a two-way sync channel for
track maps, mirroring the session-log flow — not just a download.
