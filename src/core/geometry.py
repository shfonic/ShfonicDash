"""Shared 2-D polyline geometry — projection of a point onto a line.

Factored out of ``track_recorder`` so the track recorder and the racing-line
adherence tracker (``core/line_tracker``) share one projection implementation
rather than each carrying a copy. Coordinates are the recorder's game-agnostic
horizontal plane (X / Z, metres); ``pt`` and every vertex are ``(x, z)`` pairs.

**Sign convention** (``signed_offset``): the perpendicular offset is *positive to
the right of the direction of travel* and negative to the left, where "right" is
the tangent rotated by −90° in the (x, z) plane — ``right = (tangent_z,
-tangent_x)``. ``sessionlog.lines`` reconstructs the driven line from a stored
offset profile using the *same* convention, so a positive offset always lands on
the same side in both the capture (here) and the render (there). The label
left/right is only as trustworthy as the game's world handedness, but the
reconstruction is self-consistent regardless, which is what the mini-map needs.
"""

import math


def pt_dist(a: tuple, b: tuple) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def project_to_line(pt: tuple, line: list):
    """Perpendicular projection of ``pt`` onto the nearest *segment* of ``line``,
    as ``(foot_point, segment_start_index, distance)``. Segment distance (not
    vertex distance) is what makes a tight "on the track" band meaningful — with
    ~15 m vertex spacing a car dead on the line can still be 7 m from any vertex.
    Returns ``(None, -1, inf)`` for a degenerate line."""
    best = (None, -1, float("inf"))
    for i in range(len(line) - 1):
        ax, az = line[i]
        bx, bz = line[i + 1]
        dx, dz = bx - ax, bz - az
        l2 = dx * dx + dz * dz
        if l2 == 0.0:
            foot, d = line[i], pt_dist(pt, line[i])
        else:
            t = max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - az) * dz) / l2))
            foot = (ax + t * dx, az + t * dz)
            d = pt_dist(pt, foot)
        if d < best[2]:
            best = (foot, i, d)
    return best


def signed_offset(pt: tuple, line: list) -> float:
    """Signed perpendicular distance of ``pt`` from ``line`` (metres), positive to
    the right of travel (see module sign convention), 0.0 for a degenerate line.

    Used per-frame by the line tracker to record how far off the racing line the
    player drove; the sign lets ``sessionlog.lines`` put the driven line back on
    the correct side when it reconstructs the mini-map overlay."""
    foot, i, d = project_to_line(pt, line)
    if i < 0 or foot is None:
        return 0.0
    tx, tz = line[i + 1][0] - line[i][0], line[i + 1][1] - line[i][1]
    # Right-hand normal = tangent rotated -90°; positive dot ⇒ pt is to the right.
    dot = (pt[0] - foot[0]) * tz + (pt[1] - foot[1]) * (-tx)
    return d if dot >= 0 else -d
