"""Current Chat/URL projection parity on owned SQLite and Unix PostgreSQL only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster

PROFILE = 'application-selection-postgres-contracts-v1'


def _contracts(connect):
    from agent_market.application_store_postgres import ApplicationStoreError
    from agent_market.gateway.store import Store
    from agent_market.storage_adapter import open_store
    from agent_market.concierge.selection import QualityRecommender, search_terms
    from agent_market.concierge.front import Front, create_front_app, find_existing_agent
    from fastapi.testclient import TestClient
    from tests.report_fixtures import execution_report, legacy_report_fixture
    connection = connect(); native = open_store('postgresql', connection=connection, initialize=True, workflow_key=b's'*32)
    sqlite = Store(); stores = (native, sqlite); checks = {}; now = time.time()
    def require(value, name):
        if not value: raise AssertionError(name)
        checks[name] = True
    def normalized(value):
        if type(value) is dict:return {key:normalized(item) for key,item in value.items() if key!='agent_ref'}
        if type(value) is list:return [normalized(item) for item in value]
        return value
    def equal(name, values):
        left, right = normalized(values[0]), normalized(values[1])
        if left != right:
            ids = lambda value: [item.get('id') for item in value] if isinstance(value, list) and all(isinstance(i, dict) for i in value) else value
            diff = [key for key in (left[0] if left and isinstance(left[0], dict) else {}) if right and isinstance(right[0], dict) and left[0].get(key) != right[0].get(key)] if isinstance(left, list) else []
            detail = {key: (left[0].get(key), right[0].get(key)) for key in diff[:3]} if diff else {}
            raise AssertionError(f'{name} native={ids(left)} sqlite={ids(right)} differing_fields={diff[:12]} detail={str(detail)[:600]}')
        checks[name] = True
    def write(store, sql, parameters):
        with store.tx() as db:
            if store is native: store._execute(sql.replace('?', '%s'), parameters)
            else: db.execute(sql, parameters)
    def history(data):
        """Model retained pre-guard rows only inside this owned test cluster."""
        report_id=legacy_report_fixture(sqlite,data)
        row=dict(sqlite.query('SELECT * FROM agent_test_reports WHERE id=?',(report_id,))[0])
        row.pop('id')
        if row['connection_version_id']:
            from agent_market.capability_registry import Registry
            row['connection_version_id']=Registry(native).current(row['resource_id'])['id']
        # No production API gains a duplicate-report bypass. Restore the guard
        # in the same transaction before the next native invariant check.
        with native.tx():
            native._native('ALTER TABLE agent_test_reports DISABLE TRIGGER application_report_creation').close()
            try:
                columns=','.join(row)
                cursor=native._native('INSERT INTO agent_test_reports ('+columns+') VALUES ('+
                    ','.join('%s' for _ in row)+') RETURNING id',tuple(row.values()))
                try:require(cursor.fetchone()[0]==report_id,'historical_report_id:'+str(report_id))
                finally:cursor.close()
            finally:
                native._native('ALTER TABLE agent_test_reports ENABLE TRIGGER application_report_creation').close()
    def measured_history(rid,at,**fields):
        from agent_market.capability_registry import Registry
        for store in stores:
            registry=Registry(store);version=registry.current(rid)
            registry.record(version,scope='execution',outcome='succeeded' if fields.get('is_success',1) else 'failed',started=at,finished=at)
        resource=sqlite.resource(rid);version=Registry(sqlite).current(resource)
        history({'resource_id':rid,'kind':resource['kind'],'agent_name':resource['name'],
            'agent_url':resource['url'],'executed_at':at,'execution_finished_at':at,
            'connection_version_id':version['id'],'evidence_scope':'execution',**fields})
    def add(name, kind='a2a', age=100, grade='A', security='ok', success=1, active=1, url=None, created=None, auth=0):
        ids = []
        for store in stores:
            rid = store.upsert_resource({'key':'synthetic-selection:'+name,'source':'synthetic-selection','kind':kind,
                'url':url or 'https://agent-'+str(len(ids))+'.example/'+name.replace(' ','-').replace("'",'%27'),
                'name':name,'description':'Stock news financial market headlines and equity research',
                'category':'finance_crypto','networks':[],'price_usdc':9000000 if kind=='x402' else 0,'details':{}}, now=now-1000)
            # URLs are identical across the two persistent backends.
            if url is None: write(store, 'UPDATE resources SET url=? WHERE id=?',
                ('https://agents.example/'+name.replace(' ','-').replace("'",'%27'), rid))
            write(store, '''UPDATE resources SET eval_grade=?,eval_score=95,eval_at=?,health_status='healthy',
                last_ok_at=?,auth_observed=?,eval_security=?,active=?,usage_guide=? WHERE id=?''',
                (grade,now-1000,now-2,auth,security,active,json.dumps({'tools':[{'name':'stock_news','description':'Stock market news',
                    'inputSchema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}}]}),rid))
            report = {'title':name,'slug':'synthetic-'+str(rid),'eval_grade':grade,'eval_score':95,
                'is_success':success,'status_code':200 if success else 500,
                'created_at':now-age if created is None else created}
            if created is None:
                execution_report(store, rid, now-age, **report)
            elif store is sqlite:
                # Preserve intentionally old numeric/Julian metadata through the
                # owned history fixture, never weaken the current creation API.
                history({'resource_id':rid, **report})
            ids.append(rid)
        equal('fixture_id:'+name, ids)
        return ids[0]
    try:
        older = add('Older Stock News', age=3600)
        newest = add("Recent Stock O'Reilly News", age=30, grade='B', auth=1)
        mcp = add('Recent MCP Stock News', kind='mcp', age=10, grade='B')
        x402 = add('Latest x402 Stock News', kind='x402', age=1)
        add('Quarantined Stock News', age=0, security='quarantine')
        add('Review Stock News', age=0, security='review')
        add('Failed Stock News', age=0, success=0)
        add('Inactive Stock News', age=0, active=0)
        add('Private Stock News', age=0, url='http://127.0.0.1/internal')
        add('Unicode caf\u00e9 Stock News', age=90)
        # Exercise exact SQLite strftime/CAST rules for numeric and
        # Julian-date values; future-invalid metadata must not outrank current work.
        add('Historic Stock News', created=946728000)
        add('Julian Stock News', created='2451545')
        add('Numeric String Stock News', created=str(now-120))
        from agent_market.capability_registry import Registry
        for store in stores: Registry(store)
        recommenders = [QualityRecommender(store) for store in stores]
        for kind in (None, 'a2a', 'mcp', 'x402'):
            for task in ('stock news', "stock O'Reilly news", 'caf\u00e9 stock news', '"stock" news'):
                equal('selection_parity:'+str((kind,task)), [rec.search(task,kind=kind) for rec in recommenders])
        require(recommenders[0].search('stock news',kind='a2a')[0]['id'] == newest, 'recent_verification_precedes_grade_and_auth')
        require(recommenders[0].search('stock news',kind='mcp')[0]['id'] == mcp, 'explicit_mcp_keeps_protocol_gate')
        for mode in (None,'auto','any'):
            selected=recommenders[0].search('stock news',kind=mode,limit=3)
            require(selected[0]['id']==newest and all(item['kind']!='x402' for item in selected),
                    'automatic_any_prefer_a2a_then_mcp:'+str(mode))
        require(recommenders[0].search('stock news',kind='x402')[0]['id']==x402, 'explicit_x402_remains_available')
        # A URL-only legacy publication cannot promote itself to execution proof.
        history({'title':'URL-linked newest','slug':'synthetic-url-linked','kind':'a2a',
                'agent_url':sqlite.resource(older)['url'],'eval_grade':'A','eval_score':99,'is_success':1,
                'status_code':200,'created_at':now-1})
        equal('url_linked_latest_report_parity', [rec.search('stock news',kind='a2a') for rec in recommenders])
        require(recommenders[0].search('stock news',kind='a2a')[0]['id'] == newest,
            'url_only_legacy_publication_cannot_change_verified_winner')
        # A separately recorded current execution, bound to the exact subject
        # and immutable version, can change that winner on both backends.
        measured_history(older, now-1, title='Current subject-bound execution',
                slug='synthetic-current-execution', eval_grade='A', eval_score=99,
                is_success=1, status_code=200, created_at=now-1)
        equal('current_subject_bound_execution_report_parity', [rec.search('stock news',kind='a2a') for rec in recommenders])
        require(recommenders[0].search('stock news',kind='a2a')[0]['id'] == older,
            'fresh_subject_bound_execution_report_changes_winner')
        # Metadata is refreshed per request even if no FTS document changed.
        measured_history(older, now, title='New failure', slug='synthetic-latest-failure',
                eval_grade='A',eval_score=99,is_success=0,status_code=503,created_at=now)
        equal('new_report_without_fts_change_invalidates_winner', [rec.search('stock news',kind='a2a') for rec in recommenders])
        require(recommenders[0].search('stock news',kind='a2a')[0]['id'] == newest, 'latest_failure_cannot_remain_recommended')
        # Actual current /chat applies its default protocol before local selection.
        for store in stores:
            front = Front(store, llm=Mock(side_effect=AssertionError('No model call')), public_url='https://agentconcierge.biz')
            with TestClient(create_front_app(front), base_url='https://agentconcierge.biz') as client:
                body = client.post('/chat', json={'message':'stock news'}).json()
                require(body['data']['protocol'] is None and body['data']['recommendations'][0]['id'] == newest,
                    'actual_chat_default_a2a:'+store.backend if hasattr(store,'backend') else 'actual_chat_default_a2a:sqlite')
                body = client.post('/chat', json={'message':'mcp stock news'}).json()
                require(body['data']['protocol'] == 'mcp' and body['data']['recommendations'][0]['id'] == mcp,
                    'actual_chat_explicit_mcp:'+store.backend if hasattr(store,'backend') else 'actual_chat_explicit_mcp:sqlite')
        # Current duplicate detection preserves slash, A2A well-known, explicit
        # card URL, apostrophe and Unicode path variants without SQL fragments.
        variants = [('https://dedupe.example/agent', 'a2a'), ("https://dedupe.example/quoted'caf\u00e9", 'mcp')]
        for index,(url,kind) in enumerate(variants):
            for store in stores:
                store.upsert_resource({'key':kind+':'+url,'source':'synthetic-dedupe','kind':kind,'url':url,
                    'name':'Duplicate boundary','description':'Public registry duplicate','category':'dev_tools','networks':[],'details':{}})
            for raw in (url,url+'/',url+'/.well-known/agent-card.json' if kind=='a2a' else url):
                equal('url_dedupe:'+str((index,raw)), [find_existing_agent(store,raw,kind) for store in stores])
        # These evidence changes do not mutate the FTS text or cache epoch.
        for store in stores:
            registry = Registry(store); version = registry.current(store.resource(newest))
            registry.record(version,scope='execution',outcome='failed',started=now-1,finished=now)
        equal('current_execution_failure_without_fts_change', [rec.search('stock news',kind='a2a') for rec in recommenders])
        require(recommenders[0].search('stock news',kind='a2a')[0]['id'] != newest,
            'latest_execution_failure_changes_current_winner')
        for store in stores:
            registry = Registry(store); version = registry.current(store.resource(newest))
            registry.record(version,scope='execution',outcome='succeeded',started=now,finished=now+1)
        equal('current_execution_recovery_without_fts_change', [rec.search('stock news',kind='a2a') for rec in recommenders])
        for store in stores:
            base = 'https://active-duplicate.example/agent'
            inactive_id = store.upsert_resource({'key':'a2a:'+base,'source':'synthetic-dedupe','kind':'a2a','url':base,
                'name':'Inactive exact','description':'Registry duplicate','category':'dev_tools','networks':[],'details':{}})
            active_id = store.upsert_resource({'key':'a2a:'+base+'/.well-known/agent-card.json','source':'synthetic-dedupe',
                'kind':'a2a','url':base+'/.well-known/agent-card.json','name':'Active card','description':'Registry duplicate',
                'category':'dev_tools','networks':[],'details':{}})
            write(store,'UPDATE resources SET active=0 WHERE id=?',(inactive_id,))
        equal('url_duplicate_active_precedes_inactive_exact', [find_existing_agent(store,base,'a2a') for store in stores])
        require(find_existing_agent(native,base,'a2a')['id']==active_id,'active_card_variant_wins_duplicate_order')
        equal('explicit_card_url_duplicate_parity', [find_existing_agent(store,'https://new-endpoint.example/api','a2a',base+'/.well-known/agent-card.json') for store in stores])
        # The global default query bound must not truncate a newer candidate.
        for store in stores:
            with store.tx():
                for number in range(2005):
                    last = store.upsert_resource({'key':'synthetic-bulk:'+str(number),'source':'synthetic-selection-bulk',
                        'kind':'a2a','url':'https://bulk-'+str(number)+'.example/agent','name':'Chronology documentation '+str(number),
                        'description':'Chronology documentation source','category':'dev_tools','networks':[],'details':{}})
                write(store, "UPDATE resources SET health_status='healthy',last_ok_at=?,eval_grade='A',eval_score=95,eval_at=? WHERE source='synthetic-selection-bulk'", (now-20,now-1000))
            execution_report(store, last, now-1, title='Latest bulk evidence', slug='synthetic-bulk-latest',
                eval_grade='B',eval_score=90,is_success=1,created_at=now-1)
        began = time.monotonic()
        bulk_results = [rec.search('chronology documentation',kind='a2a') for rec in recommenders]
        bulk_elapsed = time.monotonic()-began
        equal('full_candidate_ranking_beyond_generic_2000_limit', bulk_results)
        require(recommenders[0].search('chronology documentation',kind='a2a')[0]['id'] == last,
            'newest_candidate_after_2000_is_retained')
        with native.tx(readonly=True):
            require(native._fts().execute('PRAGMA temp_store').fetchone()[0] == 2, 'request_metadata_temp_store_is_memory')
            tables = native._fts().execute("SELECT name FROM sqlite_temp_master WHERE name LIKE 'ac_selection_%'").fetchall()
        require(not tables, 'request_metadata_tables_removed_without_persistent_fallback')
        for name,call in (('bad_match',lambda:native.selection_candidates('x'*4097,'a2a',now)),
            ('bad_kind',lambda:native.selection_candidates('stock','sql',now)),
            ('bad_cutoff',lambda:native.selection_candidates('stock','a2a',float('inf'))),
            ('huge_integer_cutoff',lambda:native.selection_candidates('stock','a2a',10**10000)),
            ('url_list_bound',lambda:native.find_existing_candidates(['x']*33,[],'x','x')),
            ('url_injection_is_bound',lambda:native.find_existing_candidates(["x') OR 1=1 --"],[],'x','x'))):
            if name=='url_injection_is_bound': require(call()==[],name)
            else:
                try: call()
                except ApplicationStoreError: checks[name]=True
                else: raise AssertionError(name)
        # Dedicated request sessions must not wait behind the collector's
        # in-process lock; native transaction/deployment guards still apply.
        import threading
        from agent_market.admin_postgres_pool import AdminReaderPool
        from agent_market.concierge.request_store import interactive_store
        def interactive_factory():
            session=connect()
            try:return open_store('postgresql',connection=session,workflow_key=b's'*32),session
            except BaseException:session.close();raise
        pool=AdminReaderPool(interactive_factory,maximum=1,wait_seconds=.05)
        native._interactive_pool=pool
        entered,release=threading.Event(),threading.Event()
        def hold_catalog_lock():
            with native._lock:entered.set();release.wait(10)
        holder=threading.Thread(target=hold_catalog_lock);holder.start()
        try:
            require(entered.wait(1),'collector_lock_held_for_request_isolation')
            with interactive_store(native) as scoped:
                require(scoped is not native and scoped.backend=='postgresql','interactive_native_session_is_distinct')
                require(scoped.resource(last)['id']==last,'request_reads_while_collector_python_lock_is_held')
                try:
                    with interactive_store(native):raise AssertionError('Pool bound was bypassed')
                except TimeoutError:checks['interactive_native_pool_is_bounded']=True
        finally:
            release.set();holder.join(2);pool.close();del native._interactive_pool
        return {'checks':checks,'external_provider_calls':0,'operating_actions':0,
            'observation':{'native_and_sqlite_2005_candidate_queries_seconds':bulk_elapsed,
                'timing_is_not_a_service_sla':True,'fixture_candidates':2005}}
    finally:
        native.close(); connection.close(); sqlite._db.close()


def _worker():
    from scripts import rehearse_application_store_postgres as application
    application._contracts = _contracts
    application._worker()


def rehearse():
    root = Path(__file__).resolve().parents[1]
    sources = ('agent_market/application_store_selection.py','agent_market/concierge/selection.py',
        'agent_market/concierge/front.py','agent_market/application_store_postgres.py',
        'agent_market/application_store_sql.json','scripts/rehearse_application_selection_postgres.py',
        'agent_market/capability_registry.py','agent_market/concierge/report_evidence.py',
        'agent_market/gateway/store.py','tests/report_fixtures.py')
    def hashes():return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources}
    before = hashes()
    driver = _driver()
    with _private_cluster(_tools()) as cluster:
        environment = dict(cluster['environment']); environment['PYTHONDONTWRITEBYTECODE']='1'
        environment['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        result = subprocess.run([sys.executable,'-B','-c','from scripts.rehearse_application_selection_postgres import _worker;_worker()'],
            input=json.dumps({'root':cluster['root'],'socket':cluster['socket']}),env=environment,
            text=True,capture_output=True,timeout=180)
        if result.returncode: raise RuntimeError('Synthetic selection contract failed: '+result.stderr[-6000:])
        value=json.loads(result.stdout)
    if hashes()!=before:raise AssertionError('Selection source changed during native verification.')
    return {'profile':PROFILE,**value,'synthetic':True,'temporary_cluster_removed':True,'public_activation':False,
        'production_cutover':False,'source_hashes':before,'source_unchanged':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);parser.add_argument('--run',action='store_true')
    if not parser.parse_args().run:parser.error('--run is required')
    print(json.dumps(rehearse(),sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
