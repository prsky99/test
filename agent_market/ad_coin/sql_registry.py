"""Registered SQL for AI AD Coin, like the application store's statement list.

Every statement AI AD Coin runs, on any adapter, must match a registered shape in
sql_registry.json; anything else is refused before it reaches the database. Shapes
are the SQL text with whitespace collapsed and placeholder lists folded, so an
IN (?, ?, ?) list or a multi-row VALUES list of any length is one shape.

Regenerate the list after changing SQL (it records every statement the AI AD Coin
tests and the rehearsal smoke stage run):

    .venv-tests/bin/python -m scripts.ad_coin_sql_registry --write
"""
import hashlib
import json
import os
import re
import threading
from pathlib import Path

PATH = Path(__file__).with_name('sql_registry.json')
RECORD_ENV = 'AD_COIN_SQL_RECORD'
_SPACE = re.compile(r'\s+')
_GROUP = re.compile(r'\(\s*\?(?:\s*,\s*\?)*\s*\)')
_ROWS = re.compile(r'\(\?\+\)(?:\s*,\s*\(\?\+\))+')
_lock = threading.Lock()
_shapes = None


class UnregisteredSql(RuntimeError):
    """A statement outside the registered list; nothing was sent to the database."""


def shape(sql):
    text = _SPACE.sub(' ', sql.strip())
    text = _GROUP.sub('(?+)', text)
    return _ROWS.sub('(?+)*', text)


def digest(sql_shape):
    return hashlib.sha256(sql_shape.encode()).hexdigest()


def _registered():
    global _shapes
    if _shapes is None:
        with _lock:
            if _shapes is None:
                data = json.loads(PATH.read_text()) if PATH.exists() else {'statements': []}
                _shapes = frozenset(item['sha256'] for item in data['statements'])
    return _shapes


_local = threading.local()


class unchecked:
    """Tests and operator inspection only: run ad-hoc statements on this thread. Product code
    never uses it (a test fails if any module under agent_market does)."""

    def __enter__(self):
        _local.depth = getattr(_local, 'depth', 0) + 1
        return self

    def __exit__(self, *exc):
        _local.depth -= 1
        return False


def check(sql):
    """Refuse an unregistered statement, or record it when a registry rebuild asks for that."""
    if getattr(_local, 'depth', 0):
        return
    text = shape(sql)
    record = os.environ.get(RECORD_ENV)
    if record:
        if _from_product_code():
            with _lock, open(record, 'a', encoding='utf-8') as out:
                out.write(json.dumps(text) + '\n')
        return
    if digest(text) not in _registered():
        raise UnregisteredSql('unregistered_sql: ' + text[:160])


def _from_product_code():
    """Only statements issued by AI AD Coin product code are registered, never a test's own SQL."""
    import sys
    frame = sys._getframe(2)
    here = (os.sep + 'ad_coin' + os.sep + 'db.py', os.sep + 'ad_coin' + os.sep + 'sql_registry.py')
    while frame is not None:
        name = frame.f_code.co_filename
        if not name.endswith(here) and 'contextlib' not in name:
            return (os.sep + 'agent_market' + os.sep) in name
        frame = frame.f_back
    return False


class CheckedConnection:
    """A SQLite connection whose execute() admits registered statements only."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, args=()):
        check(sql)
        return self._connection.execute(sql, args)

    def __getattr__(self, name):
        if name in ('executescript', 'executemany'):
            raise AttributeError(name)      # not used by AI AD Coin, and never unchecked
        return getattr(self._connection, name)
