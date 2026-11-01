"""Read-only visual coverage for less-frequent private frontend surfaces."""
import pytest
from playwright.sync_api import expect

from tests.test_frontend_spacing_browser import capture
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.test_workspace_provider_connections_browser import connection_page,connections,customer_flow,typed_release_world,typed_world,routing  # noqa: F401
from tests.test_customer_authoring_browser import open_page as author_page,authoring,release_world,private_api  # noqa: F401
from tests.test_customer_recovery_browser import open_page as recovery_page,recovery,orgs  # noqa: F401
from tests.test_workspace_human_studio_browser import launch,hub_world  # noqa: F401
from tests.test_customer_identity_browser import page_for as identity_page,customer  # noqa: F401


@pytest.mark.parametrize('width',[390,1440])
def test_provider_key_form_preserves_mask_and_consent_with_spaced_actions(connection_page,width):
    x,page=connection_page;page.set_viewport_size({'width':width,'height':1000})
    page.goto('https://customer.test/customer/organizations/'+x.ws+'/connections')
    expect(page.locator('#provider-status')).to_contain_text('Choose an agent')
    page.locator('#provider-search').fill(str(x.rid));page.locator('#provider-search-form button').click()
    page.get_by_role('button',name='Connection options',exact=True).click()
    expect(page.locator('#provider-key')).to_be_visible()
    expect(page.locator('#provider-key')).to_have_attribute('type','password')
    expect(page.locator('#provider-key-consent')).not_to_be_checked()
    expect(page.locator('#provider-save')).to_be_disabled()
    assert page.locator('#provider-dialog').evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
    a=page.locator('label[for="provider-key"]').bounding_box();b=page.locator('#provider-key').bounding_box()
    assert b['y']>=a['y']+a['height']+7
    capture(page,'workspace-provider-'+str(width))
    assert not x.manager.listing(x.ws,x.actor)['connections']


@pytest.mark.parametrize('width',[390,1440])
def test_private_task_and_recovery_action_groups_preserve_readonly_state(authoring,recovery,browser,width):
    context,page,errors,external=author_page(authoring,browser)
    try:
        page.set_viewport_size({'width':width,'height':1000})
        expect(page.locator('.layout-select-action')).to_have_count(2)
        expect(page.locator('#run-consent')).not_to_be_checked()
        expect(page.locator('#run')).to_be_disabled()
        capture(page,'workspace-private-task-'+str(width))
        assert not errors and not external
    finally:context.close()
    client,context,page,errors,external=recovery_page(recovery,browser,0)
    try:
        page.set_viewport_size({'width':width,'height':1000})
        expect(page.locator('#owner')).to_be_visible()
        expect(page.locator('#enroll-consent')).not_to_be_checked()
        assert page.locator('#refresh').locator('..').get_attribute('class')=='layout-actions'
        capture(page,'workspace-recovery-'+str(width))
        assert not errors and not external
    finally:context.close();client.close()


@pytest.mark.parametrize('width',[390,1440])
def test_workflow_create_library_templates_and_review_layout(hub_world,browser,width):
    x,*_=hub_world;context,page,errors,requests,calls,client=launch(x,browser,width=width)
    try:
        capture(page,'workspace-create-'+str(width))
        page.locator('#human-nav-library').click()
        page.evaluate("()=>{libraryFlows=[{id:'tf_layout',name:'A long research workflow name that should wrap within its own card',active:true,step_count:10,updated:1792900000}];renderLibrary()}")
        capture(page,'workspace-library-'+str(width))
        page.locator('#human-nav-templates').click()
        expect(page.locator('#hub-cards')).not_to_be_empty()
        capture(page,'workspace-templates-'+str(width))
        page.locator('#hub-cards').get_by_role('button',name='Use or customize template',exact=True).click()
        expect(page.locator('#human-builder')).to_be_visible()
        capture(page,'workspace-template-review-'+str(width))
        for theme in ('light','dark'):
            page.locator('body').evaluate('(body,theme)=>body.dataset.theme=theme',theme)
            contrast=page.locator('#hub-support').evaluate('''node=>{
                const style=getComputedStyle(node);
                function luminance(color){
                    const rgb=color.match(/[0-9.]+/g).slice(0,3).map(Number).map(v=>v/255);
                    return rgb.map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
                        .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
                }
                const foreground=luminance(style.color),background=luminance(style.backgroundColor);
                return (Math.max(foreground,background)+.05)/(Math.min(foreground,background)+.05);
            }''')
            assert contrast>=4.5,(theme,contrast)
        capture(page,'workspace-template-review-dark-'+str(width))
        assert not calls and not errors
        assert not any(method=='POST' for method,_ in requests)
    finally:context.close();client.close()


@pytest.mark.parametrize('width',[320,1440])
def test_login_controls_remain_visible_and_never_start_auth_without_click(customer,browser,width):
    client,context,page,errors,external,requests=identity_page(customer,browser)
    try:
        page.set_viewport_size({'width':width,'height':1000})
        page.goto('https://customer.test/customer/sign-in')
        expect(page.get_by_role('button',name='Sign in with Google')).to_be_visible()
        expect(page.locator('#status')).not_to_have_text('Checking sign-in availability.')
        capture(page,'workspace-signin-'+str(width))
        assert not errors and not external
        assert not any(method=='POST' for method,_,_ in requests)
    finally:context.close();client.close()
