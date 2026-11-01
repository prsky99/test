"""Cold and delayed public menus remain legible without inventing readiness."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_owned_data_agents_activation import operating  # noqa: F401
from tests.test_owned_data_agents import engine  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://agentconcierge.biz'


def _preview_count(page):
    """Previews are the titles published in the page; their number follows the shipped list."""
    return page.evaluate("JSON.parse(document.querySelector('[data-example-previews]').dataset.examplePreviews).length")


def _page_examples(page):
    return page.evaluate("JSON.parse(document.getElementById('appBootstrapData').textContent).testbench_examples")


def _without_page_examples(page, client, name='test'):
    """Serve the page with an empty bootstrap so the API fallback path is exercised."""
    import re

    def strip(route):
        reply = client.get('/new/en/' + name + '.html')
        body = re.sub(r'(<script\b[^>]*\bid="appBootstrapData"[^>]*>).*?(</script>)',
                      lambda m: m[1] + '{}' + m[2], reply.text, count=1, flags=re.S)
        route.fulfill(status=200, body=body, headers={'content-type': 'text/html; charset=utf-8',
                      'content-security-policy': reply.headers['content-security-policy']})
    page.context.route('**/new/en/' + name + '.html', strip)


@pytest.fixture
def cold_page(operating, browser):  # noqa: F811
    front, client, _, _, _ = operating
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
    context.add_init_script("localStorage.setItem('agent_cookie_consent_v2', JSON.stringify({essential:true,analytics:false,marketing:false,timestamp:Date.now()}))")
    page = context.new_page()
    held, calls, errors = {}, [], []
    blocked = set()

    def fulfill(route):
        req = route.request
        parsed = urlsplit(req.url)
        reply = client.request(req.method, parsed.path + ('?' + parsed.query if parsed.query else ''),
                               content=req.post_data,
                               headers={k: v for k, v in req.headers.items() if k in ('accept', 'content-type', 'x-workflow-key')})
        route.fulfill(status=reply.status_code, body=reply.content,
                      headers={k: v for k, v in reply.headers.items()
                               if k not in ('content-length', 'content-encoding', 'transfer-encoding')})

    def serve(route):
        path = urlsplit(route.request.url).path
        calls.append((route.request.method, path))
        if path in blocked or '*' in blocked and path.startswith('/api/'):
            held.setdefault(path, []).append(route)
        else:
            fulfill(route)

    context.route('**/*', serve)
    page.on('pageerror', lambda error: errors.append(str(error)))
    yield page, front, client, blocked, held, calls, errors, fulfill
    context.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_fixed_examples_open_without_any_request(cold_page, width):
    """UI policy 11-01: fixed default content is plain HTML; data loads only on a click."""
    page, _, _, blocked, held, calls, errors, fulfill = cold_page
    page.set_viewport_size({'width': width, 'height': 1000})
    blocked.add('*')
    page.goto(ORIGIN + '/new/en/test.html', wait_until='domcontentloaded')
    examples = _page_examples(page)
    expect(page.locator('.pearl-example-choice')).to_have_count(len(examples))
    expect(page.locator('.pearl-example-choice').first).to_be_enabled()
    expect(page.locator('#pearlTestExampleName')).to_have_text(examples[0]['title'])
    expect(page.locator('#tbRunBtn')).to_be_enabled()
    expect(page.locator('#tbToolSelect')).to_be_enabled()
    expect(page.locator('#testbenchRecipesGrid')).to_have_attribute('aria-busy', 'false')
    page.locator('.pearl-example-choice').nth(1).click()
    expect(page.locator('#pearlTestExampleName')).to_have_text(examples[1]['title'])
    expect(page.locator('#tbRunBtn')).to_be_enabled()
    assert not any(path.startswith('/api/') for _, path in calls), calls
    page.locator('.ux-agent-chooser > summary').click()
    for _ in range(100):
        if any(path == '/api/explore' for _, path in calls):
            break
        page.wait_for_timeout(20)
    assert any(path == '/api/explore' for _, path in calls)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
    assert not any(method == 'POST' for method, _ in calls)
    assert not errors


@pytest.mark.parametrize('width', [1440, 390])
def test_examples_appear_before_optional_catalog_and_share_connection_read(cold_page, width):
    page, _, client, blocked, held, calls, errors, fulfill = cold_page
    page.set_viewport_size({'width': width, 'height': 1000})
    _without_page_examples(page, client)
    examples = client.get('/api/test/presets').json()['live_examples']
    detail = '/api/agents/' + str(examples[0]['resource_id'])
    blocked.update(['/api/test/presets', detail])
    page.goto(ORIGIN + '/new/en/test.html', wait_until='domcontentloaded')
    expect(page.locator('.pearl-example-preview')).to_have_count(_preview_count(page))
    expect(page.locator('.pearl-example-preview').first).to_be_disabled()
    expect(page.locator('#pearlExampleLoadState')).to_contain_text('Checking')
    expect(page.locator('#tbRunBtn')).to_be_disabled()
    expect(page.locator('#tbToolSelect')).to_be_disabled()
    expect(page.locator('#tbToolSelect')).to_contain_text('Choose an agent to load tools')
    pending_height = page.locator('#testbenchRecipesGrid').bounding_box()['height']
    assert not any(path == '/api/explore' for _, path in calls)
    expect(page.locator('#binaryLoader')).not_to_be_visible()
    page.screenshot(path=str(ROOT / ('reports/frontend-first-entry-2026-10-20/examples-pending-' + str(width) + '.png')), full_page=True)
    blocked.remove('/api/test/presets')
    for route in held.pop('/api/test/presets'):
        fulfill(route)
    expect(page.locator('.pearl-example-choice')).to_have_count(len(examples))
    expect(page.locator('#pearlTestConnectionState')).to_contain_text('Loading')
    assert not any(path == '/api/explore' for _, path in calls)
    assert sum(path == detail for _, path in calls) == 1
    blocked.remove(detail)
    for route in held.pop(detail):
        fulfill(route)
    expect(page.locator('#tbRunBtn')).to_be_enabled()
    expect(page.locator('#tbToolSelect')).to_be_enabled()
    expect(page.locator('#pearlTestExampleName')).to_have_text(examples[0]['title'])
    page.wait_for_function('() => tbAgentsCache.length > 0')
    assert sum(path == detail for _, path in calls) == 1
    assert abs(page.locator('#testbenchRecipesGrid').bounding_box()['height'] - pending_height) < 40
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
    assert not any(method == 'POST' for method, _ in calls)
    assert not errors


@pytest.mark.parametrize('saved', [False, True, 'edited'])
def test_default_workflow_steps_arrive_without_reselecting_template(cold_page, saved):
    page, _, client, blocked, held, calls, errors, fulfill = cold_page
    templates = client.get('/api/workflows/templates').json()['templates']
    selected = next(t for t in templates if t['name'] == 'Daily Tech News & AI Research Digest')
    expected_graph = {'nodes': selected['nodes'], 'edges': selected['edges']}
    if saved:
        draft = {'version': 2, 'template_id': selected['id'], 'name': selected['name'],
                 'nodes': json.loads(json.dumps(selected['nodes'])), 'edges': selected['edges']}
        if saved == 'edited':
            draft['nodes'][1]['name'] = 'Saved draft node'
            draft['nodes'][1]['data']['input']['query'] = 'Retain this draft input'
        expected_graph = {'nodes': draft['nodes'], 'edges': draft['edges']}
        page.add_init_script('localStorage.setItem("front_workflow_canvas", ' + json.dumps(json.dumps(draft)) + ')')
    _without_page_examples(page, client, 'workflows')
    blocked.add('/api/workflows/templates')
    page.goto(ORIGIN + '/new/en/workflows.html', wait_until='domcontentloaded')
    expect(page.locator('#pearlWorkflowInputSteps')).to_contain_text('Loading workflow steps')
    expect(page.locator('#pearlWorkflowInputSteps')).to_have_attribute('aria-busy', 'true')
    expect(page.locator('#btnFrontRunWorkflow')).to_be_disabled()
    blocked.clear()
    for route in held.pop('/api/workflows/templates'):
        fulfill(route)
    expect(page.locator('#pearlWorkflowInputSteps .pearl-workflow-step')).to_have_count(len(selected['nodes']))
    expect(page.locator('#pearlWorkflowRunDetails li')).to_have_count(len(selected['nodes']))
    expect(page.locator('#btnFrontRunWorkflow')).to_be_enabled()
    assert page.evaluate('frontActiveTemplateId') == selected['id']
    assert page.evaluate('frontCanvasGraph') == expected_graph
    assert not any(method == 'POST' for method, _ in calls)
    assert not errors
    page.screenshot(path=str(ROOT / ('reports/frontend-first-entry-2026-10-20/workflow-restored-' + str(saved) + '.png')), full_page=True)


def test_failed_examples_have_an_explicit_retry_without_false_availability(cold_page):
    page, _, client, blocked, held, _, errors, fulfill = cold_page
    _without_page_examples(page, client)
    blocked.add('/api/test/presets')
    page.goto(ORIGIN + '/new/en/test.html', wait_until='domcontentloaded')
    expect(page.locator('.pearl-example-preview')).to_have_count(_preview_count(page))
    for route in held.pop('/api/test/presets'):
        route.fulfill(status=503, json={'detail': 'Controlled unavailable response.'})
    expect(page.locator('#pearlRetryExamples')).to_be_visible()
    expect(page.locator('#testbenchRecipesGrid')).to_have_attribute('aria-busy', 'false')
    expect(page.locator('#pearlExampleLoadState')).to_contain_text('could not')
    expect(page.locator('.pearl-example-choice')).to_have_count(0)
    blocked.clear()
    page.locator('#pearlRetryExamples').click()
    expect(page.locator('.pearl-example-choice')).not_to_have_count(0)
    expect(page.locator('#pearlRetryExamples')).not_to_be_visible()
    assert not errors


def test_published_workflows_open_without_any_request(cold_page):
    """UI policy 11-01: the published workflow list ships in the page."""
    page, _, _, blocked, _, calls, errors, _ = cold_page
    blocked.add('*')
    page.goto(ORIGIN + '/new/en/workflows.html', wait_until='domcontentloaded')
    shipped = page.evaluate("JSON.parse(document.getElementById('appBootstrapData').textContent).workflow_templates")
    assert shipped
    expect(page.locator('#pearlWorkflowInputSteps .pearl-workflow-step').first).to_be_visible()
    expect(page.locator('#pearlWorkflowInputSteps')).to_have_attribute('aria-busy', 'false')
    expect(page.locator('#btnFrontRunWorkflow')).to_be_enabled()
    assert not any(path == '/api/workflows/templates' for _, path in calls), calls
    assert not any(method == 'POST' for method, _ in calls)
    assert not errors


def test_failed_workflows_show_retry_instead_of_an_empty_flow(cold_page):
    page, _, client, blocked, held, _, errors, _ = cold_page
    _without_page_examples(page, client, 'workflows')
    blocked.add('/api/workflows/templates')
    page.goto(ORIGIN + '/new/en/workflows.html', wait_until='domcontentloaded')
    expect(page.locator('#pearlWorkflowInputSteps')).to_contain_text('Loading')
    for route in held.pop('/api/workflows/templates'):
        route.fulfill(status=503, json={'detail': 'Controlled unavailable response.'})
    expect(page.locator('#pearlWorkflowChoices')).to_contain_text('could not be loaded')
    expect(page.locator('#pearlWorkflowInputSteps')).to_contain_text('could not be loaded')
    expect(page.locator('#btnFrontRunWorkflow')).to_be_disabled()
    blocked.clear()
    page.get_by_role('button', name='Retry workflows', exact=True).click()
    expect(page.locator('#pearlWorkflowInputSteps .pearl-workflow-step')).to_have_count(3)
    expect(page.locator('#btnFrontRunWorkflow')).to_be_enabled()
    assert not errors


@pytest.mark.parametrize('file,panel', [
    ('index', 'overview'), ('agent-status', 'status'), ('explore', 'explore'),
    ('learn', 'learn'), ('test', 'test'), ('workflows', 'workflows'),
    ('chat', 'chat'), ('list-agent', 'register'), ('about', 'about'),
])
def test_delayed_data_never_hides_the_initial_menu_or_blocks_input(cold_page, file, panel):
    page, _, _, blocked, _, calls, errors, _ = cold_page
    blocked.add('*')
    page.goto(ORIGIN + '/new/en/' + file + '.html', wait_until='domcontentloaded')
    expect(page.locator('[data-panel="' + panel + '"]')).to_be_visible()
    expect(page.locator('[data-panel="' + panel + '"] h1').first).to_be_visible()
    if panel == 'explore':
        # Search now explicitly owns centered progress, including the first read.
        expect(page.locator('#binaryLoader')).to_be_visible()
        page.locator('#xQ').fill('Keep editing during search')
        expect(page.locator('#xQ')).to_have_value('Keep editing during search')
    else:
        expect(page.locator('#binaryLoader')).not_to_be_visible()
    if panel == 'test':
        expect(page.locator('.pearl-example-choice')).to_have_count(len(_page_examples(page)))
        expect(page.locator('#tbRunBtn')).to_be_enabled()
    if panel == 'workflows':
        expect(page.locator('#pearlWorkflowInputSteps .pearl-workflow-step').first).to_be_visible()
    if panel == 'explore':
        expect(page.locator('#uxExploreStatus')).to_contain_text('Finding')
    if panel == 'chat':
        page.locator('#chatInput').fill('Keep this request while data is pending.')
        expect(page.locator('#chatInput')).to_have_value('Keep this request while data is pending.')
    if panel == 'register':
        page.locator('#regUrl').fill('https://public.example/mcp')
        expect(page.locator('#regUrl')).to_have_value('https://public.example/mcp')
    assert not any(method == 'POST' for method, _ in calls)
    assert not errors
