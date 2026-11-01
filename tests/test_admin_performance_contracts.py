"""Concurrency and query shape checks, without touching the operating database."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from agent_market.gateway.store import Store
from agent_market.gateway.dashboard import dashboard_router
from agent_market.gateway import admin_auth
from agent_market.report_time import report_timestamp
from agent_market.application_store_migration import _cell
from agent_market.admin_postgres_pool import AdminReaderPool


def test_session_authentication_does_not_wait_for_collector_write_lock(tmp_path):
    path=str(tmp_path/'isolated.sqlite3');store=Store(path)
    with store.tx() as db:
        token=admin_auth.create_session(db,1,'sadmin','superadmin','Fixture')
    app=FastAPI();app.include_router(dashboard_router(store,path,'synthetic-system-token',None,ssl_manager=Mock(get_status=lambda:{})))
    with TestClient(app) as client, ThreadPoolExecutor(1) as pool:
        with store.tx():
            response=pool.submit(client.get,'/admin/api/auth/me',headers={'X-Dashboard':'1','Authorization':'Bearer '+token}).result(timeout=2)
            assert response.status_code==200
        with store.tx() as db:admin_auth.delete_session(db,token)
        assert client.get('/admin/api/auth/me',headers={'X-Dashboard':'1','Authorization':'Bearer '+token}).status_code==401
    store._db.close()


def test_status_changes_use_resource_index_for_vector_jobs():
    store=Store()
    plan=[row[3] for row in store.query("EXPLAIN QUERY PLAN UPDATE legacy_vector_jobs SET status='superseded' WHERE resource_id=? AND status IN ('pending','claimed')",(1,))]
    assert any('legacy_vector_jobs_resource_status' in item and 'SEARCH' in item for item in plan)
    store._db.close()


def test_report_dates_preserve_offsets_and_historical_sqlite_utc():
    assert report_timestamp('2026-10-15T16:18:00Z')==report_timestamp('2026-10-16T01:18:00+09:00')
    assert _cell('2026-10-15 16:18:00','REAL','agent_test_reports','created_at')==report_timestamp('2026-10-15T16:18:00Z')
    for value in (True,float('nan'),'2026-10-15 16:18:00','unexpected'):
        with pytest.raises(ValueError):report_timestamp(value)


def test_reader_pool_reuses_readonly_sessions_and_refuses_undrained_close():
    made=[]
    class Reader:
        _broken=False
        @contextmanager
        def tx(self,*,readonly=False):
            assert readonly
            yield 'isolated-read-session'
        def close(self):self.closed=True
    def factory():
        reader=Reader();conn=SimpleNamespace(closed=False)
        conn.close=lambda:setattr(conn,'closed',True)
        made.append((reader,conn));return reader,conn
    pool=AdminReaderPool(factory,maximum=1)
    with pool.reader() as db:
        assert db=='isolated-read-session'
        with pytest.raises(RuntimeError,match='not_drained'):pool.close()
    with pool.reader():pass
    assert len(made)==1
    pool.close()
    assert made[0][1].closed
    with pytest.raises(RuntimeError,match='closed'):
        with pool.reader():pass


def test_burst_pool_closes_surplus_idle_connections_after_errors():
    import threading
    import time
    made=[];lock=threading.Lock();first_wave=threading.Barrier(4)
    def factory():
        store=SimpleNamespace(_broken=False,closed=False)
        store.close=lambda:setattr(store,'closed',True)
        conn=SimpleNamespace(closed=False)
        conn.close=lambda:setattr(conn,'closed',True)
        with lock:made.append((store,conn))
        return store,conn
    pool=AdminReaderPool(factory,maximum=4,wait_seconds=2,max_idle=1)
    def request(number):
        try:
            with pool.lease_store():
                if number<4:first_wave.wait(timeout=2)
                time.sleep(.02)
                if number%3==0:raise ValueError('Isolated request failure')
        except ValueError:pass
    with ThreadPoolExecutor(16) as workers:list(workers.map(request,range(16)))
    assert pool.total==1 and pool.leased==0 and len(pool.idle)==1
    assert sum(not conn.closed for _,conn in made)==1
    assert all(store.closed==conn.closed for store,conn in made)
    pool.close()
    assert all(conn.closed for _,conn in made)
