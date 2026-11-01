"""Repeatable synthetic catalog measurements on owned SQLite and Unix PG only.

No operating path/address argument, public HTTP provider, production workload,
latency SLA, RPO/RTO or HA certification is inferred from these measurements.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROWS = 5000
PROFILE = 'platform-catalog-sandbox-measurement-v1'


def _measure(store):
    from agent_market.infra.redis_hub import RedisHub
    previous = RedisHub.__dict__['get_instance']
    RedisHub.get_instance = staticmethod(lambda: SimpleNamespace(is_available=lambda: False))
    front = None
    try:
        from agent_market.concierge import front
        return _measure_catalog(store, front)
    finally:
        if front is not None:
            front.clear_front_caches()
        RedisHub.get_instance = previous


def _measure_catalog(store, front):
    front.clear_front_caches()
    records = [{'key':'sandbox-benchmark:'+str(i),'source':'synthetic-benchmark','kind':('mcp','a2a','x402')[i%3],
        'url':'https://bench-'+str(i%24)+'.invalid/task/'+str(i),'name':'Synthetic documentation '+str(i),
        'description':'Synthetic documentation and agent discovery benchmark. No external provider.',
        'category':'research','networks':[],'details':{}} for i in range(ROWS)]
    start=time.perf_counter();store.upsert_page(records,now=int(time.time())-7200);ingest=time.perf_counter()-start
    # Prepare public-eligibility fixture fields in bounded transactions. This
    # preparation is outside measured ingestion, and does not relax timeouts.
    start = time.perf_counter()
    for lower in range(1, ROWS + 1, 100):
        # This fixed fixture update is not a production query family.
        with store.tx() as db:
            if hasattr(store, '_execute'):
                store._execute("UPDATE resources SET health_status='healthy',eval_security='ok',eval_grade='A',eval_score=85,price_usdc=0.01 WHERE id>=%s AND id<%s", (lower, lower + 100))
            else:
                db.execute("UPDATE resources SET health_status='healthy',eval_security='ok',eval_grade='A',eval_score=85,price_usdc=0.01 WHERE id>=? AND id<?", (lower, lower + 100))
    preparation = time.perf_counter() - start
    durations=[]
    for _ in range(5):
        start=time.perf_counter();result=store.search('documentation',None,None,[],['mcp','a2a','x402'],limit=20)
        durations.append(time.perf_counter()-start)
        if not result or len(result)>20:raise AssertionError('Synthetic search invariant failed.')
    surfaces={}
    for name,read in [('explore',lambda:front.get_front_explore(store,'documentation',None,None,True,False,12)),
                      ('insights',lambda:front.get_front_insights(store))]:
        start=time.perf_counter();value=read();cold=time.perf_counter()-start
        start=time.perf_counter();again=read();warm=time.perf_counter()-start
        if not value or not again:raise AssertionError('Synthetic projection invariant failed.')
        surfaces[name]={'cold_seconds':round(cold,6),'warm_seconds':round(warm,6)}
    return {'rows':ROWS,'ingest_seconds':round(ingest,6),'fixture_preparation_seconds':round(preparation,6),'search_samples':len(durations),
        'search_cold_seconds':round(durations[0],6),'search_median_seconds':round(statistics.median(durations),6),
        'search_max_seconds':round(max(durations),6),'projections':surfaces,'synthetic':True,
        'production_capacity_measured':False,'production_latency_sla':False}


def _worker():
    from scripts.rehearse_storage_adapter_postgres import _driver,PORT
    cluster=json.loads(sys.stdin.read(4096));root=Path(cluster['root']);socket_path=Path(cluster['socket'])
    if root.parent!=Path('/private/tmp') or not root.name.startswith('a2a-adapter-pg-') or socket_path!=root/'socket':
        raise AssertionError('Owned cluster required.')
    forbidden=[]
    original=socket.socket
    class GuardedSocket(original):
        def connect(self,address):
            if self.family in (socket.AF_INET,socket.AF_INET6):
                forbidden.append('unexpected_tcp');raise OSError('No external/operating connection in sandbox.')
            return super().connect(address)
        def connect_ex(self,address):
            if self.family in (socket.AF_INET,socket.AF_INET6):
                forbidden.append('unexpected_tcp');raise OSError('No external/operating connection in sandbox.')
            return super().connect_ex(address)
    socket.socket=GuardedSocket
    from agent_market.storage_adapter import open_store
    driver=_driver();connection=driver.connect(host=str(socket_path),port=PORT,dbname='postgres',user='postgres',autocommit=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('listen_addresses'),inet_server_addr(),inet_client_addr(),current_setting('data_directory')")
        if cursor.fetchone()!=('',None,None,str(root/'data')):raise AssertionError('Private Unix transport required.')
    store=open_store('postgresql',connection=connection,initialize=True,workflow_key=b'b'*32)
    try:value=_measure(store)
    finally:store.close();connection.close()
    if forbidden:raise AssertionError('Unexpected network attempts.')
    print(json.dumps(value,sort_keys=True,allow_nan=False))


def benchmark():
    from agent_market.gateway.store import Store
    from scripts.rehearse_storage_adapter_postgres import _private_cluster,_tools,_driver
    with tempfile.TemporaryDirectory(prefix='a2a-benchmark-sqlite-',dir='/private/tmp') as folder:
        store=Store(str(Path(folder)/'synthetic.sqlite3'))
        try:sqlite_result=_measure(store)
        finally:store._db.close()
    driver=_driver()
    with _private_cluster(_tools()) as cluster:
        environment=dict(cluster['environment']);environment.update(PYTHONDONTWRITEBYTECODE='1',
            PYTHONPATH=str(Path(__file__).resolve().parents[1])+os.pathsep+str(Path(driver.__file__).resolve().parent.parent))
        process=subprocess.run([sys.executable,'-B','-c','from scripts.benchmark_platform_sandbox import _worker; _worker()'],
            input=json.dumps({'root':cluster['root'],'socket':cluster['socket']}),env=environment,
            text=True,capture_output=True,timeout=180)
        if process.returncode:raise RuntimeError('Synthetic benchmark failed: '+process.stderr[-2500:])
        pg_result=json.loads(process.stdout)
    return {'profile':PROFILE,'sqlite':sqlite_result,'postgresql':pg_result,'operating_server_actions':0,
        'operating_database_writes':0,'external_provider_calls':0,'temporary_cluster_removed':True,
        'capacity_acceptance':False,'dr_acceptance':False,'ha_acceptance':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);parser.add_argument('--run',action='store_true');args=parser.parse_args()
    if not args.run:parser.error('--run is required')
    print(json.dumps(benchmark(),sort_keys=True,allow_nan=False))


if __name__=='__main__':main()
