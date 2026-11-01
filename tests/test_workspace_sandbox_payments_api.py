"""Named-session sandbox API cannot serve as a public/live payment webhook."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.advancement_service import router_for
from agent_market.workspace_sandbox_payments import PREPARE_NOTICE,EXECUTE_NOTICE
from tests.test_workspace_sandbox_payments import sandbox
from tests.test_workspace_agreements import agreement
from tests.test_provider_claims import provider


@pytest.fixture
def sandbox_api(sandbox):
    w=sandbox;app=FastAPI();app.include_router(router_for(w.access,agreements=w.agreements,sandbox_payments=w.payments))
    w.api=TestClient(app,base_url='https://private.test');w.base='/admin/api/workflow-workspaces/'+w.ws+'/advancement'
    w.header={'X-Dashboard':'1','Authorization':'Bearer '+w.raw_staff}
    yield w
    w.api.close()


def command(w):
    return {'action':'capture','target_id':w.agreement['id'],'units':101,'revision':1,
            'event_reference':'sim_api_transport','authorized':True,'notice':PREPARE_NOTICE}


def test_prepare_dispatch_read_history_and_idempotent_replay_through_actual_api(sandbox_api):
    w=sandbox_api;response=w.api.post(w.base+'/sandbox-payments/prepare',headers=w.header,json=command(w))
    assert response.status_code==200,response.text
    intent=response.json()['result'];body={'intent_id':intent['id'],'authorized':True,'notice':EXECUTE_NOTICE}
    assert 'signature' not in response.text and 'session_ref' not in response.text
    result=w.api.post(w.base+'/sandbox-payments/dispatch',headers=w.header,json=body)
    assert result.status_code==200 and not result.json()['result']['actual_money'],result.text
    replay=w.api.post(w.base+'/sandbox-payments/dispatch',headers=w.header,json=body)
    assert replay.status_code==200 and replay.json()['result']['result']['replayed']
    status=w.api.get(w.base+'/sandbox-payments',headers=w.header)
    assert status.status_code==200 and status.headers['cache-control']=='no-store'
    assert status.json()['result']['intents'][0]['state']=='recorded'
    assert len(w.provider_calls)==1
    preparation=w.api.get(w.base+'/operating-preparation',headers=w.header)
    assert preparation.status_code==200 and not preparation.json()['result']['operating_evidence_complete']
    assert w.api.post('/sandbox-events',json={}).status_code==404


@pytest.mark.parametrize('extra',[{'Origin':'null'},{'Origin':'https://outside.invalid'},{'Sec-Fetch-Site':'cross-site'}])
def test_cross_origin_cannot_read_or_mutate_sandbox(sandbox_api,extra):
    w=sandbox_api;headers=w.header|extra
    assert w.api.get(w.base+'/sandbox-payments',headers=headers).status_code==403
    assert w.api.post(w.base+'/sandbox-payments/prepare',headers=headers,json=command(w)).status_code==403


@pytest.mark.parametrize('raw',['[]','{"action":"capture","action":"refund"}','{"units":NaN}','x'*65537])
def test_strict_raw_body_and_no_implied_authority(sandbox_api,raw):
    w=sandbox_api
    assert w.api.post(w.base+'/sandbox-payments/prepare',headers=w.header,content=raw).status_code==400
    assert w.api.get(w.base+'/sandbox-payments').status_code in (401,403)
    assert w.api.post(w.base+'/sandbox-payments/prepare',headers=w.header,json=command(w)|{'actual_money':True}).status_code==400
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_sandbox_payment_intents').fetchone()[0]==0
