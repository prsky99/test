"""Transport headroom must not abort or replay a completed bounded agent read."""
import time
from urllib.parse import urlsplit

from playwright.sync_api import expect

from tests.test_owned_data_agents_activation import operating  # noqa: F401
from tests.test_owned_data_agents import engine  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


def test_testbench_waits_for_response_transit_without_retrying_post(operating, browser):  # noqa: F811
    _, client, _, _, _ = operating
    context = browser.new_context()
    submissions = []

    def serve(route):
        request = route.request
        parsed = urlsplit(request.url)
        reply = client.request(request.method, parsed.path + ('?' + parsed.query if parsed.query else ''),
                               content=request.post_data,
                               headers={k: v for k, v in request.headers.items() if k in ('accept', 'content-type')})
        if parsed.path == '/api/test/execute':
            submissions.append(reply.json())
            # Execution already completed. Delayed network delivery must not
            # compete with the server's eight-second execution deadline.
            time.sleep(8.4)
        route.fulfill(status=reply.status_code, body=reply.content,
                      headers={k: v for k, v in reply.headers.items()
                               if k not in ('content-length', 'content-encoding', 'transfer-encoding')})

    context.route('**/*', serve)
    page = context.new_page()
    try:
        page.goto('https://agentconcierge.biz/#test')
        page.locator('.pearl-example-choice[data-recipe="package-metadata"]').click()
        expect(page.locator('#tbRunBtn')).to_be_enabled()
        page.locator('#tbRunBtn').click()
        expect(page.locator('#tbKpiStatus')).to_have_text('Completed', timeout=15000)
        assert len(submissions) == 1 and submissions[0]['execution_succeeded'] is True
        assert not submissions[0]['simulated']
    finally:
        context.close()
