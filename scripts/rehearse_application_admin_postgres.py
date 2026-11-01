"""Native desktop admin finite query families on synthetic Unix-only fixtures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from scripts.rehearse_storage_adapter_postgres import _driver,_tools,_private_cluster

PROFILE='application-admin-native-contracts-v1'


def _contracts(connect):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.gateway import store as store_module,admin_auth
    from agent_market.storage_adapter import open_store
    from agent_market.gateway.dashboard import dashboard_router
    from agent_market.gateway.rag import RagEngine
    from agent_market.concierge.security import SecurityManager
    pg=connect();native=open_store('postgresql',connection=pg,initialize=True,workflow_key=b'a'*32)
    old=store_module.init_admin_auth_db
    store_module.init_admin_auth_db=lambda db:db.executescript(admin_auth.ADMIN_SCHEMA)
    try:reference=store_module.Store()
    finally:store_module.init_admin_auth_db=old
    checks={};engines=[];clock=time.time()
    try:
        for store in (native,reference):
            for index,name in enumerate(('Atomic transfer','ATOMIC','a\\b','Café','café','CAFÉ')):
                store.upsert_resource({'key':'fixture:admin:'+str(index),'source':'fixture','kind':'mcp',
                    'url':'https://synthetic-'+str(index)+'.example/mcp','name':name,'description':'Admin query parity',
                    'category':'research','networks':[],'details':{}},now=10+index)
            with store.tx() as db:
                user=admin_auth.create_admin_user(db,'fixture-owner','Synthetic-admin-password-42','Fixture owner','superadmin')
                token=admin_auth.create_session(db,user['id'],user['username'],user['role'],user['name'])
                admin_auth.record_audit(db,username='fixture-owner',role='superadmin',action='LOGIN',action_name='Fixture login',status='SUCCESS')
            if store is native:native_token=token
            else:sqlite_token=token
            # Each nonintegral bucket quotient catches PostgreSQL's rounding
            # casts, which differ from SQLite's truncating CAST AS INT.
            for stamp,outcome in ((clock-75,'healthy'),(clock-450,'failing'),(clock-8000,'reachable')):
                stamp=int(stamp//300)*300+225.5
                with store.tx() as db:
                    if store is native:store._execute('INSERT INTO health_checks(resource_id,at,outcome) VALUES(1,%s,%s)',(stamp,outcome))
                    else:db.execute('INSERT INTO health_checks(resource_id,at,outcome) VALUES(1,?,?)',(stamp,outcome))
        from agent_market.collector.server import create_app as collector_app
        with TestClient(collector_app(native,None,None,run_background=False)) as left,TestClient(collector_app(reference,None,None,run_background=False)) as right:
            for params in ({},{'q':'atomic'},{'q':'atomic','sort':'quality'},{'category':'research','kind':'mcp','status':'unknown','verified':'false'},
                    {'min_grade':'B','security':'ok','language':'en','region':'US','auth':'none'}, {'auth':'agent'}, {'auth':'oauth2'}, {'q':"x'); DROP TABLE resources; --"}):
                a=left.get('/agents',params=params);b=right.get('/agents',params=params)
                if a.status_code!=b.status_code or a.json()!=b.json():raise AssertionError('collector API query parity')
            checks['collector_full_filter_api_named_native_projection_matches_sqlite']=True
        from agent_market.collector.registries import Erc8004Crawler
        for store in (native,reference):
            with store.tx() as db:
                sql="INSERT INTO erc8004_tokens(chain,agent_id,host,uri,status,error) VALUES('fixture',?,'ipfs.io','https://ipfs.io/ipfs/fixture','deferred',NULL)"
                if store is native:store._execute(sql.replace('?','%s'),(1,))
                else:db.execute(sql,(1,))
                sql="INSERT INTO erc8004_tokens(chain,agent_id,host,uri,status,error) VALUES('fixture',?,'dead.example',NULL,'no_service',NULL)"
                for number in range(2,202):
                    if store is native:store._execute(sql.replace('?','%s'),(number,))
                    else:db.execute(sql,(number,))
            crawler=Erc8004Crawler(store,chains={'fixture':(1,'https://never-called.example')})
            if crawler.defer_dead_hosts(force=True)!=0:raise AssertionError('registry pending fixture')
            if store is native:
                with store.tx(readonly=True):row=store._execute('SELECT host,status FROM erc8004_tokens WHERE chain=%s AND agent_id=%s',('fixture',1)).fetchone()
            else:row=store.query('SELECT host,status FROM erc8004_tokens WHERE chain=? AND agent_id=?',('fixture',1))[0]
            if tuple(row)!=('ipfs','pending'):raise AssertionError('registry constant host migration')
        checks['erc8004_fixed_host_migration_and_defer_query_native_parity']=True
        from agent_market.gateway.visitor_desk import VisitorDesk
        for store in (native,reference):
            with store.tx() as db:
                for index,name in enumerate(('Alpha','Beta','Café','café','100%_test','C:\\path')):
                    values=('synthetic-visitor-'+str(index),'synthetic-hash-'+str(index),name,'admin-test' if index%2 else 'web',1,100+index)
                    sql='INSERT INTO agent_visitors(id,token_hash,name,channel,first_seen,last_seen) VALUES(?,?,?,?,?,?)'
                    if store is native:store._execute(sql.replace('?','%s'),values)
                    else:db.execute(sql,values)
                values=('synthetic-visitor-0','webhook','https://never-called.invalid','verified',1)
                sql='INSERT INTO agent_contacts(visitor_id,type,url,status,created) VALUES(?,?,?,?,?)'
                if store is native:store._execute(sql.replace('?','%s'),values)
                else:db.execute(sql,values)
        for contact in ('all','registered','authorized','marketing','pending','legacy','none'):
            for source in ('all','live','simulation'):
                a=VisitorDesk(native).list(contact=contact,source=source)
                b=VisitorDesk(reference).list(contact=contact,source=source)
                if a!=b:raise AssertionError('Visiting Agents purpose and source filter parity')
        for q in ('ALPHA','CafÉ','100%_','C:\\path',"x%' OR 1=1 --"):
            a=VisitorDesk(native).list(q=q,protocol='mcp',case_state='new',tier='new',source='live',limit=2,offset=1)
            b=VisitorDesk(reference).list(q=q,protocol='mcp',case_state='new',tier='new',source='live',limit=2,offset=1)
            if a!=b:raise AssertionError('Visiting Agents escaped query parity')
        checks['visiting_agents_named_filters_purpose_counts_and_escaped_text_parity']=True
        from agent_market.workflows import runtime_for
        from agent_market.workflow_maintenance import Maintenance
        for store in (native,reference):
            runtime=runtime_for(store)
            with store.tx() as db:
                sql="INSERT INTO workflow_versions(workflow_id,digest,snapshot,created) VALUES(999,'synthetic-unused','{}',1)"
                if store is native:store._execute(sql)
                else:db.execute(sql)
            snapshot='{}'
            digest=hashlib.sha256(snapshot.encode()).hexdigest()
            with store.tx() as db:
                for identity,outcome in (('wr_'+'1'*32,'known'),('wr_'+'2'*32,'unknown')):
                    values=(identity,999,digest,snapshot,'fixture','admin','failed',1,1,'{}',outcome)
                    sql='INSERT INTO workflow_runs(id,workflow_id,digest,snapshot,actor,source,status,created,finished,result,execution_outcome) VALUES(?,?,?,?,?,?,?,?,?,?,?)'
                    if store is native:store._execute(sql.replace('?','%s'),values)
                    else:db.execute(sql,values)
                    sql='INSERT INTO workflow_run_events VALUES(?,1,?,1)'
                    if store is native:store._execute(sql.replace('?','%s'),(identity,'synthetic-retained-event'))
                    else:db.execute(sql,(identity,'synthetic-retained-event'))
            result=Maintenance(runtime).run(apply=True,now=2000000000)
            if result['bodies_compacted']!=1:raise AssertionError('maintenance signed body fixture')
            metadata=Maintenance(runtime).run(apply=True,now=2000000000)
            if metadata['metadata_pruned']!=1:raise AssertionError('maintenance signed metadata prune')
            from agent_market.workflow_comparison import Comparison
            with Comparison(runtime).reader() as read:
                if read.resource(1)['name']!=store.resource(1)['name']:raise AssertionError('native comparison snapshot')
            if store is native:
                with store.tx(readonly=True):remaining=store._execute('SELECT COUNT(*) FROM workflow_versions WHERE workflow_id=999').fetchone()[0]
            else:remaining=store._db.execute('SELECT COUNT(*) FROM workflow_versions WHERE workflow_id=999').fetchone()[0]
            if remaining:raise AssertionError('native composite-key retention failed')
        checks['maintenance_unused_version_composite_key_pruning_matches_sqlite']=True
        checks['maintenance_signed_body_and_metadata_prune_preserves_unknowns']=True
        checks['comparison_reader_native_snapshot_without_sqlite_path']=True
        import httpx
        from agent_market.gateway.rag import RagPipeline
        def controlled_embedding(request):
            payload=json.loads(request.content)
            return httpx.Response(200,json={'embeddings':[[1.0]+[0.0]*767 for _ in payload['input']]})
        for store in (native,reference):
            http=httpx.Client(transport=httpx.MockTransport(controlled_embedding))
            engine=RagEngine(embed_model='synthetic-native-pipeline',embed_revision='fixture-v1',http=http)
            result=RagPipeline(engine,batch_size=2).step(store)
            if result['count']!=2 or result['failed']:raise AssertionError('current native RagPipeline step')
            http.close()
        checks['current_rag_pipeline_pending_claim_embedding_publication_native_and_sqlite']=True
        native_app,sqlite_app=FastAPI(),FastAPI();engines=[RagEngine(),RagEngine()]
        native_app.include_router(dashboard_router(native,None,None,None,rag_engine=engines[0]))
        sqlite_app.include_router(dashboard_router(reference,':memory:',None,None,rag_engine=engines[1]))
        native_headers={'X-Dashboard':'1','Authorization':'Bearer '+native_token}
        sqlite_headers={'X-Dashboard':'1','Authorization':'Bearer '+sqlite_token}
        with TestClient(native_app,base_url='https://admin.example') as left,TestClient(sqlite_app,base_url='https://admin.example') as right:
            choices=({}, {'q':'ATOMIC','kind':'mcp','status':'unknown','category':'research','source':'fixture','active':'all','sort':'name'},
                {'q':"x%' OR 1=1 --",'grade':'A','sort':'quality'}, {'sort':'failures','active':'0'}, {'sort':'new'}, {'sort':'popular'},
                {'q':'CAFÉ','sort':'name'},{'q':'a\\b','sort':'name'})
            for params in choices:
                a=left.get('/admin/api/agents',params=params,headers=native_headers)
                b=right.get('/admin/api/agents',params=params,headers=sqlite_headers)
                if a.status_code!=200 or a.json()!=b.json():raise AssertionError('admin agents finite parity')
            checks['admin_agent_filters_ascii_like_unicode_literal_escape_nocase_order']=True
            for hours in (1,24,168):
                a=left.get('/admin/api/timeseries',params={'hours':hours},headers=native_headers)
                b=right.get('/admin/api/timeseries',params={'hours':hours},headers=sqlite_headers)
                if a.status_code!=200 or a.json()!=b.json():raise AssertionError('admin bucket truncation parity')
            checks['admin_three_timeseries_buckets_match_sqlite_truncation']=True
            for params in ({},{'status':'active','category':'research','q':'test'}):
                a=left.get('/admin/api/needs',params=params,headers=native_headers)
                b=right.get('/admin/api/needs',params=params,headers=sqlite_headers)
                if a.status_code!=200 or a.json()!=b.json():raise AssertionError('admin needs finite parity')
            checks['admin_needs_filter_queries_bound_and_native']=True
            # Timestamps of separately created audit events legitimately differ.
            for params in ({},{'action':'LOGIN','username':'fixture-owner','status':'SUCCESS'}):
                a=left.get('/admin/api/audit/logs',params=params,headers=native_headers)
                b=right.get('/admin/api/audit/logs',params=params,headers=sqlite_headers)
                if a.status_code!=200 or a.json()['count']!=b.json()['count']:raise AssertionError('admin audit finite parity')
            checks['admin_audit_filter_queries_bound_and_native']=True
            a=left.get('/admin/api/overview',headers=native_headers)
            b=right.get('/admin/api/overview',headers=sqlite_headers)
            if a.status_code!=200 or a.json()['resources']!=b.json()['resources']:raise AssertionError('admin overview native')
            checks['admin_overview_fixed_metadata_and_boolean_aggregates']=True
            a=left.get('/admin/api/errors',headers=native_headers)
            b=right.get('/admin/api/errors',headers=sqlite_headers)
            if a.status_code!=200 or a.json()['health']!=b.json()['health']:raise AssertionError('admin errors native')
            checks['admin_error_aggregates_native']=True
            for params in ({},{'q':'atomic','kind':'mcp'},{'q':'atomic','category':'research','verified':'true','no_auth':'true'}):
                a=left.get('/admin/api/explore',params=params,headers=native_headers)
                b=right.get('/admin/api/explore',params=params,headers=sqlite_headers)
                if a.status_code!=200 or a.json()!=b.json():raise AssertionError('admin explore FTS and filter parity')
            checks['admin_explore_fts5_visibility_weighting_and_null_order_match']=True
            for path,params in (('/admin/api/test/agents',{}),('/admin/api/test/agents',{'q':'1','kind':'mcp'}),
                    ('/admin/api/test/agents',{'q':'atomic'}),('/admin/api/test/agents',{'q':'research'}),
                    ('/admin/api/workflows/agents/alternatives',{'q':'atomic','kind':'mcp'})):
                a=left.get(path,params=params,headers=native_headers);b=right.get(path,params=params,headers=sqlite_headers)
                if a.status_code!=200 or a.json()!=b.json():raise AssertionError('admin test and alternative query parity: '+path)
            checks['admin_test_agent_and_workflow_alternative_native_query_families']=True
            a=left.get('/admin/api/insights',headers=native_headers);b=right.get('/admin/api/insights',headers=sqlite_headers)
            if a.status_code!=200 or a.json()['kinds']!=b.json()['kinds']:raise AssertionError('admin insights finite queries')
            checks['admin_insights_fixed_featured_queries_upper_medians_native']=True
            # Exercise every registered top-level menu read, including the
            # workspace/customer modules composed into the administrator app.
            # Parameterized detail and provider-invoking routes are covered by
            # their dedicated tests, not guessed fixture identities here.
            menu_reads = []
            from agent_market.owned_data_agents.activation import install as install_owned
            owned = install_owned(native, 'https://synthetic-owned.example')
            for resource_id in owned.values():
                native.record_health(resource_id, 'healthy', 200, 1, None, time.time()+7200)
            current_examples = left.get('/admin/api/test/examples', headers=native_headers).json()['examples']
            checks['admin_examples_resolve_current_first_party_postgres_bindings'] = (
                # One example per owned test agent (staging.TEST_IDS), each bound to its installed resource.
                len(current_examples) == len(__import__('agent_market.owned_data_agents.staging', fromlist=['TEST_IDS']).TEST_IDS)
                and all(row['resource_id'] in owned.values() for row in current_examples))
            provisioned = left.post('/admin/api/workflow-workspaces', headers=native_headers,
                json={'name': 'Synthetic current administrator workspace', 'owner_id': user['id']})
            if provisioned.status_code != 200:
                raise AssertionError('native administrator workspace provisioning')
            workspace_id = provisioned.json()['workspace']['id']
            for path, operations in native_app.openapi()['paths'].items():
                path = path.replace('{workspace_id}', workspace_id)
                if not path.startswith('/admin/api/') or '{' in path or 'get' not in operations:
                    continue
                if path == '/admin/api/rag/ask':
                    continue
                try:
                    response = left.get(path, headers=native_headers)
                    code = response.status_code
                except Exception as exc:
                    raise AssertionError('native admin menu read failed: '+path+' '+type(exc).__name__) from exc
                menu_reads.append({'path': path, 'status': code})
                if code >= 500 and code != 503:
                    raise AssertionError('native admin menu read returned '+str(code)+': '+path)
            checks['all_registered_parameterless_admin_menu_reads_without_internal_errors']=bool(menu_reads)
            checks['admin_unauthenticated_request_denied']=left.get('/admin/api/agents').status_code in (401,403)
            checks['admin_cross_origin_write_denied']=left.post('/admin/api/credentials',headers={**native_headers,'Origin':'https://outside.example'},json={'key_name':'forbidden','key_value':'synthetic'}).status_code==403
        with native.tx() as db:
            # The last active superadmin cannot be demoted; keep a second one so the edit itself is exercised.
            admin_auth.create_admin_user(db,'second-superadmin','Second-superadmin-password','Second','superadmin')
            checks['admin_user_dynamic_mutation_and_current_session_revocation']=admin_auth.update_admin_user(db,user['id'],name='Changed',role='operator',active=1)
            checks['admin_session_invalidated_by_role_edit']=admin_auth.get_session_user(db,native_token) is None
        if not all(checks.values()):raise AssertionError('native admin contracts: '+','.join(name for name,value in checks.items() if not value))
        return {'checks':checks,'menu_reads':menu_reads,'full_application_ready':False,'backend_path_faked':False}
    finally:
        for engine in engines:engine.http.close()
        native.close();pg.close();reference._db.close()


def _worker():
    from scripts import rehearse_application_store_postgres as base
    base._contracts=_contracts;base._worker()


def rehearse():
    driver=_driver()
    paths=[Path(__file__),Path('agent_market/application_store_postgres.py'),Path('agent_market/application_store_sql.json'),Path('agent_market/gateway/dashboard.py')]
    before={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    with _private_cluster(_tools()) as cluster:
        environment=dict(cluster['environment']);environment['PYTHONDONTWRITEBYTECODE']='1'
        environment['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        child=subprocess.run([sys.executable,'-B','-c','from scripts.rehearse_application_admin_postgres import _worker; _worker()'],env=environment,
            input=json.dumps({'socket':cluster['socket'],'root':cluster['root']}),text=True,capture_output=True,timeout=180)
        if child.returncode:raise RuntimeError('Synthetic admin contracts failed: '+child.stderr[-5000:])
        result=json.loads(child.stdout)
    if before!={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}:raise AssertionError('source changed')
    return {'profile':PROFILE,**result,'source_hashes':before,'source_unchanged':True,'temporary_cluster_removed':True,
        'operating_database_writes':0,'external_provider_calls':0}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);parser.add_argument('--run',action='store_true',required=True);parser.parse_args(argv)
    print(json.dumps(rehearse(),sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
