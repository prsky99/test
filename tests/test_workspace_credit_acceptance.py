"""Credit acceptance through normal customer routes and disposable accounts."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import secrets
from zipfile import ZipFile

import pytest

from agent_market.workspace_app_factory import NOTICE
from agent_market.workspace_release import DEPLOY_NOTICE
from agent_market.workspace_typed_flows import NOTICE as RUN_NOTICE
from tests.test_customer_typed_authoring import customer_flow  # noqa: F401
from tests.test_workspace_typed_release import typed_release_world  # noqa: F401
from tests.test_workspace_typed_flows import typed_world, routing, graph  # noqa: F401


def balance(x):return x.client.get('/api/customer-credits').json()['credits']['balance']


def review(x,name='Synthetic credit acceptance',parent=None):
    body={'name':name,'definition':graph(x.w),'base_flow_id':parent['id'] if parent else None,'base_revision':parent['revision'] if parent else None}
    response=x.client.post(x.base+'/typed/reviews/plan',json=body,headers=x.headers)
    assert response.status_code==200,response.text
    return response.json()['review']


def commit(x,value,**extra):
    return x.client.post(x.base+'/typed/commits',json={'review_id':value['review_id'],'authorized':True,'notice':NOTICE,**extra},headers=x.headers)


def package(x,flow):
    path=x.base+'/typed/flows/'+flow['id']
    prepared=x.client.post(path+'/prepare',json={'revision':flow['revision']},headers=x.headers).json()
    result=x.client.post(path+'/runs',json={'ticket_id':prepared['ticket_id'],'authorized':True,'notice':RUN_NOTICE},headers=x.headers)
    assert result.status_code==200 and result.json()['run']['status']=='succeeded',result.text
    scope=path+'/versions/'+flow['version_id']
    released=x.client.post(scope+'/releases',json={'run_id':result.json()['run']['id'],'ttl_seconds':600},headers=x.headers)
    assert released.status_code==200,released.text
    deployed=x.client.post(scope+'/releases/'+released.json()['release']['id']+'/deployments',json={'allowed_origins':['https://synthetic-app.example'],'ttl_seconds':600,'minute_limit':5,'day_limit':20,'authorized':True,'notice':DEPLOY_NOTICE},headers=x.headers)
    assert deployed.status_code==200,deployed.text
    return scope+'/deployments/'+deployed.json()['deployment']['app_id']+'/package'


def test_full_credit_journey_new_predownload_repeat_download_and_postdownload(customer_flow):
    x=customer_flow;initial=balance(x)
    proposal=review(x);assert proposal['credit_charge']==1 and balance(x)==initial
    flow=commit(x,proposal).json()['flow'];assert balance(x)==initial-1
    assert commit(x,proposal).json()['flow']['id']==flow['id'] and balance(x)==initial-1
    edited=review(x,'Synthetic before-download edit',flow);assert edited['credit_charge']==0
    flow=commit(x,edited).json()['flow'];assert balance(x)==initial-1
    path=package(x,flow)
    for _ in range(2):
        response=x.client.get(path);assert response.status_code==200
        with ZipFile(BytesIO(response.content)) as archive:assert 'app-manifest.json' in archive.namelist()
        assert balance(x)==initial-1
    edited=review(x,'Synthetic after-download edit',flow);assert edited['credit_charge']==1
    saved=commit(x,edited).json()['flow'];assert balance(x)==initial-2
    assert commit(x,edited).json()['flow']['id']==saved['id'] and balance(x)==initial-2


def test_missing_consent_invalid_graph_and_csrf_do_not_spend(customer_flow):
    x=customer_flow;initial=balance(x);proposal=review(x)
    assert commit(x,proposal,authorized=False).status_code==400
    assert x.client.post(x.base+'/typed/commits',json={'review_id':proposal['review_id'],'authorized':True,'notice':NOTICE}).status_code==403
    invalid={'name':'Rejected invalid workflow','definition':{'nodes':[]},'base_flow_id':None,'base_revision':None}
    assert x.client.post(x.base+'/typed/reviews/plan',json=invalid,headers=x.headers).status_code==400
    assert balance(x)==initial and not x.core.typed.listing(x.ws,x.actor)


def test_concurrent_replay_creates_one_workflow_and_one_debit(customer_flow):
    x=customer_flow;initial=balance(x);proposal=review(x)
    with ThreadPoolExecutor(max_workers=6) as pool:responses=list(pool.map(lambda _:commit(x,proposal),range(6)))
    assert all(r.status_code==200 for r in responses),[(r.status_code,r.text) for r in responses]
    assert len({r.json()['flow']['id'] for r in responses})==1
    assert balance(x)==initial-1 and len(x.core.typed.listing(x.ws,x.actor))==1


def test_last_three_credits_exhaustion_rejects_fourth_atomically(customer_flow):
    x=customer_flow;status=x.core.credits.status(x.s.customer)
    x.core.credits.admin_change(x.w.access,x.s.customer.customer_id,{'revision':status['revision'],'delta':3-status['balance'],'status':'active','reason':'Disposable three-credit acceptance account','request_id':secrets.token_hex(16)},x.w.actor)
    for i in range(3):assert commit(x,review(x,'Credit exhaustion '+str(i))).status_code==200
    assert balance(x)==0
    proposal=review(x,'Rejected fourth workflow')
    assert commit(x,proposal).status_code==409
    assert balance(x)==0 and len(x.core.typed.listing(x.ws,x.actor))==3


@pytest.mark.parametrize('state',['closed','suspended'])
def test_inactive_enrollment_cannot_save_or_download_existing_app(customer_flow,state):
    x=customer_flow;flow=commit(x,review(x)).json()['flow'];path=package(x,flow)
    status=x.core.credits.status(x.s.customer);initial=status['balance']
    if state=='closed':
        response=x.client.post('/api/customer-credits/close',json={'revision':status['revision'],'confirm':'CLOSE'},headers=x.headers)
        assert response.status_code==200
    else:
        x.core.credits.admin_change(x.w.access,x.s.customer.customer_id,{'revision':status['revision'],'delta':0,'status':'suspended','reason':'Disposable suspended-account acceptance','request_id':secrets.token_hex(16)},x.w.actor)
    assert x.client.get(path).status_code==409
    # Preparing a proposal is advisory. Its save must still recheck enrollment.
    proposed=x.client.post(x.base+'/typed/reviews/plan',json={'name':'Inactive save denied','definition':graph(x.w),'base_flow_id':None,'base_revision':None},headers=x.headers)
    if proposed.status_code==200:assert commit(x,proposed.json()['review']).status_code==409
    else:assert proposed.status_code==409
    assert balance(x)==initial and len(x.core.typed.listing(x.ws,x.actor))==1


def test_download_revision_contention_is_safe_409_and_retry_does_not_spend(customer_flow,monkeypatch):
    from agent_market.workspace_access import WorkspaceConflict
    x=customer_flow;flow=commit(x,review(x)).json()['flow'];path=package(x,flow)
    initial=balance(x);calls=len(x.w.calls)
    original_config=x.core.typed_releases.package_config;original_version=x.core.typed._version;armed=[False];injected=[False]
    def configured(*args):
        result=original_config(*args)
        if not injected[0]:armed[0]=True
        return result
    def version(*args):
        if armed[0]:
            armed[0]=False;injected[0]=True
            raise WorkspaceConflict()
        return original_version(*args)
    monkeypatch.setattr(x.core.typed_releases,'package_config',configured)
    monkeypatch.setattr(x.core.typed,'_version',version)
    response=x.client.get(path)
    assert response.status_code==409 and balance(x)==initial
    assert 'Private workspace access is temporarily unavailable' not in response.text
    assert x.client.get(path).status_code==200
    assert balance(x)==initial and len(x.w.calls)==calls


@pytest.mark.parametrize('steps',[2,3,5,10])
def test_one_credit_covers_varied_graph_sizes_and_actual_projection(customer_flow,steps):
    import json
    from tests.test_workspace_typed_flows import node
    x=customer_flow;initial=balance(x);received=[]
    for host in ('primary.example','alternate.example'):
        x.w.hooks[host]=lambda request:received.append(json.loads(request.content)['params']['arguments']['query'])
    original=x.w.remote.handle_request
    def dynamic_response(request):
        response=original(request);body=json.loads(request.content or '{}')
        if body.get('method')=='tools/call':
            value=response.json();value['result']['structuredContent']['items'][0]['title']='Evidence: '+body['params']['arguments']['query']
            import httpx
            return httpx.Response(200,json=value)
        return response
    x.w.remote.handle_request=dynamic_response
    definition={'nodes':[node('s'+str(i),x.w.ids[i%2],parent='s'+str(i-1) if i else None) for i in range(steps)]}
    value=x.client.post(x.base+'/typed/reviews/plan',json={'name':str(steps)+' step credit acceptance','definition':definition,'base_flow_id':None,'base_revision':None},headers=x.headers)
    assert value.status_code==200 and balance(x)==initial
    flow=commit(x,value.json()['review']).json()['flow']
    download=package(x,flow)
    assert len(received)==steps and received[0]=='Current documentation'
    assert received==['Evidence: '*i+'Current documentation' for i in range(steps)]
    assert x.client.get(download).status_code==200 and balance(x)==initial-1


@pytest.mark.parametrize('failure',['unknown','error','invalid'])
def test_failed_execution_does_not_charge_twice_or_enable_export(customer_flow,failure):
    x=customer_flow;initial=balance(x)
    flow=commit(x,review(x)).json()['flow'];assert balance(x)==initial-1
    scope=x.base+'/typed/flows/'+flow['id']
    prepared=x.client.post(scope+'/prepare',json={'revision':flow['revision']},headers=x.headers).json()
    x.w.calls.clear();x.w.modes['primary.example']=failure
    body={'ticket_id':prepared['ticket_id'],'authorized':True,'notice':RUN_NOTICE}
    first=x.client.post(scope+'/runs',json=body,headers=x.headers)
    assert first.status_code==200,first.text
    result=first.json()['run'];assert result['status'] in ('failed','unknown')
    assert x.w.calls==['primary.example']
    replay=x.client.post(scope+'/runs',json=body,headers=x.headers)
    assert replay.status_code==200 and replay.json()['replayed']
    assert replay.json()['run']['id']==result['id'] and x.w.calls==['primary.example']
    denied=x.client.post(scope+'/versions/'+flow['version_id']+'/releases',json={'run_id':result['id'],'ttl_seconds':600},headers=x.headers)
    assert denied.status_code in (403,409)
    assert balance(x)==initial-1


def test_distinct_concurrent_reviews_share_last_credit_without_overdraft(customer_flow):
    x=customer_flow;status=x.core.credits.status(x.s.customer)
    x.core.credits.admin_change(x.w.access,x.s.customer.customer_id,{'revision':status['revision'],'delta':1-status['balance'],'status':'active','reason':'Disposable concurrent last-credit account','request_id':secrets.token_hex(16)},x.w.actor)
    proposals=[review(x,'Competing draft '+str(i)) for i in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:responses=list(pool.map(lambda value:commit(x,value),proposals))
    assert sum(r.status_code==200 for r in responses)==1
    assert all(r.status_code in (200,409) for r in responses)
    assert balance(x)==0 and len(x.core.typed.listing(x.ws,x.actor))==1


def test_capacity_rejection_keeps_credit_and_original_artifact(customer_flow,monkeypatch):
    # Workspaces have no workflow cap since 11-01; a store refusal stands in for any capacity limit.
    from agent_market.workspace_access import WorkspaceLimit
    x=customer_flow;initial=balance(x);flow=commit(x,review(x)).json()['flow']
    proposal=review(x,'Draft beyond temporary test capacity')
    def full(*args,**kwargs):raise WorkspaceLimit('Storage is temporarily full.')
    monkeypatch.setattr(x.core.typed,'_save_in_transaction',full)
    assert commit(x,proposal).status_code==409
    assert balance(x)==initial-1
    assert [f['id'] for f in x.core.typed.listing(x.ws,x.actor)]==[flow['id']]


def test_failure_after_credit_write_rolls_back_artifact_and_debit(customer_flow,monkeypatch):
    from agent_market.workspace_access import WorkspaceConflict
    x=customer_flow;initial=balance(x);proposal=review(x);access=x.core.factory.access;audit=access._audit
    def fail(db,actor,ws,action,*args):
        if action=='factory.commit':raise WorkspaceConflict()
        return audit(db,actor,ws,action,*args)
    monkeypatch.setattr(access,'_audit',fail)
    assert commit(x,proposal).status_code==409
    assert balance(x)==initial and not x.core.typed.listing(x.ws,x.actor)
    monkeypatch.setattr(access,'_audit',audit)
    assert commit(x,proposal).status_code==200 and balance(x)==initial-1
