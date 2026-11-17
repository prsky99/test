"""Technical Documentation (QA 19), kept outside the research/news digest. MDN only since PM 11-15 17:02: Context7's
Addendum allows internal development, educational and evaluation use only, so it is never called."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import httpx
import pytest

from agent_market.capability_contracts import validate
from agent_market.owned_data_agents import docs
from agent_market.owned_data_agents.engine import DataUnavailable

NOW = datetime(2026, 10, 31, 8, 0, tzinfo=timezone.utc)


def agent(handler, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    return docs.DocsAgent(http=http, utc_now=lambda: NOW, **kwargs), http


def mdn(request):
    assert request.url.host == 'developer.mozilla.org' and request.url.params['q'] == 'CSS grid layout'
    return httpx.Response(200, json={'documents': [
        {'mdn_url': '/en-US/docs/Web/CSS/Guides/Grid_layout', 'title': 'CSS grid layout', 'summary': 'A two-dimensional grid.'},
        {'mdn_url': 'https://evil.example/x', 'title': 'Off-site', 'summary': 'dropped'}]})


def context7(calls):
    """Context7 is no longer called (PM 11-15): any request to it is recorded and fails."""
    def handle(request):
        calls.append(request.url.host + request.url.path)
        return httpx.Response(500)
    return handle


def test_web_topics_use_mdn_and_keep_only_mdn_links():
    core, http = agent(mdn)
    with http:
        data = core.execute({'query': 'CSS grid layout', 'limit': 3})['data']
    assert data['source'] == 'MDN Web Docs'
    assert [item['url'] for item in data['items']] == ['https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Grid_layout']


def test_every_topic_goes_to_mdn_and_context7_is_never_called():
    calls = []
    def handle(request):
        calls.append(request.url.host)
        return httpx.Response(200, json={'documents': [
            {'mdn_url': '/en-US/docs/Web/API/AbortController', 'title': 'AbortController', 'summary': 'Aborts.'}]})
    core, http = agent(handle)
    with http:
        out = core.execute({'query': 'Kubernetes deployment rollout', 'limit': 3})
    assert calls == ['developer.mozilla.org'] and out['data']['source'] == 'MDN Web Docs'
    assert out['source'] == {'name': 'MDN Web Docs by Mozilla Contributors, CC BY-SA 2.5',
                             'url': 'https://developer.mozilla.org/'}
    assert not hasattr(docs, 'official_library') and not hasattr(docs.DocsAgent, '_context7')
    with pytest.raises(DataUnavailable):
        core._get('context7.com', '/api/v1/search', {'query': 'x'})


def test_private_text_is_rejected_before_networking():
    core, http = agent(lambda request: pytest.fail('no network'))
    with http:
        for query in ('token=abc123 docs', 'see https://example.com', 'mail me@example.com'):
            with pytest.raises(ValueError):
                core.execute({'query': query, 'limit': 1})


def resource():
    tool = docs.tool_spec()
    return {'id': 7, 'key': docs.KEY, 'source': 'agentconcierge-owned', 'kind': 'mcp',
            'url': 'https://agentconcierge.biz/api/owned-data-agents/technical-docs/mcp',
            'usage_full_tools': json.dumps([tool])}


def test_adapter_projects_into_docs_contract():
    from agent_market import capability_adapter_dispatch as adapters
    from agent_market.docs_capability_adapter import PROFILE
    res = resource()
    current = adapters.profile(res, 'docs.search.v1', 'search_technical_docs')
    assert current['id'] == PROFILE
    supplied = {'query': 'Kubernetes deployment rollout', 'language': 'en', 'limit': 2}
    assert adapters.arguments(res, 'docs.search.v1', 'search_technical_docs', supplied, expected=current) == \
        {'query': 'Kubernetes deployment rollout', 'limit': 2}
    retrieved = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    output = {'agent': docs.ID, 'source': {'name': docs.SPEC['source_name'], 'url': 'https://developer.mozilla.org/'},
              'retrieved_at': retrieved, 'cache': {'status': 'live', 'age_seconds': 0},
              'data': {'query': supplied['query'], 'source': 'MDN Web Docs', 'partial': False, 'items': [
                  {'title': 'AbortController', 'url': 'https://developer.mozilla.org/en-US/docs/Web/API/AbortController',
                   'summary': 'Aborts requests.', 'library': 'MDN Web Docs', 'indexed_at': ''},
                  {'title': 'Second', 'url': 'https://developer.mozilla.org/en-US/docs/Web/b', 'summary': '',
                   'library': 'MDN Web Docs', 'indexed_at': ''}]}}
    value = adapters.normalize(res, 'docs.search.v1', 'search_technical_docs', supplied, output, expected=current)
    validate('docs.search.v1', supplied, value)
    assert value['items'][0]['version'] == 'Current MDN Web Docs page'
    assert value['items'][1]['excerpt'] == 'Documentation page from MDN Web Docs.'
    assert 'Context7' not in current['input_notice'] and 'CC BY-SA 2.5' in current['input_notice']
    with pytest.raises(ValueError):
        adapters.arguments(res, 'docs.search.v1', 'search_technical_docs', supplied, expected={**current, 'implementation_hash': 'x'})


def test_research_and_news_digest_is_unchanged():
    """Saved workflows pin this digest; adding Technical Documentation must not move it.

    11-14 (948d26df): the package-advisories (OSV) path now names each record's database and license and drops
    non-commercial databases. That moved this digest because engine.py and catalog.py are hashed whole; the
    research-papers and technology-news tool specs and code paths are unchanged (same schema digests), so saved
    research and news digests keep their contracts and need only ``scripts.approve_model_contracts`` after the
    frontend deploy.

    11-16 (PM, Hacker News terms): technology-news reads a stored hourly GDELT bundle (tech_news.py); the description,
    source and an optional output 'note' changed, so this digest moved again and the news contract is re-approved with
    ``scripts.approve_model_contracts --only`` for the technology-news resource after the frontend deploy (moved once
    more the same night when the GDELT 429 began passing Retry-After to the ledger)."""
    from agent_market import owned_capability_adapter
    # 11-17 (PM): research-papers asks Crossref most cited first and puts title matches ahead (topic papers seat)
    assert owned_capability_adapter.IMPLEMENTATION == '60196ba5ae0fd262a0e52ef9db9f36e0899345fcc829990b16cd3bec65199bec'


def test_documentation_objectives_use_the_docs_agent_and_research_keeps_papers():
    from agent_market.workspace_app_factory import AppFactory
    keys = {1: 'mcp:app.openkrill/papers', 2: 'agentconcierge-owned:research-papers', 3: docs.KEY, 4: 'news'}
    factory = AppFactory.__new__(AppFactory)
    factory.store = SimpleNamespace(resource=lambda rid: {'key': keys[rid]})
    candidates = [{'resource_id': rid, 'contract_id': 'docs.search.v1'} for rid in (1, 2, 3)] + \
        [{'resource_id': 4, 'contract_id': 'news.search.v1'}]
    ids = lambda objective: [item['resource_id'] for item in factory._route_docs(objective, candidates)]
    assert ids('Find Kubernetes documentation then Docker documentation') == [3, 4]
    assert ids('Find recent research papers about battery recycling') == [1, 2, 4]
    assert ids('Find recent AI news') == [1, 2, 4]
    assert ids('Find research papers and the reference documentation for PyTorch') == [1, 2, 3, 4]


def test_mcp_route_serves_the_docs_tool(monkeypatch):
    from fastapi.testclient import TestClient
    from agent_market.owned_data_agents.service import create_app
    calls = []
    monkeypatch.setattr(docs, 'engine', lambda: SimpleNamespace(execute=lambda arguments: calls.append(arguments) or {
        'agent': docs.ID, 'source': {'name': docs.SPEC['source_name'], 'url': 'https://developer.mozilla.org/'},
        'retrieved_at': '2026-10-31T08:00:00Z', 'cache': {'status': 'live', 'age_seconds': 0},
        'data': {'query': arguments['query'], 'source': 'MDN Web Docs', 'items': [], 'partial': False}}))
    with TestClient(create_app(enabled=True)) as client:
        path = '/api/owned-data-agents/technical-docs/mcp'
        listed = client.post(path, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}).json()
        assert listed['result']['tools'] == [docs.tool_spec()]
        called = client.post(path, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
            'name': 'search_technical_docs', 'arguments': {'query': 'CSS grid', 'limit': 1}}}).json()
        assert called['result']['structuredContent']['agent'] == docs.ID and calls == [{'query': 'CSS grid', 'limit': 1}]
        assert client.post('/api/owned-data-agents/no-such/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list', 'params': {}}).status_code == 404


def test_local_execution_refuses_a_changed_registration():
    store = SimpleNamespace(resource=lambda rid: {'active': True})
    result = docs.execute_local(store, resource(), 'search_technical_docs', {'query': 'CSS grid', 'limit': 1}, None)
    assert result == {'ok': False, 'error_code': 'SCHEMA_CHANGED', 'error': 'The registered capability needs review.'}


from tests.test_owned_data_agents import engine  # noqa: F401,E402
from tests.test_customer_typed_authoring import customer_flow, typed_release_world, typed_world, routing  # noqa: F401,E402


def test_saved_documentation_workflow_runs_through_local_execution(customer_flow, monkeypatch):  # noqa: F811
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from agent_market.capability_contracts import run_test
    from agent_market.capability_registry import Registry
    from agent_market.owned_data_agents.activation import install
    from agent_market.workspace_app_factory import NOTICE
    from agent_market.workspace_typed_flows import NOTICE as RUN_NOTICE
    from tests.test_customer_ten_workflows import definition
    x = customer_flow; calls = []; docs_site = context7(calls)
    core, http = agent(lambda request: httpx.Response(200, json={'documents': [{'mdn_url': '/en-US/docs/Web/API/AbortController',
        'title': 'AbortController', 'summary': 'Aborts requests.'}]}) if request.url.host == 'developer.mozilla.org' else docs_site(request))
    core.utc_now = lambda: datetime.now(timezone.utc)
    monkeypatch.setattr(docs, 'engine', lambda: core)
    install(x.w.store, 'https://agentconcierge.biz')
    rid = x.w.store.query('SELECT id FROM resources WHERE key=?', (docs.KEY,))[0]['id']
    assert docs.check_source(x.w.store, rid) and x.w.store.resource(rid)['health_status'] == 'healthy'
    resource = x.w.store.resource(rid); registry = Registry(x.w.store)
    registry.approve(resource, 'docs.search.v1', 'search_technical_docs')

    async def runner(identity, **kwargs):
        result = x.w.rt.proxy.execute(identity, kwargs['tool'], kwargs['arguments'], public=True)
        return {'execution_succeeded': result.get('ok') is True, 'simulated': False, 'output': result.get('result')}
    with ThreadPoolExecutor(1) as pool:
        checked = pool.submit(lambda: asyncio.run(run_test(registry, resource, 'docs.search.v1',
            {'query': 'Kubernetes deployment rollout', 'language': 'en', 'limit': 1}, runner))).result(timeout=5)
    assert checked['ok'], checked
    graph = definition([rid, rid], 'Kubernetes deployment rollout', 2)
    for node in graph['nodes']:
        node['contract_id'] = 'docs.search.v1'
    body = {'name': 'Kubernetes documentation', 'definition': graph, 'base_flow_id': None, 'base_revision': None}
    review = x.core.factory.prepare_plan(x.ws, body, x.actor)
    flow = x.core.factory.commit(x.ws, {'review_id': review['review_id'], 'authorized': True, 'notice': NOTICE}, x.actor)
    ticket = x.core.typed.prepare(x.ws, flow['id'], {'revision': 1}, x.actor)
    run = x.core.typed.execute(x.ws, flow['id'], {'ticket_id': ticket['ticket_id'], 'authorized': True, 'notice': RUN_NOTICE}, x.actor)['run']
    http.close()
    assert run['status'] == 'succeeded', [(s.get('status'), s.get('error_code'), s.get('error'), s.get('input')) for s in run['steps']]
    first = run['steps'][0]['output']['items'][0]
    assert first['url'] == 'https://developer.mozilla.org/en-US/docs/Web/API/AbortController'
    assert first['version'] == 'Current MDN Web Docs page' and calls == []   # Context7 never called


def test_reverifier_keeps_docs_execution_evidence_current(customer_flow, monkeypatch):  # noqa: F811
    """The approval-driven contract loop, not _refresh_owned (SPECS only), keeps docs evidence current."""
    import time as clock
    from agent_market.capability_registry import Registry
    from agent_market.model_contract_reverify import ContractReverifier, INTERVAL
    from agent_market.owned_data_agents.activation import install
    x = customer_flow; calls = []; docs_site = context7(calls)
    core, http = agent(lambda request: httpx.Response(200, json={'documents': []}) if request.url.host == 'developer.mozilla.org' else docs_site(request))
    core.utc_now = lambda: datetime.now(timezone.utc)
    monkeypatch.setattr(docs, 'engine', lambda: core)
    install(x.w.store, 'https://agentconcierge.biz')
    rid = x.w.store.query('SELECT id FROM resources WHERE key=?', (docs.KEY,))[0]['id']
    assert docs.check_source(x.w.store, rid)
    registry = Registry(x.w.store)
    registry.approve(x.w.store.resource(rid), 'docs.search.v1', 'search_technical_docs')
    before = len(calls)
    later = clock.time() + INTERVAL + 60
    report = ContractReverifier(x.w.store, x.w.rt.proxy, clock=lambda: later).run()
    http.close()
    assert report['succeeded'] >= 1 and calls == [] and before == 0
    ready = registry.projection(x.w.store.resource(rid))['connection_readiness']
    assert ready['verified_callable'] and ready['verified_at'] > later - INTERVAL - 120


def test_reverifier_recovers_docs_after_a_failed_health_read(customer_flow, monkeypatch):  # noqa: F811
    """QA 19: one failed read left the docs agent "failing"; health changes clear eligibility and
    execution refuses failing listings, so only a real source read can restore it."""
    import time as clock
    from agent_market.capability_registry import Registry
    from agent_market.model_contract_reverify import ContractReverifier, INTERVAL
    from agent_market.owned_data_agents.activation import install
    x = customer_flow; calls = []; docs_site = context7(calls)
    core, http = agent(lambda request: httpx.Response(200, json={'documents': []}) if request.url.host == 'developer.mozilla.org' else docs_site(request))
    core.utc_now = lambda: datetime.now(timezone.utc)
    monkeypatch.setattr(docs, 'engine', lambda: core)
    install(x.w.store, 'https://agentconcierge.biz')
    rid = x.w.store.query('SELECT id FROM resources WHERE key=?', (docs.KEY,))[0]['id']
    assert docs.check_source(x.w.store, rid)
    registry = Registry(x.w.store)
    registry.approve(x.w.store.resource(rid), 'docs.search.v1', 'search_technical_docs')
    x.w.store.record_health(rid, 'failing', None, None, 'Public data source unavailable.', clock.time() + 120)
    report = ContractReverifier(x.w.store, x.w.rt.proxy, clock=lambda: clock.time() + INTERVAL + 60).run()
    http.close()
    assert x.w.store.resource(rid)['health_status'] == 'healthy' and report['succeeded'] >= 1
    assert registry.projection(x.w.store.resource(rid))['connection_readiness']['verified_callable']
