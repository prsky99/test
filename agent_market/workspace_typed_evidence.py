"""Purpose-bound lineage adapter for existing signed typed executions.

No new executor, source store, provider call or public endpoint is introduced.
Resolved input is reconstructed only under current retention permission and must
match the original signed input hash. Missing observations remain missing.
"""
from copy import deepcopy
import json
import math
import re

from .capability_contracts import CONTRACTS
from .capability_registry import digest, version_parts
from .private_artifact_keys import ArtifactKeyError
from .shadow_ledger import clock, exact, identifier
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash, _rows
from .workspace_reliability import MAX_OBSERVATIONS, MAX_SOURCES, PURPOSE, RETENTION_NOTICE, ReliabilityEvidence
from .workspace_typed_flows import TypedFlows, _project, LIMITS as TYPED_LIMITS

PROFILE = 'p2-01-typed-evidence-profile-v1'
NOTICE = 'typed-execution-source-retention-v1'
REF = re.compile(r'(wtr_[0-9a-f]{32}):([a-z][a-z0-9_]{0,31})')


class WorkspaceTypedEvidence:
    """Reuse the reliability plane's consent, encrypted source and audit tables."""
    def __init__(self, plane, typed_flows):
        if (not isinstance(plane, ReliabilityEvidence) or not isinstance(typed_flows, TypedFlows)
                or plane.access is not typed_flows.access or plane.execution is not typed_flows.execution):
            raise WorkspaceInvalid()
        self.plane, self.typed = plane, typed_flows
        self.access, self.store = plane.access, plane.store
        if getattr(plane, 'typed_evidence', None) not in (None, self):
            raise WorkspaceConflict()
        plane.typed_evidence = self

    @staticmethod
    def accepts(reference):
        return type(reference) is str and REF.fullmatch(reference) is not None

    def _snapshot(self, db, ws, flow, identity, *, decrypt=False):
        run, ticket, claims = self.typed._run(db, ws, flow, identity)
        if run['status'] not in ('running', 'succeeded', 'failed', 'unknown', 'denied'):
            raise WorkspaceConflict()
        authority = self.typed._authority(ws, self.typed._actor_from_claims(claims), write=False)
        row, _ = self.typed._flow(db, ws, flow)
        version = self.typed._version(db, ws, flow, claims['version_id'])
        if (any(claims.get(name) != value for name, value in authority.items())
                or row['revision'] != claims['flow_revision'] or row['version_id'] != claims['version_id']
                or _hash(version) != claims['version_hash'] or self.typed.execution._control(db) != claims['controls']):
            raise WorkspaceConflict()
        self.typed._guard(db, ticket['id'], claims)
        # Evidence of a failed call must not require a fresh successful call.
        # Check immutable bindings/schema/approval and purpose authority, while
        # keeping current transport health separate from historical outcomes.
        for node in version['definition']['nodes']:
            resource, current, _ = self.plane._resource(db, node['resource_id'])
            pin = version['pins'][node['id']]; parts = version_parts(resource)
            approvals = _rows(db, 'SELECT tool,created FROM capability_approvals WHERE version_id=? AND contract_id=?',
                              (pin['version']['id'], node['contract_id']))
            if (current['version_id'] != pin['version']['id'] or parts[0] != pin['version']['binding_hash']
                    or parts[1] != pin['version']['schema_hash'] or parts[2] != 'mcp-stateless-v1' or not parts[3]
                    or len(approvals) != 1 or approvals[0] != pin['approval']
                    or any(resource.get(key) not in (None, 0, False, '', '{}')
                           for key in ('auth_required', 'auth_observed', 'auth_declared', 'auth_info'))):
                raise WorkspaceConflict()
            full = resource.get('usage_full_tools')
            full = json.loads(full) if type(full) is str else full
            specs = [item for item in full if type(item) is dict and item.get('name') == pin['tool']] if type(full) is list else []
            from .capability_adapter_dispatch import profile as adapter_profile
            adapter=adapter_profile(resource,node['contract_id'],pin['tool'])
            if (adapter != pin.get('adapter') or len(specs) != 1 or not adapter and (specs[0].get('inputSchema') != CONTRACTS[node['contract_id']]['input_schema']
                    or specs[0].get('outputSchema') != CONTRACTS[node['contract_id']]['output_schema'])
                    or specs[0].get('annotations', {}).get('readOnlyHint') is not True
                    or specs[0].get('annotations', {}).get('destructiveHint') is not False
                    or specs[0].get('annotations', {}).get('idempotentHint') is not True):
                raise WorkspaceConflict()
        if (type(run['created']) not in (int, float) or type(run['deadline']) not in (int, float)
                or not math.isfinite(run['created']) or not math.isfinite(run['deadline'])
                or run['created'] > clock() or run['created'] >= run['deadline']):
            raise WorkspaceConflict()
        finished = run['finished']
        if finished is not None and (type(finished) not in (int, float) or not math.isfinite(finished)
                                    or not run['created'] <= finished <= clock()):
            raise WorkspaceConflict()
        rows = _rows(db, 'SELECT * FROM workspace_typed_flow_steps WHERE run_id=? ORDER BY node_id', (identity,))
        definitions = version['definition']['nodes']
        if len(rows) > len(definitions) or not 2 <= len(definitions) <= TYPED_LIMITS['nodes']:
            raise WorkspaceConflict()
        steps = {}; signatures = {}
        for row in rows:
            step = self.typed._step(row, version_id=claims['version_id'], decrypt=decrypt)
            if step['node_id'] in steps or step['node_id'] not in {node['id'] for node in definitions}:
                raise WorkspaceConflict()
            if (step['status'] not in ('prepared', 'dispatched', 'succeeded', 'failed', 'unknown', 'skipped')
                    or type(step['input_hash']) is not str or not re.fullmatch(r'[0-9a-f]{64}', step['input_hash'])):
                raise WorkspaceConflict()
            for field in ('dispatched', 'finished'):
                stamp = step[field]
                if stamp is not None and (type(stamp) not in (int, float) or not math.isfinite(stamp)
                                          or not run['created'] <= stamp <= (finished if finished is not None else clock())):
                    raise WorkspaceConflict()
            if step['finished'] is not None and step['dispatched'] is not None and step['finished'] < step['dispatched']:
                raise WorkspaceConflict()
            if step['status'] in ('succeeded', 'failed', 'unknown') and step['dispatched'] is None:
                raise WorkspaceConflict()
            steps[step['node_id']] = step; signatures[step['node_id']] = row['signature']
        integrity = digest([run, ticket['signature'], version, sorted(signatures.items())])
        return run, claims, version, steps, integrity

    def _binding(self, db, ws, bindings, version, *, source_ids=False):
        if type(bindings) is not list or len(bindings) != len(version['definition']['nodes']):
            raise WorkspaceInvalid()
        by_node = {}; consents = {}
        for item in bindings:
            fields = ('node_id', 'consent_id', 'case_id', 'source_id', 'observation_id')
            exact(item, fields)
            if type(item['node_id']) is not str or item['node_id'] in by_node:
                raise WorkspaceInvalid()
            identifier(item['source_id'], 'res'); identifier(item['observation_id'], 'reb')
            consent, cohort = self.plane._consent(db, ws, item['consent_id'])
            if item['case_id'] not in consent['case_pins']:
                raise WorkspaceInvalid()
            by_node[item['node_id']] = item; consents[item['node_id']] = (consent, cohort)
        if set(by_node) != {node['id'] for node in version['definition']['nodes']}:
            raise WorkspaceInvalid()
        for name in ('source_id', 'observation_id'):
            if len({v[name] for v in bindings}) != len(bindings):
                raise WorkspaceInvalid()
        for node in version['definition']['nodes']:
            consent, cohort = consents[node['id']]
            if (cohort['spec']['resource_id'] != node['resource_id']
                    or cohort['spec']['contract_id'] != node['contract_id']
                    or consent['current']['version_id'] != version['pins'][node['id']]['version']['id']):
                raise WorkspaceConflict()
        return by_node, consents

    def _resolved(self, node, steps):
        step = steps.get(node['id'])
        if step is None or step['status'] == 'skipped':
            return None
        value = deepcopy(node['input'])
        for name, projection in node['bindings'].items():
            parent = steps.get(projection['node_id'])
            if parent is None or parent['status'] != 'succeeded' or parent.get('output') is None:
                raise WorkspaceConflict()
            value[name] = _project(parent['output'], projection['path'])
        if _hash(value) != step['input_hash']:
            raise WorkspaceConflict()
        return value

    def _keys_available(self, source, steps):
        """Check current key availability without decrypting or exposing output."""
        try:
            envelope = source['encrypted_bundle']
            self.plane.cipher.keys.key(envelope['key_id'], self.plane.cipher.purpose + ':encrypt')
            for step in steps.values():
                if 'encrypted_output' in step:
                    self.typed.cipher.keys.key(step['encrypted_output']['key_id'], self.typed.cipher.purpose + ':encrypt')
        except (ArtifactKeyError, KeyError, TypeError):
            raise WorkspaceConflict() from None

    @staticmethod
    def _node_result(run, step):
        if step is None: return 'unreached'
        if step['status'] in ('prepared', 'skipped'): return step['status']
        if step['status'] == 'dispatched': return 'unknown'
        return step['status']

    def resolve_source(self, db, ws, resource, current, reference):
        match = REF.fullmatch(reference) if type(reference) is str else None
        if match is None: raise WorkspaceInvalid()
        identity, node_id = match.groups()
        rows = _rows(db, 'SELECT flow_id FROM workspace_typed_flow_runs WHERE id=? AND workspace_id=?', (identity, ws))
        if len(rows) != 1: raise WorkspaceDenied()
        run, _, version, steps, integrity = self._snapshot(db, ws, rows[0]['flow_id'], identity)
        node = next((node for node in version['definition']['nodes'] if node['id'] == node_id), None)
        step = steps.get(node_id)
        if (node is None or node['resource_id'] != current['resource_id']
                or version['pins'][node_id]['version']['id'] != current['version_id']
                or run['finished'] is None or step is None or step['dispatched'] is None):
            raise WorkspaceConflict()
        finished = step['finished'] if step['finished'] is not None else run['finished']
        return {'ref': reference, 'version': current['version_id'], 'current': True, 'not_dispatched': False,
                'outcome': self._node_result(run, step), 'started': step['dispatched'], 'finished': finished,
                'expires': run['finished'] + 604800, 'logical': identity, 'contract': node['contract_id'],
                'integrity': digest([integrity, node_id]), 'retained': True}

    def verify_bundle(self, db, ws, reference, source):
        manifest = source.get('typed_capture')
        if type(manifest) is not dict or manifest.get('profile') != PROFILE:
            raise WorkspaceConflict()
        run, _, version, steps, integrity = self._snapshot(db, ws, manifest['flow_id'], manifest['run_id'])
        by_node, _ = self._binding(db, ws, manifest['bindings'], version)
        if manifest['integrity'] != integrity or reference != manifest['run_id'] + ':' + manifest['node_id']:
            raise WorkspaceConflict()
        # Every parent source was retained under its own purpose authorization.
        # Erasure or withdrawal of any part invalidates whole-run source fidelity.
        for node in version['definition']['nodes']:
            step = steps.get(node['id'])
            if step is not None and step['dispatched'] is not None:
                item = by_node[node['id']]
                consent, _ = self.plane._consent(db, ws, item['consent_id'])
                self.plane._source(db, ws, item['source_id'], consent)
        run, _, version, steps, _ = self._snapshot(db, ws, manifest['flow_id'], manifest['run_id'], decrypt=True)
        node = next(node for node in version['definition']['nodes'] if node['id'] == manifest['node_id'])
        step = steps[node['id']]
        bundle = self.plane._retained(source)
        if (bundle['input'] != self._resolved(node, steps)
                or bundle['output'] != (step.get('output') if step['status'] == 'succeeded' else None)):
            raise WorkspaceConflict()
        return bundle

    def options(self, ws, actor):
        options = self.plane.options(ws, actor)
        return {'profile': PROFILE, 'notice': NOTICE, 'can_manage': options['can_manage'],
                'encryption_configured': options['encryption_configured'],
                'flows': self.typed.listing(ws, actor), 'provider_calls': 0, 'public_activation': False}

    def runs(self, ws, flow_id, actor):
        with self.access._tx(actor) as (db, _):
            self.plane.scope(ws, actor)
            self.typed._flow(db, ws, flow_id, active=False)
            rows = _rows(db, 'SELECT id FROM workspace_typed_flow_runs WHERE workspace_id=? AND flow_id=? ORDER BY created DESC,id LIMIT 30', (ws, flow_id))
            result = []
            for row in rows:
                run, _, _ = self.typed._run(db, ws, flow_id, row['id'])
                result.append({key: run[key] for key in ('id', 'status', 'created', 'finished')})
            return result

    def capture(self, ws, body, actor):
        exact(body, ('command_id', 'flow_id', 'run_id', 'logical_task_id', 'bindings', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        identifier(body['logical_task_id'], 'ret')
        with self.access._tx(actor, write=True) as (db, _):
            self.plane.scope(ws, actor, write=True, owner=True)
            run, _, version, steps, integrity = self._snapshot(db, ws, body['flow_id'], body['run_id'])
            by_node, consents = self._binding(db, ws, body['bindings'], version)
            if run['finished'] is None or run['status'] not in ('succeeded', 'failed', 'unknown', 'denied'):
                raise WorkspaceConflict()
            if any(run['created'] < consent['created'] for consent, _ in consents.values()):
                raise WorkspaceConflict()
            replay = self.plane._command(db, ws, body, actor)
            if replay is not None: return replay
            if not self.plane.cipher.configured:
                raise WorkspaceConflict()
            run, _, version, steps, _ = self._snapshot(db, ws, body['flow_id'], body['run_id'], decrypt=True)
            dispatched = [node for node in version['definition']['nodes'] if steps.get(node['id'], {}).get('dispatched') is not None]
            for table, limit in (('sources', MAX_SOURCES), ('observations', MAX_OBSERVATIONS)):
                count = db.execute('SELECT COUNT(*) FROM reliability_sources WHERE workspace_id=?', (ws,)).fetchone()[0] if table == 'sources' else db.execute('SELECT COUNT(*) FROM reliability_observations WHERE workspace_id=?', (ws,)).fetchone()[0]
                if count + len(dispatched) > limit: raise WorkspaceConflict()
            result_nodes = []
            tombstones = self.plane._tombstones(db, ws)
            for node in version['definition']['nodes']:
                step = steps.get(node['id']); item = by_node[node['id']]
                entry = {'node_id': node['id'], 'status': self._node_result(run, step), 'source_id': None, 'observation_id': None}
                if step is not None and step['dispatched'] is not None:
                    consent, cohort = consents[node['id']]
                    reference = run['id'] + ':' + node['id']
                    prior = _rows(db, 'SELECT * FROM reliability_observations WHERE workspace_id=? ORDER BY id LIMIT 401', (ws,))
                    if any(self.plane.opened(row).get('run_ref') == reference for row in prior):
                        raise WorkspaceConflict()
                    bundle = {'input': self._resolved(node, steps),
                              'output': step.get('output') if step['status'] == 'succeeded' else None,
                              'sources': [{'reference': reference, 'text': 'Signed typed execution source; not independent provenance.'}]}
                    encoded = _canonical(bundle).encode('ascii'); bundle_hash = _hash(bundle)
                    if len(encoded) > 32768 or item['source_id'] in tombstones or 'hash:' + bundle_hash in tombstones:
                        raise WorkspaceConflict()
                    if db.execute('SELECT 1 FROM reliability_sources WHERE id=?', (item['source_id'],)).fetchone() or db.execute('SELECT 1 FROM reliability_observations WHERE id=?', (item['observation_id'],)).fetchone():
                        raise WorkspaceConflict()
                    source = {'id': item['source_id'], 'workspace_id': ws, 'cohort_id': cohort['id'], 'consent_id': consent['id'],
                              'purpose': PURPOSE, 'created': clock(), 'expires': consent['expires'], 'bundle_hash': bundle_hash,
                              'input_hash': step['input_hash'], 'output_hash': _hash(bundle['output']) if step['status'] == 'succeeded' else None,
                              'typed_capture': {'profile': PROFILE, 'flow_id': body['flow_id'], 'run_id': run['id'],
                                                'node_id': node['id'], 'integrity': integrity, 'bindings': body['bindings']}}
                    try: source['encrypted_bundle'] = json.loads(self.plane.cipher.seal(encoded, self.plane._context(source)))
                    except ArtifactKeyError: raise WorkspaceConflict() from None
                    db.execute('INSERT INTO reliability_sources VALUES(?,?,?,?,?)', (source['id'], ws, cohort['id'], _canonical(source), self.plane.sign(source)))
                    execution = self.resolve_source(db, ws, {}, consent['current'], reference)
                    observation = {'id': item['observation_id'], 'workspace_id': ws, 'cohort_id': cohort['id'],
                                   'consent_id': consent['id'], 'case_id': item['case_id'], 'source_id': source['id'],
                                   'logical_task_id': body['logical_task_id'], 'run_ref': reference, 'run_hash': execution['integrity'],
                                   'outcome': execution['outcome'], 'started': execution['started'], 'finished': execution['finished'],
                                   'expires': min(execution['expires'], source['expires']), 'created': clock(),
                                   'agent_version': consent['current']['version_id'], 'case_pin': consent['case_pins'][item['case_id']], 'source_profile': PROFILE}
                    db.execute('INSERT INTO reliability_observations VALUES(?,?,?,?,?,?)',
                               (observation['id'], ws, cohort['id'], body['logical_task_id'], _canonical(observation), self.plane.sign(observation)))
                    entry.update(source_id=source['id'], observation_id=observation['id'])
                result_nodes.append(entry)
            return self.plane._record(db, ws, body, actor, {'profile': PROFILE, 'action': 'typed_capture', 'id': run['id'],
                'flow_id': body['flow_id'], 'logical_task_id': body['logical_task_id'], 'nodes': result_nodes,
                'provider_calls': 0, 'quality_status': 'unassessed', 'public_activation': False})

    def current_run(self, ws, flow_id, run_id, actor):
        with self.access._tx(actor) as (db, _):
            self.plane.scope(ws, actor)
            run, claims, version, steps, integrity = self._snapshot(db, ws, flow_id, run_id)
            observations = _rows(db, 'SELECT * FROM reliability_observations WHERE workspace_id=? ORDER BY id LIMIT 401', (ws,))
            if len(observations) > MAX_OBSERVATIONS: raise WorkspaceConflict()
            observed = {}
            for row in observations:
                value = self.plane.opened(row)
                if any(value[key] != row[key] for key in ('id', 'workspace_id', 'cohort_id', 'logical_task_id')):
                    raise WorkspaceConflict()
                if value.get('source_profile') == PROFILE and value['run_ref'].startswith(run_id + ':'):
                    observed.setdefault(value['run_ref'], []).append(value)
            nodes = []; events = []; last = run['created']; closed = 0
            for node in version['definition']['nodes']:
                step = steps.get(node['id']); reference = run_id + ':' + node['id']; retained = False; fingerprints = []; output_hash = None
                for observation in observed.get(reference, []):
                    try:
                        consent, _ = self.plane._consent(db, ws, observation['consent_id'])
                        source = self.plane._source(db, ws, observation['source_id'], consent)
                        if source['typed_capture']['integrity'] != integrity or observation['run_hash'] != digest([integrity, node['id']]):
                            raise WorkspaceConflict()
                        self._binding(db, ws, source['typed_capture']['bindings'], version)
                        for other in source['typed_capture']['bindings']:
                            if steps.get(other['node_id'], {}).get('dispatched') is not None:
                                other_consent, _ = self.plane._consent(db, ws, other['consent_id'])
                                other_source = self.plane._source(db, ws, other['source_id'], other_consent)
                                self._keys_available(other_source, steps)
                        retained = True; output_hash = source['output_hash']; fingerprints.append(digest(source))
                    except (WorkspaceConflict, WorkspaceDenied):
                        fingerprints.append('unavailable')
                node_events = []
                if step is not None:
                    for name, event_type in (('dispatched', 'dispatch'), ('finished', 'closed_action')):
                        stamp = step[name]
                        if stamp is None: continue
                        if stamp < last: raise WorkspaceConflict()
                        last = stamp
                        if event_type == 'closed_action' and step['status'] not in ('succeeded', 'failed'):
                            event_type = 'terminal_observation'
                        if event_type == 'closed_action': closed += 1
                        event = {'sequence': len(events)+1, 'event_type': event_type, 'observed_at': stamp,
                                 'node_id': node['id'], 'closed_action_sequence': closed}
                        events.append(event); node_events.append(event)
                pin = version['pins'][node['id']]
                nodes.append({'node_id': node['id'], 'attempt_ref': reference if step is not None and step['dispatched'] is not None else None,
                              'status': self._node_result(run, step), 'observed_status': step['status'] if step else 'unreached',
                              'resource_id': node['resource_id'], 'contract_id': node['contract_id'], 'agent_version': pin['version']['id'],
                              'schema_hash': pin['version']['schema_hash'],
                              'input_hash': step['input_hash'] if step is not None and step['dispatched'] is not None else None,
                              'prepared_input_hash': step['input_hash'] if step is not None and step['dispatched'] is None else None,
                              'source_retained': retained, 'input_source_ref': reference if retained else None,
                              'output_source_ref': reference if retained and step['status'] == 'succeeded' else None,
                              'output_hash': output_hash if retained else None,
                              'source_revision': digest(fingerprints),
                              'source_fidelity': 'retained_not_independently_assessed' if retained else 'unassessable',
                              'parents': node['after'], 'projections': deepcopy(node['bindings']),
                              'branch': None if node['when'] is None else {'node_id': node['when']['node_id'], 'path': node['when']['path'],
                                  'taken': None if step is None else step['status'] != 'skipped'},
                              'events': node_events})
            result = {'profile': PROFILE, 'logical_run_ref': run_id, 'flow_id': flow_id, 'graph_revision': claims['flow_revision'],
                      'graph_version': version['id'], 'graph_hash': claims['version_hash'],
                      'status': 'unknown' if run['status'] == 'running' and run['deadline'] <= clock() else run['status'],
                      'observed_status': run['status'],
                      'current': True, 'evidence_current': all(n['source_retained'] for n in nodes if n['attempt_ref'] is not None) and bool(observed),
                      'nodes': nodes, 'events': events, 'closed_actions': closed,
                      'authority_revision': digest({key: claims[key] for key in ('workspace_revision', 'member_revision', 'member_role', 'user_role', 'controls')}),
                      'execution_fence': digest([run['ticket_hash'], claims['controls'], claims['version_hash']]),
                      'logical_samples': int(any(observed.values())), 'attempts': sum(n['attempt_ref'] is not None for n in nodes),
                      'quality_status': 'unassessed', 'business_outcome': 'unassessed', 'automatic_retry': False,
                      'delivery_status': 'outside_profile', 'payment_status': 'outside_profile',
                      'provider_calls': 0, 'public_activation': False}
            result['source_revision'] = digest([result, integrity])
            return result
