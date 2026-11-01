"""Synthetic private schema/data for isolated atomic catalog-writer contracts.

History rows are deliberately expired/unknown fixtures, never proof of real
provider verification. These selected tables are not a full Registry migration.
"""
import hashlib
import json

from .storage_adapter import Statement

MODEL_HASH = hashlib.sha256(b'synthetic-catalog-model-v1').hexdigest()
URL = 'https://synthetic-provider.example/projects/catalog/mcp?token=synthetic-private-token'

HISTORY_SCHEMA = (
    Statement('catalog.fixture_versions',
        'CREATE TABLE connection_versions (id TEXT PRIMARY KEY,resource_id INTEGER NOT NULL,binding_hash TEXT NOT NULL,schema_hash TEXT NOT NULL,profile_version TEXT NOT NULL,schema_complete INTEGER NOT NULL,created REAL NOT NULL,UNIQUE(resource_id,binding_hash,schema_hash,profile_version))',
        'CREATE TABLE connection_versions (id TEXT PRIMARY KEY,resource_id BIGINT NOT NULL,binding_hash TEXT NOT NULL,schema_hash TEXT NOT NULL,profile_version TEXT NOT NULL,schema_complete INTEGER NOT NULL,created DOUBLE PRECISION NOT NULL,UNIQUE(resource_id,binding_hash,schema_hash,profile_version))'),
    Statement('catalog.fixture_evidence',
        "CREATE TABLE capability_evidence (id TEXT PRIMARY KEY,version_id TEXT NOT NULL,scope TEXT NOT NULL,outcome TEXT NOT NULL,started REAL NOT NULL,finished REAL NOT NULL,recorded REAL NOT NULL,expires REAL NOT NULL,code TEXT,operation_ref TEXT,contract_id TEXT NOT NULL DEFAULT '',validator_version TEXT NOT NULL,dataset_version TEXT NOT NULL,cases INTEGER NOT NULL,successes INTEGER NOT NULL,artifact_hash TEXT,UNIQUE(version_id,scope,operation_ref,contract_id))",
        "CREATE TABLE capability_evidence (id TEXT PRIMARY KEY,version_id TEXT NOT NULL,scope TEXT NOT NULL,outcome TEXT NOT NULL,started DOUBLE PRECISION NOT NULL,finished DOUBLE PRECISION NOT NULL,recorded DOUBLE PRECISION NOT NULL,expires DOUBLE PRECISION NOT NULL,code TEXT,operation_ref TEXT,contract_id TEXT NOT NULL DEFAULT '',validator_version TEXT NOT NULL,dataset_version TEXT NOT NULL,cases BIGINT NOT NULL,successes BIGINT NOT NULL,artifact_hash TEXT,UNIQUE(version_id,scope,operation_ref,contract_id))"),
    Statement('catalog.fixture_approvals',
        'CREATE TABLE capability_approvals (version_id TEXT NOT NULL,contract_id TEXT NOT NULL,tool TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(version_id,contract_id))',
        'CREATE TABLE capability_approvals (version_id TEXT NOT NULL,contract_id TEXT NOT NULL,tool TEXT NOT NULL,created DOUBLE PRECISION NOT NULL,PRIMARY KEY(version_id,contract_id))'),
    Statement('catalog.fixture_eligibility',
        'CREATE TABLE capability_eligibility (resource_id INTEGER PRIMARY KEY,version_id TEXT NOT NULL,outcome TEXT NOT NULL,executed_at REAL NOT NULL,expires REAL NOT NULL)',
        'CREATE TABLE capability_eligibility (resource_id BIGINT PRIMARY KEY,version_id TEXT NOT NULL,outcome TEXT NOT NULL,executed_at DOUBLE PRECISION NOT NULL,expires DOUBLE PRECISION NOT NULL)'),
)


def command(**overrides):
    from .catalog_writer import RegistryUpsert
    fields = {'key': 'synthetic:catalog:one', 'source': 'synthetic-writer', 'kind': 'mcp', 'url': URL,
              'name': 'Synthetic catalog resource', 'description': 'Connect at ' + URL, 'category': 'news',
              'details_json': json.dumps({'endpoint': URL, 'synthetic': True}, sort_keys=True)}
    fields.update(overrides)
    return RegistryUpsert(**fields)


def operation(number):
    if type(number) is not int or not 0 <= number < 2**128:
        raise ValueError('Use a bounded synthetic operation identifier.')
    return 'co_' + format(number, '032x')


def seed(adapter, *, enabled=True):
    """Initialize selected schemas only on an explicit disposable adapter."""
    from .catalog_writer import RESOURCE_SCHEMA, WRITE_SCHEMA
    from .catalog_index_outbox import INDEX_SCHEMA
    if type(enabled) is not bool:
        raise ValueError('Choose an explicit synthetic write-control state.')
    with adapter.transaction() as session:
        for statement in RESOURCE_SCHEMA + WRITE_SCHEMA + INDEX_SCHEMA + HISTORY_SCHEMA:
            session.execute(statement)
        if enabled:
            session.execute(Statement('catalog.fixture_enable_writer',
                'UPDATE catalog_write_controls SET enabled=1,revision=revision+1 WHERE id=1',
                'UPDATE catalog_write_controls SET enabled=1,revision=revision+1 WHERE id=1'))


def seed_history(adapter, resource_id):
    """Expired non-success fixture rows plus a cache entry to be invalidated."""
    if type(resource_id) is not int or not 0 < resource_id < 2**63:
        raise ValueError('Use a synthetic resource identifier.')
    version = 'fixture-version-' + str(resource_id)
    evidence = 'fixture-evidence-' + str(resource_id)
    with adapter.transaction() as session:
        session.execute(Statement('catalog.fixture_history_version',
            'INSERT INTO connection_versions VALUES (?,?,?,?,?,?,?)',
            'INSERT INTO connection_versions VALUES (%s,%s,%s,%s,%s,%s,%s)'),
            (version, resource_id, 'synthetic-binding', 'synthetic-schema', 'fixture-only', 0, 0.0))
        session.execute(Statement('catalog.fixture_history_evidence',
            'INSERT INTO capability_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            'INSERT INTO capability_evidence VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'),
            (evidence, version, 'synthetic.fixture', 'unknown', 0.0, 0.0, 0.0, 0.0, None, 'synthetic-history',
             'synthetic.contract', 'fixture-only', 'fixture-only', 0, 0, None))
        session.execute(Statement('catalog.fixture_history_approval',
            'INSERT INTO capability_approvals VALUES (?,?,?,?)', 'INSERT INTO capability_approvals VALUES (%s,%s,%s,%s)'),
            (version, 'synthetic.contract', 'synthetic-tool', 0.0))
        session.execute(Statement('catalog.fixture_history_cache',
            'INSERT INTO capability_eligibility VALUES (?,?,?,?,?)', 'INSERT INTO capability_eligibility VALUES (%s,%s,%s,%s,%s)'),
            (resource_id, version, 'failed', 0.0, 0.0))


def history_state(adapter):
    """Private internal values for equality checks; never a report payload."""
    statements = (
        Statement('catalog.fixture_read_versions', 'SELECT * FROM connection_versions ORDER BY id', 'SELECT * FROM connection_versions ORDER BY id', readonly=True),
        Statement('catalog.fixture_read_evidence', 'SELECT * FROM capability_evidence ORDER BY id', 'SELECT * FROM capability_evidence ORDER BY id', readonly=True),
        Statement('catalog.fixture_read_approvals', 'SELECT * FROM capability_approvals ORDER BY version_id,contract_id', 'SELECT * FROM capability_approvals ORDER BY version_id,contract_id', readonly=True),
    )
    with adapter.transaction(readonly=True) as session:
        return tuple(tuple(tuple(row) for row in session.execute(statement).rows) for statement in statements)
