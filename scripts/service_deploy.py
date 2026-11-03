"""Native, serialized A/B deployment with immutable releases and private probes.

Operational commands are explicit. Preparing a release never stops a service.
The first transition from the legacy process is a separate cutover command.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

from scripts.agentcon_config import read_settings
from agent_market.application_runtime import _private_bytes
from agent_market.service_host import probe_token

PORTS = {'frontend': {'a': 8401, 'b': 8402}, 'admin': {'a': 8201, 'b': 8202}}
RELEASE = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}\Z')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.pending')
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


# Separate apps published under a path prefix of the public site. They run outside this deployment
# (own launchd jobs, DB and secrets); the proxy only forwards the prefix to their loopback port.
PATH_APPS = (('/driveragent', 8620),)


def path_app_routes(apps):
    routes = ''
    for prefix, port in apps:
        if not re.fullmatch(r'/[a-z0-9-]+', prefix) or type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('invalid_path_app')
        name = prefix[1:].replace('-', '_')
        routes += '''    @app_%s path %s %s/*
    handle @app_%s {
        reverse_proxy 127.0.0.1:%d {
            header_up X-Forwarded-Proto https
            header_up X-Forwarded-For {client_ip}
            header_up -CF-Connecting-IP
            header_up -X-Real-IP
        }
    }
''' % (name, prefix, prefix, name, port)
    return routes


def caddyfile(directory, frontend, admin, public_port=8400, admin_port=8200, apps=PATH_APPS):
    for value in (frontend, admin, public_port, admin_port):
        if type(value) is not int or not 1024 <= value <= 65535:
            raise ValueError('invalid_proxy_port')
    socket = 'unix//' + str(Path(directory).resolve() / 'caddy-admin.sock')
    return '''{
    admin %s
    auto_https off
    servers {
        trusted_proxies static 127.0.0.1/32 ::1/128
        client_ip_headers CF-Connecting-IP X-Forwarded-For
    }
}
:%d {
    bind 127.0.0.1
%s    @private path /admin /admin/* /internal /internal/*
    respond @private 404
    reverse_proxy 127.0.0.1:%d {
        header_up X-Forwarded-Proto https
        header_up X-Forwarded-For {client_ip}
        header_up -CF-Connecting-IP
        header_up -X-Real-IP
        stream_close_delay 15s
    }
}
:%d {
    bind 127.0.0.1
    @private not path /admin /admin/*
    respond @private 404
    reverse_proxy 127.0.0.1:%d {
        header_up X-Forwarded-Proto http
        header_up X-Forwarded-For {client_ip}
        header_up -CF-Connecting-IP
        header_up -X-Real-IP
        stream_close_delay 15s
    }
}
''' % (json.dumps(socket), public_port, path_app_routes(apps), frontend, admin_port, admin)


class Deployment:
    def __init__(self, root, *, state_dir=None):
        self.root = Path(root).resolve()
        self.directory = Path(state_dir).resolve() if state_dir else self.root / 'gateway-data/services'
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.settings = self.root / 'gateway-data/agentcon.env'
        self.state_file = self.directory / 'state.json'
        self.domain = 'gui/' + str(os.getuid())
        self.prefix = 'biz.agentconcierge.' + hashlib.sha256(str(self.directory).encode()).hexdigest()[:10]
        self.caddy = shutil.which('caddy') or '/opt/homebrew/bin/caddy'

    @contextmanager
    def lock(self):
        # Serialize deployments, including resource-heavy candidate startups.
        descriptor = os.open(self.directory / 'deploy.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(descriptor)

    def state(self):
        if not self.state_file.exists():
            return {'version': 1, 'managed': False, 'services': {}, 'phase': 'uninitialized'}
        return json.loads(self.state_file.read_text())

    def save(self, state, phase):
        state.update(phase=phase, updated=time.time())
        atomic_json(self.state_file, state)

    def path(self, release):
        if not RELEASE.fullmatch(release) or release in ('.', '..'):
            raise ValueError('invalid_release_id')
        path = self.directory / 'releases' / release
        if path.is_symlink():
            raise ValueError('release_symlink_refused')
        return path

    def package(self, release):
        target = self.path(release)
        if target.exists():
            raise ValueError('release_already_exists')
        target.mkdir(mode=0o700, parents=True)
        # Keep source, assets and dependencies fixed for the process lifetime.
        ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', 'node_modules', 'qa')
        for name in ('agent_market', 'scripts', 'new'):
            shutil.copytree(self.root / name, target / name, ignore=ignore)
        metadata = {self.root / name for name in ('pyproject.toml', 'extracted_html.txt')}
        metadata.update(self.root.glob('requirements*.txt'))
        metadata.update(self.root.glob('requirements*.lock'))
        for path in sorted(metadata):
            if path.is_file() and not path.is_symlink():
                shutil.copy2(path, target / path.name)
        (target / 'service_entry.py').write_text(
            "import runpy\nrunpy.run_module('agent_market.service_host', run_name='__main__')\n")
        # APFS clone is cheap and isolates package writes from the live venv.
        result = subprocess.run(['/bin/cp', '-cR', str(self.root / '.venv'), str(target / '.venv')],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            if (target / '.venv').exists():
                shutil.rmtree(target / '.venv')
            shutil.copytree(self.root / '.venv', target / '.venv', symlinks=True)
        runtime_manifest = self.root / 'deploy/runtime-versions.json'
        if runtime_manifest.is_file() and not runtime_manifest.is_symlink():
            (target / 'deploy').mkdir(exist_ok=True)
            shutil.copy2(runtime_manifest, target / 'deploy/runtime-versions.json')
        # A release must retain the reviewed lock and match its production profile.
        if (target / 'requirements-runtime.lock').is_file():
            checked = subprocess.run([str(target / '.venv/bin/python'), '-B',
                str(target / 'scripts/audit_dependency_profile.py'), '--profile', 'runtime',
                '--output', str(target / 'runtime-environment.json')], cwd=target,
                capture_output=True, text=True)
            if checked.returncode:
                raise ValueError('runtime_dependency_profile_mismatch')
        hashes = {}
        for file in sorted(target.rglob('*')):
            if file.is_file() and '.venv' not in file.relative_to(target).parts:
                hashes[str(file.relative_to(target))] = hashlib.sha256(file.read_bytes()).hexdigest()
        atomic_json(target / 'release.json', {'release': release, 'created': time.time(), 'sha256': hashes})
        return {'release': release, 'files': len(hashes)}

    def verify_release(self, release):
        root = self.path(release)
        manifest = json.loads((root / 'release.json').read_text())
        if manifest['release'] != release:
            raise ValueError('release_manifest_mismatch')
        for name, expected in manifest['sha256'].items():
            path = root / name
            if not path.is_relative_to(root) or '..' in Path(name).parts or path.is_symlink():
                raise ValueError('unsafe_release_path')
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('release_content_changed')

    def label(self, role, slot):
        if role not in ('frontend', 'admin', 'jobs', 'execution', 'proxy') or slot not in ('a', 'b', 'main'):
            raise ValueError('invalid_service_identity')
        return self.prefix + '.' + role + '.' + slot

    def job_state(self, role, slot):
        result = subprocess.run(['launchctl', 'print', self.domain + '/' + self.label(role, slot)],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            if 'Could not find service' in result.stderr:
                return False, None
            raise RuntimeError('service_state_unavailable')
        match = re.search(r'^\s*pid = (\d+)$', result.stdout, re.M)
        return True, int(match[1]) if match else None

    def pid(self, role, slot):
        return self.job_state(role, slot)[1]

    @staticmethod
    def process_alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def start(self, role, slot, release=None):
        label = self.label(role, slot)
        if self.pid(role, slot):
            raise ValueError('service_slot_in_use')
        logs = self.root / 'logs/services'
        logs.mkdir(parents=True, exist_ok=True)
        if role == 'proxy':
            program = [self.caddy, 'run', '--config', str(self.directory / 'Caddyfile'), '--adapter', 'caddyfile']
            working = str(self.directory)
        else:
            self.verify_release(release)
            path = self.path(release)
            program = [str(path / '.venv/bin/python'), '-B', str(path / 'service_entry.py'),
                       '--role', role, '--release', release, '--settings', str(self.settings),
                       '--state-dir', str(self.directory), '--project-root', str(self.root)]
            if role in PORTS:
                program += ['--port', str(PORTS[role][slot])]
            working = str(self.root)
        spec = {'Label': label, 'ProgramArguments': program, 'WorkingDirectory': working,
                'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 10,
                'ExitTimeOut': 120, 'Umask': 0o077,
                'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin', 'PYTHONUNBUFFERED': '1'},
                'StandardOutPath': str(logs / (label + '.log')), 'StandardErrorPath': str(logs / (label + '.log'))}
        plist = self.directory / (label + '.plist')
        with plist.open('wb') as stream:
            plistlib.dump(spec, stream)
        os.chmod(plist, 0o600)
        # A loaded job can have no PID yet still be starting or unloading.
        # Wait for complete removal before registering this label again.
        self.stop(role, slot)
        result = subprocess.run(['launchctl', 'bootstrap', self.domain, str(plist)], capture_output=True)
        if result.returncode:
            raise RuntimeError('service_bootstrap_failed')

    def stop(self, role, slot, timeout=130):
        deadline = time.monotonic() + timeout
        loaded, pid = self.job_state(role, slot)
        if not loaded:
            return
        observed = {pid} if pid else set()
        subprocess.run(['launchctl', 'bootout', self.domain + '/' + self.label(role, slot)],
                       capture_output=True, timeout=timeout)
        # bootout acknowledges removal asynchronously. Even after the label
        # disappears, its old PID can still own sockets or background locks.
        # Do not force-kill it or start a competing process on timeout.
        while True:
            loaded, pid = self.job_state(role, slot)
            if pid:
                observed.add(pid)
            alive = any(self.process_alive(value) for value in observed)
            if not loaded and not alive:
                return
            if time.monotonic() >= deadline:
                raise RuntimeError('service_stop_timeout')
            time.sleep(.1)

    def persist(self, state):
        """Reload only active slots and workers at the next user login."""
        directory = Path.home() / 'Library/LaunchAgents'
        directory.mkdir(parents=True, exist_ok=True)
        wanted = set()
        if state['phase'] != 'stopped':
            for role in ('frontend', 'admin', 'jobs', 'execution', 'proxy'):
                slot = state['services'][role]['active'] if role in PORTS else 'main'
                name = self.label(role, slot) + '.plist'
                wanted.add(name)
                source = self.directory / name
                destination = directory / name
                if destination.is_symlink():
                    raise ValueError('launch_agent_symlink_refused')
                data = source.read_bytes()
                descriptor = os.open(destination, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(data)
        for file in directory.glob(self.prefix + '.*.plist'):
            if file.name not in wanted and not file.is_symlink():
                file.unlink()

    def probe(self, role, slot, release=None):
        settings = read_settings(str(self.settings))
        key_path = Path(settings['APPLICATION_WORKFLOW_KEY_FILE'])
        if not key_path.is_absolute():
            key_path = self.root / key_path
        key = _private_bytes(str(key_path), 32)
        request = urllib.request.Request('http://127.0.0.1:%d/internal/service/ready' % PORTS[role][slot],
                                         headers={'X-Service-Probe': probe_token(key)})
        # No environment proxies, redirects, or public network for private probes.
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(request, timeout=8) as reply:
            data = json.loads(reply.read(4096))
        if not data.get('ready') or data.get('role') != role or release and data.get('release') != release:
            raise RuntimeError('candidate_not_ready')
        return data

    def wait_ready(self, role, slot, release, timeout=180):
        deadline, successes = time.monotonic() + timeout, 0
        while time.monotonic() < deadline:
            try:
                self.probe(role, slot, release)
                successes += 1
                if successes >= 3:
                    self.verify_web(role, slot)
                    return
            except Exception:
                successes = 0
            time.sleep(1)
        raise RuntimeError('candidate_readiness_timeout')

    def verify_web(self, role, slot):
        import httpx
        base = 'http://127.0.0.1:' + str(PORTS[role][slot])
        with httpx.Client(base_url=base, trust_env=False, follow_redirects=False, timeout=15,
                          headers={'Accept': 'text/html', 'User-Agent': 'AgentConcierge-Deployment-Verification/1.0'}) as client:
            paths = ('/', '/customer/organizations') if role == 'frontend' else ('/admin/ui',)
            for path in paths:
                response = client.get(path)
                if response.status_code not in (200, 302, 303, 307):
                    raise RuntimeError('candidate_page_failed')
                if response.status_code == 200:
                    if 'text/html' not in response.headers.get('content-type', ''):
                        raise RuntimeError('candidate_page_type_invalid')
                    assets = set(re.findall(r'''(?:src|href)=["'](/new/en/assets/[^"']+)["']''', response.text))
                    for asset in sorted(assets)[:12]:
                        if client.get(asset).status_code != 200:
                            raise RuntimeError('candidate_asset_failed')
            if role == 'frontend':
                if client.get('/admin/ui').status_code != 404:
                    raise RuntimeError('candidate_admin_exposed')
                self.warm(client)
            elif client.get('/admin/api/overview').status_code not in (401, 403):
                raise RuntimeError('candidate_admin_authorization_failed')

    WARM_PATHS = ('/new/en/explore.html', '/new/en/chat.html', '/api/explore?limit=45', '/api/explore?q=weather&limit=45',
                  '/api/explore?q=translate&limit=45', '/api/explore?q=news&limit=45', '/api/explore?q=research%20papers&limit=45',
                  '/status.json', '/llms.txt', '/.well-known/agent-card.json')

    def warm(self, client):
        """Fill the candidate's own caches before traffic moves; never a reason to refuse a deploy."""
        warmed = 0
        for path in self.WARM_PATHS:
            try:
                if client.get(path, timeout=30).status_code == 200:
                    warmed += 1
            except Exception:
                continue
        return warmed

    def proxy_config(self, state, *, reload=True):
        frontend = PORTS['frontend'][state['services']['frontend']['active']]
        admin = PORTS['admin'][state['services']['admin']['active']]
        candidate = self.directory / 'Caddyfile.pending'
        candidate.write_text(caddyfile(self.directory, frontend, admin))
        result = subprocess.run([self.caddy, 'validate', '--config', str(candidate), '--adapter', 'caddyfile'], capture_output=True)
        if result.returncode:
            raise RuntimeError('proxy_configuration_invalid')
        if reload:
            result = subprocess.run([self.caddy, 'reload', '--config', str(candidate), '--adapter', 'caddyfile',
                                     '--address', 'unix//' + str(self.directory / 'caddy-admin.sock')], capture_output=True)
            if result.returncode:
                raise RuntimeError('proxy_reload_unconfirmed')
        os.replace(candidate, self.directory / 'Caddyfile')

    def drained(self, role, slot, timeout=100):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.probe(role, slot).get('active_requests') == 0:
                return True
            time.sleep(1)
        return False

    def deploy(self, role, release):
        if role not in PORTS:
            raise ValueError('web_service_required')
        with self.lock():
            state = self.state()
            if not state['managed'] or state['phase'] not in ('stable', 'retained'):
                raise ValueError('stable_managed_state_required')
            previous = json.loads(json.dumps(state))
            service = state['services'][role]
            old = service['active']
            new = 'b' if old == 'a' else 'a'
            if self.pid(role, new):
                if not self.drained(role, new):
                    raise RuntimeError('previous_slot_still_busy')
                self.stop(role, new)
            self.verify_release(release)
            state['pending'] = {'role': role, 'from': old, 'to': new, 'release': release, 'previous': previous}
            self.save(state, 'preparing')
            try:
                self.start(role, new, release)
                self.wait_ready(role, new, release)
            except BaseException:
                self.stop(role, new)
                self.save(previous, 'stable')
                raise
            service['slots'][new] = release
            service['active'] = new
            self.save(state, 'switching')
            # If reload acknowledgement is uncertain, retain both processes and
            # the journal; recover must inspect the active proxy configuration.
            self.proxy_config(state)
            self.save(state, 'observing')
            try:
                for _ in range(5):
                    self.probe(role, new, release)
                    time.sleep(1)
            except BaseException:
                self.wait_ready(role, old, service['slots'][old])
                self.proxy_config(previous)
                self.save(previous, 'stable')
                raise
            service['previous'] = old
            state.pop('pending', None)
            self.save(state, 'retained')
            self.persist(state)
            # Retain the previous, drained process for immediate rollback. It is
            # reclaimed only when the next candidate needs this slot.
            self.drained(role, old)
            return {'service': role, 'active': new, 'release': release, 'previous_retained': True}

    def rollback(self, role):
        with self.lock():
            state = self.state()
            if state['phase'] not in ('stable', 'retained'):
                raise ValueError('recover_interrupted_deployment_first')
            service = state['services'][role]
            old, new = service['active'], service.get('previous')
            if new not in ('a', 'b') or new == old:
                raise ValueError('previous_release_unavailable')
            if not self.pid(role, new):
                self.start(role, new, service['slots'][new])
            self.wait_ready(role, new, service['slots'][new])
            previous = json.loads(json.dumps(state))
            state['pending'] = {'role': role, 'from': old, 'to': new,
                                'release': service['slots'][new], 'previous': previous}
            service['active'], service['previous'] = new, old
            self.save(state, 'switching')
            self.proxy_config(state)
            state.pop('pending', None)
            self.save(state, 'retained')
            self.persist(state)
            return {'service': role, 'active': new, 'release': service['slots'][new]}

    def recover(self, worker=None, release=None):
        import httpx
        with self.lock():
            state = self.state()
            if worker or state.get('pending_worker') or state.get('phase') in ('worker_draining', 'worker_recovery_required'):
                return self.recover_worker(state, worker, release)
            pending = state.get('pending')
            if not pending:
                raise ValueError('no_interrupted_web_deployment')
            transport = httpx.HTTPTransport(uds=str(self.directory / 'caddy-admin.sock'))
            with httpx.Client(transport=transport, base_url='http://localhost', timeout=5) as client:
                response = client.get('/config/')
                response.raise_for_status()
                config = response.json()
            dials = set()
            def walk(value):
                if isinstance(value, dict):
                    for name, child in value.items():
                        if name == 'dial' and isinstance(child, str):
                            dials.add(child)
                        else:
                            walk(child)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)
            walk(config)
            role = pending['role']
            live = [slot for slot in ('a', 'b') if '127.0.0.1:' + str(PORTS[role][slot]) in dials]
            if len(live) != 1:
                raise RuntimeError('proxy_state_ambiguous_keep_both_slots')
            if live[0] == pending['from']:
                restored = pending['previous']
            elif live[0] == pending['to']:
                self.wait_ready(role, live[0], pending['release'])
                restored = state
                restored['services'][role]['active'] = live[0]
                restored['services'][role]['previous'] = pending['from']
                restored['services'][role]['slots'][live[0]] = pending['release']
            else:
                raise RuntimeError('proxy_state_unexpected')
            restored.pop('pending', None)
            self.save(restored, 'retained')
            self.persist(restored)
            return self.status()

    def worker_owner_free(self, role):
        """Never replace an unregistered process still owning its role lock."""
        path = self.directory / (role + '.owner.lock')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('worker_owner_still_busy') from None
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def worker_release(self, role):
        path = self.directory / (self.label(role, 'main') + '.plist')
        if path.is_symlink(): raise ValueError('launch_agent_symlink_refused')
        with path.open('rb') as stream: spec = plistlib.load(stream)
        args = spec.get('ProgramArguments', [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError('worker_release_unconfirmed')
        try:
            if args[args.index('--role')+1] != role: raise ValueError()
            release = args[args.index('--release')+1]
            if not RELEASE.fullmatch(release): raise ValueError()
        except (ValueError, IndexError, TypeError):
            raise ValueError('worker_release_unconfirmed') from None
        return release

    def recover_worker(self, state, role=None, release=None):
        if not state.get('managed') or state.get('pending') or state.get('phase') not in ('worker_draining', 'worker_recovery_required'):
            raise ValueError('no_interrupted_worker_deployment')
        pending = state.get('pending_worker')
        if pending:
            if (role is not None and role != pending['role'] or release is not None and release != pending['release']):
                raise ValueError('worker_recovery_target_mismatch')
            role, release = pending['role'], pending['release']
        elif role not in ('jobs', 'execution') or release is None:
            raise ValueError('legacy_worker_recovery_requires_role_and_release')
        if role not in ('jobs', 'execution') or not isinstance(release, str) or not RELEASE.fullmatch(release):
            raise ValueError('invalid_worker_recovery_target')
        self.verify_release(release)
        if not pending:
            pending = {'role': role, 'release': release, 'from_release': state['services'][role]['release'], 'old_pid': None}
            state['pending_worker'] = pending
            self.save(state, 'worker_draining')
        if pending.get('old_pid') and self.process_alive(pending['old_pid']):
            raise RuntimeError('worker_previous_process_still_alive')
        if self.pid(role, 'main'):
            if self.worker_release(role) != release:
                raise RuntimeError('worker_release_unconfirmed')
            # Reconcile an already started target without replaying a restart.
            self.wait_worker(role)
        else:
            self.stop(role, 'main')
            self.worker_owner_free(role)
            try:
                self.start(role, 'main', release)
                self.wait_worker(role)
            except BaseException:
                self.save(state, 'worker_recovery_required')
                raise
        state['services'][role] = {'release': release, 'previous_release': pending['from_release']}
        state.pop('pending_worker', None)
        self.save(state, 'stable')
        self.persist(state)
        return self.status()

    def control(self):
        from agent_market.service_runtime import ServiceControl
        settings = read_settings(str(self.settings))
        for name in ('APPLICATION_POSTGRES_DSN_FILE', 'APPLICATION_WORKFLOW_KEY_FILE'):
            if settings.get(name) and not Path(settings[name]).is_absolute():
                settings[name] = str(self.root / settings[name])
        os.environ.update(settings)
        return ServiceControl.open()

    def install_schema(self):
        with self.lock():
            control = self.control()
            try:
                control.install()
                return {'service_schema_ready': control.ready()}
            finally:
                control.close()

    def wait_worker(self, role, timeout=180):
        control = self.control()
        try:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.pid(role, 'main') and control.status(role).get('available'):
                    return
                time.sleep(1)
            raise RuntimeError('worker_startup_timeout')
        finally:
            control.close()

    def cutover(self, release, legacy_pid):
        with self.lock():
            state = self.state()
            if state['managed']:
                raise ValueError('already_managed')
            command = subprocess.run(['ps', '-p', str(legacy_pid), '-o', 'command='], capture_output=True, text=True)
            cwd = subprocess.run(['lsof', '-a', '-p', str(legacy_pid), '-d', 'cwd', '-Fn'], capture_output=True, text=True)
            if ('-m agent_market.gateway.server' not in command.stdout or
                    ('n' + str(self.root) + '\n') not in cwd.stdout):
                raise ValueError('legacy_process_identity_mismatch')
            self.verify_release(release)
            control = self.control()
            try:
                if not control.ready():
                    raise ValueError('service_schema_not_installed')
            finally:
                control.close()
            for role in PORTS:
                state['services'][role] = {'active': 'a', 'slots': {'a': release}}
            for role in ('jobs', 'execution'):
                state['services'][role] = {'release': release}
            state['legacy_pid'] = legacy_pid
            self.save(state, 'initial_preparing')
            for role in PORTS:
                if not self.pid(role, 'a'):
                    self.start(role, 'a', release)
                self.wait_ready(role, 'a', release)
            self.proxy_config(state, reload=False)
            self.save(state, 'initial_draining')
            began = time.time()
            os.kill(legacy_pid, signal.SIGTERM)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                try:
                    os.kill(legacy_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(.5)
            else:
                raise RuntimeError('legacy_drain_timeout_no_force_kill')
            try:
                # The old collector is gone before either new background owner
                # starts. The fixed ingress retains the existing public ports.
                for role in ('execution', 'jobs'):
                    self.start(role, 'main', release)
                self.start('proxy', 'main')
                for role in ('execution', 'jobs'):
                    self.wait_worker(role)
                for role in PORTS:
                    self.probe(role, 'a', release)
                if not self.pid('proxy', 'main'):
                    raise RuntimeError('proxy_not_running')
            except BaseException:
                for role in ('proxy', 'jobs', 'execution'):
                    self.stop(role, 'main')
                for role in PORTS:
                    self.stop(role, 'a')
                self.save(state, 'initial_failed_legacy_restore')
                subprocess.run([str(self.root / 'agentcon'), 'start', '--legacy'], cwd=self.root,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
                raise
            state['managed'] = True
            state['initial_transition_seconds'] = round(time.time() - began, 3)
            self.save(state, 'stable')
            self.persist(state)
            return self.status()

    def deploy_worker(self, role, release):
        if role not in ('jobs', 'execution'):
            raise ValueError('worker_role_required')
        with self.lock():
            state = self.state()
            if not state['managed'] or state['phase'] not in ('stable', 'retained'):
                raise ValueError('stable_managed_state_required')
            old = state['services'][role]['release']
            self.verify_release(release)
            state['pending_worker'] = {'role': role, 'release': release, 'from_release': old,
                                       'old_pid': self.pid(role, 'main')}
            self.save(state, 'worker_draining')
            self.stop(role, 'main')
            state['pending_worker']['old_pid'] = None
            self.save(state, 'worker_draining')
            try:
                self.worker_owner_free(role)
                self.start(role, 'main', release)
                self.wait_worker(role)
            except BaseException:
                try:
                    self.stop(role, 'main')
                    self.worker_owner_free(role)
                    self.start(role, 'main', old)
                    self.wait_worker(role)
                except BaseException:
                    self.save(state, 'worker_recovery_required')
                    raise
                state.pop('pending_worker', None)
                self.save(state, 'stable')
                self.persist(state)
                raise
            state['services'][role] = {'release': release, 'previous_release': old}
            state.pop('pending_worker', None)
            self.save(state, 'stable')
            self.persist(state)
            return self.status()

    def restart_web(self, role='all'):
        release = time.strftime('web-%Y%m%d-%H%M%S') + '-' + secrets.token_hex(2)
        with self.lock():
            self.package(release)
        results = []
        for target in (('frontend', 'admin') if role == 'all' else (role,)):
            results.append(self.deploy(target, release))
        return {'deployments': results, 'workers_restarted': False}

    def managed_start(self):
        with self.lock():
            state = self.state()
            if not state['managed'] or state['phase'] not in ('stable', 'retained', 'stopped'):
                raise ValueError('managed_state_required')
            for role in PORTS:
                service = state['services'][role]
                slot = service['active']
                release = service['slots'][slot]
                if not self.pid(role, slot):
                    self.start(role, slot, release)
                self.wait_ready(role, slot, release)
            for role in ('execution', 'jobs'):
                if not self.pid(role, 'main'):
                    self.start(role, 'main', state['services'][role]['release'])
                self.wait_worker(role)
            self.proxy_config(state, reload=bool(self.pid('proxy', 'main')))
            if not self.pid('proxy', 'main'):
                self.start('proxy', 'main')
            self.save(state, 'stable')
            self.persist(state)
            return self.status()

    def managed_stop(self):
        with self.lock():
            state = self.state()
            if not state['managed']:
                raise ValueError('managed_state_required')
            self.stop('proxy', 'main')
            for role in PORTS:
                for slot in state['services'][role]['slots']:
                    self.stop(role, slot)
            for role in ('jobs', 'execution'):
                self.stop(role, 'main')
            self.save(state, 'stopped')
            self.persist(state)
            return {'managed': True, 'stopped': True}

    def status(self):
        state = self.state()
        result = {'managed': state['managed'], 'phase': state['phase'], 'services': {}}
        for role, service in state['services'].items():
            if role in PORTS:
                result['services'][role] = {'active': service['active'], 'slots': {
                    slot: {'release': release, 'pid': self.pid(role, slot)}
                    for slot, release in service['slots'].items()}}
            else:
                result['services'][role] = {'release': service['release'], 'pid': self.pid(role, 'main')}
        result['proxy_pid'] = self.pid('proxy', 'main')
        return result


def release_gate(root, release, runner=subprocess.run):
    """Refuse a frontend release whose copy fails the opening-path tests (DEPLOY.md, 11-02).

    Runs before the deployment lock is taken. Its output goes to stderr; stdout stays the JSON result.
    """
    python = Path(root) / '.venv-tests' / 'bin' / 'python'
    if not python.is_file():
        raise SystemExit('release_gate_unavailable: .venv-tests is missing (emergency only: --skip-gate)')
    result = runner([str(python), '-m', 'scripts.release_gate', release], cwd=str(root),
                    stdout=sys.stderr, stderr=sys.stderr)
    if result.returncode:
        raise SystemExit('release_gate_failed: %s (see the test output above)' % release)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    commands = parser.add_subparsers(dest='command', required=True)
    package = commands.add_parser('package'); package.add_argument('release')
    deploy = commands.add_parser('deploy'); deploy.add_argument('role', choices=PORTS); deploy.add_argument('release')
    deploy.add_argument('--skip-gate', action='store_true', help='emergency only: deploy a frontend release without scripts.release_gate')
    rollback = commands.add_parser('rollback'); rollback.add_argument('role', choices=PORTS)
    commands.add_parser('status')
    commands.add_parser('install-schema')
    recovery = commands.add_parser('recover')
    recovery.add_argument('--worker', choices=('jobs', 'execution'))
    recovery.add_argument('--release')
    commands.add_parser('start')
    commands.add_parser('stop')
    restart = commands.add_parser('restart'); restart.add_argument('role', nargs='?', choices=('all', 'frontend', 'admin'), default='all')
    cutover = commands.add_parser('cutover'); cutover.add_argument('release'); cutover.add_argument('--legacy-pid', type=int, required=True)
    worker = commands.add_parser('worker-deploy'); worker.add_argument('role', choices=('jobs', 'execution')); worker.add_argument('release')
    args = parser.parse_args()
    manager = Deployment(args.root)
    if args.command == 'package':
        with manager.lock():
            result = manager.package(args.release)
    elif args.command == 'deploy':
        if args.role == 'frontend' and not args.skip_gate:
            release_gate(args.root, args.release)
        result = manager.deploy(args.role, args.release)
    elif args.command == 'rollback':
        result = manager.rollback(args.role)
    elif args.command == 'recover':
        result = manager.recover(args.worker, args.release)
    elif args.command == 'install-schema':
        result = manager.install_schema()
    elif args.command == 'cutover':
        result = manager.cutover(args.release, args.legacy_pid)
    elif args.command == 'worker-deploy':
        result = manager.deploy_worker(args.role, args.release)
    elif args.command == 'restart':
        result = manager.restart_web(args.role)
    elif args.command == 'start':
        result = manager.managed_start()
    elif args.command == 'stop':
        result = manager.managed_stop()
    else:
        result = manager.status()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
