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
            ranked = []
            rank = store._collector_rows
            store._collector_rows = lambda sql, *a: (ranked.append(sql) if 'ROW_NUMBER' in sql else None) or rank(sql, *a)
            store.__dict__.pop('_cap_batches', None)
            first = store.due_for_capability(1000.0, 100.0, 1, per_host=2, kind='a2a')
            second = store.due_for_capability(1001.0, 100.0, 1, per_host=2, kind='a2a')
            assert len(first) == len(second) == 1 and first[0]['id'] != second[0]['id'] and len(ranked) == 1
            # both ranked ids are taken and that ranking was complete (2 < its LIMIT): no new ranking until it
            # ages (11-11 22h: A2A re-ranked 152k rows 19 times a minute to get 2 ids each time)
            assert store.due_for_capability(1002.0, 100.0, 1, per_host=2, kind='a2a') == [] and len(ranked) == 1
            from agent_market import application_store_collector as collector_module
            later = 1001.0 + collector_module.CAP_BATCH_SECONDS + 1
            assert len(store.due_for_capability(later, 100.0, 1, per_host=2, kind='a2a')) == 1 and len(ranked) == 2
            store._collector_rows = rank
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


def test_due_pick_ranks_once_per_batch_hands_out_each_id_once_and_expires(tmp_path, monkeypatch):
    """11-11: the ranking touched ~104k blocks per call, 23 calls a minute, for a few rows each."""
    from agent_market.gateway import store as module
    monkeypatch.setattr(module, 'CAP_BATCH', 6)
    store = Store(str(tmp_path / 'batch.sqlite3'))
    ids = [store.upsert_resource(_agent(n, f'h{n % 4}.example'), now=10) for n in range(12)]
    _healthy(store, ids)
    ranked = []
    real = store.query
    monkeypatch.setattr(store, 'query', lambda sql, params=(): (ranked.append(1) if 'ROW_NUMBER' in sql else None) or real(sql, params))
    first = store.due_for_capability(1000.0, 100.0, 2, per_host=2, kind='a2a')
    second = store.due_for_capability(1010.0, 100.0, 2, per_host=2, kind='a2a')
    assert len(ranked) == 1 and len(first) == len(second) == 2
    assert not {r['id'] for r in first} & {r['id'] for r in second}          # never handed out twice
    with store.tx() as db:                                                      # surveyed meanwhile: skipped
        db.execute("UPDATE resources SET cap_checked_at=1015 WHERE id IN (SELECT id FROM resources ORDER BY id)")
    assert store.due_for_capability(1020.0, 100.0, 2, per_host=2, kind='a2a') == []
    _healthy(store, ids)
    store.due_for_capability(1020.0 + module.CAP_BATCH_SECONDS + 1, 100.0, 2, per_host=2, kind='a2a')
    assert len(ranked) == 3                                                     # empty batch, then expiry: ranked again


def test_health_due_pick_on_postgresql_ranks_narrow_ids_once_per_batch():
    """11-11: the health loop's per-host ranking sorted whole rows (~13 MB to disk per call, ~17 calls a minute)."""
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from agent_market.storage_adapter import open_store
    from agent_market import application_store_collector as module
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            conn.execute('CREATE EXTENSION vector')
            store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'q' * 32)
            ids = [store.upsert_resource(_agent(n, 'one.example' if n < 4 else 'two.example'), now=10) for n in range(5)]
            ranked = []
            rank = store._collector_rows
            store._collector_rows = lambda sql, *a: (ranked.append(sql) if 'ROW_NUMBER' in sql else None) or rank(sql, *a)
            first = store.due_for_check(1000.0, 2, per_host=2, kind='a2a')
            second = store.due_for_check(1001.0, 2, per_host=2, kind='a2a')
            assert len(ranked) == 1 and ranked[0].startswith('SELECT id FROM')            # one narrow ranking
            assert len(first) == 2 and len(second) == 1                                   # 2 per host: 3 ids in all
            assert {r['id'] for r in first + second} <= set(ids) and len({r['id'] for r in first + second}) == 3
            assert all(r['name'].startswith('Agent') and 'rn' not in r for r in first + second)
            # the complete ranking is handed out: nothing more until it ages, then a new ranking; a row
            # postponed meanwhile is no longer handed out
            assert store.due_for_check(1002.0, 10, per_host=2, kind='a2a') == [] and len(ranked) == 1
            store.postpone([first[0]['id']], 5000.0)
            again = store.due_for_check(1002.0 + module.CHECK_BATCH_SECONDS + 1, 10, per_host=2, kind='a2a')
            assert len(ranked) == 2 and again and first[0]['id'] not in {r['id'] for r in again}
            # a batch row that stopped being due before it was taken is dropped on the re-read
            store.__dict__.pop('_cap_batches', None)
            store._collector_rows = rank
            taken = store.due_for_check(1003.0, 1, per_host=2, kind=['a2a'])
            batch = list(store.__dict__['_cap_batches'][('check', ('a2a',), 2)][1])
            assert len(taken) == 1 and batch                             # the rest wait in the batch
            store.postpone(ids, 5000.0)                                   # nothing is due any more
            assert store.due_for_check(1004.0, 10, per_host=2, kind=['a2a']) == []
            # an old batch is ranked again: once the postponement passes, rows are due again
            assert len(store.due_for_check(5001.0 + module.CHECK_BATCH_SECONDS, 10, per_host=2, kind=['a2a'])) == 3
            store.close()
