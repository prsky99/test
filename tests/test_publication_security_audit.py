"""Publication-wide security boundaries and hostile provider output in Chromium.

Only isolated application data and intercepted local handlers are used. Real
providers, accounts, notifications and production mutations are unavailable.
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, clear_front_caches, create_front_app
from agent_market.gateway.store import Store
from tests.test_front_workflow_browser import browser as browser_fixture

browser = browser_fixture

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'new/en-manifest.json').read_text())
PAGES = sorted(set(MANIFEST['live_pages']) | set(MANIFEST['native_account_pages']) |
               set(MANIFEST['presentation_only_pages']))
ATTACK = '<img src=x onerror="window.__publicationAttack=1"><svg onload="window.__publicationAttack=1">'


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.handlers = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script':
            self.scripts.append(attrs)
        self.handlers.extend(key for key in attrs if key.lower().startswith('on'))


@pytest.fixture
def isolated_publication(tmp_path):
    clear_front_caches()
    store = Store(str(tmp_path / 'publication-security.sqlite3'))
    front = Front(store)
    app = create_front_app(front, manage_book_lifecycle=False)
    client = TestClient(app, base_url='https://agentconcierge.biz')
    yield front, client
    client.close()
    front.book.close()
    store._db.close()
    clear_front_caches()


@pytest.mark.parametrize('filename', PAGES)
def test_every_published_page_has_fresh_nonces_and_no_inline_handlers(isolated_publication, filename):
    # 11-11 PM decision A: a page is the same bytes for everyone, so inline scripts are allowed by sha256
    # instead of a per-response nonce; live pages may sit at the edge for 60 s, every other page stays no-store.
    import base64
    import hashlib
    _, client = isolated_publication
    bodies = []
    for _ in range(2):
        response = client.get('/new/en/' + filename)
        assert response.status_code == 200
        headers = response.headers
        expected = 'public, max-age=0, s-maxage=300, stale-while-revalidate=600' if filename in MANIFEST['live_pages'] else 'no-store'
        assert headers['cache-control'] == expected
        assert 'set-cookie' not in headers
        assert headers['x-frame-options'] == 'DENY'
        assert headers['x-content-type-options'] == 'nosniff'
        assert headers['referrer-policy'] == 'no-referrer'
        assert 'access-control-allow-origin' not in headers
        csp = headers['content-security-policy']
        assert "script-src-attr 'none'" in csp and "frame-ancestors 'none'" in csp and "'nonce-" not in csp
        assert "'unsafe-inline'" not in csp.split('script-src', 1)[1].split(';', 1)[0]
        allowed = set(re.findall(r"'sha256-([A-Za-z0-9+/=]+)'", csp))
        parser = Scripts()
        parser.feed(response.text)
        assert parser.scripts and not parser.handlers
        for attrs, body in re.findall(r'<script\b([^>]*)>(.*?)</script>', response.text, re.S):
            if re.search(r'\bsrc=', attrs):
                assert not re.search(r'src="(?:https?:)?//', attrs), attrs     # files only from this origin ('self')
            elif not re.search(r'type="application/(?:ld\+)?json"', attrs):
                assert base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() in allowed
        bodies.append(response.text)
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize('path', [
    '/new/en/assets/%2e%2e/%2e%2e/AGENTS.md',
    '/new/en/assets/%252e%252e/%252e%252e/agentcon.env',
    '/new/en/assets/%2fetc%2fpasswd',
    '/new/en/assets/..%5c..%5cAGENTS.md',
    '/new/design/%2e%2e/agentcon.env',
    '/new/en/assets/operating.js.map',
    '/new/en/assets/application.dsn',
    '/new/en/en-manifest.json',
])
def test_encoded_paths_and_private_assets_are_not_served(isolated_publication, path):
    _, client = isolated_publication
    response = client.get(path)
    assert response.status_code in (403, 404)
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert 'postgresql://' not in response.text and 'Traceback' not in response.text


@pytest.fixture
def hostile_output_page(isolated_publication, browser):
    _, client = isolated_publication
    context = browser.new_context(viewport={'width':1440, 'height':1000}, reduced_motion='reduce')
    external = []

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'agentconcierge.biz':
            external.append(request.url)
            return route.abort()
        response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                  content=request.post_data, headers=request.headers)
        route.fulfill(status=response.status_code, body=response.content,
                      headers={k:v for k,v in response.headers.items()
                               if k not in ('content-length', 'content-encoding', 'transfer-encoding')})

    context.route('**/*', serve)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('https://agentconcierge.biz/#workflows')
    yield page, errors, external
    context.close()


@pytest.mark.parametrize('surface', ['workflow', 'chat', 'agent', 'history', 'readable'])
def test_provider_html_is_inert_on_published_result_surfaces(hostile_output_page, surface):
    page, errors, external = hostile_output_page
    target = page.evaluate('''({attack,surface}) => {
      if (surface === 'workflow') {
        showFrontRunOutputModal({status:'succeeded',duration_ms:1,node_results:[{
          name:attack,status:'succeeded',output:JSON.stringify({items:[{
            title:attack,summary:attack,url:'javascript:window.__publicationAttack=1'}]})}]});
        return '#frontWfRunModalBody';
      }
      if (surface === 'chat') {
        appendChatBubble('bot',attack,{data:{recommendations:[{id:1,name:attack,
          kind:'a2a',description:attack,url:'javascript:window.__publicationAttack=1'}]}});
        return '#chatMessages';
      }
      if (surface === 'agent') {
        renderDrawerAgent({id:1,name:attack,kind:'mcp',description:attack,
          health_status:'healthy',details:{value:attack}},'live');
        return '#drawerContent';
      }
      if (surface === 'history') {
        tbHistory=[{agent_name:attack,protocol:'mcp',action:attack,
          task_status:attack,timestamp:Date.now(),latency_ms:1,execution_succeeded:false}];
        updateTestbenchHistoryTable();
        return '#tbHistoryTbody';
      }
      const node=document.createElement('section');node.id='audit-readable';
      node.innerHTML=readableResultHtml({items:[{title:attack,summary:attack,
        url:'data:text/html,<script>window.__publicationAttack=1</script>'}]});
      document.body.append(node);return '#audit-readable';
    }''', {'attack':ATTACK, 'surface':surface})
    assert page.locator(target + ' img,' + target + ' script,' + target + ' iframe').count() == 0
    assert page.locator(target + ' [onerror],' + target + ' [onload]').count() == 0
    assert page.locator(target + ' a[href^="javascript:"],' + target + ' a[href^="data:"]').count() == 0
    assert page.evaluate('window.__publicationAttack || 0') == 0
    assert not errors and not external
