"""Destination/marketing boundaries and encrypted browser delivery with isolated transports."""
import base64
import json
import os
import time

import http_ece
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from agent_market.concierge.browser_push import BrowserPush, b64
from agent_market.concierge.task_updates import DESTINATION_NOTICE, MARKETING_NOTICE
from tests.test_task_updates_security import updates, catalog  # noqa: F401


def subscription(token='synthetic-test-endpoint'):
    private=ec.generate_private_key(ec.SECP256R1())
    auth=os.urandom(16)
    point=private.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    return {'endpoint':'https://fcm.googleapis.com/fcm/send/'+token,'keys':{'p256dh':b64(point),'auth':b64(auth)}},private,auth


class FakePush:
    def __init__(self,public_key):
        self.public_key=public_key;self.sent=[];self.result=(True,None)
    def send(self,sub,payload,ttl=300):
        self.sent.append((sub,payload,ttl));return self.result


@pytest.fixture
def delivery(updates):
    store,front,client,add,headers,courier,data,vid=updates
    push=FakePush(front.updates.push.public_key);front.updates.push=push
    sub,private,auth=subscription()
    payload={**data,'channel':'browser','subscription':sub,'marketing':True,'marketing_notice_version':MARKETING_NOTICE}
    return (*updates,push,payload)


def enroll(delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    result=client.post('/api/task-updates',headers=headers,json=payload)
    assert result.status_code==201,result.text
    return result.json(),push.sent[-1][1]


def proof(client,message,decision='confirm',**headers):
    return client.post('/api/task-updates/browser-confirm',headers=headers,json={**message,'decision':decision})


def test_browser_requires_actual_push_challenge_before_activation_and_marketing(delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    row,message=enroll(delivery)
    assert row['state']=='pending_verification' and not row['destination_verified'] and not row['marketing_eligible']
    assert len(push.sent)==1 and not courier.challenges
    assert 'challenge' not in json.dumps(row) and payload['subscription']['endpoint'] not in json.dumps(row)
    assert payload['subscription']['keys']['auth'] not in json.dumps(front.updates._get(row['id']))
    add('New Browser Weather',report_at=time.time())
    front.updates.run_due(vid)
    assert len(push.sent)==1 and not store.query('SELECT * FROM agent_task_events')
    assert client.post(f"/api/task-updates/{row['id']}/action",headers=headers,json={'action':'verify','code':message['challenge']}).status_code==400
    assert proof(client,{**message,'challenge':'x'*43}).status_code==400
    assert proof(client,message,Origin='https://evil.example').status_code==403
    assert proof(client,message).json()['state']=='active'
    active=client.get('/api/task-updates',headers=headers).json()['items'][0]
    assert active['destination_verified'] and active['marketing_eligible'] and active['marketing_requested']
    assert proof(client,message).status_code==400
    assert front.updates.run_due(vid)['sent']==1
    assert push.sent[-1][1]['type']=='task_update' and set(push.sent[-1][1])=={'type','event_id'}
    assert not courier.events


def test_browser_decline_physically_removes_pending_request_and_choices(delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    row,message=enroll(delivery)
    assert proof(client,message,'decline').json()['state']=='deleted'
    for table in ('agent_task_watches','agent_task_destination_checks','agent_marketing_permissions','agent_task_events','agent_task_permissions'):
        assert not store.query('SELECT * FROM '+table)
    assert client.get('/api/task-updates',headers=headers).json()['items']==[]
    assert proof(client,message).status_code==400


def test_authenticated_decline_and_cross_visitor_boundaries(delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    row,_=enroll(delivery)
    another=client.post('/chat',json={'message':'hello'}).json()['visitor']['token']
    path=f"/api/task-updates/{row['id']}/action"
    assert client.post(path,headers={'X-Visitor-Token':another},json={'action':'decline'}).status_code==400
    assert client.post(path,headers=headers,json={'action':'decline'}).json()['state']=='deleted'
    assert client.post(path,headers=headers,json={'action':'decline'}).status_code==200
    assert not store.query('SELECT * FROM agent_task_watches')


def test_input_confirmation_and_separate_marketing_version_are_mandatory(delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    for invalid in [{**payload,'destination_confirmed':False},{**payload,'destination_notice_version':'old'},{**payload,'marketing':'true'},{**payload,'marketing_notice_version':'old'},{**payload,'channel':'poll'}]:
        assert client.post('/api/task-updates',headers=headers,json=invalid).status_code==400
    assert not store.query('SELECT * FROM agent_task_watches') and not push.sent
    row=client.post('/api/task-updates',headers=headers,json={**payload,'marketing':False}).json()
    assert not row['marketing_requested'] and not store.query('SELECT * FROM agent_marketing_permissions')


@pytest.mark.parametrize('endpoint',[
    'https://127.0.0.1/send/token','https://169.254.169.254/latest/meta-data/',
    'https://fcm.googleapis.com.evil.example/token','https://fcm.googleapis.com@evil.example/token',
    'https://user:pass@fcm.googleapis.com/token','http://fcm.googleapis.com/token',
    'https://fcm.googleapis.com:8443/token','https://fcm.googleapis.com/token#private',
    'https://evil.example/token','https://fcm.googleapis.com/','https://[::1]/token'])
def test_invalid_push_destinations_create_no_records(delivery,endpoint):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    value={**payload,'subscription':{**payload['subscription'],'endpoint':endpoint}}
    assert client.post('/api/task-updates',headers=headers,json=value).status_code==400
    assert not store.query('SELECT * FROM agent_task_watches') and not push.sent


@pytest.mark.parametrize('field,value',[('p256dh','invalid'),('auth',''),('p256dh',b64(b'\x04'+b'x'*64)),('auth',b64(b'x'*15))])
def test_invalid_subscription_keys_rejected_before_storage(delivery,field,value):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    sub={**payload['subscription'],'keys':{**payload['subscription']['keys'],field:value}}
    assert client.post('/api/task-updates',headers=headers,json={**payload,'subscription':sub}).status_code==400
    assert not store.query('SELECT * FROM agent_task_watches') and not push.sent


def test_browser_challenge_expiry_and_disabled_outbound(delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    row,message=enroll(delivery)
    with store.tx() as db:db.execute('UPDATE agent_task_watches SET code_expires=? WHERE id=?',(time.time()-1,row['id']))
    assert proof(client,message).status_code==400
    front.updates.outbound_enabled=False
    assert client.get('/api/task-updates/browser-config').json()['available'] is False
    assert client.post('/api/task-updates',headers=headers,json=payload).status_code==400


@pytest.mark.parametrize('channel',['webhook','a2a'])
def test_inbox_confirmation_then_challenge_and_marketing_scope(delivery,channel):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    body={**data,'channel':channel,'url':'https://inbox.example/private-inbox','marketing':True,'marketing_notice_version':MARKETING_NOTICE}
    assert client.post('/api/task-updates',headers=headers,json={**body,'destination_confirmed':False}).status_code==400
    row=client.post('/api/task-updates',headers=headers,json=body).json()
    assert not row['marketing_eligible'] and not row['destination_verified']
    code=courier.challenges[-1]['verification_code'];path=f"/api/task-updates/{row['id']}/action"
    verified=client.post(path,headers=headers,json={'action':'verify','code':code}).json()
    assert verified['marketing_eligible'] and verified['destination_verified']
    from agent_market.gateway.visitor_desk import VisitorDesk
    desk=VisitorDesk(store,front.updates)
    result=desk.list(contact='marketing')
    assert result['filtered_stats']['marketing_eligible']==1 and result['items'][0]['marketing_eligible_contacts']==1
    public=front.updates.admin_summary(front.updates._get(row['id']))
    assert public['destination']=='https://inbox.example/…' and 'private-inbox' not in json.dumps(public)
    withdrawn=client.post(path,headers=headers,json={'action':'withdraw_marketing'}).json()
    assert withdrawn['state']=='active' and not withdrawn['marketing_eligible']
    assert desk.list(contact='marketing')['filtered_stats']['total']==0
    assert front.updates.dispatch_campaign(vid,'marketing')['status']=='permission_denied'


def test_duplicate_requests_are_not_recorded_twice(delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    enroll(delivery)
    assert client.post('/api/task-updates',headers=headers,json=payload).status_code==400
    assert len(store.query('SELECT * FROM agent_task_watches'))==1 and len(push.sent)==1


def test_a2a_agent_card_cannot_switch_to_an_unconfirmed_origin(delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    courier.resolve=lambda channel,url:{'url':'https://different.example/inbox','v1':False}
    row=client.post('/api/task-updates',headers=headers,json={**data,'channel':'a2a','url':'https://card.example/.well-known/agent-card.json'}).json()
    assert front.updates._get(row['id'])['state']=='failed' and not courier.challenges


def test_webpush_encryption_vapid_and_no_inherited_credentials():
    sub,private,auth=subscription();requests=[]
    def handle(request):requests.append(request);return httpx.Response(201)
    client=httpx.Client(transport=httpx.MockTransport(handle),headers={'Authorization':'Bearer inherited-secret','Cookie':'session=private'},auth=('private','credential'))
    push=BrowserPush(b'a'*32,client)
    payload={'type':'browser_verification','challenge':'test-only-proof'}
    assert push.send(sub,payload)==(True,None)
    request=requests[0]
    assert request.headers['authorization'].startswith('vapid ') and 'inherited-secret' not in str(request.headers)
    assert request.headers['cookie']=='' and request.headers['content-encoding']=='aes128gcm'
    decoded=http_ece.decrypt(request.content,private_key=private,auth_secret=auth,version='aes128gcm')
    assert json.loads(decoded)==payload and b'test-only-proof' not in request.content
    assert BrowserPush(b'a'*32).public_key==push.public_key
    client.close()


def test_push_dns_private_address_is_blocked_at_connection(monkeypatch):
    monkeypatch.setattr('agent_market.concierge.http_security._resolve_addresses',lambda *args:['127.0.0.1'])
    sub,_,_=subscription()
    assert BrowserPush(b'b'*32).send(sub,{'type':'task_update'})==(False,'delivery_failed')


def test_cancelled_watch_does_not_reappear_when_queued_worker_runs(delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    row,message=enroll(delivery);proof(client,message)
    add('Newer Verified Browser Weather',report_at=time.time())
    front.updates.refresh(vid)
    event=dict(store.query('SELECT * FROM agent_task_events')[0])
    front.updates.decline(vid,row['id'])
    front.updates.send_challenge(row['id'])
    assert front.updates._attempt(event) is None
    assert not store.query('SELECT * FROM agent_task_watches') and len(push.sent)==1
    assert store.query("SELECT action FROM agent_task_permissions WHERE purpose='marketing' ORDER BY at DESC")[0]['action']=='withdrawn'


def test_declining_requests_cannot_reset_registration_abuse_limits(delivery):
    store,front,client,add,headers,courier,data,vid,push,payload=delivery
    for index in range(5):
        row=front.updates.create(vid,{**payload,'task':'weather forecast '+str(index)})
        front.updates.decline(vid,row['id'])
    with pytest.raises(ValueError,match='Please wait'):
        front.updates.create(vid,payload)
    assert not store.query('SELECT * FROM agent_task_watches') and not push.sent
