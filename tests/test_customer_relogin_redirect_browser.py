"""Real HTTPS redirects after session expiry, with isolated identity providers."""
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import socket
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from playwright.sync_api import expect
import pytest
import uvicorn

from agent_market.customer_identity_service import router_for
from tests.test_customer_identity import customer, github_world  # noqa: F401
from tests.test_front_workflow_browser import browser  # noqa: F401


@pytest.mark.parametrize('provider', ['google', 'github'])
def test_workflow_session_expiry_relogin_keeps_real_cross_site_redirect(customer, browser, tmp_path, provider):
    w = customer
    github_world(w)
    app = FastAPI()
    app.include_router(router_for(w.store, b'synthetic-customer-key-32bytes!!!', identity=w.core, admin=False))
    observations = []

    @app.middleware('http')
    async def record_metadata(request, call_next):
        response = await call_next(request)
        observations.append({'path': request.url.path, 'site': request.headers.get('sec-fetch-site'),
                             'mode': request.headers.get('sec-fetch-mode'),
                             'dest': request.headers.get('sec-fetch-dest'), 'status': response.status_code})
        return response

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Isolated customer test')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
            .sign(key, hashes.SHA256()))
    key_path, cert_path = tmp_path / 'test.key', tmp_path / 'test.crt'
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    key_path.chmod(0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    base = 'https://127.0.0.1:' + str(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, ssl_keyfile=str(key_path), ssl_certfile=str(cert_path),
                                           log_level='error', access_log=False, lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def restrict_network(route):
        url = urlsplit(route.request.url)
        if route.request.url.startswith(base + '/'):
            route.continue_()
            return
        expected = 'accounts.google.com' if provider == 'google' else 'github.com'
        assert url.hostname == expected, 'Unexpected outbound browser request'
        query = parse_qs(url.query)
        if provider == 'google':
            w.state['nonce'] = query['nonce'][0]
        callback = '/api/customer-auth/' + ('callback' if provider == 'google' else 'github/callback')
        target = base + callback + '?' + urlencode({'state': query['state'][0], 'code': 'synthetic-code'})
        # The provider document is synthetic. Callback and its 303 landing are
        # actual HTTPS requests, so Chromium supplies its own Fetch Metadata.
        route.fulfill(status=200, content_type='text/html',
                      body='<script>location.assign(' + json.dumps(target) + ')</script>')

    context.route('**/*', restrict_network)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started
        page.goto(base + '/customer/sign-in')
        page.locator('#' + provider).click()
        expect(page).to_have_url(base + '/customer/workspaces')
        expect(page.locator('#status')).to_contain_text('You are signed in.')
        page.locator('.workspace-sidebar').get_by_role('link', name='Workflows', exact=True).click()
        expect(page).to_have_url(base + '/customer/workflows')
        expect(page.locator('#status')).to_have_text('Create a workspace or accept an invitation to start a workflow.')
        with w.core.tx() as db:
            db.execute('UPDATE customer_sessions SET expires=0')
        page.reload()
        expect(page).to_have_url(base + '/customer/sign-in')
        expect(page.locator('#' + provider)).to_be_enabled()
        page.locator('#' + provider).click()
        expect(page).to_have_url(base + '/customer/workspaces')
        expect(page.locator('#status')).to_contain_text('You are signed in.')
        assert 'Use the customer service origin.' not in page.locator('body').inner_text()
        landed = [item for item in observations if item['path'] == '/customer/workspaces']
        assert len(landed) == 2
        assert all(item == {'path': '/customer/workspaces', 'site': 'cross-site',
                            'mode': 'navigate', 'dest': 'document', 'status': 200} for item in landed)
        from pathlib import Path
        proof = Path('reports/workspace-relogin-2026-10-23')
        proof.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(proof / (provider + '-relogin-fixed.png')), full_page=True)
        (proof / (provider + '-redirect-metadata.json')).write_text(json.dumps(landed, indent=2) + '\n')
        assert not errors
    finally:
        context.close()
        server.should_exit = True
        thread.join(15)
        sock.close()
        w.github_http.close()
        assert not thread.is_alive(), 'Isolated HTTPS server must exit'
