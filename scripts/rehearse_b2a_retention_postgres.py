"""B2A contracts on disposable PostgreSQL or an owned local PG18 schema.

--schema uses the configured local Unix socket, with private synthetic tables.
No caller-supplied schema, DSN, credentials or output destination is accepted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster


def _contracts(connect, store_factory=None):
    from agent_market.capability_registry import Registry
    from agent_market.collector import usage
    from agent_market.concierge.front import Front
    from agent_market.concierge.agent_entry import resumed_context, badge_svg
    from agent_market.concierge.discovery_state import execution_state
    from agent_market.concierge.conditional_http import etag_matches
    from agent_market.concierge.recovery import report_outcome
    from agent_market.gateway.store import Store
    from agent_market.storage_adapter import open_store

    pg = connect()
    with pg.cursor() as cursor:
        cursor.execute('SHOW server_version')
        server_version = cursor.fetchone()[0]
    native = (store_factory(pg, initialize=True, workflow_key=b'b'*32) if store_factory
              else open_store('postgresql', connection=pg, initialize=True, workflow_key=b'b'*32))
    reference = Store()
    fronts = []
    checks = {}
    comparisons = []
    try:
        for store in (reference, native):
            tools = [{'name': 'forecast', 'description': 'Weather forecast temperature',
                      'inputSchema': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']},
                      'annotations': {'readOnlyHint': True, 'destructiveHint': False}}]
            registry = Registry(store)
            ids = []
            for name, url in (('Primary Weather', 'https://primary-weather.example/mcp'),
                              ('Standby Weather', 'https://standby-weather.example/mcp'),
                              ('Alias Weather', 'https://primary-weather.example/alias')):
                rid = store.upsert_resource({'key': name, 'source': 'synthetic', 'kind': 'mcp', 'url': url,
                    'name': name, 'description': 'Weather forecast temperature', 'category': 'travel_maps_weather',
                    'price_usdc': 0, 'details': {}})
                store.record_usage(rid, usage.compact_tools(tools), usage.tools_hash(usage.compact_tools(tools)),
                                   {'tools': tools}, None, None, full_tools=tools)
                store.record_health(rid, 'healthy', 200, 1, None, time.time()+21600, auth_observed=False)
                store.record_evaluation(rid, {'score': 95, 'grade': 'A', 'security': 'ok', 'coverage': 100})
                version = registry.current(store.resource(rid))
                now = time.time()-1
                registry.record(version, scope='execution', outcome='succeeded', started=now, finished=now)
                ids.append(rid)
            front = Front(store)
            fronts.append(front)
            visitor = front.book.create('rest', 'SyntheticB2ARehearsal', 'synthetic-b2a-binding')
            found = front.concierge.handle(visitor, 'weather forecast', {'protocol': 'mcp'})
            assert len(found.data['recommendations']) == 3
            resumed = resumed_context(front, visitor.token)
            assert not resumed['changed']
            assert all(item['capability_contract']['verified_within_24h'] for item in resumed['recommendations'])
            assert 'Verified Grade A' in badge_svg(store, ids[0])
            comparisons.append([(r['id'], r['kind'], r['capability_contract']['input_required']) for r in resumed['recommendations']])
            tools[0]['inputSchema'] = {'type': 'object', 'properties': {'place': {'type': 'string'}}, 'required': ['place']}
            store.record_usage(ids[0], usage.compact_tools(tools), usage.tools_hash(usage.compact_tools(tools)),
                               {'tools': tools}, None, None, full_tools=tools)
            assert resumed_context(front, visitor.token)['changed']
            assert 'Verified' not in badge_svg(store, ids[0])
            version = registry.current(store.resource(ids[0]))
            now = time.time()-0.5
            registry.record(version, scope='execution', outcome='succeeded', started=now, finished=now)
            recovered = report_outcome(front, visitor, {'resource_id': ids[0], 'ok': False,
                                                       'task': 'weather forecast', 'error_type': 'timeout'})
            assert [r['id'] for r in recovered['alternatives']] == [ids[1]]
            assert recovered['error_category'] == 'timeout' and recovered['execution_authorized'] is False
            assert front.book.failed_resources(visitor.id) == {ids[0]}
            before = execution_state(store, store.resource(ids[0]))['evidence_id']
            report_outcome(front, visitor, {'resource_id': ids[0], 'ok': True})
            assert execution_state(store, store.resource(ids[0]))['evidence_id'] == before
            now = time.time()
            registry.record(version, scope='execution', outcome='failed', started=now, finished=now, code='UPSTREAM_TIMEOUT')
            assert 'Verified' not in badge_svg(store, ids[0])
        checks['sqlite_postgres_discovery_contract_parity'] = sorted(comparisons[0]) == sorted(comparisons[1])
        checks['same_agent_schema_change_invalidates_resume_and_badge'] = True
        checks['latest_transient_failure_withdraws_verified_badge'] = True
        checks['same_host_alias_excluded_from_recovery'] = True
        checks['feedback_does_not_fabricate_execution_evidence'] = True
        checks['weak_and_list_etags_match_without_changing_execution_authority'] = etag_matches('"other", W/"abc"', '"abc"')
        assert all(checks.values())
        return {'checks': checks, 'postgres_version': server_version, 'full_application_ready': False}
    finally:
        for front in fronts:
            assert front.book.close()
        native.close()
        pg.close()
        reference._db.close()


def _worker():
    from scripts import rehearse_application_store_postgres as base
    base._contracts = _contracts
    base._worker()


def rehearse():
    driver = _driver()
    paths = [Path(__file__), Path('agent_market/application_store_sql.json')]
    paths.extend(Path('agent_market/concierge') / name for name in (
        'agent_entry.py', 'front.py', 'fast_chat.py', 'selection.py', 'inertia.py',
        'discovery_state.py', 'conditional_http.py', 'recovery.py'))
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    preferred = Path('/opt/homebrew/opt/postgresql@18/bin')
    tools = ({name: str(preferred/name) for name in ('initdb', 'pg_ctl')}
             if all((preferred/name).is_file() for name in ('initdb', 'pg_ctl')) else _tools())
    with _private_cluster(tools) as cluster:
        environment = dict(cluster['environment'])
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(driver.__file__).resolve().parent.parent)
        child = subprocess.run([sys.executable, '-B', '-c',
            'from scripts.rehearse_b2a_retention_postgres import _worker; _worker()'],
            env=environment, input=json.dumps({'socket': cluster['socket'], 'root': cluster['root']}),
            text=True, capture_output=True, timeout=120)
        if child.returncode:
            raise RuntimeError('B2A rehearsal failed: ' + child.stderr[-3500:])
        result = json.loads(child.stdout)
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return {'profile': 'b2a-retention-owned-postgres-v1', **result, 'source_unchanged': True,
            'temporary_cluster_removed': True, 'operating_database_writes': 0, 'external_provider_calls': 0}


def schema_rehearsal(*, full=False, adoption=False):
    """Run reviewed fixtures against a fresh schema, never the public Store."""
    from contextlib import ExitStack
    from unittest.mock import patch
    import socket
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from scripts.agentcon_config import read_settings
    from agent_market.application_runtime import _private_bytes
    from agent_market.postgres_schema_rehearsal import owned_schema, SchemaRehearsalStore
    from agent_market.application_store_postgres import _CATALOG, WRITER_LOCK, ApplicationStoreError

    values = read_settings('gateway-data/agentcon.env')
    params = conninfo_to_dict(_private_bytes(values.get('APPLICATION_POSTGRES_DSN_FILE'), 16384).decode().strip())
    allowed = {'host', 'port', 'dbname', 'user', 'password'}
    if (set(params)-allowed or not params.get('host', '').startswith('/')
            or not params.get('dbname') or not params.get('user')):
        raise ValueError('schema_rehearsal_requires_explicit_local_unix_profile')
    if any(os.environ.get(n) for n in ('PGSERVICE', 'PGOPTIONS', 'PGHOSTADDR')):
        raise ValueError('schema_rehearsal_inherited_configuration_refused')
    params.update(hostaddr='', password=params.get('password', ''),
        options='', application_name='agent-concierge-schema-rehearsal',
        connect_timeout=3, sslmode='disable', gssencmode='disable', autocommit=True)
    paths = [Path(__file__), Path('scripts/rehearse_application_store_postgres.py')]
    paths += sorted(Path('agent_market').rglob('*.py'))
    paths.append(Path('agent_market/application_store_sql.json'))
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    connections = []
    def connect():
        pg = psycopg.connect(**params)
        if pg.info.host != params['host']:
            pg.close()
            raise ValueError('schema_rehearsal_transport_changed')
        connections.append(pg)
        return pg
    # Disable import-time IPv6 probing before the no-provider socket guard.
    ipv6 = socket.has_ipv6
    try:
        socket.has_ipv6 = False
        import urllib3  # noqa: F401
    finally:
        socket.has_ipv6 = ipv6
    from agent_market.infra.redis_hub import RedisHub
    offline = RedisHub(); offline._closed = True
    forbidden = []
    original_connect = socket.socket.connect
    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            forbidden.append(True)
            raise AssertionError('External network is forbidden in schema fixtures.')
        return original_connect(sock, address)
    with ExitStack() as stack:
        private_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='ac-schema-config-')))
        password_file = private_dir / 'pgpass'
        password_file.touch(mode=0o600)
        params['passfile'] = str(password_file)
        stack.enter_context(patch.object(RedisHub, '_instance', offline))
        stack.enter_context(patch.object(socket.socket, 'connect', guarded_connect))
        control = connect()
        try:
            with control.cursor() as cur:
                cur.execute('SHOW search_path'); search_path = cur.fetchone()
            try:
                with owned_schema(control) as schema:
                    def factory(pg, **kw):
                        return SchemaRehearsalStore(pg, schema, **kw)
                    try:
                        result = _contracts(connect, factory)
                        boundary = factory(connect())
                        try:
                            with boundary.tx(readonly=True):
                                cur = boundary._native('SELECT current_schema()')
                                assert cur.fetchone() == (schema.name,); cur.close()
                                cur = boundary._native("SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'")
                                tables = cur.fetchone()[0]; cur.close()
                                assert tables == len(_CATALOG['tables'])
                                assert boundary._writer_identity() != WRITER_LOCK
                                try:
                                    boundary._native('SELECT 1 FROM public.resources')
                                except ApplicationStoreError as error:
                                    assert str(error) == 'rehearsal_schema_escape'
                                else:
                                    raise AssertionError('Cross-schema query accepted.')
                        finally:
                            boundary.close()
                            for pg in connections[1:]:
                                if not pg.closed: pg.close()
                        if adoption:
                            from scripts.rehearse_agent_adoption import contracts
                            result['adoption']=contracts(connect,factory)
                        if full:
                            # Full application fixtures use a second empty schema.
                            from scripts.rehearse_application_store_postgres import _contracts as full_contracts
                            with owned_schema(control) as full_schema:
                                def full_factory(pg, **kw):
                                    return SchemaRehearsalStore(pg, full_schema, **kw)
                                try:
                                    result['application'] = full_contracts(connect, store_factory=full_factory,
                                                                         require_private_cluster=False)
                                finally:
                                    for pg in connections[1:]:
                                        if not pg.closed: pg.close()
                    finally:
                        for pg in connections[1:]:
                            if not pg.closed: pg.close()
            finally:
                with control.cursor() as cur:
                    cur.execute('SHOW search_path'); assert cur.fetchone() == search_path
        finally:
            for pg in connections:
                if not pg.closed: pg.close()
    assert not forbidden, 'Unexpected external network attempt'
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, 'Sources changed'
    return {'profile': 'b2a-owned-schema-postgres18-v1', **result,
        'private_schema_tables': tables, 'owned_schemas_removed': True,
        'session_search_path_preserved': True, 'source_unchanged': True,
        'operating_application_data_writes': 0, 'synthetic_schema_writes': True,
        'external_provider_calls': 0, 'shared_cluster_fault_isolation': False,
        'production_native_search_index_tested': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--run', action='store_true', required=True)
    parser.add_argument('--schema', action='store_true')
    parser.add_argument('--full', action='store_true', help='Include full application contracts (requires --schema).')
    args = parser.parse_args()
    if args.full and not args.schema: parser.error('--full requires --schema')
    print(json.dumps(schema_rehearsal(full=args.full) if args.schema else rehearse(), sort_keys=True))


if __name__ == '__main__':
    main()
