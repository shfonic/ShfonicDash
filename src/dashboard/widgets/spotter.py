"""
Spotter radar — top-down proximity view centred on the player's car.

Opponent cars (TelemetryData.opponents_pos) are drawn as rectangles around
the player, coloured by threat: subtle grey when merely nearby, AMBER when
close, RED when alongside. Unlike the ahead/behind gap strip
(ProximityWidget), this widget is spatial — it is the only cue that a car
is alongside in cockpit views with no mirrors.

The projection and threat maths live in module-level functions so they can
be unit-tested without pygame; every forward/right expression is inside
`to_local`, so a chirality fix verified against a real game is a one-line
change.
"""
import math

import pygame
from .base import Widget
from . import design_system as DS

CAR_LENGTH_M = 5.6       # modern F1 car
CAR_WIDTH_M = 2.0
ALONGSIDE_LONG_M = 5.6   # |ahead| within one car length → overlapping
ALONGSIDE_LAT_M = 4.0    # ≈2 car widths — "alongside" lateral window
CLOSE_RADIUS_M = 12.0    # amber zone radius


def to_local(dx: float, dz: float, heading: float) -> tuple:
    """
    World-frame offset (dx, dz) from the player → player-local (right, ahead)
    in metres. Heading is the shared model convention (F1 yaw: 0 faces +Z,
    increasing toward +X), so forward = (sin h, cos h) and right =
    (cos h, -sin h) in (x, z).
    """
    sin_h, cos_h = math.sin(heading), math.cos(heading)
    ahead = dx * sin_h + dz * cos_h
    right = dx * cos_h - dz * sin_h
    return right, ahead


def threat_level(right: float, ahead: float) -> int:
    """0 = clear-ish, 1 = close (amber), 2 = alongside (red)."""
    if abs(ahead) <= ALONGSIDE_LONG_M and abs(right) <= ALONGSIDE_LAT_M:
        return 2
    if math.hypot(right, ahead) <= CLOSE_RADIUS_M:
        return 1
    return 0


def car_corners(right: float, ahead: float, rel_yaw: float,
                length: float = CAR_LENGTH_M, width: float = CAR_WIDTH_M) -> list:
    """
    Corners of a car rectangle centred at (right, ahead) in player-local
    metres, rotated by rel_yaw (opponent yaw − player heading; 0 = pointing
    the same way as the player). Returns [(right, ahead), …] × 4.
    """
    sin_r, cos_r = math.sin(rel_yaw), math.cos(rel_yaw)
    half_l, half_w = length / 2.0, width / 2.0
    corners = []
    for cw, cl in ((-half_w, half_l), (half_w, half_l),
                   (half_w, -half_l), (-half_w, -half_l)):
        # Local car axes: +cl towards its own nose, +cw to its own right.
        corners.append((right + cw * cos_r + cl * sin_r,
                        ahead - cw * sin_r + cl * cos_r))
    return corners


_THREAT_COLORS = (DS.TEXT4, DS.AMBER, DS.RED)


class SpotterWidget(Widget):
    """
    Radar view of the cars around the player. `range_m` is the distance in
    metres from the player to the top edge of the widget; the horizontal
    coverage follows from the widget's aspect ratio (uniform scale). Shows
    in any session type — gated only on pos_valid.
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 range_m: float = 25.0):
        super().__init__(x, y, width, height)
        self.range_m = float(range_m)
        self._pos = (0.0, 0.0)      # (x, z)
        self._heading = 0.0
        self._valid = False
        self._opponents = []

    def update(self, telemetry) -> None:
        self._pos = (float(getattr(telemetry, 'pos_x', 0.0)),
                     float(getattr(telemetry, 'pos_z', 0.0)))
        self._heading = float(getattr(telemetry, 'heading', 0.0))
        self._valid = bool(getattr(telemetry, 'pos_valid', False))
        self._opponents = getattr(telemetry, 'opponents_pos', []) or []

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface)

        cx = self.x + self.width // 2
        cy = self.y + self.height // 2
        scale = (self.height / 2.0 - 6.0) / self.range_m

        # Reference geometry: amber-zone ring + centre cross.
        pygame.draw.circle(surface, DS.BORDER, (cx, cy),
                           int(CLOSE_RADIUS_M * scale), width=1)
        pygame.draw.line(surface, DS.BORDER,
                         (self.x + 4, cy), (self.x + self.width - 5, cy))
        pygame.draw.line(surface, DS.BORDER,
                         (cx, self.y + 4), (cx, self.y + self.height - 5))

        if self._valid:
            self._draw_opponents(surface, cx, cy, scale)

        # Player last, on top — always points up by construction.
        player_color = DS.TEXT if self._valid else DS.TEXT4
        pw = max(2, int(CAR_WIDTH_M * scale))
        pl = max(4, int(CAR_LENGTH_M * scale))
        pygame.draw.rect(surface, player_color,
                         pygame.Rect(cx - pw // 2, cy - pl // 2, pw, pl),
                         border_radius=3)

        surface.set_clip(None)

    def _draw_opponents(self, surface, cx: int, cy: int, scale: float) -> None:
        px, pz = self._pos
        half_w_m = (self.width / 2.0) / scale
        cars = []
        for opp in self._opponents:
            right, ahead = to_local(opp['x'] - px, opp['z'] - pz, self._heading)
            if abs(ahead) > self.range_m + CAR_LENGTH_M:
                continue
            if abs(right) > half_w_m + CAR_LENGTH_M:
                continue
            cars.append((threat_level(right, ahead), right, ahead,
                         opp['yaw'] - self._heading))

        # Grey first, red last, so the dangerous car is never occluded.
        cars.sort(key=lambda c: c[0])
        for threat, right, ahead, rel_yaw in cars:
            points = [(cx + r * scale, cy - a * scale)
                      for r, a in car_corners(right, ahead, rel_yaw)]
            pygame.draw.polygon(surface, _THREAT_COLORS[threat], points)
            pygame.draw.polygon(surface, DS.BORDER2, points, width=1)
