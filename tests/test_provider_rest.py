"""A provider that answers 429 rests for its Retry-After on every path we call it from (11-14, PM 04:5x).

11-13 05:42 the provider of 42798 answered 429 and the Edge handshake, the Origin gateway fallback and the
health check each called it again at once; the caller read our own 503 UNAVAILABLE (edge_http_503).
"""
import email.utils
import json

import httpx
import pytest

from agent_market.provider_rest import BOOK, RestBook, retry_after, MIN_S, MAX_S, DEFAULT_S
from tests.test_edge_gateway import edge, catalog  # noqa: F401 - fixtures
from tests.test_edge_gateway_catalog import enable, bridge, mcp_resource
from tests.test_mcp_proxy import WEATHER_TOOL


def test_retry_after_reads_seconds_and_dates_within_bounds():
    assert retry_after({'retry-after': '120'}) == 120
    assert retry_after({'retry-after': '5'}) == MIN_S
    assert retry_after({'retry-after': '999999'}) == MAX_S
    assert retry_after({}) == DEFAULT_S and retry_after(None) == DEFAULT_S
    assert retry_after({'retry-after': 'soon'}) == DEFAULT_S
    date = email.utils.formatdate(1_000_600, usegmt=True)
    assert retry_after({'retry-after': date}, now=1_000_000) == 600
    assert retry_after(httpx.Headers({'Retry-After': '90'})) == 90


def test_the_book_rests_a_host_until_its_wait_is_over():
    now = [100.0]
    book = RestBook(clock=lambda: now[0])
    assert book.note('https://p.example/mcp', httpx.Response(200)) == 0
    assert book.note('https://p.example/mcp', httpx.Response(429, headers={'Retry-After': '120'})) == 120
    assert book.remaining('https://P.example/other') == 120          # by host, not by path
    assert book.remaining('https://q.example/mcp') == 0
    book.rest('https://p.example/', 30)                              # a shorter wait never cuts a longer one
    now[0] += 119.5
    assert book.remaining('https://p.example/mcp') == 1
    now[0] += 1
    assert book.remaining('https://p.example/mcp') == 0


@pytest.fixture
def limited_mcp(edge, catalog, monkeypatch):
    from agent_market.edge_gateway import mcp_control
    from agent_market.concierge.http_security import bounded_client
    enable(edge, monkeypatch); rid = mcp_resource(edge, catalog)
    with edge.store.tx() as db:
        db.execute('UPDATE resources SET usage_guide=? WHERE id=?', (json.dumps({'protocol_version': '2025-06-18'}), rid))
    seen, answers = [], {}

    def handle(request):
        method = json.loads(request.content)['method']; seen.append(method)
        status = answers.get(method)
        if status == 429:
            return httpx.Response(429, text='<html>rate limited</html>', headers={'Retry-After': '120'})
        if status:
            return httpx.Response(status, text='<html>bad gateway</html>')
        result = {'protocolVersion': '2025-06-18'} if method == 'initialize' else {'tools': [WEATHER_TOOL]}
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': json.loads(request.content).get('id'), 'result': result})

    from agent_market.concierge import traffic
    recorder = traffic.Traffic(root=None)
    monkeypatch.setattr(traffic, 'recorder', lambda: recorder)
    http = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(mcp_control, 'bounded_client', lambda _http, **kw: bounded_client(http, **kw))
    yield edge, rid, seen, answers, recorder
    http.close()


def test_a_429_handshake_answers_the_provider_code_and_is_not_repeated(limited_mcp):
    edge, rid, seen, answers, recorder = limited_mcp
    answers['initialize'] = 429
    call = {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}}
    response = bridge(edge, rid, call)
    assert response.status_code == 502 and response.json()['error_code'] == 'PROVIDER_RATE_LIMITED'
    assert response.headers['retry-after'] == '120'
    assert seen == ['initialize']                       # no Origin fallback, no second handshake
    assert 'edge_fallback|handshake' not in recorder.snapshot()['funnel']
    again = bridge(edge, rid, call, idempotency_key='catalog-test-again')
    assert again.status_code == 502 and again.json()['error_code'] == 'PROVIDER_RATE_LIMITED'
    assert 0 < int(again.headers['retry-after']) <= 120
    assert seen == ['initialize']                       # resting: the provider is not contacted
    with edge.store.tx() as db:
        codes = [r[0] for r in db.execute("SELECT error_code FROM edge_gateway_runs WHERE error_code IS NOT NULL")]
    assert 'PROVIDER_RATE_LIMITED' in codes


def test_an_unusable_handshake_is_a_provider_failure_handed_to_origin(limited_mcp):
    edge, rid, seen, answers, recorder = limited_mcp
    answers['initialize'] = 502
    response = bridge(edge, rid, {'tool': 'get_weather', 'arguments': {'city': 'Tokyo'}})
    assert response.status_code == 200 and response.json() == {'backend': 'origin'}
    assert recorder.snapshot()['funnel'] == {'edge_fallback|handshake': 1}
    assert not BOOK._until                            # a 502 is not a request to wait


def test_the_claim_endpoint_tells_provider_failures_from_our_own(edge, monkeypatch):
    from agent_market.edge_gateway.config import EdgeError
    from agent_market.edge_gateway.mcp_control import provider_failure
    from tests.test_edge_gateway import service_request, ORIGIN
    value = {'access_token': 't', 'origin': ORIGIN, 'run_id': 'er_' + '0' * 32, 'input': {}}
    for error, status, code, wait in ((provider_failure(), 502, 'PROVIDER_UNAVAILABLE', None),
                                      (provider_failure('PROVIDER_RATE_LIMITED', 90), 502, 'PROVIDER_RATE_LIMITED', '90'),
                                      (EdgeError('UNAVAILABLE', 503), 503, 'UNAVAILABLE', None)):
        def refuse(*_args, error=error):
            raise error
        monkeypatch.setattr(edge.service, 'claim', refuse)
        response = service_request(edge, 'claim', value)
        assert (response.status_code, response.json()['error_code']) == (status, code)
        assert response.headers.get('retry-after') == wait


def _proxy_store():
    from agent_market.collector import usage
    from agent_market.gateway.store import Store
    store = Store()
    compact = usage.compact_tools([WEATHER_TOOL])
    rid = store.upsert_resource({
        'key': 'mcp:https://busy.example/mcp', 'source': 'mcp-registry', 'kind': 'mcp', 'url': 'https://busy.example/mcp',
        'name': 'Busy', 'description': 'Live weather', 'category': 'travel_maps_weather', 'networks': [], 'price_usdc': 0,
        'details': {'remotes': [{'type': 'streamable-http', 'url': 'https://busy.example/mcp'}]}})
    store.record_usage(rid, tools=compact, digest=usage.tools_hash(compact), guide={'tools': compact}, changes=None, trial={'ok': True})
    with store.tx() as db:
        db.execute("UPDATE resources SET health_status='healthy' WHERE id=?", (rid,))
    return store, rid


def test_the_origin_proxy_stops_at_a_429_and_rests_the_host():
    from agent_market.concierge.proxy import McpProxy
    store, rid = _proxy_store()
    seen = []

    def handle(request):
        if request.method == 'POST':
            seen.append(json.loads(request.content)['method'])
        return httpx.Response(429, text='<html>rate limited</html>', headers={'Retry-After': '60'})

    proxy = McpProxy(store, allow_private=True, http=httpx.Client(transport=httpx.MockTransport(handle)))
    first = proxy.execute(rid, 'get_weather', {'city': 'Tokyo'})
    assert first['ok'] is False and first['error_code'] == 'RESOURCE_UNAVAILABLE' and first['retry_after'] == 60
    assert seen == ['server/discover']                  # before: discover, then initialize, both 429
    second = proxy.execute(rid, 'get_weather', {'city': 'Tokyo'})
    assert second['error_code'] == 'RESOURCE_UNAVAILABLE' and second['provider_dispatched'] is False
    assert seen == ['server/discover']


def test_health_and_trial_surveys_rest_a_host_that_answered_429():
    from agent_market.collector.health import HealthChecker
    from agent_market.collector.capabilities import CapabilityProber, RateLimited
    from agent_market.gateway.store import Store
    seen = []

    def handle(request):
        seen.append(json.loads(request.content).get('method') if request.method == 'POST' else request.method)
        return httpx.Response(429, text='<html>rate limited</html>', headers={'Retry-After': '45'})

    http = httpx.Client(transport=httpx.MockTransport(handle))
    checker = HealthChecker(Store(), http=http, allow_private=True)
    result = checker.check({'kind': 'mcp', 'url': 'https://busy.example/mcp'}, http)
    assert (result.outcome, result.status_code) == ('reachable', 429)
    assert seen == ['server/discover'] and BOOK.remaining('https://busy.example/mcp') == 45
    resting = checker.check({'kind': 'mcp', 'url': 'https://busy.example/mcp'}, http)
    assert resting.local is True and seen == ['server/discover']       # postponed, not recorded as a failure
    BOOK.clear(); seen.clear()
    with pytest.raises(RateLimited):
        CapabilityProber(Store(), http=http, allow_private=True).probe('https://busy.example/mcp', http)
    assert seen == ['server/discover']                  # no initialize after the 429
