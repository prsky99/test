"""Default-off private circuit metadata; existing evaluation jobs are the only probes.

No method in this module dispatches work. A trusted MCP adapter observation is
technical evidence, not a network receipt or independent business-quality claim.
"""
from copy import deepcopy

from .reliability_evaluation import bounded_int, finite, revision_authority
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash, _identity, _rows

PROFILE = 'configured-read-circuit-v1'
NOTICE = 'separate-approved-evaluation-probe-v1'
MAX_CIRCUITS = 50
MAX_CLAIMS = 500
MAX_SAMPLES = 100
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS reliability_circuit_states (
       workspace_id TEXT NOT NULL,resource_id INTEGER NOT NULL,revision INTEGER NOT NULL,
       generation INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
       PRIMARY KEY(workspace_id,resource_id))''',
    '''CREATE TABLE IF NOT EXISTS reliability_circuit_claims (
       workspace_id TEXT NOT NULL,source_ref TEXT NOT NULL,resource_id INTEGER NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(workspace_id,source_ref))''',
    '''CREATE TABLE IF NOT EXISTS reliability_circuit_restore_blocks (
       authority_id TEXT PRIMARY KEY)''',
)


def quarantine_circuits(db):
    """Permanent restore markers; never rewrite historical signed artifacts."""
    for ws, rid, generation in db.execute('SELECT workspace_id,resource_id,generation FROM reliability_circuit_states').fetchall():
        db.execute('INSERT INTO reliability_circuit_restore_blocks VALUES(?) ON CONFLICT(authority_id) DO NOTHING',
                   ('circuit:'+ws+':'+str(rid)+':'+str(generation),))
    for ws, ref in db.execute('SELECT workspace_id,source_ref FROM reliability_circuit_claims').fetchall():
        db.execute('INSERT INTO reliability_circuit_restore_blocks VALUES(?) ON CONFLICT(authority_id) DO NOTHING',
                   ('source:'+ws+':'+ref,))


class ReliabilityCircuit(SignedWorkspaceModule):
    def __init__(self, access, evaluation, *, evidence_guard, enabled=False, execution=None):
        if (evaluation.store is not access.store or not callable(evidence_guard) or type(enabled) is not bool
                or execution is not None and execution.store is not access.store):
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.evaluation, self.evidence_guard = evaluation, evidence_guard
        self.enabled, self.execution = enabled, execution

    @staticmethod
    def _authorize(body, fields):
        exact(body, (*fields, 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        bounded_int(body['revision'], 0, 2**31-1)

    @staticmethod
    def _rid(rid):
        bounded_int(rid, 1, 2**31-1)

    @staticmethod
    def _block(db, identity):
        return bool(db.execute('SELECT 1 FROM reliability_circuit_restore_blocks WHERE authority_id=?', (identity,)).fetchone())

    def _restored(self, db, value):
        return self._block(db, 'circuit:'+value['workspace_id']+':'+str(value['resource_id'])+':'+str(value['generation']))

    def _read(self, db, ws, rid):
        # Verify the bounded scope registry before matching a resource. Moving
        # an unsigned SQL locator must not make a configured circuit disappear.
        rows = _rows(db, 'SELECT * FROM reliability_circuit_states WHERE workspace_id=? ORDER BY resource_id LIMIT 51', (ws,))
        if len(rows) > MAX_CIRCUITS:
            raise WorkspaceConflict()
        selected = None
        for row in rows:
            value = self.opened(row)
            if (value.get('profile') != PROFILE or value.get('workspace_id') != ws
                    or any(value.get(k) != row[k] for k in ('workspace_id', 'resource_id', 'revision', 'generation'))
                    or value.get('state') not in ('closed', 'open', 'half_open')
                    or type(value.get('samples')) is not list or len(value['samples']) > MAX_SAMPLES):
                raise WorkspaceConflict()
            if value['resource_id'] == rid:
                selected = value
        return selected

    def _save(self, db, value, actor, action):
        db.execute('''INSERT INTO reliability_circuit_states VALUES(?,?,?,?,?,?)
            ON CONFLICT(workspace_id,resource_id) DO UPDATE SET revision=excluded.revision,
            generation=excluded.generation,payload=excluded.payload,signature=excluded.signature''',
            (value['workspace_id'], value['resource_id'], value['revision'], value['generation'], _canonical(value), self.sign(value)))
        self.access._audit(db, actor, value['workspace_id'], 'reliability.circuit.'+action,
                           str(value['resource_id']), value['revision'])
        return self._dto(value)

    @staticmethod
    def _dto(value):
        return {key: value[key] for key in ('resource_id', 'revision', 'generation', 'enabled', 'state',
                'open_epoch', 'opened_at', 'expires', 'probe_job_id', 'reason')} | {
            'provider_calls': 0, 'automatic_probe': False, 'public_activation': False}

    def _current(self, db, ws, rid, actor, revision=None):
        member, user = self.scope(ws, actor, write=True, owner=True)
        value = self._read(db, ws, rid)
        if (not self.enabled or not value or not value['enabled'] or value['expires'] <= clock()
                or self._restored(db, value)
                or revision is not None and value['revision'] != revision
                or any(value.get(key) != v for key, v in revision_authority(member, user, actor).items())
                or self.evaluation._pin(rid, value['contract_id']) != value['pin']):
            raise WorkspaceConflict()
        controls = _rows(db, 'SELECT invoke_enabled,workflow_enabled FROM execution_controls WHERE id=1')
        if len(controls) != 1 or any(controls[0][k] != 1 for k in ('invoke_enabled', 'workflow_enabled')):
            raise WorkspaceConflict()
        return value

    def configure(self, ws, body, actor):
        fields = ('revision', 'resource_id', 'contract_id', 'environment', 'enabled', 'failure_count',
                  'unknown_count', 'sample_window_seconds', 'sample_max_age_seconds', 'open_seconds',
                  'probe_max_age_seconds', 'expires')
        self._authorize(body, fields); self._rid(body['resource_id'])
        if (body['contract_id'] not in ('news.search.v1', 'docs.search.v1')
                or body['environment'] not in ('isolated', 'sandbox', 'operating')
                or type(body['enabled']) is not bool or not finite(body['expires'])
                or not clock() < body['expires'] <= clock()+86400):
            raise WorkspaceInvalid()
        for key in ('failure_count', 'unknown_count'):
            bounded_int(body[key], 1, MAX_SAMPLES)
        for key in ('sample_window_seconds', 'sample_max_age_seconds', 'open_seconds', 'probe_max_age_seconds'):
            bounded_int(body[key], 1, 86400)
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            if not self.enabled:
                raise WorkspaceConflict()
            rid = body['resource_id']; old = self._read(db, ws, rid)
            if body['revision'] != (old['revision'] if old else 0):
                raise WorkspaceConflict()
            if not old and db.execute('SELECT COUNT(*) FROM reliability_circuit_states WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_CIRCUITS:
                raise WorkspaceConflict()
            pin = self.evaluation._pin(rid, body['contract_id'])
            source = self.evidence_guard(db, ws, rid, actor)
            if (type(source) is not dict or source.get('resource_id') != rid
                    or source.get('agent_version') != pin['pin']['version']['id']
                    or source.get('schema_hash') != pin['pin']['version']['schema_hash']
                    or source.get('contract_id') != body['contract_id'] or source.get('revoked') is not False
                    or source.get('environment') != body['environment']
                    or source.get('quality_status') != 'assessed' or source.get('source_fidelity') != 'verified'
                    or source.get('independent_qualified') is not True or not finite(source.get('expires_at'))
                    or source['expires_at'] <= clock()
                    or body['environment'] == 'operating' and source.get('qualified_operating_evidence') is not True):
                raise WorkspaceConflict()
            now = clock()
            # Reconfiguration never resets a tripped, withdrawn or restored circuit.
            sticky = bool(old and (old['state'] != 'closed' or not old['enabled'] or self._restored(db, old)
                                   or old['expires'] <= now or old['pin'] != pin))
            value = {key: body[key] for key in fields if key != 'revision'} | {
                'profile': PROFILE, 'workspace_id': ws, 'revision': body['revision']+1,
                'generation': (old['generation'] if old else 0)+1,
                'pin': pin, 'created': now, 'state': 'open' if sticky else 'closed',
                'open_epoch': (old['open_epoch'] if old else 0)+(1 if sticky else 0),
                'opened_at': now if sticky else None, 'probe_job_id': None, 'probe': None,
                'reason': 'reapproval_requires_probe' if sticky else 'owner_configured',
                'samples': old['samples'] if old else [], **revision_authority(member, user, actor)}
            return self._save(db, value, actor, 'configure')

    def _claim(self, db, ws, source_ref):
        rows = _rows(db, 'SELECT * FROM reliability_circuit_claims WHERE workspace_id=? AND source_ref=?', (ws, source_ref))
        if not rows:
            return None
        row = rows[0]; value = self.opened(row)
        if any(value.get(key) != row[key] for key in ('workspace_id', 'source_ref', 'resource_id')):
            raise WorkspaceConflict()
        return value

    def _save_claim(self, db, value, *, new=False):
        if self._block(db, 'source:'+value['workspace_id']+':'+value['source_ref']):
            raise WorkspaceConflict()
        if new:
            if (self._claim(db, value['workspace_id'], value['source_ref']) is not None
                    or db.execute('SELECT COUNT(*) FROM reliability_circuit_claims WHERE workspace_id=?',
                                  (value['workspace_id'],)).fetchone()[0] >= MAX_CLAIMS):
                raise WorkspaceConflict()
            db.execute('INSERT INTO reliability_circuit_claims VALUES(?,?,?,?,?)',
                (value['workspace_id'], value['source_ref'], value['resource_id'], _canonical(value), self.sign(value)))
        else:
            db.execute('UPDATE reliability_circuit_claims SET payload=?,signature=? WHERE workspace_id=? AND source_ref=?',
                       (_canonical(value), self.sign(value), value['workspace_id'], value['source_ref']))

    def _evaluation_source(self, db, ws, rid, source_ref, actor, value):
        job = self.evaluation.response_evidence_in_transaction(db, ws, source_ref, actor)
        if (job['resource_id'] != rid or job['response_proof']['dispatch_guard_passed'] is not True
                or job['response_proof']['pin_hash'] != _hash(value['pin']['pin'])):
            raise WorkspaceConflict()
        return job['state'], job['observed_at'], _hash(job)

    def _private_source(self, db, ws, rid, source_ref, actor, value):
        if self.execution is None:
            raise WorkspaceConflict()
        rows = _rows(db, 'SELECT * FROM workspace_private_runs WHERE id=? AND workspace_id=?', (source_ref, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        row = rows[0]
        _, ticket, claims, run = self.execution._load_run(db, source_ref, ws, row['draft_id'], row['snapshot_id'], decrypt_output=False)
        current, node, _ = self.execution._binding(db, ws, row['draft_id'], row['snapshot_id'], actor)
        if (claims['resource_id'] != rid or any(claims[k] != v for k, v in current.items())
                or node['data']['tool'] != value['pin']['pin']['approval']['tool']
                or ticket['revoked'] is not None or run['dispatched'] is None
                or run['status'] not in ('succeeded', 'failed', 'unknown') or not finite(run['finished'])
                or not run['created'] <= run['dispatched'] <= run['finished'] <= clock()):
            raise WorkspaceConflict()
        return ('completed' if run['status'] == 'succeeded' else run['status']), run['finished'], _hash(run)

    def ingest(self, ws, rid, body, actor):
        self._rid(rid); self._authorize(body, ('revision', 'source_ref'))
        ref = body['source_ref']
        if type(ref) is not str or not ref.startswith(('rej_', 'wpr_')):
            raise WorkspaceInvalid()
        _identity(ref, 'rej' if ref.startswith('rej_') else 'wpr')
        with self.access._tx(actor, write=True) as (db, _):
            value = self._current(db, ws, rid, actor, body['revision'])
            old_claim = self._claim(db, ws, ref)
            if old_claim:
                if old_claim['resource_id'] != rid or old_claim['kind'] != 'observation':
                    raise WorkspaceConflict()
                return self._dto(value) | {'replayed': True}
            resolve = self._evaluation_source if ref.startswith('rej_') else self._private_source
            outcome, observed, proof_hash = resolve(db, ws, rid, ref, actor, value)
            now = clock()
            if observed < value['created'] or observed < now-value['sample_max_age_seconds'] or observed > now:
                raise WorkspaceConflict()
            self._save_claim(db, {'workspace_id': ws, 'resource_id': rid, 'source_ref': ref,
                'kind': 'observation', 'generation': value['generation'], 'proof_hash': proof_hash,
                'outcome': outcome, 'observed_at': observed}, new=True)
            samples = [sample for sample in value['samples'] if sample['observed_at'] >= now-value['sample_window_seconds']]
            if len(samples) >= MAX_SAMPLES:
                raise WorkspaceConflict()
            samples.append({'source_ref': ref, 'outcome': outcome, 'observed_at': observed})
            value['samples'] = samples; value['revision'] += 1
            if value['state'] == 'closed' and (sum(s['outcome'] == 'failed' for s in samples) >= value['failure_count']
                    or sum(s['outcome'] == 'unknown' for s in samples) >= value['unknown_count']):
                value.update(state='open', open_epoch=value['open_epoch']+1, opened_at=now,
                             probe_job_id=None, probe=None, reason='observed_threshold')
            return self._save(db, value, actor, 'ingest')

    def bind_probe(self, ws, rid, body, actor):
        self._rid(rid); self._authorize(body, ('revision', 'job_id')); _identity(body['job_id'], 'rej')
        with self.access._tx(actor, write=True) as (db, _):
            value = self._current(db, ws, rid, actor, body['revision']); now = clock()
            plan, corpus, control = self.evaluation._current(db, ws, actor)
            job = self.evaluation._job(db, ws, body['job_id'])
            if (value['state'] != 'open' or now < value['opened_at']+value['open_seconds']
                    or job.get('restore_quarantined') or job['state'] != 'reserved' or job['resource_id'] != rid
                    or not value['opened_at'] < job['created'] <= now or job['expires'] <= now
                    or job['plan_revision'] != plan['revision'] or job['control_revision'] != control['revision']
                    or corpus['contract_id'] != value['contract_id'] or plan['pins'][str(rid)] != value['pin']):
                raise WorkspaceConflict()
            proof = {'workspace_id': ws, 'resource_id': rid, 'source_ref': job['id'], 'kind': 'probe',
                'generation': value['generation'], 'open_epoch': value['open_epoch'], 'bound_at': now,
                'plan_revision': plan['revision'], 'control_revision': control['revision'],
                'corpus_hash': corpus['corpus_hash'], 'pin_hash': _hash(value['pin']['pin']),
                'expires': min(job['expires'], value['expires'], now+value['probe_max_age_seconds']), 'outcome': None}
            self._save_claim(db, proof, new=True)
            value.update(state='half_open', revision=value['revision']+1, probe_job_id=job['id'], probe=_hash(proof), reason='separate_probe_bound')
            return self._save(db, value, actor, 'bind_probe')

    def refresh_probe(self, ws, rid, body, actor):
        self._rid(rid); self._authorize(body, ('revision',))
        with self.access._tx(actor, write=True) as (db, _):
            value = self._current(db, ws, rid, actor, body['revision']); now = clock()
            if value['state'] != 'half_open' or value['probe_job_id'] is None:
                raise WorkspaceConflict()
            proof = self._claim(db, ws, value['probe_job_id'])
            if (not proof or proof['kind'] != 'probe' or _hash(proof) != value['probe']
                    or proof['resource_id'] != rid or proof['generation'] != value['generation']
                    or proof['open_epoch'] != value['open_epoch']
                    or self._block(db, 'source:'+ws+':'+proof['source_ref'])):
                raise WorkspaceConflict()
            job = self.evaluation._job(db, ws, proof['source_ref'])
            if job['state'] in ('reserved', 'prepared', 'dispatched') and now < proof['expires'] and not job.get('restore_quarantined'):
                return self._dto(value) | {'waiting': True}
            success = False
            if now < proof['expires'] and not job.get('restore_quarantined'):
                try:
                    verified = self.evaluation.response_evidence_in_transaction(db, ws, job['id'], actor)
                    response = verified['response_proof']
                    success = (verified['state'] == 'completed' and response['response_validated'] is True
                        and response['dispatch_guard_passed'] is True and response['pin_hash'] == proof['pin_hash']
                        and response['corpus_hash'] == proof['corpus_hash']
                        and verified['plan_revision'] == proof['plan_revision'] and verified['control_revision'] == proof['control_revision']
                        and proof['bound_at'] <= verified['prepared_at'] <= verified['dispatched_at'] <= verified['observed_at']
                        and value['opened_at'] < verified['created'])
                    source = self.evidence_guard(db, ws, rid, actor)
                    success = success and (type(source) is dict and source.get('resource_id') == rid
                        and source.get('agent_version') == value['pin']['pin']['version']['id']
                        and source.get('schema_hash') == value['pin']['pin']['version']['schema_hash']
                        and source.get('contract_id') == value['contract_id']
                        and source.get('environment') == value['environment']
                        and source.get('revoked') is False and source.get('quality_status') == 'assessed'
                        and source.get('source_fidelity') == 'verified' and source.get('independent_qualified') is True
                        and finite(source.get('expires_at')) and now < source['expires_at']
                        and (value['environment'] != 'operating' or source.get('qualified_operating_evidence') is True))
                except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
                    success = False
            proof['outcome'] = 'completed' if success else ('unknown' if job['state'] in ('unknown', 'dispatched') else 'failed')
            self._save_claim(db, proof)
            value.update(state='closed' if success else 'open', revision=value['revision']+1,
                probe_job_id=None, probe=None, reason='verified_probe_response' if success else 'probe_not_verified',
                samples=[] if success else value['samples'])
            if not success:
                value.update(open_epoch=value['open_epoch']+1, opened_at=now)
            return self._save(db, value, actor, 'refresh_probe') | {'probe_outcome': proof['outcome']}

    def status(self, ws, rid, actor):
        self._rid(rid)
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            value = self._read(db, ws, rid)
            return {'configured': value is not None, 'server_enabled': self.enabled,
                    'circuit': self._dto(value) if value else None, 'provider_calls': 0,
                    'restore_quarantined': bool(value and self._restored(db, value))}

    def current_projection_in_transaction(self, db, ws, rid, actor):
        if db is not self.store._db or not db.in_transaction:
            raise WorkspaceConflict()
        source = self.evidence_guard(db, ws, rid, actor)
        value = self._read(db, ws, rid)
        # Preserve the exact original projection when there has been no circuit.
        if value is None:
            return source
        try:
            self._current(db, ws, rid, actor)
            state = value['state']
            if db.execute('SELECT COUNT(*) FROM reliability_circuit_claims WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_CLAIMS:
                state = 'quarantined'
        except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
            state = 'quarantined'
        result = deepcopy(source)
        result.update(circuit_state=state, circuit_revision=value['revision'],
                      circuit_generation=value['generation'], circuit_epoch=value['open_epoch'],
                      circuit_source_hash=_hash(value))
        if finite(result.get('expires_at')):
            result['expires_at'] = min(result['expires_at'], value['expires'])
        return result

    def get_agent_projection(self, ws, rid, actor):
        self._rid(rid)
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            return self.current_projection_in_transaction(db, ws, rid, actor)
