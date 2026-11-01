"""Private typed-connection consent in Chromium; all requests use isolated apps."""
import pytest
from playwright.sync_api import expect

from tests.test_workflow_composer_browser import enter
from tests.test_workflow_fallback import routing
from tests.test_workflow_fallback_api import routing_api as base_routing_api
from tests.test_workflow_fallback_browser import browser, fallback_page
from tests.test_workflow_typed_flow import typed_routing


@pytest.fixture
def routing_api(typed_routing):
    yield from base_routing_api.__wrapped__(typed_routing)


def preview_connection(page):
    page.locator('#composerFlow').select_option('news-title-to-docs-v1')
    page.locator('#aiComposerPrompt').fill('Latest Python news and documentation search')
    page.locator('#btnRunAiComposer').click()
    expect(page.locator('#workflowComposerDialog')).to_be_visible()
    expect(page.locator('#composerPreviewText')).to_contain_text('zero provider calls')
    expect(page.locator('#composerFlowInfo')).to_contain_text('first news result title')


def capture_posts(page):
    posts=[]
    page.on('request', lambda req: posts.append((req.url,req.post_data_json))
            if req.method=='POST' and '/admin/api/' in req.url else None)
    return posts


def test_connected_draft_requires_sharing_and_live_authorization_and_stays_private(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing
    enter(page);posts=capture_posts(page);before=len(rt.store.query('SELECT id FROM agent_workflows'))
    graph=page.evaluate('JSON.stringify(canvasGraph)');preview_connection(page)
    assert posts[-1][1]['flow']=='news-title-to-docs-v1'
    assert not calls and len(rt.store.query('SELECT id FROM agent_workflows'))==before
    assert page.evaluate('JSON.stringify(canvasGraph)')==graph
    expect(page.locator('#composerFlowAuthority')).not_to_be_checked()
    expect(page.locator('#composerPublishAuthority')).to_be_disabled()
    page.locator('#composerReview').check();page.locator('#composerSave').click()
    assert not any(url.endswith('/workflow-composer/save') for url,_ in posts)
    assert len(rt.store.query('SELECT id FROM agent_workflows'))==before
    page.locator('#composerFlowAuthority').check();page.locator('#composerSave').click()
    expect(page.locator('#composerStatus')).to_contain_text('Private connected draft saved')
    saved=next(body for url,body in posts if url.endswith('/workflow-composer/save'))
    assert saved['flow_authority'] is True and saved['flow_notice']=='workflow-composer-flow-v1'
    expect(page.locator('#composerFlowAuthority')).not_to_be_checked()
    assert not calls
    page.locator('#composerTest').click();assert not calls
    page.locator('#composerLiveAuthority').check();page.locator('#composerTest').click()
    expect(page.locator('#composerStatus')).to_contain_text('Actual test: succeeded',timeout=15000)
    wid=page.evaluate('composerSavedId');workflow=rt.store.get_workflow(wid)
    expected=[rt.store.resource(node['resource_id'])['url'].split('/')[2] for node in workflow['nodes'] if node['type']=='agent']
    assert calls==expected
    expect(page.locator('#composerPublish')).to_be_disabled()
    expect(page.locator('#composerPublishAuthority')).to_be_disabled()
    expect(page.locator('#composerPreviewText')).to_contain_text('remains private')
    page.screenshot(path='reports/advancement-r07-typed-flow-2026-10-18/connected-private-draft.png')
    page.evaluate('publishComposerDraft()')
    assert not any(url.endswith('/workflow-composer/publish') for url,_ in posts)
    assert not workflow['is_template']
    expect(page.locator('#composerLiveAuthority')).not_to_be_checked()
    assert not errors and not external


def test_connected_candidate_replacement_resets_sharing_and_fixed_inputs(fallback_page):
    page,routing,errors,external,_=fallback_page;_,_,_,calls,*_=routing
    enter(page);preview_connection(page)
    inputs=page.locator('#composerInputs').text_content()
    page.locator('#composerReview').check();page.locator('#composerFlowAuthority').check()
    choice=page.locator('#composerChoices select[data-contract="docs.search.v1"]')
    values=choice.locator('option').evaluate_all('(options)=>options.map(option=>option.value)')
    assert len(values)>=2
    choice.select_option(values[1])
    expect(page.locator('#composerFlowAuthority')).not_to_be_checked()
    expect(page.locator('#composerReview')).not_to_be_checked()
    expect(page.locator('#composerInputs')).to_have_text(inputs)
    expect(page.locator('#composerPublishAuthority')).to_be_disabled()
    assert not calls and not errors and not external


def test_invalid_news_output_stops_before_documentation_dispatch(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,modes,*_=routing
    enter(page);preview_connection(page)
    page.locator('#composerReview').check();page.locator('#composerFlowAuthority').check();page.locator('#composerSave').click()
    expect(page.locator('#composerStatus')).to_contain_text('Private connected draft saved')
    modes['primary.example']='invalid'
    page.locator('#composerLiveAuthority').check();page.locator('#composerTest').click()
    expect(page.locator('#composerStatus')).to_contain_text('Actual test: failed',timeout=15000)
    assert calls==['primary.example']
    expect(page.locator('#composerPublish')).to_be_disabled()
    assert page.evaluate('composerRunId===null')
    assert not rt.store.get_workflow(page.evaluate('composerSavedId'))['is_template']
    assert not errors and not external


def test_connected_consent_is_cleared_on_close_and_not_stored(fallback_page):
    page,routing,errors,external,_=fallback_page
    enter(page);preview_connection(page);page.locator('#composerFlowAuthority').check()
    page.locator('#composerClose').click()
    expect(page.locator('#workflowComposerDialog')).to_be_hidden()
    expect(page.locator('#composerFlowAuthority')).not_to_be_checked()
    expect(page.locator('#composerFlowAuthority')).to_be_disabled()
    expect(page.locator('#composerFlow')).to_have_value('independent')
    assert page.evaluate('composerPreview===null')
    assert not page.evaluate('Object.keys(sessionStorage).concat(Object.keys(localStorage)).some(key=>key.toLowerCase().includes("composer"))')
    page.locator('#aiComposerPrompt').fill('Python documentation search');page.locator('#btnRunAiComposer').click()
    expect(page.locator('#workflowComposerDialog')).to_be_visible()
    expect(page.locator('#composerFlowConsent')).to_be_hidden()
    expect(page.locator('#composerFlowInfo')).to_be_hidden()
    expect(page.locator('#composerPublishAuthority')).to_be_enabled()
    assert not errors and not external
