"""Local review downloads require preview acknowledgment and cannot run agents."""
from tests.browser_wait import pending_request
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

from agent_market.workflow_review_packets import ReviewPackets
from agent_market.workflow_resolved_evidence import ResolvedEvidence
from tests.test_workflow_composer_browser import enter
from tests.test_workflow_fallback import routing, output
from tests.test_workflow_fallback_api import routing_api as base_routing_api
from tests.test_workflow_fallback_browser import browser, fallback_page
from tests.test_workflow_resolved_evidence import completed
from tests.test_workflow_resolved_evidence_browser import select_test
from tests.test_workflow_typed_flow import typed_routing


@pytest.fixture
def routing_api(typed_routing):
    yield from base_routing_api.__wrapped__(typed_routing)


def prepare(page):
    page.locator('#workflowReviewPrepare').click()
    expect(page.locator('#workflowReviewStatus')).to_contain_text('Review worksheet ready')


def test_explicit_preview_acknowledgment_downloads_exact_packet_bytes_without_new_calls(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing;_,body=completed(routing)
    expected=ReviewPackets(rt).prepare(body);enter(page);posts=[];downloads=[]
    page.on('request',lambda req:posts.append((req.url,req.post_data_json)) if req.method=='POST' and '/admin/api/' in req.url else None)
    page.on('download',lambda item:downloads.append(item))
    page.evaluate('''() => {
      window.reviewUrlsCreated=[]; window.reviewUrlsRevoked=[];
      const create=URL.createObjectURL.bind(URL); const revoke=URL.revokeObjectURL.bind(URL);
      URL.createObjectURL=blob=>{const url=create(blob);window.reviewUrlsCreated.push(url);return url;};
      URL.revokeObjectURL=url=>{window.reviewUrlsRevoked.push(url);revoke(url);};
    }''')
    builder=page.evaluate('JSON.stringify(canvasGraph)');count=len(calls);runs=len(rt.store.query('SELECT id FROM workflow_runs'))
    select_test(page,body)
    assert not any(url.endswith('/review-packet') for url,_ in posts) and not downloads
    expect(page.locator('#workflowReviewAck')).to_be_disabled()
    prepare(page)
    sent=[data for url,data in posts if url.endswith('/review-packet')];assert sent==[body]
    preview=page.locator('#workflowReviewPreview').text_content()
    assert json.loads(preview)==expected['packet']
    expect(page.locator('#workflowReviewAck')).not_to_be_checked()
    expect(page.locator('#workflowReviewDownload')).to_be_disabled()
    page.evaluate('downloadReviewWorksheet()')
    assert not downloads and page.evaluate('reviewUrlsCreated.length')==0
    page.locator('#workflowReviewAck').check()
    with page.expect_download() as download:
        page.locator('#workflowReviewDownload').click()
    item=download.value
    assert item.suggested_filename==expected['download_filename']
    assert Path(item.path()).read_bytes()==preview.encode('utf-8')
    assert json.loads(Path(item.path()).read_text())==expected['packet']
    expect(page.locator('#workflowReviewAck')).not_to_be_checked()
    expect(page.locator('#workflowReviewDownload')).to_be_disabled()
    expect(page.locator('#workflowReviewStatus')).to_contain_text('No review was submitted')
    page.wait_for_function('reviewUrlsCreated.length===1 && reviewUrlsRevoked.includes(reviewUrlsCreated[0])')
    assert len(calls)==count and len(rt.store.query('SELECT id FROM workflow_runs'))==runs
    assert page.evaluate('JSON.stringify(canvasGraph)')==builder
    assert not any('/run' in url or '/publish' in url for url,_ in posts)
    page.set_viewport_size({'width':1280,'height':1100})
    page.screenshot(path='reports/advancement-r07-review-preparation-2026-10-18/review-worksheet.png')
    page.locator('#workflowResolvedClose').click()
    assert page.evaluate('workflowReviewPacket===null && workflowReviewJson==="" && workflowReviewObjectUrl===""')
    assert not errors and not external


def test_provider_metadata_renders_only_as_text_and_never_loads_external_content(fallback_page,monkeypatch):
    def injected(contract):
        value=output(contract)
        if contract=='docs.search.v1':value['structuredContent']['items'][0]['title']='<img src="https://evil.example/tracker" onerror="window.reviewInjected=true">'
        return value
    monkeypatch.setattr('tests.test_workflow_typed_flow.output',injected)
    page,routing,errors,external,_=fallback_page;_,body=completed(routing)
    enter(page);select_test(page,body);prepare(page)
    expect(page.locator('#workflowReviewPreview')).to_contain_text('<img')
    assert page.locator('#workflowReviewPreview img').count()==0 and page.evaluate('window.reviewInjected===undefined')
    assert not errors and not external


@pytest.mark.parametrize('action',['close','selection','refresh','escape'])
def test_review_context_and_ack_are_cleared_when_selection_or_dialog_changes(fallback_page,action):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing;_,body=completed(routing)
    enter(page);select_test(page,body);prepare(page);count=len(calls)
    page.locator('#workflowReviewAck').check()
    if action=='close':page.locator('#workflowResolvedClose').click()
    elif action=='selection':page.locator('#workflowResolvedRun').dispatch_event('change')
    elif action=='refresh':page.locator('#workflowResolvedRefresh').click()
    else:page.keyboard.press('Escape')
    assert page.evaluate('workflowReviewPacket===null && workflowReviewJson==="" && workflowReviewObjectUrl===""')
    assert page.locator('#workflowReviewPreview').text_content()==''
    expect(page.locator('#workflowReviewAck')).not_to_be_checked()
    expect(page.locator('#workflowReviewDownload')).to_be_disabled()
    assert len(calls)==count and not errors and not external


def test_closed_review_preparation_discards_late_response(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,*_=routing;_,body=completed(routing)
    enter(page);select_test(page,body);pending=[]
    page.route('**/admin/api/workflow-composer/review-packet',lambda route:pending.append(route))
    page.locator('#workflowReviewPrepare').click()
    expect(page.locator('#workflowReviewStatus')).to_contain_text('Preparing retained metadata')
    page.locator('#workflowResolvedClose').click()
    pending_request(page,pending)
    pending[0].fulfill(status=200,content_type='application/json',body=json.dumps(ReviewPackets(rt).prepare(body)))
    page.wait_for_timeout(100)
    assert page.evaluate('workflowReviewPacket===null') and page.locator('#workflowReviewPreview').text_content()==''
    expect(page.locator('#workflowReviewDownload')).to_be_disabled()
    assert not errors and not external


def test_inspecting_while_preparation_is_pending_resets_prepare_button_and_ignores_old_packet(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing;_,body=completed(routing)
    enter(page);select_test(page,body);pending=[];pattern='**/admin/api/workflow-composer/review-packet'
    def hold(route):pending.append(route)
    page.route(pattern,hold)
    page.locator('#workflowReviewPrepare').click()
    expect(page.locator('#workflowReviewPrepare')).to_be_disabled()
    page.locator('#workflowResolvedLoad').click()
    expect(page.locator('#workflowResolvedStatus')).to_contain_text('Recorded input inspection ready')
    expect(page.locator('#workflowReviewPrepare')).to_be_enabled()
    pending_request(page,pending)
    pending[0].fulfill(status=200,content_type='application/json',body=json.dumps(ReviewPackets(rt).prepare(body)))
    page.wait_for_timeout(100)
    assert page.evaluate('workflowReviewPacket===null') and page.locator('#workflowReviewPreview').text_content()==''
    expect(page.locator('#workflowReviewPrepare')).to_be_enabled()
    page.unroute(pattern,hold);count=len(calls);prepare(page)
    assert len(calls)==count and not errors and not external


def test_expired_session_clears_private_review_memory_without_browser_storage(fallback_page):
    page,routing,errors,external,_=fallback_page;_,body=completed(routing)
    enter(page);select_test(page,body);prepare(page)
    page.route('**/admin/api/workflow-composer/review-packet',lambda route:route.fulfill(status=401,content_type='application/json',body='{"detail":"Session expired."}'))
    page.locator('#workflowReviewPrepare').click()
    expect(page.locator('#workflowResolvedDialog')).to_be_hidden();expect(page.locator('#adminLoginModal')).to_be_visible()
    assert page.evaluate('workflowReviewPacket===null && workflowReviewJson===""')
    assert not page.evaluate('Object.keys(sessionStorage).concat(Object.keys(localStorage)).some(key=>key.toLowerCase().includes("review")||key.toLowerCase().includes("worksheet"))')
    assert not errors and not external


def test_role_refresh_closes_review_and_prevents_local_download(fallback_page):
    page,routing,errors,external,_=fallback_page;_,body=completed(routing)
    enter(page);select_test(page,body);prepare(page);page.locator('#workflowReviewAck').check()
    page.evaluate('() => {currentUser.role="admin"; updateUserUI(currentUser,false); downloadReviewWorksheet();}')
    expect(page.locator('#workflowResolvedDialog')).to_be_hidden()
    assert page.evaluate('workflowReviewPacket===null && workflowReviewJson===""')
    assert not errors and not external


def test_old_server_without_review_profile_keeps_inspection_and_never_posts_preparation(fallback_page):
    page,routing,errors,external,_=fallback_page;rt,_,_,calls,*_=routing;_,body=completed(routing)
    enter(page);posts=[]
    page.on('request',lambda req:posts.append(req.url) if req.method=='POST' else None)
    page.route('**/admin/api/workflow-composer/resolved-input/runs',lambda route:route.fulfill(
        status=200,content_type='application/json',body=json.dumps(ResolvedEvidence(rt).runs())))
    select_test(page,body);count=len(calls)
    expect(page.locator('#workflowReviewPrepare')).to_be_disabled()
    expect(page.locator('#workflowReviewStatus')).to_contain_text('unavailable in this server version')
    page.evaluate('prepareReviewWorksheet()')
    page.locator('#workflowResolvedLoad').click()
    expect(page.locator('#workflowResolvedStatus')).to_contain_text('Recorded input inspection ready')
    expect(page.locator('#workflowReviewStatus')).to_contain_text('retained-input inspector remains available')
    expect(page.locator('#workflowReviewPrepare')).to_be_disabled()
    assert not any(url.endswith('/review-packet') for url in posts) and len(calls)==count
    assert page.evaluate('workflowReviewPacket===null && workflowReviewAvailable===false')
    assert not errors and not external
