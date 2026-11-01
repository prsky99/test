"""Run the three published hub entries through actual admin and public controls."""
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.dashboard import dashboard_router
from tests.test_admin_security_browser import browser
from tests.test_workflow_runtime_browser import login
from tests.test_workflow_template_catalog import verified
from tests.workflow_package_helpers import open_hosted_package

playwright = pytest.importorskip('playwright.sync_api')


def test_three_template_hub_runs_and_connected_download(browser, verified, tmp_path,rotated_bootstrap_admin):
    store, _ = verified
    proxy = store._workflow_runtime.proxy
    front = Front(store, allow_private=True)
    front.workflows.proxy = front.proxy = proxy
    app = FastAPI(); app.include_router(dashboard_router(store, store.path, 'template-browser', None, front=front))
    admin = TestClient(app, base_url='https://admin.test')
    public = TestClient(create_front_app(front), base_url='https://agentconcierge.biz')
    context = browser.new_context(accept_downloads=True); page = context.new_page(); errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.scheme == 'file': return route.continue_()
        client = admin if url.hostname == 'admin.test' else public if url.hostname == 'agentconcierge.biz' else None
        if client is None: return route.abort()
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''), content=request.post_data, headers=request.headers)
        route.fulfill(status=response.status_code, body=response.content, headers={k: v for k, v in response.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')})

    context.route('**/*', serve)
    try:
        login(page); page.locator('#btnWfViewTemplates').click()
        playwright.expect(page.locator('#templatesGrid .template-card')).to_have_count(3)
        for workflow in store.list_workflows(is_template=1)[0]:
            card = page.locator(f'#templatesGrid [data-tmpl-id="{workflow["id"]}"]')
            card.locator('.btn-run-tmpl').click()
            playwright.expect(page.locator('#wfRunStatus')).to_have_text('Execution: succeeded')
            page.locator('#workflowHistory').click()
            playwright.expect(page.locator('#workflowHistoryList')).to_contain_text('succeeded')
            page.locator('#closeWfRunBtn').click()
        page.goto('https://agentconcierge.biz/#workflows')
        playwright.expect(page.locator('#frontWfNodesLayer .wf-node')).to_have_count(3)
        page.locator('#btnFrontRunWorkflow').click()
        playwright.expect(page.locator('#frontWfRunModalBody')).to_contain_text('Workflow: succeeded')
        assert 'Internal model' not in page.locator('#frontWfRunModalBody').inner_text()
        if page.locator('#uxFullRunDetails').count():
            playwright.expect(page.locator('#frontWfRunModal')).to_be_hidden()
            playwright.expect(page.locator('#pearlWorkflowResult')).to_contain_text('Workflow: succeeded')
            page.locator('#uxFullRunDetails').click()
        playwright.expect(page.locator('#frontWfRunModal')).to_be_visible()
        page.locator('#frontWfRunModal').get_by_role('button', name='Close Dialog', exact=True).click()
        with page.expect_download() as event: page.locator('#btnFrontExportApp').click()
        path = tmp_path / 'digest-webapp.zip'; event.value.save_as(path)
        open_hosted_package(page, path); page.locator('#runAppBtn').click()
        playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded')
        assert not errors
    finally:
        context.close(); admin.close(); public.close()
        for future in list(front.workflows.futures.values()): future.result(timeout=5)
