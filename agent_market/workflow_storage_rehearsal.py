"""Explicit, disposable SQLite storage/retention/recovery rehearsal.

No caller database, server or external provider is accepted. Timings describe
this synthetic SQL fixture, not workflow throughput, production capacity or SLA.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time

PROFILE = 'workflow-storage-load-rehearsal-v1'
SEED = 20261018
PREFIX = 'agentconcierge-storage-rehearsal-'
DEFAULTS = {'iterations':12,'readers':2,'writers':2}
LIMITS = {'isolated_only':True,'synthetic':True,'fixed_seed':SEED,'completed_fixture_runs':8,
          'max_iterations':50,'max_readers':4,'max_writers':4,'load_budget_seconds':5,
          'sql_busy_timeout_ms':20,'backup_progress_budget_seconds':30,'physical_progress_budget_seconds':5,'global_hard_deadline':False,
          'max_idle_batches':2,'body_batch_limit':20,'metadata_batch_limit':1,'retention_clock_days_after_fixture':91,
          'external_provider_calls':0,'production_actions':0,'establishes_sla':False,
          'load_scope':'separate_sqlite_fixture_connections','workflow_throughput_measured':False}
PHASES = {'fixture','durable','load','maintenance','backup_restore','physical_compaction'}
CHECKS = {'fixture_valid','durable_contracts_preserved','reader_snapshots_consistent','sql_write_accounting',
          'busy_writer_refused','maintenance_busy_refused','idle_batch_bounded','retention_invariants',
          'storage_observation_complete','workflow_queue_unchanged','source_integrity','restored_integrity','restore_authorities_paused','restore_invariants',
          'physical_integrity','physical_logical_state_preserved','temporary_workspace_removed'}
REPLAY_QUERIES = (
    'SELECT id,workflow_id,digest,actor,source,status,execution_outcome,idempotency_key,access_hash FROM workflow_runs ORDER BY id',
    'SELECT * FROM workflow_run_authority ORDER BY run_id',
    'SELECT * FROM workflow_execution_attempts ORDER BY run_id,node_id',
    'SELECT * FROM workflow_checkpoints ORDER BY run_id,node_id',
    'SELECT * FROM workflow_run_archives ORDER BY run_id',
    'SELECT * FROM workflow_result_outbox ORDER BY id',
    'SELECT * FROM workflow_delivery_grants ORDER BY id',
    'SELECT * FROM workflow_apps ORDER BY id',
    'SELECT * FROM workflow_deployment_grants ORDER BY id',
    'SELECT * FROM workflow_publication_grants ORDER BY id',
    'SELECT * FROM workflow_connection_deployments ORDER BY id',
    'SELECT * FROM workflow_connection_automation ORDER BY id',
    'SELECT * FROM workflow_connection_automation_admissions ORDER BY grant_id,slot',
    'SELECT * FROM execution_controls ORDER BY id',
    'SELECT * FROM workflow_manual_deliveries ORDER BY id',
    'SELECT * FROM workflow_event_receipts ORDER BY workflow_id,event_id',
    'SELECT * FROM workflow_destinations ORDER BY id',
)

DURABLE_CHECKS = frozenset(['dispatched_recovered_unknown', 'no_provider_or_model_call', 'one_claim_owner', 'stale_fence_denied', 'unknown_not_reclaimed'])
RETENTION_CHECKS = frozenset(['archive_signatures_valid', 'archived_checkpoints_removed', 'archived_literal_cannot_certify_publication', 'archived_source_cannot_prepare_sdk13_run', 'archived_source_cannot_reauthorize_public_connection', 'archived_source_cannot_supply_comparison', 'attempt_tombstones_retained', 'event_replay_receipts_retained', 'expired_metadata_removed_without_replay_reset', 'invalid_checkpoint_held', 'no_external_or_fixture_agent_calls', 'pending_delivery_bodies_held', 'replay_tombstones_retained', 'unknown_outcomes_unchanged', 'withdrawal_tombstones_retained'])
RESTORE_CHECKS = frozenset(['all_execution_controls_paused', 'all_grant_revisions_advanced', 'all_purpose_grants_inactive', 'automation_grants_unscheduled', 'automation_new_event_rejected', 'old_admin_sessions_removed', 'pending_deliveries_quarantined', 'private_inventory_bounded_without_secrets', 'public_old_run_key_rejected', 'retained_public_ticket_not_replayed', 'queued_and_prepared_quarantined_unknown', 'replay_tombstones_retained', 'sdk12_old_capability_rejected', 'sdk13_old_key_rejected', 'retained_sdk13_ticket_not_replayed', 'signed_archives_retained', 'verification_read_only', 'verified_destination_revoked'])

def _checks(value,expected):
    return isinstance(value,dict) and set(value)==expected and all(item is True for item in value.values())


class RehearsalError(ValueError):
    def __init__(self, code='rehearsal_failed'):
        self.code=code if code in ('rehearsal_failed','configured_key_environment','invariant_failed','invalid_configuration') else 'rehearsal_failed'
        super().__init__(self.code)


def _configuration(iterations,readers,writers):
    if any(type(value) is not int or not 1<=value<=maximum for value,maximum in ((iterations,50),(readers,4),(writers,4))):
        raise RehearsalError('invalid_configuration')


def _build_fixture(directory):
    from .workflow_storage_fixtures import synthetic_fixture
    return synthetic_fixture(directory,seed=SEED,completed=8)


def _busy(exc):
    return getattr(exc,'sqlite_errorcode',-1)&255 in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED)


def _connection(path, *, read=False, timeout=.02):
    target=Path(path).as_uri()+'?mode=ro' if read else str(path)
    db=sqlite3.connect(target,uri=read,timeout=timeout)
    db.execute('PRAGMA busy_timeout=20')
    if read:db.execute('PRAGMA query_only=ON')
    else:db.execute('PRAGMA wal_autocheckpoint=0')
    return db


def _percentile(values,fraction):
    if not values:return None
    ordered=sorted(values)
    return round(ordered[max(0,math.ceil(len(ordered)*fraction)-1)],3)


def _load(fixture,iterations,readers,writers):
    """Only bounded SQL fixture traffic; these are not workflow worker rates."""
    phase_started=time.monotonic();path=Path(fixture.store._path)
    with fixture.store.tx() as db:
        db.execute('CREATE TABLE storage_rehearsal_counters(worker INTEGER PRIMARY KEY,n INTEGER NOT NULL)')
        db.executemany('INSERT INTO storage_rehearsal_counters VALUES (?,0)',[(i,) for i in range(writers)])
    deterministic_refusals=0;holder=_connection(path);probe=None
    try:
        holder.execute('BEGIN IMMEDIATE');probe=_connection(path)
        try:probe.execute('UPDATE storage_rehearsal_counters SET n=n+1 WHERE worker=0')
        except sqlite3.OperationalError as exc:
            if not _busy(exc):raise
            deterministic_refusals=1
        else:raise RehearsalError('invariant_failed')
        finally:probe.rollback()
    finally:
        if probe is not None:probe.close()
        holder.rollback();holder.close()
    start=time.monotonic();deadline=start+5;barrier=threading.Barrier(readers+writers)
    def work(index,writer):
        db=_connection(path,read=not writer);metrics={'commits':0,'busy':0,'skipped':0,'consistent':True,'latencies':[]}
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        try:
            barrier.wait(timeout=2)
            for ordinal in range(iterations):
                if time.monotonic()>deadline:
                    metrics['skipped']=iterations-ordinal;break
                began=time.monotonic()
                try:
                    if writer:
                        db.execute('BEGIN IMMEDIATE')
                        changed=db.execute('UPDATE storage_rehearsal_counters SET n=n+1 WHERE worker=?',(index,)).rowcount
                        if changed!=1:raise RehearsalError('invariant_failed')
                    else:
                        db.execute('BEGIN')
                        one=db.execute('SELECT COUNT(*),SUM(n) FROM storage_rehearsal_counters').fetchone()
                        two=db.execute('SELECT COUNT(*),SUM(n) FROM storage_rehearsal_counters').fetchone()
                        if one!=two or one[0]!=writers or not 0<=one[1]<=iterations*writers:raise RehearsalError('invariant_failed')
                    db.commit();metrics['commits']+=1
                except sqlite3.OperationalError as exc:
                    db.rollback()
                    if _busy(exc):metrics['busy']+=1
                    elif time.monotonic()>deadline:
                        metrics['skipped']=iterations-ordinal;break
                    else:raise
                finally:metrics['latencies'].append((time.monotonic()-began)*1000)
            return metrics
        finally:db.close()
    with ThreadPoolExecutor(max_workers=readers+writers,thread_name_prefix='storage-rehearsal') as pool:
        futures=[pool.submit(work,i,True) for i in range(writers)]+[pool.submit(work,i,False) for i in range(readers)]
        values=[f.result(timeout=8) for f in futures]
    write=values[:writers];read=values[writers:];committed=sum(v['commits'] for v in write)
    rows=fixture.store.query('SELECT SUM(n) AS n FROM storage_rehearsal_counters')
    write_times=[latency for v in write for latency in v['latencies']];read_times=[latency for v in read for latency in v['latencies']]
    return {'scope':'sql_fixture_contention_only','iterations':iterations,'readers':readers,'writers':writers,
            'attempted_writes':iterations*writers,'committed_writes':committed,'busy_writes':sum(v['busy'] for v in write),
            'budget_skipped_writes':sum(v['skipped'] for v in write),'reader_snapshots':sum(v['commits'] for v in read),
            'busy_reads':sum(v['busy'] for v in read),'budget_skipped_reads':sum(v['skipped'] for v in read),
            'deterministic_busy_refusals':deterministic_refusals,'elapsed_ms':round((time.monotonic()-phase_started)*1000,3),
            'write_p50_ms':_percentile(write_times,.5),'write_p95_ms':_percentile(write_times,.95),
            'read_p50_ms':_percentile(read_times,.5),'read_p95_ms':_percentile(read_times,.95),
            'accounted_writes':rows[0]['n']==committed and sum(v['commits']+v['busy']+v['skipped'] for v in write)==iterations*writers,
            'consistent_reads':all(v['consistent'] for v in read)}


def _integrity(path):
    db=_connection(Path(path),read=True);deadline=time.monotonic()+3
    try:
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        return db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
    finally:db.close()


def _logical_state(path):
    db=_connection(Path(path),read=True);result=hashlib.sha256();deadline=time.monotonic()+3
    try:
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000);db.execute('BEGIN')
        for query in REPLAY_QUERIES:
            rows=db.execute(query).fetchall()
            if len(rows)>1000:raise RehearsalError('invariant_failed')
            result.update(json.dumps(rows,ensure_ascii=True,allow_nan=False,separators=(',',':')).encode())
        return result.hexdigest()
    finally:db.close()


def _paused(path):
    db=_connection(Path(path),read=True)
    try:
        controls=db.execute('SELECT invoke_enabled,workflow_enabled,delivery_enabled FROM execution_controls WHERE id=1').fetchone()
        active=(db.execute('SELECT COUNT(*) FROM workflow_apps WHERE active=1').fetchone()[0]
                +db.execute('SELECT COUNT(*) FROM workflow_deployment_grants WHERE active=1').fetchone()[0]
                +db.execute('SELECT COUNT(*) FROM workflow_publication_grants WHERE active=1').fetchone()[0]
                +db.execute('SELECT COUNT(*) FROM workflow_connection_deployments WHERE active=1').fetchone()[0]
                +db.execute('SELECT COUNT(*) FROM workflow_connection_automation WHERE active=1').fetchone()[0]
                +db.execute('SELECT COUNT(*) FROM workflow_schedules WHERE enabled=1').fetchone()[0]
                +db.execute('SELECT COUNT(*) FROM workflow_delivery_grants WHERE revoked IS NULL').fetchone()[0])
        return controls==(0,0,0) and active==0
    finally:db.close()


def _physical_compaction(path):
    from .workflow_storage import observe
    if not _paused(path):raise RehearsalError('invariant_failed')
    before=observe(path);logical=_logical_state(path);integrity_before=_integrity(path)
    start=time.monotonic();db=_connection(Path(path),timeout=.1);deadline=start+5
    try:
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]!=0:raise RehearsalError('invariant_failed')
        db.execute('VACUUM')
        if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]!=0:raise RehearsalError('invariant_failed')
    finally:db.close()
    return {'performed':True,'disposable_restored_copy':True,'controls_paused':True,'wal_checkpoint_performed':True,
            'elapsed_ms':round((time.monotonic()-start)*1000,3),'before':before,'after':observe(path),
            'integrity_before':integrity_before,'integrity_after':_integrity(path),
            'critical_workflow_state_unchanged':logical==_logical_state(path)}


def run_rehearsal(*,iterations=12,readers=2,writers=2):
    _configuration(iterations,readers,writers)
    if 'AGENT_UPDATES_KEY' in os.environ:raise RehearsalError('configured_key_environment')
    from .workflow_storage import observe
    from .workflow_backup import backup,restore
    fixture=None;start=time.monotonic();workspace=None
    try:
        with tempfile.TemporaryDirectory(prefix=PREFIX) as directory:
            workspace=Path(directory)
            try:
                fixture_start=time.monotonic();fixture=_build_fixture(workspace/'fixture')
                fixture_summary={**fixture.safe_summary(),'elapsed_ms':round((time.monotonic()-fixture_start)*1000,3)};durable=fixture.exercise_durable()
                if not _checks(durable.get('invariants'),DURABLE_CHECKS):raise RehearsalError('invariant_failed')
                before=observe(fixture.store._path);load=_load(fixture,iterations,readers,writers);after=observe(fixture.store._path)
                maintenance_start=time.monotonic();busy_preview=fixture.runtime.maintenance.run(now=fixture.retention_now);busy_apply=fixture.runtime.maintenance.run(apply=True,now=fixture.retention_now)
                fixture.prepare_idle();captured=fixture.capture()
                idle_preview=fixture.runtime.maintenance.run(limit=20,now=fixture.retention_now)
                idle_apply=fixture.runtime.maintenance.run(apply=True,limit=20,now=fixture.retention_now)
                metadata_preview=fixture.runtime.maintenance.run(limit=1,now=fixture.retention_now)
                metadata_apply=fixture.runtime.maintenance.run(apply=True,limit=1,now=fixture.retention_now)
                remaining_preview=fixture.runtime.maintenance.run(limit=20,now=fixture.retention_now)
                retained=fixture.verify_compaction(captured)
                if not _checks(retained,RETENTION_CHECKS):raise RehearsalError('invariant_failed')
                maintenance_elapsed=round((time.monotonic()-maintenance_start)*1000,3)
                source_integrity=_integrity(fixture.store._path)
                restore_boundary=fixture.prepare_restore()
                backup_start=time.monotonic();backup(fixture.store._path,workspace/'backup');backup_ms=(time.monotonic()-backup_start)*1000
                restore_start=time.monotonic();target=workspace/'restored.sqlite3';restore(workspace/'backup',target);restore_ms=(time.monotonic()-restore_start)*1000
                inventory=json.loads(Path(str(target)+'.restored-inventory.json').read_text());restored=fixture.verify_restore(target,inventory)
                if not _checks(restored,RESTORE_CHECKS):raise RehearsalError('invariant_failed')
                physical=_physical_compaction(target)
                checks={'fixture_valid':fixture_summary['valid'] is True,'durable_contracts_preserved':_checks(durable['invariants'],DURABLE_CHECKS),
                        'reader_snapshots_consistent':load['consistent_reads'] is True,'sql_write_accounting':load['accounted_writes'] is True,
                        'busy_writer_refused':load['deterministic_busy_refusals']==1,'maintenance_busy_refused':busy_apply['busy'] is True and busy_apply['bodies_compacted']==0,
                        'idle_batch_bounded':idle_apply['busy'] is False and 1<=idle_apply['bodies_compacted']<=20
                            and metadata_apply['busy'] is False and metadata_apply['metadata_pruned']==1
                            and metadata_apply['bodies_compacted']<=1,
                        'retention_invariants':_checks(retained,RETENTION_CHECKS),
                        'storage_observation_complete':before['coverage']['complete'] is True and after['coverage']['complete'] is True,
                        'workflow_queue_unchanged':before['workflow_counts']==after['workflow_counts'],'source_integrity':source_integrity,
                        'restored_integrity':_integrity(target),'restore_authorities_paused':_paused(target),
                        'restore_invariants':_checks(restored,RESTORE_CHECKS),
                        'physical_integrity':physical['integrity_before'] and physical['integrity_after'],
                        'physical_logical_state_preserved':physical['critical_workflow_state_unchanged'] is True}
                phases={'fixture':fixture_summary,'durable':durable,'load':{**load,'before':before,'after':after},
                        'maintenance':{'busy_preview':busy_preview,'busy_apply':busy_apply,'idle_preview':idle_preview,'idle_apply':idle_apply,
                                       'metadata_preview':metadata_preview,'metadata_apply':metadata_apply,'remaining_preview':remaining_preview,
                                       'remaining_preview_limit':20,'all_aged_metadata_cleared':False,
                                       'invariants':retained,'elapsed_ms':maintenance_elapsed},
                        'backup_restore':{'backup_elapsed_ms':round(backup_ms,3),'restore_elapsed_ms':round(restore_ms,3),'invariants':restored,'synthetic_restore_boundary':restore_boundary,
                                          'inventory_counts':{table:item['count'] for table,item in inventory['items'].items()}},
                        'physical_compaction':physical}
            finally:
                if fixture is not None:fixture.close()
        checks['temporary_workspace_removed']=not workspace.exists()
        if set(checks)!=CHECKS or not all(value is True for value in checks.values()):raise RehearsalError('invariant_failed')
        return {'ok':True,'profile':PROFILE,'elapsed_ms':round((time.monotonic()-start)*1000,3),
                'phases':phases,'invariants':checks,'limits':dict(LIMITS)}
    except RehearsalError:raise
    except Exception:raise RehearsalError() from None


class UsageError(ValueError):pass


class Parser(argparse.ArgumentParser):
    def error(self,message):raise UsageError('invalid_arguments')


class Once(argparse.Action):
    def __call__(self,parser,namespace,values,option_string=None):
        marker='_seen_'+self.dest
        if getattr(namespace,marker,False):raise UsageError('invalid_arguments')
        setattr(namespace,marker,True);setattr(namespace,self.dest,True if self.nargs==0 else values)


def _report_parent(value):
    if not isinstance(value,str) or not value or '\0' in value:raise UsageError('invalid_report_path')
    path=Path(os.path.abspath(value));parts=path.parts
    if any(part in ('.','..') for part in Path(value).parts) or path.name in ('','.', '..'):raise UsageError('invalid_report_path')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in parts[1:-1]:
            following=os.open(part,os.O_RDONLY|os.O_DIRECTORY|getattr(os,'O_NOFOLLOW',0),dir_fd=fd)
            os.close(fd);fd=following
        try:os.stat(parts[-1],dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError:return fd,parts[-1]
        raise UsageError('invalid_report_path')
    except Exception:
        os.close(fd);raise UsageError('invalid_report_path') from None


def _write_report(parent,name,data):
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600,dir_fd=parent)
    original=os.fstat(fd)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as target:
            os.fchmod(target.fileno(),0o600);target.write(data);target.flush();os.fsync(target.fileno())
    except Exception:
        try:
            current=os.stat(name,dir_fd=parent,follow_symlinks=False)
            if current.st_dev==original.st_dev and current.st_ino==original.st_ino:os.unlink(name,dir_fd=parent)
        except OSError:pass
        raise


def main(argv=None):
    parser=Parser(prog='rehearse_workflow_storage',description=__doc__,allow_abbrev=False)
    parser.add_argument('--run',action=Once,nargs=0,default=False)
    for name,default in DEFAULTS.items():parser.add_argument('--'+name,type=int,action=Once,default=default)
    parser.add_argument('--report',action=Once)
    parent=None;name=None;status=0
    try:
        args=parser.parse_args(argv)
        if args.run is not True:raise UsageError('invalid_arguments')
        try:_configuration(args.iterations,args.readers,args.writers)
        except RehearsalError:raise UsageError('invalid_arguments') from None
        if args.report is not None:parent,name=_report_parent(args.report)
        result=run_rehearsal(iterations=args.iterations,readers=args.readers,writers=args.writers)
        if (not isinstance(result,dict) or set(result)!={'ok','profile','elapsed_ms','phases','invariants','limits'}
                or result.get('ok') is not True or result.get('profile')!=PROFILE or set(result.get('phases',{}))!=PHASES
                or set(result.get('invariants',{}))!=CHECKS or not all(value is True for value in result['invariants'].values())):
            raise RehearsalError('invariant_failed')
    except UsageError:
        result={'ok':False,'profile':PROFILE,'error':'invalid_arguments_or_report'};status=2
    except RehearsalError as exc:
        result={'ok':False,'profile':PROFILE,'error':exc.code};status=1
    except Exception:
        result={'ok':False,'profile':PROFILE,'error':'rehearsal_failed'};status=1
    try:
        encoded=json.dumps(result,sort_keys=True,allow_nan=False)+'\n'
        if parent is not None and status!=2:_write_report(parent,name,encoded)
    except Exception:
        encoded=json.dumps({'ok':False,'profile':PROFILE,'error':'report_unavailable'},sort_keys=True)+'\n';status=2
    finally:
        if parent is not None:os.close(parent)
    print(encoded,end='')
    return status


if __name__=='__main__':raise SystemExit(main())
