"""Offline Chromium organization UI backed by isolated real API handlers."""
from urllib.parse import urlsplit
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect
import pytest

from agent_market.customer_identity_service import COOKIE, router_for
from tests.test_customer_organizations import orgs
from tests.test_front_workflow_browser import browser


def account_page(w, browser, index=0, mobile=False):
    app = FastAPI()
    app.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core, admin=False))
    from agent_market.customer_credit_service import router_for as credit_routes
    app.include_router(credit_routes(w.core, w.access))
    client = TestClient(app, base_url='https://customer.test')
    context = browser.new_context(viewport={'width': 390 if mobile else 1280, 'height': 844 if mobile else 900})
    context.set_offline(True)
    context.add_cookies([{'name': COOKIE, 'value': w.auths[index]['session_token'],
        'url': 'https://customer.test', 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
    page = context.new_page(); errors = []; unexpected = []; requests = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route_handler(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'customer.test':
            unexpected.append(request.url); route.abort(); return
        requests.append((request.method, url.path))
        result = client.request(request.method, url.path + ('?' + url.query if url.query else ''), content=request.post_data,
                                headers=request.headers, follow_redirects=False)
        if result.status_code == 404: errors.append('Unexpected API path: ' + url.path)
        route.fulfill(status=result.status_code, body=result.content,
                      headers={key: value for key, value in result.headers.items()
                               if key not in ('set-cookie', 'content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', route_handler)
    page.goto('https://customer.test/customer/organizations')
    expect(page.locator('#status')).to_have_text('Your organization access is current.')
    return client, context, page, errors, unexpected, requests


def choose_workspace(page):
    if not page.locator('.human-workspace-chooser').evaluate('(d)=>d.open'):
        page.locator('.human-workspace-chooser > summary').click()
    page.locator('.org-choice').first.click()


def navigate_workspace(page,label):
    if page.viewport_size['width']<=900:
        page.locator('#workspace-menu').click()
    if label in ('Members & invitations','Account','Plan & credits','Provider connections') and not page.locator('.workspace-manage').evaluate('(d)=>d.open'):
        page.locator('.workspace-manage > summary').click()
    page.locator('#workspace-navigation').get_by_role('link',name=label,exact=True).click()


def test_native_invitation_accept_owner_transfer_and_editor_draft_snapshot(orgs, browser):
    w = orgs
    from agent_market.customer_credits import CustomerCredits
    from tests.test_customer_credits import acceptance
    CustomerCredits(w.core).enroll(acceptance(),w.customers[0])
    owner = account_page(w, browser); member = None
    client, context, page, errors, unexpected, requests = owner
    try:
        choose_workspace(page)
        page.locator('#member-panel > summary').click()
        expect(page.locator('#owner-actions')).to_be_visible()
        page.locator('#recipient').fill(w.customers[1].customer_id)
        page.locator('#invite-role').select_option('owner')
        page.get_by_role('button', name='Send invitation', exact=True).click()
        expect(page.locator('#sent')).to_contain_text('pending')
        member = account_page(w, browser, 1)
        member_page = member[2]
        member_page.get_by_role('button', name='Accept', exact=True).click()
        expect(member_page.locator('#invitations')).to_contain_text('No pending invitations.')
        choose_workspace(member_page)
        expect(member_page.locator('#org-role')).to_have_text('owner access')
        page.reload(); expect(page.locator('#status')).to_have_text('Your organization access is current.')
        choose_workspace(page)
        page.locator('#member-panel > summary').click()
        page.get_by_role('button', name='Transfer ownership', exact=True).click()
        expect(page.locator('#confirm')).to_be_visible()
        page.locator('#confirm-yes').click()
        expect(page.locator('#org-role')).to_have_text('editor access')
        expect(page.locator('#owner-actions')).to_be_hidden()
        page.locator('#individual-panel > summary').click()
        page.locator('#draft-name').fill('Team research')
        page.get_by_role('button', name='Create empty draft', exact=True).click()
        # A new draft uses one credit: the exact charge is confirmed first, and Cancel sends nothing.
        expect(page.locator('#confirm')).to_be_visible()
        expect(page.locator('#confirm-copy')).to_contain_text('Saving uses 1 credit.')
        drafts_before = w.store._db.execute('SELECT COUNT(*) FROM workspace_drafts WHERE workspace_id=?', (w.organization['id'],)).fetchone()[0]
        page.get_by_role('button', name='Cancel', exact=True).click()
        expect(page.locator('#status')).to_have_text('Save cancelled. No credits were used.')
        assert w.store._db.execute('SELECT COUNT(*) FROM workspace_drafts WHERE workspace_id=?', (w.organization['id'],)).fetchone()[0] == drafts_before
        page.get_by_role('button', name='Create empty draft', exact=True).click()
        page.get_by_role('button', name='Use 1 credit and save', exact=True).click()
        expect(page.locator('#drafts')).to_contain_text('Team research')
        page.get_by_role('button', name='Edit draft', exact=True).click()
        expect(page.locator('#draft-editor')).to_be_visible()
        page.locator('#edit-draft-name').fill('Updated team research')
        page.get_by_role('button', name='Save draft', exact=True).click()
        # Changes before the first download share the draft's credit, so no charge is confirmed.
        expect(page.locator('#drafts')).to_contain_text('Updated team research')
        expect(page.locator('#confirm')).to_be_hidden()
        Path('reports/workspace-human-centered-2026-10-25').mkdir(parents=True, exist_ok=True)
        page.screenshot(path='reports/workspace-human-centered-2026-10-25/editor-desktop.png', full_page=True)
        snapshot_button = page.get_by_role('button', name='Save snapshot', exact=True)
        with page.expect_response('**/snapshots') as snapshot_response:
            snapshot_button.click()
        assert snapshot_response.value.status == 200
        expect(snapshot_button).to_be_enabled()
        assert w.store._db.execute('SELECT COUNT(*) FROM workspace_versions WHERE workspace_id=?', (w.organization['id'],)).fetchone()[0] == 1
        page.locator('#organization-settings > summary').click()
        page.get_by_role('button', name='Leave workspace', exact=True).click()
        page.locator('#confirm-yes').click()
        expect(page.locator('#org-actions')).to_be_hidden()
        assert not errors and not unexpected and not member[3] and not member[4]
        assert not any('/admin/' in path for _, path in requests)
    finally:
        context.close(); client.close()
        if member: member[1].close(); member[0].close()


def test_native_mobile_xss_safety_and_explicit_account_withdrawal(orgs, browser):
    w = orgs; client, context, page, errors, unexpected, requests = account_page(w, browser, mobile=True)
    try:
        page.locator('.human-workspace-chooser > summary').click()
        page.locator('#create-organization > summary').click()
        page.locator('#org-name').fill('<img src=x onerror=alert(1)>')
        page.get_by_role('button', name='Create workspace', exact=True).click()
        expect(page.locator('#org-title')).to_have_text('<img src=x onerror=alert(1)>')
        assert page.locator('img').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        if page.locator('#account').is_hidden():navigate_workspace(page,'Account')
        if not page.locator('#delete').is_visible():
            page.locator('#account-removal > summary').click()
        page.get_by_role('button', name='Delete account', exact=True).click()
        expect(page.locator('#confirm')).to_be_visible()
        Path('reports/workspace-human-centered-2026-10-25').mkdir(parents=True, exist_ok=True)
        page.screenshot(path='reports/workspace-human-centered-2026-10-25/withdrawal-mobile.png', full_page=True)
        page.locator('#confirm-yes').click()
        expect(page.locator('#status')).to_have_text('Type DELETE to confirm account deletion.')
        assert w.core.actor(w.auths[0]['session_token'])
        if page.locator('#account').is_hidden():navigate_workspace(page,'Account')
        if not page.locator('#delete').is_visible():
            page.locator('#account-removal > summary').click()
        page.get_by_role('button', name='Delete account', exact=True).click()
        page.locator('#delete-word').fill('DELETE')
        page.locator('#archive-owned').check()
        page.locator('#confirm-yes').click()
        page.wait_for_url('**/customer/sign-in')
        assert w.store._db.execute('SELECT active FROM customer_identities WHERE id=?', (w.customers[0].customer_id,)).fetchone()[0] == 0
        assert not errors and not unexpected
        assert any(method == 'POST' and path.endswith('/account/delete') for method, path in requests)
    finally:
        context.close(); client.close()


@pytest.mark.parametrize('mobile', [False, True])
def test_sidebar_tracks_one_current_page_through_navigation(orgs, browser, mobile):
    client, context, page, errors, unexpected, requests = account_page(orgs, browser, mobile=mobile)
    sidebar = page.locator('#workspace-navigation')
    active = sidebar.locator('a[aria-current="page"]')
    proof = Path('reports/workspace-human-centered-2026-10-25')
    proof.mkdir(parents=True, exist_ok=True)
    try:
        expect(active).to_have_count(1)
        expect(active).to_have_text('Overview')
        # An asynchronous organization selection changes URLs, not the current page.
        choose_workspace(page)
        expect(sidebar.locator('[data-workspace-section=flows]')).to_have_attribute(
            'href', '/customer/organizations/' + orgs.organization['id'] + '/flows')
        expect(active).to_have_count(1)
        expect(active).to_have_text('Overview')
        expect(page.locator('#workspace-progress')).to_be_hidden()
        page.screenshot(path=str(proof / ('overview-mobile.png' if mobile else 'overview-desktop.png')))
        for label in ('Members & invitations', 'Account', 'Overview'):
            navigate_workspace(page,label)
            expect(active).to_have_count(1)
            expect(active).to_have_text(label)
        page.go_back()
        expect(active).to_have_count(1)
        expect(active).to_have_text('Account')
        page.go_forward()
        expect(active).to_have_count(1)
        expect(active).to_have_text('Overview')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors and not unexpected
        assert not any(method == 'POST' for method, _ in requests)
    finally:
        context.close(); client.close()
