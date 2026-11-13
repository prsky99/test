"""11-11 PM decision A: public HTML is the same for every visitor, so the edge may keep it for 60 seconds.

Fixed before the change: no sign-in state, consent state or visitor value in the HTML; a response with
Set-Cookie is never shared-cacheable; every inline script the browser runs is allowed by its hash.
"""
import base64
import hashlib
import json
import re

import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response

from agent_market.concierge.front import Front, clear_front_caches, create_front_app
from agent_market.concierge.pearl_view import inline_script_hashes
from agent_market.gateway.store import Store

BROWSER = {'Accept': 'text/html,application/xhtml+xml', 'User-Agent': 'Mozilla/5.0 (Macintosh) Chrome/140 Safari/537.36'}
PAGES = ['/', '/new/en/index.html', '/new/en/explore.html', '/new/en/chat.html', '/new/en/test.html',
         '/new/en/learn.html', '/new/en/workflows.html', '/new/en/list-agent.html', '/new/en/about.html',
         '/new/en/privacy.html', '/new/en/disclosures.html']
VISITORS = [{}, {'Cookie': 'agentcon_session=signed-in-visitor; cookie_consent=accepted'},
            {'Cookie': 'cookie_consent=rejected', 'X-Visitor-Token': 'vt_someone'},
            {'Cookie': '_ga=GA1.2.3; workspace_session=abc', 'Authorization': 'Bearer person-b'}]


@pytest.fixture
def client(tmp_path):
    store = Store(str(tmp_path / 'cache.db'))
    for i in range(4):
        rid = store.upsert_resource({'key': 'c-%d' % i, 'name': 'Agent %d' % i, 'kind': 'a2a', 'source': 'isolated',
                                     'url': 'https://agent-%d.example' % i, 'description': 'Weather', 'category': 'weather'})
        with store.tx() as db:
            db.execute("UPDATE resources SET health_status='healthy',last_check_at=1 WHERE id=?", (rid,))
    clear_front_caches()
    front = Front(store)
    app = create_front_app(front, manage_book_lifecycle=False)

    @app.get('/__cookie_test', include_in_schema=False)
    def cookie_test():
        response = Response('x', headers={'Cache-Control': 'public, max-age=300, stale-while-revalidate=86400'})
        response.set_cookie('probe', '1')
        return response
    c = TestClient(app, base_url='https://agentconcierge.biz')
    yield c
    c.close()
    front.book.close()
    store._db.close()


def scripts_run_by_browser(html):
    for attributes, body in re.findall(r'<script\b([^>]*)>(.*?)</script>', html, re.S | re.I):
        if 'src=' in attributes or re.search(r'type="application/(ld\+)?json"', attributes):
            continue
        yield body


@pytest.mark.parametrize('path', PAGES)
def test_every_visitor_gets_the_same_bytes_and_no_cookie(client, path):
    bodies = []
    for extra in VISITORS:
        r = client.get(path, headers={**BROWSER, **extra})
        assert r.status_code == 200 and r.headers['content-type'].startswith('text/html')
        assert 'set-cookie' not in r.headers
        # Live pages may sit at the edge; the policy and design-sample pages stay no-store (and noindex).
        # 11-13 PM 20:5x: the notice pages are shared too, but only for a request without cookies or credentials.
        notice = path.endswith(('privacy.html', 'disclosures.html'))
        expected = 'no-store' if notice and extra else 'public, max-age=300, stale-while-revalidate=86400'
        assert r.headers['cache-control'] == expected
        bodies.append(r.text)
    assert all(body == bodies[0] for body in bodies[1:]), 'the HTML depends on who asks'
    for marker in ('signed-in-visitor', 'vt_someone', 'person-b', 'workspace_session', 'nonce='):
        assert marker not in bodies[0]


@pytest.mark.parametrize('path', PAGES)
def test_csp_allows_exactly_the_inline_scripts_by_hash(client, path):
    r = client.get(path, headers=BROWSER)
    csp = r.headers['content-security-policy']
    assert 'nonce-' not in csp and "script-src 'self'" in csp and "script-src-attr 'none'" in csp
    allowed = set(re.findall(r"'sha256-([A-Za-z0-9+/=]+)'", csp))
    run = [base64.b64encode(hashlib.sha256(b.encode()).digest()).decode() for b in scripts_run_by_browser(r.text)]
    assert set(run) == allowed == set(inline_script_hashes(r.text))  # legal pages run no inline script


def test_home_answers_agents_and_markdown_uncached_by_the_shared_rule(client):
    # The same URL answers JSON or Markdown by Accept; only text/html requests are eligible at the edge.
    md = client.get('/', headers={'Accept': 'text/markdown'})
    assert md.headers['cache-control'] == 'no-store'
    agent = client.get('/', headers={'Accept': 'application/json'})
    assert 'public' not in agent.headers.get('cache-control', '') and agent.headers['content-type'].startswith('application/json')
    assert 'accept' in client.get('/', headers=BROWSER).headers['vary'].lower()


def test_design_and_sample_pages_stay_private(client):
    r = client.get('/new/en/components.html', headers=BROWSER)
    assert r.status_code == 200 and r.headers['cache-control'] == 'no-store'


def test_a_response_that_sets_a_cookie_is_never_shared(client):
    r = client.get('/__cookie_test')
    assert 'set-cookie' in r.headers and 'public' not in r.headers['cache-control']


def test_bootstrap_data_has_no_visitor_fields(client):
    html = client.get('/', headers={**BROWSER, **VISITORS[1]}).text
    data = re.search(r'<script[^>]*id="appBootstrapData"[^>]*>(.*?)</script>', html, re.S)
    if data:
        text = json.dumps(json.loads(data[1].replace('\\u003c', '<'))).lower()
        for key in ('"visitor"', '"token"', '"email"', '"signed_in"', '"account"'):
            assert key not in text


def test_category_and_weekly_paths_are_growth_pages_for_the_edge():
    # 11-11 (user approved adding them to Cloudflare rule 2): same public cache policy as the other growth pages.
    from agent_market.concierge.public_http_contract import GROWTH_CACHE, growth_path, shared_path
    for path in ('/agents/category/web_search', '/reports/weekly/2026-W45', '/reports/weekly'):  # list: 11-12 PM
        assert growth_path(path) and shared_path(path)
    assert not growth_path('/agent/1/reported') and GROWTH_CACHE.startswith('public, max-age=21600')


def test_edge_policies_never_carry_s_maxage():
    # 11-12 noon bundle: Cloudflare treats s-maxage as proxy-revalidate and will not serve a stale copy, so every
    # live page was EXPIRED (1.0-4.0 s) instead of UPDATING 6.5 min after warming. max-age + swr gave UPDATING.
    from agent_market.concierge.pearl_view import PUBLIC_PAGE_CACHE
    from agent_market.concierge.public_http_contract import GROWTH_CACHE
    for policy in (PUBLIC_PAGE_CACHE, GROWTH_CACHE):
        assert 's-maxage' not in policy and 'must-revalidate' not in policy and 'proxy-revalidate' not in policy
        assert 'stale-while-revalidate=' in policy and 'max-age=0' not in policy
