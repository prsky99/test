"""Workflow inbox verification and signed delivery over real isolated TLS sockets."""
import hashlib
import hmac
import json

import pytest
from fastapi import Request

from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowRuntime
from tests.test_notification_inbox_integration import network  # noqa: F401
from tests.test_workflow_runtime import wait


@pytest.mark.parametrize('binding',['webhook','a2a03','a2a1'])
def test_workflow_inbox_tls_verification_delivery_and_revocation(network,tmp_path,binding):
    app,_,_,courier,transport,_=network
    observed=[];secret={}
    @app.get('/workflow/card.json')
    def card():
        base={'name':'Workflow Test Inbox','skills':[],'capabilities':{}}
        if binding=='a2a1':base['supportedInterfaces']=[{'url':'https://inbox.example/workflow/inbox','protocolBinding':'JSONRPC','protocolVersion':'1.0'}]
        else:base.update(url='https://inbox.example/workflow/inbox',protocolVersion='0.3',preferredTransport='JSONRPC')
        return base
    @app.post('/workflow/inbox')
    async def receive(request: Request):
        raw=await request.body();wire=json.loads(raw)
        payload=wire['params']['message']['parts'][0]['data'] if binding!='webhook' else wire
        if payload['type']=='workflow_inbox_verification':secret['value']=payload['signing_secret']
        expected='sha256='+hmac.new(secret['value'].encode(),request.headers['x-agent-timestamp'].encode()+b'.'+raw,hashlib.sha256).hexdigest()
        assert hmac.compare_digest(expected,request.headers['x-agent-signature'])
        assert not request.headers.get('authorization') and not request.headers.get('cookie')
        observed.append(payload)
        if binding=='webhook':return {'accepted':True}
        return {'jsonrpc':'2.0','id':wire['id'],'result':{'message':{'parts':[{'text':'Accepted'}]}}}
    store=Store(str(tmp_path/'tls-workflow.db'));rt=WorkflowRuntime(store,courier=courier)
    wid=store.create_workflow({'name':'TLS Workflow','nodes':[{'id':'start','type':'trigger','name':'Manual','data':{}}],'edges':[]})
    channel='webhook' if binding=='webhook' else 'a2a'
    url='https://inbox.example/workflow/inbox' if binding=='webhook' else 'https://inbox.example/workflow/card.json'
    pending=rt.register_destination(wid,{'channel':channel,'url':url,'authority':True,'notice':'workflow-results-v1'})
    assert len(observed)==1 and observed[0]['purpose']=='workflow_results'
    rt.verify_destination(wid,pending['id'],observed[0]['code'])
    rt.save_schedule(wid,{'mode':'manual','enabled':False,'destination_id':pending['id'],'delivery_authority':True,'delivery_notice':'workflow-result-grant-v1','delivery_sources':['admin']})
    result=wait(rt,rt.submit(store.get_workflow(wid)))
    assert result['status']=='succeeded' and result['final_deliverable']['distribution']['status']=='ACCEPTED'
    assert len(observed)==2 and observed[1]['artifact_sha256']==result['artifact_sha256']
    rt._deliver(result['run_id'],wid,result);assert len(observed)==2
    # Anonymous template runs cannot spam the administrator's verified destination.
    public=wait(rt,rt.submit(store.get_workflow(wid),source='public',actor='public',public=True))
    assert public['final_deliverable']['distribution']['status']=='NOT_REQUESTED' and len(observed)==2
    rt.revoke_destination(wid,pending['id'])
    wait(rt,rt.submit(store.get_workflow(wid)));assert len(observed)==2
    assert all(not headers.get('authorization') and not headers.get('cookie') for _,_,headers,_ in transport.requests)
    store._db.close()
