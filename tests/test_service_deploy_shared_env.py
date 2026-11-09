"""Releases share one environment per dependency set, and a retained previous slot is stopped after a
while (2026-11-10, 운영·SRE). 28 releases a day each cloned .venv; macOS assessed every new copy, and the
retained slot kept about 1.5 GB in a 16 GB machine that was swapping."""
import json
import os

from scripts.service_deploy import Deployment


def _tree(tmp_path, packages=('httpx-0.28.1',)):
    root = tmp_path / 'tree'
    for name in ('agent_market', 'scripts', 'new'):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / 'agent_market' / 'x.py').write_text('x = 1\n')
    venv = root / '.venv'
    site = venv / 'lib' / 'python3.11' / 'site-packages'
    site.mkdir(parents=True, exist_ok=True)
    (venv / 'pyvenv.cfg').write_text('home = /toolchain/bin\nversion = 3.11.18\n')
    for existing in site.glob('*.dist-info'):
        existing.rmdir()
    for name in packages:
        (site / (name + '.dist-info')).mkdir()
    return root


def test_releases_with_the_same_dependencies_share_one_environment(tmp_path, monkeypatch):
    monkeypatch.delenv('AGENTCON_RELEASE_BASE', raising=False)
    root = _tree(tmp_path)
    manager = Deployment(root, state_dir=tmp_path / 'state')
    manager.package('one-frontend-r1')
    manager.package('two-frontend-r1')
    releases = tmp_path / 'state' / 'releases'
    first, second = releases / 'one-frontend-r1' / '.venv', releases / 'two-frontend-r1' / '.venv'
    assert first.is_symlink() and second.is_symlink()
    assert os.path.realpath(first) == os.path.realpath(second)
    assert (first / 'pyvenv.cfg').read_text().startswith('home =')
    manager.verify_release('one-frontend-r1')


def test_new_dependencies_get_a_new_environment_and_old_releases_keep_theirs(tmp_path, monkeypatch):
    monkeypatch.delenv('AGENTCON_RELEASE_BASE', raising=False)
    root = _tree(tmp_path)
    manager = Deployment(root, state_dir=tmp_path / 'state')
    manager.package('old-jobs-r1')
    old = os.path.realpath(tmp_path / 'state' / 'releases' / 'old-jobs-r1' / '.venv')
    _tree(tmp_path, packages=('httpx-0.28.1', 'psycopg-3.2.9'))
    manager.package('new-jobs-r1')
    new = os.path.realpath(tmp_path / 'state' / 'releases' / 'new-jobs-r1' / '.venv')
    assert old != new
    assert sorted(p.name for p in (tmp_path / 'state' / 'releases' / 'old-jobs-r1' / '.venv' / 'lib' / 'python3.11' / 'site-packages').iterdir()) == ['httpx-0.28.1.dist-info']
    # The runtime lock is part of the identity too.
    (root / 'requirements-runtime.lock').write_text('httpx==0.28.1\n')
    key_with_lock = manager.environment_key(root)
    (root / 'requirements-runtime.lock').write_text('httpx==0.28.2\n')
    assert manager.environment_key(root) != key_with_lock


def test_an_environment_without_installed_distributions_is_copied_as_before(tmp_path, monkeypatch):
    monkeypatch.delenv('AGENTCON_RELEASE_BASE', raising=False)
    root = _tree(tmp_path, packages=())
    manager = Deployment(root, state_dir=tmp_path / 'state')
    manager.package('plain-admin-r1')
    venv = tmp_path / 'state' / 'releases' / 'plain-admin-r1' / '.venv'
    assert venv.is_dir() and not venv.is_symlink()


def test_unused_environments_are_pruned_with_their_last_release(tmp_path, monkeypatch):
    monkeypatch.delenv('AGENTCON_RELEASE_BASE', raising=False)
    root = _tree(tmp_path)
    manager = Deployment(root, state_dir=tmp_path / 'state')
    manager.package('a-frontend-r1')
    key = os.path.basename(os.path.realpath(tmp_path / 'state' / 'releases' / 'a-frontend-r1' / '.venv'))
    assert manager.prune_environments() == []
    (tmp_path / 'state' / 'releases' / 'a-frontend-r1' / '.venv').unlink()
    assert manager.prune_environments() == [key]
    assert manager.prune_environments(apply=True) == [key]
    assert not (tmp_path / 'state' / 'venvs' / key).exists()


class Reclaim(Deployment):
    def __init__(self, tmp_path, state):
        super().__init__(tmp_path, state_dir=tmp_path / 'state')
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / 'state.json').write_text(json.dumps(state))
        self.running, self.stopped = {('frontend', 'a'), ('frontend', 'b'), ('admin', 'a'), ('admin', 'b')}, []

    def pid(self, role, slot):
        return 1 if (role, slot) in self.running else None

    def drained(self, role, slot, timeout=100):
        return True

    def stop(self, role, slot, timeout=130):
        self.running.discard((role, slot))
        self.stopped.append((role, slot))


def _state(retained_at):
    return {'version': 1, 'managed': True, 'phase': 'retained', 'services': {
        'frontend': {'active': 'b', 'previous': 'a', 'retained_at': retained_at, 'slots': {'a': 'f-old', 'b': 'f-new'}},
        'admin': {'active': 'a', 'previous': 'b', 'slots': {'a': 'a-new', 'b': 'a-old'}},
        'jobs': {'release': 'j'}, 'execution': {'release': 'e'}}}


def test_the_previous_slot_is_stopped_only_after_the_window_and_state_keeps_it(tmp_path):
    manager = Reclaim(tmp_path, _state(retained_at=1000.0))
    assert manager.reclaim_standby(min_age=1800, now=1000.0 + 1799) == {'stopped': []}
    result = manager.reclaim_standby(min_age=1800, now=1000.0 + 1800)
    assert result == {'stopped': [{'role': 'frontend', 'slot': 'a', 'release': 'f-old'}]}
    # admin has no retained_at (deployed before this change): its previous slot is left alone.
    assert manager.stopped == [('frontend', 'a')]
    state = manager.state()
    assert state['services']['frontend']['previous'] == 'a' and state['services']['frontend']['slots']['a'] == 'f-old'
    assert manager.reclaim_standby(min_age=1800, now=1000.0 + 4000) == {'stopped': []}


def test_reclaim_waits_for_an_interrupted_deployment(tmp_path):
    state = _state(retained_at=0.0)
    state['phase'] = 'switching'
    manager = Reclaim(tmp_path, state)
    assert manager.reclaim_standby(min_age=0, now=10.0)['stopped'] == []
    assert manager.stopped == []


def test_rollback_starts_a_stopped_previous_slot_again():
    import inspect
    source = inspect.getsource(Deployment.rollback)
    assert 'if not self.pid(role, new):' in source and 'self.start(role, new' in source


def test_restart_redeploys_the_active_release_and_never_packages_the_working_tree(tmp_path):
    """11-10: restart packaged the working tree, uncommitted edits of other sessions included."""
    manager = Reclaim(tmp_path, _state(retained_at=0.0))
    calls = []
    manager.package = lambda *a, **k: calls.append(('package', a))
    manager.deploy = lambda role, release, force_base=False: calls.append(('deploy', role, release, force_base)) or {'service': role}
    result = manager.restart_web()
    assert calls == [('deploy', 'frontend', 'f-new', True), ('deploy', 'admin', 'a-new', True)]
    assert result['packaged'] is False
    calls.clear()
    manager.restart_web('admin')
    assert calls == [('deploy', 'admin', 'a-new', True)]


def test_a_new_frontend_slot_is_warmed_with_searches_and_failures_do_not_block(tmp_path):
    import httpx
    from scripts import service_deploy
    seen = []

    def handler(request):
        seen.append((request.url.host, request.url.port, request.url.path, request.url.params.get('q'), request.headers['host']))
        if request.url.params.get('q') == 'web search':
            raise httpx.ConnectError('cold')
        return httpx.Response(200, json={'items': []})
    manager = Reclaim(tmp_path, _state(retained_at=0.0))
    timings = manager.warm_web('frontend', 'a', transport=httpx.MockTransport(handler))
    assert [t['q'] for t in timings] == list(service_deploy.WARM_QUERIES)
    assert [t['status'] for t in timings] == [200, 'ConnectError', 200, 200]
    assert seen[0][:3] == ('127.0.0.1', 8401, '/api/explore') and seen[0][4] == 'agentconcierge.biz'
    assert manager.warm_web('admin', 'a', transport=httpx.MockTransport(handler)) == []
    assert manager.warm_web('frontend', 'b') == []  # tests never reach a real slot


def test_deploy_warms_before_switching():
    import inspect
    from scripts.service_deploy import Deployment
    source = inspect.getsource(Deployment.deploy)
    assert source.index('self.warm_web(role, new)') < source.index("service['active'] = new")
