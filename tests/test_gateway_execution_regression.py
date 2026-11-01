"""Reproduce news execution through Testbench, published DAGs and downloaded apps."""
import json
import time
from urllib.parse import urlsplit

import pytest

from agent_market.collector import usage
from agent_market.concierge.execution_policy import safe_registered_tool
from agent_market.workflow_templates import definitions
from tests.test_front_workflow_browser import browser
from tests.test_managed_agent_gateway import managed, rpc
from tests.test_fast_single_recommendation import catalog
from tests.workflow_package_helpers import open_hosted_package

NEWS_TOOL = {
    'name': 'get_latest_signals', 'description': 'Get recent source-backed news.',
    'annotations': {'readOnlyHint': True, 'destructiveHint': False},
    'inputSchema': {'type': 'object', 'properties': {
        'topic': {'type': 'string'}, 'type': {'type': 'string', 'enum': ['NEWS', 'RESEARCH']},
        'limit': {'type': 'integer', 'minimum': 1}}}}
SEARCH_TOOL = {
    'name': 'search_signals', 'description': 'Search source-backed news.',
    'annotations': {'readOnlyHint': True},
    'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}


@pytest.mark.parametrize('name', ['get_latest_signals', 'get_signal', 'search_signals'])
def test_signal_noun_does_not_match_signature_operation(name):
    assert safe_registered_tool({**NEWS_TOOL, 'name': name})


@pytest.mark.parametrize('name', ['sign_transaction', 'sign_message', 'create_signals', 'signals_delete',
                                  'delete_database', 'get_latest_signals;sign_transaction', 'get_signalsDelete'])
def test_readonly_hint_cannot_hide_destructive_names(name):
    assert not safe_registered_tool({**NEWS_TOOL, 'name': name})


def test_required_credentials_in_full_schema_are_not_informational_inputs():
    spec = {**NEWS_TOOL, 'inputSchema': {'type': 'object', 'properties': {'api_key': {'type':'string'}}, 'required':['api_key']}}
    assert not safe_registered_tool(spec)


@pytest.fixture
def news(managed):
    store, front, client, _, rid, calls, remote = managed
    remote.tools = [NEWS_TOOL, SEARCH_TOOL, {**NEWS_TOOL, 'name': 'sign_transaction'}]
    remote.call_result = {'content': [{'type': 'text', 'text': 'Recent source-backed research.'}],
        'structuredContent': {'signals': [{'title': 'Recorded study', 'body': 'Research summary',
            'url': 'https://news.example/study', 'source': {'name': 'Research journal', 'publishedAt': '2026-10-17'}}]}}
    compact = usage.compact_tools(remote.tools)
    store.record_usage(rid, tools=compact, digest=usage.tools_hash(compact), guide={}, changes=None, trial={'ok': True})
    front.workflows.proxy = front.proxy
    recipe = definitions()[0]
    for index,node in enumerate(recipe['nodes'][1:]):
        node['resource_id'] = node['data']['resource_id'] = rid
        node['data'].pop('resource_ref')
        # This fixture exercises the fixed signals tool contract. Production
        # recipes select independently versioned news and research providers.
        node['data']['action'] = NEWS_TOOL['name']
        node['data']['input'] = {'topic':'technology','type':'NEWS' if index==0 else 'RESEARCH','limit':3}
        node['data']['output_select'] = {'path':'structuredContent.signals','fields':{
            'title':'title','url':'url','source':'source.name','published_at':'source.publishedAt'},'limit':3}
    wid = store.create_workflow(recipe)
    yield store, front, client, rid, wid, calls, remote
    for future in list(front.workflows.futures.values()):
        future.result(timeout=5)


def test_same_news_tool_is_listed_and_executed_in_public_testbench_and_gateway(news):
    _, _, client, rid, _, calls, _ = news
    detail = client.get(f'/api/agents/{rid}').json()['agent']
    assert [t['name'] for t in detail['tools']] == ['get_latest_signals', 'search_signals']
    search = detail['tools'][1]
    assert isinstance(search['sample']['query'], str) and search['sample']['query']
    assert 'sign_transaction' not in str(detail['tools'])
    listed = rpc(client, f'/api/gateway/mcp/{rid}', 'tools/list').json()['result']['tools']
    assert [t['name'] for t in listed] == [t['name'] for t in detail['tools']]
    result = client.post('/api/test/execute', json={'resource_id': rid, 'tool': SEARCH_TOOL['name'], 'arguments': search['sample']})
    assert result.status_code == 200 and result.json()['execution_succeeded']
    assert any(json.loads(r.content).get('method') == 'tools/call' for r in calls)
    result = rpc(client, f'/api/gateway/mcp/{rid}', 'tools/call', {'name': NEWS_TOOL['name'], 'arguments': {'limit': 1}})
    assert 'result' in result.json()


def test_public_tool_samples_never_reuse_private_schema_examples(news):
    store, _, client, rid, _, _, remote = news
    spec = {**SEARCH_TOOL, 'inputSchema': {'type': 'object', 'properties': {
        'query': {'type': 'string', 'default': 'private-default', 'examples': ['private-example']}}, 'required': ['query']}}
    tools = usage.compact_tools([spec])
    store.record_usage(rid, tools=tools, digest=usage.tools_hash(tools), guide={'input': 'private-trial'}, changes=None, trial=None)
    result = client.get(f'/api/agents/{rid}')
    assert 'private-default' not in result.text and 'private-example' not in result.text and 'private-trial' not in result.text
    assert result.json()['agent']['tools'][0]['sample']['query']


def test_published_news_workflow_uses_same_admission_and_both_steps_complete(news):
    _, _, client, _, wid, calls, _ = news
    handle = client.post('/api/workflows/run', json={'template_id': wid}).json()
    for _ in range(200):
        result = client.get('/api/workflows/runs/' + handle['run_id'], headers={'X-Workflow-Key': handle['run_key']}).json()
        if result['status'] in ('succeeded', 'failed', 'cancelled'): break
        time.sleep(.01)
    assert result['status'] == 'succeeded', result
    assert all(n['status'] == 'succeeded' for n in result['node_results'])
    calls = [json.loads(r.content) for r in calls if json.loads(r.content).get('method') == 'tools/call']
    assert [c['params']['arguments']['type'] for c in calls] == ['NEWS', 'RESEARCH']


@pytest.fixture
def news_page(browser, news):
    _, _, client, rid, wid, _, _ = news
    context = browser.new_context(accept_downloads=True)
    page = context.new_page(); errors = []; external = []; requests = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    def serve(route):
        req = route.request; url = urlsplit(req.url)
        if url.hostname != 'agentconcierge.biz': external.append(req.url); return route.abort()
        requests.append((req.method, url.path, req.post_data))
        response = client.request(req.method, url.path + ('?' + url.query if url.query else ''), content=req.post_data, headers={
            k:v for k,v in req.headers.items() if k in ('accept', 'content-type', 'origin', 'x-workflow-key')})
        route.fulfill(status=response.status_code, body=response.content, headers={
            k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*', serve)
    yield page, rid, wid, errors, external, requests
    context.close()


def test_browser_search_tool_has_required_inputs_and_registered_shortcuts(news_page):
    from playwright.sync_api import expect
    page, rid, _, errors, external, requests = news_page
    page.goto('https://agentconcierge.biz/#test')
    page.evaluate('id => onTestbenchAgentChange(String(id))', rid)
    expect(page.locator('#tbQuickTools')).to_contain_text('get_latest_signals')
    assert 'ping' not in page.locator('#tbQuickTools').inner_text()
    page.locator('#tbQuickTools').get_by_role('button', name='search_signals', exact=True).click()
    expect(page.locator('#tbToolHint')).to_contain_text('Required fields: query')
    assert json.loads(page.locator('#tbArgsEditor').input_value())['query']
    page.locator('#tbRunBtn').click()
    expect(page.locator('#tbKpiStatus')).to_have_text('Completed')
    page.screenshot(path='reports/gateway-execution-fix-2026-10-17/testbench-completed.png')
    assert any(p == '/api/test/execute' for _, p, _ in requests)
    assert not errors and not external


def test_slow_agent_response_cannot_replace_the_newer_selection(news_page):
    from playwright.sync_api import expect
    page, rid, _, errors, external, _ = news_page
    page.goto('https://agentconcierge.biz/#test')
    expect(page.locator('#tbAgentMetaBox')).to_contain_text('Demo')
    result = page.evaluate('''async id => {
      const original = api;
      const detail = await original('/api/agents/' + id);
      let release;
      api = (path, ...args) => path === '/api/agents/' + id ? new Promise(resolve => {release = resolve;}) : original(path, ...args);
      try {
        const pending = onTestbenchAgentChange(String(id));
        await onTestbenchAgentChange('-2');
        release(detail);
        await pending;
        return tbSelectedAgent.id;
      } finally {api = original;}
    }''', rid)
    assert result == -2
    expect(page.locator('#tbAgentMetaBox')).to_contain_text('Demo: Agent discovery')
    assert not errors and not external


def test_browser_published_news_and_downloaded_app_both_complete(news_page, tmp_path):
    from playwright.sync_api import expect
    page, _, wid, errors, external, requests = news_page
    page.goto('https://agentconcierge.biz/#workflows')
    page.evaluate('async id => {await loadFrontTemplates(true);loadFrontTemplateToCanvas(id);}', wid)
    page.locator('#btnFrontRunWorkflow').click()
    expect(page.locator('#frontWfRunModalBody')).to_contain_text('Workflow: succeeded')
    expect(page.locator('#frontWfRunModalBody')).to_contain_text('Recorded study')
    if page.locator('#uxFullRunDetails').count():
        expect(page.locator('#frontWfRunModal')).to_be_hidden()
        expect(page.locator('#pearlWorkflowResult')).to_contain_text('Recorded study')
        page.locator('#uxFullRunDetails').click()
    expect(page.locator('#frontWfRunModal')).to_be_visible()
    page.screenshot(path='reports/gateway-execution-fix-2026-10-17/workflow-completed.png')
    page.locator('#frontWfRunModal').get_by_role('button', name='Close Dialog', exact=True).click()
    with page.expect_download() as event: page.locator('#btnFrontExportApp').click()
    path = tmp_path / 'news-webapp.zip'; event.value.save_as(path)
    files = open_hosted_package(page, path)
    assert b'https://agentconcierge.biz' in files['assets/agentconcierge-sdk.js']
    page.locator('#runAppBtn').click()
    expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded')
    expect(page.locator('#stepsContainer')).to_contain_text('Recorded study')
    page.screenshot(path='reports/gateway-execution-fix-2026-10-17/downloaded-app-completed.png')
    assert not errors and not external
