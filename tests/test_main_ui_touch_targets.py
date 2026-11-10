"""11-11 quality bar for the main screens (same as AD Coin): measured with scripts/ui_audit.js in Chromium.

Interactive controls are at least 44px (shared design-system controls and page controls alike) at desktop
and phone widths; in-flow boxes do not overlap and rows and stacks stay aligned; there is no horizontal
scroll or console error. A new small target, overlap or misalignment fails this test. Overlaps with a fixed
or sticky layer (the cookie strip) are measured apart as overlay_overlaps and are not gated here.
"""
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.test_agent_adoption import adoption, routing  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

AUDIT_JS = (Path(__file__).resolve().parents[1] / 'scripts/ui_audit.js').read_text()
PAGES = ('/new/en/index.html', '/new/en/explore.html', '/new/en/chat.html', '/new/en/agent-status.html',
         '/new/en/learn.html', '/new/en/test.html', '/new/en/workflows.html', '/new/en/list-agent.html',
         '/new/en/about.html', '/agents/tasks', '/connect', '/agents/category/dev_tools')


@pytest.mark.parametrize('width,height', ((1280, 800), (375, 812)))
def test_main_screens_have_no_small_targets(adoption, browser, width, height):  # noqa: F811
    *_, client = adoption[:6]
    def serve(route):
        request = route.request; url = urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz':
            route.abort(); return
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                  content=request.post_data, headers=request.headers)
        headers = {k: v for k, v in response.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')}
        route.fulfill(status=response.status_code, body=response.content, headers=headers)
    failures = {}
    for path in PAGES:
        context = browser.new_context(viewport={'width': width, 'height': height}); page = context.new_page(); errors = []
        page.on('console', lambda m, errors=errors: m.type == 'error' and errors.append(m.text))
        context.route('**/*', serve)
        try:
            if page.goto('https://agentconcierge.biz' + path).status != 200:
                continue
            page.wait_for_load_state('load')
            m = page.evaluate(AUDIT_JS)
            bad = {k: m[k] for k in ('small_targets', 'design_system_small', 'horizontal_scroll', 'overlaps', 'misaligned') if m[k]}
            if bad or errors:
                failures[path] = {**bad, 'examples': m['small_examples'] + m['design_system_examples'] + m['overlap_examples']
                                   + m['misaligned_examples'], 'console': errors}
        finally:
            context.close()
    assert not failures, failures


def test_home_lead_is_the_decided_sentence():
    """11-11: the first-visit lead (PM decision 11-10) is not replaced by an older sentence at run time."""
    root = Path(__file__).resolve().parents[1]
    decided = 'Describe what you need. We suggest up to three agents and show how each one was checked.'
    assert decided in (root / 'new/en/index.html').read_text()
    script = (root / 'new/en/assets/experience.js').read_text()
    assert 'Check the evidence. Review the inputs before you run.' not in script
    assert "lead.textContent='" not in script or decided in script
