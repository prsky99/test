"""Preserve explicit requests when the initial catalog refresh finishes late."""
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from agent_market.concierge.testbench_examples import RECIPES
from tests.test_catalog_policy_and_live_examples import examples
from tests.test_fast_single_recommendation import catalog
from tests.test_front_workflow_browser import browser

# These cases exercise the fallback's one-click Run Now interaction. The
# published choose/review/run flow is covered by the current presentation suite.
pytestmark = pytest.mark.usefixtures('legacy_public_entry')


@pytest.fixture
def initialized_page(browser, examples):
    _, _, client, calls = examples
    context = browser.new_context()
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        assert url.hostname == 'agentconcierge.biz'
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                  content=request.post_data, headers={
                                      k: v for k, v in request.headers.items()
                                      if k in ('accept', 'content-type', 'origin')})
        route.fulfill(status=response.status_code, body=response.content, headers={
            k: v for k, v in response.headers.items()
            if k not in ('content-length', 'content-encoding', 'transfer-encoding')})

    context.route('**/*', serve)
    page.goto('https://agentconcierge.biz/#test')
    expect(page.locator('#tbRunBtn')).to_be_enabled()
    page.wait_for_load_state('networkidle')
    yield page, calls, errors
    context.close()


@pytest.mark.parametrize('refresh_order', ['presets-first', 'explore-first'])
def test_late_catalog_responses_preserve_recipe_callback_and_inputs(initialized_page, refresh_order):
    page, calls, errors = initialized_page
    page.evaluate('''async () => {
      const original = api;
      const presets = await original('/api/test/presets');
      const explore = await original('/api/explore?limit=100');
      const recipe = presets.live_examples.find(r => r.id === 'camera-docs');
      const detail = await original('/api/agents/' + recipe.resource_id);
      const details = [];
      const releases = {};
      api = (path, ...args) => {
        if (path === '/api/test/presets') return new Promise(resolve => {releases.presets = () => resolve(presets);});
        if (path === '/api/explore?limit=100') return new Promise(resolve => {releases.explore = () => resolve(explore);});
        if (path === '/api/agents/' + recipe.resource_id) return new Promise(resolve => details.push(() => resolve(detail)));
        return original(path, ...args);
      };
      loadTestbenchUI();
      window.initializationTest = {original, releases, details, recipe};
    }''')
    page.get_by_role('button', name='Run Now', exact=True).nth(1).click()
    for key in (['presets', 'explore'] if refresh_order == 'presets-first' else ['explore', 'presets']):
        page.evaluate('(key) => initializationTest.releases[key]()', key)
    page.evaluate('() => initializationTest.details.forEach(release => release())')
    expect(page.locator('#tbKpiStatus')).to_have_text('Completed')
    assert len(calls) == 1
    assert calls[0]['name'] == 'search_docs'
    assert calls[0]['arguments'] == {'query': 'camera permissions android ios', 'limit': 2}
    assert not errors
    if refresh_order=='presets-first':
        notice=page.get_by_role('button',name='Reject Non-Essential',exact=True)
        if notice.is_visible():notice.click()
        acknowledgment=page.get_by_role('button',name='Acknowledge',exact=True)
        if acknowledgment.is_visible():acknowledgment.click()
        page.locator('#tbHistoryTable').scroll_into_view_if_needed()
        page.screenshot(path='reports/advancement-r01-2026-10-17/initialization-fixed.png')
    page.evaluate('() => {api = initializationTest.original; delete window.initializationTest;}')


def test_background_refresh_preserves_edited_inputs(initialized_page):
    page, _, errors = initialized_page
    page.locator('#tbArgsEditor').fill(json.dumps({'topic': 'custom-topic', 'limit': 7}))
    page.evaluate('() => loadTestbenchUI()')
    page.wait_for_load_state('networkidle')
    assert json.loads(page.locator('#tbArgsEditor').input_value()) == {'topic': 'custom-topic', 'limit': 7}
    assert not errors


def test_another_recipe_cannot_dispatch_while_a_test_is_running(initialized_page):
    page,calls,errors=initialized_page
    page.evaluate('''() => {
      const original = api;
      window.dispatchTest = {original, queued: []};
      api = (path, ...args) => path === '/api/test/execute'
        ? new Promise(resolve => dispatchTest.queued.push(() => original(path, ...args).then(resolve)))
        : original(path, ...args);
    }''')
    page.get_by_role('button',name='Run Now',exact=True).nth(0).click()
    expect(page.locator('#tbKpiStatus')).to_have_text('Probing...')
    page.get_by_role('button',name='Run Now',exact=True).nth(1).click()
    assert page.evaluate('() => dispatchTest.queued.length')==1
    page.evaluate('() => dispatchTest.queued[0]()')
    expect(page.locator('#tbKpiStatus')).to_have_text('Completed')
    assert len(calls)==1 and calls[0]['name']==RECIPES[0][4]
    assert not errors
    page.evaluate('() => {api=dispatchTest.original;delete window.dispatchTest;}')
