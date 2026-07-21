"""Tests for core.log_server — share-window filtering, the sync badge,
and (v0.7.0) pairing-token auth + the PUT upload endpoint.

The share window (v0.1.140) limits what index.json lists and what counts
as "waiting to download"; it never deletes files (session CSVs are the
dashboard's history database).
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import pytest

from core.log_server import LogServer, _in_share_window, _save_synced, count_waiting


def _fname(days_ago: int, label: str = "practice") -> str:
    d = datetime.now() - timedelta(days=days_ago)
    return f"session_{d.strftime('%Y%m%d_%H%M')}_{label}.csv"


class TestInShareWindow:

    def test_no_window_shares_everything(self):
        assert _in_share_window(_fname(400), -1) is True

    def test_recent_file_inside_window(self):
        assert _in_share_window(_fname(2), 7) is True

    def test_old_file_outside_window(self):
        assert _in_share_window(_fname(10), 7) is False

    def test_suffixed_collision_filename_parses(self):
        d = datetime.now().strftime("%Y%m%d_%H%M")
        assert _in_share_window(f"session_{d}_race_2.csv", 1) is True

    def test_non_session_file_is_never_shared(self):
        assert _in_share_window("notes.csv", -1) is False
        assert _in_share_window(".sessions.db", -1) is False


class TestCountWaiting:

    def test_counts_only_windowed_unsynced(self, tmp_path):
        recent = _fname(1)
        old    = _fname(30)
        for f in (recent, old):
            (tmp_path / f).write_text("S,version,1\n")
        assert count_waiting(str(tmp_path), -1) == 2
        assert count_waiting(str(tmp_path), 7) == 1     # old one not waiting

    def test_synced_files_are_not_waiting(self, tmp_path):
        f = _fname(1)
        (tmp_path / f).write_text("S,version,1\n")
        _save_synced(str(tmp_path), {f})
        assert count_waiting(str(tmp_path), -1) == 0


class TestAuthAndUpload:
    """Live-server tests: every endpoint requires the pairing token, and
    PUT /<filename>.csv accepts companion uploads (ACC imports)."""

    TOKEN = "A1B2C3D4"
    CSV   = b"S,version,1\nS,game,acc\nH,lap_num,lap_time\nL,1,88.5\n"

    @pytest.fixture
    def server(self, tmp_path):
        ls = LogServer()
        ls.set_token(self.TOKEN)
        ls.start(str(tmp_path), port=0)          # ephemeral port
        port = ls._server.server_address[1]
        yield f"http://127.0.0.1:{port}", str(tmp_path)
        ls.stop()

    def _request(self, url, token=None, method="GET", body=None):
        req = urllib.request.Request(url, data=body, method=method)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_index_requires_token(self, server):
        base, _ = server
        assert self._request(f"{base}/index.json")[0] == 401
        assert self._request(f"{base}/index.json", token="WRONG")[0] == 401
        status, body = self._request(f"{base}/index.json", token=self.TOKEN)
        assert status == 200
        assert "sessions" in json.loads(body)

    def test_token_is_case_insensitive(self, server):
        base, _ = server
        status, _ = self._request(f"{base}/index.json", token="a1b2c3d4")
        assert status == 200

    def test_csv_get_requires_token(self, server):
        base, logs = server
        fname = _fname(0)
        with open(f"{logs}/{fname}", "wb") as f:
            f.write(self.CSV)
        assert self._request(f"{base}/{fname}")[0] == 401
        assert self._request(f"{base}/{fname}", token=self.TOKEN)[0] == 200

    def test_upload_roundtrip(self, server):
        base, logs = server
        fname = "session_20260707_2000_practice.csv"
        status, body = self._request(f"{base}/{fname}", token=self.TOKEN,
                                     method="PUT", body=self.CSV)
        assert status == 201
        assert json.loads(body)["ok"] is True
        with open(f"{logs}/{fname}", "rb") as f:
            assert f.read() == self.CSV
        # Pushed files never count as waiting to download
        assert count_waiting(logs, -1) == 0
        # …and can be fetched back
        assert self._request(f"{base}/{fname}", token=self.TOKEN)[0] == 200

    def test_upload_requires_token(self, server):
        base, logs = server
        status, _ = self._request(f"{base}/session_20260707_2000_race.csv",
                                  method="PUT", body=self.CSV)
        assert status == 401

    def test_upload_rejects_bad_names_and_content(self, server):
        base, _ = server
        assert self._request(f"{base}/evil.txt", token=self.TOKEN,
                             method="PUT", body=self.CSV)[0] in (400, 404)
        assert self._request(f"{base}/session_20260707_2000_race.csv",
                             token=self.TOKEN, method="PUT",
                             body=b"<html>not a csv</html>")[0] == 400

    def test_empty_token_fails_closed(self, tmp_path):
        ls = LogServer()                          # no set_token at all
        ls.start(str(tmp_path), port=0)
        port = ls._server.server_address[1]
        try:
            status, _ = self._request(
                f"http://127.0.0.1:{port}/index.json", token="")
            assert status == 401
        finally:
            ls.stop()


class TestTracks:
    """The /tracks endpoints (v0.19.0): pull the index / a map, push edits."""

    TOKEN = "T0K3NXYZ"

    def _map(self, track="Melbourne", game="f1_25"):
        return {
            "format_version": 1, "game": game, "track": track,
            "car_class": "formula1", "game_track_length_m": 5276.0,
            "left_edge": [[0, 0], [1, 1]], "right_edge": [[0, 1], [1, 2]],
            "racing_line": [[0, 0.5]], "racing_attempts": 3,
            "pit_lane": [[0, 0], [2, 2]], "sections": [{"turn": "1"}],
        }

    @pytest.fixture
    def server(self, tmp_path):
        ls = LogServer()
        ls.set_token(self.TOKEN)
        ls.set_tracks_dir(str(tmp_path))
        ls.start(str(tmp_path), port=0)
        port = ls._server.server_address[1]
        yield f"http://127.0.0.1:{port}", str(tmp_path)
        ls.stop()

    def _request(self, url, token=None, method="GET", body=None):
        req = urllib.request.Request(url, data=body, method=method)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_index_lists_written_tracks(self, server):
        base, tracks = server
        with open(f"{tracks}/f1-25_melbourne.json", "w") as f:
            json.dump(self._map(), f)
        assert self._request(f"{base}/tracks/index.json")[0] == 401   # needs token
        status, body = self._request(f"{base}/tracks/index.json", token=self.TOKEN)
        assert status == 200
        meta = json.loads(body)["tracks"]
        assert len(meta) == 1
        assert meta[0]["track"] == "Melbourne"
        assert meta[0]["has_pit"] is True
        assert meta[0]["section_count"] == 1

    def test_get_track_file(self, server):
        base, tracks = server
        with open(f"{tracks}/f1-25_melbourne.json", "w") as f:
            json.dump(self._map(), f)
        assert self._request(f"{base}/tracks/f1-25_melbourne.json")[0] == 401
        status, body = self._request(f"{base}/tracks/f1-25_melbourne.json",
                                     token=self.TOKEN)
        assert status == 200
        assert json.loads(body)["track"] == "Melbourne"
        assert self._request(f"{base}/tracks/nope.json", token=self.TOKEN)[0] == 404

    def test_put_track_roundtrip(self, server):
        base, tracks = server
        body = json.dumps(self._map("Suzuka")).encode()
        status, resp = self._request(f"{base}/tracks/f1-25_suzuka.json",
                                     token=self.TOKEN, method="PUT", body=body)
        assert status == 201
        assert json.loads(resp)["ok"] is True
        with open(f"{tracks}/f1-25_suzuka.json", "rb") as f:
            assert json.loads(f.read())["track"] == "Suzuka"
        # …and lists in the index
        _, idx = self._request(f"{base}/tracks/index.json", token=self.TOKEN)
        assert any(t["track"] == "Suzuka" for t in json.loads(idx)["tracks"])

    def test_put_requires_token(self, server):
        base, _ = server
        body = json.dumps(self._map()).encode()
        assert self._request(f"{base}/tracks/x.json",
                             method="PUT", body=body)[0] == 401

    def test_put_rejects_bad_json_and_names(self, server):
        base, _ = server
        # not JSON
        assert self._request(f"{base}/tracks/a.json", token=self.TOKEN,
                             method="PUT", body=b"nope")[0] == 400
        # valid JSON but not a track map
        assert self._request(f"{base}/tracks/b.json", token=self.TOKEN,
                             method="PUT",
                             body=json.dumps({"foo": 1}).encode())[0] == 400
        # path traversal / bad filename
        assert self._request(f"{base}/tracks/../evil.json", token=self.TOKEN,
                             method="PUT",
                             body=json.dumps(self._map()).encode())[0] in (400, 404)

    def test_unconfigured_tracks_dir(self, tmp_path):
        # A server whose tracks_dir was never set (the menu-path bug): PUT must
        # reject cleanly, and GET must NOT fall back to listing the cwd.
        ls = LogServer()
        ls.set_token(self.TOKEN)
        ls.start(str(tmp_path), port=0)          # note: no set_tracks_dir
        try:
            base = f"http://127.0.0.1:{ls._server.server_address[1]}"
            status, body = self._request(f"{base}/tracks/f1-25_x.json",
                                         token=self.TOKEN, method="PUT",
                                         body=json.dumps(self._map()).encode())
            assert status == 500
            assert b"not configured" in body
            _, idx = self._request(f"{base}/tracks/index.json", token=self.TOKEN)
            assert json.loads(idx)["tracks"] == []   # empty, not the cwd
            assert self._request(f"{base}/tracks/anything.json",
                                 token=self.TOKEN)[0] == 404
        finally:
            ls.stop()


class TestProfile:
    """The /profile.json endpoints: the companion pushes the declared driver
    profile (name + avatar) on Session Sync; the Pi serves it (or a default)."""

    TOKEN = "PR0F1LE0"

    @pytest.fixture
    def server(self, tmp_path, monkeypatch):
        # Point config storage at a temp file so tests never touch real config.
        from core import config_store
        monkeypatch.setattr(config_store, "_CONFIG_PATH",
                            str(tmp_path / "config.json"))
        ls = LogServer()
        ls.set_token(self.TOKEN)
        ls.start(str(tmp_path), port=0)
        port = ls._server.server_address[1]
        yield f"http://127.0.0.1:{port}"
        ls.stop()

    def _request(self, url, token=None, method="GET", body=None):
        req = urllib.request.Request(url, data=body, method=method)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_get_requires_token(self, server):
        assert self._request(f"{server}/profile.json")[0] == 401

    def test_default_profile_when_unset(self, server):
        status, body = self._request(f"{server}/profile.json", token=self.TOKEN)
        assert status == 200
        prof = json.loads(body)
        assert prof["name"] == "Driver"          # Pi-only default
        assert prof["avatar_kind"] == "helmet"   # visible default avatar
        assert prof["avatar_helmet"]["base"]     # complete helmet dict

    def test_put_then_get_roundtrip(self, server):
        payload = {
            "name": "Richard Hawes", "experience": "intermediate",
            "discipline": "formula", "goal": "consistency",
            "avatar_kind": "helmet",
            "avatar_helmet": {"base": "green", "visor": "amber",
                              "accent": "white", "pattern": "twin"},
            "updated": "2026-07-18T19:00:00", "bogus": "ignored",
        }
        status, body = self._request(f"{server}/profile.json", token=self.TOKEN,
                                     method="PUT",
                                     body=json.dumps(payload).encode())
        assert status == 200 and json.loads(body)["ok"] is True
        _, body = self._request(f"{server}/profile.json", token=self.TOKEN)
        prof = json.loads(body)
        assert prof["name"] == "Richard Hawes"
        assert prof["avatar_helmet"]["base"] == "green"
        assert prof["avatar_helmet"]["pattern"] == "twin"
        assert "bogus" not in prof

    def test_put_requires_token(self, server):
        assert self._request(f"{server}/profile.json", method="PUT",
                             body=b"{}")[0] == 401

    def test_put_rejects_bad_json(self, server):
        assert self._request(f"{server}/profile.json", token=self.TOKEN,
                             method="PUT", body=b"not json")[0] == 400


class TestWebCompanion:
    """The /app browser routes (v0.63.0): cookie auth (a valid ?key sets a
    session cookie and redirects), the off-mode gate, and that the Bearer API
    is unaffected. Pages themselves are covered by test_web_app.py."""

    TOKEN = "W3BT0K3N"

    @pytest.fixture
    def server(self, tmp_path):
        ls = LogServer()
        ls.set_token(self.TOKEN)
        ls.set_web_enabled(True)
        ls.start(str(tmp_path), port=0)
        port = ls._server.server_address[1]
        yield ls, f"http://127.0.0.1:{port}"
        ls.stop()

    def _get(self, url, cookie=None, redirect=True):
        import http.cookiejar
        handlers = []
        if not redirect:
            class _NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k):
                    return None
            handlers.append(_NoRedirect())
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(url)
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with opener.open(req, timeout=5) as resp:
                return resp.status, resp.read().decode(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), dict(e.headers)

    def test_no_cookie_is_friendly_gate_not_data(self, server):
        _, base = server
        status, body, _ = self._get(f"{base}/app")
        assert status == 200
        assert "Not paired" in body            # no data, invites a re-scan

    def test_valid_key_sets_cookie_and_redirects(self, server):
        _, base = server
        status, _, headers = self._get(f"{base}/app?key={self.TOKEN}",
                                       redirect=False)
        assert status == 302
        assert headers.get("Location") == "/app"
        assert "shfonic_web=" in headers.get("Set-Cookie", "")

    def test_bad_key_does_not_pair(self, server):
        _, base = server
        status, body, headers = self._get(f"{base}/app?key=WRONG",
                                          redirect=False)
        assert status == 200 and "Not paired" in body
        assert "Set-Cookie" not in headers

    def test_cookie_grants_access(self, server):
        from core import web_app
        _, base = server
        cookie = f"shfonic_web={web_app.session_cookie(self.TOKEN)}"
        status, body, _ = self._get(f"{base}/app", cookie=cookie)
        assert status == 200
        assert "Shfonic Dash" in body and "Not paired" not in body

    def test_css_served_with_cookie(self, server):
        from core import web_app
        _, base = server
        cookie = f"shfonic_web={web_app.session_cookie(self.TOKEN)}"
        status, body, headers = self._get(f"{base}/app/app.css", cookie=cookie)
        assert status == 200
        assert "text/css" in headers.get("Content-Type", "")
        assert "--amber" in body

    def test_trophy_detail_route_served(self, server):
        from core import web_app
        _, base = server
        cookie = f"shfonic_web={web_app.session_cookie(self.TOKEN)}"
        status, body, _ = self._get(f"{base}/app/trophy/century", cookie=cookie)
        assert status == 200
        assert "How to earn" in body and "/app/trophies" in body

    def test_off_mode_shows_disabled_page(self, server):
        from core import web_app
        ls, base = server
        ls.set_web_enabled(False)
        cookie = f"shfonic_web={web_app.session_cookie(self.TOKEN)}"
        status, body, _ = self._get(f"{base}/app", cookie=cookie)
        assert status == 200
        assert "Web companion is off" in body

    def _post(self, url, cookie=None, body=b""):
        req = urllib.request.Request(url, data=body, method="POST")
        if cookie:
            req.add_header("Cookie", cookie)

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(req, timeout=5) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_browse_route_serves(self, server):
        from core import web_app
        _, base = server
        cookie = f"shfonic_web={web_app.session_cookie(self.TOKEN)}"
        status, body, _ = self._get(f"{base}/app/browse", cookie=cookie)
        assert status == 200 and "Games" in body

    def test_hub_routes_serve(self, server):
        from core import web_app
        _, base = server
        cookie = f"shfonic_web={web_app.session_cookie(self.TOKEN)}"
        for p in ("/app/settings", "/app/driver", "/app/favourites", "/app/tracks"):
            status, _, _ = self._get(f"{base}{p}", cookie=cookie)
            assert status == 200, p

    def test_favourite_post_needs_cookie(self, server):
        _, base = server
        url = f"{base}/app/session/session_20260101_1200_race.csv/favourite"
        assert self._post(url) == 403                     # no cookie
        from core import web_app
        cookie = f"shfonic_web={web_app.session_cookie(self.TOKEN)}"
        assert self._post(url, cookie=cookie) == 303      # toggles + redirects

    def test_unknown_post_is_404(self, server):
        from core import web_app
        _, base = server
        cookie = f"shfonic_web={web_app.session_cookie(self.TOKEN)}"
        assert self._post(f"{base}/app/nope", cookie=cookie) == 404

    def test_line_viewer_404_without_data(self, server):
        from core import web_app
        _, base = server
        cookie = f"shfonic_web={web_app.session_cookie(self.TOKEN)}"
        status, _, _ = self._get(
            f"{base}/app/session/session_20260101_1200_hotlap.csv/lines",
            cookie=cookie)
        assert status == 404       # no such session / no racing-line data

    def test_session_path_traversal_blocked(self, server):
        from core import web_app
        _, base = server
        cookie = f"shfonic_web={web_app.session_cookie(self.TOKEN)}"
        status, _, _ = self._get(f"{base}/app/session/..%2f..%2fetc%2fpasswd",
                                 cookie=cookie)
        assert status == 404

    def test_bearer_api_unaffected(self, server):
        """The JSON API still authorises off the Bearer token, not the cookie."""
        _, base = server
        req = urllib.request.Request(f"{base}/index.json")
        req.add_header("Authorization", f"Bearer {self.TOKEN}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
        # …and a cookie does NOT open the API.
        from core import web_app
        req2 = urllib.request.Request(f"{base}/index.json")
        req2.add_header("Cookie", f"shfonic_web={web_app.session_cookie(self.TOKEN)}")
        try:
            urllib.request.urlopen(req2, timeout=5)
            assert False, "cookie should not authorise the JSON API"
        except urllib.error.HTTPError as e:
            assert e.code == 401
