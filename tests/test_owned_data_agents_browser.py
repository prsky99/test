"""Future four-example/three-template composition in isolated current frontend."""
from io import BytesIO
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile

from fastapi.testclient import TestClient
from playwright.sync_api import expect
import pytest

from agent_market import workflow_templates
from agent_market.concierge import testbench_examples
from agent_market.concierge.front import Front, clear_front_caches, create_front_app
from agent_market.concierge.proxy import McpProxy
from agent_market.owned_data_agents.catalog import SPECS
from agent_market.owned_data_agents.staging import recipes, definitions, TEST_IDS
from agent_market.owned_data_agents.verification import ORIGIN, isolated_world
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_owned_data_agents import engine  # noqa: F401
from tests.workflow_package_helpers import open_hosted_package


def confirmed_run(page, client, button):
    """Check the newly submitted run, never a previous success in a modal."""
    with page.expect_response(lambda r: r.request.method == 'POST' and urlsplit(r.url).path == '/api/workflows/run') as submitted:
        button.click()
    response = submitted.value
    assert response.status == 202
    job = response.json()
    until = time.monotonic() + 15
    while time.monotonic() < until:
        reply = client.get('/api/workflows/runs/' + job['run_id'], headers={'X-Workflow-Key': job['run_key']})
        assert reply.status_code == 200
        state = reply.json()
        if state['status'] in ('succeeded', 'failed', 'cancelled'):
            assert state['status'] == 'succeeded', state
            return
        page.wait_for_timeout(100)
    raise AssertionError('The newly submitted workflow did not complete.')


@pytest.fixture
def preview(tmp_path, engine, monkeypatch):  # noqa: F811
    core, calls, _ = engine
    # Only this isolated test process substitutes the future recipe definitions.
    monkeypatch.setattr(workflow_templates, 'definitions', lambda: definitions(ORIGIN))
    monkeypatch.setattr(testbench_examples, 'RECIPES', recipes(ORIGIN))
    clear_front_caches()
    with isolated_world(tmp_path / 'world', engine=core) as world:
        front = Front(world.store, allow_private=True)
        front.proxy = McpProxy(world.store, allow_private=True, http=world.http)
        front.workflows.proxy = front.proxy
        client = TestClient(create_front_app(front, manage_book_lifecycle=False))
        try:
            yield world, client, calls
        finally:
            client.close()
            front.book.close()
            clear_front_caches()


def test_staged_four_examples_and_three_templates_execute_and_download(preview, browser, tmp_path):  # noqa: F811
    world, client, calls = preview
    errors, external = [], []
    context = browser.new_context(accept_downloads=True)
    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz':
            external.append(request.url)
            return route.abort()
        reply = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
            content=request.post_data, headers={key: value for key, value in request.headers.items()
                if key in ('accept', 'content-type', 'x-workflow-key')})
        route.fulfill(status=reply.status_code, body=reply.content,
            headers={key: value for key, value in reply.headers.items()
                     if key not in ('content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', serve)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto('https://agentconcierge.biz/#test')
        expect(page.locator('.pearl-example-choice')).to_have_count(len(TEST_IDS))
        for identity in TEST_IDS:
            page.locator('.pearl-example-choice[data-recipe="' + identity + '"]').click()
            expect(page.locator('#tbRunBtn')).to_be_enabled()
            expect(page.locator('#pearlTestExampleName')).to_have_text(SPECS[identity]['name'])
            with page.expect_response(lambda r: r.request.method == 'POST' and urlsplit(r.url).path == '/api/test/execute') as executed:
                page.locator('#tbRunBtn').click()
            assert executed.value.status == 200
            assert executed.value.json()['execution_succeeded'] is True
            expect(page.locator('#tbKpiStatus')).to_have_text('Completed', timeout=15000)
        page.screenshot(path=str(tmp_path / 'four-owned-examples.png'), full_page=True)
        page.locator('#navTabs [data-tab="workflows"]').click()
        page.locator('#btnFrontWfViewTemplates').click()
        expect(page.locator('#frontTemplatesGrid .template-card')).to_have_count(3)
        ids = page.locator('#frontTemplatesGrid .template-card').evaluate_all('(nodes) => nodes.map(n => n.dataset.templateId)')
        for wid in ids:
            page.goto('https://agentconcierge.biz/#workflows')
            page.locator('#btnFrontWfViewTemplates').click()
            page.locator('#frontTemplatesGrid [data-template-id="'+wid+'"]').get_by_role('button',name='Use workflow',exact=True).click()
            expect(page.locator('#btnFrontRunWorkflow')).to_be_enabled()
            confirmed_run(page, client, page.locator('#btnFrontRunWorkflow'))
            expect(page.locator('#frontWfRunModalBody')).to_contain_text('Workflow: succeeded', timeout=15000)
            page.locator('#uxFullRunDetails').click()
            expect(page.locator('#frontWfRunModal')).to_be_visible()
            page.locator('#frontWfRunModal').get_by_role('button', name='Close Dialog', exact=True).click()
            with page.expect_download() as download_info:
                page.locator('#btnFrontExportApp').click()
            download = download_info.value
            raw = Path(download.path()).read_bytes()
            with ZipFile(BytesIO(raw)) as archive:
                combined = b'\n'.join(archive.read(name) for name in archive.namelist())
                manifest = json.loads(archive.read('app-manifest.json'))
                assert manifest['gateway'] == 'https://agentconcierge.biz'
                assert manifest['execution'] == 'published-workflow'
                assert b'/api/workflows/run' in combined and b'owned-data-agents.example' not in combined
            package = tmp_path / ('workflow-' + wid + '.zip')
            package.write_bytes(raw)
            open_hosted_package(page, package, root='https://customer.example/preview/' + wid + '/')
            confirmed_run(page, client, page.locator('#runAppBtn'))
            expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded', timeout=15000)
        assert not errors and not external
        assert any(request.url.host == 'api.osv.dev' for request in calls)
        # The test never creates provider quality grades or approval shortcuts.
        assert all(not world.store.resource(rid).get('eval_grade') for rid in world.resources.values())
    finally:
        context.close()
