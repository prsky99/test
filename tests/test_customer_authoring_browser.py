"""Chromium task review/export uses isolated real handlers and no network."""
from urllib.parse import urlsplit
from pathlib import Path

from playwright.sync_api import expect

from agent_market.customer_identity_service import COOKIE
from tests.test_customer_authoring import authoring  # noqa: F401
from tests.test_workspace_release_v2 import release_world  # noqa: F401
from tests.test_workspace_execution_api import private_api  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


def open_page(x, browser):
    context = browser.new_context(accept_downloads=True)
    context.set_offline(True)
    context.add_cookies([{'name': COOKIE, 'value': x.raw_cookie, 'url': 'https://customer.test',
        'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
    page = context.new_page(); errors = []; external = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route_handler(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'customer.test':
            external.append(request.url); route.abort(); return
        response = x.customer_client.request(request.method, url.path, content=request.post_data,
            headers=request.headers, follow_redirects=False)
        if response.status_code >= 400:
            errors.append(str(response.status_code) + ':' + url.path)
        route.fulfill(status=response.status_code, body=response.content,
            headers={key: value for key, value in response.headers.items()
                if key not in ('content-length', 'content-encoding', 'transfer-encoding', 'set-cookie')})
    context.route('**/*', route_handler)
    page.goto('https://customer.test/customer/organizations/' + x.customer_ws + '/build')
    expect(page.locator('#status')).not_to_have_text('Checking your session.')
    assert page.locator('#status').inner_text() == 'Choose a current draft or create one reviewed task.', errors
    active = page.locator('.workspace-sidebar a[aria-current="page"]')
    expect(active).to_have_count(1)
    expect(active).to_have_text('Workflows')
    return context, page, errors, external


def test_customer_review_single_dispatch_release_and_exact_origin_download(authoring, browser, tmp_path):
    x = authoring; context, page, errors, external = open_page(x, browser)
    try:
        before = x.calls.count('tools/call')
        page.locator('#prepare').click()
        expect(page.locator('#review')).to_contain_text('Storage research')
        expect(page.locator('#run')).to_be_disabled()
        assert x.calls.count('tools/call') == before
        page.locator('#run-consent').check(); page.locator('#run').click()
        expect(page.locator('#history')).to_have_text('Task succeeded')
        assert x.calls.count('tools/call') == before + 1
        expect(page.locator('#release')).to_be_disabled()
        page.locator('#release-consent').check(); page.locator('#release').click()
        expect(page.locator('#revoke')).to_be_enabled()
        page.locator('#origin').fill('https://customer.example')
        page.locator('#deploy-consent').check(); page.locator('#deploy').click()
        expect(page.locator('#download button')).to_be_visible()
        with page.expect_download() as downloaded:
            page.locator('#download button').click()
        downloaded.value.save_as(tmp_path / 'reviewed-customer-app.zip')
        page.reload();expect(page.locator('#download button')).to_be_visible()
        assert x.calls.count('tools/call') == before + 1
        page.locator('#revoke').click()
        expect(page.locator('#download button')).to_have_count(0)
        assert not errors and not external
    finally:
        context.close()


def test_unknown_response_and_session_loss_do_not_silently_repeat(authoring, browser):
    x = authoring; context, page, errors, external = open_page(x, browser)
    try:
        page.locator('#prepare').click(); expect(page.locator('#review')).to_contain_text('Storage research')
        x.control['mode'] = 'timeout'
        page.locator('#run-consent').check(); page.locator('#run').click()
        expect(page.locator('#history')).to_have_text('Task unknown')
        expect(page.locator('#prepare')).to_be_disabled()
        calls = x.calls.count('tools/call')
        page.locator('#refresh').click()
        expect(page.locator('#prepare')).to_be_enabled()
        assert x.calls.count('tools/call') == calls
        x.identity.logout(x.raw_cookie)
        page.locator('#prepare').click()
        expect(page).to_have_url('https://customer.test/customer/sign-in')
        expect(page.locator('#run')).to_have_count(0)
        assert x.calls.count('tools/call') == calls
        assert not [error for error in errors if not error.startswith('401:')] and not external
    finally:
        context.close()


def test_unsupported_snapshot_is_explained_before_prepare_and_selection_recovers(authoring, browser):
    x = authoring
    draft = x.authoring.organizations.drafts.save_draft(x.customer_ws, {
        'name': 'Empty reviewed draft', 'description': '',
        'definition': {'nodes': [], 'edges': []}}, x.customer_principal)
    x.authoring.organizations.drafts.create_snapshot(x.customer_ws, draft['id'],
        {'draft_revision': draft['revision']}, x.customer_principal)
    context, page, errors, external = open_page(x, browser)
    requests = []
    page.on('request', lambda request: requests.append((request.method, request.url)))
    try:
        page.locator('#draft').select_option(draft['id'])
        expect(page.locator('#task-availability')).to_contain_text('does not contain one supported')
        expect(page.locator('#prepare')).to_be_disabled()
        expect(page.locator('#run')).to_be_disabled()
        assert not [url for method, url in requests if method == 'POST']
        proof = Path('reports/workspace-live-verification-2026-10-20/screenshots')
        proof.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(proof / '45-single-task-fixed-isolated.png'), full_page=True)
        before = x.calls.count('tools/call')
        page.locator('#draft').select_option(x.customer_args[1])
        expect(page.locator('#prepare')).to_be_enabled()
        expect(page.locator('#task-availability')).to_contain_text('available for one reviewed')
        page.locator('#prepare').click()
        expect(page.locator('#review')).to_contain_text('Storage research')
        assert x.calls.count('tools/call') == before
        assert not errors and not external
    finally:
        context.close()


def test_workspace_footer_targets_operating_documents(authoring, browser):
    context, page, errors, external = open_page(authoring, browser)
    try:
        footer = page.get_by_role('navigation', name='Service information')
        for name, route in [('Terms of Service', 'tos'), ('Privacy Policy', 'privacy'),
                            ('Accessibility', 'accessibility'), ('Contact', 'contact')]:
            expect(footer.get_by_role('link', name=name, exact=True)).to_have_attribute(
                'href', '/new/en/index.html#' + route)
        assert not errors and not external
    finally:
        context.close()
