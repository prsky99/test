"""Finite automatic circuit consumption inside the existing evaluation worker.

Separate owner activation permits bounded probe binding, never a new budget or
business call. All activations are process-local and lost on restart.
"""
import threading

from .reliability_circuit import NOTICE as CIRCUIT_NOTICE
from .reliability_evaluation import bounded_int, finite
from .shadow_ledger import clock, exact
from .workspace_access import WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid, _rows

PROFILE = 'approved-circuit-automation-v1'
NOTICE = 'bounded-automatic-circuit-probes-v1'


class CircuitAutomation:
    def __init__(self, circuit, *, enabled=False):
        if type(enabled) is not bool:
            raise WorkspaceInvalid()
        self.circuit, self.access, self.evaluation, self.enabled = circuit, circuit.access, circuit.evaluation, enabled
        self._lock, self._work = threading.RLock(), {}

    def activate(self, ws, body, actor):
        exact(body, ('plan_revision', 'max_probes', 'expires', 'authorized', 'notice'))
        bounded_int(body['plan_revision'], 1, 2**31-1); bounded_int(body['max_probes'], 1, 10)
        if (not self.enabled or not self.circuit.enabled or body['authorized'] is not True or body['notice'] != NOTICE
                or not finite(body['expires']) or not clock() < body['expires'] <= clock()+3600):
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            plan, _, control = self.evaluation._current(db, ws, actor)
            if plan['revision'] != body['plan_revision']:
                raise WorkspaceConflict()
            circuits = {}
            for rid in plan['pins']:
                value = self.circuit._read(db, ws, int(rid))
                if value is not None:
                    self.circuit._current(db, ws, int(rid), actor)
                    circuits[int(rid)] = value['generation']
            if not circuits:
                raise WorkspaceConflict()
            self.access._audit(db, actor, ws, 'reliability.circuit.automation.activate', ws, plan['revision'])
            value = {'actor': actor, 'plan_revision': plan['revision'], 'control_revision': control['revision'],
                     'generations': circuits, 'remaining': body['max_probes'], 'expires': body['expires']}
        with self._lock:
            if ws not in self._work and len(self._work) >= 8:
                raise WorkspaceConflict()
            self._work[ws] = value
        return self.status(ws, actor)

    def deactivate(self, ws, body, actor):
        exact(body, ('authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] != NOTICE:
            raise WorkspaceInvalid()
        with self.access._tx(actor, write=True) as (db, _):
            self.circuit.scope(ws, actor, write=True, owner=True)
            self.access._audit(db, actor, ws, 'reliability.circuit.automation.deactivate', ws, 0)
        self.stop(ws)
        return self.status(ws, actor)

    def stop(self, ws):
        with self._lock:
            self._work.pop(ws, None)

    def status(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.circuit.scope(ws, actor)
        with self._lock:
            value = self._work.get(ws)
            active = bool(self.enabled and value and value['actor'] == actor and value['expires'] > clock())
            return {'profile': PROFILE, 'enabled': self.enabled, 'active': active,
                    'remaining_probes': value['remaining'] if active else 0, 'public_activation': False,
                    'business_dispatches': 0, 'restart_reactivation_required': True}

    def sweep(self, ws, actor, jobs):
        with self._lock:
            value = self._work.get(ws)
            if not self.enabled or value is None or value['actor'] != actor:
                return {'consumed': 0, 'bound_probes': 0}
            try:
                if value['expires'] <= clock():
                    raise WorkspaceConflict()
                with self.access._tx(actor) as (db, _):
                    plan, _, control = self.evaluation._current(db, ws, actor)
                    if plan['revision'] != value['plan_revision'] or control['revision'] != value['control_revision']:
                        raise WorkspaceConflict()
                    for rid, generation in value['generations'].items():
                        if self.circuit._current(db, ws, rid, actor)['generation'] != generation:
                            raise WorkspaceConflict()
                consumed, probes = 0, 0
                for rid in value['generations']:
                    with self.access._tx(actor) as (db, _):
                        current = self.circuit._current(db, ws, rid, actor)
                    if current['state'] == 'half_open':
                        result = self.circuit.refresh_probe(ws, rid,
                            {'revision': current['revision'], 'authorized': True, 'notice': CIRCUIT_NOTICE}, actor)
                        if not result.get('waiting'):
                            consumed += 1
                        continue
                    for job in jobs[:32]:
                        if job['resource_id'] != rid:
                            continue
                        with self.access._tx(actor) as (db, _):
                            current = self.circuit._current(db, ws, rid, actor)
                            claimed = self.circuit._claim(db, ws, job['id']) is not None
                        if claimed:
                            continue
                        command = {'revision': current['revision'], 'authorized': True, 'notice': CIRCUIT_NOTICE}
                        if job['state'] in ('completed', 'failed', 'unknown'):
                            # Only the existing trusted response proof may count;
                            # invalid/manual sources are skipped, never asserted.
                            try:
                                self.circuit.ingest(ws, rid, command | {'source_ref': job['id']}, actor)
                                consumed += 1
                            except (WorkspaceConflict, WorkspaceDenied):
                                continue
                        elif (current['state'] == 'open' and job['state'] == 'reserved'
                              and value['remaining'] > 0 and current['opened_at']+current['open_seconds'] <= clock()):
                            self.circuit.bind_probe(ws, rid, command | {'job_id': job['id']}, actor)
                            value['remaining'] -= 1; probes += 1
                            break
                return {'consumed': consumed, 'bound_probes': probes}
            except (WorkspaceConflict, WorkspaceDenied, WorkspaceInvalid):
                self._work.pop(ws, None)
                raise
