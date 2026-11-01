"""Private product compiler tests use exact synthetic MCP schemas and local DBs."""
import copy
import json
import time
from types import SimpleNamespace

import pytest

from agent_market.capability_registry import Registry
from agent_market.collector import usage
from agent_market.gateway.admin_auth import session_reference
from agent_market.workspace_access import SessionActor,WorkspaceAccess,WorkspaceDenied,WorkspaceConflict,WorkspaceInvalid
from agent_market.workspace_execution import WorkspaceExecution,NOTICE as PRIVATE_NOTICE
from agent_market.workspace_release import WorkspaceReleases
from agent_market.workflows import runtime_for
from agent_market.workflow_product_composer import ProductComposer,NOTICE
from agent_market.workflow_product_semantics import CONTRACT_ID
from tests.test_workspace_execution_api import private_api
from tests.test_workflow_product_semantics import product_fixture,product_tool


@pytest.fixture
def product_world(private_api):
    w=private_api;inputs,output,_=product_fixture();tool=product_tool();w.remote.tools=[tool];w.remote.call_result={'structuredContent':output}
    compact=usage.compact_tools([tool]);w.store.record_usage(w.rid,compact,usage.tools_hash(compact),{},None,{'ok':True},full_tools=[tool])
    registry=Registry(w.store);version=registry.approve(w.store.resource(w.rid),CONTRACT_ID,tool['name']);now=time.time()
    registry.record(version,scope='execution',outcome='succeeded',started=now,finished=time.time())
    registry.record(version,scope='contract',contract_id=CONTRACT_ID,outcome='succeeded',started=time.time(),finished=time.time())
    from agent_market.concierge.proxy import McpProxy
    import httpx
    def provider(request):
        method=json.loads(request.content or b'{}').get('method');w.calls.append(method)
        if method=='tools/list' and w.control['during_list']:w.control['during_list']()
        return w.remote.handle_request(request)
    proxy=McpProxy(w.store,allow_private=True,http=httpx.Client(transport=httpx.MockTransport(provider)))
    access=WorkspaceAccess(w.store,runtime_for(w.store).key);execution=WorkspaceExecution(access,proxy)
    composer=ProductComposer(execution);execution.authority_guard=composer.guard_ticket
    actor=SessionActor(1,session_reference(w.headers['owner']['Authorization'][7:]))
    return SimpleNamespace(w=w,composer=composer,execution=execution,access=composer.access,actor=actor,inputs=inputs,output=output,version=version,ws=w.ws['id'])


def saved(x):
    plan=x.composer.prepare(x.ws,{'resource_id':x.w.rid,'input':x.inputs},x.actor)
    result=x.composer.save(x.ws,{'proposal':plan['proposal'],'signature':plan['signature'],'name':'Private typed products','description':''},x.actor)
    return result,(x.ws,result['draft_id'],result['snapshot_id'])


def perform_test(x,args):
    ticket=x.composer.prepare_test(*args,x.actor)
    return x.composer.test(*args,{'ticket_id':ticket['ticket_id'],'authorized':True,'notice':NOTICE},x.actor),ticket


def test_compile_is_atomic_private_nonexecuting_and_immutable_sidecar_bound(product_world):
    x=product_world;before=len(x.w.calls);result,args=saved(x)
    assert len(x.w.calls)==before
    snapshot=x.access.version(*args,x.actor)
    assert snapshot['executable'] is False and snapshot['published'] is False
    assert snapshot['snapshot']['definition']['nodes'][1]['data']['input']==x.inputs
    rows=x.w.store.query('SELECT * FROM workspace_product_compositions WHERE snapshot_id=?',(args[2],));assert len(rows)==1
    sidecar=json.loads(rows[0]['payload']);assert sidecar['snapshot_hash'] and sidecar['release_allowed'] is False
    assert x.w.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]==0


def test_actual_contract_pass_is_separate_from_transport_and_does_not_certify_quality(product_world):
    x=product_world;_,args=saved(x);before=x.w.calls.count('tools/call');result,ticket=perform_test(x,args)
    assert result['run']['status']=='succeeded' and result['contract_proof']['outcome']=='passed',result
    proof=result['contract_proof'];assert proof['normalized']['normalized'][0]['measurements'][0]['normalized_quantity']=={'value':'1','unit':'kg'}
    assert proof['normalized']['origin']=='retained_private_execution' and proof['normalized']['claims']['live_execution'] is True
    assert proof['source_verified'] is proof['expert_reviewed'] is proof['automatic_ranking'] is False
    assert x.w.calls.count('tools/call')==before+1
    replay=x.composer.test(*args,{'ticket_id':ticket['ticket_id'],'authorized':True,'notice':NOTICE},x.actor)
    assert replay['replayed'] and replay['run']['id']==result['run']['id'] and x.w.calls.count('tools/call')==before+1


def test_protocol_success_with_invalid_product_output_records_failed_contract_only(product_world):
    x=product_world;_,args=saved(x);x.w.remote.call_result={'content':[{'type':'text','text':'No typed evidence'}]}
    result,_=perform_test(x,args)
    assert result['run']['status']=='succeeded' and result['contract_proof']['outcome']=='failed'
    assert result['contract_proof']['normalized'] is None


def test_current_approval_withdrawal_during_list_blocks_actual_call(product_world):
    x=product_world;_,args=saved(x);before=x.w.calls.count('tools/call')
    def withdraw():
        with x.w.store.tx() as db:db.execute('DELETE FROM capability_approvals WHERE version_id=?',(x.version['id'],))
    x.w.control['during_list']=withdraw
    result,_=perform_test(x,args)
    assert result['run']['status']!='succeeded' and x.w.calls.count('tools/call')==before
    assert result['contract_proof']['outcome']=='failed'


@pytest.mark.parametrize('change',['missing_execution','missing_contract','wrong_schema','inactive','approval_replaced'])
def test_unverified_or_changed_agent_is_not_a_compiler_candidate(product_world,change):
    x=product_world;plan=x.composer.prepare(x.ws,{'resource_id':x.w.rid,'input':x.inputs},x.actor)
    with x.w.store.tx() as db:
        if change=='missing_execution':db.execute("DELETE FROM capability_evidence WHERE scope='execution'")
        elif change=='missing_contract':db.execute("DELETE FROM capability_evidence WHERE scope='contract'")
        elif change=='inactive':db.execute('UPDATE resources SET active=0 WHERE id=?',(x.w.rid,))
        elif change=='approval_replaced':db.execute('UPDATE capability_approvals SET created=created+10')
        else:db.execute("UPDATE resources SET usage_full_tools='[]' WHERE id=?",(x.w.rid,))
    with pytest.raises(WorkspaceDenied):x.composer.save(x.ws,{'proposal':plan['proposal'],'signature':plan['signature'],'name':'Private','description':''},x.actor)
    assert x.w.store.query('SELECT COUNT(*) FROM workspace_product_compositions')[0][0]==0


def test_release_and_copied_graph_bypass_are_denied_by_product_profile(product_world):
    x=product_world;_,args=saved(x);result,_=perform_test(x,args);release=WorkspaceReleases(x.execution)
    with pytest.raises(WorkspaceDenied):release.create(*args,{'run_id':result['run']['id'],'ttl_seconds':3600},x.actor)
    definition=x.access.version(*args,x.actor)['snapshot']['definition']
    draft=x.access.save_draft(x.ws,{'name':'Copied graph','description':'','definition':definition},x.actor)
    snapshot=x.access.create_snapshot(x.ws,draft['id'],{'draft_revision':draft['revision']},x.actor);other=(x.ws,draft['id'],snapshot['id'])
    ticket=x.execution.prepare(*other,{'snapshot_revision':1},x.actor)
    run=x.execution.execute(*other,{'ticket_id':ticket['ticket_id'],'authorized':True,'notice':PRIVATE_NOTICE},x.actor)
    assert run['status']=='succeeded'
    with pytest.raises(WorkspaceDenied):release.create(*other,{'run_id':run['id'],'ttl_seconds':3600},x.actor)


def test_private_scope_and_consent_are_not_inferred(product_world):
    x=product_world;_,args=saved(x);ticket=x.composer.prepare_test(*args,x.actor);before=x.w.calls.count('tools/call')
    with pytest.raises(WorkspaceInvalid):x.composer.test(*args,{'ticket_id':ticket['ticket_id'],'authorized':False,'notice':NOTICE},x.actor)
    viewer=SessionActor(x.w.users['viewer'],session_reference(x.w.headers['viewer']['Authorization'][7:]))
    with pytest.raises(WorkspaceDenied):x.composer.prepare(x.ws,{'resource_id':x.w.rid,'input':x.inputs},viewer)
    assert x.w.calls.count('tools/call')==before


def test_sidecar_tampering_and_transaction_fault_leave_no_partial_compilation(product_world):
    x=product_world;plan=x.composer.prepare(x.ws,{'resource_id':x.w.rid,'input':x.inputs},x.actor)
    with x.w.store.tx() as db:db.execute("CREATE TRIGGER deny_product_insert BEFORE INSERT ON workspace_product_compositions BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    count=x.w.store.query('SELECT COUNT(*) FROM workspace_drafts')[0][0]
    with pytest.raises(WorkspaceConflict):x.composer.save(x.ws,{'proposal':plan['proposal'],'signature':plan['signature'],'name':'Private','description':''},x.actor)
    assert x.w.store.query('SELECT COUNT(*) FROM workspace_drafts')[0][0]==count
    with x.w.store.tx() as db:db.execute('DROP TRIGGER deny_product_insert')
    _,args=saved(x)
    with x.w.store.tx() as db:db.execute("UPDATE workspace_product_compositions SET payload='{}' WHERE snapshot_id=?",(args[2],))
    with pytest.raises(WorkspaceConflict):x.composer.prepare_test(*args,x.actor)
