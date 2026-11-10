"""Daily snapshots carry the AI AD Coin v2 keys, and the Mac mini copy is checked byte for byte (2026-11-10).
Losing owner-link.key would show every site user as a new v2 account with no balance."""
import hashlib
import json
import os

import pytest

from scripts import runtime_snapshot, scheduled_backup


def _keys(tmp_path):
    keys = tmp_path / 'ad_coin_v2_keys'
    keys.mkdir(mode=0o700)
    for name, data in (('owner-link.key', b'o' * 64), ('signing.pem', b'-----BEGIN-----'), ('fresh.key', b'f' * 64)):
        path = keys / name
        path.write_bytes(data)
        os.chmod(path, 0o600)
    return keys


def test_key_directory_is_copied_privately_with_digests(tmp_path):
    keys = _keys(tmp_path)
    target = tmp_path / 'snapshot' / 'ad_coin_v2_keys'
    target.parent.mkdir(mode=0o700)
    digests = runtime_snapshot.copy_key_directory(str(keys), target)
    assert sorted(digests) == ['fresh.key', 'owner-link.key', 'signing.pem']
    assert digests['owner-link.key'] == hashlib.sha256(b'o' * 64).hexdigest()
    assert (target / 'owner-link.key').read_bytes() == b'o' * 64
    assert all(oct(p.stat().st_mode & 0o777) == '0o600' for p in target.iterdir())
    assert oct(target.stat().st_mode & 0o777) == '0o700'
    assert runtime_snapshot.copy_key_directory(None, tmp_path / 'none') == {}


def test_a_key_readable_by_others_fails_the_snapshot(tmp_path):
    keys = _keys(tmp_path)
    os.chmod(keys / 'owner-link.key', 0o644)
    with pytest.raises(Exception):
        runtime_snapshot.copy_key_directory(str(keys), tmp_path / 'out')


def test_offsite_copy_verifies_key_digests(tmp_path):
    source = tmp_path / 'snapshot-20261111-043005'
    source.mkdir()
    (source / 'database.dump').write_bytes(b'dump')
    runtime_snapshot.copy_key_directory(str(_keys(tmp_path)), source / 'ad_coin_v2_keys')
    digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source / 'ad_coin_v2_keys').iterdir()}
    (source / 'manifest.json').write_text(json.dumps({'files': {'database.dump': {'bytes': 4}}, 'ad_coin_v2_keys': digests}))
    share = tmp_path / 'share'
    share.mkdir()
    result = scheduled_backup.copy_offsite(source, share / 'agentconcierge-backups', 7, mounted=lambda p: True)
    assert result['status'] == 'ok'
    assert (share / 'agentconcierge-backups' / source.name / 'ad_coin_v2_keys' / 'owner-link.key').read_bytes() == b'o' * 64
    bad = json.loads((source / 'manifest.json').read_text())
    bad['ad_coin_v2_keys']['owner-link.key'] = '0' * 64
    other = tmp_path / 'snapshot-20261112-043005'
    import shutil
    shutil.copytree(source, other)
    (other / 'manifest.json').write_text(json.dumps(bad))
    with pytest.raises(RuntimeError, match='offsite_key_copy_mismatch'):
        scheduled_backup.copy_offsite(other, share / 'agentconcierge-backups', 7, mounted=lambda p: True)
