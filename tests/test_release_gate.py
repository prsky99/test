import json

import pytest

from scripts import release_gate


def test_unknown_release_is_refused(tmp_path):
    with pytest.raises(SystemExit, match='release not found'):
        release_gate.copy_release('no-such-release', tmp_path)


def test_default_list_covers_the_opening_paths():
    assert all((release_gate.ROOT / test.split('::')[0]).is_file() for test in release_gate.TESTS)
    assert 'tests/test_ad_coin.py::test_organic_selection_cannot_import_ad_coin' in release_gate.TESTS
    assert 'tests/test_customer_batch.py' in release_gate.TESTS


def test_frontend_deploy_refuses_a_failing_gate(tmp_path):
    from types import SimpleNamespace
    from scripts import service_deploy
    with pytest.raises(SystemExit, match='release_gate_unavailable'):
        service_deploy.release_gate(tmp_path, 'r1')
    python = tmp_path / '.venv-tests' / 'bin' / 'python'
    python.parent.mkdir(parents=True)
    python.write_text('')
    calls = []

    def runner(code):
        def run(command, **kwargs):
            calls.append((command, kwargs['cwd']))
            return SimpleNamespace(returncode=code)
        return run

    service_deploy.release_gate(tmp_path, 'r1', runner(0))
    assert calls == [([str(python), '-m', 'scripts.release_gate', 'r1'], str(tmp_path))]
    with pytest.raises(SystemExit, match='release_gate_failed: r1'):
        service_deploy.release_gate(tmp_path, 'r1', runner(1))


def test_deploy_command_runs_the_gate_only_for_frontend(monkeypatch):
    from scripts import service_deploy
    gated, deployed = [], []
    monkeypatch.setattr(service_deploy, 'release_gate', lambda root, release: gated.append(release))

    class Manager:
        def __init__(self, root):
            pass

        def deploy(self, role, release, **options):
            deployed.append((role, release))
            return {}

        def check_base(self, role, release, state=None, force=False):  # base check since 1b67c238
            return None

        def prune_after_deploy(self):  # every verified deploy prunes old releases since 5a4677e3
            return {}

    monkeypatch.setattr(service_deploy, 'Deployment', Manager)
    for argv in (['deploy', 'frontend', 'f1'], ['deploy', 'admin', 'a1'], ['deploy', 'frontend', 'f2', '--skip-gate']):
        from scripts import service_deploy as _sd
        monkeypatch.setattr(_sd, 'check_board_lock', lambda root, owner: None)
        monkeypatch.setattr('sys.argv', ['service_deploy', *argv, '--lock-owner', '운영·SRE'])
        service_deploy.main()
    assert gated == ['f1'] and deployed == [('frontend', 'f1'), ('admin', 'a1'), ('frontend', 'f2')]


def test_each_role_gets_its_own_test_list(tmp_path, monkeypatch):
    """11-10: jobs releases have no typed_engine_for, so the frontend opening tests do not fit them."""
    monkeypatch.setattr(release_gate, 'RELEASES', tmp_path)
    for name, declared in (('growth-md-jobs-20261110-r2', None), ('category-bg-frontend-20261110-r1', None),
                           ('ops-traffic-admin-20261109-r1', None), ('docs-execution-20261031-r2', None),
                           ('odd-name-r1', 'jobs')):
        (tmp_path / name).mkdir()
        (tmp_path / name / 'release.json').write_text(json.dumps({'release': name, **({'role': declared} if declared else {})}))
    assert release_gate.release_role('growth-md-jobs-20261110-r2') == 'jobs'
    assert release_gate.release_role('category-bg-frontend-20261110-r1') == 'frontend'
    assert release_gate.release_role('ops-traffic-admin-20261109-r1') == 'admin'
    assert release_gate.release_role('docs-execution-20261031-r2') == 'execution'
    assert release_gate.release_role('odd-name-r1') == 'jobs'
    with pytest.raises(SystemExit, match='release role unknown'):
        release_gate.release_role('no-role-r1')
    assert release_gate.ROLE_TESTS['frontend'] == release_gate.TESTS
    assert 'tests/test_typed_engine_for.py' in release_gate.ROLE_TESTS['frontend']
    assert 'tests/test_typed_engine_for.py' not in release_gate.ROLE_TESTS['jobs']
    assert all((release_gate.ROOT / test.split('::')[0]).is_file() for tests in release_gate.ROLE_TESTS.values() for test in tests)


def test_main_runs_the_role_list_and_compares_chat_only_for_frontend(tmp_path, monkeypatch):
    monkeypatch.setattr(release_gate, 'RELEASES', tmp_path)
    ran, chat = [], []
    monkeypatch.setattr(release_gate, 'run', lambda release, tests, python: ran.append((release, tuple(tests))) or 0)
    monkeypatch.setattr(release_gate, 'chat_check', lambda release: chat.append(release) or 0)
    for name in ('x-jobs-20261110-r1', 'x-frontend-20261110-r1'):
        (tmp_path / name).mkdir()
        (tmp_path / name / 'release.json').write_text(json.dumps({'release': name}))
    assert release_gate.main(['x-jobs-20261110-r1']) == 0
    assert release_gate.main(['x-frontend-20261110-r1']) == 0
    assert release_gate.main(['x-jobs-20261110-r1', 'tests/test_a2a.py']) == 0
    assert ran == [('x-jobs-20261110-r1', release_gate.JOBS_TESTS), ('x-frontend-20261110-r1', release_gate.TESTS),
                   ('x-jobs-20261110-r1', ('tests/test_a2a.py',))]
    assert chat == ['x-frontend-20261110-r1']


def test_gate_tests_come_from_the_commit_not_the_working_copy(tmp_path, monkeypatch):
    """11-10: another session's uncommitted edits to tests/test_collector.py failed an unrelated release."""
    import subprocess
    release_gate.committed_tests(tmp_path)
    head = subprocess.run(['git', 'show', 'HEAD:tests/test_release_gate.py'], cwd=release_gate.ROOT,
                          capture_output=True, check=True).stdout
    assert (tmp_path / 'tests' / 'test_release_gate.py').read_bytes() == head
