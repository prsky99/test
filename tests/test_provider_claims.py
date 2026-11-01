"""Endpoint-control proofs use a fixed synthetic HTTPS responder only."""
import copy
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.provider_claims import ProviderClaims, NOTICE, PROFILE
from agent_market.provider_claims_service import router_for
from agent_market.workspace_access import WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid
from tests.test_customer_identity import customer_world


@pytest.fixture
def provider():
    w=customer_world()
    w.store._db.execute('CREATE TABLE resource_observation_generations(resource_id INTEGER PRIMARY KEY,generation INTEGER)')
    w.store._db.execute('INSERT INTO resource_observation_generations VALUES(1,1)')
    w.store._db.commit()
    w.proof=None;w.provider_calls=[];w.provider_status=200;w.provider_during=None
    def handler(request):
        w.provider_calls.append(request)
        assert request.method=='GET' and str(request.url)=='https://synthetic.invalid/.well-known/agent-concierge-claim.json'
        assert not request.headers.get('authorization') and not request.headers.get('cookie')
        if w.provider_during:w.provider_during()
        return httpx.Response(w.provider_status,json=w.proof)
    w.provider_http=httpx.Client(transport=httpx.MockTransport(handler))
    w.claims=ProviderClaims(w.store,b'synthetic-provider-claim-key32!!!',w.provider_http)
    try:yield w
    finally:w.provider_http.close();w.http.close();w.store._db.close()


def prepare(w):
    value=w.claims.prepare(w.ws,{'resource_id':1},w.staff[1]);w.proof=copy.deepcopy(value['challenge']);return value


def verify(w,value):
    return w.claims.verify(w.ws,{'claim_id':value['claim']['id'],'revision':value['claim']['revision'],
         'authorized':True,'notice':NOTICE},w.staff[1])


def test_offline_nonce_then_explicit_https_control_and_revoke(provider):
    w=provider; value=prepare(w)
    assert not w.provider_calls and value['challenge']['profile']==PROFILE
    assert value['claim']['challenge_url']=='https://synthetic.invalid/.well-known/agent-concierge-claim.json'
    result=verify(w,value)
    assert result['status']=='verified' and result['revision']==3 and result['endpoint_control_only']
    assert not result['quality_certified'] and len(w.provider_calls)==1
    with w.store.tx() as db:assert w.claims.current(db,w.ws,1)['id']==result['id']
    revoked=w.claims.revoke(w.ws,result['id'],{'revision':result['revision']},w.staff[1])
    assert revoked['status']=='revoked'
    with w.store.tx() as db:
        with pytest.raises(WorkspaceDenied):w.claims.current(db,w.ws,1)
    assert len(w.provider_calls)==1


@pytest.mark.parametrize('fault',['nonce','id','profile','extra','redirect','notfound'])
def test_incorrect_challenge_or_redirect_is_failed_once(provider,fault):
    w=provider;value=prepare(w)
    if fault=='nonce':w.proof['nonce']='x'*43
    elif fault=='id':w.proof['claim_id']='pc_'+'a'*32
    elif fault=='profile':w.proof['profile']='different-purpose'
    elif fault=='extra':w.proof['token']='synthetic-secret'
    elif fault=='redirect':w.provider_status=302
    else:w.provider_status=404
    result=verify(w,value)
    assert result['status']=='failed' and result['verified'] is None
    with pytest.raises(WorkspaceDenied):verify(w,value)
    assert len(w.provider_calls)==1


@pytest.mark.parametrize('fault',['binding','generation','member','session'])
def test_live_state_rechecked_after_https_proof(provider,fault):
    w=provider;value=prepare(w)
    def mutate():
        assert not w.store._db.in_transaction
        with w.store.tx() as db:
            if fault=='binding':db.execute("UPDATE resources SET url='https://different.invalid/mcp' WHERE id=1")
            elif fault=='generation':db.execute('UPDATE resource_observation_generations SET generation=generation+1 WHERE resource_id=1')
            elif fault=='member':db.execute('UPDATE workspace_memberships SET revision=revision+1 WHERE workspace_id=?',(w.ws,))
            else:db.execute('DELETE FROM admin_sessions WHERE user_id=1')
    w.provider_during=mutate
    with pytest.raises(WorkspaceDenied):verify(w,value)
    assert len(w.provider_calls)==1
    assert w.store._db.execute("SELECT COUNT(*) FROM provider_control_claims WHERE status='verified'").fetchone()[0]==0


@pytest.mark.parametrize('url',['http://synthetic.invalid/mcp','https://127.0.0.1/mcp','https://name:secret@synthetic.invalid/mcp',
   'https://synthetic.invalid/mcp?token=secret'])
def test_source_url_must_be_public_https_without_credentials(provider,url):
    w=provider
    with w.store.tx() as db:db.execute('UPDATE resources SET url=? WHERE id=1',(url,))
    with pytest.raises(WorkspaceDenied):prepare(w)
    assert not w.provider_calls


def test_verified_binding_generation_change_and_restore_tombstone_refused(provider):
    w=provider;value=prepare(w);result=verify(w,value)
    with w.store.tx() as db:db.execute('UPDATE resource_observation_generations SET generation=generation+1 WHERE resource_id=1')
    with w.store.tx() as db:
        with pytest.raises(WorkspaceDenied):w.claims.current(db,w.ws,1)
    with w.store.tx() as db:
        db.execute('UPDATE resource_observation_generations SET generation=1 WHERE resource_id=1')
        db.execute('UPDATE provider_control_claims SET revoked=1 WHERE id=?',(result['id'],))
    with w.store.tx() as db:
        with pytest.raises(WorkspaceDenied):w.claims.current(db,w.ws,1)


def test_claim_api_current_named_owner_safe_projection_and_strict_requests(provider):
    w=provider;app=FastAPI();app.include_router(router_for(w.store,b'synthetic-provider-claim-key32!!!',claims=w.claims))
    base='/admin/api/workflow-workspaces/'+w.ws+'/provider-claims'
    header={'X-Dashboard':'1','Authorization':'Bearer '+w.raw_staff}
    with TestClient(app,base_url='https://agentconcierge.biz') as client:
        assert client.get(base).status_code==403
        assert client.get(base,headers={'X-Dashboard':'1','Authorization':'Bearer machine-token'}).status_code==401
        result=client.post(base+'/prepare',headers=header,json={'resource_id':1})
        assert result.status_code==200,result.text
        value=result.json();w.proof=value['challenge']
        result=client.post(base+'/verify',headers=header,json={'claim_id':value['claim']['id'],'revision':1,'authorized':True,'notice':NOTICE})
        assert result.status_code==200 and result.json()['status']=='verified'
        history=client.get(base,headers=header)
        assert history.status_code==200 and history.headers['cache-control']=='no-store'
        assert all(item not in history.text for item in ('nonce_hash','session_ref','signature','synthetic.invalid','payload'))
        duplicate=client.post(base+'/prepare',headers=header,content='{"resource_id":1,"resource_id":2}')
        assert duplicate.status_code==400
        crossed=client.post(base+'/prepare',headers={**header,'Origin':'https://outside.invalid'},json={'resource_id':1})
        assert crossed.status_code==403
        assert len(w.provider_calls)==1
