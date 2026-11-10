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


def test_pending_pick_takes_per_host_rows_by_index_and_reuses_the_host_list(tmp_path):
    # 11-11: one host held 906k pending tokens; ranking them all per call read 13.6k blocks (21% of disk reads).
    import sqlite3
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE erc8004_tokens(chain INT, agent_id INT, host TEXT, uri TEXT, status TEXT, next_at REAL)')
    rows = [(1, i, 'big.example', 'https://big.example/%d' % i, 'pending', float(i)) for i in range(50)]
    rows += [(1, 100, 'small.example', 'https://small.example/a', 'error', 5.0),
             (1, 101, 'small.example', 'https://small.example/b', 'pending', None),
             (1, 102, 'later.example', 'https://later.example/a', 'pending', 9999.0),
             (1, 103, 'done.example', 'https://done.example/a', 'resolved', 1.0)]
    db.executemany('INSERT INTO erc8004_tokens VALUES (?,?,?,?,?,?)', rows)

    class Sqlite:
        def __init__(self): self.sql = []
        def query(self, sql, params=()):
            self.sql.append(sql)
            return db.execute(sql, params).fetchall()
    store = Sqlite()
    crawler = _crawler(store)
    picked = crawler._pending_rows(100.0, 200)
    assert [(r['host'], r['agent_id']) for r in picked] == [
        ('big.example', 0), ('big.example', 1), ('small.example', 100), ('small.example', 101)]
    assert crawler._pending_rows(100.0, 3) == picked[:3]
    hosts_queries = [s for s in store.sql if 'GROUP BY host' in s]
    assert len(hosts_queries) == 1   # reused within PENDING_HOSTS_TTL
    crawler._pending_rows(100.0 + registries.PENDING_HOSTS_TTL, 1)
    assert len([s for s in store.sql if 'GROUP BY host' in s]) == 2
    assert not any('ROW_NUMBER' in s for s in store.sql)
