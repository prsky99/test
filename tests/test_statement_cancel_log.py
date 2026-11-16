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


def test_other_statement_errors_carry_their_sqlstate_and_are_logged_once_a_minute(caplog, monkeypatch):
    """PM 11-16 source review 4.5 (was: other errors stay quiet): every failure keeps its SQLSTATE on the error and
    one line per (SQLSTATE, statement) a minute names it, with how many were folded in; never the parameters."""
    caplog.set_level(logging.WARNING, logger=aps.__name__)
    monkeypatch.setattr(aps, '_FAILED_SEEN', {})
    clock = [100.0]
    monkeypatch.setattr(aps.time, 'monotonic', lambda: clock[0])
    for _ in range(3):
        with pytest.raises(aps.ApplicationStoreError) as raised:
            native(Other('missing table'), 'SELECT secret FROM t WHERE id = %s')
        assert raised.value.code == 'statement_failed' and raised.value.sqlstate == '42P01'
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 1 and 'sqlstate=42P01' in lines[0] and 'folded=0' in lines[0]
    clock[0] += 61
    with pytest.raises(aps.ApplicationStoreError):
        native(Other('missing table'), 'SELECT secret FROM t WHERE id = %s')
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 2 and 'folded=2' in lines[1]
    with pytest.raises(aps.ApplicationStoreError) as raised:
        native(Cancelled('timeout'), 'SELECT 1')
    assert raised.value.sqlstate == '57014'
    assert not any('Statement failed' in r.getMessage() and '57014' in r.getMessage() for r in caplog.records)
