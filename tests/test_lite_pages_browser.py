"""About, Agent Status and Learn load without operating.js (PM 11-14 17:2x, minimal bundle split).

They keep the shared pieces that live in pearl-ui.js: no page error (PAGE_METAS and the other operating globals are
only touched when operating.js is there), the current menu item, the learn guide search, the theme and menu buttons,
and category links that open Explore with the same filter. The six working pages still load operating.js."""
import re
from urllib.parse import urlsplit

import pytest
from starlette.testclient import TestClient

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.store import Store

playwright = pytest.importorskip("playwright.sync_api")
LITE = {'about': 'about', 'agent-status': 'status', 'learn': 'learn'}
FULL = ('index', 'explore', 'chat', 'test', 'workflows', 'list-agent')


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def site(browser, tmp_path):
    store = Store(str(tmp_path / "lite.db"))
    client = TestClient(create_front_app(Front(store)))
    context = browser.new_context()
    bundles = []

    def serve(route):
        url = urlsplit(route.request.url)
        if url.hostname != "agentconcierge.biz":
            route.abort()
            return
        if '/assets/bundle.js' in url.path:
            bundles.append(url.query)
        response = client.request(route.request.method, url.path + ("?" + url.query if url.query else ""),
                                  content=route.request.post_data,
                                  headers={"accept": route.request.headers.get("accept", "")})
        route.fulfill(status=response.status_code, body=response.content,
                      headers={k: v for k, v in response.headers.items()
                               if k not in ("content-length", "content-encoding", "transfer-encoding")})

    context.route("**/*", serve)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page, errors, bundles
    context.close()
    client.close()


@pytest.mark.parametrize('name', sorted(LITE))
def test_lite_pages_run_without_operating_and_keep_the_shared_pieces(site, name):
    page, errors, bundles = site
    page.goto(f'https://agentconcierge.biz/new/en/{name}.html', wait_until='load')
    page.wait_for_timeout(800)
    assert errors == []
    assert bundles and 'operating' not in re.search(r'f=([^&]+)', bundles[-1]).group(1).split(',')
    tab = page.locator(f'.nav-tab[data-tab="{LITE[name]}"]').first
    assert 'on' in (tab.get_attribute('class') or '').split() and tab.get_attribute('aria-current') == 'page'
    assert page.locator('.nav-tab.on').count() == 1
    if name == 'learn':
        assert page.locator('.learn-guide-search').count() == 1
    before = page.evaluate('document.body.dataset.theme')
    page.locator('[data-pearl-action="theme"]').first.click()
    assert page.evaluate('document.body.dataset.theme') != before
    page.set_viewport_size({'width': 375, 'height': 740})   # the menu button shows on phones
    menu = page.locator('[data-pearl-action="menu"]').first
    menu.click()
    assert menu.get_attribute('aria-expanded') == 'true'
    page.keyboard.press('Escape')
    assert menu.get_attribute('aria-expanded') == 'false'
    assert errors == []


def test_a_category_link_on_a_lite_page_opens_explore_with_the_same_filter(site):
    page, errors, _ = site
    page.goto('https://agentconcierge.biz/new/en/about.html', wait_until='load')
    link = page.locator('[data-pearl-filter="protocol=A2A"]').first
    href = link.evaluate('a => a.href')
    with page.expect_navigation():
        link.evaluate('a => a.click()')
    assert page.url == href.split('#')[0] + '#explore?kind=a2a'
    assert errors == []


def test_working_pages_still_load_operating():
    pages = {p: open(f'new/en/{p}.html', encoding='utf-8').read() for p in FULL}
    for name, html in pages.items():
        assert '<script src="/new/en/assets/operating.js" defer></script>' in html, name
    for name in LITE:
        assert 'assets/operating.js' not in open(f'new/en/{name}.html', encoding='utf-8').read(), name
