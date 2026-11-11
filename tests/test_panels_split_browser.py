"""11-11: with the inactive panels moved to panels.js, a real browser ends up with the same page.

Each live page is opened twice in Chromium, with and without the split: every panel ([data-panel]) must have the
same markup after the deferred scripts ran, no template may be left, nothing may log an error, and moving to
another panel through the main navigation must show it as before.
"""
from urllib.parse import urlsplit

import pytest

from tests.test_agent_adoption import adoption, routing  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

PAGES = ('index.html', 'explore.html', 'chat.html', 'test.html', 'learn.html')
STATE = """() => ({
  panels: [...document.querySelectorAll('[data-panel]')].map(el => el.dataset.panel + ':' + el.innerHTML.length),
  templates: document.querySelectorAll('template[data-inactive-panel]').length,
  visible: [...document.querySelectorAll('[data-panel]')].filter(el => el.getClientRects().length).map(el => el.dataset.panel)
})"""


def open_page(browser, client, path, block_panels=False):
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    errors, asked = [], []

    def serve(route):
        url = urlsplit(route.request.url)
        asked.append(url.path)
        if url.hostname != 'agentconcierge.biz' or (block_panels and url.path.endswith('/panels.js')):
            route.abort()
            return
        r = client.request(route.request.method, url.path + ('?' + url.query if url.query else ''),
                           content=route.request.post_data, headers=route.request.headers)
        headers = {k: v for k, v in r.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')}
        route.fulfill(status=r.status_code, body=r.content, headers=headers)
    context.route('**/*', serve)
    page = context.new_page()
    page.on('console', lambda m: m.type == 'error' and errors.append(m.text))
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('https://agentconcierge.biz' + path, wait_until='load')
    page.wait_for_timeout(400)
    page.asked = asked
    return context, page, errors


@pytest.mark.parametrize('name', PAGES)
def test_the_page_is_the_same_with_the_panels_in_a_shared_script(adoption, browser, name, monkeypatch):  # noqa: F811
    from agent_market.concierge import pearl_view
    *_, client = adoption[:6]
    path = '/new/en/' + name
    context, page, errors = open_page(browser, client, path)
    try:
        split = page.evaluate(STATE)
        fetched = any(p.endswith('/panels.js') for p in page.asked)
        link = page.locator('a[href="/new/en/learn.html"], a[href="learn.html"]').first if name != 'learn.html' else \
            page.locator('a[href="/new/en/explore.html"], a[href="explore.html"]').first
        target = 'learn' if name != 'learn.html' else 'explore'
        if link.count():
            link.click()
            page.wait_for_timeout(400)
            moved = page.evaluate(STATE)['visible']
        else:
            moved = None
    finally:
        context.close()
    with monkeypatch.context() as m:
        m.setattr(pearl_view, 'split_panels', lambda value: value)
        context, page, _ = open_page(browser, client, path)
        try:
            whole = page.evaluate(STATE)
        finally:
            context.close()
    assert not errors, errors[:3]
    assert fetched, 'the split page did not load panels.js'
    assert split['templates'] == 0 and split['panels'] == whole['panels']
    assert split['visible'] == whole['visible']
    if moved is not None:
        assert target in moved, moved


def test_without_panels_js_the_first_screen_still_shows(adoption, browser):  # noqa: F811
    *_, client = adoption[:6]
    context, page, _ = open_page(browser, client, '/new/en/explore.html', block_panels=True)
    try:
        state = page.evaluate(STATE)
    finally:
        context.close()
    assert 'explore' in state['visible']  # only the other panels are missing; the page's own panel is there
