"""Explicit, disposable DB-API PostgreSQL adapter rehearsal.

This does not initialize the application Store, accept a database address,
perform migration or measure production capacity. PostgreSQL listens only on a
new private Unix socket and is stopped before its temporary files are removed.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import argparse
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

PROFILE = 'storage-adapter-postgres-rehearsal-v1'
TEMP_PREFIX = 'a2a-adapter-pg-'
PORT = 55447
CONTENDERS = 4
TOOL_PATH = '/usr/lib/postgresql/18/bin:/opt/homebrew/opt/postgresql@18/bin:/usr/lib/postgresql/16/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'
CHECKS = frozenset(('unix_socket_only', 'generated_id_returning', 'scalar_round_trip', 'bound_text_not_sql',
                    'transaction_rollback', 'caught_statement_error_rolls_back', 'readonly_hint_blocks_writer',
                    'native_readonly_blocks_dishonest_hint', 'nested_transaction_refused', 'closed_session_refused',
                    'cross_thread_refused', 'multi_statement_refused', 'result_limit_refused',
                    'invalid_parameters_refused', 'claim_single_winner', 'stale_fence_refused',
                    'caller_owned_connection_open'))


class RehearsalError(ValueError):
    def __init__(self, code='rehearsal_failed'):
        self.code = code if code in ('dependency_unavailable', 'tools_unavailable', 'rehearsal_failed', 'invariant_failed') else 'rehearsal_failed'
        super().__init__(self.code)


def _driver():
    try:
        driver = importlib.import_module('psycopg')
        if not callable(getattr(driver, 'connect', None)):
            raise ImportError
        return driver
    except (ImportError, OSError):
        raise RehearsalError('dependency_unavailable') from None


def _tools():
    # Use one complete installation, preferring versioned PG18 over old aliases.
    for directory in TOOL_PATH.split(':'):
        found = {name: shutil.which(name, path=directory) for name in ('initdb', 'pg_ctl')}
        if all(found.values()):
            return found
    raise RehearsalError('tools_unavailable')


def _environment(root):
    home = root / 'home'
    home.mkdir(mode=0o700)
    # No inherited PG*, libpq services, password files, HOME or shell config.
    return {'PATH': TOOL_PATH, 'HOME': str(home), 'TMPDIR': str(root), 'LC_ALL': 'C', 'LANG': 'C',
            'PGPASSFILE': str(root / 'no-password-file'), 'PGSERVICEFILE': str(root / 'no-service-file'),
            'PGSYSCONFDIR': str(root)}


def _run(args, env, *, timeout=30, input=None):
    try:
        result = subprocess.run(args, env=env, input=input, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RehearsalError() from None
    if result.returncode != 0:
        raise RehearsalError()
    return result


ORPHAN_MIN_HOURS = 6        # a private cluster whose test process died is left running (11-12: two since 11-11 11:25)
OLD_FOLDER_DAYS = 7
_ORPHAN_ARGS = re.compile(r'-D\s+(/private/tmp/' + re.escape(TEMP_PREFIX) + r'[A-Za-z0-9_]+)/data(?:\s|$)')


def _etime_seconds(text):
    days, _, clock = text.strip().rpartition('-')
    parts = [int(p) for p in clock.split(':')]
    while len(parts) < 3:
        parts.insert(0, 0)
    return (int(days) if days else 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def stop_orphan_clusters(min_hours=ORPHAN_MIN_HOURS, ps=None, connections=None, stop=None, folders=None, now=None):
    """Stop private test clusters left behind by a dead test process; never delete their folders (PM 11-12).

    A cluster is an orphan when its postmaster's parent is launchd (ppid 1), it is older than MIN_HOURS, no other
    process names its folder and no client is connected. Returns {'stopped': [...], 'kept': [...], 'old_folders': [...]} where old_folders lists
    /private/tmp/a2a-adapter-pg-* folders untouched for OLD_FOLDER_DAYS (deleting them is the user's decision)."""
    pg_bin = Path('/opt/homebrew/opt/postgresql@18/bin')
    rows = (ps or (lambda: subprocess.run(['ps', '-Ao', 'pid=,ppid=,etime=,args='], capture_output=True, text=True).stdout))()

    def clients(root):
        out = subprocess.run([str(pg_bin / 'psql'), '-h', str(Path(root) / 'socket'), '-p', str(PORT), '-U', 'postgres',
                              '-d', 'postgres', '-At', '-c', "SELECT count(*) FROM pg_stat_activity WHERE "
                              "backend_type='client backend' AND pid<>pg_backend_pid()"], capture_output=True, text=True,
                             timeout=10)
        return int(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip().isdigit() else None

    def halt(root):
        return subprocess.run([str(pg_bin / 'pg_ctl'), '-D', str(Path(root) / 'data'), '-m', 'fast', '-w', '-t', '20',
                               'stop'], capture_output=True, text=True, timeout=30).returncode == 0
    stopped, kept = [], []
    lines = [line.split(None, 3) for line in rows.splitlines()]
    # pg_ctl daemonises, so every postmaster has ppid 1: a cluster is also kept while any other process (a migrate,
    # a script holding its DSN file) names its folder.
    users = [parts[3] for parts in lines if len(parts) == 4 and not _ORPHAN_ARGS.search(parts[3])]
    for line in rows.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        found = _ORPHAN_ARGS.search(parts[3])
        if not found or parts[1] != '1':
            continue
        root = found.group(1)
        if _etime_seconds(parts[2]) < min_hours * 3600:
            continue
        if any(root in args for args in users):
            kept.append({'root': root, 'in_use': True})
            continue
        busy = (connections or clients)(root)
        if busy != 0:
            kept.append({'root': root, 'clients': busy})
            continue
        (stopped if (stop or halt)(root) else kept).append({'root': root})
    now = time.time() if now is None else now
    old = sorted(str(path) for path in (folders if folders is not None else Path('/private/tmp').glob(TEMP_PREFIX + '*'))
                 if Path(path).is_dir() and now - Path(path).stat().st_mtime > OLD_FOLDER_DAYS * 86400)
    return {'stopped': stopped, 'kept': kept, 'old_folders': old}


@contextmanager
def _private_cluster(tools):
    """An internal explicit-connection fixture; never use a caller DSN."""
    # Automatic TemporaryDirectory cleanup would remove files even after both
    # stop commands fail. Keep ownership explicit until shutdown is confirmed.
    try:   # orphans of earlier runs hold memory and the shared port; stop them first (never fails the fixture)
        stop_orphan_clusters()
    except Exception:  # noqa: BLE001
        pass
    root = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir='/private/tmp'))
    data = root / 'data'
    env = None
    try:
        os.chmod(root, 0o700)
        socket = root / 'socket'
        socket.mkdir(mode=0o700)
        env = _environment(root)
        _run([tools['initdb'], '-D', str(data), '--username=postgres', '--auth-local=trust',
              '--auth-host=reject', '--no-locale', '--encoding=UTF8'], env)
        _run([tools['pg_ctl'], '-D', str(data), '-l', str(root / 'server.log'), '-o',
              "-k " + str(socket) + " -p " + str(PORT) + " -c listen_addresses='' -c unix_socket_permissions=0700",
              '-w', 'start'], env)

        yield {'socket': str(socket), 'root': str(root), 'environment': env}
    finally:
        # A start timeout can leave a postmaster behind. A remaining private pid
        # prevents deletion even when shutdown returns an error or times out.
        if (data / 'postmaster.pid').exists():
            for mode in ('fast', 'immediate'):
                try:
                    _run([tools['pg_ctl'], '-D', str(data), '-m', mode, '-w', 'stop'], env, timeout=10)
                except RehearsalError:
                    pass
                if not (data / 'postmaster.pid').exists():
                    break
        if (data / 'postmaster.pid').exists():
            raise RehearsalError()
        shutil.rmtree(root)
        if root.exists():
            raise RehearsalError('invariant_failed')


def _contracts(connect):
    # Kept separate so tests can prove cluster cleanup after contract failures.
    from agent_market.storage_adapter import PostgresAdapter, Statement, StorageError
    connection = connect()
    adapter = PostgresAdapter(connection)
    checks = {}

    def statement(name, sql, *, readonly=False):
        # This is trusted fixture SQL, with no rewriting or interpolated values.
        return Statement(name, sql, sql, readonly=readonly)

    count = statement('fixture.count', 'SELECT COUNT(*) AS n FROM adapter_items', readonly=True)
    read = statement('fixture.read', 'SELECT id,label,nullable,integer_value,float_value,blob_value,decimal_text,utc_text FROM adapter_items ORDER BY id', readonly=True)
    insert = statement('fixture.insert', 'INSERT INTO adapter_items(label,nullable,integer_value,float_value,blob_value,decimal_text,utc_text) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id')

    def scalar(stmt, parameters=()):
        with adapter.transaction(readonly=True) as session:
            return session.execute(stmt, parameters).rows[0][0]

    def rejected(action, codes):
        try:
            action()
        except StorageError as exc:
            return exc.code in codes
        return False

    def execute(stmt, parameters=(), *, readonly=False):
        with adapter.transaction(readonly=readonly) as session:
            return session.execute(stmt, parameters)

    try:
        with adapter.transaction(readonly=True) as session:
            transport = session.execute(statement('fixture.transport',
                "SELECT current_setting('listen_addresses') AS listeners, inet_server_addr() AS server_address, inet_client_addr() AS client_address", readonly=True)).rows[0]
        checks['unix_socket_only'] = transport['listeners'] == '' and transport['server_address'] is None and transport['client_address'] is None
        execute(statement('fixture.create', '''CREATE TABLE adapter_items (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,label TEXT NOT NULL UNIQUE,
            nullable TEXT,integer_value BIGINT,float_value DOUBLE PRECISION,blob_value BYTEA,
            decimal_text TEXT,utc_text TEXT)'''))
        text = "Synthetic O'Reilly; SELECT pg_sleep(60); -- \u00e9 \u2603"
        values = (text, None, 2**62 + 7, 1.25, b'\x00synthetic\xff', '123456789.000100', '2026-10-18T00:00:00.123456Z')
        generated = execute(insert, values)
        checks['generated_id_returning'] = generated.rowcount == 1 and len(generated.rows) == 1 and type(generated.rows[0]['id']) is int
        with adapter.transaction(readonly=True) as session:
            stored = session.execute(read).rows[0]
        checks['scalar_round_trip'] = tuple(stored)[1:] == values and dict(stored)['decimal_text'] == values[5] and stored[1:3] == values[:2]
        checks['bound_text_not_sql'] = scalar(count) == 1 and stored['label'] == text

        try:
            with adapter.transaction() as session:
                session.execute(insert, ('rollback',) + values[1:])
                raise RuntimeError('Synthetic rollback marker')
        except RuntimeError:
            pass
        checks['transaction_rollback'] = scalar(count) == 1

        try:
            with adapter.transaction() as session:
                session.execute(insert, ('before-conflict',) + values[1:])
                try:
                    session.execute(insert, values)
                except StorageError:
                    pass
        except StorageError as exc:
            conflict_refused = exc.code == 'transaction_failed'
        else:
            conflict_refused = False
        checks['caught_statement_error_rolls_back'] = conflict_refused and scalar(count) == 1
        checks['readonly_hint_blocks_writer'] = rejected(lambda: execute(insert, ('readonly-hint',) + values[1:], readonly=True), {'read_only'}) and scalar(count) == 1
        dishonest = statement('fixture.dishonest', 'INSERT INTO adapter_items(label) VALUES (%s)', readonly=True)
        checks['native_readonly_blocks_dishonest_hint'] = rejected(lambda: execute(dishonest, ('readonly-native',), readonly=True), {'statement_failed', 'read_only'}) and scalar(count) == 1

        def nested():
            with adapter.transaction():
                with adapter.transaction():
                    pass
        checks['nested_transaction_refused'] = rejected(nested, {'nested_transaction'})
        with adapter.transaction(readonly=True) as session:
            session.execute(count)
        checks['closed_session_refused'] = rejected(lambda: session.execute(count), {'session_closed'})
        with adapter.transaction(readonly=True) as session:
            with ThreadPoolExecutor(max_workers=1) as pool:
                checks['cross_thread_refused'] = pool.submit(lambda: rejected(lambda: session.execute(count), {'thread_violation'})).result(timeout=5)
        multiple = statement('fixture.multiple', 'SELECT 1; SELECT 2', readonly=True)
        checks['multi_statement_refused'] = rejected(lambda: execute(multiple, readonly=True), {'statement_failed'})
        oversized = statement('fixture.too_many', 'SELECT generate_series(1,1001) AS n', readonly=True)
        checks['result_limit_refused'] = rejected(lambda: execute(oversized, readonly=True), {'result_limit'})
        checks['invalid_parameters_refused'] = all(rejected(lambda value=value: execute(insert, value), {'invalid_parameters'}) for value in
            ([text], (True,), (float('nan'),), ('bad\x00text',), (2**63,)))

        execute(statement('fixture.create_claim', 'CREATE TABLE adapter_claim (id BIGINT PRIMARY KEY,state TEXT NOT NULL,fence BIGINT NOT NULL)'))
        execute(statement('fixture.seed_claim', 'INSERT INTO adapter_claim VALUES (%s,%s,%s)'), (1, 'queued', 0))
        barrier = threading.Barrier(CONTENDERS)
        claim = statement('fixture.claim', "UPDATE adapter_claim SET state='running',fence=fence+1 WHERE id=%s AND state='queued' RETURNING fence")
        def contender(_):
            owned = connect()
            current = PostgresAdapter(owned)
            try:
                barrier.wait(timeout=3)
                with current.transaction() as session:
                    result = session.execute(claim, (1,))
                return len(result.rows)
            finally:
                owned.close()
        with ThreadPoolExecutor(max_workers=CONTENDERS) as pool:
            winners = list(pool.map(contender, range(CONTENDERS)))
        checks['claim_single_winner'] = sum(winners) == 1 and all(value in (0, 1) for value in winners)
        stale = execute(statement('fixture.stale', "UPDATE adapter_claim SET state='succeeded' WHERE id=%s AND fence=%s RETURNING id"), (1, 0))
        checks['stale_fence_refused'] = stale.rowcount == 0 and not stale.rows
        checks['caller_owned_connection_open'] = connection.closed is False and scalar(count) == 1
        return checks, connection.info.server_version
    finally:
        connection.close()


def _worker_main():
    """Private fixed-code child entry; not a database-selecting CLI."""
    try:
        descriptor = json.loads(sys.stdin.read(1025))
        if not isinstance(descriptor, dict) or set(descriptor) != {'socket'}:
            raise RehearsalError('invariant_failed')
        socket = Path(descriptor['socket'])
        if not socket.is_absolute() or socket.name != 'socket' or not socket.parent.name.startswith(TEMP_PREFIX) or socket.parent.parent != Path('/private/tmp'):
            raise RehearsalError('invariant_failed')
        driver = _driver()
        def connect():
            return driver.connect(host=str(socket), port=PORT, user='postgres', dbname='postgres',
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
    root = Path(__file__).resolve().parents[1]
    driver_root = Path(driver.__file__).resolve().parent.parent
    env = dict(descriptor['environment'])
    env['PYTHONPATH'] = os.pathsep.join((str(root), str(driver_root)))
    result = _run([sys.executable, '-B', '-c',
                   'from scripts.rehearse_storage_adapter_postgres import _worker_main; raise SystemExit(_worker_main())'],
                  env, input=json.dumps({'socket': descriptor['socket']}), timeout=30)
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
    """Run only the fixed synthetic contract, returning no private addresses."""
    driver = _driver()
    tools = _tools()
    started = time.monotonic()
    try:
        with _private_cluster(tools) as descriptor:
            contract = _contract_child(descriptor, driver)
        checks = contract['checks']
        if not isinstance(checks, dict) or set(checks) != CHECKS or not all(value is True for value in checks.values()):
            raise RehearsalError('invariant_failed')
        return {'ok': True, 'profile': PROFILE, 'checks': checks,
                'elapsed_ms': round((time.monotonic() - started) * 1000, 3),
                'transport': 'private_unix_socket_only', 'cluster_stopped_and_removed': True,
                'versions': contract['versions'],
                'limits': {'claim_contenders': CONTENDERS, 'production_db_writes': 0, 'provider_calls': 0,
                           'application_store_integrated': False, 'production_cutover': False}}
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
    parser = Parser(prog='rehearse_storage_adapter_postgres', description=__doc__, allow_abbrev=False)
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
    raise SystemExit(main())
