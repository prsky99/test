"""Native durable worker and private archive contracts on disposable PostgreSQL.

Only --run is accepted. This fixture creates a private Unix-only cluster, uses
synthetic MCP transports, and removes its cluster after confirmed shutdown. It
does not accept operating database configuration or activate delivery/schedules.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster, PORT

PROFILE = 'native-workflow-private-archive-contracts-v1'
KEY = b'synthetic-native-workflow-key-32'


def require(value, label):
    if value is not True:
        raise AssertionError(label)


def _connection(cluster, database='postgres'):
    driver = _driver()
    value = driver.connect(host=cluster['socket'], hostaddr='', port=PORT, dbname=database,
        user='postgres', password='synthetic-unused-password', connect_timeout=3,
        passfile=str(Path(cluster['root']) / 'no-password-file'), autocommit=True,
        sslmode='disable', gssencmode='disable')
    with value.cursor() as cursor:
        cursor.execute("SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr()")
        require(cursor.fetchone() == ('', None, None) and value.info.host == cluster['socket'], 'private Unix transport')
    return value


def _network_guard(cluster):
    original = socket.socket.connect
    def connect(current, address):
        if current.family != socket.AF_UNIX or not str(address).startswith(cluster['socket'] + '/'):
            raise AssertionError('Unexpected socket destination in native workflow fixture')
        return original(current, address)
    socket.socket.connect = connect
    def resolve(*_args, **_kwargs):
        raise AssertionError('Unexpected name resolution in native workflow fixture')
    socket.getaddrinfo = resolve


def _proxy(store, audit):
    import httpx
    from agent_market.concierge.proxy import McpProxy
    from tests.test_mcp_proxy import MockRemoteMcp, WEATHER_TOOL
    remote = MockRemoteMcp([WEATHER_TOOL])
    original = remote.handle_request
    def handle(request):
        body = json.loads(request.content or '{}')
        if body.get('method') == 'tools/call':
            with audit.open('a') as output:
                output.write(json.dumps({'city': body['params']['arguments']['city']}) + '\n')
                output.flush(); os.fsync(output.fileno())
        return original(request)
    remote.handle_request = handle
    http = httpx.Client(transport=remote)
    return McpProxy(store, allow_private=True, http=http), http


def _rows(audit):
    return [json.loads(line) for line in audit.read_text().splitlines()] if audit.exists() else []


def _crash_worker():
    cluster, run_id, mode = json.loads(sys.stdin.read(8192))
    _network_guard(cluster)
    from agent_market.storage_adapter import open_store
    from agent_market.workflows import WorkflowRuntime
    connection = _connection(cluster)
    store = open_store('postgresql', connection=connection, workflow_key=KEY)
    proxy, http = _proxy(store, Path(cluster['root']) / 'calls.jsonl')
    runtime = WorkflowRuntime(store, proxy=proxy, courier=None)
    def die():
        os.kill(os.getpid(), signal.SIGKILL)
    if mode == 'prepared':
        prior = runtime.persistence.prepare
        def prepare(*args, **kwargs):
            prior(*args, **kwargs); die()
        runtime.persistence.prepare = prepare
    elif mode == 'dispatched':
        prior = runtime.persistence.dispatch
        def dispatch(*args, **kwargs):
            prior(*args, **kwargs); die()
        runtime.persistence.dispatch = dispatch
    elif mode == 'checkpoint':
        prior = runtime.persistence.checkpoint
        def checkpoint(*args, **kwargs):
            result = prior(*args, **kwargs)
            if args[3] == 'a': die()
            return result
        runtime.persistence.checkpoint = checkpoint
    else:
        raise AssertionError('Unrecognized crash boundary')
    runtime._execute(run_id)
    raise AssertionError('Crash boundary was not reached')


def _contracts(cluster, archive_tools):
    from agent_market.storage_adapter import open_store
    from agent_market.collector import usage
    from agent_market.workflows import WorkflowRuntime, canonical
    from agent_market.workflow_persistence import DurableRuns, FenceLost
    from agent_market.workflow_postgres import PostgresWorkflowWorker, NativeWorkflowUnavailable
    from agent_market.workflow_postgres_archive import backup, restore, NativeArchiveUnavailable
    from tests.test_mcp_proxy import WEATHER_TOOL
    root = Path(cluster['root']); audit = root / 'calls.jsonl'
    connection = _connection(cluster)
    store = open_store('postgresql', connection=connection, initialize=True, workflow_key=KEY)
    proxy, http = _proxy(store, audit)
    runtime = WorkflowRuntime(store, proxy=proxy, courier=None)
    checks = {}
    def sql(statement, params=()):
        with connection.cursor() as cursor:
            cursor.execute(statement, params)
            return cursor.fetchall() if cursor.description else []
    def rejected(function, exception, code=None):
        try: function()
        except exception as error: return code is None or getattr(error, 'code', None) == code
        return False
    def workflow(cities=('A',)):
        identity = store.create_workflow({'name': 'Native durable synthetic workflow', 'nodes': [
            {'id': chr(97 + index), 'name': 'Weather', 'type': 'agent', 'kind': 'mcp',
             'data': {'resource_id': rid, 'action': 'get_weather', 'input': {'city': city}}}
            for index, city in enumerate(cities)],
            'edges': [{'source': chr(97 + i), 'target': chr(98 + i)} for i in range(len(cities) - 1)]})
        return store.get_workflow(identity)
    def queued(definition):
        launch = runtime.launch; runtime.launch = lambda _identity: None
        try: return runtime.submit(definition)
        finally: runtime.launch = launch
    def crash(job, mode):
        result = subprocess.run([sys.executable, '-B', '-c',
            'from scripts.rehearse_workflow_native_postgres import _crash_worker; _crash_worker()'],
            input=json.dumps([cluster, job['run_id'], mode]), env=dict(os.environ),
            text=True, capture_output=True, timeout=20)
        require(result.returncode == -signal.SIGKILL, 'native crash boundary ' + mode + ': ' + result.stderr[-1000:])
        sql('UPDATE workflow_runs SET lease_until=0 WHERE id=%s', (job['run_id'],))
    def drain():
        owned = _connection(cluster)
        worker = PostgresWorkflowWorker(owned, workflow_key=KEY, proxy=proxy)
        try:
            value = worker.tick(execute=True); worker.wait(timeout=20)
            return value
        finally: worker.close(); owned.close()
    try:
        rid = store.upsert_resource({'key': 'synthetic:durable-weather', 'kind': 'mcp', 'source': 'fixture',
            'url': 'https://weather.example/mcp', 'name': 'Synthetic weather', 'description': 'Weather lookup',
            'category': 'travel_maps_weather', 'details': {}, 'price_usdc': 0})
        compact = usage.compact_tools([WEATHER_TOOL])
        store.record_usage(rid, tools=compact, digest=usage.tools_hash(compact), guide={}, changes=None, trial={'ok': True})
        first = queued(workflow())
        attached = _connection(cluster)
        worker = PostgresWorkflowWorker(attached, workflow_key=KEY)
        try:
            before = len(_rows(audit)); summary = worker.tick()
            checks['storage_only_tick_does_not_invoke_or_deliver'] = len(_rows(audit)) == before and summary['queue_wakeups'] == 0
            checks['execute_requires_explicit_proxy'] = rejected(lambda: worker.tick(execute=True), NativeWorkflowUnavailable, 'explicit_proxy_required')
        finally: worker.close()
        checks['worker_close_preserves_caller_connection'] = not attached.closed
        attached.close()
        drain()
        checks['actual_mock_mcp_execution_and_atomic_finish'] = runtime.get(first['run_id'])['status'] == 'succeeded' and len(_rows(audit)) == 1

        # The pool belongs to the module, not each attachment. Reattaching must
        # not create an executor/heartbeat or close the caller's connection.
        before_threads = {thread.ident for thread in threading.enumerate()}
        for _ in range(8):
            current = _connection(cluster)
            transient = PostgresWorkflowWorker(current, workflow_key=KEY)
            transient.close(); require(not current.closed, 'caller connection retained'); current.close()
        checks['repeated_worker_attachments_do_not_leak_threads'] = {thread.ident for thread in threading.enumerate()} == before_threads

        pulse_job = queued(workflow(('PULSE',))); entered, release = threading.Event(), threading.Event()
        handle = http._transport.handle_request
        def pause(request):
            body = json.loads(request.content or '{}')
            if body.get('method') == 'tools/call' and body['params']['arguments']['city'] == 'PULSE':
                entered.set(); release.wait(6)
            return handle(request)
        http._transport.handle_request = pause
        current = _connection(cluster); live = PostgresWorkflowWorker(current, workflow_key=KEY, proxy=proxy)
        try:
            live.tick(execute=True); require(entered.wait(3), 'live provider reached')
            before_lease, deadline = sql('SELECT lease_until,deadline FROM workflow_runs WHERE id=%s', (pulse_job['run_id'],))[0]
            checks['live_worker_close_refused_until_execution_finishes'] = rejected(live.close, NativeWorkflowUnavailable, 'worker_still_active') and not current.closed
            until = time.monotonic() + 4
            lease, current_deadline = before_lease, deadline
            while lease <= before_lease and time.monotonic() < until:
                time.sleep(.02)
                lease, current_deadline = sql('SELECT lease_until,deadline FROM workflow_runs WHERE id=%s', (pulse_job['run_id'],))[0]
            checks['native_heartbeat_renews_lease_without_extending_deadline'] = lease > before_lease and current_deadline == deadline
        finally:
            release.set(); live.wait(timeout=10); live.close(); current.close(); http._transport.handle_request = handle
        checks['finished_native_worker_has_no_orphan_heartbeat'] = not any(thread.name == 'workflow-lease' for thread in threading.enumerate())

        job = queued(workflow(('B',))); count = len(_rows(audit)); crash(job, 'prepared')
        prior_deadline = sql('SELECT deadline FROM workflow_runs WHERE id=%s', (job['run_id'],))[0][0]
        drain()
        checks['sigkill_prepared_resumes_once_with_original_deadline'] = (runtime.get(job['run_id'])['status'] == 'succeeded'
            and len(_rows(audit)) == count + 1 and sql('SELECT deadline FROM workflow_runs WHERE id=%s', (job['run_id'],))[0][0] == prior_deadline)

        job = queued(workflow(('C', 'D'))); count = len(_rows(audit)); crash(job, 'checkpoint'); drain()
        checks['sigkill_signed_checkpoint_is_reused_without_replay'] = (runtime.get(job['run_id'])['status'] == 'succeeded'
            and _rows(audit)[count:] == [{'city': 'C'}, {'city': 'D'}]
            and sql('SELECT COUNT(*) FROM workflow_checkpoints WHERE run_id=%s', (job['run_id'],))[0][0] == 2)

        job = queued(workflow(('E', 'F'))); count = len(_rows(audit)); crash(job, 'checkpoint')
        sql('UPDATE workflow_checkpoints SET signature=%s WHERE run_id=%s', ('0' * 64, job['run_id']))
        drain()
        checks['tampered_checkpoint_denies_remaining_dispatch'] = runtime.get(job['run_id'])['status'] == 'failed' and len(_rows(audit)) == count + 1

        unknown = queued(workflow(('G',))); count = len(_rows(audit)); crash(unknown, 'dispatched')
        for _ in range(2): drain()
        checks['sigkill_dispatched_is_unknown_and_never_retried'] = (runtime.get(unknown['run_id'])['execution_outcome'] == 'unknown'
            and len(_rows(audit)) == count and sql('SELECT status FROM workflow_execution_attempts WHERE run_id=%s', (unknown['run_id'],))[0][0] == 'unknown')

        # Native writer transactions serialize cross-connection claims; a stale
        # worker can neither dispatch nor complete the new owner's execution.
        jobs = [queued(workflow()) for _ in range(5)]
        stores, connections = [], []
        for _ in range(4):
            current = _connection(cluster); connections.append(current)
            stores.append(open_store('postgresql', connection=current, workflow_key=KEY))
        repositories = [DurableRuns(current) for current in stores]
        barrier = threading.Barrier(4)
        def claim(index):
            barrier.wait(timeout=5)
            return repositories[index].claim(jobs[0]['run_id'], 'fixture-' + str(index), 25)
        try:
            with ThreadPoolExecutor(max_workers=4) as pool: winners = list(pool.map(claim, range(4)))
            winner = next(row for row in winners if row)
            checks['cross_connection_cas_single_winner'] = sum(bool(row) for row in winners) == 1
            claimed = [runtime.persistence.claim(item['run_id'], 'capacity-fixture', 25) for item in jobs[1:]]
            checks['cross_connection_global_active_capacity_four'] = all(claimed[:3]) and claimed[3] is None
            checks['stale_fence_cannot_dispatch'] = rejected(lambda: runtime.persistence.prepare(jobs[0]['run_id'], 'old-worker', winner['fence'], 'a', '0' * 64), FenceLost)
        finally:
            for current in stores: current.close()
            for current in connections: current.close()
        sql('UPDATE workflow_runs SET lease_until=0,deadline=0 WHERE status=%s', ('running',))
        drain()

        # No network courier is attached. Inspect both recovery states directly.
        for suffix, state in (('claimed', 'claimed'), ('dispatched', 'dispatched')):
            sql("INSERT INTO workflow_result_outbox(id,run_id,destination_id,status,owner,fence,lease_until,created) VALUES(%s,%s,%s,%s,%s,1,0,%s)",
                ('fixture-outbox-' + suffix, 'fixture-run-' + suffix, 'fixture-destination', state, 'old-worker', time.time()))
        runtime.persistence.recover()
        checks['outbox_predispatch_requeues_postdispatch_unknown'] = sql('SELECT status FROM workflow_result_outbox ORDER BY id') == [('pending',), ('unknown',)]
        count = len(_rows(audit)); drain()
        checks['worker_does_not_drain_delivery_or_create_schedules'] = len(_rows(audit)) == count and sql("SELECT COUNT(*) FROM workflow_result_outbox WHERE status='pending'")[0][0] == 1

        # Include a queued run and live session/destination authority in the
        # snapshot; restoration must revoke all of it before returning success.
        pending = queued(workflow(('RESTORED-NEVER-CALL',)))
        sql("INSERT INTO workflow_destinations(id,workflow_id,channel,sealed,state,expires,created,notice) VALUES('restore-destination',%s,'webhook','private-ciphertext','verified',%s,%s,'workflow-results-v1')", (1, time.time() + 60, time.time()))
        sql("INSERT INTO workspace_typed_flows(id,workspace_id,version_id,revision,active,payload,signature) VALUES('fixture-flow','fixture-workspace','fixture-version',1,1,'{}','synthetic')")
        store.set_credential('SYNTHETIC_NATIVE_ARCHIVE', 'synthetic-private-vault-value', 'fixture')
        credential_before = sql('SELECT key_value FROM platform_credentials WHERE key_name=%s', ('SYNTHETIC_NATIVE_ARCHIVE',))[0][0]
        sql("INSERT INTO agent_credits(account_id,balance,held,total_deposited,total_spent,updated_at) VALUES('synthetic-account',70,30,100,0,%s)", (time.time(),))
        sql("INSERT INTO clearing_ledger(tx_id,account_id,resource_id,tool_name,amount,status,created_at) VALUES('synthetic-held','synthetic-account',%s,'get_weather',30,'held',%s)", (rid, time.time()))
        # Backup artifact keys are synthetic and external to the archive.
        ring = root / 'keys.json'
        def keys(active='a', revoke_a=False):
            value = {'profile': 'private-artifact-keys-v1', 'active_signing': active, 'active_encryption': active, 'allow_legacy': True,
                'keys': [{'id': identity, 'key': base64.b64encode(material * 32).decode(), 'verify_until': time.time() + 3600, 'revoked': revoke_a and identity == 'a'}
                    for identity, material in (('a', b'a'), ('b', b'b'))]}
            ring.write_text(json.dumps(value)); ring.chmod(0o600); os.environ['AGENT_PRIVATE_ARTIFACT_KEYRING'] = str(ring)
        keys()
        archive = root / 'archive'; manifest = backup(connection, archive, workflow_key=KEY, cluster=cluster, tools=archive_tools, encrypt=True)
        checks['archive_authenticated_encrypted_without_key_export'] = (manifest['encrypted'] is True and manifest['signature'].startswith('ak1.a.')
            and {path.name for path in archive.iterdir()} == {'application.dump.sealed', 'manifest.json'}
            and b'RESTORED-NEVER-CALL' not in (archive / 'application.dump.sealed').read_bytes()
            and all(path.stat().st_mode & 0o777 == 0o600 for path in archive.iterdir()))
        sql('CREATE DATABASE native_restored')
        restored_connection = _connection(cluster, 'native_restored')
        try:
            checks['wrong_workflow_key_refused_even_with_current_artifact_key'] = rejected(lambda: restore(restored_connection, archive, workflow_key=b'x' * 32, cluster=cluster, tools=archive_tools), NativeArchiveUnavailable, 'archive_authentication_failed')
            keys(active='b', revoke_a=True)
            checks['revoked_archive_key_fails_before_target_changes'] = rejected(lambda: restore(restored_connection, archive, workflow_key=KEY, cluster=cluster, tools=archive_tools), NativeArchiveUnavailable, 'archive_authentication_failed')
            keys(active='b')
            restored = restore(restored_connection, archive, workflow_key=KEY, cluster=cluster, tools=archive_tools)
            current = open_store('postgresql', connection=restored_connection, workflow_key=KEY)
            try:
                def scalar(query, params=()):
                    with restored_connection.cursor() as cursor:
                        cursor.execute(query, params); return cursor.fetchone()[0]
                checks['rotated_previous_key_restores_only_quarantined_state'] = (restored['runtime_controls'] == 'paused'
                    and scalar('SELECT status FROM workflow_runs WHERE id=%s', (pending['run_id'],)) == 'failed'
                    and scalar('SELECT execution_outcome FROM workflow_runs WHERE id=%s', (pending['run_id'],)) == 'unknown'
                    and scalar('SELECT invoke_enabled+workflow_enabled+delivery_enabled FROM execution_controls') == 0
                    and scalar("SELECT COUNT(*) FROM workflow_destinations WHERE state='verified'") == 0
                    and scalar('SELECT COUNT(*) FROM workspace_typed_flow_restore_blocks WHERE id=%s', ('fixture-flow',)) == 1
                    and scalar("SELECT COUNT(*) FROM workflow_result_outbox WHERE status IN ('pending','claimed','dispatched')") == 0)
                checks['restore_does_not_overwrite_existing_target'] = rejected(lambda: restore(restored_connection, archive, workflow_key=KEY, cluster=cluster, tools=archive_tools), NativeArchiveUnavailable, 'new_empty_target_required')
                checks['restore_preserves_vault_ciphertext_and_held_ledger_without_sweep'] = (
                    scalar('SELECT key_value FROM platform_credentials WHERE key_name=%s', ('SYNTHETIC_NATIVE_ARCHIVE',)) == credential_before
                    and scalar('SELECT status FROM clearing_ledger WHERE tx_id=%s', ('synthetic-held',)) == 'held'
                    and scalar('SELECT balance+held FROM agent_credits WHERE account_id=%s', ('synthetic-account',)) == 100)
                other = PostgresWorkflowWorker(restored_connection, workflow_key=KEY, proxy=proxy)
                try: other.tick(execute=True); other.wait(timeout=10)
                finally: other.close()
                checks['restored_unknown_never_replays_or_sends'] = len(_rows(audit)) == count and not restored['automatic_replay']
            finally: current.close()
        finally: restored_connection.close()
        sql('CREATE DATABASE native_tampered')
        tampered_connection = _connection(cluster, 'native_tampered')
        try:
            guarded = True
            for create, remove in (
                ('CREATE SEQUENCE public.fixture_sequence', 'DROP SEQUENCE public.fixture_sequence'),
                ('CREATE VIEW public.fixture_view AS SELECT 1 AS value', 'DROP VIEW public.fixture_view'),
                ('CREATE MATERIALIZED VIEW public.fixture_materialized AS SELECT 1 AS value', 'DROP MATERIALIZED VIEW public.fixture_materialized'),
                ("CREATE FUNCTION public.fixture_function() RETURNS integer LANGUAGE sql AS 'SELECT 1'", 'DROP FUNCTION public.fixture_function()')):
                with tampered_connection.cursor() as cursor: cursor.execute(create)
                guarded &= rejected(lambda: restore(tampered_connection, archive, workflow_key=KEY, cluster=cluster, tools=archive_tools), NativeArchiveUnavailable, 'new_empty_target_required')
                with tampered_connection.cursor() as cursor: cursor.execute(remove)
            checks['restore_refuses_sequences_views_materialized_views_functions'] = guarded
            sealed = archive / 'application.dump.sealed'; raw = sealed.read_bytes(); sealed.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            checks['tampered_archive_refused_before_restore'] = rejected(lambda: restore(tampered_connection, archive, workflow_key=KEY, cluster=cluster, tools=archive_tools), NativeArchiveUnavailable, 'archive_authentication_failed')
            with tampered_connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'")
                checks['tampered_archive_refused_before_restore'] &= cursor.fetchone()[0] == 0
        finally: tampered_connection.close()
        guarded = True
        for create, remove in (
            ('CREATE TABLE unrelated_private_data(id BIGINT PRIMARY KEY)', 'DROP TABLE unrelated_private_data'),
            ('CREATE MATERIALIZED VIEW unrelated_private_data AS SELECT 1 AS value', 'DROP MATERIALIZED VIEW unrelated_private_data'),
            ('CREATE SEQUENCE unrelated_private_data', 'DROP SEQUENCE unrelated_private_data')):
            sql(create)
            guarded &= rejected(lambda: backup(connection, root / 'refused-archive', workflow_key=KEY, cluster=cluster, tools=archive_tools), NativeArchiveUnavailable, 'archive_schema_scope_mismatch')
            sql(remove)
        checks['unrelated_source_objects_refuse_archive_export'] = guarded
        require(all(value is True for value in checks.values()), 'native workflow/archive contracts: ' + json.dumps(checks, sort_keys=True))
        return checks
    finally:
        for future in list(runtime.futures.values()): future.result(timeout=5)
        http.close(); store.close(); connection.close()


def _worker():
    config = json.loads(sys.stdin.read(8192))
    cluster = config['cluster']; root = Path(cluster['root'])
    require(root.parent == Path('/private/tmp') and root.name.startswith('a2a-adapter-pg-')
        and cluster['socket'] == str(root / 'socket'), 'owned cluster descriptor')
    require(not any(key.startswith('PG') and key not in ('PGPASSFILE', 'PGSERVICEFILE', 'PGSYSCONFDIR') for key in os.environ), 'clean libpq environment')
    _network_guard(cluster)
    checks = _contracts(cluster, config['tools'])
    print(json.dumps({'checks': checks}, sort_keys=True, allow_nan=False))


def rehearse():
    driver = _driver(); commands = _tools()
    archive_tools = {name: str(Path(commands['pg_ctl']).parent / name) for name in ('pg_dump', 'pg_restore')}
    with _private_cluster(commands) as fixture:
        cluster = {name: fixture[name] for name in ('root', 'socket')}
        environment = dict(fixture['environment'])
        environment.update(PYTHONDONTWRITEBYTECODE='1', REDIS_HOST='127.0.0.1', REDIS_PORT='9')
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(driver.__file__).resolve().parent.parent)
        result = subprocess.run([sys.executable, '-B', '-c',
            'from scripts.rehearse_workflow_native_postgres import _worker; _worker()'], env=environment,
            input=json.dumps({'cluster': cluster, 'tools': archive_tools}), text=True, capture_output=True, timeout=180)
        if result.returncode:
            raise RuntimeError('Synthetic native workflow contract failed: ' + result.stderr[-6000:])
        value = json.loads(result.stdout)
    return {'profile': PROFILE, **value, 'synthetic': True, 'external_provider_calls': 0, 'delivery_calls': 0,
            'production_actions': 0, 'operating_backup_ready': False, 'temporary_cluster_removed': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    if not args.run: parser.error('--run is required')
    print(json.dumps(rehearse(), sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
