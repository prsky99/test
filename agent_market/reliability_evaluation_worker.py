"""Explicit, default-off narrow MCP evaluation adapter and finite worker.

These are evaluation calls against an owner-approved synthetic/licensed corpus.
Contract validity is a technical observation, never independent business quality.
Worker activation is process-local and cannot survive a restart or restore.
"""
from copy import deepcopy
import threading

from .capability_contracts import validate
from .concierge.execution_policy import ExecutionDenied
from .concierge.http_security import outbound_operation
from .concierge.proxy import McpProxy
from .reliability_evaluation import NOTICE, clock
from .shadow_ledger import exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _canonical, _hash
from .workflow_persistence import dispatch_scope

CONTRACTS = ('docs.search.v1', 'news.search.v1')
PROFILE = 'bounded-mcp-read-evaluator-v1'
RESPONSE_PROOF = 'approved-mcp-response-observation-v1'


class McpReadEvaluator:
    """Use the existing schema-pinned gateway without retries or spending."""
    def __init__(self, evaluation, *, enabled=False, max_seconds=12):
        if type(enabled) is not bool or type(max_seconds) is not int or not 1 <= max_seconds <= 12:
            raise WorkspaceInvalid()
        proxy = evaluation.runtime.proxy
        if enabled and (not isinstance(proxy, McpProxy) or proxy.store is not evaluation.store):
            raise WorkspaceInvalid()
        self.evaluation, self.proxy = evaluation, evaluation.runtime.proxy
        self.enabled, self.max_seconds = enabled, max_seconds

    @property
    def configured(self):
        return (self.enabled is True and isinstance(self.proxy, McpProxy)
                and self.proxy.store is self.evaluation.store and self.evaluation.runtime.proxy is self.proxy)

    def authorizer(self, ws, plan, job, actor):
        # The caller-owned transaction has already checked the named owner,
        # purpose approval, current corpus/control, pin and restore tombstones.
        return (self.configured and plan['workspace_id'] == ws == job['workspace_id']
                and plan['actor_user_id'] == actor.user_id
                and plan['session_ref'] == actor.session_ref
                and job['resource_id'] in tuple(map(int, plan['pins']))
                and job['plan_revision'] == plan['revision']
                and plan['expires'] > clock() and job['expires'] > clock())

    def __call__(self, envelope):
        # An envelope alone is insufficient; the scheduling engine supplies the
        # current-authority closure only after committing its one-shot boundary.
        raise WorkspaceDenied()

    def dispatch(self, envelope, *, before_dispatch):
        if (not self.configured or not callable(before_dispatch) or type(envelope) is not dict
                or set(envelope) != {'job_id', 'purpose', 'resource_id', 'contract_id', 'corpus_hash', 'case', 'pin', 'deadline'}
                or envelope['purpose'] != 'approved_read_evaluation' or envelope['contract_id'] not in CONTRACTS):
            raise WorkspaceDenied()
        snapshot = deepcopy(envelope)
        validate(snapshot['contract_id'], snapshot['case']['input'], now=clock())
        seconds = min(self.max_seconds, snapshot['deadline'] - clock())
        if seconds <= 0:
            raise WorkspaceConflict()
        sent = False

        def guard():
            nonlocal sent
            try:
                if sent or not self.configured or snapshot != envelope:
                    raise WorkspaceConflict()
                before_dispatch()
                sent = True
            except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
                raise ExecutionDenied('Read evaluation authority is no longer current.', error_code='POLICY_DENIED') from None

        before_dispatch()
        with outbound_operation(seconds), dispatch_scope(guard):
            result = self.proxy.execute(snapshot['resource_id'], snapshot['pin']['approval']['tool'],
                                        snapshot['case']['input'], public=True)
        observed = clock()
        outcome = 'failed'
        output = None
        if not sent:
            outcome = 'failed'
        elif type(result) is not dict or result.get('error_code') in ('UPSTREAM_TIMEOUT', 'UPSTREAM_NETWORK', 'UPSTREAM_PROTOCOL'):
            outcome = 'unknown'
        elif result.get('ok') is True:
            raw = result.get('result')
            output = raw.get('structuredContent', raw) if type(raw) is dict else raw
            try:
                if len(_canonical(output).encode('ascii')) > 65536:
                    raise ValueError()
                validate(snapshot['contract_id'], snapshot['case']['input'], output, now=observed)
                before_dispatch()
            except (ValueError, TypeError, WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
                outcome = 'failed'
            else:
                outcome = 'completed'
        # The scheduler stores only outcome/time/reference, not prompts, output
        # or a synthetic assertion of independent evaluator qualification.
        reference = 'reo_' + _hash([PROFILE, snapshot['job_id'], outcome, observed]).split(':')[-1][:32]
        result = {'outcome': outcome, 'observed_at': observed, 'evidence_ref': reference,
                  'response_proof': {'profile': RESPONSE_PROOF, 'job_id': snapshot['job_id'],
                      'purpose': snapshot['purpose'], 'resource_id': snapshot['resource_id'],
                      'contract_id': snapshot['contract_id'], 'corpus_hash': snapshot['corpus_hash'],
                      'case_hash': _hash(snapshot['case']), 'pin_hash': _hash(snapshot['pin']),
                      'envelope_hash': _hash(snapshot), 'outcome': outcome, 'observed_at': observed,
                      'dispatch_guard_passed': sent, 'response_validated': outcome == 'completed'}}
        research = getattr(self.evaluation, 'research', None)
        if research is not None:
            observation = research.observe(snapshot, output, outcome)
            if observation is not None:
                result['research_observation'] = observation
        return result


class EvaluationWorker:
    """One bounded polling thread; only explicitly activated current owners run."""
    def __init__(self, evaluation, *, enabled=False, poll_seconds=5, max_jobs_per_tick=2):
        if (type(enabled) is not bool or type(poll_seconds) is not int or not 1 <= poll_seconds <= 60
                or type(max_jobs_per_tick) is not int or not 1 <= max_jobs_per_tick <= 8):
            raise WorkspaceInvalid()
        self.evaluation, self.enabled = evaluation, enabled
        self.poll_seconds, self.max_jobs_per_tick = poll_seconds, max_jobs_per_tick
        self._stop = threading.Event()
        self._lock, self._tick_lock = threading.Lock(), threading.Lock()
        self._activations, self._thread = {}, None
        self._closed = False
        self.circuit_automation = None

    @property
    def running(self):
        return bool(self.enabled and not self._closed and self._thread and self._thread.is_alive())

    def _adapter(self):
        adapter = self.evaluation.read_evaluator
        if (type(adapter) is not McpReadEvaluator or adapter.evaluation is not self.evaluation
                or not adapter.configured or self.evaluation.evaluator_authorizer != adapter.authorizer):
            raise WorkspaceConflict()
        return adapter

    def activate(self, ws, actor, plan_revision):
        if self.enabled is not True or self._closed or self._stop.is_set() or type(plan_revision) is not int:
            raise WorkspaceConflict()
        self._adapter()
        with self.evaluation.access._tx(actor, write=True) as (db, _):
            plan, _, control = self.evaluation._current(db, ws, actor)
            if plan['revision'] != plan_revision:
                raise WorkspaceConflict()
            activation = (actor, plan_revision, control['revision'], threading.Event())
            self.evaluation.access._audit(db, actor, ws, 'reliability.evaluation.worker.activate', ws, plan_revision)
        with self._lock:
            if self._closed or ws not in self._activations and len(self._activations) >= 8:
                raise WorkspaceConflict()
            if ws in self._activations:
                self._activations[ws][3].set()
            self._activations[ws] = activation

    def deactivate(self, ws):
        with self._lock:
            item = self._activations.pop(ws, None)
            if item:
                item[3].set()
        if self.circuit_automation is not None:
            self.circuit_automation.stop(ws)

    @staticmethod
    def _body(body):
        exact(body, ('revision', 'authorized', 'notice'))
        if (type(body['revision']) is not int or not 0 <= body['revision'] < 2**31
                or body['authorized'] is not True or body['notice'] != NOTICE):
            raise WorkspaceInvalid()

    def activate_for(self, ws, body, actor):
        self._body(body)
        self.activate(ws, actor, body['revision'])
        try:
            if not self.start():
                raise WorkspaceConflict()
        except Exception:
            self.deactivate(ws)
            raise
        return self.status(ws, actor)

    def deactivate_for(self, ws, body, actor):
        self._body(body)
        with self.evaluation.access._tx(actor, write=True) as (db, _):
            self.evaluation.scope(ws, actor, write=True, owner=True)
            plan = self.evaluation._plan(db, ws)
            if body['revision'] != (plan['revision'] if plan else 0):
                raise WorkspaceConflict()
            self.evaluation.access._audit(db, actor, ws, 'reliability.evaluation.worker.deactivate', ws, body['revision'])
        self.deactivate(ws)
        return self.status(ws, actor)

    def status(self, ws, actor):
        with self._lock:
            item = self._activations.get(ws)
            active = item is not None and not item[3].is_set() and not self._closed
        with self.evaluation.access._tx(actor) as (db, user):
            member, _ = self.evaluation.scope(ws, actor)
            can_write = member['member_role'] == 'owner' and user['role'] != 'operator'
            if active:
                try:
                    plan, _, control = self.evaluation._current(db, ws, item[0])
                    active = (plan['revision'] == item[1] and control['revision'] == item[2]
                              and not self._stop.is_set() and self.evaluation._adapter_configured())
                except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
                    active = False
        return {'profile': PROFILE, 'configured': self.enabled is True,
                'running': self.running, 'active': active,
                'plan_revision': item[1] if active else None, 'can_write': can_write,
                'public_activation': False, 'business_dispatches': 0,
                'quality_status': 'not_independently_assessed_by_worker'}

    def tick(self):
        if self.enabled is not True or self._closed or self._stop.is_set():
            return {'attempted_jobs': 0, 'active_workspaces': 0, 'enabled': False}
        self._adapter()
        if not self._tick_lock.acquire(blocking=False):
            raise WorkspaceConflict()
        attempted = 0
        try:
            with self._lock:
                activations = list(self._activations.items())
            for ws, (actor, revision, control_revision, stopped) in activations:
                if self._stop.is_set() or attempted >= self.max_jobs_per_tick:
                    break
                try:
                    with self.evaluation.access._tx(actor, write=True) as (db, _):
                        plan, _, control = self.evaluation._current(db, ws, actor)
                        if plan['revision'] != revision or control['revision'] != control_revision or stopped.is_set():
                            raise WorkspaceConflict()
                    jobs = self.evaluation.reserve(ws, {'revision': revision, 'authorized': True, 'notice': NOTICE}, actor)['jobs']
                    if self.circuit_automation is not None:
                        self.circuit_automation.sweep(ws, actor, jobs)
                    for job in jobs:
                        if self._stop.is_set() or stopped.is_set() or attempted >= self.max_jobs_per_tick:
                            break
                        if job['state'] not in ('reserved', 'prepared') or job['not_before'] > clock():
                            continue
                        body = {'authorized': True, 'notice': NOTICE}
                        if job['state'] == 'reserved':
                            self.evaluation.prepare(ws, job['id'], body, actor)
                        attempted += 1
                        self.evaluation.dispatch(ws, job['id'], body, actor,
                            _stopped=lambda: self._stop.is_set() or stopped.is_set())
                    if self.circuit_automation is not None:
                        self.circuit_automation.sweep(ws, actor,
                            self.evaluation.status(ws, actor)['jobs'])
                except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
                    self.deactivate(ws)
            with self._lock:
                count = len(self._activations)
            return {'attempted_jobs': attempted, 'active_workspaces': count, 'enabled': True}
        finally:
            self._tick_lock.release()

    def start(self):
        if self.enabled is not True or self._closed or self._stop.is_set():
            return False
        self._adapter()
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._thread = threading.Thread(target=self._run, name='bounded-read-evaluation', daemon=True)
            self._thread.start()
        return True

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid):
                self._stop.set()
            if self._stop.wait(self.poll_seconds):
                break

    def close(self):
        self._closed = True
        self._stop.set()
        with self._lock:
            for item in self._activations.values():
                item[3].set()
            self._activations.clear()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1)
        return not bool(thread and thread.is_alive())
