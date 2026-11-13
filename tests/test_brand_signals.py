"""11-14 (PM, search: "agent concierge" left the first page): the home page says its brand plainly.

Title starts with the brand and says what the site is for; WebSite and Organization carry every name the site goes
by, the contact address and the official profile that exists; og:site_name matches; the brand is visible text right
above the home heading. The screen-change runtime uses the same title.
"""
import json
import re
from pathlib import Path

from agent_market.concierge.public_metadata import BRAND, BRAND_ALIASES, OFFICIAL_PROFILES, PAGES
from tests.test_pearl_frontend import client  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_the_home_title_starts_with_the_brand_and_says_what_it_finds():
    title = PAGES['overview'][1]
    assert title.startswith(BRAND + ':') and 'AI Agents' in title and 'MCP Servers' in title
    runtime = (ROOT / 'new/en/assets/operating.js').read_text()
    assert json.dumps({'title': title})[1:-1] in runtime  # SPA navigation sets the same title


def test_home_head_carries_the_brand_names_contact_and_profile(client):  # noqa: F811
    html = client.get('/', headers={'Accept': 'text/html'}).text
    assert re.search(r'<title>([^<]*)</title>', html)[1] == PAGES['overview'][1].replace('&', '&amp;')
    assert '<meta property="og:site_name" content="Agent Concierge">' in html
    ld = json.loads(re.search(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S)[1])
    nodes = {n['@type']: n for n in ld['@graph']}
    for kind in ('Organization', 'WebSite'):
        assert nodes[kind]['name'] == BRAND and nodes[kind]['alternateName'] == list(BRAND_ALIASES)
    assert nodes['Organization']['email'] == 'contact@agentconcierge.biz'
    assert nodes['Organization']['sameAs'] == list(OFFICIAL_PROFILES) and nodes['Organization']['description']
    hero = html[html.index('<section class="hero catalog-hero">'):]
    assert re.match(r'<section class="hero catalog-hero">\s*<div>\s*<p class="eyebrow">Agent Concierge · ', hero)
