"""Real Chromium checks preserve admin CSP and use isolated API/database state."""
import json
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway.store import Store
from tests.test_front_workflow_browser import browser

pytestmark = pytest.mark.usefixtures('rotated_bootstrap_admin')


@pytest.fixture
def admin_page(browser, tmp_path):
    store = Store(str(tmp_path / 'browser.sqlite3'))
    app = FastAPI()
    app.include_router(dashboard_router(store, str(tmp_path/'browser.sqlite3'), 'browser-system-token', None, ssl_manager=Mock(get_status=lambda: {})))
    client = TestClient(app, base_url='https://admin.test')
    context = browser.new_context(accept_downloads=True)
    external = []
    def serve(route):
        req = route.request
        url = urlsplit(req.url)
        if url.scheme == 'file':
            return route.continue_()
        if url.hostname != 'admin.test':
            external.append(req.url)
            return route.abort()
        response = client.request(req.method, url.path + ('?' + url.query if url.query else ''), content=req.post_data, headers=req.headers)
        route.fulfill(status=response.status_code, body=response.content, headers={k:v for k,v in response.headers.items() if k not in ('content-length','content-encoding','transfer-encoding')})
    context.route('**/*', serve)
    from agent_market.workspace_admin_events import migrate
    migrate(store,b'synthetic-security-browser-key32')
    page = context.new_page()
    page.on('dialog',lambda dialog:dialog.accept('Synthetic browser security reason'))
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('https://admin.test/admin/ui')
    page.locator('#adminLoginUsername').fill('sadmin')
    page.locator('#adminLoginPassword').fill('sadmin')
    page.locator('#adminLoginSubmitBtn').click()
    pytest.importorskip('playwright.sync_api').expect(page.locator('#adminLoginModal')).to_be_hidden()
    yield page, errors, external
    context.close()
    client.close()
    store._db.close()


@pytest.mark.parametrize('menu', ['overview','learn','explore','sns','visitors','agent_telemetry','security','register','test','test_reports','workflows','progress','agents','errors','needs','manage','payments','users','audit'])
def test_all_admin_menus_under_enforced_csp(admin_page, menu):
    page, errors, external = admin_page
    requests = []
    page.on('request', lambda request: requests.append(request.url))
    page.locator(f'[data-tab="{menu}"]').click()
    pytest.importorskip('playwright.sync_api').expect(page.locator(f'[data-panel="{menu}"]').first).to_be_visible()
    if menu == 'security':
        pytest.importorskip('playwright.sync_api').expect(page.locator('#secKpis')).not_to_be_empty()
        with page.expect_response('**/admin/api/security/status'):
            page.locator('#secRefreshBtn').click()
    page.wait_for_timeout(100)
    if menu == 'security':
        assert 'OpenSSL' not in page.locator('[data-panel="security"]').inner_text()
        assert not page.locator('#sslRenewBtn, #sslInfoGrid, #sslVerifyBox').count()
        assert not any('/admin/api/ssl' in url for url in requests)
    assert not errors
    assert not external


def test_markdown_does_not_create_hostile_elements(admin_page):
    page, errors, _ = admin_page
    attack = '<img src=x onerror="window.__adminXss=1"><svg onload="window.__adminXss=1"><a href="javascript:window.__adminXss=1">x</a></svg>'
    page.evaluate('attack => {const host=document.createElement("div"); host.id="audit-markdown";host.innerHTML=renderMarkdown(attack);document.body.append(host)}', attack)
    assert page.locator('#audit-markdown img, #audit-markdown svg, #audit-markdown a').count() == 0
    assert page.locator('#audit-markdown').text_content() == attack
    assert page.evaluate('window.__adminXss || 0') == 0
    assert not errors


def test_workflow_attribute_injection_is_escaped(admin_page):
    page, errors, _ = admin_page
    attack = 'n" data-evil="yes" onpointerenter="window.__adminXss=1'
    page.locator('[data-tab="workflows"]').click()
    page.evaluate('''attack => {
      canvasGraph = {nodes:[{id:attack,type:'mcp',kind:'mcp',name:attack,position:{x:'0px;" data-coordinate="evil',y:100}}],edges:[]};
      renderCanvas();
    }''', attack)
    assert page.locator('[data-evil], [data-coordinate]').count() == 0
    assert page.evaluate('window.__adminXss || 0') == 0
    assert not errors


def test_csp_blocks_unapproved_script_and_event_handler(admin_page):
    page, errors, _ = admin_page
    page.evaluate('''() => {
      const script = document.createElement('script');script.textContent='window.__adminXss=1';document.body.append(script);
      const el = document.createElement('button');el.setAttribute('onclick','window.__adminXss=1');document.body.append(el);el.click();
    }''')
    assert page.evaluate('window.__adminXss || 0') == 0
    # The fixed callback registry remains functional with strict script-src-attr.
    page.locator('[data-tab="security"]').click()
    assert page.evaluate('typeof ADMIN_EVENT_HANDLERS.h0') == 'function'
    with page.expect_response('**/admin/api/security/rate-multiplier') as changed:
        page.locator('#secMult05').click()
    assert changed.value.status == 200
    assert changed.value.json()['result']['multiplier'] == 0.5
    assert not errors


def test_export_handles_script_breakout(admin_page, tmp_path):
    page, errors, _ = admin_page
    attack = '</script><script>window.__adminXss=1</script><img src=x onerror="window.__adminXss=1">'
    html = page.evaluate('''attack => generateStandaloneAppHtml({id:1,nodes:[],edges:[],steps:[]},{workflow_id:1,title:attack,description:attack,api_origin:"https://agentconcierge.biz"})''', attack)
    path = tmp_path/'admin-export.html'
    path.write_text(html)
    page.goto(path.as_uri())
    assert page.evaluate('window.__adminXss || 0') == 0
    assert page.locator('img').count() == 0
    assert not errors
