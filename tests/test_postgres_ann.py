"""Real pgvector retrieval preserves publication freshness and safety gates."""
from pathlib import Path
import math
import struct
import pytest

from agent_market.postgres_ann import vector_literal
from agent_market.legacy_vector_index import VectorError


@pytest.mark.parametrize('blob',[b'',b'x'*3071,struct.pack('<768f',*([float('nan')]+[0.]*767)),struct.pack('<768f',*([0.]*768))])
def test_invalid_vectors_are_refused(blob):
    with pytest.raises(VectorError):vector_literal(blob)


@pytest.mark.parametrize('lexical_first',[False,True])
def test_actual_pgvector_ann_publication_search_and_invalidation(monkeypatch,lexical_first):
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster,PORT
    from agent_market.storage_adapter import open_store
    from agent_market.legacy_vector_index import ModelDescriptor
    from agent_market.postgres_ann import install,available,nearest,cleanup
    from agent_market.postgres_lexical import install as install_lexical,available as lexical_available
    from agent_market.gateway.rag import RagEngine
    binary=Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary/'initdb').is_file():pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name:str(binary/name) for name in ('initdb','pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'],port=PORT,dbname='postgres',user='postgres',autocommit=True) as conn:
            conn.execute('CREATE EXTENSION vector')
            store=open_store('postgresql',connection=conn,initialize=True,workflow_key=b'a'*32)
            descriptor=ModelDescriptor('synthetic-ann',revision='fixture-v1')
            vector=[1.]+[0.]*767;blob=struct.pack('<768f',*vector)
            row={'key':'fixture:ann','source':'fixture','kind':'mcp','name':'Photonics research','url':'https://ann.example/mcp','description':'Synthetic photonics material','category':'research','networks':[],'details':{}}
            rid=store.upsert_resource(row,now=10)
            index=store._vector_index
            index.ensure_jobs(descriptor,limit=1,resource_ids=(rid,))
            claim=index.claim_batch(descriptor,limit=1,resource_ids=(rid,))[0]
            assert index.publish(claim,vector,descriptor)=='indexed'
            if lexical_first:install_lexical(store)
            assert install(store)['indexed']==1 and available(store)
            if not lexical_first:install_lexical(store)
            assert lexical_available(store)
            # ANN must bypass the compatibility full scan entirely.
            monkeypatch.setattr('agent_market.application_store_vector.cosine',lambda *_:pytest.fail('Exact scan used'))
            engine=RagEngine(embed_model='synthetic-ann',embed_revision='fixture-v1')
            found=engine.hybrid_search(store._db,'photonics',query_embedding=vector,query_descriptor=descriptor)
            assert found and found[0]['id']==rid and found[0]['dense_match']
            with store.tx(readonly=True):
                store._execute('SET LOCAL enable_seqscan=off')
                plan=store._execute('EXPLAIN SELECT resource_id FROM agentcon_search.embeddings ORDER BY embedding <=> %s::public.vector LIMIT 10',(vector_literal(blob),)).fetchall()
                assert any('embeddings_cosine_hnsw' in line[0] for line in plan)
            store.upsert_resource(row|{'description':'Changed source revision'},now=20)
            stale=engine.hybrid_search(store._db,'photonics',query_embedding=vector,query_descriptor=descriptor)
            assert not any(r['dense_match'] for r in stale)
            assert cleanup(store)==0  # kept while the listing waits to be embedded again (2026-11-09)
            index.ensure_jobs(descriptor,limit=1,resource_ids=(rid,))
            claim=index.claim_batch(descriptor,limit=1,resource_ids=(rid,))[0]
            assert index.publish(claim,vector,descriptor)=='indexed'
            with store.tx(readonly=True):assert nearest(store,blob,descriptor)==[rid]
            with store.tx():store._execute("UPDATE resources SET eval_security=%s WHERE id=%s",('quarantine',rid))
            assert engine.hybrid_search(store._db,'photonics',query_embedding=vector,query_descriptor=descriptor)==[]
            from concurrent.futures import ThreadPoolExecutor
            from agent_market.admin_postgres_pool import AdminReaderPool
            from agent_market.application_store_postgres import ApplicationStoreError
            def reader_factory():
                peer=psycopg.connect(host=cluster['socket'],port=PORT,dbname='postgres',user='postgres',autocommit=True)
                owned=open_store('postgresql',connection=peer,workflow_key=b'a'*32)
                peer.execute('SET default_transaction_read_only=on')
                return owned,peer
            pool=AdminReaderPool(reader_factory)
            def concurrent_read():
                with pool.reader() as db:
                    return db.execute('SELECT COUNT(*) FROM resources WHERE active=1').fetchone()[0]
            with ThreadPoolExecutor(1) as executor:
                with store.tx():
                    assert executor.submit(concurrent_read).result(timeout=2)==1
            with pytest.raises(ApplicationStoreError):
                with pool.reader() as db:
                    db._store._execute('UPDATE resources SET active=0')
            assert concurrent_read()==1
            pool.close()
            store.close()


def test_backfill_scan_runs_without_the_catalog_writer_lock(monkeypatch):
    # 2026-10-21: the full backfill scan held the writer lock for seconds and
    # Chat visitor writes failed on their 1s lock timeout (HTTP 503).
    import psycopg
    from contextlib import contextmanager
    from scripts.rehearse_storage_adapter_postgres import _private_cluster,PORT
    from agent_market.storage_adapter import open_store
    from agent_market.legacy_vector_index import ModelDescriptor
    from agent_market.application_store_postgres import WRITER_LOCK
    from agent_market.application_store_vector import PostgresVectorIndex
    binary=Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary/'initdb').is_file():pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name:str(binary/name) for name in ('initdb','pg_ctl')}) as cluster:
        connect=lambda:psycopg.connect(host=cluster['socket'],port=PORT,dbname='postgres',user='postgres',autocommit=True)
        with connect() as conn,connect() as other:
            store=open_store('postgresql',connection=conn,initialize=True,workflow_key=b'a'*32)
            for n in range(3):
                store.upsert_resource({'key':f'fixture:{n}','source':'fixture','kind':'mcp','name':f'Backfill {n}',
                    'url':f'https://backfill-{n}.example/mcp','description':'Synthetic','category':'research','networks':[],'details':{}},now=10)
            descriptor=ModelDescriptor('synthetic-backfill',revision='fixture-v1')
            # Listings whose earlier jobs finished are backfill candidates.
            with store.tx():store._execute("UPDATE legacy_vector_jobs SET status='superseded' WHERE status='pending'")
            original=PostgresVectorIndex.read_snapshot
            free=[]
            @contextmanager
            def observed(self):
                with original(self) as db:
                    free.append(other.execute('SELECT pg_try_advisory_lock(%s)',(WRITER_LOCK,)).fetchone()[0])
                    other.execute('SELECT pg_advisory_unlock_all()')
                    yield db
            monkeypatch.setattr(PostgresVectorIndex,'read_snapshot',observed)
            index=store._vector_index
            assert index.ensure_jobs(descriptor,limit=10)==3
            assert free==[True]
            assert index.ensure_jobs(descriptor,limit=10)==0


def test_cleanup_deletes_stale_rows_in_batches_the_store_accepts():
    from contextlib import contextmanager
    from types import SimpleNamespace
    from agent_market.postgres_ann import cleanup
    from agent_market.application_store_postgres import _values
    stale, deleted = list(range(1, 301)), []
    class Store:
        @contextmanager
        def tx(self, readonly=False):
            yield
        def _execute(self, sql, params=()):
            _values(params)  # the native store rejects more than 256 parameters
            if sql.lstrip().startswith('SELECT'):
                limit = int(sql.rsplit('LIMIT', 1)[1])
                return SimpleNamespace(fetchall=lambda: [(i,) for i in stale[:limit]])
            deleted.extend(params)
            for value in params:
                stale.remove(value)
            return SimpleNamespace(rowcount=len(params))
    store = Store()
    assert cleanup(store) == 256 and cleanup(store) == 44 and cleanup(store) == 0
    assert sorted(deleted) == list(range(1, 301))


def test_per_kind_halfvec_indexes_are_used_once_present_and_rolled_back_cleanly():
    """Draft D' (11-11): a kind-filtered search reads its own partial halfvec graph; code works before and after."""
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster,PORT
    from scripts import embeddings_kind_indexes as migration
    from agent_market.storage_adapter import open_store
    from agent_market.legacy_vector_index import ModelDescriptor
    from agent_market.postgres_ann import install,nearest,layout,kind_search
    binary=Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary/'initdb').is_file():pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name:str(binary/name) for name in ('initdb','pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'],port=PORT,dbname='postgres',user='postgres',autocommit=True) as conn:
            conn.execute('CREATE EXTENSION vector')
            store=open_store('postgresql',connection=conn,initialize=True,workflow_key=b'k'*32)
            descriptor=ModelDescriptor('synthetic-ann',revision='fixture-v1')
            index=store._vector_index
            ids={}
            for n,kind in enumerate(('mcp','a2a','mcp')):
                vector=[0.]*768;vector[n]=1.
                row={'key':'fixture:kind:%d'%n,'source':'fixture','kind':kind,'name':'Kind %d'%n,'url':'https://kind%d.example/%s'%(n,kind),
                     'description':'Synthetic','category':'research','networks':[],'details':{}}
                rid=store.upsert_resource(row,now=10);ids[n]=(rid,vector)
                index.ensure_jobs(descriptor,limit=1,resource_ids=(rid,))
                claim=index.claim_batch(descriptor,limit=1,resource_ids=(rid,))[0]
                assert index.publish(claim,vector,descriptor)=='indexed'
            install(store)
            with store.tx():store._execute("UPDATE resources SET health_status='healthy'")
            triggers=migration.status(conn)['public_triggers']
            blob=struct.pack('<768f',*ids[0][1])
            with store.tx(readonly=True):
                assert kind_search(store,'mcp') is None  # nothing built yet: the shared graph
                before=nearest(store,blob,descriptor,kind='mcp')
                before_any=nearest(store,blob,descriptor)  # no kind: the shared graph before D'
            steps=migration.migrate(conn,cover=True)
            assert steps['filled']==3
            state=migration.status(conn)
            assert state['kind_missing']==0 and state['public_triggers']==triggers
            assert all(state['indexes']['embeddings_half_'+k][0] for k in ('a2a','mcp','x402'))
            index._kind_layout=None
            with store.tx(readonly=True):
                assert layout(store)=={'kind_column':True,'kind_indexes':True}
                assert nearest(store,blob,descriptor,kind='mcp')==before
                # No kind: each kind's graph, merged by distance, gives the shared graph's answer (11-12 A3).
                assert nearest(store,blob,descriptor)==before_any and len(before_any)==3
                store._execute('SET LOCAL enable_seqscan=off')
                plan=store._execute("""EXPLAIN SELECT e.resource_id FROM agentcon_search.embeddings e WHERE e.kind='mcp'
                    ORDER BY e.embedding::public.halfvec(768) <=> %s::public.halfvec(768) LIMIT 10""",(vector_literal(blob),)).fetchall()
                assert any('embeddings_half_mcp' in line[0] for line in plan)
            # A new vector carries its kind.
            rid=ids[1][0]
            store.upsert_resource({'key':'fixture:kind:1','source':'fixture','kind':'a2a','name':'Kind 1 changed','url':'https://kind1.example/a2a',
                                   'description':'Changed','category':'research','networks':[],'details':{}},now=20)
            index.ensure_jobs(descriptor,limit=1,resource_ids=(rid,))
            claim=index.claim_batch(descriptor,limit=1,resource_ids=(rid,))[0]
            assert index.publish(claim,ids[1][1],descriptor)=='indexed'
            assert conn.execute('SELECT kind FROM agentcon_search.embeddings WHERE resource_id=%s',(rid,)).fetchone()[0]=='a2a'
            migration.rollback(conn,cover=True)
            index._kind_layout=None
            with store.tx(readonly=True):
                assert layout(store)['kind_column'] is False and nearest(store,blob,descriptor,kind='mcp')==before
            store.close()
