"""Chromium consent and private controls, with all network routes isolated."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser
from tests.test_workflow_fallback import routing,activate
from tests.test_workflow_fallback_api import routing_api

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


@pytest.fixture
def fallback_page(browser,routing_api,rotated_bootstrap_admin):
    routing,public,admin=routing_api;context=browser.new_context();page=context.new_page();errors=[];external=[];bodies=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        client=public if url.hostname=='agentconcierge.biz' else admin if url.hostname=='admin.test' else None
        if client is None:external.append(req.url);return route.abort()
        if url.path=='/api/workflows/run':bodies.append(req.post_data_json)
        r=client.request(req.method,url.path+('?'+url.query if url.query else ''),content=req.post_data,headers=req.headers)
        route.fulfill(status=r.status_code,body=r.content,headers={k:v for k,v in r.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    yield page,routing,errors,external,bodies
    context.close()


def test_public_consent_is_unchecked_per_run_and_hidden_without_policy(fallback_page,monkeypatch):
    page,routing,errors,external,bodies=fallback_page;rt,wf,_,calls,modes,*_=routing
    page.goto('https://agentconcierge.biz/#workflows')
    expect(page.locator('#frontFallbackConsentGroup')).to_be_hidden()
    activate(routing,monkeypatch)
    page.evaluate('async id => {await loadFrontTemplates(true); const t=frontTemplatesCache.find(t=>t.id===id); frontActiveTemplateId=id; frontCanvasGraph={nodes:t.nodes,edges:t.edges}; frontActiveWfName=t.name; updateFrontActiveName();renderFrontCanvas();}',wf['id'])
    expect(page.locator('#frontFallbackConsentGroup')).to_be_visible()
    expect(page.locator('#frontFallbackConsent')).not_to_be_checked()
    expect(page.locator('#frontFallbackNotice')).to_contain_text('your task input may be sent')
    page.locator('#frontFallbackConsent').check();page.locator('#btnFrontRunWorkflow').click()
    if page.locator('#uxFullRunDetails').count():
        expect(page.locator('#uxFullRunDetails')).to_be_visible()
        expect(page.locator('#frontWfRunModal')).to_be_hidden()
        page.locator('#uxFullRunDetails').click()
    expect(page.locator('#frontWfRunModal')).to_be_visible();expect(page.locator('#btnFrontRunWorkflow')).to_be_enabled()
    assert bodies[-1]['allow_fallback'] is True and bodies[-1]['fallback_notice']=='readonly-fallback-v1'
    expect(page.locator('#frontFallbackConsent')).not_to_be_checked()
    page.screenshot(path='reports/advancement-r06-2026-10-18/public-fallback-consent.png')
    assert not errors and not external


def test_admin_controls_shadow_setup_and_recovery_dialog(fallback_page,monkeypatch):
    page,routing,errors,external,_=fallback_page;rt,wf,ids,calls,modes,*_=routing
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    expect(page.locator('#adminLoginModal')).to_be_hidden();page.locator('[data-tab="errors"]').click()
    page.locator('#fallbackControlsPanel summary').click();page.locator('#fallbackControlReload').click()
    expect(page.locator('#fallbackEnabled')).not_to_be_checked()
    page.locator('#fallbackWorkflowId').fill(str(wf['id']));page.locator('#fallbackPolicyReload').click()
    expect(page.locator('#fallbackPolicyStatus')).to_contain_text('revision 0')
    expect(page.locator('#fallbackNode option')).to_have_count(1)
    page.locator('#fallbackMode').select_option('shadow');page.locator('#fallbackResourceId').fill(str(ids[1]));page.locator('#fallbackContract').select_option('docs.search.v1')
    page.locator('#fallbackPolicyAuthority').check();page.locator('#fallbackPolicySave').click()
    expect(page.locator('#fallbackPolicyStatus')).to_contain_text('revision 1')
    expect(page.locator('#fallbackPolicyAuthority')).not_to_be_checked()
    # Existing current controls are read only until an explicit apply action.
    page.evaluate('() => loadErrors()');expect(page.locator('#fallbackMode')).to_have_value('shadow')
    page.screenshot(path='reports/advancement-r06-2026-10-18/admin-fallback-controls.png')
    assert not errors and not external


def test_admin_logout_clears_private_policy_form(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,wf,ids,*_=routing
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    expect(page.locator('#adminLoginModal')).to_be_hidden();page.locator('[data-tab="errors"]').click()
    page.locator('#fallbackControlsPanel summary').click();page.locator('#fallbackWorkflowId').fill(str(wf['id']));page.locator('#fallbackPolicyReload').click()
    expect(page.locator('#fallbackPolicyStatus')).to_contain_text('revision 0')
    page.locator('#fallbackResourceId').fill(str(ids[1]));page.locator('#logoutBtn').click()
    expect(page.locator('#fallbackControlsPanel')).to_be_hidden()
    expect(page.locator('#fallbackWorkflowId')).to_have_value('');expect(page.locator('#fallbackResourceId')).to_have_value('')
    assert page.locator('#fallbackNode option').count()==0 and not errors and not external
