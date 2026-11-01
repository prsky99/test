"""Real loopback TLS sockets, real Courier, and isolated task-update APIs."""
import hashlib
import hmac
import json
import ssl
import time

import httpx
import pytest
from fastapi import HTTPException

from agent_market.concierge.notify import Courier
from agent_market.concierge.task_updates import NOTICE_VERSION, DESTINATION_NOTICE, MARKETING_NOTICE
from scripts.notification_test_inbox import running_inbox
from tests.test_fast_single_recommendation import catalog, ask  # noqa: F401

ORIGIN = 'https://inbox.example'
CASES = [('webhook','/webhook'),('a2a','/.well-known/agent-card.json'),
         ('a2a','/.well-known/agent-card-v1.json'),('a2a','/a2a')]


class LoopbackTransport(httpx.BaseTransport):
    """Only the test logical origin maps to our temporary, certificate-verified socket."""
    def __init__(self, origin, cert):
        self.origin = httpx.URL(origin)
        self.inner = httpx.HTTPTransport(verify=ssl.create_default_context(cafile=str(cert)),trust_env=False)
        self.requests = []

    def handle_request(self, request):
        assert request.url.scheme=='https' and request.url.host=='inbox.example' and request.url.port in (None,443)
        raw = request.read()
        self.requests.append((request.method,str(request.url),dict(request.headers),raw))
        mapped = request.url.copy_with(host='127.0.0.1',port=self.origin.port)
        return self.inner.handle_request(httpx.Request(request.method,mapped,headers=request.headers,content=raw,extensions=request.extensions))

    def close(self):
        self.inner.close()


@pytest.fixture
def network(monkeypatch):
    with running_inbox(advertised_origin=ORIGIN) as (app,origin,cert):
        def synthetic_dns(host,port,timeout):
            assert host=='inbox.example'
            return ['93.184.216.34']
        # Only logical test DNS is substituted. TLS bytes use real loopback sockets.
        monkeypatch.setattr('agent_market.concierge.http_security._resolve_addresses',synthetic_dns)
        transport = LoopbackTransport(origin,cert)
        with httpx.Client(transport=transport,trust_env=False,timeout=5,
                          headers={'Authorization':'Bearer must-not-cross','Cookie':'session=must-not-cross'},auth=('private','credential')) as client:
            courier = Courier(False,http=client)
            with httpx.Client(verify=ssl.create_default_context(cafile=str(cert)),trust_env=False,timeout=5) as receiver:
                yield app,origin,cert,courier,transport,receiver


def receipts(network):
    app,origin,_,_,_,receiver = network
    response = receiver.get(origin+'/receipts',headers={'Authorization':'Bearer '+app.state.inbox.token})
    assert response.status_code==200,response.text
    return response.json()


def register(catalog,network,channel,path):
    store,front,client,add,now = catalog
    add('Initial Weather',report_at=now-10)
    visitor = ask(client)['visitor']
    owner = {'X-Visitor-Token':visitor['token']}
    front.updates.courier = network[3]
    body = {'task':'weather forecast','protocol':'mcp','channel':channel,'url':ORIGIN+path,
            'authority':True,'task_updates':True,'notice_version':NOTICE_VERSION,
            'destination_confirmed':True,'destination_notice_version':DESTINATION_NOTICE,
            'marketing':True,'marketing_notice_version':MARKETING_NOTICE}
    response = client.post('/api/task-updates',headers=owner,json=body)
    assert response.status_code==201,response.text
    return response.json(),owner,visitor['id']


@pytest.mark.parametrize('channel,path',CASES)
def test_real_https_inbox_verification_signed_delivery_and_stop(catalog,network,channel,path):
    store,front,client,add,now = catalog
    row,owner,vid = register(catalog,network,channel,path)
    received = receipts(network)
    assert len(received['challenges'])==1, row
    assert row['state']=='pending_verification' and not row['marketing_eligible'] and not received['events']
    newest = add('Newest TLS Weather',report_at=time.time())
    assert front.updates.run_due(vid)['sent']==0 and not receipts(network)['events']
    code = received['challenges'][0]['verification_code']
    response = client.post('/api/task-updates/'+row['id']+'/action',headers=owner,json={'action':'verify','code':code})
    assert response.status_code==200 and response.json()['marketing_eligible']
    assert front.updates.run_due(vid)['sent']==1
    received = receipts(network)
    assert len(received['events'])==1 and received['events'][0]['signature_valid']
    assert received['events'][0]['recommendation_id']==newest
    assert len(receipts(network)['events'])==1 and front.updates.run_due(vid)['sent']==0
    for method,url,headers,raw in network[4].requests:
        assert not headers.get('authorization') and not headers.get('cookie')
        assert 'X-Visitor-Token'.lower() not in headers and owner['X-Visitor-Token'].encode() not in raw
    assert 'signing_secret' not in json.dumps(received) and 'secret' not in client.get('/api/task-updates',headers=owner).text
    assert client.post('/api/task-updates/'+row['id']+'/action',headers=owner,json={'action':'stop'}).status_code==200
    add('Later TLS Weather',report_at=time.time()+1)
    front.updates.run_due(vid)
    assert len(receipts(network)['events'])==1 and front.updates._get(row['id'])['sealed'] is None


def delivered(catalog,network,channel='webhook',path='/webhook'):
    row,owner,vid = register(catalog,network,channel,path)
    code = receipts(network)['challenges'][0]['verification_code']
    catalog[2].post('/api/task-updates/'+row['id']+'/action',headers=owner,json={'action':'verify','code':code})
    catalog[3]('New Signature Weather',report_at=time.time())
    assert catalog[1].updates.run_due(vid)['sent']==1
    method,url,headers,raw = next(request for request in reversed(network[4].requests) if request[2].get('x-agent-signature'))
    return method,url,{k:v for k,v in headers.items() if k not in ('content-length','host')},raw


@pytest.mark.parametrize('channel,path',CASES[:3])
def test_signed_duplicate_is_idempotent_and_tampering_is_rejected(catalog,network,channel,path):
    method,url,headers,raw = delivered(catalog,network,channel,path)
    local = network[1]+httpx.URL(url).path
    receiver = network[5]
    assert receiver.post(local,headers=headers,content=raw).status_code==200
    assert len(receipts(network)['events'])==1
    assert receiver.post(local,headers=headers,content=raw+b' ').status_code==401
    assert receiver.post(local,headers={**headers,'x-agent-signature':'sha256='+'0'*64},content=raw).status_code==401
    assert receiver.post(local,headers={**headers,'x-agent-timestamp':str(int(time.time())-301)},content=raw).status_code==401
    assert receiver.post(local,headers={k:v for k,v in headers.items() if k!='x-agent-signature'},content=raw).status_code==401
    body = json.loads(raw)
    payload = body if channel=='webhook' else body['params']['message']['parts'][0]['data']
    stamp = str(int(headers['x-agent-timestamp'])+1)
    payload['timestamp'] = int(stamp)
    retry_raw = json.dumps(body,separators=(',',':')).encode()
    key = network[0].state.inbox.registrations[headers['x-agent-key-id']]['secret']
    signature = 'sha256='+hmac.new(key.encode(),stamp.encode()+b'.'+retry_raw,hashlib.sha256).hexdigest()
    retry_headers = {**headers,'x-agent-timestamp':stamp,'x-agent-signature':signature}
    assert receiver.post(local,headers=retry_headers,content=retry_raw).status_code==200
    assert len(receipts(network)['events'])==1
    payload['recommendation'] = None
    conflicting = json.dumps(body,separators=(',',':')).encode()
    conflicting_signature = 'sha256='+hmac.new(key.encode(),stamp.encode()+b'.'+conflicting,hashlib.sha256).hexdigest()
    assert receiver.post(local,headers={**retry_headers,'x-agent-signature':conflicting_signature},content=conflicting).status_code==409
    assert len(receipts(network)['events'])==1


@pytest.mark.parametrize('channel,path',CASES[:3])
@pytest.mark.parametrize('status',[503,410])
def test_real_delivery_failure_retries_or_revokes(catalog,network,monkeypatch,channel,path,status):
    store,front,client,add,now = catalog
    row,owner,vid = register(catalog,network,channel,path)
    code = receipts(network)['challenges'][0]['verification_code']
    client.post('/api/task-updates/'+row['id']+'/action',headers=owner,json={'action':'verify','code':code})
    add('Failure Handling Weather',report_at=time.time())
    inbox = network[0].state.inbox
    original = inbox.receive
    def unavailable(*args,**kwargs):
        raise HTTPException(status,'Controlled receiver response.')
    monkeypatch.setattr(inbox,'receive',unavailable)
    assert front.updates.run_due(vid)['failed']==1 and not receipts(network)['events']
    if status==410:
        stopped = front.updates._get(row['id'])
        assert stopped['state']=='revoked' and stopped['sealed'] is None
        assert not front.updates.admin_summary(stopped)['marketing_eligible']
    else:
        event = dict(store.query('SELECT * FROM agent_task_events')[0])
        assert event['status']=='pending' and event['attempts']==1 and event['next_attempt']>time.time()
        monkeypatch.setattr(inbox,'receive',original)
        with store.tx() as db:
            db.execute('UPDATE agent_task_events SET next_attempt=? WHERE id=?',(time.time()-1,event['id']))
        assert front.updates.run_due(vid)['sent']==1
        assert len(receipts(network)['events'])==1
        assert store.query('SELECT attempts FROM agent_task_events')[0]['attempts']==2


@pytest.mark.parametrize('channel,path',CASES[1:3])
def test_http_success_without_a2a_result_is_not_delivery_success(catalog,network,monkeypatch,channel,path):
    store,front,client,add,now = catalog
    row,owner,vid = register(catalog,network,channel,path)
    code = receipts(network)['challenges'][0]['verification_code']
    client.post('/api/task-updates/'+row['id']+'/action',headers=owner,json={'action':'verify','code':code})
    add('Invalid Acknowledgement Weather',report_at=time.time())
    def invalid_result(*args,**kwargs):
        raise HTTPException(200,'Not an A2A acknowledgement.')
    monkeypatch.setattr(network[0].state.inbox,'receive',invalid_result)
    assert front.updates.run_due(vid)['failed']==1
    assert store.query('SELECT status FROM agent_task_events')[0]['status']=='pending'
    assert not receipts(network)['events']


def test_inbox_receipt_access_and_body_boundaries(network):
    app,origin,cert,courier,transport,receiver = network
    assert receiver.get(origin+'/receipts').status_code==401
    assert receiver.get(origin+'/receipts',headers={'Authorization':'Bearer wrong'}).status_code==401
    assert receiver.get(origin+'/receipts',headers={'Authorization':'Bearer '+app.state.inbox.token,'Origin':'https://evil.example'}).status_code==403
    assert receiver.post(origin+'/webhook',content=b'x'*65537,headers={'Content-Type':'application/json'}).status_code==413
    assert receiver.post(origin+'/webhook',content='[]',headers={'Content-Type':'application/json'}).status_code==400
    assert receiver.post(origin+'/webhook',content='{',headers={'Content-Type':'application/json'}).status_code==400
    assert receiver.post(origin+'/webhook',content='{}',headers={'Content-Type':'text/plain'}).status_code==415
    assert receiver.post(origin+'/webhook',content='{}',headers={'Content-Type':'application/json','Content-Encoding':'gzip'}).status_code==415
    assert not receipts(network)['challenges'] and not receipts(network)['events']


def test_untrusted_tls_certificate_is_rejected(network):
    with httpx.Client(trust_env=False,timeout=2) as untrusted:
        with pytest.raises(httpx.ConnectError,match='CERTIFICATE_VERIFY_FAILED'):
            untrusted.get(network[1]+'/.well-known/agent-card.json')


def test_test_listener_does_not_weaken_product_destination_rules(catalog,network):
    store,front,client,add,now = catalog
    visitor=ask(client)['visitor']
    body={'task':'weather forecast','channel':'webhook','url':network[1]+'/webhook','authority':True,'task_updates':True,
          'notice_version':NOTICE_VERSION,'destination_confirmed':True,'destination_notice_version':DESTINATION_NOTICE}
    assert client.post('/api/task-updates',headers={'X-Visitor-Token':visitor['token']},json=body).status_code==400
    assert not store.query('SELECT * FROM agent_task_watches') and not receipts(network)['challenges']
