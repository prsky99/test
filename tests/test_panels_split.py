"""11-11 (PM: page target 1 s, cut bytes): inactive panel markup leaves the HTML for the shared panels.js.

Fixed here: the live pages lose the eight inactive panels' markup (gzip about 44 -> 20 KB on the public site),
panels.js?v=<digest> holds exactly that markup and loads before bundle.js, it is rebuilt after a restart, and
in a real browser the page ends up with the same DOM as before the split.
"""
import gzip
import json
import re

import pytest
from fastapi.testclient import TestClient

from agent_market.concierge import pearl_view
from agent_market.concierge.front import Front, clear_front_caches, create_front_app
from agent_market.gateway.store import Store

BROWSER = {'Accept': 'text/html,application/xhtml+xml'}
LIVE = ['/', '/new/en/index.html', '/new/en/explore.html', '/new/en/chat.html', '/new/en/test.html',
        '/new/en/learn.html', '/new/en/workflows.html', '/new/en/list-agent.html', '/new/en/about.html',
        '/new/en/agent-status.html']


@pytest.fixture
def client(tmp_path):
    store = Store(str(tmp_path / 'panels.db'))
    clear_front_caches()
    front = Front(store)
    c = TestClient(create_front_app(front, manage_book_lifecycle=False), base_url='https://agentconcierge.biz')
    yield c
    c.close()
    front.book.close()
    store._db.close()


def panels_of(client, html):
    url = re.search(r'<script src="(/new/en/assets/panels\.js\?v=[0-9a-f]{16})" defer></script>', html)[1]
    r = client.get(url)
    assert r.status_code == 200 and r.headers['cache-control'] == 'public, max-age=31536000, immutable'
    assert r.headers['content-type'].startswith('text/javascript')
    text = r.text
    prefix = 'window.__pearlPanels=Object.assign(window.__pearlPanels||{},'
    assert text.startswith(prefix)
    return url, json.loads(text[len(prefix):text.rindex(');')])


@pytest.mark.parametrize('path', LIVE)
def test_live_pages_ship_empty_templates_and_load_panels_before_bundle(client, path):
    html = client.get(path, headers=BROWSER).text
    names = re.findall(r'<template data-inactive-panel="([^"]+)"></template>', html)
    assert len(names) >= 7 and not re.search(r'<template data-inactive-panel="[^"]+">\s*<(?!/template>)', html)
    url, panels = panels_of(client, html)
    assert sorted(panels) == sorted(names) and all(len(markup) > 500 for markup in panels.values())
    assert html.index(url) < html.index('<script src="/new/en/assets/bundle.js?')
    assert html.count('data-inactive-panel') == len(names)


def test_the_markup_is_exactly_what_the_page_carried_before(client, monkeypatch):
    split = client.get('/new/en/test.html', headers=BROWSER).text
    _, panels = panels_of(client, split)
    monkeypatch.setattr(pearl_view, 'split_panels', lambda value: value)
    whole = client.get('/new/en/test.html', headers=BROWSER).text
    before = dict(re.findall(r'<template data-inactive-panel="([^"]+)">(.*?)</template>', whole, re.S))
    assert before == panels
    assert len(gzip.compress(split.encode())) < len(gzip.compress(whole.encode())) * 0.7


def test_panels_js_is_rebuilt_after_a_restart(client):
    html = client.get('/new/en/explore.html', headers=BROWSER).text
    url, panels = panels_of(client, html)
    pearl_view._panels.clear()  # a new process: nothing rendered yet
    pearl_view._panels_rebuilt['at'] = 0.0
    assert panels_of(client, html) == (url, panels)
    pearl_view._panels.clear()  # within a minute a second unknown digest renders nothing and gets the union briefly
    r = client.get('/new/en/assets/panels.js?v=0123456789abcdef')
    assert r.status_code == 404


def test_an_unknown_digest_gets_the_current_panels_briefly(client):
    client.get('/new/en/chat.html', headers=BROWSER)
    r = client.get('/new/en/assets/panels.js?v=0123456789abcdef')
    assert r.status_code == 200 and r.headers['cache-control'] == 'public, max-age=300, stale-while-revalidate=86400'


def test_csp_still_matches_the_inline_scripts(client):
    r = client.get('/new/en/learn.html', headers=BROWSER)
    allowed = set(re.findall(r"'sha256-([A-Za-z0-9+/=]+)'", r.headers['content-security-policy']))
    assert allowed == set(pearl_view.inline_script_hashes(r.text))
