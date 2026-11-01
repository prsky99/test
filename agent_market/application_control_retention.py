"""Bounded private control history retention with permanent replay tombstones.

Current policies, authorization pins, financial rows, unknown effects and
admissions protecting a draft/snapshot are never removed. Expired research
bodies, known terminal circuit observations and never-ticketed admissions can
be compacted after ninety days by the existing workspace owner maintenance.
"""
import hashlib
import hmac
import json
import math
import time

from .private_artifact_keys import ArtifactSigner
from .workspace_access import WorkspaceConflict, _canonical, _tree

PROFILE = 'private-control-retention-v1'
DAYS = 90
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS application_control_archives(
       domain TEXT NOT NULL,identity TEXT NOT NULL,workspace_id TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,created REAL NOT NULL,
       PRIMARY KEY(domain,identity))''',
)


class ControlRetention:
    def __init__(self, access):
        self.access, self.store = access, access.store
        self.signer = self._signer(PROFILE)
        with self.store._lock:
            for statement in SCHEMA:
                self.store._db.execute(statement)

    def _signer(self, profile):
        return ArtifactSigner(hmac.new(self.access.key,profile.encode(),hashlib.sha256).digest(),profile)

    def _open(self, row, profile):
        try:
            raw = row['payload']
            if len(raw.encode()) > 131072:
                raise ValueError()
            value = json.loads(raw); _tree(value)
            if type(value) is not dict or not self._signer(profile).verify(value,row['signature']):
                raise ValueError()
            return value
        except (ValueError,TypeError,KeyError,UnicodeError):
            raise WorkspaceConflict() from None

    def _archive(self, db, domain, identity, ws, row, now):
        value = {'profile':PROFILE,'domain':domain,'identity':identity,'workspace_id':ws,
            'payload_sha256':hashlib.sha256(row['payload'].encode()).hexdigest(),
            'source_signature_sha256':hashlib.sha256(row['signature'].encode()).hexdigest(),
            'compacted':now,'authority_restored':False,'automatic_replay':False}
        db.execute('INSERT INTO application_control_archives VALUES(?,?,?,?,?,?)',
            (domain,identity,ws,_canonical(value),self.signer.sign(value),now))

    @staticmethod
    def _time(value):
        return type(value) in (int,float) and math.isfinite(value) and value>0

    def run(self, db, ws, *, limit=20, now=None):
        if db is not self.store._db or not db.in_transaction or type(limit) is not int or not 1<=limit<=20:
            raise WorkspaceConflict()
        now = time.time() if now is None else now
        if not self._time(now):
            raise WorkspaceConflict()
        cutoff = now-DAYS*86400
        result = {'body_days':DAYS,'research_bodies_compacted':0,'circuit_claims_compacted':0,
            'never_ticketed_admissions_compacted':0,'held_invalid_evidence':0,
            'unknown_outcomes_retained':True,'protected_admissions_retained':True,
            'financial_and_key_tombstones_retained':True,'automatic_replay':False}
        remaining = limit
        has_research = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reliability_research_manifests'").fetchone()
        if has_research:
            jobs = db.execute('SELECT id,workspace_id,state,payload,signature FROM reliability_eval_jobs WHERE workspace_id=? ORDER BY id LIMIT 501',(ws,)).fetchall()
            unresolved = len(jobs)>500
            for job in jobs:
                if job['state'] not in ('completed','failed','expired'):
                    unresolved=True
                    break
                try:
                    value=self._open(job,'bounded-continuous-evaluation-v1')
                    if any(value.get(field)!=job[field] for field in ('id','workspace_id','state')):
                        raise WorkspaceConflict()
                except WorkspaceConflict:
                    unresolved=True;result['held_invalid_evidence']+=1
                    break
            if not unresolved:
                rows = db.execute('SELECT * FROM reliability_research_manifests WHERE workspace_id=? AND created<? ORDER BY created,id LIMIT ?', (ws,cutoff,remaining)).fetchall()
                for row in rows:
                    try:
                        value = self._open(row,'bounded-reliability-research-v1')
                        if (any(value.get(field)!=row[field] for field in ('id','workspace_id','corpus_id','created'))
                                or value.get('workspace_id')!=ws
                                or not self._time(value.get('expires')) or value['expires']>=cutoff):
                            continue
                        self._archive(db,'research',row['id'],ws,row,now)
                        db.execute('INSERT INTO reliability_research_restore_blocks VALUES(?) ON CONFLICT(manifest_id) DO NOTHING',(row['id'],))
                        db.execute('DELETE FROM reliability_research_manifests WHERE id=? AND workspace_id=?',(row['id'],ws))
                        result['research_bodies_compacted']+=1;remaining-=1
                    except WorkspaceConflict:
                        result['held_invalid_evidence']+=1
        if remaining and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reliability_circuit_claims'").fetchone():
            # The per-workspace cap already bounds this scan to five hundred.
            rows = db.execute('SELECT * FROM reliability_circuit_claims WHERE workspace_id=? ORDER BY source_ref LIMIT 500',(ws,)).fetchall()
            for row in rows:
                if not remaining:
                    break
                try:
                    value = self._open(row,'configured-read-circuit-v1')
                    observed = value.get('observed_at',value.get('bound_at'))
                    if (value.get('workspace_id')!=ws or value.get('source_ref')!=row['source_ref']
                            or value.get('resource_id')!=row['resource_id']
                            or value.get('outcome') not in ('completed','failed')
                            or not self._time(observed) or observed>=cutoff):
                        continue
                    state = db.execute('SELECT * FROM reliability_circuit_states WHERE workspace_id=? AND resource_id=?',(ws,row['resource_id'])).fetchone()
                    if state and self._open(state,'configured-read-circuit-v1').get('probe_job_id')==row['source_ref']:
                        continue
                    identity=ws+':'+row['source_ref']
                    self._archive(db,'circuit',identity,ws,row,now)
                    db.execute('INSERT INTO reliability_circuit_restore_blocks VALUES(?) ON CONFLICT(authority_id) DO NOTHING',('source:'+identity,))
                    db.execute('DELETE FROM reliability_circuit_claims WHERE workspace_id=? AND source_ref=?',(ws,row['source_ref']))
                    result['circuit_claims_compacted']+=1;remaining-=1
                except WorkspaceConflict:
                    result['held_invalid_evidence']+=1
        if remaining and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reliability_admissions'").fetchone():
            rows = db.execute('SELECT * FROM reliability_admissions WHERE workspace_id=? AND snapshot_id IS NULL AND ticket_id IS NULL ORDER BY id LIMIT 100',(ws,)).fetchall()
            for row in rows:
                if not remaining:
                    break
                try:
                    value = self._open(row,'workspace-single-admission-v1')
                    if (value.get('id')!=row['id'] or value.get('workspace_id')!=ws or value.get('logical_key')!=row['logical_key']
                            or value.get('draft_id') is not None
                            or value.get('snapshot_id') is not None or value.get('ticket_id') is not None
                            or not self._time(value.get('expires')) or value['expires']>=cutoff):
                        continue
                    self._archive(db,'admission',row['id'],ws,row,now)
                    db.execute('INSERT INTO reliability_admission_restore_blocks VALUES(?) ON CONFLICT(authority_id) DO NOTHING',('logical:'+ws+':'+row['logical_key'],))
                    db.execute('INSERT INTO reliability_admission_restore_blocks VALUES(?) ON CONFLICT(authority_id) DO NOTHING',(row['id'],))
                    db.execute('DELETE FROM reliability_admissions WHERE id=? AND workspace_id=? AND snapshot_id IS NULL AND ticket_id IS NULL',(row['id'],ws))
                    result['never_ticketed_admissions_compacted']+=1;remaining-=1
                except WorkspaceConflict:
                    result['held_invalid_evidence']+=1
        return result
