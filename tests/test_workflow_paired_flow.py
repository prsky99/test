"""Isolated controlled source reuse, explicit purpose and durable dispatch tests."""
import copy
import json
import signal
import subprocess
import sys
import time

import pytest

from agent_market.capability_registry import canonical, digest
from agent_market.workflow_composer import Composer
from agent_market import workflow_paired_flow as pairs
from agent_market.workflows import WorkflowError, public_template
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_runtime import wait


def saved_pair(rt, *, owner='internal'):
    draft = Composer(rt).generate({'prompt': 'Python news and documentation search'}, owner)
    workflow = copy.deepcopy(draft['workflow'])
    start, source, a = workflow['nodes']
    b = copy.deepcopy(a); b['id'] = 'search-3'
    candidates = [candidate for candidate in draft['proposal']['candidates']
                  if candidate['contract'] == 'docs.search.v1' and candidate['pin']['resource_id'] != a['resource_id']]
    pin = candidates[0]['pin']
    b['resource_id'] = pin['resource_id']
    b['data']['tool'] = pin['approval']['tool']
    value = b['data']['composition']['payload']; value['pin'] = pin
    b['data']['composition']['mac'] = rt.authority.signature(value)
    targets = pairs.build(rt.composer, source, [a, b], owner=owner, nonce='a' * 32)
    workflow['nodes'] = [start, source, *targets]
    workflow['edges'] = [{'id': identity, 'source': parent, 'target': target} for identity, parent, target in pairs.EDGES]
    workflow['id'] = rt.store.create_workflow(workflow)
    return rt.store.get_workflow(workflow['id'])


def submit_pair(rt, workflow, **kwargs):
    return rt.submit(workflow, pair_authority=True, pair_notice=pairs.RUN_NOTICE, **kwargs)


def checkpoint(rt, run_id, node_id):
    return json.loads(rt.store.query('SELECT payload FROM workflow_checkpoints WHERE run_id=? AND node_id=?',
                                    (run_id, node_id))[0]['payload'])


def test_one_source_two_targets_receive_identical_actual_query_and_signed_context(typed_routing):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_pair(rt)
    result = wait(rt, submit_pair(rt, workflow, idempotency='one-pair'))
    assert result['status'] == result['execution_outcome'] == 'succeeded', result
    assert calls[0] == 'primary.example' and len(calls) == 3 and len(set(calls)) == 3
    assert rt.typed_test_controls['news_calls'] == 1
    actual = rt.typed_test_controls['seen']
    assert actual[1] == actual[2] == {'query': 'Python asynchronous task documentation', 'language': 'en', 'limit': 3}
    source = checkpoint(rt, result['run_id'], 'search-1')
    a, b = [checkpoint(rt, result['run_id'], identity) for identity in pairs.IDS[2:]]
    assert a['typed_input']['source_checkpoint_hash'] == b['typed_input']['source_checkpoint_hash'] == digest(source)
    assert a['typed_input']['pair_hash'] == b['typed_input']['pair_hash']
    assert a['typed_input']['side'] == 'a' and b['typed_input']['side'] == 'b'
    assert a['record']['input'] == b['record']['input'] == actual[1]
    assert not any(edge['source'] == 'search-2' for edge in workflow['edges'])
    assert not any(transfer['source_id'] == 'search-2' and transfer['target_id'] == 'search-3'
                   for transfer in result['data_flow_trace'])
    target_transfers = [transfer for transfer in result['data_flow_trace'] if transfer['target_id'] in pairs.IDS[2:]]
    assert len(target_transfers) == 2
    assert all(transfer['passed_data_summary'] == 'Verified news title used as the documentation query.'
               and transfer['size_bytes'] == len(canonical(actual[1]).encode()) for transfer in target_transfers)
    envelope = json.loads(rt.store.query('SELECT payload FROM workflow_run_authority WHERE run_id=?', (result['run_id'],))[0][0])
    assert envelope['principal']['payload']['controlled_pair'] == pairs.expected_scope(workflow)
    assert envelope['grant_id'] is None and not rt.store.query('SELECT * FROM workflow_result_outbox WHERE run_id=?', (result['run_id'],))
    replay = submit_pair(rt, workflow, idempotency='one-pair')
    assert replay['replayed'] and replay['run_id'] == result['run_id'] and len(calls) == 3


@pytest.mark.parametrize('authority,notice', [(False, None), (True, None), (True, 'workflow-composer-flow-v1'),
                                              (1, pairs.RUN_NOTICE)])
def test_generic_or_reused_single_target_consent_cannot_admit_pair(typed_routing, authority, notice):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_pair(rt)
    with pytest.raises(WorkflowError):
        rt.submit(workflow, pair_authority=authority, pair_notice=notice)
    assert not calls and not rt.store.query('SELECT id FROM workflow_runs WHERE workflow_id=?', (workflow['id'],))


@pytest.mark.parametrize('source', ['public', 'schedule', 'event', 'webapp', 'verification'])
def test_public_automatic_and_deployment_sources_are_denied(typed_routing, source):
    rt, _, _, calls, *_ = typed_routing
    with pytest.raises(WorkflowError):
        submit_pair(rt, saved_pair(rt), source=source, public=source == 'public')
    assert not calls


@pytest.mark.parametrize('option', ['operator', 'wrong_owner', 'extended', 'fallback'])
def test_pair_scope_cannot_borrow_role_owner_or_execution_budget(typed_routing, option):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_pair(rt)
    kwargs = {}
    if option == 'operator':
        kwargs['principal'] = rt.principal('admin', 'internal', workflow['id'], role='operator')
    elif option == 'wrong_owner':
        kwargs['principal'] = rt.principal('admin', 'another', workflow['id'], role='superadmin')
    elif option == 'extended':
        kwargs.update(execution_profile='extended', execution_budget_notice='workflow-budget-v1')
    else:
        kwargs.update(allow_fallback=True, fallback_notice='readonly-fallback-v1')
    with pytest.raises(WorkflowError):
        submit_pair(rt, workflow, **kwargs)
    assert not calls


@pytest.mark.parametrize('attack', ['side', 'source_hash', 'input', 'pin', 'mac', 'order', 'fake_edge',
                                    'credential', 'output_select', 'disabled', 'third_target'])
def test_purpose_and_exact_shape_tamper_fails_before_any_provider(typed_routing, attack):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_pair(rt)
    a = workflow['nodes'][2]; value = a['data']['composition']['payload']
    if attack == 'side': value['side'] = 'b'
    elif attack == 'source_hash': value['pair']['source_binding_hash'] = '0' * 64
    elif attack == 'input': a['data']['input']['query'] = 'Different public objective'
    elif attack == 'pin': value['pin']['resource_id'] = workflow['nodes'][3]['resource_id']
    elif attack == 'mac': a['data']['composition']['mac'] = 'bad'
    elif attack == 'order': workflow['nodes'][2:] = list(reversed(workflow['nodes'][2:]))
    elif attack == 'fake_edge': workflow['edges'].append({'id': 'a-b', 'source': 'search-2', 'target': 'search-3'})
    elif attack == 'credential': a['data']['credential_refs'] = {'token': 'private'}
    elif attack == 'output_select': a['data']['output_select'] = {'path': 'items'}
    elif attack == 'disabled': a['disabled'] = True
    else: workflow['nodes'].append(copy.deepcopy(a) | {'id': 'extra'})
    with pytest.raises(WorkflowError):
        submit_pair(rt, workflow)
    assert not calls


@pytest.mark.parametrize('title', [None, 'x' * 501, 'https://unsafe.example', 'Bearer synthetic-token', '{{ $prev.output }}'])
def test_empty_or_unsafe_source_stops_both_targets(typed_routing, title):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_pair(rt); rt.typed_test_controls['title'] = title
    result = wait(rt, submit_pair(rt, workflow))
    assert result['status'] == 'failed' and calls == ['primary.example']
    assert not rt.store.query("SELECT * FROM workflow_execution_attempts WHERE run_id=? AND node_id IN ('search-2','search-3')", (result['run_id'],))


def test_unknown_source_never_invokes_either_documentation_target(typed_routing):
    rt, _, _, calls, modes, *_ = typed_routing
    workflow = saved_pair(rt); modes['primary.example'] = 'unknown'
    result = wait(rt, submit_pair(rt, workflow))
    assert result['status'] == 'failed' and result['execution_outcome'] == 'unknown'
    assert calls == ['primary.example']
    assert not rt.store.query("SELECT * FROM workflow_execution_attempts WHERE run_id=? AND node_id IN ('search-2','search-3')", (result['run_id'],))


def test_cancellation_during_a_stops_b_and_does_not_grant_delivery(typed_routing):
    rt, _, _, calls, _, hooks, _ = typed_routing
    workflow = saved_pair(rt)
    a_host = rt.store.resource(workflow['nodes'][2]['resource_id'])['url'].split('/')[2]

    def cancel_current(_):
        run_id = rt.store.query("SELECT id FROM workflow_runs WHERE workflow_id=? AND status='running'", (workflow['id'],))[0][0]
        rt.cancel(run_id)

    hooks[a_host] = cancel_current
    result = wait(rt, submit_pair(rt, workflow))
    assert result['status'] == 'cancelled' and calls == ['primary.example', a_host]
    assert checkpoint(rt, result['run_id'], 'search-3')['record']['status'] == 'cancelled'
    assert not rt.store.query("SELECT * FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-3'", (result['run_id'],))
    assert not rt.store.query('SELECT * FROM workflow_result_outbox WHERE run_id=?', (result['run_id'],))


@pytest.mark.parametrize('mode', ['unknown', 'invalid'])
def test_uncertain_or_failed_a_never_calls_b(typed_routing, mode):
    rt, _, _, calls, modes, *_ = typed_routing
    workflow = saved_pair(rt)
    a_host = rt.store.resource(workflow['nodes'][2]['resource_id'])['url'].split('/')[2]
    modes[a_host] = mode
    result = wait(rt, submit_pair(rt, workflow))
    assert result['status'] == 'failed' and calls == ['primary.example', a_host]
    record = checkpoint(rt, result['run_id'], 'search-3')['record']
    assert record['status'] in ('blocked', 'failed') and record['error_code'] == 'POLICY_DENIED'
    assert not rt.store.query("SELECT * FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-3'", (result['run_id'],))


def test_b_dispatch_rechecks_a_certainty_after_b_preparation(typed_routing, monkeypatch):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_pair(rt); original = rt.persistence.prepare

    def change_certainty(*args, **kwargs):
        original(*args, **kwargs)
        if args[3] == 'search-3':
            with rt.store.tx() as db:
                db.execute("UPDATE workflow_execution_attempts SET status='unknown' WHERE run_id=? AND node_id='search-2'", (args[0],))

    monkeypatch.setattr(rt.persistence, 'prepare', change_certainty)
    result = wait(rt, submit_pair(rt, workflow))
    assert result['status'] == 'failed' and len(calls) == 2
    record = checkpoint(rt, result['run_id'], 'search-3')['record']
    assert record['status'] in ('blocked', 'failed') and record['error_code'] == 'POLICY_DENIED'
    assert rt.store.query("SELECT status FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-3'", (result['run_id'],))[0][0] == 'failed'


def test_b_dispatch_requires_recorded_start_after_a_observation(typed_routing, monkeypatch):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_pair(rt); prepare = rt.persistence.prepare

    def future_a_observation(*args, **kwargs):
        prepare(*args, **kwargs)
        if args[3] == 'search-3':
            value = checkpoint(rt, args[0], 'search-2')
            # Still within the general five-second observation tolerance, but
            # this recorded A result cannot precede B's already recorded start.
            value['record']['latency_ms'] = 4000
            with rt.store.tx() as db:
                db.execute("UPDATE workflow_checkpoints SET payload=?,signature=? WHERE run_id=? AND node_id='search-2'",
                           (json.dumps(value), rt.authority.signature(value), args[0]))

    monkeypatch.setattr(rt.persistence, 'prepare', future_a_observation)
    result = wait(rt, submit_pair(rt, workflow))
    assert result['status'] == 'failed' and len(calls) == 2
    b = checkpoint(rt, result['run_id'], 'search-3')['record']
    assert b['status'] in ('blocked', 'failed') and b['error_code'] == 'POLICY_DENIED'
    assert rt.store.query("SELECT status FROM workflow_execution_attempts WHERE run_id=? AND node_id='search-3'", (result['run_id'],))[0][0] == 'failed'


def test_current_scope_is_rechecked_after_source_checkpoint(typed_routing, monkeypatch):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_pair(rt); original = rt.composer.resolve_input

    def changed_scope(node, row, snapshot):
        with rt.store.tx() as db:
            authority = json.loads(db.execute('SELECT payload FROM workflow_run_authority WHERE run_id=?', (row['id'],)).fetchone()[0])
            authority['principal']['payload']['controlled_pair']['pair_hash'] = '0' * 64
            authority['principal']['signature'] = rt.authority.signature(authority['principal']['payload'])
            db.execute('UPDATE workflow_run_authority SET payload=?,signature=? WHERE run_id=?',
                       (json.dumps(authority), rt.authority.signature(authority), row['id']))
        return original(node, row, snapshot)

    monkeypatch.setattr(rt.composer, 'resolve_input', changed_scope)
    result = wait(rt, submit_pair(rt, workflow))
    assert result['status'] == 'failed' and calls == ['primary.example']


def test_pause_resume_after_source_revokes_old_review_until_new_pair(typed_routing):
    from agent_market.execution_authority import controls, set_controls
    rt, _, _, calls, _, hooks, _ = typed_routing
    workflow = saved_pair(rt)

    def pause_and_resume(_):
        for enabled in (False, True):
            policy = controls(rt.store)
            set_controls(rt.store, {'invoke_enabled': enabled, 'workflow_enabled': True,
                                    'delivery_enabled': policy['delivery_enabled'], 'revision': policy['revision']}, 1)

    hooks['primary.example'] = pause_and_resume
    result = wait(rt, submit_pair(rt, workflow))
    assert result['status'] == 'failed' and calls == ['primary.example']
    assert not rt.store.query("SELECT * FROM workflow_execution_attempts WHERE run_id=? AND node_id IN ('search-2','search-3')", (result['run_id'],))
    # Historical proof is independent of the current revocation epoch.
    pairs.verify_definition(rt.composer, workflow, now=rt.store.query('SELECT created FROM workflow_runs WHERE id=?', (result['run_id'],))[0][0])
    with pytest.raises(WorkflowError, match='controls changed'):
        submit_pair(rt, workflow)
    hooks.clear(); calls.clear()
    fresh = saved_pair(rt)
    assert wait(rt, submit_pair(rt, fresh))['status'] == 'succeeded'
    assert len(calls) == 3


@pytest.mark.parametrize('reviewed_at', [True, '1', None, -1, 'future'])
def test_signed_review_time_must_be_finite_numeric_and_not_after_admission(typed_routing, reviewed_at):
    rt, *_ = typed_routing
    workflow = saved_pair(rt); now = time.time()
    timestamp = now + 60 if reviewed_at == 'future' else reviewed_at
    for target in workflow['nodes'][2:]:
        binding = target['data']['composition']['payload']
        binding['pair']['reviewed_at'] = timestamp
        target['data']['composition']['mac'] = rt.authority.signature(binding)
    with pytest.raises(ValueError):
        pairs.verify_definition(rt.composer, workflow, now=now)


def test_private_pair_cannot_publish_schedule_or_register_delivery(typed_routing):
    from agent_market.workflow_comparison import Comparison, ComparisonError
    from agent_market.workflow_resolved_evidence import ResolvedEvidence
    from agent_market.workflow_webapp import export_config
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_pair(rt)
    result = wait(rt, submit_pair(rt, workflow))
    assert result['status'] == 'succeeded'
    assert public_template(workflow | {'is_template': 1}) is None
    with pytest.raises(ValueError, match='private'):
        Composer(rt).validate_publish(workflow, result['run_id'])
    with Comparison(rt).reader() as store:
        with pytest.raises(ComparisonError): Comparison(rt).load(store, result['run_id'], 'docs.search.v1')
        with pytest.raises(ComparisonError): ResolvedEvidence(rt).load_typed(store, result['run_id'])
    for mode in ('scheduled', 'event_driven'):
        with pytest.raises(WorkflowError): rt.save_schedule(workflow['id'], {'mode': mode, 'enabled': True})
    with pytest.raises(WorkflowError): rt.save_schedule(workflow['id'], {'mode': 'manual', 'delivery_authority': True})
    with pytest.raises(WorkflowError): rt.register_destination(workflow['id'], {})
    with pytest.raises(ValueError, match='Publish'):
        export_config(workflow)
    assert len(calls) == 3


def test_retained_definition_verification_is_offline_and_time_scoped(typed_routing, monkeypatch):
    rt, *_ = typed_routing
    workflow = saved_pair(rt)

    def forbidden(*args, **kwargs):
        raise AssertionError('Historical verification must not refresh the catalog.')

    monkeypatch.setattr(rt.fallback, 'pin', forbidden)
    monkeypatch.setattr(rt.composer, 'validate_node', forbidden)
    binding, source = pairs.verify_definition(rt.composer, workflow, now=time.time())
    assert binding['pair']['profile'] == pairs.PROFILE and source['id'] == 'search-1'


CHILD = r'''
import json,os,signal,sys,httpx
from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowRuntime
from agent_market.concierge.proxy import McpProxy
from tests.test_mcp_proxy import MockRemoteMcp
from tests.test_workflow_fallback import tool,output
path,run_id,audit,phase,bhost=sys.argv[1:]
remote=MockRemoteMcp([tool()],call_result=output());original=remote.handle_request
def die():os.kill(os.getpid(),signal.SIGKILL)
def handle(request):
 body=json.loads(request.content or '{}');news=request.url.host=='primary.example'
 remote.tools=[tool('news.search.v1') if news else tool()]
 if body.get('method')=='tools/call':
  with open(audit,'a') as out:out.write(request.url.host+'\n');out.flush();os.fsync(out.fileno())
  if phase=='b-dispatched' and request.url.host==bhost:die()
  remote.call_result=output('news.search.v1' if news else 'docs.search.v1')
  if news:remote.call_result['structuredContent']['items'][0]['title']='Python asynchronous task documentation'
 return original(request)
remote.handle_request=handle
store=Store(path);client=httpx.Client(transport=remote)
runtime=WorkflowRuntime(store,McpProxy(store,allow_private=True,http=client))
if phase=='before-b':
 checkpoint=runtime.persistence.checkpoint
 def saved(*args,**kwargs):
  result=checkpoint(*args,**kwargs)
  if args[3]=='search-2':die()
  return result
 runtime.persistence.checkpoint=saved
runtime._execute(run_id)
raise SystemExit('Expected crash boundary was not reached')
'''


@pytest.mark.parametrize('phase', ['before-b', 'b-dispatched'])
def test_real_sigkill_recovery_never_repeats_source_or_dispatched_targets(typed_routing, monkeypatch, tmp_path, phase):
    rt, _, _, calls, *_ = typed_routing
    workflow = saved_pair(rt)
    monkeypatch.setattr(rt, 'launch', lambda _: None)
    job = submit_pair(rt, workflow, idempotency='hard-kill-pair')
    audit = tmp_path / 'pair-calls.txt'
    b_host = rt.store.resource(workflow['nodes'][3]['resource_id'])['url'].split('/')[2]
    child = subprocess.run([sys.executable, '-B', '-c', CHILD, rt.store._path, job['run_id'], str(audit), phase, b_host],
                           capture_output=True, timeout=15)
    assert child.returncode == -signal.SIGKILL, child.stderr.decode()[-1600:]
    before = audit.read_text().splitlines()
    deadline = rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?', (job['run_id'],))[0][0]
    with rt.store.tx() as db: db.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=?', (job['run_id'],))
    rt.persistence.recover(); rt._execute(job['run_id'])
    result = rt.get(job['run_id'])
    assert before[0] == 'primary.example' and before.count('primary.example') == 1
    if phase == 'before-b':
        assert len(before) == 2 and calls == [b_host] and result['status'] == 'succeeded'
        assert len(rt.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?', (job['run_id'],))) == 4
    else:
        assert len(before) == 3 and not calls
        assert result['status'] == 'failed' and result['execution_outcome'] == 'unknown'
        for _ in range(2): rt.persistence.recover(); rt._execute(job['run_id'])
        assert not calls
    assert len(before) + len(calls) == 3
    assert rt.store.query('SELECT deadline FROM workflow_runs WHERE id=?', (job['run_id'],))[0][0] == deadline
