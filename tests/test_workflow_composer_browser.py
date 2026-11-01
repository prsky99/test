"""Real private Chromium flow, with every request routed into isolated apps."""
import pytest
from playwright.sync_api import expect
from tests.test_workflow_fallback_browser import fallback_page,browser
from tests.test_workflow_fallback_api import routing_api
from tests.test_workflow_fallback import routing

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


def enter(page):
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin');page.locator('#adminLoginPassword').fill('sadmin');page.locator('#adminLoginSubmitBtn').click()
    expect(page.locator('#adminLoginModal')).to_be_hidden()
    page.locator('[data-tab="workflows"]').click()


def preview(page):
    page.locator('#aiComposerPrompt').fill('Python documentation search');page.locator('#btnRunAiComposer').click()
    expect(page.locator('#workflowComposerDialog')).to_be_visible()
    expect(page.locator('#composerPreviewText')).to_contain_text('zero provider calls')


def test_composer_preview_preserves_builder_and_requires_each_action(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,wf,_,calls,*_=routing
    from agent_market.workspace_admin_events import migrate
    migrate(rt.store,b'isolated-composer-review-key-1234')
    enter(page);before=len(rt.store.query('SELECT id FROM agent_workflows'))
    graph=page.evaluate('JSON.stringify(canvasGraph)');preview(page)
    assert not calls and len(rt.store.query('SELECT id FROM agent_workflows'))==before
    assert page.evaluate('JSON.stringify(canvasGraph)')==graph
    for id in ['composerReview','composerLiveAuthority','composerPublishAuthority']:expect(page.locator('#'+id)).not_to_be_checked()
    page.locator('#composerSave').click();assert len(rt.store.query('SELECT id FROM agent_workflows'))==before
    page.locator('#composerReview').check();page.locator('#composerSave').click()
    expect(page.locator('#composerStatus')).to_contain_text('No provider has been called')
    assert len(rt.store.query('SELECT id FROM agent_workflows'))==before+1 and not calls
    page.locator('#composerTest').click();assert not calls
    page.locator('#composerLiveAuthority').check();page.locator('#composerTest').click()
    expect(page.locator('#composerStatus')).to_contain_text('Actual test: succeeded',timeout=10000)
    assert len(calls)==1
    page.locator('#composerPublish').click();assert not rt.store.query("SELECT id FROM agent_workflows WHERE tags LIKE '%composer_test:%'")
    page.locator('#composerPublishAuthority').check();page.once('dialog',lambda dialog:dialog.accept('Publish isolated tested fixture'));page.locator('#composerPublish').click()
    expect(page.locator('#composerStatus')).to_contain_text('Publication is awaiting approval')
    assert not rt.store.query("SELECT id FROM agent_workflows WHERE tags LIKE '%composer_test:%'")
    assert rt.store.query("SELECT id FROM admin_reviewed_commands WHERE status='pending'")
    page.screenshot(path='reports/advancement-r07-2026-10-18/composer-reviewed-publish.png')
    assert not errors and not external


def test_candidate_replacement_keeps_same_inputs_and_clears_consent(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing
    enter(page);preview(page);inputs=page.locator('#composerInputs').text_content()
    page.locator('#composerReview').check();choice=page.locator('#composerChoices select');values=choice.locator('option').evaluate_all('(options)=>options.map(o=>o.value)')
    choice.select_option(values[1]);expect(page.locator('#composerReview')).not_to_be_checked()
    expect(page.locator('#composerInputs')).to_have_text(inputs)
    assert not calls
    page.screenshot(path='reports/advancement-r07-2026-10-18/composer-preview.png')
    page.locator('#composerClose').click();expect(page.locator('#workflowComposerDialog')).to_be_hidden()
    assert page.evaluate('composerPreview===null') and not errors and not external


def test_logout_clears_preview_without_private_browser_storage(fallback_page):
    page,routing,errors,external,_=fallback_page
    enter(page);preview(page);page.locator('#composerClose').click();page.on('dialog',lambda dialog:dialog.accept());page.locator('#logoutBtn').click()
    expect(page.locator('#adminLoginModal')).to_be_visible()
    assert page.evaluate('composerPreview===null')
    assert not page.evaluate('Object.keys(sessionStorage).some(k=>k.toLowerCase().includes("composer"))')
    assert not errors and not external
