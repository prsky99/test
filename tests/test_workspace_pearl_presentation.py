"""Pearl design references on real isolated customer handlers, not preview pages."""
from pathlib import Path
import json
from tests.test_workspace_typed_flows import graph
from urllib.parse import urlsplit
from playwright.sync_api import expect
from tests.test_customer_typed_authoring import customer_flow,typed_release_world,typed_world,routing  # noqa: F401
from tests.test_workflow_model_ollama import adapter
from tests.test_front_workflow_browser import browser  # noqa: F401
from agent_market.customer_identity_service import COOKIE
from agent_market.workspace_app_factory import AppFactory


def test_pearl_studio_actual_ai_nodes_themes_mobile_and_csp(customer_flow,browser):
    x=customer_flow;value=graph(x.w);value['nodes'][0]['input']['query']='retrieval augmented generation'
    proposer,calls,client=adapter(x,payload=json.dumps({'done':True,'message':{'role':'assistant','content':json.dumps(value)}}));x.core.factory.model_source=AppFactory(x.w.core,model_proposer=proposer)
    context=browser.new_context(viewport={'width':1440,'height':1050},color_scheme='light');context.set_offline(True)
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];external=[];page.on('pageerror',lambda error:errors.append(str(error)))
    def handler(route):
        r=route.request;u=urlsplit(r.url)
        if u.hostname!='customer.test':external.append(r.url);route.abort();return
        response=x.client.request(r.method,u.path+('?'+u.query if u.query else ''),content=r.post_data,headers=r.headers,follow_redirects=False)
        if response.status_code>=400:errors.append(str(response.status_code)+':'+u.path)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
    context.route('**/*',handler)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        expect(page.locator('.workspace-sidebar')).to_be_visible()
        active=page.locator('.workspace-sidebar a[aria-current="page"]')
        expect(active).to_have_count(1);expect(active).to_have_text('Workflows')
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows#library')
        expect(active).to_have_count(1);expect(active).to_have_text('Workflows')
        page.locator('#human-nav-create').click()
        expect(page.locator('#model')).to_be_disabled()
        page.locator('#objective').fill('Find public papers about retrieval augmented generation in exactly two steps.')
        page.locator('#model-consent').check();page.locator('#model').click()
        expect(page.locator('#pearl-flow-preview .pearl-flow-node')).to_have_count(2)
        expect(page.locator('#proposal')).to_contain_text('first')
        expect(page.locator('#credit-quote')).to_have_text('Saving this reviewed change uses 1 credit(s).')
        expect(page.locator('#save-consent')).not_to_be_checked()
        assert not page.locator('#steps').is_visible()
        page.locator('#human-nav-create').click()
        page.evaluate('scrollTo(0,0)')
        assert page.locator('#model').evaluate('(button)=>button.getBoundingClientRect().bottom<=innerHeight')
        root=Path('reports/workspace-human-centered-2026-10-25');page.screenshot(path=str(root/'pearl-studio-light.png'))
        page.locator('#workspace-theme').click();expect(page.locator('body')).to_have_attribute('data-theme','dark')
        page.screenshot(path=str(root/'pearl-studio-dark.png'))
        page.set_viewport_size({'width':390,'height':844});page.evaluate('scrollTo(0,0)')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        assert page.evaluate("document.querySelector('.brand-mark i:last-child').getBoundingClientRect().right<=document.querySelector('.workspace-brand>span:last-child').getBoundingClientRect().left")
        page.screenshot(path=str(root/'pearl-studio-mobile.png'))
        page.goto(page.url.split('#')[0]+'#workflow')
        page.get_by_role('button',name='View or edit steps',exact=True).click()
        expect(page.locator('#steps')).to_be_visible()
        assert not external and not errors
        assert len(calls)==1 and len(x.core.typed.listing(x.ws,x.actor))==0
    finally:context.close();client.close()
