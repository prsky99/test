"""Click the current first-party recipe, change its inputs, and run locally."""
# ruff: noqa: F401,F811
import json
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from agent_market.gateway.dashboard import dashboard_router
from tests.test_front_workflow_browser import browser
from tests.test_owned_data_agents import engine
from tests.test_owned_data_agents_activation import operating

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def test_live_recipe_clicks_bind_inputs_and_execute_the_local_agent(browser, operating):
    front, _, _, source_calls, _ = operating
    app = FastAPI()
    app.include_router(dashboard_router(front.store, front.store._path, 'fixture-browser', None,
                                      front=front, ssl_manager=Mock(get_status=lambda: {})))
    client = TestClient(app, base_url='https://admin.test')
    context = browser.new_context(viewport={'width': 1600, 'height': 1100})
    errors, external = [], []
    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'admin.test':
            external.append(request.url)
            return route.abort()
        result = client.request(request.method, url.path+('?' + url.query if url.query else ''),
                                headers=request.headers, content=request.post_data)
        route.fulfill(status=result.status_code, body=result.content,
            headers={k: v for k, v in result.headers.items()
                     if k not in ('content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', serve)
    try:
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('https://admin.test/admin/ui')
        page.locator('#adminLoginUsername').fill('sadmin')
        page.locator('#adminLoginPassword').fill('sadmin')
        page.locator('#adminLoginSubmitBtn').click()
        expect(page.locator('#adminLoginModal')).to_be_hidden()
        page.locator('[data-tab="test"]').click()
        # Two buttons for each owned test agent (staging.TEST_IDS).
        from agent_market.owned_data_agents.staging import TEST_IDS
        expect(page.locator('#testWalkthroughCards button')).to_have_count(2 * len(TEST_IDS))
        recipe = page.locator('button[data-live-recipe="technology-news"]').first
        recipe.click()
        page.wait_for_function('() => testbenchState.selectedAgent && !testbenchState.running')
        # The recipe writes its own inputs after the spec loads; edit only once it is done.
        expect(recipe).to_be_enabled()
        arguments = {'query': 'browser administrator climate research', 'limit': 1}
        page.locator('#testArgsJson').fill(json.dumps(arguments))
        before = len(source_calls)
        page.locator('#testRunBtn').click()
        expect(page.locator('#testResStatusBadge')).to_contain_text('성공')
        expect(page.locator('#testOutputFormatted')).to_contain_text(arguments['query'])
        assert len(source_calls) > before
        assert all('/owned-data/' not in url for url in external)
        folder = Path('reports/admin-current-alignment-2026-10-21')
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder/'local-live-example-result.png'), full_page=True)
        assert not errors and not external
    finally:
        context.close()
        client.close()
