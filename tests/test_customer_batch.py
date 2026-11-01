"""11-01: reads a workspace page starts together travel as one request and keep their own answers."""
from tests.test_workspace_prelaunch_browser import browser, customer_flow, typed_release_world, typed_world, routing  # noqa: F401

def mounted(x):
    # The customer identity router now carries the batch route wherever the customer API is served.
    probe = x.client.get('/api/customer-batch', params={'p': '/api/customer-auth/session'}, headers=HEADERS)
    assert probe.status_code != 404, probe.text
    return x


HEADERS = {'Origin': 'https://customer.test', 'Sec-Fetch-Site': 'same-origin', 'Sec-Fetch-Mode': 'cors'}


def test_batch_returns_each_read_as_if_requested_alone(customer_flow):  # noqa: F811
    x = mounted(customer_flow)
    paths = ['/api/customer-auth/session', '/api/customer-organizations', '/api/customer-organizations/' + x.ws]
    direct = [x.client.get(path, headers=HEADERS) for path in paths]
    batch = x.client.get('/api/customer-batch', params=[('p', path) for path in paths], headers=HEADERS)
    assert batch.status_code == 200, batch.text
    answers = batch.json()['responses']
    assert [a['status'] for a in answers] == [r.status_code for r in direct]
    assert answers[1]['json'] == direct[1].json() and answers[2]['json'] == direct[2].json()
    assert answers[0]['json']['session']['csrf_token'] == direct[0].json()['session']['csrf_token']


def test_batch_refuses_other_paths_and_keeps_errors(customer_flow):  # noqa: F811
    x = mounted(customer_flow)
    for bad in ('/api/test/presets', '/api/customer-batch', '/admin/api/overview', '/api/customer-auth/begin',
                '/api/customer-organizations/../../admin'):
        assert x.client.get('/api/customer-batch', params={'p': bad}, headers=HEADERS).status_code == 400, bad
    assert x.client.get('/api/customer-batch', params=[('p', '/api/customer-organizations')] * 9,
                        headers=HEADERS).status_code == 400
    missing = x.client.get('/api/customer-batch', params={'p': '/api/customer-organizations/ws_' + '0' * 32},
                           headers=HEADERS).json()['responses'][0]
    assert missing['status'] in (403, 404)
    x.client.cookies.clear()
    signed_out = x.client.get('/api/customer-batch', params={'p': '/api/customer-organizations'}, headers=HEADERS)
    # Production's entry guard answers 401 for the batch itself; without it each read still reports 401.
    assert signed_out.status_code == 401 or signed_out.json()['responses'][0]['status'] == 401


def test_workflow_page_reads_arrive_in_one_request(customer_flow, browser):  # noqa: F811
    from playwright.sync_api import expect
    from tests.test_workspace_entry_progress_browser import entry_page
    x = mounted(customer_flow)
    context, page, errors, calls = entry_page(x, browser)
    try:
        page.goto('https://customer.test/customer/organizations/' + x.ws + '/flows')
        expect(page.locator('#status')).to_have_text('Review a workflow or inspect retained tests.')
        reads = [path for method, path in calls if path.startswith('/api/')]
        assert '/api/customer-batch' in reads
        # The opening reads share one round trip instead of five or six.
        assert len([path for path in reads if path != '/api/customer-batch']) <= 1, reads
        assert not errors
    finally:
        context.close()


def test_overview_reads_a_named_workspace_in_the_first_request(customer_flow, browser):  # noqa: F811
    from urllib.parse import parse_qs, urlsplit
    from playwright.sync_api import expect
    from tests.test_workspace_entry_progress_browser import entry_page
    x = mounted(customer_flow)
    context, page, errors, calls = entry_page(x, browser)
    batches = []
    page.on('request', lambda r: batches.append(parse_qs(urlsplit(r.url).query).get('p', []))
            if urlsplit(r.url).path == '/api/customer-batch' else None)
    try:
        page.goto('https://customer.test/customer/organizations?workspace=' + x.ws)
        expect(page.locator('#org-title')).to_have_text('Customer multi-step studio')
        assert batches and '/api/customer-organizations/' + x.ws in batches[0], batches
        sidebar = page.locator('.workspace-sidebar a[data-workspace-section="overview"]')
        page.goto('https://customer.test/customer/organizations/' + x.ws + '/flows')
        expect(sidebar).to_have_attribute('href', '/customer/organizations?workspace=' + x.ws)
        assert not errors
    finally:
        context.close()


def test_answers_stay_readable_behind_compression():
    """11-02: with GZip in front, replayed reads came back compressed and every opening page failed."""
    from fastapi import FastAPI
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.testclient import TestClient
    from agent_market.customer_batch import router_for
    app = FastAPI()
    app.add_middleware(GZipMiddleware, minimum_size=1)

    @app.get('/api/customer-sample')
    def sample():
        return {'items': ['x' * 50] * 40}
    app.include_router(router_for())
    client = TestClient(app)
    reply = client.get('/api/customer-batch', params=[('p', '/api/customer-sample')] * 2,
                       headers={'Accept-Encoding': 'gzip'})
    assert reply.status_code == 200 and reply.headers.get('content-encoding') == 'gzip'
    answers = reply.json()['responses']
    assert [a['json'] for a in answers] == [{'items': ['x' * 50] * 40}] * 2
