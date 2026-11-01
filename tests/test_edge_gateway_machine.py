"""Public Agent Ticket delivery, quota fallback and uncertain-outcome isolation."""
import json
from dataclasses import replace

import httpx
import pytest

from agent_market.edge_gateway import machine
from agent_market.concierge.proxy import McpProxy
from tests.test_edge_gateway import edge, catalog, ORIGIN  # noqa: F401
from tests.test_edge_gateway_catalog import enable, mcp_resource
from tests.test_mcp_proxy import MockRemoteMcp, WEATHER_TOOL


@pytest.fixture
def machine_edge(edge, catalog, monkeypatch):
    enable(edge, monkeypatch)
    edge.service.config = replace(edge.service.config, native_node_delivery=True)
    rid = mcp_resource(edge, catalog)
    return edge, rid


def run(fixture, client, *, key='agent-request-1', arguments=None, principal='synthetic-visitor'):
    edge, rid = fixture
    return machine.execute(edge.front, rid, 'get_weather', arguments or {'city': 'Tokyo'},
                           principal=principal, idempotency_key=key, http=client)


def worker(fixture, seen, *, lost=False, foreign=False, rejected=False):
    edge, _ = fixture
    def handle(request):
        seen.append(request)
        assert request.url.host == 'agentconcierge.biz'
        assert not any(k in request.headers for k in ('cookie', 'x-visitor-token', 'x-real-ip'))
        assert edge.endpoint not in request.content.decode()
        token = request.headers['authorization'].removeprefix('Bearer ')
        run_id = request.url.path.split('/')[-2]
        binding = edge.service.claim(token, ORIGIN, run_id, json.loads(request.content), backend='worker')
        if lost:
            raise httpx.ReadTimeout('Synthetic accepted result was lost', request=request)
        if rejected:
            edge.service.finish(run_id, binding['attempt_id'], 'failed', outcome_code='PROVIDER_INPUT_REJECTED')
            return httpx.Response(502, json={'error': 'The tool rejected the input.'})
        edge.service.finish(run_id, binding['attempt_id'], 'succeeded')
        return httpx.Response(200, json={'run_id': 'er_' + 'f' * 32 if foreign else run_id,
            'state': 'succeeded', 'output': {'content': [{'type': 'text', 'text': 'Tokyo weather'}]}, 'backend': 'worker'})
    return httpx.Client(transport=httpx.MockTransport(handle))


def test_public_mcp_ticket_uses_worker_once_and_replay_does_not_dispatch(machine_edge):
    seen = []
    with worker(machine_edge, seen) as client:
        first = run(machine_edge, client)
        assert first['ok'] and first['delivery_backend'] == 'worker'
        second = run(machine_edge, client)
        assert not second['ok'] and second['retry_safe'] is False
    assert len(seen) == 1


def test_idempotency_is_principal_bound_and_input_changes_do_not_reexecute(machine_edge):
    seen = []
    with worker(machine_edge, seen) as client:
        assert run(machine_edge, client)['ok']
        assert not run(machine_edge, client, arguments={'city': 'Seoul'})['ok']
        assert run(machine_edge, client, principal='other-synthetic-visitor')['ok']
    assert len(seen) == 2


def test_expired_ticket_replay_never_starts_a_new_execution(machine_edge):
    edge, _ = machine_edge
    seen = []
    with worker(machine_edge, seen) as client:
        assert run(machine_edge, client)['ok']
        edge.clock[0] += 130
        result = run(machine_edge, client)
        assert not result['ok'] and result['retry_safe'] is False
    assert len(seen) == 1


def test_rollout_disabled_after_acceptance_cannot_bypass_the_old_ticket(machine_edge):
    edge, _ = machine_edge
    seen = []
    with worker(machine_edge, seen, lost=True) as client:
        assert run(machine_edge, client)['retry_safe'] is False
        edge.service.config = replace(edge.service.config, native_node_delivery=False)
        assert run(machine_edge, client)['retry_safe'] is False
    assert len(seen) == 1


@pytest.mark.parametrize('key', [True, 'key with spaces', 'x' * 129, '../untrusted'])
def test_malformed_idempotency_keys_never_create_tickets(machine_edge, key):
    edge, _ = machine_edge
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail('No packet for invalid key'))) as client:
        assert run(machine_edge, client, key=key)['error_code'] == 'INVALID_INPUT'
    assert edge.store.query('SELECT COUNT(*) AS n FROM edge_gateway_runs')[0]['n'] == 0


@pytest.mark.parametrize('fault', ['lost', 'foreign'])
def test_uncertain_or_foreign_result_never_becomes_legacy_io(machine_edge, fault):
    seen = []
    with worker(machine_edge, seen, **{fault: True}) as client:
        result = run(machine_edge, client)
        assert result is not None and not result['ok'] and result['retry_safe'] is False
        assert not run(machine_edge, client)['ok']
    assert len(seen) == 1


def test_daily_limit_routes_same_ticket_through_origin_once(machine_edge):
    edge, rid = machine_edge
    edge.service.observe(edge.service.config.soft_limit, edge.clock[0], healthy=True)
    remote = MockRemoteMcp([WEATHER_TOOL])
    edge.front.proxy = McpProxy(edge.store, allow_private=True,
                               http=httpx.Client(transport=remote))
    seen = []
    def origin(request):
        seen.append(request)
        assert request.url.path.startswith('/api/origin-gateway/')
        response = edge.client.post(request.url.path, content=request.content, headers=dict(request.headers))
        return httpx.Response(response.status_code, content=response.content, headers=response.headers)
    with httpx.Client(transport=httpx.MockTransport(origin)) as client:
        result = run(machine_edge, client)
        assert result['ok'] and result['delivery_backend'] == 'origin'
        assert not run(machine_edge, client)['ok']
    assert len(seen) == 1


def test_confirmed_failure_receipt_allows_the_agent_to_consider_an_alternative(machine_edge):
    seen = []
    with worker(machine_edge, seen, rejected=True) as client:
        result = run(machine_edge, client)
    assert not result['ok'] and result['outcome'] == 'failed' and result['retry_safe'] is True
    assert len(seen) == 1


@pytest.mark.parametrize('change', ['rollout', 'secret', 'owned', 'paid'])
def test_non_edge_profiles_keep_existing_authorized_path_before_ticket(machine_edge, change):
    edge, rid = machine_edge
    arguments = {'city': 'Tokyo'}
    if change == 'rollout':
        edge.service.config = replace(edge.service.config, native_node_delivery=False)
    elif change == 'secret':
        arguments['api_key'] = 'synthetic-private-value'
    else:
        with edge.store.tx() as db:
            if change == 'owned':db.execute("UPDATE resources SET source='agentconcierge-owned' WHERE id=?", (rid,))
            else:db.execute('UPDATE resources SET price_usdc=100 WHERE id=?', (rid,))
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail('Unexpected packet'))) as client:
        assert run(machine_edge, client, arguments=arguments) is None
    assert edge.store.query('SELECT COUNT(*) AS n FROM edge_gateway_runs')[0]['n'] == 0


def test_mcp_route_uses_ticket_adapter_and_does_not_repeat_unknown_result(machine_edge, monkeypatch):
    edge, rid = machine_edge
    seen = []
    original = machine.execute
    def adapter(front, resource_id, tool, arguments, **kwargs):
        with worker(machine_edge, seen, lost=True) as client:
            return original(front, resource_id, tool, arguments, http=client, **kwargs)
    monkeypatch.setattr(machine, 'execute', adapter)
    monkeypatch.setattr(edge.front.proxy, 'execute', lambda *a, **k: pytest.fail('Accepted call cannot execute a second time'))
    response = edge.client.post('/mcp', json={'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {
        'name': 'call', 'arguments': {'resource_id': rid, 'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}}}}).json()
    result = response['result']
    assert result['isError'] is True
    assert result['structuredContent']['execution']['retry_safe'] is False
    assert result['structuredContent']['alternative'] is None and len(seen) == 1
