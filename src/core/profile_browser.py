"""
Driver profile — the PROFILE button on the game menu.

The Pi's mirror of the companion's driver-profile hub: the driver's overall
recent-form grade (sessionlog.career.recent_form) with its trend and per-game
breakdown, career counts (sessions + trophies), and the Personal Records
"chase statistics" (sessionlog.career.personal_records) — longest clean
streak, best consistency, largest PB, most-driven track and car, total
distance. Everything is derived from the same records index the trophies and
history browsers read, so all three agree.

Same interaction grammar as the trophies/history browsers (ScrollPane, ‹ MENU
pill, ESC). A single scrollable page, no drill-in.
"""

import logging
import os

import pygame

from core.flip import flip_pos, flip_surface
from core.history_browser import ScrollPane, _ellipsize

log = logging.getLogger(__name__)

# Grade at most this many recent sessions for the form headline — matches the
# companion's driver.compute_form cap so the two show the same number.
_FORM_CAP = 40

# Trend word + a hand-drawn triangle (the Pi UI font has no arrow glyphs).
_TREND_WORD  = {"up": "Improving", "down": "Slipping", "flat": "Holding steady"}
_TREND_COLOR = {"up": "GREEN", "down": "RED", "flat": "TEXT3"}


# ── shared summary maths (also used by the menu home card) ─────────────────
# Kept at module scope so the game-menu DRIVER PROFILE card derives identical
# numbers to this screen from the same records rows.

def load_rows(logs_dir: str) -> list:
    """Records index rows for logs_dir (newest first), or [] on any failure."""
    if not (logs_dir and os.path.isdir(logs_dir)):
        return []
    try:
        from sessionlog import records
        records.set_cache_dir(logs_dir)
        records.sync()
        return records.all_sessions()
    except Exception as e:
        log.warning(f"profile: records unavailable: {e}")
        return []


def compute_form(rows):
    """career.recent_form over the graded recent sessions (or None)."""
    from sessionlog import career, grading
    from sessionlog import records as session_db
    graded = []
    for rec in rows[:_FORM_CAP]:
        try:
            pb = session_db.prior_best(
                rec.get("game"), rec.get("car_class"), rec.get("track"),
                rec.get("session_type"), rec.get("date"),
                rec.get("filename", ""))
            g = grading.grade(rec, prior_best=pb)
        except Exception:
            g = None
        if g and g.get("score") is not None:
            graded.append({"date": rec.get("date"),
                           "game": rec.get("game_name")
                           or rec.get("game") or "",
                           "score": g["score"]})
    return career.recent_form(graded)


def count_trophies(rows) -> int:
    try:
        from sessionlog.achievements import evaluate
        return len(evaluate(rows))
    except Exception:
        return 0


def compute_records(rows) -> dict:
    try:
        from sessionlog import career
        return career.personal_records(rows)
    except Exception:
        return {}


# Full display order for the PROFILE screen. The menu home card passes its own
# curated order (HOME_RECORD_ORDER) — the four most glanceable records.
_RECORD_ORDER = ["clean_streak", "consistency", "largest_pb",
                 "most_sessions", "favourite_car", "total_distance_km"]
HOME_RECORD_ORDER = ["clean_streak", "consistency", "total_distance_km",
                     "most_sessions"]


def record_tiles(records: dict, order: list | None = None) -> list:
    """(caption, big, sub) for each populated record, in `order` (default: the
    full PROFILE-screen order). Missing records are skipped."""
    r = records or {}

    def _tile(key):
        if key == "clean_streak" and r.get("clean_streak"):
            v = r["clean_streak"]
            return ("LONGEST CLEAN STREAK", f"{v['value']} laps", v.get("label", ""))
        if key == "consistency" and r.get("consistency"):
            v = r["consistency"]
            return ("BEST CONSISTENCY", f"±{v['value']:.2f}s", v.get("label", ""))
        if key == "largest_pb" and r.get("largest_pb"):
            v = r["largest_pb"]
            return ("LARGEST PB", f"{v['value']:.2f}s", v.get("label", ""))
        if key == "most_sessions" and r.get("most_sessions"):
            v = r["most_sessions"]
            return ("MOST-DRIVEN TRACK", v["name"], f"{v['count']} sessions")
        if key == "favourite_car" and r.get("favourite_car"):
            v = r["favourite_car"]
            return ("FAVOURITE CAR", v["name"], f"{v['count']} sessions")
        if key == "total_distance_km" and r.get("total_distance_km"):
            return ("TOTAL DISTANCE", f"{r['total_distance_km']:,.0f} km", "all games")
        return None

    return [t for t in (_tile(k) for k in (order or _RECORD_ORDER)) if t]


class ProfileBrowser:
    """Blocking driver-profile loop over the records index in logs_dir."""

    W, H  = 800, 480
    HDR_H = 64
    PAD   = 28
    GAP   = 12

    def __init__(self, screen: pygame.Surface, logs_dir: str,
                 flip: bool = False):
        from dashboard.widgets.fonts import load_ui
        self._screen   = screen
        self._logs_dir = logs_dir
        self._flip     = flip
        self._f_hdr   = load_ui(16)
        self._f_grade = load_ui(52)
        self._f_big   = load_ui(26)
        self._f_name  = load_ui(16)
        self._f_body  = load_ui(14)
        self._f_sub   = load_ui(12)
        self._form     = None    # career.recent_form(...) or None
        self._sessions = 0
        self._trophies = 0
        self._records  = {}      # career.personal_records(...)
        self._profile  = {}      # declared identity (config_store.profile)
        self._items    = []      # flat drawables (see _build_items)
        self._pane     = ScrollPane(self.H - self.HDR_H)

    # ── public ───────────────────────────────────────────────────────────

    def run(self) -> str:
        """Blocking loop. Returns "menu" (back) or "quit"."""
        self._load()
        clock = pygame.time.Clock()
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return "quit"
                if event.type == pygame.KEYDOWN \
                        and event.key == pygame.K_ESCAPE:
                    return "menu"
                if event.type == pygame.MOUSEBUTTONDOWN:
                    self._pane.press(flip_pos(event.pos, self._flip))
                elif event.type == pygame.MOUSEMOTION:
                    self._pane.motion(flip_pos(event.pos, self._flip))
                elif event.type == pygame.MOUSEBUTTONUP:
                    tap = self._pane.release(flip_pos(event.pos, self._flip))
                    if tap is not None and self._back_rect().collidepoint(tap):
                        return "menu"
            self._draw()
            flip_surface(self._screen, self._flip)
            pygame.display.flip()
            clock.tick(30)

    # ── data ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        from core import config_store
        self._profile  = config_store.profile(config_store.load())
        rows = load_rows(self._logs_dir)
        self._form     = compute_form(rows)
        self._sessions = len(rows)
        self._trophies = count_trophies(rows)
        self._records  = compute_records(rows)
        self._items    = self._build_items()
        self._pane = ScrollPane(self.H - self.HDR_H, self._content_h())

    # ── layout ───────────────────────────────────────────────────────────

    def _build_items(self) -> list:
        """Flat list of drawables ({kind, h, ...}); draw walks it in order."""
        # Identity hero (avatar + name + experience/discipline/goal), then the
        # derived form/records.
        items = [{"kind": "identity", "h": 92},
                 {"kind": "grade", "h": 116}]

        per_game = (self._form or {}).get("per_game") or []
        if per_game:
            items.append({"kind": "label", "text": "BY GAME", "h": 34})
            for pg in per_game:
                items.append({"kind": "game", "pg": pg, "h": 34})

        tiles = record_tiles(self._records)
        if tiles:
            items.append({"kind": "label", "text": "PERSONAL RECORDS",
                          "h": 40})
            # Two tiles per row.
            for i in range(0, len(tiles), 2):
                items.append({"kind": "tiles", "row": tiles[i:i + 2],
                              "h": 84 + self.GAP})
        else:
            items.append({"kind": "note",
                          "text": "Drive a few sessions to start building "
                                  "your records.", "h": 40})
        return items

    def _content_h(self) -> int:
        return self.GAP + sum(it["h"] for it in self._items) + self.PAD

    def _back_rect(self) -> pygame.Rect:
        return pygame.Rect(16, 14, 104, 36)

    # ── drawing ──────────────────────────────────────────────────────────

    def _draw(self) -> None:
        from dashboard.widgets import design_system as DS
        s = self._screen
        s.fill(DS.BG)
        right = (f"{self._sessions} SESSIONS  ·  {self._trophies} TROPHIES")
        self._draw_header("PROFILE", right)

        clip = s.get_clip()
        s.set_clip(pygame.Rect(0, self.HDR_H, self.W, self.H - self.HDR_H))
        y = self.HDR_H + self.GAP - self._pane.offset
        for it in self._items:
            if -it["h"] < y < self.H:
                self._draw_item(it, y)
            y += it["h"]
        s.set_clip(clip)

    def _draw_item(self, it: dict, y: int) -> None:
        from dashboard.widgets import design_system as DS
        s = self._screen
        kind = it["kind"]
        if kind == "identity":
            self._draw_identity(y)
        elif kind == "grade":
            self._draw_grade(y)
        elif kind == "label":
            s.blit(self._f_sub.render(it["text"], True, DS.TEXT3),
                   (self.PAD, y + 18))
        elif kind == "note":
            s.blit(self._f_body.render(it["text"], True, DS.TEXT4),
                   (self.PAD, y + 8))
        elif kind == "game":
            self._draw_game_row(it["pg"], y)
        elif kind == "tiles":
            self._draw_tile_row(it["row"], y)

    def _draw_identity(self, y: int) -> None:
        """Avatar + name + experience/discipline/goal — the declared identity
        the companion synced (or the Pi-only default)."""
        from core import avatar_render
        from dashboard.widgets import design_system as DS
        s = self._screen
        size = 72
        s.blit(avatar_render.avatar_surface(self._profile, size, self._f_name),
               (self.PAD, y))
        tx = self.PAD + size + 18
        s.blit(self._f_big.render(self._profile.get("name") or "Driver",
                                  True, DS.TEXT), (tx, y + 14))
        bits = (self._profile.get("experience"),
                self._profile.get("discipline"), self._profile.get("goal"))
        sub = "  ·  ".join(b.replace("_", " ").title() for b in bits if b)
        if sub:
            s.blit(self._f_body.render(sub, True, DS.TEXT3), (tx, y + 48))

    def _draw_grade(self, y: int) -> None:
        from dashboard.widgets import design_system as DS
        s = self._screen
        rect = pygame.Rect(16, y, self.W - 32, 104)
        pygame.draw.rect(s, DS.PANEL, rect, border_radius=14)
        pygame.draw.rect(s, DS.BORDER, rect, width=1, border_radius=14)

        form = self._form
        letter = form["letter"] if form else "—"
        g = self._f_grade.render(letter, True, DS.AMBER if form else DS.TEXT4)
        s.blit(g, (rect.x + 28, rect.centery - g.get_height() // 2))

        tx = rect.x + 28 + max(96, g.get_width() + 24)
        s.blit(self._f_sub.render("RECENT FORM", True, DS.TEXT3),
               (tx, rect.y + 22))
        if form:
            trend = form.get("trend")
            head = _TREND_WORD.get(trend, "Current form")
            hcol = getattr(DS, _TREND_COLOR.get(trend, "TEXT"), DS.TEXT)
            ht = self._f_big.render(head, True, hcol)
            s.blit(ht, (tx, rect.y + 40))
            if trend in ("up", "down"):
                self._draw_trend_tri(tx + ht.get_width() + 14,
                                     rect.y + 40 + ht.get_height() // 2,
                                     trend == "up", hcol)
            sub = f"Grade {form['letter']} over your last {form['n']} " \
                  f"session{'s' if form['n'] != 1 else ''}"
            s.blit(self._f_body.render(sub, True, DS.TEXT3), (tx, rect.y + 74))
        else:
            s.blit(self._f_big.render("No graded sessions yet", True,
                                      DS.TEXT2), (tx, rect.y + 44))

    def _draw_trend_tri(self, cx: int, cy: int, up: bool, color) -> None:
        r = 7
        pts = ([(cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)] if up
               else [(cx, cy + r), (cx - r, cy - r), (cx + r, cy - r)])
        pygame.draw.polygon(self._screen, color, pts)

    def _draw_game_row(self, pg: dict, y: int) -> None:
        from dashboard.widgets import design_system as DS
        s = self._screen
        name = _ellipsize(self._f_body, pg.get("game") or "—", self.W - 260)
        s.blit(self._f_body.render(name, True, DS.TEXT2), (self.PAD, y + 8))
        n = pg.get("n", 0)
        meta = f"{pg['letter']}   ·   {n} session{'s' if n != 1 else ''}"
        m = self._f_body.render(meta, True, DS.TEXT3)
        s.blit(m, m.get_rect(topright=(self.W - self.PAD, y + 8)))

    def _draw_tile_row(self, row: list, y: int) -> None:
        from dashboard.widgets import design_system as DS
        s = self._screen
        tw = (self.W - 32 - self.GAP) // 2
        for i, (caption, big, sub) in enumerate(row):
            x = 16 + i * (tw + self.GAP)
            rect = pygame.Rect(x, y, tw, 84)
            pygame.draw.rect(s, DS.PANEL2, rect, border_radius=12)
            pygame.draw.rect(s, DS.BORDER, rect, width=1, border_radius=12)
            s.blit(self._f_sub.render(caption, True, DS.TEXT3),
                   (rect.x + 16, rect.y + 12))
            big = _ellipsize(self._f_big, big, tw - 32)
            s.blit(self._f_big.render(big, True, DS.TEXT),
                   (rect.x + 16, rect.y + 30))
            if sub:
                sub = _ellipsize(self._f_sub, sub, tw - 32)
                s.blit(self._f_sub.render(sub, True, DS.TEXT4),
                       (rect.x + 16, rect.y + 62))

    def _draw_header(self, title: str, right: str = "") -> None:
        from dashboard.widgets import design_system as DS
        s = self._screen
        back = self._back_rect()
        pygame.draw.rect(s, DS.PANEL, back, border_radius=back.height // 2)
        pygame.draw.rect(s, DS.BORDER, back, width=1,
                         border_radius=back.height // 2)
        lbl = self._f_sub.render("‹  MENU", True, DS.TEXT3)
        s.blit(lbl, lbl.get_rect(center=back.center))
        limit = self.W - 16 - (self._f_sub.size(right)[0] + 24 if right else 0)
        title = _ellipsize(self._f_hdr, title, limit - (back.right + 16))
        t = self._f_hdr.render(title, True, DS.TEXT)
        s.blit(t, (back.right + 16, back.centery - t.get_height() // 2))
        if right:
            r = self._f_sub.render(right, True, DS.TEXT3)
            s.blit(r, r.get_rect(midright=(self.W - 16, back.centery)))
        pygame.draw.line(s, DS.BORDER, (0, self.HDR_H - 1),
                         (self.W, self.HDR_H - 1))
