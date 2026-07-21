"""Draw a small "where on track" thumbnail for a Race Engineer note.

The geometry — which slice of the track edges to draw and where the event
happened — is computed by the shared, toolkit-free `sessionlog.trackmap`
(`crop_geometry`); this module is the Pi's pygame side of that split (the
companion draws the same geometry with Pythonista `ui`). Keeping the maths
in `sessionlog` means the Pi and the companion frame the identical corner.

`draw_thumbnail` fits the crop into a rect (aspect-preserving, north-up —
the same convention as the track recorder's live map), outlines the track
edges and marks the event point with a single triangle pointing the way the
car travels. `THUMB_W`/`THUMB_H`/`LABEL_H` are the metrics the note layouts
use to reserve space for a row of thumbnails.
"""
import math

import pygame

THUMB_W = 88
THUMB_H = 60
LABEL_H = 14
GAP     = 8      # between thumbnails in a row
# Single-triangle event marker (a play-head pointing the way the car travels).
_MARK_TIP  = 8    # tip reach ahead of the point
_MARK_BACK = 5    # base reach behind the point
_MARK_HALF = 5    # half-width of the base


def _fit(rect, bounds):
    """Return a world→screen projector fitting `bounds` into `rect`,
    aspect-preserving and centred, with z inverted so north is up and x
    negated (like track_viewer.html's `sx` and the track recorder's live
    map) so the thumbnail matches the real driving direction."""
    minx, minz, maxx, maxz = bounds
    span_x = max(maxx - minx, 1.0)
    span_z = max(maxz - minz, 1.0)
    scale = min(rect.width / span_x, rect.height / span_z)
    off_x = rect.x + (rect.width - span_x * scale) / 2
    off_y = rect.y + (rect.height - span_z * scale) / 2

    def project(p):
        x, z = p
        return (int(off_x + (maxx - x) * scale),
                int(off_y + (maxz - z) * scale))

    return project


def _draw_marker(surface, centre, heading, colour, *, rewound=False):
    """A single filled triangle at the event point, pointing the way the car
    travels (`heading` is the world (ux, uz) unit vector; x is negated and z
    inverted for screen, matching `_fit`). Falls back to a dot when there is
    no heading. The fill is the
    severity colour; the outline is normally the panel colour (so it reads as
    the track line breaking around the marker), but **blue when the incident
    was flashed back** — one marker then shows both what happened (fill) and
    that it was rewound (blue rim)."""
    from dashboard.widgets import design_system as DS

    edge_col = DS.BLUE if rewound else DS.PANEL2
    edge_w   = 2 if rewound else 1
    mx, my = centre
    if not heading:
        pygame.draw.circle(surface, colour, (mx, my), 4)
        pygame.draw.circle(surface, edge_col, (mx, my), 4, edge_w)
        return
    ux, uz = heading
    sx, sy = -ux, -uz           # world → screen: x negated, y inverted (matches _fit)
    mag = math.hypot(sx, sy) or 1.0
    sx, sy = sx / mag, sy / mag
    px, py = -sy, sx            # perpendicular
    pts = [(mx + sx * _MARK_TIP, my + sy * _MARK_TIP),
           (mx - sx * _MARK_BACK + px * _MARK_HALF,
            my - sy * _MARK_BACK + py * _MARK_HALF),
           (mx - sx * _MARK_BACK - px * _MARK_HALF,
            my - sy * _MARK_BACK - py * _MARK_HALF)]
    pygame.draw.polygon(surface, colour, pts)
    pygame.draw.polygon(surface, edge_col, pts, edge_w)


def kind_colour(kind):
    """Marker *fill* colour for a location `kind` — the eye triages severity
    before reading: green info · amber track-limit warning · orange contact ·
    red major collision. (Flashback is not a fill; it's a blue rim added by the
    marker when the incident was rewound.) Unknown kinds fall back to red."""
    from dashboard.widgets import design_system as DS
    return {
        "info":        DS.GREEN,
        "track_limit": DS.AMBER,
        "contact":     DS.ORANGE,
        "major":       DS.RED,
        "off_line":    DS.AMBER,
    }.get(kind, DS.RED)


def draw_line_map(surface, rect, geom, *, label=None, font=None):
    """Draw a player-vs-racing-line mini-map into `rect`. `geom` is
    `sessionlog.lines.player_line_geometry(...)` (`{racing, player, bounds}`,
    skipped silently when None) — the recorded racing line as a faint ghost and
    the driver's actual line accented over it, so how far off the line they ran
    reads at a glance. Larger than the corner thumbnails; used on the summary and
    history detail. Same north-up fit as `draw_thumbnail`."""
    from dashboard.widgets import design_system as DS

    pygame.draw.rect(surface, DS.PANEL2, rect, border_radius=6)
    if geom and len(geom.get("racing") or []) >= 2:
        project = _fit(rect.inflate(-10, -10), geom["bounds"])
        pygame.draw.lines(surface, DS.TEXT3, False,
                          [project(p) for p in geom["racing"]], 2)
        if len(geom.get("player") or []) >= 2:
            pygame.draw.lines(surface, DS.AMBER, False,
                              [project(p) for p in geom["player"]], 2)
    pygame.draw.rect(surface, DS.BORDER2, rect, width=1, border_radius=6)

    if label and font is not None:
        txt = font.render(label, True, DS.TEXT3)
        tx = rect.x + (rect.width - txt.get_width()) // 2
        surface.blit(txt, (tx, rect.bottom + 2))


def draw_thumbnail(surface, rect, geom, label=None, *, font=None, colour=None,
                   rewound=False):
    """Draw one crop into `rect`. `geom` is `trackmap.crop_geometry(...)`
    (skipped silently when None). `label` (e.g. "Turn 3") is drawn beneath
    the panel when a `font` is given; reserve `LABEL_H` for it in the layout.
    `colour` is the marker fill (defaults to red); `rewound` adds the blue rim.
    """
    from dashboard.widgets import design_system as DS

    if colour is None:
        colour = DS.RED
    pygame.draw.rect(surface, DS.PANEL2, rect, border_radius=6)
    if geom:
        project = _fit(rect.inflate(-8, -8), geom["bounds"])
        for edge in (geom["left"], geom["right"]):
            if len(edge) >= 2:
                pygame.draw.lines(surface, DS.TEXT3, False,
                                  [project(p) for p in edge], 2)
        _draw_marker(surface, project(geom["marker"]), geom.get("heading"),
                     colour, rewound=rewound)
    pygame.draw.rect(surface, DS.BORDER2, rect, width=1, border_radius=6)

    if label and font is not None:
        txt = font.render(label, True, DS.TEXT3)
        tx = rect.x + (rect.width - txt.get_width()) // 2
        surface.blit(txt, (tx, rect.bottom + 2))


def draw_row(surface, x, y, locations, geom_of, *, font=None, avail_w=None,
             max_thumbs=8, max_rows=None):
    """Draw thumbnails for `locations` (`[{label, distance, kind, rewound}, …]`
    from a detailed note), wrapping into rows that fit `avail_w` pixels (a
    single row when `avail_w` is None). `geom_of(loc)` returns the crop
    geometry (the caller owns the track map); each marker is coloured by
    `kind` and gets a blue rim when `rewound`. `max_thumbs` caps the total,
    `max_rows` the number of rows (the space-tight summary passes 1). Returns
    the y below the block, or the input `y` if nothing was drawn.
    """
    items = []
    for loc in locations:
        if len(items) >= max_thumbs:
            break
        geom = geom_of(loc)
        if geom is not None:
            items.append((loc, geom))
    if not items:
        return y

    pitch = THUMB_W + GAP
    per_row = max(1, int((avail_w + GAP) // pitch)) if avail_w else len(items)
    if max_rows:
        items = items[:per_row * max_rows]
    row_h = THUMB_H + LABEL_H + GAP

    for i, (loc, geom) in enumerate(items):
        col, r = i % per_row, i // per_row
        rect = pygame.Rect(x + col * pitch, y + r * row_h, THUMB_W, THUMB_H)
        draw_thumbnail(surface, rect, geom, loc.get("label"), font=font,
                       colour=kind_colour(loc.get("kind")),
                       rewound=loc.get("rewound", False))
    rows = (len(items) + per_row - 1) // per_row
    return y + rows * row_h
