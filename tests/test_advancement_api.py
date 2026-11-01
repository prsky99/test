"""Named-session private API checks on real Store, never a project server."""
import json

import pytest

from agent_market.advancement_service import router_for
from agent_market.shadow_ledger import NOTICE
from agent_market.workflow_support import NOTICE as SUPPORT_NOTICE, APPLY_NOTICE
from agent_market.workspace_access import WorkspaceAccess
from tests.test_workspace_execution_api import private_api


@pytest.fixture
def advancement_api(private_api):
    w=private_api
    if not any(getattr(route,'path','').endswith('/advancement/ledger/options') for route in w.app.routes):
        w.app.include_router(router_for(WorkspaceAccess(w.store,w.store._workflow_runtime.key)))
    w.base=f'/admin/api/workflow-workspaces/{w.ws["id"]}/advancement'
    return w


def approval(n=1):
    return {'operation_id':'slop_'+format(n,'032x'),'asset':'TEST_UNIT','units':40,'authorized':True,'notice':NOTICE}


def test_actual_simulation_endpoints_enforce_explicit_scope_and_signed_balance(advancement_api):
    w=advancement_api
    approved=w.client.post(w.base+'/ledger/approve',headers=w.headers['owner'],json=approval())
    assert approved.status_code==200,approved.text
    op=approved.json()['result'];assert op['simulation'] and not op['actual_money']
    command={'operation_id':op['id'],'event_id':'slev_'+'b'*32,'revision':1,'outcome':'partial',
             'settled_units':13,'authorized':True,'notice':NOTICE}
    response=w.client.post(w.base+'/ledger/post',headers=w.headers['owner'],json=command)
    assert response.status_code==200 and response.json()['result']['settled_units']==13,response.text
    assert w.client.post(w.base+'/ledger/post',headers=w.headers['owner'],json=command).json()['result']['replayed']
    summary=w.client.get(w.base+'/ledger',headers=w.headers['viewer'])
    assert summary.status_code==200 and summary.json()['result']['balanced']
    assert summary.headers['cache-control']=='no-store'
    assert not w.calls
    assert w.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]==0


@pytest.mark.parametrize('person',['editor','viewer','operator','outsider'])
def test_only_current_owner_can_authorize_accounting(advancement_api,person):
    w=advancement_api
    response=w.client.post(w.base+'/ledger/approve',headers=w.headers[person],json=approval())
    assert response.status_code==404 and response.headers['cache-control']=='no-store'
    assert w.store.query('SELECT COUNT(*) FROM workspace_shadow_operations')[0][0]==0


@pytest.mark.parametrize('raw',['{"operation_id":"x","operation_id":"y"}','{"units":NaN}',
    '{"units":1e999}','[]',r'{"note":"\ud800"}','x'*65537])
def test_strict_request_bounds_do_not_store_a_declaration_or_operation(advancement_api,raw):
    w=advancement_api
    for path in ('/ledger/approve','/readiness/declarations','/support/proposals'):
        response=w.client.post(w.base+path,headers=w.headers['owner'],content=raw)
        assert response.status_code==400 and response.headers['cache-control']=='no-store'
    assert w.store.query('SELECT COUNT(*) FROM workspace_shadow_operations')[0][0]==0


@pytest.mark.parametrize('extra',[{'Origin':'null'},{'Origin':'https://other.invalid'},{'Sec-Fetch-Site':'cross-site'}])
def test_origin_protection_also_covers_readonly_private_results(advancement_api,extra):
    w=advancement_api
    for path in ('/ledger','/support','/readiness'):
        response=w.client.get(w.base+path,headers={**w.headers['owner'],**extra})
        assert response.status_code==403 and response.headers['cache-control']=='no-store'


def test_support_patch_uses_real_scoped_snapshot_and_never_runs_or_publishes(advancement_api):
    w=advancement_api
    body={'draft_id':w.draft['id'],'snapshot_id':w.snapshot['id'],'draft_revision':w.draft['revision'],
        'snapshot_revision':w.snapshot['revision'],'changes':{'name':'Reviewed API draft'},
        'documents':['safe-change-review'],'authorized':True,'notice':SUPPORT_NOTICE}
    response=w.client.post(w.base+'/support/proposals',headers=w.headers['editor'],json=body)
    assert response.status_code==200,response.text
    p=response.json()['result'];assert p['patch']==[{'op':'replace','path':'/name','value':'Reviewed API draft'}]
    assert not p['executed'] and not p['published']
    response=w.client.post(w.base+'/support/proposals/'+p['id']+'/apply',headers=w.headers['editor'],
        json={'authorized':True,'notice':APPLY_NOTICE})
    assert response.status_code==200 and response.json()['result']['revision']==2,response.text
    assert not w.calls
    assert w.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]==0
    assert w.store.query('SELECT COUNT(*) FROM workflow_publication_grants')[0][0]==0
    history=w.client.get(w.base+'/support/proposals',headers=w.headers['viewer']).json()['result']
    assert 'patch' not in history[0]


def test_missing_evidence_and_arbitrary_verified_claim_never_complete_readiness(advancement_api):
    w=advancement_api
    report=w.client.get(w.base+'/readiness',headers=w.headers['owner'])
    assert report.status_code==200 and report.json()['result']['status']=='not_ready'
    assert not report.json()['result']['commercial_enabled']
    response=w.client.post(w.base+'/readiness/declarations',headers=w.headers['owner'],json={'verified':True,'contract':'fabricated'})
    assert response.status_code==400
    assert w.store.query('SELECT COUNT(*) FROM workspace_readiness_declarations')[0][0]==0


def test_revoked_session_and_global_superadmin_nonmember_cannot_read_support_or_readiness(advancement_api):
    w=advancement_api
    for person in ('outsider',):
        for path in ('/support','/support/proposals','/readiness','/ledger'):
            response=w.client.get(w.base+path,headers=w.headers[person])
            assert response.status_code==404
    with w.store.tx() as db:db.execute('DELETE FROM admin_sessions WHERE user_id=?',(w.users['owner'],))
    assert w.client.get(w.base+'/readiness',headers=w.headers['owner']).status_code==401
