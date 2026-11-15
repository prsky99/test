"""Every HTML page that links our own stylesheets lets the browser load them (11-15, PM gate request).

On 11-15 /advertise, /methodology, /methodology/changelog, /necklaces/<slug> and /ads/library linked
/new/en/assets/*.css but carried the default CSP (style-src 'unsafe-inline' only), so production showed them unstyled.
This walks every GET route of the assembled app (included routers too), asks for HTML, and fails when a page links a
same-origin stylesheet while its style-src has no 'self'. Routes that need data answer 404 here; the page-level tests
(test_growth_page_csp) cover the necklace and method pages with data."""
import re
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agent_market.concierge.front import Front, create_front_app
from agent_market.gateway.store import Store

SAMPLES = {'{rid}': '1', '{slug}': 'x', '{category}': 'research', '{kind}': 'mcp', '{id}': '1', '{name}': 'x'}


def routes(app, prefix=''):
    found = []
    for route in getattr(app, 'routes', None) or []:
        if hasattr(route, 'original_router'):        # FastAPI's lazily included router
            context = getattr(route, 'include_context', None)
            found += routes(route.original_router, prefix + (getattr(context, 'prefix', '') or ''))
        elif getattr(route, 'methods', None):
            found.append((prefix + route.path, route.methods))
        elif hasattr(getattr(route, 'app', None), 'routes'):
            found += routes(route.app, prefix + getattr(route, 'path', ''))
    return found


def test_pages_that_link_our_stylesheets_allow_them():
    app = create_front_app(Front(Store(str(Path(tempfile.mkdtemp()) / 'csp.db'))), workspace_access_enabled=True)
    client = TestClient(app)
    checked, broken = 0, []
    for path, methods in routes(app):
        if 'GET' not in methods or path.startswith(('/api/', '/mcp', '/a2a')):
            continue
        url = path
        for key, value in SAMPLES.items():
            url = url.replace(key, value)
        url = re.sub(r'\{[^}]+\}', 'x', url)
        try:
            r = client.get(url, headers={'accept': 'text/html'}, follow_redirects=False)
        except Exception:
            continue
        if 'text/html' not in r.headers.get('content-type', ''):
            continue
        checked += 1
        if re.search(r'<link[^>]+rel="stylesheet"[^>]+href="/', r.text):
            style = re.search(r"style-src ([^;]*)", r.headers.get('content-security-policy', ''))
            if not style or "'self'" not in style.group(1).split():
                broken.append((path, r.status_code, style.group(1) if style else None))
    assert checked >= 20, checked   # 25 HTML pages answer without data on 11-15
    assert broken == [], broken
