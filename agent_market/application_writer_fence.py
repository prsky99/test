"""Durable retirement of a SQLite writer before native service activation.

The migration owner calls these functions while holding BEGIN IMMEDIATE. The
source gate is outside application data and is never copied to PostgreSQL.
Existing application writers are stopped by native triggers, including writers
which do not cooperate with the Store transaction helper. Only the independently
approved rollback path removes this gate under both native writer reservations.
"""
import hashlib
import hmac
import json
import re
import sqlite3

TABLE = 'application_source_writer_fence'
PREFIX = 'application_retired_writer_'
_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def assert_sqlite_writer_allowed(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='application_source_writer_fence'").fetchone():
        # Even an empty, malformed or forged gate is a stop, never an invitation
        # to start a stale writer. Independent migration review owns its repair.
        raise sqlite3.OperationalError('application_source_writer_retired')


def install(db, payload, key, *, schema_definitions=None):
    if not db.in_transaction or type(key) is not bytes or len(key) != 32:
        raise ValueError('held_source_writer_reservation_required')
    # A stale supported constructor may initialize an optional domain without
    # using Store.tx. Materialize the finite reviewed table set before adding
    # triggers, so that CREATE IF NOT EXISTS cannot open an unfenced write path.
    # Arbitrary caller-selected DDL is outside the supported service profile.
    if schema_definitions is not None:
        if type(schema_definitions) is not dict or len(schema_definitions) > 1024:
            raise ValueError('reviewed_source_schema_required')
        present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(set(schema_definitions) - present)
        if missing != payload.get('materialized_tables'):
            raise ValueError('reviewed_source_schema_required')
        for name in missing:
            definition = schema_definitions[name]
            if (not _NAME.fullmatch(name) or type(definition) is not str
                    or not re.match(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?["\[]?'+re.escape(name)+r'(?:["\]]|\s|\()', definition, re.I)):
                raise ValueError('reviewed_source_schema_required')
            db.execute(definition)
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
    signature = hmac.new(key, b'application-source-writer-v1\0'+raw.encode(), hashlib.sha256).hexdigest()
    db.execute('CREATE TABLE application_source_writer_fence(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL,signature TEXT NOT NULL)')
    db.execute('INSERT INTO application_source_writer_fence VALUES(1,?,?)', (raw, signature))
    tables = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for name, sql in tables:
        if name == TABLE or sql.upper().startswith('CREATE VIRTUAL TABLE') or not _NAME.fullmatch(name):
            continue
        for action in ('INSERT', 'UPDATE', 'DELETE'):
            trigger = PREFIX + action.lower() + '_' + name
            db.execute('CREATE TRIGGER "'+trigger+'" BEFORE '+action+' ON "'+name+'" BEGIN SELECT RAISE(ABORT,\'application_source_writer_retired\'); END')
    return {'source_gate_sha256': hashlib.sha256(raw.encode()).hexdigest(), 'signature': signature}


def verify(db, payload, key):
    row = db.execute('SELECT payload,signature FROM application_source_writer_fence WHERE id=1').fetchone()
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return bool(row and row[0] == raw and hmac.compare_digest(row[1],
        hmac.new(key, b'application-source-writer-v1\0'+raw.encode(), hashlib.sha256).hexdigest()))


def remove(db):
    if not db.in_transaction:
        raise ValueError('held_source_writer_reservation_required')
    triggers = db.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
    for row in triggers:
        if row[0].startswith(PREFIX) and _NAME.fullmatch(row[0]):
            db.execute('DROP TRIGGER "'+row[0]+'"')
    db.execute('DROP TABLE application_source_writer_fence')
