"""A statement timeout in a housekeeping or due pick skips the round with a warning and waits
(2026-11-10 10:59 rag index cleanup, 13:28 a2a due pick: ApplicationStoreError statement_failed)."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from agent_market import postgres_ann
from agent_market.application_store_postgres import ApplicationStoreError
from agent_market.collector import a2a


class Store:
    def __init__(self, error):
        self.error, self.calls = error, 0

    @contextmanager
    def tx(self, readonly=False):
        yield self

    def _execute(self, sql, params=()):
        self.calls += 1
        raise self.error

    def due_for_capability(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return []


def test_a_timed_out_cleanup_search_is_skipped_and_waits(monkeypatch, caplog):
    now = [100.0]
    monkeypatch.setattr('time.monotonic', lambda: now[0])
    monkeypatch.setattr(postgres_ann, '_cleanup_backoff_until', 0.0)
    store = Store(ApplicationStoreError('statement_failed'))
    with caplog.at_level('WARNING'):
        assert postgres_ann.cleanup(store) == 0
    assert 'cleanup search timed out' in caplog.text
    assert postgres_ann.cleanup(store) == 0 and store.calls == 1  # waiting
    now[0] += postgres_ann.CLEANUP_TIMEOUT_BACKOFF + 1
    postgres_ann.cleanup(store)
    assert store.calls == 2
    with pytest.raises(ApplicationStoreError):
        monkeypatch.setattr(postgres_ann, '_cleanup_backoff_until', 0.0)
        postgres_ann.cleanup(Store(ApplicationStoreError('connection_unusable')))


def test_a_timed_out_a2a_due_pick_is_skipped_and_waits(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(a2a.time, 'monotonic', lambda: now[0])
    store = Store(ApplicationStoreError('statement_failed'))
    prober = SimpleNamespace(store=store, max_age=3600)
    run_due = a2a.A2AProber.run_due if hasattr(a2a, 'A2AProber') else next(
        getattr(v, 'run_due') for v in vars(a2a).values() if isinstance(v, type) and 'run_due' in vars(v))
    assert run_due(prober)['skipped'] == 'statement_timeout'
    assert run_due(prober)['skipped'] == 'statement_timeout_backoff' and store.calls == 1
    now[0] += a2a.DUE_TIMEOUT_BACKOFF + 1
    store.error = None
    assert run_due(prober) == {'checked': 0, 'accepted': 0, 'stale': 0}
    with pytest.raises(ApplicationStoreError):
        run_due(SimpleNamespace(store=Store(ApplicationStoreError('connection_unusable')), max_age=3600))
