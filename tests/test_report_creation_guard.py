"""A canonical agent gets one report; execution evidence remains independent."""
import itertools
import multiprocessing
import re
import sqlite3
import time
from types import SimpleNamespace

import pytest

from agent_market.capability_registry import Registry
from agent_market.concierge.connections import gateway_agent_url
from agent_market.gateway.store import Store
from agent_market.report_creation import ReportAlreadyExists, ReportSlugConflict
from tests.report_fixtures import execution_report


def add(store, key='provider', url='https://provider.example/mcp', kind='mcp'):
    return store.upsert_resource({'key':key,'kind':kind,'source':'isolated-fixture',
        'name':key,'url':url,'description':'Read public records','category':'science',
        'networks':[],'price_usdc':0})


def document(rid=None, **fields):
    return {'resource_id':rid,'title':'Recorded report','summary':'Recorded document',**fields}


@pytest.fixture
def store():
    value = Store()
    try:yield value
    finally:value._db.close()


def test_existing_agent_blocks_another_report_even_with_new_slug_payload_and_time(store):
    rid = add(store)
    first = store.create_test_report(document(rid,slug='first',created_at=time.time()-100))
    original = store.get_test_report(first)
    with pytest.raises(ReportAlreadyExists) as caught:
        store.create_test_report(document(rid,slug='new-slug',title='Completely different title',
            summary='Different authored content',input_wire={'other':True},created_at=time.time()))
    assert caught.value.report_id == first
    assert store.find_existing_test_report(resource_id=rid) == first
    assert store.get_test_report(first) == original
    assert store.query('SELECT COUNT(*) FROM agent_test_reports')[0][0] == 1


def test_canonical_provider_aliases_share_a_claim_without_name_or_id_identity(store):
    first = add(store,'first','https://PROVIDER.example:443/mcp?tenant=one')
    alias = add(store,'different-name','https://provider.example/mcp?tenant=one')
    report = store.create_test_report(document(first))
    assert store.find_existing_test_report(resource_id=alias) == report
    assert store.find_existing_test_report(kind='mcp',agent_url='HTTPS://provider.example:443/mcp?tenant=one') == report
    with pytest.raises(ReportAlreadyExists):store.create_test_report(document(alias))
    assert store.query('SELECT COUNT(*) FROM test_report_subject_claims')[0][0] == 1


@pytest.mark.parametrize('url,kind',[
    ('https://provider.example/other','mcp'),
    ('https://provider.example/mcp?tenant=two','mcp'),
    ('https://provider.example/mcp','a2a'),
    ('http://provider.example/mcp','mcp'),
])
def test_other_complete_endpoint_or_protocol_remains_a_distinct_subject(store,url,kind):
    first = add(store)
    other = add(store,'other',url,kind)
    store.create_test_report(document(first,slug='first'))
    assert store.find_existing_test_report(resource_id=other) is None
    store.create_test_report(document(other,slug='other'))
    assert store.query('SELECT COUNT(*) FROM agent_test_reports')[0][0] == 2


def test_preexisting_legacy_report_blocks_before_insert_without_backfilling_old_rows(store):
    rid = add(store)
    report = store.create_test_report(document(rid))
    with store.tx() as db:db.execute('DELETE FROM test_report_subject_claims')
    before = dict(store.query('SELECT * FROM agent_test_reports')[0])
    with pytest.raises(ReportAlreadyExists) as caught:store.create_test_report(document(rid,slug='again'))
    assert caught.value.report_id == report
    assert dict(store.query('SELECT * FROM agent_test_reports')[0]) == before
    assert store.query('SELECT COUNT(*) FROM test_report_subject_claims')[0][0] == 0


@pytest.mark.parametrize('change',[
    {'agent_url':'gateway'},
    {'kind':'a2a'},
    {'agent_url':'https://different-provider.example/mcp'},
])
def test_unproven_legacy_numeric_id_protocol_or_endpoint_drift_cannot_block_agent(store,change):
    rid = add(store)
    first = store.create_test_report(document(rid,slug='old-import'))
    values = {**change}
    if values.get('agent_url') == 'gateway':values['agent_url'] = gateway_agent_url(rid,'mcp')
    with store.tx() as db:
        db.execute('DROP TRIGGER report_subject_update')
        db.execute('DELETE FROM test_report_subject_claims')
        db.execute('UPDATE agent_test_reports SET creation_subject_key=NULL WHERE id=?',(first,))
        db.execute('UPDATE agent_test_reports SET '+','.join(key+'=?' for key in values)+' WHERE id=?',
                   (*values.values(),first))
    assert store.find_existing_test_report(resource_id=rid) is None
    current = store.create_test_report(document(rid,slug='correct-current-subject'))
    assert current != first
    assert store.query('SELECT COUNT(*) FROM agent_test_reports')[0][0] == 2


def test_current_version_bound_gateway_report_blocks_its_proven_provider_subject(store):
    rid = add(store)
    version = Registry(store).current(rid)
    report = store.create_test_report(document(rid,agent_url=gateway_agent_url(rid,'mcp'),
                                               connection_version_id=version['id']))
    with store.tx() as db:db.execute('DELETE FROM test_report_subject_claims')
    assert store.find_existing_test_report(resource_id=rid) == report
    with pytest.raises(ReportAlreadyExists):store.create_test_report(document(rid))


@pytest.mark.parametrize('fields',[
    {'resource_id':True}, {'resource_id':999},
    {'kind':'mcp','agent_url':'https://agentconcierge.biz/api/gateway/mcp/999'},
    {'kind':'mcp'}, {'kind':'unsupported','agent_url':'https://provider.example/mcp'},
])
def test_incomplete_dangling_or_numeric_only_subject_is_refused(store,fields):
    with pytest.raises(ValueError):store.find_existing_test_report(**fields)
    with pytest.raises(ValueError):store.create_test_report({'title':'Invalid subject',**fields})
    assert store.query('SELECT COUNT(*) FROM agent_test_reports')[0][0] == 0


def test_unlinked_history_requires_an_explicit_protocol_and_complete_provider_endpoint(store):
    report = store.create_test_report(document(kind='mcp',agent_url='https://provider.example/mcp'))
    assert store.find_existing_test_report(kind='mcp',agent_url='https://provider.example/mcp') == report
    with pytest.raises(ReportAlreadyExists):
        store.create_test_report(document(kind='mcp',agent_url='https://provider.example/mcp',slug='again'))


def test_slug_conflict_rolls_back_claim_and_is_a_safe_distinct_error(store):
    first = add(store)
    other = add(store,'other','https://other.example/mcp')
    store.create_test_report(document(first,slug='shared-slug'))
    with pytest.raises(ReportSlugConflict):store.create_test_report(document(other,slug='shared-slug'))
    assert store.find_existing_test_report(resource_id=other) is None
    assert store.query('SELECT COUNT(*) FROM test_report_subject_claims')[0][0] == 1
    store.create_test_report(document(other,slug='different-slug'))


def test_default_slugs_do_not_collide_in_the_same_second(store,monkeypatch):
    monkeypatch.setattr('agent_market.gateway.store.time.time',lambda:1700000000.0)
    for index in range(2):
        rid = add(store,str(index),'https://provider.example/'+str(index))
        store.create_test_report(document(rid))
    assert len({row['slug'] for row in store.query('SELECT slug FROM agent_test_reports')}) == 2


def _competing_writer(path,rid,barrier,queue):
    store = Store(path)
    try:
        barrier.wait(timeout=15)
        try:queue.put(('created',store.create_test_report(document(rid))))
        except ReportAlreadyExists as exc:queue.put(('existing',exc.report_id))
        except Exception as exc:queue.put(('error',type(exc).__name__))
    finally:store._db.close()


def test_independent_processes_can_create_only_one_report(tmp_path):
    path = str(tmp_path/'reports.sqlite3')
    initial = Store(path)
    rid = add(initial)
    initial._db.close()
    context = multiprocessing.get_context('spawn')
    barrier,queue = context.Barrier(2),context.Queue()
    workers = [context.Process(target=_competing_writer,args=(path,rid,barrier,queue)) for _ in range(2)]
    try:
        for process in workers:process.start()
        outcomes = [queue.get(timeout=25) for _ in workers]
        for process in workers:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert sorted(item[0] for item in outcomes) == ['created','existing']
        assert len({item[1] for item in outcomes}) == 1
        reopened = Store(path)
        try:
            assert reopened.query('SELECT COUNT(*) FROM agent_test_reports')[0][0] == 1
            assert reopened.query('SELECT COUNT(*) FROM test_report_subject_claims WHERE report_id IS NOT NULL')[0][0] == 1
        finally:reopened._db.close()
    finally:
        for process in workers:
            if process.is_alive():process.terminate();process.join(timeout=5)
        queue.close();queue.join_thread()


def test_new_execution_evidence_survives_without_creating_a_second_report(store):
    rid = add(store)
    with store.tx() as db:db.execute("UPDATE resources SET health_status='healthy',auth_observed=0 WHERE id=?",(rid,))
    started = time.time()-10
    report = execution_report(store,rid,started,title='First measured record')
    assert store.get_test_report(report)['execution_measured'] is True
    version = Registry(store).current(rid)
    Registry(store).record(version,scope='execution',outcome='succeeded',started=started+1,finished=started+1)
    with pytest.raises(ReportAlreadyExists):
        store.create_test_report(document(rid,executed_at=started+1,execution_finished_at=started+1,
            connection_version_id=version['id'],evidence_scope='execution',is_success=1))
    assert store.query('SELECT COUNT(*) FROM capability_evidence')[0][0] == 2
    assert store.query('SELECT COUNT(*) FROM agent_test_reports')[0][0] == 1
    listed,total = store.list_test_reports()
    assert total == 1 and listed[0]['execution_measured'] is False
    assert listed[0]['executed_at'] == started


@pytest.mark.parametrize('replace',[False,True])
def test_raw_insert_and_replace_without_pending_claim_are_refused_without_row_changes(store,replace):
    rid = add(store)
    report_id = store.create_test_report(document(rid,slug='original'))
    original = dict(store.query('SELECT * FROM agent_test_reports')[0])
    raw = {**original,'slug':'raw-replacement'}
    if not replace:raw.update(id=None,creation_subject_key=None)
    with pytest.raises(sqlite3.IntegrityError,match='report_creation_reservation_required'):
        with store.tx() as db:
            db.execute(('INSERT OR REPLACE' if replace else 'INSERT')+
                ' INTO agent_test_reports ('+','.join(raw)+') VALUES ('+
                ','.join('?' for _ in raw)+')',tuple(raw.values()))
    assert dict(store.query('SELECT * FROM agent_test_reports')[0]) == original
    assert store.get_test_report(report_id)['slug'] == 'original'


def test_existing_duplicate_history_survives_startup_and_blocks_new_creation(tmp_path):
    from tests.report_fixtures import legacy_report_fixture
    path = str(tmp_path/'existing.sqlite3')
    old = Store(path)
    rid = add(old)
    for index in range(2):legacy_report_fixture(old,document(rid,slug='old-'+str(index)))
    original = [dict(r) for r in old.query('SELECT * FROM agent_test_reports ORDER BY id')]
    old._db.close()
    reopened = Store(path)
    try:
        assert [dict(r) for r in reopened.query('SELECT * FROM agent_test_reports ORDER BY id')] == original
        with pytest.raises(ReportAlreadyExists):reopened.create_test_report(document(rid))
        assert reopened.query('SELECT COUNT(*) FROM agent_test_reports')[0][0] == 2
    finally:reopened._db.close()


@pytest.mark.parametrize('alter',['valid','missing','disabled','body'])
def test_native_guard_attachment_refuses_missing_or_changed_reservation_enforcement(alter):
    from agent_market.application_store_postgres import (
        ApplicationStoreError,PostgresApplicationStore,_invariant_ddl,_CATALOG,
    )
    functions = {re.match(r'CREATE FUNCTION ([a-z_]+)',sql)[1]:sql.split('$$')[1]
                 for sql in _invariant_ddl() if sql.startswith('CREATE FUNCTION')}
    definitions = [('application_catalog_epoch','resources_fts',28),
        ('application_observation_generation','resources',21),
        ('application_vector_enqueue','vec_outbox',21),
        ('application_vector_invalidate','resources',29),
        ('application_report_creation','agent_test_reports',7)]
    rows = [(name,table,event,'O',name,functions[name],False,'v',None,'plpgsql',0,True,'',False,False,'public')
            for name,table,event in definitions]
    if alter == 'missing':rows.pop()
    elif alter == 'disabled':rows[-1] = (*rows[-1][:3],'D',*rows[-1][4:])
    elif alter == 'body':rows[-1] = (*rows[-1][:5],'BEGIN RETURN NEW; END',*rows[-1][6:])
    native = PostgresApplicationStore.__new__(PostgresApplicationStore)
    native._execute = lambda sql, params=():SimpleNamespace(fetchone=lambda:('origin',),fetchall=lambda:rows)
    if alter == 'valid':native._validate_native_invariants()
    else:
        with pytest.raises(ApplicationStoreError,match='schema_invariants_mismatch'):
            native._validate_native_invariants()
    assert 'NEW.creation_subject_key IS NULL' in functions['application_report_creation']
    assert 'report_id IS NULL' in functions['application_report_creation']
    schema = next(sql for sql in _CATALOG['schema'] if sql.startswith('CREATE TABLE IF NOT EXISTS "test_report_subject_claims"'))
    assert 'FOREIGN KEY(report_id) REFERENCES agent_test_reports(id)' in schema
    assert not any('report_creation_insert' in item['sqlite'] for item in _CATALOG['statements'])


def test_all_creation_and_admin_list_sql_variants_remain_registered(store,monkeypatch):
    from agent_market.application_store_postgres import _STATEMENTS,_normalized
    observed = []
    original = store.query
    def capture(sql,params=()):
        observed.append(sql)
        return original(sql,params)
    monkeypatch.setattr(store,'query',capture)
    rid = add(store)
    store.create_test_report(document(rid))
    store.find_existing_test_report(resource_id=rid)
    for flags in itertools.product((False,True),repeat=6):
        values = ('mcp','science','A',1,'recorded','recorded')
        fields = ('kind','category','grade','is_success','tag','q')
        store.list_test_reports(**{key:value for key,value,enabled in zip(fields,values,flags) if enabled})
    assert not {sql for sql in observed if _normalized(sql) not in _STATEMENTS}
