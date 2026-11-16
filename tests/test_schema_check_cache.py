"""PM 11-16 source review 1: a new session skips the column and constraint check when the catalog digest equals the
one this process validated; any schema change makes the full check run (and refuse) again."""
from pathlib import Path

import pytest


def test_a_session_on_an_unchanged_schema_skips_the_full_check_and_a_changed_one_is_refused(monkeypatch):
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
    from agent_market import application_store_postgres as aps
    from agent_market.storage_adapter import open_store
    binary = Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary / 'initdb').is_file():
        pytest.skip('PostgreSQL 18 fixture tools unavailable')
    monkeypatch.setattr(aps, '_SCHEMA_CHECKED', {})
    full = []
    original = aps.PostgresApplicationStore._validate_native_schema
    monkeypatch.setattr(aps.PostgresApplicationStore, '_validate_native_schema',
                        lambda self: (full.append(1), original(self))[1])
    with _private_cluster({name: str(binary / name) for name in ('initdb', 'pg_ctl')}) as cluster:
        connect = lambda: psycopg.connect(host=cluster['socket'], port=PORT, dbname='postgres', user='postgres', autocommit=True)
        with connect() as conn:
            conn.execute('CREATE EXTENSION vector')
            open_store('postgresql', connection=conn, initialize=True, workflow_key=b'a' * 32)
        assert len(full) == 1
        with connect() as conn:                                  # same schema: the digest answers, no full check
            open_store('postgresql', connection=conn, workflow_key=b'a' * 32)
        assert len(full) == 1
        monkeypatch.setattr(aps, 'SCHEMA_CHECK_CACHE_SECONDS', 0)   # off: every session checks everything again
        with connect() as conn:
            open_store('postgresql', connection=conn, workflow_key=b'a' * 32)
        assert len(full) == 2
        monkeypatch.setattr(aps, 'SCHEMA_CHECK_CACHE_SECONDS', 600)
        with connect() as conn:
            conn.execute('ALTER TABLE resources ADD COLUMN surprise text')
        with connect() as conn, pytest.raises(aps.ApplicationStoreError) as refused:
            open_store('postgresql', connection=conn, workflow_key=b'a' * 32)
        assert refused.value.code == 'schema_profile_mismatch' and len(full) == 3
