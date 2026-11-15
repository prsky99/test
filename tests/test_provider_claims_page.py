"""Provider claim screens (growth team, 11-19 bundle) against a stand-in of the agent team's API.

Before the tables exist the API answers available false and the page says it is not open and shows no start control.
With the API open: start for one agent, see the one-time instructions, a failed check shows its plain reason, withdraw.
Server text is only ever set as text (an answer carrying markup shows as characters). No real API or network is used."""
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from agent_market import customer_provider_claims_view as view

playwright = pytest.importorskip("playwright.sync_api")
expect = playwright.expect  # locator waits: the page CSP blocks string evaluation (wait_for_function)


def stand_in(available):
    app = FastAPI()
    app.include_router(view.provider_claims_page_router())
    calls = []

    @app.get('/api/customer-auth/session')
    def session():
        return {'session': {'csrf_token': 'csrf-1'}}

    @app.get(view.BASE)
    def listing():
        return {'ok': True, 'available': available,
                'items': [{'claim_id': 'c0', 'origin': 'https://a.example', 'status': 'verified', 'resource_id': 7,
                           'expires': '2026-12-15'}] if available else []}

    @app.post(view.BASE)
    async def prepare(request: Request):
        calls.append(('prepare', request.headers.get('x-customer-csrf'), await request.json()))
        return JSONResponse({'ok': True, 'claim_id': 'c1', 'origin': 'https://a.example', 'expires': '2026-11-16',
                             'nonce': 'n' * 8, 'instructions': {
                                 'publish_at': 'https://a.example/.well-known/agentvalcon-claim.json',
                                 'content': {'profile': 'agentvalcon-provider-claim-v1', 'claim': 'c1', 'nonce': 'n' * 8},
                                 'notes': 'Serve exactly this JSON with HTTP 200, no redirect, at most 4 KiB.'}}, status_code=201)

    @app.post(view.BASE + '/c1/verify')
    def verify():
        calls.append(('verify',))
        return {'ok': True, 'status': 'pending', 'outcome': 'value_mismatch'}

    @app.post(view.BASE + '/c1/withdraw')
    def withdraw():
        calls.append(('withdraw',))
        return {'ok': True}

    @app.get(view.BASE + '/resources/7')
    def record():
        return {'ok': True, 'health': '<b>healthy</b>', 'retest_queue': {'position': 3, 'of': 40},
                'note': 'Verification never changes grades, ranks or test results.'}

    return TestClient(app), calls


@pytest.fixture(scope='module')
def browser():
    with playwright.sync_playwright() as runtime:
        b = runtime.chromium.launch()
        yield b
        b.close()


def open_page(browser, client, path):
    context = browser.new_context()

    def serve(route):
        url = urlsplit(route.request.url)
        if url.hostname != 'agentconcierge.biz':
            route.abort()
            return
        r = client.request(route.request.method, url.path + ('?' + url.query if url.query else ''),
                           content=route.request.post_data, headers=dict(route.request.headers))
        route.fulfill(status=r.status_code, body=r.content,
                      headers={k: v for k, v in r.headers.items() if k not in ('content-length', 'content-encoding')})
    context.route('**/*', serve)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('https://agentconcierge.biz' + path, wait_until='load')
    return context, page, errors


def test_before_the_tables_exist_it_says_not_open(browser):
    client, calls = stand_in(False)
    context, page, errors = open_page(browser, client, '/customer/provider-claims?agent=7')
    try:
        expect(page.locator('#status')).to_have_text(view.MESSAGES['provider_claims_not_available'])
        assert page.locator('#start').is_hidden() and calls == [] and errors == []
    finally:
        context.close()


def test_start_publish_check_and_withdraw(browser):
    client, calls = stand_in(True)
    context, page, errors = open_page(browser, client, '/customer/provider-claims?agent=7')
    try:
        page.wait_for_selector('#prepare:not([disabled])')
        assert 'Verified' in page.locator('#claims').inner_text()
        page.click('#prepare')
        page.wait_for_selector('#publish:not([hidden])')
        assert '/.well-known/agentvalcon-claim.json' in page.locator('#publishWhere').inner_text()
        assert 'agentvalcon-provider-claim-v1' in page.locator('#publishWhat').inner_text()
        assert calls[0] == ('prepare', 'csrf-1', {'resource_id': 7, 'method': 'well_known'})
        page.click('#check')
        expect(page.locator('#status')).to_contain_text('does not match')
        page.click('#withdraw')
        expect(page.locator('#status')).to_have_text('Withdrawn.')
        page.locator('#claims button').first.click()
        expect(page.locator('#recordList')).to_contain_text('Position 3 of 40')   # the area shows first, data after
        text = page.locator('#recordList').inner_text()
        assert '<b>healthy</b>' in text and 'Position 3 of 40' in text   # markup from the server stays text
        assert page.locator('#recordNote').inner_text().startswith('Verification never changes')
        assert errors == []
    finally:
        context.close()


def test_agent_query_is_a_catalog_id_or_ignored():
    _, _, _, script = view.page_html_parts('7')
    assert 'AGENT="7"' in script
    for bad in ('0', '-1', '1e3', '<x>', '1234567890123'):
        assert 'AGENT=null' in view.page_html_parts(bad)[3], bad
