"""Private bounded repeatable captures on explicit caller-owned adapters only.

No connection/path/configuration is opened and no schema is initialized. Each
capture is consistent independently; two connections are never one atomic
cross-database snapshot. Private rows must not be used as public DTOs.
"""
from dataclasses import dataclass
import re

from .storage_adapter import SQLiteAdapter, PostgresAdapter, Statement, StorageError
from .catalog_shadow import (SNAPSHOT_FIELDS, RESOURCE_FIELDS, MAX_RESOURCES,
    MAX_METADATA_ROWS, MAX_TOTAL_ROWS, MAX_SNAPSHOT_BYTES, MAX_VALUE_BYTES,
    _copy_snapshot, _resources, _metadata, _Incomplete, compare_snapshots)

PROFILE = 'bounded-repeatable-catalog-capture-v1'
_TABLES = ('resources', 'catalog_resource_revisions', 'catalog_index_heads',
           'catalog_index_jobs', 'catalog_index_projections')
_FIELDS = (
    RESOURCE_FIELDS,
    ('resource_id', 'revision', 'content_hash', 'hash_profile', 'corpus_hash', 'model_hash', 'updated_at'),
    ('resource_id', 'model_hash', 'revision', 'corpus_hash', 'updated'),
    ('job_id', 'resource_id', 'revision', 'corpus_hash', 'model_hash', 'state', 'projection_hash'),
    ('resource_id', 'model_hash', 'revision', 'corpus_hash', 'projection_hash', 'job_id', 'indexed_at'),
)
_ORDERS = ('id', 'resource_id', 'resource_id', 'job_id', 'resource_id,model_hash')
_READS = tuple(Statement('catalog.capture.' + name,
    'SELECT ' + ','.join(fields) + ' FROM main.' + table + ' ORDER BY ' + order + ' LIMIT ?',
    'SELECT ' + ','.join(fields) + ' FROM public.' + table + ' ORDER BY ' + order + ' LIMIT %s', readonly=True)
    for name, table, fields, order in zip(SNAPSHOT_FIELDS, _TABLES, _FIELDS, _ORDERS))
_PROBE = Statement('catalog.capture.native_probe',
    "SELECT CASE r.read_uncommitted WHEN 0 THEN 'serializable' ELSE 'read uncommitted' END AS isolation,q.query_only AS read_only FROM pragma_read_uncommitted() r CROSS JOIN pragma_query_only() q",
    "SELECT pg_catalog.current_setting('transaction_isolation') AS isolation,CASE pg_catalog.current_setting('transaction_read_only') WHEN 'on' THEN 1 ELSE 0 END AS read_only", readonly=True)
_SCHEMA = Statement('catalog.capture.schema',
    "SELECT schema AS schema_name,name AS table_name,type AS object_type FROM pragma_table_list() WHERE schema IN ('main','temp') AND name IN ('resources','catalog_resource_revisions','catalog_index_heads','catalog_index_jobs','catalog_index_projections') LIMIT 11",
    "SELECT n.nspname AS schema_name,c.relname AS table_name,c.relkind::text AS object_type FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE (n.nspname='public' OR n.oid=pg_catalog.pg_my_temp_schema()) AND c.relname IN ('resources','catalog_resource_revisions','catalog_index_heads','catalog_index_jobs','catalog_index_projections') LIMIT 11", readonly=True)
_CODES = frozenset(('invalid_request', 'isolation_required', 'read_only_required',
    'isolation_unavailable', 'schema_unavailable', 'shadowed_table', 'unsupported_schema',
    'capture_unavailable', 'row_limit', 'field_limit', 'cell_limit', 'value_limit',
    'byte_limit', 'invalid_scalar', 'invalid_row_shape', 'invalid_snapshot_shape',
    'missing_resource_fields', 'invalid_resource_identity', 'duplicate_resource_id',
    'duplicate_resource_key', 'invalid_resource_time', 'invalid_resource_state',
    'invalid_metadata_shape', 'duplicate_metadata_identity', 'result_limit',
    'connection_busy', 'connection_unusable', 'transaction_failed', 'commit_unknown',
    'nested_transaction', 'thread_violation', 'session_closed', 'read_only',
    'invalid_configuration'))


class CaptureError(ValueError):
    def __init__(self, code='invalid_request'):
        self.code = code if code in _CODES else 'capture_unavailable'
        super().__init__(self.code)


@dataclass(frozen=True, repr=False)
class CapturedCatalog:
    complete: bool
    issue: str | None
    role: str
    _tables: tuple = ()

    def __repr__(self):
        return '<CapturedCatalog private>'

    def as_private_snapshot(self):
        if not self.complete:
            return None
        return {name: tuple(dict(row) for row in rows) for name, rows in self._tables}

    def summary(self):
        return {'profile': PROFILE, 'complete': self.complete, 'issue': self.issue,
            'role': self.role, 'row_counts': {name: len(rows) for name, rows in self._tables} if self.complete else None,
            'repeatable_snapshot': self.complete, 'native_read_only': self.complete,
            'selected_columns_only': True, 'worker_tokens_captured': False,
            'observation_owner_clocks_or_journal_captured': False,
            'authority_or_evidence_verified': False,
            'bounds_after_driver_decode': True, 'cpu_or_latency_guaranteed': False,
            'adapter_result_bytes_limit': 1048576,
            'limits': {'resources': MAX_RESOURCES, 'metadata_per_table': MAX_METADATA_ROWS,
                'total_rows': MAX_TOTAL_ROWS, 'snapshot_bytes': MAX_SNAPSHOT_BYTES,
                'scalar_bytes': MAX_VALUE_BYTES}}


def _request(adapter, role):
    if type(adapter) not in (SQLiteAdapter, PostgresAdapter) or type(role) is not str or role not in ('legacy', 'candidate'):
        raise CaptureError()


def _schema(rows, role, dialect):
    required = set(_TABLES if role == 'candidate' else _TABLES[:1])
    main = 'main' if dialect == 'sqlite' else 'public'
    kind = 'table' if dialect == 'sqlite' else 'r'
    seen = set()
    for row in rows:
        if tuple(row.keys()) != ('schema_name', 'table_name', 'object_type'):
            raise CaptureError('unsupported_schema')
        name = row['table_name']
        if name not in required:
            continue
        if row['schema_name'] != main:
            raise CaptureError('shadowed_table')
        if row['object_type'] != kind or name in seen:
            raise CaptureError('unsupported_schema')
        seen.add(name)
    if seen != required:
        raise CaptureError('unsupported_schema')


def capture_snapshot(adapter, *, role):
    """Return no partial rows if a bound/schema/isolation/transaction fails.

    Invalid adapter/role arguments raise a fixed CaptureError before I/O. Data
    failures return an incomplete private result. Cancellation propagates after
    the adapter performs its normal transaction cleanup; no retry occurs.
    """
    _request(adapter, role)
    phase = 'transaction'
    try:
        with adapter.transaction(readonly=True) as session:
            phase = 'isolation'
            probe = session.execute(_PROBE).rows
            if len(probe) != 1 or tuple(probe[0].keys()) != ('isolation', 'read_only'):
                raise CaptureError('isolation_unavailable')
            if probe[0]['isolation'] not in ('serializable', 'repeatable read'):
                raise CaptureError('isolation_required')
            if type(probe[0]['read_only']) is not int or probe[0]['read_only'] != 1:
                raise CaptureError('read_only_required')
            phase = 'schema'
            _schema(session.execute(_SCHEMA).rows, role, adapter.dialect)
            snapshot = {name: () for name in SNAPSHOT_FIELDS}
            total = 0
            for index, (name, statement) in enumerate(zip(SNAPSHOT_FIELDS, _READS)):
                if role == 'legacy' and index:
                    break
                maximum = MAX_RESOURCES if name == 'resources' else MAX_METADATA_ROWS
                rows = session.execute(statement, (maximum + 1,)).rows
                if len(rows) > maximum:
                    raise CaptureError('row_limit')
                total += len(rows)
                if total > MAX_TOTAL_ROWS:
                    raise CaptureError('row_limit')
                if any(tuple(row.keys()) != _FIELDS[index] for row in rows):
                    raise CaptureError('unsupported_schema')
                snapshot[name] = tuple(dict(row) for row in rows)
            phase = 'validation'
            private = _copy_snapshot(snapshot)
            _resources(private['resources'])
            _metadata(private)
            tables = tuple((name, tuple(tuple(row.items()) for row in private[name])) for name in SNAPSHOT_FIELDS)
        return CapturedCatalog(True, None, role, tables)
    except (CaptureError, _Incomplete) as exc:
        return CapturedCatalog(False, CaptureError(exc.code).code, role)
    except StorageError as exc:
        if exc.code == 'statement_failed':
            code = 'isolation_unavailable' if phase == 'isolation' else 'schema_unavailable'
        else:
            code = CaptureError(exc.code).code
        return CapturedCatalog(False, code, role)
    except Exception:
        return CapturedCatalog(False, 'capture_unavailable', role)


def compare_adapters(source_adapter, candidate_adapter, *, expected_model_hash,
                     source_role='legacy', candidate_role='candidate'):
    """Capture sequentially; return only aggregate shadow/capture reports."""
    report = compare_snapshots(None, None, expected_model_hash=expected_model_hash)
    captures = {'profile': PROFILE, 'source': None, 'candidate': None,
                'cross_source_atomic': False, 'sequential_independent_transactions': True}
    report['captures'] = captures
    if type(expected_model_hash) is not str or re.fullmatch('[0-9a-f]{64}', expected_model_hash) is None:
        return report
    try:
        _request(source_adapter, source_role)
        _request(candidate_adapter, candidate_role)
    except CaptureError:
        report['issues'] = ['capture_invalid_request']
        return report
    report['scope']['database_or_source_capture_performed'] = True
    report['scope']['individual_snapshots_repeatable'] = False
    source = capture_snapshot(source_adapter, role=source_role)
    captures['source'] = source.summary()
    if not source.complete:
        report['issues'] = ['source_capture_incomplete']
        return report
    candidate = capture_snapshot(candidate_adapter, role=candidate_role)
    captures['candidate'] = candidate.summary()
    if not candidate.complete:
        report['issues'] = ['candidate_capture_incomplete']
        return report
    report = compare_snapshots(source.as_private_snapshot(), candidate.as_private_snapshot(),
                               expected_model_hash=expected_model_hash)
    report['captures'] = captures
    report['scope']['database_or_source_capture_performed'] = True
    report['scope']['caller_supplied_snapshots'] = False
    report['scope']['individual_snapshots_repeatable'] = True
    return report
