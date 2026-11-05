"""Public ingestion contracts; isolated catalogs, no provider tools or messages."""
import json
import time
from datetime import datetime, timezone

import httpcore
import httpx
import pytest

from agent_market.concierge import registration_policy as policy
from agent_market.concierge import registration_inspection as inspection
from agent_market.concierge.front import submit_register_agent
from agent_market.concierge.public_inquiries import record_inquiry, validated_inquiry
from tests.test_concierge import w


def consent(offset=0):
    return {'agreed':True,'tos_version':'2026.1','privacy_version':'2026.1',
        'agreed_at':datetime.fromtimestamp(time.time()+offset,timezone.utc).isoformat(),'gpc_active':True}


def listing(**changes):
    return {'kind':'mcp','url':'https://public.example/mcp','name':'Example Agent',
        'description':'Find documentation using a public endpoint.','category':'dev_tools',
        'legal_consent':consent(), **changes}


def inquiry(**changes):
    return {'name':'QA Fixture','email':'fixture@example.com','subject':'Integration question',
        'message':'How can I connect this agent?', 'category':'technical', **changes}


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(policy,'_resolve_addresses',lambda *a:['8.8.8.8'])


@pytest.mark.parametrize('change',[None,{}, {'agreed':False},{'agreed':'true'},
    {'tos_version':'old'},{'privacy_version':'old'},{'agreed_at':'2026-10-27T00:00:00'},
    {'agreed_at':'invalid'}, {'gpc_active':'false'}])
def test_consent_rejects_before_network_and_storage(w,monkeypatch,change):
    world,client,_=w
    def no_dns(*a):raise AssertionError('No network before consent')
    monkeypatch.setattr(policy,'_resolve_addresses',no_dns)
    value=listing();value['legal_consent']={**consent(),**change} if change else change
    before=world.store.query('SELECT COUNT(*) FROM resources')[0][0]
    response=client.post('/api/register',json=value)
    assert response.status_code==400
    assert response.json()['field']=='legal_consent'
    assert world.store.query('SELECT COUNT(*) FROM resources')[0][0]==before


@pytest.mark.parametrize('offset',[-601,601])
def test_consent_expiry(offset):
    with pytest.raises(policy.PublicRequestError,match='') as error:
        policy.legal_consent({'legal_consent':consent(offset)})
    assert error.value.code=='CONSENT_EXPIRED'


@pytest.mark.parametrize('changes,field',[({'category':'zzz'},'category'),({'price_usdc':-1},'price_usdc'),
    ({'price_usdc':True},'price_usdc'),({'networks':['unknown']},'networks'),
    ({'networks':['base'],'pay_to':'not-a-wallet'},'pay_to'),({'name':'line\nname'},'name'),
    ({'description':[]},'description'),({'method':'DELETE'},'method')])
def test_registration_fields_strict(changes,field):
    with pytest.raises(policy.PublicRequestError) as error:policy.fields(listing(**changes))
    assert error.value.field==field


@pytest.mark.parametrize('url,code',[('https://agentconcierge.biz/mcp','SELF_ENDPOINT'),
    ('https://gateway.agentconcierge.biz/mcp','SELF_ENDPOINT'),
    ('https://name:pass@public.example/mcp','URL_CREDENTIALS')])
def test_own_service_and_credentials(url,code,public_dns):
    with pytest.raises(policy.PublicRequestError) as error:policy.public_endpoint(url)
    assert error.value.code==code


def test_dns_and_private_errors(monkeypatch):
    for failure,code in [(httpcore.ConnectError('secret'), 'DNS_FAILED'),(httpcore.ConnectTimeout('secret'),'DNS_TIMEOUT')]:
        def fail(*a):raise failure
        monkeypatch.setattr(policy,'_resolve_addresses',fail)
        with pytest.raises(policy.PublicRequestError) as error:policy.public_endpoint('https://public.example')
        assert error.value.code==code and 'secret' not in error.value.detail
    monkeypatch.setattr(policy,'_resolve_addresses',lambda *a:['127.0.0.1'])
    with pytest.raises(policy.PublicRequestError) as error:policy.public_endpoint('http://localhost')
    assert error.value.code=='PRIVATE_DESTINATION'


def test_protocol_validation_without_tool_execution(public_dns):
    calls=[]
    def remote(request):
        calls.append(json.loads(request.content or '{}').get('method'))
        method=calls[-1]
        if method=='initialize':return httpx.Response(200,json={'jsonrpc':'2.0','id':1,'result':{
            'protocolVersion':'2025-11-25','serverInfo':{'name':'Docs','version':'1'},'capabilities':{'tools':{}}}})
        if method=='tools/list':return httpx.Response(200,json={'jsonrpc':'2.0','id':2,'result':{'tools':[{'name':'search_docs'}]}})
        return httpx.Response(202)
    with httpx.Client(transport=httpx.MockTransport(remote)) as client:
        found=inspection.mcp_or_payment(client,'https://public.example/mcp')
    assert found['kind']=='mcp' and found['details']['tools']==['search_docs']
    assert 'tools/call' not in calls
    for payload in ({'name':'Only a name'}, {'name':'Docs','skills':[]}, {'name':'Docs','skills':[{'id':'search'}],'url':'https://public.example/a2a'}):
        result=inspection.a2a_card(httpx.Response(200,json=payload),'https://public.example/card')
        assert bool(result)==bool(payload.get('url'))
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'result':{'capabilities':{}}}))) as client:
        assert inspection.mcp_or_payment(client,'https://public.example') is None


def test_payment_requires_402_and_valid_requirements():
    item={'scheme':'exact','network':'eip155:8453','asset':inspection.USDC['base'],
        'amount':'1000','payTo':'0x'+'1'*40}
    for status,body,expected in [(200,{'accepts':[item]},False),(402,{},False),
        (402,{'accepts':[{**item,'payTo':'bad'}]},False),(402,{'accepts':[item]},True)]:
        assert bool(inspection.payment(httpx.Response(status,json=body)))==expected
    address=inspection.USDC['solana']
    assert policy.wallet(address,['solana'])==address


def register_valid(store,monkeypatch):
    monkeypatch.setattr('agent_market.concierge.front.inspect_register_url',lambda *a,**k:{
        'protocol_verified':True,'kind':'mcp','details':{'tools':['search_docs']},'status_code':200,'latency_ms':1})
    return submit_register_agent(store,listing(details={'tools':['injected']}),'qa-fixture')


def test_atomic_private_receipt(w,monkeypatch,public_dns):
    world,client,_=w
    result=register_valid(world.store,monkeypatch)
    resource=world.store.resource(result['id'])
    assert json.loads(resource['details'])['tools']==['search_docs']
    receipt=json.loads(world.store.query("SELECT detail FROM security_events WHERE event_type='registration_consent'")[0][0])
    assert receipt['resource_id']==result['id'] and receipt['gpc_active'] is True
    assert 'consent' not in resource['details']
    with pytest.raises(policy.PublicRequestError) as error:register_valid(world.store,monkeypatch)
    assert error.value.status_code==409


@pytest.mark.parametrize('field,value',[('name','QA\r\nBcc: other@example.com'),('subject','Question\x00Bcc'),
    ('email','qa@example.com\nBcc:other@example.com'),('subject','Question\u2028Bcc'),
    ('message','<script>alert(1)</script>'),('category','zzz')])
def test_contact_rejects_controls_and_empty_sanitized_message(field,value):
    with pytest.raises(policy.PublicRequestError):validated_inquiry(inquiry(**{field:value}))


def test_inquiry_dedup_and_quota(w):
    world,client,_=w
    first=client.post('/api/contact/submit',json=inquiry());assert first.status_code==200,first.text
    second=client.post('/api/contact/submit',json=inquiry());assert second.json()['duplicate'] is True
    assert second.json()['inquiry_id']==first.json()['inquiry_id']
    for index in range(4):assert client.post('/api/contact/submit',json=inquiry(subject='Question '+str(index))).status_code==200
    response=client.post('/api/contact/submit',json=inquiry(subject='Over quota'))
    assert response.status_code==429 and response.headers['retry-after']=='3600'
    assert 'contact-email' in response.headers['ratelimit-policy']
    assert not world.app.state.front.security.is_blocked('127.0.0.1')[0]


def test_required_privacy_type_and_independent_limits(w):
    world,client,_=w
    assert client.post('/api/privacy/opt-out',json={}).status_code==422
    security=world.app.state.front.security
    for _ in range(10):assert security.allow_feature('qa-ip','registration_inspect',10)
    for _ in range(6):
        assert not security.allow_feature('qa-ip','registration_inspect',10)
        security.record_violation('qa-ip','rate_limit_429','/api/register/inspect','POST',None,'quota')
    assert not security.is_blocked('qa-ip')[0]
    assert security.allow_feature('qa-ip','contact_submit',15)
    assert security.allow_probe('qa-ip')


def test_registration_rolls_back_if_private_receipt_fails(w,monkeypatch,public_dns):
    world,client,_=w
    with world.store.tx() as db:
        db.execute("CREATE TRIGGER reject_fixture_receipt BEFORE INSERT ON security_events WHEN NEW.event_type='registration_consent' BEGIN SELECT RAISE(ABORT,'fixture receipt failure'); END")
    with pytest.raises(Exception):register_valid(world.store,monkeypatch)
    assert not world.store.query('SELECT id FROM resources WHERE url=?',('https://public.example/mcp',))
    assert not world.store.query("SELECT id FROM security_events WHERE event_type='registration_consent'")
