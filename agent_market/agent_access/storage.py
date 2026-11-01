"""Explicit additive migration and source-owned adoption SQL."""
import hashlib
import json
import secrets
import time
from contextlib import contextmanager

VERSION = 'agent-adoption-v1'
SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS adoption_preparations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,
       resource_id INTEGER NOT NULL,version_id TEXT NOT NULL,tool TEXT NOT NULL,contract_id TEXT NOT NULL,
       input_hash TEXT NOT NULL,sealed TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS adoption_grants(id TEXT PRIMARY KEY,owner TEXT NOT NULL,preparation_id TEXT NOT NULL,
       customer_id TEXT NOT NULL,session_ref TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,
       revoked INTEGER NOT NULL DEFAULT 0,used INTEGER NOT NULL DEFAULT 0,proof TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS adoption_operations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,
       preparation_id TEXT NOT NULL,request_key TEXT NOT NULL,grant_id TEXT NOT NULL,status TEXT NOT NULL,
       sealed TEXT,created REAL NOT NULL,updated REAL NOT NULL,dispatched REAL,
       UNIQUE(owner,request_key),UNIQUE(preparation_id))''',
    '''CREATE TABLE IF NOT EXISTS adoption_changes(id TEXT PRIMARY KEY,resource_id INTEGER NOT NULL,
       event_type TEXT NOT NULL,version_id TEXT,created REAL NOT NULL,status TEXT NOT NULL,
       published_seq INTEGER UNIQUE,payload TEXT)''',
    '''CREATE TABLE IF NOT EXISTS adoption_publications(resource_id INTEGER PRIMARY KEY,signature TEXT NOT NULL,
       expires REAL NOT NULL,version_id TEXT,verified INTEGER NOT NULL,updated REAL NOT NULL,state TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS adoption_dependencies(id TEXT PRIMARY KEY,owner TEXT NOT NULL,
       watch_id TEXT NOT NULL,resource_id INTEGER NOT NULL,created REAL NOT NULL,
       last_seq INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,
       version_id TEXT,contract_id TEXT,event_types TEXT NOT NULL,
       UNIQUE(watch_id,resource_id))''',
    'CREATE INDEX IF NOT EXISTS adoption_changes_pending ON adoption_changes(status,created)',
    'CREATE INDEX IF NOT EXISTS adoption_publications_expiry ON adoption_publications(expires)',
    'CREATE INDEX IF NOT EXISTS adoption_publications_checked ON adoption_publications(updated)',
    'CREATE INDEX IF NOT EXISTS adoption_preparations_expiry ON adoption_preparations(expires)',
    'CREATE INDEX IF NOT EXISTS adoption_preparations_owner ON adoption_preparations(owner,expires)',
)


@contextmanager
def transaction(store):
    with store.tx() as db:
        explicit = hasattr(db, 'in_transaction') and not db.in_transaction
        if explicit: db.execute('BEGIN IMMEDIATE')
        try:
            yield db
            if explicit: db.commit()
        except BaseException:
            if explicit: db.rollback()
            raise


def ready(store):
    value=getattr(store,'_adoption_schema_ready',None)
    if value is None:
        value=store.get_meta(VERSION)=={'version':1}
        store._adoption_schema_ready=value
    return value


def migrate(store):
    """Called only by the explicit operator migration or an owned fixture."""
    with transaction(store) as db:
        for statement in SCHEMA:
            if getattr(store, 'backend', None) == 'postgresql':
                store._execute(statement.replace(' REAL ', ' DOUBLE PRECISION ').replace(' INTEGER', ' BIGINT'))
            else: db.execute(statement)
        db.execute('INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (VERSION, json.dumps({'version': 1})))
    store._adoption_schema_ready=True
    return {'version': VERSION, 'tables': 6}


def enqueue(store, db, rid, event_type, version=None, evidence=None,observation=None):
    """Same-transaction intent, never a request-time provider probe."""
    if not ready(store): return
    if event_type=='catalog_changed'and not db.execute('SELECT 1 FROM adoption_publications WHERE resource_id=?',(rid,)).fetchone():return
    ident = hashlib.sha256(json.dumps([rid,event_type,version,evidence],sort_keys=True).encode()).hexdigest()
    db.execute('INSERT OR IGNORE INTO adoption_changes(id,resource_id,event_type,version_id,created,status,payload) VALUES (?,?,?,?,?,?,?)',
               (ident,rid,event_type,version,time.time(),'pending',json.dumps(observation)if observation else None))


def identity(prefix):
    return prefix+'_'+secrets.token_hex(16)
