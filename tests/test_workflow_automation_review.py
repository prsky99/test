"""Independent checks of atomic automation admission and dispatch certainty."""
import json
import os
from pathlib import Path

import pytest

from agent_market.workflow_connection_automation import GRANT_NOTICE, SHARE_NOTICE, EVENT_NOTICE
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_publication import publication, published
from tests.test_workflow_runtime import wait


@pytest.fixture
def automated(publication):
    rt, owner, routed = publication
    release, tested, *_ = published(rt, owner)
    prepared = rt.automation.prepare(release['id'], {'trigger': 'event', 'interval_seconds': 0,
                                                  'max_runs': 2, 'ttl_seconds': 1800}, owner)
    body = {key: prepared[key] for key in ('proposal', 'signature')} | {
        'sharing_authority': True, 'sharing_notice': SHARE_NOTICE,
        'trigger_authority': True, 'trigger_notice': GRANT_NOTICE}
    grant = rt.automation.issue(release['id'], body, owner)['grant']
    routed[3].clear()
    rt.typed_test_controls['seen'].clear()
    return rt, owner, routed, release, tested, grant


def event(rt, owner, release, grant, event_id='e' * 32):
    return rt.automation.trigger(release['id'], grant['id'],
                                 {'event_id': event_id, 'authority': True, 'notice': EVENT_NOTICE}, owner)


def test_failed_authority_write_rolls_back_run_receipt_and_quota_together(automated, monkeypatch):
    rt, owner, routed, release, _, grant = automated
    before = rt.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]
    original = rt.authority.save_run

    def fail_after_admission(*args, **kwargs):
        raise ValueError('Isolated authority write failure')

    monkeypatch.setattr(rt.authority, 'save_run', fail_after_admission)
    with pytest.raises(ValueError):
        event(rt, owner, release, grant)
    assert rt.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0] == before
    assert not rt.store.query('SELECT 1 FROM workflow_connection_automation_admissions WHERE grant_id=?', (grant['id'],))
    assert rt.store.query('SELECT used FROM workflow_connection_automation WHERE id=?', (grant['id'],))[0][0] == 0
    assert not routed[3]
    monkeypatch.setattr(rt.authority, 'save_run', original)
    job = event(rt, owner, release, grant)
    assert wait(rt, job)['status'] == 'succeeded' and len(routed[3]) == 2


@pytest.mark.parametrize('column', ['actor', 'idempotency_key'])
def test_queued_run_cannot_rebind_signed_automation_identity(automated, monkeypatch, column):
    rt, owner, routed, release, _, grant = automated
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    job = event(rt, owner, release, grant)
    with rt.store.tx() as db:
        if column == 'actor':
            db.execute("UPDATE workflow_runs SET actor='automation:another' WHERE id=?", (job['run_id'],))
        else:
            db.execute("UPDATE workflow_runs SET idempotency_key='event:another' WHERE id=?", (job['run_id'],))
    rt._execute(job['run_id'])
    assert rt.get(job['run_id'])['status'] == 'failed' and not routed[3]


def test_revocation_between_verified_news_and_docs_blocks_the_second_dispatch(automated, monkeypatch):
    rt, owner, routed, release, _, grant = automated
    original = rt.persistence.prepare
    revoked = []

    def revoke_after_docs_prepared(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[3] == 'search-2' and not revoked:
            revoked.append(rt.automation.revoke(release['id'], grant['id'], grant['revision'], owner))
        return result

    monkeypatch.setattr(rt.persistence, 'prepare', revoke_after_docs_prepared)
    job = event(rt, owner, release, grant)
    result = wait(rt, job)
    assert result['status'] != 'succeeded' and revoked
    assert routed[3] == ['primary.example']
    assert not rt.store.query("SELECT 1 FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-2' AND status='dispatched'", (job['run_id'],))


def test_unknown_event_keeps_its_receipt_and_blocks_different_event_without_retry(automated):
    rt, owner, routed, release, _, grant = automated
    workflow = rt.publication.metadata(release['id'])['workflow']
    target = rt.store.resource(workflow['nodes'][2]['resource_id'])['url'].split('/')[2]
    routed[4][target] = 'unknown'
    job = event(rt, owner, release, grant)
    assert wait(rt, job)['execution_outcome'] == 'unknown' and len(routed[3]) == 2
    replay = event(rt, owner, release, grant)
    assert replay['run_id'] == job['run_id'] and replay['replayed']
    with pytest.raises(ValueError):
        event(rt, owner, release, grant, 'f' * 32)
    assert len(routed[3]) == 2
    history = rt.automation.history(release['id'], owner)
    assert len(history['runs']) == 1 and history['runs'][0]['outcome'] == 'unknown'
    assert history['grants'][0]['used'] == 1


def test_same_title_but_changed_source_provenance_prevents_automation_docs_call(automated, monkeypatch):
    rt, owner, routed, release, _, grant = automated
    original = rt.persistence.prepare
    changed = []

    def change_after_preparation(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[3] == 'search-2' and not changed:
            changed.append(True)
            with rt.store.tx() as db:
                record = db.execute("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id='search-1'", (args[0],)).fetchone()
                payload = json.loads(record[0])
                for output in (payload['record']['data'], payload['flow_output']):
                    output.get('structuredContent', output)['items'][0]['summary'] = 'Changed provenance for the same title'
                db.execute("UPDATE workflow_checkpoints SET payload=?,signature=? WHERE run_id=? AND node_id='search-1'",
                           (json.dumps(payload), rt.authority.signature(payload), args[0]))
        return result

    monkeypatch.setattr(rt.persistence, 'prepare', change_after_preparation)
    job = event(rt, owner, release, grant)
    assert wait(rt, job)['status'] == 'failed' and changed
    assert routed[3] == ['primary.example']


def test_scheduler_cursor_progresses_beyond_a_full_batch_of_invalid_grants(publication, monkeypatch):
    import time
    from tests.test_workflow_connection_automation import issue
    rt, owner, routed = publication
    release, *_ = published(rt, owner)
    grant, _ = issue(rt, owner, release, trigger='scheduled')
    original = dict(rt.store.query('SELECT * FROM workflow_connection_automation WHERE id=?', (grant['id'],))[0])
    with rt.store.tx() as db:
        for index in range(33):
            row = {**original, 'id': 'aut_' + format(index, '032x'),
                   'proposal_nonce': format(index, '032x'), 'signature': 'invalid',
                   'next_run': original['next_run'] - 100}
            db.execute('INSERT INTO workflow_connection_automation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', tuple(row.values()))
    real = time.time
    advance = original['next_run'] + 1 - real()
    monkeypatch.setattr('agent_market.workflow_connection_automation.time.time', lambda: real() + advance)
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    routed[3].clear()
    assert rt.automation.run_due()['checked'] == 0
    assert rt.automation.run_due()['checked'] == 1
    receipts = rt.store.query('SELECT grant_id FROM workflow_connection_automation_admissions')
    assert len(receipts) == 1 and receipts[0][0] == grant['id'] and not routed[3]


def test_populated_automation_state_round_trips_through_postgres(automated, monkeypatch):
    from scripts.rehearse_workflow_postgres import rehearse,TABLES
    rt, owner, _, release, _, grant = automated
    job = event(rt, owner, release, grant)
    assert wait(rt, job)['status'] == 'succeeded'
    monkeypatch.setenv('PATH', '/opt/homebrew/opt/postgresql@14/bin:' + os.environ.get('PATH', ''))
    result = rehearse(rt.store._path)
    assert result['round_trip_equal'] and set(result['tables']) == set(TABLES)
    assert result['tables']['workflow_connection_automation'] == 1
    assert result['tables']['workflow_connection_automation_admissions'] == 1
    Path('reports/advancement-automation-batch-2026-10-18/postgres-automation.json').write_text(json.dumps(result, indent=2) + '\n')
