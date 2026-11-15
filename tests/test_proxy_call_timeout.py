"""A caller with a slot deadline passes the time it has left (workflow team request, PM 11-15 10:54)."""
from agent_market.concierge import proxy as proxy_module
from tests.test_managed_agent_gateway import managed, catalog  # noqa: F401 (fixtures)


def read_timeout(request):
    return request.extensions['timeout']['read']


def test_the_limit_is_bounded_and_the_default_stays_fifteen_seconds():
    assert proxy_module.call_timeout(None) is None
    assert proxy_module.call_timeout(3) == 3.0
    assert proxy_module.call_timeout(100) == 15.0
    assert proxy_module.call_timeout(0) == 0.5 and proxy_module.call_timeout(-4) == 0.5
    assert proxy_module._seconds() == 15.0


def test_one_call_waits_at_most_the_time_left_and_the_next_call_is_back_to_default(managed):
    store, front, client, _, rid, calls, remote = managed
    result = front.proxy.execute(rid, 'get_weather', {'city': 'Tokyo'}, timeout=2.5)
    assert result.get('ok'), result
    assert calls and {read_timeout(r) for r in calls} == {2.5}
    assert max(r.extensions['timeout']['connect'] for r in calls) <= 2.5
    calls.clear()
    assert front.proxy.execute(rid, 'get_weather', {'city': 'Tokyo'}).get('ok')
    assert {read_timeout(r) for r in calls} == {15.0}
    assert proxy_module._seconds() == 15.0


def test_the_workflow_engine_hands_its_time_left_to_the_proxy(managed, monkeypatch):
    store, front, client, _, rid, calls, remote = managed
    seen = []
    original = front.proxy.execute

    def recording(*args, **kwargs):
        seen.append(kwargs.get('timeout'))
        return original(*args, **kwargs)

    monkeypatch.setattr(front.proxy, 'execute', recording)
    front.workflows.proxy = front.proxy
    monkeypatch.setattr('agent_market.edge_gateway.native.execute', lambda *a, **kw: None)
    node = {'resource_id': rid, 'kind': 'mcp', 'data': {'tool': 'get_weather'}}
    front.workflows._call_registered(node, {'city': 'Tokyo'}, timeout=4)
    front.workflows._call_registered(node, {'city': 'Tokyo'})
    assert seen == [4, None]
    assert {read_timeout(r) for r in calls} == {4.0, 15.0}
