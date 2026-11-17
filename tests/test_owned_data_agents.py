"""Owned adapters consume controlled source responses, never production fixtures."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.execution_policy import safe_registered_tool, supported_schema
from agent_market.owned_data_agents import DataAgents, DataUnavailable, create_app
from agent_market.owned_data_agents.catalog import SPECS, tool_spec
from agent_market.owned_data_agents.service import PREFIX
from agent_market.owned_data_agents.staging import bundle
from agent_market.owned_data_agents.verification import isolated_world, wait


def source(request):
    host = request.url.host
    if host == 'api.gdeltproject.org':          # the hourly technology bundle (PM 11-16)
        return httpx.Response(200, json={'articles': [
            {'url': 'https://techcrunch.com/2026/10/19/ai', 'title': '<b>Artificial intelligence</b> agents ship',
             'domain': 'techcrunch.com', 'seendate': '20261019T020000Z', 'language': 'English'},
            {'url': 'https://arstechnica.com/2026/10/19/qc', 'title': 'Quantum computing milestone',
             'domain': 'arstechnica.com', 'seendate': '20261019T010000Z', 'language': 'English'},
            {'url': 'https://general-news.example/story', 'title': 'Artificial intelligence elsewhere',
             'domain': 'general-news.example', 'seendate': '20261019T030000Z', 'language': 'English'}]},
            headers={'Content-Type': 'application/json'})
    if host == 'api.crossref.org':
        query = request.url.params['query.bibliographic']
        return httpx.Response(200, json={'message': {'items': [{'DOI': '10.1234/source',
            'title': [query + ' research'], 'published': {'date-parts': [[2025, 3]]},
            'publisher': 'Public research publisher'}]}})
    if host == 'api.worldbank.org' and '/indicator/' not in request.url.path:
        code = request.url.path.rsplit('/', 1)[-1].upper()
        return httpx.Response(200, json=[{'total': 1}, [{'iso2Code': code, 'name': 'Country ' + code,
            'capitalCity': 'Capital ' + code, 'region': {'id': 'NAC', 'value': 'Public region'},
            'incomeLevel': {'value': 'Public classification'}}]])
    if host == 'api.worldbank.org':
        code, indicator = request.url.path.split('/')[3], request.url.path.split('/')[-1]
        return httpx.Response(200, json=[{'total': 2}, [
            {'country': {'id': code.upper()}, 'indicator': {'id': indicator}, 'date': '2025',
             'value': 100 if code == 'us' else 200},
            {'country': {'id': code.upper()}, 'indicator': {'id': indicator}, 'date': '2024', 'value': None}]])
    if host == 'registry.npmjs.org':
        package = request.url.path[1:].rsplit('/', 1)[0]
        return httpx.Response(200, json={'name': package, 'version': '1.2.3' if package == 'express' else '4.5.6',
            'description': 'Public package description', 'license': 'MIT',
            'author': {'email': 'not-for-publication@example.invalid'}, 'scripts': {'install': 'never-execute'}})
    if host == 'api.osv.dev':
        arguments = json.loads(request.content)
        return httpx.Response(200, json={'vulns': [{'id': 'OSV-2026-TEST',
            'summary': arguments['package']['name'] + '@' + arguments['version'], 'modified': '2026-10-01T00:00:00Z'}]})
    if host == 'api.github.com':
        query = request.url.params['q']
        return httpx.Response(200, json={'total_count': 1, 'incomplete_results': False, 'items': [{
            'html_url': 'https://github.com/example/project/issues/7', 'repository_url': 'https://api.github.com/repos/example/project',
            'number': 7, 'title': query.split(' repo:')[0] + ' issue', 'state': 'open', 'updated_at': '2026-10-20T00:00:00Z',
            'comments': 2, 'labels': [{'name': 'bug'}], 'user': {'login': 'not-for-publication'}, 'body': 'omitted'}]})
    raise AssertionError('Unexpected source destination')


@pytest.fixture
def engine():
    from agent_market.owned_data_agents.source_limits import GITHUB_SEARCH
    GITHUB_SEARCH.sent.clear(); GITHUB_SEARCH.blocked_until = 0.  # the process-wide window is not test state
    requests, state = [], {'fail': False, 'time': 1000.0}
    def handle(request):
        requests.append(request)
        if state['fail']:
            raise httpx.ReadTimeout('Must not expose /private/config token=secret', request=request)
        return source(request)
    http = httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)
    core = DataAgents(http=http, clock=lambda: state['time'],
                      utc_now=lambda: datetime(2026, 10, 20, tzinfo=timezone.utc))
    from agent_market.owned_data_agents.tech_news import Store
    core.news = Store(core._gdelt_bundle, clock=lambda: state['time'], utc_now=lambda: core.utc_now(), background=False)
    yield core, requests, state
    http.close()


@pytest.mark.parametrize('identity', list(SPECS))
def test_all_six_tools_execute_their_source_and_use_gateway_supported_schemas(engine, identity):
    core, requests, _ = engine
    spec = tool_spec(identity)
    assert safe_registered_tool(spec)
    supported_schema(spec)
    supported_schema({'inputSchema': spec['outputSchema']})
    output = core.execute(identity, SPECS[identity]['example'])
    assert output['agent'] == identity and output['cache']['status'] == 'live'
    assert output['source']['url'].startswith('https://') and len(requests) == 1
    assert 'not-for-publication' not in json.dumps(output) and 'never-execute' not in json.dumps(output)
    assert not requests[0].headers.get('authorization') and not requests[0].headers.get('cookie')


@pytest.mark.parametrize('identity,args', [
    ('technology-news', {'query': 'https://127.0.0.1/private', 'limit': 1}),
    ('technology-news', {'query': 'Bearer private', 'limit': 1}),
    ('research-papers', {'query': 'private@example.invalid', 'limit': 1}),
    ('research-papers', {'query': '/Users/private/key', 'limit': 1}),
    ('research-papers', {'query': '<script>bad</script>', 'limit': 1}),
    ('country-profile', {'country_code': '..'}),
    ('country-profile', {'country_code': 'us'}),
    ('package-metadata', {'package': '../private'}),
    ('package-metadata', {'package': 'https://internal.invalid'}),
    ('package-advisories', {'package': 'express', 'version': 'latest', 'limit': 1}),
    ('economic-indicators', {'country_code': 'US', 'indicator': '../../private', 'limit': 1}),
    ('technology-news', {'query': 'public words', 'limit': True}),
    ('technology-news', {'query': 'public words', 'limit': 999}),
    ('technology-news', {'query': 'public words', 'limit': 1, 'url': 'http://169.254.169.254'}),
])
def test_invalid_or_private_inputs_are_rejected_before_source_dispatch(engine, identity, args):
    core, requests, _ = engine
    with pytest.raises(ValueError):
        core.execute(identity, args)
    assert not requests


def test_cache_age_is_truthful_stale_is_bounded_and_failures_do_not_hammer_source(engine):
    core, calls, state = engine
    args = {'query': 'public research', 'limit': 2}   # research-papers: ttl 300, max_stale 3600 (news is a bundle now)
    original = core.execute('research-papers', args)
    state['time'] += 30
    cached = core.execute('research-papers', args)
    assert cached['retrieved_at'] == original['retrieved_at'] and cached['cache'] == {'status': 'fresh_cache', 'age_seconds': 30}
    state.update(fail=True, time=1301.0)
    stale = core.execute('research-papers', args)
    assert stale['retrieved_at'] == original['retrieved_at'] and stale['cache'] == {'status': 'stale_cache', 'age_seconds': 301}
    assert len(calls) == 2
    core.execute('research-papers', args)
    assert len(calls) == 2
    state['time'] = 1000 + 3601
    with pytest.raises(DataUnavailable):
        core.execute('research-papers', args)
    assert len(calls) == 3


def test_source_failure_without_cached_data_never_generates_a_success(engine):
    core, calls, state = engine
    state['fail'] = True
    for _ in range(3):
        with pytest.raises(DataUnavailable):
            core.execute('country-profile', {'country_code': 'US'})
    assert len(calls) == 1 and not core.entries


@pytest.mark.parametrize('method,url', [
    ('GET', 'http://api.worldbank.org/v2/country/us'),
    ('GET', 'https://api.worldbank.org:8443/v2/country/us'),
    ('GET', 'https://private:secret@api.worldbank.org/v2/country/us'),
    ('POST', 'https://registry.npmjs.org/express/latest'),
    ('GET', 'https://127.0.0.1/private'),
])
def test_source_transport_cannot_change_origin_method_tls_or_credentials(engine, method, url):
    core, calls, _ = engine
    with pytest.raises(DataUnavailable):
        core._request(method, url)
    assert not calls


def test_http_quota_enforces_retry_after_without_touching_sources(engine, monkeypatch):
    from agent_market.broker.server import RateLimiter
    from agent_market.owned_data_agents import service
    monkeypatch.setattr(service, 'RateLimiter', lambda _: RateLimiter(2))
    core, calls, _ = engine
    with TestClient(create_app(enabled=True, engine=core)) as client:
        codes = [rpc(client, 'technology-news', 'tools/list').status_code for _ in range(3)]
        denied = rpc(client, 'technology-news', 'tools/list')
    assert codes == [200, 200, 429] and denied.status_code == 429
    assert denied.headers['retry-after'] == '60' and not calls


def test_parallel_identical_requests_share_one_source_fetch(engine):
    core, calls, _ = engine
    barrier = threading.Barrier(6)
    def fetch(_):
        barrier.wait()
        return core.execute('package-metadata', {'package': 'express'})
    with ThreadPoolExecutor(max_workers=6) as pool:
        outputs = list(pool.map(fetch, range(6)))
    assert len(calls) == 1
    assert sum(row['cache']['status'] == 'live' for row in outputs) == 1


@pytest.mark.parametrize('response', [
    httpx.Response(302, headers={'Location': 'http://127.0.0.1/private'}),
    httpx.Response(200, content=b'{"message":{},"message":{}}', headers={'Content-Type': 'application/json'}),
    httpx.Response(200, content=b'{"message":NaN}', headers={'Content-Type': 'application/json'}),
    httpx.Response(200, content=b'x' * 524289, headers={'Content-Type': 'application/json'}),
    httpx.Response(200, text='<html>private diagnostics</html>'),
    httpx.Response(429, json={'internal': 'must-not-leak'}),
])
def test_redirect_malformed_duplicate_nonfinite_large_and_rate_limited_sources_fail_closed(response):
    calls = []
    def handle(request):
        calls.append(str(request.url))
        return response
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        core = DataAgents(http=http)
        with pytest.raises(DataUnavailable):
            core.execute('research-papers', {'query': 'public research', 'limit': 1})
    assert len(calls) == 1


def test_empty_osv_result_is_a_scoped_lookup_not_a_security_guarantee():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))) as http:
        result = DataAgents(http=http).execute('package-advisories', SPECS['package-advisories']['example'])
    assert result['data']['returned_matches'] == 0 and result['data']['items'] == []
    assert 'not a security guarantee' in result['data']['scope']


def rpc(client, identity, method='tools/call', params=None):
    return client.post(PREFIX + '/' + identity + '/mcp', json={
        'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})


def test_transport_is_disabled_by_default_and_staging_has_no_implicit_apply():
    with TestClient(create_app()) as client:
        assert rpc(client, 'technology-news', 'tools/list').status_code == 404
    staged = bundle()
    assert not staged['applied'] and staged['requires_explicit_activation']
    assert len(staged['agents']) == 7 and len(staged['testbench_recipes']) == 5 and len(staged['workflow_templates']) == 3
    assert all('agent_market.owned_data_agents' not in Path(path).read_text() for path in (
        'agent_market/concierge/front.py', 'agent_market/gateway/server.py'))
    for path in Path('agent_market/owned_data_agents').glob('*.py'):
        assert not re.search(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]', path.read_text())


@pytest.mark.parametrize('raw', [
    b'{"jsonrpc":"2.0","id":1,"method":"tools/list","id":2}',
    b'{"jsonrpc":"2.0","id":true,"method":"tools/list"}',
    b'[]', b'x' * 8193, b'{"jsonrpc":"2.0","method":"tools/list"}',
])
def test_http_protocol_rejects_invalid_requests_without_source_contact(engine, raw):
    core, calls, _ = engine
    with TestClient(create_app(enabled=True, engine=core)) as client:
        response = client.post(PREFIX + '/technology-news/mcp', content=raw)
        assert response.status_code == 200 and response.json()['error']['code'] == -32602
        assert 'no-store' in response.headers['cache-control']
    assert not calls


def test_protocol_methods_and_upstream_failure_do_not_leak_private_diagnostics(engine):
    core, calls, state = engine
    with TestClient(create_app(enabled=True, engine=core)) as client:
        assert rpc(client, 'missing', 'tools/list').status_code == 404
        assert rpc(client, 'technology-news', 'tools/list').json()['result']['tools'][0] == tool_spec('technology-news')
        assert rpc(client, 'technology-news', 'resources/read').json()['error']['code'] == -32601
        assert not calls
        state['fail'] = True
        reply = rpc(client, 'technology-news', params={'name': SPECS['technology-news']['tool'],
            'arguments': SPECS['technology-news']['example']})
        assert reply.json()['result']['isError']
        assert all(value not in reply.text for value in ('/private/', 'token=', 'Traceback', 'ReadTimeout'))


def test_all_three_existing_runtime_graphs_pass_actual_prior_outputs_and_inputs_change_results(tmp_path, engine):
    core, calls, _ = engine
    with isolated_world(tmp_path / 'isolated', engine=core) as world:
        for workflow in world.workflows:
            run = wait(world.runtime, world.runtime.submit(workflow, source='verification', public=True))
            assert run['status'] == 'succeeded', run
            assert [node['status'] for node in run['node_results']] == ['succeeded'] * 3
        inputs = {row['path'].split('/')[-2]: row['params']['arguments']
                  for row in world.requests if row['method'] == 'tools/call'}
        assert inputs['research-papers']['query'] == inputs['technology-news']['query']
        assert inputs['economic-indicators']['country_code'] == 'US'
        assert inputs['package-advisories']['version'] == '1.2.3'
        for workflow, change, expected in (
                (world.workflows[0], {'query': 'quantum computing', 'limit': 2}, ('query', 'quantum computing')),
                (world.workflows[1], {'country_code': 'GB'}, ('country_code', 'GB')),
                (world.workflows[2], {'package': 'lodash'}, ('version', '4.5.6'))):
            workflow['nodes'][1]['data']['input'] = change
            world.store.update_workflow(workflow['id'], {'nodes': workflow['nodes'], 'edges': workflow['edges']})
            run = wait(world.runtime, world.runtime.submit(world.store.get_workflow(workflow['id']), source='verification', public=True))
            assert run['status'] == 'succeeded', run
            assert run['node_results'][2]['input'][expected[0]] == expected[1]
        assert len(calls) == 11     # the second news query is answered from the same hourly bundle (PM 11-16)


def test_osv_records_carry_their_database_and_noncommercial_sources_are_dropped():
    body = {'vulns': [{'id': 'GHSA-35jh-r3h4-6jhm', 'summary': 'Command Injection in lodash', 'modified': '2024-01-02T00:00:00Z'},
                      {'id': 'CGA-abcd-1234-efgh', 'summary': 'Chainguard record', 'modified': '2024-01-03T00:00:00Z'},
                      {'id': 'MAL-2024-1', 'summary': 'Malicious package', 'modified': '2024-01-01T00:00:00Z'}]}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as http:
        data = DataAgents(http=http).execute('package-advisories', {'package': 'lodash', 'version': '4.17.20', 'limit': 5})['data']
    assert [(i['id'], i['source']) for i in data['items']] == [
        ('GHSA-35jh-r3h4-6jhm', 'GitHub Advisory Database (CC BY 4.0)'), ('MAL-2024-1', 'OpenSSF Malicious Packages (Apache-2.0)')]
    assert data['excluded_matches'] == 1 and data['returned_matches'] == 2 and data['partial'] is True
    assert 'license allows reuse' in data['scope']


def news_store(tmp_path, fetch, now=1_800_000_000.0):
    from agent_market.owned_data_agents.tech_news import Store
    state = {'now': now}
    store = Store(fetch, tmp_path / 'bundle.json', clock=lambda: state['now'],
                  utc_now=lambda: datetime(2026, 10, 20, tzinfo=timezone.utc), background=False)
    return store, state


def gdelt_page(*rows):
    return {'articles': [{'url': u, 'title': t, 'domain': d, 'seendate': s, 'language': 'English'} for u, t, d, s in rows]}


def test_technology_news_answers_from_the_hourly_bundle_without_calling_gdelt_per_request(tmp_path):
    """PM 11-16: GDELT is read at most once an hour into a bundle (technology outlets only, titles and links); requests
    filter the bundle locally and state when it was collected; no article page is ever requested."""
    calls = []
    def fetch():
        calls.append(1)
        return gdelt_page(('https://techcrunch.com/a', 'Quantum computing startup raises money', 'techcrunch.com', '20261019T120000Z'),
                          ('https://www.theverge.com/b', 'New phone review', 'theverge.com', '20261019T110000Z'),
                          ('https://general-news.example/c', 'Quantum computing in politics', 'general-news.example', '20261019T100000Z'))
    store, state = news_store(tmp_path, fetch)
    core = DataAgents(http=httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail('no request'))), news_store=store)
    out = core.execute('technology-news', {'query': 'quantum computing', 'limit': 3})
    assert out['data'] == {'query': 'quantum computing', 'partial': False, 'items': [
        {'title': 'Quantum computing startup raises money', 'url': 'https://techcrunch.com/a',
         'published_at': '2026-10-19T12:00:00Z', 'source': 'techcrunch.com'}]}           # the non-tech outlet is never kept
    assert out['retrieved_at'] == '2026-10-20T00:00:00Z' and out['cache'] == {'status': 'live', 'age_seconds': 0}
    for _ in range(20):                                            # repeated Test clicks: still one GDELT call
        core.execute('technology-news', {'query': 'phone', 'limit': 2})
    assert len(calls) == 1
    other = core.execute('technology-news', {'query': 'nothing matches this', 'limit': 2})
    assert other['data']['partial'] is True and 'latest technology news' in other['data']['note']
    assert [r['url'] for r in other['data']['items']] == ['https://techcrunch.com/a', 'https://www.theverge.com/b']


def test_technology_news_bundle_refresh_staleness_and_failure(tmp_path):
    """Refresh after an hour; a failed refresh keeps the bundle up to 6 hours (stated as stale); past that, busy."""
    pages = [gdelt_page(('https://wired.com/x', 'Chip news', 'wired.com', '20261019T000000Z'))]
    def fetch():
        if not pages:
            raise RuntimeError('GDELT 429')
        return pages.pop(0)
    store, state = news_store(tmp_path, fetch)
    store.refresh_soon()
    core = DataAgents(news_store=store)
    state['now'] += 3700                                           # older than an hour: a refresh is tried and fails
    out = core.execute('technology-news', {'query': 'chip', 'limit': 1})
    assert out['cache'] == {'status': 'stale_cache', 'age_seconds': 3700} and out['data']['items'][0]['url'] == 'https://wired.com/x'
    state['now'] += 21600 - 3700 + 1                               # past 6 hours
    with pytest.raises(DataUnavailable, match='busy'):
        core.execute('technology-news', {'query': 'chip', 'limit': 1})


def test_gdelt_bundle_request_is_one_call_counted_in_the_ledger(monkeypatch):
    """The background refresh is one GDELT call (technology outlets, newest 250, titles only) reserved in the shared
    ledger; plain-text refusals from GDELT are failures, never data."""
    from agent_market import provider_budget
    from agent_market.owned_data_agents.tech_news import TECH_OUTLETS, URL
    reserved, seen = [], []
    monkeypatch.setattr(provider_budget, 'live_reserve', lambda url, *a, **k: reserved.append(url) or (True, 'ok'))
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=gdelt_page(('https://zdnet.com/z', 'Cloud outage', 'zdnet.com', '20261019T000000Z')))
    core = DataAgents(http=httpx.Client(transport=httpx.MockTransport(handle)))
    raw = core._gdelt_bundle()
    assert len(seen) == 1 and str(seen[0].url).startswith(URL) and reserved == [URL]
    query = seen[0].url.params['query']
    assert all('domainis:' + d in query for d in TECH_OUTLETS) and seen[0].url.params['maxrecords'] == '250'
    assert raw['articles'][0]['domain'] == 'zdnet.com'
    refused = DataAgents(http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='Please limit requests'))))
    with pytest.raises(DataUnavailable):
        refused._gdelt_bundle()


def test_a_gdelt_429_pauses_the_domain_for_the_day_and_later_refreshes_do_not_call(monkeypatch):
    from agent_market.owned_data_agents.source_limits import SourceBusy
    """GDELT's own 429 pauses gdeltproject.org in the shared ledger (provider evidence), so no refresh calls it again
    that day; the request answers busy instead of waiting."""
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(429, text='Please limit requests to one every 5 seconds')
    core = DataAgents(http=httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(DataUnavailable):
        core._gdelt_bundle()
    with pytest.raises(SourceBusy):
        core._gdelt_bundle()
    assert len(seen) == 1


def test_a_gdelt_429_passes_its_retry_after_to_the_ledger(monkeypatch):
    """The ledger keeps the provider's own wait (Retry-After, seconds or HTTP-date; ops C16)."""
    from agent_market import provider_budget
    noted = []
    monkeypatch.setattr(provider_budget, 'note', lambda *a, **k: noted.append((a, k)))
    core = DataAgents(http=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(429, headers={'Retry-After': '7200'}, text='Please limit requests'))))
    with pytest.raises(DataUnavailable):
        core._gdelt_bundle()
    (args, kwargs), = noted
    assert args[2] == 429 and kwargs['evidence'] == {'origin': provider_budget.PROVIDER_HTTP, 'retry_after': '7200'}


def test_ttl_and_terms_for_gdelt_news():
    from agent_market.owned_data_agents.source_terms import LICENSES, SUSPENDED
    from agent_market.owned_data_agents.tech_news import MAX_STALE, TTL
    assert (TTL, MAX_STALE) == (3600, 21600)
    assert 'gdeltproject.org' in LICENSES['technology-news'] and 'technology-news' not in SUSPENDED


def test_technology_news_is_busy_when_nothing_is_stored_and_the_refresh_fails(tmp_path):
    """No bundle yet and GDELT refuses: 'busy, try again later', never an empty success or invented items."""
    def fetch():
        raise RuntimeError('GDELT 429')
    store, _ = news_store(tmp_path, fetch)
    with pytest.raises(DataUnavailable, match='busy'):
        DataAgents(news_store=store).execute('technology-news', {'query': 'anything here', 'limit': 2})



def test_research_papers_asks_most_cited_first_and_puts_title_matches_ahead(engine):
    """PM 11-17: topic key papers are the most cited ones (holdout-r3 premeasure 3/19 by relevance, 13/19 after)."""
    core, calls, state = engine
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'message': {'items': [
            {'DOI': '10.1000/a', 'title': ['A famous paper that mentions gene in passing'], 'publisher': 'P',
             'published': {'date-parts': [[2001, 1, 1]]}, 'is-referenced-by-count': 9000},
            {'DOI': '10.1000/b', 'title': ['Gene therapy: the review'], 'publisher': 'P',
             'published': {'date-parts': [[2010, 1, 1]]}, 'is-referenced-by-count': 800}]}})
    core.http = httpx.Client(transport=httpx.MockTransport(handler))
    out = core.execute('research-papers', {'query': 'gene therapy', 'limit': 2})
    params = seen[0].url.params
    assert params['sort'] == 'is-referenced-by-count' and params['order'] == 'desc' and params['rows'] == '40'
    assert [i['doi'] for i in out['data']['items']] == ['10.1000/b', '10.1000/a'] and out['data']['partial'] is False



def test_research_papers_never_answers_with_papers_that_miss_the_topic(engine):
    """PM 11-17: no title holds the topic words among the most-cited matches -> no papers, partial, a note."""
    core, calls, state = engine
    core.http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'message': {'items': [
        {'DOI': '10.1000/x', 'title': ['Mini-mental state'], 'is-referenced-by-count': 90000}]}})))
    out = core.execute('research-papers', {'query': 'solid-state battery', 'limit': 3})
    assert out['data'] == {'query': 'solid-state battery', 'items': [], 'partial': True,
                           'note': 'No highly cited paper with the topic words in its title was found.'}
