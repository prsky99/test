"""Expanded workspace management remains usable without changing customer data."""
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.test_customer_organizations import orgs  # noqa: F401
from tests.test_customer_organizations_browser import account_page, choose_workspace
from tests.test_front_workflow_browser import browser  # noqa: F401


@pytest.mark.parametrize('width',[320,390,900,1440])
@pytest.mark.parametrize('theme',['light','dark'])
def test_expanded_overview_has_consistent_fields_actions_and_bounds(orgs,browser,width,theme):
    client,context,page,errors,external,requests=account_page(orgs,browser)
    try:
        page.set_viewport_size({'width':width,'height':950})
        if page.locator('body').get_attribute('data-theme')!=theme:
            page.locator('#workspace-theme').click()
        choose_workspace(page)
        expect(page.locator('#org-role')).to_have_text('owner access')
        for selector in ('#member-panel','#individual-panel','#organization-settings','.human-invitations','#create-organization'):
            disclosure=page.locator(selector)
            if not disclosure.evaluate('(node)=>node.open'):
                disclosure.locator(':scope > summary').click()
        expect(page.locator('#rename-name')).to_be_visible()
        expect(page.locator('#recipient')).to_be_visible()
        expect(page.locator('#draft-name')).to_be_visible()
        expect(page.locator('#leave')).to_be_visible()
        expect(page.locator('#archive')).to_be_visible()
        assert page.locator('#organization-settings #rename').count()==1
        assert page.locator('#member-panel #rename').count()==0
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        for selector in ('#rename-name','#recipient','#invite-role','#draft-name','#org-name','#members select'):
            field=page.locator(selector).first
            box=field.bounding_box()
            assert box and box['width']>=80 and box['x']>=0 and box['x']+box['width']<=width+1,(selector,box)
        for form in ('rename','invite','new-draft','create'):
            boxes=page.locator('#'+form+' .overview-field').evaluate_all('''nodes=>nodes.map(n=>{
                const label=n.querySelector('label').getBoundingClientRect(),input=n.querySelector('input,select').getBoundingClientRect();
                return input.top-label.bottom;
            })''')
            assert all(gap>=7 for gap in boxes)
        first=page.locator('#workflow-studio');second=page.locator('#human-overview-templates')
        assert first.evaluate('(n)=>getComputedStyle(n).backgroundColor')!=second.evaluate('(n)=>getComputedStyle(n).backgroundColor')
        if width>=900:
            a,b=first.bounding_box(),second.bounding_box()
            assert abs(a['y']-b['y'])<=1 and b['x']>=a['x']+a['width']+9
        member_actions=page.locator('#members li').first.locator('select,button').evaluate_all('''nodes=>nodes.map(n=>{
            const r=n.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};
        })''')
        for a,b in zip(member_actions,member_actions[1:]):
            assert b['top']>=a['bottom']+7 or b['left']>=a['right']+7
        assert not any(method=='POST' for method,_ in requests)
        assert not errors and not external
        folder=Path('reports/frontend-guidance-design-2026-10-26');folder.mkdir(exist_ok=True,parents=True)
        page.screenshot(path=str(folder/f'overview-open-{theme}-{width}.png'),full_page=True)
    finally:
        context.close();client.close()
