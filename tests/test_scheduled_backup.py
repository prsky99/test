import json
import time

import pytest

from scripts import scheduled_backup


def _fake_snapshot(destination, settings_file):
    destination.mkdir(mode=0o700)
    (destination / 'manifest.json').write_text('{}')
    return {'created': 10.0, 'finished': 25.4, 'files': {'database.dump': {'bytes': 1234}}}


def _clock(day):
    return lambda: time.strptime(f'202611{day:02d} 043000', '%Y%m%d %H%M%S')


def test_run_takes_snapshot_and_keeps_newest(tmp_path):
    root = tmp_path / 'daily'
    for day in range(1, 5):
        result = scheduled_backup.run(root, 'settings.env', keep=2, count=lambda s: 5,
                                      take=_fake_snapshot, now=_clock(day))
    assert result['status'] == 'ok'
    assert result['snapshot'] == 'snapshot-20261104-043000'
    assert result['seconds'] == 15 and result['database_dump_bytes'] == 1234
    assert result['removed'] == ['snapshot-20261102-043000']
    assert sorted(p.name for p in root.iterdir()) == ['snapshot-20261103-043000', 'snapshot-20261104-043000']
    assert root.stat().st_mode & 0o777 == 0o700


def test_run_waits_then_skips_when_connections_stay_busy(tmp_path):
    waits = []
    taken = []
    result = scheduled_backup.run(tmp_path / 'daily', 's', limit=19, attempts=3, wait=7,
                                  count=lambda s: 20, take=lambda *a: taken.append(a),
                                  sleep=waits.append)
    assert result == {'status': 'skipped', 'reason': 'connections_busy', 'app_connections': 20}
    assert waits == [7, 7] and taken == []


def test_run_proceeds_once_connections_drop(tmp_path):
    counts = iter([22, 18])
    result = scheduled_backup.run(tmp_path / 'daily', 's', count=lambda s: next(counts),
                                  take=_fake_snapshot, sleep=lambda s: None, now=_clock(1))
    assert result['status'] == 'ok' and result['app_connections'] == 18


def test_prune_removes_failed_leftovers_older_than_newest_complete(tmp_path):
    for name, complete in [('snapshot-20261101-043000', True), ('snapshot-20261102-043000', False),
                           ('snapshot-20261103-043000', True), ('snapshot-20261104-043000', False)]:
        (tmp_path / name).mkdir()
        if complete:
            (tmp_path / name / 'manifest.json').write_text('{}')
    (tmp_path / 'other').mkdir()
    removed = scheduled_backup.prune(tmp_path, keep=7)
    assert removed == ['snapshot-20261102-043000']
    # An unfinished snapshot newer than every complete one may still be running.
    assert (tmp_path / 'snapshot-20261104-043000').exists() and (tmp_path / 'other').exists()


def test_run_refuses_shared_directory(tmp_path):
    root = tmp_path / 'daily'
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    with pytest.raises(ValueError, match='private_backup_directory_required'):
        scheduled_backup.run(root, 's', count=lambda s: 0, take=_fake_snapshot)


def _complete_snapshot(root, name, payload=b'dump'):
    path = root / name
    path.mkdir(parents=True)
    (path / 'database.dump').write_bytes(payload)
    (path / 'manifest.json').write_text(json.dumps({'files': {'database.dump': {'bytes': len(payload)}}}))
    return path


def test_copy_offsite_copies_verifies_and_keeps_newest(tmp_path):
    local, share = tmp_path / 'local', tmp_path / 'share'
    share.mkdir()
    target = share / 'agentconcierge-backups'
    for day in (1, 2, 3):
        result = scheduled_backup.copy_offsite(_complete_snapshot(local, f'snapshot-2026110{day}-043000'),
                                               target, keep=2, mounted=lambda p: p == str(share))
    assert result == {'status': 'ok', 'snapshot': 'snapshot-20261103-043000', 'removed': ['snapshot-20261101-043000']}
    assert sorted(p.name for p in target.iterdir()) == ['snapshot-20261102-043000', 'snapshot-20261103-043000']
    assert (target / 'snapshot-20261103-043000' / 'database.dump').read_bytes() == b'dump'
    again = scheduled_backup.copy_offsite(local / 'snapshot-20261103-043000', target, 2, mounted=lambda p: True)
    assert again['already'] is True


def test_copy_offsite_skips_unmounted_share_without_creating_folders(tmp_path):
    source = _complete_snapshot(tmp_path / 'local', 'snapshot-20261101-043000')
    target = tmp_path / 'Volumes' / 'kingstone' / 'agentconcierge-backups'
    result = scheduled_backup.copy_offsite(source, target, 7, mounted=lambda p: False)
    assert result == {'status': 'skipped', 'reason': 'share_not_mounted'}
    assert not (tmp_path / 'Volumes').exists()


def test_copy_offsite_rejects_truncated_copy(tmp_path):
    source = _complete_snapshot(tmp_path / 'local', 'snapshot-20261101-043000')
    (source / 'manifest.json').write_text(json.dumps({'files': {'database.dump': {'bytes': 999}}}))
    target = tmp_path / 'share' / 'backups'
    (tmp_path / 'share').mkdir()
    with pytest.raises(RuntimeError, match='offsite_copy_size_mismatch'):
        scheduled_backup.copy_offsite(source, target, 7, mounted=lambda p: True)
    assert list(target.iterdir()) == []


def test_run_keeps_local_snapshot_when_offsite_copy_fails(tmp_path):
    def broken(*args):
        raise OSError('share went away')
    result = scheduled_backup.run(tmp_path / 'daily', 's', copy_to='/Volumes/x/y', count=lambda s: 0,
                                  take=_fake_snapshot, now=_clock(1), copy=broken)
    assert result['status'] == 'ok'
    assert result['offsite'] == {'status': 'failed', 'error': 'OSError'}
    assert (tmp_path / 'daily' / 'snapshot-20261101-043000').exists()
