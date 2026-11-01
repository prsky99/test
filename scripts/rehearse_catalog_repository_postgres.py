"""Explicit, disposable SQLite/PostgreSQL catalog repository comparison.

No operating database, connection string, migration source, provider or server
is accepted. The established private-cluster harness owns PostgreSQL cleanup.
Only the new bounded repository contract is compared, not application Store/FTS.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

PROFILE = 'catalog-repository-postgres-rehearsal-v1'
CHECKS = frozenset(('unix_socket_only', 'sqlite_postgres_records_equal', 'identity_lookup_equal',
                    'bounded_batch_order_equal', 'filter_counts_equal', 'pagination_order_equal',
                    'null_and_raw_text_equal', 'bound_filter_values_not_sql', 'private_original_bindings_preserved',
                    'existing_public_projection_equal', 'stale_hash_rejected', 'postgres_read_committed_refused',
                    'postgres_repeatable_snapshot', 'fixture_cas_no_repeated_update', 'fixture_write_rollback',
                    'invalid_stored_record_refused', 'caller_owned_connections_open'))


class RehearsalError(ValueError):
    def __init__(self, code='rehearsal_failed'):
        self.code = code if code in ('dependency_unavailable', 'tools_unavailable', 'rehearsal_failed', 'invariant_failed') else 'rehearsal_failed'
        super().__init__(self.code)


def _harness():
    from scripts import rehearse_storage_adapter_postgres
    return rehearse_storage_adapter_postgres


def _contracts(connect):
    """Compare a fixed synthetic contract; never import the operating Store."""
    import sqlite3
    from agent_market.catalog_repository import CatalogRepository, CatalogFilter, CatalogError
    from agent_market.catalog_repository_fixtures import catalog_rows, seed
    from agent_market.concierge.connections import public_agent, gateway_agent_url
    from agent_market.storage_adapter import SQLiteAdapter, PostgresAdapter, Statement

    sqlite = sqlite3.connect(':memory:')
    postgres = connect()
    writer = probe = None
    try:
        # Connection policy is explicit caller setup, not SQL rewritten by the
        # repository. Its snapshot contract rejects default READ COMMITTED.
        postgres.execute('SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        adapters = (SQLiteAdapter(sqlite), PostgresAdapter(postgres))
        for adapter in adapters:
            seed(adapter)
        repositories = tuple(CatalogRepository(adapter) for adapter in adapters)
        expected = catalog_rows()
        records = tuple(tuple(row.as_private_dict() for row in repo.list()) for repo in repositories)
        checks = {}
        with adapters[1].transaction(readonly=True) as session:
            transport = session.execute(Statement('fixture.catalog_transport',
                "SELECT '' AS listeners,NULL AS server_address,NULL AS client_address",
                "SELECT current_setting('listen_addresses') AS listeners,inet_server_addr() AS server_address,inet_client_addr() AS client_address", readonly=True)).rows[0]
        checks['unix_socket_only'] = transport['listeners'] == '' and transport['server_address'] is None and transport['client_address'] is None
        checks['sqlite_postgres_records_equal'] = records[0] == records[1] == expected
        checks['identity_lookup_equal'] = all(repo.get(1).as_private_dict() == expected[0]
            and repo.get_by_key(expected[2]['key']).as_private_dict() == expected[2]
            and repo.get(999) is None and repo.get_by_key('missing-synthetic-key') is None for repo in repositories)
        batches = tuple(repo.batch((4, 2, 999, 2, 1)) for repo in repositories)
        checks['bounded_batch_order_equal'] = all(tuple(row.id for row in batch.found) == (4, 2, 1)
            and batch.missing == (999,) for batch in batches)
        filter_cases = ((CatalogFilter(), (1, 2, 3, 4, 5, 6)),
                   (CatalogFilter(kind='mcp', active=True, min_last_seen=300.0), (1, 4, 6)),
                   (CatalogFilter(active=False), (3, 5)),
                   (CatalogFilter(health_status='down'), (3,)),
                   (CatalogFilter(category='docs'), (2, 4)),
                   (CatalogFilter(category='news%'), ()))
        checks['filter_counts_equal'] = all(tuple(row.id for row in repo.list(filter_spec)) == ids and repo.count(filter_spec) == len(ids)
            for repo in repositories for filter_spec, ids in filter_cases)
        checks['pagination_order_equal'] = all(tuple(row.id for row in repo.list(limit=2, after_id=2)) == (3, 4)
            and not repo.list(limit=2, after_id=6) and repo.count() == 6 for repo in repositories)
        checks['null_and_raw_text_equal'] = all(repo.get(2).as_private_dict()['auth_info'] is None
            and repo.get(4).content_hash is None and repo.get(5).as_private_dict()['details'] == expected[4]['details']
            and repo.get(1).as_private_dict()['name'] == expected[0]['name'] for repo in repositories)
        checks['bound_filter_values_not_sql'] = all(repo.count(CatalogFilter(source=expected[2]['source'])) == 1
            and tuple(row.id for row in repo.list(CatalogFilter(category=expected[2]['category']))) == (3,)
            and repo.count() == 6 for repo in repositories)
        checks['private_original_bindings_preserved'] = all(repo.get(1).as_private_dict()['url'] == expected[0]['url']
            and repo.get(6).as_private_dict()['auth_info'] == expected[5]['auth_info']
            and repr(repo.get(1)) == '<CatalogResource private>' and repr(repo.batch((1,))) == '<CatalogBatch private>'
            for repo in repositories)

        projections = []
        for repo in repositories:
            raw = repo.get(1).as_private_dict()
            # Explicit existing public DTO selection, never serialize the
            # private repository record as if it were a public response.
            dto = {name: raw[name] for name in ('id', 'kind', 'url', 'name', 'description')}
            dto['sources'] = ['https://sources.example/catalog']
            projections.append(public_agent(dto, raw, store=None))
        projected = json.dumps(projections, sort_keys=True)
        checks['existing_public_projection_equal'] = (projections[0] == projections[1]
            and projections[0]['url'] == gateway_agent_url(1, 'mcp')
            and projections[0]['sources'] == ['https://sources.example/catalog']
            and expected[0]['url'] not in projected and 'synthetic-private-token' not in projected
            and 'content_hash' not in projections[0] and 'auth_info' not in projections[0])

        def denied(function, code):
            try:
                function()
            except CatalogError as exc:
                return exc.code == code
            return False
        stale = hashlib.sha256(b'synthetic-never-current-content').hexdigest()
        checks['stale_hash_rejected'] = all(repo.get(1, expected_hash=expected[0]['content_hash']).id == 1
            and denied(lambda repo=repo: repo.get(1, expected_hash=stale), 'stale_resource')
            and denied(lambda repo=repo: repo.get(999, expected_hash=stale), 'stale_resource') for repo in repositories)

        probe = connect()
        checks['postgres_read_committed_refused'] = denied(lambda: CatalogRepository(PostgresAdapter(probe)).count(), 'isolation_required')
        writer = connect()
        writer_adapter = PostgresAdapter(writer)
        update = Statement('fixture.catalog_cas', 'UPDATE resources SET name=?,content_hash=? WHERE id=? AND content_hash=? RETURNING id',
                           'UPDATE resources SET name=%s,content_hash=%s WHERE id=%s AND content_hash=%s RETURNING id')
        fresh_hash = hashlib.sha256(b'synthetic-catalog-content-version-two').hexdigest()
        with repositories[1].snapshot() as view:
            before = view.get(1).as_private_dict()
            with writer_adapter.transaction() as session:
                applied = session.execute(update, ('Changed synthetic catalog', fresh_hash, 1, expected[0]['content_hash']))
            during = view.get(1).as_private_dict()
            checks['postgres_repeatable_snapshot'] = before == during == expected[0] and view.count() == 6
        fresh = repositories[1].get(1).as_private_dict()
        checks['postgres_repeatable_snapshot'] = checks['postgres_repeatable_snapshot'] and fresh['name'] == 'Changed synthetic catalog' and fresh['content_hash'] == fresh_hash
        with writer_adapter.transaction() as session:
            repeated = session.execute(update, ('Must not replace again', stale, 1, expected[0]['content_hash']))
        checks['fixture_cas_no_repeated_update'] = (applied.rowcount == 1 and len(applied.rows) == 1
            and repeated.rowcount == 0 and not repeated.rows
            and denied(lambda: repositories[1].get(1, expected_hash=expected[0]['content_hash']), 'stale_resource'))

        rollback = Statement('fixture.catalog_rollback', 'UPDATE resources SET name=? WHERE id=?', 'UPDATE resources SET name=%s WHERE id=%s')
        try:
            with writer_adapter.transaction() as session:
                session.execute(rollback, ('Must roll back', 1))
                raise RuntimeError('Synthetic rollback')
        except RuntimeError:
            pass
        checks['fixture_write_rollback'] = repositories[1].get(1).as_private_dict() == fresh
        invalid = Statement('fixture.catalog_invalid', 'UPDATE resources SET active=? WHERE id=?', 'UPDATE resources SET active=%s WHERE id=%s')
        refused = []
        for adapter, repo in zip(adapters, repositories):
            with adapter.transaction() as session:
                session.execute(invalid, (2, 5))
            refused.append(denied(lambda repo=repo: repo.get(5), 'invalid_record'))
            with adapter.transaction() as session:
                session.execute(invalid, (0, 5))
        checks['invalid_stored_record_refused'] = all(refused)
        checks['caller_owned_connections_open'] = sqlite.execute('SELECT 1').fetchone() == (1,) and postgres.closed is False
        return checks, postgres.info.server_version
    finally:
        for connection in (probe, writer, postgres, sqlite):
            if connection is not None:
                connection.close()


def _worker_main():
    """Fixed-code clean-env child, with no public database-selecting CLI."""
    try:
        raw = sys.stdin.read(1025)
        if len(raw) > 1024:
            raise ValueError
        descriptor = json.loads(raw)
        if not isinstance(descriptor, dict) or set(descriptor) != {'socket'} or type(descriptor['socket']) is not str:
            raise ValueError
        pg = _harness()
        socket = Path(descriptor['socket'])
        if not socket.is_absolute() or socket.name != 'socket' or not socket.parent.name.startswith(pg.TEMP_PREFIX) or socket.parent.parent != Path('/private/tmp'):
            raise ValueError
        driver = pg._driver()
        def connect():
            return driver.connect(host=str(socket), port=pg.PORT, user='postgres', dbname='postgres',
                                  password='synthetic-unused-local-trust', connect_timeout=5,
                                  passfile=str(socket.parent / 'no-password-file'),
                                  options='-c statement_timeout=3000 -c lock_timeout=2000', autocommit=True)
        checks, server_version = _contracts(connect)
        print(json.dumps({'checks': checks, 'versions': {'postgresql_version_number': server_version,
                                                       'psycopg': driver.__version__}}, sort_keys=True, allow_nan=False))
        return 0
    except Exception:
        print(json.dumps({'error': 'rehearsal_failed'}))
        return 1


def _contract_child(descriptor, driver):
    pg = _harness()
    root = Path(__file__).resolve().parents[1]
    driver_root = Path(driver.__file__).resolve().parent.parent
    environment = dict(descriptor['environment'])
    environment['PYTHONPATH'] = os.pathsep.join((str(root), str(driver_root)))
    result = pg._run([sys.executable, '-B', '-c',
                      'from scripts.rehearse_catalog_repository_postgres import _worker_main; raise SystemExit(_worker_main())'],
                     environment, input=json.dumps({'socket': descriptor['socket']}), timeout=30)
    if result.stderr or len(result.stdout) > 8192:
        raise RehearsalError('invariant_failed')
    try:
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or set(value) != {'checks', 'versions'}:
            raise ValueError
        versions = value['versions']
        if (not isinstance(versions, dict) or set(versions) != {'postgresql_version_number', 'psycopg'}
                or type(versions['postgresql_version_number']) is not int or not 100000 <= versions['postgresql_version_number'] <= 999999
                or type(versions['psycopg']) is not str or not re.fullmatch(r'[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,3}', versions['psycopg'])):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise RehearsalError('invariant_failed') from None


def rehearse():
    """Run the fixed private pilot; no application backend is selected."""
    pg = _harness()
    started = time.monotonic()
    try:
        driver = pg._driver()
        tools = pg._tools()
        with pg._private_cluster(tools) as descriptor:
            contract = _contract_child(descriptor, driver)
        checks = contract['checks']
        if not CHECKS or not isinstance(checks, dict) or set(checks) != CHECKS or not all(value is True for value in checks.values()):
            raise RehearsalError('invariant_failed')
        return {'ok': True, 'profile': PROFILE, 'checks': checks, 'versions': contract['versions'],
                'elapsed_ms': round((time.monotonic() - started) * 1000, 3),
                'transport': 'private_unix_socket_only', 'cluster_stopped_and_removed': True,
                'limits': {'application_store_integrated': False, 'production_cutover': False,
                           'production_db_writes': 0, 'provider_calls': 0, 'fts_search_parity_established': False,
                           'synthetic_fixture_rows': 6, 'repository_read_only': True,
                           'cas_and_rollback_scope': 'trusted_fixture_statements_only'}}
    except pg.RehearsalError as exc:
        raise RehearsalError(exc.code) from None
    except RehearsalError:
        raise
    except Exception:
        raise RehearsalError() from None


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError


class Once(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, False):
            raise UsageError
        setattr(namespace, self.dest, True)


def main(argv=None):
    parser = Parser(prog='rehearse_catalog_repository_postgres', description=__doc__, allow_abbrev=False)
    parser.add_argument('--run', action=Once, nargs=0, default=False)
    status = 0
    try:
        args = parser.parse_args(argv)
        if args.run is not True:
            raise UsageError
        result = rehearse()
    except UsageError:
        result = {'ok': False, 'profile': PROFILE, 'error': 'invalid_arguments'}
        status = 2
    except RehearsalError as exc:
        result = {'ok': False, 'profile': PROFILE, 'error': exc.code}
        status = 1
    except Exception:
        result = {'ok': False, 'profile': PROFILE, 'error': 'rehearsal_failed'}
        status = 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return status


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
