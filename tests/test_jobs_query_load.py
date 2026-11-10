"""Two jobs reads that passed the 5 s statement timeout under load (11-10, handed over by SRE)."""
from pathlib import Path

import pytest

from agent_market.gateway.store import Store


def _agent(n, host):
    return {'key': f'a2a:https://{host}/a{n}', 'source': 'fixture', 'kind': 'a2a', 'url': f'https://{host}/a{n}',
            'name': f'Agent {n}', 'description': 'Fixture agent', 'category': 'dev_tools', 'networks': [], 'details': {}}


def _healthy(store, ids, checked=None):
    with store.tx() as db:
        for rid in ids:
            db.execute("UPDATE resources SET health_status='healthy', cap_checked_at=? WHERE id=?", (checked, rid))


def test_due_pick_ranks_narrow_rows_and_returns_whole_listings(tmp_path):
    store = Store(str(tmp_path / 'due.sqlite3'))
    ids = [store.upsert_resource(_agent(n, 'one.example' if n < 3 else 'two.example'), now=10) for n in range(5)]
    _healthy(store, ids)
    due = store.due_for_capability(1000.0, 100.0, 10, per_host=2, kind='a2a')
    assert len(due) == 4  # two per host
    assert all(row['kind'] == 'a2a' and row['description'] == 'Fixture agent' and 'rn' not in row for row in due)
    _healthy(store, ids, checked=990.0)  # checked recently: nothing is due
    assert store.due_for_capability(1000.0, 100.0, 10, kind='a2a') == []


def test_due_pick_and_idle_cleanup_on_postgresql():
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from agent_market.storage_adapter import open_store
    from agent_market import postgres_ann
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            conn.execute('CREATE EXTENSION vector')
            store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'q' * 32)
            ids = [store.upsert_resource(_agent(n, 'pg.example'), now=10) for n in range(3)]
            with store.tx():
                for rid in ids:
                    store._execute("UPDATE resources SET health_status='healthy' WHERE id=%s", (rid,))
            due = store.due_for_capability(1000.0, 100.0, 10, per_host=2, kind='a2a')  # registered narrow SQL
            assert len(due) == 2 and {row['id'] for row in due} <= set(ids) and due[0]['name'].startswith('Agent')
            postgres_ann.install(store)
            calls = []
            original = store._execute
            store._execute = lambda sql, *a, **k: calls.append(sql) or original(sql, *a, **k)
            assert postgres_ann.cleanup(store) == 0  # nothing stale: rest
            searched = len(calls)
            assert postgres_ann.cleanup(store) == 0 and len(calls) == searched  # no second search while resting
            store._execute = original
            store.close()


def test_read_transactions_reuse_a_passing_gate_check_and_writes_always_check():
    # 11-11: a Chat answer opened ~75 transactions and re-read the same gate rows in each.
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from agent_market.storage_adapter import open_store
    from agent_market import application_store_postgres as aps
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            conn.execute('CREATE EXTENSION vector')
            store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'g' * 32)
            target = getattr(store, '_store', store)
            checks = []
            original = target._assert_deployment_gates
            target._assert_deployment_gates = lambda: checks.append(1) or original()
            target._read_gates_at = float('-inf')
            for _ in range(3):
                with store.tx(readonly=True):
                    store._execute('SELECT 1')
            assert len(checks) == 1  # reused within READ_GATE_SECONDS
            with store.tx():
                store._execute('SELECT 1')
            assert len(checks) == 2  # a write checks every time
            target._read_gates_at = float('-inf')
            with store.tx(readonly=True):
                assert tuple(store._execute("SELECT current_setting('transaction_read_only'), current_setting('statement_timeout')").fetchone()) == ('on', '5s')
            assert len(checks) == 3
            store.close()
