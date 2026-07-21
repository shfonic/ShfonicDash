"""
Shfonic Dash sessionlog — SQLite session index (shared library; canonical
home is ShfonicDash/src/sessionlog/, vendored into the companion
app by sync_shared.py — see the package docstring).

A disposable index over a directory of session CSVs, used so session lists,
Records screens and overall-best lookups don't have to re-scan every CSV
file. The CSVs remain the source of truth: the DB file can be deleted at
any time and is rebuilt from disk (Resync on the companion's connect
screen, or the automatic heal in sync()).

The indexed directory defaults to `downloaded/` next to the sessionlog
package (the companion's cache, unchanged from when this module was its
session_db.py); the Pi points it at its `logs/` directory via
set_cache_dir() before first use.

One row per CSV, shaped by parser.scan_session() — see its docstring for the
field contract. Dates are stored as ISO strings and returned as datetimes.
Records also carry a `favourite` flag (0/1); it is user metadata, not derived
from the CSV, so its durable home is `.favourites.json` and the DB column is
reconciled from that file on every sync. This is deliberate: the DB is
disposable (deleted/corrupted/schema-bumped → rebuilt from the CSVs), and the
CSVs hold no favourite info, so the json is what keeps favourites safe.
(Favourites are companion UI metadata; the Pi simply doesn't call them.)

Importable off-device (stdlib only), so it carries test coverage in
tests/test_session_db.py.
"""

import json
import os
import sqlite3
from datetime import datetime

from .parser import scan_session

_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR   = os.path.join(_PKG_PARENT, 'downloaded')
DB_PATH     = os.path.join(CACHE_DIR, '.sessions.db')


def set_cache_dir(path):
    """Point the index at a different CSV directory (+ its .sessions.db).

    The Pi calls this once at startup with its logs/ directory; the
    companion keeps the default. Call before any other function here —
    existing connections are not migrated.
    """
    global CACHE_DIR, DB_PATH
    CACHE_DIR = path
    DB_PATH   = os.path.join(path, '.sessions.db')

# Bump when the sessions table shape changes — or when scan_session's
# SEMANTICS change and cached rows must be recomputed (v11: rewind_count
# reconciled with rewind events; v12: start_position + perfect_lap for
# achievements; v13: racing-line adherence facts for the on_the_line badge;
# v14: assist usage counts for the "reduce assist reliance" goal mission;
# v15: distance_m per session for the Personal Records total-distance stat).
# A mismatch (or a corrupt DB file) drops and recreates the table; sync()
# then repopulates from the CSVs.
SCHEMA_VERSION = 15

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    filename        TEXT PRIMARY KEY,
    date            TEXT,
    track           TEXT,
    car             TEXT,
    car_name        TEXT,
    car_class       TEXT,
    car_class_name  TEXT,
    session_type    TEXT,
    session_subtype TEXT,
    driver_name     TEXT,
    game            TEXT,
    game_name       TEXT,
    best_lap_time   REAL,
    best_s1         REAL,
    best_s2         REAL,
    best_s3         REAL,
    race_time       REAL,
    position        INTEGER,
    start_position  INTEGER,
    perfect_lap     INTEGER,
    lap_count       INTEGER,
    distance_m      REAL,
    valid_lap_count INTEGER,
    clean_lap_count INTEGER,
    clean_std_dev   REAL,
    theo_time       REAL,
    rewind_count    INTEGER,
    collision_count INTEGER,
    penalty_count   INTEGER,
    clean_streak    INTEGER,
    cons_lap_count  INTEGER,
    cons_band_count INTEGER,
    push_lap_count  INTEGER,
    on_line_lap_count INTEGER,
    on_line_session INTEGER,
    best_line_dev   REAL,
    tc_used_lap_count INTEGER,
    abs_used_lap_count INTEGER,
    racing_line_used_lap_count INTEGER,
    gearbox_assist_used_lap_count INTEGER,
    file_size       INTEGER,
    file_mtime      REAL,
    favourite       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_combo
    ON sessions (game, car_class, track, session_type);
"""

# Columns written by upsert() from a scan_session() record. `favourite` is
# deliberately excluded: it is not part of the scan and defaults to 0 on
# insert, then reconciled from the favourites file by sync() / set_favourite().
_COLUMNS = ('filename', 'date', 'track', 'car', 'car_name', 'car_class',
            'car_class_name', 'session_type', 'session_subtype',
            'driver_name', 'game', 'game_name',
            'best_lap_time', 'best_s1', 'best_s2', 'best_s3',
            'race_time', 'position', 'start_position', 'perfect_lap',
            'lap_count', 'distance_m', 'valid_lap_count',
            'clean_lap_count', 'clean_std_dev', 'theo_time', 'rewind_count',
            'collision_count', 'penalty_count',
            'clean_streak', 'cons_lap_count', 'cons_band_count',
            'push_lap_count', 'on_line_lap_count', 'on_line_session',
            'best_line_dev',
            'tc_used_lap_count', 'abs_used_lap_count',
            'racing_line_used_lap_count', 'gearbox_assist_used_lap_count',
            'file_size', 'file_mtime')


# ---------------------------------------------------------------------------
# Favourites — durable user metadata kept in .favourites.json, mirrored into
# the `favourite` column so it can be queried/sorted alongside the index. The
# json is the source of truth (it survives the DB being rebuilt from the CSVs).
# ---------------------------------------------------------------------------

def _fav_path():
    # Derived at call time so tests that monkeypatch CACHE_DIR are honoured.
    return os.path.join(CACHE_DIR, '.favourites.json')


def _load_favourites():
    try:
        with open(_fav_path(), 'r', encoding='utf-8') as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def _save_favourites(favs):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_fav_path(), 'w', encoding='utf-8') as f:
        json.dump(sorted(favs), f)


def is_favourite(filename):
    """True if this session is marked a favourite (reads the durable store)."""
    return filename in _load_favourites()


def set_favourite(filename, on):
    """Mark/unmark a session, updating both the json store and the DB column."""
    favs = _load_favourites()
    if on:
        favs.add(filename)
    else:
        favs.discard(filename)
    _save_favourites(favs)
    conn = _connect()
    try:
        conn.execute('UPDATE sessions SET favourite = ? WHERE filename = ?',
                     (1 if on else 0, filename))
        conn.commit()
    finally:
        conn.close()


def favourites():
    """Every favourited session, newest filename first."""
    conn = _connect()
    try:
        rows = conn.execute(
            'SELECT * FROM sessions WHERE favourite = 1 '
            'ORDER BY filename DESC').fetchall()
        return [_to_record(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Connection / schema
# ---------------------------------------------------------------------------

def _connect():
    """Open a connection with the schema ensured.

    Callers get a fresh connection each time (sqlite connections must not
    cross threads, and picker/stats access the DB from background threads).
    A corrupt DB file is deleted and recreated; a schema-version mismatch
    drops the table so sync()/rebuild() can repopulate it.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.executescript(_CREATE_SQL)
    except sqlite3.DatabaseError:
        try:
            conn.close()
        except Exception:
            pass
        try:
            os.remove(DB_PATH)
        except OSError:
            pass
        conn = sqlite3.connect(DB_PATH)
        conn.executescript(_CREATE_SQL)

    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version != SCHEMA_VERSION:
        conn.executescript('DROP TABLE IF EXISTS sessions;' + _CREATE_SQL)
        conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


def _to_record(row):
    """sqlite3.Row → scan_session()-shaped dict (date back to datetime)."""
    rec = dict(row)
    raw = rec.get('date')
    rec['date'] = None
    if raw:
        try:
            rec['date'] = datetime.fromisoformat(raw)
        except ValueError:
            pass
    return rec


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def upsert(record, conn=None):
    """Insert or replace one scan_session() record."""
    values = dict(record)
    date = values.get('date')
    values['date'] = date.isoformat() if date is not None else None
    row = tuple(values.get(c) for c in _COLUMNS)
    own = conn is None
    if own:
        conn = _connect()
    try:
        conn.execute(
            f'INSERT OR REPLACE INTO sessions ({",".join(_COLUMNS)}) '
            f'VALUES ({",".join("?" * len(_COLUMNS))})', row)
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def _file_meta(path):
    """(size, mtime) for a CSV, or (None, None) when unreadable. Stored on
    the row so sync() can spot content changes (an iCloud CSV that was
    still materialising when first scanned) and heal by re-scanning."""
    try:
        st = os.stat(path)
        return st.st_size, st.st_mtime
    except OSError:
        return None, None


def add_file(filepath):
    """Scan one CSV and index it. Returns the record, or None if unreadable."""
    record = scan_session(filepath)
    if record:
        record['file_size'], record['file_mtime'] = _file_meta(filepath)
        upsert(record)
    return record


def remove(filename):
    """Drop the index row for a deleted/trashed CSV (and its favourite mark)."""
    favs = _load_favourites()
    if filename in favs:
        favs.discard(filename)
        _save_favourites(favs)
    conn = _connect()
    try:
        conn.execute('DELETE FROM sessions WHERE filename = ?', (filename,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sync — keep the index matching the CSVs on disk
# ---------------------------------------------------------------------------

def sync(force=False, progress=None):
    """
    Reconcile the index with downloaded/*.csv.

    force=False — cheap heal: scan+add CSVs missing from the index, drop rows
                  whose CSV is gone, and RE-scan rows whose file size/mtime
                  no longer match (a CSV scanned while still materialising —
                  iCloud download, mid-transfer — must not leave a bogus row
                  behind forever). Run on every picker/Records load.
    force=True  — full rebuild: empty the table first so every file is
                  re-scanned (fixes edited files, e.g. corrected OCR imports).
    progress    — optional callable(done, total) for rebuild UI feedback.

    Returns (added, removed, total_rows); re-scanned rows count as added.
    """
    try:
        files = {f for f in os.listdir(CACHE_DIR) if f.endswith('.csv')}
    except OSError:
        files = set()

    conn = _connect()
    try:
        if force:
            conn.execute('DELETE FROM sessions')
        meta = {r[0]: (r[1], r[2]) for r in conn.execute(
            'SELECT filename, file_size, file_mtime FROM sessions')}
        indexed = set(meta)

        stale = indexed - files
        for fn in stale:
            conn.execute('DELETE FROM sessions WHERE filename = ?', (fn,))

        # Content heal: a row whose file changed since it was scanned (or
        # that predates size/mtime tracking) is re-scanned in place. An
        # unreadable/mid-write file drops its row — the next sync re-adds
        # it once readable (favourites live in the json, so they survive).
        changed = []
        for fn in sorted(indexed & files):
            size, mtime = _file_meta(os.path.join(CACHE_DIR, fn))
            if (size, mtime) != meta[fn]:
                changed.append(fn)

        todo  = sorted(files - indexed) + changed
        added = 0
        for i, fn in enumerate(todo):
            path   = os.path.join(CACHE_DIR, fn)
            record = scan_session(path)
            if record:
                record['file_size'], record['file_mtime'] = _file_meta(path)
                upsert(record, conn=conn)
                added += 1
            elif fn in changed:
                conn.execute('DELETE FROM sessions WHERE filename = ?', (fn,))
            if progress:
                progress(i + 1, len(todo))

        # Mirror the durable json favourites into the column (a rebuild
        # re-inserts every row with favourite defaulted to 0, so re-apply). We
        # intentionally do NOT prune the json for files missing from this
        # listing: a temporarily-absent CSV (e.g. an iCloud-evicted file, or a
        # listdir that failed entirely) must not silently forget its favourite.
        # Removing a favourite happens explicitly in remove() when the user
        # deletes the session.
        stored = _load_favourites()
        conn.execute('UPDATE sessions SET favourite = 0')
        present = stored & files
        if present:
            conn.executemany(
                'UPDATE sessions SET favourite = 1 WHERE filename = ?',
                [(fn,) for fn in present])

        conn.commit()
        total = conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
        return added, len(stale), total
    finally:
        conn.close()


def rebuild(progress=None):
    """Full drop-and-reimport of the index. Returns (added, removed, total)."""
    return sync(force=True, progress=progress)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def all_sessions():
    """Every indexed session, newest filename first."""
    conn = _connect()
    try:
        rows = conn.execute(
            'SELECT * FROM sessions ORDER BY filename DESC').fetchall()
        return [_to_record(r) for r in rows]
    finally:
        conn.close()


def overall_best(game, car_class, track, session_type):
    """
    The all-time best session for this game/car class/track/session type —
    the record whose best clean lap is fastest. None when there is no match
    (or any key part is missing, e.g. flat-format files with no track).
    """
    if not (game and car_class and track and session_type):
        return None
    conn = _connect()
    try:
        row = conn.execute(
            'SELECT * FROM sessions '
            'WHERE game = ? AND car_class = ? AND track = ? '
            'AND session_type = ? AND best_lap_time IS NOT NULL '
            'ORDER BY best_lap_time ASC, filename ASC LIMIT 1',
            (game, car_class, track, session_type)).fetchone()
        return _to_record(row) if row else None
    finally:
        conn.close()


def prior_best(game, car_class, track, session_type, before_date,
               before_filename=''):
    """
    The best session at this game/car class/track/session type among
    sessions strictly EARLIER than (before_date, before_filename) — the
    personal best as it stood going into that session. Used by the
    Improvement grading category: unlike overall_best(), grading an old
    session (or re-grading after a rebuild) never compares it against
    results that hadn't happened yet. None when there is no history or
    any key part is missing.
    """
    if not (game and car_class and track and session_type and before_date):
        return None
    iso = before_date.isoformat()
    conn = _connect()
    try:
        row = conn.execute(
            'SELECT * FROM sessions '
            'WHERE game = ? AND car_class = ? AND track = ? '
            'AND session_type = ? AND best_lap_time IS NOT NULL '
            'AND date IS NOT NULL '
            'AND (date < ? OR (date = ? AND filename < ?)) '
            'ORDER BY best_lap_time ASC, filename ASC LIMIT 1',
            (game, car_class, track, session_type,
             iso, iso, before_filename or '')).fetchone()
        return _to_record(row) if row else None
    finally:
        conn.close()


def combo_history(game, car_class, track, session_type,
                  up_to_date=None, up_to_filename=''):
    """
    Every indexed session for one game/car class/track/session type,
    oldest first — the input for grading.trend(). When (up_to_date,
    up_to_filename) is given, only sessions at or before it are included,
    so a trend shown on an old session never reflects results that
    hadn't happened yet. Empty list when any key part is missing.
    """
    if not (game and car_class and track and session_type):
        return []
    sql = ('SELECT * FROM sessions '
           'WHERE game = ? AND car_class = ? AND track = ? '
           'AND session_type = ? AND date IS NOT NULL ')
    args = [game, car_class, track, session_type]
    if up_to_date is not None:
        iso = up_to_date.isoformat()
        sql += 'AND (date < ? OR (date = ? AND filename <= ?)) '
        args += [iso, iso, up_to_filename or '']
    sql += 'ORDER BY date ASC, filename ASC'
    conn = _connect()
    try:
        return [_to_record(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()
