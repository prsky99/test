"""Progress feedback stays visible without blocking input or replaying POSTs.

Testbench and registration use the shared centered loader. Explore progress is
nonblocking, either inline or centered according to its presentation. Chat and
workflow runs report progress inline in their own panel.
"""
import json
import time
from urllib.parse import urlsplit

import pytest

from tests.test_execution_availability import published  # noqa: F401
from tests.test_execution_recovery_browser import recovery_page  # noqa: F401
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')
ORIGIN = 'https://agentconcierge.biz'


def _idle(page):
    page.wait_for_function('() => activeReqs === 0')
    playwright.expect(page.locator('#binaryLoader')).not_to_be_visible()


def _open(state, tab):
    state.page.goto(ORIGIN + '/#' + tab)
    if tab == 'explore':
        state.page.wait_for_function('() => !exploreRequestedKey')
    elif tab == 'workflows':
        state.page.wait_for_function('() => frontDefaultTemplateId !== null && frontTemplatesCache.length > 0')
        state.page.evaluate('id => loadFrontTemplateToCanvas(id)', state.healthy_ids[0])
    elif tab == 'test':
        state.page.wait_for_function('() => tbLiveExamples.length > 0 && tbAgentsCache.length > 0')
    _idle(state.page)


def _watch_loader(page):
    page.evaluate('''() => {
      window.__unexpectedLoader = false;
      new MutationObserver(records => {
        if (records.some(record => record.oldValue === 'false') ||
            document.getElementById('binaryLoader').getAttribute('aria-hidden') === 'false') {
          window.__unexpectedLoader = true;
        }
      }).observe(document.getElementById('binaryLoader'), {
        attributes:true, attributeFilter:['aria-hidden'], attributeOldValue:true});
    }''')


def _hold(state, pattern, *, status=None, payload=None):
    calls = []

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        call = {'route': route, 'method': request.method, 'path': url.path,
                'body': request.post_data_json if request.post_data else None}
        if payload is None:
            # The fixture executes registered workflows/Test tools only through
            # MockTransport; no real provider or production database is used.
            call['response'] = state.client.request(
                request.method, url.path + ('?' + url.query if url.query else ''),
                content=request.post_data,
                headers={key: value for key, value in request.headers.items()
                         if key in ('accept', 'content-type', 'origin', 'x-workflow-key')})
        else:
            call.update(status=status or 200, payload=payload)
        calls.append(call)

    state.page.route(pattern, serve)
    return calls


def _await_calls(page, calls, count=1):
    deadline = time.monotonic() + 4
    while len(calls) < count and time.monotonic() < deadline:
        page.wait_for_timeout(10)
    assert len(calls) == count


def _release(call, *, status=None, payload=None):
    if payload is not None or 'response' not in call:
        call['route'].fulfill(status=status or call.get('status', 200),
                              content_type='application/json',
                              body=json.dumps(payload if payload is not None else call['payload']))
    else:
        response = call['response']
        call['route'].fulfill(status=response.status_code, body=response.content,
                              headers={key: value for key, value in response.headers.items()
                                       if key not in ('content-length', 'content-encoding', 'transfer-encoding')})


def _centered(page):
    loader = page.locator('#binaryLoader')
    playwright.expect(loader).to_be_visible()
    playwright.expect(loader).to_have_attribute('role', 'status')
    playwright.expect(loader).to_have_attribute('aria-live', 'polite')
    playwright.expect(loader).to_have_attribute('aria-hidden', 'false')
    box = loader.bounding_box()
    size = page.viewport_size
    assert abs(box['x'] + box['width'] / 2 - size['width'] / 2) <= 2
    assert abs(box['y'] + box['height'] / 2 - size['height'] / 2) <= 2
    assert box['x'] >= 0 and box['x'] + box['width'] <= size['width']
    assert loader.evaluate('element => getComputedStyle(element).pointerEvents') == 'none'


def _inline(page, tab):
    """The pending action is announced accessibly while editing stays available."""
    if tab == 'explore' and page.locator('#binaryLoader').is_visible():
        _centered(page)
    else:
        playwright.expect(page.locator('#binaryLoader')).not_to_be_visible()
    if tab == 'explore':
        playwright.expect(page.locator('#xResults')).to_have_attribute('aria-busy', 'true')
        if page.locator('#uxExploreStatus').count():
            playwright.expect(page.locator('#uxExploreStatus')).to_have_text('Finding matching agents…')
    elif tab == 'chat':
        playwright.expect(page.locator('#chatStatus')).to_contain_text('Checking relevant agents')
        playwright.expect(page.locator('#chatStatus')).to_have_attribute('aria-live', 'polite')
        playwright.expect(page.locator('#chatForm')).to_have_attribute('aria-busy', 'true')
    elif tab == 'workflows':
        playwright.expect(page.locator('#btnFrontRunWorkflow')).to_be_disabled()
        playwright.expect(page.locator('#btnFrontRunWorkflow')).to_contain_text('Executing')
    if tab == 'explore' and page.locator('#binaryLoader').is_visible():
        assert page.evaluate('activeReqs') >= 1
    else:
        assert page.evaluate('activeReqs') == 0


@pytest.mark.parametrize('tab,selector,value', [
    ('explore', '#xQ', 'Saved search draft'),
    ('test', '#tbArgsEditor', '{"query":"Saved test arguments"}'),
    ('workflows', '#inspNodeName', 'Saved workflow node title'),
    ('chat', '#chatInput', 'Saved chat draft'),
    ('register', '#regAutoUrl', 'https://agent-fixture.example/mcp'),
])
def test_cached_menu_click_stays_silent_without_refetch_or_input_loss(recovery_page, tab, selector, value):
    state = recovery_page
    page = state.page
    _open(state, tab)
    if tab == 'workflows':
        if page.locator('.ux-canvas-editor').count():
            page.locator('.ux-canvas-editor > summary').click()
        page.evaluate("() => openFrontNodeInspector(frontCanvasGraph.nodes.find(node => node.type === 'agent').id)")
    if tab == 'register' and page.locator('.pearl-registration-import').count():
        page.locator('.pearl-registration-import > summary').click()
    if selector=='#tbArgsEditor'and page.locator('#uxRawArgs').count()and page.locator('#uxRawArgs').get_attribute('open')is None:
        page.locator('#uxRawArgs>summary').click()
    page.locator(selector).fill(value)
    if tab == 'explore':
        page.wait_for_timeout(350)
    _idle(page)
    page.locator('.nav-tab[data-tab="about"]').click()
    _idle(page)
    before = len(state.requests)
    _watch_loader(page)
    page.locator(f'.nav-tab[data-tab="{tab}"]').click()
    playwright.expect(page.locator(selector)).to_have_value(value)
    _idle(page)
    assert not page.evaluate('window.__unexpectedLoader')
    assert len(state.requests) == before
    assert not state.errors and not state.external


@pytest.mark.parametrize('width,height,theme', [(1440, 900, 'light'), (390, 844, 'dark')], ids=['desktop-light', 'mobile-dark'])
def test_pending_search_is_accessible_nonblocking_and_reduced_motion(recovery_page, width, height, theme):
    state = recovery_page
    page = state.page
    page.set_viewport_size({'width': width, 'height': height})
    page.emulate_media(color_scheme=theme, reduced_motion='reduce')
    _open(state, 'explore')
    pending = _hold(state, '**/api/explore?*')
    page.locator('#xQ').fill('Fresh search for centered progress')
    page.locator('#xGo').click()
    _await_calls(page, pending)
    page.wait_for_timeout(300)
    _inline(page, 'explore')
    assert page.evaluate('document.activeElement.id') == 'xGo'
    # Pointer events remain available while a response is pending. Editing the
    # query cancels that request; its completion must not leak a progress token.
    page.locator('#xQ').fill('Changed while pending')
    _release(pending[0])
    _await_calls(page, pending, 2)
    _release(pending[1])
    _idle(page)
    playwright.expect(page.locator('#xQ')).to_have_value('Changed while pending')
    assert not state.errors and not state.external


def test_overlapping_search_and_detail_complete_independently(recovery_page):
    state = recovery_page
    page = state.page
    _open(state, 'explore')
    searches = _hold(state, '**/api/explore?*')
    details = _hold(state, '**/api/agents/*')
    rid = next(iter(state.resource_ids.values()))
    page.locator('#xQ').fill('Fresh search for overlapping progress')
    page.locator('#xGo').click()
    _await_calls(page, searches)
    page.evaluate('id => { void openAgent(id); }', rid)
    _await_calls(page, details)
    page.wait_for_timeout(250)
    background_detail = state.presentation == 'published'
    if background_detail:
        _inline(page, 'explore')
        playwright.expect(page.locator('#drawerContent>h3')).to_be_visible()
    else:
        # The legacy drawer still announces its detail request centrally.
        playwright.expect(page.locator('#xResults')).to_have_attribute('aria-busy', 'true')
        _centered(page)
        assert page.evaluate('activeReqs') >= 1
    _release(searches[0])
    playwright.expect(page.locator('#xResults')).not_to_have_attribute('aria-busy', 'true')
    if not background_detail:
        _centered(page)
    _release(details[0])
    _idle(page)
    assert not state.errors and not state.external


@pytest.mark.parametrize('failed', [False, True], ids=['completed', 'failed'])
def test_chat_pending_feedback_ends_and_duplicate_submit_cannot_replay_post(recovery_page, failed):
    state = recovery_page
    page = state.page
    _open(state, 'chat')
    calls = _hold(state, '**/chat')
    page.locator('#chatInput').fill('Find a documentation search agent')
    page.locator('#chatSubmit').click()
    _await_calls(page, calls)
    page.locator('#chatInput').fill('Keep this next unsent task')
    page.evaluate("() => { void sendChat('Second click must not send'); }")
    page.wait_for_timeout(300)
    _inline(page, 'chat')
    assert len(calls) == 1
    playwright.expect(page.locator('#chatSubmit')).to_be_disabled()
    if failed:
        _release(calls[0], status=400, payload={'error': 'Controlled request failure.'})
    else:
        _release(calls[0])
    _idle(page)
    playwright.expect(page.locator('#chatSubmit')).to_be_enabled()
    playwright.expect(page.locator('#chatInput')).to_have_value('Keep this next unsent task')
    assert page.evaluate("document.getElementById('chatForm').getAttribute('aria-busy')") == 'false'
    assert len(calls) == 1 and not state.errors and not state.external


@pytest.mark.parametrize('failed', [False, True], ids=['completed', 'failed'])
def test_testbench_pending_feedback_and_single_execution(recovery_page, failed):
    state = recovery_page
    page = state.page
    _open(state, 'test')
    if state.presentation == 'published':
        page.locator('.pearl-example-choice').filter(has_text='Camera documentation').click()
    else:
        page.locator('.testbench-recipe-card').filter(has_text='Camera documentation').get_by_role('button',name='Load Recipe',exact=True).click()
    page.wait_for_function("() => tbSelectedAgent?.name && document.getElementById('tbToolSelect').value === 'search_docs'")
    _idle(page)
    calls = _hold(state, '**/api/test/execute')
    page.locator('#tbRunBtn').click()
    _await_calls(page, calls)
    page.evaluate('() => { void executeCurrentTestbench(); }')
    page.wait_for_timeout(300)
    _centered(page)
    assert len(calls) == 1 and len(state.calls) == 1
    if failed:
        _release(calls[0], status=400, payload={'error': 'Controlled test failure.'})
    else:
        _release(calls[0])
    _idle(page)
    playwright.expect(page.locator('#tbRunBtn')).to_be_enabled()
    assert len(calls) == 1 and not state.errors and not state.external


def test_workflow_feedback_spans_preflight_post_and_polling_without_duplicate_run(recovery_page):
    state = recovery_page
    page = state.page
    _open(state, 'workflows')
    templates = _hold(state, '**/api/workflows/templates')
    submissions = _hold(state, '**/api/workflows/run')
    polls = _hold(state, '**/api/workflows/runs/*')
    page.locator('#btnFrontRunWorkflow').click()
    _await_calls(page, templates)
    page.evaluate('() => { void runFrontCanvasWorkflow(); }')
    page.wait_for_timeout(300)
    _inline(page, 'workflows')
    assert not submissions
    _release(templates[0])
    _await_calls(page, submissions)
    _inline(page, 'workflows')
    _release(submissions[0])
    # The run button stays busy between 700ms polls.
    page.wait_for_timeout(300)
    _inline(page, 'workflows')
    _await_calls(page, polls)
    _inline(page, 'workflows')
    _release(polls[0])
    playwright.expect(page.locator('#frontWfRunModalBody')).to_contain_text('Workflow: succeeded')
    _idle(page)
    assert len(submissions) == 1 and len(state.calls) == 2
    assert not state.errors and not state.external


@pytest.mark.parametrize('action', ['inspect', 'submit'])
def test_registration_pending_feedback_and_reentry_guard_without_provider_call(recovery_page, action):
    state = recovery_page
    page = state.page
    _open(state, 'register')
    if action == 'inspect':
        path, button = '/api/register/inspect', '#regInspectBtn'
        if page.locator('.pearl-registration-import').count():
            page.locator('.pearl-registration-import > summary').click()
        page.locator('#regAutoUrl').fill('https://agent-fixture.example/mcp')
    else:
        path, button = '/api/register', '#regSubmitBtn'
        page.locator('#regUrl').fill('https://agent-fixture.example/mcp')
        page.locator('#regName').fill('Isolated registration fixture')
        page.locator('#regDesc').fill('Read documentation from this isolated fixture.')
        page.locator('#regTermsConsent').check()
        if page.locator('#pearlRegAuthority').count():
            page.locator('#pearlRegAuthority').check()
    # The registration endpoint is deliberately answered at the HTTP boundary:
    # it must never inspect a provider or write an operational registration.
    calls = _hold(state, '**' + path, status=400, payload={'error': 'Controlled registration rejection.'})
    page.locator(button).click()
    _await_calls(page, calls)
    page.evaluate('id => { void document.querySelector(id).onclick(); }', button)
    page.wait_for_timeout(300)
    _centered(page)
    assert len(calls) == 1
    _release(calls[0])
    _idle(page)
    playwright.expect(page.locator(button)).to_be_enabled()
    assert len(calls) == 1 and not state.calls
    assert not state.errors and not state.external


@pytest.mark.parametrize('tab,pattern', [
    ('explore', '**/api/explore?*'),
    ('test', '**/api/test/presets'),
    ('workflows', '**/api/workflows/templates'),
])
def test_first_menu_hydration_uses_each_panels_progress_policy(recovery_page, tab, pattern):
    state = recovery_page
    page = state.page
    _open(state, 'chat')
    pending = _hold(state, pattern)
    _watch_loader(page)
    page.locator(f'.nav-tab[data-tab="{tab}"]').click()
    _await_calls(page, pending)
    page.wait_for_timeout(300)
    if tab == 'explore' and page.locator('#binaryLoader').is_visible():
        _centered(page)
        assert page.evaluate('activeReqs') >= 1
    else:
        playwright.expect(page.locator('#binaryLoader')).not_to_be_visible()
        assert page.evaluate('activeReqs') == 0
    if tab != 'explore':assert not page.evaluate('window.__unexpectedLoader')
    _release(pending[0])
    page.wait_for_timeout(50)
    playwright.expect(page.locator('#binaryLoader')).not_to_be_visible()
    if tab != 'explore':assert not page.evaluate('window.__unexpectedLoader')
    assert not state.errors and not state.external


def test_background_api_completion_cannot_hide_an_explicit_search_indicator(recovery_page):
    state = recovery_page
    page = state.page
    _open(state, 'explore')
    searches = _hold(state, '**/api/explore?*')
    automatic = _hold(state, '**/api/insights')
    page.locator('#xQ').fill('Fresh search while background work finishes')
    page.locator('#xGo').click()
    _await_calls(page, searches)
    page.evaluate("() => { void api('/api/insights', {background:true}); }")
    _await_calls(page, automatic)
    _release(automatic[0])
    page.wait_for_timeout(50)
    _inline(page, 'explore')
    _release(searches[0])
    _idle(page)
    assert not state.errors and not state.external


def test_home_never_shows_indicator_even_with_pending_user_run_and_automatic_refresh(recovery_page):
    state = recovery_page
    page = state.page
    _open(state, 'chat')
    chats = _hold(state, '**/chat')
    overview = _hold(state, '**/api/overview')
    page.locator('#chatInput').fill('Find an agent for documentation')
    page.locator('#chatSubmit').click()
    _await_calls(page, chats)
    _inline(page, 'chat')
    page.locator('a.brand-box').click()
    playwright.expect(page.locator('#binaryLoader')).not_to_be_visible()
    assert page.evaluate('currentTab') == 'overview'
    _watch_loader(page)
    page.evaluate('() => { void loadOverview(true); }')
    _await_calls(page, overview)
    page.wait_for_timeout(250)
    playwright.expect(page.locator('#binaryLoader')).not_to_be_visible()
    _release(overview[0])
    page.wait_for_function('() => !ovRevalidating')
    playwright.expect(page.locator('#binaryLoader')).not_to_be_visible()
    _release(chats[0])
    _idle(page)
    assert not page.evaluate('window.__unexpectedLoader')
    assert not state.errors and not state.external


def test_home_periodic_focus_and_online_refresh_never_show_central_progress(recovery_page):
    state = recovery_page
    page = state.page
    page.clock.install()
    _open(state, 'chat')
    overview = _hold(state, '**/api/overview')
    page.locator('a.brand-box').click()
    if not overview:
        page.evaluate('() => { void loadOverview(true); }')
    _await_calls(page, overview)
    _release(overview[0])
    page.wait_for_function('() => !ovRevalidating')
    _watch_loader(page)
    page.clock.run_for(60000)
    _await_calls(page, overview, 2)
    page.evaluate("() => { window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('online')); document.dispatchEvent(new Event('visibilitychange')); }")
    playwright.expect(page.locator('#binaryLoader')).not_to_be_visible()
    assert page.evaluate('activeReqs') == 0
    assert not page.evaluate('window.__unexpectedLoader')
    _release(overview[1])
    page.wait_for_function('() => !ovRevalidating')
    _idle(page)
    assert not state.errors and not state.external
