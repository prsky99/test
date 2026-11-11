"""11-11 (PM stability): the protocol button groups arrive drawn, so Chat on a phone does not shift on load.

pearl-ui.js used to replace the protocol <select>s with button groups after the first paint; at 375 px the five
Chat buttons wrap to two rows and pushed the conversation down 56 px (CLS 0.027 with first-screen CSS, 0.055
without). The server now draws the same group; the script adopts it, so clicking still drives the select.
"""
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from agent_market.concierge.pearl_view import SEGMENTED, prerender_segmented
from tests.test_agent_adoption import adoption, routing  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CLS = """() => new Promise(done => { let v = 0; new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) v += e.value; })
  .observe({type: 'layout-shift', buffered: true}); setTimeout(() => done(v), 800); })"""


def test_labels_match_the_script():
    script = (ROOT / 'new/en/assets/pearl-ui.js').read_text()
    for sid, (label, labels) in SEGMENTED.items():
        call = re.search(r"segmented\(q\('#%s'\),'([^']+)',\{([^}]*)\}\)" % sid, script)
        assert call and call[1] == label
        assert dict(re.findall(r"(\w+):'([^']*)'", call[2])) == labels


def test_the_group_is_drawn_once_with_the_select_hidden():
    page = (ROOT / 'new/en/chat.html').read_text()
    once = prerender_segmented(page)
    assert prerender_segmented(once) == once  # a second pass changes nothing
    group = re.search(r'<div class="pearl-protocol-segmented" role="group" aria-label="Recommendation protocol" '
                      r'data-for="chatProtocol">(.*?)</div>', once)[1]
    assert re.findall(r'data-value="([^"]*)" aria-pressed="(true|false)"', group) == [
        ('auto', 'true'), ('any', 'false'), ('a2a', 'false'), ('mcp', 'false'), ('x402', 'false')]
    assert 'Auto · A2A → MCP' in group
    assert re.search(r'<select id="chatProtocol" class="input pearl-native-select" tabindex="-1" aria-hidden="true">', once)
    assert once.count('data-for="regKind"') == 1


def open_chat(browser, client, width):
    context = browser.new_context(viewport={'width': width, 'height': 812})

    def serve(route):
        url = urlsplit(route.request.url)
        if url.hostname != 'agentconcierge.biz':
            route.abort()
            return
        r = client.request(route.request.method, url.path + ('?' + url.query if url.query else ''),
                           content=route.request.post_data, headers=route.request.headers)
        headers = {k: v for k, v in r.headers.items() if k not in ('content-length', 'content-encoding', 'transfer-encoding')}
        route.fulfill(status=r.status_code, body=r.content, headers=headers)
    context.route('**/*', serve)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('https://agentconcierge.biz/new/en/chat.html', wait_until='load')
    return context, page, errors


@pytest.mark.parametrize('width', (375, 320))
def test_chat_on_a_phone_does_not_shift_and_the_buttons_still_work(adoption, browser, width):  # noqa: F811
    *_, client = adoption[:6]
    context, page, errors = open_chat(browser, client, width)
    try:
        shift = page.evaluate(CLS)
        groups = page.locator('#secChat .pearl-protocol-segmented').count()
        page.locator('#secChat .pearl-protocol-segmented button[data-value="mcp"]').click()
        state = page.evaluate("""() => ({value: document.querySelector('#chatProtocol').value,
          pressed: [...document.querySelectorAll('#secChat .pearl-protocol-segmented button[aria-pressed=true]')].map(b => b.dataset.value)})""")
    finally:
        context.close()
    assert not errors, errors[:2]
    assert shift < 0.001, shift
    assert groups == 1
    assert state == {'value': 'mcp', 'pressed': ['mcp']}
