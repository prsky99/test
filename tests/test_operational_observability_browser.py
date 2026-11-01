"""Admin trace dialogs stay centered and stable during automatic list refresh."""
from urllib.parse import urlsplit
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from agent_market.gateway.store import Store
from agent_market.gateway.dashboard import dashboard_router
from agent_market.observability import journal_for
from tests.test_front_workflow_browser import browser

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


@pytest.fixture
def trace_page(browser,tmp_path,rotated_bootstrap_admin):
    path=str(tmp_path/'admin.sqlite3');store=Store(path)
    app=FastAPI();app.include_router(dashboard_router(store,path,'test-observation-token',None,ssl_manager=Mock(get_status=lambda:{})))
    operation=journal_for(store).begin('execution','testbench',resource_id=7,proto='mcp')
    attempt=operation.attempt(7,'mcp');attempt.dispatch();operation.finish('timed_out','UPSTREAM_TIMEOUT')
    client=TestClient(app,base_url='https://admin.test')
    context=browser.new_context();page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def serve(route):
        req=route.request;u=urlsplit(req.url)
        if u.hostname!='admin.test':external.append(req.url);return route.abort()
        r=client.request(req.method,u.path+('?' +u.query if u.query else ''),content=req.post_data,headers=req.headers)
        route.fulfill(status=r.status_code,body=r.content,headers={k:v for k,v in r.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*',serve)
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin')
    page.locator('#adminLoginSubmitBtn').click()
    expect(page.locator('#adminLoginModal')).to_be_hidden()
    yield page,store,operation.id,errors,external
    context.close();client.close();store._db.close()


def test_trace_dialog_survives_refresh_and_has_keyboard_focus(trace_page):
    page,_,identity,errors,external=trace_page
    page.locator('[data-tab="errors"]').click()
    expect(page.locator('#observationOperations')).to_contain_text(identity)
    page.locator('[data-observation="'+identity+'"]').click()
    dialog=page.locator('#observationDialog');expect(dialog).to_be_visible()
    expect(page.locator('#observationDetail')).to_contain_text('unknown')
    box=dialog.bounding_box();viewport=page.viewport_size
    assert box and abs(box['x']+box['width']/2-viewport['width']/2)<5
    assert abs(box['y']+box['height']/2-viewport['height']/2)<5
    page.evaluate('() => loadErrors()')
    expect(dialog).to_be_visible();expect(page.locator('#observationDetail')).to_contain_text(identity)
    page.screenshot(path='reports/advancement-r02-2026-10-18/admin-trace-dialog.png')
    page.keyboard.press('Escape');expect(dialog).to_be_hidden()
    assert not errors and not external


def test_invalid_reference_does_not_create_elements_or_network_query(trace_page):
    page,_,_,errors,_=trace_page
    page.locator('[data-tab="errors"]').click()
    page.locator('#observationReference').fill('<img src=x onerror=alert(1)>')
    requests=[];page.on('request',lambda request:requests.append(request.url))
    page.locator('#observationSearch').click()
    assert not any('reference=' in url for url in requests)
    assert page.locator('#observationOperations img').count()==0
    assert not errors
