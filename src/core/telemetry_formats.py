"""Per-game telemetry format descriptors — what protocol/format each game must
be set to output, and on which UDP port.

Surfaced on the game menu and the "waiting for telemetry" screens so it's clear
what to configure in-game (and, when nothing arrives, what the app is expecting).
Pure data — no pygame — so the pygame menu and the stdlib-only recorder can both
import it. Ports mirror each source's ``_PORT`` / ``_UDP_PORT``.

Correct the ``setup`` / ``format`` wording here in one place; both surfaces follow.
"""

TELEMETRY_INFO = {
    "f1_25": {
        "port":   20777,
        "format": "UDP Format 2024-2026",
        "setup":  "Game Settings > Telemetry > UDP On, Format 2025/2026",
    },
    "pcars2": {
        "port":   5606,
        "format": "Project CARS 2 UDP",
        "setup":  "Options > System > UDP On, Protocol: Project CARS 2",
    },
    "fh6": {
        "port":   5301,
        "format": "Forza Data Out",
        "setup":  "HUD > Data Out On, IP = this device, Port 5301",
    },
    "fm": {
        "port":   5300,
        "format": "Forza Data Out",
        "setup":  "Gameplay & HUD > Data Out On, Port 5300",
    },
    "gt7": {
        "port":   33740,
        "format": "GT7 (auto-discovery)",
        "setup":  "No in-game setting; console on the same network",
    },
}


def format_label(game_id: str) -> str:
    """Short 'FORMAT · UDP :PORT' line for a game, or '' if unknown."""
    info = TELEMETRY_INFO.get(game_id)
    if not info:
        return ""
    return f"{info['format']} · UDP :{info['port']}"


def setup_hint(game_id: str) -> str:
    """The in-game setup steps for a game, or '' if unknown."""
    info = TELEMETRY_INFO.get(game_id)
    return info["setup"] if info else ""
