"""A statement timeout on the pending-token pick skips the round with a warning and waits before the next try
(2026-11-10 06:13 jobs: erc8004 resolve failed, statement_failed under load)."""

import pytest

from agent_market.application_store_postgres import ApplicationStoreError
from agent_market.collector import registries
from agent_market.collector.registries import Erc8004Crawler


class Store:
    def __init__(self, error=None):
        self.error, self.queries = error, 0

    def query(self, sql, params=()):
        self.queries += 1
        if self.error:
            raise self.error
        return []


def _crawler(store):
    crawler = object.__new__(Erc8004Crawler)
    crawler.store, crawler.per_host = store, 2
    crawler.defer_dead_hosts = lambda: 0
    return crawler


def test_a_timed_out_pick_is_skipped_and_waits_before_trying_again(monkeypatch, caplog):
    now = [1000.0]
    monkeypatch.setattr(registries.time, 'time', lambda: now[0])
    store = Store(ApplicationStoreError('statement_failed'))
    crawler = _crawler(store)
    with caplog.at_level('WARNING'):
        assert crawler.resolve_pending() == {'resolved': 0, 'skipped': 'statement_timeout'}
    assert 'pending pick timed out' in caplog.text
    now[0] += registries.RESOLVE_TIMEOUT_BACKOFF - 1
    assert crawler.resolve_pending() == {'resolved': 0, 'skipped': 'statement_timeout_backoff'}
    assert store.queries == 1
    store.error = None
    now[0] += 2
    assert crawler.resolve_pending() == {'resolved': 0}
    assert store.queries == 2


def test_other_store_errors_still_reach_the_caller():
    crawler = _crawler(Store(ApplicationStoreError('connection_unusable')))
    with pytest.raises(ApplicationStoreError):
        crawler.resolve_pending()
