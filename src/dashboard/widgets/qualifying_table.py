import pygame
from .base import Widget
from .fonts import load_ui
from . import design_system as DS


def _fmt_lap(seconds: float) -> str:
    if seconds <= 0:
        return "--:--.---"
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:06.3f}"


class QualifyingTableWidget(Widget):
    """
    Qualifying leaderboard showing P1, a window around the player, and
    the position below the player.  The number of visible rows scales
    with widget height; rows are selected so P1 and the player are always
    present, expanding symmetrically outward from the player until the
    widget is full.
    """

    _SEP_H = 10   # pixels for the "· · ·" gap indicator

    def __init__(self, x: int, y: int, width: int, height: int):
        super().__init__(x, y, width, height)
        self._session = None
        self._participants: list = []
        self._player_pos: int = 0
        self._total_cars: int = 0

        row_sz = max(11, int(height * 0.10))
        hdr_sz = max(9,  int(height * 0.085))
        self._row_font = load_ui(row_sz)
        self._hdr_font = load_ui(hdr_sz)

    def set_session(self, session) -> None:
        self._session = session

    def update(self, telemetry) -> None:
        self._player_pos = int(getattr(telemetry, 'position', 0))
        self._total_cars = int(getattr(telemetry, 'total_cars', 0))
        if self._session is None:
            self._participants = list(getattr(telemetry, 'participants', []))

    # ── Row selection ─────────────────────────────────────────────────────────

    def _select_positions(self, player_pos: int, total: int, max_rows: int) -> list:
        """
        Return a sorted list of positions to render, at most *max_rows* entries.

        Always includes P1 and the player's position.  Additional slots are
        filled by expanding outward from the player (player±1, player±2, …).
        """
        if total <= 0 or player_pos <= 0:
            return []
        if max_rows >= total:
            return list(range(1, total + 1))

        selected = {1, player_pos}
        radius = 0
        while len(selected) < max_rows:
            radius += 1
            for candidate in (player_pos - radius, player_pos + radius):
                if 2 <= candidate <= total and candidate not in selected:
                    selected.add(candidate)
                if len(selected) >= max_rows:
                    break
            if radius >= total:
                break
        return sorted(selected)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface) -> None:
        self._clip(surface)
        self._draw_bg(surface)

        pad = 8
        uw  = self.width - pad * 2

        # Column layout
        pos_w  = max(28, int(uw * 0.14))   # "P1" / "P20"
        name_w = int(uw * 0.46)            # driver name
        # time column takes the rest, right-aligned

        pos_cx  = self.x + pad + pos_w // 2
        name_x  = self.x + pad + pos_w + 6
        time_rx = self.x + self.width - pad

        y = self.y + pad

        # ── Header ───────────────────────────────────────────────────────────
        for text, ref, align in (
            ("POS",    pos_cx,  "center"),
            ("DRIVER", name_x,  "left"),
            ("TIME",   time_rx, "right"),
        ):
            s = self._hdr_font.render(text, True, DS.TEXT3)
            if align == "center":
                surface.blit(s, s.get_rect(midtop=(ref, y)))
            elif align == "left":
                surface.blit(s, (ref, y))
            else:
                surface.blit(s, s.get_rect(topright=(ref, y)))

        y += self._hdr_font.get_height() + 3
        pygame.draw.line(surface, DS.BORDER,
                         (self.x + pad, y), (self.x + self.width - pad, y))
        y += 4

        # ── Row calculation ───────────────────────────────────────────────────
        row_h    = self._row_font.get_height() + 4
        avail_h  = (self.y + self.height) - y - pad
        max_rows = max(1, avail_h // row_h)

        participants = self._session.participants if self._session is not None else self._participants
        player_pos   = self._player_pos
        total        = len(participants) or self._total_cars

        positions    = self._select_positions(player_pos, total, max_rows)
        by_pos       = {p["position"]: p for p in participants}

        dot_r = max(3, row_h // 4)

        # ── Rows ─────────────────────────────────────────────────────────────
        prev_pos = None
        for pos in positions:
            # Gap separator between non-consecutive positions
            if prev_pos is not None and pos > prev_pos + 1:
                sep = self._hdr_font.render("· · ·", True, DS.TEXT4)
                surface.blit(sep, (name_x, y + (self._SEP_H - sep.get_height()) // 2))
                y += self._SEP_H

            prev_pos = pos
            entry    = by_pos.get(pos)
            is_p1    = pos == 1
            is_player = pos == player_pos

            # Player row highlight
            if is_player:
                row_rect = pygame.Rect(self.x + 4, y - 1, self.width - 8, row_h)
                DS.draw_panel2(surface, row_rect, radius=4)

            row_mid = y + row_h // 2

            # Position label
            pos_color = DS.MAGENTA if is_p1 else (DS.AMBER if is_player else DS.TEXT3)
            ps = self._row_font.render(f"P{pos}", True, pos_color)
            surface.blit(ps, ps.get_rect(center=(pos_cx, row_mid)))

            # ── Driver cell (colour dot | race# | name) ──────────────────────
            cur_x  = name_x
            colour = (entry or {}).get("team_colour")

            # Team colour dot (always drawn — outline only when no colour)
            dot_colour = colour if colour else DS.PANEL2
            pygame.draw.circle(surface, dot_colour, (cur_x + dot_r, row_mid), dot_r)
            if not colour:
                pygame.draw.circle(surface, DS.TEXT4, (cur_x + dot_r, row_mid), dot_r, 1)
            cur_x += dot_r * 2 + 4

            # Race number
            race_num = (entry or {}).get("race_number", 0)
            if race_num:
                rn_color = DS.AMBER if is_player else DS.TEXT3
                rns = self._row_font.render(str(race_num), True, rn_color)
                surface.blit(rns, rns.get_rect(midleft=(cur_x, row_mid)))
                cur_x += rns.get_width() + 4

            # Driver name, clipped to remaining column space
            name      = entry["name"] if entry else "---"
            name_avail = name_w - (cur_x - name_x)
            ns = self._row_font.render(name, True, DS.TEXT)
            if ns.get_width() > name_avail > 0:
                ns = ns.subsurface((0, 0, name_avail, ns.get_height()))
            surface.blit(ns, ns.get_rect(midleft=(cur_x, row_mid)))

            # Best lap time
            best = entry["best_lap"] if entry else 0.0
            time_color = DS.MAGENTA if is_p1 else (DS.AMBER if is_player else DS.TEXT)
            ts = self._row_font.render(_fmt_lap(best), True, time_color)
            surface.blit(ts, ts.get_rect(midright=(time_rx, row_mid)))

            y += row_h

        surface.set_clip(None)
