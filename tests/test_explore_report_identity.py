"""Report history filters validate identity before ranking, totals and pagination."""
import itertools
import json
import sqlite3
from unittest.mock import Mock
import pytest

from agent_market.concierge.connections import gateway_agent_url
from agent_market.concierge.front import clear_front_caches
from tests.test_fast_single_recommendation import catalog
from tests.report_fixtures import legacy_report_fixture


def history(store, rid, *, created_at, slug=None):
    return legacy_report_fixture(store,{'resource_id':rid,'title':'Recorded historical report',
        'slug':slug or 'history-'+str(rid),'created_at':created_at,
        'eval_grade':'A','eval_score':99,'is_success':1})


def legacy_change(store, report_id, **fields):
    """Model pre-guard imports only in this test's isolated database."""
    with store.tx() as db:
        db.execute('DROP TRIGGER IF EXISTS report_subject_update')
        db.execute('UPDATE agent_test_reports SET '+','.join(key+'=?' for key in fields)+' WHERE id=?',
                   (*fields.values(),report_id))


def explore(client, **params):
    response = client.get('/api/explore',params={'has_report':'true',**params})
    assert response.status_code == 200,response.text
    return response.json()


def test_historical_report_is_visible_without_becoming_current_execution(catalog):
    store,_,client,add,now = catalog
    rid = add('Historical Weather',trial_ok=1)
    report_id = history(store,rid,created_at=now-3600)
    result = explore(client,kind='mcp',limit=1)
    assert result['total'] == 1 and result['total_is_estimate'] is False
    assert result['candidate_window_limited'] is False
    card = result['items'][0]
    assert card['id'] == rid and card['report_count'] == 1
    assert card['report_grade'] is None and card['report_score'] is None
    assert not card['connection_readiness']['verified_callable']
    detail = client.get('/api/agents/'+str(rid)).json()['agent']
    assert detail['report_count'] == 1 and detail['test_report']['id'] == report_id
    assert detail['active'] is card['active'] and detail['catalog_status'] == 'live'
    assert detail['health_status'] == card['health_status']
    assert detail['test_report']['verification_state'] == 'historical_record'
    assert detail['test_report']['execution_verified'] is False
    checked = explore(client,kind='mcp',verified='true')
    assert checked['items'] == [] and checked['total'] == 0


@pytest.mark.parametrize('fields',[
    {'active':0},
    {'health_status':'down'},
    {'health_status':'failing'},
    {'health_status':'unknown'},
    {'health_status':'retired'},
    {'active':0,'health_status':'down'},
])
def test_report_history_search_includes_unavailable_subjects_without_execution_claim(catalog,fields):
    store,_,client,add,now = catalog
    rid = add('Historical Unavailable',**fields)
    report_id = history(store,rid,created_at=now-3600)
    normal = client.get('/api/explore',params={'kind':'mcp'}).json()
    assert normal['total'] == 0 and normal['items'] == []
    result = explore(client,kind='mcp',q='weather')
    assert result['total'] == 1 and result['total_unit'] == 'agents'
    assert result['report_scope'] == 'history'
    assert result['matched_report_count'] == 1 and result['historical_agent_count'] == 1
    card = result['items'][0]
    assert card['id'] == rid and card['catalog_status'] == 'historical'
    assert card['active'] is bool(fields.get('active',1))
    assert card['health_status'] == fields.get('health_status','healthy')
    assert not card['connection_readiness']['verified_callable']
    assert card['report_grade'] is None and card['report_score'] is None
    detail = client.get('/api/agents/'+str(rid)).json()['agent']
    assert detail['report_count'] == 1 and detail['test_report']['id'] == report_id
    assert detail['active'] is card['active'] and detail['catalog_status'] == 'historical'
    assert detail['health_status'] == card['health_status']
    checked = explore(client,kind='mcp',verified='true')
    assert checked['total'] == 0 and checked['items'] == []
    assert checked['report_scope'] == 'live'


def test_report_search_counts_agents_and_records_separately_and_keeps_quarantine_private(catalog):
    store,_,client,add,now = catalog
    live = add('Live History',category='science')
    down = add('Down History',category='science',health_status='down')
    quarantined = add('Quarantined History',category='science',eval_security='quarantine')
    for index,rid in enumerate((live,live,down,quarantined)):
        history(store,rid,created_at=now-index,slug='separate-count-'+str(index))
    result = explore(client,category='science',q='weather')
    assert result['total'] == 2 and result['matched_report_count'] == 3
    assert result['historical_agent_count'] == 1
    assert {item['id'] for item in result['items']} == {live,down}
    assert {item['id']:item['report_count'] for item in result['items']} == {live:2,down:1}
    for kind in ('mcp','a2a','x402'):
        filtered = explore(client,kind=kind,category='science',q='weather')
        assert filtered['total'] == (2 if kind == 'mcp' else 0)
    assert explore(client,category='other')['total'] == 0


@pytest.mark.parametrize('search',['','weather'])
def test_health_quarantined_history_is_excluded_even_with_clear_security_grade(catalog,search):
    store,_,client,add,now = catalog
    quarantined = add('Health Quarantined History',health_status='quarantined',eval_security='ok')
    available = add('Available History',eval_security='ok')
    unavailable = add('Down History',health_status='down',eval_security='ok')
    for rid in (quarantined,available,unavailable):
        history(store,rid,created_at=now)
    for params in ({},{'kind':'mcp'}):
        result = explore(client,q=search,**params)
        assert result['total'] == 2 and result['matched_report_count'] == 2
        assert result['historical_agent_count'] == 1
        assert {item['id'] for item in result['items']} == {available,unavailable}


def test_history_rechecks_health_quarantine_after_candidate_query(catalog,monkeypatch):
    store,_,client,add,now = catalog
    rid = add('Quarantined During Read',eval_security='ok')
    history(store,rid,created_at=now)
    original = store.resource
    def changed(resource_id):
        resource = original(resource_id)
        return {**resource,'health_status':'quarantined'} if resource_id == rid else resource
    monkeypatch.setattr(store,'resource',changed)
    result = explore(client,kind='mcp')
    assert result['items'] == [] and result['total'] == 0
    assert result['matched_report_count'] == 0


def test_historical_scope_does_not_bypass_subject_identity_or_current_execution(catalog):
    store,_,client,add,now = catalog
    valid = add('Safe Historical Subject',active=0)
    history(store,valid,created_at=now)
    for index,change in enumerate(({'agent_name':'Another subject'},
                                    {'agent_url':'https://other-subject.example/api'},
                                    {'kind':'a2a'},
                                    {'agent_url':'managed','connection_version_id':None})):
        rid = add('Untrusted Historical '+str(index),active=0,health_status='down')
        report_id = history(store,rid,created_at=now)
        if change.get('agent_url') == 'managed':
            change = {**change,'agent_url':gateway_agent_url(rid,'mcp')}
        legacy_change(store,report_id,**change)
    result = explore(client,kind='mcp')
    assert result['total'] == 1 and result['matched_report_count'] == 1
    assert [item['id'] for item in result['items']] == [valid]
    assert explore(client,kind='mcp',verified='true')['total'] == 0


def test_canonical_name_and_complete_endpoint_share_card_filter_and_detail(catalog):
    store,_,client,add,now = catalog
    rid = add('Weather Canonical')
    valid = history(store,rid,created_at=now-100,slug='canonical-history')
    # Equivalent Unicode/case/spacing and a default HTTPS port are valid evidence.
    legacy_change(store,valid,agent_name='  ＷＥＡＴＨＥＲ   canonical ',
                  agent_url='HTTPS://WEATHER-CANONICAL.EXAMPLE:443/api')
    for index in range(6):
        bad = history(store,rid,created_at=now-index,slug='bad-newer-'+str(index))
        legacy_change(store,bad,agent_name='Unrelated subject')
    result = explore(client,kind='mcp')
    assert result['total'] == 1 and len(result['items']) == 1
    assert result['items'][0]['report_count'] == 1
    detail = client.get('/api/agents/'+str(rid)).json()['agent']
    assert detail['report_count'] == 1
    assert [report['id'] for report in detail['test_reports']] == [valid]


@pytest.mark.parametrize('change',[
    {'kind':'a2a'},
    {'agent_name':'Unrelated Agent'},
    {'agent_url':'https://identity-weather.example/other'},
    {'agent_url':'https://identity-weather.example/api?different=1'},
    {'agent_url':'https://unrelated.example/api'},
    {'agent_url':'https://identity-weather.example/api#fragment'},
    {'managed':True,'connection_version_id':None},
    {'managed':True,'connection_version_id':'cv_unrelated'},
])
def test_untrusted_identity_never_counts_or_leaks_through_warm_cards(catalog,change):
    store,_,client,add,now = catalog
    rid = add('Identity Weather')
    report_id = history(store,rid,created_at=now)
    clear_front_caches()
    assert client.get('/api/explore',params={'kind':'mcp'}).json()['items'][0]['report_count'] == 1
    changes = dict(change)
    if changes.pop('managed',False):changes['agent_url'] = gateway_agent_url(rid,'mcp')
    legacy_change(store,report_id,**changes)
    result = explore(client,kind='mcp')
    assert result['total'] == 0 and result['items'] == []
    assert result['total_is_estimate'] is False
    card = client.get('/api/explore',params={'kind':'mcp'}).json()['items'][0]
    assert card['report_count'] == 0 and card['report_grade'] is None
    detail = client.get('/api/agents/'+str(rid)).json()['agent']
    assert detail['report_count'] == 0 and detail['test_reports'] == []


def test_more_than_one_thousand_invalid_candidates_cannot_hide_late_history(catalog):
    store,_,client,add,now = catalog
    valid = add('Old Valid Source',first_seen=now-100)
    history(store,valid,created_at=now-100)
    for index in range(1050):
        rid = add('New Invalid '+str(index),first_seen=now+index)
        history(store,rid,created_at=now+index)
    with store.tx() as db:
        db.execute('DROP TRIGGER report_subject_update')
        db.execute("UPDATE agent_test_reports SET agent_name='Unrelated imported subject' WHERE resource_id!=?",(valid,))
    for params in ({'kind':'mcp','limit':1},{'limit':3},{'kind':'mcp','q':'weather','limit':1}):
        result = explore(client,**params)
        assert [item['id'] for item in result['items']] == [valid]
        assert result['total'] == 1 and result['total_is_estimate'] is False
        assert result['candidate_window_limited'] is False


def test_default_protocols_exclude_x402_and_count_only_valid_reports(catalog):
    store,_,client,add,now = catalog
    valid = []
    for index,kind in enumerate(('a2a','mcp','x402')):
        rid = add('Celestial '+kind,kind=kind,description='Celestial forecast instrument',first_seen=now-index)
        valid.append(rid)
        history(store,rid,created_at=now-index)
        bad = add('Invalid '+kind,kind=kind,description='Celestial forecast instrument',first_seen=now+index+1)
        bad_report = history(store,bad,created_at=now+index+1)
        legacy_change(store,bad_report,agent_name='Other provider')
    unrelated = add('Unrelated Geography',description='Geographic boundary information')
    history(store,unrelated,created_at=now+20)
    result = explore(client,q='celestial',limit=3)
    assert result['total'] == 2 and result['total_is_estimate'] is False
    assert [item['id'] for item in result['items']] == valid[:2]
    assert result['matched_report_count'] == 2
    any_scope = explore(client,q='celestial',kind='any',limit=3)
    assert [item['id'] for item in any_scope['items']] == valid[:2]
    for kind,rid in zip(('a2a','mcp','x402'),valid):
        page = explore(client,q='celestial',kind=kind,limit=1)
        assert page['total'] == 1 and page['items'][0]['id'] == rid
    assert explore(client,q='nomatchkeyword')['total'] == 0


def test_report_totals_share_category_auth_and_current_execution_predicates(catalog):
    store,_,client,add,now = catalog
    legacy = add('Historical Checked Category',category='science',auth_observed=0)
    history(store,legacy,created_at=now)
    measured = add('Measured Checked Category',category='science',report_at=now-1,auth_observed=0)
    other_category = add('Other Category',category='other',report_at=now-1)
    private = add('Authentication Required',category='science',auth_observed=1)
    history(store,private,created_at=now)
    result = explore(client,kind='mcp',category='science',no_auth='true')
    assert result['total'] == 2
    assert {item['id'] for item in result['items']} == {legacy,measured}
    checked = explore(client,kind='mcp',category='science',no_auth='true',verified='true')
    assert checked['total'] == 1 and checked['items'][0]['id'] == measured
    assert checked['total_is_estimate'] is False
    assert other_category not in {item['id'] for item in checked['items']}


def test_truncated_candidate_scan_reports_an_upper_bound_without_false_badges(catalog,monkeypatch):
    import agent_market.concierge.front as frontend
    store,_,client,add,now = catalog
    late = add('Late Weather',first_seen=now-100)
    history(store,late,created_at=now-100)
    for index in range(2):
        rid = add('Invalid Leading '+str(index),first_seen=now+index)
        report_id = history(store,rid,created_at=now+index)
        legacy_change(store,report_id,agent_name='Other provider')
    monkeypatch.setattr(frontend,'MAX_REPORT_CANDIDATES',2)
    result = explore(client,kind='mcp',limit=300)
    assert result['items'] == [] and result['total'] == 1
    assert result['total_is_estimate'] is True and result['candidate_window_limited'] is True
    assert result['matched_report_count'] is None and result['historical_agent_count'] is None


def test_drawer_report_count_includes_all_trusted_history_beyond_body_limit(catalog):
    store,_,client,add,now = catalog
    rid = add('Many Historical Reports')
    for index in range(7):history(store,rid,created_at=now-index,slug='many-'+str(index))
    result = explore(client,kind='mcp')
    assert result['total'] == 1 and result['items'][0]['report_count'] == 7
    detail = client.get('/api/agents/'+str(rid)).json()['agent']
    assert detail['report_count'] == 7 and len(detail['test_reports']) == 5


def test_every_report_filter_variant_has_an_exact_native_sql_registration(catalog,monkeypatch):
    from agent_market.application_store_postgres import _STATEMENTS,_normalized
    store,_,client,add,now = catalog
    add('Registered Weather',category='science',report_at=now-1)
    observed = []
    original = store.query
    def capture(sql,params=()):
        observed.append(sql)
        return original(sql,params)
    monkeypatch.setattr(store,'query',capture)
    for search,kind,category,checked,no_auth in itertools.product((False,True),repeat=5):
        result = explore(client,q='weather' if search else '',kind='mcp' if kind else '',
            category='science' if category else '',verified=str(checked).lower(),no_auth=str(no_auth).lower())
        assert result['total'] == 1 and len(result['items']) == 1
    assert observed
    missing = sorted({sql for sql in observed if _normalized(sql) not in _STATEMENTS})
    assert not missing,missing


def test_unfiltered_text_search_totals_match_the_same_fts_query_and_native_shapes(catalog,monkeypatch):
    from agent_market.application_store_postgres import _STATEMENTS,_normalized
    store,_,client,add,_ = catalog
    mcp = add('Celestial Reader',description='Celestial telescope records',category='science')
    a2a = add('Celestial Delegate',kind='a2a',description='Celestial telescope records',category='science')
    add('Other Reader',description='Geographic boundary information',category='other')
    observed = []
    original = store.query
    def capture(sql,params=()):
        observed.append(sql)
        return original(sql,params)
    monkeypatch.setattr(store,'query',capture)
    for params,expected in (({'q':'celestial','kind':'mcp'},{mcp}),
                            ({'q':'celestial'},{mcp,a2a}),
                            ({'q':'nomatchkeyword'},set())):
        response = client.get('/api/explore',params=params)
        assert response.status_code == 200,response.text
        result = response.json()
        assert result['total'] == len(expected)
        assert {item['id'] for item in result['items']} == expected
    assert not {sql for sql in observed if _normalized(sql) not in _STATEMENTS}


def test_report_queries_keep_membership_prefilter_and_protocol_subject_gate(catalog,monkeypatch):
    store,_,client,add,now = catalog
    rid = add('Reported Weather')
    history(store,rid,created_at=now)
    add('Unreported Weather')
    observed = []
    original = store.query
    def capture(sql,params=()):
        if 'FROM resources r WHERE' in sql:observed.append(sql)
        return original(sql,params)
    monkeypatch.setattr(store,'query',capture)
    result = explore(client,kind='mcp')
    assert result['total'] == 1 and result['items'][0]['id'] == rid
    assert observed
    assert all('r.id IN (SELECT resource_id FROM agent_test_reports WHERE resource_id IS NOT NULL)' in sql
               and 'tr.resource_id=r.id AND tr.kind=r.kind' in sql for sql in observed)


def test_native_report_fts_families_are_finite_bound_projections():
    from agent_market.application_store_postgres import _STATEMENTS
    for adapter,name in (('explore-fts5-count-v1','front.explore.report.fts.count'),
                         ('explore-fts5-page-v1','front.explore.report.fts.page')):
        items = [item for item in _STATEMENTS.values() if item.get('adapter')==adapter and item['name']==name]
        assert len(items) == 16
        assert {item['name'] for item in items} == {name}
        for item in items:
            assert item['readonly'] is True and item['generated_id'] is None
            assert item['parameter_count'] == item['sqlite'].count('?')
            assert 'resources_fts MATCH ?' in item['sqlite']
            assert 'json_array_elements(%s::json)' in item['postgres']
            assert 'strftime' not in item['postgres']
            if adapter=='explore-fts5-page-v1':
                assert item['sqlite'].endswith('LIMIT ? OFFSET ?')
                assert item['postgres'].endswith('LIMIT %s OFFSET %s')
            else:
                assert 'SELECT COUNT(*) AS c' in item['postgres'] and 'LIMIT' not in item['postgres']


@pytest.mark.parametrize('adapter,params',[
    ('explore-fts5-count-v1',('weather',)),
    ('explore-fts5-page-v1',('weather',2000,1000)),
])
def test_native_report_fts_adapter_preserves_bound_page_or_count_parameters(adapter,params):
    from agent_market.application_store_postgres import PostgresApplicationStore,_STATEMENTS
    store = PostgresApplicationStore.__new__(PostgresApplicationStore)
    corpus = sqlite3.connect(':memory:')
    corpus.execute('CREATE VIRTUAL TABLE documents USING fts5(name,description)')
    corpus.execute("INSERT INTO documents(rowid,name,description) VALUES(7,'Weather','Forecast')")
    store._fts = lambda:corpus
    store._execute = Mock(return_value='native-result')
    item = next(item for item in _STATEMENTS.values()
                if item.get('adapter')==adapter and item['parameter_count']==len(params))
    assert store._legacy_fts_select(item,params) == 'native-result'
    statement,bound = store._execute.call_args.args
    assert statement == item['postgres'] and bound[1:] == params[1:]
    matches = json.loads(bound[0])
    assert len(matches) == 1 and matches[0][0] == 7 and isinstance(matches[0][1],float)
    corpus.close()


@pytest.mark.parametrize('params',[
    ('weather',0,0),('weather',2001,0),('weather',True,0),
    ('weather',1,-1),('weather',1,10001),('weather',1,True),
    ('x'*4097,1,0),('weather',1),
])
def test_native_report_fts_invalid_paging_fails_before_corpus_or_database(params):
    from agent_market.application_store_postgres import ApplicationStoreError,PostgresApplicationStore,_STATEMENTS
    store = PostgresApplicationStore.__new__(PostgresApplicationStore)
    store._fts = Mock(side_effect=AssertionError('Invalid parameters must not read the corpus'))
    store._execute = Mock(side_effect=AssertionError('Invalid parameters must not execute SQL'))
    item = next(item for item in _STATEMENTS.values()
                if item.get('adapter')=='explore-fts5-page-v1' and item['parameter_count']==3)
    with pytest.raises(ApplicationStoreError,match='invalid_parameters'):
        store._legacy_fts_select(item,params)
    assert not store._fts.called and not store._execute.called


def test_combined_protocol_report_counts_sum_known_values_and_preserve_unknown():
    from agent_market.concierge.protocols import merge_discovery_results
    first={'items':[],'total':0,'matched_report_count':0,'historical_agent_count':0,'candidate_window_limited':False}
    second={'items':[],'total':2,'matched_report_count':3,'historical_agent_count':1,'candidate_window_limited':False}
    merged=merge_discovery_results([first,second],45)
    assert merged['total']==2 and merged['matched_report_count']==3 and merged['historical_agent_count']==1
    unknown={**second,'matched_report_count':None,'historical_agent_count':None,'candidate_window_limited':True,'total_is_estimate':True}
    merged=merge_discovery_results([first,unknown],45)
    assert merged['matched_report_count']is None and merged['historical_agent_count']is None
    assert merged['candidate_window_limited']and merged['total_is_estimate']

