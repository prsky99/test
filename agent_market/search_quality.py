"""Bounded quality aggregates shared with Admin through existing snapshot storage.

No queries, prompts, identifiers, arguments, model names or responses are saved.
Snapshots describe the current process generation, not a claimed 24-hour SLA.
"""
from collections import Counter, deque
from contextvars import ContextVar
from functools import wraps
import math
import logging
import threading
import time

from .concierge.retrieval_metrics import capture

SURFACES = ('explore', 'recommendation', 'workflow_generation')
ROLES = ('frontend', 'admin', 'execution', 'jobs', 'standalone')
STATUSES = ('matched', 'no_match', 'review_required', 'needs_details', 'error', 'denied')
_active = ContextVar('search_quality_active', default=())
log = logging.getLogger(__name__)


def percentile(values, fraction):
    if not values: return None
    values = sorted(values)
    return round(values[min(len(values)-1, math.ceil(fraction*len(values))-1)], 1)


class Recorder:
    def __init__(self, store):
        self.store, self.started = store, time.time()
        self.lock = threading.RLock()
        self.rows = {name: {'count': 0, 'status': Counter(), 'samples': deque(maxlen=2048),
                            'stages': {}, 'counts': Counter()} for name in SURFACES}
        self.saved_at = 0
        self.save_failures = 0

    def record(self, surface, status, elapsed, measured, repairs=0):
        if surface not in SURFACES or status not in STATUSES: raise ValueError('Invalid quality event.')
        with self.lock:
            row = self.rows[surface]; row['count'] += 1; row['status'][status] += 1
            row['samples'].append(max(0, elapsed))
            for stage, value in measured['stages_ms'].items():
                row['stages'].setdefault(stage, deque(maxlen=2048)).append(value)
            row['counts'].update(measured['counts'])
            row['counts']['local_query_repairs'] += repairs
        self.save()

    def snapshot(self):
        with self.lock:
            return {'profile': 'search-quality-current-generation-v1', 'started_at': self.started,
                    'captured_at': time.time(), 'surfaces': [{
                        'surface': surface, 'requests': row['count'], 'statuses': dict(row['status']),
                        'sample_count': len(row['samples']), 'p50_ms': percentile(row['samples'], .5),
                        'p95_ms': percentile(row['samples'], .95), 'counters': dict(row['counts']),
                        'stages': {name: {'sample_count': len(values), 'p95_ms': percentile(values, .95)}
                                   for name, values in row['stages'].items()}}
                        for surface, row in self.rows.items()]}

    def save(self):
        if getattr(self.store._db, 'in_transaction', False): return
        now = time.monotonic()
        with self.lock:
            if now-self.saved_at < 30: return
            self.saved_at = now
        from .admin_next import SnapshotStore
        role = getattr(self.store, '_service_role', 'standalone')
        role = role if role in ROLES else 'standalone'
        if not SnapshotStore(self.store, every=0).save('search-quality.'+role, self.snapshot()):
            with self.lock: self.save_failures += 1


def recorder(store):
    store = getattr(store, '_quality_owner', store)
    with store._lock:
        value = getattr(store, '_search_quality_recorder', None)
        if value is None:
            value = Recorder(store); store._search_quality_recorder = value
        return value


def observed(surface):
    if surface not in SURFACES: raise ValueError('Invalid quality surface.')
    def decorate(function):
        @wraps(function)
        def call(first, *args, **kwargs):
            if surface in _active.get(): return function(first, *args, **kwargs)
            store = getattr(first, 'store', first)
            token = _active.set(_active.get() + (surface,))
            started = time.perf_counter(); status = 'error'; repairs = 0
            try:
                with capture() as measured:
                    result = function(first, *args, **kwargs)
                if isinstance(result, list): status = 'matched' if result else 'no_match'
                elif isinstance(result, dict):
                    status = result.get('state') or ('matched' if result.get('items') else 'no_match')
                    repairs = result.get('generation_quality', {}).get('local_query_repairs', 0)
                if status not in STATUSES: status = 'matched'
                return result
            except Exception as error:
                if type(error).__name__ in ('WorkspaceDenied', 'ExecutionDenied'): status = 'denied'
                raise
            finally:
                _active.reset(token)
                try:
                    recorder(store).record(surface, status, (time.perf_counter()-started)*1000,
                                           locals().get('measured', {'stages_ms': {}, 'counts': {}}), repairs)
                except Exception:
                    # Observation failure must not change an approved operation.
                    log.debug('Quality observation is unavailable.')
        return call
    return decorate


def dashboard(store):
    from .admin_next import SnapshotStore
    snapshots = SnapshotStore(store); result = []
    local = getattr(store, '_search_quality_recorder', None)
    local_role = getattr(store, '_service_role', 'standalone')
    for role in ROLES:
        found = snapshots.load('search-quality.'+role)
        value = local.snapshot() if local and local_role == role else found[1] if found else None
        if not isinstance(value, dict) or value.get('profile') != 'search-quality-current-generation-v1': continue
        for row in value.get('surfaces', [])[:3]:
            if row.get('surface') not in SURFACES: continue
            result.append({'role': role, 'surface': row['surface'], 'requests': row.get('requests', 0),
                           'statuses': {s: row.get('statuses', {}).get(s, 0) for s in STATUSES},
                           'p50_ms': row.get('p50_ms'), 'p95_ms': row.get('p95_ms'),
                           'sample_count': row.get('sample_count', 0), 'counters': row.get('counters', {}),
                           'captured_at': value.get('captured_at'), 'started_at': value.get('started_at')})
    return {'available': bool(result), 'rows': result, 'captured_at': time.time(),
            'window': 'current_process_generation', 'latency_sample_limit': 2048,
            'production_slo_certified': False}
