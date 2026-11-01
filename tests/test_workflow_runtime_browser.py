"""Admin schedule/history and public connected app against actual controlled MCP calls."""
import json
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.collector import usage
from agent_market.concierge.front import Front, create_front_app
from agent_market.concierge.proxy import McpProxy
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from tests.test_mcp_proxy import MockRemoteMcp, WEATHER_TOOL
from tests.test_admin_security_browser import browser

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

playwright=pytest.importorskip('playwright.sync_api')


@pytest.fixture
def studio(browser,tmp_path,rotated_bootstrap_admin):
    store=Store(str(tmp_path/'studio.db'))
    front=Front(store,allow_private=True)
    rid=store.upsert_resource({'key':'mcp:https://weather.example/mcp','kind':'mcp','source':'mcp-registry','name':'Weather Agent','description':'Weather','category':'data_utility','url':'https://weather.example/mcp','price_usdc':0,'details':{}})
    tools=usage.compact_tools([WEATHER_TOOL]);store.record_usage(rid,tools=tools,digest=usage.tools_hash(tools),guide={},changes=None,trial={'ok':True})
    transport=httpx.Client(transport=MockRemoteMcp([WEATHER_TOOL]))
    front.workflows.proxy=front.proxy=McpProxy(store,allow_private=True,http=transport)
    wid=store.create_workflow({'name':'Recorded Weather Pipeline','description':'Weather outcomes','is_template':1,'nodes':[{'id':'weather','type':'agent','name':'Weather Agent','kind':'mcp','resource_id':rid,'position':{'x':100,'y':100},'data':{'action':'get_weather','input':{'city':'Tokyo'}}}],'edges':[]})
    adminapp=FastAPI();adminapp.include_router(dashboard_router(store,str(tmp_path/'studio.db'),'browser-admin',None,front=front))
    admin=TestClient(adminapp,base_url='https://admin.test');public=TestClient(create_front_app(front),base_url='https://agentconcierge.biz')
    context=browser.new_context(accept_downloads=True);page=context.new_page();errors=[];requests=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.scheme=='file':return route.continue_()
        client=admin if url.hostname=='admin.test' else public if url.hostname=='agentconcierge.biz' else None
        if client is None:return route.abort()
        requests.append((req.method,url.path,req.post_data))
        response=client.request(req.method,url.path+('?' +url.query if url.query else ''),content=req.post_data,headers=req.headers)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    yield page,wid,front,errors,requests
    context.close();admin.close();public.close()
    for future in list(front.workflows.futures.values()):future.result(timeout=5)
    transport.close();store._db.close()


def login(page):
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    playwright.expect(page.locator('#adminLoginModal')).to_be_hidden()
    page.locator('[data-tab="workflows"]').click()


def test_admin_real_run_history_schedule_and_export(studio,tmp_path):
    page,wid,front,errors,requests=studio
    login(page)
    page.evaluate('async id=>{await loadWorkflows();selectWorkflow(id);}',wid)
    page.locator('#btnRunCanvasWorkflow').click()
    playwright.expect(page.locator('#workflowRunModal')).to_be_visible()
    playwright.expect(page.locator('#wfRunStatus')).to_have_text('Execution: succeeded')
    playwright.expect(page.locator('#wfDeliverableContent')).to_contain_text('Tokyo: 22C')
    playwright.expect(page.locator('#wfDispatchStatusText')).to_contain_text('NOT_REQUESTED')
    assert not any(method=='PUT'and path==f'/admin/api/workflows/{wid}'for method,path,_ in requests)
    page.locator('#workflowHistory').click()
    playwright.expect(page.locator('#workflowHistoryList')).to_contain_text('succeeded')
    page.locator('#closeWfRunBtn').click()
    page.locator('#btnOpenScheduleModalTop').click()
    page.locator('#wfScheduleTypeSelect').select_option('scheduled')
    page.locator('#wfSchedulePresetSelect').select_option('weekly_mon_0900')
    page.locator('#wfScheduleTimezone').fill('America/New_York')
    page.locator('#wfScheduleEnabled').check()
    page.locator('#btnSaveWorkflowSchedule').click()
    playwright.expect(page.locator('#wfScheduleState')).to_contain_text('Saved')
    page.locator('#closeWfScheduleBtn').click();page.locator('#btnOpenScheduleModalTop').click()
    playwright.expect(page.locator('#wfSchedulePresetSelect')).to_have_value('weekly_mon_0900')
    playwright.expect(page.locator('#wfScheduleTimezone')).to_have_value('America/New_York')
    playwright.expect(page.locator('#wfScheduleEnabled')).to_be_checked()
    assert front.workflows.schedule(wid)['next_run']>0
    page.locator('#closeWfScheduleBtn').click();page.locator('#btnExportAppFromCanvas').click()
    playwright.expect(page.locator('#workflowAppExportModal')).to_be_visible()
    assert page.locator('#appExportPaidCheck,#appExportGoogleAuthCheck').count()==0
    with page.expect_download() as event:page.locator('#btnDownloadWorkflowHTML').click()
    path=tmp_path/'connected.html';event.value.save_as(path)
    page.goto(path.as_uri());page.locator('#runAppBtn').click()
    playwright.expect(page.locator('#appStatus')).to_have_text('Workflow: succeeded')
    playwright.expect(page.locator('#stepsContainer')).to_contain_text('Tokyo: 22C')
    assert any(p.startswith('/api/workflow-apps/') and p.endswith('/runs') for _,p,_ in requests)
    assert not errors


def test_admin_failed_run_and_public_actual_success(studio):
    page,wid,front,errors,_=studio
    page.goto('https://agentconcierge.biz/#workflows')
    # Load the real published template through the same public template API.
    page.evaluate('''async id=>{
      const response=await api('/api/workflows/templates');frontTemplatesCache=response.templates;
      const item=frontTemplatesCache.find(t=>t.id===id);frontActiveWfName=item.name;frontActiveTemplateId=item.id;
      frontCanvasGraph={nodes:item.nodes,edges:item.edges};updateFrontActiveName();renderFrontCanvas();
    }''',wid)
    page.locator('#btnFrontRunWorkflow').click()
    playwright.expect(page.locator('#frontWfRunModalBody')).to_contain_text('Workflow: succeeded')
    playwright.expect(page.locator('#frontWfRunModalBody')).to_contain_text('Tokyo: 22C')
    if page.locator('#uxFullRunDetails').count():
        playwright.expect(page.locator('#frontWfRunModal')).to_be_hidden()
        playwright.expect(page.locator('#pearlWorkflowResult')).to_contain_text('Tokyo: 22C')
        page.locator('#uxFullRunDetails').click()
    playwright.expect(page.locator('#frontWfRunModal')).to_be_visible()
    page.locator('#frontWfRunModal').get_by_role('button',name='Close Dialog',exact=True).click()
    before=front.store.query('SELECT COUNT(*) AS n FROM workflow_runs')[0]['n']
    with front.store.tx() as db:db.execute('UPDATE resources SET active=0')
    page.locator('#btnFrontRunWorkflow').click()
    playwright.expect(page.locator('#frontWorkflowAvailability')).to_contain_text('unavailable')
    playwright.expect(page.locator('#frontWfRunModal')).to_be_hidden()
    assert front.store.query('SELECT COUNT(*) AS n FROM workflow_runs')[0]['n']==before
    assert not errors


def test_router_condition_editor_runs_actual_selected_branch(studio):
    page,wid,front,errors,_=studio
    from agent_market.workspace_admin_events import migrate
    migrate(front.store,b'r'*32)
    front.store.update_workflow(wid,{'is_template':0})
    login(page)
    page.on('dialog',lambda dialog:dialog.accept('Update isolated private workflow'))
    page.evaluate('''async id=>{
      await loadWorkflows();selectWorkflow(id);
      canvasGraph.nodes.unshift({id:'route',type:'router',kind:'router',name:'Weather condition',position:{x:0,y:0},data:{condition:true}});
      canvasGraph.edges=[{id:'branch',source:'route',target:'weather',condition:true}];
      renderCanvas();selectNode('route');
    }''',wid)
    playwright.expect(page.locator('#wfRouterConditionBox')).to_be_visible()
    page.locator('#wfRouterCondition').fill('false')
    page.locator('.wf-router-branch').select_option('false')
    page.locator('#btnApplyInspector').click()
    page.locator('#btnTestSingleNode').click()
    playwright.expect(page.locator('#workflowRunModal')).to_be_visible()
    playwright.expect(page.locator('#wfRunStatus')).to_have_text('Execution: succeeded')
    playwright.expect(page.locator('#wfDeliverableContent')).to_contain_text('Tokyo: 22C')
    assert not errors


def test_duplicate_template_names_keep_selected_identity(studio):
    page,wid,front,errors,requests=studio
    original=front.store.get_workflow(wid)
    original.pop('graph_data',None)
    other=front.store.create_workflow({**original,'nodes':[{**original['nodes'][0],'id':'other','name':'Selected duplicate'}],'edges':[]})
    page.goto('https://agentconcierge.biz/#workflows')
    page.evaluate('''async id=>{await loadFrontTemplates(true);loadFrontTemplateToCanvas(id);}''',other)
    page.locator('#btnFrontRunWorkflow').click()
    playwright.expect(page.locator('#frontWfRunModalBody')).to_contain_text('Selected duplicate')
    sent=[json.loads(body) for method,path,body in requests if method=='POST' and path=='/api/workflows/run']
    assert sent[-1]['template_id']==other
    html=page.evaluate('''()=>generateStandaloneWebAppHtml(frontActiveWfName,'',[],[],[])''')
    assert '"workflow_id":'+str(other) in html
    assert not errors


def test_edited_published_canvas_waits_for_review_before_execution(studio):
    page,wid,front,errors,requests=studio
    from agent_market.workspace_admin_events import migrate
    migrate(front.store,b's'*32)
    login(page)
    page.evaluate('''async id=>{await loadWorkflows();selectWorkflow(id);canvasGraph.nodes[0].data.input.city='Paris';}''',wid)
    page.on('dialog',lambda dialog:dialog.accept('Review isolated published input edit'))
    page.locator('#btnRunCanvasWorkflow').click()
    page.wait_for_function('() => window.workflowExecutionBusy === false')
    assert any(method=='PUT'and path==f'/admin/api/workflows/{wid}'for method,path,_ in requests)
    assert not any(method=='POST'and path==f'/admin/api/workflows/{wid}/run'for method,path,_ in requests)
    assert front.store.get_workflow(wid)['nodes'][0]['data']['input']['city']=='Tokyo'
    assert front.store.query("SELECT id FROM admin_reviewed_commands WHERE status='pending'")
    assert not errors
