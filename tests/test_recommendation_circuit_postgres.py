"""Real PG parity: private cluster, or an explicitly selected isolated schema."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def circuit_contracts(connect):
    from concurrent.futures import ThreadPoolExecutor
    from agent_market.storage_adapter import open_store
    from agent_market.concierge.memory import VisitorBook
    from agent_market.concierge.recommendation_circuit import controls_for, remediate_sqlite
    from agent_market.gateway.store import Store
    from agent_market.infra.redis_hub import RedisHub
    offline = RedisHub(); offline._closed = True; RedisHub._instance = offline
    pg = connect()
    native = open_store('postgresql', connection=pg, initialize=True, workflow_key=b'a'*32)
    reference = Store()
    checks = {}
    try:
        for store in (native, reference):
            for number in range(1, 4):
                store.upsert_resource({'key': 'circuit-'+str(number), 'source': 'fixture', 'kind': 'mcp',
                    'url': 'https://fixture-'+str(number)+'.invalid/mcp', 'name': 'Circuit '+str(number),
                    'description': 'Synthetic circuit control', 'category': 'research', 'networks': []})
            with store.tx() as db:
                for i in range(10):
                    args = ('success-'+str(i), 1, 1, time.time()-60)
                    if store is native:
                        store._execute('INSERT INTO agent_outcomes VALUES (%s,%s,%s,%s)', args)
                    else:
                        db.execute('INSERT INTO agent_outcomes VALUES (?,?,?,?)', args)
        def apply(store, rid, action):
            if store is native:
                return store.remediate_agent_telemetry(action, resource_id=rid, now=time.time())
            return remediate_sqlite(store, rid, action, time.time())
        for store in (native, reference):
            assert apply(store, 1, 'trip_circuit')['circuit_open'] is True
            assert 1 in VisitorBook(store).global_failing_resources()
            assert apply(store, 1, 'reset_circuit')['circuit_open'] is False
            assert 1 not in VisitorBook(store).global_failing_resources()
            with store.tx() as db:
                for i in range(3):
                    args = ('new-failure-'+str(i), 1, 0, time.time())
                    if store is native:
                        store._execute('INSERT INTO agent_outcomes VALUES (%s,%s,%s,%s)', args)
                    else:
                        db.execute('INSERT INTO agent_outcomes VALUES (?,?,?,?)', args)
            assert 1 in VisitorBook(store).global_failing_resources()
            assert apply(store, 1, 'reset_circuit')['history_preserved'] is True
            with store.tx(readonly=True) if store is native else store.tx() as db:
                rows = (store._execute('SELECT * FROM agent_outcomes ORDER BY visitor_id').fetchall()
                        if store is native else db.execute('SELECT * FROM agent_outcomes ORDER BY visitor_id').fetchall())
                assert len(rows) == 13
        checks['manual_open_overrides_ten_successes_without_fake_failures'] = True
        checks['reset_preserves_thirteen_outcome_rows'] = True
        checks['new_epoch_failures_reopen_without_old_success_dilution'] = True
        checks['sqlite_postgres_exclusions_match'] = (
            VisitorBook(native).global_failing_resources() == VisitorBook(reference).global_failing_resources() == set())

        def concurrent_trip(rid):
            connection = connect()
            store = open_store('postgresql', connection=connection, workflow_key=b'a'*32)
            try:
                return store.remediate_agent_telemetry('trip_circuit', resource_id=rid, now=time.time())
            finally:
                store.close(); connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(concurrent_trip, (2, 3)))
        assert all(row['circuit_open'] for row in result)
        assert {'2', '3'} <= controls_for(native).keys()
        assert {2, 3} <= native.global_failing_resources()
        checks['concurrent_staff_controls_do_not_overwrite_other_resources'] = True
        return {'checks': checks, 'production_writes': 0, 'provider_calls': 0}
    finally:
        native.close(); pg.close(); reference._db.close()


def test_native_recommendation_circuit_preserves_evidence_and_serializes_controls():
    mode = os.environ.get('AGENTCON_CIRCUIT_PG_TEST_MODE', 'private-cluster')
    if mode == 'existing-schema':
        from scripts.rehearse_recommendation_circuit_existing_postgres import run
        result = run()
        assert result['passed'] and all(result['checks'].values())
        assert result['schema_removed'] and result['initdb_calls'] == 0
        assert result['operating_schema_writes'] == result['provider_calls'] == 0
        assert result['full_application_profile_install_test'] is False
        folder = Path('reports/ax-remediation-2026-10-25')
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'postgres-parity.json').write_text(json.dumps(result, indent=2)+'\n')
        return
    assert mode == 'private-cluster', 'Explicit supported PostgreSQL test mode required'
    from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster
    driver = _driver()
    with _private_cluster(_tools()) as cluster:
        environment = dict(cluster['environment'])
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PYTHONPATH'] = str(Path.cwd())+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        code = ('from scripts import rehearse_application_store_postgres as base; '
                'from tests.test_recommendation_circuit_postgres import circuit_contracts; '
                'base._contracts=circuit_contracts; base._worker()')
        child = subprocess.run([sys.executable, '-B', '-c', code], env=environment,
            input=json.dumps({'socket': cluster['socket'], 'root': cluster['root']}),
            text=True, capture_output=True, timeout=120)
        assert child.returncode == 0, child.stderr[-5000:]
        result = json.loads(child.stdout)
    assert all(result['checks'].values())
    result['temporary_cluster_removed'] = True
    report = Path('reports/ax-remediation-2026-10-25/postgres-parity.json')
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2)+'\n')
