"""Independent connected-app grant, origin, manual-purpose and recovery tests."""
import copy
import hashlib
import json
import signal
import subprocess
import sys
import time

import pytest

from agent_market.workflow_connection_deployment import PROFILE, GRANT_NOTICE, SHARE_NOTICE, RUN_NOTICE, origins
from agent_market.workflow_publication import SHARE_NOTICE as PUBLIC_SHARE, RUN_NOTICE as PUBLIC_RUN
from agent_market.workflows import WorkflowError
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_publication import publication, published, declaration as public_declaration
from tests.test_workflow_runtime import wait

ORIGIN = 'https://connected-app.example'
OTHER = 'https://second-connected-app.example'


def issue(rt, owner, release, *, allowed=None):
    core = rt.connection_deployments
    prepared = core.prepare_admin(release['id'], {'allowed_origins': allowed or [ORIGIN, OTHER], 'minute_limit': 10, 'day_limit': 500, 'ttl_seconds': 1800}, owner)
    body = {'proposal': prepared['proposal'], 'signature': prepared['signature'], 'deployment_authority': True, 'deployment_notice': GRANT_NOTICE}
    return core.issue(release['id'], body, owner), body


@pytest.fixture
def connection_deployment(publication):
    rt, owner, routed = publication; release, proof, *_ = published(rt, owner)
    issued, body = issue(rt, owner, release)
    routed[3].clear(); rt.typed_test_controls['seen'].clear()
    return rt, owner, routed, release, proof, issued['deployment'], body


def run_body(prepared):
    return {'proposal': copy.deepcopy(prepared['proposal']), 'signature': prepared['signature'], 'sharing_authority': True,
            'sharing_notice': SHARE_NOTICE, 'run_authority': True, 'run_notice': RUN_NOTICE}


def execute(rt, app, *, origin=ORIGIN):
    body = run_body(rt.connection_deployments.prepare_run(app['app_id'], origin))
    return rt.connection_deployments.execute_run(app['app_id'], body, origin), body


def test_separate_grant_runs_fixed_connection_once_and_stores_only_key_hash(connection_deployment):
    rt, _, routed, release, _, app, _ = connection_deployment; core = rt.connection_deployments
    assert app['profile'] == PROFILE and core.authorize(app['app_id'], app['publish_key'], ORIGIN)['id'] == app['app_id']
    tables = {row[0] for row in rt.store.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'workflow_connection_deployments' in tables
    if 'workflow_apps' in tables: assert not rt.store.query('SELECT 1 FROM workflow_apps WHERE id=?', (app['app_id'],))
    row = rt.store.query('SELECT key_hash,payload FROM workflow_connection_deployments WHERE id=?', (app['app_id'],))[0]
    assert app['publish_key'] not in row['payload'] and row['key_hash'] == hashlib.sha256(app['publish_key'].encode()).hexdigest()
    job, body = execute(rt, app); result = wait(rt, job)
    assert result['status'] == 'succeeded' and len(routed[3]) == 2
    assert rt.typed_test_controls['seen'][0]['query'] != rt.typed_test_controls['seen'][1]['query']
    assert rt.typed_test_controls['seen'][1]['query'] == rt.typed_test_controls['title']
    replay = core.execute_run(app['app_id'], body, ORIGIN)
    assert replay['run_id'] == job['run_id'] and replay['run_key'] == job['run_key'] and replay['replayed'] and len(routed[3]) == 2
    assert core.read_run(app['app_id'], job['run_id'], job['run_key'], ORIGIN)['status'] == 'succeeded'
    assert not rt.authorized(job['run_id'], job['run_key'])
    with pytest.raises(ValueError): rt.publication.read_run(release['id'], job['run_id'], job['run_key'])
    assert not rt.store.query('SELECT 1 FROM workflow_result_outbox WHERE run_id=?', (job['run_id'],))


@pytest.mark.parametrize('value', [[], ['*'], ['null'], ['file:///tmp/app'], ['https://user:pass@app.example'],
                                  ['https://app.example/path'], ['https://app.example?token=value'], ['https://app.example#private'],
                                  ['https://app.example/%2e'], ['https://app.example', None]])
def test_exact_origin_policy_rejects_ambiguous_or_private_origin_syntax(value):
    with pytest.raises(ValueError): origins(value)


@pytest.mark.parametrize('field,value', [('sharing_authority', False), ('sharing_authority', 1), ('run_authority', False),
                                       ('sharing_notice', PUBLIC_SHARE), ('run_notice', PUBLIC_RUN)])
def test_publication_or_previous_run_consent_cannot_supply_app_consent(connection_deployment, field, value):
    rt, _, routed, _, _, app, _ = connection_deployment
    body = run_body(rt.connection_deployments.prepare_run(app['app_id'], ORIGIN)); body[field] = value
    with pytest.raises(ValueError): rt.connection_deployments.execute_run(app['app_id'], body, ORIGIN)
    assert not routed[3]


@pytest.mark.parametrize('change', ['origin', 'key', 'other_allowed_origin', 'other_app'])
def test_publish_key_ticket_and_run_capability_are_app_origin_scoped(connection_deployment, change):
    rt, owner, routed, release, _, app, _ = connection_deployment; core = rt.connection_deployments
    prepared = core.prepare_run(app['app_id'], ORIGIN)
    if change == 'origin':
        with pytest.raises(ValueError): core.authorize(app['app_id'], app['publish_key'], 'https://unregistered.example')
    elif change == 'key':
        with pytest.raises(ValueError): core.authorize(app['app_id'], 'cpk_' + '0' * 43, ORIGIN)
    elif change == 'other_allowed_origin':
        with pytest.raises(ValueError): core.execute_run(app['app_id'], run_body(prepared), OTHER)
        job = core.execute_run(app['app_id'], run_body(prepared), ORIGIN); wait(rt, job)
        with pytest.raises(ValueError): core.read_run(app['app_id'], job['run_id'], job['run_key'], OTHER)
        return
    else:
        second, _ = issue(rt, owner, release); other_app = second['deployment']
        with pytest.raises(ValueError): core.execute_run(other_app['app_id'], run_body(prepared), ORIGIN)
    assert not routed[3]


@pytest.mark.parametrize('boundary', ['deployment', 'publication', 'issuer', 'controls', 'proof'])
def test_live_revocation_or_proof_change_stops_next_agent_without_replay(connection_deployment, boundary):
    from agent_market.execution_authority import controls, set_controls
    rt, owner, routed, release, proof, app, _ = connection_deployment; core = rt.connection_deployments
    def change(_):
        if boundary == 'deployment': core.revoke(release['id'], app['app_id'], app['revision'], owner)
        elif boundary == 'publication': rt.publication.revoke(release['id'], release['revision'], owner)
        elif boundary == 'issuer':
            with rt.store.tx() as db: db.execute('UPDATE admin_users SET active=0 WHERE id=?', (owner,))
        elif boundary == 'proof':
            with rt.store.tx() as db: db.execute('DELETE FROM workflow_checkpoints WHERE run_id=?', (proof['run_id'],))
        else:
            for enabled in (False, True):
                policy = controls(rt.store)
                set_controls(rt.store, {'invoke_enabled': enabled, 'workflow_enabled': True, 'delivery_enabled': policy['delivery_enabled'], 'revision': policy['revision']}, owner)
    prepared = core.prepare_run(app['app_id'], ORIGIN); routed[5]['primary.example'] = change
    job = core.execute_run(app['app_id'], run_body(prepared), ORIGIN)
    assert wait(rt, job)['status'] != 'succeeded' and routed[3] == ['primary.example']


@pytest.mark.parametrize('change', ['proof', 'provider', 'controls'])
def test_metadata_read_remains_separate_from_current_invocation_readiness(connection_deployment, change):
    from agent_market.execution_authority import controls, set_controls
    rt, owner, _, _, proof, app, _ = connection_deployment; core = rt.connection_deployments
    job, _ = execute(rt, app); wait(rt, job)
    if change == 'proof':
        with rt.store.tx() as db: db.execute('DELETE FROM workflow_checkpoints WHERE run_id=?', (proof['run_id'],))
    elif change == 'provider':
        with rt.store.tx() as db: db.execute('UPDATE capability_evidence SET expires=0')
    else:
        for enabled in (False, True):
            policy = controls(rt.store); set_controls(rt.store, {'invoke_enabled': enabled, 'workflow_enabled': True, 'delivery_enabled': policy['delivery_enabled'], 'revision': policy['revision']}, owner)
    assert core.authorize(app['app_id'], app['publish_key'], ORIGIN, read=True)['id'] == app['app_id']
    assert core.read_run(app['app_id'], job['run_id'], job['run_key'], ORIGIN)['status'] == 'succeeded'
    with pytest.raises(ValueError): core.prepare_run(app['app_id'], ORIGIN)


def test_consumed_export_proposal_cannot_reissue_after_revocation(connection_deployment):
    rt, owner, _, release, _, app, proposal = connection_deployment
    with pytest.raises(ValueError): rt.connection_deployments.issue(release['id'], proposal, owner)
    rt.connection_deployments.revoke(release['id'], app['app_id'], app['revision'], owner)
    with pytest.raises(ValueError): rt.connection_deployments.issue(release['id'], proposal, owner)
    assert len(rt.store.query('SELECT 1 FROM workflow_connection_deployments')) == 1


@pytest.mark.parametrize('declaration', [{}, {'deployment_authority': False, 'deployment_notice': GRANT_NOTICE},
                                      {'deployment_authority': 1, 'deployment_notice': GRANT_NOTICE},
                                      {'deployment_authority': True, 'deployment_notice': PUBLIC_SHARE}])
def test_deployment_requires_independent_current_explicit_authority(connection_deployment, declaration):
    rt, owner, _, release, _, _, _ = connection_deployment; core = rt.connection_deployments
    plan = core.prepare_admin(release['id'], {'allowed_origins': [ORIGIN], 'minute_limit': 10, 'day_limit': 500, 'ttl_seconds': 1800}, owner)
    with pytest.raises(ValueError): core.issue(release['id'], {'proposal': plan['proposal'], 'signature': plan['signature'], **declaration}, owner)
    assert len(rt.store.query('SELECT 1 FROM workflow_connection_deployments')) == 1


def test_valid_second_ticket_cannot_rebind_an_already_accepted_nonce(connection_deployment):
    rt, _, routed, _, _, app, _ = connection_deployment; core = rt.connection_deployments
    first, body = execute(rt, app); wait(rt, first); calls = len(routed[3])
    second = run_body(core.prepare_run(app['app_id'], ORIGIN)); second['proposal']['nonce'] = body['proposal']['nonce']
    second['signature'] = rt.authority.signature(second['proposal'])
    with pytest.raises((ValueError, WorkflowError)): core.execute_run(app['app_id'], second, ORIGIN)
    assert len(routed[3]) == calls


def test_independent_deployment_issuance_is_bounded_per_owner(connection_deployment):
    rt, owner, routed, release, _, _, _ = connection_deployment
    for _ in range(19): issue(rt, owner, release)
    with pytest.raises(ValueError, match='limit'): issue(rt, owner, release)
    assert len(rt.store.query('SELECT 1 FROM workflow_connection_deployments')) == 20 and not routed[3]


def test_restore_revokes_app_and_publication_without_exporting_keys_or_private_proof(connection_deployment, tmp_path):
    from pathlib import Path
    from agent_market.gateway.store import Store
    from agent_market.workflow_backup import backup, restore
    from agent_market.workflows import WorkflowRuntime
    rt, _, _, _, _, app, _ = connection_deployment
    snapshot = tmp_path / 'snapshot'; backup(rt.store._path, snapshot)
    target = tmp_path / 'restored.db'; restore(snapshot, target)
    inventory = json.loads(Path(str(target) + '.restored-inventory.json').read_text())
    records = inventory['items']['workflow_connection_deployments']['records']
    assert records[0]['id'] == app['app_id'] and records[0]['revision'] == 1 and records[0]['active'] == 1
    text = json.dumps(inventory)
    for private in ('publish_key', app['publish_key'], ORIGIN, 'definition_hash', 'key_hash', 'proof_hash', 'publication-reviewer', 'owner'):
        assert private not in text
    store = Store(str(target)); runtime = WorkflowRuntime(store, rt.proxy, rt.courier)
    try:
        row = store.query('SELECT active,revision,revoked FROM workflow_connection_deployments WHERE id=?', (app['app_id'],))[0]
        assert row['active'] == 0 and row['revision'] == 2 and row['revoked']
        assert store.query('SELECT active FROM workflow_publication_grants')[0][0] == 0
        with pytest.raises(ValueError): runtime.connection_deployments.authorize(app['app_id'], app['publish_key'], ORIGIN, read=True)
        with store.tx() as db: db.execute('UPDATE workflow_connection_deployments SET active=1 WHERE id=?', (app['app_id'],))
        with pytest.raises(ValueError): runtime.connection_deployments.metadata(app['app_id'], ORIGIN)
    finally: store._db.close()


def test_publication_revocation_requests_cancellation_for_all_its_deployments(connection_deployment, monkeypatch):
    rt, owner, _, release, _, app, _ = connection_deployment
    second, _ = issue(rt, owner, release)
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    one, _ = execute(rt, app); two, _ = execute(rt, second['deployment'])
    rt.publication.revoke(release['id'], release['revision'], owner)
    for job in (one, two):
        assert rt.store.query('SELECT cancel_requested FROM workflow_runs WHERE id=?', (job['run_id'],))[0][0] == 1
    assert len(rt.store.query('SELECT 1 FROM workflow_connection_deployments')) == 2


def test_generic_runtime_cannot_infer_deployment_authority_or_enable_automation(connection_deployment):
    rt, _, routed, release, _, app, _ = connection_deployment
    workflow = rt.connection_deployments.current(app['app_id'], ORIGIN)['workflow']
    with pytest.raises(WorkflowError): rt.submit(workflow, public=True, principal=rt.principal('public', app['app_id'], workflow['id']))
    with pytest.raises(WorkflowError): rt.save_schedule(workflow['id'], {'mode': 'scheduled', 'enabled': True})
    assert not routed[3]


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
if phase=='source-checkpoint':
 checkpoint=runtime.persistence.checkpoint
 def saved(*args,**kwargs):
  result=checkpoint(*args,**kwargs)
  if args[3]=='search-1':die()
  return result
 runtime.persistence.checkpoint=saved
runtime._execute(run_id)
raise SystemExit('Expected crash boundary was not reached')
'''


@pytest.mark.parametrize('phase', ['source-checkpoint', 'docs-dispatched'])
def test_real_sigkill_deployment_recovery_preserves_origin_scope_and_no_replay(connection_deployment, monkeypatch, tmp_path, phase):
    rt, _, routed, _, _, app, _ = connection_deployment
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    job, _ = execute(rt, app); audit = tmp_path / 'calls.txt'
    child = subprocess.run([sys.executable, '-B', '-c', CHILD, rt.store._path, job['run_id'], str(audit), phase], capture_output=True, timeout=15)
    assert child.returncode == -signal.SIGKILL, child.stderr.decode()[-1600:]
    before = audit.read_text().splitlines(); deadline = rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?', (job['run_id'],))[0][0]
    with rt.store.tx() as db: db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?', (job['run_id'],))
    rt.persistence.recover(); rt._execute(job['run_id']); result = rt.get(job['run_id'])
    if phase == 'source-checkpoint':
        assert before == ['primary.example'] and len(routed[3]) == 1 and routed[3][0] != 'primary.example'
        assert result['status'] == 'succeeded', result
    else:
        assert len(before) == 2 and not routed[3]
        assert result['status'] == 'failed' and result['execution_outcome'] == 'unknown'
        for _ in range(2): rt.persistence.recover(); rt._execute(job['run_id'])
        assert not routed[3]
    assert len(before) + len(routed[3]) == 2
    assert rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?', (job['run_id'],))[0][0] == deadline
