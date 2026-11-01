"""Workspace users can find, save, run and download fixed public templates."""
# ruff: noqa: F401,F811
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import expect
from agent_market.customer_identity_service import COOKIE
from tests.test_workspace_shared_template_catalog import ordinary,hub_world,customer_flow,typed_release_world,typed_world,routing
from tests.test_front_workflow_browser import browser

@pytest.mark.parametrize('width',[390,1440])
def test_shared_catalog_fixed_workflow_journey(hub_world,browser,width):
    x,rt,wf,ids=hub_world;ordinary(x,ids,25)
    context=browser.new_context(offline=True,viewport={'width':width,'height':1000})
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def serve(route):
        req=route.request;u=urlsplit(req.url)
        if u.hostname!='customer.test':external.append(req.url);return route.abort()
        r=x.client.request(req.method,u.path,headers=req.headers,content=req.post_data,follow_redirects=False)
        route.fulfill(status=r.status_code,body=r.content,headers={k:v for k,v in r.headers.items() if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        page.locator('#human-nav-templates').click()
        expect(page.locator('#hub-cards article')).to_have_count(4 if width==390 else 8)
        page.locator('#hub-next').click();expect(page.locator('#hub-page')).to_contain_text('Page 2')
        page.locator('#hub-search').fill('Public Documentation 24')
        expect(page.locator('#hub-cards article')).to_have_count(1)
        expect(page.locator('#hub-page')).to_contain_text('Page 1')
        page.locator('#hub-cards').get_by_role('button',name='Use template',exact=True).click()
        expect(page.locator('#hub-support')).to_have_text('Published template · Reviewed default inputs')
        expect(page.locator('#hub-fallback-note')).to_be_hidden()
        expect(page.locator('#hub-agents')).to_contain_text('documentation')
        assert page.locator('#hub-inputs input').count()==0
        page.locator('#hub-name').fill('My shared reference workflow')
        page.locator('#hub-review').click();expect(page.locator('#human-confirm')).to_be_visible()
        page.locator('#human-confirm-check').check();page.locator('#human-confirm-yes').click()
        expect(page.locator('#hub-test')).to_be_visible()
        page.locator('#human-template-try').click()
        expect(page.locator('#human-confirm')).not_to_contain_text('alternative')
        page.locator('#human-confirm-check').check();page.locator('#human-confirm-yes').click()
        expect(page.locator('#hub-results')).to_contain_text('succeeded',timeout=20000)
        expect(page.locator('#hub-download')).to_be_visible()
        with page.expect_download() as event:page.locator('#hub-download').click()
        assert event.value.suggested_filename=='my-workflow.zip'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors and not external
        dest=Path('/Users/kingstonelee/workspace/A2A_Discovery/reports/workflow-compact-picker-2026-10-25')
        page.screenshot(path=str(dest/f'after-workspace-saved-{width}.png'),full_page=True)
        page.locator('#human-nav-templates').click();page.locator('#hub-search').fill('');page.locator('#hub-category').select_option('docs_knowledge')
        expect(page.locator('#hub-page')).to_contain_text('Page 1')
        page.screenshot(path=str(dest/f'after-workspace-catalog-{width}.png'),full_page=True)
    finally:context.close()
