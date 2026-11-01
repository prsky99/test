from tests.human_workspace_helpers import manual
"""Workflow entry routing and user-only progress on isolated customer handlers."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from agent_market.customer_identity_service import COOKIE
from tests.test_customer_organizations import orgs  # noqa: F401
from tests.test_customer_organizations_browser import account_page,choose_workspace
from tests.test_workspace_prelaunch_browser import (  # noqa: F401
    browser, customer_flow, typed_release_world, typed_world, routing,
)

PROOF = Path('reports/workspace-routing-progress-2026-10-21')


def test_anonymous_entry_never_returns_workspace_document(customer_flow):
    x = customer_flow
    x.client.cookies.clear()
    for path in ('/customer/workspaces', '/customer/organizations'):
        response = x.client.get(path, follow_redirects=False)
        assert response.status_code == 303 and response.headers['location'] == '/customer/sign-in'
        assert 'workspace-sidebar' not in response.text and 'Your organizations' not in response.text
        assert response.headers['cache-control'] == 'no-store'


def test_signin_is_visible_while_session_is_checked(customer_flow, browser):
    x = customer_flow; context, page, errors, calls = entry_page(x, browser)
    held = []
    page.route('**/api/customer-auth/status', lambda route: held.append(route))
    page.route('**/api/customer-auth/session', lambda route: held.append(route))
    try:
        page.goto('https://customer.test/customer/sign-in')
        expect(page.locator('#google')).to_be_visible()
        expect(page.locator('#google')).to_be_disabled()
        expect(page.locator('.workspace-sidebar')).to_have_count(0)
        assert len(held) == 1
        response = x.client.get('/api/customer-auth/status')
        held.pop().fulfill(status=200, body=response.content, content_type='application/json')
        expect(page).to_have_url('https://customer.test/customer/workspaces')
        # UI policy 11-01: the shell is visible while the session is checked.
        expect(page.locator('.workspace-sidebar')).to_be_visible()
        expect(page.locator('#workspace-entry-progress')).to_have_count(0)
        expect(page.locator('body')).to_have_attribute('data-workspace-loading', 'true')
        assert len(held) == 1
        response = x.client.get('/api/customer-auth/session')
        held.pop().fulfill(status=200, body=response.content, content_type='application/json')
        expect(page.locator('body')).not_to_have_attribute('data-workspace-loading', 'true')
        expect(page.locator('#manage')).to_be_visible()
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize('failure', [False, True])
def test_shell_shows_at_once_and_reads_run_beside_the_session_check(customer_flow, browser, failure):
    """UI policy 11-01: no full-page gate; only the status line shows loading."""
    x = customer_flow; context, page, errors, calls = entry_page(x, browser, 390)
    session = []; drafts = []
    path = '/api/customer-organizations/' + x.ws
    page.route('**/api/customer-auth/session', lambda route: session.append(route))
    page.route('**' + path, lambda route: drafts.append(route))
    try:
        with page.expect_request('**' + path):
            page.goto('https://customer.test/customer/organizations')
        assert len(session) == 1, 'organization reads start without waiting for the session check'
        expect(page.locator('#workspace-entry-progress')).to_have_count(0)
        expect(page.locator('#workspace-main h1')).to_be_visible()
        expect(page.locator('#status')).to_be_visible()
        page.locator('#workspace-menu').click()
        expect(page.locator('.workspace-sidebar')).to_be_visible()
        page.locator('#workspace-menu').click()
        expect(page.locator('#content')).not_to_be_visible()
        response = x.client.get('/api/customer-auth/session')
        session.pop().fulfill(status=200, body=response.content, content_type='application/json')
        expect(page.locator('body')).to_have_attribute('data-workspace-loading', 'true')
        response = x.client.get(path)
        proof = Path('reports/workspace-login-loading-2026-10-22'); proof.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(proof / 'initial-loading-mobile.png'))
        drafts.pop().fulfill(status=503 if failure else response.status_code,
                            body=b'{}' if failure else response.content, content_type='application/json')
        expect(page.locator('body')).not_to_have_attribute('data-workspace-loading', 'true')
        if failure:
            expect(page.locator('#retry-access')).to_be_visible()
        else:
            expect(page.locator('#content')).to_be_visible()
            expect(page.locator('#org-title')).to_have_text('Customer multi-step studio')
            page.screenshot(path=str(proof / 'initial-ready-mobile.png'), full_page=True)
        assert not errors and not any(method != 'GET' for method, _ in calls)
    finally:
        context.close()


def test_studio_shows_without_waiting_for_fonts_and_defers_history(customer_flow, browser):
    from tests.test_customer_typed_authoring import save_run
    x = customer_flow; flow, _ = save_run(x)
    context, page, errors, calls = entry_page(x, browser)
    page.add_init_script("Object.defineProperty(document.fonts,'ready',{value:new Promise(()=>{})})")
    held = []
    path = '/api/customer-organizations/' + x.ws + '/authoring/typed/flows/' + flow['id'] + '/runs'
    page.route('**' + path, lambda route: held.append(route))
    try:
        page.goto('https://customer.test/customer/organizations/' + x.ws + '/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        assert not held, 'History is deferred until a saved workflow is opened' 
        expect(page.locator('#workspace-entry-progress')).to_have_count(0)
        expect(page.locator('#workspace-main')).to_be_visible()
        expect(page.locator('body')).not_to_have_attribute('data-workspace-loading', 'true')
        expect(page.locator('#workflow-cards .card-strand i')).to_have_count(2)
        page.locator('#human-nav-library').click()
        with page.expect_request('**' + path):page.locator('.workflow-card').first.click()
        expect(page.locator('#workspace-progress')).to_be_visible()
        response=x.client.get(path)
        held.pop().fulfill(status=response.status_code,body=response.content,content_type='application/json')
        expect(page.locator('#results')).to_contain_text('Current documentation')
        assert not errors and not any(method != 'GET' for method, _ in calls)
    finally:
        context.close()


def entry_page(x, browser, width=1440):
    context = browser.new_context(viewport={'width': width, 'height': 900}, offline=True)
    context.add_cookies([{'name': COOKIE, 'value': x.s.raw, 'url': 'https://customer.test',
                         'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
    page = context.new_page(); errors = []; calls = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    def serve(route):
        req = route.request; url = urlsplit(req.url)
        assert url.hostname == 'customer.test'
        calls.append((req.method, url.path))
        response = x.client.request(req.method, url.path + ('?' + url.query if url.query else ''),
                                    headers=req.headers, content=req.post_data, follow_redirects=False)
        route.fulfill(status=response.status_code, body=response.content,
                      headers={k: v for k, v in response.headers.items() if k not in
                               ('set-cookie', 'content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', serve)
    return context, page, errors, calls


def only_workflows(page):
    active = page.locator('.workspace-sidebar a[aria-current="page"]')
    expect(active).to_have_count(1); expect(active).to_have_text('Workflows')


@pytest.mark.parametrize('width', [1440, 390])
def test_landing_workflows_opens_studio_instead_of_overview(customer_flow, browser, width):
    x = customer_flow; context, page, errors, calls = entry_page(x, browser, width)
    before = len(x.w.calls)
    try:
        page.goto('https://customer.test/customer/workspaces')
        expect(page.locator('#status')).to_have_text('You are signed in.')
        if width<=900:page.locator('#workspace-menu').click()
        link = page.locator('.workspace-sidebar').get_by_role('link', name='Workflows', exact=True)
        expect(link).to_have_attribute('href', '/customer/workflows')
        link.click()
        expect(page).to_have_url('https://customer.test/customer/organizations/' + x.ws + '/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        only_workflows(page)
        expect(page.locator('#workspace-progress')).to_be_hidden()
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        PROOF.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(PROOF / ('fixed-workflows-' + str(width) + '.png')))
        assert not errors and len(x.w.calls) == before
        assert not any(method != 'GET' for method, _ in calls)
    finally: context.close()


def test_multiple_workspaces_choose_by_name_and_keep_workflows_active(customer_flow, browser):
    x = customer_flow
    extra = x.core.organizations.create({'name': '<img src=x onerror=alert(1)> Research'}, x.s.customer)
    context, page, errors, calls = entry_page(x, browser)
    try:
        page.goto('https://customer.test/customer/workflows')
        expect(page.locator('#status')).to_have_text('Choose a workspace to open its workflows.')
        only_workflows(page)
        expect(page.locator('#workflow-workspaces a')).to_have_count(2)
        assert page.locator('#workflow-workspaces img').count() == 0
        PROOF.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(PROOF / 'multiple-workspaces.png'))
        page.locator('#workflow-workspaces').get_by_role('link', name=extra['name'], exact=True).click()
        expect(page).to_have_url('https://customer.test/customer/organizations/' + extra['id'] + '/flows')
        only_workflows(page)
        assert not errors and not any(method != 'GET' for method, _ in calls)
    finally: context.close()


def test_empty_workflows_explains_required_access_without_falling_back_to_overview(customer_flow, browser):
    x = customer_flow
    with x.s.identity.tx() as db:
        db.execute('UPDATE customer_workspace_links SET active=0 WHERE workspace_id=?', (x.ws,))
    context, page, errors, calls = entry_page(x, browser)
    try:
        page.goto('https://customer.test/customer/workflows')
        expect(page.locator('#status')).to_have_text('Create a workspace or accept an invitation to start a workflow.')
        only_workflows(page)
        expect(page.locator('#workflow-workspaces a')).to_have_count(0)
        assert not errors and not any(method != 'GET' for method, _ in calls)
    finally: context.close()


def test_expired_workflows_entry_returns_to_signin_without_private_data(customer_flow, browser):
    x = customer_flow; x.s.identity.logout(x.s.raw)
    context, page, errors, calls = entry_page(x, browser)
    try:
        page.goto('https://customer.test/customer/workflows')
        expect(page).to_have_url('https://customer.test/customer/sign-in')
        expect(page.locator('#workflow-workspaces')).to_have_count(0)
        assert 'Customer multi-step studio' not in page.locator('body').inner_text()
        assert not errors and not any(method != 'GET' for method, _ in calls)
    finally: context.close()


@pytest.mark.parametrize('mobile', [False, True])
def test_progress_sits_small_in_the_centre_for_clicks_and_hidden_for_background_and_errors(orgs, browser, mobile):
    client, context, page, errors, external, calls = account_page(orgs, browser, mobile=mobile)
    detail = '/api/customer-organizations/' + orgs.organization['id']
    held = []; page.route('**' + detail, lambda route: held.append(route))
    try:
        expect(page.locator('#workspace-progress')).to_be_hidden()
        with page.expect_request('**' + detail):
            page.evaluate('(path)=>{window.backgroundRead=window.workspaceUI.request(path)}', detail)
        expect(page.locator('#workspace-progress')).to_be_hidden()
        page.locator('#status').text_content()
        response = client.get(detail, headers={'Cookie': COOKIE + '=' + orgs.auths[0]['session_token']})
        assert response.status_code == 200
        held.pop().fulfill(status=response.status_code, body=response.content,
                           content_type='application/json')
        page.evaluate('async()=>{await window.backgroundRead}')
        for fail in (False, True):
            with page.expect_request('**' + detail):
                choose_workspace(page)
            progress = page.locator('#workspace-progress')
            expect(progress).to_be_visible()
            bounds = progress.bounding_box(); viewport = page.viewport_size
            # UI policy 11-01 (user decision): a small centred box that never covers the page or takes clicks.
            centre_x = bounds['x'] + bounds['width'] / 2; centre_y = bounds['y'] + bounds['height'] / 2
            assert abs(centre_x - viewport['width'] / 2) < 4 and abs(centre_y - viewport['height'] / 2) < 4
            assert bounds['width'] < viewport['width'] * 0.9 and bounds['height'] < 120
            assert progress.evaluate('e=>getComputedStyle(e).pointerEvents') == 'none'
            expect(page.locator('.org-choice').first).to_be_visible()
            page.emulate_media(reduced_motion='reduce')
            assert progress.locator('.workspace-spinner').evaluate('e=>getComputedStyle(e).animationName') == 'none'
            if not fail:
                PROOF.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(PROOF / ('centre-progress-mobile.png' if mobile else 'centre-progress-desktop.png')))
                page.locator('#workspace-theme').click()
                expect(page.locator('body')).to_have_attribute('data-theme','dark')
                page.screenshot(path=str(PROOF / ('centre-progress-mobile-dark.png' if mobile else 'centre-progress-desktop-dark.png')))
            held.pop().fulfill(status=503 if fail else response.status_code,
                               body=b'{}' if fail else response.content, content_type='application/json')
            expect(progress).to_be_hidden()
            expect(page.locator('.org-choice').first).to_be_enabled()
            if fail: expect(page.locator('#status')).to_contain_text('could not')
        assert not errors and not external
        assert not any(method != 'GET' for method, _ in calls)
    finally: context.close(); client.close()


def test_cancelled_unsaved_navigation_removes_progress_and_preserves_inputs(customer_flow, browser):
    x = customer_flow; context, page, errors, calls = entry_page(x, browser)
    try:
        page.goto('https://customer.test/customer/organizations/' + x.ws + '/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        manual(page)
        page.locator('#name').fill('Keep this unsaved workflow')
        dialogs = []
        def dismiss(dialog):
            dialogs.append(dialog.type); dialog.dismiss()
        page.once('dialog', dismiss)
        page.locator('.workspace-sidebar').get_by_role('link', name='Overview', exact=True).click()
        expect(page).to_have_url('https://customer.test/customer/organizations/' + x.ws + '/flows#workflow')
        expect(page.locator('#workspace-progress')).to_be_hidden()
        expect(page.locator('#name')).to_have_value('Keep this unsaved workflow')
        assert dialogs == ['beforeunload'] and not errors
        assert not any(method != 'GET' for method, _ in calls)
    finally: context.close()
