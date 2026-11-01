"""Browser attack probes against every public menu and standalone exports."""

import json
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, clear_front_caches, create_front_app
from agent_market.gateway.store import Store
from tests.test_front_workflow_browser import browser


@pytest.fixture
def public_page(browser):
    clear_front_caches()
    client = TestClient(create_front_app(Front(Store(":memory:"))))
    context = browser.new_context(accept_downloads=True)
    def serve(route):
        req = route.request
        url = urlsplit(req.url)
        if url.scheme == "file":
            route.continue_()
            return
        if url.hostname != "agentconcierge.biz":
            route.abort()
            return
        res = client.request(req.method, url.path + ("?" + url.query if url.query else ""),
            content=req.post_data, headers={"accept": req.headers.get("accept", ""),
                                          "content-type": req.headers.get("content-type", "")})
        # Preserve CSP and other security headers in the actual browser.
        headers = {k: v for k, v in res.headers.items() if k not in ("content-length", "content-encoding", "transfer-encoding")}
        route.fulfill(status=res.status_code, body=res.content, headers=headers)
    context.route("**/*", serve)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page, errors
    context.close()
    client.close()


@pytest.mark.parametrize("menu", ["overview", "learn", "explore", "test", "workflows", "register", "chat", "about"])
def test_public_menu_loads_with_real_security_headers(public_page, menu):
    page, errors = public_page
    response = page.goto("https://agentconcierge.biz/#" + menu)
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"]
    playwright = pytest.importorskip("playwright.sync_api")
    playwright.expect(page.locator(f'[data-panel="{menu}"]')).to_be_visible()
    assert not errors


def test_workflow_coordinate_attribute_xss_is_blocked(public_page):
    page, errors = public_page
    payload = '0px;" onpointerenter="window.__auditXss=1" data-pwn="'
    saved = {"version": 2, "name": "Imported graph", "nodes": [
        {"id": "n", "name": "Imported node", "type": "agent", "position": {"x": payload, "y": 160}}], "edges": []}
    page.add_init_script("localStorage.setItem('front_workflow_canvas', " + json.dumps(json.dumps(saved)) + ");")
    page.goto("https://agentconcierge.biz/#workflows")
    page.locator("#fn-n").dispatch_event("pointerenter")
    assert page.evaluate("window.__auditXss || 0") == 0
    assert page.locator("#fn-n").get_attribute("onpointerenter") is None
    assert not errors


def test_registry_and_chat_html_are_rendered_as_text(public_page):
    page, errors = public_page
    page.goto("https://agentconcierge.biz/#chat")
    attack = '<img src=x onerror="window.__auditXss=1">'
    page.evaluate("""attack => {
        appendChatBubble('bot', attack, {intent: attack, data: {recommendations: [
            {id: attack, kind: attack, name: attack, description: attack}]}});
        document.getElementById('drawer').classList.remove('hidden');
        renderDrawerAgent({id: attack, kind: attack, name: attack, description: attack,
          url: 'javascript:window.__auditXss=1', test_report: {content_md: attack}}, 'cached');
    }""", attack)
    assert page.locator("#drawerContent img").count() == 0
    assert page.locator('#drawerContent a[href^="javascript:"]').count() == 0
    assert page.evaluate("window.__auditXss || 0") == 0
    assert not errors


def test_downloaded_app_resists_script_breakout(public_page, tmp_path):
    from tests.workflow_package_helpers import open_hosted_package
    page, errors = public_page
    page.goto("https://agentconcierge.biz/#workflows")
    page.wait_for_function('frontTemplatesCache.some(t => t.id === frontActiveTemplateId)')
    attack = '</script><script>window.__auditXss=1</script><img src=x onerror="window.__auditXss=1">'
    # Client-side metadata cannot alter the server-owned package.
    page.evaluate("""attack => {
      const template = frontTemplatesCache.find(t => t.id === frontActiveTemplateId);
      template.name = attack; template.description = attack;
    }""", attack)
    with page.expect_download() as event:
        page.locator('#btnFrontExportApp').click()
    path = tmp_path / "webapp.zip"
    event.value.save_as(path)
    files = open_hosted_package(page, path)
    assert attack.encode() not in files['index.html']
    assert page.evaluate("window.__auditXss || 0") == 0
    assert page.locator("img").count() == 0
    assert page.locator("h1").text_content() == 'Daily Tech News & AI Research Digest'
    assert not errors


def test_csp_blocks_unapproved_scripts_and_event_attributes(public_page):
    page, errors = public_page
    page.goto("https://agentconcierge.biz/#workflows")
    page.evaluate("""() => {
      window.cspViolations = [];
      document.addEventListener('securitypolicyviolation', e => window.cspViolations.push(e.effectiveDirective));
      const script = document.createElement('script');
      script.textContent = 'window.__unapprovedScript = 1';
      document.body.appendChild(script);
      const button = document.createElement('button');
      button.setAttribute('onclick', 'window.__unapprovedHandler = 1');
      document.body.appendChild(button);
      button.click();
    }""")
    page.wait_for_function("window.cspViolations.length >= 2")
    assert page.evaluate("window.__unapprovedScript || 0") == 0
    assert page.evaluate("window.__unapprovedHandler || 0") == 0
    assert not errors


def test_delegated_legal_and_dynamic_inspector_controls(public_page):
    page, errors = public_page
    page.goto("https://agentconcierge.biz/#workflows")
    page.locator('.footer-link-btn[data-doc="contact"]').click()
    playwright = pytest.importorskip("playwright.sync_api")
    playwright.expect(page.locator("#legalModal")).to_be_visible()
    page.locator("#legalModal").evaluate("el => el.close()")
    if page.locator('.ux-canvas-editor').count():
        page.locator('.ux-canvas-editor > summary').click()
    page.locator("#frontWfNodesLayer .wf-node").nth(1).get_by_text("Edit", exact=True).click()
    page.locator("#inspNodeName").fill("Edited safely")
    playwright.expect(page.locator("#frontWfNodesLayer")).to_contain_text("Edited safely")
    assert not errors
