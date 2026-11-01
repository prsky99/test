"""Read-computed, scoped history from retained evidence; never quality certification."""
import json
import math
import re

from .capability_registry import PROFILES, digest, version_parts
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _hash, _rows

PROFILE = 'bounded-evidence-rollup-v1'
NOTICE = 'evidence-withdrawal-v1'
POLICY = {'id': 'retained-metadata-v1', 'window_seconds': 86400, 'max_sources': 200,
          'minimum_logical_samples': 20, 'latency_scope': 'gateway_observation_interval'}
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS evidence_rollup_withdrawals (
       workspace_id TEXT NOT NULL,scope TEXT NOT NULL,source_ref TEXT NOT NULL,revision INTEGER NOT NULL,
       payload TEXT NOT NULL,signature TEXT NOT NULL,PRIMARY KEY(workspace_id,scope,source_ref))''',
    '''CREATE TABLE IF NOT EXISTS evidence_rollup_audit (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
)
PUBLIC_SOURCES = ('managed', 'testbench', 'workflow_public', 'workflow_verification')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class EvidenceRollups(SignedWorkspaceModule):
    def __init__(self, access, execution):
        if execution.access is not access: raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.execution = execution

    def _scope(self, ws, actor, scope, *, owner=False):
        if scope not in ('workspace', 'catalog'): raise WorkspaceInvalid()
        member, user = self.scope(ws, actor, write=owner, owner=owner)
        if scope == 'catalog' and user['role'] != 'superadmin': raise WorkspaceDenied()
        return member, user

    @staticmethod
    def _rid(resource_id):
        if type(resource_id) is not int or not 0 < resource_id < 2**31: raise WorkspaceInvalid()

    def _resource(self, db, rid):
        self._rid(rid)
        rows = _rows(db, 'SELECT * FROM resources WHERE id=?', (rid,))
        if len(rows) != 1 or rows[0].get('kind') not in PROFILES: raise WorkspaceDenied()
        resource = rows[0]
        binding, schema, profile, complete = version_parts(resource)
        version = 'cv_' + digest([rid, binding, schema, profile])[:32]
        generation = _rows(db, 'SELECT generation FROM resource_observation_generations WHERE resource_id=?', (rid,))
        controls = _rows(db, 'SELECT invoke_enabled,workflow_enabled,revision FROM execution_controls WHERE id=1')
        return resource, {'resource_id': rid, 'version_id': version, 'protocol': resource['kind'],
                          'profile_version': profile, 'schema_complete': bool(complete),
                          'generation': generation[0]['generation'] if len(generation) == 1 else None,
                          'execution_controls_enabled': bool(len(controls) == 1 and controls[0]['invoke_enabled'] == 1
                                                             and controls[0]['workflow_enabled'] == 1)}, controls

    def _withdrawals(self, db, ws, scope):
        rows = _rows(db, 'SELECT * FROM evidence_rollup_withdrawals WHERE workspace_id=? AND scope=? LIMIT 501', (ws, scope))
        if len(rows) > 500: raise WorkspaceConflict()
        result = {}
        for row in rows:
            value = self.opened(row)
            if (value['workspace_id'] != ws or value['scope'] != scope or value['source_ref'] != row['source_ref']
                    or value['revision'] != row['revision'] or value['revision'] != 1): raise WorkspaceConflict()
            result[row['source_ref']] = value
        return result

    def _catalog(self, db, current):
        rows = _rows(db, '''SELECT e.*,v.resource_id FROM capability_evidence e JOIN connection_versions v ON v.id=e.version_id
            WHERE v.resource_id=? ORDER BY e.finished DESC,e.id DESC LIMIT 201''', (current['resource_id'],))
        sources = []
        for row in rows[:200]:
            from .capability_contracts import CONTRACTS
            if (type(row['id']) is not str or not re.fullmatch(r'ev_[0-9a-f]{32}', row['id']) or row['scope'] not in ('transport', 'execution', 'contract')
                    or row['outcome'] not in ('succeeded', 'failed', 'unknown')
                    or any(type(row[key]) is not str or not re.fullmatch(r'[a-z0-9.-]{1,80}', row[key])
                           for key in ('dataset_version', 'validator_version'))
                    or type(row['cases']) is not int or not 1 <= row['cases'] <= 10000
                    or type(row['successes']) is not int or not 0 <= row['successes'] <= row['cases']
                    or row['outcome'] == 'succeeded' and row['successes'] != row['cases']
                    or row['scope'] == 'contract' and row['contract_id'] not in CONTRACTS
                    or row['scope'] != 'contract' and row['contract_id'] != ''):
                raise WorkspaceConflict()
            reference = row['operation_ref']; operation = None
            if reference:
                if re.fullmatch(r'ex_[0-9a-f]{24}', reference):
                    operations = _rows(db, 'SELECT * FROM platform_operations WHERE id=?', (reference,))
                else:
                    operations = _rows(db, '''SELECT o.* FROM platform_attempts a JOIN platform_operations o ON o.id=a.operation_id
                        WHERE a.id=?''', (reference,))
                if len(operations) == 1 and operations[0]['resource_id'] == current['resource_id']:
                    operation = operations[0]
            shared_contract = row['scope'] == 'contract' and row['dataset_version'] == 'explicit-contract-test-v1'
            approvals = _rows(db, 'SELECT created FROM capability_approvals WHERE version_id=? AND contract_id=?',
                              (row['version_id'], row['contract_id'])) if row['scope'] == 'contract' else []
            contract_current = bool(row['scope'] != 'contract' or len(approvals) == 1 and row['started'] >= approvals[0]['created'])
            attributed = bool(shared_contract or operation and operation['source'] in PUBLIC_SOURCES)
            logical = operation['id'] if operation else 'report:' + digest([row['artifact_hash'], row['started'], row['finished']])
            expiry = min(row['expires'], row['finished'] + POLICY['window_seconds']) if finite(row['expires']) and finite(row['finished']) else None
            sources.append({'ref': row['id'], 'version': row['version_id'], 'evidence_scope': row['scope'],
                            'outcome': row['outcome'], 'started': row['started'], 'finished': row['finished'],
                            'expires': expiry, 'logical': logical, 'contract': row['contract_id'],
                            'dataset': row['dataset_version'], 'validator': row['validator_version'],
                            'attributed': attributed, 'current': contract_current,
                            'integrity': digest(dict(row)), 'retained': True})
        return sources, len(rows) > 200

    def _private(self, db, ws, resource, current):
        rows = _rows(db, '''SELECT * FROM workspace_private_runs WHERE workspace_id=?
            ORDER BY created DESC,id DESC LIMIT 201''', (ws,))
        sources = []
        for row in rows[:200]:
            ticket, claims = self.execution._ticket(db, row['ticket_id'], ws, row['draft_id'], row['snapshot_id'])
            if claims['resource_id'] != current['resource_id']: continue
            if type(row['payload']) is not str or len(row['payload'].encode()) > 164000: raise WorkspaceConflict()
            try: value = json.loads(row['payload'])
            except (ValueError, TypeError): raise WorkspaceConflict() from None
            if (type(value) is not dict or not self.execution._artifact_signer.verify(value, row['signature'])
                    or value.get('ticket_hash') != _hash(claims) or ticket['run_id'] != row['id']
                    or any(value.get(key) != row[key] for key in ('id', 'ticket_id', 'workspace_id', 'draft_id',
                           'snapshot_id', 'status', 'created', 'finished', 'dispatched', 'deadline', 'actor_user_id'))):
                raise WorkspaceConflict()
            current_binding = False
            try:
                draft = self.access._draft_row(ws, row['draft_id']); self.access._open_draft(draft)
                snapshot_row = self.access._version_row(ws, row['draft_id'], row['snapshot_id'])
                snapshot = self.access._open_version(snapshot_row)
                node = self.execution._node(snapshot)
                _, pin = self.execution._resource(db, node)
                current_binding = bool(draft['active'] and snapshot_row['active'] and pin == claims['binding_hash']
                                       and snapshot_row['payload_hash'] == claims['snapshot_hash'])
            except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid): pass
            finished = row['finished']
            outcome = row['status']
            if outcome in ('prepared', 'dispatched'):
                outcome = 'unknown' if row['deadline'] <= clock() else 'pending'
                finished = row['deadline'] if outcome == 'unknown' else None
            if outcome == 'denied': outcome = 'failed'
            sources.append({'ref': row['id'], 'version': current['version_id'], 'evidence_scope': 'execution',
                            'outcome': outcome, 'started': row['created'], 'finished': finished,
                            'expires': (finished + POLICY['window_seconds']) if finite(finished) else row['deadline'],
                            'logical': row['id'], 'contract': '', 'dataset': 'private-execution-history-v1',
                            'validator': value.get('profile'), 'attributed': True,
                            'current': current_binding and ticket['revoked'] is None,
                            'not_dispatched': row['dispatched'] is None,
                            'integrity': digest([row['signature'], ticket['signature'], ticket['revoked'], current_binding]),
                            'retained': True})
        return sources, len(rows) > 200

    def options(self, ws, actor):
        with self.access._tx(actor) as (db, user):
            member, _ = self._scope(ws, actor, 'workspace')
            rows = _rows(db, "SELECT id,kind FROM resources WHERE kind IN ('a2a','mcp','x402') ORDER BY id DESC LIMIT 100") if user['role'] == 'superadmin' else []
            return {'profile': PROFILE, 'policy': POLICY, 'scopes': ['workspace', 'catalog'] if user['role'] == 'superadmin' else ['workspace'],
                    'resources': [{'resource_id': row['id'], 'protocol': row['kind']} for row in rows],
                    'can_withdraw': member['member_role'] == 'owner' and user['role'] != 'operator',
                    'withdrawal_notice': NOTICE, 'public_activation': False, 'provider_calls': 0}

    def rollup(self, ws, resource_id, scope, actor):
        with self.access._tx(actor) as (db, _):
            member, user = self._scope(ws, actor, scope)
            resource, current, controls = self._resource(db, resource_id)
            withdrawals = self._withdrawals(db, ws, scope)
            sources, truncated = self._catalog(db, current) if scope == 'catalog' else self._private(db, ws, resource, current)
            now = clock(); excluded = {key: 0 for key in ('withdrawn', 'version_changed', 'not_current', 'unattributed', 'expired', 'clock_skew', 'pending', 'not_dispatched')}
            groups = {}; displayed = []; boundaries = []
            for source in sources:
                reason = ('withdrawn' if source['ref'] in withdrawals else 'version_changed' if source['version'] != current['version_id']
                          else 'not_current' if not source['current'] else 'unattributed' if not source['attributed']
                          else 'not_dispatched' if source.get('not_dispatched') else
                          'pending' if source['outcome'] == 'pending' else 'clock_skew'
                          if not all(finite(source[k]) for k in ('started', 'finished', 'expires'))
                          or not 0 < source['started'] <= source['finished'] <= now or source['expires'] < source['finished']
                          else 'expired' if source['expires'] <= now else None)
                if reason:
                    excluded[reason] += 1
                    if finite(source['finished']) and source['finished'] > now: boundaries.append(source['finished'])
                else:
                    if source['outcome'] not in ('succeeded', 'failed', 'unknown'): raise WorkspaceConflict()
                    boundaries.append(source['expires'])
                    key = (source['evidence_scope'], source['contract'], source['dataset'], source['validator'])
                    bucket = groups.setdefault(key, {})
                    bucket.setdefault(source['logical'], []).append(source)
                if len(displayed) < 50:
                    displayed.append({'source_ref': source['ref'], 'state': reason or source['outcome'],
                                      'observed_at': source['finished'] if finite(source['finished']) else None,
                                      'expires': source['expires'] if finite(source['expires']) else None,
                                      'withdrawal_revision': 1 if source['ref'] in withdrawals else 0})
            result_groups = []
            for key, logical in sorted(groups.items()):
                counts = dict.fromkeys(('succeeded', 'failed', 'unknown'), 0); latencies = []; duplicates = 0
                for candidates in logical.values():
                    duplicates += len(candidates) - 1
                    outcome = max((s['outcome'] for s in candidates), key=lambda s: {'succeeded': 0, 'failed': 1, 'unknown': 2}[s])
                    counts[outcome] += 1
                    chosen = max(candidates, key=lambda s: (s['finished'], s['ref']))
                    duration = (chosen['finished'] - chosen['started']) * 1000
                    if 0 <= duration <= 86400000: latencies.append(duration)
                latencies.sort(); n = len(logical)
                result_groups.append({'evidence_scope': key[0], 'contract_id': key[1], 'dataset_version': key[2],
                                      'validator_version': key[3], 'logical_samples': n, 'outcomes': counts,
                                      'duplicates_removed': duplicates, 'minimum_sample_met': n >= POLICY['minimum_logical_samples'],
                                      'latency_ms': {'p50': round(latencies[max(0, math.ceil(len(latencies) * .5) - 1)], 2) if latencies else None,
                                                     'p95': round(latencies[max(0, math.ceil(len(latencies) * .95) - 1)], 2) if latencies else None}})
            result = {'profile': PROFILE, 'scope': scope, 'current': current, 'policy': POLICY,
                      'groups': result_groups, 'excluded_sources': excluded, 'sources': displayed, 'truncated': truncated,
                      'state': 'insufficient_evidence' if not result_groups or any(not g['minimum_sample_met'] for g in result_groups) else 'retained_history_only',
                      'quality_status': 'unassessed', 'source_fidelity': 'unassessable_from_metadata',
                      'qualified_operating_evidence': False, 'public_activation': False, 'provider_calls': 0,
                      'valid_until': min(boundaries) if boundaries else None}
            # Every conditional read recomputes current authority, original source
            # retention, expiry and withdrawals before comparing this digest.
            fingerprint = {'result': result, 'workspace': ws, 'member': member, 'role': user['role'],
                           'session': actor.session_ref, 'controls': controls,
                           'sources': [(s['ref'], s['integrity']) for s in sources], 'withdrawals': withdrawals}
            return result, '"' + self.sign(fingerprint).replace(':', '_') + '"'

    def withdraw(self, ws, body, actor):
        exact(body, ('scope', 'resource_id', 'source_ref', 'revision', 'reason', 'authorized', 'notice'))
        self._rid(body['resource_id']); scope, ref = body['scope'], body['source_ref']
        if (body['authorized'] is not True or body['notice'] != NOTICE or body['revision'] != 0
                or type(body['revision']) is not int or body['reason'] not in ('source_withdrawn', 'retention_review', 'invalid_source')
                or type(ref) is not str or not re.fullmatch(r'(?:ev|wpr)_[0-9a-f]{32}', ref)):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self._scope(ws, actor, scope, owner=True)
            self._resource(db, body['resource_id'])
            if scope == 'catalog':
                source = _rows(db, '''SELECT e.id FROM capability_evidence e JOIN connection_versions v ON v.id=e.version_id
                    WHERE e.id=? AND v.resource_id=?''', (ref, body['resource_id']))
            else:
                source = _rows(db, 'SELECT * FROM workspace_private_runs WHERE id=? AND workspace_id=?', (ref, ws))
                if source:
                    _, claims = self.execution._ticket(db, source[0]['ticket_id'], ws, source[0]['draft_id'], source[0]['snapshot_id'])
                    if claims['resource_id'] != body['resource_id']: raise WorkspaceDenied()
            if len(source) != 1: raise WorkspaceDenied()
            existing = self._withdrawals(db, ws, scope)
            if ref in existing:
                if existing[ref]['reason'] != body['reason']: raise WorkspaceConflict()
                return {'source_ref': ref, 'revision': 1, 'withdrawn': True, 'replayed': True}
            if db.execute('SELECT COUNT(*) FROM evidence_rollup_audit WHERE workspace_id=?', (ws,)).fetchone()[0] >= 500:
                raise WorkspaceConflict()
            value = {'workspace_id': ws, 'scope': scope, 'source_ref': ref, 'revision': 1,
                     'reason': body['reason'], 'created': clock(), 'actor_user_id': actor.user_id}
            payload, signature = json.dumps(value, sort_keys=True), self.sign(value)
            db.execute('INSERT INTO evidence_rollup_withdrawals VALUES(?,?,?,?,?,?)', (ws, scope, ref, 1, payload, signature))
            db.execute('INSERT INTO evidence_rollup_audit VALUES(?,?,?,?)', ('era_' + digest(value)[:32], ws, payload, signature))
            return {'source_ref': ref, 'revision': 1, 'withdrawn': True, 'replayed': False}
