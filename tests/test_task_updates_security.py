"""Dynamic isolated API tests for protocol preferences and purpose-scoped updates."""
import hashlib
import hmac
import json
import os
import time

import httpx
import pytest

from tests.conftest import staff_session
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front
from agent_market.concierge.notify import Courier, AgentNurtureEngine
from agent_market.concierge.task_updates import NOTICE_VERSION, DESTINATION_NOTICE, TaskUpdates, UpdateError
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from tests.test_fast_single_recommendation import catalog, ask, chosen  # noqa: F401


class UpdateCourier:
    def __init__(self):
        self.challenges=[]
        self.events=[]
        self.result=(True,None)

    def resolve(self,channel,url):
        return {'url':url,'v1':False}

    def send(self,contact,kind,text,data):
        self.challenges.append(data)
        return True,None

    def send_update(self,channel,secret,payload,event_id):
        self.events.append((channel,payload,event_id))
        return self.result


@pytest.fixture
def updates(catalog):
    store,front,client,add,now=catalog
    add('Weather MCP',report_at=now-10)
    reply=ask(client)
    headers={'X-Visitor-Token':reply['visitor']['token']}
    courier=UpdateCourier()
    front.updates.courier=courier
    data={'task':'weather forecast','protocol':'mcp','channel':'poll','authority':True,'task_updates':True,'notice_version':NOTICE_VERSION,'destination_confirmed':True,'destination_notice_version':DESTINATION_NOTICE}
    return store,front,client,add,headers,courier,data,reply['visitor']['id']


@pytest.mark.parametrize('kind',['a2a','mcp','x402'])
def test_protocol_text_selector_and_recency_within_protocol(catalog,kind):
    _,_,client,add,now=catalog
    add(kind+' A',kind=kind,grade='A',report_at=now-100)
    best=add(kind+' B',kind=kind,grade='B',report_at=now-1)
    add('Other A',kind='a2a' if kind!='a2a' else 'mcp',grade='A',report_at=now)
    assert chosen(ask(client,'find a '+kind+' weather forecast agent'))['id']==best
    assert chosen(ask(client,'MCP weather forecast',data={'protocol':kind}))['id']==best


def test_invalid_protocol_and_followup_preservation(catalog):
    _,_,client,add,now=catalog
    best=add('Weather A2A',kind='a2a',report_at=now-20)
    add('Weather MCP',kind='mcp',report_at=now)
    body=ask(client,'A2A weather forecast')
    assert chosen(body)['id']==best
    headers={'X-Visitor-Token':body['visitor']['token']}
    assert client.post('/chat',headers=headers,json={'message':'details 1'}).json()['data']['recommendations'][0]['kind']=='a2a'
    detail=client.post('/chat',headers=headers,json={'message':'details 1','data':{'protocol':'any'}}).json()['data']
    assert detail['recommendations'][0]['kind']=='a2a' and detail['protocol'] is None and detail['watch_task']
    for protocol in ['sql',{},['mcp'],True]:
        res=client.post('/chat',json={'message':'weather','data':{'protocol':protocol}})
        assert res.status_code in (200,400)
        if res.status_code==200:
            assert res.json()['data']['status']=='invalid_protocol'
    assert chosen(ask(client,'A2A weather, not MCP'))['id']==best
    assert ask(client,'weather without MCP')['data']['status']=='invalid_protocol'
    assert ask(client,'MCP or A2A weather')['data']['status']=='invalid_protocol'
    assert chosen(ask(client,'MCP or A2A weather',data={'protocol':'any'}))['kind']=='a2a'


def test_poll_permission_lifecycle_and_cross_visitor_isolation(updates):
    store,front,client,add,headers,courier,data,vid=updates
    assert client.post('/api/task-updates',json=data).status_code==401
    assert client.post('/api/task-updates',headers={**headers,'Origin':'https://evil.example'},json=data).status_code==403
    assert client.post('/api/task-updates',headers=headers,json={**data,'authority':False}).status_code==400
    res=client.post('/api/task-updates',headers=headers,json=data)
    assert res.status_code==201 and res.json()['state']=='active'
    wid=res.json()['id']
    other=ask(client,'hi')['visitor']['token']
    assert client.post(f'/api/task-updates/{wid}/action',headers={'X-Visitor-Token':other},json={'action':'stop'}).status_code==400
    add('Better Weather',report_at=time.time())
    events=client.get(f'/api/task-updates/{wid}/events',headers=headers).json()['items']
    assert len(events)==1 and events[0]['recommendation']['name']=='Better Weather'
    assert 'visitor_id' not in json.dumps(events) and not courier.events
    assert client.post(f'/api/task-updates/{wid}/action',headers=headers,json={'action':'stop'}).json()['state']=='revoked'
    assert client.get(f'/api/task-updates/{wid}/events',headers=headers).json()['items']==[]
    assert client.post(f'/api/task-updates/{wid}/action',headers=headers,json={'action':'resume'}).status_code==400
    assert front.updates._get(wid)['task']==''


def test_callback_encryption_verification_and_revocation_fence(updates):
    store,front,client,add,headers,courier,data,vid=updates
    url='https://inbox.example/notification-inbox'
    row=client.post('/api/task-updates',headers=headers,json={**data,'channel':'webhook','url':url}).json()
    wid=row['id']
    raw=front.updates._get(wid)
    assert url not in json.dumps(raw) and url not in json.dumps(row)
    assert courier.challenges and not courier.events
    code=courier.challenges[-1]['verification_code']
    assert client.post(f'/api/task-updates/{wid}/action',headers=headers,json={'action':'verify','code':code}).json()['state']=='active'
    assert client.post(f'/api/task-updates/{wid}/action',headers=headers,json={'action':'verify','code':code}).status_code==400
    add('Better Weather',report_at=time.time())
    front.updates.refresh()
    cap=front.updates.capability(wid)
    assert client.get('/api/task-updates/stop').status_code in (404,405)
    assert front.updates._get(wid)['state']=='active'
    assert client.post('/api/task-updates/stop',json={'capability':cap[:-1]+'z'}).status_code==400
    assert client.post('/api/task-updates/stop',json={'capability':cap}).status_code==200
    assert client.post('/api/task-updates/stop',json={'capability':cap}).status_code==200
    front.updates.run_due(force_visitor=vid)
    assert not courier.events and front.updates._get(wid)['sealed'] is None


def test_wrong_verification_attempts_exhaust_and_do_not_roll_back(updates):
    _,front,client,_,headers,courier,data,_=updates
    wid=client.post('/api/task-updates',headers=headers,json={**data,'channel':'webhook','url':'https://inbox.example/inbox'}).json()['id']
    good=courier.challenges[-1]['verification_code']
    wrong='000000' if good!='000000' else '000001'
    for _ in range(5):
        assert client.post(f'/api/task-updates/{wid}/action',headers=headers,json={'action':'verify','code':wrong}).status_code==400
    row=front.updates._get(wid)
    assert row['state']=='failed' and row['sealed'] is None and row['verify_failures']==5


@pytest.mark.parametrize('url',[
    'http://public.example/inbox','https://127.0.0.1/inbox','https://[::1]/',
    'https://[::ffff:127.0.0.1]/','https://169.254.169.254/latest/meta-data/',
    'https://localhost/inbox','https://foo.local/inbox','https://a:b@public.example/inbox',
    'https://public.example:8200/inbox','https://public.example/inbox?token=secret',
    'https://public.example/inbox#secret','https://hooks.slack.com/services/a/b/c',
    'https://public.example/workflows/run','https://public.example\\@127.0.0.1/',
])
def test_notification_destination_rejection(updates,url):
    _,_,client,_,headers,courier,data,_=updates
    res=client.post('/api/task-updates',headers=headers,json={**data,'channel':'webhook','url':url})
    assert res.status_code==400 and not courier.challenges
    assert url not in res.text


@pytest.mark.parametrize('task',['<img src=x onerror=alert(1)>','https://private.example/key','contact me@example.com','vt_abcdefghijklmnop','a'*161])
def test_task_label_rejects_private_or_executable_content(updates,task):
    _,_,client,_,headers,_,data,_=updates
    assert client.post('/api/task-updates',headers=headers,json={**data,'task':task}).status_code==400


def test_expiry_deletion_and_minimal_permissions(updates):
    store,front,client,_,headers,_,data,_=updates
    wid=client.post('/api/task-updates',headers=headers,json=data).json()['id']
    with store.tx() as db:
        db.execute('UPDATE agent_task_watches SET expires=? WHERE id=?',(time.time()-1,wid))
    front.updates.maintain()
    row=front.updates._get(wid)
    assert row['state']=='expired' and not row['task'] and row['baseline'] is None
    assert client.post(f'/api/task-updates/{wid}/action',headers=headers,json={'action':'delete'}).status_code==200
    evidence=[dict(r) for r in store.query('SELECT * FROM agent_task_permissions')]
    assert all('task' not in r and 'url' not in r and 'token' not in r for r in evidence)


def test_legacy_and_admin_force_paths_do_not_grant_or_send(updates):
    store,front,client,_,headers,courier,data,vid=updates
    front.llm=None
    row=client.post('/api/task-updates',headers=headers,json=data).json()
    app=FastAPI(); app.include_router(dashboard_router(store,':memory:','secret',None,front=front))
    admin=TestClient(app); auth=staff_session(store)
    path=f'/admin/api/visitors/{vid}'
    assert admin.get(path).status_code in (401,403)
    detail=admin.get(path,headers=auth).json()
    assert detail['task_watches'][0]['protocol']=='mcp' and detail['marketing_enabled'] is False
    assert 'sealed' not in json.dumps(detail) and 'token_hash' not in json.dumps(detail)
    assert admin.post(path+'/notify',headers=auth,json={'enabled':True}).status_code==403
    assert admin.post(path+'/nurture',headers=auth,json={'campaign':'pro_sla_invitation'}).json()['status']=='permission_denied'
    wp=path+'/task-updates/'+row['id']+'/action'
    assert admin.post(wp,headers=auth,json={'action':'resume'}).status_code==400
    assert admin.post(wp,headers=auth,json={'action':'stop','reason':'Synthetic visitor permission revocation verification'}).json()['state']=='revoked'
    front.digest.run_due(force_visitor=vid)
    assert not courier.events
    assert client.post('/chat',headers=headers,json={'message':'contact https://inbox.example/inbox'}).json()['data']['status']=='permission_required'
    assert not courier.challenges


def test_persistent_key_private_and_ciphertext_bound_to_watch(tmp_path):
    db=tmp_path/'isolated.db';store=Store(str(db));front=Front(store,allow_private=True)
    assert not front.updates.courier.allow_private
    keypath=str(db)+'.updates-key'
    assert os.stat(keypath).st_mode & 0o777==0o600
    sealed=front.updates._seal({'url':'https://inbox.example/inbox'},'one')
    other=TaskUpdates(store,front.rec,front.updates.courier)
    assert other._open(sealed,'one')['url']=='https://inbox.example/inbox'
    with pytest.raises(ValueError): other._open(sealed,'two')
    os.chmod(keypath,0o644)
    with pytest.raises(ValueError): TaskUpdates(store,front.rec,front.updates.courier)
    store._db.close()


def test_signed_bytes_and_gone_result():
    seen=[]
    def receive(request):
        seen.append(request)
        return httpx.Response(410)
    courier=Courier(False,http=httpx.Client(transport=httpx.MockTransport(receive),cookies={'private_cookie':'must-not-be-forwarded'},headers={'Authorization':'Bearer private-default-header'},auth=('private-user','private-password')))
    secret={'target':{'url':'https://public.example/inbox'},'secret':'test-only-signing-key'}
    assert courier.send_update('webhook',secret,{'message':'Verification evidence changed.'},'te_1')==(False,'gone')
    request=seen[0]
    expected=hmac.new(secret['secret'].encode(),request.headers['X-Agent-Timestamp'].encode()+b'.'+request.content,hashlib.sha256).hexdigest()
    assert request.headers['X-Agent-Signature']=='sha256='+expected
    assert 'X-Visitor-Token' not in request.headers and not request.headers.get('cookie')
    assert not request.headers.get('authorization')
    assert request.headers['X-Agent-Key-ID']==hashlib.sha256(secret['secret'].encode()).hexdigest()[:16]


def test_verified_send_cadence_and_gone_revocation(updates):
    store,front,client,add,headers,courier,data,vid=updates
    wid=client.post('/api/task-updates',headers=headers,json={**data,'channel':'webhook','url':'https://inbox.example/inbox'}).json()['id']
    client.post(f'/api/task-updates/{wid}/action',headers=headers,json={'action':'verify','code':courier.challenges[-1]['verification_code']})
    add('New Evidence Weather',report_at=time.time())
    assert front.updates.run_due(vid)['sent']==1
    assert len(courier.events)==1 and 'stop_url' in courier.events[0][1]
    add('Newest Weather',report_at=time.time()+1)
    front.updates.run_due(vid)
    assert len(courier.events)==1
    with store.tx() as db:
        db.execute('UPDATE agent_task_watches SET last_event=0 WHERE id=?',(wid,))
    courier.result=(False,'gone')
    front.updates.run_due(vid)
    assert front.updates._get(wid)['state']=='revoked'


def test_destination_budget_and_explicit_kill_switch(updates):
    _,front,_,_,_,courier,data,vid=updates
    assert all(front.updates._budget('same','verification',3,3600) for _ in range(3))
    assert front.updates._budget('same','verification',3,3600) is False
    front.updates.outbound_enabled=False
    with pytest.raises(UpdateError): front.updates.create(vid,{**data,'channel':'webhook','url':'https://inbox.example/inbox'})
    front.updates.create(vid,data)
    assert front.updates.run_due()['sent']==0 and not courier.challenges


def test_refresh_batches_do_not_starve_unchanged_watches(updates):
    store,front,_,_,_,_,_,vid=updates
    with store.tx() as db:
        db.executemany('''INSERT INTO agent_task_watches
            (id,visitor_id,task,channel,state,created,expires,baseline,notice_version,authority)
            VALUES (?,?,?,'poll','active',?,?,?, ?,1)''',
            [(f'tw_fair_{i}',vid,'weather forecast',time.time()+i/1000,time.time()+86400,'null',NOTICE_VERSION) for i in range(201)])
    front.updates.refresh()
    front.updates.refresh()
    assert not store.query('SELECT id FROM agent_task_watches WHERE last_checked=0')


def test_unverified_records_are_purged_after_one_day(updates):
    store,front,client,_,headers,courier,data,vid=updates
    row=client.post('/api/task-updates',headers=headers,json={**data,'channel':'webhook','url':'https://inbox.example/inbox'}).json()
    front.updates.action(vid,row['id'],'stop')
    with store.tx() as db:
        db.execute('UPDATE agent_task_watches SET created=?,revoked_at=? WHERE id=?',(time.time()-86401,time.time()-10,row['id']))
    front.updates.maintain()
    assert not store.query('SELECT * FROM agent_task_watches WHERE id=?',(row['id'],))
    assert not store.query('SELECT * FROM agent_task_permissions WHERE watch_id=?',(row['id'],))


def test_watch_schedule_independent_of_catalog_rescan(monkeypatch):
    from types import SimpleNamespace
    from agent_market.gateway import server
    clock=[0.0];rescans=[];updates=[];waits=[]
    class Stop:
        def is_set(self): return len(waits)>=4
        def wait(self,n): waits.append(n);clock[0]+=n
    collector=SimpleNamespace(start=lambda:None,stop=lambda:None)
    service=SimpleNamespace(rescan=lambda:rescans.append(clock[0]))
    digest=SimpleNamespace(run_due=lambda:(updates.append(clock[0]) or {'checked':0}))
    monkeypatch.setattr(server,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    scheduler=server.Scheduler(collector,service,900,digest);scheduler.stop_event=Stop();scheduler.run()
    assert len(rescans)==1 and len(updates)==4 and max(waits)<=60


def test_admin_single_visitor_check_does_not_trigger_other_challenges(updates):
    _,front,_,_,_,courier,data,vid=updates
    other=front.book.create('rest','isolated-test','isolated-other')
    row=front.updates.create(other.id,{**data,'channel':'webhook','url':'https://inbox.example/inbox'})
    front.updates.run_due(force_visitor=vid)
    assert not courier.challenges
    front.updates.run_due(force_visitor=other.id)
    assert courier.challenges and courier.challenges[0]['watch_id']==row['id']


def test_evidence_handles_empty_or_failing_task_gracefully(updates):
    _,front,_,_,_,_,_,_ = updates
    evidence, item = front.updates._evidence("", None)
    assert evidence == 'null' and item is None
    evidence, item = front.updates._evidence("   ", "a2a")
    assert evidence == 'null' and item is None
    evidence, item = front.updates._evidence(None, "mcp")
    assert evidence == 'null' and item is None

    class FailingRec:
        def search(self, *a, **kw):
            raise RuntimeError("unexpected search failure")
    saved_rec = front.updates.rec
    try:
        front.updates.rec = FailingRec()
        evidence, item = front.updates._evidence("valid task", "a2a")
        assert evidence == 'null' and item is None
    finally:
        front.updates.rec = saved_rec

