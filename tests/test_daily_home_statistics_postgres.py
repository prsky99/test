"""Daily snapshot persistence on an owned disposable PostgreSQL Unix socket."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.rehearse_storage_adapter_postgres import _driver, _tools, _private_cluster


def test_native_postgresql_daily_snapshot_and_shared_slot_winner(monkeypatch, record_property):
    # Only the specifically diagnosed host IPC exhaustion is an environment skip.
    from scripts import rehearse_storage_adapter_postgres as harness
    original_run = harness._run
    def owned_run(args, env, **kwargs):
        if Path(args[0]).name != "initdb":
            return original_run(args, env, **kwargs)
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=30)
        if result.returncode and "could not create shared memory segment" in result.stderr and "No space left on device" in result.stderr:
            pytest.skip("Host SysV shared memory slots exhausted; isolated PostgreSQL cannot initialize.")
        if result.returncode:
            raise harness.RehearsalError()
        return result
    monkeypatch.setattr(harness, "_run", owned_run)
    driver = _driver()
    child = r'''
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sys
import threading
import psycopg
from agent_market.storage_adapter import open_store
from agent_market.concierge.daily_statistics import DailyStatistics, KEY
from scripts.rehearse_storage_adapter_postgres import PORT
config=json.load(sys.stdin)
def connect():
    connection=psycopg.connect(host=config['socket'],hostaddr='',port=PORT,user='postgres',dbname='postgres',
        password='synthetic-unused-password',autocommit=True,connect_timeout=3,sslmode='disable',gssencmode='disable')
    assert connection.info.host==config['socket']
    return connection
store=open_store('postgresql',connection=connect(),initialize=True,workflow_key=b'k'*32)
try:
    daily=DailyStatistics(store)
    daily._refresh()
    first=daily.peek()
    assert first['cataloged']==first['reachable']==first['with_status_check']==0
    restarted=DailyStatistics(store,collect=lambda _:(_ for _ in ()).throw(AssertionError('repeat scan')))
    restarted._refresh()
    assert restarted.peek()==first
    later=datetime.now(timezone.utc)+timedelta(days=1)
    boundary=threading.Barrier(2)
    def publish(count):
        own=open_store('postgresql',connection=connect(),workflow_key=b'k'*32)
        try:
            def collect(_):
                boundary.wait(timeout=10)
                return dict(captured_at_utc=later.isoformat(),cataloged=count,reachable=count,
                            with_status_check=count,by_protocol=[{'kind':k,'n':count if k=='a2a' else 0} for k in ('a2a','mcp','x402')])
            local=DailyStatistics(own,clock=lambda:later,collect=collect)
            local._refresh()
            return local.peek()
        finally: own.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        values=list(pool.map(publish,(1,2)))
    assert values[0]==values[1]==store.get_meta(KEY)
    print(json.dumps({'native_aggregate':True,'restart_persistence':True,'shared_slot_winner':True,'postgresql_version':store._connection.info.server_version}))
finally: store.close()
'''
    with _private_cluster(_tools()) as cluster:
        environment = dict(cluster['environment'])
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])+os.pathsep+str(Path(driver.__file__).resolve().parent.parent)
        result = subprocess.run([sys.executable,'-B','-c',child],env=environment,
                                input=json.dumps({'socket':cluster['socket']}),text=True,
                                capture_output=True,timeout=60)
        assert result.returncode == 0, result.stderr[-4000:]
        evidence=json.loads(result.stdout)
        record_property('postgresql_version',evidence.pop('postgresql_version'))
        assert all(value is True for value in evidence.values())
