"""Exercise real independent processes on synthetic PostgreSQL 18 data."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import httpx


def rehearse():
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from scripts.service_deploy import caddyfile
    from agent_market.storage_adapter import open_store
    from agent_market.service_runtime import ServiceControl
    from agent_market.service_host import probe_token
    from agent_market.gateway import admin_auth
    tools = {name: '/opt/homebrew/opt/postgresql@18/bin/' + name for name in ('initdb', 'pg_ctl')}
    root = Path(__file__).resolve().parents[1]
    result = {'isolated': True, 'postgres_major': 18, 'production_modified': False, 'checks': []}
    with _private_cluster(tools) as cluster:
        directory = Path(cluster['root'])
        key = b's' * 32
        connection = psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
        store = open_store('postgresql', connection=connection, workflow_key=key, initialize=True)
        digest, salt = admin_auth.hash_password('Synthetic-rotated-password42', 'synthetic-native-staff')
        token = '6b' * 32
        now = time.time()
        with connection.transaction():
            user = connection.execute('''INSERT INTO admin_users
                (username,password_hash,salt,role,name,active,created_at,updated_at)
                VALUES('synthetic-native',%s,%s,'superadmin','Synthetic staff',1,%s,%s) RETURNING id''',
                (digest, salt, now, now)).fetchone()[0]
            connection.execute('''INSERT INTO admin_sessions
                (token,user_id,username,role,name,created_at,expires_at)
                VALUES(%s,%s,'synthetic-native','superadmin','Synthetic staff',%s,%s)''',
                (admin_auth.session_reference(token), user, now, now + 3600))
        staff = {'X-Dashboard': '1', 'Authorization': 'Bearer ' + token}
        control = ServiceControl(psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True), key)
        control.install()
        store.close(); connection.close()
        (directory / 'key').write_bytes(key)
        (directory / 'dsn').write_text('host=%s port=%d dbname=postgres user=postgres' % (cluster['socket'], PORT))
        settings = directory / 'runtime.env'
        settings.write_text('\n'.join([
            'APPLICATION_STORE_BACKEND=postgresql', 'APPLICATION_POSTGRES_DSN_FILE=' + str(directory / 'dsn'),
            'APPLICATION_WORKFLOW_KEY_FILE=' + str(directory / 'key'),
            'ADMIN_TOKEN=' + 's' * 40, 'AGENT_FRONT_URL=https://fixture.example',
            'CUSTOMER_WORKSPACE_ACCESS_ENABLED=1', 'CUSTOMER_WORKSPACE_LINK_ENABLED=1',
            'WORKSPACE_MODEL_ENABLED=0']) + '\n')
        for file in ('key', 'dsn', 'runtime.env'):
            os.chmod(directory / file, 0o600)
        environment = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
        environment.update(REDIS_PORT='1', SCHEDULER='0', CONCIERGE_LLM='off', PYTHONUNBUFFERED='1',
                           AGENT_DISCOVERY='0', DEPLOYMENT_MODE='development')
        processes = []
        ports = {}
        def port():
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                return sock.getsockname()[1]
        def start(role, version):
            address = port() if role in ('frontend', 'admin') else None
            args = [sys.executable, '-B', '-m', 'agent_market.service_host', '--role', role,
                    '--release', version, '--state-dir', str(directory / 'state'),
                    '--settings', str(settings), '--project-root', str(directory)]
            if address:
                args += ['--port', str(address)]
                ports[(role, version)] = address
            with (directory / (role + '-' + version + '.log')).open('wb') as logs:
                proc = subprocess.Popen(args, cwd=root, env=environment, stdout=logs, stderr=logs)
            processes.append(proc)
            for _ in range(240):
                if proc.poll() is not None:
                    raise RuntimeError(role + '_process_exited')
                try:
                    if address:
                        reply = httpx.get('http://127.0.0.1:%d/internal/service/ready' % address,
                            headers={'X-Service-Probe': probe_token(key)}, timeout=3, trust_env=False)
                        if reply.status_code == 200 and reply.json()['release'] == version:
                            return proc
                    elif control.status(role).get('available'):
                        return proc
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(.25)
            raise RuntimeError(role + '_readiness_timeout')
        try:
            fa = start('frontend', 'a'); aa = start('admin', 'a')
            execution = start('execution', 'worker'); jobs = start('jobs', 'worker')
            fa_pid, aa_pid, jobs_pid, execution_pid = fa.pid, aa.pid, jobs.pid, execution.pid
            fb = start('frontend', 'b'); ab = start('admin', 'b')
            proxy_public, proxy_admin = port(), port()
            config = directory / 'Caddyfile'
            def write(front, admin):
                config.write_text(caddyfile(directory, ports[('frontend', front)], ports[('admin', admin)], proxy_public, proxy_admin))
            write('a', 'a')
            caddy = shutil.which('caddy')
            with (directory / 'proxy.log').open('wb') as logs:
                proxy = subprocess.Popen([caddy, 'run', '--config', str(config), '--adapter', 'caddyfile'], stdout=logs, stderr=logs)
            processes.append(proxy)
            base = 'http://127.0.0.1:' + str(proxy_public)
            admin_base = 'http://127.0.0.1:' + str(proxy_admin)
            def switch(front, admin):
                write(front, admin)
                outcome = subprocess.run([caddy, 'reload', '--config', str(config), '--adapter', 'caddyfile',
                    '--address', 'unix//' + str(directory / 'caddy-admin.sock')], capture_output=True)
                if outcome.returncode:
                    raise RuntimeError('isolated_proxy_reload_failed')
            with httpx.Client(trust_env=False, timeout=15) as client:
                for _ in range(60):
                    try:
                        if client.get(base + '/').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError('isolated_public_origin_failed')
                assert client.get(base + '/admin/ui').status_code == 404
                assert client.get(base + '/internal/service/ready').status_code == 404
                before = client.get(admin_base + '/admin/api/overview', headers=staff)
                assert before.status_code == 200
                samples = []
                def traffic():
                    with httpx.Client(trust_env=False, timeout=15) as reader:
                        for _ in range(20):
                            samples.append(reader.get(base + '/').status_code)
                            time.sleep(.05)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    ongoing = pool.submit(traffic)
                    time.sleep(.2)
                    switch('b', 'a')
                    ongoing.result()
                assert all(status == 200 for status in samples)
                assert (aa.pid, jobs.pid, execution.pid) == (aa_pid, jobs_pid, execution_pid)
                assert all(p.poll() is None for p in (aa, jobs, execution))
                fa.terminate(); fa.wait(timeout=100)
                assert client.get(base + '/').status_code == 200
                result['checks'].append('frontend_swap_and_old_process_stop_preserve_admin_and_workers')
                switch('b', 'b')
                after = client.get(admin_base + '/admin/api/overview', headers=staff)
                assert after.status_code == 200
                assert client.get(admin_base + '/admin/api/overview').status_code in (401, 403)
                aa.terminate(); aa.wait(timeout=100)
                assert client.get(base + '/').status_code == 200
                assert client.get(admin_base + '/admin/api/overview', headers=staff).status_code == 200
                assert all(p.poll() is None for p in (fb, jobs, execution))
                result['checks'].append('admin_swap_and_old_process_stop_preserve_frontend_and_workers')
                result['checks'].append('individual_staff_session_survives_admin_swap')
                result['checks'].append('public_admin_and_private_readiness_blocked')
                result['checks'].append('unauthenticated_admin_api_denied')
                result.update(public_requests=len(samples), public_failures=sum(s != 200 for s in samples),
                              background_processes_unchanged=True)
        except BaseException:
            # Retain only private process diagnostics, never response/customer data.
            evidence = root / 'gateway-data/service-test-diagnostics'
            evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
            for path in directory.glob('*.log'):
                target = evidence / path.name
                shutil.copy2(path, target); os.chmod(target, 0o600)
            raise
        finally:
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
            for proc in reversed(processes):
                proc.wait(timeout=120)
            control.close()
    return result


if __name__ == '__main__':
    result = rehearse()
    path = Path('reports/zero-downtime-service-design-2026-10-22/process-rehearsal.json')
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
