"""Exercise the native query against session-private PostgreSQL fixture tables only."""
import os,threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import pytest
from agent_market.legacy_vector_index import ModelDescriptor,PROFILE
from agent_market.application_store_vector import PostgresVectorIndex


@pytest.mark.skipif(os.environ.get('AGENTCON_TEMP_TABLE_POSTGRES_TEST')!='1',reason='Explicit session-private PostgreSQL fixture opt-in required.')
def test_postgres_backfill_exclusions_match_publication_and_job_fences():
    from psycopg.rows import dict_row
    from scripts.agentcon_config import read_settings
    from agent_market.application_runtime import _private_bytes,_connect
    settings=read_settings(Path(__file__).resolve().parents[1]/'gateway-data/agentcon.env')
    connection=_connect(_private_bytes(settings['APPLICATION_POSTGRES_DSN_FILE'],16384).decode().strip())
    desc=ModelDescriptor('session-private-backfill-fixture')
    try:
        # Unqualified names in this one connection resolve only to temporary
        # fixture tables. Existing public tables are neither read nor modified.
        connection.execute('SET search_path=pg_temp')
        for sql in (
            'CREATE TEMP TABLE resources(id bigint PRIMARY KEY,active integer,health_status text,eval_security text)',
            'CREATE TEMP TABLE legacy_vector_jobs(job_id bigint PRIMARY KEY,status text)',
            'CREATE TEMP TABLE legacy_vector_heads(resource_id bigint PRIMARY KEY,job_id bigint)',
            'CREATE TEMP TABLE legacy_vector_generations(resource_id bigint PRIMARY KEY,generation bigint)',
            'CREATE TEMP TABLE legacy_vector_provenance(resource_id bigint PRIMARY KEY,job_id bigint,generation bigint,descriptor_hash text)',
            'CREATE TEMP TABLE legacy_vector_control(id integer,profile text,descriptor_hash text)'):
            connection.execute(sql)
        connection.execute('INSERT INTO legacy_vector_control VALUES(1,%s,%s)',(PROFILE,desc.digest))
        for rid in range(1,12):connection.execute('INSERT INTO resources VALUES(%s,%s,%s,%s)',(rid,0 if rid==7 else 1,'retired'if rid==8 else'healthy','quarantine'if rid==9 else'ok'))
        for rid,status in ((1,'pending'),(2,'claimed'),(3,'failed'),(4,'indexed'),(5,'indexed'),(10,'indexed'),(11,'indexed'),(99,'indexed')):
            connection.execute('INSERT INTO legacy_vector_jobs VALUES(%s,%s)',(rid,status))
            if rid!=99:
                connection.execute('INSERT INTO legacy_vector_heads VALUES(%s,%s)',(rid,99 if rid==10 else rid))
                connection.execute('INSERT INTO legacy_vector_generations VALUES(%s,1)',(rid,))
        for rid in (4,5,10,11):connection.execute('INSERT INTO legacy_vector_provenance VALUES(%s,%s,%s,%s)',(rid,rid,0 if rid==5 else 1,'other-model'if rid==11 else desc.digest))
        assert connection.execute("SELECT 'resources'::regclass::oid=(SELECT oid FROM pg_class WHERE relname='resources' AND relnamespace=pg_my_temp_schema())").fetchone()[0]
        class DB:
            @property
            def in_transaction(self):return connection.info.transaction_status!=0
            def execute(self,sql,params=()):return connection.execute(sql,params)
        db=DB()
        @contextmanager
        def tx(**kwargs):
            with connection.transaction():
                connection.execute("SET LOCAL statement_timeout='5000ms'")
                connection.execute('SET TRANSACTION READ ONLY')
                yield db
        def execute(sql,params=()):return connection.cursor(row_factory=dict_row).execute(sql,params)
        index=PostgresVectorIndex.__new__(PostgresVectorIndex);index.store=SimpleNamespace(tx=tx,_execute=execute);index.db=db;index.lock=threading.RLock();index.broken=False;index._reading=False
        # New publication, stale generation, replaced head and wrong model need
        # work. In-flight/failed/current publications and ineligible rows do not.
        assert index._backfill_candidates(desc,50)==[5,6,10,11]
        assert index._backfill_candidates(desc,1)==[5]
    finally:connection.close()
