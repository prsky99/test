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


def test_a_new_frontend_slot_is_warmed_with_fresh_queries_until_fast_then_recommends(tmp_path):
    # 11-11: fixed warm queries were served from the shared Redis cache, so the new process never ran a
    # search and the first public query took 14.4 s. Warm-up now uses unseen queries until two are fast.
    import random
    import httpx
    from scripts import service_deploy
    import json
    seen, slow, bodies, marks = [], iter([9000, 0, 0]), [], []

    def handler(request):
        seen.append((request.url.port, request.method, request.url.path, request.url.params.get('q'), request.headers['host']))
        marks.append({'user-agent': request.headers.get('user-agent'), 'x-agentcon-qa': request.headers.get('x-agentcon-qa')})
        if request.method == 'POST':
            bodies.append(json.loads(request.content))
            if bodies[-1]['params']['name'] == 'chat':
                return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 2, 'result': {}},
                                      headers={'Server-Timing': 'step_search;dur=812, ann;dur=400'})
        if request.url.path == '/api/explore':
            delay = next(slow, 0)
            if delay == 9000:
                raise httpx.ConnectError('cold')
            return httpx.Response(200, json={'items': []})
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 1, 'result': {}})
    manager = Reclaim(tmp_path, _state(retained_at=0.0))
    timings = manager.warm_web('frontend', 'a', transport=httpx.MockTransport(handler), rng=random.Random(7))
    explore = [t for t in timings if t['kind'] == 'explore']
    assert [t['status'] for t in explore][:1] == ['ConnectError'] and all(t['status'] == 200 for t in explore[1:])
    assert len(explore) >= 3 and [t['kind'] for t in timings[-2:]] == ['recommend', 'chat']
    assert all(t['status'] == 200 for t in timings[-2:])
    assert not set(t['q'] for t in explore) & set(service_deploy.WARM_QUERIES)   # never the cached fixed queries
    assert seen[0][:3] == (8401, 'GET', '/api/explore') and seen[0][4] == 'agentconcierge.biz'
    assert [s[1:3] for s in seen[-2:]] == [('POST', '/mcp'), ('POST', '/mcp')]
    # 11-12: the warm-up Chat is an unseen action task, marked as our own measurement
    assert bodies[-1]['params']['name'] == 'chat' and bodies[-2]['params']['name'] == 'find_agents'
    message = bodies[-1]['params']['arguments']['message']
    assert message.rsplit(' ', 1)[0] in service_deploy.WARM_CHAT_TASKS and message.rsplit(' ', 1)[1].isdigit()
    assert all(h['user-agent'] == 'agentcon-deploy-warm' and h['x-agentcon-qa'] == 'deploy-warm' for h in marks)
    assert timings[-1]['server_timing'] == 'step_search;dur=812, ann;dur=400' and timings[-1]['q'] == message
    summary = manager.warm_summary(timings)
    assert summary['explore_goal_met'] and summary['recommend_goal_met'] and summary['first_explore_ms'] is not None
    assert summary['chat_ms'] is not None and summary['chat_goal_met'] and summary['chat_timing'].startswith('step_search')
    assert manager.warm_web('admin', 'a', transport=httpx.MockTransport(handler)) == []
    assert manager.warm_web('frontend', 'b') == []  # tests never reach a real slot


def test_warm_summary_reports_a_missed_target():
    from scripts.service_deploy import Deployment
    timings = [{'kind': 'explore', 'q': 'a', 'status': 200, 'ms': 14400},
               {'kind': 'explore', 'q': 'b', 'status': 200, 'ms': 2600},
               {'kind': 'recommend', 'q': 'c', 'status': 200, 'ms': 5300}]
    summary = Deployment.warm_summary(timings)
    assert summary == {'explore_calls': 2, 'first_explore_ms': 14400, 'last_explore_ms': 2600, 'explore_goal_met': False,
                       'recommend_ms': 5300, 'recommend_goal_met': False, 'chat_ms': None, 'chat_timing': None,
                       'chat_goal_met': False}


def test_deploy_warms_before_switching():
    import inspect
    from scripts.service_deploy import Deployment
    source = inspect.getsource(Deployment.deploy)
    assert source.index('self.warm_web(role, new)') < source.index("service['active'] = new")


def test_package_from_a_commit_ignores_working_tree_edits_and_records_the_hash(tmp_path, monkeypatch):
    """11-10 operations = git: uncommitted working-tree edits reached production through overlays."""
    import subprocess
    monkeypatch.delenv('AGENTCON_RELEASE_BASE', raising=False)
    root = _tree(tmp_path)
    git = lambda *a: subprocess.run(['git', *a], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    git('init', '-q'); git('config', 'user.email', 't@example.com'); git('config', 'user.name', 't')
    (root / 'scripts' / 'keep.py').write_text('x = 1\n')
    (root / 'new' / 'index.html').write_text('<p>ok</p>\n')
    (root / 'pyproject.toml').write_text('[project]\nname = "x"\n')
    (root / '.gitignore').write_text('.venv/\n')
    git('add', '.'); git('commit', '-q', '-m', 'one')
    sha = git('rev-parse', 'HEAD')
    (root / 'agent_market' / 'x.py').write_text('x = 2  # uncommitted\n')
    (root / 'scripts' / 'stray.py').write_text('untracked\n')
    manager = Deployment(root, state_dir=tmp_path / 'state')
    result = manager.package('git-frontend-r1', commit='HEAD')
    release = tmp_path / 'state' / 'releases' / 'git-frontend-r1'
    assert result['commit'] == sha
    assert json.loads((release / 'release.json').read_text())['commit'] == sha
    assert (release / 'agent_market' / 'x.py').read_text() == 'x = 1\n'
    assert not (release / 'scripts' / 'stray.py').exists()
    assert manager.release_commit('git-frontend-r1') == sha
    import pytest
    with pytest.raises(ValueError, match='unknown_commit'):
        manager.package('git-frontend-r2', commit='no-such-ref')
    with pytest.raises(ValueError, match='invalid_commit'):
        manager.package('git-frontend-r3', commit='--upload-pack=x')


def test_deploy_waits_for_the_new_slot_report_snapshot_before_warming_and_switching(tmp_path):
    import inspect
    from scripts.service_deploy import Deployment
    source = inspect.getsource(Deployment.deploy)
    assert source.index('self.wait_snapshot(role, new, release)') < source.index('self.warm_web(role, new)') \
        < source.index("service['active'] = new")
    manager = Reclaim(tmp_path, _state(retained_at=0.0))
    states, now = iter(['building', 'building', 'ready']), [0.0]
    manager.probe = lambda role, slot, release=None: {'ready': True, 'report_snapshot': next(states)}
    result = manager.wait_snapshot('frontend', 'a', 'r1', sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert result == {'state': 'ready', 'seconds': 10.0}
    manager.probe = lambda role, slot, release=None: {'ready': True}   # an older release without the field
    assert manager.wait_snapshot('frontend', 'a', 'r1', sleep=lambda s: None)['state'] == 'absent'
    manager.probe = lambda role, slot, release=None: {'ready': True, 'report_snapshot': 'building'}
    now[0] = 0.0
    late = manager.wait_snapshot('frontend', 'a', 'r1', budget=30, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert late['state'] == 'building' and late['seconds'] >= 30   # a timeout never blocks the deploy
    assert manager.wait_snapshot('admin', 'a', 'r1') is None


def _replying(monkeypatch, code, body):
    """Answer the private readiness probe with CODE and the JSON BODY, without a network or key file."""
    import io
    import urllib.error
    import scripts.service_deploy as module

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Opener:
        def open(self, request, timeout=None):
            data = json.dumps(body).encode()
            if code != 200:
                raise urllib.error.HTTPError(request.full_url, code, 'x', {}, io.BytesIO(data))
            return Reply(data)

    monkeypatch.setattr(module, 'read_settings', lambda path: {'APPLICATION_WORKFLOW_KEY_FILE': '/k'})
    monkeypatch.setattr(module, '_private_bytes', lambda path, size: b'k' * 32)
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *handlers: Opener())


def test_an_unready_old_slot_still_drains_so_it_can_be_reclaimed(tmp_path, monkeypatch):
    # 11-12 07:12: admin's old slot (336ad6b1) failed the schema check after a DB change and answered the
    # readiness probe with 503; drained() raised HTTPError, so reclaim-standby crashed and kept 1.5 GB alive.
    manager = Deployment(tmp_path, state_dir=tmp_path / 'state')
    _replying(monkeypatch, 503, {'ready': False, 'role': 'admin', 'release': 'old', 'active_requests': 0})
    assert manager.drained('admin', 'b', timeout=1) is True
    try:
        manager.probe('admin', 'b')
    except RuntimeError as error:
        assert str(error) == 'candidate_not_ready'
    else:
        raise AssertionError('probe must still refuse an unready slot')


def test_busy_or_foreign_replies_are_not_drained(tmp_path, monkeypatch):
    manager = Deployment(tmp_path, state_dir=tmp_path / 'state')
    _replying(monkeypatch, 503, {'ready': False, 'role': 'admin', 'active_requests': 2})
    assert manager.drained('admin', 'b', timeout=0.01) is False
    _replying(monkeypatch, 503, {'ready': False, 'role': 'frontend', 'active_requests': 0})
    assert manager.drained('admin', 'b', timeout=0.01) is False
