"""A statement timeout names its statement in the log (운영·SRE, PM 11-15 22:2x: 21:50 A2A 12.45 s server time,
a frontend connection hit the 5 s timeout and no log line said which statement)."""
import logging

import pytest

from agent_market import application_store_postgres as aps


class Cancelled(Exception):
    sqlstate = '57014'


class Other(Exception):
    sqlstate = '42P01'


class Cursor:
    def __init__(self, error):
        self.error = error

    def execute(self, sql, params):
        raise self.error

    def close(self):
        pass


class Connection:
    def __init__(self, error):
        self.error = error

    def cursor(self, row_factory=None):
        return Cursor(self.error)


def native(error, sql):
    store = aps.PostgresApplicationStore.__new__(aps.PostgresApplicationStore)
    store._connection = Connection(error)
    return aps.PostgresApplicationStore._native(store, sql, (1,))


def test_a_cancelled_statement_is_named_without_its_parameters(caplog):
    caplog.set_level(logging.WARNING, logger=aps.__name__)
    with pytest.raises(aps.ApplicationStoreError) as raised:
        native(Cancelled('canceling statement due to statement timeout'),
               'SELECT * FROM resources\n   WHERE id IN (%s) AND active IN (%s)')
    assert raised.value.code == 'statement_failed'
    [line] = [r.getMessage() for r in caplog.records]
    assert 'Statement cancelled by statement timeout' in line
    assert 'SELECT * FROM resources WHERE id IN (%s) AND active IN (%s)' in line


def test_other_statement_errors_stay_quiet(caplog):
    caplog.set_level(logging.WARNING, logger=aps.__name__)
    with pytest.raises(aps.ApplicationStoreError):
        native(Other('missing table'), 'SELECT 1')
    assert not caplog.records
