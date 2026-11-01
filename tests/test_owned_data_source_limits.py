"""Source quota pacing, cooldown and deadline behavior without external calls."""
import json
from types import SimpleNamespace

import pytest
from tests.test_admin_security_audit import admin  # noqa: F401  (fixture)
from agent_market.owned_data_agents.source_limits import SourcePacer,SourceBusy


class Clock:
    def __init__(self):self.at=0.;self.waits=[]
    def now(self):return self.at
    def sleep(self,value):self.waits.append(value);self.at+=value


def test_two_queries_serialize_and_observe_list_rate_without_retry():
    clock=Clock();gate=SourcePacer(clock.now,clock.sleep);budget=SimpleNamespace(remaining=lambda:5)
    for _ in range(2):
        with gate.slot(budget):gate.observed(SimpleNamespace(status_code=200,headers={'x-rate-limit-limit':'1','x-rate-limit-interval':'1s'}))
    assert clock.waits==[1.1]


def test_429_honors_cooldown_and_fails_before_network_when_budget_short():
    clock=Clock();gate=SourcePacer(clock.now,clock.sleep)
    with gate.slot(SimpleNamespace(remaining=lambda:5)):
        gate.observed(SimpleNamespace(status_code=429,headers={'retry-after':'30'}))
    with pytest.raises(SourceBusy):
        with gate.slot(SimpleNamespace(remaining=lambda:5)):pytest.fail('No request should be sent.')
    assert clock.waits==[]


@pytest.mark.parametrize('headers',[{'x-rate-limit-limit':'0'},{'x-rate-limit-interval':'NaNs'},{'x-rate-limit-interval':'9999s','x-rate-limit-limit':'1'},{'x-rate-limit-limit':'99999'},{'retry-after':'infinite'}])
def test_untrusted_headers_are_bounded_and_never_speed_up_requests(headers):
    clock=Clock();gate=SourcePacer(clock.now,clock.sleep)
    with gate.slot(SimpleNamespace(remaining=lambda:5)):gate.observed(SimpleNamespace(status_code=429,headers=headers))
    assert 1.1<=gate.spacing<=60 and 2<=gate.next_at<=60


def test_github_window_allows_ten_searches_a_minute_and_honors_reset():
    from types import SimpleNamespace
    from agent_market.owned_data_agents.source_limits import WindowLimiter, SourceBusy
    clock = [100.0]
    limiter = WindowLimiter(clock=lambda: clock[0])
    budget = SimpleNamespace(remaining=lambda: 5.0)
    for _ in range(10):
        with limiter.slot(budget):
            pass
    with pytest.raises(SourceBusy):
        with limiter.slot(budget):
            pass
    clock[0] += 61
    with limiter.slot(budget):
        pass
    limiter.observed(SimpleNamespace(status_code=403, headers={'retry-after': '30'}))
    with pytest.raises(SourceBusy):
        with limiter.slot(budget):
            pass
    clock[0] += 31
    with limiter.slot(budget):
        pass


def test_github_search_strips_qualifiers_omits_people_and_shares_one_cache_entry():
    import httpx
    from datetime import datetime, timezone
    from agent_market.owned_data_agents.engine import DataAgents
    from agent_market.owned_data_agents.source_limits import GITHUB_SEARCH
    from tests.test_owned_data_agents import source
    GITHUB_SEARCH.sent.clear(); GITHUB_SEARCH.blocked_until = 0.
    sent = []
    def handle(request):
        sent.append(request)
        return source(request)
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        core = DataAgents(http=http, clock=lambda: 1000.0, utc_now=lambda: datetime(2026, 10, 20, tzinfo=timezone.utc))
        first = core.execute('github-issues', {'query': 'Memory leak user:someone', 'limit': 3, 'repository': 'Example/Project',
                                               'type': 'issue', 'state': 'any'})
        again = core.execute('github-issues', {'query': 'memory   LEAK user:someone', 'limit': 3, 'repository': 'example/project',
                                               'type': 'issue'})
    assert len(sent) == 1 and again['cache']['status'] == 'fresh_cache'
    assert sent[0].url.params['q'] == 'memory leak repo:example/project is:issue'
    item = first['data']['items'][0]
    assert item['repository'] == 'example/project' and item['type'] == 'issue' and item['labels'] == ['bug']
    assert 'not-for-publication' not in json.dumps(first) and 'omitted' not in json.dumps(first)
    with pytest.raises(ValueError):
        DataAgents().execute('github-issues', {'query': 'leak', 'limit': 3, 'repository': 'not a repo'})


def test_github_search_is_public_and_admin_available(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agent_market.gateway.store import Store
    from agent_market.owned_data_agents.activation import install
    from agent_market.owned_data_agents.catalog import SPECS, ADMIN_SPECS
    from agent_market.owned_data_agents.service import router_for, PREFIX
    assert 'github-issues' in SPECS and 'github-issues' not in ADMIN_SPECS
    store = Store(str(tmp_path / 'admin-only.sqlite3'))
    rid = store.upsert_resource({'key': 'agentconcierge-owned:github-issues', 'source': 'agentconcierge-owned', 'kind': 'mcp',
                                 'url': 'https://agentconcierge.biz' + PREFIX + '/github-issues/mcp', 'name': 'GitHub Issues and Pull Requests',
                                 'description': 'Search public GitHub issues', 'category': 'data_utility', 'price_usdc': 0, 'details': {}})
    resources = install(store, 'https://agentconcierge.biz')
    assert resources['github-issues'] == rid and store.resource(rid)['active'] == 1
    app = FastAPI(); app.include_router(router_for(enabled=True))
    response = TestClient(app).post(PREFIX + '/github-issues/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
    assert response.status_code == 200 and response.json()['result']['tools'][0]['name'] == 'search_github_issues'
    store._db.close()


def test_administrators_search_github_through_the_admin_api(monkeypatch, admin):
    from agent_market.owned_data_agents.engine import DataAgents, DataUnavailable
    from tests.test_admin_security_audit import H
    store, client = admin
    seen = []
    def fake(self, agent_id, arguments):
        seen.append((agent_id, arguments))
        if arguments['query'] == 'busy':
            raise DataUnavailable('limit')
        return {'agent': agent_id, 'data': {'items': []}}
    monkeypatch.setattr(DataAgents, 'execute', fake)
    path = '/admin/api/owned-data/github-issues/search'
    assert client.post(path, json={'query': 'memory leak', 'limit': 3}).status_code in (401, 403)  # no staff session
    ok = client.post(path, json={'query': 'memory leak', 'limit': 3, 'type': 'pull_request'}, headers=H)
    assert ok.status_code == 200 and seen[-1] == ('github-issues', {'query': 'memory leak', 'limit': 3, 'type': 'pull_request'})
    assert client.post(path, json={'query': 'x', 'limit': 3, 'author': 'someone'}, headers=H).status_code == 400
    assert client.post(path, json={'query': 'busy', 'limit': 3}, headers=H).status_code == 503
