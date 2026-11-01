"""Rule-based offline and decision-shadow recommendations with zero dispatch."""
import math
import secrets
from urllib.parse import urlsplit

from .capability_contracts import CONTRACTS
from .capability_registry import digest
from .reliability_controls_restore import blocked
from .reliability_evaluation import bounded_int, finite, revision_authority
from .shadow_ledger import SignedWorkspaceModule, clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash, _identity, _rows
from .workflow_fallback import RoutingDenied, graph_fingerprint

PROFILE = 'zero-dispatch-safe-routing-v1'
NOTICE = 'offline-decision-shadow-only-v1'
RULE_VERSION = 'freshness-errors-correlation-v1'
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS reliability_controls_restore_blocks (
       authority_id TEXT PRIMARY KEY)''',
    '''CREATE TABLE IF NOT EXISTS reliability_route_policies (
       workspace_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reliability_route_decisions (
       id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,logical_key TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,signature TEXT NOT NULL)''',
)


class ReliabilityRouting(SignedWorkspaceModule):
    def __init__(self, access, runtime, *, evidence_source=None):
        if runtime.store is not access.store:
            raise WorkspaceInvalid()
        super().__init__(access, PROFILE, SCHEMA)
        self.runtime, self.evidence_source = runtime, evidence_source

    def _policy(self, db, ws):
        rows = _rows(db, 'SELECT * FROM reliability_route_policies WHERE workspace_id=?', (ws,))
        if not rows:
            return None
        value = self.opened(rows[0])
        if value['workspace_id'] != ws or value['revision'] != rows[0]['revision']:
            raise WorkspaceConflict()
        if blocked(db, 'routing_policy', ws, value['revision']):
            return value | {'enabled': False, 'restore_quarantined': True}
        return value

    def _pin(self, rid, contract):
        try:
            pin = self.runtime.fallback.pin(rid, contract)
        except (RoutingDenied, ValueError, KeyError):
            raise WorkspaceConflict() from None
        resource = self.store.resource(rid)
        return {'pin': pin, 'host_key': _hash(['routing-host-v1', urlsplit(resource['url']).hostname])}

    def _fallback_absent(self, workflow_id):
        try:
            policy, _ = self.runtime.fallback.policy(workflow_id)
        except (RoutingDenied, ValueError, KeyError):
            raise WorkspaceConflict() from None
        if policy and policy['mode'] != 'disabled':
            raise WorkspaceConflict()

    def configure(self, ws, body, actor):
        exact(body, ('revision', 'mode', 'workflow_id', 'contract_id', 'resource_ids', 'share_resource_ids',
                     'expires', 'enabled', 'authorized', 'notice'))
        bounded_int(body['revision'], 0, 2**31-1); bounded_int(body['workflow_id'], 1, 2**31-1)
        if (body['mode'] not in ('offline', 'decision_shadow') or type(body['enabled']) is not bool
                or body['authorized'] is not True or body['notice'] != NOTICE or body['contract_id'] not in ('news.search.v1', 'docs.search.v1')
                or not finite(body['expires']) or not clock() < body['expires'] <= clock()+86400
                or type(body['resource_ids']) is not list or not 1 <= len(body['resource_ids']) <= 6
                or any(type(rid) is not int or not 0 < rid < 2**31 for rid in body['resource_ids'])
                or len(set(body['resource_ids'])) != len(body['resource_ids'])
                or type(body['share_resource_ids']) is not list or body['share_resource_ids'] != body['resource_ids']):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, user):
            member, _ = self.scope(ws, actor, write=True, owner=True)
            old = self._policy(db, ws)
            if body['revision'] != (old['revision'] if old else 0):
                raise WorkspaceConflict()
            if not body['enabled']:
                if not old:
                    raise WorkspaceConflict()
                value = old | {'enabled': False, 'revision': old['revision']+1,
                               **revision_authority(member, user, actor)}
                value['policy_hash'] = _hash({key: val for key, val in value.items() if key != 'policy_hash'})
                db.execute('''UPDATE reliability_route_policies SET revision=?,payload=?,signature=? WHERE workspace_id=?''',
                           (value['revision'], _canonical(value), self.sign(value), ws))
                self.access._audit(db, actor, ws, 'reliability.routing.pause', ws, value['revision'])
                return self._dto(value)
            workflow = self.store.get_workflow(body['workflow_id'])
            # The legacy workflow is a correlation reference, never an execution authorization.
            if not workflow:
                raise WorkspaceDenied()
            self._fallback_absent(body['workflow_id'])
            pins = {str(rid): self._pin(rid, body['contract_id']) for rid in body['resource_ids']}
            value = {key: body[key] for key in ('mode', 'workflow_id', 'contract_id', 'expires', 'enabled', 'share_resource_ids')}
            value.update(workspace_id=ws, revision=body['revision']+1, pins=pins, graph_hash=graph_fingerprint(workflow),
                         rule_version=RULE_VERSION, created=clock(), **revision_authority(member, user, actor))
            value['policy_hash'] = _hash(value)
            db.execute('''INSERT INTO reliability_route_policies VALUES(?,?,?,?) ON CONFLICT(workspace_id)
                DO UPDATE SET revision=excluded.revision,payload=excluded.payload,signature=excluded.signature''',
                (ws, value['revision'], _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'reliability.routing.configure', ws, value['revision'])
            return self._dto(value)

    @staticmethod
    def _dto(value):
        return {key: value[key] for key in ('revision', 'mode', 'workflow_id', 'contract_id', 'expires', 'enabled', 'rule_version', 'policy_hash')} | {
            'resource_ids': [int(rid) for rid in value['pins']], 'business_calls': 0, 'future_business_call_limit': 1,
            'future_replacements_limit': 0, 'online_learning': False, 'execution_authority': False,
            'restore_quarantined': bool(value.get('restore_quarantined'))}

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, user):
            member, _ = self.scope(ws, actor); value = self._policy(db, ws)
            rows = _rows(db, 'SELECT * FROM reliability_route_decisions WHERE workspace_id=? ORDER BY id DESC LIMIT 101', (ws,))
            if len(rows) > 100:
                raise WorkspaceConflict()
            decisions = []
            for row in rows:
                decision = self.opened(row)
                if decision['id'] != row['id'] or decision['workspace_id'] != ws or decision['logical_key'] != row['logical_key']:
                    raise WorkspaceConflict()
                decisions.append(self._decision_dto(decision))
            return {'profile': PROFILE, 'notice': NOTICE, 'policy': self._dto(value) if value else None,
                    'can_write': member['member_role'] == 'owner' and user['role'] != 'operator',
                    'decisions': decisions, 'business_calls': 0, 'public_activation': False}

    @staticmethod
    def _decision_dto(value):
        return {key: value[key] for key in ('id', 'mode', 'policy_revision', 'policy_hash', 'rule_version', 'selected_resource_id',
            'baseline_resource_id', 'eligible', 'excluded', 'reason', 'created', 'expires', 'selected_propensity', 'logical_samples')} | {
            'business_calls': 0, 'replacement_calls': 0, 'execution_authority': False,
            'future_business_call_limit': 1, 'future_replacements_limit': 0}

    def _current(self, db, ws, actor, revision):
        member, user = self.scope(ws, actor, write=True, owner=True)
        policy = self._policy(db, ws)
        if (not policy or policy['revision'] != revision or not policy['enabled'] or policy['expires'] <= clock()
                or policy.get('restore_quarantined')
                or any(policy.get(key) != val for key, val in revision_authority(member, user, actor).items())):
            raise WorkspaceConflict()
        workflow = self.store.get_workflow(policy['workflow_id'])
        if not workflow or graph_fingerprint(workflow) != policy['graph_hash']:
            raise WorkspaceConflict()
        self._fallback_absent(policy['workflow_id'])
        controls = _rows(db, 'SELECT invoke_enabled,workflow_enabled FROM execution_controls WHERE id=1')
        if len(controls) != 1 or not all(controls[0][key] == 1 for key in ('invoke_enabled', 'workflow_enabled')):
            raise WorkspaceConflict()
        return policy

    def decide(self, ws, body, actor):
        # Multiple read-only evidence sources and the decision share a writer fence.
        with self.store._lock:
            return self._decide(ws, body, actor)

    def _decision_source_hash(self, db, ws, identity, resource_id):
        """Internal read for the single-admission final current-evidence fence."""
        _identity(identity, 'rrd')
        rows = _rows(db, 'SELECT * FROM reliability_route_decisions WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        if (value['id'] != identity or value['workspace_id'] != ws or value['logical_key'] != rows[0]['logical_key']
                or value['expires'] <= clock() or value['selected_resource_id'] != resource_id):
            raise WorkspaceConflict()
        return value['source_revisions'].get(str(resource_id))

    def _decide(self, ws, body, actor):
        exact(body, ('revision', 'logical_id', 'authorized', 'notice'))
        _identity(body['logical_id'], 'rld'); bounded_int(body['revision'], 1, 2**31-1)
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            policy = self._current(db, ws, actor, body['revision'])
            pinned_revision = policy['policy_hash']
        # Re-read evidence with the same named actor, outside the policy transaction.
        sources = {}
        if callable(self.evidence_source):
            for rid in policy['pins']:
                sources[rid] = self.evidence_source(ws, int(rid), actor)
        with self.access._tx(actor, write=True) as (db, _):
            policy = self._current(db, ws, actor, body['revision'])
            if policy['policy_hash'] != pinned_revision:
                raise WorkspaceConflict()
            logical = _hash([ws, body['logical_id']])
            rows = _rows(db, 'SELECT * FROM reliability_route_decisions WHERE logical_key=?', (logical,))
            if rows:
                value = self.opened(rows[0])
                if (value['id'] != rows[0]['id'] or value['workspace_id'] != ws or value['logical_key'] != logical
                        or value['policy_hash'] != policy['policy_hash'] or value['expires'] <= clock()
                        or value['source_revisions'] != {rid: _hash(source) for rid, source in sources.items()}
                        or any(self._pin(int(rid), policy['contract_id']) != pin for rid, pin in policy['pins'].items())):
                    raise WorkspaceConflict()
                # A replay never becomes an execution capability or a fresh decision.
                return self._decision_dto(value) | {'replayed': True}
            if db.execute('SELECT COUNT(*) FROM reliability_route_decisions WHERE workspace_id=?', (ws,)).fetchone()[0] >= 100:
                raise WorkspaceConflict()
            now = clock(); eligible = []; excluded = []; scores = []; expiries = [policy['expires']]; sample_count = 0; features = []
            host_failures = {}
            for rid, expected in policy['pins'].items():
                source = sources.get(rid)
                if type(source) is dict and source.get('circuit_state') in ('open', 'half_open', 'quarantined'):
                    host_failures[expected['host_key']] = True
            for rid, expected in policy['pins'].items():
                identity = int(rid); source = sources.get(rid); reason = None
                try:
                    current = self._pin(identity, policy['contract_id'])
                    if current != expected:
                        reason = 'pin_changed'
                except WorkspaceConflict:
                    reason = 'contract_or_safety_changed'
                if identity not in policy['share_resource_ids']:
                    reason = 'input_share_denied'
                if not reason:
                    if type(source) is not dict:
                        reason = 'evidence_pending'
                    elif (source.get('resource_id') != identity or source.get('agent_version') != expected['pin']['version']['id']
                          or source.get('schema_hash') != expected['pin']['version']['schema_hash']
                          or source.get('contract_id') != policy['contract_id']
                          or source.get('contract_revision') != CONTRACTS[policy['contract_id']]['version']
                          or source.get('contract_hash') != digest(CONTRACTS[policy['contract_id']])
                          or source.get('revoked') is not False):
                        reason = 'evidence_binding_changed'
                    elif (source.get('quality_status') != 'assessed' or source.get('source_fidelity') != 'verified'
                          or source.get('independent_qualified') is not True):
                        reason = 'unqualified_evidence'
                    elif (not finite(source.get('latest_observed_at')) or not finite(source.get('expires_at'))
                          or not 0 < source['latest_observed_at'] <= now < source['expires_at']):
                        reason = 'evidence_expired'
                    elif source.get('circuit_state', 'closed') != 'closed':
                        reason = 'circuit_probe_requires_separate_evaluation'
                    elif expected['host_key'] in host_failures:
                        reason = 'correlated_host_failure'
                if reason:
                    excluded.append({'resource_id': identity, 'reason': reason}); continue
                outcomes = source.get('outcomes'); n = source.get('logical_samples')
                latency = (source.get('latency_ms') or {}).get('p95') if type(source.get('latency_ms')) is dict else None
                if (type(outcomes) is not dict or set(outcomes) != {'succeeded', 'failed', 'unknown'}
                        or type(n) is not int or n < 1 or any(type(v) is not int or v < 0 for v in outcomes.values())
                        or sum(outcomes.values()) != n
                        or latency is not None and (not finite(latency) or not 0 <= latency <= 86400000)):
                    excluded.append({'resource_id': identity, 'reason': 'invalid_evidence_denominator'}); continue
                # Deterministic ranking among qualified equivalent candidates only.
                error_ratio = (outcomes['failed']+outcomes['unknown'])/n
                scores.append(((error_ratio, -source['latest_observed_at'], latency if latency is not None else math.inf, identity), identity))
                eligible.append(identity); sample_count += n; expiries.append(source['expires_at'])
                features.append({'resource_id': identity, 'logical_samples': n, 'outcomes': outcomes,
                                 'latest_observed_at': source['latest_observed_at'], 'expires_at': source['expires_at'],
                                 'p95_ms': latency, 'source_revision': _hash(source)})
            selected = min(scores)[1] if scores else None
            baseline = next(iter(policy['pins']))
            value = {'id': 'rrd_'+secrets.token_hex(16), 'workspace_id': ws, 'logical_key': logical,
                     'mode': policy['mode'], 'policy_revision': policy['revision'], 'policy_hash': policy['policy_hash'],
                     'rule_version': RULE_VERSION, 'selected_resource_id': selected, 'baseline_resource_id': int(baseline),
                     'eligible': eligible, 'excluded': excluded, 'reason': 'qualified_rule_choice' if selected else 'no_eligible_candidate',
                     'created': now, 'expires': min(expiries), 'selected_propensity': 1.0 if selected else None,
                     'logical_samples': sample_count, 'feature_snapshot': features,
                     'source_revisions': {rid: _hash(source) for rid, source in sources.items()}}
            db.execute('INSERT INTO reliability_route_decisions VALUES(?,?,?,?,?)',
                       (value['id'], ws, logical, _canonical(value), self.sign(value)))
            self.access._audit(db, actor, ws, 'reliability.routing.decision', value['id'], policy['revision'])
            return self._decision_dto(value)

    def offline_replay(self, ws, body, actor):
        """Replay signed feature snapshots; separate histories cannot prove causal gain."""
        exact(body, ('revision', 'authorized', 'notice')); bounded_int(body['revision'], 1, 2**31-1)
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor, owner=True)
            policy = self._policy(db, ws)
            if not policy or policy['revision'] != body['revision']:
                raise WorkspaceConflict()
            rows = _rows(db, 'SELECT * FROM reliability_route_decisions WHERE workspace_id=? ORDER BY id LIMIT 101', (ws,))
            if len(rows) > 100:
                raise WorkspaceConflict()
            replayed = 0; consistent = 0; baseline = {}; selected = {}
            for row in rows:
                value = self.opened(row)
                if value['id'] != row['id'] or value['workspace_id'] != ws or value['logical_key'] != row['logical_key']:
                    raise WorkspaceConflict()
                if value['policy_hash'] != policy['policy_hash']:
                    continue
                features = value['feature_snapshot']; scores = []
                for item in features:
                    counts = item['outcomes']; n = item['logical_samples']
                    scores.append((((counts['failed']+counts['unknown'])/n, -item['latest_observed_at'],
                                    item['p95_ms'] if item['p95_ms'] is not None else math.inf, item['resource_id']), item['resource_id']))
                    key = item['resource_id']
                    if item['resource_id'] == value['baseline_resource_id']:
                        if key not in baseline or item['latest_observed_at'] >= baseline[key]['latest_observed_at']:
                            baseline[key] = item
                    if item['resource_id'] == value['selected_resource_id']:
                        if key not in selected or item['latest_observed_at'] >= selected[key]['latest_observed_at']:
                            selected[key] = item
                replayed += 1
                consistent += int((min(scores)[1] if scores else None) == value['selected_resource_id'])

            def metrics(history):
                counts = dict.fromkeys(('succeeded', 'failed', 'unknown'), 0)
                for item in history.values():
                    for key in counts:
                        counts[key] += item['outcomes'][key]
                n = sum(counts.values())
                latencies = [item['p95_ms'] for item in history.values() if item['p95_ms'] is not None]
                return {'distinct_source_snapshots': len(history), 'logical_observations': n, 'outcomes': counts,
                        'observed_success_ratio': counts['succeeded']/n if n else None,
                        'observed_unknown_ratio': counts['unknown']/n if n else None,
                        'largest_snapshot_p95_ms': max(latencies) if latencies else None,
                        'latency_scope': 'gateway_observation_interval'}

            return {'profile': PROFILE, 'rule_version': RULE_VERSION, 'policy_hash': policy['policy_hash'],
                    'replayed_decisions': replayed, 'deterministic_matches': consistent,
                    'baseline_history': metrics(baseline), 'selected_history': metrics(selected),
                    'comparison_scope': 'separate_retained_histories_not_a_paired_corpus_benchmark',
                    'paired_corpus_verified': False, 'causal_improvement_established': False,
                    'historical_replay': True, 'business_calls': 0, 'extra_attempts': 0, 'online_learning': False,
                    'execution_authority': False}
