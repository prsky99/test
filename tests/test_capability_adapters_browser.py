"""Customer consent exposes the reviewed adapter and sends native input only."""
import json
from urllib.parse import urlsplit

from playwright.sync_api import expect

from agent_market.customer_identity_service import COOKIE
from tests.test_capability_adapters import adapted,customer_flow,typed_release_world,typed_world,routing
from tests.test_front_workflow_browser import browser
from tests.workspace_credit_helpers import save_with_credit


def test_customer_prepares_adapter_notice_and_sees_chained_confirmed_results(adapted,browser):
    env=adapted;x=env.x;context=browser.new_context(offline=True)
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test',
        'secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def handle(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='customer.test':external.append(req.url);route.abort();return
        response=x.client.request(req.method,url.path,headers=req.headers,content=req.post_data,follow_redirects=False)
        if response.status_code>=400:errors.append(response.status_code)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items()
            if k not in ('content-length','content-encoding','transfer-encoding','set-cookie')})
    context.route('**/*',handle)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        # The guided workspace opens on its hub; manual creation reveals the step editor.
        from tests.human_workspace_helpers import manual, confirm
        manual(page)  # opens the step editor
        page.locator('#name').fill('Reviewed public paper connection')
        # Guided inputs: the first step searches; the second is bound to its first result title.
        rows=page.locator('#steps fieldset');expect(rows).to_have_count(2)
        wanted=str(env.rid)+'|docs.search.v1'
        for index in range(2):  # the picker's raw select stays visually hidden
            rows.nth(index).locator('[data-field=choice]').evaluate("(e,v)=>{e.value=v;e.dispatchEvent(new Event('change',{bubbles:true}))}",wanted)
            assert rows.nth(index).locator('[data-field=choice]').input_value()==wanted
        page.locator('[data-role=query]').first.fill('Machine learning')
        expect(page.locator('[data-human-source]').nth(1)).to_have_value('step_1')
        assert json.loads(page.locator('[data-field=bindings]').nth(1).input_value())=={'query':{'node_id':'step_1','path':['items',0,'title']}}
        page.locator('#human-review').click();expect(page.locator('#human-save')).to_be_enabled()
        page.locator('#human-save').click();confirm(page)
        expect(page.locator('#human-try')).to_be_enabled();assert not env.calls
        # The run confirmation carries the adapter notice before any provider call.
        page.locator('#human-try').click();expect(page.locator('#human-confirm')).to_be_visible()
        expect(page.locator('#human-confirm')).to_contain_text('Public paper-index search')
        expect(page.locator('#human-confirm')).to_contain_text('200 characters');assert not env.calls
        page.locator('#human-confirm-check').check();page.locator('#human-confirm-yes').click()
        expect(page.locator('#results')).to_contain_text('All steps completed',timeout=20000)
        expect(page.locator('#results')).to_contain_text('Paper index record')
        assert env.calls==[{'query':'Machine learning','limit':1},{'query':'Machine learning / Research','limit':1}]
        assert not errors and not external
    finally:context.close()
