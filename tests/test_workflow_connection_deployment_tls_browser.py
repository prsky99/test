"""Native Chromium CORS over an isolated fixed-origin TLS CONNECT fixture.

The exported SDK bytes and logical gateway URL are unchanged. A loopback-only
proxy tunnels only that gateway to a private TLS fixture. Chromium trusts only
the fixture key through a process-local SPKI exception; no user trust is changed.
"""
from base64 import b64encode
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import select
import socket
import ssl
from threading import Thread
from urllib.parse import urlsplit
from zipfile import ZipFile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from playwright.sync_api import expect, sync_playwright

from tests.test_workflow_fallback import routing  # noqa: F401
from tests.test_workflow_typed_flow import typed_routing  # noqa: F401
from tests.test_workflow_publication_api import publication_api, published, H, ADMIN  # noqa: F401
from tests.test_workflow_connection_deployment_api import connected_api, export_body, admin_path  # noqa: F401


@contextmanager
def running_server(handler, tls=None):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    server.daemon_threads = True
    if tls is not None:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def certificate(directory):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Isolated connected SDK gateway')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('agentconcierge.biz')]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / 'certificate.pem', directory / 'key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_path.chmod(0o600)
    spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return cert_path, key_path, b64encode(hashlib.sha256(spki).digest()).decode()


def test_native_cors_and_fixed_gateway_sdk_over_loopback_tls(connected_api, tmp_path):
    rt, public, admin, calls, _ = connected_api
    wire, tunnels, files = [], [], {}

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def forward(self):
            assert self.path.startswith('/api/workflow-connection-apps-v13/')
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            headers = dict(self.headers)
            response = public.request(self.command, self.path, content=body or None, headers=headers)
            wire.append({'method': self.command, 'path': self.path, 'origin': self.headers.get('Origin'),
                         'status': response.status_code, 'cookie': self.headers.get('Cookie'),
                         'authorization': self.headers.get('Authorization'), 'body': body})
            self.send_response(response.status_code)
            for key, value in response.headers.items():
                if key.lower() not in ('content-length', 'transfer-encoding', 'connection', 'content-encoding'):
                    self.send_header(key, value)
            self.send_header('Content-Length', str(len(response.content)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(response.content)

        do_OPTIONS = do_POST = do_GET = forward

    class Host(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            name = path.removeprefix('/apps/connected/') or 'index.html'
            content = files.get(name)
            self.send_response(200 if content is not None else 404)
            self.send_header('Content-Type', 'application/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else 'text/html')
            self.send_header('Content-Length', str(len(content or b'')))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Frame-Options', 'DENY')
            self.end_headers()
            if content is not None:
                self.wfile.write(content)

    cert_path, key_path, fingerprint = certificate(tmp_path)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(str(cert_path), str(key_path))
    with running_server(Gateway, tls) as gateway, running_server(Host) as host, running_server(Host) as foreign:
        origin = 'http://127.0.0.1:' + str(host.server_port)
        foreign_origin = 'http://127.0.0.1:' + str(foreign.server_port)

        class Tunnel(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_CONNECT(self):
                tunnels.append(self.path)
                if self.path != 'agentconcierge.biz:443':
                    self.send_error(403)
                    return
                with socket.create_connection(('127.0.0.1', gateway.server_port), timeout=5) as upstream:
                    self.send_response(200, 'Connection established')
                    self.end_headers()
                    self.connection.settimeout(10)
                    upstream.settimeout(10)
                    try:
                        while True:
                            ready, _, _ = select.select([self.connection, upstream], [], [], 10)
                            if not ready:
                                break
                            for source in ready:
                                data = source.recv(65536)
                                if not data:
                                    return
                                (upstream if source is self.connection else self.connection).sendall(data)
                    except (OSError, TimeoutError):
                        return

            def do_GET(self):
                self.send_error(403)

        release = published(connected_api)[0]
        plan = admin.post(admin_path(release) + '/prepare', headers=H,
                          json={'allowed_origins': [origin], 'minute_limit': 10, 'day_limit': 500, 'ttl_seconds': 1800})
        assert plan.status_code == 200, plan.text
        package = admin.post(admin_path(release) + '/package', headers=H, json=export_body(plan.json()))
        assert package.status_code == 200
        with ZipFile(BytesIO(package.content)) as archive:
            files.update({entry: archive.read(entry) for entry in archive.namelist()})
        assert b"origin='https://agentconcierge.biz'" in files['assets/agentconcierge-sdk.js']
        calls.clear()
        with running_server(Tunnel) as tunnel, sync_playwright() as playwright:
            browser = playwright.chromium.launch(proxy={'server': 'http://127.0.0.1:' + str(tunnel.server_port),
                                                       'bypass': '127.0.0.1,localhost'},
                                                 args=['--ignore-certificate-errors-spki-list=' + fingerprint])
            try:
                context = browser.new_context()
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin + '/apps/connected/')
                expect(page.locator('#runAppBtn')).to_be_disabled()
                page.locator('#prepareAppBtn').click()
                expect(page.locator('#appStatus')).to_contain_text('Review ready', timeout=15000)
                expect(page.locator('#shareAppAuthority')).not_to_be_checked()
                expect(page.locator('#liveAppAuthority')).not_to_be_checked()
                page.locator('#shareAppAuthority').check()
                page.locator('#liveAppAuthority').check()
                page.locator('#runAppBtn').click()
                expect(page.locator('#appStatus')).to_have_text('Connection: succeeded', timeout=15000)
                assert len(calls) == 2
                assert rt.typed_test_controls['seen'][-1]['query'] == rt.typed_test_controls['title']
                approved = list(wire)
                assert any(row['method'] == 'OPTIONS' and row['origin'] == origin and row['status'] == 204 for row in approved)
                starts = [row for row in approved if row['method'] == 'POST' and row['path'].endswith('/runs')]
                assert len(starts) == 1 and starts[0]['origin'] == origin
                assert not any(row['cookie'] or row['authorization'] for row in approved)
                page.goto(foreign_origin + '/apps/connected/')
                page.locator('#prepareAppBtn').click()
                expect(page.locator('#appStatus')).to_contain_text('unavailable', timeout=15000)
                denied = [row for row in wire if row['origin'] == foreign_origin]
                assert denied and all(row['method'] == 'OPTIONS' and row['status'] == 403 for row in denied)
                assert len(calls) == 2
                assert admin.post(ADMIN + '/releases/' + release['id'] + '/revoke', headers=H,
                                  json={'revision': release['revision']}).status_code == 200
                page.goto(origin + '/apps/connected/')
                page.locator('#prepareAppBtn').click()
                expect(page.locator('#appStatus')).to_contain_text('unavailable', timeout=15000)
                assert len(calls) == 2 and not errors
                assert 'agentconcierge.biz:443' in tunnels
                context.close()
            finally:
                browser.close()
    report = Path('reports/advancement-connected-sdk-2026-10-18/native-cors-tls.json')
    report.write_text(json.dumps({'actual_native_browser_preflight': True, 'sdk_bytes_unmodified': True,
                                  'logical_gateway': 'https://agentconcierge.biz', 'transport': 'loopback-only TLS CONNECT fixture',
                                  'tls_trust_scope': 'isolated Chromium fixture SPKI; no user trust or browser changed',
                                  'allowed_origin_run': True, 'unregistered_origin_blocked_before_post': True,
                                  'publication_withdrawal_blocks_new_prepare': True, 'fixture_provider_calls': 2,
                                  'credentials_forwarded': False, 'production_requests': 0}, indent=2) + '\n')
