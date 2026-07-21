# Shfonic Dash HTTP API Reference

Shfonic Dash runs a small **pure-standard-library** HTTP server on the Raspberry Pi so that a
companion or third-party app on the same LAN can pull and push session logs, track maps and the
driver profile. This document is the reference for building your own client against that API.

It is derived from the server implementation in
[`src/core/log_server.py`](../src/core/log_server.py); the CSV/JSON payload shapes are documented
in [session-log-format.md](session-log-format.md) (sessions) and
[track-format.md](track-format.md) (track maps).

---

## Overview

- **Base URL:** `http://<pi-ip>:8765` — the Pi's LAN IP on fixed port **8765**.
- **Transport:** plain HTTP (no TLS). LAN-only; there is no cloud component.
- **Read/write:** `GET` to pull, `PUT` to push. Every request is authenticated (see below).
- **Content:** the JSON/CSV API returns `application/json`, `text/csv` or
  `application/json` (track maps). A separate `/app` tree serves the browser web companion as HTML
  (summarised at the end — not the focus of this reference).

### When the server is running

The server is **not** always up. Its lifetime is controlled by the `web_app_mode` setting
(dashboard **SETTINGS → DATA** tab) and whether Share Logs is enabled:

| Situation | Server state |
|-----------|--------------|
| Game menu / settings overlay open | Running (so a client can sync while the DATA tab is visible) |
| During gameplay, `web_app_mode` = `menu` (default) or `off` | Stopped — frees resources at 60 fps |
| During gameplay, `web_app_mode` = `always` | Kept running mid-session (for capable Pis) |

Expect the server to appear and disappear: connect while the DATA tab is open, or set the web
companion to **ALWAYS**. `web_app_mode = off` disables the HTML `/app` tree but the JSON/CSV API
still serves while the menu is open with Share Logs enabled.

---

## Authentication

Every JSON/CSV endpoint requires the **pairing code** — an 8-character token shown on the dashboard's
**SETTINGS → DATA** tab (stored as `api_token` in `config.json`, generated once on first use;
delete the key to regenerate and re-pair every client).

Send it as a **Bearer** token:

```
Authorization: Bearer <PAIRING-CODE>
```

- The header is **case-insensitive** — the server upper-cases and compares with a constant-time
  check (`hmac.compare_digest`).
- `X-Api-Key: <PAIRING-CODE>` is also accepted as an alternative to the `Authorization` header.
- **Fail-closed:** if no token is configured on the Pi, *every* request is rejected. There is no
  unauthenticated mode.
- A missing/incorrect token returns **`401`** with a `WWW-Authenticate: Bearer` header and a JSON
  body `{"error": "pairing code required"}`.

> **Browser cookie path is separate.** The `/app` HTML pages authorise off an `HttpOnly` session
> cookie (set from a one-time `?key=<token>` in the QR link) because browsers can't attach a Bearer
> header on a navigation. That cookie **never** authorises the JSON/CSV API, and the API never
> accepts the cookie — the two auth paths do not cross. This reference covers the **Bearer** API.

---

## Endpoints

All paths below are relative to `http://<pi-ip>:8765`. Unless noted, every request needs the
`Authorization: Bearer` header and a non-matching path returns `404`.

### Session logs

#### `GET /index.json`

Lists session files currently inside the configured **share window** (DATA tab: 1 / 7 / 30 days, or
ALL; default 7 days), judged by the date encoded in each filename. Sessions are newest-first.

**Response `200`** (`application/json`):

```json
{
  "sessions": [
    {
      "filename":        "session_20260617_1430_race.csv",
      "url":             "/session_20260617_1430_race.csv",
      "version":         1,
      "session_type":    "race",
      "session_subtype": "",
      "car_class":       "formula1",
      "car_name":        "McLaren",
      "driver_name":     "PIASTRI",
      "track":           "Silverstone",
      "weather":         "clear",
      "air_temp":        "21",
      "track_temp":      "34",
      "date":            "2026-06-17T14:30:00",
      "lap_count":       28
    }
  ],
  "server_time": "2026-06-17T15:45:00"
}
```

Fields are read from the CSV's `S` (metadata) rows; `lap_count` is the number of `L` rows. Values a
game does not provide are empty strings. See [session-log-format.md](session-log-format.md) for the
full meaning of each field.

#### `GET /<filename>.csv`

Downloads the raw session CSV. The filename must match `session_YYYYMMDD_HHMM_<label>.csv` and
contain no path separators.

- **`200`** — `Content-Type: text/csv; charset=utf-8`, the file bytes. The server also marks the file
  as *synced* (so it no longer counts toward the "waiting to sync" badge on the Pi).
- **`404`** — filename doesn't match the session pattern, or the file doesn't exist.

Direct download works for **any** session regardless of the share window — the window only limits
what `/index.json` lists. A client that already knows a filename can always re-fetch it.

#### `PUT /<filename>.csv`

Pushes a session CSV **to** the Pi — used by the companion to upload sessions the Pi never logged
itself (e.g. AC/ACC screenshot imports). Re-pushing the same filename overwrites harmlessly (same
name = same session).

- **Body:** a typed-row session CSV; it **must start with `S,`**.
- **Constraints:** filename must match `session_*.csv` with no `/`; `Content-Length` must be
  `0 < length ≤ 2 MB` (`2 097 152` bytes).
- **`201`** — `{"ok": true, "filename": "<filename>"}`. The file is written into `logs/`, marked
  synced (never listed as waiting), and picked up by the records index on its next scan.
- **`400`** — `{"error": "filename must be session_*.csv"}` (bad name) or
  `{"error": "not a typed-row session CSV"}` (body doesn't start with `S,`).
- **`413`** — `{"error": "bad content length"}` (missing, zero, or over 2 MB).
- **`500`** — `{"error": "could not write file"}` (disk/OS error).

### Track maps

Recorded circuit maps live under `tracks/` and are served/accepted at `/tracks/…`. Track filenames
are slugged `<game>_<track>.json` and must match `^[A-Za-z0-9][A-Za-z0-9_-]*\.json$` (flat directory,
no path separators). The track-map JSON schema is documented in [track-format.md](track-format.md).

> If no tracks directory is configured on the server, the GET routes behave as "empty / not found"
> and the `PUT` route returns **`500`** `{"error": "tracks not configured"}`.

#### `GET /tracks/index.json`

Lists available track maps with a one-line summary each.

**Response `200`** (`application/json`):

```json
{
  "tracks": [
    {
      "filename":            "f1_25_silverstone.json",
      "url":                 "/tracks/f1_25_silverstone.json",
      "game":                "f1_25",
      "track":               "Silverstone",
      "car_classes":         ["formula1", "formula1_2026", "f2"],
      "game_track_length_m": 5891,
      "has_pit":             true,
      "section_count":       18,
      "has_notes":           true,
      "author":              "<name>",
      "updated":             "2026-07-01T12:00:00",
      "sha":                 "<sha256 of the file bytes>",
      "bytes":               40213
    }
  ],
  "server_time": "2026-06-17T15:45:00"
}
```

`car_classes` are the class keys that have a recorded racing line in the map's `lines` object. `sha`
(sha256 of the raw file) and `bytes` let a client detect changes without downloading the whole file.

#### `GET /tracks/<filename>.json`

Downloads the raw track-map JSON.

- **`200`** — `Content-Type: application/json; charset=utf-8`, the file bytes.
- **`404`** — filename doesn't match the track pattern, tracks aren't configured, or the file is
  missing.

#### `PUT /tracks/<filename>.json`

Pushes a track map (companion edits — labelled sections, orientation, notes, etc.). Overwrites the
same filename.

- **Body:** a JSON object. It must contain a `format_version` key **and** at least one of
  `left_edge`, `right_edge`, `lines`, `sections` (a minimal validity check that it is a track map,
  not arbitrary JSON).
- **Constraints:** filename must match the track pattern; `Content-Length` must be
  `0 < length ≤ 1 MB` (`1 048 576` bytes).
- **`201`** — `{"ok": true, "filename": "<filename>"}`.
- **`400`** — `{"error": "filename must be <name>.json"}`, `{"error": "body is not valid JSON"}`, or
  `{"error": "not a track map"}`.
- **`413`** — `{"error": "bad content length"}`.
- **`500`** — `{"error": "tracks not configured"}` or `{"error": "could not write file"}`.

### Driver profile

The declared driver identity (name, experience, discipline, goal, avatar). The companion is the
editor; the Pi stores what is pushed.

#### `GET /profile.json`

**Response `200`** (`application/json`): the profile object (always complete — a Pi-only driver
gets a sensible default) plus a `server_time` field. Exact keys mirror `config_store.profile`
(`name`, `experience`, `discipline`, `goal`, `avatar_kind`, `avatar_helmet`, `updated`, …).

#### `PUT /profile.json`

Pushes an updated profile.

- **Body:** a JSON object (partial or full profile). Unknown keys are ignored by the store.
- **Constraints:** `Content-Length` must be `0 < length ≤ 1 MB`.
- **`200`** — `{"ok": true, "profile": { …cleaned profile… }}`.
- **`400`** — `{"error": "invalid JSON"}` or `{"error": "expected a profile object"}`.
- **`413`** — `{"error": "bad content length"}`.

---

## Validation & limits (summary)

| Rule | Applies to | On violation |
|------|------------|--------------|
| Missing/incorrect token, or none configured (fail-closed) | all endpoints | `401` `{"error": "pairing code required"}` |
| Session filename `session_*.csv`, no `/`; body starts with `S,` | `GET`/`PUT /<file>.csv` | `404` (GET) / `400` (PUT) |
| Session upload `0 < length ≤ 2 MB` | `PUT /<file>.csv` | `413` |
| Track filename `^[A-Za-z0-9][A-Za-z0-9_-]*\.json$` | `GET`/`PUT /tracks/<file>.json` | `404` (GET) / `400` (PUT) |
| Track body JSON with `format_version` + one of `left_edge`/`right_edge`/`lines`/`sections`; `0 < length ≤ 1 MB` | `PUT /tracks/<file>.json` | `400` / `413` |
| Profile upload: valid JSON object, `0 < length ≤ 1 MB` | `PUT /profile.json` | `400` / `413` |

Error responses carry a JSON body `{"error": "<reason>"}` (empty body for a bare status). Successful
writes return `201` (uploads) or `200` (profile) with `{"ok": true, …}`.

---

## `curl` examples

List sessions:

```bash
curl -s http://192.168.1.42:8765/index.json \
  -H "Authorization: Bearer ABCD1234"
```

Upload a session CSV (must start with `S,`):

```bash
curl -s -X PUT http://192.168.1.42:8765/session_20260617_1430_race.csv \
  -H "Authorization: Bearer ABCD1234" \
  -H "Content-Type: text/csv" \
  --data-binary @race.csv
# → 201 {"ok": true, "filename": "session_20260617_1430_race.csv"}
```

Push a track map:

```bash
curl -s -X PUT http://192.168.1.42:8765/tracks/f1_25_silverstone.json \
  -H "Authorization: Bearer ABCD1234" \
  -H "Content-Type: application/json" \
  --data-binary @silverstone.json
# → 201 {"ok": true, "filename": "f1_25_silverstone.json"}
```

---

## Web companion (`/app`) — for reference only

The same server also serves a mobile-browser mirror of the companion under `/app` (server-rendered
HTML). These routes use the **cookie** auth path described above, not Bearer, and are intended for a
person with a browser rather than an API client. Notable routes: `GET /app?key=<token>` (pairs and
sets the cookie via `302`), the various `GET /app/…` HTML pages, cookie-authed `POST` form actions
(`/app/session/<file>/favourite`, `/app/driver/save`, `/app/track/<file>/save`), and one JSON
polling endpoint:

- **`GET /app/status.json`** — a new-session poll used by the pages (`Cache-Control: no-store`),
  cookie-authed like the rest of `/app`. Not part of the Bearer API.

See [session-log-format.md](session-log-format.md#web-companion-http-routes-app-v0630) and
[`src/core/web_app.py`](../src/core/web_app.py) for the full `/app` route list.

---

## Notes

Paths, methods and status codes above are taken directly from `log_server.py`; where the server
returns a bare `404`/`400` without a JSON body, that is noted rather than invented. A formal
**OpenAPI / Swagger** specification may be published later for client generation and contract
testing — until then, this document and the linked format specs are the source of truth.
