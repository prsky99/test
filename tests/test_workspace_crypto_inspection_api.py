"""Offline cryptographic inspection is separate from payment authority."""
import pytest
from types import SimpleNamespace

from agent_market.workspace_protocol_conformance import CRYPTO_NOTICE
from tests.test_workspace_x402_eip3009 import fixture, FROM, NONCE, NOW, URL
from tests.test_workspace_protocol_conformance_api import conformance_api
from tests.test_workspace_protocol_conformance import conformance
from tests.test_workspace_sandbox_payments import sandbox
from tests.test_workspace_agreements import agreement
from tests.test_provider_claims import provider


def body():
    payment,requirements=fixture()
    return {'payment':payment,'requirements':requirements,'expected_from':FROM,'expected_nonce':NONCE,
            'resource_url':URL,'authorized':True,'notice':CRYPTO_NOTICE}


def test_exact_offline_proof_never_creates_a_payment_or_exposes_sender(conformance_api,monkeypatch):
    w=conformance_api
    monkeypatch.setattr('agent_market.workspace_x402_eip3009.time',SimpleNamespace(time=lambda:NOW))
    result=w.api.post(w.base+'/cryptographic-check',headers=w.headers,json=body())
    assert result.status_code==200,result.text
    value=result.json()['result']
    assert value['signature_valid'] and not value['verified_payment'] and not value['settlement_authorized']
    assert value['rpc_calls']==value['broadcasts']==value['ledger_events']==0
    assert 'recovered_from' not in value and FROM not in result.text
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_intents').fetchone()[0]==0
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_protocol_reports').fetchone()[0]==0


@pytest.mark.parametrize('change',['anonymous','cross_origin','unapproved','wrong_nonce'])
def test_inspection_rejects_missing_authority_or_context(conformance_api,change):
    w=conformance_api;payload=body();headers=dict(w.headers)
    if change=='anonymous':headers={}
    if change=='cross_origin':headers['Origin']='https://elsewhere.invalid'
    if change=='unapproved':payload['authorized']=False
    if change=='wrong_nonce':payload['expected_nonce']='0x'+'22'*32
    result=w.api.post(w.base+'/cryptographic-check',headers=headers,json=payload)
    assert result.status_code in (400,401,403,404)
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_intents').fetchone()[0]==0
