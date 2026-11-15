"""A due pick or x402 evaluation read that passes the statement timeout under load skips the round with a warning
instead of a traceback (11-15 jobs: health loop error kinds=x402/mcp and x402 evaluation error, statement_failed)."""
import logging
import threading

import pytest

from agent_market.application_store_postgres import ApplicationStoreError
from agent_market.collector.health import HealthChecker


class Store:
    def __init__(self, error):
        self.error, self.postponed = error, []

    def due_for_check(self, now, limit, per_host=None, kind=None):
        raise self.error

    def postpone(self, ids, until):
        self.postponed.append(ids)


def checker(store):
    c = HealthChecker.__new__(HealthChecker)
    c.store, c.per_host_cap = store, 5
    c._claim_lock, c._busy_hosts = threading.Lock(), set()
    return c


def test_a_timed_out_due_pick_skips_the_round_with_a_warning(caplog):
    c = checker(Store(ApplicationStoreError("statement_failed")))
    with caplog.at_level(logging.WARNING, logger="agent_market.collector.health"):
        result = c.run_due(10, kind="x402")
    assert result == {"checked": 0, "accepted": 0, "stale": 0, "skipped": "statement_timeout"}
    assert c.store.postponed == [] and c._busy_hosts == set()
    assert "due pick timed out under load (kind=x402)" in caplog.text


def test_other_store_errors_in_the_due_pick_still_raise():
    c = checker(Store(ApplicationStoreError("unsupported_application_sql")))
    with pytest.raises(ApplicationStoreError):
        c.run_due(10, kind="mcp")
