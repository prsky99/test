"""Independent automation approvals and events in an isolated admin browser."""
import json
from pathlib import Path
from tests.browser_wait import pending_request
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_admin_security_browser import browser
from tests.test_workflow_fallback import routing
from tests.test_workflow_typed_flow import typed_routing
from tests.test_workflow_publication_browser import publication_page, released, enter_admin

REPORT = Path('reports/advancement-automation-batch-2026-10-18')


def enter_automation(page, signed_in=False, ready=True):
    if signed_in:
        page.locator('#workflowPublicationOpen').click()
        expect(page.locator('#workflowPublicationDialog')).to_be_visible()
    else:
        enter_admin(page)
    action = page.locator('#publicationReleases').get_by_role('button', name='Review automation', exact=True)
    expect(action).to_be_enabled()
    action.click()
    expect(page.locator('#connectionAutomationDialog')).to_be_visible()
    if ready: expect(page.locator('#automationPrepare')).to_be_enabled()
    else: expect(page.locator('#automationPrepare')).to_be_disabled()


def prepare_automation(page, trigger='scheduled'):
    page.locator('#automationTrigger').select_option(trigger)
    page.locator('#automationMaxRuns').fill('2')
    page.locator('#automationTtl').fill('1800')
    if trigger == 'scheduled': page.locator('#automationInterval').fill('300')
    page.locator('#automationPrepare').click()
    expect(page.locator('#automationStatus')).to_contain_text('Automation review ready')


def issue_automation(page, trigger='scheduled'):
    prepare_automation(page, trigger)
    page.locator('#automationShare').check()
    page.locator('#automationGrant').check()
    page.locator('#automationIssue').click()
    expect(page.locator('#automationStatus')).to_contain_text('automation grant issued')


def select_event(page):
    options = page.locator('#automationEventGrant option').evaluate_all('(options)=>options.map(option=>option.value).filter(Boolean)')
    assert len(options) == 1
    page.locator('#automationEventGrant').select_option(options[0])
    return options[0]


def test_schedule_review_requires_independent_sharing_and_trigger_approvals(publication_page):
    page, rt, web, _, _, errors, external, requests = publication_page
    released(web)
    before = list(rt.typed_test_controls['seen'])
    enter_automation(page)
    prepare_automation(page)
    expect(page.locator('#automationPreview')).to_contain_text('Exact news query: Python news')
    expect(page.locator('#automationPreview')).to_contain_text('future actual text is not known')
    expect(page.locator('#automationPreview')).to_contain_text('Fixed absolute news window for every run')
    expect(page.locator('#automationShare')).not_to_be_checked()
    expect(page.locator('#automationGrant')).not_to_be_checked()
    page.evaluate('issueConnectionAutomation()')
    assert not [path for method, path, _, _ in requests if method == 'POST' and path.endswith('/automation/issue')]
    page.locator('#automationShare').check()
    expect(page.locator('#automationIssue')).to_be_disabled()
    REPORT.mkdir(parents=True, exist_ok=True)
    page.set_viewport_size({'width': 1280, 'height': 1100})
    page.screenshot(path=str(REPORT / 'admin-automation-review.png'))
    rect = page.locator('#connectionAutomationDialog').bounding_box()
    assert rect and abs(rect['x'] + rect['width'] / 2 - 640) < 3
    page.locator('#automationGrant').check()
    page.locator('#automationIssue').click()
    expect(page.locator('#automationStatus')).to_contain_text('automation grant issued')
    expect(page.locator('#automationGrants')).to_contain_text('Interval schedule')
    expect(page.locator('#automationGrants')).to_contain_text('0/2')
    expect(page.locator('#automationShare')).not_to_be_checked()
    expect(page.locator('#automationGrant')).not_to_be_checked()
    assert rt.typed_test_controls['seen'] == before
    issued = [json.loads(body) for method, path, body, _ in requests if method == 'POST' and path.endswith('/automation/issue')]
    assert len(issued) == 1 and set(issued[0]) == {'proposal', 'signature', 'sharing_authority', 'sharing_notice', 'trigger_authority', 'trigger_notice'}
    assert issued[0]['sharing_authority'] is True and issued[0]['trigger_authority'] is True
    assert not errors and not external


def test_authenticated_event_requires_fresh_action_and_records_one_connected_run(publication_page):
    page, rt, web, _, _, errors, external, requests = publication_page
    released(web)
    before = len(rt.typed_test_controls['seen'])
    enter_automation(page)
    storage_before = page.evaluate('Object.keys(localStorage).concat(Object.keys(sessionStorage)).sort()')
    issue_automation(page, 'event')
    select_event(page)
    expect(page.locator('#automationInterval')).to_be_disabled()
    expect(page.locator('#automationEventAuthority')).not_to_be_checked()
    page.evaluate('submitAutomationEvent()')
    assert len(rt.typed_test_controls['seen']) == before
    page.locator('#automationEventAuthority').check()
    with page.expect_response('**/automation/grants/*/trigger') as event_response:
        page.locator('#automationEventRun').click()
    assert event_response.value.status == 202, event_response.value.text()
    expect(page.locator('#automationRuns')).to_contain_text('succeeded', timeout=15000)
    assert len(rt.typed_test_controls['seen']) == before + 2
    assert rt.typed_test_controls['seen'][-1]['query'] == rt.typed_test_controls['title']
    events = [json.loads(body) for method, path, body, _ in requests if method == 'POST' and path.endswith('/trigger')]
    assert len(events) == 1 and set(events[0]) == {'event_id', 'authority', 'notice'} and len(events[0]['event_id']) == 32
    expect(page.locator('#automationEventAuthority')).not_to_be_checked()
    expect(page.locator('#automationEventRun')).to_be_disabled()
    assert page.evaluate('Object.keys(localStorage).concat(Object.keys(sessionStorage)).sort()') == storage_before
    assert not errors and not external


@pytest.mark.parametrize('change', ['settings', 'close', 'escape', 'role', 'token'])
def test_automation_review_and_both_permissions_clear_on_context_change(publication_page, change):
    page, _, web, _, _, errors, external, _ = publication_page
    released(web)
    enter_automation(page)
    prepare_automation(page)
    page.locator('#automationShare').check()
    page.locator('#automationGrant').check()
    if change == 'settings': page.locator('#automationMaxRuns').fill('3')
    elif change == 'close': page.locator('#automationClose').click()
    elif change == 'escape': page.keyboard.press('Escape')
    elif change == 'role': page.evaluate('()=>{currentUser.role="admin";updateUserUI(currentUser,false);}')
    else: page.evaluate('()=>{token="rotated-session";updateUserUI(currentUser,false);}')
    assert page.evaluate('automationPlan===null')
    expect(page.locator('#automationShare')).not_to_be_checked()
    expect(page.locator('#automationGrant')).not_to_be_checked()
    expect(page.locator('#automationIssue')).to_be_disabled()
    assert not errors and not external


@pytest.mark.parametrize('change', ['settings', 'close', 'logout'])
def test_late_automation_review_never_restores_consent_or_stale_private_state(publication_page, change):
    page, _, web, _, admin, errors, external, _ = publication_page
    released(web)
    enter_automation(page)
    pending, logouts = [], []
    page.route('**/automation/prepare', lambda route: pending.append(route))
    def hold_logout(route):
        logouts.append(route)
        page.evaluate('globalThis.__automationLogoutHeld=true')
    page.route('**/admin/api/auth/logout', hold_logout)
    page.locator('#automationInterval').fill('300')
    page.locator('#automationTtl').fill('1800')
    page.locator('#automationPrepare').click()
    pending_request(page,pending)
    request = pending[0].request
    response = admin.post(urlsplit(request.url).path, content=request.post_data, headers=request.headers)
    assert response.status_code == 200, response.text
    if change == 'settings': page.locator('#automationMaxRuns').fill('4')
    elif change == 'close': page.locator('#automationClose').click()
    else:
        page.on('dialog', lambda dialog: dialog.accept())
        page.evaluate('document.getElementById("logoutBtn").click()')
        page.wait_for_function('()=>globalThis.__automationLogoutHeld===true')
        assert len(logouts) == 1
    with page.expect_response('**/automation/prepare'):
        pending[0].fulfill(status=200, body=response.content, content_type='application/json')
    page.wait_for_function('()=>automationBusy===false')
    assert page.evaluate('automationPlan===null')
    expect(page.locator('#automationShare')).not_to_be_checked()
    expect(page.locator('#automationIssue')).to_be_disabled()
    if change == 'settings': expect(page.locator('#automationPrepare')).to_be_enabled()
    if logouts:
        logouts[0].fulfill(status=200, content_type='application/json', body='{"ok":true}')
        expect(page.locator('#adminLoginModal')).to_be_visible()
    assert not errors and not external


def test_old_backend_marker_preserves_publication_but_never_posts_automation(publication_page):
    page, _, web, _, admin, errors, external, requests = publication_page
    released(web)
    def old(route):
        url = urlsplit(route.request.url)
        response = admin.get(url.path + ('?' + url.query if url.query else ''), headers=route.request.headers)
        body = response.json(); body.pop('connected_automation_profile', None)
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body))
    page.route('**/admin/api/workflows?limit=100', old)
    page.route('**/admin/api/workflow-publications/options', old)
    enter_admin(page)
    expect(page.locator('#publicationPrepare')).to_be_enabled()
    expect(page.locator('#publicationReleases').get_by_role('button', name='Review automation', exact=True)).to_be_disabled()
    assert not [path for _, path, _, _ in requests if '/automation/' in path]
    assert not errors and not external


def test_expired_signed_review_cannot_issue_even_before_grant_expiry(publication_page):
    page, _, web, _, _, errors, external, requests = publication_page
    released(web); enter_automation(page); prepare_automation(page)
    expiry = page.evaluate('automationPlan.proposal.expires')
    assert page.evaluate('automationPlan.preview.expires') >= expiry
    page.locator('#automationShare').check(); page.locator('#automationGrant').check()
    page.evaluate('(expires)=>{Date.now=()=>Math.ceil((expires+1)*1000);}', expiry)
    page.locator('#automationIssue').click()
    expect(page.locator('#automationStatus')).to_contain_text('signed review expired')
    assert not [path for method, path, _, _ in requests if method == 'POST' and path.endswith('/automation/issue')]
    assert not errors and not external


def test_accepted_event_with_lost_response_is_not_resubmitted_or_given_new_id(publication_page):
    page, rt, web, _, admin, errors, external, requests = publication_page
    released(web); enter_automation(page); issue_automation(page, 'event'); grant = select_event(page)
    before = len(rt.typed_test_controls['seen']); accepted = []
    def interrupted(route):
        response = admin.post(urlsplit(route.request.url).path, content=route.request.post_data, headers=route.request.headers)
        assert response.status_code in (200, 202), response.text
        accepted.append(response.json())
        route.fulfill(status=400, content_type='application/json', body='{"error":"The response is unavailable."}')
    page.route('**/automation/grants/*/trigger', interrupted)
    page.locator('#automationEventAuthority').check(); page.locator('#automationEventRun').click()
    expect(page.locator('#automationEventStatus')).to_contain_text('acceptance could not be confirmed')
    original = page.evaluate('(id)=>automationEvents.get(id).id', grant)
    page.evaluate('submitAutomationEvent()')
    expect(page.locator('#automationEventAuthority')).to_be_disabled()
    expect(page.locator('#automationEventRun')).to_be_disabled()
    assert len(accepted) == 1 and page.evaluate('(id)=>automationEvents.get(id).id', grant) == original
    page.locator('#automationRefresh').click()
    expect(page.locator('#automationRuns')).to_contain_text('succeeded', timeout=15000)
    assert len(rt.typed_test_controls['seen']) == before + 2
    assert len([path for method, path, _, _ in requests if method == 'POST' and path.endswith('/trigger')]) == 0
    assert not errors and not external


def test_unknown_event_stays_locked_across_history_refresh_and_reopen(publication_page):
    page, rt, web, _, _, errors, external, _ = publication_page
    released(web); enter_automation(page); issue_automation(page, 'event'); select_event(page)
    rt.publication_browser_modes['alternate.example'] = 'unknown'
    rt.publication_browser_modes['third.example'] = 'unknown'
    page.locator('#automationEventAuthority').check(); page.locator('#automationEventRun').click()
    expect(page.locator('#automationRuns')).to_contain_text('Agent outcome unknown', timeout=15000)
    expect(page.locator('#automationEventAuthority')).to_be_disabled()
    page.locator('#automationRefresh').click()
    expect(page.locator('#automationStatus')).to_contain_text('history refreshed')
    select_event(page); expect(page.locator('#automationEventRun')).to_be_disabled()
    page.locator('#automationClose').click(); enter_automation(page, signed_in=True, ready=False)
    expect(page.locator('#automationRuns')).to_contain_text('Agent outcome unknown')
    expect(page.locator('#automationEventAuthority')).to_be_disabled()
    expect(page.locator('#automationEventRun')).to_be_disabled()
    assert not errors and not external


def test_history_refresh_and_revision_revoke_do_not_start_any_run(publication_page):
    page, rt, web, _, _, errors, external, requests = publication_page
    released(web); enter_automation(page); issue_automation(page)
    before = list(rt.typed_test_controls['seen'])
    page.locator('#automationMaxRuns').fill('3')
    page.locator('#automationRefresh').click()
    expect(page.locator('#automationStatus')).to_contain_text('history refreshed')
    page.locator('#automationGrants').get_by_role('button', name='Revoke automation grant').click()
    expect(page.locator('#automationStatus')).to_contain_text('Automation grant revoked')
    expect(page.locator('#automationGrants')).to_contain_text('Withdrawn')
    bodies = [json.loads(body) for method, path, body, _ in requests if method == 'POST' and '/automation/' in path and path.endswith('/revoke')]
    assert bodies == [{'revision': 1}] and rt.typed_test_controls['seen'] == before
    assert not errors and not external


def test_automation_preview_treats_provider_markup_as_text(publication_page):
    page, _, web, _, admin, errors, external, _ = publication_page
    released(web); enter_automation(page)
    def hostile(route):
        response = admin.post(urlsplit(route.request.url).path, content=route.request.post_data, headers=route.request.headers)
        body = response.json(); body['preview']['source']['label'] = '<img src="https://malicious.example/x" onerror="globalThis.unsafeRan=true">'
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body))
    page.route('**/automation/prepare', hostile)
    prepare_automation(page)
    expect(page.locator('#automationPreview')).to_contain_text('<img src=')
    assert page.locator('#automationPreview img').count() == 0 and page.evaluate('globalThis.unsafeRan!==true')
    assert not errors and not external


def test_ambiguous_grant_issue_refreshes_history_without_repeating_issuance(publication_page):
    page, rt, web, _, admin, errors, external, _ = publication_page
    released(web); enter_automation(page); prepare_automation(page)
    before = list(rt.typed_test_controls['seen']); issued = []
    def interrupted(route):
        response = admin.post(urlsplit(route.request.url).path, content=route.request.post_data, headers=route.request.headers)
        assert response.status_code == 200, response.text
        issued.append(response.json())
        route.fulfill(status=500, content_type='application/json', body='{"error":"The response is unavailable."}')
    page.route('**/automation/issue', interrupted)
    page.locator('#automationShare').check(); page.locator('#automationGrant').check(); page.locator('#automationIssue').click()
    expect(page.locator('#automationStatus')).to_contain_text('issuance could not be confirmed')
    page.evaluate('issueConnectionAutomation()')
    page.locator('#automationRefresh').click()
    expect(page.locator('#automationGrants')).to_contain_text('0/2')
    assert len(issued) == 1 and page.locator('#automationGrants button').count() == 1
    assert rt.typed_test_controls['seen'] == before and not errors and not external


@pytest.mark.parametrize('action', ['issue', 'event'])
def test_late_mutation_result_after_close_cannot_restore_automation_state(publication_page, action):
    page, _, web, _, admin, errors, external, _ = publication_page
    released(web); enter_automation(page)
    if action == 'issue':
        prepare_automation(page)
        page.locator('#automationShare').check(); page.locator('#automationGrant').check()
        pattern, button = '**/automation/issue', '#automationIssue'
    else:
        issue_automation(page, 'event'); select_event(page); page.locator('#automationEventAuthority').check()
        pattern, button = '**/automation/grants/*/trigger', '#automationEventRun'
    page.evaluate('''selector => {
      globalThis.__automationMutationSettled = false;
      const element = document.querySelector(selector), original = element.onclick;
      element.onclick = async (...args) => {
        try { return await original(...args); }
        finally { globalThis.__automationMutationSettled = true; }
      };
    }''', button)
    pending = []; page.route(pattern, lambda route: pending.append(route))
    page.locator(button).click(); pending_request(page,pending)
    request = pending[0].request
    response = admin.post(urlsplit(request.url).path, content=request.post_data, headers=request.headers)
    assert response.status_code == (200 if action == 'issue' else 202), response.text
    page.locator('#automationClose').click()
    pending[0].fulfill(status=response.status_code, content_type='application/json', body=response.content)
    page.wait_for_function('()=>globalThis.__automationMutationSettled===true')
    expect(page.locator('#connectionAutomationDialog')).to_be_hidden()
    assert page.evaluate('automationPlan===null && automationRelease===null && automationEvents.size===0')
    assert page.locator('#automationGrants').inner_text() == '' and page.locator('#automationRuns').inner_text() == ''
    assert not errors and not external


def test_unavailable_release_preserves_history_and_revocation_without_new_event(publication_page):
    page, rt, web, _, admin, errors, external, requests = publication_page
    released(web); enter_automation(page); issue_automation(page, 'event'); page.locator('#automationClose').click()
    before = list(rt.typed_test_controls['seen'])
    def unavailable(route):
        response = admin.get(urlsplit(route.request.url).path, headers=route.request.headers)
        body = response.json(); body['available'] = False
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body))
    page.route('**/automation/options', unavailable)
    page.locator('#workflowPublicationOpen').click()
    page.locator('#publicationReleases').get_by_role('button', name='Review automation', exact=True).click()
    expect(page.locator('#automationStatus')).to_contain_text('unavailable for new automation')
    expect(page.locator('#automationPrepare')).to_be_disabled()
    select_event(page); expect(page.locator('#automationEventAuthority')).to_be_disabled()
    page.evaluate('submitAutomationEvent()')
    page.locator('#automationGrants').get_by_role('button', name='Revoke automation grant').click()
    expect(page.locator('#automationStatus')).to_contain_text('Automation grant revoked')
    assert not [path for method, path, _, _ in requests if method == 'POST' and path.endswith('/trigger')]
    assert rt.typed_test_controls['seen'] == before and not errors and not external
