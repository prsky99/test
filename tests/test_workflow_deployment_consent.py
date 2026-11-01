"""Isolated grant, per-run purpose and revocation boundaries for opt-in SDK 1.2."""
import copy
import json
import os
import secrets
import signal
import subprocess
import sys
import time

import pytest

from agent_market.capability_registry import Registry, digest
from agent_market.gateway.admin_auth import ADMIN_SCHEMA, create_admin_user
from agent_market.workflow_apps import WorkflowApps
from agent_market.workflow_composer import Composer
from agent_market.workflow_deployment_consent import PROFILE, GRANT_NOTICE, SHARE_NOTICE, RUN_NOTICE
from agent_market.workflows import WorkflowError
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_runtime import wait
from tests.test_workflow_composer import save

ORIGIN = 'https://fixed-app.example'


@pytest.fixture
def consent_deployment(typed_routing):
    rt, _, _, calls, modes, hooks, remote = typed_routing
    with rt.store._lock:
        rt.store._db.executescript(ADMIN_SCHEMA)
    with rt.store.tx() as db:
        owner = create_admin_user(db, 'deployment-reviewer', 'isolated-long-password', 'Deployment reviewer', 'superadmin')
    if isinstance(owner, dict): owner = owner['id']
    draft = Composer(rt).generate({'prompt': 'Python news and documentation search'}, 1)
    workflow = rt.store.get_workflow(save(rt, draft)['id'])
    principal = rt.principal('admin', str(owner), workflow['id'], role='superadmin')
    test = wait(rt, rt.submit(workflow, principal=principal))
    assert test['status'] == 'succeeded', test
    Composer(rt).validate_publish(workflow, test['run_id'])
    with rt.store.tx() as db:
        db.execute('UPDATE agent_workflows SET is_template=1 WHERE id=?', (workflow['id'],))
    workflow = rt.store.get_workflow(workflow['id'])
    legacy = WorkflowApps(rt.store, rt)
    app = legacy.create(workflow['id'], {'allowed_origins': [ORIGIN], 'input_fields': []})
    consent = rt.deployment_consent
    expires = min(time.time() + 3600, consent.expiry_limit(workflow) - .01)
    with rt.store.tx() as db:
        db.execute('UPDATE workflow_apps SET active=0 WHERE id=?', (app['app_id'],))
        grant = consent.issue(db, app['app_id'], workflow, principal, expires=expires, authority=True, notice=GRANT_NOTICE)
        db.execute('UPDATE workflow_apps SET active=1 WHERE id=?', (app['app_id'],))
    calls.clear(); rt.typed_test_controls['seen'].clear(); rt.typed_test_controls['news_calls'] = 0
    return rt, workflow, app, grant, principal, test, typed_routing


def run_context(rt, app, *, origin=ORIGIN):
    prepared = rt.deployment_consent.prepare(app['app_id'], origin)
    return {'ticket': prepared['ticket'], 'signature': prepared['signature'], 'sharing_authority': True,
            'sharing_notice': SHARE_NOTICE, 'run_authority': True, 'run_notice': RUN_NOTICE, 'origin': origin}


def submit(rt, workflow, app, context):
    return rt.submit(workflow, actor='webapp-v12:' + app['app_id'], source='webapp',
                     idempotency=context['ticket']['nonce'], principal=rt.principal('deployment', app['app_id'], workflow['id']),
                     deployment_consent=context)


def test_fixed_current_grant_and_two_fresh_declarations_execute_once(consent_deployment):
    rt, workflow, app, grant, _, _, routing = consent_deployment
    calls = routing[3]; context = run_context(rt, app)
    result = wait(rt, submit(rt, workflow, app, context))
    assert result['status'] == 'succeeded', result
    assert len(calls) == 2 and calls[0] == 'primary.example'
    assert rt.typed_test_controls['seen'] == [node['data']['input'] for node in workflow['nodes'][1:]]
    assert 'from_utc' in context['ticket'] or rt.typed_test_controls['seen'][0]['from_utc'] == workflow['nodes'][1]['data']['input']['from_utc']
    replay = submit(rt, workflow, app, context)
    assert replay['replayed'] and replay['run_id'] == result['run_id'] and len(calls) == 2
    authority = json.loads(rt.store.query('SELECT payload FROM workflow_run_authority WHERE run_id=?', (result['run_id'],))[0][0])
    assert authority['principal']['payload']['deployment_consent']['ticket'] == context['ticket']
    assert authority['grant_id'] is None
    assert not rt.store.query('SELECT * FROM workflow_result_outbox WHERE run_id=?', (result['run_id'],))


def test_public_ticket_and_preview_never_export_private_grant_or_pins(consent_deployment):
    rt, _, app, *_ = consent_deployment
    prepared = rt.deployment_consent.prepare(app['app_id'], ORIGIN)
    encoded = json.dumps(prepared)
    for private in ('owner', 'composition', 'primary.example', 'alternate.example', 'third.example',
                    'resource_id', 'version_id', 'capability_approvals', 'proof', 'bindings', 'superadmin'):
        assert private not in encoded
    recipients = prepared['preview']['recipients']
    assert len(recipients) == 2 and all(' agent ' in recipient['alias'] for recipient in recipients)
    assert prepared['preview']['sharing_notice'] == SHARE_NOTICE and prepared['preview']['run_notice'] == RUN_NOTICE
    assert prepared['ticket']['expires'] <= prepared['ticket']['created'] + 300


def test_signed_ticket_survives_browser_integral_number_roundtrip(consent_deployment, monkeypatch):
    rt, workflow, app, *_ = consent_deployment
    frozen = float(int(time.time()) + 1)
    with monkeypatch.context() as patch:
        patch.setattr('agent_market.workflow_deployment_consent.time.time', lambda: frozen)
        context = run_context(rt, app)
        context = json.loads(json.dumps(context), parse_float=lambda value: int(float(value)) if float(value).is_integer() else float(value))
        assert type(context['ticket']['created']) is int and type(context['ticket']['expires']) is int
        result = wait(rt, submit(rt, workflow, app, context))
    assert result['status'] == 'succeeded', result


@pytest.mark.parametrize('field,value', [('sharing_authority', False), ('sharing_authority', 1),
                                        ('run_authority', False), ('run_notice', SHARE_NOTICE),
                                        ('sharing_notice', GRANT_NOTICE), ('origin', 'https://other.example'),
                                        ('extra', 'not-accepted')])
def test_missing_wrong_or_cross_purpose_declarations_do_not_admit(consent_deployment, field, value):
    rt, workflow, app, _, _, _, routing = consent_deployment
    context = run_context(rt, app); context[field] = value
    with pytest.raises(WorkflowError): submit(rt, workflow, app, context)
    assert not routing[3]


def test_existing_sdk_11_style_submit_cannot_bypass_registered_grant(consent_deployment):
    rt, workflow, app, _, _, _, routing = consent_deployment
    with pytest.raises(WorkflowError):
        rt.submit(workflow, actor='webapp:' + app['app_id'], source='webapp',
                  principal=rt.principal('deployment', app['app_id'], workflow['id']))
    assert not routing[3]


@pytest.mark.parametrize('field,value', [('grant_revision', True), ('grant_id', 'dg_' + '0' * 32),
                                        ('definition_hash', '0' * 64), ('inputs_hash', '0' * 64),
                                        ('aliases_hash', '0' * 64), ('created', True), ('expires', 0)])
def test_signed_ticket_semantic_tamper_is_refused(consent_deployment, field, value):
    rt, workflow, app, _, _, _, routing = consent_deployment
    context = run_context(rt, app); context['ticket'][field] = value
    context['signature'] = rt.authority.signature(context['ticket'])
    with pytest.raises(WorkflowError): submit(rt, workflow, app, context)
    assert not routing[3]


def test_nonce_cannot_be_rebound_to_another_valid_ticket(consent_deployment):
    rt, workflow, app, _, _, _, routing = consent_deployment
    first = run_context(rt, app); wait(rt, submit(rt, workflow, app, first)); before = len(routing[3])
    other = run_context(rt, app); other['ticket']['nonce'] = first['ticket']['nonce']
    other['signature'] = rt.authority.signature(other['ticket'])
    with pytest.raises(WorkflowError): submit(rt, workflow, app, other)
    assert len(routing[3]) == before


@pytest.mark.parametrize('boundary', ['grant', 'owner', 'controls', 'app', 'input', 'approval'])
def test_live_change_after_source_stops_next_dispatch(consent_deployment, boundary):
    from agent_market.execution_authority import controls, set_controls
    rt, workflow, app, grant, principal, _, routing = consent_deployment
    calls, hooks = routing[3], routing[5]

    def change(_):
        if boundary == 'grant': rt.deployment_consent.revoke(app['app_id'], grant['revision'])
        elif boundary == 'controls':
            for enabled in (False, True):
                policy = controls(rt.store)
                set_controls(rt.store, {'invoke_enabled': enabled, 'workflow_enabled': True,
                                       'delivery_enabled': policy['delivery_enabled'], 'revision': policy['revision']}, 1)
        elif boundary == 'approval':
            target = workflow['nodes'][2]
            Registry(rt.store).approve(rt.store.resource(target['resource_id']), 'docs.search.v1', 'search_docs')
        else:
            with rt.store.tx() as db:
                if boundary == 'owner': db.execute('UPDATE admin_users SET active=0 WHERE id=?', (int(principal['payload']['subject']),))
                elif boundary == 'app': db.execute('UPDATE workflow_apps SET active=0 WHERE id=?', (app['app_id'],))
                else:
                    changed = copy.deepcopy(workflow['nodes']); changed[2]['data']['input']['query'] = 'Different reviewed query'
                    db.execute('UPDATE agent_workflows SET steps=? WHERE id=?', (json.dumps({'nodes': changed, 'edges': workflow['edges']}), workflow['id']))

    context = run_context(rt, app); hooks['primary.example'] = change
    result = wait(rt, submit(rt, workflow, app, context))
    assert result['status'] != 'succeeded' and calls == ['primary.example']
    assert not rt.store.query("SELECT * FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-2' AND status='dispatched'", (result['run_id'],))


@pytest.mark.parametrize('attack', ['unknown_attempt', 'input_hash', 'missing_authority', 'pruned_checkpoint', 'routing_attempt'])
def test_original_administrator_proof_cannot_be_replaced_by_unsigned_success(consent_deployment, attack):
    rt, _, app, _, _, proof, _ = consent_deployment
    with rt.store.tx() as db:
        if attack == 'unknown_attempt': db.execute("UPDATE workflow_execution_attempts SET status='unknown' WHERE run_id=? AND node_id='search-1'", (proof['run_id'],))
        elif attack == 'input_hash': db.execute("UPDATE workflow_execution_attempts SET input_hash='wrong' WHERE run_id=? AND node_id='search-1'", (proof['run_id'],))
        elif attack == 'missing_authority': db.execute('DELETE FROM workflow_run_authority WHERE run_id=?', (proof['run_id'],))
        elif attack == 'pruned_checkpoint': db.execute("DELETE FROM workflow_checkpoints WHERE run_id=? AND node_id='search-1'", (proof['run_id'],))
        else:
            resource_id = rt.store.get_workflow(proof['workflow_id'])['nodes'][1]['resource_id']
            db.execute("INSERT INTO workflow_routing_attempts(run_id,node_id,ordinal,resource_id,fence,status,created) VALUES (?,'search-1',2,?,1,'succeeded',?)",
                       (proof['run_id'], resource_id, time.time()))
    with pytest.raises(ValueError): rt.deployment_consent.prepare(app['app_id'], ORIGIN)


def test_original_historical_authority_need_not_remain_unexpired_today(consent_deployment):
    rt, _, app, _, _, proof, _ = consent_deployment
    with rt.store.tx() as db:
        row = db.execute('SELECT payload FROM workflow_run_authority WHERE run_id=?', (proof['run_id'],)).fetchone()
        authority = json.loads(row[0]); payload = authority['principal']['payload']
        checkpoints = db.execute("SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id!='start'", (proof['run_id'],)).fetchall()
        last_start = max(json.loads(row[0])['record']['started'] for row in checkpoints)
        payload['expires'] = last_start + .001
        authority['principal']['signature'] = rt.authority.signature(payload)
        db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?',
                   (json.dumps(authority), rt.authority.signature(authority), proof['run_id']))
    time.sleep(.005)
    assert rt.deployment_consent.prepare(app['app_id'], ORIGIN)['ticket']['profile'] == PROFILE


def test_issue_does_not_commit_an_outer_app_transaction(consent_deployment, monkeypatch):
    rt, workflow, _, _, principal, _, _ = consent_deployment
    new_id = 'app_' + secrets.token_hex(16)
    original = rt.store.query('SELECT * FROM workflow_apps LIMIT 1')[0]

    def forbidden(*args, **kwargs): raise AssertionError('Issuance must not initialize registry versions.')
    monkeypatch.setattr(Registry, 'current', forbidden)
    with pytest.raises(RuntimeError, match='rollback'):
        with rt.store.tx() as db:
            db.execute('INSERT INTO workflow_apps SELECT ?,workflow_id,key_hash,definition_hash,origins,fields,minute_limit,day_limit,0,created FROM workflow_apps WHERE id=?',
                       (new_id, original['id']))
            rt.deployment_consent.issue(db, new_id, workflow, principal, expires=time.time() + 1800,
                                        authority=True, notice=GRANT_NOTICE)
            assert db.in_transaction
            raise RuntimeError('rollback')
    assert not rt.store.query('SELECT * FROM workflow_apps WHERE id=?', (new_id,))
    assert not rt.store.query('SELECT * FROM workflow_deployment_grants WHERE app_id=?', (new_id,))


def test_grant_revocation_is_cas_and_cannot_be_resumed(consent_deployment):
    rt, _, app, grant, *_ = consent_deployment
    with pytest.raises(ValueError): rt.deployment_consent.revoke(app['app_id'], grant['revision'] + 1)
    assert rt.deployment_consent.revoke(app['app_id'], grant['revision'])['active'] is False
    with pytest.raises(ValueError): rt.deployment_consent.revoke(app['app_id'], grant['revision'])
    assert rt.deployment_consent.is_v12(app['app_id'])
    with pytest.raises(ValueError): rt.deployment_consent.prepare(app['app_id'], ORIGIN)


@pytest.mark.parametrize('change', ['failed_provider', 'pruned_proof', 'paused_and_resumed'])
def test_read_access_preserves_retained_outcomes_without_authorizing_new_invocation(consent_deployment, change):
    from agent_market.execution_authority import controls, set_controls
    rt, _, app, _, _, proof, routing = consent_deployment
    if change == 'failed_provider':
        with rt.store.tx() as db: db.execute("UPDATE capability_evidence SET expires=0")
    elif change == 'pruned_proof':
        with rt.store.tx() as db: db.execute('DELETE FROM workflow_checkpoints WHERE run_id=?', (proof['run_id'],))
    else:
        for enabled in (False, True):
            policy = controls(rt.store)
            set_controls(rt.store, {'invoke_enabled': enabled, 'workflow_enabled': True,
                                    'delivery_enabled': policy['delivery_enabled'], 'revision': policy['revision']}, 1)
    assert rt.deployment_consent.read_access(app['app_id'], ORIGIN)['grant']['profile'] == PROFILE
    with pytest.raises(ValueError): rt.deployment_consent.prepare(app['app_id'], ORIGIN)
    assert not routing[3]


@pytest.mark.parametrize('declaration', [{}, {'authority': False, 'notice': GRANT_NOTICE},
                                      {'authority': 1, 'notice': GRANT_NOTICE},
                                      {'authority': True, 'notice': SHARE_NOTICE},
                                      {'authority': True}])
def test_grant_issue_requires_an_explicit_purpose_declaration(consent_deployment, declaration):
    rt, workflow, app, _, principal, *_ = consent_deployment
    new_id = 'app_' + secrets.token_hex(16)
    with rt.store.tx() as db:
        db.execute('INSERT INTO workflow_apps SELECT ?,workflow_id,key_hash,definition_hash,origins,fields,minute_limit,day_limit,0,created FROM workflow_apps WHERE id=?',
                   (new_id, app['app_id']))
        with pytest.raises(ValueError):
            rt.deployment_consent.issue(db, new_id, workflow, principal, expires=time.time() + 1800, **declaration)
    assert not rt.store.query('SELECT * FROM workflow_deployment_grants WHERE app_id=?', (new_id,))


CHILD = r'''
import json,os,signal,sys,httpx
from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowRuntime
from agent_market.concierge.proxy import McpProxy
from tests.test_mcp_proxy import MockRemoteMcp
from tests.test_workflow_fallback import tool,output
path,run_id,audit,phase=sys.argv[1:]
remote=MockRemoteMcp([tool()],call_result=output());original=remote.handle_request
def die():os.kill(os.getpid(),signal.SIGKILL)
def handle(request):
 body=json.loads(request.content or '{}');news=request.url.host=='primary.example'
 remote.tools=[tool('news.search.v1') if news else tool()]
 if body.get('method')=='tools/call':
  with open(audit,'a') as out:out.write(request.url.host+'\n');out.flush();os.fsync(out.fileno())
  if phase=='docs-dispatched' and not news:die()
  remote.call_result=output('news.search.v1' if news else 'docs.search.v1')
 return original(request)
remote.handle_request=handle
store=Store(path);client=httpx.Client(transport=remote)
runtime=WorkflowRuntime(store,McpProxy(store,allow_private=True,http=client))
if phase=='news-checkpoint':
 checkpoint=runtime.persistence.checkpoint
 def saved(*args,**kwargs):
  result=checkpoint(*args,**kwargs)
  if args[3]=='search-1':die()
  return result
 runtime.persistence.checkpoint=saved
runtime._execute(run_id)
raise SystemExit('Expected crash boundary was not reached')
'''


@pytest.mark.parametrize('phase', ['news-checkpoint', 'docs-dispatched'])
def test_real_sigkill_recovery_preserves_grant_scope_and_never_replays_dispatch(consent_deployment, monkeypatch, tmp_path, phase):
    rt, workflow, app, _, _, _, routing = consent_deployment
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    context = run_context(rt, app); job = submit(rt, workflow, app, context)
    audit = tmp_path / 'deployment-calls.txt'
    child = subprocess.run([sys.executable, '-B', '-c', CHILD, rt.store._path, job['run_id'], str(audit), phase],
                           capture_output=True, timeout=15)
    assert child.returncode == -signal.SIGKILL, child.stderr.decode()[-1600:]
    before = audit.read_text().splitlines()
    deadline = rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?', (job['run_id'],))[0][0]
    with rt.store.tx() as db: db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?', (job['run_id'],))
    rt.persistence.recover(); rt._execute(job['run_id'])
    result = rt.get(job['run_id'])
    assert before[0] == 'primary.example' and before.count('primary.example') == 1
    if phase == 'news-checkpoint':
        assert len(before) == 1 and len(routing[3]) == 1 and routing[3][0] != 'primary.example'
        assert result['status'] == 'succeeded', result
    else:
        assert len(before) == 2 and not routing[3]
        assert result['status'] == 'failed' and result['execution_outcome'] == 'unknown'
        for _ in range(2): rt.persistence.recover(); rt._execute(job['run_id'])
        assert not routing[3]
    assert len(before) + len(routing[3]) == 2
    assert rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?', (job['run_id'],))[0][0] == deadline
    assert not rt.store.query('SELECT * FROM workflow_result_outbox WHERE run_id=?', (job['run_id'],))


def test_backup_restore_revokes_grant_and_preserves_only_safe_inventory(consent_deployment, tmp_path):
    from pathlib import Path
    from agent_market.gateway.store import Store
    from agent_market.workflow_backup import backup, restore
    from agent_market.workflows import WorkflowRuntime
    rt, _, app, grant, *_ = consent_deployment
    context = run_context(rt, app)
    before_epoch = rt.store.query('SELECT updated FROM execution_controls')[0][0]
    snapshot = tmp_path / 'snapshot'; backup(rt.store._path, snapshot)
    target = tmp_path / 'restored.db'; result = restore(snapshot, target)
    inventory = json.loads(Path(str(target) + '.restored-inventory.json').read_text())
    records = inventory['items']['workflow_deployment_grants']['records']
    assert records == [{'id': grant['grant_id'], 'app_id': app['app_id'],
                        'workflow_id': context['ticket'].get('workflow_id', rt.store.query('SELECT workflow_id FROM workflow_apps WHERE id=?', (app['app_id'],))[0][0]),
                        'revision': 1, 'active': 1}]
    serialized = json.dumps(inventory)
    for private in ('deployment-reviewer', 'primary.example', 'composition', 'superadmin', 'Python news'):
        assert private not in serialized
    assert result['integrity'] == 'ok' and inventory['automatic_reactivation'] is False
    restored = Store(str(target)); runtime = WorkflowRuntime(restored, rt.proxy, rt.courier)
    try:
        row = restored.query('SELECT active,revision,revoked FROM workflow_deployment_grants WHERE app_id=?', (app['app_id'],))[0]
        assert row['active'] == 0 and row['revision'] == grant['revision'] + 1 and row['revoked']
        assert not restored.query('SELECT active FROM workflow_apps WHERE id=?', (app['app_id'],))[0][0]
        controls = restored.query('SELECT invoke_enabled,workflow_enabled,delivery_enabled,updated FROM execution_controls')[0]
        assert not any(controls[name] for name in ('invoke_enabled', 'workflow_enabled', 'delivery_enabled'))
        assert controls['updated'] > before_epoch
        assert runtime.deployment_consent.is_v12(app['app_id'])
        with pytest.raises(ValueError): runtime.deployment_consent.current(app['app_id'], origin=ORIGIN)
    finally:
        restored._db.close()
