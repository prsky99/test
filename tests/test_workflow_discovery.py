"""Headless workflow discovery and resumption without any Provider dispatch."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.store import Store
from tests.test_workflow_fallback import routing  # noqa: F401


@pytest.fixture
def discovery(tmp_path, monkeypatch):
    monkeypatch.delenv('AGENT_EDGE_GATEWAY_CONFIG', raising=False)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', lambda *a, **kw: pytest.fail('No external IO in discovery'))
    store = Store(str(tmp_path / 'discovery.db'))
    with store.tx() as db:
        db.execute('UPDATE agent_workflows SET is_template=0')
    ids = {}
    for key, name, names in [
        ('news', 'Daily Tech News & AI Research Digest', ['Technology News', 'Research Papers']),
        ('country', 'Country & Economic Indicator Brief', ['Country Profile', 'Economic Indicators']),
        ('package', 'Package Metadata & Advisory Review', ['Package Metadata', 'Package Security Advisories']),
    ]:
        nodes = [{'id': str(i), 'name': title, 'type': 'agent', 'kind': 'mcp', 'data': {'tool': title.replace(' ', '_').lower()}} for i, title in enumerate(names)]
        ids[key] = store.create_workflow({'name': name, 'nodes': nodes, 'edges': [], 'is_template': 1})
    front = Front(store)
    with TestClient(create_front_app(front), base_url='https://agentconcierge.biz') as client:
        yield store, front, client, ids
    store._db.close()


@pytest.mark.parametrize('query,key', [
    ('papers', 'news'), ('news and research', 'news'), ('기술 뉴스와 관련 논문을 찾아주는 워크플로우 템플릿을 추천해줘', 'news'),
    ('Find a workflow that researches technology news and papers', 'news'),
    ('나라 지표', 'country'), ('국가의 인구 지표 워크플로우', 'country'),
    ('package security workflow', 'package'), ('패키지 취약점 템플릿', 'package'),
])
def test_purpose_and_node_search_share_the_public_api(discovery, query, key):
    store, _, client, ids = discovery
    before = store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]
    result = client.get('/api/workflows/templates', params={'q': query}).json()
    assert [w['id'] for w in result['templates']] == [ids[key]]
    assert store.query('SELECT COUNT(*) FROM workflow_runs')[0][0] == before


@pytest.mark.parametrize('query', ['news and country population', 'workflow that deletes email after researching papers', 'image generation workflow', 'book a hotel workflow'])
def test_no_match_does_not_relax_unmet_capability_constraints(discovery, query):
    assert discovery[2].get('/api/workflows/templates', params={'q': query}).json()['templates'] == []


def rpc(client, name, arguments, token=None):
    return client.post('/mcp', headers={'X-Visitor-Token': token} if token else {}, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}).json()


def test_chat_mcp_a2a_find_the_same_workflow_without_an_agent_substitute(discovery):
    _, _, client, ids = discovery
    task = 'Recommend a workflow template for technology news and related research papers'
    rest = client.post('/chat', json={'message': task}).json()
    mcp = rpc(client, 'search_workflows', {'task': task})['result']['structuredContent']
    a2a = client.post('/a2a', json={'jsonrpc': '2.0', 'id': 1, 'method': 'message/send', 'params': {'message': {
        'parts': [{'kind': 'text', 'text': task}]}}}).json()
    a2a_data = next(p['data'] for p in a2a['result']['parts'] if p['kind'] == 'data')
    for value in (rest['data'], mcp, a2a_data):
        assert value['workflows'][0]['id'] == ids['news']
        assert not value['recommendations']
    assert 'WORKFLOW' in rest['reply'] and rest['visitor']['token'] not in rest['reply']


def test_explicit_protocol_mismatch_preserves_the_constraint(discovery):
    value = rpc(discovery[2], 'search_workflows', {'task': 'research papers workflow', 'protocol': 'a2a'})['result']['structuredContent']
    assert value['reason_code'] == 'protocol_mismatch' and not value['workflows']
    assert value['protocol'] == 'a2a'


def test_workflow_details_hide_private_disabled_and_test_graphs(discovery):
    store, _, client, ids = discovery
    assert rpc(client, 'workflow_details', {'template_id': ids['news']})['result']['isError'] is False
    with store.tx() as db:
        db.execute('UPDATE agent_workflows SET is_template=0 WHERE id=?', (ids['news'],))
    assert client.get(f'/api/workflows/templates/{ids["news"]}').status_code == 404
    assert rpc(client, 'workflow_details', {'template_id': ids['news']})['result']['isError'] is True
    assert rpc(client, 'workflow_details', {'template_id': True})['error']['code'] == -32602


def test_entry_is_small_stable_and_session_free(discovery):
    store, _, client, _ = discovery
    before = store.query('SELECT COUNT(*) FROM agent_visitors')[0][0]
    response = client.get('/api/agent/v1/entry')
    value = response.json()
    assert len(response.content) < 8192
    assert {'find_agent', 'find_workflow', 'resume_task'} <= {a['action'] for a in value['quick_actions']}
    assert client.get('/.well-known/agent-entry.json', headers={'If-None-Match': response.headers['etag']}).status_code == 304
    assert store.query('SELECT COUNT(*) FROM agent_visitors')[0][0] == before
    root = client.get('/', headers={'Accept': 'application/json'}).json()
    assert root['quick_actions'] == value['quick_actions']


def test_resume_is_owner_bound_and_reports_real_definition_changes(discovery):
    store, _, client, ids = discovery
    assert client.get('/api/agent/v1/resume').status_code == 401
    first = client.post('/chat', json={'message': 'research papers workflow'}).json()
    token = first['visitor']['token']
    response = client.get('/api/agent/v1/resume', headers={'X-Visitor-Token': token})
    assert 'no-store' in response.headers['cache-control']
    assert 'X-Visitor-Token' in response.headers.get('vary', '')
    assert response.json()['changed'] is False
    other = client.post('/chat', json={'message': 'hello'}).json()['visitor']['token']
    assert client.get('/api/agent/v1/resume', headers={'X-Visitor-Token': other}).json()['status'] == 'no_context'
    wf = store.get_workflow(ids['news'])
    wf['nodes'][0]['name'] = 'Updated Technology News'
    store.update_workflow(wf['id'], {'nodes': wf['nodes']})
    assert client.get('/api/agent/v1/resume', headers={'X-Visitor-Token': token}).json()['changed'] is True
    later = client.post('/chat', headers={'X-Visitor-Token': token}, json={'message': "what's new"}).json()
    assert later['data']['changed'] is True
    repeated = client.post('/chat', headers={'X-Visitor-Token': token}, json={'message': "what's new"}).json()
    assert repeated['data']['changed'] is False
    assert 'No material workflow change' in repeated['reply']


def test_workflow_followup_cannot_create_provider_feedback(discovery):
    store, _, client, ids = discovery
    first = client.post('/chat', json={'message': 'country population workflow'}).json()
    token = first['visitor']['token']
    before = store.query('SELECT COUNT(*) FROM agent_outcomes')[0][0]
    for message in ('details 1', "what's new"):
        value = client.post('/chat', headers={'X-Visitor-Token': token}, json={'message': message}).json()
        assert value['data']['workflows'][0]['id'] == ids['country']
    value = client.post('/chat', headers={'X-Visitor-Token': token}, json={'message': 'failed 1'}).json()
    assert value['data']['status'] == 'run_key_required'
    assert store.query('SELECT COUNT(*) FROM agent_outcomes')[0][0] == before


def test_new_authoring_still_requires_workspace(discovery):
    value = discovery[2].post('/chat', json={'message': 'Create a new custom workflow for research papers'}).json()
    assert value['data']['status'] == 'authorization_required'
    assert value['data']['workspace_path'] == '/customer/sign-in'


def test_signed_product_discovery_keeps_publication_guards_across_scoped_chat(routing):
    from tests.test_workflow_products import published
    runtime, workflow, _ = published(routing)
    with runtime.store.tx() as db:
        db.execute('UPDATE agent_workflows SET is_template=0 WHERE id<>?', (workflow['id'],))
    front = Front(runtime.store, allow_private=True)
    before = len(routing[3])
    with TestClient(create_front_app(front), base_url='https://agentconcierge.biz') as client:
        first = client.post('/chat', json={'message': 'documentation workflow'}).json()
        assert first['data']['workflows'][0]['id'] == workflow['id']
        assert client.get(f'/api/workflows/templates/{workflow["id"]}').json()['workflow']['product']['inputs']
        token = first['visitor']['token']
        assert client.get('/api/agent/v1/resume?visitor_token='+token).status_code == 401
        changed = runtime.store.get_workflow(workflow['id'])
        changed['nodes'][0]['data']['input']['query'] = 'changed saved contract'
        runtime.store.update_workflow(workflow['id'], {'nodes': changed['nodes']})
        later = client.post('/chat', headers={'X-Visitor-Token': token}, json={'message': 'details 1'}).json()
        assert not later['data']['workflows']
        assert client.get(f'/api/workflows/templates/{workflow["id"]}').status_code == 404
    assert len(routing[3]) == before
