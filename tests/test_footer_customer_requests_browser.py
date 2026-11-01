"""Footer-to-admin user journeys with Chromium, real APIs and isolated state."""
import time
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from agent_market.concierge.front import Front, create_front_app, clear_front_caches
from tests.test_front_workflow_browser import browser  # noqa: F401
from tests.report_fixtures import execution_report

import pytest  # noqa: E402
pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')

pw = pytest.importorskip('playwright.sync_api')
REPORT = Path('reports/footer-customer-requests-2026-10-17')


@pytest.fixture
def journey(browser, tmp_path):
    db_path = tmp_path/'journey.sqlite3'
    store = Store(str(db_path))
    now = time.time()
    rid = store.upsert_resource({'key':'footer-weather', 'source':'fixture', 'kind':'a2a',
        'url':'https://weather.example/api', 'name':'Verified Weather',
        'description':'Weather forecast temperature API', 'category':'travel_maps_weather'})
    tools=[{'name':'forecast','description':'Weather forecast for a city','inputSchema':{
        'type':'object','properties':{'city':{'type':'string'}},'required':['city']}}]
    with store.tx() as db:
        db.execute("UPDATE resources SET eval_grade='A',eval_score=95,health_status='healthy',last_ok_at=?,usage_guide=?,usage_tools=?,usage_full_tools=? WHERE id=?",
                   (now,json.dumps({'tools':tools}),json.dumps(tools),json.dumps(tools),rid))
    execution_report(store,rid,now,title='Verified Weather',slug='footer-weather',
                     is_success=1,status_code=200,created_at=now)
    front = Front(store, rag_engine=Mock())
    public_client = TestClient(create_front_app(front), base_url='https://agentconcierge.biz')
    clear_front_caches()
    app = FastAPI()
    app.include_router(dashboard_router(store, str(db_path),
        'isolated-test-token', None, front=front, ssl_manager=Mock(get_status=lambda: {})))
    admin_client = TestClient(app, base_url='https://admin.test')
    context = browser.new_context(viewport={'width':1280, 'height':950})
    state = SimpleNamespace(store=store, front=front, public_client=public_client,
        admin_client=admin_client, context=context, errors=[], external=[], requests=[],
        receipts=[], fail_paths=set())

    def serve(route):
        req = route.request
        url = urlsplit(req.url)
        client = {'agentconcierge.biz':public_client, 'admin.test':admin_client}.get(url.hostname)
        if not client:
            state.external.append(req.url)
            route.abort()
            return
        state.requests.append((req.method, url.path))
        if url.path in state.fail_paths:
            route.fulfill(status=503, content_type='application/json', body='{"detail":"Please try again."}')
            return
        response = client.request(req.method, url.path+('?' + url.query if url.query else ''),
            content=req.post_data, headers=req.headers)
        if req.method == 'POST' and url.path in ('/api/contact/submit', '/api/privacy/opt-out'):
            state.receipts.append(response.json())
        route.fulfill(status=response.status_code, body=response.content,
            headers={k:v for k,v in response.headers.items()
                     if k not in ('content-length','content-encoding','transfer-encoding')})

    context.route('**/*', serve)
    state.public = context.new_page()
    state.admin = context.new_page()
    for page in (state.public, state.admin):
        page.on('pageerror', lambda error: state.errors.append(str(error)))
    state.public.goto('https://agentconcierge.biz/')
    state.public.locator('#btnRejectNonEssentialCookies').click()
    close_notice = state.public.locator('#layerModalCloseBtn')
    if close_notice.is_visible():
        close_notice.click()
    yield state
    context.close()
    admin_client.close()
    public_client.close()
    store._db.close()
    assert not state.errors
    assert not state.external


def footer(state, doc):
    state.public.locator(f'footer [data-doc="{doc}"]').click()
    pw.expect(state.public.locator('#legalModal')).to_be_visible()


def admin_tab(state, subtab):
    page = state.admin
    if not page.url.startswith('https://admin.test'):
        page.goto('https://admin.test/admin/ui')
        page.locator('#adminLoginUsername').fill('sadmin')
        page.locator('#adminLoginPassword').fill('sadmin')
        page.locator('#adminLoginSubmitBtn').click()
        pw.expect(page.locator('#adminLoginModal')).to_be_hidden()
    page.locator('[data-tab="needs"]').click()
    with page.expect_response(f'**/admin/api/needs/{subtab}?*'):
        page.locator(f'[data-subtab="{subtab}"]').click()


def fill_inquiry(page, category='technical'):
    page.locator('#inqCategory').select_option(category)
    page.locator('#inqName').fill('Footer Journey Agent')
    page.locator('#inqEmail').fill('footer-journey@example.test')
    page.locator('#inqSubject').fill(f'Footer {category} request')
    page.locator('#inqMessage').fill('Please review this synthetic footer request.\nSecond line: A2A & MCP.')


def screenshot(page, name):
    REPORT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(REPORT/name))


@pytest.mark.parametrize('category,width', [
    ('general',1280), ('technical',1280), ('partnership',1280),
    ('security_abuse',1280), ('custom_agent',1280), ('billing',1280), ('technical',390)])
def test_contact_categories_admin_details_status_and_reload(journey, category, width):
    s = journey
    s.public.set_viewport_size({'width':width, 'height':950})
    s.admin.set_viewport_size({'width':width, 'height':950})
    footer(s, 'contact')
    fill_inquiry(s.public, category)
    s.public.locator('#btnSubmitInquiry').click()
    pw.expect(s.public.locator('#inqFeedbackMsg')).to_contain_text('Inquiry registered')
    inquiry_id = s.receipts[-1]['inquiry_id']
    pw.expect(s.public.locator('#inqFeedbackMsg')).to_contain_text(inquiry_id)
    stored = s.store.get_customer_inquiry(inquiry_id)
    assert stored['category'] == category and stored['status'] == 'pending'
    assert stored['email'] == 'footer-journey@example.test'
    assert stored['message'].endswith('Second line: A2A & MCP.')
    admin_tab(s, 'inquiries')
    pw.expect(s.admin.locator('#inquiriesTable')).to_contain_text(inquiry_id)
    with s.admin.expect_response('**/admin/api/needs/inquiries?*'):
        s.admin.locator('#inqCategorySelect').select_option(category)
    pw.expect(s.admin.locator('#inquiriesTable')).to_contain_text(inquiry_id)
    with s.admin.expect_response('**/admin/api/needs/inquiries?*q=*'):
        s.admin.locator('#inqSearchInput').fill('footer-journey@example.test')
    pw.expect(s.admin.locator('#inquiriesTable')).to_contain_text(inquiry_id)
    s.admin.locator(f'[data-inquiry-id="{inquiry_id}"]').click()
    for selector, value in [('#inqDtlId',inquiry_id), ('#inqDtlName',stored['name']),
                            ('#inqDtlEmail',stored['email']), ('#inqDtlSubject',stored['subject']),
                            ('#inqDtlMessage',stored['message'])]:
        pw.expect(s.admin.locator(selector)).to_have_text(value)
    s.admin.locator('#inquiryModalStatus').select_option('resolved')
    s.admin.locator('#inquiryModalResponse').fill('Synthetic review completed; internal note only.')
    s.admin.locator('#btnSaveInquiryResponse').click()
    pw.expect(s.admin.locator('#inquiryModal')).to_be_hidden()
    assert s.store.get_customer_inquiry(inquiry_id)['status'] == 'resolved'
    s.admin.reload()
    admin_tab(s, 'inquiries')
    s.admin.locator('#inqStatusSelect').select_option('resolved')
    pw.expect(s.admin.locator('#inquiriesTable')).to_contain_text('Synthetic review completed')
    s.admin.locator(f'[data-inquiry-id="{inquiry_id}"]').click()
    pw.expect(s.admin.locator('#inquiryModalResponse')).to_have_value('Synthetic review completed; internal note only.')
    assert s.admin.locator('#inquiryModalBody').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    if category == 'technical':
        s.public.locator('#inqFeedbackMsg').scroll_into_view_if_needed()
        screenshot(s.public, f'contact-confirmed-{width}.png')
        screenshot(s.admin, f'admin-contact-detail-{width}.png')


@pytest.mark.parametrize('width', [390,1280])
def test_privacy_choice_receipt_and_admin_filters(journey, width):
    s = journey
    s.public.set_viewport_size({'width':width, 'height':950})
    s.admin.set_viewport_size({'width':width, 'height':950})
    footer(s, 'ccpa')
    s.public.locator('#btnConfirmCcpaOptOut').click()
    pw.expect(s.public.locator('#ccpaOptOutStatus')).to_contain_text('Privacy request recorded')
    request_id = s.receipts[-1]['request_id']
    admin_tab(s, 'privacy')
    pw.expect(s.admin.locator('#privacyTable')).to_contain_text(request_id)
    s.admin.locator('#prvTypeSelect').select_option('ccpa_opt_out')
    s.admin.locator('#prvStatusSelect').select_option('received')
    pw.expect(s.admin.locator('#privacyTable')).to_contain_text('GPC Active')
    rows, total = s.store.list_privacy_requests()
    assert total == 1 and rows[0]['request_id'] == request_id
    assert rows[0]['gpc_detected'] == 1 and rows[0]['proof_hash']
    with s.admin.expect_response('**/admin/api/needs/privacy?q=*'):
        s.admin.locator('#prvSearchInput').fill(request_id)
    pw.expect(s.admin.locator('#privacyTable')).to_contain_text(request_id)
    screenshot(s.admin, f'admin-privacy-{width}.png')


def test_contact_reference_can_be_searched(journey):
    s = journey
    footer(s, 'contact')
    fill_inquiry(s.public)
    s.public.locator('#btnSubmitInquiry').click()
    pw.expect(s.public.locator('#inqFeedbackMsg')).to_contain_text('Inquiry registered')
    inquiry_id = s.receipts[-1]['inquiry_id']
    admin_tab(s, 'inquiries')
    with s.admin.expect_response('**/admin/api/needs/inquiries?q=*'):
        s.admin.locator('#inqSearchInput').fill(inquiry_id)
    pw.expect(s.admin.locator('#inquiriesTable')).to_contain_text(inquiry_id)


def test_validation_and_failed_submissions_never_create_phantom_requests(journey):
    s = journey
    footer(s, 'contact')
    fill_inquiry(s.public)
    s.public.locator('#inqEmail').fill('invalid-address')
    s.public.locator('#btnSubmitInquiry').click()
    assert s.public.locator('#inqEmail').evaluate('(el)=>el.validity.valid') is False
    assert not s.store.list_customer_inquiries()[1]
    s.public.locator('#inqEmail').fill('footer-journey@example.test')
    s.fail_paths.add('/api/contact/submit')
    s.public.locator('#btnSubmitInquiry').click()
    pw.expect(s.public.locator('#inqFeedbackMsg')).to_contain_text('Error submitting inquiry')
    pw.expect(s.public.locator('#btnSubmitInquiry')).to_be_enabled()
    assert s.public.locator('#inqSubject').input_value() == 'Footer technical request'
    assert not s.store.list_customer_inquiries()[1]
    s.public.locator('#legalModalTabs [data-doc="ccpa"]').click()
    s.fail_paths.add('/api/privacy/opt-out')
    s.public.locator('#btnConfirmCcpaOptOut').click()
    pw.expect(s.public.locator('#ccpaOptOutStatus')).to_contain_text('server request could not be confirmed')
    assert not s.store.list_privacy_requests()[1]
    assert s.public.evaluate('JSON.parse(localStorage.getItem(COOKIE_STORAGE_KEY)).analytics') is False


@pytest.mark.parametrize('stop_link', [False,True])
def test_footer_task_stop_is_visible_in_admin_cancellations(journey, stop_link):
    s = journey
    s.public.goto('https://agentconcierge.biz/#chat')
    s.public.locator('#chatInput').fill('weather forecast')
    s.public.locator('#chatSubmit').click()
    s.public.get_by_role('button', name='Get updates for this task').click()
    s.public.locator('#taskUpdateChannel').select_option('poll')
    s.public.locator('#taskUpdateAuthority').check()
    s.public.locator('#taskUpdateConsent').check()
    s.public.locator('#taskUpdateSubmit').click()
    s.public.locator('#taskUpdateConfirmDestination').click()
    pw.expect(s.public.locator('#taskUpdateStatus')).to_have_text('Task updates are on.')
    watch_id = s.store.query('SELECT id FROM agent_task_watches')[0]['id']
    if stop_link:
        s.public.goto('about:blank')
        s.public.goto('https://agentconcierge.biz/#stop-updates='+s.front.updates.capability(watch_id))
        s.public.locator('#taskStopFromLink').click()
        pw.expect(s.public.locator('#taskPreferences')).to_have_text('Task updates stopped.')
    else:
        s.public.locator('#taskUpdateManage').click()
        s.public.get_by_role('button', name='Stop updates', exact=True).click()
        pw.expect(s.public.locator('#taskPreferences')).to_contain_text('Stopped')
    assert s.store.query('SELECT state FROM agent_task_watches')[0]['state'] == 'revoked'
    admin_tab(s, 'cancellations')
    rows, total = s.store.list_cancellation_requests()
    assert total == 1, 'Footer stop must be recorded in Customer Requests, not only Visitor Desk'
    request_id = rows[0]['request_id']
    pw.expect(s.admin.locator('#cancellationsTable')).to_contain_text(request_id)
    with s.admin.expect_response('**/admin/api/needs/cancellations?q=*'):
        s.admin.locator('#cnlSearchInput').fill(request_id)
    pw.expect(s.admin.locator('#cancellationsTable')).to_contain_text(request_id)
    # A revoked task requires renewed customer permission; the admin cannot revive it.
    assert s.admin.locator(f'[data-request-id="{request_id}"]').count() == 0
    screenshot(s.admin, 'admin-notification-stop.png')


def test_policy_links_and_cookie_choice_are_local_not_customer_requests(journey):
    s = journey
    for doc in ('tos','privacy','accessibility','ai','cancellation'):
        footer(s, doc)
        pw.expect(s.public.locator('#legalModalBody')).not_to_be_empty()
        s.public.keyboard.press('Escape')
    assert s.store.get_customer_requests_summary()['inquiries']['total'] == 0
    assert not s.store.list_privacy_requests()[1]
    assert not s.store.list_cancellation_requests()[1]


def test_admin_requires_authentication_and_stored_markup_stays_inert(journey):
    s = journey
    for path in ('inquiries','privacy','cancellations','summary'):
        assert s.admin_client.get('/admin/api/needs/'+path).status_code in (401,403)
    footer(s, 'contact')
    fill_inquiry(s.public, 'security_abuse')
    s.public.locator('#inqMessage').fill('Audit <img src=x onerror="window.__footerXss=1"> & <script>window.__footerXss=1</script>')
    s.public.locator('#btnSubmitInquiry').click()
    pw.expect(s.public.locator('#inqFeedbackMsg')).to_contain_text('Inquiry registered')
    inquiry_id = s.receipts[-1]['inquiry_id']
    admin_tab(s, 'inquiries')
    s.admin.locator(f'[data-inquiry-id="{inquiry_id}"]').click()
    assert s.admin.locator('#inquiryModalBody img, #inquiryModalBody script').count() == 0
    assert s.admin.evaluate('window.__footerXss || 0') == 0
