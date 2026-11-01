"""Private MCP execution transport uses isolated sessions and a controlled provider."""
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.collector import usage
from agent_market.concierge.proxy import McpProxy
from agent_market.gateway import admin_auth
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from agent_market.infra.redis_hub import RedisHub
from agent_market.workspace_execution import NOTICE, PROFILE
from agent_market.workspace_service import BASE
from tests.test_mcp_proxy import MockRemoteMcp


@pytest.fixture
def private_api(tmp_path, monkeypatch):
    cache = RedisHub(); cache._closed = True
    monkeypatch.setattr(RedisHub, 'get_instance', staticmethod(lambda: cache))
    path = tmp_path / 'private-execution.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript(admin_auth.ADMIN_SCHEMA)
        admin_auth.create_admin_user(db, 'sadmin', 'Synthetic-private-run-password', 'Synthetic owner', 'superadmin')
    store = Store(str(path)); headers = {}; users = {'owner': 1}
    with store.tx() as db:
        for name, role in [('editor', 'admin'), ('viewer', 'admin'), ('operator', 'operator'), ('outsider', 'superadmin')]:
            users[name] = admin_auth.create_admin_user(db, name, 'Synthetic-private-run-password', name, role)['id']
        for name, uid in users.items():
            row = db.execute('SELECT * FROM admin_users WHERE id=?', (uid,)).fetchone()
            token = admin_auth.create_session(db, uid, row['username'], row['role'], row['name'])
            headers[name] = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + token}
    tool = {'name': 'search_news', 'description': 'Search public news',
            'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                            'required': ['query'], 'additionalProperties': False},
            'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}}
    tools = [tool]
    rid = store.upsert_resource({'key': 'mcp:https://private-provider.example/mcp', 'source': 'mcp-registry',
        'kind': 'mcp', 'url': 'https://private-provider.example/mcp', 'name': 'Synthetic news',
        'description': 'Public research', 'category': 'news_media', 'networks': [], 'price_usdc': 0,
        'details': {'remotes': [{'type': 'streamable-http', 'url': 'https://private-provider.example/mcp'}]}})
    store.record_usage(rid, tools=usage.compact_tools(tools), digest=usage.tools_hash(usage.compact_tools(tools)),
                       guide={'tools': tools}, changes=None, trial={'ok': True})
    with store.tx() as db: db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid,))
    calls = []; control = {'mode': 'ok', 'during_list': None}
    remote = MockRemoteMcp(tools, call_result={'content': [{'type': 'text', 'text': 'Private research result <untrusted>'}]})
    def provider(request):
        body = json.loads(request.content or b'{}'); calls.append(body.get('method'))
        if body.get('method') == 'tools/list' and control['during_list']:
            control['during_list']()
        if body.get('method') == 'tools/call' and control['mode'] == 'timeout':
            raise httpx.ReadTimeout('Synthetic provider uncertainty', request=request)
        return remote.handle_request(request)
    proxy = McpProxy(store, allow_private=True, http=httpx.Client(transport=httpx.MockTransport(provider)))
    app = FastAPI(); app.include_router(dashboard_router(store, str(path), 'isolated-machine-token', None,
        front=SimpleNamespace(store=store, proxy=proxy, courier=None), ssl_manager=Mock(get_status=lambda: {})))
    client = TestClient(app, base_url='https://admin.test', raise_server_exceptions=False)
    world = SimpleNamespace(store=store, client=client, headers=headers, users=users, rid=rid, calls=calls,
                            control=control, remote=remote, app=app)
    response = client.post(BASE, headers=headers['owner'], json={'name': 'Private execution team', 'owner_id': 1})
    assert response.status_code == 200, response.text
    world.ws = response.json()['workspace']
    for name, role in [('editor', 'editor'), ('viewer', 'viewer'), ('operator', 'editor')]:
        response = client.post(f'{BASE}/{world.ws["id"]}/members', headers=headers['owner'],
            json={'user_id': users[name], 'role': role, 'active': True, 'revision': 0})
        assert response.status_code == 200, response.text
    definition = {'nodes': [{'id': 'start', 'name': 'Manual start', 'type': 'trigger', 'kind': 'trigger', 'data': {}},
        {'id': 'search', 'name': 'Selected public search', 'type': 'agent', 'kind': 'mcp', 'resource_id': rid,
         'data': {'tool': 'search_news', 'input': {'query': 'Synthetic semiconductor research'}}}],
        'edges': [{'source': 'start', 'target': 'search'}]}
    response = client.post(f'{BASE}/{world.ws["id"]}/drafts', headers=headers['owner'],
        json={'name': 'Private saved search', 'description': 'One explicitly authorized public lookup', 'definition': definition})
    assert response.status_code == 200, response.text
    world.draft = response.json()['draft']
    path = f'{BASE}/{world.ws["id"]}/drafts/{world.draft["id"]}/snapshots'
    response = client.post(path, headers=headers['owner'], json={'draft_revision': world.draft['revision']})
    assert response.status_code == 200, response.text
    world.snapshot = response.json()['snapshot']; world.path = path + '/' + world.snapshot['id'] + '/execution'
    yield world
    client.close(); proxy._http.close(); store._db.close()


def prepare(w, person='owner'):
    response = w.client.post(w.path + '/prepare', headers=w.headers[person],
                             json={'snapshot_revision': w.snapshot['revision']})
    assert response.status_code == 200, response.text
    return response.json()


def authorized(ticket):
    return {'ticket_id': ticket['ticket_id'], 'authorized': True, 'notice': NOTICE}


def execute(w, person='owner'):
    ticket = prepare(w, person)
    response = w.client.post(w.path + '/runs', headers=w.headers[person], json=authorized(ticket))
    assert response.status_code == 200, response.text
    return response.json()['run'], ticket


def test_prepare_is_offline_and_artifact_is_still_non_executable(private_api):
    w = private_api
    response = w.client.get(w.path + '/options', headers=w.headers['owner'])
    assert response.status_code == 200 and response.json()['profile'] == PROFILE
    assert response.json()['supported'] and response.json()['can_run']
    ticket = prepare(w)
    assert ticket['notice'] == NOTICE and ticket['preview']['input'] == {'query': 'Synthetic semiconductor research'}
    assert ticket['preview']['resource_id'] == w.rid and not w.calls
    result = w.client.get(w.path.removesuffix('/execution') + '/artifact', headers=w.headers['owner'])
    assert result.status_code == 200 and not result.json()['executable']


def test_single_call_result_replay_and_history_stay_scoped(private_api):
    w = private_api; job, ticket = execute(w)
    assert job['id'].startswith('wpr_') and job['status'] == 'succeeded', job
    assert w.calls.count('tools/call') == 1
    assert 'Private research result' in json.dumps(job['output'])
    response = w.client.post(w.path + '/runs', headers=w.headers['owner'], json=authorized(ticket))
    assert response.status_code == 200 and response.json()['run']['id'] == job['id']
    assert w.calls.count('tools/call') == 1
    history = w.client.get(w.path + '/runs', headers=w.headers['viewer'])
    assert history.status_code == 200 and 'output' not in history.json()['runs'][0]
    detail = w.client.get(w.path + '/runs/' + job['id'], headers=w.headers['viewer'])
    assert detail.status_code == 200 and detail.json()['run']['output'] == job['output']
    assert detail.headers['cache-control'] == 'no-store'
    assert not {'ticket', 'signature', 'session_ref', 'token', 'grant_id'} & set(detail.json()['run'])
    for table in ('workflow_runs', 'workflow_versions', 'workflow_node_runs', 'workflow_run_authority', 'workflow_result_outbox'):
        assert w.store.query('SELECT COUNT(*) FROM ' + table)[0][0] == 0


@pytest.mark.parametrize('person', ['viewer', 'operator', 'outsider'])
def test_readonly_and_nonmember_sessions_never_admit(private_api, person):
    w = private_api
    response = w.client.post(w.path + '/prepare', headers=w.headers[person], json={'snapshot_revision': w.snapshot['revision']})
    assert response.status_code == 404 and not w.calls
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('headers', [{}, {'X-Dashboard': '1', 'Authorization': 'Bearer isolated-machine-token'},
    {'X-Dashboard': '1', 'Authorization': 'Bearer visitor-token'}])
def test_machine_visitor_and_missing_session_never_authenticate(private_api, headers):
    w = private_api
    for method, suffix in [('GET', '/options'), ('POST', '/prepare'), ('POST', '/runs'), ('GET', '/runs')]:
        response = w.client.request(method, w.path + suffix, headers=headers, json={} if method == 'POST' else None)
        assert response.status_code == 401 and response.headers['cache-control'] == 'no-store'
    assert not w.calls


@pytest.mark.parametrize('field,value', [('authorized', False), ('authorized', 1), ('notice', 'old-purpose'),
    ('input', {'query': 'Modified'}), ('delivery', True), ('execution_profile', 'extended')])
def test_run_authority_is_exact_and_independent(private_api, field, value):
    w = private_api; body = authorized(prepare(w)); body[field] = value
    response = w.client.post(w.path + '/runs', headers=w.headers['owner'], json=body)
    assert response.status_code == 400 and not w.calls


@pytest.mark.parametrize('raw', ['{"snapshot_revision":1,"snapshot_revision":2}', '{"snapshot_revision":NaN}',
    '{"snapshot_revision":1e999}', '[]', '{"snapshot_revision":1,"note":"\\ud800"}', 'x' * 65537])
def test_execution_json_is_strict_before_any_provider_contact(private_api, raw):
    w = private_api
    response = w.client.post(w.path + '/prepare', headers=w.headers['owner'], content=raw)
    assert response.status_code == 400 and response.headers['cache-control'] == 'no-store'
    assert not w.calls


@pytest.mark.parametrize('headers', [{'Origin': 'null'}, {'Origin': 'https://outside.invalid'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_cross_origin_preparation_and_results_are_denied(private_api, headers):
    w = private_api
    for method, suffix in [('GET', '/options'), ('POST', '/prepare'), ('GET', '/runs')]:
        response = w.client.request(method, w.path + suffix, headers={**w.headers['owner'], **headers},
                                   json={'snapshot_revision': 1} if method == 'POST' else None)
        assert response.status_code == 403 and response.headers['cache-control'] == 'no-store'
    assert not w.calls


def test_ticket_cannot_move_to_another_member_or_session(private_api):
    w = private_api; ticket = prepare(w)
    response = w.client.post(w.path + '/runs', headers=w.headers['editor'], json=authorized(ticket))
    assert response.status_code in (404, 409) and not w.calls
    job, _ = execute(w, 'editor')
    assert job['status'] == 'succeeded'


def test_post_dispatch_timeout_is_unknown_without_reexecution(private_api):
    w = private_api; w.control['mode'] = 'timeout'; job, ticket = execute(w)
    assert job['status'] == 'unknown' and w.calls.count('tools/call') == 1
    response = w.client.post(w.path + '/runs', headers=w.headers['owner'], json=authorized(ticket))
    assert response.status_code == 200 and response.json()['run']['status'] == 'unknown'
    assert w.calls.count('tools/call') == 1 and 'Synthetic provider uncertainty' not in response.text


def test_global_legacy_routes_cannot_read_or_replay_a_private_run(private_api):
    w = private_api; job, _ = execute(w)
    for path in ['/admin/api/workflows/runs/' + job['id'], '/admin/api/workflow-runs/' + job['id'] + '/recovery']:
        result = w.client.get(path, headers=w.headers['outsider'])
        assert result.status_code in (400, 404, 422), result.text
        assert 'Private research result' not in result.text
    for suffix in ['/runs', '/runs/' + job['id']]:
        result = w.client.get(w.path + suffix, headers=w.headers['outsider'])
        assert result.status_code == 404 and 'Private research result' not in result.text
    assert w.calls.count('tools/call') == 1


def test_restore_revokes_tickets_and_pauses_workspace_access(private_api):
    from agent_market.workflow_backup import quarantine, restored_inventory
    w = private_api; ticket = prepare(w)
    with w.store.tx() as db:
        inventory = restored_inventory(db)
        quarantine(db)
    assert 'workspace_private_tickets' in inventory['items']
    assert w.store.query('SELECT revoked FROM workspace_private_tickets WHERE id=?', (ticket['ticket_id'],))[0][0]
    result = w.client.post(w.path + '/runs', headers=w.headers['owner'], json=authorized(ticket))
    assert result.status_code == 401 and not w.calls
