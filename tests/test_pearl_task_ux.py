"""Realistic-volume and task-flow regressions for the public working menus."""
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_pearl_frontend import ORIGIN, browser, client, pearl_page


@pytest.mark.parametrize('width,columns', [(1440,3),(1024,2),(768,2),(390,1)])
def test_all_45_results_use_the_full_work_area_and_load_more(pearl_page, width, columns):
    page, errors, calls = pearl_page
    reads = []
    items = [{'id':i+1,'name':'Research capability '+str(i+1),'kind':['a2a','mcp'][i%2],
              'description':'Find public research sources and summarize selected findings with references.',
              'category':'web_search','eval_grade':'A','has_report':True,
              'connection_readiness':{'verified_callable':True}}for i in range(90)]

    def results(route):
        params=parse_qs(urlsplit(route.request.url).query, keep_blank_values=True)
        reads.append(params)
        limit=int(params.get('limit',['45'])[0])
        offset=int(params.get('offset',['0'])[0])
        route.fulfill(json={'items':items[offset:offset+limit],'total':90,'matched_report_count':90,
                            'has_more':offset+limit<90,'next_offset':offset+limit if offset+limit<90 else None})

    page.route('**/api/explore?*', results)
    page.set_viewport_size({'width':width,'height':900})
    page.goto(ORIGIN+'/#explore')
    cards=page.locator('#xResults .acard:not(.skeleton-card)')
    expect(cards).to_have_count(15)
    expect(page.locator('#pearlAgentPreview')).not_to_be_visible()
    expect(page.locator('#xTitle')).to_contain_text('15')
    grid=page.locator('#xResults').bounding_box()
    main=page.locator('.main-wrap').bounding_box()
    assert grid['width']>=main['width']-4
    assert page.locator('#xResults').evaluate('(n)=>getComputedStyle(n).gridTemplateColumns.split(" ").length')==columns
    assert cards.first.bounding_box()['height']<280
    if width==1440:assert grid['height']<4500
    assert any(query.get('limit')==['15']for query in reads)  # first page 15 (11-12)
    assert len(set(cards.evaluate_all('(nodes)=>nodes.map(n=>n.dataset.id)')))==15
    page.locator('[data-ux-view="list"]').click()
    expect(cards).to_have_count(15)
    assert page.locator('#xResults').get_attribute('data-layout')=='list'
    assert page.locator('#xResults').evaluate('(n)=>getComputedStyle(n).gridTemplateColumns.split(" ").length')==1
    # Measure the items inside every row, rather than only page-level overflow.
    assert cards.evaluate_all('''nodes => nodes.flatMap(c => {
        const b=c.getBoundingClientRect();
        return [...c.querySelectorAll('.pearl-result-heading,.kind-badge,.d,.m,.pearl-result-actions,.pearl-card-actions')]
            .filter(n=>{const r=n.getBoundingClientRect();return r.left<b.left-2||r.right>b.right+2});
    }).length''')==0
    toggle=page.locator('.ux-filter-toggle')  # phones fold the filters behind one button (pearl-ui.js)
    if toggle.is_visible():
        toggle.click()
    page.locator('#xHasReport').check()
    expect(cards).to_have_count(15)
    page.wait_for_timeout(350)
    expect(page.locator('#xLoadMore')).to_be_visible()
    page.locator('#xLoadMore').click()
    expect(cards).to_have_count(60)
    assert cards.evaluate_all('''nodes => nodes.every(c=>{
        const b=c.getBoundingClientRect();return [...c.children].every(n=>{
            const r=n.getBoundingClientRect();return r.left>=b.left-2&&r.right<=b.right+2;
        });
    })''')
    assert reads[-1]['limit']==['45'] and reads[-1]['offset']==['15'] and reads[-1]['has_report']==['true']
    assert len(set(cards.evaluate_all('(nodes)=>nodes.map(n=>n.dataset.id)')))==60
    expect(page.locator('#binaryLoader')).not_to_be_visible()
    page.locator('[data-ux-view="cards"]').click()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    assert not errors


def test_test_inputs_are_linear_and_empty_result_is_collapsed(pearl_page):
    page,errors,calls=pearl_page
    page.goto(ORIGIN+'/#test')
    expect(page.locator('.ux-example-picker')).to_be_visible()
    expect(page.locator('.ux-test-input')).to_be_visible()
    expect(page.locator('#uxTestResultBody')).not_to_be_visible()
    assert page.locator('#uxTestResultPanel').bounding_box()['height']<230
    page.locator('#uxToggleTestResult').click()
    expect(page.locator('#uxTestResultBody')).to_be_visible()
    page.locator('[data-subtab="raw"]').click()
    expect(page.locator('#tbInspectorRaw')).to_be_visible()
    page.locator('#uxToggleTestResult').click()
    expect(page.locator('#uxTestResultBody')).not_to_be_visible()
    expect(page.locator('#tbHistoryTable')).not_to_be_visible()
    page.locator('.ux-history>summary').click()
    expect(page.locator('#tbHistoryTable')).to_be_visible()
    assert not [(m,p)for m,p in calls if m=='POST'] and not errors


def test_workflow_presents_steps_and_output_without_blocking_modal(pearl_page,client):
    page,errors,calls=pearl_page
    from tests.test_pearl_frontend import mock_selectable_templates
    mock_selectable_templates(page,client)
    page.goto(ORIGIN+'/#workflows')
    expect(page.locator('#pearlWorkflowSearch')).to_be_visible()
    expect(page.locator('.ux-workflow-steps')).to_be_visible()
    expect(page.locator('#frontWfCanvasContainer')).not_to_be_visible()
    assert page.locator('#uxWorkflowResultPanel').bounding_box()['height']<230
    page.locator('.ux-canvas-editor>summary').click()
    expect(page.locator('#frontWfCanvasContainer')).to_be_visible()
    page.evaluate('openFrontNodeInspector(frontCanvasGraph.nodes[1].id)')
    page.locator('#inspNodeName').fill('Keep my canvas draft')
    selected=page.locator('#pearlWorkflowChoices').get_attribute('data-selected-id')
    page.locator('#btnFrontWfViewTemplates').click()
    page.locator('#frontTemplatesGrid [data-template-id="'+selected+'"]').get_by_role('button',name='Use workflow',exact=True).click()
    expect(page.locator('#inspNodeName')).to_have_value('Keep my canvas draft')
    page.evaluate('showFrontRunOutputModal({status:"failed",results:[{name:"News",status:"failed",output:"No output available."}]})')
    expect(page.locator('#frontWfRunModal')).not_to_be_visible()
    expect(page.locator('#pearlWorkflowResult')).to_contain_text('No output available.')
    page.locator('#uxFullRunDetails').click()
    expect(page.locator('#frontWfRunModal')).to_be_visible()
    page.keyboard.press('Escape')
    assert not [(m,p)for m,p in calls if m=='POST'] and not errors


def test_chat_starter_does_not_send_and_failed_request_restores_draft(pearl_page):
    page,errors,calls=pearl_page
    page.route('**/chat',lambda route:route.fulfill(status=503,json={'detail':'Unavailable'}))
    page.goto(ORIGIN+'/#chat')
    expect(page.locator('#pearlChatAgentDetails')).not_to_be_visible()
    page.locator('[data-ux-task]').first.click()
    expect(page.locator('#chatInput')).not_to_have_value('')
    assert not [(m,p)for m,p in calls if m=='POST']
    task=page.locator('#chatInput').input_value()
    page.locator('#chatSubmit').click()
    expect(page.locator('#chatStatus')).to_contain_text('could not be completed')
    expect(page.locator('#chatInput')).to_have_value(task)
    expect(page.locator('#chatSubmit')).to_be_enabled()
    assert not errors


def test_registration_starts_with_endpoint_and_reuses_inspection_guard(pearl_page):
    page,errors,calls=pearl_page
    requests=[]
    def reject(route):
        requests.append(route.request.post_data_json)
        route.fulfill(status=400,json={'detail':'Controlled inspection rejection.'})
    page.route('**/api/register/inspect',reject)
    page.goto(ORIGIN+'/#register')
    assert page.locator('#regForm>.field').first.locator('input').get_attribute('id')=='regUrl'
    expect(page.locator('.ux-registration-help aside')).not_to_be_visible()
    page.locator('#regUrl').fill('https://agent-fixture.example/mcp')
    page.locator('#uxInspectEndpoint').click()
    expect(page.locator('#uxInspectEndpoint')).to_be_enabled()
    assert requests==[{'url':'https://agent-fixture.example/mcp'}]
    expect(page.locator('#regUrl')).to_have_value('https://agent-fixture.example/mcp')
    assert not errors
