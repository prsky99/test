"""The optional public connection listing cannot alter legacy template execution."""
import json
import time

import pytest

from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_single_agent_chat_browser import chat_page  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')
IDENTITY = 'pub_' + 'a' * 32


def release(**changes):
    return {'id': IDENTITY, 'title': 'News to documentation',
            'description': 'A reviewed connection.', 'expires': time.time() + 3600,
            'url': '/connections/' + IDENTITY, **changes}


def listing(page, rows, status=200):
    requests = []

    def respond(route):
        requests.append(route.request.method)
        route.fulfill(status=status, content_type='application/json', body=json.dumps({
            'ok': status == 200, 'profile': 'public-news-title-to-docs-v1', 'releases': rows}))

    page.route('**/api/workflow-connections', respond)
    return requests


def test_public_listing_is_text_only_and_does_not_execute_a_connection(chat_page):
    page, _, _, errors, _ = chat_page
    attack = '<img src=x onerror="window.__connectionXss=1">'
    requests = listing(page, [release(title=attack)])
    page.goto('https://agentconcierge.biz/#workflows')
    section = page.locator('#frontPublicConnections')
    playwright.expect(section).to_be_visible()
    playwright.expect(section.locator('h4')).to_have_text(attack)
    playwright.expect(section.get_by_role('link', name='Review connection')).to_have_attribute(
        'href', '/connections/' + IDENTITY)
    assert section.locator('img, [onerror], a[href^="javascript:"]').count() == 0
    assert page.evaluate('window.__connectionXss || 0') == 0
    assert requests == ['GET']
    assert not errors


@pytest.mark.parametrize('changes', [
    {'id': '../admin'}, {'url': 'javascript:alert(1)'},
    {'url': 'https://outside.example/connections/' + IDENTITY},
    {'expires': 0}, {'expires': None}, {'title': '\ud55c\uae00'},
])
def test_malformed_or_expired_listing_cannot_create_a_link(chat_page, changes):
    page, _, _, errors, _ = chat_page
    requests = listing(page, [release(**changes)])
    page.goto('https://agentconcierge.biz/#workflows')
    playwright.expect(page.locator('#frontWfCanvasView')).to_be_visible()
    playwright.expect(page.locator('#frontPublicConnections')).to_be_hidden()
    assert page.locator('#frontPublicConnectionList a').count() == 0
    assert requests == ['GET'] and not errors


@pytest.mark.parametrize('status', [404, 503])
def test_unavailable_connection_registry_preserves_legacy_workflows(chat_page, status):
    page, _, _, errors, _ = chat_page
    requests = listing(page, [], status=status)
    page.goto('https://agentconcierge.biz/#workflows')
    playwright.expect(page.locator('#frontPublicConnections')).to_be_hidden()
    playwright.expect(page.locator('#btnFrontRunWorkflow')).to_be_visible()
    playwright.expect(page.locator('#btnFrontExportApp')).to_be_visible()
    playwright.expect(page.locator('#frontWfActiveName')).to_have_text('Daily Tech News & AI Research Digest')
    assert requests == ['GET'] and not errors


@pytest.mark.parametrize('scheme', ['light', 'dark'])
def test_optional_connection_links_fit_mobile_and_have_local_lucide_icons(chat_page, scheme):
    page, _, _, errors, _ = chat_page
    page.set_viewport_size({'width': 390, 'height': 844})
    page.emulate_media(color_scheme=scheme, reduced_motion='reduce')
    listing(page, [release()])
    page.goto('https://agentconcierge.biz/#workflows')
    section = page.locator('#frontPublicConnections')
    playwright.expect(section).to_be_visible()
    assert section.evaluate('el => el.scrollWidth <= el.clientWidth + 1')
    icon = section.locator('a svg.lucide')
    assert icon.count() == 1 and icon.get_attribute('aria-hidden') == 'true'
    section.get_by_role('link', name='Review connection').focus()
    playwright.expect(section.get_by_role('link', name='Review connection')).to_be_focused()
    assert not errors
