"""Untrusted chained output remains text in the real customer result renderer."""
import json
from urllib.parse import urlsplit

from playwright.sync_api import expect

from agent_market.customer_identity_service import COOKIE
from tests.test_customer_ten_workflows import ten_world,customer_flow,typed_release_world,typed_world,routing
from tests.test_front_workflow_browser import browser
from tests.workspace_credit_helpers import save_with_credit
from tests.human_workspace_helpers import manual,confirm,load_first


def test_ten_step_output_rendering_escapes_markup_and_survives_history_reload(ten_world,browser):
    env=ten_world; x=env.x; context=browser.new_context(offline=True)
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test',
        'secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page(); errors=[]; external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def forward(route):
        request=route.request; url=urlsplit(request.url)
        if url.hostname!='customer.test':external.append(request.url);route.abort();return
        response=x.client.request(request.method,url.path+('?'+url.query if url.query else ''),headers=request.headers,content=request.post_data,follow_redirects=False)
        if response.status_code>=400:errors.append(str(response.status_code)+':'+url.path)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items()
            if k not in ('content-length','content-encoding','transfer-encoding','set-cookie')})
    context.route('**/*',forward)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        manual(page)
        page.locator('#name').fill('Synthetic ten-step output escaping')
        for _ in range(8):page.locator('#add').click()
        expect(page.locator('#add')).to_be_disabled()
        query='<img src=x onerror=alert(1)> public documentation'
        page.locator('.step-advanced').evaluate_all('ds=>ds.forEach(d=>d.open=true)')
        for index,rid in enumerate(env.ids):
            row=page.locator('#steps fieldset').nth(index)
            row.locator('[data-field=choice]').select_option(str(rid)+'|docs.search.v1')
            row.locator('[data-field=input]').fill(json.dumps({'query':query,'language':'en','limit':1} if not index else {'language':'en','limit':1}))
            row.locator('[data-field=bindings]').fill(json.dumps({} if not index else {'query':{'node_id':'step_'+str(index),'path':['items',0,'title']}}))
            row.locator('[data-field=after]').fill(json.dumps([] if not index else ['step_'+str(index)]))
        # Every step stays visible as the graph grows (2026-10-21: only the first five were shown).
        expect(page.locator('#flow-count')).to_have_text('10 steps · Review each input before running')
        page.locator('#human-show-steps').click()
        preview=page.locator('#pearl-flow-preview').bounding_box()
        for box in page.locator('#pearl-flow-preview .pearl-flow-node').evaluate_all('nodes=>nodes.map(n=>n.getBoundingClientRect().toJSON())'):
            assert preview['x']-1<=box['x'] and box['x']+box['width']<=preview['x']+preview['width']+1
        expect(page.locator('#steps [data-human-source]').nth(1)).to_have_value('step_1')
        page.locator('#human-review').click();expect(page.locator('#proposal')).to_contain_text('step_10')
        assert not env.trace
        save_with_credit(page)
        expect(page.locator('#history')).to_have_text('No retained tests for this workflow.')
        page.locator('#human-try').click();expect(page.locator('#test-review')).to_contain_text('step_10')
        expect(page.locator('#run')).to_be_disabled()
        confirm(page)
        expect(page.locator('#history')).to_have_text('Workflow succeeded')
        expect(page.locator('#results article')).to_have_count(10)
        expect(page.locator('#results .result-summary')).to_have_text('All steps completed.')
        expect(page.locator('#results article h3').first).to_have_text('Step 10 · Research search · Completed')
        expect(page.locator('#results article h3').last).to_have_text('Step 9 · Research search · Completed')
        expect(page.locator('#test-estimate')).to_contain_text('calls up to 10 agents')
        page.locator('#results > details > summary').click()
        expect(page.locator('#results')).to_contain_text(query)
        expect(page.locator('#results article').first).to_contain_text('Agent 10')
        assert len(env.trace)==10 and not external and not errors
        assert page.locator('#results img,#results script,#results iframe').count()==0
        page.reload();expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        load_first(page); expect(page.locator('#results article')).to_have_count(10)
        assert len(env.trace)==10 and not external and not errors
        # Retiring asks first; Keep changes nothing, Retire stops new tests.
        page.locator('#human-workflow-settings > summary').click()
        page.locator('#retire').click();expect(page.locator('#retire-dialog')).to_be_visible()
        page.get_by_role('button',name='Keep workflow',exact=True).click()
        expect(page.locator('.workflow-card').first).to_contain_text('Open workflow')
        page.locator('#retire').click();page.get_by_role('button',name='Retire workflow',exact=True).click()
        expect(page.locator('.workflow-card').first).to_contain_text('Archived workflow')
        expect(page.locator('#retire')).to_be_disabled();expect(page.locator('#prepare')).to_be_disabled()
        assert len(env.trace)==10 and not external and not errors
    finally:context.close()
