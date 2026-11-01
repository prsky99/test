"""Identity drift and publication timestamps cannot become execution evidence."""
import copy
import importlib
import json
import sqlite3
import time

import pytest

from agent_market.capability_registry import Registry
from agent_market.concierge.report_evidence import current_version_id, measured_report
from agent_market.concierge.report_projection import public_report
from agent_market.concierge.connections import gateway_agent_url
from agent_market.gateway.store import Store
from scripts.import_test_reports import resolve_reports
from tests.report_fixtures import execution_report, legacy_report_fixture
from tests.test_fast_single_recommendation import catalog


def add(store, key='weather', name='Weather'):
    rid = store.upsert_resource({'key': key, 'kind': 'mcp', 'source': 'fixture',
        'name': name, 'url': 'https://weather.example/mcp', 'description': 'Weather forecast',
        'category': 'travel_maps_weather', 'networks': []})
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy',last_ok_at=?,auth_observed=0 WHERE id=?",
                   (time.time(), rid))
    return rid


@pytest.mark.parametrize('change', [
    {'kind': 'a2a'}, {'agent_name': 'Unrelated Agent'},
    {'agent_url': 'https://unrelated.example/mcp'}, {'resource_id': True},
])
def test_store_rejects_cross_subject_report(change):
    store = Store()
    rid = add(store)
    with pytest.raises(ValueError):
        store.create_test_report({'resource_id': rid, 'kind': 'mcp', 'title': 'Wrong subject',
            'agent_name': 'Weather', 'agent_url': 'https://weather.example/mcp', **change})
    assert store.query('SELECT COUNT(*) FROM agent_test_reports')[0][0] == 0
    store._db.close()


def test_raw_import_and_identity_update_are_guarded_without_rewriting_history(tmp_path):
    path = tmp_path / 'fixture.sqlite3'
    store = Store(str(path))
    rid = add(store)
    report_id = store.create_test_report({'resource_id': rid, 'title': 'Historical', 'slug': 'history'})
    with pytest.raises(sqlite3.IntegrityError, match='report_subject_mismatch'):
        with store.tx() as db:
            db.execute("UPDATE agent_test_reports SET kind='a2a' WHERE id=?", (report_id,))
    with pytest.raises(sqlite3.IntegrityError, match='report_subject_mismatch'):
        legacy_report_fixture(store,{'resource_id':rid,'title':'Foreign','slug':'foreign',
                                     'agent_name':'Foreign Subject'})
    # Model a previously imported bad record before the new guards existed.
    with store.tx() as db:
        db.execute('DROP TRIGGER report_subject_update')
        db.execute("UPDATE agent_test_reports SET agent_name='Unrelated Agent' WHERE id=?", (report_id,))
    store._db.close()
    reopened = Store(str(path))
    report = reopened.get_test_report(report_id)
    assert report['agent_name'] == 'Unrelated Agent'
    assert public_report(report, reopened.resource(rid), reopened) is None
    reopened._db.close()


def test_publication_cannot_outrank_recorded_execution(catalog):
    store, front, _, create, now = catalog
    verified = create('Measured', grade='B', report_at=now-60)
    unmeasured = create('Published', grade='A')
    store.create_test_report({'resource_id': unmeasured, 'title': 'Just published', 'slug': 'publication',
                              'is_success': 1, 'created_at': now})
    assert front.rec.search('weather forecast')[0]['id'] == verified


def test_forged_timestamps_without_registry_execution_are_not_measured(catalog):
    store, front, _, create, now = catalog
    rid = create('Timestamp assertion')
    resource = store.resource(rid)
    assertion = {'resource_id': rid, 'title': 'Unmeasured', 'slug': 'unmeasured',
                 'executed_at': now-1, 'execution_finished_at': now-1,
                 'connection_version_id': current_version_id(resource),
                 'evidence_scope': 'execution', 'is_success': 1}
    with pytest.raises(ValueError, match='recorded evidence'):
        store.create_test_report(assertion)
    report_id = store.create_test_report({'resource_id': rid, 'title': 'Legacy', 'slug': 'legacy'})
    with store.tx() as db:
        db.execute("UPDATE agent_test_reports SET executed_at=?,execution_finished_at=?,connection_version_id=?,evidence_scope='execution' WHERE id=?",
                   (now-1, now-1, assertion['connection_version_id'], report_id))
    item = front.rec.search('weather forecast')[0]
    assert item['test_report'] is None and item['verified_working'] is False


def test_measured_report_has_current_subject_and_separate_publication_time(catalog):
    store, _, _, create, now = catalog
    rid = create('Recorded', report_at=now-100)
    report = store.get_test_report(store.query('SELECT id FROM agent_test_reports')[0][0])
    with store.tx() as db:
        db.execute('UPDATE agent_test_reports SET created_at=? WHERE id=?', (now, report['id']))
    report = store.get_test_report(report['id'])
    resource = store.resource(rid)
    assert measured_report(report, resource, store, now)
    public = public_report(report, resource, store)
    assert public['execution_verified'] and public['verification_state'] == 'current_execution'
    assert public['published_at'] == now and public['executed_at'] == now-100
    with store.tx() as db:
        db.execute('UPDATE resources SET usage_full_tools=? WHERE id=?', ('[]', rid))
    changed = store.resource(rid)
    assert not measured_report(report, changed, store, now)
    historical = public_report(report, changed, store)
    assert historical['verification_state'] == 'historical_record'
    assert not historical['execution_verified'] and historical['executed_at'] == now-100


def test_canonical_import_resolves_each_database_id_and_never_asserts_execution():
    left, right = Store(), Store()
    first = add(left)
    add(right, 'unrelated', 'Unrelated')
    second = add(right)
    assert first != second
    original = {'resource_id': first, 'subject_key': 'weather', 'kind': 'mcp', 'agent_name': 'Weather',
                'agent_url': 'https://weather.example/mcp', 'title': 'Historical report'}
    frozen = copy.deepcopy(original)
    assert resolve_reports(left._db, [original])[0]['resource_id'] == first
    assert resolve_reports(right._db, [original])[0]['resource_id'] == second
    assert original == frozen
    with pytest.raises(ValueError, match='subject_key'):
        resolve_reports(left._db, [{'resource_id': first}])
    with pytest.raises(ValueError, match='cannot assert'):
        resolve_reports(left._db, [{**original, 'evidence_scope': 'execution'}])
    left._db.close()
    right._db.close()


def test_managed_subject_needs_a_local_version_and_accepts_actual_measured_report(catalog):
    store, _, _, create, now = catalog
    rid = create('Version bound')
    with pytest.raises(ValueError, match='subject'):
        store.create_test_report({'resource_id':rid,'title':'Numeric ID only',
                                  'agent_url':gateway_agent_url(rid,'mcp')})
    report_id = execution_report(store,rid,now-1,title='Measured managed report',slug='measured-managed',
                                 agent_url=gateway_agent_url(rid,'mcp'))
    assert public_report(store.get_test_report(report_id),store.resource(rid),store)['execution_verified']


def test_warm_public_cards_and_report_filter_never_restore_unrelated_managed_report(catalog):
    from agent_market.concierge.front import get_front_explore,get_front_insights,clear_front_caches
    store, _, _, create, now = catalog
    rid = create('Bound Weather',report_at=now-1)
    report_id = store.query('SELECT id FROM agent_test_reports')[0][0]
    # Keep a legitimate measured report, stored with its gateway subject URL.
    version = current_version_id(store.resource(rid))
    with store.tx() as db:
        db.execute('UPDATE agent_test_reports SET agent_url=?,connection_version_id=? WHERE id=?',
                   (gateway_agent_url(rid,'mcp'),version,report_id))
    clear_front_caches()
    first = get_front_explore(store,'','mcp',None,False,False)
    assert first['items'][0]['report_count'] == 1 and first['items'][0]['report_grade'] == 'A'
    filtered = get_front_explore(store,'','mcp',None,False,False,has_report=True)
    assert filtered['total'] == 1
    get_front_insights(store)
    # Model a historic invalid record, without changing production guard policy.
    with store.tx() as db:
        db.execute('DROP TRIGGER report_subject_update')
        db.execute("UPDATE agent_test_reports SET agent_name='Unrelated Weather' WHERE id=?",(report_id,))
    again = get_front_explore(store,'','mcp',None,False,False)
    assert again['items'][0]['report_count'] == 0 and again['items'][0]['report_grade'] is None
    filtered = get_front_explore(store,'','mcp',None,False,False,has_report=True)
    assert filtered['items'] == [] and filtered['total'] == 0
    for protocol in get_front_insights(store)['kinds'].values():
        for featured in protocol['featured']:
            for item in featured['items']:
                assert item['report_count'] == 0 and item['report_grade'] is None


def test_verified_filter_and_lanes_require_current_actual_execution(catalog):
    from agent_market.concierge.front import get_front_explore,get_front_insights,clear_front_caches
    store, _, _, create, now = catalog
    healthy = create('Healthy legacy flag',trial_ok=1)
    measured = create('Actually measured',report_at=now-1)
    clear_front_caches()
    result = get_front_explore(store,'','mcp',None,True,False)
    assert [item['id'] for item in result['items']] == [measured]
    assert result['total'] == 1
    lanes = get_front_insights(store)['kinds']['mcp']['featured']
    assert [item['id'] for lane in lanes if lane['key']=='verified' for item in lane['items']] == [measured]
    with store.tx() as db:
        db.execute('UPDATE capability_evidence SET expires=? WHERE version_id=?',
                   (now-1,current_version_id(store.resource(measured))))
        db.execute('UPDATE capability_eligibility SET expires=? WHERE resource_id=?',(now-1,measured))
    result = get_front_explore(store,'','mcp',None,True,False)
    assert result['items'] == [] and result['total'] == 0
    lanes = get_front_insights(store)['kinds']['mcp']['featured']
    assert [item for lane in lanes if lane['key']=='verified' for item in lane['items']] == []


def test_recorded_contract_report_is_retained_without_becoming_execution(catalog):
    store,front,_,create,now=catalog
    rid=create('Contract subject')
    version=Registry(store).current(rid)
    Registry(store).record(version,scope='contract',contract_id='docs.search.v1',
                           outcome='succeeded',started=now-5,finished=now-5)
    report_id=store.create_test_report({'resource_id':rid,'title':'Contract results','slug':'contract-results',
        'connection_version_id':version['id'],'evidence_scope':'contract','executed_at':now-5,
        'execution_finished_at':now-5,'is_success':1})
    report=store.get_test_report(report_id)
    projected=public_report(report,store.resource(rid),store)
    assert projected['evidence_scope']=='contract' and not projected['execution_verified']
    assert front.rec.search('weather forecast')[0]['test_report'] is None


def test_bad_newer_imports_do_not_hide_legitimate_older_drawer_history(catalog):
    store,_,client,create,now=catalog
    rid=create('Historical subject')
    valid=store.create_test_report({'resource_id':rid,'title':'Legitimate older history',
                                  'slug':'older-history','created_at':now-100})
    for index in range(5):
        legacy_report_fixture(store,{'resource_id':rid,'title':'Newer untrusted import',
            'slug':'newer-'+str(index),'created_at':now-index})
    with store.tx() as db:
        db.execute('DROP TRIGGER report_subject_update')
        db.execute("UPDATE agent_test_reports SET agent_name='Unrelated historical subject' WHERE id!=?",(valid,))
    reports=client.get('/api/agents/'+str(rid)).json()['agent']['test_reports']
    assert [report['id'] for report in reports]==[valid]


@pytest.mark.parametrize('module', ['seed_scheduled_reports', 'seed_initial_test_reports',
    'seed_round3_reports', 'seed_round4_reports', 'seed_round5_reports', 'seed_round6_reports', 'seed_round7_reports'])
def test_retired_seeds_refuse_before_opening_any_database(module, monkeypatch):
    seed = importlib.import_module('scripts.' + module)
    monkeypatch.setattr(seed, 'Store', lambda *_: pytest.fail('Must not open a database'))
    with pytest.raises(SystemExit, match='canonical subject_key'):
        seed.main()
