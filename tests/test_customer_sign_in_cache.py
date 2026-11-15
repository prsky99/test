"""/customer/sign-in as a page the edge may keep (PM 11-16 04:3x).

The same bytes for everyone: no nonce, its styles in one content-addressed stylesheet, its inline scripts allowed by
sha256, public cache headers. Nothing personal is in it (status and providers are fetched after it opens). A browser
test checks the page still styles itself and runs its script under the new CSP."""
import base64
import hashlib
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_market import customer_sign_in_cache as sc
from agent_market.customer_identity_service import router_for
from tests.test_customer_identity import customer  # noqa: F401 - fixture
from tests.test_pearl_frontend import client  # noqa: F401 - fixture


def app_for(w):
    app = FastAPI()
    app.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core))
    return app


def test_same_bytes_for_everyone_with_hash_csp_and_one_stylesheet(customer):  # noqa: F811
    with TestClient(app_for(customer), base_url='https://agentconcierge.biz') as client:
        first, second = client.get('/customer/sign-in'), client.get('/customer/sign-in')
        assert first.status_code == 200 and first.text == second.text
        assert 'nonce=' not in first.text and '<style' not in first.text
        assert first.headers['cache-control'] == sc.BROWSER_CACHE
        assert first.headers['cloudflare-cdn-cache-control'] == sc.EDGE_CACHE
        assert first.headers['x-robots-tag'].startswith('noindex')
        policy = first.headers['content-security-policy']
        assert "'nonce-" not in policy and "frame-ancestors 'none'" in policy and "style-src 'self'" in policy
        for body in re.findall(r'<script>(.*?)</script>', first.text, re.S):
            digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
            assert "'sha256-" + digest + "'" in policy
        href = re.search(r'<link rel="stylesheet" href="(/customer/assets/sign-in\.[0-9a-f]{16}\.css)">', first.text).group(1)
        css = client.get(href)
        assert css.status_code == 200 and css.headers['content-type'].startswith('text/css')
        assert 'immutable' in css.headers['cache-control'] and len(css.text) > 100_000
        assert client.get('/customer/assets/sign-in.0000000000000000.css').status_code == 404
        # nothing personal: the page reads its state after it opens, and another visitor with cookies gets the same bytes
        assert '/api/customer-auth/status' in first.text
        with TestClient(app_for(customer), base_url='https://agentconcierge.biz') as other:
            other.cookies.set('customer_session', 'x' * 43)
            assert other.get('/customer/sign-in').text == first.text
        # the next destination is part of the address, so it stays per URL and safe
        nxt = client.get('/customer/sign-in?next=/customer/plan').text
        assert '/customer/plan' in nxt


def test_stylesheet_is_found_by_a_process_that_has_not_rendered_the_page(customer):  # noqa: F811
    with TestClient(app_for(customer), base_url='https://agentconcierge.biz') as client:
        href = re.search(r'href="(/customer/assets/sign-in\.([0-9a-f]{16})\.css)"', client.get('/customer/sign-in').text)
        sc._css.clear()                                     # another process: nothing kept yet
        assert client.get(href.group(1)).status_code == 200


def test_page_styles_itself_and_runs_under_the_new_policy(customer):  # noqa: F811
    import pytest
    playwright = pytest.importorskip('playwright.sync_api')
    from urllib.parse import urlsplit
    client = TestClient(app_for(customer), base_url='https://agentconcierge.biz')
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context()
        violations = []

        def serve(route):
            url = urlsplit(route.request.url)
            r = client.request(route.request.method, url.path + ('?' + url.query if url.query else ''))
            route.fulfill(status=r.status_code, body=r.content,
                          headers={k: v for k, v in r.headers.items() if k not in ('content-length', 'content-encoding')})
        context.route('**/*', serve)
        page = context.new_page()
        page.on('console', lambda m: violations.append(m.text) if 'Content Security Policy' in m.text else None)
        page.goto('https://agentconcierge.biz/customer/sign-in')
        playwright.expect(page.locator('#status')).not_to_have_text('Checking sign-in availability.')
        assert page.evaluate("getComputedStyle(document.querySelector('main')).borderRadius") != '0px'
        assert violations == []
        context.close()
        browser.close()



def test_front_app_keeps_the_public_headers_and_cookies_still_get_no_store(client):  # noqa: F811
    from tests.test_direct_sign_in_links import published
    with published(client, True) as site:
        r = site.get('/customer/sign-in', headers={'Accept': 'text/html'})
        assert r.status_code == 200 and r.headers['cache-control'] == sc.BROWSER_CACHE, r.headers.get('cache-control')
        assert r.headers.get('cloudflare-cdn-cache-control') == sc.EDGE_CACHE
        href = re.search(r'href="(/customer/assets/sign-in\.[0-9a-f]{16}\.css)"', r.text).group(1)
        css = site.get(href)                     # no sign-in asked for the page's own stylesheet
        assert css.status_code == 200 and 'immutable' in css.headers['cache-control']
        signed = site.get('/customer/sign-in', headers={'Accept': 'text/html', 'Cookie': 'customer_session=x'})
        assert signed.status_code == 200 and signed.text == r.text
