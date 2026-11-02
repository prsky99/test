import pytest

from scripts import release_gate


def test_unknown_release_is_refused(tmp_path):
    with pytest.raises(SystemExit, match='release not found'):
        release_gate.copy_release('no-such-release', tmp_path)


def test_default_list_covers_the_opening_paths():
    assert all((release_gate.ROOT / test).is_file() for test in release_gate.TESTS)
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

        def deploy(self, role, release):
            deployed.append((role, release))
            return {}

    monkeypatch.setattr(service_deploy, 'Deployment', Manager)
    for argv in (['deploy', 'frontend', 'f1'], ['deploy', 'admin', 'a1'], ['deploy', 'frontend', 'f2', '--skip-gate']):
        monkeypatch.setattr('sys.argv', ['service_deploy', *argv])
        service_deploy.main()
    assert gated == ['f1'] and deployed == [('frontend', 'f1'), ('admin', 'a1'), ('frontend', 'f2')]
