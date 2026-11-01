"""Bounded source-only inventory of application SQL consumers and unresolved paths.

Every sink retains its source location and source hash. A registry match is
source coverage, never native execution proof. Dynamic and separate SQLite-only
utilities remain explicit; neither metadata nor method counts imply readiness.
No SQL text, row values, credentials, filesystem addresses or DSNs are emitted.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json

from . import storage_inventory as inventory
from .store_migration_readiness import _read_fixed

PROFILE = 'application-postgres-consumer-coverage-v1'
_NATIVE = {'application_store_postgres', 'application_store_collector', 'application_store_finance',
    'application_store_vector', 'application_store_migration', 'application_store_sns', 'application_store_selection', 'application_store_consumers', 'postgres_restore_guard',
    'postgres_archive_provider', 'postgres_operational_archive', 'workflow_postgres_archive'}
_SQLITE_ONLY = {'concierge/token_hygiene', 'workflow_backup','workflow_template_install','application_writer_fence'}
_SEPARATE_SQLITE = {'broker/registry'}
_PILOT = {'catalog_capture', 'catalog_copy', 'catalog_copy_fixtures', 'catalog_index', 'catalog_index_fixtures',
    'catalog_index_outbox', 'catalog_observation_fixtures', 'catalog_observations', 'catalog_repository',
    'catalog_repository_fixtures', 'catalog_shadow', 'catalog_writer', 'catalog_writer_fixtures',
    'storage_adapter', 'workflow_storage', 'workflow_storage_fixtures', 'workflow_storage_rehearsal'}


# These identify source-owned families, not blanket runtime SQL admission.
# Every row still records the exact source bytes/line, and native proof is a
# separate artifact. An added branch therefore remains visible in this scan.
_NAMED = {
 'gateway/dashboard': {'dashboard_router.agents','dashboard_router.needs','dashboard_router.timeseries','dashboard_router.insights','dashboard_router.explore','dashboard_router.test_agents','dashboard_router.get_workflow_agent_alternatives','dashboard_router.agent_telemetry','dashboard_router.remediate_agent_telemetry'},
 'gateway/admin_auth': {'list_audit_logs','update_admin_user'},
 'gateway/notification_preferences': {'list'},
 'gateway/sns': {'_discoveries','_evaluations','_trials','_usage_changes','_feedback','_stored','_resources_by_id','_engagement'},
 'collector/registries': {'_migrate','defer_dead_hosts'},
 'concierge/memory': {'prune','interests','global_failing_resources'},
 'concierge/security': {'get_rules','get_events'},
 'concierge/task_updates': {'run_due','maintain'},
 'workflow_maintenance': {'run'},
 'workflow_operations': {'subject'},
 'concierge/selection': {'search'},
 'gateway/visitor_desk': {'list'},
 'concierge/front': {'get_front_explore','get_front_insights','get_front_explore.run_q','get_front_insights.q','find_existing_agent'},
}
_DISPATCH = {('gateway/store','query'),('workspace_access','_rows'),('legacy_vector_index','_rows'),
    ('observability','_write'),('gateway/dashboard','dashboard_router.overview'),('gateway/dashboard','dashboard_router.errors'),('concierge/front','get_snapshot_overview.q')}


class _Coverage(inventory.Analyzer):
    def __init__(self, tree, file, statements, scripts):
        super().__init__(tree, file, inventory.LIMITS['findings'])
        self.rows, self.functions = [], []
        self.statements, self.scripts = statements, scripts
        self.module = file[len('agent_market/'):-3]

    def visit_FunctionDef(self, node):
        self.functions.append(node.name)
        try: super().visit_FunctionDef(node)
        finally: self.functions.pop()
    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr in ('execute','executemany','executescript','query','_execute','_native'):
            method = node.func.attr
            resolved = self.resolve(node.args[0]) if node.args else None
            sql = resolved[0] if resolved else None
            forced = method in ('executemany','executescript','query','_execute','_native') or self.db_receiver(node.func.value)
            if forced or sql is not None and inventory.SQL_START.match(sql):
                from .application_store_postgres import _normalized
                fixed = _normalized(sql) if sql is not None else None
                if self.module in _NATIVE: status = 'native_source_boundary'
                elif self.module in _SQLITE_ONLY: status = 'explicit_sqlite_utility'
                elif self.module in _SEPARATE_SQLITE: status = 'separate_sqlite_store'
                elif self.module in _PILOT or self.module.endswith('_fixtures'): status = 'isolated_profile'
                elif sql in self.scripts: status = 'registered_schema_script'
                elif fixed in self.statements: status = 'registered_dialect_pair'
                elif sql == 'BEGIN IMMEDIATE' or sql == 'PRAGMA database_list': status = 'explicit_native_control'
                elif sql is not None: status = 'literal_requires_review'
                else: status = 'dynamic_requires_review'
                function='.'.join(self.functions)
                if self.module=='concierge/managed_gateway' and method=='_execute':status='non_sql_execution_sink'
                elif self.module=='collector/server' and function=='create_app.agents':status='native_consumer_seam_sqlite_fallback'
                elif self.module=='gateway/store' and self.functions and self.functions[0]=='__init__':status='sqlite_constructor_native_replaced'
                elif self.module=='gateway/store' and self.functions:
                    from .gateway.store import Store
                    from .application_store_postgres import PostgresApplicationStore
                    name=self.functions[0]
                    original=getattr(Store,name,None);current=getattr(PostgresApplicationStore,name,None)
                    if current is not None and current is not original:
                        status='unsupported_store_entry' if getattr(current,'__name__',None)=='_unsupported' else 'native_method_override'
                if (self.module,function) in {('gateway/rag','ensure_vec_table'),('legacy_vector_index','install'),
                        ('legacy_vector_index','read_snapshot'),('gateway/store','_init_observation_guards'),
                        ('gateway/store','_sync_fts_if_needed'),('gateway/store','_open_connection')}:
                    status='native_alternative_sqlite_implementation'
                elif function=='__init__' and self.module in ('provider_claims','shadow_ledger'):
                    status='strict_registered_schema_dispatch'
                elif function=='__init__' and self.module=='application_control_retention':
                    status='strict_registered_schema_dispatch'
                if status in ('literal_requires_review','dynamic_requires_review'):
                    if function in _NAMED.get(self.module,set()):status='named_fixed_query_family'
                    elif (self.module,function) in _DISPATCH:status='registered_dispatch_boundary'
                    elif function=='__init__' and self.module.startswith(('workspace_','workflow_','customer_')):status='strict_registered_schema_dispatch'
                self.rows.append({'file':self.file,'line':node.lineno,'column':node.col_offset+1,
                    'function':'.'.join(self.functions),'sink':method,'status':status,
                    'sql_hash':hashlib.sha256(sql.encode()).hexdigest() if sql is not None else None})
        super().visit_Call(node)


def audit():
    scan = inventory.scan()
    from .application_store_postgres import _CATALOG, _normalized
    statements = {_normalized(row['sqlite']) for row in _CATALOG['statements']}
    scripts = set(_CATALOG.get('scripts',{}))
    files, rows, issues = [], [], set()
    if not scan['complete']: issues.add('incomplete_source_scan')
    for item in scan['files']:
        files.append({'file':item['file'],'sha256':item.get('sha256'),'complete':item['complete']})
        if not item['complete']: continue
        try:
            tree = ast.parse(_read_fixed(inventory._source_root(),item))
            analyzer = _Coverage(tree,item['file'],statements,scripts)
            analyzer.visit(tree)
            rows.extend(analyzer.rows)
            issues.update(analyzer.issues)
        except (OSError,ValueError,SyntaxError,UnicodeError,RecursionError): issues.add('source_changed_or_incomplete')
        if len(rows)>inventory.LIMITS['findings']:
            issues.add('sink_limit');rows=rows[:inventory.LIMITS['findings']];break
    counts = Counter(row['status'] for row in rows)
    by_module = {}
    for row in rows:
        module = row['file']
        by_module.setdefault(module,Counter())[row['status']]+=1
    return {'profile':PROFILE,'complete':not issues,'issues':sorted(issues),'files':files,
        'sinks':rows,'counts':dict(sorted(counts.items())),
        'modules':{name:dict(sorted(count.items())) for name,count in sorted(by_module.items())},
        'native_execution_verified':False,'full_application_ready':False,'operating_enabled':False,
        'limitations':[
            'A syntactic sink is not a proven receiver or runtime branch.',
            'Dynamic query families need their named native tests; unresolved means review, not a proven defect.',
            'Registered literal fragments do not establish that enclosing dynamic SQL is registered.',
            'Known native repositories, isolated pilots and SQLite-only maintenance are distinguished, not silently counted as compatibility.',
            'Source hashes bind this bounded scan; no running process, actual database, load or external integration is inspected.']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--audit',action='store_true',required=True)
    parser.parse_args(argv)
    value=audit();print(json.dumps(value,sort_keys=True))
    return 0 if value['complete'] else 1


if __name__=='__main__':raise SystemExit(main())
