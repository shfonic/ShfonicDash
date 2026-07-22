"""HTTP server that serves session CSV logs over LAN for the Pythonista companion app."""
import csv
import hashlib
import json
import os
import re
import socket
import threading
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

_PORT    = 8765
# Type label may contain underscores (sprint_qualifying); an optional numeric
# suffix disambiguates same-minute collisions (session_..._race_2.csv).
_FILE_RE = re.compile(r'^session_(\d{8})_(\d{4})_([a-z_]+?)(?:_(\d+))?\.csv$')

# Track map filenames are slugged as "<game>_<track>.json" (letters, digits,
# hyphen, underscore). No path separators — a flat tracks/ directory.
_TRACK_FILE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*\.json$')

# Filenames that have been served to a client at least once are recorded here so
# the menu can show how many sessions are still waiting to be downloaded.
_SYNCED_FILE = ".synced.json"


def _synced_path(logs_dir: str) -> str:
    return os.path.join(logs_dir, _SYNCED_FILE)


def _load_synced(logs_dir: str) -> set:
    try:
        with open(_synced_path(logs_dir)) as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_synced(logs_dir: str, synced: set) -> None:
    try:
        with open(_synced_path(logs_dir), "w") as f:
            json.dump(sorted(synced), f)
    except Exception:
        pass


def _in_share_window(filename: str, window_days: int) -> bool:
    """True when the session's date (from the filename) falls within the
    share window. window_days=-1 means no window (share everything).
    Non-session filenames are never shareable."""
    m = _FILE_RE.match(filename)
    if not m:
        return False
    if window_days < 0:
        return True
    try:
        stamp = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M")
    except ValueError:
        return False
    return (datetime.now() - stamp).days < window_days


def count_waiting(logs_dir: str, window_days: int = -1) -> int:
    """Number of shareable session CSVs never served to a client.

    Works whether or not the server is running — it reads the served set that
    the server persists on each successful CSV download. Sessions outside the
    share window aren't waiting: they will never be listed for download.
    """
    synced = _load_synced(logs_dir)
    try:
        names = [f for f in os.listdir(logs_dir) if _FILE_RE.match(f)]
    except Exception:
        return 0
    return sum(1 for f in names
               if f not in synced and _in_share_window(f, window_days))


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _session_meta(logs_dir: str, filename: str) -> dict | None:
    m = _FILE_RE.match(filename)
    if not m:
        return None
    d, t, session_type_fallback = m.group(1), m.group(2), m.group(3)
    iso_fallback = f"{d[:4]}-{d[4:6]}-{d[6:]}T{t[:2]}:{t[2:]}:00"

    path      = os.path.join(logs_dir, filename)
    meta      = {}
    lap_count = 0
    try:
        with open(path, newline="") as f:
            reader = csv.reader(f)
            first = next(reader, None)
            if first is None:
                return None
            if first[0] == "S":
                # New typed format: S rows are key-value metadata, L rows are laps
                if len(first) >= 3:
                    meta[first[1]] = first[2]
                for row in reader:
                    if not row:
                        continue
                    if row[0] == "S" and len(row) >= 3:
                        meta[row[1]] = row[2]
                    elif row[0] == "L":
                        lap_count += 1
            else:
                # Legacy flat format: first row is the CSV header
                headers = first
                for i, row in enumerate(reader):
                    if not row:
                        continue
                    if i == 0:
                        d2 = dict(zip(headers, row))
                        meta["car_class"]    = d2.get("car_class", "")
                        meta["car_name"]     = d2.get("car_name", "")
                        meta["track"]        = d2.get("track", "")
                        meta["session_type"] = d2.get("session_type", "")
                    lap_count += 1
    except Exception:
        pass

    return {
        "filename":     filename,
        "url":          f"/{filename}",
        "version":      int(meta.get("version", 0)),
        "session_type": meta.get("session_type", session_type_fallback),
        "session_subtype": meta.get("session_subtype", ""),
        "car_class":    meta.get("car_class", ""),
        "car_name":     meta.get("car_name", ""),
        "driver_name":  meta.get("driver_name", ""),
        "track":        meta.get("track", ""),
        "weather":      meta.get("weather", ""),
        "air_temp":     meta.get("air_temp", ""),
        "track_temp":   meta.get("track_temp", ""),
        "date":         meta.get("started_at", iso_fallback),
        "lap_count":    lap_count,
    }


def _track_meta(tracks_dir: str, filename: str) -> dict | None:
    """One-line summary of a saved track map for the /tracks index."""
    path = os.path.join(tracks_dir, filename)
    try:
        with open(path, "rb") as f:
            raw = f.read()
        obj = json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    lines = obj.get("lines")
    car_classes = sorted(lines.keys()) if isinstance(lines, dict) else []
    return {
        "filename":            filename,
        "url":                 f"/tracks/{filename}",
        "game":                obj.get("game", ""),
        "track":               obj.get("track", ""),
        "car_classes":         car_classes,
        "game_track_length_m": obj.get("game_track_length_m", 0),
        "has_pit":             bool(obj.get("pit_lane")),
        "section_count":       len(obj.get("sections") or []),
        "has_notes":           bool(obj.get("notes")),
        "author":              obj.get("author", ""),
        "updated":             obj.get("updated", ""),
        "sha":                 hashlib.sha256(raw).hexdigest(),
        "bytes":               len(raw),
    }


class _Handler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass  # suppress request logging to stdout

    # ── auth ─────────────────────────────────────────────────────────────
    # Every endpoint requires the pairing token (config_store.api_token,
    # shown on the DATA tab). The API is read/write from v0.7.0, so an
    # unauthenticated LAN client must get nothing at all.

    def _authorised(self) -> bool:
        import hmac
        expected = getattr(self.server, "api_token", "") or ""
        if not expected:
            return False   # server misconfigured — fail closed
        auth = self.headers.get("Authorization", "")
        supplied = auth[7:] if auth.startswith("Bearer ") else \
            self.headers.get("X-Api-Key", "")
        return hmac.compare_digest(supplied.strip().upper(),
                                   expected.strip().upper())

    def _reject(self, code: int, reason: str = ""):
        body = json.dumps({"error": reason}).encode() if reason else b""
        self.send_response(code)
        if code == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # The web companion (/app/...) is browser-facing and cannot send a
        # Bearer header on a navigation, so it authorises off a session cookie
        # instead — handled entirely in _serve_app, before the API's Bearer
        # gate below. The JSON/CSV API is unchanged.
        if self.path == "/app" or self.path.startswith("/app/") \
                or self.path.startswith("/app?"):
            self._serve_app()
            return
        if not self._authorised():
            self._reject(401, "pairing code required")
            return
        if self.path == "/index.json":
            self._serve_index()
        elif self.path == "/profile.json":
            self._serve_profile()
        elif self.path == "/tracks/index.json":
            self._serve_tracks_index()
        elif self.path.startswith("/tracks/") and self.path.endswith(".json"):
            self._serve_track(self.path[len("/tracks/"):])
        elif self.path.endswith(".csv") and "/" not in self.path.lstrip("/"):
            self._serve_csv(self.path.lstrip("/"))
        else:
            self.send_response(404)
            self.end_headers()

    # ── upload (v0.7.0) ──────────────────────────────────────────────────
    # PUT /<filename>.csv — the companion pushes sessions the Pi never
    # logged itself (AC/ACC screenshot imports). Same-named files are the
    # same session; overwriting is harmless (mirrors the manual copy-back).

    _MAX_UPLOAD       = 2 * 1024 * 1024   # 2 MB — sessions are tens of KB
    _MAX_TRACK_UPLOAD = 1 * 1024 * 1024   # 1 MB — track maps are ~tens of KB

    def do_PUT(self):
        if not self._authorised():
            self._reject(401, "pairing code required")
            return
        if self.path == "/profile.json":
            self._put_profile()
            return
        if self.path.startswith("/tracks/"):
            self._put_track(self.path[len("/tracks/"):])
            return
        filename = self.path.lstrip("/")
        if "/" in filename or not _FILE_RE.match(filename):
            self._reject(400, "filename must be session_*.csv")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if not 0 < length <= self._MAX_UPLOAD:
            self._reject(413, "bad content length")
            return
        body = self.rfile.read(length)
        if not body.startswith(b"S,"):
            self._reject(400, "not a typed-row session CSV")
            return
        path = os.path.join(self.server.logs_dir, filename)
        try:
            with open(path, "wb") as f:
                f.write(body)
        except OSError:
            self._reject(500, "could not write file")
            return
        # Pushed BY the companion — never list it as waiting to sync.
        self._mark_synced(filename)
        out = json.dumps({"ok": True, "filename": filename}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def _serve_index(self):
        logs_dir = self.server.logs_dir
        window   = self.server.window_days
        sessions = []
        try:
            for fname in sorted(os.listdir(logs_dir), reverse=True):
                if not _in_share_window(fname, window):
                    continue
                meta = _session_meta(logs_dir, fname)
                if meta:
                    sessions.append(meta)
        except Exception:
            pass
        body = json.dumps({
            "sessions":    sessions,
            "server_time": datetime.now().isoformat(timespec="seconds"),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── web companion (v0.63.0) ──────────────────────────────────────────
    # Mobile HTML mirror of the Pythonista companion, served under /app on the
    # same port/token. Browsers can't send the Bearer header on a navigation,
    # so the QR carries ?key=<token> once: we validate it, set a session cookie
    # (HMAC of the token) and 302 to strip the key from the URL/history; all
    # later navigation authorises off the cookie. Fail-closed like the API —
    # no token configured, no access.

    def _send_html(self, status: int, html: str, extra=()):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _cookie_token(self):
        raw = self.headers.get("Cookie", "")
        if not raw:
            return ""
        try:
            jar = SimpleCookie()
            jar.load(raw)
        except Exception:
            return ""
        from core import web_app
        morsel = jar.get(web_app.COOKIE_NAME)
        return morsel.value if morsel else ""

    def do_POST(self):
        """Cookie-authed web-companion actions: favourite toggle + track-map
        save. (The JSON/CSV sync API uses PUT with Bearer auth, unchanged.)
        Non-/app POST isn't used; reject it."""
        from core import web_app
        path = urlsplit(self.path).path
        token = getattr(self.server, "api_token", "") or ""
        authed = (getattr(self.server, "web_enabled", True) and token
                  and web_app.cookie_valid(self._cookie_token(), token))
        if not (path.startswith("/app/") and authed):
            self._reject(403, "forbidden")
            return
        fav = re.match(r"^/app/session/(session_[^/]+\.csv)/favourite$", path)
        save = re.match(r"^/app/track/([A-Za-z0-9][A-Za-z0-9_-]*\.json)/save$", path)
        if fav:
            self._web_toggle_favourite(fav.group(1))
        elif save:
            self._web_save_track(save.group(1))
        elif path == "/app/driver/save":
            self._web_save_driver()
        else:
            self._reject(404, "not found")

    def _web_save_driver(self):
        """Save the driver profile edited in the web form (URL-encoded body)."""
        from urllib.parse import parse_qs
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        body = self.rfile.read(length) if 0 < length <= 65536 else b""
        form = parse_qs(body.decode("utf-8", "replace"))

        def g(k):
            return (form.get(k) or [""])[0]
        incoming = {
            "name": g("name"), "experience": g("experience"),
            "discipline": g("discipline"), "goal": g("goal"),
            "avatar_kind": g("avatar_kind"),
            "avatar_helmet": {"base": g("helmet_base"), "visor": g("helmet_visor"),
                              "accent": g("helmet_accent"), "pattern": g("helmet_pattern")},
        }
        try:
            from core import config_store
            config_store.set_profile(config_store.load(), incoming)
        except Exception:
            import logging
            logging.getLogger("log_server").exception("driver save failed")
        self.send_response(303)
        self.send_header("Location", "/app/driver")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _web_toggle_favourite(self, filename: str):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length:
            self.rfile.read(length)
        try:
            from sessionlog import records
            records.set_cache_dir(self.server.logs_dir)
            records.set_favourite(filename, not records.is_favourite(filename))
        except Exception:
            import logging
            logging.getLogger("log_server").exception("favourite toggle failed")
        self.send_response(303)
        self.send_header("Location", f"/app/session/{filename}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _web_save_track(self, filename: str):
        """Write an edited track map from the web editor. Same validation as the
        Bearer PUT /tracks/ path, but cookie-authed for the browser."""
        tracks_dir = self._tracks_dir()
        if not tracks_dir:
            self._reject(500, "tracks not configured")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if not 0 < length <= self._MAX_TRACK_UPLOAD:
            self._reject(413, "bad content length")
            return
        body = self.rfile.read(length)
        try:
            obj = json.loads(body)
        except ValueError:
            self._reject(400, "body is not valid JSON")
            return
        if (not isinstance(obj, dict) or "format_version" not in obj
                or not any(obj.get(k) for k in
                           ("left_edge", "right_edge", "lines", "sections"))):
            self._reject(400, "not a track map")
            return
        try:
            os.makedirs(tracks_dir, exist_ok=True)
            with open(os.path.join(tracks_dir, filename), "wb") as f:
                f.write(body)
        except OSError:
            self._reject(500, "could not write file")
            return
        out = json.dumps({"ok": True, "filename": filename}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def _serve_app(self):
        from core import web_app
        if not getattr(self.server, "web_enabled", True):
            self._send_html(200, web_app.render_shell(
                "Web companion off",
                '<div class=card><p class=label>Web companion is off</p>'
                '<p class=muted>Enable it under SETTINGS → DATA on the '
                'dashboard.</p></div>'))
            return
        token = getattr(self.server, "api_token", "") or ""
        split = urlsplit(self.path)
        path  = split.path
        query = parse_qs(split.query)

        # Home-screen assets are public: the browser fetches the manifest (and the
        # icons it names) without credentials, so they sit outside the cookie
        # gate. Both are non-sensitive brand assets.
        if path == "/app/manifest.webmanifest":
            body = web_app.APP_MANIFEST.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/app/img/app-icon.png":
            self._serve_app_image("app-icon.png")
            return

        # Pairing: a valid ?key= sets the cookie and redirects to the clean URL.
        key = (query.get("key") or [""])[0]
        if token and web_app.key_valid(key, token):
            cookie = (f"{web_app.COOKIE_NAME}={web_app.session_cookie(token)}; "
                      "Path=/app; HttpOnly; SameSite=Strict; Max-Age=31536000")
            self.send_response(302)
            self.send_header("Location", path)      # same path, key stripped
            self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if not (token and web_app.cookie_valid(self._cookie_token(), token)):
            # Friendly gate (200, no data) rather than a raw 401 — a stale
            # bookmark should invite a re-scan, not look broken.
            self._send_html(200, web_app.render_shell(
                "Pair", '<div class=card><p class=label>Not paired</p>'
                '<p class=muted>Open this page by scanning the QR code on the '
                'dashboard’s SETTINGS → DATA screen.</p></div>'))
            return

        logs_dir = self.server.logs_dir
        try:
            if path in ("/app", "/app/"):
                self._send_html(200, web_app.render_home(logs_dir))
            elif path == "/app/app.css":
                body = web_app.APP_CSS.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/app/sessions":
                game = (query.get("game") or [None])[0]
                self._send_html(200, web_app.render_sessions(logs_dir, game))
            elif path == "/app/browse":
                sel = {k: (query.get(k) or [None])[0] for k in ("g", "c", "t", "s")}
                self._send_html(200, web_app.render_browse(logs_dir, sel))
            elif path == "/app/favourites":
                self._send_html(200, web_app.render_favourites(logs_dir))
            elif path == "/app/trophies":
                self._send_html(200, web_app.render_trophies(logs_dir))
            elif path.startswith("/app/trophy/"):
                bid = unquote(path[len("/app/trophy/"):])
                self._send_html(200, web_app.render_trophy(logs_dir, bid))
            elif path == "/app/journal":
                m = (query.get("m") or [None])[0]
                self._send_html(200, web_app.render_journal(logs_dir, m))
            elif path == "/app/status.json":
                body = web_app.render_status(logs_dir).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/app/settings":
                self._send_html(200, web_app.render_settings())
            elif path == "/app/driver":
                self._send_html(200, web_app.render_driver(logs_dir))
            elif path.startswith("/app/img/"):
                self._serve_app_image(path[len("/app/img/"):])
            elif path == "/app/tracks":
                self._send_html(200, web_app.render_tracks(self._tracks_dir()))
            elif path.startswith("/app/track/") and path.endswith("/map"):
                fname = unquote(path[len("/app/track/"):-len("/map")])
                page = web_app.render_track_viewer(self._tracks_dir(), fname)
                if page is None:
                    self._send_html(404, web_app.render_shell(
                        "Not found", '<p class="empty">Unknown track map.</p>'))
                else:
                    self._send_html(200, page)
            elif path.startswith("/app/session/") and path.endswith("/share"):
                filename = unquote(path[len("/app/session/"):-len("/share")])
                if not _FILE_RE.match(filename):
                    self._send_html(404, web_app.render_shell(
                        "Not found", '<p class="empty">Unknown session.</p>'))
                else:
                    self._send_html(200, web_app.render_share(logs_dir, filename))
            elif path.startswith("/app/session/") and path.endswith("/lines"):
                filename = unquote(path[len("/app/session/"):-len("/lines")])
                if not _FILE_RE.match(filename):
                    self._send_html(404, web_app.render_shell(
                        "Not found", '<p class="empty">Unknown session.</p>'))
                    return
                page = web_app.render_line_viewer(logs_dir, filename)
                if page is None:
                    self._send_html(404, web_app.render_shell(
                        "No map", '<p class="empty">No racing-line data recorded '
                        'for this session.</p>'))
                else:
                    self._send_html(200, page)
            elif path.startswith("/app/session/"):
                filename = unquote(path[len("/app/session/"):])
                if not _FILE_RE.match(filename):
                    self._send_html(404, web_app.render_shell(
                        "Not found", '<p class="empty">Unknown session.</p>'))
                else:
                    self._send_html(200,
                                    web_app.render_session(logs_dir, filename))
            else:
                self._send_html(404, web_app.render_shell(
                    "Not found", '<p class="empty">Page not found.</p>'))
        except Exception:
            import logging
            logging.getLogger("log_server").exception("web app render failed")
            self._send_html(500, web_app.render_shell(
                "Error", '<p class="empty">Something went wrong rendering '
                'this page.</p>'))

    # Helmet avatar mask PNGs (shared with the Pi dashboard + companion) — the
    # web avatar composites these in-browser via CSS masks + the profile tints.
    _APP_IMAGES = {"helmet.png", "helmet_visor.png", "helmet_trim.png",
                   "logo-dark.png", "logo-light.png", "app-icon.png"}

    def _serve_app_image(self, name: str):
        if name not in self._APP_IMAGES:
            self.send_response(404)
            self.end_headers()
            return
        path = os.path.join(os.path.dirname(__file__), "..",
                            "dashboard", "images", name)
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _serve_csv(self, filename: str):
        if not _FILE_RE.match(filename):
            self.send_response(404)
            self.end_headers()
            return
        path = os.path.join(self.server.logs_dir, filename)
        if not os.path.isfile(path):
            self.send_response(404)
            self.end_headers()
            return
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self._mark_synced(filename)

    # ── driver profile ───────────────────────────────────────────────────
    # GET returns the declared profile the companion pushes (name + avatar +
    # experience/discipline/goal), or a sensible default for a Pi-only driver.
    # PUT stores a companion push (phone is the only editor).

    def _serve_profile(self):
        from core import config_store
        payload = config_store.profile(config_store.load())
        payload["server_time"] = datetime.now().isoformat(timespec="seconds")
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _put_profile(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if not 0 < length <= self._MAX_TRACK_UPLOAD:
            self._reject(413, "bad content length")
            return
        try:
            incoming = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._reject(400, "invalid JSON")
            return
        if not isinstance(incoming, dict):
            self._reject(400, "expected a profile object")
            return
        from core import config_store
        clean = config_store.set_profile(config_store.load(), incoming)
        out = json.dumps({"ok": True, "profile": clean}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    # ── tracks (v0.19.0) ─────────────────────────────────────────────────
    # Recorded circuit maps under tracks/. GET the index / a file to pull;
    # PUT <name>.json to push companion edits (labelled sections, tweaks).

    def _tracks_dir(self) -> str:
        return getattr(self.server, "tracks_dir", "") or ""

    def _serve_tracks_index(self):
        tracks_dir = self._tracks_dir()
        tracks = []
        try:
            for fname in (sorted(os.listdir(tracks_dir)) if tracks_dir else []):
                if fname == "index.json" or not _TRACK_FILE_RE.match(fname):
                    continue
                meta = _track_meta(tracks_dir, fname)
                if meta:
                    tracks.append(meta)
        except Exception:
            pass
        body = json.dumps({
            "tracks":      tracks,
            "server_time": datetime.now().isoformat(timespec="seconds"),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_track(self, filename: str):
        tracks_dir = self._tracks_dir()
        if not tracks_dir or not _TRACK_FILE_RE.match(filename):
            self.send_response(404)
            self.end_headers()
            return
        path = os.path.join(tracks_dir, filename)
        if not os.path.isfile(path):
            self.send_response(404)
            self.end_headers()
            return
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _put_track(self, filename: str):
        if not _TRACK_FILE_RE.match(filename):
            self._reject(400, "filename must be <name>.json")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if not 0 < length <= self._MAX_TRACK_UPLOAD:
            self._reject(413, "bad content length")
            return
        body = self.rfile.read(length)
        try:
            obj = json.loads(body)
        except ValueError:
            self._reject(400, "body is not valid JSON")
            return
        if (not isinstance(obj, dict) or "format_version" not in obj
                or not any(obj.get(k) for k in
                           ("left_edge", "right_edge", "lines", "sections"))):
            self._reject(400, "not a track map")
            return
        tracks_dir = self._tracks_dir()
        if not tracks_dir:
            self._reject(500, "tracks not configured")
            return
        try:
            os.makedirs(tracks_dir, exist_ok=True)
            with open(os.path.join(tracks_dir, filename), "wb") as f:
                f.write(body)
        except OSError:
            self._reject(500, "could not write file")
            return
        out = json.dumps({"ok": True, "filename": filename}).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def _mark_synced(self, filename: str):
        logs_dir = self.server.logs_dir
        with self.server.synced_lock:
            synced = _load_synced(logs_dir)
            if filename not in synced:
                synced.add(filename)
                _save_synced(logs_dir, synced)


class LogServer:

    def __init__(self):
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._ip    = ""
        self._port  = _PORT
        self._window_days = -1
        self._api_token   = ""
        self._tracks_dir  = ""
        self._web_enabled = True

    def set_web_enabled(self, enabled: bool) -> None:
        """Whether the browser web companion (/app) is served. False disables
        the HTML routes even while the server runs for Share Logs sync.
        Applies to a running server immediately."""
        self._web_enabled = bool(enabled)
        if self._server:
            self._server.web_enabled = self._web_enabled

    def set_tracks_dir(self, tracks_dir: str) -> None:
        """Directory of recorded track maps served/accepted under /tracks/.
        Applies to a running server immediately."""
        self._tracks_dir = tracks_dir or ""
        if self._server:
            self._server.tracks_dir = self._tracks_dir

    def set_window(self, window_days: int) -> None:
        """Set the share window (days; -1 = everything). Applies to the
        running server immediately — the DATA tab changes it live."""
        self._window_days = window_days
        if self._server:
            self._server.window_days = window_days

    def set_token(self, token: str) -> None:
        """Set the pairing token every request must carry (fail-closed:
        an empty token rejects everything)."""
        self._api_token = token or ""
        if self._server:
            self._server.api_token = self._api_token

    def start(self, logs_dir: str, port: int = _PORT) -> None:
        if self._server:
            return
        self._port = port
        self._ip   = _lan_ip()
        server             = ThreadingHTTPServer(("", port), _Handler)
        server.logs_dir    = logs_dir
        server.tracks_dir  = self._tracks_dir
        server.window_days = self._window_days
        server.api_token   = self._api_token
        server.web_enabled = self._web_enabled
        server.synced_lock = threading.Lock()
        self._server       = server
        self._thread    = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
            self._ip     = ""

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        """Returns 'IP:PORT' when running, empty string otherwise."""
        return f"{self._ip}:{self._port}" if self._server else ""
