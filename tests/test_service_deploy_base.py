"""배포 도구가 낡은 기준 판으로 만든 릴리스를 스스로 거부한다(2026-11-09, 운영·SRE).

11-09 밤 여러 세션이 겹쳐 배포하면서, 이미 바뀐 활성 판 위에 만든 릴리스가 다른 세션의 작업을
되돌릴 뻔했다. 패키징 때 기준 판을 release.json에 남기고, deploy 때 활성 판과 다르면 거부한다."""
import json

import pytest

from scripts.service_deploy import Deployment
from tests.test_service_deploy import FakeDeployment


def _release(manager, name, base=None):
    path = manager.directory / 'releases' / name
    path.mkdir(parents=True, exist_ok=True)
    manifest = {'release': name, 'created': 0, 'sha256': {}}
    if base:
        manifest['base'] = base
    (path / 'release.json').write_text(json.dumps(manifest))


def test_web_deploy_refuses_a_release_built_on_a_replaced_active_release(tmp_path):
    manager = FakeDeployment(tmp_path)
    _release(manager, 'mine', base='older')
    with pytest.raises(ValueError, match='release_base_mismatch: mine was built on older but the active frontend release is old'):
        manager.deploy('frontend', 'mine')
    assert manager.state()['services']['frontend']['active'] == 'a'
    assert not any(call[0] == 'start' for call in manager.calls)


def test_matching_base_or_explicit_force_deploys(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.service_deploy.time.sleep', lambda _: None)
    manager = FakeDeployment(tmp_path)
    _release(manager, 'mine', base='old')
    manager.deploy('frontend', 'mine')
    assert manager.state()['services']['frontend']['slots']['b'] == 'mine'
    _release(manager, 'stale', base='somewhere-else')
    manager.deploy('admin', 'stale', force_base=True)
    assert manager.state()['services']['admin']['slots']['b'] == 'stale'


def test_releases_without_a_recorded_base_keep_working(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.service_deploy.time.sleep', lambda _: None)
    manager = FakeDeployment(tmp_path)
    _release(manager, 'legacy')
    manager.deploy('frontend', 'legacy')
    assert manager.state()['services']['frontend']['slots']['b'] == 'legacy'


def test_worker_deploy_checks_the_worker_release(tmp_path):
    manager = FakeDeployment(tmp_path)
    _release(manager, 'jobs-mine', base='jobs-before')
    with pytest.raises(ValueError, match='active jobs release is jobs-old'):
        manager.deploy_worker('jobs', 'jobs-mine')
    assert manager.state()['services']['jobs']['release'] == 'jobs-old'


def test_package_base_comes_from_argument_env_or_a_copied_release_tree(tmp_path, monkeypatch):
    manager = Deployment(tmp_path)
    monkeypatch.delenv('AGENTCON_RELEASE_BASE', raising=False)
    assert manager.package_base() is None
    (tmp_path / 'release.json').write_text(json.dumps({'release': 'growth-frontend-20261109-r3'}))
    assert manager.package_base() == 'growth-frontend-20261109-r3'
    monkeypatch.setenv('AGENTCON_RELEASE_BASE', 'model-watch-frontend-20261109-r1')
    assert manager.package_base() == 'model-watch-frontend-20261109-r1'
    assert manager.package_base('explicit-r1') == 'explicit-r1'
    with pytest.raises(ValueError, match='invalid_release_base'):
        manager.package_base('../escape')


def test_package_records_the_base(tmp_path, monkeypatch):
    root = tmp_path / 'tree'
    for name in ('agent_market', 'scripts', 'new', '.venv'):
        (root / name).mkdir(parents=True)
    (root / 'agent_market' / 'x.py').write_text('x = 1\n')
    (root / 'release.json').write_text(json.dumps({'release': 'base-frontend-r1'}))
    monkeypatch.delenv('AGENTCON_RELEASE_BASE', raising=False)
    manager = Deployment(root, state_dir=tmp_path / 'state')
    result = manager.package('mine-frontend-r1')
    assert result['base'] == 'base-frontend-r1'
    assert manager.release_base('mine-frontend-r1') == 'base-frontend-r1'
