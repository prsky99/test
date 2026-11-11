"""Opt-in per-request measurements without task, identity or result retention."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
import threading
from functools import wraps

_current = ContextVar('retrieval_quality_measurements', default=None)
_lock = threading.Lock()
_STAGES = frozenset(('lexical', 'embedding', 'ann', 'expansion', 'projection', 'exact', 'total', 'rerank',
                     'contracts', 'resource_read', 'admission', 'cards', 'search_document', 'exposure',
                     'public_agent', 'states', 'describe', 'opensearch', 'documents', 'relax', 'near',
                     'shared_cache', 'revalidate', 'pool_wait', 'lock_wait', 'thread_wait', 'cpu',
                     # Recommendation legs that had no stage (11-12 PM: find_agents 4.7 s, about half unnamed)
                     'semantic', 'selection_rows', 'report_evidence', 'choice_rank', 'admission_loop', 'registry'))


def timed(name):
    """Measure inclusive stage time only during an opted-in search capture."""
    if name not in _STAGES:
        raise ValueError('Unknown retrieval stage.')
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            if _current.get() is None:
                return function(*args, **kwargs)
            with stage(name):
                return function(*args, **kwargs)
        return call
    return decorate


@contextmanager
def capture():
    """A nested capture (search_quality.observed inside a timed request) also adds its stages,
    counts and marks to the enclosing one, so Server-Timing sees inside Explore (11-11)."""
    outer = _current.get()
    values = {'stages_ms': {}, 'counts': {}}
    token = _current.set(values)
    try:
        yield values
    finally:
        _current.reset(token)
        if outer is not None:
            with _lock:
                for group in ('stages_ms', 'counts'):
                    for name, value in values[group].items():
                        outer[group][name] = outer[group].get(name, 0) + value
                if values.get('marks'):
                    outer.setdefault('marks', []).extend(values['marks'])


@contextmanager
def stage(name):
    if name not in _STAGES:
        raise ValueError('Unknown retrieval stage.')
    value = _current.get()
    started = perf_counter() if value is not None else 0
    try:
        yield
    finally:
        if value is not None:
            with _lock:
                value['stages_ms'][name] = value['stages_ms'].get(name, 0) + (perf_counter() - started) * 1000


def add(name, milliseconds):
    """Add measured milliseconds to a stage of the current request (waits measured where they happen)."""
    if name not in _STAGES:
        raise ValueError('Unknown retrieval stage.')
    value = _current.get()
    if value is not None:
        with _lock:
            value['stages_ms'][name] = value['stages_ms'].get(name, 0) + milliseconds


def entered():
    """Called where a request's work starts in its worker thread: the time it waited for that thread."""
    import time
    value = _current.get()
    if value is not None and 'started' in value and 'entered' not in value:
        value['entered'] = perf_counter()
        value['cpu_start'] = time.thread_time()
        add('thread_wait', (value['entered'] - value['started']) * 1000)


def left():
    """CPU time this worker thread used since entered(); wall time minus this is waiting (I/O, locks, GIL)."""
    import time
    value = _current.get()
    if value is not None and 'cpu_start' in value and 'cpu_done' not in value:
        value['cpu_done'] = True
        add('cpu', (time.thread_time() - value['cpu_start']) * 1000)


class TimedLock:
    """A lock whose waits count as lock_wait for the current request (11-11: 12 s of Chat went unmeasured)."""

    def __init__(self, lock):
        self._lock = lock

    def acquire(self, *args, **kwargs):
        if not args and not kwargs and self._lock.acquire(blocking=False):
            return True
        started = perf_counter()
        got = self._lock.acquire(*args, **kwargs) if args or kwargs else self._lock.acquire()
        add('lock_wait', (perf_counter() - started) * 1000)
        return got

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def __getattr__(self, name):
        return getattr(self._lock, name)


def mark(name):
    """Record that a named step started; RequestTiming turns the marks into step durations."""
    current = _current.get()
    if current is not None:
        with _lock:
            current.setdefault('marks', []).append((str(name)[:24], perf_counter()))


def count(name, value):
    if name not in ('lexical_candidates', 'dense_candidates', 'returned_candidates', 'exact_shortcuts',
                    'projection_cache_hits', 'reranked_candidates', 'rerank_order_changed', 'rerank_budget_exhausted',
                    'constraint_unknown', 'constraint_mismatch', 'task_tool_verified', 'task_tool_unverified',
                    'projection_candidates_omitted', 'expansion_candidates',
                    'compact_ranking_rows', 'rerank_skipped_compact'):
        raise ValueError('Unknown retrieval count.')
    current = _current.get()
    if current is not None:
        with _lock:
            current['counts'][name] = current['counts'].get(name, 0) + int(value)
