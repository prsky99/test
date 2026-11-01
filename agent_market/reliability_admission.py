"""Explicit single-call pilot using existing private tickets and execution journal."""
import hashlib
import hmac
import json
import secrets

from .capability_contracts import validate
from .reliability_evaluation import bounded_int, finite, revision_authority
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash, _identity, _rows, _safe_text, _tree
from .workspace_execution import NOTICE as RUN_NOTICE, LIMITS as RUN_LIMITS, OutputContractRejected

PROFILE = 'workspace-single-admission-v1'
NOTICE = 'workspace-one-provider-no-replacement-v1'
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS reliability_admission_policies(workspace_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_admissions(id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,logical_key TEXT NOT NULL UNIQUE,snapshot_id TEXT UNIQUE,ticket_id TEXT UNIQUE,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_admission_restore_blocks(authority_id TEXT PRIMARY KEY)''',
)


def protected_admission(access, db, ws, draft_id, snapshot_id):
    """Verify the bounded registry before deciding that a snapshot is unprotected."""
    if db is not access.store._db or not db.in_transaction:
        raise WorkspaceConflict()
    from .private_artifact_keys import ArtifactSigner
    key = hmac.new(access.key, PROFILE.encode('ascii'), hashlib.sha256).digest()
    signer = ArtifactSigner(key, PROFILE)
    rows = _rows(db, 'SELECT * FROM reliability_admissions WHERE workspace_id=? ORDER BY id LIMIT 101', (ws,))
    if len(rows) > 100:
        raise WorkspaceConflict()
    matches = []
    for row in rows:
        try:
            value = json.loads(row['payload']); _tree(value)
            if (type(value) is not dict or not signer.verify(value, row['signature'])
                    or any(value.get(key) != row[key] for key in ('id', 'workspace_id', 'logical_key', 'snapshot_id', 'ticket_id'))
                    or value['workspace_id'] != ws):
                raise WorkspaceConflict()
        except (ValueError, TypeError, KeyError):
            raise WorkspaceConflict() from None
        if value.get('snapshot_id') == snapshot_id or value.get('draft_id') == draft_id:
            matches.append(value)
    if len(matches) > 1:
        raise WorkspaceConflict()
    return matches[0] if matches else None


class SingleAdmission(SignedWorkspaceModule):
    def __init__(self, access, routing, execution, *, enabled=False, evidence_guard=None, environment='isolated'):
        if (routing.access is not access or execution.access is not access or type(enabled) is not bool
                or environment not in ('isolated', 'sandbox', 'operating')
                or evidence_guard is not None and not callable(evidence_guard)):
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.routing, self.execution, self.enabled = routing, execution, enabled
        self.evidence_guard, self.environment = evidence_guard, environment
        execution.purpose_guards = (*execution.purpose_guards, self.guard_ticket)
        execution.output_guards = (*execution.output_guards, self.validate_output)

    def _policy(self, db, ws):
        rows = _rows(db, 'SELECT * FROM reliability_admission_policies WHERE workspace_id=?', (ws,))
        if not rows:
            return None
        value = self.opened(rows[0])
        if value['workspace_id'] != ws or value['revision'] != rows[0]['revision']:
            raise WorkspaceConflict()
        return value

    def _blocked(self, db, authority):
        return bool(db.execute('SELECT 1 FROM reliability_admission_restore_blocks WHERE authority_id=?', (authority,)).fetchone())

    def _current(self, db, ws, actor):
        member, user = self.scope(ws, actor, write=True, owner=True)
        value = self._policy(db, ws)
        if (not self.enabled or not callable(self.evidence_guard) or not value or not value['enabled']
                or value['expires'] <= clock() or self._blocked(db, ws + ':' + str(value['revision']))
                or value['environment'] != self.environment
                or value['authority'] != revision_authority(member, user, actor)):
            raise WorkspaceDenied()
        shadow = self.routing._current(db, ws, actor, value['shadow_revision'])
        if shadow['policy_hash'] != value['shadow_hash'] or shadow['mode'] != 'decision_shadow':
            raise WorkspaceDenied()
        return value, shadow

    def configure(self, ws, body, actor):
        exact(body, ('revision', 'shadow_revision', 'enabled', 'percent', 'max_runs', 'expires', 'authorized', 'notice'))
        bounded_int(body['revision'], 0, 2**31 - 1); bounded_int(body['shadow_revision'], 1, 2**31 - 1)
        bounded_int(body['percent'], 1, 10); bounded_int(body['max_runs'], 1, 100)
        if (type(body['enabled']) is not bool or body['authorized'] is not True or body['notice'] != NOTICE
                or not finite(body['expires']) or not clock() < body['expires'] <= clock() + 86400):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            prior = self._policy(db, ws)
            if body['revision'] != (prior['revision'] if prior else 0):
                raise WorkspaceConflict()
            shadow = self.routing._current(db, ws, actor, body['shadow_revision'])
            if shadow['mode'] != 'decision_shadow' or body['expires'] > shadow['expires']:
                raise WorkspaceConflict()
            value = {key: body[key] for key in ('enabled', 'percent', 'max_runs', 'expires', 'shadow_revision')}
            value.update(workspace_id=ws, revision=body['revision']+1, admitted=0,
                         shadow_hash=shadow['policy_hash'], authority=revision_authority(member, user, actor),
                         created=clock(), environment=self.environment)
            db.execute('''INSERT INTO reliability_admission_policies VALUES(?,?,?,?) ON CONFLICT(workspace_id)
                DO UPDATE SET revision=excluded.revision,payload=excluded.payload,signature=excluded.signature''',
                (ws, value['revision'], _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'admission.configure', ws, value['revision'])
            return self._policy_dto(value)

    @staticmethod
    def _policy_dto(value):
        return {key: value[key] for key in ('revision', 'shadow_revision', 'enabled', 'percent', 'max_runs', 'admitted', 'expires', 'environment')}

    def _admission(self, db, ws, identity):
        _identity(identity, 'rad')
        rows = _rows(db, 'SELECT * FROM reliability_admissions WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        if any(value.get(key) != rows[0][key] for key in ('id', 'workspace_id', 'logical_key', 'snapshot_id', 'ticket_id')):
            raise WorkspaceConflict()
        return value

    def _put(self, db, value):
        db.execute('UPDATE reliability_admissions SET snapshot_id=?,ticket_id=?,payload=?,signature=? WHERE id=? AND workspace_id=?',
                   (value.get('snapshot_id'), value.get('ticket_id'), _canonical(value), self.sign(value), value['id'], value['workspace_id']))

    def _project(self, db, value):
        if value.get('ticket_id'):
            ticket, _ = self.execution._ticket(db, value['ticket_id'], value['workspace_id'], value['draft_id'], value['snapshot_id'])
            if ticket['run_id']:
                _, retained_ticket, _, payload = self.execution._load_run(db, ticket['run_id'], value['workspace_id'], value['draft_id'], value['snapshot_id'], decrypt_output=False)
                run = self.execution._dto(payload, retained_ticket, output=False)
                value = value | {'state': run['status'], 'run_id': run['id']}
        return self._dto(value)

    @staticmethod
    def _dto(value):
        return {key: value.get(key) for key in ('id', 'state', 'resource_id', 'created', 'expires', 'draft_id', 'snapshot_id', 'run_id', 'error_code')} | {
            'business_call_limit': 1, 'replacement_limit': 0, 'automatic_replay': False,
            'requires_run_confirmation': value['state'] == 'prepared', 'actual_operating_acceptance': False}

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, user):
            member, _ = self.scope(ws, actor)
            policy = self._policy(db, ws)
            rows = _rows(db, 'SELECT id FROM reliability_admissions WHERE workspace_id=? ORDER BY id DESC LIMIT 101', (ws,))
            if len(rows) > 100:
                raise WorkspaceConflict()
            return {'profile': PROFILE, 'notice': NOTICE, 'configured': self.enabled,
                    'policy': self._policy_dto(policy) if policy else None,
                    'can_write': member['member_role'] == 'owner' and user['role'] != 'operator',
                    'admissions': [self._project(db, self._admission(db, ws, row['id'])) for row in rows],
                    'business_call_limit': 1, 'replacement_limit': 0, 'public_activation': False,
                    'promotion': 'explicit_pilot_only', 'probe_uses_separate_approved_evaluation': True}

    def review(self, ws, identity, actor):
        """Reopen the original prepared ticket without creating execution authority."""
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor, write=True, owner=True)
            value = self._admission(db, ws, identity)
            if value['state'] != 'prepared' or not value.get('ticket_id'):
                raise WorkspaceConflict()
            ticket, claims = self.execution._ticket(db, value['ticket_id'], ws, value['draft_id'], value['snapshot_id'])
            if (ticket['run_id'] is not None or ticket['revoked'] is not None
                    or ticket['expires'] <= clock()):
                raise WorkspaceConflict()
            self.guard_ticket(db, ticket, claims)
            current, node, _ = self.execution._binding(db, ws, value['draft_id'], value['snapshot_id'], actor)
            if any(claims.get(key) != item for key, item in current.items()):
                raise WorkspaceDenied()
            preview = {key: current[key] for key in ('workspace_id', 'draft_id', 'snapshot_id', 'snapshot_revision', 'resource_id')}
            preview.update(tool=node['data']['tool'], input=node['data']['input'], seconds=RUN_LIMITS['seconds'], max_calls=1)
            return {'admission': self._dto(value), 'preview': preview, 'notice': NOTICE,
                    'current': True, 'requires_run_confirmation': True,
                    'provider_calls': 0, 'tickets_created': 0}

    def prepare(self, ws, body, actor):
        exact(body, ('revision', 'logical_id', 'input', 'name', 'authorized', 'notice'))
        bounded_int(body['revision'], 1, 2**31 - 1); _identity(body['logical_id'], 'rld'); _safe_text(body['name'], 120)
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.store._lock:
            with self.access._tx(actor, write=True) as (db, _):
                policy, shadow = self._current(db, ws, actor)
                if policy['revision'] != body['revision']:
                    raise WorkspaceConflict()
                try:
                    validate(shadow['contract_id'], body['input'])
                except (ValueError, TypeError, KeyError):
                    raise WorkspaceInvalid() from None
                logical = _hash([ws, body['logical_id']]); request_hash = _hash(body)
                if self._blocked(db, 'logical:'+ws+':'+logical):
                    raise WorkspaceConflict()
                old = _rows(db, 'SELECT id FROM reliability_admissions WHERE logical_key=?', (logical,))
                if old:
                    value = self._admission(db, ws, old[0]['id'])
                    if value['request_hash'] != request_hash:
                        raise WorkspaceConflict()
                    return self._dto(value) | {'replayed': True}
            decision = self.routing.decide(ws, {'revision': policy['shadow_revision'], 'logical_id': body['logical_id'],
                'authorized': True, 'notice': 'offline-decision-shadow-only-v1'}, actor)
            with self.access._tx(actor, write=True) as (db, _):
                current, shadow = self._current(db, ws, actor)
                if current != policy or decision['selected_resource_id'] is None:
                    raise WorkspaceConflict()
                rid = decision['selected_resource_id']
                source = self.evidence_guard(db, ws, rid, actor)
                if _hash(source) != self.routing._decision_source_hash(db, ws, decision['id'], rid):
                    raise WorkspaceConflict()
                if self.environment == 'operating' and (source.get('qualified_operating_evidence') is not True or source.get('environment') != 'operating'):
                    raise WorkspaceDenied()
                sample = int(hmac.new(self.key, _canonical([ws, logical, policy['revision']]).encode('ascii'), hashlib.sha256).hexdigest()[:8], 16) % 100
                selected = sample < policy['percent']
                if selected and (policy['admitted'] >= policy['max_runs']):
                    raise WorkspaceConflict()
                if db.execute('SELECT COUNT(*) FROM reliability_admissions WHERE workspace_id=?', (ws,)).fetchone()[0] >= 100:
                    raise WorkspaceConflict()
                value = {'id': 'rad_' + secrets.token_hex(16), 'workspace_id': ws, 'logical_key': logical,
                         'request_hash': request_hash, 'policy_revision': policy['revision'], 'decision_id': decision['id'],
                         'resource_id': rid, 'source_hash': _hash(source), 'source_expires': source['expires_at'],
                         'created': clock(), 'expires': min(policy['expires'], source['expires_at'], clock()+300),
                         'state': 'reserved' if selected else 'not_selected', 'snapshot_id': None, 'ticket_id': None,
                         'authority': policy['authority'], 'contract_id': shadow['contract_id']}
                db.execute('INSERT INTO reliability_admissions VALUES(?,?,?,NULL,NULL,?,?)',
                           (value['id'], ws, logical, _canonical(value), self.sign(value)))
                if selected:
                    policy['admitted'] += 1
                    db.execute('UPDATE reliability_admission_policies SET payload=?,signature=? WHERE workspace_id=? AND revision=?',
                               (_canonical(policy), self.sign(policy), ws, policy['revision']))
                self.access._audit(db, actor, ws, 'admission.reserve', value['id'], policy['revision'])
            if not selected:
                return self._dto(value) | {'replayed': False}
            try:
                pin = shadow['pins'][str(rid)]['pin']
                definition = {'nodes': [{'id': 'start', 'name': 'Explicit pilot', 'type': 'trigger', 'kind': 'trigger', 'data': {}},
                    {'id': 'chosen', 'name': 'Reviewed single provider', 'type': 'agent', 'kind': 'mcp', 'resource_id': rid,
                     'data': {'tool': pin['approval']['tool'], 'input': body['input']}}], 'edges': [{'source': 'start', 'target': 'chosen'}]}
                with self.access._tx(actor, write=True) as (db, _):
                    value = self._admission(db, ws, value['id']); self._current(db, ws, actor)
                    draft = self.access._save_draft_in_transaction(db, ws, {'name': body['name'], 'description': '', 'definition': definition}, actor)
                    snapshot = self.access._create_snapshot_in_transaction(db, ws, draft['id'], {'draft_revision': draft['revision']}, actor)
                    # Snapshot and protection become visible in the same commit.
                    value.update(draft_id=draft['id'], snapshot_id=snapshot['id']); self._put(db, value)
                ticket = self.execution.prepare(ws, draft['id'], snapshot['id'], {'snapshot_revision': snapshot['revision']}, actor)
                with self.access._tx(actor, write=True) as (db, _):
                    value = self._admission(db, ws, value['id']); self._current(db, ws, actor)
                    value.update(ticket_id=ticket['ticket_id'], state='prepared'); self._put(db, value)
                return self._dto(value) | {'replayed': False, 'preview': ticket['preview'], 'notice': NOTICE}
            except Exception:
                with self.access._tx(actor, write=True) as (db, _):
                    value = self._admission(db, ws, value['id']); value.update(state='denied', error_code='PREPARATION_INTERRUPTED'); self._put(db, value)
                raise

    def guard_ticket(self, db, ticket, claims):
        value = protected_admission(self.access, db, claims['workspace_id'], claims['draft_id'], claims['snapshot_id'])
        if value is None:
            return True
        actor = self.execution._actor_from_claims(claims)
        policy, shadow = self._current(db, value['workspace_id'], actor)
        if (value['state'] not in ('prepared', 'executing', 'succeeded', 'failed', 'unknown', 'denied')
                or self._blocked(db, value['id']) or value['expires'] <= clock()
                or value['policy_revision'] != policy['revision'] or value['ticket_id'] != ticket['id']
                or claims['snapshot_id'] != value['snapshot_id'] or claims['draft_id'] != value['draft_id']
                or value['authority'] != policy['authority'] or claims['resource_id'] != value['resource_id']):
            raise WorkspaceDenied()
        expected = shadow['pins'][str(value['resource_id'])]
        if self.routing._pin(value['resource_id'], shadow['contract_id']) != expected:
            raise WorkspaceDenied()
        if _hash(self.evidence_guard(db, value['workspace_id'], value['resource_id'], actor)) != value['source_hash']:
            raise WorkspaceDenied()
        return True

    def validate_output(self, db, ticket, claims, output):
        """Commit contract failure in the existing run and meter, not just a DTO."""
        value = protected_admission(self.access, db, claims['workspace_id'], claims['draft_id'], claims['snapshot_id'])
        if value is None:
            return True
        actor = self.execution._actor_from_claims(claims)
        _, _, _, snapshot = self.execution._scope(value['workspace_id'], value['draft_id'], value['snapshot_id'], actor)
        node = self.execution._node(snapshot)
        raw = output.get('structuredContent', output) if type(output) is dict else output
        try:
            validate(value['contract_id'], node['data']['input'], raw)
        except (ValueError, TypeError, KeyError):
            raise OutputContractRejected() from None
        return True

    def execute(self, ws, identity, body, actor):
        exact(body, ('authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True, owner=True); value = self._admission(db, ws, identity)
            if value['state'] not in ('prepared', 'executing', 'succeeded', 'failed', 'unknown', 'denied') or not value.get('ticket_id'):
                raise WorkspaceConflict()
            ticket, claims = self.execution._ticket(db, value['ticket_id'], ws, value['draft_id'], value['snapshot_id'])
            if ticket['run_id']:
                # Current members may inspect retained outcomes even when a
                # failed provider is no longer eligible for a new admission.
                _, retained_ticket, _, payload = self.execution._load_run(db, ticket['run_id'], ws, value['draft_id'], value['snapshot_id'])
                result = self.execution._dto(payload, retained_ticket)
                return {'admission': self._dto(value | {'state': result['status'], 'run_id': result['id']}),
                        'run': result, 'replacement_calls': 0, 'replayed': True}
            self._current(db, ws, actor)
            self.guard_ticket(db, ticket, claims)
            value['state'] = 'executing'; self._put(db, value)
        result = self.execution.execute(ws, value['draft_id'], value['snapshot_id'],
            {'ticket_id': value['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, actor)
        with self.access._tx(actor, write=True) as (db, _):
            value = self._admission(db, ws, identity)
            _, ticket, _, payload = self.execution._load_run(db, result['id'], ws, value['draft_id'], value['snapshot_id'])
            result = self.execution._dto(payload, ticket) | {'replayed': result.get('replayed', False)}
            value.update(state=result['status'], run_id=result['id']); self._put(db, value)
        return {'admission': self._dto(value), 'run': result, 'replacement_calls': 0, 'replayed': result.get('replayed', False)}
