"""Caller-owned worker and migration binding on a new Unix-only fixture.

No operating DSN, source path, credentials or output location is accepted.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster

PROFILE = 'caller-worker-fenced-binding-native-v1'


def _contracts(cluster):
    from scripts.rehearse_workflow_native_postgres import _connection, _proxy, _rows
    from agent_market.storage_adapter import open_store
    from agent_market.workflow_worker import compose_worker, run_worker
    from agent_market.workflow_persistence import FenceLost
    from agent_market.collector import usage
    from tests.test_mcp_proxy import WEATHER_TOOL
    from agent_market.application_store_postgres import ApplicationStoreError
    from agent_market.application_store_migration import (copy_application, preparation_challenge,
        prepare_transition, PreparationAuthority, bind_application, review_application, MigrationDenied, _load)
    from agent_market.gateway import store as store_module
    from agent_market.gateway.admin_auth import ADMIN_SCHEMA

    checks = {}
    connection = _connection(cluster)
    store = open_store('postgresql', connection=connection, initialize=True, workflow_key=b'w'*32,
        required_capabilities=('durable_workflow_runtime',))
    audit = Path(cluster['root'])/'worker-calls.jsonl'
    proxy, http = _proxy(store, audit)
    runtime = compose_worker(store, proxy=proxy)
    try:
        rid = store.upsert_resource({'key':'synthetic:composition','kind':'mcp','source':'fixture',
            'url':'https://weather.example/mcp','name':'Synthetic weather','description':'Weather lookup',
            'category':'travel_maps_weather','details':{},'price_usdc':0})
        tools = usage.compact_tools([WEATHER_TOOL])
        store.record_usage(rid,tools=tools,digest=usage.tools_hash(tools),guide={},changes=None,trial={'ok':True})
        wid = store.create_workflow({'name':'Caller supplied worker','nodes':[
            {'id':'weather','name':'Weather','type':'agent','kind':'mcp',
             'data':{'resource_id':rid,'action':'get_weather','input':{'city':'Fixture'}}}], 'edges':[]})
        launch = runtime.launch; runtime.launch = lambda _: None
        try: queued = runtime.submit(store.get_workflow(wid))
        finally: runtime.launch = launch
        run_worker(runtime, stop=threading.Event(), once=True)
        checks['default_recovery_preserves_queued_work_without_transport_calls'] = runtime.get(queued['run_id'])['status']=='queued' and not _rows(audit)
        run_worker(runtime, stop=threading.Event(), once=True, execute=True)
        for future in list(runtime.futures.values()): future.result(timeout=15)
        checks['caller_owned_pg_runtime_executes_original_durable_queue'] = runtime.get(queued['run_id'])['status']=='succeeded' and len(_rows(audit))==1
        run_worker(runtime, stop=threading.Event(), once=True, execute=True)
        checks['second_tick_does_not_repeat_completed_business_call'] = len(_rows(audit))==1
        checks['caller_store_and_connection_remain_open'] = not store._closed and not connection.closed and store.resource(rid)['id']==rid
        launch = runtime.launch; runtime.launch = lambda _: None
        try: interrupted = runtime.submit(store.get_workflow(wid))
        finally: runtime.launch = launch
        row = runtime.persistence.claim(interrupted['run_id'],'synthetic-owner',25)
        with connection.cursor() as cursor:
            cursor.execute('SELECT deadline,lease_until FROM workflow_runs WHERE id=%s',(interrupted['run_id'],)); before=cursor.fetchone()
        checks['native_pulse_uses_supplied_pg_store'] = runtime.persistence.pulse(interrupted['run_id'],'synthetic-owner',row['fence'])
        with connection.cursor() as cursor:
            cursor.execute('SELECT deadline,lease_until FROM workflow_runs WHERE id=%s',(interrupted['run_id'],)); after=cursor.fetchone()
        checks['native_pulse_preserves_original_deadline'] = before[0]==after[0] and after[1]>=before[1]
        runtime.persistence.prepare(interrupted['run_id'],'synthetic-owner',row['fence'],'weather','0'*64)
        runtime.persistence.dispatch(interrupted['run_id'],'synthetic-owner',row['fence'],'weather')
        with connection.cursor() as cursor:cursor.execute('UPDATE workflow_runs SET lease_until=0 WHERE id=%s',(interrupted['run_id'],))
        runtime.persistence.recover()
        run_worker(runtime,stop=threading.Event(),once=True,execute=True)
        checks['dispatched_expired_job_remains_unknown_without_reexecution'] = runtime.get(interrupted['run_id'])['execution_outcome']=='unknown' and len(_rows(audit))==1
        checks['broad_operating_readiness_not_promoted'] = not store.coverage()['full_application_ready']
    finally:
        http.close(); store.close(); connection.close()

    connection = _connection(cluster)
    with connection.cursor() as cursor:cursor.execute('CREATE DATABASE binding_fixture')
    connection.close()
    native = _connection(cluster,'binding_fixture')
    target = open_store('postgresql',connection=native,initialize=True,workflow_key=b'b'*32)
    original = store_module.init_admin_auth_db
    store_module.init_admin_auth_db = lambda db: db.executescript(ADMIN_SCHEMA)
    source_path = Path(cluster['root'])/'binding-source.sqlite3'
    try: source = store_module.Store(str(source_path))
    finally:store_module.init_admin_auth_db=original
    operation = 'apm_'+'b'*32
    fields=('owner_ref','ingress_stop_ref','workers_stop_ref','external_reconciliation_ref','compatibility_ref','rollback_point_ref')
    permitted=[None]
    def verifier(challenge,proof):
        return {name:'fixture:'+name for name in fields} if proof=='fixture-owner' and challenge==permitted[0] else None
    authority=PreparationAuthority(b'a'*32,verifier=verifier)
    def approve(phase):
        permitted[0]=preparation_challenge(target,operation_id=operation,phase=phase)
        return authority.issue(permitted[0],'fixture-owner')
    arguments=dict(operation_id=operation,source_workflow_key=b'b'*32,authority=authority,proof='fixture-owner')
    try:
        source.upsert_resource({'key':'synthetic:binding','source':'fixture','kind':'mcp',
            'url':'https://binding.example/mcp','name':'Binding fixture','description':'Synthetic catalog',
            'category':'research','details':{},'networks':[]},now=10)
        copy_application(source,target,operation_id=operation,source_workflow_key=b'b'*32)
        cutover=approve('cutover')
        prepare_transition(source,target,phase='cutover',approval=cutover,**arguments)
        binding=approve('binding')
        try:
            with bind_application(source,target,approval=binding,**arguments) as bound:
                bound.set_meta('synthetic-binding-abort','must rollback')
                raise RuntimeError('Synthetic caller abort')
        except RuntimeError as error:
            if str(error)!='Synthetic caller abort':raise
        with review_application(native,workflow_key=b'b'*32,operation_id=operation) as reviewed:
            checks['caller_exception_rolls_back_target_and_binding_receipt'] = reviewed.get_meta('synthetic-binding-abort') is None and _load(reviewed)['state']=='cutover_prepared'
        binding=approve('binding')
        try:
            with bind_application(source,target,approval=binding,**arguments) as bound:
                bound.set_meta('synthetic-binding-revoked','must rollback')
                permitted[0]=None
        except MigrationDenied as error:
            if error.code!='independent_current_owner_proof_required':raise
        else:raise AssertionError('revoked independent proof admitted')
        with review_application(native,workflow_key=b'b'*32,operation_id=operation) as reviewed:
            checks['proof_revoked_during_bound_work_rolls_back'] = reviewed.get_meta('synthetic-binding-revoked') is None
        binding=approve('binding')
        with bind_application(source,target,approval=binding,**arguments) as bound:
            checks['binding_yields_actual_caller_target'] = bound is target and bound.resource(1)['name']=='Binding fixture'
            bound.set_meta('synthetic-bound-result',{'written':True})
            writer=sqlite3.connect(source_path,timeout=.05)
            try:
                try:writer.execute("INSERT INTO meta VALUES('synthetic-rival','forbidden')")
                except sqlite3.OperationalError:checks['actual_source_writer_fence_stays_held_during_binding']=True
                else:raise AssertionError('source competitor was not fenced')
            finally:writer.close()
            try:compose_worker(bound)
            except ValueError as error:checks['transactional_binding_does_not_masquerade_as_cross_thread_worker_binding']=str(error)=='idle_application_store_required'
            else:raise AssertionError('busy transactional binding reached worker')
        try:target.resource(1)
        except ApplicationStoreError as error:checks['target_is_requarantined_after_bound_commit']=error.code=='migration_target_quarantined'
        else:raise AssertionError('target escaped binding quarantine')
        with review_application(native,workflow_key=b'b'*32,operation_id=operation) as reviewed:
            receipt=_load(reviewed)
            checks['bound_application_write_committed_not_just_prepared'] = reviewed.get_meta('synthetic-bound-result')=={'written':True} and receipt['state']=='binding_completed'
            checks['binding_never_changes_global_operating_readiness'] = not receipt['full_application_ready'] and not receipt['operating_enabled'] and not receipt['cutover_authorized']
        checks['binding_does_not_mutate_source'] = source.get_meta('synthetic-bound-result') is None
        rollback=approve('rollback')
        try:prepare_transition(source,target,phase='rollback',approval=rollback,**arguments)
        except MigrationDenied as error:checks['target_divergence_refuses_blind_rollback']=error.code=='application_baseline_diverged'
        else:raise AssertionError('divergent target allowed blind rollback')
        if not all(checks.values()):raise AssertionError('worker binding native contract')
        return {'checks':checks,'operating_cutover':False,'full_application_ready':False}
    finally:target.close();native.close();source._db.close()


def _worker():
    from scripts.rehearse_workflow_native_postgres import _network_guard
    cluster=json.loads(sys.stdin.read(8192));_network_guard(cluster)
    print(json.dumps(_contracts(cluster),sort_keys=True,allow_nan=False))


def rehearse():
    driver=_driver()
    files=[Path(__file__),Path('agent_market/workflow_worker.py'),Path('agent_market/application_store_migration.py'),Path('agent_market/application_store_postgres.py'),Path('agent_market/application_store_sql.json')]
    before={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    with _private_cluster(_tools()) as cluster:
        env=dict(cluster['environment']);env['PYTHONDONTWRITEBYTECODE']='1'
        env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        result=subprocess.run([sys.executable,'-B','-c','from scripts.rehearse_worker_binding_postgres import _worker; _worker()'],input=json.dumps(cluster),env=env,text=True,capture_output=True,timeout=180)
        if result.returncode:raise RuntimeError('Native worker binding fixture failed: '+result.stderr[-4000:])
        result=json.loads(result.stdout)
    if before!={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in files}:raise AssertionError('source changed during native fixture')
    return {'profile':PROFILE,**result,'temporary_cluster_removed':True,'operating_database_writes':0,'external_provider_calls':0,'source_hashes':before}
