"""Bound interactive storage waits without initializing or replacing a database."""
from contextlib import contextmanager
from pathlib import Path
import secrets
import sqlite3
import threading

from ..gateway.store import Store


@contextmanager
def interactive_store(source, *, readonly=False):
    if readonly and getattr(source,'backend','sqlite')=='postgresql' and getattr(source,'_admin_read_pool',None) is not None:
        with source._admin_read_pool.reader() as connection:
            yield connection._store
        return
    if not readonly and getattr(source,'backend','sqlite')=='postgresql' and getattr(source,'_interactive_pool',None) is not None:
        with source._interactive_pool.lease_store() as scoped:
            yield scoped
        return
    if getattr(source,'backend','sqlite')!='sqlite' or source._path==':memory:':
        yield source
        return
    # The caller selects an existing server-owned file. No request may supply a
    # path, create a database, run migrations or change journaling settings.
    mode='ro' if readonly else 'rw'
    uri=Path(source._path).resolve(strict=True).as_uri()+'?mode='+mode
    db=sqlite3.connect(uri,uri=True,timeout=.35,check_same_thread=False)
    db.row_factory=sqlite3.Row
    scoped=Store.__new__(Store)
    scoped._path=source._path;scoped._db=db;scoped._lock=threading.RLock()
    scoped._observation_context=None;scoped._observation_savepoint=0
    scoped._observation_broken=False;scoped._observation_issuer=secrets.token_hex(16)
    scoped._vector_index=None
    if readonly:db.execute('PRAGMA query_only=ON')
    journal=getattr(source,'_observation_journal',None)
    if journal is not None:scoped._observation_journal=journal
    try:yield scoped
    finally:db.close()
