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
# 11-10: a retained previous slot (about 1.5 GB) is stopped this long after a deploy; rollback starts it again.
RECLAIM_STANDBY_SECONDS = 1800
# Searches a new frontend slot runs before it takes traffic (cold caches made the first search 10.7 s on 11-10).
WARM_QUERIES = ('weather forecast', 'web search', 'translate text', 'pdf extraction')
WARM_SECONDS = 90
# 11-11: Explore results are shared through Redis, so the fixed queries above were answered from the old
# slot's cache and never ran the search on the new process; the first public query then took 14.4 s.
# Fresh queries are built from these words so each warm-up runs the real path.
WARM_VERBS = ('convert', 'summarize', 'extract', 'translate', 'search', 'monitor', 'generate', 'analyze',
              'schedule', 'validate', 'compare', 'classify')
WARM_OBJECTS = ('csv files', 'pdf invoices', 'news articles', 'github issues', 'stock prices', 'emails',
                'images', 'web pages', 'calendar events', 'product reviews', 'sql tables', 'audio notes')
SNAPSHOT_WAIT_SECONDS = 600     # the new slot's start report snapshot (about 3 min unpaused, 11-11)
WARM_EXPLORE_GOAL_MS = 2000      # the Explore target (CLAUDE.md response-time policy)
WARM_RECOMMEND_GOAL_MS = 3000    # the recommendation target
# Undeployed releases younger than this survive the post-deploy prune (another session may deploy them next).
AFTER_DEPLOY_MIN_AGE_HOURS = 6
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

    def package(self, release, base=None, commit=None):
        """Copy the tree into a new release. BASE names the release this tree was overlaid on;
        without it, AGENTCON_RELEASE_BASE or a release.json left in a copied release tree is used.
        deploy refuses a release whose base is no longer the active one (11-09: overlays built on
        a release that another session had replaced in the meantime reverted their work).

        COMMIT (11-10 user decision "operations = git"): build the release from that commit with
        `git archive`, never from working-tree files, and record the full hash in release.json, so
        every role can be checked against one commit."""
        source_root, exported, sha = self.root, None, None
        if commit is not None:
            sha, exported = self.export_commit(commit)
            source_root = exported
        self._from_commit = commit is not None
        try:
            return self._package(release, base, source_root, sha)
        finally:
            self._from_commit = False
            if exported is not None:
                shutil.rmtree(exported, ignore_errors=True)

    def venv_source(self):
        """The environment a new release clones. A release built from a commit uses the active frontend
        release's audited environment: the working copy's .venv gained test tools on 11-08 (pytest,
        sqlite-vec) and fails the runtime dependency profile."""
        if getattr(self, '_from_commit', False):
            try:
                service = self.state()['services']['frontend']
                release = service['slots'][service['active']]
                candidate = (self.path(release) / '.venv').resolve()
                if (candidate / 'bin' / 'python').exists():
                    return candidate
            except (KeyError, OSError, ValueError, TypeError):
                pass
        return (self.root / '.venv').resolve()

    def export_commit(self, commit):
        """Full hash and a private temporary tree of COMMIT's source, assets and metadata."""
        import tempfile
        if type(commit) is not str or not re.fullmatch(r'[A-Za-z0-9_./-]{1,100}', commit) or commit.startswith('-'):
            raise ValueError('invalid_commit')
        resolved = subprocess.run(['git', 'rev-parse', '--verify', commit + '^{commit}'], cwd=self.root,
                                  capture_output=True, text=True)
        if resolved.returncode:
            raise ValueError('unknown_commit')
        sha = resolved.stdout.strip()
        listed = subprocess.run(['git', 'ls-tree', '--name-only', sha], cwd=self.root, capture_output=True, text=True).stdout.split()
        wanted = [name for name in listed if name in ('agent_market', 'scripts', 'new', 'deploy', 'pyproject.toml', 'extracted_html.txt')
                  or name.startswith('requirements')]
        destination = Path(tempfile.mkdtemp(prefix='release-commit-'))
        archive = subprocess.run(['git', 'archive', sha, *wanted], cwd=self.root, capture_output=True)
        if archive.returncode:
            shutil.rmtree(destination, ignore_errors=True)
            raise ValueError('commit_export_failed')
        subprocess.run(['tar', '-x', '-C', str(destination)], input=archive.stdout, check=True)
        return sha, destination

    def _package(self, release, base, source_root, commit):
        base = self.package_base(base)
        target = self.path(release)
        if target.exists():
            raise ValueError('release_already_exists')
        target.mkdir(mode=0o700, parents=True)
        # Keep source, assets and dependencies fixed for the process lifetime.
        ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', 'node_modules', 'qa')
        for name in ('agent_market', 'scripts', 'new'):
            shutil.copytree(source_root / name, target / name, ignore=ignore)
        metadata = {source_root / name for name in ('pyproject.toml', 'extracted_html.txt')}
        metadata.update(source_root.glob('requirements*.txt'))
        metadata.update(source_root.glob('requirements*.lock'))
        for path in sorted(metadata):
            if path.is_file() and not path.is_symlink():
                shutil.copy2(path, target / path.name)
        (target / 'service_entry.py').write_text(
            "import runpy\nrunpy.run_module('agent_market.service_host', run_name='__main__')\n")
        # Releases with the same dependencies share one environment (11-10: 28 releases a day each
        # cloned .venv, and macOS assessed every new copy of its binaries on first run).
        shared = self.shared_environment(target)
        if shared is not None:
            os.symlink(shared, target / '.venv')
        else:
            # APFS clone is cheap and isolates package writes from the live venv.
            result = subprocess.run(['/bin/cp', '-cR', str(self.venv_source()), str(target / '.venv')],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode:
                if (target / '.venv').exists():
                    shutil.rmtree(target / '.venv')
                shutil.copytree(self.venv_source(), target / '.venv', symlinks=True)
        runtime_manifest = source_root / 'deploy/runtime-versions.json'
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
        manifest = {'release': release, 'created': time.time(), 'sha256': hashes}
        if base:
            manifest['base'] = base
        if commit:
            manifest['commit'] = commit
        atomic_json(target / 'release.json', manifest)
        return {'release': release, 'files': len(hashes), 'base': base, 'commit': commit}

    def environment_key(self, target):
        """Dependency identity of the environment a release would run: its runtime lock, the runtime
        versions file, the interpreter and the installed distributions. None when it cannot be read."""
        source = self.venv_source()
        try:
            config = (source / 'pyvenv.cfg').read_bytes()
            packages = sorted(path.name for path in source.glob('lib/python*/site-packages/*.dist-info'))
            if not packages:
                return None
            parts = [config, '\n'.join(packages).encode()]
            for name in ('requirements-runtime.lock', 'deploy/runtime-versions.json'):
                path = target / name
                parts.append(path.read_bytes() if path.is_file() else b'-')
        except OSError:
            return None
        return hashlib.sha256(b'\0'.join(parts)).hexdigest()[:24]

    def shared_environment(self, target):
        """The shared environment for this dependency key, cloned once from the packaging .venv.
        A key never changes its directory, so releases already using it are not affected by a new key."""
        key = self.environment_key(target)
        if key is None:
            return None
        venvs = self.directory / 'venvs'
        shared = venvs / key
        if shared.is_dir() and not shared.is_symlink() and (shared / '.complete').is_file():
            return shared
        venvs.mkdir(mode=0o700, exist_ok=True)
        staging = venvs / ('.staging-' + key + '-' + secrets.token_hex(4))
        result = subprocess.run(['/bin/cp', '-cR', str(self.venv_source()), str(staging)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            shutil.rmtree(staging, ignore_errors=True)
            return None
        (staging / '.complete').write_text(key)
        try:
            staging.rename(shared)
        except OSError:  # another session finished the same key first
            shutil.rmtree(staging, ignore_errors=True)
            if not (shared / '.complete').is_file():
                return None
        return shared

    def prune_environments(self, apply=False):
        """Shared environments that no remaining release links to."""
        venvs = self.directory / 'venvs'
        if not venvs.is_dir():
            return []
        used = set()
        for release in (self.directory / 'releases').iterdir():
            link = release / '.venv'
            if link.is_symlink():
                used.add(Path(os.path.realpath(link)).name)
        unused = [path for path in venvs.iterdir()
                  if path.is_dir() and not path.is_symlink() and path.name not in used and not path.name.startswith('.')]
        if apply:
            for path in unused:
                shutil.rmtree(path)
        return sorted(path.name for path in unused)

    def package_base(self, base=None):
        if base is None:
            base = os.environ.get('AGENTCON_RELEASE_BASE') or None
        if base is None:
            copied = self.root / 'release.json'
            if copied.is_file() and not copied.is_symlink():
                try:
                    base = json.loads(copied.read_text()).get('release')
                except (OSError, ValueError, AttributeError):
                    base = None
        if base is not None and (type(base) is not str or not RELEASE.fullmatch(base) or base in ('.', '..')):
            raise ValueError('invalid_release_base')
        return base

    def release_base(self, release):
        """The base recorded when RELEASE was packaged, or None (older releases recorded none)."""
        try:
            manifest = json.loads((self.path(release) / 'release.json').read_text())
        except (OSError, ValueError):
            return None
        base = manifest.get('base') if isinstance(manifest, dict) else None
        return base if type(base) is str else None

    def check_base(self, role, release, state=None, force=False):
        """Refuse RELEASE when it was built on a release that is not the active one of ROLE."""
        base = self.release_base(release)
        if base is None or force:
            return base
        state = state or self.state()
        service = (state.get('services') or {}).get(role) or {}
        active = service['slots'].get(service.get('active')) if 'slots' in service else service.get('release')
        if isinstance(active, dict):
            active = active.get('release')
        if active is not None and base != active:
            raise ValueError('release_base_mismatch: %s was built on %s but the active %s release is %s; '
                             'repackage it on the active release (or pass --force-base)' % (release, base, role, active))
        return base

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

    def wait_snapshot(self, role, slot, release, budget=SNAPSHOT_WAIT_SECONDS, sleep=time.sleep, clock=time.monotonic):
        """Wait until the new frontend slot has built its Explore report snapshot (or reports it cannot).

        11-11: a slot took traffic about a minute after start while its report snapshot took nine more
        minutes; that build shares the store lock with visitor requests and the first public search took
        14.4 s. Releases without the readiness field are not waited for; a timeout never blocks the deploy."""
        if role != 'frontend':
            return None
        began = clock()
        state = None
        while True:
            try:
                state = self.probe(role, slot, release).get('report_snapshot', 'absent')
            except Exception:
                state = 'probe_failed'
            if state in ('ready', 'skipped', 'failed', 'absent', None) or clock() - began >= budget:
                return {'state': state, 'seconds': round(clock() - began, 1)}
            sleep(5)

    def warm_web(self, role, slot, budget=WARM_SECONDS, transport=None, rng=None):
        """Warm the new frontend slot with queries it has never seen before traffic moves to it.

        Explore runs fresh queries until two in a row finish within the Explore target, then one MCP
        find_agents call (read-only, not recorded) warms the recommendation path. Failures and slowness
        never block the deploy; the timings and whether the targets were met are returned."""
        if role != 'frontend' or (transport is None and os.environ.get('PYTEST_CURRENT_TEST')):
            return []
        import httpx
        import random
        rng = rng or random.SystemRandom()
        timings, deadline = [], time.monotonic() + budget
        base = 'http://127.0.0.1:' + str(PORTS[role][slot])

        def timed(kind, call, label):
            began, stages = time.monotonic(), None
            try:
                response = call()
                status = response.status_code
                # Server-Timing stages show which part of a cold process is slow (11-11).
                stages = response.headers.get('server-timing', '')[:400] or None
            except Exception as error:
                status = type(error).__name__
            item = {'kind': kind, 'q': label, 'status': status, 'ms': round((time.monotonic() - began) * 1000)}
            if stages:
                item['server_timing'] = stages
            timings.append(item)
            return item

        try:
            with httpx.Client(base_url=base, trust_env=False, follow_redirects=False, timeout=20, transport=transport,
                              headers={'Host': 'agentconcierge.biz', 'User-Agent': 'AgentConcierge-Deployment-Warmup/1.0'}) as client:
                streak = 0
                while time.monotonic() < deadline and streak < 2:
                    query = rng.choice(WARM_VERBS) + ' ' + rng.choice(WARM_OBJECTS)
                    item = timed('explore', lambda: client.get('/api/explore', params={'q': query}), query)
                    streak = streak + 1 if item['status'] == 200 and item['ms'] <= WARM_EXPLORE_GOAL_MS else 0
                if time.monotonic() < deadline:
                    task = rng.choice(WARM_VERBS) + ' ' + rng.choice(WARM_OBJECTS)
                    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                            'params': {'name': 'find_agents', 'arguments': {'task': task}}}
                    timed('recommend', lambda: client.post('/mcp', json=body, headers={
                        'Accept': 'application/json, text/event-stream'}), task)
        except Exception as error:
            timings.append({'error': type(error).__name__})
        return timings

    @staticmethod
    def warm_summary(timings):
        """First fresh Explore time, last Explore time and whether the targets were met before the switch."""
        explore = [t for t in timings if t.get('kind') == 'explore']
        recommend = [t for t in timings if t.get('kind') == 'recommend']
        met = (len(explore) >= 2 and all(t['status'] == 200 and t['ms'] <= WARM_EXPLORE_GOAL_MS for t in explore[-2:]))
        return {'explore_calls': len(explore), 'first_explore_ms': explore[0]['ms'] if explore else None,
                'last_explore_ms': explore[-1]['ms'] if explore else None, 'explore_goal_met': met,
                'recommend_ms': recommend[-1]['ms'] if recommend else None,
                'recommend_goal_met': bool(recommend) and recommend[-1]['status'] == 200
                    and recommend[-1]['ms'] <= WARM_RECOMMEND_GOAL_MS}

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

    def deploy(self, role, release, force_base=False):
        if role not in PORTS:
            raise ValueError('web_service_required')
        with self.lock():
            state = self.state()
            if not state['managed'] or state['phase'] not in ('stable', 'retained'):
                raise ValueError('stable_managed_state_required')
            self.check_base(role, release, state, force_base)
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
            snapshot = self.wait_snapshot(role, new, release)
            warmed = self.warm_web(role, new)
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
            service['retained_at'] = time.time()
            state.pop('pending', None)
            self.save(state, 'retained')
            self.persist(state)
            # Retain the previous, drained process for immediate rollback for RECLAIM_STANDBY_SECONDS;
            # then reclaim_standby stops it (rollback starts it again, in tens of seconds).
            self.drained(role, old)
            self.schedule_reclaim()
            return {'service': role, 'active': new, 'release': release, 'previous_retained': True, 'warmed': warmed,
                    'warm': self.warm_summary(warmed), 'report_snapshot': snapshot}

    def schedule_reclaim(self, delay=RECLAIM_STANDBY_SECONDS):
        """Run reclaim-standby once after DELAY in a detached process; a failure only keeps the standby."""
        if os.environ.get('PYTEST_CURRENT_TEST'):
            return  # tests call reclaim_standby directly; never leave a sleeping process behind
        try:
            logs = self.root / 'logs/services'
            logs.mkdir(parents=True, exist_ok=True)
            with open(logs / 'reclaim-standby.log', 'ab') as output:
                subprocess.Popen(['nice', '-n', '10', sys.executable, '-m', 'scripts.service_deploy', '--root', str(self.root),
                                  'reclaim-standby', '--after', str(int(delay))], cwd=str(self.root),
                                 stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True)
        except Exception:
            pass

    def reclaim_standby(self, min_age=RECLAIM_STANDBY_SECONDS, now=None):
        """Stop each web role's previous slot once its deploy is MIN_AGE old. State keeps the slot and its
        release, so rollback starts the process again before switching."""
        stopped = []
        with self.lock():
            state = self.state()
            if not state.get('managed') or state.get('phase') not in ('stable', 'retained'):
                return {'stopped': stopped, 'skipped': 'phase ' + str(state.get('phase'))}
            now = time.time() if now is None else now
            for role in PORTS:
                service = state['services'].get(role) or {}
                previous, active = service.get('previous'), service.get('active')
                at = service.get('retained_at')
                if previous not in ('a', 'b') or previous == active or type(at) not in (int, float) or now - at < min_age:
                    continue
                if not self.pid(role, previous):
                    continue
                if not self.drained(role, previous, timeout=30):
                    continue
                self.stop(role, previous)
                stopped.append({'role': role, 'slot': previous, 'release': service['slots'].get(previous)})
        return {'stopped': stopped}

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

    def deploy_worker(self, role, release, force_base=False):
        if role not in ('jobs', 'execution'):
            raise ValueError('worker_role_required')
        with self.lock():
            state = self.state()
            if not state['managed'] or state['phase'] not in ('stable', 'retained'):
                raise ValueError('stable_managed_state_required')
            self.check_base(role, release, state, force_base)
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
        """Start each web role's active release again in its other slot and switch to it.

        11-10: restart used to package the working tree (other sessions' uncommitted edits included)
        and deploy that; only a dependency check stopped it. A restart now never changes code: the
        active release is redeployed as it is (its base is its own predecessor, so the base check
        is skipped for this same-release case)."""
        results = []
        for target in (('frontend', 'admin') if role == 'all' else (role,)):
            service = self.state()['services'][target]
            slot = service['slots'][service['active']]
            release = slot['release'] if isinstance(slot, dict) else slot
            results.append(self.deploy(target, release, force_base=True))
        return {'deployments': results, 'workers_restarted': False, 'packaged': False}

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

    def running_releases(self):
        """Releases a live process still points at (slots, gate copies, ad hoc scripts)."""
        listing = subprocess.run(['/bin/ps', '-axww', '-o', 'args='], capture_output=True, text=True, check=True).stdout
        marker = str(self.directory / 'releases') + '/'
        return {line.split(marker, 1)[1].split('/', 1)[0].split()[0] for line in listing.splitlines() if marker in line}

    def prune_releases(self, keep=10, min_age_days=3, apply=False, now=None):
        """Remove old releases (11-04: 461 releases held about 140GB). A dry run unless apply is set.

        Kept: every release named anywhere in state.json (slots, previous, pending, workers), any release a
        running process uses, the newest `keep` releases, and anything younger than `min_age_days`, which
        another session may still be testing or about to deploy.
        """
        now = time.time() if now is None else now
        named = set()
        def walk(value):
            if isinstance(value, dict):
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
            elif isinstance(value, str):
                named.add(value)
        with self.lock():
            walk(self.state())
            releases = self.directory / 'releases'
            found = []
            for path in releases.iterdir() if releases.is_dir() else ():
                if path.name.startswith('.') or path.is_symlink() or not path.is_dir() or not RELEASE.fullmatch(path.name):
                    continue
                try:
                    created = float(json.loads((path / 'release.json').read_text())['created'])
                except (OSError, ValueError, KeyError, TypeError):
                    created = path.stat().st_mtime
                found.append((created, path.name))
            found.sort(reverse=True)
            protected = (named | self.running_releases()) & {name for _, name in found}
            recent = {name for _, name in found[:max(0, keep)]}
            young = {name for created, name in found if now - created < min_age_days * 86400}
            remove = [name for _, name in reversed(found) if name not in protected | recent | young]
            if apply:
                # Rename under the lock (fast) so a half-deleted tree never looks like a release;
                # delete after releasing it so other sessions can keep packaging and deploying.
                for name in remove:
                    (releases / name).rename(releases / ('.pruning-' + name))
        removed = []
        if apply:
            # Also finishes trees an interrupted run left behind.
            for trash in sorted(releases.glob('.pruning-*')):
                if trash.is_dir() and not trash.is_symlink():
                    shutil.rmtree(trash)
                    removed.append(trash.name)
        environments = self.prune_environments(apply)
        return {'releases': len(found), 'protected': sorted(protected), 'kept_recent': len(recent),
                'kept_young': len(young - recent - protected), 'to_remove': len(remove),
                'removed': len(removed), 'applied': apply, 'oldest_removed': remove[:3], 'newest_removed': remove[-3:],
                'unused_environments': environments}

    def prune_after_deploy(self):
        """After a verified deploy keep only what is deployed (11-04 user decision).

        state.json releases (active, rollback slot, worker previous) and running ones stay; so do releases
        packaged in the last AFTER_DEPLOY_MIN_AGE_HOURS that another session may be about to deploy.
        A prune problem never fails the deploy that already succeeded.
        """
        try:
            result = self.prune_releases(keep=0, min_age_days=AFTER_DEPLOY_MIN_AGE_HOURS / 24, apply=True)
            return {key: result[key] for key in ('removed', 'protected', 'kept_young')}
        except BlockingIOError:
            return {'skipped': 'deploy_lock_busy'}
        except Exception as error:
            return {'skipped': type(error).__name__ + ': ' + str(error)[:200]}

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
        # 11-10 operations = git: the commit each active role runs (None = built from files, not a commit).
        active = {role: (service['slots'][service['active']] if role in PORTS else service['release'])
                  for role, service in state['services'].items()}
        result['commits'] = {role: self.release_commit(release) for role, release in active.items()}
        return result

    def release_commit(self, release):
        try:
            return json.loads((self.path(release) / 'release.json').read_text()).get('commit')
        except (OSError, ValueError, AttributeError):
            return None


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


# 11-11: teams started deploys while another team held the status-board deploy lock (one stopped at the
# gate, others waited or guessed). deploy and worker-deploy now read the lock section and require the
# caller's own lock line; another team's line refuses the deploy.
BOARD_TEAMS = ('운영·SRE', '검색과 RAG', '성장·유통', 'AI AD Coin', '오류 감시', '프론트앤드', 'PM')


def board_locks(board):
    """[(team or None, line)] for each line under '## 배포 잠금' in the status board."""
    try:
        text = Path(board).read_text(encoding='utf-8')
    except OSError:
        return None
    locks, inside = [], False
    for line in text.splitlines():
        if line.startswith('## '):
            inside = line.strip() == '## 배포 잠금'
            continue
        entry = line.strip().lstrip('-*').strip().strip('*').strip()
        if not inside or not entry or entry.startswith('(비어 있음)'):
            continue
        team = next((t for t in sorted(BOARD_TEAMS, key=len, reverse=True) if entry.startswith(t)), None)
        locks.append((team, entry))
    return locks


def check_board_lock(root, owner):
    """Refuse unless the status board's lock section holds OWNER's line and no other team's line."""
    if owner not in BOARD_TEAMS:
        raise RuntimeError('deploy_lock_owner_unknown: --lock-owner must be one of ' + ', '.join(BOARD_TEAMS))
    locks = board_locks(Path(root) / 'logs/ops/status-board.md')
    if locks is None:
        return None   # no status board on this machine (tests, another host)
    others = [entry for team, entry in locks if team != owner]
    if others:
        raise RuntimeError('deploy_lock_held_by_another_team: ' + ' / '.join(e[:120] for e in others)
                           + ' (wait for that team to clear its line, or ask the PM)')
    if not locks:
        raise RuntimeError('deploy_lock_not_taken: write "- %s <time> <role> <release>" under ## 배포 잠금 first' % owner)
    return [entry for _, entry in locks]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    commands = parser.add_subparsers(dest='command', required=True)
    package = commands.add_parser('package'); package.add_argument('release')
    package.add_argument('--base', help='the release this tree was overlaid on (deploy checks it is still active)')
    package.add_argument('--commit', default='HEAD', help='build from this commit with git archive (default HEAD; 11-10 operations = git)')
    package.add_argument('--from-tree', action='store_true', help='legacy: copy the files on disk instead of a commit (no commit recorded)')
    deploy = commands.add_parser('deploy'); deploy.add_argument('role', choices=PORTS); deploy.add_argument('release')
    deploy.add_argument('--force-base', action='store_true', help='deploy although the release was built on a release that is no longer active')
    deploy.add_argument('--skip-gate', action='store_true', help='emergency only: deploy a frontend release without scripts.release_gate')
    deploy.add_argument('--no-prune', action='store_true', help='keep old releases after a successful deploy')
    deploy.add_argument('--lock-owner', required=True, help='your team; the status board lock section must hold your line only')
    rollback = commands.add_parser('rollback'); rollback.add_argument('role', choices=PORTS)
    commands.add_parser('status')
    reclaim = commands.add_parser('reclaim-standby', help='stop previous web slots retained longer than --min-age')
    reclaim.add_argument('--after', type=int, default=0, help='wait this many seconds first')
    reclaim.add_argument('--min-age', type=int, default=RECLAIM_STANDBY_SECONDS)
    prune = commands.add_parser('prune-releases', help='dry run unless --apply')
    prune.add_argument('--apply', action='store_true'); prune.add_argument('--keep', type=int, default=10)
    prune.add_argument('--min-age-days', type=float, default=3)
    commands.add_parser('install-schema')
    recovery = commands.add_parser('recover')
    recovery.add_argument('--worker', choices=('jobs', 'execution'))
    recovery.add_argument('--release')
    commands.add_parser('start')
    commands.add_parser('stop')
    restart = commands.add_parser('restart'); restart.add_argument('role', nargs='?', choices=('all', 'frontend', 'admin'), default='all')
    cutover = commands.add_parser('cutover'); cutover.add_argument('release'); cutover.add_argument('--legacy-pid', type=int, required=True)
    worker = commands.add_parser('worker-deploy'); worker.add_argument('role', choices=('jobs', 'execution')); worker.add_argument('release')
    worker.add_argument('--no-prune', action='store_true', help='keep old releases after a successful deploy')
    worker.add_argument('--force-base', action='store_true', help='deploy although the release was built on a release that is no longer active')
    worker.add_argument('--lock-owner', required=True, help='your team; the status board lock section must hold your line only')
    args = parser.parse_args()
    manager = Deployment(args.root)
    if args.command == 'package':
        with manager.lock():
            result = manager.package(args.release, args.base, None if args.from_tree else args.commit)
    elif args.command == 'deploy':
        check_board_lock(args.root, args.lock_owner)
        forced = {'force_base': True} if args.force_base else {}
        if not args.force_base:
            manager.check_base(args.role, args.release)  # before the gate's minute of tests; deploy checks again
        if args.role == 'frontend' and not args.skip_gate:
            release_gate(args.root, args.release)
        result = manager.deploy(args.role, args.release, **forced)
        if not args.no_prune:
            result['pruned'] = manager.prune_after_deploy()
    elif args.command == 'rollback':
        result = manager.rollback(args.role)
    elif args.command == 'reclaim-standby':
        time.sleep(max(0, args.after))
        result = manager.reclaim_standby(args.min_age)
    elif args.command == 'recover':
        result = manager.recover(args.worker, args.release)
    elif args.command == 'prune-releases':
        result = manager.prune_releases(args.keep, args.min_age_days, args.apply)
    elif args.command == 'install-schema':
        result = manager.install_schema()
    elif args.command == 'cutover':
        result = manager.cutover(args.release, args.legacy_pid)
    elif args.command == 'worker-deploy':
        check_board_lock(args.root, args.lock_owner)
        result = manager.deploy_worker(args.role, args.release, **({'force_base': True} if args.force_base else {}))
        if not args.no_prune:
            result['pruned'] = manager.prune_after_deploy()
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
