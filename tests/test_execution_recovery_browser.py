"""Unavailable bindings are explained while healthy Test/workflows still execute."""

import json
import copy
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from agent_market.concierge.front import clear_front_caches
from agent_market.workflow_templates import NEWS_URL, bind_resources, definitions
from tests.test_execution_availability import published  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')
ORIGIN = 'https://agentconcierge.biz'


@pytest.fixture(params=['legacy', 'published'])
def recovery_page(browser, catalog, published, monkeypatch, request):
    presentation = request.param
    if presentation == 'legacy':
        from agent_market.concierge import pearl_view
        monkeypatch.setattr(pearl_view, 'public_page_available', lambda: False)
    store, front, client, ids, workflow_ids, calls = published
    _, _, _, add, now = catalog
    monkeypatch.setenv('ADMIN_TOKEN', 'isolated-token-' + 'x' * 48)
    monkeypatch.setenv('DEPLOYMENT_MODE', 'production')
    monkeypatch.setenv('PUBLIC_TLS_TERMINATION', 'proxy')
    add('Unavailable news connection', url=NEWS_URL, health_status='down',
        last_status_code=500, last_check_at=now)
    definition = definitions()[0]
    workflows, _ = store.list_workflows(is_template=1, active_only=True, limit=100)
    news = next(item for item in workflows if item['name'] == definition['name'])
    store.update_workflow(news['id'], bind_resources(store, definition))
    news = store.get_workflow(news['id'])
    clear_front_caches()
    context = browser.new_context()
    state = SimpleNamespace(page=None, context=context, store=store, client=client,
                            healthy_ids=workflow_ids, resource_ids=ids, news=news,
                            calls=calls, requests=[], errors=[], external=[], presentation=presentation)

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz':
            state.external.append(url.hostname)
            route.abort()
            return
        state.requests.append((request.method, url.path))
        response = client.request(
            request.method, url.path + ('?' + url.query if url.query else ''),
            content=request.post_data,
            headers={key: value for key, value in request.headers.items()
                     if key in ('accept', 'content-type', 'origin', 'x-workflow-key')},
        )
        route.fulfill(status=response.status_code, body=response.content,
                      headers={key: value for key, value in response.headers.items()
                               if key not in ('content-length', 'content-encoding', 'transfer-encoding')})

    context.route('**/*', serve)
    page = context.new_page()
    page.on('pageerror', lambda error: state.errors.append(str(error)))
    state.page = page
    try:
        yield state
    finally:
        context.close()


def _open_healthy_workflow(state):
    state.page.goto(ORIGIN + '/#workflows')
    state.page.wait_for_function('id => frontActiveTemplateId === id', arg=state.news['id'])
    state.page.evaluate('id => loadFrontTemplateToCanvas(id)', state.healthy_ids[0])
    playwright.expect(state.page.locator('#btnFrontRunWorkflow')).to_be_enabled()


def test_news_default_is_explicit_and_another_healthy_template_can_be_run(recovery_page):
    state = recovery_page
    state.page.goto(ORIGIN + '/#workflows')
    state.page.wait_for_function('id => frontActiveTemplateId === id', arg=state.news['id'])
    playwright.expect(state.page.locator('#frontWfActiveName')).to_have_text(state.news['name'])
    playwright.expect(state.page.locator('#btnFrontRunWorkflow')).to_be_enabled()
    playwright.expect(state.page.locator('#frontWorkflowAvailability')).to_contain_text('HTTP 500')
    assert not state.calls and not any(method == 'POST' for method, _ in state.requests)
    _open_healthy_workflow(state)
    assert state.page.evaluate('frontActiveTemplateId') != state.news['id']
    state.page.locator('#btnFrontRunWorkflow').click()
    playwright.expect(state.page.locator('#frontWfRunModalBody')).to_contain_text('Workflow: succeeded')
    assert len(state.calls) == 2
    assert ('POST', '/api/workflows/run') in state.requests
    assert not state.errors and not state.external


def test_saved_unavailable_canvas_remains_selected_with_reason_and_no_dispatch(recovery_page):
    state = recovery_page
    saved = {'version': 2, 'name': 'Saved unavailable news workflow',
             'template_id': state.news['id'], 'nodes': state.news['nodes'], 'edges': state.news['edges']}
    state.context.add_init_script(
        "localStorage.setItem('front_workflow_canvas', " + json.dumps(json.dumps(saved)) + ');')
    state.page.goto(ORIGIN + '/#workflows')
    playwright.expect(state.page.locator('#frontWfActiveName')).to_have_text(saved['name'])
    assert state.page.evaluate('frontActiveTemplateId') == state.news['id']
    playwright.expect(state.page.locator('#frontWorkflowAvailability')).to_contain_text('HTTP 500')
    playwright.expect(state.page.locator('#frontWorkflowAvailability')).to_be_visible()
    # The action remains available to recheck recovery; failed preflight must
    # never create a workflow run or replace the saved canvas selection.
    prior = state.requests.count(('GET', '/api/workflows/templates'))
    state.page.locator('#btnFrontRunWorkflow').click()
    state.page.wait_for_function("() => !document.getElementById('btnFrontRunWorkflow').disabled")
    assert state.requests.count(('GET', '/api/workflows/templates')) > prior
    assert state.page.evaluate('frontActiveTemplateId') == state.news['id']
    playwright.expect(state.page.locator('#frontWorkflowAvailability')).to_contain_text('HTTP 500')
    assert ('POST', '/api/workflows/run') not in state.requests and not state.calls
    assert not state.errors and not state.external


def test_explicit_run_revalidates_stale_healthy_cache_and_refuses_before_post(recovery_page):
    state = recovery_page
    _open_healthy_workflow(state)
    selected = state.page.evaluate('frontActiveTemplateId')
    workflow = state.store.get_workflow(selected)
    rid = workflow['nodes'][1]['resource_id']
    with state.store.tx() as db:
        db.execute("UPDATE resources SET health_status='down',last_status_code=500 WHERE id=?", (rid,))
    prior = len([request for request in state.requests if request == ('GET', '/api/workflows/templates')])
    state.page.locator('#btnFrontRunWorkflow').click()
    playwright.expect(state.page.locator('#frontWorkflowAvailability')).to_contain_text('HTTP 500')
    playwright.expect(state.page.locator('#btnFrontRunWorkflow')).to_be_enabled()
    assert len([request for request in state.requests if request == ('GET', '/api/workflows/templates')]) > prior
    assert ('POST', '/api/workflows/run') not in state.requests and not state.calls
    assert state.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0] == 0
    assert not state.errors and not state.external


def test_healthy_live_test_recipe_still_completes_under_production_proxy_settings(recovery_page):
    state = recovery_page
    state.page.goto(ORIGIN + '/#test')
    if state.presentation == 'legacy':
        docs = state.page.locator('.testbench-recipe-card').filter(has_text='Camera documentation')
        playwright.expect(docs.get_by_role('button', name='Run Now', exact=True)).to_be_enabled()
        docs.get_by_role('button', name='Run Now', exact=True).click()
    else:
        docs = state.page.locator('.pearl-example-choice').filter(has_text='Camera documentation')
        playwright.expect(docs).to_be_enabled()
        docs.click()
        assert not state.calls
        state.page.locator('#tbRunBtn').click()
    playwright.expect(state.page.locator('#tbKpiStatus')).to_have_text('Completed')
    assert [call['name'] for call in state.calls] == ['search_docs']
    assert ('POST', '/api/test/execute') in state.requests
    assert not state.errors and not state.external


def test_unavailable_recipe_shows_recorded_reason_and_never_dispatches(recovery_page):
    state = recovery_page
    state.page.goto(ORIGIN + '/#test')
    selector = '.testbench-recipe-card' if state.presentation == 'legacy' else '.pearl-example-choice'
    news = state.page.locator(selector).filter(has_text='Technology news')
    playwright.expect(news).to_contain_text('HTTP 500')
    if state.presentation == 'legacy':
        playwright.expect(news.get_by_role('button', name='Run Now', exact=True)).to_be_disabled()
        playwright.expect(news.get_by_role('button', name='Load Recipe', exact=True)).to_be_disabled()
    else:
        playwright.expect(news).to_be_disabled()
    assert ('POST', '/api/test/execute') not in state.requests and not state.calls
    assert not state.errors and not state.external


@pytest.mark.parametrize('change', ['selection', 'definition'], ids=['changed-template', 'changed-definition'])
def test_delayed_run_preflight_cannot_reuse_old_intent_or_fallback_consent(recovery_page, change):
    state = recovery_page
    _open_healthy_workflow(state)
    selected = state.page.evaluate('frontActiveTemplateId')
    baseline = state.client.get('/api/workflows/templates').json()
    pending = []
    hold = [False]

    def templates_response(payload):
        result = copy.deepcopy(payload)
        # Supply a reviewed-fallback UI scenario at the HTTP boundary. No
        # fallback authorization is created and no run may be dispatched.
        for template in result['templates']:
            if template['id'] == selected:
                template['fallback_available'] = True
        return result

    def serve_templates(route):
        assert route.request.method == 'GET'
        if hold[0]:
            pending.append(route)
        else:
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps(templates_response(baseline)))

    state.page.route('**/api/workflows/templates', serve_templates)
    state.page.evaluate('() => loadFrontTemplates(true)')
    state.page.evaluate('id => loadFrontTemplateToCanvas(id)', selected)
    playwright.expect(state.page.locator('#frontFallbackConsentGroup')).to_be_visible()
    state.page.locator('#frontFallbackConsent').check()
    hold[0] = True
    state.page.locator('#btnFrontRunWorkflow').click()
    deadline = time.monotonic() + 3
    while not pending and time.monotonic() < deadline:
        state.page.wait_for_timeout(10)
    assert len(pending) == 1

    if change == 'selection':
        other = next(wid for wid in state.healthy_ids if wid != selected)
        state.page.evaluate('id => loadFrontTemplateToCanvas(id)', other)
        expected_selection = other
        fresh = baseline
    else:
        workflow = state.store.get_workflow(selected)
        workflow['nodes'][1]['name'] = 'Changed published step'
        state.store.update_workflow(selected, workflow)
        fresh = state.client.get('/api/workflows/templates').json()
        before = next(t['definition_hash'] for t in baseline['templates'] if t['id'] == selected)
        after = next(t['definition_hash'] for t in fresh['templates'] if t['id'] == selected)
        assert before != after
        expected_selection = selected

    pending[0].fulfill(status=200, content_type='application/json',
                       body=json.dumps(templates_response(fresh)))
    state.page.wait_for_function('() => frontWorkflowRunning === false')
    assert state.page.evaluate('frontActiveTemplateId') == expected_selection
    playwright.expect(state.page.locator('#frontFallbackConsent')).not_to_be_checked()
    assert ('POST', '/api/workflows/run') not in state.requests and not state.calls
    assert state.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0] == 0
    assert not state.errors and not state.external
