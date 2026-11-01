"""Actual private product transport and native review use only a mock provider."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from agent_market.workspace_service import BASE
from tests.test_workspace_execution_api import private_api
from tests.test_workflow_product_composer import product_world
from tests.test_front_workflow_browser import browser

REPORT=Path('reports/advancement-completion-2026-10-18')


def prepare(x):
    response=x.w.client.post(BASE+'/'+x.ws+'/product-composer/prepare',headers=x.w.headers['owner'],json={'resource_id':x.w.rid,'input':x.inputs})
    assert response.status_code==200,response.text
    return response.json()


def test_actual_private_api_compile_test_proof_and_no_legacy_or_customer_exposure(product_world):
    x=product_world;path=BASE+'/'+x.ws+'/product-composer';plan=prepare(x)
    response=x.w.client.post(path+'/save',headers=x.w.headers['owner'],json={'proposal':plan['proposal'],'signature':plan['signature'],'name':'Products','description':''})
    assert response.status_code==200,response.text
    saved=response.json();nested=BASE+'/'+x.ws+'/drafts/'+saved['draft_id']+'/snapshots/'+saved['snapshot_id']+'/product-test'
    ticket=x.w.client.post(nested+'/prepare',headers=x.w.headers['owner'],json={}).json();assert ticket['notice']=='workspace-products-test-v2'
    response=x.w.client.post(nested+'/runs',headers=x.w.headers['owner'],json={'ticket_id':ticket['ticket_id'],'authorized':True,'notice':ticket['notice']})
    assert response.status_code==200,response.text
    assert response.json()['contract_proof']['outcome']=='passed'
    run=response.json()['run']['id'];proof=x.w.client.get(nested+'/runs/'+run,headers=x.w.headers['viewer'])
    assert proof.status_code==200 and proof.headers['cache-control']=='no-store'
    assert x.w.client.get('/api/workspaces/'+x.ws+'/product-composer/options').status_code==404
    assert x.w.store.query('SELECT COUNT(*) FROM workflow_runs')[0][0]==0


@pytest.mark.parametrize('person',['viewer','operator','outsider'])
def test_api_readonly_or_nonmember_cannot_compile(product_world,person):
    x=product_world;before=len(x.w.calls)
    response=x.w.client.post(BASE+'/'+x.ws+'/product-composer/prepare',headers=x.w.headers[person],json={'resource_id':x.w.rid,'input':x.inputs})
    assert response.status_code==404 and response.headers['cache-control']=='no-store' and len(x.w.calls)==before


@pytest.mark.parametrize('raw',['{"resource_id":1,"input":{},"input":{}}','{"resource_id":1,"input":{"query":"a","query":"b"}}','{"resource_id":1,"input":NaN}'])
def test_api_exact_duplicate_and_nonfinite_fields_fail_without_provider(product_world,raw):
    x=product_world;before=len(x.w.calls)
    response=x.w.client.post(BASE+'/'+x.ws+'/product-composer/prepare',headers=x.w.headers['owner'],content=raw)
    assert response.status_code==400 and response.headers['cache-control']=='no-store' and len(x.w.calls)==before


def launch(x,browser,*,hold_prepare=False):
    context=browser.new_context();context.add_init_script('sessionStorage.setItem("adminToken",'+json.dumps(x.w.headers['owner']['Authorization'][7:])+');');page=context.new_page();errors=[];held=[]
    def serve(route):
        request=route.request;url=urlsplit(request.url)
        if url.hostname!='admin.test':return route.abort()
        if hold_prepare and url.path.endswith('/product-composer/prepare'):
            held.append(route);return
        response=x.w.client.request(request.method,url.path+('?'+url.query if url.query else ''),headers=request.headers,content=request.post_data)
        route.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')},body=response.content)
    context.route('**/*',serve);page.on('pageerror',lambda value:errors.append(str(value)));page.goto('https://admin.test/admin/ui#workspaces')
    expect(page.locator('#workspaceSelect')).to_be_enabled();page.locator('#workspaceSelect').select_option(x.ws)
    page.locator('#workspaceProductMount').get_by_role('button',name='Compose private product comparison').click()
    expect(page.locator('#workspaceProductDialog')).to_be_visible();expect(page.locator('#workspaceProductStatus')).to_contain_text('Choose explicit criteria')
    return context,page,errors,held


def enter(page,x):
    page.locator('#workspaceProductQuery').fill(x.inputs['query']);page.locator('#workspaceProductCriteria').fill('\n'.join(c['criterion_id']+','+c['dimension'] for c in x.inputs['criteria']))


def test_native_private_product_review_saves_tests_once_and_renders_untrusted_text(product_world,browser):
    x=product_world;context,page,errors,_=launch(x,browser);enter(page,x);before=x.w.calls.count('tools/call')
    page.locator('#workspaceProductPrepare').click();expect(page.locator('#workspaceProductPreview')).to_contain_text(x.inputs['query']);assert x.w.calls.count('tools/call')==before
    page.locator('#workspaceProductSave').click();expect(page.locator('#workspaceProductStatus')).to_contain_text('immutable composition saved')
    page.locator('#workspaceProductTestPrepare').click();expect(page.locator('#workspaceProductConsent')).not_to_be_checked();expect(page.locator('#workspaceProductRun')).to_be_disabled()
    page.locator('#workspaceProductConsent').check();page.locator('#workspaceProductRun').click();expect(page.locator('#workspaceProductResults')).to_contain_text('Product contract: passed');expect(page.locator('#workspaceProductResults')).to_contain_text('Synthetic product 0');assert x.w.calls.count('tools/call')==before+1
    expect(page.locator('#workspaceProductConsent')).not_to_be_checked();expect(page.locator('#workspaceProductRun')).to_be_disabled();assert not errors
    assert page.locator('#workspaceProductResults a,#workspaceProductResults img').count()==0
    REPORT.mkdir(parents=True,exist_ok=True);page.set_viewport_size({'width':1280,'height':1000});page.screenshot(path=str(REPORT/'product-private-review.png'));context.close()


def test_close_suppresses_late_signed_preparation_response(product_world,browser):
    x=product_world;context,page,errors,held=launch(x,browser,hold_prepare=True);enter(page,x)
    page.locator('#workspaceProductPrepare').click();page.wait_for_function('() => document.querySelector("#workspaceProductPrepare").disabled');page.locator('#workspaceProductDialog').get_by_role('button',name='Close',exact=True).click()
    assert held
    route=held.pop();request=route.request;response=x.w.client.request(request.method,urlsplit(request.url).path,headers=request.headers,content=request.post_data);route.fulfill(status=response.status_code,headers={'content-type':'application/json'},body=response.content)
    page.locator('#workspaceProductMount').get_by_role('button',name='Compose private product comparison').click();expect(page.locator('#workspaceProductSave')).to_be_disabled();expect(page.locator('#workspaceProductPreview')).to_be_empty();assert not errors;context.close()


def test_input_edit_resets_execution_consent_and_never_calls_provider(product_world,browser):
    x=product_world;context,page,errors,_=launch(x,browser);enter(page,x);page.locator('#workspaceProductPrepare').click();expect(page.locator('#workspaceProductSave')).to_be_enabled();page.locator('#workspaceProductSave').click();expect(page.locator('#workspaceProductTestPrepare')).to_be_enabled();page.locator('#workspaceProductTestPrepare').click();expect(page.locator('#workspaceProductConsent')).to_be_enabled();page.locator('#workspaceProductConsent').check();page.locator('#workspaceProductQuery').fill('Different public product objective');expect(page.locator('#workspaceProductConsent')).not_to_be_checked();expect(page.locator('#workspaceProductRun')).to_be_disabled();assert not x.w.calls and not errors;context.close()
