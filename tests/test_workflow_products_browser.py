"""Real Chromium product inputs, consent, execution and standalone export UI."""
# ruff: noqa: F401,F811
from io import BytesIO
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from agent_market.concierge.front import Front,create_front_app
from tests.test_front_workflow_browser import browser
from tests.test_workflow_products import routing,published
from tests.workflow_package_helpers import open_hosted_package


@pytest.fixture
def product_page(browser,routing):
    rt,wf,ids=published(routing)
    proxy=rt.proxy;front=Front(rt.store,allow_private=True);front.proxy=front.workflows.proxy=proxy
    client=TestClient(create_front_app(front),base_url='https://agentconcierge.biz')
    context=browser.new_context();page=context.new_page();errors=[];bodies=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def serve(route):
        req=route.request;url=urlsplit(req.url)
        if url.hostname!='agentconcierge.biz':return route.abort()
        if url.path=='/api/workflows/run':bodies.append(req.post_data_json)
        response=client.request(req.method,url.path+('?'+url.query if url.query else ''),content=req.post_data,headers=req.headers)
        route.fulfill(status=response.status_code,body=response.content,headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    yield page,client,wf,errors,bodies
    context.close();client.close()


def test_hub_inputs_capture_then_clear_consent(product_page):
    page,client,wf,errors,bodies=product_page
    page.goto('https://agentconcierge.biz/#workflows')
    page.evaluate('async id=>{await loadFrontTemplates(true);loadFrontTemplateToCanvas(id);}',wf['id'])
    field=page.locator('[data-product-input="query"]');expect(field).to_be_visible()
    field.fill('ocean monitoring');page.locator('#frontFallbackConsent').check()
    page.locator('#btnFrontRunWorkflow').click()
    expect(page.locator('#btnFrontRunWorkflow')).to_be_enabled(timeout=15000)
    assert bodies[-1]['input']=={'query':'ocean monitoring'} and bodies[-1]['allow_fallback'] is True
    expect(page.locator('#frontFallbackConsent')).not_to_be_checked()
    assert not errors


def test_downloaded_product_renders_records_with_safe_text(product_page):
    page,client,wf,errors,bodies=product_page
    package=client.get(f"/api/workflows/{wf['id']}/webapp")
    open_hosted_package(page,BytesIO(package.content))
    page.locator('[data-input]').fill('solar energy')
    page.locator('button[type=submit]').click()
    assert not bodies
    page.locator('#consent').check();page.locator('button[type=submit]').click()
    expect(page.locator('[role=status]')).to_contain_text('Complete.',timeout=15000)
    expect(page.locator('#results article')).to_have_count(1)
    expect(page.locator('#consent')).not_to_be_checked()
    assert bodies[-1]['input']['query']=='solar energy'
    assert page.locator('#results a').get_attribute('rel')=='noopener noreferrer'
    assert not errors
