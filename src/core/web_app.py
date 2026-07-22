"""Server-rendered web companion — the Pi's session archive as mobile HTML.

A third renderer over the shared ``sessionlog`` engine (alongside the on-Pi
pygame browsers and the Pythonista companion): drivers who can't run the
companion scan a QR on the DATA tab and open these pages in any phone browser
on the LAN. Every number is computed through ``sessionlog`` + the records
index, so the web app, the Pi's own summary screens and the companion agree.

Deliberately small and pure-stdlib: no framework, no build step, f-string
templates, near-zero client JS. Functions here return HTML strings;
``core.log_server`` owns the HTTP plumbing (routing, the cookie auth flow, and
writing the bytes). The look mirrors the companion's design tokens (see the
companion ``theme.py``) so the pages match the apps in light and dark.

Pages (companion parity):
  /app                              driver profile (form, records)
  /app/sessions[?game=]             flat session list, filled badges + grades
  /app/browse[?g=&c=&t=&s=]         drill-down: Game > Class > Track > Type
  /app/session/<file>               lap detail: grade/pace/trend header, lap
                                    table (tyre + delta + flag sectors),
                                    position-by-lap / lap-time-progress chart,
                                    the driven-line minimap, engineer notes
  /app/session/<file>/lines         the full zoomable session line viewer
                                    (vendored session_viewer.html + baked data)

Auth (helpers here, plumbing in log_server): ``/app`` is gated by a session
cookie whose value is an HMAC of the pairing token — the QR carries
``?key=<token>`` once, the server validates it, sets the cookie and redirects.
"""

import hashlib
import hmac
import html
import logging
import os

log = logging.getLogger("web_app")

COOKIE_NAME = "shfonic_web"

_VIEWER_HTML = os.path.join(os.path.dirname(__file__), "session_viewer.html")
_TRACK_HTML = os.path.join(os.path.dirname(__file__), "track_viewer.html")


# ── auth helpers ────────────────────────────────────────────────────────────

def session_cookie(token: str) -> str:
    """Opaque cookie value proving possession of the pairing token — an HMAC of
    a fixed label under the token, so the raw token never lands in the cookie
    jar or browser history."""
    return hmac.new(token.encode(), b"shfonic-web-session",
                    hashlib.sha256).hexdigest()


def cookie_valid(value: str, token: str) -> bool:
    if not token or not value:
        return False
    return hmac.compare_digest(value, session_cookie(token))


def key_valid(key: str, token: str) -> bool:
    if not token or not key:
        return False
    return hmac.compare_digest(key.strip().upper(), token.strip().upper())


# ── small helpers ───────────────────────────────────────────────────────────

def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _fmt_date(dt) -> str:
    try:
        return dt.strftime("%a %d %b %Y · %H:%M")
    except Exception:
        return ""


def _fmt_day(dt) -> str:
    try:
        return dt.strftime("%d %b %Y · %H:%M")
    except Exception:
        return ""


# Session-type badge language (mirrors the companion theme.py).
_BADGE_TEXT = {
    "race": "RACE", "qualifying": "QUALI", "practice": "PRACTICE",
    "hotlap": "HOTLAP", "sprint_qualifying": "SPRINT Q",
}
_BADGE_CLASS = {
    "race": "b-race", "qualifying": "b-quali", "practice": "b-practice",
    "hotlap": "b-hotlap", "sprint_qualifying": "b-quali",
}
_GAME_ABBR = {
    "f1_25": "F1 25", "pcars2": "PC2", "fh6": "FORZA H", "fm": "FORZA M",
    "acc": "ACC", "ac": "AC", "gt7": "GT7",
}
_RACE_TYPES = ("race", "sprint")


def _badge(session_type: str, subtype: str = "") -> str:
    st = (session_type or "").strip().lower()
    txt = _BADGE_TEXT.get(subtype or st, (subtype or st or "?").upper())
    cls = _BADGE_CLASS.get(st, "b-other")
    return f'<span class="badge {cls}">{_esc(txt)}</span>'


def _grade_class(letter: str) -> str:
    return {"A": "g-a", "B": "g-b", "C": "g-c", "D": "g-d", "F": "g-f"}.get(
        (letter or " ")[0].upper(), "g-none")


def _flag_class(flag: str) -> str:
    return {"magenta": "f-magenta", "purple": "f-purple", "green": "f-green",
            "yellow": "f-yellow", "red": "f-red"}.get(flag or "", "")


# ── page shell + stylesheet ─────────────────────────────────────────────────
# Palette lifted verbatim from the companion theme.py DARK/LIGHT palettes so
# the web app reads as the same product.

APP_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&display=swap');
/* shfonic design system — mono-first, flat, border-led, oklch palette.
   Dark is default; light via [data-theme=light] or the system in auto. */
:root{
  --bg:oklch(0.16 0.006 250); --panel:oklch(0.19 0.006 250);
  --panel2:oklch(0.225 0.008 250); --border:oklch(0.30 0.008 250);
  --border-soft:oklch(0.24 0.008 250);
  --text:oklch(0.94 0.004 80); --text2:oklch(0.72 0.006 80);
  --text3:oklch(0.55 0.008 250); --text4:oklch(0.42 0.008 250);
  --amber:oklch(0.82 0.13 75); --amber-ink:oklch(0.20 0.04 75);
  --green:oklch(0.78 0.14 145); --red:oklch(0.70 0.16 25);
  --blue:oklch(0.72 0.10 230);
  --purple:oklch(0.66 0.19 300); --magenta:oklch(0.72 0.22 350);
  --orange:oklch(0.76 0.14 55);
  --mono:'IBM Plex Mono',ui-monospace,'SF Mono',SFMono-Regular,Menlo,Consolas,monospace;
  --sans:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --rad-sm:3px; --rad:4px; --rad-lg:8px;
}
:root[data-theme=light],
:root[data-theme=auto]{color-scheme:light dark}
@media (prefers-color-scheme:light){
  :root:not([data-theme=dark]):not([data-theme=light]){
    --bg:oklch(0.97 0.004 80); --panel:oklch(0.94 0.005 80);
    --panel2:oklch(0.905 0.005 80); --border:oklch(0.84 0.006 80);
    --border-soft:oklch(0.90 0.005 80);
    --text:oklch(0.18 0.006 250); --text2:oklch(0.36 0.008 250);
    --text3:oklch(0.52 0.008 250); --text4:oklch(0.66 0.008 250);
    --amber:oklch(0.55 0.14 50); --amber-ink:oklch(0.97 0.004 80);
    --green:oklch(0.52 0.15 150); --red:oklch(0.55 0.19 25);
    --blue:oklch(0.50 0.13 240);
    --purple:oklch(0.47 0.20 300); --magenta:oklch(0.55 0.24 350);
    --orange:oklch(0.55 0.15 55);
  }
}
:root[data-theme=light]{
  --bg:oklch(0.97 0.004 80); --panel:oklch(0.94 0.005 80);
  --panel2:oklch(0.905 0.005 80); --border:oklch(0.84 0.006 80);
  --border-soft:oklch(0.90 0.005 80);
  --text:oklch(0.18 0.006 250); --text2:oklch(0.36 0.008 250);
  --text3:oklch(0.52 0.008 250); --text4:oklch(0.66 0.008 250);
  --amber:oklch(0.55 0.14 50); --amber-ink:oklch(0.97 0.004 80);
  --green:oklch(0.52 0.15 150); --red:oklch(0.55 0.19 25);
  --blue:oklch(0.50 0.13 240);
  --purple:oklch(0.47 0.20 300); --magenta:oklch(0.55 0.24 350);
  --orange:oklch(0.55 0.15 55);
}
*{box-sizing:border-box}
html,body{margin:0}
body{zoom:var(--fscale,1)}
body{background:color-mix(in oklch, var(--text) 5%, var(--bg));color:var(--text);
  font-family:var(--mono);font-size:13px;font-feature-settings:"ss01","ss02","zero","calt";
  -webkit-font-smoothing:antialiased;line-height:1.5;padding-bottom:48px;
  overflow-x:hidden;font-variant-numeric:tabular-nums}
::selection{background:var(--amber);color:var(--amber-ink)}
a{color:inherit;text-decoration:none}
.wrap{max-width:520px;margin:0 auto;padding:0 16px}
header.top{position:sticky;top:0;z-index:5;background:var(--bg);
  border-bottom:1px solid var(--border);padding:12px 0}
header.top .wrap{display:flex;align-items:center;gap:12px}
.brand{flex:0 0 auto;display:flex;align-items:center}
.brand .logo{height:20px;max-height:20px;width:auto;max-width:140px;display:block}
nav.tabs{margin-left:auto;display:flex;gap:14px;flex:0 0 auto}
nav.tabs a{font-size:11px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--text3);padding:4px 0}
nav.tabs a.on{color:var(--amber)}
main{padding-top:16px}
h1.page{font-size:11px;letter-spacing:.18em;text-transform:uppercase;
  color:var(--text3);margin:2px 0 12px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--rad-lg);
  padding:16px;margin-bottom:12px}
.sublabel{font-size:10px;color:var(--text3);margin:-4px 0 8px}
.label{font-size:10px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--text3);margin:0 0 10px}
.muted{color:var(--text3)}
.mono{font-family:var(--mono)}
.track-title{font-weight:600;letter-spacing:0;text-transform:uppercase;line-height:1.1}
/* outlined session-type chip — flat, border-led (the DS look) */
.badge{font-size:9px;font-weight:500;letter-spacing:.14em;text-transform:uppercase;
  padding:2px 7px;border-radius:var(--rad-sm);white-space:nowrap;display:inline-block;
  background:transparent;border:1px solid var(--text3);color:var(--text3)}
.badge.b-race{border-color:var(--red);color:var(--red)}
.badge.b-quali{border-color:var(--purple);color:var(--purple)}
.badge.b-practice{border-color:var(--amber);color:var(--amber)}
.badge.b-hotlap{border-color:var(--green);color:var(--green)}
.badge.b-other{border-color:var(--text3);color:var(--text3)}
.grade{font-weight:600}
.g-a{color:var(--green)} .g-b{color:var(--amber)} .g-c{color:var(--orange)}
.g-d{color:var(--red)} .g-f{color:var(--red)} .g-none{color:var(--text4)}
/* profile grade hero */
.hero{display:flex;align-items:center;gap:20px}
.hero .letter{font-weight:600;font-size:52px;line-height:1}
.hero .trend{font-size:18px;font-weight:600;margin:0}
.hero .trend.up{color:var(--green)} .hero .trend.down{color:var(--red)}
.hero .meta{color:var(--text3);font-size:13px;margin-top:3px}
.pills{display:flex;gap:8px;margin-top:6px;flex-wrap:wrap}
.pill{font-size:11px;color:var(--text2);background:transparent;
  border:1px solid var(--border);padding:3px 9px;border-radius:var(--rad-sm)}
.tiles{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tile{background:var(--panel);border:1px solid var(--border);border-radius:var(--rad);padding:13px}
.tile .cap{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--text3)}
.tile .big{font-size:19px;font-weight:600;margin:5px 0 2px}
.tile .sub{font-size:12px;color:var(--text4)}
.pg{display:flex;justify-content:space-between;padding:9px 0;border-top:1px solid var(--border-soft)}
.pg .r{color:var(--text3);font-size:13px}
/* game filter chips — outlined */
.chips{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:14px}
.chip{font-size:12px;letter-spacing:.04em;color:var(--text3);background:transparent;
  border:1px solid var(--border);padding:5px 11px;border-radius:var(--rad-sm)}
.chip.on{color:var(--amber);border-color:var(--amber)}
/* full-bleed list: cancel the wrap gutter so hairline dividers span edge-to-edge */
.flush{margin-left:-16px;margin-right:-16px}
/* flush section (no card box) — the prototype is border-led, not boxed */
.sec{padding:18px 0 4px;border-top:1px solid var(--border)}
.sec.first{border-top:none;padding-top:6px}
/* session rows — flush, hairline-separated (no card) */
.srow{display:block;padding:13px 16px;border-bottom:1px solid var(--border-soft);background:transparent}
.srow:active{background:color-mix(in oklch, var(--text) 5%, transparent)}
.srow .r1,.srow .r3{display:flex;align-items:center;gap:9px;font-size:11px;color:var(--text3)}
.srow .r2{display:flex;align-items:baseline;gap:10px;margin:5px 0 3px}
.srow .spacer{margin-left:auto}
.srow .score{font-size:12px;color:var(--text3)}
.srow .name{font-size:15px;font-weight:600;text-transform:uppercase;letter-spacing:0;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1}
.srow .best{font-size:16px;font-weight:600;color:var(--magenta);white-space:nowrap}
.srow .best.notrec{color:var(--purple)}
.srow .best.plain{color:var(--text)}
.srow .ok{color:var(--green)}
/* drill rows */
.drow{display:flex;align-items:center;gap:12px;background:var(--panel);
  border:1px solid var(--border);border-radius:var(--rad);padding:14px;margin-bottom:10px}
.drow .d-name{font-weight:500;font-size:14px;flex:1;min-width:0;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.drow .d-meta{color:var(--text3);font-size:11px;text-align:right;white-space:nowrap}
.drow .chev{color:var(--text3);font-size:15px}
.crumbs{font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--text3);margin-bottom:12px}
.crumbs a{color:var(--amber)}
.combotitle{font-size:21px;font-weight:600;text-transform:uppercase;line-height:1.1}
.combosub{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--text3);margin-top:3px}
/* detail header */
.dhead .top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.dhead .loc{color:var(--text3);font-size:12px}
.dhead .facts{font-size:12px;margin-top:8px;line-height:1.75}
.dhead .best{color:var(--magenta)} .dhead .theo{color:var(--green)}
.dhead .overall{color:var(--purple)} .dhead .up{color:var(--green)} .dhead .down{color:var(--red)}
/* lap table */
.tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table.laps{width:100%;border-collapse:collapse;font-size:13px}
table.laps th{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--text3);
  text-align:right;padding:7px 7px;font-weight:400}
table.laps th:first-child,table.laps td:first-child{text-align:left}
table.laps td{text-align:right;padding:9px 7px;border-top:1px solid var(--border-soft);vertical-align:top}
table.laps td.lapn{color:var(--text3);width:34px}
table.laps td:nth-child(2){font-weight:600;font-size:14px}
table.laps tr.inv td:first-child{box-shadow:inset 3px 0 0 var(--red)}
.f-magenta{color:var(--magenta)} .f-purple{color:var(--purple)} .f-green{color:var(--green)}
.f-yellow{color:var(--amber)} .f-red{color:var(--red)}
.delta{display:block;font-size:11px;margin-top:1px}
.delta.pos{color:var(--red)} .delta.neg{color:var(--green)}
.tyre{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;
  border-radius:var(--rad-sm);font-size:9px;font-weight:600;color:#111;margin-right:6px;vertical-align:middle}
/* charts + minimap */
.chart{width:100%;height:auto;display:block}
.chart .ln{stroke:var(--amber);fill:none;stroke-width:1.5;stroke-linejoin:round}
.chart .dot{fill:var(--amber)}
.chart text{font-weight:500;font-size:11px;fill:var(--text3)}
.chart text.big{font-size:12px;fill:var(--text2)}
.mapcard{position:relative;display:block}
.mapcard .hint{position:absolute;left:0;right:0;bottom:8px;text-align:center;
  font-size:11px;color:var(--text3)}
.note{margin:0 0 15px}
.notep{margin:0;color:var(--text2);font-size:13px;line-height:1.6}
.thumbs{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}
.thumb{width:104px}
.cthumb{width:104px;height:70px;display:block;background:var(--panel2);
  border:1px solid var(--border);border-radius:var(--rad-sm)}
.tlabel{font-size:10px;color:var(--text3);text-align:center;margin-top:3px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.me{color:var(--amber)}
.empty{color:var(--text3);text-align:center;padding:44px 0;font-size:13px}
footer.foot{color:var(--text4);font-size:11px;text-align:center;margin-top:22px;letter-spacing:.05em}
.viewlink{display:inline-block;margin-top:6px;font-size:12px;color:var(--amber)}
/* driver hub home */
.driver{display:flex;align-items:flex-start;gap:16px}
.driver .av{flex:0 0 auto;width:72px;height:72px}
.driver .who{flex:1;min-width:0}
.driver .who .nm{font-size:22px;font-weight:600;line-height:1.15}
.driver .who .id{color:var(--text3);font-size:13px;margin-top:2px}
.driver .ov{text-align:right;flex:0 0 auto}
.driver .ov .lg{font-weight:600;font-size:44px;line-height:1}
.driver .ov .cap{font-size:10px;letter-spacing:.14em;color:var(--text3)}
.driver .ov .tr{font-size:13px;font-weight:600}
.driver .ov .tr.up{color:var(--green)} .driver .ov .tr.down{color:var(--red)}
.statgrid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:14px}
.statgrid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
.stat2{background:var(--panel);border:1px solid var(--border);border-radius:var(--rad);padding:13px;position:relative}
.stat2.tap{border-color:var(--amber)}
.stat2 .cap{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--text3)}
.stat2 .v{font-size:21px;font-weight:600;margin-top:6px}
.stat2 .v.mono{font-weight:600}
.stat2 .chev{position:absolute;top:11px;right:12px;color:var(--amber)}
.profile{margin-bottom:12px}
.profile .ptitle{font-size:10px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--text3);margin-bottom:8px}
.prow{display:flex;justify-content:space-between;align-items:baseline;
  gap:12px;padding:6px 0;font-size:13px;border-top:1px solid var(--border-soft)}
.prow:first-of-type{border-top:none}
.prow .pk{color:var(--text2)}
.prow .pv{font-weight:600;text-align:right;color:var(--text)}
.prow .pv.mag{color:var(--magenta)} .prow .pv.grn{color:var(--green)} .prow .pv.pur{color:var(--purple)}
.prow .stars{letter-spacing:1px}
.prow .stars .on{color:var(--amber)} .prow .stars .off{color:var(--text4)}
.recent{background:transparent;border:none;border-bottom:1px solid var(--border-soft);
  padding:13px 16px;margin:0 -16px;display:flex;align-items:center;gap:10px}
.recent .rc{flex:1;min-width:0}
.recent .rcap{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--text3)}
.recent .rt{font-size:16px;font-weight:600;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.recent .rs{color:var(--text3);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.recent .chev{color:var(--amber);font-size:18px}
.btnrow{display:flex;gap:10px;margin-top:14px}
.bigbtn{flex:1;text-align:center;padding:13px;border-radius:var(--rad);border:1px solid var(--amber);
  color:var(--amber);font-weight:500;font-size:13px;letter-spacing:.08em;text-transform:uppercase;background:transparent}
.bigbtn.solid{background:var(--amber);color:var(--amber-ink);border-color:var(--amber)}
.bigbtn.ghost{border-color:var(--border);color:var(--text2)}
/* sub-tabs (sessions: SESSIONS/GAMES/FAVOURITES) */
.subtabs{display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:14px}
.subtabs a{flex:1;text-align:center;font-size:11px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--text3);padding:11px 4px;border-bottom:2px solid transparent}
.subtabs a.on{color:var(--text);border-bottom-color:var(--amber)}
/* settings */
.optrow{display:flex;gap:8px;margin:8px 0 16px}
.opt{flex:1;text-align:center;font-size:12px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--text3);background:transparent;border:1px solid var(--border);
  padding:11px 6px;border-radius:var(--rad);cursor:pointer;user-select:none}
.opt.on{color:var(--amber);border-color:var(--amber)}
.gear{font-size:16px;line-height:1;padding:2px 0}
/* trophies */
.badges{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.badge2{display:block;background:var(--panel);border:1px solid var(--border);border-radius:var(--rad);
  padding:14px 8px;text-align:center;position:relative;color:var(--text)}
.badge2:active{border-color:var(--amber)}
.tmedal{display:flex;align-items:center;gap:14px}
.tinfo{min-width:0}
.tname{font-size:18px;font-weight:600}
.tstatus{font-size:12px;color:var(--text3);margin-top:3px}
.notes-p{margin:0 0 8px;color:var(--text2);font-size:13px;line-height:1.6}
.viewback{display:inline-block;color:var(--amber);font-size:13px;margin-bottom:10px}
.bmedal{width:52px;height:52px;margin:0 auto 8px;border-radius:50%;border:2px solid var(--amber);
  display:flex;align-items:center;justify-content:center;font-size:24px;background:var(--panel2)}
.bname{font-size:12px;font-weight:500;line-height:1.25}
.bcount{position:absolute;top:8px;right:10px;font-size:11px;color:var(--amber)}
/* journal */
.jentry{display:block;position:relative;background:var(--panel);border:1px solid var(--border);
  border-radius:var(--rad);padding:13px 28px 14px 15px;margin-bottom:12px}
.jentry:active{border-color:var(--amber)}
.jmeta{font-size:11px;font-weight:600;letter-spacing:.08em;color:var(--text3);margin-bottom:6px}
.jbody{margin:0;color:var(--text2);font-size:14px;line-height:1.6}
.jchev{position:absolute;right:12px;top:50%;transform:translateY(-50%);
  color:var(--text4);font-size:20px;line-height:1}
.jday{font-size:12px;font-weight:600;letter-spacing:.12em;color:var(--text3);
  margin:18px 0 10px}
/* month pager — arrows hug the edges with a big tap target, space beneath */
.monthbar{display:flex;align-items:center;justify-content:space-between;margin:2px 0 20px}
.monthbar .mnav{flex:0 0 auto;padding:10px 22px;margin:-10px 0;font-size:26px;
  font-weight:600;line-height:1;color:var(--amber);text-align:center}
.monthbar .mnav.off{color:var(--text4)}
.monthbar .ml{flex:1;text-align:center;font-size:14px;font-weight:600;
  letter-spacing:.12em;color:var(--text)}
/* new-session banner */
#newses{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:50;
  display:none;background:var(--amber);color:var(--amber-ink);font-weight:500;font-size:13px;
  letter-spacing:.04em;padding:11px 18px;border-radius:var(--rad);cursor:pointer;border:none}
#newses.show{display:block}
/* share button + screen */
.sharebtn{display:inline-block;background:transparent;border:1px solid var(--border);color:var(--amber);
  border-radius:var(--rad);font-size:12px;letter-spacing:.06em;padding:8px 14px;cursor:pointer;
  font-family:var(--mono);white-space:nowrap}
.sharearea{width:100%;background:var(--panel2);border:1px solid var(--border);border-radius:var(--rad);
  color:var(--text2);font-family:var(--mono);font-size:11px;line-height:1.55;padding:12px;resize:vertical;margin-top:10px}
.sharemore{margin-top:14px}
.sharemore>summary{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--text3);
  cursor:pointer;list-style:none;padding:8px 0}
.sharemore>summary::-webkit-details-marker{display:none}
.sharemore>summary::before{content:"▸ ";color:var(--amber)}
.sharemore[open]>summary::before{content:"▾ "}
/* driver editor */
.field{margin:0 0 14px}
.field label{display:block;font-size:10px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--text3);margin-bottom:6px}
.field input[type=text],.field select{width:100%;background:var(--panel2);border:1px solid var(--border);
  border-radius:var(--rad);color:var(--text);font-size:15px;padding:11px 12px;font-family:var(--mono);
  -webkit-appearance:none;appearance:none}
.field select{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='7'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%23888' stroke-width='1.5' fill='none'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 12px center}
.swatches{display:flex;gap:8px;flex-wrap:wrap}
.swatches label{width:32px;height:32px;border-radius:50%;cursor:pointer;
  border:2px solid transparent;box-sizing:border-box}
.swatches input{position:absolute;opacity:0;pointer-events:none}
.swatches input:checked + span{outline:2px solid var(--text);outline-offset:2px}
.swatches span{display:block;width:100%;height:100%;border-radius:50%;border:1px solid rgba(0,0,0,.3)}
.savebtn{width:100%;padding:14px;border-radius:var(--rad);border:none;background:var(--amber);
  color:var(--amber-ink);font-weight:600;font-size:14px;letter-spacing:.06em;text-transform:uppercase;cursor:pointer}
/* tracks list */
.trow{display:flex;align-items:center;gap:12px;background:var(--panel);border:1px solid var(--border);
  border-radius:var(--rad);padding:13px 15px;margin-bottom:10px}
.trow .tc{flex:1;min-width:0}
.trow .tn{font-weight:600;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.trow .tmeta{color:var(--text3);font-size:11px;margin-top:2px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
"""


# Bootstrap applied before paint: restore theme + text size so pages never flash
# the wrong appearance. Prefs are saved in cookies (persist, sent to the server)
# with a localStorage fallback for older saves. `savePref` writes both; the
# settings page calls it. Cookies are scoped to /app and readable by JS (not
# HttpOnly — they're display prefs, not the auth token).
_THEME_JS = (
    "<script>(function(){"
    "function ck(n){var m=document.cookie.match('(?:^|; )'+n+'=([^;]*)');"
    "return m?decodeURIComponent(m[1]):null;}"
    "function ap(){try{"
    "var t=ck('sf_theme')||localStorage.getItem('shfonic_theme')||'auto';"
    "var f=parseFloat(ck('sf_fs')||localStorage.getItem('shfonic_fs'))||1;"
    "var r=document.documentElement;"
    "if(t==='light'||t==='dark')r.setAttribute('data-theme',t);else r.removeAttribute('data-theme');"
    "r.style.setProperty('--fscale',f);"
    "}catch(e){}}"
    "window.applyPrefs=ap;"
    "window.getPref=function(k){return ck(k)||localStorage.getItem("
    "k==='sf_theme'?'shfonic_theme':'shfonic_fs');};"
    "window.savePref=function(k,v){try{"
    "document.cookie=k+'='+encodeURIComponent(v)+';path=/app;max-age=31536000;samesite=strict';"
    "localStorage.setItem(k==='sf_theme'?'shfonic_theme':'shfonic_fs',v);"
    "}catch(e){}ap();};"
    "ap();})();</script>")


_CSS_VER = None


def _css_version() -> str:
    """A short content hash of APP_CSS, appended to the stylesheet URL so any
    CSS change busts the browser cache automatically (the CSS itself stays
    cacheable). Without this, an edit never reaches an already-loaded phone."""
    global _CSS_VER
    if _CSS_VER is None:
        import hashlib
        _CSS_VER = hashlib.md5(APP_CSS.encode("utf-8")).hexdigest()[:10]
    return _CSS_VER


def render_shell(title: str, body: str, active: str = "") -> str:
    def _tab(href, key, label):
        on = " on" if key == active else ""
        return f'<a class="tab{on}" href="{href}">{label}</a>'
    nav = (_tab("/app", "home", "Profile")
           + _tab("/app/sessions", "sessions", "Sessions")
           + _tab("/app/tracks", "tracks", "Tracks")
           + f'<a class="tab gear{" on" if active == "settings" else ""}" '
             f'href="/app/settings" title="Settings">&#9881;</a>')
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<meta name=color-scheme content='dark light'>"
        f"<title>{_esc(title)} · Shfonic Dash</title>"
        f"{_THEME_JS}"
        f"<link rel=stylesheet href=/app/app.css?v={_css_version()}></head><body>"
        "<header class=top><div class=wrap>"
        "<a class=brand href=/app aria-label='Shfonic Dash'>"
        "<img id=logo class=logo height=22 src='/app/img/logo-dark.png' alt='Shfonic Dash'>"
        "</a>"
        f"<nav class=tabs>{nav}</nav></div></header>"
        f"<main><div class=wrap>{body}</div></main>"
        "<footer class=foot>Served from your Raspberry Pi over the local network</footer>"
        '<button id=newses onclick="location.reload()">New session available · Refresh</button>'
        + _POLL_JS + "</body></html>")


# Poll a cheap status endpoint so a freshly-driven session flags itself instead
# of relying on a manual refresh (works whether the server ran through the
# session — web_app_mode "always" — or came back at the menu). The banner shows
# on any change from the baseline captured on first poll.
_POLL_JS = (
    "<script>(function(){var base=null;function p(){"
    "fetch('/app/status.json',{cache:'no-store'}).then(function(r){return r.json();})"
    ".then(function(s){var sig=s.count+'|'+s.latest;"
    "if(base===null)base=sig;else if(sig!==base)"
    "document.getElementById('newses').classList.add('show');})"
    ".catch(function(){});}setInterval(p,15000);p();})();</script>")


def render_status(logs_dir: str) -> str:
    """Cheap freshness signal for the new-session poller (count + newest file)."""
    import json
    try:
        names = [f for f in os.listdir(logs_dir)
                 if f.startswith("session_") and f.endswith(".csv")]
    except OSError:
        names = []
    return json.dumps({"count": len(names), "latest": max(names) if names else ""})


# ── engine loading + per-row grading ────────────────────────────────────────

def _load_rows(logs_dir: str) -> list:
    from core.profile_browser import load_rows
    return load_rows(logs_dir)


def _grade_of(rec):
    """Grade one records row the way profile_browser.compute_form does — off the
    index row (no re-parse), so a list can grade every session cheaply."""
    try:
        from sessionlog import grading
        from sessionlog import records as db
        pb = db.prior_best(rec.get("game"), rec.get("car_class"),
                           rec.get("track"), rec.get("session_type"),
                           rec.get("date"), rec.get("filename", ""))
        return grading.grade(rec, prior_best=pb)
    except Exception:
        return None


# ── page: home (driver profile) ─────────────────────────────────────────────

_AV_COLOURS = None


def _hex(key, fallback="red"):
    global _AV_COLOURS
    if _AV_COLOURS is None:
        from sessionlog import avatar
        _AV_COLOURS = avatar
    r, g, b = _AV_COLOURS.colour_rgb(key, fallback)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _pattern_gradient(pattern, accent) -> str:
    """CSS gradient for a helmet accent pattern, matching avatar_render's crown
    bands (fractions of the helmet box). Empty for solid/none."""
    if pattern == "stripe":
        return f"linear-gradient(#0000 12%,{accent} 12% 28%,#0000 28%)"
    if pattern == "twin":
        return (f"linear-gradient(#0000 10%,{accent} 10% 18%,#0000 18% 26%,"
                f"{accent} 26% 34%,#0000 34%)")
    if pattern == "halo":
        return f"linear-gradient(#0000 2%,{accent} 2% 13%,#0000 13%)"
    return ""


def _avatar_html(profile, px=76) -> str:
    """Driver avatar reusing the SAME helmet mask PNGs the Pi and companion use
    (served at /app/img/…), composited in the browser via CSS masks + the
    profile's tint colours — so the three apps render one identity, not a
    reinvented one. Initials fall back to the amber disc."""
    from sessionlog import avatar
    kind = avatar.normalise_kind(profile.get("avatar_kind"))
    if kind != "helmet":
        ini = avatar.initials(profile.get("name") or "") or "?"
        return (f'<div class=av style="width:{px}px;height:{px}px;border-radius:50%;'
                f'flex:0 0 auto;background:#f59e1a;display:flex;align-items:center;'
                f'justify-content:center">'
                f'<span style="font:800 {int(px*0.42)}px system-ui;color:#141418">'
                f'{_esc(ini)}</span></div>')
    h = avatar.normalise_helmet(profile.get("avatar_helmet"))
    base, visor, accent = _hex(h["base"]), _hex(h["visor"], "blue"), _hex(h["accent"], "white")

    def _layer(mask, bg):
        return (f'<i style="position:absolute;inset:14%;background:{bg};'
                f'-webkit-mask:url(/app/img/{mask}) center/contain no-repeat;'
                f'mask:url(/app/img/{mask}) center/contain no-repeat"></i>')
    grad = _pattern_gradient(h.get("pattern"), accent)
    pat = (f'<i style="position:absolute;inset:14%;background:{grad};'
           f'-webkit-mask:url(/app/img/helmet.png) center/contain no-repeat;'
           f'mask:url(/app/img/helmet.png) center/contain no-repeat"></i>') if grad else ""
    return (f'<div class=av style="position:relative;width:{px}px;height:{px}px;'
            f'border-radius:50%;overflow:hidden;flex:0 0 auto;background:#ccd1e0">'
            f'{_layer("helmet.png", base)}{pat}'
            f'{_layer("helmet_visor.png", visor)}{_layer("helmet_trim.png", "#ffffff")}</div>')


def render_home(logs_dir: str) -> str:
    from core import config_store
    from core.profile_browser import compute_form, compute_records, count_trophies
    profile = config_store.profile(config_store.load())
    rows = _load_rows(logs_dir)
    form = compute_form(rows)
    rec = compute_records(rows) or {}
    sessions, trophies = len(rows), count_trophies(rows)

    name = _esc(profile.get("name") or "Driver")
    bits = [b.replace("_", " ").title()
            for b in (profile.get("experience"), profile.get("discipline"),
                      profile.get("goal")) if b]
    ident = f'<div class=id>{_esc(" · ".join(bits))}</div>' if bits else ""

    if form:
        trend = form.get("trend")
        tcls = {"up": "up", "down": "down"}.get(trend, "")
        tword = {"up": "Improving", "down": "Slipping"}.get(trend, "Holding steady")
        tri = {"up": "▲ ", "down": "▼ "}.get(trend, "")
        ov = (f'<div class="lg {_grade_class(form["letter"])}">{_esc(form["letter"])}</div>'
              f'<div class=cap>OVERALL</div>'
              f'<div class="tr {tcls}">{tri}{tword}</div>')
    else:
        ov = '<div class="lg g-none">—</div><div class=cap>OVERALL</div>'

    # driver hero (taps through to the driver editor) — flush, no card box
    driver = (
        f'<a class="sec first driver" href="/app/driver">'
        f'{_avatar_html(profile)}'
        f'<div class=who><div class=nm>{name}</div>{ident}</div>'
        f'<div class=ov>{ov}</div></a>')

    # stat tiles — companion layout
    def _tile(cap, val, cls="", href=None, chev=False):
        inner = (f'<div class=cap>{cap}</div><div class="v {cls}">{_esc(val)}</div>'
                 + ('<span class=chev>&#8250;</span>' if chev else ''))
        if href:
            return f'<a class="stat2 tap" href="{href}">{inner}</a>'
        return f'<div class=stat2>{inner}</div>'

    dist = rec.get("total_distance_km")
    cons = rec.get("consistency")
    streak = rec.get("clean_streak")
    fav_car = rec.get("favourite_car")
    fav_trk = rec.get("most_sessions")
    row1 = (_tile("SESSIONS", str(sessions), href="/app/sessions", chev=True)
            + _tile("TROPHIES", str(trophies), href="/app/trophies", chev=True)
            + _tile("DISTANCE", f'{dist:,.0f} km' if dist else "—", "mono"))
    row2 = (_tile("FAV CAR", (fav_car or {}).get("name", "—"))
            + _tile("CLEAN RUN", f'{streak["value"]} laps' if streak else "—", "mono"))
    row3 = (_tile("FAV TRACK", (fav_trk or {}).get("name", "—"))
            + _tile("CONSISTENCY", f'±{cons["value"]:.2f}s' if cons else "—", "mono"))
    tiles = (f'<div class=statgrid3>{row1}</div>'
             f'<div class=statgrid2>{row2}</div>'
             f'<div class=statgrid2>{row3}</div>')

    body = driver + f'<div class=sec>{tiles}</div>'
    body += _recent_block(rows)
    body += ('<div class="sec btnrow">'
             '<a class="bigbtn ghost" href="/app/journal">Journal</a>'
             '<a class="bigbtn ghost" href="/app/trophies">Trophies</a>'
             '<a class="bigbtn" href="/app/tracks">Tracks</a></div>')
    return render_shell("Profile", body, "home")


def _recent_block(rows) -> str:
    from sessionlog import circuits
    if not rows:
        return ""
    out = ['<h1 class=page style="margin-top:18px">Recent</h1>']
    # latest session
    r = rows[0]
    from sessionlog import circuits
    trk = circuits.display_name(r.get("game"), r.get("track")) or r.get("track") or ""
    g = _grade_of(r)
    gl = f'{g["letter"]} · ' if (g and g.get("letter")) else ""
    laps = r.get("lap_count") or 0
    when = r.get("date").strftime("%d %b %Y") if r.get("date") else ""
    out.append(
        f'<a class=recent href="/app/session/{_esc(r["filename"])}">'
        f'<div class=rc><div class=rcap>LATEST SESSION</div>'
        f'<div class=rt>{_esc(gl)}{_esc(trk)}</div>'
        f'<div class=rs>{laps} laps · {_esc(when)}</div></div>'
        f'<span class=chev>&#8250;</span></a>')
    # latest milestone
    try:
        from sessionlog import grading
        latest = grading.latest_milestone(rows)
    except Exception:
        latest = None
    if latest:
        record, ms = latest
        m = ms[0]
        icon = {"🏆": "🏆", "⭐": "⭐", "🔥": "🔥"}.get(m.get("icon", ""), "🏆")
        trk2 = circuits.display_name(record.get("game"), record.get("track")) \
            or record.get("track") or ""
        out.append(
            f'<a class=recent href="/app/session/{_esc(record.get("filename",""))}">'
            f'<div class=rc><div class=rcap>LATEST MILESTONE</div>'
            f'<div class=rt>{icon} {_esc(m.get("title",""))}</div>'
            f'<div class=rs>{_esc(m.get("detail",""))} · {_esc(trk2)}</div></div>'
            f'<span class=chev>&#8250;</span></a>')
    return "".join(out)


# ── page: settings (theme + text size, per-browser via localStorage) ────────

def render_settings() -> str:
    script = (
        "<script>(function(){"
        "function sel(g,v){[].forEach.call(g.children,function(o){"
        "o.classList.toggle('on',o.dataset.v===v);});}"
        "var t=document.getElementById('opt-theme'),f=document.getElementById('opt-fs');"
        "sel(t,window.getPref('sf_theme')||'auto');"
        "sel(f,window.getPref('sf_fs')||'1');"
        "t.addEventListener('click',function(e){var o=e.target.closest('.opt');if(!o)return;"
        "window.savePref('sf_theme',o.dataset.v);sel(t,o.dataset.v);});"
        "f.addEventListener('click',function(e){var o=e.target.closest('.opt');if(!o)return;"
        "window.savePref('sf_fs',o.dataset.v);sel(f,o.dataset.v);});"
        "})();</script>")
    body = (
        '<h1 class=page>Settings</h1>'
        '<div class="sec first"><p class=label>Appearance</p>'
        '<div class=optrow id=opt-theme>'
        '<div class=opt data-v=auto>Auto</div>'
        '<div class=opt data-v=light>Light</div>'
        '<div class=opt data-v=dark>Dark</div></div>'
        '<p class=label>Text size</p>'
        '<div class=optrow id=opt-fs>'
        '<div class=opt data-v="1">Small</div>'
        '<div class=opt data-v="1.15">Medium</div>'
        '<div class=opt data-v="1.32">Large</div></div>'
        '<p class=muted style="font-size:12px">Saved in cookies on this device.</p></div>'
        '<div class=sec><p class=label>Web companion</p>'
        '<p class=muted>These pages are served from your Raspberry Pi over the local '
        'network. To turn the web companion off, or keep it running during gameplay, '
        'use <b>SETTINGS → DATA</b> on the dashboard itself.</p></div>'
        + script)
    return render_shell("Settings", body, "settings")


# ── page: driver profile (read; editor is companion/app-side) ───────────────

# Driver-identity option vocabulary is canonical in sessionlog.profile (shared
# with the companion) — never re-listed here.
def _identity_opts(field):
    from sessionlog import profile
    return profile.options(field)


def render_driver(logs_dir: str) -> str:
    """Editable driver identity (name, experience/discipline/goal, helmet) that
    saves back to the Pi, plus the read-only profile stats (grade, records)."""
    from sessionlog import avatar
    from core import config_store
    from core.profile_browser import (compute_form, compute_records,
                                       count_trophies, record_tiles)
    profile = config_store.profile(config_store.load())
    rows = _load_rows(logs_dir)
    form = compute_form(rows)
    tiles = record_tiles(compute_records(rows))
    sessions, trophies = len(rows), count_trophies(rows)
    helmet = avatar.normalise_helmet(profile.get("avatar_helmet"))
    kind = avatar.normalise_kind(profile.get("avatar_kind"))

    preview = (f'<div style="display:flex;align-items:center;gap:16px;margin-bottom:16px">'
               f'{_avatar_html(profile)}<div><div style="font-size:22px;font-weight:800">'
               f'{_esc(profile.get("name") or "Driver")}</div>'
               f'<div class=muted style="font-size:13px">Editing your driver profile</div></div></div>')

    def _text(field, value):
        return (f'<div class=field><label>{field.title()}</label>'
                f'<input type=text name={field} value="{_esc(value)}"></div>')

    def _select(field, value):
        opts = ['<option value="">—</option>']
        for val, label in _identity_opts(field):
            sel = " selected" if val == value else ""
            opts.append(f'<option value="{_esc(val)}"{sel}>{_esc(label)}</option>')
        return (f'<div class=field><label>{field.title()}</label>'
                f'<select name={field}>{"".join(opts)}</select></div>')

    def _swatches(name_, current):
        cells = ""
        for key, _label, rgb in avatar.COLOURS:
            checked = " checked" if key == current else ""
            hexc = f"#{int(rgb[0]*255):02x}{int(rgb[1]*255):02x}{int(rgb[2]*255):02x}"
            cells += (f'<label><input type=radio name={name_} value={key}{checked}>'
                      f'<span style="background:{hexc}"></span></label>')
        return f'<div class=swatches>{cells}</div>'

    def _radios(name_, current, options):
        return " ".join(
            f'<label style="margin-right:14px;font-family:var(--mono);font-size:13px">'
            f'<input type=radio name={name_} value={k}{" checked" if k == current else ""}> {v}</label>'
            for k, v in options)

    form_html = (
        f'<form method=post action="/app/driver/save" class=card>'
        f'<p class=label>Driver</p>{preview}'
        + _text("name", profile.get("name") or "")
        + _select("experience", profile.get("experience") or "")
        + _select("discipline", profile.get("discipline") or "")
        + _select("goal", profile.get("goal") or "")
        + '<p class=label style="margin-top:8px">Avatar</p>'
        + f'<div class=field>{_radios("avatar_kind", kind, avatar.VALID_KINDS and [("initials","Initials"),("helmet","Helmet")])}</div>'
        + f'<div class=field><label>Helmet shell</label>{_swatches("helmet_base", helmet["base"])}</div>'
        + f'<div class=field><label>Visor</label>{_swatches("helmet_visor", helmet["visor"])}</div>'
        + f'<div class=field><label>Accent</label>{_swatches("helmet_accent", helmet["accent"])}</div>'
        + f'<div class=field><label>Pattern</label>{_radios("helmet_pattern", helmet["pattern"], avatar.PATTERNS)}</div>'
        + '<button class=savebtn type=submit>Save profile</button></form>')

    # read-only stats below the editor
    ov = (f'<div class="lg {_grade_class(form["letter"])}">{_esc(form["letter"])}</div>'
          '<div class=cap>OVERALL</div>') if form else ""
    stats = (f'<div class="card driver"><div class=who>'
             f'<div class=pills><span class=pill>{sessions} SESSIONS</span>'
             f'<span class=pill>{trophies} TROPHIES</span></div></div>'
             f'<div class=ov>{ov}</div></div>') if form else ""
    tile_html = "".join(
        f'<div class=tile><div class=cap>{_esc(cap)}</div>'
        f'<div class=big>{_esc(big)}</div><div class=sub>{_esc(sub)}</div></div>'
        for cap, big, sub in tiles)
    records_card = (f'<div class=card><p class=label>Personal records</p>'
                    f'<div class=tiles>{tile_html}</div></div>') if tiles else ""
    return render_shell("Driver", form_html + stats + records_card, "home")


# ── page: session list (flat) ───────────────────────────────────────────────

def _session_row(rec, record_time=None, compact=False) -> str:
    """One session row. `record_time`, when given, is the fastest lap across the
    group being listed — only the session(s) matching it show the magenta record
    colour; the rest show purple, so the fastest session stands out (companion
    parity in the drill-down).

    `compact=True` (the Game→Class→Track→Session-type leaf) drops the track name
    and game/car meta — the breadcrumb + section title already say what they are —
    leaving date + grade, then best time + laps."""
    from sessionlog import circuits
    from sessionlog.parser import format_lap_time
    track = circuits.display_name(rec.get("game"), rec.get("track"))
    name = track or rec.get("car") or rec.get("game_name") or rec["filename"]
    g = _grade_of(rec)
    grade_html = ""
    if g and g.get("letter"):
        score = g.get("score")
        sc = f'<span class=score>{int(round(score))}</span> ' if score is not None else ""
        grade_html = f'{sc}<span class="grade {_grade_class(g["letter"])}">{_esc(g["letter"])}</span>'
    best = rec.get("best_lap_time")
    is_record = best and record_time is not None and abs(best - record_time) < 1e-6
    if record_time is None:
        best_cls = "best notrec"        # flat sessions list → purple (best-lap)
    elif is_record:
        best_cls = "best"               # grouped fastest → magenta (session-best)
    else:
        best_cls = "best plain"         # grouped non-fastest → ink
    best_html = f'<span class="{best_cls}">{_esc(format_lap_time(best))}</span>' if best else ""
    laps = rec.get("lap_count") or 0
    valid = rec.get("valid_lap_count")
    ok = ' <span class=ok>✓</span>' if valid else ""
    href = f'/app/session/{_esc(rec["filename"])}'

    if compact:
        return (
            f'<a class=srow href="{href}">'
            f'<div class=r1>{_esc(_fmt_date(rec.get("date")))}'
            f'<span class=spacer></span>{grade_html}</div>'
            f'<div class=r2>{best_html}<span class=spacer></span>'
            f'<span class=r3>{laps} lap{"s" if laps != 1 else ""}{ok}</span></div></a>')

    car = rec.get("car") or rec.get("car_class_name") or ""
    return (
        f'<a class=srow href="{href}">'
        f'<div class=r1>{_esc(_fmt_day(rec.get("date")))} '
        f'{_badge(rec.get("session_type"), rec.get("session_subtype"))}'
        f'<span class=spacer></span>{grade_html}</div>'
        f'<div class=r2><span class=name>{_esc(name)}</span>{best_html}</div>'
        f'<div class=r3>{_esc(rec.get("game_name") or "")}'
        f'{"  ·  " + _esc(car) if car else ""}<span class=spacer></span>'
        f'{laps} lap{"s" if laps != 1 else ""}{ok}</div></a>')


def render_sessions(logs_dir: str, game_filter: str = None) -> str:
    rows = _load_rows(logs_dir)
    games, seen = [], set()
    for r in rows:
        gid = r.get("game")
        if gid and gid not in seen:
            seen.add(gid)
            games.append((gid, r.get("game_name") or gid))
    if game_filter and game_filter not in seen:
        game_filter = None

    chips = ""
    if len(games) > 1:
        def _chip(gid, label):
            on = " on" if game_filter == gid else ""
            href = "/app/sessions" if gid is None else f"/app/sessions?game={gid}"
            return f'<a class="chip{on}" href="{href}">{_esc(label)}</a>'
        chips = ('<div class=chips>' + _chip(None, "ALL")
                 + "".join(_chip(g, _GAME_ABBR.get(g, name.upper()))
                           for g, name in games) + "</div>")

    shown = [r for r in rows if game_filter is None or r.get("game") == game_filter]
    if not shown:
        rows_html = '<p class=empty>No sessions yet — drive one to see it here.</p>'
    else:
        rows_html = '<div class=flush>' + "".join(_session_row(r) for r in shown) + '</div>'
    body = _subtab_bar("sessions") + chips + rows_html
    return render_shell("Sessions", body, "sessions")


def _subtab_bar(active: str) -> str:
    tabs = [("/app/sessions", "sessions", "Sessions"),
            ("/app/browse", "games", "Games"),
            ("/app/favourites", "favourites", "Favourites")]
    return ('<div class=subtabs>' + "".join(
        f'<a class="{"on" if k == active else ""}" href="{h}">{l}</a>'
        for h, k, l in tabs) + '</div>')


def render_favourites(logs_dir: str) -> str:
    from sessionlog import records
    try:
        records.set_cache_dir(logs_dir)
        records.sync()
        favs = records.favourites()
    except Exception:
        favs = []
    rows_html = ('<div class=flush>' + "".join(_session_row(r) for r in favs) + '</div>'
                 if favs else
                 '<p class=empty>No favourites yet — open a session and tap the '
                 'star to pin it here.</p>')
    return render_shell("Favourites", _subtab_bar("favourites") + rows_html,
                        "sessions")


# ── page: trophies (career badge gallery) ───────────────────────────────────

_TIER_COLOUR = {3: "#ffd24a", 2: "#cfd6e0", 1: "#d08a4a"}
_CAT_ORDER = ["milestones", "pace", "consistency", "craft", "racecraft", "other"]


def render_trophies(logs_dir: str) -> str:
    from sessionlog import achievements
    rows = _load_rows(logs_dir)
    try:
        earned = achievements.evaluate(rows)
    except Exception:
        earned = {}
    cats = {}
    for bid, st in earned.items():
        d = achievements.badge(bid)
        if not d:
            continue
        cats.setdefault(d.get("category", "other"), []).append((d, st))
    if not earned:
        body = ('<h1 class=page>Trophies</h1>'
                '<p class=empty>No trophies yet — keep driving and they’ll appear.</p>')
        return render_shell("Trophies", body, "home")

    order = [c for c in _CAT_ORDER if c in cats] + \
            [c for c in cats if c not in _CAT_ORDER]
    body = [f'<h1 class=page>Trophies · {sum(1 for _ in earned)}</h1>']
    for cat in order:
        body.append(f'<p class=label style="margin:14px 0 8px">{_esc(cat.title())}</p>'
                    '<div class=badges>')
        for d, st in sorted(cats[cat], key=lambda x: -x[1].get("count", 0)):
            tier = st.get("tier")
            ring = _TIER_COLOUR.get(tier, "#ffb300")
            cnt = st.get("count", 0)
            cnt_html = f'<span class=bcount>×{cnt}</span>' if cnt > 1 else ""
            body.append(
                f'<a class=badge2 href="/app/trophy/{_esc(d.get("id",""))}">'
                f'<div class=bmedal style="border-color:{ring}">'
                f'{_esc(d.get("icon", "🏅"))}</div>'
                f'<div class=bname>{_esc(d.get("name", d.get("id","")))}</div>{cnt_html}</a>')
        body.append('</div>')
    return render_shell("Trophies", "".join(body), "home")


def render_trophy(logs_dir: str, badge_id: str) -> str:
    """Detail card for one badge: what it is, how to earn it (with tier goals
    for repeatable badges), current standing, and every session that counts
    toward it (newest first, each tappable). Mirrors the Pi trophy detail."""
    from sessionlog import achievements
    try:
        d = achievements.badge(badge_id)
    except KeyError:
        d = None
    if not d:
        return render_shell("Trophy",
                            '<p class=empty>Unknown trophy.</p>', "home")
    rows = _load_rows(logs_dir)
    by_fn = {r.get("filename"): r for r in rows}
    try:
        earned = achievements.evaluate(rows)
    except Exception:
        earned = {}
    state = earned.get(badge_id)
    count = state.get("count", 0) if state else 0
    tier = state.get("tier") if state else None
    ring = _TIER_COLOUR.get(tier if isinstance(tier, int) else
                            {"gold": 3, "silver": 2, "bronze": 1}.get(tier),
                            "#ffb300" if state else "var(--text4)")

    status = (f'Earned ×{count}' if count > 1 else "Earned") if state \
        else "Not yet earned — still on the board"
    tier_word = (tier.title() if isinstance(tier, str) else "") if state else ""
    medal = (
        f'<div class=tmedal><div class=bmedal style="border-color:{ring};'
        f'width:74px;height:74px;font-size:34px">{_esc(d.get("icon","🏅"))}</div>'
        f'<div class=tinfo><div class=tname>{_esc(d.get("name", badge_id))}</div>'
        f'<div class=tstatus>{_esc(status)}'
        + (f' · {_esc(tier_word)}' if tier_word else "") + '</div></div></div>')

    goals = achievements.tier_goals(d)
    how = f'<p class=notes-p>{_esc(d.get("desc",""))}</p>'
    if goals:
        how += f'<p class=notes-p style="color:var(--text3)">{_esc(goals)}</p>'
    how_block = (f'<div class=sec><p class=label>How to earn</p>{how}</div>')

    sess_block = ""
    sessions = (state or {}).get("sessions") or []
    if sessions:
        srows = []
        for fn, _dt in sessions:
            rec = by_fn.get(fn)
            if rec is not None:
                srows.append(_session_row(rec))
        if srows:
            sess_block = (f'<div class=sec><p class=label>Sessions · '
                          f'{len(srows)}</p><div class=flush>{"".join(srows)}</div></div>')

    back = ('<a class=viewback href="/app/trophies">‹ Trophies</a>')
    body = back + f'<div class="sec first">{medal}</div>' + how_block + sess_block
    return render_shell(d.get("name", "Trophy"), body, "home")


# ── page: journal (story diary — sessionlog.journal) ────────────────────────

def render_journal(logs_dir: str, month: str = None) -> str:
    """The racing diary, paged by month — ‹ month › navigation like the
    companion's journal_screen. `month` is "YYYY-MM" (defaults to the newest);
    only the chosen month's sessions are composed."""
    import datetime
    from sessionlog import journal, records, circuits
    from sessionlog.achievements import session_awards
    from sessionlog.parser import parse

    rows = [r for r in _load_rows(logs_dir) if r.get("date")]
    # Group index rows by (year, month), newest first — cheap, no file reads.
    by_month = {}
    for r in rows:
        by_month.setdefault((r["date"].year, r["date"].month), []).append(r)
    months = sorted(by_month, reverse=True)          # newest first
    if not months:
        return render_shell("Journal", '<h1 class=page>Journal</h1>'
                            '<p class=empty>No journal entries yet — drive a '
                            'session to start your diary.</p>', "home")

    # Resolve the selected month (param or newest), and its index for paging.
    sel = None
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            if (y, m) in by_month:
                sel = (y, m)
        except (ValueError, TypeError):
            sel = None
    if sel is None:
        sel = months[0]
    idx = months.index(sel)

    def _mkey(ym):
        return f"{ym[0]:04d}-{ym[1]:02d}"
    # months is newest-first (index 0 = newest). Match the companion: LEFT ‹
    # steps OLDER (larger index), RIGHT › steps NEWER (smaller index). Arrows
    # hug the edges with big tap targets (the whole corner is the link).
    older = (f'<a class=mnav href="/app/journal?m={_mkey(months[idx+1])}">&#8249;</a>'
             if idx + 1 < len(months) else '<span class="mnav off">&#8249;</span>')
    newer = (f'<a class=mnav href="/app/journal?m={_mkey(months[idx-1])}">&#8250;</a>'
             if idx > 0 else '<span class="mnav off">&#8250;</span>')
    label = datetime.date(sel[0], sel[1], 1).strftime("%B %Y").upper()
    monthbar = (f'<div class=monthbar>{older}'
                f'<span class=ml>{_esc(label)}</span>{newer}</div>')

    from sessionlog.parser import session_label
    all_sessions = records.all_sessions()
    parts = []
    last_day = None
    for r in by_month[sel]:
        path = os.path.join(logs_dir, r["filename"])
        try:
            with open(path, encoding="utf-8") as f:
                session = parse(f.read(), r["filename"])
            hist = records.combo_history(r.get("game"), r.get("car_class"),
                                         r.get("track"), r.get("session_type"))
            awards = session_awards(all_sessions, r["filename"])
            entry = journal.journal_entry(session, history=hist, awards=awards)
        except Exception:
            continue
        if not isinstance(entry, dict) or not entry.get("text"):
            continue
        # Day header when the calendar day changes (MONDAY 20 JULY).
        day = r["date"].strftime("%A %d %B").upper()
        if day != last_day:
            last_day = day
            parts.append(f'<div class=jday>{_esc(day)}</div>')
        # Meta: TIME · TRACK · TYPE · GAME (uppercase), matching the companion.
        stype = (session_label(session) or r.get("session_type") or "").replace("_", " ")
        meta = "  ·  ".join(b for b in (
            r["date"].strftime("%H:%M"), r.get("track") or "", stype,
            r.get("game_name") or r.get("game") or "") if b).upper()
        icon = (entry.get("icon") or "").strip()
        body_txt = (f"{icon} {entry['text']}" if icon else entry["text"]).strip()
        parts.append(
            f'<a class=jentry href="/app/session/{_esc(r["filename"])}">'
            f'<div class=jmeta>{_esc(meta)}</div>'
            f'<p class=jbody>{_esc(body_txt)}</p>'
            f'<span class=jchev>&#8250;</span></a>')
    body = ('<h1 class=page>Journal</h1>' + monthbar + (
        "".join(parts) if parts else
        '<p class=empty>No diary entries for this month.</p>'))
    return render_shell("Journal", body, "home")


# ── page: drill-down browse (Game > Class > Track > Session type) ────────────

_LEVELS = [("g", lambda r: r.get("game_name") or r.get("game") or "?"),
           ("c", lambda r: r.get("car_class_name") or r.get("car_class") or "?"),
           ("t", lambda r: r.get("track") or "?"),
           ("s", lambda r: r.get("session_type") or "?")]


def _level_label(depth: int, key: str, game_id=None) -> str:
    if depth == 2:                       # track — real circuit name, not the
        from sessionlog import circuits  # F1 short name (Melbourne → Albert Park)
        return (circuits.display_name(game_id, key) or key).upper()
    if depth == 3:                       # session type
        return _BADGE_TEXT.get(key.lower(), key.upper())
    return key


def _stars_html(n) -> str:
    """1–5 rating → filled/empty star run, matching grading.stars_text."""
    if not n:
        return ""
    n = int(n)
    return ('<span class=stars>'
            + '<span class=on>' + "★" * n + '</span>'
            + '<span class=off>' + "☆" * (5 - n) + '</span></span>')


def _pace_grade_letter(rows):
    """Average pace rating across a combo's sessions → a grade letter, mirroring
    the prototype's paceToGrade (A>=90, B>=80, C>=65, else D). '' if unknown."""
    scores = []
    for r in rows or []:
        g = _grade_of(r)
        s = g.get("score") if g else None
        if s is not None:
            scores.append(s)
    if not scores:
        return ""
    avg = sum(scores) / len(scores)
    return "A" if avg >= 90 else "B" if avg >= 80 else "C" if avg >= 65 else "D"


def _profile_panel(rows, caption="DRIVER PROFILE") -> str:
    """The DRIVER PROFILE repeatability panel shown above a combo's session
    list — the browser mirror of the companion's stats.ProfileHeader. Reads
    grading.driver_profile() over the combo history so the numbers match the
    Pi PROFILE screen and the companion exactly. Rows appear only as the
    history supports them (same gates as ProfileHeader)."""
    from sessionlog import grading
    from sessionlog import records as db
    from sessionlog.parser import format_lap_time
    if not rows:
        return ""
    r0 = rows[0]
    try:
        hist = db.combo_history(r0.get("game"), r0.get("car_class"),
                                r0.get("track"), r0.get("session_type"))
        prof = grading.driver_profile(hist or rows)
    except Exception:
        log.exception("web: driver_profile failed")
        prof = None
    if not prof:
        return ""

    out = [f'<div class="sec first profile"><div class=ptitle>{_esc(caption)}</div>']

    def _row(k, v, cls=""):
        out.append(f'<div class=prow><span class=pk>{_esc(k)}</span>'
                   f'<span class="pv {cls}">{v}</span></div>')

    _row("Personal best", _esc(format_lap_time(prof["pb"])), "pur")
    if prof.get("sessions", 0) >= 2 and prof.get("avg_best") is not None:
        gl = _pace_grade_letter(hist or rows)
        gh = (f'<span class="grade {_grade_class(gl)}" style="margin-right:8px">'
              f'{_esc(gl)}</span>' if gl else "")
        _row("Average best session", gh + _esc(format_lap_time(prof["avg_best"])))
    _row("Sessions", str(prof.get("sessions", len(rows))))
    if prof.get("stars"):
        _row("Consistency", _stars_html(prof["stars"]))
    if prof.get("typical"):
        lo, hi = prof["typical"]
        _row("Typical clean pace",
             f"{_esc(format_lap_time(lo))} – {_esc(format_lap_time(hi))}")
    baseline = prof.get("baseline")
    if baseline:
        if baseline["direction"] == "stable":
            val, cls = "→ stable", ""
        else:
            faster = baseline["shift"] < 0
            val = (f'{baseline["arrow"]} {abs(baseline["shift"]):.2f}s '
                   f'{"faster" if faster else "slower"}')
            cls = "grn" if baseline["direction"] == "improving" else ""
        _row("Typical pace trend", _esc(val), cls)
    if prof.get("on_pace_pct") is not None:
        _row("Fast-lap repeatability", f'{prof["on_pace_pct"]:.0f}%', "grn")
    conf = prof.get("confidence")
    if conf:
        _row("Profile confidence", _stars_html(conf.get("stars")))
    out.append('</div>')
    return "".join(out)


def render_browse(logs_dir: str, sel: dict) -> str:
    """Records-style drill-down. `sel` = {g,c,t,s} chosen so far (any missing).
    Mirrors the companion's stats.py GAMES drill: group by the next level,
    showing each group's best lap + session count; the deepest level lists the
    matching sessions."""
    from sessionlog import circuits
    from sessionlog.parser import format_lap_time
    rows = _load_rows(logs_dir)

    # Filter to the chosen path.
    depth = 0
    chosen = []
    for key, keyfn in _LEVELS:
        val = sel.get(key)
        if val is None:
            break
        rows = [r for r in rows if keyfn(r) == val]
        chosen.append((key, val))
        depth += 1

    # The game id of the current filtered set (all rows share it once a game is
    # chosen) — needed to resolve the real track name in the breadcrumb.
    game_id = rows[0].get("game") if rows else None

    # Breadcrumb — rebuilt from the chosen prefixes.
    crumbs = ['<a href="/app/browse">All</a>']
    for i in range(len(chosen)):
        prefix = dict(chosen[:i + 1])
        label = _level_label(i, chosen[i][1], game_id)
        crumbs.append(f'<a href="/app/browse?{_qs(prefix)}">{_esc(label)}</a>')
    crumb_html = f'<div class=crumbs>{" › ".join(crumbs)}</div>'

    bar = _subtab_bar("games")
    if depth >= len(_LEVELS):
        # Deepest level → the combo summary + the sessions themselves. The rows
        # drop the track name (the title below already says it), so lead with a
        # prominent track title + car·type subtitle.
        from sessionlog import circuits
        from sessionlog.parser import format_lap_time
        times = [r.get("best_lap_time") for r in rows if r.get("best_lap_time")]
        record = min(times) if times else None
        title = ""
        if rows:
            r0 = rows[0]
            trk = (circuits.display_name(r0.get("game"), r0.get("track"))
                   or r0.get("track") or "")
            sub = "  ·  ".join(p for p in (
                r0.get("car_class_name") or r0.get("car_class") or "",
                _BADGE_TEXT.get((r0.get("session_type") or "").lower(),
                                (r0.get("session_type") or "").upper()),
            ) if p)
            title = (f'<div class="sec first"><div class=combotitle>{_esc(trk)}</div>'
                     + (f'<div class=combosub>{_esc(sub)}</div>' if sub else "")
                     + '</div>')
        summary = ""
        if rows:
            panel = _profile_panel(rows)
            chart = _progress_chart_for(rows)
            chart_card = (f'<div class=sec><p class=label>Lap-time progress</p>'
                          f'<p class=sublabel>Best lap · shaded = clean-lap spread</p>'
                          f'{chart}</div>' if chart else "")
            summary = panel + chart_card
        rows_html = ('<div class=sec><div class=flush>'
                     + "".join(_session_row(r, record, compact=True) for r in rows)
                     + '</div></div>') if rows else '<p class=empty>No sessions here.</p>'
        return render_shell("Browse", f'{bar}{crumb_html}{title}{summary}{rows_html}',
                            "sessions")

    # Group by the next level.
    keyfn = _LEVELS[depth][1]
    groups = {}
    for r in rows:
        groups.setdefault(keyfn(r), []).append(r)

    def _best(recs):
        times = [x.get("best_lap_time") for x in recs if x.get("best_lap_time")]
        return min(times) if times else None

    items = []
    for key, recs in sorted(groups.items(),
                            key=lambda kv: (_best(kv[1]) is None, _best(kv[1]) or 0)):
        nxt = dict(chosen)
        nxt[_LEVELS[depth][0]] = key
        best = _best(recs)
        label = _level_label(depth, key, recs[0].get("game") if recs else None)
        meta = (f'{format_lap_time(best)} · ' if best else "") + \
               f'{len(recs)} session{"s" if len(recs) != 1 else ""}'
        items.append(
            f'<a class=drow href="/app/browse?{_qs(nxt)}">'
            f'<span class=d-name>{_esc(label)}</span>'
            f'<span class=d-meta>{_esc(meta)}</span><span class=chev>›</span></a>')
    titles = ["Games", "Car classes", "Tracks", "Session types"]
    crumb = crumb_html if depth else ""
    body = f'{bar}{crumb}<h1 class=page>{titles[depth]}</h1>{"".join(items)}'
    return render_shell("Browse", body, "sessions")


def _url(v) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")


def _qs(d: dict) -> str:
    return "&".join(f"{k}={_url(v)}" for k, v in d.items())


# ── page: session detail ────────────────────────────────────────────────────

def render_session(logs_dir: str, filename: str) -> str:
    from core.session_summary import build_summary
    from sessionlog import circuits
    from sessionlog.parser import format_lap_time, parse

    path = os.path.join(logs_dir, filename)
    if not os.path.isfile(path):
        return render_shell("Not found", '<p class=empty>That session no longer exists.</p>')
    try:
        summary = build_summary(path)
        with open(path, encoding="utf-8") as f:
            session = parse(f.read(), filename)
    except Exception:
        log.exception("web: cannot open %s", path)
        summary = None
    if not summary:
        return render_shell("Session",
                            '<p class=empty>No completed laps to show for this session.</p>')

    fmt = summary["fmt"]
    stype = (session.get("session_type") or "").strip().lower()
    is_race = stype in _RACE_TYPES

    head = _detail_header(summary, session, fmt, is_race, logs_dir)
    body = head
    body += _lap_table(session, is_race)
    body += _chart_card(session, summary, is_race, logs_dir)
    body += _minimap_card(session, summary, filename)
    body += _standings_table(session, format_lap_time)
    body += _notes_block(summary)
    body += _share_block(summary, session, fmt)
    return render_shell(summary["track"] or "Session", body, "sessions")


def _share_text(summary, session, fmt) -> str:
    """The coaching-ready AI brief — the canonical `sessionlog.share.format_for_ai`
    (shared verbatim with the companion). The web app supplies the app-specific
    context: the declared driver profile, the track map, and the journal entry;
    plus it enriches the session with the grade/prior-best `build_summary` has
    computed so those sections render too."""
    from sessionlog import share
    # Enrich the parsed session with what build_summary already computed, so the
    # SESSION GRADE section renders (other enriched sections degrade gracefully).
    if summary.get("grade") and not session.get("grade"):
        session["grade"] = summary["grade"]
    if summary.get("prior_best") is not None and session.get("prior_best") is None:
        session["prior_best"] = summary["prior_best"]
    profile = _share_profile()
    track_map = summary.get("track_map")
    journal_entry = _share_journal(session)
    try:
        return share.format_for_ai(session, profile=profile,
                                   track_map=track_map,
                                   journal_entry=journal_entry)
    except Exception:
        log.exception("web: format_for_ai failed")
        return "Shfonic Dash session brief unavailable."


def _share_profile():
    """{'name', 'experience_label'} from the declared driver profile, or None."""
    try:
        from core import config_store
        p = config_store.profile(config_store.load())
    except Exception:
        return None
    name = (p.get("name") or "").strip()
    exp = p.get("experience") or ""
    from sessionlog import profile as _profile_opts
    label = _profile_opts.experience_label(exp)
    if not (name or label):
        return None
    return {"name": name, "experience_label": label}


def _share_journal(session):
    """The session's journal entry {'icon','text'} for the brief, or None."""
    try:
        from sessionlog import journal, records
        from sessionlog.achievements import session_awards
        hist = records.combo_history(session.get("game"), session.get("car_class"),
                                     session.get("track"), session.get("session_type"))
        try:
            awards = session_awards(records.all_sessions(),
                                    session.get("filename") or "")
        except Exception:
            awards = None
        entry = journal.journal_entry(session, history=hist, awards=awards)
        return entry if isinstance(entry, dict) else None
    except Exception:
        return None


def _share_block(summary, session, fmt) -> str:
    """A link to the dedicated share screen. The clipboard/share Web APIs only
    work in a secure context (HTTPS/localhost); the Pi serves plain HTTP over the
    LAN, so an inline copy button silently fails — the share screen uses a
    selectable textarea + execCommand fallback that works over http."""
    fn = summary.get("filename", "")
    return (
        '<div class=sec style="display:flex;align-items:center;justify-content:space-between;gap:12px">'
        '<div><p class=label style="margin:0 0 3px">Share</p>'
        '<span class=muted style="font-size:13px">Send these notes to an AI coach</span></div>'
        f'<a class=sharebtn href="/app/session/{_esc(fn)}/share">Share notes ›</a></div>')


def render_share(logs_dir: str, filename: str) -> str:
    """A dedicated share screen: the plain-text session brief in a selectable
    textarea with a Copy button (works over http via execCommand), so the driver
    can paste the notes into an AI coach or a message."""
    from core.session_summary import build_summary
    from sessionlog.parser import parse
    path = os.path.join(logs_dir, filename)
    if not os.path.isfile(path):
        return render_shell("Share", '<p class=empty>That session no longer exists.</p>')
    try:
        summary = build_summary(path)
        with open(path, encoding="utf-8") as f:
            session = parse(f.read(), filename)
    except Exception:
        summary = None
    if not summary:
        return render_shell("Share", '<p class=empty>Nothing to share for this session.</p>')
    text = _share_text(summary, session, summary["fmt"])
    lines = text.count("\n") + 1
    trk = summary.get("track") or ""
    back = (f'<a class=viewback href="/app/session/{_esc(filename)}">‹ Back to session</a>')
    body = (
        back
        + '<div class="sec first"><p class=label>Share notes</p>'
          f'<div class=combotitle>{_esc(trk)}</div>'
          '<p class=muted style="font-size:12px;margin:6px 0 14px">Copy this brief and '
          'paste it into an AI coach (ChatGPT, Claude…) or a message.</p>'
          '<button class=savebtn id=copybtn type=button>Copy to clipboard</button>'
          f'<details class=sharemore id=sharedet><summary>View full text · {lines} lines</summary>'
          f'<textarea id=sharetext class=sharearea readonly rows=18>{_esc(text)}</textarea>'
          '</details></div>'
        '<script>(function(){var a=document.getElementById("sharetext"),'
        'd=document.getElementById("sharedet"),'
        'b=document.getElementById("copybtn");b.addEventListener("click",function(){'
        'if(d)d.open=true;'
        'a.focus();a.select();a.setSelectionRange(0,a.value.length);var ok=false;'
        'try{ok=document.execCommand("copy");}catch(e){}'
        'if(!ok&&navigator.clipboard){navigator.clipboard.writeText(a.value).then('
        'function(){},function(){});}'
        'b.textContent="Copied \\u2713";setTimeout(function(){'
        'b.textContent="Copy to clipboard";},1600);});})();</script>')
    return render_shell("Share", body, "sessions")


def _detail_header(summary, session, fmt, is_race, logs_dir) -> str:
    from sessionlog import circuits, records
    title = summary["track"] or summary["game_name"] or "Session"
    loc = circuits.location(session.get("game"), session.get("track"))
    car = summary["car"]
    g = summary["grade"]
    fn = summary.get("filename", "")
    try:
        fav = records.is_favourite(fn)
    except Exception:
        fav = False
    star = (f'<form method=post action="/app/session/{_esc(fn)}/favourite" '
            f'style="margin:0"><button type=submit aria-label="Favourite" '
            f'style="background:none;border:none;cursor:pointer;font-size:22px;'
            f'line-height:1;padding:0;color:{"#ffb300" if fav else "var(--text4)"}">'
            f'{"★" if fav else "☆"}</button></form>')

    facts = []
    if summary["fastest"]:
        facts.append(f'<span class=best>BEST {_esc(fmt(summary["fastest"]))}</span>')
    if summary["theo"]:
        gap = (f' +{summary["fastest"] - summary["theo"]:.3f}'
               if summary["fastest"] else "")
        facts.append(f'<span class=theo>THEO {_esc(fmt(summary["theo"]))}{_esc(gap)}</span>')
    facts_line = "   ·   ".join(facts)

    grade_bits = []
    if g and g.get("letter"):
        grade_bits.append(f'<span class="grade {_grade_class(g["letter"])}">GRADE {_esc(g["letter"])}</span>')
        if g.get("pace_rating") is not None:
            word = "RACE PACE" if g.get("pace_kind") == "race" else "PACE"
            grade_bits.append(f'{word} {int(g["pace_rating"])}/100')
    trend = _combo_trend(session, logs_dir)
    if trend:
        tw = {"improving": "↑", "declining": "↓", "stable": "→"}.get(trend["direction"], "→")
        grade_bits.append(f'TREND {tw}')
    grade_line = f'<div class=muted>{"   ·   ".join(grade_bits)}</div>' if grade_bits else ""

    pos_line = ""
    if is_race:
        start, finish = _race_positions(session)
        if start and finish:
            delta = start - finish
            arr = (f'<span class=up>▲ +{delta}</span>' if delta > 0
                   else f'<span class=down>▼ {delta}</span>' if delta < 0 else "held")
            pos_line = f'<div class=facts>P{start} → P{finish}   {arr}</div>'

    overall = ""
    if summary.get("overall_best") is not None:
        if summary.get("overall_holds"):
            overall = '<div class=facts><span class=best>OVERALL BEST — THIS SESSION</span></div>'
        else:
            ogap = (f' +{summary["fastest"] - summary["overall_best"]:.3f}'
                    if summary["fastest"] else "")
            overall = (f'<div class=facts><span class=overall>OVERALL '
                       f'{_esc(fmt(summary["overall_best"]))}{_esc(ogap)}</span></div>')

    return (
        f'<div class="sec first dhead">'
        f'<div class=top><div class=track-title style="font-size:24px">{_esc(title)}</div>'
        f'<div style="display:flex;align-items:center;gap:12px">'
        f'{_badge(session.get("session_type"), session.get("session_subtype"))}{star}</div></div>'
        + (f'<div class=loc>{_esc(loc)}</div>' if loc else "")
        + f'<div class=loc>{_esc(summary["game_name"])}'
          f'{"  ·  " + _esc(car) if car else ""}'
          f'{"  ·  " + _esc(session.get("driver_name")) if session.get("driver_name") else ""}</div>'
        + (f'<div class=facts>{facts_line}</div>' if facts_line else "")
        + grade_line + pos_line + overall + '</div>')


def _lap_table(session, is_race) -> str:
    from sessionlog.parser import format_lap_time, format_sector_time
    laps = session.get("laps") or []
    if not laps:
        return ""
    has_s = any(lap.get("s1") is not None for lap in laps)
    has_pos = is_race and any(lap.get("position") is not None for lap in laps)

    head = "<th>Lap</th><th>Time</th>"
    if has_s:
        head += "<th>S1</th><th>S2</th><th>S3</th>"
    if has_pos:
        head += "<th>Pos</th>"

    def _cell(val, flag):
        return f'<td class="{_flag_class(flag)}">{_esc(val)}</td>'

    rows = []
    for lap in laps:
        invalid = not lap.get("valid", True)
        t_flag = "red" if invalid else lap.get("lap_flag")
        delta = lap.get("delta")
        dhtml = ""
        if delta is not None and delta != 0:
            dcls = "pos" if delta > 0 else "neg"
            dhtml = f'<span class="delta {dcls}">{"+" if delta > 0 else ""}{delta:.3f}</span>'
        rw = ' ↺' if lap.get("rewinds") else ''
        r = f'<td class=lapn>{lap["num"]}</td>'
        r += (f'<td class="{_flag_class(t_flag)}">{_esc(format_lap_time(lap["time"]))}'
              f'{rw}{dhtml}</td>')
        if has_s:
            for key in ("s1", "s2", "s3"):
                v = lap.get(key)
                txt = format_sector_time(v) if v is not None else "—"
                if invalid:
                    r += f'<td class=muted>{_esc(txt)}</td>'
                else:
                    r += _cell(txt, lap.get(f"{key}_flag"))
        if has_pos:
            pos = lap.get("position")
            r += f'<td>{("P" + str(pos)) if pos else "—"}</td>'
        rows.append(f'<tr class="{"inv" if invalid else ""}">{r}</tr>')
    return (f'<div class=sec><div class=tablewrap>'
            f'<table class=laps><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></div>')


_TYRE_FILL = {"soft": "#e62e2e", "medium": "#ffd12e", "hard": "#e6e6e6",
              "inter": "#43b02a", "wet": "#007ac2"}


def _tyre_chip(compound) -> str:
    if not compound:
        return ""
    c = compound.strip().lower()
    fill = _TYRE_FILL.get(c, "#787c87")
    label = {"soft": "S", "medium": "M", "hard": "H", "inter": "I",
             "wet": "W"}.get(c, c[:1].upper())
    return f'<span class=tyre style="background:{fill}">{_esc(label)}</span>'


def _standings_table(session, fmt_lap) -> str:
    standings = session.get("standings") or []
    if not standings:
        return ""
    me = (session.get("driver_name") or "").strip().upper()

    def _f(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    leader = next((_f(p.get("race_time")) for p in standings
                   if str(p.get("position", "")) == "1"), None)
    rows = []
    for p in standings:
        nm = (p.get("name") or "").strip()
        cls = " class=me" if me and nm.upper() == me else ""
        best = _f(p.get("best_lap"))
        rt = _f(p.get("race_time"))
        if rt is None:
            rt_s = ""
        elif str(p.get("position", "")) == "1" or leader is None:
            rt_s = fmt_lap(rt)
        else:
            rt_s = f"+{rt - leader:.3f}"
        rows.append(
            f'<tr{cls}><td>P{_esc(p.get("position", ""))}</td>'
            f'<td style="text-align:left">{_esc(nm)}</td>'
            f'<td>{_esc(fmt_lap(best) if best else "")}</td>'
            f'<td class=muted>{_esc(rt_s)}</td></tr>')
    return (f'<div class=sec><p class=label>Standings</p><div class=tablewrap>'
            f'<table class=laps><tbody>{"".join(rows)}</tbody></table></div></div>')


_KIND_HEX = {"info": "#2fe07a", "track_limit": "#ffb300", "contact": "#ff8a2b",
             "major": "#ff3b30", "off_line": "#ffb300"}


def _notes_block(summary) -> str:
    """Race Engineer Notes — plain paragraphs (no `//`, no dividers), each
    located note followed by a row of corner mini-map thumbnails, exactly like
    the Pi history browser and the companion. Uses `notes_detailed`
    (`{text, locations:[{label, distance, kind, rewound}]}`) + the session's
    `track_map`, drawing each crop via `trackmap.crop_geometry` in SVG."""
    detailed = summary.get("notes_detailed")
    if not detailed:
        detailed = [{"text": t, "locations": []} for t in (summary.get("notes") or [])]
    if not detailed:
        return ""
    track_map = summary.get("track_map")
    items = []
    for note in detailed:
        text = note.get("text") if isinstance(note, dict) else str(note)
        if not text:
            continue
        thumbs = _note_thumbs(note.get("locations") or [], track_map)
        items.append(f'<div class=note><p class=notep>{_esc(text)}</p>{thumbs}</div>')
    if not items:
        return ""
    return (f'<div class=sec><p class=label>Race engineer notes</p>{"".join(items)}</div>')


def _note_thumbs(locations, track_map) -> str:
    if not locations or not track_map:
        return ""
    from sessionlog import trackmap
    cells = []
    for loc in locations[:8]:
        geo = trackmap.crop_geometry(track_map, loc.get("distance"))
        if not geo:
            continue
        colour = _KIND_HEX.get(loc.get("kind"), "#ff3b30")
        svg = _corner_thumb_svg(geo, colour, bool(loc.get("rewound")))
        label = _esc(loc.get("label") or "")
        cells.append(f'<div class=thumb>{svg}'
                     + (f'<div class=tlabel>{label}</div>' if label else "")
                     + '</div>')
    return f'<div class=thumbs>{"".join(cells)}</div>' if cells else ""


def _corner_thumb_svg(geo, colour, rewound) -> str:
    """One corner crop as an SVG: the left/right edge slices + a play-head
    triangle at the event point pointing the way the car travels (blue rim when
    the incident was rewound). Mirrors core/track_thumb.draw_thumbnail."""
    import math
    EDGE = "#5b6576"
    minx, minz, maxx, maxz = geo["bounds"]
    w = max(1.0, maxx - minx)
    h = max(1.0, maxz - minz)
    pad = 0.12 * max(w, h)
    vb_w, vb_h = w + 2 * pad, h + 2 * pad
    scale = max(vb_w, vb_h)

    def sx(x): return (maxx - x) + pad          # x negated, matches track_thumb / the viewers
    def sy(z): return (maxz - z) + pad          # north up
    def poly(pts): return " ".join(f"{sx(p[0]):.1f},{sy(p[1]):.1f}" for p in pts)

    sw = scale * 0.022
    edges = ""
    for e in (geo["left"], geo["right"]):
        if len(e) >= 2:
            edges += (f'<polyline points="{poly(e)}" fill="none" stroke="{EDGE}" '
                      f'stroke-width="{sw:.2f}" stroke-linejoin="round" '
                      f'stroke-linecap="round"></polyline>')
    mx, my = sx(geo["marker"][0]), sy(geo["marker"][1])
    hx, hz = geo.get("heading") or [0.0, 0.0]
    dx, dy = -hx, -hz           # world → screen: x negated, z inverted (matches sx/sy)
    mag = math.hypot(dx, dy) or 1.0
    dx, dy = dx / mag, dy / mag
    px, py = -dy, dx
    tip, back, half = scale * 0.09, scale * 0.055, scale * 0.055
    tx, ty = mx + dx * tip, my + dy * tip
    b1x, b1y = mx - dx * back + px * half, my - dy * back + py * half
    b2x, b2y = mx - dx * back - px * half, my - dy * back - py * half
    rim = f' stroke="#57c7ff" stroke-width="{scale*0.015:.2f}"' if rewound else ""
    marker = (f'<polygon points="{tx:.1f},{ty:.1f} {b1x:.1f},{b1y:.1f} '
              f'{b2x:.1f},{b2y:.1f}" fill="{colour}"{rim}></polygon>')
    # Explicit width/height so the thumbnail can never render full-bleed even if
    # the stylesheet is cached/absent (a viewBox-only SVG defaults to 100%).
    return (f'<svg class=cthumb width="104" height="70" '
            f'viewBox="0 0 {vb_w:.0f} {vb_h:.0f}" '
            f'preserveAspectRatio="xMidYMid meet">{edges}{marker}</svg>')


# ── charts (inline SVG) ─────────────────────────────────────────────────────

def _combo_trend(session, logs_dir):
    try:
        from sessionlog import grading
        from sessionlog import records as db
        hist = db.combo_history(session.get("game"), session.get("car_class"),
                                session.get("track"), session.get("session_type"))
        return grading.trend(hist)
    except Exception:
        return None


def _race_positions(session):
    """(grid, finish) from the standings for the player, or (None, None)."""
    me = (session.get("driver_name") or "").strip().lower()
    start = finish = None
    for p in session.get("grid") or []:
        if (p.get("name") or "").strip().lower() == me:
            try:
                start = int(p.get("position"))
            except (TypeError, ValueError):
                pass
    for p in session.get("standings") or []:
        if (p.get("name") or "").strip().lower() == me:
            try:
                finish = int(p.get("position"))
            except (TypeError, ValueError):
                pass
    # Fall back to the last lap's POS if no standings.
    if finish is None:
        laps = [l for l in (session.get("laps") or []) if l.get("position")]
        if laps:
            finish = laps[-1]["position"]
    return start, finish


def _chart_card(session, summary, is_race, logs_dir) -> str:
    if is_race:
        svg = _position_chart(session)
        if svg:
            return f'<div class=sec><p class=label>Position by lap</p>{svg}</div>'
        return ""
    svg = _progress_chart(session, logs_dir)
    if svg:
        return (f'<div class=sec><p class=label>Lap-time progress</p>'
                f'<p class=sublabel>Best lap · shaded = clean-lap spread</p>{svg}</div>')
    return ""


def _position_chart(session) -> str:
    laps = [l for l in (session.get("laps") or []) if l.get("position")]
    # Bookend the per-lap positions with the grid start (before lap 1) and the
    # classified finish, so the chart tells the same P{start} → P{finish} story
    # as the header. Per-lap POS only records the position at each lap tickover,
    # so without the grid slot it never shows the opening-lap climb.
    start, finish = _race_positions(session)
    nums = [l["num"] for l in laps]
    x0 = (min(nums) if nums else 1)
    x1 = (max(nums) if nums else 1)
    nodes = []  # (x-axis coord, position)
    if start:
        x0 -= 1
        nodes.append((x0, start))
    nodes.extend((l["num"], l["position"]) for l in laps)
    if finish and (not laps or finish != laps[-1]["position"]):
        x1 += 1
        nodes.append((x1, finish))
    if len(nodes) < 2:
        return ""
    W, H, pad = 680, 170, 26
    poss = [p for _, p in nodes]
    pmin, pmax = min(poss), max(poss)
    if pmin == pmax:
        pmax = pmin + 1
    def x(n): return pad + (n - x0) / max(1, x1 - x0) * (W - 2 * pad)
    def y(p): return pad + (p - pmin) / (pmax - pmin) * (H - 2 * pad)
    # Step line.
    pts = [(x(n), y(p)) for n, p in nodes]
    d = f'M {pts[0][0]:.1f} {pts[0][1]:.1f}'
    for i in range(1, len(pts)):
        d += f' L {pts[i][0]:.1f} {pts[i-1][1]:.1f} L {pts[i][0]:.1f} {pts[i][1]:.1f}'
    dots = "".join(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.2" class="dot"></circle>'
                   for px, py in pts)
    lbl_start = f'<text x="{pts[0][0]:.0f}" y="{pts[0][1]-8:.0f}" class="big">P{poss[0]}</text>'
    lbl_end = f'<text x="{pts[-1][0]:.0f}" y="{pts[-1][1]-8:.0f}" class="big" text-anchor="end">P{poss[-1]}</text>'
    return (f'<svg class="chart" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">'
            f'<path d="{d}" class="ln"></path>{dots}{lbl_start}{lbl_end}</svg>')


def _progress_chart(session, logs_dir) -> str:
    try:
        from sessionlog import records as db
        hist = db.combo_history(session.get("game"), session.get("car_class"),
                                session.get("track"), session.get("session_type"))
    except Exception:
        hist = []
    return _progress_svg(hist, session.get("filename"))


def _progress_chart_for(rows) -> str:
    """Combo lap-time-progress chart from a group of records, pulling the full
    combo history (with clean_std_dev for the spread band) when possible so it
    matches the Pi/companion chart. `rows` are newest-first index records."""
    if not rows:
        return ""
    from sessionlog import records as db
    r0 = rows[0]
    try:
        hist = db.combo_history(r0.get("game"), r0.get("car_class"),
                                r0.get("track"), r0.get("session_type"))
    except Exception:
        hist = None
    return _progress_svg(hist or list(reversed(rows)))


def _progress_svg(hist, cur=None) -> str:
    """Best lap per session over time at one combo, with the clean-lap spread
    shaded (best → best+clean_std_dev) — the companion LAP-TIME PROGRESS. Faster
    sits higher, so an improving line climbs and the band drops and narrows.
    `cur` (a filename) gets a ring."""
    import math
    from sessionlog.parser import format_lap_time
    pts = []
    for r in sorted(hist, key=lambda r: (r.get("date") or "")):
        best = r.get("best_lap_time")
        if not best or not math.isfinite(best):
            continue
        std = r.get("clean_std_dev")
        if std is None or not math.isfinite(std):
            std = 0.0
        pts.append({"best": best, "hi": best + std,
                    "current": r.get("filename") == cur})
    if len(pts) < 2:
        return ""
    W, H, px, pt, pb = 680, 168, 30, 14, 24
    lo = min(p["best"] for p in pts)
    hi = max(p["hi"] for p in pts)
    if hi <= lo:
        hi = lo + 0.5
    n = len(pts)

    def x(i): return px + i / (n - 1) * (W - 2 * px)
    def y(t): return pt + (t - lo) / (hi - lo) * (H - pt - pb)   # faster(lo)=top

    top = " ".join(f"{x(i):.1f},{y(p['best']):.1f}" for i, p in enumerate(pts))
    bot = " ".join(f"{x(i):.1f},{y(p['hi']):.1f}"
                   for i, p in reversed(list(enumerate(pts))))
    band = (f'<polygon points="{top} {bot}" fill="#2fe07a" '
            f'fill-opacity="0.15"></polygon>')
    line = "".join((("M " if i == 0 else "L ") + f"{x(i):.1f} {y(p['best']):.1f} ")
                   for i, p in enumerate(pts))
    dots = "".join(
        (f'<circle cx="{x(i):.1f}" cy="{y(p["best"]):.1f}" r="5" fill="none" '
         f'stroke="#57c7ff" stroke-width="2.5"></circle>' if p["current"] else "")
        + f'<circle cx="{x(i):.1f}" cy="{y(p["best"]):.1f}" r="3.2" class="dot"></circle>'
        for i, p in enumerate(pts))
    return (f'<svg class="chart" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">'
            f'<text x="4" y="13">{_esc(format_lap_time(lo))}</text>'
            f'<text x="4" y="{H-6}">{_esc(format_lap_time(hi))}</text>'
            f'{band}<path d="{line}" class="ln"></path>{dots}</svg>')


# ── minimap (driven line vs racing line) ────────────────────────────────────

def _racing_geometry(tm, car_class):
    """Racing-line polyline + bounds from the track map (no driven line) — used
    when a session has a mapped track but no per-lap driven profile (races,
    practice), so its circuit + incident markers still render. Mirrors
    player_line_geometry's line resolution (the class's own line, else any)."""
    lines_map = (tm or {}).get("lines") or {}
    racing = None
    entry = lines_map.get(car_class)
    if entry and entry.get("racing_line"):
        racing = entry["racing_line"]
    else:
        for e in lines_map.values():
            if e.get("racing_line"):
                racing = e["racing_line"]
                break
    if not racing:
        return None
    from sessionlog import trackmap
    deg = trackmap.orientation_deg(tm)      # cosmetic display rotation, matches player_line_geometry
    racing = trackmap.rotate_xz([list(p) for p in racing], deg)
    xs = [p[0] for p in racing]
    zs = [p[1] for p in racing]
    return {"racing": racing, "player": None,
            "bounds": (min(xs), min(zs), max(xs), max(zs))}


def _minimap_card(session, summary, filename) -> str:
    """The circuit map: the driven line vs the racing line when a lap profile
    exists, else just the racing line with the session's incident markers. Shown
    for any session at a mapped track (same condition as the full viewer), and
    taps through to it."""
    from sessionlog import lines
    tm = summary.get("track_map")
    if not tm:
        return ""
    offs = lines.best_line_offsets(session)
    geo = lines.player_line_geometry(tm, offs) if offs else None
    if geo is None:
        geo = _racing_geometry(tm, session.get("car_class"))
    if geo is None:
        return ""
    events = lines.map_events(session, tm) or []
    length = tm.get("game_track_length_m") or 0
    svg = _minimap_svg(geo, events, length)
    has_driven = geo.get("player") is not None
    caption = "Your line vs the racing line" if has_driven else \
        "Circuit & incident markers"
    href = f"/app/session/{_esc(filename)}/lines"
    return (f'<a class="sec mapcard" href="{href}">'
            f'<p class=label>{caption}</p>{svg}'
            f'<div class=viewlink>Open the full session map ›</div></a>')


def _minimap_svg(geo, events, length) -> str:
    # Fixed brand colours (not theme vars) — CSS custom properties don't apply
    # reliably to SVG presentation attributes, and the map palette is fixed in
    # both themes anyway (amber driven line, dim racing line, red incidents),
    # matching the full session_viewer.
    RACING, DRIVEN, MARK = "#5b6576", "#ffb300", "#ff5b5b"
    racing = geo["racing"]
    player = geo["player"]
    minx, minz, maxx, maxz = geo["bounds"]
    w = max(1.0, maxx - minx)
    h = max(1.0, maxz - minz)
    pad = 0.07 * max(w, h)
    vb_w, vb_h = w + 2 * pad, h + 2 * pad
    scale = max(vb_w, vb_h)

    def sx(x): return (maxx - x) + pad          # x negated, matches the viewers
    def sy(z): return (maxz - z) + pad          # flip so north is up

    def poly(pts):
        return " ".join(f"{sx(p[0]):.1f},{sy(p[1]):.1f}" for p in pts)

    marks = ""
    n = len(racing)
    if length and n:
        for ev in events:
            dist = ev.get("distance")
            if dist is None:
                continue
            i = min(n - 1, max(0, int(dist / length * n)))
            cx, cy = sx(racing[i][0]), sy(racing[i][1])
            r = scale * 0.022
            marks += (f'<path d="M {cx-r:.1f} {cy-r:.1f} L {cx+r:.1f} {cy+r:.1f} '
                      f'M {cx+r:.1f} {cy-r:.1f} L {cx-r:.1f} {cy+r:.1f}" '
                      f'stroke="{MARK}" stroke-width="{scale*0.009:.2f}" '
                      f'stroke-linecap="round"></path>')
    sw = scale * 0.006
    # Racing line: dim when a driven line overlays it, brighter (amber) when
    # it's the only line (races/practice with no driven profile).
    racing_stroke = RACING if player else DRIVEN
    racing_w = sw if player else sw * 1.4
    driven = (f'<polyline points="{poly(player)}" fill="none" stroke="{DRIVEN}" '
              f'stroke-width="{sw*1.7:.2f}" stroke-linejoin="round" '
              f'stroke-linecap="round"></polyline>') if player else ""
    return (f'<svg class="chart" viewBox="0 0 {vb_w:.0f} {vb_h:.0f}" '
            f'preserveAspectRatio="xMidYMid meet" style="max-height:420px">'
            f'<polyline points="{poly(racing)}" fill="none" stroke="{racing_stroke}" '
            f'stroke-width="{racing_w:.2f}" stroke-linejoin="round" '
            f'opacity="{0.7 if player else 1}"></polyline>'
            f'{driven}{marks}</svg>')


# ── page: full session line viewer (vendored session_viewer.html) ───────────

def render_line_viewer(logs_dir: str, filename: str) -> str | None:
    """Serve the vendored session_viewer.html with the session's line export
    baked in via window.VIEWER_DATA. Returns None when the session has no
    racing-line data (the caller 404s / redirects)."""
    import json
    from sessionlog import lines, trackmap
    from sessionlog.parser import parse

    path = os.path.join(logs_dir, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            session = parse(f.read(), filename)
        trackmap.set_tracks_dir(os.path.join(logs_dir, "..", "tracks"))
        tm = trackmap.find_map(session.get("game"), session.get("track"))
        export = lines.session_line_export(session, tm) if tm else None
    except Exception:
        log.exception("web: line viewer failed for %s", path)
        return None
    if not export:
        return None
    try:
        with open(_VIEWER_HTML, encoding="utf-8") as f:
            viewer = f.read()
    except OSError:
        return None
    payload = json.dumps(export, separators=(",", ":"), default=str)
    inject = (f"<script>window.VIEWER_DATA={payload};</script>")
    # Inject before the viewer's own script runs (it checks window.VIEWER_DATA).
    if "</head>" in viewer:
        viewer = viewer.replace("</head>", inject + "</head>", 1)
    else:
        viewer = inject + viewer
    back = _viewer_back(f"/app/session/{filename}", "Session")
    return viewer.replace("</body>", back + "</body>", 1) \
        if "</body>" in viewer else viewer + back


def _viewer_back(href: str, label: str, extra: str = "") -> str:
    """A fixed top bar with a Back link (+ optional extra control) for the
    embedded viewers, which otherwise have no way back to the companion. The
    accompanying <style> reserves the bar's height at the top of the viewer's
    own body (and shifts any top-anchored fixed chrome down) so the bar never
    overlaps the map/content beneath it."""
    return (
        '<style>body{padding-top:46px!important}'
        '#sfbar{position:fixed;top:0;left:0;right:0;z-index:100000;height:46px;'
        'display:flex;align-items:center;gap:12px;padding:0 12px;box-sizing:border-box;'
        'background:rgba(12,13,16,.92);backdrop-filter:blur(6px);'
        'border-bottom:1px solid #232b38}</style>'
        f'<div id=sfbar>'
        f'<a href="{href}" style="color:#ffb300;font:700 15px system-ui;'
        f'text-decoration:none">&#8249; {_esc(label)}</a>'
        f'<span style="font:600 12px ui-monospace,monospace;letter-spacing:.16em;'
        f'color:#8b95a6">SHFONIC · DASH</span>'
        f'<span style="margin-left:auto">{extra}</span></div>')


# ── page: tracks list + track map editor (vendored track_viewer.html) ───────

_TRACK_FILE_RE = None


def _track_name_ok(fname: str) -> bool:
    global _TRACK_FILE_RE
    if _TRACK_FILE_RE is None:
        import re
        _TRACK_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*\.json$")
    return bool(_TRACK_FILE_RE.match(fname))


def render_tracks(tracks_dir: str) -> str:
    """List the recorded track maps, each tapping through to the map editor."""
    import json
    rows = []
    try:
        names = sorted(os.listdir(tracks_dir)) if tracks_dir else []
    except OSError:
        names = []
    for fname in names:
        if fname == "index.json" or not _track_name_ok(fname):
            continue
        try:
            with open(os.path.join(tracks_dir, fname), encoding="utf-8") as f:
                tm = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(tm, dict):
            continue
        classes = sorted((tm.get("lines") or {}).keys())
        secs = len(tm.get("sections") or [])
        name = tm.get("track") or fname
        meta = " · ".join(x for x in (
            _GAME_ABBR.get(tm.get("game"), tm.get("game", "")),
            f'{secs} section{"s" if secs != 1 else ""}' if secs else "",
            f'{len(classes)} class{"es" if len(classes) != 1 else ""}' if classes else "",
            "PIT" if tm.get("pit_lane") else "") if x)
        rows.append(
            f'<a class=trow href="/app/track/{_esc(fname)}/map">'
            f'<div class=tc><div class=tn>{_esc(name)}</div>'
            f'<div class=tmeta>{_esc(meta)}</div></div>'
            f'<span class=chev style="color:var(--amber);font-family:var(--mono);font-size:20px">&#8250;</span></a>')
    body = '<h1 class=page>Tracks</h1>'
    body += ("".join(rows) if rows else
             '<p class=empty>No track maps yet. Record one on the dashboard '
             '(SELECT GAME → RECORD).</p>')
    body += ('<div class=card><p class=label>About</p><p class=muted>Tap a track to '
             'open the map editor — label corners, group complexes and edit notes, '
             'then <b>Save to Pi</b> writes it straight back to the dashboard.</p></div>')
    return render_shell("Tracks", body, "tracks")


def render_track_viewer(tracks_dir: str, filename: str) -> str | None:
    """Serve the vendored track_viewer.html (the map editor) with the chosen
    track baked in, in embedded mode, plus a Save-to-Pi button that POSTs the
    edited map back through the cookie-authed write path."""
    if not (tracks_dir and _track_name_ok(filename)):
        return None
    path = os.path.join(tracks_dir, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            track_json = f.read()
        with open(_TRACK_HTML, encoding="utf-8") as f:
            viewer = f.read()
    except OSError:
        return None
    # Bake the track in + embed (hides the open/download chrome). The top bar
    # carries Back + a Save-to-Pi control that PUTs the edited export through the
    # cookie-authed /app/track/<file>/save path.
    save_btn = ('<button id=sfSave style="font:700 14px system-ui;background:#ffb300;'
                'color:#1a1300;border:none;border-radius:9px;padding:9px 16px;'
                'cursor:pointer">Save to Pi</button>')
    bar = _viewer_back("/app/tracks", "Tracks", save_btn)
    script = (
        "<script>(function(){"
        "function load(){try{SHFONIC.embed();SHFONIC.load(" + _js_str(track_json) + ");}catch(e){}}"
        "if(window.SHFONIC)load();else window.addEventListener('load',load);"
        "var b=document.getElementById('sfSave');"
        "b.addEventListener('click',function(){var body=SHFONIC.export();"
        "fetch('/app/track/" + filename + "/save',{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:body}).then(function(r){"
        "if(r.ok){SHFONIC.markSaved();b.textContent='Saved \\u2713';"
        "setTimeout(function(){b.textContent='Save to Pi';},1500);}"
        "else b.textContent='Save failed';}).catch(function(){b.textContent='Save failed';});"
        "});})();</script>")
    inject = bar + script
    if "</body>" in viewer:
        return viewer.replace("</body>", inject + "</body>", 1)
    return viewer + inject


def _js_str(s: str) -> str:
    """A safe single-quoted JS string literal from arbitrary text."""
    return "'" + (s.replace("\\", "\\\\").replace("'", "\\'")
                  .replace("\n", "\\n").replace("\r", "")
                  .replace("<", "\\x3c").replace(">", "\\x3e")) + "'"
