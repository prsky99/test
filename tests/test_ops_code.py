"""Operations jobs run a code folder built from a commit (precision review R05, 11-15)."""
import json
import os
import subprocess

import pytest

from scripts import ops_code


def _repo(tmp_path):
    root = tmp_path / 'repo'
    for path, text in (('scripts/scheduled_backup.py', 'print("v1")\n'), ('deploy/ops/house-ad-daily.sh', 'echo v1\n'),
                       ('agent_market/__init__.py', ''), ('notes.md', 'not code\n')):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    for data in ('gateway-data', 'logs', 'exports', '.venv', '.venv-tests'):
        (root / data).mkdir(exist_ok=True)
    (root / '.gitignore').write_text('gateway-data/\nlogs/\nexports/\n.venv/\n.venv-tests/\n')
    git = lambda *a: subprocess.run(['git', *a], cwd=root, check=True, capture_output=True)
    git('init', '-q'); git('-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '-A')
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'v1')
    return root, git


def test_install_exports_the_commit_links_the_data_and_switches_current(tmp_path):
    root, git = _repo(tmp_path)
    (root / 'scripts/scheduled_backup.py').write_text('print("working copy edit")\n')   # never shipped
    result = ops_code.install('HEAD', root, now=1000.0)
    base = root / 'gateway-data/ops-code'
    current = base / 'current'
    assert (current / 'scripts/scheduled_backup.py').read_text() == 'print("v1")\n'
    assert not (current / 'notes.md').exists()                                   # code paths only
    for data in ('gateway-data', 'logs', 'exports', '.venv'):
        assert os.readlink(current / data) == str(root / data)
    assert result['current']['commit'] == json.loads((current / 'ops-code.json').read_text())['commit']
    assert result['previous'] is None


def test_a_second_install_keeps_the_first_as_previous_and_rollback_returns_to_it(tmp_path):
    root, git = _repo(tmp_path)
    first = ops_code.install('HEAD', root, now=1000.0)['current']
    (root / 'scripts/scheduled_backup.py').write_text('print("v2")\n')
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qam', 'v2')
    second = ops_code.install('HEAD', root, now=2000.0)
    assert second['previous'] == first and second['current']['commit'] != first['commit']
    assert (root / 'gateway-data/ops-code/current/scripts/scheduled_backup.py').read_text() == 'print("v2")\n'
    back = ops_code.rollback(root)
    assert back['current'] == first
    assert (root / 'gateway-data/ops-code/current/scripts/scheduled_backup.py').read_text() == 'print("v1")\n'


def test_old_folders_are_pruned_but_current_and_previous_stay(tmp_path):
    root, git = _repo(tmp_path)
    for i in range(8):
        ops_code.install('HEAD', root, now=1000.0 + i * 100)
    status = ops_code.status(root)
    assert len(status['folders']) == ops_code.KEEP
    assert status['current']['folder'] in status['folders'] and status['previous']['folder'] in status['folders']


def test_a_commit_without_the_jobs_code_is_refused_and_current_is_untouched(tmp_path):
    root, git = _repo(tmp_path)
    ops_code.install('HEAD', root, now=1000.0)
    before = ops_code.status(root)['current']
    git('rm', '-q', 'deploy/ops/house-ad-daily.sh')
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'drop')
    with pytest.raises(ValueError, match='missing_in_commit'):
        ops_code.install('HEAD', root, now=2000.0)
    assert ops_code.status(root)['current'] == before
    assert not [p for p in (root / 'gateway-data/ops-code').iterdir() if p.name.startswith('.staging-')]
