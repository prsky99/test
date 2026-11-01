"""Capture real workspace handlers with a disposable synthetic account only."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect
from tests.test_customer_typed_authoring import customer_flow,typed_release_world,typed_world,routing
from tests.test_workflow_model_ollama import adapter
from tests.test_front_workflow_browser import browser
from agent_market.customer_identity_service import COOKIE
from agent_market.workspace_app_factory import AppFactory
from scripts.audit_frontend_ux_20261020 import INSPECT,OUT


def test_capture_workspace_review(customer_flow,browser):
    x=customer_flow
    proposer,calls,model_client=adapter(x)
    x.core.factory.model_source=AppFactory(x.w.core,model_proposer=proposer)
    context=browser.new_context(viewport={'width':1440,'height':1000},color_scheme='light',reduced_motion='reduce')
    context.set_offline(True)
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    result={'scope':'isolated real workspace handlers; synthetic identity, agents and AI response; not the specified live account',
            'live_mutations':False,'external_requests':[],'screens':[],'errors':[]}
    def route_handler(route):
        r=route.request;u=urlsplit(r.url)
        if u.hostname!='customer.test':result['external_requests'].append(u.hostname);return route.abort()
        res=x.client.request(r.method,u.path+('?' +u.query if u.query else ''),content=r.post_data,headers=r.headers,follow_redirects=False)
        route.fulfill(status=res.status_code,body=res.content,headers={k:v for k,v in res.headers.items() if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
    context.route('**/*',route_handler)
    page=context.new_page();page.on('pageerror',lambda error:result['errors'].append(str(error)))
    def capture(name):
        for width,height,device in ((1440,1000,'desktop'),(390,844,'mobile')):
            page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(150)
            data=page.evaluate(INSPECT);data.update(name=name,device=device)
            file='evidence/isolated-'+name+'-'+device+'.png'
            page.screenshot(path=str(OUT/file),full_page=True);data['screenshot']=file
            result['screens'].append(data)
        page.set_viewport_size({'width':1440,'height':1000})
        (OUT/'isolated-workspace-inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    try:
        page.goto('https://customer.test/customer/organizations')
        expect(page.locator('#org-title')).to_have_text('Customer multi-step studio')
        capture('workspace-overview')
        page.get_by_role('link',name='Members & invitations',exact=True).click()
        capture('workspace-members')
        page.get_by_role('link',name='Account',exact=True).first.click()
        capture('workspace-account')
        page.goto('https://customer.test/customer/plan?workspace='+x.ws)
        page.wait_for_timeout(300);capture('workspace-plan')
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        capture('workspace-studio-empty')
        page.locator('#objective').fill('Find public research sources in two connected read-only steps.')
        page.locator('#name').fill('Research evidence review')
        page.locator('#model-consent').check();page.locator('#model').click()
        expect(page.locator('#pearl-flow-preview .pearl-flow-node')).to_have_count(2)
        capture('workspace-ai-proposal')
        page.locator('#stage-review').click();capture('workspace-review')
        page.locator('#save-consent').check();page.locator('#save').click()
        expect(page.locator('#status')).to_have_text('Current workspace action confirmed.')
        page.locator('#stage-test').click();page.locator('#prepare').click()
        expect(page.locator('#test-review')).not_to_be_empty();capture('workspace-test-review')
        page.locator('#run-consent').check();page.locator('#run').click()
        expect(page.locator('#results')).not_to_be_empty();capture('workspace-test-result')
        page.locator('#stage-export').click();capture('workspace-download')
        result['synthetic_model_calls']=len(calls)
        assert not result['external_requests']
    finally:
        (OUT/'isolated-workspace-inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        context.close();model_client.close()
