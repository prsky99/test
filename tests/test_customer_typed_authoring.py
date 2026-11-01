"""Customer typed graph review/test/release and voluntary outcome isolation."""
import copy
import base64
import hashlib
import secrets
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.customer_authoring import authoring_for
from agent_market.customer_authoring_service import router_for
from agent_market.customer_identity_service import COOKIE,router_for as identity_router
from agent_market.customer_task_outcomes import NOTICE as OUTCOME_NOTICE,WITHDRAW_NOTICE
from agent_market.workspace_access import WorkspaceDenied,WorkspaceConflict
from agent_market.workspace_app_factory import NOTICE
from agent_market.workspace_app_factory import AppFactory,MODEL_NOTICE,SDK_NOTICE
from agent_market.workspace_typed_flows import NOTICE as RUN_NOTICE
from agent_market.workspace_typed_release import RUN_NOTICE as SDK_RUN_NOTICE
from agent_market.workspace_release import DEPLOY_NOTICE
from tests.test_workspace_typed_release import typed_release_world
from tests.test_workspace_typed_flows import typed_world,routing,graph


@pytest.fixture
def customer_flow(typed_release_world):
    s=typed_release_world;w=s.w
    platform=SimpleNamespace(identity=s.identity,access=w.access,execution=w.execution,
        app_execution=s.customer_flows.execution,releases=s.releases)
    core=authoring_for(platform)
    from tests.test_customer_credits import acceptance
    core.credits.enroll(acceptance(),s.customer)
    core.credits.admin_change(w.access,s.customer.customer_id,dict(revision=1,delta=97,status="active",reason="Synthetic workflow regression credit grant",request_id=secrets.token_hex(16)),w.actor)
    ws=core.organizations.create({'name':'Customer multi-step studio'},s.customer)['id']
    actor=core.actor(ws,s.customer)
    app=FastAPI();app.include_router(identity_router(w.store,w.rt.key,identity=s.identity,admin=False));app.include_router(router_for(platform))
    client=TestClient(app,base_url='https://customer.test',raise_server_exceptions=False)
    client.cookies.set(COOKIE,s.raw)
    yield SimpleNamespace(s=s,w=w,core=core,ws=ws,actor=actor,client=client,
        base='/api/customer-organizations/'+ws+'/authoring',
        headers={'Origin':'https://customer.test','X-Customer-CSRF':s.identity.csrf(s.raw)})
    client.close()


def save_run(x):
    review=x.core.factory.prepare_plan(x.ws,{'name':'Reviewed customer graph','definition':graph(x.w),
        'base_flow_id':None,'base_revision':None},x.actor)
    flow=x.core.factory.commit(x.ws,{'review_id':review['review_id'],'authorized':True,'notice':NOTICE},x.actor)
    plan=x.core.typed.prepare(x.ws,flow['id'],{'revision':1},x.actor)
    run=x.core.typed.execute(x.ws,flow['id'],{'ticket_id':plan['ticket_id'],'authorized':True,'notice':RUN_NOTICE},x.actor)['run']
    return flow,run


def test_customer_branch_projection_executes_then_owner_releases_without_staff_conversion(customer_flow):
    x=customer_flow;before=len(x.w.calls);flow,run=save_run(x)
    assert run['status']=='succeeded' and len(x.w.calls)==before+2
    release=x.core.typed_releases.create(x.ws,flow['id'],flow['version_id'],{'run_id':run['id'],'ttl_seconds':600},x.actor)
    assert release['active']
    assert x.w.store.query('SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id=?',(x.ws,))[0][0]==0
    origin='https://customer.example'
    deployment=x.core.typed_releases.deploy(x.ws,flow['id'],flow['version_id'],release['id'],
        {'allowed_origins':[origin],'ttl_seconds':600,'minute_limit':5,'day_limit':20,
         'authorized':True,'notice':DEPLOY_NOTICE},x.actor)
    verifier=secrets.token_urlsafe(32)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    code=x.core.typed_releases.authorize(deployment['app_id'],{'origin':origin,'redirect_uri':origin+'/bff/callback',
        'challenge':challenge,'state':secrets.token_urlsafe(32)},x.s.customer)
    token=x.core.typed_releases.exchange(deployment['app_id'],{'code':code['code'],'verifier':verifier,
        'redirect_uri':origin+'/bff/callback'},origin)['access_token']
    plan=x.core.typed_releases.prepare(deployment['app_id'],token,origin)
    result=x.core.typed_releases.execute(deployment['app_id'],token,{'ticket_id':plan['ticket_id'],
        'authorized':True,'notice':SDK_RUN_NOTICE},origin)
    assert result['run']['status']=='succeeded' and len(x.w.calls)==before+4
    path=x.base+'/typed/flows/'+flow['id']+'/versions/'+flow['version_id']+'/deployments/'+deployment['app_id']+'/package'
    assert x.client.get(path).status_code==200
    x.core.typed_releases.revoke(x.ws,flow['id'],flow['version_id'],release['id'],{'revision':release['revision']},x.actor)
    with pytest.raises(WorkspaceDenied):x.core.typed_releases.prepare(deployment['app_id'],token,origin)


def test_customer_runner_may_test_but_never_author_or_commit(customer_flow):
    x=customer_flow;flow,_=save_run(x)
    with x.s.identity.tx() as db:
        db.execute("UPDATE customer_workspace_links SET role='runner',revision=revision+1 WHERE workspace_id=?",(x.ws,))
    assert x.core.typed.prepare(x.ws,flow['id'],{'revision':1},x.actor)['ticket_id']
    assert not x.core.factory.options(x.ws,x.actor)['can_edit']
    with pytest.raises(WorkspaceDenied):
        x.core.factory.prepare_plan(x.ws,{'name':'Unapproved edit','definition':graph(x.w),
            'base_flow_id':None,'base_revision':None},x.actor)


def test_customer_report_is_consent_bound_separate_from_execution_and_withdrawable(customer_flow):
    x=customer_flow;flow,run=save_run(x)
    body={'source_kind':'typed','subject_id':flow['id'],'version_id':flow['version_id'],'run_id':run['id'],
        'task_succeeded':False,'correction_count':2,'support_minutes':7,'authorized':True,'notice':OUTCOME_NOTICE}
    result=x.core.outcomes.record(x.ws,body,x.actor)
    assert x.core.outcomes.record(x.ws,body,x.actor)['replayed']
    report=x.core.outcomes.report(x.ws,x.actor)
    assert report['sample_count']==report['execution_succeeded_count']==1 and report['reported_success_count']==0
    assert not report['independently_verified_business_success'] and not report['cohort_observation_complete']
    with pytest.raises(WorkspaceConflict):x.core.outcomes.record(x.ws,body|{'task_succeeded':True},x.actor)
    x.core.outcomes.withdraw(x.ws,{'outcome_id':result['outcome_id'],'authorized':True,'notice':WITHDRAW_NOTICE},x.actor)
    assert x.core.outcomes.report(x.ws,x.actor)['sample_count']==0
    with pytest.raises(WorkspaceDenied):x.core.outcomes.record(x.ws,body,x.actor)


def test_customer_api_csrf_review_support_patch_new_draft_and_no_implicit_dispatch(customer_flow):
    x=customer_flow;before=len(x.w.calls)
    body={'name':'Customer branch graph','definition':graph(x.w),'base_flow_id':None,'base_revision':None}
    path=x.base+'/typed/reviews/plan'
    assert x.client.post(path,json=body).status_code==403
    r=x.client.post(path,json=body,headers=x.headers)
    assert r.status_code==200,r.text
    review=r.json()['review']
    saved=x.client.post(x.base+'/typed/commits',json={'review_id':review['review_id'],'authorized':True,'notice':NOTICE},headers=x.headers)
    flow=saved.json()['flow'];definition=copy.deepcopy(body['definition'])
    change={'flow_id':flow['id'],'revision':1,'version_id':flow['version_id'],'name':'Reviewed revised graph',
        'patch':[{'op':'replace','path':'/nodes/0/input','value':definition['nodes'][0]['input']|{'query':'New documentation'}}],
        'documents':['safe-change-review']}
    r=x.client.post(x.base+'/typed/reviews/support',json=change,headers=x.headers)
    assert r.status_code==200,r.text
    assert r.json()['review']['patch']==change['patch'] and r.json()['review']['new_draft_only']
    assert len(x.w.calls)==before
    assert x.client.get('/customer/organizations/'+x.ws+'/flows').status_code==200
    assert x.client.get(x.base.replace(x.ws,'ws_'+'a'*32)+'/typed/options').status_code==403


@pytest.mark.parametrize('aba',[False,True])
def test_customer_model_review_tracks_current_central_adapter_generation(customer_flow,aba):
    x=customer_flow
    callback=lambda envelope:graph(x.w)
    source=AppFactory(x.w.core,model_proposer=callback)
    x.core.factory.model_source=source
    review=x.core.factory.prepare_model_proposal(x.ws,{'objective':'Find public documentation and supporting references',
        'name':'Reviewed customer model proposal','authorized':True,'notice':MODEL_NOTICE,
        'data_attestation':'public_objective_without_personal_or_private_data'},x.actor)
    source.model_proposer=None
    if aba:source.model_proposer=callback
    with pytest.raises(WorkspaceDenied):x.core.factory.commit(x.ws,{'review_id':review['review_id'],
        'authorized':True,'notice':NOTICE},x.actor)


def test_customer_can_withdraw_own_consent_after_membership_is_removed(customer_flow):
    x=customer_flow;flow,run=save_run(x)
    body={'source_kind':'typed','subject_id':flow['id'],'version_id':flow['version_id'],'run_id':run['id'],
        'task_succeeded':True,'correction_count':0,'support_minutes':0,'authorized':True,'notice':OUTCOME_NOTICE}
    record=x.core.outcomes.record(x.ws,body,x.actor)
    with x.s.identity.tx() as db:
        db.execute('UPDATE customer_workspace_links SET active=0,revision=revision+1 WHERE workspace_id=?',(x.ws,))
    response=x.client.post(x.base+'/task-outcomes/withdrawals',headers=x.headers,json={
        'outcome_id':record['outcome_id'],'authorized':True,'notice':WITHDRAW_NOTICE})
    assert response.status_code==200 and response.json()['outcome']['withdrawn']
    assert x.client.get(x.base+'/typed/options').status_code==403


def sdk_policy(revision=0):
    return {'sdk_profile':'workspace-typed-sdk-v2','revision':revision,'accepting_runs':True,
        'minimum_sdk_version':'2.1.0','sunset_seconds':600,'authorized':True,'notice':SDK_NOTICE}


@pytest.mark.parametrize('mutation',['role','membership','identity','organization','workspace'])
def test_customer_sdk_policy_pins_current_customer_owner_without_staff_membership(customer_flow,mutation):
    x=customer_flow;body=sdk_policy()
    x.core.factory.configure_sdk(x.ws,body,x.actor)
    guard=AppFactory(x.w.core)
    release={'profile':'workspace-typed-executable-release-v1','workspace_id':x.ws}
    with x.w.store.tx() as db:
        value=guard._policy(db,x.ws,body['sdk_profile'])
        assert value['owner_state']['user_role']=='customer'
        assert value['owner_state']['member_role']=='owner'
        guard.enforce_compatibility(db,release)
        if mutation=='role':db.execute("UPDATE customer_workspace_links SET role='editor' WHERE workspace_id=?",(x.ws,))
        elif mutation=='membership':db.execute('UPDATE customer_workspace_links SET revision=revision+1 WHERE workspace_id=?',(x.ws,))
        elif mutation=='identity':db.execute('UPDATE customer_identities SET revision=revision+1 WHERE id=?',(x.actor.user_id,))
        elif mutation=='organization':db.execute('UPDATE customer_organizations SET revision=revision+1 WHERE workspace_id=?',(x.ws,))
        elif mutation=='workspace':db.execute('UPDATE organization_workspaces SET revision=revision+1 WHERE id=?',(x.ws,))
        with pytest.raises(WorkspaceDenied):guard.enforce_compatibility(db,release)
    assert not x.w.store.query('SELECT user_id FROM workspace_memberships WHERE workspace_id=?',(x.ws,))


def test_customer_sdk_policy_rejects_null_owner_pin_and_stale_cas(customer_flow,monkeypatch):
    x=customer_flow
    original=x.core.factory._owner_state
    monkeypatch.setattr(x.core.factory,'_owner_state',lambda *_:None)
    with pytest.raises(WorkspaceDenied):x.core.factory.configure_sdk(x.ws,sdk_policy(),x.actor)
    assert not x.w.store.query('SELECT * FROM workspace_sdk_policies WHERE workspace_id=?',(x.ws,))
    monkeypatch.setattr(x.core.factory,'_owner_state',original)
    x.core.factory.configure_sdk(x.ws,sdk_policy(),x.actor)
    with pytest.raises(WorkspaceConflict):x.core.factory.configure_sdk(x.ws,sdk_policy(),x.actor)
    assert x.core.factory.configure_sdk(x.ws,sdk_policy(1),x.actor)['revision']==2
    with x.w.store.tx() as db:
        value=x.core.factory._policy(db,x.ws,'workspace-typed-sdk-v2')
        value['owner_state']=None
        from agent_market.workspace_access import _canonical
        db.execute('UPDATE workspace_sdk_policies SET payload=?,signature=? WHERE workspace_id=?',
            (_canonical(value),x.core.factory.sign(value),x.ws))
        with pytest.raises(WorkspaceDenied):x.core.factory.enforce_compatibility(db,
            {'profile':'workspace-typed-executable-release-v1','workspace_id':x.ws})
    assert not x.core.factory.catalog(x.ws,x.actor)['policies'][1]['current_owner']


def test_credit_quote_download_race_requires_new_review_and_replay_debits_once(customer_flow):
    x=customer_flow;before=x.core.credits.status(x.s.customer)['balance']
    flow,_=save_run(x)
    body={'name':'Reviewed corrected workflow','definition':graph(x.w),'base_flow_id':flow['id'],'base_revision':flow['revision']}
    review=x.core.factory.prepare_plan(x.ws,body,x.actor)
    assert review['credit_charge']==0
    x.core.credits.downloaded(x.ws,flow['id'],flow['revision'],x.actor)
    command={'review_id':review['review_id'],'authorized':True,'notice':NOTICE}
    with pytest.raises(WorkspaceConflict):x.core.factory.commit(x.ws,command,x.actor)
    review=x.core.factory.prepare_plan(x.ws,body,x.actor);assert review['credit_charge']==1
    command['review_id']=review['review_id'];saved=x.core.factory.commit(x.ws,command,x.actor)
    assert x.core.factory.commit(x.ws,command,x.actor)['id']==saved['id']
    assert x.core.credits.status(x.s.customer)['balance']==before-2


def test_flows_page_without_session_redirects_to_sign_in(customer_flow):
    # 2026-10-21: an expired session showed a raw JSON error page.
    x=customer_flow
    from fastapi.testclient import TestClient
    page=TestClient(x.client.app,base_url='https://customer.test').get('/customer/organizations/'+x.ws+'/flows',follow_redirects=False)
    from urllib.parse import urlsplit, parse_qs
    location=urlsplit(page.headers['location']);query=parse_qs(location.query)
    # The sign-in page also carries a same-site return path to the requested workspace page.
    assert page.status_code==303 and location.path=='/customer/sign-in' and query.get('result',['expired'])==['expired']
    assert query.get('next',['/customer/organizations/'+x.ws+'/flows'])==['/customer/organizations/'+x.ws+'/flows']


def test_worker_runs_customer_flow_under_customer_authority(customer_flow):
    """Managed web roles hand every run to the execution worker; a customer run must not use the staff adapter."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    from agent_market.service_host import execute_typed
    from tests.test_service_split import Control
    x=customer_flow;store=x.w.store
    review=x.core.factory.prepare_plan(x.ws,{'name':'Worker customer graph','definition':graph(x.w),
        'base_flow_id':None,'base_revision':None},x.actor)
    flow=x.core.factory.commit(x.ws,{'review_id':review['review_id'],'authorized':True,'notice':NOTICE},x.actor)
    plan=x.core.typed.prepare(x.ws,flow['id'],{'revision':1},x.actor)
    store._service_role,store._service_control='frontend',Control()
    platform=SimpleNamespace(typed_flows=x.w.core,customer_authoring=x.core,access=x.w.access)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(x.core.typed.execute,x.ws,flow['id'],{'ticket_id':plan['ticket_id'],'authorized':True,'notice':RUN_NOTICE},x.actor)
        identity=None;deadline=time.monotonic()+3
        while identity is None and time.monotonic()<deadline:
            with store._lock:
                row=store._db.execute('SELECT id FROM workspace_typed_flow_runs WHERE flow_id=?',(flow['id'],)).fetchone()
            identity=row[0] if row else None
            time.sleep(.01)
        assert identity and x.w.core.admitted_actor_kind(identity,x.ws,flow['id'])=='customer'
        execute_typed(platform,identity,x.ws,flow['id'])
        assert pending.result(timeout=5)['run']['status']=='succeeded'


def test_commit_has_no_active_workflow_limit(customer_flow):
    """11-01: a reviewed commit is never refused for the number of workflows already saved."""
    from agent_market import workspace_typed_flows as module
    x=customer_flow
    assert 'flows' not in module.LIMITS
    review=x.core.factory.prepare_plan(x.ws,{'name':'No cap','definition':graph(x.w),'base_flow_id':None,'base_revision':None},x.actor)
    response=x.client.post(x.base+'/typed/commits',headers=x.headers,json={'review_id':review['review_id'],'authorized':True,'notice':NOTICE})
    assert response.status_code==200,response.text
