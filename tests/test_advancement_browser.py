"""Actual Chromium renders selected private facts and never retries mutations."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_advancement_api import advancement_api
from tests.test_workspace_execution_api import private_api
from tests.test_front_workflow_browser import browser
from tests.test_workspace_browser import sign_in,select_space


@pytest.fixture
def advancement_page(advancement_api,browser):
    w=advancement_api;context=browser.new_context();w.page=context.new_page();w.errors=[];w.external=[];w.requests=[]
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='admin.test':w.external.append(req.url);return route.abort()
        w.requests.append((req.method,url.path,req.post_data))
        if url.path=='/admin/assets/advancement-admin.js':
            return route.fulfill(status=200,content_type='application/javascript',body=Path('agent_market/gateway/advancement-admin.js').read_text())
        response=w.client.request(req.method,url.path+('?'+url.query if url.query else ''),headers=req.headers,content=req.post_data)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve);w.page.on('pageerror',lambda error:w.errors.append(str(error)))
    sign_in(w);select_space(w,w.ws)
    if not w.page.evaluate('Boolean(window.AdvancementAdmin)'):
        w.page.add_script_tag(url='https://admin.test/admin/assets/advancement-admin.js')
    w.page.evaluate('(ws)=>window.AdvancementAdmin.open(ws)',w.ws['id'])
    expect(w.page.locator('#advancementAdminDialog')).to_be_visible()
    yield w
    context.close()


def test_native_dialog_simulation_and_reviewed_patch_require_distinct_unchecked_purposes(advancement_page):
    w=advancement_page;dialog=w.page.locator('#advancementAdminDialog')
    expect(dialog).to_contain_text('No customer charge')
    consent=dialog.get_by_label('Approve this exact simulated logical operation. This is not payment consent.')
    expect(consent).not_to_be_checked();dialog.get_by_role('button',name='Approve simulation',exact=True).click()
    assert not any(method=='POST' and path.endswith('/ledger/approve') for method,path,_ in w.requests)
    consent.check();dialog.get_by_role('button',name='Approve simulation',exact=True).click()
    expect(dialog).to_contain_text('approved 1')
    approve=dialog.get_by_label('Review and authorize this simulation event once.')
    expect(approve).not_to_be_checked();approve.check();dialog.get_by_role('button',name='Record simulated outcome').click()
    expect(dialog).to_contain_text('settled 1 · completed')
    dialog.get_by_role('button',name='Draft support',exact=True).click()
    expect(dialog).to_contain_text('deterministic JSON patch')
    dialog.locator('select').nth(0).select_option(w.draft['id'])
    expect(dialog.locator('select').nth(1)).to_contain_text('Snapshot 1')
    dialog.locator('select').nth(1).select_option(w.snapshot['id'])
    dialog.get_by_label('Proposed draft name').fill('Reviewed browser draft')
    review=dialog.get_by_label('Review these private draft changes before preparing a patch.')
    expect(review).not_to_be_checked();review.check();dialog.get_by_role('button',name='Prepare exact JSON patch').click()
    expect(dialog).to_contain_text('replace /name: "Reviewed browser draft"')
    apply=dialog.get_by_label('Apply this exact patch to a new private draft revision.')
    expect(apply).not_to_be_checked();apply.check();dialog.get_by_role('button',name='Apply reviewed patch').click()
    expect(dialog).to_contain_text('Private draft revision 2 saved')
    dialog.get_by_role('button',name='Readiness',exact=True).click()
    expect(dialog).to_contain_text('Not ready')
    expect(dialog).to_contain_text('source adapter not configured')
    assert not w.calls and not w.errors and not w.external
    assert len([1 for method,path,_ in w.requests if method=='POST' and path.endswith('/apply')])==1


def test_support_markup_is_text_and_logout_discards_private_dialog(advancement_page):
    w=advancement_page;dialog=w.page.locator('#advancementAdminDialog')
    dialog.get_by_role('button',name='Draft support',exact=True).click()
    expect(dialog).to_contain_text('deterministic JSON patch')
    dialog.locator('select').nth(0).select_option(w.draft['id'])
    expect(dialog.locator('select').nth(1)).to_contain_text('Snapshot 1')
    dialog.locator('select').nth(1).select_option(w.snapshot['id'])
    attack='<img src=x onerror=window.__supportXss=1>'
    dialog.get_by_label('Proposed draft name').fill(attack)
    dialog.get_by_label('Review these private draft changes before preparing a patch.').check()
    dialog.get_by_role('button',name='Prepare exact JSON patch').click()
    expect(dialog).to_contain_text(attack)
    assert dialog.locator('img,script,iframe').count()==0
    assert w.page.evaluate('window.__supportXss||0')==0
    w.page.evaluate('token="";currentUser=null;window.AdvancementAdmin.onSession()')
    expect(dialog).to_have_count(0)
    assert not w.errors and not w.external and not w.calls
