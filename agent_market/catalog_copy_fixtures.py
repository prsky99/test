"""Exact selected synthetic legacy copy sources, never an operating Store.

The 44-column fixture is deliberately smaller than the current Store's 67 known
resource columns. Unsupported domains require the copy profile's explicit
manifest. Stored registry hashes below are declared fixture facts, not hashes
reconstructed from normalized candidate data or evidence of provider success.
"""
import hashlib
import json

from .catalog_shadow import RESOURCE_FIELDS
from .catalog_writer import RESOURCE_SCHEMA
from .storage_adapter import SQLiteAdapter, PostgresAdapter, Statement

LEGACY_RESOURCE_SCHEMA = RESOURCE_SCHEMA
LEGACY_HASHES = ('7' * 64, '4' * 64)
SOURCE_PROFILE = 'owned-legacy-subset-v1'
SOURCE_EPOCH = 5
EXCLUSION_DOMAINS = ('auth', 'trial', 'history', 'authority', 'fts_vector',
                     'unselected_fields', 'uncoordinated_writers')
SOURCE_SCHEMA = RESOURCE_SCHEMA + (
    Statement('catalog.copy_fixture_control_schema',
        'CREATE TABLE catalog_copy_source_control (id INTEGER PRIMARY KEY,epoch BIGINT NOT NULL,profile TEXT NOT NULL)',
        'CREATE TABLE catalog_copy_source_control (id BIGINT PRIMARY KEY,epoch BIGINT NOT NULL,profile TEXT NOT NULL)'),
    Statement('catalog.copy_fixture_clock_schema',
        'CREATE TABLE catalog_copy_source_clocks (resource_id BIGINT NOT NULL,owner TEXT NOT NULL,observed_at REAL NOT NULL,outcome TEXT NOT NULL,PRIMARY KEY(resource_id,owner))',
        'CREATE TABLE catalog_copy_source_clocks (resource_id BIGINT NOT NULL,owner TEXT NOT NULL,observed_at DOUBLE PRECISION NOT NULL,outcome TEXT NOT NULL,PRIMARY KEY(resource_id,owner))'),
    Statement('catalog.copy_fixture_exclusion_schema',
        'CREATE TABLE catalog_copy_source_exclusions (domain TEXT PRIMARY KEY,records BIGINT)',
        'CREATE TABLE catalog_copy_source_exclusions (domain TEXT PRIMARY KEY,records BIGINT)'),
)
EXCLUDED_LEGACY_RESOURCE_FIELDS = (
    'auth_autonomy', 'auth_checked_at', 'auth_error', 'auth_method', 'auth_scope',
    'cap_currencies', 'cap_error', 'cap_languages', 'cap_regions', 'cap_tool_count',
    'cap_tool_names', 'eval_coverage', 'eval_info', 'last_error', 'last_status_code',
    'probe_fail', 'probe_latency_ms', 'probe_ok', 'probed_at', 'trial_info',
    'trial_ok', 'usage_changes', 'usage_updated_at',
)
_INSERT = Statement('catalog.copy_fixture_resource',
    'INSERT INTO resources (' + ','.join(RESOURCE_FIELDS) + ') VALUES (' + ','.join(('?',) * len(RESOURCE_FIELDS)) + ')',
    'INSERT INTO resources (' + ','.join(RESOURCE_FIELDS) + ') VALUES (' + ','.join(('%s',) * len(RESOURCE_FIELDS)) + ')')
_RESOURCES = Statement('catalog.copy_fixture_resources',
    'SELECT ' + ','.join(RESOURCE_FIELDS) + ' FROM main.resources ORDER BY id',
    'SELECT ' + ','.join(RESOURCE_FIELDS) + ' FROM public.resources ORDER BY id', readonly=True)


def source_rows():
    """Fresh private mappings; nonsequential IDs and old hashes are intentional."""
    endpoint = 'https://copy-source.example/agents/seven/mcp'
    tools = [{'name': 'lookup', 'description': 'Find news reference records'}]
    full = [tools[0] | {'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                                      'required': ['query'], 'additionalProperties': False}}]
    compact_json = json.dumps(tools, sort_keys=True)
    full_json = json.dumps(full, sort_keys=True)
    first = dict.fromkeys(RESOURCE_FIELDS)
    first.update(id=7, key='synthetic:owned-copy:seven', source='synthetic-legacy-copy', kind='mcp',
        url=endpoint, name='Stock News Reader', description='Research news and reference records',
        category='news', active=1, first_seen=0.0, last_seen=100.0, health_status='reachable',
        last_check_at=120.0, last_ok_at=120.0, eval_score=88.5, eval_grade='B',
        eval_security='unknown', eval_at=None, content_hash=LEGACY_HASHES[0],
        auth_declared=None, auth_observed=None, auth_info=None,
        details=json.dumps({'endpoint': endpoint, 'synthetic': True}, sort_keys=True),
        usage_tools=compact_json, usage_full_tools=full_json,
        usage_full_hash=hashlib.sha256(full_json.encode()).hexdigest(),
        usage_tools_hash=hashlib.sha256(compact_json.encode()).hexdigest(),
        usage_guide=json.dumps({'endpoint': endpoint, 'synthetic': True}, sort_keys=True),
        networks=',,', price_usdc=None, pay_to=None, method=None, calls_30d=0,
        payers_30d=0, last_called=None, host='copy-source.example', desc_lang='en',
        regions=None, cap_checked_at=None, consecutive_failures=0, failing_since=None,
        next_check_at=160.0, health_ok_24h=1, health_n_24h=1)
    second = dict.fromkeys(RESOURCE_FIELDS)
    second.update(id=41, key='synthetic:owned-copy:forty-one', source='synthetic-legacy-copy', kind='a2a',
        url='https://copy-source.example/agents/forty-one', name='Inactive Docs Reader',
        description='Archived documentation reference', category='docs', active=0,
        first_seen=5.0, last_seen=80.0, content_hash=LEGACY_HASHES[1], details='{}',
        networks=',,', host='copy-source.example', consecutive_failures=0,
        health_ok_24h=0, health_n_24h=0)
    return first, second


legacy_rows = source_rows


def seed_resources(adapter):
    """Create only the explicit two-row synthetic resource subset."""
    if type(adapter) not in (SQLiteAdapter, PostgresAdapter):
        raise ValueError('Use an explicit disposable adapter.')
    rows = legacy_rows()
    with adapter.transaction() as session:
        for statement in LEGACY_RESOURCE_SCHEMA:
            session.execute(statement)
        for row in rows:
            session.execute(_INSERT, tuple(row[name] for name in RESOURCE_FIELDS))
    return rows


def seed_source(adapter, *, unsupported=None):
    """Seed exactly four synthetic tables, with explicit unsupported-domain facts.

    Nonzero or unknown exclusion facts are deliberately available for refusal
    tests. They are declarations about this selected fixture, not an audit of an
    operating legacy Store. No credential, authority or history rows are seeded.
    """
    if type(adapter) not in (SQLiteAdapter, PostgresAdapter):
        raise ValueError('Use an explicit disposable adapter.')
    if unsupported is None:
        unsupported = {}
    if (type(unsupported) is not dict or not set(unsupported) <= set(EXCLUSION_DOMAINS)
            or any(value is not None and (type(value) is not int or not 0 <= value < 2**63)
                   for value in unsupported.values())):
        raise ValueError('Use bounded synthetic exclusion declarations.')
    rows = source_rows()
    with adapter.transaction() as session:
        for statement in SOURCE_SCHEMA:
            session.execute(statement)
        for row in rows:
            session.execute(_INSERT, tuple(row[name] for name in RESOURCE_FIELDS))
        session.execute(Statement('catalog.copy_fixture_control_seed',
            'INSERT INTO catalog_copy_source_control (id,epoch,profile) VALUES (1,?,?)',
            'INSERT INTO catalog_copy_source_control (id,epoch,profile) VALUES (1,%s,%s)'),
            (SOURCE_EPOCH, SOURCE_PROFILE))
        clock_insert = Statement('catalog.copy_fixture_clock_seed',
            'INSERT INTO catalog_copy_source_clocks (resource_id,owner,observed_at,outcome) VALUES (?,?,?,?)',
            'INSERT INTO catalog_copy_source_clocks (resource_id,owner,observed_at,outcome) VALUES (%s,%s,%s,%s)')
        for owner, observed, outcome in (('health', 120.0, 'reachable'),
                ('survey', 150.0, 'failed'), ('evaluation', 140.0, 'recorded')):
            session.execute(clock_insert, (7, owner, observed, outcome))
        exclusion_insert = Statement('catalog.copy_fixture_exclusion_seed',
            'INSERT INTO catalog_copy_source_exclusions (domain,records) VALUES (?,?)',
            'INSERT INTO catalog_copy_source_exclusions (domain,records) VALUES (%s,%s)')
        for domain in EXCLUSION_DOMAINS:
            session.execute(exclusion_insert, (domain, unsupported.get(domain, 0)))
    return rows


seed_legacy = seed_source


def mutate_source(adapter, *, description='Updated synthetic copy source'):
    """A cooperating writer locks the control row before changing this fixture.

    SQLite's write transaction excludes other writers. PostgreSQL's row lock
    coordinates only participants in this explicit source protocol.
    """
    if type(adapter) not in (SQLiteAdapter, PostgresAdapter):
        raise ValueError('Use an explicit disposable adapter.')
    if (type(description) is not str or not description or len(description) > 2000
            or '\0' in description):
        raise ValueError('Use a bounded synthetic description.')
    with adapter.transaction() as session:
        control = session.execute(Statement('catalog.copy_fixture_lock_control',
            'SELECT epoch FROM catalog_copy_source_control WHERE id=1',
            'SELECT epoch FROM catalog_copy_source_control WHERE id=1 FOR UPDATE')).rows
        if len(control) != 1 or not 0 <= control[0]['epoch'] < 2**63 - 1:
            raise ValueError('Use an initialized synthetic source.')
        session.execute(Statement('catalog.copy_fixture_mutate_resource',
            'UPDATE resources SET description=? WHERE id=7',
            'UPDATE resources SET description=%s WHERE id=7'), (description,))
        epoch = control[0]['epoch'] + 1
        session.execute(Statement('catalog.copy_fixture_advance_epoch',
            'UPDATE catalog_copy_source_control SET epoch=? WHERE id=1',
            'UPDATE catalog_copy_source_control SET epoch=%s WHERE id=1'), (epoch,))
    return epoch


def private_resources(adapter):
    """Private source equality witness; never return this in a report."""
    if type(adapter) not in (SQLiteAdapter, PostgresAdapter):
        raise ValueError('Use an explicit disposable adapter.')
    with adapter.transaction(readonly=True) as session:
        return tuple(dict(row) for row in session.execute(_RESOURCES).rows)


def private_source_state(adapter):
    """A raw private equality witness; never a report or public projection."""
    if type(adapter) not in (SQLiteAdapter, PostgresAdapter):
        raise ValueError('Use an explicit disposable adapter.')
    tables = (('resources', 'id'), ('catalog_copy_source_control', 'id'),
              ('catalog_copy_source_clocks', 'resource_id,owner'),
              ('catalog_copy_source_exclusions', 'domain'))
    statements = tuple(Statement('catalog.copy_fixture_state_' + str(index),
        'SELECT * FROM main.' + table + ' ORDER BY ' + order,
        'SELECT * FROM public.' + table + ' ORDER BY ' + order, readonly=True)
        for index, (table, order) in enumerate(tables))
    with adapter.transaction(readonly=True) as session:
        return {table: tuple(dict(row) for row in session.execute(statement).rows)
                for (table, _), statement in zip(tables, statements)}
