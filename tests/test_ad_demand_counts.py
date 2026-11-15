"""Ad demand counts (PM 11-15 10:37): the advertiser pages are a traffic entry of their own, clicks on the provider
note under agent pages are counted through one fixed query value, and listing pages without evidence carry the same
note. The query never stores an agent or a visitor, and /advertise keeps one cache policy with or without it."""
import inspect

import pytest

from agent_market.concierge import growth_catalog, traffic
from agent_market.concierge.traffic import Traffic, entry_of, usage
from tests.test_fast_single_recommendation import catalog  # noqa: F401

CHROME = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36'
OUTSIDE = {'X-Forwarded-For': '203.0.113.9', 'User-Agent': CHROME}


@pytest.mark.parametrize('path,entry', [
    ('/advertise', 'advertise'), ('/ads/library', 'advertise'), ('/ads/library.json', 'advertise'),
    ('/ad-coin/v2', 'advertise'), ('/ad-coin/v2/advertise', 'advertise'),
    ('/ad-coin/v2/admin', None), ('/ad-coin/v2/assets/app.js', None),
    ('/api/ad-coin/v2/advertisers', 'api_other'), ('/agent/5', 'agent_pages')])
def test_advertiser_pages_are_one_entry(path, entry):
    assert entry_of('GET', path) == entry


def test_note_clicks_count_only_the_fixed_value(tmp_path):
    rec = Traffic(tmp_path, clock=lambda: 1794200000.0)
    rec.observe('GET', '/advertise', 200, '203.0.113.9', CHROME, source='agent-page')
    rec.observe('GET', '/advertise', 200, '203.0.113.9', CHROME, source='agent-page-77')
    rec.observe('GET', '/advertise', 200, '203.0.113.9', CHROME)
    rec.observe('GET', '/ads/library', 200, '203.0.113.9', CHROME, source='agent-page')   # not the note's target
    rec.observe('GET', '/advertise', 200, '203.0.113.10', 'Mozilla/5.0 (compatible; GPTBot/1.2)', source='agent-page')
    snap = rec.snapshot()
    assert snap['requests']['advertise|browser'] == 4
    assert snap['requests']['advertise_from_agent_page|browser'] == 1
    assert snap['requests']['advertise_from_agent_page|ai_bot'] == 1
    rec.flush()
    text = next(tmp_path.glob('*.json')).read_text()
    assert 'agent-page-77' not in text and '203.0.113' not in text
    row = usage(traffic.load_day(tmp_path, rec.day))
    assert row['advertise_human_requests'] == 4 and row['advertise_from_agent_page_human'] == 1


def test_usage_reads_the_advertise_counts():
    day = {'requests': {'advertise|browser': 5, 'advertise_from_agent_page|browser': 2, 'advertise|ai_bot': 9},
           'distinct': {'advertise|browser': 3}, 'rpc': {}, 'mcp_clients': {}, 'errors': {}}
    row = usage(day)
    assert (row['advertise_human_requests'], row['advertise_human_visitors'], row['advertise_from_agent_page_human']) == (5, 3, 2)
    before = usage({**day, 'requests': {'home|browser': 4}, 'distinct': {}})    # a day before the counter shipped
    assert before['advertise_human_requests'] is None and before['advertise_from_agent_page_human'] is None


def test_the_real_middleware_counts_a_note_click_and_keeps_one_cache_policy(catalog, tmp_path, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient
    from agent_market.concierge.front import create_front_app
    _, front, _, _, _ = catalog
    recorder = Traffic(tmp_path)
    monkeypatch.setattr(traffic, '_SINGLETON', recorder)
    client = TestClient(create_front_app(front))
    plain = client.get('/advertise', headers={**OUTSIDE, 'Accept': 'text/html'})
    noted = client.get('/advertise?from=agent-page', headers={**OUTSIDE, 'Accept': 'text/html'})
    assert plain.status_code == noted.status_code == 200
    assert plain.headers['cache-control'] == noted.headers['cache-control']
    assert 'no-store' not in noted.headers['cache-control']
    snap = recorder.snapshot()
    assert snap['requests']['advertise|browser'] == 2 and snap['requests']['advertise_from_agent_page|browser'] == 1


def test_listing_pages_carry_the_same_note():
    note = growth_catalog.PROVIDER_NOTE
    assert note == ('<p class="muted provider-note">Is this your agent? <a href="/methodology">See how it is verified</a>'
                    ' · <a href="/advertise?from=agent-page">Advertise in Sponsored</a></p>')
    assert 'PROVIDER_NOTE' in inspect.getsource(growth_catalog._render_basic)
    assert 'PROVIDER_NOTE' in inspect.getsource(growth_catalog.agent_page)
