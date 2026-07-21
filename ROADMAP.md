# Shfonic Dash — Roadmap

Where Shfonic Dash is heading: the planned features and improvements grouped
by area. This is the detailed backlog behind each open item in the README —
already-shipped functionality lives in the app and the changelog, not here.

---

## Widgets & dashboards

New readouts and layouts for the live cockpit view:

- **Driver inputs + trace** — throttle/brake bars with a scrolling history of
  the last ~30 s, plus a steering rotation indicator.
- **Lap comparison chart** — two laps stacked against distance (speed,
  throttle/brake, gear, delta) with corner markers, F1 TV-overlay style.
- **Weather** — rain intensity, track wetness, and a dry/inter/wet compound hint.
- **Safety car / VSC delta** — gap to the delta target during an SC or VSC period.
- **Pit window** — a PIT OPEN / PIT CLOSE indicator driven by fuel and lap count.
- **Session countdown** — time-remaining readout for timed and endurance races.
- **Engine temps & warnings** — water/oil temperature bars that flash over threshold.
- **Car settings** — brake bias, differential, engine map and assist grid.
- **Flag / race status** — colour-matched banner with flash for yellow and red.
- **G-force** — lateral/longitudinal readout or a 2D dot-in-circle plot.
- **Speed trap** — per-lap peak speed plus a short history for setup comparison.
- **Mini-sector colouring** — per-mini-sector purple/green/yellow split timing.
- **Tyre widget upgrades** — PSI in the tyre grid and a top-down car-outline variant.
- **Tyre wear trend** — projected laps left on the current set from recent wear.
- **Position & gaps redesign** — large position block with ahead/behind gap rows.
- **Rival strip** — gap to P1 and to a chosen target position in practice/quali.
- **Personal best flash** — full-screen celebration when a new PB lap is set.

### Visual refinement pass

- Audit every dashboard for alignment, symmetry, consistent padding and font scale.
- Confirm all dashboards use theme colours (no hardcoded values) and read well
  side by side.
- Retune theme presets against the real 7" panel; add a brighter/high-contrast
  option if the current set reads too dark in the cockpit.

---

## Track mapping & spatial features

Building on the driver-controlled track recorder (drive the circuit once to
capture edges, racing line, sectors and pit lane into a reusable map):

- **Track map widget** — north-up full-circuit overview with a live car dot and
  sector colouring, and the whole field once opponent positions are plotted.
- **Mini-map widget** — a zoomed, player-rotated radar that always points "up",
  showing nearby cars around you.
- **Broadcast-style race overview** — a full-screen view pairing the circuit map
  with a live-timing standings panel that reorders as positions change.
- **Fastest-line heatmap** — colour the racing line by speed to reveal braking
  points and corner-exit speed across a stint.
- **Incident replay markers** — overlay penalties, off-tracks and invalidated
  laps on the map for post-session review.
- **Car-specific track profiles** — DRS zones, active-aero zones and per-class
  racing lines recorded as overlays on top of the shared base map.
- **Per-track file layout** — a folder per circuit holding geometry, a
  lightweight index and a preview thumbnail.
- **Track hosting & sharing** — record on the Pi, edit the map in a browser
  (offline or live against the Pi), and let the web companion sync labelled
  tracks over the local network.
- **Section-aware coaching** — Race Engineer Notes and event summaries that
  describe *where* by corner name rather than distance ("invalidated at Copse
  three times"). Journal entries are next to gain named locations.
- **Richer contact context** — capture the other car's relative position at a
  collision so incident notes can describe the *kind* of contact as fact, not
  a guess.

The spotter radar (top-down "where are they" view) is shipped; remaining work is
placing it in dashboard configs and adding a text CLEAR / CAR LEFT / CAR RIGHT
readout.

---

## Multi-view & UX

Make each session a set of swipeable views rather than cycling through unrelated
session types:

- **View-scoped swipe** — swipe cycles dedicated views (main / map / standings /
  inputs) within the current session, with page-indicator dots.
- **Base-class fallback** — a custom dashboard (e.g. the DeLorean) can fall
  through to a standard set of views for its base game.
- **Touch navigation** — edge taps for previous/next view and a long-press view
  picker, alongside the existing long-press exit.
- **Last-used view memory** — restore the view you last used per game / car /
  session, with a settings toggle.
- **Font size (Small/Medium/Large)** — a per-screen reflow of menu, summary and
  settings chrome (live gauges stay fixed-layout).

### System & hardware

- **Car / garage log** — record every car driven (Forza especially) into a
  browsable garage view, with a community ordinal → name lookup.
- **Pi health indicator** — a small CPU-temperature / throttling status dot.
- **Auto-brightness** — adjust the display by time of day or an ambient sensor.
- **Physical shift-light bar** — an addressable LED strip along the cockpit that
  mirrors the on-screen shift lights, driven from the Pi's GPIO.

---

## More games

- **Project CARS 2** — complete practice-session timing (current lap, best lap,
  delta), position, and the tyre/lap/sector widgets.
- **Forza (Horizon & Motorsport)** — verify tyre temps and fuel on real
  hardware; expose world position for track mapping; grow the car-recognition
  list so special dashboards (e.g. the DeLorean) switch reliably across titles.
- **Gran Turismo 7** — promote the beta parser to verified once real captures
  confirm it, and add per-car recognition.
- **Wider mapping support** — surface world position in PC2 / Forza / GT7 so the
  track recorder and spatial widgets work beyond F1.

---

## Analysis & coaching

- **Time Trial reference lap** — show the game's all-time best immediately
  (instead of `0:00`), then persist the best-lap profile so a live delta is
  available from the first corner of the next session.
- **Lap trace persistence** — save the record-holding laps (personal best plus
  each best sector) per session for later comparison, synced to the web companion.
- **Focus-driven follow-through** — extend the pick-a-focus → summary → debrief
  loop (already shipped) with a matching debrief question and web-companion parity.
- **Car setup capture (F1)** — record the setup each lap was driven on so the
  archive can suggest the setup that works best at a given track and conditions.
- **Post-session AI debrief** — an on-device coaching summary that reads the
  session's lap, sector and pace data and calls out weak sectors, pace trends and
  consistency in plain English. Nothing like this exists for console games today.
- **Voice race engineer** — spoken calls through the Pi (lap times, PBs, sector
  deltas, blue flags, car-alongside, pit window) so you never glance away from the
  track. The Xbox headset can pair to the console and the Pi at once, making this
  practical.

### Web companion

The Pi already serves a mobile browser companion over the local network — scan a
QR code and get a driver profile, session browser, records drill-down, detailed
session view, driven-line-vs-racing-line maps and a zoomable line viewer, no
install required. Remaining work:

- Journal and trophies galleries in the browser.
- Answering debrief questions from the browser.
- A pre-session goal card in the records drill-down.
- A longer-term path toward one shared engine behind every host (Pi, phone,
  static web).

---

## Known limitations / to verify

- **Project CARS 2** — practice-session timing (lap/best/delta), position and
  several widgets are incomplete; qualifying and race modes are not yet exercised.
- **Forza (Horizon & Motorsport)** — gear and speed are confirmed, but tyre
  temps and fuel still need checking on real hardware, and car ordinals differ
  between titles so special-car recognition can vary.
- **Gran Turismo 7** — ships as **beta**: the parser is built from the
  community-documented protocol and has not yet been confirmed against a real
  console. Current-lap time is estimated rather than read from the game.
- **Track mapping is F1-first** — world position is currently populated for F1
  only, so the recorder and spatial widgets need per-game work for the others.
