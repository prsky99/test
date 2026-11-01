"""Direct result transport: authority, byte direction, immutability and recovery."""
from dataclasses import replace
import hashlib
import json
import secrets

import httpx
import pytest

from agent_market.edge_gateway import native, result_transport as results
from agent_market.edge_gateway.auth import canonical, service_mac
from agent_market.edge_gateway.config import EdgeError
from agent_market.edge_gateway.result_view import recipe, MEDIA, RESULT_PATH
from agent_market.workflow_persistence import dispatch_scope
from tests.test_edge_gateway import edge, catalog, ORIGIN, prepare, proposal, claim, service_request
from tests.test_edge_gateway_machine import machine_edge


@pytest.fixture(autouse=True)
def enabled(edge):
    edge.service.config = replace(edge.service.config, native_node_delivery=True, direct_result_delivery=True)


def saved(edge, value=None):
    value = value or {'parts':[{'kind':'text','text':'verified result ' * 200}]}
    request = proposal(edge); grant = prepare(edge, request); binding = claim(edge, grant, request)
    wire = json.dumps(value, ensure_ascii=False, separators=(',',':'))
    body = {'run_id':grant['run_id'],'attempt_id':binding['attempt_id'],
            'wire':wire,'wire_hash':hashlib.sha256(wire.encode()).hexdigest()}
    answer = service_request(edge, 'result', body)
    assert answer.status_code == 200, answer.text
    return body, results.load_result(edge.service, grant['run_id'])


def signed(edge, method, path, value=None, marker='X-Edge-Result-View'):
    raw = canonical(value).encode() if value is not None else b''
    timestamp, nonce = str(int(edge.clock[0])), secrets.token_hex(16)
    return raw, {'Content-Type':'application/json', marker:'v1', 'X-Edge-Time':timestamp,
        'X-Edge-Nonce':nonce, 'X-Edge-Signature':service_mac(edge.config.key, method, path, timestamp, nonce, raw)}


def test_result_callback_is_inbound_and_returns_only_a_small_receipt(edge):
    body, stored = saved(edge)
    assert stored['output']['parts'][0]['text'].startswith('verified result')
    replay = service_request(edge, 'result', body)
    assert replay.status_code == 200 and len(replay.content) < 200
    assert 'wire' not in replay.json() and not edge.calls
    changed = {**body,'wire':'{"parts":[]}'}
    changed['wire_hash'] = hashlib.sha256(changed['wire'].encode()).hexdigest()
    assert service_request(edge, 'result', changed).status_code == 409
    assert results.load_result(edge.service, body['run_id']) == stored


def test_bad_receipt_does_not_finish_or_dispatch(edge):
    request=proposal(edge); grant=prepare(edge,request); binding=claim(edge,grant,request)
    bad={'run_id':grant['run_id'],'attempt_id':binding['attempt_id'],'wire':'{}','wire_hash':'0'*64}
    assert service_request(edge,'result',bad).status_code==400
    assert edge.service.authorized(grant['access_token'],ORIGIN,grant['run_id'])['state']=='dispatch_reserved'
    assert not edge.calls


def test_disabling_new_admissions_preserves_a_claimed_result_callback(edge):
    request=proposal(edge);grant=prepare(edge,request);binding=claim(edge,grant,request)
    edge.service.config=replace(edge.service.config,direct_result_delivery=False)
    wire='{"parts":[{"kind":"text","text":"Already executed"}]}'
    body={'run_id':grant['run_id'],'attempt_id':binding['attempt_id'],'wire':wire,'wire_hash':hashlib.sha256(wire.encode()).hexdigest()}
    assert service_request(edge,'result',body).status_code==200
    assert results.load_result(edge.service,grant['run_id'])['output']['parts'][0]['text']=='Already executed'
    assert not edge.calls


def test_native_reads_a_receipt_locally_instead_of_downloading_output(edge):
    seen=[]; large='A'*40000
    def worker(request):
        seen.append(request)
        assert request.headers['x-edge-result-format']=='receipt'
        run=request.url.path.split('/')[-2]
        binding=edge.service.claim(request.headers['authorization'][7:],ORIGIN,run,json.loads(request.content),'worker')
        wire=json.dumps({'parts':[{'kind':'text','text':large}]},separators=(',',':'))
        digest=hashlib.sha256(wire.encode()).hexdigest()
        results.store_result(edge.service,run,binding['attempt_id'],wire,digest)
        reply={'run_id':run,'state':'succeeded','wire_hash':digest,'backend':'worker'}
        assert len(json.dumps(reply))<220
        return httpx.Response(200,json=reply)
    with httpx.Client(transport=httpx.MockTransport(worker)) as client, dispatch_scope(lambda:None), results.parent_scope('workflow-test','node-1'):
        output=native.execute(edge.store,edge.store.resource(edge.rid),{'message':'Weather?'},scope='receipt-node',http=client)
    assert output['ok'] and output['result']['parts'][0]['text']==large
    assert len(seen)==1 and len(results.parent_results(edge.service,'workflow-test'))==1
    assert not edge.calls


def test_lost_receipt_never_repeats_dispatch_and_saved_result_is_recoverable(edge):
    def worker(request):
        run=request.url.path.split('/')[-2]
        binding=edge.service.claim(request.headers['authorization'][7:],ORIGIN,run,json.loads(request.content),'worker')
        wire='{"parts":[{"kind":"text","text":"Saved"}]}'
        results.store_result(edge.service,run,binding['attempt_id'],wire,hashlib.sha256(wire.encode()).hexdigest())
        raise httpx.ReadTimeout('Lost receipt',request=request)
    with httpx.Client(transport=httpx.MockTransport(worker)) as client,dispatch_scope(lambda:None):
        result=native.execute(edge.store,edge.store.resource(edge.rid),{'message':'Weather?'},scope='lost',http=client)
        assert result['ok'] and result['result']['parts'][0]['text']=='Saved'
        with pytest.raises(Exception):
            native.execute(edge.store,edge.store.resource(edge.rid),{'message':'Weather?'},scope='lost',http=client)
    assert not edge.calls


def test_real_workflow_result_handler_preserves_run_key_and_sends_a_recipe(edge,monkeypatch):
    body,source=saved(edge)
    run_id='wr_'+'c'*32
    with results.parent_scope(run_id,'node-1'):results.link_parent(edge.service,body['run_id'])
    monkeypatch.setattr(edge.front.workflows,'authorized',lambda rid,key:rid==run_id and key=='private-key')
    monkeypatch.setattr(edge.front.workflows,'get',lambda rid:{'run_id':rid,'status':'succeeded','node_results':[{'data':source['output']}]})
    path='/api/workflows/runs/'+run_id
    _,headers=signed(edge,'GET',path); headers['X-Workflow-Key']='private-key'
    response=edge.client.get(path,headers=headers)
    assert response.status_code==200,response.text
    assert response.headers['content-type']==MEDIA
    assert 'verified result '*200 not in response.text
    assert body['wire_hash'] in response.text
    _,headers=signed(edge,'GET',path);headers['X-Workflow-Key']='other-key'
    denied=edge.client.get(path,headers=headers)
    assert denied.status_code in (401,403,404)
    assert body['wire_hash'] not in denied.text


def test_synchronous_webapp_post_runs_once_and_provides_same_result_recovery(edge):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from agent_market.edge_gateway.result_view import install
    run_id='wpr_'+'d'*32
    body,source=saved(edge)
    with results.parent_scope(run_id,'node-1'):results.link_parent(edge.service,body['run_id'])
    app=FastAPI();calls=[]
    @app.post('/api/workflow-apps/app/runs')
    async def run(request:Request):
        assert request.headers.get('authorization')=='Bearer private-app-capability'
        assert await request.json()=={'approved':True}
        calls.append(True)
        from fastapi.responses import JSONResponse
        response=JSONResponse({'run':{'id':run_id,'status':'succeeded','output':source['output']}})
        response.set_cookie('session','synthetic-session',httponly=True,secure=True)
        response.set_cookie('csrf','synthetic-csrf',secure=True)
        return response
    install(app,edge.front)
    path='/api/workflow-apps/app/runs'
    raw,headers=signed(edge,'POST',path,{'approved':True});headers['authorization']='Bearer private-app-capability'
    with TestClient(app) as client:response=client.post(path,content=raw,headers=headers)
    assert response.status_code==200,response.text
    assert response.headers['content-type']==MEDIA
    assert response.json()['recovery']=={'run_id':run_id}
    assert len(response.headers.get_list('set-cookie'))==2
    assert len(calls)==1 and not edge.calls


def test_orphan_receipts_cleanup_preserves_normal_workflow_checkpoints(edge):
    body,_=saved(edge)
    with edge.store.tx() as db:
        db.execute('DELETE FROM edge_gateway_runs WHERE id=?',(body['run_id'],))
        db.execute('INSERT INTO workflow_checkpoints VALUES (?,?,?,?)',('wr_preserved','node-1','{}','existing-proof'))
    results.prune(edge.service)
    assert not edge.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',(body['run_id'],))
    assert edge.store.query('SELECT * FROM workflow_checkpoints WHERE run_id=?',('wr_preserved',))


def test_native_origin_failopen_still_returns_a_local_receipt(edge):
    def origin(req):
        response=edge.client.post(req.url.path,content=req.content,headers=dict(req.headers))
        assert len(response.content)<220, response.text
        return httpx.Response(response.status_code,content=response.content,headers=response.headers)
    with httpx.Client(transport=httpx.MockTransport(origin)) as client,dispatch_scope(lambda:None):
        result=native.execute(edge.store,edge.store.resource(edge.rid),{'message':'Weather?'},scope='failopen',http=client)
    assert result['ok'] and result['delivery_backend']=='origin' and len(edge.calls)==1


def test_recipe_references_outputs_for_small_and_large_results(edge):
    for count in (1,8,2000):
        output={'content':[{'type':'text','text':'result '*count}]}
        _,source=saved(edge,output)
        value={'status':'succeeded','data':output,'output':canonical(output)}
        packed=recipe(value,[source])
        assert source['wire_hash'] in str(packed)
        assert 'result '*count not in str(packed)
        assert len(canonical(packed))<1000


def test_receipt_tampering_is_detected_and_reserved_namespace_does_not_overlap(edge):
    body,_=saved(edge)
    with edge.store.tx() as db:
        db.execute('UPDATE workflow_checkpoints SET payload=? WHERE run_id=?',('{}',body['run_id']))
    with pytest.raises(EdgeError):results.load_result(edge.service,body['run_id'])
    with results.parent_scope(body['run_id'],'private-node'):
        results.link_parent(edge.service,body['run_id'])
    assert not results.parent_results(edge.service,body['run_id'])


def test_result_view_never_accepts_an_unsigned_internal_flag(edge):
    path='/api/workflows/runs/missing'
    response=edge.client.get(path,headers={'X-Edge-Result-View':'v1'})
    assert response.status_code==401
    _,headers=signed(edge,'GET',path)
    # Original run-key authorization still applies to a signed Worker request.
    response=edge.client.get(path,headers=headers)
    assert response.status_code in (401,403,404)
    assert response.headers.get('content-type')!=MEDIA
    assert not edge.calls


@pytest.mark.parametrize('path',[
    '/api/workflows/runs/run-1','/api/workflow-apps/app/runs/run-1',
    '/api/workflow-apps-v12/app/runs/run-1','/api/workspace-apps-v2/app/runs/run-1',
    '/api/workspace-flow-apps-v2/app/runs/run-1'])
def test_only_explicit_authenticated_result_routes_are_eligible(path):
    assert RESULT_PATH.fullmatch(path)
    assert not RESULT_PATH.fullmatch(path+'/cancel')
    assert not RESULT_PATH.fullmatch('/admin'+path)


@pytest.mark.parametrize('suffix',[
    'drafts/draft/snapshots/snapshot/runs/run-1','drafts/draft/snapshots/snapshot/runs',
    'typed/flows/flow/runs/run-1','typed/flows/flow/runs','templates/drafts/draft/runs'])
def test_customer_workspace_result_and_history_routes_are_explicit(suffix):
    path='/api/customer-organizations/ws/authoring/'+suffix
    assert RESULT_PATH.fullmatch(path)
    assert not RESULT_PATH.fullmatch(path+('/cancel' if suffix.endswith('run-1') else '/run-1/cancel'))


def test_template_history_uses_authorized_internal_parent_without_exposing_it(edge):
    from fastapi import FastAPI,Request,HTTPException
    from fastapi.testclient import TestClient
    from agent_market.edge_gateway.result_view import install
    run_id='wr_'+'e'*32;alias='twr_'+'f'*32
    body,source=saved(edge)
    with results.parent_scope(run_id,'node-1'):results.link_parent(edge.service,body['run_id'])
    app=FastAPI()
    path='/api/customer-organizations/ws/authoring/templates/drafts/draft/runs'
    @app.get(path)
    async def history(request:Request):
        if request.cookies.get('customer')!='private-session':raise HTTPException(403)
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(results.note_parent,run_id)
        return {'runs':[{'id':alias,'status':'succeeded','data':source['output']}]}
    install(app,edge.front)
    _,headers=signed(edge,'GET',path);headers['Cookie']='customer=private-session'
    with TestClient(app) as client:
        response=client.get(path,headers=headers)
        assert response.status_code==200 and response.headers['content-type']==MEDIA,response.text
        assert run_id not in response.text and body['wire_hash'] in response.text
        _,headers=signed(edge,'GET',path)
        assert client.get(path,headers=headers).status_code==403
    with results.collecting() as observed:results.note_parent(run_id)
    assert observed=={run_id}
    results.note_parent('wr_'+'0'*32)
    assert observed=={run_id},'Request collection must not leak across visits'


def test_mcp_direct_prepare_and_finalize_preserve_auth_and_single_execution(machine_edge,monkeypatch):
    edge,rid=machine_edge
    edge.service.config=replace(edge.service.config,direct_result_delivery=True)
    monkeypatch.setattr(edge.front.proxy,'execute',lambda *a,**k:pytest.fail('No Origin Provider execution'))
    request={'jsonrpc':'2.0','id':'agent-1','method':'tools/call','params':{'name':'call','arguments':{
        'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'},'visitor_token':edge.token,'idempotency_key':'direct-mcp-1'}},
        '_edge_transport':{'mode':'prepare'}}
    raw,headers=signed(edge,'POST','/mcp',request,marker='X-Edge-MCP-Prepare')
    response=edge.client.post('/mcp',content=raw,headers=headers)
    assert response.status_code==200,response.text
    grant=response.json(); assert grant['_edge_plan'] and grant['backend']=='worker'
    assert 'no-store' in [part.strip().lower() for part in response.headers['cache-control'].split(',')]
    binding=edge.service.claim(grant['access_token'],ORIGIN,grant['run_id'],grant['input'],'worker')
    wire=json.dumps({'content':[{'type':'text','text':'Tokyo weather '*500}]},separators=(',',':'))
    results.store_result(edge.service,grant['run_id'],binding['attempt_id'],wire,hashlib.sha256(wire.encode()).hexdigest())
    request['_edge_transport']={'mode':'result','run_id':grant['run_id']}
    raw,headers=signed(edge,'POST','/mcp',request,marker='X-Edge-MCP-Prepare')
    response=edge.client.post('/mcp',content=raw,headers=headers)
    assert response.status_code==200,response.text
    if response.headers['content-type'] != MEDIA:
        recipe(response.json(),[results.load_result(edge.service,grant['run_id'])])
    assert response.headers['content-type']==MEDIA
    assert 'Tokyo weather '*500 not in response.text
    assert 'Tokyo weather' not in response.text
    assert len(response.content)<3000
    # A fresh signed retry also cannot execute or record success a second time.
    raw,headers=signed(edge,'POST','/mcp',request,marker='X-Edge-MCP-Prepare')
    replay=edge.client.post('/mcp',content=raw,headers=headers)
    assert replay.json()['result']['isError'] is True
    assert not edge.calls


def test_mcp_definitive_failure_remains_a_failure_and_never_reexecutes(machine_edge,monkeypatch):
    from agent_market.edge_gateway import machine
    edge,rid=machine_edge
    edge.service.config=replace(edge.service.config,direct_result_delivery=True)
    monkeypatch.setattr(edge.front.proxy,'execute',lambda *a,**k:pytest.fail('No Provider execution'))
    plan=machine.execute(edge.front,rid,'get_weather',{'city':'Tokyo'},principal='synthetic-visitor',idempotency_key='confirmed-failure',prepare_only=True)
    binding=edge.service.claim(plan['access_token'],ORIGIN,plan['run_id'],plan['input'],'worker')
    edge.service.finish(plan['run_id'],binding['attempt_id'],'failed',outcome_code='PROVIDER_INPUT_REJECTED')
    output=machine.execute(edge.front,rid,'get_weather',{'city':'Tokyo'},principal='synthetic-visitor',idempotency_key='confirmed-failure',stored_run=plan['run_id'])
    assert output['outcome']=='failed' and output['retry_safe'] is True and output['error_code']=='UPSTREAM_TOOL_ERROR'
    replay=machine.execute(edge.front,rid,'get_weather',{'city':'Tokyo'},principal='synthetic-visitor',idempotency_key='confirmed-failure',stored_run=plan['run_id'])
    assert replay['outcome']=='unknown' and replay['retry_safe'] is False
    assert not edge.calls


def test_paid_mcp_fallback_does_not_create_an_authenticated_visitor_during_preparation(machine_edge,monkeypatch):
    edge,rid=machine_edge
    edge.service.config=replace(edge.service.config,direct_result_delivery=True)
    resource=edge.store.resource(rid)
    monkeypatch.setattr(edge.front.store,'resource',lambda value:{**resource,'price_usdc':1} if value==rid else None)
    monkeypatch.setattr(edge.front,'identify',lambda *a,**k:pytest.fail('Original account authentication must remain unchanged'))
    request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'call','arguments':{
        'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'},'idempotency_key':'paid-fallback'}},'_edge_transport':{'mode':'prepare'}}
    raw,headers=signed(edge,'POST','/mcp',request,marker='X-Edge-MCP-Prepare')
    response=edge.client.post('/mcp',content=raw,headers=headers)
    assert response.json()=={'backend':'origin'}
    assert not edge.store.query('SELECT * FROM edge_gateway_runs') and not edge.calls
