"""Finite owner-approved read evaluation scheduling with explicit trusted adapters."""
import math
import re
import secrets
from urllib.parse import urlsplit

from .capability_contracts import validate
from .reliability_controls_restore import blocked
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash, _identity, _rows
from .workflow_fallback import RoutingDenied

PROFILE = 'bounded-continuous-evaluation-v1'
NOTICE = 'approved-read-evaluation-corpus-v1'
STATES = ('reserved', 'prepared', 'dispatched', 'completed', 'failed', 'unknown', 'expired')
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS reliability_controls_restore_blocks (
       authority_id TEXT PRIMARY KEY)''',
    '''CREATE TABLE IF NOT EXISTS reliability_eval_controls (
       workspace_id TEXT PRIMARY KEY,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_eval_corpora (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_eval_plans (
       workspace_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_eval_jobs (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,logical_key TEXT NOT NULL UNIQUE,
       state TEXT NOT NULL,host_key TEXT NOT NULL,window_start REAL NOT NULL,expires REAL NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def bounded_int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise WorkspaceInvalid()
    return value


def revision_authority(member, user, actor):
    return {'actor_user_id': actor.user_id, 'session_ref': actor.session_ref,
            'workspace_revision': member['revision'], 'member_revision': member['member_revision'],
            'user_role': user['role']}


class ReliabilityEvaluation(SignedWorkspaceModule):
    def __init__(self, access, runtime, *, read_evaluator=None, evaluator_authorizer=None):
        if runtime.store is not access.store:
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.runtime = runtime
        self.read_evaluator = read_evaluator
        self.evaluator_authorizer = evaluator_authorizer
        self.worker = None
        self.research = None

    def _adapter_configured(self):
        return (callable(self.read_evaluator) and callable(self.evaluator_authorizer)
                and getattr(self.read_evaluator, 'configured', True) is True)

    def _worker_enabled(self):
        return bool(self.worker is not None and self.worker.running)

    def _put(self, db, table, value):
        # Table names are fixed at each call site; user fields never select SQL identifiers.
        payload, signature = _canonical(value), self.sign(value)
        if table == 'control':
            db.execute('''INSERT INTO reliability_eval_controls VALUES(?,?,?) ON CONFLICT(workspace_id)
                DO UPDATE SET payload=excluded.payload,signature=excluded.signature''', (value['workspace_id'], payload, signature))
        elif table == 'plan':
            db.execute('''INSERT INTO reliability_eval_plans VALUES(?,?,?,?) ON CONFLICT(workspace_id)
                DO UPDATE SET revision=excluded.revision,payload=excluded.payload,signature=excluded.signature''',
                (value['workspace_id'], value['revision'], payload, signature))
        elif table == 'job':
            db.execute('''INSERT INTO reliability_eval_jobs VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id)
                DO UPDATE SET state=excluded.state,payload=excluded.payload,signature=excluded.signature''',
                (value['id'], value['workspace_id'], value['logical_key'], value['state'], value['host_key'],
                 value['window_start'], value['expires'], payload, signature))
        else:
            raise WorkspaceInvalid()

    def _control(self, db, ws):
        rows = _rows(db, 'SELECT * FROM reliability_eval_controls WHERE workspace_id=?', (ws,))
        if not rows:
            return {'workspace_id': ws, 'revision': 0, 'enabled': False}
        value = self.opened(rows[0])
        if value['workspace_id'] != ws or type(value['enabled']) is not bool or type(value['revision']) is not int:
            raise WorkspaceConflict()
        if blocked(db, 'eval_control', ws, value['revision']):
            return value | {'enabled': False, 'restore_quarantined': True}
        return value

    def _plan(self, db, ws):
        rows = _rows(db, 'SELECT * FROM reliability_eval_plans WHERE workspace_id=?', (ws,))
        if not rows:
            return None
        value = self.opened(rows[0])
        if value['workspace_id'] != ws or value['revision'] != rows[0]['revision']:
            raise WorkspaceConflict()
        if blocked(db, 'eval_plan', ws, value['revision']):
            return value | {'restore_quarantined': True}
        return value

    def _corpus(self, db, ws, identity):
        _identity(identity, 'rcp')
        rows = _rows(db, 'SELECT * FROM reliability_eval_corpora WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        if value['workspace_id'] != ws or value['id'] != identity:
            raise WorkspaceConflict()
        return value

    def _job(self, db, ws, identity):
        _identity(identity, 'rej')
        rows = _rows(db, 'SELECT * FROM reliability_eval_jobs WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        if any(value[key] != rows[0][key] for key in ('id', 'workspace_id', 'logical_key', 'state', 'host_key', 'window_start', 'expires')):
            raise WorkspaceConflict()
        if value['state'] not in STATES:
            raise WorkspaceConflict()
        if blocked(db, 'eval_job', identity):
            state = ('unknown' if value['state'] == 'dispatched' else 'expired'
                     if value['state'] in ('reserved', 'prepared') else value['state'])
            return value | {'state': state, 'outcome': 'unknown' if state == 'unknown' else value['outcome'],
                            'reason': 'restore_quarantined', 'restore_quarantined': True}
        return value

    def _pin(self, resource_id, contract):
        try:
            pin = self.runtime.fallback.pin(resource_id, contract, evidence=False)
        except (RoutingDenied, ValueError, KeyError):
            raise WorkspaceConflict() from None
        resource = self.store.resource(resource_id)
        host = urlsplit(resource['url']).hostname
        if not host:
            raise WorkspaceConflict()
        return {'pin': pin, 'host_key': _hash(['evaluation-host-v1', host.lower()])}

    @staticmethod
    def _job_dto(value):
        return {key: value[key] for key in ('id', 'state', 'resource_id', 'case_id', 'corpus_version',
            'plan_revision', 'window_start', 'not_before', 'expires', 'created', 'prepared_at',
            'dispatched_at', 'finished_at', 'observed_at', 'outcome', 'reason')} | {
                'evaluation_dispatches': int(value['dispatched_at'] is not None),
                'restore_quarantined': bool(value.get('restore_quarantined'))}

    def _recover(self, db, ws, now):
        rows = _rows(db, 'SELECT id FROM reliability_eval_jobs WHERE workspace_id=? AND state IN (?,?,?)',
                     (ws, 'reserved', 'prepared', 'dispatched'))
        for row in rows:
            if blocked(db, 'eval_job', row['id']):
                continue
            value = self._job(db, ws, row['id'])
            if value['expires'] <= now:
                value.update(state='unknown' if value['state'] == 'dispatched' else 'expired',
                             finished_at=now, reason='dispatch_uncertain' if value['state'] == 'dispatched' else 'deadline_elapsed')
                self._put(db, 'job', value)

    @staticmethod
    def _active_host_jobs(db, host_key, now, exclude=''):
        # Restored signatures stay immutable. A permanently quarantined or
        # expired row cannot hold new, separately approved evaluation capacity.
        # Live unblocked prepared/dispatched jobs still serialize each host.
        return db.execute('''SELECT COUNT(*) FROM reliability_eval_jobs AS job
            WHERE job.host_key=? AND job.id!=? AND job.state IN (?,?) AND job.expires>?
            AND NOT EXISTS (SELECT 1 FROM reliability_controls_restore_blocks AS restored
                WHERE restored.authority_id='eval_job:'||job.id)''',
            (host_key, exclude, 'prepared', 'dispatched', now)).fetchone()[0]

    def options(self, ws, actor):
        with self.access._tx(actor) as (db, user):
            member, _ = self.scope(ws, actor)
            return {'profile': PROFILE, 'notice': NOTICE, 'control': self._control(db, ws),
                    'can_write': member['member_role'] == 'owner' and user['role'] != 'operator',
                    'evaluator_configured': self._adapter_configured(),
                    'states': list(STATES), 'automatic_worker_enabled': self._worker_enabled(), 'public_activation': False,
                    'business_dispatches': 0}

    def set_control(self, ws, body, actor):
        exact(body, ('revision', 'enabled', 'authorized', 'notice'))
        bounded_int(body['revision'], 0, 2**31-1)
        if type(body['enabled']) is not bool or body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            old = self._control(db, ws)
            if body['revision'] != old['revision']:
                raise WorkspaceConflict()
            value = {'workspace_id': ws, 'revision': old['revision']+1, 'enabled': body['enabled']}
            self._put(db, 'control', value)
            self.access._audit(db, actor, ws, 'reliability.evaluation.control', ws, value['revision'])
            return value

    def register_corpus(self, ws, body, actor):
        exact(body, ('corpus_id', 'version', 'contract_id', 'cases', 'training_hashes', 'authorized', 'notice', 'data_attestation'))
        _identity(body['corpus_id'], 'rcp')
        if (type(body['version']) is not str or not re.fullmatch(r'[a-z0-9.-]{1,60}', body['version'])
                or body['contract_id'] not in ('news.search.v1', 'docs.search.v1')
                or body['authorized'] is not True or body['notice'] != NOTICE
                or body['data_attestation'] != 'synthetic_or_licensed_no_personal_data'
                or type(body['cases']) is not list or not 1 <= len(body['cases']) <= 20
                or type(body['training_hashes']) is not list or len(body['training_hashes']) > 100
                or any(type(value) is not str or not re.fullmatch(r'sha256:[a-f0-9]{64}', value) for value in body['training_hashes'])):
            raise WorkspaceInvalid()
        seen = set(); inputs = set(); splits = {}
        for case in body['cases']:
            exact(case, ('case_id', 'kind', 'split', 'input'))
            if (type(case['case_id']) is not str or not re.fullmatch(r'[a-z0-9.-]{1,60}', case['case_id'])
                    or case['case_id'] in seen or case['kind'] not in ('repeatability', 'semantic_variant', 'schema_drift', 'response_loss', 'rate_limit')
                    or case['split'] not in ('evaluation', 'holdout')):
                raise WorkspaceInvalid()
            try:
                validate(body['contract_id'], case['input'])
            except (TypeError, ValueError):
                raise WorkspaceInvalid() from None
            input_hash = _hash(case['input'])
            if input_hash in splits and splits[input_hash] != case['split']:
                raise WorkspaceInvalid()
            seen.add(case['case_id']); inputs.add(input_hash); splits[input_hash] = case['split']
        if inputs.intersection(body['training_hashes']):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            value = {'id': body['corpus_id'], 'workspace_id': ws, 'version': body['version'],
                     'contract_id': body['contract_id'], 'cases': body['cases'], 'training_hashes': sorted(set(body['training_hashes'])),
                     'created': clock(), **revision_authority(member, user, actor)}
            value['corpus_hash'] = _hash({key: value[key] for key in ('version', 'contract_id', 'cases', 'training_hashes')})
            rows = _rows(db, 'SELECT workspace_id FROM reliability_eval_corpora WHERE id=?', (value['id'],))
            if rows:
                old = self._corpus(db, ws, value['id'])
                if old['corpus_hash'] != value['corpus_hash']:
                    raise WorkspaceConflict()
                return {'id': old['id'], 'version': old['version'], 'corpus_hash': old['corpus_hash'], 'replayed': True}
            if db.execute('SELECT COUNT(*) FROM reliability_eval_corpora WHERE workspace_id=?', (ws,)).fetchone()[0] >= 50:
                raise WorkspaceConflict()
            db.execute('INSERT INTO reliability_eval_corpora VALUES(?,?,?,?)', (value['id'], ws, _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'reliability.evaluation.corpus', value['id'], 1)
            return {key: value[key] for key in ('id', 'version', 'corpus_hash')}

    def configure_plan(self, ws, body, actor):
        exact(body, ('revision', 'corpus_id', 'resource_ids', 'interval_seconds', 'jitter_seconds',
                     'per_host_budget', 'expires', 'authorized', 'notice'))
        bounded_int(body['revision'], 0, 2**31-1); bounded_int(body['interval_seconds'], 60, 86400)
        bounded_int(body['jitter_seconds'], 0, min(60, body['interval_seconds']//2)); bounded_int(body['per_host_budget'], 1, 10)
        if (body['authorized'] is not True or body['notice'] != NOTICE or not finite(body['expires'])
                or not clock() < body['expires'] <= clock()+86400 or type(body['resource_ids']) is not list
                or not 1 <= len(body['resource_ids']) <= 10 or any(type(rid) is not int or not 0 < rid < 2**31 for rid in body['resource_ids'])
                or len(set(body['resource_ids'])) != len(body['resource_ids'])):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            old = self._plan(db, ws)
            if body['revision'] != (old['revision'] if old else 0):
                raise WorkspaceConflict()
            corpus = self._corpus(db, ws, body['corpus_id'])
            pins = {str(rid): self._pin(rid, corpus['contract_id']) for rid in body['resource_ids']}
            value = {key: body[key] for key in ('corpus_id', 'interval_seconds', 'jitter_seconds', 'per_host_budget', 'expires')}
            value.update(workspace_id=ws, revision=body['revision']+1, corpus_hash=corpus['corpus_hash'],
                         pins=pins, created=clock(), **revision_authority(member, user, actor))
            self._put(db, 'plan', value)
            self.access._audit(db, actor, ws, 'reliability.evaluation.plan', ws, value['revision'])
            return {key: value[key] for key in ('revision', 'corpus_id', 'corpus_hash', 'interval_seconds', 'jitter_seconds', 'per_host_budget', 'expires')}

    def _current(self, db, ws, actor):
        member, user = self.scope(ws, actor, write=True, owner=True)
        plan = self._plan(db, ws); control = self._control(db, ws)
        if (not plan or not control['enabled'] or plan['expires'] <= clock()
                or plan.get('restore_quarantined') or control.get('restore_quarantined')):
            raise WorkspaceConflict()
        if any(plan.get(key) != value for key, value in revision_authority(member, user, actor).items()):
            raise WorkspaceConflict()
        corpus = self._corpus(db, ws, plan['corpus_id'])
        if corpus['corpus_hash'] != plan['corpus_hash']:
            raise WorkspaceConflict()
        controls = _rows(db, 'SELECT invoke_enabled,workflow_enabled FROM execution_controls WHERE id=1')
        if len(controls) != 1 or not all(controls[0][key] == 1 for key in ('invoke_enabled', 'workflow_enabled')):
            raise WorkspaceConflict()
        for rid, pin in plan['pins'].items():
            if self._pin(int(rid), corpus['contract_id']) != pin:
                raise WorkspaceConflict()
        return plan, corpus, control

    def reserve(self, ws, body, actor):
        exact(body, ('revision', 'authorized', 'notice'))
        if type(body['revision']) is not int or body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            plan, corpus, control = self._current(db, ws, actor)
            if body['revision'] != plan['revision']:
                raise WorkspaceConflict()
            now = clock(); self._recover(db, ws, now)
            window = math.floor(now/plan['interval_seconds'])*plan['interval_seconds']
            total_jobs = db.execute('SELECT COUNT(*) FROM reliability_eval_jobs WHERE workspace_id=?', (ws,)).fetchone()[0]
            if total_jobs >= 500:
                raise WorkspaceConflict()
            jobs = []; deferred = 0
            cases = (self.research.prioritize(db, ws, plan, corpus, actor, window)
                     if self.research is not None else corpus['cases'])
            resources = (self.research.prioritize_resources(db, ws, plan, corpus, actor, window)
                         if self.research is not None else sorted(plan['pins'].items()))
            for rid, pin in resources:
                for case in cases:
                    logical = _hash([ws, plan['revision'], corpus['corpus_hash'], rid, case['case_id'], window])
                    existing = _rows(db, 'SELECT id FROM reliability_eval_jobs WHERE logical_key=?', (logical,))
                    if existing:
                        jobs.append(self._job_dto(self._job(db, ws, existing[0]['id']))); continue
                    used = db.execute('''SELECT COUNT(*) FROM reliability_eval_jobs WHERE host_key=? AND window_start<?
                        AND expires>?''', (pin['host_key'], window+plan['interval_seconds'], window)).fetchone()[0]
                    active = self._active_host_jobs(db, pin['host_key'], now)
                    if used >= plan['per_host_budget'] or active or len(jobs) >= 16 or total_jobs >= 500:
                        deferred += 1; continue
                    jitter = int(logical[-8:], 16) % (plan['jitter_seconds']+1)
                    value = {'id': 'rej_'+secrets.token_hex(16), 'workspace_id': ws, 'logical_key': logical,
                             'state': 'reserved', 'host_key': pin['host_key'], 'window_start': window,
                             'resource_id': int(rid), 'case_id': case['case_id'], 'corpus_version': corpus['version'],
                             'plan_revision': plan['revision'], 'control_revision': control['revision'],
                             'not_before': max(window+jitter, plan['created']), 'expires': min(window+plan['interval_seconds'], plan['expires']),
                             'created': now, 'prepared_at': None, 'dispatched_at': None, 'finished_at': None,
                             'observed_at': None, 'outcome': None, 'reason': None}
                    self._put(db, 'job', value); jobs.append(self._job_dto(value)); total_jobs += 1
            return {'jobs': jobs, 'deferred_cases': deferred, 'window_start': window, 'provider_calls': 0}

    def prepare(self, ws, identity, body, actor):
        exact(body, ('authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            plan, _, control = self._current(db, ws, actor)
            now = clock(); self._recover(db, ws, now); value = self._job(db, ws, identity)
            if self.research is not None:
                self.research.guard_job(db, ws, plan, value, actor)
            if value['state'] in ('completed', 'failed', 'unknown', 'expired'):
                return self._job_dto(value)
            if (value['state'] != 'reserved' or value['plan_revision'] != plan['revision']
                    or value['control_revision'] != control['revision'] or value['not_before'] > now):
                raise WorkspaceConflict()
            active = self._active_host_jobs(db, value['host_key'], now, identity)
            if active:
                raise WorkspaceConflict()
            value.update(state='prepared', prepared_at=now)
            self._put(db, 'job', value)
            return self._job_dto(value)

    def _dispatch_fence(self, ws, identity, actor, envelope, stopped):
        """Recheck authority at the final provider packet boundary, without I/O."""
        if stopped is not None and stopped():
            raise WorkspaceConflict()
        with self.access._tx(actor, write=True) as (db, _):
            plan, corpus, control = self._current(db, ws, actor)
            value = self._job(db, ws, identity)
            if self.research is not None:
                self.research.guard_job(db, ws, plan, value, actor)
            if (value['state'] != 'dispatched' or value['expires'] <= clock()
                    or value['plan_revision'] != plan['revision']
                    or value['control_revision'] != control['revision']
                    or envelope['pin'] != plan['pins'][str(value['resource_id'])]['pin']
                    or envelope['corpus_hash'] != corpus['corpus_hash']
                    or envelope['case'] != next(case for case in corpus['cases'] if case['case_id'] == value['case_id'])
                    or not self._adapter_configured()
                    or self.evaluator_authorizer(ws, plan, value, actor) is not True
                    or stopped is not None and stopped()):
                raise WorkspaceConflict()

    @staticmethod
    def _response_proof(proof, envelope, outcome, observed):
        """A trusted adapter observation is not a remote packet receipt."""
        from .reliability_evaluation_worker import RESPONSE_PROOF
        expected = {'profile': RESPONSE_PROOF, 'job_id': envelope['job_id'],
                    'purpose': envelope['purpose'], 'resource_id': envelope['resource_id'],
                    'contract_id': envelope['contract_id'], 'corpus_hash': envelope['corpus_hash'],
                    'case_hash': _hash(envelope['case']), 'pin_hash': _hash(envelope['pin']),
                    'envelope_hash': _hash(envelope), 'outcome': outcome, 'observed_at': observed}
        return (type(proof) is dict and set(proof) == set(expected) | {'dispatch_guard_passed', 'response_validated'}
                and all(proof.get(key) == value for key, value in expected.items())
                and type(proof['dispatch_guard_passed']) is bool
                and type(proof['response_validated']) is bool
                and proof['response_validated'] == (outcome == 'completed')
                and (outcome != 'completed' or proof['dispatch_guard_passed'] is True))

    def response_evidence_in_transaction(self, db, ws, identity, actor):
        """Read current signed adapter evidence in the caller's exact transaction."""
        if db is not self.store._db or not db.in_transaction:
            raise WorkspaceConflict()
        plan, corpus, control = self._current(db, ws, actor)
        job = self._job(db, ws, identity)
        if (job.get('restore_quarantined') or job['state'] not in ('completed', 'failed', 'unknown')
                or job['outcome'] != job['state'] or job['plan_revision'] != plan['revision']
                or job['control_revision'] != control['revision'] or job['expires'] <= clock()
                or not all(finite(job.get(key)) for key in ('prepared_at', 'dispatched_at', 'observed_at', 'finished_at'))
                or not job['created'] <= job['prepared_at'] <= job['dispatched_at'] <= job['observed_at'] <= job['finished_at'] <= clock()):
            raise WorkspaceConflict()
        case = next((case for case in corpus['cases'] if case['case_id'] == job['case_id']), None)
        envelope = {'job_id': identity, 'purpose': 'approved_read_evaluation', 'resource_id': job['resource_id'],
                    'contract_id': corpus['contract_id'], 'corpus_hash': corpus['corpus_hash'], 'case': case,
                    'pin': plan['pins'][str(job['resource_id'])]['pin'], 'deadline': job['expires']}
        if not self._response_proof(job.get('response_proof'), envelope, job['state'], job['observed_at']):
            raise WorkspaceConflict()
        return job

    def dispatch(self, ws, identity, body, actor, *, _stopped=None):
        exact(body, ('authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        # Only an injected trusted purpose authorizer can enable evaluation calls.
        if not self._adapter_configured() or _stopped is not None and not callable(_stopped):
            raise WorkspaceConflict()
        with self.access._tx(actor, write=True) as (db, _):
            plan, corpus, control = self._current(db, ws, actor)
            now = clock(); self._recover(db, ws, now); value = self._job(db, ws, identity)
            if self.research is not None:
                self.research.guard_job(db, ws, plan, value, actor)
            if value['state'] in ('dispatched', 'completed', 'failed', 'unknown', 'expired'):
                return self._job_dto(value)
            if (value['state'] != 'prepared' or value['plan_revision'] != plan['revision']
                    or value['control_revision'] != control['revision'] or value['not_before'] > now
                    or self.evaluator_authorizer(ws, plan, value, actor) is not True):
                raise WorkspaceConflict()
            case = next(case for case in corpus['cases'] if case['case_id'] == value['case_id'])
            envelope = {'job_id': identity, 'purpose': 'approved_read_evaluation', 'resource_id': value['resource_id'],
                        'contract_id': corpus['contract_id'], 'corpus_hash': corpus['corpus_hash'], 'case': case,
                        'pin': plan['pins'][str(value['resource_id'])]['pin'], 'deadline': value['expires']}
            value.update(state='dispatched', dispatched_at=now)
            self._put(db, 'job', value)
        # An interruption after this durable boundary remains unknown; never replay.
        adapter = self.read_evaluator
        try:
            guarded = getattr(adapter, 'dispatch', None)
            if callable(guarded):
                result = guarded(envelope, before_dispatch=lambda: self._dispatch_fence(ws, identity, actor, envelope, _stopped))
            else:
                result = adapter(envelope)
        except Exception:
            result = None
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            value = self._job(db, ws, identity); now = clock()
            if value['state'] != 'dispatched':
                return self._job_dto(value)
            valid = (type(result) is dict and set(result) in ({'outcome', 'observed_at', 'evidence_ref'},
                     {'outcome', 'observed_at', 'evidence_ref', 'research_observation'},
                     {'outcome', 'observed_at', 'evidence_ref', 'response_proof'},
                     {'outcome', 'observed_at', 'evidence_ref', 'research_observation', 'response_proof'})
                     and result.get('outcome') in ('completed', 'failed', 'unknown')
                     and finite(result.get('observed_at')) and value['dispatched_at'] <= result['observed_at'] <= now
                     and type(result.get('evidence_ref')) is str and re.fullmatch(r'[a-z0-9_-]{1,100}', result['evidence_ref']))
            try:
                current, _, current_control = self._current(db, ws, actor)
                still_current = current['revision'] == value['plan_revision'] and current_control['revision'] == value['control_revision']
                if self.research is not None:
                    self.research.guard_job(db, ws, current, value, actor)
            except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
                still_current = False
            state = result['outcome'] if valid and still_current and value['expires'] > now and not (_stopped and _stopped()) else 'unknown'
            from .reliability_evaluation_worker import McpReadEvaluator
            if (valid and still_current and state == result['outcome']
                    and type(adapter) is McpReadEvaluator and adapter is self.read_evaluator
                    and adapter.evaluation is self and adapter.configured
                    and self._response_proof(result.get('response_proof'), envelope, state, result['observed_at'])):
                value['response_proof'] = result['response_proof']
            if valid and still_current and self.research is not None and result.get('research_observation') is not None:
                try:
                    value['research_observation'] = self.research.accept_observation(result['research_observation'], envelope)
                except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid, TypeError, ValueError):
                    state = 'unknown'
            value.update(state=state, finished_at=now, outcome=state,
                         observed_at=result['observed_at'] if valid else None,
                         evidence_ref=result['evidence_ref'] if valid else None,
                         reason=None if state in ('completed', 'failed') else 'dispatch_uncertain')
            self._put(db, 'job', value)
            return self._job_dto(value)

    def cancel(self, ws, identity, body, actor):
        exact(body, ('authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            value = self._job(db, ws, identity)
            if value['state'] in ('reserved', 'prepared', 'dispatched'):
                value.update(state='unknown' if value['state'] == 'dispatched' else 'expired',
                             finished_at=clock(), reason='owner_cancelled_after_dispatch' if value['state'] == 'dispatched' else 'owner_cancelled')
                self._put(db, 'job', value)
                self.access._audit(db, actor, ws, 'reliability.evaluation.cancel', identity, value['plan_revision'])
            return self._job_dto(value)

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor); now = clock(); self._recover(db, ws, now)
            plan = self._plan(db, ws)
            rows = _rows(db, 'SELECT id FROM reliability_eval_jobs WHERE workspace_id=? ORDER BY window_start DESC,id LIMIT 501', (ws,))
            if len(rows) > 500:
                raise WorkspaceConflict()
            jobs = [self._job(db, ws, row['id']) for row in rows]
            expected = 0; windows = 0; oldest_due = None; current_jobs = []
            if plan:
                corpus = self._corpus(db, ws, plan['corpus_id'])
                start = math.floor(plan['created']/plan['interval_seconds'])*plan['interval_seconds']
                end = min(now, plan['expires'])
                windows = max(0, math.floor((end-start)/plan['interval_seconds'])+int(end < plan['expires']))
                expected = windows*len(plan['pins'])*len(corpus['cases'])
                current_jobs = [job for job in jobs if job['plan_revision'] == plan['revision'] and not job.get('restore_quarantined')]
                completed_keys = {job['logical_key'] for job in current_jobs if job['state'] == 'completed'}
                debt = max(0, expected-len(completed_keys))
                if debt:
                    per_window = len(plan['pins'])*len(corpus['cases'])
                    completed_windows = {}
                    for job in current_jobs:
                        if job['state'] == 'completed':
                            completed_windows[job['window_start']] = completed_windows.get(job['window_start'], 0)+1
                    for index in range(windows):
                        due = start+index*plan['interval_seconds']
                        if completed_windows.get(due, 0) < per_window:
                            oldest_due = max(due, plan['created']); break
            else:
                debt = 0
            observed = [job['observed_at'] for job in current_jobs if job['state'] == 'completed' and job['observed_at'] is not None]
            return {'profile': PROFILE, 'control': self._control(db, ws),
                    'plan': ({key: plan[key] for key in ('revision', 'corpus_id', 'interval_seconds', 'per_host_budget', 'expires')}
                             | {'restore_quarantined': bool(plan.get('restore_quarantined'))}) if plan else None,
                    'jobs': [self._job_dto(job) for job in jobs],
                    'coverage': {'plan_revision': plan['revision'] if plan else None,
                                 'expected_cases': expected, 'scheduled_cases': len(current_jobs), 'windows': windows,
                                 'debt_cases': debt, 'oldest_due_at': oldest_due,
                                 'delay_seconds': max(0, now-oldest_due) if oldest_due is not None else 0,
                                 'latest_actual_observed_at': max(observed) if observed else None},
                    'automatic_worker_enabled': self._worker_enabled(), 'business_dispatches': 0,
                    'quality_status': 'not_inferred_from_scheduler'}
