"""Explore/Chat speed and quality round 2 (2026-10-27): prefilter, subjects, focus tiers, warm chips."""
import json
import threading

import pytest

from agent_market.concierge import selection as sel
from agent_market.concierge.discovery import normalize_task


@pytest.mark.parametrize('task,core', [
    ('Look up the current EUR to USD exchange rate', ['exchange', 'rate']),
    ('I need to scrape product prices from an e-commerce website', ['scrape', 'website']),
    ('convert currency from EUR to JPY', ['convert', 'currency']),
])
def test_subjects_of_currency_and_scraping_are_not_capabilities(task, core):
    assert sel.capability_terms(normalize_task(task)) == core


def test_prefilter_is_a_necessary_condition_of_scope_admission():
    tools = [{'name': 'get_weather', 'description': 'Current weather for a city',
              'inputSchema': {'type': 'object', 'properties': {'city': {'type': 'string'}}}}]
    weather = {'kind': 'mcp', 'name': 'Forecasts', 'description': 'City data', 'usage_tools': json.dumps(tools)}
    unrelated = {'kind': 'mcp', 'name': 'Invoices', 'description': 'Read invoices', 'usage_tools': '[]'}
    category = {'kind': 'mcp', 'name': 'Koekatsu', 'description': 'Survey site', 'category': 'web_search', 'usage_tools': '[]'}
    assert sel.text_may_match(['weather'], weather)  # tool name underscores are word breaks
    assert not sel.text_may_match(['weather'], unrelated) and not sel.task_scope_matches(['weather'], unrelated)
    assert sel.text_may_match(['web', 'search'], category)
    assert sel.text_may_match(['directory'], unrelated)  # directory requests keep their own rules


@pytest.mark.parametrize('description,expected', [
    ('Live EUR/USD and other foreign exchange rates.', True),
    ('Perpetual funding rates on every crypto exchange.', False),
])
def test_currency_requests_need_currency_rates(description, expected):
    resource = {'kind': 'a2a', 'name': 'Rates', 'description': description}
    terms = ['exchange', 'rate']
    assert sel.task_scope_matches(terms, resource, terms, tools=[]) is expected


def test_explore_orders_task_led_listings_before_mentions_across_protocols(monkeypatch):
    from agent_market.concierge import hybrid_explore
    calls = []
    def group(kind, items):
        return {'query': 'q', 'terms': [], 'total': len(items), 'total_is_estimate': True, 'items': items, 'verified': False}
    real = hybrid_explore.explore.__wrapped__ if hasattr(hybrid_explore.explore, '__wrapped__') else None
    def fake(store, engine, query, kind, category, verified, no_auth, limit):
        if kind is None:
            return original(store, engine, query, kind, category, verified, no_auth, limit)
        calls.append((kind, limit))
        if kind == 'a2a':
            return group(kind, [{'id': i, 'kind': 'a2a', 'match_basis': 'mention'} for i in range(1, 5)])
        return group(kind, [{'id': 10, 'kind': 'mcp', 'match_basis': 'listing'}, {'id': 11, 'kind': 'mcp', 'match_basis': 'mention'}])
    original = hybrid_explore.explore
    monkeypatch.setattr(hybrid_explore, 'explore', fake)
    result = original(object(), None, 'exchange rate', None, None, False, False, 4)
    assert [item['id'] for item in result['items']] == [10, 1, 2, 3]
    assert calls == [('a2a', 4), ('mcp', 4)]  # A2A filled the page; MCP still checked a bounded window
    assert real is None or callable(real)


def test_warm_explore_fills_the_same_cache_key_a_chip_uses(monkeypatch):
    from types import SimpleNamespace
    from agent_market.concierge import front as front_module
    store = SimpleNamespace(backend='postgresql')
    front = SimpleNamespace(store=store, rag_engine=None)
    seen = []
    monkeypatch.setattr('agent_market.concierge.hybrid_explore.explore',
                        lambda s, e, q, *rest: seen.append(q) or {'items': [], 'query': q})
    front_module._explore_result_cache.clear()
    stop = threading.Event()
    assert front_module.warm_explore(front, ('weather', 'news'), stop=stop) == 2
    key = front_module.explore_cache_key(front, '  Weather ', None, None, False, False, 46)
    assert front_module._explore_result_cache.get(key) == {'items': [], 'query': 'weather'} and seen == ['weather', 'news']
    stop.set()
    assert front_module.warm_explore(front, ('weather',), stop=stop) == 0
    front_module._explore_result_cache.clear()


def test_warm_queries_cover_the_public_chips():
    from agent_market.concierge.front import EXPLORE_WARM_QUERIES
    import re
    html = open('extracted_html.txt').read()
    chips = re.search(r'const QUICK_CHIPS = \[(.*?)\];', html, re.S).group(1)
    queries = re.findall(r'\["[^"]+", "([^"]+)"\]', chips)
    assert queries and set(queries) <= set(EXPLORE_WARM_QUERIES)
    pearl = open('new/live-assets/pearl-ui.js').read()
    assert "['Web Search','Research','research papers']" in pearl and 'research papers' in EXPLORE_WARM_QUERIES


@pytest.mark.parametrize('text,regions', [
    ('Phuket real estate and weather', ['sea']), ('Hawaii Conditions', ['us']), ('weather seoul', ['kr']),
    ('New York weather', ['us']), ('global weather for any city', []),
])
def test_focused_gazetteer_names_regions(text, regions):
    from agent_market.gateway.constraints import places_in_text
    assert places_in_text(text) == regions


def test_city_weather_excludes_services_scoped_to_another_place():
    assert not sel._weather_scope_matches(['weather', 'seoul'], 'phuket real estate. current weather now')
    assert not sel._weather_scope_matches(['weather', 'seoul'], 'hawaii conditions and surf')
    assert sel._weather_scope_matches(['weather', 'seoul'], 'worldwide forecasts for any city')
    assert sel._weather_scope_matches(['weather', 'honolulu'], 'hawaii conditions and surf')


def test_only_plain_repeated_searches_are_kept_warm():
    from agent_market.concierge.front import _QueryPopularity, EXPLORE_WARM_QUERIES
    popular = _QueryPopularity()
    for _ in range(3):
        popular.record('  Vector Database ')
        popular.record('call me at 01012345678')
        popular.record('mail jane@example.com')
    popular.record('rare search')
    assert popular.top() == ['vector database']
    assert 'vector database' not in EXPLORE_WARM_QUERIES


def test_task_facts_are_reused_across_searches_for_ten_minutes():
    from agent_market.concierge.discovery_contracts import TaskFacts
    facts = TaskFacts()
    assert facts.lifetime == 600 and facts.maximum >= 32768


def test_video_summaries_need_a_summarizing_or_transcribing_tool():
    from agent_market.concierge.task_capability import matches
    schema = {'type': 'object', 'properties': {'url': {'type': 'string'}}}
    task = 'Find an agent that can summarize YouTube videos'
    schools = {'name': 'Schools', 'description': 'U.S. boarding schools for international students.'}
    channel = {'name': 'get_school_videos', 'description': "Official videos from the school's YouTube channel.", 'inputSchema': schema}
    transcripts = {'name': 'get_transcript', 'description': 'Read a YouTube transcript.', 'inputSchema': schema}
    assert not matches(task, channel, 'mcp', schools)
    assert matches(task, transcripts, 'mcp', {'name': 'Video notes', 'description': 'Transcribe and summarize videos.'})


def test_prediction_markets_are_not_weather_forecasts():
    assert not sel._weather_scope_matches(['weather', 'forecast'], 'forecast future events and scan prediction-market edges')
    assert sel._weather_scope_matches(['prediction', 'markets', 'weather'], 'weather prediction markets')


def test_listings_without_coverage_follow_ones_that_cover_the_requested_place():
    tools = json.dumps([{'name': 'get_weather', 'description': 'Current weather and forecast for any location.'}])
    anywhere = {'kind': 'mcp', 'name': 'Geocoding & Weather', 'description': 'Weather forecasts', 'usage_tools': tools}
    address = {'kind': 'mcp', 'name': 'Storm Data API', 'description': 'Storm history by address since 2003, weather forecasts.', 'usage_tools': '[]'}
    korea = {'kind': 'mcp', 'name': 'Korea Weather', 'description': 'Weather forecasts for Korea.', 'usage_tools': '[]'}
    assert sel.place_fit(['weather', 'seoul'], anywhere) and sel.place_fit(['weather', 'seoul'], korea)
    assert not sel.place_fit(['weather', 'seoul'], address)
    assert sel.place_fit(['weather'], address)  # no place requested: nothing to rank by
