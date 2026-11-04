"""Old releases are pruned without touching anything state.json, a process or a recent deploy still needs (11-04)."""
import json
import time

import pytest

from scripts.service_deploy import Deployment

DAY = 86400


class Prune(Deployment):
    running = set()

    def running_releases(self):
        return set(self.running)


@pytest.fixture
def deployment(tmp_path):
    manager = Prune(tmp_path, state_dir=tmp_path / 'services')
    now = time.time()
    for age, name in enumerate(['r%02d' % index for index in range(20)]):
        path = manager.directory / 'releases' / name
        (path / '.venv').mkdir(parents=True)
        (path / 'release.json').write_text(json.dumps({'release': name, 'created': now - (20 - age) * DAY}))
    manager.save({'version': 1, 'managed': True, 'services': {
        'frontend': {'active': 'a', 'slots': {'a': 'r00', 'b': 'r01'}, 'previous': 'a'},
        'jobs': {'release': 'r02', 'previous_release': 'r03'}},
        'pending': {'role': 'admin', 'release': 'r04'}}, 'retained')
    manager.running = {'r05'}
    return manager, now


def names(manager):
    return sorted(path.name for path in (manager.directory / 'releases').iterdir())


def test_dry_run_lists_only_unprotected_old_releases_and_deletes_nothing(deployment):
    manager, now = deployment
    result = manager.prune_releases(keep=5, min_age_days=8, now=now)
    # r00-r04 are named in state.json, r05 is running, r15-r19 are the newest five, r13-r14 are under 8 days old.
    assert result['protected'] == ['r00', 'r01', 'r02', 'r03', 'r04', 'r05']
    assert result['to_remove'] == 7 and result['oldest_removed'] == ['r06', 'r07', 'r08']
    assert result['newest_removed'] == ['r10', 'r11', 'r12'] and result['applied'] is False
    assert len(names(manager)) == 20


def test_apply_removes_exactly_the_listed_releases(deployment):
    manager, now = deployment
    result = manager.prune_releases(keep=5, min_age_days=8, apply=True, now=now)
    assert result['removed'] == 7
    assert names(manager) == ['r%02d' % index for index in (0, 1, 2, 3, 4, 5, 13, 14, 15, 16, 17, 18, 19)]


def test_apply_finishes_trees_an_interrupted_run_left_and_ignores_other_entries(deployment):
    manager, now = deployment
    releases = manager.directory / 'releases'
    (releases / '.pruning-old').mkdir()
    (releases / 'notes.txt').write_text('not a release')
    (releases / 'outside').symlink_to(manager.directory)
    manager.prune_releases(keep=20, min_age_days=0, apply=True, now=now)
    assert not (releases / '.pruning-old').exists()
    assert (releases / 'notes.txt').exists() and (releases / 'outside').is_symlink()
    assert len([name for name in names(manager) if name.startswith('r')]) == 20


def test_prune_waits_for_no_deploy_holding_the_lock(deployment):
    manager, now = deployment
    with manager.lock():
        with pytest.raises(BlockingIOError):
            manager.prune_releases(apply=True, now=now)
    assert len(names(manager)) == 20


def test_running_releases_reads_paths_under_this_release_directory(tmp_path, monkeypatch):
    manager = Deployment(tmp_path, state_dir=tmp_path / 'services')
    base = str(manager.directory / 'releases')
    listing = '\n'.join([base + '/live-r1/.venv/bin/python -m agent_market.service_host',
                         '/bin/zsh -c cd ' + base + '/gate-r2 && pytest', '/usr/bin/other /tmp/releases/x/y'])
    monkeypatch.setattr('scripts.service_deploy.subprocess.run',
                        lambda *a, **k: type('R', (), {'stdout': listing})())
    assert manager.running_releases() == {'live-r1', 'gate-r2'}
