"""Native QA10 checks on disposable PostgreSQL only; no production data or providers."""
import time


def contracts(connect, factory):
    from fastapi.testclient import TestClient
    from agent_market.capability_registry import Registry
    from agent_market.collector import usage
    from agent_market.concierge.front import Front, create_front_app
    from agent_market.concierge.report_projection import public_report

    connection = connect()
    store = factory(connection, initialize=True, workflow_key=b'q' * 32)
    front = None
    checks = {}
    try:
        assert 180000 <= connection.info.server_version < 190000
        checks['postgresql_major_is_18'] = True
        from agent_market.postgres_lexical import install
        install(store)
        assert store._native_lexical is True
        checks['native_gin_lexical_schema_installed'] = True
        registry = Registry(store)
        ids = []
        for key, name, description in (
            ('ground', 'Global Weather', 'Current weather and daily forecasts for any city.'),
            ('space', 'Sky Observatory', 'Aviation and space data: METAR/TAF, space weather, aurora and satellite passes.'),
        ):
            tools = [{'name': 'get_weather', 'description': description,
                'inputSchema': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']},
                'annotations': {'readOnlyHint': True}}]
            rid = store.upsert_resource({'key': 'qa10:' + key, 'source': 'fixture', 'kind': 'mcp',
                'url': f'https://{key}.example/mcp', 'name': name, 'description': description,
                'category': 'travel_maps_weather', 'price_usdc': 0})
            store.record_usage(rid, usage.compact_tools(tools), usage.tools_hash(usage.compact_tools(tools)),
                {'tools': tools}, None, None, full_tools=tools)
            store.record_health(rid, 'healthy', 200, 1, None, time.time() + 21600, auth_observed=False)
            store.record_evaluation(rid, {'score': 95, 'grade': 'A', 'security': 'ok', 'coverage': 100})
            now = time.time() - 1
            registry.record(registry.current(store.resource(rid)), scope='execution', outcome='succeeded', started=now, finished=now)
            ids.append(rid)
        front = Front(store)
        with TestClient(create_front_app(front)) as client:
            response = client.get('/api/explore', params={'q': '*'})
            assert response.status_code == 200 and response.json()['items'] == []
            assert response.json()['status'] == 'needs_query'
            checks['meaningless_query_is_not_a_browse'] = True
            before = connection.execute('SELECT COUNT(*) FROM agent_visitors').fetchone()[0]
            result = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'search', 'arguments': {'task': 'weather', 'kind': 'mcp'}}}).json()['result']
            items = result['structuredContent']['recommendations']
            assert ids[0] in [row['id'] for row in items] and ids[1] not in [row['id'] for row in items]
            assert result['structuredContent']['visitor'] is None and result['structuredContent']['conversation_recorded'] is False
            assert connection.execute('SELECT COUNT(*) FROM agent_visitors').fetchone()[0] == before
            checks['native_lookup_is_stateless_and_terrestrial_weather_is_scoped'] = True
            for repeat in range(2):
                result = client.get('/api/explore', params={'q': 'weather', 'kind': 'mcp'}).json()
                assert ids[0] in [row['id'] for row in result['items']], result
                assert ids[1] not in [row['id'] for row in result['items']]
            with connection.transaction():
                connection.execute("UPDATE resources SET eval_security='quarantine' WHERE id=%s", (ids[0],))
            assert ids[0] not in [row['id'] for row in client.get('/api/explore', params={'q': 'weather', 'kind': 'mcp'}).json()['items']]
            checks['cached_pages_immediately_recheck_quarantine'] = True
            document = client.get('/api/agent/v1/openapi.json').json()
            assert all(path in document['paths'] for path in ('/api/agent/v1/entry',
                '/api/agent/v1/openapi.json', '/api/agent/v1/badge/{resource_id}.svg'))
            checks['documented_public_paths_exist_in_discovery_schema'] = True
            report = public_report({'resource_id': ids[0], 'kind': 'mcp',
                'agent_url': store.resource(ids[0])['url'], 'tags': '["weather","record"]'}, store.resource(ids[0]), store)
            assert report['tags'] == ['weather', 'record'] and report['execution_measured'] is False
            checks['historical_report_does_not_invent_current_execution'] = True
        return {'checks': checks}
    finally:
        if front is not None:
            assert front.book.close()
        store.close()
