"""Open existing host state without initializing unrelated application tables."""
from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3

from ..application_runtime import open_runtime_storage
from .config import EdgeError


class SQLiteState:
    backend = 'sqlite'

    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def tx(self):
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield self.connection
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise


@contextmanager
def open_operator_store(path):
    if os.environ.get('APPLICATION_STORE_BACKEND', 'sqlite') != 'sqlite':
        storage = open_runtime_storage(path)
        try:
            yield storage.store
        finally:
            storage.close()
        return
    try:
        target = Path(path).resolve(strict=True)
        if not target.is_file():
            raise EdgeError('CONFIGURATION_INVALID')
        connection = sqlite3.connect(target.as_uri() + '?mode=rw', uri=True, timeout=5, isolation_level=None)
    except (OSError, sqlite3.Error):
        raise EdgeError('CONFIGURATION_INVALID') from None
    try:
        yield SQLiteState(connection)
    finally:
        connection.close()
