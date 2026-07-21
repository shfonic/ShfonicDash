"""
Drift check for the vendored sessionlog package.

Shared test: lives canonically in ShfonicDash/tests/ and is copied
into the companion repo by sync_shared.py.

In the companion repo the sessionlog/ package is a vendored copy written
by sync_shared.py alongside a _manifest.json of file hashes. This test
fails if any vendored file was edited directly or the copy is otherwise
inconsistent — the fix is always to edit the canonical copy in
ShfonicDash/src/sessionlog/ and re-run sync_shared.py.

In the canonical repo there is no manifest and the test skips.
"""

import hashlib
import json
import os

import pytest

import sessionlog

PKG_DIR  = os.path.dirname(os.path.abspath(sessionlog.__file__))
MANIFEST = os.path.join(PKG_DIR, '_manifest.json')


def _sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.mark.skipif(not os.path.exists(MANIFEST),
                    reason='no manifest — canonical home, nothing vendored')
def test_vendored_copy_matches_manifest():
    with open(MANIFEST, encoding='utf-8') as f:
        manifest = json.load(f)

    assert manifest['sessionlog_version'] == sessionlog.SESSIONLOG_VERSION, (
        'vendored SESSIONLOG_VERSION differs from the manifest — '
        're-run sync_shared.py from ShfonicDash')

    files = {f for f in os.listdir(PKG_DIR) if f.endswith('.py')}
    assert files == set(manifest['files']), (
        'vendored sessionlog file set differs from the manifest — '
        're-run sync_shared.py; never add/remove files in the vendored copy')

    for name, digest in sorted(manifest['files'].items()):
        assert _sha256(os.path.join(PKG_DIR, name)) == digest, (
            f'sessionlog/{name} differs from the synced version — edit the '
            'canonical copy in ShfonicDash/src/sessionlog/ and '
            're-run sync_shared.py')
