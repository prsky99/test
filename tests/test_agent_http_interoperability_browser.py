"""Chromium CORS enforcement over real TLS against a disposable local app."""
from urllib.parse import urlsplit

from agent_market.concierge.front import create_front_app
from scripts.notification_test_inbox import running_inbox
from tests.test_fast_single_recommendation import catalog  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


def test_browser_pages_get_anonymous_reads_but_only_trusted_origins_execute(catalog, browser, monkeypatch):
    """Since 2026-10-30 any page may open /mcp anonymously and call read-only tools; execution
    tools and /a2a keep the explicit origin list (see agent_http.PUBLIC_TRANSPORTS)."""
    _, front, _, _, _ = catalog
    trusted, untrusted = 'https://localhost:9443', 'https://localhost:9444'
    monkeypatch.setenv('AGENT_BROWSER_ORIGINS', trusted)
    # Reuse only the temporary TLS listener/certificate lifecycle, not the
    # inbox application's independent origin-denial middleware.
    monkeypatch.setattr('scripts.notification_test_inbox.create_inbox', lambda _: create_front_app(front))
    with running_inbox() as (host, origin, _):
        port = urlsplit(origin).port
        context = browser.new_context(ignore_https_errors=True)
        # Chromium separately gates loopback access; this is not a CORS grant.
        context.grant_permissions(['local-network-access'], origin=trusted)
        context.grant_permissions(['local-network-access'], origin=untrusted)
        page = context.new_page()
        diagnostics = []
        page.on('console', lambda message: diagnostics.append(message.text))
        page.on('requestfailed', lambda request: diagnostics.append(request.failure))
        def serve(route):
            url = urlsplit(route.request.url)
            if url.hostname == 'localhost':
                return route.fulfill(status=200, content_type='text/html', body='<html lang="en"><title>Isolated browser agent</title><p>Isolated browser agent</p></html>')
            if url.hostname != '127.0.0.1' or url.port != port:
                return route.abort()
            route.continue_()
        context.route('**/*', serve)
        script = '''async ([endpoint, message]) => {
            try {
                const response = await fetch(endpoint, {method: 'POST', credentials: 'omit',
                    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(message)});
                return {status: response.status, sessionVisible: Boolean(response.headers.get('Mcp-Session-Id'))};
            } catch (error) { return {blocked: true}; }
        }'''
        initialize = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25',
                      'capabilities': {}, 'clientInfo': {'name': 'IsolatedBrowserAgent', 'version': '1'}}}
        execute = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'call', 'arguments': {}}}
        try:
            page.goto(trusted + '/')
            assert page.evaluate(script, [origin + '/mcp', initialize]) == {'status': 200, 'sessionVisible': True}, diagnostics
            page.goto(untrusted + '/')
            # An anonymous visitor session: credentials are stripped, the session id stays readable.
            assert page.evaluate(script, [origin + '/mcp', initialize]) == {'status': 200, 'sessionVisible': True}, diagnostics
            assert page.evaluate(script, [origin + '/mcp', execute])['status'] == 403
            assert page.evaluate(script, [origin + '/a2a', {'jsonrpc': '2.0', 'id': 3, 'method': 'message/send', 'params': {}}]) == {'blocked': True}
        finally:
            context.close()
