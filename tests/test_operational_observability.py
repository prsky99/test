"""Reconcile logical operations, provider attempts, privacy and admin boundaries."""
import asyncio
import json
import sqlite3
import threading
import time
from unittest.mock import Mock

import pytest

from agent_market.gateway.store import Store
from agent_market.observability import journal_for, snapshot, stable_reference, attempt_scope, provider_dispatch
from tests.test_fast_single_recommendation import catalog, ask
from tests.test_managed_agent_gateway import managed, rpc
from tests.test_gateway_execution_regression import news
from tests.test_admin_security_audit import admin, H, login, session_headers
from tests.test_visitor_desk import desk, register
from tests.test_task_updates_security import updates


def view(store):
    with store._lock:return snapshot(store._db)


def test_logical_identity_and_event_replay_are_idempotent(catalog):
    store,*_=catalog;journal=journal_for(store)
    op=journal.begin('execution','testbench');attempt=op.attempt(7,'mcp')
    with attempt_scope(attempt):
        provider_dispatch();provider_dispatch()
        attempt.finish('succeeded',transport=True,valid=True)
        attempt.finish('succeeded',transport=True,valid=True)
    op.finish('succeeded');op.finish('succeeded')
    same=journal.begin('execution','testbench',identity=op.id)
    assert same.id==op.id
    result=view(store)
    assert result['counts']['execution']=={'succeeded':1}
    assert result['attempt_counts']=={'prepared':1,'dispatched':1,'unknown_count':0}
    assert [e['event'] for e in result['operations'][0]['events']]==[
        'operation.started','attempt.started','attempt.dispatched','attempt.finished','operation.finished']
    assert same.attempt().id is None


def test_unknown_is_not_rewritten_by_late_success(catalog):
    store,*_=catalog;op=journal_for(store).begin('execution','managed');attempt=op.attempt(9,'a2a')
    attempt.dispatch();op.finish('timed_out','UPSTREAM_TIMEOUT')
    attempt.finish('succeeded',transport=True,valid=True);op.finish('succeeded')
    row=view(store)['operations'][0]
    assert row['status']=='unknown' and row['attempts'][0]['status']=='unknown'
    assert row['events'][-1]['event']=='attempt.late_result'
    assert sum(e['event']=='operation.finished' for e in row['events'])==1


def test_no_dispatch_timeout_is_not_an_uncertain_provider_call(catalog):
    store,*_=catalog;op=journal_for(store).begin('execution','managed');op.attempt(9,'mcp')
    op.finish('timed_out','UPSTREAM_TIMEOUT')
    row=view(store)['operations'][0]
    assert row['status']=='timed_out' and row['attempts'][0]['dispatched'] is None


def test_late_managed_worker_is_detached_from_request_storage(managed,monkeypatch):
    store,front,_,_,rid,_,_=managed
    release=threading.Event();done=threading.Event()
    def late(resource,*args):
        provider_dispatch();release.wait(2)
        # An abandoned worker cannot start a second provider call or touch DB.
        with pytest.raises(ValueError):provider_dispatch()
        done.set()
        return front.managed_gateway.result(resource,True,True,'completed',{'result':'Late output'})
    monkeypatch.setattr(front.managed_gateway,'_execute',late)
    result=asyncio.run(front.managed_gateway.execute(rid,tool='get_weather',arguments={'city':'Tokyo'},timeout=.03))
    assert result['task_status']=='timeout'
    assert view(store)['operations'][0]['status']=='unknown'
    journal=journal_for(store)
    monkeypatch.setattr(journal,'_write',lambda action:pytest.fail('A detached worker cannot access request storage.'))
    release.set();assert done.wait(2)


def test_same_delivery_retry_is_one_operation_two_attempts(catalog):
    store,*_=catalog;journal=journal_for(store);identity=stable_reference('delivery','internal-event')
    op=journal.begin('delivery','task_delivery',identity=identity)
    a=op.attempt();a.dispatch();a.finish('failed','UPSTREAM_NETWORK');op.finish('pending','UPSTREAM_NETWORK')
    replay=journal.begin('delivery','task_delivery',identity=identity)
    a=replay.attempt();a.dispatch();a.finish('accepted');replay.finish('accepted')
    result=view(store)
    assert result['counts']['delivery']=={'accepted':1}
    assert result['attempt_counts']=={'prepared':2,'dispatched':2,'unknown_count':1}
    assert 'not recipient receipt' in result['limits'][2]


def test_context_is_restored_and_plain_trace_headers_cannot_pick_identity(managed):
    store,front,client,_,rid,_,_=managed
    spoof='ex_'+'a'*24
    response=client.post('/api/test/execute',headers={'X-Execution-Reference':spoof,'X-Request-ID':spoof},
                         json={'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}})
    assert response.json()['execution_succeeded']
    assert response.json()['correlation_id']!=spoof
    row=view(store)['operations'][0]
    assert row['id']==response.json()['correlation_id'] and row['source']=='testbench'
    assert len(row['attempts'])==1 and row['attempts'][0]['dispatched']
    assert view(store)['counts']['execution']=={'succeeded':1}
    assert not store.query('SELECT * FROM platform_operations WHERE source=\'legacy\'')


def test_denied_request_and_format_demo_cannot_inflate_success(managed):
    store,_,client,_,rid,calls,_=managed
    client.post('/api/test/execute',json={'resource_id':rid,'tool':'delete_database','arguments':{}})
    client.post('/api/test/execute',json={'resource_id':-1,'tool':'get_current_weather','arguments':{}})
    result=view(store)
    assert result['counts']['execution']=={'denied':1}
    assert result['attempt_counts']['dispatched']==0 and not calls


def test_protocol_discovery_is_not_an_execution(managed):
    store,_,client,_,rid,_,_=managed
    for method in ('initialize','ping','tools/list'):rpc(client,f'/api/gateway/mcp/{rid}',method)
    assert view(store)['counts']['execution']=={}


def test_recommendation_search_counts_without_prompts_or_visitor_identity(catalog):
    store,_,client,add,now=catalog
    # An A2A card alone is not task evidence; the listing carries a recorded execution report.
    add(kind='a2a',report_at=now-1);client.post('/chat',json={'message':'hello'})
    ask(client,'find an a2a weather forecast agent')
    result=view(store)
    assert result['counts']['recommendation']=={'matched':1}
    raw=json.dumps(result)
    for marker in ('vt_','weather forecast agent','visitor_id','api_key','Bearer','https://'):
        assert marker not in raw
    assert result['coverage_complete'] is False


def test_saved_workflow_steps_share_one_operation_and_polling_does_not_count(news):
    store,front,client,rid,wid,_,_=news
    handle=client.post('/api/workflows/run',json={'template_id':wid}).json()
    for _ in range(200):
        result=client.get('/api/workflows/runs/'+handle['run_id'],headers={'X-Workflow-Key':handle['run_key']}).json()
        if result['status'] in ('succeeded','failed'):break
        time.sleep(.01)
    assert result['status']=='succeeded'
    report=view(store)
    rows=[op for op in report['operations'] if op['kind']=='workflow']
    assert len(rows)==1 and rows[0]['status']=='succeeded'
    assert len(rows[0]['attempts'])==2 and all(a['dispatched'] for a in rows[0]['attempts'])
    assert report['counts']['execution']=={}
    assert handle['run_key'] not in json.dumps(report) and handle['run_id'] not in json.dumps(report)


def test_notification_sender_records_acceptance_without_contact_or_permission_data(desk):
    store,front,_,add,_,courier,_,vid,_=desk
    wid=register(desk);add('Recent Weather',report_at=time.time())
    p=front.updates.preview(vid,wid,'reviewer')
    assert front.updates.process_preview(vid,wid,'reviewer',p['preview_token'])['sent']==1
    result=view(store)
    assert result['counts']['delivery']=={'accepted':1}
    assert len(courier.events)==1
    for private in (vid,wid,'inbox.example','private-routing-secret',p['preview_token']):
        assert private not in json.dumps(result)


def test_journal_is_shared_by_independent_connections_and_survives_reopen(tmp_path):
    path=tmp_path/'shared.sqlite3';one=Store(str(path));two=Store(str(path))
    op=journal_for(one).begin('execution','managed');a=op.attempt(7,'mcp');a.dispatch();a.finish('succeeded');op.finish('succeeded')
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        assert snapshot(db)['operations'][0]['id']==op.id
    assert view(two)['counts']['execution']=={'succeeded':1}
    one._db.close();two._db.close()
    three=Store(str(path));assert view(three)['counts']['execution']=={'succeeded':1};three._db.close()


def test_metadata_outage_does_not_block_business_execution(managed,monkeypatch):
    store,front,client,_,rid,_,_=managed
    monkeypatch.setattr(journal_for(store),'_write',lambda action:None)
    result=client.post('/api/test/execute',json={
        'resource_id':rid,'tool':'get_weather','arguments':{'city':'Tokyo'}}).json()
    assert result['execution_succeeded'] is True
    assert view(store)['counts']['execution']=={}
    assert view(store)['coverage_complete'] is False


def test_additive_schema_and_online_backup_restore_preserve_catalog(tmp_path):
    source=Store(str(tmp_path/'source.sqlite3'))
    with source.tx() as db:db.execute("INSERT INTO meta VALUES('restore-marker','catalog-preserved')")
    op=journal_for(source).begin('execution','managed');op.finish('denied','POLICY_DENIED')
    journal_for(source)
    restored_path=tmp_path/'restored.sqlite3'
    with sqlite3.connect(restored_path) as target:
        with source._lock:source._db.backup(target)
    source._db.close()
    restored=Store(str(restored_path));journal_for(restored)
    assert restored.query("SELECT value FROM meta WHERE key='restore-marker'")[0][0]=='catalog-preserved'
    assert view(restored)['counts']['execution']=={'denied':1}
    assert restored.query('PRAGMA integrity_check')[0][0]=='ok'
    restored._db.close()


def test_journal_does_not_commit_callers_business_transaction(catalog):
    store,*_=catalog;journal=journal_for(store)
    with store._lock:
        store._db.execute('BEGIN IMMEDIATE')
        store._db.execute("INSERT INTO meta VALUES('uncommitted-business','{}')")
        assert journal.begin('execution','managed').id is None
        store._db.rollback()
    assert not store.query("SELECT * FROM meta WHERE key='uncommitted-business'")


def test_unfinished_old_observation_is_unknown_without_mutating_runtime(catalog):
    store,*_=catalog;op=journal_for(store).begin('execution','managed');a=op.attempt(7,'mcp');a.dispatch()
    with store.tx() as db:db.execute('UPDATE platform_operations SET created=? WHERE id=?',(time.time()-180,op.id))
    result=view(store)
    assert result['counts']['execution']=={'unknown':1}
    assert result['operations'][0]['observation_stale']
    assert result['operations'][0]['attempts'][0]['status']=='unknown'
    assert result['attempt_counts']['unknown_count']==1
    assert store.query('SELECT status FROM platform_operations WHERE id=?',(op.id,))[0][0]=='running'


def test_busy_recording_is_bounded_and_restores_business_timeout(tmp_path):
    path=tmp_path/'busy.sqlite3';store=Store(str(path));journal=journal_for(store)
    other=sqlite3.connect(path);other.execute('BEGIN IMMEDIATE')
    original=store._db.execute('PRAGMA busy_timeout').fetchone()[0]
    started=time.monotonic()
    assert journal.begin('execution','managed').id is None
    assert time.monotonic()-started<.4
    assert store._db.execute('PRAGMA busy_timeout').fetchone()[0]==original
    assert journal.write_failures
    other.rollback();other.close();store._db.close()


def test_file_journal_finishes_while_catalog_reader_holds_store_lock(tmp_path):
    store=Store(str(tmp_path/'reader-contention.sqlite3'));journal=journal_for(store)
    op=journal.begin('execution','managed');a=op.attempt(7,'mcp');a.dispatch()
    held=threading.Event();release=threading.Event()
    def reader():
        with store._lock:
            store._db.execute('SELECT COUNT(*) FROM resources').fetchone()
            held.set();release.wait(2)
    thread=threading.Thread(target=reader);thread.start();assert held.wait(1)
    try:
        a.finish('succeeded');op.finish('succeeded')
    finally:
        release.set();thread.join(2)
    assert view(store)['counts']['execution']=={'succeeded':1}
    store._db.close()


def test_retention_removes_related_metadata_but_not_catalog(catalog,monkeypatch):
    import agent_market.observability as obs
    store,_,_,add,_=catalog;rid=add();journal=journal_for(store)
    op=journal.begin('execution','managed');a=op.attempt(rid,'mcp');a.dispatch();a.finish('succeeded');op.finish('succeeded')
    with store.tx() as db:db.execute('UPDATE platform_operations SET created=?',(time.time()-8*86400,))
    journal.begin('execution','managed')
    assert not store.query('SELECT * FROM platform_attempts WHERE operation_id=?',(op.id,))
    assert not store.query('SELECT * FROM platform_observation_events WHERE operation_id=?',(op.id,))
    assert store.resource(rid)


def test_diagnostics_require_authenticated_superadmin_and_valid_filters(admin):
    store,client=admin
    op=journal_for(store).begin('execution','managed');op.finish('denied','POLICY_DENIED')
    assert client.get('/admin/api/observations').status_code in (401,403)
    assert client.get('/admin/api/observations',headers={'X-Dashboard':'1'}).status_code==401
    with store.tx() as db:
        from agent_market.gateway import admin_auth
        admin_auth.create_admin_user(db,'viewer','viewer-password-123','Viewer','operator')
    token=login(client,'viewer','viewer-password-123').json()['token']
    assert client.get('/admin/api/observations',headers=session_headers(token)).status_code==403
    r=client.get('/admin/api/observations',headers=H,params={'reference':op.id})
    assert r.status_code==200 and r.json()['operations'][0]['id']==op.id
    assert r.headers['cache-control']=='no-store'
    for params in ({'hours':0},{'hours':169},{'limit':500},{'reference':"' OR 1=1 --"}):
        assert client.get('/admin/api/observations',headers=H,params=params).status_code==422
