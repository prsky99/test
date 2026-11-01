"""Synthetic acceptance on newly created databases in an existing PostgreSQL server.

Never accepts an existing application database as a write target. No project
server, identity provider, model, payment service or external agent is started.
The same command supports a separately configured TLS PostgreSQL test server.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import getpass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import time
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

PROFILE = 'synthetic-existing-postgres-acceptance-v1'
PREFIX = 'ac_validation_'


def require(value, label):
    if value is not True:
        raise AssertionError(label)


def configuration(path=None):
    if path is None:
        return {'host': '/tmp', 'port': 5432, 'user': getpass.getuser(),
                'dbname': 'postgres', 'sslmode': 'disable', 'connect_timeout': 5}
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as handle:
        info = os.fstat(handle.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) & 0o077 == 0 and info.st_size <= 16384,
                'Connection file must be an owner-only regular file')
        raw = handle.read(16385)
        require(len(raw) <= 16384, 'Connection file is too large')
        value = json.loads(raw)
    allowed = {'host', 'port', 'user', 'password', 'dbname', 'sslmode', 'sslrootcert'}
    require(type(value) is dict and not set(value) - allowed, 'Explicit connection fields required')
    require(all(type(value.get(k)) is str and value[k] and '\x00' not in value[k]
                for k in ('host', 'user', 'dbname')), 'Connection identity required')
    require(type(value.get('port')) is int and 1 <= value['port'] <= 65535, 'Valid port required')
    require(value.get('sslmode') == 'verify-full' or
            (value['host'].startswith('/') and value.get('sslmode') == 'disable'),
            'Remote PostgreSQL requires verified TLS')
    for field in ('password', 'sslrootcert'):
        require(field not in value or type(value[field]) is str, 'Invalid connection field')
    return {**value, 'connect_timeout': 5}


def private_json(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(raw)


def tool_environment(config, database):
    # Do not inherit libpq services, passwords, connection targets or options.
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    fields = {'host': 'PGHOST', 'port': 'PGPORT', 'user': 'PGUSER',
              'password': 'PGPASSWORD', 'sslmode': 'PGSSLMODE', 'sslrootcert': 'PGSSLROOTCERT'}
    env.update({target: str(config[key]) for key, target in fields.items() if key in config})
    env.update(PGDATABASE=database, PGCONNECT_TIMEOUT='5',
               PGPASSFILE=os.devnull, PGSERVICEFILE=os.devnull, PGSYSCONFDIR='/nonexistent')
    return env


def customer_contracts(store, key):
    """Three virtual customers exercise current repositories and execution guards."""
    import httpx
    from agent_market.collector import usage
    from agent_market.concierge.proxy import McpProxy
    from agent_market.customer_identity import CustomerIdentity, GitHubConfig
    from agent_market.customer_organizations import CustomerOrganizations
    from agent_market.customer_workspace_runtime import CustomerWorkspaceAccess
    from agent_market.workspace_access import WorkspaceAccess, WorkspaceDenied
    from agent_market.workspace_execution import WorkspaceExecution, NOTICE
    from agent_market.workspace_release import WorkspaceReleases, DEPLOY_NOTICE, RUN_NOTICE
    from agent_market.workspace_release_service import build_package

    state, calls = {'subject': 10001}, []
    config = GitHubConfig('synthetic-acceptance-client',
                         'https://agentconcierge.biz/api/customer-auth/github/callback',
                         'synthetic-unused-secret')
    spec = {'name': 'search_docs', 'description': 'Read synthetic public documents',
            'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True},
            'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}},
                            'required': ['query']}}

    def provider(request):
        if str(request.url) == config.token_endpoint:
            return httpx.Response(200, json={'access_token': 'synthetic-unused-provider-token',
                                            'token_type': 'bearer'})
        if str(request.url) == config.user_endpoint:
            return httpx.Response(200, json={'id': state['subject']})
        require(str(request.url) == 'https://synthetic-docs.example/mcp', 'Unexpected fixture destination')
        body = json.loads(request.content)
        method = body.get('method')
        if method == 'notifications/initialized':
            return httpx.Response(202)
        if method == 'initialize':
            result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'Synthetic documents', 'version': '1'}}
        elif method == 'tools/list':
            result = {'tools': [spec]}
        elif method == 'tools/call':
            require(body['params']['name'] == spec['name'], 'Selected tool required')
            query = body['params']['arguments']['query']
            calls.append(query)
            result = {'content': [{'type': 'text', 'text': 'Result for ' + query}]}
        else:
            raise AssertionError('Unexpected fixture method')
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})

    http = httpx.Client(transport=httpx.MockTransport(provider), trust_env=False)
    identity = CustomerIdentity(store, key, http=http, github_config=config)
    access = WorkspaceAccess(store, key)
    orgs = CustomerOrganizations(identity, access)
    adapter = CustomerWorkspaceAccess(access, identity)
    proxy = McpProxy(store, allow_private=True, http=http)
    execution = WorkspaceExecution(adapter, proxy)
    app_execution = WorkspaceExecution(adapter, proxy)
    releases = WorkspaceReleases(execution, customer_identity=identity, customer_executor=app_execution)
    app_execution.authority_guard = releases.guard_ticket
    logins = []
    checks = {}
    try:
        for subject in (10001, 10002, 10003):
            state['subject'] = subject
            browser_binding = secrets.token_hex(32)
            start = identity.begin(browser_binding, 'github')
            oauth_state = parse_qs(urlsplit(start['authorization_url']).query)['state'][0]
            logins.append(identity.complete(oauth_state, 'synthetic-one-use-code', browser_binding, 'github'))
        owner, editor, stranger = [identity.actor(x['session_token']) for x in logins]
        ws = orgs.create({'name': 'Synthetic acceptance customers'}, owner)['id']
        invitation = orgs.invite(ws, {'customer_id': editor.customer_id, 'role': 'editor', 'revision': 1}, owner)
        orgs.resolve_invitation(invitation['id'], {'decision': 'accept', 'revision': 1}, editor)
        actor = orgs.runtime_actor(ws, owner)
        checks['virtual_customer_registration_invitation_and_roles'] = orgs.detail(ws, editor)['can_edit']
        try:
            orgs.detail(ws, stranger)
        except WorkspaceDenied:
            checks['other_customer_cannot_read_organization'] = True
        else:
            raise AssertionError('Cross-customer access')

        rid = store.upsert_resource({'key': 'synthetic:acceptance:docs', 'source': 'fixture', 'kind': 'mcp',
            'url': 'https://synthetic-docs.example/mcp', 'name': 'Synthetic documentation',
            'description': 'Isolated acceptance data', 'category': 'dev_tools', 'networks': [],
            'price_usdc': 0, 'details': {}})
        compact = usage.compact_tools([spec])
        store.record_usage(rid, compact, usage.tools_hash(compact), {}, None, {'ok': True}, full_tools=[spec])
        store.record_health(rid, 'healthy', 200, 1, None, time.time() + 3600)
        definition = {'nodes': [
            {'id': 'start', 'name': 'Manual start', 'type': 'trigger', 'kind': 'trigger', 'data': {}},
            {'id': 'lookup', 'name': 'Synthetic lookup', 'type': 'agent', 'kind': 'mcp',
             'resource_id': rid, 'data': {'tool': 'search_docs', 'input': {'query': 'acceptance alpha'}}}],
            'edges': [{'source': 'start', 'target': 'lookup'}]}
        draft = orgs.drafts.save_draft(ws, {'name': 'Synthetic customer task', 'description': '',
                                          'definition': definition}, actor)
        snap = orgs.drafts.create_snapshot(ws, draft['id'], {'draft_revision': 1}, actor)
        args = (ws, draft['id'], snap['id'])
        review = execution.prepare(*args, {'snapshot_revision': 1}, actor)
        require(not calls, 'Review must be offline')
        command = {'ticket_id': review['ticket_id'], 'authorized': True, 'notice': NOTICE}
        run = execution.execute(*args, command, actor)
        require(run['status'] == 'succeeded', 'Native customer execution failed')
        again = execution.execute(*args, command, actor)
        checks['review_single_dispatch_and_idempotent_replay'] = again['replayed'] and calls == ['acceptance alpha']
        checks['input_affects_retained_output'] = 'acceptance alpha' in run['output']['content'][0]['text']
        release = releases.create(*args, {'run_id': run['id'], 'ttl_seconds': 600}, actor)
        origin = 'https://synthetic-app.example'
        app = releases.deploy(*args, release['id'], {'allowed_origins': [origin], 'ttl_seconds': 600,
            'minute_limit': 3, 'day_limit': 5, 'authorized': True, 'notice': DEPLOY_NOTICE}, actor)
        verifier = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        code = releases.authorize(app['app_id'], {'origin': origin, 'redirect_uri': origin + '/bff/callback',
                                  'challenge': challenge, 'state': secrets.token_urlsafe(32)}, owner)
        token = releases.exchange(app['app_id'], {'code': code['code'], 'verifier': verifier,
                                  'redirect_uri': origin + '/bff/callback'}, origin)
        plan = releases.prepare(app['app_id'], token['access_token'], origin)
        result = releases.execute(app['app_id'], token['access_token'], {'ticket_id': plan['ticket_id'],
                                   'authorized': True, 'notice': RUN_NOTICE}, origin)
        checks['sdk_customer_pkce_review_and_run'] = result['run']['status'] == 'succeeded' and len(calls) == 2
        package, _ = build_package(releases.package_config(*args, app['app_id'], actor))
        with ZipFile(BytesIO(package)) as archive:
            contents = b'\n'.join(archive.read(name) for name in archive.namelist())
            checks['sdk_package_has_no_customer_or_access_tokens'] = all(
                value.encode() not in contents for value in (token['access_token'], logins[0]['session_token']))
        releases.revoke(*args, release['id'], {'revision': 1}, actor)
        try:
            releases.prepare(app['app_id'], token['access_token'], origin)
        except WorkspaceDenied:
            checks['withdrawal_blocks_sdk_dispatch'] = len(calls) == 2
        else:
            raise AssertionError('Revoked app accepted')
        with store.tx(readonly=True):
            checks['no_staff_membership_created'] = store._execute(
                'SELECT COUNT(*) FROM workspace_memberships WHERE workspace_id=%s', (ws,)).fetchone()[0] == 0
        retained = {'run_id': run['id'], 'output_sha256': hashlib.sha256(
                    json.dumps(run['output'], sort_keys=True).encode()).hexdigest()}
        for login in logins:
            require(identity.logout(login['session_token'])['signed_out'], 'Logout required before backup')
        checks['all_virtual_customer_sessions_revoked_before_backup'] = True
        require(all(checks.values()), 'Synthetic customer contract')
        return checks, retained, {'config': config, 'token': logins[0]['session_token']}
    finally:
        http.close()


def workload(connect, workers, operations):
    def worker(number):
        durations = []
        with connect() as db:
            for index in range(operations):
                start = time.monotonic()
                with db.transaction():
                    db.execute('INSERT INTO acceptance_probe.load VALUES (%s,%s)', (number * operations + index, 'synthetic'))
                    db.execute('UPDATE acceptance_probe.counter SET value=value+1 WHERE id=1')
                durations.append((time.monotonic() - start) * 1000)
        return durations
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        durations = sorted(value for batch in pool.map(worker, range(workers)) for value in batch)
    with connect() as db:
        require(db.execute('SELECT value FROM acceptance_probe.counter WHERE id=1').fetchone()[0]
                == workers * operations, 'Concurrent update lost data')
        require(db.execute('SELECT count(*) FROM acceptance_probe.load').fetchone()[0]
                == workers * operations, 'Concurrent insert count')
    return {'workers': workers, 'transactions': len(durations), 'seconds': time.monotonic() - started,
            'transaction_ms_p50': durations[len(durations) // 2],
            'transaction_ms_p95': durations[min(len(durations) - 1, int(len(durations) * .95))]}


def run(config, output, workers=4, operations=25):
    import psycopg
    from psycopg import sql
    from agent_market.storage_adapter import open_store
    from agent_market.customer_identity import CustomerIdentity
    from agent_market.workspace_access import WorkspaceDenied
    # An inherited operating keyring must never sign these synthetic records.
    from agent_market.private_artifact_keys import ENV
    require(not os.environ.get(ENV), 'Unset the operating artifact keyring for this synthetic command')
    require(not any(name.startswith('PG') for name in os.environ),
            'Unset inherited libpq settings; use the explicit connection file')
    require(type(workers) is int and 2 <= workers <= 8 and type(operations) is int
            and 1 <= operations <= 100, 'Bounded synthetic workload required')
    output = Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    run_id = secrets.token_hex(10)
    source, restored = PREFIX + run_id, PREFIX + run_id + '_restore'
    tools = {name: shutil.which(name) for name in ('pg_dump', 'pg_restore')}
    require(all(tools.values()), 'PostgreSQL tools unavailable')
    settings = {**config, 'autocommit': True, 'application_name': 'agentconcierge-synthetic-acceptance'}
    created = []
    report = {'profile': PROFILE, 'started_at': datetime.now(timezone.utc).isoformat(),
              'synthetic': True, 'production_database_modified': False, 'project_server_actions': 0,
              'provider_network_calls': 0, 'source_database': source, 'restore_database': restored,
              'created_databases': created, 'completed': False,
              'ha_failover_verified': False, 'production_capacity_claim': False,
              'recovery_scope': 'Logical dump/restore on one server; not PITR, HA or a full outage RTO.'}
    try:
        with psycopg.connect(**settings) as admin:
            report['postgresql_version'] = admin.info.server_version
            report['transport_tls'] = bool(admin.pgconn.ssl_in_use)
            for database in (source, restored):
                # No IF EXISTS, existing target, rename, truncate or drop is accepted.
                admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(database)))
                created.append(database)
                with psycopg.connect(**{**settings, 'dbname': database}) as db:
                    db.execute('CREATE SCHEMA acceptance_probe')
                    db.execute('CREATE TABLE acceptance_probe.owner (run_id text PRIMARY KEY)')
                    db.execute('INSERT INTO acceptance_probe.owner VALUES (%s)', (run_id,))
        def connect(database=source):
            db = psycopg.connect(**{**settings, 'dbname': database})
            require(db.info.dbname in created, 'Only newly created targets are allowed')
            return db
        key = secrets.token_bytes(32)
        with connect() as db:
            store = open_store('postgresql', connection=db, initialize=True, workflow_key=key)
            try:
                checks, retained, customer = customer_contracts(store, key)
                report['checks'] = checks
                store.set_meta('synthetic-backup-checkpoint', {'run_id': run_id, 'scope': 'synthetic'})
                try:
                    with store.tx():
                        store.set_meta('synthetic-rollback', 'must-not-commit')
                        raise ValueError('Synthetic rollback')
                except ValueError:
                    pass
                checks['application_transaction_rolls_back'] = store.get_meta('synthetic-rollback') is None
                report['application_tables'] = db.execute(
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
            finally:
                store.close()
            db.execute('CREATE TABLE acceptance_probe.load (id integer PRIMARY KEY, payload text NOT NULL)')
            db.execute('CREATE TABLE acceptance_probe.counter (id integer PRIMARY KEY,value integer NOT NULL)')
            db.execute('INSERT INTO acceptance_probe.counter VALUES (1,0)')
            db.execute('CREATE TABLE acceptance_probe.claim (id integer PRIMARY KEY, fence integer NOT NULL, owner text)')
            db.execute('INSERT INTO acceptance_probe.claim VALUES (1,0,NULL)')
        report['load'] = workload(connect, workers, operations)
        def claim(number):
            with connect() as db:
                return db.execute('UPDATE acceptance_probe.claim SET owner=%s,fence=fence+1 '
                                  'WHERE id=1 AND owner IS NULL RETURNING fence', (str(number),)).fetchone()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            claims = list(pool.map(claim, range(workers)))
        report['checks']['concurrent_claim_has_exactly_one_winner'] = sum(x is not None for x in claims) == 1
        with connect() as db:
            report['checks']['stale_fence_update_denied'] = db.execute(
                'UPDATE acceptance_probe.claim SET owner=%s WHERE id=1 AND fence=0 RETURNING fence', ('stale',)).fetchone() is None
            try:
                with db.transaction():
                    db.execute('INSERT INTO acceptance_probe.load VALUES (-1,%s)', ('rollback',))
                    raise ValueError('Synthetic uncommitted transaction')
            except ValueError:
                pass
        with connect() as db:
            report['checks']['reconnect_preserves_commits_and_excludes_rollback'] = db.execute(
                'SELECT count(*) FROM acceptance_probe.load WHERE id=-1').fetchone()[0] == 0
        # A new empty restore DB contains only this run's ownership marker.
        with connect(restored) as db:
            require(db.execute('SELECT run_id FROM acceptance_probe.owner').fetchone() == (run_id,), 'Owned restore target')
            db.execute('DROP SCHEMA acceptance_probe CASCADE')
        backup = output / 'synthetic.dump'
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        started = time.monotonic()
        with os.fdopen(fd, 'wb') as archive:
            result = subprocess.run([tools['pg_dump'], '--format=custom', '--no-owner', '--no-acl'],
                env=tool_environment(config, source), stdout=archive, stderr=subprocess.PIPE, timeout=120)
        require(result.returncode == 0, 'Logical backup failed; inspect tool/version/connection configuration')
        report['backup_seconds'] = time.monotonic() - started
        with connect() as db:
            db.execute('INSERT INTO acceptance_probe.load VALUES (-2,%s)', ('after-backup-checkpoint',))
        started = time.monotonic()
        result = subprocess.run([tools['pg_restore'], '--dbname=' + restored, '--no-owner', '--no-acl', '--exit-on-error',
                                 '--single-transaction', str(backup)], env=tool_environment(config, restored),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        require(result.returncode == 0, 'Logical restore failed; inspect tool/version/connection configuration')
        report['logical_restore_seconds'] = time.monotonic() - started
        with connect(restored) as db:
            require(db.execute('SELECT run_id FROM acceptance_probe.owner').fetchone() == (run_id,), 'Restored ownership marker')
            checks = report['checks']
            checks['restore_contains_all_before_checkpoint_transactions'] = db.execute(
                'SELECT count(*) FROM acceptance_probe.load').fetchone()[0] == workers * operations
            checks['restore_excludes_exactly_one_after_checkpoint_transaction'] = db.execute(
                'SELECT count(*) FROM acceptance_probe.load WHERE id=-2').fetchone()[0] == 0
            store = open_store('postgresql', connection=db, workflow_key=key)
            try:
                checks['application_checkpoint_survives_restore'] = store.get_meta('synthetic-backup-checkpoint') == {
                    'run_id': run_id, 'scope': 'synthetic'}
                row = db.execute('SELECT payload FROM workspace_private_runs WHERE id=%s',
                                 (retained['run_id'],)).fetchone()
                checks['retained_workflow_output_survives_restore'] = hashlib.sha256(
                    json.dumps(json.loads(row[0])['output'], sort_keys=True).encode()).hexdigest() == retained['output_sha256']
                identity = CustomerIdentity(store, key, github_config=customer['config'])
                try:
                    identity.actor(customer['token'])
                except WorkspaceDenied:
                    checks['restore_does_not_revive_logged_out_session'] = True
                else:
                    raise AssertionError('Restored revoked session')
            finally:
                store.close()
        report['backup_sha256'] = hashlib.sha256(backup.read_bytes()).hexdigest()
        report['backup_bytes'] = backup.stat().st_size
        report['rpo_observation'] = {'before_checkpoint_transactions_lost': 0,
                                     'deliberate_after_checkpoint_transactions_not_in_snapshot': 1}
        require(all(report['checks'].values()), 'Acceptance check failed')
        report['completed'] = True
        return report
    except Exception as error:
        report['failure_type'] = type(error).__name__
        if isinstance(error, AssertionError):
            report['failure_check'] = str(error)
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        private_json(output / 'result.json', report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--local', action='store_true', help='Existing /tmp PostgreSQL socket, current OS user')
    source.add_argument('--connection-file', help='Owner-only JSON; remote connections require verify-full')
    parser.add_argument('--output', required=True, help='New private output directory')
    parser.add_argument('--workers', type=int, default=4, metavar='2..8')
    parser.add_argument('--operations', type=int, default=25, metavar='1..100')
    parser.add_argument('--run', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        result = run(configuration(args.connection_file), args.output, args.workers, args.operations)
    except Exception as error:
        # Connection strings, raw server errors and tokens must never be printed.
        print(json.dumps({'completed': False, 'error_type': type(error).__name__,
                          'detail': str(error) if isinstance(error, AssertionError) else 'Validation failed; inspect the private result file.'}))
        return 1
    print(json.dumps({'completed': result['completed'], 'checks': len(result['checks']),
                      'source_database': result['source_database'], 'restore_database': result['restore_database']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
