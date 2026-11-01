"""Restore-aware capacity retains signed history and never replays old jobs."""
import pytest
from agent_market.reliability_controls_restore import authority_id
from agent_market.reliability_research import ReliabilityResearch
from agent_market.workspace_access import WorkspaceConflict
from tests.test_reliability_controls import controls, private_api, setup_plan, reserve, prepare, plan, post
from tests.test_reliability_evaluation_worker import worker_world
from tests.test_reliability_research import manifest


@pytest.mark.parametrize('old_state', ['prepared', 'dispatched'])
@pytest.mark.parametrize('quarantined', [True, False])
def test_prior_capacity_only_counts_current_live_unblocked_jobs(worker_world, monkeypatch, old_state, quarantined):
    w = worker_world
    monkeypatch.setattr('agent_market.reliability_research.clock', lambda: w.now)
    setup_plan(w)
    previous = reserve(w)['jobs'][0]
    assert prepare(w, previous['id']).status_code == 200
    with w.store.tx() as db:
        value = w.evaluation._job(db, w.ws['id'], previous['id'])
        value.update(state=old_state, dispatched_at=w.now if old_state == 'dispatched' else None)
        w.evaluation._put(db, 'job', value)
        original = dict(db.execute('SELECT * FROM reliability_eval_jobs WHERE id=?', (previous['id'],)).fetchone())
        if quarantined:
            db.execute('INSERT INTO reliability_controls_restore_blocks VALUES(?)',
                       (authority_id('eval_job', previous['id']),))
    research = ReliabilityResearch(w.access, w.evaluation)
    approved = research.register_manifest(w.ws['id'], manifest(w), w.actor)
    response = post(w, '/evaluation/plans', plan(w, revision=1,
        corpus_id=approved['corpus_id'], per_host_budget=10))
    assert response.status_code == 200, response.text
    w.worker.max_jobs_per_tick = 8
    w.worker.activate(w.ws['id'], w.actor, 2)
    first = w.worker.tick()
    if quarantined:
        assert first['attempted_jobs'] == 4
        assert w.worker.tick()['attempted_jobs'] == 0
    else:
        # A fresh unblocked prepared/dispatched evaluation still owns the host,
        # even after a different plan was approved. Capacity is not bypassed.
        assert first['attempted_jobs'] == 0 and not w.eval_calls
        w.now = previous['expires']+1
        assert w.worker.tick()['attempted_jobs'] == 4
        assert w.worker.tick()['attempted_jobs'] == 0
    assert w.eval_calls.count('tools/call') == 4
    with w.store.tx() as db:
        raw = dict(db.execute('SELECT * FROM reliability_eval_jobs WHERE id=?', (previous['id'],)).fetchone())
        if quarantined:
            # Ignoring capacity never rewrites the original signed payload.
            assert raw == original and raw['state'] == old_state
        else:
            assert raw['state'] == ('unknown' if old_state == 'dispatched' else 'expired')
    result = research.analyze(w.ws['id'], approved['id'], w.actor)
    assert result['scheduled_episodes'] == 4 and result['paired']['both_failed'] == 2
    with pytest.raises(WorkspaceConflict):
        w.evaluation.dispatch(w.ws['id'], previous['id'],
            {'authorized': True, 'notice': 'approved-read-evaluation-corpus-v1'}, w.actor)
    assert w.eval_calls.count('tools/call') == 4


@pytest.mark.parametrize('old_state', ['prepared', 'dispatched'])
def test_prepare_uses_same_live_and_restore_aware_capacity_predicate(worker_world, monkeypatch, old_state):
    w = worker_world
    # Admit two current-plan episodes first, then make the first one active.
    from tests.test_reliability_controls import corpus
    body = corpus(w)
    body['cases'].append(body['cases'][0] | {'case_id': 'holdout-2'})
    assert post(w, '/evaluation/corpora', body).status_code == 200
    assert post(w, '/evaluation/plans', plan(w, per_host_budget=2)).status_code == 200
    assert post(w, '/evaluation/control', {'revision': 0, 'enabled': True, 'authorized': True,
        'notice': 'approved-read-evaluation-corpus-v1'}).status_code == 200
    jobs = reserve(w)['jobs']; assert len(jobs) == 2
    assert prepare(w, jobs[0]['id']).status_code == 200
    with w.store.tx() as db:
        value = w.evaluation._job(db, w.ws['id'], jobs[0]['id'])
        value.update(state=old_state, dispatched_at=w.now if old_state == 'dispatched' else None)
        w.evaluation._put(db, 'job', value)
        original = dict(db.execute('SELECT * FROM reliability_eval_jobs WHERE id=?', (jobs[0]['id'],)).fetchone())
    assert prepare(w, jobs[1]['id']).status_code == 409
    with w.store.tx() as db:
        db.execute('INSERT INTO reliability_controls_restore_blocks VALUES(?)',
                   (authority_id('eval_job', jobs[0]['id']),))
    assert prepare(w, jobs[1]['id']).status_code == 200
    with w.store.tx() as db:
        assert dict(db.execute('SELECT * FROM reliability_eval_jobs WHERE id=?', (jobs[0]['id'],)).fetchone()) == original
    assert not w.eval_calls
