"""Disposable Unix PostgreSQL workspace operations acceptance; no operating DSN."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster, PORT


def contracts(connection):
    import secrets
    import time
    import statistics
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.storage_adapter import open_store
    from agent_market.gateway import admin_auth
    from agent_market.customer_identity import CustomerIdentity
    from agent_market.customer_organizations import CustomerOrganizations
    from agent_market.workspace_access import WorkspaceAccess, SessionActor
    from agent_market.workspace_admin_control import WorkspaceAdminControl
    from agent_market.workspace_admin_events import migrate,drain
    from agent_market.workspace_admin_service import router_for,BASE
    from agent_market.workspace_admin_worker import backfill,quarantine
    from tests.test_customer_identity import customer_world,login
    from tests.test_customer_credits import acceptance
    from tests.test_workspace_admin_control import case_body,command_body
    store=open_store('postgresql',connection=connection,initialize=True,workflow_key=b'k'*32)
    w=customer_world();w.store._db.close();w.store=store
    w.access=WorkspaceAccess(store,b'synthetic-workspace-key-32-bytes!!')
    w.core=CustomerIdentity(store,b'synthetic-customer-key-32bytes!!!',w.config,w.http)
    w.orgs=CustomerOrganizations(w.core,w.access)
    with store.tx() as db:
        staff=admin_auth.create_admin_user(db,'wac-fixture-owner','Synthetic-workspace-password-42','Fixture owner','superadmin')
        raw=admin_auth.create_session(db,staff['id'],staff['username'],staff['role'],staff['name'])
    actor=SessionActor(staff['id'],admin_auth.session_reference(raw));w.staff={1:actor}
    migrate(store,w.core.key);w.ops=WorkspaceAdminControl(w.core,w.access)
    auth=login(w);customer=w.core.actor(auth['session_token']);w.customers=[customer]
    w.organization=w.orgs.create({'name':'Synthetic native operations team'},customer)
    w.ops.credits.enroll(acceptance(),customer)
    checks={}
    try:
        assert w.ops.customer(actor,customer.customer_id)['credits']['balance']==3
        checks['native_identity_enrollment_and_metadata']=True
        body=command_body(w);item=w.ops.command(actor,body)
        def approve(_):return w.ops.approve(actor,item['command_id'],{'revision':1,'reason':'Native reviewed correction','confirm':'APPLY','allow_self_review':True})
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(approve,range(4)))
        assert sum(not x['replayed'] for x in results)==1
        assert w.ops.credits.status(customer)['balance']==5
        checks['native_concurrent_command_one_effect']=True
        from agent_market.workspace_admin_reviewed import ReviewedCommands
        from agent_market.execution_authority import controls as execution_state,set_controls
        queue=ReviewedCommands(store,{'execution_release':lambda payload,uid:set_controls(store,payload,uid)})
        assert queue.ready()
        current=execution_state(store)
        review=queue.request(staff['id'],'execution_release','execution',
            {k:current[k] for k in ('invoke_enabled','workflow_enabled','delivery_enabled','revision')},'Native reviewed release')
        done=queue.approve(staff['id'],actor.session_ref,review['id'],review['revision'],'Native reviewed release',True)
        assert done['status']=='applied' and done['same_person_review'] and queue.list(10)[0]['status']=='applied'
        assert execution_state(store)['revision']==current['revision']+1
        checks['native_reviewed_command_two_step']=True
        from agent_market.workspace_admin_summaries import HealthSummaries,DAY,day_key
        start=(int(time.time()//DAY)-1)*DAY
        with store.tx():
            for i,(outcome,latency) in enumerate((('healthy',100),('healthy',300),('down',None),('reachable',200))):
                store._execute('INSERT INTO health_checks(resource_id,at,outcome,status_code,latency_ms) VALUES(%s,%s,%s,%s,%s)',(4242,start+60*i,outcome,200,latency))
        summaries=HealthSummaries(store)
        assert summaries.ready() and summaries.summarize_day(start)==1 and summaries.summarize_day(start)==1
        import agent_market.workspace_admin_summaries as summary_module
        with store.tx():
            for rid in (5001,5002,5003):
                store._execute('INSERT INTO health_checks(resource_id,at,outcome,status_code,latency_ms) VALUES(%s,%s,%s,%s,%s)',(rid,start+30,'healthy',200,rid))
        summary_module.PAGE=2  # keyset pages across the native result cap
        assert [len(page) for page in summaries.aggregate(start)]==[2,2] and summaries.summarize_day(start)==4
        summary_module.PAGE=1000
        row=[r for r in summaries.agent(4242,7) if r['day']==day_key(start)][0]
        assert (row['checks'],row['ok'],row['latency_p50'],row['latency_p95'])==(4,3,200,300)
        assert summaries.run_due(force=True)['ready'] and summaries.span()['n']>=1
        checks['native_health_daily_summary']=True
        from agent_market.workspace_admin_retention import Retention
        with store.tx():
            for days_ago in (6,5,1):
                store._execute('INSERT INTO health_checks(resource_id,at,outcome,status_code,latency_ms) VALUES(%s,%s,%s,%s,%s)',(4343,time.time()-days_ago*DAY,'healthy',200,90))
        for _ in range(9): summaries.run_due(force=True)
        retention=Retention(store)
        assert retention.run_due(force=True)=={'ready':True,'removed':{}}
        retention.apply({'table':'health_checks','days':3,'backup_confirmed':True},staff['id'])
        removed=retention.run_due(force=True)['removed']['health_checks']
        with store.tx(readonly=True):
            left=store._execute('SELECT COUNT(*) FROM health_checks WHERE resource_id=4343').fetchone()[0]
        assert removed>=2 and left==1 and retention.status()['policy']['health_checks']==3
        checks['native_approved_retention_batches']=True
        from scripts.admin_console_indexes import build, state
        assert retention.indexed('legacy_vector_jobs')  # new stores receive them at initialization
        connection.execute('DROP INDEX legacy_vector_jobs_finished_done')  # an existing store before the operator step
        assert not retention.indexed('legacy_vector_jobs')
        before,built=build(connection)
        assert set(built)=={'legacy_vector_jobs_finished_done'} and before['platform_observation_events_created']['state']=='valid'
        assert all(v['state']=='valid' for v in state(connection).values()) and build(connection)[1]=={}
        with store.tx():
            for n,(status,days_ago) in enumerate((('superseded',9),('indexed',8),('pending',9),('indexed',1))):
                store._execute('INSERT INTO legacy_vector_jobs(job_id,resource_id,generation,status,created,finished) VALUES(%s,%s,%s,%s,%s,%s)',
                               ('rehearsal-%d'%n,1,1,status,time.time()-days_ago*DAY,time.time()-days_ago*DAY))
        retention.apply({'table':'legacy_vector_jobs','days':3,'backup_confirmed':True},staff['id'])
        assert retention.run_due(force=True)['removed']['legacy_vector_jobs']==2
        with store.tx(readonly=True):
            kept=sorted(r[0] for r in store._execute("SELECT status FROM legacy_vector_jobs WHERE job_id LIKE 'rehearsal-%%'").fetchall())
        assert kept==['indexed','pending']
        checks['native_concurrent_retention_indexes_and_vector_job_cleanup']=True
        assert w.ops.reconciliation(actor)['accounts'][0]['status']=='matched'
        checks['native_signed_credit_reconciliation']=True
        case=w.ops.create_case(actor,customer.customer_id,case_body(workspace_id=w.organization['id']))['case']
        action={'revision':1,'status':'in_progress','priority':'normal','assigned_to':staff['id'],
                'message':'Internal synthetic note','visibility':'internal','request_id':secrets.token_hex(16)}
        assert w.ops.case_action(actor,case['id'],action)['case']['revision']==2
        assert len(w.ops.case(actor,case['id'])['messages'])==2
        checks['native_support_case_and_revision']=True
        with store.tx():
            store._execute('''INSERT INTO customer_inquiries(inquiry_id,created_at,updated_at,category,name,email,subject,message)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
                ('inq_fixture',time.time(),time.time(),'general','Synthetic visitor','synthetic@example.invalid','Synthetic request','Controlled fixture'))
        linked=w.ops.link_case(actor,case['id'],{'revision':2,'source_kind':'inquiry','source_ref':'inq_fixture',
            'reason':'Synthetic customer relationship explicitly reviewed','confirmed_customer_relation':True})
        assert linked['original_request_state_unchanged']
        checks['native_original_customer_request_link_without_state_mutation']=True
        assert backfill(store,100)['source_rows_reviewed']>=1
        assert drain(store)['projected']>=3
        assert drain(store)['projected']==0
        assert w.ops.events(actor,customer.customer_id)['events']
        assert w.ops.overview(actor)['ingestion']['complete']
        checks['native_backfill_signed_projection_and_replay']=True
        assert w.ops.operations(actor,w.organization['id'])['drafts']==[]
        checks['native_all_workflow_metadata_queries']=True
        with store.tx():
            store._execute('''INSERT INTO customer_identities(id,issuer,subject_hash,active,revision,created,last_login)
                SELECT 'cu_' || lpad(n::text,32,'0'),'https://synthetic.invalid','perf-' || n::text,1,1,%s,%s
                FROM generate_series(1,1000) n''',(time.time(),time.time()))
        latencies=[]
        for _ in range(10):
            started=time.monotonic();assert len(w.ops.customers(actor)['customers'])==50
            latencies.append((time.monotonic()-started)*1000)
        performance={'fixture_customers':1001,'samples':10,'median_list_ms':round(statistics.median(latencies),3),
            'maximum_list_ms':round(max(latencies),3),'scope':'Local Unix PostgreSQL, metadata list only; not an operating-load SLA'}
        checks['native_customer_keyset_list_measurement']=True
        app=FastAPI();app.include_router(router_for(w.core,w.access,core=w.ops))
        paths=['/options','/overview','/customers','/customers/'+customer.customer_id,
            '/customers/'+customer.customer_id+'/timeline','/organizations','/organizations/'+w.organization['id']+'/operations',
            '/credits/reconciliation','/events','/cases','/cases/'+case['id'],'/commands','/incidents','/audit',
            '/customers/'+customer.customer_id+'/disclosures','/commands/'+item['command_id']]
        headers={'X-Dashboard':'1','Authorization':'Bearer '+raw}
        with TestClient(app,base_url='https://admin.test') as client:
            for path in paths:
                response=client.get(BASE+path,headers=headers)
                assert response.status_code==200,(path,response.status_code,response.text[:120])
            assert client.get(BASE+'/customers').status_code==401
        checks['native_authenticated_reads_no_5xx']=True
        pending=w.ops.command(actor,command_body(w,target_revision=2,delta=1))
        quarantine(store)
        from agent_market.workspace_access import WorkspaceConflict
        try:w.ops.approve(actor,pending['command_id'],{'revision':1,'reason':'Restored native command review','confirm':'APPLY'})
        except WorkspaceConflict:pass
        else:raise AssertionError('Restored pending command replayed')
        checks['native_restore_quarantine']=True
        return {'checks':checks,'authenticated_gets':len(paths),'performance':performance,'operating_writes':0,'external_provider_calls':0}
    finally:
        w.http.close();store.close()


def worker():
    cluster=json.load(sys.stdin);driver=_driver()
    connection=driver.connect(host=cluster['socket'],hostaddr='',port=PORT,dbname='postgres',user='postgres',
        password='synthetic-unused-password',passfile=str(Path(cluster['root'])/'no-password-file'),
        autocommit=True,connect_timeout=3,sslmode='disable',gssencmode='disable')
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr()")
            assert cursor.fetchone()==('',None,None)
        print(json.dumps(contracts(connection)))
    finally:connection.close()


def rehearse():
    driver=_driver()
    with _private_cluster(_tools()) as cluster:
        environment=dict(cluster['environment']);environment['PYTHONDONTWRITEBYTECODE']='1'
        environment['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        result=subprocess.run([sys.executable,'-B','-c','from scripts.rehearse_workspace_admin_postgres import worker;worker()'],
            env=environment,input=json.dumps({'socket':cluster['socket'],'root':cluster['root']}),
            text=True,capture_output=True,timeout=180)
        if result.returncode:raise RuntimeError('Workspace admin native contracts failed: '+result.stderr[-4000:])
        return {**json.loads(result.stdout),'temporary_cluster_removed':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true',required=True);parser.parse_args()
    print(json.dumps(rehearse(),indent=2))
