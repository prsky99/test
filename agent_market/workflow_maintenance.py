"""Explicit bounded retention; replay tombstones and unknown evidence are kept."""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import time
import os

SCHEMA='''
CREATE TABLE IF NOT EXISTS workflow_run_archives (
 run_id TEXT PRIMARY KEY,payload TEXT NOT NULL,signature TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS workflow_maintenance_events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,admin_id INTEGER NOT NULL,
 bodies_compacted INTEGER NOT NULL,metadata_pruned INTEGER NOT NULL,created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS workflow_retention_due ON workflow_runs(status,finished);
'''
BODY_DAYS=14
METADATA_DAYS=90


class Maintenance:
    def __init__(self,runtime):
        self.runtime,self.store=runtime,runtime.store
        with self.store._lock:self.store._db.executescript(SCHEMA)

    def candidates(self,db,cutoff,limit):
        return db.execute('''SELECT r.* FROM workflow_runs r
            WHERE r.status IN ('succeeded','failed','cancelled') AND r.finished<?
            AND r.execution_outcome IS NOT NULL AND r.execution_outcome!='unknown'
            AND NOT EXISTS (SELECT 1 FROM workflow_run_archives a WHERE a.run_id=r.id)
            AND NOT EXISTS (SELECT 1 FROM workflow_result_outbox o WHERE o.run_id=r.id AND o.status IN ('pending','claimed','dispatched','unknown'))
            AND NOT EXISTS (SELECT 1 FROM workflow_manual_deliveries m WHERE m.run_id=r.id AND m.status IN ('pending','claimed','dispatched','unknown'))
            ORDER BY r.finished LIMIT ?''',(cutoff,limit)).fetchall()

    def run(self,*,apply=False,limit=20,actor=0,now=None):
        if type(apply) is not bool or type(limit) is not int or not 1<=limit<=20:raise ValueError('Use a bounded retention batch of one to twenty runs.')
        now=time.time() if now is None else now
        with self.store.tx() as db:
            if apply:db.execute('UPDATE workflow_runs SET fence=fence WHERE id IN (SELECT run_id FROM workflow_run_archives LIMIT 1)')
            bodies=self.candidates(db,now-BODY_DAYS*86400,limit)
            metadata=db.execute('''SELECT r.id FROM workflow_runs r JOIN workflow_run_archives a ON a.run_id=r.id
                WHERE r.finished<? AND r.status IN ('succeeded','failed','cancelled') AND r.execution_outcome!='unknown'
                AND NOT EXISTS (SELECT 1 FROM workflow_result_outbox o WHERE o.run_id=r.id AND o.status IN ('pending','claimed','dispatched','unknown'))
                AND NOT EXISTS (SELECT 1 FROM workflow_manual_deliveries m WHERE m.run_id=r.id AND m.status IN ('pending','claimed','dispatched','unknown'))
                AND EXISTS (SELECT 1 FROM workflow_run_events e WHERE e.run_id=r.id)
                ORDER BY r.finished LIMIT ?''',(now-METADATA_DAYS*86400,limit)).fetchall()
            result={'dry_run':not apply,'body_days':BODY_DAYS,'metadata_days':METADATA_DAYS,
                    'body_candidates':len(bodies),'metadata_candidates':len(metadata),
                    'bodies_compacted':0,'metadata_pruned':0,'held_invalid_evidence':0,
                    'replay_tombstones_retained':True,'unknown_outcomes_retained':True,
                    'busy':bool(db.execute("SELECT 1 FROM workflow_runs WHERE status IN ('queued','running') LIMIT 1").fetchone()
                        or db.execute("SELECT 1 FROM workflow_result_outbox WHERE status IN ('claimed','dispatched') LIMIT 1").fetchone()
                        or db.execute("SELECT 1 FROM workflow_manual_deliveries WHERE status IN ('claimed','dispatched') LIMIT 1").fetchone())}
            if not apply:return result
            if result['busy']:return result
            started=time.monotonic()
            for row in bodies:
                if time.monotonic()-started>.5:break
                valid=hashlib.sha256(row['snapshot'].encode()).hexdigest()==row['digest']
                for cp in db.execute('SELECT node_id,payload,signature FROM workflow_checkpoints WHERE run_id=?',(row['id'],)):
                    try:
                        value=json.loads(cp['payload'])
                        if (not isinstance(value,dict) or value.get('audience')!='workflow-checkpoint-v1' or value.get('node_id')!=cp['node_id']
                                or value.get('run_id')!=row['id'] or value.get('digest')!=row['digest']
                                or not hmac.compare_digest(cp['signature'],self.runtime.authority.signature(value))):valid=False
                    except (ValueError,TypeError):valid=False
                if not valid:result['held_invalid_evidence']+=1;continue
                old=json.loads(row['result']) if row['result'] else {}
                proof={'audience':'workflow-retention-v1','run_id':row['id'],'digest':row['digest'],'status':row['status'],
                       'execution_outcome':row['execution_outcome'],'artifact_sha256':old.get('artifact_sha256'),
                       'result_sha256':hashlib.sha256((row['result'] or '').encode()).hexdigest(),
                       'snapshot_sha256':hashlib.sha256(row['snapshot'].encode()).hexdigest(),'created':now}
                db.execute('INSERT INTO workflow_run_archives VALUES (?,?,?,?)',(row['id'],json.dumps(proof),self.runtime.authority.signature(proof),now))
                summary={'ok':row['status']=='succeeded','run_id':row['id'],'workflow_id':row['workflow_id'],
                         'workflow_name':old.get('workflow_name','Archived workflow'),'status':row['status'],
                         'execution_outcome':row['execution_outcome'],'artifact_sha256':old.get('artifact_sha256'),
                         'retained_summary':True,'node_results':[],'step_results':[],
                         'message':'Detailed run content has expired under the retention policy.'}
                db.execute('UPDATE workflow_runs SET snapshot=?,result=? WHERE id=?',
                           (json.dumps({'id':row['workflow_id'],'name':summary['workflow_name'],'nodes':[],'edges':[],'retained_summary':True}),json.dumps(summary),row['id']))
                db.execute('DELETE FROM workflow_checkpoints WHERE run_id=?',(row['id'],))
                db.execute('UPDATE workflow_node_runs SET input=NULL,output=NULL,error=NULL WHERE run_id=?',(row['id'],))
                result['bodies_compacted']+=1
            # Never remove run IDs, actor/idempotency keys, attempt tombstones,
            # delivery IDs or reconciliation evidence to make replay possible.
            for row in metadata:
                if time.monotonic()-started>.5:break
                archive=db.execute('SELECT payload,signature FROM workflow_run_archives WHERE run_id=?',(row['id'],)).fetchone()
                try:
                    proof=json.loads(archive['payload'])
                    valid=isinstance(proof,dict) and proof.get('audience')=='workflow-retention-v1' and proof.get('run_id')==row['id'] and hmac.compare_digest(archive['signature'],self.runtime.authority.signature(proof))
                except (ValueError,TypeError):valid=False
                if not valid:result['held_invalid_evidence']+=1;continue
                for table in ('workflow_run_events','workflow_routing_attempts','workflow_routing_decisions','workflow_fallback_shadow','workflow_run_authority'):
                    db.execute('DELETE FROM '+table+' WHERE run_id=?',(row['id'],))  # fixed internal names only
                result['metadata_pruned']+=1
            # An unused version cannot be needed by a run, current delivery grant
            # or deployed app. Keep those references even beyond the body window.
            app_guard='AND NOT EXISTS (SELECT 1 FROM workflow_apps a WHERE a.workflow_id=v.workflow_id AND a.active=1)' if db.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_apps' AND type='table'").fetchone() else ''
            db.execute('''DELETE FROM workflow_versions WHERE rowid IN (SELECT v.rowid FROM workflow_versions v
                WHERE v.created<? AND NOT EXISTS (SELECT 1 FROM workflow_runs r WHERE r.workflow_id=v.workflow_id AND r.digest=v.digest AND r.status IN ('queued','running'))
                AND NOT EXISTS (SELECT 1 FROM workflow_runs r WHERE r.workflow_id=v.workflow_id AND r.digest=v.digest AND NOT EXISTS (SELECT 1 FROM workflow_run_archives a WHERE a.run_id=r.id))
                AND NOT EXISTS (SELECT 1 FROM workflow_delivery_grants g WHERE g.workflow_id=v.workflow_id AND g.digest=v.digest AND g.revoked IS NULL AND g.expires>?)
                '''+app_guard+''' LIMIT ?)''',(now-BODY_DAYS*86400,now,limit))
            db.execute('INSERT INTO workflow_maintenance_events(admin_id,bodies_compacted,metadata_pruned,created) VALUES (?,?,?,?)',
                       (actor,result['bodies_compacted'],result['metadata_pruned'],now))
            return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--db')
    parser.add_argument('--apply',action='store_true');parser.add_argument('--limit',type=int,default=20);args=parser.parse_args()
    backend=os.environ.get('APPLICATION_STORE_BACKEND','sqlite')
    if backend=='postgresql':
        from .application_runtime import open_runtime_storage
        from .execution_authority import Authority
        from types import SimpleNamespace
        storage=open_runtime_storage(None)
        try:
            maintenance=object.__new__(Maintenance);maintenance.store=storage.store;maintenance.runtime=None
            if args.apply:
                key=hmac.new(storage.store.workflow_key,b'workflow-results-v1',hashlib.sha256).digest()
                context=SimpleNamespace(store=storage.store,key=key,authority=Authority(storage.store,key))
                maintenance=Maintenance(context)
            print(json.dumps(maintenance.run(apply=args.apply,limit=args.limit)))
        finally:
            storage.close()
        return
    if backend!='sqlite':parser.error('Choose a supported application backend.')
    if not args.db:parser.error('--db is required for the SQLite backend.')
    if not Path(args.db).is_file():parser.error('An existing database is required.')
    from contextlib import contextmanager
    from types import SimpleNamespace
    import sqlite3
    if not args.apply:
        # Preview never initializes a Store, recovers a lease or writes a key.
        db=sqlite3.connect(Path(args.db).resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        class PreviewStore:
            @contextmanager
            def tx(self):yield db
        maintenance=object.__new__(Maintenance);maintenance.store=PreviewStore();maintenance.runtime=None
        try:print(json.dumps(maintenance.run(limit=args.limit)))
        finally:db.close()
    else:
        from .gateway.store import Store
        from .execution_authority import Authority
        from .concierge.task_updates import TaskUpdates
        store=Store(args.db);context=SimpleNamespace(store=store)
        context.key=hmac_key=hmac.new(TaskUpdates._load_key(context),b'workflow-results-v1',hashlib.sha256).digest()
        context.authority=Authority(store,hmac_key)
        try:print(json.dumps(Maintenance(context).run(apply=True,limit=args.limit)))
        finally:store._db.close()


if __name__=='__main__':main()
