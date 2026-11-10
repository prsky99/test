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
                     'public_agent', 'states', 'describe'))


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
    values = {'stages_ms': {}, 'counts': {}}
    token = _current.set(values)
    try:
        yield values
    finally:
        _current.reset(token)


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
