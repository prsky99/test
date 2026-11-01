"""Reviewed factory commits and support metrics never grant implicit execution."""
import copy
import json
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.workspace_app_factory import AppFactory, NOTICE, SDK_NOTICE
from agent_market.workspace_support_outcomes import SupportOutcomes, NOTICE as SUPPORT_NOTICE, WITHDRAW_NOTICE
from agent_market.workspace_growth_service import router_for
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from tests.test_workspace_typed_flows import typed_world, routing, save, run
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_execution_api import private_api, execute as single_execute


@pytest.fixture
def growth(typed_world):
    w = typed_world
    factory = AppFactory(w.core); support = SupportOutcomes(w.access, w.execution, w.core)
    app = FastAPI(); app.include_router(router_for(factory, support))
    with TestClient(app, base_url='http://growth.test', raise_server_exceptions=False) as client:
        yield SimpleNamespace(w=w, factory=factory, support=support, client=client,
            base='/admin/api/workflow-workspaces/'+w.ws,
            headers={'Authorization': 'Bearer '+w.raw, 'X-Dashboard': '1', 'Origin': 'http://growth.test'})


def review_body(g):
    return {'template_id': 'documentation_crosscheck', 'purpose': 'Current reference documentation',
            'resource_ids': g.w.ids[:2], 'name': 'Reviewed documentation app', 'from_utc': None, 'criteria': []}


def test_actual_factory_preview_commit_is_atomic_idempotent_and_no_provider_call(growth):
    g = growth; before = len(g.w.calls)
    review = g.factory.prepare(g.w.ws, review_body(g), g.w.actor)
    assert len(g.w.calls) == before and review['provider_calls'] == 0
    assert len(review['definition']['nodes']) == 2 and len(review['destinations']) == 2
    body = {'review_id': review['review_id'], 'authorized': True, 'notice': NOTICE}
    first = g.factory.commit(g.w.ws, body, g.w.actor)
    again = g.factory.commit(g.w.ws, body, g.w.actor)
    assert first['id'] == again['id'] and again['replayed']
    assert g.w.store.query('SELECT COUNT(*) FROM workspace_typed_flows')[0][0] == 1
    assert len(g.w.calls) == before
    detail = g.w.core.detail(g.w.ws, first['id'], g.w.actor)
    assert detail['definition'] == review['definition']
    result, _ = run(g.w, first)
    assert result['run']['status'] == 'succeeded' and len(g.w.calls) == before + 2


@pytest.mark.parametrize('mutation', ['expiry', 'binding', 'role', 'restore', 'signature'])
def test_stale_factory_review_never_materializes(mutation, growth, monkeypatch):
    g = growth; review = g.factory.prepare(g.w.ws, review_body(g), g.w.actor)
    with g.w.store.tx() as db:
        if mutation == 'binding': db.execute("UPDATE resources SET url='https://changed.example/mcp' WHERE id=?", (g.w.ids[0],))
        elif mutation == 'role': db.execute("UPDATE workspace_memberships SET role='viewer',revision=revision+1 WHERE workspace_id=?", (g.w.ws,))
        elif mutation == 'restore': db.execute('INSERT INTO workspace_expansion_restore_blocks VALUES(?)', (review['review_id'],))
        elif mutation == 'signature': db.execute("UPDATE workspace_factory_reviews SET signature='invalid' WHERE id=?", (review['review_id'],))
    if mutation == 'expiry': monkeypatch.setattr('agent_market.workspace_app_factory.clock', lambda: review['expires'])
    with pytest.raises((WorkspaceDenied, WorkspaceConflict)):
        g.factory.commit(g.w.ws, {'review_id': review['review_id'], 'authorized': True, 'notice': NOTICE}, g.w.actor)
    assert not g.w.calls and not g.w.store.query('SELECT id FROM workspace_typed_flows')


def test_factory_rollback_cannot_leave_an_orphan_flow(growth, monkeypatch):
    g = growth; review = g.factory.prepare(g.w.ws, review_body(g), g.w.actor)
    original = g.w.access._audit
    def fail(db, actor, ws, action, *args):
        if action == 'factory.commit': raise WorkspaceConflict()
        return original(db, actor, ws, action, *args)
    monkeypatch.setattr(g.w.access, '_audit', fail)
    with pytest.raises(WorkspaceConflict):
        g.factory.commit(g.w.ws, {'review_id': review['review_id'], 'authorized': True, 'notice': NOTICE}, g.w.actor)
    assert not g.w.store.query('SELECT id FROM workspace_typed_flows')
    assert not g.w.store.query('SELECT review_id FROM workspace_factory_commits')


def test_factory_auto_compiles_only_fixed_contracts_and_rejects_secret_inputs(growth):
    g = growth; body = review_body(g) | {'template_id': 'auto', 'resource_ids': None}
    result = g.factory.prepare(g.w.ws, body, g.w.actor)
    assert result['template_id'] == 'documentation_crosscheck'
    assert all(node['contract_id'] == 'docs.search.v1' for node in result['definition']['nodes'])
    for change in ({'purpose': 'Bearer synthetic-secret'}, {'purpose': 'Fetch https://private.example'}, {'resource_ids': [True, 2]}, {'criteria': [{}]}, {'from_utc': 'not-a-date'}):
        with pytest.raises(WorkspaceInvalid): g.factory.prepare(g.w.ws, body | change, g.w.actor)
    assert not g.w.calls


def sdk_body(profile='workspace-typed-sdk-v2', *, accepting=False, revision=0):
    return {'sdk_profile': profile, 'revision': revision, 'accepting_runs': accepting,
            'minimum_sdk_version': '2.1.0' if profile == 'workspace-typed-sdk-v2' else '2.0.0',
            'sunset_seconds': 300, 'authorized': True, 'notice': SDK_NOTICE}


def test_current_sdk_policy_blocks_new_typed_execution_but_keeps_retained_history(typed_release_world):
    s = typed_release_world
    factory = AppFactory(s.w.core, releases=s.releases, typed_releases=s.releases)
    from tests.test_workspace_typed_release import token
    raw = token(s)
    origin = s.config['allowed_origins'][0]
    plan = s.releases.prepare(s.deployment['app_id'], raw, origin)
    from agent_market.workspace_typed_release import RUN_NOTICE
    completed = s.releases.execute(s.deployment['app_id'], raw, {'ticket_id': plan['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, origin)
    before = len(s.w.calls)
    factory.configure_sdk(s.w.ws, sdk_body(), s.w.actor)
    with pytest.raises(WorkspaceDenied): s.releases.prepare(s.deployment['app_id'], raw, s.config['allowed_origins'][0])
    assert len(s.w.calls) == before
    retained = s.releases.history(s.deployment['app_id'], raw, origin)
    assert retained[0]['id'] == completed['run']['id']
    retained_status = s.releases.status(s.deployment['app_id'], completed['status_capability']['access_token'], completed['run']['id'], origin)
    assert retained_status['status'] == 'succeeded'
    catalog = factory.catalog(s.w.ws, s.w.actor)
    assert catalog['releases'][0]['blocked_by_sdk_policy']
    factory.configure_sdk(s.w.ws, sdk_body(accepting=True, revision=1), s.w.actor)
    current = s.releases.prepare(s.deployment['app_id'], raw, s.config['allowed_origins'][0])
    assert current['review']['max_calls'] == 2 and len(s.w.calls) == before


def support_body(g, flow, result):
    return {'source_kind': 'typed', 'subject_id': flow['id'], 'version_id': flow['version_id'], 'run_id': result['run']['id'],
            'category': 'setup', 'resolution': 'resolved', 'iterations': 2, 'revision': 0,
            'authorized': True, 'notice': SUPPORT_NOTICE}


def test_support_outcomes_are_source_bound_deduplicated_and_not_business_quality(growth):
    g = growth; flow = save(g.w); result, _ = run(g.w, flow); body = support_body(g, flow, result); calls = len(g.w.calls)
    first = g.support.record(g.w.ws, body, g.w.actor)
    assert g.support.record(g.w.ws, body, g.w.actor)['replayed']
    report = g.support.report(g.w.ws, g.w.actor)
    assert report['logical_run_samples'] == 1 and report['resolution_counts']['resolved'] == 1
    assert report['business_outcome'] == 'unassessed' and not report['customer_reuse_qualified']
    assert not report['provider_quality_qualified'] and report['observed_subject_repeat_after_28_days'] == 0
    g.support.withdraw(g.w.ws, {'case_id': first['case_id'], 'revision': 1, 'authorized': True, 'notice': WITHDRAW_NOTICE}, g.w.actor)
    report = g.support.report(g.w.ws, g.w.actor)
    assert report['logical_run_samples'] == 0 and report['excluded']['withdrawn'] == 1 and len(g.w.calls) == calls
    with pytest.raises(WorkspaceDenied): g.support.record(g.w.ws, body, g.w.actor)


def test_support_source_deleted_or_restore_is_neutral_and_cannot_resurrect(growth):
    g = growth; flow = save(g.w); result, _ = run(g.w, flow)
    case = g.support.record(g.w.ws, support_body(g, flow, result), g.w.actor)
    with g.w.store.tx() as db: db.execute('DELETE FROM workspace_typed_flow_runs WHERE id=?', (result['run']['id'],))
    report = g.support.report(g.w.ws, g.w.actor)
    assert report['excluded']['source_unavailable'] == 1 and report['logical_run_samples'] == 0
    with g.w.store.tx() as db: db.execute('INSERT INTO workspace_support_restore_blocks VALUES(?)', (case['case_id'],))
    assert g.support.report(g.w.ws, g.w.actor)['excluded']['restored'] == 1


def test_growth_api_auth_origin_body_shape_and_no_private_leaks(growth):
    g = growth
    assert g.client.get(g.base+'/app-factory/options').status_code == 401
    assert g.client.get(g.base+'/app-factory/options', headers=g.headers).status_code == 200
    url = g.base+'/app-factory/reviews'
    assert g.client.post(url, json=review_body(g), headers=g.headers | {'Origin': 'https://other.example'}).status_code == 403
    assert g.client.post(url, json=review_body(g) | {'endpoint': 'https://secret.example'}, headers=g.headers).status_code == 400
    response = g.client.post(url, json=review_body(g), headers=g.headers)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert g.w.raw not in response.text and 'primary.example' not in response.text and 'session_ref' not in response.text
    review = response.json()['result']
    assert g.client.post(g.base+'/app-factory/commits', json={'review_id': review['review_id'], 'authorized': False, 'notice': NOTICE}, headers=g.headers).status_code == 400
    assert not g.w.calls


def test_support_single_run_metadata_does_not_decrypt_retained_output(private_api, monkeypatch):
    from agent_market.workspace_access import SessionActor, WorkspaceAccess
    from agent_market.workspace_execution import WorkspaceExecution
    from agent_market.workspace_typed_flows import TypedFlows
    from agent_market.gateway import admin_auth
    from agent_market.workflows import runtime_for
    from tests.test_workspace_reliability import encryption
    w = private_api; result, _ = single_execute(w)
    access = WorkspaceAccess(w.store, runtime_for(w.store, None).key)
    execution = WorkspaceExecution(access, SimpleNamespace())
    actor = SessionActor(1, admin_auth.session_reference(w.headers['owner']['Authorization'][7:]))
    execution._output_cipher = encryption()
    with access._tx(actor, write=True) as (db, _):
        _, _, _, payload = execution._load_run(db, result['id'], w.ws['id'], w.draft['id'], w.snapshot['id'])
        execution._store_run(db, payload)
    assert 'encrypted_output' in w.store.query('SELECT payload FROM workspace_private_runs')[0][0]
    monkeypatch.setattr(execution._output_cipher, 'open', lambda *_args: pytest.fail('Support metrics decrypted a private output'))
    support = SupportOutcomes(access, execution, TypedFlows(execution))
    body = {'source_kind': 'single', 'subject_id': w.draft['id'], 'version_id': w.snapshot['id'], 'run_id': result['id'],
        'category': 'execution', 'resolution': 'resolved', 'iterations': 0, 'revision': 0, 'authorized': True, 'notice': SUPPORT_NOTICE}
    support.record(w.ws['id'], body, actor)
    report = support.report(w.ws['id'], actor)
    assert report['logical_run_samples'] == 1 and report['business_outcome'] == 'unassessed'
    assert 'Private research result' not in json.dumps(report)


def test_sdk_policy_requires_current_owner_and_rejects_replayed_revision(growth):
    g = growth
    g.factory.configure_sdk(g.w.ws, sdk_body(), g.w.actor)
    with pytest.raises(WorkspaceConflict): g.factory.configure_sdk(g.w.ws, sdk_body(), g.w.actor)
    with g.w.store.tx() as db:
        db.execute("UPDATE workspace_memberships SET role='editor',revision=revision+1 WHERE workspace_id=?", (g.w.ws,))
    with pytest.raises(WorkspaceDenied): g.factory.configure_sdk(g.w.ws, sdk_body(revision=1), g.w.actor)
    assert not g.factory.catalog(g.w.ws, g.w.actor)['policies'][1]['current_owner']


def test_proposal_limit_counts_only_the_last_30_days(growth):
    """QA 19: the 100-proposal limit was lifetime, so an active workspace lost AI generation for good."""
    from agent_market.workspace_access import WorkspaceLimit
    g = growth; old = time.time() - 31 * 86400
    with g.w.store.tx() as db:
        for _ in range(150):
            db.execute('''INSERT INTO workspace_access_audit
                (workspace_id,actor_user_id,action,object_id,revision,created) VALUES(?,?,?,?,?,?)''',
                (g.w.ws, g.w.actor.user_id, 'factory.prepare', 'wfr_old', 1, old))
    assert g.factory.prepare(g.w.ws, review_body(g), g.w.actor)['review_id']
    with g.w.store.tx() as db:
        for _ in range(99):
            db.execute('''INSERT INTO workspace_access_audit
                (workspace_id,actor_user_id,action,object_id,revision,created) VALUES(?,?,?,?,?,?)''',
                (g.w.ws, g.w.actor.user_id, 'factory.plan_review', 'wfr_new', 1, time.time()))
    with pytest.raises(WorkspaceLimit) as error:
        g.factory.prepare(g.w.ws, review_body(g), g.w.actor)
    assert 'last 30 days, the limit.' in str(error.value)


def test_proposal_limit_query_is_registered_for_postgresql():
    import inspect, re
    from agent_market import application_store_postgres as postgres, workspace_app_factory as module
    sql = re.search(r"'''(.+?)'''", inspect.getsource(module._admit_review), re.S).group(1)
    assert postgres._normalized(sql) in postgres._STATEMENTS
