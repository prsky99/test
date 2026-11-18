"""Deploy rules in the deploy tool itself (precision review R54, 11-15)."""
import json
import sys
import time
from types import SimpleNamespace

import pytest

from scripts import service_deploy as sd


class Manager:
    def __init__(self, tmp_path, state):
        self.directory = tmp_path
        self._state = state

    def state(self):
        return self._state

    def path(self, release):
        return self.directory / 'releases' / release


def _sql(tmp_path, release, names):
    folder = tmp_path / 'releases' / release / 'agent_market'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'application_store_sql.json').write_text(json.dumps(
        {'statements': [{'name': n, 'sqlite': 'S ' + n, 'postgres': 'P ' + n} for n in names]}))


STATE = {'services': {'frontend': {'active': 'a', 'slots': {'a': 'fe-r1', 'b': 'fe-r0'}},
                      'jobs': {'release': 'jobs-r1', 'previous_release': 'jobs-r0'},
                      'admin': {'active': 'b', 'slots': {'a': 'ad-r0', 'b': {'release': 'ad-r1'}}}}}


def test_policy_hash_changes_only_at_night(tmp_path):
    manager = Manager(tmp_path, STATE)
    hashes = {'fe-r1': 'aaaa', 'fe-r2': 'bbbb', 'fe-same': 'aaaa', 'ad-r1': 'x', 'ad-r2': 'y'}
    hasher = lambda m, release: hashes.get(release)
    noon = time.mktime((2026, 11, 15, 12, 0, 0, 0, 0, -1))
    night = time.mktime((2026, 11, 16, 0, 45, 0, 0, 0, -1))
    assert sd.check_policy_hash(manager, 'frontend', 'fe-same', noon, hasher)['changed'] is False
    with pytest.raises(SystemExit, match='policy_hash_changes_outside_night'):
        sd.check_policy_hash(manager, 'frontend', 'fe-r2', noon, hasher)
    assert sd.check_policy_hash(manager, 'frontend', 'fe-r2', night, hasher)['changed'] is True
    assert sd.check_policy_hash(manager, 'admin', 'ad-r2', noon, hasher) is None       # not a policy role
    with pytest.raises(SystemExit, match='policy_hash_unreadable'):
        sd.check_policy_hash(manager, 'frontend', 'fe-missing', night, hasher)


def test_a_release_that_loses_a_registered_statement_is_refused(tmp_path):
    manager = Manager(tmp_path, STATE)
    _sql(tmp_path, 'jobs-r1', ['a', 'b'])
    _sql(tmp_path, 'jobs-r2', ['a', 'b', 'c'])
    _sql(tmp_path, 'jobs-r3', ['a'])
    assert sd.check_sql_list(manager, 'jobs', 'jobs-r2') == {'compared': True, 'added': ['c']}
    with pytest.raises(SystemExit, match='sql_statements_removed: 1, e.g. b'):
        sd.check_sql_list(manager, 'jobs', 'jobs-r3')
    assert sd.check_sql_list(manager, 'jobs', 'jobs-none') == {'compared': False}


def test_a_recent_pass_of_the_same_commit_is_reused(tmp_path):
    (tmp_path / '.venv-tests/bin').mkdir(parents=True)
    (tmp_path / '.venv-tests/bin/python').write_text('')
    calls = []
    passing = lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0)
    assert 'ran' in sd.release_gate(tmp_path, 'r1', passing, now=1000.0, commit='c1')
    assert sd.release_gate(tmp_path, 'r1', passing, now=1000.0 + 3600, commit='c1') == {'reused': 1000.0}
    assert 'ran' in sd.release_gate(tmp_path, 'r1', passing, now=1000.0 + 3600, commit='c2')   # another commit
    assert 'ran' in sd.release_gate(tmp_path, 'r1', passing, now=1000.0 + 90000, commit='c2')  # older than 24 h
    assert len(calls) == 3
    with pytest.raises(SystemExit, match='release_gate_failed'):
        sd.release_gate(tmp_path, 'r2', lambda *a, **k: SimpleNamespace(returncode=1), now=1.0, commit='c')
    assert not (tmp_path / sd.GATE_RECORDS / 'r2.json').exists()


def test_emergency_options_are_written_down(tmp_path):
    sd.log_override(tmp_path, '운영·SRE', 'deploy frontend', 'fe-r2', ['--skip-gate', '--force-base'])
    sd.log_override(tmp_path, '운영·SRE', 'deploy frontend', 'fe-r3', [])
    lines = (tmp_path / sd.OVERRIDES).read_text().splitlines()
    assert len(lines) == 1 and lines[0].endswith('운영·SRE deploy frontend fe-r2 --skip-gate --force-base')


def test_worker_rollback_runs_the_previous_release(tmp_path):
    calls = []
    manager = SimpleNamespace(state=lambda: STATE,
                              deploy_worker=lambda role, release, force_base=False: calls.append((role, release, force_base)))
    sd.Deployment.rollback_worker(manager, 'jobs')
    assert calls == [('jobs', 'jobs-r0', True)]
    with pytest.raises(ValueError):
        sd.Deployment.rollback_worker(manager, 'frontend')


def _main(monkeypatch, tmp_path, argv):
    monkeypatch.setattr(sys, 'argv', ['service_deploy', '--root', str(tmp_path), *argv])
    sd.main()


def test_worker_deploy_checks_in_order_and_records_them(tmp_path, monkeypatch, capsys):
    order = []
    monkeypatch.setattr(sd, 'check_board_lock', lambda *a, **k: order.append('lock'))
    monkeypatch.setattr(sd.Deployment, 'check_base', lambda self, role, release, *a: order.append('base'))
    monkeypatch.setattr(sd, 'check_policy_hash', lambda m, role, release, **k: order.append('policy') or {'changed': False})
    monkeypatch.setattr(sd, 'check_sql_list', lambda m, role, release: order.append('sql') or {'compared': True})
    monkeypatch.setattr(sd, 'release_gate', lambda root, release, commit=None: order.append('gate') or {'ran': 1})
    monkeypatch.setattr(sd.Deployment, 'release_commit', lambda self, release: 'c1')
    monkeypatch.setattr(sd.Deployment, 'deploy_worker', lambda self, role, release, **k: order.append('deploy') or {})
    _main(monkeypatch, tmp_path, ['worker-deploy', 'jobs', 'jobs-r2', '--lock-owner', '운영·SRE', '--no-prune'])
    assert order == ['lock', 'base', 'policy', 'sql', 'gate', 'deploy']
    assert json.loads(capsys.readouterr().out)['checks'] == {'policy_hash': {'changed': False},
                                                             'sql_list': {'compared': True}, 'gate': {'ran': 1}}


def test_commit_packages_need_a_base(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match='package_base_required'):
        _main(monkeypatch, tmp_path, ['package', 'r1', '--commit', 'HEAD'])


@pytest.mark.parametrize('argv', [['rollback', 'frontend'], ['worker-rollback', 'jobs'], ['restart'], ['stop']])
def test_rollback_restart_and_stop_need_a_lock_owner(tmp_path, monkeypatch, argv):
    with pytest.raises(SystemExit):
        _main(monkeypatch, tmp_path, argv)   # argparse: --lock-owner is required
    seen = []
    monkeypatch.setattr(sd, 'check_board_lock', lambda root, owner, *a: seen.append(owner) or (_ for _ in ()).throw(
        RuntimeError('deploy_lock_not_taken')))
    with pytest.raises(RuntimeError, match='deploy_lock_not_taken'):
        _main(monkeypatch, tmp_path, argv + ['--lock-owner', '운영·SRE'])
    assert seen == ['운영·SRE']


def test_a_full_gate_pass_from_the_runner_is_reused_by_the_deploy(tmp_path, monkeypatch):
    from scripts import release_gate as gate
    releases = tmp_path / 'gateway-data/services/releases'
    monkeypatch.setattr(gate, 'RELEASES', releases)
    (releases / 'fe-r2').mkdir(parents=True)
    (releases / 'fe-r2/release.json').write_text(json.dumps({'commit': 'c9'}))
    gate.record_pass('fe-r2', now=5000.0)
    never = lambda *a, **k: (_ for _ in ()).throw(AssertionError('ran the tests again'))
    assert sd.release_gate(tmp_path, 'fe-r2', never, now=5000.0 + 600, commit='c9') == {'reused': 5000.0}
    assert gate.record_pass('missing-release') is None


def test_a_packaged_release_protects_itself_until_deployed_or_48_hours(tmp_path):
    """R60 (11-15): 11-12 the post-deploy prune removed releases still waiting for their turn."""
    (tmp_path / 'pinned-releases.txt').write_text('align-admin-20261113-r2\nday15-fe  # adcoin-worker daemon\n')
    sd.pin_packaged(tmp_path, 'fe-r5', now=1000)
    sd.pin_packaged(tmp_path, 'jobs-r3', now=2000)
    sd.pin_packaged(tmp_path, 'fe-r5', now=3000)                       # packaged again: one line, new time
    lines = (tmp_path / 'pinned-releases.txt').read_text().splitlines()
    assert lines[:2] == ['align-admin-20261113-r2', 'day15-fe  # adcoin-worker daemon']
    assert [l.split()[0] for l in lines if sd.PACKAGED_TAG in l] == ['jobs-r3', 'fe-r5']
    manager = SimpleNamespace(directory=tmp_path, root=tmp_path)
    assert sd.Deployment.waiting_releases(manager, {'fe-r5', 'jobs-r3', 'x'}) == {'fe-r5', 'jobs-r3'}
    sd.unpin_packaged(tmp_path, 'fe-r5', now=3100)                     # deployed
    assert [l.split()[0] for l in (tmp_path / 'pinned-releases.txt').read_text().splitlines()
            if sd.PACKAGED_TAG in l] == ['jobs-r3']
    sd.unpin_packaged(tmp_path, now=2000 + 49 * 3600)                    # older than 48 h: expires
    assert (tmp_path / 'pinned-releases.txt').read_text().splitlines() == lines[:2]


def test_allow_policy_hash_day_lets_one_change_through_and_is_recorded(tmp_path):
    """PM 11-18: --allow-policy-hash-day REASON passes a day change of the policy hash; a short reason, no change and
    non-policy roles are unaffected; the exception is written to its own jsonl and to the overrides list."""
    manager = Manager(tmp_path, STATE)
    hashes = {'fe-r1': 'aaaa', 'fe-r2': 'bbbb', 'fe-same': 'aaaa', 'ad-r1': 'x', 'ad-r2': 'y'}
    hasher = lambda m, release: hashes.get(release)
    noon = time.mktime((2026, 11, 15, 12, 0, 0, 0, 0, -1))
    reason = 'user asked for the deploy now; 21:10 is 07:10 in the US east'
    with pytest.raises(SystemExit, match='policy_hash_day_reason_too_short'):
        sd.check_policy_hash(manager, 'frontend', 'fe-r2', noon, hasher, allow_day='now')
    check = sd.check_policy_hash(manager, 'frontend', 'fe-r2', noon, hasher, allow_day=reason)
    assert check['changed'] is True and check['day_exception'] == reason
    same = sd.check_policy_hash(manager, 'frontend', 'fe-same', noon, hasher, allow_day=reason)
    assert same['changed'] is False and 'day_exception' not in same          # nothing to excuse, nothing recorded
    assert sd.check_policy_hash(manager, 'admin', 'ad-r2', noon, hasher, allow_day=reason) is None
    sd.log_policy_day_exception(tmp_path, 'ops', 'deploy', 'frontend', 'fe-r2', check)
    sd.log_override(tmp_path, 'ops', 'deploy frontend', 'fe-r2', ['--allow-policy-hash-day'])
    row = json.loads((tmp_path / 'logs/ops/policy-hash-day-exceptions.jsonl').read_text().splitlines()[0])
    assert row['release'] == 'fe-r2' and row['from'] == 'aaaa' and row['to'] == 'bbbb' and row['reason'] == reason
    assert '--allow-policy-hash-day' in (tmp_path / sd.OVERRIDES).read_text()


def test_worker_deploy_with_the_day_exception_records_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sd, 'check_board_lock', lambda *a, **k: None)
    monkeypatch.setattr(sd.Deployment, 'check_base', lambda self, role, release, *a: None)
    seen = {}
    def policy(m, role, release, **k):
        seen.update(k)
        return {'active': 'aaaa', 'release': 'bbbb', 'changed': True, 'day_exception': k.get('allow_day')}
    monkeypatch.setattr(sd, 'check_policy_hash', policy)
    monkeypatch.setattr(sd, 'check_sql_list', lambda m, role, release: {'compared': True})
    monkeypatch.setattr(sd, 'release_gate', lambda root, release, commit=None: {'ran': 1})
    monkeypatch.setattr(sd.Deployment, 'release_commit', lambda self, release: 'c1')
    monkeypatch.setattr(sd.Deployment, 'deploy_worker', lambda self, role, release, **k: {})
    reason = 'the day deploy is the user instruction; the regeneration counts once'
    _main(monkeypatch, tmp_path, ['worker-deploy', 'jobs', 'jobs-r2', '--lock-owner', '운영·SRE', '--no-prune',
                                  '--allow-policy-hash-day', reason])
    assert seen == {'allow_day': reason}
    row = json.loads((tmp_path / 'logs/ops/policy-hash-day-exceptions.jsonl').read_text().splitlines()[0])
    assert row['release'] == 'jobs-r2' and row['role'] == 'jobs' and row['reason'] == reason and row['owner'] == '운영·SRE'
    assert '--allow-policy-hash-day' in (tmp_path / sd.OVERRIDES).read_text()
