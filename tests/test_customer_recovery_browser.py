"""Offline Chromium recovery controls use disposable customer API state."""
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from agent_market.customer_identity import _b64
from agent_market.customer_identity_service import COOKIE, router_for as identity_router
from agent_market.customer_recovery_service import router_for
from agent_market.workspace_access import _canonical
from tests.test_customer_recovery import recovery, prepare  # noqa: F401
from tests.test_customer_organizations import orgs  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


def open_page(w, browser, index):
    app = FastAPI()
    app.include_router(identity_router(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core, admin=False))
    app.include_router(router_for(w.recovery))
    client = TestClient(app, base_url='https://customer.test')
    context = browser.new_context(viewport={'width': 1280, 'height': 1000})
    context.set_offline(True)
    context.add_cookies([{'name': COOKIE, 'value': w.auths[index]['session_token'],
                         'url': 'https://customer.test', 'secure': True, 'httpOnly': True, 'sameSite': 'Lax'}])
    unexpected, errors = [], []
    def bridge(route):
        request = route.request; part = urlsplit(request.url)
        if part.hostname != 'customer.test':
            unexpected.append(request.url); route.abort(); return
        result = client.request(request.method, part.path, content=request.post_data,
                                headers=request.headers, follow_redirects=False)
        route.fulfill(status=result.status_code, body=result.content,
                      headers={key: value for key, value in result.headers.items()
                               if key not in ('set-cookie', 'content-length', 'content-encoding', 'transfer-encoding')})
    context.route('**/*', bridge)
    page = context.new_page(); page.on('pageerror', lambda value: errors.append(str(value)))
    page.goto('https://customer.test/customer/organizations/' + w.organization['id'] + '/recovery')
    return client, context, page, errors, unexpected


def test_requester_submits_dual_proofs_owner_can_contest_in_native_browser(recovery, browser):
    w = recovery; claim = prepare(w)
    target = open_page(w, browser, 1)
    owner = None
    try:
        _, _, page, errors, unexpected = target
        expect(page.locator('#owner')).to_be_hidden()
        page.get_by_label('Request reference', exact=True).fill(claim['id'])
        page.get_by_label('Offline key signature', exact=True).fill(_b64(w.offline.sign(_canonical(claim).encode())))
        page.get_by_label('Independent review signature', exact=True).fill(_b64(w.reviewer.sign(_canonical(claim).encode())))
        page.get_by_role('button', name='Submit reviewed proofs', exact=True).click()
        expect(page.locator('#request-state')).to_contain_text('Request status: pending')
        expect(page.locator('#owner-proof')).to_have_value('')
        expect(page.get_by_role('button', name='Complete recovery', exact=True)).to_be_disabled()
        owner = open_page(w, browser, 0); owner_page = owner[2]
        expect(owner_page.locator('#owner')).to_be_visible()
        expect(owner_page.locator('#pending')).to_contain_text('pending')
        owner_page.get_by_role('button', name='Contest request', exact=True).click()
        expect(owner_page.locator('#pending')).to_contain_text('No pending recovery requests.')
        page.get_by_role('button', name='Check request', exact=True).click()
        expect(page.locator('#request-state')).to_have_text('Request status: contested')
        Path('reports/workspace-prelaunch-2026-10-20').mkdir(parents=True, exist_ok=True)
        owner_page.screenshot(path='reports/workspace-prelaunch-2026-10-20/recovery-owner-desktop.png', full_page=True)
        assert not errors and not unexpected and not owner[3] and not owner[4]
    finally:
        target[1].close(); target[0].close()
        if owner:
            owner[1].close(); owner[0].close()
