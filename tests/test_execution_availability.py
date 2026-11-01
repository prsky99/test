"""Recorded preflight explains denials and preserves healthy public execution."""

import copy
import json
import time

import httpx
import pytest

from agent_market.collector import usage
from agent_market.concierge.execution_availability import (
    resource_execution_availability, workflow_execution_availability,
)
from agent_market.concierge.proxy import McpProxy
from agent_market.concierge.testbench_examples import RECIPES, live_examples
from agent_market.workflow_templates import bind_resources, definitions
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_mcp_proxy import MockRemoteMcp


def _tool(name, properties=None):
    properties = properties or {'query': {'type': 'string'}, 'limit': {'type': 'integer'}}
    return {'name': name, 'description': 'Read controlled public records.',
            'annotations': {'readOnlyHint': True, 'destructiveHint': False},
            'inputSchema': {'type': 'object', 'properties': properties, 'required': list(properties)}}


def _resource(**changes):
    return {'active': 1, 'kind': 'mcp', 'url': 'https://recorded.example/mcp',
            'health_status': 'healthy', 'eval_security': 'ok', 'auth_observed': 0,
            'price_usdc': 0, 'usage_tools_hash': 'fixture-schema',
            'usage_tools': json.dumps([_tool('search_docs')]),
            'last_check_at': 1700000000, **changes}


def test_recorded_http_failure_is_safe_specific_and_never_changes_the_resource():
    resource = _resource(health_status='down', last_status_code=500,
                         last_error='private traceback https://private.example/?token=secret')
    before = copy.deepcopy(resource)
    result = resource_execution_availability(resource, tool='search_docs', arguments={'query': 'camera', 'limit': 2})
    assert result == {'available': False, 'reason_code': 'UPSTREAM_HTTP_ERROR',
        'message': 'A required agent returned HTTP 500 in its latest recorded health check. '
                   'Choose another available connection or retry after it recovers.',
        'http_status': 500, 'checked_at': 1700000000, 'scope': 'recorded_preflight'}
    assert resource == before
    assert 'private' not in json.dumps(result) and 'token' not in json.dumps(result)


@pytest.mark.parametrize('changes,reason', [
    ({'active': 0}, 'RESOURCE_UNAVAILABLE'),
    ({'health_status': 'down'}, 'RESOURCE_UNAVAILABLE'),
    ({'health_status': 'retired'}, 'RESOURCE_UNAVAILABLE'),
    ({'health_status': 'quarantined'}, 'POLICY_DENIED'),
    ({'eval_security': 'quarantine'}, 'POLICY_DENIED'),
    ({'auth_observed': 1}, 'AUTH_REQUIRED'),
    ({'price_usdc': 10}, 'AUTH_REQUIRED'),
    ({'usage_tools_hash': None}, 'SCHEMA_CHANGED'),
    ({'usage_tools': '[]'}, 'TOOL_UNAVAILABLE'),
])
def test_existing_admission_categories_are_kept_separate(changes, reason):
    result = resource_execution_availability(_resource(**changes), tool='search_docs',
                                               arguments={'query': 'camera', 'limit': 2})
    assert not result['available'] and result['reason_code'] == reason


def test_x402_probe_does_not_claim_provider_authorization_or_completed_execution():
    resource = _resource(kind='x402', price_usdc=10)
    assert resource_execution_availability(resource)['reason_code'] == 'AUTH_REQUIRED'
    probe = resource_execution_availability(resource, probe_only=True)
    assert probe['available'] and probe['reason_code'] == 'READY'
    assert 'not guaranteed' in probe['message']


def test_old_http_failure_does_not_override_current_eligible_health():
    state = resource_execution_availability(_resource(last_status_code=500), tool='search_docs',
                                              arguments={'query': 'camera', 'limit': 2})
    assert state['available'] and state['http_status'] is None


@pytest.fixture
def published(catalog):
    store, front, client, add, now = catalog
    recipes = definitions()[1:]
    tools_by_url = {}
    for recipe in recipes:
        for node in recipe['nodes'][1:]:
            url = node['data']['resource_ref']['url']
            name = node['data']['action']
            props = ({'a': {'type': 'string'}, 'b': {'type': 'string'}} if name == 'compare_rackets'
                     else {'query': {'type': 'string'}, 'limit': {'type': 'integer'}})
            tools_by_url.setdefault(url, []).append(_tool(name, props))
    ids = {}
    for number, (url, tools) in enumerate(tools_by_url.items()):
        rid = add(f'Published healthy connection {number}', url=url)
        compact = usage.compact_tools(tools)
        store.record_usage(rid, tools=compact, digest=usage.tools_hash(compact),
                           guide={}, changes=None, trial=None)
        ids[url] = rid
    calls = []

    def provider(request):
        payload = json.loads(request.content or '{}')
        if payload.get('method') == 'tools/call':
            calls.append(payload['params'])
        result = {'content': [{'type': 'text', 'text': 'Controlled informational output.'}],
                  'structuredContent': {'results': [
                      {'slug': 'model-one', 'name': 'Model One', 'year': 2026, 'shape': 'round',
                       'ratings': {'control': 8}, 'page': 'https://source.example/one',
                       'title': 'Camera permissions', 'url': 'https://source.example/docs', 'snippet': 'Permission guide.'},
                      {'slug': 'model-two', 'name': 'Model Two', 'year': 2026, 'shape': 'round',
                       'ratings': {'control': 9}, 'page': 'https://source.example/two',
                       'title': 'Camera settings', 'url': 'https://source.example/settings', 'snippet': 'Settings guide.'},
                  ]}}
        return MockRemoteMcp(tools_by_url[str(request.url)], call_result=result).handle_request(request)

    front.proxy = McpProxy(store, allow_private=True,
                          http=httpx.Client(transport=httpx.MockTransport(provider)))
    front.workflows.proxy = front.proxy
    front.security.allow_probe = lambda *args, **kwargs: True
    workflow_ids = []
    for recipe in recipes:
        workflow_ids.append(store.create_workflow(bind_resources(store, recipe)))
    try:
        yield store, front, client, ids, workflow_ids, calls
    finally:
        for future in list(front.workflows.futures.values()):
            future.result(timeout=5)


def test_workflow_preflight_is_readonly_without_prior_execution_or_contract_evidence(published):
    store, _, _, _, workflow_ids, calls = published
    assert store.query('SELECT COUNT(*) FROM capability_evidence')[0][0] == 0
    before = store._db.total_changes
    for wid in workflow_ids:
        result = workflow_execution_availability(store, store.get_workflow(wid))
        assert result['available'] and result['reason_code'] == 'READY'
    assert store._db.total_changes == before
    assert not calls


@pytest.mark.parametrize('index', [0, 1], ids=['documentation', 'racket-comparison'])
def test_healthy_published_workflow_still_completes_without_admin_bearer(published, monkeypatch, index):
    store, _, client, _, workflow_ids, calls = published
    monkeypatch.setenv('ADMIN_TOKEN', 'isolated-token-' + 'x' * 48)
    monkeypatch.setenv('DEPLOYMENT_MODE', 'production')
    monkeypatch.setenv('PUBLIC_TLS_TERMINATION', 'proxy')
    wid = workflow_ids[index]
    assert workflow_execution_availability(store, store.get_workflow(wid))['available']
    response = client.post('/api/workflows/run', json={'template_id': wid})
    assert response.status_code == 202, response.text
    handle = response.json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get('/api/workflows/runs/' + handle['run_id'],
                            headers={'X-Workflow-Key': handle['run_key']}).json()
        if result['status'] in ('succeeded', 'failed', 'cancelled'):
            break
        time.sleep(.01)
    assert result['status'] == 'succeeded', result
    assert all(node['status'] == 'succeeded' for node in result['node_results'])
    expected = (['search_docs', 'list_plugins'] if index == 0 else ['search_rackets', 'compare_rackets'])
    assert [call['name'] for call in calls] == expected
    if index == 1:
        assert calls[1]['arguments'] == {'a': 'model-one', 'b': 'model-two'}


def test_down_node_explains_http_500_without_fallback_or_provider_dispatch(published):
    store, _, _, _, workflow_ids, calls = published
    workflow = store.get_workflow(workflow_ids[0])
    rid = workflow['nodes'][1]['resource_id']
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='down',last_status_code=500,last_check_at=? WHERE id=?",
                   (time.time(), rid))
    before = copy.deepcopy(workflow)
    state = workflow_execution_availability(store, workflow)
    assert not state['available'] and state['reason_code'] == 'UPSTREAM_HTTP_ERROR'
    assert state['http_status'] == 500 and workflow == before
    assert not calls
    assert store.query('SELECT COUNT(*) FROM workflow_runs')[0][0] == 0


@pytest.mark.parametrize('health', ['healthy', 'quarantined'])
def test_known_schema_failure_stays_unavailable_after_health_recovery_and_expiry(published, health):
    from agent_market.capability_registry import Registry, TTL
    store, _, client, _, workflow_ids, calls = published
    workflow = store.get_workflow(workflow_ids[0])
    rid = workflow['nodes'][1]['resource_id']
    registry = Registry(store)
    version = registry.current(rid)
    finished = time.time() - TTL * 2
    registry.record(version, scope='execution', outcome='failed',
                    started=finished - 1, finished=finished, code='SCHEMA_CHANGED')
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status=?,last_status_code=200 WHERE id=?", (health, rid))
    before = store._db.total_changes
    state = workflow_execution_availability(store, workflow)
    recipe = next(item for item in live_examples(store) if item['id'] == 'camera-docs')
    assert not state['available'] and state['reason_code'] == 'SCHEMA_CHANGED'
    assert not recipe['available'] and recipe['execution_availability']['reason_code'] == 'SCHEMA_CHANGED'
    assert store._db.total_changes == before and not calls
    response = client.post('/api/workflows/run', json={'template_id': workflow['id']})
    assert response.status_code == 202
    handle = response.json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get('/api/workflows/runs/' + handle['run_id'],
                            headers={'X-Workflow-Key': handle['run_key']}).json()
        if result['status'] in ('succeeded', 'failed', 'cancelled'):
            break
        time.sleep(.01)
    assert result['status'] == 'failed'
    failed = next(node for node in result['node_results'] if node['status'] == 'failed')
    assert failed['error_code'] == 'SCHEMA_CHANGED'
    assert not calls


def test_reviewed_new_contract_does_not_inherit_an_old_version_failure(published):
    from agent_market.capability_registry import Registry
    from agent_market.concierge.execution_policy import tools_for
    store, _, _, _, workflow_ids, calls = published
    workflow = store.get_workflow(workflow_ids[0])
    rid = workflow['nodes'][1]['resource_id']
    registry = Registry(store)
    original = registry.current(rid)
    finished = time.time() - 1
    registry.record(original, scope='execution', outcome='failed',
                    started=finished - 1, finished=finished, code='SCHEMA_CHANGED')
    resource = store.resource(rid)
    reviewed = [_tool(spec['name']) for spec in tools_for(resource)]
    reviewed[0]['outputSchema'] = {'type': 'object', 'properties': {'results': {'type': 'array'}}}
    store.record_usage(rid, tools=tools_for(resource), digest=resource['usage_tools_hash'],
                       guide={}, changes=None, trial=None, full_tools=reviewed)
    assert registry.current(rid)['id'] != original['id']
    assert workflow_execution_availability(store, workflow)['available']
    recipe = next(item for item in live_examples(store) if item['id'] == 'camera-docs')
    assert recipe['available']
    assert not calls


def test_unavailable_public_workflow_is_not_reported_as_a_permission_failure(published):
    store, _, client, _, workflow_ids, calls = published
    workflow = store.get_workflow(workflow_ids[0])
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='down' WHERE id=?",
                   (workflow['nodes'][1]['resource_id'],))
    response = client.post('/api/workflows/run', json={'template_id': workflow['id']})
    assert response.status_code == 202
    handle = response.json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get('/api/workflows/runs/' + handle['run_id'],
                            headers={'X-Workflow-Key': handle['run_key']}).json()
        if result['status'] in ('succeeded', 'failed', 'cancelled'):
            break
        time.sleep(.01)
    assert result['status'] == 'failed'
    failed = next(node for node in result['node_results'] if node['status'] == 'failed')
    assert failed['error_code'] == 'RESOURCE_UNAVAILABLE'
    assert 'unavailable' in failed['error'].lower()
    assert not calls


def test_healthy_testbench_still_executes_without_admin_bearer_under_proxy_settings(published, monkeypatch):
    store, _, client, ids, _, calls = published
    monkeypatch.setenv('ADMIN_TOKEN', 'isolated-token-' + 'x' * 48)
    monkeypatch.setenv('DEPLOYMENT_MODE', 'production')
    monkeypatch.setenv('PUBLIC_TLS_TERMINATION', 'proxy')
    rid = next(iter(ids.values()))
    response = client.post('/api/test/execute', json={
        'resource_id': rid, 'tool': 'search_docs',
        'arguments': {'query': 'camera permissions', 'limit': 2},
    })
    assert response.status_code == 200
    assert response.json()['execution_succeeded'] is True
    assert [call['name'] for call in calls] == ['search_docs']


def test_disabled_unbound_node_does_not_disable_an_otherwise_eligible_workflow(published):
    store, _, _, _, workflow_ids, _ = published
    workflow = store.get_workflow(workflow_ids[0])
    workflow['nodes'].append({'id': 'skip', 'type': 'agent', 'kind': 'mcp', 'disabled': True, 'data': {}})
    assert workflow_execution_availability(store, workflow)['available']


def test_unavailable_live_example_has_safe_reason_without_becoming_a_demo(catalog):
    store, _, _, add, now = catalog
    _, title, _, url, tool, args = RECIPES[0]
    rid = add(title, url=url, health_status='down', last_status_code=500, last_check_at=now)
    record = live_examples(store)[0]
    assert not record['available'] and record['resource_id'] is None and not record['simulated']
    assert record['execution_availability']['reason_code'] == 'UPSTREAM_HTTP_ERROR'
    assert record['execution_availability']['http_status'] == 500


def test_paused_global_invocation_is_reflected_by_all_live_recipes_readonly(published):
    store, _, _, _, _, calls = published
    with store.tx() as db:
        db.execute('UPDATE execution_controls SET invoke_enabled=0 WHERE id=1')
    before = store._db.total_changes
    records = live_examples(store)
    assert len(records) == 4
    assert all(not item['available'] and item['resource_id'] is None for item in records)
    assert all(item['execution_availability']['reason_code'] == 'POLICY_DENIED' for item in records)
    assert all(item['execution_availability']['http_status'] is None for item in records)
    assert store._db.total_changes == before and not calls


@pytest.mark.parametrize('flag,value', [('disabled', True), ('is_active', False)])
def test_public_projection_preserves_disabled_data_flags_and_runtime_skips_node(published, flag, value):
    from agent_market.workflows import public_template

    store, _, client, _, workflow_ids, calls = published
    workflow = store.get_workflow(workflow_ids[0])
    workflow['name'] = 'Published workflow with an intentionally skipped step'
    workflow['nodes'].append({'id': 'disabled-unbound', 'name': 'Skipped optional connection',
                              'type': 'agent', 'kind': 'mcp', 'data': {flag: value}})
    workflow['edges'].append({'id': 'skip-after-end', 'source': workflow['nodes'][2]['id'],
                              'target': 'disabled-unbound'})
    wid = store.create_workflow(workflow)
    workflow = store.get_workflow(wid)
    assert workflow_execution_availability(store, workflow)['available']
    projected = public_template(workflow)
    assert projected['nodes'][-1]['data'][flag] is value
    response = client.post('/api/workflows/run', json={'template_id': wid})
    assert response.status_code == 202, response.text
    handle = response.json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get('/api/workflows/runs/' + handle['run_id'],
                            headers={'X-Workflow-Key': handle['run_key']}).json()
        if result['status'] in ('succeeded', 'failed', 'cancelled'):
            break
        time.sleep(.01)
    assert result['status'] == 'succeeded', result
    skipped = next(node for node in result['node_results'] if node['node_id'] == 'disabled-unbound')
    assert skipped['status'] == 'skipped'
    assert [call['name'] for call in calls] == ['search_docs', 'list_plugins']
