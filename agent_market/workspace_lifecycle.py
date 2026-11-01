"""Bounded private-run retention and owner review without authority resurrection."""
import hashlib
import hmac
import json
import secrets

from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash, _rows, _safe_text
from .workspace_execution import _now
from .private_artifact_keys import ArtifactSigner

PROFILE='workspace-private-lifecycle-v1'
NOTICE='workspace-current-owner-review-v1'
SCHEMA=(
'''CREATE TABLE IF NOT EXISTS workspace_ticket_tombstones(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS workspace_output_archives(run_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS workspace_reconciliation_notes(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,run_id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,UNIQUE(run_id,revision))''',
'''CREATE TABLE IF NOT EXISTS workspace_restore_reviews(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,consumed REAL)''')


class WorkspaceLifecycle:
    def __init__(self,execution):
        self.execution,self.access,self.store=execution,execution.access,execution.store
        self.key=hmac.new(self.access.key,PROFILE.encode(),hashlib.sha256).digest()
        self.signer=ArtifactSigner(self.key,PROFILE)
        with execution._internal() as db:
            for sql in SCHEMA:db.execute(sql)
        from .application_control_retention import ControlRetention
        self.controls=ControlRetention(self.access)

    def _sign(self,value):
        return self.signer.sign(value)

    def _open(self,row):
        try:
            value=json.loads(row['payload'])
            if not self.signer.verify(value,row['signature']):raise WorkspaceConflict()
            return value
        except (ValueError,TypeError,KeyError):raise WorkspaceConflict() from None

    def _owner(self,ws,actor):
        return self.access._access(ws,actor,write=True,owner=True)[0]

    def preview(self,ws,actor):
        with self.access._tx(actor) as (db,_):
            self._owner(ws,actor);now=_now()
            return {'profile':PROFILE,'expired_unused_tickets':db.execute('SELECT COUNT(*) FROM workspace_private_tickets WHERE workspace_id=? AND run_id IS NULL AND expires<=?',(ws,now)).fetchone()[0],
                    'old_terminal_outputs':db.execute("SELECT COUNT(*) FROM workspace_private_runs WHERE workspace_id=? AND status IN ('succeeded','failed','denied') AND finished<? AND id NOT IN(SELECT run_id FROM workspace_output_archives)",(ws,now-604800)).fetchone()[0],
                    'unknown_runs_retained':db.execute("SELECT COUNT(*) FROM workspace_private_runs WHERE workspace_id=? AND status='unknown'",(ws,)).fetchone()[0],
                    'output_days':7,'max_batch':50,'automatic_resend':False,'restores_memberships':False}

    def maintain(self,ws,body,actor):
        if type(body) is not dict or set(body)!={'limit'} or type(body['limit']) is not int or not 1<=body['limit']<=50:raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as (db,_):
            self._owner(ws,actor);now=_now();expired=archived=0
            tickets=_rows(db,'SELECT * FROM workspace_private_tickets WHERE workspace_id=? AND run_id IS NULL AND expires<=? ORDER BY expires,id LIMIT ?',(ws,now,body['limit']))
            for row in tickets:
                ticket,claims=self.execution._ticket(db,row['id'],ws,row['draft_id'],row['snapshot_id'])
                if ticket['run_id'] is not None:raise WorkspaceConflict()
                receipt={'profile':PROFILE,'id':row['id'],'workspace_id':ws,'ticket_hash':_hash(claims),'expired':row['expires'],'pruned':now,'never_dispatched':True}
                db.execute('INSERT INTO workspace_ticket_tombstones VALUES(?,?,?,?)',(row['id'],ws,_canonical(receipt),self._sign(receipt)))
                if db.execute('DELETE FROM workspace_private_tickets WHERE id=? AND run_id IS NULL',(row['id'],)).rowcount!=1:raise WorkspaceConflict()
                expired+=1
            rows=_rows(db,"SELECT * FROM workspace_private_runs WHERE workspace_id=? AND status IN ('succeeded','failed','denied') AND finished<? AND id NOT IN(SELECT run_id FROM workspace_output_archives) ORDER BY finished,id LIMIT ?",(ws,now-604800,body['limit']))
            for row in rows:
                _,_,_,payload=self.execution._load_run(db,row['id'],ws,row['draft_id'],row['snapshot_id'])
                receipt={'profile':PROFILE,'run_id':row['id'],'workspace_id':ws,'output_hash':_hash(payload['output']),'retained_payload_hash':_hash(json.loads(row['payload'])),'archived':now,'status':row['status']}
                db.execute('INSERT INTO workspace_output_archives VALUES(?,?,?,?)',(row['id'],ws,_canonical(receipt),self._sign(receipt)))
                payload.update(output=None,output_archived=True,archived_output_hash=receipt['output_hash'])
                self.execution._store_run(db,payload);archived+=1
            self.access._audit(db,actor,ws,'lifecycle.maintain',None,expired+archived)
            controls=self.controls.run(db,ws,limit=min(20,body['limit']),now=now)
            return {'profile':PROFILE,'expired_unused_pruned':expired,'outputs_archived':archived,'controls_retention':controls,'unknown_deleted':0,'automatic_resend':False}

    def reconcile(self,ws,draft,snapshot,run,body,actor):
        if type(body) is not dict or set(body)!={'revision','note'} or type(body['revision']) is not int or body['revision']<0:raise WorkspaceInvalid()
        note=_safe_text(body['note'],1000)
        with self.access._tx(actor,write=True) as (db,_):
            self._owner(ws,actor);self.execution._scope(ws,draft,snapshot,actor)
            self.execution._load_run(db,run,ws,draft,snapshot)
            rows=_rows(db,'SELECT * FROM workspace_reconciliation_notes WHERE workspace_id=? AND run_id=? ORDER BY revision DESC LIMIT 1',(ws,run))
            revision=rows[0]['revision'] if rows else 0
            if rows:self._open(rows[0])
            if body['revision']!=revision:raise WorkspaceConflict()
            value={'id':'wn_'+secrets.token_hex(16),'workspace_id':ws,'run_id':run,'revision':revision+1,'note':note,'reviewer_id':actor.user_id,'created':_now(),'execution_status_changed':False,'resent':False}
            db.execute('INSERT INTO workspace_reconciliation_notes VALUES(?,?,?,?,?,?)',(value['id'],ws,run,value['revision'],_canonical(value),self._sign(value)))
            self.access._audit(db,actor,ws,'execution.reconcile',run,value['revision']);return value

    def notes(self,ws,draft,snapshot,run,actor):
        with self.access._tx(actor) as (db,_):
            self._owner(ws,actor);self.execution._scope(ws,draft,snapshot,actor);self.execution._load_run(db,run,ws,draft,snapshot)
            return [self._open(row) for row in _rows(db,'SELECT * FROM workspace_reconciliation_notes WHERE workspace_id=? AND run_id=? ORDER BY revision DESC LIMIT 30',(ws,run))]

    def prepare_restore_review(self,ws,draft,snapshot,actor):
        with self.access._tx(actor,write=True) as (db,_):
            membership=self._owner(ws,actor);_,_,row,_=self.execution._scope(ws,draft,snapshot,actor)
            value={'profile':PROFILE,'id':'wrr_'+secrets.token_hex(16),'workspace_id':ws,'draft_id':draft,'snapshot_id':snapshot,'snapshot_hash':row['payload_hash'],'workspace_revision':membership['revision'],'member_revision':membership['member_revision'],'owner_id':actor.user_id,'session_ref':actor.session_ref,'created':_now(),'expires':_now()+300}
            db.execute('INSERT INTO workspace_restore_reviews VALUES(?,?,?,?,NULL)',(value['id'],ws,_canonical(value),self._sign(value)))
            return {'review_id':value['id'],'expires':value['expires'],'notice':NOTICE,'restores_memberships':False,'reactivates_old_grants':False}

    def approve_restore_review(self,ws,body,actor):
        if type(body) is not dict or set(body)!={'review_id','authorized','notice'} or body['authorized'] is not True or body['notice']!=NOTICE:raise WorkspaceInvalid()
        with self.access._tx(actor,write=True) as (db,_):
            membership=self._owner(ws,actor);rows=_rows(db,'SELECT * FROM workspace_restore_reviews WHERE id=? AND workspace_id=?',(body['review_id'],ws))
            if len(rows)!=1:raise WorkspaceDenied()
            value=self._open(rows[0]);_,_,snapshot,_=self.execution._scope(ws,value['draft_id'],value['snapshot_id'],actor)
            if (rows[0]['consumed'] is not None or value['expires']<=_now() or value['owner_id']!=actor.user_id or value['session_ref']!=actor.session_ref or value['workspace_revision']!=membership['revision'] or value['member_revision']!=membership['member_revision'] or value['snapshot_hash']!=snapshot['payload_hash']):raise WorkspaceDenied()
            db.execute('UPDATE workspace_restore_reviews SET consumed=? WHERE id=? AND consumed IS NULL',(_now(),value['id']))
            self.access._audit(db,actor,ws,'restore.current_owner_review',value['snapshot_id'],snapshot['revision'])
            return {'reviewed':True,'fresh_grants_required':True,'restores_memberships':False,'reactivates_old_grants':False,'starts_runs':False}
