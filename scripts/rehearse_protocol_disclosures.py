"""Synthetic MCP/disclosure contracts for a disposable native PostgreSQL store."""
import time
from unittest.mock import AsyncMock


def contracts(connect, factory):
    from fastapi.testclient import TestClient
    from agent_market.capability_registry import Registry
    from agent_market.collector import usage
    from agent_market.concierge.front import Front, create_front_app

    connection = connect()
    store = factory(connection, initialize=True, workflow_key=b'p' * 32)
    front = None
    checks = {}
    try:
        tools = [{'name': 'forecast', 'description': 'Weather forecast temperature',
            'inputSchema': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']},
            'annotations': {'readOnlyHint': True}}]
        rid = store.upsert_resource({'key': 'synthetic:protocol', 'source': 'fixture', 'kind': 'mcp',
            'url': 'https://weather.example/mcp', 'name': 'Weather forecast',
            'description': 'Weather forecast temperature', 'category': 'travel_maps_weather', 'price_usdc': 0})
        store.record_usage(rid, usage.compact_tools(tools), usage.tools_hash(usage.compact_tools(tools)),
            {'tools': tools}, None, None, full_tools=tools)
        store.record_health(rid, 'healthy', 200, 1, None, time.time() + 21600, auth_observed=False)
        store.record_evaluation(rid, {'score': 95, 'grade': 'A', 'security': 'ok', 'coverage': 100})
        registry = Registry(store)
        now = time.time() - 1
        registry.record(registry.current(store.resource(rid)), scope='execution', outcome='succeeded', started=now, finished=now)
        front = Front(store)
        with TestClient(create_front_app(front)) as client:
            def rpc(name, args=None, token=None):
                return client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                    'params': {'name': name, 'arguments': args or {}}},
                    headers={'X-Visitor-Token': token} if token else {}).json()['result']

            def snapshot():
                return {table: connection.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()
                    for table in ('agent_visitors', 'agent_messages', 'agent_interests', 'agent_contexts')}

            before = snapshot()
            for name in ('search', 'find_agents'):
                value = rpc(name, {'task': 'weather forecast for Seoul', 'kind': 'mcp'})
                assert value['structuredContent']['recommendations'][0]['id'] == rid
                assert value['structuredContent']['conversation_recorded'] is False
            assert snapshot() == before
            checks['anonymous_lookup_does_not_create_conversation'] = True
            session = client.post('/chat', json={'message': 'MCP weather forecast for Seoul'}).json()
            token = session['visitor']['token']
            before = snapshot()
            rpc('search', {'task': 'PostgreSQL administration'}, token)
            assert rpc('whats_new', token=token)['structuredContent']['recommendations'][0]['id'] == rid
            assert snapshot() == before
            checks['saved_context_is_read_without_touch_or_overwrite'] = True
            by_name = {t['name']: t for t in client.get('/.well-known/mcp.json').json()['tools']}
            assert all(by_name[name]['annotations']['readOnlyHint'] for name in ('search', 'find_agents', 'whats_new'))
            checks['native_mcp_contract_has_truthful_annotations'] = True
            paid = store.upsert_resource({'key': 'synthetic:payment', 'source': 'fixture', 'kind': 'x402',
                'url': 'https://provider.example/api', 'name': 'Synthetic payment inspection',
                'description': 'Synthetic payment requirement', 'category': 'data_feeds', 'price_usdc': 100})
            store.record_health(paid, 'healthy', 402, 1, None, time.time() + 21600, auth_observed=False)
            front.security.allow_probe = lambda *a, **kw: True
            front.managed_gateway.execute = AsyncMock(return_value={'status_code': 402, 'protocol_valid': True,
                'output': {'x402Version': 2, 'resource': {'url': 'https://provider.example/api'}, 'accepts': []}})
            challenge = client.get(f'/api/gateway/x402/{paid}')
            assert challenge.status_code == 402 and challenge.json()['inspection_only'] is True
            assert challenge.json()['payment_forwarded'] is False
            checks['first_challenge_is_inspection_only'] = True
        return {'checks': checks}
    finally:
        if front is not None:
            assert front.book.close()
        store.close()
