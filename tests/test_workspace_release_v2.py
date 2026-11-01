"""Isolated release/customer-app tests never use an operating identity provider."""
import base64
import hashlib
import json
import secrets
import time
from types import SimpleNamespace

import httpx
import pytest

from agent_market.concierge.proxy import McpProxy
from agent_market.customer_identity import CustomerActor,CustomerIdentity,OIDCConfig
from agent_market.customer_workspace_runtime import CustomerWorkspaceAccess
from agent_market.gateway.admin_auth import session_reference
from agent_market.workspace_access import SessionActor,WorkspaceAccess,WorkspaceDenied,WorkspaceConflict,WorkspaceInvalid
from agent_market.workspace_execution import WorkspaceExecution,NOTICE
from agent_market.workspace_release import WorkspaceReleases,DEPLOY_NOTICE,RUN_NOTICE
from agent_market.workspace_lifecycle import WorkspaceLifecycle
from agent_market.workflows import runtime_for
from tests.test_workspace_execution_api import private_api

ORIGIN='https://customer.example'

@pytest.fixture
def release_world(private_api):
    w=private_api;access=WorkspaceAccess(w.store,runtime_for(w.store).key);calls=[];control={'before_call':None,'mode':'ok'}
    def provider(request):
        method=json.loads(request.content or b'{}').get('method');calls.append(method)
        if method=='tools/list' and control['before_call']:control['before_call']()
        if method=='tools/call' and control['mode']=='timeout':raise httpx.ReadTimeout('Synthetic timeout',request=request)
        return w.remote.handle_request(request)
    proxy=McpProxy(w.store,allow_private=True,http=httpx.Client(transport=httpx.MockTransport(provider)))
    staff=WorkspaceExecution(access,proxy)
    config=OIDCConfig('https://accounts.google.com','synthetic-client.apps.googleusercontent.com','https://accounts.google.com/o/oauth2/v2/auth','https://oauth2.googleapis.com/token','https://www.googleapis.com/oauth2/v3/certs','https://agentconcierge.biz/api/customer-auth/callback','synthetic-google-secret')
    identity=CustomerIdentity(w.store,runtime_for(w.store).key,config)
    customer='cu_'+secrets.token_hex(16);raw='cst_'+secrets.token_urlsafe(32);ref=identity._mac('session',raw)
    with identity.tx() as db:
        db.execute('INSERT INTO customer_identities VALUES(?,?,?,1,1,?,?)',(customer,config.issuer,identity._mac('subject','synthetic-customer'),time.time(),time.time()))
        db.execute('INSERT INTO customer_sessions VALUES(?,?,?,?,?,NULL)',(ref,customer,identity._issuer_configuration(config.issuer),time.time(),time.time()+86400*30))
        db.execute('INSERT INTO customer_workspace_links VALUES(?,?,?,1,1,?)',(w.ws['id'],customer,'runner',time.time()))
    customer_access=CustomerWorkspaceAccess(access,identity);runner=WorkspaceExecution(customer_access,proxy)
    releases=WorkspaceReleases(staff,customer_identity=identity,customer_executor=runner);runner.authority_guard=releases.guard_ticket
    actor=SessionActor(1,session_reference(w.headers['owner']['Authorization'][7:]));customer_actor=CustomerActor(customer,ref)
    args=(w.ws['id'],w.draft['id'],w.snapshot['id'])
    plan=staff.prepare(*args,{'snapshot_revision':w.snapshot['revision']},actor)
    result=staff.execute(*args,{'ticket_id':plan['ticket_id'],'authorized':True,'notice':NOTICE},actor)
    assert result['status']=='succeeded',result
    world=SimpleNamespace(w=w,access=access,staff=staff,runner=runner,releases=releases,identity=identity,actor=actor,customer=customer_actor,raw_cookie=raw,args=args,result=result,calls=calls,control=control,lifecycle=WorkspaceLifecycle(staff))
    yield world
    proxy._http.close()


def release(x):return x.releases.create(*x.args,{'run_id':x.result['id'],'ttl_seconds':3600},x.actor)
def deployment(x,rid=None,**extra):
    rid=rid or release(x)['id']
    return x.releases.deploy(*x.args,rid,{'allowed_origins':[ORIGIN],'ttl_seconds':1800,'minute_limit':5,'day_limit':20,'authorized':True,'notice':DEPLOY_NOTICE,**extra},x.actor)
def app_token(x,app):
    verifier=secrets.token_urlsafe(32);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    code=x.releases.authorize(app,{'origin':ORIGIN,'redirect_uri':ORIGIN+'/bff/callback','challenge':challenge,'state':secrets.token_urlsafe(32)},x.customer)
    return x.releases.exchange(app,{'code':code['code'],'verifier':verifier,'redirect_uri':ORIGIN+'/bff/callback'},ORIGIN)
def run_app(x,app,token):
    plan=x.releases.prepare(app,token['access_token'],ORIGIN)
    result=x.releases.execute(app,token['access_token'],{'ticket_id':plan['ticket_id'],'authorized':True,'notice':RUN_NOTICE},ORIGIN)
    return result,plan


def test_release_requires_retained_success_current_pin_and_separate_deployment_consent(release_world):
    x=release_world;r=release(x);assert r['active']==1
    with pytest.raises(WorkspaceInvalid):deployment(x,r['id'],authorized=False)
    app=deployment(x,r['id']);assert app['profile']=='workspace-sdk-v2' and x.releases.package_config(*x.args,app['app_id'],x.actor)['app_id']==app['app_id']
    assert not any(key in json.dumps(app) for key in ('session_ref','signature','access_token','binding_hash'))
    with x.w.store.tx() as db:db.execute("UPDATE resources SET description='Changed source' WHERE id=?",(x.w.rid,))
    with pytest.raises(WorkspaceDenied):x.releases.package_config(*x.args,app['app_id'],x.actor)


def test_customer_code_exchange_and_per_run_authority_use_private_rows_only(release_world):
    x=release_world;app=deployment(x);token=app_token(x,app['app_id']);before=x.calls.count('tools/call')
    result,plan=run_app(x,app['app_id'],token)
    assert result['run']['status']=='succeeded' and x.calls.count('tools/call')==before+1
    replay=x.releases.execute(app['app_id'],token['access_token'],{'ticket_id':plan['ticket_id'],'authorized':True,'notice':RUN_NOTICE},ORIGIN)
    assert replay['run']['id']==result['run']['id'] and x.calls.count('tools/call')==before+1
    assert x.w.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]==0
    status=x.releases.status(app['app_id'],result['status_capability']['access_token'],result['run']['id'],ORIGIN)
    assert status['status']=='succeeded'
    with pytest.raises(WorkspaceDenied):x.releases.prepare(app['app_id'],result['status_capability']['access_token'],ORIGIN)


@pytest.mark.parametrize('changed',['origin','verifier','redirect','replay'])
def test_pkce_code_is_one_time_and_exact_app_origin_bound(release_world,changed):
    x=release_world;app=deployment(x);verifier=secrets.token_urlsafe(32);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    code=x.releases.authorize(app['app_id'],{'origin':ORIGIN,'redirect_uri':ORIGIN+'/bff/callback','challenge':challenge,'state':secrets.token_urlsafe(32)},x.customer)
    body={'code':code['code'],'verifier':verifier,'redirect_uri':ORIGIN+'/bff/callback'}
    if changed=='verifier':body['verifier']=secrets.token_urlsafe(32)
    if changed=='redirect':body['redirect_uri']=ORIGIN+'/wrong'
    if changed=='replay':x.releases.exchange(app['app_id'],body,ORIGIN)
    with pytest.raises(WorkspaceDenied):x.releases.exchange(app['app_id'],body,'https://other.example' if changed=='origin' else ORIGIN)


def test_deployment_withdrawal_during_tools_list_prevents_actual_tool_dispatch(release_world):
    x=release_world;app=deployment(x);token=app_token(x,app['app_id']);before=x.calls.count('tools/call')
    x.control['before_call']=lambda:x.releases.revoke_deployment(*x.args,app['app_id'],{'revision':app['revision']},x.actor)
    result,_=run_app(x,app['app_id'],token)
    assert result['run']['status'] in ('denied','failed') and x.calls.count('tools/call')==before


def test_customer_link_withdrawal_invalidates_app_token_without_admin_identity_conversion(release_world):
    x=release_world;app=deployment(x);token=app_token(x,app['app_id'])
    with x.w.store.tx() as db:db.execute('UPDATE customer_workspace_links SET active=0,revision=revision+1 WHERE customer_id=?',(x.customer.customer_id,))
    with pytest.raises(WorkspaceDenied):x.releases.prepare(app['app_id'],token['access_token'],ORIGIN)
    with pytest.raises(WorkspaceDenied):x.releases.authorize(app['app_id'],{'origin':ORIGIN,'redirect_uri':ORIGIN+'/bff/callback','challenge':'x'*43,'state':'s'*43},x.actor)


def test_status_capability_cannot_read_another_run_or_app_and_survives_grant_withdrawal(release_world):
    x=release_world;app=deployment(x);token=app_token(x,app['app_id']);result,_=run_app(x,app['app_id'],token)
    x.releases.revoke_deployment(*x.args,app['app_id'],{'revision':app['revision']},x.actor)
    cap=result['status_capability']['access_token']
    assert x.releases.status(app['app_id'],cap,result['run']['id'],ORIGIN)['status']=='succeeded'
    with pytest.raises(WorkspaceDenied):x.releases.status(app['app_id'],cap,'wpr_'+'f'*32,ORIGIN)
    with pytest.raises(WorkspaceDenied):x.releases.status('wap_'+'f'*32,cap,result['run']['id'],ORIGIN)
    with pytest.raises(WorkspaceDenied):x.releases.prepare(app['app_id'],token['access_token'],ORIGIN)


def test_atomic_deployment_admission_budget_counts_replay_once(release_world):
    x=release_world;app=deployment(x,minute_limit=1);token=app_token(x,app['app_id']);result,plan=run_app(x,app['app_id'],token)
    assert x.releases.execute(app['app_id'],token['access_token'],{'ticket_id':plan['ticket_id'],'authorized':True,'notice':RUN_NOTICE},ORIGIN)['run']['id']==result['run']['id']
    another=x.releases.prepare(app['app_id'],token['access_token'],ORIGIN)
    with pytest.raises(WorkspaceConflict):x.releases.execute(app['app_id'],token['access_token'],{'ticket_id':another['ticket_id'],'authorized':True,'notice':RUN_NOTICE},ORIGIN)


def test_lifecycle_tombstones_unused_expired_tickets_archives_outputs_and_never_resends(release_world,monkeypatch):
    import agent_market.workspace_lifecycle as lifecycle
    x=release_world;pending=x.staff.prepare(*x.args,{'snapshot_revision':x.w.snapshot['revision']},x.actor);before=x.calls.count('tools/call')
    monkeypatch.setattr(lifecycle,'_now',lambda:time.time()+86400*8)
    value=x.lifecycle.maintain(x.args[0],{'limit':50},x.actor)
    assert value['expired_unused_pruned']==1 and value['outputs_archived']==1 and value['unknown_deleted']==0
    assert x.w.store.query('SELECT id FROM workspace_ticket_tombstones WHERE id=?',(pending['ticket_id'],))
    assert x.staff.run(*x.args,x.result['id'],x.actor)['output'] is None
    assert x.calls.count('tools/call')==before
    with pytest.raises(WorkspaceDenied):x.staff.execute(*x.args,{'ticket_id':pending['ticket_id'],'authorized':True,'notice':NOTICE},x.actor)


def test_reconciliation_notes_do_not_change_certainty_and_restore_review_never_revives_members(release_world):
    x=release_world;value=x.lifecycle.reconcile(*x.args,x.result['id'],{'revision':0,'note':'Owner checked the retained result.'},x.actor)
    assert value['revision']==1 and value['resent'] is False and value['execution_status_changed'] is False
    with pytest.raises(WorkspaceConflict):x.lifecycle.reconcile(*x.args,x.result['id'],{'revision':0,'note':'Stale owner note'},x.actor)
    review=x.lifecycle.prepare_restore_review(*x.args,x.actor);approved=x.lifecycle.approve_restore_review(x.args[0],{'review_id':review['review_id'],'authorized':True,'notice':'workspace-current-owner-review-v1'},x.actor)
    assert not approved['restores_memberships'] and not approved['reactivates_old_grants'] and approved['fresh_grants_required']
    with x.w.store.tx() as db:db.execute('UPDATE workspace_memberships SET active=0,revision=revision+1')
    with pytest.raises(WorkspaceDenied):x.lifecycle.prepare_restore_review(*x.args,x.actor)


def test_opaque_token_database_retargeting_fails_closed_without_signing_key(release_world):
    x=release_world;app=deployment(x);token=app_token(x,app['app_id']);forged=secrets.token_urlsafe(32)
    with x.w.store.tx() as db:db.execute('UPDATE workspace_app_tokens SET token_hash=? WHERE token_hash=?',(x.releases._ref(forged),x.releases._ref(token['access_token'])))
    with pytest.raises(WorkspaceDenied):x.releases.prepare(app['app_id'],forged,ORIGIN)


def test_unknown_run_survives_retention_and_no_provider_is_recalled(release_world,monkeypatch):
    import agent_market.workspace_lifecycle as lifecycle
    x=release_world;x.control['mode']='timeout';ticket=x.staff.prepare(*x.args,{'snapshot_revision':x.w.snapshot['revision']},x.actor)
    job=x.staff.execute(*x.args,{'ticket_id':ticket['ticket_id'],'authorized':True,'notice':NOTICE},x.actor);assert job['status']=='unknown'
    before=x.calls.count('tools/call');monkeypatch.setattr(lifecycle,'_now',lambda:time.time()+86400*8)
    x.lifecycle.maintain(x.args[0],{'limit':50},x.actor)
    assert x.staff.run(*x.args,job['id'],x.actor)['status']=='unknown' and x.calls.count('tools/call')==before


def test_retention_failure_rolls_back_earlier_tombstone_and_ticket_delete(release_world,monkeypatch):
    import agent_market.workspace_lifecycle as lifecycle
    x=release_world;pending=x.staff.prepare(*x.args,{'snapshot_revision':x.w.snapshot['revision']},x.actor);sign=x.lifecycle._sign
    monkeypatch.setattr(lifecycle,'_now',lambda:time.time()+86400*8)
    def fail(value):
        if value.get('run_id')==x.result['id']:raise WorkspaceConflict()
        return sign(value)
    monkeypatch.setattr(x.lifecycle,'_sign',fail)
    with pytest.raises(WorkspaceConflict):x.lifecycle.maintain(x.args[0],{'limit':50},x.actor)
    assert x.w.store.query('SELECT id FROM workspace_private_tickets WHERE id=?',(pending['ticket_id'],))
    assert not x.w.store.query('SELECT id FROM workspace_ticket_tombstones WHERE id=?',(pending['ticket_id'],))
