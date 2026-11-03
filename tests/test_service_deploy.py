"""Deployment failure boundaries and real isolated Caddy switching evidence."""
from concurrent.futures import ThreadPoolExecutor
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

import httpx
import pytest

from scripts.service_deploy import Deployment, caddyfile


class FakeDeployment(Deployment):
    def __init__(self, root):
        super().__init__(root)
        self.processes = {('frontend', 'a'): 'old', ('admin', 'a'): 'old', ('jobs', 'main'): 'jobs-old'}
        self.calls = []
        self.fail_ready = False
        self.fail_switch = False
        self.save({'version': 1, 'managed': True, 'services': {
            'frontend': {'active': 'a', 'slots': {'a': 'old'}},
            'admin': {'active': 'a', 'slots': {'a': 'old'}},
            'jobs': {'release': 'jobs-old'}}}, 'stable')

    def verify_release(self, release):
        return None

    def persist(self, state):
        self.calls.append(('persist', state['phase']))

    def pid(self, role, slot):
        return 123 if (role, slot) in self.processes else None

    def start(self, role, slot, release=None):
        self.calls.append(('start', role, slot))
        self.processes[(role, slot)] = release

    def stop(self, role, slot):
        self.calls.append(('stop', role, slot))
        self.processes.pop((role, slot), None)

    def wait_ready(self, role, slot, release, timeout=180):
        if self.fail_ready and slot == 'b':
            raise RuntimeError('synthetic_readiness_failure')

    def probe(self, role, slot, release=None):
        assert self.processes[(role, slot)] == (release or self.processes[(role, slot)])
        return {'ready': True, 'active_requests': 0}

    def proxy_config(self, state, reload=True):
        self.calls.append(('switch', state['services']['frontend']['active'], state['services']['admin']['active']))
        if self.fail_switch:
            raise RuntimeError('synthetic_lost_proxy_ack')

    def drained(self, role, slot, timeout=100):
        return True


def test_independent_deploy_and_rollback_preserve_other_services(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.service_deploy.time.sleep', lambda _: None)
    manager = FakeDeployment(tmp_path)
    manager.deploy('frontend', 'new')
    state = manager.state()
    assert state['services']['frontend']['active'] == 'b'
    assert state['services']['admin']['active'] == 'a'
    assert ('stop', 'jobs', 'main') not in manager.calls
    assert manager.processes[('frontend', 'a')] == 'old'
    manager.rollback('frontend')
    assert manager.state()['services']['frontend']['active'] == 'a'
    assert manager.state()['services']['admin']['active'] == 'a'


def test_failed_readiness_keeps_old_service(tmp_path):
    manager = FakeDeployment(tmp_path)
    manager.fail_ready = True
    with pytest.raises(RuntimeError):
        manager.deploy('frontend', 'bad')
    assert manager.state()['phase'] == 'stable'
    assert manager.state()['services']['frontend']['active'] == 'a'
    assert ('frontend', 'b') not in manager.processes
    assert not any(c[0] == 'switch' for c in manager.calls)


def test_uncertain_switch_preserves_both_slots_and_blocks_second_deploy(tmp_path):
    manager = FakeDeployment(tmp_path)
    manager.fail_switch = True
    with pytest.raises(RuntimeError):
        manager.deploy('admin', 'new')
    assert manager.state()['phase'] == 'switching'
    assert ('admin', 'a') in manager.processes and ('admin', 'b') in manager.processes
    with pytest.raises(ValueError):
        manager.deploy('frontend', 'another')


def test_release_paths_and_ports_are_not_shell_inputs(tmp_path):
    manager = FakeDeployment(tmp_path)
    for name in ('../escape', '/tmp/escape', 'x; command', '..'):
        with pytest.raises(ValueError):
            manager.path(name)
    with pytest.raises(ValueError):
        caddyfile(tmp_path, '8401\n', 8201)


def test_path_apps_are_validated_and_default_to_driveragent(tmp_path):
    assert '@app_driveragent path /driveragent /driveragent/*' in caddyfile(tmp_path, 8401, 8201)
    for apps in ((('/Bad', 8620),), (('/x y', 8620),), (('/ok', 80),), (('/ok', '8620'),)):
        with pytest.raises(ValueError):
            caddyfile(tmp_path, 8401, 8201, apps=apps)


def test_candidate_smoke_requests_browser_representation(tmp_path, monkeypatch):
    manager = FakeDeployment(tmp_path)
    original = httpx.Client
    seen = []
    def respond(request):
        seen.append(request.url.path)
        if request.url.path == '/admin/ui':
            return httpx.Response(404)
        if request.url.path == '/customer/organizations':
            return httpx.Response(303, headers={'Location': '/customer/login'})
        if request.url.path == '/new/en/assets/site.css':
            return httpx.Response(200, text='body{}', headers={'Content-Type': 'text/css'})
        if request.headers.get('accept') != 'text/html':
            return httpx.Response(200, json={'agent_protocol': True})
        return httpx.Response(200, text='<html><link href="/new/en/assets/site.css"></html>',
                              headers={'Content-Type': 'text/html'})
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)))
    manager.verify_web('frontend', 'a')
    assert '/new/en/assets/site.css' in seen
    # The candidate's own caches are filled before traffic moves.
    assert '/api/explore' in seen and '/status.json' in seen


def test_warm_failures_never_refuse_a_candidate(tmp_path):
    manager = FakeDeployment(tmp_path)
    class Broken:
        def get(self, path, **kwargs):
            raise httpx.ConnectError('down')
    assert manager.warm(Broken()) == 0


def test_stop_waits_for_launchd_removal_and_old_process_exit(tmp_path, monkeypatch):
    manager = Deployment(tmp_path)
    states = iter([(True, 123), (True, 123), (False, None), (False, None)])
    alive = iter([True, True, False])
    calls, pauses = [], []
    monkeypatch.setattr(manager, 'job_state', lambda *_: next(states))
    monkeypatch.setattr(manager, 'process_alive', lambda pid: next(alive))
    monkeypatch.setattr('scripts.service_deploy.subprocess.run',
                        lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr('scripts.service_deploy.time.sleep', pauses.append)
    manager.stop('admin', 'b')
    assert calls == [['launchctl', 'bootout', manager.domain + '/' + manager.label('admin', 'b')]]
    assert len(pauses) == 2


def test_stop_timeout_never_reuses_or_force_kills_slot(tmp_path, monkeypatch):
    manager = Deployment(tmp_path)
    calls = []
    monkeypatch.setattr(manager, 'job_state', lambda *_: (True, 123))
    monkeypatch.setattr(manager, 'process_alive', lambda pid: True)
    monkeypatch.setattr('scripts.service_deploy.subprocess.run',
                        lambda args, **kwargs: calls.append(args))
    with pytest.raises(RuntimeError, match='service_stop_timeout'):
        manager.stop('admin', 'b', timeout=.01)
    assert len(calls) == 1 and calls[0][1] == 'bootout'


def test_stop_waits_for_loaded_job_without_pid(tmp_path, monkeypatch):
    manager = Deployment(tmp_path)
    states = iter([(True, None), (True, None), (False, None)])
    pauses = []
    monkeypatch.setattr(manager, 'job_state', lambda *_: next(states))
    monkeypatch.setattr('scripts.service_deploy.subprocess.run', lambda *a, **kw: None)
    monkeypatch.setattr('scripts.service_deploy.time.sleep', pauses.append)
    manager.stop('admin', 'b')
    assert len(pauses) == 1


def test_launchd_inspection_failure_is_not_treated_as_free_slot(tmp_path, monkeypatch):
    manager = Deployment(tmp_path)
    monkeypatch.setattr('scripts.service_deploy.subprocess.run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 1, '', 'Operation not permitted'))
    with pytest.raises(RuntimeError, match='service_state_unavailable'):
        manager.pid('admin', 'b')
    monkeypatch.setattr('scripts.service_deploy.subprocess.run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 113, '', 'Could not find service "test"'))
    assert manager.job_state('admin', 'b') == (False, None)


def test_real_launchd_repeated_slot_reuse_waits_for_delayed_exit(tmp_path):
    import os
    import sys
    if sys.platform != 'darwin' or not shutil.which('launchctl'):
        pytest.skip('Native launchd integration requires macOS')
    manager = Deployment(tmp_path)
    release = manager.path('isolated-reuse')
    (release / '.venv/bin').mkdir(parents=True)
    (release / '.venv/bin/python').symlink_to(sys.executable)
    # A synthetic HTTP listener on an ephemeral port, never the project app.
    (release / 'service_entry.py').write_text('''
import json, os, signal, sys, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
role = sys.argv[sys.argv.index('--role') + 1]
root = Path(sys.argv[sys.argv.index('--project-root') + 1])
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'isolated')
    def log_message(self, *args): pass
def delayed_exit(*args):
    time.sleep(.4)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, delayed_exit)
with HTTPServer(('127.0.0.1', 0), Handler) as server:
    (root / (role + '.ready')).write_text(json.dumps({'pid': os.getpid(), 'port': server.server_port}))
    server.serve_forever()
''')
    manager.verify_release = lambda _: None
    def start(role):
        marker = tmp_path / (role + '.ready')
        marker.unlink(missing_ok=True)
        manager.start(role, 'main', 'isolated-reuse')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if marker.exists():
                return json.loads(marker.read_text())
            time.sleep(.05)
        pytest.fail('Isolated launchd process did not become ready')
    try:
        other = start('execution')
        for _ in range(3):
            candidate = start('jobs')
            assert httpx.get('http://127.0.0.1:%d/' % candidate['port'], trust_env=False).status_code == 200
            manager.stop('jobs', 'main')
            assert not manager.process_alive(candidate['pid'])
            assert manager.job_state('jobs', 'main') == (False, None)
            assert manager.pid('execution', 'main') == other['pid']
            os.kill(other['pid'], 0)
    finally:
        manager.stop('jobs', 'main')
        manager.stop('execution', 'main')


def test_real_caddy_switch_preserves_requests_and_ingress_boundaries(tmp_path):
    caddy = shutil.which('caddy')
    if not caddy:
        pytest.skip('Caddy is required for the real proxy integration test')
    # Unix-domain socket path must fit Darwin's sockaddr_un limit.
    import tempfile
    root = Path(tempfile.mkdtemp(prefix='ac-proxy-', dir='/private/tmp'))
    processes = []
    servers = []
    def server(version):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/slow':
                    time.sleep(.8)
                value = json.dumps({'version': version, 'scheme': self.headers.get('X-Forwarded-Proto'),
                                    'forwarded': self.headers.get('X-Forwarded-For'),
                                    'cf': self.headers.get('CF-Connecting-IP')}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(value)))
                self.end_headers()
                self.wfile.write(value)
            def log_message(self, *args):
                pass
        instance = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=instance.serve_forever, daemon=True).start()
        servers.append(instance)
        return instance.server_port
    def port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]
    old, new, admin, app = server('old'), server('new'), server('admin'), server('path-app')
    apps = (('/driveragent', app),)
    public_port, admin_port = port(), port()
    config = root / 'Caddyfile'
    config.write_text(caddyfile(root, old, admin, public_port, admin_port, apps))
    evidence = {'requests': 0, 'errors': [], 'versions': []}
    try:
        with (root / 'proxy.log').open('wb') as logs:
            process = subprocess.Popen([caddy, 'run', '--config', str(config), '--adapter', 'caddyfile'], stdout=logs, stderr=logs)
            processes.append(process)
        base = 'http://127.0.0.1:' + str(public_port)
        with httpx.Client(base_url=base, timeout=5, trust_env=False) as client:
            for _ in range(100):
                try:
                    if client.get('/').status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.05)
            else:
                raise AssertionError('Isolated proxy did not start')
            assert client.get('/admin/ui').status_code == 404
            assert client.get('/internal/service/ready', headers={'X-Service-Probe': 'forged'}).status_code == 404
            headers = client.get('/', headers={'CF-Connecting-IP': '198.51.100.8'}).json()
            assert headers['scheme'] == 'https' and headers['forwarded'] == '198.51.100.8' and headers['cf'] is None
            routed = client.get('/driveragent/', headers={'CF-Connecting-IP': '198.51.100.9'}).json()
            assert routed['version'] == 'path-app' and routed['scheme'] == 'https'
            assert routed['forwarded'] == '198.51.100.9' and routed['cf'] is None
            assert client.get('/driveragent').json()['version'] == 'path-app'
            assert client.get('/driveragentx').json()['version'] == 'old'
            def traffic():
                with httpx.Client(base_url=base, timeout=5, trust_env=False) as session:
                    for _ in range(80):
                        reply = session.get('/')
                        evidence['requests'] += 1
                        if reply.status_code != 200:
                            evidence['errors'].append(reply.status_code)
                        else:
                            evidence['versions'].append(reply.json()['version'])
                        time.sleep(.01)
            with ThreadPoolExecutor(max_workers=2) as pool:
                ongoing = pool.submit(traffic)
                slow = pool.submit(client.get, '/slow')
                time.sleep(.15)
                config.write_text(caddyfile(root, new, admin, public_port, admin_port, apps))
                result = subprocess.run([caddy, 'reload', '--config', str(config), '--adapter', 'caddyfile',
                    '--address', 'unix//' + str(root / 'caddy-admin.sock')], capture_output=True)
                assert result.returncode == 0
                assert slow.result().json()['version'] == 'old'
                ongoing.result()
            assert client.get('/').json()['version'] == 'new'
            assert client.get('/driveragent/x').json()['version'] == 'path-app'
            assert set(evidence['versions']) == {'old', 'new'} and not evidence['errors']
            assert httpx.get('http://127.0.0.1:%d/admin/ui' % admin_port, trust_env=False).json()['version'] == 'admin'
            bad = root / 'bad.caddy'; bad.write_text('this configuration is invalid {')
            invalid = subprocess.run([caddy, 'reload', '--config', str(bad), '--adapter', 'caddyfile',
                '--address', 'unix//' + str(root / 'caddy-admin.sock')], capture_output=True)
            assert invalid.returncode != 0 and client.get('/').json()['version'] == 'new'
        (tmp_path / 'proxy-evidence.json').write_text(json.dumps(evidence, indent=2))
    finally:
        for process in processes:
            process.terminate()
            process.wait(timeout=15)
        for instance in servers:
            instance.shutdown()
            instance.server_close()
        shutil.rmtree(root)
