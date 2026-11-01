"""B2A design boundary regressions, promoted from the independent audit."""
import json
import time
from urllib.parse import urlsplit

import httpx
import pytest

from agent_market.concierge.inertia import InertiaGraph
from tests.report_fixtures import execution_report
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_workflow_fallback import routing  # noqa: F401


@pytest.fixture(autouse=True)
def isolated_network(monkeypatch):
    monkeypatch.delenv('AGENT_EDGE_GATEWAY_CONFIG', raising=False)
    def deny_network(*args, **kwargs):
        raise AssertionError('Unexpected external network in isolated audit')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', deny_network)


def ask(client, protocol='auto'):
    return client.post('/chat', json={'message': 'weather forecast', 'data': {'protocol': protocol}}).json()


def report(client, token, resource_id, **extra):
    response = client.post('/mcp', headers={'X-Visitor-Token': token}, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'report', 'arguments': {
            'resource_id': resource_id, 'ok': False, 'task': 'weather forecast', **extra}}})
    assert response.status_code == 200
    return response.json()['result']['structuredContent']


@pytest.mark.parametrize('state', ['stale', 'review', 'latest_failure'])
def test_badge_requires_current_successful_safe_evidence(catalog, state):
    store, _, client, add, now = catalog
    rid = add('Weather badge', health_at=now-172800 if state == 'stale' else now-1,
              eval_security='review' if state == 'review' else '')
    if state == 'latest_failure':
        execution_report(store, rid, now-1, title='Failed check', slug='audit-failed-badge',
                         is_success=0, status_code=500, created_at=now-1)
    response = client.get(f'/api/agent/v1/badge/{rid}.svg')
    assert response.status_code == 200
    assert 'Verified' not in response.text, f'{state} resource is incorrectly labeled Verified'


@pytest.mark.parametrize('protocol,target_kind,health,security', [
    ('auto', 'x402', 'healthy', ''), ('mcp', 'a2a', 'healthy', ''),
    ('mcp', 'mcp', 'down', 'quarantine'), ('mcp', 'mcp', 'healthy', 'review')])
def test_next_steps_preserve_protocol_and_safety_gates(catalog, protocol, target_kind, health, security):
    store, _, client, add, _ = catalog
    primary = add('Primary Weather', kind='a2a' if protocol == 'auto' else 'mcp',
                  description='A2A weather forecast temperature agent' if protocol == 'auto' else 'MCP weather forecast temperature API',
                  report_at=time.time()-1)
    unsafe = add('Unsafe Weather', kind=target_kind, health_status=health, eval_security=security, report_at=time.time()-1)
    InertiaGraph(store).record_transition(primary, 'forecast', unsafe, 'forecast')
    body = ask(client, protocol)
    assert body['data']['recommendations'][0]['id'] == primary
    assert not body['data']['next_steps'], 'Unsafe or out-of-scope next step was published'


def test_optional_prefetch_failure_does_not_break_main_chat(catalog):
    _, _, client, add, _ = catalog
    add('Weather malformed', kind='a2a', usage_tools='{', description='A2A weather forecast temperature agent', report_at=time.time()-1)
    response = client.post('/chat', json={'message': 'weather forecast'})
    assert response.status_code == 200
    assert response.json()['data']['recommendations']


def test_report_alternative_uses_managed_gateway(catalog):
    _, _, client, add, _ = catalog
    first_id = add('Primary Weather')
    add('Standby Weather', report_at=time.time()-1)
    first = ask(client, 'mcp')
    result = report(client, first['visitor']['token'], first_id, error='timeout')
    alternative = result['alternative']
    assert alternative
    assert alternative['url'].startswith('https://agentconcierge.biz/api/gateway/'), alternative['url']


def test_report_respects_explicit_mcp_scope(catalog):
    _, _, client, add, _ = catalog
    first_id = add('Primary Weather')
    add('Other A2A Weather', kind='a2a')
    first = ask(client, 'mcp')
    result = report(client, first['visitor']['token'], first_id)
    assert result['alternative'] is None or result['alternative']['kind'] == 'mcp'


def test_report_excludes_same_host_alias(catalog):
    store, _, client, add, _ = catalog
    first_id = add('Primary Weather')
    second_id = add('Alias Weather')
    with store.tx() as db:
        db.execute('UPDATE resources SET url=? WHERE id=?', ('https://primary-weather.example/alias', second_id))
    first = ask(client, 'mcp')
    result = report(client, first['visitor']['token'], first_id)
    alternative = result['alternative']
    assert alternative is None or urlsplit(store.resource(alternative['id'])['url']).hostname != 'primary-weather.example'


def test_report_schema_supports_designed_error_type(catalog):
    _, _, client, _, _ = catalog
    body = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()
    tool = next(t for t in body['result']['tools'] if t['name'] == 'report')
    assert 'error_type' in tool['inputSchema']['properties']


def test_designed_rest_report_route_exists(catalog):
    _, _, client, add, _ = catalog
    rid = add('Primary Weather')
    first = ask(client, 'mcp')
    response = client.post('/api/agent/v1/report', headers={'X-Visitor-Token': first['visitor']['token']},
                           json={'resource_id': rid, 'ok': False, 'error_type': 'timeout'})
    assert response.status_code not in (404, 405)


def test_resume_invalidates_etag_after_same_agent_contract_changes(catalog):
    store, _, client, add, _ = catalog
    rid = add('Primary Weather')
    first = ask(client, 'mcp')
    headers = {'X-Visitor-Token': first['visitor']['token']}
    before = client.get('/api/agent/v1/resume', headers=headers)
    tools = [{'name': 'forecast', 'description': 'Weather forecast temperature API',
              'inputSchema': {'type': 'object', 'properties': {'place': {'type': 'string'}}, 'required': ['place']}}]
    with store.tx() as db:
        db.execute('UPDATE resources SET usage_tools=?,usage_full_tools=?,usage_guide=? WHERE id=?',
                   (json.dumps(tools), json.dumps(tools), json.dumps({'tools': tools}), rid))
    after = client.get('/api/agent/v1/resume', headers=headers | {'If-None-Match': before.headers['etag']})
    assert after.status_code == 200, 'Schema changed but cached context is declared unchanged'
    assert after.json()['changed'] is True


def test_resume_returns_updated_top_three(catalog):
    _, _, client, add, _ = catalog
    add('Primary Weather')
    first = ask(client, 'mcp')
    add('New Weather')
    result = client.get('/api/agent/v1/resume', headers={'X-Visitor-Token': first['visitor']['token']}).json()
    assert result['changed'] is True
    assert result.get('recommendations'), 'Updated candidates required by design are absent'


def test_next_steps_include_followup_and_per_candidate_contract(catalog):
    store, _, client, add, _ = catalog
    primary = add('Primary Weather', report_at=time.time()-1)
    second = add('Secondary Weather', report_at=time.time()-2)
    InertiaGraph(store).record_transition(primary, 'forecast', second, 'forecast')
    body = ask(client, 'mcp')['data']
    assert body['next_steps']
    assert 'follow_up_query' in body['next_steps'][0]
    assert all('capability_contract' in item and 'revalidate_after_sec' in item for item in body['recommendations'])


def test_each_candidate_has_designed_contract_summary(catalog):
    _, _, client, add, _ = catalog
    add('Primary Weather')
    candidate = ask(client, 'mcp')['data']['recommendations'][0]
    assert 'capability_contract' in candidate
    assert candidate['revalidate_after_sec'] == 3600


def test_report_error_category_does_not_match_generate_as_rate(catalog):
    _, _, client, add, _ = catalog
    rid = add('Primary Weather')
    first = ask(client, 'mcp')
    result = report(client, first['visitor']['token'], rid, error='Unable to generate report')
    assert result['error_category'] != 'rate_limit'


def test_resume_owner_boundary_and_no_body_on_304(catalog):
    _, _, client, add, _ = catalog
    add('Primary Weather')
    first = ask(client, 'mcp')
    headers = {'X-Visitor-Token': first['visitor']['token']}
    response = client.get('/api/agent/v1/resume', headers=headers)
    cached = client.get('/api/agent/v1/resume', headers=headers | {'If-None-Match': response.headers['etag']})
    assert cached.status_code == 304 and cached.content == b''
    assert client.get('/api/agent/v1/resume', headers={'If-None-Match': response.headers['etag']}).status_code == 401
    assert 'no-store' in response.headers['cache-control']


def test_report_remembers_all_session_failures(catalog):
    _, front, client, add, _ = catalog
    ids = [add('Weather ' + str(i)) for i in range(3)]
    first = ask(client, 'mcp')
    token = first['visitor']['token']
    report(client, token, ids[0], error='timeout')
    report(client, token, ids[1], error='HTTP 503')
    assert front.book.failed_resources(first['visitor']['id']) == set(ids[:2])
    response = client.get('/api/agent/v1/resume', headers={'X-Visitor-Token': token}).json()
    assert response['avoid_resource_ids'] == sorted(ids[:2])


def test_skill_alias_and_static_document_etag(catalog):
    _, _, client, _, _ = catalog
    doc = client.get('/skill.md')
    assert doc.status_code == 200
    assert client.get('/.well-known/skill.md').text == doc.text
    conditional = client.get('/skill.md', headers={'If-None-Match': doc.headers['etag']})
    assert conditional.status_code == 304 and not conditional.content


def test_svg_untrusted_grade_is_not_executable(catalog):
    _, _, client, add, _ = catalog
    rid = add('Weather malicious grade', grade='<script>alert(1)</script>')
    response = client.get(f'/api/agent/v1/badge/{rid}.svg')
    assert '<script>' not in response.text
    assert "default-src 'none'" in response.headers['content-security-policy']


def test_measure_conditional_resume_search_work(catalog, monkeypatch, tmp_path):
    _, front, client, add, _ = catalog
    add('Primary Weather')
    first = ask(client, 'mcp')
    headers = {'X-Visitor-Token': first['visitor']['token']}
    baseline = client.get('/api/agent/v1/resume', headers=headers)
    original = front.rec.search
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(front.rec, 'search', counted)
    records = []
    for _ in range(5):
        start = time.perf_counter()
        result = client.get('/api/agent/v1/resume', headers=headers | {'If-None-Match': baseline.headers['etag']})
        records.append({'http': result.status_code, 'body_bytes': len(result.content),
                        'elapsed_ms': round((time.perf_counter()-start)*1000, 2)})
    assert all(r['http'] == 304 and r['body_bytes'] == 0 for r in records)
    (tmp_path / 'resume-measurements.json').write_text(json.dumps({
        'scope': 'isolated in-memory SQLite, one synthetic listing, TestClient',
        'checks': records, 'recommendation_search_calls': len(calls),
        'note': 'No production latency or model-token-use guarantee can be inferred.'}, indent=2))


@pytest.mark.parametrize('header,expected', [
    ('"abc"', True), ('W/"abc"', True), ('"other", W/"abc"', True),
    (' W/"abc" , "other" ', True), ('*', True), ('W/"other"', False),
    ('abc', False), ('"abc" trailing', False), ('"abc",', False),
    ('"other,abc"', False), ('"abc"\r\nX-Foo: yes', False), ('x'*5000, False)])
def test_conditional_get_uses_weak_comparison_without_invalid_header_acceptance(header, expected):
    from agent_market.concierge.conditional_http import etag_matches
    assert etag_matches(header, '"abc"') is expected


def test_resume_weak_and_list_etags_keep_authentication_boundary(catalog):
    _, _, client, add, _ = catalog
    add('Primary Weather')
    body = ask(client, 'mcp')
    headers = {'X-Visitor-Token': body['visitor']['token']}
    current = client.get('/api/agent/v1/resume', headers=headers)
    tag = current.headers['etag']
    for value in ('W/'+tag, '"other", W/'+tag, '*'):
        result = client.get('/api/agent/v1/resume', headers=headers | {'If-None-Match': value})
        assert result.status_code == 304 and result.content == b''
    assert client.get('/api/agent/v1/resume', headers={'If-None-Match': '*'}).status_code == 401
    assert client.get('/api/agent/v1/resume?visitor_token='+body['visitor']['token']).status_code == 401


def test_badge_success_is_version_bound_and_cache_does_not_outlive_evidence(catalog):
    store, _, client, add, now = catalog
    from agent_market.concierge.agent_entry import badge_document
    rid = add('Measured Weather', report_at=now-1)
    assert 'Verified Grade A' in client.get(f'/api/agent/v1/badge/{rid}.svg').text
    with store.tx() as db:
        db.execute('UPDATE capability_evidence SET expires=?', (time.time()+4,))
    svg, ttl = badge_document(store, rid)
    assert 'Verified' in svg and 0 <= ttl <= 4
    with store.tx() as db:
        db.execute('UPDATE resources SET usage_full_tools=? WHERE id=?', ('[]', rid))
    assert 'Verified' not in client.get(f'/api/agent/v1/badge/{rid}.svg').text


def test_same_agent_expired_evidence_changes_resume_without_extending_it(catalog):
    store, _, client, add, now = catalog
    rid = add('Measured Weather', report_at=now-1)
    initial = ask(client, 'mcp')
    headers = {'X-Visitor-Token': initial['visitor']['token']}
    prior = client.get('/api/agent/v1/resume', headers=headers)
    with store.tx() as db:
        db.execute('UPDATE capability_evidence SET expires=?', (time.time()-1,))
    later = client.get('/api/agent/v1/resume', headers=headers | {'If-None-Match': prior.headers['etag']})
    assert later.status_code == 200 and later.json()['changed'] is True
    assert not later.json()['recommendations'][0]['capability_contract']['verified_within_24h']
    assert 'Verified' not in client.get(f'/api/agent/v1/badge/{rid}.svg').text


def test_optional_storage_failure_keeps_primary_recommendation_and_masks_error(catalog, monkeypatch, caplog):
    store, _, client, add, _ = catalog
    add('Primary Weather')
    def broken(*args, **kwargs):
        raise RuntimeError('password=fixture-secret /private/system')
    monkeypatch.setattr(store, 'get_tool_transitions', broken)
    body = ask(client, 'mcp')
    assert body['data']['recommendations'] and body['data']['next_steps'] == []
    assert 'fixture-secret' not in json.dumps(body) and 'fixture-secret' not in caplog.text
    assert 'Next-tool suggestions unavailable (RuntimeError)' in caplog.text


def test_verified_hints_keep_a2a_priority_exclude_failures_and_never_invoke(catalog):
    store, front, _, add, now = catalog
    primary = add('Primary Weather', kind='a2a', report_at=now-1)
    mcp = add('MCP Weather', kind='mcp', report_at=now-2)
    a2a = add('A2A Weather', kind='a2a', report_at=now-3)
    graph = InertiaGraph(store)
    graph.record_transition(primary, 'forecast', mcp, 'forecast')
    graph.record_transition(primary, 'forecast', a2a, 'forecast')
    result = graph.predict_next(primary, 'forecast')
    assert [item['kind'] for item in result] == ['a2a', 'mcp']
    assert all(item['execution_authorized'] is False for item in result)
    assert [item['resource_id'] for item in graph.predict_next(primary, 'forecast', exclude={a2a})] == [mcp]
    assert not front.llm.mock_calls


def test_recovery_returns_three_verified_independent_choices_and_shared_operator_is_excluded(catalog):
    store, _, client, add, now = catalog
    primary = add('Primary Weather', report_at=now-1)
    related = add('Same Publisher Weather', report_at=now-2)
    for i in range(3):
        add('Standby Weather '+str(i), report_at=now-3-i)
    with store.tx() as db:
        for rid in (primary, related):
            db.execute('UPDATE resources SET details=? WHERE id=?',
                       (json.dumps({'repository': {'url': 'https://github.com/shared-owner/weather'}}), rid))
    # Metadata changes create new pins; record proof for those current pins.
    for rid in (primary, related):
        execution_report(store, rid, now-1, title='Current publisher binding', slug='publisher-'+str(rid), is_success=1)
    initial = ask(client, 'mcp')
    value = report(client, initial['visitor']['token'], primary, error_type='timeout')
    assert len(value['alternatives']) == 3
    assert related not in [item['id'] for item in value['alternatives']]
    assert value['alternative'] == value['alternatives'][0]
    assert value['recovery_mode'] == 'suggestions_only' and value['execution_authorized'] is False
    assert all(item['kind'] == 'mcp' and item['capability_contract']['verified_within_24h'] for item in value['alternatives'])


def test_report_success_is_feedback_not_execution_proof(catalog):
    store, _, client, add, _ = catalog
    rid = add('Unverified Weather')
    initial = ask(client, 'mcp')
    headers = {'X-Visitor-Token': initial['visitor']['token']}
    before = store.query('SELECT COUNT(*) FROM capability_evidence')[0][0]
    result = client.post('/api/agent/v1/report', headers=headers, json={'resource_id': rid, 'ok': True})
    assert result.status_code == 200 and result.json()['alternatives'] == []
    assert store.query('SELECT COUNT(*) FROM capability_evidence')[0][0] == before
    assert 'Verified' not in client.get(f'/api/agent/v1/badge/{rid}.svg').text


@pytest.mark.parametrize('extra', [{'resource_id': True}, {'ok': 'false'}, {'error_type': 'arbitrary'},
                                   {'task': {}}, {'error': 'x'*1001}, {'protocol': 'sql'}, {'authority': True}])
def test_invalid_rest_reports_do_not_record_outcomes(catalog, extra):
    store, _, client, add, _ = catalog
    rid = add('Primary Weather')
    initial = ask(client, 'mcp')
    before = store.query('SELECT COUNT(*) FROM feedback')[0][0]
    result = client.post('/api/agent/v1/report', headers={'X-Visitor-Token': initial['visitor']['token']},
                         json={'resource_id': rid, 'ok': False, **extra})
    assert result.status_code == 400
    assert store.query('SELECT COUNT(*) FROM feedback')[0][0] == before


def test_rest_report_requires_existing_session_and_json(catalog):
    _, _, client, add, _ = catalog
    rid = add('Primary Weather')
    initial = ask(client, 'mcp')
    body = {'resource_id': rid, 'ok': False}
    assert client.post('/api/agent/v1/report', json=body).status_code == 401
    assert client.post('/api/agent/v1/report?visitor_token='+initial['visitor']['token'], json=body).status_code == 401
    result = client.post('/api/agent/v1/report', headers={'X-Visitor-Token': initial['visitor']['token']}, content='{}')
    assert result.status_code == 415


def test_rest_and_mcp_report_error_types_have_same_semantics(catalog):
    _, _, client, add, _ = catalog
    rid = add('Primary Weather')
    initial = ask(client, 'mcp')
    token = initial['visitor']['token']
    body = {'resource_id': rid, 'ok': False, 'error': 'rate limit', 'error_type': 'auth_error'}
    rest = client.post('/api/agent/v1/report', headers={'X-Visitor-Token': token}, json=body).json()
    mcp = report(client, token, rid, error='rate limit', error_type='auth_error')
    assert rest['error_category'] == mcp['error_category'] == 'auth_required'
    assert rest['status'] == mcp['status'] == 'no_alternative'


def test_generated_optional_code_cannot_interpolate_tool_names():
    import ast
    name = 'forecast\");raise RuntimeError("injected")#'
    text = InertiaGraph.generate_code_mode_template([{'resource_id': 1, 'name': name}])
    tree = ast.parse(text)
    assert not any(isinstance(node, ast.Raise) for node in ast.walk(tree))
    assert any(isinstance(node, ast.Constant) and node.value == name for node in ast.walk(tree))


def test_verified_published_workflow_recovery_does_not_execute_or_reuse_failed_agent(routing):
    from fastapi.testclient import TestClient
    from agent_market.concierge.front import Front, create_front_app
    from tests.test_workflow_products import published
    runtime, workflow, ids = published(routing)
    store = runtime.store
    rid = store.upsert_resource({'key': 'failed-docs', 'source': 'fixture', 'kind': 'mcp',
        'name': 'Failed Documentation', 'url': 'https://failed-docs.example/mcp',
        'description': 'Public documentation search', 'category': 'developer_tools'})
    front = Front(store)
    before = len(routing[3])
    client = TestClient(create_front_app(front))
    initial = client.post('/chat', json={'message': 'hi'}).json()
    token = initial['visitor']['token']
    body = {'resource_id': rid, 'ok': False, 'task': 'documentation', 'protocol': 'mcp'}
    value = client.post('/api/agent/v1/report', headers={'X-Visitor-Token': token}, json=body).json()
    assert workflow['id'] in [w['id'] for w in value['workflows']]
    later = client.post('/api/agent/v1/report', headers={'X-Visitor-Token': token}, json=body | {'resource_id': ids[0]}).json()
    assert not later['workflows']
    assert len(routing[3]) == before


def test_resume_detects_semantic_approval_withdrawal_without_schema_change(catalog):
    from agent_market.capability_registry import Registry
    store, _, client, add, now = catalog
    rid = add('Measured Weather', report_at=now-1)
    # Approval metadata is distinct from a successful semantic contract test.
    # A proposed contract can be withdrawn while execution proof stays valid.
    Registry(store).approve(store.resource(rid), 'docs.search.v1', 'forecast')
    initial = ask(client, 'mcp')
    candidate = initial['data']['recommendations'][0]
    assert candidate['capability_contracts']
    headers = {'X-Visitor-Token': initial['visitor']['token']}
    first = client.get('/api/agent/v1/resume', headers=headers)
    version = candidate['capability_contract']['connection_version_id']
    with store.tx() as db:
        db.execute('DELETE FROM capability_approvals WHERE version_id=?', (version,))
    later = client.get('/api/agent/v1/resume', headers=headers | {'If-None-Match': first.headers['etag']})
    assert later.status_code == 200 and later.json()['changed'] is True
