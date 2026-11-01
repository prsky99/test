"""First-party Hacker News search projected into the private news contract (2026-10-28)."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from agent_market.capability_contracts import run_test
from agent_market.capability_registry import Registry
from agent_market.gateway.store import Store
from agent_market.owned_capability_adapter import NEWS_CONTRACT, NEWS_TOOL, arguments, normalize, profile
from agent_market.owned_data_agents.activation import install, check_sources
from agent_market.concierge.proxy import McpProxy
from tests.test_owned_data_agents import engine  # noqa: F401


def stamp(value):
    return value.strftime('%Y-%m-%dT%H:%M:%SZ')


@pytest.fixture
def news(tmp_path, engine):  # noqa: F811
    core, calls, state = engine
    core.utc_now = lambda: datetime.now(timezone.utc)
    store = Store(str(tmp_path / 'owned-news.sqlite3'))
    rid = install(store, 'https://agentconcierge.biz')['technology-news']
    store._owned_data_engine = core
    check_sources(store, core, {'technology-news': rid})
    yield store, store.resource(rid), core, calls
    store._db.close()


def request(days=2, **changes):
    return {'query': 'artificial intelligence', 'language': 'en', 'limit': 3,
            'from_utc': stamp(datetime.now(timezone.utc) - timedelta(days=days)), **changes}


def test_requests_become_bounded_hacker_news_searches(news):
    _, resource, _, _ = news
    current = profile(resource, NEWS_CONTRACT, NEWS_TOOL)
    assert current['id'] == 'owned-technology-news-v1'
    assert arguments(resource, NEWS_CONTRACT, NEWS_TOOL, request(limit=8), expected=current) == {'query': 'artificial intelligence', 'limit': 5}
    with pytest.raises(ValueError):
        arguments(resource, NEWS_CONTRACT, NEWS_TOOL, request(query='x' * 161), expected=current)
    with pytest.raises(ValueError):
        profile({**resource, 'key': 'other'}, NEWS_CONTRACT, NEWS_TOOL)


def test_stories_before_the_start_are_omitted_and_marked_partial(news):
    _, resource, core, _ = news
    current = profile(resource, NEWS_CONTRACT, NEWS_TOOL)
    now = datetime.now(timezone.utc)
    output = {'agent': 'technology-news', 'source': {'name': 'Hacker News Search by Algolia', 'url': 'https://hn.algolia.com/api'},
              'retrieved_at': stamp(now), 'cache': {'status': 'live', 'age_seconds': 0},
              'data': {'query': 'artificial intelligence', 'partial': False, 'items': [
                  {'title': 'New', 'url': 'https://news.example/new', 'published_at': stamp(now - timedelta(hours=1)), 'source': 'Hacker News'},
                  {'title': 'Old', 'url': 'https://news.example/old', 'published_at': stamp(now - timedelta(days=5)), 'source': 'Hacker News'}]}}
    value = normalize(resource, NEWS_CONTRACT, NEWS_TOOL, request(), output, expected=current)
    assert [item['title'] for item in value['items']] == ['New'] and value['partial'] is True
    assert value['items'][0]['summary'].startswith('Hacker News story submitted ')


def test_approved_news_contract_is_verified_by_a_real_local_execution(news):
    store, resource, _, calls = news
    registry = Registry(store)
    registry.approve(resource, NEWS_CONTRACT, NEWS_TOOL)
    proxy = McpProxy(store)
    async def runner(identity, **kwargs):
        result = proxy.execute(identity, kwargs['tool'], kwargs['arguments'], public=True)
        return {'execution_succeeded': result.get('ok') is True, 'simulated': False, 'output': result.get('result')}
    with ThreadPoolExecutor(1) as pool:
        checked = pool.submit(lambda: asyncio.run(run_test(registry, resource, NEWS_CONTRACT, request(days=3650), runner))).result(timeout=5)
    assert checked['ok'], checked
    contracts = registry.projection(store.resource(resource['id']))['capability_contracts']
    assert contracts == [{'id': NEWS_CONTRACT, 'verified': True}]
    assert not any(call.url.host == 'agentconcierge.biz' for call in calls)
