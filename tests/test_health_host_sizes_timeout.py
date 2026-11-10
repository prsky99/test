"""A timed-out host size count keeps the previous counts instead of dropping the health batch
(2026-11-11 00:58 jobs: health loop error, ApplicationStoreError statement_failed in host_sizes)."""
import time
from collections import Counter

import pytest

from agent_market.application_store_postgres import ApplicationStoreError
from agent_market.collector.health import HealthChecker


class Store:
    def __init__(self, error=None, rows=()):
        self.error, self.rows, self.calls = error, list(rows), 0

    def health_host_sizes(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows


def checker(store, sizes=None, at=0.0):
    c = HealthChecker.__new__(HealthChecker)
    c.store, c._host_sizes, c._host_sizes_at = store, Counter(sizes or {}), at
    return c


def test_timeout_keeps_previous_counts_and_retries_in_a_minute():
    c = checker(Store(ApplicationStoreError("statement_failed")), {"a.example": 7})
    assert c.host_sizes() == Counter({"a.example": 7})
    assert 530 <= time.time() - c._host_sizes_at <= 550
    c.store.error, c.store.rows = None, [{"host": "a.example", "n": 9}]
    c._host_sizes_at -= 61
    assert c.host_sizes() == Counter({"a.example": 9})


def test_timeout_with_no_previous_counts_returns_empty_default():
    c = checker(Store(ApplicationStoreError("statement_failed")))
    assert c.host_sizes().get("x.example", 1) == 1


def test_other_store_errors_still_raise():
    c = checker(Store(ApplicationStoreError("unsupported_application_sql")))
    with pytest.raises(ApplicationStoreError):
        c.host_sizes()
