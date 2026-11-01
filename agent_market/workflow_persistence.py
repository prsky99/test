"""Transactional workflow leases, signed checkpoints and a conservative outbox.

The catalog remains SQLite. This repository is the execution-storage boundary;
process-local futures are wakeups, never execution ownership or completion proof.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import sqlite3
import time

LEASE_SECONDS = 8
# A file-backed Store normally allows a writer to wait up to ten seconds.
# Its lease must outlive that valid wait plus scheduling/heartbeat margin.
# Run deadlines, cancellation and monotonic fences remain separate hard gates.
SQLITE_LEASE_SECONDS = 20
DELIVERY_LEASE_SECONDS = 60
_dispatch_guard = ContextVar('workflow_dispatch_guard', default=None)
SCHEMA = '''
CREATE TABLE IF NOT EXISTS workflow_execution_attempts (
 run_id TEXT NOT NULL,node_id TEXT NOT NULL,fence INTEGER NOT NULL,
 input_hash TEXT NOT NULL,status TEXT NOT NULL,prepared REAL NOT NULL,dispatched REAL,finished REAL,
 PRIMARY KEY(run_id,node_id));
CREATE TABLE IF NOT EXISTS workflow_checkpoints (
 run_id TEXT NOT NULL,node_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
 PRIMARY KEY(run_id,node_id));
CREATE TABLE IF NOT EXISTS workflow_result_outbox (
 id TEXT PRIMARY KEY,run_id TEXT NOT NULL UNIQUE,destination_id TEXT NOT NULL,
 status TEXT NOT NULL,owner TEXT,fence INTEGER NOT NULL DEFAULT 0,lease_until REAL NOT NULL DEFAULT 0,
 created REAL NOT NULL,finished REAL);
CREATE INDEX IF NOT EXISTS workflow_outbox_pending ON workflow_result_outbox(status,created);
CREATE TABLE IF NOT EXISTS workflow_run_events (
 run_id TEXT NOT NULL,sequence INTEGER NOT NULL,event TEXT NOT NULL,created REAL NOT NULL,
 PRIMARY KEY(run_id,sequence));
'''


class FenceLost(ValueError):
    error_code = 'POLICY_DENIED'


@contextmanager
def dispatch_scope(guard, *, extend=False):
    previous = _dispatch_guard.get() if extend else None
    def combined():
        guard()
        if previous is not None:previous()
    token = _dispatch_guard.set(combined if extend else guard)
    try:yield
    finally:_dispatch_guard.reset(token)


def before_dispatch():
    guard = _dispatch_guard.get()
    if guard:guard()


def has_dispatch_guard():
    """Native Edge delivery requires an existing durable execution fence."""
    return callable(_dispatch_guard.get())


class DurableRuns:
    def __init__(self, store):
        self.store = store
        with store._lock:
            store._db.executescript(SCHEMA)
            columns = {r[1] for r in store._db.execute('PRAGMA table_info(workflow_runs)')}
            for column, declaration in (('fence','INTEGER NOT NULL DEFAULT 0'),('deadline','REAL'),('execution_outcome','TEXT')):
                if column not in columns:
                    try:store._db.execute(f'ALTER TABLE workflow_runs ADD COLUMN {column} {declaration}')
                    except Exception:
                        if column not in {r[1] for r in store._db.execute('PRAGMA table_info(workflow_runs)')}:raise

    @staticmethod
    def uncertain_routes(db, run_id):
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_routing_attempts'").fetchone():
            db.execute("UPDATE workflow_routing_attempts SET status='unknown',reason='interrupted',finished=? WHERE run_id=? AND status='dispatched'", (time.time(),run_id))

    @staticmethod
    def event(db, run_id, name):
        db.execute('INSERT INTO workflow_run_events SELECT ?,COALESCE(MAX(sequence),0)+1,?,? FROM workflow_run_events WHERE run_id=?',
                   (run_id,name,time.time(),run_id))

    @staticmethod
    def owned(db, run_id, owner, fence, *, dispatch=False):
        db.execute('UPDATE workflow_runs SET fence=fence WHERE id=?',(run_id,))
        # Waiting for the writer reservation consumes real lease time. Never
        # admit an expired owner using a timestamp captured before that wait.
        now = time.time()
        row = db.execute('SELECT * FROM workflow_runs WHERE id=? AND owner=? AND fence=? AND status=\'running\' AND lease_until>?',
                         (run_id,owner,fence,now)).fetchone()
        if not row or row['deadline'] is not None and row['deadline']<=now or dispatch and row['cancel_requested']:
            raise FenceLost('Execution ownership is no longer current.')
        return row

    def claim(self, run_id, owner, seconds):
        with self.store.tx() as db:
            # Acquire SQLite's writer lock before inspecting shared capacity.
            db.execute('UPDATE workflow_runs SET fence=fence WHERE id=?',(run_id,))
            now=time.time()
            if db.execute("SELECT COUNT(*) FROM workflow_runs WHERE status='running' AND lease_until>?",(now,)).fetchone()[0]>=4:return None
            changed=db.execute("UPDATE workflow_runs SET status='running',started=COALESCE(started,?),deadline=COALESCE(deadline,?),owner=?,fence=fence+1,lease_until=? WHERE id=? AND status='queued'",
                               (now,now+seconds,owner,now+self.lease_seconds,run_id)).rowcount
            if not changed:return None
            self.event(db,run_id,'run.claimed')
            return dict(db.execute('SELECT * FROM workflow_runs WHERE id=?',(run_id,)).fetchone())

    @property
    def lease_seconds(self):
        return (SQLITE_LEASE_SECONDS if getattr(self.store,'backend','sqlite')!='postgresql'
                and self.store._path!=':memory:' else LEASE_SECONDS)

    @contextmanager
    def heartbeat_connection(self):
        # Open in the heartbeat thread and close when that worker ends. Keep the
        # existing synchronous durability level; only bound lock contention.
        if getattr(self.store, 'backend', 'sqlite') == 'postgresql':
            # The explicit backend owns connection creation and writer fencing.
            # Reuse its bounded native transaction instead of a SQLite filename.
            yield None
            return
        db=sqlite3.connect(self.store._path,timeout=.1) if self.store._path!=':memory:' else None
        try:
            if db is not None:db.execute('PRAGMA busy_timeout=100')
            yield db
        finally:
            if db is not None:db.close()

    def pulse(self, run_id, owner, fence, connection=None):
        def update(db):
            # Sample time only after acquiring the writer reservation, just as
            # claim/owned do. A heartbeat may never revive an expired lease
            # using a timestamp captured before waiting for another writer.
            db.execute('UPDATE workflow_runs SET fence=fence WHERE id=?',(run_id,))
            now=time.time()
            return bool(db.execute("UPDATE workflow_runs SET lease_until=? WHERE id=? AND owner=? AND fence=? AND status='running' AND lease_until>? AND deadline>?",
                                   (now+self.lease_seconds,run_id,owner,fence,now,now)).rowcount)
        if getattr(self.store, 'backend', 'sqlite') == 'postgresql':
            with self.store.tx() as db:
                return update(db)
        if self.store._path!=':memory:':
            if connection is not None:
                with connection:return update(connection)
            db=sqlite3.connect(self.store._path,timeout=.1)
            try:
                with db:return update(db)
            finally:db.close()
        if not self.store._lock.acquire(timeout=.05):return False
        try:
            if self.store._db.in_transaction:return False
            with self.store.tx() as db:return update(db)
        finally:self.store._lock.release()

    def prepare(self, run_id, owner, fence, node_id, input_hash):
        with self.store.tx() as db:
            self.owned(db,run_id,owner,fence,dispatch=True)
            row=db.execute('SELECT input_hash,status FROM workflow_execution_attempts WHERE run_id=? AND node_id=?',(run_id,node_id)).fetchone()
            if row and (row['input_hash']!=input_hash or row['status']!='prepared'):raise FenceLost('The saved attempt cannot be repeated.')
            db.execute("INSERT INTO workflow_execution_attempts VALUES (?,?,?,?,'prepared',?,NULL,NULL) ON CONFLICT(run_id,node_id) DO UPDATE SET fence=excluded.fence",
                       (run_id,node_id,fence,input_hash,time.time()))
            self.event(db,run_id,'attempt.prepared')

    def dispatch(self, run_id, owner, fence, node_id):
        with self.store.tx() as db:
            self.owned(db,run_id,owner,fence,dispatch=True)
            if not db.execute("UPDATE workflow_execution_attempts SET status='dispatched',dispatched=? WHERE run_id=? AND node_id=? AND fence=? AND status='prepared'",
                              (time.time(),run_id,node_id,fence)).rowcount:raise FenceLost('The attempt was already dispatched.')
            self.event(db,run_id,'attempt.dispatched')

    def checkpoint(self, run_id, owner, fence, node_id, payload, signature, record):
        with self.store.tx() as db:
            self.owned(db,run_id,owner,fence)
            db.execute('INSERT INTO workflow_checkpoints VALUES (?,?,?,?)',(run_id,node_id,payload,signature))
            prior=db.execute('SELECT status FROM workflow_execution_attempts WHERE run_id=? AND node_id=?',(run_id,node_id)).fetchone()
            certainty='succeeded' if record['status']=='succeeded' else 'unknown' if prior and prior[0]=='dispatched' else 'failed'
            db.execute('UPDATE workflow_execution_attempts SET status=?,finished=? WHERE run_id=? AND node_id=?',(certainty,time.time(),run_id,node_id))
            db.execute('INSERT OR REPLACE INTO workflow_node_runs VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (run_id,node_id,record['status'],record['attempts'],record['started'],time.time(),json.dumps(record['input']),json.dumps(record['data']),record['error'],record['latency_ms']))
            self.event(db,run_id,'node.checkpointed')

    def finish(self, run_id, owner, fence, result, delivery=None):
        with self.store.tx() as db:
            row=self.owned(db,run_id,owner,fence)
            if row['cancel_requested'] and result['status']!='cancelled':raise FenceLost('Cancellation changed the final outcome.')
            uncertain=db.execute("SELECT 1 FROM workflow_execution_attempts WHERE run_id=? AND status='unknown'",(run_id,)).fetchone()
            result['execution_outcome']='unknown' if uncertain else result['status']
            db.execute('UPDATE workflow_runs SET status=?,execution_outcome=?,finished=?,result=?,lease_until=0 WHERE id=? AND owner=? AND fence=?',
                       (result['status'],result['execution_outcome'],time.time(),json.dumps(result,separators=(',',':')),run_id,owner,fence))
            db.execute('UPDATE agent_workflows SET runs_count=runs_count+1 WHERE id=?',(row['workflow_id'],))
            if delivery:
                db.execute("INSERT INTO workflow_result_outbox(id,run_id,destination_id,status,created) VALUES (?,?,?,'pending',?) ON CONFLICT(run_id) DO NOTHING",
                           (delivery['id'],run_id,delivery['destination_id'],time.time()))
                self.event(db,run_id,'delivery.queued')
            self.event(db,run_id,'run.completed')

    def fail_owned(self, run_id, owner, fence):
        # Invalidate first; no result from this owner may commit afterward.
        with self.store.tx() as db:
            db.execute('UPDATE workflow_runs SET fence=fence WHERE id=?',(run_id,))
            row=db.execute("SELECT cancel_requested FROM workflow_runs WHERE id=? AND owner=? AND fence=? AND status='running'",(run_id,owner,fence)).fetchone()
            if not row:return
            uncertain=db.execute("SELECT 1 FROM workflow_execution_attempts WHERE run_id=? AND status IN ('dispatched','unknown')",(run_id,)).fetchone()
            state='cancelled' if row[0] else 'failed'
            db.execute("UPDATE workflow_runs SET status=?,execution_outcome=?,fence=fence+1,lease_until=0,finished=?,error='Execution interrupted; review before retrying.' WHERE id=?",
                       (state,'unknown' if uncertain else state,time.time(),run_id))
            db.execute("UPDATE workflow_execution_attempts SET status='unknown',finished=? WHERE run_id=? AND status='dispatched'",(time.time(),run_id))
            self.uncertain_routes(db,run_id)
            db.execute("UPDATE workflow_node_runs SET status=?,error='Execution interrupted; review before retrying.' WHERE run_id=? AND status='running'",('unknown' if uncertain else state,run_id))
            self.event(db,run_id,'run.reconciliation_required' if uncertain else 'run.interrupted')

    def recover(self):
        now=time.time();recovered=0
        with self.store.tx() as db:
            db.execute("UPDATE workflow_deliveries SET status='uncertain',finished=?,error='Delivery interrupted; inspect before retrying.' WHERE status='sending' AND created<? AND NOT EXISTS (SELECT 1 FROM workflow_result_outbox o WHERE o.id=workflow_deliveries.id)",(now,now-120))
            db.execute('UPDATE workflow_runs SET fence=fence WHERE status=\'running\' AND (lease_until<=? OR deadline<=?)',(now,now))
            for row in db.execute("SELECT * FROM workflow_runs WHERE status='running' AND (lease_until<=? OR deadline<=?) LIMIT 100",(now,now)).fetchall():
                run_id=row['id']
                uncertain=db.execute("SELECT 1 FROM workflow_execution_attempts WHERE run_id=? AND status IN ('dispatched','unknown')",(run_id,)).fetchone()
                # Legacy interrupted executions have no proof of pre-dispatch state.
                legacy=row['deadline'] is None
                terminal=bool(uncertain or legacy or row['cancel_requested'] or row['deadline']<=now)
                state='cancelled' if row['cancel_requested'] else 'failed' if terminal else 'queued'
                outcome='unknown' if uncertain or legacy else state
                db.execute('UPDATE workflow_runs SET status=?,execution_outcome=?,owner=NULL,fence=fence+1,lease_until=0,finished=?,error=? WHERE id=?',
                           (state,outcome,now if terminal else None,'Execution interrupted; outcome unknown. Review before retrying.' if outcome=='unknown' else 'Execution interrupted; time limit or cancellation reached.' if terminal else None,run_id))
                if uncertain:db.execute("UPDATE workflow_execution_attempts SET status='unknown',finished=? WHERE run_id=? AND status='dispatched'",(now,run_id))
                if terminal:self.uncertain_routes(db,run_id)
                db.execute("UPDATE workflow_node_runs SET status=?,error='Execution interrupted; review before retrying.' WHERE run_id=? AND status='running'",('unknown' if uncertain or legacy else 'queued',run_id))
                self.event(db,run_id,'run.reconciliation_required' if outcome=='unknown' else 'run.interrupted' if terminal else 'run.resumable')
                recovered+=1
            for row in db.execute("SELECT * FROM workflow_result_outbox WHERE status IN ('claimed','dispatched') AND lease_until<=? LIMIT 100",(now,)).fetchall():
                state='pending' if row['status']=='claimed' else 'unknown'
                db.execute('UPDATE workflow_result_outbox SET status=?,owner=NULL,fence=fence+1,lease_until=0,finished=? WHERE id=?',(state,now if state=='unknown' else None,row['id']))
                if state=='unknown':
                    db.execute("UPDATE workflow_deliveries SET status='uncertain',finished=?,error='Delivery outcome unknown; do not resend automatically.' WHERE id=?",(now,row['id']))
                    self.distribution(db,row['run_id'],{'status':'UNKNOWN','event_id':row['id']})
                    self.event(db,row['run_id'],'delivery.unknown')
        return recovered

    @staticmethod
    def distribution(db, run_id, value):
        row=db.execute('SELECT result FROM workflow_runs WHERE id=?',(run_id,)).fetchone()
        if row and row[0]:
            result=json.loads(row[0]);result['final_deliverable']['distribution']=value
            db.execute('UPDATE workflow_runs SET result=? WHERE id=?',(json.dumps(result,separators=(',',':')),run_id))

    def claim_delivery(self, event_id, owner):
        with self.store.tx() as db:
            changed=db.execute("UPDATE workflow_result_outbox SET status='claimed',owner=?,fence=fence+1,lease_until=? WHERE id=? AND status='pending'",(owner,time.time()+DELIVERY_LEASE_SECONDS,event_id)).rowcount
            return dict(db.execute('SELECT * FROM workflow_result_outbox WHERE id=?',(event_id,)).fetchone()) if changed else None

    def delivery_dispatch(self, row):
        with self.store.tx() as db:
            changed=db.execute("UPDATE workflow_result_outbox SET status='dispatched' WHERE id=? AND owner=? AND fence=? AND status='claimed' AND lease_until>?",
                               (row['id'],row['owner'],row['fence'],time.time())).rowcount
            if not changed:raise FenceLost('Delivery ownership changed.')
            db.execute("INSERT INTO workflow_deliveries VALUES (?,?,?,'sending',1,?,NULL,NULL) ON CONFLICT(run_id,destination_id) DO UPDATE SET status='sending'",
                       (row['id'],row['run_id'],row['destination_id'],time.time()))
            self.event(db,row['run_id'],'delivery.dispatched')

    def delivery_finish(self, row, status, distribution):
        with self.store.tx() as db:
            changed=db.execute("UPDATE workflow_result_outbox SET status=?,finished=?,lease_until=0 WHERE id=? AND owner=? AND fence=? AND status IN ('claimed','dispatched') AND lease_until>?",
                               (status,time.time(),row['id'],row['owner'],row['fence'],time.time())).rowcount
            if not changed:raise FenceLost('Delivery completion is no longer current.')
            db.execute("INSERT INTO workflow_deliveries VALUES (?,?,?,?,1,?,?,?) ON CONFLICT(run_id,destination_id) DO UPDATE SET status=excluded.status,finished=excluded.finished,error=excluded.error",
                       (row['id'],row['run_id'],row['destination_id'],'uncertain' if status=='unknown' else status,time.time(),time.time(),None if status=='accepted' else 'POLICY_DENIED' if status=='denied' else 'Delivery outcome unknown.'))
            self.distribution(db,row['run_id'],distribution)
            self.event(db,row['run_id'],'delivery.'+status)

    def inspect(self, run_id):
        runs=self.store.query('SELECT status,execution_outcome,fence,deadline,lease_until FROM workflow_runs WHERE id=?',(run_id,))
        if not runs:return None
        return {'run':dict(runs[0]),'attempts':[dict(r) for r in self.store.query('SELECT node_id,status,prepared,dispatched,finished FROM workflow_execution_attempts WHERE run_id=?',(run_id,))],
                'events':[dict(r) for r in self.store.query('SELECT sequence,event,created FROM workflow_run_events WHERE run_id=? ORDER BY sequence DESC LIMIT 300',(run_id,))][::-1],
                'deliveries':[dict(r) for r in self.store.query('SELECT id,status,created,finished FROM workflow_result_outbox WHERE run_id=?',(run_id,))]}
