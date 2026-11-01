"""Anonymous visit lifecycle and startup DTOs on owned Unix-only PostgreSQL.

No DSN or operating path is accepted. The existing isolated child harness also
denies Python TCP socket creation, including hidden cache or provider probes.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster

PROFILE = 'front-performance-delta-owned-postgres-v1'


def _contracts(connect):
    from fastapi.testclient import TestClient
    from agent_market.concierge import memory
    from agent_market.concierge.front import Front, create_front_app, clear_front_caches
    from agent_market.gateway import admin_auth, store as store_module
    from agent_market.storage_adapter import open_store

    pg = connect()
    native = open_store('postgresql', connection=pg, initialize=True, workflow_key=b'p' * 32)
    initializer = store_module.init_admin_auth_db
    store_module.init_admin_auth_db = lambda db: db.executescript(admin_auth.ADMIN_SCHEMA)
    try:
        reference = store_module.Store()
    finally:
        store_module.init_admin_auth_db = initializer
    books, checks, results = [], {}, []
    original_cap = memory.MAX_HITS

    def rows(store):
        sql = 'SELECT fingerprint,user_agent,first_seen,last_seen,hits,last_path FROM agent_hits ORDER BY fingerprint'
        if store is native:
            with native.tx(readonly=True):
                return [dict(row) for row in native._execute(sql).fetchall()]
        return [dict(row) for row in store.query(sql)]

    try:
        with pg.cursor() as cursor:
            cursor.execute("SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr()")
            checks['owned_private_unix_socket_only'] = cursor.fetchone() == ('', None, None)

        owners = []
        transaction = native.tx

        @contextmanager
        def observed_transaction(**kwargs):
            with transaction(**kwargs) as db:
                if threading.current_thread().name == 'visitor-hit-worker':
                    owners.append((threading.get_ident(), native._owner))
                yield db

        native.tx = observed_transaction
        for store in (native, reference):
            book = memory.VisitorBook(store)
            books.append(book)
            token = 'vt_' + 's' * 32
            start = time.time()
            # Requests never lend their own tx/cursor to the queue worker.
            try:
                with store.tx():
                    assert book.record_hit(memory.fingerprint('synthetic-0', 'client'), token, '/first?secret=discard')
                    assert not book.flush_hits(0.02)
                    raise ValueError('Synthetic caller rollback')
            except ValueError:
                pass
            assert book.flush_hits()
            with ThreadPoolExecutor(max_workers=8) as producers:
                accepted = list(producers.map(lambda index: book.record_hit(
                    memory.fingerprint('synthetic-' + str(index % 4), 'client'), token, '/next#discard'), range(200)))
            assert all(accepted) and book.close()
            current = rows(store)
            assert sum(row['hits'] for row in current) == 201
            assert all(start <= row['first_seen'] <= row['last_seen'] <= time.time() for row in current)
            assert all(row['last_path'] == '/next' and token not in row['user_agent'] for row in current)
            assert book.hit_diagnostics()['unconfirmed'] == book.hit_diagnostics()['pending'] == 0
            results.append([(row['fingerprint'], row['hits'], row['last_path'], row['user_agent']) for row in current])
        checks['actual_sqlite_postgres_async_aggregate_and_sanitization_parity'] = results[0] == results[1]
        checks['native_worker_owns_each_transaction_after_request_rollback'] = bool(owners) and all(a == b for a, b in owners)
        checks['concurrent_admission_settles_without_unconfirmed_or_duplicate_records'] = True

        memory.MAX_HITS = 3
        # Existing finite SQL is used by the worker; fixture setup is explicit.
        for store in (native, reference):
            expired_at = time.time() - memory.HIT_RETENTION - 100
            values = (memory.fingerprint('expired', 'client'), 'Synthetic', expired_at, expired_at, '/expired')
            with store.tx() as db:
                sql = 'INSERT INTO agent_hits VALUES (?,?,?,?,1,?)'
                if store is native:
                    native._execute(sql.replace('?', '%s'), values)
                else:
                    db.execute(sql, values)
            book = memory.VisitorBook(store)
            books.append(book)
            assert book.record_hit(memory.fingerprint('newest', 'client'), 'Synthetic', '/newest')
            assert book.close()
            current = rows(store)
            assert len(current) == 3
            assert any(row['last_path'] == '/newest' for row in current)
            assert all(row['last_path'] != '/expired' for row in current)
        checks['native_and_sqlite_deterministic_retention_and_hard_row_cap'] = True

        # Exercise the actual sequential startup prewarm in a foreign thread.
        for store in (native, reference):
            front = Front(store)
            books.append(front.book)
            clear_front_caches()

            def prewarm():
                data = front.bootstrap_snapshot()
                encoded = front.bootstrap_snapshot_json()
                counts = front.live_counts()
                assert json.loads(encoded) == data and '<' not in encoded
                assert set(('overview', 'explore', 'insights')) <= set(data)
                assert isinstance(counts, dict)

            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(prewarm).result(timeout=20)
            with TestClient(create_front_app(front)) as client:
                response = client.get('/', headers={'accept': 'text/html'})
                assert response.status_code == 200
                assert "script-src 'nonce-" in response.headers['content-security-policy']
                assert 'visitor-hit-worker' not in response.text
            assert front.book.hit_diagnostics()['closed']
            assert front.book.hit_diagnostics()['pending'] == front.book.hit_diagnostics()['unconfirmed'] == 0
        checks['actual_threaded_startup_prewarm_and_html_bootstrap_native_and_sqlite'] = True
        checks['standalone_front_lifespan_drains_without_closing_caller_store'] = pg.closed is False
        if not all(checks.values()):
            raise AssertionError('Performance fixture invariant failed')
        return {'checks': checks, 'full_application_ready': False, 'backend_path_faked': False}
    finally:
        memory.MAX_HITS = original_cap
        for book in books:
            assert book.close()
        native.close()
        pg.close()
        reference._db.close()


def _worker():
    from scripts import rehearse_application_store_postgres as base
    base._contracts = _contracts
    base._worker()


def rehearse():
    driver = _driver()
    paths = [Path(__file__), Path('agent_market/concierge/memory.py'),
             Path('agent_market/concierge/front.py'), Path('agent_market/gateway/server.py'),
             Path('agent_market/application_store_sql.json')]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    with _private_cluster(_tools()) as cluster:
        environment = dict(cluster['environment'])
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(driver.__file__).resolve().parent.parent)
        child = subprocess.run([sys.executable, '-B', '-c',
            'from scripts.rehearse_front_performance_postgres import _worker; _worker()'],
            env=environment, input=json.dumps({'socket': cluster['socket'], 'root': cluster['root']}),
            text=True, capture_output=True, timeout=120)
        if child.returncode:
            raise RuntimeError('Synthetic performance contracts failed: ' + child.stderr[-4000:])
        result = json.loads(child.stdout)
    if before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}:
        raise AssertionError('Source changed during performance rehearsal')
    return {'profile': PROFILE, **result, 'source_hashes': before,
            'source_unchanged': True, 'temporary_cluster_removed': True,
            'operating_database_writes': 0, 'external_provider_calls': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--run', action='store_true', required=True)
    parser.parse_args(argv)
    print(json.dumps(rehearse(), sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
