"""A bounded HTML shell hydrates workflow defaults without replacing user edits."""
import json
import time
import copy

import pytest

from agent_market.workflows import public_template
from agent_market.concierge.front import clear_front_caches
from tests.test_execution_availability import published  # noqa: F401
from tests.test_execution_recovery_browser import recovery_page  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')
ORIGIN = 'https://agentconcierge.biz'


@pytest.fixture
def bounded_page(recovery_page, catalog, monkeypatch):
    _, front, _, _, _ = catalog
    empty = {key: None for key in ('overview', 'explore', 'insights', 'workflow_default',
                                   'workflow_templates', 'testbench_presets', 'testbench_examples')}
    # Force the documented cold-shell response on this isolated Front only.
    # Leave the delivery module and each explicit API unchanged.
    monkeypatch.setattr(front.html_bootstrap, 'read', lambda *args, **kwargs: json.dumps(empty))
    yield recovery_page


def _ready(state):
    state.page.wait_for_function('id => frontActiveTemplateId === id', arg=state.news['id'])
    state.page.wait_for_function('() => activeReqs === 0')
    playwright.expect(state.page.locator('#btnFrontRunWorkflow')).to_be_enabled()


def _selected(state):
    return state.page.evaluate('''() => ({id:frontActiveTemplateId,name:frontActiveWfName,
      graph:JSON.parse(JSON.stringify(frontCanvasGraph))})''')


def test_missing_inline_workflow_data_hydrates_once_on_first_menu_entry(bounded_page):
    state = bounded_page
    page = state.page
    page.goto(ORIGIN + '/#chat')
    assert page.evaluate("JSON.parse(document.getElementById('appBootstrapData').textContent).workflow_default") is None
    assert not any(path == '/api/workflows/templates' for _, path in state.requests)
    page.locator('#chatInput').fill('Preserve this unsent task')
    page.locator('.nav-tab[data-tab="workflows"]').click()
    _ready(state)
    selected = _selected(state)
    assert selected['name'] == 'Daily Tech News & AI Research Digest'
    playwright.expect(page.locator('#frontWfSelectedTemplate')).to_contain_text(selected['name'])
    assert not any(method == 'POST' for method, _ in state.requests)
    template = public_template(state.store.get_workflow(selected['id']))
    assert selected['graph']['nodes'] == template['nodes']
    assert selected['graph']['edges'] == template['edges']
    # The fixture deliberately has an unavailable news binding. Selecting the
    # published default must retain that admission result without executing it.
    assert page.evaluate('frontTemplatesCache.find(t => t.id === frontActiveTemplateId).execution_availability.available') is False
    playwright.expect(page.locator('#frontWorkflowAvailability')).to_contain_text('HTTP 500')
    requests = state.requests.count(('GET', '/api/workflows/templates'))
    page.locator('.nav-tab[data-tab="chat"]').click()
    playwright.expect(page.locator('#chatInput')).to_have_value('Preserve this unsent task')
    page.locator('.nav-tab[data-tab="workflows"]').click()
    page.wait_for_function('() => activeReqs === 0')
    assert _selected(state) == selected
    assert state.requests.count(('GET', '/api/workflows/templates')) == requests
    assert not state.errors and not state.external


def test_reset_uses_hydrated_published_default_graph_not_unbound_shell(bounded_page):
    state = bounded_page
    page = state.page
    page.goto(ORIGIN + '/#workflows')
    _ready(state)
    original = _selected(state)
    page.evaluate("() => { frontCanvasGraph.nodes[1].name = 'Unsaved edit before explicit reset'; renderFrontCanvas(); }")
    page.locator('#btnFrontResetCanvas').click()
    assert _selected(state) == original
    assert not state.errors and not state.external


def test_saved_custom_canvas_remains_unchanged_after_default_hydration(bounded_page):
    state = bounded_page
    saved = {'version': 2, 'name': 'Preserved custom canvas', 'template_id': state.news['id'],
             'nodes': [{'id': 'saved-custom-trigger', 'type': 'trigger', 'name': 'Saved custom trigger',
                        'data': {}, 'position': {'x': 123, 'y': 234}}], 'edges': []}
    state.context.add_init_script("localStorage.setItem('front_workflow_canvas', " + json.dumps(json.dumps(saved)) + ');')
    state.page.goto(ORIGIN + '/#workflows')
    state.page.wait_for_function('() => frontDefaultTemplateId !== null && activeReqs === 0')
    assert _selected(state) == {'id': saved['template_id'], 'name': saved['name'],
                                'graph': {'nodes': saved['nodes'], 'edges': saved['edges']}}
    assert state.page.evaluate("JSON.parse(localStorage.getItem('front_workflow_canvas'))") == saved
    assert not state.errors and not state.external


def test_editing_cold_canvas_while_first_api_is_pending_preserves_edits(bounded_page):
    state = bounded_page
    page = state.page
    pending = []
    templates = state.client.get('/api/workflows/templates').json()
    page.route('**/api/workflows/templates', lambda route: pending.append(route))
    page.goto(ORIGIN + '/#chat')
    page.locator('.nav-tab[data-tab="workflows"]').click()
    deadline = time.monotonic() + 3
    while not pending and time.monotonic() < deadline:
        page.wait_for_timeout(10)
    assert len(pending) == 1
    assert page.evaluate('activeReqs') == 0, 'Menu hydration must remain silent.'
    editor = page.locator('.ux-canvas-editor')
    if editor.count() and editor.get_attribute('open') is None:
        editor.locator('summary').click()
    page.evaluate("() => openFrontNodeInspector(frontCanvasGraph.nodes[1].id)")
    page.locator('#inspNodeName').fill('Keep this edit made before hydration')
    edited = _selected(state)
    assert len(pending) == 1
    pending[0].fulfill(status=200, content_type='application/json', body=json.dumps(templates))
    page.wait_for_function('() => frontDefaultTemplateId !== null && activeReqs === 0')
    assert _selected(state) == edited
    assert page.evaluate('frontActiveTemplateId') is None
    assert not any(method == 'POST' for method, _ in state.requests)
    # A later explicit reset may replace those edits with the hydrated default.
    page.locator('#btnFrontResetCanvas').click()
    selected = _selected(state)
    assert selected['id'] == state.news['id']
    expected = public_template(state.store.get_workflow(selected['id']))
    assert selected['graph'] == {'nodes': expected['nodes'], 'edges': expected['edges']}
    assert not state.errors and not state.external


def test_compact_explore_preview_hydrates_full_page_and_report_metadata_on_first_visit(bounded_page, catalog, monkeypatch):
    state = bounded_page
    _, front, client, add, now = catalog
    rid = add('Compact preview report fixture', report_at=now - 60)
    full = client.get('/api/explore?limit=45').json()
    reported = next(item for item in full['items'] if item['id'] == rid)
    assert reported['report_count'] == 1
    preview = {key: reported[key] for key in ('id', 'kind', 'name', 'url', 'description')}
    # The bounded delivery layer may omit report metadata from its first card.
    # This is a preview, never a completed Explore page or evidence assertion.
    monkeypatch.setattr(front.html_bootstrap, 'read', lambda *args, **kwargs: json.dumps({
        'explore': {**full, 'items': [preview]}, 'workflow_default': None,
        'workflow_templates': None}))
    page = state.page
    page.goto(ORIGIN + '/#chat')
    assert page.locator('#xResults .acard[data-id]').count() == 1
    assert not any(path == '/api/explore' for _, path in state.requests)
    page.locator('#chatInput').fill('Keep this draft during explicit Explore hydration')
    page.locator('.nav-tab[data-tab="explore"]').click()
    playwright.expect(page.locator('#xResults .acard[data-id]')).to_have_count(len(full['items']))
    report_label = 'Recorded report' if state.presentation == 'published' else 'Report available'
    playwright.expect(page.locator(f'#xResults .acard[data-id="{rid}"]')).to_contain_text(report_label)
    assert page.evaluate('id => EXPLORE_AGENT_MAP.get(String(id)).report_count', rid) == 1
    assert state.requests.count(('GET', '/api/explore')) == 1
    page.locator('.nav-tab[data-tab="chat"]').click()
    playwright.expect(page.locator('#chatInput')).to_have_value('Keep this draft during explicit Explore hydration')
    page.locator('.nav-tab[data-tab="explore"]').click()
    page.wait_for_function('() => activeReqs === 0')
    assert state.requests.count(('GET', '/api/explore')) == 1
    page.locator('#xHasReport').check()
    playwright.expect(page.locator('#xResults .acard[data-id]')).to_have_count(1)
    playwright.expect(page.locator(f'#xResults .acard[data-id="{rid}"]')).to_contain_text(report_label)
    assert state.requests.count(('GET', '/api/explore')) == 2
    assert not state.errors and not state.external


def _old_news_placeholder():
    return {'version': 2, 'name': 'Daily Tech News & AI Research Digest', 'template_id': None,
            'nodes': [
                {'id': 'node-trigger-1', 'type': 'trigger', 'name': 'Manual Trigger', 'kind': 'trigger',
                 'position': {'x': 60, 'y': 180}, 'data': {}},
                {'id': 'node-agent-1', 'type': 'agent', 'name': 'Recent Technology News', 'kind': 'mcp',
                 'position': {'x': 340, 'y': 180}, 'data': {'input': {}}},
                {'id': 'node-agent-2', 'type': 'agent', 'name': 'Recent AI Research', 'kind': 'mcp',
                 'position': {'x': 620, 'y': 180}, 'data': {'input': {}}}],
            'edges': [{'id': 'e-1', 'source': 'node-trigger-1', 'target': 'node-agent-1'},
                      {'id': 'e-2', 'source': 'node-agent-1', 'target': 'node-agent-2'}]}


@pytest.mark.parametrize('edited', [False, True], ids=['known-old-default', 'user-edited-default'])
def test_old_unbound_default_is_rebound_only_when_its_canvas_is_unchanged(bounded_page, edited):
    state = bounded_page
    saved = _old_news_placeholder()
    if edited:
        saved['nodes'][1]['name'] = 'Preserve my edited news task'
    state.context.add_init_script("localStorage.setItem('front_workflow_canvas', " + json.dumps(json.dumps(saved)) + ');')
    page = state.page
    page.goto(ORIGIN + '/#workflows')
    page.wait_for_function('() => frontDefaultTemplateId !== null && !frontTemplatesLoading')
    if edited:
        assert _selected(state) == {'id': None, 'name': saved['name'],
                                    'graph': {'nodes': saved['nodes'], 'edges': saved['edges']}}
        playwright.expect(page.locator('#btnFrontRunWorkflow')).to_be_disabled()
        playwright.expect(page.locator('#frontWfSelectedTemplate')).to_contain_text('Choose a published template')
        assert page.evaluate("JSON.parse(localStorage.getItem('front_workflow_canvas'))") == saved
    else:
        _ready(state)
        template = public_template(state.store.get_workflow(state.news['id']))
        assert _selected(state)['graph'] == {'nodes': template['nodes'], 'edges': template['edges']}
        playwright.expect(page.locator('#frontWfSelectedTemplate')).to_contain_text(saved['name'])
    assert not any(method == 'POST' for method, _ in state.requests)
    assert not state.errors and not state.external


def test_cached_news_template_is_selected_while_fresh_menu_metadata_is_pending(bounded_page):
    state = bounded_page
    templates = state.client.get('/api/workflows/templates').json()['templates']
    pending = []
    page = state.page
    page.goto(ORIGIN + '/#chat')
    page.evaluate('value => setSwrCache("workflow_templates_v5", value)',templates)
    page.route('**/api/workflows/templates', lambda route: pending.append(route))
    page.locator('.nav-tab[data-tab="workflows"]').click()
    _ready(state)
    deadline = time.monotonic() + 3
    while not pending and time.monotonic() < deadline:
        page.wait_for_timeout(10)
    assert len(pending) == 1
    playwright.expect(page.locator('#binaryLoader')).not_to_be_visible()
    playwright.expect(page.locator('#frontWfSelectedTemplate')).to_contain_text(state.news['name'])
    assert page.evaluate('frontTemplatesLoading')
    assert not any(method == 'POST' for method, _ in state.requests)
    pending[0].fulfill(status=400, content_type='application/json', body='{"error":"Controlled metadata failure."}')
    page.wait_for_function('() => !frontTemplatesLoading')
    _ready(state)
    assert not state.errors and not state.external


def test_reset_before_first_template_response_still_selects_the_news_default(bounded_page):
    state = bounded_page
    page = state.page
    payload = state.client.get('/api/workflows/templates').json()
    pending = []
    page.route('**/api/workflows/templates', lambda route: pending.append(route))
    page.goto(ORIGIN + '/#workflows')
    deadline = time.monotonic() + 3
    while not pending and time.monotonic() < deadline:
        page.wait_for_timeout(10)
    assert len(pending) == 1
    assert page.evaluate('frontDefaultTemplateId') is None
    page.locator('#btnFrontResetCanvas').click()
    pending[0].fulfill(status=200, content_type='application/json', body=json.dumps(payload))
    _ready(state)
    assert _selected(state)['name'] == state.news['name']
    assert not any(method == 'POST' for method, _ in state.requests)
    assert not state.errors and not state.external


def test_ready_news_default_waits_for_explicit_run_then_uses_published_definition(bounded_page):
    state = bounded_page
    # Use an existing bound fixture graph and MockTransport to exercise the
    # actual public workflow POST/poll path under the news template identity.
    ready = copy.deepcopy(state.store.get_workflow(state.healthy_ids[0]))
    assert state.store.update_workflow(state.news['id'], {'nodes': ready['nodes'], 'edges': ready['edges']})
    clear_front_caches()
    page = state.page
    page.goto(ORIGIN + '/#workflows')
    _ready(state)
    playwright.expect(page.locator('#frontWfActiveName')).to_have_text('Daily Tech News & AI Research Digest')
    assert not state.calls and not any(method == 'POST' for method, _ in state.requests)
    page.locator('#btnFrontRunWorkflow').click()
    playwright.expect(page.locator('#frontWfRunModalBody')).to_contain_text('Workflow: succeeded')
    assert ('POST', '/api/workflows/run') in state.requests and len(state.calls) == 2
    assert not state.errors and not state.external
