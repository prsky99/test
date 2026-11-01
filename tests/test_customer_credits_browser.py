"""Isolated Chromium enrollment tests; no customer or provider network calls."""
import re
from urllib.parse import urlsplit
from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from agent_market.customer_identity_service import router_for as identity_router, COOKIE
from agent_market.customer_credit_service import router_for
from tests.test_customer_credits import credits, orgs  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


def test_enrollment_separate_unchecked_choices_close_and_rejoin(credits,browser,tmp_path):
    w=credits;app=FastAPI();app.include_router(identity_router(w.store,w.core.key,identity=w.core,admin=False));app.include_router(router_for(w.core,w.access))
    context=browser.new_context(viewport={'width':390,'height':844});context.set_offline(True)
    context.add_cookies([{'name':COOKIE,'value':w.auths[0]['session_token'],'url':'https://customer.test','secure':True,'httpOnly':True,'sameSite':'Lax'}])
    errors=[];requests=[];page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    with TestClient(app,base_url='https://customer.test') as client:
        def handler(route):
            r=route.request;u=urlsplit(r.url);assert u.hostname=='customer.test'
            response=client.request(r.method,u.path+('?'+u.query if u.query else ''),content=r.post_data,headers=r.headers)
            requests.append((r.method,u.path,response.status_code))
            route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('set-cookie','content-length','content-encoding','transfer-encoding')})
        context.route('**/*',handler)
        scoped='ws_'+'b'*32
        page.goto('https://customer.test/customer/plan?workspace='+scoped)
        expect(page.locator('#balance')).to_contain_text('0 credits')
        expect(page.get_by_text('New accounts receive 100 credits',exact=False)).to_be_visible()
        expect(page.locator('#credit-balance-basis')).to_contain_text('grants, credit adjustments and workflow usage')
        expect(page.locator('#credit-balance-basis')).to_be_hidden()
        page.locator('#credit-balance-help > summary').focus()
        page.keyboard.press('Enter')
        expect(page.locator('#credit-balance-basis')).to_be_visible()
        expect(page.locator('.workspace-sidebar [data-workspace-section="templates"]')).to_have_attribute('href','/customer/organizations/'+scoped+'/flows#templates')
        expect(page.locator('#terms')).to_contain_text('100 credits once')
        active=page.locator('.workspace-sidebar a[aria-current="page"]')
        expect(active).to_have_count(1);expect(active).to_have_text('Plan & credits')
        expect(page.locator('#join')).to_be_disabled()
        for key in ('terms-check','privacy-check','adult-check'):expect(page.locator('#'+key)).not_to_be_checked()
        page.screenshot(path='reports/workspace-human-centered-2026-10-25/enrollment-mobile.png',full_page=True)
        page.locator('#terms-check').check();page.locator('#privacy-check').check();expect(page.locator('#join')).to_be_disabled()
        page.locator('#adult-check').check();page.locator('#join').click()
        expect(page.locator('#balance')).to_contain_text('100 credits · Plan active')
        expect(page.locator('#enroll')).to_be_hidden()
        page.locator('.human-plan-soon > summary').click()
        expect(page.get_by_role('button',name='Top up credits · Coming soon')).to_be_disabled()
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.locator('.human-plan-settings > summary').click()
        page.locator('#close-check').check();page.locator('#close').click();expect(page.locator('#balance')).to_contain_text('100 credits · Enrollment closed')
        for key in ('terms-check','privacy-check','adult-check'):page.locator('#'+key).check()
        page.locator('#join').click();expect(page.locator('#balance')).to_contain_text('100 credits · Plan active')
        page.screenshot(path=str(tmp_path/'enrollment-mobile.png'),full_page=True)
        page.screenshot(path='reports/workspace-human-centered-2026-10-25/credits-mobile.png',full_page=True)
        assert not errors and all(r[2]<400 for r in requests)
        # A rejected credit mutation must conceal the retained account balance.
        w.core.logout(w.auths[0]['session_token'])
        page.locator('#close-check').check();page.locator('#close').click()
        # The relay now forwards the query, so sign-in keeps the destination (?next=...).
        expect(page).to_have_url(re.compile(r'^https://customer\.test/customer/sign-in(\?next=.*)?$'))
        expect(page.locator('#balance')).to_have_count(0)
        assert any(method=='POST' and path.endswith('/close') and status==401
                   for method,path,status in requests)
        assert tuple(w.store._db.execute(
            'SELECT status,balance FROM customer_credit_accounts WHERE customer_id=?',
            (w.customers[0].customer_id,)).fetchone()) == ('active',100)
    context.close()
