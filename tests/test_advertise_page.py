"""/advertise (PM 11-14, demand side of coin revenue): measured audience, placement and trust rules, price, and the
apply link to the AD Coin booking flow. USDC wording follows the payment switch; no promise words."""
import json
import re

from agent_market.concierge import advertise_page as ap
from tests.test_pearl_frontend import client  # noqa: F401 - fixture

ROWS = [{'day': '2026-11-1%d' % d, 'human_visitors': 30, 'explore_external': 7, 'chat_external': 2, 'mcp_sessions_real': 90,
         'a2a_messages_external': 15} for d in range(0, 4)]


def text(value):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', value))


def test_measured_audience_trust_rules_and_apply_link():
    value = ap.page_html(rows=ROWS, usdc=False)
    t = text(value)
    for expected in ('People visiting our pages 120', 'Explore searches from outside 28', 'MCP client sessions (checkers excluded) 360',
                     '2026-11-10 to 2026-11-13', 'labelled “Sponsored”', 'Which agents become pearls', 'no ad cookies',
                     'USDC payments are not open yet', '5 USDC'):
        assert expected in t, expected
    assert 'href="/ad-coin/v2#advertising"' in value and 'href="/methodology"' in value
    for word in ('guaranteed', '#1', ' best '):
        assert word not in t


def test_payment_wording_follows_the_switch_and_missing_numbers_hide_the_section():
    assert 'from your own wallet, when you book' in text(ap.page_html(rows=ROWS, usdc=True))
    empty = text(ap.page_html(rows=[], usdc=False))
    assert 'Who sees AgentValCon' not in empty and 'Apply as an advertiser' in empty
    partial = [dict(ROWS[0], chat_external=None)] + ROWS[1:]
    assert 'Chat questions from outside' not in text(ap.page_html(rows=partial, usdc=False))


def test_route_sitemap_and_llms(client, tmp_path, monkeypatch):  # noqa: F811
    (tmp_path / 'logs/growth').mkdir(parents=True)
    (tmp_path / 'logs/growth/usage-daily.jsonl').write_text('\n'.join(json.dumps(r) for r in ROWS) + '\n')
    monkeypatch.setenv('AGENTCON_PROJECT_ROOT', str(tmp_path))
    r = client.get('/advertise', headers={'Accept': 'text/html'})
    assert r.status_code == 200 and 'Advertise on AgentValCon' in r.text and 'People visiting our pages' in r.text
    assert '/advertise' in client.get('/llms.txt').text
    from agent_market.concierge.growth_pages import sitemap_paths
    assert '/advertise' in sitemap_paths({'tasks': [], 'catalog': [], 'captured': 0})
