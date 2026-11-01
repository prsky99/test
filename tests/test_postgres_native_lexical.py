"""Native GIN reads page in PostgreSQL and bound only per-query compatibility work."""
import json,time
from pathlib import Path
import pytest


def test_native_gin_search_pages_security_and_query_projection(monkeypatch):
    import psycopg
    from scripts.rehearse_storage_adapter_postgres import _private_cluster,PORT
    from agent_market.storage_adapter import open_store
    from agent_market.postgres_lexical import install,available,DOCUMENT,QUERY
    from agent_market.application_store_postgres import _CATALOG
    from agent_market.gateway.rag import RagEngine
    from agent_market.legacy_vector_index import ModelDescriptor
    binary=Path('/opt/homebrew/opt/postgresql@18/bin')
    if not (binary/'initdb').is_file():pytest.skip('PostgreSQL 18 fixture tools unavailable')
    with _private_cluster({name:str(binary/name) for name in ('initdb','pg_ctl')}) as cluster:
        with psycopg.connect(host=cluster['socket'],port=PORT,dbname='postgres',user='postgres',autocommit=True) as conn:
            store=open_store('postgresql',connection=conn,initialize=True,workflow_key=b'l'*32)
            for i,name in enumerate(('Café market news','Weather alerts','Market research','Unrelated documentation')):
                rid=store.upsert_resource({'key':f'fixture:lexical:{i}','source':'fixture','kind':'mcp','name':name,'url':f'https://lexical{i}.example/mcp','description':name,'category':'research','networks':[],'details':{}})
                store.record_health(rid,'healthy',200,1,None,next_check_at=time.time()+100)
            assert install(store)['native_index'] and available(store)
            monkeypatch.setattr('agent_market.application_store_postgres.MAX_CORPUS_ROWS',1)
            # Whole-corpus projection must not be a hidden dependency of page reads.
            monkeypatch.setattr(store,'_fts',lambda *_:pytest.fail('Whole-corpus FTS projection used'))
            assert [r['id'] for r in store.search('cafe','research',None,[],['mcp'],limit=1)]==[1]
            engine=RagEngine(embed_model='synthetic-lexical')
            result=engine.hybrid_search(store._db,'market',query_embedding=None,query_descriptor=None)
            assert {r['id'] for r in result}=={1,3}
            assert store.idf(['market','absent'])['absent']>store.idf(['market'])['market']
            entry=next(e for e in _CATALOG['statements'] if e.get('adapter')=='explore-fts5-count-v1' and e['parameter_count']==1 and 'agent_test_reports' not in e['sqlite'] and 'trial_ok=1' not in e['sqlite'] and 'r.kind=' not in e['sqlite'])
            with store.tx(readonly=True):
                assert store._db.execute(entry['sqlite'],('"market"',)).fetchone()[0]==2
                store._execute('SET LOCAL enable_seqscan=off')
                explain=store._execute("EXPLAIN SELECT rowid FROM resources_fts f WHERE agentcon_search.lexical_document(f.name,f.description) @@ websearch_to_tsquery('simple','market')").fetchall()
                assert any('resources_fts_native_gin' in r[0] for r in explain)
            with store.tx():store._execute('UPDATE resources SET eval_security=%s WHERE id=%s',('quarantine',3))
            assert [r['id'] for r in engine.hybrid_search(store._db,'market',query_embedding=None,query_descriptor=None)]==[1]
            with store.tx(readonly=True):
                assert store._db.execute(entry['sqlite'],('"market"',)).fetchone()[0]==1
            # Removing the guard seam allows only the matched subset for Chat.
            monkeypatch.delattr(store,'_fts')
            with store.tx(readonly=True):
                local=store._fts('"weather"')
                assert local.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==1
            candidates=store.selection_candidates('"weather"','mcp',time.time()-3600)
            assert [row['id'] for row in candidates]==[2]
            store.upsert_resource({'key':'fixture:lexical:1','source':'fixture','kind':'mcp','name':'Volcano alerts','url':'https://lexical1.example/mcp','description':'Volcano alerts','category':'research','networks':[],'details':{}})
            assert store.search('weather','unmatched-category',None,[],['mcp'])==[]
            store.close()
