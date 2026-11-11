"""The task evidence tables live in their own schema; the attested public triggers stay five (11-11 draft)."""
from pathlib import Path

import pytest


def test_task_evidence_schema_migrates_and_rolls_back_without_touching_public_triggers():
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from scripts import task_evidence_schema as schema
    from agent_market.storage_adapter import open_store
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'e' * 32)
            result = schema.run(conn, schema.MIGRATE)
            assert result['after'] == {'tables': ['calls', 'rollup'], 'public_triggers': 5}
            assert schema.run(conn, schema.MIGRATE)['after']['tables'] == ['calls', 'rollup']  # repeatable
            with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as again:
                other = open_store('postgresql', connection=again, workflow_key=b'e' * 32)  # still attaches
                with other.tx():
                    pass
                other.close()
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute("INSERT INTO task_evidence.calls(resource_id,source,outcome,at) VALUES(1,'elsewhere','failed',1)")
            assert schema.run(conn, schema.ROLLBACK)['after'] == {'tables': [], 'public_triggers': 5}
            store.close()
