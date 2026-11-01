"""The public template hub uses the same purpose search as headless clients."""
from urllib.parse import urlsplit, parse_qs

import pytest
from tests.test_workflow_discovery import discovery  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

playwright = pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('standalone', [False, True])
def test_browser_node_aliases_latest_query_and_failure_message(browser, discovery, standalone):
    store, front, client, _ = discovery
    context = browser.new_context()
    queries, unexpected = [], []
    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz':
            unexpected.append(url.hostname); route.abort(); return
        query = parse_qs(url.query).get('q', [''])[0]
        if url.path == '/api/workflows/templates' and query:
            queries.append(query)
            if query == 'unavailable':
                route.fulfill(status=503, content_type='application/json', body='{"ok":false}'); return
        response = client.request(request.method, url.path+('?' + url.query if url.query else ''),
            content=request.post_data, headers={k:v for k,v in request.headers.items() if k in ('accept', 'content-type')})
        body = response.content
        if url.path == '/new/en/workflows.html':
            # Search is checked against this fixture's catalog, not the published list shipped in the page.
            import re
            body = re.sub(rb'(<script\b[^>]*\bid="appBootstrapData"[^>]*>).*?(</script>)', lambda m: m[1] + b'{}' + m[2], body, count=1, flags=re.S)
        route.fulfill(status=response.status_code, body=body,
            headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*', serve)
    page = context.new_page(); errors=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto('https://agentconcierge.biz/new/en/workflows.html' if standalone else 'https://agentconcierge.biz/#workflows')
        page.locator('#btnFrontWfViewTemplates').click()
        field = page.locator('#frontTmplSearchInput')
        grid = page.locator('#frontTemplatesGrid')
        field.fill('papers')
        playwright.expect(grid.locator('.template-card')).to_have_count(1)
        playwright.expect(grid).to_contain_text('Daily Tech News')
        field.fill('papers')
        field.fill('나라 지표')
        playwright.expect(grid).to_contain_text('Country & Economic Indicator')
        playwright.expect(grid.locator('.template-card')).to_have_count(1)
        field.fill('unavailable')
        playwright.expect(grid).to_contain_text('Workflow search is unavailable')
        field.fill('package security workflow')
        playwright.expect(grid).to_contain_text('Package Metadata')
        field.fill('')
        playwright.expect(grid.locator('.template-card')).to_have_count(3)
        assert queries and not errors and not unexpected
        assert store.query('SELECT COUNT(*) FROM workflow_runs')[0][0] == 0
    finally:
        context.close()


@pytest.mark.parametrize('standalone',[False,True])
def test_chat_three_workflows_review_without_execution(browser,discovery,standalone):
    store,_,client,ids=discovery
    original=store.get_workflow(ids['news'])
    for name in ('Technology Research Brief','Related Research Brief'):
        store.create_workflow({'name':name,'description':'Technology news and research papers','nodes':original['nodes'],'edges':[],'is_template':1})
    context=browser.new_context(viewport={'width':1440,'height':1000})
    context.add_init_script("localStorage.setItem('agent_cookie_consent_v2',JSON.stringify({analytics:false,marketing:false,essential:true,timestamp:Date.now()}))")
    page=context.new_page();errors=[];calls=[]
    def forward(route):
        r=route.request;u=urlsplit(r.url)
        if u.hostname!='agentconcierge.biz':route.abort();return
        calls.append((r.method,u.path))
        response=client.request(r.method,u.path+('?' +u.query if u.query else ''),content=r.post_data,headers={k:v for k,v in r.headers.items() if k in ('accept','content-type','x-visitor-token')})
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
    context.route('**/*',forward);page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto('https://agentconcierge.biz/new/en/chat.html' if standalone else 'https://agentconcierge.biz/#chat')
        page.locator('#chatInput').fill('Find a workflow that researches technology news and papers')
        page.locator('#chatSubmit').click()
        cards=page.locator('.chat-workflow-recommendation');playwright.expect(cards).to_have_count(3)
        playwright.expect(cards.first).to_contain_text('Daily Tech News & AI Research Digest')
        assert not page.locator('#chatMessages pre').count()
        page.screenshot(path='reports/discovery-three-recommendations-2026-10-25/workflow-chat-'+str(standalone)+'.png',full_page=True)
        cards.first.get_by_role('button',name='Review template').click()
        playwright.expect(page.locator('#secWorkflows')).to_be_visible()
        playwright.expect(page.locator('#frontWfActiveName')).to_contain_text('Daily Tech News')
        assert not any(method=='POST' and path in ('/api/workflows/run','/api/test/execute') for method,path in calls)
        assert store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]==0 and not errors
    finally:context.close()
