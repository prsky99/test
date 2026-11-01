"""Expired real customer handlers must remove previously rendered private UI."""
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect
import re

from agent_market.customer_identity_service import COOKIE
from tests.test_customer_authoring import authoring  # noqa: F401
from tests.test_customer_typed_authoring import customer_flow, save_run  # noqa: F401

# Sign-in may carry a same-site return path back to the customer area, never an external target.
SIGN_IN = re.compile(r'^https://customer\.test/customer/sign-in(\?next=%2Fcustomer%2F[^&#]*)?$')
from tests.test_workspace_release_v2 import release_world  # noqa: F401
from tests.test_workspace_execution_api import private_api  # noqa: F401
from tests.test_workspace_typed_release import typed_release_world  # noqa: F401
from tests.test_workspace_typed_flows import typed_world, routing  # noqa: F401
from tests.test_customer_organizations import orgs  # noqa: F401
from tests.test_customer_organizations_browser import account_page
from tests.test_customer_authoring_browser import open_page
from tests.test_front_workflow_browser import browser  # noqa: F401


def test_expired_single_task_session_redirects_without_retaining_private_draft(authoring, browser):
    x = authoring
    context, page, errors, external = open_page(x, browser)
    try:
        assert page.locator('#draft option').count()
        x.identity.logout(x.raw_cookie)
        page.locator('#refresh').click()
        expect(page).to_have_url(SIGN_IN)
        expect(page.get_by_role('heading', name='Your workspace', exact=True)).to_be_visible()
        assert page.locator('#draft,#review,#history').count() == 0
        assert not external
        assert not [error for error in errors if not error.startswith('401:')]
    finally:
        context.close()


def test_expired_typed_session_discards_results_and_never_dispatches(customer_flow, browser):
    x = customer_flow
    flow, _ = save_run(x)
    context = browser.new_context()
    context.set_offline(True)
    context.add_cookies([{'name': COOKIE, 'value': x.s.raw, 'url': 'https://customer.test',
                         'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def handler(route):
        req = route.request
        url = urlsplit(req.url)
        assert url.hostname == 'customer.test'
        response = x.client.request(req.method, url.path+('?'+url.query if url.query else ''), headers=req.headers,
                                    content=req.post_data, follow_redirects=False)
        route.fulfill(status=response.status_code, body=response.content,
                      headers={k: v for k, v in response.headers.items()
                               if k not in ('set-cookie', 'content-length', 'content-encoding', 'transfer-encoding')})

    context.route('**/*', handler)
    try:
        page.goto('https://customer.test/customer/organizations/' + x.ws + '/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        page.locator('#human-nav-library').click()
        page.locator('#workflow-cards .workflow-card').first.click()
        expect(page.locator('#workflow-state')).to_contain_text(flow['name'])
        expect(page.locator('#results')).to_contain_text('Current documentation')
        before = len(x.w.calls)
        x.s.identity.logout(x.s.raw)
        page.locator('#human-refresh').click()
        expect(page).to_have_url(SIGN_IN)
        assert page.locator('#results,#proposal,#saved').count() == 0
        assert flow['name'] not in page.locator('body').inner_text()
        assert len(x.w.calls) == before and not errors
        proof = Path('reports/workspace-security-audit-2026-10-21/screenshots')
        proof.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(proof / 'session-expiry-fixed-isolated.png'), full_page=True)
    finally:
        context.close()


def test_expired_organization_session_removes_account_and_member_details(orgs, browser):
    w = orgs
    client, context, page, errors, external, requests = account_page(w, browser)
    try:
        expect(page.locator('#reference')).to_have_text(w.customers[0].customer_id)
        page.locator('#organization-settings > summary').click()
        page.locator('#archive').click()
        expect(page.locator('#confirm')).to_be_visible()
        page.locator('#confirm').evaluate("dialog => { dialog.returnValue = 'confirm'; }")
        w.core.logout(w.auths[0]['session_token'])
        page.evaluate("() => { void window.workspaceUI.request('/api/customer-auth/session'); }")
        expect(page).to_have_url(SIGN_IN)
        assert page.locator('#reference,#members,#drafts').count() == 0
        assert w.organization['name'] not in page.locator('body').inner_text()
        assert not any(method == 'POST' and path.endswith('/archive') for method, path in requests)
        assert not errors and not external
    finally:
        context.close()
        client.close()
