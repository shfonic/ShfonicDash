#!/usr/bin/env python3
"""
Sync the shared sessionlog library into the Pythonista companion app.

The canonical code lives in src/sessionlog/ in this repo; the companion
app (ShfonicDashCompanion, in the Pythonista iCloud folder) carries a
vendored copy because Pythonista has no pip and its only sync channel is
iCloud. This script owns that copy:

    python3 sync_shared.py            # copy package + shared tests over
    python3 sync_shared.py --check    # report drift, copy nothing (exit 1)

What is synced:
  src/sessionlog/*.py      -> <companion>/sessionlog/*.py  (stale files pruned)
  tests/<shared tests>     -> <companion>/tests/
  <companion>/sessionlog/_manifest.json is (re)written with sha256 hashes;
  the shared test_sessionlog_drift.py fails the companion's CI if the
  vendored copy is ever edited directly.

Never edit the companion's sessionlog/ by hand — change it here, re-sync,
and commit both repos.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys

HERE          = os.path.dirname(os.path.abspath(__file__))
CANONICAL_PKG = os.path.join(HERE, 'src', 'sessionlog')
CANONICAL_TESTS = os.path.join(HERE, 'tests')

COMPANION = os.environ.get(
    'SHFONIC_COMPANION_DIR',
    os.path.expanduser(
        '~/Library/Mobile Documents/iCloud~com~omz-software~Pythonista3/'
        'Documents/ShfonicDashCompanion'))

# Tests that exercise sessionlog and therefore travel with it. test_api.py
# (and any future companion-only tests) stay untouched.
SHARED_TESTS = (
    'test_parser.py',
    'test_pace.py',
    'test_circuits.py',
    'test_trackmap.py',
    'test_grading.py',
    'test_career.py',
    'test_goals.py',
    'test_progression.py',
    'test_objectives.py',
    'test_focus.py',
    'test_debrief.py',
    'test_journal.py',
    'test_share.py',
    'test_profile.py',
    'test_achievements.py',
    'test_lines.py',
    'test_assists.py',
    'test_session_db.py',
    'test_sessionlog_drift.py',
    'test_avatar.py',
)


def _sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _pkg_files():
    return sorted(f for f in os.listdir(CANONICAL_PKG) if f.endswith('.py'))


def _sessionlog_version():
    ns = {}
    with open(os.path.join(CANONICAL_PKG, '__init__.py'), encoding='utf-8') as f:
        for line in f:
            if line.startswith('SESSIONLOG_VERSION'):
                exec(line, ns)   # noqa: S102 — our own constant line
    return ns['SESSIONLOG_VERSION']


def _diff():
    """[(relpath, state)] where state is 'missing' | 'differs' | 'stale'."""
    problems = []
    dest_pkg = os.path.join(COMPANION, 'sessionlog')
    for name in _pkg_files():
        dst = os.path.join(dest_pkg, name)
        if not os.path.exists(dst):
            problems.append((f'sessionlog/{name}', 'missing'))
        elif _sha256(dst) != _sha256(os.path.join(CANONICAL_PKG, name)):
            problems.append((f'sessionlog/{name}', 'differs'))
    if os.path.isdir(dest_pkg):
        for name in sorted(os.listdir(dest_pkg)):
            if name.endswith('.py') and name not in _pkg_files():
                problems.append((f'sessionlog/{name}', 'stale'))
    for name in SHARED_TESTS:
        src = os.path.join(CANONICAL_TESTS, name)
        dst = os.path.join(COMPANION, 'tests', name)
        if not os.path.exists(dst):
            problems.append((f'tests/{name}', 'missing'))
        elif _sha256(dst) != _sha256(src):
            problems.append((f'tests/{name}', 'differs'))
    return problems


def sync():
    dest_pkg = os.path.join(COMPANION, 'sessionlog')
    os.makedirs(dest_pkg, exist_ok=True)

    manifest = {'sessionlog_version': _sessionlog_version(), 'files': {}}
    for name in _pkg_files():
        src = os.path.join(CANONICAL_PKG, name)
        shutil.copyfile(src, os.path.join(dest_pkg, name))
        manifest['files'][name] = _sha256(src)
        print(f'  sessionlog/{name}')
    for name in sorted(os.listdir(dest_pkg)):
        if name.endswith('.py') and name not in manifest['files']:
            os.remove(os.path.join(dest_pkg, name))
            print(f'  sessionlog/{name} (removed — stale)')

    with open(os.path.join(dest_pkg, '_manifest.json'), 'w',
              encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write('\n')
    print('  sessionlog/_manifest.json')

    os.makedirs(os.path.join(COMPANION, 'tests'), exist_ok=True)
    for name in SHARED_TESTS:
        shutil.copyfile(os.path.join(CANONICAL_TESTS, name),
                        os.path.join(COMPANION, 'tests', name))
        print(f'  tests/{name}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument('--check', action='store_true',
                    help='report drift between canonical and vendored copies '
                         'without writing anything (exit 1 on drift)')
    args = ap.parse_args()

    if not os.path.isdir(COMPANION):
        sys.exit(f'companion app folder not found: {COMPANION}\n'
                 '(set SHFONIC_COMPANION_DIR to override)')

    if args.check:
        problems = _diff()
        if not problems:
            print('vendored copy is in sync')
            return
        for rel, state in problems:
            print(f'  {rel}: {state}')
        sys.exit(1)

    print(f'syncing into {COMPANION}')
    sync()
    print('done — run the companion test suite to confirm '
          '(cd to the app folder; python3 -m pytest)')


if __name__ == '__main__':
    main()
