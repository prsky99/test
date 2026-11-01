"""Owned offline paired experiment over the existing evaluation jobs and worker.

There is no external input, endpoint, second executor, or operating controller.
Only this producer's in-process evidence envelope is accepted by the analyzer.
The HMAC is an accidental-mixing/tamper guard inside this process, not a public
attestation or independent scientific qualification.
"""
from collections import Counter, defaultdict, deque
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets
import time
from unittest.mock import patch

import httpx

from agent_market.capability_contracts import CONTRACTS
from agent_market.capability_registry import Registry
from agent_market.collector import usage
from agent_market.concierge.proxy import McpProxy
from agent_market.gateway.store import Store
from agent_market.infra.redis_hub import RedisHub
from agent_market.reliability_evaluation import NOTICE as EVAL_NOTICE, ReliabilityEvaluation
from agent_market.reliability_evaluation_worker import EvaluationWorker, McpReadEvaluator
from agent_market.reliability_research import NOTICE, ReliabilityResearch, item_goal_hash
from agent_market.workspace_access import SessionActor, WorkspaceAccess, _canonical, _hash
from agent_market.workflows import WorkflowRuntime

PROFILE = 'owned-paired-evaluation-experiment-v1'
_OWNER, _SEAL_KEY = object(), secrets.token_bytes(32)
_SOURCES = ('agent_market/reliability_evaluation.py',
            'agent_market/reliability_evaluation_worker.py',
            'agent_market/reliability_research.py',
            'scripts/rehearse_reliability_experiment.py')
_ROOT = Path(__file__).resolve().parents[1]
_OUTCOMES = ('goal_pass', 'agent_failure', 'unknown', 'unassessable', 'oracle_error')
_POLICIES = (2, 3)


@dataclass(frozen=True, repr=False)
class ExperimentEvidence:
    owner: object = field(repr=False)
    payload: bytes = field(repr=False)
    binding_hash: str
    signature: str = field(repr=False)


def _seal(value):
    payload = _canonical(value).encode('ascii')
    return ExperimentEvidence(_OWNER, payload, hashlib.sha256(payload).hexdigest(),
                              hmac.new(_SEAL_KEY, payload, hashlib.sha256).hexdigest())


def _opened(evidence):
    if (type(evidence) is not ExperimentEvidence or evidence.owner is not _OWNER
            or type(evidence.payload) is not bytes or len(evidence.payload) > 262144
            or type(evidence.binding_hash) is not str or not re.fullmatch('[0-9a-f]{64}', evidence.binding_hash)
            or type(evidence.signature) is not str or not re.fullmatch('[0-9a-f]{64}', evidence.signature)
            or not hmac.compare_digest(evidence.binding_hash, hashlib.sha256(evidence.payload).hexdigest())
            or not hmac.compare_digest(evidence.signature,
                hmac.new(_SEAL_KEY, evidence.payload, hashlib.sha256).hexdigest())):
        raise ValueError('Use unchanged evidence from this owned offline producer.')
    value = json.loads(evidence.payload)
    if (_canonical(value).encode('ascii') != evidence.payload or value['profile'] != PROFILE
            or value['manifest_hash'] != _hash(value['manifest'])):
        raise ValueError('The experiment manifest binding changed.')
    return value


def _source_hashes():
    return {name: hashlib.sha256((_ROOT / name).read_bytes()).hexdigest() for name in _SOURCES}


def _fixture_item(now):
    return {'title': 'Approved synthetic reference', 'url': 'https://docs.example/reference',
            'excerpt': 'An approved deterministic documentation fixture.', 'version': 'fixture-v1',
            'retrieved_at': datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z')}


def _fault(case_id):
    # Declared before dispatch. No fault depends on an observed outcome.
    return {'alpha-1-0': 'empty_goal', 'alpha-1-1': 'empty_goal',
            'beta-0-0': 'response_loss', 'beta-0-1': 'schema_drift',
            'beta-1-0': 'partial'}.get(case_id, 'none')


class _OwnedTrace:
    """Metadata from actual local MockTransport invocations, never model text."""
    def __init__(self, spec, clock_value):
        self.spec, self.clock_value = spec, clock_value
        self.arm, self.occurrences = 'baseline', Counter()
        self.pending, self.traces = defaultdict(deque), {}
        self.packets, self.handshakes = 0, 0
        self.started = time.perf_counter()

    def elapsed(self):
        return time.perf_counter()-self.started

    def handle(self, request):
        if str(request.url) != 'https://owned-experiment.example/mcp' or request.method != 'POST':
            raise AssertionError('Only the owned fixed MockTransport destination is allowed.')
        body = json.loads(request.content)
        method = body.get('method')
        if method in ('server/discover', 'tools/list'):
            self.handshakes += 1
            result = {'protocolVersion': '2026-07-28'} if method == 'server/discover' else {'tools': [self.spec]}
        elif method == 'tools/call':
            if body.get('params', {}).get('name') != self.spec['name']:
                raise AssertionError('The approved fixture tool changed.')
            inputs = body['params']['arguments']
            input_hash = _hash(inputs)
            base = 'alpha' if 'alpha' in inputs['query'] else 'beta'
            transformed = int(inputs['query'].startswith(' '))
            occurrence = self.occurrences[(self.arm, input_hash)]
            self.occurrences[(self.arm, input_hash)] += 1
            if occurrence > 1:
                raise AssertionError('A fixture episode was replayed.')
            case_id = f'{base}-{occurrence}-{transformed}'
            fault = _fault(case_id) if self.arm == 'perturbed' else 'none'
            trace = {'case_id': case_id, 'input_hash': input_hash, 'fault': fault,
                     'events': [{'sequence': 1, 'event_type': 'packet_dispatched',
                                 'elapsed_seconds': self.elapsed()}]}
            self.packets += 1
            self.pending[(self.arm, input_hash)].append(trace)
            if fault == 'response_loss':
                trace['events'].append({'sequence': 2, 'event_type': 'transport_uncertain',
                                        'elapsed_seconds': self.elapsed()})
                raise httpx.ReadTimeout('Owned fixture response loss', request=request)
            output = {'items': [_fixture_item(self.clock_value[0])], 'partial': False}
            if fault == 'empty_goal':
                output['items'] = []
            elif fault == 'partial':
                output = {'items': [], 'partial': True}
            elif fault == 'schema_drift':
                output = {'invalid_fixture_schema': True}
            result = {'structuredContent': output}
            trace['events'].append({'sequence': 2, 'event_type': 'mock_response_returned',
                                    'elapsed_seconds': self.elapsed()})
        else:
            raise AssertionError('An undeclared fixture method was requested.')
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})


class _ObservedResearch(ReliabilityResearch):
    """Record the existing trusted oracle callback without changing its result."""
    def __init__(self, access, evaluation, trace):
        super().__init__(access, evaluation)
        self.trace = trace

    def observe(self, envelope, output, outcome):
        proof = super().observe(envelope, output, outcome)
        observation = self.accept_observation(proof, envelope)
        key = (self.trace.arm, observation['input_hash'])
        pending = self.trace.pending[key]
        if not pending:
            # Missing packet/trace is preserved, never manufactured as a failure.
            return proof
        trace = pending.popleft()
        if trace['case_id'] != observation['case_id']:
            raise AssertionError('The observed packet is not the same approved seeded episode.')
        trace['events'].append({'sequence': 3,
            'event_type': 'goal_observed' if observation['outcome'] == 'goal_pass' else 'oracle_assessment',
            'elapsed_seconds': self.trace.elapsed()})
        trace['envelope_hash'] = _hash(envelope)
        self.trace.traces[envelope['job_id']] = trace
        return proof


def produce_owned_fixture():
    """No path, transport, task, threshold, endpoint, or claimed verdict is accepted."""
    before = _source_hashes()
    # Both arms use the same approved input/seed/pin/oracle. Separate evaluation
    # windows preserve the existing host budget; retrieval time is not a goal.
    clock_value = [int(time.time()//600)*600+30]
    spec = {'name': 'search_docs', 'description': 'Search approved synthetic documentation',
        'inputSchema': deepcopy(CONTRACTS['docs.search.v1']['input_schema']),
        'outputSchema': deepcopy(CONTRACTS['docs.search.v1']['output_schema']),
        'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}}
    item_hash = item_goal_hash('docs.search.v1', _fixture_item(clock_value[0]))
    inputs = {name: {'query': f'Approved public {name} documentation', 'language': 'en', 'limit': 2}
              for name in ('alpha', 'beta')}
    manifest = {'profile': PROFILE, 'version': 'paired-fixture-v1', 'seed': 19,
        'environment': 'owned_in_memory_mock_transport', 'synthetic': True,
        'contract_id': 'docs.search.v1', 'schema_hash': _hash(spec),
        'inputs': inputs, 'input_hashes': {name: _hash(value) for name, value in inputs.items()},
        'transform': 'outer-whitespace-v1', 'transform_version': 'reviewed-whitespace-only-v1',
        'oracle_version': 'exact-approved-item-goal-v1', 'expected_items': [item_hash],
        'milestone_version': 'observed-approved-goal-and-terminal-closure-v1',
        'threshold_version': 'synthetic-prefix-sensitivity-v1', 'fixture_thresholds': list(_POLICIES),
        'threshold_selection': 'precommitted_fixture_sensitivity_no_operating_choice',
        'analysis_version': 'paired-admitted-denominators-v1', 'k': 2,
        'baseline_window': clock_value[0]//600*600, 'arm_window_delta_seconds': 600,
        'fault_schedule': {f'{base}-{trial}-{variant}': _fault(f'{base}-{trial}-{variant}')
            for base in inputs for trial in range(2) for variant in range(2)},
        'source_hashes': before, 'expected_pairs': 8,
        'source_hash_scope': 'producer_and_research_evaluation_modules_only_not_repository_freeze',
        'trace_profile': 'existing-evaluation-job-and-owned-mock-transport-v1',
        'source_scope': 'single_read_action_not_remote_internal_steps_or_multinode_frontier',
        'replay_assumption': 'discard_observed_suffix_after_would_stop_no_remote_cancellation',
        'surface_axes': {'epsilon': 'discrete_original_or_reviewed_whitespace',
                         'lambda': 'categorical_fixture_fault_not_calibrated_severity',
                         'k': 'all_repeated_goals_must_pass'},
        'planned_arms': ['baseline', 'perturbed']}
    manifest['episode_input_hashes'] = {f'{base}-{trial}-{variant}': _hash(value if variant == 0 else
        dict(value, query=' '+value['query']+' ')) for base, value in inputs.items()
        for trial in range(2) for variant in range(2)}
    trace = _OwnedTrace(spec, clock_value)
    store = worker = client = None
    network_attempts = 0

    def blocked_network(*args, **kwargs):
        nonlocal network_attempts
        network_attempts += 1
        raise AssertionError('The owned experiment cannot open network sockets or resolve hosts.')

    with ExitStack() as scope:
        cache = RedisHub(); cache._closed = True
        scope.enter_context(patch.object(RedisHub, 'get_instance', staticmethod(lambda: cache)))
        for target in ('socket.create_connection', 'socket.socket.connect', 'socket.socket.connect_ex', 'socket.getaddrinfo'):
            scope.enter_context(patch(target, blocked_network))
        # Module-local simulated fixture time does not change a running server.
        for target in ('agent_market.reliability_evaluation.clock',
                       'agent_market.reliability_evaluation_worker.clock',
                       'agent_market.reliability_research.clock'):
            scope.enter_context(patch(target, lambda: clock_value[0]))
        # Never read an operating encryption key even if the shell has one set.
        scope.enter_context(patch.dict('os.environ', {'AGENT_UPDATES_KEY': '',
            'ADMIN_BOOTSTRAP_PASSWORD': secrets.token_urlsafe(32), 'DEPLOYMENT_MODE': 'test'}))
        try:
            store = Store()
            runtime = WorkflowRuntime(store)
            access = WorkspaceAccess(store, runtime.key)
            ref = 'sha256:'+hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            with store.tx() as db:
                uid = db.execute('SELECT COALESCE(MAX(id),0)+1 FROM admin_users').fetchone()[0]
                db.execute('INSERT INTO admin_users VALUES(?,?,?,?,?,?,1,?,?,NULL)',
                    (uid, 'owned-experiment', 'unused-fixture-hash', 'unused-fixture-salt', 'superadmin',
                     'Synthetic experiment owner', time.time(), time.time()))
                db.execute('INSERT INTO admin_sessions VALUES(?,?,?,?,?,?,?,?,?)',
                    (ref, uid, 'owned-experiment', 'superadmin', 'Synthetic experiment owner',
                     time.time(), time.time()+3600, None, None))
            actor = SessionActor(uid, ref)
            ws = access.provision({'name': 'Owned offline evaluation', 'owner_id': uid}, actor)['id']
            rid = store.upsert_resource({'key': 'mcp:https://owned-experiment.example/mcp', 'kind': 'mcp',
                'source': 'mcp-registry', 'name': 'Owned synthetic reference',
                'description': 'Approved deterministic documentation fixture', 'category': 'dev_tools',
                'url': 'https://owned-experiment.example/mcp', 'price_usdc': 0, 'details': {}})
            compact = usage.compact_tools([spec])
            store.record_usage(rid, compact, usage.tools_hash(compact), {}, None, {'ok': True}, full_tools=[spec])
            with store.tx() as db:
                db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid,))
            Registry(store).approve(store.resource(rid), 'docs.search.v1', 'search_docs')
            client = httpx.Client(transport=httpx.MockTransport(trace.handle))
            runtime.proxy = McpProxy(store, allow_private=True, http=client)
            evaluation = ReliabilityEvaluation(access, runtime)
            research = _ObservedResearch(access, evaluation, trace)
            adapter = McpReadEvaluator(evaluation, enabled=True)
            evaluation.read_evaluator, evaluation.evaluator_authorizer = adapter, adapter.authorizer
            worker = EvaluationWorker(evaluation, enabled=True, max_jobs_per_tick=8)
            evaluation.worker = worker
            evaluation.set_control(ws, {'revision': 0, 'enabled': True,
                'authorized': True, 'notice': EVAL_NOTICE}, actor)
            arms, plan_revision = {}, 0
            for arm in manifest['planned_arms']:
                trace.arm = arm
                body = {'manifest_id': 'rrm_'+secrets.token_hex(16), 'version': 'paired-'+arm+'-v1',
                    'contract_id': 'docs.search.v1', 'cases': [{'case_id': name, 'input': value,
                        'expected_items': [item_hash]} for name, value in inputs.items()],
                    'k': 2, 'mutators': ['outer-whitespace-v1'], 'seed': manifest['seed'],
                    'reference_time': clock_value[0], 'timezone': 'UTC', 'locale': 'en-US',
                    'dataset_version': 'owned-synthetic-documentation-v1',
                    'oracle_version': manifest['oracle_version'], 'analysis': {'version': 'paired-fixture-v1',
                        'minimum_pairs': 2, 'grouping': 'resource-version-host-window-case-trials',
                        'unknown_policy': 'retain_in_admitted_denominator',
                        'confidence': 'conservative-wilson95-and-cluster-count'},
                    'expires': clock_value[0]+1200, 'adaptive_priority': False, 'authorized': True, 'notice': NOTICE,
                    'semantic_attestation': 'reviewed_search_whitespace_preserves_task',
                    'data_attestation': 'synthetic_or_licensed_no_personal_data'}
                approved = research.register_manifest(ws, body, actor)
                plan = evaluation.configure_plan(ws, {'revision': plan_revision, 'corpus_id': approved['corpus_id'],
                    'resource_ids': [rid], 'interval_seconds': 600, 'jitter_seconds': 0,
                    'per_host_budget': 10, 'expires': clock_value[0]+1200,
                    'authorized': True, 'notice': EVAL_NOTICE}, actor)
                plan_revision = plan['revision']
                worker.activate(ws, actor, plan_revision)
                attempted = worker.tick()['attempted_jobs']
                replayed = worker.tick()['attempted_jobs']
                if attempted != 8 or replayed:
                    raise AssertionError('The owned experiment must dispatch eight unique episodes once per arm.')
                with store.tx() as db:
                    current_manifest = research._manifest(db, ws, approved['id'])
                    current_plan = evaluation._plan(db, ws)
                    corpus = evaluation._corpus(db, ws, approved['corpus_id'])
                    case_inputs = {case['case_id']: case['input'] for case in corpus['cases']}
                    rows = db.execute('SELECT id FROM reliability_eval_jobs WHERE workspace_id=?', (ws,)).fetchall()
                    jobs = [evaluation._job(db, ws, row['id']) for row in rows]
                episodes = []
                for job in jobs:
                    if job['plan_revision'] != plan_revision:
                        continue
                    observed = job.get('research_observation')
                    recorded = deepcopy(trace.traces.get(job['id'], {}))
                    events = recorded.get('events', [])
                    if job['state'] in ('completed', 'failed') and events:
                        events.append({'sequence': len(events)+1, 'event_type': 'closed_action',
                                       'elapsed_seconds': trace.elapsed()})
                    if events:
                        events.append({'sequence': len(events)+1, 'event_type': 'terminal_observation',
                                       'elapsed_seconds': trace.elapsed()})
                    source = {'job_id': job['id'], 'logical_key': job['logical_key'], 'case_id': job['case_id'],
                        'plan_revision': plan_revision, 'corpus_hash': current_manifest['corpus_hash'],
                        'manifest_definition_hash': current_manifest['definition_hash'],
                        'pin_hash': _hash(current_plan['pins'][str(rid)]['pin']),
                        'input_hash': _hash(case_inputs[job['case_id']]),
                        'observation_hash': _hash(observed), 'state': job['state'],
                        'signed_job_payload_hash': _hash(job), 'events': events,
                        'transport_envelope_hash': recorded.get('envelope_hash')}
                    episodes.append({'case_id': job['case_id'], 'input_hash': source['input_hash'],
                        'fault': recorded.get('fault'), 'outcome': observed['outcome'] if observed else 'unknown',
                        'state': job['state'], 'events': events, 'source': source,
                        'source_revision': _hash(source)})
                arms[arm] = {'plan_revision': plan_revision,
                    'manifest_definition_hash': current_manifest['definition_hash'],
                    'corpus_hash': current_manifest['corpus_hash'], 'pin_hash': _hash(current_plan['pins'][str(rid)]['pin']),
                    'expected_episodes': 8, 'attempted_episodes': attempted, 'second_tick_attempts': replayed,
                    'research_binding': {key: current_manifest[key] for key in
                        ('seed', 'k', 'mutators', 'oracle_version', 'episodes', 'goals', 'reference_time', 'timezone', 'locale')},
                    'episodes': sorted(episodes, key=lambda row: row['case_id']),
                    'research_analysis': research.analyze(ws, approved['id'], actor)}
                worker.deactivate(ws)
                clock_value[0] += manifest['arm_window_delta_seconds']
            if before != _source_hashes():
                raise AssertionError('Source changed while the immutable experiment was running.')
            if network_attempts:
                raise AssertionError('The owned experiment attempted to leave its MockTransport fixture.')
            evidence = _seal({'profile': PROFILE, 'manifest': manifest, 'manifest_hash': _hash(manifest),
                'arms': arms, 'packets': trace.packets, 'handshakes': trace.handshakes,
                'external_network_attempts': network_attempts})
        finally:
            if worker is not None:
                worker.close()
            if client is not None:
                client.close()
            if store is not None:
                store._db.close()
    return evidence


def _rate(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator/denominator if denominator else None}


def _prefix(episode, threshold):
    count, closed = 0, 0
    for event in episode['events']:
        if event['event_type'] == 'goal_observed':
            count = 0
        elif event['event_type'] == 'closed_action':
            closed += 1
            count = 0
        else:
            count += 1
        if count >= threshold:
            return {'would_stop': True, 'sequence': event['sequence'],
                    'closed_actions_before_stop': closed,
                    'discarded_observed_suffix_events': len(episode['events'])-event['sequence']}
    return {'would_stop': False, 'sequence': None, 'closed_actions_before_stop': closed,
            'discarded_observed_suffix_events': 0}


def _pair_category(a, b):
    if a is None or b is None:
        return 'missing'
    return ('unknown' if 'unknown' in (a, b) else 'unassessable' if 'unassessable' in (a, b)
        else 'oracle_error' if 'oracle_error' in (a, b) else 'both_goal_pass'
        if a == b == 'goal_pass' else 'both_failed' if a == b == 'agent_failure'
        else 'goal_regression' if a == 'goal_pass' else 'goal_improvement')


def analyze_evidence(evidence):
    """Analyze only producer-bound facts; no client verdicts or traces accepted."""
    started = time.perf_counter()
    value = _opened(evidence)
    manifest, arms = value['manifest'], value['arms']
    expected = manifest['expected_pairs']
    if (manifest['fixture_thresholds'] != list(_POLICIES) or set(arms) != {'baseline', 'perturbed'}
            or manifest['seed'] != 19 or type(expected) is not int or expected != 8
            or len(manifest['episode_input_hashes']) != expected):
        raise ValueError('The precommitted arms or fixture sensitivity policies changed.')
    by_arm, states, missing = {}, {}, {}
    for name, arm in arms.items():
        bound = arm['research_binding']
        if (bound['seed'] != manifest['seed'] or bound['k'] != manifest['k']
                or bound['mutators'] != [manifest['transform']] or bound['oracle_version'] != manifest['oracle_version']
                or bound['timezone'] != 'UTC' or bound['locale'] != 'en-US'
                or any(goal != manifest['expected_items'] for goal in bound['goals'].values())):
            raise ValueError('The arm is outside the immutable seed, oracle or approved transform.')
        rows = {}
        for row in arm['episodes']:
            source = row['source']
            if (row['case_id'] in rows or row['outcome'] not in _OUTCOMES
                    or row['case_id'] not in manifest['episode_input_hashes']
                    or row['input_hash'] != manifest['episode_input_hashes'][row['case_id']]
                    or bound['episodes'][row['case_id']]['input_hash'] != row['input_hash']
                    or row['source_revision'] != _hash(source) or row['events'] != source['events']
                    or any(row[key] != source[key] for key in ('case_id', 'input_hash', 'state'))
                    or source['pin_hash'] != arm['pin_hash']
                    or source['manifest_definition_hash'] != arm['manifest_definition_hash']
                    or source['plan_revision'] != arm['plan_revision'] or source['corpus_hash'] != arm['corpus_hash']):
                raise ValueError('The signed-job/trace/manifest source binding changed.')
            previous_time = -1
            for index, event in enumerate(row['events'], 1):
                if (type(event['sequence']) is not int or event['sequence'] != index
                        or type(event['elapsed_seconds']) not in (int, float)
                        or not math.isfinite(event['elapsed_seconds']) or event['elapsed_seconds'] < previous_time
                        or event['event_type'] not in ('packet_dispatched', 'mock_response_returned',
                            'transport_uncertain', 'goal_observed', 'oracle_assessment', 'closed_action', 'terminal_observation')):
                    raise ValueError('The bounded observed trace is malformed.')
                previous_time = event['elapsed_seconds']
            if (row['events'] and sum(event['event_type'] == 'goal_observed' for event in row['events']) != int(row['outcome'] == 'goal_pass')
                    or any(event['event_type'] == 'closed_action' for event in row['events']) and row['state'] not in ('completed', 'failed')):
                raise ValueError('A goal or closed action lacks a definitive observed source.')
            rows[row['case_id']] = row
        if len(rows) > expected:
            raise ValueError('Observed episodes exceed the immutable planned denominator.')
        by_arm[name] = rows
        states[name] = {outcome: sum(row['outcome'] == outcome for row in rows.values()) for outcome in _OUTCOMES}
        missing[name] = expected-len(rows)
    surface = []
    for arm_name, rows in by_arm.items():
        groups = defaultdict(list)
        for identity in manifest['episode_input_hashes']:
            fault = manifest['fault_schedule'][identity] if arm_name == 'perturbed' else 'none'
            groups[(int(identity[-1]), fault)].append(rows.get(identity))
        for (epsilon, fault), cell in sorted(groups.items()):
            surface.append({'arm': arm_name, 'epsilon': epsilon, 'lambda_fixture_fault': fault,
                'planned_denominator': len(cell), 'observed_denominator': sum(row is not None for row in cell),
                'goal_pass': sum(row is not None and row['outcome'] == 'goal_pass' for row in cell),
                'unknown': sum(row is not None and row['outcome'] == 'unknown' for row in cell),
                'unassessable': sum(row is not None and row['outcome'] == 'unassessable' for row in cell),
                'missing': sum(row is None for row in cell),
                'inference': 'descriptive_sparse_discrete_fixture_cell_no_interpolation'})
    categories = Counter()
    paired_ids = sorted(set(by_arm['baseline']).union(by_arm['perturbed']))
    for identity in paired_ids:
        baseline, perturbed = by_arm['baseline'].get(identity), by_arm['perturbed'].get(identity)
        if not baseline or not perturbed:
            categories['missing'] += 1
            continue
        if baseline['input_hash'] != perturbed['input_hash'] or arms['baseline']['pin_hash'] != arms['perturbed']['pin_hash']:
            raise ValueError('Pairing changed input or immutable agent/schema pin beyond the approved fault.')
        if perturbed['fault'] != manifest['fault_schedule'][identity] or baseline['fault'] != 'none':
            raise ValueError('An observation is outside the precommitted fault schedule.')
        categories[_pair_category(baseline['outcome'], perturbed['outcome'])] += 1
    categories['missing'] += expected-len(paired_ids)
    replay = []
    for threshold in manifest['fixture_thresholds']:
        for arm_name, rows in by_arm.items():
            successes = [row for row in rows.values() if row['outcome'] == 'goal_pass' and row['events']]
            measured = [row for row in rows.values() if row['events']]
            stops = {row['case_id']: _prefix(row, threshold) for row in measured}
            false_stops = sum(stops[row['case_id']]['would_stop'] and
                stops[row['case_id']]['sequence'] < next(event['sequence'] for event in row['events']
                    if event['event_type'] == 'goal_observed') for row in successes)
            replay.append({'arm': arm_name, 'fixture_threshold': threshold,
                'scope': 'same_trajectory_prefix_counterfactual_replay',
                'planned_denominator': expected, 'observed_trace_denominator': len(measured),
                'missing_trace_count': expected-len(measured),
                'unknown_count': states[arm_name]['unknown'], 'unassessable_count': states[arm_name]['unassessable'],
                'would_stop': sum(row['would_stop'] for row in stops.values()),
                'replay_false_stop': _rate(false_stops, len(successes)),
                'replay_successful_goal_loss_if_suffix_discarded': _rate(false_stops, len(successes)),
                'counterfactual_discarded_observed_events': sum(row['discarded_observed_suffix_events'] for row in stops.values()),
                'saved_business_calls': None, 'remote_cancellation_confirmed': False,
                'assumption': manifest['replay_assumption']})
    report = {'profile': PROFILE, 'report_version': 'owned-paired-experiment-report-v1',
        'manifest_hash': value['manifest_hash'], 'evidence_hash': evidence.binding_hash,
        'manifest': manifest, 'synthetic': True, 'promotion_qualified': False,
        'planned_pairs': expected, 'paired_categories': {name: categories[name] for name in
            ('both_goal_pass', 'both_failed', 'goal_regression', 'goal_improvement', 'unknown', 'unassessable', 'oracle_error', 'missing')},
        'paired_observed_count': expected-categories['missing'],
        'paired_fully_assessable_count': expected-sum(categories[name] for name in ('missing', 'unknown', 'unassessable', 'oracle_error')),
        'arm_outcomes': states, 'missing_episodes': missing,
        'surface_cells': surface,
        'within_arm_original_variant_mr': {name: {'planned_pairs': 4,
            'categories': dict(Counter(_pair_category(rows.get(f'{base}-{trial}-0', {}).get('outcome'),
                rows.get(f'{base}-{trial}-1', {}).get('outcome'))
                for base in manifest['inputs'] for trial in range(manifest['k']))),
            'both_failed_is_goal_success': False} for name, rows in by_arm.items()},
        'all_k_goal_success': {name: {'numerator': sum(all(rows.get(f'{base}-{trial}-{variant}', {}).get('outcome') == 'goal_pass'
            for trial in range(manifest['k'])) for base in manifest['inputs'] for variant in range(2)),
            'denominator': len(manifest['inputs'])*2, 'k': manifest['k'],
            'unknown_missing_retained_as_not_established': True} for name, rows in by_arm.items()},
        'established_goal_count_delta_over_planned': {
            **_rate(states['perturbed']['goal_pass']-states['baseline']['goal_pass'], expected),
            'interpretation': 'difference_in_established_goal_counts_unknown_and_partial_are_not_assumed_failures'},
        'uncertainty': {'method': 'descriptive_fixed_fixture_paired_counts_only',
            'synthetic_task_clusters': 2, 'independence_established': False, 'confidence_interval': None,
            'calibrated_prediction': False, 'reason': 'two synthetic task clusters cannot justify an operating confidence claim'},
        'replay_policies': replay, 'actual_interventions': 0,
        'actual_paired_intervention_false_stop': None, 'actual_paired_intervention_goal_loss': None,
        'actual_paired_intervention_judge_overhead_seconds': None,
        'evaluation_packets': value['packets'], 'business_packets': 0,
        'external_network_attempts': value['external_network_attempts'],
        'operating_qualification': False, 'independent_quality': 'unassessed',
        'controller_enabled': False, 'public_activation': False,
        'source_binding': {name: {'plan_revision': arm['plan_revision'], 'corpus_hash': arm['corpus_hash'],
            'manifest_definition_hash': arm['manifest_definition_hash'], 'pin_hash': arm['pin_hash'],
            'source_revisions': [row['source_revision'] for row in arm['episodes']],
            'second_tick_attempts': arm['second_tick_attempts']} for name, arm in arms.items()},
        'observed_episode_metadata': {name: [{key: row[key] for key in
            ('case_id', 'input_hash', 'fault', 'outcome', 'state', 'events', 'source_revision')}
            for row in arm['episodes']] for name, arm in arms.items()},
        'remaining_requirements': ['reviewed representative real-task ground truth and milestone/frontier definitions',
            'precommitted operating thresholds and independent held-out calibration',
            'approved controlled paired intervention pilot and actual false-stop, goal-loss and judge-overhead measurements',
            'separate authority-bound promotion review and bounded before-next-node controller implementation']}
    report['analyzer_elapsed_seconds'] = time.perf_counter()-started
    report['elapsed_scope'] = 'local_artifact_analysis_only_not_live_judge_or_intervention_overhead'
    report['report_binding_hash'] = _hash(report)
    return report


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 1:
        raise SystemExit('This owned offline fixture accepts no arguments.')
    print(json.dumps(analyze_evidence(produce_owned_fixture()), sort_keys=True, indent=2))
