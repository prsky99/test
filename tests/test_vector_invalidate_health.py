"""A health change keeps a listing's vector current once the new trigger body runs (11-11)."""
from pathlib import Path
import struct

import pytest


def test_health_change_keeps_the_vector_and_both_bodies_attach():
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from scripts import vector_invalidate_health as change
    from agent_market.storage_adapter import open_store
    from agent_market.legacy_vector_index import ModelDescriptor
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as conn:
            store = open_store('postgresql', connection=conn, initialize=True, workflow_key=b'h' * 32)
            descriptor = ModelDescriptor('synthetic-health', revision='fixture-v1')
            row = {'key': 'fixture:health', 'source': 'fixture', 'kind': 'mcp', 'name': 'Health fixture',
                   'url': 'https://health.example/mcp', 'description': 'Synthetic', 'category': 'dev_tools',
                   'networks': [], 'details': {}}
            rid = store.upsert_resource(row, now=10)
            index = store._vector_index
            index.ensure_jobs(descriptor, limit=1, resource_ids=(rid,))
            claim = index.claim_batch(descriptor, limit=1, resource_ids=(rid,))[0]
            assert index.publish(claim, [1.0] + [0.0] * 767, descriptor) == 'indexed'
            assert change.status(conn) == {'body': 'health_invalidates', 'public_triggers': 5}
            assert change.change(conn, False)['after'] == {'body': 'health_kept', 'public_triggers': 5}
            # A new connection still attaches (exact prosrc check accepts the new body).
            with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as again:
                other = open_store('postgresql', connection=again, workflow_key=b'h' * 32)
                with other.tx():
                    pass
                other.close()
            with store.tx():
                store._execute("UPDATE resources SET health_status='degraded' WHERE id=%s", (rid,))
            assert index.current_ids([rid], descriptor) == {rid}  # the vector stays current
            with store.tx():
                store._execute("UPDATE resources SET description='Changed text' WHERE id=%s", (rid,))
            assert index.current_ids([rid], descriptor) == set()  # changed text still invalidates
            # Exactly the two bodies attach (PM 11-11): any third body, even one changed space, is refused.
            from agent_market.application_store_postgres import ApplicationStoreError
            third = change.definition(False).replace('BEGIN IF TG_OP', 'BEGIN  IF TG_OP', 1)
            assert third != change.definition(False)
            conn.execute(third)
            assert change.status(conn)['body'] == 'unknown'
            with psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True) as again:
                with pytest.raises(ApplicationStoreError):
                    refused = open_store('postgresql', connection=again, workflow_key=b'h' * 32)
                    with refused.tx():
                        pass
            conn.execute(change.definition(False))
            assert change.change(conn, True)['after'] == {'body': 'health_invalidates', 'public_triggers': 5}
            with store.tx():
                pass
            store.close()
