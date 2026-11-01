"""Source-bound application PostgreSQL gaps, without importing the app Store.

The existing bounded syntax inventory is reused. Static table declarations are
not a native schema, a repository implementation or permission to migrate data.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
import os
import re
import stat

from . import storage_inventory
from .storage_adapter import SQLiteAdapter, Statement, StorageError

PROFILE = 'application-store-migration-readiness-v1'
LIMITS = {'tables': 512, 'declarations': 3000, 'columns_per_table': 128, 'total_columns': 4096,
          'metadata_bytes': 2 * 1024 * 1024, 'identifier': 128}
_TABLE = re.compile(r'\bCREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["`\[]?([A-Za-z_][A-Za-z0-9_]{0,127})["`\]]?\s*(?:\(|USING\b|AS\b)', re.I)
_START = re.compile(r'\bCREATE\s+(?:VIRTUAL\s+)?TABLE\b', re.I)
_SAFE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,127}\Z')
_PROBE = Statement('readiness.sqlite_mode', 'SELECT q.query_only AS readonly,r.read_uncommitted AS relaxed FROM pragma_query_only() q CROSS JOIN pragma_read_uncommitted() r', 'SELECT NULL WHERE FALSE', readonly=True)
_TABLES = Statement('readiness.tables', "SELECT name,type FROM main.sqlite_schema WHERE type IN ('table','view') ORDER BY name LIMIT ?", 'SELECT NULL WHERE FALSE', readonly=True)
_TEMP = Statement('readiness.temp', "SELECT name FROM temp.sqlite_schema WHERE type IN ('table','view') LIMIT 1", 'SELECT NULL WHERE FALSE', readonly=True)
_COLUMNS = Statement('readiness.columns', 'SELECT name,type,"notnull" AS required,pk,hidden FROM pragma_table_xinfo(?,\'main\') LIMIT ?', 'SELECT NULL WHERE FALSE', readonly=True)
_OWNERS = {
    **{name: 'visitor_privacy_consent_delivery' for name in ('agent_contacts', 'agent_contexts', 'agent_hits',
        'agent_interests', 'agent_marketing_permissions', 'agent_messages', 'agent_outcomes', 'agent_task_budgets',
        'agent_task_events', 'agent_task_permissions', 'agent_task_watches')},
    **{name: 'catalog_observation_search_vector' for name in ('crawl_runs', 'health_checks', 'tool_inertia', 'wellknown_hosts')},
    **{name: 'accounting_commerce' for name in ('fee_history', 'fee_state', 'quotes')},
    **{name: 'marketplace_registry' for name in ('agents', 'services', 'needs', 'offers')},
    'agent_test_reports': 'catalog_capability_evidence', 'erc8004_tokens': 'provider_identity_asset_registry',
    'feedback': 'feedback_moderation', 'sns_likes': 'social_content', 'sns_posts': 'social_content',
    'meta': 'schema_bootstrap_versions', 'storage_rehearsal_counters': 'isolated_storage_rehearsal',
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def owner(name):
    if name in _OWNERS:
        return _OWNERS[name]
    if name in ('admin_users', 'admin_sessions') or name.startswith(('security_', 'admin_')):
        return 'staff_authentication_security'
    if name.startswith('customer_'):
        return 'customer_identity_private_authorization'
    if name.startswith('provider_control_'):
        return 'provider_control_proofs'
    if name.startswith(('workspace_', 'organization_')):
        return 'workspace_private_data_execution_deployment'
    if name.startswith(('workflow_', 'agent_workflow')) or name in ('execution_controls', 'execution_control_events'):
        return 'workflow_authority_queue_delivery'
    if name.startswith('platform_'):
        return 'operational_metadata'
    if name.startswith(('catalog_',)):
        return 'isolated_catalog_adapter_profiles'
    if name.startswith(('capability_', 'connection_')):
        return 'catalog_capability_evidence'
    if name.startswith(('resource', 'vec_', 'legacy_vector_', 'fts_')):
        return 'catalog_observation_search_vector'
    if any(word in name for word in ('ledger', 'escrow', 'payment', 'settlement', 'clearing', 'credit')):
        return 'accounting_commerce'
    if any(word in name for word in ('visitor', 'notification', 'subscriber', 'consent', 'request', 'destination', 'push_', 'task_update')):
        return 'visitor_privacy_consent_delivery'
    return 'unclassified_owner_required'


def _read_fixed(root, item):
    """Reopen only a scanner-listed regular file through no-follow dir fds."""
    parts = item['file'].split('/')
    if (parts[0] != 'agent_market' or len(parts) < 2 or any(not storage_inventory.NAME.fullmatch(p) for p in parts[1:])):
        raise ValueError('source_unavailable')
    descriptors = []
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(root, flags | getattr(os, 'O_DIRECTORY', 0)); descriptors.append(fd)
        for directory in parts[1:-1]:
            fd = os.open(directory, flags | getattr(os, 'O_DIRECTORY', 0), dir_fd=fd); descriptors.append(fd)
        leaf = os.open(parts[-1], flags | getattr(os, 'O_NONBLOCK', 0), dir_fd=fd)
        with os.fdopen(leaf, 'rb') as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > storage_inventory.LIMITS['file_bytes']:
                raise ValueError('source_unavailable')
            data = handle.read(storage_inventory.LIMITS['file_bytes'] + 1)
            after = os.fstat(handle.fileno())
        if (len(data) > storage_inventory.LIMITS['file_bytes'] or before.st_mtime_ns != after.st_mtime_ns
                or before.st_size != after.st_size or hashlib.sha256(data).hexdigest() != item.get('sha256')):
            raise ValueError('source_changed')
        return data.decode('utf-8')
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def audit_sources():
    inventory = storage_inventory.scan()
    declarations, issues = {}, set()
    count = 0
    root = storage_inventory._source_root()
    manifest = [{'file': item['file'], 'sha256': item.get('sha256'), 'complete': item['complete']} for item in inventory['files']]
    for item in inventory['files']:
        if not item['complete']:
            issues.add('incomplete_source_scan'); continue
        try:
            tree = ast.parse(_read_fixed(root, item))
            nodes = 0
            for node in ast.walk(tree):
                nodes += 1
                if nodes > storage_inventory.LIMITS['file_ast_nodes']:
                    raise ValueError('analysis_limit')
                if not isinstance(node, ast.Constant) or type(node.value) is not str:
                    continue
                if _START.search(node.value) and _TABLE.search(node.value) is None:
                    issues.add('dynamic_or_partial_table_declaration')
                for match in _TABLE.finditer(node.value):
                    count += 1
                    if count > LIMITS['declarations'] or len(declarations) >= LIMITS['tables'] and match[1] not in declarations:
                        raise ValueError('analysis_limit')
                    declarations.setdefault(match[1], []).append({'file': item['file'], 'line': node.lineno})
        except (ValueError, SyntaxError, UnicodeError, OSError, RecursionError):
            issues.add('source_or_declaration_incomplete')
    tables = []
    for name, origins in sorted(declarations.items()):
        tables.append({'name': name, 'owner': owner(name), 'declarations': origins,
                       'application_postgres_repository': 'not_integrated', 'native_parity': 'not_verified',
                       'isolated_profile_only': name.startswith('catalog_') or all('fixture' in x['file'] for x in origins)})
    features = inventory['counts']['categories']
    # A checked-in dialect catalog establishes only a scoped source profile.
    # It is neither native execution evidence nor proof that dynamic call sites
    # are implemented. Fixture roots without that profile retain old blockers.
    scoped = None
    profile_path = os.path.join(root, 'application_store_sql.json')
    try:
        if os.path.isfile(profile_path) and not os.path.islink(profile_path):
            with open(profile_path, 'rb') as handle: data = handle.read(4 * 1024 * 1024 + 1)
            profile = json.loads(data) if len(data) <= 4 * 1024 * 1024 else {}
            if profile.get('profile') == 'application-postgres-statements-v1':
                scoped = {'profile': profile['profile'], 'native_execution_verified_by_this_scan': False,
                    'full_application_ready': False, 'operating_enabled': False,
                    'runtime_profile':profile.get('runtime_profile'),
                    'declared_tables': len(profile['tables']), 'registered_dialect_pairs': len(profile['statements']),
                    'source_artifact_sha256': hashlib.sha256(data).hexdigest()}
    except (OSError, ValueError, TypeError, KeyError):
        issues.add('scoped_application_profile_unavailable')
    runtime_declared = bool(scoped and scoped.get('runtime_profile')=='explicit-service-runtime-v1')
    blockers = (['native_service_runtime_acceptance_not_established', 'dynamic_consumer_native_regressions_required'] if runtime_declared
        else ['full_application_postgres_source_gaps', 'legacy_dynamic_repository_bindings_incomplete'] if scoped
        else ['application_store_postgres_backend_unsupported', 'live_application_repository_bindings_not_implemented']) + [
                'native_full_schema_not_captured', 'full_authorization_search_and_ledger_parity_not_verified',
                'operator_cutover_not_authorized']
    if inventory['coverage']['detected_unresolved_sql_calls']:
        blockers.append('unresolved_runtime_sql_boundaries')
    if issues or not inventory['complete']:
        blockers.append('bounded_source_evidence_incomplete')
    if any(table['owner'] == 'unclassified_owner_required' for table in tables):
        blockers.append('unclassified_table_owners')
    return {'profile': PROFILE, 'status': 'application_mapping_incomplete', 'application_postgres_enabled': False,
            'operating_ready': False, 'schema_coverage_complete': False, 'source_scan_complete': inventory['complete'],
            'declaration_scan_complete': not issues and inventory['complete'], 'native_schema_captured': False,
            'source_manifest_hash': _digest(manifest), 'sources': manifest, 'tables': tables,
            'table_owner_counts': dict(sorted(Counter(item['owner'] for item in tables).items())),
            'counts': {'source_files': len(manifest), 'static_table_names': len(tables), 'declarations': count,
                       'unresolved_sql_calls': inventory['coverage']['detected_unresolved_sql_calls']},
            'sqlite_features': {key: value for key, value in features.items() if key.startswith('sql.')},
            'blockers': blockers, 'scoped_application_profile': scoped, 'issues': sorted(issues), 'limits': dict(LIMITS),
            'scope': {'source_only': True, 'source_execution': False, 'database_opened': False,
                      'schema_created': False, 'credential_or_environment_read': False, 'single_atomic_source_snapshot': False},
            'limitations': ['Static declarations may include isolated fixture/pilot schemas; they are not all live tables.',
                'Aliases, string-built declarations, engine-created FTS/vector internals and runtime migrations may remain unresolved.',
                'Native metadata capture verifies shape only, never repository transaction or authorization parity.',
                'Private adapter/rehearsal success does not implement the PostgreSQL application Store.',
                'Missing application repositories are development work; an operating change window cannot substitute for them.']}


def capture_schema(adapter):
    """Optional fixture API only: caller-owned adapter, native readonly snapshot."""
    if type(adapter) is not SQLiteAdapter:
        return {'complete': False, 'issue': 'explicit_sqlite_adapter_required', 'tables': None}
    try:
        with adapter.transaction(readonly=True) as session:
            probe = session.execute(_PROBE).rows[0]
            if probe['readonly'] != 1 or probe['relaxed'] != 0:
                raise ValueError('native_isolation_required')
            if session.execute(_TEMP).rows:
                raise ValueError('temporary_schema_unsupported')
            rows = session.execute(_TABLES, (LIMITS['tables'] + 1,)).rows
            if len(rows) > LIMITS['tables']:
                raise ValueError('table_limit')
            tables, total, metadata_bytes = [], 0, 0
            for row in rows:
                if not _SAFE.fullmatch(row['name']) or row['type'] not in ('table', 'view'):
                    raise ValueError('unsupported_identifier')
                columns = session.execute(_COLUMNS, (row['name'], LIMITS['columns_per_table'] + 1)).rows
                if len(columns) > LIMITS['columns_per_table']:
                    raise ValueError('column_limit')
                selected = []
                for column in columns:
                    if (type(column['name']) is not str or not _SAFE.fullmatch(column['name'])
                            or type(column['type']) is not str or len(column['type']) > 128
                            or not re.fullmatch(r'[A-Za-z0-9_ (),]*', column['type'])):
                        raise ValueError('unsupported_identifier')
                    selected.append(dict(column))
                total += len(columns)
                if total > LIMITS['total_columns']:
                    raise ValueError('column_limit')
                table = {'name': row['name'], 'type': row['type'], 'owner': owner(row['name']), 'columns': selected}
                metadata_bytes += len(json.dumps(table).encode('utf-8'))
                if metadata_bytes > LIMITS['metadata_bytes']:
                    raise ValueError('metadata_limit')
                tables.append(table)
            return {'complete': True, 'issue': None, 'tables': tables, 'schema_hash': _digest(tables),
                    'native_readonly': True, 'repository_parity_verified': False, 'operating_ready': False}
    except (StorageError, ValueError, TypeError, KeyError, UnicodeError):
        return {'complete': False, 'issue': 'native_schema_capture_incomplete', 'tables': None,
                'repository_parity_verified': False, 'operating_ready': False}


def main(argv=None):
    parser = storage_inventory.Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--scan', action=storage_inventory.ScanOnce, nargs=0, default=False)
    try:
        args = parser.parse_args(argv)
        if args.scan is not True:
            raise storage_inventory.InventoryError('invalid_arguments')
        result = audit_sources()
        status = 0 if result['declaration_scan_complete'] else 1
    except storage_inventory.InventoryError as error:
        result, status = {'profile': PROFILE, 'error': error.code, 'operating_ready': False}, 2
    except Exception:
        result, status = {'profile': PROFILE, 'error': 'source_audit_unavailable', 'operating_ready': False}, 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False))
    return status
