"""Native production-sized host metrics and concurrent vector ownership edges."""
from concurrent.futures import ThreadPoolExecutor
import time

import pytest


def test_native_host_metrics_public_aggregates_and_concurrent_bad_requests(monkeypatch):
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, _tools, PORT
    from agent_market.storage_adapter import open_store
    from agent_market.application_store_postgres import ApplicationStoreError
    from agent_market.collector.health import HealthChecker, CheckResult
    from agent_market.concierge.pearl_view import catalog_status
    from agent_market.concierge.verification_summary import execution_summary
    from agent_market.legacy_vector_index import VectorError, ModelDescriptor
    with _private_cluster(_tools()) as cluster:
        conn = psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
        store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'a' * 32)
        try:
            now = time.time()
            with store.tx():
                store._execute('''INSERT INTO resources(key,source,kind,url,name,description,category,networks,details,host,
                    first_seen,last_seen,active,health_status)
                    SELECT 'fixture:'||i,'fixture','mcp','https://host-'||i||'.example/mcp','Synthetic agent',
                    'Public synthetic source','web_search','[]','{}','host-'||i||'.example',%s,%s,1,'healthy'
                    FROM generate_series(1,2105) AS i''', (now, now))
            checker = HealthChecker(store)
            assert len(checker.host_sizes()) == 2105
            resource = store.resource(1)
            token = store.observation_guard(1, 'health', expected_resource=resource)
            with store.observation_transaction(token):
                checker.record(resource, CheckResult('healthy', 200, 1))
            with store.tx(readonly=True):
                assert store._execute('SELECT COUNT(*) FROM health_checks').fetchone()[0] == 1

            # Seed genuine typed rows for boundary and outcome aggregation. The
            # rows are fixture evidence, never published operating assertions.
            start = now - 86400
            with store.tx():
                store._execute("INSERT INTO connection_versions VALUES('fixture-version',1,'binding','schema','mcp-stateless-v1',1,%s)", (now,))
                for i, (offset, outcome) in enumerate(((0, 'succeeded'), (3599.9, 'failed'),
                                                      (3600, 'unknown'), (86400, 'succeeded'))):
                    store._execute('''INSERT INTO capability_evidence(id,version_id,scope,outcome,started,finished,
                        recorded,expires,validator_version,dataset_version,cases,successes)
                        VALUES(%s,'fixture-version','execution',%s,%s,%s,%s,%s,'fixture','fixture',1,%s)''',
                        ('fixture-' + str(i), outcome, start + offset - 1, start + offset,
                         now, now + 86400, int(outcome == 'succeeded')))
            snapshot = catalog_status(store)
            assert snapshot['cataloged'] == snapshot['reachable'] == snapshot['new_24h'] == 2105
            assert snapshot['with_status_check'] == 1
            summary = execution_summary(store, now)
            assert summary['completed'] == 4 and summary['successful_resources'] == 1
            assert summary['hourly'][0]['succeeded'] == summary['hourly'][0]['failed'] == 1
            assert summary['hourly'][1]['unknown'] == summary['hourly'][23]['succeeded'] == 1
            assert summary['by_protocol']['mcp']['succeeded'] == 2

            def rejected_query():
                with pytest.raises(ApplicationStoreError):
                    store.query('SELECT synthetic_unregistered')
                with pytest.raises(ApplicationStoreError):
                    store._db.execute('SELECT synthetic_unregistered')
                with pytest.raises(ApplicationStoreError):
                    store._db.executescript('CREATE TABLE synthetic_unregistered(id INTEGER)')
            with ThreadPoolExecutor(max_workers=1) as pool:
                with store.tx():
                    store._execute("INSERT INTO meta VALUES('valid-other-thread','true')")
                    pool.submit(rejected_query).result(timeout=2)
                    assert not store._failed
            assert store.get_meta('valid-other-thread') is True

            index = store._vector_index
            with pytest.raises(VectorError, match='database_error'):
                with index._tx():
                    store._execute("INSERT INTO meta VALUES('known-rollback','true')")
                    raise ApplicationStoreError('transaction_failed')
            assert not index.broken and not store._broken
            assert store.get_meta('known-rollback') is None
            descriptor = ModelDescriptor('fixture-native-running', revision='v1')
            index.ensure_jobs(descriptor, limit=1, resource_ids=(1,))
            claim = index.claim_batch(descriptor, limit=1, resource_ids=(1,))[0]
            assert index.publish(claim, [1.] + [0.] * 767, descriptor) == 'indexed'

            class LostCommitAcknowledgement:
                def __getattr__(self, name):
                    return getattr(conn, name)
                def commit(self):
                    conn.commit()
                    raise OSError('Synthetic lost commit acknowledgement')
            store._connection = LostCommitAcknowledgement()
            with pytest.raises(VectorError, match='commit_unknown'):
                with index._tx():
                    store._execute("INSERT INTO meta VALUES('uncertain-commit','true')")
            assert index.broken and store._broken
            assert conn.execute("SELECT value FROM meta WHERE key='uncertain-commit'").fetchone()[0] == 'true'
            with pytest.raises(VectorError, match='broken'):
                index.ensure_jobs(descriptor, limit=1, resource_ids=(1,))
        finally:
            store.close()
            conn.close()
