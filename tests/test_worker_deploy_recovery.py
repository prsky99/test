"""Worker recovery uses isolated state and fake processes, never live services."""
import fcntl
import plistlib

import pytest

from scripts.service_deploy import Deployment
from tests.test_service_deploy import FakeDeployment


class WorkerDeployment(FakeDeployment):
    def __init__(self, root):
        super().__init__(root)
        self.fail_stop = False
        self.fail_releases = set()
        self.owner_busy = False
        self.old_alive = False

    def stop(self, role, slot):
        if self.fail_stop:
            raise RuntimeError('service_stop_timeout')
        super().stop(role, slot)

    def worker_owner_free(self, role):
        if self.owner_busy:
            raise RuntimeError('worker_owner_still_busy')

    def worker_release(self, role):
        return self.processes[(role, 'main')]

    def process_alive(self, pid):
        return self.old_alive

    def wait_worker(self, role):
        if self.processes[(role, 'main')] in self.fail_releases:
            raise RuntimeError('worker_startup_timeout')


def interrupted(manager, journal=False):
    state = manager.state()
    if journal:
        state['pending_worker'] = {'role': 'jobs', 'release': 'new',
                                   'from_release': 'jobs-old', 'old_pid': None}
    manager.save(state, 'worker_draining')
    manager.processes.pop(('jobs', 'main'), None)


def test_successful_worker_deploy_journals_then_commits(tmp_path):
    manager = WorkerDeployment(tmp_path)
    before = manager.state()['services']['frontend']
    original_stop = manager.stop
    def stop(role, slot):
        pending = manager.state()['pending_worker']
        assert pending == {'role': 'jobs', 'release': 'new',
                           'from_release': 'jobs-old', 'old_pid': 123}
        original_stop(role, slot)
    manager.stop = stop
    manager.deploy_worker('jobs', 'new')
    state = manager.state()
    assert state['phase'] == 'stable' and 'pending_worker' not in state
    assert state['services']['jobs']['release'] == 'new'
    assert state['services']['frontend'] == before


def test_stop_failure_retains_recoverable_journal(tmp_path):
    manager = WorkerDeployment(tmp_path)
    manager.fail_stop = True
    with pytest.raises(RuntimeError, match='service_stop_timeout'):
        manager.deploy_worker('jobs', 'new')
    assert manager.state()['phase'] == 'worker_draining'
    assert manager.state()['pending_worker']['old_pid'] == 123
    assert not manager.calls


def test_candidate_failure_rolls_back_then_restores_stable(tmp_path):
    manager = WorkerDeployment(tmp_path)
    manager.fail_releases = {'new'}
    with pytest.raises(RuntimeError, match='worker_startup_timeout'):
        manager.deploy_worker('jobs', 'new')
    assert manager.processes[('jobs', 'main')] == 'jobs-old'
    assert manager.state()['phase'] == 'stable'
    assert 'pending_worker' not in manager.state()


def test_failed_rollback_preserves_recovery_journal(tmp_path):
    manager = WorkerDeployment(tmp_path)
    manager.fail_releases = {'new', 'jobs-old'}
    with pytest.raises(RuntimeError, match='worker_startup_timeout'):
        manager.deploy_worker('jobs', 'new')
    assert manager.state()['phase'] == 'worker_recovery_required'
    assert manager.state()['pending_worker']['release'] == 'new'


def test_legacy_recovery_requires_explicit_target(tmp_path):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager)
    before = manager.state()
    with pytest.raises(ValueError, match='legacy_worker_recovery_requires_role_and_release'):
        manager.recover()
    assert manager.state() == before and not manager.calls


@pytest.mark.parametrize('journal', [False, True])
def test_recovery_starts_only_requested_worker(tmp_path, journal):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager, journal)
    web = {role: manager.state()['services'][role] for role in ('frontend', 'admin')}
    result = manager.recover('jobs', 'new')
    assert result['phase'] == 'stable'
    assert manager.processes[('jobs', 'main')] == 'new'
    assert {role: manager.state()['services'][role] for role in web} == web
    assert [call for call in manager.calls if call[0] == 'start'] == [('start', 'jobs', 'main')]
    assert 'pending_worker' not in manager.state()


def test_busy_owner_refuses_recovery_without_starting(tmp_path):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager, True)
    manager.owner_busy = True
    with pytest.raises(RuntimeError, match='worker_owner_still_busy'):
        manager.recover()
    assert not any(call[0] == 'start' for call in manager.calls)
    assert manager.state()['phase'] == 'worker_draining'


def test_recovery_refuses_still_alive_previous_pid(tmp_path):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager, True)
    state = manager.state()
    state['pending_worker']['old_pid'] = 123
    manager.save(state, state['phase'])
    manager.old_alive = True
    with pytest.raises(RuntimeError, match='worker_previous_process_still_alive'):
        manager.recover()
    assert not manager.calls


def test_recovery_reconciles_running_target_without_restart(tmp_path):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager, True)
    manager.processes[('jobs', 'main')] = 'new'
    manager.recover()
    assert manager.state()['phase'] == 'stable'
    assert not any(call[0] in ('start', 'stop') for call in manager.calls)


def test_recovery_candidate_failure_retains_journal_for_retry(tmp_path):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager, True)
    manager.fail_releases = {'new'}
    with pytest.raises(RuntimeError, match='worker_startup_timeout'):
        manager.recover()
    assert manager.state()['phase'] == 'worker_recovery_required'
    manager.fail_releases.clear()
    manager.recover()
    assert manager.state()['phase'] == 'stable'
    assert len([call for call in manager.calls if call[0] == 'start']) == 1


@pytest.mark.parametrize('role,release', [('execution', 'new'), ('jobs', 'other')])
def test_journal_mismatch_refuses_mutation(tmp_path, role, release):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager, True)
    before = manager.state()
    with pytest.raises(ValueError, match='worker_recovery_target_mismatch'):
        manager.recover(role, release)
    assert manager.state() == before and not manager.calls


def test_running_unexpected_release_is_not_restarted(tmp_path):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager, True)
    manager.processes[('jobs', 'main')] = 'jobs-old'
    with pytest.raises(RuntimeError, match='worker_release_unconfirmed'):
        manager.recover()
    assert not manager.calls


def test_explicit_worker_recovery_refuses_stable_phase(tmp_path):
    manager = WorkerDeployment(tmp_path)
    with pytest.raises(ValueError, match='no_interrupted_worker_deployment'):
        manager.recover('jobs', 'new')
    assert not manager.calls


def test_pending_web_transition_blocks_worker_recovery(tmp_path):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager, True)
    state = manager.state()
    state['pending'] = {'role': 'frontend'}
    manager.save(state, state['phase'])
    before = manager.state()
    with pytest.raises(ValueError, match='no_interrupted_worker_deployment'):
        manager.recover()
    assert manager.state() == before and not manager.calls


def test_invalid_legacy_release_refuses_before_journaling(tmp_path):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager)
    before = manager.state()
    with pytest.raises(ValueError, match='invalid_worker_recovery_target'):
        manager.recover('jobs', '../escape')
    assert manager.state() == before and not manager.calls


def test_immutable_release_verification_runs_before_recovery_mutation(tmp_path):
    manager = WorkerDeployment(tmp_path)
    interrupted(manager)
    before = manager.state()
    def reject(release):
        raise ValueError('release_hash_mismatch')
    manager.verify_release = reject
    with pytest.raises(ValueError, match='release_hash_mismatch'):
        manager.recover('jobs', 'new')
    assert manager.state() == before and not manager.calls


def test_real_isolated_owner_lock_and_symlink_boundary(tmp_path):
    manager = Deployment(tmp_path)
    path = manager.directory / 'jobs.owner.lock'
    path.touch()
    with path.open() as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match='worker_owner_still_busy'):
            manager.worker_owner_free('jobs')
    manager.worker_owner_free('jobs')
    path.unlink()
    path.symlink_to(tmp_path / 'other')
    with pytest.raises(OSError):
        manager.worker_owner_free('jobs')


@pytest.mark.parametrize('args', [
    ['python', '--role', 'jobs', '--release', 'new'],
    ['python', '--role', 'execution', '--release', 'new'],
    ['python', '--role', 'jobs', '--release', '../escape'],
    ['python', '--role', 'jobs', '--release'],
    {'--role': 'jobs'},
])
def test_launch_plist_release_validation(tmp_path, args):
    manager = Deployment(tmp_path)
    path = manager.directory / (manager.label('jobs', 'main') + '.plist')
    path.write_bytes(plistlib.dumps({'ProgramArguments': args}))
    if isinstance(args, list) and args[-1] == 'new' and 'execution' not in args:
        assert manager.worker_release('jobs') == 'new'
    else:
        with pytest.raises(ValueError, match='worker_release_unconfirmed'):
            manager.worker_release('jobs')
