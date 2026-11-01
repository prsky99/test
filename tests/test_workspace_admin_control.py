"""Synthetic customer/staff journeys; no operating account or provider calls."""
# ruff: noqa: F811
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.customer_identity_service import COOKIE
from agent_market.workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid
from agent_market.workspace_admin_control import WorkspaceAdminControl
from agent_market.workspace_admin_events import activate, drain, emit, migrate
from agent_market.workspace_admin_service import BASE, router_for
from agent_market.workspace_admin_worker import backfill, prune, quarantine
from tests.test_customer_organizations import orgs  # noqa: F401
from tests.test_customer_credits import acceptance
from tests.test_workspace_access import draft_body

HEADERS={'Authorization':'Bearer '+'a'*64,'X-Dashboard':'1'}


@pytest.fixture
def operations(orgs):
    w=orgs
    migrate(w.store,w.core.key)
    w.ops=WorkspaceAdminControl(w.core,w.access)
    w.ops.credits.enroll(acceptance(),w.customers[0])
    from agent_market import workspace_execution,workspace_typed_flows,workspace_release
    with w.core.tx() as db:
        for module in (workspace_execution,workspace_typed_flows,workspace_release):
            for sql in module.SCHEMA: db.execute(sql)
    return w


def case_body(**kwargs):
    return {'subject':'Credit question','message':'Please review this saved workflow.',
            'workspace_id':None,'source_ref':None,'request_id':secrets.token_hex(16),**kwargs}


def command_body(w,**kwargs):
    return {'customer_id':w.customers[0].customer_id,'kind':'credit_adjust','target_revision':1,
            'delta':2,'credit_status':'active','reason':'Confirmed synthetic correction',
            'request_id':secrets.token_hex(16),**kwargs}


def test_explicit_migration_only_and_existing_calls_unchanged(orgs):
    w=orgs; core=WorkspaceAdminControl(w.core,w.access)
    assert core.options(w.staff[1])['migration_required']
    assert not w.store._db.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_admin_cases'").fetchone()
    with pytest.raises(WorkspaceConflict):core.overview(w.staff[1])
    migrate(w.store,w.core.key); migrate(w.store,w.core.key)
    assert activate(w.store,w.core.key)
    assert not core.options(w.staff[1])['migration_required']


def test_atomic_credit_audit_projection_and_signed_tamper(operations):
    w=operations; a=w.customers[0]
    with pytest.raises(RuntimeError):
        with w.core.tx() as db:
            w.ops.credits.saved(db,w.organization['id'],'atomic-failed',1,a)
            raise RuntimeError('Synthetic rollback')
    assert w.ops.credits.status(a)['balance']==100
    first=drain(w.store); assert first['projected']==1
    assert drain(w.store)['projected']==0
    result=w.ops.events(w.staff[1],a.customer_id)
    assert result['events'][0]['event_type'].startswith('credit.')
    with w.core.tx() as db:
        emit(w.store,db,'execution.failed',customer=a.customer_id)
        db.execute("UPDATE workspace_admin_outbox SET payload='{}'")
    result=drain(w.store)
    assert result['quarantined']==1
    assert not w.ops.overview(w.staff[1])['ingestion']['complete']


def test_credit_reconciliation_and_reviewed_exactly_once_command(operations):
    w=operations;c=w.ops
    assert c.reconciliation(w.staff[1])['accounts'][0]['status']=='matched'
    body=command_body(w); created=c.command(w.staff[2],body)
    assert c.command(w.staff[2],body)['replayed']
    with pytest.raises(WorkspaceConflict):c.command(w.staff[2],dict(body,delta=3))
    with pytest.raises(WorkspaceDenied):c.approve(w.staff[2],created['command_id'],{'revision':1,'reason':'Confirmed synthetic review','confirm':'APPLY'})
    result=c.approve(w.staff[1],created['command_id'],{'revision':1,'reason':'Confirmed synthetic review','confirm':'APPLY'})
    assert result['status']=='applied'
    assert c.credits.status(w.customers[0])['balance']==102
    assert c.approve(w.staff[1],created['command_id'],{'revision':1,'reason':'Confirmed synthetic review','confirm':'APPLY'})['replayed']
    assert c.credits.status(w.customers[0])['balance']==102


def test_conflict_restore_blocks_operator_and_no_fabricated_enrollment(operations):
    w=operations;c=w.ops
    with pytest.raises(WorkspaceDenied):c.command(w.staff[3],command_body(w))
    for body in (command_body(w,target_revision=2),command_body(w,customer_id=w.customers[1].customer_id)):
        item=c.command(w.staff[2],body)
        with pytest.raises((WorkspaceDenied,WorkspaceConflict)):
            c.approve(w.staff[1],item['command_id'],{'revision':1,'reason':'Synthetic highest staff review','confirm':'APPLY'})
    with w.core.tx() as db:
        db.execute('INSERT INTO customer_credit_restore_blocks VALUES(?)',(w.customers[0].customer_id,))
    item=c.command(w.staff[2],command_body(w))
    with pytest.raises(WorkspaceDenied):c.approve(w.staff[1],item['command_id'],{'revision':1,'reason':'Synthetic restore block review','confirm':'APPLY'})


def test_concurrent_approval_and_critical_outbox_failure_roll_back(operations,monkeypatch):
    w=operations;c=w.ops;item=c.command(w.staff[2],command_body(w))
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=list(pool.map(lambda _:c.approve(w.staff[1],item['command_id'],{'revision':1,'reason':'Concurrent synthetic approval','confirm':'APPLY'}),range(4)))
    assert sum(not x['replayed'] for x in result)==1
    assert c.credits.status(w.customers[0])['balance']==102
    from agent_market import workspace_admin_events as module
    original=module.execute
    def fail(db,name,params=()):
        if name=='outbox_insert':raise WorkspaceConflict()
        return original(db,name,params)
    monkeypatch.setattr(module,'execute',fail)
    with pytest.raises(WorkspaceConflict):
        c.credits.admin_change(w.access,w.customers[0].customer_id,
            {'revision':2,'delta':3,'status':'active','reason':'Synthetic atomic rollback','request_id':secrets.token_hex(16)},w.staff[1])
    assert c.credits.status(w.customers[0])['balance']==102


def test_customer_sessions_revoke_and_admin_session_revocation(operations):
    w=operations;c=w.ops
    item=c.command(w.staff[2],command_body(w,kind='sessions_revoke'))
    c.approve(w.staff[1],item['command_id'],{'revision':1,'reason':'Synthetic session revocation','confirm':'APPLY'})
    with pytest.raises(WorkspaceDenied):w.core.actor(w.auths[0]['session_token'])
    with w.core.tx() as db:db.execute('DELETE FROM admin_sessions WHERE user_id=2')
    with pytest.raises(WorkspaceDenied):c.customers(w.staff[2])


def test_case_idempotency_notes_revision_and_customer_boundary(operations):
    w=operations;c=w.ops;customer=w.customers[0].customer_id
    body=case_body();case=c.create_case(w.staff[2],customer,body)['case']
    assert c.create_case(w.staff[2],customer,body)['case']['id']==case['id']
    with pytest.raises(WorkspaceConflict):c.create_case(w.staff[2],customer,dict(body,subject='Different subject'))
    action={'revision':1,'status':'waiting_internal','priority':'high','assigned_to':2,'message':'Internal account review',
            'visibility':'internal','request_id':secrets.token_hex(16)}
    assert c.case_action(w.staff[2],case['id'],action)['case']['revision']==2
    assert c.case_action(w.staff[2],case['id'],action)['replayed']
    with pytest.raises(WorkspaceConflict):c.case_action(w.staff[2],case['id'],dict(action,status='closed'))
    with pytest.raises(WorkspaceDenied):c.case(w.staff[3],case['id'])
    with w.core.tx() as db:
        with pytest.raises(WorkspaceDenied):c._case(db,case['id'],w.customers[1].customer_id)


def test_scoped_disclosure_current_revision_revocation_and_no_membership(operations):
    w=operations;c=w.ops;actor=w.customers[0];ws=w.organization['id']
    draft=w.orgs.drafts.save_draft(ws,draft_body(),w.orgs.runtime_actor(ws,actor))
    item=c.create_case(w.staff[2],actor.customer_id,case_body(workspace_id=ws))['case']
    grant=c.disclosure(actor,item['id'],{'workspace_id':ws,'draft_id':draft['id'],'ttl_seconds':60,'confirm':'SHARE'})
    assert c.disclosure_read(w.staff[1],grant['disclosure_id'])['draft']['id']==draft['id']
    with pytest.raises(WorkspaceDenied):c.disclosure_read(w.staff[2],grant['disclosure_id'])
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id=?',(ws,)).fetchone()[0]==0
    c.disclosure_revoke(actor,grant['disclosure_id'],{'revision':1})
    with pytest.raises(WorkspaceDenied):c.disclosure_read(w.staff[1],grant['disclosure_id'])


@pytest.mark.parametrize('change',['expiry','draft_revision','membership','binding'])
def test_disclosure_rechecks_every_authority(operations,change):
    w=operations;c=w.ops;a=w.customers[0];ws=w.organization['id']
    draft=w.orgs.drafts.save_draft(ws,draft_body(),w.orgs.runtime_actor(ws,a))
    case=c.create_case(w.staff[1],a.customer_id,case_body(workspace_id=ws))['case']
    grant=c.disclosure(a,case['id'],{'workspace_id':ws,'draft_id':draft['id'],'ttl_seconds':60,'confirm':'SHARE'})
    with w.core.tx() as db:
        if change=='expiry':db.execute('UPDATE workspace_admin_disclosures SET expires=0')
        elif change=='draft_revision':db.execute('UPDATE workspace_drafts SET revision=revision+1')
        elif change=='membership':db.execute('UPDATE customer_workspace_links SET active=0')
        else:db.execute("UPDATE workspace_admin_disclosures SET binding='tampered'")
    with pytest.raises((WorkspaceDenied,WorkspaceConflict)):c.disclosure_read(w.staff[1],grant['disclosure_id'])


def test_backfill_bounded_replay_and_restore_quarantine(operations):
    w=operations
    assert backfill(w.store,1)['source_rows_reviewed']>=1
    drain(w.store)
    before=w.store._db.execute('SELECT COUNT(*) FROM workspace_admin_events').fetchone()[0]
    with w.core.tx() as db:db.execute("DELETE FROM workspace_admin_state WHERE id LIKE 'backfill:%'")
    backfill(w.store,1);drain(w.store)
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_admin_events').fetchone()[0]==before
    command=w.ops.command(w.staff[2],command_body(w))
    quarantine(w.store)
    with pytest.raises(WorkspaceConflict):w.ops.approve(w.staff[1],command['command_id'],{'revision':1,'reason':'Restored command review','confirm':'APPLY'})


def test_privacy_cleanup_and_no_false_activity(operations):
    w=operations
    drain(w.store)
    with w.core.tx() as db:db.execute('UPDATE workspace_admin_events SET occurred=?',(time.time()-31*86400,))
    assert prune(w.store)['expired_events_removed']>=1
    v=w.ops.overview(w.staff[1]);assert v['events']==[]
    assert v['commerce']['actual_revenue'] is None and v['commerce']['payments']=='coming_soon'


def test_admin_and_customer_transport_csrf_rbac_private_notes(operations):
    w=operations;app=FastAPI();app.include_router(router_for(w.core,w.access,core=w.ops))
    app.include_router(router_for(w.core,w.access,core=w.ops,public=True))
    with TestClient(app,base_url='https://customer.test') as client:
        assert client.get(BASE+'/customers').status_code==401
        assert client.get(BASE+'/customers',headers={'X-Dashboard':'1','Authorization':'Bearer machine-token'}).status_code==401
        assert client.get(BASE+'/customers',headers=dict(HEADERS,Origin='https://evil.test')).status_code==403
        assert client.get(BASE+'/customers',headers=HEADERS).status_code==200
        client.cookies.set(COOKIE,w.auths[0]['session_token'])
        payload=case_body()
        assert client.post('/api/customer-support/cases',json=payload).status_code==403
        headers={'Origin':'https://customer.test','X-Customer-CSRF':w.core.csrf(w.auths[0]['session_token'])}
        response=client.post('/api/customer-support/cases',json=payload,headers=headers)
        assert response.status_code==200,response.text
        case=response.json()['case']
        assert client.post('/api/customer-support/cases',json=payload,headers=headers).json()['case']['id']==case['id']
        note={'revision':1,'status':'waiting_internal','priority':'normal','assigned_to':1,'message':'Internal secret support note',
              'visibility':'internal','request_id':secrets.token_hex(16)}
        assert client.post(BASE+'/cases/'+case['id']+'/actions',json=note,headers=HEADERS).status_code==200
        public=client.get('/api/customer-support/cases/'+case['id'])
        assert 'Internal secret support note' not in public.text and 'assigned_to' not in public.text
        client.cookies.set(COOKIE,w.auths[1]['session_token'])
        assert client.get('/api/customer-support/cases/'+case['id']).status_code==403
        page=client.get('/customer/support');assert page.status_code==200 and "script-src 'nonce-" in page.headers['content-security-policy']
        assert 'no-store' in page.headers['cache-control']


@pytest.mark.parametrize('name,params',[
    ('customers',{'q':"%' OR 1=1 --"}),('customers',{'limit':True}),('events',{'before':float('nan')}),
    ('events',{'hours':169}),('organizations',{'cursor':'x'*121})])
def test_bounded_inputs(operations,name,params):
    with pytest.raises(WorkspaceInvalid):getattr(operations.ops,name)(operations.staff[1],**params)


def test_native_view_projections_omit_private_bodies(operations):
    w=operations;v=w.ops.operations(w.staff[1],w.organization['id'])
    assert set(v)=={'drafts','typed_flows','executions','typed_executions','releases','deployments'}
    serialized=json.dumps(v)
    assert 'definition' not in serialized and 'payload' not in serialized and 'token' not in serialized


def test_auth_failure_is_anonymous_and_projection_tampering_is_rejected(operations):
    w=operations
    with pytest.raises(WorkspaceDenied):w.core.complete('invalid-state','synthetic-code','b'*64)
    drain(w.store)
    with w.core.tx() as db:
        failed=db.execute("SELECT customer_id FROM workspace_admin_events WHERE event_type='auth.failed'").fetchone()
        assert failed and failed[0] is None
        db.execute("UPDATE workspace_admin_events SET outcome='failed'")
    with pytest.raises(WorkspaceConflict):w.ops.events(w.staff[1])


def test_self_approval_requires_fresh_session_and_explicit_acknowledgment(operations):
    w=operations;item=w.ops.command(w.staff[1],command_body(w))
    body={'revision':1,'reason':'Explicit single administrator review','confirm':'APPLY'}
    with pytest.raises(WorkspaceDenied):w.ops.approve(w.staff[1],item['command_id'],body)
    with w.core.tx() as db:db.execute('UPDATE admin_sessions SET created_at=? WHERE user_id=1',(time.time()-601,))
    with pytest.raises(WorkspaceDenied):w.ops.approve(w.staff[1],item['command_id'],dict(body,allow_self_review=True))
    assert w.ops.credits.status(w.customers[0])['balance']==100


def test_malformed_event_does_not_poison_following_batch(operations):
    w=operations
    with w.core.tx() as db:
        emit(w.store,db,'execution.failed',customer=w.customers[0].customer_id)
        db.execute("UPDATE workspace_admin_outbox SET payload='not-json' WHERE event_key=id")
    result=drain(w.store)
    assert result['projected']==1 and result['quarantined']==1


def test_closed_case_retention_and_invalid_assignment(operations):
    w=operations;case=w.ops.create_case(w.staff[2],w.customers[0].customer_id,case_body())['case']
    body={'revision':1,'status':'closed','priority':'normal','assigned_to':999999,'message':'Completed synthetic review',
          'visibility':'internal','request_id':secrets.token_hex(16)}
    with pytest.raises(WorkspaceInvalid):w.ops.case_action(w.staff[2],case['id'],body)
    w.ops.case_action(w.staff[2],case['id'],dict(body,assigned_to=2))
    with w.core.tx() as db:db.execute('UPDATE workspace_admin_cases SET updated=?',(time.time()-91*86400,))
    assert prune(w.store)['closed_cases_pruned']==1
    assert prune(w.store)['closed_cases_pruned']==0
    assert w.ops.case(w.staff[2],case['id'])['messages']==[]


def test_transport_duplicate_fields_and_format_valid_machine_token_denied(operations):
    w=operations;app=FastAPI();app.include_router(router_for(w.core,w.access,core=w.ops))
    with TestClient(app,base_url='https://admin.test') as client:
        assert client.get(BASE+'/customers',headers={'X-Dashboard':'1','Authorization':'Bearer '+'f'*64}).status_code==401
        response=client.post(BASE+'/commands',headers={**HEADERS,'Content-Type':'application/json'},content=b'{"kind":"sessions_revoke","kind":"credit_adjust"}')
        assert response.status_code==400
        assert 'no-store' in response.headers['cache-control']


def test_migration_key_binding_rejects_wrong_namespace(operations):
    w=operations
    with pytest.raises(WorkspaceConflict):activate(w.store,b'x'*32)
    with pytest.raises(WorkspaceConflict):migrate(w.store,b'x'*32)
    assert activate(w.store,w.core.key)
    assert w.ops.credits.status(w.customers[0])['balance']==100


def test_command_cancellation_and_metadata_tamper_fail_closed(operations):
    w=operations;item=w.ops.command(w.staff[2],command_body(w))
    assert w.ops.cancel_command(w.staff[2],item['command_id'],{'revision':1,'reason':'Withdrawal after synthetic review'})['status']=='cancelled'
    with pytest.raises(WorkspaceConflict):w.ops.approve(w.staff[1],item['command_id'],{'revision':1,'reason':'No cancelled application','confirm':'APPLY'})
    item=w.ops.command(w.staff[2],command_body(w))
    with w.core.tx() as db:db.execute('UPDATE workspace_admin_commands SET requested_by=1 WHERE id=?',(item['command_id'],))
    with pytest.raises(WorkspaceConflict):w.ops.command_detail(w.staff[1],item['command_id'])


def test_existing_request_link_preserves_source_and_rejects_duplicate_case(operations):
    w=operations;customer=w.customers[0].customer_id
    with w.core.tx() as db:
        db.execute('CREATE TABLE customer_inquiries(inquiry_id TEXT PRIMARY KEY,status TEXT,created_at REAL)')
        db.execute('INSERT INTO customer_inquiries VALUES(?,?,?)',('inq_fixture','pending',time.time()))
    first=w.ops.create_case(w.staff[2],customer,case_body())['case']
    second=w.ops.create_case(w.staff[2],customer,case_body())['case']
    body={'revision':1,'source_kind':'inquiry','source_ref':'inq_fixture',
          'reason':'Verified synthetic customer relationship','confirmed_customer_relation':True}
    assert w.ops.link_case(w.staff[2],first['id'],body)['original_request_state_unchanged']
    assert w.ops.link_case(w.staff[2],first['id'],body)['replayed']
    with pytest.raises(WorkspaceConflict):w.ops.link_case(w.staff[2],second['id'],body)
    assert w.store._db.execute('SELECT status FROM customer_inquiries').fetchone()[0]=='pending'


def test_deletion_cleanup_and_backfill_cannot_restore_removed_activity(operations):
    w=operations;a=w.customers[0]
    w.ops.create_case(w.staff[2],a.customer_id,case_body())
    w.orgs.delete_account({'revision':1,'confirm':'DELETE','archive_owned':True},a)
    with w.core.tx() as db:db.execute('UPDATE customer_account_deletions SET requested=?',(time.time()-91*86400,))
    assert prune(w.store)['deleted_accounts_reviewed']==1
    backfill(w.store,100);drain(w.store)
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_admin_events WHERE customer_id=?',(a.customer_id,)).fetchone()[0]==0
    assert w.store._db.execute('SELECT COUNT(*) FROM workspace_admin_cases WHERE customer_id=?',(a.customer_id,)).fetchone()[0]==0


def test_missing_optional_historical_source_does_not_block_projection(operations):
    w=operations
    with w.core.tx() as db:db.execute('DROP TABLE customer_organization_audit')
    assert backfill(w.store,100)['source_rows_reviewed']>=1
    assert drain(w.store)['projected']>=1
    coverage=w.ops.overview(w.staff[1])['ingestion']['source_coverage']
    assert {'id':'source:orgs','value':'not_provisioned'} in coverage


def test_anonymous_auth_retention_is_shorter_than_business_history(operations):
    w=operations
    with w.core.tx() as db:
        emit(w.store,db,'auth.failed',outcome='denied',occurred=time.time()-8*86400)
    drain(w.store)
    assert prune(w.store)['anonymous_auth_events_removed']==1
    assert w.ops.events(w.staff[1],w.customers[0].customer_id)['events']


def test_backfill_does_not_launder_invalid_signed_source_records(operations):
    w=operations
    with w.core.tx() as db:db.execute("UPDATE customer_credit_events SET payload='{}'")
    backfill(w.store,100);drain(w.store)
    events=w.ops.events(w.staff[1])['events']
    assert any(item['event_type']=='integrity.failed' for item in events)
    assert not any(item['event_type']=='historical.credit.recorded' for item in events)
    assert 'historical_source_integrity_review_required' in w.ops.overview(w.staff[1])['alerts']


def test_reviewed_command_expires_after_fifteen_minutes(operations):
    w=operations;item=w.ops.command(w.staff[2],command_body(w))
    listed=[x for x in w.ops.commands(w.staff[1])['commands'] if x['id']==item['command_id']][0]
    assert listed['status']=='pending' and listed['expires']-listed['created']==15*60
    with w.core.tx() as db:db.execute('UPDATE workspace_admin_commands SET created=created-901 WHERE id=?',(item['command_id'],))
    assert [x for x in w.ops.commands(w.staff[1])['commands'] if x['id']==item['command_id']][0]['status']=='expired'
    with pytest.raises(WorkspaceConflict):
        w.ops.approve(w.staff[1],item['command_id'],{'revision':1,'reason':'Expired synthetic review','confirm':'APPLY'})
    assert w.ops.credits.status(w.customers[0])['balance']==100


def test_self_review_only_for_a_sole_superadmin_with_fresh_login(operations):
    w=operations;body={'revision':1,'reason':'Explicit single administrator review','confirm':'APPLY','allow_self_review':True}
    with w.core.tx() as db:
        db.execute('UPDATE admin_sessions SET created_at=? WHERE user_id=1',(time.time(),))
        assert db.execute("SELECT COUNT(*) FROM admin_users WHERE role='superadmin' AND active=1").fetchone()[0]==2
    item=w.ops.command(w.staff[1],command_body(w))
    with pytest.raises(WorkspaceDenied):w.ops.approve(w.staff[1],item['command_id'],body)
    with w.core.tx() as db:db.execute("UPDATE admin_users SET active=0 WHERE id=5")
    result=w.ops.approve(w.staff[1],item['command_id'],body)
    assert result['status']=='applied' and result['same_person_review']
    assert w.ops.credits.status(w.customers[0])['balance']==102
    assert any(row['action']=='command.apply.single_approver' for row in w.ops.audits(w.staff[1])['audit'])


def test_operator_case_list_excludes_subject_identity_and_body(operations):
    w=operations
    created=w.ops.create_case(w.staff[2],w.customers[0].customer_id,case_body())
    listed=w.ops.cases(w.staff[3])['cases']
    assert listed and set(listed[0])=={'id','status','priority','assigned_to','revision','updated'}
    assert 'Credit question' not in json.dumps(listed)
    with pytest.raises(WorkspaceDenied):w.ops.cases(w.staff[3],w.customers[0].customer_id)
    with pytest.raises(WorkspaceDenied):w.ops.case(w.staff[3],listed[0]['id'])
