"""Isolated workflow-state PostgreSQL migration/CAS rehearsal, never production cutover.

Requires local PostgreSQL tools. Creates a private, Unix-socket-only temporary
cluster, imports a bounded execution-state snapshot and destroys that cluster.
The rest of the SQLite catalog/FTS/application adapter is deliberately unchanged.
"""
# ruff: noqa: S608 -- fixed TABLES identifiers; values pass literal(), with standard_conforming_strings enabled
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess  # nosec B404
import tempfile

TABLES=('workflow_versions','workflow_runs','workflow_node_runs','workflow_schedules','workflow_event_receipts',
        'workflow_destinations','workflow_deliveries','execution_controls','execution_control_events',
        'workflow_delivery_grants','workflow_run_authority','workflow_execution_attempts','workflow_checkpoints',
        'workflow_result_outbox','workflow_run_events','workflow_fallback_control','workflow_fallback_policies',
        'workflow_fallback_runs','workflow_routing_attempts','workflow_routing_decisions','workflow_fallback_shadow','workflow_fallback_audit',
        'workflow_execution_budgets','workflow_reconciliation_events','workflow_manual_deliveries','workflow_run_archives','workflow_maintenance_events','workflow_io_profiles',
        'workflow_deployment_grants','workflow_publication_grants','workflow_connection_deployments','workflow_connection_automation','workflow_connection_automation_admissions')


def literal(value):
    if value is None:return 'NULL'
    if isinstance(value,int):return str(value)
    if isinstance(value,float):
        if not math.isfinite(value):raise ValueError('Non-finite migration value.')
        return repr(value)
    if not isinstance(value,str):raise ValueError('Unsupported migration type.')
    if '\x00' in value:raise ValueError('NUL is not a PostgreSQL text value.')
    return "'"+value.replace("'","''")+"'"


def export_state(path):
    from agent_market.workflows import SCHEMA as WORKFLOWS
    from agent_market.execution_authority import SCHEMA as AUTHORITY
    from agent_market.workflow_persistence import SCHEMA as PERSISTENCE
    from agent_market.workflow_fallback import SCHEMA as FALLBACK
    from agent_market.workflow_budgets import SCHEMA as BUDGETS
    from agent_market.workflow_operations import SCHEMA as OPERATIONS
    from agent_market.workflow_maintenance import SCHEMA as MAINTENANCE
    from agent_market.workflow_deployment_consent import SCHEMA as DEPLOYMENT
    from agent_market.workflow_publication import SCHEMA as PUBLICATION
    from agent_market.workflow_connection_deployment import SCHEMA as CONNECTION_DEPLOYMENT
    from agent_market.workflow_connection_automation import SCHEMA as CONNECTION_AUTOMATION
    from agent_market.workflow_io_profiles import SCHEMA as IO_PROFILES
    # DDL comes from trusted application code, never snapshot sqlite_master SQL.
    model=sqlite3.connect(':memory:');model.executescript(WORKFLOWS+AUTHORITY+PERSISTENCE+FALLBACK+BUDGETS+OPERATIONS+MAINTENANCE+DEPLOYMENT+PUBLICATION+CONNECTION_DEPLOYMENT+CONNECTION_AUTOMATION+IO_PROFILES)
    for name,declaration in (('lease_until','REAL NOT NULL DEFAULT 0'),('owner','TEXT'),('fence','INTEGER NOT NULL DEFAULT 0'),('deadline','REAL'),('execution_outcome','TEXT')):
        model.execute(f'ALTER TABLE workflow_runs ADD COLUMN {name} {declaration}')
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    statements=['CREATE SCHEMA workflow_rehearsal; SET search_path=workflow_rehearsal; SET standard_conforming_strings=on;'];expected={}
    try:
        db.execute('BEGIN')
        for table in TABLES:
            schema=model.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()
            columns=[r[1] for r in model.execute('PRAGMA table_info('+table+')')]
            if {r[1] for r in db.execute('PRAGMA table_info('+table+')')}!=set(columns):raise ValueError('Initialize the current workflow schema before rehearsal.')
            ddl=re.sub(r'\bINTEGER PRIMARY KEY AUTOINCREMENT\b','BIGSERIAL PRIMARY KEY',schema[0])
            ddl=re.sub(r'\bREAL\b','DOUBLE PRECISION',ddl);ddl=re.sub(r'\bINTEGER\b','BIGINT',ddl)
            statements.append(ddl+';')
            # Names are a fixed internal allowlist; values use SQL literals, never shell interpolation.
            rows=db.execute('SELECT '+','.join('"'+c+'"' for c in columns)+' FROM '+table+' LIMIT 10001').fetchall()
            if len(rows)>10000:raise ValueError('Rehearsal snapshot exceeds the bounded row limit.')
            expected[table]=[dict(r) for r in rows]
            for row in rows:statements.append('INSERT INTO '+table+' VALUES ('+','.join(literal(v) for v in tuple(row))+');')
    finally:db.close();model.close()
    return '\n'.join(statements),expected


def rehearse(path):
    from scripts.rehearse_storage_adapter_postgres import _tools,RehearsalError
    try:directory=str(Path(_tools()['pg_ctl']).parent)
    except RehearsalError:raise ValueError('Local PostgreSQL tools are required.') from None
    bins={name:shutil.which(name,path=directory) for name in ('initdb','pg_ctl','psql')}
    if not all(bins.values()):raise ValueError('Local PostgreSQL tools are required.')
    sql,expected=export_state(path)
    with tempfile.TemporaryDirectory(prefix='r05-pg-',dir='/tmp') as directory:
        root=Path(directory);socket=root/'socket';socket.mkdir(mode=0o700);data=root/'data'
        env={k:v for k,v in os.environ.items() if not k.startswith('PG')};env.update(PGPASSFILE=str(root/'no-password-file'),PGSERVICEFILE=str(root/'no-service-file'))
        # macOS postmaster refuses to start without a valid locale ("became multithreaded during startup").
        env.update(LC_ALL='C',LANG='C')
        def run(args,*,input=None):
            result=subprocess.run(args,input=input,capture_output=True,text=True,env=env,timeout=45)  # noqa: S603 -- selected local PostgreSQL binaries, fixed flags and private fixture paths
            if result.returncode:raise RuntimeError('Isolated PostgreSQL rehearsal failed.')
            return result.stdout.strip()
        run([bins['initdb'],'-D',str(data),'--auth=trust','--no-locale','--encoding=UTF8'])
        started=False
        try:
            run([bins['pg_ctl'],'-D',str(data),'-l',str(root/'server.log'),'-o',"-k "+str(socket)+" -p 55439 -c listen_addresses=''",'-w','start']);started=True
            command=[bins['psql'],'-X','-h',str(socket),'-p','55439','-d','postgres','-v','ON_ERROR_STOP=1','-A','-t','-q']
            def query(value):return run(command,input='SET search_path=workflow_rehearsal; '+value)
            run(command,input=sql)
            def normalized(value):
                if isinstance(value,float) and value.is_integer():return int(value)
                if isinstance(value,list):return [normalized(v) for v in value]
                if isinstance(value,dict):return {k:normalized(v) for k,v in value.items()}
                return value
            def normalize(rows):return sorted(json.dumps(normalized(r),sort_keys=True,separators=(',',':')) for r in rows)
            counts={}
            for table,rows in expected.items():
                observed=json.loads(query("SELECT COALESCE(json_agg(t),'[]'::json) FROM "+table+' t;'))
                if normalize(observed)!=normalize(rows):raise AssertionError('Migration round-trip mismatch: '+table)
                counts[table]=len(rows)
            runs=expected['workflow_runs']
            if not runs:raise ValueError('A workflow run fixture is required.')
            identity=literal(runs[0]['id'])
            query("UPDATE workflow_runs SET status='queued',fence=0,owner=NULL,lease_until=0,deadline=EXTRACT(EPOCH FROM clock_timestamp())+25 WHERE id="+identity)
            def claim(i):
                return query("BEGIN; SELECT pg_advisory_xact_lock(52005); UPDATE workflow_runs SET status='running',owner="+literal('worker-'+str(i))+",fence=fence+1,lease_until=EXTRACT(EPOCH FROM clock_timestamp())+8 WHERE id="+identity+" AND status='queued' AND (SELECT COUNT(*) FROM workflow_runs WHERE status='running' AND lease_until>EXTRACT(EPOCH FROM clock_timestamp()))<4 RETURNING fence; COMMIT;")
            with ThreadPoolExecutor(max_workers=8) as pool:claims=list(pool.map(claim,range(8)))
            winners=sum('1' in c.splitlines() for c in claims)
            if winners!=1:raise AssertionError('Claim CAS must have exactly one winner.')
            stale=query("UPDATE workflow_runs SET status='succeeded' WHERE id="+identity+" AND owner='stale-worker' AND fence=0 RETURNING id;")
            if stale:raise AssertionError('A stale owner changed the result.')
            duplicate=query("WITH inserted AS (INSERT INTO workflow_result_outbox(id,run_id,destination_id,status,created) VALUES ('rehearsal-event',"+identity+",'fixture-destination','pending',0) ON CONFLICT(run_id) DO NOTHING RETURNING id) SELECT COUNT(*) FROM inserted;")
            duplicate2=query("WITH inserted AS (INSERT INTO workflow_result_outbox(id,run_id,destination_id,status,created) VALUES ('rehearsal-event-two',"+identity+",'fixture-destination','pending',0) ON CONFLICT(run_id) DO NOTHING RETURNING id) SELECT COUNT(*) FROM inserted;")
            if duplicate2!='0':raise AssertionError('Duplicate run outbox was admitted.')
            canary_winners=None;manual_duplicate_rejected=None
            if expected['workflow_fallback_policies']:
                wid=literal(expected['workflow_fallback_policies'][0]['workflow_id'])
                query('UPDATE workflow_fallback_policies SET admitted=0 WHERE workflow_id='+wid)
                def admit(_):return query('UPDATE workflow_fallback_policies SET admitted=admitted+1 WHERE workflow_id='+wid+' AND admitted<2 RETURNING admitted;')
                with ThreadPoolExecutor(max_workers=8) as pool:admissions=list(pool.map(admit,range(8)))
                canary_winners=sum(bool(value) for value in admissions)
                if canary_winners!=2:raise AssertionError('Canary CAS exceeded its admission cap.')
            if expected['workflow_manual_deliveries']:
                event=expected['workflow_manual_deliveries'][0]
                duplicate=query("WITH inserted AS (INSERT INTO workflow_manual_deliveries(id,run_id,source_event_id,payload,signature,status,created) VALUES ('manual-duplicate',"+literal(event['run_id'])+','+literal(event['source_event_id'])+",'{}','fixture','pending',0) ON CONFLICT(source_event_id) DO NOTHING RETURNING id) SELECT COUNT(*) FROM inserted;")
                manual_duplicate_rejected=duplicate=='0'
                if not manual_duplicate_rejected:raise AssertionError('Duplicate manual delivery was admitted.')
            return {'tables':counts,'round_trip_equal':True,'claim_contenders':8,'claim_winners':winners,'stale_owner_rejected':True,'duplicate_outbox_rejected':True,
                    'canary_cap':2 if canary_winners is not None else None,'canary_admission_winners':canary_winners,'duplicate_manual_delivery_rejected':manual_duplicate_rejected,
                    'transport':'private Unix socket; no TCP listener','scope':'execution/routing/operations state only; full Store/FTS/auth/production cutover not implemented','production_DB_writes':0,'provider_calls':0}
        finally:
            if started:run([bins['pg_ctl'],'-D',str(data),'-m','fast','-w','stop'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--db',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    result=rehearse(args.db);Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='tables'}))
