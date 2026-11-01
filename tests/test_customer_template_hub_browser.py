"""Native Pearl template hub with synthetic signed products and private sessions."""
# ruff: noqa: F401,F811
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import expect
from agent_market.customer_identity_service import COOKIE
from tests.test_customer_template_hub import hub_world, customer_flow, typed_release_world, typed_world, routing
from tests.test_front_workflow_browser import browser


@pytest.mark.parametrize('width',[390,1440])
def test_template_hub_select_customize_credit_save_run_and_keyboard(hub_world,browser,width):
    x,rt,wf,ids=hub_world
    context=browser.new_context(offline=True,viewport={'width':width,'height':1000})
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def serve(route):
        request=route.request;u=urlsplit(request.url)
        if u.hostname!='customer.test':external.append(request.url);return route.abort()
        r=x.client.request(request.method,u.path+('?'+u.query if u.query else ''),headers=request.headers,content=request.post_data,follow_redirects=False)
        route.fulfill(status=r.status_code,body=r.content,headers={k:v for k,v in r.headers.items() if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        page.wait_for_timeout(500)
        assert not errors,errors
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        page.locator('#human-nav-templates').click()
        expect(page.get_by_role('heading',name='Start from a template',exact=True)).to_be_visible()
        expect(page.locator('#hub-cards')).to_contain_text('Verified fallback supported')
        page.locator('#hub-cards').get_by_role('button',name='Use or customize template').click()
        expect(page.locator('#hub-support')).to_contain_text('with your permission')
        page.locator('#hub-name').fill('My safe service')
        page.locator('#hub-field-query').fill('public solar research')
        before=len(x.w.calls)
        page.locator('#hub-review').click()
        expect(page.locator('#human-confirm')).to_be_visible()
        expect(page.locator('#human-confirm-yes')).to_be_disabled()
        assert len(x.w.calls)==before
        page.locator('#human-confirm-check').check();page.locator('#human-confirm-yes').click()
        expect(page.locator('#hub-test')).to_be_visible()
        expect(page.locator('#hub-run')).to_be_disabled()
        page.locator('#human-template-try').click()
        page.locator('#human-confirm-check').check();page.locator('#human-confirm-yes').click()
        expect(page.locator('#hub-results')).to_contain_text('succeeded',timeout=20000)
        expect(page.locator('#hub-results')).to_contain_text('Current documentation')
        expect(page.locator('#hub-run-consent')).not_to_be_checked()
        expect(page.locator('#hub-download')).to_be_visible()
        with page.expect_download() as download:
            page.locator('#hub-download').click()
        assert download.value.suggested_filename=='my-workflow.zip'
        expect(page.locator('#hub-state')).to_contain_text('downloaded')
        page.locator('#hub-field-query').fill('changed research')
        expect(page.locator('#hub-run')).to_be_disabled()
        expect(page.locator('#hub-download')).to_be_hidden()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'No horizontal overflow'
        assert not errors and not external
        dest=Path('reports/workspace-template-gemma4-2026-10-24/browser');dest.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(dest/('template-hub-'+str(width)+'.png')),full_page=True)
    finally:context.close()


def test_editable_starter_uses_reviewed_connections_without_inheriting_fallback(hub_world,browser):
    x,rt,wf,ids=hub_world
    context=browser.new_context(offline=True,viewport={'width':1440,'height':1000})
    context.add_cookies([{'name':COOKIE,'value':x.s.raw,'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    def serve(route):
        r=route.request;url=urlsplit(r.url)
        if url.hostname!='customer.test':return route.abort()
        response=x.client.request(r.method,url.path+('?'+url.query if url.query else ''),headers=r.headers,content=r.post_data)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    try:
        page.goto('https://customer.test/customer/organizations/'+x.ws+'/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        page.locator('#human-nav-templates').click()
        page.locator('#hub-blueprints summary').click()
        page.locator('#hub-starters').get_by_role('button',name='Open starter in editor',exact=True).first.click()
        expect(page.locator('#human-builder')).to_be_visible()
        expect(page.locator('#steps fieldset')).to_have_count(2)
        page.locator('#step-editor > summary').click()
        queries=page.locator('#steps [data-role=query]');queries.first.fill('solar energy')
        expect(page.locator('#steps')).to_contain_text('This custom graph needs separate fallback verification.')
        page.locator('#human-review').click()
        expect(page.locator('#review-summary')).not_to_be_empty()
        assert not errors
    finally:context.close()
