"""Audited reconciliation and explicit, single-result resend authorization.

An operator statement never changes the original unknown transport outcome.
Every resend is a new bounded delivery, with a separate signed permission.
"""
import hashlib
import hmac
import json
import re
import secrets
import time

from .workflow_persistence import dispatch_scope, FenceLost
from .observability import stable_reference,attempt_scope,provider_dispatch

SCHEMA='''
CREATE TABLE IF NOT EXISTS workflow_reconciliation_events (
 run_id TEXT NOT NULL,subject TEXT NOT NULL,revision INTEGER NOT NULL,
 payload TEXT NOT NULL,signature TEXT NOT NULL,created REAL NOT NULL,
 PRIMARY KEY(run_id,subject,revision));
CREATE TABLE IF NOT EXISTS workflow_manual_deliveries (
 id TEXT PRIMARY KEY,run_id TEXT NOT NULL,source_event_id TEXT NOT NULL UNIQUE,
 payload TEXT NOT NULL,signature TEXT NOT NULL,status TEXT NOT NULL,
 owner TEXT,fence INTEGER NOT NULL DEFAULT 0,lease_until REAL NOT NULL DEFAULT 0,
 created REAL NOT NULL,finished REAL);
CREATE INDEX IF NOT EXISTS workflow_manual_run ON workflow_manual_deliveries(run_id,status);
'''
RECONCILE='workflow-reconciliation-v1'
RESEND='workflow-manual-resend-v1'


class Operations:
    def __init__(self,runtime):
        self.runtime,self.store=runtime,runtime.store
        with self.store._lock:self.store._db.executescript(SCHEMA)

    def verified(self,row):
        p=json.loads(row['payload'])
        if not hmac.compare_digest(row['signature'],self.runtime.authority.signature(p)):
            raise ValueError('Stored operation approval is invalid.')
        return p

    def principal(self,principal,wid):
        p=self.runtime.authority.validate(principal,wid,'admin')
        if p['role']!='superadmin':raise ValueError('Superadmin authorization is required.')
        return p

    def subject(self,db,run_id,subject):
        run=db.execute('SELECT * FROM workflow_runs WHERE id=?',(run_id,)).fetchone()
        if not run:raise ValueError('Run not found.')
        if subject=='run':valid=run['execution_outcome']=='unknown'
        else:
            sql="SELECT 1 FROM workflow_manual_deliveries WHERE id=? AND run_id=? AND status='unknown'" if subject.startswith('wm_') else "SELECT 1 FROM workflow_result_outbox WHERE id=? AND run_id=? AND status='unknown'"
            event=db.execute(sql,(subject,run_id)).fetchone()
            valid=bool(event)
        if not valid:raise ValueError('Only an original unknown outcome can be reconciled.')
        return dict(run)

    def reconcile(self,run_id,data,principal):
        if (not isinstance(data,dict) or set(data)!={'subject','revision','disposition','evidence_ref','authority','notice'}
                or data['authority'] is not True or data['notice']!=RECONCILE
                or type(data['revision']) is not int or data['revision']<0
                or data['disposition'] not in ('received','not_received','reviewed')
                or not isinstance(data['subject'],str) or not re.fullmatch(r'run|(?:we|wm)_[a-f0-9]{32}',data['subject'])
                or not isinstance(data['evidence_ref'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{2,99}',data['evidence_ref'])):
            raise ValueError('Provide explicit review authorization, an outcome and an opaque evidence reference.')
        with self.store.tx() as db:
            db.execute('UPDATE workflow_runs SET fence=fence WHERE id=?',(run_id,))
            run=self.subject(db,run_id,data['subject']);claims=self.principal(principal,run['workflow_id'])
            revision=db.execute('SELECT COALESCE(MAX(revision),0) FROM workflow_reconciliation_events WHERE run_id=? AND subject=?',(run_id,data['subject'])).fetchone()[0]
            if revision!=data['revision']:raise ValueError('Review revision changed; reload before recording.')
            p={'audience':RECONCILE,'run_id':run_id,'subject':data['subject'],'revision':revision+1,
               'disposition':data['disposition'],'evidence_ref':data['evidence_ref'],'admin_id':claims['subject'],'created':time.time()}
            db.execute('INSERT INTO workflow_reconciliation_events VALUES (?,?,?,?,?,?)',(run_id,data['subject'],revision+1,json.dumps(p),self.runtime.authority.signature(p),p['created']))
        return self.inspect(run_id)

    def inspect(self,run_id):
        history=[]
        for r in self.store.query('SELECT * FROM workflow_reconciliation_events WHERE run_id=? ORDER BY created DESC LIMIT 100',(run_id,)):
            p=self.verified(r)
            if p.get('run_id')!=run_id or p.get('subject')!=r['subject'] or p.get('revision')!=r['revision']:raise ValueError('Stored review scope is invalid.')
            history.append({k:p[k] for k in ('subject','revision','disposition','evidence_ref','admin_id','created')})
        return {'reviews':history,'manual_deliveries':[dict(r) for r in self.store.query('SELECT id,source_event_id,status,created,finished FROM workflow_manual_deliveries WHERE run_id=? ORDER BY created DESC LIMIT 10',(run_id,))]}

    def request_resend(self,run_id,data,principal):
        if (not isinstance(data,dict) or set(data)!={'source_event_id','review_revision','destination_id','authority','duplicate_risk_ack','notice'}
                or data['notice']!=RESEND or data['authority'] is not True or data['duplicate_risk_ack'] is not True
                or type(data['review_revision']) is not int or data['review_revision']<1
                or not isinstance(data['source_event_id'],str) or not re.fullmatch(r'we_[a-f0-9]{32}',data['source_event_id'])
                or not isinstance(data['destination_id'],str) or not re.fullmatch(r'wd_[a-f0-9]{32}',data['destination_id'])):
            raise ValueError('Explicit resend authorization and duplicate-delivery risk acknowledgement are required.')
        from .execution_authority import require_enabled
        require_enabled(self.store,'delivery')
        with self.store.tx() as db:
            db.execute('UPDATE workflow_runs SET fence=fence WHERE id=?',(run_id,))
            run=self.subject(db,run_id,data['source_event_id']);self.principal(principal,run['workflow_id'])
            if run['status']!='succeeded' or not run['result']:raise ValueError('A retained successful result is required; providers are never rerun here.')
            latest=db.execute('SELECT * FROM workflow_reconciliation_events WHERE run_id=? AND subject=? ORDER BY revision DESC LIMIT 1',(run_id,data['source_event_id'])).fetchone()
            if not latest:raise ValueError('Record an external delivery review first.')
            review=self.verified(latest)
            if review['revision']!=data['review_revision'] or review['disposition']!='not_received' or review.get('run_id')!=run_id or review.get('subject')!=data['source_event_id']:
                raise ValueError('A current not-received review is required.')
            destination=db.execute("SELECT * FROM workflow_destinations WHERE id=? AND workflow_id=? AND state='verified'",(data['destination_id'],run['workflow_id'])).fetchone()
            if not destination:raise ValueError('Select a currently verified workflow inbox.')
            old=db.execute('SELECT id FROM workflow_manual_deliveries WHERE source_event_id=?',(data['source_event_id'],)).fetchone()
            if old:raise ValueError('This source event already has a manual delivery; inspect it before any further action.')
            identity='wm_'+secrets.token_hex(16)
            p={'audience':RESEND,'id':identity,'run_id':run_id,'workflow_id':run['workflow_id'],'source_event_id':data['source_event_id'],
               'review_revision':review['revision'],'result_hash':hashlib.sha256(run['result'].encode()).hexdigest(),
               'destination_id':destination['id'],'destination_hash':self.runtime.authority.destination_hash(dict(destination)),
               'principal':principal,'expires':time.time()+3600,'duplicate_risk_ack':True}
            db.execute("INSERT INTO workflow_manual_deliveries VALUES (?,?,?,?,?,'pending',NULL,0,0,?,NULL)",
                       (identity,run_id,p['source_event_id'],json.dumps(p),self.runtime.authority.signature(p),time.time()))
        return {'id':identity,'status':'pending'}

    def recover(self):
        with self.store.tx() as db:
            db.execute("UPDATE workflow_manual_deliveries SET status=CASE WHEN status='claimed' THEN 'pending' ELSE 'unknown' END,owner=NULL,fence=fence+1,lease_until=0 WHERE status IN ('claimed','dispatched') AND lease_until<=?",(time.time(),))

    def validate_delivery(self,event):
        p=self.verified(event)
        if (p.get('audience')!=RESEND or p.get('id')!=event['id'] or p.get('run_id')!=event['run_id']
                or p.get('source_event_id')!=event['source_event_id'] or p.get('expires',0)<=time.time()):raise ValueError('Manual delivery approval expired or changed.')
        self.principal(p['principal'],p['workflow_id'])
        run=dict(self.store.query('SELECT * FROM workflow_runs WHERE id=?',(p['run_id'],))[0])
        if run['status']!='succeeded' or not run['result'] or hashlib.sha256(run['result'].encode()).hexdigest()!=p['result_hash']:
            raise ValueError('The reviewed result changed.')
        review=self.store.query('SELECT * FROM workflow_reconciliation_events WHERE run_id=? AND subject=? ORDER BY revision DESC LIMIT 1',(p['run_id'],p['source_event_id']))
        current=self.verified(review[0]) if review else {}
        if current.get('revision')!=p['review_revision'] or current.get('disposition')!='not_received':raise ValueError('The reviewed delivery outcome changed.')
        dest=self.store.query("SELECT * FROM workflow_destinations WHERE id=? AND workflow_id=? AND state='verified'",(p['destination_id'],p['workflow_id']))
        if not dest or self.runtime.authority.destination_hash(dict(dest[0]))!=p['destination_hash']:raise ValueError('Inbox verification changed.')
        return p,run,dict(dest[0])

    def drain(self):
        from .execution_authority import require_enabled
        try:require_enabled(self.store,'delivery')
        except ValueError:return
        if self.runtime.courier is None:return
        self.recover()
        for item in self.store.query("SELECT id FROM workflow_manual_deliveries WHERE status='pending' ORDER BY created LIMIT 12"):
            with self.store.tx() as db:
                if not db.execute("UPDATE workflow_manual_deliveries SET status='claimed',owner=?,fence=fence+1,lease_until=? WHERE id=? AND status='pending'",(self.runtime.instance,time.time()+60,item['id'])).rowcount:continue
                event=dict(db.execute('SELECT * FROM workflow_manual_deliveries WHERE id=?',(item['id'],)).fetchone())
            operation=self.runtime.journal.begin('delivery','workflow_delivery',identity=stable_reference('manual-delivery',event['id']),parent_id=stable_reference('workflow',event['run_id']))
            attempt=operation.attempt()
            def dispatch():
                with self.store.tx() as db:
                    db.execute('UPDATE workflow_manual_deliveries SET fence=fence WHERE id=?',(event['id'],))
                    self.validate_delivery(event)
                    if not db.execute("UPDATE workflow_manual_deliveries SET status='dispatched' WHERE id=? AND owner=? AND fence=? AND status='claimed' AND lease_until>?",(event['id'],self.runtime.instance,event['fence'],time.time())).rowcount:raise FenceLost('Manual delivery ownership changed.')
            try:
                p,run,dest=self.validate_delivery(event);result=json.loads(run['result']);secret=self.runtime._open(dest['sealed'],dest['id'])
                from .concierge.http_security import outbound_operation
                with attempt_scope(attempt),dispatch_scope(dispatch),outbound_operation(15):
                    provider_dispatch()
                    sent,_=self.runtime.courier.send_update(dest['channel'],secret,{'type':'workflow_result','run_id':run['id'],'workflow_id':run['workflow_id'],
                        'artifact_sha256':result['artifact_sha256'],'content':result['final_deliverable']['content_md'],'manual_resend':True,'source_event_id':p['source_event_id']},event['id'])
                state='accepted' if sent else 'unknown';attempt.finish(state,None if sent else 'UPSTREAM_NETWORK')
            except Exception:
                row=self.store.query('SELECT status FROM workflow_manual_deliveries WHERE id=?',(event['id'],))
                state='unknown' if row and row[0]['status']=='dispatched' else 'denied'
                attempt.finish(state,'EXECUTION_FAILED')
            with self.store.tx() as db:
                db.execute("UPDATE workflow_manual_deliveries SET status=?,finished=?,lease_until=0 WHERE id=? AND owner=? AND fence=? AND lease_until>? AND status IN ('claimed','dispatched')",(state,time.time(),event['id'],self.runtime.instance,event['fence'],time.time()))
            operation.finish(state,None if state=='accepted' else 'EXECUTION_FAILED')
