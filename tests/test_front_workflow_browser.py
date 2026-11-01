"""Exercise public workflow controls and exported apps in a real browser."""

import json
from urllib.parse import urlsplit

import pytest
from starlette.testclient import TestClient

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.store import Store
from tests.workflow_package_helpers import open_hosted_package

playwright = pytest.importorskip("playwright.sync_api")
DEFAULT_NAME = "Daily Tech News & AI Research Digest"


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def workflow_page(browser, tmp_path):
    store = Store(str(tmp_path / "workflows.db"))
    client = TestClient(create_front_app(Front(store, allow_private=True)))
    context = browser.new_context(accept_downloads=True)
    requests = []

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.scheme == "file":
            route.continue_()
            return
        if url.hostname != "agentconcierge.biz":
            route.abort()
            return
        if url.path == "/api/workflows/run":
            requests.append(request.post_data_json)
        response = client.request(
            request.method,
            url.path + ("?" + url.query if url.query else ""),
            content=request.post_data,
            headers={"accept": request.headers.get("accept", ""),
                     "x-workflow-key": request.headers.get("x-workflow-key", ""),
                     "content-type": request.headers.get("content-type", "")},
        )
        route.fulfill(status=response.status_code, body=response.content,
                      headers={k:v for k,v in response.headers.items() if k not in ("content-length","content-encoding","transfer-encoding")})

    context.route("**/*", serve)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page, requests, errors
    context.close()
    client.close()


def test_default_workflow_run_and_download(workflow_page, tmp_path):
    page, requests, errors = workflow_page
    page.goto("https://agentconcierge.biz/#workflows")
    playwright.expect(page.locator("#frontWfActiveName")).to_have_text(DEFAULT_NAME)
    playwright.expect(page.locator("#frontWfNodesLayer .wf-node")).to_have_count(3)

    page.locator("#btnFrontRunWorkflow").click()
    playwright.expect(page.locator("#frontWorkflowAvailability")).to_be_visible()
    playwright.expect(page.locator("#frontWorkflowAvailability")).to_contain_text("The registered agent is unavailable.")
    page.wait_for_function("() => frontWorkflowRunning === false")
    playwright.expect(page.locator("#frontWfRunModal")).not_to_be_visible()
    playwright.expect(page.locator("#btnFrontRunWorkflow")).to_be_enabled()
    assert requests == [], "Missing bindings must be rejected before submitting a workflow run."

    with page.expect_download() as download_event:
        page.locator("#btnFrontExportApp").click()
    download = download_event.value
    assert download.suggested_filename == "daily-tech-news-ai-research-digest-webapp.zip"
    app_path = tmp_path / download.suggested_filename
    download.save_as(app_path)
    open_hosted_package(page, app_path)
    playwright.expect(page.locator("h1")).to_have_text(DEFAULT_NAME)
    playwright.expect(page.locator("#appStatus")).to_have_text("Ready")
    assert "${" not in page.content()
    page.locator("#runAppBtn").click()
    playwright.expect(page.locator("#appStatus")).to_have_text("Workflow: failed")
    playwright.expect(page.locator("#runAppBtn")).to_be_enabled()
    assert not errors


@pytest.mark.parametrize("saved_name", ["Flight & Forex Settlement Pipeline", DEFAULT_NAME, "My saved pipeline"])
def test_legacy_default_migration_and_reset(workflow_page, saved_name):
    page, _, errors = workflow_page
    saved = {"name": saved_name, "nodes": [{"id": "custom", "name": "Saved node", "type": "agent"}], "edges": []}
    if saved_name == DEFAULT_NAME:
        saved.update(version=2, template_id=999999)
    page.add_init_script("localStorage.setItem('front_workflow_canvas', " + json.dumps(json.dumps(saved)) + ");")
    page.goto("https://agentconcierge.biz/#workflows")
    expected_name = DEFAULT_NAME if saved_name.startswith("Flight") or saved_name == DEFAULT_NAME else saved_name
    playwright.expect(page.locator("#frontWfActiveName")).to_have_text(expected_name)
    page.locator("#btnFrontResetCanvas").click()
    playwright.expect(page.locator("#frontWfActiveName")).to_have_text(DEFAULT_NAME)
    playwright.expect(page.locator("#frontWfNodesLayer .wf-node")).to_have_count(3)
    assert page.evaluate("JSON.parse(localStorage.getItem('front_workflow_canvas')).version") == 2
    assert not errors


def test_run_error_recovers_button(workflow_page):
    page, _, errors = workflow_page
    page.goto("https://agentconcierge.biz/#workflows")
    selected = page.evaluate("frontActiveTemplateId")
    templates = page.evaluate("frontTemplatesCache")
    assert any(template['id'] == selected for template in templates)
    selected_hash = next(template['definition_hash'] for template in templates if template['id'] == selected)
    # This test isolates run-transport recovery after a successful preflight.
    # The synthetic availability is supplied at the HTTP boundary, not by
    # replacing application methods or contacting an actual provider.
    for template in templates:
        if template['id'] == selected:
            template['execution_availability'] = {
                'available': True, 'reason_code': 'READY', 'message': 'Controlled preflight accepted.',
                'http_status': None, 'checked_at': None, 'scope': 'recorded_preflight'}
    preflights = []
    attempts = []

    def accept_preflight(route):
        assert route.request.method == 'GET'
        preflights.append(route.request.url)
        route.fulfill(status=200, content_type='application/json',
                      body=json.dumps({'ok': True, 'templates': templates, 'count': len(templates)}))

    def reject_run(route):
        assert route.request.method == 'POST'
        attempts.append(route.request.post_data_json)
        route.fulfill(status=503, content_type='application/json', body='{"detail":"Please retry later"}')

    page.route("**/api/workflows/templates", accept_preflight)
    page.route("**/api/workflows/run", reject_run)
    page.locator("#btnFrontRunWorkflow").click()
    playwright.expect(page.locator('#frontToastContainer')).to_contain_text('Please retry later')
    playwright.expect(page.locator("#btnFrontRunWorkflow")).to_have_text("Run Workflow")
    playwright.expect(page.locator("#btnFrontRunWorkflow")).to_be_enabled()
    playwright.expect(page.locator("#frontWfRunModal")).not_to_be_visible()
    assert preflights and len(attempts) == 1
    assert attempts[0] == {'template_id': selected, 'definition_hash': selected_hash}
    assert not errors
