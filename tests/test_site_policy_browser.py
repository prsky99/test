"""Consent banner and policy dialogs on all nine main pages after they moved to site-policy.js (PM 11-14 17:4x).

Consent is a record of the visitor's choice, so it is tested by real clicks on every page: the banner on a first
visit, accept, reject and saved preferences, no banner on a return visit, and the stored value exactly as the code
before the move wrote it (key agent_cookie_consent_v2; level, analytics, marketing, gpc, timestamp), so choices
made before keep working. The eight footer policy links open their dialog from the keyboard on every page at 1280
and 375, light and dark; Escape closes it and focus returns to the link. No page error anywhere."""
import json
from urllib.parse import urlsplit

import pytest
from starlette.testclient import TestClient

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.store import Store

playwright = pytest.importorskip("playwright.sync_api")
PAGES = ['index', 'explore', 'chat', 'test', 'workflows', 'list-agent', 'learn', 'about', 'agent-status']
FOOTER = ['terms', 'privacy', 'cookies', 'privacy-choices', 'accessibility', 'disclosures', 'notifications', 'contact']
KEY = 'agent_cookie_consent_v2'
STATUS = []   # responses of 400 or more, for a failure message
FIELDS = {'level', 'analytics', 'marketing', 'timestamp', 'gpc'}


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def app(tmp_path):
    """One app per test: every request comes from the same test address, so a shared app's request limit (429)
    would answer later pages with an empty error page (seen 11-14: about at 375 after the consent tests)."""
    store = Store(str(tmp_path / 'policy.db'))
    client = TestClient(create_front_app(Front(store)))
    yield client
    client.close()


def open_page(browser, app, width=1280, scheme='light'):
    context = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme=scheme)

    def serve(route):
        url = urlsplit(route.request.url)
        if url.hostname != "agentconcierge.biz":
            route.abort()
            return
        response = app.request(route.request.method, url.path + ("?" + url.query if url.query else ""),
                               content=route.request.post_data, headers={"accept": route.request.headers.get("accept", "")})
        if response.status_code >= 400:
            STATUS.append((response.status_code, url.path))
        route.fulfill(status=response.status_code, body=response.content,
                      headers={k: v for k, v in response.headers.items()
                               if k not in ("content-length", "content-encoding", "transfer-encoding")})
    context.route("**/*", serve)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    return context, page, errors


def url(name):
    return 'https://agentconcierge.biz/' + ('' if name == 'index' else 'new/en/' + name + '.html')


def stored(page):
    raw = page.evaluate(f'localStorage.getItem({json.dumps(KEY)})')
    return json.loads(raw) if raw else None


def banner_shown(page):
    return page.evaluate("(() => {const b = document.getElementById('cookieConsentBanner'); return !!b && !b.classList.contains('hidden') && !b.hidden && getComputedStyle(b).display !== 'none';})()")


@pytest.mark.parametrize('name', PAGES)
def test_consent_banner_choices_and_return_visits(browser, app, name):
    context, page, errors = open_page(browser, app)
    try:
        page.goto(url(name), wait_until='load'); page.wait_for_timeout(300)
        assert stored(page) is None and banner_shown(page)
        page.click('#btnAcceptAllCookies')
        value = stored(page)
        assert set(value) == FIELDS and (value['level'], value['analytics'], value['marketing'], value['gpc']) == ('all', True, True, False)
        assert not banner_shown(page)
        page.reload(wait_until='load'); page.wait_for_timeout(300)
        assert not banner_shown(page) and stored(page) == value                    # a return visit keeps the choice
        page.evaluate(f'localStorage.removeItem({json.dumps(KEY)})')
        page.reload(wait_until='load'); page.wait_for_timeout(300)
        assert banner_shown(page)
        page.click('#btnRejectNonEssentialCookies')
        value = stored(page)
        assert (value['level'], value['analytics'], value['marketing']) == ('essential', False, False) and not banner_shown(page)
        page.locator('footer.pearl-footer [data-footer-key="cookies"]').click()
        page.wait_for_selector('#cookiePrefsModal[open]')
        page.evaluate("document.getElementById('prefAnalyticsToggle').checked = true; document.getElementById('prefMarketingToggle').checked = false;")
        page.click('#btnSaveCookiePrefs')
        value = stored(page)
        assert (value['level'], value['analytics'], value['marketing']) == ('custom', True, False)
        # as before the move: the preferences dialog closes and a confirmation opens; Acknowledge closes it
        assert not page.evaluate("document.getElementById('cookiePrefsModal').open")
        page.wait_for_selector('#appLayerModal[open]')
        assert page.locator('#layerModalTitle').inner_text().strip() == 'Custom Preferences Saved'
        page.click('#layerModalOkBtn')
        page.wait_for_function("!document.querySelector('dialog[open]')", timeout=5000)
        assert errors == []
    finally:
        context.close()


@pytest.mark.parametrize('name', PAGES)
@pytest.mark.parametrize('width,scheme', [(1280, 'light'), (1280, 'dark'), (375, 'light'), (375, 'dark')])
def test_policy_dialogs_open_from_the_keyboard_and_return_focus(browser, app, name, width, scheme):
    context, page, errors = open_page(browser, app, width, scheme)
    try:
        page.goto(url(name), wait_until='load'); page.wait_for_timeout(300)
        page.evaluate(f'localStorage.setItem({json.dumps(KEY)}, JSON.stringify({{level: "essential", analytics: false, marketing: false, timestamp: "2026-11-14T00:00:00Z", gpc: false}}))')
        page.reload(wait_until='load'); page.wait_for_timeout(300)
        assert page.locator('footer.pearl-footer').count() == 1, ('no footer', page.title(), STATUS[-8:])
        for key in FOOTER:
            link = page.locator(f'footer.pearl-footer [data-footer-key="{key}"]')
            link.focus()
            page.keyboard.press('Enter')
            page.wait_for_selector('dialog[open]', timeout=5000)
            page.keyboard.press('Escape')
            page.wait_for_function("!document.querySelector('dialog[open]')", timeout=5000)
            assert page.evaluate(f"document.activeElement?.dataset?.footerKey") == key, (name, key, STATUS[-5:])
        assert errors == []
    finally:
        context.close()


@pytest.mark.parametrize('name', ['learn', 'about', 'agent-status'])
def test_notifications_dialog_on_pages_without_operating_links_to_the_home_settings(browser, app, name):
    """PM 11-14: the task notification list needs the Chat code; on these pages the dialog says where to manage it."""
    context, page, errors = open_page(browser, app)
    try:
        page.goto(url(name), wait_until='load'); page.wait_for_timeout(300)
        page.locator('footer.pearl-footer [data-footer-key="notifications"]').click()
        page.wait_for_selector('#legalModal[open]')
        link = page.locator('#taskPreferences a')
        assert link.inner_text().strip() == 'Manage task notifications on the home page'
        assert link.get_attribute('href') == '/#cancellation'
        assert page.locator('#legalModalBody').inner_text().strip()
        assert errors == []
    finally:
        context.close()
