"""Native Edge state rehearsal in a new private Unix-socket PostgreSQL cluster."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.rehearse_storage_adapter_postgres import _driver, _private_cluster, _tools, PORT


def main():
    from agent_market.storage_adapter import open_store
    from agent_market.concierge.front import Front, create_front_app
    from agent_market.capability_registry import Registry
    from agent_market.edge_gateway.config import Config, Provider, EdgeError
    from agent_market.edge_gateway.service import Service
    from agent_market.edge_gateway.state import migrate, rows, transaction
    connections, stores = [], []
    with _private_cluster(_tools()) as fixture:
        try:
            for initialize in (True, False):
                connection = _driver().connect(host=fixture['socket'], port=PORT, user='postgres', dbname='postgres', autocommit=True)
                connections.append(connection)
                stores.append(open_store('postgresql', connection=connection, initialize=initialize, workflow_key=b'e' * 32))
            store = stores[0]
            rid = store.upsert_resource({'key': 'edge-fixture', 'source': 'fixture', 'kind': 'a2a',
                'url': 'https://provider.example/api', 'name': 'Edge fixture', 'description': 'Weather informational agent',
                'category': 'research', 'networks': [], 'details': {}})
            with store.tx():
                store._execute('UPDATE resources SET health_status=%s,auth_observed=%s WHERE id=%s', ('healthy', 0, rid))
            version = Registry(store).current(rid)['id']
            migrate(store); migrate(store)
            config = Config(b'e' * 32, 'https://agentconcierge.biz', (Provider(rid, version, 'https://provider.example/api'),), True)
            services = []
            for source in stores:
                front = Front(source, llm=Mock(), rag_engine=Mock())
                create_front_app(front, manage_book_lifecycle=False)
                front.courier.resolve = lambda *_args, **_kwargs: {'url': 'https://provider.example/api', 'v1': False}
                services.append(Service(front, config))
            payload = {'resource_id': rid, 'input': {'message': 'What is the weather in Tokyo?'},
                'idempotency_key': 'native-postgres-one-run', 'run_authority': True, 'sharing_authority': True}
            with patch('agent_market.edge_gateway.service.validate_public_url'):
                services[0].observe(0, time.time(), healthy=True)
                grant = services[0].prepare('a' * 64, config.origin, payload)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    repeated = list(pool.map(lambda i: services[i].prepare('a' * 64, config.origin, payload), (0, 1)))
                assert {r['run_id'] for r in repeated} == {grant['run_id']}
                def claim(index):
                    try:
                        value = services[index].claim(grant['access_token'], config.origin, grant['run_id'], payload['input'], ('worker', 'origin')[index])
                        return {'winner': index, 'attempt': value['attempt_id']}
                    except EdgeError as error:
                        return {'denied': error.code}
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(claim, (0, 1)))
                winners = [r for r in results if 'winner' in r]
                assert len(winners) == 1 and any(r.get('denied') == 'ALREADY_CLAIMED' for r in results), results
                services[0].finish(grant['run_id'], winners[0]['attempt'], 'succeeded')
                services[1].finish(grant['run_id'], winners[0]['attempt'], 'succeeded')
                assert services[1].status('a' * 64, grant['run_id'])['state'] == 'succeeded'
                with transaction(store, readonly=True) as db:
                    assert rows(db, 'run', (grant['run_id'],))[0]['state'] == 'succeeded'
                for service in services:
                    service.config = replace(config, max_inflight=1, soft_limit=2)
                def prepare(index):
                    request = {**payload, 'idempotency_key': 'native-concurrent-' + str(index)}
                    return services[index].prepare('a' * 64, config.origin, request)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    grants = list(pool.map(prepare, (0, 1)))
                assert sum('/edge-gateway/' in r['stream_path'] for r in grants) == 1
                def capacity(index):
                    try:
                        r = grants[index]
                        services[index].claim(r['access_token'], config.origin, r['run_id'], payload['input'], 'origin')
                        return 'claimed'
                    except EdgeError as error:
                        return error.code
                with ThreadPoolExecutor(max_workers=2) as pool:
                    assert sorted(pool.map(capacity, (0, 1))) == ['CAPACITY_EXCEEDED', 'claimed']
            print(json.dumps({'native_postgres': 'passed', 'connections': 2, 'additive_migration': True,
                'cross_connection_single_claim': True, 'idempotent_receipts': True, 'idempotent_preparation': True,
                'concurrent_quota_reservation': True, 'concurrent_capacity_limit': True, 'operating_database_accessed': False}))
        finally:
            for store in stores:
                try: store.close()
                except Exception: pass
            for connection in connections:
                connection.close()


if __name__ == '__main__':
    main()
