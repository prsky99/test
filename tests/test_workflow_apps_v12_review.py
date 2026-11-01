"""Independent deployment-authority races use isolated catalog and provider data."""
import json
import os
from pathlib import Path
import sqlite3

import pytest

from agent_market.capability_registry import Registry
from agent_market.execution_authority import set_controls, controls
from tests.test_workflow_fallback import routing
from tests.test_workflow_apps_v12 import (
    ORIGIN, v12_runtime, export_request, exported, ticket, run_request,
)
from tests.test_workflow_runtime import wait


def test_nested_registry_write_cannot_leave_an_active_ungranted_app(v12_runtime, monkeypatch):
    rt, wf, service, calls = v12_runtime
    request = export_request(service, wf)
    resource = rt.store.resource(wf['nodes'][1]['resource_id'])

    def metadata_then_fail(*args, **kwargs):
        # Registry.current legitimately uses Store.tx when a current version is
        # absent. Its nested commit must not publish a partially registered app.
        changed = {**resource, 'usage_full_tools': []}
        Registry(rt.store).current(changed)
        raise ValueError('Synthetic grant validation failure after catalog metadata refresh')

    monkeypatch.setattr(service.consent, 'issue', metadata_then_fail)
    with pytest.raises(ValueError):
        service.export_admin(wf['id'], request, 1)
    assert not rt.store.query('SELECT id FROM workflow_apps WHERE active=1')
    assert not rt.store.query('SELECT id FROM workflow_deployment_grants WHERE active=1')
    assert not calls


@pytest.mark.parametrize('change', ['missing_authority', 'unknown_attempt', 'missing_attempt', 'wrong_input_hash'])
def test_deployment_review_requires_retained_certain_execution_proof(v12_runtime, change):
    rt, wf, service, calls = v12_runtime
    run_id = rt.store.query('SELECT id FROM workflow_runs WHERE workflow_id=?', (wf['id'],))[0]['id']
    with rt.store.tx() as db:
        if change == 'missing_authority':
            db.execute('DELETE FROM workflow_run_authority WHERE run_id=?', (run_id,))
        elif change == 'unknown_attempt':
            db.execute("UPDATE workflow_execution_attempts SET status='unknown' WHERE run_id=?", (run_id,))
        elif change == 'missing_attempt':
            db.execute('DELETE FROM workflow_execution_attempts WHERE run_id=?', (run_id,))
        else:
            db.execute("UPDATE workflow_execution_attempts SET input_hash='wrong' WHERE run_id=?", (run_id,))
    with pytest.raises(ValueError):
        export_request(service, wf)
    assert not rt.store.query('SELECT id FROM workflow_apps WHERE active=1') and not calls


def test_historical_authority_expiry_is_checked_at_original_admission(v12_runtime):
    rt, wf, service, calls = v12_runtime
    row = rt.store.query('SELECT id,created FROM workflow_runs WHERE workflow_id=?', (wf['id'],))[0]
    envelope = rt.store.query('SELECT payload FROM workflow_run_authority WHERE run_id=?', (row['id'],))[0]
    authority = json.loads(envelope['payload'])
    authority['principal']['payload']['expires'] = row['created'] - 1
    authority['principal']['signature'] = rt.authority.signature(authority['principal']['payload'])
    with rt.store.tx() as db:
        db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?',
                   (json.dumps(authority), rt.authority.signature(authority), row['id']))
    with pytest.raises(ValueError):
        export_request(service, wf)
    assert not calls


def test_run_ticket_is_bound_to_one_origin_even_when_both_are_registered(v12_runtime):
    rt, wf, service, calls = v12_runtime
    deployment = exported(v12_runtime, allowed_origins=[ORIGIN, 'https://other.example'])
    app, prepared = ticket(service, deployment)
    count = len(rt.store.query('SELECT id FROM workflow_runs'))
    with pytest.raises(ValueError):
        service.execute(app, run_request(prepared), 'https://other.example')
    assert len(rt.store.query('SELECT id FROM workflow_runs')) == count and not calls


def cycle_controls(rt):
    previous = controls(rt.store)
    flags = {key: previous[key] for key in ('invoke_enabled', 'workflow_enabled', 'delivery_enabled')}
    paused = set_controls(rt.store, {**flags, 'workflow_enabled': False, 'revision': previous['revision']}, 1)
    set_controls(rt.store, {**flags, 'revision': paused['revision']}, 1)


def test_controls_changed_after_export_review_require_a_new_review(v12_runtime):
    rt, wf, service, calls = v12_runtime
    request = export_request(service, wf)
    cycle_controls(rt)
    with pytest.raises(ValueError):
        service.export_admin(wf['id'], request, 1)
    assert not rt.store.query('SELECT id FROM workflow_apps WHERE active=1') and not calls


@pytest.mark.parametrize('change', ['revoke', 'control_cycle', 'owner_role'])
def test_current_authority_is_rechecked_between_service_validation_and_admission(v12_runtime, monkeypatch, change):
    rt, wf, service, calls = v12_runtime
    deployment = exported(v12_runtime)
    app, prepared = ticket(service, deployment)
    original = rt.submit

    def intervening_change(*args, **kwargs):
        if change == 'revoke':
            service.consent.revoke(app['id'], deployment['revision'])
        elif change == 'control_cycle':
            cycle_controls(rt)
        else:
            with rt.store.tx() as db:
                db.execute("UPDATE admin_users SET role='operator' WHERE id=1")
        return original(*args, **kwargs)

    monkeypatch.setattr(rt, 'submit', intervening_change)
    count = len(rt.store.query('SELECT id FROM workflow_runs'))
    with pytest.raises(ValueError):
        service.execute(app, run_request(prepared), ORIGIN)
    assert len(rt.store.query('SELECT id FROM workflow_runs')) == count and not calls


def test_dispatch_rechecks_revocation_even_if_cancel_signal_is_lost(v12_runtime, monkeypatch):
    rt, wf, service, calls = v12_runtime
    deployment = exported(v12_runtime)
    app, prepared = ticket(service, deployment)
    original = rt.persistence.prepare
    changed = []

    def revoke_after_prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        if not changed:
            changed.append(True)
            service.consent.revoke(app['id'], deployment['revision'])
        return result

    monkeypatch.setattr(rt, 'cancel', lambda run_id: None)
    monkeypatch.setattr(rt.persistence, 'prepare', revoke_after_prepare)
    job = service.execute(app, run_request(prepared), ORIGIN)
    result = wait(rt, job)
    assert changed and result['status'] == 'failed'
    assert not calls


@pytest.mark.parametrize('mismatch', ['actor', 'nonce', 'missing_nonce'])
def test_runtime_cannot_reuse_an_authorized_ticket_under_a_different_admission_key(v12_runtime, mismatch):
    rt, wf, service, calls = v12_runtime
    deployment = exported(v12_runtime)
    app, prepared = ticket(service, deployment)
    first = service.execute(app, run_request(prepared), ORIGIN)
    assert wait(rt, first)['status'] == 'succeeded' and len(calls) == 1
    current = service.consent.current(app['id'], origin=ORIGIN)
    context = {'ticket': prepared['proposal'], 'signature': prepared['signature'],
               'sharing_authority': True, 'sharing_notice': prepared['notices']['share'],
               'run_authority': True, 'run_notice': prepared['notices']['run'], 'origin': ORIGIN}
    actor = 'webapp-v12:' + app['id']
    nonce = prepared['proposal']['nonce']
    if mismatch == 'actor':
        actor = 'different-admission-actor'
    elif mismatch == 'nonce':
        nonce = 'different-admission-nonce'
    else:
        nonce = None
    with pytest.raises(ValueError):
        rt.submit(current['workflow'], actor=actor, source='webapp', idempotency=nonce,
                  principal=rt.principal('deployment', app['id'], wf['id']), deployment_consent=context)
    assert len(calls) == 1


def test_signed_deployment_and_run_purpose_round_trip_postgres_state(v12_runtime, monkeypatch):
    from scripts.rehearse_workflow_postgres import rehearse,TABLES

    rt, wf, service, calls = v12_runtime
    deployment = exported(v12_runtime)
    app, prepared = ticket(service, deployment)
    result = wait(rt, service.execute(app, run_request(prepared), ORIGIN))
    assert result['status'] == 'succeeded' and len(calls) == 1
    monkeypatch.setenv('PATH', '/opt/homebrew/opt/postgresql@14/bin:' + os.environ.get('PATH', ''))
    rehearsal = rehearse(rt.store._path)
    assert rehearsal['round_trip_equal'] and set(rehearsal['tables']) == set(TABLES)
    assert rehearsal['tables']['workflow_deployment_grants'] == 1
    assert rehearsal['tables']['workflow_run_authority'] >= 2
    assert rehearsal['tables']['workflow_execution_attempts'] >= 2
    output = Path('reports/advancement-sdk12-consent-2026-10-18/postgres-sdk12.json')
    output.write_text(json.dumps(rehearsal, indent=2) + '\n')
    assert len(calls) == 1


def test_restore_quarantine_preserves_but_revokes_deployment_tombstone(v12_runtime):
    from agent_market.workflow_backup import quarantine

    rt, wf, service, calls = v12_runtime
    deployment = exported(v12_runtime)
    copy_db = sqlite3.connect(':memory:')
    try:
        with rt.store._lock:
            rt.store._db.backup(copy_db)
        with copy_db:
            quarantine(copy_db)
        grant = copy_db.execute('SELECT active,revision,payload FROM workflow_deployment_grants').fetchone()
        assert grant[0] == 0 and grant[1] == deployment['revision'] + 1
        assert json.loads(grant[2])['revision'] == deployment['revision']
        assert copy_db.execute('SELECT active FROM workflow_apps').fetchone()[0] == 0
        assert copy_db.execute('SELECT invoke_enabled,workflow_enabled,delivery_enabled FROM execution_controls').fetchone() == (0, 0, 0)
    finally:
        copy_db.close()
    # The original isolated fixture was not restored or modified by the copy.
    assert service.consent.current(deployment['app_id'], origin=ORIGIN) and not calls


@pytest.mark.parametrize('column', ['actor', 'idempotency_key'])
def test_queued_run_cannot_resume_with_changed_nonce_admission_metadata(v12_runtime, monkeypatch, column):
    rt, wf, service, calls = v12_runtime
    deployment = exported(v12_runtime)
    app, prepared = ticket(service, deployment)
    launch = rt.launch
    monkeypatch.setattr(rt, 'launch', lambda run_id: None)
    job = service.execute(app, run_request(prepared), ORIGIN)
    with rt.store.tx() as db:
        # The column is a fixed parametrized allowlist, never request text.
        if column == 'actor':
            db.execute("UPDATE workflow_runs SET actor='changed-admission' WHERE id=?", (job['run_id'],))
        else:
            db.execute("UPDATE workflow_runs SET idempotency_key='changed-admission' WHERE id=?", (job['run_id'],))
    launch(job['run_id'])
    assert wait(rt, job)['status'] == 'failed'
    assert not calls
