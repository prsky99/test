"""Actual Chromium operations controls with external network disabled."""
import copy
from playwright.sync_api import expect

from tests.test_front_workflow_browser import browser
from tests.test_workflow_fallback import routing
from tests.test_workflow_fallback_api import routing_api
from tests.test_workflow_fallback_browser import fallback_page
from tests.test_execution_authority import inbox
from tests.test_workflow_operations_hardening import unknown_delivery

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def login(page):
    page.goto('https://admin.test/admin/ui');page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    expect(page.locator('#adminLoginModal')).to_be_hidden();page.locator('[data-tab="errors"]').click()


def test_multi_pair_editor_preserves_all_rows_and_grant_reapproval_context(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,wf,ids,*_=routing
    nodes=copy.deepcopy(wf['nodes']);nodes.append({**copy.deepcopy(nodes[0]),'id':'second','name':'Second Search'})
    rt.store.update_workflow(wf['id'],{'nodes':nodes});wf=rt.store.get_workflow(wf['id']);inbox(rt,wf)
    login(page);page.locator('#fallbackControlsPanel summary').click()
    page.locator('#fallbackWorkflowId').fill(str(wf['id']));page.locator('#fallbackPolicyReload').click();expect(page.locator('#fallbackNode option')).to_have_count(2)
    page.locator('#fallbackMode').select_option('shadow');page.locator('#fallbackResourceId').fill(str(ids[1]));page.locator('#fallbackContract').select_option('docs.search.v1')
    page.locator('#fallbackPairAdd').click();rows=page.locator('#fallbackPairs > div');expect(rows).to_have_count(2)
    rows.nth(1).locator('[data-field="resource"]').fill(str(ids[2]));rows.nth(1).locator('[data-field="contract"]').select_option('docs.search.v1')
    page.locator('#fallbackPolicyAuthority').check();page.locator('#fallbackPolicySave').click();expect(page.locator('#fallbackPolicyStatus')).to_contain_text('revision 1')
    assert len(rt.fallback.policy(wf['id'])[0]['pairs'])==2
    page.locator('#fallbackPolicyReload').click();expect(rows).to_have_count(2)
    page.locator('#fallbackPolicyAuthority').check();page.locator('#fallbackPolicySave').click();expect(page.locator('#fallbackPolicyStatus')).to_contain_text('revision 2')
    # Reissue a grant and change policy once more to exercise the explicit banner.
    rt.save_schedule(wf['id'],{'mode':'manual','enabled':False,'destination_id':rt.schedule(wf['id'])['destination_id'],'delivery_authority':True,'delivery_notice':'workflow-result-grant-v1','delivery_sources':['admin']})
    page.evaluate("() => {activeWorkflow={id:999,name:'Unsaved'};canvasGraph={nodes:[{id:'unsaved'}],edges:[]};}")
    page.locator('#fallbackPolicyAuthority').check();page.locator('#fallbackPolicySave').click();expect(page.locator('#fallbackGrantWarning')).to_be_visible()
    page.locator('#fallbackGrantReview').click();expect(page.locator('#workflowScheduleModal')).to_be_visible()
    expect(page.locator('#wfDeliveryAuthority')).not_to_be_checked();expect(page.locator('#wfDeliveryAdmin')).not_to_be_checked()
    assert page.evaluate('activeWorkflow.id')==999 and page.evaluate('canvasGraph.nodes[0].id')=='unsaved'
    page.screenshot(path='reports/operations-hardening-2026-10-18/multi-node-grant-review.png')
    assert not errors and not external


def test_unknown_review_and_new_manual_delivery_require_separate_actions(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,wf,*_=routing
    job,event,dest,courier=unknown_delivery(rt,wf);count=len(courier.sent)
    login(page);page.locator('#workflowRecoveryReference').fill(job['run_id']);page.locator('#workflowRecoveryInspect').click()
    dialog=page.locator('#observationDialog');expect(dialog).to_be_visible()
    expect(page.locator('#recoveryReviewAuthority')).not_to_be_checked();expect(page.locator('#recoveryResendAuthority')).not_to_be_checked();expect(page.locator('#recoveryResendRisk')).not_to_be_checked()
    page.locator('#recoveryReviewSubject').select_option(event);page.locator('#recoveryDisposition').select_option('not_received');page.locator('#recoveryEvidenceRef').fill('ticket-1234')
    page.locator('#recoveryReviewAuthority').check();page.locator('#recoveryReviewSave').click()
    expect(page.locator('#observationDetail')).to_contain_text('ticket-1234')
    assert len(courier.sent)==count
    page.locator('#recoveryReviewSubject').select_option(event);page.locator('#recoveryInboxLoad').click();expect(page.locator('#recoveryResendDestination option')).to_have_count(1)
    page.locator('#recoveryResendAuthority').check();page.locator('#recoveryResendRisk').check();page.locator('#recoveryResend').click()
    expect(page.locator('#observationDetail')).to_contain_text('pending')
    assert len(courier.sent)==count
    rt.operations.drain();assert len(courier.sent)==count+1
    page.keyboard.press('Escape');page.locator('#workflowRecoveryInspect').click();expect(page.locator('#observationDetail')).to_contain_text('accepted')
    page.evaluate('() => loadErrors()');expect(dialog).to_be_visible()
    assert page.locator('#observationDetail img').count()==0
    page.screenshot(path='reports/operations-hardening-2026-10-18/reconciliation-manual-delivery.png')
    page.keyboard.press('Escape');expect(dialog).to_be_hidden()
    assert not errors and not external


def test_retention_preview_never_applies_without_explicit_authority(fallback_page):
    page,_,errors,external,_=fallback_page;login(page);page.locator('#workflowMaintenancePanel summary').click()
    expect(page.locator('#workflowRetentionAuthority')).not_to_be_checked();page.locator('#workflowRetentionPreview').click()
    expect(page.locator('#workflowRetentionStatus')).to_contain_text('미리보기')
    page.locator('#workflowRetentionApply').click();expect(page.locator('#workflowRetentionStatus')).to_contain_text('미리보기')
    page.locator('#workflowRetentionAuthority').check();page.locator('#workflowRetentionApply').click()
    expect(page.locator('#workflowRetentionStatus')).to_contain_text('적용 결과');expect(page.locator('#workflowRetentionAuthority')).not_to_be_checked()
    assert not errors and not external
