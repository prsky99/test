"""Frontend layout review with real isolated handlers and no operating writes."""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_pearl_frontend import client,pearl_page  # noqa: F401
from tests.test_customer_organizations import orgs  # noqa: F401
from tests.test_customer_organizations_browser import account_page
from tests.test_front_workflow_browser import browser  # noqa: F401

ROOT=Path('reports/frontend-layout-system-2026-10-26')


def capture(page,name):
    phase=os.getenv('LAYOUT_CAPTURE_PHASE','after');folder=ROOT/phase;folder.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(folder/(name+'.png')))
    metrics=page.evaluate('''()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
        controls:[...document.querySelectorAll('main input:not([type=hidden]),main select,main textarea,main button')]
        .filter(n=>n.getClientRects().length).slice(0,24).map(n=>{const r=n.getBoundingClientRect();return {id:n.id,tag:n.tagName,x:r.x,y:r.y,width:r.width,height:r.height}})})''')
    (folder/(name+'.json')).write_text(json.dumps(metrics,indent=2)+'\n')
    assert metrics['scrollWidth']<=metrics['width']+1,metrics


@pytest.mark.parametrize('width',[320,768,1440])
def test_all_public_menus_have_bounded_layout_and_readonly_navigation(pearl_page,width):
    page,errors,calls=pearl_page;page.set_viewport_size({'width':width,'height':1000})
    for panel in ('overview','status','learn','explore','test','workflows','chat','register','about'):
        page.goto('https://agentconcierge.biz/#'+panel)
        expect(page.locator('[data-panel="'+panel+'"]')).to_be_visible()
        capture(page,'public-'+panel+'-'+str(width))
        if panel=='about':
            expect(page.locator('.about-necklace-art')).to_be_hidden()
            heading=page.locator('.reference-about-intro h1').bounding_box()
            lead=page.locator('.reference-about-intro .lead').bounding_box()
            assert lead['y']>=heading['y']+heading['height']+12
        if panel=='learn' and width<=1100:
            assert page.locator('.reference-protocol-copy').first.bounding_box()['width']>=140
        if panel=='register':
            for name in ('regName','regCategory'):
                field=page.locator('#'+name);label=page.locator('label[for="'+name+'"]')
                a,b=label.bounding_box(),field.bounding_box();assert b['y']>=a['y']+a['height']+7
            expect(page.locator('#regKind + .pearl-protocol-segmented button')).to_have_count(3)
            for button in page.locator('#regKind + .pearl-protocol-segmented button').all():
                box=button.bounding_box();assert box['x']>=0 and box['x']+box['width']<=width
    assert not errors
    assert not any(method=='POST' for method,_ in calls)


@pytest.mark.parametrize('width',[390,1440])
def test_private_account_credit_and_support_layout(orgs,browser,width):
    client,context,page,errors,external,requests=account_page(orgs,browser)
    from agent_market.workspace_admin_service import router_for
    from agent_market.workspace_admin_events import migrate
    migrate(orgs.store,orgs.core.key)
    client.app.include_router(router_for(orgs.core,orgs.access,public=True))
    try:
        page.set_viewport_size({'width':width,'height':1000})
        page.goto('https://customer.test/customer/organizations#account')
        expect(page.locator('#account')).to_be_visible()
        page.locator('#account-removal > summary').click()
        capture(page,'workspace-account-'+str(width))
        page.goto('https://customer.test/customer/plan?workspace='+orgs.organization['id'])
        expect(page.locator('#enroll')).to_be_visible()
        capture(page,'workspace-enrollment-'+str(width))
        page.goto('https://customer.test/customer/support')
        expect(page.locator('#support-content')).to_be_visible()
        capture(page,'workspace-support-'+str(width))
        for name in ('support-subject','support-message','support-organization'):
            field=page.locator('#'+name)
            assert field.evaluate('(n)=>parseFloat(getComputedStyle(n.parentElement).rowGap)')>=8
        page.goto('https://customer.test/customer/workspaces')
        expect(page.locator('#manage')).to_be_visible()
        capture(page,'workspace-access-'+str(width))
        if width<900:
            menu=page.locator('#workspace-menu').bounding_box()
            brand=page.locator('.workspace-brand').bounding_box()
            assert 40<=menu['width']<=48 and brand['x']>=menu['x']+menu['width']+5
        assert not errors and not external
        assert not any(method=='POST' for method,_ in requests)
    finally:context.close();client.close()


@pytest.mark.parametrize('width',[390,1440])
def test_footer_forms_fit_the_dialog_without_submitting(pearl_page,width):
    page,errors,calls=pearl_page;page.set_viewport_size({'width':width,'height':1000})
    page.goto('https://agentconcierge.biz/#overview')
    for label in ('Contact','Notification Preferences','Do Not Sell or Share My Personal Info'):
        page.get_by_role('link',name=label,exact=True).click()  # footer items are links that open the dialog
        dialog=page.locator('#legalModal');expect(dialog).to_be_visible()
        assert dialog.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
        if label=='Contact' and width<700:
            email=page.locator('#inqEmail').bounding_box();subject=page.locator('#inqSubject').bounding_box()
            assert subject['y']>=email['y']+email['height']+20
        capture(page,'footer-'+label.split()[0].lower()+'-'+str(width))
        dialog.get_by_role('button',name='Close',exact=True).click()
    assert not errors
    assert not any(method=='POST' for method,_ in calls)
