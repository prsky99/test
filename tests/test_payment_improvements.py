"""Payment regression matrix: isolated proofs, fake providers, no real funds."""
import base64
import copy
import json
from unittest.mock import Mock

import httpx
import pytest

from agent_market.concierge.payment_wire import payment_headers, settlement_response, PaymentWireError
from agent_market.concierge.managed_gateway import challenge
from agent_market.workspace_x402_eip3009 import EIP3009Invalid
from tests.test_workspace_x402_eip3009 import fixture as proof, verify, NOW
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_security_audit import target, rpc  # noqa: F401


def encoded(value):return base64.b64encode(json.dumps(value).encode()).decode()


def test_native_v1_and_v2_proofs_are_not_rewritten():
    payment,_=proof();v2=encoded(payment)
    v1=encoded({'x402Version':1,'scheme':'exact','network':'base-sepolia','payload':payment['payload']})
    assert payment_headers({'headers':{'PAYMENT-SIGNATURE':v2}})=={'payment-signature':v2}
    assert payment_headers({'headers':{'X-PAYMENT':v1}})=={'x-payment':v1}


@pytest.mark.parametrize('headers',[
    {'Host':'private.example'}, {'Authorization':'Bearer secret'}, {'Cookie':'secret'},
    {'PAYMENT-SIGNATURE':'not base64'}, {'X-PAYMENT':'A'*60000},
    {'X-PAYMENT':'AAAA','x-payment':'AAAA'},
    {'PAYMENT-SIGNATURE':encoded({'x402Version':True,'payload':{}})},
    {'PAYMENT-SIGNATURE':encoded({'x402Version':1,'payload':{}})},
    {'PAYMENT-SIGNATURE':encoded({'x402Version':2,'payload':{}})},
    {'PAYMENT-SIGNATURE':encoded({'x402Version':2,'payload':{},'accepted':{}}),'X-PAYMENT':'AAAA'},
])
def test_untrusted_header_injection_and_ambiguous_proofs_are_rejected(headers):
    with pytest.raises(PaymentWireError):payment_headers({'headers':headers})


@pytest.mark.parametrize('wire',[b'{"x402Version":2,"x402Version":1}',b'{"value":NaN}',
    b'{"value":1e999}',b'{"a":'+b'['*20+b'0'+b']'*20+b'}'])
def test_malformed_canonical_challenge_cannot_fall_back_to_an_untrusted_body(wire):
    body={'x402Version':1,'error':'payment required','accepts':[]}
    response=httpx.Response(402,json=body,headers={'PAYMENT-REQUIRED':base64.b64encode(wire).decode()})
    assert challenge(response) is None


@pytest.mark.parametrize('change,code,stage',[
    ('version','invalid_x402_version','version'),
    ('scheme','invalid_scheme','scheme'),
    ('network','invalid_network','network'),
    ('recipient','invalid_exact_evm_payload_recipient_mismatch','recipient'),
    ('amount','invalid_exact_evm_payload_authorization_value_mismatch','amount'),
    ('future','invalid_exact_evm_payload_authorization_valid_after','validity'),
    ('expired','invalid_exact_evm_payload_authorization_valid_before','validity'),
    ('signature','invalid_exact_evm_payload_signature','signature'),
])
def test_offline_validation_exposes_the_first_safe_protocol_reason(change,code,stage):
    payment,required=proof();auth=payment['payload']['authorization']
    if change=='version':payment['x402Version']=3;payment['accepted']['network']='unsupported'
    if change=='scheme':payment['accepted']['scheme']='unsupported'
    if change=='network':payment['accepted']['network']='eip155:1'
    if change=='recipient':auth.update(to='0x'+'22'*20,value='1',validBefore='1')
    if change=='amount':auth.update(value='1',validBefore='1')
    if change=='future':auth['validAfter']=str(NOW+1)
    if change=='expired':auth['validBefore']=str(NOW-1)
    if change=='signature':payment['payload']['signature']='0x'+'00'*65
    with pytest.raises(EIP3009Invalid) as error:verify(payment,required)
    assert (error.value.error_code,error.value.stage)==(code,stage)
    assert '0x' not in str(error.value)


def test_legacy_malformed_proofs_do_not_contact_rpc():
    from agent_market.payments import PaymentVerifier,PaymentError
    rpc=Mock();verifier=PaymentVerifier(rpc,'0x'+'11'*20,'0x'+'22'*20)
    for tx,signature in [('0x'+'g'*64,'0x'+'11'*65),('0x'+'11'*32,'malformed')]:
        with pytest.raises(PaymentError) as error:verifier.verify(tx,signature,b'{}',1)
        assert error.value.stage=='format'
    rpc.receipt.assert_not_called()
    rpc.receipt.side_effect=RuntimeError('secret RPC configuration')
    with pytest.raises(PaymentError) as error:verifier.verify('0x'+'11'*32,'0x'+'11'*64+'1b',b'{}',1)
    assert error.value.status==503 and error.value.error_code=='PAYMENT_VERIFICATION_UNAVAILABLE'
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('method',['get','post'])
@pytest.mark.parametrize('header',['PAYMENT-SIGNATURE','X-PAYMENT','X-Payment-Tx'])
def test_public_probe_never_processes_or_forwards_an_attached_payment(catalog,method,header):
    _,front,client,add,now=catalog
    rid=add('Payment probe',kind='x402',price=100)
    front.security.allow_probe=lambda *a,**kw:True
    front.managed_gateway.execute=Mock(side_effect=AssertionError('Proof must not dispatch'))
    kwargs={'headers':{header:'untrusted-proof'}}
    if method=='post':kwargs['json']={'action':'probe'}
    response=getattr(client,method)(f'/api/gateway/x402/{rid}',**kwargs)
    assert response.status_code==501 and response.json()['error_code']=='PAYMENT_EXECUTION_DISABLED'
    assert response.json()['payment_processed'] is False
    front.managed_gateway.execute.assert_not_called()
    assert 'untrusted-proof' not in response.text


def test_credit_database_error_is_structured_and_does_not_leak(target,monkeypatch):
    front,client=target
    hello=rpc(client,'hello',{})['result']['structuredContent']['visitor']
    monkeypatch.setattr(front.clearinghouse,'balance',Mock(side_effect=RuntimeError('private database path and token')))
    data=rpc(client,'credit',{'action':'balance'},hello['token'])
    assert data['error']['code']==-32603
    assert data['error']['data']['error_code']=='CREDIT_BALANCE_UNAVAILABLE'
    assert 'private database' not in json.dumps(data)


def test_public_schema_excludes_private_routes_and_unused_definitions(catalog):
    _,_,client,_,_=catalog
    schema=client.get('/openapi.json').json();raw=json.dumps(schema)
    assert '/api/agent/v1/discover' in schema['paths']
    assert '/api/explore' in schema['paths'] and '/api/gateway/{kind}/{rid}' in schema['paths']
    for text in ('/admin','/customer/','/api/customer-auth','/api/customer-organizations','/api/workspace-apps-v2'):
        assert text not in raw


def test_missing_and_pending_receipts_are_not_confirmed_payment():
    assert settlement_response(httpx.Response(200)) is None
    pending={'success':False,'errorReason':'settlement_pending','transaction':'0x'+'11'*32,'network':'eip155:84532'}
    assert settlement_response(httpx.Response(402,headers={'PAYMENT-RESPONSE':encoded(pending)}))==pending
    pending['transaction']=''
    with pytest.raises(PaymentWireError):settlement_response(httpx.Response(402,headers={'PAYMENT-RESPONSE':encoded(pending)}))


@pytest.mark.parametrize('outcome',['missing_receipt','timeout','pending','accepted','invalid_signature','wrong_network','wrong_amount','wrong_payer'])
def test_uncertain_payment_keeps_escrow_and_never_auto_retries(catalog,outcome):
    from agent_market.concierge.proxy import McpProxy
    store,_,_,add,_=catalog
    rid=add('Payment provider',kind='x402',price=100)
    payment,_=proof();calls=[]
    body={'x402Version':2,'resource':payment['resource'],'error':'invalid_exact_evm_payload_signature',
          'accepts':[payment['accepted']]}
    def provider(request):
        calls.append(1)
        assert request.headers['payment-signature']==encoded(payment)
        assert 'authorization' not in request.headers and 'cookie' not in request.headers
        if outcome=='timeout':raise httpx.ReadTimeout('untrusted private transport detail')
        headers={};status=200
        if outcome in ('accepted','wrong_network','wrong_amount','wrong_payer'):
            receipt={'success':True,'transaction':'0x'+'11'*32,'network':'eip155:84532'}
            if outcome=='wrong_network':receipt['network']='eip155:1'
            if outcome=='wrong_amount':receipt['amount']='1'
            if outcome=='wrong_payer':receipt['payer']='0x'+'22'*20
            headers['PAYMENT-RESPONSE']=encoded(receipt)
        if outcome=='pending':
            status=402;headers['PAYMENT-RESPONSE']=encoded({'success':False,'transaction':'0x'+'11'*32,
                'network':'eip155:84532','errorReason':'settlement_pending'})
        if outcome=='invalid_signature':
            status=402;headers['PAYMENT-REQUIRED']=encoded(body)
        return httpx.Response(status,json={'value':'Controlled provider result'},headers=headers)
    proxy=McpProxy(store,allow_private=True,http=httpx.Client(transport=httpx.MockTransport(provider)))
    proxy.clearinghouse.deposit('synthetic-payment-owner',1000)
    result=proxy.execute(rid,'request',{},account_id='synthetic-payment-owner',
                         payment={'headers':{'PAYMENT-SIGNATURE':encoded(payment)}})
    assert calls==[1]
    credit=proxy.clearinghouse.balance('synthetic-payment-owner')
    if outcome in ('missing_receipt','timeout','pending','wrong_network','wrong_amount','wrong_payer'):
        assert not result['ok'] and result['retry_safe'] is False
        assert result['payment']['status']=='held' and credit['held']==100
        assert result['payment']['automatic_refund'] is False
        assert 'untrusted private' not in json.dumps(result)
    elif outcome=='accepted':
        assert result['ok'] and result['settlement_verified'] is False
        assert result['payment_response']['success'] is True and credit['held']==0
    else:
        assert not result['ok'] and result['retry_safe'] is True and credit['held']==0
        assert result['error_code']=='invalid_exact_evm_payload_signature'


def test_unknown_seller_failure_preserves_claim_and_forbids_automatic_retry():
    from tests.test_market import FakeChain,FakeWorker,NET,SELLER,BUYER,paid_post
    from agent_market.config import SellerConfig,usdc
    from agent_market.server import create_app
    from agent_market.payments import PaymentVerifier
    from agent_market.ledger import Ledger
    from fastapi.testclient import TestClient
    chain=FakeChain();worker=FakeWorker();worker.fail=RuntimeError('unconfirmed worker outcome')
    ledger=Ledger()
    config=SellerConfig(NET,SELLER.address,':memory:','test-admin',1)
    app=create_app(config,verifier=PaymentVerifier(chain,NET.token,SELLER.address),worker=worker,ledger=ledger)
    client=TestClient(app)
    tx=chain.add_transfer(BUYER.address,SELLER.address,usdc('0.02'))
    response=paid_post(client,tx,{'input':'Synthetic invoice input'})
    assert response.status_code==502 and response.json()['retry_with_same_payment'] is False
    assert ledger.stats()['pending_tx']==1
    worker.fail=None
    repeated=paid_post(client,tx,{'input':'Synthetic invoice input'})
    assert repeated.status_code==409 and repeated.json()['error_code']=='PAYMENT_REPLAY'
    ledger.close()


def test_gateway_limit_has_retry_and_quota_headers_without_an_upstream_call(catalog):
    _,front,client,add,_=catalog;rid=add('Quota check',kind='mcp')
    front.security.redis=Mock(is_available=Mock(return_value=False))
    for number in range(30):
        response=client.post(f'/api/gateway/mcp/{rid}',json={'jsonrpc':'2.0','id':1,'method':'ping'})
        assert 'RateLimit-Policy' in response.headers and 'RateLimit' in response.headers
        if response.status_code==429:
            assert int(response.headers['Retry-After'])>0
            break
    else:pytest.fail('The gateway quota was not enforced')


@pytest.mark.parametrize('allowed',[True,False])
def test_distributed_limit_reports_only_known_remaining_without_a_second_counter_read(catalog,allowed):
    _,front,client,add,_=catalog;rid=add('Distributed quota',kind='mcp')
    hub=Mock(is_available=Mock(return_value=True),sliding_window_snapshot=None,check_sliding_window=Mock(return_value=allowed),
             is_ip_jailed=Mock(return_value=(False,None)))
    front.security.redis=hub
    response=client.post(f'/api/gateway/mcp/{rid}',json={'jsonrpc':'2.0','id':1,'method':'ping'})
    assert 'RateLimit-Policy' in response.headers
    hub.check_sliding_window.assert_called_once()
    if allowed:
        assert response.status_code==200 and 'RateLimit' not in response.headers
    else:
        assert response.status_code==429
        assert ';r=0;' in response.headers['RateLimit']
        assert int(response.headers['Retry-After'])>0
