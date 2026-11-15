"""Backups carry the state outside the database (precision review R51, 11-15) and a failed copy is not a success."""
import hashlib
import os
import tarfile

from scripts import runtime_snapshot, scheduled_backup


def test_state_archive_holds_files_with_digests_lists_missing_and_skips_links(tmp_path):
    root = tmp_path / 'root'
    (root / 'gateway-data/necklaces/results').mkdir(parents=True)
    (root / 'gateway-data/necklaces/approvals.json').write_text('{"substitutes": []}')
    (root / 'gateway-data/necklaces/results/a.json').write_text('{}')
    (root / 'gateway-data/sponsored.env').write_text('AD_COIN_PAID_BOOKING_ENABLED=1\n')
    (root / 'logs/ops').mkdir(parents=True)
    (root / 'logs/ops/status-board.md').write_text('# board\n')
    os.symlink(root / 'logs/ops/status-board.md', root / 'gateway-data/necklaces/link.md')
    out = tmp_path / 'snap'
    out.mkdir()
    state = runtime_snapshot.copy_state(root, out, ('gateway-data/necklaces', 'gateway-data/sponsored.env',
                                                    'logs/ops/status-board.md', 'gateway-data/signing'))
    assert set(state['files']) == {'gateway-data/necklaces/approvals.json', 'gateway-data/necklaces/results/a.json',
                                   'gateway-data/sponsored.env', 'logs/ops/status-board.md'}
    assert state['files']['logs/ops/status-board.md'] == hashlib.sha256(b'# board\n').hexdigest()
    assert state['missing'] == ['gateway-data/signing'] and state['skipped_symlinks'] == ['gateway-data/necklaces/link.md']
    archive = out / 'state.tar.gz'
    assert oct(archive.stat().st_mode & 0o777) == '0o600'
    with tarfile.open(archive) as tar:
        members = {m.name: m for m in tar.getmembers()}
        assert set(members) == set(state['files']) and all(m.mode == 0o600 for m in members.values())
        assert tar.extractfile('gateway-data/sponsored.env').read() == b'AD_COIN_PAID_BOOKING_ENABLED=1\n'


def test_the_production_list_names_the_reviewed_state():
    for name in ('gateway-data/necklaces', 'exports/pearls', 'gateway-data/web-bot-auth', 'gateway-data/sponsored.env',
                 'gateway-data/edge-gateway.json', 'gateway-data/services/state.json', 'logs/ops/status-board.md',
                 'logs/ops/user-slo.jsonl', 'logs/ops/error-ledger-known.json', 'gateway-data/signing'):
        assert name in runtime_snapshot.STATE_PATHS


def test_exit_code_is_non_zero_when_the_offsite_copy_did_not_happen():
    ok = {'status': 'ok', 'offsite': {'status': 'ok'}}
    assert scheduled_backup.exit_code(ok, '/Volumes/x/backups') == 0
    assert scheduled_backup.exit_code({'status': 'ok'}, None) == 0                      # no copy asked for
    assert scheduled_backup.exit_code({'status': 'ok', 'offsite': {'status': 'failed'}}, '/Volumes/x/b') == 3
    assert scheduled_backup.exit_code({'status': 'ok', 'offsite': {'status': 'skipped'}}, '/Volumes/x/b') == 3
    assert scheduled_backup.exit_code({'status': 'skipped'}, '/Volumes/x/b') == 2


def test_the_snapshot_root_is_the_project_also_from_the_ops_code_folder(tmp_path, monkeypatch):
    """R05: the backup job runs in gateway-data/ops-code/current, whose gateway-data links to the project's."""
    import inspect
    project = tmp_path / 'project'
    (project / 'gateway-data/ops-code/c1').mkdir(parents=True)
    os.symlink(project / 'gateway-data', project / 'gateway-data/ops-code/c1/gateway-data')
    source = inspect.getsource(runtime_snapshot.snapshot)
    assert "root = Path(os.path.realpath(Path.cwd() / 'gateway-data')).parent" in source
    for cwd in (project, project / 'gateway-data/ops-code/c1'):
        monkeypatch.chdir(cwd)
        assert runtime_snapshot.Path(os.path.realpath(runtime_snapshot.Path.cwd() / 'gateway-data')).parent == project.resolve()
