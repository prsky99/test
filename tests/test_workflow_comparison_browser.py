"""Private comparison UI cannot start new tests or execute provider text."""
from tests.browser_wait import pending_request
import json
from playwright.sync_api import expect
from tests.test_workflow_fallback_browser import fallback_page,browser
from tests.test_workflow_fallback_api import routing_api
from tests.test_workflow_fallback import routing
from tests.test_workflow_composer_browser import enter
from tests.test_workflow_comparison import paired
from agent_market.workflow_comparison import Comparison


def select_pair(page,body):
    page.locator('#workflowCompareOpen').click()
    expect(page.locator('#workflowComparisonDialog')).to_be_visible()
    expect(page.locator('#workflowCompareLeft option')).to_have_count(2)
    page.locator('#workflowCompareLeft').select_option(body['left_run_id']+':'+body['contract'])
    expect(page.locator('#workflowCompareRight option')).to_have_count(1)
    page.locator('#workflowCompareRight').select_option(body['right_run_id']+':'+body['contract'])


def test_completed_pair_renders_metrics_without_runs_or_builder_changes(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing;_,_,body=paired(routing)
    enter(page);before=page.evaluate('JSON.stringify(canvasGraph)');count=len(calls);runs=len(rt.store.query('SELECT * FROM workflow_runs'))
    select_pair(page,body);page.locator('#workflowCompareLoad').click()
    expect(page.locator('#workflowCompareStatus')).to_contain_text('Recorded comparison ready')
    expect(page.locator('#workflowCompareResult')).to_contain_text('contract_passed')
    expect(page.locator('#workflowCompareResult')).to_contain_text('Factual accuracy is not assessed')
    assert len(calls)==count and len(rt.store.query('SELECT * FROM workflow_runs'))==runs
    assert page.evaluate('JSON.stringify(canvasGraph)')==before
    page.evaluate('() => loadWorkflows()')
    expect(page.locator('#workflowComparisonDialog')).to_be_visible()
    expect(page.locator('#workflowCompareStatus')).to_contain_text('Recorded comparison ready')
    page.screenshot(path='reports/advancement-r07-comparison-2026-10-18/completed-comparison.png')
    assert not errors and not external


def test_provider_titles_render_as_text_without_network_or_script(fallback_page,monkeypatch):
    from tests.test_workflow_fallback import output
    def injected():
        value=output();value['structuredContent']['items'][0]['title']='<img src="https://evil.example/tracker" onerror="window.comparisonInjected=true">'
        return value
    monkeypatch.setattr('tests.test_workflow_fallback.output',injected)
    page,routing,errors,external,_=fallback_page;paired_result=paired(routing);body=paired_result[2]
    enter(page);select_pair(page,body);page.locator('#workflowCompareLoad').click()
    expect(page.locator('#workflowCompareStatus')).to_contain_text('Recorded comparison ready')
    expect(page.locator('#workflowCompareResult')).to_contain_text('<img')
    assert page.locator('#workflowCompareResult img').count()==0 and page.evaluate('window.comparisonInjected===undefined')
    assert not errors and not external


def test_closed_dialog_ignores_late_comparison_response(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,*_=routing;_,_,body=paired(routing)
    enter(page);select_pair(page,body);pending=[]
    page.route('**/admin/api/workflow-composer/comparison',lambda route:pending.append(route))
    page.locator('#workflowCompareLoad').click()
    expect(page.locator('#workflowCompareStatus')).to_contain_text('Checking retained signed evidence')
    page.locator('#workflowCompareClose').click();expect(page.locator('#workflowComparisonDialog')).to_be_hidden()
    pending_request(page,pending)
    pending[0].fulfill(status=200,content_type='application/json',body=json.dumps(Comparison(rt).compare(body)))
    page.wait_for_timeout(100)
    assert page.locator('#workflowCompareResult').text_content()=='' and page.evaluate('workflowComparisonRows.length===0')
    assert not errors and not external


def test_authentication_expiry_clears_comparison_private_state(fallback_page):
    page,routing,errors,external,_=fallback_page;_,_,body=paired(routing)
    enter(page);select_pair(page,body)
    page.route('**/admin/api/workflow-composer/comparison',lambda route:route.fulfill(status=401,content_type='application/json',body='{"detail":"Session expired."}'))
    page.locator('#workflowCompareLoad').click()
    expect(page.locator('#workflowComparisonDialog')).to_be_hidden();expect(page.locator('#adminLoginModal')).to_be_visible()
    assert page.evaluate('workflowComparisonRows.length===0') and page.locator('#workflowCompareResult').text_content()==''
    assert not page.evaluate('Object.keys(sessionStorage).some(k=>k.toLowerCase().includes("comparison"))')
    assert not errors and not external
