"""Only Home refreshes itself; editing panels retain input across lifecycle events."""
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')
ORIGIN = 'https://agentconcierge.biz'
NON_HOME = ('test','explore','workflows','chat','learn','register','about')


@pytest.fixture
def refresh_page(browser,catalog):
    _,_,client,add,now = catalog
    schema = {'type':'object','properties':{'city':{'type':'string'}},'required':['city']}
    tools = [{'name':name,'description':'Read a weather forecast','inputSchema':schema}
             for name in ('forecast','get_forecast_details')]
    rid = add('Retained Weather',usage_guide=json.dumps({'tools':tools}),report_at=now-10)
    context = browser.new_context(reduced_motion='reduce')
    page = context.new_page()
    page.clock.install()
    state = SimpleNamespace(page=page,rid=rid,calls=[],errors=[],blocked=[],allow_run=False,polls=0)
    page.on('pageerror',lambda error:state.errors.append(str(error)))

    def serve(route):
        req = route.request
        url = urlsplit(req.url)
        if url.hostname != 'agentconcierge.biz' or url.path.startswith('/api/gateway/'):
            state.blocked.append((req.method,url.hostname,url.path))
            return route.abort()
        state.calls.append((req.method,url.path))
        # User-run polling is exercised with synthetic responses only. No
        # provider execution, live server or deployment database is involved.
        if state.allow_run and url.path == '/api/workflows/run' and req.method == 'POST':
            return route.fulfill(status=200,content_type='application/json',body=json.dumps({
                'run_id':'isolated-refresh-run','run_key':'isolated-run-capability','status':'queued'}))
        if state.allow_run and url.path == '/api/workflows/runs/isolated-refresh-run':
            state.polls += 1
            return route.fulfill(status=200,content_type='application/json',body=json.dumps({
                'run_id':'isolated-refresh-run','status':'running' if state.polls==1 else 'succeeded',
                'nodes':[],'workflow':{'name':'Isolated run'}}))
        if req.method not in ('GET','HEAD'):
            state.blocked.append((req.method,url.hostname,url.path))
            return route.abort()
        response = client.request(req.method,url.path+('?' +url.query if url.query else ''),
            headers={'accept':req.headers.get('accept','*/*')})
        body = response.content
        if url.path == '/api/workflows/templates' and response.status_code == 200:
            # An isolated catalog projection makes the fallback control visible;
            # this test checks retention, never fallback execution authorization.
            data = response.json()
            for template in data.get('templates',[]):
                template['fallback_available'] = True
                template['execution_availability'] = {'available':True}
            body = json.dumps(data).encode()
        route.fulfill(status=response.status_code,body=body,headers={key:value
            for key,value in response.headers.items()
            if key not in ('content-length','content-encoding','transfer-encoding')})

    context.route('**/*',serve)
    try:yield state
    finally:context.close()


def settle(page):
    page.wait_for_function('() => activeReqs===0 && !learnRevalidating && !ovRevalidating && !exploreRequestedKey')
    page.wait_for_timeout(50)


def open_tab(state,tab):
    state.page.locator(f'.nav-tab[data-tab="{tab}"]').click()
    settle(state.page)


def prepare_edits(state):
    page = state.page
    page.goto(ORIGIN+'/#test')
    reject = page.get_by_role('button',name='Reject Non-Essential',exact=True)
    if reject.is_visible():
        reject.click()
        assert page.locator('dialog[open]').count()==0
    options = page.locator('.pearl-selection-options')
    if options.count() and options.get_attribute('open') is None:
        options.locator('summary').click()
    page.locator('#tbAgentSelect').select_option(str(state.rid))
    page.wait_for_function('id => tbSelectedAgent?.id===id',arg=state.rid)
    page.locator('#tbToolSelect').select_option('get_forecast_details')
    if page.locator('#uxRawArgs').count()and page.locator('#uxRawArgs').get_attribute('open')is None:
        page.locator('#uxRawArgs>summary').click()
    page.locator('#tbArgsEditor').fill('{"city":"Retain this draft","hours":17}')
    open_tab(state,'explore')
    page.locator('#xQ').fill('weather')
    page.clock.run_for(400)
    if page.locator('.pearl-search-panel .pearl-protocol-segmented').count():
        page.locator('.pearl-search-panel .pearl-protocol-segmented [data-kind="mcp"]').click()
    else:
        page.locator('#xKind').select_option('mcp')
    page.locator('#xNoAuth').check()
    page.locator('#xHasReport').check()
    settle(page)
    open_tab(state,'workflows')
    if page.locator('.ux-canvas-editor').count():
        page.locator('.ux-canvas-editor > summary').click()
    page.evaluate('''async () => {
      await loadFrontTemplates(true);
      updateFrontActiveName();
      const node=frontCanvasGraph.nodes.find(node=>node.type==='agent');
      openFrontNodeInspector(node.id);
    }''')
    page.locator('#inspNodeName').fill('Retain edited node title')
    page.locator('#inspNodeAction').fill('forecast_details')
    page.locator('#inspNodeSample').fill('Retain this workflow input')
    page.locator('#frontFallbackConsent').check()
    open_tab(state,'chat')
    page.locator('#chatInput').fill('Retain this unsent task and its context')
    settle(page)


def editing_state(page):
    return page.evaluate('''() => ({
      test:{agent:$('tbAgentSelect').value,tool:$('tbToolSelect').value,args:$('tbArgsEditor').value},
      explore:{query:$('xQ').value,kind:$('xKind').value,category:$('xCategory').value,
        checked:$('xVerified').checked,noAuth:$('xNoAuth').checked,reports:$('xHasReport').checked},
      workflow:{graph:structuredClone(frontCanvasGraph),selected:frontSelectedNodeId,
        title:$('inspNodeName')?.value,action:$('inspNodeAction')?.value,
        input:$('inspNodeSample')?.value,fallback:$('frontFallbackConsent').checked},
      chat:$('chatInput').value
    })''')


def visibility(page,visible):
    page.evaluate('''visible => {
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>!visible});
      Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>visible?'visible':'hidden'});
      document.dispatchEvent(new Event('visibilitychange'));
    }''',visible)


def test_non_home_panels_never_refresh_from_timers_focus_visibility_or_online(refresh_page):
    state = refresh_page
    prepare_edits(state)
    baseline = editing_state(state.page)
    for tab in NON_HOME:
        open_tab(state,tab)
        assert editing_state(state.page) == baseline
        state.calls.clear()
        state.page.clock.run_for(61000)
        state.page.evaluate("window.dispatchEvent(new Event('focus'))")
        settle(state.page)
        visibility(state.page,False)
        state.page.clock.run_for(61000)
        visibility(state.page,True)
        settle(state.page)
        state.page.clock.run_for(61000)
        state.page.evaluate("window.dispatchEvent(new Event('online'))")
        state.page.clock.run_for(121000)
        settle(state.page)
        assert state.calls == [],(tab,state.calls)
        assert editing_state(state.page) == baseline,tab
    assert not state.errors and not state.blocked


def test_home_refreshes_only_overview_and_pauses_hidden_or_offline(refresh_page):
    state = refresh_page
    page = state.page
    page.goto(ORIGIN+'/#overview')
    settle(page)
    state.calls.clear()
    page.clock.run_for(61000)
    settle(page)
    assert state.calls and set(state.calls) == {('GET','/api/overview'),('GET','/api/pearl/status')}
    visibility(page,False)
    state.calls.clear()
    page.clock.run_for(121000)
    settle(page)
    assert state.calls == []
    visibility(page,True)
    settle(page)
    assert state.calls and set(state.calls) == {('GET','/api/overview'),('GET','/api/pearl/status')}
    page.evaluate("Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>false})")
    state.calls.clear()
    page.clock.run_for(121000)
    page.evaluate("window.dispatchEvent(new Event('focus'));window.dispatchEvent(new Event('online'))")
    settle(page)
    assert state.calls == []
    assert not state.errors and not state.blocked


def test_reopening_panels_and_hash_navigation_preserve_all_unsent_edits(refresh_page):
    state = refresh_page
    prepare_edits(state)
    baseline = editing_state(state.page)
    for tab in ('workflows','test','explore','chat','workflows','test'):
        open_tab(state,tab)
        assert editing_state(state.page) == baseline
    for tab in ('chat','workflows','explore','test'):
        state.page.evaluate('tab => {location.hash=tab}',tab)
        state.page.wait_for_function('tab => currentTab===tab',arg=tab)
        settle(state.page)
        assert editing_state(state.page) == baseline
    assert not [call for call in state.calls if call[0] not in ('GET','HEAD')]
    assert not state.errors and not state.blocked


def test_explicit_workflow_run_may_poll_its_status_without_reloading_other_menus(refresh_page):
    state = refresh_page
    prepare_edits(state)
    open_tab(state,'workflows')
    before = editing_state(state.page)
    state.allow_run = True
    state.calls.clear()
    state.page.locator('#btnFrontRunWorkflow').click()
    state.page.wait_for_function('() => Boolean(window.frontWorkflowRun)')
    open_tab(state,'chat')
    for _ in range(2):
        state.page.clock.run_for(800)
        state.page.wait_for_timeout(50)
    state.page.wait_for_function('() => !frontWorkflowRunning')
    after = editing_state(state.page)
    assert after['test'] == before['test'] and after['explore'] == before['explore']
    assert after['chat'] == before['chat']
    assert after['workflow']['graph'] == before['workflow']['graph']
    assert after['workflow']['fallback'] is False
    assert state.polls == 2
    assert set(state.calls) <= {('GET','/api/workflows/templates'),('POST','/api/workflows/run'),
                               ('GET','/api/workflows/runs/isolated-refresh-run')}
    assert not state.errors and not state.blocked
