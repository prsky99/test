"""Administrator control edits and explicit delivery consent in a real browser."""
from playwright.sync_api import expect

from agent_market.execution_authority import controls
from tests.test_execution_authority import inbox
from tests.test_operational_observability_browser import trace_page
from tests.test_front_workflow_browser import browser
from tests.test_workflow_runtime import save,node


def test_runtime_controls_keep_unsaved_edits_and_apply_resume(trace_page):
    page,store,_,errors,external=trace_page
    page.locator('[data-tab="errors"]').click()
    page.locator('#executionControlsPanel summary').click()
    expect(page.locator('#controlStatus')).to_contain_text('revision 0')
    page.locator('#controlInvoke').uncheck()
    page.evaluate('() => loadErrors()')
    expect(page.locator('#controlInvoke')).not_to_be_checked()
    page.locator('#controlSave').click()
    expect(page.locator('#controlStatus')).to_contain_text('revision 1')
    assert not controls(store)['invoke_enabled']
    page.screenshot(path='reports/advancement-r04-2026-10-18/admin-runtime-controls.png')
    page.locator('#controlInvoke').check();page.locator('#controlSave').click()
    expect(page.locator('#controlStatus')).to_contain_text('revision 2')
    assert controls(store)['invoke_enabled']
    assert not errors and not external


def test_delivery_permission_is_unchecked_scoped_and_revocable_in_modal(trace_page):
    from agent_market.workflows import runtime_for
    page,store,_,errors,external=trace_page
    wf=save(store,[node(resource_id=123,action='get_weather',input={'city':'Tokyo'})])
    rt=runtime_for(store);_,destination=inbox(rt,wf,authorize=False)
    page.evaluate('wf => { activeWorkflow=wf; return openWorkflowScheduleModal(); }',wf)
    modal=page.locator('#workflowScheduleModal');expect(modal).to_be_visible()
    expect(page.locator('#wfDeliveryAuthority')).not_to_be_checked()
    expect(page.locator('#wfDeliveryAdmin')).not_to_be_checked()
    page.locator('#wfScheduleDestination').select_option(destination)
    page.locator('#wfDeliveryAuthority').check();page.locator('#wfDeliveryAdmin').check()
    page.locator('#btnSaveWorkflowSchedule').click()
    expect(page.locator('#wfDeliveryGrants')).to_contain_text('admin')
    expect(page.locator('#wfDeliveryAuthority')).not_to_be_checked()
    assert len(rt.authority.grants(wf['id']))==1
    page.screenshot(path='reports/advancement-r04-2026-10-18/admin-delivery-grant.png')
    page.locator('[data-revoke-workflow-grant]').click()
    expect(page.locator('#wfDeliveryGrants')).to_contain_text('철회됨')
    assert rt.authority.grants(wf['id'])[0]['revoked']
    assert not errors and not external
