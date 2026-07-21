"""Persistent JSON config — stores user preferences across sessions."""
import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.json')


def load() -> dict:
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(config: dict) -> None:
    with open(_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)


def last_game(config: dict) -> str:
    """The game id the driver last selected from the menu (empty if none).
    Persisted so the home "CONTINUE WITH" tile reflects the last game *chosen*
    rather than the last game that happened to produce a lap-based session
    record (Forza free-roam, for instance, logs no laps)."""
    return (config.get("last_game") or "").strip()


def set_last_game(config: dict, game_id: str) -> None:
    """Persist the last selected game id (see ``last_game``)."""
    config["last_game"] = game_id
    save(config)


_WINDOW_CHOICES = (1, 7, 30, -1)


def share_window_days(config: dict) -> int:
    """Share window (days; -1 = everything) with migration from the
    pre-v0.1.140 `log_retention_days` key. Retention used to DELETE old
    session files; the window only limits what the Share Logs API lists —
    files are always kept (they are the dashboard's history database).
    Unmapped legacy values (e.g. 90 days) fall back to the 7-day default.
    """
    value = config.get("share_window_days",
                       config.get("log_retention_days", 7))
    return value if value in _WINDOW_CHOICES else 7


_WEB_APP_MODES = ("off", "menu", "always")


def web_app_mode(config: dict) -> str:
    """When the browser-based web companion (served under /app on the log
    server) is reachable:

      "off"    — never; the /app routes are disabled.
      "menu"   — only while the game menu / settings are on screen (default) —
                 same lifetime as Share Logs, so a Pi 3 never runs the HTTP
                 server during 60fps gameplay.
      "always" — kept up during gameplay too, so a phone works mid-session.
                 For more powerful Pis; measure idle cost before relying on it.

    Unknown values fall back to the safe "menu" default."""
    value = (config.get("web_app_mode") or "menu").strip().lower()
    return value if value in _WEB_APP_MODES else "menu"


def author(config: dict) -> str:
    """Who to credit as the author of recorded track maps. Set the "author"
    key in config.json (there is no on-screen editor — the Pi has no keyboard);
    the companion can also stamp its own author on maps it edits. Empty by
    default, in which case saved maps carry no author."""
    return (config.get("author") or "").strip()


def api_token(config: dict) -> str:
    """The Share Logs API pairing token, generating and persisting one on
    first use. Shown as the pairing code on the DATA tab; the companion
    sends it as a Bearer token. Regenerate by deleting `api_token` from
    config.json (re-pairs every client)."""
    token = (config.get("api_token") or "").strip()
    if not token:
        import secrets
        token = secrets.token_hex(4).upper()   # 8 chars — typable pairing code
        config["api_token"] = token
        save(config)
    return token


# ── Driver profile (synced from the companion) ───────────────────────────────
# The companion is the only editor (the Pi has no keyboard); it pushes the
# declared profile on Session Sync. Stored under config["profile"]. The avatar
# is structured data (initials, or a helmet with base/visor/accent colours +
# pattern) — see sessionlog.avatar — so phone and Pi render it identically.

_PROFILE_FIELDS = ("name", "experience", "discipline", "goal",
                   "avatar_kind", "avatar_helmet", "updated")


def profile(config: dict) -> dict:
    """The declared driver profile, always complete.

    When nothing has been synced (a Pi-only driver who never uses the
    companion), returns a sensible default — the ``author`` name (or "Driver")
    and a visible default *helmet* avatar — so the profile card/screen always
    renders. Computed on read, not persisted; a later companion push (see
    ``set_profile``) replaces it.
    """
    from sessionlog import avatar
    stored = config.get("profile")
    has = isinstance(stored, dict) and bool(stored)
    p = stored if has else {}
    return {
        "name":          (p.get("name") or author(config) or "Driver"),
        "experience":    p.get("experience", ""),
        "discipline":    p.get("discipline", ""),
        "goal":          p.get("goal", ""),
        # A never-synced Pi defaults to a helmet (visible); a synced profile
        # keeps its own choice (initials or helmet).
        "avatar_kind":   avatar.normalise_kind(p.get("avatar_kind")) if has
                         else "helmet",
        "avatar_helmet": avatar.normalise_helmet(p.get("avatar_helmet")),
        "updated":       p.get("updated", ""),
    }


def set_profile(config: dict, incoming: dict) -> dict:
    """Store a companion-pushed profile (whitelisting known fields) and keep
    ``author`` in step with the name. Returns the cleaned profile."""
    from sessionlog import avatar
    src = incoming if isinstance(incoming, dict) else {}
    clean = {
        "name":          (src.get("name") or "").strip(),
        "experience":    (src.get("experience") or ""),
        "discipline":    (src.get("discipline") or ""),
        "goal":          (src.get("goal") or ""),
        "avatar_kind":   avatar.normalise_kind(src.get("avatar_kind")),
        "avatar_helmet": avatar.normalise_helmet(src.get("avatar_helmet")),
        "updated":       (src.get("updated") or ""),
    }
    config["profile"] = clean
    if clean["name"]:
        config["author"] = clean["name"]
    save(config)
    return clean
