"""Current pages use isolated API stores; all browser destinations are intercepted."""
# ruff: noqa: F401,F811
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser
from tests.test_workflow_discovery import discovery
from tests.test_workspace_human_studio_browser import launch
from tests.test_customer_template_hub import hub_world, customer_flow, typed_release_world, typed_world, routing

OUTPUT = Path('reports/discovery-chat-workspace-upgrade-development-2026-10-25')


@pytest.mark.parametrize('standalone', [False, True])
def test_public_workflow_negative_query_matches_current_api(browser, discovery, standalone):
    store, _, client, _ = discovery
    context = browser.new_context(offline=True)
    errors = []

    def forward(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz':
            errors.append('Unexpected destination'); route.abort(); return
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
            content=request.post_data, headers={k:v for k,v in request.headers.items() if k in ('accept','content-type')})
        route.fulfill(status=response.status_code, body=response.content,
            headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})

    context.route('**/*', forward)
    page = context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
    try:
        page.goto('https://agentconcierge.biz/new/en/workflows.html' if standalone else 'https://agentconcierge.biz/#workflows')
        page.locator('#btnFrontWfViewTemplates').click()
        page.locator('#frontTmplSearchInput').fill('news and papers; exclude GDP')
        grid = page.locator('#frontTemplatesGrid')
        expect(grid.locator('.template-card')).to_have_count(1)
        expect(grid).to_contain_text('Daily Tech News')
        assert not errors and store.query('SELECT COUNT(*) FROM workflow_runs')[0][0] == 0
        page.screenshot(path=str(OUTPUT/('workflow-exclusion-' + str(standalone) + '.png')), full_page=True)
    finally:
        context.close()


@pytest.mark.parametrize('width', [390,1440])
def test_workspace_source_preserving_repair_and_review_are_visible_without_execution(hub_world, browser, width):
    x, *_ = hub_world
    context, page, errors, requests, calls, model_client = launch(x, browser, width)
    before = len(x.w.calls)
    try:
        # The mock model always suggests Python; it must not drop a requested product.
        page.locator('#objective').fill('Find documentation about FastAPI and PostgreSQL using two steps')
        page.locator('#model-consent').check(); page.locator('#model').click()
        page.wait_for_function('()=>!busy')
        expect(page.locator('#status')).to_have_text('AI proposal ready. Review the steps and exact inputs before saving.')
        expect(page.locator('#human-builder')).to_contain_text('FastAPI')
        expect(page.locator('#human-builder')).to_contain_text('PostgreSQL')
        assert len(calls) == 1 and len(x.w.calls) == before
        assert not page.locator('pre:visible').count()
        page.locator('#human-nav-create').click()
        page.locator('#objective').fill('Find Python documentation using two steps')
        page.locator('#model-consent').check(); page.locator('#model').click()
        page.wait_for_function('()=>!busy')
        expect(page.locator('#status')).to_have_text('AI proposal ready. Review the steps and exact inputs before saving.')
        assert len(calls) == 2 and len(x.w.calls) == before
        assert not any(method == 'POST' and path.endswith(('/commits','/runs')) for method,path in requests)
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(OUTPUT/('workspace-quality-' + str(width) + '.png')), full_page=True)
    finally:
        context.close(); model_client.close()
