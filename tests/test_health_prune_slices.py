"""Health history pruning in time slices (PM 11-15): hourly, oldest first, one short transaction per slice, capped."""
import contextlib

from agent_market.collector import agent as collector_agent
from agent_market.gateway.store import Store


def _store(tmp_path, times):
    store = Store(str(tmp_path / 'c.sqlite3'))
    with store.tx() as db:
        db.executemany('INSERT INTO health_checks(resource_id,at,outcome,status_code,latency_ms) VALUES(?,?,?,?,?)',
                       [(1, t, 'up', 200, 10) for t in times])
    return store


def _count_tx(store):
    calls = []
    real = store.tx

    @contextlib.contextmanager
    def counted(*args, **kwargs):
        calls.append(1)
        with real(*args, **kwargs) as db:
            yield db
    store.tx = counted
    return calls


def test_prune_removes_only_older_rows_slice_by_slice(tmp_path):
    times = [1000 + 60 * i for i in range(120)]          # two hours, one row a minute
    store = _store(tmp_path, times)
    calls = _count_tx(store)
    before = 1000 + 3600                                   # the first hour is old
    assert store.prune_health(before, slice_seconds=600, max_slices=36) == 60
    assert len(calls) == 6                                 # six ten-minute slices, one transaction each
    left = [r['at'] for r in store.query('SELECT at FROM health_checks ORDER BY at')]
    assert left == [t for t in times if t >= before]
    assert store.prune_health(before) == 0                 # nothing older left: no transaction


def test_a_backlog_is_spread_over_calls_by_the_slice_cap(tmp_path):
    store = _store(tmp_path, [60 * i for i in range(600)])   # ten hours
    assert store.prune_health(60 * 600, slice_seconds=600, max_slices=3) == 30
    assert store.query('SELECT MIN(at) AS oldest FROM health_checks')[0]['oldest'] == 1800
    assert store.prune_health(60 * 600, slice_seconds=600, max_slices=1000) == 570


def test_sparse_history_skips_empty_gaps(tmp_path):
    store = _store(tmp_path, [0, 10, 100_000, 200_000])
    assert store.prune_health(150_000, slice_seconds=600, max_slices=2) == 3   # the gap costs no slice


def test_collector_prunes_hourly():
    assert collector_agent.PRUNE_SECONDS == 3600 and collector_agent.HISTORY_DAYS == 7


def test_postgresql_store_prunes_in_slices_with_registered_sql(monkeypatch):
    """The production path is the PostgreSQL store: both statements must be registered and behave the same."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    import pytest

    from scripts import rehearse_storage_adapter_postgres as harness
    original_run = harness._run

    def owned_run(args, env, **kwargs):
        if Path(args[0]).name != 'initdb':
            return original_run(args, env, **kwargs)
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
        if result.returncode and 'could not create shared memory segment' in result.stderr:
            pytest.skip('Host SysV shared memory slots exhausted; isolated PostgreSQL cannot initialize.')
        if result.returncode:
            raise harness.RehearsalError()
        return result
    monkeypatch.setattr(harness, '_run', owned_run)
    driver = harness._driver()
    child = r'''
import json, sys
import psycopg
from agent_market.storage_adapter import open_store
from scripts.rehearse_storage_adapter_postgres import PORT
config = json.load(sys.stdin)
def connect():
    return psycopg.connect(host=config['socket'], hostaddr='', port=PORT, user='postgres', dbname='postgres',
        password='synthetic-unused-password', autocommit=True, connect_timeout=3, sslmode='disable', gssencmode='disable')
store = open_store('postgresql', connection=connect(), initialize=True, workflow_key=b'k'*32)
try:
    raw = connect()
    raw.execute("INSERT INTO health_checks(resource_id,at,outcome,status_code,latency_ms) "
                "SELECT 1, 1000 + 60*g, 'up', 200, 10 FROM generate_series(0, 119) g")
    first = store.prune_health(1000 + 3600, slice_seconds=600, max_slices=2)
    rest = store.prune_health(1000 + 3600)
    left = raw.execute("SELECT COUNT(*), MIN(at) FROM health_checks").fetchone()
    print(json.dumps({'first': first, 'rest': rest, 'left': left[0], 'oldest': left[1]}))
    raw.close()
finally:
    store.close()
'''
    with harness._private_cluster(harness._tools()) as cluster:
        environment = dict(cluster['environment'])
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PYTHONPATH'] = (str(Path(__file__).resolve().parents[1]) + os.pathsep
                                     + str(Path(driver.__file__).resolve().parent.parent))
        result = subprocess.run([sys.executable, '-B', '-c', child], env=environment,
                                input=json.dumps({'socket': cluster['socket']}), text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr[-4000:]
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {'first': 20, 'rest': 40, 'left': 60, 'oldest': 4600.0}
