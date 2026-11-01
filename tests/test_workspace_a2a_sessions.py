"""Real SSE parsing against isolated transports and encrypted durable state."""
import json

import httpx
import pytest

from agent_market.workspace_access import WorkspaceConflict,WorkspaceDenied
from agent_market.workspace_remote_a2a import NOTICE, SESSION_PROFILE
from tests.test_workspace_remote_a2a import remote, command  # noqa: F401
from tests.test_workspace_execution_api import private_api  # noqa: F401


def stream_provider(x, *, disconnect=False, changed=False):
    client = x.core.bindings[x.w.remote_rid].client
    client.streaming = True
    def provider(request):
        body = json.loads(request.content); x.calls.append(body)
        task = {'kind':'task','id':'session-task','contextId':'session-context','status':{'state':'working'}}
        if body['method'] == 'tasks/cancel':
            return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':task | {'status':{'state':'canceled'}}})
        events = [('1',task)]
        if body['method'] == 'tasks/resubscribe':
            assert request.headers['Last-Event-ID'] == '2'
            events = [('2',{'kind':'artifact-update','taskId':'session-task','contextId':'session-context',
                         'artifact':{'artifactId':'doc','parts':[{'kind':'text','text':'Retained evidence'}]}})]
        else:
            events += [('2',{'kind':'artifact-update','taskId':'session-task','contextId':'session-context',
                         'artifact':{'artifactId':'doc','parts':[{'kind':'text','text':'Retained evidence'}]}})]
        if not disconnect or body['method'] == 'tasks/resubscribe':
            state = 'completed' if body['method'] == 'tasks/resubscribe' or 'taskId' in body['params'].get('message',{}) else 'input-required'
            events += [('3' if state=='input-required' else '4',{'kind':'status-update','taskId':'changed' if changed else 'session-task',
                         'contextId':'session-context','status':{'state':state},'final':True})]
        wire = ''.join('id: '+cursor+'\ndata: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':event})+'\n\n' for cursor,event in events)
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},text=wire)
    client.http = httpx.Client(transport=httpx.MockTransport(provider))


def test_session_continuation_keeps_context_and_deduplicates_turn(remote):
    x=remote; stream_provider(x)
    first=x.core.send(x.w.ws['id'],command(x),x.actor)
    assert first['profile']==SESSION_PROFILE and first['state']=='input-required' and first['retained_events']==3
    body={'revision':first['revision'],'logical_id':'rat_'+'b'*32,'text':'Continue the approved task',
          'authorized':True,'notice':NOTICE}
    second=x.core.continue_session(x.w.ws['id'],first['id'],body,x.actor)
    assert second['state']=='completed' and second['session_turn']==2
    message=x.calls[-1]['params']['message']
    assert message['contextId']=='session-context' and message['taskId']=='session-task'
    assert x.core.continue_session(x.w.ws['id'],first['id'],body,x.actor)['replayed'] and len(x.calls)==2
    assert 'session-context' not in x.w.store.query('SELECT payload FROM workspace_remote_tasks')[0][0]


def test_interrupted_stream_resumes_read_only_and_deduplicates_artifact(remote):
    x=remote; stream_provider(x,disconnect=True)
    task=x.core.send(x.w.ws['id'],command(x),x.actor)
    assert task['state']=='unknown' and task['resume_available']
    task=x.core.command(x.w.ws['id'],task['id'],{'revision':task['revision'],'action':'resume','authorized':True,'notice':NOTICE},x.actor)
    assert task['state']=='completed' and [c['method'] for c in x.calls]==['message/stream','tasks/resubscribe']
    assert x.core.status(x.w.ws['id'],task['id'],x.actor)['output_preview']=='Retained evidence'


def test_session_identity_switch_is_unknown_and_does_not_resubmit(remote):
    x=remote;stream_provider(x,changed=True)
    task=x.core.send(x.w.ws['id'],command(x),x.actor)
    assert task['state']=='unknown'
    assert x.core.send(x.w.ws['id'],command(x),x.actor)['id']==task['id'] and len(x.calls)==1


def test_private_early_stop_guard_blocks_packet_after_durable_preparation(remote):
    x=remote;task=x.core.send(x.w.ws['id'],command(x),x.actor)
    def denied():
        raise WorkspaceConflict()
    result=x.core.command(x.w.ws['id'],task['id'],{'revision':task['revision'],'action':'cancel','authorized':True,'notice':NOTICE},x.actor,_guard=denied)
    assert result['state']=='unknown' and len(x.calls)==1


def test_crash_after_durable_stream_event_fences_old_operation_and_resumes_same_task(remote,monkeypatch):
    import copy
    import agent_market.workspace_remote_a2a as module
    x=remote;client=x.core.bindings[x.w.remote_rid].client;client.streaming=True
    now=module.clock()
    class ProcessLost(BaseException):
        pass
    class InterruptedBody(httpx.SyncByteStream):
        def __init__(self,identity):self.identity=identity
        def __iter__(self):
            task={'kind':'task','id':'crash-task','contextId':'crash-context','status':{'state':'working'}}
            yield ('id: event-1\ndata: '+json.dumps({'jsonrpc':'2.0','id':self.identity,'result':task})+'\n\n').encode()
            raise ProcessLost()
    def provider(request):
        body=json.loads(request.content);x.calls.append(body)
        if body['method']=='message/stream':
            return httpx.Response(200,headers={'Content-Type':'text/event-stream'},stream=InterruptedBody(body['id']))
        assert body['method']=='tasks/resubscribe' and body['params']=={'id':'crash-task'}
        assert request.headers['Last-Event-ID']=='event-1'
        event={'kind':'status-update','taskId':'crash-task','contextId':'crash-context','status':{'state':'completed'},'final':True}
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},text='id: event-2\ndata: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':event})+'\n\n')
    client.http=httpx.Client(transport=httpx.MockTransport(provider))
    with pytest.raises(ProcessLost):x.core.send(x.w.ws['id'],command(x),x.actor)
    task=x.core.listing(x.w.ws['id'],x.actor)[0]
    assert task['state']=='dispatched' and not task['resume_available']
    monkeypatch.setattr(module,'clock',lambda:now+46)
    task=x.core.status(x.w.ws['id'],task['id'],x.actor)
    assert task['resume_available']
    # Four interrupted leases must not deadlock recovery by counting the same
    # retained task as both an existing lease and a new admission.
    with x.core.access._tx(x.actor,write=True) as (db,_):
        original=x.core._load(db,x.w.ws['id'],task['id'])
        for i in range(3):
            value=copy.deepcopy(original);private=x.core._private(original)
            value.update(id='rtk_'+str(i)*32,logical_id='rat_'+str(i)*32)
            x.core._seal(value,private);x.core._save(db,value)
    result=x.core.command(x.w.ws['id'],task['id'],{'revision':task['revision'],'action':'resume','authorized':True,'notice':NOTICE},x.actor)
    assert result['state']=='completed' and [c['method'] for c in x.calls]==['message/stream','tasks/resubscribe']


def test_active_stream_can_be_canceled_with_full_business_pool_and_late_frames_are_fenced(remote):
    from agent_market.workspace_execution import _slots
    x=remote;stream_provider(x,disconnect=True)
    task=x.core.send(x.w.ws['id'],command(x),x.actor)
    with x.core.access._tx(x.actor,write=True) as (db,_):
        old=x.core._load(db,x.w.ws['id'],task['id'])
        old.update(state='dispatched');x.core._save(db,old)
    for _ in range(4):assert _slots.acquire(blocking=False)
    try:
        result=x.core.command(x.w.ws['id'],task['id'],{'revision':old['revision'],'action':'cancel','authorized':True,'notice':NOTICE},x.actor)
    finally:
        for _ in range(4):_slots.release()
    assert result['state']=='canceled' and x.calls[-1]['method']=='tasks/cancel'
    with pytest.raises(WorkspaceDenied):
        x.core._event(x.w.ws['id'],old,{'kind':'status-update','taskId':'session-task','contextId':'session-context',
            'status':{'state':'completed'},'final':True},'late-event',x.actor)
    assert x.core.status(x.w.ws['id'],task['id'],x.actor)['state']=='canceled'
