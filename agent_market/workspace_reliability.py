"""Bounded private evaluation contracts and retained source fidelity.

No request can qualify its own evaluator, establish a holdout, dispatch a provider
or activate a public badge. Trusted evaluator adapters return bounded local
verdicts. Remote judge work requires a separately authorized producer; configuring
this interface does not authorize network calls or additional input sharing.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
import re
import secrets
import threading

from .capability_contracts import CONTRACTS
from .capability_registry import digest, version_parts
from .evidence_rollups import EvidenceRollups
from .private_artifact_keys import ArtifactCipher, ArtifactKeyError
from .shadow_ledger import SignedWorkspaceModule, clock, exact, identifier
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash, _rows

PROFILE = 'bounded-reliability-evidence-v1'
NOTICE = 'reliability-contract-authorization-v1'
RETENTION_NOTICE = 'reliability-source-retention-v1'
ERASE_NOTICE = 'reliability-permanent-erasure-v1'
OPERATING_NOTICE = 'independent-operating-read-qualification-v1'
PURPOSE = 'independent-read-evaluation'
MAX_OBJECTS, MAX_VERSIONS, MAX_OBSERVATIONS, MAX_SOURCES = 100, 32, 400, 200
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS reliability_objects (
       id TEXT NOT NULL,workspace_id TEXT NOT NULL,revision INTEGER NOT NULL,kind TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(id,revision))''',
    '''CREATE TABLE IF NOT EXISTS reliability_consents (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,cohort_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_sources (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,cohort_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_observations (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,cohort_id TEXT NOT NULL,logical_task_id TEXT NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_tombstones (
       workspace_id TEXT NOT NULL,target_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL,
       PRIMARY KEY(workspace_id,target_id))''',
    '''CREATE TABLE IF NOT EXISTS reliability_commands (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_restore_blocks (authority_id TEXT PRIMARY KEY)''',
    '''CREATE TABLE IF NOT EXISTS reliability_operating_qualifications (
       workspace_id TEXT NOT NULL,resource_id INTEGER NOT NULL,revision INTEGER NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(workspace_id,resource_id))''',
)


@dataclass(frozen=True)
class EvaluatorVerdict:
    """Trusted assessment result; dispatch reads its signed local cache only."""
    binding_hash: str
    evaluator_id: str
    qualification_hash: str
    independence_hash: str
    expires: float
    environment: str
    quality: str
    source_fidelity: str
    reviewer_count: int = 1
    reviewer_agreement: float | None = None


@dataclass(frozen=True)
class OperatingEvidenceApproval:
    """Trusted server qualification, never supplied as a client-claimed verdict."""
    binding_hash: str
    qualification_hash: str
    approval_hash: str
    expires: float


def _number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise WorkspaceInvalid()
    return value


def _int(value, low, high):
    if type(value) is not int or not low <= value <= high: raise WorkspaceInvalid()
    return value


def _label(value):
    if type(value) is not str or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,79}', value): raise WorkspaceInvalid()
    return value


def _digest(value):
    if type(value) is not str or not re.fullmatch(r'[0-9a-f]{64}', value): raise WorkspaceInvalid()
    return value


class ReliabilityEvidence(SignedWorkspaceModule):
    _rid = staticmethod(EvidenceRollups._rid)

    def __init__(self, access, execution, *, evaluator=None, cipher=None, operating_qualifier=None):
        if (execution.access is not access or evaluator is not None and not callable(evaluator)
                or operating_qualifier is not None and not callable(operating_qualifier)):
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.execution = execution
        self._assessment_lock = threading.RLock()
        self._verdict_cache = {}
        self._evaluator = evaluator
        self._evaluator_generation = secrets.token_hex(16)
        self._operating_qualifier = operating_qualifier
        self._qualifier_generation = secrets.token_hex(16)
        self.typed_evidence = None
        self.cipher = cipher if cipher is not None else ArtifactCipher(PROFILE + ':sources')

    @property
    def evaluator(self):
        return self._evaluator

    @evaluator.setter
    def evaluator(self, value):
        if value is not None and not callable(value):
            raise WorkspaceInvalid()
        with self._assessment_lock:
            self._evaluator = value
            self._evaluator_generation = secrets.token_hex(16)
            self._verdict_cache.clear()

    @property
    def operating_qualifier(self):
        return self._operating_qualifier

    @operating_qualifier.setter
    def operating_qualifier(self, value):
        if value is not None and not callable(value):
            raise WorkspaceInvalid()
        self._operating_qualifier = value
        # Restart/configuration changes require a fresh independent approval.
        self._qualifier_generation = secrets.token_hex(16)

    def _authority(self, db, ws, owner_id):
        rows = _rows(db, '''SELECT w.revision AS workspace_revision,m.revision AS member_revision,
            m.role AS member_role,u.role AS user_role,u.updated_at AS user_updated
            FROM organization_workspaces w JOIN workspace_memberships m ON m.workspace_id=w.id
            JOIN admin_users u ON u.id=m.user_id WHERE w.id=? AND w.active=1 AND m.user_id=?
            AND m.active=1 AND m.role='owner' AND u.active=1 AND u.role IN ('admin','superadmin')''', (ws, owner_id))
        if len(rows) != 1: raise WorkspaceDenied()
        return {'owner_id': owner_id, **rows[0]}

    def _resource(self, db, rid):
        resource, current, controls = EvidenceRollups._resource(self, db, rid)
        _, schema_hash, _, _ = version_parts(resource)
        current['schema_hash'] = schema_hash
        return resource, current, controls

    def _tombstones(self, db, ws):
        rows = _rows(db, 'SELECT * FROM reliability_tombstones WHERE workspace_id=? LIMIT 2001', (ws,))
        if len(rows) > 2000: raise WorkspaceConflict()
        result = {}
        for row in rows:
            value = self.opened(row)
            if value['workspace_id'] != ws or value['target_id'] != row['target_id']: raise WorkspaceConflict()
            result[row['target_id']] = value
        return result

    def _object(self, db, ws, oid, *, revision=None, current=True):
        identifier(oid, 'reo')
        rows = _rows(db, 'SELECT * FROM reliability_objects WHERE id=? AND workspace_id=? ORDER BY revision DESC LIMIT 33', (oid, ws))
        if not rows: raise WorkspaceDenied()
        if len(rows) > MAX_VERSIONS: raise WorkspaceConflict()
        values = []
        for row in rows:
            value = self.opened(row)
            if any(value[key] != row[key] for key in ('id', 'workspace_id', 'revision', 'kind')): raise WorkspaceConflict()
            values.append(value)
        if sorted(v['revision'] for v in values) != list(range(1, len(values)+1)): raise WorkspaceConflict()
        value = values[0] if revision is None else next((v for v in values if v['revision'] == revision), None)
        if value is None: raise WorkspaceDenied()
        if current and (value != values[0] or oid in self._tombstones(db, ws)): raise WorkspaceConflict()
        return value

    @staticmethod
    def _dto(value):
        return {key: value[key] for key in ('id', 'kind', 'revision', 'spec', 'created')}

    def _command(self, db, ws, body, actor):
        identifier(body['command_id'], 'rec')
        rows = _rows(db, 'SELECT * FROM reliability_commands WHERE id=?', (body['command_id'],))
        if rows:
            value = self.opened(rows[0])
            if value['workspace_id'] != ws or value['request_hash'] != _hash(body) or value['actor_user_id'] != actor.user_id:
                raise WorkspaceConflict()
            return value['result'] | {'replayed': True}
        if db.execute('SELECT COUNT(*) FROM reliability_commands WHERE workspace_id=?', (ws,)).fetchone()[0] >= 2000:
            raise WorkspaceConflict()
        return None

    def _record(self, db, ws, body, actor, result):
        value = {'id': body['command_id'], 'workspace_id': ws, 'request_hash': _hash(body),
                 'actor_user_id': actor.user_id, 'created': clock(), 'result': result}
        db.execute('INSERT INTO reliability_commands VALUES(?,?,?,?)', (value['id'], ws, _canonical(value), self.sign(value)))
        self.access._audit(db, actor, ws, 'reliability.' + result.get('action', 'write'), result.get('id'), result.get('revision'))
        return result

    @staticmethod
    def _authorized(body, notice=NOTICE):
        if body['authorized'] is not True or body['notice'] != notice: raise WorkspaceInvalid()

    def _spec(self, db, ws, kind, spec):
        if kind == 'plan':
            exact(spec, ('dataset_version', 'dataset_hash', 'rubric_version', 'rubric_hash', 'minimum_samples',
                         'window_seconds', 'confidence', 'environment', 'evaluator_version'))
            for name in ('dataset_version', 'rubric_version', 'evaluator_version'): _label(spec[name])
            for name in ('dataset_hash', 'rubric_hash'): _digest(spec[name])
            _int(spec['minimum_samples'], 2, MAX_OBSERVATIONS); _int(spec['window_seconds'], 60, 604800)
            if spec['confidence'] != 'wilson-95-v1' or spec['environment'] not in ('synthetic', 'isolated', 'approved_external'):
                raise WorkspaceInvalid()
        elif kind == 'case':
            exact(spec, ('plan_id', 'plan_revision', 'case_version', 'case_hash', 'category'))
            _label(spec['case_version']); _digest(spec['case_hash']); _int(spec['plan_revision'], 1, MAX_VERSIONS)
            plan = self._object(db, ws, spec['plan_id'], revision=spec['plan_revision'])
            if plan['kind'] != 'plan' or spec['category'] not in ('repeatability', 'semantic_variant', 'schema_drift', 'response_loss', 'baseline'):
                raise WorkspaceInvalid()
        elif kind == 'cohort':
            exact(spec, ('plan_id', 'plan_revision', 'case_ids', 'resource_id', 'contract_id', 'purpose'))
            _int(spec['plan_revision'], 1, MAX_VERSIONS)
            plan = self._object(db, ws, spec['plan_id'], revision=spec['plan_revision'])
            if (plan['kind'] != 'plan' or spec['contract_id'] not in CONTRACTS or spec['purpose'] != PURPOSE
                    or type(spec['case_ids']) is not list or not 1 <= len(spec['case_ids']) <= 20
                    or len(set(spec['case_ids'])) != len(spec['case_ids'])): raise WorkspaceInvalid()
            self._resource(db, spec['resource_id'])
            for case_id in spec['case_ids']:
                case = self._object(db, ws, case_id)
                if case['kind'] != 'case' or any(case['spec'][k] != spec[k] for k in ('plan_id', 'plan_revision')): raise WorkspaceInvalid()
        else: raise WorkspaceInvalid()

    def options(self, ws, actor):
        with self.access._tx(actor) as (db, user):
            member, _ = self.scope(ws, actor)
            return {'profile': PROFILE, 'can_manage': member['member_role'] == 'owner' and user['role'] != 'operator',
                    'notices': {'contract': NOTICE, 'retain': RETENTION_NOTICE, 'erase': ERASE_NOTICE},
                    'purpose': PURPOSE, 'encryption_configured': self.cipher.configured,
                    'trusted_evaluator_configured': self.evaluator is not None,
                    'provider_calls': 0, 'public_activation': False, 'operating_qualification': False}

    def save_object(self, ws, body, actor):
        exact(body, ('command_id', 'object_id', 'kind', 'revision', 'spec', 'authorized', 'notice'))
        self._authorized(body); identifier(body['object_id'], 'reo'); _int(body['revision'], 0, MAX_VERSIONS-1)
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            replay = self._command(db, ws, body, actor)
            if replay is not None: return replay
            if body['object_id'] in self._tombstones(db, ws): raise WorkspaceConflict()
            prior = _rows(db, 'SELECT * FROM reliability_objects WHERE id=? ORDER BY revision DESC LIMIT 1', (body['object_id'],))
            if prior:
                previous = self._object(db, ws, body['object_id'])
                if previous['revision'] != body['revision'] or previous['kind'] != body['kind']: raise WorkspaceConflict()
            elif body['revision'] != 0: raise WorkspaceConflict()
            if db.execute('SELECT COUNT(*) FROM reliability_objects WHERE workspace_id=? AND revision=1', (ws,)).fetchone()[0] >= MAX_OBJECTS and not prior:
                raise WorkspaceConflict()
            self._spec(db, ws, body['kind'], body['spec'])
            value = {'id': body['object_id'], 'workspace_id': ws, 'kind': body['kind'], 'revision': body['revision']+1,
                     'spec': body['spec'], 'created': clock(), 'owner_id': actor.user_id}
            db.execute('INSERT INTO reliability_objects VALUES(?,?,?,?,?,?)',
                       (value['id'], ws, value['revision'], value['kind'], _canonical(value), self.sign(value)))
            return self._record(db, ws, body, actor, self._dto(value))

    def list_objects(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            rows = _rows(db, 'SELECT * FROM reliability_objects WHERE workspace_id=? ORDER BY id,revision LIMIT 3201', (ws,))
            if len(rows) > 3200: raise WorkspaceConflict()
            tombstones = self._tombstones(db, ws)
            return [self._dto(self.opened(row)) | {'revoked': row['id'] in tombstones} for row in rows]

    def authorize_cohort(self, ws, body, actor):
        exact(body, ('command_id', 'consent_id', 'cohort_id', 'cohort_revision', 'retention_seconds', 'authorized', 'notice'))
        self._authorized(body, RETENTION_NOTICE); identifier(body['consent_id'], 'ren'); _int(body['retention_seconds'], 60, 604800)
        _int(body['cohort_revision'], 1, MAX_VERSIONS)
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            replay = self._command(db, ws, body, actor)
            if replay is not None: return replay
            cohort = self._object(db, ws, body['cohort_id'], revision=body['cohort_revision'])
            if cohort['kind'] != 'cohort': raise WorkspaceInvalid()
            self._spec(db, ws, 'cohort', cohort['spec'])
            _, current, controls = self._resource(db, cohort['spec']['resource_id'])
            cases = [self._object(db, ws, cid) for cid in cohort['spec']['case_ids']]
            now = clock()
            value = {'id': body['consent_id'], 'workspace_id': ws, 'cohort_id': cohort['id'], 'cohort_revision': cohort['revision'],
                     'cohort_hash': _hash(cohort), 'case_pins': {c['id']: [c['revision'], _hash(c)] for c in cases},
                     'authority': self._authority(db, ws, actor.user_id), 'current': current, 'controls': controls,
                     'contract_hash': digest(CONTRACTS[cohort['spec']['contract_id']]), 'purpose': PURPOSE,
                     'created': now, 'expires': now + body['retention_seconds']}
            if db.execute('SELECT 1 FROM reliability_consents WHERE id=?', (value['id'],)).fetchone(): raise WorkspaceConflict()
            if db.execute('SELECT COUNT(*) FROM reliability_consents WHERE workspace_id=?', (ws,)).fetchone()[0] >= 200: raise WorkspaceConflict()
            db.execute('INSERT INTO reliability_consents VALUES(?,?,?,?,?)', (value['id'], ws, cohort['id'], _canonical(value), self.sign(value)))
            return self._record(db, ws, body, actor, {'id': value['id'], 'cohort_id': cohort['id'], 'expires': value['expires'], 'revision': 1})

    def _consent(self, db, ws, cid):
        identifier(cid, 'ren')
        rows = _rows(db, 'SELECT * FROM reliability_consents WHERE id=? AND workspace_id=?', (cid, ws))
        if len(rows) != 1: raise WorkspaceDenied()
        value = self.opened(rows[0]); tombstones = self._tombstones(db, ws)
        if any(value[k] != rows[0][k] for k in ('id', 'workspace_id', 'cohort_id')): raise WorkspaceConflict()
        if (cid in tombstones or value['expires'] <= clock()
                or db.execute('SELECT 1 FROM reliability_restore_blocks WHERE authority_id=?', (cid,)).fetchone()): raise WorkspaceConflict()
        cohort = self._object(db, ws, value['cohort_id'], revision=value['cohort_revision'])
        self._spec(db, ws, 'cohort', cohort['spec'])
        _, current, controls = self._resource(db, cohort['spec']['resource_id'])
        if (value['cohort_hash'] != _hash(cohort) or value['authority'] != self._authority(db, ws, value['authority']['owner_id'])
                or value['current'] != current or value['controls'] != controls
                or value['contract_hash'] != digest(CONTRACTS[cohort['spec']['contract_id']])): raise WorkspaceConflict()
        for case_id, pin in value['case_pins'].items():
            case = self._object(db, ws, case_id, revision=pin[0])
            if _hash(case) != pin[1]: raise WorkspaceConflict()
        return value, cohort

    def _source(self, db, ws, sid, consent):
        identifier(sid, 'res')
        rows = _rows(db, 'SELECT * FROM reliability_sources WHERE id=? AND workspace_id=?', (sid, ws))
        if len(rows) != 1: raise WorkspaceDenied()
        value = self.opened(rows[0]); tombstones = self._tombstones(db, ws)
        if any(value[k] != rows[0][k] for k in ('id', 'workspace_id', 'cohort_id')): raise WorkspaceConflict()
        if (value['consent_id'] != consent['id'] or value['expires'] <= clock() or sid in tombstones
                or 'hash:' + value['bundle_hash'] in tombstones): raise WorkspaceConflict()
        return value

    @staticmethod
    def _context(source):
        return {k: source[k] for k in ('id', 'workspace_id', 'cohort_id', 'consent_id', 'purpose', 'bundle_hash', 'expires')}

    def retain_source(self, ws, body, actor):
        exact(body, ('command_id', 'source_id', 'consent_id', 'bundle', 'authorized', 'notice'))
        self._authorized(body, RETENTION_NOTICE); identifier(body['source_id'], 'res')
        exact(body['bundle'], ('input', 'output', 'sources'))
        encoded = _canonical(body['bundle']).encode('ascii')
        if len(encoded) > 32768 or type(body['bundle']['sources']) is not list or len(body['bundle']['sources']) > 20: raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            consent, cohort = self._consent(db, ws, body['consent_id'])
            replay = self._command(db, ws, body, actor)
            if replay is not None: return replay
            bundle_hash = _hash(body['bundle']); tombstones = self._tombstones(db, ws)
            if body['source_id'] in tombstones or 'hash:' + bundle_hash in tombstones: raise WorkspaceConflict()
            if db.execute('SELECT 1 FROM reliability_sources WHERE id=?', (body['source_id'],)).fetchone(): raise WorkspaceConflict()
            if db.execute('SELECT COUNT(*) FROM reliability_sources WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_SOURCES: raise WorkspaceConflict()
            value = {'id': body['source_id'], 'workspace_id': ws, 'cohort_id': cohort['id'], 'consent_id': consent['id'],
                     'purpose': PURPOSE, 'created': clock(), 'expires': consent['expires'], 'bundle_hash': bundle_hash}
            try: value['encrypted_bundle'] = json.loads(self.cipher.seal(encoded, self._context(value)))
            except ArtifactKeyError: raise WorkspaceConflict() from None
            db.execute('INSERT INTO reliability_sources VALUES(?,?,?,?,?)', (value['id'], ws, cohort['id'], _canonical(value), self.sign(value)))
            return self._record(db, ws, body, actor, {k: value[k] for k in ('id', 'cohort_id', 'expires', 'bundle_hash')})

    def _retained(self, source):
        try:
            bundle = json.loads(self.cipher.open(_canonical(source['encrypted_bundle']).encode('ascii'), self._context(source)))
            exact(bundle, ('input', 'output', 'sources'))
            if _hash(bundle) != source['bundle_hash']: raise WorkspaceConflict()
            return bundle
        except (ArtifactKeyError, ValueError, TypeError, UnicodeError): raise WorkspaceConflict() from None

    def _run_source(self, db, ws, resource, current, source_ref, source_map=None):
        if self.typed_evidence is not None and self.typed_evidence.accepts(source_ref):
            return self.typed_evidence.resolve_source(db, ws, resource, current, source_ref)
        if source_map is None:
            sources, _ = EvidenceRollups._private(self, db, ws, resource, current)
            source_map = {source['ref']: source for source in sources}
        source = source_map.get(source_ref)
        if (source is None or source['version'] != current['version_id'] or not source['current'] or source.get('not_dispatched')
                or source['outcome'] not in ('succeeded', 'failed', 'unknown')
                or not all(type(source[k]) in (int, float) and math.isfinite(source[k]) for k in ('started', 'finished', 'expires'))
                or not 0 < source['started'] <= source['finished'] <= clock() or source['expires'] <= clock()): raise WorkspaceConflict()
        return source

    def _bind_bundle(self, db, ws, run_ref, source):
        if self.typed_evidence is not None and self.typed_evidence.accepts(run_ref):
            return self.typed_evidence.verify_bundle(db, ws, run_ref, source)
        rows = _rows(db, 'SELECT * FROM workspace_private_runs WHERE id=? AND workspace_id=?', (run_ref, ws))
        if len(rows) != 1: raise WorkspaceDenied()
        row = rows[0]
        _, _, _, payload = self.execution._load_run(db, run_ref, ws, row['draft_id'], row['snapshot_id'])
        snapshot = self.access._open_version(self.access._version_row(ws, row['draft_id'], row['snapshot_id']))
        node = self.execution._node(snapshot)
        bundle = self._retained(source)
        if bundle['input'] != node['data']['input'] or bundle['output'] != payload['output']: raise WorkspaceConflict()
        return bundle

    def observe(self, ws, body, actor):
        exact(body, ('command_id', 'observation_id', 'consent_id', 'case_id', 'source_id', 'run_ref', 'logical_task_id', 'authorized', 'notice'))
        self._authorized(body); identifier(body['observation_id'], 'reb'); identifier(body['logical_task_id'], 'ret')
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            consent, cohort = self._consent(db, ws, body['consent_id'])
            replay = self._command(db, ws, body, actor)
            if replay is not None: return replay
            if body['case_id'] not in consent['case_pins']: raise WorkspaceInvalid()
            source = self._source(db, ws, body['source_id'], consent)
            resource, current, _ = self._resource(db, cohort['spec']['resource_id'])
            run = self._run_source(db, ws, resource, current, body['run_ref'])
            if run['started'] < consent['created']: raise WorkspaceConflict()
            self._bind_bundle(db, ws, run['ref'], source)
            if db.execute('SELECT COUNT(*) FROM reliability_observations WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_OBSERVATIONS: raise WorkspaceConflict()
            if db.execute('SELECT 1 FROM reliability_observations WHERE id=?', (body['observation_id'],)).fetchone(): raise WorkspaceConflict()
            value = {'id': body['observation_id'], 'workspace_id': ws, 'cohort_id': cohort['id'], 'consent_id': consent['id'],
                     'case_id': body['case_id'], 'source_id': source['id'], 'logical_task_id': body['logical_task_id'],
                     'run_ref': run['ref'], 'run_hash': run['integrity'], 'outcome': run['outcome'], 'started': run['started'],
                     'finished': run['finished'], 'expires': min(run['expires'], source['expires']), 'created': clock(),
                     'agent_version': current['version_id'], 'case_pin': consent['case_pins'][body['case_id']]}
            db.execute('INSERT INTO reliability_observations VALUES(?,?,?,?,?,?)',
                       (value['id'], ws, cohort['id'], value['logical_task_id'], _canonical(value), self.sign(value)))
            return self._record(db, ws, body, actor, {k: value[k] for k in ('id', 'cohort_id', 'outcome', 'finished', 'expires')})

    def erase(self, ws, body, actor):
        exact(body, ('command_id', 'target_id', 'target_kind', 'reason', 'authorized', 'notice'))
        self._authorized(body, ERASE_NOTICE)
        if body['target_kind'] not in ('source', 'consent', 'object') or body['reason'] not in ('withdrawn', 'retention_expired', 'source_deleted'):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            replay = self._command(db, ws, body, actor)
            if replay is not None: return replay
            tombstones = self._tombstones(db, ws); target = body['target_id']; hashes = []
            if target not in tombstones:
                if body['target_kind'] == 'source':
                    identifier(target, 'res'); rows = _rows(db, 'SELECT * FROM reliability_sources WHERE id=? AND workspace_id=?', (target, ws))
                    if len(rows) != 1: raise WorkspaceDenied()
                    hashes.append(self.opened(rows[0])['bundle_hash'])
                elif body['target_kind'] == 'consent':
                    identifier(target, 'ren'); rows = _rows(db, 'SELECT * FROM reliability_consents WHERE id=? AND workspace_id=?', (target, ws))
                    if len(rows) != 1: raise WorkspaceDenied()
                    rows = _rows(db, 'SELECT * FROM reliability_sources WHERE workspace_id=? LIMIT 201', (ws,))
                    for row in rows:
                        value = self.opened(row)
                        if value['consent_id'] == target:
                            hashes.append(value['bundle_hash'])
                            db.execute('DELETE FROM reliability_sources WHERE id=? AND workspace_id=?', (value['id'], ws))
                else: self._object(db, ws, target, current=False)
                for ref in [target, *('hash:' + h for h in hashes)]:
                    if ref in tombstones: continue
                    if len(tombstones) >= 2000: raise WorkspaceConflict()
                    value = {'workspace_id': ws, 'target_id': ref, 'reason': body['reason'], 'created': clock(), 'owner_id': actor.user_id}
                    db.execute('INSERT INTO reliability_tombstones VALUES(?,?,?,?)', (ws, ref, _canonical(value), self.sign(value)))
                    tombstones[ref] = value
                if body['target_kind'] == 'source': db.execute('DELETE FROM reliability_sources WHERE id=? AND workspace_id=?', (target, ws))
            return self._record(db, ws, body, actor, {'id': target, 'erased': True, 'permanent': True, 'revision': 1})

    def erase_expired(self, ws, body, actor):
        exact(body, ('command_id', 'authorized', 'notice')); self._authorized(body, ERASE_NOTICE)
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            replay = self._command(db, ws, body, actor)
            if replay is not None: return replay
            tombstones = self._tombstones(db, ws); count = 0
            rows = _rows(db, 'SELECT * FROM reliability_sources WHERE workspace_id=? LIMIT 201', (ws,))
            if len(rows) > MAX_SOURCES: raise WorkspaceConflict()
            for row in rows:
                source = self.opened(row)
                if any(source[k] != row[k] for k in ('id', 'workspace_id', 'cohort_id')): raise WorkspaceConflict()
                if source['expires'] > clock(): continue
                for target in (source['id'], 'hash:' + source['bundle_hash']):
                    if target in tombstones: continue
                    if len(tombstones) >= 2000: raise WorkspaceConflict()
                    value = {'workspace_id': ws, 'target_id': target, 'reason': 'retention_expired', 'created': clock(), 'owner_id': actor.user_id}
                    db.execute('INSERT INTO reliability_tombstones VALUES(?,?,?,?)', (ws, target, _canonical(value), self.sign(value)))
                    tombstones[target] = value
                db.execute('DELETE FROM reliability_sources WHERE id=? AND workspace_id=?', (source['id'], ws)); count += 1
            return self._record(db, ws, body, actor, {'erased_sources': count, 'permanent': True, 'action': 'retention_cleanup'})

    def inventory(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            tombstones = self._tombstones(db, ws)
            consents = []
            for row in _rows(db, 'SELECT * FROM reliability_consents WHERE workspace_id=? LIMIT 201', (ws,)):
                value = self.opened(row); current = True
                try: self._consent(db, ws, value['id'])
                except (WorkspaceDenied, WorkspaceConflict): current = False
                consents.append({k: value[k] for k in ('id', 'cohort_id', 'cohort_revision', 'created', 'expires')} | {'current': current})
            sources = []
            for row in _rows(db, 'SELECT * FROM reliability_sources WHERE workspace_id=? LIMIT 201', (ws,)):
                value = self.opened(row)
                sources.append({k: value[k] for k in ('id', 'cohort_id', 'consent_id', 'expires', 'bundle_hash')} | {'retained': value['expires'] > clock()})
            observations = []
            for row in _rows(db, 'SELECT * FROM reliability_observations WHERE workspace_id=? ORDER BY id LIMIT 401', (ws,)):
                value = self.opened(row)
                if any(value[k] != row[k] for k in ('id', 'workspace_id', 'cohort_id', 'logical_task_id')): raise WorkspaceConflict()
                observations.append({k: value[k] for k in ('id', 'cohort_id', 'case_id', 'source_id', 'run_ref', 'logical_task_id', 'outcome', 'finished', 'expires')})
            return {'consents': consents, 'sources': sources, 'observations': observations,
                    'permanent_tombstones': len(tombstones), 'provider_calls': 0}

    def inspect_source(self, ws, sid, body, actor):
        exact(body, ('authorized', 'notice')); self._authorized(body, RETENTION_NOTICE)
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            rows = _rows(db, 'SELECT * FROM reliability_sources WHERE id=? AND workspace_id=?', (sid, ws))
            if len(rows) != 1: raise WorkspaceDenied()
            value = self.opened(rows[0]); consent, _ = self._consent(db, ws, value['consent_id'])
            source = self._source(db, ws, sid, consent); bundle = self._retained(source)
            self.access._audit(db, actor, ws, 'reliability.source.inspect', sid, None)
            return {'id': sid, 'bundle': bundle, 'purpose': PURPOSE, 'expires': source['expires'], 'public_activation': False}

    @staticmethod
    def _validated_verdict(binding, verdict):
        if type(verdict) is not EvaluatorVerdict: return None
        try:
            _label(verdict.evaluator_id); _digest(verdict.qualification_hash); _digest(verdict.independence_hash)
            _number(verdict.expires, clock(), clock()+604800)
            _int(verdict.reviewer_count, 1, 10)
            if verdict.reviewer_agreement is not None:
                _number(verdict.reviewer_agreement, 0, 1)
                if verdict.reviewer_count < 2: return None
            if (verdict.binding_hash != digest(binding) or verdict.environment != binding['environment']
                    or verdict.evaluator_id != binding['evaluator_version']
                    or verdict.quality not in ('passed', 'failed', 'unassessed')
                    or verdict.source_fidelity not in ('verified', 'failed', 'unassessable')): return None
        except WorkspaceInvalid: return None
        return verdict

    def _verdict(self, binding, bundle):
        """Local-only current verdict lookup; never invoke an evaluator here."""
        identity = digest(binding)
        with self._assessment_lock:
            cached = self._verdict_cache.get(identity)
            if cached is None or self.evaluator is None:
                return None
            value, signature = cached
            if (not self._artifact_signer.verify(value, signature)
                    or value['binding_hash'] != identity
                    or value['bundle_hash'] != digest(bundle)
                    or value['generation'] != self._evaluator_generation):
                raise WorkspaceConflict()
            if value['expires'] <= clock():
                return None
            raw = value['verdict']
            return self._validated_verdict(binding, EvaluatorVerdict(**raw)) if raw is not None else None

    def _prepare_verdicts(self, ws, resource_id, actor):
        """Assess retained sources outside DB transactions; never a dispatch hook."""
        requests = {}
        with self.access._tx(actor) as (db, user):
            member, _ = self.scope(ws, actor)
            self._current_report(db, ws, resource_id, actor, user, member, assessment_requests=requests)
        with self._assessment_lock:
            adapter, generation = self.evaluator, self._evaluator_generation
        if adapter is None:
            return
        for identity, (binding, bundle) in requests.items():
            with self._assessment_lock:
                prior = self._verdict_cache.get(identity)
                if prior and prior[0]['generation'] == generation and prior[0]['expires'] > clock():
                    continue
                if len(self._verdict_cache) >= MAX_OBSERVATIONS and identity not in self._verdict_cache:
                    raise WorkspaceConflict()
            # Callers must enter through this explicit top-level preparation,
            # never while owning a store transaction or the final dispatch fence.
            if self.store._db.in_transaction:
                raise WorkspaceConflict()
            try:
                verdict = self._validated_verdict(binding, adapter(deepcopy(binding), deepcopy(bundle)))
            except Exception:
                verdict = None
            value = {'binding_hash': identity, 'bundle_hash': digest(bundle), 'generation': generation,
                     'verdict': asdict(verdict) if verdict is not None else None,
                     'expires': verdict.expires if verdict is not None else clock()+30}
            with self._assessment_lock:
                if adapter is not self.evaluator or generation != self._evaluator_generation:
                    raise WorkspaceConflict()
                self._verdict_cache[identity] = (value, self.sign(value))

    def current_report(self, ws, resource_id, actor):
        self._prepare_verdicts(ws, resource_id, actor)
        with self.access._tx(actor) as (db, user):
            member, _ = self.scope(ws, actor)
            return self._current_report(db, ws, resource_id, actor, user, member)

    def _current_report(self, db, ws, resource_id, actor, user, member, *, assessment_requests=None):
        resource, current, _ = self._resource(db, resource_id)
        rows = _rows(db, 'SELECT * FROM reliability_observations WHERE workspace_id=? ORDER BY id LIMIT 401', (ws,))
        if len(rows) > MAX_OBSERVATIONS: raise WorkspaceConflict()
        groups = {}; excluded = {'not_current': 0, 'source_unavailable': 0, 'expired': 0, 'version_changed': 0}
        fingerprints = []; now = clock(); tombstones = self._tombstones(db, ws)
        run_sources, _ = EvidenceRollups._private(self, db, ws, resource, current)
        source_map = {source['ref']: source for source in run_sources}; consent_cache = {}
        for row in rows:
            value = self.opened(row)
            if any(value[k] != row[k] for k in ('id', 'workspace_id', 'cohort_id', 'logical_task_id')): raise WorkspaceConflict()
            fingerprints.append([row['signature'], value['id']])
            if value['consent_id'] not in consent_cache:
                try: consent_cache[value['consent_id']] = self._consent(db, ws, value['consent_id'])
                except (WorkspaceDenied, WorkspaceConflict): consent_cache[value['consent_id']] = None
            if consent_cache[value['consent_id']] is None: excluded['not_current'] += 1; continue
            consent, cohort = consent_cache[value['consent_id']]
            if cohort['spec']['resource_id'] != resource_id: continue
            if value['agent_version'] != current['version_id']: excluded['version_changed'] += 1; continue
            if value['expires'] <= now: excluded['expired'] += 1; continue
            plan = self._object(db, ws, cohort['spec']['plan_id'], revision=cohort['spec']['plan_revision'])
            policy = plan['spec']; start = max(consent['created'], now-policy['window_seconds'])
            if not start <= value['started'] <= value['finished'] <= now: excluded['expired'] += 1; continue
            try:
                run = self._run_source(db, ws, resource, current, value['run_ref'], source_map)
                if run['integrity'] != value['run_hash']: raise WorkspaceConflict()
            except (WorkspaceDenied, WorkspaceConflict): excluded['not_current'] += 1; continue
            fidelity, quality, qualified, evaluator, verdict_expiry = 'unassessable', 'unassessed', False, None, value['expires']
            agreement = None
            binding = {'workspace_id': ws, 'resource_id': resource_id, 'agent_version': current['version_id'],
                       'contract_id': cohort['spec']['contract_id'], 'contract_hash': consent['contract_hash'],
                       'schema_hash': current['schema_hash'], 'plan_id': plan['id'], 'plan_revision': plan['revision'],
                       'dataset_hash': policy['dataset_hash'], 'dataset_version': policy['dataset_version'],
                       'evaluator_version': policy['evaluator_version'],
                       'rubric_hash': policy['rubric_hash'], 'rubric_version': policy['rubric_version'],
                       'case_id': value['case_id'], 'case_pin': value['case_pin'], 'permission_revision': digest(consent),
                       'observation_hash': digest(value), 'observed_at': value['finished'], 'environment': policy['environment']}
            try:
                source = self._source(db, ws, value['source_id'], consent); binding['bundle_hash'] = source['bundle_hash']
                bundle = self._bind_bundle(db, ws, value['run_ref'], source)
                if assessment_requests is not None:
                    assessment_requests[digest(binding)] = (deepcopy(binding), bundle)
                verdict = self._verdict(binding, bundle)
                if verdict:
                    fidelity, quality, qualified, evaluator = verdict.source_fidelity, verdict.quality, True, verdict.evaluator_id
                    agreement = verdict.reviewer_agreement
                    verdict_expiry = min(verdict_expiry, verdict.expires)
                    fingerprints.append([verdict.binding_hash, verdict.qualification_hash, verdict.independence_hash, verdict.expires, quality, fidelity,
                                         verdict.reviewer_count, verdict.reviewer_agreement])
            except (WorkspaceDenied, WorkspaceConflict): excluded['source_unavailable'] += 1
            key = (cohort['id'], cohort['revision'])
            group = groups.setdefault(key, {'cohort_id': cohort['id'], 'cohort_revision': cohort['revision'],
                'contract_id': cohort['spec']['contract_id'], 'contract_revision': CONTRACTS[cohort['spec']['contract_id']]['version'],
                'contract_hash': consent['contract_hash'], 'plan_id': plan['id'], 'plan_revision': plan['revision'],
                'dataset_version': policy['dataset_version'], 'rubric_version': policy['rubric_version'],
                'evaluator_version': policy['evaluator_version'],
                'environment': policy['environment'], 'minimum_samples': policy['minimum_samples'], 'window_seconds': policy['window_seconds'],
                '_samples': [], 'expires': consent['expires']})
            # The original signed execution is a second dedupe key. A caller
            # cannot inflate samples by assigning new logical task labels.
            group['_samples'].append({'run_ref': value['run_ref'], 'logical_task_id': value['logical_task_id'],
                'outcome': value['outcome'], 'quality': quality, 'fidelity': fidelity,
                'agreement': agreement,
                'qualified': qualified, 'evaluator': evaluator, 'finished': value['finished'], 'expires': verdict_expiry,
                'latency': (value['finished']-value['started'])*1000})
        reports = []
        for group in groups.values():
            attempts = group.pop('_samples'); parents = {}
            def root(key):
                parents.setdefault(key, key)
                while parents[key] != key:
                    parents[key] = parents[parents[key]]; key = parents[key]
                return key
            for attempt in attempts:
                left, right = root('run:' + attempt['run_ref']), root('task:' + attempt['logical_task_id'])
                parents[max(left, right)] = min(left, right)
            samples = {}
            for attempt in attempts: samples.setdefault(root('run:' + attempt['run_ref']), []).append(attempt)
            outcomes = dict.fromkeys(('succeeded', 'failed', 'unknown'), 0)
            qualities = dict.fromkeys(('passed', 'failed', 'unassessed'), 0); fidelities = dict.fromkeys(('verified', 'failed', 'unassessable'), 0)
            latency = []; latest = []; expiry = [group['expires']]; duplicates = 0; qualified_count = 0; agreements = []
            for attempts in samples.values():
                duplicates += len(attempts)-1
                outcome = max((v['outcome'] for v in attempts), key=lambda s: {'succeeded': 0, 'failed': 1, 'unknown': 2}[s]); outcomes[outcome] += 1
                quality = max((v['quality'] for v in attempts), key=lambda s: {'passed': 0, 'failed': 1, 'unassessed': 2}[s]); qualities[quality] += 1
                fidelity = max((v['fidelity'] for v in attempts), key=lambda s: {'verified': 0, 'failed': 1, 'unassessable': 2}[s]); fidelities[fidelity] += 1
                qualified_count += int(all(v['qualified'] and v['quality'] != 'unassessed' for v in attempts))
                chosen = max(attempts, key=lambda v: v['finished']); latency.append(chosen['latency']); latest.append(chosen['finished'])
                if chosen['agreement'] is not None: agreements.append(chosen['agreement'])
                expiry.extend(v['expires'] for v in attempts)
            n = len(samples); latency.sort(); p = outcomes['succeeded']/n; z = 1.959963984540054
            denominator = 1+z*z/n; center = (p+z*z/(2*n))/denominator
            radius = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denominator
            group.update({'logical_samples': n, 'outcomes': outcomes, 'quality_outcomes': qualities, 'source_fidelity_outcomes': fidelities,
                'duplicates_removed': duplicates, 'independently_assessed_samples': qualified_count,
                'unassessed_ratio': qualities['unassessed']/n, 'minimum_sample_met': n >= group['minimum_samples'],
                'reviewer_agreement': {'assessed_logical_samples': len(agreements),
                    'ratio': sum(agreements)/len(agreements) if agreements else None},
                'success_interval': {'method': 'wilson-95-v1', 'lower': max(0, center-radius), 'upper': min(1, center+radius), 'denominator': n},
                'latency_ms': {'p50': latency[math.ceil(n*.5)-1], 'p95': latency[math.ceil(n*.95)-1], 'scope': 'gateway_observation_interval'},
                'latest_observed_at': max(latest), 'expires': min(expiry),
                'quality_status': 'assessed' if qualified_count == n and qualities['unassessed'] == 0 else 'unassessed',
                'source_fidelity': 'verified' if fidelities['verified'] == n else 'failed' if fidelities['failed'] else 'unassessable'})
            reports.append(group)
        result = {'profile': PROFILE, 'scope': 'workspace', 'resource_id': resource_id, 'agent_ref': 'resource:'+str(resource_id),
                  'agent_version': current['version_id'], 'schema_hash': current['schema_hash'], 'groups': sorted(reports, key=lambda v: v['cohort_id']),
                  'excluded_sources': excluded, 'quality_status': 'unassessed', 'source_fidelity': 'unassessable',
                  'qualified_operating_evidence': False, 'provider_calls': 0, 'public_activation': False}
        result['source_revision'] = digest([result, fingerprints, tombstones, member, user['role']])
        return result

    def current_projection_in_transaction(self, db, ws, resource_id, actor):
        """Trusted dispatch guard: exact caller-owned Store transaction only."""
        if db is not self.store._db or not db.in_transaction:
            raise WorkspaceConflict()
        member, user = self.scope(ws, actor)
        report = self._current_report(db, ws, resource_id, actor, user, member)
        return self._apply_operating(db, ws, resource_id, actor, self._projection(report))

    def get_agent_projection(self, ws, resource_id, actor):
        # Recommendation, notification and dispatch consumers never prepare or
        # refresh verdicts. A missing local verdict is honestly unassessed.
        with self.access._tx(actor) as (db, _):
            return self.current_projection_in_transaction(db, ws, resource_id, actor)

    def _operating(self, db, ws, resource_id):
        rows = _rows(db, 'SELECT * FROM reliability_operating_qualifications WHERE workspace_id=? AND resource_id=?', (ws, resource_id))
        if not rows:
            return None
        row = rows[0]; value = self.opened(row)
        if any(value.get(key) != row[key] for key in ('workspace_id', 'resource_id', 'revision')):
            raise WorkspaceConflict()
        return value

    def _base_projection(self, db, ws, resource_id, actor):
        member, user = self.scope(ws, actor)
        return self._projection(self._current_report(db, ws, resource_id, actor, user, member))

    @staticmethod
    def _external_qualified(source):
        return (source.get('environment') == 'approved_external'
                and source.get('independent_qualified') is True
                and source.get('quality_status') == 'assessed'
                and source.get('source_fidelity') == 'verified'
                and source.get('revoked') is False
                and type(source.get('expires_at')) in (int, float)
                and clock() < source['expires_at'])

    def _apply_operating(self, db, ws, resource_id, actor, source):
        """Pure signed local qualification lookup; never call an approval adapter."""
        value = self._operating(db, ws, resource_id)
        if (value is None or self.operating_qualifier is None or value['enabled'] is not True
                or value['qualifier_generation'] != self._qualifier_generation
                or value['expires'] <= clock() or not self._external_qualified(source)):
            return source
        marker = 'operating:'+ws+':'+str(resource_id)+':'+str(value['revision'])
        if db.execute('SELECT 1 FROM reliability_restore_blocks WHERE authority_id=?', (marker,)).fetchone():
            return source
        authority = self._authority(db, ws, value['binding']['authority']['owner_id'])
        if (value['binding']['authority'] != authority
                or value['binding']['source_hash'] != digest(source)
                or value['binding']['source_revision'] != source['source_revision']):
            return source
        result = source | {'environment': 'operating', 'source_environment': 'approved_external',
            'qualified_operating_evidence': True, 'expires_at': min(source['expires_at'], value['expires']),
            'operating_qualification_revision': value['revision']}
        result['source_revision'] = digest([source['source_revision'], self.sign(value)])
        return result

    def operating_status(self, ws, resource_id, actor):
        self._rid(resource_id)
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            value = self._operating(db, ws, resource_id)
            source = self.current_projection_in_transaction(db, ws, resource_id, actor)
            return {'configured': self.operating_qualifier is not None, 'notice': OPERATING_NOTICE,
                'resource_id': resource_id, 'revision': value['revision'] if value else 0,
                'qualified_operating_evidence': source['qualified_operating_evidence'],
                'expires': source['expires_at'] if source['qualified_operating_evidence'] else None,
                'provider_calls': 0, 'public_activation': False}

    def qualify_operating(self, ws, body, actor):
        exact(body, ('resource_id', 'revision', 'authorized', 'notice'))
        self._authorized(body, OPERATING_NOTICE); self._rid(body['resource_id']); _int(body['revision'], 0, 2**31-1)
        adapter, generation = self.operating_qualifier, self._qualifier_generation
        if adapter is None:
            raise WorkspaceDenied()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            source = self._base_projection(db, ws, body['resource_id'], actor)
            prior = self._operating(db, ws, body['resource_id'])
            if (body['revision'] != (prior['revision'] if prior else 0)
                    or not self._external_qualified(source)):
                raise WorkspaceConflict()
            if not prior and db.execute('SELECT COUNT(*) FROM reliability_operating_qualifications WHERE workspace_id=?', (ws,)).fetchone()[0] >= MAX_OBJECTS:
                raise WorkspaceConflict()
            binding = {'workspace_id': ws, 'resource_id': body['resource_id'],
                'purpose': 'operating-read-routing', 'source_environment': 'approved_external',
                'source_hash': digest(source), 'source_revision': source['source_revision'],
                'authority': self._authority(db, ws, actor.user_id), 'expires': source['expires_at']}
        if self.store._db.in_transaction:
            raise WorkspaceConflict()
        try:
            approval = adapter(deepcopy(binding))
        except Exception:
            raise WorkspaceConflict() from None
        if type(approval) is not OperatingEvidenceApproval:
            raise WorkspaceDenied()
        _digest(approval.binding_hash); _digest(approval.qualification_hash); _digest(approval.approval_hash)
        _number(approval.expires, clock()+0.001, min(binding['expires'], clock()+3600))
        if approval.binding_hash != digest(binding):
            raise WorkspaceDenied()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            current = self._base_projection(db, ws, body['resource_id'], actor)
            prior = self._operating(db, ws, body['resource_id'])
            if (adapter is not self.operating_qualifier or generation != self._qualifier_generation
                    or body['revision'] != (prior['revision'] if prior else 0)
                    or digest(current) != binding['source_hash']
                    or binding['authority'] != self._authority(db, ws, actor.user_id)
                    or approval.expires <= clock()):
                raise WorkspaceConflict()
            value = {'workspace_id': ws, 'resource_id': body['resource_id'], 'revision': body['revision']+1,
                'binding': binding, 'approval': asdict(approval), 'qualifier_generation': generation,
                'created': clock(), 'expires': approval.expires, 'enabled': True}
            db.execute('''INSERT INTO reliability_operating_qualifications VALUES(?,?,?,?,?)
                ON CONFLICT(workspace_id,resource_id) DO UPDATE SET revision=excluded.revision,
                payload=excluded.payload,signature=excluded.signature''',
                (ws, body['resource_id'], value['revision'], _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'reliability.operating.qualify', str(body['resource_id']), value['revision'])
        return self.operating_status(ws, body['resource_id'], actor)

    def withdraw_operating(self, ws, body, actor):
        exact(body, ('resource_id', 'revision', 'authorized', 'notice'))
        self._authorized(body, OPERATING_NOTICE); self._rid(body['resource_id']); _int(body['revision'], 1, 2**31-1)
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            value = self._operating(db, ws, body['resource_id'])
            if value is None or value['revision'] != body['revision']:
                raise WorkspaceConflict()
            value.update(enabled=False, revision=value['revision']+1)
            db.execute('UPDATE reliability_operating_qualifications SET revision=?,payload=?,signature=? WHERE workspace_id=? AND resource_id=?',
                (value['revision'], _canonical(value), self.sign(value), ws, body['resource_id']))
            self.access._audit(db, actor, ws, 'reliability.operating.withdraw', str(body['resource_id']), value['revision'])
        return self.operating_status(ws, body['resource_id'], actor)

    @staticmethod
    def _projection(report):
        groups = report.pop('groups'); qualified = [g for g in groups if g['minimum_sample_met'] and g['quality_status'] == 'assessed'
            and g['source_fidelity'] == 'verified' and g['quality_outcomes']['failed'] == 0
            and g['outcomes']['unknown'] == 0 and g['outcomes']['failed'] == 0]
        # A single declared contract remains exact; heterogeneous cohorts are
        # never silently combined into a quality assertion.
        group = qualified[0] if len(qualified) == 1 else None
        return report | {'contract_id': group['contract_id'] if group else None,
            'contract_revision': group['contract_revision'] if group else None, 'contract_hash': group['contract_hash'] if group else None,
            'quality_status': 'assessed' if group else 'unassessed', 'source_fidelity': 'verified' if group else 'unassessable',
            'independent_qualified': bool(group), 'latest_observed_at': group['latest_observed_at'] if group else None,
            'expires_at': group['expires'] if group else None, 'revoked': not bool(group),
            'logical_samples': group['logical_samples'] if group else 0, 'outcomes': group['outcomes'] if group else {'succeeded': 0, 'failed': 0, 'unknown': 0},
            'latency_ms': group['latency_ms'] if group else None,
            'environment': group['environment'] if group else None, 'qualified_operating_evidence': False}
