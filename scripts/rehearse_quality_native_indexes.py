"""Acceptance on private PG18 with real GIN/HNSW; no operator DSN or SQLite."""
import argparse
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import psycopg
from scripts.rehearse_storage_adapter_postgres import _private_cluster, PORT
from scripts.evaluate_search_workflow_quality import evaluate
from agent_market.storage_adapter import open_store
from agent_market.postgres_lexical import install as install_lexical
from agent_market.postgres_ann import install as install_ann, vector_literal
from agent_market.legacy_vector_index import ModelDescriptor
from agent_market.concierge.discovery import candidates


def run():
    binary=Path('/opt/homebrew/opt/postgresql@18/bin')
    tools={name:str(binary/name)for name in ('initdb','pg_ctl')}
    with _private_cluster(tools) as cluster:
        root=Path(cluster['root'])
        with psycopg.connect(host=cluster['socket'],port=PORT,dbname='postgres',user='postgres',autocommit=True) as pg:
            pg.execute('CREATE EXTENSION vector')
            store=open_store('postgresql',connection=pg,initialize=True,workflow_key=b'q'*32)
            try:
                install_lexical(store)
                assert store._native_lexical is True
                result=evaluate(store)
                assert result['passed']==result['runs']
                rid=result['gold_resources']['weather']
                descriptor=ModelDescriptor('synthetic-quality-ann',revision='fixture-v1')
                vector=[1.]+[0.]*767
                index=store._vector_index
                index.ensure_jobs(descriptor,limit=1,resource_ids=(rid,))
                claim=index.claim_batch(descriptor,limit=1,resource_ids=(rid,))[0]
                assert index.publish(claim,vector,descriptor)=='indexed'
                install_ann(store)
                engine=SimpleNamespace(embeddings_enabled=True,model_descriptor=lambda:descriptor,discovery_embedding=lambda _:vector)
                found=candidates(store,engine,'Weather forecast',kind='mcp',category='general')
                assert any(row['id']==rid and row['dense_match']for row in found)
                assert index._quality_iterative_supported is True
                with store.tx(readonly=True):
                    assert store._execute("SELECT current_setting('hnsw.iterative_scan')").fetchone()[0]=='off'
                with pg.transaction():
                    pg.execute('SET LOCAL enable_seqscan=off')
                    gin=pg.execute("EXPLAIN SELECT rowid FROM resources_fts WHERE agentcon_search.lexical_document(name,description) @@ plainto_tsquery('simple','weather')").fetchall()
                    ann=pg.execute('EXPLAIN SELECT resource_id FROM agentcon_search.embeddings ORDER BY embedding <=> %s::vector LIMIT 10',(vector_literal(struct.pack('<768f',*vector)),)).fetchall()
                assert any('resources_fts_native_gin'in line[0]for line in gin)
                assert any('embeddings_cosine_hnsw'in line[0]for line in ann)
                store.upsert_resource({'key':'quality-fixture:weather','source':'synthetic-quality-fixture',
                    'kind':'mcp','url':'https://quality-weather.example/mcp','name':'Quality weather',
                    'description':'Changed weather forecast source','category':'general','price_usdc':0,'details':{}})
                stale=candidates(store,engine,'Weather forecast',kind='mcp')
                assert not any(row['id']==rid and row['dense_match']for row in stale)
                result['native_index_checks']={'gin_plan':True,'hnsw_plan':True,'filtered_iterative_scan':True,
                    'settings_transaction_local':True,'stale_dense_rejected':True}
                result['retrieval_backend']='PostgreSQL GIN and pgvector HNSW'
                result['reference_sqlite_used']=False
                result['operating_application_data_writes']=0
            finally:store.close()
    assert not root.exists()
    result['private_cluster_removed']=True
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=run()
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k]for k in ('runs','passed','retrieval_backend','native_index_checks','private_cluster_removed')}))


if __name__=='__main__':main()
