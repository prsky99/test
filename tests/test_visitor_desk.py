"""Isolated API security and accuracy regressions for individual visitor handling."""
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.concierge.task_updates import UpdateError
from agent_market.gateway.dashboard import dashboard_router
from tests.admin_public_helpers import prepare, approved
from agent_market.gateway.visitor_desk import VisitorDesk
from tests.test_task_updates_security import updates, catalog  # noqa: F401
from tests.test_fast_single_recommendation import ask
from tests.conftest import STAFF, staff_session  # individual staff session; the machine token reads aggregates only

AUTH=STAFF

@pytest.fixture
def desk(updates):
    store,front,client,add,headers,courier,data,vid=updates
    front.llm=None
    app=FastAPI();app.include_router(dashboard_router(store,':memory:','desk-test',None,front=front))
    staff_session(store)
    from agent_market.workspace_admin_events import migrate
    migrate(store,b'synthetic-public-integration-key32')
    with TestClient(app,base_url='https://admin.test') as admin:
        yield (*updates,admin)


def register(desk,channel='webhook',verify=True,vid=None):
    store,front,client,add,headers,courier,data,visitor,admin=desk
    row=front.updates.create(vid or visitor,{**data,'channel':channel,'url':'https://inbox.example/private-routing-secret'})
    if channel!='poll' and verify:
        front.updates.send_challenge(row['id'])
        front.updates.verify(vid or visitor,row['id'],courier.challenges[-1]['verification_code'])
    return row['id']


def test_contact_filters_counts_and_pagination_use_new_and_legacy_sources(desk):
    store,front,client,add,headers,courier,data,vid,admin=desk
    register(desk)
    client.post('/chat',headers=headers,json={'message':'MCP weather forecast'})
    other=ask(client,'hello')['visitor']['id']
    poll=ask(client,'weather forecast')['visitor']['id'];register(desk,'poll',vid=poll)
    with store.tx() as db:
        db.execute("INSERT INTO agent_contacts(visitor_id,type,url,status,created) VALUES (?,?,?,?,?)",(other,'webhook','https://legacy.example/secret','verified',time.time()))
    res=admin.get('/admin/api/visitors',headers=AUTH,params={'contact':'registered','limit':1}).json()
    assert res['filtered_stats']['total']==2 and res['filtered_stats']['authorized']==1
    assert res['pagination']['has_more'] and len(res['items'])==1
    second=admin.get('/admin/api/visitors',headers=AUTH,params={'contact':'registered','limit':1,'offset':1}).json()
    assert res['items'][0]['id']!=second['items'][0]['id']
    assert {r['id'] for r in admin.get('/admin/api/visitors',headers=AUTH,params={'contact':'none'}).json()['items']}=={poll}
    assert admin.get('/admin/api/visitors',headers=AUTH,params={'q':"%' OR 1=1 --"}).json()['filtered_stats']['total']==0
    # Automatic requests prefer A2A then MCP; they are recorded as "any", not as an explicit A2A choice.
    assert admin.get('/admin/api/visitors',headers=AUTH,params={'protocol':'any'}).json()['filtered_stats']['total']==2  # automatic + no interest yet
    assert admin.get('/admin/api/visitors',headers=AUTH,params={'protocol':'a2a'}).json()['filtered_stats']['total']==0
    assert admin.get('/admin/api/visitors',headers=AUTH,params={'protocol':'mcp','contact':'authorized'}).json()['items'][0]['id']==vid
    with store.tx() as db:db.execute('UPDATE agent_task_watches SET notice_version=? WHERE visitor_id=?',('old',vid))
    assert admin.get('/admin/api/visitors',headers=AUTH,params={'contact':'authorized'}).json()['filtered_stats']['total']==0


def test_history_retains_actual_selector_and_snapshot_without_retroactive_reconstruction(desk):
    store,front,client,add,headers,courier,data,vid,admin=desk
    a2a=add('A2A Weather',kind='a2a',report_at=time.time())
    body=client.post('/chat',headers=headers,json={'message':'MCP weather forecast','data':{'protocol':'a2a'}}).json()
    original=body['data']['recommendations'][0]
    with store.tx() as db:
        db.execute('UPDATE resources SET name=?,eval_grade=? WHERE id=?',('Renamed later','C',a2a))
        db.execute("INSERT INTO agent_messages(visitor_id,at,role,channel,text,data) VALUES (?,?,?,?,?,?)",(vid,time.time(),'concierge','web','Old response','{}'))
    detail=admin.get('/admin/api/visitors/'+vid,headers=AUTH).json()
    turn=detail['chat_turns'][0]
    assert turn['question']=='MCP weather forecast' and turn['protocol_mode']=='a2a' and turn['protocol_filter']=='a2a'
    assert turn['recommendations'][0]['id']==a2a and turn['recommendations'][0]['name']==original['name']
    assert turn['recommendations'][0]['grade']=='A' and turn['recommendations'][0]['test_report']==original['test_report']
    assert detail['legacy_messages']==1 and len(detail['chat_turns'])==2
    client.post('/chat',headers=headers,json={'message':'contact https://inbox.example/private-secret'})
    redacted=admin.get('/admin/api/visitors/'+vid,headers=AUTH).json()['chat_turns'][0]
    assert 'private-secret' not in json.dumps(redacted) and redacted['status']=='permission_required'


def test_case_saved_as_internal_only_and_optimistic_conflict(desk):
    store,front,client,add,headers,courier,data,vid,admin=desk
    path='/admin/api/visitors/'+vid+'/case'
    body={'status':'waiting','owner':'Desk team','next_followup':time.time()-1,'note':'Review weather coverage <script>alert(1)</script>','version':0}
    saved=admin.post(path,headers=AUTH,json=body)
    assert saved.status_code==200 and saved.json()['version']==1
    assert admin.post(path,headers=AUTH,json=body).status_code==409
    detail=admin.get(path[:-5],headers=AUTH).json()
    assert detail['case']['owner']=='Desk team' and len(detail['case_notes'])==1
    assert '<script>' not in detail['case_notes'][0]['body'] and detail['case_notes'][0]['actor']
    stats=admin.get('/admin/api/visitors',headers=AUTH,params={'case_state':'waiting'}).json()['filtered_stats']
    assert stats['total']==1 and stats['followup_due']==1
    assert admin.post(path,headers=AUTH,json={**body,'version':1,'status':'resolved'}).status_code==200
    assert admin.get(path[:-5],headers=AUTH).json()['case']['next_followup'] is None
    assert not courier.events and not courier.challenges
    for invalid in [[],{'status':'oops','version':2},{**body,'version':2,'owner':'x'*81},{**body,'version':2,'next_followup':True}]:
        assert admin.post(path,headers=AUTH,json=invalid).status_code==400
    assert admin.post(path,json=body).status_code in (401,403)
    assert admin.post(path,headers={**AUTH,'Origin':'https://evil.example'},json=body).status_code==403


def test_individual_preview_no_send_then_exact_watch_only_and_replay_blocked(desk):
    store,front,client,add,headers,courier,data,vid,admin=desk
    wid=register(desk);other=ask(client,'weather forecast')['visitor']['id'];second=register(desk,vid=other)
    add('Newest Weather',report_at=time.time())
    prepare(store,AUTH)
    base=f'/admin/api/visitors/{vid}/task-updates/{wid}'
    preview=admin.get(base+'/preview',headers=AUTH).json()
    assert preview['can_process'] and preview['recommendation']['name']=='Newest Weather'
    assert preview['watch']['destination']=='https://inbox.example/…'
    assert 'private-routing-secret' not in json.dumps(preview) and not courier.events
    assert not store.query('SELECT * FROM agent_task_events')
    assert admin.get(f'/admin/api/visitors/{other}/task-updates/{wid}/preview',headers=AUTH).status_code==404
    assert admin.post(base+'/process',headers=AUTH,json={'preview_token':preview['preview_token']+'bad'}).status_code==409
    other_watch=register(desk,'poll')
    assert admin.post(f'/admin/api/visitors/{vid}/task-updates/{other_watch}/process',headers=AUTH,json={'preview_token':preview['preview_token']}).status_code==409
    result=admin.post(base+'/process',headers=AUTH,json={'preview_token':preview['preview_token'],'message':'Send my promotion','reason':'Synthetic exact task review'})
    assert not courier.events
    assert approved(admin,AUTH,result)['sent']==1
    assert len(courier.events)==1 and 'promotion' not in json.dumps(courier.events)
    assert not store.query('SELECT * FROM agent_task_events WHERE watch_id=?',(second,))
    assert admin.post(base+'/process',headers=AUTH,json={'preview_token':preview['preview_token']}).status_code==409
    assert admin.post('/admin/api/visitors/nurture/run',headers=AUTH).status_code==403
    assert admin.post(f'/admin/api/visitors/{vid}/digest',headers=AUTH).json()['sent']==0
    assert len(courier.events)==1


@pytest.mark.parametrize('change',['recommendation','endpoint','revoked','expired','actor','notice'])
def test_preview_stale_or_wrong_actor_rejected(desk,change):
    store,front,client,add,headers,courier,data,vid,admin=desk
    wid=register(desk);rid=add('Latest Weather',report_at=time.time())
    p=front.updates.preview(vid,wid,'reviewer')
    if change=='recommendation':add('Newer Weather',report_at=time.time()+1)
    elif change=='endpoint':
        with store.tx() as db:db.execute('UPDATE resources SET url=? WHERE id=?',('https://changed.example/api',rid))
    elif change=='revoked':front.updates.action(vid,wid,'stop')
    elif change=='expired':
        with store.tx() as db:db.execute('UPDATE agent_task_watches SET expires=? WHERE id=?',(time.time()-1,wid))
    elif change=='notice':
        with store.tx() as db:db.execute('UPDATE agent_task_watches SET notice_version=? WHERE id=?',('old',wid))
    with pytest.raises(UpdateError):front.updates.process_preview(vid,wid,'other' if change=='actor' else 'reviewer',p['preview_token'])
    assert not courier.events


def test_stale_queued_payload_never_sent_even_by_worker(desk):
    store,front,client,add,headers,courier,data,vid,admin=desk
    wid=register(desk);add('Weather B',report_at=time.time())
    front.updates.refresh(vid,wid)
    add('Weather C',report_at=time.time()+1)
    assert front.updates.preview(vid,wid,'reviewer')['reason']=='queued_evidence_changed'
    front.updates.run_due(vid)
    assert not courier.events
    assert store.query('SELECT status FROM agent_task_events WHERE watch_id=?',(wid,))[0]['status']=='cancelled'


@pytest.mark.parametrize('column,value', [
    ('url','https://changed.example/api'),
    ('usage_tools_hash','a-new-verified-schema'),
    ('usage_guide',json.dumps({'endpoint':'https://changed.example/rpc'})),
])
def test_private_binding_change_cancels_previously_queued_update(desk,column,value):
    store,front,_,add,_,courier,_,vid,_=desk
    wid=register(desk);rid=add('Bound Weather',report_at=time.time())
    front.updates.refresh(vid,wid)
    assert store.query('SELECT status FROM agent_task_events WHERE watch_id=?',(wid,))[0]['status']=='pending'
    with store.tx() as db:
        db.execute('UPDATE resources SET '+column+'=? WHERE id=?',(value,rid))
    assert front.updates.preview(vid,wid,'reviewer')['reason']=='queued_evidence_changed'
    front.updates.run_due(vid)
    assert not courier.events
    row=store.query('SELECT payload,status FROM agent_task_events WHERE watch_id=?',(wid,))[0]
    assert row['status']=='cancelled' and row['payload']=='{}'


def test_non_binding_metadata_does_not_invalidate_review(desk):
    store,front,_,add,_,courier,_,vid,_=desk
    wid=register(desk);rid=add('Stable Weather',report_at=time.time())
    preview=front.updates.preview(vid,wid,'reviewer')
    with store.tx() as db:
        db.execute('UPDATE resources SET details=? WHERE id=?',
                   (json.dumps({'fetched_at':time.time(),'description':'Updated catalog description'}),rid))
    assert front.updates.process_preview(vid,wid,'reviewer',preview['preview_token'])['sent']==1
    assert len(courier.events)==1


def test_poll_processing_scope_and_visitor_prune_protects_open_case(desk):
    store,front,client,add,headers,courier,data,vid,admin=desk
    wid=register(desk,'poll');add('Poll Weather Latest',report_at=time.time())
    p=front.updates.preview(vid,wid,'reviewer')
    assert front.updates.process_preview(vid,wid,'reviewer',p['preview_token'])['status']=='ready'
    assert not courier.events
    VisitorDesk(store).save_case(vid,{'status':'reviewing','version':0},'reviewer')
    with store.tx() as db:db.execute('UPDATE agent_visitors SET last_seen=?,messages=0 WHERE id=?',(time.time()-40*86400,vid))
    front.book.prune()
    assert store.query('SELECT id FROM agent_visitors WHERE id=?',(vid,))


def test_operator_cannot_save_or_process(desk):
    from agent_market.gateway.admin_auth import create_admin_user
    store,front,client,add,headers,courier,data,vid,admin=desk
    with store.tx() as db:create_admin_user(db,'viewer','viewer-password-123','Viewer','operator')
    token=admin.post('/admin/api/auth/login',headers={'X-Dashboard':'1'},json={'username':'viewer','password':'viewer-password-123'}).json()['token']
    auth={**AUTH,'Authorization':'Bearer '+token}
    assert admin.get('/admin/api/visitors/'+vid,headers=auth).status_code==200
    assert admin.post('/admin/api/visitors/'+vid+'/case',headers=auth,json={'version':0,'status':'new'}).status_code==403
    assert admin.post('/admin/api/visitors/'+vid+'/task-updates/none/process',headers=auth,json={}).status_code==403


def test_preview_expires_and_disabled_outbound_never_processes(desk,monkeypatch):
    store,front,client,add,headers,courier,data,vid,admin=desk
    wid=register(desk);add('Next Weather',report_at=time.time())
    p=front.updates.preview(vid,wid,'reviewer')
    now=time.time()
    with monkeypatch.context() as context:
        context.setattr('agent_market.concierge.task_updates.time.time',lambda:now+301)
        with pytest.raises(UpdateError):front.updates.process_preview(vid,wid,'reviewer',p['preview_token'])
    front.updates.outbound_enabled=False
    assert front.updates.preview(vid,wid,'reviewer')['reason']=='delivery_disabled'
    with pytest.raises(UpdateError):front.updates.process_preview(vid,wid,'reviewer',p['preview_token'])
    assert not courier.events


def test_catalog_change_between_review_and_refresh_requires_review_again(desk,monkeypatch):
    store,front,client,add,headers,courier,data,vid,admin=desk
    wid=register(desk)
    with store.tx() as db:db.execute("UPDATE resources SET health_status='down'")
    p=front.updates.preview(vid,wid,'reviewer')
    assert p['can_process'] and p['recommendation'] is None
    original=front.updates.refresh
    def changed(*args,**kwargs):
        add('Arrived After Review',report_at=time.time())
        return original(*args,**kwargs)
    monkeypatch.setattr(front.updates,'refresh',changed)
    with pytest.raises(UpdateError):front.updates.process_preview(vid,wid,'reviewer',p['preview_token'])
    assert not courier.events and not store.query('SELECT * FROM agent_task_events')


def test_pending_contacts_and_simulation_are_distinct_filters(desk):
    store,front,client,add,headers,courier,data,vid,admin=desk
    register(desk,verify=False)
    with store.tx() as db:db.execute("UPDATE agent_visitors SET channel='admin-test' WHERE id=?",(vid,))
    live=admin.get('/admin/api/visitors',headers=AUTH,params={'source':'live','contact':'pending'}).json()
    simulation=admin.get('/admin/api/visitors',headers=AUTH,params={'source':'simulation','contact':'pending'}).json()
    assert live['filtered_stats']['total']==0 and simulation['filtered_stats']['pending']==1
    assert simulation['items'][0]['authorized_inboxes']==0


def test_large_history_metadata_keeps_valid_json_and_marks_evidence_gap(desk):
    store,front,client,add,headers,courier,data,vid,admin=desk
    visitor=front.book.by_id(vid)
    request=front.book.add_message(visitor,'agent','rest','weather forecast',{'record_version':1,'protocol_mode':'auto'})
    front.book.add_message(visitor,'concierge','rest','Recorded reply',{'record_version':1,'request_message_id':request,'recommendations':[{'name':'x'*9000}]})
    detail=VisitorDesk(store,front.updates).detail(vid)
    assert detail['chat_turns'][0]['metadata_truncated'] and detail['chat_turns'][0]['recommendations']==[]
    assert detail['chat_turns'][0]['question']=='weather forecast'


def test_verified_separate_marketing_permission_is_view_only_and_audited(desk):
    from agent_market.concierge.task_updates import MARKETING_NOTICE
    store,front,client,add,headers,courier,data,vid,admin=desk
    body={**data,'channel':'webhook','url':'https://inbox.example/private-marketing-route','marketing':True,'marketing_notice_version':MARKETING_NOTICE}
    row=front.updates.create(vid,body);wid=row['id']
    assert admin.get('/admin/api/visitors',headers=AUTH,params={'contact':'marketing'}).json()['items']==[]
    front.updates.send_challenge(wid);front.updates.verify(vid,wid,courier.challenges[-1]['verification_code'])
    result=admin.get('/admin/api/visitors',headers=AUTH,params={'contact':'marketing'}).json()
    assert result['items'][0]['id']==vid and result['filtered_stats']['marketing_eligible']==1
    detail=admin.get('/admin/api/visitors/'+vid,headers=AUTH).json()
    contact=detail['contact_relationships'][0]
    assert contact['marketing_requested_at'] and contact['marketing_verified_at'] and contact['marketing_eligible']
    assert detail['policy']['marketing_enabled'] is False and 'private-marketing-route' not in json.dumps(detail)
    path=f'/admin/api/visitors/{vid}/task-updates/{wid}/action'
    assert admin.post(path,headers=AUTH,json={'action':'grant_marketing'}).status_code in (400,403)
    assert admin.post(path,headers=AUTH,json={'action':'withdraw_marketing','reason':'Synthetic consent withdrawal'}).status_code==200
    assert admin.get('/admin/api/visitors',headers=AUTH,params={'contact':'marketing'}).json()['items']==[]
    assert front.updates._get(wid)['state']=='active' and not courier.events
    detail=admin.get('/admin/api/visitors/'+vid,headers=AUTH).json()
    assert detail['contact_relationships'][0]['marketing_withdrawn_at']
    assert any(r['purpose']=='marketing' and r['action']=='withdrawn' for r in detail['task_permissions'])
