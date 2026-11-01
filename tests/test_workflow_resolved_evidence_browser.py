"""Private typed evidence uses text rendering and cannot dispatch another test."""
from tests.browser_wait import pending_request
import json

import pytest
from playwright.sync_api import expect

from agent_market.workflow_resolved_evidence import ResolvedEvidence
from tests.test_workflow_composer_browser import enter
from tests.test_workflow_fallback import routing, output
from tests.test_workflow_fallback_api import routing_api as base_routing_api
from tests.test_workflow_fallback_browser import browser, fallback_page
from tests.test_workflow_resolved_evidence import completed
from tests.test_workflow_typed_flow import typed_routing


@pytest.fixture
def routing_api(typed_routing):
    yield from base_routing_api.__wrapped__(typed_routing)


def select_test(page,body):
    page.locator('#workflowResolvedOpen').click()
    expect(page.locator('#workflowResolvedDialog')).to_be_visible()
    expect(page.locator('#workflowResolvedRun option')).to_have_count(1)
    page.locator('#workflowResolvedRun').select_option(body['run_id'])


def test_single_run_inspection_displays_actual_query_without_execution_or_builder_changes(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing;_,body=completed(routing)
    enter(page);count=len(calls);runs=len(rt.store.query('SELECT id FROM workflow_runs'));builder=page.evaluate('JSON.stringify(canvasGraph)')
    select_test(page,body);page.locator('#workflowResolvedLoad').click()
    expect(page.locator('#workflowResolvedStatus')).to_contain_text('Recorded input inspection ready')
    expect(page.locator('#workflowResolvedResult')).to_contain_text('Python asynchronous task documentation')
    expect(page.locator('#workflowResolvedResult')).to_contain_text('Provenance: verified')
    expect(page.locator('#workflowResolvedResult')).to_contain_text('excluded from paired comparison and publication')
    assert len(calls)==count and len(rt.store.query('SELECT id FROM workflow_runs'))==runs
    assert page.evaluate('JSON.stringify(canvasGraph)')==builder
    page.evaluate('() => loadWorkflows()');expect(page.locator('#workflowResolvedDialog')).to_be_visible()
    expect(page.locator('#workflowResolvedStatus')).to_contain_text('Recorded input inspection ready')
    page.screenshot(path='reports/advancement-r07-resolved-evidence-2026-10-18/resolved-input-inspection.png')
    assert not errors and not external


def test_retained_provider_text_is_not_markup_and_causes_no_external_requests(fallback_page,monkeypatch):
    def injected(contract):
        result=output(contract)
        if contract=='docs.search.v1':result['structuredContent']['items'][0]['title']='<img src="https://evil.example/tracker" onerror="window.resolvedInjected=true">'
        return result
    monkeypatch.setattr('tests.test_workflow_typed_flow.output',injected)
    page,routing,errors,external,_=fallback_page;_,body=completed(routing)
    enter(page);select_test(page,body);page.locator('#workflowResolvedLoad').click()
    expect(page.locator('#workflowResolvedStatus')).to_contain_text('Recorded input inspection ready')
    expect(page.locator('#workflowResolvedResult')).to_contain_text('<img')
    assert page.locator('#workflowResolvedResult img').count()==0 and page.evaluate('window.resolvedInjected===undefined')
    assert not errors and not external


def test_closed_inspection_ignores_late_response_and_clears_private_memory(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,*_=routing;_,body=completed(routing)
    enter(page);select_test(page,body);pending=[]
    page.route('**/admin/api/workflow-composer/resolved-input',lambda route:pending.append(route))
    page.locator('#workflowResolvedLoad').click()
    expect(page.locator('#workflowResolvedStatus')).to_contain_text('Checking retained signed input')
    page.locator('#workflowResolvedClose').click();expect(page.locator('#workflowResolvedDialog')).to_be_hidden()
    pending_request(page,pending)
    pending[0].fulfill(status=200,content_type='application/json',body=json.dumps(ResolvedEvidence(rt).inspect(body)))
    page.wait_for_timeout(100)
    assert page.locator('#workflowResolvedResult').text_content()=='' and page.evaluate('workflowResolvedRows.length===0')
    assert not errors and not external


def test_expired_session_and_logout_clear_inspection_inventory_and_query(fallback_page):
    page,routing,errors,external,_=fallback_page;_,body=completed(routing)
    enter(page);select_test(page,body)
    page.route('**/admin/api/workflow-composer/resolved-input',lambda route:route.fulfill(status=401,content_type='application/json',body='{"detail":"Session expired."}'))
    page.locator('#workflowResolvedLoad').click()
    expect(page.locator('#workflowResolvedDialog')).to_be_hidden();expect(page.locator('#adminLoginModal')).to_be_visible()
    assert page.evaluate('workflowResolvedRows.length===0') and page.locator('#workflowResolvedResult').text_content()==''
    assert not page.evaluate('Object.keys(sessionStorage).concat(Object.keys(localStorage)).some(key=>key.toLowerCase().includes("resolved"))')
    assert not errors and not external


def test_selection_refresh_and_escape_clear_results_without_submitting_workflow(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing;_,body=completed(routing)
    enter(page);select_test(page,body);page.locator('#workflowResolvedLoad').click()
    expect(page.locator('#workflowResolvedStatus')).to_contain_text('Recorded input inspection ready');count=len(calls)
    page.locator('#workflowResolvedRun').dispatch_event('change')
    assert page.locator('#workflowResolvedResult').text_content()==''
    page.locator('#workflowResolvedRefresh').click()
    expect(page.locator('#workflowResolvedStatus')).to_contain_text('Choose one retained test')
    assert page.locator('#workflowResolvedResult').text_content()==''
    page.keyboard.press('Escape');expect(page.locator('#workflowResolvedDialog')).to_be_hidden()
    assert page.evaluate('workflowResolvedRows.length===0') and len(calls)==count
    assert not errors and not external
