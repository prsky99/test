"""Whole service backend and writer rollback on a disposable Unix PostgreSQL.

No operating DSN, key, database, listener or output destination is accepted.
The child builds the current finite catalog in memory while concurrent source
work is underway; final release verification uses the checked-in frozen catalog.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster

PROFILE = 'application-runtime-postgres-service-v1'


def _contracts(cluster, *, provisional=False):
    import threading
    from fastapi.testclient import TestClient
    from scripts.build_application_store_postgres_catalog import build_catalog
    from scripts.rehearse_workflow_native_postgres import _connection, _network_guard
    import agent_market.application_store_postgres as native
    from agent_market.application_runtime import open_runtime_storage
    from agent_market.application_store_migration import (copy_application, prepare_transition,
        preparation_challenge, PreparationAuthority, activate_application, rollback_activation,
        MigrationDenied, _load)
    from agent_market.storage_adapter import open_store
    from agent_market.gateway.store import Store
    from agent_market.config import GatewayConfig, NetworkConfig
    from agent_market.gateway.server import create_app
    from agent_market.concierge.front import create_front_app
    from agent_market.collector.server import create_app as collector_app
    from agent_market.ledger import Ledger
    from agent_market.workflow_worker import compose_worker, run_worker, drain_worker
    from agent_market.workflow_storage import observe_store
    import agent_market.gateway.ssl_manager as tls
    checks = {}
    def require(value, name):
        if not value:
            raise AssertionError(name)
        checks[name] = True
    # Development can explicitly test a provisional catalog without overwriting
    # the canonical artifact. Release tests use the actual checked-in catalog.
    if provisional:
        native._CATALOG = build_catalog()
        native._STATEMENTS = {native._normalized(item['sqlite']):item for item in native._CATALOG['statements']}
    _network_guard(cluster)
    tls.get_ssl_manager = lambda: None
    root = Path(cluster['root'])
    connection = _connection(cluster)
    store = open_store('postgresql', connection=connection, initialize=True, workflow_key=b'r'*32)
    try:
        ledger = Ledger(store=store)
        require(ledger.claim('synthetic-tx','synthetic-payer','workflow',40), 'native_payment_replay_claim')
        require(not ledger.claim('SYNTHETIC-TX','other','other',99), 'native_duplicate_payment_refused')
        ledger.settle('synthetic-tx')
        require(ledger.list_payments(status='settled',service='work')[1] == 1
            and ledger.stats()['total_revenue'] == 40, 'native_payment_projection_exact')
        require(ledger.list_payments(service='WORK')[1] == 1, 'native_ledger_preserves_ascii_like_semantics')
        require(ledger.list_payments()[1] == 1, 'native_null_filters_typed')
        store.upsert_resource({'key':'synthetic:runtime','kind':'mcp','source':'fixture',
            'url':'https://fixture.example/mcp','name':'Synthetic runtime','description':'Native backend test',
            'category':'developer_tools','details':{},'networks':[]})
        configuration = GatewayConfig(NetworkConfig.from_env(),None,str(root/'must-not-open.sqlite3'),
            'synthetic-admin-token',1,60,60,False,False,agent_discovery=False,erc8004_chains='',trials=False,
            agent_front_url='https://agentconcierge.biz')
        app = create_app(configuration,store=store)
        with TestClient(app) as client:
            require(client.get('/health').status_code == 200, 'actual_gateway_app_uses_native_backend')
            require(client.get('/.well-known/agent.json').status_code == 200, 'actual_gateway_card_reads_native')
            require(app.state.service.ledger._db is store._db, 'gateway_ledger_has_no_sidecar_database')
            require(not (root/'must-not-open.sqlite3').exists(), 'gateway_does_not_create_sqlite_fallback')
            with TestClient(create_front_app(app.state.front,manage_book_lifecycle=False)) as public:
                response = public.get('/')
                require(response.status_code == 200 and ('AgentValCon' in response.text or 'Agent Concierge' in response.text),
                    'actual_public_front_bootstrap_uses_native')
                require(public.get('/customer/sign-in').status_code == 404,
                    'native_backend_does_not_open_public_workspace')
            with TestClient(collector_app(store,None,'synthetic-admin-token',run_background=False)) as collector:
                require(collector.get('/health').status_code == 200
                    and collector.get('/agents').status_code == 200
                    and collector.get('/stats').status_code == 200,
                    'actual_collector_app_reads_same_native_backend')
            observed = observe_store(store)
            require(observed['available'] and observed['backend']=='postgresql',
                'native_storage_observer_never_uses_sqlite_path')
            from agent_market.application_control_retention import ControlRetention
            from agent_market.workspace_access import _canonical
            import time
            graph=app.state.front._workspace_platform
            retention=ControlRetention(graph.access);old=time.time()-100*86400
            ws='ws_'+'e'*32
            research={'id':'rrm_'+'a'*32,'workspace_id':ws,'corpus_id':'rcp_'+'a'*32,
                'created':old,'expires':old+60,'episodes':[{'query':'Synthetic retained research'}]}
            claim={'workspace_id':ws,'resource_id':1,'source_ref':'rej_'+'b'*32,
                'kind':'observation','outcome':'completed','observed_at':old}
            admission={'id':'rad_'+'c'*32,'workspace_id':ws,'logical_key':'d'*64,
                'created':old,'expires':old+60,'snapshot_id':None,'ticket_id':None}
            with store.tx() as db:
                db.execute('INSERT INTO reliability_research_manifests VALUES(?,?,?,?,?,?)',
                    (research['id'],ws,research['corpus_id'],old,_canonical(research),graph.reliability_research.sign(research)))
                db.execute('INSERT INTO reliability_circuit_claims VALUES(?,?,?,?,?)',
                    (ws,claim['source_ref'],1,_canonical(claim),graph.reliability_circuit.sign(claim)))
                db.execute('INSERT INTO reliability_admissions VALUES(?,?,?,NULL,NULL,?,?)',
                    (admission['id'],ws,admission['logical_key'],_canonical(admission),graph.single_admission.sign(admission)))
                compacted=retention.run(db,ws)
            require(compacted['research_bodies_compacted']==compacted['circuit_claims_compacted']
                ==compacted['never_ticketed_admissions_compacted']==1,
                'actual_native_retention_compacts_only_expired_safe_control_bodies')
            with store.tx(readonly=True):
                require(store._execute('SELECT COUNT(*) FROM application_control_archives').fetchone()[0]==3,
                    'native_retention_keeps_signed_hash_archives')
        require(not store._closed and not connection.closed, 'caller_owned_service_store_retained_after_shutdown')
        runtime = compose_worker(store)
        require(run_worker(runtime,stop=threading.Event(),once=True)['ticks']==1
            and drain_worker(runtime), 'selected_native_worker_recovers_and_drains')
        with store.tx():
            store._execute('INSERT INTO customer_recovery_policies VALUES(%s,%s,%s,%s)',(ws,7,'synthetic','signature'))
            store._execute('INSERT INTO customer_recovery_requests VALUES(%s,%s,%s,%s,%s,%s,%s)',
                ('recovery-fixture',ws,'target','pending',old,'synthetic','signature'))
            store._execute('INSERT INTO stripe_sandbox_orders VALUES(%s,%s,%s,%s)',('stripe-fixture',ws,'synthetic','signature'))
        from agent_market.workflow_postgres_archive import quarantine
        quarantine(store)
        with store.tx(readonly=True):
            require(store._execute('SELECT COUNT(*) FROM customer_recovery_blocks').fetchone()[0]==2
                and store._execute('SELECT COUNT(*) FROM stripe_sandbox_restore_blocks').fetchone()[0]==1,
                'actual_native_restore_permanently_blocks_recovery_and_sandbox_orders')
    finally:
        store.close(); connection.close()
    dsn_file=root/'runtime.dsn';key_file=root/'runtime.key'
    dsn_file.write_text('host='+cluster['socket']+' port=55447 dbname=postgres user=postgres')
    key_file.write_bytes(b'r'*32)
    dsn_file.chmod(0o600);key_file.chmod(0o600)
    from agent_market.application_runtime import _connect
    _connect(dsn_file.read_text()).close()
    selected=open_runtime_storage(None,values={'APPLICATION_STORE_BACKEND':'postgresql',
        'APPLICATION_POSTGRES_DSN_FILE':str(dsn_file),'APPLICATION_WORKFLOW_KEY_FILE':str(key_file)})
    try:
        require(selected.store.resource(1)['name']=='Synthetic runtime',
            'actual_process_setting_factory_attaches_same_native_database')
    finally:
        selected.close()
    require(selected.closed and selected.connection.closed, 'selected_owner_closes_native_connection_after_drain')
    from contextlib import redirect_stdout
    from io import StringIO
    from unittest.mock import patch
    settings={'APPLICATION_STORE_BACKEND':'postgresql','APPLICATION_POSTGRES_DSN_FILE':str(dsn_file),
              'APPLICATION_WORKFLOW_KEY_FILE':str(key_file)}
    from agent_market.workflow_storage import main as storage_main
    from agent_market.workflow_maintenance import main as maintenance_main
    from agent_market.workflow_worker import main as worker_main
    with patch.dict(os.environ,settings):
        output=StringIO()
        with patch.object(sys,'argv',['workflow-storage']),redirect_stdout(output):
            require(storage_main()==0, 'selected_native_storage_cli_succeeds_without_sqlite_filename')
        require(json.loads(output.getvalue())['backend']=='postgresql', 'native_storage_cli_reports_selected_backend')
        output=StringIO()
        with patch.object(sys,'argv',['workflow-maintenance']),redirect_stdout(output):
            maintenance_main()
        require(json.loads(output.getvalue())['dry_run'] is True,
            'selected_native_maintenance_cli_preview_does_not_initialize_sqlite')
        with patch.object(sys,'argv',['workflow-worker','--once']):
            worker_main()
        checks['normal_native_worker_cli_runs_and_drains_with_no_sqlite_filename']=True

    connection = _connection(cluster)
    with connection.cursor() as cursor:
        cursor.execute('CREATE DATABASE runtime_activation')
    connection.close()
    connection = _connection(cluster,'runtime_activation')
    target = open_store('postgresql',connection=connection,initialize=True,workflow_key=b'm'*32)
    source_path = root/'activation-source.sqlite3'
    source = Store(str(source_path))
    from agent_market.credential_vault import CredentialVault
    source._credential_vault=CredentialVault.from_key(b'v'*32)
    source.set_credential('synthetic-api','initial-synthetic-secret','fixture')
    # Seed the payment table in the source; it belongs to application transfer.
    source_ledger = Ledger(store=source)
    source_ledger.claim('baseline-tx','baseline-payer','test',3)
    source_ledger.settle('baseline-tx')
    operation='apm_'+'d'*32
    fields=('owner_ref','ingress_stop_ref','workers_stop_ref','external_reconciliation_ref','compatibility_ref','rollback_point_ref')
    allowed=[None]
    def verifier(challenge, proof):
        return {name:'fixture:'+name for name in fields} if proof=='fixture-owner' and challenge==allowed[0] else None
    authority=PreparationAuthority(b'a'*32,verifier=verifier)
    def approval(phase):
        allowed[0]=preparation_challenge(target,operation_id=operation,phase=phase)
        return authority.issue(allowed[0],'fixture-owner')
    arguments=dict(operation_id=operation,source_workflow_key=b'm'*32,authority=authority,
        proof='fixture-owner',source_vault=source._credential_vault)
    try:
        from agent_market.application_store_migration import _quiescent
        from agent_market.private_artifact_keys import ArtifactSigner
        from agent_market.workspace_access import PROFILE as ACCESS_PROFILE
        import hashlib
        import hmac
        runtime_key=hmac.new(b'm'*32,b'workflow-results-v1',hashlib.sha256).digest()
        access_key=hmac.new(runtime_key,ACCESS_PROFILE.encode(),hashlib.sha256).digest()
        domains=(
            ('workspace_remote_tasks','private-a2a03-task-poll-v1','status','completed',
                ('submitted','working','input-required','auth-required','dispatched','unknown'),
                {'logical_id':'logical','expires':9999999999.0}),
            ('reliability_eval_jobs','bounded-continuous-evaluation-v1','state','completed',
                ('reserved','prepared','dispatched','unknown'),
                {'logical_key':'logical','host_key':'host','window_start':1.0,'expires':9999999999.0}),
            ('workspace_machine_update_events','workspace-machine-evidence-updates-v1','state','accepted',
                ('prepared','dispatched','unknown'),
                {'subscription_id':'subscription','dedupe_hash':'dedupe','created':1.0}),
            ('stripe_sandbox_commands','stripe-connect-test-usd-gross-v1',None,'accepted',
                ('dispatched','unknown'),{'order_id':'order'}),
        )
        with target.tx():
            require(_quiescent(target),'native_handoff_starts_without_external_effects')
            for table,profile,state_column,terminal,active,extras in domains:
                signer=ArtifactSigner(hmac.new(access_key,profile.encode(),hashlib.sha256).digest(),profile)
                for state in (*active,terminal):
                    value={'id':'native-effect','workspace_id':'workspace','state':state,**extras}
                    row={**value,'payload':json.dumps(value),'signature':signer.sign(value)}
                    if state_column:
                        row[state_column]=state
                    if state_column!='state':
                        del row['state']
                    statement='INSERT INTO public."'+table+'"('+','.join(row)+') VALUES('+','.join('%s' for _ in row)+')'
                    target._execute(statement,tuple(row.values()))
                    if _quiescent(target)!=(state==terminal):
                        raise AssertionError('Native external-effect handoff state mismatch: '+table)
                    target._execute('DELETE FROM public."'+table+'"')
                checks['native_handoff_checks_all_'+table+'_states']=True
                row['signature']='0'*64
                target._execute(statement,tuple(row.values()))
                require(not _quiescent(target),'native_handoff_rejects_forged_'+table+'_terminal_proof')
                target._execute('DELETE FROM public."'+table+'"')
                row['signature']=signer.sign(value)
                row['workspace_id']='tampered-locator'
                target._execute(statement,tuple(row.values()))
                require(not _quiescent(target),'native_handoff_rejects_changed_'+table+'_terminal_locator')
                target._execute('DELETE FROM public."'+table+'"')
        require(source._db.execute("SELECT 1 FROM sqlite_master WHERE name='stripe_sandbox_commands'").fetchone() is None,
            'optional_source_effect_domain_absent_before_retirement')
        source.set_meta('before-activation',{'original':True})
        copy_application(source,target,operation_id=operation,source_workflow_key=b'm'*32,source_vault=source._credential_vault)
        prepare_transition(source,target,phase='cutover',approval=approval('cutover'),**arguments)
        import agent_market.application_store_migration as migration
        original_receipt = migration._receipt
        def interrupted_receipt(current, value, **options):
            if value['state']=='service_active':
                require(source._db.execute('PRAGMA synchronous').fetchone()[0]==2
                    and source._db.execute('PRAGMA fullfsync').fetchone()[0]==1,
                    'source_retirement_uses_full_durability_before_native_activation')
                raise RuntimeError('Synthetic target failure after committed source retirement')
            return original_receipt(current,value,**options)
        migration._receipt = interrupted_receipt
        try:
            try:
                activate_application(source,target,approval=approval('activation'),**arguments)
            except RuntimeError as error:
                require(str(error).startswith('Synthetic target failure'), 'fault_after_source_retirement_is_injected')
            else:
                raise AssertionError('Missing injected activation failure')
        finally:
            migration._receipt = original_receipt
        require(_load(target)['state']=='cutover_prepared', 'failed_target_activation_keeps_native_quarantine')
        try:
            source.set_meta('cannot-write','retired')
        except Exception as error:
            require(str(error)=='application_source_writer_retired', 'failed_target_activation_keeps_source_retired')
        else:
            raise AssertionError('Failed activation reopened stale source')
        activated=activate_application(source,target,approval=approval('activation'),**arguments)
        require(activated['receipt']['persistent_writer_binding'], 'fresh_independent_approval_completes_retired_transfer')
        require(source._db.execute('PRAGMA synchronous').fetchone()[0]==1,
            'transition_restores_normal_source_connection_durability_after_full_commit')
        require(target.get_meta('before-activation')=={'original':True}, 'activated_target_usable_outside_bounded_binding')
        import sqlite3
        raw=sqlite3.connect(source_path,timeout=.05)
        try:
            try:
                raw.execute("INSERT INTO meta VALUES('forbidden','stale source')")
            except sqlite3.IntegrityError:
                checks['stale_raw_sqlite_writer_remains_durably_blocked']=True
            else:
                raise AssertionError('old source writer admitted')
            raw.rollback()
            from agent_market.stripe_sandbox import SCHEMA as STRIPE_SCHEMA
            for statement in STRIPE_SCHEMA:
                raw.execute(statement)
            raw.commit()
            try:
                raw.execute("INSERT INTO stripe_sandbox_commands VALUES('stale-effect','workspace','order','synthetic','signature')")
            except sqlite3.IntegrityError:
                checks['retired_source_fences_late_optional_raw_schema_constructor']=True
            else:
                raise AssertionError('Late optional source constructor escaped retirement')
        finally:
            raw.close()
        target.close();connection.close()
        connection=_connection(cluster,'runtime_activation')
        target=open_store('postgresql',connection=connection,workflow_key=b'm'*32)
        require(target.get_meta('before-activation')=={'original':True}, 'native_service_can_restart_after_activation')
        target.set_meta('after-activation',{'new':True})
        target.set_credential('synthetic-api','changed-synthetic-secret','fixture')
        native_ledger=Ledger(store=target)
        native_ledger.claim('new-tx','new-payer','test',7)
        native_ledger.settle('new-tx')
        try:
            rollback_activation(source,target,approval=approval('rollback_activation'),**arguments)
        except MigrationDenied as error:
            require(error.code=='application_baseline_diverged', 'divergent_target_never_blindly_rolls_back')
        else:
            raise AssertionError('divergent rollback accepted')
        reversed=rollback_activation(source,target,approval=approval('rollback_activation'),capture_changes=True,**arguments)
        require(reversed['receipt']['change_capture']['captured_rows']>0
            and source.get_meta('after-activation')=={'new':True}, 'latest_native_changes_captured_before_source_activation')
        require(source_ledger.get_payment('new-tx')['status']=='settled'
            and not source_ledger.claim('new-tx','any','test',1), 'rollback_preserves_new_financial_replay_tombstones')
        require(source.get_credential('synthetic-api')=='changed-synthetic-secret',
            'rollback_decrypts_and_reseals_current_credentials_with_original_source_custody')
        source.set_meta('after-rollback',True)
        require(source.get_meta('after-rollback') is True, 'source_writer_resumes_after_known_target_stop')
        try:
            target.get_meta('after-activation')
        except native.ApplicationStoreError as error:
            require(error.code=='migration_target_quarantined', 'rolled_back_target_cannot_keep_writing')
        else:
            raise AssertionError('retired native target admitted')
    finally:
        target.close();connection.close();source._db.close()
    return checks


def _worker():
    cluster=json.loads(sys.stdin.read(8192))
    provisional=cluster.pop('provisional_catalog',False)
    print(json.dumps({'checks':_contracts(cluster,provisional=provisional)},sort_keys=True))


def rehearse(*, provisional=False):
    if type(provisional) is not bool:
        raise ValueError('explicit_fixture_catalog_required')
    driver=_driver()
    with _private_cluster(_tools()) as cluster:
        environment=dict(cluster['environment']);environment['PYTHONDONTWRITEBYTECODE']='1'
        environment['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        result=subprocess.run([sys.executable,'-B','-c','from scripts.rehearse_application_runtime_postgres import _worker; _worker()'],
            input=json.dumps({**cluster,'provisional_catalog':provisional}),env=environment,text=True,capture_output=True,timeout=240)
        if result.returncode:
            raise RuntimeError('Isolated native runtime fixture failed: '+result.stderr[-6000:])
        value=json.loads(result.stdout)
    return {'profile':PROFILE,**value,'temporary_cluster_removed':True,'operating_database_writes':0,
        'external_provider_calls':0,'operating_cutover':False,'external_ha_dr_acceptance':False,
        'provisional_catalog':provisional}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--provisional-catalog',action='store_true')
    args=parser.parse_args()
    print(json.dumps(rehearse(provisional=args.provisional_catalog),sort_keys=True))
