"""Click through tasks and inspect their resulting state, not only page geometry."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect
from tests.test_pearl_frontend import ORIGIN, browser, client, pearl_page


@pytest.mark.parametrize('protocol',['A2A','MCP','x402','Any'])
def test_home_task_sends_the_selected_protocol(pearl_page,protocol):
    page,errors,_=pearl_page
    submitted=[]
    def reply(route):
        submitted.append(route.request.post_data_json)
        route.fulfill(json={'reply':'No currently active, relevant agent found.','data':{'recommendations':[]}})
    page.route('**/chat',reply)
    page.goto(ORIGIN+'/')
    page.locator('#home-task').fill('Find public research sources')
    page.locator('#home-protocol').select_option(label=protocol)
    page.locator('.home-query button').click()
    expect(page.locator('#secChat')).to_be_visible()
    expect(page.locator('#chatSubmit')).to_be_enabled()
    assert submitted[0]['data']['protocol']==protocol.lower()
    assert not errors


def test_home_keeps_recorded_counts_when_the_status_refresh_is_unavailable(pearl_page):
    page,errors,_=pearl_page
    page.route('**/api/pearl/status',lambda route:route.fulfill(status=503,json={'detail':'Controlled status failure'}))
    page.goto(ORIGIN+'/')
    expect(page.locator('#secOverview [data-metric="cataloged"]')).to_have_text('8')
    expect(page.locator('#secOverview [data-metric="reachable"]')).to_have_text('8')
    expect(page.locator('#uxHomeSnapshotState')).to_contain_text('unavailable')
    expect(page.locator('#secOverview [data-metric="with_status_check"]')).to_have_text('—')
    expect(page.locator('#secOverview .catalog-hero .actions a[href="https://agentconcierge.biz/new/en/explore.html"]')).to_have_text('Explore agents')
    assert page.locator('#secOverview time').first.get_attribute('datetime')
    assert not errors


def install_examples(page):
    examples=[{'id':'news','title':'Technology news','desc':'Find recent news with sources.','available':True,'resource_id':501,'protocol':'mcp','tool':'search','args':{'query':'technology news','limit':2}},
              {'id':'docs','title':'Camera documentation','desc':'Find official camera guidance.','available':True,'resource_id':502,'protocol':'mcp','tool':'search','args':{'query':'camera permissions','limit':3}}]
    page.route('**/api/test/presets',lambda r:r.fulfill(json={'presets':[],'live_examples':examples}))
    def agent(route):
        id=int(urlsplit(route.request.url).path.rsplit('/',1)[1])
        route.fulfill(json={'agent':{'id':id,'name':'News sources'if id==501 else'Official documentation','kind':'mcp','description':'Registered search capability','health_status':'healthy','tools':[{'name':'search','inputSchema':{'type':'object','properties':{'query':{'type':'string','title':'Search query'},'limit':{'type':'integer','title':'Result limit'}},'required':['query']}}]}})
    page.route('**/api/agents/50*',agent)


def test_examples_fill_editable_fields_and_reset_to_the_selected_sample(pearl_page):
    page,errors,_=pearl_page;install_examples(page)
    page.goto(ORIGIN+'/#test')
    expect(page.locator('#tbRunBtn')).to_be_enabled()
    expect(page.locator('#pearlTestExampleName')).to_have_text('Technology news')
    expect(page.locator('[data-arg-key="query"]')).to_have_value('technology news')
    assert not page.locator('#uxRawArgs').get_attribute('open')
    page.locator('[data-arg-key="query"]').fill('Keep these sources')
    assert json.loads(page.locator('#tbArgsEditor').input_value())['query']=='Keep these sources'
    page.locator('.pearl-example-choice[data-recipe="docs"]').click()
    expect(page.locator('#pearlTestExampleName')).to_have_text('Camera documentation')
    expect(page.locator('[data-arg-key="query"]')).to_have_value('camera permissions')
    expect(page.locator('[data-arg-key="limit"]')).to_have_value('3')
    page.locator('#uxRawArgs>summary').click()
    page.locator('#tbArgsEditor').fill('{"query":"Changed JSON","limit":4}')
    page.locator('#tbArgsEditor').press('Tab')
    expect(page.locator('[data-arg-key="query"]')).to_have_value('Changed JSON')
    page.locator('#tbResetBtn').click()
    expect(page.locator('[data-arg-key="query"]')).to_have_value('camera permissions')
    expect(page.locator('#pearlTestExampleName')).to_have_text('Camera documentation')
    assert not errors


def test_agent_picker_searches_catalog_without_replacing_the_current_request(pearl_page):
    page,errors,_=pearl_page;install_examples(page)
    searches=[]
    def catalog(route):
        query=parse_qs(urlsplit(route.request.url).query);searches.append(query)
        route.fulfill(json={'items':[{'id':502,'name':'Official documentation','description':'Camera permissions reference','kind':'mcp'}],'total':1})
    page.route('**/api/explore?*',catalog)
    page.goto(ORIGIN+'/#test');expect(page.locator('#tbRunBtn')).to_be_enabled()
    page.locator('[data-arg-key="query"]').fill('Keep unsent draft')
    page.locator('.pearl-selection-options>summary').click()
    page.locator('#tbAgentSearch').fill('camera')
    expect(page.locator('#uxAgentSearchStatus')).to_contain_text('matching choices')
    expect(page.locator('#tbAgentSelect option[value="502"]')).to_have_count(1)
    expect(page.locator('[data-arg-key="query"]')).to_have_value('Keep unsent draft')
    assert page.locator('#tbAgentSelect').input_value()==''
    page.locator('#tbAgentSelect').select_option('502')
    expect(page.locator('#tbAgentMetaBox')).to_contain_text('Official documentation')
    assert not errors


def test_agent_picker_protocol_change_discards_an_older_catalog_reply(pearl_page):
    page,errors,_=pearl_page;install_examples(page)
    held=[]
    def catalog(route):
        if parse_qs(urlsplit(route.request.url).query).get('q')==['camera']:held.append(route)
        else:route.fulfill(json={'items':[],'total':0})
    page.route('**/api/explore?*',catalog)
    page.goto(ORIGIN+'/#test');expect(page.locator('#tbRunBtn')).to_be_enabled()
    page.locator('.pearl-selection-options>summary').click()
    page.locator('#tbAgentSearch').fill('camera')
    for _ in range(100):
        if len(held)==1:break
        page.wait_for_timeout(10)
    assert len(held)==1
    page.locator('#secTest .quick-chips [data-kind="a2a"]').click()
    for _ in range(100):
        if len(held)==2:break
        page.wait_for_timeout(10)
    assert len(held)==2 and parse_qs(urlsplit(held[1].request.url).query)['kind']==['a2a']
    held[1].fulfill(json={'items':[{'id':700,'name':'Camera A2A agent','kind':'a2a'}],'total':1})
    expect(page.locator('#tbAgentSelect option[value="700"]')).to_have_count(1)
    held[0].fulfill(json={'items':[{'id':701,'name':'Camera MCP agent','kind':'mcp'}],'total':1})
    page.wait_for_timeout(50)
    expect(page.locator('#tbAgentSelect option[value="700"]')).to_have_count(1)
    expect(page.locator('#tbAgentSelect option[value="701"]')).to_have_count(0)
    expect(page.locator('#pearlTestExampleName')).to_have_text('Technology news')
    assert not errors


def test_human_input_validation_and_execution_use_the_edited_request(pearl_page):
    page,errors,_=pearl_page;install_examples(page)
    sent=[]
    def execute(route):
        sent.append(route.request.post_data_json)
        route.fulfill(json={'protocol':'mcp','output':'First source\nSecond source','execution_succeeded':True,'task_status':'succeeded','latency_ms':10})
    page.route('**/api/test/execute',execute)
    page.goto(ORIGIN+'/#test');expect(page.locator('#tbRunBtn')).to_be_enabled()
    page.locator('[data-arg-key="limit"]').fill('2.5')
    page.locator('#tbRunBtn').click()
    assert sent==[]
    page.locator('[data-arg-key="limit"]').fill('4')
    page.locator('[data-arg-key="query"]').fill('Documentation sources')
    page.locator('#tbRunBtn').click()
    expect(page.locator('#tbKpiStatus')).to_have_text('Completed')
    assert sent[0]['arguments']=={'query':'Documentation sources','limit':4}
    expect(page.locator('#tbOutputPre')).to_have_text('First source\nSecond source')
    # Plain-text results keep their line breaks inside the readable result view.
    assert page.locator('#tbOutputPre .result-plain').evaluate('(n)=>getComputedStyle(n).whiteSpace')=='pre-wrap'
    assert not errors


def test_explore_use_in_test_keeps_the_requested_agent_over_the_default_sample(pearl_page):
    page,errors,_=pearl_page;install_examples(page)
    page.goto(ORIGIN+'/#explore')
    card=page.locator('#xResults .acard').first
    expect(card).to_be_visible();id=card.get_attribute('data-id')
    card.click();page.locator('#drawerTestBtn').click()
    expect(page.locator('#secTest')).to_be_visible()
    expect(page.locator('#tbRunBtn')).to_be_enabled()
    page.wait_for_function('id => String(tbSelectedAgent?.id)===id',arg=id)
    page.wait_for_timeout(350)
    expect(page.locator('#tbAgentSelect')).to_have_value(id)
    assert page.locator('#tbAgentSelect').input_value()!='501'
    assert not errors


@pytest.mark.parametrize('width',[1440,390])
def test_two_chat_results_are_ordered_separate_and_fully_accessible(pearl_page,width):
    page,errors,_=pearl_page
    count=0
    def response(route):
        nonlocal count
        count+=1
        route.fulfill(json={'reply':'Agent selected','data':{'recommendations':[{'id':count,'name':['First research agent','Second documentation agent'][count-1],'kind':'a2a','grade':'A','quality_score':91,'tools':['search'],'test_report':{'id':count,'created_at':1792400000,'success':True}}]}})
    page.route('**/chat',response)
    page.set_viewport_size({'width':width,'height':900})
    page.goto(ORIGIN+'/#chat')
    for task in ['Find research sources','Find documentation']:
        page.locator('#chatInput').fill(task);page.locator('#chatSubmit').click()
        expect(page.locator('#chatSubmit')).to_be_enabled()
    cards=page.locator('.chat-recommendation');expect(cards).to_have_count(2)
    expect(cards.first).to_contain_text('Second documentation agent')
    expect(cards.nth(1)).to_contain_text('First research agent')
    first=cards.first.bounding_box();second=cards.nth(1).bounding_box()
    assert second['y']>=first['y']+first['height']
    # The chat log may scroll on its own; it is then reachable from the keyboard, and each result
    # can be brought fully into view.
    messages=page.locator('#chatMessages')
    if not messages.evaluate('(n)=>n.scrollHeight<=n.clientHeight+2'):
        assert messages.evaluate('(n)=>n.tabIndex>=0')
    for index in range(2):
        cards.nth(index).scroll_into_view_if_needed();expect(cards.nth(index)).to_be_in_viewport()
    cards.nth(1).get_by_role('button',name='Calling details').click()
    expect(page.locator('#drawerContent')).to_contain_text('First research agent')
    page.locator('#closeDrawer').click()
    cards.first.get_by_role('button',name='Calling details').click()
    expect(page.locator('#drawerContent')).to_contain_text('Second documentation agent')
    page.keyboard.press('Escape')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    assert not errors


def test_workflow_choices_keep_their_positions_and_pearls_show_actual_steps(pearl_page,client):
    page,errors,_=pearl_page
    from tests.test_pearl_frontend import mock_selectable_templates
    mock_selectable_templates(page,client)
    page.goto(ORIGIN+'/#workflows')
    expect(page.locator('#pearlWorkflowSearch')).to_be_visible()
    page.locator('#btnFrontWfViewTemplates').click()
    cards=page.locator('#frontTemplatesGrid .template-card')
    ids=cards.evaluate_all('(ns)=>ns.map(n=>n.dataset.templateId)')
    for id in ids:
        page.locator('#btnFrontWfViewTemplates').click()
        assert cards.evaluate_all('(ns)=>ns.map(n=>n.dataset.templateId)')==ids
        page.locator('#frontTemplatesGrid [data-template-id="'+id+'"]').get_by_role('button',name='Use workflow',exact=True).click()
        expected=page.evaluate('frontTemplatesCache.find(t=>t.id===frontActiveTemplateId).nodes.filter(n=>n.type!=="trigger").length')
        expect(page.locator('.ux-workflow-pearl img')).to_have_count(expected)
        for index in range(page.locator('.ux-workflow-pearl').count()):
            page.locator('.ux-workflow-pearl').nth(index).click()
            expect(page.locator('#pearlWorkflowInputDialog')).to_be_visible()
            page.keyboard.press('Escape')
    page.locator('#btnFrontResetCanvas').click()
    expect(page.locator('#frontWfActiveName')).to_contain_text('News')
    expect(page.locator('#btnFrontRunWorkflow')).to_be_enabled()
    assert not errors


@pytest.mark.parametrize('width',[1440,390])
def test_template_browser_search_and_selection_return_to_the_same_workflow(pearl_page,client,width):
    page,errors,_=pearl_page
    from tests.test_pearl_frontend import mock_selectable_templates
    mock_selectable_templates(page,client)
    page.set_viewport_size({'width':width,'height':900})
    page.goto(ORIGIN+'/#workflows')
    expect(page.locator('#pearlWorkflowSearch')).to_be_visible()
    page.locator('#btnFrontWfViewTemplates').click()
    expect(page.locator('#frontWfTemplatesView')).to_be_visible()
    expect(page.locator('#pearlWorkflowTemplates')).not_to_be_visible()
    search=page.locator('#frontTmplSearchInput')
    search.fill('no-such-template-example')
    expect(page.locator('.wf-library-empty')).to_be_visible()
    search.fill('')
    card=page.locator('#frontTemplatesGrid .template-card').first
    name=card.locator('h3').inner_text()
    card.get_by_role('button',name='Use workflow',exact=True).click()
    expect(page.locator('#frontWfActiveName')).to_have_text(name)
    expect(page.locator('#pearlWorkflowTemplates')).to_be_visible()
    expect(page.locator('#frontWfTemplatesView')).not_to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    assert not errors


def test_clear_search_restores_all_filters_and_home_links_do_not_carry_old_constraints(pearl_page):
    page,errors,_=pearl_page
    page.goto(ORIGIN+'/#explore')
    page.locator('#xQ').fill('No matching sample')
    page.locator('#xHasReport').check();page.locator('#xNoAuth').check()
    page.locator('#xCategory').select_option('web_search')
    page.locator('#uxClearSearch').click()
    expect(page.locator('#xQ')).to_have_value('')
    assert not page.locator('#xHasReport').is_checked()and not page.locator('#xNoAuth').is_checked()
    expect(page.locator('#xCategory')).to_have_value('')
    page.locator('#xHasReport').check()
    page.locator('.brand-box').click()
    page.locator('#secOverview [data-pearl-filter="protocol=MCP"]').first.click()
    expect(page.locator('#xKind')).to_have_value('mcp')
    assert not page.locator('#xHasReport').is_checked()
    assert not errors


def test_search_waits_for_a_slow_response_without_replaying_the_read(pearl_page):
    page,errors,_=pearl_page
    page.goto(ORIGIN+'/#explore')
    expect(page.locator('#xResults .acard:not(.skeleton-card)').first).to_be_visible()
    page.clock.install()
    held=[]
    page.route('**/api/explore?*',lambda route:held.append(route))
    page.locator('.pearl-search-panel [data-kind="x402"]').click()
    page.wait_for_timeout(50)
    assert len(held)==1
    page.clock.run_for(14000)
    assert len(held)==1
    expect(page.locator('#uxExploreStatus')).to_contain_text('Finding')
    held[0].fulfill(json={'items':[{'id':50,'name':'Delayed service','kind':'x402','description':'A controlled delayed response','category':'web_search'}],'total':1})
    expect(page.locator('#xResults .acard')).to_have_count(1)
    expect(page.locator('#xResults')).to_contain_text('Delayed service')
    expect(page.locator('#binaryLoader')).not_to_be_visible()
    assert not errors


@pytest.mark.parametrize('width',[320,390])
def test_mobile_policy_close_button_keeps_its_label_on_one_line(pearl_page,width):
    page,errors,_=pearl_page
    page.set_viewport_size({'width':width,'height':844})
    page.goto(ORIGIN+'/')
    for key in ['terms','privacy','contact','notifications']:
        page.locator('footer [data-footer-key="'+key+'"]').click()
        button=page.locator('#legalModal .legal-modal-footer>.btn')
        expect(button).to_be_visible()
        assert button.evaluate('''n=>{const r=document.createRange();r.selectNodeContents(n);
            return r.getClientRects().length===1&&r.getBoundingClientRect().width<=n.clientWidth;
        }''')
        button.click()
        expect(page.locator('#legalModal')).not_to_be_visible()
    assert not errors


@pytest.mark.parametrize('width',[1440,390])
def test_canvas_click_opens_editable_properties_inside_the_viewport(pearl_page,width):
    page,errors,_=pearl_page
    page.set_viewport_size({'width':width,'height':900})
    page.goto(ORIGIN+'/#workflows')
    expect(page.locator('#pearlWorkflowSearch')).to_be_visible()
    page.locator('.ux-canvas-editor>summary').click()
    page.locator('.wf-node').nth(1).click()
    field=page.locator('#inspNodeName')
    expect(field).to_be_visible()
    page.wait_for_timeout(250)
    canvas=page.locator('#frontWfCanvasContainer').bounding_box()
    bounds=field.bounding_box()
    assert canvas['x']<=bounds['x'] and bounds['x']+bounds['width']<=canvas['x']+canvas['width']+2
    field.fill('Edited research draft')
    expect(page.locator('.wf-node.selected')).to_contain_text('Edited research draft')
    page.locator('[aria-label="Close Inspector"]').click()
    expect(field).not_to_be_visible()
    page.locator('.wf-node').nth(1).get_by_text('Edit',exact=True).click()
    expect(field).to_have_value('Edited research draft')
    count=page.locator('.wf-node').count()
    page.locator('#frontWfInspector').get_by_role('button',name='Delete Node').click()
    expect(page.locator('.wf-node')).to_have_count(count-1)
    page.locator('#btnFrontResetCanvas').click()
    expect(page.locator('.wf-node')).to_have_count(count)
    assert not errors


@pytest.mark.parametrize('width',[320,390])
def test_cookie_actions_keep_whole_words_and_fit_the_dialog(pearl_page,width):
    page,errors,_=pearl_page
    page.set_viewport_size({'width':width,'height':844})
    page.goto(ORIGIN+'/')
    page.locator('footer [data-footer-key="cookies"]').click()
    modal=page.locator('#cookiePrefsModal')
    bounds=modal.bounding_box()
    for button in modal.locator('.legal-modal-footer .btn').all():
        box=button.bounding_box()
        assert bounds['x']<=box['x'] and box['x']+box['width']<=bounds['x']+bounds['width']
        assert button.evaluate('''n=>{const r=document.createRange();r.selectNodeContents(n);
            return r.getClientRects().length<=n.textContent.trim().split(/\\s+/).length;
        }''')
        assert box['height']<=70
    modal.get_by_role('button',name='Cancel',exact=True).click()
    expect(modal).not_to_be_visible()
    assert not errors
