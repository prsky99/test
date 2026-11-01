"""Representative isolated HTML timing; never reads an operator database."""
import gzip
import json
import re
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent_market.capability_registry import Registry
from agent_market.concierge.front import Front, create_front_app, clear_front_caches, RedisHub
from agent_market.gateway.store import Store
from tests.report_fixtures import execution_report


def run():
    with tempfile.TemporaryDirectory(prefix='a2a-html-representative-') as folder:
        store=Store(str(Path(folder)/'synthetic.sqlite3'))
        now=time.time()
        count=115009
        # This benchmark measures reads of an existing large catalog, not the
        # ingestion/event fan-out of 115k inserts. Disable only the disposable
        # fixture's triggers while seeding, then restore their exact definitions.
        triggers=store.query("SELECT name,sql FROM sqlite_master WHERE type='trigger'")
        with store.tx() as db:
            for trigger in triggers:
                assert re.fullmatch('[a-zA-Z_][a-zA-Z0-9_]*',trigger['name'])
                db.execute('DROP TRIGGER "'+trigger['name']+'"')
            db.executemany('''INSERT INTO resources(key,source,kind,url,name,description,category,
                networks,details,first_seen,last_seen,health_status,active,auth_observed)
                VALUES(?,?,?,?,?,?,?,'[]','{}',?,?,'healthy',1,0)''',
                ((f'synthetic:{i}','synthetic',('mcp','a2a','x402')[i%3],f'https://synthetic-{i}.example.invalid/api',
                  f'Synthetic agent {i}','Public information retrieval benchmark','news_media',now,now)
                 for i in range(count)))
            db.execute('INSERT INTO resources_fts(rowid,name,description) SELECT id,name,description FROM resources')
            for trigger in triggers:db.execute(trigger['sql'])
        print('Synthetic catalog seeded: 115009 resources.',flush=True)
        registry=Registry(store)
        for rid in range(1,1001):
            version=registry.current(rid)
            registry.record(version,scope='execution',outcome='succeeded',started=now-10,finished=now-9)
        for rid in range(1,201):
            execution_report(store,rid,now-9,title=f'Synthetic report {rid}',slug=f'synthetic-report-{rid}')
        print('Synthetic evidence and report fixtures seeded.',flush=True)
        previous=RedisHub.get_instance
        RedisHub.get_instance=staticmethod(lambda:SimpleNamespace(is_available=lambda:False))
        try:
            clear_front_caches()
            front=Front(store)
            query=store.query
            query_stats=[]
            def measured(sql,params=()):
                started=time.monotonic()
                try:return query(sql,params)
                finally:query_stats.append((sql.lstrip().split(None,1)[0],(time.monotonic()-started)*1000))
            store.query=measured
            with TestClient(create_front_app(front)) as client:
                elapsed=[];wire=[]
                for _ in range(2):
                    started=time.monotonic()
                    response=client.get('/',headers={'Accept':'text/html'})
                    elapsed.append(round((time.monotonic()-started)*1000,3))
                    assert response.status_code==200
                    wire.append(len(gzip.compress(response.content)))
                    job=front.html_bootstrap.job
                    if job:assert job['done'].wait(45),'Isolated catalog build exceeded the diagnostic deadline.'
                assert all(ms<2000 for ms in elapsed),elapsed
                assert all(n<125000 for n in wire),wire
                result={'profile':'isolated-representative-html-v1','resources':count,
                    'execution_evidence_rows':1000,'canonical_reports':200,
                    'html_request_ms':elapsed,'gzip_bytes':wire,
                    'latest_snapshot_stage_ms':front._bootstrap_timings_ms,
                    'query_calls':len(query_stats),'max_query_ms':round(max(v for _,v in query_stats),3),
                    'provider_calls':0,'operating_data_used':False,'operating_SLA_acceptance':False,
                    'collector_contention_modeled':False}
                return result
        finally:
            RedisHub.get_instance=previous
            store._db.close()


if __name__=='__main__':
    result=run()
    output=Path('reports/advancement-completion-2026-10-19/representative-html.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
