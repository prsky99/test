"""Manual result permission traverses the real isolated TLS delivery transport."""
import hashlib
import hmac
import json

from fastapi import Request
from fastapi.responses import JSONResponse
from agent_market.gateway.store import Store
from agent_market.workflows import WorkflowRuntime
from tests.test_notification_inbox_integration import network
from tests.test_workflow_runtime import wait
from tests.test_workflow_operations_hardening import review,resend


def test_explicit_manual_result_delivery_over_tls_uses_new_event_and_no_automatic_repeat(network,tmp_path):
    app,_,_,courier,transport,_=network;observed=[];secret={}
    @app.post('/workflow/manual-results')
    async def receive(request:Request):
        raw=await request.body();payload=json.loads(raw)
        if payload['type']=='workflow_inbox_verification':secret['value']=payload['signing_secret']
        expected='sha256='+hmac.new(secret['value'].encode(),request.headers['x-agent-timestamp'].encode()+b'.'+raw,hashlib.sha256).hexdigest()
        assert hmac.compare_digest(expected,request.headers['x-agent-signature'])
        assert not request.headers.get('authorization') and not request.headers.get('cookie')
        observed.append((payload,request.headers.get('x-agent-event-id')))
        if len(observed)==2:return JSONResponse({'accepted':False},status_code=503)
        return {'accepted':True}
    store=Store(str(tmp_path/'workflow-manual-tls.sqlite3'));rt=WorkflowRuntime(store,courier=courier)
    wid=store.create_workflow({'name':'TLS manual result','nodes':[{'id':'start','name':'Start','type':'trigger','data':{}}],'edges':[]});wf=store.get_workflow(wid)
    try:
        pending=rt.register_destination(wid,{'channel':'webhook','url':'https://inbox.example/workflow/manual-results','authority':True,'notice':'workflow-results-v1'})
        rt.verify_destination(wid,pending['id'],observed[0][0]['code'])
        rt.save_schedule(wid,{'mode':'manual','enabled':False,'destination_id':pending['id'],'delivery_authority':True,'delivery_notice':'workflow-result-grant-v1','delivery_sources':['admin']})
        job=wait(rt,rt.submit(wf));event=store.query('SELECT id,status FROM workflow_result_outbox WHERE run_id=?',(job['run_id'],))[0]
        assert event['status']=='unknown' and len(observed)==2
        rt.operations.drain();assert len(observed)==2
        # This is an operator statement, not machine proof of the external
        # receiver's state. The separate risk acknowledgement permits a duplicate.
        review(rt,wf,job,event['id']);manual=resend(rt,wf,job,event['id'],pending['id']);rt.operations.drain();rt.operations.drain()
        assert len(observed)==3 and observed[-1][0]['manual_resend']
        assert observed[-1][0]['source_event_id']==event['id'] and manual['id']!=event['id']
        assert rt.operations.inspect(job['run_id'])['manual_deliveries'][0]['status']=='accepted'
    finally:store._db.close()
