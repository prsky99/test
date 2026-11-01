"""Runtime sessions survive a database restart; owners and operator tools never reconnect silently."""
import asyncio
from contextlib import asynccontextmanager
import os
from types import SimpleNamespace

import pytest

KEY = b'a' * 32


@pytest.fixture(scope='module')
def cluster():
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, _tools
    with _private_cluster(_tools()) as value:
        yield value


def _connect(cluster):
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import PORT
    return psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)


@pytest.fixture(scope='module')
def installed(cluster):
    from agent_market.storage_adapter import open_store
    from agent_market.service_runtime import ServiceControl
    connection = _connect(cluster)
    store = open_store('postgresql', connection=connection, initialize=True, workflow_key=KEY)
    ServiceControl(_connect(cluster), KEY).install()
    store.close(); connection.close()
    return cluster


def _terminate(cluster, connection):
    """What a database restart does to an idle session."""
    pid = connection.info.backend_pid
    with _connect(cluster) as admin:
        assert admin.execute('SELECT pg_terminate_backend(%s)', (pid,)).fetchone()[0]
    return pid


def _store(cluster, factory=True):
    from agent_market.storage_adapter import open_store
    store = open_store('postgresql', connection=_connect(cluster), workflow_key=KEY,
                       required_capabilities=('full_application',))
    if factory:
        store._connection_factory = lambda: _connect(cluster)
    return store


def _backend(store):
    with store.tx(readonly=True):
        return store._execute('SELECT pg_backend_pid()').fetchone()[0]


def test_idle_runtime_session_reconnects_at_the_next_transaction(installed):
    store = _store(installed)
    before = _terminate(installed, store._connection)
    assert _backend(store) != before  # no failed request: BEGIN found the dead session first
    with store.tx():
        store._execute("INSERT INTO application_store_state(id,profile) VALUES(1,'x') ON CONFLICT(id) DO NOTHING")
    assert store._broken is False


def test_work_in_flight_fails_once_and_is_never_replayed(installed):
    from agent_market.application_store_postgres import ApplicationStoreError
    store = _store(installed)
    with pytest.raises(ApplicationStoreError):
        with store.tx(readonly=True):
            _terminate(installed, store._connection)
            store._execute('SELECT 1').fetchone()
    assert store._broken is True
    assert _backend(store)  # the following request gets a fresh session


def test_operator_store_without_factory_keeps_failing_closed(installed):
    from agent_market.application_store_postgres import ApplicationStoreError
    store = _store(installed, factory=False)
    _terminate(installed, store._connection)
    for _ in range(2):
        with pytest.raises(ApplicationStoreError):
            _backend(store)


def test_unreachable_database_is_retried_at_most_once_per_backoff(installed, monkeypatch):
    from agent_market import application_store_postgres as module
    store = _store(installed)
    calls = []
    def down():
        calls.append(1)
        raise OSError('database starting up')
    store._connection_factory = down
    _terminate(installed, store._connection)
    for _ in range(3):
        with pytest.raises(module.ApplicationStoreError, match='connection_unusable'):
            _backend(store)
    assert len(calls) == 1
    store._connection_factory = lambda: _connect(installed)
    monkeypatch.setattr(module, 'RECONNECT_BACKOFF', 0)
    store._reconnect_after = 0
    assert _backend(store)


def test_pool_keeps_the_reconnected_session_and_closes_the_dead_one(installed):
    from agent_market.admin_postgres_pool import AdminReaderPool
    opened = []
    def create():
        store = _store(installed)
        opened.append(store._connection)
        return store, store._connection
    pool = AdminReaderPool(create, maximum=1, max_idle=1)
    with pool.lease_store() as store:
        _backend(store)
    original = opened[0]
    _terminate(installed, original)
    with pool.lease_store() as again:
        assert again is store and _backend(again)
    assert pool.idle[0][1] is store._connection is not original and original.closed
    pool.close()
    assert store._connection.closed


def test_runtime_factories_reapply_session_settings(installed, tmp_path):
    from agent_market.application_runtime import open_runtime_storage
    from scripts.rehearse_storage_adapter_postgres import PORT
    dsn, key = tmp_path / 'dsn', tmp_path / 'key'
    dsn.write_text('host=%s port=%s dbname=postgres user=postgres' % (installed['socket'], PORT))
    key.write_bytes(KEY)
    os.chmod(dsn, 0o600); os.chmod(key, 0o600)
    runtime = open_runtime_storage(':memory:', values={'APPLICATION_STORE_BACKEND': 'postgresql',
        'APPLICATION_POSTGRES_DSN_FILE': str(dsn), 'APPLICATION_WORKFLOW_KEY_FILE': str(key)},
        connector=lambda value: _connect(installed))
    try:
        store = runtime.store
        _terminate(installed, store._connection)
        assert _backend(store)
        with store._admin_read_pool.lease_store() as reader:
            _terminate(installed, reader._connection)
            with reader.tx(readonly=True):
                assert reader._execute('SHOW default_transaction_read_only').fetchone()[0] == 'on'
        with store._interactive_pool.lease_store() as session:
            _terminate(installed, session._connection)
            assert _backend(session)
    finally:
        runtime.close()
    assert store._connection.closed


def test_web_control_reconnects_but_an_owner_never_does(installed):
    import psycopg
    from agent_market.service_runtime import ServiceControl
    web = ServiceControl(_connect(installed), KEY, reopen=lambda: _connect(installed))
    _terminate(installed, web.connection)
    assert web.ready()
    owner = ServiceControl(_connect(installed), KEY, reopen=lambda: _connect(installed))
    owner.acquire_owner('jobs')
    assert owner.reopen is None
    _terminate(installed, owner.connection)
    with pytest.raises(psycopg.OperationalError):
        owner.heartbeat('jobs', {'running': True})
    web.close(); owner.close()


def test_worker_that_lost_ownership_exits_non_zero(monkeypatch):
    from agent_market import service_host
    def run(self):
        self.ownership_lost = True
    def close(self):
        raise RuntimeError('heartbeat on a dead session')
    monkeypatch.setattr(service_host.BackgroundLoop, 'run', run)
    monkeypatch.setattr(service_host.BackgroundLoop, 'close', close)
    @asynccontextmanager
    async def lifespan(_app):
        yield
    app = SimpleNamespace(router=SimpleNamespace(lifespan_context=lifespan))
    with pytest.raises(SystemExit) as exited:
        asyncio.run(service_host.serve_background(app, object(), 'jobs'))
    assert exited.value.code and 'ownership' in str(exited.value.code)


def test_execution_loop_defers_a_storage_timeout_instead_of_exiting(monkeypatch):
    import threading
    from agent_market import service_host
    from agent_market.application_store_postgres import ApplicationStoreError
    stop, rounds = threading.Event(), []
    def run_due():
        rounds.append(1)
        if len(rounds) == 1:
            raise ApplicationStoreError('statement_failed')  # e.g. lock_timeout behind a long writer
        stop.set()
    front = SimpleNamespace(workflows=SimpleNamespace(run_due=run_due))
    control = SimpleNamespace(expired_runs=lambda: ([], []), claim_private=lambda: None, claim_typed=lambda: None,
                              heartbeat=lambda *a: None)
    app = SimpleNamespace(state=SimpleNamespace(front=front))
    monkeypatch.setattr('agent_market.workspace_platform.platform_for', lambda _front: SimpleNamespace())
    loop = service_host.BackgroundLoop(app, control, 'execution', stop)
    monkeypatch.setattr(loop, 'heartbeat', lambda: None)
    clock = iter(range(10, 100000))  # advances on every read, so the deferred round comes due
    monkeypatch.setattr(service_host.time, 'monotonic', lambda: float(next(clock)))
    loop.run()
    assert len(rounds) == 2 and not loop.ownership_lost
    loop.pool.shutdown(wait=False)
