"""Private recovery detail stays centered, escaped and stable in Chromium."""
from playwright.sync_api import expect
from tests.test_operational_observability_browser import trace_page
from tests.test_front_workflow_browser import browser
from tests.test_workflow_runtime import save,wait
from agent_market.workflows import runtime_for


def test_recovery_detail_is_private_centered_escaped_and_refresh_stable(trace_page):
    page,store,_,errors,external=trace_page;rt=runtime_for(store)
    wf=save(store,[{'id':'a','type':'trigger','name':'Start','data':{}}]);job=rt.submit(wf);wait(rt,job)
    with store.tx() as db:db.execute("INSERT INTO workflow_execution_attempts VALUES (?,?,1,'fixture','unknown',0,0,0)",(job['run_id'],'<img src=x onerror=alert(1)>'))
    page.locator('[data-tab="errors"]').click()
    page.locator('#workflowRecoveryReference').fill(job['run_id']);page.locator('#workflowRecoveryInspect').click()
    dialog=page.locator('#observationDialog');expect(dialog).to_be_visible()
    expect(page.locator('#observationDetail')).to_contain_text('unknown')
    assert page.locator('#observationDetail img').count()==0
    box=dialog.bounding_box();viewport=page.viewport_size
    assert abs(box['x']+box['width']/2-viewport['width']/2)<5 and abs(box['y']+box['height']/2-viewport['height']/2)<5
    page.evaluate('() => loadErrors()');expect(dialog).to_be_visible()
    page.screenshot(path='reports/advancement-r05-2026-10-18/admin-workflow-recovery.png')
    page.keyboard.press('Escape');expect(dialog).to_be_hidden()
    assert not errors and not external
