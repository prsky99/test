"""Explicit synthetic catalog schema/data for disposable repository contracts.

These are selected private columns, not the application's complete catalog
schema, collection history, evidence, search indexes or a public response DTO.
"""
import hashlib
import json

from .catalog_repository import COLUMNS
from .storage_adapter import Statement

_TYPES = (
    ('id', 'INTEGER PRIMARY KEY', 'BIGINT PRIMARY KEY'),
    ('key', 'TEXT NOT NULL UNIQUE', 'TEXT NOT NULL UNIQUE'),
    ('source', 'TEXT NOT NULL', 'TEXT NOT NULL'), ('kind', 'TEXT NOT NULL', 'TEXT NOT NULL'),
    ('url', 'TEXT NOT NULL', 'TEXT NOT NULL'), ('name', 'TEXT NOT NULL', 'TEXT NOT NULL'),
    ('description', 'TEXT NOT NULL', 'TEXT NOT NULL'), ('category', 'TEXT NOT NULL', 'TEXT NOT NULL'),
    ('active', 'INTEGER NOT NULL', 'INTEGER NOT NULL'),
    ('first_seen', 'REAL NOT NULL', 'DOUBLE PRECISION NOT NULL'),
    ('last_seen', 'REAL NOT NULL', 'DOUBLE PRECISION NOT NULL'),
    ('health_status', 'TEXT', 'TEXT'), ('last_check_at', 'REAL', 'DOUBLE PRECISION'),
    ('last_ok_at', 'REAL', 'DOUBLE PRECISION'), ('eval_score', 'REAL', 'DOUBLE PRECISION'),
    ('eval_grade', 'TEXT', 'TEXT'), ('eval_security', 'TEXT', 'TEXT'),
    ('eval_at', 'REAL', 'DOUBLE PRECISION'), ('content_hash', 'TEXT', 'TEXT'),
    ('auth_declared', 'INTEGER', 'INTEGER'), ('auth_observed', 'INTEGER', 'INTEGER'),
    ('auth_info', 'TEXT', 'TEXT'), ('details', 'TEXT', 'TEXT'), ('usage_tools', 'TEXT', 'TEXT'),
    ('usage_full_tools', 'TEXT', 'TEXT'), ('usage_full_hash', 'TEXT', 'TEXT'),
    ('usage_tools_hash', 'TEXT', 'TEXT'), ('usage_guide', 'TEXT', 'TEXT'),
)
if tuple(column[0] for column in _TYPES) != COLUMNS:
    raise ValueError('The explicit synthetic schema must match the repository columns.')

CATALOG_SCHEMA = (Statement('catalog.fixture_schema',
    'CREATE TABLE resources (' + ','.join(name + ' ' + sqlite for name, sqlite, _postgres in _TYPES) + ')',
    'CREATE TABLE resources (' + ','.join(name + ' ' + postgres for name, _sqlite, postgres in _TYPES) + ')'),)
_INSERT = Statement('catalog.fixture_insert',
    'INSERT INTO resources (' + ','.join(COLUMNS) + ') VALUES (' + ','.join(('?',) * len(COLUMNS)) + ')',
    'INSERT INTO resources (' + ','.join(COLUMNS) + ') VALUES (' + ','.join(('%s',) * len(COLUMNS)) + ')')


def catalog_rows():
    """Six fixed synthetic private records; no claim of provider verification."""
    rows = []
    for identity, kind, category, active, health, last_seen in (
            (1, 'mcp', 'news', 1, 'healthy', 300.0),
            (2, 'a2a', 'docs', 1, 'reachable', 300.0),
            (3, 'x402', "category' OR 1=1 --", 0, 'down', 100.0),
            (4, 'mcp', 'docs', 1, None, 300.0),
            (5, 'a2a', 'quarantine', 0, 'retired', 0.0),
            (6, 'mcp', 'news', 1, 'failing', 301.0)):
        endpoint = 'https://provider' + str(identity) + '.example/projects/synthetic/mcp'
        if identity == 1: endpoint += '?token=synthetic-private-token'
        record = {
            'id': identity, 'key': kind + ':' + endpoint, 'source': 'synthetic-feed', 'kind': kind,
            'url': endpoint, 'name': 'Synthetic catalog ' + str(identity),
            'description': 'Synthetic catalog only', 'category': category, 'active': active,
            'first_seen': 0.0, 'last_seen': last_seen, 'health_status': health,
            'last_check_at': 300.0, 'last_ok_at': 299.0, 'eval_score': 75.5,
            'eval_grade': 'B', 'eval_security': 'synthetic-unverified', 'eval_at': 298.0,
            'content_hash': hashlib.sha256(('synthetic-content:' + str(identity)).encode()).hexdigest(),
            'auth_declared': 0, 'auth_observed': 0, 'auth_info': '{}',
            'details': json.dumps({'endpoint': endpoint, 'synthetic': True}, sort_keys=True),
            'usage_tools': '[]', 'usage_full_tools': '[]',
            'usage_full_hash': hashlib.sha256(b'synthetic-full-schema').hexdigest(),
            'usage_tools_hash': hashlib.sha256(b'synthetic-compact-schema').hexdigest(),
            'usage_guide': json.dumps({'endpoint': endpoint, 'documentation': 'https://sources.example/catalog'}, sort_keys=True),
        }
        if identity == 1:
            record.update(name='Synthetic Caf\u00e9 \u2603', description='Connect at ' + endpoint,
                          eval_score=98.0, eval_grade='A')
        if identity == 2:
            record.update(last_check_at=None, last_ok_at=None, eval_score=None, eval_grade=None,
                          eval_security=None, eval_at=None, auth_declared=None, auth_observed=None,
                          auth_info=None, details=None, usage_full_hash=None)
        if identity == 3:
            record.update(key="synthetic-key'); DROP TABLE resources; --",
                          source="source'; DROP TABLE resources; --", eval_score=0.0)
        if identity == 4:
            record.update(content_hash=None, usage_tools_hash=None, usage_guide=None)
        if identity == 5:
            # JSON is deliberately raw text at this boundary; no provider schema
            # validation, parsing or credential certification is inferred.
            record.update(details='{deliberately raw synthetic text', last_check_at=None, last_ok_at=None)
        if identity == 6:
            record.update(auth_declared=1, auth_observed=0,
                          auth_info=json.dumps({'Authorization': 'Bearer synthetic-auth-marker'}))
        rows.append(record)
    return tuple(rows)


def seed(adapter, rows=None):
    """Initialize only a caller-owned disposable adapter, with bound values."""
    rows = catalog_rows() if rows is None else rows
    if type(rows) is not tuple or not 1 <= len(rows) <= 1000 or any(type(row) is not dict or set(row) != set(COLUMNS) for row in rows):
        raise ValueError('A bounded explicit synthetic catalog fixture is required.')
    with adapter.transaction() as session:
        for statement in CATALOG_SCHEMA:
            session.execute(statement)
        for row in rows:
            session.execute(_INSERT, tuple(row[column] for column in COLUMNS))
    return len(rows)
