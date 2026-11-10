import logging

from agent_market.application_store_postgres import ApplicationStoreError
from agent_market.service_host import BackgroundLoop


class Refresher:
    def __init__(self, error):
        self.error, self.rest_until = error, 0

    def clock(self):
        return 1000

    def run(self):
        raise self.error


def test_a_statement_timeout_is_a_warning_and_waits_five_minutes(caplog):
    refresher = Refresher(ApplicationStoreError('statement_failed'))
    with caplog.at_level(logging.WARNING, logger='agent_market.service_host'):
        BackgroundLoop.refresh_capability_text(object.__new__(BackgroundLoop), refresher)
    assert refresher.rest_until == 1300
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert caplog.records[0].exc_info is None


def test_other_failures_still_log_an_error_with_traceback(caplog):
    refresher = Refresher(RuntimeError('boom'))
    with caplog.at_level(logging.WARNING, logger='agent_market.service_host'):
        BackgroundLoop.refresh_capability_text(object.__new__(BackgroundLoop), refresher)
    assert refresher.rest_until == 1300
    assert [r.levelno for r in caplog.records] == [logging.ERROR]
    assert caplog.records[0].exc_info is not None
